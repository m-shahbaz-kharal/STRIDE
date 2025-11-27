from __future__ import annotations

from typing import Any, Dict

from .base import ExecutionContext, NodeBase
from . import register_node


class BaseNumberNode(NodeBase):
    """Share logic between source nodes that emit a scalar value."""

    input_ports = []
    output_ports = ["value"]

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(config)
        self._value = config.get("params", {}).get("value", 0)

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        ctx.log(f"{self.id} emits constant {self._value}")
        return {"value": self._value}


@register_node
class ConstantNumberNode(BaseNumberNode):
    node_type = "constant.number"


@register_node
class MirrorNumberNode(BaseNumberNode):
    node_type = "mirror.number"

