"""shell.py — coquille studio à 3 modes (Chat / Canvas / Mix).

`build_studio(container, hub, session, author)` pose un sélecteur de mode + la scène :
- Chat   : ChatComponent plein cadre ;
- Canvas : le canvas (Kernel/Chat/Queue) plein cadre ;
- Mix    : ChatComponent (focus) à gauche + canvas à droite.
Le MÊME ChatComponent est instancié partout (onglet, node canvas, panneau focus).
"""
from __future__ import annotations

from nicegui import app, ui

from component import ChatComponent
from mekicanvas.canvas_page import render_canvas

_MODES = (("chat", "Chat"), ("canvas", "Canvas"), ("mix", "Mix"))


def build_studio(container, hub, session, author) -> None:
    state = {"mode": app.storage.user.get("studio_mode", "mix")}

    with container:
        bar = ui.element("div").classes("studio-modes")
        stage = ui.element("div").classes("studio-stage")

    def _set_mode(m: str) -> None:
        state["mode"] = m
        app.storage.user["studio_mode"] = m
        _render()

    def _render() -> None:
        bar.clear()
        with bar:
            ui.label("◢ mekistudio").classes("studio-brand")
            for key, label in _MODES:
                b = ui.button(label, on_click=lambda _=None, mm=key: _set_mode(mm))
                b.classes("mode-btn" + (" on" if state["mode"] == key else "")).props("flat dense")
            ui.label(f"// {session.title}").classes("studio-sub")
        stage.clear()
        stage.classes(remove="mode-chat mode-canvas mode-mix")
        stage.classes(f"mode-{state['mode']}")
        with stage:
            if state["mode"] in ("chat", "mix"):
                left = ui.element("div").classes("stage-chat")
                ChatComponent(left, hub, session.id, author)
            if state["mode"] in ("canvas", "mix"):
                right = ui.element("div").classes("stage-canvas")
                render_canvas(right, hub, session.id, author, inject=False)  # assets injectés au build /studio

    _render()
