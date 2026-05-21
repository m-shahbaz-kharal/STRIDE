"""
The ``convert.*`` node family.

Each node wraps a single, well-known transform that bridges between two
canonical record types declared in ``stride-core``:

  * image / grayscale / RGB
  * 2-D detection records (``detections2d`` <-> list of ``bbox2d``)
  * pose keypoints -> bounding boxes
  * depth map -> point cloud
  * point cloud subsampling and box-cropping
  * scalar / list / record helpers

The frontend reads each spec's ``metadata.convert_from`` /
``metadata.convert_to`` to build a single-hop converter index. When the
user attempts a connection between mismatched kinds, the editor offers
the cheapest matching converter as a one-click insertion.

Design reference: ``docs/architecture/unified-type-system-and-ux.md`` §4.5.
"""

from __future__ import annotations

import base64
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import numpy as np

try:
    import cv2  # type: ignore
    HAS_CV2 = True
except ImportError:  # pragma: no cover - import guard
    HAS_CV2 = False
    cv2 = None  # type: ignore

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.errors import (
    NodeInputError,
    NodeMissingDependencyError,
    NodeNetworkError,
    NodeFileNotFoundError,
)
from stride_core.image_utils import (
    decode_image_to_numpy,
    encode_numpy_to_image,
    make_bbox2d,
    make_detections2d,
)
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_any,
    t_boolean,
    t_bbox2d,
    t_bbox3d,
    t_control,
    t_depthmap,
    t_detections2d,
    t_float,
    t_image,
    t_int,
    t_keypoints,
    t_list,
    t_map,
    t_mat3,
    t_pointcloud,
    t_record,
    t_string,
    TypeDescriptor,
)


# =============================================================================
# Spec helpers
# =============================================================================
#
# Every converter declares ``metadata.convert_from`` / ``convert_to`` so
# the frontend can index them. Cost is advisory (1..10), suggested means
# the editor offers a one-click insert; both default to sensible values
# below so individual nodes only override when interesting.


def _convert_meta(
    *,
    convert_from: str,
    convert_to: str,
    cost: int = 3,
    suggested: bool = True,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "convert_from": convert_from,
        "convert_to": convert_to,
        "cost": int(cost),
        "suggested": bool(suggested),
    }
    if extra:
        payload.update(extra)
    return payload


def _require_cv2() -> None:
    if not HAS_CV2:
        raise NodeMissingDependencyError(
            "opencv-python is required (pip install opencv-python)"
        )


# =============================================================================
# Image converters
# =============================================================================


URL_LOAD_SPEC = NodeSpec(
    type="convert.image.from_url",
    version="1.0.0",
    display_name="URL → Image",
    category="Convert",
    summary="Load an image from a URL or file path.",
    description=(
        "Fetches an image from an HTTP(S) URL or reads it from a local "
        "file path. Emits a canonical Image record (data URL, base64)."
    ),
    icon="download",
    tags=["convert", "image", "url"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(
            name="url",
            # Nullable so live-stream sources (fl511.get_frame.image) that
            # may transiently emit ``null`` between frames can flow into
            # this converter without a static type error. The runtime
            # raises ``NodeInputError`` if ``None``/empty arrives.
            type=t_string().with_nullable(True),
            required=True,
            description="HTTP(S) URL, data: URL, or absolute file path to load.",
        ),
        PortSpec(
            name="timeout",
            type=t_float(),
            required=False,
            default=10.0,
            constraints={"min": 0.1, "max": 120.0},
        ),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_image()),
        PortSpec(name="width", type=t_int()),
        PortSpec(name="height", type=t_int()),
    ],
    cache_policy="auto",
    metadata=_convert_meta(convert_from="string", convert_to="image", cost=4),
)


def _looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https", "file"}


def _decode_data_url(value: str) -> bytes:
    """Decode an RFC 2397 ``data:`` URL into raw bytes.

    Accepts ``data:<mime>;base64,<payload>``. Non-base64 / percent-encoded
    payloads aren't relevant for image streams produced by FL511 etc.
    """
    if not value.startswith("data:"):
        raise NodeInputError("not a data: URL", port="url")
    head, _, body = value.partition(",")
    if not body:
        raise NodeInputError("data: URL has no payload", port="url")
    if ";base64" in head:
        try:
            return base64.b64decode(body)
        except Exception as exc:
            raise NodeInputError(
                f"data: URL base64 decode failed: {exc}", port="url",
            ) from exc
    # Percent-encoded text payload — supported but rare for images.
    from urllib.parse import unquote_to_bytes
    return unquote_to_bytes(body)


@register_node(URL_LOAD_SPEC)
class ConvertImageFromUrlNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_cv2()
        url = str(inputs.get("url") or "").strip()
        if not url:
            raise NodeInputError("url is required", port="url")
        timeout = float(inputs.get("timeout") if inputs.get("timeout") is not None else 10.0)

        raw: bytes
        if url.startswith("data:"):
            raw = _decode_data_url(url)
        elif _looks_like_url(url):
            try:
                req = Request(url, headers={"User-Agent": "STRIDE-Converter/1.0"})
                with urlopen(req, timeout=timeout) as resp:
                    raw = resp.read()
            except Exception as exc:
                raise NodeNetworkError(
                    f"failed to fetch {url!r}: {exc}", port="url",
                ) from exc
        else:
            if not os.path.isfile(url):
                raise NodeFileNotFoundError(f"file not found: {url}", port="url")
            with open(url, "rb") as f:
                raw = f.read()

        arr = np.frombuffer(raw, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None:
            raise NodeInputError("could not decode image bytes", port="url")
        h, w = bgr.shape[:2]
        data_url = encode_numpy_to_image(bgr, fmt="jpeg", quality=90)
        ctx.log(f"convert.image.from_url: {w}x{h} from {url}")

        record = {
            "_type": "Image",
            "width": int(w),
            "height": int(h),
            "format": "jpeg",
            "data_b64": data_url,
        }
        return {"control_out": None, "image": record, "width": int(w), "height": int(h)}


GRAYSCALE_SPEC = NodeSpec(
    type="convert.image.to_grayscale",
    version="1.0.0",
    display_name="Image → Grayscale",
    category="Convert",
    summary="Convert an RGB/BGR image to single-channel grayscale.",
    description=(
        "Drops chroma using the standard ITU-R BT.601 luma coefficients "
        "(cv2.cvtColor BGR2GRAY). Output is a 3-channel grayscale image "
        "for downstream nodes that still expect H×W×3 input."
    ),
    icon="filter",
    tags=["convert", "image", "grayscale"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_image(), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_image(subtype="grayscale")),
    ],
    cache_policy="auto",
    metadata=_convert_meta(convert_from="image", convert_to="image", cost=2),
)


