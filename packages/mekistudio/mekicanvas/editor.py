"""editor.py — rendu d'un éditeur de code (ui.codemirror) dans une node canvas.

`render_editor(container, root, rel, on_close, *, ephemeral=False, on_pin=None)` : CodeMirror
(coloration par extension) + barre nom/modifié/[épingler]/[aperçu md]/sauver/fermer. Pour les `.md`,
toggle aperçu (ui.markdown). Le bouton 📌 (éphémères) appelle `on_pin()` pour rendre la node permanente.
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


def _git_diff(root, rel: str) -> str:
    import subprocess
    try:
        return subprocess.run(["git", "-C", str(root), "diff", "--no-color", "HEAD", "--", rel],
                              capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return ""


def render_editor(container, root, rel: str, on_close, *, ephemeral=False, on_pin=None) -> None:
    name = Path(rel).name
    is_md = language_for(rel) == "Markdown"
    st = {"cm": None, "dot": None, "preview": None, "host": None, "pin": None, "diff": None,
          "show_preview": False, "show_diff": False}

    def _set_dirty(v: bool) -> None:
        if st["dot"] is not None:
            st["dot"].style(f"visibility:{'visible' if v else 'hidden'}")

    def _save() -> None:
        if st["cm"] is None:
            return
        try:
            fs.write_text(root, rel, st["cm"].value or "")
            _set_dirty(False)
            ui.notify(f"{name} sauvé", type="positive")
        except Exception as e:  # noqa: BLE001
            ui.notify(f"Erreur sauvegarde : {e}", type="negative")

    def _toggle_preview() -> None:
        st["show_preview"] = not st["show_preview"]
        sp = st["show_preview"]
        if sp and st["preview"] is not None:
            st["preview"].set_content(st["cm"].value or "")
        if st["host"] is not None:
            st["host"].style(f"display:{'none' if sp else 'flex'}")
        if st["preview"] is not None:
            st["preview"].style(f"display:{'block' if sp else 'none'}")

    def _pin() -> None:
        if on_pin:
            on_pin()
        if st["pin"] is not None:
            st["pin"].style("display:none")

    def _toggle_diff() -> None:
        st["show_diff"] = not st["show_diff"]
        sd = st["show_diff"]
        if sd and st["diff"] is not None:
            st["diff"].clear()
            diff = _git_diff(root, rel)
            with st["diff"]:
                if not diff.strip():
                    ui.label("(aucune modification vs HEAD)").classes("diff-empty")
                else:
                    for line in diff.splitlines():
                        cls = "diff-line"
                        if line.startswith("+++") or line.startswith("---") or line.startswith(("diff ", "index ")):
                            cls += " meta"
                        elif line.startswith("+"):
                            cls += " add"
                        elif line.startswith("-"):
                            cls += " del"
                        elif line.startswith("@@"):
                            cls += " hunk"
                        ui.label(line or " ").classes(cls)
        st["show_preview"] = False
        if st["host"] is not None:
            st["host"].style(f"display:{'none' if sd else 'flex'}")
        if st["preview"] is not None:
            st["preview"].style("display:none")
        if st["diff"] is not None:
            st["diff"].style(f"display:{'block' if sd else 'none'}")

    with container:
        with ui.element("div").classes("editor-embed"):
            with ui.element("div").classes("editor-bar"):
                ui.label("✎ " + name).classes("editor-name")
                st["dot"] = ui.label("●").classes("editor-dirty")
                st["dot"].style("visibility:hidden")
                if ephemeral and on_pin:
                    st["pin"] = ui.button("📌", on_click=lambda: _pin()).props("flat dense").classes("editor-act").tooltip("épingler")
                if is_md:
                    ui.button("👁", on_click=lambda: _toggle_preview()).props("flat dense").classes("editor-act").tooltip("aperçu / éditer")
                ui.button("⇄", on_click=lambda: _toggle_diff()).props("flat dense").classes("editor-act").tooltip("diff vs HEAD")
                ui.button("💾", on_click=lambda: _save()).props("flat dense").classes("editor-act")
                ui.button("✕", on_click=lambda: on_close()).props("flat dense").classes("editor-act")
            try:
                content = fs.read_text(root, rel)
            except Exception as e:  # noqa: BLE001
                ui.label(f"⚠ {e}").classes("editor-err")
                return
            st["host"] = ui.element("div").classes("editor-cm")
            with st["host"]:
                st["cm"] = ui.codemirror(value=content, language=language_for(rel), theme="basicDark",
                                         line_wrapping=True, on_change=lambda _=None: _set_dirty(True))
            if is_md:
                st["preview"] = ui.markdown(content).classes("editor-preview")
                st["preview"].style("display:none")
            st["diff"] = ui.element("div").classes("editor-diff")
            st["diff"].style("display:none")
