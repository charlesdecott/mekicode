"""canvas_page.py — rend le canvas : kernel → folders (scopes) → [explorateur + chats] → éditeurs.

Sprint 2a : chaque folder (workspace) gagne un ExplorerNode (arbre fichiers sandboxé). Double-clic
fichier → EditorNode épinglé. Quand l'agent LIT un fichier (read/grep/glob), un EditorNode éphémère
apparaît sous l'explorateur + une comète file du chat vers lui (abonnement par session).
"""
from __future__ import annotations

import json
from pathlib import Path

from nicegui import ui

from mekicanvas import editor as editor_mod
from mekicanvas import explorer as explorer_mod
from mekicanvas.impulses import impulse_from_hub_event, normalize_path
from mekicanvas.nodes import kernel as kernel_node  # noqa: F401  (réservé)

_JS = Path(__file__).resolve().parent / "static" / "js"
_CSS = Path(__file__).resolve().parent / "static" / "css" / "canvas.css"
_CHAT_CSS = Path(__file__).resolve().parent.parent / "mekichat" / "static" / "mekichat.css"

_CHAT_W, _CHAT_H = 400.0, 440.0
_COL_GAP, _ROW_GAP = 460.0, 480.0
_FOLDER_GAP = 1320.0
_EXPLORER_W, _EXPLORER_H = 340.0, 560.0
_EDITOR_W, _EDITOR_H = 520.0, 380.0
_KERNEL_ID = "kernel"
_EPH_TTL_S = 600  # 10 min


def inject_assets() -> None:
    for fname in ("cables.js", "collision.js", "canvas.js"):
        ui.add_body_html(f"<script>{(_JS / fname).read_text(encoding='utf-8')}</script>")
    ui.add_css(_CHAT_CSS.read_text(encoding="utf-8"))
    ui.add_css(_CSS.read_text(encoding="utf-8"))


def _branch_for(repo_path: str) -> str:
    import subprocess
    try:
        out = subprocess.run(["git", "-C", repo_path, "rev-parse", "--abbrev-ref", "HEAD"],
                             capture_output=True, text=True, timeout=3)
        return out.stdout.strip() or "?"
    except Exception:
        return "?"


def _git_status(repo: str) -> dict:
    import subprocess

    def g(*args):
        try:
            return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=4).stdout
        except Exception:
            return ""

    branch = (g("rev-parse", "--abbrev-ref", "HEAD").strip() or "?")
    dirty = len([ln for ln in g("status", "--porcelain").splitlines() if ln.strip()])
    ahead = behind = 0
    ab = g("rev-list", "--left-right", "--count", "@{u}...HEAD").split()
    if len(ab) == 2:
        try:
            behind, ahead = int(ab[0]), int(ab[1])
        except ValueError:
            pass
    return {"branch": branch, "ahead": ahead, "behind": behind, "dirty": dirty}


def _render_git(container, repo) -> None:
    lbl = {"el": None}
    with container:
        lbl["el"] = ui.label("…").classes("git-line")

    def _refresh() -> None:
        s = _git_status(str(repo))
        txt = f"⎇ {s['branch']}"
        if s["ahead"]:
            txt += f"  ↑{s['ahead']}"
        if s["behind"]:
            txt += f"  ↓{s['behind']}"
        txt += f"  ● {s['dirty']} modifs" if s["dirty"] else "  ✓ propre"
        try:
            lbl["el"].set_text(txt)
        except Exception:
            pass

    _refresh()
    ui.timer(8.0, _refresh)


def _workspace_path(store, registry, meta) -> Path:
    try:
        from mekihub.projects import workspace_for
        return Path(workspace_for(store.load(meta.id), registry)).resolve()
    except Exception:
        return Path.cwd().resolve()


def _groups(metas, store, registry):
    by_key: dict = {}
    order: list = []
    for m in metas:
        key = (m.project_id, m.scope)
        if key not in by_key:
            by_key[key] = []
            order.append(key)
        by_key[key].append(m)
    order.sort(key=lambda k: (k[1] != "main", k[0], k[1]))
    out = []
    for pid, scope in order:
        project = registry.get(pid) if registry else None
        name = project.name if project else pid
        sessions = by_key[(pid, scope)]
        ws = _workspace_path(store, registry, sessions[0])
        if scope == "main":
            branch = _branch_for(project.repo_path) if project else "main"
            label, glyph = f"{name} · ⎇ {branch}", "\U0001F4C1"
        else:
            label, glyph = f"{name} · ⎇ {scope}", "\U0001F33F"
        out.append({"key": f"folder:{pid}:{scope}", "label": label, "glyph": glyph,
                    "sessions": sessions, "ws": ws})
    return out


