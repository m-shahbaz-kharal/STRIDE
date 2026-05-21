"""Unit tests for the live / bridge traffic nodes added in the
'composable pipelines' redesign:

* traffic.events.timestamps  - events -> list<float>
* traffic.events.filter      - events -> filtered events
* traffic.events.travel_time - detections + 2 lines -> travel events
* traffic.events.annotate    - image + events + ROI -> annotated image
* traffic.safety.headway_live  - events -> live headway stats
* traffic.safety.drac_pairwise - track-store -> DRAC events
* traffic.safety.pet_at_polygon - detections + polygon -> PET events
* traffic.flow.live_metrics  - count + elapsed -> AADT/hourly/per-min
* traffic.flow.live_phf      - events -> rolling 4x15-min PHF
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

import pytest

from stride_core import ExecutionContext, NODE_REGISTRY


def _node(node_type: str, ctx_id: str = "n1"):
    import stride_traffic  # noqa: F401
    entry = NODE_REGISTRY[node_type]
    return entry["class"]({"id": ctx_id, "type": node_type}, spec=entry["spec"])


def _det(track_id: int, x: float, y: float, *, w: float = 40.0,
         h: float = 80.0, cls: str = "car") -> Dict[str, Any]:
    return {
        "x1": x, "y1": y, "x2": x + w, "y2": y + h,
        "confidence": 0.9, "class_id": 1, "class_name": cls,
        "track_id": track_id,
    }


def _detections(boxes: List[Dict[str, Any]], width: int = 1280,
                height: int = 720) -> Dict[str, Any]:
    return {
        "_type": "Detections2D",
        "image_width": width, "image_height": height,
        "boxes": boxes, "image": None,
    }


def _make_event(kind="line_cross", severity="info", ts_start=0.0,
                ts_end=None, metric=None, track_ids=None):
    return {
        "_type": "TrafficEvent",
        "kind": kind, "severity": severity,
        "track_ids": list(track_ids or []),
        "ts_start": float(ts_start),
        "ts_end": float(ts_end if ts_end is not None else ts_start),
        "metric": float(metric) if metric is not None else None,
        "label": "", "details": {},
    }


# ---------------------------------------------------------------------------
# Events bridges
# ---------------------------------------------------------------------------


def test_events_timestamps_extracts_field() -> None:
    n = _node("traffic.events.timestamps")
    out = n.forward({
        "events": [
            _make_event(ts_start=10.0),
            _make_event(ts_start=11.5),
            _make_event(ts_start=13.0),
        ],
        "field": "ts_start",
    }, ExecutionContext())
    assert out["values"] == [10.0, 11.5, 13.0]
    assert out["count"] == 3


def test_events_timestamps_pulls_metric_field() -> None:
    n = _node("traffic.events.timestamps")
    out = n.forward({
        "events": [
            _make_event(metric=2.5),
            _make_event(metric=None),  # filtered
            _make_event(metric=1.1),
        ],
        "field": "metric",
    }, ExecutionContext())
    assert out["values"] == [2.5, 1.1]


def test_events_filter_by_kind_and_severity() -> None:
    n = _node("traffic.events.filter")
    evs = [
        _make_event(kind="line_cross", severity="info"),
        _make_event(kind="hard_brake", severity="warning"),
        _make_event(kind="hard_brake", severity="critical"),
    ]
    out = n.forward({"events": evs, "kind": "hard_brake", "severity": ""},
                    ExecutionContext())
    assert out["count"] == 2
    out = n.forward({"events": evs, "kind": "", "severity": "critical"},
                    ExecutionContext())
    assert out["count"] == 1


def test_events_travel_time_basic() -> None:
    """Track 1 crosses entry-line then exit-line -> emits a travel event."""
    line_node = _node("traffic.roi.line")
    entry = line_node.forward(
        {"name": "entry", "x1": 100, "y1": 0, "x2": 100, "y2": 480},
        ExecutionContext(),
    )["line"]
    exit_ = _node("traffic.roi.line").forward(
        {"name": "exit", "x1": 300, "y1": 0, "x2": 300, "y2": 480},
        ExecutionContext(),
    )["line"]
    n = _node("traffic.events.travel_time")
    ctx = ExecutionContext()
    # Frame 1: track at x=50 (left of entry)
    n.forward({
        "detections": _detections([_det(1, 50, 200)]),
        "entry_line": entry, "exit_line": exit_, "reference": "center",
    }, ctx)
    # Frame 2: track at x=200 (between lines) -> entry crossed, no exit yet
    out2 = n.forward({
        "detections": _detections([_det(1, 200, 200)]),
        "entry_line": entry, "exit_line": exit_, "reference": "center",
    }, ctx)
    assert out2["completed_total"] == 0
    assert out2["active_total"] == 1
    # Frame 3: track at x=400 (right of exit) -> emits travel event
    out3 = n.forward({
        "detections": _detections([_det(1, 400, 200)]),
        "entry_line": entry, "exit_line": exit_, "reference": "center",
    }, ctx)
    assert out3["completed_total"] == 1
    assert len(out3["events"]) == 1
    assert out3["events"][0]["details"]["entry"] == "entry"
    assert out3["events"][0]["details"]["exit"] == "exit"
    assert out3["events"][0]["metric"] >= 0


# ---------------------------------------------------------------------------
# Safety live nodes
# ---------------------------------------------------------------------------


def test_safety_headway_live_running_stats() -> None:
    n = _node("traffic.safety.headway_live")
    ctx = ExecutionContext()
    # First call: 3 events
    n.forward({"events": [
        _make_event(ts_start=10.0), _make_event(ts_start=12.0),
        _make_event(ts_start=13.5),
    ]}, ctx)
    # Second call: 2 more events
    out = n.forward({"events": [
        _make_event(ts_start=14.0), _make_event(ts_start=15.0),
    ]}, ctx)
    # Headways: 2.0, 1.5, 0.5, 1.0 — only 0.5 is < 1.0 strictly.
    assert out["n"] == 4
    assert out["min_s"] == pytest.approx(0.5)
    assert out["critical_count"] == 1
    assert sum(1 for g in out["headways_s"] if g < 1.0) == out["critical_count"]


def test_safety_drac_pairwise_basic() -> None:
    """Two tracks: faster follower closing on slower leader -> DRAC event."""
    from stride_traffic.types import TrackState

    n = _node("traffic.safety.drac_pairwise")
    ctx = ExecutionContext()
    # Build a fake track store for the 'speed' key.
    store = ctx.acquire_run_resource("stride_traffic:tracks:speed", lambda: {})
    now = time.time()

    # Leader at world (10, 0), moving +x at 5 m/s (slow)
    leader = TrackState(101)
    leader.history = [
        {"ts": now - 0.5, "px": 200, "py": 200, "x_w": 7.5, "y_w": 0.0},
        {"ts": now,        "px": 220, "py": 200, "x_w": 10.0, "y_w": 0.0},
    ]
    leader.last_seen = now
    store[101] = leader

    # Follower at world (5, 0), moving +x at 20 m/s (fast)
    follower = TrackState(102)
    follower.history = [
        {"ts": now - 0.5, "px": 100, "py": 200, "x_w": -5.0, "y_w": 0.0},
        {"ts": now,        "px": 130, "py": 200, "x_w": 5.0, "y_w": 0.0},
    ]
    follower.last_seen = now
    store[102] = follower

    out = n.forward({
        "store_key": "speed",
        "threshold_mps2": 3.4,
        "critical_mps2": 4.5,
        "max_lead_distance_m": 20.0,
        "min_speed_mps": 1.0,
    }, ctx)
    # Follower closing 15 m/s on leader 5 m apart -> DRAC = 15²/(2*5) = 22.5
    assert out["max_drac_mps2"] > 4.5
    assert out["critical_count"] >= 1
    assert any(e["kind"] == "hard_brake" for e in out["events"])


def test_safety_pet_at_polygon_consecutive_tracks() -> None:
    poly = _node("traffic.roi.polygon").forward({
        "name": "Z",
        "points": [[100, 100], [300, 100], [300, 300], [100, 300]],
    }, ExecutionContext())["polygon"]
    n = _node("traffic.safety.pet_at_polygon")
    ctx = ExecutionContext()
    # Track 1 inside the polygon
    n.forward({
        "detections": _detections([_det(1, 200, 200)]),
        "polygon": poly, "reference": "center", "threshold_s": 1.5,
    }, ctx)
    # Track 1 leaves
    n.forward({
        "detections": _detections([_det(1, 400, 200)]),
        "polygon": poly, "reference": "center", "threshold_s": 1.5,
    }, ctx)
    # Track 2 enters shortly after -> emit PET event
    out = n.forward({
        "detections": _detections([_det(2, 200, 200)]),
        "polygon": poly, "reference": "center", "threshold_s": 1.5,
    }, ctx)
    assert len(out["events"]) == 1
    assert out["events"][0]["details"]["pet_s"] >= 0
    assert out["events"][0]["kind"] == "near_miss"


# ---------------------------------------------------------------------------
# Flow live nodes
# ---------------------------------------------------------------------------


def test_flow_live_metrics_extrapolates() -> None:
    n = _node("traffic.flow.live_metrics")
    ctx = ExecutionContext()
    # First call seeds the start timestamp
    n.forward({"count": 5}, ctx)
    time.sleep(0.05)
    out = n.forward({"count": 50}, ctx)
    assert out["elapsed_s"] > 0
    assert out["hourly_rate"] > 0
    # AADT = hourly * 24 * 1.0 * 1.0 * 1.0
    assert out["aadt"] == pytest.approx(out["hourly_rate"] * 24.0)


def test_flow_live_metrics_zero_until_first_count() -> None:
    n = _node("traffic.flow.live_metrics")
    ctx = ExecutionContext()
    out = n.forward({"count": 0}, ctx)
    assert out["aadt"] == 0.0
    assert out["elapsed_s"] == 0.0


def test_flow_live_phf_4_bins() -> None:
    n = _node("traffic.flow.live_phf")
    ctx = ExecutionContext()
    # 4 bins of 900 s. Use timestamps chosen to land squarely inside the
    # intended bin (offsets well inside 900-s slots, never on the boundary).
    # bin 3 (newest, offsets 0..899): 4 events
    # bin 2 (offsets 900..1799):     12 events
    # bin 1 (offsets 1800..2699):     8 events
    # bin 0 (oldest, offsets 2700..3599): 5 events
    latest = 100000.0
    events = []
    for i in range(4):
        events.append(_make_event(ts_start=latest - (100 + i * 50)))    # bin 3
    for i in range(12):
        events.append(_make_event(ts_start=latest - (1000 + i * 50)))   # bin 2
    for i in range(8):
        events.append(_make_event(ts_start=latest - (1900 + i * 50)))   # bin 1
    for i in range(5):
        events.append(_make_event(ts_start=latest - (2800 + i * 50)))   # bin 0
    out = n.forward({"events": events, "bin_seconds": 900}, ctx)
    assert out["bins"] == [5, 8, 12, 4]
    assert out["peak_15"] == 12
    assert out["hourly_volume"] == 29
    assert out["phf"] == pytest.approx(29.0 / 48.0, rel=0.01)


# ---------------------------------------------------------------------------
# Annotation
# ---------------------------------------------------------------------------


def test_events_annotate_overlays_lines_and_events() -> None:
    pytest.importorskip("cv2")
    pytest.importorskip("numpy")
    import numpy as np
    import cv2

    # Build a 320x240 black image as a canonical Image record.
    img = np.zeros((240, 320, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    import base64
    data_url = "data:image/jpeg;base64," + base64.b64encode(buf).decode("ascii")
    image_rec = {
        "_type": "Image", "width": 320, "height": 240,
        "format": "jpeg", "data_b64": data_url,
    }
    line_rec = _node("traffic.roi.line").forward({
        "name": "L", "x1": 50, "y1": 100, "x2": 250, "y2": 100,
    }, ExecutionContext())["line"]
    poly_rec = _node("traffic.roi.polygon").forward({
        "name": "Z",
        "points": [[60, 50], [200, 50], [200, 180], [60, 180]],
    }, ExecutionContext())["polygon"]
    out = _node("traffic.events.annotate").forward({
        "image": image_rec,
        "events": [_make_event(kind="hard_brake", severity="critical")],
        "lines": [line_rec],
        "polygons": [poly_rec],
        "thickness": 2,
    }, ExecutionContext())
    assert out["event_count"] == 1
    # Output is a data-URL string (matching core.image.load convention) so
    # downstream YOLO / display widgets can consume it directly.
    assert isinstance(out["image"], str)
    assert out["image"].startswith("data:image/jpeg;base64,")

    # Also exercise string-input form (the duck-typed convention).
    out_str = _node("traffic.events.annotate").forward({
        "image": data_url,
        "events": [],
        "lines": [line_rec],
        "polygons": [],
        "thickness": 1,
    }, ExecutionContext())
    assert out_str["image"].startswith("data:image/jpeg;base64,")
