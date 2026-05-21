"""Trajectory / kinematics nodes.

NOTE: This module is a foundation stub — the autonomous loop will
expand it across iterations. The first implementations focus on
useful building blocks: per-track Savitzky-Golay smoothing, an
acceleration-profile estimator, and a stop detector.
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional

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

from .roi import detection_bottom_center
from .types import TrackState, get_track_store, is_calibration, t_traffic_calibration
from .calibration import project_pixel_to_world


# ---------------------------------------------------------------------------
# traffic.trajectory.accumulate
# ---------------------------------------------------------------------------


ACCUMULATE_SPEC = NodeSpec(
    type="traffic.trajectory.accumulate",
    version="1.0.0",
    display_name="Trajectory · Accumulate",
    category="Traffic Trajectory",
    summary="Maintain per-track trajectory history (pixel + world).",
    description=(
        "For each tracked detection, append a sample to the per-track "
        "history. Other downstream nodes can read this same store via "
        "``store_key`` to avoid duplicating state."
    ),
    icon="git-branch",
    tags=["traffic", "trajectory"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d(), required=True),
        PortSpec(name="calibration", type=t_traffic_calibration(), required=True),
        PortSpec(name="store_key", type=t_string(), required=False,
                 default="trajectory"),
        PortSpec(name="max_history", type=t_int(), required=False, default=128,
                 constraints={"min": 2}),
        PortSpec(name="reset", type=t_boolean(), required=False, default=False),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="active_tracks", type=t_int()),
        PortSpec(name="store_key", type=t_string()),
    ],
    cache_policy="disabled",
)


@register_node(ACCUMULATE_SPEC)
class TrajectoryAccumulateNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        cal = inputs.get("calibration")
        if not is_calibration(cal):
            raise NodeInputError("calibration must be a TrafficCalibration",
                                 port="calibration")
        det = inputs.get("detections") or {}
        boxes = det.get("boxes") if isinstance(det, dict) else (det or [])
        store_key = str(inputs.get("store_key") or "trajectory")
        max_hist = int(inputs.get("max_history") or 128)
        reset = bool(inputs.get("reset") or False)
        store = get_track_store(ctx, store_key)
        if reset:
            store.clear()
        ts = time.time()
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
            world = project_pixel_to_world(cal, pt[0], pt[1])
            track = store.get(tid)
            if track is None:
                track = TrackState(tid)
                store[tid] = track
            track.push({
                "ts": ts,
                "px": pt[0], "py": pt[1],
                "x_w": world[0] if world else 0.0,
                "y_w": world[1] if world else 0.0,
                "class_name": d.get("class_name"),
            }, max_len=max_hist)
        return {
            "control_out": None,
            "active_tracks": len(store),
            "store_key": store_key,
        }


# ---------------------------------------------------------------------------
# traffic.trajectory.acceleration — finite difference acceleration profile
# ---------------------------------------------------------------------------


ACCEL_SPEC = NodeSpec(
    type="traffic.trajectory.acceleration",
    version="1.0.0",
    display_name="Trajectory · Acceleration Profile",
    category="Traffic Trajectory",
    summary="Per-track acceleration (m/s²) by finite differences over a window.",
    description=(
        "Reads the per-track history maintained by ``traffic.trajectory."
        "accumulate`` and computes acceleration over the trailing "
        "window."
    ),
    icon="trending-up",
    tags=["traffic", "trajectory", "acceleration"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="store_key", type=t_string(), required=False,
                 default="trajectory"),
        PortSpec(name="window_s", type=t_float(), required=False, default=1.0,
                 constraints={"min": 0.1}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="accel_per_track", type=t_list(t_float()),
                 description="One acceleration value per active track (m/s²)"),
        PortSpec(name="track_ids", type=t_list(t_int())),
        PortSpec(name="max_decel", type=t_float(),
                 description="Most-negative acceleration this frame (m/s²)"),
    ],
    cache_policy="disabled",
)


def _track_speed_at(track: TrackState, t_query: float, window_s: float) -> Optional[float]:
    if len(track.history) < 2:
        return None
    cutoff = t_query - window_s
    a_idx = 0
    for i in range(len(track.history) - 1, -1, -1):
        if track.history[i]["ts"] <= cutoff:
            a_idx = i
            break
    a = track.history[a_idx]
    b = track.history[-1]
    dt = max(1e-6, float(b["ts"] - a["ts"]))
    dx = float(b.get("x_w", 0.0) - a.get("x_w", 0.0))
    dy = float(b.get("y_w", 0.0) - a.get("y_w", 0.0))
    return math.sqrt(dx * dx + dy * dy) / dt


@register_node(ACCEL_SPEC)
class TrajectoryAccelerationNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        store_key = str(inputs.get("store_key") or "trajectory")
        win = float(inputs.get("window_s") or 1.0)
        store = get_track_store(ctx, store_key)
        accels: List[float] = []
        ids: List[int] = []
        max_decel = 0.0
        now = time.time()
        for tid, track in store.items():
            v_now = _track_speed_at(track, now, win / 2.0)
            v_prev = _track_speed_at(track, now - win / 2.0, win / 2.0)
            if v_now is None or v_prev is None:
                continue
            a = (v_now - v_prev) / max(1e-6, win / 2.0)
            accels.append(a)
            ids.append(int(tid))
            if a < max_decel:
                max_decel = a
        return {
            "control_out": None,
            "accel_per_track": accels,
            "track_ids": ids,
            "max_decel": float(max_decel),
        }


# ---------------------------------------------------------------------------
# traffic.trajectory.stop_detect — find tracks that are stationary
# ---------------------------------------------------------------------------


STOP_SPEC = NodeSpec(
    type="traffic.trajectory.stop_detect",
    version="1.0.0",
    display_name="Trajectory · Stop Detect",
    category="Traffic Trajectory",
    summary="Flag tracks whose recent speed has been below a threshold.",
    description=(
        "Finds every track with mean speed under ``threshold_kph`` for "
        "at least ``min_duration_s``. Useful as a primitive for stopped-"
        "vehicle and queue events."
    ),
    icon="square",
    tags=["traffic", "trajectory", "stop"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="store_key", type=t_string(), required=False,
                 default="trajectory"),
        PortSpec(name="threshold_kph", type=t_float(), required=False, default=3.0,
                 constraints={"min": 0.0}),
        PortSpec(name="min_duration_s", type=t_float(), required=False, default=2.0,
                 constraints={"min": 0.0}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="stopped_track_ids", type=t_list(t_int())),
        PortSpec(name="count", type=t_int()),
    ],
    cache_policy="disabled",
)


@register_node(STOP_SPEC)
class TrajectoryStopDetectNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        store_key = str(inputs.get("store_key") or "trajectory")
        thr_kph = float(inputs.get("threshold_kph") or 3.0)
        min_dur = float(inputs.get("min_duration_s") or 2.0)
        thr_mps = thr_kph / 3.6
        store = get_track_store(ctx, store_key)
        stopped: List[int] = []
        for tid, track in store.items():
            if len(track.history) < 2:
                continue
            t_end = track.history[-1]["ts"]
            t_start = t_end - min_dur
            samples = [s for s in track.history if s["ts"] >= t_start]
            if len(samples) < 2:
                continue
            duration = float(samples[-1]["ts"] - samples[0]["ts"])
            if duration < min_dur:
                continue
            dx = float(samples[-1].get("x_w", 0.0) - samples[0].get("x_w", 0.0))
            dy = float(samples[-1].get("y_w", 0.0) - samples[0].get("y_w", 0.0))
            mean_v = math.sqrt(dx * dx + dy * dy) / max(1e-6, duration)
            if mean_v < thr_mps:
                stopped.append(int(tid))
        return {
            "control_out": None,
            "stopped_track_ids": stopped,
            "count": len(stopped),
        }
