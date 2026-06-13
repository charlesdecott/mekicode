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
