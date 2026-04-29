"""
People detection and occupancy tracking nodes.

Algorithm overview (no deep learning):
1. Background subtraction via voxel occupancy model
2. Ground plane removal via RANSAC
3. Height-based filtering
4. DBSCAN clustering
5. Human filtering by expected dimensions
6. Simple centroid-based tracking with Hungarian algorithm
"""

from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional
import uuid

try:
    import numpy as np
    from scipy.spatial.distance import cdist
    from scipy.optimize import linear_sum_assignment
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False
    np = None

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_pointcloud, t_float, t_int, t_string, t_boolean, t_list, t_any,
    t_record, t_control, t_bbox3d, t_region3d, t_scene3d,
)


# =============================================================================
# Utility Functions
# =============================================================================

def b64_to_f32(b64: str) -> "np.ndarray":
    """Decode base64 string to Float32 numpy array."""
    raw = base64.b64decode(b64)
    return np.frombuffer(raw, dtype=np.float32)


def f32_to_b64(arr: "np.ndarray") -> str:
    """Encode numpy array as base64 Float32."""
    return base64.b64encode(arr.astype(np.float32).tobytes()).decode("ascii")


def voxel_hash(pts: "np.ndarray", voxel_size: float) -> "np.ndarray":
    """Convert points to voxel indices."""
    return np.floor(pts / voxel_size).astype(np.int32)


def dbscan_cluster(pts: "np.ndarray", eps: float, min_samples: int) -> "np.ndarray":
    """
    Simple DBSCAN implementation.
    Returns array of cluster labels (-1 for noise).
    """
    n = len(pts)
    labels = np.full(n, -1, dtype=np.int32)
    cluster_id = 0

    # Build a simple distance matrix in chunks for memory efficiency
    visited = np.zeros(n, dtype=bool)

    for i in range(n):
        if visited[i]:
            continue

        # Find neighbors
        dists = np.linalg.norm(pts - pts[i], axis=1)
        neighbors = np.where(dists <= eps)[0]

        if len(neighbors) < min_samples:
            continue

        # Start a new cluster
        labels[i] = cluster_id
        visited[i] = True

        seed_set = list(neighbors)
        j = 0
        while j < len(seed_set):
            q = seed_set[j]
            if not visited[q]:
                visited[q] = True
                dists_q = np.linalg.norm(pts - pts[q], axis=1)
                neighbors_q = np.where(dists_q <= eps)[0]
                if len(neighbors_q) >= min_samples:
                    seed_set.extend(neighbors_q.tolist())
            if labels[q] == -1:
                labels[q] = cluster_id
            j += 1

        cluster_id += 1

    return labels


def fit_ground_plane_ransac(
    pts: "np.ndarray",
    n_iterations: int = 100,
    distance_threshold: float = 0.1
) -> tuple["np.ndarray", float]:
    """
    RANSAC ground plane fitting.
    Returns (normal, d) where plane is: normal . x + d = 0
    """
    best_inliers = 0
    best_plane = (np.array([0, 0, 1]), 0.0)

    n = len(pts)
    if n < 3:
        return best_plane

    for _ in range(n_iterations):
        # Sample 3 random points
        idx = np.random.choice(n, 3, replace=False)
        p1, p2, p3 = pts[idx]

        # Compute plane normal
        v1 = p2 - p1
        v2 = p3 - p1
        normal = np.cross(v1, v2)
        norm = np.linalg.norm(normal)
        if norm < 1e-6:
            continue
        normal /= norm

        # Make normal point "up" (positive z component)
        if normal[2] < 0:
            normal = -normal

        d = -np.dot(normal, p1)

        # Count inliers
        distances = np.abs(np.dot(pts, normal) + d)
        inliers = np.sum(distances < distance_threshold)

        if inliers > best_inliers:
            best_inliers = inliers
            best_plane = (normal, d)

    return best_plane


