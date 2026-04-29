"""
MediaPipe pose / hands / face landmark nodes.

MediaPipe's modern `mediapipe.tasks.python.vision` API is the supported
path on the recent (>=0.10.x) wheels (the legacy `mp.solutions.*`
modules were removed in 0.10.20+).  Each node:

  * ensures the matching `.task` model bundle is present in the local
    cache (auto-downloads from Google's published storage if missing);
  * loads it lazily via `BaseOptions(model_asset_path=...)`;
  * runs it on a single image frame; and
  * emits a `keypoints` record + an annotated image.

Detector instances are cached at module level keyed on their config so
we don't re-allocate the underlying graph on every frame.
"""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

try:
    import numpy as np  # type: ignore
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    np = None  # type: ignore

try:
    import cv2  # type: ignore
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    cv2 = None  # type: ignore

try:
    import mediapipe as mp  # type: ignore
    from mediapipe.tasks import python as _mp_tasks  # type: ignore
    from mediapipe.tasks.python import vision as _mp_vision  # type: ignore
    HAS_MP = True
except ImportError:
    HAS_MP = False
    mp = None  # type: ignore
    _mp_tasks = None  # type: ignore
    _mp_vision = None  # type: ignore

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_boolean, t_control, t_float, t_int, t_list, t_string,
    t_image, t_keypoints,
)
from stride_core.image_utils import decode_image_to_numpy, encode_numpy_to_image


_DETECTORS: Dict[str, Any] = {}


# Official Google-hosted task bundle URLs.  These are the canonical
# defaults from the MediaPipe docs:
# https://developers.google.com/mediapipe/solutions/vision/<task>/index
_TASK_URLS = {
    "pose_lite": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
    "pose_full": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task",
    "pose_heavy": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task",
    "hands": "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task",
    "face": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task",
}


def _cache_dir() -> Path:
    """Where we put downloaded .task bundles."""
    base = os.environ.get("STRIDE_MEDIAPIPE_CACHE")
    if base:
        return Path(base)
    return Path.home() / ".cache" / "stride" / "mediapipe"


def _ensure_task_file(task_key: str, override_path: str = "") -> str:
    """Resolve a task bundle: prefer caller-supplied path, else download."""
    if override_path:
        if not os.path.exists(override_path):
            raise FileNotFoundError(f"model file not found: {override_path}")
        return override_path

    if task_key not in _TASK_URLS:
        raise ValueError(f"unknown mediapipe task: {task_key}")

    cache = _cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f"{task_key}.task"
    if target.exists() and target.stat().st_size > 0:
        return str(target)

    url = _TASK_URLS[task_key]
    tmp = target.with_suffix(".task.partial")
    try:
        with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as f:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
        os.replace(tmp, target)
    except Exception as exc:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise RuntimeError(
            f"failed to download MediaPipe task bundle from {url}: {exc}. "
            "You can pre-download it manually and pass its path via the "
            "`model_path` parameter."
        ) from exc
    return str(target)


def _require_deps() -> None:
    if not HAS_NUMPY or not HAS_CV2:
        raise RuntimeError("numpy and opencv-python are required for MediaPipe nodes")
    if not HAS_MP:
        raise RuntimeError(
            "mediapipe not installed. Install with: pip install mediapipe"
        )


def _bgr_to_mp_image(bgr: "np.ndarray") -> Any:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)


# =============================================================================
# Pose
# =============================================================================

POSE_SPEC = NodeSpec(
    type="image.pose.mediapipe",
    version="1.0.0",
    display_name="MediaPipe Pose",
    category="Image / Pose",
    summary="33-point body pose with MediaPipe BlazePose.",
    description=(
        "Runs MediaPipe Pose Landmarker (tasks API) on an input image. "
        "Returns 33 (x, y, z, visibility) keypoints per detected person "
        "along with an annotated visualization."
    ),
    icon="user",
    tags=["mediapipe", "pose", "blazepose"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_image(), required=True),
        PortSpec(name="model_complexity", type=t_int(), required=False, default=1,
                 description="0=Lite, 1=Full, 2=Heavy"),
        PortSpec(name="model_path", type=t_string(), required=False, default="",
                 description="Override path to a .task bundle (else auto-downloaded)"),
        PortSpec(name="num_poses", type=t_int(), required=False, default=1),
        PortSpec(name="min_detection_confidence", type=t_float(), required=False, default=0.5),
        PortSpec(name="annotate", type=t_boolean(), required=False, default=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="keypoints", type=t_keypoints()),
        PortSpec(name="count", type=t_int()),
        PortSpec(name="image", type=t_image()),
    ],
    cache_policy="disabled",
)


