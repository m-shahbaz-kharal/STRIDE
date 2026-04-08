"""
STRIDE Backend Node Specification.

This module re-exports the node specification classes from stride-core for backwards compatibility.
All spec definitions are now consolidated in stride-core.
"""

from stride_core.node_spec import (
    NodeSpec,
    PortSpec,
)

__all__ = [
    "NodeSpec",
    "PortSpec",
]
