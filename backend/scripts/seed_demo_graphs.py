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


# Grid spacing for the auto-layout helper :func:`gp` below.
#
# The frontend (``BlueprintNode``) renders each node at:
#
#     width  = max(node["width"], MIN_NODE_WIDTH=260)
#     height = HEADER_HEIGHT(70) + maxPorts * PORT_ROW_HEIGHT(42)
#            + paramCount * PARAM_ROW_HEIGHT(26) + 8
#
# A high-fanout node like ``tracker.bytetrack`` (9 inputs / 6 outputs)
# therefore renders at ~456 px tall; ``traffic.events.annotate`` and
# ``image.detect.yolo`` are ~330 px tall. The grid spacing below leaves
# a ~50 px buffer below even the tallest node so no two nodes can ever
# visually overlap in the editor.
GRID_X0, GRID_Y0 = 60, 60
# col_w must beat the actual rendered node width (which often grows past
# the declared 280 once long display names + parameter widgets land).
# 540 gives a clean ~260 px clear gap between node edges horizontally.
# row_h beats the tallest node we register (~456 px for tracker.bytetrack
# with 9 ports) plus ~64 px of breathing room.
GRID_COL_W, GRID_ROW_H = 540, 520


def gp(col: int, row: int) -> Tuple[int, int]:
    """Return ``(x, y)`` for a node placed at ``(col, row)`` on the
    canonical demo-grid. Use as ``make_node("foo", "...", *gp(2, 1))``.
    """
    return GRID_X0 + col * GRID_COL_W, GRID_Y0 + row * GRID_ROW_H


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
        "End-to-end 3D pipeline: a single image is monocular-depth-estimated "
        "by Depth-Anything V2, the depth map is unprojected into a ~200k-point "
        "cloud, that cloud is fed through people.detect (DBSCAN clustering "
        "after voxel-grid background subtraction) and tracker.kalman3d. The "
        "dashboard's 3-D viewer shows the unprojected cloud and any detected "
        "person boxes. NOTE: people.detect does *temporal* background "
        "subtraction (it learns what's static across multiple frames). With a "
        "single synthetic frame nothing has a chance to look like foreground, "
        "so 0 detections is expected — the demo proves the wiring works "
        "end-to-end. For real detections, replace the depth branch with a "
        "streaming source like ouster.open_source -> ouster.get_frame "
        "(needs a pcap+metadata pair) and run the graph in a loop."
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
        # Show the FULL unprojected cloud in the 3D viewer rather than the
        # post-subtraction foreground (which is empty for a single frame —
        # background subtraction is temporal). Detection boxes still overlay
        # if any are produced upstream.
        make_edge("topc", "point_cloud", "viz", "point_cloud", nodes=nodes),
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


# ---------------------------------------------------------------------------
# Traffic demos — exercise the stride-traffic plugin
# ---------------------------------------------------------------------------


def demo_traffic_01_flow_metrics() -> Tuple[str, str, Dict[str, Any]]:
    """Live counting + classification + AADT/PHF/headway from FL511."""
    name = f"{DEMO_NAME_PREFIX}Traffic 01 — Live Counting + AADT / PHF / Headway"
    desc = (
        "End-to-end live counting pipeline. FL511 → image-decode → YOLO "
        "→ ByteTrack → traffic.count.line + traffic.count.classify. The "
        "counter's running ``total`` flows into traffic.flow.live_metrics "
        "for an extrapolated AADT and hourly rate. Its ``events`` stream "
        "feeds traffic.flow.live_phf (4×15-min rolling Peak-Hour Factor) "
        "and traffic.safety.headway_live (running mean / minimum / "
        "critical-headway tally). The annotated tracker frame is "
        "post-processed by traffic.events.annotate to overlay the virtual "
        "counting line and a severity-coloured border whenever a "
        "critical-headway event lands. If the FL511 'frame' node errors "
        "with a 404, the configured camera 2130 is offline — edit the "
        "``camera`` parameter on the ``connect`` node to any other active "
        "FL511 camera ID."
    )
    nodes: List[Dict[str, Any]] = [
        # Top pipeline (row 1): start → connect → loop → frame → decode → YOLO → track → count
        make_node("start", "core.control.start", *gp(0, 1)),
        make_node("connect", "fl511.connect", *gp(1, 1),
                  inputs={"camera": 2130, "fps": 10, "buffer_seconds": 4,
                          "refresh_minutes": 4}),
        make_node("loop", "core.control.for", *gp(2, 1),
                  inputs={"first_index": 0, "last_index": 29}),
        make_node("frame", "fl511.get_frame", *gp(3, 1),
                  inputs={"timeout": 5.0, "quality": 80,
                          "require_frame": True, "pace": True}),
        make_node("img_decode", "convert.image.from_url", *gp(4, 1),
                  inputs={"timeout": 5.0}),
        make_node("yolo", "image.detect.yolo", *gp(5, 1),
                  inputs={"weights": "yolo11n.pt", "confidence": 0.3,
                          "iou": 0.45, "annotate": False}),
        make_node("track", "tracker.bytetrack", *gp(6, 1),
                  inputs={"track_activation_threshold": 0.25,
                          "lost_track_buffer": 30,
                          "minimum_matching_threshold": 0.8,
                          "frame_rate": 10, "annotate": True}),
        make_node("count", "traffic.count.line", *gp(7, 1),
                  inputs={"reference": "bottom", "hysteresis_px": 2.0}),
        # ROI source (row 3, below the pipeline) → annot_lines (row 3, col 7)
        make_node("line", "traffic.roi.line", *gp(6, 3),
                  inputs={"name": "screen line",
                          "x1": 0, "y1": 240, "x2": 704, "y2": 240}),
        make_node("annot_lines", "traffic.roi.merge_lines", *gp(7, 3),
                  inputs={}),
        # Classification on row 2 below count
        make_node("classify", "traffic.count.classify", *gp(7, 2),
                  inputs={}),
        # Metrics column (col 8): live AADT, PHF, headway, severity filter
        make_node("live_metrics", "traffic.flow.live_metrics", *gp(8, 0),
                  inputs={"seasonal_factor": 1.0, "dow_factor": 1.0,
                          "axle_factor": 1.0}),
        make_node("live_phf", "traffic.flow.live_phf", *gp(8, 1),
                  inputs={"bin_seconds": 900.0,
                          "kind_filter": "line_cross"}),
        make_node("hd_live", "traffic.safety.headway_live", *gp(8, 2),
                  inputs={"kind_filter": "line_cross",
                          "max_samples": 4096}),
        make_node("hd_filter", "traffic.events.filter", *gp(8, 3),
                  inputs={"kind": "", "severity": "critical"}),
        # Annotator + dashboard widgets
        make_node("annotate", "traffic.events.annotate", *gp(9, 1),
                  inputs={"thickness": 2}),
        make_node("disp_frame", "general.to_display", *gp(10, 0),
                  inputs={"section": "Frame", "title": "Annotated"}),
        make_node("disp_total", "general.to_display", *gp(10, 1),
                  inputs={"section": "Counts", "title": "Total"}),
        make_node("disp_classes", "general.to_display", *gp(10, 2),
                  inputs={"section": "Counts", "title": "Per-class"}),
        make_node("disp_hd_mean", "general.to_display", *gp(10, 3),
                  inputs={"section": "Headway", "title": "Mean (s)"}),
        make_node("disp_hd_crit", "general.to_display", *gp(10, 4),
                  inputs={"section": "Headway", "title": "Critical (<1s)"}),
        make_node("disp_aadt", "general.to_display", *gp(11, 0),
                  inputs={"section": "Flow", "title": "AADT (extrapolated)"}),
        make_node("disp_hourly", "general.to_display", *gp(11, 1),
                  inputs={"section": "Flow", "title": "Hourly rate"}),
        make_node("disp_phf", "general.to_display", *gp(11, 2),
                  inputs={"section": "Flow", "title": "Live PHF"}),
        make_node("disp_hd_min", "general.to_display", *gp(11, 3),
                  inputs={"section": "Headway", "title": "Min (s)"}),
    ]
    edges = [
        # FL511 → frame → image → YOLO → ByteTrack
        make_edge("start", "control_out", "connect", "control_in", nodes=nodes),
        make_edge("connect", "control_out", "loop", "control_in", nodes=nodes),
        make_edge("loop", "loop_body", "frame", "control_in", nodes=nodes),
        make_edge("connect", "stream", "frame", "stream", nodes=nodes),
        make_edge("frame", "control_out", "img_decode", "control_in", nodes=nodes),
        make_edge("frame", "image", "img_decode", "url", nodes=nodes),
        make_edge("img_decode", "control_out", "yolo", "control_in", nodes=nodes),
        make_edge("img_decode", "image", "yolo", "image", nodes=nodes),
        make_edge("yolo", "control_out", "track", "control_in", nodes=nodes),
        make_edge("yolo", "detections", "track", "detections", nodes=nodes),
        make_edge("img_decode", "image", "track", "image", nodes=nodes),
        # Counting + classification
        make_edge("track", "control_out", "count", "control_in", nodes=nodes),
        make_edge("track", "detections", "count", "detections", nodes=nodes),
        make_edge("line", "line", "count", "line", nodes=nodes),
        make_edge("track", "control_out", "classify", "control_in", nodes=nodes),
        make_edge("track", "detections", "classify", "detections", nodes=nodes),
        # Live flow metrics from running total
        make_edge("count", "control_out", "live_metrics", "control_in",
                  nodes=nodes),
        make_edge("count", "total", "live_metrics", "count", nodes=nodes),
        # Live PHF + Headway from event stream
        make_edge("count", "control_out", "live_phf", "control_in", nodes=nodes),
        make_edge("count", "events", "live_phf", "events", nodes=nodes),
        make_edge("count", "control_out", "hd_live", "control_in", nodes=nodes),
        make_edge("count", "events", "hd_live", "events", nodes=nodes),
        # Severity overlay: pull only critical-severity events for the border
        make_edge("count", "control_out", "hd_filter", "control_in",
                  nodes=nodes),
        make_edge("count", "events", "hd_filter", "events", nodes=nodes),
        # Compose the line into a list for the annotator
        make_edge("line", "line", "annot_lines", "line_1", nodes=nodes),
        # Annotate
        make_edge("track", "control_out", "annotate", "control_in", nodes=nodes),
        make_edge("track", "image", "annotate", "image", nodes=nodes),
        make_edge("hd_filter", "events", "annotate", "events", nodes=nodes),
        make_edge("annot_lines", "lines", "annotate", "lines", nodes=nodes),
        # Displays
        make_edge("annotate", "control_out", "disp_frame",
                  "control_in", nodes=nodes),
        make_edge("annotate", "image", "disp_frame", "value", nodes=nodes),
        make_edge("count", "total", "disp_total", "value", nodes=nodes),
        make_edge("count", "control_out", "disp_total", "control_in",
                  nodes=nodes),
        make_edge("classify", "summary", "disp_classes", "value", nodes=nodes),
        make_edge("classify", "control_out", "disp_classes",
                  "control_in", nodes=nodes),
        make_edge("live_metrics", "aadt", "disp_aadt", "value", nodes=nodes),
        make_edge("live_metrics", "control_out", "disp_aadt",
                  "control_in", nodes=nodes),
        make_edge("live_metrics", "hourly_rate", "disp_hourly",
                  "value", nodes=nodes),
        make_edge("live_metrics", "control_out", "disp_hourly",
                  "control_in", nodes=nodes),
        make_edge("live_phf", "phf", "disp_phf", "value", nodes=nodes),
        make_edge("live_phf", "control_out", "disp_phf",
                  "control_in", nodes=nodes),
        make_edge("hd_live", "mean_s", "disp_hd_mean", "value", nodes=nodes),
        make_edge("hd_live", "control_out", "disp_hd_mean",
                  "control_in", nodes=nodes),
        make_edge("hd_live", "min_s", "disp_hd_min", "value", nodes=nodes),
        make_edge("hd_live", "control_out", "disp_hd_min",
                  "control_in", nodes=nodes),
        make_edge("hd_live", "critical_count", "disp_hd_crit",
                  "value", nodes=nodes),
        make_edge("hd_live", "control_out", "disp_hd_crit",
                  "control_in", nodes=nodes),
    ]
    widgets = [
        widget("w-title", type="label", x=20, y=20, w=700, h=40,
               label="Demo · Traffic 01 — Live Counting + Flow"),
        widget("w-frame", type="bound-output", x=20, y=80, w=480, h=320,
               label="Annotated frame", node_id="annotate",
               port_name="image", input_type="image"),
        widget("w-total", type="bound-output", x=520, y=80, w=200, h=80,
               label="Total count", node_id="count",
               port_name="total", input_type="int"),
        widget("w-class", type="bound-output", x=740, y=80, w=240, h=200,
               label="Per-class", node_id="classify",
               port_name="counts", input_type="any"),
        widget("w-aadt", type="bound-output", x=520, y=200, w=200, h=80,
               label="AADT (extrap.)", node_id="live_metrics",
               port_name="aadt", input_type="float"),
        widget("w-hourly", type="bound-output", x=520, y=320, w=200, h=80,
               label="Hourly rate", node_id="live_metrics",
               port_name="hourly_rate", input_type="float"),
        widget("w-phf", type="bound-output", x=20, y=420, w=240, h=80,
               label="Live PHF", node_id="live_phf",
               port_name="phf", input_type="float"),
        widget("w-hd-mean", type="bound-output", x=280, y=420, w=240, h=80,
               label="Mean headway (s)", node_id="hd_live",
               port_name="mean_s", input_type="float"),
        widget("w-hd-min", type="bound-output", x=540, y=420, w=240, h=80,
               label="Min headway (s)", node_id="hd_live",
               port_name="min_s", input_type="float"),
        widget("w-hd-crit", type="bound-output", x=800, y=420, w=240, h=80,
               label="Critical (<1s)", node_id="hd_live",
               port_name="critical_count", input_type="int"),
    ]
    return name, desc, make_graph_data(nodes, edges, widgets=widgets)


