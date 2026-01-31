"""
Tests for the ready-queue scheduler.

Verifies scheduling behavior:
- Initial ready queue computation
- Dependency tracking
- Failure propagation
"""

import pytest
from app.executor.scheduler import ReadyQueueScheduler, LoopIterationScheduler
from app.execution import NodeStatus


class TestReadyQueueScheduler:
    """Tests for ReadyQueueScheduler."""

    def test_initial_ready_queue_empty_graph(self):
        """Empty graph has empty ready queue."""
        scheduler = ReadyQueueScheduler(
            execution_set=set(),
            input_map={},
            control_inputs={},
            dependents={},
            node_status={},
        )

        ready = scheduler.compute_initial_ready_queue()
        assert len(ready) == 0

    def test_initial_ready_queue_no_dependencies(self):
        """Nodes with no dependencies are immediately ready."""
        execution_set = {"a", "b", "c"}
        scheduler = ReadyQueueScheduler(
            execution_set=execution_set,
            input_map={},
            control_inputs={},
            dependents={},
            node_status={n: NodeStatus.PENDING for n in execution_set},
        )

        ready = scheduler.compute_initial_ready_queue()
        assert set(ready) == {"a", "b", "c"}

    def test_initial_ready_queue_with_dependencies(self):
        """Only nodes with no inputs are initially ready."""
        # a -> b -> c (linear chain)

        class MockLink:
            def __init__(self, from_node, from_port):
                self.from_node = from_node
                self.from_port = from_port

        execution_set = {"a", "b", "c"}
        scheduler = ReadyQueueScheduler(
            execution_set=execution_set,
            input_map={
                "b": {"input": MockLink("a", "output")},
                "c": {"input": MockLink("b", "output")},
            },
            control_inputs={},
            dependents={
                "a": ["b"],
                "b": ["c"],
            },
            node_status={n: NodeStatus.PENDING for n in execution_set},
        )

        ready = scheduler.compute_initial_ready_queue()
        assert set(ready) == {"a"}

    def test_mark_node_complete_enqueues_dependents(self):
        """Completing a node enqueues its dependents when all inputs ready."""

        class MockLink:
            def __init__(self, from_node, from_port):
                self.from_node = from_node
                self.from_port = from_port

        execution_set = {"a", "b"}
        scheduler = ReadyQueueScheduler(
            execution_set=execution_set,
            input_map={
                "b": {"input": MockLink("a", "output")},
            },
            control_inputs={},
            dependents={
                "a": ["b"],
            },
            node_status={n: NodeStatus.PENDING for n in execution_set},
        )

        scheduler.compute_initial_ready_queue()
        assert scheduler.get_next_ready() == "a"

        # Mark a complete - b should become ready
        newly_ready = scheduler.mark_node_complete("a")
        assert "b" in newly_ready

    def test_mark_node_failed_skips_dependents(self):
        """Failed node causes all dependents to be skipped."""

        class MockLink:
            def __init__(self, from_node, from_port):
                self.from_node = from_node
                self.from_port = from_port

        # a -> b -> c (linear)
        execution_set = {"a", "b", "c"}
        scheduler = ReadyQueueScheduler(
            execution_set=execution_set,
            input_map={
                "b": {"input": MockLink("a", "output")},
                "c": {"input": MockLink("b", "output")},
            },
            control_inputs={},
            dependents={
                "a": ["b"],
                "b": ["c"],
            },
            node_status={n: NodeStatus.PENDING for n in execution_set},
        )

        scheduler.compute_initial_ready_queue()

        # Mark a as failed - both b and c should be skipped
        to_skip = scheduler.mark_node_failed("a")
        assert set(to_skip) == {"b", "c"}

    def test_parallel_branches_both_ready(self):
        """Parallel branches are both ready when source completes."""

        class MockLink:
            def __init__(self, from_node, from_port):
                self.from_node = from_node
                self.from_port = from_port

        # a -> [b, c] (parallel)
        execution_set = {"a", "b", "c"}
        scheduler = ReadyQueueScheduler(
            execution_set=execution_set,
            input_map={
                "b": {"input": MockLink("a", "out1")},
                "c": {"input": MockLink("a", "out2")},
            },
            control_inputs={},
            dependents={
                "a": ["b", "c"],
            },
            node_status={n: NodeStatus.PENDING for n in execution_set},
        )

        scheduler.compute_initial_ready_queue()
        assert scheduler.get_next_ready() == "a"

        newly_ready = scheduler.mark_node_complete("a")
        assert set(newly_ready) == {"b", "c"}


class TestLoopIterationScheduler:
    """Tests for LoopIterationScheduler."""

    def test_iterates_through_body_order(self):
        """Scheduler returns nodes in topological order."""
        scheduler = LoopIterationScheduler(
            body_nodes={"a", "b", "c"},
            body_order=["a", "b", "c"],
        )

        assert scheduler.get_next() == "a"
        assert scheduler.get_next() == "b"
        assert scheduler.get_next() == "c"
        assert scheduler.get_next() is None

    def test_reset_restarts_iteration(self):
        """Reset allows starting a new iteration."""
        scheduler = LoopIterationScheduler(
            body_nodes={"a"},
            body_order=["a"],
        )

        assert scheduler.get_next() == "a"
        assert scheduler.get_next() is None

        scheduler.reset()
        assert scheduler.get_next() == "a"

    def test_has_more(self):
        """has_more correctly reports remaining nodes."""
        scheduler = LoopIterationScheduler(
            body_nodes={"a", "b"},
            body_order=["a", "b"],
        )

        assert scheduler.has_more() is True
        scheduler.get_next()
        assert scheduler.has_more() is True
        scheduler.get_next()
        assert scheduler.has_more() is False
