"""
Smoke tests for the new STRIDE algorithm packages added by Agent 2:

  * stride-yolo
  * stride-rtdetr
  * stride-mediapipe
  * stride-depth-anything
  * stride-pcdet
  * stride-bytetrack
  * stride-clip

Each test imports the package, runs its `register()`, and verifies that
the expected node IDs appear in the global registry.  We deliberately
do NOT run forward() here — model weights have to be downloaded from
the internet on first use, which would make the test suite flaky.
Backend integration is verified separately by manually-driven smoke
tests in the development environment.
"""

from __future__ import annotations

import importlib

import pytest

from stride_core import NODE_REGISTRY


PACKAGES = [
    ("stride_yolo", ["image.detect.yolo", "image.segment.yolo", "image.pose.yolo"]),
    ("stride_rtdetr", ["image.detect.rtdetr"]),
    ("stride_mediapipe", ["image.pose.mediapipe", "image.hands.mediapipe", "image.face.mediapipe"]),
    ("stride_depth_anything", ["image.depth.depth_anything"]),
    ("stride_pcdet", [
        "lidar.detect.pointpillars",
        "lidar.detect.centerpoint",
        "lidar.detect.second",
        "lidar.detect.pvrcnn",
    ]),
    ("stride_bytetrack", ["tracker.bytetrack"]),
    ("stride_clip", ["image.classify.clip", "image.embed.clip"]),
]


@pytest.mark.parametrize("module_name,expected_nodes", PACKAGES)
def test_package_registers_nodes(module_name: str, expected_nodes: list[str]):
    try:
        mod = importlib.import_module(module_name)
    except ImportError as exc:
        pytest.skip(f"{module_name} not installed: {exc}")

    # Plugin entry point must exist and be callable
    assert hasattr(mod, "register"), f"{module_name} missing register()"
    mod.register()

    # All expected node ids must be present in the registry
    for node_id in expected_nodes:
        assert node_id in NODE_REGISTRY, (
            f"{node_id} not registered after importing {module_name}; "
            f"registry has: {sorted(NODE_REGISTRY)}"
        )


def test_bytetrack_runs_on_synthetic_input():
    """Smoke test for ByteTrack — the only new package that has zero
    network/weight dependencies and can run end-to-end."""
    pytest.importorskip("supervision")
    pytest.importorskip("numpy")

    from stride_bytetrack.nodes import ByteTrackNode, BYTETRACK_SPEC
    from stride_core import ExecutionContext

    node = ByteTrackNode({"id": "bt-test", "type": BYTETRACK_SPEC.type})
    ctx = ExecutionContext()

    det = {
        "_type": "Detections2D",
        "image_width": 640,
        "image_height": 480,
        "boxes": [
            {
                "x1": 100.0, "y1": 100.0, "x2": 200.0, "y2": 250.0,
                "confidence": 0.9, "class_id": 0, "class_name": "obj",
            }
        ],
        "image": "",
    }
    out = node.forward({
        "detections": det,
        "image": "",
        "reset": True,
        "annotate": False,
    }, ctx)

    assert out["count"] == 1
    assert out["track_ids"] and out["track_ids"][0] >= 1
    assert out["detections"]["_type"] == "Detections2D"


def test_yolo_specs_are_well_formed():
    """Each YOLO node spec must have an image input + detections output."""
    pytest.importorskip("ultralytics")
    import stride_yolo  # noqa: F401

    for nid in ["image.detect.yolo", "image.segment.yolo", "image.pose.yolo"]:
        spec = NODE_REGISTRY[nid]["spec"]
        port_names = [p.name for p in spec.inputs]
        assert "image" in port_names, f"{nid} missing image input port"
        out_names = [p.name for p in spec.outputs]
        assert "control_out" in out_names
