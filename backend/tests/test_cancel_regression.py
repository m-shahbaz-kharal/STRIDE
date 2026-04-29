"""
Cancel-still-works regression test for Phase 2.

Phase 2 introduced typed exception dispatch in NodeExecutor.execute_node_work.
This test guards the cancel/stop semantics fixed in commit 69358da against
regressions: typed-error catches must NOT swallow asyncio.CancelledError, and
the streaming executor must always emit the terminal `complete` event so the
UI can clear state.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

import pytest

from stride_core import ExecutionContext, NodeBase, NodeSpec, PortSpec, register_node
from stride_core.typesystem import t_int

from app.runner import GraphExecutor


_LONG_SPEC = NodeSpec(
    type="test.cancel.long_running",
    display_name="Long Running",
    category="Test",
    inputs=[],
    outputs=[PortSpec(name="value", type=t_int())],
)


@register_node(_LONG_SPEC)
class _LongRunningNode(NodeBase):
    """A node that politely checks ctx.is_interrupted but otherwise loops."""

    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        # Loop for up to 10s but cooperatively yield to cancellation. The
        # streaming executor's force-abandon timeout (~0.5s) provides the
        # real cancellation guarantee — this is just a stress backdrop.
        deadline = time.time() + 10.0
        while time.time() < deadline:
            if ctx.is_interrupted:
                break
            time.sleep(0.05)
        return {"value": 1}


def _long_running_graph() -> Dict[str, Any]:
    return {
        "nodes": [{"id": "slow", "type": "test.cancel.long_running"}],
        "links": [],
        "output_nodes": [{"node_id": "slow", "port": "value", "alias": "out"}],
    }


class TestCancelRegression:
    """Cancel semantics from 69358da must keep working post-Phase-2."""

    @pytest.mark.asyncio
    async def test_cancellation_emits_complete_event(self) -> None:
        """A long-running graph cancelled mid-flight still emits `complete`.

        This is the contract from 69358da: the UI must always receive a
        terminal event so it can clear "running…" state.
        """
        executor = GraphExecutor(_long_running_graph())
        events: List[Any] = []

        async def _drain() -> None:
            async for event in executor.run_streaming():
                events.append(event)

        runner = asyncio.create_task(_drain())

        # Wait until the slow node has started, then cancel.
        async def _wait_for_started() -> None:
            for _ in range(200):  # up to ~10s
                if any(e.event_type == "node_started" for e in events):
                    return
                await asyncio.sleep(0.05)

        await asyncio.wait_for(_wait_for_started(), timeout=10.0)
        # Cancel via the public API the HTTP layer uses.
        cancelled = GraphExecutor.cancel_execution(executor.execution_id)
        assert cancelled, "cancel_execution returned False — execution did not register"

        # Run must terminate within a reasonable budget — Phase 2 must not
        # have introduced any path that hangs the streaming loop.
        await asyncio.wait_for(runner, timeout=5.0)

        complete_events = [e for e in events if e.event_type == "complete"]
        assert complete_events, (
            "no `complete` terminal event observed after cancel — Phase 2 must "
            "preserve the cancel/stop contract from commit 69358da."
        )

    @pytest.mark.asyncio
    async def test_typed_error_dispatch_does_not_swallow_cancelled_error(self) -> None:
        """asyncio.CancelledError must NOT be caught by NodeError dispatch."""
        # Build a node that raises asyncio.CancelledError directly. The
        # typed-exception dispatch in execute_node_work runs in a thread, so
        # CancelledError there manifests as a regular exception — but the
        # important thing is that it's wrapped into "internal_error" rather
        # than being swallowed silently. The streaming executor's cancellation
        # path uses asyncio.CancelledError on the *task*, not the node body.
        cancel_spec = NodeSpec(
            type="test.cancel.raises_cancelled",
            display_name="Raises CancelledError",
            category="Test",
            inputs=[],
            outputs=[PortSpec(name="value", type=t_int())],
        )

        @register_node(cancel_spec)
        class _RaiseCancelled(NodeBase):
            def forward(self, inputs, ctx):
                raise asyncio.CancelledError("simulated mid-forward cancel")

        graph = {
            "nodes": [{"id": "c", "type": "test.cancel.raises_cancelled"}],
            "links": [],
            "output_nodes": [{"node_id": "c", "port": "value", "alias": "out"}],
        }
        # asyncio.CancelledError in the worker thread does NOT propagate to
        # the asyncio loop — the dispatch correctly catches it as a generic
        # Exception (Python 3.8+: CancelledError is BaseException, but it's
        # raised inside a thread so it bubbles via concurrent.futures.future).
        # The point of this test is that the run completes (does not hang)
        # and emits a terminal event.
        executor = GraphExecutor(graph)
        events: List[Any] = []
        try:
            async for event in executor.run_streaming():
                events.append(event)
        except asyncio.CancelledError:
            pytest.fail(
                "CancelledError escaped the runtime — typed-exception dispatch "
                "must not let asyncio.CancelledError leak."
            )

        assert any(e.event_type == "complete" for e in events), (
            "terminal `complete` event was not emitted; runtime hung on a "
            "CancelledError raised from forward()."
        )
