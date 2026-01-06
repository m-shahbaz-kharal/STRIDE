"""
liguard-sam3: SAM3 integration plugin for LiGuard-Web.
"""

from .nodes import (
    SAM3ConnectNode,
    SAM3IsAliveNode,
    SAM3SetPromptNode,
    SAM3AddImageNode,
    SAM3GetOutputNode,
    SAM3VisualizeNode,
    SAM3DisconnectNode,
)

__version__ = "2.0.0"

# Plugin metadata for discovery
PLUGIN_INFO = {
    "name": "SAM3",
    "version": __version__,
    "category": "AI",
    "description": "Segment Anything Model 3 integration - Unified nodes",
    "api_version": "2.0",
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
    # Re-export node classes
    "SAM3ConnectNode",
    "SAM3IsAliveNode",
    "SAM3SetPromptNode",
    "SAM3AddImageNode",
    "SAM3GetOutputNode",
    "SAM3VisualizeNode",
    "SAM3DisconnectNode",
]
