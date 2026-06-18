#!/usr/bin/env python3
"""app.py — front mekichat (NiceGUI). Chat + outils (bash/read/write/edit/grep/glob), streaming."""
from __future__ import annotations

import asyncio
import sys
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent             # packages/mekistudio/mekichat/
STUDIO = HERE.parent                               # packages/mekistudio/
PACKAGES = STUDIO.parent                           # packages/
sys.path.insert(0, str(HERE))                      # sessions, views, component (locaux)
sys.path.insert(0, str(STUDIO))                    # mekicanvas (paquet sœur, futur)
sys.path.insert(0, str(PACKAGES))                  # mekillm, mekihub (packages/)
sys.path.insert(0, str(PACKAGES / "mekicore"))     # base, tools, events

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
from mekicanvas.canvas_page import inject_assets, render_canvas  # noqa: E402  (canvas studio)
from shell import build_studio  # noqa: E402  (coquille 3 modes — route /studio)

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
    """Fabrique le provider LLM consommé par le SessionHub. Modes de test réseau-free :
    - MEKICHAT_FAKE_LLM  : FakeLLM déterministe (réponse texte lente, observable) ;
    - MEKICHAT_FAKE_TOOL : FakeToolLLM appelant `bash rm …` (déclenche le tier `ask` de s15)."""
    import os
    tests_dir = str(HERE.parent.parent.parent / "tests")   # racine/tests (fakes)
    if os.environ.get("MEKICHAT_FAKE_PWD"):
        sys.path.insert(0, tests_dir)
        from fakes import FakeToolLLM
        return FakeToolLLM(tool_name="bash", tool_args={"command": "pwd"},
                           final="Voici le répertoire courant.")
    if os.environ.get("MEKICHAT_FAKE_ASK"):
        sys.path.insert(0, tests_dir)
        from fakes import FakeToolLLM
        return FakeToolLLM(tool_name="ask_user",
                           tool_args={"question": "Quelle option choisis-tu ?", "options": ["Option A", "Option B"]},
                           final="Bien reçu.")
    if os.environ.get("MEKICHAT_FAKE_READ"):
        sys.path.insert(0, tests_dir)
        from fakes import FakeToolLLM
        return FakeToolLLM(tool_name="read", tool_args={"path": "CLAUDE.md"},
                           final="J'ai lu CLAUDE.md.")
    if os.environ.get("MEKICHAT_FAKE_TOOL"):
        sys.path.insert(0, tests_dir)
        from fakes import FakeToolLLM
        return FakeToolLLM(tool_name="bash", tool_args={"command": "rm fichier_demo.txt"},
                           final="C'est fait.")
    if os.environ.get("MEKICHAT_FAKE_LLM"):
        sys.path.insert(0, tests_dir)
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

    def _metas_for_scope(pid: str, scope: str):
        """Sessions d'un projet pour un scope EXACT (main, ou un worktree précis)."""
        return [m for m in _get_store().list(project_id=pid) if (m.scope or "main") == scope]

    def _worktree_scopes(pid: str):
        """Scopes distincts des worktrees du projet (hors main), triés — un par worktree."""
        scopes = {m.scope for m in _get_store().list(project_id=pid) if (m.scope or "main") != "main"}
        return sorted(scopes)

    def _new_session():
        """Crée une nouvelle session pour le projet/scope courant et la retourne."""
        return _get_store().create(
            model=DEFAULT_MODEL,
            system=_system_for(current_project, current_scope),
            project_id=current_project.id,
            scope=current_scope,
        )

    def open_session(session_id: str) -> None:
        nonlocal current
        if state["busy"]:
            return
        current = _get_store().load(session_id)
        _refresh()

    def new_session_in(scope: str) -> None:
        """Crée une session DANS un scope précis (main ou un worktree) et bascule dessus."""
        nonlocal current, current_scope
        if state["busy"]:
            return
        current_scope = scope
        current = _get_store().create(model=DEFAULT_MODEL, system=_system_for(current_project, scope),
                                      project_id=current_project.id, scope=scope)
        _mirror_session_to_discord(current)
        _refresh()

    async def delete_session(session_id: str) -> None:
        nonlocal current
        if state["busy"]:
            return
        await _get_hub().purge_session(session_id)   # supprime la session ET son canal Discord
        if current.id == session_id:                 # session courante supprimée → basculer
            current = _ensure_current()              # plus récente restante, ou une nouvelle
        _refresh()

    async def delete_worktree_home(scope: str) -> None:
        """Supprime un worktree : ses sessions, ses canaux Discord, le worktree git et sa catégorie."""
        nonlocal current, current_scope
        if state["busy"] or scope == "main":
            return
        n = await _get_hub().delete_worktree(current_project.id, scope)
        if current.scope == scope:                   # on était dans ce worktree → revenir à main
            current_scope = "main"
            current = _ensure_current()
        _refresh()
        ui.notify(f"worktree « {scope} » supprimé ({n} session·s, canaux Discord inclus)", color="warning")

    def _confirm_delete_worktree(scope: str) -> None:
        n = len(_metas_for_scope(current_project.id, scope))
        dlg = ui.dialog()
        with dlg, ui.card().classes("wt-dialog"):
            ui.label("⚠ Supprimer le worktree ?").classes("sec-label")
            ui.label(f"« {scope} » et ses {n} session·s seront supprimés (worktree git, branche, "
                     "canaux Discord). Action irréversible.").classes("wt-dlg-hint")
            with ui.row():
                async def _go():
                    dlg.close()
                    await delete_worktree_home(scope)
                ui.button("Supprimer", on_click=_go).props("color=negative")
                ui.button("Annuler", on_click=dlg.close).props("flat")
        dlg.open()

    def pick_project(pid: str) -> None:
        nonlocal current, current_project, current_scope
        if state["busy"]:
            return
        proj = _get_registry().get(pid)
        if proj is None:
            return
        current_project = proj
        # Charge la session la plus récente pour ce projet/scope, ou en crée une
        metas = _metas_for_scope(pid, current_scope)
        current = _get_store().load(metas[0].id) if metas else _new_session()
        _refresh()

    def _open_worktree_dialog_home() -> None:
        """Dialog « nouveau worktree » côté accueil → hub.create_worktree + bascule dans sa session."""
        dlg = ui.dialog()
        with dlg, ui.card().classes("wt-dialog"):
            ui.label("🌳 Nouveau worktree isolé").classes("sec-label")
            ui.label("crée <repo>/.worktrees/<nom>_<uuid> + une session dédiée (.env copié)").classes("wt-dlg-hint")
            inp = ui.input(placeholder="nom (ex. feature-login)")
            busy = {"v": False}

            async def _go(_=None) -> None:
                nonlocal current, current_scope
                nm = (inp.value or "").strip()
                if not nm or busy["v"]:
                    return
                busy["v"] = True
                dlg.close()
                ui.notify(f"création du worktree « {nm} »…")
                try:
                    cid, scope = await _get_hub().create_worktree(current_project.id, nm)
                    current_scope = scope
                    current = _get_store().load(cid)
                    _refresh()
                    ui.notify(f"worktree « {scope} » créé ✓", color="positive")
                except Exception as e:  # noqa: BLE001
                    ui.notify(f"échec création worktree : {e}", color="negative")

            inp.on("keydown.enter", _go)
            with ui.row():
                ui.button("Créer le worktree", on_click=_go)
                ui.button("Annuler", on_click=dlg.close).props("flat")
        dlg.open()

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
                ui.button("◢ studio", on_click=lambda: ui.navigate.to("/studio")) \
                    .props("flat dense").style(
                    "margin-left:auto;color:#39ff14;border:1px solid rgba(57,255,20,.4);"
                    "border-radius:7px;font-size:11px;padding:2px 9px")

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
                on_pick_project=pick_project,
                on_add_project=_open_add_project_dialog,
            )

            # Arbre hiérarchique (Design C) : main + worktrees → sessions
            main_metas = _metas_for_scope(current_project.id, "main")
            worktrees = [(sc, _metas_for_scope(current_project.id, sc))
                         for sc in _worktree_scopes(current_project.id)]
            views.render_worktree_tree(
                main_sessions=main_metas,
                worktrees=worktrees,
                current_sid=current.id,
                on_open_session=open_session,
                on_new_session=new_session_in,
                on_new_worktree=_open_worktree_dialog_home,
                on_delete=delete_session,
                on_delete_worktree=_confirm_delete_worktree,
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


@ui.page("/canvas")
def canvas_route() -> None:
    """Aperçu du canvas studio (Kernel/Chat/Queue + câbles 45° + comètes). Route temporaire :
    sera intégrée à la coquille 3 modes (shell.py) en Phase 7."""
    ui.add_head_html(FONTS)
    ui.query("body").props('data-theme=phosphor')
    _ensure_current()
    author = realtime.author_for_client()
    stage = ui.element("div").style("position:fixed;inset:0;")
    render_canvas(stage, _get_hub(), _get_store(), author)


@ui.page("/studio")
def studio_route() -> None:
    """Coquille studio 3 modes (Chat / Canvas / Mix) — la cible du Sprint 1."""
    ui.add_head_html(FONTS)
    ui.query("body").props('data-theme=phosphor')
    inject_assets()                       # JS + CSS chargés UNE fois au build
    _ensure_current()                     # garantit ≥1 session existante
    author = realtime.author_for_client()
    studio = ui.element("div").classes("studio")
    build_studio(studio, _get_hub(), _get_store(), author,
                 make_session=lambda: _get_store().create(model=DEFAULT_MODEL, system=SYSTEM))


if __name__ in {"__main__", "__mp_main__"}:   # garde requise par NiceGUI (reload/multiprocessing)
    # storage_secret : requis par app.storage.user (identité éphémère par navigateur, cf. realtime.py)
    ui.run(title="mekichat", port=8080, dark=True, reload=False, show=True,
           storage_secret="mekichat-dev")
