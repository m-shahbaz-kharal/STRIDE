# stride-kalman

Kalman-filter / Hungarian-assignment 3D multi-object tracker for STRIDE.

This is the de-facto reference 3D tracker for autonomous-driving
benchmarks (used by AB3DMOT, CenterPoint's tracking evaluator, and
nearly all KITTI/nuScenes leaderboards).  It runs a per-track linear
Kalman filter with a constant-velocity model in (x, y, z) space, and
solves the frame-to-frame association with the Hungarian algorithm.

This package implements the algorithm directly using `numpy` + `scipy`
since the dependency is tiny and the reference implementations
(AB3DMOT, etc.) are themselves trivially small Python.

## Installation

```bash
pip install numpy scipy
```

No model weights — pure algorithm.

## Nodes

| Node ID            | Purpose                                          |
|--------------------|--------------------------------------------------|
| `tracker.kalman3d` | Assigns persistent track IDs to 3D bbox detections |

## Reference

Weng & Kitani, *AB3DMOT: A Baseline for 3D Multi-Object Tracking and
New Evaluation Metrics*, IROS 2020.
