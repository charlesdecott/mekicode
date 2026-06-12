"""tools.py — outils de mekicore (s01 adapté), au format function-calling OpenAI."""
from __future__ import annotations

import os
import subprocess

# Fragments de commande toujours bloqués (sécurité, repris de s01).
_ALWAYS_BLOCK = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/", ":(){ :|:& };:"]


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
