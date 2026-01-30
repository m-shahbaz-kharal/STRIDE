"""Array/list operation nodes."""
from __future__ import annotations

from typing import Any, Dict

from . import register_node
from .base import ExecutionContext, NodeBase
from ..node_spec import NodeSpec, PortSpec
from ..typesystem import t_any, t_boolean, t_control, t_float, t_int, t_list


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
