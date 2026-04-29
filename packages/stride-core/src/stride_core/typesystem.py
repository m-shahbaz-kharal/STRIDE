"""
Type system for STRIDE nodes.

Provides :class:`TypeDescriptor` plus factory functions for the canonical
taxonomy described in
``docs/architecture/unified-type-system-and-ux.md`` §3.

Design principles
-----------------

- ``kind`` is a *category* label (used for colours, icons, visualiser
  dispatch). It identifies the family of payloads ("this is a 2-D
  detection bundle"). It does **not** carry the schema by itself.
- For *domain* payloads, the schema is encoded as the descriptor's
  ``fields`` map (the same field used by ``record``). The schema lives in
  this module so packages cannot redefine it.
- ``metadata.subtype`` is a non-binding refinement string used for UI
  rendering and visualiser dispatch. ``is_assignable_to`` allows
  *widening* on subtype: a more specific source flows into a less
  specific (or unspecified) target, but not the other way around.

Phase 1 reference: design doc §3.2-3.4, §4.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


PRIMITIVES = {"int", "float", "string", "boolean", "null"}
CONTAINERS = {"list", "map", "record", "tuple", "option"}
FLEXIBLE = {
    "any", "unknown", "tensor", "control", "stream",
    "point", "box", "mask", "session",
    "pointcloud", "bbox3d", "region3d", "scene3d",
    "image", "bbox2d", "detections2d", "detections3d", "depthmap",
    "track2d", "track3d", "keypoints",
}


@dataclass(frozen=True)
class TypeDescriptor:
    """Immutable descriptor for a port value type.

    ``element_type`` and ``key_type`` are the canonical field names; the
    ``item`` and ``value`` properties are compatibility aliases for
    callers that use the backend's older naming.

    The ``fields`` map is used both for ``record`` and for any *domain*
    kind whose schema is a fixed-shape record (e.g. ``bbox3d`` carries a
    ``fields`` map of ``id``, ``center``, ``size``, …). Compatibility
    checking treats a non-record kind with ``fields`` set the same way
    it treats a ``record``: structural subtyping on the schema, with the
    additional gate that ``kind`` must match (or one side is ``any`` /
    ``unknown``).
    """

    kind: str = "any"
    element_type: Optional["TypeDescriptor"] = None
    key_type: Optional["TypeDescriptor"] = None
    fields: Optional[Dict[str, "TypeDescriptor"]] = None
    nullable: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Optional name field for labeled types
    name: Optional[str] = None

    # =========================================================================
    # Compatibility Aliases
    # =========================================================================

    @property
    def item(self) -> Optional["TypeDescriptor"]:
        """Alias for element_type (for list/option/tuple)."""
        return self.element_type

    @property
    def value(self) -> Optional["TypeDescriptor"]:
        """Alias for element_type when used with maps."""
        return self.element_type if self.kind == "map" else None

    @property
    def subtype(self) -> Optional[str]:
        """Optional refinement tag used by UI/visualisers (§3.3)."""
        sub = self.metadata.get("subtype") if self.metadata else None
        return str(sub) if sub else None

    @property
    def payload_schema(self) -> Optional[Dict[str, "TypeDescriptor"]]:
        """The structural schema for this descriptor's payload, if any.

        For ``record`` and for domain-kind record-shaped types created by
        :func:`t_record_kind`, this is the ``fields`` map. Everything
        else returns ``None``.
        """
        return self.fields

    # =========================================================================
    # Type Checks
    # =========================================================================

    def is_primitive(self) -> bool:
        return self.kind in PRIMITIVES

    def is_container(self) -> bool:
        return self.kind in CONTAINERS

    def is_flexible(self) -> bool:
        return self.kind in FLEXIBLE

    def has_record_schema(self) -> bool:
        """True iff this descriptor carries a structural record schema.

        Includes ``record`` itself plus every domain kind built with
        :func:`t_record_kind`.
        """
        return self.fields is not None

    def with_nullable(self, nullable: bool = True) -> "TypeDescriptor":
        """Return a copy of this TypeDescriptor with nullable set to the given value."""
        return TypeDescriptor(
            kind=self.kind,
            element_type=self.element_type,
            key_type=self.key_type,
            fields=self.fields,
            nullable=nullable,
            metadata=self.metadata,
            name=self.name,
        )

    def with_subtype(self, subtype: Optional[str]) -> "TypeDescriptor":
        """Return a copy with ``metadata['subtype']`` set (or cleared)."""
        new_meta = dict(self.metadata) if self.metadata else {}
        if subtype is None:
            new_meta.pop("subtype", None)
        else:
            new_meta["subtype"] = subtype
        return TypeDescriptor(
            kind=self.kind,
            element_type=self.element_type,
            key_type=self.key_type,
            fields=self.fields,
            nullable=self.nullable,
            metadata=new_meta,
            name=self.name,
        )

    # =========================================================================
    # Serialization
    # =========================================================================

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a JSON-serializable dictionary."""
        data: Dict[str, Any] = {"kind": self.kind}
        if self.name is not None:
            data["name"] = self.name
        if self.element_type is not None:
            # Use both for max compatibility
            data["item"] = self.element_type.to_dict()
            if self.kind != "map":
                data["elementType"] = self.element_type.to_dict()
            else:
                data["value"] = self.element_type.to_dict()
        if self.key_type is not None:
            data["keyType"] = self.key_type.to_dict()
        if self.fields is not None:
            data["fields"] = {k: v.to_dict() for k, v in self.fields.items()}
        if self.nullable:
            data["nullable"] = True
        if self.metadata:
            data["metadata"] = self.metadata
        return data

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "TypeDescriptor":
        """Create a TypeDescriptor from a JSON dictionary."""
        kind = payload.get("kind")
        if not kind:
            raise ValueError("TypeDescriptor requires 'kind'")

        # Handle both naming conventions for element types
        element_raw = payload.get("item") or payload.get("elementType") or payload.get("element_type")
        value_raw = payload.get("value")
        key_raw = payload.get("keyType") or payload.get("key_type")

        element_type = None
        if kind == "map" and value_raw:
            element_type = TypeDescriptor.from_dict(value_raw)
        elif element_raw:
            element_type = TypeDescriptor.from_dict(element_raw)

        key_type = TypeDescriptor.from_dict(key_raw) if key_raw else None

        fields_raw = payload.get("fields")
        fields = {k: TypeDescriptor.from_dict(v) for k, v in fields_raw.items()} if fields_raw else None

        return TypeDescriptor(
            kind=kind,
            name=payload.get("name"),
            element_type=element_type,
            key_type=key_type,
            fields=fields,
            nullable=bool(payload.get("nullable", False)),
            metadata=payload.get("metadata", {}) or {},
        )

    # =========================================================================
    # Type Compatibility
    # =========================================================================

    def is_assignable_to(self, target: "TypeDescriptor") -> bool:
        """Check if this type can flow into ``target``.

        Rules (in order):

        1. ``any`` / ``unknown`` on either side is universally compatible.
        2. A nullable source cannot flow into a non-nullable target.
        3. ``int`` widens to ``float``.
        4. Different kinds otherwise reject.
        5. **Subtype widening** (§3.3): when both sides carry the same
           ``kind``, the source may have a more specific
           ``metadata.subtype`` than the target, but not the reverse.
           A target without a ``subtype`` (or with ``subtype="any"``)
           accepts any source subtype.
        6. Container kinds (``list``, ``map``, ``option``) recurse on
           their element types.
        7. Record-shaped kinds (``record`` plus domain kinds whose
           schema is encoded via ``fields``) use structural subtyping:
           every required target field must be present in the source
           and recursively assignable.
        8. ``tensor`` requires matching ``dtype`` and ``shape`` when
           both sides specify them.
        """
        if target.kind == "any":
            return True
        if self.kind == "any":
            return True
        if target.kind == "unknown":
            return True
        if self.kind == "unknown":
            return True
        if self.nullable and not target.nullable:
            return False
        if self.kind != target.kind:
            # Allow int -> float widening
            if self.kind == "int" and target.kind == "float":
                return True
            return False

        # Same kind: enforce subtype widening rules.
        if not _subtype_compatible(self.subtype, target.subtype):
            return False

        if self.kind == "list":
            if not self.element_type or not target.element_type:
                return True
            return self.element_type.is_assignable_to(target.element_type)
        if self.kind == "map":
            if not self.element_type or not target.element_type:
                return True
            return self.element_type.is_assignable_to(target.element_type)
        if self.kind == "option":
            if not self.element_type or not target.element_type:
                return True
            return self.element_type.is_assignable_to(target.element_type)
        # Record-shaped kinds: structural subtyping on `fields`. This
        # covers `record` plus every domain kind built via
        # `t_record_kind` (image, bbox2d, pointcloud, …).
        if self.has_record_schema() or target.has_record_schema():
            # If only one side has a schema, the other is treated as a
            # "schema-less" descriptor of the same kind (e.g. an
            # un-detailed `t_image()`). That should still flow — the
            # static system has nothing to enforce. Schema validation
            # at the value level happens in NodeBase (Phase 2).
            if self.fields is None or target.fields is None:
                return True
            for key, val in target.fields.items():
                if key not in self.fields:
                    return False
                if not self.fields[key].is_assignable_to(val):
                    return False
            return True
        if self.kind == "tensor":
            target_dtype = target.metadata.get("dtype")
            source_dtype = self.metadata.get("dtype")
            if target_dtype and source_dtype and target_dtype != source_dtype:
                return False
            target_shape = target.metadata.get("shape")
            source_shape = self.metadata.get("shape")
            if target_shape and source_shape and target_shape != source_shape:
                return False
            return True
        return True

    def label(self) -> str:
        """Human-readable label for UI/tooling."""
        if self.kind == "control":
            return "Control"
        if self.kind == "list" and self.element_type:
            return f"List<{self.element_type.label()}>"
        if self.kind == "map" and self.element_type:
            return f"Map<string,{self.element_type.label()}>"
        if self.kind == "record" and self.fields:
            return "Record"
        if self.kind == "option" and self.element_type:
            return f"Option<{self.element_type.label()}>"
        if self.kind == "tensor":
            shape = self.metadata.get("shape")
            dtype = self.metadata.get("dtype", "float32")
            shape_str = f"[{', '.join(map(str, shape))}]" if shape else ""
            return f"Tensor{shape_str}:{dtype}"
        sub = self.subtype
        if sub:
            return f"{self.kind.capitalize()}[{sub}]"
        return self.kind.capitalize()

    def __repr__(self) -> str:
        parts = [f"kind={self.kind!r}"]
        if self.element_type:
            parts.append(f"element={self.element_type.kind!r}")
        if self.key_type:
            parts.append(f"key={self.key_type.kind!r}")
        if self.fields:
            parts.append(f"fields={list(self.fields.keys())}")
        sub = self.subtype
        if sub:
            parts.append(f"subtype={sub!r}")
        if self.nullable:
            parts.append("nullable=True")
        return f"TypeDescriptor({', '.join(parts)})"


