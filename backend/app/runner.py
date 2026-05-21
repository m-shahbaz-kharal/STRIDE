from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
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
from .executor.cancellation import CancellationController as _CancellationController
from .executor.graph_builder import GraphBuilder
from .executor.control_flow import LoopHandler, IfElseHandler, BranchHandler
from .executor.node_execution import NodeExecutor
from .executor.streaming import StreamingExecutor
from .executor.utils import (
    normalize_type,
    collect_dependents,
    expand_dependencies,
    collect_downstream,
    collect_outputs,
    calculate_stats,
)


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
    def clear_cache_by_node(cls, node_id: str) -> int:
        """Clear cache entries for a specific node id. Returns number of entries cleared."""
        return ExecutionCache.clear_by_node(node_id)

    @classmethod
    def clear_cache_by_nodes(cls, node_ids: List[str]) -> int:
        """Clear cache entries for a list of node ids. Returns number of entries cleared."""
        return ExecutionCache.clear_by_nodes(node_ids)

    @classmethod
    def get_cache_size(cls) -> int:
        """Get the current number of cached entries."""
        return ExecutionCache.size()

    def __init__(self, graph_definition: Dict[str, Any], options: Optional[Dict[str, Any]] = None) -> None:
        self.definition = graph_definition
        self.options: Dict[str, Any] = options or {}
        self.execution_id = str(uuid.uuid4())[:8]
        # Per-graph worker cap. The old default of ``cpu_count() + 2``
        # blew up on 64-core boxes (66 threads per run × N concurrent
        # runs = thousands of OS threads). Default down to 8 to bound
        # total concurrency; ``STRIDE_MAX_WORKERS`` raises the ceiling
        # and ``options["max_workers"]`` overrides per-call.
        _env_default = int(os.getenv("STRIDE_MAX_WORKERS", "8"))
        self._max_workers = int(
            self.options.get(
                "max_workers",
                max(2, min(32, _env_default)),
            )
        )
        self._fail_fast = bool(self.options.get("fail_fast", True))

        # Build graph structure using GraphBuilder
        self._builder = GraphBuilder(graph_definition)
        self._builder.build()

        # Copy references from builder
        self.nodes: Dict[str, NodeBase] = self._builder.nodes
        self.links: List[Link] = self._builder.links
        self.input_map = self._builder.input_map
        self.control_inputs = self._builder.control_inputs
        self.control_outputs = self._builder.control_outputs
        self.output_map = self._builder.output_map
        self._dependents = self._builder.dependents

        # Compute topological order and levels
        self._topo_order = self._builder.topological_sort()
        self._node_levels, self._levels = self._builder.compute_levels(self._topo_order)

        # Initialize node status
        self._node_status: Dict[str, NodeStatus] = {node_id: NodeStatus.PENDING for node_id in self.nodes}

        # Execution state
        self._computed_values: Dict[str, Dict[str, Any]] = {}
        self._total_execution_time_ms: float = 0.0
        self._max_parallelism: int = 0
        self._state_lock = threading.Lock()
        self._thread_pool: Optional[ThreadPoolExecutor] = None
        self._cancellation = _CancellationController(self._state_lock)
        self._variables: Dict[str, Any] = {}
        self._shared_metadata: Dict[str, Any] = {}
        self._resources: List[Tuple[str, Any]] = []
        # Phase 2: per-run lifecycle bookkeeping. All dicts are owned here
        # and shared with every NodeExecutor created during the run so
        # prepare/forward/teardown observe the same state.
        self._node_resources_state: Dict[str, Dict[str, Any]] = {}
        self._prepared_nodes: Set[str] = set()
        # Phase 5: per-run, cross-node resource registry (shared model
        # caches, live FL511 streams, etc.). Released by the executor's
        # teardown step at run end.
        self._run_resources_state: Dict[str, Any] = {}
        self.execution_trace: List[NodeExecutionResult] = []
        self.outputs: Dict[str, Any] = {}

        # Caching options
        self._cache = ExecutionCache(enabled=self.options.get("use_cache", True))
        self._force_no_cache: Set[str] = set()

        # Build control flow handlers
        self._loop_handler = LoopHandler(self.nodes, self.control_outputs, self._topo_order)
        self._loop_handler.build_loop_sets()

        self._ifelse_handler = IfElseHandler(self.nodes, self.control_outputs, self._loop_handler)
        self._ifelse_handler.build_ifelse_sets()

        self._branch_handler = BranchHandler(self.nodes, self.control_outputs, self.input_map, self.links)
        self._branch_handler.build_branch_info()

        # Copy references from handlers for backwards compatibility
        self._loop_nodes = self._loop_handler.loop_nodes
        self._loop_body_nodes = self._loop_handler.loop_body_nodes
        self._nodes_in_loop_body = self._loop_handler.nodes_in_loop_body
        self._loop_parent = self._loop_handler.loop_parent

        self._ifelse_nodes = self._ifelse_handler.ifelse_nodes
        self._ifelse_true_branch = self._ifelse_handler.ifelse_true_branch
        self._ifelse_false_branch = self._ifelse_handler.ifelse_false_branch
        self._nodes_in_ifelse_branch = self._ifelse_handler.nodes_in_ifelse_branch
        self._skipped_branches: Set[str] = set()

        self._start_nodes = self._branch_handler.start_nodes
        self._branch_roots = self._branch_handler.branch_roots
        self._branches = self._branch_handler.branches
        self._merge_points = self._branch_handler.merge_points
        self._branch_completed: Dict[str, asyncio.Event] = {}

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
        # Just signal cancellation. The executor's finally block performs
        # resource cleanup. Calling _cleanup_resources() here would race with
        # nodes currently using those resources and could close them mid-read.
        executor._cancellation.cancel_all()
        return True

    @classmethod
    def cancel_node(cls, execution_id: str, node_id: str) -> bool:
        with cls._active_lock:
            executor = cls._active_executions.get(execution_id)
        if not executor:
            return False
        # Signal node-level cancellation; the streaming loop will pick it up
        # and finalize the node. Cleaning the resource is deferred to the
        # node's own finalization path (or the executor's finally block) to
        # avoid races with the worker thread still using it.
        executor._cancellation.cancel_node(node_id)
        return True

    def _reset_execution_state(self) -> None:
        """Reset per-run execution state so subsequent runs are isolated."""
        # IMPORTANT: Use .clear() instead of reassignment (= {}) to preserve
        # references held by NodeExecutor and other components
        self.execution_trace.clear()
        self.outputs.clear()
        self._computed_values.clear()
        self._variables.clear()
        self._shared_metadata.clear()
        self._resources.clear()
        self._skipped_branches.clear()
        self._cancellation.reset()
        # Phase 2: stateful trackers / model sessions must not leak across
        # runs. Both dicts are owned by the runner and shared with the
        # NodeExecutor; clearing here is the single source of truth.
        self._node_resources_state.clear()
        self._prepared_nodes.clear()
        # Phase 5: also reset the run-scoped resource registry.
        self._run_resources_state.clear()
        self._node_status = {node_id: NodeStatus.PENDING for node_id in self.nodes}

    def _cleanup_resources(self, target_node_id: Optional[str] = None) -> None:
        """Close and cleanup any registered resources.

        Phase 2: when called for whole-run cleanup (``target_node_id=None``),
        also runs ``teardown(ctx)`` for every node that completed ``prepare``
        in this run, then drops per-node ctx-acquired resources.
        """
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

        # Phase 2: whole-run teardown of prepared nodes. Single-node cleanup
        # (target_node_id) keeps the existing semantics — those resources are
        # the legacy ctx.register_resource path.
        if target_node_id is None:
            executor = self._create_node_executor()
            executor.teardown_prepared_nodes()

    def _create_node_executor(self) -> NodeExecutor:
        """Create a NodeExecutor instance with current state."""
        return NodeExecutor(
            nodes=self.nodes,
            node_levels=self._node_levels,
            input_map=self.input_map,
            control_inputs=self.control_inputs,
            cache=self._cache,
            cancellation=self._cancellation,
            computed_values=self._computed_values,
            node_status=self._node_status,
            variables=self._variables,
            shared_metadata=self._shared_metadata,
            resources=self._resources,
            state_lock=self._state_lock,
            force_no_cache=self._force_no_cache,
            node_resources_state=self._node_resources_state,
            prepared_nodes=self._prepared_nodes,
            run_resources_state=self._run_resources_state,
        )

    def _finalize_node_result(
        self,
        node_id: str,
        inputs: Dict[str, Any],
        result: NodeExecutionResult,
        cached: bool = False,
        allow_cache: bool = True,
    ) -> None:
        """Persist a node result back into executor state."""
        # In case of error, append details to logs for better visibility
        if result.status == NodeStatus.ERROR and result.error:
            separator = "=" * 40
            log_entry = f"\n{separator}\n[ERROR] {result.error}"
            if result.error_details:
                log_entry += f"\n\n[STACK TRACE]\n{result.error_details}\n{separator}"
            result.logs.append(log_entry)

        if result.status == NodeStatus.COMPLETED:
            executor = self._create_node_executor()
            if not cached and allow_cache:
                executor.cache_outputs(node_id, inputs, result.outputs)
            with self._state_lock:
                self._computed_values[node_id] = result.outputs
        self._node_status[node_id] = result.status
        self.execution_trace.append(result)
        self._cancellation.clear_running(node_id)

    def _should_interrupt(self, node_id: Optional[str] = None) -> bool:
        return self._cancellation.is_cancelled(node_id)

    def _should_stop_execution(self) -> bool:
        return self._cancellation.should_stop()

    def _resolve_execution_order(self) -> List[str]:
        """Resolve which nodes to execute based on options."""
        mode = str(self.options.get("mode", "full")).lower()
        self._force_no_cache = set(str(node_id) for node_id in (self.options.get("force_no_cache_nodes") or []))
        invalidate_nodes = [str(node_id) for node_id in (self.options.get("invalidate_cache_nodes") or [])]
        if invalidate_nodes:
            ExecutionCache.clear_by_nodes(invalidate_nodes)
        if mode == "selection":
            target_nodes = [node_id for node_id in (self.options.get("target_nodes") or []) if node_id in self.nodes]
            if target_nodes:
                allowed = expand_dependencies(target_nodes, self.nodes, self.input_map, self.control_inputs)
                return [
                    node_id
                    for node_id in self._topo_order
                    if node_id in allowed and node_id not in self._nodes_in_loop_body
                ]
        if mode in {"from_node", "from_nodes", "downstream"}:
            entry_nodes = [
                node_id
                for node_id in (self.options.get("entry_nodes") or self.options.get("target_nodes") or [])
                if node_id in self.nodes
            ]
            if entry_nodes:
                downstream = collect_downstream(entry_nodes, self.nodes, self._dependents)
                self._force_no_cache.update(downstream)
                allowed = expand_dependencies(list(downstream), self.nodes, self.input_map, self.control_inputs)
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

    def _execute_loop_sync(
        self,
        loop_id: str,
        executed_count: int,
        max_steps: Optional[int],
        breakpoints: Set[str],
        execution_set: Optional[Set[str]] = None,
    ) -> int:
        """Execute a loop node synchronously."""
        executor = self._create_node_executor()
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

        is_while = loop_node.type == "core.control.while"

        if loop_node.type == "core.control.for":
            inputs = executor.prepare_inputs(loop_id)
            first_index = int(inputs.get("first_index") or 0)
            last_index_input = int(inputs.get("last_index") or 0)
            step = 1 if last_index_input >= first_index else -1
            indices = range(first_index, last_index_input + step, step)
        elif not is_while:
            indices = range(0)
        else:
            indices = None

        idx = 0
        while True:
            if self._should_interrupt(loop_id) or self._should_stop_execution():
                interrupted = True
                break
            if _should_stop():
                break
            if loop_id in breakpoints:
                break

            if is_while:
                inputs = executor.prepare_inputs(loop_id)
                if not bool(inputs.get("condition")):
                    break
                idx = iterations
            elif loop_node.type == "core.control.for":
                inputs = executor.prepare_inputs(loop_id)
                first_index = int(inputs.get("first_index") or 0)
                last_index_input = int(inputs.get("last_index") or 0)
                step = 1 if last_index_input >= first_index else -1
                idx = first_index + iterations * step
                if step > 0 and idx > last_index_input:
                    break
                if step < 0 and idx < last_index_input:
                    break
            else:
                if iterations >= len(indices):
                    break
                idx = indices[iterations]

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
                    result = executor.make_interrupted_result(node_id)
                    self._finalize_node_result(node_id, {}, result, cached=False)
                    executed_count += 1
                    for dep in collect_dependents(node_id, self._dependents):
                        self._cancellation.cancel_node(dep)
                    continue
                if node_id in self._skipped_branches:
                    result = executor.make_interrupted_result(node_id)
                    self._finalize_node_result(node_id, {}, result, cached=False)
                    executed_count += 1
                    continue
                if self._loop_handler.is_loop_node(node_id):
                    executed_count = self._execute_loop_sync(
                        node_id,
                        executed_count,
                        max_steps,
                        breakpoints,
                        execution_set=execution_set,
                    )
                    continue
                if self._ifelse_handler.is_ifelse_node(node_id):
                    try:
                        inputs = executor.prepare_inputs(node_id)
                    except GraphExecutionError as exc:
                        result = executor.make_input_error_result(node_id, exc)
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

                inputs = executor.prepare_inputs(node_id)
                result = executor.execute_node_sync(
                    node_id, inputs, allow_cache=True,
                    finalize_callback=self._finalize_node_result
                )
                executed_count += 1
                if result.status == NodeStatus.ERROR:
                    break

        if interrupted:
            result = executor.make_interrupted_result(loop_id)
            self._finalize_node_result(loop_id, {}, result, cached=False)
            executed_count += 1
            # Skip dependents
            for dep in collect_dependents(loop_id, self._dependents):
                self._cancellation.cancel_node(dep)
                if execution_set is not None and dep not in execution_set:
                    continue
                if self._node_status.get(dep) != NodeStatus.PENDING:
                    continue
                dep_result = NodeExecutionResult(
                    node_id=dep,
                    node_type=self.nodes[dep].type,
                    status=NodeStatus.SKIPPED,
                    logs=[f"Dependency '{loop_id}' was interrupted"],
                    duration_ms=0.0,
                    level=self._node_levels.get(dep, 0),
                    from_cache=False,
                )
                self._finalize_node_result(dep, {}, dep_result, cached=False)
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
        executor = self._create_node_executor()

        executed_count = 0
        max_steps = self.options.get("max_steps")
        breakpoints: Set[str] = set(self.options.get("breakpoints") or [])

        start_time = time.perf_counter()

        for node_id in self._execution_order:
            if self._node_status.get(node_id) != NodeStatus.PENDING:
                continue
            if self._should_interrupt(node_id):
                result = executor.make_interrupted_result(node_id)
                self._finalize_node_result(node_id, {}, result, cached=False)
                executed_count += 1
                for dep in collect_dependents(node_id, self._dependents):
                    self._cancellation.cancel_node(dep)
                    if dep not in execution_set:
                        continue
                    if self._node_status.get(dep) != NodeStatus.PENDING:
                        continue
                    dep_result = NodeExecutionResult(
                        node_id=dep,
                        node_type=self.nodes[dep].type,
                        status=NodeStatus.SKIPPED,
                        logs=[f"Dependency '{node_id}' was interrupted"],
                        duration_ms=0.0,
                        level=self._node_levels.get(dep, 0),
                        from_cache=False,
                    )
                    self._finalize_node_result(dep, {}, dep_result, cached=False)
                    executed_count += 1
                continue
            if max_steps is not None and executed_count >= max_steps:
                break
            if node_id in breakpoints:
                break
            if node_id in self._skipped_branches:
                result = executor.make_interrupted_result(node_id)
                self._finalize_node_result(node_id, {}, result, cached=False)
                executed_count += 1
                continue

            if self._ifelse_handler.is_ifelse_node(node_id):
                try:
                    inputs = executor.prepare_inputs(node_id)
                except GraphExecutionError as exc:
                    result = executor.make_input_error_result(node_id, exc)
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

            if self._loop_handler.is_loop_node(node_id):
                executed_count = self._execute_loop_sync(
                    node_id,
                    executed_count,
                    max_steps,
                    breakpoints,
                    execution_set=execution_set,
                )
                continue

            inputs = executor.prepare_inputs(node_id)
            result = executor.execute_node_sync(
                node_id, inputs, allow_cache=True,
                finalize_callback=self._finalize_node_result
            )
            executed_count += 1

            if result.status == NodeStatus.ERROR:
                break

        total_time = (time.perf_counter() - start_time) * 1000

        self.outputs = collect_outputs(self.definition, self._computed_values)

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

        stats = calculate_stats(self.execution_trace, self._execution_order, total_time)

        return {
            "outputs": self.outputs,
            "trace": legacy_trace,
            "stats": stats.__dict__,
            "levels": self._levels,
            "execution_id": self.execution_id,
        }

    def run(self) -> Dict[str, Any]:
        """Execute the graph synchronously (legacy interface)."""
        # Register so /api/executions/{id}/cancel can target this run too.
        self._register_execution(self)
        try:
            return self._run_internal()
        finally:
            self._unregister_execution(self.execution_id)
            self._cleanup_resources()

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

        stats = calculate_stats(
            self.execution_trace,
            self._execution_order,
            self._total_execution_time_ms,
            self._max_parallelism
        )

        return {
            "outputs": self.outputs,
            "trace": legacy_trace,
            "stats": stats.__dict__,
            "levels": self._levels,
            "execution_id": self.execution_id,
        }

    async def run_streaming(self) -> AsyncIterator[ExecutionEvent]:
        """Execute the graph with real-time event streaming using readiness queue (no level barrier)."""
        # Bound the queue so a slow consumer (paused tab, congested
        # WebSocket) can't grow the buffer to GB-scale. Producers will
        # back-pressure naturally via ``await queue.put(...)`` once the
        # queue is full. Override via ``STRIDE_EVENT_QUEUE_MAX``.
        _queue_max = int(os.environ.get("STRIDE_EVENT_QUEUE_MAX", "2048"))
        event_queue: asyncio.Queue = asyncio.Queue(maxsize=max(64, _queue_max))

        streaming_executor = StreamingExecutor(
            executor=self._create_node_executor(),
            nodes=self.nodes,
            topo_order=self._topo_order,
            node_levels=self._node_levels,
            levels=self._levels,
            input_map=self.input_map,
            control_inputs=self.control_inputs,
            control_outputs=self.control_outputs,
            dependents=self._dependents,
            loop_handler=self._loop_handler,
            ifelse_handler=self._ifelse_handler,
            branch_handler=self._branch_handler,
            cancellation=self._cancellation,
            execution_id=self.execution_id,
            max_workers=self._max_workers,
            fail_fast=self._fail_fast,
            options=self.options,
            computed_values=self._computed_values,
            node_status=self._node_status,
            execution_trace=self.execution_trace,
            state_lock=self._state_lock,
            skipped_branches=self._skipped_branches,
            force_no_cache=self._force_no_cache,
            finalize_node_result=self._finalize_node_result,
            resolve_execution_order=self._resolve_execution_order,
            reset_execution_state=self._reset_execution_state,
            register_execution=lambda: self._register_execution(self),
            unregister_execution=lambda: self._unregister_execution(self.execution_id),
            cleanup_resources=self._cleanup_resources,
        )

        runner = asyncio.create_task(streaming_executor.run_streaming_ready_queue(event_queue))

        try:
            while True:
                event = await event_queue.get()
                if event is None:
                    break
                yield event
        finally:
            # Capture execution stats
            self._execution_order = streaming_executor.execution_order
            self._total_execution_time_ms = streaming_executor.total_execution_time_ms
            self._max_parallelism = streaming_executor.max_parallelism
            self.outputs = collect_outputs(self.definition, self._computed_values)

            if not runner.done():
                runner.cancel()
            try:
                await runner
            except Exception:
                pass

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

    # Backwards compatibility methods
    @staticmethod
    def _normalize_type(raw_type: Any) -> Optional[TypeDescriptor]:
        """Normalize type descriptors (backwards compatibility wrapper)."""
        return normalize_type(raw_type)

    def _is_loop_node(self, node_id: str) -> bool:
        """Check if node is a loop (backwards compatibility)."""
        return self._loop_handler.is_loop_node(node_id)

    def _is_ifelse_node(self, node_id: str) -> bool:
        """Check if node is an if/else (backwards compatibility)."""
        return self._ifelse_handler.is_ifelse_node(node_id)

    def _is_start_node(self, node_id: str) -> bool:
        """Check if node is a start node (backwards compatibility)."""
        return self._branch_handler.is_start_node(node_id)

    def _collect_dependents(self, node_id: str) -> Set[str]:
        """Collect transitive dependents (backwards compatibility)."""
        return collect_dependents(node_id, self._dependents)

    def _expand_dependencies(self, node_ids: List[str]) -> Set[str]:
        """Expand dependencies (backwards compatibility)."""
        return expand_dependencies(node_ids, self.nodes, self.input_map, self.control_inputs)

    def _collect_downstream(self, node_ids: List[str]) -> Set[str]:
        """Collect downstream nodes (backwards compatibility)."""
        return collect_downstream(node_ids, self.nodes, self._dependents)

    def _collect_outputs(self) -> Dict[str, Any]:
        """Collect outputs (backwards compatibility)."""
        return collect_outputs(self.definition, self._computed_values)

    def _calculate_stats(self, total_time_ms: float, max_parallelism: int = 1) -> ExecutionStats:
        """Calculate stats (backwards compatibility)."""
        return calculate_stats(self.execution_trace, self._execution_order, total_time_ms, max_parallelism)
