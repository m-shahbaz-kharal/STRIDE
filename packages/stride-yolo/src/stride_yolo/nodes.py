"""
YOLO detection / segmentation / pose nodes.

All three nodes share the same input/output convention:

  inputs:
    image       — base64 image string (data URL or raw)
    weights     — model weights path or pretrained name (auto-downloaded)
    confidence  — detection confidence threshold
    iou         — NMS IoU threshold
    image_size  — inference image size (default 640)
    device      — "cpu", "cuda", "mps", or "" (auto)
    annotate    — when True, also produce an annotated image output

  outputs:
    detections  — t_detections2d record (image_width/height, boxes, image)
    boxes       — convenience list of bbox2d
    count       — len(boxes)
    image       — annotated visualization (only filled when annotate=True)
"""

from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional

try:
    import numpy as np  # type: ignore
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None  # type: ignore

try:
    import cv2  # type: ignore
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    cv2 = None  # type: ignore

try:
    from ultralytics import YOLO  # type: ignore
    HAS_ULTRA = True
except ImportError:
    HAS_ULTRA = False
    YOLO = None  # type: ignore

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_any, t_boolean, t_control, t_float, t_int, t_list, t_record, t_string,
    t_image, t_bbox2d, t_detections2d, t_keypoints,
)
from stride_core.image_utils import (
    decode_image_to_numpy,
    encode_numpy_to_image,
    make_bbox2d,
    make_detections2d,
)


# Module-level model cache so we don't reload the same .pt for every frame.
_MODEL_CACHE: Dict[str, Any] = {}


def _require_deps() -> None:
    if not HAS_NUMPY:
        raise RuntimeError("numpy not installed (pip install numpy)")
    if not HAS_CV2:
        raise RuntimeError("opencv-python not installed (pip install opencv-python)")
    if not HAS_ULTRA:
        raise RuntimeError("ultralytics not installed (pip install ultralytics)")


def _load_model(weights: str, device: str) -> Any:
    """Load (or fetch from cache) a YOLO model for the given weights file."""
    cache_key = f"{weights}|{device}"
    model = _MODEL_CACHE.get(cache_key)
    if model is None:
        model = YOLO(weights)
        if device:
            try:
                model.to(device)
            except Exception:
                pass
        _MODEL_CACHE[cache_key] = model
    return model


def _coerce_int(value: Any, fallback: int) -> int:
    try:
        if value is None:
            return fallback
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _coerce_float(value: Any, fallback: float) -> float:
    try:
        if value is None:
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


# =============================================================================
# Detection
# =============================================================================

YOLO_DETECT_SPEC = NodeSpec(
    type="image.detect.yolo",
    version="1.0.0",
    display_name="YOLO Detect",
    category="Image / Detection",
    summary="2D object detection with YOLOv8 / YOLO11 (Ultralytics).",
    description=(
        "Runs an Ultralytics YOLO detector over an input image and emits a "
        "Detections2D record with bounding boxes, class labels, and "
        "confidence scores."
    ),
    icon="crosshair",
    tags=["yolo", "ultralytics", "detection", "image"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_image(), required=True, description="Input image (base64)"),
        PortSpec(name="weights", type=t_string(), required=False, default="yolo11n.pt",
                 description="Pretrained model name (e.g. 'yolo11n.pt', 'yolov8s.pt') or path to .pt file"),
        PortSpec(name="confidence", type=t_float(), required=False, default=0.25,
                 description="Confidence threshold"),
        PortSpec(name="iou", type=t_float(), required=False, default=0.45,
                 description="NMS IoU threshold"),
        PortSpec(name="image_size", type=t_int(), required=False, default=640,
                 description="Inference image size (square)"),
        PortSpec(name="device", type=t_string(), required=False, default="",
                 description="'cpu', 'cuda', 'mps', or '' for auto"),
        PortSpec(name="annotate", type=t_boolean(), required=False, default=True,
                 description="Produce an annotated visualization image"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d()),
        PortSpec(name="boxes", type=t_list(t_bbox2d())),
        PortSpec(name="count", type=t_int()),
        PortSpec(name="image", type=t_image()),
    ],
    cache_policy="disabled",
)