def _subtype_compatible(source_sub: Optional[str], target_sub: Optional[str]) -> bool:
    """Subtype-widening rule (§3.3 + user decision for Phase 1).

    A source subtype is *more specific than or equal to* a target subtype
    when:

    - the target has no subtype, or
    - the target's subtype is ``"any"``, or
    - both subtypes are equal.

    A target with a specific subtype rejects a source with no subtype
    (the source could be anything, the target only accepts the
    refinement). A specific source flows into a generic target — the
    "widening" direction.
    """
    if not target_sub or target_sub == "any":
        return True
    return source_sub == target_sub


def types_compatible(source: TypeDescriptor, target: TypeDescriptor) -> bool:
    """
    Check if a source type can be connected to a target type.

    This is the older entry point used by the engine-side validator
    (``backend/app/engine/graph_builder.py``). It is now a thin wrapper
    around :meth:`TypeDescriptor.is_assignable_to`.
    """
    return source.is_assignable_to(target)


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


def t_list(element_type: TypeDescriptor) -> TypeDescriptor:
    """Create a list type descriptor."""
    return TypeDescriptor(kind="list", element_type=element_type)


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


def t_record_kind(
    kind: str,
    fields: Dict[str, TypeDescriptor],
    *,
    subtype: Optional[str] = None,
) -> TypeDescriptor:
    """Record with a non-default kind tag.

    Used for domain payloads that want both a category label AND a
    schema. ``kind`` drives category-identity (colour, icon, visualiser
    dispatch); ``fields`` drives structural-subtyping checks; optional
    ``subtype`` is a UI-only refinement tag (§3.3).
    """
    metadata: Dict[str, Any] = {}
    if subtype:
        metadata["subtype"] = subtype
    return TypeDescriptor(kind=kind, fields=fields, metadata=metadata)


