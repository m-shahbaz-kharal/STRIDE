"""
STRIDE Backend Type System.

Thin re-export layer over :mod:`stride_core.typesystem`. The canonical
taxonomy lives in stride-core so plugins outside the backend tree can
share the same factories.
"""

from stride_core.typesystem import (
    # Type descriptor class
    TypeDescriptor,
    # Type compatibility check
    types_compatible,
    # Constants
    PRIMITIVES,
    CONTAINERS,
    FLEXIBLE,
    # Factory functions — primitives
    t_any,
    t_unknown,
    t_null,
    t_int,
    t_float,
    t_string,
    t_boolean,
    # Containers
    t_list,
    t_map,
    t_tuple,
    t_option,
    t_record,
    t_record_kind,
    # Special / control
    t_control,
    t_session,
    t_stream,
    # Numeric tensors
    t_tensor,
    t_vec2,
    t_vec3,
    t_quat,
    t_mat3,
    t_mat4,
    # Image / 2-D detection
    t_image,
    t_mask,
    t_depthmap,
    t_bbox2d,
    t_track2d,
    t_keypoints,
    t_detections2d,
    # 3-D scene
    t_pointcloud,
    t_bbox3d,
    t_track3d,
    t_region3d,
    t_scene3d,
    t_detections3d,
    # Deprecated (Phase-5 removal)
    t_point,
    t_box,
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
    "t_record",
    "t_record_kind",
    "t_control",
    "t_session",
    "t_stream",
    "t_tensor",
    "t_vec2",
    "t_vec3",
    "t_quat",
    "t_mat3",
    "t_mat4",
    "t_image",
    "t_mask",
    "t_depthmap",
    "t_bbox2d",
    "t_track2d",
    "t_keypoints",
    "t_detections2d",
    "t_pointcloud",
    "t_bbox3d",
    "t_track3d",
    "t_region3d",
    "t_scene3d",
    "t_detections3d",
    "t_point",
    "t_box",
]
