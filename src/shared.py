"""shared.py — bibliothèque commune du harness mekicode.

Code dédupliqué du repo pédagogique learn-claude-code : source principale s20_comprehensive/code.py
(qui ré-assemble les mécanismes de s01-s19), complété par le sous-système mémoire de s09_memory/code.py
(absent de s20, qui ne lisait que MEMORY.md). Différences avec s20 : pas de main/CLI/REPL — uniquement
fonctions, classes et registres importables par les sessions src/sNN.py ; agent_loop est paramétrable
(tools/handlers/system à None = registres complets, comportement s20) ; les corrections sont marquées
« FIX(mekicode): ... ». L'état global module-level de s20 (registres, locks, mkdir, thread cron) est
conservé tel quel.
"""

import ast, json, os, subprocess, time, random, threading, re
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict, field
import yaml

try:
    import readline
    readline.parse_and_bind('set bind-tty-special-chars off')
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False

from anthropic import Anthropic
from dotenv import load_dotenv

# ── Config & console ──

load_dotenv(override=True)
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]
PRIMARY_MODEL = MODEL
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL_ID")

# Budgets de tokens / retry (s11) et seuils de compaction (s08).
# Attention : les seuils de contexte sont en CARACTÈRES JSON, pas en tokens.
DEFAULT_MAX_TOKENS = 8000; ESCALATED_MAX_TOKENS = 16000
MAX_RETRIES = 3; MAX_CONSECUTIVE_529 = 2; MAX_RECOVERY_RETRIES = 2; BASE_DELAY_MS = 500
CONTEXT_LIMIT = 50000; KEEP_RECENT_TOOL_RESULTS = 3; PERSIST_THRESHOLD = 30000
CONTINUATION_PROMPT = "Continue from the previous response. Do not repeat completed work."
PROMPT = "\033[36m>> \033[0m"; CLI_ACTIVE = False

def terminal_print(text: str):
    """Affichage thread-safe : redessine la ligne readline si un thread d'arrière-plan parle pendant la saisie."""
    if threading.current_thread() is threading.main_thread() or not CLI_ACTIVE:
        print(text)
        return
    line = ""
    if READLINE_AVAILABLE:
        try: line = readline.get_line_buffer()
        except Exception: line = ""
    print(f"\r\033[K{text}")
    print(PROMPT + line, end="", flush=True)

# ── Sécurité fichiers ──

WORKDIR = Path.cwd()

def safe_path(p: str, cwd: Path = None) -> Path:
    """Confine les outils fichiers au workspace (ou au worktree d'un teammate) ; bash reste contrôlé par le hook."""
    base = cwd or WORKDIR
    path = (base / p).resolve()
    if not path.is_relative_to(base): raise ValueError(f"Path escapes workspace: {p}")
    return path

# ── Outils de base ──

def _tool(name: str, desc: str, _required=(), _schema_key="input_schema", /, **props) -> dict:
    """Fabrique de schéma d'outil : object + properties + required (4e arg positionnel : inputSchema pour MCP)."""
    return {"name": name, "description": desc,
            _schema_key: {"type": "object", "properties": props, "required": list(_required)}}

_STR = {"type": "string"}; _INT = {"type": "integer"}; _BOOL = {"type": "boolean"}

def run_bash(command: str, cwd: Path = None, run_in_background: bool = False) -> str:
    """Exécute une commande shell ; run_in_background est consommé par le dispatcher (should_run_background)."""
    try:
        r = subprocess.run(command, shell=True, cwd=cwd or WORKDIR, capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired: return "Error: Timeout (120s)"

def run_read(path: str, limit: int | None = None, offset: int = 0, cwd: Path = None) -> str:
    """Lecture paginée d'un fichier, avec marqueur « ... (N more lines) »."""
    try:
        lines = safe_path(path, cwd).read_text().splitlines()[max(int(offset or 0), 0):]
        limit = int(limit) if limit is not None else None
        if limit is not None and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)
    except Exception as e: return f"Error: {e}"

def run_write(path: str, content: str, cwd: Path = None) -> str:
    """Écrit un fichier (crée les répertoires parents)."""
    try:
        fp = safe_path(path, cwd)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e: return f"Error: {e}"

def run_edit(path: str, old_text: str, new_text: str, cwd: Path = None) -> str:
    """Remplacement exact et unique (le pattern Edit en miniature)."""
    try:
        fp = safe_path(path, cwd)
        text = fp.read_text()
        if old_text not in text: return f"Error: text not found in {path}"
        fp.write_text(text.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e: return f"Error: {e}"

def run_glob(pattern: str, cwd: Path = None) -> str:
    """glob.glob confiné : re-filtre les motifs qui s'échappent (../...)."""
    import glob as g
    try:
        base = cwd or WORKDIR
        results = [m for m in g.glob(pattern, root_dir=base) if (base / m).resolve().is_relative_to(base)]
        return "\n".join(results) if results else "(no matches)"
    except Exception as e: return f"Error: {e}"

def call_tool_handler(handler, args: dict, name: str) -> str:
    """Dispatch universel : handler(**args), TypeError → message d'erreur retourné au modèle plutôt qu'un crash."""
    if not handler: return f"Unknown: {name}"
    try: return handler(**(args or {}))
    except TypeError as e: return f"Error: {e}"

# ── Todos (s05) ──

# Todos en mémoire seulement (plan léger de session) ; le task graph durable (.tasks/) coordonne inter-sessions.
CURRENT_TODOS: list[dict] = []

def _normalize_todos(todos):
    """Accepte liste, chaîne JSON ou littéral Python, puis valide chaque item (content, status)."""
    if isinstance(todos, str):
        try:
            todos = json.loads(todos)
        except json.JSONDecodeError:
            try: todos = ast.literal_eval(todos)
            except (SyntaxError, ValueError): return None, "Error: todos must be a list or JSON array string"
    if not isinstance(todos, list): return None, "Error: todos must be a list"
    for i, todo in enumerate(todos):
        if not isinstance(todo, dict): return None, f"Error: todos[{i}] must be an object"
        if "content" not in todo or "status" not in todo:
            return None, f"Error: todos[{i}] missing 'content' or 'status'"
        if todo["status"] not in ("pending", "in_progress", "completed"):
            return None, f"Error: todos[{i}] has invalid status '{todo['status']}'"
    return todos, None

def run_todo_write(todos: list) -> str:
    """Remplace CURRENT_TODOS en bloc."""
    global CURRENT_TODOS
    todos, error = _normalize_todos(todos)
    if error: return error
    CURRENT_TODOS = todos
    print(f"  \033[33m[todo] updated {len(CURRENT_TODOS)} item(s)\033[0m")
    return f"Updated {len(CURRENT_TODOS)} todos"

# ── Permissions & hooks (s03 + s04) ──

# Les hooks vivent hors des handlers : la boucle ajoute permission, journal et arrêt sans modifier chaque outil.
HOOKS = {"UserPromptSubmit": [], "PreToolUse": [], "PostToolUse": [], "Stop": []}

def register_hook(event: str, callback): HOOKS[event].append(callback)

def trigger_hooks(event: str, *args):
    """Premier retour non-None court-circuite ; pour PreToolUse, une chaîne = bloquer l'outil avec ce message."""
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None: return result
    return None

DENY_LIST = ["rm -rf /", "sudo", "shutdown", "reboot", "mkfs", "dd if="]
DESTRUCTIVE = ["rm ", "> /etc/", "chmod 777"]

def _ask_allow() -> bool:
    """Confirmation interactive [y/N]."""
    return input("  Allow? [y/N] ").strip().lower() in ("y", "yes")

def permission_hook(block):
    """Couche de permission : voit le tool_use brut avant dispatch (refus, confirmation, ou passage)."""
    if block.name == "bash":
        command = block.input.get("command", "")
        for pattern in DENY_LIST:
            if pattern in command: return f"Permission denied: '{pattern}' is on the deny list"
        if any(token in command for token in DESTRUCTIVE):
            print(f"\n\033[33m[permission] destructive command\033[0m\n  {command}")
            if not _ask_allow(): return "Permission denied by user"
    if block.name in ("write_file", "edit_file"):
        path = block.input.get("path", "")
        try: safe_path(path)
        except Exception: return f"Permission denied: path escapes workspace: {path}"
    if block.name.startswith("mcp__") and "deploy" in block.name:
        print(f"\n\033[33m[permission] MCP destructive-looking tool: {block.name}\033[0m")
        if not _ask_allow(): return "Permission denied by user"
    return None

def log_hook(block):
    """Démonstrateur minimal : trace le nom de l'outil, laisse passer."""
    print(f"\033[90m[HOOK] {block.name}\033[0m")
    return None

def large_output_hook(block, output):
    """PostToolUse : avertit si une sortie dépasse 100 000 caractères."""
    if len(str(output)) > 100000:
        print(f"\033[33m[HOOK] large output from {block.name}: {len(str(output))} chars\033[0m")
    return None

def user_prompt_hook(query: str):
    """UserPromptSubmit : trace l'arrivée d'une entrée utilisateur."""
    print(f"\033[90m[HOOK] UserPromptSubmit: {WORKDIR}\033[0m")
    return None

def stop_hook(messages: list):
    """Stop : compte les tool_result de la conversation (audit de fin de tour)."""
    tool_count = sum(1 for msg in messages if isinstance(msg.get("content"), list)
                     for item in msg["content"]
                     if isinstance(item, dict) and item.get("type") == "tool_result")
    print(f"\033[90m[HOOK] Stop: {tool_count} tool result(s)\033[0m")
    return None

# L'ordre d'enregistrement est une politique : permission_hook AVANT log_hook (un outil refusé n'est jamais loggé).
register_hook("UserPromptSubmit", user_prompt_hook); register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook); register_hook("PostToolUse", large_output_hook)
register_hook("Stop", stop_hook)

# ── Subagent one-shot (s06) ──

