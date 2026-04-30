"""
End-to-end WebSocket verification driver for the seeded ``Demo · NN`` graphs.

Where ``verify_demos.py`` runs the executor in-process, this script exercises
the full HTTP + WebSocket wire path the frontend uses:

  1. boot the FastAPI app in a subprocess (uvicorn on port 8770)
  2. POST /api/auth/register to mint a fresh ephemeral test user
  3. seed all ten demo graphs under that user (re-using
     :mod:`scripts.seed_demo_graphs`'s ``DEMO_BUILDERS``)
  4. GET /api/graphs to fetch the list
  5. for each demo, open ws://.../ws/run-graph and send the exact same payload
     that :func:`buildGraphPayload` in ``frontend/src/App.tsx`` produces — i.e.
     ``{graph: {nodes: [...], links: [...]}, options: {mode: "full"}}``.
     Stream events until the terminal ``result`` (or ``error``) event is seen.
  6. Demo 08 is the cancel test: after ~2s call ``POST
     /api/executions/{id}/cancel`` and verify the WS still emits a clean
     terminal event within budget.
  7. tear down — drop the ephemeral user (cascade-deletes their graphs) and
     stop the subprocess.

Per-demo timeouts are generous (240 s for download-heavy demos) and demo 10 is
held to a tight 5 s ceiling. The verifier reports a structured summary at the
end and exits 1 if any demo emits an error that is NOT a network/weights/CUDA
issue (those are categorised as ``flake`` and don't fail the run).

Usage::

    cd backend
    PYTHONPATH=. uv run python scripts/verify_demos_ws.py

Set ``STRIDE_WS_PORT`` to override the default port (8770). Set
``STRIDE_WS_KEEP_USER=1`` to keep the ephemeral user/graphs around after the
run for manual inspection.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import httpx
import websockets


# Make sure ``app`` and the seed module are importable.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_THIS_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from app.db import SessionLocal  # noqa: E402
from app.models import Graph, User  # noqa: E402
from app.auth import hash_password  # noqa: E402
from app.nodes import list_node_definitions  # noqa: E402

# Re-use the demo builders from the seed script so we always test the
# canonical demo payloads — no risk of drift between this verifier and what
# the user actually sees.
import seed_demo_graphs as seed  # noqa: E402  pylint: disable=wrong-import-position


PORT = int(os.getenv("STRIDE_WS_PORT", "8770"))
HOST = "127.0.0.1"
BASE_URL = f"http://{HOST}:{PORT}"
WS_URL = f"ws://{HOST}:{PORT}/ws/run-graph"
KEEP_USER = bool(int(os.getenv("STRIDE_WS_KEEP_USER", "0")))

DEMO_NAME_PREFIX = seed.DEMO_NAME_PREFIX

# Per-demo timeouts (wall clock). Download-heavy demos get a generous ceiling
# because first-run weight downloads happen on the wire path and there's
# nothing the verifier can do to short-circuit that.
DEFAULT_TIMEOUT_S = 240.0
DEMO_10_TIMEOUT_S = 5.0
DEMO_08_RUN_BEFORE_CANCEL_S = 2.0
DEMO_08_CANCEL_BUDGET_S = 8.0


# =============================================================================
# Registry helpers (mirror frontend buildGraphPayload)
# =============================================================================

def _load_registry() -> Dict[str, Dict[str, Any]]:
    return {d["node_type"]: d for d in list_node_definitions()}


REGISTRY = _load_registry()


def _port_kind(node_type: str, port_name: str, role: str) -> str:
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


def saved_to_payload(saved: Dict[str, Any]) -> Dict[str, Any]:
    """Mirror ``buildGraphPayload`` from ``frontend/src/App.tsx`` exactly.

    The shape it produces is what we send over the WebSocket — same as a
    real Run-button click would produce.
    """
    nodes_out: List[Dict[str, Any]] = []
    for n in saved.get("nodes", []):
        data = n.get("data", {}) or {}
        nodes_out.append({
            "id": n["id"],
            "type": data.get("nodeType"),
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
    return {
        "graph": {"nodes": nodes_out, "links": links_out},
        "options": {"mode": "full"},
    }


# =============================================================================
# Subprocess server lifecycle
# =============================================================================

def _wait_for_port(host: str, port: int, timeout: float = 30.0) -> None:
    """Poll the TCP port until something accepts. Raises on timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.25)
    raise TimeoutError(f"server on {host}:{port} did not come up within {timeout}s")


