"""
Node execution and caching for graph execution.

Handles individual node execution, caching, and loop iteration.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Set, TYPE_CHECKING

from .utils import normalize_type

if TYPE_CHECKING:
    from ..execution import ExecutionCache, NodeExecutionResult, NodeStatus
    from ..nodes import ExecutionContext, NodeBase
    from .cancellation import CancellationController


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

        try:
            ctx = ExecutionContext()
            ctx.variables = self.variables
            ctx.metadata = self.shared_metadata

            # Hook up resource registration
            def _register_resource(r: Any) -> None:
                with self.state_lock:
                    self.resources.append((node_id, r))
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
            import traceback
            end_time = time.perf_counter()
            error_traceback = traceback.format_exc()
            return NodeExecutionResult(
                node_id=node_id,
                node_type=node.type,
                status=NodeStatus.ERROR,
                start_time=start_time,
                end_time=end_time,
                duration_ms=(end_time - start_time) * 1000,
                error=str(e),
                error_code=getattr(e, "code", None),
                error_details=error_traceback,
                logs=[f"ERROR: {str(e)}"],
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
        return NodeExecutionResult(
            node_id=node_id,
            node_type=self.nodes[node_id].type,
            status=NodeStatus.ERROR,
            error=str(exc),
            error_code=getattr(exc, "code", None),
            error_details=error_traceback,
            logs=[f"ERROR: {str(exc)}"],
            duration_ms=0.0,
            level=self.node_levels.get(node_id, 0),
            from_cache=False,
        )


__all__ = ["NodeExecutor"]
