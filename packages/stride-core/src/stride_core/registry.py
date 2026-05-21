"""
Node registry for STRIDE.

Provides the register_node decorator and registry utilities.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .node_base import NodeBase
    from .node_spec import NodeSpec


# Global registry of node types. Mutations are serialised by
# ``_REGISTRY_LOCK`` so concurrent plugin imports can't tear the dict
# under iteration on alternative runtimes without the GIL.
NODE_REGISTRY: Dict[str, Dict[str, Any]] = {}
_REGISTRY_LOCK = threading.Lock()


def register_node(spec: "NodeSpec") -> Callable[[Type["NodeBase"]], Type["NodeBase"]]:
    """Decorator to register a node class with its specification.

    Usage:
        @register_node(MY_NODE_SPEC)
        class MyNode(NodeBase):
            def forward(self, inputs, ctx):
                ...
    """
    def decorator(cls: Type["NodeBase"]) -> Type["NodeBase"]:
        cls.spec = spec
        with _REGISTRY_LOCK:
            NODE_REGISTRY[spec.type] = {
                "spec": spec,
                "class": cls,
            }
        return cls
    return decorator


def get_node(node_type: str) -> Dict[str, Any]:
    """Get a registered node by its type name.

    Returns:
        Dictionary with 'spec' and 'class' keys.

    Raises:
        KeyError: If node type is not registered.
    """
    with _REGISTRY_LOCK:
        entry = NODE_REGISTRY.get(node_type)
    if entry is None:
        raise KeyError(f"Unknown node type: {node_type}")
    return entry


def list_node_types() -> List[Dict[str, Any]]:
    """List all registered node types with summary info."""
    with _REGISTRY_LOCK:
        snapshot = list(NODE_REGISTRY.items())
    result = []
    for node_type, info in snapshot:
        spec = info["spec"]
        result.append({
            "node_type": node_type,
            "display_name": spec.display_name or node_type,
            "category": spec.category,
            "summary": spec.summary,
            "input_ports": [p.name for p in spec.inputs],
            "output_ports": [p.name for p in spec.outputs],
            "plugin_name": spec.plugin_name,
        })
    return result


def list_node_definitions() -> List[Dict[str, Any]]:
    """List all registered nodes with full specifications."""
    with _REGISTRY_LOCK:
        infos = list(NODE_REGISTRY.values())
    return [info["spec"].to_dict() for info in infos]


def clear_registry() -> None:
    """Clear the node registry. Useful for testing."""
    with _REGISTRY_LOCK:
        NODE_REGISTRY.clear()
