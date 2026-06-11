"""s10 — System prompt : assemblé depuis des sections, jamais codé en dur.

Original : inspiration/learn-claude-code/s10_system_prompt/code.py
(219 lignes). La thèse : le system prompt est une configuration assemblée à
l'exécution — sections toujours chargées (identity, tools, workspace) +
sections conditionnelles pilotées par l'ÉTAT RÉEL (la section mémoire
n'apparaît que si .memory/MEMORY.md existe et a du contenu), jamais par des
mots-clés devinés dans la conversation.

shared.py fournit PROMPT_SECTIONS (les fragments), assemble_system_prompt
(le system VIVANT de s20 : horloge + catalogue skills + mémoires + MCP,
reconstruit à chaque tour) et update_context (dérive le contexte de l'état
réel). Le délta de ce fichier : un assemblage de démo qui réécrit la section
tools pour le sous-ensemble réel (celle de shared liste les 27 outils), le
cache à un emplacement get_system_prompt() — pièce de l'original NON portée
dans shared.py, réimplémentée ici (clé json.dumps déterministe ; hash() est
randomisé par processus et échoue sur les structures imbriquées) — et le
passage de ce system FIGÉ à agent_loop (system=...), figé pour tout le tour.
"""

import json

from shared import (BUILTIN_HANDLERS, BUILTIN_TOOLS, PROMPT,
                    PROMPT_SECTIONS, agent_loop, assemble_system_prompt,
                    print_turn_assistants, update_context)


def pick(*names):
    """Sous-ensemble de BUILTIN_TOOLS par nom (schémas JSON complets)."""
    return [t for t in BUILTIN_TOOLS if t["name"] in names]


TOOL_NAMES = ("bash", "read_file", "write_file")
TOOLS = pick(*TOOL_NAMES)
HANDLERS = {n: BUILTIN_HANDLERS[n] for n in TOOL_NAMES}


def assemble_demo_prompt(context):
    """Version s10 de l'assemblage : 3 sections toujours chargées (ordre
    fixe = préfixe stable, condition du prompt caching API) + la section
    mémoire si et seulement si l'état réel la justifie."""
    sections = [
        PROMPT_SECTIONS["identity"],
        f"Available tools: {', '.join(TOOL_NAMES)}.",
        PROMPT_SECTIONS["workspace"],
    ]
    if context.get("memories"):
        sections.append(f"Relevant memories:\n{context['memories']}")
    return "\n\n".join(sections)


_last_key = None
_last_prompt = None


def get_system_prompt(context):
    """Cache à un emplacement (le délta s10 absent de shared.py) : même
    contexte → même chaîne, sans réassemblage. La clé est json.dumps trié."""
    global _last_key, _last_prompt
    key = json.dumps(context, sort_keys=True, ensure_ascii=False, default=str)
    if key == _last_key and _last_prompt:
        print("  \033[90m[cache hit] system prompt inchangé\033[0m")
        return _last_prompt
    _last_key = key
    _last_prompt = assemble_demo_prompt(context)
    loaded = ["identity", "tools", "workspace"]
    if context.get("memories"):
        loaded.append("memory")
    print(f"  \033[32m[assemblé] sections : {', '.join(loaded)}\033[0m")
    return _last_prompt


def main():
    print("s10 · System prompt — PROMPT_SECTIONS + assemblage + cache")
    print("':sections' = fragments de shared, ':vivant' = system s20 vivant,")
    print("':fige' = system de démo (avec cache), texte = agent, 'q' = quitter.\n")
    history = []
    while True:
        try:
            user = input(PROMPT).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user or user.lower() in ("q", "quit", "exit"):
            break
        if user == ":sections":
            for name, text in PROMPT_SECTIONS.items():
                print(f"- {name} ({len(text)} caractères) : {text[:60]}...")
            continue
        if user == ":vivant":
            # Le system s20 : reconstruit à CHAQUE appel (horloge, catalogue
            # skills, MCP connectés) — un cache serait invalidé à la seconde.
            print(assemble_system_prompt(update_context({}, history)))
            continue
        if user == ":fige":
            print(get_system_prompt(update_context({}, history)))
            continue
        # Contexte dérivé de l'état réel (MEMORY.md existe-t-il ?), system
        # figé pour tout le tour : agent_loop ne ré-assemble plus rien.
        # Relancer le même prompt sans changement d'état → [cache hit] ;
        # créer .memory/MEMORY.md entre deux tours → réassemblage + memory.
        context = update_context({}, history)
        system = get_system_prompt(context)
        turn_start = len(history)
        agent_loop(user, history,
                   tools=TOOLS, handlers=HANDLERS, system=system)
        print_turn_assistants(history, turn_start)


if __name__ == "__main__":
    main()
