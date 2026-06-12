#!/usr/bin/env python3
"""app.py — front mekichat (NiceGUI). Phase 2 : chat + outils (bash), non-streaming."""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))                      # import sessions, views
sys.path.insert(0, str(HERE.parent))               # import mekillm (packages/)
sys.path.insert(0, str(HERE.parent / "mekicore"))  # import base, tools, events

from nicegui import run, ui  # noqa: E402

import events  # noqa: E402
import mekillm  # noqa: E402
import sessions as sessions_mod  # noqa: E402
import views  # noqa: E402
from base import run_agent  # noqa: E402
from tools import DISPATCH, TOOLS  # noqa: E402

STATIC = HERE / "static"
DEFAULT_MODEL = mekillm.config.resolve()["model"]
SYSTEM = f"You are a coding agent at {Path.cwd()}. Use the bash tool to act. Be concise."
FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Chakra+Petch:wght@400;500;600;700&family=Share+Tech+Mono&display=swap" rel="stylesheet">'
)
_BG = (
    '<div class="bg"><div class="grid"></div><div class="vig"></div>'
    '<div class="scan"></div><div class="noise"></div><div class="sweep"></div>'
    '<div class="mosh"></div><div class="mosh b"></div></div>'
)
_DONE = object()  # sentinelle de fin de générateur pour run.io_bound(next, gen, _DONE)

@lru_cache(maxsize=1)
def _get_store() -> sessions_mod.SessionStore:
    """Singleton paresseux : évite de créer .sessions/ au simple import du module."""
    return sessions_mod.SessionStore()


@lru_cache(maxsize=1)
def _get_llm():
    """Singleton paresseux du provider LLM. Peut lever si pas de clé (géré à l'appel) ; une
    construction qui échoue n'est pas mise en cache (Python ≥3.9) → réessai au prochain appel."""
    return mekillm.LLM()


def _ensure_current() -> sessions_mod.Session:
    """Charge la session la plus récente, ou en crée une (avec prompt système)."""
    store = _get_store()
    metas = store.list()
    return store.load(metas[0].id) if metas else store.create(model=DEFAULT_MODEL, system=SYSTEM)


