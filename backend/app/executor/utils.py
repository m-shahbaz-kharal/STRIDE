"""
Shared utilities for graph execution.

Provides common functions used across executor modules.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Callable, Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    from ..execution import ExecutionStats, NodeExecutionResult, NodeStatus
    from ..typesystem import TypeDescriptor


def normalize_type(raw_type: Any) -> Optional["TypeDescriptor"]:
    """Normalize type descriptors from various sources into a TypeDescriptor.

    Handles:
    - TypeDescriptor instances (returned as-is)
    - Dict payloads (parsed via from_dict)
    - Objects with 'kind' attribute (liguard_core TypeDescriptor)
    - String type names (wrapped in TypeDescriptor)
    """
    from ..typesystem import TypeDescriptor

    if raw_type is None:
        return None
    if isinstance(raw_type, TypeDescriptor):
        return raw_type
    if isinstance(raw_type, dict):
        return TypeDescriptor.from_dict(raw_type)
    # Handle liguard_core TypeDescriptor objects
    kind = getattr(raw_type, "kind", None)
    if kind:
        # Already a compatible TypeDescriptor-like object
        if hasattr(raw_type, "to_dict"):
            return TypeDescriptor.from_dict(raw_type.to_dict())
        # Fallback for objects with kind attribute
        return TypeDescriptor(
            kind=kind,
            element_type=normalize_type(getattr(raw_type, "element_type", None)),
            fields=({k: normalize_type(v) for k, v in getattr(raw_type, "fields", {}).items()}
                    if getattr(raw_type, "fields", None) else None),
            nullable=bool(getattr(raw_type, "nullable", False)),
            metadata=getattr(raw_type, "metadata", {}) or {},
        )
    if isinstance(raw_type, str):
        return TypeDescriptor(kind=raw_type)
    return None


def collect_dependents(
    node_id: str,
    dependents_map: Dict[str, List[str]],
) -> Set[str]:
    """Collect all transitive dependents of a node.

    Args:
        node_id: The node to collect dependents for
        dependents_map: Mapping of node_id -> list of dependent node_ids

    Returns:
        Set of all transitively dependent node IDs
    """
    collected: Set[str] = set()
    stack = list(dependents_map.get(node_id, []))
    while stack:
        current = stack.pop()
        if current in collected:
            continue
        collected.add(current)
        stack.extend(dependents_map.get(current, []))
    return collected


def expand_dependencies(
    node_ids: List[str],
    nodes: Dict[str, Any],
    input_map: Dict[str, Dict[str, Any]],
    control_inputs: Dict[str, List[tuple]],
) -> Set[str]:
    """Expand a set of target nodes to include all their dependencies.

    Args:
        node_ids: Initial nodes to expand from
        nodes: All nodes in the graph
        input_map: Mapping of node_id -> port -> Link
        control_inputs: Mapping of node_id -> [(parent_id, port)]

    Returns:
        Set of all nodes including dependencies
    """
    queue = deque(node_ids)
    collected: Set[str] = set()
    while queue:
        current = queue.popleft()
        if current in collected or current not in nodes:
            continue
        collected.add(current)
        for link in input_map.get(current, {}).values():
            if link.from_node not in collected:
                queue.append(link.from_node)
        for parent, _ in control_inputs.get(current, []):
            if parent not in collected:
                queue.append(parent)
    return collected


def collect_downstream(
    node_ids: List[str],
    nodes: Dict[str, Any],
    dependents_map: Dict[str, List[str]],
) -> Set[str]:
    """Collect all nodes reachable downstream from the given nodes.

    Args:
        node_ids: Starting nodes
        nodes: All nodes in the graph
        dependents_map: Mapping of node_id -> list of dependent node_ids

    Returns:
        Set of all downstream nodes including starting nodes
    """
    queue = deque(node_ids)
    collected: Set[str] = set()
    while queue:
        current = queue.popleft()
        if current in collected or current not in nodes:
            continue
        collected.add(current)
        for child in dependents_map.get(current, []):
            if child not in collected:
                queue.append(child)
    return collected


def collect_outputs(
    definition: Dict[str, Any],
    computed_values: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Collect final outputs from executed nodes.

    Args:
        definition: Graph definition containing output_nodes config
        computed_values: Mapping of node_id -> port -> value

    Returns:
        Dict of alias -> value for all outputs
    """
    results: Dict[str, Any] = {}
    for entry in definition.get("output_nodes", []):
        node_id = entry["node_id"]
        port = entry["port"]
        alias = entry.get("alias", f"{node_id}.{port}")
        node_outputs = computed_values.get(node_id)
        if not node_outputs or port not in node_outputs:
            continue
        results[alias] = node_outputs[port]
    if not results:
        for node_id, output_map in computed_values.items():
            for port, value in output_map.items():
                results[f"{node_id}.{port}"] = value
    return results


def calculate_stats(
    execution_trace: List["NodeExecutionResult"],
    execution_order: List[str],
    total_time_ms: float,
    max_parallelism: int = 1,
) -> "ExecutionStats":
    """Calculate execution statistics.

    Args:
        execution_trace: List of node execution results
        execution_order: Ordered list of node IDs to execute
        total_time_ms: Total wall-clock execution time
        max_parallelism: Maximum number of nodes executed in parallel

    Returns:
        ExecutionStats with computed metrics
    """
    from ..execution import ExecutionStats, NodeStatus

    node_time_ms = sum(r.duration_ms for r in execution_trace)
    completed = [r for r in execution_trace if r.status == NodeStatus.COMPLETED]
    cached = len([r for r in completed if r.from_cache])
    executed = len(completed) - cached  # Actually executed (not from cache)
    errors = len([r for r in execution_trace if r.status == NodeStatus.ERROR])
    skipped = len([r for r in execution_trace if r.status == NodeStatus.SKIPPED])
    total_nodes = len(execution_trace) if execution_trace else len(execution_order)

    parallel_efficiency = node_time_ms / total_time_ms if total_time_ms > 0 else 1.0
    levels_executed = len(set(r.level for r in execution_trace))

    return ExecutionStats(
        total_nodes=total_nodes,
        executed_nodes=executed,
        skipped_nodes=skipped,
        cached_nodes=cached,
        error_nodes=errors,
        total_time_ms=total_time_ms,
        node_time_ms=node_time_ms,
        parallel_efficiency=parallel_efficiency,
        max_parallelism=max_parallelism,
        levels_executed=levels_executed,
    )


__all__ = [
    "normalize_type",
    "collect_dependents",
    "expand_dependencies",
    "collect_downstream",
    "collect_outputs",
    "calculate_stats",
]
