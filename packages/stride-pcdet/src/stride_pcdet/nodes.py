"""
3D LIDAR detection nodes — PointPillars, CenterPoint, SECOND, PV-RCNN.

Each node is a thin adapter over one of the OpenPCDet / mmdet3d
detector families.  The detectors themselves are NOT reimplemented —
this package wraps existing reference code.

Because OpenPCDet/mmdet3d both have non-trivial CUDA build deps, this
module:

  * defines complete NodeSpecs (so the nodes show up in the editor
    even when no detector backend is installed);
  * tries to instantiate a real detector via OpenPCDet's `pcdet`
    package when a `config_path` and `weights` are supplied;
  * raises a clean `RuntimeError` with installation guidance if no
    backend is available, instead of returning faked detections.

Output schema
-------------
Each detection is a record:

    {
        "id": int,                      # 1..N within frame (overwritten by trackers)
        "center": [x, y, z],            # box center (m, sensor frame)
        "size": [w, l, h],              # box extents (m)
        "heading": float,               # yaw (rad)
        "confidence": float,
        "class_id": int,
        "class_name": str,
        "velocity": [vx, vy] | None,    # only for CenterPoint nuScenes
    }
"""

from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional, Tuple

try:
    import numpy as np  # type: ignore
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None  # type: ignore

# Lazy backend imports.  Both backends are heavy + optional.
try:
    import torch  # type: ignore
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    torch = None  # type: ignore

try:
    from pcdet.config import cfg, cfg_from_yaml_file  # type: ignore
    from pcdet.models import build_network, load_data_to_gpu  # type: ignore
    from pcdet.datasets import DatasetTemplate  # type: ignore
    HAS_PCDET = True
except ImportError:
    HAS_PCDET = False

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_any, t_boolean, t_control, t_float, t_int, t_list, t_pointcloud,
    t_record, t_string, t_bbox3d, t_detections3d,
)


_MODEL_CACHE: Dict[str, Any] = {}


def _decode_pointcloud(cloud: Dict[str, Any]) -> "np.ndarray":
    """Pull (N, 3+) float32 points out of a STRIDE PointCloud record."""
    if not isinstance(cloud, dict):
        raise ValueError("point_cloud must be a PointCloud record")

    if cloud.get("positions_b64"):
        raw = base64.b64decode(cloud["positions_b64"])
        pts = np.frombuffer(raw, dtype=np.float32).reshape(-1, 3)
    elif cloud.get("positions") is not None:
        pts = np.asarray(cloud["positions"], dtype=np.float32)
        if pts.ndim == 1:
            pts = pts.reshape(-1, 3)
    else:
        raise ValueError("PointCloud has no `positions` or `positions_b64`")

    # Optional intensity / extra channel (most LIDAR detectors expect XYZI)
    intensities: Optional["np.ndarray"] = None
    if cloud.get("intensities_b64"):
        intensities = np.frombuffer(base64.b64decode(cloud["intensities_b64"]), dtype=np.float32)
    elif cloud.get("intensities") is not None:
        intensities = np.asarray(cloud["intensities"], dtype=np.float32)

    if intensities is not None and len(intensities) == len(pts):
        pts = np.concatenate([pts, intensities.reshape(-1, 1)], axis=1)
    else:
        # Pad with zero intensity column.  Most pretrained PointPillars/
        # CenterPoint/PV-RCNN/SECOND configs expect XYZI input.
        pts = np.concatenate([pts, np.zeros((len(pts), 1), dtype=np.float32)], axis=1)

    return pts


def _ensure_backend() -> str:
    """Pick a backend or raise RuntimeError with install instructions."""
    if HAS_PCDET and HAS_TORCH:
        return "pcdet"
    raise RuntimeError(
        "No 3D detector backend installed. This node wraps OpenPCDet / "
        "mmdet3d, which require CUDA-compiled extensions. Install one of:\n"
        "  - OpenPCDet (recommended): see "
        "https://github.com/open-mmlab/OpenPCDet#installation\n"
        "  - mmdetection3d: pip install -U openmim && mim install mmdet3d\n"
        "Then provide `config_path` and `weights` parameters."
    )