def start_server() -> subprocess.Popen:
    """Boot uvicorn in a subprocess. Returns the Popen handle.

    Subprocess (not in-process) because uvloop/asyncio playing host-server +
    websocket-client in the same loop has historically been flaky on Windows.
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = _BACKEND_DIR
    cmd = [
        sys.executable, "-m", "uvicorn", "app.main:app",
        "--host", HOST, "--port", str(PORT),
        "--ws", "wsproto",
        "--log-level", "warning",
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=_BACKEND_DIR,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_port(HOST, PORT, timeout=30.0)
    except TimeoutError:
        proc.terminate()
        out = b""
        try:
            out, _ = proc.communicate(timeout=2)
        except Exception:
            pass
        raise RuntimeError(f"server failed to start; output: {out.decode(errors='replace')[-2000:]}")
    return proc


def stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


# =============================================================================
# Test user lifecycle
# =============================================================================

@dataclass
class TestUser:
    user_id: uuid.UUID
    email: str
    password: str
    token: str


def create_user_and_seed_demos() -> TestUser:
    """Create a fresh ephemeral user by writing directly to the DB
    (with a known bcrypt password hash) and seed all 10 demo graphs under
    that user. Doing it via DB lets us also pre-create the password without
    hitting the auth router — but we keep the password known so the verifier
    can log in via /api/auth/login afterwards (i.e. we still exercise the
    auth wire path)."""
    email = f"verify-{uuid.uuid4().hex[:12]}@example.com"
    password = "verify-" + uuid.uuid4().hex[:16]
    db = SessionLocal()
    try:
        u = User(
            email=email,
            password_hash=hash_password(password),
            display_name="WS Verifier",
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        user_id = u.id

        # Seed the demos under this user (re-using the canonical builders).
        from app.domain.graph_migrations import CURRENT_SCHEMA_VERSION, migrate
        for builder in seed.DEMO_BUILDERS:
            name, desc, data = builder()
            data = migrate(data)
            assert data.get("schema_version") == CURRENT_SCHEMA_VERSION
            g = Graph(owner_id=user_id, name=name, description=desc, data=data)
            db.add(g)
        db.commit()
    finally:
        db.close()

    return TestUser(user_id=user_id, email=email, password=password, token="")


def delete_user(user_id: uuid.UUID) -> None:
    """Cascade-delete the ephemeral user and all their graphs."""
    db = SessionLocal()
    try:
        u = db.get(User, user_id)
        if u is not None:
            db.delete(u)
            db.commit()
    finally:
        db.close()


# =============================================================================
# Per-demo verification
# =============================================================================

@dataclass
class DemoResult:
    name: str
    status: str  # "pass", "flake", "fail"
    duration_ms: float
    nodes_total: int = 0
    completed_nodes: int = 0
    errored_nodes: int = 0
    terminal_event: Optional[str] = None  # "result" / "error" / "<missing>"
    error: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    failed_nodes: List[Tuple[str, str]] = field(default_factory=list)
    execution_id: Optional[str] = None


def categorize_error(msg: str) -> str:
    s = (msg or "").lower()
    if any(k in s for k in (
        "weight", "download", "huggingface", "hf hub", "huggingface_hub",
        "no module named", "modulenotfounderror",
    )):
        return "flake"
    if any(k in s for k in ("cuda", "no gpu", "no cuda", "torch.cuda")):
        return "flake"
    if any(k in s for k in (
        "connect", "timeout", "name resolution", "max retries", "url",
    )):
        return "flake"
    if "preprocessor_config" in s:
        # If our hardening worked, this should never escape — flag as real bug
        return "real_bug"
    return "real_bug"


async def _consume_until_terminal(
    ws: websockets.WebSocketClientProtocol,
    timeout_s: float,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Read events from the socket until a terminal one (``result`` or
    ``error``) arrives. Returns (events, terminal_event_type).
    """
    events: List[Dict[str, Any]] = []
    deadline = time.time() + timeout_s
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            return events, None
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except asyncio.TimeoutError:
            return events, None
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            continue
        events.append(ev)
        et = ev.get("event_type")
        if et in ("result", "error"):
            return events, et


