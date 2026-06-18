"""views.py — helpers de rendu NiceGUI (mappés sur les classes CSS de la maquette)."""
from __future__ import annotations

import json
import re
from datetime import datetime

from nicegui import ui

_AVATARS = {"user": ("user", "CD"), "assistant": ("bot", "M")}
_WHO = {"user": "charles", "assistant": "mekicore"}
_TAG = {"user": "//USER", "assistant": "//AGENT"}
_MD_EXTRAS = ["fenced-code-blocks", "tables", "break-on-newline"]
# Glyphe cyberpunk par outil (la couleur est portée par la classe CSS `t-<nom>`).
_TOOL_GLYPH = {"bash": "❯_", "read": "▤", "write": "✎", "edit": "±", "grep": "⌕", "glob": "✲"}


def _md(text: str) -> None:
    """Rendu markdown d'une réponse (titres, listes, code, retours-ligne)."""
    ui.markdown(text, extras=_MD_EXTRAS)


def _msg_shell(role: str):
    """Squelette d'une ligne de message (avatar + en-tête). Renvoie (ligne, colonne) :
    l'appelant ajoute le corps dans `colonne`. Partagé par message et bulle de streaming."""
    kind, initials = _AVATARS[role]
    row = ui.element("div").classes(f"msg {kind}")
    with row:
        with ui.element("div").classes(f"avatar {kind}"):
            ui.label(initials)
        col = ui.element("div")
        with col:
            with ui.element("div").classes("head"):
                ui.label(_WHO[role]).classes("who")
                ui.label(_TAG[role]).classes("tag")
                ui.label(datetime.now().strftime("%H:%M:%S")).classes("time")
    return row, col


def render_message(msg: dict) -> None:
    """Affiche une ligne de message (avatar + en-tête + corps), façon Discord."""
    role = msg.get("role", "assistant")
    if role not in ("user", "assistant"):
        return  # system / tool non affichés directement
    _, col = _msg_shell(role)
    content = msg.get("content", "")
    with col:
        if role == "assistant":
            # réponses de l'agent : rendu markdown (titres, listes, code, retours-ligne)
            with ui.element("div").classes("body"):
                _md(content)
        else:
            # messages utilisateur : texte brut, retours-ligne préservés (pas de markdown
            # pour ne pas mâcher les commandes/globs avec * ou _)
            with ui.element("div").classes("body plain"):
                ui.label(content)


def render_session_item(meta, *, active: bool, on_click, on_delete) -> None:
    """Affiche un item de la barre latérale (titre + id + nb msg + bouton supprimer)."""
    classes = "session active" if active else "session"
    with ui.element("div").classes(classes).on("click", on_click):
        with ui.element("div").classes("s-title"):
            ui.label(">_").classes("mk")
            ui.label(meta.title).classes("s-name")
            ui.label("✕").classes("s-del").on("click.stop", on_delete)  # .stop : ne pas ouvrir la session
        ui.label(f"{meta.id} · {meta.n_messages} msg").classes("s-meta")


def tool_summary(args) -> str:
    """Résumé d'un appel d'outil pour l'affichage : la commande / le chemin / le motif."""
    if not isinstance(args, dict):
        return ""
    for k in ("command", "path", "pattern"):
        if k in args:
            return str(args[k])
    # aucun argument connu → 1er argument (cas inattendu ; .cmd tronque si trop long)
    return str(next(iter(args.values()), ""))


_ST_CLASS = {"DONE": "st done", "ERR": "st err"}


def _render_diff(old: str, new: str) -> None:
    """Affiche le changement d'`edit` en diff : `--- ancien` (lignes `-`) / `+++ nouveau` (lignes `+`)."""
    with ui.element("div").classes("diff"):
        ui.label("--- ancien").classes("dh")
        for line in (old.splitlines() or [""]):
            ui.label(f"- {line}").classes("dl del")
        ui.label("+++ nouveau").classes("dh")
        for line in (new.splitlines() or [""]):
            ui.label(f"+ {line}").classes("dl add")


def _line_count(text: str) -> int:
    """Nombre de lignes du texte (sans la newline finale)."""
    t = (text or "").rstrip("\n")
    return len(t.splitlines()) if t else 0


def _edit_metric(old: str, new: str) -> str:
    """Métrique d'un `edit` : lignes ajoutées / retirées."""
    return f"+{_line_count(new)} -{_line_count(old)}"


def tool_metric(name: str, output: str) -> str:
    """Info compacte affichée dans l'en-tête (surtout utile quand le bloc est replié)."""
    if not output:
        return ""
    if output.startswith("Error"):
        return "erreur"
    if name in ("read", "bash"):
        return "—" if output == "(no output)" else f"{_line_count(output)} lignes"
    if name == "write":
        m = re.search(r"\d+", output)                 # "écrit N caractères dans ..."
        return f"{m.group()} car." if m else ""
    if name == "grep":
        return "0 résultat" if output.startswith("(aucun") else f"{_line_count(output)} résultats"
    if name == "glob":
        return "0 fichier" if output.startswith("(aucun") else f"{_line_count(output)} fichiers"
    return ""


