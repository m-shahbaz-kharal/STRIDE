# Type System

This document describes the unified port type system used by STRIDE for
validating connections between nodes. The full design rationale and
migration history live in
[`unified-type-system-and-ux.md`](./unified-type-system-and-ux.md);
the canonical taxonomy is **§3.2** there. This file is the practical
reference: what types exist, when they're compatible, and where the
record schemas come from.

## Overview

Every port (input or output) on a node carries a `TypeDescriptor`. The
descriptor combines a *kind* (the visualisation / dispatch category) with
optional *fields* (a structural record schema) and optional
*metadata.subtype* (a non-binding refinement tag).

Connections are validated in two places:

- The frontend's `useConnectionValidation` hook decides whether to allow
  a drag-drop and surfaces "convertible" suggestions when a registered
  `convert.*` node would bridge a mismatch.
- The backend's `GraphBuilder.build()` re-runs the same compatibility
  rule before execution starts so an out-of-band graph (loaded from a
  file, an API call, a saved demo) is still rejected if it's
  ill-typed.

## Type Descriptors

```python
# packages/stride-core/src/stride_core/typesystem.py
@dataclass(frozen=True)
class TypeDescriptor:
    kind: str                                       # e.g. "image", "bbox2d", "list"
    element_type: Optional["TypeDescriptor"] = None # list / option / tuple element
    key_type: Optional["TypeDescriptor"] = None     # map key (always string)
    fields: Optional[Dict[str, "TypeDescriptor"]] = None  # record schema
    nullable: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)  # {"subtype": str, ...}
```

## Canonical taxonomy

The full taxonomy ships in `stride-core`. Plugin packages **must not**
redefine these kinds; they import the factory functions and reuse them.

### Scalars

| Kind | Factory | Wire form |
|---|---|---|
| `int`, `float`, `string`, `boolean`, `null` | `t_int()` etc. | bare value |

### Containers

| Kind | Factory | Wire form |
|---|---|---|
| `list<T>` | `t_list(T)` | JSON array |
| `map<K, V>` | `t_map(K, V)` | JSON object (K = string) |
| `option<T>` | `t_option(T)` | T or `null` |
| `record` | `t_record({...})` | JSON object with fixed schema |
| `tuple` | `t_tuple(...)` | fixed-arity JSON array |

### Domain records (kinds with structural schemas)

These are the records every cross-package wiring depends on. The schema
comes from `stride-core`; field names are stable across the codebase.

| Kind | Factory | Required fields |
|---|---|---|
| `image` | `t_image()` | `_type, width, height, format, data_b64` |
| `mask` | `t_mask()` | `_type, width, height, data_b64, encoding` |
| `depthmap` | `t_depthmap()` | `_type, width, height, depth_b64, min_depth, max_depth, image` |
| `bbox2d` | `t_bbox2d()` | `x1, y1, x2, y2, confidence, class_id, class_name, track_id` |
| `track2d` | `t_track2d()` | `bbox2d` fields plus `track_age, track_score` (track_id non-null) |
| `detections2d` | `t_detections2d()` | `_type, image_width, image_height, boxes: list<bbox2d>, image` |
| `keypoints` | `t_keypoints()` | `_type, instances, schema_name?` |
| `pointcloud` | `t_pointcloud()` | `_type, num_points, positions_b64, fields_b64?, …, frame?` |
| `bbox3d` | `t_bbox3d()` | `id?, center, size, rotation?, velocity?, confidence?, class_id?, class_name?, frame?` |
| `track3d` | `t_track3d()` | `bbox3d` fields plus `track_age, track_score` (id non-null) |
| `region3d` | `t_region3d()` | `name, center, size, rotation?` |
| `detections3d` | `t_detections3d()` | `_type, boxes: list<bbox3d>, scene_metadata?` |
| `scene3d` | `t_scene3d()` | `_type, point_cloud, boxes, regions, occupancy, image_overlays?` |
| `stream` | `t_stream()` | `_type, stream_id, width, height, target_fps, active` |

### Numeric tensors

`tensor` carries optional `metadata.dtype` and `metadata.shape`. The
sugar functions `t_vec2/3()`, `t_quat()`, `t_mat3/4()` produce
fixed-shape float32 tensors.

### Special / control

| Kind | Factory | Use |
|---|---|---|
| `any` | `t_any()` | universal sink |
| `unknown` | `t_unknown()` | universal source |
| `control` | `t_control()` | sequencing-only port (no payload) |
| `session` | `t_session()` | opaque AI-model session handle |

## Subtype refinement

Domain records accept an optional `metadata.subtype` tag that the UI and
visualiser registry consult for dispatch:

