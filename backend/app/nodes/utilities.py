from __future__ import annotations

import math
import random
import time
import json
import re
from typing import Any, Dict

from . import register_node
from .base import ExecutionContext, NodeBase
from ..node_spec import NodeSpec, PortSpec
from ..typesystem import t_any, t_boolean, t_control, t_float, t_int, t_string, t_list


# ============================================================================
# STRING OPERATIONS
# ============================================================================

STRING_UPPER_SPEC = NodeSpec(
    type="core.string.upper",
    version="1.0.0",
    display_name="Uppercase",
    category="Strings",
    summary="Convert string to uppercase.",
    description="Returns the input string in all uppercase characters.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="text", type=t_string(), required=False, default=""),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_string()),
    ],
)


@register_node(STRING_UPPER_SPEC)
class StringUpperNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        text = str(inputs.get("text") or "")
        result = text.upper()
        ctx.log(f"Uppercase -> {result}")
        return {"control_out": None, "result": result}


STRING_LOWER_SPEC = NodeSpec(
    type="core.string.lower",
    version="1.0.0",
    display_name="Lowercase",
    category="Strings",
    summary="Convert string to lowercase.",
    description="Returns the input string in all lowercase characters.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="text", type=t_string(), required=False, default=""),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_string()),
    ],
)


@register_node(STRING_LOWER_SPEC)
class StringLowerNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        text = str(inputs.get("text") or "")
        result = text.lower()
        ctx.log(f"Lowercase -> {result}")
        return {"control_out": None, "result": result}


STRING_TRIM_SPEC = NodeSpec(
    type="core.string.trim",
    version="1.0.0",
    display_name="Trim",
    category="Strings",
    summary="Remove whitespace from both ends.",
    description="Strips leading and trailing whitespace from a string.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="text", type=t_string(), required=False, default=""),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_string()),
    ],
)


@register_node(STRING_TRIM_SPEC)
class StringTrimNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        text = str(inputs.get("text") or "")
        result = text.strip()
        ctx.log(f"Trim -> {result}")
        return {"control_out": None, "result": result}


STRING_SPLIT_SPEC = NodeSpec(
    type="core.string.split",
    version="1.0.0",
    display_name="Split",
    category="Strings",
    summary="Split string by delimiter.",
    description="Splits a string into an array using the specified delimiter.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="text", type=t_string(), required=False, default=""),
        PortSpec(name="delimiter", type=t_string(), required=False, default=","),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="parts", type=t_list(t_string())),
    ],
)


@register_node(STRING_SPLIT_SPEC)
class StringSplitNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        text = str(inputs.get("text") or "")
        delimiter = str(inputs.get("delimiter") or ",")
        parts = text.split(delimiter) if delimiter else [text]
        ctx.log(f"Split -> {len(parts)} parts")
        return {"control_out": None, "parts": parts}


STRING_JOIN_SPEC = NodeSpec(
    type="core.string.join",
    version="1.0.0",
    display_name="Join",
    category="Strings",
    summary="Join array with delimiter.",
    description="Joins an array of values into a string using the specified delimiter.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="array", type=t_list(t_any()), required=False, default=None),
        PortSpec(name="delimiter", type=t_string(), required=False, default=","),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_string()),
    ],
)


@register_node(STRING_JOIN_SPEC)
class StringJoinNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        array = inputs.get("array") or []
        delimiter = str(inputs.get("delimiter") or ",")
        result = delimiter.join(str(item) for item in array)
        ctx.log(f"Join -> {result}")
        return {"control_out": None, "result": result}


STRING_REPLACE_SPEC = NodeSpec(
    type="core.string.replace",
    version="1.0.0",
    display_name="Replace",
    category="Strings",
    summary="Replace occurrences in string.",
    description="Replaces all occurrences of a pattern with replacement text.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="text", type=t_string(), required=False, default=""),
        PortSpec(name="find", type=t_string(), required=False, default=""),
        PortSpec(name="replace", type=t_string(), required=False, default=""),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_string()),
    ],
)