@register_node(GRAYSCALE_SPEC)
class ConvertImageToGrayscaleNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_cv2()
        image = inputs.get("image")
        data_url = _image_data_url(image)
        bgr = decode_image_to_numpy(data_url)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        gray3 = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        encoded = encode_numpy_to_image(gray3, fmt="jpeg", quality=90)
        h, w = gray3.shape[:2]
        ctx.log(f"convert.image.to_grayscale: {w}x{h}")
        return {
            "control_out": None,
            "image": {
                "_type": "Image",
                "width": int(w),
                "height": int(h),
                "format": "jpeg",
                "data_b64": encoded,
            },
        }


GRAY_TO_RGB_SPEC = NodeSpec(
    type="convert.image.from_grayscale_to_rgb",
    version="1.0.0",
    display_name="Grayscale → RGB",
    category="Convert",
    summary="Promote a single-channel image to a 3-channel BGR record.",
    description=(
        "Replicates the luminance plane across the BGR channels so "
        "downstream nodes that require 3-channel input work unchanged."
    ),
    icon="image",
    tags=["convert", "image", "rgb", "grayscale"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_image(), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_image(subtype="rgb")),
    ],
    cache_policy="auto",
    metadata=_convert_meta(convert_from="image", convert_to="image", cost=2),
)


@register_node(GRAY_TO_RGB_SPEC)
class ConvertGrayscaleToRgbNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_cv2()
        data_url = _image_data_url(inputs.get("image"))
        bgr = decode_image_to_numpy(data_url)
        if bgr.ndim == 2:
            rgb_like = cv2.cvtColor(bgr, cv2.COLOR_GRAY2BGR)
        elif bgr.ndim == 3 and bgr.shape[2] == 1:
            rgb_like = cv2.cvtColor(bgr[:, :, 0], cv2.COLOR_GRAY2BGR)
        else:
            # Already 3-channel; preserve as-is (the operation is idempotent
            # in practice when feeding the result to nodes expecting BGR).
            rgb_like = bgr
        encoded = encode_numpy_to_image(rgb_like, fmt="jpeg", quality=90)
        h, w = rgb_like.shape[:2]
        ctx.log(f"convert.image.from_grayscale_to_rgb: {w}x{h}")
        return {
            "control_out": None,
            "image": {
                "_type": "Image",
                "width": int(w),
                "height": int(h),
                "format": "jpeg",
                "data_b64": encoded,
            },
        }


def _image_data_url(image: Any) -> str:
    """Pull a base64 data URL out of a STRIDE Image record or raw string."""
    if isinstance(image, str):
        return image
    if isinstance(image, dict):
        candidate = image.get("data_b64") or image.get("image") or ""
        if not isinstance(candidate, str):
            candidate = ""
        return candidate
    raise NodeInputError("image input is empty", port="image")


# =============================================================================
# 2-D detection converters
# =============================================================================


XYXY_TO_XYWH_SPEC = NodeSpec(
    type="convert.detections2d.xyxy_to_xywh",
    version="1.0.0",
    display_name="Detections2D xyxy → xywh",
    category="Convert",
    summary="Re-encode bounding boxes from corner form to centre+size form.",
    description=(
        "Each box's (x1, y1, x2, y2) is rewritten as (cx, cy, w, h) and "
        "carried alongside the original corners so downstream consumers "
        "can pick whichever they prefer. Class id, label, confidence and "
        "track id are preserved unchanged."
    ),
    icon="square",
    tags=["convert", "detections2d", "bbox2d"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d(), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d()),
        PortSpec(name="boxes_xywh", type=t_list(t_list(t_float()))),
    ],
    cache_policy="auto",
    metadata=_convert_meta(convert_from="detections2d", convert_to="detections2d", cost=1),
)


@register_node(XYXY_TO_XYWH_SPEC)
class ConvertDetections2DXyxyToXywhNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        rec = inputs.get("detections")
        if not isinstance(rec, dict):
            raise NodeInputError("detections must be a Detections2D record", port="detections")
        boxes = list(rec.get("boxes") or [])
        out_boxes: List[Dict[str, Any]] = []
        xywh: List[List[float]] = []
        for b in boxes:
            x1, y1, x2, y2 = float(b["x1"]), float(b["y1"]), float(b["x2"]), float(b["y2"])
            w = max(0.0, x2 - x1)
            h = max(0.0, y2 - y1)
            cx = x1 + w / 2.0
            cy = y1 + h / 2.0
            updated = dict(b)
            updated["cx"] = cx
            updated["cy"] = cy
            updated["w"] = w
            updated["h"] = h
            out_boxes.append(updated)
            xywh.append([cx, cy, w, h])

        out_rec = dict(rec)
        out_rec["boxes"] = out_boxes
        ctx.log(f"convert.detections2d.xyxy_to_xywh: {len(out_boxes)} boxes")
        return {"control_out": None, "detections": out_rec, "boxes_xywh": xywh}


