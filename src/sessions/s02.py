"""s02 — Tool use et dispatch : la boucle devient un moteur générique.

Deux tables parallèles font tout le travail :
- TOOLS dit au MODÈLE ce qui existe (schémas JSON envoyés à l'API) ;
- HANDLERS dit au HARNESS quoi exécuter (nom → fonction Python).
Ajouter un outil = une entrée dans chaque table ; la boucle n'est jamais
touchée. C'est le slogan de la session : « add a tool, add just one handler ».

Mapping vers l'original (inspiration/learn-claude-code/s02_tool_use/code.py) :
- safe_path, run_bash/run_read/run_write et leurs schémas : déjà dans
  shared.py (BUILTIN_TOOLS / BUILTIN_HANDLERS) — on n'en recâble ici qu'un
  sous-ensemble de 3 outils via pick() ;
- TOOL_HANDLERS de l'original = le dict HANDLERS passé à shared.agent_loop ;
- la boucle while de l'original = shared.agent_loop, paramétrée
  tools/handlers/system : pool figé (pas de ré-assemblage MCP) et system
  prompt figé (pas de system vivant).

Lancer : python src/sessions/s02.py   (q pour quitter)
"""
import _bootstrap  # noqa: F401 — rend shared.py importable depuis sessions/
import shared  # rebind de shared.PROMPT : l'affectation doit viser le module
from shared import (BUILTIN_TOOLS, BUILTIN_HANDLERS, WORKDIR, agent_loop,
                    print_turn_assistants)


def pick(*names):
    """Sous-ensemble de BUILTIN_TOOLS par noms — le délta de chaque session."""
    return [t for t in BUILTIN_TOOLS if t["name"] in names]


TOOL_NAMES = ("bash", "read_file", "write_file")
TOOLS = pick(*TOOL_NAMES)
HANDLERS = {name: BUILTIN_HANDLERS[name] for name in TOOL_NAMES}

SYSTEM = (f"You are a coding agent at {WORKDIR}. "
          "Use tools to solve tasks. Act, don't explain.")


def main():
    shared.PROMPT = "\033[36ms02 >> \033[0m"
    print(f"s02 : tool use et dispatch — pool figé de {len(TOOLS)} outils "
          f"({', '.join(TOOL_NAMES)})")
    print("Tape une question, Entrée pour envoyer, q pour quitter.\n")
    history = []
    while True:
        try:
            query = input(shared.PROMPT)
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        turn_start = len(history)
        agent_loop(query, history,
                   tools=TOOLS, handlers=HANDLERS, system=SYSTEM)
        print_turn_assistants(history, turn_start)
        print()


if __name__ == "__main__":
    main()