SUB_SYSTEM = (f"You are a coding subagent at {WORKDIR}. "
              "Complete the task, then return a concise final summary. Do not spawn more agents.")

SUB_TOOLS = [
    _tool("bash", "Run a shell command.", ("command",), command=_STR),
    _tool("read_file", "Read file contents.", ("path",), path=_STR, limit=_INT, offset=_INT),
    _tool("write_file", "Write content to a file.", ("path", "content"), path=_STR, content=_STR),
    _tool("edit_file", "Replace exact text in a file once.", ("path", "old_text", "new_text"),
          path=_STR, old_text=_STR, new_text=_STR),
    _tool("glob", "Find files matching a glob pattern.", ("pattern",), pattern=_STR),
]

SUB_HANDLERS = {"bash": run_bash, "read_file": run_read, "write_file": run_write,
                "edit_file": run_edit, "glob": run_glob}

def extract_text(content) -> str:
    """Concatène les blocs text d'une réponse (résumés, compaction)."""
    if not isinstance(content, list): return str(content)
    return "\n".join(getattr(b, "text", "") for b in content if getattr(b, "type", None) == "text").strip()

def has_tool_use(content) -> bool:
    """LE prédicat de la boucle : un bloc tool_use concret est le signal de continuation, pas stop_reason seul."""
    return any(getattr(b, "type", None) == "tool_use" for b in content)

def spawn_subagent(description: str) -> str:
    """Boucle agent isolée (max 30 tours) : seul le dernier texte assistant remonte ; hooks Pre/PostToolUse appliqués."""
    messages = [{"role": "user", "content": description}]
    for _ in range(30):
        response = client.messages.create(model=MODEL, system=SUB_SYSTEM, messages=messages,
                                          tools=SUB_TOOLS, max_tokens=8000)
        messages.append({"role": "assistant", "content": response.content})
        if not has_tool_use(response.content): break
        results = []
        for block in response.content:
            if block.type != "tool_use": continue
            blocked = trigger_hooks("PreToolUse", block)
            if blocked:
                output = str(blocked)
            else:
                output = call_tool_handler(SUB_HANDLERS.get(block.name), block.input, block.name)
                trigger_hooks("PostToolUse", block, output)
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
        messages.append({"role": "user", "content": results})
    for msg in reversed(messages):
        if msg["role"] == "assistant" and (text := extract_text(msg["content"])):
            return text
    return "Subagent finished without a text summary."

# ── Skills (s07) ──

