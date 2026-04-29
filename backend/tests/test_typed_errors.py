"""
Typed exception dispatch tests for Phase 2.

Verifies that each ``NodeError`` subclass produces a NodeExecutionResult
with the correct ``error_code`` and a structured ``error_payload`` that
matches §6.3 of the design doc, and that the streaming WS event surfaces
the payload to the frontend.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from stride_core import (
    ExecutionContext,
    NodeBase,
    NodeSpec,
    PortSpec,
    register_node,
)
from stride_core.errors import (
    NodeCancelled,
    NodeError,
    NodeFileNotFoundError,
    NodeInputError,
    NodeMissingDependencyError,
    NodeNetworkError,
    NodeRuntimeError,
    NodeTypeError,
)
from stride_core.typesystem import t_int

from app.execution import NodeStatus
from app.runner import GraphExecutor


# Each subclass gets its own probe node so we can isolate dispatch.

def _make_raising_node(node_type: str, exc_factory):
    spec = NodeSpec(
        type=node_type,
        display_name=node_type,
        category="Test",
        inputs=[],
        outputs=[PortSpec(name="value", type=t_int())],
    )

    @register_node(spec)
    class _Raise(NodeBase):
        def forward(self, inputs, ctx):
            raise exc_factory()

    return spec


_make_raising_node(
    "test.error.input",
    lambda: NodeInputError(
        "value out of range",
        port="threshold",
        details={"got": -1, "min": 0},
    ),
)
_make_raising_node(
    "test.error.missing_dep",
    lambda: NodeMissingDependencyError("torch not installed"),
)
_make_raising_node(
    "test.error.runtime",
    lambda: NodeRuntimeError("GPU OOM", details={"alloc_mb": 9999}),
)
_make_raising_node(
    "test.error.cancelled",
    lambda: NodeCancelled("user pressed stop"),
)
_make_raising_node(
    "test.error.file_not_found",
    lambda: NodeFileNotFoundError("missing model weights"),
)
_make_raising_node(
    "test.error.network",
    lambda: NodeNetworkError("rtsp connection refused"),
)
_make_raising_node(
    "test.error.type",
    lambda: NodeTypeError("expected StreamResource, got dict"),
)
_make_raising_node(
    "test.error.untyped",
    lambda: ValueError("oh no"),
)


# A custom NodeError subclass to exercise the catch-all branch.
class _CustomNodeError(NodeError):
    code = "custom_error"


_make_raising_node(
    "test.error.custom",
    lambda: _CustomNodeError("a brand new error", details={"k": "v"}),
)


def _single_node_graph(node_type: str) -> Dict[str, Any]:
    return {
        "nodes": [{"id": "n", "type": node_type}],
        "links": [],
        "output_nodes": [{"node_id": "n", "port": "value", "alias": "out"}],
    }


def _run_and_get_entry(node_type: str):
    executor = GraphExecutor(_single_node_graph(node_type))
    executor.run()
    assert len(executor.execution_trace) == 1
    return executor.execution_trace[0]


class TestTypedErrorDispatch:
    """Each NodeError subclass produces a structured ERROR result."""

    def test_node_input_error(self) -> None:
        entry = _run_and_get_entry("test.error.input")
        assert entry.status == NodeStatus.ERROR
        assert entry.error_code == "node_input_error"
        assert entry.error_payload is not None
        assert entry.error_payload["code"] == "node_input_error"
        assert entry.error_payload["port"] == "threshold"
        assert entry.error_payload["details"]["got"] == -1
        assert entry.error_payload["details"]["min"] == 0
        # Traceback should be present in the details for dev-mode dumps.
        assert "traceback" in entry.error_payload["details"]

    def test_node_missing_dependency_error(self) -> None:
        entry = _run_and_get_entry("test.error.missing_dep")
        assert entry.status == NodeStatus.ERROR
        assert entry.error_code == "node_missing_dependency"
        assert entry.error_payload["code"] == "node_missing_dependency"

    def test_node_runtime_error(self) -> None:
        entry = _run_and_get_entry("test.error.runtime")
        assert entry.status == NodeStatus.ERROR
        assert entry.error_code == "node_runtime_error"
        assert entry.error_payload["details"]["alloc_mb"] == 9999

    def test_node_cancelled_is_skipped_not_errored(self) -> None:
        """NodeCancelled is special: not an error in stats — surfaced as SKIPPED."""
        entry = _run_and_get_entry("test.error.cancelled")
        assert entry.status == NodeStatus.SKIPPED
        # The typed payload is still attached so the UI can render
        # "cancelled" rather than "errored".
        assert entry.error_code == "node_cancelled"
        assert entry.error_payload["code"] == "node_cancelled"

    def test_node_file_not_found_error(self) -> None:
        entry = _run_and_get_entry("test.error.file_not_found")
        assert entry.error_code == "node_file_not_found"

    def test_node_network_error(self) -> None:
        entry = _run_and_get_entry("test.error.network")
        assert entry.error_code == "node_network_error"

    def test_node_type_error(self) -> None:
        entry = _run_and_get_entry("test.error.type")
        assert entry.error_code == "node_type_error"

    def test_custom_node_error_falls_through_catch_all(self) -> None:
        """An out-of-tree NodeError subclass still gets its custom code."""
        entry = _run_and_get_entry("test.error.custom")
        assert entry.status == NodeStatus.ERROR
        assert entry.error_code == "custom_error"
        assert entry.error_payload["code"] == "custom_error"
        assert entry.error_payload["details"]["k"] == "v"

    def test_untyped_exception_wraps_to_internal_error(self) -> None:
        """Bare Exception becomes NodeRuntimeError(code='internal_error')."""
        entry = _run_and_get_entry("test.error.untyped")
        assert entry.status == NodeStatus.ERROR
        assert entry.error_code == "internal_error"
        assert entry.error_payload["code"] == "internal_error"
        assert entry.error_payload["details"]["exception_type"] == "ValueError"
        # Traceback always captured on the wrapper-of-last-resort path.
        assert "traceback" in entry.error_payload["details"]


class TestStreamingErrorPayload:
    """Verify the WS streaming path threads error_payload to events."""

    @pytest.mark.asyncio
    async def test_node_error_event_carries_error_payload(self) -> None:
        executor = GraphExecutor(_single_node_graph("test.error.runtime"))
        events: List[Any] = []
        async for event in executor.run_streaming():
            events.append(event)

        node_error_events = [e for e in events if e.event_type == "node_error"]
        assert node_error_events, "expected at least one node_error event"
        evt = node_error_events[0]
        assert evt.error_code == "node_runtime_error"
        assert evt.error_payload is not None
        assert evt.error_payload["code"] == "node_runtime_error"
        # The terminal complete event must still arrive — the runtime is
        # contractually unable to "hang" on an error.
        assert any(e.event_type == "complete" for e in events)

    @pytest.mark.asyncio
    async def test_internal_error_event_payload_shape(self) -> None:
        executor = GraphExecutor(_single_node_graph("test.error.untyped"))
        events: List[Any] = []
        async for event in executor.run_streaming():
            events.append(event)

        evt = next(e for e in events if e.event_type == "node_error")
        assert evt.error_code == "internal_error"
        assert evt.error_payload["code"] == "internal_error"
        # System never crashes: terminal event still fires.
        assert any(e.event_type == "complete" for e in events)