def render_canvas(container, hub, store, author, *, focus_sid=None, inject: bool = True) -> None:
    if inject:
        inject_assets()
    metas = store.list()
    registry = getattr(hub, "registry", None)
    groups = _groups(metas, store, registry)

    # --- 1. positions (coords MONDE) + maps ---
    placed = []   # dict par node
    placed.append(dict(id=_KERNEL_ID, kind="kernel", x=0.0, y=0.0, w=None, h=None,
                       src=None, glyph="◉", text="kernel", sid=None, payload=None))
    session_ws: dict = {}      # sid -> ws Path
    explorers: dict = {}       # ws_str -> {id, x, y, count}
    n_groups = max(1, len(groups))
    for gi, g in enumerate(groups):
        fx = (gi - (n_groups - 1) / 2.0) * _FOLDER_GAP
        fy = 220.0
        fid = g["key"]
        placed.append(dict(id=fid, kind="folder", x=fx - 150.0, y=fy, w=300.0, h=66.0,
                           src=_KERNEL_ID, glyph=g["glyph"], text=g["label"], sid=None, payload=None))
        ws = g["ws"]; ws_str = str(ws)
        exp_id = f"explorer:{g['key']}"
        exp_x, exp_y = fx - _COL_GAP - _EXPLORER_W - 80.0, fy + 200.0
        placed.append(dict(id=exp_id, kind="explorer", x=exp_x, y=exp_y, w=_EXPLORER_W, h=_EXPLORER_H,
                           src=fid, glyph="\U0001F5C2", text="fichiers", sid=None, payload=ws_str))
        explorers[ws_str] = {"id": exp_id, "x": exp_x, "y": exp_y, "count": 0}
        # node git (statut de branche, à droite du cluster)
        placed.append(dict(id=f"git:{g['key']}", kind="git", x=fx + _COL_GAP + 60.0, y=fy + 200.0,
                           w=300.0, h=72.0, src=fid, glyph="⎇", text="git", sid=None, payload=ws_str))
        for si, m in enumerate(g["sessions"]):
            col, row = si % 2, si // 2
            cx = fx + (col - 0.5) * _COL_GAP - _CHAT_W / 2.0
            cy = fy + 200.0 + row * _ROW_GAP
            placed.append(dict(id=m.id, kind="chat", x=cx, y=cy, w=_CHAT_W, h=_CHAT_H, src=fid,
                               glyph="\U0001F4AC", text=(m.title or m.id)[:22], sid=m.id, payload=None))
            session_ws[m.id] = ws

    spawned: dict = {}   # (ws_str, rel) -> editor id
    seq = {"n": 0}

    # --- 2. canvas + world ---
    with container:
        canvas = ui.element("div").classes("mc-canvas")
        with canvas:
            # précharge la lib CodeMirror dès le build (sinon le 1er éditeur spawné dynamiquement
            # ne monte pas : la dépendance JS n'est pas encore chargée).
            ui.codemirror(value="", theme="basicDark").style(
                "position:absolute;width:1px;height:1px;opacity:0;pointer-events:none;left:-9999px").classes("cm-preload")
            world = ui.element("div").classes("mc-world")

    # --- 3. spawn / remove (closures) ---
    def _remove_editor(key, eid) -> None:
        spawned.pop(key, None)
        ui.run_javascript(
            f"(()=>{{const w=document.querySelector('.node-wrap[data-id=\"{eid}\"]');"
            f"if(w)w.remove(); window.MekiCanvas && window.MekiCanvas.redraw();}})()")

    def _spawn_editor(ws, rel, from_id, *, ephemeral) -> None:
        rel = normalize_path(rel)
        ws_str = str(Path(ws).resolve())
        exp = explorers.get(ws_str)
        if exp is None or not rel:
            return
        key = (ws_str, rel)
        existing = spawned.get(key)
        if existing:
            ui.run_javascript(f"window.MekiCanvas && window.MekiCanvas.cometTo({json.dumps(from_id)},{json.dumps(existing)})")
            return
        seq["n"] += 1
        eid = f"editor:{seq['n']}"
        spawned[key] = eid
        i = exp["count"]; exp["count"] = i + 1
        ex, ey = exp["x"] - _EDITOR_W - 60.0, exp["y"] + i * (_EDITOR_H + 40.0)
        with world:
            _build_node(dict(id=eid, kind="editor", x=ex, y=ey, w=_EDITOR_W, h=_EDITOR_H, src=exp["id"],
                             glyph="✎", text=Path(rel).name, sid=None, payload={"ws": ws_str, "rel": rel}),
                        focus_sid, hub, author, explorers, _spawn_editor, _remove_editor,
                        ephemeral=ephemeral, close_key=key)

        def _after(_from=from_id, _eid=eid) -> None:
            ui.run_javascript("window.MekiCanvas && window.MekiCanvas.redraw();")
            ui.run_javascript(f"window.MekiCanvas && window.MekiCanvas.cometTo({json.dumps(_from)},{json.dumps(_eid)})")
        ui.timer(0.06, _after, once=True)
        if ephemeral:
            def _expire(_key=key, _eid=eid) -> None:
                if spawned.get(_key) == _eid:
                    _remove_editor(_key, _eid)
            ui.timer(_EPH_TTL_S, _expire, once=True)

    # --- 4. rendu initial ---
    with world:
        for p in placed:
            _build_node(p, focus_sid, hub, author, explorers, _spawn_editor, _remove_editor)

    ui.timer(0.25, lambda: ui.run_javascript("window.MekiCanvas && window.MekiCanvas.initWorld();"), once=True)

    # --- 5. abonnements par session : spawn éphémère + comète sur lecture de l'agent ---
    for sid, ws in session_ws.items():
        _start_file_watch(hub, sid, ws, _spawn_editor)


