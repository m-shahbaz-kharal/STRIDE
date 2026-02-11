"""
LiGuard-Web Backend Type System.

This module re-exports the type system from liguard-core for backwards compatibility.
All type definitions and utilities are now consolidated in liguard-core.
"""

from liguard_core.typesystem import (
    # Type descriptor class
    TypeDescriptor,
    # Type compatibility check
    types_compatible,
    # Constants
    PRIMITIVES,
    CONTAINERS,
    FLEXIBLE,
    # Factory functions
    t_any,
    t_unknown,
    t_null,
    t_int,
    t_float,
    t_string,
    t_boolean,
    t_list,
    t_map,
    t_tuple,
    t_option,
    t_control,
    t_record,
    t_tensor,
    t_stream,
    # AI-specific types
    t_point,
    t_box,
    t_mask,
    t_session,
    t_pointcloud,
)

__all__ = [
    "TypeDescriptor",
    "types_compatible",
    "PRIMITIVES",
    "CONTAINERS",
    "FLEXIBLE",
    "t_any",
    "t_unknown",
    "t_null",
    "t_int",
    "t_float",
    "t_string",
    "t_boolean",
    "t_list",
    "t_map",
    "t_tuple",
    "t_option",
    "t_control",
    "t_record",
    "t_tensor",
    "t_stream",
    "t_point",
    "t_box",
    "t_mask",
    "t_session",
    "t_pointcloud",
]
