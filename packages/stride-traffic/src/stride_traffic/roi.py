"""Region-of-interest geometry primitives for traffic graphs.

These nodes produce the simple line/polygon records consumed by the
counting, intersection, and event-detection nodes. They are kept tiny
and side-effect free so they can be reused freely.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.errors import NodeInputError
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_any,
    t_boolean,
    t_control,
    t_float,
    t_int,
    t_list,
    t_string,
)

from .types import (
    is_line,
    is_polygon,
    make_line,
    make_polygon,
    t_traffic_line,
    t_traffic_polygon,
)


# ---------------------------------------------------------------------------
# traffic.roi.line
# ---------------------------------------------------------------------------


LINE_SPEC = NodeSpec(
    type="traffic.roi.line",
    version="1.0.0",
    display_name="ROI · Line",
    category="Traffic ROI",
    summary="Define a directed virtual line in image coordinates.",
    description=(
        "Used by ``traffic.count.line`` and other crossing detectors. "
        "Direction matters: a positive crossing is from the left of "
        "``(a -> b)`` to the right (cross product convention)."
    ),
    icon="minus",
    tags=["traffic", "roi"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="name", type=t_string(), required=False, default="line",
                 description="Label for dashboards / events"),
        PortSpec(name="x1", type=t_float(), required=False, default=0.0),
        PortSpec(name="y1", type=t_float(), required=False, default=0.0),
        PortSpec(name="x2", type=t_float(), required=False, default=100.0),
        PortSpec(name="y2", type=t_float(), required=False, default=0.0),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="line", type=t_traffic_line()),
    ],
    cache_policy="auto",
)


@register_node(LINE_SPEC)
class RoiLineNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        line = make_line(
            name=str(inputs.get("name") or "line"),
            a=[float(inputs.get("x1") or 0.0), float(inputs.get("y1") or 0.0)],
            b=[float(inputs.get("x2") or 0.0), float(inputs.get("y2") or 0.0)],
        )
        return {"control_out": None, "line": line}


# ---------------------------------------------------------------------------
# traffic.roi.polygon
# ---------------------------------------------------------------------------


POLYGON_SPEC = NodeSpec(
    type="traffic.roi.polygon",
    version="1.0.0",
    display_name="ROI · Polygon",
    category="Traffic ROI",
    summary="Define a polygon ROI (in pixel coordinates) from a list of points.",
    description=(
        "Convex or simple-concave polygons are both supported by point-in-"
        "polygon tests. The polygon is consumed by counters, occupancy "
        "regions, and intersection turn-movement detectors."
    ),
    icon="hexagon",
    tags=["traffic", "roi"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="name", type=t_string(), required=False, default="zone"),
        PortSpec(
            name="points", type=t_list(t_list(t_float())), required=True,
            description="Vertices [[x, y], ...] in image coordinates",
        ),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="polygon", type=t_traffic_polygon()),
    ],
    cache_policy="auto",
)


@register_node(POLYGON_SPEC)
class RoiPolygonNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        raw = inputs.get("points") or []
        pts: List[List[float]] = []
        for p in raw:
            if isinstance(p, (list, tuple)) and len(p) >= 2:
                pts.append([float(p[0]), float(p[1])])
        if len(pts) < 3:
            raise NodeInputError(
                "polygon needs at least 3 vertices",
                port="points",
                details={"got": len(pts)},
            )
        return {
            "control_out": None,
            "polygon": make_polygon(
                name=str(inputs.get("name") or "zone"), points=pts
            ),
        }


# ---------------------------------------------------------------------------
# traffic.roi.lane_polygon — quad-shaped lane region
# ---------------------------------------------------------------------------


LANE_POLY_SPEC = NodeSpec(
    type="traffic.roi.lane_polygon",
    version="1.0.0",
    display_name="ROI · Lane Polygon (4-pt)",
    category="Traffic ROI",
    summary="A 4-vertex lane polygon parameterised by stop/start widths.",
    description=(
        "Convenience constructor: produces a trapezoidal lane polygon "
        "from a near/far centerline pair plus the lane's near and far "
        "widths in pixels. Useful when defining lanes from a perspective "
        "view of a road."
    ),
    icon="hexagon",
    tags=["traffic", "roi", "lane"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="name", type=t_string(), required=False, default="lane"),
        PortSpec(name="near_x", type=t_float(), required=False, default=640.0),
        PortSpec(name="near_y", type=t_float(), required=False, default=720.0),
        PortSpec(name="far_x", type=t_float(), required=False, default=640.0),
        PortSpec(name="far_y", type=t_float(), required=False, default=200.0),
        PortSpec(name="near_width", type=t_float(), required=False, default=400.0,
                 constraints={"min": 1.0}),
        PortSpec(name="far_width", type=t_float(), required=False, default=80.0,
                 constraints={"min": 1.0}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="polygon", type=t_traffic_polygon()),
    ],
    cache_policy="auto",
)


@register_node(LANE_POLY_SPEC)
class RoiLanePolygonNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        nx = float(inputs.get("near_x") or 0.0)
        ny = float(inputs.get("near_y") or 0.0)
        fx = float(inputs.get("far_x") or 0.0)
        fy = float(inputs.get("far_y") or 0.0)
        nw = float(inputs.get("near_width") or 1.0)
        fw = float(inputs.get("far_width") or 1.0)
        # Half-widths
        hw_near = nw / 2.0
        hw_far = fw / 2.0
        # Build a trapezoid: NL, FL, FR, NR (clockwise)
        pts = [
            [nx - hw_near, ny],
            [fx - hw_far, fy],
            [fx + hw_far, fy],
            [nx + hw_near, ny],
        ]
        return {
            "control_out": None,
            "polygon": make_polygon(
                name=str(inputs.get("name") or "lane"), points=pts
            ),
        }


# ---------------------------------------------------------------------------
# traffic.roi.merge_lines
# ---------------------------------------------------------------------------


MERGE_LINES_SPEC = NodeSpec(
    type="traffic.roi.merge_lines",
    version="1.0.0",
    display_name="ROI · Merge Lines",
    category="Traffic ROI",
    summary="Combine up to 8 individual lines into a single list.",
    description=(
        "ReactFlow does not yet have multi-input ports, so this node "
        "lets a counter consume several line ROIs (lanes, approaches, "
        "screen lines) by chaining them through one node."
    ),
    icon="git-merge",
    tags=["traffic", "roi"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
    ] + [
        PortSpec(name=f"line_{i}", type=t_traffic_line(),
                 required=False, default=None)
        for i in range(1, 9)
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="lines", type=t_list(t_traffic_line())),
        PortSpec(name="count", type=t_int()),
    ],
    cache_policy="auto",
)


@register_node(MERGE_LINES_SPEC)
class RoiMergeLinesNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        lines: List[Dict[str, Any]] = []
        for i in range(1, 9):
            v = inputs.get(f"line_{i}")
            if is_line(v):
                lines.append(v)
        return {"control_out": None, "lines": lines, "count": len(lines)}


# ---------------------------------------------------------------------------
# traffic.roi.merge_polygons
# ---------------------------------------------------------------------------


MERGE_POLYS_SPEC = NodeSpec(
    type="traffic.roi.merge_polygons",
    version="1.0.0",
    display_name="ROI · Merge Polygons",
    category="Traffic ROI",
    summary="Combine up to 8 polygons into a single list.",
    description="See ``traffic.roi.merge_lines``.",
    icon="git-merge",
    tags=["traffic", "roi"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
    ] + [
        PortSpec(name=f"polygon_{i}", type=t_traffic_polygon(),
                 required=False, default=None)
        for i in range(1, 9)
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="polygons", type=t_list(t_traffic_polygon())),
        PortSpec(name="count", type=t_int()),
    ],
    cache_policy="auto",
)


@register_node(MERGE_POLYS_SPEC)
class RoiMergePolygonsNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        polys: List[Dict[str, Any]] = []
        for i in range(1, 9):
            v = inputs.get(f"polygon_{i}")
            if is_polygon(v):
                polys.append(v)
        return {"control_out": None, "polygons": polys, "count": len(polys)}


# ---------------------------------------------------------------------------
# Geometry helpers (importable, used elsewhere)
# ---------------------------------------------------------------------------


def line_side(line: Dict[str, Any], point: List[float]) -> float:
    """Signed distance of point from the line.

    Positive => left of (a -> b), negative => right. Magnitude is the
    perpendicular pixel distance.
    """
    a = line["a"]
    b = line["b"]
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    norm = (dx * dx + dy * dy) ** 0.5
    if norm < 1e-9:
        return 0.0
    cross = (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])
    return cross / norm


def segments_intersect(p1, p2, p3, p4) -> bool:
    """Standard segment-segment intersection test."""

    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) > (b[1] - a[1]) * (c[0] - a[0])

    return ccw(p1, p3, p4) != ccw(p2, p3, p4) and ccw(p1, p2, p3) != ccw(p1, p2, p4)


def point_in_polygon(point: List[float], polygon: Dict[str, Any]) -> bool:
    """Ray-casting point-in-polygon test."""
    pts = polygon.get("points") or []
    if len(pts) < 3:
        return False
    x, y = float(point[0]), float(point[1])
    inside = False
    n = len(pts)
    j = n - 1
    for i in range(n):
        xi, yi = float(pts[i][0]), float(pts[i][1])
        xj, yj = float(pts[j][0]), float(pts[j][1])
        intersect = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
        )
        if intersect:
            inside = not inside
        j = i
    return inside


def detection_center(det: Dict[str, Any]) -> Optional[List[float]]:
    """Centre of a 2-D detection record. Returns [x, y] in pixels."""
    if "x1" in det and "y1" in det and "x2" in det and "y2" in det:
        return [
            (float(det["x1"]) + float(det["x2"])) / 2.0,
            (float(det["y1"]) + float(det["y2"])) / 2.0,
        ]
    if "center" in det and isinstance(det["center"], (list, tuple)):
        c = det["center"]
        return [float(c[0]), float(c[1])]
    return None


def detection_bottom_center(det: Dict[str, Any]) -> Optional[List[float]]:
    """Bottom-centre of a 2-D bbox — better proxy for ground-plane projection."""
    if "x1" in det and "y2" in det:
        return [
            (float(det["x1"]) + float(det["x2"])) / 2.0,
            float(det["y2"]),
        ]
    return detection_center(det)
