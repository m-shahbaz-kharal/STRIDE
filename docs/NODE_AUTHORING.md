# Node Authoring Guide

This project uses a typed, versioned Node SDK shared across frontend and backend. Use this guide to add new nodes or update existing ones.

## Core concepts
- **NodeSpec** (`backend/app/node_spec.py`): single source of truth for a node’s definition (type id, version, category, ports, params, UI metadata, cache policy).
- **TypeDescriptor** (`backend/app/typesystem.py`): structured types (`int`, `float`, `string`, `boolean`, `null`, `control`, `any`, `unknown`, containers, tensor). `int` widens to `float`; `control` is used for sequencing edges.
- **Registry**: Nodes are registered via `@register_node(spec)` in `backend/app/nodes`. Frontend consumes `/api/node-definitions`.
- **Ports**: Declare data ports and (optionally) `control` ports. Control edges enforce ordering but do not carry data.
- **Defaults**: Inputs can be optional; if no link is provided, `input_values` or port defaults are used.
- **Cache policy**: Set `cache_policy="disabled"` on a NodeSpec to prevent caching for side-effecting nodes.

## Adding a new node (backend)
1) Create a spec in `backend/app/nodes/<domain>.py`:
   ```python
   from ..node_spec import NodeSpec, PortSpec, ParamSpec
   from ..typesystem import t_float, t_control

   MY_SPEC = NodeSpec(
       type="core.math.myop",
       version="1.0.0",
       display_name="My Op",
       category="Math",
       summary="Does something",
       inputs=[PortSpec(name="a", type=t_float())],
       outputs=[PortSpec(name="out", type=t_float())],
       params={"scale": ParamSpec(name="scale", type="float", default=1.0)},
       cache_policy="default",  # or "disabled"
   )
   ```
2) Implement the node with `@register_node(MY_SPEC)` and a `forward(inputs, ctx)` method that returns a dict matching `outputs`.
3) Import the module in `backend/app/nodes/__init__.py` so it registers.
4) (Optional) Add tests or an entry in `backend/app/test_graph.py` to exercise it.

## Control vs data edges
- Use `t_control()` ports to enforce ordering (e.g., variable set/get, function sequencing). Frontend renders control edges dashed/orange.
- Data edges remain type-checked using `TypeDescriptor.is_assignable_to`.

## Functions/subgraphs
- Custom functions are deferred; `core.fn` nodes have been removed and will be revisited later.

## Frontend expectations
- `/api/node-definitions` is preferred; it includes typed ports. Legacy `/api/node-types` still works.
- Palette renders ports using `type` color/label. Control edges are dashed.

## Testing nodes
- Run sample graph: `python -m app.test_graph` from `backend`.
- For manual calls, POST `graph` payload to `/api/run-graph` or use WebSocket `/ws/run-graph`.
- Keep `params_schema` defaults sensible so newly dropped nodes in the editor have valid initial params.

## Versioning & migrations
- Bump `version` when changing port shapes/semantics.
- For breaking changes, add migration logic (future work) and keep backward-compatible aliases when possible.
