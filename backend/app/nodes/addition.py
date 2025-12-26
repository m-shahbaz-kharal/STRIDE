from __future__ import annotations

from typing import Any, Dict

from .base import ExecutionContext, NodeBase
from . import register_node
from ..node_spec import NodeSpec, PortSpec
from ..typesystem import t_any, t_control
from .coercion import coerce_add


ADDITION_SPEC = NodeSpec(
    type="core.math.add",
    version="1.0.0",
    display_name="Add",
    category="Math",
    summary="Add two numbers.",
    description="Combines two numeric inputs.",
    icon="plus",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="a", type=t_any(), required=False, default=None),
        PortSpec(name="b", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="sum", type=t_any()),
    ],
    params={},
)


@register_node(ADDITION_SPEC)
class AdditionNode(NodeBase):
    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        a_value = inputs.get("a")
        b_value = inputs.get("b")
        
        # Sample logs for demonstration
        ctx.log(f"[AdditionNode] Starting addition operation")
        ctx.log(f"[AdditionNode] Input a = {a_value} (type: {type(a_value).__name__})")
        ctx.log(f"[AdditionNode] Input b = {b_value} (type: {type(b_value).__name__})")
        
        result, mode = coerce_add(a_value, b_value)
        
        ctx.log(f"[AdditionNode] Computed ({mode}): {a_value} + {b_value} = {result}")
        ctx.log(f"[AdditionNode] Operation completed successfully")
        
        return {"control_out": None, "sum": result}