XYWH_TO_XYXY_SPEC = NodeSpec(
    type="convert.detections2d.xywh_to_xyxy",
    version="1.0.0",
    display_name="Detections2D xywh → xyxy",
    category="Convert",
    summary="Re-encode (cx, cy, w, h) back to (x1, y1, x2, y2) corners.",
    description=(
        "Inverse of ``convert.detections2d.xyxy_to_xywh``. Reads "
        "centre+size fields when present and populates the canonical "
        "x1/y1/x2/y2 fields used by every downstream box consumer."
    ),
    icon="square",
    tags=["convert", "detections2d", "bbox2d"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d(), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d()),
    ],
    cache_policy="auto",
    metadata=_convert_meta(convert_from="detections2d", convert_to="detections2d", cost=1),
)


@register_node(XYWH_TO_XYXY_SPEC)
class ConvertDetections2DXywhToXyxyNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        rec = inputs.get("detections")
        if not isinstance(rec, dict):
            raise NodeInputError("detections must be a Detections2D record", port="detections")
        boxes_in = list(rec.get("boxes") or [])
        out_boxes: List[Dict[str, Any]] = []
        for b in boxes_in:
            updated = dict(b)
            if "cx" in b and "cy" in b and "w" in b and "h" in b:
                cx, cy, w, h = float(b["cx"]), float(b["cy"]), float(b["w"]), float(b["h"])
                updated["x1"] = cx - w / 2.0
                updated["y1"] = cy - h / 2.0
                updated["x2"] = cx + w / 2.0
                updated["y2"] = cy + h / 2.0
            out_boxes.append(updated)
        out_rec = dict(rec)
        out_rec["boxes"] = out_boxes
        ctx.log(f"convert.detections2d.xywh_to_xyxy: {len(out_boxes)} boxes")
        return {"control_out": None, "detections": out_rec}


FROM_POSE_SPEC = NodeSpec(
    type="convert.detections2d.from_pose",
    version="1.0.0",
    display_name="Pose → Detections2D",
    category="Convert",
    summary="Derive bounding boxes from pose keypoint extents.",
    description=(
        "For each pose instance, computes the axis-aligned bounding box "
        "covering all keypoints with visibility above ``min_visibility``. "
        "The resulting Detections2D record can be fed into trackers, "
        "filters, or visualisers that operate on bbox2d records."
    ),
    icon="user",
    tags=["convert", "keypoints", "detections2d"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="keypoints", type=t_keypoints(), required=True),
        PortSpec(name="image_width", type=t_int(), required=False, default=0),
        PortSpec(name="image_height", type=t_int(), required=False, default=0),
        PortSpec(
            name="min_visibility",
            type=t_float(),
            required=False,
            default=0.1,
            constraints={"min": 0.0, "max": 1.0},
        ),
        PortSpec(
            name="padding",
            type=t_float(),
            required=False,
            default=0.05,
            description="Fractional padding of the resulting bbox.",
            constraints={"min": 0.0, "max": 0.5},
        ),
        PortSpec(name="class_id", type=t_int(), required=False, default=0),
        PortSpec(name="class_name", type=t_string(), required=False, default="person"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d()),
        PortSpec(name="boxes", type=t_list(t_bbox2d())),
        PortSpec(name="count", type=t_int()),
    ],
    cache_policy="auto",
    metadata=_convert_meta(convert_from="keypoints", convert_to="detections2d", cost=2),
)


@register_node(FROM_POSE_SPEC)
class ConvertPoseToDetections2DNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        rec = inputs.get("keypoints")
        if not isinstance(rec, dict):
            raise NodeInputError("keypoints must be a Keypoints record", port="keypoints")
        instances = list(rec.get("instances") or [])

        width = int(inputs.get("image_width") or 0)
        height = int(inputs.get("image_height") or 0)
        min_vis = float(inputs.get("min_visibility") or 0.1)
        pad = float(inputs.get("padding") or 0.0)
        class_id = int(inputs.get("class_id") or 0)
        class_name = str(inputs.get("class_name") or "person")

        boxes: List[Dict[str, Any]] = []
        for inst in instances:
            kps = inst.get("keypoints") if isinstance(inst, dict) else None
            if not kps:
                continue
            xs: List[float] = []
            ys: List[float] = []
            for kp in kps:
                if isinstance(kp, dict):
                    x = float(kp.get("x", kp.get("u", 0.0)))
                    y = float(kp.get("y", kp.get("v", 0.0)))
                    v = float(kp.get("visibility", kp.get("v", 1.0)))
                elif isinstance(kp, (list, tuple)):
                    x = float(kp[0])
                    y = float(kp[1])
                    v = float(kp[2]) if len(kp) >= 3 else 1.0
                else:
                    continue
                if v < min_vis:
                    continue
                xs.append(x)
                ys.append(y)
            if not xs:
                continue
            x1, x2 = min(xs), max(xs)
            y1, y2 = min(ys), max(ys)
            box_w = x2 - x1
            box_h = y2 - y1
            if pad > 0:
                x1 -= box_w * pad
                x2 += box_w * pad
                y1 -= box_h * pad
                y2 += box_h * pad
            if width > 0:
                x1 = max(0.0, min(x1, float(width)))
                x2 = max(0.0, min(x2, float(width)))
            if height > 0:
                y1 = max(0.0, min(y1, float(height)))
                y2 = max(0.0, min(y2, float(height)))
            confidence = float(inst.get("confidence", 1.0)) if isinstance(inst, dict) else 1.0
            boxes.append(make_bbox2d(
                x1=x1, y1=y1, x2=x2, y2=y2,
                confidence=confidence,
                class_id=class_id,
                class_name=class_name,
            ))

        detections = make_detections2d(boxes, width, height)
        ctx.log(f"convert.detections2d.from_pose: {len(boxes)} boxes from {len(instances)} poses")
        return {
            "control_out": None,
            "detections": detections,
            "boxes": boxes,
            "count": len(boxes),
        }


