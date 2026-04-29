# stride-depth-anything

Monocular depth estimation with **Depth Anything V2** (CVPR 2024, Yang
et al.) for STRIDE.

This package wraps the official Hugging Face `transformers` integration:

* `depth-anything/Depth-Anything-V2-Small-hf`
* `depth-anything/Depth-Anything-V2-Base-hf`
* `depth-anything/Depth-Anything-V2-Large-hf`

No model code is reimplemented — we use
`transformers.AutoImageProcessor` + `AutoModelForDepthEstimation` and
the model is auto-downloaded on first use to the standard Hugging Face
cache (`~/.cache/huggingface/hub`).

## Installation

```bash
pip install transformers torch pillow opencv-python
```

A CUDA-enabled PyTorch install is recommended; CPU inference works but
is slow on the Large model.

## Nodes

| Node ID                        | Purpose                              |
|--------------------------------|--------------------------------------|
| `image.depth.depth_anything`   | Monocular depth estimation           |

The node emits a STRIDE `depthmap` record:

```python
{
  "_type": "DepthMap",
  "width": int, "height": int,
  "depth_b64": str,           # float32, packed
  "min_depth": float,
  "max_depth": float,
  "image": str,               # colorized base64 visualization
}
```

## Reference

* Yang et al., *Depth Anything V2*, CVPR 2024.