# Divulgation progressive : seul le catalogue entre dans le system prompt ; load_skill charge le contenu à la demande.
SKILLS_DIR = WORKDIR / "skills"
SKILL_REGISTRY: dict[str, dict] = {}

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Découpe un markdown en (métadonnées YAML, corps) ; tolère le YAML invalide. Partagé skills/mémoire (s07/s09)."""
    if not text.startswith("---"): return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3: return {}, text
    try: meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError: meta = {}
    return meta, parts[2].strip()

def scan_skills():
    """Vide puis repeuple SKILL_REGISTRY en parcourant skills/*/SKILL.md."""
    SKILL_REGISTRY.clear()
    if not SKILLS_DIR.exists(): return
    for directory in sorted(SKILLS_DIR.iterdir()):
        manifest = directory / "SKILL.md"
        if not directory.is_dir() or not manifest.exists(): continue
        raw = manifest.read_text()
        meta, _ = _parse_frontmatter(raw)
        name = meta.get("name", directory.name)
        desc = meta.get("description", raw.split("\n")[0].lstrip("#").strip())
        SKILL_REGISTRY[name] = {"name": name, "description": desc, "content": raw}

scan_skills()

def list_skills() -> str:
    """Formate le catalogue en puces « - nom: description »."""
    if not SKILL_REGISTRY: return "(no skills found)"
    return "\n".join(f"- {s['name']}: {s['description']}" for s in SKILL_REGISTRY.values())

def load_skill(name: str) -> str:
    """Retourne le SKILL.md complet ; si inconnu, liste les skills disponibles (l'erreur est utile au modèle)."""
    skill = SKILL_REGISTRY.get(name)
    if skill: return skill["content"]
    return f"Skill not found: {name}. Available: {', '.join(SKILL_REGISTRY.keys()) or '(none)'}"

# ── System prompt (s10) ──

PROMPT_SECTIONS = {
    "identity": "You are a coding agent. Act, don't explain.",
    "tools": "Available tools: bash, read_file, write_file, edit_file, glob, "
             "todo_write, task, load_skill, compact, "
             "create_task, list_tasks, get_task, claim_task, complete_task, "
             "schedule_cron, list_crons, cancel_cron, "
             "spawn_teammate, send_message, check_inbox, "
             "request_shutdown, request_plan, review_plan, "
             "create_worktree, remove_worktree, keep_worktree, "
             "connect_mcp. MCP tools are prefixed mcp__{server}__{tool}.",
    "workspace": f"Working directory: {WORKDIR}",
    "memory": "Relevant memories are injected below when available.",
}

def assemble_system_prompt(context: dict) -> str:
    """Reconstruit le system prompt à chaque tour : mémoire, skills, serveurs MCP connectés, heure courante."""
    sections = [PROMPT_SECTIONS["identity"], PROMPT_SECTIONS["tools"], PROMPT_SECTIONS["workspace"],
                f"Current time: {datetime.now().isoformat(timespec='seconds')}",
                "Skills catalog:\n" + list_skills() + "\nUse load_skill(name) when a skill is relevant."]
    if context.get("memories"):
        sections.append(f"Relevant memories:\n{context['memories']}")
    mcp_names = list(mcp_clients.keys())
    if mcp_names:
        sections.append(f"Connected MCP servers: {', '.join(mcp_names)}")
    return "\n\n".join(sections)

# ── Compaction de contexte (s08) ──

# Stratégie en couches : réduire les sorties d'outils, tailler les vieux messages, et n'appeler le
# modèle pour un résumé que si le contexte reste trop gros (ou sur demande explicite compact).
TRANSCRIPT_DIR = WORKDIR / ".transcripts"; TOOL_RESULTS_DIR = WORKDIR / ".task_outputs" / "tool-results"

def estimate_size(messages: list) -> int:
    """Approximation en caractères JSON, comparée à CONTEXT_LIMIT."""
    return len(json.dumps(messages, default=str))

def block_type(block):
    """Lit type que le bloc soit un dict (harness) ou un objet SDK (modèle)."""
    return block.get("type") if isinstance(block, dict) else getattr(block, "type", None)

def message_has_tool_use(message: dict) -> bool:
    content = message.get("content")
    return (message.get("role") == "assistant" and isinstance(content, list)
            and any(block_type(b) == "tool_use" for b in content))

def is_tool_result_message(message: dict) -> bool:
    content = message.get("content")
    return (message.get("role") == "user" and isinstance(content, list)
            and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content))

def collect_tool_results(messages: list):
    """Liste tous les blocs tool_result avec leurs indices (message, bloc)."""
    found = []
    for mi, msg in enumerate(messages):
        content = msg.get("content")
        if msg.get("role") != "user" or not isinstance(content, list): continue
        found += [(mi, bi, b) for bi, b in enumerate(content)
                  if isinstance(b, dict) and b.get("type") == "tool_result"]
    return found

def persist_large_output(tool_use_id: str, output: str) -> str:
    """Sorties > PERSIST_THRESHOLD : écrites sur disque, remplacées par un <persisted-output> (chemin + aperçu)."""
    if len(output) <= PERSIST_THRESHOLD: return output
    TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = TOOL_RESULTS_DIR / f"{tool_use_id}.txt"
    if not path.exists(): path.write_text(output)
    return f"<persisted-output>\nFull output: {path}\nPreview:\n{output[:2000]}\n</persisted-output>"

def tool_result_budget(messages: list, max_bytes: int = 200_000) -> list:
    """Couche 1 : si les tool_result du dernier message dépassent le budget, persiste les plus gros un à un.
    NB (piège documenté, porté tel quel) : les blocs sous PERSIST_THRESHOLD ressortent inchangés de
    persist_large_output — un dépassement fait de nombreux petits blocs est silencieusement toléré."""
    if not messages: return messages
    last = messages[-1]
    content = last.get("content")
    if last.get("role") != "user" or not isinstance(content, list): return messages
    blocks = [(i, b) for i, b in enumerate(content) if isinstance(b, dict) and b.get("type") == "tool_result"]
    total = sum(len(str(b.get("content", ""))) for _, b in blocks)
    if total <= max_bytes: return messages
    for _, block in sorted(blocks, key=lambda pair: len(str(pair[1].get("content", ""))), reverse=True):
        if total <= max_bytes: break
        block["content"] = persist_large_output(block.get("tool_use_id", "unknown"), str(block.get("content", "")))
        total = sum(len(str(b.get("content", ""))) for _, b in blocks)
    return messages

def snip_compact(messages: list, max_messages: int = 50) -> list:
    """Couche 2 : tête (3) + queue, milieu → « [snipped N messages] », sans couper une paire tool_use/tool_result."""
    if len(messages) <= max_messages: return messages
    head_end, tail_start = 3, len(messages) - (max_messages - 3)
    if head_end > 0 and message_has_tool_use(messages[head_end - 1]):
        while head_end < len(messages) and is_tool_result_message(messages[head_end]):
            head_end += 1
    if (tail_start > 0 and tail_start < len(messages)
            and is_tool_result_message(messages[tail_start])
            and message_has_tool_use(messages[tail_start - 1])):
        tail_start -= 1
    if head_end >= tail_start: return messages
    return (messages[:head_end] + [{"role": "user", "content": f"[snipped {tail_start - head_end} messages]"}]
            + messages[tail_start:])

def micro_compact(messages: list) -> list:
    """Couche 3 : efface les vieux tool_result (sauf les N derniers) — info récupérable en relançant l'outil."""
    tool_results = collect_tool_results(messages)
    if len(tool_results) <= KEEP_RECENT_TOOL_RESULTS: return messages
    for _, _, block in tool_results[:-KEEP_RECENT_TOOL_RESULTS]:
        if len(str(block.get("content", ""))) > 120:
            block["content"] = "[Earlier tool result compacted. Re-run if needed.]"
    return messages

def write_transcript(messages: list) -> Path:
    """Avant toute compaction destructive : historique complet sauvé en JSONL."""
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with path.open("w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    return path

def summarize_history(messages: list) -> str:
    """Appel LLM dédié (sans outils) : résume en préservant objectif, découvertes, fichiers modifiés, restes, contraintes."""
    prompt = ("Summarize this coding-agent conversation so work can continue. "
              "Preserve current goal, key findings, changed files, remaining work, "
              "and user constraints.\n\n" + json.dumps(messages, default=str)[:80000])
    response = client.messages.create(model=MODEL, messages=[{"role": "user", "content": prompt}], max_tokens=2000)
    return extract_text(response.content) or "(empty summary)"

def compact_history(messages: list) -> list:
    """Couche 4 (la plus destructive) : transcript + résumé, l'historique entier devient UN message [Compacted]."""
    transcript = write_transcript(messages)
    print(f"  \033[36m[compact] transcript saved: {transcript}\033[0m")
    return [{"role": "user", "content": f"[Compacted]\n\n{summarize_history(messages)}"}]

def reactive_compact(messages: list) -> list:
    """Compaction d'urgence après « prompt too long » : garde ~5 derniers messages bruts ; repli si le résumé échoue."""
    transcript = write_transcript(messages)
    print(f"  \033[31m[reactive compact] transcript saved: {transcript}\033[0m")
    try: summary = summarize_history(messages)
    except Exception: summary = "Earlier conversation was trimmed after a prompt-too-long error."
    tail_start = max(0, len(messages) - 5)
    if (tail_start > 0 and tail_start < len(messages)
            and is_tool_result_message(messages[tail_start])
            and message_has_tool_use(messages[tail_start - 1])):
        tail_start -= 1
    return [{"role": "user", "content": f"[Reactive compact]\n\n{summary}"}, *messages[tail_start:]]

# ── Mémoire (s09) ──

# Sous-système complet porté de s09 (s20 ne lisait que MEMORY.md) : fichiers .memory/*.md avec
# frontmatter, index, sélection, extraction, consolidation. Réutilise _parse_frontmatter (s07).
MEMORY_DIR = WORKDIR / ".memory"; MEMORY_DIR.mkdir(exist_ok=True)
MEMORY_INDEX = MEMORY_DIR / "MEMORY.md"
MEMORY_TYPES = ["user", "feedback", "project", "reference"]

def write_memory_file(name: str, mem_type: str, description: str, body: str):
    """Écrit un fichier mémoire (frontmatter YAML) et reconstruit l'index."""
    slug = name.lower().replace(" ", "-").replace("/", "-")
    filepath = MEMORY_DIR / f"{slug}.md"
    filepath.write_text(f"---\nname: {name}\ndescription: {description}\ntype: {mem_type}\n---\n\n{body}\n")
    _rebuild_index()
    return filepath

def _rebuild_index():
    """Reconstruit MEMORY.md (une ligne par mémoire) depuis les fichiers."""
    lines = []
    for f in sorted(MEMORY_DIR.glob("*.md")):
        if f.name == "MEMORY.md": continue
        meta, body = _parse_frontmatter(f.read_text())
        desc = meta.get("description", body.split("\n")[0][:80])
        lines.append(f"- [{meta.get('name', f.stem)}]({f.name}) — {desc}")
    MEMORY_INDEX.write_text("\n".join(lines) + "\n" if lines else "")

def read_memory_index() -> str:
    """Lit l'index MEMORY.md (injecté dans le SYSTEM à chaque tour)."""
    if not MEMORY_INDEX.exists(): return ""
    return MEMORY_INDEX.read_text().strip()

def read_memory_file(filename: str) -> str | None:
    """Lit le contenu complet d'un fichier mémoire."""
    path = MEMORY_DIR / filename
    return path.read_text() if path.exists() else None

def list_memory_files() -> list[dict]:
    """Liste tous les fichiers mémoire avec leurs métadonnées."""
    result = []
    for f in sorted(MEMORY_DIR.glob("*.md")):
        if f.name == "MEMORY.md": continue
        meta, body = _parse_frontmatter(f.read_text())
        result.append({"filename": f.name, "name": meta.get("name", f.stem),
                       "description": meta.get("description", ""),
                       "type": meta.get("type", "user"), "body": body})
    return result

def _content_text(content: list) -> str:
    """Concatène le texte des blocs text d'un content de message (dicts ou objets SDK)."""
    return " ".join(str(getattr(b, "text", "")) for b in content if getattr(b, "type", None) == "text")

def _llm_extract_items(prompt: str, max_tokens: int):
    """Appel LLM → première liste JSON [...] de la réponse (parsée), ou None si absente."""
    response = client.messages.create(model=MODEL, messages=[{"role": "user", "content": prompt}],
                                      max_tokens=max_tokens)
    match = re.search(r'\[.*\]', extract_text(response.content).strip(), re.DOTALL)
    return json.loads(match.group()) if match else None

def _write_mem_item(mem: dict) -> bool:
    """Écrit une mémoire extraite si description et body sont présents."""
    desc, body = mem.get("description", ""), mem.get("body", "")
    if desc and body:
        write_memory_file(mem.get("name", f"memory_{int(time.time())}"), mem.get("type", "user"), desc, body)
        return True
    return False

def select_relevant_memories(messages: list, max_items: int = 5) -> list[str]:
    """Sélectionne les mémoires pertinentes via LLM sur le catalogue ; repli : matching par mots-clés."""
    files = list_memory_files()
    if not files: return []
    recent_texts = []
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list): content = _content_text(content)
            if isinstance(content, str): recent_texts.append(content)
            if len(recent_texts) >= 3: break
    recent = " ".join(reversed(recent_texts))[:2000]
    if not recent.strip(): return []
    catalog = "\n".join(f"{i}: {f['name']} — {f['description']}" for i, f in enumerate(files))
    prompt = ("Given the recent conversation and the memory catalog below, "
              "select the indices of memories that are clearly relevant. "
              "Return ONLY a JSON array of integers, e.g. [0, 3]. "
              "If none are relevant, return [].\n\n"
              f"Recent conversation:\n{recent}\n\nMemory catalog:\n{catalog}")
    try:
        response = client.messages.create(model=MODEL, messages=[{"role": "user", "content": prompt}],
                                          max_tokens=200)
        match = re.search(r'\[.*?\]', extract_text(response.content).strip(), re.DOTALL)
        if match:
            indices = json.loads(match.group())
            return [files[i]["filename"] for i in indices if isinstance(i, int) and 0 <= i < len(files)][:max_items]
    except Exception: pass
    keywords = [w.lower() for w in recent.split() if len(w) > 3]
    selected = []
    for f in files:
        if any(kw in (f["name"] + " " + f["description"]).lower() for kw in keywords):
            selected.append(f["filename"])
            if len(selected) >= max_items: break
    return selected

def load_memories(messages: list) -> str:
    """Charge le contenu des mémoires pertinentes pour injection en contexte."""
    selected_files = select_relevant_memories(messages)
    if not selected_files: return ""
    parts = ["<relevant_memories>"]
    parts += [c for c in (read_memory_file(f) for f in selected_files) if c]
    parts.append("</relevant_memories>")
    return "\n\n".join(parts)

def extract_memories(messages: list):
    """Extrait de nouvelles mémoires du dialogue récent (après chaque tour)."""
    dialogue_parts = []
    for msg in messages[-10:]:
        content = msg.get("content", "")
        if isinstance(content, list): content = _content_text(content)
        if isinstance(content, str) and content.strip():
            dialogue_parts.append(f"{msg.get('role', '?')}: {content}")
    dialogue = "\n".join(dialogue_parts)
    if not dialogue.strip(): return
    existing = list_memory_files()
    existing_desc = "\n".join(f"- {m['name']}: {m['description']}" for m in existing) if existing else "(none)"
    prompt = ("Extract user preferences, constraints, or project facts from this dialogue.\n"
              "Return a JSON array. Each item: {name, type, description, body}.\n"
              "- name: short kebab-case identifier (e.g. 'user-preference-tabs')\n"
              "- type: one of 'user' (user preference), 'feedback' (guidance), "
              "'project' (project fact), 'reference' (external pointer)\n"
              "- description: one-line summary for index lookup\n"
              "- body: full detail in markdown\n"
              "If nothing new or already covered by existing memories, return [].\n\n"
              f"Existing memories:\n{existing_desc}\n\nDialogue:\n{dialogue[:4000]}")
    try:
        items = _llm_extract_items(prompt, 800)
        if not items: return
        count = sum(_write_mem_item(mem) for mem in items)
        if count:
            print(f"\n\033[33m[Memory: extracted {count} new memories]\033[0m")
    except Exception: pass

CONSOLIDATE_THRESHOLD = 10

def consolidate_memories():
    """Fusionne doublons et mémoires périmées (déclenché à partir du seuil)."""
    files = list_memory_files()
    if len(files) < CONSOLIDATE_THRESHOLD: return
    catalog = "\n\n".join(
        f"## {f['filename']}\nname: {f['name']}\ndescription: {f['description']}\n{f['body']}"
        for f in files)
    prompt = ("Consolidate the following memory files. Rules:\n"
              "1. Merge duplicates into one\n"
              "2. Remove outdated/contradicted memories\n"
              "3. Keep the total under 30 memories\n"
              "4. Preserve important user preferences above all\n"
              "Return a JSON array. Each item: {name, type, description, body}.\n\n"
              f"{catalog[:16000]}")
    try:
        items = _llm_extract_items(prompt, 3000)
        if items is None: return
        for f in MEMORY_DIR.glob("*.md"):
            if f.name != "MEMORY.md": f.unlink()
        for mem in items:
            _write_mem_item(mem)
        print(f"\n\033[33m[Memory: consolidated {len(files)} → {len(items)} memories]\033[0m")
    except Exception: pass

def update_context(context: dict, messages: list) -> dict:
    """Contexte pour assemble_system_prompt : MEMORY.md (2000 premiers caractères) + état vivant MCP/teammates (s20)."""
    return {"memories": MEMORY_INDEX.read_text()[:2000] if MEMORY_INDEX.exists() else "",
            "connected_mcp": list(mcp_clients.keys()),
            "active_teammates": list(active_teammates.keys())}

# ── Récupération d'erreurs / retry (s11) ──

class RecoveryState:
    """État de récupération par conversation : escalade max_tokens, continuations, 529, compaction réactive, modèle courant."""

    def __init__(self):
        self.has_escalated = self.has_attempted_reactive_compact = False
        self.recovery_count = self.consecutive_529 = 0
        self.current_model = PRIMARY_MODEL

def retry_delay(attempt: int) -> float:
    """Backoff exponentiel plafonné à 32 s + jitter 0-25 %."""
    base = min(BASE_DELAY_MS * (2 ** attempt), 32000) / 1000
    return base + random.uniform(0, base * 0.25)

def with_retry(fn, state: RecoveryState):
    """Jusqu'à MAX_RETRIES tentatives. 429 → backoff ; 529 → backoff + bascule FALLBACK_MODEL ; le reste relancé tel quel."""
    for attempt in range(MAX_RETRIES):
        try:
            result = fn()
            state.consecutive_529 = 0
            return result
        except Exception as e:
            name, msg = type(e).__name__.lower(), str(e).lower()
            if "ratelimit" in name or "429" in msg:
                code = "429"
            elif "overloaded" in name or "529" in msg or "overloaded" in msg:
                code = "529"
                state.consecutive_529 += 1
                if state.consecutive_529 >= MAX_CONSECUTIVE_529 and FALLBACK_MODEL:
                    state.current_model = FALLBACK_MODEL
                    state.consecutive_529 = 0
                    print(f"  \033[31m[529] switching to {FALLBACK_MODEL}\033[0m")
            else:
                raise
            delay = retry_delay(attempt)
            print(f"  \033[33m[{code}] retry {attempt + 1}/{MAX_RETRIES} after {delay:.1f}s\033[0m")
            time.sleep(delay)
    raise RuntimeError(f"Max retries ({MAX_RETRIES}) exceeded")

def is_prompt_too_long_error(e: Exception) -> bool:
    """Détecte les formulations de l'erreur de contexte (déclenche reactive_compact dans la boucle)."""
    msg = str(e).lower()
    return ("prompt" in msg and "long" in msg) or "context_length_exceeded" in msg or "max_context_window" in msg

# ── Système de tâches (s12) ──

# Petits enregistrements durables (JSON sur disque) ; les couches suivantes ajoutent
# propriété, dépendances, worktrees et teammates.
TASKS_DIR = WORKDIR / ".tasks"; TASKS_DIR.mkdir(exist_ok=True)

@dataclass
class Task:
    id: str; subject: str; description: str; status: str
    owner: str | None; blockedBy: list[str]
    worktree: str | None = None

def _task_path(task_id: str) -> Path: return TASKS_DIR / f"{task_id}.json"

def create_task(subject: str, description: str = "", blockedBy: list[str] | None = None) -> Task:
    """Crée une Task (id horodaté + aléa), statut pending, persistée."""
    task = Task(id=f"task_{int(time.time())}_{random.randint(0, 9999):04d}",
                subject=subject, description=description,
                status="pending", owner=None, blockedBy=blockedBy or [])
    save_task(task)
    return task

def save_task(task: Task): _task_path(task.id).write_text(json.dumps(asdict(task), indent=2))

def load_task(task_id: str) -> Task: return Task(**json.loads(_task_path(task_id).read_text()))

def list_tasks() -> list[Task]:
    return [Task(**json.loads(p.read_text())) for p in sorted(TASKS_DIR.glob("task_*.json"))]

def get_task_json(task_id: str) -> str: return json.dumps(asdict(load_task(task_id)), indent=2)

def can_start(task_id: str) -> bool:
    """Règle de dépendances volontairement simple : chaque bloqueur doit exister ET être completed."""
    return all(_task_path(d).exists() and load_task(d).status == "completed"
               for d in load_task(task_id).blockedBy)

def claim_task(task_id: str, owner: str = "agent") -> str:
    """Revendication avec triple garde : pending, sans owner, démarrable."""
    task = load_task(task_id)
    if task.status != "pending": return f"Task {task_id} is {task.status}, cannot claim"
    if task.owner: return f"Task {task_id} already owned by {task.owner}"
    if not can_start(task_id):
        deps = [d for d in task.blockedBy if _task_path(d).exists() and load_task(d).status != "completed"]
        missing = [d for d in task.blockedBy if not _task_path(d).exists()]
        parts = []
        if deps: parts.append(f"blocked by: {deps}")
        if missing: parts.append(f"missing deps: {missing}")
        return "Cannot start — " + ", ".join(parts)
    task.owner = owner
    task.status = "in_progress"
    save_task(task)
    print(f"  \033[36m[claim] {task.subject} → in_progress\033[0m")
    return f"Claimed {task.id} ({task.subject})"

def complete_task(task_id: str) -> str:
    """Termine la tâche et signale au modèle les tâches débloquées."""
    task = load_task(task_id)
    if task.status != "in_progress": return f"Task {task_id} is {task.status}, cannot complete"
    task.status = "completed"
    save_task(task)
    unblocked = [t.subject for t in list_tasks() if t.status == "pending" and t.blockedBy and can_start(t.id)]
    print(f"  \033[32m[complete] {task.subject} ✓\033[0m")
    msg = f"Completed {task.id} ({task.subject})"
    return msg + (f"\nUnblocked: {', '.join(unblocked)}" if unblocked else "")

def run_create_task(subject: str, description: str = "", blockedBy: list[str] | None = None) -> str:
    task = create_task(subject, description, blockedBy)
    deps = f" (blockedBy: {', '.join(blockedBy)})" if blockedBy else ""
    print(f"  \033[34m[create] {task.subject}{deps}\033[0m")
    return f"Created {task.id}: {task.subject}{deps}"

def run_list_tasks() -> str:
    tasks = list_tasks()
    if not tasks: return "No tasks."
    return "\n".join(f"  {t.id}: {t.subject} [{t.status}]"
                     + (f" (wt:{t.worktree})" if t.worktree else "") for t in tasks)

def _task_op(fn, task_id: str, **kw) -> str:
    """Garde commune des wrappers de tâche : FileNotFoundError → message d'erreur."""
    try: return fn(task_id, **kw)
    except FileNotFoundError: return f"Error: task {task_id} not found"

def run_get_task(task_id: str) -> str: return _task_op(get_task_json, task_id)
def run_claim_task(task_id: str) -> str: return _task_op(claim_task, task_id, owner="agent")
def run_complete_task(task_id: str) -> str: return _task_op(complete_task, task_id)

# ── Tâches d'arrière-plan (s13) ──

# Les outils lents retournent un placeholder tool_result immédiat ; la vraie sortie revient en task_notification.
_bg_counter = 0
background_tasks: dict[str, dict] = {}; background_results: dict[str, str] = {}
background_lock = threading.Lock()

def is_slow_operation(tool_name: str, tool_input: dict) -> bool:
    """Heuristique par mots-clés sur les commandes bash uniquement."""
    if tool_name != "bash": return False
    command = tool_input.get("command", "").lower()
    return any(kw in command for kw in ["install", "build", "test", "deploy", "compile", "docker build",
                                        "pip install", "npm install", "cargo build", "pytest", "make"])

def should_run_background(tool_name: str, tool_input: dict) -> bool:
    """Arrière-plan si le modèle l'a demandé (run_in_background) OU si l'heuristique juge la commande lente."""
    if tool_name != "bash": return False
    return bool(tool_input.get("run_in_background")) or is_slow_operation(tool_name, tool_input)

def start_background_task(block, handlers: dict) -> str:
    """Lance un worker daemon ; déclenche quand même PostToolUse ; résultat déposé dans background_results."""
    global _bg_counter
    _bg_counter += 1
    bg_id = f"bg_{_bg_counter:04d}"
    command = block.input.get("command", block.name)

    def worker():
        result = call_tool_handler(handlers.get(block.name), block.input, block.name)
        trigger_hooks("PostToolUse", block, result)
        with background_lock:
            background_tasks[bg_id]["status"] = "completed"
            background_results[bg_id] = str(result)

    with background_lock:
        background_tasks[bg_id] = {"tool_use_id": block.id, "command": command, "status": "running"}
    threading.Thread(target=worker, daemon=True).start()
    print(f"  \033[33m[background] {bg_id}: {str(command)[:60]}\033[0m")
    return bg_id

def collect_background_results() -> list[str]:
    """Draine les tâches completed en blocs XML <task_notification>."""
    with background_lock:
        ready = [bg_id for bg_id, task in background_tasks.items() if task["status"] == "completed"]
    notifications = []
    for bg_id in ready:
        with background_lock:
            task = background_tasks.pop(bg_id); output = background_results.pop(bg_id, "")
        summary = output[:200] if len(output) > 200 else output
        notifications.append(
            f"<task_notification>\n  <task_id>{bg_id}</task_id>\n  <status>completed</status>\n"
            f"  <command>{task['command']}</command>\n  <summary>{summary}</summary>\n"
            f"</task_notification>")
    return notifications

# ── Cron (s14) ──

# Les jobs vivent hors de l'historique ; quand un job tire, il devient un prompt réinjecté dans la boucle agent.
DURABLE_PATH = WORKDIR / ".scheduled_tasks.json"

@dataclass
class CronJob:
    id: str; cron: str; prompt: str; recurring: bool; durable: bool

scheduled_jobs: dict[str, CronJob] = {}; cron_queue: list[CronJob] = []
cron_lock = threading.Lock(); _last_fired: dict[str, str] = {}

def _cron_field_matches(field: str, value: int) -> bool:
    """Matching récursif d'un champ : *, pas */n, listes, plages, valeur."""
    if field == "*": return True
    if field.startswith("*/"):
        step = int(field[2:])
        return step > 0 and value % step == 0
    if "," in field:
        return any(_cron_field_matches(part.strip(), value) for part in field.split(","))
    if "-" in field:
        lo, hi = field.split("-", 1)
        return int(lo) <= value <= int(hi)
    return value == int(field)

def cron_matches(cron_expr: str, dt: datetime) -> bool:
    """Matching 5 champs avec la sémantique OU dom/dow du vrai cron (lundi=0 Python → dimanche=0 cron)."""
    fields = cron_expr.strip().split()
    if len(fields) != 5: return False
    minute, hour, dom, month, dow = fields
    if not (_cron_field_matches(minute, dt.minute) and _cron_field_matches(hour, dt.hour)
            and _cron_field_matches(month, dt.month)):
        return False
    dom_ok = _cron_field_matches(dom, dt.day)
    dow_ok = _cron_field_matches(dow, (dt.weekday() + 1) % 7)
    if dom == "*" and dow == "*": return True
    if dom == "*": return dow_ok
    if dow == "*": return dom_ok
    return dom_ok or dow_ok

def _validate_cron_field(field: str, lo: int, hi: int) -> str | None:
    if field == "*": return None
    if field.startswith("*/"):
        step = field[2:]
        return None if step.isdigit() and int(step) > 0 else f"Invalid step: {field}"
    if "," in field:
        return next((err for part in field.split(",") if (err := _validate_cron_field(part.strip(), lo, hi))), None)
    if "-" in field:
        left, right = field.split("-", 1)
        if not left.isdigit() or not right.isdigit(): return f"Invalid range: {field}"
        a, b = int(left), int(right)
        if a < lo or a > hi or b < lo or b > hi: return f"Range {field} out of bounds [{lo}-{hi}]"
        return f"Range start > end: {field}" if a > b else None
    if not field.isdigit(): return f"Invalid field: {field}"
    value = int(field)
    return f"Value {value} out of bounds [{lo}-{hi}]" if value < lo or value > hi else None

def validate_cron(cron_expr: str) -> str | None:
    """Validation complète à la création, messages nommant le champ fautif."""
    fields = cron_expr.strip().split()
    if len(fields) != 5: return f"Expected 5 fields, got {len(fields)}"
    bounds = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    names = ["minute", "hour", "day-of-month", "month", "day-of-week"]
    return next((f"{name}: {err}" for field, (lo, hi), name in zip(fields, bounds, names)
                 if (err := _validate_cron_field(field, lo, hi))), None)

def save_durable_jobs():
    durable = [asdict(job) for job in scheduled_jobs.values() if job.durable]
    DURABLE_PATH.write_text(json.dumps(durable, indent=2))

def load_durable_jobs():
    """Recharge les jobs durables ; chaque job est re-validé au passage."""
    if not DURABLE_PATH.exists(): return
    try:
        for item in json.loads(DURABLE_PATH.read_text()):
            job = CronJob(**item)
            if not validate_cron(job.cron):
                scheduled_jobs[job.id] = job
    except Exception: pass

def schedule_job(cron: str, prompt: str, recurring: bool = True, durable: bool = True) -> CronJob | str:
    """Valide, crée et enregistre le CronJob (persisté si durable) ; retourne le job ou la chaîne d'erreur."""
    err = validate_cron(cron)
    if err: return err
    job = CronJob(id=f"cron_{random.randint(0, 999999):06d}",
                  cron=cron, prompt=prompt, recurring=recurring, durable=durable)
    with cron_lock: scheduled_jobs[job.id] = job
    if durable: save_durable_jobs()
    return job

