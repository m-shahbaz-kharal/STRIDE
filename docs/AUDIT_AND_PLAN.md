# LiGuard DT Audit & Upgrade Plan

This doc captures the current state, key risks, and the proposed architecture before large-scale changes. It is intentionally concise so we can execute quickly.

## Audit: Current State & Gaps
- **Backend runtime**: FastAPI + `GraphExecutor` with level-based scheduling and a simple cache. Graph schema is implicit (`nodes`, `links`, `output_nodes`), lacks versioning, type-checking, or validation beyond missing ports/ids. Errors are stringly-typed; no structured error model or diagnostics. Caching is global, unbounded, and hashes raw inputs without type awareness or TTL.
- **Node system**: Nodes are classes with ad-hoc class attributes (`input_ports`, `output_ports`, `params_schema`, optional type hints). Registry is a global dict populated via module imports; no plugin loading, versioning, migrations, or separation of definition vs runtime implementation. Port types are arbitrary strings and unenforced at runtime.
- **APIs**: `GET /api/node-types` mirrors the loose registry; `POST /api/run-graph` accepts unvalidated payloads; WebSocket streaming reuses the same contract. No schema validation, no IR version, and no way to request capabilities/types.
- **Frontend editor**: React Flow with a single ~2k line `App.tsx` handling canvas, selection, connections, execution, palette, and panels. State is local-only; no shared store or clear separation between UI state, graph IR, and execution state. Connection validation is string-based, tied to current port metadata, and there is no notion of control vs data edges.
- **Type system**: Effectively “free-form strings”. No canonical type ids, no structured primitives/containers, no serialization contract, and no shared type utilities between front/back.
- **Nodes shipped**: Mostly demo/test math/util nodes plus camera/streaming nodes. No programming constructs (variables, control flow, functions), no typed errors, and no standard outputs for display/logging.
- **Tooling**: No linting/formatting config, no tests, no module boundaries, and minimal docs for adding nodes.

## Proposed Architecture (Target State)
Goals: typed, modular, plugin-friendly; clear separation of graph model, editor UI, and execution runtime; “node SDK” with versioned definitions and migrations; first-class programming constructs.

1) **Canonical Graph IR (shared front/back)**
   - `GraphDocument` with `version`, `metadata`, `nodes`, `edges`, `outputs`, `options`.
   - `NodeInstance`: `id`, `definition` (`type`, `version`), `label`, `params`, optional `annotations` (breakpoints, device, tags), and optional port-level overrides.
   - `Edge`: `from` `{node, port, kind}`, `to` `{node, port, kind}`, optional `guard`/`condition` for control edges. Distinguish **data edges** from **control edges**.
   - `OutputBinding`: `{node_id, port, alias}`.
   - JSON Schema validation for inbound API payloads and saved graphs; include IR `version` for migrations.

2) **Type System**
   - Primitives: `number`, `string`, `boolean`, `null`.
   - Containers: `list<T>`, `map<string, T>`, `tuple`, `option<T>`.
   - Structured: `record` with named fields; `enum` (string-valued).
   - Flex: `any`, `unknown` (unknown requires explicit casts/guards).
   - Numeric extended: `tensor` (dtype, shape, device hint) to future-proof ML nodes.
   - Portable `TypeDescriptor` + helpers for compatibility checks, defaulting, serialization, and UI badges. Shared library in both stacks.

3) **Node Definition Schema (single source of truth)**
   - Fields: `type`, `version`, `display_name`, `category`, `summary`, `description`, `tags`, `icon`.
   - Ports: `inputs[]` / `outputs[]` with `name`, `type` (`TypeDescriptor`), `required`, `default`, `variadic?`, `ui` (label, tooltip, group).
   - Params: JSON-schema-like `params` with defaults and validation rules.
   - Validation: compile-time rules (e.g., port constraints, param ranges) and runtime contract description.
   - Migrations: `up(from_version) -> NodeInstance` to upgrade saved graphs.
   - Registry metadata: stability (`experimental/stable`), cacheability, purity, side-effects.

