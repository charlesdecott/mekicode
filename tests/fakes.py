"""fakes.py — doublures et utilitaires de test réseau-free pour mekihub (pas de SDK, pas de clé)."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field


def init_git_repo(repo, commit=False) -> None:
    """Initialise un dépôt git de test dans `repo` (+ commit vide optionnel, identité déterministe)."""
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    if commit:
        subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", "i"], cwd=repo,
                       env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}, check=True)


async def drain_until(sub, names=None, *, stop="Idle") -> None:
    """Consomme l'async-iterator `sub` jusqu'à un événement de type `stop` (inclus).
    Si `names` (list) est fourni, y empile le nom de type de chaque événement reçu."""
    async for e in sub:
        if names is not None:
            names.append(type(e).__name__)
        if type(e).__name__ == stop:
            break


@dataclass
class _Resp:
    text: str
    tool_calls: list = field(default_factory=list)
    finish_reason: str = "stop"
    message: dict = field(default_factory=dict)


@dataclass
class _ToolCall:
    id: str
    name: str
    arguments: dict


class FakeLLM:
    """Renvoie une réponse texte fixe sans outil. `delay` : pause synchrone pour simuler un run lent."""

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


class FakeToolLLM:
    """1er tour : appelle un outil ; tours suivants : répond `final` (texte). Pour tester les outils."""
    def __init__(self, tool_name, tool_args, final="ok", model="fake/model"):
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.final = final
        self.model = model
        self._calls = 0

    def _step(self):
        import json as _json
        self._calls += 1
        if self._calls == 1:
            tc = _ToolCall(id="tc1", name=self.tool_name, arguments=dict(self.tool_args))
            msg = {"role": "assistant", "content": None,
                   "tool_calls": [{"id": "tc1", "type": "function",
                                   "function": {"name": self.tool_name,
                                                "arguments": _json.dumps(self.tool_args)}}]}
            return _Resp(text="", tool_calls=[tc], finish_reason="tool_calls", message=msg)
        return _Resp(text=self.final, tool_calls=[], finish_reason="stop",
                     message={"role": "assistant", "content": self.final})

    def complete(self, messages, tools=None):
        return self._step()

    def stream(self, messages, tools=None):
        resp = self._step()
        for w in (resp.text or "").split():
            yield w + " "
        return resp
