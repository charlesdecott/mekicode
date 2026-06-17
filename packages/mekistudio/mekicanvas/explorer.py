"""explorer.py — arbre de fichiers lazy (NiceGUI) sandboxé à une racine de workspace.

`render_explorer(container, root, on_open)` : dossiers en `ui.expansion` (enfants chargés au 1er expand
via fs.list_dir), fichiers en ligne cliquable (double-clic → on_open(rel_posix)). Pur NiceGUI.
"""
from __future__ import annotations

from nicegui import ui

from . import fs


def render_explorer(container, root, on_open, *, excludes=fs.DEFAULT_EXCLUDES) -> None:
    with container:
        tree = ui.element("div").classes("fs-tree")
    _render_dir(tree, root, "", on_open, excludes)


def _render_dir(parent, root, rel: str, on_open, excludes) -> None:
    try:
        entries = fs.list_dir(root, rel, excludes)
    except Exception as e:  # noqa: BLE001
        with parent:
            ui.label(f"⚠ {e}").classes("fs-err")
        return
    with parent:
        for entry in entries:
            if entry["kind"] == "dir":
                exp = ui.expansion(entry["name"]).props("dense").classes("fs-dir")
                loaded = {"v": False}

                def _on_change(ev, _exp=exp, _path=entry["path"], _loaded=loaded) -> None:
                    if getattr(ev, "value", False) and not _loaded["v"]:
                        _loaded["v"] = True
                        _render_dir(_exp, root, _path, on_open, excludes)

                exp.on_value_change(_on_change)
            else:
                row = ui.element("div").classes("fs-file")
                with row:
                    ui.label("📄").classes("fs-ico")
                    ui.label(entry["name"]).classes("fs-name")
                row.on("click", lambda _=None, p=entry["path"]: on_open(p))
