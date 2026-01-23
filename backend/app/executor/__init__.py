"""
Executor package for LiGuard-Web graph execution.

This package provides the core execution engine for running node graphs.
"""

from __future__ import annotations

# Export cancellation controller for direct use
from .cancellation import CancellationController


def __getattr__(name: str):
    """Lazy import to avoid circular dependencies."""
    if name == "GraphExecutor":
        from ..runner import GraphExecutor
        return GraphExecutor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "GraphExecutor",
    "CancellationController",
]