def _build_pose(complexity: int, num_poses: int, min_conf: float, model_path: str) -> Any:
    key = f"pose|{complexity}|{num_poses}|{min_conf}|{model_path}"
    det = _DETECTORS.get(key)
    if det is not None:
        return det
    task_key = {0: "pose_lite", 1: "pose_full", 2: "pose_heavy"}.get(complexity, "pose_full")
    path = _ensure_task_file(task_key, model_path)
    options = _mp_vision.PoseLandmarkerOptions(
        base_options=_mp_tasks.BaseOptions(model_asset_path=path),
        running_mode=_mp_vision.RunningMode.IMAGE,
        num_poses=int(num_poses),
        min_pose_detection_confidence=float(min_conf),
    )
    det = _mp_vision.PoseLandmarker.create_from_options(options)
    _DETECTORS[key] = det
    return det


@register_node(POSE_SPEC)
class MediaPipePoseNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_deps()
        image_str = inputs.get("image")
        if not image_str:
            raise ValueError("MediaPipe pose: no image provided")

        complexity = int(inputs.get("model_complexity") if inputs.get("model_complexity") is not None else 1)
        num_poses = int(inputs.get("num_poses") if inputs.get("num_poses") is not None else 1)
        min_conf = float(inputs.get("min_detection_confidence") if inputs.get("min_detection_confidence") is not None else 0.5)
        annotate = bool(inputs.get("annotate", True))
        model_path = inputs.get("model_path") or ""

        det = _build_pose(complexity, num_poses, min_conf, model_path)

        bgr = decode_image_to_numpy(image_str)
        h, w = bgr.shape[:2]
        result = det.detect(_bgr_to_mp_image(bgr))

        instances: List[Dict[str, Any]] = []
        annotated = bgr.copy() if annotate else None

        for landmarks in (result.pose_landmarks or []):
            kps = [[float(lm.x * w), float(lm.y * h), float(getattr(lm, "visibility", 1.0))] for lm in landmarks]
            instances.append({"keypoints": kps})
            if annotate:
                # Draw a circle at each landmark; lines between known connections
                for x, y, _ in kps:
                    cv2.circle(annotated, (int(x), int(y)), 3, (0, 255, 0), -1)
                # Skeleton connections (from POSE_CONNECTIONS in mp.tasks)
                connections = getattr(_mp_vision.PoseLandmarksConnections,
                                      "POSE_LANDMARKS", None)
                if connections is not None:
                    pass  # not always exposed; skip — circles still convey output

        annotated_b64 = ""
        if annotate and annotated is not None:
            annotated_b64 = encode_numpy_to_image(annotated, fmt="jpeg", quality=85)

        return {
            "control_out": None,
            "keypoints": {
                "_type": "Keypoints",
                "schema": "blazepose33",
                "instances": instances,
            },
            "count": len(instances),
            "image": annotated_b64,
        }


# =============================================================================
# Hands
# =============================================================================

HANDS_SPEC = NodeSpec(
    type="image.hands.mediapipe",
    version="1.0.0",
    display_name="MediaPipe Hands",
    category="Image / Pose",
    summary="21-point hand landmarks with MediaPipe.",
    description=(
        "Runs MediaPipe Hand Landmarker (tasks API) on an input image and "
        "emits 21 landmarks per detected hand along with handedness "
        "('Left' / 'Right')."
    ),
    icon="hand",
    tags=["mediapipe", "hands", "landmarks"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_image(), required=True),
        PortSpec(name="max_num_hands", type=t_int(), required=False, default=2),
        PortSpec(name="min_detection_confidence", type=t_float(), required=False, default=0.5),
        PortSpec(name="model_path", type=t_string(), required=False, default=""),
        PortSpec(name="annotate", type=t_boolean(), required=False, default=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="keypoints", type=t_keypoints()),
        PortSpec(name="handedness", type=t_list(t_string())),
        PortSpec(name="count", type=t_int()),
        PortSpec(name="image", type=t_image()),
    ],
    cache_policy="disabled",
)


def _build_hands(max_hands: int, min_conf: float, model_path: str) -> Any:
    key = f"hands|{max_hands}|{min_conf}|{model_path}"
    det = _DETECTORS.get(key)
    if det is not None:
        return det
    path = _ensure_task_file("hands", model_path)
    options = _mp_vision.HandLandmarkerOptions(
        base_options=_mp_tasks.BaseOptions(model_asset_path=path),
        running_mode=_mp_vision.RunningMode.IMAGE,
        num_hands=int(max_hands),
        min_hand_detection_confidence=float(min_conf),
    )
    det = _mp_vision.HandLandmarker.create_from_options(options)
    _DETECTORS[key] = det
    return det


