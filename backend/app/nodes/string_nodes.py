"""String manipulation nodes."""
from __future__ import annotations

from typing import Any, Dict

from . import register_node
from .base import ExecutionContext, NodeBase
from ..node_spec import NodeSpec, PortSpec
from ..typesystem import t_any, t_boolean, t_control, t_int, t_list, t_string


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