def demo_traffic_02_hsm_crash() -> Tuple[str, str, Dict[str, Any]]:
    """Live FL511 -> speed estimation -> density / v/c / fundamental diagram."""
    name = f"{DEMO_NAME_PREFIX}Traffic 02 — Live Speed + Density + v/c"
    desc = (
        "Wires per-track speed estimation onto the FL511 → YOLO → ByteTrack "
        "stack. ``traffic.calibration.from_known_width`` produces a "
        "TrafficCalibration record that ``traffic.speed.estimate`` uses to "
        "stamp every detection with km/h. The running 85th-/95th-percentile "
        "speeds come from ``traffic.speed.summary``. The hourly flow rate "
        "from a screen-line counter feeds ``traffic.flow.density`` "
        "(k = q / v_space-mean) and ``traffic.flow.capacity_vc``. Edit the "
        "``connect`` node's ``camera`` parameter if FL511 returns a 404 on "
        "the configured camera."
    )
    nodes: List[Dict[str, Any]] = [
        # Top pipeline (row 1): start → connect → loop → frame → decode → YOLO → track → speed → summary
        make_node("start", "core.control.start", *gp(0, 1)),
        make_node("connect", "fl511.connect", *gp(1, 1),
                  inputs={"camera": 2130, "fps": 10, "buffer_seconds": 4}),
        make_node("loop", "core.control.for", *gp(2, 1),
                  inputs={"first_index": 0, "last_index": 29}),
        make_node("frame", "fl511.get_frame", *gp(3, 1),
                  inputs={"timeout": 5.0, "quality": 80,
                          "require_frame": True, "pace": True}),
        make_node("img_decode", "convert.image.from_url", *gp(4, 1),
                  inputs={"timeout": 5.0}),
        make_node("yolo", "image.detect.yolo", *gp(5, 1),
                  inputs={"weights": "yolo11n.pt", "confidence": 0.3,
                          "iou": 0.45, "annotate": False}),
        make_node("track", "tracker.bytetrack", *gp(6, 1),
                  inputs={"track_activation_threshold": 0.25,
                          "lost_track_buffer": 30,
                          "minimum_matching_threshold": 0.8,
                          "frame_rate": 10, "annotate": True}),
        make_node("speed", "traffic.speed.estimate", *gp(7, 1),
                  inputs={"reference": "bottom", "ema_alpha": 0.4,
                          "window_s": 0.6, "store_key": "speed"}),
        make_node("speed_summary", "traffic.speed.summary", *gp(8, 1),
                  inputs={"max_samples": 5000}),
        # Calibration is computed once at run start (col 0, row 3 — out of pipeline path)
        make_node("cal", "traffic.calibration.from_known_width", *gp(0, 3),
                  inputs={"image_width": 704, "image_height": 480,
                          "point_a": [320, 360], "point_b": [400, 360],
                          "real_distance_m": 3.65}),
        # ROI + counting branch (row 3): line → annot_lines, count
        make_node("line", "traffic.roi.line", *gp(6, 3),
                  inputs={"name": "screen line",
                          "x1": 0, "y1": 240, "x2": 704, "y2": 240}),
        make_node("annot_lines", "traffic.roi.merge_lines", *gp(7, 3),
                  inputs={}),
        make_node("count", "traffic.count.line", *gp(7, 2),
                  inputs={"reference": "bottom", "hysteresis_px": 2.0}),
        make_node("live_metrics", "traffic.flow.live_metrics", *gp(8, 2),
                  inputs={}),
        # Density / v/c on row 2 (col 9), keeping a clear vertical for displays
        make_node("density", "traffic.flow.density", *gp(9, 2),
                  inputs={}),
        make_node("vc", "traffic.flow.capacity_vc", *gp(9, 3),
                  inputs={"capacity_vph": 2200.0}),
        # Annotator (col 9, row 1) and dashboard widgets (col 10-11)
        make_node("annotate", "traffic.events.annotate", *gp(9, 1),
                  inputs={"thickness": 2}),
        make_node("disp_frame", "general.to_display", *gp(10, 0),
                  inputs={"section": "Frame", "title": "Annotated"}),
        make_node("disp_mean", "general.to_display", *gp(10, 1),
                  inputs={"section": "Speed", "title": "Mean (km/h)"}),
        make_node("disp_p85", "general.to_display", *gp(11, 0),
                  inputs={"section": "Speed", "title": "85th %ile (km/h)"}),
        make_node("disp_dens", "general.to_display", *gp(10, 2),
                  inputs={"section": "Flow", "title": "Density (veh/km)"}),
        make_node("disp_vc", "general.to_display", *gp(10, 3),
                  inputs={"section": "Flow", "title": "v/c"}),
        make_node("disp_status", "general.to_display", *gp(11, 3),
                  inputs={"section": "Flow", "title": "Capacity status"}),
    ]
    edges = [
        # Calibration computed once; feeds speed.estimate
        make_edge("start", "control_out", "cal", "control_in", nodes=nodes),
        # FL511 → frame → image → YOLO → ByteTrack
        make_edge("start", "control_out", "connect", "control_in", nodes=nodes),
        make_edge("connect", "control_out", "loop", "control_in", nodes=nodes),
        make_edge("loop", "loop_body", "frame", "control_in", nodes=nodes),
        make_edge("connect", "stream", "frame", "stream", nodes=nodes),
        make_edge("frame", "control_out", "img_decode", "control_in", nodes=nodes),
        make_edge("frame", "image", "img_decode", "url", nodes=nodes),
        make_edge("img_decode", "control_out", "yolo", "control_in", nodes=nodes),
        make_edge("img_decode", "image", "yolo", "image", nodes=nodes),
        make_edge("yolo", "control_out", "track", "control_in", nodes=nodes),
        make_edge("yolo", "detections", "track", "detections", nodes=nodes),
        make_edge("img_decode", "image", "track", "image", nodes=nodes),
        # Speed estimation
        make_edge("track", "control_out", "speed", "control_in", nodes=nodes),
        make_edge("track", "detections", "speed", "detections", nodes=nodes),
        make_edge("cal", "calibration", "speed", "calibration", nodes=nodes),
        make_edge("speed", "control_out", "speed_summary", "control_in",
                  nodes=nodes),
        make_edge("speed", "speeds_kph", "speed_summary",
                  "speeds_kph", nodes=nodes),
        # Counter on the screen line
        make_edge("track", "control_out", "count", "control_in", nodes=nodes),
        make_edge("speed", "detections", "count", "detections", nodes=nodes),
        make_edge("line", "line", "count", "line", nodes=nodes),
        # Hourly rate from live_metrics
        make_edge("count", "control_out", "live_metrics", "control_in",
                  nodes=nodes),
        make_edge("count", "total", "live_metrics", "count", nodes=nodes),
        # Density: q from hourly_rate, v from space_mean speed proxy
        # (use mean_kph; in full HCM you'd want true space-mean)
        make_edge("live_metrics", "control_out", "density",
                  "control_in", nodes=nodes),
        make_edge("live_metrics", "hourly_rate", "density",
                  "flow_vph", nodes=nodes),
        make_edge("speed_summary", "mean_kph", "density",
                  "space_mean_speed_kph", nodes=nodes),
        # v/c
        make_edge("live_metrics", "control_out", "vc", "control_in", nodes=nodes),
        make_edge("live_metrics", "hourly_rate", "vc", "volume_vph", nodes=nodes),
        # Annotation: tracker-annotated image + line ROI
        make_edge("line", "line", "annot_lines", "line_1", nodes=nodes),
        make_edge("track", "control_out", "annotate", "control_in", nodes=nodes),
        make_edge("track", "image", "annotate", "image", nodes=nodes),
        make_edge("annot_lines", "lines", "annotate", "lines", nodes=nodes),
        # Displays
        make_edge("annotate", "control_out", "disp_frame",
                  "control_in", nodes=nodes),
        make_edge("annotate", "image", "disp_frame", "value", nodes=nodes),
        make_edge("speed_summary", "mean_kph", "disp_mean", "value", nodes=nodes),
        make_edge("speed_summary", "control_out", "disp_mean",
                  "control_in", nodes=nodes),
        make_edge("speed_summary", "p85_kph", "disp_p85", "value", nodes=nodes),
        make_edge("speed_summary", "control_out", "disp_p85",
                  "control_in", nodes=nodes),
        make_edge("density", "density_vpkm", "disp_dens",
                  "value", nodes=nodes),
        make_edge("density", "control_out", "disp_dens",
                  "control_in", nodes=nodes),
        make_edge("vc", "vc", "disp_vc", "value", nodes=nodes),
        make_edge("vc", "control_out", "disp_vc",
                  "control_in", nodes=nodes),
        make_edge("vc", "status", "disp_status", "value", nodes=nodes),
        make_edge("vc", "control_out", "disp_status",
                  "control_in", nodes=nodes),
    ]
    widgets = [
        widget("w-title", type="label", x=20, y=20, w=700, h=40,
               label="Demo · Traffic 02 — Live Speed + Density"),
        widget("w-frame", type="bound-output", x=20, y=80, w=480, h=320,
               label="Annotated frame", node_id="annotate",
               port_name="image", input_type="image"),
        widget("w-mean", type="bound-output", x=520, y=80, w=240, h=80,
               label="Mean speed (km/h)", node_id="speed_summary",
               port_name="mean_kph", input_type="float"),
        widget("w-p85", type="bound-output", x=520, y=200, w=240, h=80,
               label="85th %ile (km/h)", node_id="speed_summary",
               port_name="p85_kph", input_type="float"),
        widget("w-p95", type="bound-output", x=520, y=320, w=240, h=80,
               label="95th %ile (km/h)", node_id="speed_summary",
               port_name="p95_kph", input_type="float"),
        widget("w-dens", type="bound-output", x=20, y=420, w=240, h=80,
               label="Density (veh/km)", node_id="density",
               port_name="density_vpkm", input_type="float"),
        widget("w-vc", type="bound-output", x=280, y=420, w=240, h=80,
               label="v/c", node_id="vc",
               port_name="vc", input_type="float"),
        widget("w-status", type="bound-output", x=540, y=420, w=240, h=80,
               label="Capacity status", node_id="vc",
               port_name="status", input_type="string"),
    ]
    return name, desc, make_graph_data(nodes, edges, widgets=widgets)


