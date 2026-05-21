"""Smoke + numerical tests for the stride-traffic package.

These tests instantiate each node class directly and call forward()
with synthetic inputs. We deliberately avoid GraphExecutor here so the
suite stays fast and deterministic.
"""

from __future__ import annotations

from typing import Any, Dict, List

import math
import time

import pytest

from stride_core import ExecutionContext, NODE_REGISTRY


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


def _node(node_type: str, ctx_id: str = "n1"):
    """Instantiate a registered node by id."""
    entry = NODE_REGISTRY.get(node_type)
    assert entry is not None, f"missing node {node_type!r}"
    cls = entry["class"]
    spec = entry["spec"]
    return cls({"id": ctx_id, "type": node_type}, spec=spec)


# ---------------------------------------------------------------------------
# Package import
# ---------------------------------------------------------------------------


def test_package_imports() -> None:
    import stride_traffic  # noqa: F401
    stride_traffic.register()
    # 50+ nodes registered
    traffic_ids = [k for k in NODE_REGISTRY if k.startswith("traffic.")]
    assert len(traffic_ids) >= 50, traffic_ids


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


def test_calibration_identity() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.calibration.identity")
    out = n.forward({
        "image_width": 1280,
        "image_height": 720,
        "scale_m_per_px": 0.1,
        "frame": "world",
    }, ExecutionContext())
    cal = out["calibration"]
    assert cal["_type"] == "TrafficCalibration"
    assert cal["scale_m_per_px"] == pytest.approx(0.1)
    assert cal["homography"][0][0] == pytest.approx(0.1)


def test_calibration_known_width() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.calibration.from_known_width")
    # Two points 100 px apart, claimed to be 5 m -> 0.05 m/px
    out = n.forward({
        "image_width": 1280, "image_height": 720,
        "point_a": [100.0, 360.0], "point_b": [200.0, 360.0],
        "real_distance_m": 5.0,
    }, ExecutionContext())
    assert out["scale_m_per_px"] == pytest.approx(0.05, rel=1e-6)


def test_calibration_homography_basic() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.calibration.from_homography")
    # Trivial identity-like correspondences (a square -> a 10x scaled square)
    img = [[0, 0], [100, 0], [100, 100], [0, 100], [50, 50]]
    world = [[0, 0], [1, 0], [1, 1], [0, 1], [0.5, 0.5]]
    out = n.forward({
        "image_width": 1280, "image_height": 720,
        "image_points": img, "world_points": world,
    }, ExecutionContext())
    assert out["reprojection_error_px"] < 1e-6
    h = out["calibration"]["homography"]
    # H * (50, 50, 1) should land at (0.5, 0.5)
    px = [50.0, 50.0, 1.0]
    proj = [
        sum(h[i][j] * px[j] for j in range(3))
        for i in range(3)
    ]
    assert proj[0] / proj[2] == pytest.approx(0.5, abs=1e-6)
    assert proj[1] / proj[2] == pytest.approx(0.5, abs=1e-6)


# ---------------------------------------------------------------------------
# ROI
# ---------------------------------------------------------------------------


def test_roi_line() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.roi.line")
    out = n.forward({"name": "L", "x1": 0, "y1": 0, "x2": 100, "y2": 0},
                    ExecutionContext())
    assert out["line"]["_type"] == "TrafficLine"


def test_roi_polygon_rejects_short() -> None:
    import stride_traffic  # noqa: F401
    from stride_core.errors import NodeInputError
    n = _node("traffic.roi.polygon")
    with pytest.raises(NodeInputError):
        n.forward({"name": "p", "points": [[0, 0], [1, 1]]}, ExecutionContext())


def test_roi_lane_polygon_shape() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.roi.lane_polygon")
    out = n.forward({
        "name": "lane1",
        "near_x": 640, "near_y": 720, "far_x": 640, "far_y": 200,
        "near_width": 400, "far_width": 80,
    }, ExecutionContext())
    poly = out["polygon"]
    assert len(poly["points"]) == 4
    # near-left at (640 - 200, 720)
    assert poly["points"][0] == [440.0, 720.0]
    assert poly["points"][2] == [680.0, 200.0]


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def test_count_line_directional() -> None:
    import stride_traffic  # noqa: F401
    line_node = _node("traffic.roi.line")
    line = line_node.forward(
        {"name": "L", "x1": 100, "y1": 0, "x2": 100, "y2": 480},
        ExecutionContext(),
    )["line"]
    n = _node("traffic.count.line")
    ctx = ExecutionContext()
    # Track 1 starts at x=50, then moves to x=150 -> forward crossing
    n.forward({
        "detections": _detections([_det(1, 50, 200)]),
        "line": line, "reference": "center", "hysteresis_px": 0.0,
    }, ctx)
    out = n.forward({
        "detections": _detections([_det(1, 150, 200)]),
        "line": line, "reference": "center", "hysteresis_px": 0.0,
    }, ctx)
    assert out["forward"] == 1
    assert out["backward"] == 0


