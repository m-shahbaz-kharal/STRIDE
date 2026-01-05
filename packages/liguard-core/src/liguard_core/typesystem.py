"""
Type system for LiGuard-Web nodes.

Provides TypeDescriptor and factory functions for creating type specifications.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


PRIMITIVES = {"int", "float", "string", "boolean", "null"}
CONTAINERS = {"list", "map", "record", "tuple", "option"}
FLEXIBLE = {"any", "unknown", "tensor", "control", "stream", "point", "box", "mask", "session"}


@dataclass(frozen=True)
class TypeDescriptor:
    """Immutable descriptor for a data type in the node system."""

    kind: str = "any"
    element_type: Optional["TypeDescriptor"] = None
    key_type: Optional["TypeDescriptor"] = None
    fields: Optional[Dict[str, "TypeDescriptor"]] = None
    nullable: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_primitive(self) -> bool:
        return self.kind in PRIMITIVES

    def is_container(self) -> bool:
        return self.kind in CONTAINERS

    def is_flexible(self) -> bool:
        return self.kind in FLEXIBLE

    def with_nullable(self, nullable: bool = True) -> "TypeDescriptor":
        """Return a copy of this TypeDescriptor with nullable set to the given value."""
        return TypeDescriptor(
            kind=self.kind,
            element_type=self.element_type,
            key_type=self.key_type,
            fields=self.fields,
            nullable=nullable,
            metadata=self.metadata,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a JSON-serializable dictionary."""
        data: Dict[str, Any] = {"kind": self.kind}
        if self.element_type is not None:
            data["elementType"] = self.element_type.to_dict()
        if self.key_type is not None:
            data["keyType"] = self.key_type.to_dict()
        if self.fields is not None:
            data["fields"] = {k: v.to_dict() for k, v in self.fields.items()}
        if self.nullable:
            data["nullable"] = True
        if self.metadata:
            data["metadata"] = self.metadata
        return data

    def __repr__(self) -> str:
        parts = [f"kind={self.kind!r}"]
        if self.element_type:
            parts.append(f"element={self.element_type.kind!r}")
        if self.key_type:
            parts.append(f"key={self.key_type.kind!r}")
        if self.fields:
            parts.append(f"fields={list(self.fields.keys())}")
        if self.nullable:
            parts.append("nullable=True")
        return f"TypeDescriptor({', '.join(parts)})"


def types_compatible(source: TypeDescriptor, target: TypeDescriptor) -> bool:
    """
    Check if a source type can be connected to a target type.
    Returns True if the connection is valid.
    """
    if target.kind == "any" or source.kind == "any":
        return True
    if target.kind == "unknown" or source.kind == "unknown":
        return True

    # Nullable compatibility: nullable source can connect to nullable target
    # Non-nullable source can always connect to nullable target
    if source.nullable and not target.nullable:
        # A nullable source should be able to connect to non-nullable if types match
        # This is a design choice - we'll allow it with runtime checks
        pass

    if source.kind != target.kind:
        return False

    if source.kind == "list":
        if source.element_type and target.element_type:
            return types_compatible(source.element_type, target.element_type)
        return True

    if source.kind == "map":
        key_ok = True
        val_ok = True
        if source.key_type and target.key_type:
            key_ok = types_compatible(source.key_type, target.key_type)
        if source.element_type and target.element_type:
            val_ok = types_compatible(source.element_type, target.element_type)
        return key_ok and val_ok

    if source.kind == "record":
        if source.fields and target.fields:
            for fname, ftype in target.fields.items():
                if fname not in source.fields:
                    return False
                if not types_compatible(source.fields[fname], ftype):
                    return False
        return True

    return True


# =============================================================================
# Type Factory Functions
# =============================================================================

def t_any() -> TypeDescriptor:
    return TypeDescriptor(kind="any")


def t_unknown() -> TypeDescriptor:
    return TypeDescriptor(kind="unknown")


def t_null() -> TypeDescriptor:
    return TypeDescriptor(kind="null")


def t_int() -> TypeDescriptor:
    return TypeDescriptor(kind="int")


def t_float() -> TypeDescriptor:
    return TypeDescriptor(kind="float")


def t_string() -> TypeDescriptor:
    return TypeDescriptor(kind="string")


def t_boolean() -> TypeDescriptor:
    return TypeDescriptor(kind="boolean")


def t_list(element_type: TypeDescriptor = None) -> TypeDescriptor:
    return TypeDescriptor(kind="list", element_type=element_type or t_any())


def t_map(key_type: TypeDescriptor = None, value_type: TypeDescriptor = None) -> TypeDescriptor:
    return TypeDescriptor(
        kind="map",
        key_type=key_type or t_string(),
        element_type=value_type or t_any(),
    )


def t_tuple(*element_types: TypeDescriptor) -> TypeDescriptor:
    if not element_types:
        return TypeDescriptor(kind="tuple")
    return TypeDescriptor(
        kind="tuple",
        fields={str(i): et for i, et in enumerate(element_types)},
    )


def t_option(inner_type: TypeDescriptor) -> TypeDescriptor:
    return TypeDescriptor(kind="option", element_type=inner_type)


def t_control() -> TypeDescriptor:
    return TypeDescriptor(kind="control")


def t_record(fields: Dict[str, TypeDescriptor]) -> TypeDescriptor:
    return TypeDescriptor(kind="record", fields=fields)


def t_tensor(dtype: str = "float32", shape: Optional[list[int]] = None) -> TypeDescriptor:
    return TypeDescriptor(kind="tensor", metadata={"dtype": dtype, "shape": shape or []})


def t_stream() -> TypeDescriptor:
    return TypeDescriptor(kind="stream")


# =============================================================================
# AI-Specific Types
# =============================================================================

def t_point() -> TypeDescriptor:
    """A 2D point with x, y coordinates (normalized 0-1) and optional label."""
    return TypeDescriptor(kind="point")


def t_box() -> TypeDescriptor:
    """A bounding box with x1, y1, x2, y2 (normalized 0-1) and optional label."""
    return TypeDescriptor(kind="box")


def t_mask() -> TypeDescriptor:
    """A segmentation mask (base64 encoded PNG)."""
    return TypeDescriptor(kind="mask")


def t_session() -> TypeDescriptor:
    """An AI model session handle."""
    return TypeDescriptor(kind="session")
