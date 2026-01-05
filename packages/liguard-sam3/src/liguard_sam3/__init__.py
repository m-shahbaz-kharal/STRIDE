"""
liguard-sam3: SAM3 integration plugin for LiGuard-Web.
"""

from .nodes import (
    SAM3ConnectNode,
    SAM3DisconnectNode,
    SAM3HeartbeatNode,
    SAM3SetImageNode,
    SAM3PromptTextNode,
    SAM3PromptBoxNode,
    SAM3PromptPointNode,
    SAM3GetResultsNode,
    SAM3VisualizeNode,
    SAM3ResetNode,
    SAM3VideoStartNode,
    SAM3VideoAddFrameNode,
    SAM3VideoPromptNode,
    SAM3VideoVisualizeFrameNode,
    SAM3CreatePointNode,
    SAM3CreateBoxNode,
    SAM3BoxToStringNode,
    SAM3SegmentImageNode,
)

__version__ = "1.0.0"

# Plugin metadata for discovery
PLUGIN_INFO = {
    "name": "SAM3",
    "version": __version__,
    "category": "AI",
    "description": "Segment Anything Model 3 integration",
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
    # Re-export node classes
    "SAM3ConnectNode",
    "SAM3DisconnectNode",
    "SAM3HeartbeatNode",
    "SAM3SetImageNode",
    "SAM3PromptTextNode",
    "SAM3PromptBoxNode",
    "SAM3PromptPointNode",
    "SAM3GetResultsNode",
    "SAM3VisualizeNode",
    "SAM3ResetNode",
    "SAM3VideoStartNode",
    "SAM3VideoAddFrameNode",
    "SAM3VideoPromptNode",
    "SAM3VideoVisualizeFrameNode",
    "SAM3CreatePointNode",
    "SAM3CreateBoxNode",
    "SAM3BoxToStringNode",
    "SAM3SegmentImageNode",
]
