from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor
from collections import defaultdict, deque
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple

from .execution import (
    ExecutionCache,
    ExecutionEvent,
    ExecutionStats,
    GraphExecutionError,
    Link,
    NodeExecutionResult,
    NodeStatus,
)
from .nodes import ExecutionContext, NodeBase, get_node
from .typesystem import TypeDescriptor


class _CancellationController:
    def __init__(self, state_lock: threading.Lock) -> None:
        self._state_lock = state_lock
        self._cancel_all = threading.Event()
        self._cancelled_nodes: Set[str] = set()
        self._running_tasks: Dict[str, asyncio.Future] = {}

    def reset(self) -> None:
        self._cancel_all.clear()
        self._cancelled_nodes.clear()
        with self._state_lock:
            self._running_tasks = {}

    def cancel_all(self) -> None:
        self._cancel_all.set()
        self.cancel_running_tasks()

    def cancel_node(self, node_id: str) -> None:
        self._cancelled_nodes.add(node_id)
        self.cancel_running_tasks(target=node_id)

    def should_stop(self) -> bool:
        return self._cancel_all.is_set()

    def is_cancelled(self, node_id: Optional[str] = None) -> bool:
        if self._cancel_all.is_set():
            return True
        if node_id is not None and node_id in self._cancelled_nodes:
            return True
        return False

    def register_running(self, node_id: str, fut: asyncio.Future) -> None:
        with self._state_lock:
            self._running_tasks[node_id] = fut

    def clear_running(self, node_id: str) -> None:
        with self._state_lock:
            self._running_tasks.pop(node_id, None)

    def cancel_running_tasks(self, target: Optional[str] = None) -> None:
        with self._state_lock:
            items = list(self._running_tasks.items())
        for node_id, fut in items:
            if target and node_id != target:
                continue
            if not fut.done():
                fut.cancel()


