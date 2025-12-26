from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..node_spec import NodeSpec
from ..typesystem import t_any

@dataclass
class ExecutionContext:
    """Provides runtime metadata that nodes can use while running."""

    logger: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    variables: Dict[str, Any] = field(default_factory=dict)

    def log(self, message: str) -> None:
        self.logger.append(message)

    def set_var(self, name: str, value: Any) -> None:
        self.variables[name] = value

    def get_var(self, name: str, default: Any = None) -> Any:
        return self.variables.get(name, default)


class NodeBase(abc.ABC):
    """Minimal base for nodes with ports and params.

    Concrete nodes should be registered with a NodeSpec via the register_node decorator.
    """

    spec: NodeSpec  # injected during registration

    def __init__(self, config: Dict[str, Any], spec: Optional[NodeSpec] = None) -> None:
        self.spec = spec or getattr(self, "spec", None)
        self.id: str = config["id"]
        self.type: str = config.get("type") or (self.spec.type if self.spec else "")
        self.params: Dict[str, Any] = config.get("params", {})
        self.input_values: Dict[str, Any] = config.get("input_values", {})
        self.config: Dict[str, Any] = config

        # Derived for compatibility with the existing executor/UI.
        input_override = config.get("input_ports_override")
        output_override = config.get("output_ports_override")
        input_types_override = config.get("input_port_types_override")
        output_types_override = config.get("output_port_types_override")

        self.input_ports: List[str] = input_override or [p.name for p in (self.spec.inputs if self.spec else [])]
        self.output_ports: List[str] = output_override or [p.name for p in (self.spec.outputs if self.spec else [])]

        if input_types_override:
            self.input_port_types = input_types_override
        else:
            self.input_port_types = {p.name: p.type for p in (self.spec.inputs if self.spec else [])}
        if output_types_override:
            self.output_port_types = output_types_override
        else:
            self.output_port_types = {p.name: p.type for p in (self.spec.outputs if self.spec else [])}

        for port in self.input_ports:
            self.input_port_types.setdefault(port, t_any())
        for port in self.output_ports:
            self.output_port_types.setdefault(port, t_any())
        if self.spec:
            self.params_schema = {name: param.to_dict() for name, param in self.spec.params.items()}
        else:
            self.params_schema = {}

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "input_ports": self.input_ports,
            "output_ports": self.output_ports,
            "input_port_types": self.input_port_types,
            "output_port_types": self.output_port_types,
            "params": self.params,
            "input_values": self.input_values,
        }

    @abc.abstractmethod
    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        ...
