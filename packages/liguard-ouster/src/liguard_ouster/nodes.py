from __future__ import annotations

import json
import time
from typing import Any, Dict

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

try:
    from ouster.sdk import open_source
    from ouster.sdk import core as ouster_core
    OUSTER_AVAILABLE = True
except ImportError:
    OUSTER_AVAILABLE = False

from liguard_core import register_node, NodeBase, ExecutionContext
from liguard_core.node_spec import NodeSpec, PortSpec
from liguard_core.typesystem import t_any, t_control, t_float, t_int, t_pointcloud, t_string


def _require_ouster() -> None:
    if not OUSTER_AVAILABLE:
        raise RuntimeError(
            "ouster-sdk is not installed. Please install it with: pip install ouster-sdk"
        )


def _require_numpy() -> None:
    if not NUMPY_AVAILABLE:
        raise RuntimeError(
            "numpy is not installed. Please install it with: pip install numpy"
        )


# ---------------------------------------------------------------------------
# Node 1: Open Ouster Source
# ---------------------------------------------------------------------------

OUSTER_OPEN_SOURCE_SPEC = NodeSpec(
    type="ouster.open_source",
    version="1.0.0",
    display_name="Open Ouster Source",
    category="Ouster LiDAR",
    summary="Open an Ouster pcap+metadata file as a scan source.",
    description=(
        "Uses ouster-sdk open_source() to open a pcap file with its "
        "associated JSON metadata. Returns an opaque scan source handle, "
        "sensor info JSON, and the total number of frames."
    ),
    icon="radar",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="pcap_path", type=t_string(), required=True, default=""),
        PortSpec(name="metadata_path", type=t_string(), required=True, default=""),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="source", type=t_any()),
        PortSpec(name="sensor_info", type=t_string()),
        PortSpec(name="num_frames", type=t_int()),
    ],
)


@register_node(OUSTER_OPEN_SOURCE_SPEC)
class OusterOpenSourceNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_ouster()
        _require_numpy()

        pcap_path = str(inputs.get("pcap_path", ""))
        metadata_path = str(inputs.get("metadata_path", ""))
        if not pcap_path:
            raise ValueError("pcap_path is required")
        if not metadata_path:
            raise ValueError("metadata_path is required")

        ctx.log(f"Opening Ouster source: {pcap_path}")
        source = open_source(
            pcap_path,
            meta=[metadata_path],
            sensor_idx=0,
        )

        # Extract sensor info (v0.16 API: sensor_info is a list)
        info = source.sensor_info[0]
        info_json = json.dumps({
            "product_line": str(getattr(info, "prod_line", "unknown")),
            "fw_rev": str(getattr(info, "fw_rev", "unknown")),
            "sn": str(getattr(info, "sn", "unknown")),
        })

        # Collect all scans into a list for random access
        # v0.16 API: iterator yields LidarScanSet, index [0] to get LidarScan
        ctx.log("Scanning frames...")
        scans = []
        for scan_set in source:
            scans.append(scan_set[0])
        num_frames = len(scans)
        ctx.log(f"Loaded {num_frames} frames")

        # Bundle the source data for downstream
        source_bundle = {
            "_type": "OusterSource",
            "scans": scans,
            "metadata": info,
        }

        return {
            "control_out": None,
            "source": source_bundle,
            "sensor_info": info_json,
            "num_frames": num_frames,
        }


# ---------------------------------------------------------------------------
# Node 2: Get Ouster Frame
# ---------------------------------------------------------------------------

OUSTER_GET_FRAME_SPEC = NodeSpec(
    type="ouster.get_frame",
    version="1.0.0",
    display_name="Get Ouster Frame",
    category="Ouster LiDAR",
    summary="Extract a point cloud from an Ouster scan source.",
    description=(
        "Reads a specific frame from the Ouster source, converts it to "
        "XYZ coordinates using XYZLut, and outputs a general PointCloud dict. "
        "Optionally downsamples if the point count exceeds max_points."
    ),
    icon="radar",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="source", type=t_any(), required=True, default=None),
        PortSpec(name="frame_index", type=t_int(), required=False, default=0),
        PortSpec(name="max_points", type=t_int(), required=False, default=100000),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="point_cloud", type=t_pointcloud()),
        PortSpec(name="frame_id", type=t_int()),
        PortSpec(name="timestamp", type=t_float()),
    ],
)


@register_node(OUSTER_GET_FRAME_SPEC)
class OusterGetFrameNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_ouster()
        _require_numpy()

        source_bundle = inputs.get("source")
        if not source_bundle or not isinstance(source_bundle, dict):
            raise ValueError("Invalid or missing input: source")
        if source_bundle.get("_type") != "OusterSource":
            raise ValueError("source must come from an Open Ouster Source node")

        scans = source_bundle["scans"]
        metadata = source_bundle["metadata"]

        frame_index = int(inputs.get("frame_index", 0))
        max_points = int(inputs.get("max_points", 100000))

        if frame_index < 0 or frame_index >= len(scans):
            raise ValueError(
                f"frame_index {frame_index} out of range [0, {len(scans) - 1}]"
            )

        scan = scans[frame_index]
        ctx.log(f"Processing frame {frame_index} (frame_id={scan.frame_id})")

        # Build XYZ lookup table and convert to 3D coordinates
        xyzlut = ouster_core.XYZLut(metadata)
        xyz = xyzlut(scan)  # shape: (H, W, 3)

        # Get range to filter zero-range (invalid) points
        range_field = scan.field(ouster_core.ChanField.RANGE)  # (H, W)
        valid_mask = range_field.flatten() > 0
        points = xyz.reshape(-1, 3)
        valid_points = points[valid_mask]

        # Gather optional per-point fields
        fields: Dict[str, Any] = {}
        for field_name, key in [
            (ouster_core.ChanField.SIGNAL, "signal"),
            (ouster_core.ChanField.REFLECTIVITY, "reflectivity"),
            (ouster_core.ChanField.NEAR_IR, "near_ir"),
        ]:
            try:
                field_data = scan.field(field_name)
                field_flat = field_data.flatten().astype(np.float64)
                fields[key] = field_flat[valid_mask]
            except Exception:
                pass

        num_valid = int(valid_points.shape[0])
        ctx.log(f"Valid points: {num_valid}")

        # Downsample if needed
        if num_valid > max_points:
            ctx.log(f"Downsampling from {num_valid} to {max_points}")
            indices = np.random.choice(num_valid, max_points, replace=False)
            indices.sort()
            valid_points = valid_points[indices]
            for k in fields:
                fields[k] = fields[k][indices]
            num_valid = max_points

        # Convert to lists for JSON serialization
        positions = valid_points.tolist()
        serialized_fields = {k: v.tolist() for k, v in fields.items()}

        point_cloud = {
            "_type": "PointCloud",
            "num_points": num_valid,
            "positions": positions,
            "fields": serialized_fields,
            "metadata": {
                "source": "ouster",
                "frame_id": int(scan.frame_id),
                "frame_index": frame_index,
            },
        }

        return {
            "control_out": None,
            "point_cloud": point_cloud,
            "frame_id": int(scan.frame_id),
            "timestamp": float(time.time()),
        }