def cancel_job(job_id: str) -> str:
    with cron_lock: job = scheduled_jobs.pop(job_id, None)
    if not job: return f"Job {job_id} not found"
    if job.durable: save_durable_jobs()
    return f"Cancelled {job_id}"

def cron_scheduler_loop():
    """Thread daemon : tick chaque seconde, anti-double-déclenchement par marqueur à la minute."""
    while True:
        time.sleep(1)
        now = datetime.now()
        marker = now.strftime("%Y-%m-%d %H:%M")
        with cron_lock:
            for job in list(scheduled_jobs.values()):
                try:
                    if cron_matches(job.cron, now) and _last_fired.get(job.id) != marker:
                        cron_queue.append(job)
                        _last_fired[job.id] = marker
                        if not job.recurring:
                            scheduled_jobs.pop(job.id, None)
                            if job.durable: save_durable_jobs()
                except Exception as e:
                    print(f"  \033[31m[cron error] {job.id}: {e}\033[0m")

def consume_cron_queue() -> list[CronJob]:
    """Vide atomiquement la file des jobs tirés (boucle agent et autorun)."""
    with cron_lock: fired = list(cron_queue); cron_queue.clear()
    return fired

def run_schedule_cron(cron: str, prompt: str, recurring: bool = True, durable: bool = True) -> str:
    result = schedule_job(cron, prompt, recurring, durable)
    return f"Error: {result}" if isinstance(result, str) else f"Scheduled {result.id}: '{cron}' -> {prompt}"

