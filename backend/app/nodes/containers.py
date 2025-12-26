from __future__ import annotations

from typing import Any, Dict, List

from . import register_node
from .base import ExecutionContext, NodeBase
from ..node_spec import NodeSpec, PortSpec
from ..typesystem import t_any, t_int, t_list


MAKE_ARRAY_SPEC = NodeSpec(
    type="core.container.make_array",
    version="1.0.0",
    display_name="Make Array",
    category="Containers",
    summary="Create an array from inputs.",
    description="Collects item inputs into an array.",
    icon="list",
    inputs=[],
    outputs=[PortSpec(name="array", type=t_list(t_any()))],
    params={},
)


@register_node(MAKE_ARRAY_SPEC)
class MakeArrayNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        items: List[Any] = []
        for port in sorted(inputs.keys(), key=lambda name: int(name.split("_")[1]) if "_" in name and name.split("_")[1].isdigit() else 0):
            items.append(inputs.get(port))
        ctx.log(f"{self.id} make array ({len(items)} items)")
        return {"array": items}


APPEND_ARRAY_SPEC = NodeSpec(
    type="core.container.append",
    version="1.0.0",
    display_name="Append",
    category="Containers",
    summary="Append a value to an array.",
    description="Returns a new array with the value appended.",
    icon="list",
    inputs=[
        PortSpec(name="array", type=t_list(t_any()), required=False, default=None),
        PortSpec(name="value", type=t_any(), required=False, default=None),
    ],
    outputs=[PortSpec(name="array", type=t_list(t_any()))],
    params={},
)


@register_node(APPEND_ARRAY_SPEC)
class AppendArrayNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        array = inputs.get("array") or []
        if not isinstance(array, list):
            array = list(array) if array is not None else []
        value = inputs.get("value")
        result = list(array) + [value]
        ctx.log(f"{self.id} append -> {len(result)} items")
        return {"array": result}


GET_INDEX_SPEC = NodeSpec(
    type="core.container.get_index",
    version="1.0.0",
    display_name="Get Index",
    category="Containers",
    summary="Get array item by index.",
    description="Returns the value at index if present.",
    icon="list",
    inputs=[
        PortSpec(name="array", type=t_list(t_any()), required=False, default=None),
        PortSpec(name="index", type=t_int(), required=False, default=0),
    ],
    outputs=[PortSpec(name="value", type=t_any())],
    params={},
)


@register_node(GET_INDEX_SPEC)
class GetIndexNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        array = inputs.get("array") or []
        index = int(inputs.get("index") or 0)
        if not isinstance(array, list):
            array = list(array) if array is not None else []
        value = array[index] if 0 <= index < len(array) else None
        ctx.log(f"{self.id} get index {index} -> {value}")
        return {"value": value}


RANGE_SPEC = NodeSpec(
    type="core.container.range",
    version="1.0.0",
    display_name="Range",
    category="Containers",
    summary="Create a range of integers.",
    description="Creates a list of integers from start to end (inclusive).",
    icon="list",
    inputs=[
        PortSpec(name="start", type=t_int(), required=False, default=0),
        PortSpec(name="end", type=t_int(), required=False, default=0),
        PortSpec(name="step", type=t_int(), required=False, default=1),
    ],
    outputs=[PortSpec(name="array", type=t_list(t_int()))],
    params={},
)


@register_node(RANGE_SPEC)
class RangeNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        start = int(inputs.get("start") or 0)
        end = int(inputs.get("end") or 0)
        step = int(inputs.get("step") or 1)
        if step == 0:
            step = 1
        if start <= end and step < 0:
            step = abs(step)
        if start >= end and step > 0:
            step = -step
        values = list(range(start, end + (1 if step > 0 else -1), step))
        ctx.log(f"{self.id} range {start}->{end} step {step} ({len(values)})")
        return {"array": values}