@ui.page("/")
def index() -> None:
    ui.add_head_html(FONTS)
    ui.add_css((STATIC / "mekichat.css").read_text(encoding="utf-8"))
    ui.query("body").props('data-theme=phosphor')

    current = _ensure_current()
    thread_ref: dict[str, object] = {"inner": None}
    thinking_ref: dict[str, object] = {"el": None}
    stream_ref: dict[str, object] = {"body": None, "lbl": None, "text": ""}
    state = {"busy": False}

    def open_session(session_id: str) -> None:
        nonlocal current
        if state["busy"]:
            return
        current = _get_store().load(session_id)
        _refresh()

    def new_session() -> None:
        nonlocal current
        if state["busy"]:
            return
        current = _get_store().create(model=DEFAULT_MODEL, system=SYSTEM)
        _refresh()

    def delete_session(session_id: str) -> None:
        nonlocal current
        if state["busy"]:
            return
        _get_store().delete(session_id)
        if current.id == session_id:               # session courante supprimée → basculer
            current = _ensure_current()             # plus récente restante, ou une nouvelle
        _refresh()

    def _scroll_bottom() -> None:
        try:
            ui.run_javascript("const t=document.querySelector('.thread'); if(t) t.scrollTop=t.scrollHeight;")
        except Exception:
            pass

    def _clear_thinking() -> None:
        el = thinking_ref["el"]
        if el is not None:
            el.delete()
            thinking_ref["el"] = None

    def _render_error(message: str) -> None:
        with ui.element("div").classes("run-error"):
            ui.label(f"⚠ {message}")

    def _render_event(ev, handles: dict) -> None:
        inner = thread_ref["inner"]
        if isinstance(ev, events.ThinkingStarted):
            _clear_thinking()
            with inner:
                thinking_ref["el"] = views.render_thinking()
            return
        _clear_thinking()
        with inner:
            if isinstance(ev, events.AssistantDelta):
                if stream_ref["body"] is None:
                    body, lbl = views.render_stream_bubble()
                    stream_ref["body"], stream_ref["lbl"], stream_ref["text"] = body, lbl, ""
                stream_ref["text"] = stream_ref["text"] + ev.text
                stream_ref["lbl"].set_text(stream_ref["text"])
            elif isinstance(ev, events.AssistantDone):
                if stream_ref["body"] is not None:
                    views.finalize_stream(stream_ref["body"], ev.text)
                    stream_ref["body"] = None
                elif ev.text:
                    views.render_message({"role": "assistant", "content": ev.text})
            elif isinstance(ev, events.ToolStarted):
                cmd = str(ev.args.get("command", "")) if isinstance(ev.args, dict) else ""
                handles[ev.id] = views.render_tool(cmd)
            elif isinstance(ev, events.ToolFinished):
                handle = handles.get(ev.id)
                ok = not ev.output.startswith("Error")
                if handle is not None:
                    views.fill_tool(handle, ev.output, ok=ok)
                else:
                    views.render_tool("", output=ev.output, status="DONE")
            elif isinstance(ev, events.RunError):
                if stream_ref["body"] is not None:   # fige la bulle partielle (retire le caret)
                    views.finalize_stream(stream_ref["body"], stream_ref["text"])
                    stream_ref["body"] = None
                _render_error(ev.message)

    async def send(text: str) -> None:
        text = text.strip()
        if not text or state["busy"]:
            return
        state["busy"] = True
        stream_ref["body"] = None
        try:
            store = _get_store()
            current.add("user", text)
            store.save(current)
            inner = thread_ref["inner"]
            with inner:
                views.render_message({"role": "user", "content": text})
            _scroll_bottom()
            try:
                llm = _get_llm()
            except Exception as e:  # pas de clé / config invalide
                with inner:
                    _render_error(f"LLM indisponible : {e}")
                return
            gen = run_agent(current.messages, llm, TOOLS, DISPATCH, stream=True)
            handles: dict = {}
            disconnected = False
            while True:
                ev = await run.io_bound(next, gen, _DONE)
                if ev is _DONE or isinstance(ev, events.RunFinished):
                    break
                try:
                    _render_event(ev, handles)
                    _scroll_bottom()
                except RuntimeError as exc:  # onglet/client fermé pendant le run : on cesse de rendre
                    if "deleted" not in str(exc):
                        raise
                    disconnected = True
                    break
            if not disconnected:
                _clear_thinking()
            store.save(current)              # persiste la conversation même si l'onglet a été fermé
            if not disconnected:
                _refresh_sidebar()
        finally:
            state["busy"] = False

    ui.html(_BG)  # fond animé plein écran (derrière l'UI)

    app_root = ui.element("div").classes("app")
    with app_root:
        sidebar = ui.element("aside").classes("sidebar")
        main = ui.element("section").classes("main")

    def _refresh_sidebar() -> None:
        store = _get_store()
        sidebar.clear()
        with sidebar:
            with ui.element("div").classes("brand"):
                with ui.element("div").classes("glyph"):
                    ui.label("M")
                with ui.element("div"):
                    ui.html('<div class="glitch" data-t="MEKICHAT">MEKICHAT</div>')
                    ui.label("// harness v0.1 :: ROOT").classes("ver")
            with ui.element("button").classes("new-btn").on("click", lambda _: new_session()):
                ui.label("+ nouvelle session")
                ui.html("<kbd>⌘N</kbd>")
            metas = store.list()
            with ui.element("div").classes("sec-label"):
                ui.label("SESSIONS")
                ui.label(f"[{len(metas):02d}]").classes("n")
            with ui.element("div").classes("sessions"):
                for meta in metas:
                    views.render_session_item(
                        meta, active=(meta.id == current.id),
                        on_click=lambda _, sid=meta.id: open_session(sid),
                        on_delete=lambda _, sid=meta.id: delete_session(sid),
                    )
            with ui.element("div").classes("sidebar-foot"):
                ui.element("span").classes("led")
                ui.label("OPENROUTER :: LINK_OK")

    def _refresh() -> None:
        thinking_ref["el"] = None
        stream_ref["body"] = None
        _refresh_sidebar()
        main.clear()
        with main:
            with ui.element("header").classes("topbar"):
                with ui.element("div").classes("channel"):
                    ui.label("[#]").classes("br")
                    ui.html("<h1>conversation</h1>")
                    ui.label(f"// {current.title}").classes("sub")
                with ui.element("div").classes("chips"):
                    _chip("MODEL", current.model, "model")
                    _chip("SID", current.id, "sid")
                    _chip("TOK", "0↑ 0↓", "")
            with ui.element("div").classes("thread"):
                inner = ui.element("div").classes("thread-inner")
                thread_ref["inner"] = inner
                with inner:
                    views.render_thread(current.messages)
            with ui.element("div").classes("composer"):
                with ui.element("div").classes("composer-inner"):
                    with ui.element("div").classes("input-wrap"):
                        box = ui.textarea(placeholder="// message à mekicore (l'agent peut lancer des commandes bash)")
                        box.props("borderless autogrow").classes("ta")

                        async def _flush(_=None) -> None:
                            # lit la valeur (box.value est synchronisée via l'event input, qui précède
                            # le keydown dans le websocket ordonné), la vide, puis envoie.
                            value = box.value or ""
                            box.set_value("")
                            await send(value)

                        async def _on_enter(e) -> None:
                            # Entrée seule → envoyer ; Maj+Entrée → nouvelle ligne (comportement par défaut).
                            if not (isinstance(e.args, dict) and e.args.get("shiftKey")):
                                await _flush()

                        ui.button("▸", on_click=_flush).props("flat").classes("send")
                        box.on("keydown.enter", _on_enter, args=["shiftKey"])
                    with ui.element("div").classes("hint"):
                        ui.html("<span><kbd>Entrée</kbd> envoyer · <kbd>Maj+Entrée</kbd> ligne</span>")
                        ui.html('<span class="haz">⚠ STREAM ON · TOOLS: BASH</span>')
        _scroll_bottom()

    _refresh()
    ui.timer(0.2, _scroll_bottom, once=True)   # scroll initial une fois le client connecté


def _chip(key: str, value: str, extra: str):
    with ui.element("div").classes(f"chip {extra}"):
        ui.label(key).classes("k")
        lbl = ui.label(value).classes("v")
    return lbl


if __name__ in {"__main__", "__mp_main__"}:   # garde requise par NiceGUI (reload/multiprocessing)
    ui.run(title="mekichat", port=8080, dark=True, reload=False, show=True)