def run_list_crons() -> str:
    with cron_lock: jobs = list(scheduled_jobs.values())
    if not jobs: return "No cron jobs."
    return "\n".join(f"  {job.id}: '{job.cron}' -> {job.prompt[:40]} "
                     f"[{'recurring' if job.recurring else 'one-shot'}, "
                     f"{'durable' if job.durable else 'session'}]" for job in jobs)

run_cancel_cron = cancel_job

# Amorçage à l'import, comme dans s20 : jobs durables + scheduler daemon.
load_durable_jobs()
threading.Thread(target=cron_scheduler_loop, daemon=True).start()

# ── Teams / MessageBus (s15) ──

# Mailboxes JSONL append-only : protocole inspectable sur disque, les teammates en arrière-plan peuvent émettre.
MAILBOX_DIR = WORKDIR / ".mailboxes"; MAILBOX_DIR.mkdir(exist_ok=True)

class MessageBus:
    def send(self, from_agent: str, to_agent: str, content: str,
             msg_type: str = "message", metadata: dict = None):
        msg = {"from": from_agent, "to": to_agent, "content": content,
               "type": msg_type, "ts": time.time(), "metadata": metadata or {}}
        with open(MAILBOX_DIR / f"{to_agent}.jsonl", "a") as f: f.write(json.dumps(msg) + "\n")
        terminal_print(f"  \033[33m[bus] {from_agent} → {to_agent}: ({msg_type}) {content[:50]}\033[0m")

    def read_inbox(self, agent: str) -> list[dict]:
        # Lecture destructive (unlink) : les messages ne sont délivrés qu'une fois.
        inbox = MAILBOX_DIR / f"{agent}.jsonl"
        if not inbox.exists(): return []
        msgs = [json.loads(line) for line in inbox.read_text().splitlines() if line.strip()]
        inbox.unlink()
        return msgs

BUS = MessageBus()
active_teammates: dict[str, bool] = {}

TEAMMATE_TOOLS = [
    _tool("bash", "Run a shell command.", ("command",), command=_STR),
    _tool("read_file", "Read file.", ("path",), path=_STR, limit=_INT, offset=_INT),
    _tool("write_file", "Write file.", ("path", "content"), path=_STR, content=_STR),
    _tool("send_message", "Send message to another agent.", ("to", "content"), to=_STR, content=_STR),
    _tool("submit_plan", "Submit a plan for Lead approval.", ("plan",), plan=_STR),
    _tool("list_tasks", "List all tasks."),
    _tool("claim_task", "Claim a pending task.", ("task_id",), task_id=_STR),
    _tool("complete_task", "Mark an in-progress task as completed.", ("task_id",), task_id=_STR),
]

