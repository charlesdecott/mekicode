"""canvas_page.py — rend le canvas : kernel → folders (scopes) → chats groupés.

Une node "folder" n'est PAS un dossier FS : c'est un **espace de travail** = (projet, scope).
- scope "main"  : le repo de base, on affiche la branche git courante ;
- autre scope   : un worktree (dossier séparé), on affiche son nom de branche.
Les chats sont groupés SOUS leur folder (en grille), reliés par câbles 45°. IDs stables
(session_id pour les chats, "folder:<projet>:<scope>" pour les folders, "kernel") → le drag
persiste les positions côté client (localStorage). Cliquer la pastille ◎ d'un chat → focus à gauche.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from nicegui import ui

from mekicanvas.nodes import kernel as kernel_node

_JS = Path(__file__).resolve().parent / "static" / "js"
_CSS = Path(__file__).resolve().parent / "static" / "css" / "canvas.css"
_CHAT_CSS = Path(__file__).resolve().parent.parent / "mekichat" / "static" / "mekichat.css"

_CHAT_W, _CHAT_H = 400.0, 440.0
_COL_GAP, _ROW_GAP = 460.0, 480.0
_FOLDER_GAP = 1040.0
_KERNEL_ID = "kernel"


def inject_assets() -> None:
    """Injecte JS (géométrie + pont) + CSS (chat + canvas). À appeler UNE FOIS au build de page."""
    for fname in ("cables.js", "collision.js", "canvas.js"):
        ui.add_body_html(f"<script>{(_JS / fname).read_text(encoding='utf-8')}</script>")
    ui.add_css(_CHAT_CSS.read_text(encoding="utf-8"))
    ui.add_css(_CSS.read_text(encoding="utf-8"))


def _branch_for(repo_path: str) -> str:
    try:
        out = subprocess.run(["git", "-C", repo_path, "rev-parse", "--abbrev-ref", "HEAD"],
                             capture_output=True, text=True, timeout=3)
        return (out.stdout.strip() or "?")
    except Exception:
        return "?"


def _groups(metas, registry):
    """Groupe les sessions par (project_id, scope) → liste ordonnée de groupes décrits."""
    by_key: dict = {}
    order: list = []
    for m in metas:
        key = (m.project_id, m.scope)
        if key not in by_key:
            by_key[key] = []
            order.append(key)
        by_key[key].append(m)
    # main d'abord, puis worktrees, pour un placement stable
    order.sort(key=lambda k: (k[1] != "main", k[0], k[1]))
    out = []
    for pid, scope in order:
        project = registry.get(pid) if registry else None
        name = project.name if project else pid
        if scope == "main":
            branch = _branch_for(project.repo_path) if project else "main"
            label, glyph = f"{name} · ⎇ {branch}", "\U0001F4C1"   # 📁 + ⎇
        else:
            label, glyph = f"{name} · ⎇ {scope}", "\U0001F33F"     # 🌿 worktree
        out.append({"key": f"folder:{pid}:{scope}", "label": label, "glyph": glyph,
                    "sessions": by_key[(pid, scope)]})
    return out


def render_canvas(container, hub, store, author, *, focus_sid=None, on_focus=None, inject: bool = True) -> None:
    if inject:
        inject_assets()
    metas = store.list()
    registry = getattr(hub, "registry", None)
    groups = _groups(metas, registry)

    # --- positions (coordonnées MONDE) ---
    placed = []   # (id, kind, x, y, w, h, source_id, head_glyph, head_text, session_id)
    placed.append((_KERNEL_ID, "kernel", 0.0, 0.0, None, None, None, "◉", "kernel", None))
    n_groups = max(1, len(groups))
    for gi, g in enumerate(groups):
        fx = (gi - (n_groups - 1) / 2.0) * _FOLDER_GAP
        fy = 220.0
        placed.append((g["key"], "folder", fx - 150.0, fy, 300.0, 66.0, _KERNEL_ID,
                       g["glyph"], g["label"], None))
        for si, m in enumerate(g["sessions"]):
            col, row = si % 2, si // 2
            cx = fx + (col - 0.5) * _COL_GAP - _CHAT_W / 2.0
            cy = fy + 200.0 + row * _ROW_GAP
            title = (m.title or m.id)[:22]
            placed.append((m.id, "chat", cx, cy, _CHAT_W, _CHAT_H, g["key"],
                           "\U0001F4AC", title, m.id))

    with container:
        canvas = ui.element("div").classes("mc-canvas")
        with canvas:
            world = ui.element("div").classes("mc-world")
            with world:
                for nid, kind, x, y, w, h, src, glyph, text, sid in placed:
                    cls = "node-wrap" + (" focused" if sid and sid == focus_sid else "")
                    wrap = ui.element("div").classes(cls)
                    style = f"left:{x}px;top:{y}px;"
                    if w:
                        style += f"width:{w}px;"
                    if h:
                        style += f"height:{h}px;"
                    wrap.style(style)
                    wrap.props(f'data-id="{nid}" data-kind="{kind}" '
                               f'data-source="{src or ""}" data-session="{sid or ""}"')
                    with wrap:
                        with ui.element("div").classes("node-card"):
                            head = ui.element("div").classes("nhead")
                            with head:
                                ui.label(f"{glyph} {text}").classes("nhead-label")
                                if kind == "chat" and on_focus:
                                    dot = ui.label("◎").classes("focus-dot").tooltip("focus à gauche")
                                    dot.on("click", lambda _=None, s=sid: on_focus(s))
                            if kind == "chat":
                                body = ui.element("div").classes("nbody nbody-chat")
                                with body:
                                    scale = ui.element("div").classes("chat-scale")
                                from component import ChatComponent  # mekichat (sys.path posé par l'app)
                                ChatComponent(scale, hub, sid, author)

    ui.timer(0.25, lambda: ui.run_javascript(
        "window.MekiCanvas && window.MekiCanvas.initWorld();"), once=True)
