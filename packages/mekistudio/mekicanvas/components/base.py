"""base.py — composants du canvas (union discriminée pydantic).

ComponentBase porte un id stable ; chaque composant concret porte `type: Literal[...]`
(pivot de la sérialisation hétérogène). Sprint 1 : Header, Layout, Node, Chat, Queue.
Un Layout/Node peut contenir d'autres composants (récursif).
"""
from __future__ import annotations

import uuid
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


def new_id() -> str:
    return uuid.uuid4().hex


class ComponentBase(BaseModel):
    id: str = Field(default_factory=new_id)


class HeaderComponent(ComponentBase):
    type: Literal["header"] = "header"
    text: str = ""
    level: int = Field(default=1, ge=1, le=4)


class ChatComponentSpec(ComponentBase):
    type: Literal["chat"] = "chat"
    title: str = "chat"


class QueueComponentSpec(ComponentBase):
    type: Literal["queue"] = "queue"
    title: str = "file d'attente"


class LayoutComponent(ComponentBase):
    type: Literal["layout"] = "layout"
    direction: Literal["column", "row"] = "column"
    gap: int = 8
    children: list["Component"] = Field(default_factory=list)


class NodeComponent(ComponentBase):
    type: Literal["node"] = "node"
    children: list["Component"] = Field(default_factory=list)


Component = Annotated[
    Union[NodeComponent, LayoutComponent, HeaderComponent, ChatComponentSpec, QueueComponentSpec],
    Field(discriminator="type"),
]

LayoutComponent.model_rebuild()
NodeComponent.model_rebuild()
