# LiGuard Web Prototype

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

1. Create a virtual environment (recommended) and install the backend:
   ```bash
   cd backend
   python -m venv .venv
   .venv/Scripts/activate
   pip install -r requirements.txt
   ```
2. Run the backend:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
3. Open `http://127.0.0.1:8000` in your browser and click **Run sample graph**.

You can also validate the runner directly:

```bash
cd backend
.venv/Scripts/activate
python -m app.test_graph
```

## Architecture notes

- **Execution plan**: The backend builds a topological order (Kahn's algorithm),
  partitions nodes into device-aligned execution units, and logs the trace for
  each node with the assigned device hint.
- **Node model**: Each node declares `input_ports`, `output_ports`, and a
  `forward()` implementation. The two constant nodes inherit from a shared
  `BaseNumberNode`, while the addition node demonstrates a GPU hint.
- **Device placement**: The scheduler honors explicit `device_hint` values
  (`cpu` or `gpu`) and otherwise defaults to a heuristic (math nodes prefer GPU).
- **Frontend to backend communication**: The browser POSTs JSON graphs, displays
  the returned outputs, and exposes the execution trace to prove the pipeline.

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