CROP_IMAGE_SPEC = NodeSpec(
    type="convert.bbox.crop_image",
    version="1.0.0",
    display_name="Crop image to bbox",
    category="Convert",
    summary="Extract the rectangular region of an image enclosed by a bbox2d.",
    description=(
        "The bbox is clamped to the image bounds and the resulting "
        "sub-image is re-encoded as a JPEG data URL. Useful for feeding "
        "single-instance crops into classifiers / embedding models."
    ),
    icon="crop",
    tags=["convert", "image", "bbox2d", "crop"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_image(), required=True),
        PortSpec(name="bbox", type=t_bbox2d(), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_image()),
        PortSpec(name="width", type=t_int()),
        PortSpec(name="height", type=t_int()),
    ],
    cache_policy="auto",
    metadata=_convert_meta(convert_from="image", convert_to="image", cost=2),
)


@register_node(CROP_IMAGE_SPEC)
class ConvertBboxCropImageNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_cv2()
        bbox = inputs.get("bbox")
        if not isinstance(bbox, dict):
            raise NodeInputError("bbox must be a bbox2d record", port="bbox")
        bgr = decode_image_to_numpy(_image_data_url(inputs.get("image")))
        h, w = bgr.shape[:2]
        x1 = int(max(0, min(round(float(bbox["x1"])), w - 1)))
        y1 = int(max(0, min(round(float(bbox["y1"])), h - 1)))
        x2 = int(max(x1 + 1, min(round(float(bbox["x2"])), w)))
        y2 = int(max(y1 + 1, min(round(float(bbox["y2"])), h)))
        crop = bgr[y1:y2, x1:x2]
        if crop.size == 0:
            raise NodeInputError(
                f"crop is empty after clamping: bbox=({x1},{y1},{x2},{y2}) image={w}x{h}",
                port="bbox",
            )
        encoded = encode_numpy_to_image(crop, fmt="jpeg", quality=90)
        ch, cw = crop.shape[:2]
        ctx.log(f"convert.bbox.crop_image: {cw}x{ch} from {w}x{h} bbox=({x1},{y1},{x2},{y2})")
        return {
            "control_out": None,
            "image": {
                "_type": "Image",
                "width": int(cw),
                "height": int(ch),
                "format": "jpeg",
                "data_b64": encoded,
            },
            "width": int(cw),
            "height": int(ch),
        }


# =============================================================================
# Detection list helpers
# =============================================================================


def _iou_xyxy(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    x1 = max(float(a["x1"]), float(b["x1"]))
    y1 = max(float(a["y1"]), float(b["y1"]))
    x2 = min(float(a["x2"]), float(b["x2"]))
    y2 = min(float(a["y2"]), float(b["y2"]))
    iw = max(0.0, x2 - x1)
    ih = max(0.0, y2 - y1)
    inter = iw * ih
    aw = max(0.0, float(a["x2"]) - float(a["x1"])) * max(0.0, float(a["y2"]) - float(a["y1"]))
    bw = max(0.0, float(b["x2"]) - float(b["x1"])) * max(0.0, float(b["y2"]) - float(b["y1"]))
    union = aw + bw - inter
    if union <= 0.0:
        return 0.0
    return inter / union


MERGE_DETECTIONS_SPEC = NodeSpec(
    type="convert.detections.merge",
    version="1.0.0",
    display_name="Merge Detections2D",
    category="Convert",
    summary="Concatenate two Detections2D records, deduplicating by IoU.",
    description=(
        "Walks the second list and appends each box only if its IoU "
        "against every box already kept is below ``iou_threshold``. The "
        "more confident of two duplicates wins. Image dimensions and "
        "image preview are taken from the first input."
    ),
    icon="merge",
    tags=["convert", "detections2d", "merge"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="detections_a", type=t_detections2d(), required=True),
        PortSpec(name="detections_b", type=t_detections2d(), required=True),
        PortSpec(
            name="iou_threshold",
            type=t_float(),
            required=False,
            default=0.5,
            constraints={"min": 0.0, "max": 1.0},
        ),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d()),
        PortSpec(name="count", type=t_int()),
    ],
    cache_policy="auto",
    metadata=_convert_meta(convert_from="detections2d", convert_to="detections2d", cost=2),
)


@register_node(MERGE_DETECTIONS_SPEC)
class ConvertDetectionsMergeNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        a = inputs.get("detections_a")
        b = inputs.get("detections_b")
        if not isinstance(a, dict) or not isinstance(b, dict):
            raise NodeInputError(
                "both detection inputs must be Detections2D records",
                port="detections_a" if not isinstance(a, dict) else "detections_b",
            )
        threshold = float(inputs.get("iou_threshold") or 0.5)
        merged: List[Dict[str, Any]] = []
        for box in list(a.get("boxes") or []):
            if not isinstance(box, dict):
                continue
            merged.append(dict(box))
        for box in list(b.get("boxes") or []):
            if not isinstance(box, dict):
                continue
            duplicate_idx = -1
            for i, existing in enumerate(merged):
                if _iou_xyxy(existing, box) >= threshold:
                    duplicate_idx = i
                    break
            if duplicate_idx == -1:
                merged.append(dict(box))
                continue
            existing = merged[duplicate_idx]
            if float(box.get("confidence", 0.0)) > float(existing.get("confidence", 0.0)):
                merged[duplicate_idx] = dict(box)

        out = dict(a)
        out["boxes"] = merged
        ctx.log(
            f"convert.detections.merge: {len(a.get('boxes') or [])} + "
            f"{len(b.get('boxes') or [])} -> {len(merged)} (iou>={threshold})"
        )
        return {"control_out": None, "detections": out, "count": len(merged)}


# =============================================================================
# Point cloud converters
# =============================================================================


