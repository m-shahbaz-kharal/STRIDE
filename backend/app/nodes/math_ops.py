from __future__ import annotations

import time
from typing import Any, Dict

from .base import ExecutionContext, NodeBase
from . import register_node


@register_node
class MultiplyNode(NodeBase):
    node_type = "math.multiply"
    display_name = "Multiply"
    description = "Multiplies two numbers together."
    icon = "times"
    params_schema: Dict[str, Any] = {}
    input_ports = ["a", "b"]
    output_ports = ["product"]

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        a_value = inputs.get("a", 0)
        b_value = inputs.get("b", 0)
        result = a_value * b_value
        ctx.log(f"{self.id} multiplied {a_value} * {b_value} -> {result}")
        return {"product": result}


@register_node
class SubtractNode(NodeBase):
    node_type = "math.subtract"
    display_name = "Subtract"
    description = "Subtracts second number from first."
    icon = "minus"
    params_schema: Dict[str, Any] = {}
    input_ports = ["a", "b"]
    output_ports = ["difference"]

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        a_value = inputs.get("a", 0)
        b_value = inputs.get("b", 0)
        result = a_value - b_value
        ctx.log(f"{self.id} subtracted {a_value} - {b_value} -> {result}")
        return {"difference": result}


@register_node
class DivideNode(NodeBase):
    node_type = "math.divide"
    display_name = "Divide"
    description = "Divides first number by second."
    icon = "divide"
    params_schema: Dict[str, Any] = {}
    input_ports = ["a", "b"]
    output_ports = ["quotient"]

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        a_value = inputs.get("a", 0)
        b_value = inputs.get("b", 1)
        if b_value == 0:
            ctx.log(f"{self.id} division by zero, returning 0")
            return {"quotient": 0}
        result = a_value / b_value
        ctx.log(f"{self.id} divided {a_value} / {b_value} -> {result}")
        return {"quotient": result}


@register_node
class PowerNode(NodeBase):
    node_type = "math.power"
    display_name = "Power"
    description = "Raises base to the power of exponent."
    icon = "superscript"
    params_schema: Dict[str, Any] = {}
    input_ports = ["base", "exponent"]
    output_ports = ["result"]

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        base = inputs.get("base", 0)
        exponent = inputs.get("exponent", 1)
        result = base ** exponent
        ctx.log(f"{self.id} computed {base} ^ {exponent} -> {result}")
        return {"result": result}


@register_node
class AbsoluteNode(NodeBase):
    node_type = "math.abs"
    display_name = "Absolute"
    description = "Returns absolute value of input."
    icon = "abs"
    params_schema: Dict[str, Any] = {}
    input_ports = ["value"]
    output_ports = ["result"]

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        value = inputs.get("value", 0)
        result = abs(value)
        ctx.log(f"{self.id} abs({value}) -> {result}")
        return {"result": result}


@register_node
class DelayNode(NodeBase):
    """Simulates a slow operation for testing parallel execution."""
    node_type = "util.delay"
    display_name = "Delay"
    description = "Passes through value after a configurable delay. Useful for testing parallel execution."
    icon = "clock"
    params_schema = {
        "delay_ms": {
            "type": "number",
            "label": "Delay (ms)",
            "description": "Milliseconds to wait before producing output.",
            "default": 100,
        }
    }
    input_ports = ["value"]
    output_ports = ["value"]

    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__(config)
        self._delay_ms = config.get("params", {}).get("delay_ms", 100)

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        value = inputs.get("value")
        time.sleep(self._delay_ms / 1000.0)
        ctx.log(f"{self.id} delayed {self._delay_ms}ms, passing {value}")
        return {"value": value}


@register_node
class SplitterNode(NodeBase):
    """Splits a single input into multiple identical outputs for parallel branches."""
    node_type = "util.splitter"
    display_name = "Splitter"
    description = "Splits a single value into multiple outputs for parallel processing branches."
    icon = "split"
    params_schema: Dict[str, Any] = {}
    input_ports = ["input"]
    output_ports = ["out_a", "out_b", "out_c"]

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        value = inputs.get("input")
        ctx.log(f"{self.id} splitting {value} to 3 outputs")
        return {"out_a": value, "out_b": value, "out_c": value}


@register_node 
class MergerNode(NodeBase):
    """Merges multiple inputs by summing them."""
    node_type = "util.merger"
    display_name = "Merger"
    description = "Merges multiple inputs by summing them together."
    icon = "merge"
    params_schema: Dict[str, Any] = {}
    input_ports = ["in_a", "in_b", "in_c"]
    output_ports = ["sum"]

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        a = inputs.get("in_a", 0)
        b = inputs.get("in_b", 0)
        c = inputs.get("in_c", 0)
        result = a + b + c
        ctx.log(f"{self.id} merged {a} + {b} + {c} -> {result}")
        return {"sum": result}

