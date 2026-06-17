"""model.py — Node (brique canvas) + CanvasState (état persistable).

Le parent (`source_id`) est DÉRIVÉ par le registry (non éditable) ; les câbles en découlent.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from .components.base import NodeComponent, new_id


class Node(BaseModel):
    id: str = Field(default_factory=new_id)
    kind: str
    x: float = 0.0
    y: float = 0.0
    w: float | None = None
    h: float | None = None
    source_id: str | None = None
    movable: bool = True
    resizable: bool = True
    collapsed: bool = False
    path: str | None = None
    root: NodeComponent


class CanvasState(BaseModel):
    schema_version: int = 1
    nodes: list[Node] = Field(default_factory=list)