DEPTH_TO_POINTCLOUD_SPEC = NodeSpec(
    type="convert.depth.to_pointcloud",
    version="1.0.0",
    display_name="Depth → Point cloud",
    category="Convert",
    summary="Project a depth map into a 3-D point cloud given camera intrinsics.",
    description=(
        "Reads the depth float32 buffer from a DepthMap record and "
        "projects each pixel into the camera frame using the supplied "
        "fx, fy, cx, cy intrinsics. Points whose depth lies outside "
        "[min_depth, max_depth] are dropped."
    ),
    icon="cloud",
    tags=["convert", "depthmap", "pointcloud"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="depth", type=t_depthmap(), required=True),
        PortSpec(name="fx", type=t_float(), required=False, default=525.0,
                 constraints={"min": 1e-3}),
        PortSpec(name="fy", type=t_float(), required=False, default=525.0,
                 constraints={"min": 1e-3}),
        PortSpec(name="cx", type=t_float(), required=False, default=-1.0,
                 description="Principal point x. Negative => use width / 2."),
        PortSpec(name="cy", type=t_float(), required=False, default=-1.0,
                 description="Principal point y. Negative => use height / 2."),
        PortSpec(name="min_depth", type=t_float(), required=False, default=0.01,
                 constraints={"min": 0.0}),
        PortSpec(name="max_depth", type=t_float(), required=False, default=100.0,
                 constraints={"min": 0.0}),
        PortSpec(name="step", type=t_int(), required=False, default=1,
                 description="Pixel stride; >1 thins the cloud uniformly.",
                 constraints={"min": 1, "max": 16}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="point_cloud", type=t_pointcloud()),
        PortSpec(name="num_points", type=t_int()),
    ],
    cache_policy="auto",
    metadata=_convert_meta(convert_from="depthmap", convert_to="pointcloud", cost=5),
)


@register_node(DEPTH_TO_POINTCLOUD_SPEC)
class ConvertDepthToPointCloudNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        depth = inputs.get("depth")
        if not isinstance(depth, dict):
            raise NodeInputError("depth must be a DepthMap record", port="depth")
        width = int(depth.get("width") or 0)
        height = int(depth.get("height") or 0)
        b64 = depth.get("depth_b64") or ""
        if not (width and height and b64):
            raise NodeInputError("DepthMap missing width/height/depth_b64", port="depth")

        fx = float(inputs.get("fx") or 525.0)
        fy = float(inputs.get("fy") or 525.0)
        cx = float(inputs.get("cx") if inputs.get("cx") is not None else -1.0)
        cy = float(inputs.get("cy") if inputs.get("cy") is not None else -1.0)
        if cx < 0:
            cx = width / 2.0
        if cy < 0:
            cy = height / 2.0
        min_d = float(inputs.get("min_depth") or 0.01)
        max_d = float(inputs.get("max_depth") or 100.0)
        step = max(1, int(inputs.get("step") or 1))

        raw = base64.b64decode(b64)
        depth_arr = np.frombuffer(raw, dtype=np.float32).reshape(height, width)
        ys, xs = np.meshgrid(
            np.arange(0, height, step, dtype=np.int32),
            np.arange(0, width, step, dtype=np.int32),
            indexing="ij",
        )
        d = depth_arr[ys, xs].astype(np.float32)
        mask = (d > min_d) & (d < max_d) & np.isfinite(d)
        xs = xs[mask].astype(np.float32)
        ys = ys[mask].astype(np.float32)
        d = d[mask]

        x_world = (xs - cx) * d / fx
        y_world = (ys - cy) * d / fy
        z_world = d
        pts = np.stack([x_world, y_world, z_world], axis=1).astype(np.float32)

        positions_b64 = base64.b64encode(pts.tobytes()).decode("ascii")
        record = {
            "_type": "PointCloud",
            "num_points": int(pts.shape[0]),
            "positions_b64": positions_b64,
            "fields_b64": None,
            "frame": "camera",
        }
        ctx.log(f"convert.depth.to_pointcloud: {pts.shape[0]} points")
        return {
            "control_out": None,
            "point_cloud": record,
            "num_points": int(pts.shape[0]),
        }


SUBSAMPLE_SPEC = NodeSpec(
    type="convert.pointcloud.subsample",
    version="1.0.0",
    display_name="Subsample point cloud",
    category="Convert",
    summary="Down-sample a point cloud to at most ``max_points``.",
    description=(
        "Two strategies: ``random`` selects ``max_points`` indices "
        "uniformly at random; ``voxel`` partitions space into "
        "axis-aligned cells of side ``voxel_size`` and keeps one "
        "representative per occupied cell."
    ),
    icon="filter",
    tags=["convert", "pointcloud", "subsample"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="point_cloud", type=t_pointcloud(), required=True),
        PortSpec(name="strategy", type=t_string(), required=False, default="random",
                 constraints={"enum": ["random", "voxel"]}),
        PortSpec(name="max_points", type=t_int(), required=False, default=50000,
                 constraints={"min": 1}),
        PortSpec(name="voxel_size", type=t_float(), required=False, default=0.05,
                 description="Voxel side length, metres (only for voxel strategy).",
                 constraints={"min": 1e-4}),
        PortSpec(name="seed", type=t_int(), required=False, default=0),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="point_cloud", type=t_pointcloud()),
        PortSpec(name="num_points", type=t_int()),
    ],
    cache_policy="auto",
    metadata=_convert_meta(convert_from="pointcloud", convert_to="pointcloud", cost=3),
)


def _decode_pointcloud_positions(record: Dict[str, Any]) -> np.ndarray:
    if record.get("positions_b64"):
        raw = base64.b64decode(record["positions_b64"])
        return np.frombuffer(raw, dtype=np.float32).reshape(-1, 3)
    if record.get("positions") is not None:
        arr = np.asarray(record["positions"], dtype=np.float32)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 3)
        return arr
    raise NodeInputError("PointCloud has neither positions_b64 nor positions", port="point_cloud")


