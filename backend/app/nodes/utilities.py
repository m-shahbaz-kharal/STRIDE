"""
Utility nodes module - re-exports from category-specific modules.

This module maintains backward compatibility by re-exporting all node classes
and specs from the following modules:
- string_nodes: String manipulation operations
- math_nodes: Mathematical operations
- time_random_nodes: Time and random number operations
- json_nodes: JSON parsing and serialization
- debug_nodes: Debug and utility operations
- array_nodes: Array/list operations
- image_nodes: Image loading and saving
"""
from __future__ import annotations

# Re-export all string nodes
from .string_nodes import (
    STRING_UPPER_SPEC,
    StringUpperNode,
    STRING_LOWER_SPEC,
    StringLowerNode,
    STRING_TRIM_SPEC,
    StringTrimNode,
    STRING_SPLIT_SPEC,
    StringSplitNode,
    STRING_JOIN_SPEC,
    StringJoinNode,
    STRING_REPLACE_SPEC,
    StringReplaceNode,
    STRING_CONTAINS_SPEC,
    StringContainsNode,
    STRING_STARTS_WITH_SPEC,
    StringStartsWithNode,
    STRING_ENDS_WITH_SPEC,
    StringEndsWithNode,
    STRING_SUBSTRING_SPEC,
    StringSubstringNode,
    STRING_FORMAT_SPEC,
    StringFormatNode,
)

# Re-export all math nodes
from .math_nodes import (
    MATH_MIN_SPEC,
    MathMinNode,
    MATH_MAX_SPEC,
    MathMaxNode,
    MATH_CLAMP_SPEC,
    MathClampNode,
    MATH_LERP_SPEC,
    MathLerpNode,
    MATH_ROUND_SPEC,
    MathRoundNode,
    MATH_FLOOR_SPEC,
    MathFloorNode,
    MATH_CEIL_SPEC,
    MathCeilNode,
    MATH_MOD_SPEC,
    MathModNode,
    MATH_SQRT_SPEC,
    MathSqrtNode,
    MATH_SIN_SPEC,
    MathSinNode,
    MATH_COS_SPEC,
    MathCosNode,
    MATH_DEGREES_SPEC,
    MathDegreesNode,
    MATH_RADIANS_SPEC,
    MathRadiansNode,
)

# Re-export all time and random nodes
from .time_random_nodes import (
    TIME_NOW_SPEC,
    TimeNowNode,
    TIME_DELAY_SPEC,
    TimeDelayNode,
    RANDOM_FLOAT_SPEC,
    RandomFloatNode,
    RANDOM_INT_SPEC,
    RandomIntNode,
    RANDOM_BOOLEAN_SPEC,
    RandomBooleanNode,
    RANDOM_CHOICE_SPEC,
    RandomChoiceNode,
)

# Re-export all JSON nodes
from .json_nodes import (
    JSON_PARSE_SPEC,
    JsonParseNode,
    JSON_STRINGIFY_SPEC,
    JsonStringifyNode,
)

# Re-export all debug nodes
from .debug_nodes import (
    DEBUG_LOG_SPEC,
    DebugLogNode,
    DEBUG_BREAKPOINT_SPEC,
    DebugBreakpointNode,
    TYPE_OF_SPEC,
    TypeOfNode,
    IS_NULL_SPEC,
    IsNullNode,
    COALESCE_SPEC,
    CoalesceNode,
    PASSTHROUGH_SPEC,
    PassthroughNode,
)

# Re-export all array nodes
from .array_nodes import (
    ARRAY_FIRST_SPEC,
    ArrayFirstNode,
    ARRAY_LAST_SPEC,
    ArrayLastNode,
    ARRAY_SLICE_SPEC,
    ArraySliceNode,
    ARRAY_REVERSE_SPEC,
    ArrayReverseNode,
    ARRAY_SORT_SPEC,
    ArraySortNode,
    ARRAY_CONTAINS_SPEC,
    ArrayContainsNode,
    ARRAY_INDEX_OF_SPEC,
    ArrayIndexOfNode,
    ARRAY_SUM_SPEC,
    ArraySumNode,
    ARRAY_AVERAGE_SPEC,
    ArrayAverageNode,
)