def demo_traffic_03_safety_metrics() -> Tuple[str, str, Dict[str, Any]]:
    """Live FL511 -> live multi-event safety overlay (TTC + DRAC + brake + WW)."""
    name = f"{DEMO_NAME_PREFIX}Traffic 03 — Live Safety Conflicts (TTC + DRAC + Brake + Wrong-way)"
    desc = (
        "Live surrogate-safety overlay. The same FL511 → YOLO → ByteTrack "
        "stack feeds ``traffic.speed.estimate`` (which fills the per-run "
        "track store). Four detectors then read that store and emit "
        "``traffic.event`` records:\n\n"
        " · ``traffic.safety.ttc_pairwise`` — Hayward-style Time-to-Collision\n"
        " · ``traffic.safety.drac_pairwise`` — leader/follower DRAC\n"
        " · ``traffic.events.hard_brake`` — deceleration > 3.4 m/s²\n"
        " · ``traffic.events.wrong_way`` — heading vs lane-flow\n\n"
        "All event lists merge into ``traffic.events.merge`` → "
        "``traffic.events.annotate`` (severity-coloured border + caption "
        "showing per-kind counts) → dashboard image. ``traffic.report."
        "event_summary`` provides the running tally widget. If FL511 cam "
        "2130 returns 404, edit the connect node's ``camera`` parameter."
    )
    nodes: List[Dict[str, Any]] = [
        # Top pipeline (row 1): start → connect → loop → frame → decode → YOLO → track → speed
        make_node("start", "core.control.start", *gp(0, 1)),
        make_node("connect", "fl511.connect", *gp(1, 1),
                  inputs={"camera": 2130, "fps": 10, "buffer_seconds": 4}),
        make_node("loop", "core.control.for", *gp(2, 1),
                  inputs={"first_index": 0, "last_index": 29}),
        make_node("frame", "fl511.get_frame", *gp(3, 1),
                  inputs={"timeout": 5.0, "quality": 80,
                          "require_frame": True, "pace": True}),
        make_node("img_decode", "convert.image.from_url", *gp(4, 1),
                  inputs={"timeout": 5.0}),
        make_node("yolo", "image.detect.yolo", *gp(5, 1),
                  inputs={"weights": "yolo11n.pt", "confidence": 0.3,
                          "iou": 0.45, "annotate": False}),
        make_node("track", "tracker.bytetrack", *gp(6, 1),
                  inputs={"track_activation_threshold": 0.25,
                          "lost_track_buffer": 30,
                          "minimum_matching_threshold": 0.8,
                          "frame_rate": 10, "annotate": True}),
        make_node("speed", "traffic.speed.estimate", *gp(7, 1),
                  inputs={"reference": "bottom", "ema_alpha": 0.4,
                          "window_s": 0.6, "store_key": "speed"}),
        # Calibration node parked off the main pipeline (col 0, row 3)
        make_node("cal", "traffic.calibration.from_known_width", *gp(0, 3),
                  inputs={"image_width": 704, "image_height": 480,
                          "point_a": [320, 360], "point_b": [400, 360],
                          "real_distance_m": 3.65}),
        # Four parallel safety detectors stacked in col 8
        make_node("ttc", "traffic.safety.ttc_pairwise", *gp(8, 0),
                  inputs={"store_key": "speed", "threshold_s": 2.0,
                          "critical_s": 0.8, "min_speed_mps": 1.5}),
        make_node("drac", "traffic.safety.drac_pairwise", *gp(8, 1),
                  inputs={"store_key": "speed", "threshold_mps2": 3.4,
                          "critical_mps2": 4.5,
                          "max_lead_distance_m": 50.0,
                          "min_speed_mps": 2.0}),
        make_node("brake", "traffic.events.hard_brake", *gp(8, 2),
                  inputs={"store_key": "speed", "threshold_mps2": 3.4,
                          "window_s": 1.0}),
        make_node("ww", "traffic.events.wrong_way", *gp(8, 3),
                  inputs={"store_key": "speed",
                          "expected_dx": 1.0, "expected_dy": 0.0,
                          "angle_threshold_deg": 110.0,
                          "min_speed_mps": 2.0}),
        # Merge → summary + annotate
        make_node("ev_merge", "traffic.events.merge", *gp(9, 1), inputs={}),
        make_node("ev_summary", "traffic.report.event_summary", *gp(9, 2),
                  inputs={}),
        make_node("annotate", "traffic.events.annotate", *gp(9, 0),
                  inputs={"thickness": 3}),
        # Displays (col 10, 11)
        make_node("disp_frame", "general.to_display", *gp(10, 0),
                  inputs={"section": "Frame", "title": "Annotated"}),
        make_node("disp_kinds", "general.to_display", *gp(10, 1),
                  inputs={"section": "Events", "title": "By kind"}),
        make_node("disp_sev", "general.to_display", *gp(10, 2),
                  inputs={"section": "Events", "title": "By severity"}),
        make_node("disp_total", "general.to_display", *gp(10, 3),
                  inputs={"section": "Events", "title": "Total"}),
        make_node("disp_min_ttc", "general.to_display", *gp(11, 0),
                  inputs={"section": "Safety", "title": "Min TTC (s)"}),
        make_node("disp_max_drac", "general.to_display", *gp(11, 1),
                  inputs={"section": "Safety", "title": "Max DRAC (m/s²)"}),
    ]
    edges = [
        # Calibration once
        make_edge("start", "control_out", "cal", "control_in", nodes=nodes),
        # FL511 chain
        make_edge("start", "control_out", "connect", "control_in", nodes=nodes),
        make_edge("connect", "control_out", "loop", "control_in", nodes=nodes),
        make_edge("loop", "loop_body", "frame", "control_in", nodes=nodes),
        make_edge("connect", "stream", "frame", "stream", nodes=nodes),
        make_edge("frame", "control_out", "img_decode", "control_in", nodes=nodes),
        make_edge("frame", "image", "img_decode", "url", nodes=nodes),
        make_edge("img_decode", "control_out", "yolo", "control_in", nodes=nodes),
        make_edge("img_decode", "image", "yolo", "image", nodes=nodes),
        make_edge("yolo", "control_out", "track", "control_in", nodes=nodes),
        make_edge("yolo", "detections", "track", "detections", nodes=nodes),
        make_edge("img_decode", "image", "track", "image", nodes=nodes),
        # Speed: fills the track store
        make_edge("track", "control_out", "speed", "control_in", nodes=nodes),
        make_edge("track", "detections", "speed", "detections", nodes=nodes),
        make_edge("cal", "calibration", "speed", "calibration", nodes=nodes),
        # Four parallel safety detectors
        make_edge("speed", "control_out", "ttc", "control_in", nodes=nodes),
        make_edge("speed", "control_out", "drac", "control_in", nodes=nodes),
        make_edge("speed", "control_out", "brake", "control_in", nodes=nodes),
        make_edge("speed", "control_out", "ww", "control_in", nodes=nodes),
        # Merge events
        make_edge("ttc", "events", "ev_merge", "events_1", nodes=nodes),
        make_edge("drac", "events", "ev_merge", "events_2", nodes=nodes),
        make_edge("brake", "events", "ev_merge", "events_3", nodes=nodes),
        make_edge("ww", "events", "ev_merge", "events_4", nodes=nodes),
        make_edge("ttc", "control_out", "ev_merge", "control_in", nodes=nodes),
        # Summary + annotation
        make_edge("ev_merge", "control_out", "ev_summary",
                  "control_in", nodes=nodes),
        make_edge("ev_merge", "events", "ev_summary", "events", nodes=nodes),
        make_edge("ev_merge", "control_out", "annotate",
                  "control_in", nodes=nodes),
        make_edge("track", "image", "annotate", "image", nodes=nodes),
        make_edge("ev_merge", "events", "annotate", "events", nodes=nodes),
        # Displays
        make_edge("annotate", "image", "disp_frame", "value", nodes=nodes),
        make_edge("annotate", "control_out", "disp_frame",
                  "control_in", nodes=nodes),
        make_edge("ev_summary", "by_kind", "disp_kinds",
                  "value", nodes=nodes),
        make_edge("ev_summary", "control_out", "disp_kinds",
                  "control_in", nodes=nodes),
        make_edge("ev_summary", "by_severity", "disp_sev",
                  "value", nodes=nodes),
        make_edge("ev_summary", "control_out", "disp_sev",
                  "control_in", nodes=nodes),
        make_edge("ev_summary", "total", "disp_total",
                  "value", nodes=nodes),
        make_edge("ev_summary", "control_out", "disp_total",
                  "control_in", nodes=nodes),
        make_edge("ttc", "min_ttc_s", "disp_min_ttc", "value", nodes=nodes),
        make_edge("ttc", "control_out", "disp_min_ttc",
                  "control_in", nodes=nodes),
        make_edge("drac", "max_drac_mps2", "disp_max_drac",
                  "value", nodes=nodes),
        make_edge("drac", "control_out", "disp_max_drac",
                  "control_in", nodes=nodes),
    ]
    widgets = [
        widget("w-title", type="label", x=20, y=20, w=700, h=40,
               label="Demo · Traffic 03 — Live Safety Conflicts"),
        widget("w-frame", type="bound-output", x=20, y=80, w=520, h=360,
               label="Annotated frame", node_id="annotate",
               port_name="image", input_type="image"),
        widget("w-total", type="bound-output", x=560, y=80, w=200, h=80,
               label="Total events", node_id="ev_summary",
               port_name="total", input_type="int"),
        widget("w-kinds", type="bound-output", x=560, y=200, w=240, h=160,
               label="By kind", node_id="ev_summary",
               port_name="by_kind", input_type="any"),
        widget("w-sev", type="bound-output", x=820, y=200, w=240, h=160,
               label="By severity", node_id="ev_summary",
               port_name="by_severity", input_type="any"),
        widget("w-min-ttc", type="bound-output", x=20, y=460, w=240, h=80,
               label="Min TTC (s)", node_id="ttc",
               port_name="min_ttc_s", input_type="float"),
        widget("w-max-drac", type="bound-output", x=280, y=460, w=240, h=80,
               label="Max DRAC (m/s²)", node_id="drac",
               port_name="max_drac_mps2", input_type="float"),
    ]
    return name, desc, make_graph_data(nodes, edges, widgets=widgets)


