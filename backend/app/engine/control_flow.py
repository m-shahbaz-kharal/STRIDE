"""
Control flow analysis utilities extracted from GraphExecutor.

This module contains logic for analyzing and building control flow structures:
- Loop detection and body collection
- If/Else branch detection
- Branch tracing from Start nodes
- Merge point detection
"""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from ..nodes import NodeBase


def is_loop_node(node: "NodeBase") -> bool:
    """Check if a node is a loop node."""
    spec = getattr(node, "spec", None)
    tags = getattr(spec, "tags", None) or []
    if "loop" in tags:
        return True
    return node.type in {"core.control.for", "core.control.while"}


def is_ifelse_node(node: "NodeBase") -> bool:
    """Check if a node is an if/else node."""
    spec = getattr(node, "spec", None)
    tags = getattr(spec, "tags", None) or []
    if "ifelse" in tags:
        return True
    return node.type == "core.control.ifelse"


def is_start_node(node: "NodeBase") -> bool:
    """Check if a node is a start node."""
    spec = getattr(node, "spec", None)
    tags = getattr(spec, "tags", None) or []
    if "start" in tags:
        return True
    return node.type == "core.control.start"


def collect_loop_body_nodes(
    loop_id: str,
    nodes: Dict[str, "NodeBase"],
    control_outputs: Dict[str, List[Tuple[str, str, str]]],
) -> Set[str]:
    """Collect all nodes that are part of a loop's body."""
    body_nodes: Set[str] = set()
    queue = deque()
    
    for to_node, from_port, _ in control_outputs.get(loop_id, []):
        if from_port == "loop_body":
            queue.append(to_node)
    
    while queue:
        node_id = queue.popleft()
        if node_id in body_nodes:
            continue
        body_nodes.add(node_id)
        child_outputs = control_outputs.get(node_id, [])
        
        if is_loop_node(nodes[node_id]) and node_id != loop_id:
            # For nested loops, only follow the 'completed' output
            for child, from_port, _ in child_outputs:
                if from_port == "completed" and child not in body_nodes:
                    queue.append(child)
            continue
        
        for child, _, _ in child_outputs:
            if child not in body_nodes:
                queue.append(child)
    
    return body_nodes


def build_loop_sets(
    nodes: Dict[str, "NodeBase"],
    topo_order: List[str],
    control_outputs: Dict[str, List[Tuple[str, str, str]]],
) -> Tuple[
    Set[str],  # loop_nodes
    Dict[str, Set[str]],  # loop_body_nodes
    Set[str],  # nodes_in_loop_body
    Dict[str, str],  # loop_parent
]:
    """Build tracking sets for loop nodes and their bodies."""
    loop_nodes = {node_id for node_id, node in nodes.items() if is_loop_node(node)}
    loop_body_nodes: Dict[str, Set[str]] = {}
    nodes_in_loop_body: Set[str] = set()
    loop_parent: Dict[str, str] = {}
    
    for loop_id in loop_nodes:
        body_nodes = collect_loop_body_nodes(loop_id, nodes, control_outputs)
        loop_body_nodes[loop_id] = body_nodes
        nodes_in_loop_body.update(body_nodes)
    
    for node_id in topo_order:
        if node_id not in loop_nodes:
            continue
        for body_id in loop_body_nodes.get(node_id, set()):
            loop_parent.setdefault(body_id, node_id)
    
    return loop_nodes, loop_body_nodes, nodes_in_loop_body, loop_parent


def collect_branch_nodes(
    ifelse_id: str,
    branch_port: str,
    nodes: Dict[str, "NodeBase"],
    control_outputs: Dict[str, List[Tuple[str, str, str]]],
) -> Set[str]:
    """Collect all nodes reachable from an If/Else branch output."""
    branch_nodes: Set[str] = set()
    queue = deque()
    
    # Start from nodes connected to the specified branch port
    for to_node, from_port, _ in control_outputs.get(ifelse_id, []):
        if from_port == branch_port:
            queue.append(to_node)
    
    while queue:
        node_id = queue.popleft()
        if node_id in branch_nodes:
            continue
        branch_nodes.add(node_id)
        
        child_outputs = control_outputs.get(node_id, [])
        node = nodes[node_id]
        
        if is_loop_node(node):
            # For loops, only follow the 'completed' output to stay in branch
            for child, from_port, _ in child_outputs:
                if from_port == "completed" and child not in branch_nodes:
                    queue.append(child)
        elif is_ifelse_node(node):
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


