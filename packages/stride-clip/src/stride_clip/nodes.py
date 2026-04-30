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
    try:
        from transformers import AutoProcessor  # type: ignore
    except ImportError:  # pragma: no cover - very old transformers
        AutoProcessor = None  # type: ignore
    try:
        from transformers import CLIPImageProcessor, CLIPTokenizer  # type: ignore
    except ImportError:  # pragma: no cover
        CLIPImageProcessor = None  # type: ignore
        CLIPTokenizer = None  # type: ignore
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False
    CLIPModel = None  # type: ignore
    CLIPProcessor = None  # type: ignore
    AutoProcessor = None  # type: ignore
    CLIPImageProcessor = None  # type: ignore
    CLIPTokenizer = None  # type: ignore

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.errors import NodeMissingDependencyError
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_control, t_float, t_int, t_list, t_string, t_image, t_record,
)
from stride_core.image_utils import decode_image_to_numpy


def _require_deps() -> None:
    if not HAS_NUMPY or not HAS_CV2 or not HAS_PIL:
        raise NodeMissingDependencyError("numpy, opencv-python, and pillow are required for CLIP nodes")
    if not HAS_TORCH:
        raise NodeMissingDependencyError("torch not installed (pip install torch)")
    if not HAS_TRANSFORMERS:
        raise NodeMissingDependencyError(
            "transformers not installed (pip install transformers)."
        )


def _load_processor(checkpoint: str) -> Any:
    """Load the CLIP processor with a fallback chain.

    Some HF caches end up partially populated when a download is interrupted
    (network flake, ctrl-C). ``CLIPProcessor.from_pretrained`` then complains
    about a missing ``preprocessor_config.json`` even though one of the more
    specific classes can still load the same files. Try the canonical class
    first, fall back through ``AutoProcessor`` and the concrete
    ``CLIPImageProcessor``, and only re-raise once every path fails.
    """
    last_err: Exception | None = None
    # Note: only CLIPProcessor / AutoProcessor return a full processor with
    # text tokenizer; CLIPImageProcessor is image-only and won't support the
    # text= kwarg used by the classifier. We deliberately leave it out of
    # the chain so a partial cache fails loudly rather than silently breaking
    # text-prompt classification at call time.
    candidates = [CLIPProcessor, AutoProcessor]
    for klass in candidates:
        if klass is None:
            continue
        try:
            return klass.from_pretrained(checkpoint)
        except Exception as exc:  # noqa: BLE001 — re-raised below if all fail
            last_err = exc
            continue
    safe_dir = checkpoint.replace("/", "--")
    cache_hint = (
        "If the error mentions a missing 'preprocessor_config.json', the HF cache "
        "may be partially populated from an interrupted download. Delete "
        f"'~/.cache/huggingface/hub/models--{safe_dir}' and retry."
    )
    raise NodeMissingDependencyError(
        f"Failed to load CLIP processor for '{checkpoint}'. {cache_hint} "
        f"Underlying error: {last_err}"
    ) from last_err


def _load_model(ctx: ExecutionContext, checkpoint: str, device: str):
    """Get-or-create a (processor, model, device) bundle on the run-scoped registry."""
    if not device:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    cache_key = f"stride_clip:{checkpoint}|{device}"

    def _factory():
        processor = _load_processor(checkpoint)
        model = CLIPModel.from_pretrained(checkpoint).to(device).eval()
        return (processor, model, device)

    return ctx.acquire_run_resource(cache_key, _factory)


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

        processor, model, used_device = _load_model(ctx, checkpoint, device)

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

        processor, model, used_device = _load_model(ctx, checkpoint, device)

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
