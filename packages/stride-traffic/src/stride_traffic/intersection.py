"""Intersection-level analysis nodes.

Turn-movement counts, control delay, HCM Level-of-Service, and
intersection capacity utilisation. Most of these consume primitives
emitted by the line / polygon counters in ``counting.py``.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.errors import NodeInputError
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_any,
    t_boolean,
    t_control,
    t_detections2d,
    t_float,
    t_int,
    t_list,
    t_map,
    t_string,
)

from .roi import detection_bottom_center, line_side, point_in_polygon
from .types import (
    is_line,
    is_polygon,
    make_event,
    t_traffic_event,
    t_traffic_line,
    t_traffic_polygon,
)


# ---------------------------------------------------------------------------
# traffic.intersection.turn_movement
# ---------------------------------------------------------------------------


TMC_SPEC = NodeSpec(
    type="traffic.intersection.turn_movement",
    version="1.0.0",
    display_name="Intersection · Turn Movement Count",
    category="Traffic Intersection",
    summary="Track turn movements as approach-line × exit-line OD pairs.",
    description=(
        "For every track, records the first approach line it crosses and "
        "the first exit line it then crosses, producing a (approach -> "
        "exit) tally. Use 4 approach lines (N, S, E, W) and 4 exit lines "
        "to get the canonical 12-movement TMC matrix."
    ),
    icon="git-fork",
    tags=["traffic", "intersection", "tmc"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d(), required=True),
        PortSpec(name="approach_lines", type=t_list(t_traffic_line()),
                 required=True,
                 description="Lines a track crosses on entry"),
        PortSpec(name="exit_lines", type=t_list(t_traffic_line()),
                 required=True,
                 description="Lines a track crosses on exit"),
        PortSpec(name="reset", type=t_boolean(), required=False, default=False),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="tmc", type=t_map(t_string(), t_int()),
                 description="(approach -> exit) movement counts"),
        PortSpec(name="total", type=t_int()),
        PortSpec(name="summary", type=t_string()),
    ],
    cache_policy="disabled",
)


_TMC_KEY = "tmc.state"


def _detect_line_cross(line: Dict[str, Any], prev_pt, cur_pt) -> bool:
    if prev_pt is None or cur_pt is None:
        return False
    return (line_side(line, prev_pt) > 0) != (line_side(line, cur_pt) > 0)


@register_node(TMC_SPEC)
class IntersectionTMCNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        det = inputs.get("detections") or {}
        boxes = det.get("boxes") if isinstance(det, dict) else (det or [])
        approach = [l for l in (inputs.get("approach_lines") or []) if is_line(l)]
        exits = [l for l in (inputs.get("exit_lines") or []) if is_line(l)]
        if not approach or not exits:
            raise NodeInputError("approach_lines and exit_lines required")
        reset = bool(inputs.get("reset") or False)
        bucket = ctx.node_resources.setdefault(self.id, {})
        if reset or _TMC_KEY not in bucket:
            bucket[_TMC_KEY] = {
                "tmc": {},
                "track_state": {},  # tid -> {"approach": str|None, "exit": str|None, "last_pt": [x, y]}
            }
        state = bucket[_TMC_KEY]
        for d in boxes or []:
            if not isinstance(d, dict):
                continue
            tid = d.get("track_id") if d.get("track_id") is not None else d.get("id")
            if tid is None:
                continue
            tid = int(tid)
            pt = detection_bottom_center(d)
            if pt is None:
                continue
            tstate = state["track_state"].setdefault(tid, {
                "approach": None, "exit": None, "last_pt": pt,
            })
            prev_pt = tstate["last_pt"]
            # Detect approach line crossing
            if tstate["approach"] is None:
                for line in approach:
                    if _detect_line_cross(line, prev_pt, pt):
                        tstate["approach"] = line.get("name")
                        break
            elif tstate["exit"] is None:
                for line in exits:
                    if _detect_line_cross(line, prev_pt, pt):
                        tstate["exit"] = line.get("name")
                        key = f"{tstate['approach']} -> {tstate['exit']}"
                        state["tmc"][key] = state["tmc"].get(key, 0) + 1
                        break
            tstate["last_pt"] = pt

        total = sum(state["tmc"].values())
        summary = ", ".join(f"{k}={v}" for k, v in sorted(state["tmc"].items()))
        return {
            "control_out": None,
            "tmc": dict(state["tmc"]),
            "total": int(total),
            "summary": summary or "no movements",
        }


# ---------------------------------------------------------------------------
# traffic.intersection.control_delay — HCM uniform delay (Eq. 19-26)
# ---------------------------------------------------------------------------


DELAY_SPEC = NodeSpec(
    type="traffic.intersection.control_delay",
    version="1.0.0",
    display_name="Intersection · Control Delay",
    category="Traffic Intersection",
    summary="HCM signalised-intersection uniform delay (d1).",
    description=(
        "Computes the uniform delay term d1 = 0.5 * C * (1 - g/C)² / "
        "(1 - min(1, X) * g/C), in seconds. C is the cycle length, g is "
        "the effective green, and X = v/c is the volume-to-capacity ratio."
    ),
    icon="clock",
    tags=["traffic", "intersection", "hcm"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="cycle_s", type=t_float(), required=True,
                 constraints={"min": 1.0}),
        PortSpec(name="green_s", type=t_float(), required=True,
                 constraints={"min": 0.0}),
        PortSpec(name="vc", type=t_float(), required=True,
                 description="Volume-to-capacity ratio (X)",
                 constraints={"min": 0.0, "max": 2.0}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="d1_s", type=t_float()),
        PortSpec(name="los", type=t_string()),
    ],
    cache_policy="auto",
)


def _los_from_delay(delay_s: float) -> str:
    """HCM signalised-intersection LOS bins (Exhibit 19-8)."""
    if delay_s <= 10:
        return "A"
    if delay_s <= 20:
        return "B"
    if delay_s <= 35:
        return "C"
    if delay_s <= 55:
        return "D"
    if delay_s <= 80:
        return "E"
    return "F"


@register_node(DELAY_SPEC)
class IntersectionDelayNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        C = float(inputs.get("cycle_s") or 60.0)
        g = float(inputs.get("green_s") or 30.0)
        X = max(0.0, float(inputs.get("vc") or 0.0))
        if C <= 0:
            raise NodeInputError("cycle_s must be > 0", port="cycle_s")
        if g > C:
            raise NodeInputError("green_s cannot exceed cycle_s", port="green_s")
        gC = g / C
        denom = 1.0 - min(1.0, X) * gC
        if denom < 1e-9:
            d1 = 0.5 * C * (1.0 - gC) ** 2 / 1e-9
        else:
            d1 = 0.5 * C * (1.0 - gC) ** 2 / denom
        return {"control_out": None, "d1_s": float(d1), "los": _los_from_delay(d1)}


# ---------------------------------------------------------------------------
# traffic.intersection.los_from_delay
# ---------------------------------------------------------------------------


LOS_SPEC = NodeSpec(
    type="traffic.intersection.los_from_delay",
    version="1.0.0",
    display_name="Intersection · LOS from delay",
    category="Traffic Intersection",
    summary="HCM signalised-intersection Level-of-Service from control delay.",
    description="Maps a delay (s/veh) to the HCM Exhibit 19-8 LOS bins.",
    icon="award",
    tags=["traffic", "intersection", "los"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="delay_s", type=t_float(), required=True,
                 constraints={"min": 0.0}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="los", type=t_string()),
    ],
    cache_policy="auto",
)


@register_node(LOS_SPEC)
class IntersectionLOSNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        d = float(inputs.get("delay_s") or 0.0)
        return {"control_out": None, "los": _los_from_delay(d)}


# ---------------------------------------------------------------------------
# traffic.intersection.icu — Intersection Capacity Utilisation (Husch & Albeck 2003)
# ---------------------------------------------------------------------------


ICU_SPEC = NodeSpec(
    type="traffic.intersection.icu",
    version="1.0.0",
    display_name="Intersection · ICU",
    category="Traffic Intersection",
    summary="Intersection Capacity Utilisation = sum(v/c per critical movement) + lost time.",
    description=(
        "ICU = sum_critical(v_i / c_i) * (cycle / (cycle - L)) + L / cycle. "
        "Reports capacity-saturation as a single fraction; values >= 1.0 "
        "indicate the intersection is at or above capacity."
    ),
    icon="gauge",
    tags=["traffic", "intersection", "icu"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="critical_vc", type=t_list(t_float()), required=True,
                 description="v/c ratios for each critical movement"),
        PortSpec(name="cycle_s", type=t_float(), required=False, default=120.0,
                 constraints={"min": 1.0}),
        PortSpec(name="lost_time_s", type=t_float(), required=False, default=12.0,
                 constraints={"min": 0.0}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="icu", type=t_float()),
        PortSpec(name="los", type=t_string()),
    ],
    cache_policy="auto",
)


def _icu_los(icu: float) -> str:
    """ICU LOS bins per the original Husch & Albeck spec."""
    if icu <= 0.55:
        return "A"
    if icu <= 0.64:
        return "B"
    if icu <= 0.73:
        return "C"
    if icu <= 0.82:
        return "D"
    if icu <= 0.91:
        return "E"
    if icu <= 1.0:
        return "F"
    return "G"


@register_node(ICU_SPEC)
class IntersectionICUNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        vc = [float(v) for v in (inputs.get("critical_vc") or []) if v is not None]
        C = float(inputs.get("cycle_s") or 120.0)
        L = float(inputs.get("lost_time_s") or 12.0)
        if C <= L:
            raise NodeInputError("cycle_s must be > lost_time_s",
                                 port="cycle_s")
        adj = C / (C - L)
        icu = sum(vc) * adj + L / C
        return {"control_out": None, "icu": float(icu), "los": _icu_los(icu)}
