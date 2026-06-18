"""canvas_page.py — rend le canvas : kernel → folders (scopes) → [explorateur + chats] → éditeurs.

Sprint 2a : chaque folder (workspace) gagne un ExplorerNode (arbre fichiers sandboxé). Double-clic
fichier → EditorNode épinglé. Quand l'agent LIT un fichier (read/grep/glob), un EditorNode éphémère
apparaît sous l'explorateur + une comète file du chat vers lui (abonnement par session).
"""
from __future__ import annotations

import json
import posixpath
from pathlib import Path

from nicegui import ui

from mekicanvas import editor as editor_mod
from mekicanvas import explorer as explorer_mod
from mekicanvas import terminal as terminal_mod
from mekicanvas.impulses import impulse_from_hub_event, normalize_path
from mekicanvas.nodes import kernel as kernel_node  # noqa: F401  (réservé)

_JS = Path(__file__).resolve().parent / "static" / "js"
_CSS = Path(__file__).resolve().parent / "static" / "css" / "canvas.css"
_CHAT_CSS = Path(__file__).resolve().parent.parent / "mekichat" / "static" / "mekichat.css"

_CHAT_W, _CHAT_H = 400.0, 440.0
_COL_GAP, _ROW_GAP = 460.0, 480.0
_FOLDER_GAP = 1850.0   # > largeur d'un cluster (~1740 : explorateur fx-880 → terminal fx+860)
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
                    "sessions": sessions, "ws": ws, "pid": pid, "scope": scope})
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

    def _place_group(g, fx, fy, folder_src):
        """Place un cluster d'espace de travail : folder + explorateur + git + terminal + chats."""
        fid = g["key"]
        placed.append(dict(id=fid, kind="folder", x=fx - 150.0, y=fy, w=300.0, h=66.0,
                           src=folder_src, glyph=g["glyph"], text=g["label"], sid=None, payload=None))
        ws = g["ws"]; ws_str = str(ws)
        exp_id = f"explorer:{g['key']}"
        exp_x, exp_y = fx - _COL_GAP - _EXPLORER_W - 80.0, fy + 200.0
        placed.append(dict(id=exp_id, kind="explorer", x=exp_x, y=exp_y, w=_EXPLORER_W, h=_EXPLORER_H,
                           src=fid, glyph="\U0001F5C2", text="fichiers", sid=None, payload=ws_str))
        explorers[ws_str] = {"id": exp_id, "x": exp_x, "y": exp_y, "count": 0}
        placed.append(dict(id=f"git:{g['key']}", kind="git", x=fx + _COL_GAP + 60.0, y=fy + 200.0,
                           w=300.0, h=72.0, src=fid, glyph="⎇", text="git", sid=None, payload=ws_str))
        placed.append(dict(id=f"term:{g['key']}", kind="terminal", x=fx + _COL_GAP + 60.0, y=fy + 320.0,
                           w=340.0, h=220.0, src=f"git:{g['key']}", glyph="⌨", text="terminal",
                           sid=None, payload=ws_str))
        for si, m in enumerate(g["sessions"]):
            col, row = si % 2, si // 2
            cx = fx + (col - 0.5) * _COL_GAP - _CHAT_W / 2.0
            cy = fy + 200.0 + row * _ROW_GAP
            placed.append(dict(id=m.id, kind="chat", x=cx, y=cy, w=_CHAT_W, h=_CHAT_H, src=fid,
                               glyph="\U0001F4AC", text=(m.title or m.id)[:22], sid=m.id, payload=None))
            session_ws[m.id] = ws

    # séparer main / worktrees, regroupés par projet
    mains = [g for g in groups if g["scope"] == "main"]
    wts_by_pid: dict = {}
    for g in groups:
        if g["scope"] != "main":
            wts_by_pid.setdefault(g["pid"], []).append(g)

    # rangée du haut : folder main (1 fente) + node « worktrees » (réserve `nw` fentes pour ses worktrees,
    # sinon 2 worktrees+ se chevaucheraient horizontalement / déborderaient sur les voisins)
    items: list = []                 # (kind, payload, largeur_en_fentes)
    placed_pids: list = []
    for g in mains:
        items.append(("main", g, 1)); placed_pids.append(g["pid"])
        if g["pid"] in wts_by_pid:
            items.append(("wt", g["pid"], max(1, len(wts_by_pid[g["pid"]]))))
    for pid in wts_by_pid:                        # projets sans session main mais avec worktrees
        if pid not in placed_pids:
            items.append(("wt", pid, max(1, len(wts_by_pid[pid]))))

    total_slots = sum(w for _, _, w in items) or 1
    off = (total_slots - 1) / 2.0                # centre l'ensemble sur le kernel

    def _cluster_bottom(g, fy=220.0):            # profondeur réelle d'un cluster (anti-chevauchement vertical)
        nrows = (len(g["sessions"]) + 1) // 2 or 1
        return fy + 200.0 + (nrows - 1) * _ROW_GAP + max(_CHAT_H, _EXPLORER_H)
    wt_row_y = max([_cluster_bottom(g) for g in mains] + [420.0 + _EXPLORER_H]) + 140.0

    wt_start: dict = {}                          # pid -> fente de départ de la bande worktrees
    start = 0
    for kind, payload, w in items:
        cx = (start + (w - 1) / 2.0 - off) * _FOLDER_GAP    # centre de la fente (main) / bande (worktrees)
        if kind == "main":
            _place_group(payload, cx, 220.0, _KERNEL_ID)
        else:
            pid = payload
            proj = registry.get(pid) if registry else None
            nm = proj.name if proj else pid
            placed.append(dict(id=f"wtgroup:{pid}", kind="wtgroup", x=cx - 150.0, y=220.0, w=300.0, h=66.0,
                               src=_KERNEL_ID, glyph="\U0001F333", text=f"worktrees · {nm}",
                               sid=None, payload=None))
            wt_start[pid] = start
        start += w

    # worktrees rattachés SOUS leur node « worktrees », chacun dans SA fente (→ wtgroup → kernel)
    for pid, wl in wts_by_pid.items():
        s = wt_start.get(pid, 0)
        for wi, g in enumerate(wl):
            cx = (s + wi - off) * _FOLDER_GAP
            _place_group(g, cx, wt_row_y, f"wtgroup:{pid}")

    spawned: dict = {}   # (ws_str, rel) -> editor id
    eph_timers: dict = {}  # eid -> timer TTL (pour annulation au pin)
    dirs: dict = {}      # (ws_str, dir_rel) -> dir node id (groupement organique des éditeurs)
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

    def _ensure_dir(ws_str, rel, exp):
        """Crée (ou réutilise) un node dossier pour le dossier parent de `rel` → les éditeurs d'un même
        dossier s'y rattachent (groupement organique). Racine → parent = explorateur."""
        base = exp["id"] if exp else _KERNEL_ID
        dpath = posixpath.dirname(rel)
        if not dpath:
            return base
        dkey = (ws_str, dpath)
        if dkey in dirs:
            return dirs[dkey]
        seq["n"] += 1
        did = f"dir:{seq['n']}"
        dirs[dkey] = did
        n = len(dirs)
        dx = (exp["x"] - 250.0) if exp else -400.0
        dy = (exp["y"] if exp else 0.0) + 24.0 + n * 66.0
        with world:
            _build_node(dict(id=did, kind="dir", x=dx, y=dy, w=210.0, h=52.0, src=base,
                             glyph="\U0001F4C1", text=dpath.split("/")[-1] or dpath, sid=None, payload=None),
                        focus_sid, hub, author, explorers, _spawn_editor, _remove_editor)
        return did

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

        def _pin(_eid=eid) -> None:
            t = eph_timers.pop(_eid, None)
            if t is not None:
                try:
                    t.cancel()
                except Exception:
                    try:
                        t.active = False
                    except Exception:
                        pass
            ui.run_javascript(
                f"(()=>{{const w=document.querySelector('.node-wrap[data-id=\"{_eid}\"]');"
                f"if(w)w.classList.remove('ephemeral');}})()")

        dir_src = _ensure_dir(ws_str, rel, exp)
        with world:
            _build_node(dict(id=eid, kind="editor", x=ex, y=ey, w=_EDITOR_W, h=_EDITOR_H, src=dir_src,
                             glyph="✎", text=Path(rel).name, sid=None, payload={"ws": ws_str, "rel": rel}),
                        focus_sid, hub, author, explorers, _spawn_editor, _remove_editor,
                        ephemeral=ephemeral, close_key=key, on_pin=(_pin if ephemeral else None))

        def _after(_from=from_id, _eid=eid) -> None:
            ui.run_javascript("window.MekiCanvas && window.MekiCanvas.redraw();")
            ui.run_javascript(f"window.MekiCanvas && window.MekiCanvas.cometTo({json.dumps(_from)},{json.dumps(_eid)})")
        ui.timer(0.06, _after, once=True)
        if ephemeral:
            def _expire(_key=key, _eid=eid) -> None:
                if spawned.get(_key) == _eid:
                    _remove_editor(_key, _eid)
            eph_timers[eid] = ui.timer(_EPH_TTL_S, _expire, once=True)

    # --- 4. rendu initial ---
    with world:
        for p in placed:
            _build_node(p, focus_sid, hub, author, explorers, _spawn_editor, _remove_editor)

    # --- palette : ajouter des nodes à la volée ---
    _default_ws = str(groups[0]["ws"]) if groups else str(Path.cwd())
    pal = {"n": 0}

    def _spawn_generic(kind, payload, glyph, text, w, h) -> None:
        pal["n"] += 1
        nid = f"{kind}:pal:{pal['n']}"
        x, y = 220.0 + (pal["n"] % 3) * (w + 40.0), -260.0 - (pal["n"] // 3) * (h + 40.0)
        with world:
            _build_node(dict(id=nid, kind=kind, x=x, y=y, w=w, h=h, src=_KERNEL_ID,
                             glyph=glyph, text=text, sid=None, payload=payload),
                        focus_sid, hub, author, explorers, _spawn_editor, _remove_editor)

        def _after(_nid=nid) -> None:
            ui.run_javascript("window.MekiCanvas && window.MekiCanvas.redraw();")
            ui.run_javascript(f"window.MekiCanvas && window.MekiCanvas.cometTo('kernel',{json.dumps(_nid)})")
        ui.timer(0.06, _after, once=True)

    def _open_path_dialog() -> None:
        dlg = ui.dialog()
        with dlg, ui.card().classes("pal-dialog"):
            ui.label("Ouvrir un fichier (chemin relatif au workspace)").classes("pal-dlg-title")
            inp = ui.input(placeholder="ex. packages/mekicore/tools.py").classes("pal-dlg-in")

            def _go(_=None):
                rel = (inp.value or "").strip()
                if rel:
                    _spawn_editor(_default_ws, rel, _KERNEL_ID, ephemeral=False)
                dlg.close()

            inp.on("keydown.enter", _go)
            with ui.row():
                ui.button("Ouvrir", on_click=_go).props("flat").classes("pal-dlg-btn")
                ui.button("Annuler", on_click=dlg.close).props("flat").classes("pal-dlg-btn")
        dlg.open()

    def _open_worktree_dialog() -> None:
        projects = registry.list() if registry else []
        if not projects:
            ui.notify("aucun projet enregistré", type="warning")
            return
        dlg = ui.dialog()
        with dlg, ui.card().classes("pal-dialog"):
            ui.label("🌳 Nouveau worktree isolé").classes("pal-dlg-title")
            ui.label("crée <repo>/.worktrees/<nom>_<uuid> + une session dédiée (.env copié)").classes("pal-dlg-hint")
            name_in = ui.input(placeholder="nom (ex. feature-login)").classes("pal-dlg-in")
            proj_sel = None
            if len(projects) > 1:
                proj_sel = ui.select({p.id: p.name for p in projects}, value=projects[0].id,
                                     label="projet").classes("pal-dlg-in")
            busy = {"v": False}

            async def _go(_=None) -> None:
                nm = (name_in.value or "").strip()
                if not nm or busy["v"]:
                    return
                busy["v"] = True
                pid = proj_sel.value if proj_sel is not None else projects[0].id
                dlg.close()
                ui.notify(f"création du worktree « {nm} »…")
                try:
                    _cid, scope = await hub.create_worktree(pid, nm)
                    ui.notify(f"worktree « {scope} » créé ✓", type="positive")
                    ui.run_javascript("setTimeout(()=>location.reload(), 500)")
                except Exception as e:  # noqa: BLE001
                    busy["v"] = False
                    ui.notify(f"échec création worktree : {e}", type="negative")

            name_in.on("keydown.enter", _go)
            with ui.row():
                ui.button("Créer le worktree", on_click=_go).props("flat").classes("pal-dlg-btn")
                ui.button("Annuler", on_click=dlg.close).props("flat").classes("pal-dlg-btn")
        dlg.open()

    with canvas:
        with ui.element("div").classes("mc-palette"):
            with ui.element("div").classes("pal-trigger"):        # « + » → menu (ancré sur ce div seul)
                ui.label("＋")
                with ui.menu().classes("pal-menu"):
                    ui.menu_item("⌨  Terminal", lambda: _spawn_generic("terminal", _default_ws, "⌨", "terminal", 340.0, 220.0))
                    ui.menu_item("✎  Ouvrir un fichier…", _open_path_dialog)
                    ui.menu_item("🌳  Nouveau worktree…", _open_worktree_dialog)
            wt_btn = ui.element("div").classes("pal-trigger pal-wt")  # bouton dédié « nouveau worktree »
            with wt_btn:
                ui.label("🌳")
            wt_btn.on("click", lambda _=None: _open_worktree_dialog())

    ui.timer(0.25, lambda: ui.run_javascript("window.MekiCanvas && window.MekiCanvas.initWorld();"), once=True)

    # --- 5. abonnements par session : spawn éphémère + comète sur lecture de l'agent ---
    for sid, ws in session_ws.items():
        _start_file_watch(hub, sid, ws, _spawn_editor)


def _explorer_id_for(ws_str, explorers):
    e = explorers.get(str(ws_str))
    return e["id"] if e else _KERNEL_ID


def _build_node(p, focus_sid, hub, author, explorers, spawn_fn, remove_fn,
                *, ephemeral=False, close_key=None, on_pin=None) -> None:
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
                                         lambda _k=close_key, _id=p["id"]: remove_fn(_k, _id),
                                         ephemeral=ephemeral, on_pin=on_pin)
            elif kind == "git":
                body = ui.element("div").classes("nbody nbody-git")
                _render_git(body, p["payload"])
            elif kind == "terminal":
                body = ui.element("div").classes("nbody nbody-term")
                terminal_mod.render_terminal(body, p["payload"])
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