@register_node(STRING_REPLACE_SPEC)
class StringReplaceNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        text = str(inputs.get("text") or "")
        find = str(inputs.get("find") or "")
        replace_with = str(inputs.get("replace") or "")
        result = text.replace(find, replace_with) if find else text
        ctx.log(f"Replace -> {result}")
        return {"control_out": None, "result": result}


STRING_CONTAINS_SPEC = NodeSpec(
    type="core.string.contains",
    version="1.0.0",
    display_name="Contains",
    category="Strings",
    summary="Check if string contains substring.",
    description="Returns true if the text contains the search string.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="text", type=t_string(), required=False, default=""),
        PortSpec(name="search", type=t_string(), required=False, default=""),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_boolean()),
    ],
)


@register_node(STRING_CONTAINS_SPEC)
class StringContainsNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        text = str(inputs.get("text") or "")
        search = str(inputs.get("search") or "")
        result = search in text
        ctx.log(f"Contains '{search}' -> {result}")
        return {"control_out": None, "result": result}


STRING_STARTS_WITH_SPEC = NodeSpec(
    type="core.string.starts_with",
    version="1.0.0",
    display_name="Starts With",
    category="Strings",
    summary="Check if string starts with prefix.",
    description="Returns true if the text starts with the specified prefix.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="text", type=t_string(), required=False, default=""),
        PortSpec(name="prefix", type=t_string(), required=False, default=""),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_boolean()),
    ],
)


@register_node(STRING_STARTS_WITH_SPEC)
class StringStartsWithNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        text = str(inputs.get("text") or "")
        prefix = str(inputs.get("prefix") or "")
        result = text.startswith(prefix)
        ctx.log(f"StartsWith '{prefix}' -> {result}")
        return {"control_out": None, "result": result}


STRING_ENDS_WITH_SPEC = NodeSpec(
    type="core.string.ends_with",
    version="1.0.0",
    display_name="Ends With",
    category="Strings",
    summary="Check if string ends with suffix.",
    description="Returns true if the text ends with the specified suffix.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="text", type=t_string(), required=False, default=""),
        PortSpec(name="suffix", type=t_string(), required=False, default=""),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_boolean()),
    ],
)


@register_node(STRING_ENDS_WITH_SPEC)
class StringEndsWithNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        text = str(inputs.get("text") or "")
        suffix = str(inputs.get("suffix") or "")
        result = text.endswith(suffix)
        ctx.log(f"EndsWith '{suffix}' -> {result}")
        return {"control_out": None, "result": result}


STRING_SUBSTRING_SPEC = NodeSpec(
    type="core.string.substring",
    version="1.0.0",
    display_name="Substring",
    category="Strings",
    summary="Extract part of string.",
    description="Returns a substring from start index to end index.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="text", type=t_string(), required=False, default=""),
        PortSpec(name="start", type=t_int(), required=False, default=0),
        PortSpec(name="end", type=t_int(), required=False, default=-1),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_string()),
    ],
)


@register_node(STRING_SUBSTRING_SPEC)
class StringSubstringNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        text = str(inputs.get("text") or "")
        start = int(inputs.get("start") or 0)
        end = inputs.get("end")
        if end is None or end == -1:
            result = text[start:]
        else:
            result = text[start:int(end)]
        ctx.log(f"Substring [{start}:{end}] -> {result}")
        return {"control_out": None, "result": result}


STRING_FORMAT_SPEC = NodeSpec(
    type="core.string.format",
    version="1.0.0",
    display_name="Format",
    category="Strings",
    summary="Format string with values.",
    description="Formats a template string with provided values using Python's format().",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="template", type=t_string(), required=False, default=""),
        PortSpec(name="arg1", type=t_any(), required=False, default=""),
        PortSpec(name="arg2", type=t_any(), required=False, default=""),
        PortSpec(name="arg3", type=t_any(), required=False, default=""),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_string()),
    ],
)


