from __future__ import annotations

from typing import Callable, Dict, Type

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

__all__ = [
    "NodeBase",
    "ExecutionContext",
    "register_node",
    "get_node",
    "NODE_REGISTRY",
]

