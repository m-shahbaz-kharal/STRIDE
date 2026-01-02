# LiGuard DT

This repository contains the minimal prototype for a node-graph runtime inspired
by Unreal Blueprints / ComfyUI + a GPU/CPU scheduler that fits into the
conceptual architecture described in the project brief.

## What is in this prototype

- **Backend** (`backend/app`): FastAPI service that exposes a `/api/run-graph`
  endpoint, a `GraphExecutor` that compiles a JSON graph into execution units,
  and the minimal node family described in the requirements:
  `BaseNumberNode` → `ConstantNumberNode` & `MirrorNumberNode`, plus `AdditionNode`.
- **Front-end** (`frontend/public/index.html`): Static page that pushes the sample
  graph to the Python server, showing the output values and the execution trace.
- **Test graph** (`backend/app/test_graph.py`): A runnable script that exercises the
  same a+b=c graph so you can verify the scheduler outside of the UI.

## Getting started

1. Create a virtual environment (recommended) and install the backend dependencies:
   ```bash
   cd backend
   python -m venv .venv
   .venv/Scripts/activate
   pip install -r requirements.txt
   ```
2. Install the React frontend dependencies and run the dev server:
   ```bash
   cd ../frontend
   npm install
   npm run dev
   ```
   The dev server proxies API calls to `http://127.0.0.1:8000` by default so you can iterate on the editor while the backend is running.
3. For a production-backed experience, build the frontend bundle (this writes to `frontend/dist`) and then launch the backend so it can serve the static assets:
   ```bash
   npm run build
   cd ../backend
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

You can also validate the runner directly:

```bash
cd backend
.venv/Scripts/activate
python -m app.test_graph
```

## Frontend experience

- React + React Flow powers a Blueprint-style canvas with draggable nodes, typed ports, and an inspector panel that exposes device preference, params, and breakpoints.
- Execution controls support Run Graph, Run Selection, and Step while capturing live logs, execution units, and tensor-like output summaries returned from the backend.
- The palette is populated directly from the backend registry (`/api/node-types`) so the UI always reflects the nodes available to the scheduler, and every node highlights the last device/resolution it ran on for quick debugging.

## Backend APIs

- `GET /api/node-types` exposes every registered node’s metadata (ports, descriptions, param schema, defaults) so the frontend can render a consistent palette.
- `POST /api/run-graph` still accepts a graph definition, but it also looks for two optional helpers: an embedded `options` object (`mode`, `target_nodes`, `breakpoints`, `max_steps`) and a `graph` wrapper. The executor now respects selection-only runs, breakpoints, and stepping hints from the UI.

## Architecture notes

- **Execution plan**: The backend still topologically sorts nodes, but the planner can now restrict execution to a selection, honor breakpoints, and stop after a fixed number of steps thanks to the new executor options.
- **Node metadata**: Each node class declares ports, documentation, and a parameter schema that feeds the frontend inspector (the node registry also returns schema defaults so the React Flow nodes are initialized sensibly).
- **Device placement**: Explicit `device_hint` values (`cpu`, `gpu`) are honored while math nodes default to GPU. Nodes can be tagged with breakpoints from the UI, and the executor halts before hitting them.
- **Frontend / backend surface**: The React UI POSTs `{"graph": {...}, "options": {...}}` to `/api/run-graph`, then displays the returned `outputs`, `trace`, and `units` (which describe the device-aligned execution chunks).

## Roadmap ideas

- Plug in NVIDIA fVDB-backed nodes (VDB grids, sparse convolutions, mesh/export).
- Improve scheduler with CUDA streams, tensor streaming via WebSocket, and
  pinned-memory H2D/D2H transfers.
- Add debug hooks: breakpoints, step-by-step execution, tensor inspector
  previews (images/3D).
- Package the backend into a Docker container with pinned compute resources; the
  front-end can stay static and talk to the local container via HTTP/WebSocket.

This prototype is deliberately minimal but structured so it can scale into the
full node-rich, GPU-first application described in the brief.