- `image` — `"rgb"`, `"grayscale"`, `"data_url"`, `"raw_b64"`, `"url"`,
  `"mono16"`.
- `pointcloud` — `"lidar"`, `"rgbd"`, `"xyz"`, `"xyzi"`, `"xyzrgb"`,
  `"synthetic"`, `"unknown"`.

Subtype acts as a **widening** rule: a more specific source flows into a
less specific (or unspecified) target, never the reverse. A target with
`subtype="any"` accepts every source.

## Compatibility rules

`TypeDescriptor.is_assignable_to(target)` returns True when the
following layered checks pass.

1. `any` / `unknown` on either side accepts everything.
2. A nullable source rejects a non-nullable target.
3. `int` widens to `float` (free).
4. Different kinds reject — except for the `int -> float` rule above,
   the only cross-kind paths are explicit `convert.*` nodes (see
   [Conversion graph](#conversion-graph) below).
5. Same kind, subtype refinement: source's subtype must be more specific
   than or equal to the target's (§3.3).
6. Container kinds (`list`, `map`, `option`) recurse on element types.
7. Record-shaped kinds use **structural subtyping**: every field
   declared on the *target* must be present in the *source* and
   recursively assignable.
8. `tensor` requires matching `dtype` and `shape` whenever both sides
   specify them.

## Conversion graph

The `stride-converters` package houses every `convert.*` node. Each
converter declares `metadata.convert_from` / `metadata.convert_to` /
`metadata.cost` so the frontend can build a lookup table at app start
(see `/api/converters`). When the user attempts an invalid connection
that a converter could bridge, the editor offers a one-click "Insert
&lt;converter&gt;" action.

Current converter inventory (Phase 5 ships ~14 of the ~25 design-doc
candidates):

- `convert.image.from_url` — `string` → `image`
- `convert.image.to_grayscale` — `image` → `image[grayscale]`
- `convert.image.from_grayscale_to_rgb` — `image` → `image[rgb]`
- `convert.detections2d.xyxy_to_xywh` and reverse
- `convert.detections2d.from_pose` — `keypoints` → `detections2d`
- `convert.detections.merge` — two `detections2d` → one (IoU dedup)
- `convert.bbox.crop_image` — `image` + `bbox2d` → `image`
- `convert.depth.to_pointcloud` — `depthmap` → `pointcloud`
- `convert.pointcloud.subsample` — `pointcloud` → `pointcloud`
- `convert.pointcloud.crop_box` — `pointcloud` + `bbox3d` → `pointcloud`
- `convert.list.to_first` / `length` — `list<T>` → `T` / `int`
- `convert.record.get` — `record` + key → field value
- `convert.scalar.float_to_int` (truncate / round / floor / ceil)
- `convert.scalar.int_to_string` and `convert.scalar.float_to_string`
- `convert.sv.detections_to_detections2d` and reverse
  (marshallers for the supervision-pipeline `t_any()` ports in
  `sv_core.py` / `sv_annotators.py`)

### Implicit conversions (no node insertion)

Handled inside `is_assignable_to`:

| From | To |
|---|---|
| `T` | `T` (identity) |
| `T` | `any` / `unknown` |
| `int` | `float` |
| `image[<sub>]` | `image` (refinement → base) |
| `pointcloud[<sub>]` | `pointcloud` |

## Plugin contract

A package contributes types by **importing** the canonical factories
and using them in `NodeSpec` ports. It must **not** redefine the kind
locally — Phase 1 fixed the cases where `stride-people` did so and the
resulting graph wiring failed silently.

If a package needs a new kind (not in `stride-core`), it must:

1. Pick a kind name namespaced by its package (e.g. `stride.foo.frame`).
2. Register a factory function alongside the package's nodes.
3. Document the wire form in the package's README.

The plugin loader rejects duplicate kind registrations.

## Frontend / backend parity

The frontend re-implements the compatibility rules in
`hooks/useConnectionValidation.ts` (`arePortTypesCompatible`). This is
not a duplicate of truth — it's the same rule expressed in TypeScript so
drag-drop validation runs locally without a backend round trip. The
`backend/tests/test_typesystem_assignability.py` and
`frontend/src/hooks/useConnectionValidation.test.ts` suites verify
parity.

## See also

- [`unified-type-system-and-ux.md`](./unified-type-system-and-ux.md) — the original design doc.
- [`overview.md`](./overview.md) — system-level architecture.
- [`execution-engine.md`](./execution-engine.md) — how the executor uses types.
- [`../nodes/authoring-guide.md`](../nodes/authoring-guide.md) — node authoring with the v2 lifecycle.
