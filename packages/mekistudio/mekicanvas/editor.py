"""editor.py — rendu d'un éditeur de code (ui.codemirror natif) dans une node canvas.

`render_editor(container, root, rel, on_close)` : lit `rel` (sandboxé sous `root`) dans un CodeMirror,
barre nom/modifié/sauver/fermer. Ctrl+S et le bouton sauvent (write_text atomique). Pur NiceGUI.
"""
from __future__ import annotations

from pathlib import Path

from nicegui import ui

from . import fs

_LANG = {
    ".py": "Python", ".pyi": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TSX", ".jsx": "JSX", ".json": "JSON", ".md": "Markdown",
    ".css": "CSS", ".scss": "CSS", ".html": "HTML", ".htm": "HTML", ".xml": "XML", ".svg": "XML",
    ".yaml": "YAML", ".yml": "YAML", ".toml": "TOML", ".sql": "SQL", ".sh": "Shell", ".bash": "Shell",
    ".ps1": "Shell", ".rs": "Rust", ".go": "Go", ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++",
    ".hpp": "C++", ".java": "Java",
}


def language_for(rel: str):
    return _LANG.get(Path(rel).suffix.lower())


def render_editor(container, root, rel: str, on_close) -> None:
    name = Path(rel).name
    state = {"dirty": False, "cm": None, "dot": None}

    def _set_dirty(v: bool) -> None:
        state["dirty"] = v
        if state["dot"] is not None:
            state["dot"].style(f"visibility:{'visible' if v else 'hidden'}")

    def _save() -> None:
        cm = state["cm"]
        if cm is None:
            return
        try:
            fs.write_text(root, rel, cm.value or "")
            _set_dirty(False)
            ui.notify(f"{name} sauvé", type="positive")
        except Exception as e:  # noqa: BLE001
            ui.notify(f"Erreur sauvegarde : {e}", type="negative")

    with container:
        with ui.element("div").classes("editor-embed"):
            with ui.element("div").classes("editor-bar"):
                ui.label("✎ " + name).classes("editor-name")
                state["dot"] = ui.label("●").classes("editor-dirty")
                state["dot"].style("visibility:hidden")
                ui.button("💾", on_click=lambda: _save()).props("flat dense").classes("editor-act")
                ui.button("✕", on_click=lambda: on_close()).props("flat dense").classes("editor-act")
            try:
                content = fs.read_text(root, rel)
            except Exception as e:  # noqa: BLE001
                ui.label(f"⚠ {e}").classes("editor-err")
                return
            state["cm"] = ui.codemirror(
                value=content, language=language_for(rel), theme="basicDark",
                line_wrapping=True, on_change=lambda _=None: _set_dirty(True),
            ).classes("editor-cm")
