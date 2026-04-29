"""
State-isolation tests for stateful nodes migrated in Phase 2.

Each node previously held its tracker / model state on a module-level
dict, which leaked across consecutive runs. After the migration the
state lives on the ExecutionContext, scoped to a single run. These
tests exercise that semantics for ByteTrack, Kalman3D, and the People
detector.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

# These modules are dynamically imported because the optional plugin
# packages may not be installed; tests skip cleanly in that case.
sv = pytest.importorskip("supervision")
np = pytest.importorskip("numpy")


from stride_core import ExecutionContext, NODE_REGISTRY


def _make_node(node_type: str, node_id: str, params: Dict[str, Any] | None = None):
    """Instantiate a registered node type by walking the registry."""
    info = NODE_REGISTRY[node_type]
    cls = info["class"]
    spec = info["spec"]
    config = {"id": node_id, "type": node_type, "params": params or {}}
    return cls(config, spec=spec)


def _detections_record(boxes: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "_type": "Detections2D",
        "image_width": 640,
        "image_height": 480,
        "boxes": boxes,
        "image": "",
    }


@pytest.fixture
def two_box_record() -> Dict[str, Any]:
    return _detections_record([
        {"x1": 10, "y1": 10, "x2": 50, "y2": 50, "confidence": 0.9, "class_id": 0, "class_name": "person"},
        {"x1": 100, "y1": 100, "x2": 200, "y2": 200, "confidence": 0.85, "class_id": 0, "class_name": "person"},
    ])


def _no_module_dict_in(module, name: str) -> bool:
    return not hasattr(module, name)


class TestByteTrackIsolation:
    """ByteTrack state must reset between runs."""

    def test_module_level_TRACKERS_dict_is_gone(self) -> None:
        """The migration deletes _TRACKERS — no legacy alias allowed."""
        from stride_bytetrack import nodes as bt_nodes

        assert _no_module_dict_in(bt_nodes, "_TRACKERS"), (
            "_TRACKERS was migrated to ExecutionContext; the module-level "
            "dict must be deleted, not aliased."
        )

    def test_consecutive_runs_get_fresh_trackers(self, two_box_record: Dict[str, Any]) -> None:
        """Two consecutive runs each start with track_id=1 (fresh tracker)."""
        if "tracker.bytetrack" not in NODE_REGISTRY:
            pytest.skip("stride-bytetrack not registered in this environment")

        ids_per_run: List[List[int]] = []
        for _ in range(2):
            node = _make_node("tracker.bytetrack", node_id="bt")
            ctx = ExecutionContext()
            # ByteTrack's tracker_id is None until enough updates accrue. Run
            # the same set of detections through several frames so we get
            # stable ids.
            run_ids: List[int] = []
            for _frame in range(6):
                out = node.forward(
                    {
                        "detections": two_box_record,
                        "annotate": False,
                        "reset": False,
                    },
                    ctx,
                )
                run_ids = out["track_ids"]
            ids_per_run.append(sorted(run_ids))

        # Each independent run should produce IDs starting at 1 — the
        # tracker rebuilt itself on every run because ctx.node_resources
        # was a fresh dict.
        assert ids_per_run[0] == [1, 2]
        assert ids_per_run[1] == [1, 2], (
            f"Tracker state leaked across runs; second run produced {ids_per_run[1]} "
            "(expected fresh [1, 2])."
        )

    def test_within_a_run_state_persists(self, two_box_record: Dict[str, Any]) -> None:
        """Within a single run, tracker IDs must persist across forward calls."""
        if "tracker.bytetrack" not in NODE_REGISTRY:
            pytest.skip("stride-bytetrack not registered in this environment")

        node = _make_node("tracker.bytetrack", node_id="bt")
        ctx = ExecutionContext()
        last_ids: List[int] = []
        for _ in range(7):
            out = node.forward(
                {"detections": two_box_record, "annotate": False, "reset": False},
                ctx,
            )
            last_ids = out["track_ids"]
        # IDs should stabilise to the same set across consecutive frames in
        # the same run because the tracker survives.
        assert sorted(last_ids) == [1, 2]


class TestKalmanIsolation:
    """Kalman3D tracker state must reset between runs."""

    def test_module_level_TRACKER_STATES_dict_is_gone(self) -> None:
        from stride_kalman import nodes as k_nodes

        assert _no_module_dict_in(k_nodes, "_TRACKER_STATES"), (
            "_TRACKER_STATES was migrated to ExecutionContext; the module-level "
            "dict must be deleted, not aliased."
        )

    def test_consecutive_runs_restart_id_counter(self) -> None:
        """First track in each run gets id=1 (next_id starts at 1 every run)."""
        if "tracker.kalman3d" not in NODE_REGISTRY:
            pytest.skip("stride-kalman not registered in this environment")

        boxes = [{"center": [1.0, 2.0, 0.5], "size": [0.5, 0.5, 1.7]}]

        seen_first_ids: List[int] = []
        for _ in range(2):
            node = _make_node("tracker.kalman3d", node_id="kf")
            ctx = ExecutionContext()
            # Need enough updates to surface a "confirmed" track (min_hits=2).
            for _ in range(3):
                out = node.forward(
                    {"boxes": boxes, "min_hits": 1},
                    ctx,
                )
            ids = [b["id"] for b in out["boxes"]]
            assert ids, "expected at least one confirmed track"
            seen_first_ids.append(ids[0])

        assert seen_first_ids == [1, 1], (
            f"Kalman id counter leaked across runs; saw first ids {seen_first_ids}."
        )


class TestPeopleNodeIsolation:
    """People detector background model + tracker must reset between runs."""

    def test_module_level_dicts_are_gone(self) -> None:
        from stride_people import nodes as p_nodes

        assert _no_module_dict_in(p_nodes, "_background_models")
        assert _no_module_dict_in(p_nodes, "_trackers")