def render_tool(name: str, summary: str = "", output: str = "", status: str = "RUN",
                *, old: str | None = None, new: str | None = None):
    """Bloc d'outil **replié par défaut** (clic sur l'en-tête → ouvre/ferme). En-tête : glyphe + NOM
    (couleur par outil) + résumé + métrique compacte + statut + chevron. Pour `edit`, le corps est le
    diff `---`/`+++`. Renvoie (label_statut, label_sortie, label_métrique) pour remplissage différé."""
    glyph = _TOOL_GLYPH.get(name, "▣")
    base = f"tool t-{name}" if name in _TOOL_GLYPH else "tool"
    tool = ui.element("div").classes(f"{base} collapsed")
    with tool:
        head = ui.element("div").classes("tool-head")
        with head:
            ui.label(glyph).classes("ic")
            ui.label(name).classes("tname")
            ui.label(summary).classes("cmd")
            meta = ui.label("").classes("meta")
            st = ui.label(status).classes(_ST_CLASS.get(status, "st"))
            ui.label("▾").classes("chev")
        if name == "edit" and old is not None:
            _render_diff(old, new or "")
        out = ui.label(output).classes("tool-out")

    state = {"open": False}

    def _toggle(_=None, t=tool, s=state):
        s["open"] = not s["open"]
        if s["open"]:
            t.classes(remove="collapsed")
        else:
            t.classes("collapsed")

    head.on("click", _toggle)
    if name == "edit" and old is not None:
        meta.set_text("erreur" if status == "ERR" else _edit_metric(old, new or ""))
    return st, out, meta


def fill_tool(handle, output: str, ok: bool = True, name: str = "") -> None:
    """Remplit un bloc d'outil créé en statut RUN (statut DONE/ERR + sortie + métrique compacte)."""
    st, out, meta = handle
    st.set_text("DONE" if ok else "ERR")
    st.classes(replace="st done" if ok else "st err")
    out.set_text(output)
    if name == "edit":
        if not ok:
            meta.set_text("erreur")          # le diff montrait le changement tenté
    else:
        meta.set_text(tool_metric(name, output))


def render_thinking():
    """Indicateur animé « PROCESSING… » affiché pendant un appel LLM.
    Renvoie l'élément ligne (l'appelant le supprime via .delete() quand le tour répond)."""
    row = ui.element("div").classes("msg bot")
    with row:
        with ui.element("div").classes("avatar bot"):
            ui.label("M")
        with ui.element("div"):
            ui.html('<div class="thinking"><span class="bars"><i></i><i></i><i></i><i></i></span> PROCESSING…</div>')
    return row


def render_thread(messages: list, authors: dict | None = None) -> None:
    """Rejoue tout un historique : texte (user/assistant) + blocs d'outils appariés
    (assistant.tool_calls ↔ messages role:'tool'). Chemin de rechargement de session.

    `authors` (optionnel) = {index_message: {"name","color"}} : si fourni, les messages
    user sont rendus AVEC leur attribution (auteur multi-utilisateur), comme le rendu
    live. Sans lui, repli sur le rendu générique (compat)."""
    authors = authors or {}
    outputs = {m.get("tool_call_id"): m.get("content", "")
               for m in messages if m.get("role") == "tool"}
    for idx, m in enumerate(messages):
        role = m.get("role")
        if role == "user" and m.get("content") and idx in authors:
            attr = authors[idx]
            render_user_message(m["content"], attr.get("name", "anon"),
                                attr.get("color", "#39ff14"))
            continue
        if role in ("user", "assistant") and m.get("content"):
            render_message(m)
        if role == "assistant":
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                name = fn.get("name", "tool")
                raw = outputs.get(tc.get("id"), "")
                status = "ERR" if raw.startswith("Error") else "DONE"
                old = new = None
                out = raw
                if name == "edit":
                    old, new = args.get("old"), args.get("new")
                    out = "" if status == "DONE" else raw   # succès : le diff suffit
                handle = render_tool(name, tool_summary(args), output=out, status=status,
                                     old=old, new=new)
                if name != "edit":
                    handle[2].set_text(tool_metric(name, raw))


def render_stream_bubble():
    """Bulle assistant en cours de streaming. Renvoie (conteneur_body, élément_markdown) :
    on met à jour le markdown à chaque token (preview live), puis on finalise via finalize_stream()."""
    _, col = _msg_shell("assistant")
    with col:
        body = ui.element("div").classes("body streaming")
        with body:
            md = ui.markdown("", extras=_MD_EXTRAS)   # preview markdown live (pas seulement à la fin)
    return body, md


