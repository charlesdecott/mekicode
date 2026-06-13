"""fakes.py — doublures de test réseau-free pour mekihub (pas de SDK, pas de clé)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _Resp:
    text: str
    tool_calls: list = field(default_factory=list)
    finish_reason: str = "stop"
    message: dict = field(default_factory=dict)


class FakeLLM:
    """Renvoie une réponse texte fixe sans outil. `model` exposé comme la vraie LLM.

    `reply` : texte renvoyé. `delay` : secondes de pause (synchrone) pour simuler un run lent
    et tester l'empilement de la file.
    """

    def __init__(self, reply: str = "réponse de test", delay: float = 0.0, model: str = "fake/model"):
        self.reply = reply
        self.delay = delay
        self.model = model

    def complete(self, messages, tools=None):
        import time
        if self.delay:
            time.sleep(self.delay)
        msg = {"role": "assistant", "content": self.reply}
        return _Resp(text=self.reply, tool_calls=[], finish_reason="stop", message=msg)

    def stream(self, messages, tools=None):
        import time
        for word in self.reply.split():
            if self.delay:
                time.sleep(self.delay)
            yield word + " "
        msg = {"role": "assistant", "content": self.reply}
        return _Resp(text=self.reply, tool_calls=[], finish_reason="stop", message=msg)
