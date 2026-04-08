"""
Graph building utilities extracted from GraphExecutor.

This module contains the pure logic for constructing graph data structures
from a graph definition: building nodes, links, topological sorting, and
computing execution levels.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

from ..execution import GraphExecutionError, Link
from ..typesystem import TypeDescriptor

if TYPE_CHECKING:
    from ..nodes import NodeBase, NodeRegistration


def normalize_type(raw_type: Any) -> Optional[TypeDescriptor]:
    """Normalize type descriptors from various sources into a TypeDescriptor.
    
    Handles:
    - TypeDescriptor instances (returned as-is)
    - Dict payloads (parsed via from_dict)
    - Objects with 'kind' attribute (stride_core TypeDescriptor)
    - String type names (wrapped in TypeDescriptor)
    """
    if raw_type is None:
        return None
    if isinstance(raw_type, TypeDescriptor):
        return raw_type
    if isinstance(raw_type, dict):
        return TypeDescriptor.from_dict(raw_type)
    # Handle stride_core TypeDescriptor objects
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


def build_nodes(
    definition: Dict[str, Any],
    get_node: callable,
) -> Dict[str, "NodeBase"]:
    """Build node instances from graph definition.
    
    Args:
        definition: Graph definition containing 'nodes' list
        get_node: Function to get node registration by type name
        
    Returns:
        Dict mapping node_id -> NodeBase instance
        
    Raises:
        GraphExecutionError: If nodes are missing, have no type, or duplicated
    """
    from ..nodes import get_node as _get_node
    
    node_configs = definition.get("nodes", [])
    if not node_configs:
        raise GraphExecutionError("Graph contains no nodes to execute")

    nodes: Dict[str, "NodeBase"] = {}
    
    for node_config in node_configs:
        node_type = node_config.get("type")
        if not node_type:
            raise GraphExecutionError(f"Node {node_config} has no type", code="missing_type")
        node_id = node_config.get("id")
        if not node_id:
            raise GraphExecutionError("Every node must declare a unique 'id'", code="missing_id")
        if node_id in nodes:
            raise GraphExecutionError(f"Duplicate node id '{node_id}' detected", code="duplicate_id")
        try:
            registration = get_node(node_type)
        except KeyError as exc:
            raise GraphExecutionError(str(exc), code="unknown_node") from exc
        node = registration.cls(node_config, spec=registration.spec)
        node.cache_enabled = bool(node_config.get("cache_enabled", getattr(node, "cache_enabled", False)))
        nodes[node.id] = node
        
    return nodes


def build_links(
    definition: Dict[str, Any],
    nodes: Dict[str, "NodeBase"],
) -> Tuple[
    List[Link],
    Dict[str, Dict[str, Link]],  # input_map
    Dict[str, List[Tuple[str, str]]],  # control_inputs
    Dict[str, List[Tuple[str, str, str]]],  # control_outputs
    Dict[str, List[Tuple[str, str, str]]],  # output_map
    Dict[str, List[str]],  # dependents
]:
    """Build link structures from graph definition.
    
    Returns:
        Tuple of (links, input_map, control_inputs, control_outputs, output_map, dependents)
    """
    links: List[Link] = []
    input_map: Dict[str, Dict[str, Link]] = defaultdict(dict)
    control_inputs: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    control_outputs: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
    output_map: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
    dependents: Dict[str, List[str]] = defaultdict(list)
    
    seen_links: Set[Tuple[str, str, str, str, str]] = set()
    
    for raw_link in definition.get("links", []):
        link = Link(**raw_link)
        if link.to_node not in nodes:
            raise GraphExecutionError(f"Link references unknown node {link.to_node}")
        if link.from_node not in nodes:
            raise GraphExecutionError(f"Link references unknown node {link.from_node}")

        key = (link.from_node, link.from_port, link.to_node, link.to_port, link.kind)
        if key in seen_links:
            raise GraphExecutionError(
                f"Duplicate link detected: {link.from_node}.{link.from_port} -> {link.to_node}.{link.to_port}",
                code="duplicate_link",
            )

        from_node = nodes[link.from_node]
        to_node = nodes[link.to_node]
        
        if link.kind == "control":
            if any(
                parent == link.from_node and port == link.from_port
                for parent, port in control_inputs.get(link.to_node, [])
            ):
                raise GraphExecutionError(
                    f"Duplicate control link detected: {link.from_node}.{link.from_port} -> {link.to_node}.{link.to_port}",
                    code="duplicate_link",
                )
            control_inputs[link.to_node].append((link.from_node, link.from_port))
            control_outputs[link.from_node].append((link.to_node, link.from_port, link.to_port))
            output_map[link.from_node].append((link.to_node, link.from_port, link.to_port))
            dependents[link.from_node].append(link.to_node)
        else:
            if link.to_port in input_map.get(link.to_node, {}):
                raise GraphExecutionError(
                    f"Duplicate input link detected: {link.from_node}.{link.from_port} -> {link.to_node}.{link.to_port}",
                    code="duplicate_link",
                )
            if link.from_port not in from_node.output_ports:
                raise GraphExecutionError(
                    f"Link from '{link.from_node}' references missing output port '{link.from_port}'",
                    code="missing_output_port",
                )
            if link.to_port not in to_node.input_ports:
                raise GraphExecutionError(
                    f"Link to '{link.to_node}' references missing input port '{link.to_port}'",
                    code="missing_input_port",
                )

            # Type compatibility
            from_type = normalize_type(from_node.output_port_types.get(link.from_port))
            to_type = normalize_type(to_node.input_port_types.get(link.to_port))
            if isinstance(from_type, TypeDescriptor) and isinstance(to_type, TypeDescriptor):
                if not from_type.is_assignable_to(to_type):
                    raise GraphExecutionError(
                        f"Type mismatch: {from_node.type}.{link.from_port} ({from_type.label()}) -> "
                        f"{to_node.type}.{link.to_port} ({to_type.label()})",
                        code="type_mismatch",
                    )

            input_map[link.to_node][link.to_port] = link
            output_map[link.from_node].append((link.to_node, link.from_port, link.to_port))
            dependents[link.from_node].append(link.to_node)

        links.append(link)
        seen_links.add(key)

    return links, dict(input_map), dict(control_inputs), dict(control_outputs), dict(output_map), dict(dependents)


def validate_output_nodes(
    definition: Dict[str, Any],
    nodes: Dict[str, "NodeBase"],
) -> None:
    """Validate that declared output nodes reference valid ports."""
    for entry in definition.get("output_nodes", []):
        node_id = entry.get("node_id")
        port = entry.get("port")
        if not node_id or not port:
            raise GraphExecutionError("Each output node entry must include 'node_id' and 'port'")
        if node_id not in nodes:
            raise GraphExecutionError(f"Output references unknown node '{node_id}'")
        node = nodes[node_id]
        if port not in node.output_ports:
            raise GraphExecutionError(
                f"Output references unknown port '{port}' on node '{node_id}'",
                code="missing_output_port",
            )


def topological_sort(
    nodes: Dict[str, "NodeBase"],
    links: List[Link],
    input_map: Dict[str, Dict[str, Link]],
    control_inputs: Dict[str, List[Tuple[str, str]]],
) -> List[str]:
    """Kahn's algorithm for topological sorting.
    
    Returns:
        List of node IDs in topological order
        
    Raises:
        GraphExecutionError: If graph contains a cycle
    """
    dependencies: Dict[str, int] = {}
    for node_id in nodes:
        data_deps = len(input_map.get(node_id, {}))
        control_deps = len(control_inputs.get(node_id, []))
        dependencies[node_id] = data_deps + control_deps
    
    queue = deque([node_id for node_id, count in dependencies.items() if count == 0])
    order: List[str] = []

    children: Dict[str, List[str]] = defaultdict(list)
    for link in links:
        children[link.from_node].append(link.to_node)

    while queue:
        current = queue.popleft()
        order.append(current)
        for child in children.get(current, []):
            dependencies[child] -= 1
            if dependencies[child] == 0:
                queue.append(child)

    if len(order) != len(nodes):
        raise GraphExecutionError("Graph contains a cycle or missing inputs")
    return order


def compute_levels(
    topo_order: List[str],
    input_map: Dict[str, Dict[str, Link]],
    control_inputs: Dict[str, List[Tuple[str, str]]],
) -> Tuple[Dict[str, int], List[List[str]]]:
    """Compute topological levels for parallel execution.
    
    Nodes at the same level have no dependencies on each other
    and can be executed in parallel.
    
    Returns:
        Tuple of (node_levels dict, levels list)
    """
    levels: Dict[str, int] = {}
    
    for node_id in topo_order:
        input_links = input_map.get(node_id, {})
        control_parents = [parent for parent, _ in control_inputs.get(node_id, [])]
        if not input_links and not control_parents:
            levels[node_id] = 0
        else:
            max_input_level = 0
            if input_links:
                max_input_level = max(
                    levels.get(link.from_node, 0) for link in input_links.values()
                )
            if control_parents:
                max_input_level = max(max_input_level, max(levels.get(pid, 0) for pid in control_parents))
            levels[node_id] = max_input_level + 1
    
    level_groups: Dict[int, List[str]] = defaultdict(list)
    for node_id, level in levels.items():
        level_groups[level].append(node_id)
    
    max_level = max(levels.values()) if levels else 0
    levels_list = [level_groups.get(i, []) for i in range(max_level + 1)]
    
    return levels, levels_list
