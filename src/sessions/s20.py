"""s20 · L'agent complet — le CLI qui assemble tout le harness.

Concept : s20 n'introduit aucun mécanisme nouveau — c'est l'ORCHESTRATION.
Le pipeline d'un tour : saisie → hook UserPromptSubmit → injections (prompts
cron tirés, notifications d'arrière-plan, rappel todo) → compaction
(prepare_context) → system prompt vivant (mémoire + skills + MCP) → LLM →
tool_use ? → PreToolUse/permission → handlers (natifs, MCP ou arrière-plan)
→ PostToolUse → tool_result → tour suivant. Et autour de la boucle : un
thread cron_autorun_loop qui lance des tours d'agent AUTONOMES quand un job
cron tire, sérialisé avec la saisie humaine par agent_lock sur le même
history, et le drainage de l'inbox du lead après chaque tour (messages des
teammates routés vers les états de protocole puis injectés en [Inbox]).

Mapping vers l'original (inspiration/learn-claude-code/s20_comprehensive/
code.py, 2124 lignes) : tout le corps du fichier original EST shared.py —
registres BUILTIN_TOOLS/BUILTIN_HANDLERS (27 outils), agent_loop,
prepare_context, call_llm, hooks, compaction, mémoire (s09 porté),
print_turn_assistants, cron_autorun_loop... Le seul délta de cette session
est le bloc __main__ original (lignes 2088–2123), volontairement non porté
dans la bibliothèque : le REPL à double entrée reconstruit ici, plus le
helper local inbox_label (défini inline dans le __main__ original).

Lancement : python src/sessions/s20.py (exige MODEL_ID dans .env — c'est la seule
démo de s16–s20 qui appelle réellement le modèle).
"""

import threading
import _bootstrap  # noqa: F401 — rend shared.py importable depuis sessions/
import shared  # gardé : main() rebinde shared.CLI_ACTIVE
from shared import (PROMPT, agent_lock, agent_loop, consume_lead_inbox,
                    cron_autorun_loop, print_turn_assistants, trigger_hooks,
                    update_context)


def inbox_label(msg: dict) -> str:
    """Étiquette d'un message d'inbox : type + request_id éventuel — le lead
    voit `req:req_NNNNNN` et peut appeler review_plan avec le bon id.
    (Helper local : recréé ici, il n'existe pas dans shared.)"""
    req_id = msg.get("metadata", {}).get("request_id", "")
    suffix = f" req:{req_id}" if req_id else ""
    return f"{msg.get('type', 'message')}{suffix}"


def main():
    # CLI_ACTIVE pilote terminal_print : les threads d'arrière-plan
    # (teammates, bus, cron) redessinent la ligne readline en cours de
    # saisie au lieu de la casser.
    shared.CLI_ACTIVE = True
    print("s20 : agent complet (harness mekicode)")
    print("Entrez une question puis Entrée. q pour quitter.\n")

    # history et context sont PARTAGÉS entre la boucle humaine et le thread
    # cron : agent_lock sérialise les deux entrées sur la même conversation,
    # et agent_loop mute history en place (messages[:] = ...).
    history: list = []
    context = update_context({}, [])
    threading.Thread(target=cron_autorun_loop,
                     args=(history, context), daemon=True).start()

    while True:
        try:
            query = input(PROMPT)
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break

        # 1. Hook UserPromptSubmit, puis tour d'agent complet sous verrou.
        # tools/handlers/system laissés à None = registres complets par
        # défaut : pool builtin + MCP ré-assemblé à chaque tour, system
        # prompt vivant — le comportement s20 de la bibliothèque.
        trigger_hooks("UserPromptSubmit", query)
        turn_start = len(history)
        history.append({"role": "user", "content": query})
        with agent_lock:
            agent_loop(messages=history, context=context)
            context = update_context(context, history)
            print_turn_assistants(history, turn_start)

        # 2. Après le tour : drainage de l'inbox du lead. Les *_response
        # sont routées vers les états de protocole (même si le modèle n'a
        # pas appelé check_inbox), puis tout est injecté dans history en
        # [Inbox] — le modèle les verra au prochain tour, sans relance.
        inbox = consume_lead_inbox(route_protocol=True)
        if inbox:
            inbox_text = "\n".join(
                f"From {m['from']} [{inbox_label(m)}]: "
                f"{m['content'][:200]}" for m in inbox)
            history.append({"role": "user",
                            "content": f"[Inbox]\n{inbox_text}"})
        print()


if __name__ == "__main__":
    main()
