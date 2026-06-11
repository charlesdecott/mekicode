"""Gestion de la connaissance et du contexte : skills à la demande (s05),
compaction de l'historique et mémoire persistante (s06)."""

import json
from datetime import datetime
from pathlib import Path

import yaml

from core import MODEL, ROOT, STATE_DIR, client, paint
from tools import register_tool

# FIX(mekicode): SKILLS_DIR dans le repo (la source remontait hors du dépôt avec parent.parent)
SKILLS_DIR: Path = ROOT / "skills"
MEMORY_FILE: Path = STATE_DIR / "MEMORY.md"
COMPACT_THRESHOLD: int = 40_000  # même valeur que s06 (ici en tokens estimés)
KEEP_RECENT: int = 6             # messages gardés verbatim


# ---------------------------------------------------------------- skills (s05)

def _skill_description(md: str) -> str:
    """Description d'un SKILL.md. FIX(mekicode): lue dans le frontmatter YAML
    (la source lisait le corps) ; repli sur la première ligne utile du corps."""
    body = md
    if md.startswith("---"):
        end = md.find("\n---", 3)
        if end != -1:
            body = md[end + 4:]
            try:
                meta = yaml.safe_load(md[3:end])
            except yaml.YAMLError:
                meta = None
            if isinstance(meta, dict) and meta.get("description"):
                return str(meta["description"]).strip()
    for line in body.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            return s[:100]
    return "No description available."


def skills_index() -> str:
    """Index léger « - nom: description » destiné au prompt système."""
    if not SKILLS_DIR.exists():
        return "(none currently installed)"
    lines = []
    for d in sorted(SKILLS_DIR.iterdir()):
        md = d / "SKILL.md"
        if d.is_dir() and md.exists():
            try:
                lines.append(f"- {d.name}: {_skill_description(md.read_text(encoding='utf-8'))}")
            except Exception as e:
                lines.append(f"- {d.name}: Error reading metadata: {e}")
    return "\n".join(lines) or "(none currently installed)"


def load_skill(name: str) -> str:
    """Charge le contenu complet d'un skill dans le contexte."""
    path = (SKILLS_DIR / name / "SKILL.md").resolve()
    # FIX(mekicode): vraie garde anti-traversée (la source l'annonçait sans la faire)
    if SKILLS_DIR.resolve() not in path.parents or not path.exists():
        return f"Error: skill '{name}' not found. Available:\n{skills_index()}"
    try:
        return f"=== SKILL: {name} ===\n\n{path.read_text(encoding='utf-8')}\n\n=== END SKILL ==="
    except Exception as e:
        return f"Error loading skill '{name}': {e}"


register_tool(
    {
        "name": "load_skill",
        "description": (
            "Load the full instructions for a skill into your context. "
            "Use this before starting a task requiring specialized domain knowledge."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string",
                                    "description": "The exact name of the skill folder to load."}},
            "required": ["name"],
        },
    },
    lambda inp: load_skill(inp["name"]),
)


# ------------------------------------------------- compaction & mémoire (s06)

def load_memory() -> str:
    """Mémoire persistante, "" si absente."""
    return MEMORY_FILE.read_text(encoding="utf-8") if MEMORY_FILE.exists() else ""


def estimate_tokens(messages: list) -> int:
    """Estimation grossière : ~4 caractères de JSON par token."""
    return len(json.dumps(messages, default=str, ensure_ascii=False)) // 4


def _flatten(messages: list) -> str:
    """Aplatissement textuel [role]: texte pour le compresseur."""
    out = []
    for m in messages:
        c = m.get("content", "")
        if not isinstance(c, str):
            c = " ".join(
                (b.get("text") or str(b.get("content", "")) if isinstance(b, dict)
                 else getattr(b, "text", "") or "")
                for b in (c if isinstance(c, list) else [])
            )
        out.append(f"[{m['role']}]: {c}")
    return "\n\n".join(out)


def _summarize(messages: list) -> str:
    """Résumé LLM one-shot de la partie ancienne (appel direct, hors boucle)."""
    response = client.messages.create(
        model=MODEL,
        system=("You are a context compressor. Summarize the provided conversation history "
                "concisely. Retain all critical technical decisions, file paths mentioned, "
                "code changes made, and pending tasks. Ignore trivial back-and-forth."),
        messages=[{"role": "user",
                   "content": f"Summarize this history:\n\n{_flatten(messages)[:20000]}"}],
        max_tokens=2000,
    )
    return "".join(b.text for b in response.content if hasattr(b, "text"))


def _has_tool_result(msg: dict) -> bool:
    """Vrai si message user composé de blocs tool_result (frontière interdite)."""
    c = msg.get("content")
    return (msg.get("role") == "user" and isinstance(c, list)
            and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c))


def maybe_compact(messages: list, keep_recent: int = KEEP_RECENT, force: bool = False) -> list:
    """Si le seuil est dépassé (ou force=True — commande :compact) : résume la partie
    ancienne, persiste la mémoire datée, retourne [résumé] + messages récents."""
    if (not force and estimate_tokens(messages) < COMPACT_THRESHOLD) or len(messages) <= keep_recent:
        return messages
    # FIX(mekicode): la coupe recule jusqu'à une frontière propre — le premier message
    # gardé ne peut pas être un tool_result dont le tool_use assistant serait résumé
    cut = len(messages) - keep_recent
    while cut > 0 and _has_tool_result(messages[cut]):
        cut -= 1
    if cut <= 0:
        return messages
    print(paint("  [compact] contexte volumineux — condensation de l'historique ancien...", "dim"))
    old, recent = messages[:cut], messages[cut:]
    summary = _summarize(old)
    # FIX(mekicode): mémoire datée (la source écrivait os.getcwd()) et en append
    try:
        with MEMORY_FILE.open("a", encoding="utf-8") as f:
            f.write(f"\n## Compaction du {datetime.now():%Y-%m-%d %H:%M}\n\n{summary}\n")
    except OSError as e:
        print(paint(f"  [compact] échec d'écriture mémoire : {e}", "red"))
    print(paint(f"  [compact] {len(old)} messages → 1 résumé (mémoire : {MEMORY_FILE})", "dim"))
    return [{"role": "user",
             "content": f"[Context summary of previous turns]:\n\n{summary}"}] + recent
