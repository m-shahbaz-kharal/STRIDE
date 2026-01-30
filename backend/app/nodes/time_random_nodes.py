"""Time and random operation nodes."""
from __future__ import annotations

import random
import time
from typing import Any, Dict

from . import register_node
from .base import ExecutionContext, NodeBase
from ..node_spec import NodeSpec, PortSpec
from ..typesystem import t_any, t_boolean, t_control, t_float, t_int, t_list


# ============================================================================
# TIME OPERATIONS
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


# ============================================================================
# RANDOM OPERATIONS
# ============================================================================

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