def finalize_stream(body, text: str) -> None:
    """Remplace le texte brut streamé par le rendu markdown final (retire le caret)."""
    body.classes(remove="streaming")
    body.clear()
    with body:
        _md(text)


def render_presence(present):
    """Affiche les pastilles de présence (un chip par participant, couleur de l'auteur).
    `present` : list[Author]. Renvoie le conteneur (l'appelant le remplace à chaque maj)."""
    box = ui.element("div").classes("presence")
    with box:
        for a in present:
            ui.label(a.name).classes("pres-chip").style(f"--ac:{a.color}")
    return box


def render_queue_item(item_id, name, color, text, on_delete):
    """Affiche une ligne de file d'attente (auteur + texte + bouton ✕). Renvoie la ligne.
    `on_delete(item_id)` est appelé au clic sur ✕ (suppression d'un item en attente)."""
    row = ui.element("div").classes("qitem").style(f"--ac:{color}")
    with row:
        ui.label(name).classes("q-author").style(f"--ac:{color}")
        ui.label(text).classes("q-text")
        btn = ui.button("✕").props("flat dense").classes("q-del")
        btn.on("click", lambda _: on_delete(item_id))
    return row


def render_user_message(text, name, color):
    """Affiche un message utilisateur attribué (avatar + en-tête avec nom/couleur d'auteur).
    Variante de render_message : l'auteur n'est pas figé (multi-utilisateur)."""
    _, col = _msg_shell("user")
    with col:
        with ui.element("div").classes("body plain attrib"):
            ui.label(name).classes("msg-author").style(f"--ac:{color}")
            ui.label(text)


def render_worktree_proposal(name: str, prompt: str, on_approve, on_reject):
    """Carte « worktree proposé » (style Phosphore) avec boutons Approuver / Refuser.

    `name`       : nom du worktree (affiché dans le titre)
    `prompt`     : texte d'amorçage (affiché en sous-texte)
    `on_approve` : callback sans argument (appelé au clic sur Approuver)
    `on_reject`  : callback sans argument (appelé au clic sur Refuser)
    Renvoie l'élément racine de la carte (peut être supprimé via .delete()).
    """
    card = ui.element("div").classes("wt-proposal")
    with card:
        with ui.element("div").classes("wt-proposal-head"):
            ui.label(f"⎇ worktree proposé : {name}").classes("wt-proposal-title")
        ui.label(prompt).classes("wt-proposal-prompt")
        with ui.element("div").classes("wt-proposal-actions"):
            ui.button("Approuver", on_click=lambda: on_approve()).classes("wt-btn approve")
            ui.button("Refuser", on_click=lambda: on_reject()).classes("wt-btn reject").props("flat")
    return card


_PERM_LABELS = {
    "once": "Autoriser une fois", "session": "Autoriser (session)",
    "project": "Autoriser (projet)", "deny": "Refuser",
    "blacklist": "Refuser + ne plus demander",
}


def render_permission_request(tool: str, target: str, reason: str, options, on_choice):
    """Carte de demande de permission (s15, style Phosphore), façon Claude Code.

    `on_choice(choice)` est appelé au clic (choice ∈ options) ; la carte se supprime ensuite.
    Renvoie l'élément racine (supprimable via .delete()).
    """
    card = ui.element("div").classes("perm-request")
    with card:
        with ui.element("div").classes("perm-head"):
            ui.label(f"⚿ permission requise : {tool}").classes("perm-title")
        ui.label(target).classes("perm-target")
        ui.label(reason).classes("perm-reason")
        with ui.element("div").classes("perm-actions"):
            for opt in options:
                danger = opt in ("deny", "blacklist")
                btn = ui.button(_PERM_LABELS.get(opt, opt),
                                on_click=lambda _=None, o=opt: (on_choice(o), card.delete()))
                btn.classes("perm-btn " + ("reject" if danger else "approve")).props("flat dense")
    return card


def render_ask_request(question: str, options, on_answer):
    """Carte « question de l'agent » (ask_user). Boutons si `options`, sinon champ libre.
    `on_answer(reponse)` est appelé puis la carte se supprime. Renvoie l'élément racine."""
    card = ui.element("div").classes("ask-request")
    with card:
        with ui.element("div").classes("ask-head"):
            ui.label("❓ question de l'agent").classes("ask-title")
        ui.label(question).classes("ask-q")
        with ui.element("div").classes("ask-actions"):
            if options:
                for opt in options:
                    ui.button(str(opt), on_click=lambda _=None, o=opt: (on_answer(o), card.delete())) \
                        .classes("ask-btn").props("flat dense")
            else:
                inp = ui.input(placeholder="ta réponse…").classes("ask-input")

                def _send(_=None):
                    v = (inp.value or "").strip()
                    if v:
                        on_answer(v)
                        card.delete()

                inp.on("keydown.enter", _send)
                ui.button("Répondre", on_click=_send).classes("ask-btn").props("flat dense")
    return card


