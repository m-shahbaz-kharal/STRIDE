"""
stride-core: Core interfaces for STRIDE node plugins.

This package provides the base classes and utilities needed to create
STRIDE node plugins.
"""

from .node_base import NodeBase, ExecutionContext
from .node_spec import NodeSpec, PortSpec
from .registry import register_node, NODE_REGISTRY, get_node, list_node_types, list_node_definitions
from .typesystem import (
    TypeDescriptor,
    t_control, t_float, t_int, t_string, t_boolean, t_any, t_list, t_record,
    t_image, t_bbox2d, t_detections2d, t_detections3d, t_depthmap,
    t_track2d, t_track3d, t_keypoints, t_pointcloud, t_bbox3d,
)
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
    "t_string",
    "t_boolean",
    "t_any",
    "t_list",
    "t_record",
    "t_image",
    "t_bbox2d",
    "t_detections2d",
    "t_detections3d",
    "t_depthmap",
    "t_track2d",
    "t_track3d",
    "t_keypoints",
    "t_pointcloud",
    "t_bbox3d",
    # Plugins
    "discover_plugins",
    "PluginInfo",
    # Version
    "__version__",
    "__api_version__",
]
