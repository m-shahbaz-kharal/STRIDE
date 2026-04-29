"""
Depth Anything V2 monocular depth estimation node.

Wraps the Hugging Face `transformers` `AutoModelForDepthEstimation` API
which has first-class support for the `depth-anything/...` checkpoints.
"""

from __future__ import annotations

import base64
from typing import Any, Dict

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
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation  # type: ignore
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False
    AutoImageProcessor = None  # type: ignore
    AutoModelForDepthEstimation = None  # type: ignore

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_boolean, t_control, t_float, t_int, t_string, t_image, t_depthmap,
)
from stride_core.image_utils import decode_image_to_numpy, encode_numpy_to_image


_MODEL_CACHE: Dict[str, Any] = {}


def _require_deps() -> None:
    if not HAS_NUMPY or not HAS_CV2 or not HAS_PIL:
        raise RuntimeError("numpy, opencv-python, and pillow are required for depth-anything nodes")
    if not HAS_TORCH:
        raise RuntimeError("torch not installed (pip install torch)")
    if not HAS_TRANSFORMERS:
        raise RuntimeError(
            "transformers not installed (pip install transformers). "
            "Depth Anything V2 weights are auto-downloaded by HF on first use."
        )


def _load_model(checkpoint: str, device: str) -> "tuple[Any, Any, str]":
    cache_key = f"{checkpoint}|{device}"
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if not device:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    processor = AutoImageProcessor.from_pretrained(checkpoint)
    model = AutoModelForDepthEstimation.from_pretrained(checkpoint).to(device).eval()
    _MODEL_CACHE[cache_key] = (processor, model, device)
    return processor, model, device


DEPTH_ANYTHING_SPEC = NodeSpec(
    type="image.depth.depth_anything",
    version="1.0.0",
    display_name="Depth Anything V2",
    category="Image / Depth",
    summary="Monocular depth estimation (Depth Anything V2).",
    description=(
        "Estimates a per-pixel relative depth map for an input image using "
        "the Depth Anything V2 transformer (Yang et al., CVPR 2024) via the "
        "Hugging Face transformers library."
    ),
    icon="layers",
    tags=["depth", "monocular", "transformers", "depth-anything"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_image(), required=True),
        PortSpec(
            name="checkpoint",
            type=t_string(),
            required=False,
            default="depth-anything/Depth-Anything-V2-Small-hf",
            description=(
                "HF model id. Options: "
                "'depth-anything/Depth-Anything-V2-Small-hf' (fastest), "
                "'depth-anything/Depth-Anything-V2-Base-hf', "
                "'depth-anything/Depth-Anything-V2-Large-hf' (best quality)."
            ),
        ),
        PortSpec(name="device", type=t_string(), required=False, default="",
                 description="'cpu', 'cuda', 'mps', or '' for auto"),
        PortSpec(name="colormap", type=t_string(), required=False, default="inferno",
                 description="OpenCV colormap for visualization (e.g. inferno, viridis, plasma, jet)"),
        PortSpec(name="visualize", type=t_boolean(), required=False, default=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="depth", type=t_depthmap()),
        PortSpec(name="image", type=t_image(),
                 description="Colorized depth visualization"),
        PortSpec(name="min_depth", type=t_float()),
        PortSpec(name="max_depth", type=t_float()),
    ],
    cache_policy="disabled",
)


@register_node(DEPTH_ANYTHING_SPEC)
class DepthAnythingNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_deps()
        image_str = inputs.get("image")
        if not image_str:
            raise ValueError("Depth Anything: no image provided")

        checkpoint = inputs.get("checkpoint") or "depth-anything/Depth-Anything-V2-Small-hf"
        device = inputs.get("device") or ""
        colormap = inputs.get("colormap") or "inferno"
        visualize = bool(inputs.get("visualize", True))

        ctx.log(f"Depth-Anything: checkpoint={checkpoint}")

        bgr = decode_image_to_numpy(image_str)
        h, w = bgr.shape[:2]
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)

        processor, model, used_device = _load_model(checkpoint, device)

        with torch.no_grad():
            inputs_t = processor(images=pil_img, return_tensors="pt").to(used_device)
            outputs = model(**inputs_t)
            predicted = outputs.predicted_depth  # (1, H', W')

            # Resize back to original
            depth = torch.nn.functional.interpolate(
                predicted.unsqueeze(1),
                size=(h, w),
                mode="bicubic",
                align_corners=False,
            ).squeeze().cpu().numpy().astype("float32")

        d_min = float(depth.min())
        d_max = float(depth.max())

        # Visualization
        viz_b64 = ""
        if visualize:
            norm = depth - d_min
            denom = max(d_max - d_min, 1e-6)
            norm = (norm / denom * 255.0).clip(0, 255).astype("uint8")
            cmap_id = _resolve_colormap(colormap)
            colored = cv2.applyColorMap(norm, cmap_id)
            viz_b64 = encode_numpy_to_image(colored, fmt="jpeg", quality=85)

        depth_b64 = base64.b64encode(depth.tobytes()).decode("ascii")
        depth_record = {
            "_type": "DepthMap",
            "width": int(w),
            "height": int(h),
            "depth_b64": depth_b64,
            "min_depth": d_min,
            "max_depth": d_max,
            "image": viz_b64,
        }

        ctx.log(f"Depth-Anything: depth range [{d_min:.3f}, {d_max:.3f}] on {used_device}")

        return {
            "control_out": None,
            "depth": depth_record,
            "image": viz_b64,
            "min_depth": d_min,
            "max_depth": d_max,
        }


def _resolve_colormap(name: str) -> int:
    """Resolve an OpenCV colormap name to its integer constant."""
    if not HAS_CV2:
        return 0
    table = {
        "inferno": cv2.COLORMAP_INFERNO,
        "viridis": cv2.COLORMAP_VIRIDIS,
        "plasma": cv2.COLORMAP_PLASMA,
        "jet": cv2.COLORMAP_JET,
        "magma": cv2.COLORMAP_MAGMA,
        "turbo": cv2.COLORMAP_TURBO,
        "cividis": cv2.COLORMAP_CIVIDIS,
        "hot": cv2.COLORMAP_HOT,
    }
    return table.get((name or "").lower(), cv2.COLORMAP_INFERNO)


def register() -> None:
    pass
