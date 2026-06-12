"""core.py — socle du harness : config, client Anthropic, gouvernance, event bus, couleurs.

Refonte dédupliquée de inspiration/claude-code-from-scratch (core.py + s15 + s16).
Hooks de l'event bus : appelés `hook(event, payload)` ; un retour False vaut veto.
"""
import json
import os
import queue
import re
import sys
from pathlib import Path

# FIX(mekicode): console Windows en cp1252 — les caractères → ou ≈ des affichages
# (stats de cache…) feraient crasher print, et un pipe UTF-8 vers stdin serait
# décodé de travers. UTF-8 + replace partout, AVANT le wrap colorama.
for _stream in (sys.stdout, sys.stderr, sys.stdin):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# Dépendances optionnelles de confort terminal (comme la source).
try:
    import readline
    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
except ImportError:
    pass
try:
    from colorama import init as _colorama_init
    _colorama_init()
except ImportError:
    pass

import yaml
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv(override=True)
if os.getenv("ANTHROPIC_BASE_URL"):
    # Purge le token résiduel pour ne pas l'envoyer vers un gateway tiers.
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

client: Anthropic = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL: str = os.environ.get("MODEL_ID", "claude-sonnet-4-6")
DEFAULT_SYSTEM: str = (
    f"You are a coding agent at {os.getcwd()}. Use tools to solve tasks. Act, don't explain."
)

ROOT: Path = Path(__file__).parent
STATE_DIR: Path = Path(os.environ.get("MEKI_STATE_DIR", ROOT / ".state"))
STATE_DIR.mkdir(parents=True, exist_ok=True)
# FIX(mekicode): chemin ancré sur ROOT — la source visait parent.parent (hors repo)
# et tournait silencieusement sans aucune règle.
CONFIG_PATH: Path = ROOT / "config.yaml"

_ANSI = {"red": "31", "green": "32", "yellow": "33", "cyan": "36", "magenta": "35", "dim": "90"}


def paint(text: str, color: str) -> str:
    """Colore `text` en ANSI (red/green/yellow/cyan/magenta/dim)."""
    return f"\033[{_ANSI.get(color, '0')}m{text}\033[0m"


_CONFIG: dict | None = None


def load_config() -> dict:
    """config.yaml complet, mis en cache module. Dict vide si absent."""
    global _CONFIG
    if _CONFIG is None:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                _CONFIG = yaml.safe_load(f) or {}
        except FileNotFoundError:
            _CONFIG = {}
    return _CONFIG


def load_rules() -> dict:
    """Section `permissions` du config.yaml — trois tiers, listes vides par défaut."""
    perms = load_config().get("permissions") or {}
    return {tier: perms.get(tier) or [] for tier in ("always_deny", "always_allow", "ask_user")}


def check_permission(tool_name: str, input_str: str, rules: dict | None = None) -> tuple[bool, str]:
    """Gouvernance trois tiers (s15) : deny → allow → ask → allow par défaut."""
    rules = rules if rules is not None else load_rules()
    for rule in rules.get("always_deny", []):
        if re.search(rule["pattern"], input_str, re.IGNORECASE):
            reason = rule.get("reason", "blocked by policy")
            print(paint(f"[DENIED] {reason}", "red"))
            return False, f"Denied: {reason}"
    for rule in rules.get("always_allow", []):
        if re.search(rule["pattern"], input_str, re.IGNORECASE):
            return True, "allowed by policy"
    for rule in rules.get("ask_user", []):
        if re.search(rule["pattern"], input_str, re.IGNORECASE):
            reason = rule.get("reason", "requires user confirmation")
            print(paint(f"\n[PERMISSION] {tool_name}: {input_str[:100]}\n  Raison : {reason}", "yellow"))
            try:
                ans = input("  Autoriser ? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            return (ans in ("y", "yes")), "user decision"
    return True, "allowed by default (no rule matched)"


# --- Event bus (s16) ---------------------------------------------------------
# Événements émis par le harness : session_start, user_message, pre_tool,
# post_tool, assistant_message, session_end.
HOOKS: dict[str, list] = {}


def on(event: str, hook) -> None:
    """Abonne `hook(event, payload)` à `event`."""
    HOOKS.setdefault(event, []).append(hook)


def emit(event: str, payload: dict) -> bool:
    """Émet `event` vers tous les hooks. False si l'un d'eux renvoie False (veto).

    FIX(mekicode): une exception de hook est loggée en rouge — la source (s16)
    l'avalait en silence, neutralisant les hooks de sécurité.
    """
    ok = True
    for hook in HOOKS.get(event, []):
        try:
            if hook(event, payload) is False:
                ok = False
        except Exception as e:
            print(paint(f"[hooks] erreur dans un hook '{event}': {e}", "red"))
    return ok


# --- Utilitaires partagés ------------------------------------------------------

def text_of(message) -> str:
    """Concatène les blocs texte d'une réponse API (ignore tool_use et autres blocs)."""
    return "".join(getattr(b, "text", "") for b in message.content)


def drain_queue(q: queue.Queue) -> list:
    """Vide une file sans bloquer ; retourne la liste des éléments en attente."""
    out = []
    while True:
        try:
            out.append(q.get_nowait())
        except queue.Empty:
            return out


def write_json(path: Path, data) -> None:
    """Écrit `data` en JSON indenté UTF-8 — format unique de persistance du harness."""
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
