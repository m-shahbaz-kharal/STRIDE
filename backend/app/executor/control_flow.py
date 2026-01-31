"""
Control flow detection and management for graph execution.

Handles loops, if/else branches, and start nodes for hybrid execution.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Dict, List, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from ..nodes import NodeBase


class LoopHandler:
    """Handles loop node detection and body collection."""

    LOOP_TYPES = {"core.control.for", "core.control.repeat", "core.control.while"}

    def __init__(
        self,
        nodes: Dict[str, "NodeBase"],
        control_outputs: Dict[str, List[Tuple[str, str, str]]],
        topo_order: List[str],
    ) -> None:
        """Initialize the loop handler.

        Args:
            nodes: All nodes in the graph
            control_outputs: Mapping of node_id -> [(target, from_port, to_port)]
            topo_order: Topological order of node IDs
        """
        self.nodes = nodes
        self.control_outputs = control_outputs
        self.topo_order = topo_order

        self.loop_nodes: Set[str] = set()
        self.loop_body_nodes: Dict[str, Set[str]] = {}
        self.nodes_in_loop_body: Set[str] = set()
        self.loop_parent: Dict[str, str] = {}

    def is_loop_node(self, node_id: str) -> bool:
        """Check if a node is a loop control node."""
        node = self.nodes[node_id]
        spec = getattr(node, "spec", None)
        tags = getattr(spec, "tags", None) or []
        if "loop" in tags:
            return True
        return node.type in self.LOOP_TYPES

    def build_loop_sets(self) -> None:
        """Build tracking sets for all loops in the graph."""
        self.loop_nodes = {node_id for node_id in self.nodes if self.is_loop_node(node_id)}
        self.loop_body_nodes = {}
        self.nodes_in_loop_body = set()
        self.loop_parent = {}

        for loop_id in self.loop_nodes:
            body_nodes = self.collect_loop_body_nodes(loop_id)
            self.loop_body_nodes[loop_id] = body_nodes
            self.nodes_in_loop_body.update(body_nodes)

        for node_id in self.topo_order:
            if node_id not in self.loop_nodes:
                continue
            for body_id in self.loop_body_nodes.get(node_id, set()):
                self.loop_parent.setdefault(body_id, node_id)

    def collect_loop_body_nodes(self, loop_id: str) -> Set[str]:
        """Collect all nodes that are part of a loop's body.

        Args:
            loop_id: The loop node ID

        Returns:
            Set of node IDs in the loop body
        """
        body_nodes: Set[str] = set()
        queue = deque()

        for to_node, from_port, _ in self.control_outputs.get(loop_id, []):
            if from_port == "loop_body":
                queue.append(to_node)

        while queue:
            node_id = queue.popleft()
            if node_id in body_nodes:
                continue
            body_nodes.add(node_id)
            child_outputs = self.control_outputs.get(node_id, [])
            if self.is_loop_node(node_id) and node_id != loop_id:
                for child, from_port, _ in child_outputs:
                    if from_port == "completed" and child not in body_nodes:
                        queue.append(child)
                continue
            for child, _, _ in child_outputs:
                if child not in body_nodes:
                    queue.append(child)

        return body_nodes


class IfElseHandler:
    """Handles if/else node detection and branch collection."""

    IFELSE_TYPES = {"core.control.ifelse"}

    def __init__(
        self,
        nodes: Dict[str, "NodeBase"],
        control_outputs: Dict[str, List[Tuple[str, str, str]]],
        loop_handler: LoopHandler,
    ) -> None:
        """Initialize the if/else handler.

        Args:
            nodes: All nodes in the graph
            control_outputs: Mapping of node_id -> [(target, from_port, to_port)]
            loop_handler: Loop handler for nested loop detection
        """
        self.nodes = nodes
        self.control_outputs = control_outputs
        self.loop_handler = loop_handler

        self.ifelse_nodes: Set[str] = set()
        self.ifelse_true_branch: Dict[str, Set[str]] = {}
        self.ifelse_false_branch: Dict[str, Set[str]] = {}
        self.nodes_in_ifelse_branch: Set[str] = set()

    def is_ifelse_node(self, node_id: str) -> bool:
        """Check if a node is an if/else control node."""
        node = self.nodes[node_id]
        spec = getattr(node, "spec", None)
        tags = getattr(spec, "tags", None) or []
        if "ifelse" in tags:
            return True
        return node.type in self.IFELSE_TYPES

    def build_ifelse_sets(self) -> None:
        """Build tracking sets for If/Else nodes and their branches."""
        self.ifelse_nodes = {node_id for node_id in self.nodes if self.is_ifelse_node(node_id)}
        self.ifelse_true_branch = {}
        self.ifelse_false_branch = {}
        self.nodes_in_ifelse_branch = set()

        for ifelse_id in self.ifelse_nodes:
            true_nodes = self.collect_branch_nodes(ifelse_id, "true")
            false_nodes = self.collect_branch_nodes(ifelse_id, "false")
            shared_nodes = true_nodes & false_nodes
            if shared_nodes:
                true_nodes -= shared_nodes
                false_nodes -= shared_nodes
            self.ifelse_true_branch[ifelse_id] = true_nodes
            self.ifelse_false_branch[ifelse_id] = false_nodes
            self.nodes_in_ifelse_branch.update(true_nodes)
            self.nodes_in_ifelse_branch.update(false_nodes)

    def collect_branch_nodes(self, ifelse_id: str, branch_port: str) -> Set[str]:
        """Collect all nodes reachable from an If/Else branch output.

        Args:
            ifelse_id: The if/else node ID
            branch_port: Either "true" or "false"

        Returns:
            Set of node IDs in this branch
        """
        branch_nodes: Set[str] = set()
        queue = deque()

        # Start from nodes connected to the specified branch port
        for to_node, from_port, _ in self.control_outputs.get(ifelse_id, []):
            if from_port == branch_port:
                queue.append(to_node)

        while queue:
            node_id = queue.popleft()
            if node_id in branch_nodes:
                continue
            branch_nodes.add(node_id)

            # Follow control outputs (but handle nested loops/if-else specially)
            child_outputs = self.control_outputs.get(node_id, [])

            if self.loop_handler.is_loop_node(node_id):
                # For loops, only follow the 'completed' output to stay in branch
                for child, from_port, _ in child_outputs:
                    if from_port == "completed" and child not in branch_nodes:
                        queue.append(child)
            elif self.is_ifelse_node(node_id):
                # For nested if/else, follow both true and false outputs
                for child, _, _ in child_outputs:
                    if child not in branch_nodes:
                        queue.append(child)
            else:
                # Regular nodes, follow all control outputs
                for child, _, _ in child_outputs:
                    if child not in branch_nodes:
                        queue.append(child)

        return branch_nodes


class BranchHandler:
    """Handles parallel branch detection from Start nodes."""

    START_TYPES = {"core.control.start"}

    def __init__(
        self,
        nodes: Dict[str, "NodeBase"],
        control_outputs: Dict[str, List[Tuple[str, str, str]]],
        input_map: Dict[str, Dict[str, Any]],
        links: List[Any],
    ) -> None:
        """Initialize the branch handler.

        Args:
            nodes: All nodes in the graph
            control_outputs: Mapping of node_id -> [(target, from_port, to_port)]
            input_map: Mapping of node_id -> port -> Link
            links: All links in the graph
        """
        self.nodes = nodes
        self.control_outputs = control_outputs
        self.input_map = input_map
        self.links = links

        self.start_nodes: Set[str] = set()
        self.branch_roots: Dict[str, str] = {}  # node_id -> branch_id
        self.branches: Dict[str, Set[str]] = {}  # branch_id -> set of nodes
        self.merge_points: Set[str] = set()  # Nodes receiving inputs from multiple branches

    def is_start_node(self, node_id: str) -> bool:
        """Check if a node is a Start control node."""
        node = self.nodes[node_id]
        spec = getattr(node, "spec", None)
        tags = getattr(spec, "tags", None) or []
        if "start" in tags:
            return True
        return node.type in self.START_TYPES

    def build_branch_info(self) -> None:
        """Detect parallel branches from Start nodes and identify merge points.

        This implements the hybrid execution model:
        - Identify Start nodes (core.control.start)
        - Trace branches from each Start node's control outputs
        - Nodes reachable only via data dependencies are "dataflow" nodes
        - Nodes with control connections are "controlflow" nodes
        - Merge points are nodes that receive inputs from multiple distinct branches
        """
        # Find all Start nodes
        self.start_nodes = {node_id for node_id in self.nodes if self.is_start_node(node_id)}

        if not self.start_nodes:
            # No Start nodes - pure dataflow execution
            return

        # Trace branches from each Start node
        for start_id in self.start_nodes:
            control_targets = self.control_outputs.get(start_id, [])

            if len(control_targets) <= 1:
                # Single or no control output - linear execution
                branch_id = start_id
                self.branches[branch_id] = set()
                self._trace_branch(start_id, branch_id)
            else:
                # Multiple control outputs - parallel branches
                for i, (target_node, _, _) in enumerate(control_targets):
                    branch_id = f"{start_id}_branch_{i}"
                    self.branches[branch_id] = set()
                    self._trace_branch_from(target_node, branch_id)

        # Identify merge points: nodes receiving data from multiple branches
        for node_id in self.nodes:
            if node_id in self.start_nodes:
                continue
            input_branches = set()
            for link in self.input_map.get(node_id, {}).values():
                from_branch = self.branch_roots.get(link.from_node)
                if from_branch:
                    input_branches.add(from_branch)

            if len(input_branches) > 1:
                self.merge_points.add(node_id)

    def _trace_branch(self, start_id: str, branch_id: str) -> None:
        """Trace all nodes reachable from a Start node via control flow."""
        queue = deque([start_id])
        while queue:
            node_id = queue.popleft()
            if node_id in self.branch_roots:
                continue  # Already assigned to a branch
            self.branch_roots[node_id] = branch_id
            self.branches[branch_id].add(node_id)

            # Follow control outputs
            for target, _, _ in self.control_outputs.get(node_id, []):
                if target not in self.branch_roots:
                    queue.append(target)

    def _trace_branch_from(self, node_id: str, branch_id: str) -> None:
        """Trace a branch starting from a specific node (not the Start)."""
        queue = deque([node_id])
        while queue:
            current = queue.popleft()
            if current in self.branch_roots:
                continue  # Already assigned to a branch
            self.branch_roots[current] = branch_id
            self.branches[branch_id].add(current)

            # Follow control outputs
            for target, _, _ in self.control_outputs.get(current, []):
                if target not in self.branch_roots:
                    queue.append(target)

    def has_cross_branch_data_edges(self) -> bool:
        """Check if there are data edges that cross branch boundaries."""
        for link in self.links:
            if link.kind == "control":
                continue
            from_branch = self.branch_roots.get(link.from_node)
            to_branch = self.branch_roots.get(link.to_node)
            if from_branch and to_branch and from_branch != to_branch:
                return True
        return False


__all__ = ["LoopHandler", "IfElseHandler", "BranchHandler"]