def test_count_polygon_enter_exit() -> None:
    import stride_traffic  # noqa: F401
    poly_node = _node("traffic.roi.polygon")
    poly = poly_node.forward({
        "name": "Z",
        "points": [[100, 100], [300, 100], [300, 300], [100, 300]],
    }, ExecutionContext())["polygon"]
    n = _node("traffic.count.polygon")
    ctx = ExecutionContext()
    # Track 1 outside -> inside -> outside
    n.forward({
        "detections": _detections([_det(1, 50, 50)]),
        "polygon": poly, "reference": "center",
    }, ctx)
    out = n.forward({
        "detections": _detections([_det(1, 200, 200)]),
        "polygon": poly, "reference": "center",
    }, ctx)
    assert out["entered"] == 1
    out2 = n.forward({
        "detections": _detections([_det(1, 400, 400)]),
        "polygon": poly, "reference": "center",
    }, ctx)
    assert out2["exited"] == 1


def test_count_classify_unique_ids() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.count.classify")
    ctx = ExecutionContext()
    n.forward({
        "detections": _detections([
            _det(1, 0, 0, cls="car"), _det(2, 100, 0, cls="bus"),
        ]),
    }, ctx)
    # Same IDs again -> no double-count
    out = n.forward({
        "detections": _detections([
            _det(1, 10, 0, cls="car"), _det(2, 110, 0, cls="bus"),
        ]),
    }, ctx)
    assert out["counts"]["car"] == 1
    assert out["counts"]["bus"] == 1
    assert out["total"] == 2


# ---------------------------------------------------------------------------
# Flow
# ---------------------------------------------------------------------------


def test_flow_aadt() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.flow.aadt_estimate")
    out = n.forward({"count": 600, "duration_hours": 1.0}, ExecutionContext())
    assert out["hourly_rate"] == pytest.approx(600)
    assert out["aadt"] == pytest.approx(14400)


def test_flow_phf() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.flow.peak_hour_factor")
    out = n.forward({"counts_15min": [200, 250, 300, 250]}, ExecutionContext())
    assert out["hourly_volume"] == 1000
    assert out["peak_15"] == 300
    assert out["phf"] == pytest.approx(1000 / (4 * 300))


def test_flow_density() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.flow.density")
    out = n.forward(
        {"flow_vph": 1800, "space_mean_speed_kph": 60.0},
        ExecutionContext(),
    )
    assert out["density_vpkm"] == pytest.approx(30)


def test_flow_vc() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.flow.capacity_vc")
    out = n.forward({"volume_vph": 1800, "capacity_vph": 2200}, ExecutionContext())
    assert out["vc"] == pytest.approx(1800 / 2200)


def test_flow_time_vs_space_mean() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.flow.time_vs_space_mean")
    out = n.forward(
        {"speeds_kph": [60.0, 30.0]}, ExecutionContext()
    )
    assert out["time_mean_kph"] == pytest.approx(45.0)
    # Harmonic mean of (60, 30) = 2 / (1/60 + 1/30) = 40
    assert out["space_mean_kph"] == pytest.approx(40.0)
    # Time-mean is always >= space-mean
    assert out["time_mean_kph"] >= out["space_mean_kph"]


# ---------------------------------------------------------------------------
# Speed
# ---------------------------------------------------------------------------


def _ident_cal() -> Dict[str, Any]:
    """Identity-scaled calibration: 1 px = 0.05 m."""
    import stride_traffic  # noqa: F401
    return _node("traffic.calibration.identity").forward({
        "image_width": 1280, "image_height": 720, "scale_m_per_px": 0.05,
    }, ExecutionContext())["calibration"]