@register_node(SUBSAMPLE_SPEC)
class ConvertPointCloudSubsampleNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        record = inputs.get("point_cloud")
        if not isinstance(record, dict):
            raise NodeInputError("point_cloud must be a PointCloud record", port="point_cloud")
        pts = _decode_pointcloud_positions(record)
        strategy = (inputs.get("strategy") or "random").lower()
        max_points = max(1, int(inputs.get("max_points") or 50000))
        seed = int(inputs.get("seed") or 0)
        rng = np.random.default_rng(seed)

        n_in = pts.shape[0]
        if strategy == "voxel":
            voxel = float(inputs.get("voxel_size") or 0.05)
            keys = np.floor(pts / max(voxel, 1e-6)).astype(np.int64)
            # Keep first index per voxel cell.
            _, unique_idx = np.unique(keys, axis=0, return_index=True)
            unique_idx.sort()
            kept = pts[unique_idx]
            if kept.shape[0] > max_points:
                idx = rng.choice(kept.shape[0], max_points, replace=False)
                idx.sort()
                kept = kept[idx]
        else:
            if n_in <= max_points:
                kept = pts
            else:
                idx = rng.choice(n_in, max_points, replace=False)
                idx.sort()
                kept = pts[idx]

        positions_b64 = base64.b64encode(kept.astype(np.float32).tobytes()).decode("ascii")
        out = dict(record)
        out["num_points"] = int(kept.shape[0])
        out["positions_b64"] = positions_b64
        out["positions"] = None
        ctx.log(f"convert.pointcloud.subsample[{strategy}]: {n_in} -> {kept.shape[0]}")
        return {
            "control_out": None,
            "point_cloud": out,
            "num_points": int(kept.shape[0]),
        }


CROP_BOX_SPEC = NodeSpec(
    type="convert.pointcloud.crop_box",
    version="1.0.0",
    display_name="Crop point cloud to bbox3d",
    category="Convert",
    summary="Keep only points inside an axis-aligned 3-D bounding box.",
    description=(
        "Filters the point set by membership in the cuboid defined by "
        "``bbox.center`` ± ``bbox.size`` / 2. Box rotation is ignored "
        "(treated as axis-aligned); rotation-aware cropping is a "
        "Phase-N+1 enhancement."
    ),
    icon="cube",
    tags=["convert", "pointcloud", "bbox3d", "crop"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="point_cloud", type=t_pointcloud(), required=True),
        PortSpec(name="bbox", type=t_bbox3d(), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="point_cloud", type=t_pointcloud()),
        PortSpec(name="num_points", type=t_int()),
    ],
    cache_policy="auto",
    metadata=_convert_meta(convert_from="pointcloud", convert_to="pointcloud", cost=2),
)


@register_node(CROP_BOX_SPEC)
class ConvertPointCloudCropBoxNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        record = inputs.get("point_cloud")
        if not isinstance(record, dict):
            raise NodeInputError("point_cloud must be a PointCloud record", port="point_cloud")
        bbox = inputs.get("bbox")
        if not isinstance(bbox, dict):
            raise NodeInputError("bbox must be a bbox3d record", port="bbox")
        center = list(bbox.get("center") or [0.0, 0.0, 0.0])
        size = list(bbox.get("size") or [0.0, 0.0, 0.0])
        if len(center) < 3 or len(size) < 3:
            raise NodeInputError("bbox center and size must each have 3 entries", port="bbox")

        pts = _decode_pointcloud_positions(record)
        cx, cy, cz = float(center[0]), float(center[1]), float(center[2])
        sx, sy, sz = float(size[0]) / 2.0, float(size[1]) / 2.0, float(size[2]) / 2.0
        mask = (
            (np.abs(pts[:, 0] - cx) <= sx)
            & (np.abs(pts[:, 1] - cy) <= sy)
            & (np.abs(pts[:, 2] - cz) <= sz)
        )
        kept = pts[mask]
        positions_b64 = base64.b64encode(kept.astype(np.float32).tobytes()).decode("ascii")
        out = dict(record)
        out["num_points"] = int(kept.shape[0])
        out["positions_b64"] = positions_b64
        out["positions"] = None
        ctx.log(
            f"convert.pointcloud.crop_box: {pts.shape[0]} -> {kept.shape[0]} inside "
            f"({cx:.3f},{cy:.3f},{cz:.3f}) ± ({sx:.3f},{sy:.3f},{sz:.3f})"
        )
        return {
            "control_out": None,
            "point_cloud": out,
            "num_points": int(kept.shape[0]),
        }


# =============================================================================
# List & record helpers
# =============================================================================


LIST_FIRST_SPEC = NodeSpec(
    type="convert.list.to_first",
    version="1.0.0",
    display_name="List → First",
    category="Convert",
    summary="Return the first element of a list.",
    description="Errors if the list is empty.",
    icon="arrow-right",
    tags=["convert", "list"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="items", type=t_list(t_any()), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any()),
    ],
    cache_policy="auto",
    metadata=_convert_meta(convert_from="list", convert_to="any", cost=1),
)


@register_node(LIST_FIRST_SPEC)
class ConvertListToFirstNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        items = inputs.get("items")
        if items is None:
            raise NodeInputError("items is required", port="items")
        try:
            seq = list(items)
        except TypeError as exc:
            raise NodeInputError(f"items must be iterable: {exc}", port="items") from exc
        if not seq:
            raise NodeInputError("items is empty; cannot take first element", port="items")
        return {"control_out": None, "value": seq[0]}


LIST_LENGTH_SPEC = NodeSpec(
    type="convert.list.length",
    version="1.0.0",
    display_name="List length",
    category="Convert",
    summary="Return ``len(list)``.",
    description="Equivalent to Python's ``len()`` on a list.",
    icon="hash",
    tags=["convert", "list"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="items", type=t_list(t_any()), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="length", type=t_int()),
    ],
    cache_policy="auto",
    metadata=_convert_meta(convert_from="list", convert_to="int", cost=1),
)


