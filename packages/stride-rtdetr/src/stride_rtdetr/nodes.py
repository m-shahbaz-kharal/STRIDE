"""
RT-DETR detection node.

Wraps the RT-DETR implementation that ships with the Ultralytics package
(`from ultralytics import RTDETR`).  Output schema mirrors `stride-yolo`
so RT-DETR detections can be fed into the same downstream nodes
(trackers, visualizers, etc.).
"""

from __future__ import annotations

from typing import Any, Dict, List

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
    from ultralytics import RTDETR  # type: ignore
    HAS_ULTRA = True
except ImportError:
    HAS_ULTRA = False
    RTDETR = None  # type: ignore

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_boolean, t_control, t_float, t_int, t_list, t_string,
    t_image, t_bbox2d, t_detections2d,
)
from stride_core.image_utils import (
    decode_image_to_numpy, encode_numpy_to_image, make_bbox2d, make_detections2d,
)


_MODEL_CACHE: Dict[str, Any] = {}


def _require_deps() -> None:
    if not HAS_NUMPY:
        raise RuntimeError("numpy not installed")
    if not HAS_CV2:
        raise RuntimeError("opencv-python not installed")
    if not HAS_ULTRA:
        raise RuntimeError(
            "ultralytics not installed (pip install ultralytics) — "
            "RTDETR is shipped as part of the ultralytics package."
        )


def _load_model(weights: str, device: str) -> Any:
    key = f"{weights}|{device}"
    model = _MODEL_CACHE.get(key)
    if model is None:
        model = RTDETR(weights)
        if device:
            try:
                model.to(device)
            except Exception:
                pass
        _MODEL_CACHE[key] = model
    return model


RTDETR_DETECT_SPEC = NodeSpec(
    type="image.detect.rtdetr",
    version="1.0.0",
    display_name="RT-DETR Detect",
    category="Image / Detection",
    summary="Real-time transformer object detection (RT-DETR).",
    description=(
        "Runs RT-DETR (Baidu PaddlePaddle, ported in the Ultralytics "
        "package) on a single image and emits Detections2D."
    ),
    icon="zap",
    tags=["rt-detr", "transformer", "detection", "ultralytics"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_image(), required=True),
        PortSpec(name="weights", type=t_string(), required=False, default="rtdetr-l.pt",
                 description="'rtdetr-l.pt' or 'rtdetr-x.pt', or a path to a .pt file"),
        PortSpec(name="confidence", type=t_float(), required=False, default=0.25),
        PortSpec(name="image_size", type=t_int(), required=False, default=640),
        PortSpec(name="device", type=t_string(), required=False, default=""),
        PortSpec(name="annotate", type=t_boolean(), required=False, default=True),
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


@register_node(RTDETR_DETECT_SPEC)
class RTDETRDetectNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_deps()
        image_str = inputs.get("image")
        if not image_str:
            raise ValueError("RT-DETR: no image provided")

        weights = inputs.get("weights") or "rtdetr-l.pt"
        try:
            conf = float(inputs.get("confidence") if inputs.get("confidence") is not None else 0.25)
        except (TypeError, ValueError):
            conf = 0.25
        try:
            imgsz = int(inputs.get("image_size") if inputs.get("image_size") is not None else 640)
        except (TypeError, ValueError):
            imgsz = 640
        device = inputs.get("device") or ""
        annotate = bool(inputs.get("annotate", True))

        ctx.log(f"RT-DETR: weights={weights} conf={conf} imgsz={imgsz}")

        img = decode_image_to_numpy(image_str)
        h, w = img.shape[:2]

        model = _load_model(weights, device)
        results = model.predict(img, conf=conf, imgsz=imgsz, verbose=False)
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
                boxes_out.append(make_bbox2d(
                    x1=float(box[0]), y1=float(box[1]),
                    x2=float(box[2]), y2=float(box[3]),
                    confidence=float(score),
                    class_id=cid,
                    class_name=str(names.get(cid, cid)),
                ))

        annotated = ""
        if annotate and results:
            try:
                plotted = results[0].plot()
                annotated = encode_numpy_to_image(plotted, fmt="jpeg", quality=85)
            except Exception as exc:  # pragma: no cover
                ctx.log(f"annotate failed: {exc}")

        detections = make_detections2d(boxes_out, w, h, image=annotated or None)
        ctx.log(f"RT-DETR: {len(boxes_out)} boxes")

        return {
            "control_out": None,
            "detections": detections,
            "boxes": boxes_out,
            "count": len(boxes_out),
            "image": annotated,
        }


def register() -> None:
    pass
