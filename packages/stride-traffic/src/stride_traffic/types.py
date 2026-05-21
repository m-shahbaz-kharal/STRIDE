"""Shared type factories and helpers for the traffic package.

Defines two new domain record kinds:

- ``traffic.calibration`` — a per-camera intrinsic + extrinsic record
  consumed by every speed / counting / safety node that needs to
  convert pixel coordinates into world (metric) units.
- ``traffic.event`` — a uniform discrete-event record emitted by
  detectors (stopped vehicle, wrong-way, near-miss, hard-brake, …) so
  downstream aggregators / writers can treat them homogeneously.

Both kinds are namespaced under ``traffic.*`` per the design doc rule
that plugin packages must not pollute the canonical taxonomy.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from stride_core.typesystem import (
    TypeDescriptor,
    t_any,
    t_boolean,
    t_float,
    t_int,
    t_list,
    t_map,
    t_record_kind,
    t_string,
)


# ---------------------------------------------------------------------------
# traffic.calibration
# ---------------------------------------------------------------------------


def t_traffic_calibration() -> TypeDescriptor:
    """Per-camera calibration: intrinsics + ground-plane homography.

    Wire form::

        {
            "_type": "TrafficCalibration",
            "fx": float, "fy": float,
            "cx": float, "cy": float,
            "image_width": int,
            "image_height": int,
            "homography": list[list[float]],  # 3x3 row-major, image px -> world m
            "vanishing_point": [float, float] | None,
            "scale_m_per_px": float | None,
            "frame": str,
        }
    """
    return t_record_kind(
        "traffic.calibration",
        fields={
            "_type": t_string(),
            "fx": t_float(),
            "fy": t_float(),
            "cx": t_float(),
            "cy": t_float(),
            "image_width": t_int(),
            "image_height": t_int(),
            "homography": t_list(t_list(t_float())),
            "vanishing_point": t_list(t_float()).with_nullable(True),
            "scale_m_per_px": t_float().with_nullable(True),
            "frame": t_string(),
        },
    )


def make_calibration(
    *,
    image_width: int,
    image_height: int,
    fx: Optional[float] = None,
    fy: Optional[float] = None,
    cx: Optional[float] = None,
    cy: Optional[float] = None,
    homography: Optional[List[List[float]]] = None,
    vanishing_point: Optional[List[float]] = None,
    scale_m_per_px: Optional[float] = None,
    frame: str = "world",
) -> Dict[str, Any]:
    """Construct a calibration dict, filling sensible defaults."""
    if fx is None:
        fx = float(max(image_width, image_height))
    if fy is None:
        fy = fx
    if cx is None:
        cx = float(image_width) / 2.0
    if cy is None:
        cy = float(image_height) / 2.0
    if homography is None:
        # Identity scaled by scale_m_per_px (or 1.0): pixels -> "metres" with
        # 1:1 mapping. Downstream nodes should still produce numeric output;
        # callers wanting real-world values should provide a real H.
        s = float(scale_m_per_px) if scale_m_per_px else 1.0
        homography = [[s, 0.0, 0.0], [0.0, s, 0.0], [0.0, 0.0, 1.0]]
    return {
        "_type": "TrafficCalibration",
        "fx": float(fx),
        "fy": float(fy),
        "cx": float(cx),
        "cy": float(cy),
        "image_width": int(image_width),
        "image_height": int(image_height),
        "homography": [[float(v) for v in row] for row in homography],
        "vanishing_point": (
            [float(vanishing_point[0]), float(vanishing_point[1])]
            if vanishing_point is not None
            else None
        ),
        "scale_m_per_px": (
            float(scale_m_per_px) if scale_m_per_px is not None else None
        ),
        "frame": str(frame),
    }


def is_calibration(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("_type") == "TrafficCalibration"
        and "homography" in value
    )


# ---------------------------------------------------------------------------
# traffic.line / traffic.polygon — geometry primitives in pixel coords
# ---------------------------------------------------------------------------


def t_traffic_line() -> TypeDescriptor:
    """A directed line segment in image (pixel) coordinates.

    Used by line-crossing counters. Direction matters: a track moving
    from the right side of the line to the left counts as ``backward``;
    left to right is ``forward``. The orientation is determined by the
    line's own (a -> b) sense.
    """
    return t_record_kind(
        "traffic.line",
        fields={
            "_type": t_string(),
            "name": t_string(),
            "a": t_list(t_float()),  # [x, y]
            "b": t_list(t_float()),
        },
    )


def t_traffic_polygon() -> TypeDescriptor:
    """A polygon in image (pixel) coordinates."""
    return t_record_kind(
        "traffic.polygon",
        fields={
            "_type": t_string(),
            "name": t_string(),
            "points": t_list(t_list(t_float())),  # list of [x, y]
        },
    )


def make_line(name: str, a: List[float], b: List[float]) -> Dict[str, Any]:
    return {
        "_type": "TrafficLine",
        "name": str(name),
        "a": [float(a[0]), float(a[1])],
        "b": [float(b[0]), float(b[1])],
    }


def make_polygon(name: str, points: List[List[float]]) -> Dict[str, Any]:
    return {
        "_type": "TrafficPolygon",
        "name": str(name),
        "points": [[float(p[0]), float(p[1])] for p in points],
    }


def is_line(value: Any) -> bool:
    return isinstance(value, dict) and value.get("_type") == "TrafficLine"


def is_polygon(value: Any) -> bool:
    return isinstance(value, dict) and value.get("_type") == "TrafficPolygon"


# ---------------------------------------------------------------------------
# traffic.event — discrete events emitted by detectors
# ---------------------------------------------------------------------------


EVENT_KINDS = (
    "stopped",
    "wrong_way",
    "near_miss",
    "hard_brake",
    "lane_change",
    "queue",
    "spillback",
    "ped_on_road",
    "ped_conflict",
    "bike_intrusion",
    "illegal_turn",
    "red_light_run",
    "speeding",
    "debris",
    "line_cross",
    "info",
)

SEVERITIES = ("info", "warning", "critical")


def t_traffic_event() -> TypeDescriptor:
    """A discrete observable traffic event.

    Wire form::

        {
            "_type": "TrafficEvent",
            "kind": str,           # one of EVENT_KINDS
            "severity": str,       # one of SEVERITIES
            "track_ids": list[int],
            "ts_start": float,
            "ts_end": float,
            "metric": float | None,
            "label": str,
            "details": dict,
        }
    """
    return t_record_kind(
        "traffic.event",
        fields={
            "_type": t_string(),
            "kind": t_string(),
            "severity": t_string(),
            "track_ids": t_list(t_int()),
            "ts_start": t_float(),
            "ts_end": t_float(),
            "metric": t_float().with_nullable(True),
            "label": t_string(),
            "details": t_map(t_string(), t_any()),
        },
    )


def make_event(
    *,
    kind: str,
    severity: str = "info",
    track_ids: Optional[List[int]] = None,
    ts_start: float = 0.0,
    ts_end: Optional[float] = None,
    metric: Optional[float] = None,
    label: str = "",
    details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if severity not in SEVERITIES:
        severity = "info"
    return {
        "_type": "TrafficEvent",
        "kind": str(kind),
        "severity": str(severity),
        "track_ids": [int(t) for t in (track_ids or [])],
        "ts_start": float(ts_start),
        "ts_end": float(ts_end if ts_end is not None else ts_start),
        "metric": (float(metric) if metric is not None else None),
        "label": str(label),
        "details": dict(details or {}),
    }


def is_event(value: Any) -> bool:
    return isinstance(value, dict) and value.get("_type") == "TrafficEvent"


# ---------------------------------------------------------------------------
# Trajectory state — per-track history kept on ExecutionContext
# ---------------------------------------------------------------------------


class TrackState:
    """Per-track running state used by speed / safety / event nodes."""

    __slots__ = ("track_id", "history", "class_name", "last_seen")

    def __init__(self, track_id: int) -> None:
        self.track_id = int(track_id)
        # Each entry: {ts, cx, cy, x_w, y_w, w, h, class_name, ...}
        self.history: List[Dict[str, Any]] = []
        self.class_name: Optional[str] = None
        self.last_seen: float = 0.0

    def push(self, sample: Dict[str, Any], max_len: int = 256) -> None:
        self.history.append(sample)
        if len(self.history) > max_len:
            del self.history[0 : len(self.history) - max_len]
        if "class_name" in sample and sample["class_name"]:
            self.class_name = str(sample["class_name"])
        self.last_seen = float(sample.get("ts", self.last_seen))


def get_track_store(ctx: Any, key: str) -> Dict[int, TrackState]:
    """Acquire / create a per-run dict[track_id -> TrackState] bucket.

    The bucket is keyed on (ctx, key) so multiple traffic nodes can
    share one history (e.g. line-counter + speed-estimator both want to
    see the same position stream). Use distinct ``key`` values when
    nodes legitimately need separate state.
    """
    return ctx.acquire_run_resource(
        f"stride_traffic:tracks:{key}", lambda: {}
    )


# ---------------------------------------------------------------------------
# Backwards-compat re-exports
# ---------------------------------------------------------------------------

__all__ = [
    "t_traffic_calibration",
    "make_calibration",
    "is_calibration",
    "t_traffic_line",
    "t_traffic_polygon",
    "make_line",
    "make_polygon",
    "is_line",
    "is_polygon",
    "t_traffic_event",
    "make_event",
    "is_event",
    "EVENT_KINDS",
    "SEVERITIES",
    "TrackState",
    "get_track_store",
]
