"""
Engine package initialization.

This package contains the core execution engine modules:
- graph_builder: Graph construction and topological sorting
- control_flow: Loop/branch detection and analysis
"""

from .graph_builder import (
    normalize_type,
    build_nodes,
    build_links,
    validate_output_nodes,
    topological_sort,
    compute_levels,
)

from .control_flow import (
    is_loop_node,
    is_ifelse_node,
    is_start_node,
    collect_loop_body_nodes,
    build_loop_sets,
    collect_branch_nodes,
    build_ifelse_sets,
    build_branch_info,
)

__all__ = [
    # Graph building
    "normalize_type",
    "build_nodes",
    "build_links",
    "validate_output_nodes",
    "topological_sort",
    "compute_levels",
    # Control flow
    "is_loop_node",
    "is_ifelse_node",
    "is_start_node",
    "collect_loop_body_nodes",
    "build_loop_sets",
    "collect_branch_nodes",
    "build_ifelse_sets",
    "build_branch_info",
]
