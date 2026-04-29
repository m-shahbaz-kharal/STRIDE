"""
Base classes for STRIDE nodes.

Phase 2 introduces the v2 NodeBase contract with explicit lifecycle hooks
(``prepare`` / ``teardown``), a per-node ``validate_inputs`` step, an opt-in
``cache_key`` override, and a scheduler-friendly ``estimate_cost`` hook.

See ``docs/architecture/unified-type-system-and-ux.md`` §5.1 for the design.
Backwards compatibility is preserved: every new hook has a no-op default so
nodes that previously implemented only ``forward`` keep working unchanged.
"""

from __future__ import annotations

import abc
import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .node_spec import NodeSpec


@dataclass
class ExecutionContext:
    """Provides runtime metadata that nodes can use while running.

    Attributes:
        logger: List of log messages.
        metadata: Shared metadata dict.
        variables: Shared variables dict.
        resources: List of resources to clean up.
        node_resources: Per-(node_id, key) resource registry. Phase 2 stateful
            nodes hold their tracker / model state here via
            ``acquire_node_resource`` so module-level dicts are no longer
            needed.
        _interrupted: Internal interruption flag.
        register_subprocess: Callback to register a subprocess for cleanup on
            interruption.
        check_cancelled: Callback to check if the node has been cancelled.
    """

    logger: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    variables: Dict[str, Any] = field(default_factory=dict)
    resources: List[Any] = field(default_factory=list)
    node_resources: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    _interrupted: bool = field(default=False, repr=False)

    # These are injected by the executor at runtime
    register_subprocess: Optional[Callable[[subprocess.Popen], None]] = field(default=None, repr=False)
    check_cancelled: Optional[Callable[[], bool]] = field(default=None, repr=False)

    def log(self, message: str) -> None:
        """Add a log message."""
        self.logger.append(message)

    def set_var(self, name: str, value: Any) -> None:
        """Set a variable in the execution context."""
        self.variables[name] = value

    def get_var(self, name: str, default: Any = None) -> Any:
        """Get a variable from the execution context."""
        return self.variables.get(name, default)

    def register_resource(self, resource: Any) -> None:
        """Register a resource that needs to be cleaned up when execution finishes."""
        self.resources.append(resource)

    def acquire_node_resource(
        self,
        node_id: str,
        key: str,
        factory: Callable[[], Any],
    ) -> Any:
        """Get-or-create a per-(node, key) resource for this execution run.

        Stateful nodes (trackers, model sessions, voxel background models, …)
        should hold their state here rather than on a module-level dict so it
        is automatically scoped to a single run. ``release_node_resource`` or
        the executor's run-end cleanup releases it.

        Args:
            node_id: Owning node id (typically ``self.id``).
            key: Logical resource name within the node (e.g. ``"tracker"``).
            factory: Zero-arg callable that constructs the resource on first
                acquire. Subsequent calls in the same run return the same
                instance.

        Returns:
            The resource instance.
        """
        bucket = self.node_resources.setdefault(node_id, {})
        if key not in bucket:
            bucket[key] = factory()
        return bucket[key]

    def release_node_resource(self, node_id: str, key: str) -> None:
        """Release a single per-node resource immediately.

        Calls ``.close()`` on the resource if available. No-op if the resource
        is not registered.
        """
        bucket = self.node_resources.get(node_id)
        if not bucket or key not in bucket:
            return
        resource = bucket.pop(key)
        close = getattr(resource, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
        if not bucket:
            self.node_resources.pop(node_id, None)

    def release_all_node_resources(self, node_id: Optional[str] = None) -> None:
        """Release every per-node resource for ``node_id`` (or all nodes).

        Used by the executor at run end. ``.close()`` is invoked for any
        resource that exposes it, and exceptions are swallowed so a single
        broken resource cannot block cleanup of the rest.
        """
        if node_id is not None:
            for key in list(self.node_resources.get(node_id, {}).keys()):
                self.release_node_resource(node_id, key)
            return
        for nid in list(self.node_resources.keys()):
            self.release_all_node_resources(nid)

    @property
    def is_interrupted(self) -> bool:
        """Check if execution has been interrupted.

        Nodes can call this periodically during long-running operations
        to cooperatively respond to cancellation requests.
        """
        # Use the injected check_cancelled if available (more accurate)
        if self.check_cancelled is not None:
            return self.check_cancelled()
        return self._interrupted

    def interrupt(self) -> None:
        """Mark execution as interrupted."""
        self._interrupted = True


class NodeBase(abc.ABC):
    """Minimal base for nodes with ports and params.

    Concrete nodes should be registered with a NodeSpec via the
    ``register_node`` decorator.

    Phase 2 lifecycle hooks (see §5.1 of the design doc):

    * ``prepare(ctx)`` — called once per execution run *before* the first
      ``forward()``. Default no-op. Override to allocate stateful resources
      (model weights, sockets, voxel background models, …) typically via
      ``ctx.acquire_node_resource(...)``.
    * ``forward(inputs, ctx)`` — pure-ish data transform. Still abstract.
    * ``teardown(ctx)`` — called once per execution run *after* the last
      ``forward()``, on success, error, or cancellation. Default no-op.
      Release non-Python resources here.
    * ``validate_inputs(inputs)`` — default checks ``PortSpec.constraints``;
      override to add bespoke shape/range checks. Raise ``NodeInputError`` on
      failure.
    * ``cache_key(inputs)`` — return a stable hash for cache lookup, or
      ``None`` to disable caching for this call.
    * ``estimate_cost(inputs)`` — scheduler hint in seconds. Default ``0.0``.
    """

    spec: "NodeSpec"  # injected during registration

    def __init__(self, config: Dict[str, Any], spec: Optional["NodeSpec"] = None) -> None:
        self.spec = spec or getattr(self, "spec", None)
        self.id: str = config.get("id", "")
        self.type: str = config.get("type") or (self.spec.type if self.spec else "")
        self.params: Dict[str, Any] = config.get("params", {})
        self.input_values: Dict[str, Any] = config.get("input_values", {})
        self.config: Dict[str, Any] = config

        # Derived for compatibility with the existing executor/UI.
        input_override = config.get("input_ports_override")
        if input_override is not None:
            self.input_ports = input_override
        elif self.spec:
            self.input_ports = [p.name for p in self.spec.inputs]
        else:
            self.input_ports = []

        output_override = config.get("output_ports_override")
        if output_override is not None:
            self.output_ports = output_override
        elif self.spec:
            self.output_ports = [p.name for p in self.spec.outputs]
        else:
            self.output_ports = []

        if self.spec:
            self.input_port_types = {p.name: p.type for p in self.spec.inputs}
            self.output_port_types = {p.name: p.type for p in self.spec.outputs}
        else:
            self.input_port_types = {}
            self.output_port_types = {}

    # ------------------------------------------------------------------
    # Phase 2 lifecycle hooks
    # ------------------------------------------------------------------

    def prepare(self, ctx: ExecutionContext) -> None:
        """Called once per run before the first ``forward()``.

        Default no-op so stateless nodes inherit-for-free. Override to
        allocate stateful resources that should outlive a single ``forward``
        call but be released at run end.
        """
        return None

    @abc.abstractmethod
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        """Execute the node logic.

        Args:
            inputs: Dictionary of input port names to values.
            ctx: Execution context with logger, metadata, and resources.

        Returns:
            Dictionary of output port names to values.
        """
        ...

    def teardown(self, ctx: ExecutionContext) -> None:
        """Called once per run after the last ``forward()`` (or on error / cancel).

        Default no-op. Override to release non-Python resources (file
        handles, sockets, model sessions). Resources allocated via
        ``ctx.acquire_node_resource`` are released automatically by the
        executor — ``teardown`` is for resources the runtime cannot inspect.
        """
        return None

    # ------------------------------------------------------------------
    # Phase 2 optional hooks
    # ------------------------------------------------------------------

    def validate_inputs(self, inputs: Dict[str, Any]) -> None:
        """Validate per-port input values before ``forward()``.

        The default implementation enforces ``PortSpec.constraints``
        declarations (min/max for numerics, enum membership, regex pattern,
        path-extension whitelist, length bounds — see
        ``docs/architecture/unified-type-system-and-ux.md`` §5.3). Subclasses
        may override to add bespoke checks; calling ``super().validate_inputs``
        first preserves the constraint enforcement.

        Raises:
            NodeInputError: when a value violates its declared constraints.
        """
        from .errors import NodeInputError

        if not self.spec:
            return

        for port_spec in self.spec.inputs:
            constraints = getattr(port_spec, "constraints", None)
            if not constraints:
                continue
            if port_spec.name not in inputs:
                continue
            value = inputs.get(port_spec.name)
            if value is None:
                # ``required`` semantics are enforced elsewhere; constraints
                # are about *value* shape, so treat None as no-op here.
                continue
            error = _check_constraint(value, constraints)
            if error is not None:
                raise NodeInputError(
                    f"input '{port_spec.name}' failed constraint: {error}",
                    port=port_spec.name,
                    details={
                        "constraint": constraints,
                        "value_preview": _truncate_for_preview(value),
                    },
                )

    def cache_key(self, inputs: Dict[str, Any]) -> Optional[str]:
        """Return a stable cache key for this call, or ``None`` to disable
        caching for this invocation.

        Default returns a hash over ``(node_type, params, normalized inputs)``.
        Override when the node has hidden state that affects output, or when
        an input is intrinsically time-varying (live stream frames, etc.) —
        return ``None`` in that case.
        """
        try:
            payload = {
                "type": self.type,
                "params": _normalize_for_hash(self.params),
                "inputs": _normalize_for_hash(inputs),
            }
            blob = json.dumps(payload, sort_keys=True, default=str)
        except Exception:
            return None
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def estimate_cost(self, inputs: Dict[str, Any]) -> float:
        """Return a scheduler hint for the cost (relative units) of this call.

        Default ``1.0`` — a generic node. Override when a node has a known
        heavyweight or lightweight profile so future schedulers can budget
        accordingly. Used for batching / work-stealing in later phases.
        """
        return 1.0


def _check_constraint(value: Any, constraints: Dict[str, Any]) -> Optional[str]:
    """Apply a PortSpec.constraints dict to ``value``.

    Returns a human-readable failure message, or ``None`` if the value is OK.
    The constraint vocabulary is the one specified in §5.3 of the design doc.
    """
    # Numeric bounds.
    if "min" in constraints or "max" in constraints:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return f"expected numeric value, got {type(value).__name__}"
        lo = constraints.get("min")
        hi = constraints.get("max")
        if lo is not None and number < float(lo):
            return f"value {number} < min {lo}"
        if hi is not None and number > float(hi):
            return f"value {number} > max {hi}"

    # Enum membership.
    if "enum" in constraints:
        choices = constraints["enum"] or []
        if value not in choices:
            return f"value {value!r} not in enum {list(choices)!r}"

    # Regex pattern.
    if "pattern" in constraints and isinstance(value, str):
        import re
        pattern = constraints["pattern"]
        if pattern and not re.search(pattern, value):
            return f"value {value!r} did not match pattern {pattern!r}"

    # Length bounds (string or list-like).
    length: Optional[int] = None
    if "length_min" in constraints or "length_max" in constraints:
        try:
            length = len(value)
        except TypeError:
            return "value has no length"
        lo_len = constraints.get("length_min")
        hi_len = constraints.get("length_max")
        if lo_len is not None and length < int(lo_len):
            return f"length {length} < length_min {lo_len}"
        if hi_len is not None and length > int(hi_len):
            return f"length {length} > length_max {hi_len}"

    # File-path extension allow-list (only meaningful for strings).
    extensions = constraints.get("extensions")
    if extensions and isinstance(value, str):
        lowered = value.lower()
        allowed = [str(ext).lower().lstrip(".") for ext in extensions]
        if not any(lowered.endswith("." + ext) for ext in allowed):
            return f"path {value!r} extension not in {allowed!r}"

    return None


def _normalize_for_hash(value: Any) -> Any:
    """Best-effort JSON-friendly normalisation for the default cache key.

    Mirrors ``ExecutionCache._normalize_for_key`` for primitives but stays
    deliberately minimal — heavyweight payloads (numpy / torch / PIL) are
    handled by the executor cache and rarely flow through ``cache_key``.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        h = hashlib.sha256(bytes(value)).hexdigest()
        return {"__bytes__": h, "len": len(value) if hasattr(value, "__len__") else 0}
    if isinstance(value, dict):
        return {str(k): _normalize_for_hash(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize_for_hash(v) for v in value]
    if isinstance(value, set):
        return sorted([_normalize_for_hash(v) for v in value], key=lambda v: json.dumps(v, sort_keys=True, default=str))
    return {"__repr__": repr(value)}


def _truncate_for_preview(value: Any, limit: int = 160) -> Any:
    """Best-effort small representation for an error payload."""
    try:
        text = repr(value)
    except Exception:
        text = f"<unrepresentable {type(value).__name__}>"
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text