def demo_traffic_04_video_pipeline() -> Tuple[str, str, Dict[str, Any]]:
    """Live travel-time pipeline: entry/exit lines -> reliability indices -> CSV."""
    name = f"{DEMO_NAME_PREFIX}Traffic 04 — Live Travel Time + Reliability + CSV Snapshot"
    desc = (
        "End-to-end travel-time pipeline using two virtual screen lines. "
        "FL511 → YOLO → ByteTrack → traffic.trajectory.accumulate (with a "
        "calibration). traffic.events.travel_time stamps each track that "
        "crosses both lines with an elapsed-seconds metric. The metric "
        "values flow through traffic.events.timestamps (field=metric) → "
        "traffic.report.travel_time_indices for FHWA-style reliability "
        "indices (Travel-Time Index, Planning-Time Index, Buffer Index). "
        "Every event also lands in traffic.report.csv_emit → "
        "traffic.report.snapshot_writer for an on-disk CSV report. If "
        "FL511 cam 2130 is offline, edit the connect node's ``camera`` "
        "parameter."
    )
    nodes: List[Dict[str, Any]] = [
        # Top pipeline (row 1): start → connect → loop → frame → decode → YOLO → track → trajectory → travel-time
        make_node("start", "core.control.start", *gp(0, 1)),
        make_node("connect", "fl511.connect", *gp(1, 1),
                  inputs={"camera": 2130, "fps": 10, "buffer_seconds": 4}),
        make_node("loop", "core.control.for", *gp(2, 1),
                  inputs={"first_index": 0, "last_index": 29}),
        make_node("frame", "fl511.get_frame", *gp(3, 1),
                  inputs={"timeout": 5.0, "quality": 80,
                          "require_frame": True, "pace": True}),
        make_node("img_decode", "convert.image.from_url", *gp(4, 1),
                  inputs={"timeout": 5.0}),
        make_node("yolo", "image.detect.yolo", *gp(5, 1),
                  inputs={"weights": "yolo11n.pt", "confidence": 0.3,
                          "iou": 0.45, "annotate": False}),
        make_node("track", "tracker.bytetrack", *gp(6, 1),
                  inputs={"track_activation_threshold": 0.25,
                          "frame_rate": 10, "annotate": True}),
        make_node("traj", "traffic.trajectory.accumulate", *gp(7, 1),
                  inputs={"store_key": "trajectory", "max_history": 256}),
        make_node("travel", "traffic.events.travel_time", *gp(8, 1),
                  inputs={"reference": "bottom"}),
        # Calibration off the main pipeline (col 0, row 3)
        make_node("cal", "traffic.calibration.from_known_width", *gp(0, 3),
                  inputs={"image_width": 704, "image_height": 480,
                          "point_a": [320, 360], "point_b": [400, 360],
                          "real_distance_m": 3.65}),
        # ROI lines + merger (row 3, cols 6-7)
        make_node("entry_line", "traffic.roi.line", *gp(6, 3),
                  inputs={"name": "entry", "x1": 0, "y1": 180,
                          "x2": 704, "y2": 180}),
        make_node("exit_line", "traffic.roi.line", *gp(7, 3),
                  inputs={"name": "exit", "x1": 0, "y1": 320,
                          "x2": 704, "y2": 320}),
        make_node("annot_lines", "traffic.roi.merge_lines", *gp(8, 3),
                  inputs={}),
        # Bridge events → list<float> of travel times → reliability indices
        make_node("ts_extract", "traffic.events.timestamps", *gp(9, 1),
                  inputs={"field": "metric"}),
        make_node("tti", "traffic.report.travel_time_indices", *gp(10, 1),
                  inputs={"free_flow_s": 2.0}),
        make_node("ev_summary", "traffic.report.event_summary", *gp(9, 2),
                  inputs={}),
        make_node("csv", "traffic.report.csv_emit", *gp(10, 2), inputs={}),
        # Annotator + dashboard widgets
        make_node("annotate", "traffic.events.annotate", *gp(9, 0),
                  inputs={"thickness": 2}),
        make_node("disp_frame", "general.to_display", *gp(10, 0),
                  inputs={"section": "Frame", "title": "Annotated"}),
        make_node("disp_completed", "general.to_display", *gp(11, 0),
                  inputs={"section": "Travel Time", "title": "Completed"}),
        make_node("disp_active", "general.to_display", *gp(11, 1),
                  inputs={"section": "Travel Time", "title": "Active (in transit)"}),
        make_node("disp_mean", "general.to_display", *gp(11, 2),
                  inputs={"section": "Travel Time", "title": "Mean (s)"}),
        make_node("disp_pti", "general.to_display", *gp(11, 3),
                  inputs={"section": "Reliability", "title": "Planning Time Index"}),
        make_node("disp_bi", "general.to_display", *gp(10, 3),
                  inputs={"section": "Reliability", "title": "Buffer Index"}),
        make_node("disp_csv", "general.to_display", *gp(9, 3),
                  inputs={"section": "Snapshot", "title": "CSV preview"}),
    ]
    edges = [
        make_edge("start", "control_out", "cal", "control_in", nodes=nodes),
        # FL511
        make_edge("start", "control_out", "connect", "control_in", nodes=nodes),
        make_edge("connect", "control_out", "loop", "control_in", nodes=nodes),
        make_edge("loop", "loop_body", "frame", "control_in", nodes=nodes),
        make_edge("connect", "stream", "frame", "stream", nodes=nodes),
        make_edge("frame", "control_out", "img_decode", "control_in", nodes=nodes),
        make_edge("frame", "image", "img_decode", "url", nodes=nodes),
        make_edge("img_decode", "control_out", "yolo", "control_in", nodes=nodes),
        make_edge("img_decode", "image", "yolo", "image", nodes=nodes),
        make_edge("yolo", "control_out", "track", "control_in", nodes=nodes),
        make_edge("yolo", "detections", "track", "detections", nodes=nodes),
        make_edge("img_decode", "image", "track", "image", nodes=nodes),
        # Trajectory (uses calibration)
        make_edge("track", "control_out", "traj", "control_in", nodes=nodes),
        make_edge("track", "detections", "traj", "detections", nodes=nodes),
        make_edge("cal", "calibration", "traj", "calibration", nodes=nodes),
        # Travel-time events between the two lines
        make_edge("traj", "control_out", "travel", "control_in", nodes=nodes),
        make_edge("track", "detections", "travel", "detections", nodes=nodes),
        make_edge("entry_line", "line", "travel", "entry_line", nodes=nodes),
        make_edge("exit_line", "line", "travel", "exit_line", nodes=nodes),
        # Reliability indices via timestamp-extractor
        make_edge("travel", "control_out", "ts_extract",
                  "control_in", nodes=nodes),
        make_edge("travel", "events", "ts_extract", "events", nodes=nodes),
        make_edge("ts_extract", "control_out", "tti",
                  "control_in", nodes=nodes),
        make_edge("ts_extract", "values", "tti",
                  "travel_times_s", nodes=nodes),
        # Event summary + CSV
        make_edge("travel", "control_out", "ev_summary",
                  "control_in", nodes=nodes),
        make_edge("travel", "events", "ev_summary", "events", nodes=nodes),
        make_edge("travel", "control_out", "csv", "control_in", nodes=nodes),
        make_edge("travel", "events", "csv", "records", nodes=nodes),
        # Annotate frame with both lines
        make_edge("entry_line", "line", "annot_lines", "line_1", nodes=nodes),
        make_edge("exit_line", "line", "annot_lines", "line_2", nodes=nodes),
        make_edge("track", "control_out", "annotate", "control_in", nodes=nodes),
        make_edge("track", "image", "annotate", "image", nodes=nodes),
        make_edge("annot_lines", "lines", "annotate", "lines", nodes=nodes),
        # Displays
        make_edge("annotate", "image", "disp_frame", "value", nodes=nodes),
        make_edge("annotate", "control_out", "disp_frame",
                  "control_in", nodes=nodes),
        make_edge("travel", "completed_total", "disp_completed",
                  "value", nodes=nodes),
        make_edge("travel", "control_out", "disp_completed",
                  "control_in", nodes=nodes),
        make_edge("travel", "active_total", "disp_active",
                  "value", nodes=nodes),
        make_edge("travel", "control_out", "disp_active",
                  "control_in", nodes=nodes),
        make_edge("tti", "mean_s", "disp_mean", "value", nodes=nodes),
        make_edge("tti", "control_out", "disp_mean",
                  "control_in", nodes=nodes),
        make_edge("tti", "planning_time_index", "disp_pti",
                  "value", nodes=nodes),
        make_edge("tti", "control_out", "disp_pti",
                  "control_in", nodes=nodes),
        make_edge("tti", "buffer_index", "disp_bi",
                  "value", nodes=nodes),
        make_edge("tti", "control_out", "disp_bi",
                  "control_in", nodes=nodes),
        make_edge("csv", "csv", "disp_csv", "value", nodes=nodes),
        make_edge("csv", "control_out", "disp_csv",
                  "control_in", nodes=nodes),
    ]
    widgets = [
        widget("w-title", type="label", x=20, y=20, w=700, h=40,
               label="Demo · Traffic 04 — Live Travel Time"),
        widget("w-frame", type="bound-output", x=20, y=80, w=520, h=360,
               label="Annotated frame", node_id="annotate",
               port_name="image", input_type="image"),
        widget("w-completed", type="bound-output", x=560, y=80, w=200, h=80,
               label="Completed", node_id="travel",
               port_name="completed_total", input_type="int"),
        widget("w-active", type="bound-output", x=560, y=200, w=200, h=80,
               label="In transit", node_id="travel",
               port_name="active_total", input_type="int"),
        widget("w-mean", type="bound-output", x=560, y=320, w=200, h=80,
               label="Mean travel (s)", node_id="tti",
               port_name="mean_s", input_type="float"),
        widget("w-pti", type="bound-output", x=20, y=460, w=240, h=80,
               label="Planning Time Index", node_id="tti",
               port_name="planning_time_index", input_type="float"),
        widget("w-bi", type="bound-output", x=280, y=460, w=240, h=80,
               label="Buffer Index", node_id="tti",
               port_name="buffer_index", input_type="float"),
    ]
    return name, desc, make_graph_data(nodes, edges, widgets=widgets)