def build_ifelse_sets(
    nodes: Dict[str, "NodeBase"],
    control_outputs: Dict[str, List[Tuple[str, str, str]]],
) -> Tuple[
    Set[str],  # ifelse_nodes
    Dict[str, Set[str]],  # true_branch
    Dict[str, Set[str]],  # false_branch
    Set[str],  # nodes_in_ifelse_branch
]:
    """Build tracking sets for If/Else nodes and their branches."""
    ifelse_nodes = {node_id for node_id, node in nodes.items() if is_ifelse_node(node)}
    true_branch: Dict[str, Set[str]] = {}
    false_branch: Dict[str, Set[str]] = {}
    nodes_in_ifelse_branch: Set[str] = set()
    
    for ifelse_id in ifelse_nodes:
        true_nodes = collect_branch_nodes(ifelse_id, "true", nodes, control_outputs)
        false_nodes = collect_branch_nodes(ifelse_id, "false", nodes, control_outputs)
        
        # Remove shared nodes from both branches
        shared_nodes = true_nodes & false_nodes
        if shared_nodes:
            true_nodes -= shared_nodes
            false_nodes -= shared_nodes
        
        true_branch[ifelse_id] = true_nodes
        false_branch[ifelse_id] = false_nodes
        nodes_in_ifelse_branch.update(true_nodes)
        nodes_in_ifelse_branch.update(false_nodes)
    
    return ifelse_nodes, true_branch, false_branch, nodes_in_ifelse_branch


def trace_branch(
    start_id: str,
    branch_id: str,
    control_outputs: Dict[str, List[Tuple[str, str, str]]],
    branch_roots: Dict[str, str],
    branches: Dict[str, Set[str]],
) -> None:
    """Trace all nodes reachable from a Start node via control flow."""
    queue = deque([start_id])
    while queue:
        node_id = queue.popleft()
        if node_id in branch_roots:
            continue  # Already assigned to a branch
        branch_roots[node_id] = branch_id
        branches[branch_id].add(node_id)
        
        # Follow control outputs
        for target, _, _ in control_outputs.get(node_id, []):
            if target not in branch_roots:
                queue.append(target)


def trace_branch_from(
    node_id: str,
    branch_id: str,
    control_outputs: Dict[str, List[Tuple[str, str, str]]],
    branch_roots: Dict[str, str],
    branches: Dict[str, Set[str]],
) -> None:
    """Trace a branch starting from a specific node (not the Start)."""
    queue = deque([node_id])
    while queue:
        current = queue.popleft()
        if current in branch_roots:
            continue  # Already assigned to a branch
        branch_roots[current] = branch_id
        branches[branch_id].add(current)
        
        # Follow control outputs
        for target, _, _ in control_outputs.get(current, []):
            if target not in branch_roots:
                queue.append(target)


def build_branch_info(
    nodes: Dict[str, "NodeBase"],
    input_map: Dict[str, Dict[str, Any]],
    control_outputs: Dict[str, List[Tuple[str, str, str]]],
) -> Tuple[
    Set[str],  # start_nodes
    Dict[str, str],  # branch_roots
    Dict[str, Set[str]],  # branches
    Set[str],  # merge_points
]:
    """Detect parallel branches from Start nodes and identify merge points.
    
    This implements the hybrid execution model:
    - Identify Start nodes (core.control.start)
    - Trace branches from each Start node's control outputs
    - Nodes reachable only via data dependencies are "dataflow" nodes
    - Nodes with control connections are "controlflow" nodes
    - Merge points are nodes that receive inputs from multiple distinct branches
    """
    start_nodes = {node_id for node_id, node in nodes.items() if is_start_node(node)}
    branch_roots: Dict[str, str] = {}
    branches: Dict[str, Set[str]] = {}
    merge_points: Set[str] = set()
    
    if not start_nodes:
        # No Start nodes - pure dataflow execution
        return start_nodes, branch_roots, branches, merge_points
    
    # Trace branches from each Start node
    for start_id in start_nodes:
        control_targets = control_outputs.get(start_id, [])
        
        if len(control_targets) <= 1:
            # Single or no control output - linear execution
            branch_id = start_id
            branches[branch_id] = set()
            trace_branch(start_id, branch_id, control_outputs, branch_roots, branches)
        else:
            # Multiple control outputs - parallel branches
            for i, (target_node, _, _) in enumerate(control_targets):
                branch_id = f"{start_id}_branch_{i}"
                branches[branch_id] = set()
                trace_branch_from(target_node, branch_id, control_outputs, branch_roots, branches)
    
    # Identify merge points: nodes receiving data from multiple branches
    for node_id in nodes:
        if node_id in start_nodes:
            continue
        input_branches = set()
        for link in input_map.get(node_id, {}).values():
            from_branch = branch_roots.get(link.from_node)
            if from_branch:
                input_branches.add(from_branch)
        
        if len(input_branches) > 1:
            merge_points.add(node_id)
    
    return start_nodes, branch_roots, branches, merge_points
