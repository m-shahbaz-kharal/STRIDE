from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
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

    @classmethod
    def clear_cache(cls) -> int:
        """Clear the global execution cache. Returns number of entries cleared."""
        count = len(cls._global_cache)
        cls._global_cache.clear()
        cls._cache_metadata.clear()
        return count

    @classmethod
    def clear_cache_by_type(cls, node_type: str) -> int:
        """Clear cache entries for a specific node type. Returns number of entries cleared."""
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
        return len(cls._global_cache)

    def __init__(self, graph_definition: Dict[str, Any], options: Optional[Dict[str, Any]] = None) -> None:
        self.definition = graph_definition
        self.nodes: Dict[str, NodeBase] = {}
        self.links: List[Link] = []
        self.input_map: Dict[str, Dict[str, Link]] = defaultdict(dict)
        self.output_map: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
        self.execution_trace: List[NodeExecutionResult] = []
        self.outputs: Dict[str, Any] = {}
        self.options: Dict[str, Any] = options or {}
        self.execution_id = str(uuid.uuid4())[:8]
        
        # Execution state
        self._computed_values: Dict[str, Dict[str, Any]] = {}
        self._node_status: Dict[str, NodeStatus] = {}
        self._node_levels: Dict[str, int] = {}
        self._levels: List[List[str]] = []  # Nodes grouped by topological level
        self._total_execution_time_ms: float = 0.0  # Actual wall-clock time
        self._max_parallelism: int = 0
        
        # Caching options
        self._use_cache = self.options.get("use_cache", True)
        
        self._build_nodes()
        self._build_links()
        self._topo_order = self._topological_sort()
        self._compute_levels()
        self._execution_order: List[str] = []

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
        return self._global_cache.get(cache_key)

    def _cache_outputs(self, node_id: str, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        """Cache the outputs for a node."""
        if not self._use_cache:
            return
        cache_key = self._compute_cache_key(node_id, inputs)
        self._global_cache[cache_key] = outputs
        # Store metadata for selective clearing
        node = self.nodes[node_id]
        self._cache_metadata[cache_key] = node.type

    def _build_nodes(self) -> None:
        for node_config in self.definition.get("nodes", []):
            node_type = node_config.get("type")
            if not node_type:
                raise GraphExecutionError(f"Node {node_config} has no type")
            try:
                node_cls = get_node(node_type)
            except KeyError as exc:
                raise GraphExecutionError(str(exc)) from exc
            node = node_cls(node_config)
            self.nodes[node.id] = node
            self._node_status[node.id] = NodeStatus.PENDING

    def _build_links(self) -> None:
        for raw_link in self.definition.get("links", []):
            link = Link(**raw_link)
            if link.to_node not in self.nodes:
                raise GraphExecutionError(f"Link references unknown node {link.to_node}")
            if link.from_node not in self.nodes:
                raise GraphExecutionError(f"Link references unknown node {link.from_node}")
            self.links.append(link)
            self.input_map[link.to_node][link.to_port] = link
            self.output_map[link.from_node].append((link.to_node, link.from_port, link.to_port))

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

    def _execute_node(self, node_id: str) -> NodeExecutionResult:
        """Execute a single node synchronously, using cache if available."""
        node = self.nodes[node_id]
        level = self._node_levels.get(node_id, 0)
        start_time = time.perf_counter()
        
        try:
            inputs = self._gather_inputs(node_id)
            if inputs is None:
                raise GraphExecutionError(f"Node '{node_id}' could not resolve inputs")
            
            # Check cache first
            cached_outputs = self._try_get_cached(node_id, inputs)
            if cached_outputs is not None:
                end_time = time.perf_counter()
                duration_ms = (end_time - start_time) * 1000
                
                self._computed_values[node_id] = cached_outputs
                self._node_status[node_id] = NodeStatus.COMPLETED
                
                return NodeExecutionResult(
                    node_id=node_id,
                    node_type=node.type,
                    status=NodeStatus.COMPLETED,
                    outputs=cached_outputs,
                    logs=[f"[CACHED] Skipped execution, using cached result"],
                    start_time=start_time,
                    end_time=end_time,
                    duration_ms=duration_ms,
                    level=level,
                    from_cache=True,
                )
            
            # Not cached - execute the node
            ctx = ExecutionContext()
            outputs = node.forward(inputs, ctx)
            
            if set(outputs.keys()) != set(node.output_ports):
                raise GraphExecutionError(
                    f"Node '{node_id}' output ports {node.output_ports} do not match produced {list(outputs.keys())}"
                )
            
            end_time = time.perf_counter()
            duration_ms = (end_time - start_time) * 1000
            
            # Cache the results
            self._cache_outputs(node_id, inputs, outputs)
            
            self._computed_values[node_id] = outputs
            self._node_status[node_id] = NodeStatus.COMPLETED
            
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
            self._node_status[node_id] = NodeStatus.ERROR
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

    async def _execute_node_async(self, node_id: str) -> NodeExecutionResult:
        """Execute a single node asynchronously (wraps sync execution)."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._execute_node, node_id)

    def run(self) -> Dict[str, Any]:
        """Execute the graph synchronously (legacy interface)."""
        self._execution_order = self._resolve_execution_order()
        self.execution_trace = []
        self.outputs = {}
        self._computed_values = {}
        
        executed_count = 0
        max_steps = self.options.get("max_steps")
        breakpoints: Set[str] = set(self.options.get("breakpoints") or [])
        
        start_time = time.perf_counter()

        for node_id in self._execution_order:
            if max_steps is not None and executed_count >= max_steps:
                break
            if node_id in breakpoints:
                break

            result = self._execute_node(node_id)
            executed_count += 1
            self.execution_trace.append(result)
            
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
        """Execute the graph with level-based parallelism."""
        self._execution_order = self._resolve_execution_order()
        self.execution_trace = []
        self.outputs = {}
        self._computed_values = {}
        
        execution_levels = self._resolve_execution_levels()
        max_steps = self.options.get("max_steps")
        breakpoints: Set[str] = set(self.options.get("breakpoints") or [])
        
        start_time = time.perf_counter()
        executed_count = 0
        max_parallelism = 0

        for level_idx, level_nodes in enumerate(execution_levels):
            if not level_nodes:
                continue
                
            should_break = False
            nodes_to_execute = []
            for node_id in level_nodes:
                if max_steps is not None and executed_count >= max_steps:
                    should_break = True
                    break
                if node_id in breakpoints:
                    should_break = True
                    break
                nodes_to_execute.append(node_id)
                executed_count += 1
            
            if not nodes_to_execute:
                break
            
            max_parallelism = max(max_parallelism, len(nodes_to_execute))
            
            if len(nodes_to_execute) == 1:
                result = self._execute_node(nodes_to_execute[0])
                self.execution_trace.append(result)
            else:
                tasks = [self._execute_node_async(node_id) for node_id in nodes_to_execute]
                results = await asyncio.gather(*tasks)
                self.execution_trace.extend(results)
            
            for result in self.execution_trace[-len(nodes_to_execute):]:
                if result.status == NodeStatus.ERROR:
                    should_break = True
                    break
            
            if should_break:
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
        
        stats = self._calculate_stats(total_time, max_parallelism)
        
        return {
            "outputs": self.outputs,
            "trace": legacy_trace,
            "stats": stats.__dict__,
            "levels": self._levels,
            "execution_id": self.execution_id,
        }

    async def run_streaming(self) -> AsyncIterator[ExecutionEvent]:
        """Execute the graph with real-time event streaming."""
        self._execution_order = self._resolve_execution_order()
        self.execution_trace = []
        self.outputs = {}
        self._computed_values = {}
        
        execution_levels = self._resolve_execution_levels()
        max_steps = self.options.get("max_steps")
        breakpoints: Set[str] = set(self.options.get("breakpoints") or [])
        
        total_nodes = len(self._execution_order)
        completed_nodes = 0
        
        start_time = time.perf_counter()
        
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
            levels=[list(level) for level in execution_levels],
        )
        
        executed_count = 0
        max_parallelism = 0

        for level_idx, level_nodes in enumerate(execution_levels):
            if not level_nodes:
                continue
            
            for node_id in level_nodes:
                if max_steps is not None and executed_count >= max_steps:
                    break
                if node_id in breakpoints:
                    break
                    
                node = self.nodes[node_id]
                yield ExecutionEvent(
                    event_type="node_queued",
                    execution_id=self.execution_id,
                    timestamp=time.time(),
                    node_id=node_id,
                    node_type=node.type,
                    status=NodeStatus.QUEUED,
                    level=level_idx,
                    progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                    total_nodes=total_nodes,
                    completed_nodes=completed_nodes,
                )
            
            should_break = False
            nodes_to_execute = []
            for node_id in level_nodes:
                if max_steps is not None and executed_count >= max_steps:
                    should_break = True
                    break
                if node_id in breakpoints:
                    should_break = True
                    break
                nodes_to_execute.append(node_id)
                executed_count += 1
            
            if not nodes_to_execute:
                break
            
            max_parallelism = max(max_parallelism, len(nodes_to_execute))
            
            for node_id in nodes_to_execute:
                node = self.nodes[node_id]
                yield ExecutionEvent(
                    event_type="node_started",
                    execution_id=self.execution_id,
                    timestamp=time.time(),
                    node_id=node_id,
                    node_type=node.type,
                    status=NodeStatus.RUNNING,
                    level=level_idx,
                    progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                    total_nodes=total_nodes,
                    completed_nodes=completed_nodes,
                )
            
            # Execute nodes and stream results as they complete (not waiting for all)
            if len(nodes_to_execute) == 1:
                # Single node - execute directly
                result = self._execute_node(nodes_to_execute[0])
                self.execution_trace.append(result)
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
                    should_break = True
                else:
                    yield ExecutionEvent(
                        event_type="node_completed" if not result.from_cache else "node_cached",
                        execution_id=self.execution_id,
                        timestamp=time.time(),
                        node_id=result.node_id,
                        node_type=result.node_type,
                        status=NodeStatus.COMPLETED,
                        outputs=result.outputs,
                        logs=result.logs,
                        duration_ms=result.duration_ms,
                        level=result.level,
                        progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                        total_nodes=total_nodes,
                        completed_nodes=completed_nodes,
                        from_cache=result.from_cache,
                    )
            else:
                # Multiple nodes - execute in parallel and stream results as they complete
                # Create all tasks first (this schedules them)
                tasks = [
                    asyncio.create_task(self._execute_node_async(node_id))
                    for node_id in nodes_to_execute
                ]
                
                # Yield control to let all tasks start executing in the thread pool
                # This ensures all blocking operations begin before we start waiting
                await asyncio.sleep(0)
                
                # Wait for results as they complete using asyncio.wait
                pending = set(tasks)
                while pending:
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    
                    for task in done:
                        result = task.result()
                        self.execution_trace.append(result)
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
                            should_break = True
                        else:
                            yield ExecutionEvent(
                                event_type="node_completed" if not result.from_cache else "node_cached",
                                execution_id=self.execution_id,
                                timestamp=time.time(),
                                node_id=result.node_id,
                                node_type=result.node_type,
                                status=NodeStatus.COMPLETED,
                                outputs=result.outputs,
                                logs=result.logs,
                                duration_ms=result.duration_ms,
                                level=result.level,
                                progress=completed_nodes / total_nodes if total_nodes > 0 else 0,
                                total_nodes=total_nodes,
                                completed_nodes=completed_nodes,
                                from_cache=result.from_cache,
                            )
            
            if should_break:
                break
            
            await asyncio.sleep(0)

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