def test_speed_estimate_two_frames() -> None:
    import stride_traffic  # noqa: F401
    cal = _ident_cal()
    n = _node("traffic.speed.estimate")
    ctx = ExecutionContext()
    t0 = time.time()
    # Frame 1
    n.forward({
        "detections": _detections([dict(_det(1, 100, 200), timestamp=t0)]),
        "calibration": cal, "reference": "center", "ema_alpha": 1.0,
        "window_s": 1.0,
    }, ctx)
    # Frame 2: dx = 20 px = 1 m at 0.05 m/px, dt = 0.5 s -> 2 m/s
    out = n.forward({
        "detections": _detections([dict(_det(1, 120, 200), timestamp=t0 + 0.5)]),
        "calibration": cal, "reference": "center", "ema_alpha": 1.0,
        "window_s": 1.0,
    }, ctx)
    speeds = out["speeds_kph"]
    assert len(speeds) == 1
    # 2 m/s = 7.2 km/h
    assert speeds[0] == pytest.approx(7.2, rel=0.05)


def test_speed_summary_percentiles() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.speed.summary")
    ctx = ExecutionContext()
    n.forward({"speeds_kph": list(range(1, 101))}, ctx)
    out = n.forward({"speeds_kph": []}, ctx)  # query
    assert out["n"] == 100
    assert out["p50_kph"] == pytest.approx(50.0, abs=1.0)
    assert out["p85_kph"] == pytest.approx(85.0, abs=1.0)
    assert out["p95_kph"] == pytest.approx(95.0, abs=1.0)


def test_speed_percentile_stateless() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.speed.percentile")
    out = n.forward({
        "speeds_kph": list(range(1, 101)),
        "percentile": 85.0,
    }, ExecutionContext())
    assert out["value_kph"] == pytest.approx(85.0, abs=0.5)


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


def test_safety_drac_zero_when_leader_faster() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.safety.drac")
    out = n.forward(
        {"follower_mps": 10, "leader_mps": 15, "gap_m": 20},
        ExecutionContext(),
    )
    assert out["drac_mps2"] == 0.0


def test_safety_drac_basic() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.safety.drac")
    out = n.forward(
        {"follower_mps": 20, "leader_mps": 10, "gap_m": 25},
        ExecutionContext(),
    )
    # (20 - 10)² / (2 * 25) = 100 / 50 = 2.0
    assert out["drac_mps2"] == pytest.approx(2.0)


def test_safety_pet_negative_is_info() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.safety.pet")
    out = n.forward(
        {"ts_first_left_s": 10.0, "ts_second_arrived_s": 9.0},
        ExecutionContext(),
    )
    assert out["pet_s"] == pytest.approx(-1.0)
    assert out["severity"] == "info"


def test_safety_pet_critical() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.safety.pet")
    out = n.forward(
        {"ts_first_left_s": 10.0, "ts_second_arrived_s": 10.3},
        ExecutionContext(),
    )
    assert out["severity"] == "critical"


def test_safety_headway() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.safety.headway")
    out = n.forward(
        {"crossing_times_s": [0.0, 2.0, 4.5, 5.0]},  # gaps: 2, 2.5, 0.5
        ExecutionContext(),
    )
    assert out["headways_s"] == [2.0, 2.5, 0.5]
    assert out["min_s"] == 0.5
    assert out["critical_count"] == 1


# ---------------------------------------------------------------------------
# Intersection
# ---------------------------------------------------------------------------


def test_intersection_los_from_delay() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.intersection.los_from_delay")
    assert n.forward({"delay_s": 5.0}, ExecutionContext())["los"] == "A"
    assert n.forward({"delay_s": 25.0}, ExecutionContext())["los"] == "C"
    assert n.forward({"delay_s": 90.0}, ExecutionContext())["los"] == "F"


def test_intersection_control_delay() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.intersection.control_delay")
    out = n.forward(
        {"cycle_s": 90.0, "green_s": 30.0, "vc": 0.5},
        ExecutionContext(),
    )
    assert out["d1_s"] > 0
    assert out["los"] in ("A", "B", "C", "D", "E", "F")


def test_intersection_icu() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.intersection.icu")
    out = n.forward(
        {"critical_vc": [0.4, 0.3], "cycle_s": 120, "lost_time_s": 12},
        ExecutionContext(),
    )
    assert out["icu"] > 0
    assert out["los"] in "ABCDEFG"


# ---------------------------------------------------------------------------
# Crash / HSM
# ---------------------------------------------------------------------------


