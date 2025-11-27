from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ExecutionContext:
    """Provides runtime metadata that nodes can use while running."""

    logger: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def log(self, message: str) -> None:
        self.logger.append(message)


class NodeBase(abc.ABC):
    """Minimal base for nodes with ports and params."""

    node_type: str = "node.base"
    display_name: str = "Node"
    description: str = ""
    icon: str = "node"
    params_schema: Dict[str, Dict[str, Any]] = {}
    input_ports: List[str] = []
    output_ports: List[str] = []

    def __init__(self, config: Dict[str, Any]) -> None:
        self.id: str = config["id"]
        self.type: str = config["type"]
        self.params: Dict[str, Any] = config.get("params", {})
        self.config: Dict[str, Any] = config

    @property
    def metadata(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "input_ports": self.input_ports,
            "output_ports": self.output_ports,
            "params": self.params,
        }

    @abc.abstractmethod
    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        ...
