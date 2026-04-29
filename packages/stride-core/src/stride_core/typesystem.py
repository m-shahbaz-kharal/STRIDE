"""
Type system for LiGuard-Web nodes.

Provides TypeDescriptor and factory functions for creating type specifications.
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
    """Immutable descriptor for a data type in the node system.
    
    This class uses `element_type` and `key_type` as the canonical field names,
    but provides `item` and `value` property aliases for compatibility with
    the backend's type system conventions.
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

    # =========================================================================
    # Type Checks
    # =========================================================================

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
        """Check if this type can flow into the target type."""
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
        if self.kind == "record":
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
        return self.kind.capitalize()

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
        if source.fields is not None and target.fields is not None:
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


def t_tensor(dtype: str = "float32", shape: Optional[List[int]] = None) -> TypeDescriptor:
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


def t_pointcloud() -> TypeDescriptor:
    """A 3D point cloud (positions + optional per-point fields)."""
    return TypeDescriptor(kind="pointcloud")


def t_bbox3d() -> TypeDescriptor:
    """A 3D bounding box (center, size, id)."""
    return TypeDescriptor(kind="bbox3d")


def t_region3d() -> TypeDescriptor:
    """A 3D occupancy region (center, size, name)."""
    return TypeDescriptor(kind="region3d")


def t_scene3d() -> TypeDescriptor:
    """A 3D scene for visualization (point cloud + boxes + regions)."""
    return TypeDescriptor(kind="scene3d")


# =============================================================================
# Image / 2D Detection Types
# =============================================================================
#
# Convention used across STRIDE image packages:
#
# - An *image* is a base64-encoded data URL string (e.g.
#   "data:image/jpeg;base64,...") matching what `core.image.load` produces.
#   The `image` kind below is a marker for that — values are still strings on
#   the wire, but the type label conveys "this string is an image".
#
# - A *bbox2d* is a record describing a single 2D detection result:
#       {
#           "x1": float, "y1": float, "x2": float, "y2": float,  # absolute pixel coords
#           "confidence": float,
#           "class_id": int,
#           "class_name": str,
#           "track_id": int (optional, set by trackers),
#       }
#   Coordinates are absolute pixel coordinates (top-left origin).
#
# - A *detections2d* is a record bundling a list of bbox2d with image metadata:
#       {
#           "_type": "Detections2D",
#           "image_width": int,
#           "image_height": int,
#           "boxes": [bbox2d, ...],
#           "image": str (optional base64 thumbnail),
#       }
#
# - A *depthmap* is a record describing a per-pixel depth result:
#       {
#           "_type": "DepthMap",
#           "width": int, "height": int,
#           "depth_b64": str (float32 packed),
#           "min_depth": float, "max_depth": float,
#           "image": str (optional colorized base64 visualization),
#       }
#
# - A *keypoints* record bundles per-instance keypoint sets, e.g. body pose:
#       {
#           "_type": "Keypoints",
#           "instances": [
#               {"keypoints": [[x, y, score], ...], "bbox": bbox2d (optional)}
#           ],
#       }
#
# These conventions are used by stride-yolo, stride-rtdetr, stride-mediapipe,
# stride-depth-anything, stride-bytetrack, stride-clip, and the *-pcdet 3D
# detectors. New packages should reuse them.


def t_image() -> TypeDescriptor:
    """A 2D image (carried as a base64 data URL string in practice)."""
    return TypeDescriptor(kind="image")


def t_bbox2d() -> TypeDescriptor:
    """A 2D bounding box with class label and confidence."""
    return t_record({
        "x1": t_float(),
        "y1": t_float(),
        "x2": t_float(),
        "y2": t_float(),
        "confidence": t_float(),
        "class_id": t_int(),
        "class_name": t_string(),
    })


def t_detections2d() -> TypeDescriptor:
    """A bundle of 2D detections with source image metadata."""
    return TypeDescriptor(kind="detections2d")


def t_detections3d() -> TypeDescriptor:
    """A bundle of 3D detections (boxes + scores + class labels)."""
    return TypeDescriptor(kind="detections3d")


def t_depthmap() -> TypeDescriptor:
    """A per-pixel depth map."""
    return TypeDescriptor(kind="depthmap")


def t_track2d() -> TypeDescriptor:
    """A tracked 2D detection (bbox2d + persistent track id)."""
    return TypeDescriptor(kind="track2d")


def t_track3d() -> TypeDescriptor:
    """A tracked 3D detection (bbox3d + persistent track id)."""
    return TypeDescriptor(kind="track3d")


def t_keypoints() -> TypeDescriptor:
    """A set of keypoints (e.g. body pose, hands, face landmarks)."""
    return TypeDescriptor(kind="keypoints")
