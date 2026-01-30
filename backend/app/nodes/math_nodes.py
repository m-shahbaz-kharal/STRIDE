"""Math operation nodes."""
from __future__ import annotations

import math
from typing import Any, Dict

from . import register_node
from .base import ExecutionContext, NodeBase
from ..node_spec import NodeSpec, PortSpec
from ..typesystem import t_control, t_float, t_int


# ============================================================================
# MATH FUNCTIONS
# ============================================================================

MATH_MIN_SPEC = NodeSpec(
    type="core.math.min",
    version="1.0.0",
    display_name="Min",
    category="Math",
    summary="Minimum of two numbers.",
    description="Returns the smaller of two numbers.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="a", type=t_float(), required=False, default=0),
        PortSpec(name="b", type=t_float(), required=False, default=0),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_float()),
    ],
)


@register_node(MATH_MIN_SPEC)
class MathMinNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        a = float(inputs.get("a") or 0)
        b = float(inputs.get("b") or 0)
        result = min(a, b)
        ctx.log(f"Min({a}, {b}) -> {result}")
        return {"control_out": None, "result": result}


MATH_MAX_SPEC = NodeSpec(
    type="core.math.max",
    version="1.0.0",
    display_name="Max",
    category="Math",
    summary="Maximum of two numbers.",
    description="Returns the larger of two numbers.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="a", type=t_float(), required=False, default=0),
        PortSpec(name="b", type=t_float(), required=False, default=0),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_float()),
    ],
)


@register_node(MATH_MAX_SPEC)
class MathMaxNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        a = float(inputs.get("a") or 0)
        b = float(inputs.get("b") or 0)
        result = max(a, b)
        ctx.log(f"Max({a}, {b}) -> {result}")
        return {"control_out": None, "result": result}


MATH_CLAMP_SPEC = NodeSpec(
    type="core.math.clamp",
    version="1.0.0",
    display_name="Clamp",
    category="Math",
    summary="Clamp value between min and max.",
    description="Constrains a value to be within a specified range.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_float(), required=False, default=0),
        PortSpec(name="min", type=t_float(), required=False, default=0),
        PortSpec(name="max", type=t_float(), required=False, default=1),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_float()),
    ],
)


@register_node(MATH_CLAMP_SPEC)
class MathClampNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        value = float(inputs.get("value") or 0)
        min_val = float(inputs.get("min") or 0)
        max_val = float(inputs.get("max") or 1)
        result = max(min_val, min(max_val, value))
        ctx.log(f"Clamp({value}, {min_val}, {max_val}) -> {result}")
        return {"control_out": None, "result": result}


MATH_LERP_SPEC = NodeSpec(
    type="core.math.lerp",
    version="1.0.0",
    display_name="Lerp",
    category="Math",
    summary="Linear interpolation.",
    description="Linearly interpolates between a and b using t (0-1).",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="a", type=t_float(), required=False, default=0),
        PortSpec(name="b", type=t_float(), required=False, default=1),
        PortSpec(name="t", type=t_float(), required=False, default=0.5),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_float()),
    ],
)


@register_node(MATH_LERP_SPEC)
class MathLerpNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        a = float(inputs.get("a") or 0)
        b = float(inputs.get("b") or 1)
        t = float(inputs.get("t") or 0.5)
        result = a + (b - a) * t
        ctx.log(f"Lerp({a}, {b}, {t}) -> {result}")
        return {"control_out": None, "result": result}


MATH_ROUND_SPEC = NodeSpec(
    type="core.math.round",
    version="1.0.0",
    display_name="Round",
    category="Math",
    summary="Round to nearest integer.",
    description="Rounds a number to the nearest integer or specified decimals.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_float(), required=False, default=0),
        PortSpec(name="decimals", type=t_int(), required=False, default=0),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_float()),
    ],
)


@register_node(MATH_ROUND_SPEC)
class MathRoundNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        value = float(inputs.get("value") or 0)
        decimals = int(inputs.get("decimals") or 0)
        result = round(value, decimals)
        ctx.log(f"Round({value}, {decimals}) -> {result}")
        return {"control_out": None, "result": result}


MATH_FLOOR_SPEC = NodeSpec(
    type="core.math.floor",
    version="1.0.0",
    display_name="Floor",
    category="Math",
    summary="Round down to integer.",
    description="Returns the largest integer less than or equal to the input.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_float(), required=False, default=0),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_int()),
    ],
)


