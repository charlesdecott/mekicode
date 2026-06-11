"""s11 — Récupération d'erreurs : l'appel LLM blindé.

Démo du sous-système de récupération de shared.py, porté de
inspiration/learn-claude-code/s11_error_recovery/code.py :

- RecoveryState            : drapeaux du tour (escalade, 529, compaction) ;
- retry_delay              : backoff exponentiel plafonné 32 s + jitter 0-25 % ;
- with_retry               : 429/529 -> backoff, bascule FALLBACK_MODEL ;
- is_prompt_too_long_error : détecte le dépassement de contexte ;
- reactive_compact         : compaction d'urgence après « prompt too long ».

L'original recopiait 366 lignes (outils, prompt, REPL) ; ici tout vient de
shared.py et le fichier ne garde que le câblage : une mini-boucle à 3 outils
où l'appel LLM nu passe par les trois chemins de récupération de s11.
Commandes hors-ligne : `backoff` (table des délais) et `detect`
(classification d'erreurs). Lancement : python src/s11.py
"""

from shared import (
    BASE_DELAY_MS, BUILTIN_HANDLERS, BUILTIN_TOOLS, DEFAULT_MAX_TOKENS,
    ESCALATED_MAX_TOKENS, MAX_RETRIES, PROMPT, RecoveryState, WORKDIR,
    call_tool_handler, client, has_tool_use, is_prompt_too_long_error,
    print_turn_assistants, reactive_compact, retry_delay, with_retry,
)


def pick(*names):
    return [t for t in BUILTIN_TOOLS if t["name"] in names]


TOOL_NAMES = ("bash", "read_file", "write_file")
TOOLS = pick(*TOOL_NAMES)
HANDLERS = {n: BUILTIN_HANDLERS[n] for n in TOOL_NAMES}
SYSTEM = ("You are a resilient coding agent. "
          f"Workspace: {WORKDIR}. Tools: bash, read_file, write_file.")


def show_backoff():
    """Hors-ligne : la courbe de retry_delay, trois tirages par tentative
    (le jitter rend chaque tirage différent — anti thundering herd)."""
    print(f"  base {BASE_DELAY_MS} ms, plafond 32 s, jitter 0-25 %")
    for attempt in range(MAX_RETRIES):
        delays = ", ".join(f"{retry_delay(attempt):.2f}s"
                           for _ in range(3))
        print(f"  tentative {attempt}: {delays}")


def show_detector():
    """Hors-ligne : is_prompt_too_long_error ne matche que les erreurs de
    contexte — les transitoires (429/529) restent l'affaire de with_retry."""
    samples = [
        Exception("prompt is too long: 215000 tokens > 200000"),
        Exception("context_length_exceeded"),
        Exception("Error code: 429 - rate limited"),
        Exception("overloaded_error (529)"),
    ]
    for e in samples:
        verdict = ("PROMPT-TOO-LONG" if is_prompt_too_long_error(e)
                   else "autre erreur   ")
        print(f"  {verdict} <- {e}")


def resilient_turn(history: list):
    """Un tour d'agent où l'appel LLM est blindé par les trois chemins s11 :
    transitoires via with_retry, contexte via reactive_compact (une seule
    fois), sortie tronquée via l'escalade de max_tokens."""
    state = RecoveryState()
    max_tokens = DEFAULT_MAX_TOKENS
    while True:
        try:
            # Le lambda relit state.current_model à chaque tentative : la
            # bascule FALLBACK_MODEL de with_retry prend effet immédiatement.
            response = with_retry(
                lambda mt=max_tokens: client.messages.create(
                    model=state.current_model, system=SYSTEM,
                    messages=history, tools=TOOLS, max_tokens=mt),
                state)
        except Exception as e:
            if (is_prompt_too_long_error(e)
                    and not state.has_attempted_reactive_compact):
                history[:] = reactive_compact(history)
                state.has_attempted_reactive_compact = True
                continue
            history.append({"role": "assistant", "content": [
                {"type": "text", "text": f"[Error] {type(e).__name__}: {e}"}]})
            return
        if response.stop_reason == "max_tokens" and not state.has_escalated:
            # La sortie tronquée est jetée : même requête, budget x2.
            max_tokens = ESCALATED_MAX_TOKENS
            state.has_escalated = True
            print(f"  [max_tokens] nouvel essai avec {max_tokens} tokens")
            continue
        history.append({"role": "assistant", "content": response.content})
        if not has_tool_use(response.content):
            return
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"> {block.name}")
            output = call_tool_handler(
                HANDLERS.get(block.name), block.input, block.name)
            results.append({"type": "tool_result",
                            "tool_use_id": block.id, "content": output})
        history.append({"role": "user", "content": results})


def main():
    print("s11 — récupération d'erreurs. "
          "`backoff`, `detect`, ou un prompt LLM. `q` pour quitter.")
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
        if user == "backoff":
            show_backoff()
            continue
        if user == "detect":
            show_detector()
            continue
        history.append({"role": "user", "content": user})
        turn_start = len(history)
        resilient_turn(history)
        print_turn_assistants(history, turn_start)


if __name__ == "__main__":
    main()
