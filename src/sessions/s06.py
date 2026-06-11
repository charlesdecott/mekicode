"""s06 — Subagent : déléguer un sous-problème à un contexte vierge.

Original : inspiration/learn-claude-code/s06_subagent/code.py (384 lignes).
Le délta de la session : un outil `task` qui appelle spawn_subagent() — une
boucle agent isolée (30 tours max) qui repart d'un messages[] frais ; tous
les pas intermédiaires sont jetés, seul le dernier texte assistant remonte
au parent. Anti-récursion : SUB_TOOLS (5 outils) ne contient pas `task`.
Point crucial : l'isolation de contexte n'est PAS une isolation de
permissions — les hooks PreToolUse/PostToolUse de shared s'appliquent aussi
aux outils exécutés par le sous-agent.

Tout le mécanisme (spawn_subagent, SUB_SYSTEM, SUB_TOOLS, SUB_HANDLERS,
hooks, agent_loop) vit dans shared.py. Ce fichier ne fait que câbler le
sous-ensemble d'outils du parent (5 outils de base + task) sur agent_loop
paramétrée, et offrir un raccourci `:sub` pour observer le sous-agent seul.
"""
import _bootstrap  # noqa: F401 — rend shared.py importable depuis sessions/
from shared import (BUILTIN_HANDLERS, BUILTIN_TOOLS, PROMPT, WORKDIR,
                    agent_loop, print_turn_assistants, spawn_subagent)


def pick(*names):
    """Sous-ensemble de BUILTIN_TOOLS par nom (schémas JSON complets)."""
    return [t for t in BUILTIN_TOOLS if t["name"] in names]


TOOL_NAMES = ("bash", "read_file", "write_file", "edit_file", "glob", "task")
TOOLS = pick(*TOOL_NAMES)
HANDLERS = {n: BUILTIN_HANDLERS[n] for n in TOOL_NAMES}

# System figé (pool figé => pas de ré-assemblage vivant) : il annonce la
# délégation, comme le SYSTEM de l'original s06.
SYSTEM = (
    f"You are a coding agent at {WORKDIR}. "
    "For complex sub-problems, use the task tool to spawn a subagent "
    "with a fresh context. Keep your final answers concise."
)


def main():
    print("s06 · Subagent — l'outil task délègue à shared.spawn_subagent()")
    print(f"Outils du parent : {', '.join(TOOL_NAMES)}")
    print("Le sous-agent n'a que 5 outils, sans task (anti-récursion).")
    print("':sub <description>' = sous-agent direct, 'q' = quitter.\n")
    history = []
    while True:
        try:
            user = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user or user.lower() in ("q", "quit", "exit"):
            break
        if user.startswith(":sub "):
            # Démo directe : un sous-agent one-shot, sans le parent. On ne
            # récupère que le résumé — l'historique du sous-agent est jeté.
            summary = spawn_subagent(user[len(":sub "):].strip())
            print(f"\n\033[35m[résumé du sous-agent]\033[0m\n{summary}\n")
            continue
        turn_start = len(history)
        agent_loop(user, history,
                   tools=TOOLS, handlers=HANDLERS, system=SYSTEM)
        print_turn_assistants(history, turn_start)


if __name__ == "__main__":
    main()
