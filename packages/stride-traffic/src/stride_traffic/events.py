"""Discrete event detection nodes.

These nodes consume tracked detections (or read the per-run track
store) and emit ``traffic.event`` records for downstream aggregation,
visualisation, and reporting:

* Live detectors that scan the per-run track store:
  ``stopped_vehicle``, ``wrong_way``, ``hard_brake``, ``queue_length``.
* Stream-shape converters that bridge events into the existing
  list-of-floats / list-of-records consumers:
  ``timestamps``, ``filter``, ``merge``.
* Pipeline-friendly detectors that compose with detector outputs
  rather than literal numbers:
  ``travel_time`` (entry-line + exit-line crossing), ``annotate``
  (event overlay on the camera image).
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import numpy as np  # type: ignore
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None  # type: ignore

try:
    import cv2  # type: ignore
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    cv2 = None  # type: ignore

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.errors import (
    NodeInputError,
    NodeMissingDependencyError,
)
from stride_core.image_utils import (
    decode_image_to_numpy,
    encode_numpy_to_image,
)
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_any,
    t_boolean,
    t_control,
    t_detections2d,
    t_float,
    t_image,
    t_int,
    t_list,
    t_string,
)

from .roi import (
    detection_bottom_center,
    line_side,
    point_in_polygon,
)
from .types import (
    TrackState,
    get_track_store,
    is_event,
    is_line,
    is_polygon,
    make_event,
    t_traffic_event,
    t_traffic_line,
    t_traffic_polygon,
)


# ---------------------------------------------------------------------------
# traffic.events.stopped_vehicle
# ---------------------------------------------------------------------------


STOPPED_SPEC = NodeSpec(
    type="traffic.events.stopped_vehicle",
    version="1.0.0",
    display_name="Events · Stopped Vehicle",
    category="Traffic Events",
    summary="Emit an event for each vehicle stationary > min_duration_s in an ROI.",
    description=(
        "Reads a per-track trajectory store (populated upstream by "
        "``traffic.trajectory.accumulate`` or ``traffic.speed.estimate``) "
        "and tags any track whose recent mean speed has stayed below "
        "``threshold_kph`` for at least ``min_duration_s``."
    ),
    icon="square",
    tags=["traffic", "events", "stopped"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="store_key", type=t_string(), required=False,
                 default="speed"),
        PortSpec(name="threshold_kph", type=t_float(), required=False, default=3.0,
                 constraints={"min": 0.0}),
        PortSpec(name="min_duration_s", type=t_float(), required=False, default=5.0,
                 constraints={"min": 0.0}),
        PortSpec(name="polygon", type=t_traffic_polygon(), required=False,
                 default=None,
                 description="Optional ROI; when set, only stopped vehicles "
                             "inside this polygon are emitted"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="events", type=t_list(t_traffic_event())),
        PortSpec(name="count", type=t_int()),
    ],
    cache_policy="disabled",
)


_STOP_REPORTED_KEY = "stopped.reported"


def _track_recent_mean_speed(track: TrackState, window_s: float) -> Optional[float]:
    if len(track.history) < 2:
        return None
    last = track.history[-1]
    cutoff = float(last["ts"]) - window_s
    samples = [s for s in track.history if float(s.get("ts", 0.0)) >= cutoff]
    if len(samples) < 2:
        return None
    duration = float(samples[-1]["ts"] - samples[0]["ts"])
    if duration < window_s * 0.5:
        return None
    dx = float(samples[-1].get("x_w", 0.0) - samples[0].get("x_w", 0.0))
    dy = float(samples[-1].get("y_w", 0.0) - samples[0].get("y_w", 0.0))
    return math.sqrt(dx * dx + dy * dy) / max(1e-6, duration)


@register_node(STOPPED_SPEC)
class EventsStoppedNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        store_key = str(inputs.get("store_key") or "speed")
        thr_kph = float(inputs.get("threshold_kph") or 3.0)
        min_dur = float(inputs.get("min_duration_s") or 5.0)
        thr_mps = thr_kph / 3.6
        polygon = inputs.get("polygon")
        require_in_poly = is_polygon(polygon)

        bucket = ctx.node_resources.setdefault(self.id, {})
        reported = bucket.setdefault(_STOP_REPORTED_KEY, set())
        store = get_track_store(ctx, store_key)
        events: List[Dict[str, Any]] = []
        ts = time.time()
        for tid, track in store.items():
            mean_v = _track_recent_mean_speed(track, min_dur)
            if mean_v is None or mean_v >= thr_mps:
                continue
            if not track.history:
                continue
            last = track.history[-1]
            if require_in_poly:
                pt = [float(last.get("px", 0.0)), float(last.get("py", 0.0))]
                if not point_in_polygon(pt, polygon):
                    continue
            if int(tid) in reported:
                continue
            reported.add(int(tid))
            events.append(make_event(
                kind="stopped",
                severity="warning",
                track_ids=[int(tid)],
                ts_start=ts - min_dur,
                ts_end=ts,
                metric=float(mean_v),
                label=f"Track {tid} stopped {min_dur:.0f}s+",
                details={"mean_mps": float(mean_v)},
            ))
        # Forget tracks no longer in the store so they can re-trigger if
        # they reappear and stop again.
        active = set(int(t) for t in store.keys())
        for stale in list(reported):
            if stale not in active:
                reported.discard(stale)
        return {
            "control_out": None,
            "events": events,
            "count": len(events),
        }


# ---------------------------------------------------------------------------
# traffic.events.wrong_way
# ---------------------------------------------------------------------------


WRONG_SPEC = NodeSpec(
    type="traffic.events.wrong_way",
    version="1.0.0",
    display_name="Events · Wrong-Way Driving",
    category="Traffic Events",
    summary="Detect tracks moving against an expected direction vector.",
    description=(
        "Compares each track's velocity vector against an expected "
        "direction (in world frame, [dx, dy]). When the angle exceeds "
        "``angle_threshold_deg`` and the track has at least "
        "``min_speed_mps`` of motion, a ``wrong_way`` event is emitted."
    ),
    icon="alert-circle",
    tags=["traffic", "events", "wrong-way"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="store_key", type=t_string(), required=False,
                 default="speed"),
        PortSpec(name="expected_dx", type=t_float(), required=False, default=1.0,
                 description="Expected world-frame direction vector x"),
        PortSpec(name="expected_dy", type=t_float(), required=False, default=0.0,
                 description="Expected world-frame direction vector y"),
        PortSpec(name="angle_threshold_deg", type=t_float(), required=False,
                 default=110.0,
                 description="Track is wrong-way when angle > this",
                 constraints={"min": 0.0, "max": 180.0}),
        PortSpec(name="min_speed_mps", type=t_float(), required=False, default=2.0,
                 constraints={"min": 0.0}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="events", type=t_list(t_traffic_event())),
        PortSpec(name="count", type=t_int()),
    ],
    cache_policy="disabled",
)


_WRONG_REPORTED_KEY = "wrongway.reported"


@register_node(WRONG_SPEC)
class EventsWrongWayNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        store_key = str(inputs.get("store_key") or "speed")
        ex = float(inputs.get("expected_dx") or 1.0)
        ey = float(inputs.get("expected_dy") or 0.0)
        thr = float(inputs.get("angle_threshold_deg") or 110.0)
        min_v = float(inputs.get("min_speed_mps") or 2.0)
        store = get_track_store(ctx, store_key)
        bucket = ctx.node_resources.setdefault(self.id, {})
        reported = bucket.setdefault(_WRONG_REPORTED_KEY, set())
        en = math.hypot(ex, ey)
        if en < 1e-9:
            raise NodeInputError("expected direction vector is zero")
        ux, uy = ex / en, ey / en
        events: List[Dict[str, Any]] = []
        ts = time.time()
        for tid, track in store.items():
            if len(track.history) < 2:
                continue
            last = track.history[-1]
            cutoff = float(last["ts"]) - 0.5
            anchor = track.history[0]
            for i in range(len(track.history) - 2, -1, -1):
                if float(track.history[i]["ts"]) <= cutoff:
                    anchor = track.history[i]
                    break
            dt = max(1e-6, float(last["ts"] - anchor["ts"]))
            vx = float(last.get("x_w", 0.0) - anchor.get("x_w", 0.0)) / dt
            vy = float(last.get("y_w", 0.0) - anchor.get("y_w", 0.0)) / dt
            v = math.hypot(vx, vy)
            if v < min_v:
                continue
            cos_a = max(-1.0, min(1.0, (vx * ux + vy * uy) / max(1e-9, v)))
            angle_deg = math.degrees(math.acos(cos_a))
            if angle_deg < thr:
                continue
            if int(tid) in reported:
                continue
            reported.add(int(tid))
            events.append(make_event(
                kind="wrong_way",
                severity="critical",
                track_ids=[int(tid)],
                ts_start=ts,
                metric=float(angle_deg),
                label=f"Track {tid} wrong-way ({angle_deg:.0f}°)",
                details={"angle_deg": float(angle_deg), "speed_mps": float(v)},
            ))
        active = set(int(t) for t in store.keys())
        for stale in list(reported):
            if stale not in active:
                reported.discard(stale)
        return {
            "control_out": None,
            "events": events,
            "count": len(events),
        }


# ---------------------------------------------------------------------------
# traffic.events.hard_brake
# ---------------------------------------------------------------------------


BRAKE_SPEC = NodeSpec(
    type="traffic.events.hard_brake",
    version="1.0.0",
    display_name="Events · Hard Brake",
    category="Traffic Events",
    summary="Detect deceleration > threshold in m/s² over a window.",
    description=(
        "Reads the track-store, computes deceleration over the trailing "
        "``window_s`` seconds, and emits a hard_brake event when "
        "deceleration exceeds ``threshold_mps2``. AAA / FHWA studies "
        "use 3.4 m/s² as a typical threshold for a 'hard' brake."
    ),
    icon="alert-octagon",
    tags=["traffic", "events", "brake"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="store_key", type=t_string(), required=False,
                 default="speed"),
        PortSpec(name="threshold_mps2", type=t_float(), required=False,
                 default=3.4, constraints={"min": 0.0}),
        PortSpec(name="window_s", type=t_float(), required=False, default=1.0,
                 constraints={"min": 0.1}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="events", type=t_list(t_traffic_event())),
        PortSpec(name="count", type=t_int()),
    ],
    cache_policy="disabled",
)


@register_node(BRAKE_SPEC)
class EventsHardBrakeNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        from .trajectory import _track_speed_at  # local import to avoid cycles
        store_key = str(inputs.get("store_key") or "speed")
        thr = float(inputs.get("threshold_mps2") or 3.4)
        win = float(inputs.get("window_s") or 1.0)
        store = get_track_store(ctx, store_key)
        events: List[Dict[str, Any]] = []
        ts = time.time()
        for tid, track in store.items():
            if not track.history:
                continue
            t_now = float(track.history[-1]["ts"])
            v_now = _track_speed_at(track, t_now, win / 2.0)
            v_prev = _track_speed_at(track, t_now - win / 2.0, win / 2.0)
            if v_now is None or v_prev is None:
                continue
            a = (v_now - v_prev) / max(1e-6, win / 2.0)
            if a < -thr:
                events.append(make_event(
                    kind="hard_brake",
                    severity="warning",
                    track_ids=[int(tid)],
                    ts_start=ts,
                    metric=float(a),
                    label=f"Track {tid} brake {a:.1f}m/s²",
                    details={"accel_mps2": float(a)},
                ))
        return {"control_out": None, "events": events, "count": len(events)}


# ---------------------------------------------------------------------------
# traffic.events.queue_length
# ---------------------------------------------------------------------------


QUEUE_SPEC = NodeSpec(
    type="traffic.events.queue_length",
    version="1.0.0",
    display_name="Events · Queue Length",
    category="Traffic Events",
    summary="Estimate queue length from stopped vehicles in a polygon.",
    description=(
        "Counts the number of tracks inside ``polygon`` whose recent "
        "speed is below ``threshold_kph``, then multiplies by the "
        "average vehicle spacing to estimate queue length in metres."
    ),
    icon="bar-chart",
    tags=["traffic", "events", "queue"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="store_key", type=t_string(), required=False,
                 default="speed"),
        PortSpec(name="polygon", type=t_traffic_polygon(), required=True),
        PortSpec(name="threshold_kph", type=t_float(), required=False, default=5.0,
                 constraints={"min": 0.0}),
        PortSpec(name="vehicle_spacing_m", type=t_float(), required=False,
                 default=7.5,
                 description="Mean spacing per stopped vehicle (m)",
                 constraints={"min": 1.0}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="queue_count", type=t_int()),
        PortSpec(name="queue_length_m", type=t_float()),
        PortSpec(name="events", type=t_list(t_traffic_event())),
    ],
    cache_policy="disabled",
)


@register_node(QUEUE_SPEC)
class EventsQueueNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        store_key = str(inputs.get("store_key") or "speed")
        polygon = inputs.get("polygon")
        if not is_polygon(polygon):
            raise NodeInputError("polygon required", port="polygon")
        thr_kph = float(inputs.get("threshold_kph") or 5.0)
        spacing = float(inputs.get("vehicle_spacing_m") or 7.5)
        thr_mps = thr_kph / 3.6
        store = get_track_store(ctx, store_key)
        n = 0
        for tid, track in store.items():
            mean_v = _track_recent_mean_speed(track, 2.0)
            if mean_v is None or mean_v >= thr_mps:
                continue
            if not track.history:
                continue
            last = track.history[-1]
            pt = [float(last.get("px", 0.0)), float(last.get("py", 0.0))]
            if point_in_polygon(pt, polygon):
                n += 1
        length = float(n) * spacing
        events: List[Dict[str, Any]] = []
        if n > 0:
            events.append(make_event(
                kind="queue",
                severity="warning" if n >= 5 else "info",
                track_ids=[],
                ts_start=time.time(),
                metric=float(length),
                label=f"Queue {n} vehs / {length:.0f}m in '{polygon.get('name')}'",
                details={"queue_count": int(n), "polygon": polygon.get("name")},
            ))
        return {
            "control_out": None,
            "queue_count": int(n),
            "queue_length_m": float(length),
            "events": events,
        }


# ---------------------------------------------------------------------------
# traffic.events.merge — collect events from up to 8 inputs
# ---------------------------------------------------------------------------


MERGE_SPEC = NodeSpec(
    type="traffic.events.merge",
    version="1.0.0",
    display_name="Events · Merge",
    category="Traffic Events",
    summary="Combine event lists from up to 8 detectors.",
    description="Concatenates event lists; preserves order.",
    icon="git-merge",
    tags=["traffic", "events"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
    ] + [
        PortSpec(name=f"events_{i}", type=t_list(t_traffic_event()),
                 required=False, default=[])
        for i in range(1, 9)
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="events", type=t_list(t_traffic_event())),
        PortSpec(name="count", type=t_int()),
    ],
    cache_policy="auto",
)


@register_node(MERGE_SPEC)
class EventsMergeNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        out: List[Dict[str, Any]] = []
        for i in range(1, 9):
            v = inputs.get(f"events_{i}") or []
            for e in v:
                if is_event(e):
                    out.append(e)
        return {"control_out": None, "events": out, "count": len(out)}


# ---------------------------------------------------------------------------
# traffic.events.timestamps — bridge events into list<float> consumers
# ---------------------------------------------------------------------------


TIMESTAMPS_SPEC = NodeSpec(
    type="traffic.events.timestamps",
    version="1.0.0",
    display_name="Events · Extract Timestamps",
    category="Traffic Events",
    summary="Pull ts_start (or a numeric metric) out of every event.",
    description=(
        "Unblocks chaining a live event stream into the existing "
        "list-of-float consumers (``traffic.report.time_bin``, "
        "``traffic.safety.headway``, ``traffic.report.percentile_bundle``, "
        "etc.). Pick ``field=ts_start`` for crossing-times, ``ts_end`` for "
        "exit-times, or ``metric`` for whatever numeric value the upstream "
        "detector chose to attach."
    ),
    icon="clock",
    tags=["traffic", "events", "bridge"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="events", type=t_list(t_traffic_event()), required=True),
        PortSpec(
            name="field", type=t_string(), required=False, default="ts_start",
            description="Which numeric field to extract",
            constraints={"enum": ["ts_start", "ts_end", "metric"]},
        ),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="values", type=t_list(t_float())),
        PortSpec(name="count", type=t_int()),
    ],
    cache_policy="auto",
)


@register_node(TIMESTAMPS_SPEC)
class EventsTimestampsNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        events = [e for e in (inputs.get("events") or []) if is_event(e)]
        field = str(inputs.get("field") or "ts_start")
        out: List[float] = []
        for e in events:
            v = e.get(field)
            if v is None:
                continue
            try:
                out.append(float(v))
            except (TypeError, ValueError):
                continue
        return {"control_out": None, "values": out, "count": len(out)}


# ---------------------------------------------------------------------------
# traffic.events.filter — keep events matching kind/severity/track-id
# ---------------------------------------------------------------------------


FILTER_SPEC = NodeSpec(
    type="traffic.events.filter",
    version="1.0.0",
    display_name="Events · Filter",
    category="Traffic Events",
    summary="Subset events by kind / severity.",
    description=(
        "Returns a copy of the input events list keeping only entries "
        "that match the (optional) ``kind`` and ``severity`` filters. Empty "
        "filter strings mean 'don't filter on this field'."
    ),
    icon="filter",
    tags=["traffic", "events"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="events", type=t_list(t_traffic_event()), required=True),
        PortSpec(name="kind", type=t_string(), required=False, default="",
                 description='Match an exact "kind" (or "" for any)'),
        PortSpec(name="severity", type=t_string(), required=False, default="",
                 description='"info" | "warning" | "critical" | "" for any',
                 constraints={"enum": ["", "info", "warning", "critical"]}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="events", type=t_list(t_traffic_event())),
        PortSpec(name="count", type=t_int()),
    ],
    cache_policy="auto",
)


@register_node(FILTER_SPEC)
class EventsFilterNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        events = [e for e in (inputs.get("events") or []) if is_event(e)]
        kind = (inputs.get("kind") or "").strip().lower()
        sev = (inputs.get("severity") or "").strip().lower()
        out: List[Dict[str, Any]] = []
        for e in events:
            if kind and str(e.get("kind") or "").lower() != kind:
                continue
            if sev and str(e.get("severity") or "").lower() != sev:
                continue
            out.append(e)
        return {"control_out": None, "events": out, "count": len(out)}


# ---------------------------------------------------------------------------
# traffic.events.travel_time — link entry-line + exit-line crossings per track
# ---------------------------------------------------------------------------


TRAVEL_SPEC = NodeSpec(
    type="traffic.events.travel_time",
    version="1.0.0",
    display_name="Events · Travel Time",
    category="Traffic Events",
    summary="Stamp each track's elapsed time between two virtual lines.",
    description=(
        "On every frame, observes which tracks crossed ``entry_line`` and "
        "``exit_line``. The first time a given track is seen on the +side of "
        "``entry_line`` we record the entry timestamp; when it later flips "
        "across ``exit_line`` (regardless of direction) we emit a "
        "``line_cross`` event whose ``metric`` is the travel time in "
        "seconds. Stateful — per-run, per-node."
    ),
    icon="clock",
    tags=["traffic", "events", "travel-time"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d(), required=True),
        PortSpec(name="entry_line", type=t_traffic_line(), required=True),
        PortSpec(name="exit_line", type=t_traffic_line(), required=True),
        PortSpec(name="reference", type=t_string(), required=False,
                 default="bottom",
                 constraints={"enum": ["center", "bottom"]}),
        PortSpec(name="reset", type=t_boolean(), required=False, default=False),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="events", type=t_list(t_traffic_event()),
                 description="One event per fresh entry->exit completion this frame"),
        PortSpec(name="completed_total", type=t_int()),
        PortSpec(name="active_total", type=t_int(),
                 description="Tracks that crossed entry but not yet exit"),
    ],
    cache_policy="disabled",
)


_TRAVEL_KEY = "travel_time.state"


def _crossed(line: Dict[str, Any], prev_pt: Optional[List[float]],
             cur_pt: List[float]) -> bool:
    if prev_pt is None:
        return False
    return (line_side(line, prev_pt) > 0) != (line_side(line, cur_pt) > 0)


@register_node(TRAVEL_SPEC)
class EventsTravelTimeNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        det = inputs.get("detections") or {}
        boxes = det.get("boxes") if isinstance(det, dict) else (det or [])
        entry = inputs.get("entry_line")
        exit_ = inputs.get("exit_line")
        if not (is_line(entry) and is_line(exit_)):
            raise NodeInputError("entry_line and exit_line are required")
        ref = str(inputs.get("reference") or "bottom")
        anchor = (
            detection_bottom_center
            if ref == "bottom"
            else (lambda d: [(d["x1"] + d["x2"]) / 2.0,
                             (d["y1"] + d["y2"]) / 2.0])
        )
        reset = bool(inputs.get("reset") or False)

        bucket = ctx.node_resources.setdefault(self.id, {})
        if reset or _TRAVEL_KEY not in bucket:
            bucket[_TRAVEL_KEY] = {
                "last_pt": {},      # tid -> [x, y]
                "entry_ts": {},     # tid -> ts of entry crossing
                "completed": 0,
            }
        state = bucket[_TRAVEL_KEY]

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
            prev = state["last_pt"].get(tid)
            # Detect entry crossing
            if tid not in state["entry_ts"] and _crossed(entry, prev, pt):
                state["entry_ts"][tid] = ts
            # Detect exit crossing
            elif tid in state["entry_ts"] and _crossed(exit_, prev, pt):
                t_entry = state["entry_ts"].pop(tid)
                travel_s = float(ts - t_entry)
                state["completed"] += 1
                events.append(make_event(
                    kind="line_cross",
                    severity="info",
                    track_ids=[tid], ts_start=t_entry, ts_end=ts,
                    metric=travel_s,
                    label=f"Track {tid}: {travel_s:.1f}s "
                          f"({entry.get('name')}->{exit_.get('name')})",
                    details={
                        "travel_s": travel_s,
                        "entry": entry.get("name"),
                        "exit": exit_.get("name"),
                        "class_name": d.get("class_name"),
                    },
                ))
            state["last_pt"][tid] = pt

        return {
            "control_out": None,
            "events": events,
            "completed_total": int(state["completed"]),
            "active_total": len(state["entry_ts"]),
        }


# ---------------------------------------------------------------------------
# traffic.events.annotate — overlay events + ROI on the camera image
# ---------------------------------------------------------------------------


_SEVERITY_BGR = {
    "info":     (240, 200, 80),    # cyan-ish
    "warning":  (60, 200, 250),    # orange
    "critical": (60, 60, 240),     # red
}


ANNOTATE_SPEC = NodeSpec(
    type="traffic.events.annotate",
    version="1.0.0",
    display_name="Events · Annotate Image",
    category="Traffic Events",
    summary="Draw event markers + ROI lines/polygons over the source image.",
    description=(
        "Renders a visual overlay on top of the input image:\n\n"
        "* every line in ``lines`` is drawn as an arrow (direction = a → b)\n"
        "* every polygon in ``polygons`` is outlined\n"
        "* the most-recent severity colour from ``events`` is used as the "
        "  border colour, plus a small caption listing kinds + counts\n\n"
        "Useful as the final 'paint' stage before showing the camera view "
        "on a dashboard widget."
    ),
    icon="layers",
    tags=["traffic", "events", "annotate"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_image(), required=True),
        PortSpec(name="events", type=t_list(t_traffic_event()),
                 required=False, default=[]),
        PortSpec(name="lines", type=t_list(t_traffic_line()),
                 required=False, default=[]),
        PortSpec(name="polygons", type=t_list(t_traffic_polygon()),
                 required=False, default=[]),
        PortSpec(name="thickness", type=t_int(), required=False, default=2,
                 constraints={"min": 1, "max": 10}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_image()),
        PortSpec(name="event_count", type=t_int()),
    ],
    cache_policy="disabled",
)


def _require_imaging() -> None:
    if not HAS_NUMPY:
        raise NodeMissingDependencyError("numpy required for annotate")
    if not HAS_CV2:
        raise NodeMissingDependencyError("opencv-python required for annotate")


@register_node(ANNOTATE_SPEC)
class EventsAnnotateNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_imaging()
        # Accept either the canonical Image record or the string data URL —
        # `decode_image_to_numpy` handles both forms transparently.
        image_in = inputs.get("image")
        if not image_in:
            raise NodeInputError("image required", port="image")
        thickness = int(inputs.get("thickness") or 2)
        events = [e for e in (inputs.get("events") or []) if is_event(e)]
        lines = [l for l in (inputs.get("lines") or []) if is_line(l)]
        polys = [p for p in (inputs.get("polygons") or []) if is_polygon(p)]

        img = decode_image_to_numpy(image_in)
        h, w = img.shape[:2]

        # --- ROI overlays -------------------------------------------------
        for ln in lines:
            a = ln.get("a") or [0, 0]
            b = ln.get("b") or [0, 0]
            try:
                pa = (int(round(a[0])), int(round(a[1])))
                pb = (int(round(b[0])), int(round(b[1])))
            except (IndexError, ValueError):
                continue
            cv2.arrowedLine(img, pa, pb, (60, 200, 250), thickness, tipLength=0.05)
            name = ln.get("name") or ""
            if name:
                tx = (pa[0] + pb[0]) // 2
                ty = (pa[1] + pb[1]) // 2 - 6
                cv2.putText(img, str(name), (tx, ty),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                            (255, 255, 255), 1, cv2.LINE_AA)
        for pg in polys:
            pts_raw = pg.get("points") or []
            if len(pts_raw) < 3:
                continue
            pts = np.asarray(
                [[int(round(p[0])), int(round(p[1]))] for p in pts_raw],
                dtype=np.int32,
            )
            cv2.polylines(img, [pts], isClosed=True,
                          color=(80, 240, 80), thickness=thickness)
            name = pg.get("name") or ""
            if name:
                cv2.putText(img, str(name), tuple(pts[0]),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                            (255, 255, 255), 1, cv2.LINE_AA)

        # --- Event border + caption --------------------------------------
        if events:
            severities = {e.get("severity") for e in events}
            if "critical" in severities:
                border = _SEVERITY_BGR["critical"]
            elif "warning" in severities:
                border = _SEVERITY_BGR["warning"]
            else:
                border = _SEVERITY_BGR["info"]
            cv2.rectangle(img, (1, 1), (w - 2, h - 2), border, thickness)
            # Caption: kinds + counts
            counts: Dict[str, int] = {}
            for e in events:
                k = str(e.get("kind") or "")
                counts[k] = counts.get(k, 0) + 1
            caption = " ".join(f"{k}={v}" for k, v in counts.items())[:120]
            cv2.rectangle(img, (0, 0), (min(w, 460), 26), (0, 0, 0), -1)
            cv2.putText(img, caption, (6, 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (240, 240, 240), 1, cv2.LINE_AA)

        # Match the rest of the image-pipeline convention: emit the data
        # URL string directly so YOLO / ByteTrack / display widgets can
        # consume it without an extra extraction step.
        out_b64 = encode_numpy_to_image(img, fmt="jpeg", quality=85)
        return {
            "control_out": None,
            "image": out_b64,
            "event_count": len(events),
        }
