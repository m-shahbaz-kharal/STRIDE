from __future__ import annotations

from typing import Any, Dict

from .base import ExecutionContext, NodeBase
from . import register_node


class BaseNumberNode(NodeBase):
    """Share logic between source nodes that emit a scalar value."""

    display_name = "Scalar Source"
    description = "Emits a numeric scalar that can be wired into other nodes."
    icon = "circle"
    input_ports = []
    output_ports = ["value"]
    params_schema = {
        "value": {
            "type": "number",
            "label": "Value",
            "description": "Numeric payload emitted every run.",
            "default": 0,
        }
    }

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
    display_name = "Number"
    description = "Always produces the configured scalar."
    icon = "math"


