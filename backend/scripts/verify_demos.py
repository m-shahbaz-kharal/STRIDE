"""
Headless verification driver for the seeded ``Demo · NN`` graphs.

Loads every demo from Postgres, converts the saved frontend (ReactFlow) shape
into the executor's ``{nodes, links}`` shape using the same logic as
``frontend/src/App.tsx::buildGraphPayload`` + ``GraphBuilder``, and pipes the
result through ``GraphExecutor`` — the same code path the WebSocket handler
hits at runtime.

Demo 08 is special: it's intentionally infinite. We launch it on a background
thread, sleep ~2s, call ``GraphExecutor.cancel_execution(...)``, and assert
the executor terminates promptly. This is the end-to-end check for the
Phase 1 cancel fix.

Usage::

    cd backend
    uv run python scripts/verify_demos.py

The script never writes to the DB. Output is plain text so it's easy to
embed in a verification report.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Make sure ``app`` is importable.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_THIS_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.db import SessionLocal  # noqa: E402
from app.models import Graph, User  # noqa: E402
from app.nodes import list_node_definitions  # noqa: E402
from app.runner import GraphExecutor, GraphExecutionError  # noqa: E402
from app.execution import NodeStatus  # noqa: E402

SEED_USER_EMAIL = os.getenv("SEED_USER_EMAIL", "test@test.com")
DEMO_NAME_PREFIX = "Demo · "

# Per-demo timeouts (seconds). Demos that download ML weights need a generous
# first-run budget; demo 10 is trivial; demo 08 is the cancel-test special.
DEFAULT_TIMEOUT_S = 180.0
DEMO_10_TIMEOUT_S = 5.0
DEMO_08_RUN_BEFORE_CANCEL_S = 2.0
DEMO_08_CANCEL_BUDGET_S = 5.0


def _load_registry() -> Dict[str, Dict[str, Any]]:
    return {d["node_type"]: d for d in list_node_definitions()}


REGISTRY = _load_registry()


def _port_kind(node_type: str, port_name: str, role: str) -> str:
    """Return the ``TypeDescriptor.kind`` string for a port, or 'any'."""
    spec = REGISTRY.get(node_type) or {}
    map_key = "output_port_types" if role == "source" else "input_port_types"
    pmap = spec.get(map_key) or {}
    val = pmap.get(port_name)
    if val is None:
        return "any"
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        return val.get("kind", "any")
    return "any"


def saved_to_executor(saved: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a saved frontend graph payload to the executor format.

    Mirrors ``buildGraphPayload`` in ``frontend/src/App.tsx``: each ReactFlow
    node becomes ``{id, type, input_values, ...}``; each ReactFlow edge
    becomes a ``Link`` with ``kind`` derived from the port type kind on
    either end (control ports are stamped ``kind="control"``).
    """
    nodes_out: List[Dict[str, Any]] = []
    for n in saved.get("nodes", []):
        data = n.get("data", {}) or {}
        node_type = data.get("nodeType")
        nodes_out.append({
            "id": n["id"],
            "type": node_type,
            "params": data.get("params") or {},
            "input_values": data.get("inputValues") or {},
            "input_ports_override": data.get("input_ports"),
            "input_port_types_override": data.get("input_port_types"),
            "output_ports_override": data.get("output_ports"),
            "output_port_types_override": data.get("output_port_types"),
            "cache_enabled": bool(data.get("cacheEnabled", False)),
        })

    node_types = {n["id"]: n["type"] for n in nodes_out}
    links_out: List[Dict[str, Any]] = []
    for e in saved.get("edges", []):
        sh = e.get("sourceHandle")
        th = e.get("targetHandle")
        if not sh or not th:
            continue
        src_id = e["source"]
        tgt_id = e["target"]
        src_kind = _port_kind(node_types.get(src_id, ""), sh, "source")
        tgt_kind = _port_kind(node_types.get(tgt_id, ""), th, "target")
        is_control = src_kind == "control" or tgt_kind == "control"
        links_out.append({
            "from_node": src_id,
            "from_port": sh,
            "to_node": tgt_id,
            "to_port": th,
            "kind": "control" if is_control else "data",
        })

    return {"nodes": nodes_out, "links": links_out}


@dataclass
class DemoResult:
    name: str
    status: str  # "ok", "ok_with_caveats", "failed", "skipped"
    duration_ms: float
    nodes_total: int = 0
    nodes_ok: int = 0
    nodes_failed: int = 0
    error: Optional[str] = None
    error_category: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    failed_nodes: List[Tuple[str, str]] = field(default_factory=list)

    def to_row(self, num: int) -> str:
        short = self.name.replace(DEMO_NAME_PREFIX, "")[:60]
        marker = {
            "ok": "OK",
            "ok_with_caveats": "WARN",
            "failed": "FAIL",
            "skipped": "SKIP",
        }.get(self.status, "?")
        return f"{num:>2}  {marker:<5}  {self.duration_ms:>8.0f}ms  {self.nodes_ok}/{self.nodes_total}  {short}"


