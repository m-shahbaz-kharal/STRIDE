from __future__ import annotations

from typing import Any, Callable, Dict, List, Type

from .base import ExecutionContext, NodeBase

NODE_REGISTRY: Dict[str, Type[NodeBase]] = {}


def register_node(node_cls: Type[NodeBase]) -> Type[NodeBase]:
    NODE_REGISTRY[node_cls.node_type] = node_cls
    return node_cls


def get_node(node_type: str) -> Type[NodeBase]:
    if node_type not in NODE_REGISTRY:
        raise KeyError(f"Unknown node type '{node_type}'")
    return NODE_REGISTRY[node_type]


from . import addition  # noqa: F401
from . import constant  # noqa: F401
from . import math_ops  # noqa: F401


def list_node_types() -> List[Dict[str, Any]]:
    metadata: List[Dict[str, Any]] = []
    for node_cls in NODE_REGISTRY.values():
        schema = getattr(node_cls, "params_schema", {}) or {}
        metadata.append(
            {
                "node_type": node_cls.node_type,
                "display_name": getattr(node_cls, "display_name", node_cls.node_type),
                "description": getattr(node_cls, "description", ""),
                "icon": getattr(node_cls, "icon", ""),
                "input_ports": list(getattr(node_cls, "input_ports", [])),
                "output_ports": list(getattr(node_cls, "output_ports", [])),
                "params_schema": schema,
                "params_defaults": {
                    name: field.get("default") for name, field in schema.items() if "default" in field
                },
            }
        )
    return metadata


__all__ = [
    "NodeBase",
    "ExecutionContext",
    "register_node",
    "get_node",
    "NODE_REGISTRY",
    "list_node_types",
]

