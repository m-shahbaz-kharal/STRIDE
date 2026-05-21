"""Camera calibration nodes for traffic analysis.

Calibration is the foundation that lets every downstream node convert
pixel-space measurements into world-frame metres / metres-per-second.

We expose four practical calibration primitives:

1. ``traffic.calibration.identity`` — passthrough with optional
   ``scale_m_per_px`` for quick debugging on uncalibrated cameras.
2. ``traffic.calibration.from_homography`` — given 4+ image-to-world
   point correspondences, fits a planar homography (DLT). This is the
   most common practical calibration: a roadway is approximately flat,
   so a single homography maps the pavement plane.
3. ``traffic.calibration.from_known_width`` — derive
   ``scale_m_per_px`` from a known reference width visible in the
   image (e.g. a 3.65 m / 12 ft lane width).
4. ``traffic.calibration.vanishing_point`` — estimate the dominant
   vanishing point from a list of parallel-line samples (Lutton-Maitre
   1992). Useful for road-direction recovery.

All four output the same ``traffic.calibration`` record kind.
"""

from __future__ import annotations

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
    t_control,
    t_float,
    t_int,
    t_list,
    t_string,
)

from .types import make_calibration, t_traffic_calibration


def _require_numpy() -> None:
    if not HAS_NUMPY:
        raise NodeMissingDependencyError(
            "numpy is required for calibration nodes"
        )


# ---------------------------------------------------------------------------
# traffic.calibration.identity
# ---------------------------------------------------------------------------


IDENTITY_SPEC = NodeSpec(
    type="traffic.calibration.identity",
    version="1.0.0",
    display_name="Calibration · Identity",
    category="Traffic Calibration",
    summary="Passthrough calibration with optional scale_m_per_px.",
    description=(
        "Produces a TrafficCalibration record with default focal length and "
        "an identity homography (or one scaled by ``scale_m_per_px``). Use as "
        "a placeholder while iterating, or for camera setups where you only "
        "have a single linear scale and don't need a perspective-correct "
        "homography."
    ),
    icon="ruler",
    tags=["traffic", "calibration"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(
            name="image_width", type=t_int(), required=False, default=1280,
            description="Source-image width in pixels",
            constraints={"min": 1},
        ),
        PortSpec(
            name="image_height", type=t_int(), required=False, default=720,
            description="Source-image height in pixels",
            constraints={"min": 1},
        ),
        PortSpec(
            name="scale_m_per_px", type=t_float(), required=False, default=0.05,
            description="World metres per image pixel (rough scale)",
            constraints={"min": 0.0},
        ),
        PortSpec(
            name="frame", type=t_string(), required=False, default="world",
            description='Frame label (e.g. "world", "image")',
        ),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="calibration", type=t_traffic_calibration()),
    ],
    cache_policy="auto",
)


@register_node(IDENTITY_SPEC)
class CalibrationIdentityNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        w = int(inputs.get("image_width") or 1280)
        h = int(inputs.get("image_height") or 720)
        scale = float(inputs.get("scale_m_per_px") or 0.05)
        frame = str(inputs.get("frame") or "world")
        cal = make_calibration(
            image_width=w,
            image_height=h,
            scale_m_per_px=scale,
            frame=frame,
        )
        ctx.log(f"Identity calibration: {w}x{h} @ {scale:.4f} m/px")
        return {"control_out": None, "calibration": cal}


# ---------------------------------------------------------------------------
# traffic.calibration.from_homography
# ---------------------------------------------------------------------------


