"""
Domain models for LiGuard-Web graph execution.

This module provides the core domain types that separate:
- GraphDefinition: Immutable graph structure (nodes, links, specs)
- ExecutionState: Mutable per-run state (computed_values, node_status, etc.)
- TypeDescriptor: Port type definitions and compatibility rules
"""

from __future__ import annotations

from .graph import GraphDefinition, NodeSpec, LinkSpec
from .execution import ExecutionState
from .types import TypeDescriptor, normalize_type, are_types_compatible

__all__ = [
    "GraphDefinition",
    "NodeSpec",
    "LinkSpec",
    "ExecutionState",
    "TypeDescriptor",
    "normalize_type",
    "are_types_compatible",
]
