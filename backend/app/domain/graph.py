"""
Graph definition domain model.

Represents the immutable structure of a node graph - what nodes exist,
how they're connected, and their static configuration. This is separate
from execution state (computed values, node status) which changes per-run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass(frozen=True)
class NodeSpec:
    """Specification of a single node in the graph.

    This is immutable configuration that doesn't change during execution.
    """
    id: str
    type: str
    params: Dict[str, Any] = field(default_factory=dict)
    input_values: Dict[str, Any] = field(default_factory=dict)
    input_ports_override: Optional[List[str]] = None
    input_port_types_override: Optional[Dict[str, Any]] = None
    output_ports_override: Optional[List[str]] = None
    output_port_types_override: Optional[Dict[str, Any]] = None
    cache_enabled: bool = False

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NodeSpec):
            return NotImplemented
        return self.id == other.id


@dataclass(frozen=True)
class LinkSpec:
    """Specification of a link between two node ports.

    Links are directed edges in the graph, connecting an output port
    of one node to an input port of another.
    """
    from_node: str
    from_port: str
    to_node: str
    to_port: str
    kind: str = "data"  # "data" or "control"

    def __hash__(self) -> int:
        return hash((self.from_node, self.from_port, self.to_node, self.to_port))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, LinkSpec):
            return NotImplemented
        return (
            self.from_node == other.from_node
            and self.from_port == other.from_port
            and self.to_node == other.to_node
            and self.to_port == other.to_port
        )


@dataclass
class GraphDefinition:
    """Immutable definition of a node graph.

    Contains the complete structural definition of a graph without any
    execution state. This allows the same graph to be executed multiple
    times with different state, and enables safe concurrent access.

    Attributes:
        nodes: Mapping of node_id to NodeSpec
        links: List of all connections between nodes
        input_map: node_id -> {port_name -> (source_node, source_port)}
        output_map: node_id -> {port_name -> [(target_node, target_port), ...]}
        control_inputs: node_id -> [(source_node, source_port), ...]
        control_outputs: node_id -> [(target_node, target_port), ...]
        dependents: node_id -> [dependent_node_ids]
        topo_order: Topologically sorted list of node_ids
        node_levels: node_id -> level (for parallel execution)
        levels: List of node_ids grouped by level
    """
    nodes: Dict[str, NodeSpec] = field(default_factory=dict)
    links: List[LinkSpec] = field(default_factory=list)

    # Derived structures (computed once, immutable after)
    input_map: Dict[str, Dict[str, tuple]] = field(default_factory=dict)
    output_map: Dict[str, Dict[str, List[tuple]]] = field(default_factory=dict)
    control_inputs: Dict[str, List[tuple]] = field(default_factory=dict)
    control_outputs: Dict[str, List[tuple]] = field(default_factory=dict)
    dependents: Dict[str, List[str]] = field(default_factory=dict)
    topo_order: List[str] = field(default_factory=list)
    node_levels: Dict[str, int] = field(default_factory=dict)
    levels: List[List[str]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphDefinition":
        """Create a GraphDefinition from a dictionary (API payload).

        Args:
            data: Dictionary with 'nodes' and 'links' keys

        Returns:
            A new GraphDefinition instance
        """
        nodes_data = data.get("nodes", [])
        links_data = data.get("links", [])

        nodes = {}
        for node_data in nodes_data:
            node_spec = NodeSpec(
                id=node_data["id"],
                type=node_data["type"],
                params=node_data.get("params", {}),
                input_values=node_data.get("input_values", {}),
                input_ports_override=node_data.get("input_ports_override"),
                input_port_types_override=node_data.get("input_port_types_override"),
                output_ports_override=node_data.get("output_ports_override"),
                output_port_types_override=node_data.get("output_port_types_override"),
                cache_enabled=node_data.get("cache_enabled", False),
            )
            nodes[node_spec.id] = node_spec

        links = []
        for link_data in links_data:
            link_spec = LinkSpec(
                from_node=link_data["from_node"],
                from_port=link_data["from_port"],
                to_node=link_data["to_node"],
                to_port=link_data["to_port"],
                kind=link_data.get("kind", "data"),
            )
            links.append(link_spec)

        return cls(nodes=nodes, links=links)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary representation.

        Returns:
            Dictionary with 'nodes' and 'links' keys
        """
        return {
            "nodes": [
                {
                    "id": node.id,
                    "type": node.type,
                    "params": node.params,
                    "input_values": node.input_values,
                    "input_ports_override": node.input_ports_override,
                    "input_port_types_override": node.input_port_types_override,
                    "output_ports_override": node.output_ports_override,
                    "output_port_types_override": node.output_port_types_override,
                    "cache_enabled": node.cache_enabled,
                }
                for node in self.nodes.values()
            ],
            "links": [
                {
                    "from_node": link.from_node,
                    "from_port": link.from_port,
                    "to_node": link.to_node,
                    "to_port": link.to_port,
                    "kind": link.kind,
                }
                for link in self.links
            ],
        }

    def get_node_ids(self) -> Set[str]:
        """Get all node IDs in the graph."""
        return set(self.nodes.keys())

    def get_data_links(self) -> List[LinkSpec]:
        """Get all data (non-control) links."""
        return [link for link in self.links if link.kind == "data"]

    def get_control_links(self) -> List[LinkSpec]:
        """Get all control flow links."""
        return [link for link in self.links if link.kind == "control"]

    def get_upstream_nodes(self, node_id: str) -> Set[str]:
        """Get all nodes that this node depends on (directly or indirectly).

        Args:
            node_id: The node to find dependencies for

        Returns:
            Set of node IDs that must execute before this node
        """
        upstream: Set[str] = set()
        visited: Set[str] = set()
        queue = [node_id]

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            # Add data input sources
            for source_node, _ in self.input_map.get(current, {}).values():
                if source_node not in upstream:
                    upstream.add(source_node)
                    queue.append(source_node)

            # Add control input sources
            for source_node, _ in self.control_inputs.get(current, []):
                if source_node not in upstream:
                    upstream.add(source_node)
                    queue.append(source_node)

        upstream.discard(node_id)  # Don't include self
        return upstream

    def get_downstream_nodes(self, node_id: str) -> Set[str]:
        """Get all nodes that depend on this node (directly or indirectly).

        Args:
            node_id: The node to find dependents for

        Returns:
            Set of node IDs that execute after this node
        """
        downstream: Set[str] = set()
        queue = [node_id]

        while queue:
            current = queue.pop(0)
            for dep in self.dependents.get(current, []):
                if dep not in downstream:
                    downstream.add(dep)
                    queue.append(dep)

        return downstream
