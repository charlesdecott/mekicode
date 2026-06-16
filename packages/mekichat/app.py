#!/usr/bin/env python3
"""app.py — front mekichat (NiceGUI). Chat + outils (bash/read/write/edit/grep/glob), streaming."""
from __future__ import annotations

import asyncio
import sys
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))                      # import sessions, views
sys.path.insert(0, str(HERE.parent))               # import mekillm (packages/)
sys.path.insert(0, str(HERE.parent / "mekicore"))  # import base, tools, events

from nicegui import app as nicegui_app, run, ui  # noqa: E402

import mekillm  # noqa: E402
import realtime  # noqa: E402
import sessions as sessions_mod  # noqa: E402
import views  # noqa: E402
from base import run_agent  # noqa: E402  (conservé : compat / rejouage direct, plus piloté ici)
from mekihub.hub import SessionHub  # noqa: E402
from mekihub.session import SessionStore as _HubSessionStore  # noqa: E402
from tools import DISPATCH, TOOLS, make_dispatch  # noqa: E402
from mekihub.projects import ProjectRegistry  # noqa: E402

STATIC = HERE / "static"
DEFAULT_MODEL = mekillm.config.resolve()["model"]
SYSTEM = (
    f"You are a coding agent at {Path.cwd()}. Tools: bash, read, write, edit (str-replace), "
    "grep, glob (file tools are confined to the workspace). Be concise."
)
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
def _get_registry() -> ProjectRegistry:
    """Singleton paresseux du registre de projets. S'assure que le projet par défaut existe."""
    reg = ProjectRegistry()
    reg.ensure_default()
    return reg


@lru_cache(maxsize=1)
def _get_llm():
    """Singleton paresseux du provider LLM. Peut lever si pas de clé (géré à l'appel) ; une
    construction qui échoue n'est pas mise en cache (Python ≥3.9) → réessai au prochain appel."""
    return mekillm.LLM()


def _llm_factory():
    """Fabrique le provider LLM consommé par le SessionHub. Si MEKICHAT_FAKE_LLM est posée,
    renvoie un FakeLLM déterministe (validation Playwright réseau-free, runs lents observables)."""
    import os
    if os.environ.get("MEKICHAT_FAKE_LLM"):
        sys.path.insert(0, str(HERE.parent.parent / "tests"))   # tests/ (fakes)
        from fakes import FakeLLM
        return FakeLLM(reply="reponse simulee lente", delay=0.6)
    return mekillm.LLM()


_HUB = None


def _get_hub() -> SessionHub:
    """SessionHub partagé au niveau module (un seul pour tous les clients/onglets).
    Câblé sur le LLM (réel ou factice) + les outils de mekicore. Paresseux : pas de
    construction au simple import."""
    global _HUB
    if _HUB is None:
        _HUB = SessionHub(store=_HubSessionStore(), llm_factory=_llm_factory,
                          tools=TOOLS, dispatch_factory=make_dispatch, registry=_get_registry())
    return _HUB


def _ensure_current() -> sessions_mod.Session:
    """Charge la session la plus récente, ou en crée une (avec prompt système)."""
    store = _get_store()
    metas = store.list()
    return store.load(metas[0].id) if metas else store.create(model=DEFAULT_MODEL, system=SYSTEM)


# Holder du runtime Discord (adapter + provisioner), peuplé par run_discord à on_ready.
_DISCORD: dict = {}


@nicegui_app.on_startup
async def _boot_discord() -> None:
    """Au démarrage du serveur : si DISCORD_BOT_TOKEN est posé, lance le bot (provisioning +
    miroir bidirectionnel) dans une tâche asyncio. Sinon ne fait rien (Discord optionnel)."""
    import os
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        return
    from mekihub.adapters.discord import run_discord
    hub = _get_hub()
    import asyncio
    asyncio.create_task(run_discord(
        hub, _get_registry(), hub.store, token=token,
        guild_id=os.environ.get("DISCORD_GUILD_ID") or None,
        admin_user_id=os.environ.get("MEKICODE_ADMIN_USER_ID") or None,
        holder=_DISCORD,
    ))


def _mirror_session_to_discord(session) -> None:
    """Crée (à chaud) le canal Discord d'une nouvelle session + démarre son rendu. No-op sans Discord."""
    prov = _DISCORD.get("provisioner")
    adapter = _DISCORD.get("adapter")
    if prov is None or adapter is None:
        return
    import asyncio

    async def _run():
        try:
            ch = await prov.ensure_channel(session)
            _get_store().save(session)
            adapter.add_mapping(str(ch), session.id)
        except Exception as e:                      # never-raise : Discord optionnel
            print(f"[discord] miroir nouvelle session échoué : {e}")

    try:
        asyncio.create_task(_run())
    except RuntimeError:
        pass        # hors boucle asyncio (ne devrait pas arriver dans un handler NiceGUI)


