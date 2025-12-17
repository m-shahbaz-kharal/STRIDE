from __future__ import annotations

import asyncio
import hashlib
import json
import os
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple

from .nodes import ExecutionContext, NodeBase, get_node


class GraphExecutionError(Exception):
    pass


class NodeStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class Link:
    from_node: str
    from_port: str
    to_node: str
    to_port: str


@dataclass
class NodeExecutionResult:
    """Result of executing a single node."""
    node_id: str
    node_type: str
    status: NodeStatus
    outputs: Dict[str, Any] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: float = 0.0
    error: Optional[str] = None
    level: int = 0  # Topological level for parallel execution
    from_cache: bool = False  # Whether result came from cache


@dataclass
class ExecutionEvent:
    """Event emitted during graph execution for real-time updates."""
    event_type: str  # "start", "node_queued", "node_started", "node_completed", "node_skipped", "node_error", "complete"
    execution_id: str
    timestamp: float
    node_id: Optional[str] = None
    node_type: Optional[str] = None
    status: Optional[NodeStatus] = None
    outputs: Optional[Dict[str, Any]] = None
    logs: Optional[List[str]] = None
    duration_ms: Optional[float] = None
    error: Optional[str] = None
    level: Optional[int] = None
    progress: Optional[float] = None  # 0.0 to 1.0
    total_nodes: Optional[int] = None
    completed_nodes: Optional[int] = None
    from_cache: Optional[bool] = None  # Whether result came from cache
    # Execution plan info (sent at start)
    execution_plan: Optional[List[Dict[str, Any]]] = None
    levels: Optional[List[List[str]]] = None


@dataclass
class ExecutionStats:
    """Statistics about graph execution."""
    total_nodes: int = 0
    executed_nodes: int = 0
    skipped_nodes: int = 0
    cached_nodes: int = 0  # Nodes that used cached results
    error_nodes: int = 0
    total_time_ms: float = 0.0
    node_time_ms: float = 0.0  # Sum of individual node times
    parallel_efficiency: float = 0.0  # node_time_ms / total_time_ms (higher = more parallelism)
    max_parallelism: int = 0  # Max nodes that ran in parallel
    levels_executed: int = 0


