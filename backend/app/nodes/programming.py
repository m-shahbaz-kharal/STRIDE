from __future__ import annotations

from typing import Any, Dict

from . import register_node
from .base import ExecutionContext, NodeBase
from ..node_spec import NodeSpec, PortSpec
from ..typesystem import (
    t_any,
    t_boolean,
    t_int,
    t_string,
    t_control,
)


# Variables
VAR_DECLARE_SPEC = NodeSpec(
    type="core.var.declare",
    version="1.0.0",
    display_name="Declare Variable",
    category="Variables",
    summary="Declare a variable with an optional initial value.",
    description="Creates or resets a graph-scoped variable.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="name", type=t_string(), required=False, default="var"),
        PortSpec(name="value", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any()),
    ],
    cache_policy="disabled",
)


@register_node(VAR_DECLARE_SPEC)
class VariableDeclareNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        name = str(inputs.get("name") or self.params.get("name", "var"))
        value = inputs.get("value")
        ctx.set_var(name, value)
        ctx.log(f"Declared variable '{name}' = {value}")
        return {"control_out": None, "value": value}


VAR_SET_SPEC = NodeSpec(
    type="core.var.set",
    version="1.0.0",
    display_name="Set Variable",
    category="Variables",
    summary="Set an existing variable.",
    description="Assigns a value to a graph-scoped variable.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="name", type=t_string(), required=False, default="var"),
        PortSpec(name="value", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any()),
    ],
    cache_policy="disabled",
)


@register_node(VAR_SET_SPEC)
class VariableSetNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        name = str(inputs.get("name") or self.params.get("name", "var"))
        value = inputs.get("value")
        ctx.set_var(name, value)
        ctx.log(f"Set variable '{name}' = {value}")
        return {"control_out": None, "value": value}


VAR_GET_SPEC = NodeSpec(
    type="core.var.get",
    version="1.0.0",
    display_name="Get Variable",
    category="Variables",
    summary="Read a variable.",
    description="Reads a graph-scoped variable, returning a default if missing.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="name", type=t_string(), required=False, default="var"),
        PortSpec(name="default", type=t_any(), required=False, default=""),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any()),
    ],
    cache_policy="disabled",
)


@register_node(VAR_GET_SPEC)
class VariableGetNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        name = str(inputs.get("name") or self.params.get("name", "var"))
        default = inputs.get("default") if "default" in inputs else self.params.get("default", "")
        value = ctx.get_var(name, default)
        ctx.log(f"Get variable '{name}' -> {value}")
        return {"control_out": None, "value": value}


# Expressions / operators
COMPARE_SPEC = NodeSpec(
    type="core.logic.compare",
    version="1.0.0",
    display_name="Compare",
    category="Logic",
    summary="Compare two values.",
    description="Performs a comparison between two inputs.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="a", type=t_any(), required=False, default=None),
        PortSpec(name="b", type=t_any(), required=False, default=None),
        PortSpec(
            name="op",
            type=t_string(),
            required=False,
            default="==",
            ui={"control": "select", "options": ["==", "!=", ">", ">=", "<", "<="]},
        ),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_boolean()),
    ],
)


@register_node(COMPARE_SPEC)
class CompareNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        a = inputs.get("a")
        b = inputs.get("b")
        op = inputs.get("op") or self.params.get("op", "==")
        result = False
        if op == "==":
            result = a == b
        elif op == "!=":
            result = a != b
        elif op == ">":
            result = a > b
        elif op == ">=":
            result = a >= b
        elif op == "<":
            result = a < b
        elif op == "<=":
            result = a <= b
        ctx.log(f"Compare {a} {op} {b} -> {result}")
        return {"control_out": None, "result": result}


BOOL_AND_SPEC = NodeSpec(
    type="core.logic.and",
    version="1.0.0",
    display_name="And",
    category="Logic",
    summary="Logical AND.",
    description="Returns true if both inputs are truthy.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="a", type=t_boolean(), required=False, default=False),
        PortSpec(name="b", type=t_boolean(), required=False, default=False),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_boolean()),
    ],
)


@register_node(BOOL_AND_SPEC)
class BooleanAndNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        result = bool(inputs.get("a")) and bool(inputs.get("b"))
        ctx.log(f"And -> {result}")
        return {"control_out": None, "result": result}


BOOL_OR_SPEC = NodeSpec(
    type="core.logic.or",
    version="1.0.0",
    display_name="Or",
    category="Logic",
    summary="Logical OR.",
    description="Returns true if either input is truthy.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="a", type=t_boolean(), required=False, default=False),
        PortSpec(name="b", type=t_boolean(), required=False, default=False),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_boolean()),
    ],
)


@register_node(BOOL_OR_SPEC)
class BooleanOrNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        result = bool(inputs.get("a")) or bool(inputs.get("b"))
        ctx.log(f"Or -> {result}")
        return {"control_out": None, "result": result}


BOOL_NOT_SPEC = NodeSpec(
    type="core.logic.not",
    version="1.0.0",
    display_name="Not",
    category="Logic",
    summary="Logical NOT.",
    description="Returns the negation of the input.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_boolean(), required=False, default=False),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_boolean()),
    ],
)


@register_node(BOOL_NOT_SPEC)
class BooleanNotNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        result = not bool(inputs.get("value"))
        ctx.log(f"Not -> {result}")
        return {"control_out": None, "result": result}


