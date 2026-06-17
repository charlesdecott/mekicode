"""chat.py — node Chat (embarque le ChatComponent mekichat côté rendu)."""
from __future__ import annotations

from ..components.base import ChatComponentSpec, LayoutComponent, NodeComponent
from ..model import Node

KIND = "chat"


def build_chat_node(x: float = 0.0, y: float = 200.0) -> Node:
    return Node(
        kind=KIND, x=x, y=y, w=400.0, h=520.0,
        root=NodeComponent(children=[
            LayoutComponent(children=[ChatComponentSpec()]),
        ]),
    )
