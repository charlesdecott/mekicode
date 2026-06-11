"""s13 — Tâches d'arrière-plan : ne jamais attendre devant le hublot.

Démo du sous-système background de shared.py, porté de
inspiration/learn-claude-code/s13_background_tasks/code.py :

- is_slow_operation / should_run_background : demande explicite du modèle
  (run_in_background) OU heuristique mots-clés (install, build, test...) ;
- start_background_task   : worker daemon, placeholder tool_result immédiat ;
- collect_background_results : drainage en blocs <task_notification> ;
- inject_background_notifications : second canal, en début de tour.

L'original recopiait 479 lignes ; ici tout vient de shared.py — agent_loop
fait déjà le dispatch sync/async et les deux canaux de livraison. Ce fichier
ajoute une démo hors-ligne (`demo`) qui pilote start_background_task avec un
faux bloc tool_use, et `heuristic` qui montre la décision sync/async.
Lancement : python src/sessions/s13.py
"""

import time
import _bootstrap  # noqa: F401 — rend shared.py importable depuis sessions/
from shared import (
    BUILTIN_HANDLERS, BUILTIN_TOOLS, PROMPT, WORKDIR, agent_loop,
    inject_background_notifications, is_slow_operation,
    print_turn_assistants, should_run_background, start_background_task,
)


def pick(*names):
    return [t for t in BUILTIN_TOOLS if t["name"] in names]


TOOL_NAMES = ("bash", "read_file", "write_file")
TOOLS = pick(*TOOL_NAMES)
HANDLERS = {n: BUILTIN_HANDLERS[n] for n in TOOL_NAMES}
SYSTEM = ("You are a coding agent. Slow bash commands (installs, builds, "
          "tests) can run in the background: pass run_in_background=true, "
          "you get a placeholder at once and the result arrives later as a "
          f"<task_notification>. Workspace: {WORKDIR}.")


class DemoBlock:
    """Stand-in minimal d'un bloc tool_use du SDK (type/name/input/id) :
    juste ce qu'il faut pour piloter start_background_task sans appel LLM."""
    _seq = 0

    def __init__(self, command: str):
        DemoBlock._seq += 1
        self.type = "tool_use"
        self.name = "bash"
        self.input = {"command": command, "run_in_background": True}
        self.id = f"demo_bg_{DemoBlock._seq:04d}"


def show_heuristic():
    """Hors-ligne : la décision sync/async. La demande explicite du modèle
    prime ; sinon l'heuristique par sous-chaînes décide (et se trompe
    parfois : 'cat latest.log' contient 'test')."""
    samples = ["pip install requests", "npm run build", "echo bonjour",
               "python -m pytest -q", "cat latest.log"]
    for cmd in samples:
        bg = should_run_background("bash", {"command": cmd})
        slow = is_slow_operation("bash", {"command": cmd})
        print(f"  {'BACKGROUND' if bg else 'sync      '} "
              f"(heuristique={slow}) <- {cmd}")
    forced = {"command": "echo vite", "run_in_background": True}
    print(f"  BACKGROUND (explicite={should_run_background('bash', forced)})"
          f" <- {forced['command']} + run_in_background=true")


def demo_background(history: list):
    """Hors-ligne : une commande de ~2 s part en worker daemon ; le
    placeholder revient immédiatement, puis inject_background_notifications
    livre la <task_notification> dans l'historique dès qu'elle est prête."""
    cmd = 'python -c "import time; time.sleep(2); print(\'fini\')"'
    bg_id = start_background_task(DemoBlock(cmd), HANDLERS)
    print(f"  placeholder immédiat : [Background task {bg_id} started]")
    print("  l'agent resterait libre pendant ce temps... (polling 0.5 s)")
    while True:
        time.sleep(0.5)
        before = len(history)
        inject_background_notifications(history)
        if len(history) > before:
            break
    print("  notification injectée comme message user :")
    for block in history[-1]["content"]:
        print("    " + block["text"].replace("\n", "\n    "))
    # On retire le message de démo : pas de message user orphelin dans
    # l'historique envoyé au LLM aux tours suivants.
    history.pop()


def main():
    print("s13 — tâches d'arrière-plan. "
          "`demo`, `heuristic`, ou un prompt LLM. `q` pour quitter.")
    history = []
    while True:
        try:
            user = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user.lower() in ("q", "quit", "exit"):
            break
        if not user:
            continue
        if user == "demo":
            demo_background(history)
            continue
        if user == "heuristic":
            show_heuristic()
            continue
        turn_start = len(history)
        agent_loop(user, history,
                   tools=TOOLS, handlers=HANDLERS, system=SYSTEM)
        print_turn_assistants(history, turn_start)


if __name__ == "__main__":
    main()
