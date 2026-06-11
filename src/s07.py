"""s07 — Skills : divulgation progressive (catalogue puis contenu).

Original : inspiration/learn-claude-code/s07_skill_loading/code.py
(427 lignes). Le délta de la session : un catalogue bon marché (nom +
description issus du frontmatter de chaque SKILL.md) injecté dans le system
prompt, et le contenu complet chargé À LA DEMANDE par l'outil load_skill —
il arrive alors en tool_result dans l'historique, pas dans le system.

Le mécanisme (scan_skills, SKILL_REGISTRY, list_skills, load_skill,
_parse_frontmatter) vit dans shared.py, qui définit SKILLS_DIR =
WORKDIR / "skills" et scanne à l'import. Ce fichier crée un dossier de
démo `skills-demo/` (2 skills, écriture idempotente), repointe
shared.SKILLS_DIR dessus puis rescanne : scan_skills() lit la globale du
module, la réaffecter suffit. La recherche de load_skill se fait dans le
registre (dict.get), jamais sur le disque : pas de path traversal possible.
"""

import shared  # gardé : ensure_demo_skills() rebinde shared.SKILLS_DIR
from shared import (BUILTIN_HANDLERS, BUILTIN_TOOLS, PROMPT, WORKDIR,
                    agent_loop, list_skills, load_skill,
                    print_turn_assistants, scan_skills)


def pick(*names):
    """Sous-ensemble de BUILTIN_TOOLS par nom (schémas JSON complets)."""
    return [t for t in BUILTIN_TOOLS if t["name"] in names]


TOOL_NAMES = ("bash", "read_file", "glob", "load_skill")
TOOLS = pick(*TOOL_NAMES)
HANDLERS = {n: BUILTIN_HANDLERS[n] for n in TOOL_NAMES}

SKILLS_DEMO_DIR = WORKDIR / "skills-demo"

# Contenus ASCII volontairement : shared lit les SKILL.md avec read_text()
# sans encodage explicite (encodage locale sous Windows).
DEMO_SKILLS = {
    "commit-style": (
        "---\n"
        "name: commit-style\n"
        "description: Project conventions for commit messages\n"
        "---\n\n"
        "# Commit conventions\n\n"
        "- Subject in imperative mood, 50 chars max.\n"
        "- Body explains the why, not the how.\n"
        "- Reference issues in the footer (Refs: #123).\n"
    ),
    "code-review": (
        "---\n"
        "name: code-review\n"
        "description: Checklist for reviewing a change\n"
        "---\n\n"
        "# Code review checklist\n\n"
        "1. Does the change do what it claims?\n"
        "2. Are edge cases and errors handled?\n"
        "3. Is anything duplicated that shared code already provides?\n"
    ),
}


def ensure_demo_skills():
    """Écrit les SKILL.md de démo (idempotent), repointe shared.SKILLS_DIR
    vers skills-demo/ et repeuple SKILL_REGISTRY via scan_skills()."""
    for slug, content in DEMO_SKILLS.items():
        manifest = SKILLS_DEMO_DIR / slug / "SKILL.md"
        if not manifest.exists():
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(content)
    shared.SKILLS_DIR = SKILLS_DEMO_DIR
    scan_skills()


def build_system():
    """Niveau 1 de la divulgation : le CATALOGUE entre dans le system prompt
    (~1 ligne par skill), jamais le contenu complet."""
    return (f"You are a coding agent at {WORKDIR}.\n"
            f"Skills available:\n{list_skills()}\n"
            "Use load_skill(name) to get the full instructions when relevant.")


def main():
    ensure_demo_skills()
    system = build_system()
    print("s07 · Skills — catalogue dans le system, contenu via load_skill")
    print(f"SKILLS_DIR repointé sur : {SKILLS_DEMO_DIR}")
    print("Catalogue scanné :")
    print(list_skills())
    print("\n':list' = catalogue, ':load <nom>' = contenu complet (local,")
    print("sans appel API), tout autre texte = agent, 'q' = quitter.\n")
    history = []
    while True:
        try:
            user = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user or user.lower() in ("q", "quit", "exit"):
            break
        if user == ":list":
            print(list_skills())
            continue
        if user.startswith(":load "):
            # Même fonction que celle câblée derrière l'outil load_skill ;
            # un nom inconnu renvoie la liste des skills disponibles.
            print(load_skill(user[len(":load "):].strip()))
            continue
        turn_start = len(history)
        agent_loop(user, history,
                   tools=TOOLS, handlers=HANDLERS, system=system)
        print_turn_assistants(history, turn_start)


if __name__ == "__main__":
    main()
