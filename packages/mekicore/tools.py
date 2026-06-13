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


# Schéma au format function-calling OpenAI (lingua franca OpenRouter/ollama/litellm).
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
]

# Table de routage nom d'outil → handler(args: dict) -> str.
DISPATCH = {"bash": lambda args: run_bash(args["command"])}
