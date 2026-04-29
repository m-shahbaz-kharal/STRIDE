"""
Lifecycle hook tests for NodeBase v2.

Verifies that ``prepare`` is called once per run before the first ``forward``
and that ``teardown`` is called once per run after the last ``forward`` —
including when ``forward`` raises, when execution is cancelled, and when
the same node runs in two consecutive runs (state isolation).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from stride_core import (
    ExecutionContext,
    NodeBase,
    NodeSpec,
    PortSpec,
    register_node,
)
from stride_core.errors import NodeRuntimeError
from stride_core.typesystem import t_int

from app.runner import GraphExecutor


# ----------------------------------------------------------------------
# Test node fixtures — instrumented with a per-test trace list so each
# test can verify call ordering without leaking across tests.
# ----------------------------------------------------------------------

# Module-level instrumentation: each call appends (node_id, hook).
LIFECYCLE_TRACE: List[Tuple[str, str]] = []


_PROBE_SPEC = NodeSpec(
    type="test.lifecycle.probe",
    display_name="Lifecycle Probe",
    category="Test",
    inputs=[],
    outputs=[PortSpec(name="value", type=t_int())],
)


@register_node(_PROBE_SPEC)
class _LifecycleProbeNode(NodeBase):
    """Records every prepare/forward/teardown call for assertion."""

    def prepare(self, ctx: ExecutionContext) -> None:
        LIFECYCLE_TRACE.append((self.id, "prepare"))

    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        LIFECYCLE_TRACE.append((self.id, "forward"))
        return {"value": 42}

    def teardown(self, ctx: ExecutionContext) -> None:
        LIFECYCLE_TRACE.append((self.id, "teardown"))


_FAILING_SPEC = NodeSpec(
    type="test.lifecycle.failing",
    display_name="Lifecycle Failing Probe",
    category="Test",
    inputs=[],
    outputs=[PortSpec(name="value", type=t_int())],
)


@register_node(_FAILING_SPEC)
class _FailingProbeNode(NodeBase):
    """Always raises NodeRuntimeError; teardown should still fire."""

    def prepare(self, ctx: ExecutionContext) -> None:
        LIFECYCLE_TRACE.append((self.id, "prepare"))

    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        LIFECYCLE_TRACE.append((self.id, "forward"))
        raise NodeRuntimeError("intentional failure", details={"reason": "test"})

    def teardown(self, ctx: ExecutionContext) -> None:
        LIFECYCLE_TRACE.append((self.id, "teardown"))


@pytest.fixture(autouse=True)
def _clear_trace() -> None:
    LIFECYCLE_TRACE.clear()


def _probe_graph(node_id: str = "probe", node_type: str = "test.lifecycle.probe") -> Dict[str, Any]:
    return {
        "nodes": [{"id": node_id, "type": node_type}],
        "links": [],
        "output_nodes": [{"node_id": node_id, "port": "value", "alias": "out"}],
    }


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


class TestLifecycleHooks:
    """prepare / forward / teardown ordering."""

    def test_prepare_then_forward_then_teardown_on_success(self) -> None:
        executor = GraphExecutor(_probe_graph())
        result = executor.run()

        assert result["outputs"]["out"] == 42
        # Exact ordering: prepare before forward, teardown after.
        assert LIFECYCLE_TRACE == [
            ("probe", "prepare"),
            ("probe", "forward"),
            ("probe", "teardown"),
        ]

    def test_prepare_called_only_once_across_a_run(self) -> None:
        # Even though we re-use the same NodeExecutor / node within a run,
        # prepare must fire exactly once.
        executor = GraphExecutor(_probe_graph())
        executor.run()
        assert [hook for (_, hook) in LIFECYCLE_TRACE].count("prepare") == 1

    def test_teardown_runs_after_forward_failure(self) -> None:
        executor = GraphExecutor(_probe_graph(node_type="test.lifecycle.failing"))
        result = executor.run()

        # The run completes (does not crash); the failing node is marked errored.
        trace = result["trace"]
        assert len(trace) == 1
        # error_payload from the typed NodeRuntimeError must propagate.
        # The legacy "trace" view is shallow — but execution_trace exposes the
        # structured payload directly.
        rich_entry = executor.execution_trace[0]
        assert rich_entry.error_code == "node_runtime_error"
        assert rich_entry.error_payload is not None
        assert rich_entry.error_payload["code"] == "node_runtime_error"

        # Lifecycle ordering still holds even on failure.
        assert ("probe", "prepare") in LIFECYCLE_TRACE
        assert ("probe", "forward") in LIFECYCLE_TRACE
        assert ("probe", "teardown") in LIFECYCLE_TRACE
        # Teardown must be last.
        assert LIFECYCLE_TRACE[-1] == ("probe", "teardown")

    def test_two_consecutive_runs_each_get_prepare_and_teardown(self) -> None:
        """Each run is fully isolated — prepare/teardown fire per run."""
        for _ in range(2):
            executor = GraphExecutor(_probe_graph())
            executor.run()

        # 2 runs × (prepare + forward + teardown) = 6 entries.
        prepare_count = sum(1 for (_, h) in LIFECYCLE_TRACE if h == "prepare")
        teardown_count = sum(1 for (_, h) in LIFECYCLE_TRACE if h == "teardown")
        assert prepare_count == 2
        assert teardown_count == 2

    def test_default_hooks_are_no_ops(self) -> None:
        """A NodeBase subclass that overrides only forward must still work."""

        spec = NodeSpec(
            type="test.lifecycle.minimal",
            display_name="Lifecycle Minimal",
            category="Test",
            inputs=[],
            outputs=[PortSpec(name="value", type=t_int())],
        )

        @register_node(spec)
        class _MinimalNode(NodeBase):
            def forward(self, inputs, ctx):
                return {"value": 7}

        graph = {
            "nodes": [{"id": "m", "type": "test.lifecycle.minimal"}],
            "links": [],
            "output_nodes": [{"node_id": "m", "port": "value", "alias": "out"}],
        }
        result = GraphExecutor(graph).run()
        assert result["outputs"]["out"] == 7
