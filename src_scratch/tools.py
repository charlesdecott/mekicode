"""tools.py — outils du harness : implémentations sync/async, schémas, registre, background.

Reprend les 6 outils de la source (bash, read, write, grep, glob, revert — s02/s14),
ajoute le registre dynamique `register_tool` et l'exécution en arrière-plan (s08).
Convention : un handler de dispatch reçoit le dict `input` complet et renvoie une str.
"""
import asyncio
import glob as _glob
import os
import queue
import subprocess
import threading
import uuid
from typing import Callable, Optional

from core import drain_queue, paint

# s14 — snapshots pour revert : chemin -> contenu avant écriture (None = fichier créé).
SNAPSHOTS: dict[str, Optional[str]] = {}

# Liste noire testée par sous-chaîne — filet grossier, la vraie politique est dans config.yaml.
_ALWAYS_BLOCK = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/", ":(){ :|:& };:"]
_BLOCK_MSG = "Error: dangerous command blocked"


def _blocked(command: str) -> bool:
    """Vrai si `command` contient un motif de la liste noire (filet grossier)."""
    return any(b in command for b in _ALWAYS_BLOCK)


# --- Implémentations synchrones ----------------------------------------------

def run_bash(command: str) -> str:
    """Commande shell : blocklist, timeout 120 s, sortie plafonnée à 50 000 car."""
    if _blocked(command):
        return _BLOCK_MSG
    try:
        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: timeout (120s)"
    except Exception as e:
        return f"Error: {e}"


def run_read(path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
    """Lit un fichier avec numérotation absolue des lignes (tranche 1-indexée optionnelle)."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        start = (start_line or 1) - 1
        end = end_line or len(lines)
        numbered = "".join(f"{start + 1 + i:4d}\t{line}" for i, line in enumerate(lines[start:end]))
        return numbered[:50000] or "(empty file)"
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except Exception as e:
        return f"Error reading {path}: {e}"


def run_write(path: str, content: str) -> str:
    """Écrit un fichier après snapshot de l'état précédent (undo à un niveau)."""
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                SNAPSHOTS[path] = f.read()
            action = "updated"
        else:
            SNAPSHOTS[path] = None
            action = "created"
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"{action}: {path} (snapshot saved — use revert to undo)"
    except Exception as e:
        return f"Error writing {path}: {e}"


def run_grep(pattern: str, path: str = ".", recursive: bool = True) -> str:
    """Recherche regex via grep système, repli findstr sous Windows. Cap 10 000 car."""
    try:
        flags = ["-r"] if recursive else []
        r = subprocess.run(["grep", "-n", *flags, pattern, path],
                           capture_output=True, text=True, timeout=30)
        return ((r.stdout + r.stderr).strip() or "(no matches)")[:10000]
    except FileNotFoundError:
        try:
            cmd = f'findstr /S /N "{pattern}" "{path}\\*.py" "{path}\\*.js" "{path}\\*.md"'
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return ((r.stdout + r.stderr).strip() or "(no matches)")[:10000]
        except Exception as e:
            return f"Error: grep/findstr failed: {e}"
    except subprocess.TimeoutExpired:
        return "Error: grep timeout"
    except Exception as e:
        return f"Error: {e}"


def run_glob(pattern: str) -> str:
    """Fichiers correspondant au motif glob (récursif), triés, cap 200 chemins."""
    matches = _glob.glob(pattern, recursive=True)
    return "\n".join(sorted(matches)[:200]) if matches else "(no matches)"


def run_revert(path: str) -> str:
    """Restaure l'état pré-écriture depuis SNAPSHOTS (consommé au passage)."""
    if path not in SNAPSHOTS:
        return f"Error: no snapshot for {path}"
    original = SNAPSHOTS.pop(path)
    try:
        if original is None:
            os.remove(path)
            return f"reverted: deleted {path} (it was a new file)"
        with open(path, "w", encoding="utf-8") as f:
            f.write(original)
        return f"reverted: {path}"
    except Exception as e:
        return f"Error reverting {path}: {e}"


# --- bash async natif (les autres outils : sync déporté en thread, voir _as_async) --

async def async_bash(command: str) -> str:
    """Version async native de run_bash (sous-processus non bloquant)."""
    if _blocked(command):
        return _BLOCK_MSG
    try:
        proc = await asyncio.create_subprocess_shell(
            command, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=os.getcwd())
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        out = (stdout.decode() + stderr.decode()).strip()
        return out[:50000] if out else "(no output)"
    except asyncio.TimeoutError:
        return "Error: timeout (120s)"
    except Exception as e:
        return f"Error: {e}"


# --- Schémas et tables de dispatch (= EXTENDED_TOOLS/EXTENDED_DISPATCH source) --

TOOLS: list[dict] = [
    {"name": "bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}},
                      "required": ["command"]}},
    {"name": "read",
     "description": "Read a file. Optional start_line/end_line for a range (1-indexed).",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string"}, "start_line": {"type": "integer"},
         "end_line": {"type": "integer"}}, "required": ["path"]}},
    {"name": "write",
     "description": "Write content to a file. Snapshots previous content automatically.",
     "input_schema": {"type": "object", "properties": {
         "path": {"type": "string"}, "content": {"type": "string"}},
         "required": ["path", "content"]}},
    {"name": "grep", "description": "Search for a regex pattern in files under a path.",
     "input_schema": {"type": "object", "properties": {
         "pattern": {"type": "string"}, "path": {"type": "string", "default": "."},
         "recursive": {"type": "boolean", "default": True}}, "required": ["pattern"]}},
    {"name": "glob", "description": "Find files matching a glob pattern, e.g. '**/*.py'.",
     "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}},
                      "required": ["pattern"]}},
    {"name": "revert", "description": "Restore a file to its state before the last write.",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}},
                      "required": ["path"]}},
]

