"""Supervision annotator nodes for drawing on images."""
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
# Annotator helper
# ============================================================================

def _run_annotator(annotator, image: np.ndarray, detections, labels=None) -> np.ndarray:
    """Run an annotator, passing labels if supported."""
    scene = image.copy()
    if labels is not None and hasattr(annotator, "annotate") and "labels" in annotator.annotate.__code__.co_varnames:
        return annotator.annotate(scene=scene, detections=detections, labels=labels)
    return annotator.annotate(scene=scene, detections=detections)


# ============================================================================
# BOX ANNOTATOR
# ============================================================================

SV_BOX_ANNOTATOR_SPEC = NodeSpec(
    type="sv.annotate.box",
    version="1.0.0",
    display_name="SV - Box Annotator",
    category="Supervision",
    summary="Draw bounding boxes on image.",
    description="Draws bounding boxes around detections using supervision's BoxAnnotator.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any(), required=True),
        PortSpec(name="detections", type=t_any(), required=True),
        PortSpec(name="thickness", type=t_int(), required=False, default=2),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any()),
    ],
)


@register_node(SV_BOX_ANNOTATOR_SPEC)
class SvBoxAnnotatorNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_sv()
        image = inputs.get("image")
        dets = inputs.get("detections")
        thickness = int(inputs.get("thickness") or 2)

        annotator = sv.BoxAnnotator(thickness=thickness)
        result = annotator.annotate(scene=image.copy(), detections=dets)
        ctx.log(f"Box annotator: {len(dets)} detections")
        return {"control_out": None, "image": result}


# ============================================================================
# LABEL ANNOTATOR
# ============================================================================

SV_LABEL_ANNOTATOR_SPEC = NodeSpec(
    type="sv.annotate.label",
    version="1.0.0",
    display_name="SV - Label Annotator",
    category="Supervision",
    summary="Draw labels on image.",
    description="Draws text labels for each detection using supervision's LabelAnnotator.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any(), required=True),
        PortSpec(name="detections", type=t_any(), required=True),
        PortSpec(name="labels", type=t_list(t_string()), required=False, default=None),
        PortSpec(name="text_scale", type=t_float(), required=False, default=0.5),
        PortSpec(name="text_thickness", type=t_int(), required=False, default=1),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any()),
    ],
)


@register_node(SV_LABEL_ANNOTATOR_SPEC)
class SvLabelAnnotatorNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_sv()
        image = inputs.get("image")
        dets = inputs.get("detections")
        labels = inputs.get("labels")
        text_scale = float(inputs.get("text_scale") or 0.5)
        text_thickness = int(inputs.get("text_thickness") or 1)

        annotator = sv.LabelAnnotator(text_scale=text_scale, text_thickness=text_thickness)
        kwargs: Dict[str, Any] = {"scene": image.copy(), "detections": dets}
        if labels is not None:
            kwargs["labels"] = list(labels)
        result = annotator.annotate(**kwargs)
        ctx.log(f"Label annotator: {len(dets)} detections")
        return {"control_out": None, "image": result}


# ============================================================================
# MASK ANNOTATOR
# ============================================================================

SV_MASK_ANNOTATOR_SPEC = NodeSpec(
    type="sv.annotate.mask",
    version="1.0.0",
    display_name="SV - Mask Annotator",
    category="Supervision",
    summary="Draw filled masks on image.",
    description="Draws semi-transparent filled masks for detections using supervision's MaskAnnotator.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any(), required=True),
        PortSpec(name="detections", type=t_any(), required=True),
        PortSpec(name="opacity", type=t_float(), required=False, default=0.5),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any()),
    ],
)


@register_node(SV_MASK_ANNOTATOR_SPEC)
class SvMaskAnnotatorNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_sv()
        image = inputs.get("image")
        dets = inputs.get("detections")
        opacity = float(inputs.get("opacity") or 0.5)

        annotator = sv.MaskAnnotator(opacity=opacity)
        result = annotator.annotate(scene=image.copy(), detections=dets)
        ctx.log(f"Mask annotator: {len(dets)} detections")
        return {"control_out": None, "image": result}


# ============================================================================
# CIRCLE ANNOTATOR
# ============================================================================

SV_CIRCLE_ANNOTATOR_SPEC = NodeSpec(
    type="sv.annotate.circle",
    version="1.0.0",
    display_name="SV - Circle Annotator",
    category="Supervision",
    summary="Draw circles at detection centers.",
    description="Draws circles at the center of each detection using supervision's CircleAnnotator.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any(), required=True),
        PortSpec(name="detections", type=t_any(), required=True),
        PortSpec(name="thickness", type=t_int(), required=False, default=2),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any()),
    ],
)


