"""
stride-fl511: FL511 Camera integration plugin for STRIDE.
"""

from .nodes import (
    Fl511ResolveNode,
    Fl511StartNode,
    Fl511TickNode,
    Fl511StopNode,
    StreamResource,
)

__version__ = "1.0.0"

# Plugin metadata for discovery
PLUGIN_INFO = {
    "name": "FL511",
    "version": __version__,
    "category": "FL511 Camera",
    "description": "FL511 traffic camera streaming integration",
    "api_version": "1.0",
    "author": "STRIDE Team",
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
    "Fl511ResolveNode",
    "Fl511StartNode",
    "Fl511TickNode",
    "Fl511StopNode",
    "StreamResource",
]