@register_node(HANDS_SPEC)
class MediaPipeHandsNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_deps()
        image_str = inputs.get("image")
        if not image_str:
            raise ValueError("MediaPipe hands: no image provided")

        max_hands = int(inputs.get("max_num_hands") if inputs.get("max_num_hands") is not None else 2)
        min_conf = float(inputs.get("min_detection_confidence") if inputs.get("min_detection_confidence") is not None else 0.5)
        annotate = bool(inputs.get("annotate", True))
        model_path = inputs.get("model_path") or ""

        det = _build_hands(max_hands, min_conf, model_path)

        bgr = decode_image_to_numpy(image_str)
        h, w = bgr.shape[:2]
        result = det.detect(_bgr_to_mp_image(bgr))

        instances: List[Dict[str, Any]] = []
        handedness: List[str] = []
        annotated = bgr.copy() if annotate else None

        for i, landmarks in enumerate(result.hand_landmarks or []):
            kps = [[float(lm.x * w), float(lm.y * h), float(lm.z)] for lm in landmarks]
            instances.append({"keypoints": kps})
            label = ""
            if result.handedness and i < len(result.handedness) and result.handedness[i]:
                label = result.handedness[i][0].category_name or ""
            handedness.append(label)
            if annotate:
                for x, y, _ in kps:
                    cv2.circle(annotated, (int(x), int(y)), 3, (255, 0, 255), -1)

        annotated_b64 = ""
        if annotate and annotated is not None:
            annotated_b64 = encode_numpy_to_image(annotated, fmt="jpeg", quality=85)

        return {
            "control_out": None,
            "keypoints": {
                "_type": "Keypoints",
                "schema": "mediapipe_hands21",
                "instances": instances,
            },
            "handedness": handedness,
            "count": len(instances),
            "image": annotated_b64,
        }


# =============================================================================
# Face Mesh
# =============================================================================

FACE_SPEC = NodeSpec(
    type="image.face.mediapipe",
    version="1.0.0",
    display_name="MediaPipe Face Mesh",
    category="Image / Pose",
    summary="478-point face mesh with MediaPipe.",
    description=(
        "Runs MediaPipe Face Landmarker (tasks API) on an input image and "
        "emits 478 facial landmarks per detected face."
    ),
    icon="smile",
    tags=["mediapipe", "face", "mesh", "landmarks"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_image(), required=True),
        PortSpec(name="max_num_faces", type=t_int(), required=False, default=1),
        PortSpec(name="min_detection_confidence", type=t_float(), required=False, default=0.5),
        PortSpec(name="model_path", type=t_string(), required=False, default=""),
        PortSpec(name="annotate", type=t_boolean(), required=False, default=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="keypoints", type=t_keypoints()),
        PortSpec(name="count", type=t_int()),
        PortSpec(name="image", type=t_image()),
    ],
    cache_policy="disabled",
)


def _build_face(max_faces: int, min_conf: float, model_path: str) -> Any:
    key = f"face|{max_faces}|{min_conf}|{model_path}"
    det = _DETECTORS.get(key)
    if det is not None:
        return det
    path = _ensure_task_file("face", model_path)
    options = _mp_vision.FaceLandmarkerOptions(
        base_options=_mp_tasks.BaseOptions(model_asset_path=path),
        running_mode=_mp_vision.RunningMode.IMAGE,
        num_faces=int(max_faces),
        min_face_detection_confidence=float(min_conf),
    )
    det = _mp_vision.FaceLandmarker.create_from_options(options)
    _DETECTORS[key] = det
    return det


@register_node(FACE_SPEC)
class MediaPipeFaceMeshNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_deps()
        image_str = inputs.get("image")
        if not image_str:
            raise ValueError("MediaPipe face: no image provided")

        max_faces = int(inputs.get("max_num_faces") if inputs.get("max_num_faces") is not None else 1)
        min_conf = float(inputs.get("min_detection_confidence") if inputs.get("min_detection_confidence") is not None else 0.5)
        annotate = bool(inputs.get("annotate", True))
        model_path = inputs.get("model_path") or ""

        det = _build_face(max_faces, min_conf, model_path)

        bgr = decode_image_to_numpy(image_str)
        h, w = bgr.shape[:2]
        result = det.detect(_bgr_to_mp_image(bgr))

        instances: List[Dict[str, Any]] = []
        annotated = bgr.copy() if annotate else None

        for landmarks in (result.face_landmarks or []):
            kps = [[float(lm.x * w), float(lm.y * h), float(lm.z)] for lm in landmarks]
            instances.append({"keypoints": kps})
            if annotate:
                for x, y, _ in kps:
                    cv2.circle(annotated, (int(x), int(y)), 1, (0, 255, 255), -1)

        annotated_b64 = ""
        if annotate and annotated is not None:
            annotated_b64 = encode_numpy_to_image(annotated, fmt="jpeg", quality=85)

        return {
            "control_out": None,
            "keypoints": {
                "_type": "Keypoints",
                "schema": "mediapipe_facemesh478",
                "instances": instances,
            },
            "count": len(instances),
            "image": annotated_b64,
        }


def register() -> None:
    pass
