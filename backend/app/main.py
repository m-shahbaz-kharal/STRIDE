from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .auth import get_current_user, resolve_user_for_token
from .db import SessionLocal, init_db
from .models import User
from .nodes import list_node_types, list_node_definitions
from .runner import GraphExecutionError, GraphExecutor, NodeStatus
from stride_fl511.nodes import get_active_stream
from .routers import auth as auth_router
from .routers import graphs as graphs_router


# Maximum request body size (JSON payload) accepted by the API. Defaults
# to 16 MiB which covers graphs of a few thousand nodes plus modest
# embedded payloads; tune via env for embedded-image-heavy use cases.
MAX_BODY_BYTES = int(os.getenv("STRIDE_MAX_BODY_BYTES", str(16 * 1024 * 1024)))

# Maximum single WebSocket message size. Same default as the HTTP cap.
MAX_WS_MESSAGE_BYTES = int(os.getenv("STRIDE_MAX_WS_MESSAGE_BYTES", str(16 * 1024 * 1024)))

# Maximum number of concurrent graph executions per WebSocket connection.
MAX_WS_CONCURRENT_EXECUTIONS = int(os.getenv("STRIDE_MAX_WS_CONCURRENT_EXECUTIONS", "4"))


class _LegacyWSKeepaliveFilter(logging.Filter):
    """Drop the harmless 'keepalive ping failed' AssertionError emitted by
    websockets.legacy during graceful close races. Real WebSocket errors still
    surface — we only suppress this specific known-harmless trace."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "keepalive ping failed" in msg:
            return False
        if record.exc_info:
            exc_type = record.exc_info[0]
            # The traceback frame includes "_drain_helper" and the assertion
            # text — match either marker so we catch the trace whether or not
            # the message has been formatted yet.
            if exc_type is AssertionError:
                tb_text = ""
                exc_value = record.exc_info[1]
                if exc_value is not None:
                    tb_text = repr(exc_value)
                if (
                    "keepalive" in msg.lower()
                    or "_drain_helper" in tb_text
                    or "_drain_helper" in (record.pathname or "")
                ):
                    return False
        return True


_KEEPALIVE_FILTER = _LegacyWSKeepaliveFilter()

# Attach to every logger in the websockets namespace, including the root one
# (per-connection child loggers inherit from the root's ancestors), and re-attach
# whenever a new logger appears under that namespace by hooking the manager.
def _install_keepalive_filter() -> None:
    """Attach the filter at every level of the websockets logger tree.

    websockets creates a child logger per connection (e.g.
    ``websockets.server.<id>``) that bypasses filters set on a sibling. We
    install the filter on the root ``websockets`` logger and on every
    already-known child, then monkey-patch ``Logger.callHandlers`` once at
    module load — cheap, narrow, and keeps real errors visible.
    """
    base_names = (
        "websockets",
        "websockets.server",
        "websockets.client",
        "websockets.protocol",
        "websockets.legacy",
        "websockets.legacy.protocol",
        "websockets.legacy.server",
        "uvicorn.error",
        "uvicorn",
    )
    for name in base_names:
        logger = logging.getLogger(name)
        if _KEEPALIVE_FILTER not in logger.filters:
            logger.addFilter(_KEEPALIVE_FILTER)


_install_keepalive_filter()

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = (BASE_DIR.parent.parent / "frontend" / "dist").resolve()
INDEX_FILE = FRONTEND_DIR / "index.html"


def _json_serializer(obj: Any) -> Any:
    """Custom JSON serializer for objects that are not JSON serializable."""
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    # numpy arrays/scalars
    if hasattr(obj, "dtype"):
        return obj.tolist()
    return str(obj)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="STRIDE Graph Runtime", lifespan=_lifespan)

_cors_origins_raw = os.getenv("STRIDE_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
_cors_origins = [origin.strip() for origin in _cors_origins_raw.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class _BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject HTTP requests whose declared ``Content-Length`` exceeds the cap.

    Streaming bodies without an advertised length are still bounded by
    Starlette's per-receive buffer; this guard catches the common case
    where a curl one-liner pushes a multi-gigabyte payload.
    """

    def __init__(self, app, max_bytes: int) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self._max_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": f"Request body too large (max {self._max_bytes} bytes)"},
                    )
            except ValueError:
                pass
        return await call_next(request)


