"""
Graph building and validation for graph execution.

Handles node instantiation, link creation, validation, and topological sorting.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Dict, List, Set, Tuple, TYPE_CHECKING

from .utils import normalize_type

if TYPE_CHECKING:
    from ..execution import Link
    from ..nodes import NodeBase


class GraphBuilder:
    """Builds and validates a graph from a definition."""

    def __init__(
        self,
        definition: Dict[str, Any],
    ) -> None:
        """Initialize the graph builder.

        Args:
            definition: Graph definition containing nodes and links
        """
        self.definition = definition
        self.nodes: Dict[str, "NodeBase"] = {}
        self.links: List["Link"] = []
        self.input_map: Dict[str, Dict[str, "Link"]] = defaultdict(dict)
        self.control_inputs: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        self.control_outputs: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
        self.output_map: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
        self._dependents: Dict[str, List[str]] = defaultdict(list)

    def build(self) -> None:
        """Build the complete graph structure."""
        self.build_nodes()
        self.build_links()
        self.validate_output_nodes()

    def build_nodes(self) -> Dict[str, "NodeBase"]:
        """Instantiate nodes from configuration.

        Returns:
            Dict mapping node_id to NodeBase instances

        Raises:
            GraphExecutionError: If nodes are missing, have no type, or duplicate IDs
        """
        from ..execution import GraphExecutionError
        from ..nodes import get_node

        node_configs = self.definition.get("nodes", [])
        if not node_configs:
            raise GraphExecutionError("Graph contains no nodes to execute")

        for node_config in node_configs:
            node_type = node_config.get("type")
            if not node_type:
                raise GraphExecutionError(f"Node {node_config} has no type", code="missing_type")
            node_id = node_config.get("id")
            if not node_id:
                raise GraphExecutionError("Every node must declare a unique 'id'", code="missing_id")
            if node_id in self.nodes:
                raise GraphExecutionError(f"Duplicate node id '{node_id}' detected", code="duplicate_id")
            try:
                registration = get_node(node_type)
            except KeyError as exc:
                raise GraphExecutionError(str(exc), code="unknown_node") from exc
            node = registration.cls(node_config, spec=registration.spec)
            node.cache_enabled = bool(node_config.get("cache_enabled", getattr(node, "cache_enabled", False)))
            self.nodes[node.id] = node

        return self.nodes

    def build_links(self) -> List["Link"]:
        """Create links with type validation.

        Returns:
            List of Link objects

        Raises:
            GraphExecutionError: For invalid or duplicate links, missing ports, or type mismatches
        """
        from ..execution import GraphExecutionError, Link
        from ..typesystem import TypeDescriptor

        seen_links: Set[Tuple[str, str, str, str, str]] = set()
        for raw_link in self.definition.get("links", []):
            link = Link(**raw_link)
            if link.to_node not in self.nodes:
                raise GraphExecutionError(f"Link references unknown node {link.to_node}")
            if link.from_node not in self.nodes:
                raise GraphExecutionError(f"Link references unknown node {link.from_node}")

            key = (link.from_node, link.from_port, link.to_node, link.to_port, link.kind)
            if key in seen_links:
                raise GraphExecutionError(
                    f"Duplicate link detected: {link.from_node}.{link.from_port} -> {link.to_node}.{link.to_port}",
                    code="duplicate_link",
                )

            from_node = self.nodes[link.from_node]
            to_node = self.nodes[link.to_node]
            if link.kind == "control":
                if any(
                    parent == link.from_node and port == link.from_port
                    for parent, port in self.control_inputs.get(link.to_node, [])
                ):
                    raise GraphExecutionError(
                        f"Duplicate control link detected: {link.from_node}.{link.from_port} -> {link.to_node}.{link.to_port}",
                        code="duplicate_link",
                    )
                # Control edge only enforces ordering; no port binding required.
                self.control_inputs[link.to_node].append((link.from_node, link.from_port))
                self.control_outputs[link.from_node].append((link.to_node, link.from_port, link.to_port))
                self.output_map[link.from_node].append((link.to_node, link.from_port, link.to_port))
                self._dependents[link.from_node].append(link.to_node)
            else:
                if link.to_port in self.input_map.get(link.to_node, {}):
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

                self.input_map[link.to_node][link.to_port] = link
                self.output_map[link.from_node].append((link.to_node, link.from_port, link.to_port))
                self._dependents[link.from_node].append(link.to_node)

            self.links.append(link)
            seen_links.add(key)

        return self.links

    def validate_output_nodes(self) -> None:
        """Validate that declared output nodes reference valid ports.

        Raises:
            GraphExecutionError: If output references unknown nodes or ports
        """
        from ..execution import GraphExecutionError

        for entry in self.definition.get("output_nodes", []):
            node_id = entry.get("node_id")
            port = entry.get("port")
            if not node_id or not port:
                raise GraphExecutionError("Each output node entry must include 'node_id' and 'port'")
            if node_id not in self.nodes:
                raise GraphExecutionError(f"Output references unknown node '{node_id}'")
            node = self.nodes[node_id]
            if port not in node.output_ports:
                raise GraphExecutionError(
                    f"Output references unknown port '{port}' on node '{node_id}'",
                    code="missing_output_port",
                )

    def topological_sort(self) -> List[str]:
        """Kahn's algorithm for topological sorting.

        Returns:
            List of node_ids in topological order

        Raises:
            GraphExecutionError: If the graph contains cycles
        """
        from ..execution import GraphExecutionError

        dependencies: Dict[str, int] = {}
        for node_id in self.nodes:
            data_deps = len(self.input_map.get(node_id, {}))
            control_deps = len(self.control_inputs.get(node_id, []))
            dependencies[node_id] = data_deps + control_deps
        queue = deque([node_id for node_id, count in dependencies.items() if count == 0])
        order: List[str] = []

        children: Dict[str, List[str]] = defaultdict(list)
        for link in self.links:
            children[link.from_node].append(link.to_node)

        while queue:
            current = queue.popleft()
            order.append(current)
            for child in children.get(current, []):
                dependencies[child] -= 1
                if dependencies[child] == 0:
                    queue.append(child)

        if len(order) != len(self.nodes):
            raise GraphExecutionError("Graph contains a cycle or missing inputs")
        return order

    def compute_levels(self, topo_order: List[str]) -> Tuple[Dict[str, int], List[List[str]]]:
        """Compute topological levels for parallel execution.

        Nodes at the same level have no dependencies on each other
        and can be executed in parallel.

        Args:
            topo_order: Topological order of node IDs

        Returns:
            Tuple of (node_levels dict, list of levels where each level is a list of node_ids)
        """
        levels: Dict[str, int] = {}

        for node_id in topo_order:
            input_links = self.input_map.get(node_id, {})
            control_parents = [parent for parent, _ in self.control_inputs.get(node_id, [])]
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
        level_list = [level_groups.get(i, []) for i in range(max_level + 1)]

        return levels, level_list

    @property
    def dependents(self) -> Dict[str, List[str]]:
        """Get the dependents map."""
        return self._dependents


__all__ = ["GraphBuilder"]
