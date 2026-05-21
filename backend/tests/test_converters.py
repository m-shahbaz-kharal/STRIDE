"""
Smoke + round-trip tests for the ``stride-converters`` package.

Each converter is exercised through ``GraphExecutor.run`` so the test
also covers the full lifecycle (prepare → forward → teardown) and the
typed-error contract for invalid inputs. Inputs that are not exposed
through a literal-node spec (records, point clouds, etc.) are injected
via the per-node ``input_values`` dict, which the runner reads directly
when no link is connected to that port.
"""

from __future__ import annotations

import base64
from typing import Any, Dict, List

import numpy as np
import pytest

from stride_core.image_utils import encode_numpy_to_image

from app.runner import GraphExecutor


def _make_image(width: int = 64, height: int = 48, color=(0, 128, 200)) -> Dict[str, Any]:
    bgr = np.full((height, width, 3), 0, dtype=np.uint8)
    bgr[:, :] = color
    data_url = encode_numpy_to_image(bgr, fmt="jpeg", quality=90)
    return {
        "_type": "Image",
        "width": width,
        "height": height,
        "format": "jpeg",
        "data_b64": data_url,
    }


def _run(graph: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a tiny graph and return the alias->value outputs map."""
    return GraphExecutor(graph).run()["outputs"]


def _bbox(x1, y1, x2, y2, conf=0.9, cid=0, cname="t") -> Dict[str, Any]:
    return {
        "x1": float(x1), "y1": float(y1), "x2": float(x2), "y2": float(y2),
        "confidence": float(conf), "class_id": int(cid), "class_name": cname,
    }


def _pc(positions: np.ndarray) -> Dict[str, Any]:
    return {
        "_type": "PointCloud",
        "num_points": int(positions.shape[0]),
        "positions_b64": base64.b64encode(positions.astype(np.float32).tobytes()).decode("ascii"),
    }


# ----------------------------------------------------------------------
# Image converters
# ----------------------------------------------------------------------


class TestImageConverters:
    def test_to_grayscale_then_to_rgb_round_trip(self) -> None:
        image = _make_image(32, 24, (10, 50, 200))
        graph = {
            "nodes": [
                {
                    "id": "gray",
                    "type": "convert.image.to_grayscale",
                    "input_values": {"image": image},
                },
                {"id": "rgb", "type": "convert.image.from_grayscale_to_rgb"},
            ],
            "links": [
                {"from_node": "gray", "from_port": "image", "to_node": "rgb", "to_port": "image"},
            ],
            "output_nodes": [
                {"node_id": "gray", "port": "image", "alias": "gray"},
                {"node_id": "rgb", "port": "image", "alias": "rgb"},
            ],
        }
        outputs = _run(graph)
        assert outputs["gray"]["width"] == 32
        assert outputs["gray"]["height"] == 24
        assert outputs["rgb"]["width"] == 32
        assert outputs["rgb"]["height"] == 24

    def test_crop_inside_bounds(self) -> None:
        image = _make_image(64, 48)
        bbox = _bbox(8, 8, 40, 32)
        graph = {
            "nodes": [
                {
                    "id": "crop",
                    "type": "convert.bbox.crop_image",
                    "input_values": {"image": image, "bbox": bbox},
                },
            ],
            "links": [],
            "output_nodes": [
                {"node_id": "crop", "port": "image", "alias": "crop"},
                {"node_id": "crop", "port": "width", "alias": "w"},
                {"node_id": "crop", "port": "height", "alias": "h"},
            ],
        }
        outputs = _run(graph)
        assert outputs["w"] == 32
        assert outputs["h"] == 24


# ----------------------------------------------------------------------
# Detection converters
# ----------------------------------------------------------------------


class TestDetectionConverters:
    def test_xyxy_to_xywh_round_trip(self) -> None:
        det = {
            "_type": "Detections2D",
            "image_width": 100,
            "image_height": 80,
            "boxes": [_bbox(10, 20, 30, 50), _bbox(0, 0, 10, 10, 0.5, 1, "x")],
            "image": "",
        }
        graph = {
            "nodes": [
                {
                    "id": "to_xywh",
                    "type": "convert.detections2d.xyxy_to_xywh",
                    "input_values": {"detections": det},
                },
                {"id": "back", "type": "convert.detections2d.xywh_to_xyxy"},
            ],
            "links": [
                {"from_node": "to_xywh", "from_port": "detections", "to_node": "back", "to_port": "detections"},
            ],
            "output_nodes": [
                {"node_id": "back", "port": "detections", "alias": "out"},
            ],
        }
        outputs = _run(graph)
        boxes = outputs["out"]["boxes"]
        assert len(boxes) == 2
        for orig, recovered in zip(det["boxes"], boxes):
            assert pytest.approx(orig["x1"], abs=1e-6) == recovered["x1"]
            assert pytest.approx(orig["y1"], abs=1e-6) == recovered["y1"]
            assert pytest.approx(orig["x2"], abs=1e-6) == recovered["x2"]
            assert pytest.approx(orig["y2"], abs=1e-6) == recovered["y2"]

    def test_pose_to_detections2d(self) -> None:
        kp = {
            "_type": "Keypoints",
            "instances": [
                {"keypoints": [[10.0, 10.0, 1.0], [20.0, 30.0, 1.0], [5.0, 25.0, 0.0]]},
                {"keypoints": [[50.0, 50.0, 1.0], [60.0, 60.0, 1.0]]},
            ],
        }
        graph = {
            "nodes": [
                {
                    "id": "to_dets",
                    "type": "convert.detections2d.from_pose",
                    "input_values": {
                        "keypoints": kp,
                        "min_visibility": 0.5,
                        "padding": 0.0,
                    },
                },
            ],
            "links": [],
            "output_nodes": [
                {"node_id": "to_dets", "port": "boxes", "alias": "boxes"},
                {"node_id": "to_dets", "port": "count", "alias": "count"},
            ],
        }
        outputs = _run(graph)
        assert outputs["count"] == 2
        boxes = outputs["boxes"]
        # First instance — visible kps are (10,10) and (20,30); the (5,25) kp
        # has visibility 0.0 and must be excluded.
        first = boxes[0]
        assert first["x1"] == 10.0 and first["x2"] == 20.0
        assert first["y1"] == 10.0 and first["y2"] == 30.0
        # Second instance — both kps visible.
        second = boxes[1]
        assert second["x1"] == 50.0 and second["x2"] == 60.0

    def test_merge_dedup(self) -> None:
        a = {
            "_type": "Detections2D",
            "image_width": 100, "image_height": 100, "image": "",
            "boxes": [_bbox(10, 10, 30, 30, 0.5, 0, "x")],
        }
        b = {
            "_type": "Detections2D",
            "image_width": 100, "image_height": 100, "image": "",
            "boxes": [
                _bbox(11, 11, 31, 31, 0.9, 0, "x"),  # almost identical to a's box
                _bbox(80, 80, 90, 90, 0.8, 1, "y"),  # disjoint
            ],
        }
        graph = {
            "nodes": [
                {
                    "id": "merge",
                    "type": "convert.detections.merge",
                    "input_values": {
                        "detections_a": a,
                        "detections_b": b,
                        "iou_threshold": 0.5,
                    },
                },
            ],
            "links": [],
            "output_nodes": [
                {"node_id": "merge", "port": "count", "alias": "count"},
                {"node_id": "merge", "port": "detections", "alias": "out"},
            ],
        }
        outputs = _run(graph)
        # Two duplicates collapse to one; the disjoint box stays. Total 2.
        assert outputs["count"] == 2
        # Higher-confidence box wins the duplicate slot.
        kept = sorted(outputs["out"]["boxes"], key=lambda b: b["x1"])
        assert kept[0]["confidence"] == 0.9


# ----------------------------------------------------------------------
# Point cloud converters
# ----------------------------------------------------------------------


class TestPointCloudConverters:
    def test_subsample_random(self) -> None:
        rng = np.random.default_rng(0)
        pts = rng.normal(size=(2000, 3)).astype(np.float32)
        graph = {
            "nodes": [
                {
                    "id": "down",
                    "type": "convert.pointcloud.subsample",
                    "input_values": {
                        "point_cloud": _pc(pts),
                        "strategy": "random",
                        "max_points": 512,
                        "seed": 7,
                    },
                },
            ],
            "links": [],
            "output_nodes": [
                {"node_id": "down", "port": "num_points", "alias": "n"},
            ],
        }
        outputs = _run(graph)
        assert outputs["n"] == 512

    def test_subsample_voxel_caps_total(self) -> None:
        # All points share the same voxel.
        pts = np.full((128, 3), 0.001, dtype=np.float32)
        graph = {
            "nodes": [
                {
                    "id": "down",
                    "type": "convert.pointcloud.subsample",
                    "input_values": {
                        "point_cloud": _pc(pts),
                        "strategy": "voxel",
                        "voxel_size": 1.0,
                        "max_points": 32,
                    },
                },
            ],
            "links": [],
            "output_nodes": [
                {"node_id": "down", "port": "num_points", "alias": "n"},
            ],
        }
        outputs = _run(graph)
        # All points collapse to a single voxel representative.
        assert outputs["n"] == 1

    def test_crop_box_excludes_corners(self) -> None:
        # 8 points at the corners of a unit cube; cropping to the central
        # cube (size 0.5) should leave none.
        pts = np.array([
            [-1, -1, -1], [1, -1, -1], [-1, 1, -1], [1, 1, -1],
            [-1, -1, 1], [1, -1, 1], [-1, 1, 1], [1, 1, 1],
        ], dtype=np.float32)
        bbox = {
            "id": None, "center": [0.0, 0.0, 0.0], "size": [0.5, 0.5, 0.5],
            "rotation": None, "velocity": None, "confidence": None,
            "class_id": None, "class_name": None, "frame": "world",
        }
        graph = {
            "nodes": [
                {
                    "id": "crop",
                    "type": "convert.pointcloud.crop_box",
                    "input_values": {"point_cloud": _pc(pts), "bbox": bbox},
                },
            ],
            "links": [],
            "output_nodes": [
                {"node_id": "crop", "port": "num_points", "alias": "n"},
            ],
        }
        outputs = _run(graph)
        assert outputs["n"] == 0

    def test_depth_to_pointcloud(self) -> None:
        # A 4x3 depthmap of constant 2.0 metres.
        h, w = 3, 4
        depth = np.full((h, w), 2.0, dtype=np.float32)
        depth_b64 = base64.b64encode(depth.tobytes()).decode("ascii")
        depth_record = {
            "_type": "DepthMap",
            "width": w, "height": h,
            "depth_b64": depth_b64,
            "min_depth": 2.0, "max_depth": 2.0,
            "image": None,
        }
        graph = {
            "nodes": [
                {
                    "id": "to_pc",
                    "type": "convert.depth.to_pointcloud",
                    "input_values": {
                        "depth": depth_record,
                        "fx": 100.0, "fy": 100.0,
                        "cx": -1.0, "cy": -1.0,  # auto-centre
                        "min_depth": 0.0, "max_depth": 10.0,
                        "step": 1,
                    },
                },
            ],
            "links": [],
            "output_nodes": [
                {"node_id": "to_pc", "port": "num_points", "alias": "n"},
                {"node_id": "to_pc", "port": "point_cloud", "alias": "pc"},
            ],
        }
        outputs = _run(graph)
        # Every pixel projects to a finite point.
        assert outputs["n"] == w * h
        # Decode positions and check that z is the depth we set.
        pc = outputs["pc"]
        positions = np.frombuffer(
            base64.b64decode(pc["positions_b64"]), dtype=np.float32
        ).reshape(-1, 3)
        assert np.allclose(positions[:, 2], 2.0)


# ----------------------------------------------------------------------
# List / record / scalar
# ----------------------------------------------------------------------


class TestListAndScalarConverters:
    def test_list_first_and_length(self) -> None:
        items = [10, 20, 30]
        graph = {
            "nodes": [
                {
                    "id": "first",
                    "type": "convert.list.to_first",
                    "input_values": {"items": items},
                },
                {
                    "id": "length",
                    "type": "convert.list.length",
                    "input_values": {"items": items},
                },
            ],
            "links": [],
            "output_nodes": [
                {"node_id": "first", "port": "value", "alias": "first"},
                {"node_id": "length", "port": "length", "alias": "len"},
            ],
        }
        outputs = _run(graph)
        assert outputs["first"] == 10
        assert outputs["len"] == 3

    def test_list_first_empty_errors(self) -> None:
        graph = {
            "nodes": [
                {
                    "id": "first",
                    "type": "convert.list.to_first",
                    "input_values": {"items": []},
                },
            ],
            "links": [],
            "output_nodes": [
                {"node_id": "first", "port": "value", "alias": "first"},
            ],
        }
        result = GraphExecutor(graph).run()
        # Find the error trace entry — runtime should not crash.
        errored = [t for t in result["trace"] if t.get("logs") and any("ERROR" in str(l) for l in t["logs"])]
        assert errored, "expected the empty-list converter to surface a typed error"

    def test_record_get_present_and_default(self) -> None:
        rec = {"x": 5}
        graph = {
            "nodes": [
                {
                    "id": "x",
                    "type": "convert.record.get",
                    "input_values": {"record": rec, "key": "x", "default": -1},
                },
                {
                    "id": "missing",
                    "type": "convert.record.get",
                    "input_values": {"record": rec, "key": "y", "default": -1},
                },
            ],
            "links": [],
            "output_nodes": [
                {"node_id": "x", "port": "value", "alias": "x"},
                {"node_id": "x", "port": "present", "alias": "x_present"},
                {"node_id": "missing", "port": "value", "alias": "miss"},
                {"node_id": "missing", "port": "present", "alias": "miss_present"},
            ],
        }
        outputs = _run(graph)
        assert outputs["x"] == 5
        assert outputs["x_present"] is True
        assert outputs["miss"] == -1
        assert outputs["miss_present"] is False

    @pytest.mark.parametrize("mode,value,expected", [
        ("truncate", 3.7, 3),
        ("truncate", -3.7, -3),
        ("round", 3.5, 4),
        ("round", 2.5, 2),
        ("floor", 3.7, 3),
        ("floor", -3.2, -4),
        ("ceil", -3.2, -3),
        ("ceil", 3.2, 4),
    ])
    def test_float_to_int_modes(self, mode: str, value: float, expected: int) -> None:
        graph = {
            "nodes": [
                {
                    "id": "f",
                    "type": "convert.scalar.float_to_int",
                    "input_values": {"value": value, "mode": mode},
                },
            ],
            "links": [],
            "output_nodes": [{"node_id": "f", "port": "value", "alias": "v"}],
        }
        assert _run(graph)["v"] == expected

    def test_int_to_string_pad(self) -> None:
        graph = {
            "nodes": [
                {
                    "id": "i",
                    "type": "convert.scalar.int_to_string",
                    "input_values": {"value": 42, "pad_width": 5},
                },
            ],
            "links": [],
            "output_nodes": [{"node_id": "i", "port": "value", "alias": "v"}],
        }
        assert _run(graph)["v"] == "00042"

    def test_float_to_string_styles(self) -> None:
        graph = {
            "nodes": [
                {
                    "id": "fix",
                    "type": "convert.scalar.float_to_string",
                    "input_values": {"value": 1.23456, "precision": 2, "style": "fixed"},
                },
                {
                    "id": "exp",
                    "type": "convert.scalar.float_to_string",
                    "input_values": {"value": 12345.0, "precision": 1, "style": "exponential"},
                },
            ],
            "links": [],
            "output_nodes": [
                {"node_id": "fix", "port": "value", "alias": "fix"},
                {"node_id": "exp", "port": "value", "alias": "exp"},
            ],
        }
        outputs = _run(graph)
        assert outputs["fix"] == "1.23"
        assert outputs["exp"].startswith("1.2") and "e" in outputs["exp"]


# ----------------------------------------------------------------------
# Spec-level expectations
# ----------------------------------------------------------------------


class TestConverterRegistry:
    def test_every_converter_declares_metadata(self) -> None:
        from app.nodes import list_node_definitions

        defs = list_node_definitions()
        converters = [d for d in defs if d.get("node_type", "").startswith("convert.")]
        assert converters, "expected at least one converter to be registered"
        for spec in converters:
            meta = spec.get("metadata") or {}
            assert "convert_from" in meta and meta["convert_from"], (
                f"{spec['node_type']} missing metadata.convert_from"
            )
            assert "convert_to" in meta and meta["convert_to"], (
                f"{spec['node_type']} missing metadata.convert_to"
            )
            assert isinstance(meta.get("cost"), int), f"{spec['node_type']} missing cost"

    def test_node_count_grew(self) -> None:
        from app.nodes import list_node_definitions

        defs = list_node_definitions()
        converters = [d for d in defs if d.get("node_type", "").startswith("convert.")]
        # Per the design doc target subset: 12+ converters.
        assert len(converters) >= 12


class TestConvertersEndpoint:
    def test_endpoint_returns_indexable_payload(self) -> None:
        from fastapi.testclient import TestClient

        from app.auth import get_current_user
        from app.main import app

        # The endpoint is auth-protected. Override the dependency with a
        # stub user so the test exercises the converter index logic rather
        # than the auth layer.
        class _StubUser:
            id = "test-user"

        app.dependency_overrides[get_current_user] = lambda: _StubUser()
        try:
            client = TestClient(app)
            response = client.get("/api/converters")
            assert response.status_code == 200
            payload = response.json()
            converters = payload["converters"]
            assert isinstance(converters, list) and converters
            for entry in converters:
                assert entry["node_type"].startswith("convert.")
                assert entry["from_kind"]
                assert entry["to_kind"]
                assert isinstance(entry["cost"], int)
            # The image group must be reachable from grayscale → image.
            types = {(c["from_kind"], c["to_kind"]) for c in converters}
            assert ("image", "image") in types
            assert ("depthmap", "pointcloud") in types
            assert ("detections2d", "detections2d") in types
        finally:
            app.dependency_overrides.pop(get_current_user, None)


# ----------------------------------------------------------------------
# Supervision marshalling
# ----------------------------------------------------------------------


class TestSupervisionMarshalling:
    def test_round_trip_sv_detections(self) -> None:
        det = {
            "_type": "Detections2D",
            "image_width": 100, "image_height": 100, "image": "",
            "boxes": [_bbox(0, 0, 10, 10, 0.5, 0, "a"), _bbox(20, 20, 30, 30, 0.9, 1, "b")],
        }
        # Detections2D -> sv.Detections -> Detections2D with class names so
        # we can compare class_name fidelity through the round trip.
        graph = {
            "nodes": [
                {
                    "id": "to_sv",
                    "type": "convert.sv.detections2d_to_detections",
                    "input_values": {"detections": det},
                },
                {
                    "id": "back",
                    "type": "convert.sv.detections_to_detections2d",
                    "input_values": {
                        "image_width": 100,
                        "image_height": 100,
                        "class_names": "a, b",
                    },
                },
            ],
            "links": [
                {
                    "from_node": "to_sv", "from_port": "detections",
                    "to_node": "back", "to_port": "detections",
                },
            ],
            "output_nodes": [
                {"node_id": "back", "port": "detections", "alias": "out"},
                {"node_id": "back", "port": "count", "alias": "count"},
            ],
        }
        outputs = _run(graph)
        assert outputs["count"] == 2
        boxes = sorted(outputs["out"]["boxes"], key=lambda b: b["x1"])
        # Co-ordinates / confidence / class_id round-trip exactly.
        assert boxes[0]["confidence"] == pytest.approx(0.5)
        assert boxes[1]["confidence"] == pytest.approx(0.9)
        assert boxes[0]["class_id"] == 0
        assert boxes[1]["class_id"] == 1
        # Class names recover from the explicit class_names mapping.
        assert boxes[0]["class_name"] == "a"
        assert boxes[1]["class_name"] == "b"
