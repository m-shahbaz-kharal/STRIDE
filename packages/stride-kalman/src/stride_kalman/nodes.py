"""
Kalman-filter / Hungarian 3D multi-object tracker.

Constant-velocity Kalman per track (state = [x, y, z, vx, vy, vz]),
greedy Hungarian assignment on Mahalanobis or Euclidean centroid
distance.  Pattern matches AB3DMOT (Weng & Kitani, IROS 2020) — the
canonical baseline for 3D MOT on KITTI/nuScenes.

Phase 2: tracker state lives on the ExecutionContext (per-run, per-node).
Two consecutive runs always start with a fresh state — no cross-run ID
leakage. ``reset=True`` still forces a fresh state mid-run.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    import numpy as np  # type: ignore
    from scipy.optimize import linear_sum_assignment  # type: ignore
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False
    np = None  # type: ignore
    linear_sum_assignment = None  # type: ignore

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.errors import NodeMissingDependencyError
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_boolean, t_control, t_float, t_int, t_list,
    t_bbox3d, t_detections3d,
)


_TRACKER_STATE_KEY = "kalman3d.state"


def _require_deps() -> None:
    if not HAS_DEPS:
        raise NodeMissingDependencyError(
            "numpy and scipy are required for the Kalman tracker"
        )


class _KalmanTrack:
    """Constant-velocity Kalman filter on 3D centroid.

    State: x = [cx, cy, cz, vx, vy, vz]^T   (size 6)
    """

    def __init__(self, init_center: "np.ndarray", track_id: int, dt: float = 0.1):
        self.id = track_id
        self.dt = dt
        self.x = np.zeros(6, dtype=np.float64)
        self.x[:3] = init_center
        # Process & measurement covariances
        self.P = np.eye(6) * 10.0
        self.Q = np.eye(6) * 0.5  # process noise
        self.R = np.eye(3) * 0.5  # measurement noise
        self.age = 0
        self.hits = 1
        self.time_since_update = 0
        # Latest associated detection record (for output)
        self.last_record: Optional[Dict[str, Any]] = None

    def _F(self) -> "np.ndarray":
        F = np.eye(6)
        F[0, 3] = self.dt
        F[1, 4] = self.dt
        F[2, 5] = self.dt
        return F

    def predict(self) -> "np.ndarray":
        F = self._F()
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + self.Q
        self.age += 1
        self.time_since_update += 1
        return self.x[:3].copy()

    def update(self, measurement: "np.ndarray") -> None:
        H = np.zeros((3, 6))
        H[:3, :3] = np.eye(3)
        z = measurement.reshape(3)
        y = z - H @ self.x
        S = H @ self.P @ H.T + self.R
        K = self.P @ H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        self.P = (np.eye(6) - K @ H) @ self.P
        self.hits += 1
        self.time_since_update = 0

    @property
    def center(self) -> "np.ndarray":
        return self.x[:3]


KALMAN3D_SPEC = NodeSpec(
    type="tracker.kalman3d",
    version="1.0.0",
    display_name="Kalman 3D Tracker",
    category="Tracking",
    summary="3D multi-object tracker (Kalman + Hungarian).",
    description=(
        "Constant-velocity Kalman filter per track + Hungarian assignment "
        "on 3D centroid distance.  Matches the AB3DMOT (Weng & Kitani, "
        "IROS 2020) reference baseline used by KITTI / nuScenes."
    ),
    icon="git-branch",
    tags=["tracking", "kalman", "ab3dmot", "3d"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="boxes", type=t_list(t_bbox3d()), required=True,
                 description="3D bounding-box detections from a 3D detector"),
        PortSpec(name="max_distance", type=t_float(), required=False, default=2.0,
                 description="Max centroid distance (m) for association",
                 constraints={"min": 0.0}),
        PortSpec(name="max_age", type=t_int(), required=False, default=10,
                 description="Drop a track after this many frames without update",
                 constraints={"min": 0}),
        PortSpec(name="min_hits", type=t_int(), required=False, default=2,
                 description="Suppress brand-new tracks until they have this many hits",
                 constraints={"min": 0}),
        PortSpec(name="dt", type=t_float(), required=False, default=0.1,
                 description="Time delta between frames (s)",
                 constraints={"min": 0.0}),
        PortSpec(name="reset", type=t_boolean(), required=False, default=False),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="boxes", type=t_list(t_bbox3d()),
                 description="Detections with persistent track ids assigned to `id`"),
        PortSpec(name="count", type=t_int()),
    ],
    cache_policy="disabled",
)


@register_node(KALMAN3D_SPEC)
class Kalman3DTrackerNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_deps()

        boxes: List[Dict[str, Any]] = list(inputs.get("boxes") or [])
        try:
            max_distance = float(inputs.get("max_distance") if inputs.get("max_distance") is not None else 2.0)
        except (TypeError, ValueError):
            max_distance = 2.0
        try:
            max_age = int(inputs.get("max_age") if inputs.get("max_age") is not None else 10)
        except (TypeError, ValueError):
            max_age = 10
        try:
            min_hits = int(inputs.get("min_hits") if inputs.get("min_hits") is not None else 2)
        except (TypeError, ValueError):
            min_hits = 2
        try:
            dt = float(inputs.get("dt") if inputs.get("dt") is not None else 0.1)
        except (TypeError, ValueError):
            dt = 0.1
        reset = bool(inputs.get("reset", False))

        # Phase 2: state lives on the per-run ExecutionContext rather than a
        # module-level dict. Two consecutive runs always start fresh, and
        # ``reset=True`` still rebuilds mid-run.
        bucket = ctx.node_resources.setdefault(self.id, {})
        if reset or _TRACKER_STATE_KEY not in bucket:
            bucket[_TRACKER_STATE_KEY] = {"tracks": [], "next_id": 1}
        state = bucket[_TRACKER_STATE_KEY]

        # Predict step for all existing tracks
        for trk in state["tracks"]:
            trk.predict()

        # Build assignment cost matrix (M tracks × N detections)
        det_centers = np.array([b["center"] for b in boxes], dtype=np.float64) if boxes else np.zeros((0, 3))
        track_centers = np.array([t.center for t in state["tracks"]], dtype=np.float64) if state["tracks"] else np.zeros((0, 3))

        assigned_dets: set = set()
        assigned_tracks: set = set()

        if len(det_centers) and len(track_centers):
            # Pairwise distance
            diff = track_centers[:, None, :] - det_centers[None, :, :]
            cost = np.linalg.norm(diff, axis=-1)
            # Hungarian
            row_ind, col_ind = linear_sum_assignment(cost)
            for r, c in zip(row_ind, col_ind):
                if cost[r, c] <= max_distance:
                    state["tracks"][r].update(det_centers[c])
                    state["tracks"][r].last_record = boxes[c]
                    assigned_tracks.add(r)
                    assigned_dets.add(c)

        # Spawn new tracks for unassigned detections
        for c, det in enumerate(boxes):
            if c in assigned_dets:
                continue
            new_id = state["next_id"]
            state["next_id"] += 1
            trk = _KalmanTrack(np.asarray(det["center"], dtype=np.float64), new_id, dt=dt)
            trk.last_record = det
            state["tracks"].append(trk)

        # Reap stale tracks
        state["tracks"] = [t for t in state["tracks"] if t.time_since_update <= max_age]

        # Build output detections — only emit tracks that have at least min_hits
        out_boxes: List[Dict[str, Any]] = []
        for trk in state["tracks"]:
            if trk.hits < min_hits and trk.time_since_update > 0:
                continue  # not yet confirmed
            rec = dict(trk.last_record) if trk.last_record else {}
            rec["id"] = int(trk.id)
            rec["center"] = trk.center.tolist()
            rec["track_id"] = int(trk.id)
            out_boxes.append(rec)

        ctx.log(f"Kalman3D: {len(out_boxes)} confirmed tracks (active={len(state['tracks'])})")

        return {
            "control_out": None,
            "boxes": out_boxes,
            "count": len(out_boxes),
        }


def register() -> None:
    pass