def spawn_teammate_thread(name: str, role: str, prompt: str) -> str:
    """Mini-harness par teammate (s15-s18) : gate d'approbation de plan, outils fichiers basculés dans le worktree de la tâche revendiquée, idle_poll entre rafales."""
    if name in active_teammates: return f"Teammate '{name}' already exists"
    # Vrai gate : après submit_plan, plus aucun pas modèle/outil tant que lead n'a pas répondu.
    protocol_ctx = {"waiting_plan": None}
    system = (f"You are '{name}', a {role}. Use tools to complete tasks. "
              f"If a task has a worktree, work in that directory.")

    def handle_inbox_message(name: str, msg: dict, messages: list):
        meta = msg.get("metadata", {})
        req_id = meta.get("request_id", "")
        msg_type = msg.get("type", "message")
        if msg_type == "shutdown_request":
            BUS.send(name, "lead", "Shutting down.", "shutdown_response",
                     {"request_id": req_id, "approve": True})
            return True
        if msg_type == "plan_approval_response":
            approve = meta.get("approve", False)
            if req_id == protocol_ctx["waiting_plan"]:
                protocol_ctx["waiting_plan"] = None
            messages.append({"role": "user",
                "content": "[Plan approved]" if approve else f"[Plan rejected] {msg['content']}"})
        return False

    def run():
        wt_ctx = {"path": None}

        def _wt_cwd():
            # Tâche à worktree revendiquée → tous les outils fichiers du teammate tournent dans ce répertoire.
            p = wt_ctx["path"]
            return Path(p) if p else None

        def _run_bash(command: str) -> str: return run_bash(command, cwd=_wt_cwd())
        def _run_read(path: str) -> str: return run_read(path, cwd=_wt_cwd())
        def _run_write(path: str, content: str) -> str: return run_write(path, content, cwd=_wt_cwd())

        def _run_claim_task(task_id: str):
            result = claim_task(task_id, owner=name)
            if "Claimed" in result:
                task = load_task(task_id)
                wt_ctx["path"] = str(WORKTREES_DIR / task.worktree) if task.worktree else None
            return result

        def _run_complete_task(task_id: str):
            result = complete_task(task_id)
            wt_ctx["path"] = None
            return result

        messages = [{"role": "user", "content": prompt}]
        sub_handlers = {
            "bash": _run_bash, "read_file": _run_read, "write_file": _run_write,
            "send_message": lambda to, content: (BUS.send(name, to, content), "Sent")[1],
            "list_tasks": run_list_tasks,
            "claim_task": _run_claim_task, "complete_task": _run_complete_task,
        }

        while True:
            if len(messages) <= 3:
                messages.insert(0, {"role": "user",
                    "content": f"<identity>You are '{name}', role: {role}. "
                               f"Continue your work.</identity>"})
            should_shutdown = False
            for _ in range(10):
                inbox = BUS.read_inbox(name)
                for msg in inbox:
                    if handle_inbox_message(name, msg, messages):
                        should_shutdown = True
                        break
                if should_shutdown: break
                if protocol_ctx["waiting_plan"]:
                    # Gate fermé : on ne poll que les réponses de protocole, pas d'appel LLM.
                    time.sleep(IDLE_POLL_INTERVAL)
                    continue
                if inbox and not should_shutdown:
                    non_protocol = [m for m in inbox if m.get("type") == "message"]
                    if non_protocol:
                        messages.append({"role": "user",
                            "content": "<inbox>" + json.dumps(non_protocol) + "</inbox>"})
                try:
                    response = client.messages.create(model=MODEL, system=system, messages=messages[-20:],
                                                      tools=TEAMMATE_TOOLS, max_tokens=8000)
                except Exception: break
                messages.append({"role": "assistant", "content": response.content})
                if not has_tool_use(response.content): break
                results = []
                blocks = list(response.content)
                for bi, block in enumerate(blocks):
                    if block.type != "tool_use": continue
                    if block.name == "submit_plan":
                        output = _teammate_submit_plan(name, block.input.get("plan", ""))
                        match = re.search(r"\((req_\d+)\)", output)
                        protocol_ctx["waiting_plan"] = match.group(1) if match else output
                    else:
                        output = call_tool_handler(sub_handlers.get(block.name), block.input, block.name)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(output)})
                    if protocol_ctx["waiting_plan"]:
                        # Les tool_use suivants de la même réponse appartiennent à l'après-approbation.
                        # FIX(mekicode): s20 les abandonnait sans tool_result, ce qui produit une
                        # erreur API 400 (chaque tool_use exige un tool_result) dès que la paire
                        # bancale reste dans la fenêtre messages[-20:]. On répond par un placeholder
                        # avant de fermer.
                        for later in blocks[bi + 1:]:
                            if getattr(later, "type", None) == "tool_use":
                                results.append({"type": "tool_result", "tool_use_id": later.id,
                                                "content": "[Deferred until plan approval]"})
                        break
                messages.append({"role": "user", "content": results})
                if protocol_ctx["waiting_plan"]: break
            if should_shutdown: break
            if protocol_ctx["waiting_plan"]: continue
            if idle_poll(name, messages, name, role, wt_ctx) in ("shutdown", "timeout"):
                break

        # Épilogue : dernier texte assistant → résumé envoyé au lead.
        summary = "Done."
        for msg in reversed(messages):
            if msg["role"] == "assistant" and isinstance(msg["content"], list):
                for b in msg["content"]:
                    if getattr(b, "type", None) == "text":
                        summary = b.text
                        break
                else:
                    continue
                break
        BUS.send(name, "lead", summary, "result")
        active_teammates.pop(name, None)

    active_teammates[name] = True
    threading.Thread(target=run, daemon=True).start()
    return f"Teammate '{name}' spawned as {role}"

def _teammate_submit_plan(from_name: str, plan: str) -> str:
    """Crée la ProtocolState plan_approval et envoie le plan au lead avec le request_id en métadonnées."""
    req_id = new_request_id()
    pending_requests[req_id] = ProtocolState(request_id=req_id, type="plan_approval", sender=from_name,
                                             target="lead", status="pending", payload=plan)
    BUS.send(from_name, "lead", plan, "plan_approval_request", {"request_id": req_id})
    return f"Plan submitted ({req_id})"

run_spawn_teammate = spawn_teammate_thread

def run_send_message(to: str, content: str) -> str:
    BUS.send("lead", to, content)
    return f"Sent to {to}"

def run_check_inbox() -> str:
    """Draine l'inbox du lead (routage protocole) et formate chaque message avec type et request_id."""
    msgs = consume_lead_inbox(route_protocol=True)
    if not msgs: return "(inbox empty)"
    lines = []
    for m in msgs:
        req_id = m.get("metadata", {}).get("request_id", "")
        tag = f" [{m['type']} req:{req_id}]" if req_id else f" [{m['type']}]"
        lines.append(f"  [{m['from']}]{tag} {m['content'][:200]}")
    return "\n".join(lines)

# ── Protocoles (s16) ──

@dataclass
class ProtocolState:
    request_id: str; type: str; sender: str; target: str; status: str; payload: str
    created_at: float = field(default_factory=time.time)

pending_requests: dict[str, ProtocolState] = {}

def new_request_id() -> str: return f"req_{random.randint(0, 999999):06d}"

def match_response(response_type: str, request_id: str, approve: bool):
    """Apparie une réponse par request_id ET par type : une réponse ne peut pas approuver une autre requête pendante."""
    state = pending_requests.get(request_id)
    if not state: return
    if state.type == "shutdown" and response_type != "shutdown_response": return
    if state.type == "plan_approval" and response_type != "plan_approval_response": return
    state.status = "approved" if approve else "rejected"

def consume_lead_inbox(route_protocol=True) -> list[dict]:
    """Vide l'inbox du lead ; si route_protocol, route tout message *_response vers match_response."""
    msgs = BUS.read_inbox("lead")
    if route_protocol:
        for msg in msgs:
            meta = msg.get("metadata", {})
            req_id = meta.get("request_id", "")
            msg_type = msg.get("type", "")
            if req_id and msg_type.endswith("_response"):
                match_response(msg_type, req_id, meta.get("approve", False))
    return msgs

def run_request_shutdown(teammate: str) -> str:
    """Côté lead : arrêt négocié, pas imposé — le teammate répond avant."""
    req_id = new_request_id()
    pending_requests[req_id] = ProtocolState(request_id=req_id, type="shutdown", sender="lead",
                                             target=teammate, status="pending", payload="")
    BUS.send("lead", teammate, "Shut down.", "shutdown_request", {"request_id": req_id})
    return f"Shutdown request sent to {teammate}"

def run_request_plan(teammate: str, task: str) -> str:
    """Simple message ; c'est le teammate qui crée la requête formelle."""
    BUS.send("lead", teammate, f"Submit plan for: {task}", "message")
    return f"Asked {teammate} to submit a plan"

def run_review_plan(request_id: str, approve: bool, feedback: str = "") -> str:
    """Met à jour la ProtocolState et envoie la plan_approval_response qui lèvera le gate du teammate."""
    state = pending_requests.get(request_id)
    if not state: return f"Request {request_id} not found"
    state.status = "approved" if approve else "rejected"
    BUS.send("lead", state.sender, feedback or ("Approved" if approve else "Rejected"),
             "plan_approval_response", {"request_id": request_id, "approve": approve})
    return f"Plan {'approved' if approve else 'rejected'}"

# ── Agent autonome (s17) ──

IDLE_POLL_INTERVAL = 5; IDLE_TIMEOUT = 60

def scan_unclaimed_tasks() -> list[dict]:
    """Tâches pending, sans owner, démarrables (lecture JSON brute)."""
    return [task for f in sorted(TASKS_DIR.glob("task_*.json"))
            for task in [json.loads(f.read_text())]
            if task.get("status") == "pending" and not task.get("owner") and can_start(task["id"])]