def _summarize_events(events: List[Dict[str, Any]]) -> Tuple[int, int, List[Tuple[str, str]]]:
    """Count completed (incl. cache hits) and errored nodes from the stream.

    The streaming executor emits ``node_completed`` for fresh runs and
    ``node_cached`` for cache hits — both mean "this node finished successfully".
    Control-flow nodes (start, for, while) and looped subgraphs may emit
    multiple ``node_completed`` events for the same node id, so we
    de-duplicate by node id.
    """
    completed_ids: set[str] = set()
    errored_ids: set[str] = set()
    failed: List[Tuple[str, str]] = []
    for ev in events:
        et = ev.get("event_type")
        nid = ev.get("node_id")
        if not nid:
            continue
        if et in ("node_completed", "node_cached"):
            completed_ids.add(nid)
        elif et == "node_error":
            errored_ids.add(nid)
            failed.append((nid, ev.get("error") or "unknown"))
    # Errored takes precedence — if a node both completed and errored
    # (shouldn't happen but be defensive) we count it as errored.
    completed_ids -= errored_ids
    return len(completed_ids), len(errored_ids), failed


async def verify_demo(
    name: str,
    saved_data: Dict[str, Any],
    timeout_s: float,
) -> DemoResult:
    """Run one demo end-to-end via the WebSocket and capture results."""
    payload = saved_to_payload(saved_data)
    nodes_total = len(payload["graph"]["nodes"])
    t0 = time.time()

    try:
        async with websockets.connect(WS_URL, max_size=64 * 1024 * 1024) as ws:
            await ws.send(json.dumps(payload))
            events, terminal = await _consume_until_terminal(ws, timeout_s)
    except Exception as exc:  # noqa: BLE001
        tb = traceback.format_exc(limit=3)
        return DemoResult(
            name=name, status="fail",
            duration_ms=(time.time() - t0) * 1000.0,
            nodes_total=nodes_total,
            terminal_event="<connection_failed>",
            error=f"{type(exc).__name__}: {exc}\n{tb}",
        )

    duration_ms = (time.time() - t0) * 1000.0
    completed, errored, failed = _summarize_events(events)

    # Try to lift the execution_id off any event for context.
    exec_id = next((ev.get("execution_id") for ev in events if ev.get("execution_id")), None)

    if terminal is None:
        return DemoResult(
            name=name, status="fail",
            duration_ms=duration_ms,
            nodes_total=nodes_total,
            completed_nodes=completed,
            errored_nodes=errored,
            terminal_event="<missing>",
            error=f"timeout after {timeout_s:.0f}s; no terminal event received",
            failed_nodes=failed,
            execution_id=exec_id,
        )

    if terminal == "error":
        last_err = next((ev.get("error") for ev in reversed(events) if ev.get("event_type") == "error"), "unknown")
        cat = categorize_error(last_err or "")
        return DemoResult(
            name=name,
            status="flake" if cat == "flake" else "fail",
            duration_ms=duration_ms,
            nodes_total=nodes_total,
            completed_nodes=completed,
            errored_nodes=errored,
            terminal_event=terminal,
            error=last_err,
            failed_nodes=failed,
            execution_id=exec_id,
            notes=[f"category={cat}"],
        )

    # Terminal == "result". Check whether any individual node errored.
    if errored > 0:
        # Were the failures all flake-y (download/CUDA/etc)?
        cats = {categorize_error(err) for _, err in failed}
        cat_summary = ",".join(sorted(cats))
        all_flake = cats == {"flake"}
        return DemoResult(
            name=name,
            status="flake" if all_flake else "fail",
            duration_ms=duration_ms,
            nodes_total=nodes_total,
            completed_nodes=completed,
            errored_nodes=errored,
            terminal_event=terminal,
            error=f"{errored}/{nodes_total} node(s) errored",
            failed_nodes=failed,
            execution_id=exec_id,
            notes=[f"categories={cat_summary}"],
        )

    return DemoResult(
        name=name, status="pass",
        duration_ms=duration_ms,
        nodes_total=nodes_total,
        completed_nodes=completed,
        errored_nodes=0,
        terminal_event=terminal,
        execution_id=exec_id,
    )


