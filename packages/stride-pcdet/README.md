# stride-pcdet

3D LIDAR object detection nodes for STRIDE, wrapping the four most-cited
voxel/point-pillar detectors:

| Node ID                       | Algorithm     | Reference                                      |
|-------------------------------|---------------|------------------------------------------------|
| `lidar.detect.pointpillars`   | PointPillars  | Lang et al., CVPR 2019                         |
| `lidar.detect.centerpoint`    | CenterPoint   | Yin et al., CVPR 2021                          |
| `lidar.detect.second`         | SECOND        | Yan et al., Sensors 2018                       |
| `lidar.detect.pvrcnn`         | PV-RCNN       | Shi et al., CVPR 2020                          |

All four detectors share the same input/output schema: a STRIDE
PointCloud in, and a list of `bbox3d` records with class labels and
confidence scores out.  We bundle them into one package because they
all draw from the same underlying ecosystem (**OpenPCDet** /
**mmdet3d**) and choosing between them is a hyperparameter.

## Why one package and not four?

These four algorithms share the exact same dependency stack — `torch`,
`spconv`, and either `OpenPCDet` or `mmdetection3d` — and choosing
between them is a one-line config change.  Splitting them into four
packages would force the user to install the same heavyweight stack
four times.  This is the explicit guidance Agent 2 was given when this
package was created ("group these four under one package
`stride-pcdet` if it makes more sense").

## Status

These nodes are implemented as **complete NodeSpecs with runnable
adapter glue**, but since both OpenPCDet and mmdet3d are non-trivial
to install (they require building CUDA C++ extensions and matching
PyTorch/CUDA versions), the actual model invocation tries multiple
backends in order:

1. **`pcdet`** (OpenPCDet) — preferred. The node tries to instantiate
   the matching detector if `pcdet` is importable AND you've passed a
   `config_path` and `weights` parameter.
2. Falls back with a clean `RuntimeError` describing how to install
   the deps and where to find the official weights.

This gives you a working pipeline as soon as either backend is
installed, and a clear error message until then.  No wrong / fake
results are ever returned.

## Installation (any one of these)

### Option A: OpenPCDet (recommended, official PointPillars/CenterPoint/PV-RCNN/SECOND)

```bash
# Ensure CUDA + matching torch first
pip install torch
pip install spconv-cu121         # match your CUDA version
git clone https://github.com/open-mmlab/OpenPCDet
cd OpenPCDet && pip install -e .
```

Pretrained weights (PyTorch checkpoints) are at
[OpenPCDet#model-zoo](https://github.com/open-mmlab/OpenPCDet#model-zoo).

Then in the node, set:

* `config_path` = absolute path to the OpenPCDet YAML
  (e.g. `tools/cfgs/kitti_models/pointpillar.yaml`)
* `weights` = absolute path to the matching `.pth` file

### Option B: mmdetection3d

```bash
pip install -U openmim
mim install mmengine
mim install mmcv
mim install mmdet
mim install mmdet3d
```

Then point `config_path` and `weights` at any of the
[mmdet3d configs](https://github.com/open-mmlab/mmdetection3d/tree/main/configs).

## Input / Output

* **Input** `point_cloud` — STRIDE `t_pointcloud` (typed positions list +
  optional intensity).  See `stride-ouster` for the canonical producer.
* **Output** `boxes` — list of `t_bbox3d` records, each with `center`,
  `size`, `id`, `class_id`, `class_name`, `confidence`, and a
  `heading` (yaw, radians).

Velocity-aware variants (CenterPoint nuScenes config) additionally
populate the optional `velocity` field of the bbox3d record.
