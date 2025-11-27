from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .runner import GraphExecutionError, GraphExecutor

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = (BASE_DIR.parent.parent / "frontend" / "public").resolve()
INDEX_FILE = FRONTEND_DIR / "index.html"

app = FastAPI(title="LiGuard Web Graph Runtime")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", response_class=FileResponse)
async def serve_client() -> FileResponse:
    if not INDEX_FILE.exists():
        raise HTTPException(404, "Frontend bundle missing")
    return FileResponse(INDEX_FILE)


@app.post("/api/run-graph")
async def run_graph(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        graph_executor = GraphExecutor(payload)
        return graph_executor.run()
    except GraphExecutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

