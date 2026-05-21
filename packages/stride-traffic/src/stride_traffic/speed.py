"""Per-track speed estimation nodes.

Speed comes from differentiating tracked positions over time, projected
into world coordinates via a TrafficCalibration. The pipeline shape is::

    detector -> tracker -> traffic.speed.estimate -> traffic.speed.summary

The estimator stamps the input detection records in-place with
``speed_mps``, ``speed_kph``, ``speed_mph`` so downstream display nodes
can read them directly.
"""

from __future__ import annotations

import math
import statistics
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
    t_map,
    t_string,
)

from .calibration import project_pixel_to_world
from .roi import detection_bottom_center, detection_center
from .types import TrackState, get_track_store, is_calibration, t_traffic_calibration


def _require_numpy() -> None:
    if not HAS_NUMPY:
        raise NodeMissingDependencyError("numpy is required for speed nodes")


# ---------------------------------------------------------------------------
# traffic.speed.estimate — per-track instantaneous speed
# ---------------------------------------------------------------------------


ESTIMATE_SPEC = NodeSpec(
    type="traffic.speed.estimate",
    version="1.0.0",
    display_name="Speed · Estimate (per track)",
    category="Traffic Speed",
    summary="Stamp each tracked detection with instantaneous speed.",
    description=(
        "Maintains per-track position history, computes the ground-plane "
        "displacement using the calibration's homography, divides by the "
        "elapsed time, and stamps speed_mps / speed_kph / speed_mph onto "
        "each output detection. Smoothing is exponential (configurable)."
    ),
    icon="zap",
    tags=["traffic", "speed"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d(), required=True),
        PortSpec(name="calibration", type=t_traffic_calibration(), required=True),
        PortSpec(name="reference", type=t_string(), required=False, default="bottom",
                 constraints={"enum": ["center", "bottom"]}),
        PortSpec(name="ema_alpha", type=t_float(), required=False, default=0.3,
                 description="Exponential smoothing factor in (0, 1]",
                 constraints={"min": 1e-6, "max": 1.0}),
        PortSpec(name="window_s", type=t_float(), required=False, default=0.5,
                 description="Time window over which to compute displacement",
                 constraints={"min": 1e-3}),
        PortSpec(name="store_key", type=t_string(), required=False, default="speed",
                 description="Run-resource key for the shared track-store"),
        PortSpec(name="reset", type=t_boolean(), required=False, default=False),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d(),
                 description="Same detections with speed fields stamped"),
        PortSpec(name="mean_speed_kph", type=t_float()),
        PortSpec(name="speeds_kph", type=t_list(t_float()),
                 description="Per-detection speeds emitted this frame (km/h)"),
    ],
    cache_policy="disabled",
)


def _now_seconds(det: Dict[str, Any]) -> float:
    """Get a timestamp for the detection; default to wall clock."""
    ts = det.get("timestamp")
    if ts is not None:
        try:
            return float(ts)
        except (TypeError, ValueError):
            pass
    return time.time()


@register_node(ESTIMATE_SPEC)
class SpeedEstimateNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        cal = inputs.get("calibration")
        if not is_calibration(cal):
            raise NodeInputError(
                "calibration must be a TrafficCalibration",
                port="calibration",
            )
        boxes_in = inputs.get("detections")
        if isinstance(boxes_in, dict):
            boxes = list(boxes_in.get("boxes") or [])
        elif isinstance(boxes_in, list):
            boxes = list(boxes_in)
        else:
            boxes = []

        anchor = (
            detection_bottom_center
            if str(inputs.get("reference") or "bottom") == "bottom"
            else detection_center
        )
        alpha = float(inputs.get("ema_alpha") or 0.3)
        window_s = float(inputs.get("window_s") or 0.5)
        reset = bool(inputs.get("reset") or False)
        store_key = str(inputs.get("store_key") or "speed")
        store = get_track_store(ctx, store_key)
        if reset:
            store.clear()

        out_boxes: List[Dict[str, Any]] = []
        speeds: List[float] = []
        for det in boxes:
            tid = det.get("track_id") if det.get("track_id") is not None else det.get("id")
            if tid is None:
                # No track id — emit unchanged
                out_boxes.append(dict(det))
                continue
            tid = int(tid)
            pt = anchor(det)
            if pt is None:
                out_boxes.append(dict(det))
                continue
            world = project_pixel_to_world(cal, pt[0], pt[1])
            if world is None:
                out_boxes.append(dict(det))
                continue
            ts = _now_seconds(det)
            track = store.get(tid)
            if track is None:
                track = TrackState(tid)
                store[tid] = track
            track.push({
                "ts": ts,
                "px": pt[0], "py": pt[1],
                "x_w": world[0], "y_w": world[1],
                "class_name": det.get("class_name"),
            })
            # Find the oldest sample within window_s
            speed_mps = None
            if len(track.history) >= 2:
                cutoff = ts - window_s
                # Walk backward to find first sample <= cutoff
                anchor_idx = 0
                for i in range(len(track.history) - 2, -1, -1):
                    if track.history[i]["ts"] <= cutoff:
                        anchor_idx = i
                        break
                a = track.history[anchor_idx]
                b = track.history[-1]
                dt = max(1e-6, float(b["ts"] - a["ts"]))
                dx = float(b["x_w"] - a["x_w"])
                dy = float(b["y_w"] - a["y_w"])
                speed_mps = math.sqrt(dx * dx + dy * dy) / dt
                # Exponential smoothing using prior smoothed value
                prior = track.history[-2].get("speed_mps")
                if prior is not None:
                    speed_mps = alpha * speed_mps + (1.0 - alpha) * float(prior)
                track.history[-1]["speed_mps"] = speed_mps

            new_det = dict(det)
            if speed_mps is not None:
                new_det["speed_mps"] = float(speed_mps)
                new_det["speed_kph"] = float(speed_mps) * 3.6
                new_det["speed_mph"] = float(speed_mps) * 2.236936
                speeds.append(new_det["speed_kph"])
            out_boxes.append(new_det)

        # Build the output: preserve original detections-record shape if given
        if isinstance(boxes_in, dict):
            out = dict(boxes_in)
            out["boxes"] = out_boxes
        else:
            # Need to fabricate a minimal detections2d record so downstream
            # nodes that expect that kind keep working.
            iw = int(cal.get("image_width") or 1280)
            ih = int(cal.get("image_height") or 720)
            out = {
                "_type": "Detections2D",
                "image_width": iw,
                "image_height": ih,
                "boxes": out_boxes,
                "image": None,
            }
        mean_kph = float(sum(speeds) / len(speeds)) if speeds else 0.0
        return {
            "control_out": None,
            "detections": out,
            "mean_speed_kph": mean_kph,
            "speeds_kph": speeds,
        }


