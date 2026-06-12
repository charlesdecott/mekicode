"""views.py — helpers de rendu NiceGUI (mappés sur les classes CSS de la maquette)."""
from __future__ import annotations

from nicegui import ui

_AVATARS = {"user": ("user", "CD"), "assistant": ("bot", "M")}
_WHO = {"user": "charles", "assistant": "mekicore"}
_TAG = {"user": "//USER", "assistant": "//AGENT"}


def render_message(msg: dict) -> None:
    """Affiche une ligne de message (avatar + en-tête + corps), façon Discord."""
    role = msg.get("role", "assistant")
    if role not in ("user", "assistant"):
        return  # system / tool non affichés en phase 1
    kind, initials = _AVATARS[role]
    with ui.element("div").classes(f"msg {kind}"):
        with ui.element("div").classes(f"avatar {kind}"):
            ui.label(initials)
        with ui.element("div"):
            with ui.element("div").classes("head"):
                ui.label(_WHO[role]).classes("who")
                ui.label(_TAG[role]).classes("tag")
            with ui.element("div").classes("body"):
                ui.label(msg.get("content", ""))


def render_session_item(meta, *, active: bool, on_click) -> None:
    """Affiche un item de la barre latérale (titre + id + nb msg)."""
    classes = "session active" if active else "session"
    with ui.element("div").classes(classes).on("click", on_click):
        with ui.element("div").classes("s-title"):
            ui.label(">_").classes("mk")
            ui.label(meta.title)
        ui.label(f"{meta.id} · {meta.n_messages} msg").classes("s-meta")
