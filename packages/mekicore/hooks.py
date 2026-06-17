"""hooks.py — bus de hooks synchrone de mekicore.

Deux familles d'événements autour de l'exécution d'un outil :
  - `pre_tool`  : VETOABLE. Chaque abonné reçoit {tool, input} et renvoie soit None
                  (laisse passer), soit une chaîne « raison de refus » (bloque). Le
                  premier refus court-circuite (les abonnés suivants ne sont pas appelés).
  - `post_tool` : notification seule. {tool, input, output}. Renvoi ignoré.

Les permissions (s15) sont un abonné `pre_tool`. Le rendu (tool-cards, impulsions
canvas) n'utilise PAS ce bus : il dérive du flux d'événements mekihub.
"""
from __future__ import annotations

from typing import Any, Callable

PreToolFn = Callable[[dict], "str | None"]
PostToolFn = Callable[[dict], Any]


class HookBus:
    def __init__(self) -> None:
        self._subs: dict[str, list] = {"pre_tool": [], "post_tool": []}

    def on(self, event: str, fn: Callable) -> None:
        """Abonne `fn` à `event` ('pre_tool' | 'post_tool')."""
        self._subs.setdefault(event, []).append(fn)

    def emit_pre_tool(self, tool: str, tool_input: dict) -> "str | None":
        """Renvoie la raison de refus du premier abonné qui refuse, sinon None."""
        payload = {"tool": tool, "input": tool_input}
        for fn in self._subs.get("pre_tool", []):
            try:
                reason = fn(payload)
            except Exception:
                reason = None
            if reason:
                return str(reason)
        return None

    def emit_post_tool(self, tool: str, tool_input: dict, output: str) -> None:
        payload = {"tool": tool, "input": tool_input, "output": output}
        for fn in self._subs.get("post_tool", []):
            try:
                fn(payload)
            except Exception:
                pass