@register_node(SV_CIRCLE_ANNOTATOR_SPEC)
class SvCircleAnnotatorNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_sv()
        image = inputs.get("image")
        dets = inputs.get("detections")
        thickness = int(inputs.get("thickness") or 2)

        annotator = sv.CircleAnnotator(thickness=thickness)
        result = annotator.annotate(scene=image.copy(), detections=dets)
        ctx.log(f"Circle annotator: {len(dets)} detections")
        return {"control_out": None, "image": result}


# ============================================================================
# DOT ANNOTATOR
# ============================================================================

SV_DOT_ANNOTATOR_SPEC = NodeSpec(
    type="sv.annotate.dot",
    version="1.0.0",
    display_name="SV - Dot Annotator",
    category="Supervision",
    summary="Draw dots at detection centers.",
    description="Draws small dots at the center of each detection using supervision's DotAnnotator.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any(), required=True),
        PortSpec(name="detections", type=t_any(), required=True),
        PortSpec(name="radius", type=t_int(), required=False, default=4),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any()),
    ],
)


@register_node(SV_DOT_ANNOTATOR_SPEC)
class SvDotAnnotatorNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_sv()
        image = inputs.get("image")
        dets = inputs.get("detections")
        radius = int(inputs.get("radius") or 4)

        annotator = sv.DotAnnotator(radius=radius)
        result = annotator.annotate(scene=image.copy(), detections=dets)
        ctx.log(f"Dot annotator: {len(dets)} detections")
        return {"control_out": None, "image": result}


# ============================================================================
# BLUR ANNOTATOR
# ============================================================================

SV_BLUR_ANNOTATOR_SPEC = NodeSpec(
    type="sv.annotate.blur",
    version="1.0.0",
    display_name="SV - Blur Annotator",
    category="Supervision",
    summary="Blur detection regions.",
    description="Blurs the region inside each detection's bounding box using supervision's BlurAnnotator.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any(), required=True),
        PortSpec(name="detections", type=t_any(), required=True),
        PortSpec(name="kernel_size", type=t_int(), required=False, default=15),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any()),
    ],
)


@register_node(SV_BLUR_ANNOTATOR_SPEC)
class SvBlurAnnotatorNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_sv()
        image = inputs.get("image")
        dets = inputs.get("detections")
        kernel_size = int(inputs.get("kernel_size") or 15)

        annotator = sv.BlurAnnotator(kernel_size=kernel_size)
        result = annotator.annotate(scene=image.copy(), detections=dets)
        ctx.log(f"Blur annotator: {len(dets)} detections")
        return {"control_out": None, "image": result}


# ============================================================================
# PIXELATE ANNOTATOR
# ============================================================================

SV_PIXELATE_ANNOTATOR_SPEC = NodeSpec(
    type="sv.annotate.pixelate",
    version="1.0.0",
    display_name="SV - Pixelate Annotator",
    category="Supervision",
    summary="Pixelate detection regions.",
    description="Pixelates the region inside each detection's bounding box using supervision's PixelateAnnotator.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any(), required=True),
        PortSpec(name="detections", type=t_any(), required=True),
        PortSpec(name="pixel_size", type=t_int(), required=False, default=20),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any()),
    ],
)


@register_node(SV_PIXELATE_ANNOTATOR_SPEC)
class SvPixelateAnnotatorNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_sv()
        image = inputs.get("image")
        dets = inputs.get("detections")
        pixel_size = int(inputs.get("pixel_size") or 20)

        annotator = sv.PixelateAnnotator(pixel_size=pixel_size)
        result = annotator.annotate(scene=image.copy(), detections=dets)
        ctx.log(f"Pixelate annotator: {len(dets)} detections")
        return {"control_out": None, "image": result}


# ============================================================================
# HEATMAP ANNOTATOR
# ============================================================================

SV_HEATMAP_ANNOTATOR_SPEC = NodeSpec(
    type="sv.annotate.heatmap",
    version="1.0.0",
    display_name="SV - Heatmap Annotator",
    category="Supervision",
    summary="Draw heatmap overlay on image.",
    description="Draws a heatmap overlay based on detection density using supervision's HeatMapAnnotator.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any(), required=True),
        PortSpec(name="detections", type=t_any(), required=True),
        PortSpec(name="opacity", type=t_float(), required=False, default=0.5),
        PortSpec(name="radius", type=t_int(), required=False, default=40),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any()),
    ],
)