def categorize_error(msg: str) -> str:
    s = (msg or "").lower()
    if "weight" in s or "download" in s or "huggingface" in s or "hf hub" in s:
        return "weight_download"
    if "cuda" in s or "no gpu" in s or "no cuda" in s or "torch.cuda" in s:
        return "no_gpu"
    if "connect" in s or "timeout" in s or "url" in s or "name resolution" in s:
        return "network"
    if "import" in s or "no module" in s or "modulenotfound" in s:
        return "missing_dep"
    if "type mismatch" in s or "missing port" in s or "unknown node" in s:
        return "wiring_bug"
    if "cancel" in s:
        return "cancellation"
    return "other"


def _async_run_with_timeout(graph_def: Dict[str, Any], timeout_s: float) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[List[Any]]]:
    """Run a graph via ``run_async`` with a wall-clock timeout. Returns
    (result, error_string, execution_trace_or_none)."""

    async def _go() -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[List[Any]]]:
        executor = GraphExecutor(graph_def, options={"use_cache": False})
        try:
            result = await asyncio.wait_for(executor.run_async(), timeout=timeout_s)
            return result, None, list(executor.execution_trace)
        except asyncio.TimeoutError:
            try:
                GraphExecutor.cancel_execution(executor.execution_id)
            except Exception:
                pass
            return None, f"timeout after {timeout_s:.0f}s", list(executor.execution_trace)
        except GraphExecutionError as exc:
            return None, f"GraphExecutionError: {exc}", list(executor.execution_trace)
        except Exception as exc:
            tb = traceback.format_exc(limit=3)
            return None, f"{type(exc).__name__}: {exc}\n{tb}", list(executor.execution_trace)

    return asyncio.run(_go())


def verify_normal(name: str, saved: Dict[str, Any], timeout_s: float) -> DemoResult:
    """Run a regular demo synchronously and capture per-node status."""
    t0 = time.time()
    try:
        graph_def = saved_to_executor(saved)
    except Exception as exc:
        return DemoResult(
            name=name,
            status="failed",
            duration_ms=(time.time() - t0) * 1000.0,
            error=f"normalization failed: {exc}",
            error_category="wiring_bug",
        )

    nodes_total = len(graph_def["nodes"])
    result, err, trace = _async_run_with_timeout(graph_def, timeout_s)
    duration_ms = (time.time() - t0) * 1000.0

    nodes_ok = 0
    nodes_failed = 0
    failed_nodes: List[Tuple[str, str]] = []
    if trace:
        for r in trace:
            status = r.status.value if isinstance(r.status, NodeStatus) else str(r.status)
            if status == "completed":
                nodes_ok += 1
            elif status == "error":
                nodes_failed += 1
                failed_nodes.append((r.node_id, r.error or "unknown"))

    if err is None:
        return DemoResult(
            name=name,
            status="ok" if nodes_failed == 0 else "ok_with_caveats",
            duration_ms=duration_ms,
            nodes_total=nodes_total,
            nodes_ok=nodes_ok,
            nodes_failed=nodes_failed,
            failed_nodes=failed_nodes,
        )

    return DemoResult(
        name=name,
        status="failed",
        duration_ms=duration_ms,
        nodes_total=nodes_total,
        nodes_ok=nodes_ok,
        nodes_failed=nodes_failed,
        failed_nodes=failed_nodes,
        error=err,
        error_category=categorize_error(err),
    )


