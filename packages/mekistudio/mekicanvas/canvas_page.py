"""canvas_page.py — rend le canvas (Kernel/Chat/Queue) en NiceGUI + comètes pilotées serveur.

`render_canvas(container, hub, session_id, author)` : pose les nodes en .node-wrap dans .mc-world,
charge la géométrie vendorée + canvas.js + canvas.css, initialise pan/zoom et trace les câbles,
puis s'abonne au hub pour transformer les events d'outils en impulsions (glow/comète).
Sprint 1 : corps de nodes simples (le ChatComponent réel s'embarquera en Task 9).
"""
from __future__ import annotations

import json
from pathlib import Path

from nicegui import ui

from mekicanvas.registry import default_canvas
from mekicanvas.impulses import impulse_from_hub_event

_JS = Path(__file__).resolve().parent / "static" / "js"
_CSS = Path(__file__).resolve().parent / "static" / "css" / "canvas.css"
_CHAT_CSS = Path(__file__).resolve().parent.parent / "mekichat" / "static" / "mekichat.css"


def inject_assets() -> None:
    """Injecte JS (géométrie + pont) + CSS (chat + canvas). À appeler UNE FOIS au build de page."""
    for fname in ("cables.js", "collision.js", "canvas.js"):
        ui.add_body_html(f"<script>{(_JS / fname).read_text(encoding='utf-8')}</script>")
    ui.add_css(_CHAT_CSS.read_text(encoding="utf-8"))   # styles du chat embarqué (node chat)
    ui.add_css(_CSS.read_text(encoding="utf-8"))


def _node_body(node) -> None:
    """Contenu (placeholder Sprint 1) selon le kind."""
    if node.kind == "kernel":
        with ui.element("div").classes("nhead"):
            ui.label("◉ kernel")
    elif node.kind == "chat":
        with ui.element("div").classes("nhead"):
            ui.label("💬 chat")
        with ui.element("div").classes("nbody"):
            ui.label("(ChatComponent embarqué — Task 9)").style("opacity:.6")
    elif node.kind == "queue":
        with ui.element("div").classes("nhead"):
            ui.label("⏳ file d'attente")
        with ui.element("div").classes("nbody"):
            ui.label("(vide)").style("opacity:.6")
    else:
        with ui.element("div").classes("nhead"):
            ui.label(node.kind)


def render_canvas(container, hub, session_id: str, author, *, inject: bool = True) -> None:
    if inject:
        inject_assets()
    state = default_canvas()
    with container:
        canvas = ui.element("div").classes("mc-canvas")
        with canvas:
            world = ui.element("div").classes("mc-world")
            with world:
                for n in state.nodes:
                    wrap = ui.element("div").classes("node-wrap")
                    style = f"left:{n.x}px;top:{n.y}px;"
                    if n.w:
                        style += f"width:{n.w}px;"
                    if n.h:
                        style += f"height:{n.h}px;"
                    wrap.style(style)
                    wrap.props(f'data-id="{n.id}" data-kind="{n.kind}" data-source="{n.source_id or ""}"')
                    with wrap:
                        with ui.element("div").classes("node-card"):
                            if n.kind == "chat":
                                with ui.element("div").classes("nhead"):
                                    ui.label("💬 chat")
                                body = ui.element("div").classes("nbody nbody-chat")
                                from component import ChatComponent  # mekichat (sys.path posé par l'app)
                                ChatComponent(body, hub, session_id, author)
                            else:
                                _node_body(n)

    # init pan/zoom + tracé des câbles (après que le DOM des nodes soit posé)
    ui.timer(0.25, lambda: ui.run_javascript(
        "window.MekiCanvas && window.MekiCanvas.initWorld();"), once=True)

    # abonnement aux events du hub -> impulsions (glow/comète)
    args_by_id: dict = {}

    async def _impulses() -> None:
        async for ev in hub.subscribe(session_id):
            name = type(ev).__name__
            if name == "ToolStarted":
                args_by_id[ev.id] = ev.args
            elif name == "ToolFinished":
                try:
                    setattr(ev, "args", args_by_id.get(ev.id, {}))
                except Exception:
                    pass
            try:
                intent = impulse_from_hub_event(ev)
            except Exception:
                intent = None
            if intent:
                ui.run_javascript(f"window.MekiCanvas && window.MekiCanvas.impulse({json.dumps(intent)})")

    ui.timer(0.1, _impulses, once=True)
