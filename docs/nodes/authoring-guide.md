# Node Authoring Guide

This guide explains how to create new nodes for STRIDE.

A node is a Python class registered against a `NodeSpec`. It has typed
input and output ports, an explicit lifecycle (prepare → forward →
teardown), declarative parameter constraints, and access to a per-run
`ExecutionContext` for resources, logging, and cancellation.

## Where to put it

- **Built-in node** (ships with the runtime): a new module under
  `backend/app/nodes/` and an import in `backend/app/nodes/__init__.py`.
- **Plugin package** (preferred for anything domain-specific): a new
  `packages/stride-<name>/` folder following the
  `stride-bytetrack` template, plus a `[project.entry-points."stride.plugins"]`
  registration in its `pyproject.toml`. The runtime auto-loads plugin
  packages from the entry-point group at startup; you only need to add
  the package name to `backend/pyproject.toml`'s dependencies and
  `[tool.uv.sources]` and run `uv sync`.

## NodeBase v2 contract

```python
# packages/stride-core/src/stride_core/node_base.py
class NodeBase(abc.ABC):
    spec: NodeSpec  # injected by @register_node

    def prepare(self, ctx: ExecutionContext) -> None: ...
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]: ...
    def teardown(self, ctx: ExecutionContext) -> None: ...
    def validate_inputs(self, inputs: Dict[str, Any]) -> None: ...
    def cache_key(self, inputs: Dict[str, Any]) -> Optional[str]: ...
    def estimate_cost(self, inputs: Dict[str, Any]) -> float: ...
```

Hook lifecycle:

- `prepare` runs **once per execution run**, before the first `forward()`
  call. Use it to allocate stateful resources (model sessions, sockets,
  Kalman state, voxel background models, …) — typically via
  `ctx.acquire_node_resource(...)` or `ctx.acquire_run_resource(...)`.
  Default no-op so stateless nodes inherit-for-free.
- `forward` is the data transform. **Pure-ish**: must not allocate
  per-call expensive resources; reuse what `prepare` allocated.
- `teardown` runs once per run after the last forward (also on
  cancellation / error). Default no-op. Override only when the resource
  you held is not Python-managed (an OS handle, a subprocess) — Python
  refs and `acquire_node_resource` / `acquire_run_resource` resources
  are released automatically.
- `validate_inputs` is auto-called by the executor before `forward`.
  The default enforces declarative `PortSpec.constraints` and raises
  `NodeInputError` on failure (see below). Override to add bespoke
  shape / range checks.
- `cache_key` returns a stable hash (or `None` to disable caching for
  this call). The default hashes type + params + inputs and is correct
  for almost every node.
- `estimate_cost` is a scheduler hint (in arbitrary units). Default
  returns 1.0.

## A minimal node

```python
# packages/stride-foo/src/stride_foo/nodes.py

from typing import Any, Dict
from stride_core import NodeBase, ExecutionContext, register_node
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import t_float, t_int, t_control

ADD_SPEC = NodeSpec(
    type="foo.add",
    version="1.0.0",
    display_name="Add",
    category="Foo",
    summary="Add two numbers.",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="a", type=t_float(), required=True, default=0.0),
        PortSpec(name="b", type=t_float(), required=True, default=0.0),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="sum", type=t_float()),
    ],
    cache_policy="auto",
)

@register_node(ADD_SPEC)
class AddNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        a = float(inputs.get("a") or 0.0)
        b = float(inputs.get("b") or 0.0)
        ctx.log(f"foo.add: {a} + {b}")
        return {"control_out": None, "sum": a + b}
```

## Declarative parameter constraints

`PortSpec.constraints` (see `node_spec.py`) lets the runtime enforce
shape / range / enum / pattern checks server-side and the frontend
render bounded widgets.

| Constraint | Meaning |
|---|---|
| `{"min": x, "max": y}` | numeric range; bounds enforced by `validate_inputs` |
| `{"enum": [...]}` | value must be one of the choices |
| `{"pattern": "regex"}` | string must match the regex |
| `{"length_min": n, "length_max": m}` | string / list length bounds |
| `{"extensions": ["jpg", "png"]}` | file path extension whitelist |
| `{"presets": [{"label": ..., "value": ...}]}` | UI-only preset hint |

Example:

```python
PortSpec(
    name="track_activation_threshold",
    type=t_float(),
    required=False, default=0.25,
    constraints={"min": 0.0, "max": 1.0},
)
PortSpec(
    name="strategy",
    type=t_string(),
    required=False, default="random",
    constraints={"enum": ["random", "voxel"]},
)
```