class GraphExecutor:
    """High-performance graph executor with level-based parallel execution and caching."""

    _active_executions: Dict[str, "GraphExecutor"] = {}
    _active_lock = threading.Lock()

    @classmethod
    def clear_cache(cls) -> int:
        """Clear the global execution cache. Returns number of entries cleared."""
        return ExecutionCache.clear_all()

    @classmethod
    def clear_cache_by_type(cls, node_type: str) -> int:
        """Clear cache entries for a specific node type. Returns number of entries cleared."""
        return ExecutionCache.clear_by_type(node_type)

    @classmethod
    def get_cache_size(cls) -> int:
        """Get the current number of cached entries."""
        return ExecutionCache.size()

    def __init__(self, graph_definition: Dict[str, Any], options: Optional[Dict[str, Any]] = None) -> None:
        self.definition = graph_definition
        self.nodes: Dict[str, NodeBase] = {}
        self.links: List[Link] = []
        self.input_map: Dict[str, Dict[str, Link]] = defaultdict(dict)
        self.control_inputs: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        self.control_outputs: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
        self.output_map: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
        self._dependents: Dict[str, List[str]] = defaultdict(list)
        self.execution_trace: List[NodeExecutionResult] = []
        self.outputs: Dict[str, Any] = {}
        self.options: Dict[str, Any] = options or {}
        self.execution_id = str(uuid.uuid4())[:8]
        self._max_workers = int(
            self.options.get(
                "max_workers",
                max(2, min(32, (os.cpu_count() or 4) + 2)),
            )
        )
        self._fail_fast = bool(self.options.get("fail_fast", True))
        
        # Execution state
        self._computed_values: Dict[str, Dict[str, Any]] = {}
        self._node_status: Dict[str, NodeStatus] = {}
        self._node_levels: Dict[str, int] = {}
        self._levels: List[List[str]] = []  # Nodes grouped by topological level
        self._total_execution_time_ms: float = 0.0  # Actual wall-clock time
        self._max_parallelism: int = 0
        self._state_lock = threading.Lock()
        self._thread_pool: Optional[ThreadPoolExecutor] = None
        self._cancellation = _CancellationController(self._state_lock)
        self._variables: Dict[str, Any] = {}
        self._shared_metadata: Dict[str, Any] = {}
        self._resources: List[Tuple[str, Any]] = []
        
        # Caching options
        self._cache = ExecutionCache(enabled=self.options.get("use_cache", True))
        
        self._execution_order: List[str] = []
        self._loop_nodes: Set[str] = set()
        self._loop_body_nodes: Dict[str, Set[str]] = {}
        self._nodes_in_loop_body: Set[str] = set()
        
        # If/Else branch tracking
        self._ifelse_nodes: Set[str] = set()
        self._ifelse_true_branch: Dict[str, Set[str]] = {}  # ifelse_id -> nodes reachable from 'true' port
        self._ifelse_false_branch: Dict[str, Set[str]] = {}  # ifelse_id -> nodes reachable from 'false' port
        self._nodes_in_ifelse_branch: Set[str] = set()  # All nodes that are in an if/else branch
        self._skipped_branches: Set[str] = set()  # Nodes skipped due to if/else condition
        
        # Branch detection for hybrid execution model
        self._start_nodes: Set[str] = set()  # Nodes with type core.control.start
        self._branch_roots: Dict[str, str] = {}  # node_id -> branch_id (root start node)
        self._branches: Dict[str, Set[str]] = {}  # branch_id -> set of nodes in that branch
        self._merge_points: Set[str] = set()  # Nodes receiving inputs from multiple branches
        self._branch_completed: Dict[str, asyncio.Event] = {}  # Events for branch completion

        self._build_nodes()
        self._build_links()
        self._validate_output_nodes()
        self._topo_order = self._topological_sort()
        self._compute_levels()
        self._build_loop_sets()
        self._build_ifelse_sets()
        self._build_branch_info()

    @classmethod
    def _register_execution(cls, executor: "GraphExecutor") -> None:
        with cls._active_lock:
            cls._active_executions[executor.execution_id] = executor

    @classmethod
    def _unregister_execution(cls, execution_id: str) -> None:
        with cls._active_lock:
            cls._active_executions.pop(execution_id, None)

    @classmethod
    def cancel_execution(cls, execution_id: str) -> bool:
        with cls._active_lock:
            executor = cls._active_executions.get(execution_id)
        if not executor:
            return False
        executor._cancellation.cancel_all()
        executor._cleanup_resources()
        return True

    @classmethod
    def cancel_node(cls, execution_id: str, node_id: str) -> bool:
        with cls._active_lock:
            executor = cls._active_executions.get(execution_id)
        if not executor:
            return False
        executor._cancellation.cancel_node(node_id)
        executor._cleanup_resources(node_id)
        return True

    def _reset_execution_state(self) -> None:
        """Reset per-run execution state so subsequent runs are isolated."""
        self.execution_trace = []
        self.outputs = {}
        self._computed_values = {}
        self._variables = {}
        self._shared_metadata = {}
        self._resources = []
        self._skipped_branches = set()  # Reset If/Else skipped branches
        self._cancellation.reset()

    def _cleanup_resources(self, target_node_id: Optional[str] = None) -> None:
        """Close and cleanup any registered resources."""
        to_close: List[Tuple[str, Any]] = []
        remaining: List[Tuple[str, Any]] = []
        with self._state_lock:
            for node_id, resource in self._resources:
                if target_node_id is None or node_id == target_node_id:
                    to_close.append((node_id, resource))
                else:
                    remaining.append((node_id, resource))
            self._resources = remaining

        for _, resource in to_close:
            if hasattr(resource, "close") and callable(resource.close):
                try:
                    resource.close()
                except Exception:
                    pass

    def _can_cache(self, node_id: str) -> bool:
        node = self.nodes[node_id]
        spec = getattr(node, "spec", None)
        if spec and getattr(spec, "cache_policy", "default") == "disabled":
            return False
        return True

    @staticmethod
    def _normalize_type(raw_type: Any) -> Optional[TypeDescriptor]:
        """Normalize type descriptors from backend/liguard_core into a backend TypeDescriptor."""
        if raw_type is None:
            return None
        if isinstance(raw_type, TypeDescriptor):
            return raw_type
        if isinstance(raw_type, dict):
            payload = dict(raw_type)
            kind = payload.get("kind")
            if "element_type" in payload and "elementType" not in payload:
                payload["elementType"] = payload.pop("element_type")
            if "key_type" in payload and "keyType" not in payload:
                payload["keyType"] = payload.pop("key_type")
            element_type = payload.pop("elementType", None)
            payload.pop("keyType", None)
            if element_type is not None:
                if kind == "map":
                    payload.setdefault("value", element_type)
                else:
                    payload.setdefault("item", element_type)
            if kind == "map" and "value" not in payload and "item" in payload:
                payload["value"] = payload["item"]
            return TypeDescriptor.from_dict(payload)
        kind = getattr(raw_type, "kind", None)
        if kind:
            element_type = getattr(raw_type, "element_type", None)
            fields = getattr(raw_type, "fields", None)
            nullable = bool(getattr(raw_type, "nullable", False))
            metadata = getattr(raw_type, "metadata", {}) or {}
            item = None
            value = None
            if kind == "map":
                value = GraphExecutor._normalize_type(element_type) if element_type else None
            else:
                item = GraphExecutor._normalize_type(element_type) if element_type else None
            fields_norm = (
                {k: GraphExecutor._normalize_type(v) for k, v in fields.items()}
                if fields
                else None
            )
            return TypeDescriptor(
                kind=kind,
                item=item,
                value=value,
                fields=fields_norm,
                nullable=nullable,
                metadata=metadata,
            )
        if isinstance(raw_type, str):
            return TypeDescriptor(kind=raw_type)
        return None

    def _collect_dependents(self, node_id: str) -> Set[str]:
        """Collect all transitive dependents of a node."""
        collected: Set[str] = set()
        stack = list(self._dependents.get(node_id, []))
        while stack:
            current = stack.pop()
            if current in collected:
                continue
            collected.add(current)
            stack.extend(self._dependents.get(current, []))
        return collected

    def _record_skipped_dependents(
        self,
        node_id: str,
        reason: str,
        execution_set: Optional[Set[str]] = None,
    ) -> List[NodeExecutionResult]:
        results: List[NodeExecutionResult] = []
        for dep in self._collect_dependents(node_id):
            if execution_set is not None and dep not in execution_set:
                continue
            if self._node_status.get(dep) != NodeStatus.PENDING:
                continue
            result = NodeExecutionResult(
                node_id=dep,
                node_type=self.nodes[dep].type,
                status=NodeStatus.SKIPPED,
                logs=[reason],
                duration_ms=0.0,
                level=self._node_levels.get(dep, 0),
                from_cache=False,
            )
            self._finalize_node_result(dep, {}, result, cached=False)
            results.append(result)
        return results

    def _try_get_cached(self, node_id: str, inputs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Try to get cached outputs for a node. Returns None if not cached or disabled."""
        if not self._can_cache(node_id):
            return None
        node = self.nodes[node_id]
        return self._cache.get(node.type, node.params, inputs)

    def _cache_outputs(self, node_id: str, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        """Cache the outputs for a node when caching is enabled."""
        if not self._can_cache(node_id):
            return
        node = self.nodes[node_id]
        self._cache.set(node.type, node.params, inputs, outputs)

    def _build_nodes(self) -> None:
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
            self.nodes[node.id] = node
            self._node_status[node.id] = NodeStatus.PENDING

    def _build_links(self) -> None:
        seen_links: Set[Tuple[str, str, str, str]] = set()
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
                from_type = self._normalize_type(from_node.output_port_types.get(link.from_port))
                to_type = self._normalize_type(to_node.input_port_types.get(link.to_port))
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

    def _validate_output_nodes(self) -> None:
        """Validate that declared output nodes reference valid ports."""
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

    def _topological_sort(self) -> List[str]:
        """Kahn's algorithm for topological sorting."""
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

    def _compute_levels(self) -> None:
        """Compute topological levels for parallel execution.
        
        Nodes at the same level have no dependencies on each other
        and can be executed in parallel.
        """
        levels: Dict[str, int] = {}
        
        for node_id in self._topo_order:
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
        
        self._node_levels = levels
        
        level_groups: Dict[int, List[str]] = defaultdict(list)
        for node_id, level in levels.items():
            level_groups[level].append(node_id)
        
        max_level = max(levels.values()) if levels else 0
        self._levels = [level_groups.get(i, []) for i in range(max_level + 1)]

    def _is_loop_node(self, node_id: str) -> bool:
        node = self.nodes[node_id]
        spec = getattr(node, "spec", None)
        tags = getattr(spec, "tags", None) or []
        if "loop" in tags:
            return True
        return node.type in {"core.control.for", "core.control.repeat", "core.control.while"}

    def _is_ifelse_node(self, node_id: str) -> bool:
        node = self.nodes[node_id]
        spec = getattr(node, "spec", None)
        tags = getattr(spec, "tags", None) or []
        if "ifelse" in tags:
            return True
        return node.type == "core.control.ifelse"

    def _is_start_node(self, node_id: str) -> bool:
        node = self.nodes[node_id]
        spec = getattr(node, "spec", None)
        tags = getattr(spec, "tags", None) or []
        if "start" in tags:
            return True
        return node.type == "core.control.start"

    def _build_loop_sets(self) -> None:
        self._loop_nodes = {node_id for node_id in self.nodes if self._is_loop_node(node_id)}
        self._loop_body_nodes = {}
        self._nodes_in_loop_body = set()
        for loop_id in self._loop_nodes:
            body_nodes = self._collect_loop_body_nodes(loop_id)
            self._loop_body_nodes[loop_id] = body_nodes
            self._nodes_in_loop_body.update(body_nodes)

    def _collect_loop_body_nodes(self, loop_id: str) -> Set[str]:
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
            if self._is_loop_node(node_id) and node_id != loop_id:
                for child, from_port, _ in child_outputs:
                    if from_port == "completed" and child not in body_nodes:
                        queue.append(child)
                continue
            for child, _, _ in child_outputs:
                if child not in body_nodes:
                    queue.append(child)
        return body_nodes

    def _build_ifelse_sets(self) -> None:
        """Build tracking sets for If/Else nodes and their branches."""
        self._ifelse_nodes = {node_id for node_id in self.nodes if self._is_ifelse_node(node_id)}
        self._ifelse_true_branch = {}
        self._ifelse_false_branch = {}
        self._nodes_in_ifelse_branch = set()
        
        for ifelse_id in self._ifelse_nodes:
            true_nodes = self._collect_branch_nodes(ifelse_id, "true")
            false_nodes = self._collect_branch_nodes(ifelse_id, "false")
            shared_nodes = true_nodes & false_nodes
            if shared_nodes:
                true_nodes -= shared_nodes
                false_nodes -= shared_nodes
            self._ifelse_true_branch[ifelse_id] = true_nodes
            self._ifelse_false_branch[ifelse_id] = false_nodes
            self._nodes_in_ifelse_branch.update(true_nodes)
            self._nodes_in_ifelse_branch.update(false_nodes)

    def _collect_branch_nodes(self, ifelse_id: str, branch_port: str) -> Set[str]:
        """Collect all nodes reachable from an If/Else branch output."""
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
            node_type = self.nodes[node_id].type
            
            if self._is_loop_node(node_id):
                # For loops, only follow the 'completed' output to stay in branch
                for child, from_port, _ in child_outputs:
                    if from_port == "completed" and child not in branch_nodes:
                        queue.append(child)
            elif self._is_ifelse_node(node_id):
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

    def _build_branch_info(self) -> None:
        """Detect parallel branches from Start nodes and identify merge points.
        
        This implements the hybrid execution model:
        - Identify Start nodes (core.control.start)
        - Trace branches from each Start node's control outputs
        - Nodes reachable only via data dependencies are "dataflow" nodes
        - Nodes with control connections are "controlflow" nodes
        - Merge points are nodes that receive inputs from multiple distinct branches
        """
        # Find all Start nodes
        self._start_nodes = {node_id for node_id in self.nodes if self._is_start_node(node_id)}
        
        if not self._start_nodes:
            # No Start nodes - pure dataflow execution
            return
        
        # Trace branches from each Start node
        for start_id in self._start_nodes:
            control_targets = self.control_outputs.get(start_id, [])
            
            if len(control_targets) <= 1:
                # Single or no control output - linear execution
                branch_id = start_id
                self._branches[branch_id] = set()
                self._trace_branch(start_id, branch_id)
            else:
                # Multiple control outputs - parallel branches
                for i, (target_node, _, _) in enumerate(control_targets):
                    branch_id = f"{start_id}_branch_{i}"
                    self._branches[branch_id] = set()
                    self._trace_branch_from(target_node, branch_id)
        
        # Identify merge points: nodes receiving data from multiple branches
        for node_id in self.nodes:
            if node_id in self._start_nodes:
                continue
            input_branches = set()
            for link in self.input_map.get(node_id, {}).values():
                from_branch = self._branch_roots.get(link.from_node)
                if from_branch:
                    input_branches.add(from_branch)
            
            if len(input_branches) > 1:
                self._merge_points.add(node_id)

    def _has_cross_branch_data_edges(self) -> bool:
        for link in self.links:
            if link.kind == "control":
                continue
            from_branch = self._branch_roots.get(link.from_node)
            to_branch = self._branch_roots.get(link.to_node)
            if from_branch and to_branch and from_branch != to_branch:
                return True
        return False
    
    def _trace_branch(self, start_id: str, branch_id: str) -> None:
        """Trace all nodes reachable from a Start node via control flow."""
        queue = deque([start_id])
        while queue:
            node_id = queue.popleft()
            if node_id in self._branch_roots:
                continue  # Already assigned to a branch
            self._branch_roots[node_id] = branch_id
            self._branches[branch_id].add(node_id)
            
            # Follow control outputs
            for target, _, _ in self.control_outputs.get(node_id, []):
                if target not in self._branch_roots:
                    queue.append(target)
    
    def _trace_branch_from(self, node_id: str, branch_id: str) -> None:
        """Trace a branch starting from a specific node (not the Start)."""
        queue = deque([node_id])
        while queue:
            current = queue.popleft()
            if current in self._branch_roots:
                continue  # Already assigned to a branch
            self._branch_roots[current] = branch_id
            self._branches[branch_id].add(current)
            
            # Follow control outputs
            for target, _, _ in self.control_outputs.get(current, []):
                if target not in self._branch_roots:
                    queue.append(target)

    def _expand_dependencies(self, node_ids: List[str]) -> Set[str]:
        """Expand a set of target nodes to include all their dependencies."""
        queue = deque(node_ids)
        collected: Set[str] = set()
        while queue:
            current = queue.popleft()
            if current in collected or current not in self.nodes:
                continue
            collected.add(current)
            for link in self.input_map.get(current, {}).values():
                if link.from_node not in collected:
                    queue.append(link.from_node)
            for parent, _ in self.control_inputs.get(current, []):
                if parent not in collected:
                    queue.append(parent)
        return collected

    def _resolve_execution_order(self) -> List[str]:
        """Resolve which nodes to execute based on options."""
        mode = str(self.options.get("mode", "full")).lower()
        if mode == "selection":
            target_nodes = [node_id for node_id in (self.options.get("target_nodes") or []) if node_id in self.nodes]
            if target_nodes:
                allowed = self._expand_dependencies(target_nodes)
                return [
                    node_id
                    for node_id in self._topo_order
                    if node_id in allowed and node_id not in self._nodes_in_loop_body
                ]
        return [node_id for node_id in self._topo_order if node_id not in self._nodes_in_loop_body]

    def _resolve_execution_levels(self) -> List[List[str]]:
        """Get execution levels filtered by the resolved execution order."""
        execution_set = set(self._execution_order)
        return [
            [node_id for node_id in level if node_id in execution_set]
            for level in self._levels
        ]

    def _gather_inputs(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Gather inputs for a node from computed values."""
        node = self.nodes[node_id]
        if not node.input_ports:
            return {}
        inputs: Dict[str, Any] = {}
        port_specs = {p.name: p for p in (node.spec.inputs if getattr(node, "spec", None) else [])}
        input_values = node.input_values or {}
        for port in node.input_ports:
            port_type = self._normalize_type(node.input_port_types.get(port))
            if isinstance(port_type, TypeDescriptor) and port_type.kind == "control":
                # Control ports are sequencing only; no data value needed.
                continue
            link = self.input_map.get(node_id, {}).get(port)
            if link:
                if link.from_node not in self._computed_values:
                    return None
                value = self._computed_values[link.from_node].get(link.from_port)
                inputs[port] = value
                continue
            if port in input_values:
                inputs[port] = input_values[port]
                continue
            if port in node.params:
                inputs[port] = node.params.get(port)
                continue
            port_spec = port_specs.get(port)
            if port_spec and port_spec.default is not None:
                inputs[port] = port_spec.default
                continue
            if port_spec and not port_spec.required:
                inputs[port] = None
                continue
            raise GraphExecutionError(f"Node '{node_id}' is missing link for port '{port}'", code="missing_link")
        return inputs

    def _prepare_inputs(self, node_id: str) -> Dict[str, Any]:
        """Gather inputs and raise if dependencies are not ready."""
        inputs = self._gather_inputs(node_id)
        if inputs is None:
            raise GraphExecutionError(f"Node '{node_id}' could not resolve inputs")
        return inputs

    def _finalize_node_result(
        self,
        node_id: str,
        inputs: Dict[str, Any],
        result: NodeExecutionResult,
        cached: bool = False,
        allow_cache: bool = True,
    ) -> None:
        """Persist a node result back into executor state."""
        if result.status == NodeStatus.COMPLETED:
            if not cached and allow_cache:
                self._cache_outputs(node_id, inputs, result.outputs)
            with self._state_lock:
                self._computed_values[node_id] = result.outputs
        self._node_status[node_id] = result.status
        self.execution_trace.append(result)
        self._cancellation.clear_running(node_id)

    def _should_interrupt(self, node_id: Optional[str] = None) -> bool:
        return self._cancellation.is_cancelled(node_id)

    def _should_stop_execution(self) -> bool:
        return self._cancellation.should_stop()

    def _make_interrupted_result(self, node_id: str) -> NodeExecutionResult:
        return NodeExecutionResult(
            node_id=node_id,
            node_type=self.nodes[node_id].type,
            status=NodeStatus.SKIPPED,
            logs=[f"Node {node_id} interrupted"],
            duration_ms=0.0,
            level=self._node_levels.get(node_id, 0),
            from_cache=False,
        )

    def _make_input_error_result(self, node_id: str, exc: Exception) -> NodeExecutionResult:
        return NodeExecutionResult(
            node_id=node_id,
            node_type=self.nodes[node_id].type,
            status=NodeStatus.ERROR,
            error=str(exc),
            error_code=getattr(exc, "code", None),
            duration_ms=0.0,
            level=self._node_levels.get(node_id, 0),
            from_cache=False,
        )

    def _record_interrupted(
        self,
        node_id: str,
        inputs: Optional[Dict[str, Any]] = None,
        allow_cache: bool = False,
    ) -> NodeExecutionResult:
        result = self._make_interrupted_result(node_id)
        self._finalize_node_result(node_id, inputs or {}, result, cached=False, allow_cache=allow_cache)
        return result

    def _mark_pending_interrupted(self, node_ids: Set[str]) -> List[NodeExecutionResult]:
        results: List[NodeExecutionResult] = []
        for node_id in node_ids:
            if self._node_status.get(node_id) != NodeStatus.PENDING:
                continue
            results.append(self._record_interrupted(node_id))
        return results

    def _execute_node_work(self, node_id: str, inputs: Dict[str, Any]) -> NodeExecutionResult:
        """Execute a node in an isolated worker thread without mutating shared state."""
        node = self.nodes[node_id]
        level = self._node_levels.get(node_id, 0)
        start_time = time.perf_counter()

        try:
            ctx = ExecutionContext()
            ctx.variables = self._variables
            ctx.metadata = self._shared_metadata
            
            # Hook up resource registration
            def _register_resource(r: Any) -> None:
                with self._state_lock:
                    self._resources.append((node_id, r))
            ctx.register_resource = _register_resource

            outputs = node.forward(inputs, ctx)

            if set(outputs.keys()) != set(node.output_ports):
                raise GraphExecutionError(
                    f"Node '{node_id}' output ports {node.output_ports} do not match produced {list(outputs.keys())}"
                )

            end_time = time.perf_counter()
            duration_ms = (end_time - start_time) * 1000

            return NodeExecutionResult(
                node_id=node_id,
                node_type=node.type,
                status=NodeStatus.COMPLETED,
                outputs=outputs,
                logs=ctx.logger,
                start_time=start_time,
                end_time=end_time,
                duration_ms=duration_ms,
                level=level,
                from_cache=False,
            )

        except Exception as e:
            end_time = time.perf_counter()
            return NodeExecutionResult(
                node_id=node_id,
                node_type=node.type,
                status=NodeStatus.ERROR,
                start_time=start_time,
                end_time=end_time,
                duration_ms=(end_time - start_time) * 1000,
                error=str(e),
                error_code=getattr(e, "code", None),
                level=level,
                from_cache=False,
            )

    def _execute_node_sync(self, node_id: str, inputs: Dict[str, Any], allow_cache: bool = True) -> NodeExecutionResult:
        node_start = time.perf_counter()
        cached_outputs = self._try_get_cached(node_id, inputs) if allow_cache else None
        if cached_outputs is not None:
            end_time = time.perf_counter()
            result = NodeExecutionResult(
                node_id=node_id,
                node_type=self.nodes[node_id].type,
                status=NodeStatus.COMPLETED,
                outputs=cached_outputs,
                logs=[f"[CACHED] Skipped execution, using cached result"],
                start_time=node_start,
                end_time=end_time,
                duration_ms=(end_time - node_start) * 1000,
                level=self._node_levels.get(node_id, 0),
                from_cache=True,
            )
            self._finalize_node_result(node_id, inputs, result, cached=True, allow_cache=allow_cache)
            return result
        result = self._execute_node_work(node_id, inputs)
        self._finalize_node_result(node_id, inputs, result, cached=False, allow_cache=allow_cache)
        return result

    def _execute_loop_sync(
        self,
        loop_id: str,
        executed_count: int,
        max_steps: Optional[int],
        breakpoints: Set[str],
    ) -> int:
        loop_node = self.nodes[loop_id]
        loop_start = time.perf_counter()
        body_nodes = self._loop_body_nodes.get(loop_id, set())
        body_order = [node_id for node_id in self._topo_order if node_id in body_nodes]
        iterations = 0
        last_index = 0

        def _should_stop() -> bool:
            return (
                self._should_stop_execution()
                or (max_steps is not None and executed_count >= max_steps)
            )
        interrupted = False

        if loop_node.type == "core.control.for":
            inputs = self._prepare_inputs(loop_id)
            first_index = int(inputs.get("first_index") or 0)
            last_index_input = int(inputs.get("last_index") or 0)
            step = 1 if last_index_input >= first_index else -1
            indices = range(first_index, last_index_input + step, step)
        elif loop_node.type == "core.control.repeat":
            inputs = self._prepare_inputs(loop_id)
            count = int(inputs.get("count") or 0)
            indices = range(max(0, count))
        else:
            indices = range(0)

        if loop_node.type == "core.control.while":
            inputs = self._prepare_inputs(loop_id)
            max_iterations_value = inputs.get("max_iterations")
            if max_iterations_value is None:
                max_iterations_value = loop_node.params.get("max_iterations", 100)
            max_iterations = int(max_iterations_value)
            indices = range(max_iterations)

        for idx in indices:
            if self._should_interrupt(loop_id) or self._should_stop_execution():
                interrupted = True
                break
            if _should_stop():
                break
            if loop_id in breakpoints:
                break

            if loop_node.type == "core.control.while":
                inputs = self._prepare_inputs(loop_id)
                if not bool(inputs.get("condition")):
                    break

            self._computed_values[loop_id] = {"loop_body": None, "index": idx, "completed": None}
            last_index = idx
            iterations += 1

            for node_id in body_order:
                if self._should_interrupt(loop_id) or self._should_stop_execution():
                    interrupted = True
                    break
                if _should_stop():
                    break
                if node_id in breakpoints:
                    return executed_count
                if self._should_interrupt(node_id):
                    self._record_interrupted(node_id)
                    executed_count += 1
                    continue
                if node_id in self._skipped_branches:
                    self._record_interrupted(node_id)
                    executed_count += 1
                    continue
                if self._is_loop_node(node_id):
                    executed_count = self._execute_loop_sync(node_id, executed_count, max_steps, breakpoints)
                    continue
                if self._is_ifelse_node(node_id):
                    try:
                        inputs = self._prepare_inputs(node_id)
                    except GraphExecutionError as exc:
                        result = self._make_input_error_result(node_id, exc)
                        self._finalize_node_result(node_id, {}, result, cached=False)
                        executed_count += 1
                        if self._fail_fast:
                            interrupted = True
                            break
                        continue

                    true_nodes = self._ifelse_true_branch.get(node_id, set())
                    false_nodes = self._ifelse_false_branch.get(node_id, set())
                    self._skipped_branches -= true_nodes
                    self._skipped_branches -= false_nodes

                    condition = bool(inputs.get("condition", False))
                    if condition:
                        self._skipped_branches.update(false_nodes)
                    else:
                        self._skipped_branches.update(true_nodes)

                    ifelse_outputs = {"true": None, "false": None}
                    result = NodeExecutionResult(
                        node_id=node_id,
                        node_type=self.nodes[node_id].type,
                        status=NodeStatus.COMPLETED,
                        outputs=ifelse_outputs,
                        logs=[f"[loop {idx}] Condition evaluated to {condition}"],
                        duration_ms=0.0,
                        level=self._node_levels.get(node_id, 0),
                        from_cache=False,
                    )
                    self._finalize_node_result(node_id, inputs, result, cached=False)
                    executed_count += 1
                    continue
                inputs = self._prepare_inputs(node_id)
                result = self._execute_node_sync(node_id, inputs, allow_cache=False)
                executed_count += 1
                if result.status == NodeStatus.ERROR:
                    break

        if interrupted:
            self._record_interrupted(loop_id)
            executed_count += 1
            return executed_count

        outputs = {"loop_body": None, "index": last_index, "completed": None}
        loop_end = time.perf_counter()
        result = NodeExecutionResult(
            node_id=loop_id,
            node_type=loop_node.type,
            status=NodeStatus.COMPLETED,
            outputs=outputs,
            logs=[f"Looped {iterations} iterations"],
            start_time=loop_start,
            end_time=loop_end,
            duration_ms=(loop_end - loop_start) * 1000,
            level=self._node_levels.get(loop_id, 0),
            from_cache=False,
        )
        self._finalize_node_result(loop_id, {}, result, cached=False)
        executed_count += 1
        return executed_count

    def _run_internal(self) -> Dict[str, Any]:
        """Execute the graph synchronously (legacy interface)."""
        self._execution_order = self._resolve_execution_order()
        self._reset_execution_state()
        execution_set = set(self._execution_order)
        
        executed_count = 0
        max_steps = self.options.get("max_steps")
        breakpoints: Set[str] = set(self.options.get("breakpoints") or [])
        
        start_time = time.perf_counter()

        for node_id in self._execution_order:
            if self._node_status.get(node_id) != NodeStatus.PENDING:
                continue
            if self._should_interrupt(node_id):
                self._record_interrupted(node_id)
                executed_count += 1
                executed_count += len(
                    self._record_skipped_dependents(
                        node_id,
                        f"Dependency '{node_id}' was interrupted",
                        execution_set=execution_set,
                    )
                )
                continue
            if max_steps is not None and executed_count >= max_steps:
                break
            if node_id in breakpoints:
                break
            if node_id in self._skipped_branches:
                self._record_interrupted(node_id)
                executed_count += 1
                continue

            if self._is_ifelse_node(node_id):
                try:
                    inputs = self._prepare_inputs(node_id)
                except GraphExecutionError as exc:
                    result = self._make_input_error_result(node_id, exc)
                    self._finalize_node_result(node_id, {}, result, cached=False)
                    executed_count += 1
                    if self._fail_fast:
                        break
                    continue
                true_nodes = self._ifelse_true_branch.get(node_id, set())
                false_nodes = self._ifelse_false_branch.get(node_id, set())
                self._skipped_branches -= true_nodes
                self._skipped_branches -= false_nodes

                condition = bool(inputs.get("condition", False))
                if condition:
                    self._skipped_branches.update(false_nodes)
                else:
                    self._skipped_branches.update(true_nodes)

                ifelse_outputs = {"true": None, "false": None}
                result = NodeExecutionResult(
                    node_id=node_id,
                    node_type=self.nodes[node_id].type,
                    status=NodeStatus.COMPLETED,
                    outputs=ifelse_outputs,
                    logs=[f"Condition evaluated to {condition}"],
                    duration_ms=0.0,
                    level=self._node_levels.get(node_id, 0),
                    from_cache=False,
                )
                self._finalize_node_result(node_id, inputs, result, cached=False)
                executed_count += 1
                continue

            if self._is_loop_node(node_id):
                executed_count = self._execute_loop_sync(node_id, executed_count, max_steps, breakpoints)
                continue

            inputs = self._prepare_inputs(node_id)
            result = self._execute_node_sync(node_id, inputs, allow_cache=True)
            executed_count += 1
            
            if result.status == NodeStatus.ERROR:
                break

        total_time = (time.perf_counter() - start_time) * 1000
        
        self.outputs = self._collect_outputs()
        
        legacy_trace = [
            {
                "node_id": r.node_id,
                "type": r.node_type,
                "outputs": r.outputs,
                "logs": r.logs,
                "duration_ms": r.duration_ms,
                "level": r.level,
                "from_cache": r.from_cache,
            }
            for r in self.execution_trace
        ]
        
        stats = self._calculate_stats(total_time)
        
        return {
            "outputs": self.outputs,
            "trace": legacy_trace,
            "stats": stats.__dict__,
            "levels": self._levels,
            "execution_id": self.execution_id,
        }

    def run(self) -> Dict[str, Any]:
        """Execute the graph synchronously (legacy interface)."""
        try:
            return self._run_internal()
        finally:
            self._cleanup_resources()

    async def _run_streaming_sequential(self) -> AsyncIterator[ExecutionEvent]:
        self._execution_order = self._resolve_execution_order()
        self._reset_execution_state()
        self._register_execution(self)
        loop = asyncio.get_running_loop()
        self._thread_pool = ThreadPoolExecutor(max_workers=self._max_workers)
        execution_set = set(self._execution_order)
        max_steps = self.options.get("max_steps")
        breakpoints: Set[str] = set(self.options.get("breakpoints") or [])
        executed_count = 0
        start_time = time.perf_counter()

        total_nodes = len(self._execution_order)
        completed_nodes = 0
        execution_plan = [
            {
                "node_id": node_id,
                "node_type": self.nodes[node_id].type,
                "level": self._node_levels.get(node_id, 0),
            }
            for node_id in self._execution_order
        ]

        try:
            yield ExecutionEvent(
                event_type="start",
                execution_id=self.execution_id,
                timestamp=time.time(),
                total_nodes=total_nodes,
                execution_plan=execution_plan,
                levels=self._levels,
            )

            for node_id in self._execution_order:
                if self._node_status.get(node_id) != NodeStatus.PENDING:
                    continue
                if max_steps is not None and executed_count >= max_steps:
                    break
                if node_id in breakpoints:
                    break
                if self._should_interrupt(node_id):
                    skipped = self._record_interrupted(node_id)
                    completed_nodes += 1
                    executed_count += 1
                    yield ExecutionEvent(
                        event_type="node_skipped",
                        execution_id=self.execution_id,
                        timestamp=time.time(),
                        node_id=node_id,
                        node_type=skipped.node_type,
                        status=NodeStatus.SKIPPED,
                        level=skipped.level,
                        progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                        total_nodes=total_nodes,
                        completed_nodes=completed_nodes,
                    )
                    for dep in self._record_skipped_dependents(
                        node_id,
                        f"Dependency '{node_id}' was interrupted",
                        execution_set=execution_set,
                    ):
                        completed_nodes += 1
                        executed_count += 1
                        yield ExecutionEvent(
                            event_type="node_skipped",
                            execution_id=self.execution_id,
                            timestamp=time.time(),
                            node_id=dep.node_id,
                            node_type=dep.node_type,
                            status=NodeStatus.SKIPPED,
                            logs=dep.logs,
                            level=dep.level,
                            progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                            total_nodes=total_nodes,
                            completed_nodes=completed_nodes,
                        )
                    continue

                # Skip nodes in inactive If/Else branches
                if node_id in self._skipped_branches:
                    skipped = self._record_interrupted(node_id)
                    completed_nodes += 1
                    executed_count += 1
                    yield ExecutionEvent(
                        event_type="node_skipped",
                        execution_id=self.execution_id,
                        timestamp=time.time(),
                        node_id=node_id,
                        node_type=skipped.node_type,
                        status=NodeStatus.SKIPPED,
                        logs=["Skipped: If/Else condition was False"],
                        level=skipped.level,
                        progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                        total_nodes=total_nodes,
                        completed_nodes=completed_nodes,
                    )
                    continue
                
                if self._is_loop_node(node_id):
                    loop_node = self.nodes[node_id]
                    body_nodes = self._loop_body_nodes.get(node_id, set())
                    body_order = [nid for nid in self._topo_order if nid in body_nodes]

                    yield ExecutionEvent(
                        event_type="node_started",
                        execution_id=self.execution_id,
                        timestamp=time.time(),
                        node_id=node_id,
                        node_type=loop_node.type,
                        status=NodeStatus.RUNNING,
                        level=self._node_levels.get(node_id, 0),
                        progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                        total_nodes=total_nodes,
                        completed_nodes=completed_nodes,
                    )

                    iterations = 0
                    last_index = 0

                    if loop_node.type == "core.control.for":
                        inputs = self._prepare_inputs(node_id)
                        first_index = int(inputs.get("first_index") or 0)
                        last_index_input = int(inputs.get("last_index") or 0)
                        step = 1 if last_index_input >= first_index else -1
                        indices = range(first_index, last_index_input + step, step)
                        total_nodes += len(indices) * len(body_order)
                    elif loop_node.type == "core.control.repeat":
                        inputs = self._prepare_inputs(node_id)
                        count = int(inputs.get("count") or 0)
                        indices = range(max(0, count))
                        total_nodes += len(indices) * len(body_order)
                    else:
                        inputs = self._prepare_inputs(node_id)
                        max_iterations_value = inputs.get("max_iterations")
                        if max_iterations_value is None:
                            max_iterations_value = loop_node.params.get("max_iterations", 100)
                        max_iterations = int(max_iterations_value)
                        indices = range(max_iterations)
                        total_nodes += len(indices) * len(body_order)

                    loop_interrupted = False
                    for idx in indices:
                        if self._should_interrupt(node_id):
                            loop_interrupted = True
                            break
                        if self._should_stop_execution():
                            break
                        if loop_node.type == "core.control.while":
                            inputs = self._prepare_inputs(node_id)
                            if not bool(inputs.get("condition")):
                                break
                        self._computed_values[node_id] = {"loop_body": None, "index": idx, "completed": None}
                        last_index = idx
                        iterations += 1

                        for body_id in body_order:
                            if self._should_interrupt(node_id):
                                loop_interrupted = True
                                break
                            if self._should_stop_execution():
                                break
                            if self._should_interrupt(body_id):
                                skipped = self._record_interrupted(body_id)
                                completed_nodes += 1
                                executed_count += 1
                                yield ExecutionEvent(
                                    event_type="node_skipped",
                                    execution_id=self.execution_id,
                                    timestamp=time.time(),
                                    node_id=body_id,
                                    node_type=skipped.node_type,
                                    status=NodeStatus.SKIPPED,
                                    level=skipped.level,
                                    progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                                    total_nodes=total_nodes,
                                    completed_nodes=completed_nodes,
                                )
                                continue

                            # Skip nodes in inactive If/Else branches
                            if body_id in self._skipped_branches:
                                skipped = self._record_interrupted(body_id)
                                completed_nodes += 1
                                executed_count += 1
                                yield ExecutionEvent(
                                    event_type="node_skipped",
                                    execution_id=self.execution_id,
                                    timestamp=time.time(),
                                    node_id=body_id,
                                    node_type=skipped.node_type,
                                    status=NodeStatus.SKIPPED,
                                    logs=["Skipped: If/Else condition was False"],
                                    level=skipped.level,
                                    progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                                    total_nodes=total_nodes,
                                    completed_nodes=completed_nodes,
                                )
                                continue

                            if self._is_loop_node(body_id):
                                executed_count = self._execute_loop_sync(body_id, executed_count, max_steps, breakpoints)
                                completed_nodes += 1
                                continue

                            # Handle If/Else nodes in loop body
                            if self._is_ifelse_node(body_id):
                                yield ExecutionEvent(
                                    event_type="node_started",
                                    execution_id=self.execution_id,
                                    timestamp=time.time(),
                                    node_id=body_id,
                                    node_type=self.nodes[body_id].type,
                                    status=NodeStatus.RUNNING,
                                    level=self._node_levels.get(body_id, 0),
                                    progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                                    total_nodes=total_nodes,
                                    completed_nodes=completed_nodes,
                                )
                                
                                try:
                                    inputs = self._prepare_inputs(body_id)
                                except GraphExecutionError as exc:
                                    result = self._make_input_error_result(body_id, exc)
                                    self._finalize_node_result(body_id, {}, result, cached=False)
                                    completed_nodes += 1
                                    yield ExecutionEvent(
                                        event_type="node_error",
                                        execution_id=self.execution_id,
                                        timestamp=time.time(),
                                        node_id=body_id,
                                        node_type=result.node_type,
                                        status=NodeStatus.ERROR,
                                        error=result.error,
                                        error_code=result.error_code,
                                        duration_ms=result.duration_ms,
                                        level=result.level,
                                        progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                                        total_nodes=total_nodes,
                                        completed_nodes=completed_nodes,
                                        from_cache=result.from_cache,
                                    )
                                    if self._fail_fast:
                                        loop_interrupted = True
                                        break
                                    continue
                                
                                # Evaluate condition and mark inactive branch
                                true_nodes = self._ifelse_true_branch.get(body_id, set())
                                false_nodes = self._ifelse_false_branch.get(body_id, set())
                                self._skipped_branches -= true_nodes
                                self._skipped_branches -= false_nodes
                                
                                condition = bool(inputs.get("condition", False))
                                if condition:
                                    self._skipped_branches.update(false_nodes)
                                else:
                                    self._skipped_branches.update(true_nodes)
                                
                                ifelse_outputs = {"true": None, "false": None}
                                result = NodeExecutionResult(
                                    node_id=body_id,
                                    node_type=self.nodes[body_id].type,
                                    status=NodeStatus.COMPLETED,
                                    outputs=ifelse_outputs,
                                    logs=[f"[loop {idx}] Condition evaluated to {condition}"],
                                    duration_ms=0.0,
                                    level=self._node_levels.get(body_id, 0),
                                    from_cache=False,
                                )
                                self._finalize_node_result(body_id, inputs, result, cached=False)
                                completed_nodes += 1
                                executed_count += 1
                                yield ExecutionEvent(
                                    event_type="node_completed",
                                    execution_id=self.execution_id,
                                    timestamp=time.time(),
                                    node_id=body_id,
                                    node_type=self.nodes[body_id].type,
                                    status=NodeStatus.COMPLETED,
                                    outputs=ifelse_outputs,
                                    logs=result.logs,
                                    duration_ms=result.duration_ms,
                                    level=result.level,
                                    progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                                    total_nodes=total_nodes,
                                    completed_nodes=completed_nodes,
                                    from_cache=False,
                                )
                                continue

                            yield ExecutionEvent(
                                event_type="node_started",
                                execution_id=self.execution_id,
                                timestamp=time.time(),
                                node_id=body_id,
                                node_type=self.nodes[body_id].type,
                                status=NodeStatus.RUNNING,
                                level=self._node_levels.get(body_id, 0),
                                progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                                total_nodes=total_nodes,
                                completed_nodes=completed_nodes,
                            )
                            try:
                                inputs = self._prepare_inputs(body_id)
                            except GraphExecutionError as exc:
                                result = self._make_input_error_result(body_id, exc)
                                self._finalize_node_result(body_id, {}, result, cached=False)
                                completed_nodes += 1
                                yield ExecutionEvent(
                                    event_type="node_error",
                                    execution_id=self.execution_id,
                                    timestamp=time.time(),
                                    node_id=body_id,
                                    node_type=result.node_type,
                                    status=NodeStatus.ERROR,
                                    error=result.error,
                                    error_code=result.error_code,
                                    duration_ms=result.duration_ms,
                                    level=result.level,
                                    progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                                    total_nodes=total_nodes,
                                    completed_nodes=completed_nodes,
                                    from_cache=result.from_cache,
                                )
                                if self._fail_fast:
                                    loop_interrupted = True
                                    break
                                continue

                            future = loop.run_in_executor(self._thread_pool, self._execute_node_work, body_id, inputs)
                            task = asyncio.wrap_future(future)
                            self._cancellation.register_running(body_id, task)
                            try:
                                result = await task
                            except asyncio.CancelledError:
                                result = self._make_interrupted_result(body_id)
                            result.logs = [f"[loop {idx}] {log}" for log in result.logs] or [f"[loop {idx}]"]
                            self._finalize_node_result(body_id, inputs, result, cached=False)
                            completed_nodes += 1
                            executed_count += 1

                            if result.status == NodeStatus.ERROR:
                                yield ExecutionEvent(
                                    event_type="node_error",
                                    execution_id=self.execution_id,
                                    timestamp=time.time(),
                                    node_id=result.node_id,
                                    node_type=result.node_type,
                                    status=NodeStatus.ERROR,
                                    error=result.error,
                                    error_code=result.error_code,
                                    duration_ms=result.duration_ms,
                                    level=result.level,
                                    progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                                    total_nodes=total_nodes,
                                    completed_nodes=completed_nodes,
                                    from_cache=result.from_cache,
                                )
                                if self._fail_fast:
                                    break
                            else:
                                event_type = "node_completed" if result.status == NodeStatus.COMPLETED else "node_skipped"
                                yield ExecutionEvent(
                                    event_type=event_type,
                                    execution_id=self.execution_id,
                                    timestamp=time.time(),
                                    node_id=result.node_id,
                                    node_type=result.node_type,
                                    status=result.status,
                                    outputs=result.outputs,
                                    logs=result.logs,
                                    duration_ms=result.duration_ms,
                                    level=result.level,
                                    progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                                    total_nodes=total_nodes,
                                    completed_nodes=completed_nodes,
                                    from_cache=result.from_cache,
                                )

                    if loop_interrupted or self._should_stop_execution():
                        loop_result = self._record_interrupted(node_id)
                        completed_nodes += 1
                        executed_count += 1
                        yield ExecutionEvent(
                            event_type="node_skipped",
                            execution_id=self.execution_id,
                            timestamp=time.time(),
                            node_id=node_id,
                            node_type=loop_node.type,
                            status=NodeStatus.SKIPPED,
                            logs=loop_result.logs,
                            duration_ms=loop_result.duration_ms,
                            level=loop_result.level,
                            progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                            total_nodes=total_nodes,
                            completed_nodes=completed_nodes,
                            from_cache=False,
                        )
                    else:
                        loop_outputs = {"loop_body": None, "index": last_index, "completed": None}
                        loop_result = NodeExecutionResult(
                            node_id=node_id,
                            node_type=loop_node.type,
                            status=NodeStatus.COMPLETED,
                            outputs=loop_outputs,
                            logs=[f"Looped {iterations} iterations"],
                            duration_ms=0.0,
                            level=self._node_levels.get(node_id, 0),
                            from_cache=False,
                        )
                        self._finalize_node_result(node_id, {}, loop_result, cached=False)
                        completed_nodes += 1
                        executed_count += 1
                        yield ExecutionEvent(
                            event_type="node_completed",
                            execution_id=self.execution_id,
                            timestamp=time.time(),
                            node_id=node_id,
                            node_type=loop_node.type,
                            status=NodeStatus.COMPLETED,
                            outputs=loop_outputs,
                            logs=loop_result.logs,
                            duration_ms=loop_result.duration_ms,
                            level=loop_result.level,
                            progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                            total_nodes=total_nodes,
                            completed_nodes=completed_nodes,
                            from_cache=False,
                        )
                    continue

                # Handle If/Else nodes specially - execute and mark inactive branch
                if self._is_ifelse_node(node_id):
                    yield ExecutionEvent(
                        event_type="node_started",
                        execution_id=self.execution_id,
                        timestamp=time.time(),
                        node_id=node_id,
                        node_type=self.nodes[node_id].type,
                        status=NodeStatus.RUNNING,
                        level=self._node_levels.get(node_id, 0),
                        progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                        total_nodes=total_nodes,
                        completed_nodes=completed_nodes,
                    )
                    
                    try:
                        inputs = self._prepare_inputs(node_id)
                    except GraphExecutionError as exc:
                        result = self._make_input_error_result(node_id, exc)
                        self._finalize_node_result(node_id, {}, result, cached=False)
                        completed_nodes += 1
                        yield ExecutionEvent(
                            event_type="node_error",
                            execution_id=self.execution_id,
                            timestamp=time.time(),
                            node_id=node_id,
                            node_type=result.node_type,
                            status=NodeStatus.ERROR,
                            error=result.error,
                            error_code=result.error_code,
                            duration_ms=result.duration_ms,
                            level=result.level,
                            progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                            total_nodes=total_nodes,
                            completed_nodes=completed_nodes,
                            from_cache=result.from_cache,
                        )
                        if self._fail_fast:
                            break
                        continue
                    
                    # Evaluate the condition and mark inactive branch as skipped
                    # Clear any previous skip state for this If/Else (important for loops)
                    true_nodes = self._ifelse_true_branch.get(node_id, set())
                    false_nodes = self._ifelse_false_branch.get(node_id, set())
                    self._skipped_branches -= true_nodes
                    self._skipped_branches -= false_nodes
                    
                    condition = bool(inputs.get("condition", False))
                    if condition:
                        # Condition is True: skip the false branch
                        self._skipped_branches.update(false_nodes)
                    else:
                        # Condition is False: skip the true branch
                        self._skipped_branches.update(true_nodes)
                    
                    # Execute the If/Else node to record it
                    ifelse_outputs = {"true": None, "false": None}
                    result = NodeExecutionResult(
                        node_id=node_id,
                        node_type=self.nodes[node_id].type,
                        status=NodeStatus.COMPLETED,
                        outputs=ifelse_outputs,
                        logs=[f"Condition evaluated to {condition}"],
                        duration_ms=0.0,
                        level=self._node_levels.get(node_id, 0),
                        from_cache=False,
                    )
                    self._finalize_node_result(node_id, inputs, result, cached=False)
                    completed_nodes += 1
                    executed_count += 1
                    yield ExecutionEvent(
                        event_type="node_completed",
                        execution_id=self.execution_id,
                        timestamp=time.time(),
                        node_id=node_id,
                        node_type=self.nodes[node_id].type,
                        status=NodeStatus.COMPLETED,
                        outputs=ifelse_outputs,
                        logs=result.logs,
                        duration_ms=result.duration_ms,
                        level=result.level,
                        progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                        total_nodes=total_nodes,
                        completed_nodes=completed_nodes,
                        from_cache=False,
                    )
                    continue

                yield ExecutionEvent(
                    event_type="node_started",
                    execution_id=self.execution_id,
                    timestamp=time.time(),
                    node_id=node_id,
                    node_type=self.nodes[node_id].type,
                    status=NodeStatus.RUNNING,
                    level=self._node_levels.get(node_id, 0),
                    progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                    total_nodes=total_nodes,
                    completed_nodes=completed_nodes,
                )
                try:
                    inputs = self._prepare_inputs(node_id)
                except GraphExecutionError as exc:
                    result = self._make_input_error_result(node_id, exc)
                    self._finalize_node_result(node_id, {}, result, cached=False)
                    completed_nodes += 1
                    executed_count += 1
                    yield ExecutionEvent(
                        event_type="node_error",
                        execution_id=self.execution_id,
                        timestamp=time.time(),
                        node_id=node_id,
                        node_type=result.node_type,
                        status=NodeStatus.ERROR,
                        error=result.error,
                        error_code=result.error_code,
                        duration_ms=result.duration_ms,
                        level=result.level,
                        progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                        total_nodes=total_nodes,
                        completed_nodes=completed_nodes,
                        from_cache=result.from_cache,
                    )
                    if self._fail_fast:
                        break
                    continue

                cached_outputs = self._try_get_cached(node_id, inputs)

                if cached_outputs is not None:
                    cached_start = time.perf_counter()
                    result = NodeExecutionResult(
                        node_id=node_id,
                        node_type=self.nodes[node_id].type,
                        status=NodeStatus.COMPLETED,
                        outputs=cached_outputs,
                        logs=[f"[CACHED] Skipped execution, using cached result"],
                        start_time=cached_start,
                        end_time=cached_start,
                        duration_ms=0.0,
                        level=self._node_levels.get(node_id, 0),
                        from_cache=True,
                    )
                    self._finalize_node_result(node_id, inputs, result, cached=True)
                    completed_nodes += 1
                    executed_count += 1
                    yield ExecutionEvent(
                        event_type="node_cached",
                        execution_id=self.execution_id,
                        timestamp=time.time(),
                        node_id=result.node_id,
                        node_type=result.node_type,
                        status=result.status,
                        outputs=result.outputs,
                        logs=result.logs,
                        duration_ms=result.duration_ms,
                        level=result.level,
                        progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                        total_nodes=total_nodes,
                        completed_nodes=completed_nodes,
                        from_cache=result.from_cache,
                    )
                    continue

                future = loop.run_in_executor(self._thread_pool, self._execute_node_work, node_id, inputs)
                task = asyncio.wrap_future(future)
                self._cancellation.register_running(node_id, task)
                try:
                    result = await task
                except asyncio.CancelledError:
                    result = self._make_interrupted_result(node_id)
                self._finalize_node_result(node_id, inputs, result, cached=False)
                completed_nodes += 1
                executed_count += 1

                if result.status == NodeStatus.ERROR:
                    yield ExecutionEvent(
                        event_type="node_error",
                        execution_id=self.execution_id,
                        timestamp=time.time(),
                        node_id=result.node_id,
                        node_type=result.node_type,
                        status=NodeStatus.ERROR,
                        error=result.error,
                        error_code=result.error_code,
                        duration_ms=result.duration_ms,
                        level=result.level,
                        progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                        total_nodes=total_nodes,
                        completed_nodes=completed_nodes,
                        from_cache=result.from_cache,
                    )
                    if self._fail_fast:
                        break
                else:
                    event_type = "node_completed" if result.status == NodeStatus.COMPLETED else "node_skipped"
                    yield ExecutionEvent(
                        event_type=event_type,
                        execution_id=self.execution_id,
                        timestamp=time.time(),
                        node_id=result.node_id,
                        node_type=result.node_type,
                        status=result.status,
                        outputs=result.outputs,
                        logs=result.logs,
                        duration_ms=result.duration_ms,
                        level=result.level,
                        progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                        total_nodes=total_nodes,
                        completed_nodes=completed_nodes,
                        from_cache=result.from_cache,
                    )
                    if result.status == NodeStatus.SKIPPED:
                        for dep in self._record_skipped_dependents(
                            node_id,
                            f"Dependency '{node_id}' was interrupted",
                            execution_set=execution_set,
                        ):
                            completed_nodes += 1
                            executed_count += 1
                            yield ExecutionEvent(
                                event_type="node_skipped",
                                execution_id=self.execution_id,
                                timestamp=time.time(),
                                node_id=dep.node_id,
                                node_type=dep.node_type,
                                status=NodeStatus.SKIPPED,
                                logs=dep.logs,
                                level=dep.level,
                                progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                                total_nodes=total_nodes,
                                completed_nodes=completed_nodes,
                            )

            total_time = (time.perf_counter() - start_time) * 1000
            self._total_execution_time_ms = total_time
            self._max_parallelism = 1 if executed_count > 0 else 0
            self.outputs = self._collect_outputs()
            yield ExecutionEvent(
                event_type="complete",
                execution_id=self.execution_id,
                timestamp=time.time(),
                progress=1.0,
                total_nodes=total_nodes,
                completed_nodes=completed_nodes,
            )
        finally:
            if self._thread_pool:
                self._thread_pool.shutdown(wait=False)
                self._thread_pool = None
            self._cleanup_resources()
            self._unregister_execution(self.execution_id)

    async def _execute_branch_streaming(
        self,
        branch_id: str,
        branch_nodes: Set[str],
        event_queue: asyncio.Queue,
        progress_state: Dict[str, Any],
    ) -> None:
        """Execute a single branch sequentially, pushing events to the shared queue.
        
        This handles loops within the branch while allowing other branches to run in parallel.
        """
        # Get execution order for just this branch's nodes
        branch_order = [nid for nid in self._topo_order if nid in branch_nodes]
        
        for node_id in branch_order:
            if self._should_interrupt(node_id):
                skipped = self._record_interrupted(node_id)
                with progress_state["lock"]:
                    progress_state["completed"] += 1
                    completed = progress_state["completed"]
                    total = progress_state["total"]
                await event_queue.put(ExecutionEvent(
                    event_type="node_skipped",
                    execution_id=self.execution_id,
                    timestamp=time.time(),
                    node_id=node_id,
                    node_type=skipped.node_type,
                    status=NodeStatus.SKIPPED,
                    level=skipped.level,
                    progress=completed / total if total > 0 else 0,
                    total_nodes=total,
                    completed_nodes=completed,
                ))
                continue

            if self._is_loop_node(node_id):
                # Execute loop inline (sequentially within this branch)
                async for event in self._execute_loop_streaming(node_id, event_queue, progress_state):
                    await event_queue.put(event)
                continue

            # Regular node execution
            node = self.nodes[node_id]
            with progress_state["lock"]:
                total = progress_state["total"]
                completed = progress_state["completed"]
            
            await event_queue.put(ExecutionEvent(
                event_type="node_started",
                execution_id=self.execution_id,
                timestamp=time.time(),
                node_id=node_id,
                node_type=node.type,
                status=NodeStatus.RUNNING,
                level=self._node_levels.get(node_id, 0),
                progress=completed / total if total > 0 else 0,
                total_nodes=total,
                completed_nodes=completed,
            ))

            try:
                inputs = self._prepare_inputs(node_id)
            except GraphExecutionError as exc:
                result = self._make_input_error_result(node_id, exc)
                self._finalize_node_result(node_id, {}, result, cached=False)
                with progress_state["lock"]:
                    progress_state["completed"] += 1
                    completed = progress_state["completed"]
                    total = progress_state["total"]
                await event_queue.put(ExecutionEvent(
                    event_type="node_error",
                    execution_id=self.execution_id,
                    timestamp=time.time(),
                    node_id=node_id,
                    node_type=result.node_type,
                    status=NodeStatus.ERROR,
                    error=result.error,
                    error_code=result.error_code,
                    duration_ms=result.duration_ms,
                    level=result.level,
                    progress=completed / total if total > 0 else 0,
                    total_nodes=total,
                    completed_nodes=completed,
                    from_cache=result.from_cache,
                ))
                if self._fail_fast:
                    break
                continue
            
            # Execute in thread pool to avoid blocking
            loop = asyncio.get_running_loop()
            future = loop.run_in_executor(
                self._thread_pool,
                self._execute_node_work,
                node_id,
                inputs
            )
            task = asyncio.wrap_future(future)
            self._cancellation.register_running(node_id, task)
            try:
                result = await task
            except asyncio.CancelledError:
                result = self._make_interrupted_result(node_id)
            self._finalize_node_result(node_id, inputs, result, cached=False)
            
            with progress_state["lock"]:
                progress_state["completed"] += 1
                completed = progress_state["completed"]
                total = progress_state["total"]

            if result.status == NodeStatus.ERROR:
                await event_queue.put(ExecutionEvent(
                    event_type="node_error",
                    execution_id=self.execution_id,
                    timestamp=time.time(),
                    node_id=result.node_id,
                    node_type=result.node_type,
                    status=NodeStatus.ERROR,
                    error=result.error,
                    error_code=result.error_code,
                    duration_ms=result.duration_ms,
                    level=result.level,
                    progress=completed / total if total > 0 else 0,
                    total_nodes=total,
                    completed_nodes=completed,
                    from_cache=result.from_cache,
                ))
                if self._fail_fast:
                    break
            else:
                event_type = "node_completed" if result.status == NodeStatus.COMPLETED else "node_skipped"
                await event_queue.put(ExecutionEvent(
                    event_type=event_type,
                    execution_id=self.execution_id,
                    timestamp=time.time(),
                    node_id=result.node_id,
                    node_type=result.node_type,
                    status=result.status,
                    outputs=result.outputs,
                    logs=result.logs,
                    duration_ms=result.duration_ms,
                    level=result.level,
                    progress=completed / total if total > 0 else 0,
                    total_nodes=total,
                    completed_nodes=completed,
                    from_cache=result.from_cache,
                ))

    async def _execute_loop_streaming(
        self,
        node_id: str,
        event_queue: asyncio.Queue,
        progress_state: Dict[str, Any],
    ) -> AsyncIterator[ExecutionEvent]:
        """Execute a loop node, yielding events for each iteration."""
        loop_node = self.nodes[node_id]
        body_nodes = self._loop_body_nodes.get(node_id, set())
        body_order = [nid for nid in self._topo_order if nid in body_nodes]

        with progress_state["lock"]:
            total = progress_state["total"]
            completed = progress_state["completed"]

        yield ExecutionEvent(
            event_type="node_started",
            execution_id=self.execution_id,
            timestamp=time.time(),
            node_id=node_id,
            node_type=loop_node.type,
            status=NodeStatus.RUNNING,
            level=self._node_levels.get(node_id, 0),
            progress=completed / total if total > 0 else 0,
            total_nodes=total,
            completed_nodes=completed,
        )

        iterations = 0
        last_index = 0

        if loop_node.type == "core.control.for":
            inputs = self._prepare_inputs(node_id)
            first_index = int(inputs.get("first_index") or 0)
            last_index_input = int(inputs.get("last_index") or 0)
            step = 1 if last_index_input >= first_index else -1
            indices = range(first_index, last_index_input + step, step)
        elif loop_node.type == "core.control.repeat":
            inputs = self._prepare_inputs(node_id)
            count = int(inputs.get("count") or 0)
            indices = range(max(0, count))
        else:
            inputs = self._prepare_inputs(node_id)
            max_iterations_value = inputs.get("max_iterations")
            if max_iterations_value is None:
                max_iterations_value = loop_node.params.get("max_iterations", 100)
            max_iterations = int(max_iterations_value)
            indices = range(max_iterations)

        loop = asyncio.get_running_loop()

        loop_interrupted = False
        for idx in indices:
            if self._should_interrupt(node_id):
                loop_interrupted = True
                break
            if self._should_stop_execution():
                break
            if loop_node.type == "core.control.while":
                inputs = self._prepare_inputs(node_id)
                if not bool(inputs.get("condition")):
                    break
            self._computed_values[node_id] = {"loop_body": None, "index": idx, "completed": None}
            last_index = idx
            iterations += 1

            for body_id in body_order:
                if self._should_interrupt(node_id):
                    loop_interrupted = True
                    break
                if self._should_stop_execution():
                    break
                if self._should_interrupt(body_id):
                    skipped = self._record_interrupted(body_id)
                    with progress_state["lock"]:
                        progress_state["completed"] += 1
                        completed = progress_state["completed"]
                        total = progress_state["total"]
                    yield ExecutionEvent(
                        event_type="node_skipped",
                        execution_id=self.execution_id,
                        timestamp=time.time(),
                        node_id=body_id,
                        node_type=skipped.node_type,
                        status=NodeStatus.SKIPPED,
                        level=skipped.level,
                        progress=completed / total if total > 0 else 0,
                        total_nodes=total,
                        completed_nodes=completed,
                    )
                    continue

                if self._is_loop_node(body_id):
                    self._execute_loop_sync(body_id, 0, None, set())
                    continue

                with progress_state["lock"]:
                    total = progress_state["total"]
                    completed = progress_state["completed"]

                yield ExecutionEvent(
                    event_type="node_started",
                    execution_id=self.execution_id,
                    timestamp=time.time(),
                    node_id=body_id,
                    node_type=self.nodes[body_id].type,
                    status=NodeStatus.RUNNING,
                    level=self._node_levels.get(body_id, 0),
                    progress=completed / total if total > 0 else 0,
                    total_nodes=total,
                    completed_nodes=completed,
                )

                try:
                    inputs = self._prepare_inputs(body_id)
                except GraphExecutionError as exc:
                    result = self._make_input_error_result(body_id, exc)
                    self._finalize_node_result(body_id, {}, result, cached=False)
                    with progress_state["lock"]:
                        progress_state["completed"] += 1
                        completed = progress_state["completed"]
                        total = progress_state["total"]
                    yield ExecutionEvent(
                        event_type="node_error",
                        execution_id=self.execution_id,
                        timestamp=time.time(),
                        node_id=body_id,
                        node_type=result.node_type,
                        status=NodeStatus.ERROR,
                        error=result.error,
                        error_code=result.error_code,
                        duration_ms=result.duration_ms,
                        level=result.level,
                        progress=completed / total if total > 0 else 0,
                        total_nodes=total,
                        completed_nodes=completed,
                        from_cache=result.from_cache,
                    )
                    if self._fail_fast:
                        loop_interrupted = True
                        break
                    continue
                future = loop.run_in_executor(
                    self._thread_pool,
                    self._execute_node_work,
                    body_id,
                    inputs
                )
                task = asyncio.wrap_future(future)
                self._cancellation.register_running(body_id, task)
                try:
                    result = await task
                except asyncio.CancelledError:
                    result = self._make_interrupted_result(body_id)
                result.logs = [f"[loop {idx}] {log}" for log in result.logs] or [f"[loop {idx}]"]
                self._finalize_node_result(body_id, inputs, result, cached=False)

                with progress_state["lock"]:
                    progress_state["completed"] += 1
                    completed = progress_state["completed"]
                    total = progress_state["total"]

                if result.status == NodeStatus.ERROR:
                    yield ExecutionEvent(
                        event_type="node_error",
                        execution_id=self.execution_id,
                        timestamp=time.time(),
                        node_id=result.node_id,
                        node_type=result.node_type,
                        status=NodeStatus.ERROR,
                        error=result.error,
                        error_code=result.error_code,
                        duration_ms=result.duration_ms,
                        level=result.level,
                        progress=completed / total if total > 0 else 0,
                        total_nodes=total,
                        completed_nodes=completed,
                        from_cache=result.from_cache,
                    )
                    if self._fail_fast:
                        break
                else:
                    event_type = "node_completed" if result.status == NodeStatus.COMPLETED else "node_skipped"
                    yield ExecutionEvent(
                        event_type=event_type,
                        execution_id=self.execution_id,
                        timestamp=time.time(),
                        node_id=result.node_id,
                        node_type=result.node_type,
                        status=result.status,
                        outputs=result.outputs,
                        logs=result.logs,
                        duration_ms=result.duration_ms,
                        level=result.level,
                        progress=completed / total if total > 0 else 0,
                        total_nodes=total,
                        completed_nodes=completed,
                        from_cache=result.from_cache,
                    )

        if loop_interrupted or self._should_stop_execution():
            loop_result = self._record_interrupted(node_id)
            with progress_state["lock"]:
                progress_state["completed"] += 1
                completed = progress_state["completed"]
                total = progress_state["total"]

            yield ExecutionEvent(
                event_type="node_skipped",
                execution_id=self.execution_id,
                timestamp=time.time(),
                node_id=node_id,
                node_type=loop_node.type,
                status=NodeStatus.SKIPPED,
                logs=loop_result.logs,
                duration_ms=loop_result.duration_ms,
                level=loop_result.level,
                progress=completed / total if total > 0 else 0,
                total_nodes=total,
                completed_nodes=completed,
                from_cache=False,
            )
        else:
            loop_outputs = {"loop_body": None, "index": last_index, "completed": None}
            loop_result = NodeExecutionResult(
                node_id=node_id,
                node_type=loop_node.type,
                status=NodeStatus.COMPLETED,
                outputs=loop_outputs,
                logs=[f"Looped {iterations} iterations"],
                duration_ms=0.0,
                level=self._node_levels.get(node_id, 0),
                from_cache=False,
            )
            self._finalize_node_result(node_id, {}, loop_result, cached=False)
            
            with progress_state["lock"]:
                progress_state["completed"] += 1
                completed = progress_state["completed"]
                total = progress_state["total"]

            yield ExecutionEvent(
                event_type="node_completed",
                execution_id=self.execution_id,
                timestamp=time.time(),
                node_id=node_id,
                node_type=loop_node.type,
                status=NodeStatus.COMPLETED,
                outputs=loop_outputs,
                logs=loop_result.logs,
                duration_ms=loop_result.duration_ms,
                level=loop_result.level,
                progress=completed / total if total > 0 else 0,
                total_nodes=total,
                completed_nodes=completed,
                from_cache=False,
            )

    async def _run_parallel_branches(self) -> AsyncIterator[ExecutionEvent]:
        """Execute independent branches in parallel, each running sequentially internally."""
        self._execution_order = self._resolve_execution_order()
        self._reset_execution_state()
        self._register_execution(self)
        self._thread_pool = ThreadPoolExecutor(max_workers=self._max_workers)
        
        total_nodes = len(self._execution_order)
        
        # Build execution plan info
        execution_plan = [
            {
                "node_id": node_id,
                "node_type": self.nodes[node_id].type,
                "level": self._node_levels.get(node_id, 0),
                "branch_id": self._branch_roots.get(node_id),
                "is_merge_point": node_id in self._merge_points,
            }
            for node_id in self._execution_order
        ]
        
        branches_dict = {
            branch_id: list(node_ids) 
            for branch_id, node_ids in self._branches.items()
        } if self._branches else None
        
        yield ExecutionEvent(
            event_type="start",
            execution_id=self.execution_id,
            timestamp=time.time(),
            total_nodes=total_nodes,
            execution_plan=execution_plan,
            levels=self._levels,
            branches=branches_dict,
            merge_points=list(self._merge_points) if self._merge_points else None,
        )
        
        # Shared progress state with lock for thread safety
        progress_state = {
            "total": total_nodes,
            "completed": 0,
            "lock": threading.Lock(),
        }
        
        # Event queue to collect events from all branches
        event_queue: asyncio.Queue = asyncio.Queue()
        
        # Identify independent branches (those from the same Start node)
        parallel_branch_groups: Dict[str, List[str]] = defaultdict(list)
        for branch_id in self._branches:
            # Group by start node
            if "_branch_" in branch_id:
                start_id = branch_id.rsplit("_branch_", 1)[0]
                parallel_branch_groups[start_id].append(branch_id)
            else:
                parallel_branch_groups[branch_id].append(branch_id)
        
        start_time = time.perf_counter()
        
        try:
            # Start all branches as parallel tasks
            branch_tasks = []
            for start_id, branch_ids in parallel_branch_groups.items():
                for branch_id in branch_ids:
                    branch_nodes = self._branches.get(branch_id, set())
                    if branch_nodes:
                        task = asyncio.create_task(
                            self._execute_branch_streaming(
                                branch_id,
                                branch_nodes,
                                event_queue,
                                progress_state,
                            )
                        )
                        branch_tasks.append(task)
            
            # Also handle any dataflow-only nodes (not in any branch)
            all_branch_nodes = set()
            for nodes in self._branches.values():
                all_branch_nodes.update(nodes)
            dataflow_nodes = set(self._execution_order) - all_branch_nodes - self._start_nodes
            
            if dataflow_nodes:
                task = asyncio.create_task(
                    self._execute_branch_streaming(
                        "__dataflow__",
                        dataflow_nodes,
                        event_queue,
                        progress_state,
                    )
                )
                branch_tasks.append(task)
            
            # Sentinel to signal completion
            async def wait_for_branches():
                await asyncio.gather(*branch_tasks, return_exceptions=True)
                await event_queue.put(None)  # Sentinel
            
            asyncio.create_task(wait_for_branches())
            
            # Yield events as they arrive from all branches
            while True:
                event = await event_queue.get()
                if event is None:
                    break
                yield event
            
            # Execute Start nodes (they typically have no inputs)
            for start_id in self._start_nodes:
                if start_id in self._execution_order:
                    with progress_state["lock"]:
                        total = progress_state["total"]
                        completed = progress_state["completed"]
                    
                    inputs = self._prepare_inputs(start_id)
                    start_node = self.nodes[start_id]
                    result = NodeExecutionResult(
                        node_id=start_id,
                        node_type=start_node.type,
                        status=NodeStatus.COMPLETED,
                        outputs={"control_out": None},
                        logs=["Start node triggered"],
                        duration_ms=0.0,
                        level=self._node_levels.get(start_id, 0),
                        from_cache=False,
                    )
                    self._finalize_node_result(start_id, inputs, result, cached=False)
            
            self.outputs = self._collect_outputs()
            
            total_time = (time.perf_counter() - start_time) * 1000
            self._total_execution_time_ms = total_time
            self._max_parallelism = len(branch_tasks)
            
            with progress_state["lock"]:
                completed = progress_state["completed"]
            
            yield ExecutionEvent(
                event_type="complete",
                execution_id=self.execution_id,
                timestamp=time.time(),
                progress=1.0,
                total_nodes=total_nodes,
                completed_nodes=completed,
            )
            
        finally:
            if self._thread_pool:
                self._thread_pool.shutdown(wait=False)
                self._thread_pool = None
            self._cleanup_resources()
            self._unregister_execution(self.execution_id)


    async def run_async(self) -> Dict[str, Any]:
        """Execute the graph asynchronously using the streaming scheduler for consistency."""
        async for _ in self.run_streaming():
            pass

        legacy_trace = [
            {
                "node_id": r.node_id,
                "type": r.node_type,
                "outputs": r.outputs,
                "logs": r.logs,
                "duration_ms": r.duration_ms,
                "level": r.level,
                "from_cache": r.from_cache,
            }
            for r in self.execution_trace
        ]

        stats = self._calculate_stats(self._total_execution_time_ms, self._max_parallelism)

        return {
            "outputs": self.outputs,
            "trace": legacy_trace,
            "stats": stats.__dict__,
            "levels": self._levels,
            "execution_id": self.execution_id,
        }

    async def run_streaming(self) -> AsyncIterator[ExecutionEvent]:
        """Execute the graph with real-time event streaming using readiness queue (no level barrier)."""
        # Check if we have multiple independent branches that can run in parallel
        # even if they contain loops
        allow_parallel = bool(self.options.get("allow_parallel_branches", False))
        has_parallel_branches = allow_parallel and len(self._branches) > 1
        
        if has_parallel_branches and (self._merge_points or self._has_cross_branch_data_edges()):
            has_parallel_branches = False

        if has_parallel_branches:
            # Use parallel branch execution - each branch runs sequentially internally
            # but multiple branches execute concurrently
            async for event in self._run_parallel_branches():
                yield event
            return
        
        # Fall back to sequential execution for single-branch graphs with loops
        if self._loop_nodes:
            async for event in self._run_streaming_sequential():
                yield event
            return
        self._execution_order = self._resolve_execution_order()
        execution_set = set(self._execution_order)
        self._reset_execution_state()
        
        max_steps = self.options.get("max_steps")
        breakpoints: Set[str] = set(self.options.get("breakpoints") or [])
        
        total_nodes = len(self._execution_order)
        completed_nodes = 0
        executed_count = 0
        max_parallelism = 0
        loop = asyncio.get_running_loop()
        self._thread_pool = ThreadPoolExecutor(max_workers=self._max_workers)
        self._register_execution(self)
        
        execution_plan = [
            {
                "node_id": node_id,
                "node_type": self.nodes[node_id].type,
                "level": self._node_levels.get(node_id, 0),
                "branch_id": self._branch_roots.get(node_id),
                "is_merge_point": node_id in self._merge_points,
            }
            for node_id in self._execution_order
        ]
        
        # Convert branch sets to lists for JSON serialization
        branches_dict = {
            branch_id: list(node_ids) 
            for branch_id, node_ids in self._branches.items()
        } if self._branches else None
        
        yield ExecutionEvent(
            event_type="start",
            execution_id=self.execution_id,
            timestamp=time.time(),
            total_nodes=total_nodes,
            execution_plan=execution_plan,
            levels=self._levels,
            branches=branches_dict,
            merge_points=list(self._merge_points) if self._merge_points else None,
        )
        
        remaining_inputs: Dict[str, int] = {
            node_id: len(self.input_map.get(node_id, {})) + len(self.control_inputs.get(node_id, [])) for node_id in execution_set
        }
        ready: deque[str] = deque([nid for nid, deg in remaining_inputs.items() if deg == 0])
        tasks: Dict[asyncio.Task[NodeExecutionResult], Tuple[str, Dict[str, Any]]] = {}
        pending_interrupted = False

        def _propagate_failure(failed_id: str, reason: str, status: NodeStatus = NodeStatus.ERROR):
            """Mark downstream nodes as skipped/errors and emit events so UI doesn't show them stuck as queued."""
            nonlocal ready, completed_nodes
            stack = list(self._dependents.get(failed_id, []))
            while stack:
                dep = stack.pop()
                if dep not in execution_set:
                    continue
                if remaining_inputs.get(dep, 0) < 0:
                    continue
                if dep in ready:
                    ready = deque([n for n in ready if n != dep])
                remaining_inputs[dep] = -1
                result = NodeExecutionResult(
                    node_id=dep,
                    node_type=self.nodes[dep].type,
                    status=status,
                    logs=[reason],
                    duration_ms=0.0,
                    level=self._node_levels.get(dep, 0),
                    from_cache=False,
                )
                self._finalize_node_result(dep, {}, result, cached=False)
                completed_nodes += 1
                yield ExecutionEvent(
                    event_type="node_error" if status == NodeStatus.ERROR else "node_skipped",
                    execution_id=self.execution_id,
                    timestamp=time.time(),
                    node_id=dep,
                    node_type=result.node_type,
                    status=status,
                    error=reason if status == NodeStatus.ERROR else None,
                    error_code="dependency_failed" if status == NodeStatus.ERROR else "dependency_skipped",
                    duration_ms=0.0,
                    level=result.level,
                    progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                    total_nodes=total_nodes,
                    completed_nodes=completed_nodes,
                    from_cache=False,
                )
                stack.extend(self._dependents.get(dep, []))

        start_time = time.perf_counter()

        try:
            while ready or tasks:
                if self._should_stop_execution():
                    if not pending_interrupted:
                        for skipped in self._mark_pending_interrupted(execution_set):
                            completed_nodes += 1
                            yield ExecutionEvent(
                                event_type="node_skipped",
                                execution_id=self.execution_id,
                                timestamp=time.time(),
                                node_id=skipped.node_id,
                                node_type=skipped.node_type,
                                status=NodeStatus.SKIPPED,
                                level=skipped.level,
                                progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                                total_nodes=total_nodes,
                                completed_nodes=completed_nodes,
                            )
                        pending_interrupted = True
                    for pending in tasks.keys():
                        pending.cancel()
                    ready.clear()
                else:
                    # Queue ready nodes
                    while ready and len(tasks) < self._max_workers:
                        node_id = ready.popleft()
                        if self._should_interrupt(node_id):
                            skipped = self._record_interrupted(node_id)
                            completed_nodes += 1
                            yield ExecutionEvent(
                                event_type="node_skipped",
                                execution_id=self.execution_id,
                                timestamp=time.time(),
                                node_id=node_id,
                                node_type=skipped.node_type,
                                status=NodeStatus.SKIPPED,
                                level=skipped.level,
                                progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                                total_nodes=total_nodes,
                                completed_nodes=completed_nodes,
                            )
                            for event in _propagate_failure(
                                node_id,
                                f"Dependency '{node_id}' was interrupted",
                                status=NodeStatus.SKIPPED,
                            ):
                                yield event
                            continue

                        # Skip nodes in inactive If/Else branches
                        if node_id in self._skipped_branches:
                            skipped = self._record_interrupted(node_id)
                            completed_nodes += 1
                            yield ExecutionEvent(
                                event_type="node_skipped",
                                execution_id=self.execution_id,
                                timestamp=time.time(),
                                node_id=node_id,
                                node_type=skipped.node_type,
                                status=NodeStatus.SKIPPED,
                                logs=["Skipped: If/Else condition was False"],
                                level=skipped.level,
                                progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                                total_nodes=total_nodes,
                                completed_nodes=completed_nodes,
                            )
                            # Still propagate dependencies so downstream nodes become ready
                            for dep_node in self._dependents.get(node_id, []):
                                if dep_node in remaining_inputs:
                                    remaining_inputs[dep_node] -= 1
                                    if remaining_inputs[dep_node] == 0 and dep_node in execution_set:
                                        ready.append(dep_node)
                            continue

                        # Handle If/Else nodes specially
                        if self._is_ifelse_node(node_id):
                            try:
                                inputs = self._prepare_inputs(node_id)
                            except GraphExecutionError as exc:
                                result = self._make_input_error_result(node_id, exc)
                                self._finalize_node_result(node_id, {}, result, cached=False)
                                completed_nodes += 1
                                executed_count += 1
                                yield ExecutionEvent(
                                    event_type="node_error",
                                    execution_id=self.execution_id,
                                    timestamp=time.time(),
                                    node_id=node_id,
                                    node_type=result.node_type,
                                    status=NodeStatus.ERROR,
                                    error=result.error,
                                    error_code=result.error_code,
                                    duration_ms=result.duration_ms,
                                    level=result.level,
                                    progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                                    total_nodes=total_nodes,
                                    completed_nodes=completed_nodes,
                                    from_cache=result.from_cache,
                                )
                                if self._fail_fast:
                                    tasks.clear()
                                    break
                                continue
                            
                            # Evaluate condition and mark inactive branch
                            true_nodes = self._ifelse_true_branch.get(node_id, set())
                            false_nodes = self._ifelse_false_branch.get(node_id, set())
                            self._skipped_branches -= true_nodes
                            self._skipped_branches -= false_nodes
                            
                            condition = bool(inputs.get("condition", False))
                            if condition:
                                self._skipped_branches.update(false_nodes)
                            else:
                                self._skipped_branches.update(true_nodes)
                            
                            ifelse_outputs = {"true": None, "false": None}
                            result = NodeExecutionResult(
                                node_id=node_id,
                                node_type=self.nodes[node_id].type,
                                status=NodeStatus.COMPLETED,
                                outputs=ifelse_outputs,
                                logs=[f"Condition evaluated to {condition}"],
                                duration_ms=0.0,
                                level=self._node_levels.get(node_id, 0),
                                from_cache=False,
                            )
                            self._finalize_node_result(node_id, inputs, result, cached=False)
                            completed_nodes += 1
                            executed_count += 1
                            yield ExecutionEvent(
                                event_type="node_completed",
                                execution_id=self.execution_id,
                                timestamp=time.time(),
                                node_id=node_id,
                                node_type=self.nodes[node_id].type,
                                status=NodeStatus.COMPLETED,
                                outputs=ifelse_outputs,
                                logs=result.logs,
                                duration_ms=result.duration_ms,
                                level=result.level,
                                progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                                total_nodes=total_nodes,
                                completed_nodes=completed_nodes,
                                from_cache=False,
                            )
                            # Propagate dependencies - use remaining_inputs for dependency tracking
                            for dep_node in self._dependents.get(node_id, []):
                                if dep_node in remaining_inputs:
                                    remaining_inputs[dep_node] -= 1
                                    if remaining_inputs[dep_node] == 0 and dep_node in execution_set:
                                        ready.append(dep_node)
                            continue

                        if max_steps is not None and executed_count >= max_steps:
                            tasks.clear()
                            break
                        if node_id in breakpoints:
                            tasks.clear()
                            break

                        node = self.nodes[node_id]
                        yield ExecutionEvent(
                            event_type="node_queued",
                            execution_id=self.execution_id,
                            timestamp=time.time(),
                            node_id=node_id,
                            node_type=node.type,
                            status=NodeStatus.QUEUED,
                            level=self._node_levels.get(node_id, 0),
                            progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                            total_nodes=total_nodes,
                            completed_nodes=completed_nodes,
                        )

                        inputs = self._prepare_inputs(node_id)
                        cached_outputs = self._try_get_cached(node_id, inputs)

                        if cached_outputs is not None:
                            cached_start = time.perf_counter()
                            result = NodeExecutionResult(
                                node_id=node_id,
                                node_type=node.type,
                                status=NodeStatus.COMPLETED,
                                outputs=cached_outputs,
                                logs=[f"[CACHED] Skipped execution, using cached result"],
                                start_time=cached_start,
                                end_time=cached_start,
                                duration_ms=0.0,
                                level=self._node_levels.get(node_id, 0),
                                from_cache=True,
                            )
                            self._finalize_node_result(node_id, inputs, result, cached=True)
                            completed_nodes += 1
                            executed_count += 1
                            yield ExecutionEvent(
                                event_type="node_cached",
                                execution_id=self.execution_id,
                                timestamp=time.time(),
                                node_id=node_id,
                                node_type=node.type,
                                status=NodeStatus.COMPLETED,
                                outputs=result.outputs,
                                logs=result.logs,
                                duration_ms=result.duration_ms,
                                level=result.level,
                                progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                                total_nodes=total_nodes,
                                completed_nodes=completed_nodes,
                                from_cache=True,
                            )
                            # Enqueue dependents immediately
                            for dep in self._dependents.get(node_id, []):
                                if dep not in execution_set:
                                    continue
                                if remaining_inputs.get(dep, 0) < 0:
                                    continue
                                remaining_inputs[dep] -= 1
                                if remaining_inputs[dep] == 0:
                                    ready.append(dep)
                            continue

                        self._node_status[node_id] = NodeStatus.RUNNING
                        yield ExecutionEvent(
                            event_type="node_started",
                            execution_id=self.execution_id,
                            timestamp=time.time(),
                            node_id=node_id,
                            node_type=node.type,
                            status=NodeStatus.RUNNING,
                            level=self._node_levels.get(node_id, 0),
                            progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                            total_nodes=total_nodes,
                            completed_nodes=completed_nodes,
                        )

                        future = loop.run_in_executor(self._thread_pool, self._execute_node_work, node_id, inputs)
                        task = asyncio.wrap_future(future)
                        tasks[task] = (node_id, inputs)
                        self._cancellation.register_running(node_id, task)
                        executed_count += 1

                max_parallelism = max(max_parallelism, len(tasks) or 1 if executed_count else 0)

                if not tasks:
                    break

                done, _ = await asyncio.wait(tasks.keys(), return_when=FIRST_COMPLETED)
                for task in done:
                    node_id, inputs = tasks.pop(task)
                    try:
                        result = task.result()
                    except asyncio.CancelledError:
                        result = self._make_interrupted_result(node_id)
                    self._finalize_node_result(node_id, inputs, result, cached=False)
                    completed_nodes += 1

                    if result.status == NodeStatus.ERROR:
                        yield ExecutionEvent(
                            event_type="node_error",
                            execution_id=self.execution_id,
                            timestamp=time.time(),
                            node_id=result.node_id,
                            node_type=result.node_type,
                            status=NodeStatus.ERROR,
                            error=result.error,
                            error_code=result.error_code,
                            duration_ms=result.duration_ms,
                            level=result.level,
                            progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                            total_nodes=total_nodes,
                            completed_nodes=completed_nodes,
                            from_cache=result.from_cache,
                        )
                        if self._fail_fast:
                            for pending in tasks.keys():
                                pending.cancel()
                            tasks.clear()
                            break
                    else:
                        yield ExecutionEvent(
                            event_type="node_completed" if result.status == NodeStatus.COMPLETED else "node_skipped",
                            execution_id=self.execution_id,
                            timestamp=time.time(),
                            node_id=result.node_id,
                            node_type=result.node_type,
                            status=result.status,
                            outputs=result.outputs,
                            logs=result.logs,
                            duration_ms=result.duration_ms,
                            level=result.level,
                            progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                            total_nodes=total_nodes,
                            completed_nodes=completed_nodes,
                            from_cache=result.from_cache,
                        )

                    if result.status != NodeStatus.COMPLETED:
                        status = NodeStatus.ERROR if result.status == NodeStatus.ERROR else NodeStatus.SKIPPED
                        reason = (
                            f"Dependency '{result.node_id}' failed"
                            if status == NodeStatus.ERROR
                            else f"Dependency '{result.node_id}' was interrupted"
                        )
                        for event in _propagate_failure(result.node_id, reason, status=status):
                            yield event

                    # Enqueue dependents
                    for dep in self._dependents.get(node_id, []):
                        if dep not in execution_set:
                            continue
                        if remaining_inputs.get(dep, 0) < 0:
                            continue
                        remaining_inputs[dep] -= 1
                        if remaining_inputs[dep] == 0:
                            ready.append(dep)
                
                await asyncio.sleep(0)

        finally:
            if self._thread_pool:
                self._thread_pool.shutdown(wait=False)
                self._thread_pool = None
            self._cleanup_resources()
            self._unregister_execution(self.execution_id)

        if max_parallelism == 0 and executed_count > 0:
            max_parallelism = 1

        total_time = (time.perf_counter() - start_time) * 1000
        self._total_execution_time_ms = total_time
        self._max_parallelism = max_parallelism
        self.outputs = self._collect_outputs()
        
        yield ExecutionEvent(
            event_type="complete",
            execution_id=self.execution_id,
            timestamp=time.time(),
            progress=1.0,
            total_nodes=total_nodes,
            completed_nodes=completed_nodes,
        )

    def _collect_outputs(self) -> Dict[str, Any]:
        """Collect final outputs from executed nodes."""
        results: Dict[str, Any] = {}
        for entry in self.definition.get("output_nodes", []):
            node_id = entry["node_id"]
            port = entry["port"]
            alias = entry.get("alias", f"{node_id}.{port}")
            node_outputs = self._computed_values.get(node_id)
            if not node_outputs or port not in node_outputs:
                continue
            results[alias] = node_outputs[port]
        if not results:
            for node_id, output_map in self._computed_values.items():
                for port, value in output_map.items():
                    results[f"{node_id}.{port}"] = value
        return results

    def _calculate_stats(self, total_time_ms: float, max_parallelism: int = 1) -> ExecutionStats:
        """Calculate execution statistics."""
        node_time_ms = sum(r.duration_ms for r in self.execution_trace)
        completed = [r for r in self.execution_trace if r.status == NodeStatus.COMPLETED]
        cached = len([r for r in completed if r.from_cache])
        executed = len(completed) - cached  # Actually executed (not from cache)
        errors = len([r for r in self.execution_trace if r.status == NodeStatus.ERROR])
        skipped = len([r for r in self.execution_trace if r.status == NodeStatus.SKIPPED])
        total_nodes = len(self.execution_trace) if self.execution_trace else len(self._execution_order)
        
        parallel_efficiency = node_time_ms / total_time_ms if total_time_ms > 0 else 1.0
        levels_executed = len(set(r.level for r in self.execution_trace))
        
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

    def get_execution_plan(self) -> Dict[str, Any]:
        """Get the execution plan without running."""
        self._execution_order = self._resolve_execution_order()
        execution_levels = self._resolve_execution_levels()
        
        plan = {
            "execution_id": self.execution_id,
            "total_nodes": len(self._execution_order),
            "levels": len(execution_levels),
            "max_parallelism": max(len(level) for level in execution_levels) if execution_levels else 0,
            "nodes": [
                {
                    "node_id": node_id,
                    "node_type": self.nodes[node_id].type,
                    "level": self._node_levels.get(node_id, 0),
                    "inputs": list(self.input_map.get(node_id, {}).keys()),
                    "outputs": self.nodes[node_id].output_ports,
                }
                for node_id in self._execution_order
            ],
            "execution_levels": [[node_id for node_id in level] for level in execution_levels],
        }
        
        return plan
