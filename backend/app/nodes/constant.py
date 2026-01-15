from __future__ import annotations

from typing import Any, Dict

from .base import ExecutionContext, NodeBase
from . import register_node
from ..node_spec import NodeSpec, PortSpec
from ..typesystem import t_boolean, t_float, t_int, t_string


class BaseLiteralNode(NodeBase):
    """Share logic between literal nodes that emit a scalar value."""

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        val = inputs.get("value")
        ctx.log(f"{self.id} emits constant {val}")
        return {"value": val}


LITERAL_INT_SPEC = NodeSpec(
    type="core.literal.int",
    version="1.0.0",
    display_name="Int",
    category="Literal",
    summary="Emit a fixed integer.",
    description="Always produces the configured integer.",
    icon="math",
    inputs=[
        PortSpec(name="value", type=t_int(), required=False, default=0, ui={"control": "number"}),
    ],
    outputs=[PortSpec(name="value", type=t_int())],

)


@register_node(LITERAL_INT_SPEC)
class LiteralIntNode(BaseLiteralNode):
    pass


LITERAL_FLOAT_SPEC = NodeSpec(
    type="core.literal.float",
    version="1.0.0",
    display_name="Float",
    category="Literal",
    summary="Emit a fixed float.",
    description="Always produces the configured float.",
    icon="math",
    inputs=[
        PortSpec(name="value", type=t_float(), required=False, default=0.0, ui={"control": "number"}),
    ],
    outputs=[PortSpec(name="value", type=t_float())],

)


@register_node(LITERAL_FLOAT_SPEC)
class LiteralFloatNode(BaseLiteralNode):
    pass


LITERAL_STRING_SPEC = NodeSpec(
    type="core.literal.string",
    version="1.0.0",
    display_name="String",
    category="Literal",
    summary="Emit a fixed string.",
    description="Always produces the configured string.",
    icon="text",
    inputs=[
        PortSpec(name="value", type=t_string(), required=False, default="", ui={"control": "text"}),
    ],
    outputs=[PortSpec(name="value", type=t_string())],

)


@register_node(LITERAL_STRING_SPEC)
class LiteralStringNode(BaseLiteralNode):
    pass


LITERAL_BOOL_SPEC = NodeSpec(
    type="core.literal.boolean",
    version="1.0.0",
    display_name="Boolean",
    category="Literal",
    summary="Emit a fixed boolean.",
    description="Always produces the configured boolean.",
    icon="check",
    inputs=[
        PortSpec(name="value", type=t_boolean(), required=False, default=False, ui={"control": "checkbox"}),
    ],
    outputs=[PortSpec(name="value", type=t_boolean())],

)


@register_node(LITERAL_BOOL_SPEC)
class LiteralBooleanNode(BaseLiteralNode):
    pass

