"""base.py — boucle perception-action (s01 adapté), branchée sur mekillm.

Travaille en format OpenAI : tool_calls normalisés en entrée, messages role:"tool"
en sortie. `run_agent` émet des événements (front/REPL agnostique) ; `agent_loop`
(REPL console) est réexprimé dessus.
"""
from __future__ import annotations

from datetime import datetime

from events import AssistantDone, RunError, RunFinished, ToolFinished, ToolStarted


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


def run_agent(messages, llm, tools, dispatch):
    """Boucle « penser-agir » émettant des événements (non-streaming).

    Mute `messages` en place (append du message assistant puis des messages role:'tool').
    Générateur : ToolStarted/ToolFinished par outil, AssistantDone par texte de tour,
    RunFinished à la fin, RunError si l'appel LLM lève.
    """
    while True:
        try:
            resp = llm.complete(messages, tools=tools)
        except Exception as e:
            yield RunError(str(e))
            return
        messages.append(resp.message)
        if resp.text:
            yield AssistantDone(resp.text)
        if resp.finish_reason != "tool_calls":
            yield RunFinished()
            return
        for tc in resp.tool_calls:
            yield ToolStarted(tc.id, tc.name, tc.arguments)
            handler = dispatch.get(tc.name)
            try:
                output = handler(tc.arguments) if handler else f"Error: Unknown tool '{tc.name}'"
            except Exception as e:
                output = f"Error during tool execution: {e}"
            output = str(output)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": output})
            yield ToolFinished(tc.id, tc.name, output)


def agent_loop(messages, llm, tools, dispatch) -> None:
    """REPL console : consomme run_agent et rend les événements en print (compat s01)."""
    model = getattr(llm, "model", "?")
    for ev in run_agent(messages, llm, tools, dispatch):
        if isinstance(ev, AssistantDone):
            print(f"\033[90m[{datetime.now().strftime('%H:%M:%S')} · {model}]\033[0m {ev.text}")
        elif isinstance(ev, ToolStarted):
            first = str(next(iter(ev.args.values()), ""))[:80] if ev.args else ""
            print(f"\033[33m[{ev.name}] {first}...\033[0m")
        elif isinstance(ev, ToolFinished):
            print(str(ev.output)[:300])
        elif isinstance(ev, RunError):
            print(f"\033[31m[error] {ev.message}\033[0m")