@register_node(LIST_LENGTH_SPEC)
class ConvertListLengthNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        items = inputs.get("items")
        if items is None:
            return {"control_out": None, "length": 0}
        try:
            return {"control_out": None, "length": int(len(items))}
        except TypeError as exc:
            raise NodeInputError(f"items has no length: {exc}", port="items") from exc


RECORD_GET_SPEC = NodeSpec(
    type="convert.record.get",
    version="1.0.0",
    display_name="Record field",
    category="Convert",
    summary="Read one field from a record / dict by key.",
    description=(
        "Returns ``record[key]`` or the supplied default if absent. The "
        "output is typed as ``any`` because the value's kind depends on "
        "the record schema."
    ),
    icon="key",
    tags=["convert", "record"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="record", type=t_record({}), required=True),
        PortSpec(name="key", type=t_string(), required=True),
        PortSpec(name="default", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any()),
        PortSpec(name="present", type=t_boolean()),
    ],
    cache_policy="auto",
    metadata=_convert_meta(convert_from="record", convert_to="any", cost=1),
)


@register_node(RECORD_GET_SPEC)
class ConvertRecordGetNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        rec = inputs.get("record")
        key = str(inputs.get("key") or "")
        if not key:
            raise NodeInputError("key is required", port="key")
        default = inputs.get("default")
        if not isinstance(rec, dict):
            return {"control_out": None, "value": default, "present": False}
        present = key in rec
        return {
            "control_out": None,
            "value": rec.get(key, default),
            "present": bool(present),
        }


# =============================================================================
# Scalar converters
# =============================================================================


FLOAT_TO_INT_SPEC = NodeSpec(
    type="convert.scalar.float_to_int",
    version="1.0.0",
    display_name="Float → Int",
    category="Convert",
    summary="Cast a float to an int with a chosen rounding mode.",
    description=(
        "Modes: ``truncate`` drops the fractional part (Python int()), "
        "``round`` uses banker's rounding (round-half-to-even), ``floor`` "
        "rounds toward −∞, and ``ceil`` rounds toward +∞."
    ),
    icon="hash",
    tags=["convert", "scalar"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_float(), required=True),
        PortSpec(name="mode", type=t_string(), required=False, default="truncate",
                 constraints={"enum": ["truncate", "round", "floor", "ceil"]}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_int()),
    ],
    cache_policy="auto",
    metadata=_convert_meta(convert_from="float", convert_to="int", cost=1),
)


@register_node(FLOAT_TO_INT_SPEC)
class ConvertFloatToIntNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        try:
            value = float(inputs.get("value") if inputs.get("value") is not None else 0.0)
        except (TypeError, ValueError) as exc:
            raise NodeInputError(f"value must be numeric: {exc}", port="value") from exc
        mode = (inputs.get("mode") or "truncate").lower()
        if mode == "round":
            out = int(round(value))
        elif mode == "floor":
            import math
            out = int(math.floor(value))
        elif mode == "ceil":
            import math
            out = int(math.ceil(value))
        else:
            out = int(value)
        return {"control_out": None, "value": int(out)}


INT_TO_STRING_SPEC = NodeSpec(
    type="convert.scalar.int_to_string",
    version="1.0.0",
    display_name="Int → String",
    category="Convert",
    summary="Render an integer as text.",
    description="Optional zero-padding via the ``pad_width`` parameter.",
    icon="type",
    tags=["convert", "scalar"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_int(), required=True),
        PortSpec(name="pad_width", type=t_int(), required=False, default=0,
                 constraints={"min": 0, "max": 64}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_string()),
    ],
    cache_policy="auto",
    metadata=_convert_meta(convert_from="int", convert_to="string", cost=1),
)


@register_node(INT_TO_STRING_SPEC)
class ConvertIntToStringNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        try:
            value = int(inputs.get("value") if inputs.get("value") is not None else 0)
        except (TypeError, ValueError) as exc:
            raise NodeInputError(f"value must be int-coercible: {exc}", port="value") from exc
        pad = max(0, int(inputs.get("pad_width") or 0))
        text = str(value)
        if pad and len(text.lstrip("-")) < pad:
            sign = "-" if value < 0 else ""
            text = sign + text.lstrip("-").zfill(pad)
        return {"control_out": None, "value": text}


FLOAT_TO_STRING_SPEC = NodeSpec(
    type="convert.scalar.float_to_string",
    version="1.0.0",
    display_name="Float → String",
    category="Convert",
    summary="Render a float as text with configurable precision.",
    description=(
        "``precision`` picks the number of digits after the decimal "
        "point; ``style`` switches between fixed-point and exponential."
    ),
    icon="type",
    tags=["convert", "scalar"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_float(), required=True),
        PortSpec(name="precision", type=t_int(), required=False, default=3,
                 constraints={"min": 0, "max": 16}),
        PortSpec(name="style", type=t_string(), required=False, default="fixed",
                 constraints={"enum": ["fixed", "exponential"]}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_string()),
    ],
    cache_policy="auto",
    metadata=_convert_meta(convert_from="float", convert_to="string", cost=1),
)


@register_node(FLOAT_TO_STRING_SPEC)
class ConvertFloatToStringNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        try:
            value = float(inputs.get("value") if inputs.get("value") is not None else 0.0)
        except (TypeError, ValueError) as exc:
            raise NodeInputError(f"value must be numeric: {exc}", port="value") from exc
        precision = int(inputs.get("precision") or 0)
        style = (inputs.get("style") or "fixed").lower()
        if style == "exponential":
            text = f"{value:.{precision}e}"
        else:
            text = f"{value:.{precision}f}"
        return {"control_out": None, "value": text}