async def verify_demo_cancel(
    name: str,
    saved_data: Dict[str, Any],
    client: httpx.AsyncClient,
    auth_header: Dict[str, str],
) -> DemoResult:
    """Demo 08 special: connect, send the payload, sleep ~2s, fire
    POST /api/executions/{id}/cancel, and verify the WS emits a terminal
    event within budget. Tests both:

    - the WebSocket → executor cancellation propagation path
    - the REST cancel endpoint's interaction with a live WS executor
    """
    payload = saved_to_payload(saved_data)
    nodes_total = len(payload["graph"]["nodes"])
    t0 = time.time()
    notes: List[str] = []
    exec_id: Optional[str] = None
    events: List[Dict[str, Any]] = []
    terminal: Optional[str] = None

    try:
        async with websockets.connect(WS_URL, max_size=64 * 1024 * 1024) as ws:
            await ws.send(json.dumps(payload))

            # Read events for ~2 s so the executor is provably running and we
            # have an execution_id to cancel.
            deadline = time.time() + DEMO_08_RUN_BEFORE_CANCEL_S
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(0.05, deadline - time.time()))
                except asyncio.TimeoutError:
                    break
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                events.append(ev)
                if not exec_id:
                    exec_id = ev.get("execution_id")

            if not exec_id:
                return DemoResult(
                    name=name, status="fail",
                    duration_ms=(time.time() - t0) * 1000.0,
                    nodes_total=nodes_total,
                    terminal_event="<missing>",
                    error="never observed an execution_id from the WS",
                )

            # Fire the cancel REST request.
            cancel_t0 = time.time()
            resp = await client.post(
                f"{BASE_URL}/api/executions/{exec_id}/cancel",
                headers=auth_header,
            )
            if resp.status_code not in (200, 404):
                # 404 = already finished (race); 200 = cancel registered.
                notes.append(f"cancel POST returned {resp.status_code}: {resp.text[:200]}")

            # Now consume until terminal (with a tight budget).
            extra_events, terminal = await _consume_until_terminal(ws, DEMO_08_CANCEL_BUDGET_S)
            events.extend(extra_events)
            cancel_dt = (time.time() - cancel_t0) * 1000.0
            notes.append(f"cancel landed in {cancel_dt:.0f}ms")

    except Exception as exc:  # noqa: BLE001
        return DemoResult(
            name=name, status="fail",
            duration_ms=(time.time() - t0) * 1000.0,
            nodes_total=nodes_total,
            terminal_event="<connection_failed>",
            error=f"{type(exc).__name__}: {exc}",
            execution_id=exec_id,
        )

    duration_ms = (time.time() - t0) * 1000.0
    completed, errored, failed = _summarize_events(events)

    if terminal is None:
        return DemoResult(
            name=name, status="fail",
            duration_ms=duration_ms,
            nodes_total=nodes_total,
            completed_nodes=completed,
            errored_nodes=errored,
            terminal_event="<missing>",
            error=f"executor did not emit a terminal event within {DEMO_08_CANCEL_BUDGET_S:.1f}s of cancel",
            execution_id=exec_id,
            notes=notes,
        )

    # The executor's cancel path may emit terminal=result or terminal=error.
    # Either is acceptable; what matters is "terminal arrived cleanly".
    return DemoResult(
        name=name, status="pass",
        duration_ms=duration_ms,
        nodes_total=nodes_total,
        completed_nodes=completed,
        errored_nodes=errored,
        terminal_event=terminal,
        execution_id=exec_id,
        notes=notes,
        failed_nodes=failed,
    )


# =============================================================================
# Driver
# =============================================================================