# Re-export all image nodes
from .image_nodes import (
    LOAD_IMAGE_SPEC,
    LoadImageNode,
    SAVE_IMAGE_SPEC,
    SaveImageNode,
)

__all__ = [
    # String nodes
    "STRING_UPPER_SPEC", "StringUpperNode",
    "STRING_LOWER_SPEC", "StringLowerNode",
    "STRING_TRIM_SPEC", "StringTrimNode",
    "STRING_SPLIT_SPEC", "StringSplitNode",
    "STRING_JOIN_SPEC", "StringJoinNode",
    "STRING_REPLACE_SPEC", "StringReplaceNode",
    "STRING_CONTAINS_SPEC", "StringContainsNode",
    "STRING_STARTS_WITH_SPEC", "StringStartsWithNode",
    "STRING_ENDS_WITH_SPEC", "StringEndsWithNode",
    "STRING_SUBSTRING_SPEC", "StringSubstringNode",
    "STRING_FORMAT_SPEC", "StringFormatNode",
    # Math nodes
    "MATH_MIN_SPEC", "MathMinNode",
    "MATH_MAX_SPEC", "MathMaxNode",
    "MATH_CLAMP_SPEC", "MathClampNode",
    "MATH_LERP_SPEC", "MathLerpNode",
    "MATH_ROUND_SPEC", "MathRoundNode",
    "MATH_FLOOR_SPEC", "MathFloorNode",
    "MATH_CEIL_SPEC", "MathCeilNode",
    "MATH_MOD_SPEC", "MathModNode",
    "MATH_SQRT_SPEC", "MathSqrtNode",
    "MATH_SIN_SPEC", "MathSinNode",
    "MATH_COS_SPEC", "MathCosNode",
    "MATH_DEGREES_SPEC", "MathDegreesNode",
    "MATH_RADIANS_SPEC", "MathRadiansNode",
    # Time and random nodes
    "TIME_NOW_SPEC", "TimeNowNode",
    "TIME_DELAY_SPEC", "TimeDelayNode",
    "RANDOM_FLOAT_SPEC", "RandomFloatNode",
    "RANDOM_INT_SPEC", "RandomIntNode",
    "RANDOM_BOOLEAN_SPEC", "RandomBooleanNode",
    "RANDOM_CHOICE_SPEC", "RandomChoiceNode",
    # JSON nodes
    "JSON_PARSE_SPEC", "JsonParseNode",
    "JSON_STRINGIFY_SPEC", "JsonStringifyNode",
    # Debug nodes
    "DEBUG_LOG_SPEC", "DebugLogNode",
    "DEBUG_BREAKPOINT_SPEC", "DebugBreakpointNode",
    "TYPE_OF_SPEC", "TypeOfNode",
    "IS_NULL_SPEC", "IsNullNode",
    "COALESCE_SPEC", "CoalesceNode",
    "PASSTHROUGH_SPEC", "PassthroughNode",
    # Array nodes
    "ARRAY_FIRST_SPEC", "ArrayFirstNode",
    "ARRAY_LAST_SPEC", "ArrayLastNode",
    "ARRAY_SLICE_SPEC", "ArraySliceNode",
    "ARRAY_REVERSE_SPEC", "ArrayReverseNode",
    "ARRAY_SORT_SPEC", "ArraySortNode",
    "ARRAY_CONTAINS_SPEC", "ArrayContainsNode",
    "ARRAY_INDEX_OF_SPEC", "ArrayIndexOfNode",
    "ARRAY_SUM_SPEC", "ArraySumNode",
    "ARRAY_AVERAGE_SPEC", "ArrayAverageNode",
    # Image nodes
    "LOAD_IMAGE_SPEC", "LoadImageNode",
    "SAVE_IMAGE_SPEC", "SaveImageNode",
]
