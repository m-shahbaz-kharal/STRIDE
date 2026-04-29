# stride-rtdetr

RT-DETR (Real-Time DEtection TRansformer, Baidu PaddlePaddle) for STRIDE.

This package wraps the RT-DETR family of weights that ship with the
Ultralytics library (`rtdetr-l.pt`, `rtdetr-x.pt`).  RT-DETR is a
transformer-based detector that delivers DETR-level accuracy at YOLO-level
speeds and is one of the strongest publicly available real-time detectors
on COCO.

## Installation

```bash
pip install ultralytics opencv-python
```

Weights are auto-downloaded by Ultralytics on first use.

## Nodes

| Node ID                | Purpose                                      |
|------------------------|----------------------------------------------|
| `image.detect.rtdetr`  | RT-DETR object detection (default `rtdetr-l.pt`) |

The output schema matches `stride-yolo` (`Detections2D`).

## Reference

* Lv et al., *DETRs Beat YOLOs on Real-time Object Detection*, CVPR 2024.