app.add_middleware(_BodySizeLimitMiddleware, max_bytes=MAX_BODY_BYTES)

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

app.include_router(auth_router.router)
app.include_router(graphs_router.router)


@app.get("/", response_class=FileResponse)
async def serve_client() -> FileResponse:
    if not INDEX_FILE.exists():
        raise HTTPException(404, "Frontend bundle missing")
    return FileResponse(INDEX_FILE)


@app.get("/api/health")
async def health_check() -> Dict[str, Any]:
    """Liveness probe. Returns plain JSON, no DB hop, no auth.

    Use this for load-balancer health checks and container probes;
    keep it cheap and unauthenticated so a misconfigured token can't
    take the deployment off the LB.
    """
    return {"status": "ok"}


@app.get("/api/ready")
async def ready_check() -> Dict[str, Any]:
    """Readiness probe. Touches the DB so the LB only routes traffic
    once the database is reachable.
    """
    from sqlalchemy import text
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"db not ready: {exc}") from exc
    finally:
        db.close()


@app.get("/api/node-types")
async def get_node_types(current_user: User = Depends(get_current_user)) -> list[Dict[str, Any]]:
    return list_node_types()


@app.get("/api/node-definitions")
async def get_node_definitions(current_user: User = Depends(get_current_user)) -> list[Dict[str, Any]]:
    """Typed node definition schema (preferred)."""
    return list_node_definitions()