def _system_for(project, scope: str = "main") -> str:
    """Génère un prompt système adapté au projet et au scope (main ou worktree)."""
    root = project.repo_path
    return (f"You are a coding agent working in the project '{project.name}' at {root} "
            f"(scope: {scope}). Tools: bash, read, write, edit (str-replace), grep, glob "
            "(file tools are confined to the workspace). Be concise.")


@ui.page("/")
def index() -> None:
    ui.add_head_html(FONTS)
    ui.add_css((STATIC / "mekichat.css").read_text(encoding="utf-8"))
    ui.query("body").props('data-theme=phosphor')

    current = _ensure_current()
    current_project = _get_registry().get(current.project_id) or _get_registry().ensure_default()
    current_scope = current.scope
    # Identité du navigateur résolue UNE SEULE FOIS ici, dans le contexte de page (cookie de
    # session lié à la requête → app.storage.user/.browser fiables). Réutilisée ensuite par la
    # tâche de fond (_subscribe_loop) et l'envoi (send) via cette closure : on ne résout JAMAIS
    # l'identité ailleurs, ce qui garantit une identité stable et distincte par navigateur.
    author_ref: dict[str, object] = {"author": realtime.author_for_client()}
    thread_ref: dict[str, object] = {"inner": None}
    thinking_ref: dict[str, object] = {"el": None}
    stream_ref: dict[str, object] = {"body": None, "lbl": None, "text": ""}
    # conteneurs live (présence + file), reconstruits à chaque _refresh / Snapshot
    bars_ref: dict[str, object] = {"presence": None, "queue": None}
    # lignes de file indexées par item_id (pour QueueItemDeleted) ; tâche d'abonnement courante
    queue_rows: dict[str, object] = {}
    # cartes « worktree proposé » indexées par proposal_id (supprimées à WorktreeCreated/Rejected)
    wt_cards: dict[str, object] = {}
    sub_ref: dict[str, object] = {"timer": None}
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
        current = _get_store().create(
            model=DEFAULT_MODEL,
            system=_system_for(current_project, current_scope),
            project_id=current_project.id,
            scope=current_scope,
        )
        _mirror_session_to_discord(current)     # crée le canal Discord (no-op si Discord off)
        _refresh()

    def delete_session(session_id: str) -> None:
        nonlocal current
        if state["busy"]:
            return
        _get_store().delete(session_id)
        if current.id == session_id:               # session courante supprimée → basculer
            current = _ensure_current()             # plus récente restante, ou une nouvelle
        _refresh()

    def pick_project(pid: str) -> None:
        nonlocal current, current_project, current_scope
        if state["busy"]:
            return
        proj = _get_registry().get(pid)
        if proj is None:
            return
        current_project = proj
        # Charge la session la plus récente pour ce projet/scope, ou en crée une
        metas = _get_store().list(project_id=pid, scope="main" if current_scope == "main" else None)
        if current_scope != "main":
            metas = [m for m in _get_store().list(project_id=pid) if m.scope != "main"]
        if metas:
            current = _get_store().load(metas[0].id)
        else:
            current = _get_store().create(
                model=DEFAULT_MODEL,
                system=_system_for(current_project, current_scope),
                project_id=current_project.id,
                scope=current_scope,
            )
        _refresh()

    def pick_scope(scope: str) -> None:
        nonlocal current, current_scope
        if state["busy"]:
            return
        current_scope = scope
        # Charge la session la plus récente pour ce projet/scope, ou en crée une
        if scope == "main":
            metas = _get_store().list(project_id=current_project.id, scope="main")
        else:
            metas = [m for m in _get_store().list(project_id=current_project.id)
                     if m.scope != "main"]
        if metas:
            current = _get_store().load(metas[0].id)
        else:
            current = _get_store().create(
                model=DEFAULT_MODEL,
                system=_system_for(current_project, current_scope),
                project_id=current_project.id,
                scope=current_scope,
            )
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

    def _delete_pending(item_id: str) -> None:
        """Clic sur ✕ d'un item en file : demande la suppression au hub (broadcast)."""
        _get_hub().delete_pending(current.id, item_id)

    def _rebuild_queue(items) -> None:
        """Reconstruit l'affichage de la file depuis une liste de QueueItem (Snapshot)."""
        box = bars_ref["queue"]
        if box is None:
            return
        box.clear()
        queue_rows.clear()
        with box:
            for it in items:
                row = views.render_queue_item(it.item_id, it.author.name, it.author.color,
                                              it.text, _delete_pending)
                queue_rows[it.item_id] = row

    def _set_presence(present) -> None:
        """Reconstruit les pastilles de présence dans leur conteneur dédié."""
        box = bars_ref["presence"]
        if box is None:
            return
        box.clear()
        with box:
            for a in present:
                ui.label(a.name).classes("pres-chip").style(f"--ac:{a.color}")

    def _render_hub_event(event, handles: dict) -> None:
        """Rend un événement du SessionHub dans le contexte du client courant.

        Discrimine par nom de type (les events viennent de mekihub.events ; comparaison robuste).
        Les mutations d'UI sont poussées au bon client car cette coroutine tourne dans son slot."""
        name = type(event).__name__
        inner = thread_ref["inner"]

        if name == "Snapshot":
            # rejoue le fil + la file + la présence depuis l'instantané partagé
            state_ = event.state
            queue_rows.clear()
            inner.clear()
            with inner:
                views.render_thread(state_.messages, getattr(state_, "authors", None))
            _rebuild_queue(getattr(state_, "queue", []) or [])
            _set_presence(getattr(state_, "presence", []) or [])
            stream_ref["body"] = None
            return

        if name == "PresenceChanged":
            _set_presence(event.present)
            return

        if name == "QueueEnqueued":
            box = bars_ref["queue"]
            if box is not None:
                with box:
                    row = views.render_queue_item(event.item_id, event.author_name, event.color,
                                                  event.text, _delete_pending)
                    queue_rows[event.item_id] = row
            return

        if name == "QueueItemDeleted":
            row = queue_rows.pop(event.item_id, None)
            if row is not None:
                row.delete()
            return

        if name == "RunStarted":
            # un item quitte la file pour devenir le run courant → retirer sa ligne d'attente
            row = queue_rows.pop(event.item_id, None)
            if row is not None:
                row.delete()
            _clear_thinking()
            with inner:
                thinking_ref["el"] = views.render_thinking()
            return

        if name == "MessagePosted":
            _clear_thinking()
            with inner:
                views.render_user_message(event.text, event.author_name, event.color)
            return

        if name == "AgentDelta":
            _clear_thinking()
            with inner:
                if stream_ref["body"] is None:
                    body, lbl = views.render_stream_bubble()
                    stream_ref["body"], stream_ref["lbl"], stream_ref["text"] = body, lbl, ""
                stream_ref["text"] = stream_ref["text"] + event.text
                stream_ref["lbl"].set_content(stream_ref["text"])   # preview markdown live
            return

        if name == "AgentDone":
            _clear_thinking()
            with inner:
                if stream_ref["body"] is not None:
                    views.finalize_stream(stream_ref["body"], event.text)
                    stream_ref["body"] = None
                elif event.text:
                    views.render_message({"role": "assistant", "content": event.text})
            return

        if name == "ToolStarted":
            _clear_thinking()
            with inner:
                args = event.args if isinstance(event.args, dict) else {}
                old = args.get("old") if event.name == "edit" else None
                new = args.get("new") if event.name == "edit" else None
                handles[event.id] = views.render_tool(event.name, views.tool_summary(event.args),
                                                      old=old, new=new)
            return

        if name == "ToolFinished":
            with inner:
                handle = handles.get(event.id)
                ok = not event.output.startswith("Error")
                out_text = "" if (event.name == "edit" and ok) else event.output
                if handle is not None:
                    views.fill_tool(handle, out_text, ok=ok, name=event.name)
                else:
                    h = views.render_tool(event.name, "", output=out_text,
                                          status="DONE" if ok else "ERR")
                    if event.name != "edit":
                        h[2].set_text(views.tool_metric(event.name, event.output))
            return

        if name == "RunError":
            _clear_thinking()
            with inner:
                if stream_ref["body"] is not None:   # fige la bulle partielle (retire le caret)
                    views.finalize_stream(stream_ref["body"], stream_ref["text"])
                    stream_ref["body"] = None
                _render_error(event.message)
            return

        if name == "WorktreeProposed":
            def _approve(pid=event.proposal_id):
                asyncio.create_task(_get_hub().approve_worktree(current.id, pid))
            def _reject(pid=event.proposal_id):
                _get_hub().reject_worktree(current.id, pid)
            with inner:
                card = views.render_worktree_proposal(event.name, event.prompt, _approve, _reject)
            wt_cards[event.proposal_id] = card
            return

        if name == "WorktreeCreated":
            card = wt_cards.pop(event.proposal_id, None)
            if card is not None:
                card.delete()
            try:
                ui.notify("worktree prêt — nouvelle session enfant", type="positive")
            except Exception:
                pass
            _refresh_sidebar()
            return

        if name == "WorktreeRejected":
            card = wt_cards.pop(event.proposal_id, None)
            if card is not None:
                card.delete()
            return

        if name in ("RunFinished", "Idle"):
            _clear_thinking()
            stream_ref["body"] = None
            _refresh_sidebar()
            return

    async def _subscribe_loop() -> None:
        """Boucle d'abonnement live du client courant : join la salle, rend chaque event,
        leave à la sortie. Lancée via ui.timer one-shot → tourne dans le contexte du client,
        donc les mutations d'UI sont poussées par websocket au bon onglet."""
        author = author_ref["author"]   # identité résolue en contexte de page (cf. index)
        hub = _get_hub()
        sid = current.id
        hub.join(sid, author)
        handles: dict = {}
        try:
            async for event in hub.subscribe(sid):
                if current.id != sid:            # l'utilisateur a changé de session → arrêter
                    break
                try:
                    _render_hub_event(event, handles)
                    _scroll_bottom()
                except RuntimeError as exc:      # onglet fermé pendant le run
                    if "deleted" in str(exc):
                        break
                    raise
        finally:
            hub.leave(sid, author)

    async def send(text: str) -> None:
        """Envoi : on soumet au hub partagé. AUCUN rendu local (cohérence inter-clients) :
        le message user, la réponse et les outils arrivent via la boucle d'abonnement."""
        text = text.strip()
        if not text:
            return
        _get_hub().submit(current.id, text, author=author_ref["author"])

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

            # Sélecteur Projet → scope (en tête de sidebar, avant les sessions)
            def _open_add_project_dialog():
                dlg = ui.dialog()
                with dlg, ui.card():
                    ui.label("Ajouter un projet").classes("sec-label")
                    inp = ui.input(placeholder="Chemin du dépôt git")
                    def _do_register():
                        path = inp.value.strip()
                        try:
                            _get_registry().register(path)
                            dlg.close()
                            _refresh_sidebar()
                        except ValueError as e:
                            ui.notify(str(e), color="negative")
                    ui.button("Enregistrer", on_click=_do_register)
                    ui.button("Annuler", on_click=dlg.close).props("flat")
                dlg.open()

            views.render_project_selector(
                projects=_get_registry().list(),
                current_project_id=current_project.id,
                current_scope=current_scope,
                on_pick_project=pick_project,
                on_pick_scope=pick_scope,
                on_add_project=_open_add_project_dialog,
            )

            with ui.element("button").classes("new-btn").on("click", lambda _: new_session()):
                ui.label("+ nouvelle session")
                ui.html("<kbd>⌘N</kbd>")

            # Sessions filtrées par projet courant + scope courant
            if current_scope == "main":
                metas = store.list(project_id=current_project.id, scope="main")
            else:
                metas = [m for m in store.list(project_id=current_project.id)
                         if m.scope != "main"]
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
                    bars_ref["presence"] = ui.element("div").classes("presence")
            with ui.element("div").classes("thread"):
                inner = ui.element("div").classes("thread-inner")
                thread_ref["inner"] = inner
                with inner:
                    views.render_thread(current.messages, current.authors)
            # cadre de file d'attente : juste au-dessus du composer (en bas), hors de thread-inner
            # pour survivre à la reconstruction du fil sur Snapshot
            with ui.element("div").classes("queue-bar"):
                bars_ref["queue"] = ui.element("div").classes("queue")
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
                        ui.html('<span class="haz">⚠ STREAM ON · 6 TOOLS</span>')
        # abonnement live de CE client à la session courante (broadcast multi-onglet).
        # ui.timer one-shot → la coroutine tourne dans le contexte du client : ses mutations
        # d'UI sont poussées par websocket au bon onglet.
        try:
            sub_ref["timer"] = ui.timer(0.1, _subscribe_loop, once=True)
        except RuntimeError:
            # slot du client supprimé entre l'event et le rebuild (onglet fermé) : rien à abonner
            sub_ref["timer"] = None
        _scroll_bottom()

    _refresh()
    ui.timer(0.2, _scroll_bottom, once=True)   # scroll initial une fois le client connecté


def _chip(key: str, value: str, extra: str):
    with ui.element("div").classes(f"chip {extra}"):
        ui.label(key).classes("k")
        lbl = ui.label(value).classes("v")
    return lbl


if __name__ in {"__main__", "__mp_main__"}:   # garde requise par NiceGUI (reload/multiprocessing)
    # storage_secret : requis par app.storage.user (identité éphémère par navigateur, cf. realtime.py)
    ui.run(title="mekichat", port=8080, dark=True, reload=False, show=True,
           storage_secret="mekichat-dev")
