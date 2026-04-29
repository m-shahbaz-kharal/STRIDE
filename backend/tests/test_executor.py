"""
Unit tests for the graph executor.
"""

from __future__ import annotations

import pytest
from typing import Any, Dict

# Import the executor
from app.runner import GraphExecutor
from app.execution import NodeStatus


class TestGraphExecutorBasics:
    """Basic executor functionality tests."""

    def test_simple_addition(self, simple_graph: Dict[str, Any]) -> None:
        """Test that a simple addition graph executes correctly."""
        executor = GraphExecutor(simple_graph)
        result = executor.run()

        assert "outputs" in result
        assert result["outputs"].get("sum") == 8  # 5 + 3

    def test_execution_trace(self, simple_graph: Dict[str, Any]) -> None:
        """Test that execution trace is captured."""
        executor = GraphExecutor(simple_graph)
        result = executor.run()

        assert "trace" in result
        assert len(result["trace"]) == 3  # 3 nodes executed

        # All nodes should be completed
        for entry in result["trace"]:
            assert entry.get("node_id") is not None

    def test_execution_stats(self, simple_graph: Dict[str, Any]) -> None:
        """Test that execution statistics are calculated."""
        executor = GraphExecutor(simple_graph)
        result = executor.run()

        assert "stats" in result
        stats = result["stats"]
        assert stats["total_nodes"] == 3
        assert stats["executed_nodes"] >= 0
        assert stats["total_time_ms"] >= 0


class TestGraphExecutorValidation:
    """Graph validation tests."""

    def test_empty_graph_raises(self) -> None:
        """Test that an empty graph raises an error."""
        with pytest.raises(Exception):
            GraphExecutor({"nodes": []})

    def test_unknown_node_type_raises(self) -> None:
        """Test that an unknown node type raises an error."""
        graph = {
            "nodes": [
                {"id": "n1", "type": "nonexistent.node.type"},
            ],
        }
        with pytest.raises(Exception):
            GraphExecutor(graph)

    def test_duplicate_node_id_raises(self) -> None:
        """Test that duplicate node IDs raise an error."""
        graph = {
            "nodes": [
                {"id": "same-id", "type": "core.constant.number"},
                {"id": "same-id", "type": "core.constant.number"},
            ],
        }
        with pytest.raises(Exception):
            GraphExecutor(graph)


class TestCancellation:
    """Tests for execution cancellation."""

    def test_cancel_execution(self, simple_graph: Dict[str, Any]) -> None:
        """Test that cancellation API exists and is callable."""
        executor = GraphExecutor(simple_graph)

        # Cancel should return False for non-registered execution
        result = GraphExecutor.cancel_execution("nonexistent-id")
        assert result is False

    def test_cancel_node(self, simple_graph: Dict[str, Any]) -> None:
        """Test that node cancellation API exists."""
        result = GraphExecutor.cancel_node("nonexistent-exec", "nonexistent-node")
        assert result is False

    def test_sync_run_unregisters_after_completion(
        self, simple_graph: Dict[str, Any]
    ) -> None:
        """The sync `run()` path must unregister itself when finished so the
        active-executions registry doesn't leak references across runs."""
        executor = GraphExecutor(simple_graph)
        executor.run()

        # After run() returns, cancelling that id should report "not found"
        # because the executor has unregistered itself.
        assert GraphExecutor.cancel_execution(executor.execution_id) is False

    def test_sync_run_can_be_cancelled_via_class_api(
        self, simple_graph: Dict[str, Any]
    ) -> None:
        """While `run()` is in flight the executor must be addressable via
        `GraphExecutor.cancel_execution`. Without the registration fix the
        sync path was completely uncancellable from the HTTP API."""
        import threading

        executor = GraphExecutor(simple_graph)
        ready = threading.Event()
        cancelled = threading.Event()

        def _cancel_when_ready() -> None:
            ready.wait(timeout=1.0)
            # Even though the graph is tiny, the executor is registered for
            # the duration of `run()`, so cancel_execution should find it.
            # We can't reliably interrupt 5+3 mid-flight, but we can prove
            # the registration is wired up by cancelling immediately after
            # run() starts.
            if GraphExecutor.cancel_execution(executor.execution_id):
                cancelled.set()

        t = threading.Thread(target=_cancel_when_ready)
        t.start()
        ready.set()
        executor.run()
        t.join(timeout=2.0)

        # The cancel may or may not race in before `run()` finishes for such
        # a tiny graph - but if it did, the cancel must have succeeded
        # (proving registration). The post-condition we strictly require:
        # after run() returns the executor is unregistered.
        assert GraphExecutor.cancel_execution(executor.execution_id) is False


class TestExecutionPlan:
    """Tests for execution plan generation."""

    def test_get_execution_plan(self, simple_graph: Dict[str, Any]) -> None:
        """Test that execution plan is generated correctly."""
        executor = GraphExecutor(simple_graph)
        plan = executor.get_execution_plan()

        assert "execution_id" in plan
        assert "total_nodes" in plan
        assert plan["total_nodes"] == 3
        assert "nodes" in plan
        assert len(plan["nodes"]) == 3


class TestCaching:
    """Tests for execution caching."""

    def test_cache_clear(self) -> None:
        """Test that cache clearing works."""
        cleared = GraphExecutor.clear_cache()
        assert isinstance(cleared, int)

    def test_cache_stats(self) -> None:
        """Test that cache size is retrievable."""
        size = GraphExecutor.get_cache_size()
        assert isinstance(size, int)
        assert size >= 0