@app.get("/api/converters")
async def get_converters(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Index of every registered ``convert.*`` node.

    The frontend fetches this once at app start to build a single-hop
    lookup ``Map<from_kind, Map<to_kind, ConverterSpec[]>>`` it then
    consults during connection drag to surface "insert converter"
    suggestions for invalid edges. See design doc §4.7.
    """
    converters = []
    for spec in list_node_definitions():
        node_type = spec.get("node_type") or spec.get("type")
        if not isinstance(node_type, str) or not node_type.startswith("convert."):
            continue
        meta = spec.get("metadata") or {}
        from_kind = meta.get("convert_from")
        to_kind = meta.get("convert_to")
        if not from_kind or not to_kind:
            continue
        converters.append({
            "node_type": node_type,
            "display_name": spec.get("display_name") or node_type,
            "from_kind": from_kind,
            "to_kind": to_kind,
            "cost": meta.get("cost", 5),
            "suggested": bool(meta.get("suggested", True)),
            "summary": spec.get("summary", ""),
            "category": spec.get("category", "Convert"),
            "icon": spec.get("icon", ""),
            "input_ports": spec.get("input_ports") or [],
            "output_ports": spec.get("output_ports") or [],
        })
    converters.sort(key=lambda c: (c["from_kind"], c["to_kind"], c["cost"], c["node_type"]))
    return {"converters": converters}


@app.post("/api/run-graph")
async def run_graph(
    payload: Dict[str, Any],
    current_user: User = Depends(get_current_user),
) -> Response:
    """Execute graph synchronously (legacy endpoint)."""
    try:
        graph_definition = payload.get("graph", payload)
        options = payload.get("options", {})
        graph_executor = GraphExecutor(graph_definition, options=options)
        result = graph_executor.run()
        return Response(content=json.dumps(result, default=_json_serializer), media_type="application/json")
    except GraphExecutionError as exc:
        return Response(
            content=json.dumps({"error": str(exc), "code": getattr(exc, "code", "execution_error")}),
            status_code=400,
            media_type="application/json"
        )


@app.post("/api/run-graph-async")
async def run_graph_async(
    payload: Dict[str, Any],
    current_user: User = Depends(get_current_user),
) -> Response:
    """Execute graph with parallel execution."""
    try:
        graph_definition = payload.get("graph", payload)
        options = payload.get("options", {})
        graph_executor = GraphExecutor(graph_definition, options=options)
        result = await graph_executor.run_async()
        return Response(content=json.dumps(result, default=_json_serializer), media_type="application/json")
    except GraphExecutionError as exc:
        return Response(
            content=json.dumps({"error": str(exc), "code": getattr(exc, "code", "execution_error")}),
            status_code=400,
            media_type="application/json"
        )


@app.post("/api/execution-plan")
async def get_execution_plan(
    payload: Dict[str, Any],
    current_user: User = Depends(get_current_user),
) -> Response:
    """Get execution plan without running."""
    try:
        graph_definition = payload.get("graph", payload)
        options = payload.get("options", {})
        graph_executor = GraphExecutor(graph_definition, options=options)
        result = graph_executor.get_execution_plan()
        return Response(content=json.dumps(result, default=_json_serializer), media_type="application/json")
    except GraphExecutionError as exc:
        return Response(
            content=json.dumps({"error": str(exc), "code": getattr(exc, "code", "execution_error")}),
            status_code=400,
            media_type="application/json"
        )


@app.post("/api/cache/clear")
async def clear_cache(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Clear the execution cache."""
    cleared = GraphExecutor.clear_cache()
    return {"cleared": cleared, "message": f"Cleared {cleared} cached entries"}


@app.post("/api/cache/clear/{node_type:path}")
async def clear_cache_by_type(
    node_type: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Clear the execution cache for a specific node type."""
    cleared = GraphExecutor.clear_cache_by_type(node_type)
    return {"cleared": cleared, "node_type": node_type, "message": f"Cleared {cleared} cached entries for {node_type}"}

@app.post("/api/cache/clear-nodes")
async def clear_cache_by_nodes(
    payload: Dict[str, Any],
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Clear the execution cache for a list of node ids."""
    node_ids = payload.get("node_ids") or []
    if not isinstance(node_ids, list):
        raise HTTPException(status_code=400, detail="node_ids must be a list")
    normalized_ids = [str(node_id) for node_id in node_ids]
    cleared = GraphExecutor.clear_cache_by_nodes(normalized_ids)
    return {
        "cleared": cleared,
        "node_ids": normalized_ids,
        "message": f"Cleared {cleared} cached entries for {len(normalized_ids)} nodes",
    }


@app.get("/api/cache/stats")
async def get_cache_stats(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Get cache statistics."""
    return {"size": GraphExecutor.get_cache_size()}


@app.get("/api/streams/{stream_id}/frame")
async def get_stream_frame(
    stream_id: str,
    current_user: User = Depends(get_current_user),
) -> Response:
    """Fetch the latest JPEG frame for a running stream."""
    worker = get_active_stream(stream_id)
    if not worker:
        raise HTTPException(status_code=404, detail="Stream not found")

    frame = worker.latest_frame(timeout=0.1)
    if frame is None:
        return Response(status_code=204)

    try:
        import cv2
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="OpenCV not installed for stream encoding") from exc

    # cv2.imencode expects BGR input, so we pass the frame directly
    ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
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
async def cancel_execution(
    execution_id: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Cancel an in-flight execution."""
    cancelled = GraphExecutor.cancel_execution(execution_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Execution not found or already finished")
    return {"execution_id": execution_id, "cancelled": cancelled}


@app.post("/api/executions/{execution_id}/cancel/{node_id}")
async def cancel_node(
    execution_id: str,
    node_id: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
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
        "completed_nodes", "execution_plan", "levels", "from_cache", "error_code", "error_details",
        "branch_id", "is_merge_point", "branches", "merge_points",
    ]
    
    for field in optional_fields:
        value = getattr(event, field, None)
        if value is not None:
            if isinstance(value, NodeStatus):
                value = value.value
            data[field] = value
    
    return json.dumps(data, default=_json_serializer)


def _authenticate_websocket(websocket: WebSocket) -> Optional[User]:
    """Extract a user from a WebSocket connection.

    Browsers can't set custom Authorization headers on the WebSocket
    handshake, so we accept the token from a ``token`` query parameter
    (the conventional pattern). The DB lookup runs synchronously on a
    short-lived session because the WS handler isn't covered by FastAPI's
    Depends machinery.
    """
    token = websocket.query_params.get("token")
    if not token:
        return None
    db = SessionLocal()
    try:
        return resolve_user_for_token(token, db)
    finally:
        db.close()


@app.websocket("/ws/run-graph")
async def websocket_run_graph(websocket: WebSocket):
    """WebSocket endpoint for streaming graph execution."""
    # Authenticate BEFORE accept() so we don't expose any session state to
    # an unauthenticated client.
    user = _authenticate_websocket(websocket)
    if user is None:
        # Code 4001 = "policy violation, unauthorized" by convention.
        await websocket.close(code=4001)
        return
    await websocket.accept()

    # Lock to ensure thread-safe writes to the websocket
    send_lock = asyncio.Lock()

    # Track executors created by this socket so we can cancel them if the
    # connection drops or is forcefully closed.
    active_executors: set[str] = set()

    # Bound concurrent runs per socket so a single client can't exhaust
    # the thread pool by spamming run requests.
    request_semaphore = asyncio.Semaphore(MAX_WS_CONCURRENT_EXECUTIONS)

    async def handle_request(payload: Dict[str, Any]):
        async with request_semaphore:
            await _handle_one_request(payload)

    async def _handle_one_request(payload: Dict[str, Any]):
        graph_executor: GraphExecutor | None = None
        try:
            graph_definition = payload.get("graph", payload)
            options = payload.get("options", {})
            graph_executor = GraphExecutor(graph_definition, options=options)
            active_executors.add(graph_executor.execution_id)

            async for event in graph_executor.run_streaming():
                message = serialize_event(event)
                try:
                    async with send_lock:
                        await websocket.send_text(message)
                except Exception:
                    # Connection likely closed - propagate cancellation to executor
                    graph_executor._cancellation.cancel_all()
                    break
                    
            final_result = {
                "event_type": "result",
                "execution_id": graph_executor.execution_id,
                "outputs": graph_executor.outputs,
                "trace": [
                    {
                        "node_id": r.node_id,
                        "type": r.node_type,
                        "display_name": graph_executor.nodes.get(r.node_id).spec.display_name if graph_executor.nodes.get(r.node_id) else r.node_type,
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
            try:
                async with send_lock:
                    await websocket.send_text(json.dumps(final_result, default=_json_serializer))
            except Exception:
                pass
                
        except GraphExecutionError as exc:
            error_response = {
                "event_type": "error",
                "error": str(exc),
            }
            try:
                async with send_lock:
                    await websocket.send_text(json.dumps(error_response))
            except Exception:
                pass
        except asyncio.CancelledError:
            # Connection dropped or task was cancelled - propagate to executor
            if graph_executor is not None:
                graph_executor._cancellation.cancel_all()
            raise
        except Exception as exc:
            error_response = {
                "event_type": "error",
                "error": f"Unexpected error: {str(exc)}",
            }
            try:
                async with send_lock:
                    await websocket.send_text(json.dumps(error_response))
            except Exception:
                pass
        finally:
            if graph_executor is not None:
                active_executors.discard(graph_executor.execution_id)

    # Keep track of active tasks to prevent garbage collection
    background_tasks = set()

    def _cancel_active_executors() -> None:
        """Signal cancellation to every executor still running on this socket."""
        for execution_id in list(active_executors):
            try:
                GraphExecutor.cancel_execution(execution_id)
            except Exception:
                pass

    try:
        while True:
            data = await websocket.receive_text()
            if len(data) > MAX_WS_MESSAGE_BYTES:
                try:
                    async with send_lock:
                        await websocket.send_text(json.dumps({
                            "event_type": "error",
                            "error": (
                                f"Payload too large ({len(data)} > {MAX_WS_MESSAGE_BYTES} bytes)"
                            ),
                            "error_code": "payload_too_large",
                        }))
                except Exception:
                    pass
                continue
            try:
                payload = json.loads(data)
            except json.JSONDecodeError as exc:
                try:
                    async with send_lock:
                        await websocket.send_text(json.dumps({
                            "event_type": "error",
                            "error": f"Invalid JSON: {exc.msg}",
                            "error_code": "bad_request",
                        }))
                except Exception:
                    pass
                continue

            # Create a background task for each request to allow concurrency
            task = asyncio.create_task(handle_request(payload))
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)

    except WebSocketDisconnect:
        # Tell every executor on this socket to stop, then cancel the
        # asyncio tasks running them. The executor's finally block will
        # tear down resources cleanly.
        _cancel_active_executors()
        for task in background_tasks:
            task.cancel()
    except Exception:
        _cancel_active_executors()
        for task in background_tasks:
            task.cancel()


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True, ws="wsproto")
