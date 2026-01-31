"""
Task completion handler for graph execution.

Handles node completion and failure propagation.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from ..execution import NodeExecutionResult, NodeStatus
    from .events import ExecutionEventEmitter
    from .scheduler import ReadyQueueScheduler


class TaskCompletionHandler:
    """Handles node completion and failure propagation.

    This class is responsible for:
    - Finalizing node results (storing outputs, updating status)
    - Propagating failures to dependent nodes
    - Coordinating with the scheduler to enqueue newly ready nodes
    """

    def __init__(
        self,
        nodes: Dict[str, Any],
        node_status: Dict[str, "NodeStatus"],
        finalize_node_result: Callable,
        scheduler: "ReadyQueueScheduler",
        events: "ExecutionEventEmitter",
        dependents: Dict[str, List[str]],
        execution_set: Set[str],
    ) -> None:
        """Initialize the completion handler.

        Args:
            nodes: All nodes in the graph
            node_status: Current status of each node
            finalize_node_result: Callback to finalize results
            scheduler: Ready queue scheduler
            events: Event emitter
            dependents: Mapping of node_id -> [dependent_node_ids]
            execution_set: Set of node IDs being executed
        """
        self.nodes = nodes
        self.node_status = node_status
        self.finalize_node_result = finalize_node_result
        self.scheduler = scheduler
        self.events = events
        self.dependents = dependents
        self.execution_set = execution_set

    async def handle_completion(
        self,
        result: "NodeExecutionResult",
        inputs: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Handle a successful node completion.

        Args:
            result: The node execution result
            inputs: The inputs that were used
        """
        from ..execution import NodeStatus

        # Finalize the result
        self.finalize_node_result(
            result.node_id,
            inputs or {},
            result,
            cached=result.from_cache,
        )

        # Emit appropriate event
        if result.from_cache:
            await self.events.emit_node_cached(result)
        else:
            await self.events.emit_node_completed(result)

        # Enqueue dependents
        self.scheduler.mark_node_complete(result.node_id)

    async def handle_error(
        self,
        result: "NodeExecutionResult",
        inputs: Optional[Dict[str, Any]] = None,
        propagate: bool = True,
    ) -> None:
        """Handle a node error.

        Args:
            result: The node execution result with error
            inputs: The inputs that were used
            propagate: Whether to propagate failure to dependents
        """
        from ..execution import NodeStatus

        # Finalize the result
        self.finalize_node_result(
            result.node_id,
            inputs or {},
            result,
            cached=False,
        )

        # Emit error event
        await self.events.emit_node_error(result)

        # Propagate to dependents if requested
        if propagate:
            await self.propagate_failure(
                result.node_id,
                f"Dependency '{result.node_id}' failed",
                as_error=True,
            )

    async def handle_skipped(
        self,
        result: "NodeExecutionResult",
        inputs: Optional[Dict[str, Any]] = None,
        propagate: bool = True,
    ) -> None:
        """Handle a skipped node.

        Args:
            result: The node execution result
            inputs: The inputs that were used (if any)
            propagate: Whether to propagate skip to dependents
        """
        from ..execution import NodeStatus

        # Finalize the result
        self.finalize_node_result(
            result.node_id,
            inputs or {},
            result,
            cached=False,
            allow_cache=False,
        )

        # Emit skipped event
        await self.events.emit_node_skipped(result.node_id, result.logs)

        # Propagate to dependents if requested
        if propagate:
            await self.propagate_failure(
                result.node_id,
                f"Dependency '{result.node_id}' was interrupted",
                as_error=False,
            )

    async def propagate_failure(
        self,
        source_node_id: str,
        reason: str,
        as_error: bool = True,
    ) -> None:
        """Propagate failure to all downstream nodes.

        Args:
            source_node_id: The node that failed/was skipped
            reason: The reason message
            as_error: If True, mark as error; if False, mark as skipped
        """
        from ..execution import NodeExecutionResult, NodeStatus

        # Get all nodes to skip
        to_skip = self.scheduler.mark_node_failed(source_node_id)

        status = NodeStatus.ERROR if as_error else NodeStatus.SKIPPED

        for dep in to_skip:
            if self.node_status.get(dep) != NodeStatus.PENDING:
                continue

            # Create result for the skipped node
            result = NodeExecutionResult(
                node_id=dep,
                node_type=self.nodes[dep].type,
                status=status,
                logs=[reason],
                duration_ms=0.0,
                level=0,  # Will be set correctly elsewhere
                from_cache=False,
            )

            # Finalize
            self.finalize_node_result(dep, {}, result, cached=False)

            # Emit event
            await self.events.emit_dependency_error(dep, reason, as_error=as_error)


class LoopCompletionHandler:
    """Handles completion within loop iterations.

    Simplified version of TaskCompletionHandler for use within loops
    where execution is synchronous.
    """

    def __init__(
        self,
        nodes: Dict[str, Any],
        node_levels: Dict[str, int],
        finalize_node_result: Callable,
        fail_fast: bool = True,
    ) -> None:
        """Initialize the loop completion handler.

        Args:
            nodes: All nodes in the graph
            node_levels: Mapping of node_id -> execution level
            finalize_node_result: Callback to finalize results
            fail_fast: Whether to stop on first error
        """
        self.nodes = nodes
        self.node_levels = node_levels
        self.finalize_node_result = finalize_node_result
        self.fail_fast = fail_fast

    def handle_result(
        self,
        result: "NodeExecutionResult",
        inputs: Dict[str, Any],
    ) -> bool:
        """Handle a node result within a loop.

        Args:
            result: The node execution result
            inputs: The inputs that were used

        Returns:
            True if execution should continue, False if should stop
        """
        from ..execution import NodeStatus

        # Finalize the result
        self.finalize_node_result(
            result.node_id,
            inputs,
            result,
            cached=result.from_cache,
        )

        # Check if we should stop
        if result.status == NodeStatus.ERROR and self.fail_fast:
            return False

        return True


__all__ = ["TaskCompletionHandler", "LoopCompletionHandler"]
