# STRIDE

A visual node-graph runtime for creating data processing pipelines, inspired by
Unreal Blueprints and ComfyUI. Features a React-based canvas editor, FastAPI backend,
and modular execution engine.

## Features

- **Unified type system** with structural subtyping: every kind (image,
  bbox2d, detections2d, pointcloud, depthmap, scene3d, …) carries a
  fixed record schema declared once in `stride-core` and reused
  across every plugin package.
- **Conversion graph** (`stride-converters`): the editor consults a
  one-hop converter index at drag-time and offers a single-click
  "Insert <converter>" action whenever a `convert.*` node would bridge
  an otherwise-incompatible edge.
- **Lifecycle hooks**: `prepare` / `forward` / `teardown` per run, plus
  declarative `PortSpec.constraints` enforced server-side and consumed
  client-side to render bounded widgets (sliders, enums, file
  pickers).
- **Run-scoped resources**: model sessions and live streams live on
  `ExecutionContext.acquire_run_resource`; nothing leaks across runs,
  no module-level caches.
- **Typed errors**: every node failure surfaces as a structured
  `error_payload` (code, message, port, details) and renders inline
  in the editor with a disclosure tooltip.
- **Visual graph editor**: React Flow canvas with draggable nodes,
  type-aware connection validation, real-time execution highlights,
  and inline node error UI.
- **Streaming execution**: WebSocket-based per-node events for live
  progress, log, and result updates.
- **Parallel branch execution** with proper error isolation.
- **Caching**: node-level result caching with hash-based invalidation.
- **Extensible plugin system**: every node ships in a `stride-*`
  package registered through Python entry-points; the runtime
  auto-discovers plugins on startup.
- **Visualizer registry**: per-kind dashboard widgets (Scene3D,
  ImageWidget, …); future packages contribute custom visualisers via
  Vite-time discovery (see `docs/architecture/visualizers.md`).

## Quick Start

### Prerequisites

- Python 3.11+ with [uv](https://github.com/astral-sh/uv) package manager
- Node.js 18+ with npm

### Backend Setup

```bash
cd backend
uv sync                                          # Install dependencies
uv run uvicorn app.main:app --reload --port 8000 # Start dev server
```

### Frontend Setup

```bash
cd frontend
npm install      # Install dependencies
npm run dev      # Start dev server on http://localhost:5173
```

The frontend proxies API calls to `http://127.0.0.1:8000` automatically.

## Project Structure

```
STRIDE/
├── backend/
│   ├── app/
│   │   ├── engine/              # Graph analysis utilities
│   │   │   ├── graph_builder.py # Node/link construction, topological sort
│   │   │   └── control_flow.py  # Loop/branch detection
│   │   ├── executor/            # Modular execution engine
│   │   │   └── cancellation.py  # Thread-safe cancellation control
│   │   ├── nodes/               # Node implementations by category
│   │   ├── routers/             # FastAPI route handlers
│   │   ├── runner.py            # Core graph executor
│   │   ├── execution.py         # Execution primitives & events
│   │   └── main.py              # FastAPI application
│   └── tests/                   # Pytest test suite
├── frontend/
│   ├── src/
│   │   ├── components/          # React components
│   │   ├── hooks/               # Custom React hooks
│   │   │   ├── useGraphExecution.ts     # WebSocket execution
│   │   │   ├── useGraphDependencies.ts  # Dependency tracking
│   │   │   ├── useConnectionValidation.ts
│   │   │   └── ...              # Additional hooks
│   │   ├── graph/               # Graph utilities
│   │   └── App.tsx              # Main application
│   └── public/
└── packages/
    └── stride-core/            # Shared node definitions package
```


## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/node-definitions` | Get all available node types and specs |
| `GET` | `/api/converters` | Converter index (Phase 5 §4.7) — `(from_kind, to_kind)` lookup |
| `POST` | `/api/run-graph` | Execute a graph synchronously |
| `WS` | `/ws/run-graph` | Execute graph with streaming events |
| `POST` | `/api/executions/{id}/cancel` | Cancel a running execution |
| `POST` | `/api/executions/{id}/cancel/{node}` | Cancel a specific node |
| `POST` | `/api/cache/clear` | Clear all cached results |
| `GET` | `/api/graphs` | List saved graphs |
| `POST` | `/api/graphs` | Create a new graph |

## Development

### Running Tests

```bash
cd backend
uv run pytest tests/ -v
```

### Building for Production

```bash
# Frontend build
cd frontend
npm run build  # Outputs to dist/

# Backend can be deployed with uvicorn
cd backend
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_URL` | (proxy) | Backend API URL for production builds |

## Architecture

### Execution Engine

The `GraphExecutor` in `runner.py` handles:
- **Topological Sorting**: Determines execution order respecting dependencies
- **Parallel Execution**: Runs independent branches concurrently
- **Error Isolation**: Errors in one branch don't stop independent branches
- **Caching**: Node-level result caching with hash-based invalidation

### Node System

Nodes are defined using `NodeSpec` with:
- Input/output port definitions with type information
- Parameter schemas for runtime configuration
- Execution method (`forward`) that processes inputs

### Frontend State

Key React hooks:
- `useGraphExecution`: WebSocket-based execution with streaming events
- `useNodeLibrary`: Manages available node types from backend
- `useConnectionValidation`: Type-safe port connection validation
- `useUndoRedo`: Graph state history management

## License

See LICENSE file for details.
