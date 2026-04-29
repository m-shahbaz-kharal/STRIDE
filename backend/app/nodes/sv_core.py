"""Supervision core nodes: image conversion and detection utilities.

Every ``t_any()`` port in this module carries an opaque, in-process
value: either a ``numpy.ndarray`` (BGR image) or a
``supervision.Detections`` handle. These are not the canonical record
types declared in ``stride-core``; the supervision library uses
ndarray-backed objects end-to-end and the wire form is recovered by
``sv.image.encode`` (image) or by the
``convert.sv.detections_to_detections2d`` /
``convert.sv.detections2d_to_detections`` marshallers shipped in the
``stride-converters`` package.

Per the Phase 5 §4 contract: the ``t_any()`` ports here are documented,
single-purpose escape hatches for live in-process Python references —
not unconstrained "anything goes" — and round-tripping into / out of the
canonical record types is supported by the explicit marshallers above.
"""
from __future__ import annotations

import base64
from typing import Any, Dict, List

import cv2
import numpy as np

from . import register_node
from .base import ExecutionContext, NodeBase
from ..node_spec import NodeSpec, PortSpec
from ..typesystem import t_any, t_control, t_float, t_int, t_list, t_string

try:
    import supervision as sv
except ImportError:
    sv = None  # type: ignore[assignment]


# ============================================================================
# Helpers
# ============================================================================

def _decode_base64_image(b64: str) -> np.ndarray:
    """Decode a base64 (optionally data-URL prefixed) string to a BGR numpy array."""
    if "," in b64:
        b64 = b64.split(",", 1)[1]
    data = base64.b64decode(b64)
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode image from base64 data")
    return img


def _encode_image_base64(img: np.ndarray) -> str:
    """Encode a BGR numpy array to a base64 data-URL string (PNG)."""
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("Failed to encode image to PNG")
    b64 = base64.b64encode(buf).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def _require_sv():
    if sv is None:
        raise ImportError(
            "The 'supervision' package is required for this node. "
            "Install it with: pip install supervision"
        )


# ============================================================================
# IMAGE CONVERSION
# ============================================================================

SV_IMAGE_DECODE_SPEC = NodeSpec(
    type="sv.image.decode",
    version="1.0.0",
    display_name="SV - Decode Image",
    category="Supervision",
    summary="Convert base64 image to numpy array.",
    description="Decodes a base64-encoded image string into a BGR numpy array for use with supervision nodes.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image_b64", type=t_string().with_nullable(True), required=True, default=""),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        # t_any: emits an in-process numpy ndarray (BGR), not the
        # canonical `image` record. The supervision pipeline uses
        # ndarrays end-to-end; the cross-process wire form is
        # produced by sv.image.encode below.
        PortSpec(name="image", type=t_any()),
    ],
)


@register_node(SV_IMAGE_DECODE_SPEC)
class SvImageDecodeNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        b64 = str(inputs.get("image_b64") or "")
        if not b64:
            raise ValueError("No image data provided")
        img = _decode_base64_image(b64)
        ctx.log(f"Decoded image: {img.shape}")
        return {"control_out": None, "image": img}


SV_IMAGE_ENCODE_SPEC = NodeSpec(
    type="sv.image.encode",
    version="1.0.0",
    display_name="SV - Encode Image",
    category="Supervision",
    summary="Convert numpy array to base64 image.",
    description="Encodes a BGR numpy array back into a base64 PNG data-URL string.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        # t_any: consumes an in-process numpy ndarray (BGR) produced by
        # sv.image.decode or any sv annotator. No record-shaped image
        # is convertible to a numpy array at the type level.
        PortSpec(name="image", type=t_any(), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image_b64", type=t_string()),
    ],
)


@register_node(SV_IMAGE_ENCODE_SPEC)
class SvImageEncodeNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        img = inputs.get("image")
        if img is None or not isinstance(img, np.ndarray):
            raise ValueError("Input must be a numpy array")
        b64 = _encode_image_base64(img)
        ctx.log(f"Encoded image: {img.shape} -> {len(b64)} chars")
        return {"control_out": None, "image_b64": b64}


# ============================================================================
# DETECTIONS
# ============================================================================

SV_DETECTIONS_CREATE_SPEC = NodeSpec(
    type="sv.detections.create",
    version="1.0.0",
    display_name="SV - Create Detections",
    category="Supervision",
    summary="Build a Detections object from arrays.",
    description="Creates a supervision Detections object from xyxy bounding boxes, optional confidence scores, and optional class IDs.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="xyxy", type=t_list(t_list(t_float())), required=True),
        PortSpec(name="confidence", type=t_list(t_float()).with_nullable(True),
                 required=False, default=None),
        PortSpec(name="class_id", type=t_list(t_int()).with_nullable(True),
                 required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        # t_any: emits an in-process supervision.Detections object,
        # opaque to the wire format. Annotator nodes consume it via
        # the same in-process ref. Phase-2 conversion to t_detections2d
        # would require sv.Detections -> record marshalling.
        PortSpec(name="detections", type=t_any()),
    ],
)


