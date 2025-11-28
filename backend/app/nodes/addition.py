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
        
        # Sample logs for demonstration
        ctx.log(f"[AdditionNode] Starting addition operation")
        ctx.log(f"[AdditionNode] Input a = {a_value} (type: {type(a_value).__name__})")
        ctx.log(f"[AdditionNode] Input b = {b_value} (type: {type(b_value).__name__})")
        
        result = a_value + b_value
        
        ctx.log(f"[AdditionNode] Computed: {a_value} + {b_value} = {result}")
        ctx.log(f"[AdditionNode] Operation completed successfully")
        
        return {"sum": result}
