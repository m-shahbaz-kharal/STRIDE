"""
Node registry and discovery for LiGuard-Web.

This module bridges the liguard_core plugin system with the backend,
providing backwards-compatible exports and loading installed plugins.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Type

# Re-export base classes from liguard_core
from liguard_core import (
    NodeBase, 
    ExecutionContext,
    register_node,
    NODE_REGISTRY as _CORE_REGISTRY,
    list_node_definitions as _core_list_definitions,
)
from liguard_core.plugin import load_all_plugins, discover_plugins
from liguard_core.node_spec import NodeSpec

logger = logging.getLogger(__name__)


class NodeRegistration:
    """Backwards-compatible wrapper for node registry entries."""
    
    def __init__(self, spec: NodeSpec, cls: Type[NodeBase]) -> None:
        self.spec = spec
        self.cls = cls


# Create a backwards-compatible view into the core registry
class _NodeRegistryProxy:
    """Proxy that provides dict-like access to the liguard_core registry."""
    
    def __getitem__(self, key: str) -> NodeRegistration:
        entry = _CORE_REGISTRY.get(key)
        if not entry:
            raise KeyError(f"Unknown node type '{key}'")
        return NodeRegistration(entry["spec"], entry["class"])
    
    def __contains__(self, key: str) -> bool:
        return key in _CORE_REGISTRY
    
    def get(self, key: str, default=None):
        try:
            return self[key]
        except KeyError:
            return default
    
    def values(self):
        for entry in _CORE_REGISTRY.values():
            yield NodeRegistration(entry["spec"], entry["class"])
    
    def keys(self):
        return _CORE_REGISTRY.keys()
    
    def items(self):
        for key, entry in _CORE_REGISTRY.items():
            yield key, NodeRegistration(entry["spec"], entry["class"])
    
    def __len__(self):
        return len(_CORE_REGISTRY)


NODE_REGISTRY = _NodeRegistryProxy()


def get_node(node_type: str) -> NodeRegistration:
    """Get a node registration by type name."""
    if node_type not in _CORE_REGISTRY:
        raise KeyError(f"Unknown node type '{node_type}'")
    entry = _CORE_REGISTRY[node_type]
    return NodeRegistration(entry["spec"], entry["class"])


def list_node_types() -> List[Dict[str, Any]]:
    """Legacy endpoint payload for the existing frontend."""
    return _core_list_definitions()


def list_node_definitions() -> List[Dict[str, Any]]:
    """List all registered node definitions."""
    return _core_list_definitions()


# =============================================================================
# Register built-in nodes (intentional ordering)
# These are core nodes that are always available, not plugins
# =============================================================================
from . import addition  # noqa: E402,F401
from . import constant  # noqa: E402,F401
from . import control  # noqa: E402,F401
from . import casting  # noqa: E402,F401
from . import containers  # noqa: E402,F401
from . import math_ops  # noqa: E402,F401
from . import programming  # noqa: E402,F401
from . import utilities  # noqa: E402,F401
from . import display  # noqa: E402,F401
from . import sv_core        # noqa: E402,F401
from . import sv_annotators  # noqa: E402,F401
from . import sv_tools       # noqa: E402,F401
from . import ul_yolo        # noqa: E402,F401

# Note: fl511 and sam3 are now loaded as plugins, not built-in nodes
# from . import fl511  # Moved to liguard-fl511 plugin
# from . import sam3   # Moved to liguard-sam3 plugin

# =============================================================================
# Load plugins from entry points
# =============================================================================
_plugins = load_all_plugins()
logger.info(f"Loaded {len([p for p in _plugins if p.loaded])} plugins")


__all__ = [
    "NodeBase",
    "ExecutionContext",
    "register_node",
    "get_node",
    "NODE_REGISTRY",
    "list_node_types",
    "list_node_definitions",
]
