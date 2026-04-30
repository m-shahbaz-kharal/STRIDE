"""
Seed STRIDE demo pipelines into the database.

Idempotent: re-running this script updates demos in place (matched by exact
name) instead of duplicating them. Existing non-demo graphs (e.g. the
``FL511`` graph saved by the user) are never touched.

Usage::

    cd backend
    uv run python scripts/seed_demo_graphs.py

The script targets the user ``test@test.com``. Override via ``SEED_USER_EMAIL``
environment variable if needed.

Each demo is built from a small DSL (see :func:`make_node` / :func:`make_edge`)
that references node IDs and port names verified against the live registry on
startup — if any referenced node/port is missing the script aborts before
writing.
"""

from __future__ import annotations

import os
import sys
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

# Make sure ``app`` is importable when running ``python scripts/seed_demo_graphs.py``.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_THIS_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.db import SessionLocal  # noqa: E402
from app.models import Graph, User  # noqa: E402
from app.nodes import list_node_definitions  # noqa: E402
from app.domain.graph_migrations import CURRENT_SCHEMA_VERSION, migrate  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("seed")


SEED_USER_EMAIL = os.getenv("SEED_USER_EMAIL", "test@test.com")
DEMO_NAME_PREFIX = "Demo · "  # "Demo · "

# Stable image URL — Ultralytics' bus.jpg is widely used and very stable.
SAMPLE_IMAGE_URL = "https://ultralytics.com/images/bus.jpg"


# ---------------------------------------------------------------------------
# Registry-backed helpers
# ---------------------------------------------------------------------------

def _load_registry() -> Dict[str, Dict[str, Any]]:
    defs = list_node_definitions()
    return {d["node_type"]: d for d in defs}


REGISTRY: Dict[str, Dict[str, Any]] = _load_registry()


def _check_node(node_type: str) -> Dict[str, Any]:
    if node_type not in REGISTRY:
        raise SystemExit(
            f"Seed script references unknown node type '{node_type}' — "
            f"check the live registry has it registered."
        )
    return REGISTRY[node_type]


def make_node(
    node_id: str,
    node_type: str,
    x: int,
    y: int,
    *,
    inputs: Optional[Dict[str, Any]] = None,
    width: int = 280,
    height: int = 140,
) -> Dict[str, Any]:
    """Build a ``BlueprintNodeData``-shaped node dict using the live spec.

    ``inputs`` provides literal values for unwired input ports. Each key must
    correspond to an actual input-port name on the node, otherwise we abort
    (catches typos that would silently get dropped at runtime).
    """
    spec = _check_node(node_type)
    valid_inputs = {p["name"] for p in spec.get("inputs", [])}
    inputs = inputs or {}
    for name in inputs:
        if name not in valid_inputs:
            raise SystemExit(
                f"Node '{node_id}' ({node_type}): inputValue '{name}' not "
                f"in spec inputs {sorted(valid_inputs)}"
            )
    return {
        "id": node_id,
        "type": "blueprint",
        "position": {"x": x, "y": y},
        "data": {
            "displayName": spec.get("display_name") or node_type,
            "nodeType": node_type,
            "description": spec.get("description") or spec.get("summary") or "",
            "input_ports": list(spec.get("input_ports", [])),
            "output_ports": list(spec.get("output_ports", [])),
            "input_port_types": spec.get("input_port_types") or {},
            "output_port_types": spec.get("output_port_types") or {},
            "params": {},
            "inputValues": inputs,
            "cacheEnabled": True,
        },
        "width": width,
        "height": height,
    }