@register_node(YOLO_DETECT_SPEC)
class YoloDetectNode(NodeBase):
    """YOLO 2D object detection."""

    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_deps()

        image_str = inputs.get("image")
        if not image_str:
            raise ValueError("YOLO detect: no image provided")

        weights = inputs.get("weights") or "yolo11n.pt"
        conf = _coerce_float(inputs.get("confidence"), 0.25)
        iou = _coerce_float(inputs.get("iou"), 0.45)
        imgsz = _coerce_int(inputs.get("image_size"), 640)
        device = inputs.get("device") or ""
        annotate = bool(inputs.get("annotate", True))

        ctx.log(f"YOLO detect: weights={weights} conf={conf} iou={iou} imgsz={imgsz}")

        img = decode_image_to_numpy(image_str)
        h, w = img.shape[:2]

        model = _load_model(weights, device)
        results = model.predict(img, conf=conf, iou=iou, imgsz=imgsz, verbose=False)

        names = getattr(model, "names", {}) or {}
        boxes_out: List[Dict[str, Any]] = []
        for r in results:
            if r.boxes is None:
                continue
            xyxy = r.boxes.xyxy.cpu().numpy() if hasattr(r.boxes.xyxy, "cpu") else np.asarray(r.boxes.xyxy)
            confs = r.boxes.conf.cpu().numpy() if hasattr(r.boxes.conf, "cpu") else np.asarray(r.boxes.conf)
            classes = r.boxes.cls.cpu().numpy() if hasattr(r.boxes.cls, "cpu") else np.asarray(r.boxes.cls)
            for box, score, cls_id in zip(xyxy, confs, classes):
                cid = int(cls_id)
                boxes_out.append(
                    make_bbox2d(
                        x1=float(box[0]), y1=float(box[1]),
                        x2=float(box[2]), y2=float(box[3]),
                        confidence=float(score),
                        class_id=cid,
                        class_name=str(names.get(cid, cid)),
                    )
                )

        annotated = ""
        if annotate and results:
            try:
                plotted = results[0].plot()  # BGR ndarray
                annotated = encode_numpy_to_image(plotted, fmt="jpeg", quality=85)
            except Exception as exc:  # pragma: no cover - best-effort
                ctx.log(f"annotate failed: {exc}")

        detections = make_detections2d(boxes_out, w, h, image=annotated or None)
        ctx.log(f"YOLO detect: {len(boxes_out)} boxes")

        return {
            "control_out": None,
            "detections": detections,
            "boxes": boxes_out,
            "count": len(boxes_out),
            "image": annotated,
        }


# =============================================================================
# Instance Segmentation
# =============================================================================

YOLO_SEGMENT_SPEC = NodeSpec(
    type="image.segment.yolo",
    version="1.0.0",
    display_name="YOLO Segment",
    category="Image / Segmentation",
    summary="Instance segmentation with YOLO11-seg / YOLOv8-seg.",
    description=(
        "Runs an Ultralytics YOLO segmentation model and emits both "
        "Detections2D and per-instance binary masks (base64 PNG)."
    ),
    icon="scissors",
    tags=["yolo", "ultralytics", "segmentation", "image"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_image(), required=True),
        PortSpec(name="weights", type=t_string(), required=False, default="yolo11n-seg.pt"),
        PortSpec(name="confidence", type=t_float(), required=False, default=0.25),
        PortSpec(name="iou", type=t_float(), required=False, default=0.45),
        PortSpec(name="image_size", type=t_int(), required=False, default=640),
        PortSpec(name="device", type=t_string(), required=False, default=""),
        PortSpec(name="annotate", type=t_boolean(), required=False, default=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d()),
        PortSpec(name="boxes", type=t_list(t_bbox2d())),
        PortSpec(name="masks", type=t_list(t_string()),
                 description="Per-instance binary masks as base64 PNG"),
        PortSpec(name="count", type=t_int()),
        PortSpec(name="image", type=t_image()),
    ],
    cache_policy="disabled",
)


