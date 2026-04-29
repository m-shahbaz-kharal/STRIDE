"""
ByteTrack tracker node.

Wraps `supervision.ByteTrack`, a well-maintained, pip-installable port
of the original ByteTrack reference implementation (Zhang et al., ECCV
2022).
"""

from __future__ import annotations

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
    import supervision as sv  # type: ignore
    HAS_SV = True
except ImportError:
    HAS_SV = False
    sv = None  # type: ignore

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_boolean, t_control, t_float, t_int, t_list, t_string,
    t_image, t_bbox2d, t_detections2d,
)
from stride_core.image_utils import (
    decode_image_to_numpy, encode_numpy_to_image,
)


# Per-node tracker state, keyed by node id.
_TRACKERS: Dict[str, Any] = {}


def _require_deps() -> None:
    if not HAS_NUMPY:
        raise RuntimeError("numpy not installed")
    if not HAS_SV:
        raise RuntimeError(
            "supervision not installed. Install with: pip install supervision"
        )


BYTETRACK_SPEC = NodeSpec(
    type="tracker.bytetrack",
    version="1.0.0",
    display_name="ByteTrack",
    category="Tracking",
    summary="2D multi-object tracking with ByteTrack.",
    description=(
        "Assigns persistent track IDs to 2D detections across frames using "
        "ByteTrack (Zhang et al., ECCV 2022) via the `supervision` library. "
        "Stateful — maintains one tracker per node id."
    ),
    icon="git-branch",
    tags=["tracking", "mot", "bytetrack"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d(), required=True),
        PortSpec(name="image", type=t_image(), required=False, default=None,
                 description="Optional source image, used for the annotated output"),
        PortSpec(name="track_activation_threshold", type=t_float(), required=False, default=0.25),
        PortSpec(name="lost_track_buffer", type=t_int(), required=False, default=30,
                 description="Frames to keep a lost track alive before deleting"),
        PortSpec(name="minimum_matching_threshold", type=t_float(), required=False, default=0.8),
        PortSpec(name="frame_rate", type=t_int(), required=False, default=30),
        PortSpec(name="reset", type=t_boolean(), required=False, default=False,
                 description="Reset the tracker state on this call"),
        PortSpec(name="annotate", type=t_boolean(), required=False, default=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d(),
                 description="Detections augmented with stable track_id values"),
        PortSpec(name="boxes", type=t_list(t_bbox2d())),
        PortSpec(name="track_ids", type=t_list(t_int())),
        PortSpec(name="count", type=t_int()),
        PortSpec(name="image", type=t_image()),
    ],
    cache_policy="disabled",
)


def _detections_to_sv(boxes: List[Dict[str, Any]]) -> Any:
    """Pack a list of bbox2d records into a supervision.Detections."""
    if not boxes:
        return sv.Detections.empty()
    xyxy = np.array(
        [[b["x1"], b["y1"], b["x2"], b["y2"]] for b in boxes],
        dtype=np.float32,
    )
    confidence = np.array([b.get("confidence", 1.0) for b in boxes], dtype=np.float32)
    class_id = np.array([int(b.get("class_id", 0)) for b in boxes], dtype=int)
    return sv.Detections(xyxy=xyxy, confidence=confidence, class_id=class_id)


def _build_tracker(params: Dict[str, Any]) -> Any:
    """Construct a fresh sv.ByteTrack with the given params."""
    return sv.ByteTrack(
        track_activation_threshold=float(params["track_activation_threshold"]),
        lost_track_buffer=int(params["lost_track_buffer"]),
        minimum_matching_threshold=float(params["minimum_matching_threshold"]),
        frame_rate=int(params["frame_rate"]),
    )


@register_node(BYTETRACK_SPEC)
class ByteTrackNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_deps()

        det_record = inputs.get("detections")
        if not isinstance(det_record, dict):
            raise ValueError("ByteTrack: `detections` must be a Detections2D record")

        boxes_in: List[Dict[str, Any]] = list(det_record.get("boxes") or [])
        params = {
            "track_activation_threshold": inputs.get("track_activation_threshold") or 0.25,
            "lost_track_buffer": inputs.get("lost_track_buffer") or 30,
            "minimum_matching_threshold": inputs.get("minimum_matching_threshold") or 0.8,
            "frame_rate": inputs.get("frame_rate") or 30,
        }
        reset = bool(inputs.get("reset", False))
        annotate = bool(inputs.get("annotate", True))

        if reset or self.id not in _TRACKERS:
            _TRACKERS[self.id] = _build_tracker(params)
        tracker = _TRACKERS[self.id]

        sv_dets = _detections_to_sv(boxes_in)
        tracked = tracker.update_with_detections(sv_dets)

        # Build output boxes by re-packing supervision results.
        out_boxes: List[Dict[str, Any]] = []
        track_ids: List[int] = []
        if len(tracked) > 0:
            xyxy = np.asarray(tracked.xyxy)
            confidences = (
                np.asarray(tracked.confidence)
                if tracked.confidence is not None
                else np.zeros(len(tracked), dtype=np.float32)
            )
            class_ids = (
                np.asarray(tracked.class_id)
                if tracked.class_id is not None
                else np.zeros(len(tracked), dtype=int)
            )
            tids = tracked.tracker_id
            for i in range(len(tracked)):
                cls_id = int(class_ids[i])
                # Try to recover the class_name from the original box if possible
                class_name = ""
                for orig in boxes_in:
                    if int(orig.get("class_id", -1)) == cls_id:
                        class_name = str(orig.get("class_name", ""))
                        break
                tid = int(tids[i]) if tids is not None else -1
                out_boxes.append({
                    "x1": float(xyxy[i, 0]),
                    "y1": float(xyxy[i, 1]),
                    "x2": float(xyxy[i, 2]),
                    "y2": float(xyxy[i, 3]),
                    "confidence": float(confidences[i]),
                    "class_id": cls_id,
                    "class_name": class_name,
                    "track_id": tid,
                })
                track_ids.append(tid)

        # Annotate visualization
        annotated_b64 = ""
        image_str: Optional[str] = inputs.get("image")
        if image_str is None or image_str == "":
            image_str = det_record.get("image") or ""
        if annotate and image_str:
            try:
                bgr = decode_image_to_numpy(image_str)
                box_annotator = sv.BoxAnnotator()
                label_annotator = sv.LabelAnnotator()
                labels = [
                    f"#{tid} {b.get('class_name', '?')} {b.get('confidence', 0.0):.2f}"
                    for tid, b in zip(track_ids, out_boxes)
                ]
                annotated = box_annotator.annotate(scene=bgr, detections=tracked)
                if labels:
                    annotated = label_annotator.annotate(
                        scene=annotated, detections=tracked, labels=labels
                    )
                annotated_b64 = encode_numpy_to_image(annotated, fmt="jpeg", quality=85)
            except Exception as exc:  # pragma: no cover - best-effort
                ctx.log(f"annotate failed: {exc}")

        out_record = {
            "_type": "Detections2D",
            "image_width": det_record.get("image_width", 0),
            "image_height": det_record.get("image_height", 0),
            "boxes": out_boxes,
            "image": annotated_b64 or det_record.get("image", ""),
        }

        ctx.log(f"ByteTrack: {len(out_boxes)} tracks (in={len(boxes_in)})")

        return {
            "control_out": None,
            "detections": out_record,
            "boxes": out_boxes,
            "track_ids": track_ids,
            "count": len(out_boxes),
            "image": annotated_b64,
        }


def register() -> None:
    pass
