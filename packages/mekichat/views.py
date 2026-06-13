"""views.py — helpers de rendu NiceGUI (mappés sur les classes CSS de la maquette)."""
from __future__ import annotations

import json
from datetime import datetime

from nicegui import ui

_AVATARS = {"user": ("user", "CD"), "assistant": ("bot", "M")}
_WHO = {"user": "charles", "assistant": "mekicore"}
_TAG = {"user": "//USER", "assistant": "//AGENT"}
_MD_EXTRAS = ["fenced-code-blocks", "tables", "break-on-newline"]


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
    return str(next(iter(args.values()), ""))


def render_tool(name: str, summary: str = "", output: str = "", status: str = "RUN"):
    """Bloc d'outil générique : ▣ <NOM> :: <résumé>. Renvoie (label_statut, label_sortie)."""
    with ui.element("div").classes("tool"):
        with ui.element("div").classes("tool-head"):
            ui.label(f"▣ {name}").classes("ic")
            ui.label(summary).classes("cmd")
            st = ui.label(status).classes("st done" if status == "DONE" else "st")
        out = ui.label(output).classes("tool-out")
    return st, out


def fill_tool(handle, output: str, ok: bool = True) -> None:
    """Remplit un bloc [bash] créé en statut RUN (chemin live)."""
    st, out = handle
    st.set_text("DONE" if ok else "ERR")
    st.classes(replace="st done" if ok else "st")
    out.set_text(output)


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


def render_thread(messages: list) -> None:
    """Rejoue tout un historique : texte (user/assistant) + blocs [bash] appariés
    (assistant.tool_calls ↔ messages role:'tool'). Chemin de rechargement de session."""
    outputs = {m.get("tool_call_id"): m.get("content", "")
               for m in messages if m.get("role") == "tool"}
    for m in messages:
        role = m.get("role")
        if role in ("user", "assistant") and m.get("content"):
            render_message(m)
        if role == "assistant":
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                render_tool(fn.get("name", "tool"), tool_summary(args),
                            output=outputs.get(tc.get("id"), ""), status="DONE")


def render_stream_bubble():
    """Bulle assistant en cours de streaming. Renvoie (conteneur_body, label_texte) :
    on met à jour le label à chaque token, puis on finalise via finalize_stream()."""
    _, col = _msg_shell("assistant")
    with col:
        body = ui.element("div").classes("body streaming")
        with body:
            lbl = ui.label("")
    return body, lbl


def finalize_stream(body, text: str) -> None:
    """Remplace le texte brut streamé par le rendu markdown final (retire le caret)."""
    body.classes(remove="streaming")
    body.clear()
    with body:
        _md(text)
