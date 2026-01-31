"""
Execution event emitter for graph execution.

Creates and emits typed execution events for real-time updates.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..execution import ExecutionEvent, NodeExecutionResult, NodeStatus


class ExecutionEventEmitter:
    """Creates and emits typed execution events.

    This class encapsulates all event creation and emission logic,
    providing a clean interface for the executor to report progress.
    """

    def __init__(
        self,
        event_queue: asyncio.Queue,
        execution_id: str,
        nodes: Dict[str, Any],
        node_levels: Dict[str, int],
    ) -> None:
        """Initialize the event emitter.

        Args:
            event_queue: Queue to emit events to
            execution_id: Unique identifier for this execution
            nodes: All nodes in the graph
            node_levels: Mapping of node_id -> execution level
        """
        self.event_queue = event_queue
        self.execution_id = execution_id
        self.nodes = nodes
        self.node_levels = node_levels

        # Progress tracking
        self._total_nodes = 0
        self._completed_nodes = 0

    def set_total_nodes(self, total: int) -> None:
        """Set the total number of nodes for progress calculation."""
        self._total_nodes = total

    def increment_completed(self) -> int:
        """Increment completed count and return new value."""
        self._completed_nodes += 1
        return self._completed_nodes

    def get_progress(self) -> float:
        """Get current progress as a fraction."""
        if self._total_nodes == 0:
            return 0.0
        return self._completed_nodes / self._total_nodes

    async def emit_start(
        self,
        execution_plan: List[Dict[str, Any]],
        levels: List[List[str]],
        branches: Optional[Dict[str, List[str]]] = None,
        merge_points: Optional[List[str]] = None,
    ) -> None:
        """Emit the execution start event.

        Args:
            execution_plan: List of node info dicts
            levels: Nodes grouped by execution level
            branches: Optional branch info for hybrid execution
            merge_points: Optional list of merge point node IDs
        """
        from ..execution import ExecutionEvent

        await self.event_queue.put(ExecutionEvent(
            event_type="start",
            execution_id=self.execution_id,
            timestamp=time.time(),
            total_nodes=self._total_nodes,
            execution_plan=execution_plan,
            levels=levels,
            branches=branches,
            merge_points=merge_points,
        ))

    async def emit_node_queued(self, node_id: str) -> None:
        """Emit event when a node enters the execution queue.

        Args:
            node_id: The queued node ID
        """
        from ..execution import ExecutionEvent, NodeStatus

        node = self.nodes[node_id]
        await self.event_queue.put(ExecutionEvent(
            event_type="node_queued",
            execution_id=self.execution_id,
            timestamp=time.time(),
            node_id=node_id,
            node_type=node.type,
            status=NodeStatus.QUEUED,
            level=self.node_levels.get(node_id, 0),
            progress=self.get_progress(),
            total_nodes=self._total_nodes,
            completed_nodes=self._completed_nodes,
        ))

    async def emit_node_started(self, node_id: str) -> None:
        """Emit event when a node begins execution.

        Args:
            node_id: The started node ID
        """
        from ..execution import ExecutionEvent, NodeStatus

        node = self.nodes[node_id]
        await self.event_queue.put(ExecutionEvent(
            event_type="node_started",
            execution_id=self.execution_id,
            timestamp=time.time(),
            node_id=node_id,
            node_type=node.type,
            status=NodeStatus.RUNNING,
            level=self.node_levels.get(node_id, 0),
            progress=self.get_progress(),
            total_nodes=self._total_nodes,
            completed_nodes=self._completed_nodes,
        ))

    async def emit_node_completed(self, result: "NodeExecutionResult") -> None:
        """Emit event when a node completes successfully.

        Args:
            result: The node execution result
        """
        from ..execution import ExecutionEvent, NodeStatus

        self.increment_completed()
        await self.event_queue.put(ExecutionEvent(
            event_type="node_completed",
            execution_id=self.execution_id,
            timestamp=time.time(),
            node_id=result.node_id,
            node_type=result.node_type,
            status=NodeStatus.COMPLETED,
            outputs=result.outputs,
            logs=result.logs,
            duration_ms=result.duration_ms,
            level=result.level,
            progress=self.get_progress(),
            total_nodes=self._total_nodes,
            completed_nodes=self._completed_nodes,
            from_cache=result.from_cache,
        ))

    async def emit_node_cached(self, result: "NodeExecutionResult") -> None:
        """Emit event when a node result is retrieved from cache.

        Args:
            result: The cached node execution result
        """
        from ..execution import ExecutionEvent, NodeStatus

        self.increment_completed()
        await self.event_queue.put(ExecutionEvent(
            event_type="node_cached",
            execution_id=self.execution_id,
            timestamp=time.time(),
            node_id=result.node_id,
            node_type=result.node_type,
            status=NodeStatus.COMPLETED,
            outputs=result.outputs,
            logs=result.logs,
            duration_ms=result.duration_ms,
            level=result.level,
            progress=self.get_progress(),
            total_nodes=self._total_nodes,
            completed_nodes=self._completed_nodes,
            from_cache=True,
        ))

    async def emit_node_skipped(
        self,
        node_id: str,
        logs: Optional[List[str]] = None,
    ) -> None:
        """Emit event when a node is skipped.

        Args:
            node_id: The skipped node ID
            logs: Optional log messages
        """
        from ..execution import ExecutionEvent, NodeStatus

        node = self.nodes[node_id]
        self.increment_completed()
        await self.event_queue.put(ExecutionEvent(
            event_type="node_skipped",
            execution_id=self.execution_id,
            timestamp=time.time(),
            node_id=node_id,
            node_type=node.type,
            status=NodeStatus.SKIPPED,
            logs=logs,
            duration_ms=0.0,
            level=self.node_levels.get(node_id, 0),
            progress=self.get_progress(),
            total_nodes=self._total_nodes,
            completed_nodes=self._completed_nodes,
            from_cache=False,
        ))

    async def emit_node_error(
        self,
        result: "NodeExecutionResult",
        error_code: Optional[str] = None,
    ) -> None:
        """Emit event when a node fails with an error.

        Args:
            result: The node execution result with error info
            error_code: Optional error code override
        """
        from ..execution import ExecutionEvent, NodeStatus

        self.increment_completed()
        await self.event_queue.put(ExecutionEvent(
            event_type="node_error",
            execution_id=self.execution_id,
            timestamp=time.time(),
            node_id=result.node_id,
            node_type=result.node_type,
            status=NodeStatus.ERROR,
            error=result.error,
            error_code=error_code or result.error_code,
            error_details=result.error_details,
            duration_ms=result.duration_ms,
            level=result.level,
            progress=self.get_progress(),
            total_nodes=self._total_nodes,
            completed_nodes=self._completed_nodes,
            from_cache=result.from_cache,
        ))

    async def emit_dependency_error(
        self,
        node_id: str,
        reason: str,
        as_error: bool = True,
    ) -> None:
        """Emit event for a node that failed due to dependency failure.

        Args:
            node_id: The affected node ID
            reason: The reason for the failure
            as_error: If True, emit as error; if False, emit as skipped
        """
        from ..execution import ExecutionEvent, NodeStatus

        node = self.nodes[node_id]
        status = NodeStatus.ERROR if as_error else NodeStatus.SKIPPED
        event_type = "node_error" if as_error else "node_skipped"

        self.increment_completed()
        await self.event_queue.put(ExecutionEvent(
            event_type=event_type,
            execution_id=self.execution_id,
            timestamp=time.time(),
            node_id=node_id,
            node_type=node.type,
            status=status,
            error=reason if as_error else None,
            error_code="dependency_failed" if as_error else "dependency_skipped",
            logs=[reason],
            duration_ms=0.0,
            level=self.node_levels.get(node_id, 0),
            progress=self.get_progress(),
            total_nodes=self._total_nodes,
            completed_nodes=self._completed_nodes,
            from_cache=False,
        ))

    async def emit_execution_error(self, error: str) -> None:
        """Emit event for a general execution error.

        Args:
            error: The error message
        """
        from ..execution import ExecutionEvent

        await self.event_queue.put(ExecutionEvent(
            event_type="error",
            execution_id=self.execution_id,
            timestamp=time.time(),
            error=error,
            error_code="execution_error",
        ))

    async def emit_complete(self) -> None:
        """Emit the execution complete event."""
        from ..execution import ExecutionEvent

        await self.event_queue.put(ExecutionEvent(
            event_type="complete",
            execution_id=self.execution_id,
            timestamp=time.time(),
            progress=1.0,
            total_nodes=self._total_nodes,
            completed_nodes=self._completed_nodes,
        ))

    async def emit_sentinel(self) -> None:
        """Emit the sentinel value to signal end of stream."""
        await self.event_queue.put(None)


__all__ = ["ExecutionEventEmitter"]
