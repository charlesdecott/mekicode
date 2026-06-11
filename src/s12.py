"""s12 — Système de tâches : le graphe durable sous .tasks/.

Démo du système de tâches de shared.py, porté de
inspiration/learn-claude-code/s12_task_system/code.py : chaque tâche est un
fichier JSON (dataclass Task), les dépendances blockedBy forment un graphe
orienté, et claim_task/complete_task font respecter le cycle
pending -> in_progress -> completed en signalant les tâches débloquées.

L'original recopiait 377 lignes (outils fichiers, prompt, boucle, REPL) ;
ici tout vient de shared.py et le fichier ne garde que le câblage des
5 outils tâches + 3 outils fichiers dans agent_loop, plus une démo
hors-ligne du graphe de dépendances (`demo`). Lancement : python src/s12.py
"""

from shared import (
    BUILTIN_HANDLERS, BUILTIN_TOOLS, PROMPT, WORKDIR, agent_loop,
    claim_task, complete_task, create_task, print_turn_assistants,
    run_list_tasks,
)


def pick(*names):
    return [t for t in BUILTIN_TOOLS if t["name"] in names]


TOOL_NAMES = ("bash", "read_file", "write_file",
              "create_task", "list_tasks", "get_task",
              "claim_task", "complete_task")
TOOLS = pick(*TOOL_NAMES)
HANDLERS = {n: BUILTIN_HANDLERS[n] for n in TOOL_NAMES}
SYSTEM = ("You are a project agent with a durable task system. "
          "Tasks persist as JSON under .tasks/ and survive restarts. "
          "Workflow: create_task (blockedBy = dependency ids), claim_task, "
          "complete_task. A task is claimable only when every blockedBy "
          f"task is completed. Workspace: {WORKDIR}.")


def demo_graph():
    """Hors-ligne : deux tâches liées par blockedBy. Le claim de l'aval est
    refusé tant que l'amont n'est pas completed ; complete_task rapporte le
    déblocage en cascade."""
    a = create_task("Schéma de base de données",
                    "Créer les tables users et sessions")
    b = create_task("API REST", "Endpoints CRUD sur le schéma",
                    blockedBy=[a.id])
    print(f"  créées : {a.id} puis {b.id} (blockedBy=[{a.id}])")
    print(f"  claim aval (bloqué)   : {claim_task(b.id, 'demo')}")
    print(f"  claim amont           : {claim_task(a.id, 'demo')}")
    print(f"  complete amont        : {complete_task(a.id)}")
    print(f"  claim aval (débloqué) : {claim_task(b.id, 'demo')}")
    print(f"  complete aval         : {complete_task(b.id)}")
    print("  re-claim (refusé)     : "
          + claim_task(a.id, 'demo'))


def main():
    print("s12 — système de tâches. "
          "`demo` (graphe hors-ligne), `ls`, ou un prompt LLM. `q` pour quitter.")
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
            demo_graph()
            continue
        if user == "ls":
            print(run_list_tasks())
            continue
        turn_start = len(history)
        agent_loop(user, history,
                   tools=TOOLS, handlers=HANDLERS, system=SYSTEM)
        print_turn_assistants(history, turn_start)


if __name__ == "__main__":
    main()