@register_node(MATH_FLOOR_SPEC)
class MathFloorNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        value = float(inputs.get("value") or 0)
        result = math.floor(value)
        ctx.log(f"Floor({value}) -> {result}")
        return {"control_out": None, "result": result}


MATH_CEIL_SPEC = NodeSpec(
    type="core.math.ceil",
    version="1.0.0",
    display_name="Ceiling",
    category="Math",
    summary="Round up to integer.",
    description="Returns the smallest integer greater than or equal to the input.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_float(), required=False, default=0),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_int()),
    ],
)


@register_node(MATH_CEIL_SPEC)
class MathCeilNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        value = float(inputs.get("value") or 0)
        result = math.ceil(value)
        ctx.log(f"Ceil({value}) -> {result}")
        return {"control_out": None, "result": result}


MATH_MOD_SPEC = NodeSpec(
    type="core.math.mod",
    version="1.0.0",
    display_name="Modulo",
    category="Math",
    summary="Remainder of division.",
    description="Returns the remainder when a is divided by b.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="a", type=t_float(), required=False, default=0),
        PortSpec(name="b", type=t_float(), required=False, default=1),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_float()),
    ],
)


@register_node(MATH_MOD_SPEC)
class MathModNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        a = float(inputs.get("a") or 0)
        b = float(inputs.get("b") or 1)
        if b == 0:
            result = 0
        else:
            result = a % b
        ctx.log(f"Mod({a}, {b}) -> {result}")
        return {"control_out": None, "result": result}


MATH_SQRT_SPEC = NodeSpec(
    type="core.math.sqrt",
    version="1.0.0",
    display_name="Square Root",
    category="Math",
    summary="Square root of a number.",
    description="Returns the square root of the input value.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_float(), required=False, default=0),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_float()),
    ],
)


@register_node(MATH_SQRT_SPEC)
class MathSqrtNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        value = float(inputs.get("value") or 0)
        result = math.sqrt(max(0, value))
        ctx.log(f"Sqrt({value}) -> {result}")
        return {"control_out": None, "result": result}


MATH_SIN_SPEC = NodeSpec(
    type="core.math.sin",
    version="1.0.0",
    display_name="Sine",
    category="Math",
    summary="Sine of angle (radians).",
    description="Returns the sine of the angle in radians.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="radians", type=t_float(), required=False, default=0),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_float()),
    ],
)


@register_node(MATH_SIN_SPEC)
class MathSinNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        radians = float(inputs.get("radians") or 0)
        result = math.sin(radians)
        ctx.log(f"Sin({radians}) -> {result}")
        return {"control_out": None, "result": result}


MATH_COS_SPEC = NodeSpec(
    type="core.math.cos",
    version="1.0.0",
    display_name="Cosine",
    category="Math",
    summary="Cosine of angle (radians).",
    description="Returns the cosine of the angle in radians.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="radians", type=t_float(), required=False, default=0),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_float()),
    ],
)


@register_node(MATH_COS_SPEC)
class MathCosNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        radians = float(inputs.get("radians") or 0)
        result = math.cos(radians)
        ctx.log(f"Cos({radians}) -> {result}")
        return {"control_out": None, "result": result}


MATH_DEGREES_SPEC = NodeSpec(
    type="core.math.degrees",
    version="1.0.0",
    display_name="To Degrees",
    category="Math",
    summary="Convert radians to degrees.",
    description="Converts an angle from radians to degrees.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="radians", type=t_float(), required=False, default=0),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="degrees", type=t_float()),
    ],
)


@register_node(MATH_DEGREES_SPEC)
class MathDegreesNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        radians = float(inputs.get("radians") or 0)
        result = math.degrees(radians)
        ctx.log(f"Degrees({radians}) -> {result}")
        return {"control_out": None, "degrees": result}


MATH_RADIANS_SPEC = NodeSpec(
    type="core.math.radians",
    version="1.0.0",
    display_name="To Radians",
    category="Math",
    summary="Convert degrees to radians.",
    description="Converts an angle from degrees to radians.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="degrees", type=t_float(), required=False, default=0),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="radians", type=t_float()),
    ],
)


@register_node(MATH_RADIANS_SPEC)
class MathRadiansNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        degrees = float(inputs.get("degrees") or 0)
        result = math.radians(degrees)
        ctx.log(f"Radians({degrees}) -> {result}")
        return {"control_out": None, "radians": result}
