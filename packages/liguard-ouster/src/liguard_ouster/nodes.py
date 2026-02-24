from __future__ import annotations

import base64
import json
import time
import threading
from typing import Any, Dict, List, Optional

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


# ═══════════════════════════════════════════════════════════════════════════
# Lazy Ouster Scan Source — reads frames on demand, caches what it reads
# ═══════════════════════════════════════════════════════════════════════════
class _LazyScans:
    """Wraps an ouster ScanSource iterator for lazy, on-demand frame loading.

    Frames are loaded sequentially (pcap files can't random-seek) but only as
    far as needed.  Already-read frames are cached so re-access is instant.
    Thread-safe for concurrent GetFrame calls.
    """

    def __init__(self, source: Any, metadata: Any, ctx: Optional[ExecutionContext] = None):
        self._source = source
        self._iter = iter(source)
        self._cache: List[Any] = []      # scans read so far
        self._exhausted = False
        self._lock = threading.Lock()
        self._metadata = metadata
        self._ctx = ctx
        # Pre-compute XYZLut once — this is expensive to build repeatedly
        self._xyzlut = ouster_core.XYZLut(metadata)

    @property
    def metadata(self) -> Any:
        return self._metadata

    @property
    def xyzlut(self) -> Any:
        return self._xyzlut

    @property
    def cached_count(self) -> int:
        return len(self._cache)

    @property
    def exhausted(self) -> bool:
        return self._exhausted

    def count_frames(self) -> int:
        """Scan through the entire source to get total frame count.
        Only iterates unread portions; already-cached frames are counted instantly.
        Respects interruption requests via ctx.is_interrupted.
        """
        with self._lock:
            if self._exhausted:
                return len(self._cache)
            # Iterate remaining frames, checking for interruption periodically
            frames_since_check = 0
            while not self._exhausted:
                # Check for interruption every 10 frames to avoid overhead
                if self._ctx and frames_since_check >= 10:
                    if self._ctx.is_interrupted:
                        if self._ctx:
                            self._ctx.log(f"Frame counting interrupted at {len(self._cache)} frames")
                        break
                    frames_since_check = 0
                try:
                    scan_set = next(self._iter)
                    self._cache.append(scan_set[0])
                    frames_since_check += 1
                except StopIteration:
                    self._exhausted = True
            if self._ctx:
                self._ctx.log(f"Indexed {len(self._cache)} total frames")
            return len(self._cache)

    def get(self, idx: int) -> Any:
        """Get scan at index `idx`, loading up to that point if necessary.
        Respects interruption requests via ctx.is_interrupted.
        """
        with self._lock:
            if idx < len(self._cache):
                return self._cache[idx]
            if self._exhausted:
                raise IndexError(f"Frame {idx} out of range (total: {len(self._cache)})")
            # Advance the iterator to the requested index, checking for interruption
            frames_since_check = 0
            while len(self._cache) <= idx:
                # Check for interruption every 10 frames
                if self._ctx and frames_since_check >= 10:
                    if self._ctx.is_interrupted:
                        raise InterruptedError(
                            f"Frame loading interrupted at {len(self._cache)} (target: {idx})"
                        )
                    frames_since_check = 0
                try:
                    scan_set = next(self._iter)
                    self._cache.append(scan_set[0])
                    frames_since_check += 1
                except StopIteration:
                    self._exhausted = True
                    raise IndexError(
                        f"Frame {idx} out of range (total: {len(self._cache)})"
                    )
            return self._cache[idx]

    def preload(self, count: int) -> int:
        """Pre-load up to `count` frames in background. Returns actual loaded count.
        Respects interruption requests via ctx.is_interrupted.
        """
        with self._lock:
            target = count
            frames_since_check = 0
            while len(self._cache) < target and not self._exhausted:
                # Check for interruption every 10 frames
                if self._ctx and frames_since_check >= 10:
                    if self._ctx.is_interrupted:
                        break
                    frames_since_check = 0
                try:
                    scan_set = next(self._iter)
                    self._cache.append(scan_set[0])
                    frames_since_check += 1
                except StopIteration:
                    self._exhausted = True
            return len(self._cache)


# ═══════════════════════════════════════════════════════════════════════════
# Node 1: Open Ouster Source  (lazy — no full scan on open)
# ═══════════════════════════════════════════════════════════════════════════

