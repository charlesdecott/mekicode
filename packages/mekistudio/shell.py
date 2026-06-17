"""shell.py — coquille studio à 3 modes (Chat / Canvas / Mix) + sélecteur de session.

`build_studio(container, hub, store, author, *, make_session)` pose : une barre (marque +
sélecteur de mode + sélecteur de session + « nouvelle session ») et la scène :
- Chat   : ChatComponent plein cadre ;
- Canvas : le canvas (Kernel/Chat/Queue) plein cadre ;
- Mix    : ChatComponent (focus) à gauche + canvas à droite.
Le MÊME ChatComponent est instancié partout (panneau focus + node canvas).
"""
from __future__ import annotations

from nicegui import app, ui

from component import ChatComponent
from mekicanvas.canvas_page import render_canvas

_MODES = (("chat", "Chat"), ("canvas", "Canvas"), ("mix", "Mix"))


def build_studio(container, hub, store, author, *, make_session) -> None:
    metas = store.list()
    if not metas:
        make_session()
        metas = store.list()
    state = {"mode": app.storage.user.get("studio_mode", "mix"), "sid": metas[0].id}

    with container:
        bar = ui.element("div").classes("studio-modes")
        stage = ui.element("div").classes("studio-stage")

    def _set_mode(m: str) -> None:
        state["mode"] = m
        app.storage.user["studio_mode"] = m
        _render()

    def _switch(sid: str) -> None:
        if sid and sid != state["sid"]:
            state["sid"] = sid
            _render()

    def _new() -> None:
        sess = make_session()
        state["sid"] = sess.id
        _render()

    def _render() -> None:
        sessions = store.list()
        if not any(m.id == state["sid"] for m in sessions):
            state["sid"] = sessions[0].id if sessions else make_session().id
            sessions = store.list()
        sess = store.load(state["sid"])

        bar.clear()
        with bar:
            ui.label("◢ mekistudio").classes("studio-brand")
            for key, label in _MODES:
                b = ui.button(label, on_click=lambda _=None, mm=key: _set_mode(mm))
                b.classes("mode-btn" + (" on" if state["mode"] == key else "")).props("flat dense")
            opts = {m.id: ((m.title or m.id)[:30]) for m in sessions}
            ui.select(options=opts, value=state["sid"],
                      on_change=lambda e: _switch(e.value)).props("dense outlined options-dense").classes("studio-sel")
            ui.button("+ session", on_click=lambda _=None: _new()).props("flat dense").classes("mode-btn")
            ui.label(f"// {sess.title}").classes("studio-sub")

        stage.clear()
        stage.classes(remove="mode-chat mode-canvas mode-mix")
        stage.classes(f"mode-{state['mode']}")
        with stage:
            if state["mode"] in ("chat", "mix"):
                left = ui.element("div").classes("stage-chat")
                ChatComponent(left, hub, sess.id, author)
            if state["mode"] in ("canvas", "mix"):
                right = ui.element("div").classes("stage-canvas")
                render_canvas(right, hub, sess.id, author, inject=False)

    _render()
