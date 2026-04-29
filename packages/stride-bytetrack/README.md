# stride-bytetrack

ByteTrack 2D multi-object tracking for STRIDE.

This package wraps Roboflow's `supervision.ByteTrack`, which is a clean
port of the original
[ByteTrack reference implementation](https://github.com/ifzhang/ByteTrack)
(Zhang et al., ECCV 2022).  No tracking logic is reimplemented.

## Installation

```bash
pip install supervision opencv-python
```

## Nodes

| Node ID            | Purpose                                        |
|--------------------|------------------------------------------------|
| `tracker.bytetrack` | Assigns persistent track IDs to 2D detections |

The node is **stateful** — it maintains one tracker instance per node
ID across frames.  Set the `reset` parameter to True to clear the
tracker (e.g. when restarting a stream).

## Input / Output

* **Input**: a STRIDE `Detections2D` record (typically from `stride-yolo`,
  `stride-rtdetr`, etc.)
* **Output**: the same record with each box augmented with a
  `track_id` field, plus an annotated image showing the IDs.

## Reference

Zhang et al., *ByteTrack: Multi-Object Tracking by Associating Every
Detection Box*, ECCV 2022.
