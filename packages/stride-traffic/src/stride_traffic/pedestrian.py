"""Pedestrian and bicycle analysis nodes.

Pedestrian and bike-specific metrics are usually derived from the same
detection / tracking primitives used for vehicles, but with different
class filters and tighter spatial / temporal thresholds.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.errors import NodeInputError
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_any,
    t_control,
    t_detections2d,
    t_float,
    t_int,
    t_list,
    t_string,
)

from .roi import detection_bottom_center, point_in_polygon
from .types import (
    TrackState,
    get_track_store,
    is_polygon,
    make_event,
    t_traffic_event,
    t_traffic_polygon,
)


# ---------------------------------------------------------------------------
# traffic.pedestrian.filter — keep only pedestrian-class detections
# ---------------------------------------------------------------------------


FILTER_SPEC = NodeSpec(
    type="traffic.pedestrian.filter",
    version="1.0.0",
    display_name="Pedestrian · Filter",
    category="Traffic Pedestrian",
    summary="Drop non-pedestrian detections by class name.",
    description=(
        "Keeps detections whose ``class_name`` is in the configured "
        "list. Defaults to {person, pedestrian}. Useful as the first "
        "stage of a pedestrian-specific pipeline."
    ),
    icon="user",
    tags=["traffic", "pedestrian"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d(), required=True),
        PortSpec(name="class_names", type=t_list(t_string()), required=False,
                 default=["person", "pedestrian"]),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d()),
        PortSpec(name="count", type=t_int()),
    ],
    cache_policy="auto",
)


@register_node(FILTER_SPEC)
class PedestrianFilterNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        det = inputs.get("detections") or {}
        cls = set(s.lower() for s in (inputs.get("class_names") or ["person"]))
        boxes = det.get("boxes") if isinstance(det, dict) else (det or [])
        keep = [b for b in boxes or [] if isinstance(b, dict) and
                str(b.get("class_name") or "").lower() in cls]
        if isinstance(det, dict):
            out = dict(det)
            out["boxes"] = keep
        else:
            out = {
                "_type": "Detections2D",
                "image_width": 0,
                "image_height": 0,
                "boxes": keep,
                "image": None,
            }
        return {"control_out": None, "detections": out, "count": len(keep)}


# ---------------------------------------------------------------------------
# traffic.pedestrian.crossing_count — count peds passing through ROI
# ---------------------------------------------------------------------------


CROSSING_SPEC = NodeSpec(
    type="traffic.pedestrian.crossing_count",
    version="1.0.0",
    display_name="Pedestrian · Crossing Count",
    category="Traffic Pedestrian",
    summary="Count peds whose track-bottom passes through a polygon.",
    description=(
        "Polygon-based crossing tally — each unique track is counted "
        "at most once. Use multiple polygons to monitor concurrent "
        "crosswalks."
    ),
    icon="users",
    tags=["traffic", "pedestrian", "crosswalk"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d(), required=True),
        PortSpec(name="polygon", type=t_traffic_polygon(), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="crossings", type=t_int()),
        PortSpec(name="track_ids", type=t_list(t_int())),
    ],
    cache_policy="disabled",
)


@register_node(CROSSING_SPEC)
class PedestrianCrossingNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        det = inputs.get("detections") or {}
        polygon = inputs.get("polygon")
        if not is_polygon(polygon):
            raise NodeInputError("polygon required", port="polygon")
        boxes = det.get("boxes") if isinstance(det, dict) else (det or [])
        bucket = ctx.node_resources.setdefault(self.id, {})
        seen = bucket.setdefault("ped_seen", set())
        for d in boxes or []:
            if not isinstance(d, dict):
                continue
            tid = d.get("track_id") if d.get("track_id") is not None else d.get("id")
            if tid is None or int(tid) in seen:
                continue
            pt = detection_bottom_center(d)
            if pt is None:
                continue
            if point_in_polygon(pt, polygon):
                seen.add(int(tid))
        return {
            "control_out": None,
            "crossings": len(seen),
            "track_ids": sorted(seen),
        }


# ---------------------------------------------------------------------------
# traffic.pedestrian.vehicle_conflict — peds vs vehicles TTC
# ---------------------------------------------------------------------------


PED_CONFLICT_SPEC = NodeSpec(
    type="traffic.pedestrian.vehicle_conflict",
    version="1.0.0",
    display_name="Pedestrian · Vehicle Conflict",
    category="Traffic Pedestrian",
    summary="TTC between every (pedestrian, vehicle) track pair.",
    description=(
        "Restricts the pairwise-TTC computation to pedestrian-vs-vehicle "
        "pairs only. The pedestrian and vehicle stores must already be "
        "populated by ``traffic.speed.estimate`` or "
        "``traffic.trajectory.accumulate``."
    ),
    icon="alert-triangle",
    tags=["traffic", "pedestrian", "ttc"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="ped_store_key", type=t_string(), required=False,
                 default="pedestrian"),
        PortSpec(name="veh_store_key", type=t_string(), required=False,
                 default="speed"),
        PortSpec(name="threshold_s", type=t_float(), required=False, default=2.5,
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


def _ttc_pair(a, b) -> Optional[float]:
    ax, ay, avx, avy = a
    bx, by, bvx, bvy = b
    rx = bx - ax
    ry = by - ay
    rvx = bvx - avx
    rvy = bvy - avy
    rv2 = rvx * rvx + rvy * rvy
    if rv2 < 1e-9:
        return None
    t = -(rx * rvx + ry * rvy) / rv2
    if t <= 0:
        return None
    return float(t)


def _track_pos_vel(track: TrackState):
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


@register_node(PED_CONFLICT_SPEC)
class PedestrianVehicleConflictNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        ped_key = str(inputs.get("ped_store_key") or "pedestrian")
        veh_key = str(inputs.get("veh_store_key") or "speed")
        thr = float(inputs.get("threshold_s") or 2.5)
        ped = get_track_store(ctx, ped_key)
        veh = get_track_store(ctx, veh_key)
        ped_snap = {tid: _track_pos_vel(t) for tid, t in ped.items()}
        veh_snap = {tid: _track_pos_vel(t) for tid, t in veh.items()}
        events: List[Dict[str, Any]] = []
        min_ttc = float("inf")
        critical = 0
        ts = time.time()
        for ptid, pa in ped_snap.items():
            if pa is None:
                continue
            for vtid, va in veh_snap.items():
                if va is None:
                    continue
                t = _ttc_pair(pa, va)
                if t is None:
                    continue
                if t < min_ttc:
                    min_ttc = t
                if t < thr:
                    sev = "critical" if t < 0.8 else "warning"
                    if sev == "critical":
                        critical += 1
                    events.append(make_event(
                        kind="ped_conflict",
                        severity=sev,
                        track_ids=[int(ptid), int(vtid)],
                        ts_start=ts,
                        metric=float(t),
                        label=f"Ped {ptid} vs Veh {vtid} TTC {t:.2f}s",
                        details={"ttc_s": float(t)},
                    ))
        return {
            "control_out": None,
            "events": events,
            "min_ttc_s": float(min_ttc) if min_ttc != float("inf") else 0.0,
            "critical_count": int(critical),
        }


# ---------------------------------------------------------------------------
# traffic.pedestrian.walking_speed
# ---------------------------------------------------------------------------


WALKING_SPEC = NodeSpec(
    type="traffic.pedestrian.walking_speed",
    version="1.0.0",
    display_name="Pedestrian · Walking Speed",
    category="Traffic Pedestrian",
    summary="Mean / median walking speed of active pedestrian tracks.",
    description=(
        "Computes the mean and median speed of pedestrians in the "
        "configured store. HCM design walking speed is 1.2 m/s for "
        "able-bodied adults; older / mobility-impaired peds use 1.0 m/s."
    ),
    icon="user-check",
    tags=["traffic", "pedestrian", "speed"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="store_key", type=t_string(), required=False,
                 default="pedestrian"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="mean_mps", type=t_float()),
        PortSpec(name="median_mps", type=t_float()),
        PortSpec(name="n", type=t_int()),
    ],
    cache_policy="disabled",
)


@register_node(WALKING_SPEC)
class PedestrianWalkingSpeedNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        store = get_track_store(ctx, str(inputs.get("store_key") or "pedestrian"))
        speeds: List[float] = []
        for tid, track in store.items():
            s = _track_pos_vel(track)
            if s is None:
                continue
            v = math.sqrt(s[2] ** 2 + s[3] ** 2)
            if v > 0:
                speeds.append(v)
        if not speeds:
            return {"control_out": None, "mean_mps": 0.0, "median_mps": 0.0, "n": 0}
        speeds_sorted = sorted(speeds)
        median = speeds_sorted[len(speeds_sorted) // 2]
        return {
            "control_out": None,
            "mean_mps": float(sum(speeds) / len(speeds)),
            "median_mps": float(median),
            "n": len(speeds),
        }