def render_project_selector(projects, current_project_id,
                             on_pick_project, on_add_project):
    """Liste des projets (PROJETS) dans la sidebar, style Phosphore. La navigation worktree/session
    est gérée par `render_worktree_tree`."""
    with ui.element("div").classes("proj-selector"):
        with ui.element("div").classes("sec-label"):
            ui.label("PROJETS")
        with ui.element("div").classes("proj-list"):
            for p in projects:
                is_active = p.id == current_project_id
                with ui.element("div").classes("proj-item active" if is_active else "proj-item").on(
                    "click", lambda _, pid=p.id: on_pick_project(pid)
                ):
                    ui.label(">").classes("mk")
                    ui.label(p.name).classes("proj-name")
        with ui.element("div").classes("proj-add-wrap"):
            with ui.element("button").classes("proj-add-btn").on("click", lambda _: on_add_project()):
                ui.label("+ projet")


def _wt_scope_parts(scope: str):
    """Sépare un scope worktree 'nom_uuid' → ('nom', '_uuid') pour l'affichage ; sinon (scope, '')."""
    import re
    m = re.match(r"^(.*)_([0-9a-f]{6,})$", scope or "")
    return (m.group(1), "_" + m.group(2)) if m else (scope, "")


def _wt_session_line(meta, current_sid, on_open_session, on_delete):
    """Ligne de session compacte (Design C) : puce + titre + ✕ au survol."""
    is_on = meta.id == current_sid
    with ui.element("div").classes("wtt-line on" if is_on else "wtt-line").on(
        "click", lambda _, sid=meta.id: on_open_session(sid)
    ):
        ui.label("●").classes("b")
        ui.label(meta.title or meta.id[:8]).classes("nm")
        if on_delete is not None:
            with ui.element("span").classes("x").on(
                "click.stop", lambda _, sid=meta.id: on_delete(sid)
            ):
                ui.label("✕")


def render_worktree_tree(main_sessions, worktrees, current_sid,
                         on_open_session, on_new_session, on_new_worktree, on_delete=None,
                         on_delete_worktree=None):
    """Sidebar hiérarchique « rail compact » (Design C) : catégorie main + catégorie worktrees
    (sous-catégories repliables par worktree), sessions imbriquées, + session sous chaque groupe,
    + new worktree.

    `main_sessions` : list[SessionMeta] (scope main)
    `worktrees`     : list[(scope, [SessionMeta])]
    `current_sid`   : str — session active (surlignée)
    `on_open_session(sid)` ; `on_new_session(scope)` ; `on_new_worktree()` ; `on_delete(sid)|None`
    """
    with ui.element("div").classes("wt-tree"):
        # ── catégorie MAIN ──
        with ui.element("div").classes("wtt-grp"):
            with ui.element("div").classes("wtt-glabel"):
                ui.label("🌿 MAIN")
                ui.element("span").classes("bar")
                with ui.element("span").classes("plus").on("click", lambda _: on_new_session("main")):
                    ui.label("＋")
            for m in main_sessions:
                _wt_session_line(m, current_sid, on_open_session, on_delete)
            with ui.element("div").classes("wtt-add").on("click", lambda _: on_new_session("main")):
                ui.label("＋ session")

        # ── catégorie WORKTREES ──
        with ui.element("div").classes("wtt-grp"):
            with ui.element("div").classes("wtt-glabel wts"):
                ui.label("🌳 WORKTREES")
                ui.element("span").classes("bar")
                with ui.element("span").classes("plus").on("click", lambda _: on_new_worktree()):
                    ui.label("＋")
            for scope, sessions in worktrees:
                name, uid = _wt_scope_parts(scope)
                with ui.element("details").classes("wtt-chip").props("open"):
                    with ui.element("summary"):
                        ui.label("▸").classes("car")
                        ui.label("🌳").classes("ic")
                        ui.label(name).classes("nm")
                        if uid:
                            ui.label(uid).classes("uuid")
                        ui.label(str(len(sessions))).classes("cnt")
                        if on_delete_worktree is not None:
                            with ui.element("span").classes("wtx").on(
                                "click.stop", lambda _, s=scope: on_delete_worktree(s)
                            ):
                                ui.label("🗑")
                    for m in sessions:
                        _wt_session_line(m, current_sid, on_open_session, on_delete)
                    with ui.element("div").classes("wtt-add").on(
                        "click", lambda _, s=scope: on_new_session(s)
                    ):
                        ui.label("＋ session")
            with ui.element("div").classes("wtt-newwt").on("click", lambda _: on_new_worktree()):
                ui.label("＋ new worktree")