# =============================================================================
# Supervision <-> Detections2D marshalling (Phase 5 t_any() retirement)
# =============================================================================
#
# `backend/app/nodes/sv_*` carries a supervision.Detections handle on
# t_any() ports because the live ndarray-backed object is not the same
# kind as the canonical t_detections2d() record. Phase 5 ships explicit
# marshallers so a graph that mixes the two can declare a real type at
# every edge.

SV_DETECTIONS_TO_RECORD_SPEC = NodeSpec(
    type="convert.sv.detections_to_detections2d",
    version="1.0.0",
    display_name="sv.Detections → Detections2D",
    category="Convert",
    summary="Marshal a supervision.Detections handle into a Detections2D record.",
    description=(
        "Turns the in-process supervision handle (xyxy / confidence / "
        "class_id ndarrays) into the canonical, JSON-serialisable "
        "Detections2D record so it can flow over WebSocket and into "
        "any record-shaped consumer (trackers, filters, visualisers)."
    ),
    icon="package",
    tags=["convert", "supervision", "detections2d"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        # The source side is genuinely polymorphic — it's an in-process
        # supervision.Detections handle. We accept t_any() here and make
        # the kind explicit on the output side.
        PortSpec(name="detections", type=t_any(), required=True),
        PortSpec(name="image_width", type=t_int(), required=False, default=0),
        PortSpec(name="image_height", type=t_int(), required=False, default=0),
        PortSpec(name="class_names", type=t_string(), required=False, default=""),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d()),
        PortSpec(name="count", type=t_int()),
    ],
    cache_policy="auto",
    metadata=_convert_meta(convert_from="any", convert_to="detections2d", cost=2),
)


@register_node(SV_DETECTIONS_TO_RECORD_SPEC)
class ConvertSvDetectionsToRecordNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        try:
            import supervision as sv  # type: ignore
        except ImportError as exc:  # pragma: no cover - import guard
            raise NodeMissingDependencyError(
                "supervision not installed (pip install supervision)"
            ) from exc

        det = inputs.get("detections")
        if det is None:
            raise NodeInputError("detections is required", port="detections")
        if not isinstance(det, sv.Detections):
            raise NodeInputError(
                "expected a supervision.Detections handle",
                port="detections",
                details={"got": type(det).__name__},
            )

        names_raw = str(inputs.get("class_names") or "")
        name_list = [n.strip() for n in names_raw.split(",") if n.strip()]

        boxes: List[Dict[str, Any]] = []
        if len(det) > 0:
            xyxy = np.asarray(det.xyxy)
            confidence = (
                np.asarray(det.confidence)
                if det.confidence is not None
                else np.zeros(len(det), dtype=np.float32)
            )
            class_id = (
                np.asarray(det.class_id)
                if det.class_id is not None
                else np.zeros(len(det), dtype=int)
            )
            for i in range(len(det)):
                cid = int(class_id[i])
                cname = name_list[cid] if 0 <= cid < len(name_list) else f"class_{cid}"
                boxes.append(make_bbox2d(
                    x1=float(xyxy[i, 0]), y1=float(xyxy[i, 1]),
                    x2=float(xyxy[i, 2]), y2=float(xyxy[i, 3]),
                    confidence=float(confidence[i]),
                    class_id=cid,
                    class_name=cname,
                ))

        width = int(inputs.get("image_width") or 0)
        height = int(inputs.get("image_height") or 0)
        record = make_detections2d(boxes, width, height)
        ctx.log(f"convert.sv.detections_to_detections2d: {len(boxes)} boxes")
        return {"control_out": None, "detections": record, "count": len(boxes)}


RECORD_TO_SV_DETECTIONS_SPEC = NodeSpec(
    type="convert.sv.detections2d_to_detections",
    version="1.0.0",
    display_name="Detections2D → sv.Detections",
    category="Convert",
    summary="Marshal a Detections2D record into a supervision.Detections handle.",
    description=(
        "Inverse of ``convert.sv.detections_to_detections2d``: builds an "
        "in-process supervision.Detections from xyxy / confidence / "
        "class_id columns so the result can be fed into supervision "
        "annotators."
    ),
    icon="package",
    tags=["convert", "supervision", "detections2d"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d(), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_any()),
        PortSpec(name="count", type=t_int()),
    ],
    cache_policy="auto",
    metadata=_convert_meta(convert_from="detections2d", convert_to="any", cost=2),
)


@register_node(RECORD_TO_SV_DETECTIONS_SPEC)
class ConvertRecordToSvDetectionsNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        try:
            import supervision as sv  # type: ignore
        except ImportError as exc:  # pragma: no cover - import guard
            raise NodeMissingDependencyError(
                "supervision not installed (pip install supervision)"
            ) from exc

        record = inputs.get("detections")
        if not isinstance(record, dict):
            raise NodeInputError("detections must be a Detections2D record", port="detections")
        boxes = list(record.get("boxes") or [])
        if not boxes:
            handle = sv.Detections.empty()
            return {"control_out": None, "detections": handle, "count": 0}
        xyxy = np.array(
            [[float(b["x1"]), float(b["y1"]), float(b["x2"]), float(b["y2"])] for b in boxes],
            dtype=np.float32,
        )
        confidence = np.array(
            [float(b.get("confidence", 1.0)) for b in boxes], dtype=np.float32
        )
        class_id = np.array(
            [int(b.get("class_id", 0)) for b in boxes], dtype=int
        )
        handle = sv.Detections(xyxy=xyxy, confidence=confidence, class_id=class_id)
        ctx.log(f"convert.sv.detections2d_to_detections: {len(boxes)} boxes")
        return {"control_out": None, "detections": handle, "count": len(boxes)}


# =============================================================================
# Plugin entry point
# =============================================================================


def register() -> None:
    """STRIDE plugin entry point — nodes auto-register on import."""
    return None
