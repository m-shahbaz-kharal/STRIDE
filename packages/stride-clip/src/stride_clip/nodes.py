"""
CLIP zero-shot classification + image embedding nodes.

Wraps the Hugging Face `transformers` `CLIPModel` / `CLIPProcessor`
APIs, so any HF CLIP checkpoint can be used (default:
`openai/clip-vit-base-patch32`).
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
    from transformers import CLIPModel, CLIPProcessor  # type: ignore
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False
    CLIPModel = None  # type: ignore
    CLIPProcessor = None  # type: ignore

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_any, t_control, t_float, t_int, t_list, t_string, t_image, t_record,
)
from stride_core.image_utils import decode_image_to_numpy


_MODEL_CACHE: Dict[str, Any] = {}


def _require_deps() -> None:
    if not HAS_NUMPY or not HAS_CV2 or not HAS_PIL:
        raise RuntimeError("numpy, opencv-python, and pillow are required for CLIP nodes")
    if not HAS_TORCH:
        raise RuntimeError("torch not installed (pip install torch)")
    if not HAS_TRANSFORMERS:
        raise RuntimeError(
            "transformers not installed (pip install transformers)."
        )


def _load_model(checkpoint: str, device: str):
    cache_key = f"{checkpoint}|{device}"
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached
    if not device:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    processor = CLIPProcessor.from_pretrained(checkpoint)
    model = CLIPModel.from_pretrained(checkpoint).to(device).eval()
    _MODEL_CACHE[cache_key] = (processor, model, device)
    return processor, model, device


def _bgr_to_pil(bgr: "np.ndarray") -> "Image.Image":
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


# =============================================================================
# Classifier
# =============================================================================

CLIP_CLASSIFY_SPEC = NodeSpec(
    type="image.classify.clip",
    version="1.0.0",
    display_name="CLIP Classify",
    category="Image / Classification",
    summary="Zero-shot classification with OpenAI CLIP.",
    description=(
        "Computes per-prompt softmax probabilities for an image given a "
        "user-provided list of text prompts.  Default checkpoint: "
        "openai/clip-vit-base-patch32."
    ),
    icon="tag",
    tags=["clip", "zero-shot", "classification"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_image(), required=True),
        PortSpec(
            name="prompts",
            type=t_string(),
            required=True,
            default="a photo of a person, a photo of a car, a photo of a dog, a photo of a cat",
            description="Comma-separated list of candidate text prompts",
        ),
        PortSpec(name="checkpoint", type=t_string(), required=False,
                 default="openai/clip-vit-base-patch32"),
        PortSpec(name="device", type=t_string(), required=False, default=""),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="top_label", type=t_string(),
                 description="Prompt with the highest probability"),
        PortSpec(name="top_score", type=t_float()),
        PortSpec(name="labels", type=t_list(t_string())),
        PortSpec(name="scores", type=t_list(t_float())),
        PortSpec(name="results", type=t_list(t_record({
            "label": t_string(),
            "score": t_float(),
        }))),
    ],
    cache_policy="disabled",
)


@register_node(CLIP_CLASSIFY_SPEC)
class CLIPClassifyNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_deps()
        image_str = inputs.get("image")
        if not image_str:
            raise ValueError("CLIP classify: no image provided")
        prompts_str = inputs.get("prompts") or ""
        if isinstance(prompts_str, list):
            prompts = [str(p).strip() for p in prompts_str if str(p).strip()]
        else:
            prompts = [p.strip() for p in str(prompts_str).split(",") if p.strip()]
        if not prompts:
            raise ValueError("CLIP classify: no prompts provided")

        checkpoint = inputs.get("checkpoint") or "openai/clip-vit-base-patch32"
        device = inputs.get("device") or ""

        ctx.log(f"CLIP classify: checkpoint={checkpoint} prompts={len(prompts)}")

        bgr = decode_image_to_numpy(image_str)
        pil = _bgr_to_pil(bgr)

        processor, model, used_device = _load_model(checkpoint, device)

        with torch.no_grad():
            batch = processor(text=prompts, images=pil, return_tensors="pt", padding=True).to(used_device)
            outputs = model(**batch)
            logits = outputs.logits_per_image  # (1, n_prompts)
            probs = logits.softmax(dim=-1).squeeze(0).cpu().numpy()

        results = [
            {"label": prompts[i], "score": float(probs[i])}
            for i in range(len(prompts))
        ]
        # Sort descending by score
        ranked = sorted(results, key=lambda r: r["score"], reverse=True)
        top = ranked[0] if ranked else {"label": "", "score": 0.0}

        return {
            "control_out": None,
            "top_label": top["label"],
            "top_score": float(top["score"]),
            "labels": [r["label"] for r in ranked],
            "scores": [float(r["score"]) for r in ranked],
            "results": ranked,
        }


# =============================================================================
# Embedder
# =============================================================================

CLIP_EMBED_SPEC = NodeSpec(
    type="image.embed.clip",
    version="1.0.0",
    display_name="CLIP Embed",
    category="Image / Embedding",
    summary="L2-normalized CLIP image embedding.",
    description=(
        "Returns the CLIP image embedding for an input image. The "
        "embedding is L2-normalized so cosine similarity reduces to a "
        "dot product."
    ),
    icon="hash",
    tags=["clip", "embedding"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_image(), required=True),
        PortSpec(name="checkpoint", type=t_string(), required=False,
                 default="openai/clip-vit-base-patch32"),
        PortSpec(name="device", type=t_string(), required=False, default=""),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="embedding", type=t_list(t_float())),
        PortSpec(name="dim", type=t_int()),
    ],
    cache_policy="disabled",
)


@register_node(CLIP_EMBED_SPEC)
class CLIPEmbedNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_deps()
        image_str = inputs.get("image")
        if not image_str:
            raise ValueError("CLIP embed: no image provided")

        checkpoint = inputs.get("checkpoint") or "openai/clip-vit-base-patch32"
        device = inputs.get("device") or ""

        bgr = decode_image_to_numpy(image_str)
        pil = _bgr_to_pil(bgr)

        processor, model, used_device = _load_model(checkpoint, device)

        with torch.no_grad():
            inp = processor(images=pil, return_tensors="pt").to(used_device)
            features = model.get_image_features(**inp)
            features = features / features.norm(dim=-1, keepdim=True)
            vec = features.squeeze(0).cpu().numpy().astype("float32")

        return {
            "control_out": None,
            "embedding": [float(x) for x in vec.tolist()],
            "dim": int(vec.shape[0]),
        }


def register() -> None:
    pass