A constraint violation surfaces as a `NodeInputError` with a structured
payload (`code: "node_input_error"`, `port: ...`, `details.constraint`)
and is rendered as an inline node error in the editor.

## Resource scoping

Three lifetimes are available on `ExecutionContext`:

| Scope | API | Released by | Use when |
|---|---|---|---|
| Per node, per run | `ctx.acquire_node_resource(self.id, key, factory)` | end of run | tracker / Kalman state private to one node |
| Run-scoped, cross node | `ctx.acquire_run_resource(key, factory)` | end of run | model session shared between sibling nodes; FL511 stream |
| Process-wide | global module dict (rare) | never | only when the runtime cannot manage it (e.g. an HTTP endpoint must reach the resource from outside the executor) |

Pre-Phase-2 nodes used module-level dicts as caches; **don't do this
anymore**. Phase 5 deleted every model cache dict in the plugin
packages — they all flow through `ctx.acquire_run_resource` now. The
benefits:

- Two consecutive runs can never see each other's state.
- Nodes that share a model (e.g. two YOLO nodes pointing at the same
  weights) materialise the model exactly once per run.
- The executor's teardown step closes every resource even when a
  `forward` raises.

## Typed errors

Raise a typed `NodeError` subclass (from `stride_core.errors`) so the
runtime emits a structured error payload:

```python
from stride_core.errors import (
    NodeInputError, NodeFileNotFoundError, NodeNetworkError,
    NodeMissingDependencyError, NodeRuntimeError, NodeCancelled,
)

raise NodeInputError("voxel_size must be > 0",
                     port="voxel_size", details={"got": -0.1})
```

The streaming WebSocket emits `error_payload = {code, message, port,
node_id, details}`; the editor renders an inline badge and disclosure
tooltip. Untyped exceptions still don't crash the runtime — they're
folded into a `NodeRuntimeError` with code `"internal_error"`.

## Cancellation

A node that runs a long loop should poll `ctx.is_interrupted` and exit
early when it returns True:

```python
for chunk in stream_chunks():
    if ctx.is_interrupted:
        return {"control_out": None, "result": partial}
    consume(chunk)
```

For subprocess-based nodes, register the process with
`ctx.register_subprocess(proc)`; the cancellation controller will send
SIGTERM on cancel.

## Plugin contract

A plugin package contributes types, nodes, validators, and
visualisers. The minimum:

```toml
# packages/stride-foo/pyproject.toml

[project]
name = "stride-foo"
dependencies = ["stride-core", "numpy>=1.24"]

[project.entry-points."stride.plugins"]
foo = "stride_foo:register"
```

```python
# packages/stride-foo/src/stride_foo/__init__.py
from .nodes import register
__all__ = ["register"]
```

The `register()` function may be a no-op — registration happens
automatically when the package's `nodes` module is imported (via the
`@register_node` decorator). Importing `stride_foo` from the entry
point is what triggers registration.

## Testing

```python
# backend/tests/test_foo.py

from app.runner import GraphExecutor

def test_foo_add() -> None:
    graph = {
        "nodes": [
            {"id": "add", "type": "foo.add",
             "input_values": {"a": 2.0, "b": 3.0}},
        ],
        "links": [],
        "output_nodes": [{"node_id": "add", "port": "sum", "alias": "out"}],
    }
    assert GraphExecutor(graph).run()["outputs"]["out"] == 5.0
```

The runner exercises the full prepare → forward → teardown cycle and
the typed-error contract, so a graph-level test is usually sufficient.
For more targeted tests of `validate_inputs`, instantiate the node
directly and call the hook.

## Best practices

- One node = one responsibility. Add a `convert.*` node when you find
  yourself reaching for a "transform inside another node".
- Always declare a `cache_policy` — `"disabled"` for time-varying or
  side-effecting nodes, `"auto"` (default) otherwise.
- Use the canonical type factories from `stride_core.typesystem`. Don't
  redefine `bbox3d` or `image` locally; the type system uses
  structural subtyping and any drift breaks cross-package wiring.
- Prefer `t_<kind>()` over `t_any()`. The Phase 5 contract is that
  `t_any()` is reserved for documented in-process opaque handles
  (e.g. supervision.Detections) — every other use is a code-review
  red flag.

## See also

- [Type System](../architecture/type-system.md)
- [Execution Engine](../architecture/execution-engine.md)
- [Visualizers](../architecture/visualizers.md)
- [Unified design doc](../architecture/unified-type-system-and-ux.md)
