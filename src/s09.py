"""s09 — Mémoire persistante : une couche qui survit à la compaction.

Original : inspiration/learn-claude-code/s09_memory/code.py (656 lignes).
La compaction de s08 est avec perte ; s09 ajoute un magasin `.memory/*.md`
(frontmatter name/description/type) + un index MEMORY.md, qui persiste entre
les sessions. Tout le sous-système vit dans shared.py : write_memory_file
(écriture + reconstruction d'index), load_memories (sélection LLM avec repli
mots-clés, contenu en bloc <relevant_memories>), extract_memories
(extraction post-tour, anti-doublons), consolidate_memories (fusion à partir
de 10 fichiers) et update_context (l'index dans le dict de contexte que
assemble_system_prompt injecte dans le system vivant).

Le délta de ce fichier : le câblage des trois moments mémoire autour
d'agent_loop — injection de load_memories() dans le tour utilisateur,
system vivant (system=None → l'index MEMORY.md y figure via update_context),
extraction + consolidation après le tour — plus des commandes locales pour
observer l'état (:seed, :index, :fichiers, :ctx) sans appel API.
"""

import json

from shared import (BUILTIN_HANDLERS, BUILTIN_TOOLS, MEMORY_DIR, PROMPT,
                    agent_loop, consolidate_memories, extract_memories,
                    list_memory_files, load_memories, print_turn_assistants,
                    read_memory_index, update_context, write_memory_file)


def pick(*names):
    """Sous-ensemble de BUILTIN_TOOLS par nom (schémas JSON complets)."""
    return [t for t in BUILTIN_TOOLS if t["name"] in names]


TOOL_NAMES = ("bash", "read_file", "write_file", "glob")
TOOLS = pick(*TOOL_NAMES)
HANDLERS = {n: BUILTIN_HANDLERS[n] for n in TOOL_NAMES}

# Mémoires d'exemple (ASCII : shared écrit/lit sans encodage explicite).
EXEMPLES = [
    ("user-preference-langue", "user",
     "The user wants answers in French",
     "Always answer in French, even when the question is in English."),
    ("projet-structure", "project",
     "Layout of the mekicode repository",
     "shared.py holds the whole harness; each sNN.py only wires the delta "
     "of its session on top of it."),
]


def seed():
    """Écrit les mémoires d'exemple via write_memory_file (l'index MEMORY.md
    est reconstruit à chaque écriture) — 0 appel API."""
    for name, mem_type, desc, body in EXEMPLES:
        path = write_memory_file(name, mem_type, desc, body)
        print(f"  écrit : {path.name} [{mem_type}]")
    print("index reconstruit :")
    print(read_memory_index())


def main():
    print("s09 · Mémoire — .memory/*.md + MEMORY.md, sélection / extraction")
    print(f"MEMORY_DIR : {MEMORY_DIR}")
    print("':seed' = mémoires d'exemple, ':index' = MEMORY.md, ':fichiers' =")
    print("liste détaillée, ':ctx' = update_context, texte = agent, 'q' = quitter.\n")
    history = []
    while True:
        try:
            user = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user or user.lower() in ("q", "quit", "exit"):
            break
        if user == ":seed":
            seed()
            continue
        if user == ":index":
            print(read_memory_index() or "(index vide)")
            continue
        if user == ":fichiers":
            for m in list_memory_files():
                print(f"- {m['filename']} [{m['type']}] {m['description']}")
            continue
        if user == ":ctx":
            # Le dict consommé par assemble_system_prompt : l'index MEMORY.md
            # (2000 premiers caractères) + état vivant MCP/teammates.
            print(json.dumps(update_context({}, history),
                             indent=2, ensure_ascii=False))
            continue

        # 1. Sélection : confronte la conversation récente au catalogue
        # (1 appel LLM, repli mots-clés) et charge le contenu des mémoires
        # retenues. Injecté dans le TOUR utilisateur, pas dans le system.
        probe = history + [{"role": "user", "content": user}]
        mem_block = load_memories(probe)
        if mem_block:
            print(f"  \033[33m[mémoire] {mem_block.count('---') // 2} "
                  f"fichier(s) injecté(s) dans le tour\033[0m")
        user_input = f"{mem_block}\n\n{user}" if mem_block else user

        # 2. Tour d'agent avec system VIVANT (system=None) : update_context
        # place l'index MEMORY.md dans le system prompt à chaque tour.
        turn_start = len(history)
        agent_loop(user_input, history, tools=TOOLS, handlers=HANDLERS)
        print_turn_assistants(history, turn_start)

        # 3. Post-tour : extraction de nouvelles mémoires (anti-doublons,
        # échec silencieux) puis consolidation au-delà de 10 fichiers.
        extract_memories(history)
        consolidate_memories()


if __name__ == "__main__":
    main()
