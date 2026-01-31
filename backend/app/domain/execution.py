"""
Execution state domain model.

Represents the mutable state that changes during graph execution.
This is separate from GraphDefinition which is immutable.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from ..execution import NodeStatus, NodeExecutionResult


@dataclass
class ExecutionState:
    """Mutable state for a single graph execution run.

    This class holds all per-execution state that changes as nodes
    execute. It's created fresh for each execution run, while the
    GraphDefinition remains constant.

    Attributes:
        execution_id: Unique identifier for this execution run
        computed_values: node_id -> {port_name -> value} for completed nodes
        node_status: node_id -> current NodeStatus
        execution_trace: List of NodeExecutionResult in execution order
        variables: Shared variables across nodes (e.g., from variable nodes)
        shared_metadata: Metadata shared across the execution context
        resources: List of (node_id, resource) tuples to cleanup
        skipped_branches: Set of node_ids in branches that should be skipped
        force_no_cache: Set of node_ids that should not use cache
    """
    execution_id: str
    computed_values: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    node_status: Dict[str, "NodeStatus"] = field(default_factory=dict)
    execution_trace: List["NodeExecutionResult"] = field(default_factory=list)
    variables: Dict[str, Any] = field(default_factory=dict)
    shared_metadata: Dict[str, Any] = field(default_factory=dict)
    resources: List[tuple] = field(default_factory=list)
    skipped_branches: Set[str] = field(default_factory=set)
    force_no_cache: Set[str] = field(default_factory=set)

    # Thread safety
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def reset(self) -> None:
        """Reset all execution state for a fresh run."""
        with self._lock:
            self.computed_values.clear()
            self.node_status.clear()
            self.execution_trace.clear()
            self.variables.clear()
            self.shared_metadata.clear()
            self.resources.clear()
            self.skipped_branches.clear()
            # Note: force_no_cache is set before execution, don't clear here

    def get_computed_value(self, node_id: str, port: str) -> Optional[Any]:
        """Get a computed output value from a node.

        Args:
            node_id: The node that produced the value
            port: The output port name

        Returns:
            The computed value, or None if not available
        """
        with self._lock:
            node_outputs = self.computed_values.get(node_id)
            if node_outputs is None:
                return None
            return node_outputs.get(port)

    def set_computed_values(self, node_id: str, outputs: Dict[str, Any]) -> None:
        """Store computed output values for a node.

        Args:
            node_id: The node that produced the values
            outputs: Dictionary of port_name -> value
        """
        with self._lock:
            self.computed_values[node_id] = outputs

    def get_node_status(self, node_id: str) -> Optional["NodeStatus"]:
        """Get the current status of a node.

        Args:
            node_id: The node to check

        Returns:
            The node's status, or None if not set
        """
        with self._lock:
            return self.node_status.get(node_id)

    def set_node_status(self, node_id: str, status: "NodeStatus") -> None:
        """Set the status of a node.

        Args:
            node_id: The node to update
            status: The new status
        """
        with self._lock:
            self.node_status[node_id] = status

    def add_trace_entry(self, result: "NodeExecutionResult") -> None:
        """Add an execution result to the trace.

        Args:
            result: The execution result to record
        """
        with self._lock:
            self.execution_trace.append(result)

    def get_variable(self, name: str, default: Any = None) -> Any:
        """Get a shared variable value.

        Args:
            name: The variable name
            default: Value to return if variable not found

        Returns:
            The variable value
        """
        with self._lock:
            return self.variables.get(name, default)

    def set_variable(self, name: str, value: Any) -> None:
        """Set a shared variable value.

        Args:
            name: The variable name
            value: The value to store
        """
        with self._lock:
            self.variables[name] = value

    def register_resource(self, node_id: str, resource: Any) -> None:
        """Register a resource for cleanup.

        Args:
            node_id: The node that owns the resource
            resource: The resource to cleanup (must have close() method)
        """
        with self._lock:
            self.resources.append((node_id, resource))

    def cleanup_resources(self, target_node_id: Optional[str] = None) -> None:
        """Close and cleanup registered resources.

        Args:
            target_node_id: If provided, only cleanup resources for this node.
                           If None, cleanup all resources.
        """
        to_close: List[tuple] = []
        remaining: List[tuple] = []

        with self._lock:
            for node_id, resource in self.resources:
                if target_node_id is None or node_id == target_node_id:
                    to_close.append((node_id, resource))
                else:
                    remaining.append((node_id, resource))
            self.resources = remaining

        for _, resource in to_close:
            if hasattr(resource, "close") and callable(resource.close):
                try:
                    resource.close()
                except Exception:
                    pass  # Best effort cleanup

    def is_node_skipped(self, node_id: str) -> bool:
        """Check if a node should be skipped (e.g., false branch of if/else).

        Args:
            node_id: The node to check

        Returns:
            True if the node should be skipped
        """
        with self._lock:
            return node_id in self.skipped_branches

    def skip_branch(self, node_ids: Set[str]) -> None:
        """Mark nodes as skipped (e.g., branch not taken).

        Args:
            node_ids: Set of node IDs to skip
        """
        with self._lock:
            self.skipped_branches.update(node_ids)

    def unskip_branch(self, node_ids: Set[str]) -> None:
        """Remove nodes from the skipped set.

        Args:
            node_ids: Set of node IDs to unskip
        """
        with self._lock:
            self.skipped_branches -= node_ids

    def should_skip_cache(self, node_id: str) -> bool:
        """Check if a node should bypass the cache.

        Args:
            node_id: The node to check

        Returns:
            True if the node should not use cached results
        """
        with self._lock:
            return node_id in self.force_no_cache

    def get_outputs(self) -> Dict[str, Any]:
        """Get all computed output values.

        Returns:
            Dictionary mapping node_id to output values dict
        """
        with self._lock:
            return dict(self.computed_values)

    def get_trace(self) -> List["NodeExecutionResult"]:
        """Get a copy of the execution trace.

        Returns:
            List of execution results in order
        """
        with self._lock:
            return list(self.execution_trace)

    def get_completed_count(self) -> int:
        """Get the count of completed nodes.

        Returns:
            Number of nodes that have completed (any terminal status)
        """
        from ..execution import NodeStatus
        with self._lock:
            return sum(
                1 for status in self.node_status.values()
                if status in (NodeStatus.COMPLETED, NodeStatus.SKIPPED, NodeStatus.ERROR)
            )
