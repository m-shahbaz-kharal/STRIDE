"""Surrogate safety nodes — TTC, PET, DRAC, headway, near-miss events.

These metrics are the workhorses of camera-based traffic safety analysis
(FHWA SSAM, Hayward 1972, Allen et al. 1978). They are pairwise functions
of two trajectories and are evaluated on every frame to detect conflicts.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None  # type: ignore

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.errors import NodeInputError, NodeMissingDependencyError
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_any,
    t_boolean,
    t_control,
    t_detections2d,
    t_float,
    t_int,
    t_list,
    t_string,
)

from .calibration import project_pixel_to_world
from .roi import detection_bottom_center, point_in_polygon
from .types import (
    TrackState,
    get_track_store,
    is_calibration,
    make_event,
    t_traffic_calibration,
    t_traffic_event,
    t_traffic_polygon,
)


def _require_numpy() -> None:
    if not HAS_NUMPY:
        raise NodeMissingDependencyError("numpy is required for safety nodes")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _track_position_velocity(track: TrackState) -> Optional[Tuple[float, float, float, float]]:
    """Return (x, y, vx, vy) in world units from a TrackState's last samples.

    Computes velocity as a finite difference over the last ~0.5 s of
    history. Returns None if there isn't enough history.
    """
    if len(track.history) < 2:
        return None
    last = track.history[-1]
    # Find a sample ~0.5 s earlier
    t_end = float(last["ts"])
    cutoff = t_end - 0.5
    a = track.history[0]
    for i in range(len(track.history) - 2, -1, -1):
        if float(track.history[i]["ts"]) <= cutoff:
            a = track.history[i]
            break
    dt = max(1e-6, t_end - float(a["ts"]))
    vx = float(last.get("x_w", 0.0) - a.get("x_w", 0.0)) / dt
    vy = float(last.get("y_w", 0.0) - a.get("y_w", 0.0)) / dt
    return float(last.get("x_w", 0.0)), float(last.get("y_w", 0.0)), vx, vy


def _ttc_pair(
    a: Tuple[float, float, float, float],
    b: Tuple[float, float, float, float],
) -> Optional[float]:
    """Standard TTC for two point-mass particles.

    Returns the time at which the relative distance is minimised, only
    if the particles are currently approaching (dot(rel_v, rel_p) < 0).
    """
    ax, ay, avx, avy = a
    bx, by, bvx, bvy = b
    rx = bx - ax
    ry = by - ay
    rvx = bvx - avx
    rvy = bvy - avy
    rv2 = rvx * rvx + rvy * rvy
    if rv2 < 1e-9:
        return None
    # Time of closest approach
    t = -(rx * rvx + ry * rvy) / rv2
    # Approach test
    if t <= 0:
        return None
    return float(t)


# ---------------------------------------------------------------------------
# traffic.safety.ttc_pairwise
# ---------------------------------------------------------------------------


TTC_SPEC = NodeSpec(
    type="traffic.safety.ttc_pairwise",
    version="1.0.0",
    display_name="Safety · Time-to-Collision (pairwise)",
    category="Traffic Safety",
    summary="Compute pairwise TTC for active tracks; emit events below threshold.",
    description=(
        "For every pair of active tracks, computes the standard TTC "
        "(Hayward 1972) under a constant-velocity model. Emits a "
        "near_miss event when TTC drops below ``threshold_s``."
    ),
    icon="alert-triangle",
    tags=["traffic", "safety", "ttc"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="store_key", type=t_string(), required=False,
                 default="speed",
                 description="Key of a track-store maintained by speed.estimate"
                             " or trajectory.accumulate"),
        PortSpec(name="threshold_s", type=t_float(), required=False, default=1.5,
                 constraints={"min": 0.0}),
        PortSpec(name="critical_s", type=t_float(), required=False, default=0.5,
                 constraints={"min": 0.0},
                 description="TTC below this is a 'critical' severity event"),
        PortSpec(name="min_speed_mps", type=t_float(), required=False, default=1.0,
                 description="Skip pairs where both speeds are under this",
                 constraints={"min": 0.0}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="events", type=t_list(t_traffic_event())),
        PortSpec(name="min_ttc_s", type=t_float()),
        PortSpec(name="critical_count", type=t_int()),
    ],
    cache_policy="disabled",
)


@register_node(TTC_SPEC)
class SafetyTTCPairwiseNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        store_key = str(inputs.get("store_key") or "speed")
        thr = float(inputs.get("threshold_s") or 1.5)
        crit = float(inputs.get("critical_s") or 0.5)
        v_min = float(inputs.get("min_speed_mps") or 1.0)
        store = get_track_store(ctx, store_key)
        # Snapshot per-track (x, y, vx, vy)
        snaps: Dict[int, Tuple[float, float, float, float]] = {}
        for tid, track in store.items():
            s = _track_position_velocity(track)
            if s is None:
                continue
            speed = math.sqrt(s[2] * s[2] + s[3] * s[3])
            if speed < v_min:
                continue
            snaps[int(tid)] = s
        ids = sorted(snaps.keys())
        events: List[Dict[str, Any]] = []
        min_ttc = float("inf")
        critical = 0
        ts = time.time()
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                t = _ttc_pair(snaps[ids[i]], snaps[ids[j]])
                if t is None:
                    continue
                if t < min_ttc:
                    min_ttc = t
                if t < thr:
                    severity = "critical" if t < crit else "warning"
                    if severity == "critical":
                        critical += 1
                    events.append(make_event(
                        kind="near_miss",
                        severity=severity,
                        track_ids=[ids[i], ids[j]],
                        ts_start=ts,
                        metric=float(t),
                        label=f"TTC {t:.2f}s ({ids[i]}<>{ids[j]})",
                        details={"ttc_s": float(t)},
                    ))
        return {
            "control_out": None,
            "events": events,
            "min_ttc_s": float(min_ttc) if min_ttc != float("inf") else 0.0,
            "critical_count": int(critical),
        }


# ---------------------------------------------------------------------------
# traffic.safety.headway — instantaneous time-gap between leader and follower
# ---------------------------------------------------------------------------


HEADWAY_SPEC = NodeSpec(
    type="traffic.safety.headway",
    version="1.0.0",
    display_name="Safety · Headway / Gap",
    category="Traffic Safety",
    summary="Compute time-gaps from a list of crossing timestamps.",
    description=(
        "Given an ordered list of crossing times (e.g. from "
        "``traffic.count.line``), returns the time-gap series, mean, "
        "stdev, and percentile."
    ),
    icon="git-merge",
    tags=["traffic", "safety", "headway"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="crossing_times_s", type=t_list(t_float()), required=True,
                 description="Times at which vehicles crossed a reference"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="headways_s", type=t_list(t_float())),
        PortSpec(name="mean_s", type=t_float()),
        PortSpec(name="stdev_s", type=t_float()),
        PortSpec(name="min_s", type=t_float()),
        PortSpec(name="critical_count", type=t_int(),
                 description="# headways < 1.0 s"),
    ],
    cache_policy="auto",
)


@register_node(HEADWAY_SPEC)
class SafetyHeadwayNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        raw = inputs.get("crossing_times_s") or []
        ts_sorted = sorted(float(t) for t in raw if t is not None)
        if len(ts_sorted) < 2:
            return {
                "control_out": None,
                "headways_s": [],
                "mean_s": 0.0,
                "stdev_s": 0.0,
                "min_s": 0.0,
                "critical_count": 0,
            }
        gaps = [ts_sorted[i] - ts_sorted[i - 1] for i in range(1, len(ts_sorted))]
        n = len(gaps)
        mean = sum(gaps) / n
        var = sum((g - mean) ** 2 for g in gaps) / n
        sd = math.sqrt(var)
        return {
            "control_out": None,
            "headways_s": gaps,
            "mean_s": float(mean),
            "stdev_s": float(sd),
            "min_s": float(min(gaps)),
            "critical_count": int(sum(1 for g in gaps if g < 1.0)),
        }


# ---------------------------------------------------------------------------
# traffic.safety.drac — deceleration rate to avoid collision
# ---------------------------------------------------------------------------


DRAC_SPEC = NodeSpec(
    type="traffic.safety.drac",
    version="1.0.0",
    display_name="Safety · DRAC",
    category="Traffic Safety",
    summary="Deceleration rate required by the follower to avoid collision.",
    description=(
        "DRAC = (v_follower - v_leader)² / (2 * gap). Inputs are the "
        "follower's speed (m/s), the leader's speed (m/s), and the "
        "current bumper-to-bumper gap (m). Reported in m/s² (positive)."
    ),
    icon="alert-triangle",
    tags=["traffic", "safety", "drac"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="follower_mps", type=t_float(), required=True,
                 constraints={"min": 0.0}),
        PortSpec(name="leader_mps", type=t_float(), required=True,
                 constraints={"min": 0.0}),
        PortSpec(name="gap_m", type=t_float(), required=True,
                 constraints={"min": 1e-6}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="drac_mps2", type=t_float()),
        PortSpec(name="severity", type=t_string()),
    ],
    cache_policy="auto",
)


@register_node(DRAC_SPEC)
class SafetyDracNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        vf = float(inputs.get("follower_mps") or 0.0)
        vl = float(inputs.get("leader_mps") or 0.0)
        gap = float(inputs.get("gap_m") or 1.0)
        if vf <= vl:
            return {
                "control_out": None,
                "drac_mps2": 0.0,
                "severity": "info",
            }
        drac = (vf - vl) ** 2 / (2.0 * max(gap, 1e-6))
        if drac > 4.5:
            sev = "critical"
        elif drac > 3.4:
            sev = "warning"
        else:
            sev = "info"
        return {"control_out": None, "drac_mps2": float(drac), "severity": sev}


# ---------------------------------------------------------------------------
# traffic.safety.pet — Post-Encroachment Time at a conflict point
# ---------------------------------------------------------------------------


PET_SPEC = NodeSpec(
    type="traffic.safety.pet",
    version="1.0.0",
    display_name="Safety · Post-Encroachment Time",
    category="Traffic Safety",
    summary="PET between two timestamps at the same conflict point.",
    description=(
        "PET = time between road-user A leaving the conflict zone and "
        "road-user B arriving at the same zone. Allen et al., 1978."
    ),
    icon="clock",
    tags=["traffic", "safety", "pet"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="ts_first_left_s", type=t_float(), required=True),
        PortSpec(name="ts_second_arrived_s", type=t_float(), required=True),
        PortSpec(name="threshold_s", type=t_float(), required=False, default=1.5,
                 constraints={"min": 0.0}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="pet_s", type=t_float()),
        PortSpec(name="severity", type=t_string()),
        PortSpec(name="event", type=t_traffic_event()),
    ],
    cache_policy="auto",
)


@register_node(PET_SPEC)
class SafetyPetNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        t_left = float(inputs.get("ts_first_left_s") or 0.0)
        t_arr = float(inputs.get("ts_second_arrived_s") or 0.0)
        thr = float(inputs.get("threshold_s") or 1.5)
        pet = t_arr - t_left
        if pet < 0:
            sev = "info"
        elif pet < 0.5:
            sev = "critical"
        elif pet < thr:
            sev = "warning"
        else:
            sev = "info"
        evt = make_event(
            kind="near_miss",
            severity=sev,
            track_ids=[],
            ts_start=t_left,
            ts_end=t_arr,
            metric=float(pet),
            label=f"PET {pet:.2f}s",
            details={"pet_s": float(pet)},
        )
        return {"control_out": None, "pet_s": float(pet), "severity": sev,
                "event": evt}


# ---------------------------------------------------------------------------
# traffic.safety.headway_live — running headway from a line-cross event stream
# ---------------------------------------------------------------------------


HEADWAY_LIVE_SPEC = NodeSpec(
    type="traffic.safety.headway_live",
    version="1.0.0",
    display_name="Safety · Headway (live)",
    category="Traffic Safety",
    summary="Stateful headway analyzer: ingest line-cross events, emit running stats.",
    description=(
        "On every call, append the timestamps of the supplied events to "
        "an internal ring buffer keyed per-run, then re-emit the same "
        "headway statistics ``traffic.safety.headway`` produces — but live, "
        "frame-by-frame, instead of from a manually-specified list."
    ),
    icon="git-merge",
    tags=["traffic", "safety", "headway", "live"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="events", type=t_list(t_traffic_event()), required=True,
                 description="Typically wired from traffic.count.line.events"),
        PortSpec(name="kind_filter", type=t_string(), required=False,
                 default="line_cross",
                 description='Only count events with this kind (or "" for all)'),
        PortSpec(name="max_samples", type=t_int(), required=False, default=2048,
                 constraints={"min": 4}),
        PortSpec(name="reset", type=t_boolean(), required=False, default=False),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="headways_s", type=t_list(t_float())),
        PortSpec(name="mean_s", type=t_float()),
        PortSpec(name="min_s", type=t_float()),
        PortSpec(name="critical_count", type=t_int(),
                 description="Count of headways < 1.0 s (rear-end risk)"),
        PortSpec(name="n", type=t_int()),
    ],
    cache_policy="disabled",
)


_HW_KEY = "headway_live.times"


@register_node(HEADWAY_LIVE_SPEC)
class SafetyHeadwayLiveNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        events = inputs.get("events") or []
        kind = str(inputs.get("kind_filter") or "").lower()
        cap = int(inputs.get("max_samples") or 2048)
        reset = bool(inputs.get("reset") or False)
        bucket = ctx.node_resources.setdefault(self.id, {})
        if reset or _HW_KEY not in bucket:
            bucket[_HW_KEY] = []
        buf: List[float] = bucket[_HW_KEY]

        for e in events:
            if not isinstance(e, dict):
                continue
            if kind and str(e.get("kind") or "").lower() != kind:
                continue
            ts = e.get("ts_start")
            if ts is None:
                continue
            try:
                buf.append(float(ts))
            except (TypeError, ValueError):
                continue
        # Truncate
        if len(buf) > cap:
            del buf[0 : len(buf) - cap]
        sorted_ts = sorted(buf)
        if len(sorted_ts) < 2:
            return {
                "control_out": None,
                "headways_s": [], "mean_s": 0.0, "min_s": 0.0,
                "critical_count": 0, "n": 0,
            }
        gaps = [sorted_ts[i] - sorted_ts[i - 1] for i in range(1, len(sorted_ts))]
        mean = sum(gaps) / len(gaps)
        return {
            "control_out": None,
            "headways_s": gaps,
            "mean_s": float(mean),
            "min_s": float(min(gaps)),
            "critical_count": int(sum(1 for g in gaps if g < 1.0)),
            "n": len(gaps),
        }


# ---------------------------------------------------------------------------
# traffic.safety.drac_pairwise — live DRAC from the per-run track store
# ---------------------------------------------------------------------------


DRAC_PAIR_SPEC = NodeSpec(
    type="traffic.safety.drac_pairwise",
    version="1.0.0",
    display_name="Safety · DRAC (pairwise live)",
    category="Traffic Safety",
    summary="Per-frame leader/follower DRAC from the active track store.",
    description=(
        "For every track-pair on each frame:\n"
        "1. find the closest other track in the direction of motion;\n"
        "2. treat it as the leader, this track as the follower;\n"
        "3. compute DRAC = (vf - vl)² / (2 * gap_m) when vf > vl;\n"
        "4. emit a ``hard_brake`` event if DRAC > ``threshold_mps2`` "
        "   (FHWA SSAM ≥ 3.4 m/s² is the standard 'hard brake'; "
        "   ≥ 4.5 m/s² is treated as critical).\n"
        "Reads the track store populated by ``traffic.speed.estimate`` or "
        "``traffic.trajectory.accumulate`` — wire ``store_key`` to whatever "
        "the upstream tracker / speed-estimator is using."
    ),
    icon="alert-triangle",
    tags=["traffic", "safety", "drac", "live"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="store_key", type=t_string(), required=False,
                 default="speed"),
        PortSpec(name="threshold_mps2", type=t_float(), required=False,
                 default=3.4, constraints={"min": 0.0}),
        PortSpec(name="critical_mps2", type=t_float(), required=False,
                 default=4.5, constraints={"min": 0.0}),
        PortSpec(name="max_lead_distance_m", type=t_float(), required=False,
                 default=50.0, constraints={"min": 0.0},
                 description="Ignore leaders further than this many metres ahead"),
        PortSpec(name="min_speed_mps", type=t_float(), required=False,
                 default=2.0, constraints={"min": 0.0}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="events", type=t_list(t_traffic_event())),
        PortSpec(name="max_drac_mps2", type=t_float()),
        PortSpec(name="critical_count", type=t_int()),
    ],
    cache_policy="disabled",
)


def _track_pos_vel(track: TrackState):
    """(x, y, vx, vy) from the trailing 0.5 s of history."""
    if len(track.history) < 2:
        return None
    last = track.history[-1]
    cutoff = float(last["ts"]) - 0.5
    a = track.history[0]
    for i in range(len(track.history) - 2, -1, -1):
        if float(track.history[i]["ts"]) <= cutoff:
            a = track.history[i]
            break
    dt = max(1e-6, float(last["ts"] - a["ts"]))
    vx = float(last.get("x_w", 0.0) - a.get("x_w", 0.0)) / dt
    vy = float(last.get("y_w", 0.0) - a.get("y_w", 0.0)) / dt
    return float(last.get("x_w", 0.0)), float(last.get("y_w", 0.0)), vx, vy


@register_node(DRAC_PAIR_SPEC)
class SafetyDracPairwiseNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        store_key = str(inputs.get("store_key") or "speed")
        thr = float(inputs.get("threshold_mps2") or 3.4)
        crit = float(inputs.get("critical_mps2") or 4.5)
        max_lead = float(inputs.get("max_lead_distance_m") or 50.0)
        min_speed = float(inputs.get("min_speed_mps") or 2.0)
        store = get_track_store(ctx, store_key)

        snaps: Dict[int, Tuple[float, float, float, float]] = {}
        for tid, track in store.items():
            s = _track_pos_vel(track)
            if s is None:
                continue
            speed = math.sqrt(s[2] ** 2 + s[3] ** 2)
            if speed < min_speed:
                continue
            snaps[int(tid)] = s

        events: List[Dict[str, Any]] = []
        max_drac = 0.0
        critical = 0
        ts = time.time()
        ids = list(snaps.keys())

        for f_id in ids:
            fx, fy, fvx, fvy = snaps[f_id]
            f_speed = math.sqrt(fvx * fvx + fvy * fvy)
            if f_speed < 1e-6:
                continue
            ux, uy = fvx / f_speed, fvy / f_speed
            best_leader = None
            best_gap = float("inf")
            for l_id in ids:
                if l_id == f_id:
                    continue
                lx, ly, _, _ = snaps[l_id]
                # Project leader's offset onto follower's direction
                ahead = (lx - fx) * ux + (ly - fy) * uy
                if ahead <= 0 or ahead > max_lead:
                    continue
                lateral = abs((lx - fx) * (-uy) + (ly - fy) * ux)
                # Restrict to roughly same lane (lateral within ~3.6 m)
                if lateral > 3.6:
                    continue
                if ahead < best_gap:
                    best_gap = ahead
                    best_leader = l_id
            if best_leader is None:
                continue
            lx, ly, lvx, lvy = snaps[best_leader]
            l_speed_along = lvx * ux + lvy * uy
            f_speed_along = f_speed
            if f_speed_along <= l_speed_along:
                continue
            gap = max(best_gap, 0.5)
            drac = (f_speed_along - l_speed_along) ** 2 / (2.0 * gap)
            if drac > max_drac:
                max_drac = drac
            if drac > thr:
                if drac > crit:
                    sev = "critical"
                    critical += 1
                else:
                    sev = "warning"
                events.append(make_event(
                    kind="hard_brake",
                    severity=sev,
                    track_ids=[int(f_id), int(best_leader)],
                    ts_start=ts,
                    metric=float(drac),
                    label=f"Track {f_id}<-{best_leader}: DRAC {drac:.1f} m/s²",
                    details={
                        "follower": int(f_id),
                        "leader": int(best_leader),
                        "gap_m": float(gap),
                        "drac_mps2": float(drac),
                    },
                ))
        return {
            "control_out": None,
            "events": events,
            "max_drac_mps2": float(max_drac),
            "critical_count": int(critical),
        }


# ---------------------------------------------------------------------------
# traffic.safety.pet_at_polygon — PET when consecutive tracks cross a polygon
# ---------------------------------------------------------------------------


PET_POLY_SPEC = NodeSpec(
    type="traffic.safety.pet_at_polygon",
    version="1.0.0",
    display_name="Safety · PET at Polygon",
    category="Traffic Safety",
    summary="Live Post-Encroachment Time as tracks enter/exit a conflict zone.",
    description=(
        "Records the timestamp at which each track *leaves* the polygon, "
        "and computes PET against the timestamp at which the next "
        "different track *arrives* in the polygon. A near-miss event "
        "is emitted on each completion, with severity bins matching the "
        "Allen et al. 1978 thresholds: <0.5 s critical, <``threshold_s`` "
        "warning, otherwise info."
    ),
    icon="clock",
    tags=["traffic", "safety", "pet", "live"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d(), required=True),
        PortSpec(name="polygon", type=t_traffic_polygon(), required=True),
        PortSpec(name="threshold_s", type=t_float(), required=False, default=1.5,
                 constraints={"min": 0.0}),
        PortSpec(name="reference", type=t_string(), required=False,
                 default="bottom",
                 constraints={"enum": ["center", "bottom"]}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="events", type=t_list(t_traffic_event())),
        PortSpec(name="min_pet_s", type=t_float()),
        PortSpec(name="critical_count", type=t_int()),
    ],
    cache_policy="disabled",
)


_PET_KEY = "pet_poly.state"


@register_node(PET_POLY_SPEC)
class SafetyPetAtPolygonNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        from .roi import detection_bottom_center, point_in_polygon  # local cycle guard
        det = inputs.get("detections") or {}
        boxes = det.get("boxes") if isinstance(det, dict) else (det or [])
        polygon = inputs.get("polygon")
        if not isinstance(polygon, dict) or polygon.get("_type") != "TrafficPolygon":
            raise NodeInputError("polygon required", port="polygon")
        ref = str(inputs.get("reference") or "bottom")
        thr = float(inputs.get("threshold_s") or 1.5)
        anchor = (
            detection_bottom_center
            if ref == "bottom"
            else (lambda d: [(d["x1"] + d["x2"]) / 2.0,
                             (d["y1"] + d["y2"]) / 2.0])
        )

        bucket = ctx.node_resources.setdefault(self.id, {})
        state = bucket.setdefault(_PET_KEY, {
            "inside": {},          # tid -> bool
            "last_exit": None,     # (tid, ts)
            "min_pet": float("inf"),
            "critical": 0,
        })

        events: List[Dict[str, Any]] = []
        ts = time.time()
        for d in boxes or []:
            if not isinstance(d, dict):
                continue
            tid = d.get("track_id") if d.get("track_id") is not None else d.get("id")
            if tid is None:
                continue
            tid = int(tid)
            pt = anchor(d)
            if pt is None:
                continue
            inside = point_in_polygon(pt, polygon)
            was_inside = state["inside"].get(tid, False)
            if inside and not was_inside:
                # Track A entered. If a different track recently exited,
                # we have a PET.
                last = state["last_exit"]
                if last is not None and last[0] != tid:
                    pet = ts - last[1]
                    if pet < state["min_pet"]:
                        state["min_pet"] = pet
                    sev = (
                        "critical" if pet < 0.5 else
                        "warning" if pet < thr else
                        "info"
                    )
                    if sev == "critical":
                        state["critical"] += 1
                    events.append(make_event(
                        kind="near_miss",
                        severity=sev,
                        track_ids=[int(last[0]), tid],
                        ts_start=last[1], ts_end=ts,
                        metric=float(pet),
                        label=f"PET {pet:.2f}s @ {polygon.get('name')}",
                        details={
                            "polygon": polygon.get("name"),
                            "left_track": int(last[0]),
                            "arrived_track": int(tid),
                            "pet_s": float(pet),
                        },
                    ))
            elif was_inside and not inside:
                # Track exited the polygon.
                state["last_exit"] = (tid, ts)
            state["inside"][tid] = inside

        min_pet = state["min_pet"] if state["min_pet"] != float("inf") else 0.0
        return {
            "control_out": None,
            "events": events,
            "min_pet_s": float(min_pet),
            "critical_count": int(state["critical"]),
        }