def idle_poll(agent_name: str, messages: list, name: str, role: str,
              worktree_context: dict | None = None) -> str:
    """Oisiveté d'un teammate : inbox d'abord (protocole prioritaire), puis revendication autonome d'une tâche libre (bascule worktree), sinon timeout."""
    for _ in range(IDLE_TIMEOUT // IDLE_POLL_INTERVAL):
        time.sleep(IDLE_POLL_INTERVAL)
        inbox = BUS.read_inbox(agent_name)
        if inbox:
            for msg in inbox:
                if msg.get("type") == "shutdown_request":
                    req_id = msg.get("metadata", {}).get("request_id", "")
                    BUS.send(name, "lead", "Shutting down.", "shutdown_response",
                             {"request_id": req_id, "approve": True})
                    return "shutdown"
            messages.append({"role": "user", "content": "<inbox>" + json.dumps(inbox) + "</inbox>"})
            return "work"
        unclaimed = scan_unclaimed_tasks()
        if unclaimed:
            task_data = unclaimed[0]
            if "Claimed" in claim_task(task_data["id"], agent_name):
                wt_info = ""
                if task_data.get("worktree"):
                    wt_path = WORKTREES_DIR / task_data["worktree"]
                    wt_info = f"\nWork directory: {wt_path}"
                    if worktree_context is not None:
                        worktree_context["path"] = str(wt_path)
                messages.append({"role": "user",
                    "content": f"<auto-claimed>Task {task_data['id']}: "
                               f"{task_data['subject']}{wt_info}</auto-claimed>"})
                return "work"
    return "timeout"

# ── Worktrees (s18) ──

# Les noms de worktrees deviennent des chemins : validation stricte partagée par create/remove/keep.
WORKTREES_DIR = WORKDIR / ".worktrees"; WORKTREES_DIR.mkdir(exist_ok=True)
VALID_WT_NAME = re.compile(r'^[A-Za-z0-9._-]{1,64}$')

def validate_worktree_name(name: str) -> str | None:
    """Frontière de sécurité au niveau outil — avant que git voie le nom."""
    if not name: return "Worktree name cannot be empty"
    if name in (".", ".."): return f"'{name}' is not a valid worktree name"
    if not VALID_WT_NAME.match(name):
        return (f"Invalid worktree name '{name}': "
                "only letters, digits, dots, underscores, dashes (1-64 chars)")
    return None

def run_git(args: list[str]) -> tuple[bool, str]:
    """Wrapper git → (succès, sortie tronquée à 5000 caractères)."""
    try:
        r = subprocess.run(["git"] + args, cwd=WORKDIR, capture_output=True, text=True, timeout=30)
        out = (r.stdout + r.stderr).strip()
        return r.returncode == 0, out[:5000] if out else "(no output)"
    except subprocess.TimeoutExpired: return False, "Error: git timeout"

def log_event(event_type: str, worktree_name: str, task_id: str = ""):
    """Journal d'audit append-only .worktrees/events.jsonl."""
    event = {"type": event_type, "worktree": worktree_name, "task_id": task_id, "ts": time.time()}
    with open(WORKTREES_DIR / "events.jsonl", "a") as f: f.write(json.dumps(event) + "\n")

def create_worktree(name: str, task_id: str = "") -> str:
    """Valide le nom (avant git), vérifie la tâche éventuelle, puis git worktree add + liaison tâche ↔ worktree."""
    err = validate_worktree_name(name)
    if err: return f"Error: {err}"
    if task_id:
        try: load_task(task_id)
        except FileNotFoundError: return f"Error: task {task_id} not found"
    path = WORKTREES_DIR / name
    if path.exists(): return f"Worktree '{name}' already exists at {path}"
    ok, result = run_git(["worktree", "add", str(path), "-b", f"wt/{name}", "HEAD"])
    if not ok: return f"Git error: {result}"
    if task_id: bind_task_to_worktree(task_id, name)
    log_event("create", name, task_id)
    print(f"  \033[33m[worktree] created: {name} at {path}\033[0m")
    return f"Worktree '{name}' created at {path}"

def bind_task_to_worktree(task_id: str, worktree_name: str):
    """Écrit le nom du worktree dans la tâche : le teammate qui la revendiquera y basculera ses outils fichiers."""
    task = load_task(task_id)
    task.worktree = worktree_name
    save_task(task)

def _count_worktree_changes(path: Path) -> tuple[int, int]:
    """(fichiers modifiés, commits non poussés) ; (-1, -1) si invérifiable."""
    def count(args):
        r = subprocess.run(args, cwd=path, capture_output=True, text=True, timeout=10)
        return len([l for l in r.stdout.strip().splitlines() if l.strip()])
    try:
        return count(["git", "status", "--porcelain"]), count(["git", "log", "@{push}..HEAD", "--oneline"])
    except Exception: return -1, -1

def remove_worktree(name: str, discard_changes: bool = False) -> str:
    """Suppression refusée par défaut s'il reste des changements (ou si la vérification échoue : incertitude = danger)."""
    err = validate_worktree_name(name)
    if err: return err
    path = WORKTREES_DIR / name
    if not path.exists(): return f"Worktree '{name}' not found"
    if not discard_changes:
        files, commits = _count_worktree_changes(path)
        if files < 0: return "Cannot verify status. Use discard_changes=true to force."
        if files > 0 or commits > 0:
            return (f"Worktree '{name}' has {files} file(s), {commits} commit(s). "
                    "Use discard_changes=true or keep_worktree.")
    ok1, _ = run_git(["worktree", "remove", str(path), "--force"])
    if not ok1: return f"Failed to remove worktree '{name}'"
    run_git(["branch", "-D", f"wt/{name}"])
    log_event("remove", name)
    print(f"  \033[33m[worktree] removed: {name}\033[0m")
    return f"Worktree '{name}' removed"

def keep_worktree(name: str) -> str:
    """Ne supprime rien : journalise et indique la branche à examiner."""
    err = validate_worktree_name(name)
    if err: return err
    log_event("keep", name)
    return f"Worktree '{name}' kept for review (branch: wt/{name})"

run_create_worktree = create_worktree
run_remove_worktree = remove_worktree
run_keep_worktree = keep_worktree

# ── MCP (s19) ──

# Outils à liaison tardive : connexion d'abord, puis fusion dans le pool sous le nom mcp__server__tool.
class MCPClient:
    """Découvre et appelle les outils d'un serveur MCP (mock pédagogique)."""

    def __init__(self, name: str):
        self.name = name; self.tools: list[dict] = []; self._handlers: dict[str, callable] = {}

    def register(self, tool_defs: list[dict], handlers: dict[str, callable]):
        self.tools = tool_defs; self._handlers = handlers

    def call_tool(self, tool_name: str, args: dict) -> str:
        handler = self._handlers.get(tool_name)
        if not handler: return f"MCP error: unknown tool '{tool_name}'"
        try: return handler(**args)
        except Exception as e: return f"MCP error: {e}"

mcp_clients: dict[str, MCPClient] = {}
_DISALLOWED_CHARS = re.compile(r'[^a-zA-Z0-9_-]')

def normalize_mcp_name(name: str) -> str:
    """Assainit les noms externes : tout hors [a-zA-Z0-9_-] devient _."""
    return _DISALLOWED_CHARS.sub('_', name)

def _mock_server_docs():
    client = MCPClient("docs")
    client.register(
        tool_defs=[
            _tool("search", "Search documentation. (readOnly)", ("query",), "inputSchema", query=_STR),
            _tool("get_version", "Get API version. (readOnly)", (), "inputSchema"),
        ],
        handlers={"search": lambda query: f"[docs] Found 3 results for '{query}'",
                  "get_version": lambda: "[docs] API v2.1.0"})
    return client

def _mock_server_deploy():
    client = MCPClient("deploy")
    client.register(
        tool_defs=[
            _tool("trigger", "Trigger a deployment. (destructive — requires approval in real CC)",
                  ("service",), "inputSchema", service=_STR),
            _tool("status", "Check deployment status. (readOnly)", ("service",), "inputSchema", service=_STR),
        ],
        handlers={"trigger": lambda service: f"[deploy] Triggered: {service}",
                  "status": lambda service: f"[deploy] {service}: running (v1.4.2)"})
    return client

MOCK_SERVERS = {"docs": _mock_server_docs, "deploy": _mock_server_deploy}

def connect_mcp(name: str) -> str:
    """Connexion idempotente ; les nouveaux outils ne sont utilisables qu'au tour suivant (assemble_tool_pool)."""
    if name in mcp_clients: return f"MCP server '{name}' already connected"
    factory = MOCK_SERVERS.get(name)
    if not factory: return f"Unknown server '{name}'. Available: {', '.join(MOCK_SERVERS.keys())}"
    mcp_client = factory()
    mcp_clients[name] = mcp_client
    tool_names = [t["name"] for t in mcp_client.tools]
    print(f"  \033[31m[mcp] connected: {name} → {tool_names}\033[0m")
    return (f"Connected to MCP server '{name}'. "
            f"Discovered {len(mcp_client.tools)} tools: {', '.join(tool_names)}")

def assemble_tool_pool() -> tuple[list[dict], dict]:
    """Pool BUILTIN_TOOLS + outils MCP (copies défensives, inputSchema → input_schema) ; les défauts de la lambda figent client/outil (capture tardive)."""
    tools = list(BUILTIN_TOOLS)
    handlers = dict(BUILTIN_HANDLERS)
    for server_name, mcp_client in mcp_clients.items():
        safe_server = normalize_mcp_name(server_name)
        for tool_def in mcp_client.tools:
            prefixed = f"mcp__{safe_server}__{normalize_mcp_name(tool_def['name'])}"
            tools.append({"name": prefixed, "description": tool_def.get("description", ""),
                          "input_schema": tool_def.get("inputSchema", {})})
            handlers[prefixed] = lambda *, c=mcp_client, t=tool_def["name"], **kw: c.call_tool(t, kw)
    return tools, handlers

run_connect_mcp = connect_mcp

# ── Registres BUILTIN_TOOLS / BUILTIN_HANDLERS ──

# Le modèle voit les schémas ; Python exécute les handlers. Les deux tables restent explicites.
BUILTIN_TOOLS = [
    _tool("bash", "Run a shell command.", ("command",), command=_STR, run_in_background=_BOOL),
    _tool("read_file", "Read file contents.", ("path",), path=_STR, limit=_INT, offset=_INT),
    _tool("write_file", "Write content to a file.", ("path", "content"), path=_STR, content=_STR),
    _tool("edit_file", "Replace exact text in a file once.", ("path", "old_text", "new_text"),
          path=_STR, old_text=_STR, new_text=_STR),
    _tool("glob", "Find files matching a glob pattern.", ("pattern",), pattern=_STR),
    _tool("todo_write", "Create and manage a task list for the current session.", ("todos",),
          todos={"type": "array",
                 "items": {"type": "object",
                           "properties": {"content": {"type": "string"},
                                          "status": {"type": "string",
                                                     "enum": ["pending", "in_progress", "completed"]}},
                           "required": ["content", "status"]}}),
    _tool("task", "Launch a focused subagent. Returns only its final summary.", ("description",),
          description=_STR),
    _tool("load_skill", "Load the full content of a skill by name.", ("name",), name=_STR),
    _tool("compact", "Summarize earlier conversation and continue with compacted context.", (), focus=_STR),
    _tool("create_task", "Create a task.", ("subject",), subject=_STR, description=_STR,
          blockedBy={"type": "array", "items": {"type": "string"}}),
    _tool("list_tasks", "List all tasks."),
    _tool("get_task", "Get full task details.", ("task_id",), task_id=_STR),
    _tool("claim_task", "Claim a pending task.", ("task_id",), task_id=_STR),
    _tool("complete_task", "Complete an in-progress task.", ("task_id",), task_id=_STR),
    _tool("schedule_cron", "Schedule a cron job. cron is 5-field: min hour dom month dow. "
          "For one-shot reminders, compute the target minute and set recurring=false.",
          ("cron", "prompt"), cron=_STR, prompt=_STR, recurring=_BOOL, durable=_BOOL),
    _tool("list_crons", "List registered cron jobs."),
    _tool("cancel_cron", "Cancel a cron job by ID.", ("job_id",), job_id=_STR),
    _tool("spawn_teammate", "Spawn an autonomous teammate.", ("name", "role", "prompt"),
          name=_STR, role=_STR, prompt=_STR),
    _tool("send_message", "Send message to a teammate.", ("to", "content"), to=_STR, content=_STR),
    _tool("check_inbox", "Check inbox for messages and protocol responses."),
    _tool("request_shutdown", "Request a teammate to shut down.", ("teammate",), teammate=_STR),
    _tool("request_plan", "Ask a teammate to submit a plan.", ("teammate", "task"),
          teammate=_STR, task=_STR),
    _tool("review_plan", "Approve or reject a submitted plan.", ("request_id", "approve"),
          request_id=_STR, approve=_BOOL, feedback=_STR),
    _tool("create_worktree", "Create an isolated git worktree.", ("name",), name=_STR, task_id=_STR),
    _tool("remove_worktree", "Remove a worktree. Refuses if changes exist.", ("name",),
          name=_STR, discard_changes=_BOOL),
    _tool("keep_worktree", "Keep a worktree for manual review.", ("name",), name=_STR),
    _tool("connect_mcp", "Connect to an MCP server (docs, deploy) and discover tools.", ("name",),
          name=_STR),
]

# NB : compact n'a pas de handler — intercepté par agent_loop avant dispatch (il doit réécrire messages).
BUILTIN_HANDLERS = {
    "bash": run_bash, "read_file": run_read, "write_file": run_write,
    "edit_file": run_edit, "glob": run_glob, "todo_write": run_todo_write,
    "task": spawn_subagent, "load_skill": load_skill,
    "create_task": run_create_task, "list_tasks": run_list_tasks,
    "get_task": run_get_task, "claim_task": run_claim_task,
    "complete_task": run_complete_task, "schedule_cron": run_schedule_cron,
    "list_crons": run_list_crons, "cancel_cron": run_cancel_cron,
    "spawn_teammate": run_spawn_teammate, "send_message": run_send_message,
    "check_inbox": run_check_inbox, "request_shutdown": run_request_shutdown,
    "request_plan": run_request_plan, "review_plan": run_review_plan,
    "create_worktree": run_create_worktree, "remove_worktree": run_remove_worktree,
    "keep_worktree": run_keep_worktree, "connect_mcp": run_connect_mcp,
}

# ── Agent loop & helpers ──

rounds_since_todo = 0
agent_lock = threading.Lock()

def prepare_context(messages: list) -> list:
    """Compaction EN PLACE avant chaque appel LLM (budget → snip → micro → compact) ; messages[:] = ... essentiel (historique partagé entre threads)."""
    messages[:] = tool_result_budget(messages)
    messages[:] = snip_compact(messages)
    messages[:] = micro_compact(messages)
    if estimate_size(messages) > CONTEXT_LIMIT:
        messages[:] = compact_history(messages)
    return messages

def build_user_content(results: list[dict]) -> list[dict]:
    """Fusionne les tool_result du tour et les <task_notification> d'arrière-plan en un seul message user."""
    return list(results) + [{"type": "text", "text": note} for note in collect_background_results()]

def inject_background_notifications(messages: list):
    """Second canal : résultats d'arrière-plan prêts en DÉBUT de tour, injectés comme message user autonome."""
    notes = collect_background_results()
    if notes:
        messages.append({"role": "user", "content": [{"type": "text", "text": note} for note in notes]})

def call_llm(messages: list, context: dict, tools: list,
             state: RecoveryState, max_tokens: int, system: str = None):
    """Assemble le system prompt vivant (sauf si system est fourni) et enveloppe l'appel API dans with_retry."""
    sys_prompt = system if system is not None else assemble_system_prompt(context)
    return with_retry(lambda: client.messages.create(model=state.current_model, system=sys_prompt,
                                                     messages=messages, tools=tools, max_tokens=max_tokens),
                      state)

def agent_loop(user_input: str = None, messages: list = None, *,
               tools: list = None, handlers: dict = None,
               system: str = None, context: dict = None) -> list:
    """LA boucle de synthèse (s20), paramétrable. Tous None = comportement s20 (pool builtin+MCP
    ré-assemblé à chaque tour, system prompt vivant, contexte mémoire/MCP/teammates). user_input →
    message user ; messages muté en place ; tools/handlers = pool figé ; system = prompt figé.
    Cycle : injections (cron, background, todo) → compaction → appel modèle → tool_use → tool_results."""
    global rounds_since_todo
    if messages is None: messages = []
    if user_input: messages.append({"role": "user", "content": user_input})
    if context is None: context = update_context({}, messages)
    # Pool figé si la session a fourni tools et/ou handlers.
    fixed_pool = tools is not None or handlers is not None
    if fixed_pool:
        turn_tools = tools if tools is not None else list(BUILTIN_TOOLS)
        turn_handlers = handlers if handlers is not None else dict(BUILTIN_HANDLERS)
    else:
        turn_tools, turn_handlers = assemble_tool_pool()
    state = RecoveryState()
    max_tokens = DEFAULT_MAX_TOKENS
    while True:
        # 1. Injections avant LLM : prompts cron tirés, notifications d'arrière-plan,
        # rappel todo tous les 3 tours.
        for job in consume_cron_queue():
            messages.append({"role": "user", "content": f"[Scheduled] {job.prompt}"})
            print(f"  \033[35m[cron inject] {job.prompt[:60]}\033[0m")
        inject_background_notifications(messages)
        if rounds_since_todo >= 3:
            messages.append({"role": "user", "content": "<reminder>Update your todos.</reminder>"})
            rounds_since_todo = 0
        # 2. Préparation : compaction, contexte vivant, ré-assemblage du pool
        # (c'est ce qui fait apparaître les outils MCP après connect_mcp).
        prepare_context(messages)
        context = update_context(context, messages)
        if not fixed_pool:
            turn_tools, turn_handlers = assemble_tool_pool()
        # 3. Appel LLM + récupération : prompt-too-long → reactive_compact (une fois) ;
        # autre erreur → message assistant [Error] visible.
        try:
            response = call_llm(messages, context, turn_tools, state, max_tokens, system=system)
        except Exception as e:
            if is_prompt_too_long_error(e) and not state.has_attempted_reactive_compact:
                messages[:] = reactive_compact(messages)
                state.has_attempted_reactive_compact = True
                continue
            messages.append({"role": "assistant", "content": [
                {"type": "text", "text": f"[Error] {type(e).__name__}: {e}"}]})
            return messages
        # max_tokens → escalade à ESCALATED_MAX_TOKENS, puis prompt de continuation
        # (MAX_RECOVERY_RETRIES fois max).
        if response.stop_reason == "max_tokens":
            if not state.has_escalated:
                max_tokens = ESCALATED_MAX_TOKENS
                state.has_escalated = True
                print(f"  \033[33m[max_tokens] retry with {max_tokens}\033[0m")
                continue
            messages.append({"role": "assistant", "content": response.content})
            if state.recovery_count < MAX_RECOVERY_RETRIES:
                messages.append({"role": "user", "content": CONTINUATION_PROMPT})
                state.recovery_count += 1
                continue
            return messages
        # 4. Sortie ou exécution : pas de tool_use → hook Stop et retour.
        max_tokens = DEFAULT_MAX_TOKENS
        state.has_escalated = False
        messages.append({"role": "assistant", "content": response.content})
        if not has_tool_use(response.content):
            trigger_hooks("Stop", messages)
            return messages
        # 5. Dispatch des outils : (a) compact = outil méta hors table ;
        # (b) hooks/permission ; (c) détour arrière-plan ; (d) dispatch normal.
        results = []
        compacted_now = False
        for block in response.content:
            if block.type != "tool_use": continue
            print(f"\033[36m> {block.name}\033[0m")
            if block.name == "compact":
                messages[:] = compact_history(messages)
                messages.append({"role": "user",
                                 "content": "[Compacted. Continue with summarized context.]"})
                compacted_now = True
                break
            blocked = trigger_hooks("PreToolUse", block)
            if blocked:
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(blocked)})
                continue
            if should_run_background(block.name, block.input):
                bg_id = start_background_task(block, turn_handlers)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": (f"[Background task {bg_id} started] "
                                            "Result will arrive as a task_notification.")})
                continue
            output = call_tool_handler(turn_handlers.get(block.name), block.input, block.name)
            trigger_hooks("PostToolUse", block, output)
            print(str(output)[:300])
            rounds_since_todo = 0 if block.name == "todo_write" else rounds_since_todo + 1
            results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
        if compacted_now: continue
        # 6. Retour au modèle : résultats + notifications, tour suivant.
        messages.append({"role": "user", "content": build_user_content(results)})

def print_turn_assistants(messages: list, turn_start: int):
    """Affiche les textes assistants produits depuis turn_start (rendu découplé, compatible threads)."""
    for msg in messages[turn_start:]:
        if msg.get("role") != "assistant": continue
        for block in msg.get("content", []):
            if getattr(block, "type", None) == "text":
                terminal_print(block.text)

def cron_autorun_loop(history: list, context: dict):
    """Agent long-running : un job cron tire → tour d'agent complet sur le même history, sous agent_lock (sérialise humain et cron)."""
    while True:
        time.sleep(1)
        fired = consume_cron_queue()
        if not fired: continue
        with agent_lock:
            turn_start = len(history)
            for job in fired:
                history.append({"role": "user", "content": f"[Scheduled] {job.prompt}"})
                terminal_print(f"  \033[35m[cron auto] {job.prompt[:60]}\033[0m")
            agent_loop(messages=history, context=context)
            context.update(update_context(context, history))
            print_turn_assistants(history, turn_start)
