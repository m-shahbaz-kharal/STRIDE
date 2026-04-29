# Unified Type System & Connection UX — Design Document

**Status**: proposal
**Audience**: STRIDE core maintainers, package authors, frontend engineers
**Scope**: type system across `stride-core`, all `stride-*` / `liguard-*` packages, the FastAPI runtime in `backend/app`, and the React graph editor in `frontend/`
**Sibling docs**: [overview.md](./overview.md), [execution-engine.md](./execution-engine.md), [type-system.md](./type-system.md)

---

## 1. Executive summary

STRIDE today is a working multi-package node-graph runtime: ~145 registered node types across `backend/app/nodes/` and 14 plugin packages, a topologically-aware streaming executor, and a React-Flow editor with type-coloured ports. The core mechanics work. What does *not* work — and what blocks the project from acting like a Blueprint-grade visual programming tool — is the contract between **types**, **nodes**, and **the UI that has to render them**:

- The Python `TypeDescriptor` taxonomy in `packages/stride-core/src/stride_core/typesystem.py` has *opaque kinds* for every domain payload (`bbox3d`, `detections2d`, `track2d`, `keypoints`, `image`, `depthmap`, …). They carry no schema. Wrong-shape dicts pass validation; right-shape dicts crash deep inside a node.
- Two different packages have already disagreed on what `t_bbox3d()` means: `stride-people` redefines it as a `t_record({...})`, while `stride-core` keeps it as `TypeDescriptor(kind="bbox3d")`. Wiring `people.detect → tracker.kalman3d` would be **rejected** at graph build time today (the architect's prior note that this passes by accident is incorrect — see §2.4).
- A second class of latent break exists: `core.image.load` outputs `t_string()` while `yolo.detect`, `rtdetr.detect`, `clip.embed_image`, and `depth_anything.estimate` declare `t_image()` inputs. Strict type validation rejects this connection. The system continues to work in practice only because the YOLO/CLIP wrappers tolerate base64 strings at runtime — i.e. the *runtime* never sees the *type system's* opinion. Ports across the codebase routinely escape into `t_any()` (see `backend/app/nodes/sv_core.py:71,96,129,135,178`) which silently disables checking.
- The frontend's `TypeKind` union in `frontend/src/types.ts:3-24` predates the AI types. There is no entry for `detections2d`, `detections3d`, `depthmap`, `track2d`, `track3d`, `keypoints`, or `mask`. Their port colours fall through to the grey `any` default in `frontend/src/graph/utils.ts:3-19`. Every AI port looks the same.
- `NodeBase` (`packages/stride-core/src/stride_core/node_base.py:73-124`) has *only* `forward()`. There is no `prepare()`, no `teardown()`, no per-node lifecycle. Every stateful node — `tracker.kalman3d`, `bytetrack`, `people.detect` — uses module-level dicts (`_TRACKERS`, `_TRACKER_STATES`, `_background_models`, `_trackers`) that survive across runs and are only nominally cleaned up by `_cleanup_resources()` in `backend/app/runner.py:197-214`, which targets `ctx.register_resource(...)` registrations and not those dicts.
- Node errors funnel through one bare `except Exception` at `backend/app/executor/node_execution.py:263`. Every failure mode — missing input, missing dependency, GPU OOM, file-not-found, cancellation, type-mismatch — collapses to a single string. The frontend has no way to render *why* a node is red.
- Visualisers exist for exactly two payload kinds: `PointCloud` and `Scene3D` (`frontend/src/components/dashboard/`). Everything else dumps as JSON.

**The shape of the answer.** This document proposes a single coherent revision:

1. A **strengthened type system** where every domain payload has a *schema* (a `t_record(...)` with named fields, dtypes, units, frames), with a `metadata.subtype` refinement mechanism for refinements that are too cheap or too dynamic to encode as separate kinds.
2. A canonical **type taxonomy** owned by `stride-core` so packages cannot diverge by accident. `t_bbox3d`, `t_detections2d`, `t_image`, `t_depthmap` etc. become record schemas, not opaque kinds.
3. A **conversion graph** of zero-cost / cheap / explicit conversions, exposed both as an `is_assignable_to` improvement (transparent identity / refinement / numeric widening) and as a **new `stride-converters` package** for the explicit cases.
4. A **NodeBase v2 contract** with `prepare()` / `forward()` / `teardown()`, typed exceptions (`NodeInputError`, `NodeRuntimeError`, `NodeMissingDependencyError`, `NodeCancelled`, `NodeTypeError`), declarative parameter schemas (constraints, enums, presets, file-path validation), explicit cache-key contract, and per-node resource lifecycle. Migration is incremental — 80 of 145 nodes inherit-for-free.
5. A **five-layer validation pipeline** in the backend (graph load → port wiring → run start → node entry → node exit) emitting structured `error_code` + `error_path` JSON the frontend can render.
6. A **Blueprint-grade connection UX** on the frontend: drag-from-port port highlighting, drop-on-canvas type-filtered context menu, per-type colour + icon, real-time edge invalidation as parameters change, inline node error panels with disclosure.
7. A **visualiser registry** mapping `kind`/`subtype` to React components, with build-time discovery via `stride.visualizer.json` manifests and a Vite plugin. Composition is supported (`image + detections2d` → overlay).
8. An **extensibility & plugin contract** that lets packages contribute types, converters, visualisers, and validation rules without forking core, plus a graph-schema-version field so saved graphs survive type renames.

**Effort.** Phase 0 is reversible groundwork (no behavioural change). Phase 1 is the minimum viable cut — enough to unblock the UX work — and is roughly 1.5 weeks of focused engineering. Phases 2–4 add visualisers, error UI, and converters. Total programme: 4–6 weeks, parallelisable across 3 agents.

**What this is *not*.** This is not a rewrite. The execution engine in `backend/app/runner.py` and `backend/app/executor/` is sound and not in scope here. We do not re-architect topological ordering, control-flow handlers, the cache, or the WebSocket streaming. We replace the *type contract* and the *node contract* and the *frontend rendering contract* — and only those.

---

## 2. Audit & current state

This section is an inventory grounded in real file:line citations. Everything below has been read, not summarised from memory.

### 2.1 Type definitions in `stride-core`

The single source of truth is `packages/stride-core/src/stride_core/typesystem.py`. All factory functions and the constants:

| Group | Factory | Definition site | Kind | Has fields? |
|---|---|---|---|---|
| Scalars | `t_int`, `t_float`, `t_string`, `t_boolean`, `t_null` | `typesystem.py:284-301` | `int`, `float`, `string`, `boolean`, `null` | No |
| Containers | `t_list`, `t_map`, `t_tuple`, `t_option` | `typesystem.py:304-327` | `list`, `map`, `tuple`, `option` | Element types |
| Containers | `t_record` | `typesystem.py:334-335` | `record` | Yes (named) |
| Containers | `t_any`, `t_unknown` | `typesystem.py:276-281` | `any`, `unknown` | No |
| Control | `t_control` | `typesystem.py:330-331` | `control` | No |
| Tensor | `t_tensor` | `typesystem.py:338-339` | `tensor` | metadata only (`dtype`, `shape`) |
| Stream | `t_stream` | `typesystem.py:342-343` | `stream` | No (live `StreamResource` value) |
| AI primitives | `t_point`, `t_box`, `t_mask`, `t_session` | `typesystem.py:350-367` | `point`, `box`, `mask`, `session` | No |
| 3D | `t_pointcloud`, `t_bbox3d`, `t_region3d`, `t_scene3d` | `typesystem.py:370-387` | `pointcloud`, `bbox3d`, `region3d`, `scene3d` | **No** |
| 2D | `t_image`, `t_bbox2d`, `t_detections2d`, `t_depthmap` | `typesystem.py:442-472` | `image`, `record`, `detections2d`, `depthmap` | `bbox2d` *is* a record; everything else is opaque |
| Tracking | `t_track2d`, `t_track3d` | `typesystem.py:475-482` | `track2d`, `track3d` | No |
| Pose | `t_keypoints` | `typesystem.py:485-487` | `keypoints` | No |

The `FLEXIBLE` set at `typesystem.py:15-21` enumerates all opaque kinds. Note that `bbox2d` is special — it is the *only* domain factory that returns an actual `t_record({...})`. Everything else is `TypeDescriptor(kind="<name>")` with no schema. The doc comments at `typesystem.py:393-440` describe the *intended* schema for each kind in prose, but the type system does not enforce it.

### 2.2 Where types are checked at runtime

Type compatibility is checked at exactly one point during graph execution:

```
backend/app/executor/graph_builder.py:142-150

from_type = normalize_type(from_node.output_port_types.get(link.from_port))
to_type = normalize_type(to_node.input_port_types.get(link.to_port))
if isinstance(from_type, TypeDescriptor) and isinstance(to_type, TypeDescriptor):
    if not from_type.is_assignable_to(to_type):
        raise GraphExecutionError(
            f"Type mismatch: {from_node.type}.{link.from_port} ({from_type.label()}) -> "
            f"{to_node.type}.{link.to_port} ({to_type.label()})",
            code="type_mismatch",
        )
```

The check happens once during `GraphBuilder.build()` from `__init__` of `GraphExecutor` (`backend/app/runner.py:81-83`). There is no second check at run-start, no per-frame check during streaming, no shape/schema check at node entry. The `GraphExecutionError` is raised before any node forwards, which is good — but it produces only a string with no structured payload (no path, no expected vs. actual schema).

`is_assignable_to` itself (`typesystem.py:144-192`) handles:

- `any` and `unknown` are universal (lines 146-153).
- `nullable` source cannot flow into non-nullable target (lines 154-155).
- Different kinds with the single exception of `int → float` widening (lines 156-160).
- `list`/`map`/`option` recurse on element type (lines 161-172).
- `record` is **structural subtyping** (lines 173-181): source must have all of target's fields and each compatible.
- `tensor` checks `dtype` and `shape` exactly (lines 182-191).
- Everything else falls through to `return True` at line 192 — but only when `self.kind == target.kind` (line 156 already filtered the rest).

**Implication.** For two opaque kinds `bbox3d → bbox3d`, the check is purely *kind identity*. There is no schema enforcement. So an int `42` passed where a `bbox3d` is expected would type-check fine and crash inside `forward()`.

### 2.3 Frontend connection validation

`frontend/src/hooks/useConnectionValidation.ts:67-105` mirrors the backend check in TypeScript:

- Same `any`/`unknown` universal rule (lines 74-75).
- Same `int → float` widening (line 76).
- Same nullable rule (line 77).
- Recursive on `list`/`map`/`option`/`record` (lines 79-95).
- Tensor dtype check (lines 97-101).
- Default fall-through to `return true` for matching kinds (line 102).

The frontend additionally normalises type descriptors in `normalizeType` (`useConnectionValidation.ts:31-65`). `validateConnection` returns a `{valid, reason, sourceType, targetType}` triple and pushes connection-line colour through `setConnectionLineColor` (lines 259, 305). It does **not**:

- Suggest auto-cast / converter insertions.
- Highlight compatible target ports across the canvas while a drag is in progress.
- Surface a context-menu of nodes filtered by what the dragged source can produce.
- Re-validate links when a node's parameter changes (e.g. when a `Cast` node toggles output type).

The connection-line colour comes from `getPortTypeColor` in `frontend/src/graph/utils.ts:67-70`, which looks up `PORT_TYPE_COLORS` (`utils.ts:3-19`). Only 14 kinds are mapped: `int`, `float`, `number`, `image`, `stream`, `url`, `boolean`, `string`, `any`, `unknown`, `list`, `map`, `record`, `tensor`, `control`. Notably absent: `pointcloud`, `bbox3d`, `bbox2d`, `detections2d`, `detections3d`, `depthmap`, `track2d`, `track3d`, `keypoints`, `mask`, `region3d`, `scene3d`, `point`, `box`, `session`. They all silently fall back to the grey `#94a3b8` `any` colour.

The TypeKind union in `frontend/src/types.ts:3-24` lists exactly 20 kinds — the four scalars, `null`, `control`, `image`, `stream`, `url`, `any`, `unknown`, the five containers (including `tuple`), `tensor`, `pointcloud`, `bbox3d`, `region3d`, `scene3d`. Eleven backend kinds are missing from this enum. TypeScript will not catch their absence because backend kinds arrive as JSON strings and are cast to `TypeKind` at the boundary (e.g. `frontend/src/types.ts:226` `kind: TypeKind` on `PublishedPortData`).

### 2.4 Concrete divergences between packages

#### Divergence A — `t_bbox3d` redefined locally

`packages/stride-people/src/stride_people/nodes.py:39-65` redefines all three 3D types as records:

```python
def t_bbox3d():
    """3D bounding box: center, size, id, optional velocity."""
    return t_record({
        "id": t_int(),
        "center": t_list(t_float()),  # [x, y, z]
        "size": t_list(t_float()),    # [w, h, d]
    })


def t_region3d():
    """Occupancy region: center, size, name."""
    return t_record({
        "name": t_string(),
        "center": t_list(t_float()),
        "size": t_list(t_float()),
    })


def t_scene3d():
    """Combined scene for visualization."""
    return t_record({...})
```

Meanwhile `packages/stride-core/src/stride_core/typesystem.py:375-387` defines them as opaque kinds:

```python
def t_bbox3d() -> TypeDescriptor:
    """A 3D bounding box (center, size, id)."""
    return TypeDescriptor(kind="bbox3d")
```

`stride-kalman` imports the core version (`packages/stride-kalman/src/stride_kalman/nodes.py:28-31`):

```python
from stride_core.typesystem import (
    t_boolean, t_control, t_float, t_int, t_list,
    t_bbox3d, t_detections3d,
)
```

**Tracing `is_assignable_to` for `people.detect.detections (list<record>) → tracker.kalman3d.boxes (list<bbox3d>)`:**

1. Outer kinds match (`list` == `list`) — line 161.
2. Recurse on element types.
3. Element source `kind="record"`, target `kind="bbox3d"`.
4. Line 156: `record != bbox3d`, neither is `int → float` widening, returns **False**.
5. Line 145 in `graph_builder.py` raises `GraphExecutionError(code="type_mismatch")`.

**Correction to the prior architect's finding.** The prior note that this connection "currently passes only because `is_assignable_to()` falls through for non-container kinds at line ~192" is wrong. Line 192 is reached only when the kinds *match* (filtered at line 156). With non-matching kinds, line 156 returns `False` first. So `people.detect → kalman3d` is *currently rejected at graph build time*. The bug is "you cannot wire these together" — not "they wire together accidentally and produce nonsense at runtime". The user-visible symptom is a graph-build error, not a silent crash.

#### Divergence B — `image` is sometimes `t_string`, sometimes `t_image`

| Producer / Consumer | Port | Type declared | File:line |
|---|---|---|---|
| `core.image.load` (output) | `image` | `t_string()` | `backend/app/nodes/image_nodes.py:34` |
| `core.image.save` (input) | `image` | `t_string().with_nullable(True)` | `backend/app/nodes/image_nodes.py:96` |
| `yolo.detect` (input) | `image` | `t_image()` | `packages/stride-yolo/src/stride_yolo/nodes.py:127` |
| `yolo.detect` (output) | `image` | `t_image()` | `packages/stride-yolo/src/stride_yolo/nodes.py:146` |
| `rtdetr.detect` (input) | `image` | `t_image()` | `packages/stride-rtdetr/src/stride_rtdetr/nodes.py:89` |
| `clip.embed_image` (input) | `image` | `t_image()` | `packages/stride-clip/src/stride_clip/nodes.py:108,204` |
| `depth_anything.estimate` (input) | `image` | `t_image()` | `packages/stride-depth-anything/src/stride_depth_anything/nodes.py:102` |
| `bytetrack` (input) | `image` | `t_image()` | `packages/stride-bytetrack/src/stride_bytetrack/nodes.py:74` |
| `sv.image_to_b64`, `sv.b64_to_image` | `image` | `t_any()` | `backend/app/nodes/sv_core.py:71,96` |

Strict type-checking rejects `core.image.load.image (string) → yolo.detect.image (image)`. The reason production demos work is that `sv_core.py` interposes `t_any()`-typed adapters, or because users wire `t_string` outputs into `t_any` inputs in supervision-style nodes. There is no documented convention that `image` *is* a base64 string at the wire level; the `typesystem.py` doc comment at lines 393-444 *says* "an image is a base64-encoded data URL string", but the type system doesn't reflect that.

#### Divergence C — `bbox2d` schema differs from `Detections2D` field

`t_bbox2d()` (`typesystem.py:447-457`) is a `t_record` with fields `x1, y1, x2, y2, confidence, class_id, class_name`. The doc comment at `typesystem.py:404-410` adds an optional `track_id`. But `track_id` is not in the schema, so a downstream node that expects `bbox2d` and reads `box["track_id"]` will succeed at type-check but `KeyError` at runtime if upstream did not add it (e.g. before tracking).

#### Divergence D — `t_stream` carries an unserialisable value

`t_stream()` (`typesystem.py:342-343`) is opaque kind `stream`. The wire value at runtime is a live `StreamResource` instance (`packages/stride-fl511/src/stride_fl511/nodes.py:134-403`). The class implements `to_dict()` (`nodes.py:394-403`) which intentionally drops the `_proc`, `_thread`, `_queue`, etc. — only `stream_id` and dimensions survive.

`backend/app/main.py:45-52` defines:

```python
def _json_serializer(obj: Any) -> Any:
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if hasattr(obj, "dtype"):
        return obj.tolist()
    return str(obj)
```

This is invoked at lines 95, 112, 129, 241, 299. So when an execution result containing a `StreamResource` is serialised over HTTP/WS, the live handle is silently replaced by the dict-form. This is *currently latent* because streams stay in-process — `tracker.kalman3d`, etc. consume `t_stream` only via in-memory references — but the moment we add a "save graph state" or "remote worker" feature it breaks.

### 2.5 NodeBase has no lifecycle

`packages/stride-core/src/stride_core/node_base.py:73-124` defines exactly one abstract method on `NodeBase`:

```python
class NodeBase(abc.ABC):
    @abc.abstractmethod
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        ...
```

No `prepare()`. No `teardown()`. Stateful nodes work around this with **module-level dicts keyed by `self.id`**:

| Package | File | Globals |
|---|---|---|
| `stride-bytetrack` | `nodes.py:46` | `_TRACKERS: Dict[str, Any] = {}` |
| `stride-kalman` | `nodes.py:130` | `_TRACKER_STATES: Dict[str, Dict[str, Any]] = {}` |
| `stride-people` | `nodes.py:473-474` | `_background_models`, `_trackers` |
| `stride-fl511` | `nodes.py:127` | `ACTIVE_STREAMS: Dict[str, "StreamResource"] = {}` |

These dicts persist across runs. They are cleared only by passing `reset=True` as an input on the next forward (`bytetrack/nodes.py:140`, `kalman/nodes.py:158`, `people/nodes.py:514`). If the user deletes the node and re-creates it with the same auto-generated id, state can leak. If the node is interrupted mid-forward, no cleanup runs. The `_cleanup_resources` path (`backend/app/runner.py:197-214`) only closes resources registered via `ctx.register_resource(...)` — module dicts are invisible to it.

`ExecutionContext` (`node_base.py:16-70`) does provide `register_resource`, `register_subprocess`, and a `check_cancelled` callback, but these are advisory — they handle subprocess lifecycle, not Python-level state.

### 2.6 Node errors collapse to a single string

`backend/app/executor/node_execution.py:197-280` has the only place that catches node-execution exceptions:

```python
def execute_node_work(self, node_id: str, inputs: Dict[str, Any]) -> "NodeExecutionResult":
    ...
    try:
        ctx = ExecutionContext()
        ...
        outputs = node.forward(inputs, ctx)
        ...
        return NodeExecutionResult(... status=NodeStatus.COMPLETED ...)

    except Exception as e:
        import traceback
        end_time = time.perf_counter()
        error_traceback = traceback.format_exc()
        return NodeExecutionResult(
            node_id=node_id,
            node_type=node.type,
            status=NodeStatus.ERROR,
            ...
            error=str(e),
            error_code=getattr(e, "code", None),
            error_details=error_traceback,
            ...
        )
```

The catch is at line 263. It pulls `error_code` only if the exception happens to have a `.code` attribute (which only `GraphExecutionError` does). Distinct failure modes — bad input, missing dep, GPU OOM, file-not-found, KeyError, IndexError — all produce the same shape: one stringified message and a stacktrace. The frontend has no way to distinguish "your input was malformed" from "this node tried to import torch and torch isn't installed" from "the file path doesn't exist". All three are red.

### 2.7 Visualiser coverage

`frontend/src/components/dashboard/DashboardWidgetContent.tsx:97-119` is the entire visualiser dispatch:

```typescript
case "bound-output":
    if (typeof value === "string" && (value.startsWith("data:image") || value.startsWith("http"))) {
        return <img ... />;
    } else if (value && typeof value === 'object' && (value as any)._type === 'StreamResource') {
        return <img src={`/api/streams/${stream.stream_id}/frame?ts=${Date.now()}`} ... />;
    } else if (value && typeof value === 'object' && (value as any)._type === 'Scene3D') {
        return <Scene3DWidget data={value as any} />;
    } else if (value && typeof value === 'object' && (value as any)._type === 'PointCloud') {
        return <PointCloudWidget data={value as any} />;
    }
    return (
        <div ... >
            {value !== undefined ? (typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)) : <span>No Data</span>}
        </div>
    );
```

Five branches, all hand-coded:

| Payload shape | Visualiser | File |
|---|---|---|
| `string` starting `data:image` or `http` | `<img>` | inline |
| object with `_type === "StreamResource"` | `<img>` polling `/api/streams/.../frame` | inline |
| object with `_type === "Scene3D"` | `Scene3DWidget` | `frontend/src/components/dashboard/Scene3DWidget.tsx` |
| object with `_type === "PointCloud"` | `PointCloudWidget` | `frontend/src/components/dashboard/PointCloudWidget.tsx` |
| anything else | `JSON.stringify` in a monospace block | inline |

So `detections2d`, `track2d`, `keypoints`, `depthmap`, `bbox2d`, `bbox3d` (the bare ones), `region3d` — all of them, when wired to a dashboard, show as JSON.

The visualiser branch is keyed on the *value's* `_type` property, not on the *port's* type descriptor. The `widget.inputType` field of `DashboardWidget` (`frontend/src/types.ts:256`) carries a `TypeKind` but is only used for `bound-input` widgets to choose a numeric vs. text input. The `bound-output` widget ignores its port type completely.

### 2.8 Where `t_any` is currently used as an escape hatch

A non-exhaustive count from `backend/app/nodes/sv_core.py`:

- `image` output of `b64_to_image_node`: `t_any()` (line 71) — should be `t_image`.
- `image` input of `image_to_b64_node`: `t_any()` (line 96) — should be `t_image`.
- `xyxy`, `confidence`, `class_id` inputs: `t_any()` (lines 129-131) — should be tensors with shape constraints.
- `detections` input/output: `t_any()` (lines 135, 172, 178) — should be `t_detections2d`.

Each `t_any()` is a place where the type system is silently disabled. There are dozens of these across the codebase. They are not documented as escape hatches — they are mistakes that nobody fixed because the runtime kept working.

### 2.9 Saved-graph schema

Saved graphs are JSON blobs persisted via `backend/app/routers/graphs_router.py` (and consumed via `frontend/src/api/`). There is currently no `schema_version` field on the graph payload, no migration step, and no compatibility shim. If we rename `t_bbox3d` from opaque-kind to record-schema, every saved graph that uses that port will fail to load. We must address this.

### 2.10 Summary of bugs / gaps

| # | Bug | Severity | Evidence |
|---|---|---|---|
| 1 | `t_bbox3d` redefined locally in `stride-people` as record while `stride-core` keeps it opaque; cross-package wiring rejected | High (blocks compositions) | `packages/stride-people/src/stride_people/nodes.py:39-65` vs `typesystem.py:375-377` |
| 2 | `core.image.load` outputs `t_string` while consumer nodes expect `t_image`; rejected by validator | High | `image_nodes.py:34` vs `yolo/nodes.py:127` |
| 3 | `bbox2d` schema lacks `track_id` despite docs referencing it | Medium | `typesystem.py:447-457` vs `typesystem.py:404-410` |
| 4 | `t_stream` value is an unserialisable live object; `to_dict()` drops the live handle silently | Medium (latent until persistence/RPC) | `main.py:45-52`, `fl511/nodes.py:394-403` |
| 5 | NodeBase has no `prepare`/`teardown`; state lives in module dicts; cleanup is best-effort | High (memory & state leaks) | `node_base.py:73-124`, `_TRACKERS`, `_TRACKER_STATES`, `_background_models` |
| 6 | Single bare `except Exception` collapses error semantics | High (UX) | `node_execution.py:263` |
| 7 | Frontend `TypeKind` union missing 11 AI types; all render grey | Medium (UX) | `frontend/src/types.ts:3-24`, `graph/utils.ts:3-19` |
| 8 | `useConnectionValidation` lacks port highlighting, type-filtered context menu, auto-cast suggestions | Medium (UX) | `useConnectionValidation.ts:67-105` |
| 9 | Visualisers exist only for PointCloud, Scene3D, Image, Stream; everything else dumps JSON | Medium (UX) | `DashboardWidgetContent.tsx:97-119` |
| 10 | `t_any()` is widely used as silent escape hatch | Medium (correctness) | `sv_core.py` and others |
| 11 | No `schema_version` on saved graphs | Medium (compat risk) | `routers/graphs_router.py` |

---

## 3. Target type system

This section is normative.

### 3.1 Core principle: kinds are *categories*, schemas are records

We keep `TypeDescriptor` and the `kind` field. We change what `kind` means:

- `kind` is a **category label**. It identifies the *family* of payloads ("this is a 2-D detection bundle"). It does **not** carry the schema.
- For domain payloads, the schema is encoded as a `t_record(...)` whose fields are the canonical wire shape. The schema lives in `stride-core` so packages cannot redefine it.

A domain type factory has the form:

```python
# stride-core/src/stride_core/typesystem.py

def t_bbox3d() -> TypeDescriptor:
    """3-D bounding box. Frame: world; units: metres."""
    return t_record_kind(
        kind="bbox3d",
        fields={
            "id":         t_int(),
            "center":     t_vec3(),                                     # list<float> length 3
            "size":       t_vec3(),
            "rotation":   t_quat().with_nullable(True),                 # optional
            "velocity":   t_vec3().with_nullable(True),                 # optional
            "confidence": t_float().with_nullable(True),
            "class_id":   t_int().with_nullable(True),
            "class_name": t_string().with_nullable(True),
        },
    )
```

`t_record_kind` is a new factory:

```python
def t_record_kind(kind: str, fields: Dict[str, TypeDescriptor]) -> TypeDescriptor:
    """Record with a non-default kind tag.

    Used for domain payloads that want both a category label AND a schema.
    `kind` is used for category-identity (colour, icon, visualiser dispatch).
    `fields` is used for structural-subtyping checks.
    """
    return TypeDescriptor(kind=kind, fields=fields)
```

`is_assignable_to` is extended to handle the `kind != "record"` && `fields is not None` case the same way as `kind == "record"` — i.e. structural subtyping on fields, and kind-equal *or* refinement (see §3.4). This is the only behavioural change to the matcher.

### 3.2 Canonical taxonomy

The full canonical taxonomy lives in `stride-core/src/stride_core/typesystem.py`. Below is the proposed final shape. Every kind has either *primitive* meaning (no fields) or a *record schema*. Frame and units are documented in field descriptions.

#### 3.2.1 Scalars (unchanged)

| Factory | Kind | Notes |
|---|---|---|
| `t_int()` | `int` | 64-bit signed |
| `t_float()` | `float` | IEEE-754 double |
| `t_string()` | `string` | UTF-8 |
| `t_boolean()` | `boolean` | |
| `t_null()` | `null` | only in `option` |

#### 3.2.2 Containers (unchanged)

| Factory | Kind | Notes |
|---|---|---|
| `t_list(T)` | `list` | ordered |
| `t_map(K, V)` | `map` | string keys preferred |
| `t_tuple(T1, T2, ...)` | `tuple` | fixed arity |
| `t_option(T)` | `option` | nullable T |
| `t_record({k: T, ...})` | `record` | named fields |

#### 3.2.3 Numeric tensors

| Factory | Kind | Schema |
|---|---|---|
| `t_tensor(dtype, shape)` | `tensor` | metadata: `{dtype, shape}` |
| `t_vec2()` | `tensor` | `{dtype: "float32", shape: [2]}` |
| `t_vec3()` | `tensor` | `{dtype: "float32", shape: [3]}` |
| `t_quat()` | `tensor` | `{dtype: "float32", shape: [4]}` |
| `t_mat3()` | `tensor` | `{dtype: "float32", shape: [3, 3]}` |
| `t_mat4()` | `tensor` | `{dtype: "float32", shape: [4, 4]}` |

Tensor compatibility uses metadata-based shape and dtype matching as it does today (`typesystem.py:182-191`). The new shape-aliases above are sugar — they decompose to plain `t_tensor()`.

#### 3.2.4 Image / pixel-grid types

| Factory | Kind | Schema | Wire form |
|---|---|---|---|
| `t_image()` | `image` (record) | `{width: int, height: int, format: string, data_b64: string}` | JSON record |
| `t_image_url()` | `image` with `metadata.subtype="url"` | same as above; `data_b64` is the data-URL prefix-and-payload | JSON record |
| `t_mask()` | `mask` (record) | `{width: int, height: int, data_b64: string, encoding: string}` | JSON record |
| `t_depthmap()` | `depthmap` (record) | `{width: int, height: int, depth_b64: string, min_depth: float, max_depth: float, image: t_image().with_nullable(True)}` | JSON record |

Migration of `core.image.load`: change its `image` output from `t_string()` to `t_image()`, and have it produce a record `{width, height, format, data_b64}` rather than a raw data-URL string. Existing nodes that read the string form become an explicit `convert.image.from_data_url` call in saved graphs (see Phase 1 migration).

For *backwards compatibility during the transition*, a `t_image_legacy()` alias = `t_string()` exists and is documented as deprecated.

#### 3.2.5 2-D detection / tracking

| Factory | Kind | Schema |
|---|---|---|
| `t_bbox2d()` | `bbox2d` (record) | `{x1: float, y1: float, x2: float, y2: float, confidence: float, class_id: int, class_name: string, track_id: int (nullable)}` |
| `t_keypoint2d()` | `keypoint2d` (record) | `{x: float, y: float, score: float, visible: boolean (nullable)}` |
| `t_keypoints()` | `keypoints` (record) | `{instances: list<{keypoints: list<keypoint2d>, bbox: bbox2d (nullable)}>, schema_name: string (nullable)}` |
| `t_detections2d()` | `detections2d` (record) | `{image_width: int, image_height: int, boxes: list<bbox2d>, image: t_image (nullable)}` |
| `t_track2d()` | `track2d` (record) | extends `bbox2d`; `track_id` non-nullable, adds `track_age: int, track_score: float` |

Note: a `bbox2d` *with* a non-null `track_id` is structurally a `track2d`. `is_assignable_to` performs structural subtyping so `track2d → bbox2d` flows freely (track2d has all of bbox2d's fields). `bbox2d → track2d` does **not** flow, because `track2d` requires non-null `track_id`. This is exactly the right semantic.

#### 3.2.6 3-D detection / tracking / scene

| Factory | Kind | Schema |
|---|---|---|
| `t_pointcloud()` | `pointcloud` (record) | `{num_points: int, positions_b64: string, fields_b64: map<string, string> (nullable), positions: list<vec3> (nullable, fallback path), fields: map<string, list<float>> (nullable), frame: string ("world", "sensor", "ego")}` |
| `t_bbox3d()` | `bbox3d` (record) | `{id: int, center: vec3, size: vec3, rotation: quat (nullable), velocity: vec3 (nullable), confidence: float (nullable), class_id: int (nullable), class_name: string (nullable), frame: string}` |
| `t_track3d()` | `track3d` (record) | extends `bbox3d`; non-nullable `id`, adds `track_age, track_score` |
| `t_region3d()` | `region3d` (record) | `{name: string, center: vec3, size: vec3, rotation: quat (nullable)}` |
| `t_detections3d()` | `detections3d` (record) | `{boxes: list<bbox3d>, scene_metadata: map<string, any> (nullable)}` |
| `t_scene3d()` | `scene3d` (record) | `{point_cloud: pointcloud, boxes: list<bbox3d>, regions: list<region3d>, occupancy: list<int>, image_overlays: list<image> (nullable)}` |

#### 3.2.7 Special / control / resource

| Factory | Kind | Notes |
|---|---|---|
| `t_control()` | `control` | sequencing only; no value carried |
| `t_stream()` | `stream` (record) | `{_type: "StreamResource", stream_id: string, width: int, height: int, target_fps: int, active: boolean}` — the wire form. Live handle stays in-process via `ACTIVE_STREAMS` registry. See §3.7. |
| `t_session()` | `session` | opaque resource handle (e.g. AI model session); not serialisable |
| `t_any()`, `t_unknown()` | `any`, `unknown` | escape hatches; deprecated where a real type is known |

### 3.3 Subtype refinement via `metadata.subtype`

Some refinements are *too cheap* to deserve their own kind:

- `image` with `subtype="url"` vs. `subtype="data_url"` vs. `subtype="raw_b64"`.
- `pointcloud` with `subtype="lidar"` vs. `subtype="rgbd"` vs. `subtype="synthetic"`.
- `string` with `subtype="path"` (denoting a file path).
- `int` with `subtype="port"` (TCP port; integer 1..65535).

We adopt the convention that `metadata.subtype` is a **non-binding refinement string**:

- It does **not** affect type compatibility. `string subtype="path"` still flows freely into `string` and vice versa.
- It **does** affect UI rendering. The frontend can show a file picker for `subtype="path"`, a numeric stepper for `subtype="port"`.
- It **does** affect visualiser dispatch. A `pointcloud subtype="lidar"` may use a different colour ramp than `subtype="rgbd"`.
- It **does** propagate through implicit conversions. A converter that takes `image` produces `image` with the same `subtype` if not explicitly overridden.

`metadata.subtype` is already supported by `TypeDescriptor.metadata` (`typesystem.py:38`) and survives `to_dict`/`from_dict`. We simply formalise the convention.

### 3.4 Generics for `list<T>` and `map<K, V>`

Generics already work via `t_list(element_type)` and `t_map(key_type, value_type)`, with structural recursion at `typesystem.py:161-168`. We make two small additions:

- `t_list(t_any())` is treated as a wildcard list (assignable both ways with any other list).
- A new helper `t_list_of(*kinds)` creates a `list` whose element accepts a *union* of kinds: `t_list_of("bbox2d", "track2d")`. Internally this is sugar for an `Any`-typed list with metadata `{accepts: ["bbox2d", "track2d"]}` — `is_assignable_to` checks `metadata.accepts` if present.

Beyond these, no full Hindley-Milner is required. A `Cast` node is the explicit escape hatch for cases generics can't express.

### 3.5 Colour / icon assignment

Frontend `PORT_TYPE_COLORS` (`frontend/src/graph/utils.ts:3-19`) is extended:

| Kind | Colour | Icon | Rationale |
|---|---|---|---|
| `int` | `#4a9eff` | `hash` | unchanged |
| `float` | `#60a5fa` | `decimal` | unchanged |
| `boolean` | `#f59e0b` | `toggle` | unchanged |
| `string` | `#10b981` | `text` | unchanged |
| `any` | `#94a3b8` | `circle` | unchanged grey |
| `unknown` | `#cbd5e1` | `help-circle` | unchanged grey |
| `control` | `#f97316` | `play` | unchanged orange |
| `list` | `#7dd3fc` | `list` | unchanged |
| `map` | `#facc15` | `key` | unchanged |
| `record` | `#a855f7` | `box` | unchanged |
| `tensor` | `#22d3ee` | `grid` | unchanged |
| `stream` | `#0fb5a9` | `radio` | unchanged |
| `image` | `#e85aad` | `image` | (new in `image` shorthand sense; was already used) |
| `mask` | `#f472b6` | `mask` | sibling colour to image |
| `depthmap` | `#14b8a6` | `layers` | depth = teal |
| `bbox2d` | `#fb7185` | `rectangle` | warm |
| `track2d` | `#f43f5e` | `target` | sibling of bbox2d, more saturated |
| `keypoints` | `#facc15` | `dot-circle` | yellow (re-use map yellow OK; map is rare in 2-D pipelines) |
| `detections2d` | `#ef4444` | `crosshair` | aggregate bundle = red |
| `pointcloud` | `#8b5cf6` | `cloud` | violet (LiDAR convention) |
| `bbox3d` | `#a78bfa` | `cube` | sibling of pointcloud |
| `track3d` | `#7c3aed` | `cube-rotate` | sibling of bbox3d, deeper |
| `region3d` | `#ec4899` | `region` | pink, distinct from bbox3d |
| `scene3d` | `#6366f1` | `box-3d` | indigo |
| `detections3d` | `#dc2626` | `target-3d` | aggregate red, deeper than detections2d |
| `session` | `#64748b` | `link` | neutral resource |

Colours come from Tailwind's `*-400`/`*-500` palette to stay consistent with the existing UI. Icons are `lucide-react` names so they are tree-shakable.

### 3.6 Stream type wire form

`t_stream()` becomes a record with kind `stream`. Live handle stays in-process via the existing `ACTIVE_STREAMS` registry (`packages/stride-fl511/src/stride_fl511/nodes.py:127`). The wire form contains only what the frontend needs to render:

```python
def t_stream() -> TypeDescriptor:
    return t_record_kind("stream", {
        "_type":      t_string(),       # always "StreamResource"
        "stream_id":  t_string(),
        "width":      t_int(),
        "height":     t_int(),
        "target_fps": t_int(),
        "active":     t_boolean(),
    })
```

This *is* the dict that `StreamResource.to_dict()` already produces (`stride-fl511/src/stride_fl511/nodes.py:394-403`). We are just teaching the type system what's on the wire. The cross-process re-attachment problem (§11) is acknowledged but deferred — for now, streams must stay in-process, and we add an explicit assertion to that effect.

### 3.7 Migration of legacy graph payloads

Saved graphs gain a `schema_version` field (string semver). The graphs router (`backend/app/routers/graphs_router.py`) gains a `migrate(graph)` step on load that walks the version chain. For the 1.0 → 1.1 step this means:

- Rewrite any port type literally `{"kind": "string"}` on `core.image.load.image` to `{"kind": "image"}`.
- Rewrite any port type literally `{"kind": "bbox3d"}` referencing the old opaque form to the new record form (the kind tag is the same, but field structure is now expected).
- For now, rewrites are pure JSON transforms; no runtime data migration is needed because port types are recomputed from each node's spec on graph build (`backend/app/executor/graph_builder.py:142-143`).

The migration table is centralised in `backend/app/domain/graph_migrations.py` (new file). Each migration is a `(from_version, to_version, transform)` tuple. See §6.4 for the full migration story.

---

## 4. Type conversion graph

### 4.1 Three classes of conversion

| Class | Cost | UX | Implementation |
|---|---|---|---|
| **Implicit** | zero | invisible | `is_assignable_to` returns `True`; no node inserted |
| **Suggested** | cheap | one-click "auto-convert" suggestion in the UI | `useConnectionValidation` returns `{valid: false, suggestion: <converter_node_type>}`; user accepts to insert |
| **Explicit** | non-trivial | user must add a `convert.*` node | rejected by `is_assignable_to`; no auto-suggestion |

### 4.2 Implicit conversions (free)

| From | To | Rule |
|---|---|---|
| `T` | `T` | identity |
| `T` | `any` / `unknown` | universal target |
| `any` / `unknown` | `T` | universal source |
| `T` | `option<T>` | wrap in option (already supported via nullability) |
| `int` | `float` | numeric widening (already at `typesystem.py:158`) |
| `track2d` | `bbox2d` | structural subtyping (track2d has all bbox2d fields) |
| `track3d` | `bbox3d` | structural subtyping |
| `image subtype="url"` | `image` | refinement-to-base |
| `pointcloud subtype="lidar"` | `pointcloud` | refinement-to-base |
| `T` | `T` (different `metadata.subtype`) | refinements don't gate flow (§3.3) |

These are handled by `is_assignable_to` and are invisible.

### 4.3 Suggested conversions (one-click)

| From | To | Suggested converter |
|---|---|---|
| `string subtype="path"` | `image` | `convert.image.load_path` |
| `string` (raw URL or data URL) | `image` | `convert.image.from_data_url` |
| `image` | `string subtype="data_url"` | `convert.image.to_data_url` |
| `bbox2d` | `track2d` | `tracker.bytetrack` (full tracker) — *suggestion is "you need a tracker"* |
| `list<bbox2d>` | `detections2d` | `convert.detections2d.from_boxes` (requires image_width/height) |
| `detections2d` | `list<bbox2d>` | `convert.detections2d.unpack_boxes` |
| `list<bbox3d>` | `detections3d` | `convert.detections3d.from_boxes` |
| `pointcloud` (sensor frame) | `pointcloud` (world frame) | `convert.pointcloud.transform` |
| `tensor[H,W,3] float32` | `image` | `convert.image.from_tensor` |
| `image` | `tensor[H,W,3] float32` | `convert.image.to_tensor` |
| `depthmap` | `pointcloud` | `convert.depth.to_pointcloud` (requires intrinsics) |
| `mask` | `bbox2d` | `convert.mask.bounding_box` |

### 4.4 Explicit conversions (manual node insertion)

Conversions that are lossy, expensive, or ambiguous require an explicit node. Examples:

- `pointcloud → image` — requires projection matrix.
- `image → mask` — requires segmentation model.
- `string → int` (parsing) — see existing `core.cast.*` family in `backend/app/nodes/casting.py`.
- `string → bbox2d` (regex / JSON parsing) — explicit `convert.parse.bbox2d_json`.

### 4.5 The `stride-converters` package

A new package at `packages/stride-converters/` housing every `convert.*` node. Module layout:

```
packages/stride-converters/
├── pyproject.toml
└── src/
    └── stride_converters/
        ├── __init__.py            # register()
        ├── image_converters.py
        ├── pointcloud_converters.py
        ├── detection_converters.py
        ├── tensor_converters.py
        └── parse_converters.py
```

Initial node inventory (~25 nodes):

| Node type | From | To | Required params |
|---|---|---|---|
| `convert.image.from_data_url` | `string` | `image` | — |
| `convert.image.to_data_url` | `image` | `string` | `format` (jpeg/png) |
| `convert.image.load_path` | `string subtype="path"` | `image` | — |
| `convert.image.from_tensor` | `tensor` | `image` | `format` |
| `convert.image.to_tensor` | `image` | `tensor` | `dtype`, `layout` |
| `convert.image.resize` | `image` | `image` | `width`, `height`, `mode` |
| `convert.image.crop` | `image` + `bbox2d` | `image` | — |
| `convert.detections2d.from_boxes` | `list<bbox2d>` + `image` | `detections2d` | — |
| `convert.detections2d.unpack_boxes` | `detections2d` | `list<bbox2d>` | — |
| `convert.detections2d.filter` | `detections2d` | `detections2d` | `min_confidence`, `class_ids` |
| `convert.detections3d.from_boxes` | `list<bbox3d>` | `detections3d` | — |
| `convert.detections3d.unpack_boxes` | `detections3d` | `list<bbox3d>` | — |
| `convert.bbox.2d_to_track2d` | `bbox2d` + `int` (track_id) | `track2d` | — |
| `convert.bbox.3d_to_track3d` | `bbox3d` + `int` (track_id) | `track3d` | — |
| `convert.pointcloud.transform` | `pointcloud` | `pointcloud` | `mat4` (transform) |
| `convert.pointcloud.from_arrays` | `tensor` (positions) + `tensor` (fields) | `pointcloud` | — |
| `convert.pointcloud.to_arrays` | `pointcloud` | `tensor`, `map<string, tensor>` | — |
| `convert.depth.to_pointcloud` | `depthmap` + `mat3` (intrinsics) | `pointcloud` | — |
| `convert.depth.colormap` | `depthmap` | `image` | `colormap` |
| `convert.mask.bounding_box` | `mask` | `bbox2d` | — |
| `convert.mask.to_image` | `mask` | `image` | `colormap` |
| `convert.tensor.cast` | `tensor` | `tensor` | `dtype` |
| `convert.tensor.reshape` | `tensor` | `tensor` | `shape` |
| `convert.parse.bbox2d_json` | `string` | `bbox2d` | — |
| `convert.parse.json` | `string` | `any` | `path` (JSONPath) |

Each converter's NodeSpec must include:

```python
NodeSpec(
    type="convert.<name>",
    category="Convert",
    tags=["convert", "<from-kind>", "<to-kind>"],
    cache_policy="auto",        # most converters are pure
    metadata={
        "convert_from": "<from-kind>",
        "convert_to":   "<to-kind>",
        "implicit":     False,  # True for free conversions
        "suggested":    True,   # True if frontend should one-click suggest
    },
)
```

The `metadata.convert_from`/`convert_to` fields are the indexing key the frontend uses to populate the suggestion list (§4.6).

### 4.6 Conversion-cost metric

Each converter declares an integer `metadata.cost` in `1..10`:

- `1`: pure metadata change (e.g. `bbox2d → track2d` with a known id).
- `2-3`: small CPU work (resize, format change).
- `4-6`: meaningful CPU work or I/O (path load, JSON parse).
- `7-9`: expensive or model-driven (image → mask via segmentation).
- `10`: requires explicit user intent (no auto-suggestion).

The frontend uses cost to rank suggestions: when multiple converters could bridge a connection, suggest the cheapest.

Cost is *advisory*; not enforced by the runtime.

### 4.7 Discovery

The frontend discovers converters via `/api/node-definitions` (already exists at `backend/app/main.py:81-84`). It builds an in-memory index `Map<from_kind, Map<to_kind, ConverterSpec[]>>` at app load. When the user attempts an invalid connection, the index is queried by `(source.kind, target.kind)`.

---

## 5. NodeBase strengthening

This section is the heaviest single change. It is also where the most legacy nodes touch.

### 5.1 New NodeBase contract

```python
# packages/stride-core/src/stride_core/node_base.py

class NodeBase(abc.ABC):
    spec: "NodeSpec"

    def __init__(self, config: Dict[str, Any], spec: Optional["NodeSpec"] = None) -> None:
        ...   # unchanged

    # New lifecycle

    def prepare(self, ctx: ExecutionContext) -> None:
        """Called once per execution run, before the first forward.

        Subclasses that need stateful resources (model weights, sockets,
        background threads, voxel models) should allocate them here.
        Default no-op so existing nodes inherit-for-free.
        """
        pass

    @abc.abstractmethod
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        """Pure-ish data transform. Should NOT allocate per-call resources;
        instead, allocate in `prepare()` and reuse here.
        """
        ...

    def teardown(self, ctx: ExecutionContext) -> None:
        """Called once per execution run, after the last forward (or on
        cancellation / error). Release stateful resources here.

        Default no-op.
        """
        pass

    # New optional hooks

    def cache_key(self, inputs: Dict[str, Any]) -> Optional[str]:
        """Override to customise cache key. Return None to disable caching
        for this call (e.g. when one of the inputs is a live stream)."""
        return None  # default: use built-in input-hash strategy

    def validate_inputs(self, inputs: Dict[str, Any]) -> None:
        """Override to add per-node input shape/value checks beyond the
        type system. Raise NodeInputError on failure."""
        pass

    def estimate_cost(self, inputs: Dict[str, Any]) -> float:
        """Override to estimate execution cost (seconds). The scheduler
        may use this for batching or work-stealing in the future. Default
        returns 0.0."""
        return 0.0
```

Backwards compatibility: `prepare` and `teardown` default to no-op. Every existing node is a valid v2 node out of the box. No source change required for the 80+ stateless nodes. Stateful nodes (≈12) must move their initialisation into `prepare` and cleanup into `teardown` — see §5.6 migration matrix.

### 5.2 Typed exception hierarchy

```python
# packages/stride-core/src/stride_core/errors.py  (new file)

class NodeError(Exception):
    """Base class for typed node errors."""
    code: str = "node_error"

    def __init__(self, message: str, *, port: Optional[str] = None,
                 details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.port = port
        self.details = details or {}


class NodeInputError(NodeError):
    """Input value violates the node's expectations.

    Use when a value is the right type but wrong shape/range/contents:
        raise NodeInputError("voxel_size must be > 0", port="voxel_size",
                             details={"got": -0.5, "min": 0.0})
    """
    code = "node_input_error"


class NodeTypeError(NodeError):
    """A typed input was the wrong category. Should rarely fire — graph
    validation catches this — but stateful nodes that cast at runtime
    (e.g. `if isinstance(x, StreamResource)`) can use it."""
    code = "node_type_error"


class NodeRuntimeError(NodeError):
    """A runtime failure during forward (GPU OOM, division by zero,
    file IO error, etc.). Wrap the underlying exception."""
    code = "node_runtime_error"


class NodeMissingDependencyError(NodeError):
    """A required Python package or external binary is missing."""
    code = "node_missing_dependency"


class NodeCancelled(NodeError):
    """Cooperative cancellation marker. Raised by ctx.check_cancelled()
    helpers when the node decides to abort."""
    code = "node_cancelled"


class NodeFileNotFoundError(NodeError):
    """A file the node was asked to read does not exist."""
    code = "node_file_not_found"


class NodeNetworkError(NodeError):
    """A network operation (HTTP, RTSP, websocket, etc.) failed."""
    code = "node_network_error"
```

`backend/app/executor/node_execution.py:263` is updated to inspect the exception type and propagate `error_code` accordingly:

```python
except NodeError as e:
    error_code = e.code
    error_payload = {
        "code": e.code,
        "port": e.port,
        "details": e.details,
    }
    ...
except Exception as e:
    error_code = "internal_error"  # everything else — bug, not user error
    ...
```

### 5.3 Declarative parameter schema

`PortSpec` (`packages/stride-core/src/stride_core/node_spec.py:13-32`) gains a `constraints` field:

```python
@dataclass
class PortSpec:
    name: str
    type: TypeDescriptor = field(default_factory=t_any)
    required: bool = True
    default: Any = None
    description: str = ""
    ui: Dict[str, Any] = field(default_factory=dict)

    # NEW
    constraints: Optional[Dict[str, Any]] = None
    # constraints schema:
    #   {"min": float, "max": float}                      for numeric
    #   {"enum": [v1, v2, ...]}                            for any
    #   {"pattern": "regex"}                               for string
    #   {"path_kind": "file"|"directory", "exists": True}  for file-like strings
    #   {"length_min": int, "length_max": int}             for string/list
    #   {"presets": [{"label": "...", "value": ...}]}     UI-only

    def to_dict(self) -> Dict[str, Any]:
        d = {...}
        if self.constraints:
            d["constraints"] = self.constraints
        return d
```

Constraints are *enforced server-side* in a new `validate_inputs()` step (see §6.3) and *consumed client-side* to render appropriate widgets:

- `{enum: [...]}` → `<select>`.
- `{min, max, step}` → `<input type="range">` or numeric stepper with bounds.
- `{path_kind: "file"}` → file picker (with `<input type="file">` or backend-mediated browse API).
- `{presets: [...]}` → preset dropdown that fills `default`-like values.

### 5.4 Cache-key contract

Today, caching keys off the node type plus a hash of its inputs (`backend/app/executor/node_execution.py:88-114`). The new `cache_key` hook lets a node opt into a custom key:

```python
class StreamFrameNode(NodeBase):
    def cache_key(self, inputs: Dict[str, Any]) -> Optional[str]:
        # Stream frames are time-varying; never cache.
        return None

class StableTransformNode(NodeBase):
    def cache_key(self, inputs: Dict[str, Any]) -> str:
        # Custom key omits a noisy timestamp input.
        return hash_subset(inputs, exclude={"trigger_time"})
```

Returning `None` disables caching for *this* call without globally disabling it. This is what current `cache_policy="disabled"` on the spec achieves (`stride-kalman/nodes.py:125`), but at finer granularity.

### 5.5 Resource lifecycle

`ExecutionContext` (`packages/stride-core/src/stride_core/node_base.py:16-70`) already has `register_resource`. We extend with two methods:

```python
@dataclass
class ExecutionContext:
    ...

    def acquire_node_resource(self, node_id: str, key: str,
                              factory: Callable[[], Any]) -> Any:
        """Get-or-create a per-node, per-key resource. Stored in a
        per-execution dict that is automatically cleaned up at run end."""
        ...

    def release_node_resource(self, node_id: str, key: str) -> None:
        """Release a per-node resource immediately."""
        ...
```

Stateful nodes adopt this pattern in `prepare`:

```python
class Kalman3DTrackerNode(NodeBase):
    def prepare(self, ctx: ExecutionContext) -> None:
        self._state = ctx.acquire_node_resource(
            self.id, "kalman_state",
            lambda: {"tracks": [], "next_id": 1},
        )

    def forward(self, inputs, ctx):
        # use self._state directly; no module-level dict
        ...

    def teardown(self, ctx):
        # ctx auto-releases; teardown is for non-Python resources
        pass
```

Module-level dicts (`_TRACKERS`, `_TRACKER_STATES`, `_background_models`, `_trackers`) are removed in favour of the per-execution context dict. Cross-execution state (the *intentional* persistent learning behaviour) is opt-in via a new `ExecutionContext.acquire_persistent_resource(...)` API that uses a process-wide registry (effectively replicating the current behaviour but explicitly).

### 5.6 Migration matrix for the 145 existing nodes

Categorisation rules:

- **Inherits-for-free**: stateless `forward`, no module dict, no resources. *No source change required.*
- **Light touch**: uses `t_any()` to bypass type checks. Replace with the proper type. ~30-min change.
- **Lifecycle migration**: uses module-level state dicts. Move to `prepare`/`teardown`. ~1-2 hour change per node family.
- **Type-redefinition**: redefines a core type (only `stride-people`). Delete local definition, import core. ~1-hour change.

Estimated breakdown (full per-package matrix in **Appendix B**):

| Category | Approx. node count | Effort |
|---|---|---|
| Inherits-for-free | ~80 | 0 |
| Light touch (any → real type) | ~40 | 1 dev-day total |
| Lifecycle migration | ~15 | 2 dev-days total |
| Type-redefinition (`stride-people`) | ~6 | 0.5 dev-days |
| Converter authoring (new package) | ~25 | 3-4 dev-days |
| **Total** | ~165 (incl. converters) | **~7 dev-days** |

---

## 6. Backend validation pipeline

The current single check at `backend/app/executor/graph_builder.py:142-150` becomes one layer of five.

### 6.1 The five layers

| # | Layer | When | What it catches | Existing site to extend |
|---|---|---|---|---|
| 1 | **Graph-load validation** | `GraphBuilder.build()` constructor | Missing nodes, duplicate node ids, missing port ids, malformed JSON, schema migration | `executor/graph_builder.py:80-160` |
| 2 | **Port-wiring validation** | same constructor, after node lookup | Type mismatch, kind mismatch, structural-subtype failure | `executor/graph_builder.py:142-150` (extend) |
| 3 | **Run-start validation** | `GraphExecutor.run()` / `run_streaming()` entry | Missing required inputs without defaults, control-flow cycles that escape detection | `runner.py:497-505` (extend) |
| 4 | **Node-entry validation** | `NodeExecutor.execute_node_work()` before `forward` | Per-node `validate_inputs`, constraint checks (min/max/enum), required-input null check | `executor/node_execution.py:214-236` (extend) |
| 5 | **Node-exit validation** | same, after `forward` | Output port set matches spec (already enforced), output values match declared types (new shape check) | `executor/node_execution.py:238-245` (extend) |

### 6.2 The "system never crashes" contract

Every layer raises a typed exception (`NodeError` family or `GraphValidationError` family). The runtime catches every typed exception, packages it as a `NodeExecutionResult(status=ERROR, ...)`, and the streaming executor emits a `node_error` event. **No layer ever lets an exception unwind out of the runtime.** Bare `except Exception as e: error_code = "internal_error"` remains as the catch-all.

The frontend never sees a 500. Type-mismatch is a structured 400 with `code="type_mismatch"`. Internal errors are still structured.

### 6.3 Error JSON schema

```typescript
interface NodeErrorPayload {
  code: ErrorCode;            // see §6.5
  message: string;            // human readable
  node_id?: string;           // which node
  port?: string;              // which port (if applicable)
  details?: {
    expected?: TypeDescriptor | string;
    actual?: TypeDescriptor | string;
    value_preview?: unknown;  // truncated, for display
    [extra: string]: unknown;
  };
  stack_trace?: string;       // only in dev mode
}
```

The existing `ExecutionTraceEntry` (`frontend/src/types.ts:79-90`) already has `error` and `error_details`. We add `error_payload?: NodeErrorPayload` and have the frontend prefer it.

### 6.4 Graph-schema migration

`backend/app/domain/graph_migrations.py` (new file):

```python
MIGRATIONS = [
    ("1.0", "1.1", _v1_0_to_1_1),  # rename t_string image ports to t_image, etc.
]

def migrate(graph: dict) -> dict:
    version = graph.get("schema_version", "1.0")
    while version != CURRENT_SCHEMA_VERSION:
        next_version, transform = next(
            (to, fn) for (frm, to, fn) in MIGRATIONS if frm == version
        )
        graph = transform(graph)
        graph["schema_version"] = next_version
        version = next_version
    return graph
```

Invoked at `routers/graphs_router.py` on graph load.

### 6.5 Error codes

```typescript
type ErrorCode =
  | "graph_invalid"                  // malformed graph JSON
  | "node_unknown_type"              // node type not in registry
  | "duplicate_node_id"
  | "missing_input_port"
  | "missing_output_port"
  | "duplicate_link"
  | "type_mismatch"                  // existing
  | "kind_mismatch"                  // new — different kinds, not just shape
  | "schema_subtype_failure"         // record fields don't match
  | "input_required"
  | "input_constraint"               // value violates min/max/enum
  | "node_input_error"
  | "node_runtime_error"
  | "node_missing_dependency"
  | "node_file_not_found"
  | "node_network_error"
  | "node_type_error"
  | "node_cancelled"
  | "internal_error";                // fallback
```

### 6.6 No deep changes to streaming executor

The streaming executor at `backend/app/executor/streaming.py` already catches every per-node error via the `NodeExecutionResult` path. We do not change scheduling, parallelism, or the readiness-queue. We just enrich the error payload that flows through the existing path.

---

## 7. Frontend connection UX (Blueprint-grade)

The current connection flow is in `frontend/src/hooks/useConnectionValidation.ts` plus the React Flow integration in the graph editor. Minimum target is parity with Unreal Blueprint / NodeRed / TouchDesigner.

### 7.1 Drag-from-port port highlighting

When the user grabs a port and starts dragging, every other port on the canvas should visually classify itself:

- **Compatible (green halo)**: directly assignable per `is_assignable_to`.
- **Suggested (amber halo)**: invalid but a converter exists per §4.3.
- **Incompatible (greyed out)**: rejected.
- **Self / illegal direction**: hidden / opacity 0.3.

Implementation: `BlueprintNodeData` (`frontend/src/types.ts:181-226`) already has `highlightedPort` on a per-node basis. We extend with `connectionMode: "compatible" | "suggested" | "incompatible" | "neutral"` and have the React Flow node renderer apply a CSS class. The state is computed from a new context `ConnectionDragContext` populated when `onConnectStart` fires (already in `useConnectionValidation`).

The compatibility check is the same `arePortTypesCompatible` we already have (`useConnectionValidation.ts:67-105`). The suggestion check queries the converter index built from `/api/node-definitions` (see §4.7).

### 7.2 Drop-on-canvas type-filtered context menu

When the user releases the drag on empty canvas:

- Show a search palette pre-filtered to nodes that *accept* the source type (output drag) or *produce* the target type (input drag).
- Filter is by structural compatibility, not exact kind match.
- Top section: "compatible" (zero-cost direct connection).
- Second section: "via converter" (suggested intermediate).
- Search box for additional fuzzy filtering.

Implementation: a new `<NodeSearchPalette>` component at `frontend/src/components/graph/NodeSearchPalette.tsx`. Triggered by React Flow's `onConnectEnd` callback when `event.target` is the canvas pane (no port). Same component can be triggered by `Ctrl+K` for general node search.

### 7.3 Real-time edge invalidation

When a node parameter changes — particularly `Cast` nodes whose output type depends on a `target_type` parameter — downstream edges may become invalid. Today, validation only runs on `onConnect` and is not re-run.

We add a `useEdgeValidation` hook that subscribes to node updates and revalidates every edge whose `from_node` or `to_node` is among the changed nodes. Invalid edges are visually marked with red dashes; the user can either delete the edge or accept a suggested converter.

### 7.4 Inline node error UI with disclosure

Today, `BlueprintNodeData.executionStatus === "error"` renders the node red. There is no error message until the user opens an inspector panel.

Improvement: each error node gets a small badge in its header showing the error category (icon + 2-letter code). Clicking the badge opens a tooltip with:

- Human-readable message.
- Disclosure triangle for stack trace (dev mode).
- Link to the offending input port (highlighted on the node) if `error.port` is set.
- "Quick fix" button when applicable (e.g. when `error.code === "input_required"` and a default exists).

### 7.5 In-canvas search palette

The Ctrl+K palette becomes the canonical entry for adding nodes. It supports:

- Fuzzy search on `display_name`, `category`, `tags`.
- Type filter (when invoked from a port drag).
- Recently used.
- Pinned favourites (per-graph).

Existing left-sidebar node list (visible by default) becomes the categorical-tree view, secondary to the palette.

### 7.6 No regressions to control / data port distinction

Today, control ports are dashed-orange (`useConnectionValidation.ts:300-304`). This is preserved — control connections do not participate in any of the new type-suggestion machinery.

---

## 8. Visualiser registry

### 8.1 Goal

Replace the hand-coded `if/else` chain in `frontend/src/components/dashboard/DashboardWidgetContent.tsx:97-119` with a registry keyed on type kind (and optionally subtype):

```typescript
// frontend/src/visualizers/registry.ts

export interface VisualizerProps<TValue = unknown> {
  value: TValue;
  type: TypeDescriptor;
  width: number;
  height: number;
  context: { nodeId: string; portName: string };
}

export interface VisualizerSpec {
  kind: string;                                        // e.g. "image"
  subtype?: string;                                    // e.g. "url"
  priority: number;                                    // higher wins
  match: (value: unknown, type: TypeDescriptor) => boolean;
  Component: React.FC<VisualizerProps>;
  composesWith?: string[];                             // for overlays
}

export const VISUALIZER_REGISTRY: VisualizerSpec[] = [];
export function registerVisualizer(spec: VisualizerSpec): void;
export function resolveVisualizer(
  value: unknown,
  type: TypeDescriptor,
): VisualizerSpec | null;
```

Resolution order:

1. Filter to specs where `kind === type.kind` (or `kind === "*"` for fallback).
2. If `type.metadata.subtype` exists, prefer specs with the matching `subtype`.
3. Filter by `match()` returning true.
4. Sort by `priority` desc, take the first.
5. If none, fall back to JSON dump.

### 8.2 Build-time discovery via `stride.visualizer.json`

A package contributes visualisers by including a manifest in its frontend package:

```json
// frontend/packages/stride-yolo-frontend/stride.visualizer.json
{
  "visualizers": [
    {
      "module": "./src/visualizers/Detections2DOverlay.tsx",
      "export": "default",
      "kind": "detections2d",
      "priority": 10
    }
  ]
}
```

A Vite plugin (`frontend/vite-plugin-stride-visualizers.ts`, new) scans `frontend/packages/*/stride.visualizer.json` at build time and emits a generated registration file imported by `frontend/src/visualizers/index.ts`. This keeps adding a visualiser to a single-line registration in a manifest — no central file edits.

### 8.3 Default visualiser inventory

| Kind | Visualiser | Backed by |
|---|---|---|
| `int`, `float` | numeric badge with format options | inline |
| `boolean` | toggle indicator | inline |
| `string` | text with auto-`<a>` for URLs | inline |
| `image` | `<img>` with zoom/pan | wraps the existing `data:image` branch |
| `mask` | `<canvas>` with colour overlay | new |
| `depthmap` | `<canvas>` with viridis colormap + min/max ramp | new |
| `bbox2d` (single) | mini diagram with the box | new |
| `detections2d` | `<canvas>` overlaying boxes on `image` field | new |
| `keypoints` | `<canvas>` skeleton overlay | new |
| `track2d` | same as `detections2d` plus track-ID label | reuses |
| `pointcloud` | `PointCloudWidget` (existing) | existing |
| `bbox3d` (single) | three.js cube primitive | new |
| `track3d` | three.js with track trails | new |
| `region3d` | three.js wireframe box | new |
| `scene3d` | `Scene3DWidget` (existing) | existing |
| `detections3d` | three.js boxes | new |
| `stream` | streaming `<img>` (existing logic) | existing |
| `tensor` (1-D) | sparkline | new |
| `tensor` (2-D) | heatmap | new |
| `tensor` (3-D, dim≤4) | image strip | new |
| `list<T>` | scrollable strip of T-visualisers | new |
| `record` | key-value pairs (current JSON dump cleaned up) | new |
| `*` (fallback) | JSON dump | existing |

### 8.4 Composition (overlay)

Some visualisations need composition — `image` plus `detections2d` plus `keypoints` is a single overlay, not three stacked widgets. The widget config in `DashboardWidget` (`frontend/src/types.ts:237-258`) gains an optional `composition` field:

```typescript
interface DashboardWidget {
  ...
  composition?: {
    primary: { nodeId: string; portName: string };       // e.g. the image
    overlays: Array<{ nodeId: string; portName: string }>;  // e.g. detections, keypoints
  };
}
```

A composition visualiser is a special entry in the registry with `kind: "composition"` that knows how to render the primary plus each overlay using the registry recursively.

### 8.5 Performance envelope

- Pointcloud and large tensors must use base64-encoded binary fields (existing convention) and stream-decode on the worker thread.
- Visualisers that re-render at >10 Hz (live streams) must use `<canvas>` not React-driven SVG.
- Three.js scenes share a single WebGL context per dashboard.

---

## 9. Extensibility & plugin contract

### 9.1 What a package contributes

A STRIDE plugin package today contributes nodes via `register_node` and the `stride.plugins` entry-point group (`packages/stride-core/src/stride_core/plugin.py:23`). After this proposal, a package may also contribute:

- **Types**: new `TypeDescriptor` kinds, in a new `types` module that registers via a `stride.types` entry-point.
- **Converters**: `convert.*` nodes, no special API beyond being normal nodes; their `metadata.convert_from`/`convert_to` makes them discoverable.
- **Visualisers**: React components keyed in `stride.visualizer.json` (§8.2).
- **Validation rules**: optional functions `(value, type) -> Optional[NodeError]` registered via `stride.validators` entry-point. Run inside Layer 4 / Layer 5 of the validation pipeline.

### 9.2 Type registration

```python
# packages/<your-package>/src/<your_package>/types.py

from stride_core.typesystem import t_record_kind, t_int, t_string

def t_my_payload():
    return t_record_kind("my_payload", {
        "id": t_int(),
        "data": t_string(),
    })


# pyproject.toml entry-point
# [project.entry-points."stride.types"]
# my_payload = "<your_package>.types:t_my_payload"
```

The runtime calls every entry-point function during `discover_plugins()` (extending `packages/stride-core/src/stride_core/plugin.py`) and adds the returned `TypeDescriptor`'s kind to the global type registry. Two packages declaring the same kind name with different schemas raises a startup error — fail-fast prevents silent shadowing.

### 9.3 Validator registration

```python
# packages/<your-package>/validators.py

def validate_my_payload(value, type_desc):
    if not isinstance(value, dict):
        return NodeInputError("expected dict for my_payload")
    return None

# entry-point: stride.validators
# my_payload = "<your_package>.validators:validate_my_payload"
```

### 9.4 Versioning

Each `NodeSpec` already has `version: str = "1.0.0"` (`node_spec.py:40`). We adopt the convention:

- Major version bump: breaking change to port types or required inputs.
- Minor: additive only.
- Patch: doc / behaviour fixes.

The graph-schema migration (§6.4) keys off node version when applicable. A graph saved with `node@1.0` is automatically run through migrations on load if `node@2.0` is now installed.

### 9.5 Plugin discovery resilience

`packages/stride-core/src/stride_core/plugin.py:75-124` already catches per-plugin load errors. Extend so a failed plugin reports a structured `PluginInfo.error` and the editor surfaces it in a "Plugins" panel — failed plugins should be visible, not silently absent.

---

## 10. Implementation phases

### Phase 0 — Groundwork (no behavioural change)

**Goal**: land the scaffolding that lets every later phase be reversible.

**Deliverables**:

1. New file `packages/stride-core/src/stride_core/errors.py` with the `NodeError` hierarchy (§5.2). No call sites change yet.
2. New file `backend/app/domain/graph_migrations.py` with empty migration list.
3. `schema_version` field added to graph save/load with default `"1.0"`. Migrations run but do nothing.
4. Frontend `TypeKind` union (`frontend/src/types.ts:3-24`) extended to all backend kinds. PORT_TYPE_COLORS map extended (§3.5). All ports continue to render — just with their proper colour.
5. New `frontend/src/visualizers/registry.ts` with the `VISUALIZER_REGISTRY` array and `resolveVisualizer` function. Existing visualisers re-registered into the registry. The `if/else` chain in `DashboardWidgetContent.tsx:97-119` is replaced with `resolveVisualizer(...).Component`. **Functionally identical**.

**Files added**: 3. **Files touched**: 4. **Complexity**: S.

**Parallelisable**: yes — three distinct surfaces (Python, frontend types, frontend registry) can be three sub-PRs.

### Phase 1 — MVP type unification (backend-only)

**Goal**: domain types have schemas; cross-package wiring works.

**Deliverables**:

1. `packages/stride-core/src/stride_core/typesystem.py`: add `t_record_kind` factory; rewrite `t_bbox2d`, `t_bbox3d`, `t_detections2d`, `t_detections3d`, `t_track2d`, `t_track3d`, `t_keypoints`, `t_image`, `t_depthmap`, `t_mask`, `t_pointcloud`, `t_region3d`, `t_scene3d`, `t_stream` per §3.2.
2. `is_assignable_to` (`typesystem.py:144-192`) extended to accept the `kind != "record" && fields is not None` case the same way as `record`. Behaviour: structural-subtype check, kind label is for UI only.
3. `packages/stride-people/src/stride_people/nodes.py:39-65` removes the local `t_bbox3d`/`t_region3d`/`t_scene3d` and imports from core.
4. `backend/app/nodes/image_nodes.py:34,96`: change `t_string()` → `t_image()` for the image port. Add a 1.0→1.1 migration that rewrites graphs.
5. `backend/app/nodes/sv_core.py`: replace `t_any()` with proper types where possible (lines 71, 96, 129, 130, 131, 135, 172, 178). Cast nodes can keep `t_any` where genuinely polymorphic.
6. Backend tests for `is_assignable_to` against the new schemas.

**Migration risk**: existing saved graphs with literal `t_string` image ports continue to work because the migration step at load rewrites them. Loading `liguard-people` graphs continues to work because the local types now align with core via the schema convergence.

**Files added**: 0. **Files touched**: ~10. **Complexity**: M.

**Parallelisable**: medium — type definitions must land first; per-package node fixes can fan out.

### Phase 2 — NodeBase v2 + typed exceptions

**Goal**: lifecycle hooks; structured errors.

**Deliverables**:

1. `packages/stride-core/src/stride_core/node_base.py`: add `prepare`, `teardown`, `cache_key`, `validate_inputs`, `estimate_cost` defaults.
2. `backend/app/executor/node_execution.py`: extend `try/except` to dispatch on `NodeError` family; emit structured payload (§6.3). The bare `except Exception` becomes the fallback `internal_error` only.
3. `backend/app/executor/streaming.py`: thread the typed error through the WS event payload.
4. Migrate stateful nodes — `tracker.kalman3d`, `tracker.bytetrack`, `people.detect` — to `prepare`/`teardown` and `ctx.acquire_node_resource(...)`. Module dicts deleted. (See **Appendix B** for the full table.)
5. `PortSpec.constraints` field (§5.3); enforced in `validate_inputs` step. Backend updated with the field; frontend uses still pending.
6. `frontend/src/types.ts`: add `error_payload?: NodeErrorPayload` to `ExecutionTraceEntry`.

**Files added**: 1 (`errors.py`). **Files touched**: ~15. **Complexity**: L.

### Phase 3 — Frontend connection UX

**Goal**: Blueprint-grade drag/drop.

**Deliverables**:

1. Extended `useConnectionValidation` (§7.1) returning compatibility classification per port, not just go/no-go for the in-progress edge.
2. `<NodeSearchPalette>` component (§7.2). Triggered from canvas drop and `Ctrl+K`.
3. Edge revalidation hook (§7.3).
4. Inline error badges + tooltips (§7.4). Frontend reads `error_payload.code` to look up category icon and label.
5. Connection-line colour and dash pulled from the new colour map (§3.5).

**Files added**: 3-5. **Files touched**: ~8. **Complexity**: L.

### Phase 4 — Visualisers + converters

**Goal**: every type has a non-JSON visualiser; one-click conversion suggestions.

**Deliverables**:

1. New package `packages/stride-converters/` with the ~25 nodes from §4.5.
2. Vite plugin `frontend/vite-plugin-stride-visualizers.ts` (§8.2).
3. New visualiser components for `image`, `mask`, `depthmap`, `detections2d`, `track2d`, `keypoints`, `bbox3d`, `track3d`, `region3d`, `detections3d`, `tensor` (1-D, 2-D), `list<T>`, `record`. (See **§8.3** for the full table.)
4. Composition visualiser (§8.4).
5. Frontend conversion-suggestion UI driven by the converter index (§4.7).

**Files added**: ~30. **Files touched**: ~5. **Complexity**: XL.

**Parallelisable**: high — each visualiser is independent.

### Phase 5 — Polish & cleanup

**Goal**: remove deprecated code paths; add docs and tests.

**Deliverables**:

1. Delete `t_image_legacy` alias.
2. Delete `_TRACKERS`, `_TRACKER_STATES`, `_background_models`, `_trackers` module dicts (already migrated in Phase 2 but kept as deprecated aliases for one cycle).
3. Validator entry-point support (§9.3).
4. Migration of `t_any()` escape hatches that survive Phases 1-4.
5. Documentation: update `docs/architecture/type-system.md` to reflect the new taxonomy. Update `docs/nodes/authoring-guide.md` with the lifecycle hooks.
6. Test suite expansion: round-trip tests for every new conversion node; structural-subtype tests for every record schema.

**Files added**: ~5. **Files touched**: ~15. **Complexity**: M.

### 10.1 Minimum viable cut

Phase 0 + Phase 1 + Phase 2 (lifecycle migration of stateful nodes only; constraints API can wait) is the minimum cut that resolves the "system never crashes" contract and the cross-package wiring failure. ~4 dev-days of focused work; can ship in one PR if reviewed carefully.

After the MVP, Phase 3 (UX) and Phase 4 (visualisers) are independent and can run in parallel.

### 10.2 Parallelisability across agents

| Agent | Lane | Phases |
|---|---|---|
| A | Backend types & lifecycle | 0 (Python parts) → 1 → 2 |
| B | Frontend types & UX | 0 (frontend parts) → 3 |
| C | Visualisers & converters | Phase 4 (waits for Phase 1) |

Total wall-clock with three agents: ~2 weeks (the longest path is A's serial chain).

---

## 11. Risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | Schema migration breaks saved demo graphs | High | Medium | Phase 0 lands `schema_version` and migrations *first*; Phase 1 transforms are pure JSON rewrites; CI fixture: load every saved graph in `tests/fixtures/graphs/` after each phase |
| 2 | Hot-path `is_assignable_to` cost grows on every connection | Low | Medium | Profile a 200-node graph build; structural subtyping is O(fields) per record — already cheap. Cache `to_dict()` results on `NodeSpec` |
| 3 | Two packages declare the same `kind` with different schemas | Medium | High | Plugin loader (§9.2) raises on duplicate kind. Ship a startup linter |
| 4 | Frontend bundle bloat from per-type visualisers | Medium | Medium | Vite plugin emits dynamic imports per visualiser; lazy-load on first use; three.js shared singleton |
| 5 | Large pointclouds over WebSocket lock the event loop | Medium | High | Already a problem today (`Scene3DWidget.tsx:47-52` decodes synchronously). Move base64 → Float32Array decode to a Worker; throttle stream rate. Out-of-scope for this proposal but tracked |
| 6 | Stateful node migration loses persistent learning state across runs | Medium | High | Provide `acquire_persistent_resource` (§5.5) that mirrors current module-dict semantics; default behaviour for `tracker.*` and `people.detect` is opt-out (still cross-run) |
| 7 | New `t_image` record format breaks user-authored "core.image.load → my custom node" wiring | High | Medium | The 1.0→1.1 migration auto-rewrites; document the change in CHANGELOG; legacy alias `t_image_legacy = t_string` for one minor version |
| 8 | Plugin author shadows a core type | Low | High | Plugin loader rejects duplicate-kind. Document the kind namespace |
| 9 | Visualiser registry resolution is wrong for multi-match types | Low | Low | Specs declare `priority`; ties broken by registration order; tests for resolution stability |
| 10 | Weight downloads (CLIP, YOLO, depth-anything) on first run | High | Medium | Already a problem; not made worse by this proposal. Track separately |
| 11 | Stream type's live-handle assumption fails when we add multi-process workers | Medium | High | Document the in-process invariant; plan a follow-up for stream-handle re-attachment via `stream_id` lookup. Out-of-scope |
| 12 | Hot reload breaks when `NODE_REGISTRY` accumulates duplicates | Low | Low | Existing `clear_registry()` path (`packages/stride-core/src/stride_core/registry.py:83-85`); ensure dev hot-reload calls it |

---

## 12. Open questions for the user

### Q1. Should we keep `t_any` as a documented escape hatch, or drive it to zero?

**Options**:

a. Keep `t_any` and document when to use it (e.g. truly polymorphic helper nodes like `core.cast.*`).
b. Drive to zero; require every escape to use a generic instead.
c. Keep `t_any` but lint against it in CI (warn-only).

**Recommendation**: (a). The `core.cast.*` family genuinely needs polymorphism, and `Map<string, any>` for opaque metadata is a useful pattern. Document the use-cases and treat any *new* `t_any` outside those patterns as a code-review red flag.

### Q2. How aggressively should we replace `t_string()` with refined types like `t_string(subtype="path")`?

**Options**:

a. Add `subtype` everywhere it makes sense (path, URL, regex pattern, JSONPath).
b. Only for `path` (file pickers are the obvious UX win).
c. Don't touch — keep strings as strings.

**Recommendation**: (b) for the MVP, expand later. File pickers are an obvious UX win; URL syntax validation is a marginal one. Keep the door open.

### Q3. Should `track2d` and `bbox2d` share a kind or have separate kinds?

**Options**:

a. Same kind (`bbox2d`) with `track_id` nullable; "track" is a value-level distinction.
b. Separate kinds (`bbox2d`, `track2d`) related by structural subtyping.
c. Same kind plus `metadata.subtype: "track"`.

**Recommendation**: (b). Kind-level distinction lets the frontend pick the right colour and visualiser without inspecting values. Structural subtyping (track has all of bbox's fields) makes `track2d → bbox2d` flow freely. Same goes for 3-D.

### Q4. Where does the `metadata.subtype` namespace come from?

**Options**:

a. Open string (any subtype anyone wants).
b. Closed enum maintained in `stride-core` (limits drift).
c. Per-kind enum maintained alongside the type definition.

**Recommendation**: (c). `stride-core` declares per-kind enums (`pointcloud.subtype: ["lidar", "rgbd", "synthetic", "unknown"]`); plugin packages can extend their own kinds' enums via the `stride.types` entry-point.

### Q5. How do we handle node renames in graph migrations?

**Options**:

a. Hard-rewrite at load with a static rename table.
b. Keep deprecated aliases registered alongside new names.
c. Both — rename table for major changes, aliases for minor.

**Recommendation**: (c). Aliases for one minor version (gives users a release cycle to migrate); rename table for graphs older than that.

### Q6. Should the visualiser registry support per-graph custom visualisers?

**Options**:

a. Build-time only — packages contribute, that's it.
b. Runtime registration via a node param (e.g. a "custom HTML" widget node).
c. Both.

**Recommendation**: (a) for MVP. Runtime custom HTML opens a sandbox-escape risk; defer until we have an isolation story.

### Q7. Should converter nodes auto-insert when the user makes an "easy" suggested connection, or always require explicit acceptance?

**Options**:

a. Always require an explicit click (current convention).
b. Auto-insert for cost ≤ 2 conversions; require click for higher cost.
c. Per-user preference setting.

**Recommendation**: (a) for MVP. Auto-insertion can produce confusing graphs where the user didn't realise a node was added. Always-explicit preserves the user's mental model.

---

## 13. Appendix A — Full port type inventory

The table is sorted by kind alphabetically. "Defined at" is the primary `TypeDescriptor` factory site; "used at" is a representative usage. "Frontend colour" is the current colour, "Proposed colour" is per §3.5.

| Kind | Factory | Defined at | Used at (sample) | Payload shape (proposed) | Frontend colour today | Proposed colour |
|---|---|---|---|---|---|---|
| `any` | `t_any()` | `typesystem.py:276` | many | — | `#94a3b8` | unchanged |
| `boolean` | `t_boolean()` | `typesystem.py:300` | many | bool | `#f59e0b` | unchanged |
| `bbox2d` | `t_bbox2d()` | `typesystem.py:447` | `yolo/nodes.py:139`, `bytetrack/nodes.py:91` | `{x1,y1,x2,y2,confidence,class_id,class_name,track_id?}` | falls through (grey) | `#fb7185` |
| `bbox3d` | `t_bbox3d()` | `typesystem.py:375` (opaque) **OR** `stride-people/nodes.py:39` (record) | `kalman/nodes.py:107`, `pcdet/...` | `{id,center,size,rotation?,velocity?,confidence?,class_id?,class_name?,frame}` | grey | `#a78bfa` |
| `box` | `t_box()` | `typesystem.py:355` | (rare) | (deprecated alias for bbox2d) | grey | `#fb7185` |
| `control` | `t_control()` | `typesystem.py:330` | every node | sequencing only | `#f97316` | unchanged |
| `depthmap` | `t_depthmap()` | `typesystem.py:470` | `depth_anything/nodes.py:124` | `{width,height,depth_b64,min_depth,max_depth,image?}` | grey | `#14b8a6` |
| `detections2d` | `t_detections2d()` | `typesystem.py:460` | `yolo/nodes.py`, `rtdetr/nodes.py` | `{image_width,image_height,boxes:list<bbox2d>,image?}` | grey | `#ef4444` |
| `detections3d` | `t_detections3d()` | `typesystem.py:465` | `pcdet/nodes.py`, `kalman/nodes.py:30` | `{boxes:list<bbox3d>,scene_metadata?}` | grey | `#dc2626` |
| `float` | `t_float()` | `typesystem.py:292` | many | float | `#60a5fa` | unchanged |
| `image` | `t_image()` (kind=image) | `typesystem.py:442` | `yolo/nodes.py:127` | `{width,height,format,data_b64}` | `#e85aad` | unchanged |
| `image` (legacy) | `t_string()` (kind=string) | `image_nodes.py:34` | `core.image.load` output | data URL string | `#10b981` (green) | (rewrite to image record) |
| `int` | `t_int()` | `typesystem.py:288` | many | int | `#4a9eff` | unchanged |
| `keypoints` | `t_keypoints()` | `typesystem.py:485` | `mediapipe/nodes.py` | `{instances:list<{keypoints,bbox?}>,schema_name?}` | grey | `#facc15` |
| `list` | `t_list(T)` | `typesystem.py:304` | many | (parametric) | `#7dd3fc` | unchanged |
| `map` | `t_map(K,V)` | `typesystem.py:309` | many | (parametric) | `#facc15` | unchanged |
| `mask` | `t_mask()` | `typesystem.py:360` | (sam3, future) | `{width,height,data_b64,encoding}` | grey | `#f472b6` |
| `null` | `t_null()` | `typesystem.py:284` | (rare) | null | — | unchanged |
| `option` | `t_option(T)` | `typesystem.py:326` | (parametric) | T or null | falls to inner | falls to inner |
| `point` | `t_point()` | `typesystem.py:350` | (rare; sam3) | `{x,y}` | grey | (deprecated; use record) |
| `pointcloud` | `t_pointcloud()` | `typesystem.py:370` | `ouster/nodes.py`, `people/nodes.py:388` | `{num_points,positions_b64,fields_b64?,...,frame}` | grey | `#8b5cf6` |
| `record` | `t_record(F)` | `typesystem.py:334` | many | (parametric) | `#a855f7` | unchanged |
| `region3d` | `t_region3d()` | `typesystem.py:380` (opaque) **OR** `stride-people/nodes.py:48` (record) | `people/nodes.py:425` | `{name,center,size,rotation?}` | grey | `#ec4899` |
| `scene3d` | `t_scene3d()` | `typesystem.py:385` (opaque) **OR** `stride-people/nodes.py:57` (record) | `people/nodes.py:463` | `{point_cloud,boxes,regions,occupancy,image_overlays?}` | grey | `#6366f1` |
| `session` | `t_session()` | `typesystem.py:365` | (rare; AI handles) | opaque resource | grey | `#64748b` |
| `stream` | `t_stream()` | `typesystem.py:342` | `fl511/nodes.py:464,527,600` | (becomes record per §3.6) | `#0fb5a9` | unchanged |
| `string` | `t_string()` | `typesystem.py:296` | many | str | `#10b981` | unchanged |
| `tensor` | `t_tensor(dtype,shape)` | `typesystem.py:338` | (rare; ML interop) | numeric ndarray | `#22d3ee` | unchanged |
| `track2d` | `t_track2d()` | `typesystem.py:475` (opaque) | `bytetrack/nodes.py` | extends bbox2d, non-null track_id | grey | `#f43f5e` |
| `track3d` | `t_track3d()` | `typesystem.py:480` (opaque) | (kalman output, future) | extends bbox3d, non-null id | grey | `#7c3aed` |
| `tuple` | `t_tuple(...)` | `typesystem.py:317` | (rare) | fixed arity | grey | `#a855f7` (record family) |
| `unknown` | `t_unknown()` | `typesystem.py:280` | many | universal | `#cbd5e1` | unchanged |
| `url` | (no factory) | (used as string only) | (frontend convention) | — | `#7c3aed` | (deprecate; use `string subtype="url"`) |

---

## 14. Appendix B — Migration matrix per package

For each package, the table lists each registered node and what changes (if anything).

### `stride-core` — built-in nodes in `backend/app/nodes/`

| File | Node count | Inherits-for-free | Light touch | Lifecycle | Notes |
|---|---|---|---|---|---|
| `addition.py` | 1 | 1 | — | — | |
| `array_nodes.py` | 9 | 9 | — | — | |
| `casting.py` | 4 | 4 | — | — | uses `t_any` legitimately |
| `constant.py` | 4 | 4 | — | — | |
| `containers.py` | 4 | 4 | — | — | |
| `control.py` | 1 | 1 | — | — | |
| `debug_nodes.py` | 6 | 6 | — | — | |
| `display.py` | 1 | 1 | — | — | |
| `image_nodes.py` | 2 | — | 2 | — | output type `t_string` → `t_image` |
| `json_nodes.py` | 2 | 2 | — | — | |
| `math_nodes.py` | 13 | 13 | — | — | |
| `math_ops.py` | 5 | 5 | — | — | |
| `programming.py` | 13 | 13 | — | — | |
| `string_nodes.py` | 11 | 11 | — | — | |
| `sv_annotators.py` | 11 | — | 11 | — | many `t_any()` ports → real types |
| `sv_core.py` | 6 | — | 6 | — | many `t_any()` ports → real types |
| `sv_tools.py` | 3 | — | 3 | — | mixed |
| `time_random_nodes.py` | 6 | 6 | — | — | |
| `ul_yolo.py` | 6 | — | 6 | — | uses `t_any` for image/detections |
| **subtotal** | **108** | **80** | **28** | **0** | |

### Plugin packages

| Package | Node count | Free | Light | Lifecycle | Type-redef | Notes |
|---|---|---|---|---|---|---|
| `stride-bytetrack` | 1 | — | — | 1 | — | move `_TRACKERS` to ctx |
| `stride-clip` | 2 | 2 | — | — | — | |
| `stride-depth-anything` | 1 | — | — | 1 | — | model session via `prepare` |
| `stride-fl511` | 4 | — | — | 4 | — | StreamResource via prepare/teardown |
| `stride-grounding-dino` | 1 | — | — | 1 | — | model session |
| `stride-kalman` | 1 | — | — | 1 | — | move `_TRACKER_STATES` to ctx |
| `stride-mediapipe` | 3 | 3 | — | — | — | (MediaPipe holds its own state) |
| `stride-ouster` | 2 | — | — | 2 | — | sensor handle via prepare/teardown |
| `stride-pcdet` | 4 | — | — | 4 | — | model session |
| `stride-people` | 6 | — | — | 4 | 6 | type-redef priority + stateful nodes |
| `stride-rtdetr` | 1 | — | — | 1 | — | model session |
| `stride-sam3` | 7 | — | — | 4 | — | session API |
| `stride-yolo` | 3 | — | — | 3 | — | model session |
| `liguard-lidarops` | unknown | (TBD) | — | — | — | not yet inventoried |
| `liguard-waymo` | unknown | (TBD) | — | — | — | dataset reader |
| **subtotal** | **~36** | **5** | **0** | **26** | **6** | |

### Grand totals

- Free: 85 (~58%)
- Light touch: 28 (~19%)
- Lifecycle migration: 26 (~18%)
- Type redefinition: 6 (~4%)
- New (converters): 25

Most of the codebase migrates for free. The lifecycle-migration nodes (26) are concentrated in plugin packages and most use the same pattern (model session held in a global dict), so a single helper `acquire_session_resource(loader)` solves most of them in one place.

---

## 15. Document changelog

- **2026-04-29**: Initial draft.