def make_edge(
    src_node: str,
    src_port: str,
    tgt_node: str,
    tgt_port: str,
    *,
    nodes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build an edge dict, validating the ports exist on both endpoints."""
    by_id = {n["id"]: n for n in nodes}
    if src_node not in by_id:
        raise SystemExit(f"Edge source node '{src_node}' not in graph")
    if tgt_node not in by_id:
        raise SystemExit(f"Edge target node '{tgt_node}' not in graph")
    src_outs = set(by_id[src_node]["data"]["output_ports"])
    tgt_ins = set(by_id[tgt_node]["data"]["input_ports"])
    if src_port not in src_outs:
        raise SystemExit(
            f"Edge {src_node}.{src_port} -> {tgt_node}.{tgt_port}: "
            f"source port '{src_port}' not in {sorted(src_outs)}"
        )
    if tgt_port not in tgt_ins:
        raise SystemExit(
            f"Edge {src_node}.{src_port} -> {tgt_node}.{tgt_port}: "
            f"target port '{tgt_port}' not in {sorted(tgt_ins)}"
        )
    # Use the same shape the frontend produces. The editor registers
    # CustomEdge under the "default" key (App.tsx: `edgeTypes = { default: CustomEdge }`),
    # so leaving `type` unset (or setting it to "default") is what ReactFlow expects.
    return {
        "id": f"e-{src_node}-{src_port}-{tgt_node}-{tgt_port}",
        "source": src_node,
        "target": tgt_node,
        "sourceHandle": src_port,
        "targetHandle": tgt_port,
        "type": "default",
    }


def widget(
    wid: str,
    *,
    type: str,
    x: int,
    y: int,
    w: int,
    h: int,
    label: Optional[str] = None,
    node_id: Optional[str] = None,
    port_name: Optional[str] = None,
    input_type: Optional[str] = None,
    composition: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "id": wid,
        "type": type,
        "x": x,
        "y": y,
        "w": w,
        "h": h,
        "style": {},
    }
    if label is not None:
        out["label"] = label
    if node_id is not None:
        out["nodeId"] = node_id
    if port_name is not None:
        out["portName"] = port_name
    if input_type is not None:
        out["inputType"] = input_type
    if composition is not None:
        out["composition"] = composition
    return out


def make_graph_data(
    nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    *,
    widgets: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "nodes": nodes,
        "edges": edges,
        "ui": {
            "leftPanelCollapsed": False,
            "rightPanelCollapsed": False,
            "leftPanelWidth": 260,
            "rightPanelWidth": 340,
        },
        "dashboard": {
            "widgets": widgets,
            "viewport": {"x": 0, "y": 0, "w": 1600, "h": 900},
        },
    }


# ---------------------------------------------------------------------------
# Demo builders
# ---------------------------------------------------------------------------


def demo_01_yolo_clip() -> Tuple[str, str, Dict[str, Any]]:
    """Image -> YOLO detect + CLIP classify."""
    name = f"{DEMO_NAME_PREFIX}01 — YOLO Detection + CLIP Classify"
    desc = (
        "Loads a sample image from a URL (Ultralytics' bus.jpg), runs it "
        "through YOLOv11n object detection AND CLIP zero-shot classification "
        "in parallel. Click Run; the dashboard shows the annotated image with "
        "boxes plus the top-K CLIP class scores. First run downloads weights "
        "(~6 MB YOLO, ~150 MB CLIP) so it may take a moment."
    )
    nodes: List[Dict[str, Any]] = [
        make_node("start", "core.control.start", 100, 200),
        make_node("url", "core.image.load", 380, 200,
                  inputs={"file_path": SAMPLE_IMAGE_URL}),
        make_node("yolo", "image.detect.yolo", 720, 100,
                  inputs={"weights": "yolo11n.pt", "confidence": 0.3,
                          "iou": 0.45, "image_size": 640, "annotate": True}),
        make_node("clip", "image.classify.clip", 720, 320,
                  inputs={"prompts": "a photo of a person, a photo of a bus, "
                                     "a photo of a car, a photo of a dog"}),
    ]
    edges = [
        make_edge("start", "control_out", "url", "control_in", nodes=nodes),
        make_edge("url", "control_out", "yolo", "control_in", nodes=nodes),
        make_edge("url", "image", "yolo", "image", nodes=nodes),
        make_edge("yolo", "control_out", "clip", "control_in", nodes=nodes),
        make_edge("url", "image", "clip", "image", nodes=nodes),
    ]
    widgets = [
        widget("w-title", type="label", x=20, y=20, w=520, h=40,
               label="Demo 01 — YOLO + CLIP"),
        widget("w-img-orig", type="bound-output", x=20, y=80, w=320, h=240,
               label="Source image", node_id="url", port_name="image",
               input_type="image"),
        widget("w-img-detected", type="bound-output", x=360, y=80, w=420, h=320,
               label="YOLO detections (annotated)", node_id="yolo",
               port_name="image", input_type="image"),
        widget("w-yolo-count", type="bound-output", x=800, y=80, w=200, h=80,
               label="Detection count", node_id="yolo", port_name="count",
               input_type="int"),
        widget("w-clip-top", type="bound-output", x=800, y=180, w=320, h=80,
               label="CLIP top label", node_id="clip", port_name="top_label",
               input_type="string"),
        widget("w-clip-scores", type="bound-output", x=800, y=280, w=320, h=160,
               label="CLIP scores", node_id="clip", port_name="results",
               input_type="any"),
    ]
    return name, desc, make_graph_data(nodes, edges, widgets=widgets)


def demo_02_tracking_loop() -> Tuple[str, str, Dict[str, Any]]:
    """For-loop: each frame is the same URL image, but ByteTrack still
    exercises across iterations and you see track_ids appear."""
    name = f"{DEMO_NAME_PREFIX}02 — Object Tracking (YOLO + ByteTrack loop)"
    desc = (
        "Loops 10 times: each iteration loads the sample image, runs YOLO, "
        "and feeds detections to ByteTrack. Because we re-load the same image "
        "the tracker quickly locks IDs onto stable detections. Demonstrates "
        "(a) the for-loop control node, (b) tracker state across iterations, "
        "and (c) the cancel button — click Stop mid-run and confirm the "
        "execution terminates cleanly. Replace the URL with a video frame "
        "stream for real-world tracking."
    )
    nodes: List[Dict[str, Any]] = [
        make_node("start", "core.control.start", 100, 200),
        make_node("loop", "core.control.for", 380, 200,
                  inputs={"first_index": 0, "last_index": 9}),
        make_node("url", "core.image.load", 720, 200,
                  inputs={"file_path": SAMPLE_IMAGE_URL}),
        make_node("yolo", "image.detect.yolo", 1060, 200,
                  inputs={"weights": "yolo11n.pt", "confidence": 0.3,
                          "iou": 0.45, "annotate": False}),
        make_node("track", "tracker.bytetrack", 1400, 200,
                  inputs={"track_activation_threshold": 0.25,
                          "lost_track_buffer": 30,
                          "minimum_matching_threshold": 0.8,
                          "frame_rate": 30, "annotate": True}),
    ]
    edges = [
        make_edge("start", "control_out", "loop", "control_in", nodes=nodes),
        make_edge("loop", "loop_body", "url", "control_in", nodes=nodes),
        make_edge("url", "control_out", "yolo", "control_in", nodes=nodes),
        make_edge("url", "image", "yolo", "image", nodes=nodes),
        make_edge("yolo", "control_out", "track", "control_in", nodes=nodes),
        make_edge("yolo", "detections", "track", "detections", nodes=nodes),
        make_edge("url", "image", "track", "image", nodes=nodes),
    ]
    widgets = [
        widget("w-title", type="label", x=20, y=20, w=520, h=40,
               label="Demo 02 — YOLO + ByteTrack (10-frame loop)"),
        widget("w-iter", type="bound-output", x=20, y=80, w=200, h=80,
               label="Loop index", node_id="loop", port_name="index",
               input_type="int"),
        widget("w-tracked", type="bound-output", x=240, y=80, w=520, h=400,
               label="ByteTrack annotated frame", node_id="track",
               port_name="image", input_type="image"),
        widget("w-track-count", type="bound-output", x=780, y=80, w=200, h=80,
               label="Tracked objects", node_id="track", port_name="count",
               input_type="int"),
        widget("w-track-ids", type="bound-output", x=780, y=180, w=200, h=200,
               label="Track IDs", node_id="track", port_name="track_ids",
               input_type="any"),
    ]
    return name, desc, make_graph_data(nodes, edges, widgets=widgets)


def demo_03_depth() -> Tuple[str, str, Dict[str, Any]]:
    name = f"{DEMO_NAME_PREFIX}03 — Monocular Depth + 3D Point Cloud"
    desc = (
        "Loads an image, estimates per-pixel depth with Depth Anything V2 "
        "(small), then projects into a 3D point cloud using default pinhole "
        "intrinsics (fx=fy=525, cx/cy auto). Dashboard shows the source "
        "image, the depth heatmap, and the resulting point cloud in the 3D "
        "scene visualizer. First run downloads the Depth Anything weights "
        "(~110 MB) from HuggingFace."
    )
    nodes: List[Dict[str, Any]] = [
        make_node("start", "core.control.start", 100, 200),
        make_node("url", "core.image.load", 380, 200,
                  inputs={"file_path": SAMPLE_IMAGE_URL}),
        make_node("depth", "image.depth.depth_anything", 720, 200,
                  inputs={"colormap": "inferno", "visualize": True}),
        make_node("topc", "convert.depth.to_pointcloud", 1060, 200,
                  inputs={"fx": 525.0, "fy": 525.0, "cx": -1.0, "cy": -1.0,
                          "min_depth": 0.05, "max_depth": 50.0, "step": 2}),
        make_node("subsample", "convert.pointcloud.subsample", 1400, 200,
                  inputs={"strategy": "random", "max_points": 30000}),
    ]
    edges = [
        make_edge("start", "control_out", "url", "control_in", nodes=nodes),
        make_edge("url", "control_out", "depth", "control_in", nodes=nodes),
        make_edge("url", "image", "depth", "image", nodes=nodes),
        make_edge("depth", "control_out", "topc", "control_in", nodes=nodes),
        make_edge("depth", "depth", "topc", "depth", nodes=nodes),
        make_edge("topc", "control_out", "subsample", "control_in", nodes=nodes),
        make_edge("topc", "point_cloud", "subsample", "point_cloud", nodes=nodes),
    ]
    widgets = [
        widget("w-title", type="label", x=20, y=20, w=520, h=40,
               label="Demo 03 — Depth-Anything + Point Cloud"),
        widget("w-orig", type="bound-output", x=20, y=80, w=320, h=240,
               label="Source", node_id="url", port_name="image",
               input_type="image"),
        widget("w-depth-heat", type="bound-output", x=360, y=80, w=320, h=240,
               label="Depth heatmap", node_id="depth", port_name="image",
               input_type="image"),
        widget("w-pc-count", type="bound-output", x=700, y=80, w=200, h=80,
               label="Point count", node_id="subsample",
               port_name="num_points", input_type="int"),
        widget("w-pc-3d", type="bound-output", x=20, y=340, w=900, h=380,
               label="3D point cloud", node_id="subsample",
               port_name="point_cloud", input_type="pointcloud"),
    ]
    return name, desc, make_graph_data(nodes, edges, widgets=widgets)


def demo_04_lidar_people() -> Tuple[str, str, Dict[str, Any]]:
    """LIDAR people detection. We synthesize a point cloud by depth->pc.

    There's no PCD file loader in the registry, but we can approximate a
    LIDAR-style point cloud from depth-anything output. This is described
    honestly in the demo description.
    """
    name = f"{DEMO_NAME_PREFIX}04 — People Detection from Point Cloud"
    desc = (
        "Density-based people detection on a 3D point cloud. NOTE: there is "
        "no raw .pcd loader in the current registry, so we synthesize an "
        "approximate point cloud from a single image via Depth-Anything -> "
        "convert.depth.to_pointcloud. The cloud is then fed into "
        "people.detect (DBSCAN-style clustering after voxel-grid background "
        "subtraction) and tracker.kalman3d. Dashboard shows the foreground "
        "cloud + detection counts. For real LIDAR data, replace the depth "
        "branch with an Ouster source (ouster.open_source -> "
        "ouster.get_frame) plus a pcap+metadata pair."
    )
    nodes: List[Dict[str, Any]] = [
        make_node("start", "core.control.start", 100, 200),
        make_node("url", "core.image.load", 380, 200,
                  inputs={"file_path": SAMPLE_IMAGE_URL}),
        make_node("depth", "image.depth.depth_anything", 720, 200,
                  inputs={"visualize": False}),
        make_node("topc", "convert.depth.to_pointcloud", 1060, 200,
                  inputs={"fx": 525.0, "fy": 525.0, "step": 2,
                          "min_depth": 0.5, "max_depth": 30.0}),
        make_node("people", "people.detect", 1400, 200,
                  inputs={"voxel_size": 0.2, "learning_frames": 1,
                          "cluster_eps": 0.5, "min_cluster_points": 20,
                          "min_height": 0.6, "max_height": 2.5,
                          "ground_height": 0.0, "enable_tracking": True,
                          "reset_background": False}),
        make_node("kalman", "tracker.kalman3d", 1740, 200,
                  inputs={"max_distance": 2.0, "max_age": 10,
                          "min_hits": 1, "dt": 0.1, "reset": False}),
        make_node("viz", "people.visualize", 1740, 420),
    ]
    edges = [
        make_edge("start", "control_out", "url", "control_in", nodes=nodes),
        make_edge("url", "control_out", "depth", "control_in", nodes=nodes),
        make_edge("url", "image", "depth", "image", nodes=nodes),
        make_edge("depth", "control_out", "topc", "control_in", nodes=nodes),
        make_edge("depth", "depth", "topc", "depth", nodes=nodes),
        make_edge("topc", "control_out", "people", "control_in", nodes=nodes),
        make_edge("topc", "point_cloud", "people", "point_cloud", nodes=nodes),
        make_edge("people", "control_out", "kalman", "control_in", nodes=nodes),
        # tracker.kalman3d expects 'boxes' (list)
        make_edge("people", "detections", "kalman", "boxes", nodes=nodes),
        make_edge("people", "control_out", "viz", "control_in", nodes=nodes),
        make_edge("people", "foreground_cloud", "viz", "point_cloud", nodes=nodes),
        make_edge("people", "detections", "viz", "detections", nodes=nodes),
    ]
    widgets = [
        widget("w-title", type="label", x=20, y=20, w=600, h=40,
               label="Demo 04 — People Detection (synthetic point cloud)"),
        widget("w-orig", type="bound-output", x=20, y=80, w=300, h=200,
               label="Source", node_id="url", port_name="image",
               input_type="image"),
        widget("w-depth", type="bound-output", x=340, y=80, w=300, h=200,
               label="Depth", node_id="depth", port_name="image",
               input_type="image"),
        widget("w-pcount", type="bound-output", x=660, y=80, w=200, h=80,
               label="People detected", node_id="people", port_name="count",
               input_type="int"),
        widget("w-tcount", type="bound-output", x=660, y=180, w=200, h=80,
               label="Tracked", node_id="kalman", port_name="count",
               input_type="int"),
        widget("w-scene", type="bound-output", x=20, y=300, w=900, h=400,
               label="Scene (foreground + tracks)", node_id="viz",
               port_name="scene", input_type="scene3d"),
    ]
    return name, desc, make_graph_data(nodes, edges, widgets=widgets)


def demo_05_grounding_dino() -> Tuple[str, str, Dict[str, Any]]:
    name = f"{DEMO_NAME_PREFIX}05 — Open-Vocabulary Detection (Grounding DINO)"
    desc = (
        "Open-vocabulary detection: provide a free-text prompt and Grounding "
        "DINO finds matching regions. Prompt is 'a person. a bus. a traffic "
        "light.' — edit the text_prompt input on the grounding-dino node "
        "to try anything. First run downloads ~700 MB of weights from "
        "HuggingFace; subsequent runs are cached."
    )
    nodes: List[Dict[str, Any]] = [
        make_node("start", "core.control.start", 100, 200),
        make_node("url", "core.image.load", 380, 200,
                  inputs={"file_path": SAMPLE_IMAGE_URL}),
        make_node("dino", "image.detect.grounding_dino", 720, 200,
                  inputs={"text_prompt": "a person. a bus. a traffic light.",
                          "box_threshold": 0.35, "text_threshold": 0.25,
                          "annotate": True}),
    ]
    edges = [
        make_edge("start", "control_out", "url", "control_in", nodes=nodes),
        make_edge("url", "control_out", "dino", "control_in", nodes=nodes),
        make_edge("url", "image", "dino", "image", nodes=nodes),
    ]
    widgets = [
        widget("w-title", type="label", x=20, y=20, w=520, h=40,
               label="Demo 05 — Grounding DINO"),
        widget("w-orig", type="bound-output", x=20, y=80, w=320, h=240,
               label="Source", node_id="url", port_name="image",
               input_type="image"),
        widget("w-out", type="bound-output", x=360, y=80, w=520, h=380,
               label="Open-vocab detections", node_id="dino",
               port_name="image", input_type="image"),
        widget("w-cnt", type="bound-output", x=900, y=80, w=200, h=80,
               label="Detections", node_id="dino", port_name="count",
               input_type="int"),
    ]
    return name, desc, make_graph_data(nodes, edges, widgets=widgets)


def demo_06_pose() -> Tuple[str, str, Dict[str, Any]]:
    name = f"{DEMO_NAME_PREFIX}06 — Pose Estimation (MediaPipe BlazePose)"
    desc = (
        "33-point body pose estimation via MediaPipe BlazePose. The annotated "
        "image overlays the skeleton; the keypoints output is a structured "
        "list you can wire into downstream conversion nodes. First run "
        "downloads MediaPipe model assets (~5 MB)."
    )
    nodes: List[Dict[str, Any]] = [
        make_node("start", "core.control.start", 100, 200),
        make_node("url", "core.image.load", 380, 200,
                  inputs={"file_path": SAMPLE_IMAGE_URL}),
        make_node("pose", "image.pose.mediapipe", 720, 200,
                  inputs={"model_complexity": 1, "num_poses": 4,
                          "min_detection_confidence": 0.5, "annotate": True}),
    ]
    edges = [
        make_edge("start", "control_out", "url", "control_in", nodes=nodes),
        make_edge("url", "control_out", "pose", "control_in", nodes=nodes),
        make_edge("url", "image", "pose", "image", nodes=nodes),
    ]
    widgets = [
        widget("w-title", type="label", x=20, y=20, w=520, h=40,
               label="Demo 06 — MediaPipe Pose"),
        widget("w-orig", type="bound-output", x=20, y=80, w=320, h=240,
               label="Source", node_id="url", port_name="image",
               input_type="image"),
        widget("w-out", type="bound-output", x=360, y=80, w=520, h=380,
               label="Pose overlay", node_id="pose", port_name="image",
               input_type="image"),
        widget("w-cnt", type="bound-output", x=900, y=80, w=200, h=80,
               label="People found", node_id="pose", port_name="count",
               input_type="int"),
        widget("w-kp", type="bound-output", x=900, y=180, w=320, h=300,
               label="Keypoints (raw)", node_id="pose", port_name="keypoints",
               input_type="keypoints"),
    ]
    return name, desc, make_graph_data(nodes, edges, widgets=widgets)


def demo_07_converters() -> Tuple[str, str, Dict[str, Any]]:
    name = f"{DEMO_NAME_PREFIX}07 — Type-Conversion Showcase"
    desc = (
        "Chains several convert.* nodes to demonstrate the type system. "
        "Pipeline: load image -> YOLO detect -> crop the first detection's "
        "bbox -> grayscale -> back to RGB. Also branches into depth -> "
        "point cloud -> subsample to show 2D and 3D conversions. Each step's "
        "output is shown on the dashboard so you can see types flow."
    )
    nodes: List[Dict[str, Any]] = [
        make_node("start", "core.control.start", 100, 220),
        make_node("url", "core.image.load", 380, 220,
                  inputs={"file_path": SAMPLE_IMAGE_URL}),
        make_node("yolo", "image.detect.yolo", 720, 100,
                  inputs={"weights": "yolo11n.pt", "confidence": 0.3,
                          "annotate": False}),
        make_node("first", "convert.list.to_first", 1060, 100,
                  inputs={}),
        make_node("crop", "convert.bbox.crop_image", 1400, 100,
                  inputs={}),  # bbox input gets first detection's box
        make_node("gray", "convert.image.to_grayscale", 1740, 100,
                  inputs={}),
        make_node("rgb", "convert.image.from_grayscale_to_rgb", 2080, 100,
                  inputs={}),
        # 3D branch
        make_node("depth", "image.depth.depth_anything", 720, 380,
                  inputs={"visualize": False}),
        make_node("topc", "convert.depth.to_pointcloud", 1060, 380,
                  inputs={"step": 4}),
        make_node("sub", "convert.pointcloud.subsample", 1400, 380,
                  inputs={"strategy": "voxel", "voxel_size": 0.1,
                          "max_points": 20000}),
    ]
    edges = [
        make_edge("start", "control_out", "url", "control_in", nodes=nodes),
        make_edge("url", "control_out", "yolo", "control_in", nodes=nodes),
        make_edge("url", "image", "yolo", "image", nodes=nodes),
        make_edge("yolo", "control_out", "first", "control_in", nodes=nodes),
        make_edge("yolo", "boxes", "first", "items", nodes=nodes),
        make_edge("first", "control_out", "crop", "control_in", nodes=nodes),
        make_edge("url", "image", "crop", "image", nodes=nodes),
        make_edge("first", "value", "crop", "bbox", nodes=nodes),
        make_edge("crop", "control_out", "gray", "control_in", nodes=nodes),
        make_edge("crop", "image", "gray", "image", nodes=nodes),
        make_edge("gray", "control_out", "rgb", "control_in", nodes=nodes),
        make_edge("gray", "image", "rgb", "image", nodes=nodes),
        # 3D branch
        make_edge("url", "control_out", "depth", "control_in", nodes=nodes),
        make_edge("url", "image", "depth", "image", nodes=nodes),
        make_edge("depth", "control_out", "topc", "control_in", nodes=nodes),
        make_edge("depth", "depth", "topc", "depth", nodes=nodes),
        make_edge("topc", "control_out", "sub", "control_in", nodes=nodes),
        make_edge("topc", "point_cloud", "sub", "point_cloud", nodes=nodes),
    ]
    widgets = [
        widget("w-title", type="label", x=20, y=20, w=600, h=40,
               label="Demo 07 — Conversion chain"),
        widget("w-orig", type="bound-output", x=20, y=80, w=240, h=180,
               label="Original", node_id="url", port_name="image",
               input_type="image"),
        widget("w-crop", type="bound-output", x=280, y=80, w=240, h=180,
               label="Cropped bbox", node_id="crop", port_name="image",
               input_type="image"),
        widget("w-gray", type="bound-output", x=540, y=80, w=240, h=180,
               label="Grayscale", node_id="gray", port_name="image",
               input_type="image"),
        widget("w-rgb", type="bound-output", x=800, y=80, w=240, h=180,
               label="Promoted to RGB", node_id="rgb", port_name="image",
               input_type="image"),
        widget("w-pc", type="bound-output", x=20, y=280, w=540, h=400,
               label="Subsampled point cloud", node_id="sub",
               port_name="point_cloud", input_type="pointcloud"),
        widget("w-pcnt", type="bound-output", x=580, y=280, w=200, h=80,
               label="Subsampled count", node_id="sub", port_name="num_points",
               input_type="int"),
    ]
    return name, desc, make_graph_data(nodes, edges, widgets=widgets)


def demo_08_cancel_loop() -> Tuple[str, str, Dict[str, Any]]:
    name = f"{DEMO_NAME_PREFIX}08 — Cancellation Demo (infinite loop)"
    desc = (
        "Intentionally infinite while-loop. Each iteration increments a "
        "counter and adds a small delay so you can watch it tick. Click Run, "
        "then click Stop — the Phase 1 cancellation fix means the loop "
        "should terminate cleanly within ~250 ms. Dashboard shows the live "
        "counter."
    )
    nodes: List[Dict[str, Any]] = [
        make_node("start", "core.control.start", 100, 200),
        # Declare counter before the loop
        make_node("decl", "core.var.declare", 380, 200,
                  inputs={"name": "counter", "value": 0}),
        # While true
        make_node("cond", "core.literal.boolean", 380, 380,
                  inputs={"value": True}),
        make_node("loop", "core.control.while", 660, 200, inputs={}),
        # Body: read, +1, write
        make_node("get", "core.var.get", 940, 200,
                  inputs={"name": "counter", "default": 0}),
        make_node("one", "core.literal.int", 940, 380, inputs={"value": 1}),
        make_node("add", "core.math.add", 1220, 200, inputs={}),
        make_node("set", "core.var.set", 1500, 200,
                  inputs={"name": "counter"}),
        make_node("delay", "core.time.delay", 1780, 200,
                  inputs={"seconds": 0.2}),
    ]
    edges = [
        make_edge("start", "control_out", "decl", "control_in", nodes=nodes),
        make_edge("decl", "control_out", "loop", "control_in", nodes=nodes),
        make_edge("cond", "value", "loop", "condition", nodes=nodes),
        make_edge("loop", "loop_body", "get", "control_in", nodes=nodes),
        make_edge("get", "control_out", "add", "control_in", nodes=nodes),
        make_edge("get", "value", "add", "a", nodes=nodes),
        make_edge("one", "value", "add", "b", nodes=nodes),
        make_edge("add", "control_out", "set", "control_in", nodes=nodes),
        make_edge("add", "sum", "set", "value", nodes=nodes),
        make_edge("set", "control_out", "delay", "control_in", nodes=nodes),
    ]
    widgets = [
        widget("w-title", type="label", x=20, y=20, w=520, h=40,
               label="Demo 08 — Click Run, then Stop"),
        widget("w-instr", type="label", x=20, y=80, w=600, h=40,
               label="Loop runs forever — expect cancellation in <=250ms."),
        widget("w-counter", type="bound-output", x=20, y=140, w=300, h=120,
               label="Counter (live)", node_id="set", port_name="value",
               input_type="any"),
        widget("w-iter", type="bound-output", x=340, y=140, w=200, h=120,
               label="Loop index", node_id="loop", port_name="index",
               input_type="int"),
    ]
    return name, desc, make_graph_data(nodes, edges, widgets=widgets)


def demo_09_multimodal() -> Tuple[str, str, Dict[str, Any]]:
    name = f"{DEMO_NAME_PREFIX}09 — Multi-Modal: 2D Detection + Depth + 3D Tracking"
    desc = (
        "Combines monocular depth and 2D detection. The image is run through "
        "YOLO (2D boxes) and Depth-Anything in parallel; depth is converted "
        "to a point cloud, and people.detect (or simply the 3D bbox tracker) "
        "creates 3D tracks. Dashboard shows both modalities side-by-side."
    )
    nodes: List[Dict[str, Any]] = [
        make_node("start", "core.control.start", 100, 220),
        make_node("url", "core.image.load", 380, 220,
                  inputs={"file_path": SAMPLE_IMAGE_URL}),
        make_node("yolo", "image.detect.yolo", 720, 100,
                  inputs={"weights": "yolo11n.pt", "confidence": 0.3,
                          "annotate": True}),
        make_node("track2d", "tracker.bytetrack", 1060, 100,
                  inputs={"track_activation_threshold": 0.25, "annotate": True}),
        make_node("depth", "image.depth.depth_anything", 720, 380,
                  inputs={"visualize": True}),
        make_node("topc", "convert.depth.to_pointcloud", 1060, 380,
                  inputs={"step": 2, "min_depth": 0.5, "max_depth": 30.0}),
        make_node("sub", "convert.pointcloud.subsample", 1400, 380,
                  inputs={"strategy": "random", "max_points": 30000}),
    ]
    edges = [
        make_edge("start", "control_out", "url", "control_in", nodes=nodes),
        make_edge("url", "control_out", "yolo", "control_in", nodes=nodes),
        make_edge("url", "image", "yolo", "image", nodes=nodes),
        make_edge("yolo", "control_out", "track2d", "control_in", nodes=nodes),
        make_edge("yolo", "detections", "track2d", "detections", nodes=nodes),
        make_edge("url", "image", "track2d", "image", nodes=nodes),
        make_edge("url", "control_out", "depth", "control_in", nodes=nodes),
        make_edge("url", "image", "depth", "image", nodes=nodes),
        make_edge("depth", "control_out", "topc", "control_in", nodes=nodes),
        make_edge("depth", "depth", "topc", "depth", nodes=nodes),
        make_edge("topc", "control_out", "sub", "control_in", nodes=nodes),
        make_edge("topc", "point_cloud", "sub", "point_cloud", nodes=nodes),
    ]
    widgets = [
        widget("w-title", type="label", x=20, y=20, w=600, h=40,
               label="Demo 09 — Multi-modal scene"),
        widget("w-track2d", type="bound-output", x=20, y=80, w=460, h=320,
               label="2D tracking", node_id="track2d", port_name="image",
               input_type="image"),
        widget("w-depth", type="bound-output", x=500, y=80, w=300, h=240,
               label="Depth", node_id="depth", port_name="image",
               input_type="image"),
        widget("w-pc", type="bound-output", x=20, y=420, w=780, h=320,
               label="3D scene", node_id="sub", port_name="point_cloud",
               input_type="pointcloud"),
        widget("w-2dcnt", type="bound-output", x=820, y=80, w=200, h=80,
               label="2D tracked", node_id="track2d", port_name="count",
               input_type="int"),
        widget("w-pccnt", type="bound-output", x=820, y=180, w=200, h=80,
               label="Cloud points", node_id="sub", port_name="num_points",
               input_type="int"),
    ]
    return name, desc, make_graph_data(nodes, edges, widgets=widgets)


def demo_10_hello() -> Tuple[str, str, Dict[str, Any]]:
    name = f"{DEMO_NAME_PREFIX}10 — Hello World (smoke test)"
    desc = (
        "Trivial graph for a quick smoke test: emit two integer literals, "
        "add them, send the result to the Display tab. Click Run — "
        "expect Display['Main']['Sum'] == 7. Useful for checking the "
        "engine, websocket events, and dashboard wiring without "
        "downloading any model weights."
    )
    nodes: List[Dict[str, Any]] = [
        make_node("start", "core.control.start", 100, 220),
        make_node("a", "core.literal.int", 380, 120, inputs={"value": 3}),
        make_node("b", "core.literal.int", 380, 320, inputs={"value": 4}),
        make_node("add", "core.math.add", 660, 220, inputs={}),
        make_node("disp", "general.to_display", 940, 220,
                  inputs={"section": "Main", "title": "Sum"}),
    ]
    edges = [
        make_edge("start", "control_out", "add", "control_in", nodes=nodes),
        make_edge("a", "value", "add", "a", nodes=nodes),
        make_edge("b", "value", "add", "b", nodes=nodes),
        make_edge("add", "control_out", "disp", "control_in", nodes=nodes),
        make_edge("add", "sum", "disp", "value", nodes=nodes),
    ]
    widgets = [
        widget("w-title", type="label", x=20, y=20, w=460, h=40,
               label="Demo 10 — Hello world"),
        widget("w-sum", type="bound-output", x=20, y=80, w=300, h=120,
               label="Sum", node_id="add", port_name="sum", input_type="any"),
    ]
    return name, desc, make_graph_data(nodes, edges, widgets=widgets)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


DEMO_BUILDERS = [
    demo_01_yolo_clip,
    demo_02_tracking_loop,
    demo_03_depth,
    demo_04_lidar_people,
    demo_05_grounding_dino,
    demo_06_pose,
    demo_07_converters,
    demo_08_cancel_loop,
    demo_09_multimodal,
    demo_10_hello,
]


def main() -> int:
    log.info("Loaded %d nodes from registry", len(REGISTRY))

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(email=SEED_USER_EMAIL).first()
        if user is None:
            log.error("User %s not found", SEED_USER_EMAIL)
            return 2
        log.info("Seeding under user %s (%s)", user.email, user.id)

        before = db.query(Graph).filter_by(owner_id=user.id).count()
        log.info("User has %d graphs before seeding", before)

        created = 0
        updated = 0
        for builder in DEMO_BUILDERS:
            name, desc, data = builder()
            # Sanity-check by running the migration plumbing on the dict.
            migrated = migrate(data)
            assert migrated.get("schema_version") == CURRENT_SCHEMA_VERSION

            existing = (
                db.query(Graph)
                .filter_by(owner_id=user.id, name=name)
                .one_or_none()
            )
            if existing is None:
                g = Graph(
                    owner_id=user.id,
                    name=name,
                    description=desc,
                    data=data,
                )
                db.add(g)
                created += 1
                log.info("CREATED: %s  (%d nodes, %d edges, %d widgets)",
                         name, len(data["nodes"]), len(data["edges"]),
                         len(data["dashboard"]["widgets"]))
            else:
                existing.description = desc
                existing.data = data
                updated += 1
                log.info("UPDATED: %s  (%d nodes, %d edges, %d widgets)",
                         name, len(data["nodes"]), len(data["edges"]),
                         len(data["dashboard"]["widgets"]))

        db.commit()

        after = db.query(Graph).filter_by(owner_id=user.id).count()
        log.info("\nDone. created=%d updated=%d before=%d after=%d",
                 created, updated, before, after)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
