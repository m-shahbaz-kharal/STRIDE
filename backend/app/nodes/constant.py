from __future__ import annotations

from typing import Any, Dict

from .base import ExecutionContext, NodeBase
from . import register_node
from ..node_spec import NodeSpec, ParamSpec, PortSpec
from ..typesystem import t_boolean, t_float, t_int, t_string


class BaseLiteralNode(NodeBase):
    """Share logic between literal nodes that emit a scalar value."""

    def __init__(self, config: Dict[str, Any], spec: NodeSpec) -> None:
        super().__init__(config, spec=spec)
        self._value = config.get(
            "params", {}
        ).get("value", spec.params.get("value").default if spec and spec.params.get("value") else None)

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        ctx.log(f"{self.id} emits constant {self._value}")
        return {"value": self._value}


LITERAL_INT_SPEC = NodeSpec(
    type="core.literal.int",
    version="1.0.0",
    display_name="Int",
    category="Literal",
    summary="Emit a fixed integer.",
    description="Always produces the configured integer.",
    icon="math",
    inputs=[],
    outputs=[PortSpec(name="value", type=t_int())],
    params={
        "value": ParamSpec(
            name="value",
            type="int",
            label="Value",
            description="Integer payload emitted every run.",
            default=0,
        )
    },
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
    inputs=[],
    outputs=[PortSpec(name="value", type=t_float())],
    params={
        "value": ParamSpec(
            name="value",
            type="float",
            label="Value",
            description="Float payload emitted every run.",
            default=0.0,
        )
    },
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
    inputs=[],
    outputs=[PortSpec(name="value", type=t_string())],
    params={
        "value": ParamSpec(
            name="value",
            type="string",
            label="Value",
            description="String payload emitted every run.",
            default="",
        )
    },
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
    inputs=[],
    outputs=[PortSpec(name="value", type=t_boolean())],
    params={
        "value": ParamSpec(
            name="value",
            type="boolean",
            label="Value",
            description="Boolean payload emitted every run.",
            default=False,
        )
    },
)


@register_node(LITERAL_BOOL_SPEC)
class LiteralBooleanNode(BaseLiteralNode):
    pass

