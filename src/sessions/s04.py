"""s04 — Hooks : étendre l'agent sans rouvrir la boucle.

Le patron observateur appliqué au cycle d'agent : un registre HOOKS
(événement → liste de callbacks), register_hook() pour s'abonner,
trigger_hooks() déclenché par la boucle à quatre moments :
UserPromptSubmit, PreToolUse, PostToolUse, Stop. Convention de retour :
None = laisser passer ; non-None = court-circuit (pour PreToolUse, la
chaîne retournée devient le tool_result de blocage).

Dans notre harness, le mécanisme ET les hooks de base vivent dans shared.py :
log_hook et large_output_hook y sont déjà enregistrés à l'import (avec
permission_hook, user_prompt_hook et stop_hook). Le délta de cette session :
1. afficher le registre HOOKS câblé par shared — qui écoute quoi ;
2. empiler deux hooks custom de démo (compteur PostToolUse + bilan Stop) ;
3. déclencher nous-mêmes trigger_hooks("UserPromptSubmit", ...) dans le REPL,
   le seul des quatre événements qui appartient au CLI, pas à la boucle.

Mapping vers l'original (inspiration/learn-claude-code/s04_hooks/code.py) :
- HOOKS, register_hook, trigger_hooks : portés tels quels dans shared.py ;
- permission_hook / log_hook / large_output_hook / context_inject_hook /
  summary_hook de l'original = permission_hook / log_hook /
  large_output_hook / user_prompt_hook / stop_hook de shared ;
- les hooks custom ci-dessous remplacent la paire « observation + bilan »
  pour montrer qu'une session peut s'abonner sans toucher à la bibliothèque.

Lancer : python src/sessions/s04.py   (q pour quitter)
"""
import _bootstrap  # noqa: F401 — rend shared.py importable depuis sessions/
import shared  # rebind de shared.PROMPT : l'affectation doit viser le module
from shared import (BUILTIN_TOOLS, BUILTIN_HANDLERS, WORKDIR, HOOKS,
                    register_hook, trigger_hooks, agent_loop,
                    print_turn_assistants)


def pick(*names):
    """Sous-ensemble de BUILTIN_TOOLS par noms — le délta de chaque session."""
    return [t for t in BUILTIN_TOOLS if t["name"] in names]


TOOL_NAMES = ("bash", "read_file", "write_file", "glob")
TOOLS = pick(*TOOL_NAMES)
HANDLERS = {name: BUILTIN_HANDLERS[name] for name in TOOL_NAMES}

SYSTEM = (f"You are a coding agent at {WORKDIR}. "
          "Use tools to solve tasks. Act, don't explain.")

# État du hook custom : tally des appels d'outils, rempli par PostToolUse.
USAGE_PAR_OUTIL: dict[str, int] = {}


def compteur_hook(block, output):
    """PostToolUse custom : compte chaque exécution, par nom d'outil.

    Observation pure : retourne toujours None (ne court-circuite jamais).
    Ne voit que les outils réellement exécutés — un appel bloqué par
    permission_hook ne passe jamais par PostToolUse.
    """
    USAGE_PAR_OUTIL[block.name] = USAGE_PAR_OUTIL.get(block.name, 0) + 1
    return None


def bilan_hook(messages):
    """Stop custom : affiche le tally du compteur en fin de tour.

    Retourner une valeur non-None ici forcerait la boucle à continuer
    (contrat du hook Stop) ; on retourne None = autoriser l'arrêt.
    """
    if USAGE_PAR_OUTIL:
        bilan = ", ".join(f"{name} x{count}" for name, count
                          in sorted(USAGE_PAR_OUTIL.items()))
        print(f"\033[90m[HOOK] bilan outils : {bilan}\033[0m")
    return None


register_hook("PostToolUse", compteur_hook)
register_hook("Stop", bilan_hook)


def afficher_registre():
    """Montre HOOKS après câblage : hooks de shared + hooks de la session."""
    print("  registre HOOKS :")
    for event, callbacks in HOOKS.items():
        noms = ", ".join(cb.__name__ for cb in callbacks) or "(aucun)"
        print(f"    {event}: {noms}")


def main():
    shared.PROMPT = "\033[36ms04 >> \033[0m"
    print("s04 : hooks — la boucle n'appelle plus que trigger_hooks()")
    afficher_registre()
    print("Tape une question, Entrée pour envoyer, q pour quitter.\n")
    history = []
    while True:
        try:
            query = input(shared.PROMPT)
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        # Le 4e point d'accroche : UserPromptSubmit se déclenche dans le REPL,
        # entre la saisie et l'entrée du message dans l'historique.
        trigger_hooks("UserPromptSubmit", query)
        turn_start = len(history)
        agent_loop(query, history,
                   tools=TOOLS, handlers=HANDLERS, system=SYSTEM)
        print_turn_assistants(history, turn_start)
        print()


if __name__ == "__main__":
    main()
