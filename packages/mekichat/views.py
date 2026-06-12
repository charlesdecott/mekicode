"""views.py — helpers de rendu NiceGUI (mappés sur les classes CSS de la maquette)."""
from __future__ import annotations

import json

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
            content = msg.get("content", "")
            if role == "assistant":
                # réponses de l'agent : rendu markdown (titres, listes, code, retours-ligne)
                with ui.element("div").classes("body"):
                    ui.markdown(content, extras=["fenced-code-blocks", "tables", "break-on-newline"])
            else:
                # messages utilisateur : texte brut, retours-ligne préservés (pas de markdown
                # pour ne pas mâcher les commandes/globs avec * ou _)
                with ui.element("div").classes("body plain"):
                    ui.label(content)


def render_session_item(meta, *, active: bool, on_click) -> None:
    """Affiche un item de la barre latérale (titre + id + nb msg)."""
    classes = "session active" if active else "session"
    with ui.element("div").classes(classes).on("click", on_click):
        with ui.element("div").classes("s-title"):
            ui.label(">_").classes("mk")
            ui.label(meta.title)
        ui.label(f"{meta.id} · {meta.n_messages} msg").classes("s-meta")


def render_tool(command: str, output: str = "", status: str = "RUN"):
    """Bloc [bash] : commande + sortie + statut. Renvoie (label_statut, label_sortie)
    pour pouvoir remplir la sortie plus tard (chemin live)."""
    with ui.element("div").classes("tool"):
        with ui.element("div").classes("tool-head"):
            ui.label("▣ PROC :: bash").classes("ic")
            ui.label(command).classes("cmd")
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
                    cmd = json.loads(fn.get("arguments") or "{}").get("command", "")
                except (json.JSONDecodeError, AttributeError):
                    cmd = str(fn.get("arguments", ""))
                render_tool(cmd, output=outputs.get(tc.get("id"), ""), status="DONE")


def render_stream_bubble():
    """Bulle assistant en cours de streaming. Renvoie (conteneur_body, label_texte) :
    on met à jour le label à chaque token, puis on finalise via finalize_stream()."""
    with ui.element("div").classes("msg bot"):
        with ui.element("div").classes("avatar bot"):
            ui.label("M")
        with ui.element("div"):
            with ui.element("div").classes("head"):
                ui.label("mekicore").classes("who")
                ui.label("//AGENT").classes("tag")
            body = ui.element("div").classes("body streaming")
            with body:
                lbl = ui.label("")
    return body, lbl


def finalize_stream(body, text: str) -> None:
    """Remplace le texte brut streamé par le rendu markdown final (retire le caret)."""
    body.classes(remove="streaming")
    body.clear()
    with body:
        ui.markdown(text, extras=["fenced-code-blocks", "tables", "break-on-newline"])
