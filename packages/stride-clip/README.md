# stride-clip

Zero-shot image classification with **OpenAI CLIP** (Radford et al.,
2021) for STRIDE.

This package wraps the Hugging Face `transformers` integration of CLIP
(`CLIPModel` + `CLIPProcessor`).  Default checkpoint is
`openai/clip-vit-base-patch32`; any HF CLIP checkpoint id will work
(e.g. `openai/clip-vit-large-patch14`,
`laion/CLIP-ViT-H-14-laion2B-s32B-b79K`).

## Installation

```bash
pip install transformers torch pillow opencv-python
```

Weights are auto-downloaded by Hugging Face on first use.

## Nodes

| Node ID                | Purpose                              |
|------------------------|--------------------------------------|
| `image.classify.clip`  | Zero-shot classification             |
| `image.embed.clip`     | Image embedding (vector output)      |

The classifier takes an image plus a list of text prompts (one
candidate label per prompt), runs both modalities through CLIP, and
returns each prompt's softmax probability + the top label.

The embedder takes an image and returns the L2-normalized CLIP image
embedding (e.g. for downstream similarity / retrieval).

## Reference

Radford et al., *Learning Transferable Visual Models From Natural
Language Supervision*, ICML 2021.
