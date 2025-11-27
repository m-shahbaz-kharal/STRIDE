from __future__ import annotations

from typing import Any, Dict

from .base import ExecutionContext, NodeBase
from . import register_node


@register_node
class AdditionNode(NodeBase):
    node_type = "math.add"
    display_name = "Add"
    description = "Combines two numbers."
    icon = "plus"
    params_schema: Dict[str, Any] = {}
    input_ports = ["a", "b"]
    output_ports = ["sum"]

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        a_value = inputs.get("a")
        b_value = inputs.get("b")
        result = a_value + b_value
        ctx.log(f"{self.id} added {a_value} + {b_value} -> {result}")
        return {"sum": result}

