"""
Type system domain model.

Provides type descriptors and compatibility rules for port types.
This is the source of truth for type compatibility logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


@dataclass
class TypeDescriptor:
    """Describes the type of a port value.

    This is the canonical representation of port types used for
    validation and compatibility checking.

    Attributes:
        kind: The base type kind (e.g., 'int', 'float', 'string', 'list', etc.)
        item: For container types (list, option), the element type
        value: For map types, the value type (key is always string)
        key: For map types, optional key type descriptor
        fields: For record types, mapping of field names to types
        nullable: Whether None/null is a valid value
        metadata: Additional type-specific metadata (e.g., dtype for tensor)
    """
    kind: str
    item: Optional["TypeDescriptor"] = None
    value: Optional["TypeDescriptor"] = None
    key: Optional["TypeDescriptor"] = None
    fields: Optional[Dict[str, "TypeDescriptor"]] = None
    nullable: bool = False
    metadata: Optional[Dict[str, Any]] = None

    @classmethod
    def from_any(cls, raw_type: Any) -> "TypeDescriptor":
        """Create a TypeDescriptor from various input formats.

        Handles:
        - None -> any type
        - String -> simple type
        - Dict with 'kind' -> full descriptor

        Args:
            raw_type: The type specification in any supported format

        Returns:
            A normalized TypeDescriptor
        """
        return normalize_type(raw_type)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary representation."""
        result: Dict[str, Any] = {"kind": self.kind}
        if self.item is not None:
            result["item"] = self.item.to_dict()
        if self.value is not None:
            result["value"] = self.value.to_dict()
        if self.key is not None:
            result["key"] = self.key.to_dict()
        if self.fields is not None:
            result["fields"] = {
                name: td.to_dict() for name, td in self.fields.items()
            }
        if self.nullable:
            result["nullable"] = True
        if self.metadata is not None:
            result["metadata"] = self.metadata
        return result

    def is_any(self) -> bool:
        """Check if this is the 'any' type that accepts anything."""
        return self.kind in ("any", "unknown")

    def is_numeric(self) -> bool:
        """Check if this is a numeric type."""
        return self.kind in ("int", "float", "number")

    def is_container(self) -> bool:
        """Check if this is a container type."""
        return self.kind in ("list", "map", "option", "record")

    def is_control(self) -> bool:
        """Check if this is a control flow type."""
        return self.kind == "control"


def normalize_type(raw_type: Any) -> TypeDescriptor:
    """Normalize a type specification to a TypeDescriptor.

    This handles various input formats:
    - None -> TypeDescriptor(kind='any')
    - 'int' -> TypeDescriptor(kind='int')
    - 'number' -> TypeDescriptor(kind='float')  # Normalize number to float
    - {'kind': 'list', 'item': 'int'} -> TypeDescriptor(kind='list', item=TypeDescriptor(kind='int'))

    Args:
        raw_type: The type specification in any supported format

    Returns:
        A normalized TypeDescriptor
    """
    if raw_type is None:
        return TypeDescriptor(kind="any")

    if isinstance(raw_type, TypeDescriptor):
        return raw_type

    if isinstance(raw_type, str):
        # Normalize common type aliases
        if raw_type == "number":
            return TypeDescriptor(kind="float")
        return TypeDescriptor(kind=raw_type)

    if isinstance(raw_type, dict):
        kind = raw_type.get("kind", "any")

        # Normalize 'number' to 'float'
        if kind == "number":
            kind = "float"

        # Handle element_type -> item normalization
        element_type = raw_type.get("elementType") or raw_type.get("element_type")

        item = None
        if element_type is not None:
            item = normalize_type(element_type)
        elif "item" in raw_type:
            item = normalize_type(raw_type["item"])

        value = None
        if "value" in raw_type:
            value = normalize_type(raw_type["value"])
        elif kind == "map" and item is not None and value is None:
            # For maps, element_type often means value type
            value = item
            item = None

        key = None
        if "key" in raw_type:
            key = normalize_type(raw_type["key"])

        fields = None
        if "fields" in raw_type and isinstance(raw_type["fields"], dict):
            fields = {
                name: normalize_type(field_type)
                for name, field_type in raw_type["fields"].items()
            }

        nullable = bool(raw_type.get("nullable", False))

        metadata = raw_type.get("metadata")

        return TypeDescriptor(
            kind=kind,
            item=item,
            value=value,
            key=key,
            fields=fields,
            nullable=nullable,
            metadata=metadata,
        )

    # Unknown format, treat as any
    return TypeDescriptor(kind="any")