def _mask_to_png_b64(mask: "np.ndarray") -> str:
    """Encode a HxW {0,1} mask as a base64 PNG."""
    arr = (np.asarray(mask) > 0.5).astype(np.uint8) * 255
    ok, buf = cv2.imencode(".png", arr)
    if not ok:
        return ""
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode("ascii")


@register_node(YOLO_SEGMENT_SPEC)
class YoloSegmentNode(NodeBase):
    """YOLO instance segmentation."""

    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_deps()

        image_str = inputs.get("image")
        if not image_str:
            raise ValueError("YOLO segment: no image provided")

        weights = inputs.get("weights") or "yolo11n-seg.pt"
        conf = _coerce_float(inputs.get("confidence"), 0.25)
        iou = _coerce_float(inputs.get("iou"), 0.45)
        imgsz = _coerce_int(inputs.get("image_size"), 640)
        device = inputs.get("device") or ""
        annotate = bool(inputs.get("annotate", True))

        ctx.log(f"YOLO segment: weights={weights}")

        img = decode_image_to_numpy(image_str)
        h, w = img.shape[:2]

        model = _load_model(weights, device)
        results = model.predict(img, conf=conf, iou=iou, imgsz=imgsz, verbose=False)
        names = getattr(model, "names", {}) or {}

        boxes_out: List[Dict[str, Any]] = []
        masks_out: List[str] = []
        for r in results:
            if r.boxes is None:
                continue
            xyxy = r.boxes.xyxy.cpu().numpy() if hasattr(r.boxes.xyxy, "cpu") else np.asarray(r.boxes.xyxy)
            confs = r.boxes.conf.cpu().numpy() if hasattr(r.boxes.conf, "cpu") else np.asarray(r.boxes.conf)
            classes = r.boxes.cls.cpu().numpy() if hasattr(r.boxes.cls, "cpu") else np.asarray(r.boxes.cls)
            mask_data = None
            if r.masks is not None:
                mask_data = r.masks.data.cpu().numpy() if hasattr(r.masks.data, "cpu") else np.asarray(r.masks.data)
            for i, (box, score, cls_id) in enumerate(zip(xyxy, confs, classes)):
                cid = int(cls_id)
                boxes_out.append(
                    make_bbox2d(
                        x1=float(box[0]), y1=float(box[1]),
                        x2=float(box[2]), y2=float(box[3]),
                        confidence=float(score),
                        class_id=cid,
                        class_name=str(names.get(cid, cid)),
                    )
                )
                if mask_data is not None and i < len(mask_data):
                    # Resize mask to original frame
                    m = mask_data[i]
                    if m.shape != (h, w):
                        m = cv2.resize(m.astype(np.float32), (w, h), interpolation=cv2.INTER_NEAREST)
                    masks_out.append(_mask_to_png_b64(m))
                else:
                    masks_out.append("")

        annotated = ""
        if annotate and results:
            try:
                plotted = results[0].plot()
                annotated = encode_numpy_to_image(plotted, fmt="jpeg", quality=85)
            except Exception as exc:  # pragma: no cover
                ctx.log(f"annotate failed: {exc}")

        detections = make_detections2d(boxes_out, w, h, image=annotated or None)
        ctx.log(f"YOLO segment: {len(boxes_out)} instances")

        return {
            "control_out": None,
            "detections": detections,
            "boxes": boxes_out,
            "masks": masks_out,
            "count": len(boxes_out),
            "image": annotated,
        }


# =============================================================================
# Pose
# =============================================================================