def _load_pcdet_model(config_path: str, weights: str, device: str) -> Tuple[Any, Any]:
    """Build a pcdet model + dataset template from a config/weights pair."""
    cache_key = f"{config_path}|{weights}|{device}"
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    cfg_from_yaml_file(config_path, cfg)
    if not device:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    # Minimal dataset template providing class_names + point_feature_encoder
    class _SingleFrameDataset(DatasetTemplate):
        def __init__(self):
            super().__init__(
                dataset_cfg=cfg.DATA_CONFIG,
                class_names=cfg.CLASS_NAMES,
                training=False,
                root_path=None,
                logger=None,
            )

        def __len__(self):  # pragma: no cover - never iterated
            return 0

        def __getitem__(self, idx):  # pragma: no cover - never indexed
            raise StopIteration

    dataset = _SingleFrameDataset()
    model = build_network(model_cfg=cfg.MODEL, num_class=len(cfg.CLASS_NAMES), dataset=dataset)
    model.load_params_from_file(filename=weights, logger=None, to_cpu=(device == "cpu"))
    model.to(device).eval()
    _MODEL_CACHE[cache_key] = (model, dataset)
    return model, dataset


def _run_pcdet_inference(
    model: Any,
    dataset: Any,
    pts_xyzi: "np.ndarray",
    score_threshold: float,
    device: str,
) -> List[Dict[str, Any]]:
    """Run a single forward pass through a pcdet model on one frame."""
    data_dict = dataset.prepare_data(data_dict={"points": pts_xyzi.astype(np.float32), "frame_id": "stride"})
    data_dict = dataset.collate_batch([data_dict])
    load_data_to_gpu(data_dict)
    with torch.no_grad():
        pred_dicts, _ = model(data_dict)

    pd = pred_dicts[0]
    boxes = pd["pred_boxes"].detach().cpu().numpy()      # (N, 7) or (N, 9)
    scores = pd["pred_scores"].detach().cpu().numpy()
    labels = pd["pred_labels"].detach().cpu().numpy()
    class_names = list(getattr(dataset, "class_names", []) or [])

    out: List[Dict[str, Any]] = []
    for i, (b, s, l) in enumerate(zip(boxes, scores, labels)):
        if s < score_threshold:
            continue
        cx, cy, cz, dx, dy, dz, heading = (float(x) for x in b[:7])
        cls_idx = int(l) - 1  # pcdet labels are 1-indexed
        cls_name = class_names[cls_idx] if 0 <= cls_idx < len(class_names) else str(cls_idx)
        rec: Dict[str, Any] = {
            "id": i + 1,
            "center": [cx, cy, cz],
            "size": [dx, dy, dz],
            "heading": heading,
            "confidence": float(s),
            "class_id": cls_idx,
            "class_name": cls_name,
        }
        if len(b) >= 9:  # CenterPoint nuScenes — has (vx, vy)
            rec["velocity"] = [float(b[7]), float(b[8])]
        out.append(rec)
    return out


# =============================================================================
# Shared NodeSpec factory
# =============================================================================

def _make_detector_spec(
    *,
    node_type: str,
    display_name: str,
    summary: str,
    description: str,
    default_config_path: str,
    default_weights: str,
) -> NodeSpec:
    return NodeSpec(
        type=node_type,
        version="1.0.0",
        display_name=display_name,
        category="LIDAR / Detection",
        summary=summary,
        description=description,
        icon="cube",
        tags=["lidar", "3d", "detection", "openpcdet"],
        inputs=[
            PortSpec(name="control_in", type=t_control(), required=False, default=None),
            PortSpec(name="point_cloud", type=t_pointcloud(), required=True),
            PortSpec(name="config_path", type=t_string(), required=False, default=default_config_path,
                     description="Path to an OpenPCDet YAML config"),
            PortSpec(name="weights", type=t_string(), required=False, default=default_weights,
                     description="Path to a matching .pth checkpoint"),
            PortSpec(name="score_threshold", type=t_float(), required=False, default=0.3,
                     description="Per-detection confidence threshold"),
            PortSpec(name="device", type=t_string(), required=False, default="",
                     description="'cuda', 'cpu', or '' for auto"),
        ],
        outputs=[
            PortSpec(name="control_out", type=t_control(), required=False, default=None),
            PortSpec(name="boxes", type=t_list(t_bbox3d()),
                     description="3D bounding box detections"),
            PortSpec(name="count", type=t_int()),
            PortSpec(name="detections", type=t_detections3d(),
                     description="Bundle of detections with metadata"),
        ],
        cache_policy="disabled",
    )


