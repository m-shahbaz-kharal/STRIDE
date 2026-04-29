"""
Node execution and caching for graph execution.

Handles individual node execution, caching, and loop iteration.

Phase 2 (§5.2 / §6.2): the exception path dispatches on ``NodeError``
subclasses to attach a structured ``error_payload`` (code/port/details) to
``NodeExecutionResult`` and surface it through the streaming WS event. Any
untyped ``Exception`` is wrapped into ``NodeRuntimeError`` so the runtime
contract — "system never crashes" — is upheld.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Set, TYPE_CHECKING

from stride_core.errors import (
    NodeCancelled,
    NodeError,
    NodeFileNotFoundError,
    NodeInputError,
    NodeMissingDependencyError,
    NodeNetworkError,
    NodeRuntimeError,
    NodeTypeError,
)

from .utils import normalize_type

if TYPE_CHECKING:
    from ..execution import ExecutionCache, NodeExecutionResult, NodeStatus
    from ..nodes import ExecutionContext, NodeBase
    from .cancellation import CancellationController


def _build_error_payload(
    exc: BaseException,
    *,
    node_id: str,
    node_type: str,
    traceback_str: Optional[str] = None,
) -> Dict[str, Any]:
    """Convert an exception into the structured ``error_payload`` dict
    documented in §6.3.

    Untyped exceptions are folded into ``NodeRuntimeError`` semantics with
    code ``"internal_error"`` so the frontend always receives the same
    shape.
    """
    if isinstance(exc, NodeError):
        payload: Dict[str, Any] = {
            "code": exc.code,
            "message": exc.message or str(exc) or exc.__class__.__name__,
            "node_id": exc.node_id or node_id,
            "node_type": node_type,
            "port": exc.port,
            "details": dict(exc.details) if exc.details else {},
        }
    else:
        payload = {
            "code": "internal_error",
            "message": str(exc) or exc.__class__.__name__,
            "node_id": node_id,
            "node_type": node_type,
            "port": None,
            "details": {"exception_type": exc.__class__.__name__},
        }
    if traceback_str:
        payload["details"].setdefault("traceback", traceback_str)
    return payload


class NodeExecutor:
    """Executes individual nodes with caching support."""

    def __init__(
        self,
        nodes: Dict[str, "NodeBase"],
        node_levels: Dict[str, int],
        input_map: Dict[str, Dict[str, Any]],
        control_inputs: Dict[str, List[tuple]],
        cache: "ExecutionCache",
        cancellation: "CancellationController",
        computed_values: Dict[str, Dict[str, Any]],
        node_status: Dict[str, "NodeStatus"],
        variables: Dict[str, Any],
        shared_metadata: Dict[str, Any],
        resources: List[tuple],
        state_lock: Any,
        force_no_cache: Set[str],
        node_resources_state: Optional[Dict[str, Dict[str, Any]]] = None,
        prepared_nodes: Optional[Set[str]] = None,
    ) -> None:
        """Initialize the node executor.

        Args:
            nodes: All nodes in the graph
            node_levels: Mapping of node_id -> execution level
            input_map: Mapping of node_id -> port -> Link
            control_inputs: Mapping of node_id -> [(parent_id, port)]
            cache: Execution cache instance
            cancellation: Cancellation controller
            computed_values: Mapping of node_id -> port -> computed value
            node_status: Mapping of node_id -> NodeStatus
            variables: Shared variables between nodes
            shared_metadata: Shared metadata between nodes
            resources: List of (node_id, resource) tuples for cleanup
            state_lock: Thread lock for state mutations
            force_no_cache: Set of node IDs to skip cache for
        """
        self.nodes = nodes
        self.node_levels = node_levels
        self.input_map = input_map
        self.control_inputs = control_inputs
        self.cache = cache
        self.cancellation = cancellation
        self.computed_values = computed_values
        self.node_status = node_status
        self.variables = variables
        self.shared_metadata = shared_metadata
        self.resources = resources
        self.state_lock = state_lock
        self.force_no_cache = force_no_cache
        # Phase 2: per-run, per-node lifecycle bookkeeping. The runner owns
        # the underlying dicts so they survive across NodeExecutor recreation
        # but are scoped to a single execution run.
        self.node_resources_state: Dict[str, Dict[str, Any]] = (
            node_resources_state if node_resources_state is not None else {}
        )
        self.prepared_nodes: Set[str] = prepared_nodes if prepared_nodes is not None else set()

    def can_cache(self, node_id: str) -> bool:
        """Check if a node's outputs can be cached.

        Args:
            node_id: The node ID

        Returns:
            True if the node can be cached
        """
        node = self.nodes[node_id]
        if node.type.startswith("core.control"):
            return False
        spec = getattr(node, "spec", None)
        tags = getattr(spec, "tags", None) or []
        if "control" in tags:
            return False
        return bool(getattr(node, "cache_enabled", False))

    def cache_params(self, node_id: str) -> Dict[str, Any]:
        """Get cache parameters for a node.

        Args:
            node_id: The node ID

        Returns:
            Cache parameter dict
        """
        return {"__cache_node_id": node_id}

    def try_get_cached(self, node_id: str, inputs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Try to get cached outputs for a node.

        Args:
            node_id: The node ID
            inputs: Input values for the node

        Returns:
            Cached outputs if available, None otherwise
        """
        if node_id in self.force_no_cache:
            return None
        if not self.can_cache(node_id):
            return None
        node = self.nodes[node_id]
        return self.cache.get(node.type, self.cache_params(node_id), inputs)

    def cache_outputs(self, node_id: str, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        """Cache the outputs for a node.

        Args:
            node_id: The node ID
            inputs: Input values
            outputs: Output values to cache
        """
        if not self.can_cache(node_id):
            return
        node = self.nodes[node_id]
        self.cache.set(node.type, self.cache_params(node_id), inputs, outputs, node_id=node_id)

    def gather_inputs(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Gather inputs for a node from computed values, user values, or defaults.

        Args:
            node_id: The node ID

        Returns:
            Dict of port -> value, or None if dependencies not ready
        """
        node = self.nodes[node_id]
        if not node.input_ports:
            return {}
        inputs: Dict[str, Any] = {}
        # Get input specs to access default values
        port_specs = {p.name: p for p in (node.spec.inputs if getattr(node, "spec", None) else [])}
        input_values = node.input_values or {}

        for port in node.input_ports:
            port_type = normalize_type(node.input_port_types.get(port))
            from ..typesystem import TypeDescriptor
            if isinstance(port_type, TypeDescriptor) and port_type.kind == "control":
                # Control ports are sequencing only; no data value needed.
                continue

            # 1. Check for connected link
            link = self.input_map.get(node_id, {}).get(port)
            if link:
                if link.from_node not in self.computed_values:
                    return None
                value = self.computed_values[link.from_node].get(link.from_port)
                inputs[port] = value
                continue

            # 2. Check for user-provided value (e.g. from UI input box)
            if port in input_values:
                inputs[port] = input_values[port]
                continue

            # 3. Use Default value from Spec
            spec = port_specs.get(port)
            if spec and spec.default is not None:
                inputs[port] = spec.default
                continue

            # 4. Explicit None for unconnected/defaultless ports
            inputs[port] = None

        return inputs

    def prepare_inputs(self, node_id: str) -> Dict[str, Any]:
        """Gather inputs and raise if dependencies are not ready.

        Args:
            node_id: The node ID

        Returns:
            Dict of port -> value

        Raises:
            GraphExecutionError: If inputs cannot be resolved
        """
        from ..execution import GraphExecutionError

        inputs = self.gather_inputs(node_id)
        if inputs is None:
            raise GraphExecutionError(f"Node '{node_id}' could not resolve inputs")
        return inputs

    def execute_node_work(self, node_id: str, inputs: Dict[str, Any]) -> "NodeExecutionResult":
        """Execute a node in an isolated worker thread without mutating shared state.

        Args:
            node_id: The node ID
            inputs: Input values

        Returns:
            NodeExecutionResult with outputs or error
        """
        from ..execution import GraphExecutionError, NodeExecutionResult, NodeStatus
        from ..nodes import ExecutionContext

        node = self.nodes[node_id]
        level = self.node_levels.get(node_id, 0)
        start_time = time.perf_counter()

        ctx = self._build_context(node_id)

        try:
            # Phase 2: prepare() runs once per run before the first forward.
            if node_id not in self.prepared_nodes:
                try:
                    node.prepare(ctx)
                except NodeError:
                    raise
                except Exception as exc:
                    raise NodeRuntimeError(
                        f"prepare() raised: {exc}",
                        details={"exception_type": exc.__class__.__name__},
                    ) from exc
                # Mark only after a successful prepare so a failure in
                # prepare doesn't permanently block re-attempt within the
                # same run; the run will fail-fast anyway.
                with self.state_lock:
                    self.prepared_nodes.add(node_id)

            # Phase 2: per-node validate_inputs runs *before* forward so a
            # constraint violation surfaces as a NodeInputError rather than a
            # TypeError thrown from within the node body.
            try:
                node.validate_inputs(inputs)
            except NodeError:
                raise
            except Exception as exc:
                # Misbehaving validate_inputs override — fold to runtime error
                raise NodeRuntimeError(
                    f"validate_inputs raised: {exc}",
                    details={"exception_type": exc.__class__.__name__},
                ) from exc

            outputs = node.forward(inputs, ctx)

            expected = set(node.output_ports)
            actual = set(outputs.keys())
            if not expected.issubset(actual):
                raise GraphExecutionError(
                    f"Node '{node_id}' missing output ports: {expected - actual}"
                )
            # Trim to declared ports only
            outputs = {k: outputs[k] for k in expected}

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

        # ------------------------------------------------------------------
        # Phase 2 typed-exception dispatch (§5.2). Order matters: more-
        # specific subclasses first so the catch-all NodeError branch only
        # picks up bespoke subclasses we haven't named explicitly.
        # ------------------------------------------------------------------
        except NodeCancelled as e:
            # Cooperative cancellation. Don't treat as an error in stats:
            # surface as SKIPPED with the typed payload so the UI can render
            # "cancelled" rather than "errored".
            from ..execution import NodeStatus
            end_time = time.perf_counter()
            payload = _build_error_payload(e, node_id=node_id, node_type=node.type)
            return NodeExecutionResult(
                node_id=node_id,
                node_type=node.type,
                status=NodeStatus.SKIPPED,
                start_time=start_time,
                end_time=end_time,
                duration_ms=(end_time - start_time) * 1000,
                error=None,
                error_code=e.code,
                error_payload=payload,
                logs=ctx.logger + [f"CANCELLED: {e.message or 'node cancelled'}"],
                level=level,
                from_cache=False,
            )
        except NodeInputError as e:
            return self._make_typed_error_result(
                e, node_id=node_id, node_type=node.type,
                level=level, start_time=start_time, ctx=ctx,
            )
        except NodeMissingDependencyError as e:
            return self._make_typed_error_result(
                e, node_id=node_id, node_type=node.type,
                level=level, start_time=start_time, ctx=ctx,
            )
        except NodeFileNotFoundError as e:
            return self._make_typed_error_result(
                e, node_id=node_id, node_type=node.type,
                level=level, start_time=start_time, ctx=ctx,
            )
        except NodeNetworkError as e:
            return self._make_typed_error_result(
                e, node_id=node_id, node_type=node.type,
                level=level, start_time=start_time, ctx=ctx,
            )
        except NodeTypeError as e:
            return self._make_typed_error_result(
                e, node_id=node_id, node_type=node.type,
                level=level, start_time=start_time, ctx=ctx,
            )
        except NodeRuntimeError as e:
            return self._make_typed_error_result(
                e, node_id=node_id, node_type=node.type,
                level=level, start_time=start_time, ctx=ctx,
            )
        except NodeError as e:
            # Catch-all for any future / out-of-tree NodeError subclass.
            return self._make_typed_error_result(
                e, node_id=node_id, node_type=node.type,
                level=level, start_time=start_time, ctx=ctx,
            )
        except Exception as e:
            # Wrapper-of-last-resort: every untyped exception becomes a
            # NodeRuntimeError with code "internal_error" so the WS contract
            # always emits a structured payload — "system never crashes".
            import traceback
            end_time = time.perf_counter()
            error_traceback = traceback.format_exc()
            wrapped = NodeRuntimeError(
                str(e) or e.__class__.__name__,
                details={"exception_type": e.__class__.__name__},
            )
            payload = _build_error_payload(
                wrapped, node_id=node_id, node_type=node.type,
                traceback_str=error_traceback,
            )
            payload["code"] = "internal_error"
            return NodeExecutionResult(
                node_id=node_id,
                node_type=node.type,
                status=NodeStatus.ERROR,
                start_time=start_time,
                end_time=end_time,
                duration_ms=(end_time - start_time) * 1000,
                error=str(e),
                error_code="internal_error",
                error_details=error_traceback,
                error_payload=payload,
                logs=ctx.logger + [f"ERROR: {str(e)}"],
                level=level,
                from_cache=False,
            )

    def _build_context(self, node_id: str) -> "ExecutionContext":
        """Build an ExecutionContext for ``node_id`` with the runtime hooks.

        Factored out of ``execute_node_work`` so the typed-exception path
        can attach ``ctx.logger`` to error results without the ``ctx``
        falling out of scope.
        """
        from ..nodes import ExecutionContext

        ctx = ExecutionContext()
        ctx.variables = self.variables
        ctx.metadata = self.shared_metadata
        # Phase 2: per-node resources are held on a shared dict provided by
        # the runner so prepare/forward/teardown all see the same state.
        node_resources = getattr(self, "node_resources_state", None)
        if node_resources is not None:
            ctx.node_resources = node_resources

        def _register_resource(r: Any) -> None:
            with self.state_lock:
                self.resources.append((node_id, r))
        ctx.register_resource = _register_resource

        import subprocess
        def _register_subprocess(proc: subprocess.Popen) -> None:
            self.cancellation.register_process(node_id, proc)
        ctx.register_subprocess = _register_subprocess

        def _check_cancelled() -> bool:
            return self.cancellation.is_cancelled(node_id)
        ctx.check_cancelled = _check_cancelled

        return ctx

    def _make_typed_error_result(
        self,
        exc: NodeError,
        *,
        node_id: str,
        node_type: str,
        level: int,
        start_time: float,
        ctx: "ExecutionContext",
    ) -> "NodeExecutionResult":
        """Package a typed NodeError as a NodeExecutionResult."""
        import traceback
        from ..execution import NodeExecutionResult, NodeStatus

        end_time = time.perf_counter()
        error_traceback = traceback.format_exc()
        payload = _build_error_payload(
            exc, node_id=node_id, node_type=node_type, traceback_str=error_traceback,
        )
        return NodeExecutionResult(
            node_id=node_id,
            node_type=node_type,
            status=NodeStatus.ERROR,
            start_time=start_time,
            end_time=end_time,
            duration_ms=(end_time - start_time) * 1000,
            error=exc.message or str(exc) or exc.__class__.__name__,
            error_code=exc.code,
            error_details=error_traceback,
            error_payload=payload,
            logs=ctx.logger + [f"ERROR [{exc.code}]: {exc.message or exc}"],
            level=level,
            from_cache=False,
        )

    def execute_node_sync(
        self,
        node_id: str,
        inputs: Dict[str, Any],
        allow_cache: bool = True,
        finalize_callback: Optional[Callable] = None,
    ) -> "NodeExecutionResult":
        """Execute a node synchronously with caching support.

        Args:
            node_id: The node ID
            inputs: Input values
            allow_cache: Whether to use caching
            finalize_callback: Optional callback to finalize results

        Returns:
            NodeExecutionResult
        """
        from ..execution import NodeExecutionResult, NodeStatus

        node_start = time.perf_counter()
        cached_outputs = self.try_get_cached(node_id, inputs) if allow_cache else None
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
                level=self.node_levels.get(node_id, 0),
                from_cache=True,
            )
            if finalize_callback:
                finalize_callback(node_id, inputs, result, cached=True, allow_cache=allow_cache)
            return result

        result = self.execute_node_work(node_id, inputs)
        if finalize_callback:
            finalize_callback(node_id, inputs, result, cached=False, allow_cache=allow_cache)
        return result

    def teardown_prepared_nodes(self) -> None:
        """Run ``teardown(ctx)`` for every node that successfully ``prepare``-d.

        Called once per run, in the runner's finally block. Errors raised by
        teardown are swallowed (logged via the node's ctx.logger only) so a
        misbehaving teardown can never tear down the whole runtime.
        """
        if not self.prepared_nodes:
            return
        # Snapshot under the lock so concurrent failures during shutdown
        # don't mutate the set under our feet.
        with self.state_lock:
            prepared = list(self.prepared_nodes)
            self.prepared_nodes.clear()

        for node_id in prepared:
            node = self.nodes.get(node_id)
            if node is None:
                continue
            try:
                ctx = self._build_context(node_id)
                node.teardown(ctx)
            except Exception:
                # Swallow — teardown is best-effort cleanup.
                pass

        # Release per-node ctx-acquired resources.
        for node_id in list(self.node_resources_state.keys()):
            bucket = self.node_resources_state.pop(node_id, {})
            for resource in list(bucket.values()):
                close = getattr(resource, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass

    def make_interrupted_result(self, node_id: str) -> "NodeExecutionResult":
        """Create a result for an interrupted node.

        Args:
            node_id: The node ID

        Returns:
            NodeExecutionResult with SKIPPED status
        """
        from ..execution import NodeExecutionResult, NodeStatus

        return NodeExecutionResult(
            node_id=node_id,
            node_type=self.nodes[node_id].type,
            status=NodeStatus.SKIPPED,
            logs=[f"Node {node_id} interrupted"],
            duration_ms=0.0,
            level=self.node_levels.get(node_id, 0),
            from_cache=False,
        )

    def make_input_error_result(self, node_id: str, exc: Exception) -> "NodeExecutionResult":
        """Create a result for an input resolution error.

        Args:
            node_id: The node ID
            exc: The exception that occurred

        Returns:
            NodeExecutionResult with ERROR status
        """
        import traceback
        from ..execution import NodeExecutionResult, NodeStatus

        error_traceback = traceback.format_exc()
        node_type = self.nodes[node_id].type
        payload = _build_error_payload(
            exc, node_id=node_id, node_type=node_type, traceback_str=error_traceback,
        )
        return NodeExecutionResult(
            node_id=node_id,
            node_type=node_type,
            status=NodeStatus.ERROR,
            error=str(exc),
            error_code=getattr(exc, "code", None) or payload["code"],
            error_details=error_traceback,
            error_payload=payload,
            logs=[f"ERROR: {str(exc)}"],
            duration_ms=0.0,
            level=self.node_levels.get(node_id, 0),
            from_cache=False,
        )


__all__ = ["NodeExecutor"]
