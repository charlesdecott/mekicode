"""canvas_page.py — rend le canvas : kernel + UNE node chat par session.

`render_canvas(container, hub, store, author, *, focus_sid=None, on_focus=None, inject=True)` :
pose un kernel et une node chat par session (chacune embarque le MÊME ChatComponent), reliées
au kernel par des câbles 45°. Cliquer l'en-tête d'une node chat appelle `on_focus(session_id)`
(mode Mix → met cette session en panneau focus à gauche). La node `focus_sid` est surlignée.
"""
from __future__ import annotations

from pathlib import Path

from nicegui import ui

from mekicanvas.components.base import ChatComponentSpec, LayoutComponent, NodeComponent
from mekicanvas.model import Node
from mekicanvas.nodes import kernel as kernel_node

_JS = Path(__file__).resolve().parent / "static" / "js"
_CSS = Path(__file__).resolve().parent / "static" / "css" / "canvas.css"
_CHAT_CSS = Path(__file__).resolve().parent.parent / "mekichat" / "static" / "mekichat.css"

_CHAT_W, _CHAT_H, _GAP = 420.0, 460.0, 60.0


def inject_assets() -> None:
    """Injecte JS (géométrie + pont) + CSS (chat + canvas). À appeler UNE FOIS au build de page."""
    for fname in ("cables.js", "collision.js", "canvas.js"):
        ui.add_body_html(f"<script>{(_JS / fname).read_text(encoding='utf-8')}</script>")
    ui.add_css(_CHAT_CSS.read_text(encoding="utf-8"))
    ui.add_css(_CSS.read_text(encoding="utf-8"))


def _build_nodes(metas):
    """kernel + une node chat par session (session_id stocké dans node.path). Disposées en
    rangée centrée sous le kernel ; toutes rattachées au kernel (câbles en éventail)."""
    k = kernel_node.build_kernel_node(x=0.0, y=0.0)
    nodes = [k]
    n = max(1, len(metas))
    span = (_CHAT_W + _GAP)
    for i, m in enumerate(metas):
        x = (i - (n - 1) / 2.0) * span
        nodes.append(Node(
            kind="chat", x=x, y=260.0, w=_CHAT_W, h=_CHAT_H, source_id=k.id, path=m.id,
            root=NodeComponent(children=[LayoutComponent(children=[ChatComponentSpec(title=m.title)])]),
        ))
    return nodes


def render_canvas(container, hub, store, author, *, focus_sid=None, on_focus=None, inject: bool = True) -> None:
    if inject:
        inject_assets()
    metas = store.list()
    title_by_id = {m.id: (m.title or m.id) for m in metas}
    nodes = _build_nodes(metas)

    with container:
        canvas = ui.element("div").classes("mc-canvas")
        with canvas:
            world = ui.element("div").classes("mc-world")
            with world:
                for node in nodes:
                    sid = node.path if node.kind == "chat" else None
                    cls = "node-wrap" + (" focused" if sid and sid == focus_sid else "")
                    wrap = ui.element("div").classes(cls)
                    style = f"left:{node.x}px;top:{node.y}px;"
                    if node.w:
                        style += f"width:{node.w}px;"
                    if node.h:
                        style += f"height:{node.h}px;"
                    wrap.style(style)
                    wrap.props(f'data-id="{node.id}" data-kind="{node.kind}" '
                               f'data-source="{node.source_id or ""}" data-session="{sid or ""}"')
                    with wrap:
                        with ui.element("div").classes("node-card"):
                            if node.kind == "chat":
                                head = ui.element("div").classes("nhead nhead-focus")
                                with head:
                                    ui.label("💬 " + (title_by_id.get(sid, "chat") or "chat")[:22])
                                    if on_focus:
                                        ui.label("◎").classes("focus-dot").tooltip("focus à gauche")
                                if on_focus:
                                    head.on("click", lambda _=None, s=sid: on_focus(s))
                                body = ui.element("div").classes("nbody nbody-chat")
                                from component import ChatComponent  # mekichat (sys.path posé par l'app)
                                ChatComponent(body, hub, sid, author)
                            else:
                                with ui.element("div").classes("nhead"):
                                    ui.label("◉ kernel")

    ui.timer(0.25, lambda: ui.run_javascript(
        "window.MekiCanvas && window.MekiCanvas.initWorld();"), once=True)