OUSTER_OPEN_SOURCE_SPEC = NodeSpec(
    type="ouster.open_source",
    version="1.0.0",
    display_name="Open Ouster Source",
    category="Ouster LiDAR",
    summary="Open an Ouster pcap+metadata file as a scan source.",
    description=(
        "Uses ouster-sdk open_source() to open a pcap file with its "
        "associated JSON metadata. Returns an opaque scan source handle, "
        "sensor info JSON, and the total number of frames. "
        "Frames are loaded lazily — only accessed frames are decoded."
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

        pcap_path = inputs.get("pcap_path")
        pcap_path = str(pcap_path) if pcap_path is not None else ""
        metadata_path = inputs.get("metadata_path")
        metadata_path = str(metadata_path) if metadata_path is not None else ""
        if not pcap_path:
            raise ValueError("pcap_path is required")
        if not metadata_path:
            raise ValueError("metadata_path is required")

        ctx.log(f"Opening Ouster source: {pcap_path}")
        t0 = time.time()
        source = open_source(
            pcap_path,
            meta=[metadata_path],
            sensor_idx=0,
        )

        # Extract sensor info
        info = source.sensor_info[0]
        info_json = json.dumps({
            "product_line": str(getattr(info, "prod_line", "unknown")),
            "fw_rev": str(getattr(info, "fw_rev", "unknown")),
            "sn": str(getattr(info, "sn", "unknown")),
        })

        # Wrap in lazy loader (no iteration yet!)
        lazy = _LazyScans(source, info, ctx)

        # Try instant O(1) frame count from the SDK first.
        # Only iterate the full file if that fails.
        num_frames: int
        try:
            num_frames = len(source)  # type: ignore[arg-type]
            ctx.log(f"Source reports {num_frames} frames (instant)")
        except (TypeError, AttributeError):
            # SDK doesn't support len() for this source type — full scan required
            ctx.log("Source does not support len(); scanning frames...")
            num_frames = lazy.count_frames()

        elapsed = time.time() - t0
        ctx.log(f"Source ready: {num_frames} frames in {elapsed:.1f}s")

        source_bundle = {
            "_type": "OusterSource",
            "_lazy": lazy,          # lazy accessor (not serialized — internal only)
            "num_frames": num_frames,
        }

        return {
            "control_out": None,
            "source": source_bundle,
            "sensor_info": info_json,
            "num_frames": num_frames,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Node 2: Get Ouster Frame  (optimized: reuses cached XYZLut, base64 output)
# ═══════════════════════════════════════════════════════════════════════════

OUSTER_GET_FRAME_SPEC = NodeSpec(
    type="ouster.get_frame",
    version="1.0.0",
    display_name="Get Ouster Frame",
    category="Ouster LiDAR",
    summary="Extract a point cloud from an Ouster scan source.",
    description=(
        "Reads a specific frame from the Ouster source, converts it to "
        "XYZ coordinates using XYZLut, and outputs a general PointCloud dict. "
        "Optionally downsamples if the point count exceeds max_points. "
        "Output uses base64-encoded Float32Arrays for maximum transfer speed."
    ),
    icon="radar",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="source", type=t_any(), required=True, default=None),
        PortSpec(name="frame_index", type=t_int(), required=False, default=0),
        PortSpec(name="max_points", type=t_int(), required=False, default=200000),
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

        lazy: _LazyScans = source_bundle["_lazy"]
        frame_index = int(inputs.get("frame_index") if inputs.get("frame_index") is not None else 0)
        max_points = int(inputs.get("max_points") if inputs.get("max_points") is not None else 200000)

        num_frames = source_bundle.get("num_frames", lazy.cached_count)
        if frame_index < 0 or frame_index >= num_frames:
            raise ValueError(
                f"frame_index {frame_index} out of range [0, {num_frames - 1}]"
            )

        t0 = time.time()
        scan = lazy.get(frame_index)
        ctx.log(f"Frame {frame_index} (id={scan.frame_id}) loaded in {(time.time()-t0)*1000:.0f}ms")

        # Use the pre-built XYZLut from the lazy source
        xyz = lazy.xyzlut(scan)  # (H, W, 3) float64

        # Filter invalid points (range == 0)
        range_field = scan.field(ouster_core.ChanField.RANGE)
        valid = range_field.flatten() > 0
        pts = xyz.reshape(-1, 3)[valid]

        # Gather optional per-point fields
        fields: Dict[str, np.ndarray] = {}
        for chan, key in [
            (ouster_core.ChanField.SIGNAL, "signal"),
            (ouster_core.ChanField.REFLECTIVITY, "reflectivity"),
            (ouster_core.ChanField.NEAR_IR, "near_ir"),
        ]:
            try:
                fd = scan.field(chan).flatten().astype(np.float32)[valid]
                fields[key] = fd
            except Exception:
                pass

        n = int(pts.shape[0])
        ctx.log(f"Valid: {n} points")

        # Downsample if needed
        if n > max_points:
            ctx.log(f"Downsampling {n} → {max_points}")
            idx = np.random.choice(n, max_points, replace=False)
            idx.sort()
            pts = pts[idx]
            for k in fields:
                fields[k] = fields[k][idx]
            n = max_points

        # Fast base64 binary serialization
        pos_b64 = base64.b64encode(pts.astype(np.float32).tobytes()).decode("ascii")
        fields_b64 = {
            k: base64.b64encode(v.astype(np.float32).tobytes()).decode("ascii")
            for k, v in fields.items()
        }

        elapsed_ms = (time.time() - t0) * 1000
        ctx.log(f"Frame processed in {elapsed_ms:.0f}ms")

        point_cloud = {
            "_type": "PointCloud",
            "num_points": n,
            "positions_b64": pos_b64,
            "fields_b64": fields_b64,
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
