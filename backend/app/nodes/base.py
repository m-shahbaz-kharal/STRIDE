"""
LiGuard-Web Backend Node Base Classes.

This module re-exports the base classes from liguard-core for backwards compatibility.
All base class definitions are now consolidated in liguard-core.
"""

from liguard_core import (
    NodeBase,
    ExecutionContext,
)

# Re-export for backwards compatibility
__all__ = [
    "NodeBase",
    "ExecutionContext",
]