def demo_traffic_05_speed_estimate() -> Tuple[str, str, Dict[str, Any]]:
    """Live FL511 counter -> AADT -> HSM SPF -> CMFs -> EB -> PSI."""
    name = f"{DEMO_NAME_PREFIX}Traffic 05 — Live HSM Crash Prediction (Counter -> AADT -> SPF/CMF/EB/PSI)"
    desc = (
        "End-to-end Highway Safety Manual Part C predictive method, "
        "bootstrapped from a live FL511 counter. The pipeline:\n\n"
        " 1. FL511 → YOLO → ByteTrack → traffic.count.line gives a live "
        "    cumulative count of vehicles crossing a screen line.\n"
        " 2. traffic.flow.live_metrics extrapolates that count to an AADT "
        "    estimate (count × 3600 / elapsed × 24 × adjustment factors).\n"
        " 3. The extrapolated AADT feeds traffic.crash.spf_urban_arterial "
        "    (HSM Ch. 12 SPF for 4-lane undivided arterials).\n"
        " 4. traffic.crash.apply_cmfs applies a chain of crash-modification "
        "    factors and a local calibration factor.\n"
        " 5. traffic.crash.empirical_bayes blends the SPF prediction with "
        "    a recent observed crash count.\n"
        " 6. traffic.crash.psi reports the Potential-for-Safety-Improvement "
        "    (excess crashes — the canonical network-screening score).\n"
        " 7. traffic.crash.epdo translates a KABCO breakdown into an "
        "    Equivalent-Property-Damage-Only ($k) cost.\n\n"
        "Edit the connect node's ``camera`` parameter if FL511 returns a "
        "404 on the configured camera."
    )
    nodes: List[Dict[str, Any]] = [
        # Top pipeline (row 1): start → connect → loop → frame → decode → YOLO → track → count → live_metrics
        make_node("start", "core.control.start", *gp(0, 1)),
        make_node("connect", "fl511.connect", *gp(1, 1),
                  inputs={"camera": 2130, "fps": 10, "buffer_seconds": 4}),
        make_node("loop", "core.control.for", *gp(2, 1),
                  inputs={"first_index": 0, "last_index": 29}),
        make_node("frame", "fl511.get_frame", *gp(3, 1),
                  inputs={"timeout": 5.0, "quality": 80,
                          "require_frame": True, "pace": True}),
        make_node("img_decode", "convert.image.from_url", *gp(4, 1),
                  inputs={"timeout": 5.0}),
        make_node("yolo", "image.detect.yolo", *gp(5, 1),
                  inputs={"weights": "yolo11n.pt", "confidence": 0.3,
                          "annotate": False}),
        make_node("track", "tracker.bytetrack", *gp(6, 1),
                  inputs={"track_activation_threshold": 0.25,
                          "frame_rate": 10, "annotate": True}),
        make_node("count", "traffic.count.line", *gp(7, 1),
                  inputs={"reference": "bottom", "hysteresis_px": 2.0}),
        make_node("live_metrics", "traffic.flow.live_metrics", *gp(8, 1),
                  inputs={"seasonal_factor": 1.05, "dow_factor": 1.02,
                          "axle_factor": 1.0}),
        # ROI and merger on row 3 below the pipeline
        make_node("line", "traffic.roi.line", *gp(6, 3),
                  inputs={"name": "screen line",
                          "x1": 0, "y1": 240, "x2": 704, "y2": 240}),
        make_node("annot_lines", "traffic.roi.merge_lines", *gp(7, 3),
                  inputs={}),
        # SPF → CMFs → EB → PSI chain on row 2 (below live_metrics)
        make_node("spf", "traffic.crash.spf_urban_arterial", *gp(8, 2),
                  inputs={"length_mi": 0.75, "a": -7.99, "b": 1.17}),
        make_node("cmfs", "traffic.crash.apply_cmfs", *gp(9, 2),
                  inputs={"cmfs": [0.92, 1.05, 0.88],
                          "calibration_factor": 1.10}),
        make_node("eb", "traffic.crash.empirical_bayes", *gp(10, 2),
                  inputs={"n_observed_total": 5.0,
                          "overdispersion_k": 0.236}),
        make_node("psi", "traffic.crash.psi", *gp(11, 2), inputs={}),
        make_node("rate", "traffic.crash.crash_rate", *gp(9, 3),
                  inputs={"n_crashes": 4, "length_mi": 0.75, "years": 1.0}),
        # KABCO → EPDO branch (col 0, row 4 — out of pipeline)
        make_node("epdo", "traffic.crash.epdo", *gp(0, 4),
                  inputs={"k": 1, "a": 2, "b": 5, "c": 8, "o": 25}),
        # Annotator + dashboard widgets
        make_node("annotate", "traffic.events.annotate", *gp(9, 1),
                  inputs={"thickness": 2}),
        make_node("disp_frame", "general.to_display", *gp(10, 0),
                  inputs={"section": "Frame", "title": "Annotated"}),
        make_node("disp_aadt", "general.to_display", *gp(10, 1),
                  inputs={"section": "Live Counter",
                          "title": "AADT (extrapolated)"}),
        make_node("disp_predicted", "general.to_display", *gp(11, 1),
                  inputs={"section": "HSM Predicted", "title": "N predicted"}),
        make_node("disp_expected", "general.to_display", *gp(11, 0),
                  inputs={"section": "HSM Expected", "title": "N expected (EB)"}),
        make_node("disp_psi", "general.to_display", *gp(11, 3),
                  inputs={"section": "Network Screening", "title": "PSI (excess)"}),
        make_node("disp_rate", "general.to_display", *gp(10, 3),
                  inputs={"section": "Rate", "title": "Per MVM"}),
        make_node("disp_epdo", "general.to_display", *gp(1, 4),
                  inputs={"section": "Severity", "title": "EPDO ($k)"}),
    ]
    edges = [
        # FL511 chain
        make_edge("start", "control_out", "connect", "control_in", nodes=nodes),
        make_edge("connect", "control_out", "loop", "control_in", nodes=nodes),
        make_edge("loop", "loop_body", "frame", "control_in", nodes=nodes),
        make_edge("connect", "stream", "frame", "stream", nodes=nodes),
        make_edge("frame", "control_out", "img_decode", "control_in", nodes=nodes),
        make_edge("frame", "image", "img_decode", "url", nodes=nodes),
        make_edge("img_decode", "control_out", "yolo", "control_in", nodes=nodes),
        make_edge("img_decode", "image", "yolo", "image", nodes=nodes),
        make_edge("yolo", "control_out", "track", "control_in", nodes=nodes),
        make_edge("yolo", "detections", "track", "detections", nodes=nodes),
        make_edge("img_decode", "image", "track", "image", nodes=nodes),
        # Counter -> AADT
        make_edge("track", "control_out", "count", "control_in", nodes=nodes),
        make_edge("track", "detections", "count", "detections", nodes=nodes),
        make_edge("line", "line", "count", "line", nodes=nodes),
        make_edge("count", "control_out", "live_metrics", "control_in",
                  nodes=nodes),
        make_edge("count", "total", "live_metrics", "count", nodes=nodes),
        # AADT -> SPF -> CMFs -> EB -> PSI
        make_edge("live_metrics", "control_out", "spf",
                  "control_in", nodes=nodes),
        make_edge("live_metrics", "aadt", "spf", "aadt", nodes=nodes),
        make_edge("spf", "control_out", "cmfs", "control_in", nodes=nodes),
        make_edge("spf", "n_spf_per_year", "cmfs",
                  "n_spf_per_year", nodes=nodes),
        make_edge("cmfs", "control_out", "eb", "control_in", nodes=nodes),
        make_edge("cmfs", "n_predicted", "eb", "n_predicted_total",
                  nodes=nodes),
        make_edge("eb", "control_out", "psi", "control_in", nodes=nodes),
        make_edge("eb", "n_expected", "psi", "n_expected", nodes=nodes),
        make_edge("cmfs", "n_predicted", "psi", "n_predicted", nodes=nodes),
        # Crash rate (uses live AADT too)
        make_edge("live_metrics", "control_out", "rate",
                  "control_in", nodes=nodes),
        make_edge("live_metrics", "aadt", "rate", "aadt", nodes=nodes),
        # EPDO independent
        make_edge("start", "control_out", "epdo", "control_in", nodes=nodes),
        # Annotate
        make_edge("line", "line", "annot_lines", "line_1", nodes=nodes),
        make_edge("track", "control_out", "annotate", "control_in", nodes=nodes),
        make_edge("track", "image", "annotate", "image", nodes=nodes),
        make_edge("annot_lines", "lines", "annotate", "lines", nodes=nodes),
        # Displays
        make_edge("annotate", "image", "disp_frame", "value", nodes=nodes),
        make_edge("annotate", "control_out", "disp_frame",
                  "control_in", nodes=nodes),
        make_edge("live_metrics", "aadt", "disp_aadt", "value", nodes=nodes),
        make_edge("live_metrics", "control_out", "disp_aadt",
                  "control_in", nodes=nodes),
        make_edge("cmfs", "n_predicted", "disp_predicted", "value", nodes=nodes),
        make_edge("cmfs", "control_out", "disp_predicted",
                  "control_in", nodes=nodes),
        make_edge("eb", "n_expected", "disp_expected", "value", nodes=nodes),
        make_edge("eb", "control_out", "disp_expected",
                  "control_in", nodes=nodes),
        make_edge("psi", "psi", "disp_psi", "value", nodes=nodes),
        make_edge("psi", "control_out", "disp_psi",
                  "control_in", nodes=nodes),
        make_edge("rate", "rate_per_million", "disp_rate", "value", nodes=nodes),
        make_edge("rate", "control_out", "disp_rate",
                  "control_in", nodes=nodes),
        make_edge("epdo", "epdo", "disp_epdo", "value", nodes=nodes),
        make_edge("epdo", "control_out", "disp_epdo",
                  "control_in", nodes=nodes),
    ]
    widgets = [
        widget("w-title", type="label", x=20, y=20, w=700, h=40,
               label="Demo · Traffic 05 — Live HSM Crash Prediction"),
        widget("w-frame", type="bound-output", x=20, y=80, w=480, h=320,
               label="Annotated frame", node_id="annotate",
               port_name="image", input_type="image"),
        widget("w-aadt", type="bound-output", x=520, y=80, w=240, h=80,
               label="AADT (extrap.)", node_id="live_metrics",
               port_name="aadt", input_type="float"),
        widget("w-pred", type="bound-output", x=520, y=200, w=240, h=80,
               label="HSM N predicted", node_id="cmfs",
               port_name="n_predicted", input_type="float"),
        widget("w-exp", type="bound-output", x=520, y=320, w=240, h=80,
               label="N expected (EB)", node_id="eb",
               port_name="n_expected", input_type="float"),
        widget("w-psi", type="bound-output", x=20, y=420, w=240, h=80,
               label="PSI (excess)", node_id="psi",
               port_name="psi", input_type="float"),
        widget("w-rate", type="bound-output", x=280, y=420, w=240, h=80,
               label="Crash rate (MVM)", node_id="rate",
               port_name="rate_per_million", input_type="float"),
        widget("w-epdo", type="bound-output", x=540, y=420, w=240, h=80,
               label="EPDO ($k)", node_id="epdo",
               port_name="epdo", input_type="float"),
    ]
    return name, desc, make_graph_data(nodes, edges, widgets=widgets)


# ---------------------------------------------------------------------------
# Traffic analytics — pure-math static demos
# ---------------------------------------------------------------------------
#
# These four demos run entirely off literal inputs and exercise the
# stride-traffic analytics nodes end-to-end. They produce numbers a
# transportation engineer recognises immediately (LOS letters, 85th
# percentile speed, PSI ranking, …) without needing any camera, GPU,
# or network access. They're ideal for a 30-second screen-share
# walkthrough: open the graph, click Run, point at the dashboard.


