"""JSON parsing and serialization nodes."""
from __future__ import annotations

import json
from typing import Any, Dict

from . import register_node
from .base import ExecutionContext, NodeBase
from ..node_spec import NodeSpec, PortSpec
from ..typesystem import t_any, t_boolean, t_control, t_string


# ============================================================================
# JSON OPERATIONS
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
            ctx.log("Parsed JSON successfully")
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
        ctx.log("Stringified to JSON")
        return {"control_out": None, "json_string": result}
