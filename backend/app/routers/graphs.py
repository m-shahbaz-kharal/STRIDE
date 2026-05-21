from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..domain.graph_migrations import CURRENT_SCHEMA_VERSION, migrate
from ..models import Graph, User
from ..schemas import GraphCreate, GraphOut, GraphUpdate


router = APIRouter(prefix="/api/graphs", tags=["graphs"])


def _stamp_schema_version(data: dict | None) -> dict | None:
    """Tag a graph payload with the current ``schema_version`` if missing.

    Phase 0 plumbing — pure pass-through for graphs that already declare a
    version. New graphs save with :data:`CURRENT_SCHEMA_VERSION`.
    """
    if not isinstance(data, dict):
        return data
    if "schema_version" not in data:
        # Don't mutate caller's dict.
        data = dict(data)
        data["schema_version"] = CURRENT_SCHEMA_VERSION
    return data


def _migrate_on_load(graph: Graph) -> Graph:
    """Run the migration chain on a graph's stored ``data`` payload.

    Phase 0 is a no-op — :func:`migrate` simply ensures
    ``schema_version`` is present and current. The migrated payload is not
    written back to the database here; persistence happens on the next save.
    """
    if isinstance(graph.data, dict):
        graph.data = migrate(graph.data)
    return graph


@router.get("", response_model=list[GraphOut])
def list_graphs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[GraphOut]:
    """List the caller's graphs, paginated.

    Default page size of 100 covers the realistic UI need (the library
    panel renders ~20 graphs at a time); the ``limit=500`` ceiling caps
    the worst case at a single round-trip without unbounded memory.
    """
    stmt = (
        select(Graph)
        .where(Graph.owner_id == current_user.id)
        .order_by(Graph.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    graphs = db.execute(stmt).scalars().all()
    return [GraphOut.model_validate(_migrate_on_load(graph)) for graph in graphs]


@router.post("", response_model=GraphOut)
def create_graph(
    payload: GraphCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GraphOut:
    graph = Graph(
        owner_id=current_user.id,
        name=payload.name,
        description=payload.description,
        data=_stamp_schema_version(payload.data),
    )
    db.add(graph)
    db.commit()
    db.refresh(graph)
    return GraphOut.model_validate(graph)


@router.get("/{graph_id}", response_model=GraphOut)
def get_graph(
    graph_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GraphOut:
    try:
        graph_uuid = uuid.UUID(graph_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Graph not found") from exc

    graph = db.get(Graph, graph_uuid)
    if not graph or graph.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Graph not found")
    return GraphOut.model_validate(_migrate_on_load(graph))


@router.put("/{graph_id}", response_model=GraphOut)
def update_graph(
    graph_id: str,
    payload: GraphUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GraphOut:
    try:
        graph_uuid = uuid.UUID(graph_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Graph not found") from exc

    graph = db.get(Graph, graph_uuid)
    if not graph or graph.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Graph not found")

    if payload.name is not None:
        graph.name = payload.name
    if payload.description is not None:
        graph.description = payload.description
    if payload.data is not None:
        graph.data = _stamp_schema_version(payload.data)

    db.commit()
    db.refresh(graph)
    return GraphOut.model_validate(_migrate_on_load(graph))


@router.delete("/{graph_id}")
def delete_graph(
    graph_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        graph_uuid = uuid.UUID(graph_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Graph not found") from exc

    graph = db.get(Graph, graph_uuid)
    if not graph or graph.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Graph not found")
    db.delete(graph)
    db.commit()
    return {"deleted": True}