def demo_traffic_06_intersection_los() -> Tuple[str, str, Dict[str, Any]]:
    """4-approach signalised intersection: per-approach HCM control
    delay and LOS, plus the intersection-wide ICU score.

    Realistic operating point: a 90-second cycle with two phase pairs
    (NB/SB 30 s green; EB/WB 24 s green) carrying mixed mainline and
    cross-street volumes. The four v/c ratios are chosen so the
    intersection straddles the LOS C / D / E threshold — exactly the
    case a designer wants to be able to read at a glance.
    """
    name = f"{DEMO_NAME_PREFIX}Traffic 06 — Intersection LOS Snapshot (HCM)"
    desc = (
        "Per-approach HCM 2010 control delay and LOS, plus the "
        "intersection-wide ICU score, computed entirely from literal "
        "v/c ratios. NB/SB get 30 s of green in a 90 s cycle; EB/WB "
        "get 24 s. Initial v/c values land all four approaches at "
        "LOS C and the intersection at LOS D (ICU ≈ 0.78). Edit any "
        "v/c literal to immediately re-run the analysis: bump EB v/c "
        "from 0.30 to 0.55 and watch ICU slip past LOS F. Static — "
        "runs in <50 ms; drop-in template for any 4-leg signalised "
        "intersection."
    )
    nodes: List[Dict[str, Any]] = [
        make_node("start", "core.control.start", *gp(0, 0)),
        # Shared cycle constant — one literal feeds all four approaches.
        make_node("cycle", "core.literal.float", *gp(0, 1),
                  inputs={"value": 90.0}),
        # Per-approach green-split literals.
        make_node("g_ns", "core.literal.float", *gp(0, 2),
                  inputs={"value": 30.0}),
        make_node("g_ew", "core.literal.float", *gp(0, 3),
                  inputs={"value": 24.0}),
        # Per-approach v/c literals. Chosen to land all approaches at
        # LOS C and the intersection-wide ICU at LOS D — a "modestly
        # busy suburban intersection" snapshot. Editing these
        # literals in the canvas immediately re-runs the LOS recompute,
        # which makes for a great hands-on demo: turn EB v/c up to
        # 0.55 and watch ICU slip to LOS F.
        make_node("vc_nb", "core.literal.float", *gp(1, 0),
                  inputs={"value": 0.25}),
        make_node("vc_sb", "core.literal.float", *gp(1, 1),
                  inputs={"value": 0.20}),
        make_node("vc_eb", "core.literal.float", *gp(1, 2),
                  inputs={"value": 0.30}),
        make_node("vc_wb", "core.literal.float", *gp(1, 3),
                  inputs={"value": 0.18}),
        # Per-approach control-delay nodes.
        make_node("cd_nb", "traffic.intersection.control_delay", *gp(2, 0)),
        make_node("cd_sb", "traffic.intersection.control_delay", *gp(2, 1)),
        make_node("cd_eb", "traffic.intersection.control_delay", *gp(2, 2)),
        make_node("cd_wb", "traffic.intersection.control_delay", *gp(2, 3)),
        # ICU — needs the CRITICAL-phase v/c per phase pair. For a
        # 2-phase signal that's the max of the conflicting approaches:
        # NS-critical = max(NB, SB); EW-critical = max(EB, WB).
        make_node("critical_vc_str", "core.literal.string", *gp(0, 5),
                  inputs={"value": "[0.25, 0.30]"}),
        make_node("critical_vc", "core.json.parse", *gp(1, 5),
                  inputs={}),
        make_node("icu", "traffic.intersection.icu", *gp(2, 5),
                  inputs={"cycle_s": 90.0, "lost_time_s": 12.0}),
        # Dashboard outputs.
        make_node("disp_nb_d", "general.to_display", *gp(3, 0),
                  inputs={"section": "NB Approach", "title": "Delay (s/veh)"}),
        make_node("disp_nb_los", "general.to_display", *gp(4, 0),
                  inputs={"section": "NB Approach", "title": "LOS"}),
        make_node("disp_sb_d", "general.to_display", *gp(3, 1),
                  inputs={"section": "SB Approach", "title": "Delay (s/veh)"}),
        make_node("disp_sb_los", "general.to_display", *gp(4, 1),
                  inputs={"section": "SB Approach", "title": "LOS"}),
        make_node("disp_eb_d", "general.to_display", *gp(3, 2),
                  inputs={"section": "EB Approach", "title": "Delay (s/veh)"}),
        make_node("disp_eb_los", "general.to_display", *gp(4, 2),
                  inputs={"section": "EB Approach", "title": "LOS"}),
        make_node("disp_wb_d", "general.to_display", *gp(3, 3),
                  inputs={"section": "WB Approach", "title": "Delay (s/veh)"}),
        make_node("disp_wb_los", "general.to_display", *gp(4, 3),
                  inputs={"section": "WB Approach", "title": "LOS"}),
        make_node("disp_icu", "general.to_display", *gp(3, 5),
                  inputs={"section": "Intersection", "title": "ICU"}),
        make_node("disp_icu_los", "general.to_display", *gp(4, 5),
                  inputs={"section": "Intersection", "title": "ICU LOS"}),
    ]
    edges: List[Dict[str, Any]] = [
        make_edge("start", "control_out", "cd_nb", "control_in", nodes=nodes),
        make_edge("start", "control_out", "cd_sb", "control_in", nodes=nodes),
        make_edge("start", "control_out", "cd_eb", "control_in", nodes=nodes),
        make_edge("start", "control_out", "cd_wb", "control_in", nodes=nodes),
        make_edge("start", "control_out", "critical_vc", "control_in", nodes=nodes),
        # NB
        make_edge("cycle", "value", "cd_nb", "cycle_s", nodes=nodes),
        make_edge("g_ns", "value", "cd_nb", "green_s", nodes=nodes),
        make_edge("vc_nb", "value", "cd_nb", "vc", nodes=nodes),
        # SB
        make_edge("cycle", "value", "cd_sb", "cycle_s", nodes=nodes),
        make_edge("g_ns", "value", "cd_sb", "green_s", nodes=nodes),
        make_edge("vc_sb", "value", "cd_sb", "vc", nodes=nodes),
        # EB
        make_edge("cycle", "value", "cd_eb", "cycle_s", nodes=nodes),
        make_edge("g_ew", "value", "cd_eb", "green_s", nodes=nodes),
        make_edge("vc_eb", "value", "cd_eb", "vc", nodes=nodes),
        # WB
        make_edge("cycle", "value", "cd_wb", "cycle_s", nodes=nodes),
        make_edge("g_ew", "value", "cd_wb", "green_s", nodes=nodes),
        make_edge("vc_wb", "value", "cd_wb", "vc", nodes=nodes),
        # ICU
        make_edge("critical_vc_str", "value", "critical_vc", "json_string", nodes=nodes),
        make_edge("critical_vc", "control_out", "icu", "control_in", nodes=nodes),
        make_edge("critical_vc", "data", "icu", "critical_vc", nodes=nodes),
        # Dashboard wiring.
        make_edge("cd_nb", "d1_s", "disp_nb_d", "value", nodes=nodes),
        make_edge("cd_nb", "los", "disp_nb_los", "value", nodes=nodes),
        make_edge("cd_sb", "d1_s", "disp_sb_d", "value", nodes=nodes),
        make_edge("cd_sb", "los", "disp_sb_los", "value", nodes=nodes),
        make_edge("cd_eb", "d1_s", "disp_eb_d", "value", nodes=nodes),
        make_edge("cd_eb", "los", "disp_eb_los", "value", nodes=nodes),
        make_edge("cd_wb", "d1_s", "disp_wb_d", "value", nodes=nodes),
        make_edge("cd_wb", "los", "disp_wb_los", "value", nodes=nodes),
        make_edge("icu", "icu", "disp_icu", "value", nodes=nodes),
        make_edge("icu", "los", "disp_icu_los", "value", nodes=nodes),
        # Sequencing: control_delay -> displays
        make_edge("cd_nb", "control_out", "disp_nb_d", "control_in", nodes=nodes),
        make_edge("cd_nb", "control_out", "disp_nb_los", "control_in", nodes=nodes),
        make_edge("cd_sb", "control_out", "disp_sb_d", "control_in", nodes=nodes),
        make_edge("cd_sb", "control_out", "disp_sb_los", "control_in", nodes=nodes),
        make_edge("cd_eb", "control_out", "disp_eb_d", "control_in", nodes=nodes),
        make_edge("cd_eb", "control_out", "disp_eb_los", "control_in", nodes=nodes),
        make_edge("cd_wb", "control_out", "disp_wb_d", "control_in", nodes=nodes),
        make_edge("cd_wb", "control_out", "disp_wb_los", "control_in", nodes=nodes),
        make_edge("icu", "control_out", "disp_icu", "control_in", nodes=nodes),
        make_edge("icu", "control_out", "disp_icu_los", "control_in", nodes=nodes),
    ]
    widgets = [
        widget("w-title", type="label", x=20, y=20, w=620, h=40,
               label="Traffic 06 — Intersection LOS Snapshot"),
        widget("w-nb-d", type="bound-output", x=20, y=80, w=300, h=120,
               label="NB delay (s/veh)", node_id="cd_nb", port_name="d1_s",
               input_type="float"),
        widget("w-nb-los", type="bound-output", x=340, y=80, w=180, h=120,
               label="NB LOS", node_id="cd_nb", port_name="los",
               input_type="string"),
        widget("w-sb-d", type="bound-output", x=20, y=220, w=300, h=120,
               label="SB delay (s/veh)", node_id="cd_sb", port_name="d1_s",
               input_type="float"),
        widget("w-sb-los", type="bound-output", x=340, y=220, w=180, h=120,
               label="SB LOS", node_id="cd_sb", port_name="los",
               input_type="string"),
        widget("w-eb-d", type="bound-output", x=20, y=360, w=300, h=120,
               label="EB delay (s/veh)", node_id="cd_eb", port_name="d1_s",
               input_type="float"),
        widget("w-eb-los", type="bound-output", x=340, y=360, w=180, h=120,
               label="EB LOS", node_id="cd_eb", port_name="los",
               input_type="string"),
        widget("w-wb-d", type="bound-output", x=20, y=500, w=300, h=120,
               label="WB delay (s/veh)", node_id="cd_wb", port_name="d1_s",
               input_type="float"),
        widget("w-wb-los", type="bound-output", x=340, y=500, w=180, h=120,
               label="WB LOS", node_id="cd_wb", port_name="los",
               input_type="string"),
        widget("w-icu", type="bound-output", x=560, y=80, w=300, h=160,
               label="ICU", node_id="icu", port_name="icu",
               input_type="float"),
        widget("w-icu-los", type="bound-output", x=560, y=260, w=300, h=160,
               label="Intersection LOS (ICU)", node_id="icu", port_name="los",
               input_type="string"),
    ]
    return name, desc, make_graph_data(nodes, edges, widgets=widgets)


