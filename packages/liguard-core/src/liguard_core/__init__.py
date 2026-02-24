"""
liguard-core: Core interfaces for LiGuard-Web node plugins.

This package provides the base classes and utilities needed to create
LiGuard-Web node plugins.
"""

from .node_base import NodeBase, ExecutionContext
from .node_spec import NodeSpec, PortSpec
from .registry import register_node, NODE_REGISTRY, get_node, list_node_types, list_node_definitions
from .typesystem import TypeDescriptor, t_control, t_float, t_int
from .plugin import discover_plugins, PluginInfo

__version__ = "1.0.0"
__api_version__ = "1.0"

__all__ = [
    # Base classes
    "NodeBase",
    "ExecutionContext",
    # Specs
    "NodeSpec",
    "PortSpec",
    # Registry
    "register_node",
    "NODE_REGISTRY",
    "get_node",
    "list_node_types",
    "list_node_definitions",
    # Types
    "TypeDescriptor",
    "t_control",
    "t_float",
    "t_int",
    # Plugins
    "discover_plugins",
    "PluginInfo",
    # Version
    "__version__",
    "__api_version__",
]