@register_node(STRING_FORMAT_SPEC)
class StringFormatNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        template = str(inputs.get("template") or "")
        args = [inputs.get("arg1", ""), inputs.get("arg2", ""), inputs.get("arg3", "")]
        try:
            result = template.format(*args)
        except Exception:
            result = template
        ctx.log(f"Format -> {result}")
        return {"control_out": None, "result": result}


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


# ============================================================================
# TIME & RANDOM
# ============================================================================

TIME_NOW_SPEC = NodeSpec(
    type="core.time.now",
    version="1.0.0",
    display_name="Now",
    category="Time",
    summary="Get current timestamp.",
    description="Returns the current Unix timestamp in seconds.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="timestamp", type=t_float()),
    ],
    cache_policy="disabled",
)


@register_node(TIME_NOW_SPEC)
class TimeNowNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        timestamp = time.time()
        ctx.log(f"Now -> {timestamp}")
        return {"control_out": None, "timestamp": timestamp}


TIME_DELAY_SPEC = NodeSpec(
    type="core.time.delay",
    version="1.0.0",
    display_name="Delay",
    category="Time",
    summary="Pause execution for seconds.",
    description="Pauses execution for the specified number of seconds.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="seconds", type=t_float(), required=False, default=1.0),
        PortSpec(name="passthrough", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="passthrough", type=t_any()),
    ],
    cache_policy="disabled",
)


@register_node(TIME_DELAY_SPEC)
class TimeDelayNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        seconds = float(inputs.get("seconds") or 1.0)
        passthrough = inputs.get("passthrough")
        time.sleep(max(0, min(seconds, 60)))  # Cap at 60s for safety
        ctx.log(f"Delayed {seconds}s")
        return {"control_out": None, "passthrough": passthrough}


RANDOM_FLOAT_SPEC = NodeSpec(
    type="core.random.float",
    version="1.0.0",
    display_name="Random Float",
    category="Random",
    summary="Generate random float.",
    description="Generates a random float between min and max (inclusive).",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="min", type=t_float(), required=False, default=0.0),
        PortSpec(name="max", type=t_float(), required=False, default=1.0),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_float()),
    ],
    cache_policy="disabled",
)


@register_node(RANDOM_FLOAT_SPEC)
class RandomFloatNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        min_val = float(inputs.get("min") or 0.0)
        max_val = float(inputs.get("max") or 1.0)
        value = random.uniform(min_val, max_val)
        ctx.log(f"Random float [{min_val}, {max_val}] -> {value}")
        return {"control_out": None, "value": value}


RANDOM_INT_SPEC = NodeSpec(
    type="core.random.int",
    version="1.0.0",
    display_name="Random Int",
    category="Random",
    summary="Generate random integer.",
    description="Generates a random integer between min and max (inclusive).",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="min", type=t_int(), required=False, default=0),
        PortSpec(name="max", type=t_int(), required=False, default=100),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_int()),
    ],
    cache_policy="disabled",
)


@register_node(RANDOM_INT_SPEC)
class RandomIntNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        min_val = int(inputs.get("min") or 0)
        max_val = int(inputs.get("max") or 100)
        value = random.randint(min_val, max_val)
        ctx.log(f"Random int [{min_val}, {max_val}] -> {value}")
        return {"control_out": None, "value": value}


RANDOM_BOOLEAN_SPEC = NodeSpec(
    type="core.random.boolean",
    version="1.0.0",
    display_name="Random Boolean",
    category="Random",
    summary="Generate random true/false.",
    description="Generates a random boolean with specified probability of being true.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="probability", type=t_float(), required=False, default=0.5),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_boolean()),
    ],
    cache_policy="disabled",
)


@register_node(RANDOM_BOOLEAN_SPEC)
class RandomBooleanNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        probability = float(inputs.get("probability") or 0.5)
        value = random.random() < probability
        ctx.log(f"Random boolean (p={probability}) -> {value}")
        return {"control_out": None, "value": value}


