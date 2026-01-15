from __future__ import annotations

from typing import Any, Dict

from . import register_node
from .base import ExecutionContext, NodeBase
from ..node_spec import NodeSpec, PortSpec
from ..typesystem import t_any, t_boolean, t_control, t_float, t_int, t_string


def _to_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        return 1 if value else 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _to_boolean(value: Any) -> bool:
    return bool(value)


CAST_TO_INT_SPEC = NodeSpec(
    type="core.cast.to_int",
    version="1.0.0",
    display_name="To Int",
    category="Casting",
    summary="Cast value to int.",
    description="Converts the input to an integer.",
    icon="swap",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_int()),
    ],

)


@register_node(CAST_TO_INT_SPEC)
class CastToIntNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        value = _to_int(inputs.get("value"))
        ctx.log(f"{self.id} cast to int -> {value}")
        return {"control_out": None, "value": value}


CAST_TO_FLOAT_SPEC = NodeSpec(
    type="core.cast.to_float",
    version="1.0.0",
    display_name="To Float",
    category="Casting",
    summary="Cast value to float.",
    description="Converts the input to a float.",
    icon="swap",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_float()),
    ],

)


@register_node(CAST_TO_FLOAT_SPEC)
class CastToFloatNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        value = _to_float(inputs.get("value"))
        ctx.log(f"{self.id} cast to float -> {value}")
        return {"control_out": None, "value": value}


CAST_TO_STRING_SPEC = NodeSpec(
    type="core.cast.to_string",
    version="1.0.0",
    display_name="To String",
    category="Casting",
    summary="Cast value to string.",
    description="Converts the input to a string.",
    icon="swap",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_string()),
    ],

)


@register_node(CAST_TO_STRING_SPEC)
class CastToStringNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        value = _to_string(inputs.get("value"))
        ctx.log(f"{self.id} cast to string -> {value}")
        return {"control_out": None, "value": value}


CAST_TO_BOOLEAN_SPEC = NodeSpec(
    type="core.cast.to_boolean",
    version="1.0.0",
    display_name="To Boolean",
    category="Casting",
    summary="Cast value to boolean.",
    description="Converts the input to a boolean.",
    icon="swap",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_any(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_boolean()),
    ],

)


@register_node(CAST_TO_BOOLEAN_SPEC)
class CastToBooleanNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        value = _to_boolean(inputs.get("value"))
        ctx.log(f"{self.id} cast to boolean -> {value}")
        return {"control_out": None, "value": value}
