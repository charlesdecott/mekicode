"""shell.py — coquille studio 3 modes (Chat / Canvas / Mix) + sélecteur de session.

- Chat   : ChatComponent plein cadre (la session courante).
- Canvas : une node chat PAR session (clic sans effet de focus ici — chaque node est éditable).
- Mix    : ChatComponent focus à gauche + canvas à droite ; cliquer l'en-tête d'une node chat
           la met en focus à gauche (sans reconstruire le canvas).
Le MÊME ChatComponent est instancié partout.
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
    mode0 = app.storage.user.get("studio_mode", "mix")
    if mode0 not in ("canvas", "mix"):   # 'chat' = page d'accueil (route /), jamais persisté ici
        mode0 = "mix"
    # session à focus après création d'un worktree (one-shot) → on atterrit dans SA session
    focus_sid = app.storage.user.get("studio_focus_sid")
    if focus_sid is not None:
        try:
            del app.storage.user["studio_focus_sid"]
        except Exception:
            pass
    init_sid = focus_sid if (focus_sid and any(m.id == focus_sid for m in metas)) else metas[0].id
    state = {"mode": mode0, "sid": init_sid}
    refs = {"left": None}

    with container:
        bar = ui.element("div").classes("studio-modes")
        stage = ui.element("div").classes("studio-stage")

    def _set_mode(m: str) -> None:
        state["mode"] = m
        app.storage.user["studio_mode"] = m
        _render()

    def _focus(sid: str) -> None:
        """Focus d'un chat : highlight de sa node (déjà posé côté JS) + en mode Mix il passe à
        gauche. On mémorise l'id pour qu'au passage en Mix ce soit le chat de gauche."""
        if not sid:
            return
        state["sid"] = sid
        if refs["left"] is not None:
            refs["left"].clear()
            ChatComponent(refs["left"], hub, sid, author)
        ui.run_javascript(
            "document.querySelectorAll('.node-wrap[data-kind=\"chat\"]').forEach("
            "w=>w.classList.toggle('focused', w.dataset.session==='" + sid + "'));")

    def _on_focus_event(e) -> None:
        args = getattr(e, "args", None)
        _focus(args.get("session") if isinstance(args, dict) else None)

    ui.on("meki_focus", _on_focus_event)   # clic sur une node chat (canvas.js) → focus côté Python

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
                if key == "chat":
                    # Chat seul = la page d'accueil mekicode historique (sidebar cyberpunk).
                    b = ui.button(label, on_click=lambda _=None: ui.navigate.to("/"))
                    b.classes("mode-btn").props("flat dense")
                else:
                    b = ui.button(label, on_click=lambda _=None, mm=key: _set_mode(mm))
                    b.classes("mode-btn" + (" on" if state["mode"] == key else "")).props("flat dense")
            ui.label(f"{len(sessions)} chats").classes("studio-sub")

        stage.clear()
        stage.classes(remove="mode-chat mode-canvas mode-mix")
        stage.classes(f"mode-{state['mode']}")
        refs["left"] = None
        with stage:
            if state["mode"] == "canvas":
                right = ui.element("div").classes("stage-canvas")
                render_canvas(right, hub, store, author, focus_sid=state["sid"], inject=False)
            else:  # mix
                left = ui.element("div").classes("stage-chat")
                refs["left"] = left
                ChatComponent(left, hub, sess.id, author)
                right = ui.element("div").classes("stage-canvas")
                render_canvas(right, hub, store, author, focus_sid=state["sid"], inject=False)

    _render()