RANDOM_CHOICE_SPEC = NodeSpec(
    type="core.random.choice",
    version="1.0.0",
    display_name="Random Choice",
    category="Random",
    summary="Pick random item from array.",
    description="Selects a random element from an array.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="array", type=t_list(t_any()), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any()),
        PortSpec(name="index", type=t_int()),
    ],
    cache_policy="disabled",
)


@register_node(RANDOM_CHOICE_SPEC)
class RandomChoiceNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        array = inputs.get("array") or []
        if not array:
            ctx.log("Random choice: empty array")
            return {"control_out": None, "value": None, "index": -1}
        index = random.randint(0, len(array) - 1)
        value = array[index]
        ctx.log(f"Random choice -> index {index}: {value}")
        return {"control_out": None, "value": value, "index": index}


# ============================================================================
# JSON & DATA
# ============================================================================

JSON_PARSE_SPEC = NodeSpec(
    type="core.json.parse",
    version="1.0.0",
    display_name="Parse JSON",
    category="JSON",
    summary="Parse JSON string to object.",
    description="Parses a JSON string into a Python object.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="json_string", type=t_string(), required=False, default="{}"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="data", type=t_any()),
        PortSpec(name="success", type=t_boolean()),
    ],
)


@register_node(JSON_PARSE_SPEC)
class JsonParseNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        json_string = str(inputs.get("json_string") or "{}")
        try:
            data = json.loads(json_string)
            ctx.log(f"Parsed JSON successfully")
            return {"control_out": None, "data": data, "success": True}
        except Exception as e:
            ctx.log(f"JSON parse error: {e}")
            return {"control_out": None, "data": None, "success": False}


JSON_STRINGIFY_SPEC = NodeSpec(
    type="core.json.stringify",
    version="1.0.0",
    display_name="Stringify JSON",
    category="JSON",
    summary="Convert object to JSON string.",
    description="Converts a Python object to a JSON string.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="data", type=t_any(), required=False, default=None),
        PortSpec(name="pretty", type=t_boolean(), required=False, default=False),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="json_string", type=t_string()),
    ],
)


@register_node(JSON_STRINGIFY_SPEC)
class JsonStringifyNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        data = inputs.get("data")
        pretty = bool(inputs.get("pretty"))
        try:
            indent = 2 if pretty else None
            result = json.dumps(data, indent=indent, default=str)
        except Exception:
            result = str(data)
        ctx.log(f"Stringified to JSON")
        return {"control_out": None, "json_string": result}


# ============================================================================
# DEBUG & DISPLAY
# ============================================================================

DEBUG_LOG_SPEC = NodeSpec(
    type="core.debug.log",
    version="1.0.0",
    display_name="Log",
    category="Debug",
    summary="Log a value to execution trace.",
    description="Logs a value with an optional label to the execution trace.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any(), required=False, default=None),
        PortSpec(name="label", type=t_string(), required=False, default=""),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any()),
    ],
    cache_policy="disabled",
)


@register_node(DEBUG_LOG_SPEC)
class DebugLogNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        value = inputs.get("value")
        label = inputs.get("label") or "Log"
        ctx.log(f"[{label}] {value}")
        return {"control_out": None, "value": value}


DEBUG_BREAKPOINT_SPEC = NodeSpec(
    type="core.debug.breakpoint",
    version="1.0.0",
    display_name="Breakpoint",
    category="Debug",
    summary="Pause and inspect value.",
    description="Logs the value and pauses briefly for debugging.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any(), required=False, default=None),
        PortSpec(name="enabled", type=t_boolean(), required=False, default=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any()),
    ],
    cache_policy="disabled",
)


@register_node(DEBUG_BREAKPOINT_SPEC)
class DebugBreakpointNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        value = inputs.get("value")
        enabled = inputs.get("enabled", True)
        if enabled:
            ctx.log(f"[BREAKPOINT] Value: {value}")
        return {"control_out": None, "value": value}


TYPE_OF_SPEC = NodeSpec(
    type="core.util.typeof",
    version="1.0.0",
    display_name="Type Of",
    category="Utility",
    summary="Get type name of value.",
    description="Returns the type name of the input value.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="type_name", type=t_string()),
    ],
)


