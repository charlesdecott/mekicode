#!/usr/bin/env python3
"""app.py — front mekichat (NiceGUI). Phase 1 : sessions + UI statique (sans LLM)."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# Lancement direct : rend `import sessions, views` résoluble (comme mekicore/main.py).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nicegui import ui  # noqa: E402

import sessions as sessions_mod  # noqa: E402
import views  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
DEFAULT_MODEL = "gpt-4o-mini"
FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Chakra+Petch:wght@400;500;600;700&family=Share+Tech+Mono&display=swap" rel="stylesheet">'
)
PALETTES = [("phosphor", "PHOSPHORE"), ("blade", "BLADE RUNNER"),
            ("orange", "ORANGE/TEAL"), ("acid", "ACIDE")]

store = sessions_mod.SessionStore()


def _ensure_current() -> sessions_mod.Session:
    """Charge la session la plus récente, ou en crée une."""
    metas = store.list()
    return store.load(metas[0].id) if metas else store.create(model=DEFAULT_MODEL)


def _now_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")


@ui.page("/")
def index() -> None:
    ui.add_head_html(FONTS)
    ui.add_css((STATIC / "mekichat.css").read_text(encoding="utf-8"))
    ui.query("body").props('data-theme=phosphor')

    current = _ensure_current()
    # Référence vivante vers le label horloge courant : recréé à chaque _refresh(),
    # mais le timer (créé UNE seule fois plus bas) le relit ici → pas d'empilement de timers.
    clock_ref: dict[str, object] = {"label": None}

    def switch_theme(key: str) -> None:
        ui.run_javascript(f"document.body.setAttribute('data-theme','{key}')")

    def open_session(session_id: str) -> None:
        nonlocal current
        current = store.load(session_id)
        _refresh()

    def new_session() -> None:
        nonlocal current
        current = store.create(model=DEFAULT_MODEL)
        _refresh()

    def send(text: str) -> None:
        text = text.strip()
        if not text:
            return
        current.add("user", text)         # phase 1 : pas de réponse LLM
        store.save(current)
        _refresh()

    def _tick() -> None:
        label = clock_ref["label"]
        if label is not None:
            label.set_text(_now_hms())

    # ---- barre d'outils palettes ----
    with ui.element("div").classes("toolbar"):
        ui.label("PALETTE //").classes("lbl")
        for key, label in PALETTES:
            ui.button(label, on_click=lambda _, k=key: switch_theme(k)).props("flat no-caps").classes("sw")
        ui.element("div").classes("spacer")
        ui.label("phase 1 · UI statique").classes("meta")

    # ---- coquille principale (grille latérale + main) ----
    app_root = ui.element("div").classes("app")
    with app_root:
        sidebar = ui.element("aside").classes("sidebar")
        main = ui.element("section").classes("main")

    def _refresh() -> None:
        """Reconstruit barre latérale + zone principale pour la session courante."""
        sidebar.clear()
        main.clear()
        with sidebar:
            with ui.element("div").classes("brand"):
                with ui.element("div").classes("glyph"):
                    ui.label("M")
                with ui.element("div"):
                    ui.html('<div class="glitch" data-t="MEKICHAT">MEKICHAT</div>')
                    ui.label("// harness v0.1 :: ROOT").classes("ver")
            ui.button("+ nouvelle session", on_click=lambda _: new_session()).props("flat no-caps").classes("new-btn")
            metas = store.list()
            with ui.element("div").classes("sec-label"):
                ui.label("SESSIONS")
                ui.label(f"[{len(metas):02d}]").classes("n")
            with ui.element("div").classes("sessions"):
                for meta in metas:
                    views.render_session_item(
                        meta, active=(meta.id == current.id),
                        on_click=lambda _, sid=meta.id: open_session(sid),
                    )
            with ui.element("div").classes("sidebar-foot"):
                ui.element("span").classes("led")
                ui.label("OPENROUTER :: LINK_OK")

        with main:
            # en-tête
            with ui.element("header").classes("topbar"):
                with ui.element("div").classes("channel"):
                    ui.label("[#]").classes("br")
                    ui.html("<h1>conversation</h1>")
                    ui.label(f"// {current.title}").classes("sub")
                with ui.element("div").classes("chips"):
                    _chip("MODEL", current.model, "model")
                    _chip("SID", current.id, "sid")
                    _chip("TOK", "0↑ 0↓", "")          # placeholder phase 1
                    clock_ref["label"] = _chip("⌚", _now_hms(), "")
            # fil
            with ui.element("div").classes("thread"):
                with ui.element("div").classes("thread-inner"):
                    for msg in current.messages:
                        views.render_message(msg)
            # composer
            with ui.element("div").classes("composer"):
                with ui.element("div").classes("composer-inner"):
                    with ui.element("div").classes("input-wrap"):
                        box = ui.textarea(placeholder="// message à mekicore (phase 1 : pas encore de réponse)")
                        box.props("borderless autogrow").classes("ta")
                        ui.button("▸", on_click=lambda _: (send(box.value), box.set_value(""))).props("flat").classes("send")

    _refresh()
    # Timer horloge créé UNE seule fois (hors _refresh) → met à jour le label courant
    # via clock_ref ; aucun empilement de timers lors des reconstructions.
    ui.timer(1.0, _tick)


def _chip(key: str, value: str, extra: str):
    with ui.element("div").classes(f"chip {extra}"):
        ui.label(key).classes("k")
        lbl = ui.label(value)
    return lbl


if __name__ in {"__main__", "__mp_main__"}:   # garde requise par NiceGUI (reload/multiprocessing)
    ui.run(title="mekichat", port=8080, dark=True, reload=False, show=True)
