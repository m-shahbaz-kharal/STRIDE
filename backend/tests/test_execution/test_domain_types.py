"""
Tests for the domain types module.

Verifies:
- Type normalization
- Type compatibility rules
- Type label generation
"""

import pytest
from app.domain.types import (
    TypeDescriptor,
    normalize_type,
    are_types_compatible,
    get_type_label,
)


class TestNormalizeType:
    """Tests for normalize_type function."""

    def test_none_becomes_any(self):
        """None input returns any type."""
        result = normalize_type(None)
        assert result.kind == "any"

    def test_string_becomes_simple_type(self):
        """String input creates simple type."""
        result = normalize_type("int")
        assert result.kind == "int"
        assert result.item is None

    def test_number_normalized_to_float(self):
        """'number' is normalized to 'float'."""
        result = normalize_type("number")
        assert result.kind == "float"

    def test_dict_creates_full_descriptor(self):
        """Dict input creates full type descriptor."""
        result = normalize_type({
            "kind": "list",
            "item": {"kind": "int"},
        })
        assert result.kind == "list"
        assert result.item is not None
        assert result.item.kind == "int"

    def test_element_type_normalized_to_item(self):
        """element_type key is normalized to item."""
        result = normalize_type({
            "kind": "list",
            "elementType": "string",
        })
        assert result.kind == "list"
        assert result.item is not None
        assert result.item.kind == "string"

    def test_map_element_type_becomes_value(self):
        """For maps, elementType becomes value."""
        result = normalize_type({
            "kind": "map",
            "elementType": "int",
        })
        assert result.kind == "map"
        assert result.value is not None
        assert result.value.kind == "int"

    def test_nested_fields_normalized(self):
        """Record field types are recursively normalized."""
        result = normalize_type({
            "kind": "record",
            "fields": {
                "name": "string",
                "age": {"kind": "int"},
            },
        })
        assert result.kind == "record"
        assert result.fields is not None
        assert result.fields["name"].kind == "string"
        assert result.fields["age"].kind == "int"


class TestAreTypesCompatible:
    """Tests for are_types_compatible function."""

    def test_any_compatible_with_everything(self):
        """'any' type is compatible with any other type."""
        assert are_types_compatible("any", "int") is True
        assert are_types_compatible("int", "any") is True
        assert are_types_compatible("any", "any") is True

    def test_unknown_compatible_with_everything(self):
        """'unknown' type is compatible with any other type."""
        assert are_types_compatible("unknown", "string") is True
        assert are_types_compatible("list", "unknown") is True

    def test_int_compatible_with_float(self):
        """int can be assigned to float (numeric promotion)."""
        assert are_types_compatible("int", "float") is True

    def test_float_not_compatible_with_int(self):
        """float cannot be assigned to int."""
        assert are_types_compatible("float", "int") is False

    def test_same_types_compatible(self):
        """Same types are always compatible."""
        assert are_types_compatible("string", "string") is True
        assert are_types_compatible("int", "int") is True
        assert are_types_compatible("bool", "bool") is True

    def test_different_types_not_compatible(self):
        """Different types are not compatible."""
        assert are_types_compatible("string", "int") is False
        assert are_types_compatible("bool", "string") is False

    def test_nullable_source_requires_nullable_target(self):
        """Nullable source requires nullable target."""
        src = TypeDescriptor(kind="string", nullable=True)
        tgt = TypeDescriptor(kind="string", nullable=False)
        assert are_types_compatible(src, tgt) is False

        tgt_nullable = TypeDescriptor(kind="string", nullable=True)
        assert are_types_compatible(src, tgt_nullable) is True

    def test_list_element_compatibility(self):
        """List compatibility checks element types."""
        list_int = TypeDescriptor(kind="list", item=TypeDescriptor(kind="int"))
        list_float = TypeDescriptor(kind="list", item=TypeDescriptor(kind="float"))
        list_string = TypeDescriptor(kind="list", item=TypeDescriptor(kind="string"))

        # int list compatible with float list (promotion)
        assert are_types_compatible(list_int, list_float) is True

        # float list not compatible with int list
        assert are_types_compatible(list_float, list_int) is False

        # different element types not compatible
        assert are_types_compatible(list_int, list_string) is False

    def test_map_value_compatibility(self):
        """Map compatibility checks value types."""
        map_int = TypeDescriptor(kind="map", value=TypeDescriptor(kind="int"))
        map_float = TypeDescriptor(kind="map", value=TypeDescriptor(kind="float"))

        assert are_types_compatible(map_int, map_float) is True
        assert are_types_compatible(map_float, map_int) is False

    def test_record_field_compatibility(self):
        """Record compatibility checks all target fields exist."""
        source = TypeDescriptor(
            kind="record",
            fields={
                "name": TypeDescriptor(kind="string"),
                "age": TypeDescriptor(kind="int"),
            }
        )
        target = TypeDescriptor(
            kind="record",
            fields={
                "name": TypeDescriptor(kind="string"),
            }
        )

        # Source has extra fields - ok
        assert are_types_compatible(source, target) is True

        # Target has fields source doesn't
        target_extra = TypeDescriptor(
            kind="record",
            fields={
                "name": TypeDescriptor(kind="string"),
                "email": TypeDescriptor(kind="string"),
            }
        )
        assert are_types_compatible(source, target_extra) is False

    def test_tensor_dtype_compatibility(self):
        """Tensor compatibility checks dtype when specified."""
        tensor_f32 = TypeDescriptor(kind="tensor", metadata={"dtype": "float32"})
        tensor_f64 = TypeDescriptor(kind="tensor", metadata={"dtype": "float64"})
        tensor_any = TypeDescriptor(kind="tensor")

        # Different dtypes not compatible
        assert are_types_compatible(tensor_f32, tensor_f64) is False

        # Unspecified dtype is compatible
        assert are_types_compatible(tensor_f32, tensor_any) is True
        assert are_types_compatible(tensor_any, tensor_f32) is True


class TestGetTypeLabel:
    """Tests for get_type_label function."""

    def test_simple_type_label(self):
        """Simple types return their kind."""
        assert get_type_label("int") == "int"
        assert get_type_label("string") == "string"
        assert get_type_label("bool") == "bool"

    def test_list_label(self):
        """List types show element type."""
        td = TypeDescriptor(kind="list", item=TypeDescriptor(kind="int"))
        assert get_type_label(td) == "list<int>"

    def test_map_label(self):
        """Map types show value type."""
        td = TypeDescriptor(kind="map", value=TypeDescriptor(kind="string"))
        assert get_type_label(td) == "map<string>"

    def test_option_label(self):
        """Option types show inner type with ?."""
        td = TypeDescriptor(kind="option", item=TypeDescriptor(kind="int"))
        assert get_type_label(td) == "int?"

    def test_nullable_label(self):
        """Nullable types append ?."""
        td = TypeDescriptor(kind="string", nullable=True)
        assert get_type_label(td) == "string?"

    def test_tensor_with_dtype_label(self):
        """Tensor types show dtype."""
        td = TypeDescriptor(kind="tensor", metadata={"dtype": "float32"})
        assert get_type_label(td) == "tensor<float32>"

    def test_nested_list_label(self):
        """Nested types are fully expanded."""
        td = TypeDescriptor(
            kind="list",
            item=TypeDescriptor(
                kind="list",
                item=TypeDescriptor(kind="int")
            )
        )
        assert get_type_label(td) == "list<list<int>>"
