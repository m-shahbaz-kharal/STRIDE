"""
Streaming execution for graph execution.

Handles async streaming execution with events, parallel branches, and ready-queue scheduling.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import defaultdict, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from ..execution import ExecutionEvent, NodeExecutionResult, NodeStatus
    from .node_execution import NodeExecutor
    from .control_flow import LoopHandler, IfElseHandler, BranchHandler
    from .cancellation import CancellationController


class StreamingExecutor:
    """Executes graphs with streaming events."""

    def __init__(
        self,
        executor: "NodeExecutor",
        nodes: Dict[str, Any],
        topo_order: List[str],
        node_levels: Dict[str, int],
        levels: List[List[str]],
        input_map: Dict[str, Dict[str, Any]],
        control_inputs: Dict[str, List[tuple]],
        control_outputs: Dict[str, List[tuple]],
        dependents: Dict[str, List[str]],
        loop_handler: "LoopHandler",
        ifelse_handler: "IfElseHandler",
        branch_handler: "BranchHandler",
        cancellation: "CancellationController",
        execution_id: str,
        max_workers: int,
        fail_fast: bool,
        options: Dict[str, Any],
        computed_values: Dict[str, Dict[str, Any]],
        node_status: Dict[str, Any],
        execution_trace: List[Any],
        state_lock: threading.Lock,
        skipped_branches: Set[str],
        force_no_cache: Set[str],
        finalize_node_result: Any,
        resolve_execution_order: Any,
        reset_execution_state: Any,
        register_execution: Any,
        unregister_execution: Any,
        cleanup_resources: Any,
    ) -> None:
        """Initialize the streaming executor."""
        self.executor = executor
        self.nodes = nodes
        self.topo_order = topo_order
        self.node_levels = node_levels
        self.levels = levels
        self.input_map = input_map
        self.control_inputs = control_inputs
        self.control_outputs = control_outputs
        self.dependents = dependents
        self.loop_handler = loop_handler
        self.ifelse_handler = ifelse_handler
        self.branch_handler = branch_handler
        self.cancellation = cancellation
        self.execution_id = execution_id
        self.max_workers = max_workers
        self.fail_fast = fail_fast
        self.options = options
        self.computed_values = computed_values
        self.node_status = node_status
        self.execution_trace = execution_trace
        self.state_lock = state_lock
        self.skipped_branches = skipped_branches
        self.force_no_cache = force_no_cache
        self.finalize_node_result = finalize_node_result
        self.resolve_execution_order = resolve_execution_order
        self.reset_execution_state = reset_execution_state
        self.register_execution = register_execution
        self.unregister_execution = unregister_execution
        self.cleanup_resources = cleanup_resources

        self._execution_order: List[str] = []
        self._thread_pool: Optional[ThreadPoolExecutor] = None
        self._total_execution_time_ms: float = 0.0
        self._max_parallelism: int = 0

    def _should_interrupt(self, node_id: Optional[str] = None) -> bool:
        return self.cancellation.is_cancelled(node_id)

    def _should_stop_execution(self) -> bool:
        return self.cancellation.should_stop()

    def _record_interrupted(
        self,
        node_id: str,
        inputs: Optional[Dict[str, Any]] = None,
        allow_cache: bool = False,
    ) -> "NodeExecutionResult":
        result = self.executor.make_interrupted_result(node_id)
        self.finalize_node_result(node_id, inputs or {}, result, cached=False, allow_cache=allow_cache)
        return result

    def _cancel_dependents(self, node_id: str) -> None:
        from .utils import collect_dependents
        for dep in collect_dependents(node_id, self.dependents):
            self.cancellation.cancel_node(dep)

    def _record_skipped_dependents(
        self,
        node_id: str,
        reason: str,
        execution_set: Optional[Set[str]] = None,
    ) -> List["NodeExecutionResult"]:
        from ..execution import NodeExecutionResult, NodeStatus
        from .utils import collect_dependents

        results: List[NodeExecutionResult] = []
        for dep in collect_dependents(node_id, self.dependents):
            self.cancellation.cancel_node(dep)
            if execution_set is not None and dep not in execution_set:
                continue
            if self.node_status.get(dep) != NodeStatus.PENDING:
                continue
            result = NodeExecutionResult(
                node_id=dep,
                node_type=self.nodes[dep].type,
                status=NodeStatus.SKIPPED,
                logs=[reason],
                duration_ms=0.0,
                level=self.node_levels.get(dep, 0),
                from_cache=False,
            )
            self.finalize_node_result(dep, {}, result, cached=False)
            results.append(result)
        return results

    def _mark_pending_interrupted(self, execution_set: Set[str]) -> List["NodeExecutionResult"]:
        from ..execution import NodeStatus
        results: List["NodeExecutionResult"] = []
        for node_id in execution_set:
            if self.node_status.get(node_id) != NodeStatus.PENDING:
                continue
            results.append(self._record_interrupted(node_id))
        return results

    async def run_streaming_ready_queue(self, event_queue: asyncio.Queue) -> None:
        """Execute the graph with readiness-based scheduling and emit events to a queue."""
        from ..execution import ExecutionEvent, NodeExecutionResult, NodeStatus

        self._execution_order = self.resolve_execution_order()
        execution_set = set(self._execution_order)
        self.reset_execution_state()

        max_steps = self.options.get("max_steps")
        breakpoints: Set[str] = set(self.options.get("breakpoints") or [])

        total_nodes = len(self._execution_order)
        progress_state = {"total": total_nodes, "completed": 0, "lock": threading.Lock()}
        executed_count = 0
        max_parallelism = 0
        loop = asyncio.get_running_loop()
        self._thread_pool = ThreadPoolExecutor(max_workers=self.max_workers)
        self.register_execution()

        execution_plan = [
            {
                "node_id": node_id,
                "node_type": self.nodes[node_id].type,
                "level": self.node_levels.get(node_id, 0),
                "branch_id": self.branch_handler.branch_roots.get(node_id),
                "is_merge_point": node_id in self.branch_handler.merge_points,
            }
            for node_id in self._execution_order
        ]

        branches_dict = {
            branch_id: list(node_ids)
            for branch_id, node_ids in self.branch_handler.branches.items()
        } if self.branch_handler.branches else None

        await event_queue.put(ExecutionEvent(
            event_type="start",
            execution_id=self.execution_id,
            timestamp=time.time(),
            total_nodes=total_nodes,
            execution_plan=execution_plan,
            levels=self.levels,
            branches=branches_dict,
            merge_points=list(self.branch_handler.merge_points) if self.branch_handler.merge_points else None,
        ))

        remaining_inputs: Dict[str, int] = {
            node_id: len(self.input_map.get(node_id, {})) + len(self.control_inputs.get(node_id, []))
            for node_id in execution_set
        }
        ready: deque[str] = deque([nid for nid, deg in remaining_inputs.items() if deg == 0])
        
        tasks: Dict[asyncio.Task[Any], Tuple[str, Optional[Dict[str, Any]], str]] = {}
        pending_interrupted = False
        stop_scheduling = False

        async def _propagate_failure(
            failed_id: str,
            reason: str,
            status: NodeStatus = NodeStatus.ERROR,
        ) -> None:
            """Mark downstream nodes as skipped/errors."""
            nonlocal ready
            stack = list(self.dependents.get(failed_id, []))
            visited: Set[str] = set()
            while stack:
                dep = stack.pop()
                if dep in visited:
                    continue
                visited.add(dep)
                if dep in execution_set:
                    if remaining_inputs.get(dep, 0) < 0:
                        stack.extend(self.dependents.get(dep, []))
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
                        level=self.node_levels.get(dep, 0),
                        from_cache=False,
                    )
                    self.finalize_node_result(dep, {}, result, cached=False)
                    with progress_state["lock"]:
                        progress_state["completed"] += 1
                        completed = progress_state["completed"]
                        total = progress_state["total"]
                    await event_queue.put(ExecutionEvent(
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
                        progress=completed / total if total > 0 else 0,
                        total_nodes=total,
                        completed_nodes=completed,
                        from_cache=False,
                    ))
                stack.extend(self.dependents.get(dep, []))

        def _enqueue_dependents(source_id: str) -> None:
            for dep in self.dependents.get(source_id, []):
                if dep not in execution_set:
                    continue
                if remaining_inputs.get(dep, 0) < 0:
                    continue
                remaining_inputs[dep] -= 1
                if remaining_inputs[dep] == 0:
                    ready.append(dep)

        def _enqueue_loop_body_dependents(loop_id: str) -> None:
            for body_id in self.loop_handler.loop_body_nodes.get(loop_id, set()):
                if self.loop_handler.loop_parent.get(body_id) != loop_id:
                    continue
                _enqueue_dependents(body_id)

        async def _run_loop_task(loop_id: str) -> None:
            async for event in self._execute_loop_streaming(
                loop_id,
                event_queue,
                progress_state,
                execution_set=execution_set,
            ):
                await event_queue.put(event)

        start_time = time.perf_counter()

        try:
            while ready or tasks:
                if stop_scheduling:
                    ready.clear()
                if self._should_stop_execution():
                    if not pending_interrupted:
                        for skipped in self._mark_pending_interrupted(execution_set):
                            with progress_state["lock"]:
                                progress_state["completed"] += 1
                                completed = progress_state["completed"]
                                total = progress_state["total"]
                            await event_queue.put(ExecutionEvent(
                                event_type="node_skipped",
                                execution_id=self.execution_id,
                                timestamp=time.time(),
                                node_id=skipped.node_id,
                                node_type=skipped.node_type,
                                status=NodeStatus.SKIPPED,
                                level=skipped.level,
                                progress=completed / total if total > 0 else 0,
                                total_nodes=total,
                                completed_nodes=completed,
                            ))
                        pending_interrupted = True
                    for pending in tasks.keys():
                        pending.cancel()
                    ready.clear()
                else:
                    while ready and len(tasks) < self.max_workers:
                        node_id = ready.popleft()
                        if self.node_status.get(node_id) != NodeStatus.PENDING:
                            continue
                        if max_steps is not None and executed_count >= max_steps:
                            stop_scheduling = True
                            ready.clear()
                            break
                        if node_id in breakpoints:
                            stop_scheduling = True
                            ready.clear()
                            break
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
                            await _propagate_failure(
                                node_id,
                                f"Dependency '{node_id}' was interrupted",
                                status=NodeStatus.SKIPPED,
                            )
                            continue

                        if node_id in self.skipped_branches:
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
                                logs=["Skipped: If/Else condition was False"],
                                level=skipped.level,
                                progress=completed / total if total > 0 else 0,
                                total_nodes=total,
                                completed_nodes=completed,
                            ))
                            _enqueue_dependents(node_id)
                            continue

                        if self.ifelse_handler.is_ifelse_node(node_id):
                            try:
                                inputs = self.executor.prepare_inputs(node_id)
                            except Exception as exc:
                                result = self.executor.make_input_error_result(node_id, exc)
                                self.finalize_node_result(node_id, {}, result, cached=False)
                                with progress_state["lock"]:
                                    progress_state["completed"] += 1
                                    completed = progress_state["completed"]
                                    total = progress_state["total"]
                                executed_count += 1
                                await event_queue.put(ExecutionEvent(
                                    event_type="node_error",
                                    execution_id=self.execution_id,
                                    timestamp=time.time(),
                                    node_id=node_id,
                                    node_type=result.node_type,
                                    status=NodeStatus.ERROR,
                                    error=result.error,
                                    error_code=result.error_code,
                                    error_details=result.error_details,
                                    duration_ms=result.duration_ms,
                                    level=result.level,
                                    progress=completed / total if total > 0 else 0,
                                    total_nodes=total,
                                    completed_nodes=completed,
                                    from_cache=result.from_cache,
                                ))
                                await _propagate_failure(
                                    node_id,
                                    f"Dependency '{node_id}' failed",
                                    status=NodeStatus.ERROR,
                                )
                                continue

                            true_nodes = self.ifelse_handler.ifelse_true_branch.get(node_id, set())
                            false_nodes = self.ifelse_handler.ifelse_false_branch.get(node_id, set())
                            self.skipped_branches -= true_nodes
                            self.skipped_branches -= false_nodes

                            condition = bool(inputs.get("condition", False))
                            if condition:
                                self.skipped_branches.update(false_nodes)
                            else:
                                self.skipped_branches.update(true_nodes)

                            ifelse_outputs = {"true": None, "false": None}
                            result = NodeExecutionResult(
                                node_id=node_id,
                                node_type=self.nodes[node_id].type,
                                status=NodeStatus.COMPLETED,
                                outputs=ifelse_outputs,
                                logs=[f"Condition evaluated to {condition}"],
                                duration_ms=0.0,
                                level=self.node_levels.get(node_id, 0),
                                from_cache=False,
                            )
                            self.finalize_node_result(node_id, inputs, result, cached=False)
                            with progress_state["lock"]:
                                progress_state["completed"] += 1
                                completed = progress_state["completed"]
                                total = progress_state["total"]
                            executed_count += 1
                            await event_queue.put(ExecutionEvent(
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
                                progress=completed / total if total > 0 else 0,
                                total_nodes=total,
                                completed_nodes=completed,
                                from_cache=False,
                            ))
                            _enqueue_dependents(node_id)
                            continue

                        node = self.nodes[node_id]
                        with progress_state["lock"]:
                            total = progress_state["total"]
                            completed = progress_state["completed"]
                        await event_queue.put(ExecutionEvent(
                            event_type="node_queued",
                            execution_id=self.execution_id,
                            timestamp=time.time(),
                            node_id=node_id,
                            node_type=node.type,
                            status=NodeStatus.QUEUED,
                            level=self.node_levels.get(node_id, 0),
                            progress=completed / total if total > 0 else 0,
                            total_nodes=total,
                            completed_nodes=completed,
                        ))

                        if self.loop_handler.is_loop_node(node_id):
                            loop_task = asyncio.create_task(_run_loop_task(node_id))
                            tasks[loop_task] = (node_id, None, "loop")
                            self.cancellation.register_running(node_id, loop_task)
                            executed_count += 1
                            continue

                        try:
                            inputs = self.executor.prepare_inputs(node_id)
                        except Exception as exc:
                            result = self.executor.make_input_error_result(node_id, exc)
                            self.finalize_node_result(node_id, {}, result, cached=False)
                            with progress_state["lock"]:
                                progress_state["completed"] += 1
                                completed = progress_state["completed"]
                                total = progress_state["total"]
                            executed_count += 1
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
                            await _propagate_failure(
                                node_id,
                                f"Dependency '{node_id}' failed",
                                status=NodeStatus.ERROR,
                            )
                            continue

                        cached_outputs = self.executor.try_get_cached(node_id, inputs)

                        if cached_outputs is not None:
                            cached_start = time.perf_counter()
                            result = NodeExecutionResult(
                                node_id=node_id,
                                node_type=node.type,
                                status=NodeStatus.COMPLETED,
                                outputs=cached_outputs,
                                logs=["[CACHED] Skipped execution, using cached result"],
                                start_time=cached_start,
                                end_time=cached_start,
                                duration_ms=0.0,
                                level=self.node_levels.get(node_id, 0),
                                from_cache=True,
                            )
                            self.finalize_node_result(node_id, inputs, result, cached=True)
                            with progress_state["lock"]:
                                progress_state["completed"] += 1
                                completed = progress_state["completed"]
                                total = progress_state["total"]
                            executed_count += 1
                            await event_queue.put(ExecutionEvent(
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
                                progress=completed / total if total > 0 else 0,
                                total_nodes=total,
                                completed_nodes=completed,
                                from_cache=True,
                            ))
                            _enqueue_dependents(node_id)
                            continue

                        self.node_status[node_id] = NodeStatus.RUNNING
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
                            level=self.node_levels.get(node_id, 0),
                            progress=completed / total if total > 0 else 0,
                            total_nodes=total,
                            completed_nodes=completed,
                        ))

                        future = loop.run_in_executor(self._thread_pool, self.executor.execute_node_work, node_id, inputs)
                        task = asyncio.wrap_future(future)
                        tasks[task] = (node_id, inputs, "node")
                        self.cancellation.register_running(node_id, task)
                        executed_count += 1

                max_parallelism = max(max_parallelism, len(tasks) or 1 if executed_count else 0)

                if not tasks:
                    break

                done, _ = await asyncio.wait(tasks.keys(), return_when=FIRST_COMPLETED)
                for task in done:
                    node_id, inputs, kind = tasks.pop(task)
                    if kind == "loop":
                        try:
                            task.result()
                        except asyncio.CancelledError:
                            if self.node_status.get(node_id) == NodeStatus.PENDING:
                                loop_result = self._record_interrupted(node_id)
                                with progress_state["lock"]:
                                    progress_state["completed"] += 1
                                    completed = progress_state["completed"]
                                    total = progress_state["total"]
                                await event_queue.put(ExecutionEvent(
                                    event_type="node_skipped",
                                    execution_id=self.execution_id,
                                    timestamp=time.time(),
                                    node_id=node_id,
                                    node_type=loop_result.node_type,
                                    status=NodeStatus.SKIPPED,
                                    logs=loop_result.logs,
                                    duration_ms=loop_result.duration_ms,
                                    level=loop_result.level,
                                    progress=completed / total if total > 0 else 0,
                                    total_nodes=total,
                                    completed_nodes=completed,
                                    from_cache=False,
                                ))
                        except Exception as exc:
                            if self.node_status.get(node_id) == NodeStatus.PENDING:
                                result = NodeExecutionResult(
                                    node_id=node_id,
                                    node_type=self.nodes[node_id].type,
                                    status=NodeStatus.ERROR,
                                    error=str(exc),
                                    error_code="loop_error",
                                    duration_ms=0.0,
                                    level=self.node_levels.get(node_id, 0),
                                    from_cache=False,
                                )
                                self.finalize_node_result(node_id, {}, result, cached=False)
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
                                    error_details=result.error_details,
                                    duration_ms=result.duration_ms,
                                    level=result.level,
                                    progress=completed / total if total > 0 else 0,
                                    total_nodes=total,
                                    completed_nodes=completed,
                                    from_cache=False,
                                ))
                        status = self.node_status.get(node_id, NodeStatus.SKIPPED)
                        if status != NodeStatus.COMPLETED:
                            status_to_use = NodeStatus.ERROR if status == NodeStatus.ERROR else NodeStatus.SKIPPED
                            reason = (
                                f"Dependency '{node_id}' failed"
                                if status_to_use == NodeStatus.ERROR
                                else f"Dependency '{node_id}' was interrupted"
                            )
                            await _propagate_failure(node_id, reason, status=status_to_use)
                        _enqueue_dependents(node_id)
                        _enqueue_loop_body_dependents(node_id)
                        continue

                    try:
                        result = task.result()
                    except asyncio.CancelledError:
                        result = self.executor.make_interrupted_result(node_id)
                    self.finalize_node_result(node_id, inputs or {}, result, cached=False)
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
                    else:
                        await event_queue.put(ExecutionEvent(
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
                            progress=completed / total if total > 0 else 0,
                            total_nodes=total,
                            completed_nodes=completed,
                            from_cache=result.from_cache,
                        ))

                    if result.status != NodeStatus.COMPLETED:
                        status = NodeStatus.ERROR if result.status == NodeStatus.ERROR else NodeStatus.SKIPPED
                        reason = (
                            f"Dependency '{result.node_id}' failed"
                            if status == NodeStatus.ERROR
                            else f"Dependency '{result.node_id}' was interrupted"
                        )
                        await _propagate_failure(result.node_id, reason, status=status)

                    _enqueue_dependents(node_id)

                await asyncio.sleep(0)

        except Exception as exc:
            await event_queue.put(ExecutionEvent(
                event_type="error",
                execution_id=self.execution_id,
                timestamp=time.time(),
                error=str(exc),
                error_code="execution_error",
            ))

        finally:
            if self._thread_pool:
                self._thread_pool.shutdown(wait=False)
                self._thread_pool = None
            self.cleanup_resources()
            self.unregister_execution()

            if max_parallelism == 0 and executed_count > 0:
                max_parallelism = 1

            total_time = (time.perf_counter() - start_time) * 1000
            self._total_execution_time_ms = total_time
            self._max_parallelism = max_parallelism

            with progress_state["lock"]:
                completed = progress_state["completed"]
                total = progress_state["total"]

            await event_queue.put(ExecutionEvent(
                event_type="complete",
                execution_id=self.execution_id,
                timestamp=time.time(),
                progress=1.0,
                total_nodes=total,
                completed_nodes=completed,
            ))

            await event_queue.put(None)

    async def _execute_loop_streaming(
        self,
        node_id: str,
        event_queue: asyncio.Queue,
        progress_state: Dict[str, Any],
        execution_set: Optional[Set[str]] = None,
        adjust_total: bool = True,
    ) -> AsyncIterator["ExecutionEvent"]:
        """Execute a loop node, yielding events for each iteration."""
        from ..execution import ExecutionEvent, NodeExecutionResult, NodeStatus

        loop_node = self.nodes[node_id]
        body_nodes = self.loop_handler.loop_body_nodes.get(node_id, set())
        body_order = [nid for nid in self.topo_order if nid in body_nodes]

        iterations = 0
        last_index = 0

        is_while = loop_node.type == "core.control.while"
        indices: Any = None

        if loop_node.type == "core.control.for":
            inputs = self.executor.prepare_inputs(node_id)
            first_index = int(inputs.get("first_index") or 0)
            last_index_input = int(inputs.get("last_index") or 0)
            step = 1 if last_index_input >= first_index else -1
            indices = range(first_index, last_index_input + step, step)
        elif not is_while:
            indices = range(0)  # unknown loop type — skip

        if adjust_total and indices is not None:
            additional = len(indices) * len(body_order)
            if additional:
                with progress_state["lock"]:
                    progress_state["total"] += additional

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
            level=self.node_levels.get(node_id, 0),
            progress=completed / total if total > 0 else 0,
            total_nodes=total,
            completed_nodes=completed,
        )

        loop = asyncio.get_running_loop()

        loop_interrupted = False
        idx = 0
        idx_iter = iter(indices) if indices is not None else iter(range(0))

        while True:
            if self._should_interrupt(node_id):
                loop_interrupted = True
                break
            if self._should_stop_execution():
                break

            if is_while:
                # Re-read condition every iteration
                inputs = self.executor.prepare_inputs(node_id)
                if not bool(inputs.get("condition")):
                    break
                idx = iterations
                # Dynamically adjust progress total for the new iteration
                if body_order:
                    with progress_state["lock"]:
                        progress_state["total"] += len(body_order)
            else:
                # For loop: re-read bounds each iteration
                if loop_node.type == "core.control.for":
                    inputs = self.executor.prepare_inputs(node_id)
                    first_index = int(inputs.get("first_index") or 0)
                    last_index_input = int(inputs.get("last_index") or 0)
                    step = 1 if last_index_input >= first_index else -1
                    idx = first_index + iterations * step
                    if step > 0 and idx > last_index_input:
                        break
                    if step < 0 and idx < last_index_input:
                        break
                else:
                    try:
                        idx = next(idx_iter)
                    except StopIteration:
                        break

            self.computed_values[node_id] = {"loop_body": None, "index": idx, "completed": None}
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
                    self._cancel_dependents(body_id)
                    continue

                if body_id in self.skipped_branches:
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
                        logs=["Skipped: If/Else condition was False"],
                        level=skipped.level,
                        progress=completed / total if total > 0 else 0,
                        total_nodes=total,
                        completed_nodes=completed,
                    )
                    continue

                # Handle nested loops by recursive streaming execution
                if self.loop_handler.is_loop_node(body_id):
                    async for nested_event in self._execute_loop_streaming(
                        body_id,
                        event_queue,
                        progress_state,
                        execution_set=execution_set,
                        adjust_total=True,
                    ):
                        yield nested_event
                    # Check if nested loop failed
                    nested_status = self.node_status.get(body_id)
                    if nested_status == NodeStatus.ERROR:
                        if self.fail_fast:
                            loop_interrupted = True
                            break
                    continue

                # Handle if/else in loop body
                if self.ifelse_handler.is_ifelse_node(body_id):
                    try:
                        inputs = self.executor.prepare_inputs(body_id)
                    except Exception as exc:
                        result = self.executor.make_input_error_result(body_id, exc)
                        self.finalize_node_result(body_id, {}, result, cached=False)
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
                        if self.fail_fast:
                            loop_interrupted = True
                            break
                        continue

                    true_nodes = self.ifelse_handler.ifelse_true_branch.get(body_id, set())
                    false_nodes = self.ifelse_handler.ifelse_false_branch.get(body_id, set())
                    self.skipped_branches -= true_nodes
                    self.skipped_branches -= false_nodes

                    condition = bool(inputs.get("condition", False))
                    if condition:
                        self.skipped_branches.update(false_nodes)
                    else:
                        self.skipped_branches.update(true_nodes)

                    ifelse_outputs = {"true": None, "false": None}
                    result = NodeExecutionResult(
                        node_id=body_id,
                        node_type=self.nodes[body_id].type,
                        status=NodeStatus.COMPLETED,
                        outputs=ifelse_outputs,
                        logs=[f"[loop {idx}] Condition evaluated to {condition}"],
                        duration_ms=0.0,
                        level=self.node_levels.get(body_id, 0),
                        from_cache=False,
                    )
                    self.finalize_node_result(body_id, inputs, result, cached=False)
                    with progress_state["lock"]:
                        progress_state["completed"] += 1
                        completed = progress_state["completed"]
                        total = progress_state["total"]
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
                        progress=completed / total if total > 0 else 0,
                        total_nodes=total,
                        completed_nodes=completed,
                        from_cache=False,
                    )
                    continue

                # Regular body node execution
                try:
                    inputs = self.executor.prepare_inputs(body_id)
                except Exception as exc:
                    result = self.executor.make_input_error_result(body_id, exc)
                    self.finalize_node_result(body_id, {}, result, cached=False)
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
                    if self.fail_fast:
                        loop_interrupted = True
                        break
                    continue

                cached_outputs = self.executor.try_get_cached(body_id, inputs)
                if cached_outputs is not None:
                    cached_start = time.perf_counter()
                    result = NodeExecutionResult(
                        node_id=body_id,
                        node_type=self.nodes[body_id].type,
                        status=NodeStatus.COMPLETED,
                        outputs=cached_outputs,
                        logs=[f"[loop {idx}] [CACHED] Skipped execution, using cached result"],
                        start_time=cached_start,
                        end_time=cached_start,
                        duration_ms=0.0,
                        level=self.node_levels.get(body_id, 0),
                        from_cache=True,
                    )
                    self.finalize_node_result(body_id, inputs, result, cached=True)
                    with progress_state["lock"]:
                        progress_state["completed"] += 1
                        completed = progress_state["completed"]
                        total = progress_state["total"]
                    yield ExecutionEvent(
                        event_type="node_cached",
                        execution_id=self.execution_id,
                        timestamp=time.time(),
                        node_id=body_id,
                        node_type=self.nodes[body_id].type,
                        status=NodeStatus.COMPLETED,
                        outputs=result.outputs,
                        logs=result.logs,
                        duration_ms=result.duration_ms,
                        level=result.level,
                        progress=completed / total if total > 0 else 0,
                        total_nodes=total,
                        completed_nodes=completed,
                        from_cache=True,
                    )
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
                    level=self.node_levels.get(body_id, 0),
                    progress=completed / total if total > 0 else 0,
                    total_nodes=total,
                    completed_nodes=completed,
                )

                future = loop.run_in_executor(
                    self._thread_pool,
                    self.executor.execute_node_work,
                    body_id,
                    inputs
                )
                task = asyncio.wrap_future(future)
                self.cancellation.register_running(body_id, task)
                try:
                    result = await task
                except asyncio.CancelledError:
                    result = self.executor.make_interrupted_result(body_id)
                result.logs = [f"[loop {idx}] {log}" for log in result.logs] or [f"[loop {idx}]"]
                self.finalize_node_result(body_id, inputs, result, cached=False)

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
                    if self.fail_fast:
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
                    if result.status == NodeStatus.SKIPPED:
                        self._cancel_dependents(body_id)

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
            for dep in self._record_skipped_dependents(
                node_id,
                f"Dependency '{node_id}' was interrupted",
                execution_set=execution_set,
            ):
                with progress_state["lock"]:
                    progress_state["completed"] += 1
                    completed = progress_state["completed"]
                    total = progress_state["total"]
                yield ExecutionEvent(
                    event_type="node_skipped",
                    execution_id=self.execution_id,
                    timestamp=time.time(),
                    node_id=dep.node_id,
                    node_type=dep.node_type,
                    status=NodeStatus.SKIPPED,
                    logs=dep.logs,
                    duration_ms=dep.duration_ms,
                    level=dep.level,
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
                level=self.node_levels.get(node_id, 0),
                from_cache=False,
            )
            self.finalize_node_result(node_id, {}, loop_result, cached=False)

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

    @property
    def total_execution_time_ms(self) -> float:
        return self._total_execution_time_ms

    @property
    def max_parallelism(self) -> int:
        return self._max_parallelism

    @property
    def execution_order(self) -> List[str]:
        return self._execution_order


__all__ = ["StreamingExecutor"]
