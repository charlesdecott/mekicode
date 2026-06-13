"""tools.py — outils de mekicore au format function-calling OpenAI.

bash + outils de fichiers (read/write/edit/grep/glob) **confinés à un workspace**
(racine = cwd par défaut, surchargeable par MEKICORE_WORKSPACE). bash reste non confiné.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

_ALWAYS_BLOCK = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/", ":(){ :|:& };:"]
_MAX_OUT = 50000


def _workspace() -> Path:
    """Racine du workspace (lue à chaque appel : surchargeable par MEKICORE_WORKSPACE)."""
    return Path(os.environ.get("MEKICORE_WORKSPACE") or os.getcwd()).resolve()


def _safe_path(p: str) -> Path:
    """Résout p dans le workspace ; lève ValueError s'il s'en échappe (absolu hors racine, ../)."""
    ws = _workspace()
    target = (ws / p).resolve()
    if target != ws and ws not in target.parents:
        raise ValueError(f"chemin hors du workspace : {p}")
    return target


def run_bash(command: str) -> str:
    """Exécute une commande shell (timeout 120 s), sortie tronquée à 50k chars."""
    if any(b in command for b in _ALWAYS_BLOCK):
        return "Error: dangerous command blocked"
    try:
        r = subprocess.run(
            command, shell=True, cwd=os.getcwd(),
            capture_output=True, text=True, timeout=120,
        )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: timeout (120s)"
    except Exception as e:
        return f"Error: {e}"


def read_file(path: str) -> str:
    """Lit un fichier texte (confiné au workspace)."""
    try:
        p = _safe_path(path)
    except ValueError as e:
        return f"Error: {e}"
    if not p.is_file():
        return f"Error: fichier introuvable : {path}"
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:_MAX_OUT]
    except OSError as e:
        return f"Error: {e}"


def write_file(path: str, content: str) -> str:
    """Crée ou écrase un fichier texte (crée les dossiers parents)."""
    try:
        p = _safe_path(path)
    except ValueError as e:
        return f"Error: {e}"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    except OSError as e:
        return f"Error: {e}"
    return f"écrit {len(content)} caractères dans {path}"


def edit_file(path: str, old: str, new: str) -> str:
    """Remplace `old` par `new` si `old` apparaît exactement une fois (str-replace)."""
    try:
        p = _safe_path(path)
    except ValueError as e:
        return f"Error: {e}"
    if not p.is_file():
        return f"Error: fichier introuvable : {path}"
    content = p.read_text(encoding="utf-8")
    count = content.count(old)
    if count == 0:
        return "Error: texte introuvable (old)"
    if count > 1:
        return f"Error: texte ambigu ({count} occurrences) — ajoute du contexte"
    p.write_text(content.replace(old, new, 1), encoding="utf-8")
    return f"édité {path}"


def grep_files(pattern: str, path: str = ".") -> str:
    """Cherche une regex dans les fichiers texte sous `path` (confiné). Renvoie relpath:ligne: contenu."""
    try:
        root = _safe_path(path)
        rx = re.compile(pattern)
    except ValueError as e:
        return f"Error: {e}"
    except re.error as e:
        return f"Error: regex invalide : {e}"
    ws = _workspace()
    candidates = [root] if root.is_file() else sorted(root.rglob("*"))
    results: list[str] = []
    for f in candidates:
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # binaire / illisible : on saute
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                results.append(f"{f.relative_to(ws)}:{i}: {line.strip()[:200]}")
                if len(results) >= 200:
                    break
        if len(results) >= 200:
            break
    if not results:
        return "(aucun résultat)"
    return "\n".join(results)[:_MAX_OUT]


def glob_files(pattern: str) -> str:
    """Liste les fichiers correspondant au motif (ex. **/*.py) sous le workspace, chemins relatifs."""
    ws = _workspace()
    try:
        matches = sorted(str(p.relative_to(ws)) for p in ws.glob(pattern) if p.is_file())
    except ValueError as e:
        return f"Error: motif invalide : {e}"
    if not matches:
        return "(aucun fichier)"
    return "\n".join(matches[:1000])


def _tool(name: str, desc: str, props: dict, required: list) -> dict:
    """Construit un schéma function-calling OpenAI."""
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": required},
    }}


# Schémas au format function-calling OpenAI (ce que le modèle voit).
TOOLS = [
    _tool("bash", "Run a shell command.", {"command": {"type": "string"}}, ["command"]),
    _tool("read", "Read a text file (path relative to the workspace).",
          {"path": {"type": "string"}}, ["path"]),
    _tool("write", "Create or overwrite a text file (path relative to the workspace).",
          {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
    _tool("edit", "Replace an exact, unique snippet in a file (str-replace).",
          {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
          ["path", "old", "new"]),
    _tool("grep", "Search a regex in files under a path (relative to the workspace).",
          {"pattern": {"type": "string"}, "path": {"type": "string"}}, ["pattern"]),
    _tool("glob", "List files matching a glob pattern (e.g. **/*.py) under the workspace.",
          {"pattern": {"type": "string"}}, ["pattern"]),
]

# Routage nom d'outil → handler(args: dict) -> str.
DISPATCH = {
    "bash": lambda a: run_bash(a["command"]),
    "read": lambda a: read_file(a["path"]),
    "write": lambda a: write_file(a["path"], a["content"]),
    "edit": lambda a: edit_file(a["path"], a["old"], a["new"]),
    "grep": lambda a: grep_files(a["pattern"], a.get("path", ".")),
    "glob": lambda a: glob_files(a["pattern"]),
}
