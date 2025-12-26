from __future__ import annotations

from typing import Any, Dict

from . import register_node
from .base import ExecutionContext, NodeBase
from ..node_spec import NodeSpec, PortSpec
from ..typesystem import t_control


CONTROL_START_SPEC = NodeSpec(
    type="core.control.start",
    version="1.0.0",
    display_name="Start",
    category="Control",
    summary="Entry point for control flow.",
    description="Emits a control signal to begin execution chains.",
    icon="play",
    inputs=[],
    outputs=[PortSpec(name="control_out", type=t_control(), required=False, default=None)],
    params={},
)


@register_node(CONTROL_START_SPEC)
class ControlStartNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        ctx.log(f"{self.id} start")
        return {"control_out": None}