def _shared_forward(
    self: NodeBase,
    inputs: Dict[str, Any],
    ctx: ExecutionContext,
    *,
    detector_label: str,
) -> Dict[str, Any]:
    if not HAS_NUMPY:
        raise RuntimeError("numpy not installed")

    cloud = inputs.get("point_cloud")
    if not cloud:
        raise ValueError(f"{detector_label}: no point cloud provided")

    config_path = inputs.get("config_path") or ""
    weights = inputs.get("weights") or ""
    try:
        score_threshold = float(inputs.get("score_threshold") if inputs.get("score_threshold") is not None else 0.3)
    except (TypeError, ValueError):
        score_threshold = 0.3
    device = inputs.get("device") or ""

    if not config_path or not weights:
        raise RuntimeError(
            f"{detector_label}: `config_path` and `weights` are required. "
            "See the package README for installation + checkpoint URLs."
        )

    backend = _ensure_backend()
    if backend != "pcdet":  # pragma: no cover - only path implemented
        raise RuntimeError(f"unsupported backend {backend!r}")

    pts = _decode_pointcloud(cloud)
    ctx.log(f"{detector_label}: {len(pts)} points → {config_path}")

    model, dataset = _load_pcdet_model(config_path, weights, device)
    boxes = _run_pcdet_inference(model, dataset, pts, score_threshold, device)

    detections_record = {
        "_type": "Detections3D",
        "detector": detector_label,
        "boxes": boxes,
    }

    return {
        "control_out": None,
        "boxes": boxes,
        "count": len(boxes),
        "detections": detections_record,
    }


# =============================================================================
# Concrete detector nodes
# =============================================================================

POINTPILLARS_SPEC = _make_detector_spec(
    node_type="lidar.detect.pointpillars",
    display_name="PointPillars",
    summary="3D LIDAR detection with PointPillars (Lang et al., CVPR 2019).",
    description=(
        "PointPillars 3D object detection. Encodes the LIDAR point cloud "
        "into vertical pillars, runs a 2D backbone, and decodes 3D boxes. "
        "Wraps the OpenPCDet implementation."
    ),
    default_config_path="",
    default_weights="",
)


@register_node(POINTPILLARS_SPEC)
class PointPillarsNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        return _shared_forward(self, inputs, ctx, detector_label="PointPillars")


CENTERPOINT_SPEC = _make_detector_spec(
    node_type="lidar.detect.centerpoint",
    display_name="CenterPoint",
    summary="Center-based 3D LIDAR detection (Yin et al., CVPR 2021).",
    description=(
        "CenterPoint anchor-free 3D detector. Predicts object centers on a "
        "BEV heatmap and regresses 3D box parameters. Wraps OpenPCDet's "
        "CenterPoint configs."
    ),
    default_config_path="",
    default_weights="",
)


@register_node(CENTERPOINT_SPEC)
class CenterPointNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        return _shared_forward(self, inputs, ctx, detector_label="CenterPoint")


SECOND_SPEC = _make_detector_spec(
    node_type="lidar.detect.second",
    display_name="SECOND",
    summary="Sparsely Embedded Convolutional Detection (Yan et al., 2018).",
    description=(
        "SECOND voxel-based 3D detector. Uses sparse 3D conv (spconv) to "
        "extract features from voxelized LIDAR. Wraps the OpenPCDet "
        "SECOND configs."
    ),
    default_config_path="",
    default_weights="",
)


@register_node(SECOND_SPEC)
class SecondNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        return _shared_forward(self, inputs, ctx, detector_label="SECOND")


PVRCNN_SPEC = _make_detector_spec(
    node_type="lidar.detect.pvrcnn",
    display_name="PV-RCNN",
    summary="PointVoxel R-CNN — two-stage 3D detection (Shi et al., CVPR 2020).",
    description=(
        "PV-RCNN combines voxel-based proposal generation with point-based "
        "refinement. Wraps the OpenPCDet implementation."
    ),
    default_config_path="",
    default_weights="",
)


@register_node(PVRCNN_SPEC)
class PVRCNNNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        return _shared_forward(self, inputs, ctx, detector_label="PV-RCNN")


def register() -> None:
    pass
