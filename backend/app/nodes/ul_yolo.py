"""Ultralytics YOLO nodes for object detection, segmentation, and tracking."""
from __future__ import annotations

from typing import Any, Dict

import numpy as np

from . import register_node
from .base import ExecutionContext, NodeBase
from ..node_spec import NodeSpec, PortSpec
from ..typesystem import t_any, t_control, t_float, t_int, t_string

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None  # type: ignore[assignment,misc]

try:
    import supervision as sv
except ImportError:
    sv = None  # type: ignore[assignment]


def _require_ultralytics():
    if YOLO is None:
        raise ImportError(
            "The 'ultralytics' package is required for this node. "
            "Install it with: pip install ultralytics"
        )


def _require_sv():
    if sv is None:
        raise ImportError(
            "The 'supervision' package is required for this node. "
            "Install it with: pip install supervision"
        )


def _results_to_sv_detections(results) -> "sv.Detections":
    """Convert ultralytics Results to supervision Detections."""
    _require_sv()
    return sv.Detections.from_ultralytics(results[0])


# ============================================================================
# YOLO MODEL LOADER
# ============================================================================

UL_YOLO_LOAD_SPEC = NodeSpec(
    type="ul.yolo.load",
    version="1.0.0",
    display_name="YOLO - Load Model",
    category="Ultralytics",
    summary="Load a YOLO model.",
    description=(
        "Loads an Ultralytics YOLO model by name or path. "
        "Common models: yolo11n.pt, yolo11s.pt, yolo11m.pt, yolo11l.pt, yolo11x.pt "
        "(also yolo11n-seg.pt for segmentation). "
        "The model is cached in the execution context so it is only loaded once per graph run."
    ),
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="model_name", type=t_string(), required=False, default="yolo11n.pt"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="model", type=t_any()),
    ],
)


@register_node(UL_YOLO_LOAD_SPEC)
class UlYoloLoadNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_ultralytics()
        model_name = str(inputs.get("model_name") or "yolo11n.pt")

        cache_key = f"_ul_yolo_model_{model_name}"
        model = ctx.get_var(cache_key)
        if model is None:
            ctx.log(f"Loading YOLO model: {model_name}")
            model = YOLO(model_name)
            ctx.set_var(cache_key, model)
        else:
            ctx.log(f"Using cached YOLO model: {model_name}")

        return {"control_out": None, "model": model}


# ============================================================================
# YOLO DETECT
# ============================================================================

UL_YOLO_DETECT_SPEC = NodeSpec(
    type="ul.yolo.detect",
    version="1.0.0",
    display_name="YOLO - Detect",
    category="Ultralytics",
    summary="Run YOLO object detection.",
    description=(
        "Runs YOLO object detection on a numpy image and returns "
        "supervision Detections. Connect a YOLO model from 'YOLO - Load Model' "
        "and a numpy image from 'SV - Decode Image'."
    ),
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="model", type=t_any(), required=True),
        PortSpec(name="image", type=t_any(), required=True),
        PortSpec(name="confidence", type=t_float(), required=False, default=0.25),
        PortSpec(name="iou_threshold", type=t_float(), required=False, default=0.7),
        PortSpec(name="image_size", type=t_int(), required=False, default=640),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_any()),
        PortSpec(name="class_names", type=t_string()),
    ],
)


@register_node(UL_YOLO_DETECT_SPEC)
class UlYoloDetectNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_ultralytics()
        model = inputs.get("model")
        image = inputs.get("image")
        if model is None:
            raise ValueError("No YOLO model provided")
        if image is None or not isinstance(image, np.ndarray):
            raise ValueError("Input image must be a numpy array")

        conf = float(inputs.get("confidence") or 0.25)
        iou = float(inputs.get("iou_threshold") or 0.7)
        imgsz = int(inputs.get("image_size") or 640)

        results = model(image, conf=conf, iou=iou, imgsz=imgsz, verbose=False)
        detections = _results_to_sv_detections(results)

        # Build comma-separated class names string from model
        names = model.names  # dict {0: 'person', 1: 'bicycle', ...}
        class_names_str = ",".join(names[i] for i in sorted(names.keys()))

        ctx.log(f"YOLO detect: {len(detections)} objects found")
        return {
            "control_out": None,
            "detections": detections,
            "class_names": class_names_str,
        }


