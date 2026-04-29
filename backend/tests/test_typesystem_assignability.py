"""
Tests for ``TypeDescriptor.is_assignable_to`` after the Phase 1 rewrite.

Covers the rules from
``docs/architecture/unified-type-system-and-ux.md`` §3.4 + §4.2:

- Same kind, same subtype = OK
- Specific subtype source -> generic-or-equal subtype target = OK
- Generic source -> specific target = REJECT
- ``int -> float`` widening
- ``float -> int`` rejection
- Record structural subtyping
- Mismatched kinds reject
- Domain kinds with the same record schema flow freely
- Payload-schema-divergent same-kind nodes are OK at type level
  (schema validation is Phase 2's job)
"""

from __future__ import annotations

import pytest

from app.typesystem import (
    TypeDescriptor,
    t_any,
    t_bbox2d,
    t_bbox3d,
    t_boolean,
    t_detections2d,
    t_float,
    t_image,
    t_int,
    t_keypoints,
    t_list,
    t_mask,
    t_pointcloud,
    t_record,
    t_record_kind,
    t_string,
    t_track2d,
    t_track3d,
)


class TestSameKindSameSubtype:
    """Trivial identity flow."""

    def test_identical_descriptors_flow(self) -> None:
        assert t_int().is_assignable_to(t_int())
        assert t_string().is_assignable_to(t_string())
        assert t_image().is_assignable_to(t_image())
        assert t_bbox3d().is_assignable_to(t_bbox3d())

    def test_same_explicit_subtype_flows(self) -> None:
        rgb_a = t_image(subtype="rgb")
        rgb_b = t_image(subtype="rgb")
        assert rgb_a.is_assignable_to(rgb_b)


class TestSubtypeWidening:
    """``image[rgb]`` -> ``image[any]`` flows; ``image[any]`` -> ``image[rgb]`` rejects."""

    def test_specific_to_unspecified_target(self) -> None:
        rgb = t_image(subtype="rgb")
        bare = t_image()  # no subtype
        assert rgb.is_assignable_to(bare)

    def test_specific_to_any_subtype_target(self) -> None:
        rgb = t_image(subtype="rgb")
        any_sub = t_image(subtype="any")
        assert rgb.is_assignable_to(any_sub)

    def test_unspecified_to_specific_target_rejects(self) -> None:
        bare = t_image()
        rgb = t_image(subtype="rgb")
        assert not bare.is_assignable_to(rgb)

    def test_specific_to_different_specific_rejects(self) -> None:
        rgb = t_image(subtype="rgb")
        gray = t_image(subtype="grayscale")
        assert not rgb.is_assignable_to(gray)
        assert not gray.is_assignable_to(rgb)

    def test_pointcloud_xyz_to_pointcloud_any_flows(self) -> None:
        xyz = t_pointcloud(subtype="xyz")
        any_pc = t_pointcloud(subtype="any")
        assert xyz.is_assignable_to(any_pc)
        # Reverse direction rejects.
        assert not any_pc.is_assignable_to(t_pointcloud(subtype="xyz"))


class TestNumericWidening:
    """``int`` widens to ``float``, but not vice versa."""

    def test_int_to_float(self) -> None:
        assert t_int().is_assignable_to(t_float())

    def test_float_to_int_rejects(self) -> None:
        assert not t_float().is_assignable_to(t_int())

    def test_int_to_int(self) -> None:
        assert t_int().is_assignable_to(t_int())

    def test_widening_inside_lists(self) -> None:
        assert t_list(t_int()).is_assignable_to(t_list(t_float()))
        assert not t_list(t_float()).is_assignable_to(t_list(t_int()))


class TestRecordStructuralSubtyping:
    """Source record must contain every target field, recursively assignable."""

    def test_extra_source_fields_ok(self) -> None:
        source = t_record({
            "name": t_string(),
            "age":  t_int(),
            "city": t_string(),
        })
        target = t_record({
            "name": t_string(),
            "age":  t_int(),
        })
        assert source.is_assignable_to(target)

    def test_missing_source_field_rejects(self) -> None:
        source = t_record({"name": t_string()})
        target = t_record({"name": t_string(), "age": t_int()})
        assert not source.is_assignable_to(target)

    def test_field_type_mismatch_rejects(self) -> None:
        source = t_record({"age": t_string()})
        target = t_record({"age": t_int()})
        assert not source.is_assignable_to(target)


