"""
Cross-package wiring tests for Phase 1.

These exercise the headline cases from the design doc that *failed* on
master before Phase 1: an image flowing from ``core.image.load`` into
``image.detect.yolo`` (string -> image record), and a 3-D detection
list flowing from ``people.detect`` into ``tracker.kalman3d``
(divergent local vs canonical bbox3d schemas).

The tests build a graph definition and run it through ``GraphBuilder``
— the executor's static validation step. They do *not* execute the
graphs end-to-end (model weights, scipy, etc. would have to be
present); a successful build proves the type system accepts the wiring.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict

import pytest

from app.executor.graph_builder import GraphBuilder


def _import_optional_packages() -> None:
    """Plugin packages register their nodes on import; pull them in once."""
    for module in (
        "stride_yolo.nodes",
        "stride_bytetrack.nodes",
        "stride_kalman.nodes",
        "stride_people.nodes",
    ):
        try:
            importlib.import_module(module)
        except Exception:
            # If a package's heavy deps are missing the spec import will
            # still register, but a transitive ImportError might bail.
            pytest.skip(f"plugin not importable in this env: {module}")


@pytest.fixture(scope="module", autouse=True)
def _load_plugins() -> None:
    _import_optional_packages()


def _build(graph: Dict[str, Any]) -> GraphBuilder:
    """Construct a GraphBuilder and run the static type-validation pass.

    Raises ``GraphExecutionError`` on any type mismatch — the test
    assertion is "this call doesn't raise".
    """
    builder = GraphBuilder(graph)
    builder.build()
    return builder


class TestImageDataflow:
    """``core.image.load.image (image[data_url]) -> image.detect.yolo.image (image)``."""

    def test_load_to_yolo_type_validates(self) -> None:
        graph = {
            "nodes": [
                {
                    "id": "load-1",
                    "type": "core.image.load",
                    "input_values": {"file_path": "sample.png"},
                },
                {
                    "id": "yolo-1",
                    "type": "image.detect.yolo",
                    "input_values": {"weights": "yolo11n.pt"},
                },
            ],
            "links": [
                {
                    "from_node": "load-1",
                    "from_port": "image",
                    "to_node":   "yolo-1",
                    "to_port":   "image",
                },
            ],
            "output_nodes": [
                {"node_id": "yolo-1", "port": "detections", "alias": "detections"},
            ],
        }
        # No exception = type validation passed.
        _build(graph)

    def test_load_to_save_type_validates(self) -> None:
        # Pre-Phase-1, both ends were t_string and this trivially worked.
        # Phase 1: load output is image[data_url] and save input is image
        # (subtype-less). image[data_url] -> image is a widening, so OK.
        graph = {
            "nodes": [
                {
                    "id": "load-1",
                    "type": "core.image.load",
                    "input_values": {"file_path": "sample.png"},
                },
                {
                    "id": "save-1",
                    "type": "core.image.save",
                    "input_values": {"file_path": "out.png"},
                },
            ],
            "links": [
                {
                    "from_node": "load-1",
                    "from_port": "image",
                    "to_node":   "save-1",
                    "to_port":   "image",
                },
            ],
            "output_nodes": [
                {"node_id": "save-1", "port": "saved", "alias": "saved"},
            ],
        }
        _build(graph)


class TestPeopleToKalmanWiring:
    """``people.detect.detections (list<bbox3d>) -> tracker.kalman3d.boxes (list<bbox3d>)``.

    Pre-Phase-1, ``people.detect`` produced ``list<bbox3d>`` where
    ``bbox3d`` was the *local* record schema (``id``, ``center``, ``size``
    only) and ``tracker.kalman3d`` consumed ``list<bbox3d>`` against the
    *canonical* schema with extra fields. Schemas were structurally
    incompatible — the cross-package edge raised a type mismatch at
    build time. Phase 1 unifies the schema in ``stride-core``."""

    def test_people_to_kalman_type_validates(self) -> None:
        graph = {
            "nodes": [
                {
                    "id": "pcd-source",
                    "type": "core.literal.string",
                    "input_values": {"value": ""},
                },
                {
                    "id": "detect-1",
                    "type": "people.detect",
                },
                {
                    "id": "track-1",
                    "type": "tracker.kalman3d",
                },
            ],
            # No data link from pcd-source — people.detect's required
            # `point_cloud` input has a default of None and we want to
            # exercise the *type* validator, not the runtime. Static
            # validation runs over declared link types only.
            "links": [
                {
                    "from_node": "detect-1",
                    "from_port": "detections",
                    "to_node":   "track-1",
                    "to_port":   "boxes",
                },
            ],
            "output_nodes": [
                {"node_id": "track-1", "port": "boxes", "alias": "tracked"},
            ],
        }
        _build(graph)
