from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .nodes import list_node_types
from .runner import GraphExecutionError, GraphExecutor, NodeStatus
from .nodes.camera import STREAM_MANAGER

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


@app.post("/api/cache/clear")
async def clear_cache() -> Dict[str, Any]:
    """Clear the execution cache."""
    cleared = GraphExecutor.clear_cache()
    return {"cleared": cleared, "message": f"Cleared {cleared} cached entries"}


@app.post("/api/cache/clear/{node_type:path}")
async def clear_cache_by_type(node_type: str) -> Dict[str, Any]:
    """Clear the execution cache for a specific node type."""
    cleared = GraphExecutor.clear_cache_by_type(node_type)
    return {"cleared": cleared, "node_type": node_type, "message": f"Cleared {cleared} cached entries for {node_type}"}


@app.get("/api/cache/stats")
async def get_cache_stats() -> Dict[str, Any]:
    """Get cache statistics."""
    return {"size": GraphExecutor.get_cache_size()}


@app.get("/api/streams/{stream_id}/frame")
async def get_stream_frame(stream_id: str) -> Response:
    """Fetch the latest JPEG frame for a running stream."""
    try:
        worker = STREAM_MANAGER.get_stream(stream_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Stream not found")

    frame = worker.latest_frame(timeout=0.1)
    if frame is None:
        return Response(status_code=204)

    import cv2

    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    ok, buffer = cv2.imencode(".jpg", frame_rgb, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to encode frame")
    return StreamingResponse(
        iter([buffer.tobytes()]),
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
        },
    )


@app.post("/api/executions/{execution_id}/cancel")
async def cancel_execution(execution_id: str) -> Dict[str, Any]:
    """Cancel an in-flight execution."""
    cancelled = GraphExecutor.cancel_execution(execution_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Execution not found or already finished")
    return {"execution_id": execution_id, "cancelled": cancelled}


@app.post("/api/executions/{execution_id}/cancel/{node_id}")
async def cancel_node(execution_id: str, node_id: str) -> Dict[str, Any]:
    """Cancel a specific node inside an in-flight execution."""
    cancelled = GraphExecutor.cancel_node(execution_id, node_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Execution not found or already finished")
    return {"execution_id": execution_id, "node_id": node_id, "cancelled": cancelled}


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
        "completed_nodes", "execution_plan", "levels", "from_cache"
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
                            "from_cache": r.from_cache,
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