def _explorer_id_for(ws_str, explorers):
    e = explorers.get(str(ws_str))
    return e["id"] if e else _KERNEL_ID


def _build_node(p, focus_sid, hub, author, explorers, spawn_fn, remove_fn,
                *, ephemeral=False, close_key=None) -> None:
    kind, sid = p["kind"], p["sid"]
    cls = "node-wrap" + (" focused" if sid and sid == focus_sid else "") + (" ephemeral" if ephemeral else "")
    wrap = ui.element("div").classes(cls)
    style = f"left:{p['x']}px;top:{p['y']}px;"
    if p["w"]:
        style += f"width:{p['w']}px;"
    if p["h"]:
        style += f"height:{p['h']}px;"
    wrap.style(style)
    wrap.props(f'data-id="{p["id"]}" data-kind="{kind}" data-source="{p["src"] or ""}" data-session="{sid or ""}"')
    with wrap:
        with ui.element("div").classes("node-card"):
            with ui.element("div").classes("nhead"):
                ui.label(f"{p['glyph']} {p['text']}").classes("nhead-label")
            if kind == "chat":
                body = ui.element("div").classes("nbody nbody-chat")
                from component import ChatComponent  # mekichat
                ChatComponent(body, hub, sid, author)
            elif kind == "explorer":
                body = ui.element("div").classes("nbody nbody-fs")
                ws = p["payload"]
                explorer_mod.render_explorer(
                    body, ws,
                    lambda rel, _ws=ws: spawn_fn(_ws, rel, _explorer_id_for(_ws, explorers), ephemeral=False))
            elif kind == "editor":
                body = ui.element("div").classes("nbody nbody-editor")  # noqa: F841
                editor_mod.render_editor(body, p["payload"]["ws"], p["payload"]["rel"],
                                         lambda _k=close_key, _id=p["id"]: remove_fn(_k, _id))
            elif kind == "git":
                body = ui.element("div").classes("nbody nbody-git")
                _render_git(body, p["payload"])
            if kind != "kernel":
                ui.element("div").classes("resize-handle")


def _start_file_watch(hub, sid, ws, spawn_editor) -> None:
    args_by_id: dict = {}

    async def _watch() -> None:
        async for ev in hub.subscribe(sid):
            name = type(ev).__name__
            if name == "ToolStarted":
                args_by_id[ev.id] = ev.args
            elif name == "ToolFinished":
                try:
                    setattr(ev, "args", args_by_id.get(ev.id, {}))
                except Exception:
                    pass
                try:
                    intent = impulse_from_hub_event(ev)
                except Exception:
                    intent = None
                tgt = (intent or {}).get("target", {})
                is_read = getattr(ev, "name", "").lower() == "read"   # read = un seul fichier (grep/glob = dossier)
                if is_read and intent and intent.get("kind") == "comet" and tgt.get("by") == "file":
                    try:
                        spawn_editor(ws, tgt["value"], sid, ephemeral=True)
                    except RuntimeError as e:
                        if "deleted" in str(e):
                            return   # canvas obsolète (changement de mode) → on arrête cet abonnement
                    except Exception:
                        pass

    ui.timer(0.15, _watch, once=True)