HOMOGRAPHY_SPEC = NodeSpec(
    type="traffic.calibration.from_homography",
    version="1.0.0",
    display_name="Calibration · Homography (4-pt)",
    category="Traffic Calibration",
    summary="Estimate H from 4+ image-to-world point pairs (DLT).",
    description=(
        "Given a list of image-plane points and the corresponding world-frame "
        "points (in metres on the ground plane), solves a planar homography "
        "via Direct Linear Transform. The resulting H projects pixel "
        "coordinates onto a flat ground plane — accurate to within a few cm "
        "for typical ITS camera angles."
    ),
    icon="ruler",
    tags=["traffic", "calibration", "homography"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image_width", type=t_int(), required=False, default=1280,
                 constraints={"min": 1}),
        PortSpec(name="image_height", type=t_int(), required=False, default=720,
                 constraints={"min": 1}),
        PortSpec(
            name="image_points", type=t_list(t_list(t_float())), required=True,
            description="List of [x, y] image-plane pixel coordinates "
                        "(at least 4)",
        ),
        PortSpec(
            name="world_points", type=t_list(t_list(t_float())), required=True,
            description="List of [X, Y] world-plane metric coordinates "
                        "in same order",
        ),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="calibration", type=t_traffic_calibration()),
        PortSpec(
            name="reprojection_error_px", type=t_float(),
            description="RMS reprojection error of the fitted H, in pixels",
        ),
    ],
    cache_policy="auto",
)


def _solve_homography_dlt(
    img: "np.ndarray", world: "np.ndarray"
) -> "np.ndarray":
    """Direct Linear Transform planar homography: img -> world.

    Solves H (3x3) such that homogeneous([X, Y, 1]) ~ H @ homogeneous(
    [u, v, 1]).
    """
    n = img.shape[0]
    A = np.zeros((2 * n, 9), dtype=np.float64)
    for i in range(n):
        u, v = float(img[i, 0]), float(img[i, 1])
        X, Y = float(world[i, 0]), float(world[i, 1])
        A[2 * i] = [-u, -v, -1.0, 0, 0, 0, X * u, X * v, X]
        A[2 * i + 1] = [0, 0, 0, -u, -v, -1.0, Y * u, Y * v, Y]
    # Smallest-singular-value vector of A is the null-space solution.
    _, _, vt = np.linalg.svd(A)
    h = vt[-1, :].reshape(3, 3)
    if abs(h[2, 2]) > 1e-12:
        h /= h[2, 2]
    return h


def _project(h: "np.ndarray", pts: "np.ndarray") -> "np.ndarray":
    n = pts.shape[0]
    homog = np.hstack([pts, np.ones((n, 1))])
    out = (h @ homog.T).T
    out[:, 0] /= np.where(np.abs(out[:, 2]) > 1e-12, out[:, 2], 1.0)
    out[:, 1] /= np.where(np.abs(out[:, 2]) > 1e-12, out[:, 2], 1.0)
    return out[:, :2]


@register_node(HOMOGRAPHY_SPEC)
class CalibrationFromHomographyNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_numpy()
        img_pts_raw = inputs.get("image_points") or []
        wld_pts_raw = inputs.get("world_points") or []
        if len(img_pts_raw) < 4 or len(wld_pts_raw) < 4:
            raise NodeInputError(
                "homography fitting needs at least 4 point correspondences",
                port="image_points",
                details={"img_n": len(img_pts_raw), "world_n": len(wld_pts_raw)},
            )
        if len(img_pts_raw) != len(wld_pts_raw):
            raise NodeInputError(
                "image_points and world_points must have the same length",
                port="image_points",
            )
        img_pts = np.asarray(img_pts_raw, dtype=np.float64)
        wld_pts = np.asarray(wld_pts_raw, dtype=np.float64)

        h = _solve_homography_dlt(img_pts, wld_pts)

        # Reprojection error (world -> image -> world cycle)
        proj_world = _project(h, img_pts)
        rms = float(np.sqrt(np.mean(np.sum((proj_world - wld_pts) ** 2, axis=1))))

        w = int(inputs.get("image_width") or 1280)
        ht = int(inputs.get("image_height") or 720)
        cal = make_calibration(
            image_width=w,
            image_height=ht,
            homography=h.tolist(),
            frame="world",
        )
        ctx.log(
            f"Homography calibration: {len(img_pts_raw)} pts, "
            f"reproj RMS {rms:.4f} m"
        )
        return {
            "control_out": None,
            "calibration": cal,
            "reprojection_error_px": rms,
        }


