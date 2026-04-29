# stride-yolo

YOLO (v8 / v11) detection, segmentation, and pose-estimation nodes for the
STRIDE node-graph runtime.

## Algorithms

This package wraps Ultralytics' `ultralytics` Python library, which ships
official YOLOv8 / YOLO11 / YOLO-World weights and is the de-facto reference
implementation. No model code is reimplemented in this package — the nodes
are thin adapters that turn a STRIDE base64 image into a numpy array, run
the relevant predict call, and pack the output into STRIDE detection
records.

## Installation

```bash
pip install ultralytics opencv-python
```

The first time a node runs, Ultralytics will auto-download the model
weights to its cache directory (`~/.cache/ultralytics` by default).  No
manual weight download is required for the standard models
(`yolov8n.pt`, `yolo11n.pt`, etc.).

For custom weights, set the `weights` parameter to an absolute path to a
local `.pt` file.

## Nodes

| Node ID                | Purpose                                                |
|------------------------|--------------------------------------------------------|
| `image.detect.yolo`    | 2D bounding-box detection (default model: `yolo11n.pt`) |
| `image.segment.yolo`   | Instance segmentation (default `yolo11n-seg.pt`)        |
| `image.pose.yolo`      | Human pose / keypoints (default `yolo11n-pose.pt`)      |

All three accept a STRIDE `image` (base64 string) and emit a
`detections2d` record (boxes + class labels + confidence) plus an
optional annotated image for display.

## Example

```
core.image.load → image.detect.yolo → core.image.save
```

Set the `weights` parameter to choose a model size: `yolov8n.pt`,
`yolov8s.pt`, `yolov8m.pt`, `yolov8l.pt`, `yolov8x.pt`, or any of the
`yolo11*` equivalents.