@register_node(TYPE_OF_SPEC)
class TypeOfNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        value = inputs.get("value")
        type_name = type(value).__name__
        ctx.log(f"TypeOf -> {type_name}")
        return {"control_out": None, "type_name": type_name}


IS_NULL_SPEC = NodeSpec(
    type="core.util.is_null",
    version="1.0.0",
    display_name="Is Null",
    category="Utility",
    summary="Check if value is null/None.",
    description="Returns true if the value is None.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="is_null", type=t_boolean()),
    ],
)


@register_node(IS_NULL_SPEC)
class IsNullNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        value = inputs.get("value")
        is_null = value is None
        ctx.log(f"IsNull -> {is_null}")
        return {"control_out": None, "is_null": is_null}


COALESCE_SPEC = NodeSpec(
    type="core.util.coalesce",
    version="1.0.0",
    display_name="Coalesce",
    category="Utility",
    summary="Return first non-null value.",
    description="Returns the first non-null value from the inputs.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="a", type=t_any(), required=False, default=None),
        PortSpec(name="b", type=t_any(), required=False, default=None),
        PortSpec(name="c", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any()),
    ],
)


@register_node(COALESCE_SPEC)
class CoalesceNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        for key in ["a", "b", "c"]:
            value = inputs.get(key)
            if value is not None:
                ctx.log(f"Coalesce -> {value}")
                return {"control_out": None, "value": value}
        ctx.log("Coalesce -> None (all null)")
        return {"control_out": None, "value": None}


PASSTHROUGH_SPEC = NodeSpec(
    type="core.util.passthrough",
    version="1.0.0",
    display_name="Passthrough",
    category="Utility",
    summary="Pass value unchanged.",
    description="Simply passes the input value to output without modification.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any()),
    ],
)


@register_node(PASSTHROUGH_SPEC)
class PassthroughNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        value = inputs.get("value")
        ctx.log(f"Passthrough -> {value}")
        return {"control_out": None, "value": value}


# ============================================================================
# ARRAY OPERATIONS
# ============================================================================

ARRAY_FIRST_SPEC = NodeSpec(
    type="core.array.first",
    version="1.0.0",
    display_name="First",
    category="Arrays",
    summary="Get first item of array.",
    description="Returns the first element of an array.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="array", type=t_list(t_any()), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any()),
    ],
)


@register_node(ARRAY_FIRST_SPEC)
class ArrayFirstNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        array = inputs.get("array") or []
        value = array[0] if array else None
        ctx.log(f"First -> {value}")
        return {"control_out": None, "value": value}


ARRAY_LAST_SPEC = NodeSpec(
    type="core.array.last",
    version="1.0.0",
    display_name="Last",
    category="Arrays",
    summary="Get last item of array.",
    description="Returns the last element of an array.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="array", type=t_list(t_any()), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any()),
    ],
)


@register_node(ARRAY_LAST_SPEC)
class ArrayLastNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        array = inputs.get("array") or []
        value = array[-1] if array else None
        ctx.log(f"Last -> {value}")
        return {"control_out": None, "value": value}


ARRAY_SLICE_SPEC = NodeSpec(
    type="core.array.slice",
    version="1.0.0",
    display_name="Slice",
    category="Arrays",
    summary="Get portion of array.",
    description="Returns a slice of an array from start to end index.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="array", type=t_list(t_any()), required=False, default=None),
        PortSpec(name="start", type=t_int(), required=False, default=0),
        PortSpec(name="end", type=t_int(), required=False, default=-1),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_list(t_any())),
    ],
)


@register_node(ARRAY_SLICE_SPEC)
class ArraySliceNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        array = inputs.get("array") or []
        start = int(inputs.get("start") or 0)
        end = inputs.get("end")
        if end is None or end == -1:
            result = array[start:]
        else:
            result = array[start:int(end)]
        ctx.log(f"Slice [{start}:{end}] -> {len(result)} items")
        return {"control_out": None, "result": result}