# ---------------------------------------------------------------------------
# traffic.calibration.from_known_width
# ---------------------------------------------------------------------------


KNOWN_WIDTH_SPEC = NodeSpec(
    type="traffic.calibration.from_known_width",
    version="1.0.0",
    display_name="Calibration · Known Width",
    category="Traffic Calibration",
    summary="Derive a uniform pixel-to-metre scale from a reference width.",
    description=(
        "Given two image points that span a known real-world distance "
        "(e.g. lane width = 3.65 m, or two posts 10 m apart), produces a "
        "scaled-identity calibration. Cheap and approximate — assumes the "
        "reference is roughly perpendicular to the camera optical axis."
    ),
    icon="ruler",
    tags=["traffic", "calibration"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image_width", type=t_int(), required=False, default=1280,
                 constraints={"min": 1}),
        PortSpec(name="image_height", type=t_int(), required=False, default=720,
                 constraints={"min": 1}),
        PortSpec(
            name="point_a", type=t_list(t_float()), required=True,
            description="First reference image-plane point [x, y]",
        ),
        PortSpec(
            name="point_b", type=t_list(t_float()), required=True,
            description="Second reference image-plane point [x, y]",
        ),
        PortSpec(
            name="real_distance_m", type=t_float(), required=False, default=3.65,
            description="Real-world distance between the two points (metres)",
            constraints={"min": 1e-6},
        ),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="calibration", type=t_traffic_calibration()),
        PortSpec(name="scale_m_per_px", type=t_float()),
    ],
    cache_policy="auto",
)


@register_node(KNOWN_WIDTH_SPEC)
class CalibrationFromKnownWidthNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_numpy()
        a = inputs.get("point_a") or [0.0, 0.0]
        b = inputs.get("point_b") or [1.0, 0.0]
        if len(a) < 2 or len(b) < 2:
            raise NodeInputError("point_a and point_b must be [x, y]")
        d_m = float(inputs.get("real_distance_m") or 3.65)
        dx = float(b[0]) - float(a[0])
        dy = float(b[1]) - float(a[1])
        d_px = (dx * dx + dy * dy) ** 0.5
        if d_px < 1e-6:
            raise NodeInputError(
                "point_a and point_b are coincident (zero pixel distance)"
            )
        scale = d_m / d_px
        w = int(inputs.get("image_width") or 1280)
        ht = int(inputs.get("image_height") or 720)
        cal = make_calibration(
            image_width=w,
            image_height=ht,
            scale_m_per_px=scale,
            frame="world",
        )
        ctx.log(
            f"Known-width calibration: {d_px:.2f} px = {d_m:.2f} m -> "
            f"{scale:.5f} m/px"
        )
        return {
            "control_out": None,
            "calibration": cal,
            "scale_m_per_px": scale,
        }


# ---------------------------------------------------------------------------
# traffic.calibration.vanishing_point
# ---------------------------------------------------------------------------


