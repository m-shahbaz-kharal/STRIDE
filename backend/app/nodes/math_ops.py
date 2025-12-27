from __future__ import annotations

from typing import Any, Dict

from .base import ExecutionContext, NodeBase
from . import register_node
from ..node_spec import NodeSpec, PortSpec
from ..typesystem import t_any, t_control, t_float
from .coercion import coerce_number


MULTIPLY_SPEC = NodeSpec(
    type="core.math.multiply",
    version="1.0.0",
    display_name="Multiply",
    category="Math",
    summary="Multiplies two numbers.",
    description="Multiplies two numbers together.",
    icon="times",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="a", type=t_any(), required=False, default=None),
        PortSpec(name="b", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="product", type=t_float()),
    ],
    params={},
)


@register_node(MULTIPLY_SPEC)
class MultiplyNode(NodeBase):

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        a_value = coerce_number(inputs.get("a"))
        b_value = coerce_number(inputs.get("b"))
        result = (a_value or 0.0) * (b_value or 0.0)
        ctx.log(f"{self.id} multiplied {a_value} * {b_value} -> {result}")
        return {"control_out": None, "product": result}


SUBTRACT_SPEC = NodeSpec(
    type="core.math.subtract",
    version="1.0.0",
    display_name="Subtract",
    category="Math",
    summary="Subtracts second number from first.",
    description="Subtracts second number from first.",
    icon="minus",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="a", type=t_any(), required=False, default=None),
        PortSpec(name="b", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="difference", type=t_float()),
    ],
    params={},
)


@register_node(SUBTRACT_SPEC)
class SubtractNode(NodeBase):

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        a_value = coerce_number(inputs.get("a"))
        b_value = coerce_number(inputs.get("b"))
        result = (a_value or 0.0) - (b_value or 0.0)
        ctx.log(f"{self.id} subtracted {a_value} - {b_value} -> {result}")
        return {"control_out": None, "difference": result}


DIVIDE_SPEC = NodeSpec(
    type="core.math.divide",
    version="1.0.0",
    display_name="Divide",
    category="Math",
    summary="Divides first number by second.",
    description="Divides first number by second.",
    icon="divide",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="a", type=t_any(), required=False, default=None),
        PortSpec(name="b", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="quotient", type=t_float()),
    ],
    params={},
)


@register_node(DIVIDE_SPEC)
class DivideNode(NodeBase):

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        a_value = coerce_number(inputs.get("a"))
        b_value = coerce_number(inputs.get("b"))
        if not b_value:
            ctx.log(f"{self.id} division by zero, returning 0")
            return {"control_out": None, "quotient": 0}
        result = (a_value or 0.0) / b_value
        ctx.log(f"{self.id} divided {a_value} / {b_value} -> {result}")
        return {"control_out": None, "quotient": result}


POWER_SPEC = NodeSpec(
    type="core.math.power",
    version="1.0.0",
    display_name="Power",
    category="Math",
    summary="Raises base to exponent.",
    description="Raises base to the power of exponent.",
    icon="superscript",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="base", type=t_any(), required=False, default=None),
        PortSpec(name="exponent", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_float()),
    ],
    params={},
)


@register_node(POWER_SPEC)
class PowerNode(NodeBase):

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        base = coerce_number(inputs.get("base")) or 0.0
        exponent = coerce_number(inputs.get("exponent")) or 1.0
        result = base ** exponent
        ctx.log(f"{self.id} computed {base} ^ {exponent} -> {result}")
        return {"control_out": None, "result": result}


ABS_SPEC = NodeSpec(
    type="core.math.abs",
    version="1.0.0",
    display_name="Absolute",
    category="Math",
    summary="Absolute value.",
    description="Returns absolute value of input.",
    icon="abs",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_float()),
    ],
    params={},
)


@register_node(ABS_SPEC)
class AbsoluteNode(NodeBase):

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        value = coerce_number(inputs.get("value")) or 0.0
        result = abs(value)
        ctx.log(f"{self.id} abs({value}) -> {result}")
        return {"control_out": None, "result": result}