def t_tensor(dtype: str = "float32", shape: Optional[List[int]] = None) -> TypeDescriptor:
    return TypeDescriptor(kind="tensor", metadata={"dtype": dtype, "shape": shape or []})


# Sugar for fixed-shape numeric tensors (§3.2.3).

def t_vec2() -> TypeDescriptor:
    return t_tensor(dtype="float32", shape=[2])


def t_vec3() -> TypeDescriptor:
    return t_tensor(dtype="float32", shape=[3])


def t_quat() -> TypeDescriptor:
    return t_tensor(dtype="float32", shape=[4])


def t_mat3() -> TypeDescriptor:
    return t_tensor(dtype="float32", shape=[3, 3])


def t_mat4() -> TypeDescriptor:
    return t_tensor(dtype="float32", shape=[4, 4])


def t_session() -> TypeDescriptor:
    """An AI model session handle. Opaque, not serialisable."""
    return TypeDescriptor(kind="session")


# =============================================================================
# Image / 2-D detection types (§3.2.4-3.2.5)
# =============================================================================
#
# Wire form for `image` (the canonical record):
#
#     {
#         "_type": "Image",
#         "width":   int,
#         "height":  int,
#         "format":  str,         # "jpeg" | "png" | "webp" | …
#         "data_b64": str,        # data URL or raw base64 — see metadata.subtype
#     }
#
# Subtype convention (`metadata.subtype` on the descriptor only — wire
# values do not carry the subtype tag):
#
#   - `"data_url"` : `data_b64` is `"data:image/<format>;base64,<…>"`.
#   - `"raw_b64"`  : `data_b64` is the base64 payload only.
#   - `"url"`      : `data_b64` is an http(s) URL pointing at the image.
#   - `"rgb"` / `"grayscale"` / `"mono16"` : pixel-format refinements
#     used by visualisers and downstream nodes.


