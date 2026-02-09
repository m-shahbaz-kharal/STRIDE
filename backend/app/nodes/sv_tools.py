"""Supervision tools: object tracking and zone counting."""
from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

from . import register_node
from .base import ExecutionContext, NodeBase
from ..node_spec import NodeSpec, PortSpec
from ..typesystem import t_any, t_control, t_float, t_int, t_list, t_string

try:
    import supervision as sv
except ImportError:
    sv = None  # type: ignore[assignment]


def _require_sv():
    if sv is None:
        raise ImportError(
            "The 'supervision' package is required for this node. "
            "Install it with: pip install supervision"
        )


# ============================================================================
# BYTETRACK TRACKER
# ============================================================================

SV_BYTETRACK_SPEC = NodeSpec(
    type="sv.track.bytetrack",
    version="1.0.0",
    display_name="SV - ByteTrack",
    category="Supervision",
    summary="Track objects across frames.",
    description="Applies ByteTrack object tracking to detections, assigning persistent tracker IDs across frames. State is maintained across executions within the same graph run.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_any(), required=True),
        PortSpec(name="track_activation_threshold", type=t_float(), required=False, default=0.25),
        PortSpec(name="lost_track_buffer", type=t_int(), required=False, default=30),
        PortSpec(name="minimum_matching_threshold", type=t_float(), required=False, default=0.8),
        PortSpec(name="frame_rate", type=t_int(), required=False, default=30),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_any()),
    ],
    cache_policy="disabled",
)


@register_node(SV_BYTETRACK_SPEC)
class SvByteTrackNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_sv()
        dets = inputs.get("detections")
        if dets is None:
            raise ValueError("No detections provided")

        tracker_key = f"_sv_bytetrack_{self.id}"
        tracker = ctx.get_var(tracker_key)
        if tracker is None:
            tracker = sv.ByteTrack(
                track_activation_threshold=float(inputs.get("track_activation_threshold") or 0.25),
                lost_track_buffer=int(inputs.get("lost_track_buffer") or 30),
                minimum_matching_threshold=float(inputs.get("minimum_matching_threshold") or 0.8),
                frame_rate=int(inputs.get("frame_rate") or 30),
            )
            ctx.set_var(tracker_key, tracker)

        tracked = tracker.update_with_detections(dets)
        ctx.log(f"ByteTrack: {len(dets)} in -> {len(tracked)} tracked")
        return {"control_out": None, "detections": tracked}


# ============================================================================
# POLYGON ZONE
# ============================================================================

SV_POLYGON_ZONE_SPEC = NodeSpec(
    type="sv.zone.polygon",
    version="1.0.0",
    display_name="SV - Polygon Zone",
    category="Supervision",
    summary="Check detections inside a polygon region.",
    description="Defines a polygon zone and filters detections to those whose anchors fall inside it. Polygon is specified as comma-separated x,y pairs (e.g. '100,100,200,100,200,200,100,200').",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_any(), required=True),
        PortSpec(name="polygon", type=t_string(), required=True, default=""),
        PortSpec(name="frame_width", type=t_int(), required=False, default=640),
        PortSpec(name="frame_height", type=t_int(), required=False, default=480),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="detections_in_zone", type=t_any()),
        PortSpec(name="count", type=t_int()),
    ],
)


@register_node(SV_POLYGON_ZONE_SPEC)
class SvPolygonZoneNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_sv()
        dets = inputs.get("detections")
        if dets is None:
            raise ValueError("No detections provided")

        polygon_str = str(inputs.get("polygon") or "")
        if not polygon_str.strip():
            raise ValueError("Polygon coordinates are required")

        coords = [float(c.strip()) for c in polygon_str.split(",") if c.strip()]
        if len(coords) % 2 != 0 or len(coords) < 6:
            raise ValueError("Polygon must have at least 3 points (6 coordinates)")
        polygon = np.array(coords, dtype=np.float32).reshape(-1, 2)

        zone_key = f"_sv_polygon_zone_{self.id}_{polygon_str}"
        zone = ctx.get_var(zone_key)
        if zone is None:
            frame_resolution = (
                int(inputs.get("frame_width") or 640),
                int(inputs.get("frame_height") or 480),
            )
            zone = sv.PolygonZone(
                polygon=polygon,
                frame_resolution_wh=frame_resolution,
            )
            ctx.set_var(zone_key, zone)

        mask = zone.trigger(detections=dets)
        filtered = dets[mask]
        count = int(np.sum(mask))

        ctx.log(f"Polygon zone: {count}/{len(dets)} detections inside")
        return {"control_out": None, "detections_in_zone": filtered, "count": count}


# ============================================================================
# LINE ZONE
# ============================================================================

SV_LINE_ZONE_SPEC = NodeSpec(
    type="sv.zone.line",
    version="1.0.0",
    display_name="SV - Line Zone",
    category="Supervision",
    summary="Count objects crossing a line.",
    description="Counts objects crossing a line between two points. Provide start and end as 'x,y' strings. Tracks cumulative in/out counts across frames.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_any(), required=True),
        PortSpec(name="line_start", type=t_string(), required=True, default="0,240"),
        PortSpec(name="line_end", type=t_string(), required=True, default="640,240"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="in_count", type=t_int()),
        PortSpec(name="out_count", type=t_int()),
    ],
    cache_policy="disabled",
)


@register_node(SV_LINE_ZONE_SPEC)
class SvLineZoneNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_sv()
        dets = inputs.get("detections")
        if dets is None:
            raise ValueError("No detections provided")

        start_str = str(inputs.get("line_start") or "0,240")
        end_str = str(inputs.get("line_end") or "640,240")

        start_parts = [float(c.strip()) for c in start_str.split(",")]
        end_parts = [float(c.strip()) for c in end_str.split(",")]
        if len(start_parts) != 2 or len(end_parts) != 2:
            raise ValueError("Line start and end must be 'x,y' pairs")

        start = sv.Point(x=start_parts[0], y=start_parts[1])
        end = sv.Point(x=end_parts[0], y=end_parts[1])

        zone_key = f"_sv_line_zone_{self.id}_{start_str}_{end_str}"
        zone = ctx.get_var(zone_key)
        if zone is None:
            zone = sv.LineZone(start=start, end=end)
            ctx.set_var(zone_key, zone)

        zone.trigger(detections=dets)

        ctx.log(f"Line zone: in={zone.in_count}, out={zone.out_count}")
        return {
            "control_out": None,
            "in_count": zone.in_count,
            "out_count": zone.out_count,
        }