def verify_cancel(name: str, saved: Dict[str, Any]) -> DemoResult:
    """Demo 08 cancel-test: launch on a background thread, sleep, cancel,
    assert the executor stops within budget. Returns ``ok_with_caveats`` if
    cancel landed but late, ``ok`` if landed promptly, ``failed`` otherwise."""
    try:
        graph_def = saved_to_executor(saved)
    except Exception as exc:
        return DemoResult(
            name=name,
            status="failed",
            duration_ms=0,
            error=f"normalization failed: {exc}",
            error_category="wiring_bug",
        )

    nodes_total = len(graph_def["nodes"])
    executor = GraphExecutor(graph_def, options={"use_cache": False})

    run_error: List[Optional[str]] = [None]
    started = threading.Event()
    finished = threading.Event()

    def _runner() -> None:
        try:
            started.set()
            executor.run()
        except Exception as exc:  # noqa: BLE001
            run_error[0] = f"{type(exc).__name__}: {exc}"
        finally:
            finished.set()

    t = threading.Thread(target=_runner, name=f"verify-{name}", daemon=True)
    t0 = time.time()
    t.start()
    started.wait(timeout=2.0)

    # Let the loop tick so we know it's truly running.
    time.sleep(DEMO_08_RUN_BEFORE_CANCEL_S)

    cancel_t0 = time.time()
    cancelled = GraphExecutor.cancel_execution(executor.execution_id)
    finished.wait(timeout=DEMO_08_CANCEL_BUDGET_S)
    cancel_dt = (time.time() - cancel_t0) * 1000.0

    duration_ms = (time.time() - t0) * 1000.0
    notes: List[str] = []
    if cancelled is False:
        return DemoResult(
            name=name, status="failed", duration_ms=duration_ms,
            nodes_total=nodes_total,
            error="cancel_execution returned False — execution did not register before cancel",
            error_category="cancellation",
        )

    if not finished.is_set():
        # Force-poll briefly more — but if still running, that's a regression.
        return DemoResult(
            name=name, status="failed", duration_ms=duration_ms,
            nodes_total=nodes_total,
            error=f"executor did not terminate within {DEMO_08_CANCEL_BUDGET_S:.1f}s of cancel — Phase 1 regression!",
            error_category="cancellation",
        )

    if t.is_alive():
        # Thread still running after finished event = zombie.
        return DemoResult(
            name=name, status="failed", duration_ms=duration_ms,
            nodes_total=nodes_total,
            error="zombie thread: runner thread still alive after run() returned",
            error_category="cancellation",
        )

    nodes_ok = 0
    nodes_failed = 0
    for r in executor.execution_trace:
        status = r.status.value if isinstance(r.status, NodeStatus) else str(r.status)
        if status == "completed":
            nodes_ok += 1
        elif status == "error":
            nodes_failed += 1

    notes.append(f"cancel landed in {cancel_dt:.0f}ms")
    status = "ok"
    if cancel_dt > 250.0:
        status = "ok_with_caveats"
        notes.append(f"cancel slower than 250ms target ({cancel_dt:.0f}ms)")

    return DemoResult(
        name=name, status=status, duration_ms=duration_ms,
        nodes_total=nodes_total,
        nodes_ok=nodes_ok,
        nodes_failed=nodes_failed,
        notes=notes,
    )


def main() -> int:
    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email=SEED_USER_EMAIL).first()
        if user is None:
            print(f"User {SEED_USER_EMAIL} not found", file=sys.stderr)
            return 2

        graphs = (
            db.query(Graph)
            .filter(Graph.owner_id == user.id)
            .filter(Graph.name.like(f"{DEMO_NAME_PREFIX}%"))
            .order_by(Graph.name)
            .all()
        )
        if len(graphs) != 10:
            print(f"WARNING: expected 10 demos, found {len(graphs)}", file=sys.stderr)

        # Sort by demo number embedded in the name (e.g. ``Demo · 03 — ...``).
        def _num(g: Graph) -> int:
            try:
                # ``Demo · 03 — ...``
                tail = g.name[len(DEMO_NAME_PREFIX):]
                return int(tail.split()[0])
            except Exception:
                return 999
        graphs.sort(key=_num)

        results: List[DemoResult] = []
        print(f"\n=== Verifying {len(graphs)} demo graphs ===\n")
        for g in graphs:
            num = _num(g)
            short = g.name[len(DEMO_NAME_PREFIX):]
            print(f"\n--- Demo {num:02d}: {short} ---")
            sys.stdout.flush()
            if num == 8:
                r = verify_cancel(g.name, g.data or {})
            elif num == 10:
                r = verify_normal(g.name, g.data or {}, timeout_s=DEMO_10_TIMEOUT_S)
            else:
                r = verify_normal(g.name, g.data or {}, timeout_s=DEFAULT_TIMEOUT_S)
            results.append(r)
            if r.status == "failed":
                print(f"  FAIL ({r.duration_ms:.0f}ms): {r.error}")
                if r.failed_nodes:
                    for nid, err in r.failed_nodes[:5]:
                        print(f"    - {nid}: {err.splitlines()[0] if err else '(no detail)'}")
            elif r.status == "ok_with_caveats":
                print(f"  WARN ({r.duration_ms:.0f}ms): {r.nodes_ok}/{r.nodes_total} ok")
                for nid, err in r.failed_nodes[:5]:
                    print(f"    - {nid}: {err.splitlines()[0] if err else '(no detail)'}")
                for note in r.notes:
                    print(f"    note: {note}")
            else:
                print(f"  OK ({r.duration_ms:.0f}ms): {r.nodes_ok}/{r.nodes_total} ok")
                for note in r.notes:
                    print(f"    note: {note}")
            sys.stdout.flush()

        print("\n=== Summary ===")
        print("  #  STATUS    TIME       NODES   NAME")
        for i, r in enumerate(results, 1):
            print(r.to_row(i))

        # Print structured JSON for downstream parsing.
        print("\n=== JSON ===")
        print(json.dumps([
            {
                "name": r.name,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "nodes_total": r.nodes_total,
                "nodes_ok": r.nodes_ok,
                "nodes_failed": r.nodes_failed,
                "error": r.error,
                "error_category": r.error_category,
                "failed_nodes": [{"id": nid, "err": err.splitlines()[0] if err else ""} for nid, err in r.failed_nodes],
                "notes": r.notes,
            }
            for r in results
        ], indent=2, default=str))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