STRING_CONCAT_SPEC = NodeSpec(
    type="core.string.concat",
    version="1.0.0",
    display_name="Concat",
    category="Strings",
    summary="Concatenate two values as strings.",
    description="Concatenate two inputs into a single string.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="a", type=t_any(), required=False, default=""),
        PortSpec(name="b", type=t_any(), required=False, default=""),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="result", type=t_string()),
    ],
)


@register_node(STRING_CONCAT_SPEC)
class StringConcatNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        a = inputs.get("a", "")
        b = inputs.get("b", "")
        result = f"{a}{b}"
        ctx.log(f"Concat -> {result}")
        return {"control_out": None, "result": result}


LENGTH_SPEC = NodeSpec(
    type="core.container.length",
    version="1.0.0",
    display_name="Length",
    category="Containers",
    summary="Length of string/list/map.",
    description="Returns len(value) when supported.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="length", type=t_int()),
    ],
)


@register_node(LENGTH_SPEC)
class LengthNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        value = inputs.get("value")
        try:
            result = len(value)  # type: ignore[arg-type]
        except Exception:
            result = 0
        ctx.log(f"Length -> {result}")
        return {"control_out": None, "length": result}


MAP_GET_SPEC = NodeSpec(
    type="core.container.get",
    version="1.0.0",
    display_name="Get Key",
    category="Containers",
    summary="Get value from map/object.",
    description="Returns map[key] with optional default.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="map", type=t_any(), required=False, default=None),
        PortSpec(name="key", type=t_any(), required=False, default=None),
        PortSpec(name="default", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any()),
    ],
)


@register_node(MAP_GET_SPEC)
class MapGetNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        mapping = inputs.get("map") or {}
        key = inputs.get("key")
        default = inputs.get("default")
        value = mapping.get(key, default) if isinstance(mapping, dict) else default
        ctx.log(f"Get key '{key}' -> {value}")
        return {"control_out": None, "value": value}


# Control flow
IF_ELSE_SPEC = NodeSpec(
    type="core.control.ifelse",
    version="1.0.0",
    display_name="If / Else",
    category="Control",
    summary="Branch execution based on condition.",
    description="Executes the True branch when condition is truthy, else the False branch.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="condition", type=t_boolean(), required=False, default=False),
    ],
    outputs=[
        PortSpec(name="true", type=t_control(), required=False, default=None),
        PortSpec(name="false", type=t_control(), required=False, default=None),
    ],
)


@register_node(IF_ELSE_SPEC)
class IfElseNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        cond = bool(inputs.get("condition"))
        ctx.log(f"IfElse cond={cond} -> {'True' if cond else 'False'} branch")
        return {"true": None, "false": None}


FOR_LOOP_SPEC = NodeSpec(
    type="core.control.for",
    version="1.0.0",
    display_name="For Loop",
    category="Control",
    summary="Iterate from first to last index.",
    description="Blueprint-style for loop with control pins and an index output.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="first_index", type=t_int(), required=False, default=0),
        PortSpec(name="last_index", type=t_int(), required=False, default=0),
    ],
    outputs=[
        PortSpec(name="loop_body", type=t_control(), required=False, default=None),
        PortSpec(name="index", type=t_int()),
        PortSpec(name="completed", type=t_control(), required=False, default=None),
    ],
)


@register_node(FOR_LOOP_SPEC)
class ForLoopNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        first_index = int(inputs.get("first_index") or 0)
        last_index = int(inputs.get("last_index") or 0)
        ctx.log(f"ForLoop range {first_index}..{last_index}")
        return {"loop_body": None, "index": first_index, "completed": None}


REPEAT_LOOP_SPEC = NodeSpec(
    type="core.control.repeat",
    version="1.0.0",
    display_name="Repeat",
    category="Control",
    summary="Repeat N times.",
    description="Executes the loop body a fixed number of times.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="count", type=t_int(), required=False, default=1),
    ],
    outputs=[
        PortSpec(name="loop_body", type=t_control(), required=False, default=None),
        PortSpec(name="index", type=t_int()),
        PortSpec(name="completed", type=t_control(), required=False, default=None),
    ],
)


@register_node(REPEAT_LOOP_SPEC)
class RepeatLoopNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        count = int(inputs.get("count") or 0)
        ctx.log(f"Repeat count {count}")
        return {"loop_body": None, "index": 0, "completed": None}


WHILE_LOOP_SPEC = NodeSpec(
    type="core.control.while",
    version="1.0.0",
    display_name="While",
    category="Control",
    summary="Repeat while condition is true.",
    description="Executes the loop body while condition remains true, with a max iteration safeguard.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="condition", type=t_boolean(), required=False, default=False),
        PortSpec(name="max_iterations", type=t_int(), required=False, default=100),
    ],
    outputs=[
        PortSpec(name="loop_body", type=t_control(), required=False, default=None),
        PortSpec(name="index", type=t_int()),
        PortSpec(name="completed", type=t_control(), required=False, default=None),
    ],
)


@register_node(WHILE_LOOP_SPEC)
class WhileLoopNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        condition = bool(inputs.get("condition"))
        ctx.log(f"While condition {condition}")
        return {"loop_body": None, "index": 0, "completed": None}
