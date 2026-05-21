"""Quick in-process verifier for the static traffic demos.

Builds each Traffic 01 / 02 / 03 demo, normalises it through the same
saved-to-executor logic the WebSocket runner uses, and runs it through
``GraphExecutor`` in-process. Skips the live-video demos (Traffic 04, 05)
which need an FL511 stream + YOLO weights.

Usage::

    cd backend
    uv run python scripts/verify_traffic_static.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import traceback
from typing import Any, Dict

_THIS = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_THIS)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.runner import GraphExecutor  # noqa: E402

# Reuse the seed builders + the normaliser from verify_demos.
from scripts.seed_demo_graphs import (  # noqa: E402
    demo_traffic_01_flow_metrics,
    demo_traffic_02_hsm_crash,
    demo_traffic_03_safety_metrics,
)
from scripts.verify_demos import saved_to_executor  # noqa: E402


STATIC_BUILDERS = [
    demo_traffic_01_flow_metrics,
    demo_traffic_02_hsm_crash,
    demo_traffic_03_safety_metrics,
]


async def _run_once(graph_def: Dict[str, Any]) -> Dict[str, Any]:
    executor = GraphExecutor(graph_def, options={"use_cache": False})
    return await asyncio.wait_for(executor.run_async(), timeout=30.0)


def main() -> int:
    failures = 0
    for builder in STATIC_BUILDERS:
        name, _, data = builder()
        graph_def = saved_to_executor(data)
        try:
            result = asyncio.run(_run_once(graph_def))
        except Exception as exc:
            failures += 1
            print(f"FAIL: {builder.__name__}: {type(exc).__name__}: {exc}")
            traceback.print_exc(limit=3)
            continue
        outputs = result.get("outputs", {})
        print(f"OK : {builder.__name__}")
        for k, v in outputs.items():
            preview = repr(v)
            if len(preview) > 80:
                preview = preview[:77] + "..."
            print(f"     {k} = {preview}")
    print()
    print(f"Done. {len(STATIC_BUILDERS) - failures}/{len(STATIC_BUILDERS)} passed.")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