# ---------------------------------------------------------------------------
# traffic.speed.summary — running statistics (mean, stdev, percentiles)
# ---------------------------------------------------------------------------


SUMMARY_SPEC = NodeSpec(
    type="traffic.speed.summary",
    version="1.0.0",
    display_name="Speed · Running Summary",
    category="Traffic Speed",
    summary="Mean / stdev / 50th / 85th / 95th percentile of incoming speeds.",
    description=(
        "Append-only buffer that summarises every speed it has seen. "
        "Useful for live dashboards that show the cumulative percentile "
        "speed, the 85th percentile (the speed limit benchmark), etc."
    ),
    icon="bar-chart-2",
    tags=["traffic", "speed", "stats"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="speeds_kph", type=t_list(t_float()), required=True,
                 description="Speeds emitted this frame"),
        PortSpec(name="max_samples", type=t_int(), required=False, default=10000,
                 constraints={"min": 100}),
        PortSpec(name="reset", type=t_boolean(), required=False, default=False),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="mean_kph", type=t_float()),
        PortSpec(name="stdev_kph", type=t_float()),
        PortSpec(name="p50_kph", type=t_float()),
        PortSpec(name="p85_kph", type=t_float()),
        PortSpec(name="p95_kph", type=t_float()),
        PortSpec(name="n", type=t_int()),
    ],
    cache_policy="disabled",
)


_SUMMARY_KEY = "speed_summary.buf"


@register_node(SUMMARY_SPEC)
class SpeedSummaryNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        raw = inputs.get("speeds_kph") or []
        max_samples = int(inputs.get("max_samples") or 10000)
        reset = bool(inputs.get("reset") or False)
        bucket = ctx.node_resources.setdefault(self.id, {})
        if reset or _SUMMARY_KEY not in bucket:
            bucket[_SUMMARY_KEY] = []
        buf: List[float] = bucket[_SUMMARY_KEY]
        for v in raw:
            if v is None:
                continue
            try:
                buf.append(float(v))
            except (TypeError, ValueError):
                continue
        if len(buf) > max_samples:
            del buf[0 : len(buf) - max_samples]

        n = len(buf)
        if n == 0:
            return {
                "control_out": None, "mean_kph": 0.0, "stdev_kph": 0.0,
                "p50_kph": 0.0, "p85_kph": 0.0, "p95_kph": 0.0, "n": 0,
            }
        mean = statistics.fmean(buf)
        sd = statistics.pstdev(buf) if n > 1 else 0.0
        sorted_buf = sorted(buf)

        def pct(p: float) -> float:
            if not sorted_buf:
                return 0.0
            idx = int(round((len(sorted_buf) - 1) * p))
            return float(sorted_buf[max(0, min(len(sorted_buf) - 1, idx))])

        return {
            "control_out": None,
            "mean_kph": float(mean),
            "stdev_kph": float(sd),
            "p50_kph": pct(0.50),
            "p85_kph": pct(0.85),
            "p95_kph": pct(0.95),
            "n": n,
        }


# ---------------------------------------------------------------------------
# traffic.speed.percentile — single percentile over a list
# ---------------------------------------------------------------------------


PERCENTILE_SPEC = NodeSpec(
    type="traffic.speed.percentile",
    version="1.0.0",
    display_name="Speed · Percentile",
    category="Traffic Speed",
    summary="Compute an arbitrary percentile (default 85th).",
    description="Stateless. Sort + linear-interpolation percentile.",
    icon="bar-chart",
    tags=["traffic", "speed"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="speeds_kph", type=t_list(t_float()), required=True),
        PortSpec(name="percentile", type=t_float(), required=False, default=85.0,
                 constraints={"min": 0.0, "max": 100.0}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value_kph", type=t_float()),
    ],
    cache_policy="auto",
)


@register_node(PERCENTILE_SPEC)
class SpeedPercentileNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        raw = inputs.get("speeds_kph") or []
        speeds = sorted(float(v) for v in raw if v is not None)
        if not speeds:
            return {"control_out": None, "value_kph": 0.0}
        p = float(inputs.get("percentile") or 85.0) / 100.0
        idx_f = (len(speeds) - 1) * p
        lo = int(math.floor(idx_f))
        hi = int(math.ceil(idx_f))
        if lo == hi:
            return {"control_out": None, "value_kph": float(speeds[lo])}
        frac = idx_f - lo
        v = speeds[lo] * (1 - frac) + speeds[hi] * frac
        return {"control_out": None, "value_kph": float(v)}