def are_types_compatible(
    source_type: Union[TypeDescriptor, Dict[str, Any], str, None],
    target_type: Union[TypeDescriptor, Dict[str, Any], str, None],
) -> bool:
    """Check if a source type is compatible with a target type.

    Compatibility rules:
    1. 'any' or 'unknown' types are compatible with anything
    2. int is compatible with float (numeric promotion)
    3. Nullable source requires nullable target (nullable safety)
    4. Container types check element type compatibility recursively
    5. Record types check that all target fields exist with compatible types

    Args:
        source_type: The type of the source port (output)
        target_type: The type of the target port (input)

    Returns:
        True if the connection is valid
    """
    src = normalize_type(source_type)
    tgt = normalize_type(target_type)

    # Rule 1: Any/unknown accepts or provides anything
    if src.is_any() or tgt.is_any():
        return True

    # Rule 2: int -> float promotion
    if src.kind == "int" and tgt.kind == "float":
        return True

    # Rule 3: Nullable safety (source can be null, target must accept null)
    if src.nullable and not tgt.nullable:
        return False

    # Kind must match for remaining checks
    if src.kind != tgt.kind:
        return False

    # Rule 4: Container element type compatibility
    if src.kind == "list" and src.item and tgt.item:
        return are_types_compatible(src.item, tgt.item)

    if src.kind == "map" and src.value and tgt.value:
        return are_types_compatible(src.value, tgt.value)

    if src.kind == "option" and src.item and tgt.item:
        return are_types_compatible(src.item, tgt.item)

    # Rule 5: Record field compatibility
    if src.kind == "record" and src.fields and tgt.fields:
        # Target must have all required fields with compatible types
        for field_name, target_field_type in tgt.fields.items():
            source_field_type = src.fields.get(field_name)
            if source_field_type is None:
                return False  # Missing required field
            if not are_types_compatible(source_field_type, target_field_type):
                return False
        return True

    # Tensor dtype compatibility
    if src.kind == "tensor":
        src_dtype = src.metadata.get("dtype") if src.metadata else None
        tgt_dtype = tgt.metadata.get("dtype") if tgt.metadata else None
        if src_dtype and tgt_dtype and src_dtype != tgt_dtype:
            return False

    return True


def get_type_label(type_desc: Union[TypeDescriptor, Dict[str, Any], str, None]) -> str:
    """Get a human-readable label for a type.

    Args:
        type_desc: The type to describe

    Returns:
        A human-readable string like "list<int>" or "map<string>"
    """
    td = normalize_type(type_desc)

    if td.kind == "list" and td.item:
        return f"list<{get_type_label(td.item)}>"

    if td.kind == "map":
        if td.value:
            return f"map<{get_type_label(td.value)}>"
        return "map"

    if td.kind == "option" and td.item:
        return f"{get_type_label(td.item)}?"

    if td.kind == "record" and td.fields:
        field_strs = [f"{name}: {get_type_label(ft)}" for name, ft in td.fields.items()]
        return "{" + ", ".join(field_strs) + "}"

    if td.kind == "tensor" and td.metadata and td.metadata.get("dtype"):
        return f"tensor<{td.metadata['dtype']}>"

    if td.nullable and td.kind not in ("any", "unknown"):
        return f"{td.kind}?"

    return td.kind
