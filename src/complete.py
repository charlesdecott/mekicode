"""complete.py — LE point d'entrée du harness mekicode : toutes les features.

Là où chaque sessions/sNN.py ne démontre qu'UN mécanisme, complete.py les
active tous en même temps, uniquement en câblant shared.py :

- registres complets par défaut (tools/handlers/system à None) : 27 outils
  natifs + pool MCP ré-assemblé à chaque tour, system prompt VIVANT
  (mémoire, skills, MCP, teammates via update_context) ;
- hooks et permissions enregistrés à l'import de shared (PreToolUse/
  PostToolUse/UserPromptSubmit/Stop, deny list, confirmations) ;
- compaction automatique du contexte dans prepare_context/agent_loop ;
- mémoire persistante — les trois moments de s09 : sélection injectée dans
  le tour utilisateur (load_memories), index MEMORY.md dans le system vivant
  (update_context), extraction + consolidation post-tour ;
- thread cron_autorun_loop : les jobs cron déclenchent des tours d'agent
  AUTONOMES, sérialisés avec la saisie humaine par agent_lock sur le même
  history ;
- drainage de l'inbox du lead après chaque tour : réponses de protocole
  routées (consume_lead_inbox) puis injectées en [Inbox] pour le tour
  suivant ;
- todos, tâches, background, teams, worktrees, subagents : disponibles via
  les outils du registre.

Méta-commandes locales (sans appel API) : :aide, :memoire (index MEMORY.md),
:taches (tableau des tâches). q pour quitter ; une entrée vide ré-affiche
le prompt (contrairement aux démos sNN, où vide = quitter).

Lancement : python src/complete.py   (exige ANTHROPIC_API_KEY et MODEL_ID
dans .env — voir .env.example à la racine).
"""

import threading

import shared  # main() rebinde shared.CLI_ACTIVE
from shared import (PROMPT, agent_lock, agent_loop, consolidate_memories,
                    consume_lead_inbox, cron_autorun_loop, extract_memories,
                    load_memories, print_turn_assistants, read_memory_index,
                    run_list_tasks, trigger_hooks, update_context)

AIDE = """Méta-commandes :
  :aide      cette aide
  :memoire   index MEMORY.md (mémoires persistantes)
  :taches    tableau des tâches (.tasks/)
  q / exit   quitter
Tout le reste part à l'agent (outils complets + MCP + mémoire + cron)."""


def inbox_label(msg: dict) -> str:
    """Étiquette d'un message d'inbox : type + request_id éventuel — le lead
    voit `req:req_NNNNNN` et peut appeler review_plan avec le bon id."""
    req_id = msg.get("metadata", {}).get("request_id", "")
    return f"{msg.get('type', 'message')}{f' req:{req_id}' if req_id else ''}"


def main():
    # CLI_ACTIVE pilote terminal_print : les threads d'arrière-plan
    # (teammates, bus, cron) redessinent la ligne readline au lieu de la casser.
    shared.CLI_ACTIVE = True
    print("mekicode — harness complet (shared.py, toutes features)")
    print("':aide' pour les méta-commandes, q pour quitter.\n")

    # history et context sont PARTAGÉS entre la boucle humaine et le thread
    # cron : agent_lock sérialise les deux entrées sur la même conversation.
    history: list = []
    context = update_context({}, [])
    threading.Thread(target=cron_autorun_loop,
                     args=(history, context), daemon=True).start()

    while True:
        try:
            query = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not query:
            continue
        if query.lower() in ("q", "exit"):
            break
        if query == ":aide":
            print(AIDE)
            continue
        if query == ":memoire":
            print(read_memory_index() or "(index vide)")
            continue
        if query == ":taches":
            print(run_list_tasks())
            continue

        # 1. Hook UserPromptSubmit puis mémoire (moment 1/3) : confronter la
        # conversation au catalogue et injecter les mémoires pertinentes dans
        # le TOUR utilisateur (load_memories : 1 appel LLM, repli mots-clés).
        trigger_hooks("UserPromptSubmit", query)
        probe = history + [{"role": "user", "content": query}]
        mem_block = load_memories(probe)
        user_input = f"{mem_block}\n\n{query}" if mem_block else query

        # 2. Tour d'agent complet sous verrou. tools/handlers/system à None =
        # registres complets + pool MCP ré-assemblé + system prompt vivant
        # (moment 2/3 de la mémoire : l'index MEMORY.md y figure via context).
        turn_start = len(history)
        history.append({"role": "user", "content": user_input})
        with agent_lock:
            agent_loop(messages=history, context=context)
            context = update_context(context, history)
            print_turn_assistants(history, turn_start)

        # 3. Post-tour — mémoire (moment 3/3) : extraction de nouvelles
        # mémoires (anti-doublons, échec silencieux) puis consolidation.
        extract_memories(history)
        consolidate_memories()

        # 4. Drainage de l'inbox du lead : réponses de protocole routées même
        # si le modèle n'a pas appelé check_inbox, puis injection en [Inbox] —
        # visibles par le modèle au prochain tour, sans relance.
        inbox = consume_lead_inbox(route_protocol=True)
        if inbox:
            inbox_text = "\n".join(
                f"From {m['from']} [{inbox_label(m)}]: {m['content'][:200]}"
                for m in inbox)
            history.append({"role": "user", "content": f"[Inbox]\n{inbox_text}"})
        print()


if __name__ == "__main__":
    main()