class TestKindMismatch:
    """Different kinds reject (except via the explicit widening / any rules)."""

    def test_string_to_int_rejects(self) -> None:
        assert not t_string().is_assignable_to(t_int())

    def test_image_to_pointcloud_rejects(self) -> None:
        assert not t_image().is_assignable_to(t_pointcloud())

    def test_bbox2d_to_bbox3d_rejects(self) -> None:
        assert not t_bbox2d().is_assignable_to(t_bbox3d())

    def test_list_to_record_rejects(self) -> None:
        assert not t_list(t_int()).is_assignable_to(t_record({"x": t_int()}))


class TestAnyAndUnknown:
    """``any`` / ``unknown`` accept and produce anything."""

    def test_any_accepts_anything(self) -> None:
        assert t_image().is_assignable_to(t_any())
        assert t_int().is_assignable_to(t_any())

    def test_anything_accepts_any(self) -> None:
        assert t_any().is_assignable_to(t_image())
        assert t_any().is_assignable_to(t_pointcloud())


class TestDomainRecordKindFlow:
    """Cross-package wiring on canonical types should flow freely."""

    def test_bbox2d_to_bbox2d(self) -> None:
        assert t_bbox2d().is_assignable_to(t_bbox2d())

    def test_track2d_distinct_kind_from_bbox2d(self) -> None:
        # Per the Phase-1 user decision: only *same-kind* subtype
        # widening flows implicitly. Cross-kind structural widening
        # (track2d -> bbox2d) is not in Phase 1 — track2d and bbox2d
        # carry different ``kind`` tags and require an explicit
        # converter (or, in Phase 4+, a refinement-via-subtype model).
        assert not t_track2d().is_assignable_to(t_bbox2d())
        # Reverse direction also rejects (track2d demands non-null
        # track_id, bbox2d's is nullable).
        assert not t_bbox2d().is_assignable_to(t_track2d())

    def test_track3d_distinct_kind_from_bbox3d(self) -> None:
        # Same Phase-1 binding rule as the 2-D case.
        assert not t_track3d().is_assignable_to(t_bbox3d())
        assert not t_bbox3d().is_assignable_to(t_track3d())

    def test_list_of_bbox3d_flows_through(self) -> None:
        # The headline cross-package wiring case: people.detect emits
        # list<bbox3d>, kalman.tracker3d consumes list<bbox3d>.
        assert t_list(t_bbox3d()).is_assignable_to(t_list(t_bbox3d()))

    def test_detections2d_kind_isolation(self) -> None:
        # detections2d shares no `kind` with bbox2d — it's an aggregate.
        assert not t_detections2d().is_assignable_to(t_bbox2d())
        assert not t_bbox2d().is_assignable_to(t_detections2d())

    def test_payload_schema_divergent_same_kind_ok_at_type_level(self) -> None:
        # A "lean" image descriptor with no fields (older spec form, or
        # a schema-less marker) still flows into a fully-specified
        # image. The static system has nothing to enforce; runtime
        # field-presence checks live in NodeBase (Phase 2).
        bare = TypeDescriptor(kind="image")  # no fields, no metadata
        full = t_image()                     # full record schema
        assert bare.is_assignable_to(full)
        assert full.is_assignable_to(bare)


class TestNullability:
    """Existing nullable rule preserved: nullable -> non-nullable rejects."""

    def test_nullable_source_rejects_non_nullable_target(self) -> None:
        source = t_string().with_nullable(True)
        target = t_string().with_nullable(False)
        assert not source.is_assignable_to(target)

    def test_non_nullable_source_to_nullable_target_ok(self) -> None:
        source = t_string()
        target = t_string().with_nullable(True)
        assert source.is_assignable_to(target)


class TestPayloadSchemaAccessor:
    """Phase 1 added a ``payload_schema`` property on every domain type."""

    @pytest.mark.parametrize(
        "factory,expected_keys",
        [
            (t_image,        {"_type", "width", "height", "format", "data_b64"}),
            (t_mask,         {"_type", "width", "height", "data_b64", "encoding"}),
            (t_bbox2d,       {"x1", "y1", "x2", "y2", "confidence", "class_id",
                              "class_name", "track_id"}),
            (t_bbox3d,       {"id", "center", "size", "rotation", "velocity",
                              "confidence", "class_id", "class_name", "frame"}),
            (t_keypoints,    {"_type", "instances", "schema_name"}),
            (t_detections2d, {"_type", "image_width", "image_height", "boxes",
                              "image"}),
        ],
    )
    def test_canonical_kinds_carry_full_schema(self, factory, expected_keys) -> None:
        td = factory()
        schema = td.payload_schema
        assert schema is not None, f"{factory.__name__} should expose payload_schema"
        assert set(schema.keys()) == expected_keys, (
            f"{factory.__name__} schema keys: got {set(schema.keys())}, "
            f"expected {expected_keys}"
        )