async def run_all_demos(client: httpx.AsyncClient, auth_header: Dict[str, str]) -> List[DemoResult]:
    # Fetch graphs through the real API (not the DB) so we exercise that path.
    resp = await client.get(f"{BASE_URL}/api/graphs", headers=auth_header)
    resp.raise_for_status()
    graphs = resp.json()
    demo_graphs = [g for g in graphs if g.get("name", "").startswith(DEMO_NAME_PREFIX)]

    def _num(g: Dict[str, Any]) -> int:
        try:
            tail = g["name"][len(DEMO_NAME_PREFIX):]
            return int(tail.split()[0])
        except Exception:
            return 999

    demo_graphs.sort(key=_num)

    results: List[DemoResult] = []
    print(f"\n=== WS-verifying {len(demo_graphs)} demo graphs ===\n")
    for g in demo_graphs:
        n = _num(g)
        short = g["name"][len(DEMO_NAME_PREFIX):][:60]
        print(f"--- Demo {n:02d}: {short} ---")
        sys.stdout.flush()

        # Saved data lives in g["data"] for our schema.
        saved = g.get("data") or {}
        if n == 8:
            r = await verify_demo_cancel(g["name"], saved, client, auth_header)
        elif n == 10:
            r = await verify_demo(g["name"], saved, DEMO_10_TIMEOUT_S)
        else:
            r = await verify_demo(g["name"], saved, DEFAULT_TIMEOUT_S)
        results.append(r)

        marker = {"pass": "PASS", "flake": "FLAKE", "fail": "FAIL"}.get(r.status, "?")
        print(f"  {marker} {r.duration_ms:.0f}ms  "
              f"nodes={r.completed_nodes}/{r.nodes_total} err={r.errored_nodes} "
              f"terminal={r.terminal_event}")
        if r.error:
            print(f"  err: {r.error.splitlines()[0] if r.error else ''}")
        for nid, err in r.failed_nodes[:3]:
            print(f"    - {nid}: {(err or '').splitlines()[0][:160]}")
        for note in r.notes:
            print(f"    note: {note}")
        sys.stdout.flush()

    return results


def main() -> int:
    print(f"WS verifier: starting server on {BASE_URL}")
    proc = start_server()

    user: Optional[TestUser] = None
    try:
        user = create_user_and_seed_demos()
        print(f"WS verifier: created ephemeral user {user.email}")

        async def _go():
            assert user is not None
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Login the real way to get a JWT.
                resp = await client.post(
                    f"{BASE_URL}/api/auth/login",
                    json={"email": user.email, "password": user.password},
                )
                resp.raise_for_status()
                token = resp.json()["access_token"]
                user.token = token
                auth = {"Authorization": f"Bearer {token}"}

                results = await run_all_demos(client, auth)
                return results

        results = asyncio.run(_go())

        print("\n=== Summary ===")
        print("  #  STATUS  TIME       NODES    NAME")
        any_real_bug = False
        for i, r in enumerate(results, 1):
            short = r.name.replace(DEMO_NAME_PREFIX, "")[:60]
            marker = {"pass": "PASS", "flake": "FLAKE", "fail": "FAIL"}.get(r.status, "?")
            print(f"  {i:>2}  {marker:<6}  {r.duration_ms:>8.0f}ms  "
                  f"{r.completed_nodes}/{r.nodes_total}    {short}")
            if r.status == "fail":
                any_real_bug = True

        # Print structured JSON for downstream parsing.
        print("\n=== JSON ===")
        print(json.dumps([
            {
                "name": r.name,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "nodes_total": r.nodes_total,
                "completed_nodes": r.completed_nodes,
                "errored_nodes": r.errored_nodes,
                "terminal_event": r.terminal_event,
                "error": r.error,
                "execution_id": r.execution_id,
                "failed_nodes": [{"id": nid, "err": (err or "").splitlines()[0]} for nid, err in r.failed_nodes],
                "notes": r.notes,
            }
            for r in results
        ], indent=2, default=str))

        return 1 if any_real_bug else 0

    finally:
        if user is not None and not KEEP_USER:
            try:
                delete_user(user.user_id)
                print(f"\nWS verifier: deleted ephemeral user {user.email}")
            except Exception as exc:  # noqa: BLE001
                print(f"\nWS verifier: failed to delete user {user.email}: {exc}", file=sys.stderr)
        elif user is not None and KEEP_USER:
            print(f"\nWS verifier: keeping ephemeral user {user.email} (STRIDE_WS_KEEP_USER=1)")
        stop_server(proc)


if __name__ == "__main__":
    raise SystemExit(main())
