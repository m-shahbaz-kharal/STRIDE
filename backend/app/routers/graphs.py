from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..models import Graph, User
from ..schemas import GraphCreate, GraphOut, GraphUpdate


router = APIRouter(prefix="/api/graphs", tags=["graphs"])


@router.get("", response_model=list[GraphOut])
def list_graphs(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[GraphOut]:
    graphs = db.execute(select(Graph).where(Graph.owner_id == current_user.id).order_by(Graph.updated_at.desc())).scalars().all()
    return [GraphOut.model_validate(graph) for graph in graphs]


@router.post("", response_model=GraphOut)
def create_graph(
    payload: GraphCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GraphOut:
    graph = Graph(owner_id=current_user.id, name=payload.name, data=payload.data)
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
    return GraphOut.model_validate(graph)


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
    if payload.data is not None:
        graph.data = payload.data

    db.commit()
    db.refresh(graph)
    return GraphOut.model_validate(graph)


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