@register_node(SV_HEATMAP_ANNOTATOR_SPEC)
class SvHeatmapAnnotatorNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_sv()
        image = inputs.get("image")
        dets = inputs.get("detections")
        opacity = float(inputs.get("opacity") or 0.5)
        radius = int(inputs.get("radius") or 40)

        annotator = sv.HeatMapAnnotator(opacity=opacity, radius=radius)
        result = annotator.annotate(scene=image.copy(), detections=dets)
        ctx.log(f"Heatmap annotator: {len(dets)} detections")
        return {"control_out": None, "image": result}


# ============================================================================
# CORNER BOX ANNOTATOR
# ============================================================================

SV_CORNER_BOX_ANNOTATOR_SPEC = NodeSpec(
    type="sv.annotate.corner_box",
    version="1.0.0",
    display_name="SV - Corner Box Annotator",
    category="Supervision",
    summary="Draw corner-style bounding boxes.",
    description="Draws corner-style bounding boxes for detections using supervision's BoxCornerAnnotator.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any(), required=True),
        PortSpec(name="detections", type=t_any(), required=True),
        PortSpec(name="thickness", type=t_int(), required=False, default=2),
        PortSpec(name="corner_length", type=t_int(), required=False, default=15),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any()),
    ],
)


@register_node(SV_CORNER_BOX_ANNOTATOR_SPEC)
class SvCornerBoxAnnotatorNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_sv()
        image = inputs.get("image")
        dets = inputs.get("detections")
        thickness = int(inputs.get("thickness") or 2)
        corner_length = int(inputs.get("corner_length") or 15)

        annotator = sv.BoxCornerAnnotator(thickness=thickness, corner_length=corner_length)
        result = annotator.annotate(scene=image.copy(), detections=dets)
        ctx.log(f"Corner box annotator: {len(dets)} detections")
        return {"control_out": None, "image": result}


# ============================================================================
# COLOR ANNOTATOR
# ============================================================================

SV_COLOR_ANNOTATOR_SPEC = NodeSpec(
    type="sv.annotate.color",
    version="1.0.0",
    display_name="SV - Color Annotator",
    category="Supervision",
    summary="Draw colored regions for detections.",
    description="Fills detection bounding box regions with semi-transparent color using supervision's ColorAnnotator.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any(), required=True),
        PortSpec(name="detections", type=t_any(), required=True),
        PortSpec(name="opacity", type=t_float(), required=False, default=0.5),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any()),
    ],
)


@register_node(SV_COLOR_ANNOTATOR_SPEC)
class SvColorAnnotatorNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_sv()
        image = inputs.get("image")
        dets = inputs.get("detections")
        opacity = float(inputs.get("opacity") or 0.5)

        annotator = sv.ColorAnnotator(opacity=opacity)
        result = annotator.annotate(scene=image.copy(), detections=dets)
        ctx.log(f"Color annotator: {len(dets)} detections")
        return {"control_out": None, "image": result}


# ============================================================================
# TRACE ANNOTATOR
# ============================================================================

SV_TRACE_ANNOTATOR_SPEC = NodeSpec(
    type="sv.annotate.trace",
    version="1.0.0",
    display_name="SV - Trace Annotator",
    category="Supervision",
    summary="Draw tracking trails on image.",
    description="Draws motion trails for tracked objects using supervision's TraceAnnotator. Requires detections with tracker_id (from YOLO Track or SV ByteTrack). State persists across frames within the same graph run.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any(), required=True),
        PortSpec(name="detections", type=t_any(), required=True),
        PortSpec(name="trace_length", type=t_int(), required=False, default=30),
        PortSpec(name="thickness", type=t_int(), required=False, default=2),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_any()),
    ],
    cache_policy="disabled",
)


@register_node(SV_TRACE_ANNOTATOR_SPEC)
class SvTraceAnnotatorNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_sv()
        image = inputs.get("image")
        dets = inputs.get("detections")
        trace_length = int(inputs.get("trace_length") or 30)
        thickness = int(inputs.get("thickness") or 2)

        cache_key = f"_sv_trace_annotator_{self.id}"
        annotator = ctx.get_var(cache_key)
        if annotator is None:
            annotator = sv.TraceAnnotator(trace_length=trace_length, thickness=thickness)
            ctx.set_var(cache_key, annotator)

        result = annotator.annotate(scene=image.copy(), detections=dets)
        ctx.log(f"Trace annotator: {len(dets)} detections")
        return {"control_out": None, "image": result}