VANISHING_SPEC = NodeSpec(
    type="traffic.calibration.vanishing_point",
    version="1.0.0",
    display_name="Calibration · Vanishing Point",
    category="Traffic Calibration",
    summary="Estimate the dominant vanishing point from parallel lines.",
    description=(
        "Lutton-Maitre style vanishing-point estimator. Given a list of "
        "image-plane line segments that should be parallel in the world (e.g. "
        "lane-edge stripes), returns the least-squares-optimal point that all "
        "lines extend through. Augments the calibration with that VP for "
        "downstream nodes that infer road heading."
    ),
    icon="ruler",
    tags=["traffic", "calibration", "vanishing-point"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image_width", type=t_int(), required=False, default=1280,
                 constraints={"min": 1}),
        PortSpec(name="image_height", type=t_int(), required=False, default=720,
                 constraints={"min": 1}),
        PortSpec(
            name="lines", type=t_list(t_list(t_float())), required=True,
            description="List of line segments as [x1, y1, x2, y2] (pixel coords)",
        ),
        PortSpec(
            name="scale_m_per_px", type=t_float(), required=False, default=0.05,
            description="Optional metric scale to attach to the output",
            constraints={"min": 0.0},
        ),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="calibration", type=t_traffic_calibration()),
        PortSpec(name="vanishing_point", type=t_list(t_float())),
    ],
    cache_policy="auto",
)


def _line_to_homog(x1, y1, x2, y2) -> "np.ndarray":
    """Cross-product line representation (a, b, c) where a*x + b*y + c = 0."""
    p1 = np.array([x1, y1, 1.0])
    p2 = np.array([x2, y2, 1.0])
    line = np.cross(p1, p2)
    return line


@register_node(VANISHING_SPEC)
class CalibrationVanishingPointNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_numpy()
        raw = inputs.get("lines") or []
        if len(raw) < 2:
            raise NodeInputError(
                "vanishing-point estimation needs at least 2 lines",
                port="lines",
            )
        lines = []
        for ln in raw:
            if len(ln) < 4:
                continue
            line = _line_to_homog(ln[0], ln[1], ln[2], ln[3])
            n = np.linalg.norm(line)
            if n > 1e-9:
                lines.append(line / n)
        if len(lines) < 2:
            raise NodeInputError("not enough non-degenerate lines")
        L = np.asarray(lines, dtype=np.float64)
        # Solve L v = 0 in least squares sense: smallest singular vector
        _, _, vt = np.linalg.svd(L)
        v = vt[-1, :]
        if abs(v[2]) > 1e-12:
            vx = float(v[0] / v[2])
            vy = float(v[1] / v[2])
        else:
            vx = float(v[0])
            vy = float(v[1])

        w = int(inputs.get("image_width") or 1280)
        h = int(inputs.get("image_height") or 720)
        scale = float(inputs.get("scale_m_per_px") or 0.05)
        cal = make_calibration(
            image_width=w,
            image_height=h,
            vanishing_point=[vx, vy],
            scale_m_per_px=scale,
            frame="world",
        )
        ctx.log(f"Vanishing point: ({vx:.1f}, {vy:.1f})")
        return {
            "control_out": None,
            "calibration": cal,
            "vanishing_point": [vx, vy],
        }


# ---------------------------------------------------------------------------
# Helpers consumed by other modules
# ---------------------------------------------------------------------------


def project_pixel_to_world(
    cal: Dict[str, Any], x: float, y: float
) -> Optional[List[float]]:
    """Project a pixel (x, y) to world (X, Y) via the calibration's H."""
    if not HAS_NUMPY:
        return None
    h_raw = cal.get("homography")
    if not h_raw:
        s = cal.get("scale_m_per_px") or 1.0
        return [float(x) * float(s), float(y) * float(s)]
    h = np.asarray(h_raw, dtype=np.float64)
    p = np.array([float(x), float(y), 1.0])
    out = h @ p
    if abs(out[2]) < 1e-12:
        return None
    return [float(out[0] / out[2]), float(out[1] / out[2])]


def world_distance(
    cal: Dict[str, Any],
    a_px: List[float],
    b_px: List[float],
) -> Optional[float]:
    """World-frame metric distance between two pixel points."""
    pa = project_pixel_to_world(cal, a_px[0], a_px[1])
    pb = project_pixel_to_world(cal, b_px[0], b_px[1])
    if pa is None or pb is None:
        return None
    dx = pa[0] - pb[0]
    dy = pa[1] - pb[1]
    return (dx * dx + dy * dy) ** 0.5