4) **Backend Node SDK & Registry**
   - `NodeSpec` dataclass encapsulating the schema above.
   - Base classes: `PureNode`, `EffectNode`, `ControlNode`, `FunctionNode` with `run(self, inputs, ctx) -> outputs` and optional async support.
   - `ExecutionContext` with structured logger, metrics, cancellation token, and scoped variables.
   - Registry that loads plugins from `nodes/` modules or external entry points; exposes `list_definitions()`, `get_runner(type, version)`, `migrate(node_instance)`.
   - Versioned API responses: `GET /api/node-definitions` returns the schema; `GET /api/types` exposes type palette.

5) **Execution Engine**
   - Compiler: validate graph against schema/types, expand defaults, bind functions/variables, build execution plan (levels + control flow).
   - Scheduler: dataflow with control-edge awareness; support bounded loops (`for`), conditional branches, and function calls (subgraphs).
   - Deterministic variable scope: graph/global vs function/local vs loop iteration; explicit variable nodes for declare/set/get with type checks.
   - Error model: structured `ExecutionError {code, message, node_id, details}`; propagate to events and HTTP responses.
   - Caching: type-aware cache keys, optional TTL/size limits, per-node cache policy.
   - Instrumentation: per-node timings, cache hits, warnings; consistent event envelope for WebSocket and HTTP.

6) **Frontend Architecture**
   - Split into domains: `core/graph` (IR + selectors), `core/types`, `sdk/nodes` (definition adapters), `state` store (Zustand or reducer) for graph + execution state, `ui` components (canvas, inspector, palette, outputs).
   - Consume the same `NodeDefinition` schema; auto-generate forms for params and port badges from `TypeDescriptor`.
   - Connection validation uses shared type compatibility; highlight control vs data edges; render function/loop scopes distinctly.
   - Graph serialization/deserialization aligned with backend IR; migrations applied client-side for older saves.
   - Execution overlay separated from editor (clear boundary between edit mode and run state).

7) **Programming Constructs (as first-class nodes)**
   - Variables: declare/set/get with scopes and defaults; type-enforced.
   - Expressions/Operators: arithmetic, comparison, boolean, string, container ops mapped to type system.
   - Control flow: `If/Else`, `Switch`, `Guard`, control edges; loops via `For Loop` (first/last index), `Repeat n`, safe `While` with max-iterations.
   - Functions: deferred (custom functions to be revisited later).
   - Errors: `Raise`, `Try/Catch`, or `Result`-style nodes with consistent runtime behavior.

8) **Tooling & Standards**
   - Enforce formatting/linting (ruff/black for backend, eslint+prettier for frontend), strict TS, and typed Python where feasible.
   - Logging utilities with node-scoped context; consistent IDs and timestamps.
   - Docs: “How to create a new node” guide driven by the Node Definition schema and SDK, plus migration notes.

## Near-Term Implementation Steps (proposed order)
1) Land shared type/IR models (Python + TS) and schema validation; wire API to serve typed definitions. Remove/quarantine demo nodes that don’t meet the schema. **[DONE]**
2) Introduce Node SDK + registry with versioning; port existing math/constant nodes; drop or quarantine camera/selenium-heavy nodes until wrapped correctly. **[DONE]**
3) Rework executor with typed compile/plan, structured errors, cache policy, and control/data edge awareness. **[MOSTLY: control/data awareness, cache policy flag, error codes/events]**
4) Refactor frontend into modular domains, consume new definitions, and rebuild palette/inspector/connection logic around the shared type system. **[IN PROGRESS: definitions normalized, type-aware validation/colors/dash control edges; modularization still pending]**
5) Add core programming nodes (variables, expressions, control flow) and execution support for loops/conditionals. **[ADDED: variables, comparisons/logic, if/else, for loop (pins only); DEFERRED: functions/subgraph call]**
6) Polish UX (scopes, control edges), logging, and docs for node authors. **[IMPROVED: control edge labels, docs added, error codes surfaced; further logging polish possible]**
