from __future__ import annotations

from typing import Any, Dict, List, Type

from .base import ExecutionContext, NodeBase
from ..node_spec import NodeSpec

class NodeRegistration:
    def __init__(self, spec: NodeSpec, cls: Type[NodeBase]) -> None:
        self.spec = spec
        self.cls = cls


NODE_REGISTRY: Dict[str, NodeRegistration] = {}


def register_node(spec: NodeSpec):
    def decorator(node_cls: Type[NodeBase]) -> Type[NodeBase]:
        node_cls.spec = spec
        NODE_REGISTRY[spec.type] = NodeRegistration(spec, node_cls)
        return node_cls
    return decorator


def get_node(node_type: str) -> NodeRegistration:
    if node_type not in NODE_REGISTRY:
        raise KeyError(f"Unknown node type '{node_type}'")
    return NODE_REGISTRY[node_type]


def list_node_types() -> List[Dict[str, Any]]:
    """Legacy endpoint payload for the existing frontend."""
    return [
        registration.spec.to_dict()
        for registration in NODE_REGISTRY.values()
    ]


def list_node_definitions() -> List[Dict[str, Any]]:
    return [
        registration.spec.to_dict()
        for registration in NODE_REGISTRY.values()
    ]


# Register built-in nodes (intentional ordering)
from . import addition  # noqa: E402,F401
from . import constant  # noqa: E402,F401
from . import control  # noqa: E402,F401
from . import casting  # noqa: E402,F401
from . import containers  # noqa: E402,F401
from . import math_ops  # noqa: E402,F401
from . import programming  # noqa: E402,F401
from . import fl511  # noqa: E402,F401
from . import utilities  # noqa: E402,F401
from . import display  # noqa: E402,F401
from . import sam3  # noqa: E402,F401


__all__ = [
    "NodeBase",
    "ExecutionContext",
    "register_node",
    "get_node",
    "NODE_REGISTRY",
    "list_node_types",
    "list_node_definitions",
]