def demo_traffic_07_spot_speed_study() -> Tuple[str, str, Dict[str, Any]]:
    """Spot-speed study summary from 30 measured speeds.

    The 30 samples are drawn from a 45-mph (≈72 kph) collector with a
    moderate-spread distribution (σ≈8 kph). The dashboard surfaces the
    classical ITE/AASHTO spot-speed metrics: mean, median, 85th and
    95th percentile, and the standard deviation. Engineers use the
    85th percentile as the canonical "operating speed" — typically
    compared against the posted limit when calibrating signage and
    enforcement.
    """
    name = f"{DEMO_NAME_PREFIX}Traffic 07 — Spot Speed Study (85th percentile)"
    desc = (
        "30 measured spot-speeds from a 45 mph (72 kph) collector. "
        "Computes mean / median / 85th / 95th percentile and standard "
        "deviation via traffic.report.percentile_bundle, plus an "
        "explicit 85th-percentile readout via traffic.speed.percentile. "
        "Expected: 85th ≈ 78 kph (~49 mph) — about 4 mph above the "
        "posted limit, the classic case where a designer either lifts "
        "the limit or adds traffic-calming. Static; runs in <30 ms."
    )
    # 30 spot speeds (kph), drawn from N(72, 8) and rounded to 1 decimal.
    speeds_json = (
        "[65.4, 71.2, 74.8, 68.1, 80.3, 76.7, 69.5, 73.2, 78.5, 66.9, "
        "70.4, 75.1, 81.8, 72.6, 67.3, 79.2, 73.9, 69.8, 77.0, 74.5, "
        "68.7, 82.6, 71.5, 76.3, 70.1, 73.6, 78.0, 75.8, 68.4, 80.9]"
    )
    nodes: List[Dict[str, Any]] = [
        make_node("start", "core.control.start", *gp(0, 1)),
        make_node("speeds_str", "core.literal.string", *gp(1, 1),
                  inputs={"value": speeds_json}),
        make_node("speeds", "core.json.parse", *gp(2, 1),
                  inputs={}),
        make_node("bundle", "traffic.report.percentile_bundle", *gp(3, 1),
                  inputs={}),
        make_node("p85", "traffic.speed.percentile", *gp(3, 3),
                  inputs={"percentile": 85.0}),
        make_node("p95", "traffic.speed.percentile", *gp(3, 4),
                  inputs={"percentile": 95.0}),
        make_node("disp_mean", "general.to_display", *gp(4, 0),
                  inputs={"section": "Spot Speeds", "title": "Mean (kph)"}),
        make_node("disp_p50", "general.to_display", *gp(4, 1),
                  inputs={"section": "Spot Speeds", "title": "Median (kph)"}),
        make_node("disp_p85", "general.to_display", *gp(4, 2),
                  inputs={"section": "Spot Speeds", "title": "85th %ile (kph)"}),
        make_node("disp_p95", "general.to_display", *gp(4, 3),
                  inputs={"section": "Spot Speeds", "title": "95th %ile (kph)"}),
        make_node("disp_std", "general.to_display", *gp(5, 0),
                  inputs={"section": "Spot Speeds", "title": "Std-dev (kph)"}),
        make_node("disp_n", "general.to_display", *gp(5, 1),
                  inputs={"section": "Spot Speeds", "title": "Sample size N"}),
    ]
    edges = [
        make_edge("start", "control_out", "speeds", "control_in", nodes=nodes),
        make_edge("speeds_str", "value", "speeds", "json_string", nodes=nodes),
        make_edge("speeds", "control_out", "bundle", "control_in", nodes=nodes),
        make_edge("speeds", "data", "bundle", "values", nodes=nodes),
        make_edge("speeds", "control_out", "p85", "control_in", nodes=nodes),
        make_edge("speeds", "data", "p85", "speeds_kph", nodes=nodes),
        make_edge("speeds", "control_out", "p95", "control_in", nodes=nodes),
        make_edge("speeds", "data", "p95", "speeds_kph", nodes=nodes),
        # Wire bundle outputs to dashboard.
        make_edge("bundle", "mean", "disp_mean", "value", nodes=nodes),
        make_edge("bundle", "p50", "disp_p50", "value", nodes=nodes),
        make_edge("p85", "value_kph", "disp_p85", "value", nodes=nodes),
        make_edge("p95", "value_kph", "disp_p95", "value", nodes=nodes),
        make_edge("bundle", "stdev", "disp_std", "value", nodes=nodes),
        make_edge("bundle", "n", "disp_n", "value", nodes=nodes),
        make_edge("bundle", "control_out", "disp_mean", "control_in", nodes=nodes),
        make_edge("bundle", "control_out", "disp_p50", "control_in", nodes=nodes),
        make_edge("p85", "control_out", "disp_p85", "control_in", nodes=nodes),
        make_edge("p95", "control_out", "disp_p95", "control_in", nodes=nodes),
        make_edge("bundle", "control_out", "disp_std", "control_in", nodes=nodes),
        make_edge("bundle", "control_out", "disp_n", "control_in", nodes=nodes),
    ]
    widgets = [
        widget("w-title", type="label", x=20, y=20, w=620, h=40,
               label="Traffic 07 — Spot Speed Study"),
        widget("w-mean", type="bound-output", x=20, y=80, w=280, h=120,
               label="Mean speed (kph)", node_id="bundle", port_name="mean",
               input_type="float"),
        widget("w-p50", type="bound-output", x=320, y=80, w=280, h=120,
               label="Median (kph)", node_id="bundle", port_name="p50",
               input_type="float"),
        widget("w-p85", type="bound-output", x=20, y=220, w=280, h=120,
               label="85th percentile (kph)", node_id="p85", port_name="value_kph",
               input_type="float"),
        widget("w-p95", type="bound-output", x=320, y=220, w=280, h=120,
               label="95th percentile (kph)", node_id="p95", port_name="value_kph",
               input_type="float"),
        widget("w-std", type="bound-output", x=20, y=360, w=280, h=120,
               label="Std-dev (kph)", node_id="bundle", port_name="stdev",
               input_type="float"),
        widget("w-n", type="bound-output", x=320, y=360, w=280, h=120,
               label="N samples", node_id="bundle", port_name="n",
               input_type="int"),
    ]
    return name, desc, make_graph_data(nodes, edges, widgets=widgets)


def demo_traffic_08_safety_ranking() -> Tuple[str, str, Dict[str, Any]]:
    """HSM network safety ranking for 5 urban arterial corridors.

    For each corridor the pipeline computes the SPF-predicted crash
    rate, applies an Empirical-Bayes adjustment toward the observed
    count, and produces a PSI (potential for safety improvement)
    score. PSI ranks the corridors so the agency can prioritise the
    worst three for engineering review. This is the textbook AASHTO
    HSM Part B workflow, condensed into a single graph.
    """
    name = f"{DEMO_NAME_PREFIX}Traffic 08 — Network Safety Ranking (HSM PSI)"
    desc = (
        "AASHTO HSM Part B workflow for five urban arterial corridors: "
        "SPF-predicted crashes (n_predicted) → Empirical-Bayes shrinkage "
        "toward observed (n_expected) → PSI = n_expected − n_predicted. "
        "Positive PSI means the corridor is performing worse than its "
        "peer group; rank-order them for prioritisation. Expected: "
        "Corridor C (AADT 22k, 18 observed) tops the ranking with PSI "
        "≈ +4 cr/yr. Static; runs in <50 ms."
    )
    # Five urban arterial corridors: (label, AADT, length_mi, observed
    # crashes / year). Chosen so corridors C and D have observed
    # counts notably above the SPF-predicted baseline, giving positive
    # PSI scores that rank-order them above the merely-typical
    # corridors A, B and E. This is the bread-and-butter case the
    # HSM Part B network screening workflow is designed for.
    corridors = [
        ("A", 18000.0, 0.75, 30.0),  # ~typical: PSI ≈ +2
        ("B", 25000.0, 0.50, 25.0),  # ~typical
        ("C", 22000.0, 1.00, 60.0),  # WORST: PSI ≈ +11
        ("D", 30000.0, 0.65, 42.0),  # mild over-baseline
        ("E", 15000.0, 1.20, 20.0),  # under-baseline (PSI = 0)
    ]
    nodes: List[Dict[str, Any]] = [
        make_node("start", "core.control.start", *gp(0, 0)),
    ]
    edges: List[Dict[str, Any]] = []
    widgets = [
        widget("w-title", type="label", x=20, y=20, w=620, h=40,
               label="Traffic 08 — Network Safety Ranking"),
    ]
    widget_x = 20
    widget_y = 80
    for col, (label, aadt, length_mi, observed) in enumerate(corridors):
        # Literals
        nodes.append(make_node(f"aadt_{label}", "core.literal.float", *gp(col, 1),
                               inputs={"value": float(aadt)}))
        nodes.append(make_node(f"len_{label}", "core.literal.float", *gp(col, 2),
                               inputs={"value": float(length_mi)}))
        nodes.append(make_node(f"obs_{label}", "core.literal.float", *gp(col, 3),
                               inputs={"value": float(observed)}))
        # SPF
        nodes.append(make_node(f"spf_{label}", "traffic.crash.spf_urban_arterial",
                               *gp(col, 4), inputs={}))
        # EB
        nodes.append(make_node(f"eb_{label}", "traffic.crash.empirical_bayes",
                               *gp(col, 5), inputs={}))
        # PSI
        nodes.append(make_node(f"psi_{label}", "traffic.crash.psi",
                               *gp(col, 6), inputs={}))
        # Display PSI
        nodes.append(make_node(f"disp_psi_{label}", "general.to_display",
                               *gp(col, 7),
                               inputs={"section": "PSI Ranking",
                                       "title": f"Corridor {label} PSI"}))
        # Wiring
        edges.append(make_edge("start", "control_out",
                               f"spf_{label}", "control_in", nodes=nodes))
        edges.append(make_edge(f"aadt_{label}", "value",
                               f"spf_{label}", "aadt", nodes=nodes))
        edges.append(make_edge(f"len_{label}", "value",
                               f"spf_{label}", "length_mi", nodes=nodes))
        edges.append(make_edge(f"spf_{label}", "control_out",
                               f"eb_{label}", "control_in", nodes=nodes))
        edges.append(make_edge(f"spf_{label}", "n_spf_per_year",
                               f"eb_{label}", "n_predicted_total", nodes=nodes))
        edges.append(make_edge(f"obs_{label}", "value",
                               f"eb_{label}", "n_observed_total", nodes=nodes))
        edges.append(make_edge(f"eb_{label}", "control_out",
                               f"psi_{label}", "control_in", nodes=nodes))
        edges.append(make_edge(f"eb_{label}", "n_expected",
                               f"psi_{label}", "n_expected", nodes=nodes))
        edges.append(make_edge(f"spf_{label}", "n_spf_per_year",
                               f"psi_{label}", "n_predicted", nodes=nodes))
        edges.append(make_edge(f"psi_{label}", "control_out",
                               f"disp_psi_{label}", "control_in", nodes=nodes))
        edges.append(make_edge(f"psi_{label}", "psi",
                               f"disp_psi_{label}", "value", nodes=nodes))
        widgets.append(widget(
            f"w-psi-{label}", type="bound-output",
            x=widget_x, y=widget_y + col * 96, w=620, h=80,
            label=f"Corridor {label} — PSI (cr/yr)",
            node_id=f"psi_{label}", port_name="psi", input_type="float",
        ))
    return name, desc, make_graph_data(nodes, edges, widgets=widgets)