YOLO_POSE_SPEC = NodeSpec(
    type="image.pose.yolo",
    version="1.0.0",
    display_name="YOLO Pose",
    category="Image / Pose",
    summary="Human pose estimation with YOLO-pose.",
    description=(
        "Runs an Ultralytics YOLO pose model (17 COCO keypoints per person) "
        "and emits Detections2D + a Keypoints record."
    ),
    icon="user",
    tags=["yolo", "ultralytics", "pose", "keypoints"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_image(), required=True),
        PortSpec(name="weights", type=t_string(), required=False, default="yolo11n-pose.pt"),
        PortSpec(name="confidence", type=t_float(), required=False, default=0.25),
        PortSpec(name="iou", type=t_float(), required=False, default=0.45),
        PortSpec(name="image_size", type=t_int(), required=False, default=640),
        PortSpec(name="device", type=t_string(), required=False, default=""),
        PortSpec(name="annotate", type=t_boolean(), required=False, default=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d()),
        PortSpec(name="keypoints", type=t_keypoints()),
        PortSpec(name="count", type=t_int()),
        PortSpec(name="image", type=t_image()),
    ],
    cache_policy="disabled",
)


@register_node(YOLO_POSE_SPEC)
class YoloPoseNode(NodeBase):
    """YOLO human pose estimation."""

    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_deps()

        image_str = inputs.get("image")
        if not image_str:
            raise ValueError("YOLO pose: no image provided")

        weights = inputs.get("weights") or "yolo11n-pose.pt"
        conf = _coerce_float(inputs.get("confidence"), 0.25)
        iou = _coerce_float(inputs.get("iou"), 0.45)
        imgsz = _coerce_int(inputs.get("image_size"), 640)
        device = inputs.get("device") or ""
        annotate = bool(inputs.get("annotate", True))

        ctx.log(f"YOLO pose: weights={weights}")

        img = decode_image_to_numpy(image_str)
        h, w = img.shape[:2]

        model = _load_model(weights, device)
        results = model.predict(img, conf=conf, iou=iou, imgsz=imgsz, verbose=False)
        names = getattr(model, "names", {}) or {}

        boxes_out: List[Dict[str, Any]] = []
        instances: List[Dict[str, Any]] = []
        for r in results:
            if r.boxes is None:
                continue
            xyxy = r.boxes.xyxy.cpu().numpy() if hasattr(r.boxes.xyxy, "cpu") else np.asarray(r.boxes.xyxy)
            confs = r.boxes.conf.cpu().numpy() if hasattr(r.boxes.conf, "cpu") else np.asarray(r.boxes.conf)
            classes = r.boxes.cls.cpu().numpy() if hasattr(r.boxes.cls, "cpu") else np.asarray(r.boxes.cls)
            kp_data = None
            if r.keypoints is not None and r.keypoints.data is not None:
                kp_data = r.keypoints.data.cpu().numpy() if hasattr(r.keypoints.data, "cpu") else np.asarray(r.keypoints.data)

            for i, (box, score, cls_id) in enumerate(zip(xyxy, confs, classes)):
                cid = int(cls_id)
                bbox = make_bbox2d(
                    x1=float(box[0]), y1=float(box[1]),
                    x2=float(box[2]), y2=float(box[3]),
                    confidence=float(score),
                    class_id=cid,
                    class_name=str(names.get(cid, "person")),
                )
                boxes_out.append(bbox)

                kps_list = []
                if kp_data is not None and i < len(kp_data):
                    for kp in kp_data[i]:
                        if len(kp) >= 3:
                            kps_list.append([float(kp[0]), float(kp[1]), float(kp[2])])
                        else:
                            kps_list.append([float(kp[0]), float(kp[1]), 1.0])
                instances.append({
                    "bbox": bbox,
                    "keypoints": kps_list,
                })

        annotated = ""
        if annotate and results:
            try:
                plotted = results[0].plot()
                annotated = encode_numpy_to_image(plotted, fmt="jpeg", quality=85)
            except Exception as exc:  # pragma: no cover
                ctx.log(f"annotate failed: {exc}")

        detections = make_detections2d(boxes_out, w, h, image=annotated or None)
        keypoints = {
            "_type": "Keypoints",
            "schema": "coco17",
            "instances": instances,
        }
        ctx.log(f"YOLO pose: {len(boxes_out)} people")

        return {
            "control_out": None,
            "detections": detections,
            "keypoints": keypoints,
            "count": len(boxes_out),
            "image": annotated,
        }


def register() -> None:
    """STRIDE plugin entry point — nodes auto-register on import."""
    pass
