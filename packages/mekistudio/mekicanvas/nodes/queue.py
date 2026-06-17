"""queue.py — node File d'attente (sous le chat ; rend la file mekihub de la session)."""
from __future__ import annotations

from ..components.base import LayoutComponent, NodeComponent, QueueComponentSpec
from ..model import Node

KIND = "queue"


def build_queue_node(x: float = 0.0, y: float = 760.0) -> Node:
    return Node(
        kind=KIND, x=x, y=y, w=400.0, h=220.0, resizable=False,
        root=NodeComponent(children=[
            LayoutComponent(children=[QueueComponentSpec()]),
        ]),
    )
