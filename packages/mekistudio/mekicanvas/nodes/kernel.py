"""kernel.py — node ancre du canvas (fixe, ni déplaçable ni redimensionnable)."""
from __future__ import annotations

from ..components.base import HeaderComponent, LayoutComponent, NodeComponent
from ..model import Node

KIND = "kernel"


def build_kernel_node(x: float = 0.0, y: float = 0.0) -> Node:
    return Node(
        kind=KIND, x=x, y=y, movable=False, resizable=False,
        root=NodeComponent(children=[
            LayoutComponent(children=[HeaderComponent(level=1, text="Kernel")]),
        ]),
    )
