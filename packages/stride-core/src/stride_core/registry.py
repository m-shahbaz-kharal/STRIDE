"""
Node registry for STRIDE.

Provides the register_node decorator and registry utilities.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .node_base import NodeBase
    from .node_spec import NodeSpec


# Global registry of node types
NODE_REGISTRY: Dict[str, Dict[str, Any]] = {}


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
    if node_type not in NODE_REGISTRY:
        raise KeyError(f"Unknown node type: {node_type}")
    return NODE_REGISTRY[node_type]


def list_node_types() -> List[Dict[str, Any]]:
    """List all registered node types with summary info.
    
    Returns:
        List of dictionaries with node type info.
    """
    result = []
    for node_type, info in NODE_REGISTRY.items():
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
    """List all registered nodes with full specifications.
    
    Returns:
        List of full node specification dictionaries.
    """
    return [info["spec"].to_dict() for info in NODE_REGISTRY.values()]


def clear_registry() -> None:
    """Clear the node registry. Useful for testing."""
    NODE_REGISTRY.clear()