def extract_clusters_as_boxes(
    pts: "np.ndarray",
    labels: "np.ndarray",
    min_height: float = 0.8,
    max_height: float = 2.5,
    min_width: float = 0.2,
    max_width: float = 1.2,
    min_points: int = 50
) -> List[Dict[str, Any]]:
    """
    Extract bounding boxes from clusters, filtering by human-like dimensions.
    """
    boxes = []
    unique_labels = np.unique(labels)

    for label in unique_labels:
        if label == -1:
            continue

        mask = labels == label
        cluster_pts = pts[mask]

        if len(cluster_pts) < min_points:
            continue

        # Compute bounding box
        min_pt = cluster_pts.min(axis=0)
        max_pt = cluster_pts.max(axis=0)
        size = max_pt - min_pt
        center = (min_pt + max_pt) / 2

        # Filter by dimensions (assuming Z is up)
        height = size[2]
        width = max(size[0], size[1])
        depth = min(size[0], size[1])

        # Check if dimensions are human-like
        if height < min_height or height > max_height:
            continue
        if width < min_width or width > max_width:
            continue
        if depth < min_width or depth > max_width:
            continue

        boxes.append({
            "center": center.tolist(),
            "size": size.tolist(),
            "point_count": len(cluster_pts),
        })

    return boxes


# =============================================================================
# Background Model (stateful)
# =============================================================================

class VoxelBackgroundModel:
    """
    Voxel-based background model.
    Learns static scene by tracking voxel occupancy counts.
    """

    def __init__(self, voxel_size: float = 0.1, threshold: int = 5, learning_frames: int = 30):
        self.voxel_size = voxel_size
        self.threshold = threshold
        self.learning_frames = learning_frames
        self.occupancy: Dict[tuple, int] = {}
        self.frame_count = 0

    def update(self, pts: "np.ndarray"):
        """Update background model with new frame."""
        voxels = voxel_hash(pts, self.voxel_size)
        unique_voxels = set(map(tuple, voxels))

        # Only update model during learning phase
        if self.frame_count < self.learning_frames:
            for v in unique_voxels:
                self.occupancy[v] = self.occupancy.get(v, 0) + 1
            self.frame_count += 1

    def get_foreground(self, pts: "np.ndarray") -> "np.ndarray":
        """
        Return mask of foreground points (not in static background).
        """
        if self.frame_count < self.learning_frames:
            # Still learning background, return nothing (mask everything out)
            return np.zeros(len(pts), dtype=bool)

        voxels = voxel_hash(pts, self.voxel_size)
        mask = np.zeros(len(pts), dtype=bool)

        # Normalize threshold by frame count
        norm_threshold = self.threshold

        for i, v in enumerate(map(tuple, voxels)):
            count = self.occupancy.get(v, 0)
            # If voxel hasn't been seen often, it's foreground
            occupancy_ratio = count / self.frame_count
            if occupancy_ratio < 0.7:  # Less than 70% of frames = foreground
                mask[i] = True

        return mask


# =============================================================================
# Tracker
# =============================================================================