ARRAY_REVERSE_SPEC = NodeSpec(
    type="core.array.reverse",
    version="1.0.0",
    display_name="Reverse",
    category="Arrays",
    summary="Reverse array order.",
    description="Returns the array in reverse order.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="array", type=t_list(t_any()), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_list(t_any())),
    ],
)


@register_node(ARRAY_REVERSE_SPEC)
class ArrayReverseNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        array = inputs.get("array") or []
        result = list(reversed(array))
        ctx.log(f"Reverse -> {len(result)} items")
        return {"control_out": None, "result": result}


ARRAY_SORT_SPEC = NodeSpec(
    type="core.array.sort",
    version="1.0.0",
    display_name="Sort",
    category="Arrays",
    summary="Sort array elements.",
    description="Returns the array sorted in ascending or descending order.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="array", type=t_list(t_any()), required=False, default=None),
        PortSpec(name="descending", type=t_boolean(), required=False, default=False),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_list(t_any())),
    ],
)


@register_node(ARRAY_SORT_SPEC)
class ArraySortNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        array = inputs.get("array") or []
        descending = bool(inputs.get("descending"))
        try:
            result = sorted(array, reverse=descending)
        except TypeError:
            result = list(array)
        ctx.log(f"Sort (desc={descending}) -> {len(result)} items")
        return {"control_out": None, "result": result}


ARRAY_CONTAINS_SPEC = NodeSpec(
    type="core.array.contains",
    version="1.0.0",
    display_name="Contains",
    category="Arrays",
    summary="Check if array contains value.",
    description="Returns true if the array contains the specified value.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="array", type=t_list(t_any()), required=False, default=None),
        PortSpec(name="value", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_boolean()),
    ],
)


@register_node(ARRAY_CONTAINS_SPEC)
class ArrayContainsNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        array = inputs.get("array") or []
        value = inputs.get("value")
        result = value in array
        ctx.log(f"Contains {value} -> {result}")
        return {"control_out": None, "result": result}


ARRAY_INDEX_OF_SPEC = NodeSpec(
    type="core.array.index_of",
    version="1.0.0",
    display_name="Index Of",
    category="Arrays",
    summary="Find index of value in array.",
    description="Returns the index of the first occurrence of a value, or -1 if not found.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="array", type=t_list(t_any()), required=False, default=None),
        PortSpec(name="value", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="index", type=t_int()),
    ],
)


@register_node(ARRAY_INDEX_OF_SPEC)
class ArrayIndexOfNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        array = inputs.get("array") or []
        value = inputs.get("value")
        try:
            index = array.index(value)
        except ValueError:
            index = -1
        ctx.log(f"IndexOf {value} -> {index}")
        return {"control_out": None, "index": index}


ARRAY_SUM_SPEC = NodeSpec(
    type="core.array.sum",
    version="1.0.0",
    display_name="Sum",
    category="Arrays",
    summary="Sum all array elements.",
    description="Returns the sum of all numeric elements in an array.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="array", type=t_list(t_any()), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_float()),
    ],
)


@register_node(ARRAY_SUM_SPEC)
class ArraySumNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        array = inputs.get("array") or []
        total = 0.0
        for item in array:
            try:
                total += float(item)
            except (ValueError, TypeError):
                pass
        ctx.log(f"Sum -> {total}")
        return {"control_out": None, "result": total}


ARRAY_AVERAGE_SPEC = NodeSpec(
    type="core.array.average",
    version="1.0.0",
    display_name="Average",
    category="Arrays",
    summary="Average of array elements.",
    description="Returns the average of all numeric elements in an array.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="array", type=t_list(t_any()), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_float()),
    ],
)


@register_node(ARRAY_AVERAGE_SPEC)
class ArrayAverageNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        array = inputs.get("array") or []
        values = []
        for item in array:
            try:
                values.append(float(item))
            except (ValueError, TypeError):
                pass
        result = sum(values) / len(values) if values else 0.0
        ctx.log(f"Average -> {result}")
        return {"control_out": None, "result": result}
