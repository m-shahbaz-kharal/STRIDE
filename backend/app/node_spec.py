"""
LiGuard-Web Backend Node Specification.

This module re-exports the node specification classes from liguard-core for backwards compatibility.
All spec definitions are now consolidated in liguard-core.
"""

from liguard_core.node_spec import (
    NodeSpec,
    PortSpec,
)

__all__ = [
    "NodeSpec",
    "PortSpec",
]