def test_crash_spf_rural_two_lane() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.crash.spf_rural_two_lane")
    out = n.forward(
        {"aadt": 5000, "length_mi": 1.0, "intercept": -0.312},
        ExecutionContext(),
    )
    expected = 5000 * 1.0 * 365 * 1e-6 * math.exp(-0.312)
    assert out["n_spf_per_year"] == pytest.approx(expected, rel=1e-9)


def test_crash_apply_cmfs() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.crash.apply_cmfs")
    out = n.forward(
        {"n_spf_per_year": 2.0, "cmfs": [0.9, 1.1], "calibration_factor": 1.2},
        ExecutionContext(),
    )
    assert out["cmf_product"] == pytest.approx(0.99)
    assert out["n_predicted"] == pytest.approx(2.0 * 0.99 * 1.2)


def test_crash_eb() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.crash.empirical_bayes")
    out = n.forward(
        {"n_predicted_total": 3.0, "n_observed_total": 9.0, "overdispersion_k": 0.236},
        ExecutionContext(),
    )
    # Weight w = 1 / (1 + 0.236 * 3) ≈ 0.586
    assert out["weight"] == pytest.approx(1.0 / (1.0 + 0.236 * 3.0))
    # N_expected = w * 3 + (1 - w) * 9
    assert out["n_expected"] == pytest.approx(
        out["weight"] * 3.0 + (1.0 - out["weight"]) * 9.0
    )


def test_crash_rate_mvm_vs_mev() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.crash.crash_rate")
    out_mvm = n.forward(
        {"n_crashes": 2, "aadt": 10000, "length_mi": 0.5, "years": 1},
        ExecutionContext(),
    )
    assert out_mvm["basis"] == "MVM"
    out_mev = n.forward(
        {"n_crashes": 2, "aadt": 10000, "length_mi": 0.0, "years": 1},
        ExecutionContext(),
    )
    assert out_mev["basis"] == "MEV"


def test_crash_epdo_default_weights() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.crash.epdo")
    out = n.forward(
        {"k": 1, "a": 0, "b": 0, "c": 0, "o": 10},
        ExecutionContext(),
    )
    # 1 * 11295 + 10 * 10 = 11395
    assert out["epdo"] == pytest.approx(11395.0)
    assert out["total_crashes"] == 11


def test_crash_psi() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.crash.psi")
    out = n.forward(
        {"n_expected": 5.0, "n_predicted": 2.0}, ExecutionContext()
    )
    assert out["psi"] == 3.0
    out2 = n.forward(
        {"n_expected": 1.0, "n_predicted": 5.0}, ExecutionContext()
    )
    assert out2["psi"] == 0.0


# ---------------------------------------------------------------------------
# Report / aggregation
# ---------------------------------------------------------------------------


def test_report_time_bin() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.report.time_bin")
    out = n.forward(
        {"timestamps": [0, 100, 200, 1000, 1100, 2000], "bin_width_s": 1000},
        ExecutionContext(),
    )
    assert out["total"] == 6
    assert sum(out["bins"]) == 6
    assert out["bins"][0] == 3


def test_report_percentile_bundle() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.report.percentile_bundle")
    out = n.forward(
        {"values": list(range(1, 101))}, ExecutionContext()
    )
    assert out["n"] == 100
    assert out["p50"] == pytest.approx(50.5, abs=1.0)


def test_report_travel_time_indices() -> None:
    import stride_traffic  # noqa: F401
    n = _node("traffic.report.travel_time_indices")
    out = n.forward(
        {"travel_times_s": [60, 70, 80, 90, 100], "free_flow_s": 60},
        ExecutionContext(),
    )
    assert out["mean_s"] == pytest.approx(80)
    assert out["travel_time_index"] == pytest.approx(80 / 60)


def test_report_event_summary_and_csv() -> None:
    import stride_traffic  # noqa: F401
    from stride_traffic.types import make_event
    events = [
        make_event(kind="line_cross", severity="info"),
        make_event(kind="line_cross", severity="info"),
        make_event(kind="hard_brake", severity="warning"),
    ]
    out = _node("traffic.report.event_summary").forward(
        {"events": events}, ExecutionContext()
    )
    assert out["total"] == 3
    assert out["by_kind"]["line_cross"] == 2
    assert out["by_severity"]["warning"] == 1
    csv_out = _node("traffic.report.csv_emit").forward(
        {"records": events}, ExecutionContext(),
    )
    assert csv_out["rows"] == 3
    assert "kind" in csv_out["csv"].splitlines()[0]
