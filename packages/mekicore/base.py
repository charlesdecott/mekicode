"""base.py — boucle perception-action (s01 adapté), branchée sur mekillm.

Travaille directement en format OpenAI : tool_calls normalisés en entrée,
messages role:"tool" en sortie.
"""
from __future__ import annotations

from datetime import datetime


def dispatch_tools(tool_calls, dispatch) -> list:
    """Exécute chaque ToolCall et renvoie les messages role:'tool' correspondants."""
    results = []
    for tc in tool_calls:
        handler = dispatch.get(tc.name)
        first = str(next(iter(tc.arguments.values()), ""))[:80] if tc.arguments else ""
        print(f"\033[33m[{tc.name}] {first}...\033[0m")
        if handler:
            try:
                output = handler(tc.arguments)
            except Exception as e:
                output = f"Error during tool execution: {e}"
        else:
            output = f"Error: Unknown tool '{tc.name}'"
        print(str(output)[:300])
        results.append({"role": "tool", "tool_call_id": tc.id, "content": str(output)})
    return results


def agent_loop(messages, llm, tools, dispatch) -> None:
    """Boucle « penser-agir » : complete → tools → complete … jusqu'à finish != tool_calls.

    Modifie `messages` en place.
    """
    while True:
        print("\n\033[36m> Thinking...\033[0m")
        resp = llm.complete(messages, tools=tools)
        messages.append(resp.message)
        if resp.text:
            # En-tête : heure de réception + modèle qui a répondu (celui renvoyé par
            # le provider si dispo, sinon celui configuré sur le client).
            model = getattr(resp.raw, "model", None) or getattr(llm, "model", "?")
            print(f"\033[90m[{datetime.now().strftime('%H:%M:%S')} · {model}]\033[0m {resp.text}")
        if resp.finish_reason != "tool_calls":
            return
        messages += dispatch_tools(resp.tool_calls, dispatch)
