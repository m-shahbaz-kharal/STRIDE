"""End-to-end verifier for the new static traffic analytics demos
(Traffic 06-09). Builds each demo, normalises through the same
saved-to-executor pipe the WebSocket runner uses, runs through
``GraphExecutor``, and prints the dashboard-bound outputs.

Usage:

    cd backend
    PYTHONPATH=. uv run python scripts/verify_traffic_new_demos.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback
from typing import Any, Dict, Optional

_THIS = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_THIS)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.runner import GraphExecutor  # noqa: E402
from scripts.seed_demo_graphs import (  # noqa: E402
    demo_traffic_06_intersection_los,
    demo_traffic_07_spot_speed_study,
    demo_traffic_08_safety_ranking,
    demo_traffic_09_capacity_workbook,
    demo_traffic_10_fundamental_diagram,
)
from scripts.verify_demos import saved_to_executor  # noqa: E402


BUILDERS = [
    demo_traffic_06_intersection_los,
    demo_traffic_07_spot_speed_study,
    demo_traffic_08_safety_ranking,
    demo_traffic_09_capacity_workbook,
    demo_traffic_10_fundamental_diagram,
]


async def _run(graph_def: Dict[str, Any]) -> Dict[str, Any]:
    executor = GraphExecutor(graph_def, options={"use_cache": False})
    return await asyncio.wait_for(executor.run_async(), timeout=30.0)


def _grab(trace, node_id: str, port: str) -> Optional[Any]:
    for r in trace:
        nid = r.get("node_id") if isinstance(r, dict) else getattr(r, "node_id", None)
        outs = r.get("outputs") if isinstance(r, dict) else getattr(r, "outputs", None)
        if nid == node_id and isinstance(outs, dict):
            return outs.get(port)
    return None


def main() -> int:
    failures = 0
    for builder in BUILDERS:
        name, _, data = builder()
        print(f"\n--- {builder.__name__}  /  {name}")
        try:
            graph_def = saved_to_executor(data)
            result = asyncio.run(_run(graph_def))
        except Exception as exc:
            failures += 1
            print(f"  FAIL: {type(exc).__name__}: {exc}")
            traceback.print_exc(limit=3)
            continue
        trace = result.get("trace") or []
        # Per-demo expected probes.
        if builder is demo_traffic_06_intersection_los:
            probes = [
                ("cd_nb", "d1_s"), ("cd_nb", "los"),
                ("cd_sb", "d1_s"), ("cd_sb", "los"),
                ("cd_eb", "d1_s"), ("cd_eb", "los"),
                ("cd_wb", "d1_s"), ("cd_wb", "los"),
                ("icu", "icu"), ("icu", "los"),
            ]
        elif builder is demo_traffic_07_spot_speed_study:
            probes = [
                ("bundle", "mean"), ("bundle", "p50"),
                ("p85", "value_kph"), ("p95", "value_kph"),
                ("bundle", "stdev"), ("bundle", "n"),
            ]
        elif builder is demo_traffic_08_safety_ranking:
            probes = [
                (f"spf_{l}", "n_spf_per_year") for l in "ABCDE"
            ] + [
                (f"eb_{l}", "n_expected") for l in "ABCDE"
            ] + [
                (f"psi_{l}", "psi") for l in "ABCDE"
            ]
        elif builder is demo_traffic_09_capacity_workbook:
            probes = [
                ("sat_flow", "sat_flow_vph"), ("sat_flow", "mean_headway_s"),
                ("phf", "phf"), ("phf", "hourly_volume"),
                ("aadt", "aadt"),
                ("vc", "vc"), ("vc", "status"),
            ]
        else:  # 10 fundamental diagram
            probes = [
                ("gs_ff", "speed_kph"), ("gs_ff", "flow_vph"),
                ("gs_cap", "speed_kph"), ("gs_cap", "flow_vph"),
                ("gs_cong", "speed_kph"), ("gs_cong", "flow_vph"),
            ]
        for node_id, port in probes:
            val = _grab(trace, node_id, port)
            if isinstance(val, float):
                val = round(val, 4)
            print(f"  {node_id}.{port} = {val!r}")
    print()
    print(f"Done. {len(BUILDERS) - failures}/{len(BUILDERS)} passed.")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
