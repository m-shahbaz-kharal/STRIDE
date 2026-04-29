"""
Grounding DINO open-vocabulary detection node.

Wraps Hugging Face transformers' `AutoModelForZeroShotObjectDetection`
which has first-class support for the `IDEA-Research/grounding-dino-*`
checkpoints (Liu et al., ECCV 2024).
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
    import torch  # type: ignore
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    torch = None  # type: ignore

try:
    from PIL import Image  # type: ignore
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    Image = None  # type: ignore

try:
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor  # type: ignore
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False
    AutoModelForZeroShotObjectDetection = None  # type: ignore
    AutoProcessor = None  # type: ignore

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.errors import NodeMissingDependencyError
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_boolean, t_control, t_float, t_int, t_list, t_string,
    t_image, t_bbox2d, t_detections2d,
)
from stride_core.image_utils import (
    decode_image_to_numpy, encode_numpy_to_image, make_bbox2d, make_detections2d,
)


def _require_deps() -> None:
    if not HAS_NUMPY or not HAS_CV2 or not HAS_PIL:
        raise NodeMissingDependencyError("numpy, opencv-python, and pillow are required")
    if not HAS_TORCH:
        raise NodeMissingDependencyError("torch not installed")
    if not HAS_TRANSFORMERS:
        raise NodeMissingDependencyError("transformers not installed (pip install transformers)")


def _load_model(ctx: ExecutionContext, checkpoint: str, device: str):
    """Get-or-create a Grounding DINO (processor, model, device) bundle on the run-scoped registry."""
    if not device:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    cache_key = f"stride_grounding_dino:{checkpoint}|{device}"

    def _factory():
        processor = AutoProcessor.from_pretrained(checkpoint)
        model = AutoModelForZeroShotObjectDetection.from_pretrained(checkpoint).to(device).eval()
        return (processor, model, device)

    return ctx.acquire_run_resource(cache_key, _factory)


GROUNDING_DINO_SPEC = NodeSpec(
    type="image.detect.grounding_dino",
    version="1.0.0",
    display_name="Grounding DINO",
    category="Image / Detection",
    summary="Open-vocabulary detection from a text prompt.",
    description=(
        "Runs Grounding DINO (IDEA Research, ECCV 2024) via Hugging Face "
        "transformers. The user provides a period-separated `text_prompt` "
        "naming the categories to find (e.g. 'a person. a car. a "
        "truck.') and the model returns bounding boxes for each phrase."
    ),
    icon="search",
    tags=["grounding-dino", "open-vocab", "transformer", "detection"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_image(), required=True),
        PortSpec(
            name="text_prompt",
            type=t_string(),
            required=True,
            default="a person. a car. a truck. a bicycle.",
            description="Period-separated list of text queries; lowercase recommended.",
        ),
        PortSpec(name="checkpoint", type=t_string(), required=False,
                 default="IDEA-Research/grounding-dino-tiny",
                 description="HF model id (tiny, base, or a fine-tuned variant)"),
        PortSpec(name="box_threshold", type=t_float(), required=False, default=0.35),
        PortSpec(name="text_threshold", type=t_float(), required=False, default=0.25),
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


def _draw_boxes(bgr: "np.ndarray", boxes: List[Dict[str, Any]]) -> "np.ndarray":
    out = bgr.copy()
    for b in boxes:
        p1 = (int(b["x1"]), int(b["y1"]))
        p2 = (int(b["x2"]), int(b["y2"]))
        cv2.rectangle(out, p1, p2, (0, 255, 0), 2)
        label = f"{b['class_name']} {b['confidence']:.2f}"
        cv2.putText(out, label, (p1[0], max(0, p1[1] - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    return out


@register_node(GROUNDING_DINO_SPEC)
class GroundingDinoNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_deps()
        image_str = inputs.get("image")
        if not image_str:
            raise ValueError("Grounding DINO: no image provided")
        text_prompt = inputs.get("text_prompt") or ""
        if not text_prompt.strip():
            raise ValueError("Grounding DINO: text_prompt is required")

        checkpoint = inputs.get("checkpoint") or "IDEA-Research/grounding-dino-tiny"
        try:
            box_thresh = float(inputs.get("box_threshold") if inputs.get("box_threshold") is not None else 0.35)
        except (TypeError, ValueError):
            box_thresh = 0.35
        try:
            text_thresh = float(inputs.get("text_threshold") if inputs.get("text_threshold") is not None else 0.25)
        except (TypeError, ValueError):
            text_thresh = 0.25
        device = inputs.get("device") or ""
        annotate = bool(inputs.get("annotate", True))

        ctx.log(f"Grounding DINO: checkpoint={checkpoint} prompt={text_prompt!r}")

        bgr = decode_image_to_numpy(image_str)
        h, w = bgr.shape[:2]
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)

        processor, model, used_device = _load_model(ctx, checkpoint, device)

        # Grounding DINO expects lowercase text ending with a period per phrase
        text = text_prompt.lower().strip()
        if not text.endswith("."):
            text = text + "."

        with torch.no_grad():
            batch = processor(images=pil_img, text=text, return_tensors="pt").to(used_device)
            outputs = model(**batch)
            target_sizes = torch.tensor([[h, w]]).to(used_device)
            # transformers >=4.50 uses post_process_grounded_object_detection
            post = getattr(processor, "post_process_grounded_object_detection", None)
            if post is None:  # pragma: no cover - older transformers
                post = processor.post_process_object_detection
            results = post(
                outputs,
                input_ids=batch["input_ids"],
                box_threshold=box_thresh,
                text_threshold=text_thresh,
                target_sizes=target_sizes,
            )

        out_boxes: List[Dict[str, Any]] = []
        if results:
            r = results[0]
            scores = r["scores"].detach().cpu().numpy()
            boxes = r["boxes"].detach().cpu().numpy()
            labels = r.get("labels", None)
            for i, (score, box) in enumerate(zip(scores, boxes)):
                cname = ""
                if labels is not None and i < len(labels):
                    cname = str(labels[i])
                out_boxes.append(make_bbox2d(
                    x1=float(box[0]), y1=float(box[1]),
                    x2=float(box[2]), y2=float(box[3]),
                    confidence=float(score),
                    class_id=i,  # no fixed class id space — use index
                    class_name=cname,
                ))

        annotated_b64 = ""
        if annotate:
            annotated = _draw_boxes(bgr, out_boxes)
            annotated_b64 = encode_numpy_to_image(annotated, fmt="jpeg", quality=85)

        detections = make_detections2d(out_boxes, w, h, image=annotated_b64 or None)
        ctx.log(f"Grounding DINO: {len(out_boxes)} boxes")

        return {
            "control_out": None,
            "detections": detections,
            "boxes": out_boxes,
            "count": len(out_boxes),
            "image": annotated_b64,
        }


def register() -> None:
    pass