# ============================================================================
# YOLO SEGMENT
# ============================================================================

UL_YOLO_SEGMENT_SPEC = NodeSpec(
    type="ul.yolo.segment",
    version="1.0.0",
    display_name="YOLO - Segment",
    category="Ultralytics",
    summary="Run YOLO instance segmentation.",
    description=(
        "Runs YOLO instance segmentation on a numpy image and returns "
        "supervision Detections with masks. Use a segmentation model "
        "(e.g. yolo11n-seg.pt)."
    ),
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="model", type=t_any(), required=True),
        PortSpec(name="image", type=t_any(), required=True),
        PortSpec(name="confidence", type=t_float(), required=False, default=0.25),
        PortSpec(name="iou_threshold", type=t_float(), required=False, default=0.7),
        PortSpec(name="image_size", type=t_int(), required=False, default=640),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_any()),
        PortSpec(name="class_names", type=t_string()),
    ],
)


@register_node(UL_YOLO_SEGMENT_SPEC)
class UlYoloSegmentNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_ultralytics()
        model = inputs.get("model")
        image = inputs.get("image")
        if model is None:
            raise ValueError("No YOLO model provided")
        if image is None or not isinstance(image, np.ndarray):
            raise ValueError("Input image must be a numpy array")

        conf = float(inputs.get("confidence") or 0.25)
        iou = float(inputs.get("iou_threshold") or 0.7)
        imgsz = int(inputs.get("image_size") or 640)

        results = model(image, conf=conf, iou=iou, imgsz=imgsz, verbose=False)
        detections = _results_to_sv_detections(results)

        names = model.names
        class_names_str = ",".join(names[i] for i in sorted(names.keys()))

        ctx.log(f"YOLO segment: {len(detections)} objects found")
        return {
            "control_out": None,
            "detections": detections,
            "class_names": class_names_str,
        }


# ============================================================================
# YOLO CLASSIFY
# ============================================================================

UL_YOLO_CLASSIFY_SPEC = NodeSpec(
    type="ul.yolo.classify",
    version="1.0.0",
    display_name="YOLO - Classify",
    category="Ultralytics",
    summary="Run YOLO image classification.",
    description=(
        "Runs YOLO image classification on a numpy image and returns "
        "the top-K predicted class names and their confidence scores. "
        "Use a classification model (e.g. yolo11n-cls.pt)."
    ),
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="model", type=t_any(), required=True),
        PortSpec(name="image", type=t_any(), required=True),
        PortSpec(name="top_k", type=t_int(), required=False, default=5),
        PortSpec(name="image_size", type=t_int(), required=False, default=640),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="top_class", type=t_string()),
        PortSpec(name="top_confidence", type=t_float()),
        PortSpec(name="summary", type=t_string()),
    ],
)


@register_node(UL_YOLO_CLASSIFY_SPEC)
class UlYoloClassifyNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_ultralytics()
        model = inputs.get("model")
        image = inputs.get("image")
        if model is None:
            raise ValueError("No YOLO model provided")
        if image is None or not isinstance(image, np.ndarray):
            raise ValueError("Input image must be a numpy array")

        top_k = int(inputs.get("top_k") or 5)
        imgsz = int(inputs.get("image_size") or 640)

        results = model(image, imgsz=imgsz, verbose=False)
        probs = results[0].probs

        names = model.names
        top_indices = probs.top5[:top_k]
        top_confs = probs.top5conf[:top_k]

        top_class = names[top_indices[0]]
        top_confidence = float(top_confs[0])

        lines = [f"{names[idx]}: {float(c):.3f}" for idx, c in zip(top_indices, top_confs)]
        summary = " | ".join(lines)

        ctx.log(f"YOLO classify: {top_class} ({top_confidence:.3f})")
        return {
            "control_out": None,
            "top_class": top_class,
            "top_confidence": top_confidence,
            "summary": summary,
        }


# ============================================================================
# YOLO TRACK (built-in ByteTrack / BoT-SORT)
# ============================================================================

