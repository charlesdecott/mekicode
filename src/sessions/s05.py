"""s05 — TodoWrite : un outil qui n'exécute rien, il fait planifier.

todo_write ne lit pas de fichier, ne lance pas de commande : il remplace en
bloc une liste d'étapes (pending / in_progress / completed). Sa valeur n'est
pas son effet mais son PASSAGE DANS LE CONTEXTE : chaque appel ré-écrit le
plan complet dans la conversation, donc le ramène dans le champ d'attention
du modèle au lieu de le laisser diluer par les résultats d'outils.

Deux mécanismes d'accompagnement, déjà dans shared :
- le rappel de planification (« nag ») : shared.agent_loop injecte
  « <reminder>Update your todos.</reminder> » quand rounds_since_todo
  atteint 3, et remet le compteur à zéro à chaque appel de todo_write ;
- la validation défensive : shared._normalize_todos accepte liste, chaîne
  JSON ou littéral Python, et renvoie des erreurs indexées au modèle.
Le délta de la session : prescrire la planification dans le SYSTEM (un outil
de pure discipline doit être prescrit, pas seulement disponible), câbler le
sous-ensemble d'outils incluant todo_write, et ré-afficher le plan courant
(shared.run_todo_write ne montre qu'un compteur).

Mapping vers l'original (inspiration/learn-claude-code/s05_todo_write/code.py) :
- CURRENT_TODOS, _normalize_todos, run_todo_write : portés dans shared.py ;
- le compteur rounds_since_todo + l'injection du <reminder> : intégrés à
  shared.agent_loop (incrément par appel d'outil, voir la page wiki) ;
- le rendu « ## Current Tasks » de l'original = afficher_todos() ci-dessous,
  déplacé hors du handler (l'affichage est un choix de session, pas d'outil).

Lancer : python src/sessions/s05.py   (q pour quitter)
Essai : « renomme les fichiers .txt en .md puis vérifie le résultat » —
        le modèle doit poser un plan avant d'agir, puis le tenir à jour.
"""
import _bootstrap  # noqa: F401 — rend shared.py importable depuis sessions/
import shared  # PROMPT rebindé ici ; CURRENT_TODOS rebindé par shared
from shared import (BUILTIN_TOOLS, BUILTIN_HANDLERS, WORKDIR, trigger_hooks,
                    agent_loop, print_turn_assistants)


def pick(*names):
    """Sous-ensemble de BUILTIN_TOOLS par noms — le délta de chaque session."""
    return [t for t in BUILTIN_TOOLS if t["name"] in names]


TOOL_NAMES = ("bash", "read_file", "write_file", "edit_file", "glob",
              "todo_write")
TOOLS = pick(*TOOL_NAMES)
HANDLERS = {name: BUILTIN_HANDLERS[name] for name in TOOL_NAMES}

# La consigne de planification : sans elle, le modèle ignore largement l'outil.
SYSTEM = (f"You are a coding agent at {WORKDIR}. "
          "Before starting any multi-step task, use todo_write to plan "
          "your steps. Update status as you go.")

ICONES = {"pending": " ", "in_progress": ">", "completed": "x"}


def afficher_todos():
    """Rend le plan courant pour l'humain (le modèle, lui, l'a déjà dans son
    propre appel tool_use — run_todo_write ne lui renvoie qu'un compteur)."""
    # via le module : shared rebinde ce nom à l'exécution (run_todo_write)
    if not shared.CURRENT_TODOS:
        return
    print("\033[33m## Plan courant\033[0m")
    for todo in shared.CURRENT_TODOS:
        print(f"  [{ICONES[todo['status']]}] {todo['content']}")


def main():
    shared.PROMPT = "\033[36ms05 >> \033[0m"
    print("s05 : todo_write — planifier avant d'exécuter, rappel après "
          "3 tours d'oubli")
    print(f"  outils : {', '.join(TOOL_NAMES)}")
    print("Tape une question, Entrée pour envoyer, q pour quitter.\n")
    history = []
    while True:
        try:
            query = input(shared.PROMPT)
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        trigger_hooks("UserPromptSubmit", query)
        turn_start = len(history)
        agent_loop(query, history,
                   tools=TOOLS, handlers=HANDLERS, system=SYSTEM)
        print_turn_assistants(history, turn_start)
        afficher_todos()
        print()


if __name__ == "__main__":
    main()