@register_node(SV_DETECTIONS_CREATE_SPEC)
class SvDetectionsCreateNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_sv()
        xyxy = np.array(inputs.get("xyxy"), dtype=np.float32)
        if xyxy.ndim == 1:
            xyxy = xyxy.reshape(-1, 4)

        kwargs: Dict[str, Any] = {"xyxy": xyxy}

        conf = inputs.get("confidence")
        if conf is not None:
            kwargs["confidence"] = np.array(conf, dtype=np.float32)

        cid = inputs.get("class_id")
        if cid is not None:
            kwargs["class_id"] = np.array(cid, dtype=int)

        detections = sv.Detections(**kwargs)
        ctx.log(f"Created Detections: {len(detections)} objects")
        return {"control_out": None, "detections": detections}


SV_DETECTIONS_FILTER_SPEC = NodeSpec(
    type="sv.detections.filter",
    version="1.0.0",
    display_name="SV - Filter Detections",
    category="Supervision",
    summary="Filter detections by confidence or class.",
    description="Filters a Detections object by minimum confidence threshold and/or a list of allowed class IDs.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        # t_any: see sv.detections.create — opaque sv.Detections handle.
        PortSpec(name="detections", type=t_any(), required=True),
        PortSpec(name="min_confidence", type=t_float(), required=False, default=0.0),
        PortSpec(name="class_ids", type=t_string(), required=False, default=""),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        # t_any: same opaque sv.Detections handle, sliced.
        PortSpec(name="detections", type=t_any()),
    ],
)


@register_node(SV_DETECTIONS_FILTER_SPEC)
class SvDetectionsFilterNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_sv()
        dets = inputs.get("detections")
        if dets is None:
            raise ValueError("No detections provided")

        min_conf = float(inputs.get("min_confidence") or 0.0)
        class_ids_str = str(inputs.get("class_ids") or "")

        mask = np.ones(len(dets), dtype=bool)

        if min_conf > 0.0 and dets.confidence is not None:
            mask &= dets.confidence >= min_conf

        if class_ids_str.strip() and dets.class_id is not None:
            allowed = [int(c.strip()) for c in class_ids_str.split(",") if c.strip()]
            mask &= np.isin(dets.class_id, allowed)

        filtered = dets[mask]
        ctx.log(f"Filtered: {len(dets)} -> {len(filtered)} detections")
        return {"control_out": None, "detections": filtered}


SV_DETECTIONS_COUNT_SPEC = NodeSpec(
    type="sv.detections.count",
    version="1.0.0",
    display_name="SV - Count Detections",
    category="Supervision",
    summary="Count detections and return stats.",
    description="Returns the count of detections and basic statistics (min/max/mean confidence).",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        # t_any: opaque sv.Detections handle (see sv.detections.create).
        PortSpec(name="detections", type=t_any(), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="count", type=t_int()),
        PortSpec(name="mean_confidence", type=t_float()),
    ],
)


@register_node(SV_DETECTIONS_COUNT_SPEC)
class SvDetectionsCountNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_sv()
        dets = inputs.get("detections")
        if dets is None:
            raise ValueError("No detections provided")

        count = len(dets)
        mean_conf = 0.0
        if count > 0 and dets.confidence is not None:
            mean_conf = float(np.mean(dets.confidence))

        ctx.log(f"Count: {count}, mean confidence: {mean_conf:.3f}")
        return {"control_out": None, "count": count, "mean_confidence": mean_conf}


SV_DETECTIONS_LABELS_SPEC = NodeSpec(
    type="sv.detections.labels",
    version="1.0.0",
    display_name="SV - Detection Labels",
    category="Supervision",
    summary="Generate label strings from detections.",
    description="Creates label strings from detections, optionally mapping class IDs to names and appending confidence scores.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        # t_any: opaque sv.Detections handle (see sv.detections.create).
        PortSpec(name="detections", type=t_any(), required=True),
        PortSpec(name="class_names", type=t_string(), required=False, default=""),
        PortSpec(name="show_confidence", type=t_float(), required=False, default=1.0),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="labels", type=t_list(t_string())),
    ],
)


@register_node(SV_DETECTIONS_LABELS_SPEC)
class SvDetectionsLabelsNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_sv()
        dets = inputs.get("detections")
        if dets is None:
            raise ValueError("No detections provided")

        class_names_str = str(inputs.get("class_names") or "")
        show_conf = float(inputs.get("show_confidence") or 1.0)

        name_list: List[str] = []
        if class_names_str.strip():
            name_list = [n.strip() for n in class_names_str.split(",")]

        labels: List[str] = []
        for i in range(len(dets)):
            parts: List[str] = []
            if dets.class_id is not None and name_list:
                cid = int(dets.class_id[i])
                name = name_list[cid] if cid < len(name_list) else f"class_{cid}"
                parts.append(name)
            elif dets.class_id is not None:
                parts.append(f"class_{int(dets.class_id[i])}")
            if show_conf > 0 and dets.confidence is not None:
                parts.append(f"{dets.confidence[i]:.2f}")
            labels.append(" ".join(parts))

        ctx.log(f"Generated {len(labels)} labels")
        return {"control_out": None, "labels": labels}
