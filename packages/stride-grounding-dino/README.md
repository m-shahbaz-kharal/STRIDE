# stride-grounding-dino

Open-vocabulary 2D object detection with **Grounding DINO** (Liu et al.,
ECCV 2024) for STRIDE.

This package wraps the Hugging Face `transformers` integration of
Grounding DINO via the
`AutoModelForZeroShotObjectDetection` / `AutoProcessor` APIs. Default
checkpoint is `IDEA-Research/grounding-dino-tiny`; the
`IDEA-Research/grounding-dino-base` checkpoint is also supported.

## Installation

```bash
pip install transformers torch pillow opencv-python
```

Weights are auto-downloaded by Hugging Face on first use.

## Nodes

| Node ID                          | Purpose                                |
|----------------------------------|----------------------------------------|
| `image.detect.grounding_dino`    | Open-vocabulary detection from a text prompt |

The user supplies a `text_prompt` listing the categories to find
(period-separated, e.g. `"a person. a car. a truck."`) — the model
returns bounding boxes for each phrase.

## Reference

Liu et al., *Grounding DINO: Marrying DINO with Grounded Pre-Training
for Open-Set Object Detection*, ECCV 2024.