def t_image(*, subtype: Optional[str] = None) -> TypeDescriptor:
    """A 2-D image carried as a base64 record.

    See module docstring for the wire schema. ``subtype`` is an optional
    refinement tag (e.g. ``"rgb"``, ``"grayscale"``, ``"data_url"``).
    """
    return t_record_kind(
        "image",
        fields={
            "_type":    t_string(),
            "width":    t_int(),
            "height":   t_int(),
            "format":   t_string(),
            "data_b64": t_string(),
        },
        subtype=subtype,
    )


def t_mask() -> TypeDescriptor:
    """A 2-D segmentation mask (PNG-encoded, base64)."""
    return t_record_kind(
        "mask",
        fields={
            "_type":    t_string(),
            "width":    t_int(),
            "height":   t_int(),
            "data_b64": t_string(),
            "encoding": t_string(),
        },
    )


def t_depthmap() -> TypeDescriptor:
    """A per-pixel depth map (float32 packed, base64)."""
    return t_record_kind(
        "depthmap",
        fields={
            "_type":     t_string(),
            "width":     t_int(),
            "height":    t_int(),
            "depth_b64": t_string(),
            "min_depth": t_float(),
            "max_depth": t_float(),
            "image":     t_image().with_nullable(True),
        },
    )


def t_bbox2d() -> TypeDescriptor:
    """A 2-D bounding box with class label and confidence."""
    return t_record_kind(
        "bbox2d",
        fields={
            "x1":         t_float(),
            "y1":         t_float(),
            "x2":         t_float(),
            "y2":         t_float(),
            "confidence": t_float(),
            "class_id":   t_int(),
            "class_name": t_string(),
            "track_id":   t_int().with_nullable(True),
        },
    )


def t_track2d() -> TypeDescriptor:
    """A tracked 2-D detection (bbox2d + non-null track id + history)."""
    return t_record_kind(
        "track2d",
        fields={
            "x1":          t_float(),
            "y1":          t_float(),
            "x2":          t_float(),
            "y2":          t_float(),
            "confidence":  t_float(),
            "class_id":    t_int(),
            "class_name":  t_string(),
            "track_id":    t_int(),
            "track_age":   t_int(),
            "track_score": t_float(),
        },
    )


def t_keypoints() -> TypeDescriptor:
    """A set of keypoints (e.g. body pose, hands, face landmarks)."""
    return t_record_kind(
        "keypoints",
        fields={
            "_type":       t_string(),
            "instances":   t_list(t_any()),
            "schema_name": t_string().with_nullable(True),
        },
    )


def t_detections2d() -> TypeDescriptor:
    """A bundle of 2-D detections with source image metadata."""
    return t_record_kind(
        "detections2d",
        fields={
            "_type":        t_string(),
            "image_width":  t_int(),
            "image_height": t_int(),
            "boxes":        t_list(t_bbox2d()),
            "image":        t_image().with_nullable(True),
        },
    )


# =============================================================================
# 3-D detection / scene types (§3.2.6)
# =============================================================================


