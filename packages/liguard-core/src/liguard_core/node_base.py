"""
Base classes for LiGuard-Web nodes.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .node_spec import NodeSpec


@dataclass
class ExecutionContext:
    """Provides runtime metadata that nodes can use while running."""

    logger: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    variables: Dict[str, Any] = field(default_factory=dict)
    resources: List[Any] = field(default_factory=list)
    _interrupted: bool = field(default=False, repr=False)

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

    @property
    def is_interrupted(self) -> bool:
        """Check if execution has been interrupted."""
        return self._interrupted

    def interrupt(self) -> None:
        """Mark execution as interrupted."""
        self._interrupted = True


class NodeBase(abc.ABC):
    """Minimal base for nodes with ports and params.

    Concrete nodes should be registered with a NodeSpec via the register_node decorator.
    """

    spec: "NodeSpec"  # injected during registration

    def __init__(self, config: Dict[str, Any], spec: Optional["NodeSpec"] = None) -> None:
        self.spec = spec or getattr(self, "spec", None)
        self.id: str = config["id"]
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
