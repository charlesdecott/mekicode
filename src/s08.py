"""s08 — Compaction de contexte : le bon marché d'abord, le coûteux en dernier.

Original : inspiration/learn-claude-code/s08_context_compact/code.py
(525 lignes). Le pipeline complet vit dans shared.py — tool_result_budget
(persiste les sorties géantes) → snip_compact (coupe le milieu sans casser
une paire tool_use/tool_result) → micro_compact (placeholders sur les vieux
tool_result) → compact_history (résumé LLM, 1 appel API) — appliqué par
prepare_context avant CHAQUE appel modèle, plus reactive_compact en urgence
après une erreur « prompt too long ».

Le délta de ce fichier : des seuils module-level de shared abaissés
(CONTEXT_LIMIT 50000→6000, KEEP_RECENT_TOOL_RESULTS 3→1, PERSIST_THRESHOLD
30000→1000 — tous en caractères JSON, pas en tokens) pour que la compaction
se déclenche vite, et une démo « à sec » (:sec, 0 appel API) qui rejoue les
couches structurelles sur un historique synthétique en montrant la taille
après chaque couche.
"""

import shared  # gardé : ce fichier rebinde les seuils shared.CONTEXT_LIMIT & co
from shared import (BUILTIN_HANDLERS, BUILTIN_TOOLS, PROMPT,
                    TOOL_RESULTS_DIR, WORKDIR, agent_loop, compact_history,
                    estimate_size, micro_compact, print_turn_assistants,
                    reactive_compact, snip_compact, tool_result_budget)


def pick(*names):
    """Sous-ensemble de BUILTIN_TOOLS par nom (schémas JSON complets)."""
    return [t for t in BUILTIN_TOOLS if t["name"] in names]


# `compact` est un outil méta : présent dans TOOLS (le modèle peut le
# demander) mais absent de BUILTIN_HANDLERS — agent_loop l'intercepte car il
# doit réécrire messages, ce qu'un handler ordinaire ne peut pas faire.
TOOL_NAMES = ("bash", "read_file", "glob", "compact")
TOOLS = pick(*TOOL_NAMES)
HANDLERS = {n: BUILTIN_HANDLERS[n] for n in TOOL_NAMES
            if n in BUILTIN_HANDLERS}

# Seuils abaissés pour rendre la compaction observable en démo. Accès
# qualifié obligatoire : l'affectation doit toucher les globales du module
# shared (lues par prepare_context, micro_compact, persist_large_output).
shared.CONTEXT_LIMIT = 6000
shared.KEEP_RECENT_TOOL_RESULTS = 1
shared.PERSIST_THRESHOLD = 1000

SYSTEM = (
    f"You are a coding agent at {WORKDIR}. "
    "Explore files when asked. You may call the compact tool if the "
    "conversation grows too long."
)


def fake_history(pairs=12):
    """Historique synthétique : `pairs` paires tool_use/tool_result en dicts
    (le format harness), la dernière sortie étant volontairement géante."""
    msgs = [{"role": "user", "content": "Analyse le depot et resume-le."}]
    for i in range(pairs):
        out = "sortie " + ("x" * (5000 if i == pairs - 1 else 150))
        msgs.append({"role": "assistant", "content": [
            {"type": "tool_use", "id": f"tu_{i:03d}", "name": "bash",
             "input": {"command": f"cat fichier_{i}.txt"}}]})
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"tu_{i:03d}",
             "content": out}]})
    return msgs


def demo_a_sec():
    """Rejoue les couches structurelles (0 appel API) en montrant la taille
    estimée après chacune. compact_history/reactive_compact, qui appellent le
    modèle, se testent dans la boucle interactive (:compact / :reactive)."""
    msgs = fake_history()
    print(f"historique synthétique : {len(msgs)} messages, "
          f"{estimate_size(msgs)} caractères JSON")
    msgs = tool_result_budget(msgs, max_bytes=3000)
    print(f"1. tool_result_budget   : {estimate_size(msgs)} caractères "
          f"(la sortie géante est persistée sous {TOOL_RESULTS_DIR})")
    msgs = snip_compact(msgs, max_messages=8)
    print(f"2. snip_compact(max=8)  : {len(msgs)} messages, "
          f"{estimate_size(msgs)} caractères")
    print(f"   placeholder inséré   : {msgs[3]['content']!r}")
    msgs = micro_compact(msgs)
    print(f"3. micro_compact        : {estimate_size(msgs)} caractères "
          f"(garde les {shared.KEEP_RECENT_TOOL_RESULTS} derniers tool_result)")


def main():
    print("s08 · Compaction — seuils abaissés : CONTEXT_LIMIT="
          f"{shared.CONTEXT_LIMIT}, KEEP_RECENT={shared.KEEP_RECENT_TOOL_RESULTS}, "
          f"PERSIST={shared.PERSIST_THRESHOLD}")
    print("':sec' = démo sans API, ':taille' = taille de l'historique,")
    print("':compact' = compact_history, ':reactive' = reactive_compact,")
    print("texte libre = agent (compaction auto avant chaque appel), 'q' = quitter.\n")
    history = []
    while True:
        try:
            user = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user or user.lower() in ("q", "quit", "exit"):
            break
        if user == ":sec":
            demo_a_sec()
            continue
        if user == ":taille":
            print(f"{len(history)} messages, {estimate_size(history)} "
                  f"caractères (seuil compact : {shared.CONTEXT_LIMIT})")
            continue
        if user == ":compact":
            # Couche 4 : transcript JSONL puis résumé LLM — tout l'historique
            # devient UN message [Compacted]. (1 appel API)
            history[:] = compact_history(history)
            print(f"historique compacté → {len(history)} message(s)")
            continue
        if user == ":reactive":
            # Urgence post « prompt too long » : résumé + ~5 derniers messages
            # bruts ; si même le résumé échoue, texte de repli sans API.
            history[:] = reactive_compact(history)
            print(f"compaction réactive → {len(history)} message(s)")
            continue
        turn_start = len(history)
        agent_loop(user, history,
                   tools=TOOLS, handlers=HANDLERS, system=SYSTEM)
        print_turn_assistants(history, turn_start)


if __name__ == "__main__":
    main()