def t_pointcloud(*, subtype: Optional[str] = None) -> TypeDescriptor:
    """A 3-D point cloud (positions + optional per-point fields).

    ``subtype`` is an optional refinement (e.g. ``"lidar"``, ``"rgbd"``,
    ``"xyz"``, ``"xyzi"``, ``"xyzrgb"``).
    """
    return t_record_kind(
        "pointcloud",
        fields={
            "_type":         t_string(),
            "num_points":    t_int(),
            "positions_b64": t_string().with_nullable(True),
            "fields_b64":    t_map(t_string(), t_string()).with_nullable(True),
            "positions":     t_list(t_vec3()).with_nullable(True),
            "fields":        t_map(t_string(), t_list(t_float())).with_nullable(True),
            "frame":         t_string().with_nullable(True),
        },
        subtype=subtype,
    )


def t_bbox3d() -> TypeDescriptor:
    """A 3-D bounding box. Frame: world; units: metres."""
    return t_record_kind(
        "bbox3d",
        fields={
            "id":         t_int().with_nullable(True),
            "center":     t_list(t_float()),   # [x, y, z]
            "size":       t_list(t_float()),   # [w, h, d]
            "rotation":   t_list(t_float()).with_nullable(True),  # quaternion
            "velocity":   t_list(t_float()).with_nullable(True),  # [vx, vy, vz]
            "confidence": t_float().with_nullable(True),
            "class_id":   t_int().with_nullable(True),
            "class_name": t_string().with_nullable(True),
            "frame":      t_string().with_nullable(True),
        },
    )


def t_track3d() -> TypeDescriptor:
    """A tracked 3-D detection (bbox3d + non-null track id + history)."""
    return t_record_kind(
        "track3d",
        fields={
            "id":          t_int(),
            "center":      t_list(t_float()),
            "size":        t_list(t_float()),
            "rotation":    t_list(t_float()).with_nullable(True),
            "velocity":    t_list(t_float()).with_nullable(True),
            "confidence":  t_float().with_nullable(True),
            "class_id":    t_int().with_nullable(True),
            "class_name":  t_string().with_nullable(True),
            "frame":       t_string().with_nullable(True),
            "track_age":   t_int(),
            "track_score": t_float(),
        },
    )


def t_region3d() -> TypeDescriptor:
    """A 3-D occupancy region (cuboid; centre, size, optional rotation)."""
    return t_record_kind(
        "region3d",
        fields={
            "name":     t_string(),
            "center":   t_list(t_float()),
            "size":     t_list(t_float()),
            "rotation": t_list(t_float()).with_nullable(True),
        },
    )


def t_detections3d() -> TypeDescriptor:
    """A bundle of 3-D detections."""
    return t_record_kind(
        "detections3d",
        fields={
            "_type":          t_string(),
            "boxes":          t_list(t_bbox3d()),
            "scene_metadata": t_map(t_string(), t_any()).with_nullable(True),
        },
    )


def t_scene3d() -> TypeDescriptor:
    """A 3-D scene for visualization (point cloud + boxes + regions)."""
    return t_record_kind(
        "scene3d",
        fields={
            "_type":          t_string(),
            "point_cloud":    t_pointcloud(),
            "boxes":          t_list(t_bbox3d()),
            "regions":        t_list(t_region3d()),
            "occupancy":      t_list(t_int()),
            "image_overlays": t_list(t_image()).with_nullable(True),
        },
    )


# =============================================================================
# Stream / resource types (§3.2.7, §3.6)
# =============================================================================


def t_stream() -> TypeDescriptor:
    """A live stream resource handle.

    The wire form carries only what the frontend needs to render. The
    in-process Python handle stays in ``ACTIVE_STREAMS`` (cross-process
    re-attachment is a Phase-3+ concern, see design doc §3.6).
    """
    return t_record_kind(
        "stream",
        fields={
            "_type":      t_string(),   # always "StreamResource"
            "stream_id":  t_string(),
            "width":      t_int(),
            "height":     t_int(),
            "target_fps": t_int(),
            "active":     t_boolean(),
        },
    )


# =============================================================================
# Backwards-compat shims
# =============================================================================
#
# `t_point` and `t_box` predate the canonical taxonomy. They are kept
# as marker kinds (no schema) for the rare nodes that still reference
# them; the design doc lists them as "deprecated; use record" and they
# will be removed in Phase 5.


def t_point() -> TypeDescriptor:
    """A 2-D point with x, y coordinates (deprecated; use record)."""
    return TypeDescriptor(kind="point")


def t_box() -> TypeDescriptor:
    """A bounding box marker (deprecated; use t_bbox2d)."""
    return TypeDescriptor(kind="box")
