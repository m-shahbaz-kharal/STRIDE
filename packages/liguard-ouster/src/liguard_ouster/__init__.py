"""
liguard-ouster: Ouster LiDAR integration plugin for LiGuard-Web.
"""

from .nodes import (
    OusterOpenSourceNode,
    OusterGetFrameNode,
)

__version__ = "1.0.0"

PLUGIN_INFO = {
    "name": "Ouster LiDAR",
    "version": __version__,
    "category": "Ouster LiDAR",
    "description": "Ouster LiDAR data loading and point cloud extraction",
    "api_version": "1.0",
    "author": "LiGuard-Web Team",
}


def register():
    """Called by LiGuard-Web to register this plugin's nodes.

    All nodes are already registered via the @register_node decorator
    when the nodes module is imported above.
    """
    pass


__all__ = [
    "register",
    "PLUGIN_INFO",
    "__version__",
    "OusterOpenSourceNode",
    "OusterGetFrameNode",
]