def demo_traffic_09_capacity_workbook() -> Tuple[str, str, Dict[str, Any]]:
    """Composite capacity / volume study: saturation flow from
    measured headways, PHF + hourly volume from 15-minute counts,
    AADT extrapolation, and a v/c ratio against the saturation
    capacity. The graph wires four independent analyses to a single
    dashboard the user can read top-to-bottom.
    """
    name = f"{DEMO_NAME_PREFIX}Traffic 09 — Capacity & Volume Workbook"
    desc = (
        "Four traffic-engineering primitives in one graph:\n"
        "1. Saturation flow from 12 measured saturation headways "
        "(skip first 4, mean of remainder).\n"
        "2. Peak-hour factor (PHF) and hourly volume from four "
        "15-minute counts.\n"
        "3. AADT extrapolation from the hourly volume using HCM "
        "seasonal / DOW factors.\n"
        "4. v/c ratio of the peak hour against the computed "
        "saturation flow.\n"
        "Expected: sat-flow ≈ 1900 vph, PHF ≈ 0.92, AADT ≈ 14 k, "
        "v/c ≈ 0.66 (acceptable). Static; runs in <50 ms."
    )
    # 12 saturation headways (s) — first 4 are the start-up lost time,
    # mean of remainder ≈ 1.9 s -> 3600/1.9 ≈ 1894 vph.
    headways_json = (
        "[2.8, 2.4, 2.1, 2.0, 1.95, 1.90, 1.85, 1.92, 1.88, 1.93, 1.89, 1.91]"
    )
    # 15-minute counts during the peak hour — totals 350, peak 15 = 100.
    counts_json = "[80, 90, 100, 80]"
    nodes: List[Dict[str, Any]] = [
        make_node("start", "core.control.start", *gp(0, 0)),
        # Saturation flow.
        make_node("hw_str", "core.literal.string", *gp(0, 1),
                  inputs={"value": headways_json}),
        make_node("hw_list", "core.json.parse", *gp(1, 1),
                  inputs={}),
        make_node("sat_flow", "traffic.flow.saturation_flow", *gp(2, 1),
                  inputs={"trim_first": 4}),
        # PHF + hourly volume.
        make_node("cnt_str", "core.literal.string", *gp(0, 2),
                  inputs={"value": counts_json}),
        make_node("cnt_list", "core.json.parse", *gp(1, 2),
                  inputs={}),
        make_node("phf", "traffic.flow.peak_hour_factor", *gp(2, 2),
                  inputs={}),
        # AADT — typical urban arterial factors (1.0, 1.0, 1.0 conservative).
        make_node("aadt", "traffic.flow.aadt_estimate", *gp(3, 2),
                  inputs={"duration_hours": 1.0,
                          "seasonal_factor": 1.0,
                          "dow_factor": 1.0,
                          "axle_factor": 1.0}),
        # v/c using sat_flow as capacity.
        make_node("vc", "traffic.flow.capacity_vc", *gp(4, 2),
                  inputs={}),
        # Dashboard outputs.
        make_node("disp_sat", "general.to_display", *gp(3, 1),
                  inputs={"section": "Capacity", "title": "Saturation flow (vph)"}),
        make_node("disp_hw", "general.to_display", *gp(4, 1),
                  inputs={"section": "Capacity",
                          "title": "Mean headway (s)"}),
        make_node("disp_phf", "general.to_display", *gp(3, 3),
                  inputs={"section": "Volume", "title": "PHF"}),
        make_node("disp_vph", "general.to_display", *gp(4, 3),
                  inputs={"section": "Volume", "title": "Hourly volume"}),
        make_node("disp_aadt", "general.to_display", *gp(5, 2),
                  inputs={"section": "AADT", "title": "AADT (cr/day)"}),
        make_node("disp_vc", "general.to_display", *gp(5, 3),
                  inputs={"section": "Capacity", "title": "v/c"}),
        make_node("disp_status", "general.to_display", *gp(6, 3),
                  inputs={"section": "Capacity", "title": "v/c status"}),
    ]
    edges = [
        make_edge("start", "control_out", "hw_list", "control_in", nodes=nodes),
        make_edge("start", "control_out", "cnt_list", "control_in", nodes=nodes),
        make_edge("hw_str", "value", "hw_list", "json_string", nodes=nodes),
        make_edge("cnt_str", "value", "cnt_list", "json_string", nodes=nodes),
        # Saturation flow
        make_edge("hw_list", "control_out", "sat_flow", "control_in", nodes=nodes),
        make_edge("hw_list", "data", "sat_flow", "headways_s", nodes=nodes),
        # PHF
        make_edge("cnt_list", "control_out", "phf", "control_in", nodes=nodes),
        make_edge("cnt_list", "data", "phf", "counts_15min", nodes=nodes),
        # AADT — driven by PHF's hourly_volume.
        make_edge("phf", "control_out", "aadt", "control_in", nodes=nodes),
        make_edge("phf", "hourly_volume", "aadt", "count", nodes=nodes),
        # v/c using sat_flow as capacity and PHF's hourly_volume as numerator.
        make_edge("aadt", "control_out", "vc", "control_in", nodes=nodes),
        make_edge("phf", "hourly_volume", "vc", "volume_vph", nodes=nodes),
        make_edge("sat_flow", "sat_flow_vph", "vc", "capacity_vph", nodes=nodes),
        # Dashboard wiring.
        make_edge("sat_flow", "sat_flow_vph", "disp_sat", "value", nodes=nodes),
        make_edge("sat_flow", "mean_headway_s", "disp_hw", "value", nodes=nodes),
        make_edge("phf", "phf", "disp_phf", "value", nodes=nodes),
        make_edge("phf", "hourly_volume", "disp_vph", "value", nodes=nodes),
        make_edge("aadt", "aadt", "disp_aadt", "value", nodes=nodes),
        make_edge("vc", "vc", "disp_vc", "value", nodes=nodes),
        make_edge("vc", "status", "disp_status", "value", nodes=nodes),
        # Sequencing.
        make_edge("sat_flow", "control_out", "disp_sat", "control_in", nodes=nodes),
        make_edge("sat_flow", "control_out", "disp_hw", "control_in", nodes=nodes),
        make_edge("phf", "control_out", "disp_phf", "control_in", nodes=nodes),
        make_edge("phf", "control_out", "disp_vph", "control_in", nodes=nodes),
        make_edge("aadt", "control_out", "disp_aadt", "control_in", nodes=nodes),
        make_edge("vc", "control_out", "disp_vc", "control_in", nodes=nodes),
        make_edge("vc", "control_out", "disp_status", "control_in", nodes=nodes),
    ]
    widgets = [
        widget("w-title", type="label", x=20, y=20, w=620, h=40,
               label="Traffic 09 — Capacity & Volume Workbook"),
        widget("w-sat", type="bound-output", x=20, y=80, w=300, h=120,
               label="Saturation flow (vph)", node_id="sat_flow",
               port_name="sat_flow_vph", input_type="float"),
        widget("w-hw", type="bound-output", x=340, y=80, w=300, h=120,
               label="Mean headway (s)", node_id="sat_flow",
               port_name="mean_headway_s", input_type="float"),
        widget("w-phf", type="bound-output", x=20, y=220, w=300, h=120,
               label="PHF", node_id="phf", port_name="phf",
               input_type="float"),
        widget("w-vph", type="bound-output", x=340, y=220, w=300, h=120,
               label="Hourly volume (vph)", node_id="phf",
               port_name="hourly_volume", input_type="int"),
        widget("w-aadt", type="bound-output", x=20, y=360, w=300, h=120,
               label="AADT", node_id="aadt", port_name="aadt",
               input_type="float"),
        widget("w-vc", type="bound-output", x=340, y=360, w=300, h=120,
               label="v/c", node_id="vc", port_name="vc",
               input_type="float"),
        widget("w-status", type="bound-output", x=20, y=500, w=620, h=120,
               label="Capacity status", node_id="vc",
               port_name="status", input_type="string"),
    ]
    return name, desc, make_graph_data(nodes, edges, widgets=widgets)


def demo_traffic_10_fundamental_diagram() -> Tuple[str, str, Dict[str, Any]]:
    """Greenshields macroscopic flow model: q-k-v fundamental diagram.

    Three operating points (free-flow, capacity, congested) feed three
    greenshields nodes that emit (speed, flow) for each density level.
    The dashboard reads like a textbook table and demonstrates the
    classical capacity = v_f * k_j / 4 result.
    """
    name = f"{DEMO_NAME_PREFIX}Traffic 10 — Fundamental Diagram (Greenshields)"
    desc = (
        "Greenshields macroscopic flow model sampled at three operating "
        "points: free-flow (k=20), capacity (k=100), congested (k=170). "
        "Free-flow speed = 100 kph, jam density = 200 vpkm — so the "
        "theoretical capacity is v_f · k_j / 4 = 5000 vph at the "
        "critical density k_c = k_j / 2 = 100 vpkm. The dashboard "
        "shows speed and flow at each point. Edit any density literal "
        "to slide along the diagram and watch flow rise to the capacity "
        "point then collapse back to zero. Static; runs in <30 ms."
    )
    # Three operating points: free-flow / capacity / congested.
    operating = [
        ("ff",  20.0),   # free-flow (mostly empty road)
        ("cap", 100.0),  # at capacity
        ("cong", 170.0), # heavily congested
    ]
    nodes: List[Dict[str, Any]] = [
        make_node("start", "core.control.start", *gp(0, 0)),
    ]
    edges: List[Dict[str, Any]] = []
    widgets = [
        widget("w-title", type="label", x=20, y=20, w=620, h=40,
               label="Traffic 10 — Greenshields Fundamental Diagram"),
        widget("w-formula", type="label", x=20, y=70, w=620, h=40,
               label="v(k) = v_f · (1 - k/k_j) ;   q(k) = v(k) · k ;   q_max = v_f · k_j / 4"),
    ]
    for col, (label, k) in enumerate(operating):
        nodes.append(make_node(
            f"k_{label}", "core.literal.float", *gp(col, 1),
            inputs={"value": float(k)},
        ))
        nodes.append(make_node(
            f"gs_{label}", "traffic.flow.fundamental_greenshields", *gp(col, 2),
            inputs={"free_flow_speed_kph": 100.0, "jam_density_vpkm": 200.0},
        ))
        nodes.append(make_node(
            f"disp_v_{label}", "general.to_display", *gp(col, 3),
            inputs={"section": f"k = {int(k)} vpkm", "title": "Speed (kph)"},
        ))
        nodes.append(make_node(
            f"disp_q_{label}", "general.to_display", *gp(col, 4),
            inputs={"section": f"k = {int(k)} vpkm", "title": "Flow (vph)"},
        ))
        edges.append(make_edge("start", "control_out",
                               f"gs_{label}", "control_in", nodes=nodes))
        edges.append(make_edge(f"k_{label}", "value",
                               f"gs_{label}", "density_vpkm", nodes=nodes))
        edges.append(make_edge(f"gs_{label}", "control_out",
                               f"disp_v_{label}", "control_in", nodes=nodes))
        edges.append(make_edge(f"gs_{label}", "control_out",
                               f"disp_q_{label}", "control_in", nodes=nodes))
        edges.append(make_edge(f"gs_{label}", "speed_kph",
                               f"disp_v_{label}", "value", nodes=nodes))
        edges.append(make_edge(f"gs_{label}", "flow_vph",
                               f"disp_q_{label}", "value", nodes=nodes))
        widgets.append(widget(
            f"w-v-{label}", type="bound-output",
            x=20 + col * 220, y=130, w=200, h=120,
            label=f"k={int(k)} → Speed (kph)",
            node_id=f"gs_{label}", port_name="speed_kph",
            input_type="float",
        ))
        widgets.append(widget(
            f"w-q-{label}", type="bound-output",
            x=20 + col * 220, y=270, w=200, h=120,
            label=f"k={int(k)} → Flow (vph)",
            node_id=f"gs_{label}", port_name="flow_vph",
            input_type="float",
        ))
    return name, desc, make_graph_data(nodes, edges, widgets=widgets)


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
    demo_traffic_01_flow_metrics,
    demo_traffic_02_hsm_crash,
    demo_traffic_03_safety_metrics,
    demo_traffic_04_video_pipeline,
    demo_traffic_05_speed_estimate,
    demo_traffic_06_intersection_los,
    demo_traffic_07_spot_speed_study,
    demo_traffic_08_safety_ranking,
    demo_traffic_09_capacity_workbook,
    demo_traffic_10_fundamental_diagram,
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