UL_YOLO_TRACK_SPEC = NodeSpec(
    type="ul.yolo.track",
    version="1.0.0",
    display_name="YOLO - Track",
    category="Ultralytics",
    summary="Run YOLO detection with built-in tracking.",
    description=(
        "Runs YOLO object detection with built-in object tracking (ByteTrack or BoT-SORT). "
        "Returns supervision Detections with tracker_id assigned. "
        "The tracker state persists across calls within the same graph run."
    ),
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="model", type=t_any(), required=True),
        PortSpec(name="image", type=t_any(), required=True),
        PortSpec(name="confidence", type=t_float(), required=False, default=0.25),
        PortSpec(name="iou_threshold", type=t_float(), required=False, default=0.7),
        PortSpec(name="tracker", type=t_string(), required=False, default="bytetrack.yaml"),
        PortSpec(name="image_size", type=t_int(), required=False, default=640),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_any()),
        PortSpec(name="class_names", type=t_string()),
    ],
    cache_policy="disabled",
)


@register_node(UL_YOLO_TRACK_SPEC)
class UlYoloTrackNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_ultralytics()
        model = inputs.get("model")
        image = inputs.get("image")
        if model is None:
            raise ValueError("No YOLO model provided")
        if image is None or not isinstance(image, np.ndarray):
            raise ValueError("Input image must be a numpy array")

        conf = float(inputs.get("confidence") or 0.25)
        iou = float(inputs.get("iou_threshold") or 0.7)
        tracker = str(inputs.get("tracker") or "bytetrack.yaml")
        imgsz = int(inputs.get("image_size") or 640)

        results = model.track(
            image, conf=conf, iou=iou, imgsz=imgsz,
            tracker=tracker, persist=True, verbose=False,
        )
        detections = _results_to_sv_detections(results)

        names = model.names
        class_names_str = ",".join(names[i] for i in sorted(names.keys()))

        n_tracked = 0
        if detections.tracker_id is not None:
            n_tracked = len(detections.tracker_id[detections.tracker_id >= 0])

        ctx.log(f"YOLO track: {len(detections)} detections, {n_tracked} tracked")
        return {
            "control_out": None,
            "detections": detections,
            "class_names": class_names_str,
        }


# ============================================================================
# YOLO POSE
# ============================================================================

UL_YOLO_POSE_SPEC = NodeSpec(
    type="ul.yolo.pose",
    version="1.0.0",
    display_name="YOLO - Pose",
    category="Ultralytics",
    summary="Run YOLO pose estimation.",
    description=(
        "Runs YOLO pose estimation on a numpy image and returns "
        "supervision Detections plus raw keypoints. "
        "Use a pose model (e.g. yolo11n-pose.pt)."
    ),
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="model", type=t_any(), required=True),
        PortSpec(name="image", type=t_any(), required=True),
        PortSpec(name="confidence", type=t_float(), required=False, default=0.25),
        PortSpec(name="iou_threshold", type=t_float(), required=False, default=0.7),
        PortSpec(name="image_size", type=t_int(), required=False, default=640),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_any()),
        PortSpec(name="keypoints", type=t_any()),
    ],
)


@register_node(UL_YOLO_POSE_SPEC)
class UlYoloPoseNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_ultralytics()
        model = inputs.get("model")
        image = inputs.get("image")
        if model is None:
            raise ValueError("No YOLO model provided")
        if image is None or not isinstance(image, np.ndarray):
            raise ValueError("Input image must be a numpy array")

        conf = float(inputs.get("confidence") or 0.25)
        iou = float(inputs.get("iou_threshold") or 0.7)
        imgsz = int(inputs.get("image_size") or 640)

        results = model(image, conf=conf, iou=iou, imgsz=imgsz, verbose=False)
        detections = _results_to_sv_detections(results)

        keypoints = None
        if results[0].keypoints is not None:
            keypoints = results[0].keypoints.data.cpu().numpy()

        ctx.log(f"YOLO pose: {len(detections)} persons found")
        return {
            "control_out": None,
            "detections": detections,
            "keypoints": keypoints,
        }