DISPATCH: dict[str, Callable] = {
    "bash":   lambda inp: run_bash(inp["command"]),
    "read":   lambda inp: run_read(inp["path"], inp.get("start_line"), inp.get("end_line")),
    "write":  lambda inp: run_write(inp["path"], inp["content"]),
    "grep":   lambda inp: run_grep(inp["pattern"], inp.get("path", "."), inp.get("recursive", True)),
    "glob":   lambda inp: run_glob(inp["pattern"]),
    "revert": lambda inp: run_revert(inp["path"]),
}


def _as_async(sync_fn: Callable) -> Callable:
    """Dérive un handler async d'un handler sync : exécution déportée hors event loop."""
    return lambda inp: asyncio.to_thread(sync_fn, inp)


# Async = sync déporté en thread, SAUF bash (async natif). revert inclus via la dérivation (FIX).
ASYNC_DISPATCH: dict[str, Callable] = {name: _as_async(fn) for name, fn in DISPATCH.items()}
ASYNC_DISPATCH["bash"] = lambda inp: async_bash(inp["command"])


def register_tool(schema: dict, sync_fn: Callable | None = None,
                  async_fn: Callable | None = None) -> None:
    """Ajoute (ou remplace) un outil dans TOOLS, DISPATCH et ASYNC_DISPATCH.

    Les handlers prennent le dict input complet. Si une seule version est fournie,
    l'autre est dérivée : async = to_thread(sync), sync = asyncio.run(async).
    """
    name = schema["name"]
    if sync_fn is None and async_fn is None:
        raise ValueError(f"register_tool({name!r}): fournir sync_fn et/ou async_fn")
    if async_fn is None:
        async_fn = _as_async(sync_fn)
    if sync_fn is None:
        sync_fn = lambda inp: asyncio.run(async_fn(inp))  # noqa: E731
    TOOLS[:] = [t for t in TOOLS if t["name"] != name] + [schema]
    DISPATCH[name] = sync_fn
    ASYNC_DISPATCH[name] = async_fn


# --- s08 : exécution en arrière-plan + notifications ---------------------------

NOTIFICATIONS: queue.Queue = queue.Queue()


def run_bash_background(command: str) -> str:
    """Lance `command` dans un thread daemon ; le résultat arrive via NOTIFICATIONS.

    FIX(mekicode): applique _ALWAYS_BLOCK — la source (s08) laissait le fond
    contourner la liste noire appliquée au bash synchrone.
    """
    if _blocked(command):
        return _BLOCK_MSG
    bg_id = uuid.uuid4().hex[:6]

    def _worker():
        print(paint(f"  [bg {bg_id}] démarré : {command[:60]}", "dim"))
        try:
            r = subprocess.run(command, shell=True, capture_output=True,
                               text=True, timeout=300, cwd=os.getcwd())
            out = (r.stdout + r.stderr).strip()[:2000] or "(no output)"
        except subprocess.TimeoutExpired:
            out = "Error: timeout (300s)"
        except Exception as e:
            out = f"Error: {e}"
        NOTIFICATIONS.put(f"[bg {bg_id}] terminé: {out}")

    threading.Thread(target=_worker, daemon=True).start()
    return f"Background task [{bg_id}] started: '{command[:60]}'. Result will arrive as a notification."


def drain_notifications() -> list[str]:
    """Vide la file de notifications sans bloquer."""
    return drain_queue(NOTIFICATIONS)


register_tool(
    {"name": "bash_background",
     "description": "Run a slow shell command in the background (tests, builds, long scripts). "
                    "Returns immediately; the result arrives later as a notification.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}},
                      "required": ["command"]}},
    sync_fn=lambda inp: run_bash_background(inp["command"]),
)
