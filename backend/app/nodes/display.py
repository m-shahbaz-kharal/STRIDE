from __future__ import annotations

from typing import Any, Dict

from . import register_node
from .base import ExecutionContext, NodeBase
from ..node_spec import NodeSpec, PortSpec
from ..typesystem import t_any, t_control, t_string

DISPLAY_NODE_SPEC = NodeSpec(
    type="general.to_display",
    version="1.0.0",
    display_name="To Display",
    category="General",
    summary="Send data to the Display tab.",
    description="Captures its input value and sends it to the Display tab in the frontend, organized by section and title.",
    icon="monitor",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="section", type=t_string(), required=False, default="Main"),
        PortSpec(name="title", type=t_string(), required=False, default="Output"),
        PortSpec(name="value", type=t_any(), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="section", type=t_string()),
        PortSpec(name="title", type=t_string()),
        PortSpec(name="value", type=t_any()),
    ],
    cache_policy="disabled",  # potential side-effect (display), so maybe disable cache? or keep it enabled if pure? 
    # The user wants "streaming" to work efficiently. If we cache, we might miss updates?
    # Usually "Display" nodes are side-effect nodes, so disabling cache is safer.
)

@register_node(DISPLAY_NODE_SPEC)
class ToDisplayNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        section = inputs.get("section", "Main")
        title = inputs.get("title", "Output")
        value = inputs.get("value")

        # We primarily just pass through the values. 
        # The frontend will inspect the "last_outputs" of this node to render the display.
        return {
            "control_out": None,
            "section": section,
            "title": title,
            "value": value,
        }
