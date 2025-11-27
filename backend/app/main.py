from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .nodes import list_node_types
from .runner import GraphExecutionError, GraphExecutor, NodeStatus

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = (BASE_DIR.parent.parent / "frontend" / "dist").resolve()
INDEX_FILE = FRONTEND_DIR / "index.html"

app = FastAPI(title="LiGuard Web Graph Runtime")

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", response_class=FileResponse)
async def serve_client() -> FileResponse:
    if not INDEX_FILE.exists():
        raise HTTPException(404, "Frontend bundle missing")
    return FileResponse(INDEX_FILE)


@app.get("/api/node-types")
async def get_node_types() -> list[Dict[str, Any]]:
    return list_node_types()


@app.post("/api/run-graph")
async def run_graph(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute graph synchronously (legacy endpoint)."""
    try:
        graph_definition = payload.get("graph", payload)
        options = payload.get("options", {})
        graph_executor = GraphExecutor(graph_definition, options=options)
        return graph_executor.run()
    except GraphExecutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/run-graph-async")
async def run_graph_async(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute graph with parallel execution."""
    try:
        graph_definition = payload.get("graph", payload)
        options = payload.get("options", {})
        graph_executor = GraphExecutor(graph_definition, options=options)
        return await graph_executor.run_async()
    except GraphExecutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/execution-plan")
async def get_execution_plan(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Get execution plan without running."""
    try:
        graph_definition = payload.get("graph", payload)
        options = payload.get("options", {})
        graph_executor = GraphExecutor(graph_definition, options=options)
        return graph_executor.get_execution_plan()
    except GraphExecutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def serialize_event(event) -> str:
    """Serialize an ExecutionEvent to JSON."""
    data = {
        "event_type": event.event_type,
        "execution_id": event.execution_id,
        "timestamp": event.timestamp,
    }
    
    optional_fields = [
        "node_id", "node_type", "status", "outputs", "logs",
        "duration_ms", "error", "level", "progress", "total_nodes",
        "completed_nodes", "execution_plan", "levels"
    ]
    
    for field in optional_fields:
        value = getattr(event, field, None)
        if value is not None:
            if isinstance(value, NodeStatus):
                value = value.value
            data[field] = value
    
    return json.dumps(data)


@app.websocket("/ws/run-graph")
async def websocket_run_graph(websocket: WebSocket):
    """WebSocket endpoint for streaming graph execution."""
    await websocket.accept()
    
    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            
            try:
                graph_definition = payload.get("graph", payload)
                options = payload.get("options", {})
                graph_executor = GraphExecutor(graph_definition, options=options)
                
                async for event in graph_executor.run_streaming():
                    await websocket.send_text(serialize_event(event))
                    
                final_result = {
                    "event_type": "result",
                    "execution_id": graph_executor.execution_id,
                    "outputs": graph_executor.outputs,
                    "trace": [
                        {
                            "node_id": r.node_id,
                            "type": r.node_type,
                            "outputs": r.outputs,
                            "logs": r.logs,
                            "duration_ms": r.duration_ms,
                            "level": r.level,
                        }
                        for r in graph_executor.execution_trace
                    ],
                    "stats": graph_executor._calculate_stats(
                        graph_executor._total_execution_time_ms,  # Use actual wall-clock time!
                        graph_executor._max_parallelism
                    ).__dict__,
                    "levels": graph_executor._levels,
                }
                await websocket.send_text(json.dumps(final_result))
                
            except GraphExecutionError as exc:
                error_response = {
                    "event_type": "error",
                    "error": str(exc),
                }
                await websocket.send_text(json.dumps(error_response))
            except Exception as exc:
                error_response = {
                    "event_type": "error", 
                    "error": f"Unexpected error: {str(exc)}",
                }
                await websocket.send_text(json.dumps(error_response))
                
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
