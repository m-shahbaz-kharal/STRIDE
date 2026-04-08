"""
STRIDE Backend Node Base Classes.

This module re-exports the base classes from stride-core for backwards compatibility.
All base class definitions are now consolidated in stride-core.
"""

from stride_core import (
    NodeBase,
    ExecutionContext,
)

# Re-export for backwards compatibility
__all__ = [
    "NodeBase",
    "ExecutionContext",
]
