from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


PRIMITIVES = {"int", "float", "string", "boolean", "null"}
CONTAINERS = {"list", "map", "record", "tuple", "option"}
FLEXIBLE = {"any", "unknown", "tensor", "control", "stream", "point", "box", "mask", "session"}


@dataclass(frozen=True)
class TypeDescriptor:
    """Portable type descriptor shared across frontend/backend.

    This is intentionally minimal but expressive enough for validation and UI hints.
    """

    kind: str
    name: Optional[str] = None
    item: Optional["TypeDescriptor"] = None  # for list/option/tuple positional type
    value: Optional["TypeDescriptor"] = None  # for map values
    fields: Optional[Dict[str, "TypeDescriptor"]] = None  # for records
    nullable: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_primitive(self) -> bool:
        return self.kind in PRIMITIVES

    def is_container(self) -> bool:
        return self.kind in CONTAINERS

    def is_flexible(self) -> bool:
        return self.kind in FLEXIBLE

    def with_nullable(self, nullable: bool = True) -> "TypeDescriptor":
        return TypeDescriptor(
            kind=self.kind,
            name=self.name,
            item=self.item,
            value=self.value,
            fields=self.fields,
            nullable=nullable,
            metadata=self.metadata,
        )

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "kind": self.kind,
            "nullable": self.nullable,
        }
        if self.name:
            data["name"] = self.name
        if self.item:
            data["item"] = self.item.to_dict()
        if self.value:
            data["value"] = self.value.to_dict()
        if self.fields:
            data["fields"] = {k: v.to_dict() for k, v in self.fields.items()}
        if self.metadata:
            data["metadata"] = self.metadata
        return data

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "TypeDescriptor":
        kind = payload.get("kind")
        if not kind:
            raise ValueError("TypeDescriptor requires 'kind'")
        return TypeDescriptor(
            kind=kind,
            name=payload.get("name"),
            item=TypeDescriptor.from_dict(payload["item"]) if payload.get("item") else None,
            value=TypeDescriptor.from_dict(payload["value"]) if payload.get("value") else None,
            fields={k: TypeDescriptor.from_dict(v) for k, v in (payload.get("fields") or {}).items()},
            nullable=bool(payload.get("nullable", False)),
            metadata=payload.get("metadata", {}) or {},
        )

    def label(self) -> str:
        """Human-readable label for UI/tooling."""
        if self.kind == "control":
            return "Control"
        if self.kind == "list" and self.item:
            return f"List<{self.item.label()}>"
        if self.kind == "map" and self.value:
            return f"Map<string,{self.value.label()}>"
        if self.kind == "record" and self.fields:
            return "Record"
        if self.kind == "option" and self.item:
            return f"Option<{self.item.label()}>"
        if self.kind == "tensor":
            shape = self.metadata.get("shape")
            dtype = self.metadata.get("dtype", "float32")
            shape_str = f"[{', '.join(map(str, shape))}]" if shape else ""
            return f"Tensor{shape_str}:{dtype}"
        return self.kind.capitalize()

    def is_assignable_to(self, target: "TypeDescriptor") -> bool:
        """Check if this type can flow into the target type."""
        if target.kind == "any":
            return True
        if self.kind == "any":
            return True
        if target.kind == "unknown":
            # Unknown is a sentinel for "explicitly unchecked" – allow writes, warn in UI separately.
            return True
        if self.kind == "unknown":
            # Unknown flowing into concrete types is allowed but should be highlighted; allow at runtime.
            return True
        if self.nullable and not target.nullable:
            return False
        if self.kind != target.kind:
            # Allow int -> float widening
            if self.kind == "int" and target.kind == "float":
                return True
            return False
        if self.kind == "list":
            return bool(self.item) and bool(target.item) and self.item.is_assignable_to(target.item)
        if self.kind == "map":
            return bool(self.value) and bool(target.value) and self.value.is_assignable_to(target.value)
        if self.kind == "option":
            return bool(self.item) and bool(target.item) and self.item.is_assignable_to(target.item)
        if self.kind == "record":
            if not self.fields or not target.fields:
                return False
            for key, val in target.fields.items():
                if key not in self.fields:
                    return False
                if not self.fields[key].is_assignable_to(val):
                    return False
            return True
        if self.kind == "tensor":
            # Minimal tensor compatibility: dtype must match if provided; shape must be compatible if provided.
            target_dtype = target.metadata.get("dtype")
            source_dtype = self.metadata.get("dtype")
            if target_dtype and source_dtype and target_dtype != source_dtype:
                return False
            target_shape = target.metadata.get("shape")
            source_shape = self.metadata.get("shape")
            if target_shape and source_shape and target_shape != source_shape:
                return False
            return True
        # primitives and control
        return True


def t_any() -> TypeDescriptor:
    return TypeDescriptor(kind="any")


def t_unknown() -> TypeDescriptor:
    return TypeDescriptor(kind="unknown")


def t_int() -> TypeDescriptor:
    return TypeDescriptor(kind="int")


def t_float() -> TypeDescriptor:
    return TypeDescriptor(kind="float")


def t_string() -> TypeDescriptor:
    return TypeDescriptor(kind="string")


def t_boolean() -> TypeDescriptor:
    return TypeDescriptor(kind="boolean")


def t_null() -> TypeDescriptor:
    return TypeDescriptor(kind="null")


def t_control() -> TypeDescriptor:
    return TypeDescriptor(kind="control")


def t_list(inner: TypeDescriptor) -> TypeDescriptor:
    return TypeDescriptor(kind="list", item=inner)


def t_map(inner: TypeDescriptor) -> TypeDescriptor:
    return TypeDescriptor(kind="map", value=inner)


def t_option(inner: TypeDescriptor) -> TypeDescriptor:
    return TypeDescriptor(kind="option", item=inner, nullable=True)


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
