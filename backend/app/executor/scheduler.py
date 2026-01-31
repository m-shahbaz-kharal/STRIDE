"""
Ready-queue scheduler for graph execution.

Manages node readiness based on dependency completion and schedules
nodes for execution when all their inputs are available.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Deque, Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from ..execution import NodeStatus


class ReadyQueueScheduler:
    """Manages node readiness based on dependency completion.

    This scheduler tracks which nodes have all their dependencies satisfied
    and are ready to execute. It handles:
    - Initial computation of ready nodes (those with no dependencies)
    - Marking nodes complete and enqueueing their dependents
    - Respecting execution limits (max_steps, breakpoints)

    The scheduler is stateless with respect to node execution - it only
    tracks readiness, not actual execution state.
    """

    def __init__(
        self,
        execution_set: Set[str],
        input_map: Dict[str, Dict[str, Any]],
        control_inputs: Dict[str, List[tuple]],
        dependents: Dict[str, List[str]],
        node_status: Dict[str, "NodeStatus"],
        max_workers: int = 4,
    ) -> None:
        """Initialize the scheduler.

        Args:
            execution_set: Set of node IDs that should be executed
            input_map: Mapping of node_id -> port -> Link
            control_inputs: Mapping of node_id -> [(parent_id, port)]
            dependents: Mapping of node_id -> [dependent_node_ids]
            node_status: Current status of each node
            max_workers: Maximum concurrent executions
        """
        self.execution_set = execution_set
        self.input_map = input_map
        self.control_inputs = control_inputs
        self.dependents = dependents
        self.node_status = node_status
        self.max_workers = max_workers

        # Remaining input count for each node
        self._remaining_inputs: Dict[str, int] = {}
        # Ready queue (nodes with all deps satisfied)
        self._ready: Deque[str] = deque()
        # Track if scheduling should stop
        self._stop_scheduling = False

    def compute_initial_ready_queue(self) -> Deque[str]:
        """Compute which nodes are initially ready (no dependencies).

        This should be called once at the start of execution to initialize
        the ready queue with nodes that have no input dependencies.

        Returns:
            Deque of node IDs that are ready to execute
        """
        self._remaining_inputs = {
            node_id: len(self.input_map.get(node_id, {})) + len(self.control_inputs.get(node_id, []))
            for node_id in self.execution_set
        }

        self._ready = deque([
            node_id for node_id, count in self._remaining_inputs.items()
            if count == 0
        ])

        return self._ready

    def mark_node_complete(self, node_id: str) -> List[str]:
        """Mark a node as complete and return newly ready dependents.

        This decrements the remaining input count for all dependents
        and returns any that become ready (count reaches 0).

        Args:
            node_id: The completed node ID

        Returns:
            List of node IDs that are now ready to execute
        """
        newly_ready: List[str] = []

        for dep in self.dependents.get(node_id, []):
            if dep not in self.execution_set:
                continue
            if self._remaining_inputs.get(dep, 0) < 0:
                # Already marked as failed/skipped
                continue

            self._remaining_inputs[dep] -= 1
            if self._remaining_inputs[dep] == 0:
                self._ready.append(dep)
                newly_ready.append(dep)

        return newly_ready

    def mark_node_failed(self, node_id: str) -> List[str]:
        """Mark a node as failed and return all downstream nodes to skip.

        This marks all transitive dependents as failed (count = -1)
        to prevent them from executing.

        Args:
            node_id: The failed node ID

        Returns:
            List of node IDs that should be skipped
        """
        to_skip: List[str] = []
        stack = list(self.dependents.get(node_id, []))
        visited: Set[str] = set()

        while stack:
            dep = stack.pop()
            if dep in visited:
                continue
            visited.add(dep)

            if dep not in self.execution_set:
                stack.extend(self.dependents.get(dep, []))
                continue

            if self._remaining_inputs.get(dep, 0) < 0:
                # Already failed
                stack.extend(self.dependents.get(dep, []))
                continue

            # Remove from ready queue if present
            if dep in self._ready:
                self._ready = deque([n for n in self._ready if n != dep])

            # Mark as failed
            self._remaining_inputs[dep] = -1
            to_skip.append(dep)
            stack.extend(self.dependents.get(dep, []))

        return to_skip

    def get_next_ready(self) -> Optional[str]:
        """Get the next node that is ready to execute.

        Returns:
            Node ID if one is ready, None if queue is empty
        """
        from ..execution import NodeStatus

        while self._ready:
            node_id = self._ready.popleft()
            # Skip nodes that are no longer pending
            if self.node_status.get(node_id) != NodeStatus.PENDING:
                continue
            return node_id
        return None

    def get_next_ready_batch(self, max_count: int) -> List[str]:
        """Get up to max_count nodes that are ready to execute.

        This is useful for filling a thread pool with work.

        Args:
            max_count: Maximum nodes to return

        Returns:
            List of ready node IDs (may be fewer than max_count)
        """
        batch: List[str] = []
        while len(batch) < max_count:
            node_id = self.get_next_ready()
            if node_id is None:
                break
            batch.append(node_id)
        return batch

    def has_pending_work(self) -> bool:
        """Check if there is any pending work (ready nodes or in-progress).

        Returns:
            True if there are ready nodes
        """
        return len(self._ready) > 0

    def clear_ready_queue(self) -> None:
        """Clear the ready queue (e.g., when stopping execution)."""
        self._ready.clear()

    def stop_scheduling(self) -> None:
        """Signal that no more nodes should be scheduled."""
        self._stop_scheduling = True
        self._ready.clear()

    def is_stopped(self) -> bool:
        """Check if scheduling has been stopped."""
        return self._stop_scheduling

    def enqueue_if_ready(self, node_id: str) -> bool:
        """Add a node to the ready queue if it's ready.

        This is useful for re-enqueueing nodes after loop iterations.

        Args:
            node_id: The node ID to potentially enqueue

        Returns:
            True if the node was enqueued
        """
        if node_id not in self.execution_set:
            return False
        if self._remaining_inputs.get(node_id, 0) == 0:
            self._ready.append(node_id)
            return True
        return False


class LoopIterationScheduler:
    """Manages scheduling within a loop body.

    Loop bodies execute synchronously within their iteration, so this
    is simpler than the main scheduler. It tracks which body nodes
    have completed within the current iteration.
    """

    def __init__(
        self,
        body_nodes: Set[str],
        body_order: List[str],
    ) -> None:
        """Initialize the loop iteration scheduler.

        Args:
            body_nodes: Set of node IDs in the loop body
            body_order: Topologically sorted list of body node IDs
        """
        self.body_nodes = body_nodes
        self.body_order = body_order
        self._index = 0

    def reset(self) -> None:
        """Reset for a new iteration."""
        self._index = 0

    def get_next(self) -> Optional[str]:
        """Get the next node to execute in the loop body.

        Returns:
            Node ID or None if iteration is complete
        """
        if self._index >= len(self.body_order):
            return None
        node_id = self.body_order[self._index]
        self._index += 1
        return node_id

    def has_more(self) -> bool:
        """Check if there are more nodes in this iteration."""
        return self._index < len(self.body_order)


__all__ = ["ReadyQueueScheduler", "LoopIterationScheduler"]
