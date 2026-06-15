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


def _safe_path(p: str, ws: Path | None = None) -> Path:
    """Résout p dans le workspace ; lève ValueError s'il s'en échappe (absolu hors racine, ../)."""
    ws = ws if ws is not None else _workspace()
    target = (ws / p).resolve()
    if target != ws and ws not in target.parents:
        raise ValueError(f"chemin hors du workspace : {p}")
    return target


def run_bash(command: str, cwd: Path | None = None) -> str:
    """Exécute une commande shell (timeout 120 s), sortie tronquée à 50k chars."""
    if any(b in command for b in _ALWAYS_BLOCK):
        return "Error: dangerous command blocked"
    effective_cwd = str(cwd) if cwd else os.getcwd()
    try:
        r = subprocess.run(
            command, shell=True, cwd=effective_cwd,
            capture_output=True, text=True, timeout=120,
        )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: timeout (120s)"
    except Exception as e:
        return f"Error: {e}"


def read_file(path: str, ws: Path | None = None) -> str:
    """Lit un fichier texte (confiné au workspace)."""
    ws = ws if ws is not None else _workspace()
    try:
        p = _safe_path(path, ws)
    except ValueError as e:
        return f"Error: {e}"
    if not p.is_file():
        return f"Error: fichier introuvable : {path}"
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:_MAX_OUT]
    except OSError as e:
        return f"Error: {e}"


def write_file(path: str, content: str, ws: Path | None = None) -> str:
    """Crée ou écrase un fichier texte (crée les dossiers parents)."""
    ws = ws if ws is not None else _workspace()
    try:
        p = _safe_path(path, ws)
    except ValueError as e:
        return f"Error: {e}"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    except (OSError, ValueError) as e:
        return f"Error: {e}"
    return f"écrit {len(content)} caractères dans {path}"


def edit_file(path: str, old: str, new: str, ws: Path | None = None) -> str:
    """Remplace `old` par `new` si `old` apparaît exactement une fois (str-replace)."""
    ws = ws if ws is not None else _workspace()
    try:
        p = _safe_path(path, ws)
    except ValueError as e:
        return f"Error: {e}"
    if not p.is_file():
        return f"Error: fichier introuvable : {path}"
    try:
        content = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return f"Error: {e}"
    count = content.count(old)
    if count == 0:
        return "Error: texte introuvable (old)"
    if count > 1:
        return f"Error: texte ambigu ({count} occurrences) — ajoute du contexte"
    try:
        p.write_text(content.replace(old, new, 1), encoding="utf-8")
    except OSError as e:
        return f"Error: {e}"
    return f"édité {path}"


def grep_files(pattern: str, path: str = ".", ws: Path | None = None) -> str:
    """Cherche une regex dans les fichiers texte sous `path` (confiné). Renvoie relpath:ligne: contenu."""
    ws = ws if ws is not None else _workspace()
    try:
        root = _safe_path(path, ws)
        rx = re.compile(pattern)
    except ValueError as e:
        return f"Error: {e}"
    except re.error as e:
        return f"Error: regex invalide : {e}"
    try:
        candidates = [root] if root.is_file() else sorted(root.rglob("*"))
    except (OSError, ValueError) as e:
        return f"Error: {e}"
    results: list[str] = []
    for f in candidates:
        if not f.is_file():
            continue
        rf = f.resolve()
        if rf != ws and ws not in rf.parents:
            continue  # symlink qui s'échappe du workspace : on saute
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


def glob_files(pattern: str, ws: Path | None = None) -> str:
    """Liste les fichiers correspondant au motif (ex. **/*.py) sous le workspace, chemins relatifs.
    Ignore les correspondances qui s'échappent du workspace (motifs avec ../, absolus)."""
    ws = ws if ws is not None else _workspace()
    matches: list[str] = []
    try:
        for p in ws.glob(pattern):
            rp = p.resolve()
            if p.is_file() and (rp == ws or ws in rp.parents):
                matches.append(str(rp.relative_to(ws)))
    except (ValueError, NotImplementedError) as e:
        return f"Error: motif invalide : {e}"
    if not matches:
        return "(aucun fichier)"
    return "\n".join(sorted(matches)[:1000])


def make_dispatch(workspace) -> dict:
    """Construit un DISPATCH dont les handlers fichiers sont confinés à `workspace` (Path absolu)."""
    ws = Path(workspace).resolve()
    return {
        "bash":  lambda a: run_bash(a["command"], cwd=ws),
        "read":  lambda a: read_file(a["path"], ws),
        "write": lambda a: write_file(a["path"], a["content"], ws),
        "edit":  lambda a: edit_file(a["path"], a["old"], a["new"], ws),
        "grep":  lambda a: grep_files(a["pattern"], a.get("path", "."), ws),
        "glob":  lambda a: glob_files(a["pattern"], ws),
    }


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
