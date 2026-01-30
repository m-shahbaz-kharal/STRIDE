"""Debug and utility nodes."""
from __future__ import annotations

from typing import Any, Dict

from . import register_node
from .base import ExecutionContext, NodeBase
from ..node_spec import NodeSpec, PortSpec
from ..typesystem import t_any, t_boolean, t_control, t_string


# ============================================================================
# DEBUG & UTILITY
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
