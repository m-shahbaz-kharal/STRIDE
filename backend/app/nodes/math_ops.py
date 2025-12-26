from __future__ import annotations

import time
from typing import Any, Dict

from .base import ExecutionContext, NodeBase
from . import register_node
from ..node_spec import NodeSpec, ParamSpec, PortSpec
from ..typesystem import t_any, t_float
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
        PortSpec(name="a", type=t_any(), required=False, default=None),
        PortSpec(name="b", type=t_any(), required=False, default=None),
    ],
    outputs=[PortSpec(name="product", type=t_float())],
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
        return {"product": result}


SUBTRACT_SPEC = NodeSpec(
    type="core.math.subtract",
    version="1.0.0",
    display_name="Subtract",
    category="Math",
    summary="Subtracts second number from first.",
    description="Subtracts second number from first.",
    icon="minus",
    inputs=[
        PortSpec(name="a", type=t_any(), required=False, default=None),
        PortSpec(name="b", type=t_any(), required=False, default=None),
    ],
    outputs=[PortSpec(name="difference", type=t_float())],
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
        return {"difference": result}


DIVIDE_SPEC = NodeSpec(
    type="core.math.divide",
    version="1.0.0",
    display_name="Divide",
    category="Math",
    summary="Divides first number by second.",
    description="Divides first number by second.",
    icon="divide",
    inputs=[
        PortSpec(name="a", type=t_any(), required=False, default=None),
        PortSpec(name="b", type=t_any(), required=False, default=None),
    ],
    outputs=[PortSpec(name="quotient", type=t_float())],
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
            return {"quotient": 0}
        result = (a_value or 0.0) / b_value
        ctx.log(f"{self.id} divided {a_value} / {b_value} -> {result}")
        return {"quotient": result}


POWER_SPEC = NodeSpec(
    type="core.math.power",
    version="1.0.0",
    display_name="Power",
    category="Math",
    summary="Raises base to exponent.",
    description="Raises base to the power of exponent.",
    icon="superscript",
    inputs=[
        PortSpec(name="base", type=t_any(), required=False, default=None),
        PortSpec(name="exponent", type=t_any(), required=False, default=None),
    ],
    outputs=[PortSpec(name="result", type=t_float())],
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
        return {"result": result}


ABS_SPEC = NodeSpec(
    type="core.math.abs",
    version="1.0.0",
    display_name="Absolute",
    category="Math",
    summary="Absolute value.",
    description="Returns absolute value of input.",
    icon="abs",
    inputs=[PortSpec(name="value", type=t_any(), required=False, default=None)],
    outputs=[PortSpec(name="result", type=t_float())],
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
        return {"result": result}


DELAY_SPEC = NodeSpec(
    type="core.util.delay",
    version="1.0.0",
    display_name="Delay",
    category="Utility",
    summary="Sleep for a bit then pass the value through.",
    description="Passes through value after a configurable delay. Useful for testing parallel execution.",
    icon="clock",
    inputs=[PortSpec(name="value", type=t_any(), required=False, default=None)],
    outputs=[PortSpec(name="value", type=t_any())],
    params={
        "delay_ms": ParamSpec(
            name="delay_ms",
            type="number",
            label="Delay (ms)",
            description="Milliseconds to wait before producing output.",
            default=100,
        )
    },
    stability="experimental",
)


@register_node(DELAY_SPEC)
class DelayNode(NodeBase):
    """Simulates a slow operation for testing parallel execution."""

    def __init__(self, config: Dict[str, Any], spec: NodeSpec = DELAY_SPEC) -> None:
        super().__init__(config, spec=spec)
        self._delay_ms = config.get("params", {}).get("delay_ms", spec.params["delay_ms"].default)

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        value = inputs.get("value")
        time.sleep(self._delay_ms / 1000.0)
        ctx.log(f"{self.id} delayed {self._delay_ms}ms, passing {value}")
        return {"value": value}


SPLITTER_SPEC = NodeSpec(
    type="core.util.splitter",
    version="1.0.0",
    display_name="Splitter",
    category="Utility",
    summary="Fork a value to three outputs.",
    description="Splits a single value into multiple outputs for parallel processing branches.",
    icon="split",
    inputs=[PortSpec(name="input", type=t_any(), required=False, default=None)],
    outputs=[
        PortSpec(name="out_a", type=t_any()),
        PortSpec(name="out_b", type=t_any()),
        PortSpec(name="out_c", type=t_any()),
    ],
    params={},
    stability="experimental",
)


@register_node(SPLITTER_SPEC)
class SplitterNode(NodeBase):
    """Splits a single input into multiple identical outputs for parallel branches."""

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        value = inputs.get("input")
        ctx.log(f"{self.id} splitting {value} to 3 outputs")
        return {"out_a": value, "out_b": value, "out_c": value}


MERGER_SPEC = NodeSpec(
    type="core.util.merger",
    version="1.0.0",
    display_name="Merger",
    category="Utility",
    summary="Sum three numbers.",
    description="Merges multiple inputs by summing them together.",
    icon="merge",
    inputs=[
        PortSpec(name="in_a", type=t_any(), required=False, default=None),
        PortSpec(name="in_b", type=t_any(), required=False, default=None),
        PortSpec(name="in_c", type=t_any(), required=False, default=None),
    ],
    outputs=[PortSpec(name="sum", type=t_float())],
    params={},
)


@register_node(MERGER_SPEC)
class MergerNode(NodeBase):
    """Merges multiple inputs by summing them."""

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        a = coerce_number(inputs.get("in_a")) or 0.0
        b = coerce_number(inputs.get("in_b")) or 0.0
        c = coerce_number(inputs.get("in_c")) or 0.0
        result = a + b + c
        ctx.log(f"{self.id} merged {a} + {b} + {c} -> {result}")
        return {"sum": result}
