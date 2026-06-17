"""registry.py — fabrique de nodes par kind + dérivation de parent + réconciliation.

Sprint 1 : Kernel <- Chat <- Queue (par kind canonique). Le path-aware (folder/fileeditor)
viendra au Sprint 2. `reconcile_source_links` est idempotent et déterministe.
"""
from __future__ import annotations

from .model import CanvasState, Node
from .nodes import chat, kernel, queue

NODE_BUILDERS = {
    kernel.KIND: kernel.build_kernel_node,
    chat.KIND: chat.build_chat_node,
    queue.KIND: queue.build_queue_node,
}

CANONICAL_PARENT_KIND = {
    chat.KIND: kernel.KIND,
    queue.KIND: chat.KIND,
}


def _canonical_parent_id(state: CanvasState, kind: str) -> str | None:
    pk = CANONICAL_PARENT_KIND.get(kind)
    if pk is None:
        return None
    for n in state.nodes:
        if n.kind == pk:
            return n.id
    return None


def reconcile_source_links(state: CanvasState) -> CanvasState:
    by_id = {n.id: n for n in state.nodes}
    for node in state.nodes:
        if node.kind == kernel.KIND:
            node.source_id = None
            continue
        expected = CANONICAL_PARENT_KIND.get(node.kind)
        cur = by_id.get(node.source_id) if node.source_id else None
        dangling = node.source_id is None or node.source_id not in by_id
        wrong = cur is not None and expected is not None and cur.kind != expected
        if dangling or wrong:
            node.source_id = _canonical_parent_id(state, node.kind)
    return state


def default_canvas() -> CanvasState:
    """Canvas par défaut du Sprint 1 : Kernel -> Chat -> Queue."""
    nodes = [kernel.build_kernel_node(), chat.build_chat_node(), queue.build_queue_node()]
    return reconcile_source_links(CanvasState(nodes=nodes))