class SimpleTracker:
    """
    Simple centroid-based tracker using Hungarian algorithm.
    Maintains persistent IDs across frames.
    """

    def __init__(self, max_distance: float = 1.5, max_age: int = 10):
        self.max_distance = max_distance
        self.max_age = max_age
        self.tracks: Dict[int, Dict[str, Any]] = {}
        self.next_id = 1

    def update(self, detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Match detections to existing tracks and assign IDs.
        Returns detections with 'id' field added.
        """
        if not detections:
            # Age out all tracks
            for tid in list(self.tracks.keys()):
                self.tracks[tid]["age"] += 1
                if self.tracks[tid]["age"] > self.max_age:
                    del self.tracks[tid]
            return []

        det_centers = np.array([d["center"] for d in detections])

        if not self.tracks:
            # No existing tracks, create new ones
            result = []
            for det in detections:
                det_with_id = dict(det)
                det_with_id["id"] = self.next_id
                self.tracks[self.next_id] = {
                    "center": det["center"],
                    "age": 0,
                }
                self.next_id += 1
                result.append(det_with_id)
            return result

        # Build cost matrix
        track_ids = list(self.tracks.keys())
        track_centers = np.array([self.tracks[tid]["center"] for tid in track_ids])

        cost_matrix = cdist(det_centers, track_centers)

        # Hungarian assignment
        row_ind, col_ind = linear_sum_assignment(cost_matrix)

        matched_dets = set()
        matched_tracks = set()
        result = []

        for r, c in zip(row_ind, col_ind):
            if cost_matrix[r, c] < self.max_distance:
                tid = track_ids[c]
                det_with_id = dict(detections[r])
                det_with_id["id"] = tid
                self.tracks[tid]["center"] = detections[r]["center"]
                self.tracks[tid]["age"] = 0
                matched_dets.add(r)
                matched_tracks.add(c)
                result.append(det_with_id)

        # Create new tracks for unmatched detections
        for i, det in enumerate(detections):
            if i not in matched_dets:
                det_with_id = dict(det)
                det_with_id["id"] = self.next_id
                self.tracks[self.next_id] = {
                    "center": det["center"],
                    "age": 0,
                }
                self.next_id += 1
                result.append(det_with_id)

        # Age unmatched tracks
        for c, tid in enumerate(track_ids):
            if c not in matched_tracks:
                self.tracks[tid]["age"] += 1
                if self.tracks[tid]["age"] > self.max_age:
                    del self.tracks[tid]

        return result


# =============================================================================
# Node Specs
# =============================================================================

DETECT_SPEC = NodeSpec(
    type="people.detect",
    display_name="Detect People",
    category="People Detection",
    description="Detect people in point cloud using background subtraction and clustering",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="point_cloud", type=t_pointcloud(), description="Input point cloud"),
        PortSpec(name="voxel_size", type=t_float(), default=0.1, description="Voxel size for background model (m)"),
        PortSpec(name="learning_frames", type=t_int(), default=30, description="Frames to learn background"),
        PortSpec(name="cluster_eps", type=t_float(), default=0.3, description="DBSCAN epsilon (m)"),
        PortSpec(name="min_cluster_points", type=t_int(), default=30, description="Minimum points per cluster"),
        PortSpec(name="min_height", type=t_float(), default=0.8, description="Minimum person height (m)"),
        PortSpec(name="max_height", type=t_float(), default=2.3, description="Maximum person height (m)"),
        PortSpec(name="ground_height", type=t_float(), default=0.0, description="Ground plane Z height (m)"),
        PortSpec(name="enable_tracking", type=t_boolean(), default=True, description="Enable ID tracking"),
        PortSpec(name="reset_background", type=t_boolean(), default=False, description="Reset background model"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_list(t_bbox3d()), description="List of detected person bounding boxes"),
        PortSpec(name="count", type=t_int(), description="Number of detected people"),
        PortSpec(name="foreground_cloud", type=t_pointcloud(), description="Foreground points only"),
    ],
)


CREATE_REGION_SPEC = NodeSpec(
    type="people.create_region",
    display_name="Create Region",
    category="People Detection",
    description="Create an occupancy counting region (cuboid)",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="name", type=t_string(), default="Region 1", description="Region name"),
        PortSpec(name="center_x", type=t_float(), default=0.0, description="Center X"),
        PortSpec(name="center_y", type=t_float(), default=0.0, description="Center Y"),
        PortSpec(name="center_z", type=t_float(), default=1.0, description="Center Z"),
        PortSpec(name="size_x", type=t_float(), default=3.0, description="Size X (width)"),
        PortSpec(name="size_y", type=t_float(), default=3.0, description="Size Y (depth)"),
        PortSpec(name="size_z", type=t_float(), default=2.5, description="Size Z (height)"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="region", type=t_region3d(), description="Occupancy region"),
    ],
)


COUNT_OCCUPANCY_SPEC = NodeSpec(
    type="people.count_occupancy",
    display_name="Count Occupancy",
    category="People Detection",
    description="Count how many detected people are in each region",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_list(t_bbox3d()), description="Detected person boxes"),
        PortSpec(name="regions", type=t_list(t_region3d()), description="Occupancy regions"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="counts", type=t_list(t_int()), description="Count per region"),
        PortSpec(name="total", type=t_int(), description="Total people across all regions"),
        PortSpec(name="summary", type=t_string(), description="Human-readable summary"),
    ],
)


VISUALIZE_SPEC = NodeSpec(
    type="people.visualize",
    display_name="Visualize Scene",
    category="People Detection",
    description="Create Scene3D for dashboard visualization with point cloud, boxes, and regions",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="point_cloud", type=t_pointcloud(), description="Point cloud to display"),
        PortSpec(name="detections", type=t_list(t_bbox3d()), description="Detected person boxes"),
        PortSpec(name="regions", type=t_list(t_region3d()), description="Occupancy regions"),
        PortSpec(name="counts", type=t_list(t_int()), default=[], description="Occupancy counts per region"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="scene", type=t_scene3d(), description="Scene3D for visualization widget"),
    ],
)


# =============================================================================
# Node Implementations
# =============================================================================

# Phase 2: stateful components live on the per-run ExecutionContext rather
# than module-level dicts. The keys below namespace them inside
# ctx.node_resources[self.id].
_BG_MODEL_KEY = "people.background_model"
_TRACKER_KEY = "people.tracker"


@register_node(DETECT_SPEC)
class DetectPeopleNode(NodeBase):
    """Detect people in point cloud."""

    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        if not HAS_DEPS:
            ctx.log("numpy/scipy not available")
            return {"control_out": None, "detections": [], "count": 0, "foreground_cloud": None}

        cloud = inputs.get("point_cloud")
        if not cloud or cloud.get("_type") != "PointCloud":
            return {"control_out": None, "detections": [], "count": 0, "foreground_cloud": None}

        # Decode point cloud
        if cloud.get("positions_b64"):
            pts = b64_to_f32(cloud["positions_b64"]).reshape(-1, 3)
        elif cloud.get("positions"):
            pts = np.array(cloud["positions"], dtype=np.float32)
        else:
            return {"control_out": None, "detections": [], "count": 0, "foreground_cloud": None}

        if len(pts) == 0:
            return {"control_out": None, "detections": [], "count": 0, "foreground_cloud": None}

        # Get parameters
        voxel_size = inputs.get("voxel_size", 0.1)
        learning_frames = inputs.get("learning_frames", 30)
        cluster_eps = inputs.get("cluster_eps", 0.3)
        min_cluster_points = inputs.get("min_cluster_points", 30)
        min_height = inputs.get("min_height", 0.8)
        max_height = inputs.get("max_height", 2.3)
        ground_height = inputs.get("ground_height", 0.0)
        enable_tracking = inputs.get("enable_tracking", True)
        reset_background = inputs.get("reset_background", False)

        # Phase 2: per-run state lives on the ExecutionContext.
        bucket = ctx.node_resources.setdefault(self.id, {})
        if reset_background or _BG_MODEL_KEY not in bucket:
            bucket[_BG_MODEL_KEY] = VoxelBackgroundModel(
                voxel_size=voxel_size, learning_frames=learning_frames
            )
        bg_model = bucket[_BG_MODEL_KEY]

        # Update parameters if changed
        if bg_model.learning_frames != learning_frames:
            bg_model.learning_frames = learning_frames

        # Update background and get foreground
        bg_model.update(pts)
        fg_mask = bg_model.get_foreground(pts)
        fg_pts = pts[fg_mask]

        ctx.log(f"Foreground points: {len(fg_pts)} / {len(pts)}")

        if len(fg_pts) < min_cluster_points:
            fg_cloud = {
                "_type": "PointCloud",
                "num_points": len(fg_pts),
                "positions_b64": f32_to_b64(fg_pts.flatten()) if len(fg_pts) > 0 else "",
            }
            return {"control_out": None, "detections": [], "count": 0, "foreground_cloud": fg_cloud}

        # Height-based filtering (remove ground and ceiling)
        height_mask = (fg_pts[:, 2] > ground_height + 0.1) & (fg_pts[:, 2] < ground_height + max_height + 0.2)
        filtered_pts = fg_pts[height_mask]

        ctx.log(f"Height-filtered points: {len(filtered_pts)}")

        if len(filtered_pts) < min_cluster_points:
            fg_cloud = {
                "_type": "PointCloud",
                "num_points": len(fg_pts),
                "positions_b64": f32_to_b64(fg_pts.flatten()),
            }
            return {"control_out": None, "detections": [], "count": 0, "foreground_cloud": fg_cloud}

        # Cluster foreground points
        labels = dbscan_cluster(filtered_pts, eps=cluster_eps, min_samples=min_cluster_points // 3)

        # Extract human-like boxes
        boxes = extract_clusters_as_boxes(
            filtered_pts,
            labels,
            min_height=min_height,
            max_height=max_height,
            min_points=min_cluster_points,
        )

        ctx.log(f"Detected clusters: {len(boxes)}")

        # Tracking
        if enable_tracking:
            if _TRACKER_KEY not in bucket:
                bucket[_TRACKER_KEY] = SimpleTracker()
            tracker = bucket[_TRACKER_KEY]
            boxes = tracker.update(boxes)
        else:
            # Assign sequential IDs
            for i, box in enumerate(boxes):
                box["id"] = i + 1

        # Build foreground cloud
        fg_cloud = {
            "_type": "PointCloud",
            "num_points": len(fg_pts),
            "positions_b64": f32_to_b64(fg_pts.flatten()),
        }

        return {
            "control_out": None,
            "detections": boxes,
            "count": len(boxes),
            "foreground_cloud": fg_cloud,
        }


@register_node(CREATE_REGION_SPEC)
class CreateRegionNode(NodeBase):
    """Create an occupancy counting region."""

    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        region = {
            "name": inputs.get("name", "Region"),
            "center": [
                inputs.get("center_x", 0.0),
                inputs.get("center_y", 0.0),
                inputs.get("center_z", 1.0),
            ],
            "size": [
                inputs.get("size_x", 3.0),
                inputs.get("size_y", 3.0),
                inputs.get("size_z", 2.5),
            ],
        }
        return {"control_out": None, "region": region}


@register_node(COUNT_OCCUPANCY_SPEC)
class CountOccupancyNode(NodeBase):
    """Count people in regions."""

    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        detections = inputs.get("detections", [])
        regions = inputs.get("regions", [])

        if not regions:
            return {"control_out": None, "counts": [], "total": len(detections), "summary": f"Total: {len(detections)} people"}

        counts = []
        summary_parts = []

        for region in regions:
            rc = np.array(region["center"])
            rs = np.array(region["size"])
            half = rs / 2

            count = 0
            for det in detections:
                dc = np.array(det["center"])
                # Check if detection center is inside region
                if np.all(np.abs(dc - rc) < half):
                    count += 1

            counts.append(count)
            summary_parts.append(f"{region['name']}: {count}")

        total = sum(counts)
        summary = " | ".join(summary_parts) + f" | Total: {total}"

        return {"control_out": None, "counts": counts, "total": total, "summary": summary}


@register_node(VISUALIZE_SPEC)
class VisualizeSceneNode(NodeBase):
    """Create Scene3D for dashboard visualization."""

    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        point_cloud = inputs.get("point_cloud", {})
        detections = inputs.get("detections", [])
        regions = inputs.get("regions", [])
        counts = inputs.get("counts", [])

        # Ensure regions is a list
        if regions and not isinstance(regions, list):
            regions = [regions]

        scene = {
            "_type": "Scene3D",
            "point_cloud": point_cloud,
            "boxes": detections,
            "regions": regions,
            "occupancy": counts,
        }

        return {"control_out": None, "scene": scene}


# =============================================================================
# Merge Regions Node
# =============================================================================

MERGE_REGIONS_SPEC = NodeSpec(
    type="people.merge_regions",
    display_name="Merge Regions",
    category="People Detection",
    description="Combine multiple regions into a single list",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="region_1", type=t_region3d(), description="First region"),
        PortSpec(name="region_2", type=t_region3d(), description="Second region"),
        PortSpec(name="region_3", type=t_region3d(), description="Third region (optional)"),
        PortSpec(name="region_4", type=t_region3d(), description="Fourth region (optional)"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="regions", type=t_list(t_region3d()), description="List of regions"),
    ],
)


@register_node(MERGE_REGIONS_SPEC)
class MergeRegionsNode(NodeBase):
    """Combine multiple regions into a list."""

    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        regions = []
        for key in ["region_1", "region_2", "region_3", "region_4"]:
            region = inputs.get(key)
            if region and isinstance(region, dict) and "center" in region:
                regions.append(region)
        return {"control_out": None, "regions": regions}


def register():
    """Plugin registration function."""
    # Nodes are auto-registered via @register_node decorator
    pass