class GraphExecutor:
    """High-performance graph executor with level-based parallel execution and caching."""

    # Class-level cache shared across all executor instances
    # Key: cache_key (hash of node type + params + inputs)
    # Value: cached outputs dict
    _global_cache: Dict[str, Dict[str, Any]] = {}

    # Maps cache_key -> node_type for selective clearing
    _cache_metadata: Dict[str, str] = {}
    _cache_lock = threading.Lock()
    _active_executions: Dict[str, "GraphExecutor"] = {}
    _active_lock = threading.Lock()

    @classmethod
    def clear_cache(cls) -> int:
        """Clear the global execution cache. Returns number of entries cleared."""
        with cls._cache_lock:
            count = len(cls._global_cache)
            cls._global_cache.clear()
            cls._cache_metadata.clear()
        return count

    @classmethod
    def clear_cache_by_type(cls, node_type: str) -> int:
        """Clear cache entries for a specific node type. Returns number of entries cleared."""
        with cls._cache_lock:
            keys_to_remove = [
                key for key, cached_type in cls._cache_metadata.items()
                if cached_type == node_type
            ]
            for key in keys_to_remove:
                cls._global_cache.pop(key, None)
                cls._cache_metadata.pop(key, None)
            return len(keys_to_remove)

    @classmethod
    def get_cache_size(cls) -> int:
        """Get the current number of cached entries."""
        with cls._cache_lock:
            return len(cls._global_cache)

    def __init__(self, graph_definition: Dict[str, Any], options: Optional[Dict[str, Any]] = None) -> None:
        self.definition = graph_definition
        self.nodes: Dict[str, NodeBase] = {}
        self.links: List[Link] = []
        self.input_map: Dict[str, Dict[str, Link]] = defaultdict(dict)
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
        self._running_tasks: Dict[str, asyncio.Future] = {}
        self._cancelled_nodes: Set[str] = set()
        self._cancel_all: bool = False
        
        # Caching options
        self._use_cache = self.options.get("use_cache", True)
        
        self._build_nodes()
        self._build_links()
        self._validate_output_nodes()
        self._topo_order = self._topological_sort()
        self._compute_levels()
        self._execution_order: List[str] = []

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
        executor._cancel_all = True
        executor._cancel_running_tasks()
        return True

    @classmethod
    def cancel_node(cls, execution_id: str, node_id: str) -> bool:
        with cls._active_lock:
            executor = cls._active_executions.get(execution_id)
        if not executor:
            return False
        executor._cancelled_nodes.add(node_id)
        executor._cancel_running_tasks(target=node_id)
        return True

    def _cancel_running_tasks(self, target: Optional[str] = None) -> None:
        """Cancel running asyncio futures for specific node or all."""
        with self._state_lock:
            items = list(self._running_tasks.items())
        for node_id, fut in items:
            if target and node_id != target:
                continue
            if not fut.done():
                fut.cancel()

    def _compute_cache_key(self, node_id: str, inputs: Dict[str, Any]) -> str:
        """Compute a unique cache key for a node based on its type, params, and inputs."""
        node = self.nodes[node_id]
        key_data = {
            "type": node.type,
            "params": node.params,
            "inputs": inputs,
        }
        # Create a stable hash from the key data
        key_str = json.dumps(key_data, sort_keys=True, default=str)
        return hashlib.sha256(key_str.encode()).hexdigest()[:16]

    def _try_get_cached(self, node_id: str, inputs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Try to get cached outputs for a node. Returns None if not cached."""
        if not self._use_cache:
            return None
        cache_key = self._compute_cache_key(node_id, inputs)
        with self._cache_lock:
            return self._global_cache.get(cache_key)

    def _cache_outputs(self, node_id: str, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        """Cache the outputs for a node."""
        if not self._use_cache:
            return
        cache_key = self._compute_cache_key(node_id, inputs)
        node = self.nodes[node_id]
        with self._cache_lock:
            self._global_cache[cache_key] = outputs
            # Store metadata for selective clearing
            self._cache_metadata[cache_key] = node.type

    def _build_nodes(self) -> None:
        node_configs = self.definition.get("nodes", [])
        if not node_configs:
            raise GraphExecutionError("Graph contains no nodes to execute")

        for node_config in node_configs:
            node_type = node_config.get("type")
            if not node_type:
                raise GraphExecutionError(f"Node {node_config} has no type")
            node_id = node_config.get("id")
            if not node_id:
                raise GraphExecutionError("Every node must declare a unique 'id'")
            if node_id in self.nodes:
                raise GraphExecutionError(f"Duplicate node id '{node_id}' detected")
            try:
                node_cls = get_node(node_type)
            except KeyError as exc:
                raise GraphExecutionError(str(exc)) from exc
            node = node_cls(node_config)
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

            key = (link.from_node, link.from_port, link.to_node, link.to_port)
            if key in seen_links:
                raise GraphExecutionError(
                    f"Duplicate link detected: {link.from_node}.{link.from_port} -> {link.to_node}.{link.to_port}"
                )

            from_node = self.nodes[link.from_node]
            to_node = self.nodes[link.to_node]
            if link.from_port not in from_node.output_ports:
                raise GraphExecutionError(
                    f"Link from '{link.from_node}' references missing output port '{link.from_port}'"
                )
            if link.to_port not in to_node.input_ports:
                raise GraphExecutionError(
                    f"Link to '{link.to_node}' references missing input port '{link.to_port}'"
                )

            self.links.append(link)
            self.input_map[link.to_node][link.to_port] = link
            self.output_map[link.from_node].append((link.to_node, link.from_port, link.to_port))
            self._dependents[link.from_node].append(link.to_node)

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
                    f"Output references unknown port '{port}' on node '{node_id}'"
                )

    def _topological_sort(self) -> List[str]:
        """Kahn's algorithm for topological sorting."""
        dependencies: Dict[str, int] = {
            node_id: len(self.input_map.get(node_id, {})) for node_id in self.nodes
        }
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
            if not input_links:
                levels[node_id] = 0
            else:
                max_input_level = max(
                    levels.get(link.from_node, 0) for link in input_links.values()
                )
                levels[node_id] = max_input_level + 1
        
        self._node_levels = levels
        
        level_groups: Dict[int, List[str]] = defaultdict(list)
        for node_id, level in levels.items():
            level_groups[level].append(node_id)
        
        max_level = max(levels.values()) if levels else 0
        self._levels = [level_groups.get(i, []) for i in range(max_level + 1)]

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
        return collected

    def _resolve_execution_order(self) -> List[str]:
        """Resolve which nodes to execute based on options."""
        mode = str(self.options.get("mode", "full")).lower()
        if mode == "selection":
            target_nodes = [node_id for node_id in (self.options.get("target_nodes") or []) if node_id in self.nodes]
            if target_nodes:
                allowed = self._expand_dependencies(target_nodes)
                return [node_id for node_id in self._topo_order if node_id in allowed]
        return list(self._topo_order)

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
        if node_id not in self.input_map:
            raise GraphExecutionError(f"Node '{node_id}' declares inputs but no links are mapped")
        inputs: Dict[str, Any] = {}
        for port in node.input_ports:
            link = self.input_map[node_id].get(port)
            if not link:
                raise GraphExecutionError(f"Node '{node_id}' is missing link for port '{port}'")
            if link.from_node not in self._computed_values:
                return None
            value = self._computed_values[link.from_node].get(link.from_port)
            inputs[port] = value
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
    ) -> None:
        """Persist a node result back into executor state."""
        if result.status == NodeStatus.COMPLETED:
            if not cached:
                self._cache_outputs(node_id, inputs, result.outputs)
            with self._state_lock:
                self._computed_values[node_id] = result.outputs
        self._node_status[node_id] = result.status
        self.execution_trace.append(result)
        with self._state_lock:
            self._running_tasks.pop(node_id, None)

    def _execute_node_work(self, node_id: str, inputs: Dict[str, Any]) -> NodeExecutionResult:
        """Execute a node in an isolated worker thread without mutating shared state."""
        node = self.nodes[node_id]
        level = self._node_levels.get(node_id, 0)
        start_time = time.perf_counter()

        try:
            ctx = ExecutionContext()
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
                level=level,
                from_cache=False,
            )

    def run(self) -> Dict[str, Any]:
        """Execute the graph synchronously (legacy interface)."""
        self._execution_order = self._resolve_execution_order()
        self.execution_trace = []
        self.outputs = {}
        self._computed_values = {}
        self._cancel_all = False
        self._cancelled_nodes.clear()
        self._running_tasks = {}
        self._running_tasks = {}
        
        executed_count = 0
        max_steps = self.options.get("max_steps")
        breakpoints: Set[str] = set(self.options.get("breakpoints") or [])
        
        start_time = time.perf_counter()

        for node_id in self._execution_order:
            if self._cancel_all or node_id in self._cancelled_nodes:
                skipped_result = NodeExecutionResult(
                    node_id=node_id,
                    node_type=self.nodes[node_id].type,
                    status=NodeStatus.SKIPPED,
                    logs=[f"Node {node_id} interrupted"],
                    duration_ms=0.0,
                    level=self._node_levels.get(node_id, 0),
                )
                self._finalize_node_result(node_id, {}, skipped_result, cached=False)
                executed_count += 1
                continue
            if max_steps is not None and executed_count >= max_steps:
                break
            if node_id in breakpoints:
                break

            node_start = time.perf_counter()
            inputs = self._prepare_inputs(node_id)
            cached_outputs = self._try_get_cached(node_id, inputs)

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
                self._finalize_node_result(node_id, inputs, result, cached=True)
            else:
                result = self._execute_node_work(node_id, inputs)
                self._finalize_node_result(node_id, inputs, result, cached=False)

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

    async def run_async(self) -> Dict[str, Any]:
        """Execute the graph with dynamic readiness (no level barrier)."""
        self._execution_order = self._resolve_execution_order()
        execution_set = set(self._execution_order)
        self.execution_trace = []
        self.outputs = {}
        self._computed_values = {}
        self._cancel_all = False
        self._cancelled_nodes.clear()

        max_steps = self.options.get("max_steps")
        breakpoints: Set[str] = set(self.options.get("breakpoints") or [])

        # Track remaining dependencies per node
        remaining_inputs: Dict[str, int] = {
          node_id: len(self.input_map.get(node_id, {})) for node_id in execution_set
        }
        ready: deque[str] = deque([nid for nid, deg in remaining_inputs.items() if deg == 0])

        start_time = time.perf_counter()
        executed_count = 0
        completed_nodes = 0
        max_parallelism = 0
        loop = asyncio.get_running_loop()
        self._thread_pool = ThreadPoolExecutor(max_workers=self._max_workers)
        self._register_execution(self)

        tasks: Dict[asyncio.Task[NodeExecutionResult], Tuple[str, Dict[str, Any]]] = {}

        try:
            while (ready or tasks) and not self._cancel_all:
                # Launch tasks while capacity remains
                while ready and len(tasks) < self._max_workers:
                    node_id = ready.popleft()
                    if node_id in self._cancelled_nodes:
                        skipped = NodeExecutionResult(
                            node_id=node_id,
                            node_type=self.nodes[node_id].type,
                            status=NodeStatus.SKIPPED,
                            logs=[f"Node {node_id} interrupted"],
                            duration_ms=0.0,
                            level=self._node_levels.get(node_id, 0),
                            from_cache=False,
                        )
                        self._finalize_node_result(node_id, {}, skipped, cached=False)
                        completed_nodes += 1
                        continue
                    if max_steps is not None and executed_count >= max_steps:
                        tasks.clear()
                        break
                    if node_id in breakpoints:
                        tasks.clear()
                        break

                    inputs = self._prepare_inputs(node_id)
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
                    else:
                        self._node_status[node_id] = NodeStatus.RUNNING
                        future = loop.run_in_executor(self._thread_pool, self._execute_node_work, node_id, inputs)
                        task = asyncio.wrap_future(future)
                        tasks[task] = (node_id, inputs)
                        with self._state_lock:
                            self._running_tasks[node_id] = task
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
                        result = NodeExecutionResult(
                            node_id=node_id,
                            node_type=self.nodes[node_id].type,
                            status=NodeStatus.SKIPPED,
                            logs=[f"Node {node_id} interrupted"],
                            duration_ms=0.0,
                            level=self._node_levels.get(node_id, 0),
                            from_cache=False,
                        )
                    self._finalize_node_result(node_id, inputs, result, cached=False)
                    completed_nodes += 1

                    if result.status == NodeStatus.ERROR and self._fail_fast:
                        for pending in tasks.keys():
                            pending.cancel()
                        tasks.clear()
                        break

                    # Enqueue dependents when all their inputs are ready
                    for dep in self._dependents.get(node_id, []):
                        if dep not in execution_set:
                            continue
                        remaining_inputs[dep] -= 1
                        if remaining_inputs[dep] == 0:
                            ready.append(dep)

        finally:
            if self._thread_pool:
                self._thread_pool.shutdown(wait=False)
                self._thread_pool = None
            self._unregister_execution(self.execution_id)

        if max_parallelism == 0 and executed_count > 0:
            max_parallelism = 1

        total_time = (time.perf_counter() - start_time) * 1000
        self._total_execution_time_ms = total_time
        self._max_parallelism = max_parallelism
        
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
        
        stats = self._calculate_stats(total_time, max_parallelism)
        
        return {
            "outputs": self.outputs,
            "trace": legacy_trace,
            "stats": stats.__dict__,
            "levels": self._levels,
            "execution_id": self.execution_id,
        }

    async def run_streaming(self) -> AsyncIterator[ExecutionEvent]:
        """Execute the graph with real-time event streaming using readiness queue (no level barrier)."""
        self._execution_order = self._resolve_execution_order()
        execution_set = set(self._execution_order)
        self.execution_trace = []
        self.outputs = {}
        self._computed_values = {}
        self._cancel_all = False
        self._cancelled_nodes.clear()
        
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
            }
            for node_id in self._execution_order
        ]
        
        yield ExecutionEvent(
            event_type="start",
            execution_id=self.execution_id,
            timestamp=time.time(),
            total_nodes=total_nodes,
            execution_plan=execution_plan,
            levels=self._levels,
        )
        
        remaining_inputs: Dict[str, int] = {
            node_id: len(self.input_map.get(node_id, {})) for node_id in execution_set
        }
        ready: deque[str] = deque([nid for nid, deg in remaining_inputs.items() if deg == 0])
        tasks: Dict[asyncio.Task[NodeExecutionResult], Tuple[str, Dict[str, Any]]] = {}
        
        start_time = time.perf_counter()

        try:
            while (ready or tasks) and not self._cancel_all:
                # Queue ready nodes
                while ready and len(tasks) < self._max_workers:
                    node_id = ready.popleft()
                    if node_id in self._cancelled_nodes:
                        skipped = NodeExecutionResult(
                            node_id=node_id,
                            node_type=self.nodes[node_id].type,
                            status=NodeStatus.SKIPPED,
                            logs=[f"Node {node_id} interrupted"],
                            duration_ms=0.0,
                            level=self._node_levels.get(node_id, 0),
                            from_cache=False,
                        )
                        self._finalize_node_result(node_id, {}, skipped, cached=False)
                        completed_nodes += 1
                        yield ExecutionEvent(
                            event_type="node_skipped",
                            execution_id=self.execution_id,
                            timestamp=time.time(),
                            node_id=node_id,
                            node_type=self.nodes[node_id].type,
                            status=NodeStatus.SKIPPED,
                            level=self._node_levels.get(node_id, 0),
                            progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                            total_nodes=total_nodes,
                            completed_nodes=completed_nodes,
                        )
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
                    with self._state_lock:
                        self._running_tasks[node_id] = task
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
                        result = NodeExecutionResult(
                            node_id=node_id,
                            node_type=self.nodes[node_id].type,
                            status=NodeStatus.SKIPPED,
                            logs=[f"Node {node_id} interrupted"],
                            duration_ms=0.0,
                            level=self._node_levels.get(node_id, 0),
                            from_cache=False,
                        )
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

                    # Enqueue dependents
                    for dep in self._dependents.get(node_id, []):
                        if dep not in execution_set:
                            continue
                        remaining_inputs[dep] -= 1
                        if remaining_inputs[dep] == 0:
                            ready.append(dep)
                
                await asyncio.sleep(0)

        finally:
            if self._thread_pool:
                self._thread_pool.shutdown(wait=False)
                self._thread_pool = None
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
        skipped = len(self._execution_order) - len(completed) - errors
        
        parallel_efficiency = node_time_ms / total_time_ms if total_time_ms > 0 else 1.0
        levels_executed = len(set(r.level for r in self.execution_trace))
        
        return ExecutionStats(
            total_nodes=len(self._execution_order),
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
