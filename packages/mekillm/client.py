"""client.py — provider LLM généraliste : wrapper du SDK openai + normalisation.

Backend par défaut OpenRouter ; compatible ollama / litellm-proxy (tous parlent
l'API OpenAI). complete() renvoie un LLMResponse normalisé et émet un CallRecord.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from . import config
from .observability import CallRecord, emit, log, now_iso


@dataclass
class ToolCall:
    """Appel d'outil normalisé : arguments déjà parsés en dict."""

    id: str
    name: str
    arguments: dict


@dataclass
class Usage:
    """Comptage de tokens (0 si le backend ne le renvoie pas)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """Réponse normalisée, agnostique du provider."""

    text: str
    tool_calls: list            # list[ToolCall]
    finish_reason: str
    usage: Usage
    message: dict               # message assistant prêt à append à l'historique
    raw: Any = None


def _message_dict(msg) -> dict:
    """Convertit le message assistant du SDK en dict simple (sérialisable)."""
    d = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
    return d


def _normalize(resp) -> LLMResponse:
    """Transforme une réponse SDK openai en LLMResponse normalisé."""
    choice = resp.choices[0]
    msg = choice.message
    tool_calls = []
    for tc in (msg.tool_calls or []):
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            log.warning("arguments JSON invalides pour l'outil %s", tc.function.name)
            args = {}
        tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
    u = resp.usage
    usage = (
        Usage(
            prompt_tokens=getattr(u, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(u, "completion_tokens", 0) or 0,
            total_tokens=getattr(u, "total_tokens", 0) or 0,
        )
        if u
        else Usage()
    )
    return LLMResponse(
        text=msg.content or "",
        tool_calls=tool_calls,
        finish_reason=choice.finish_reason or "",
        usage=usage,
        message=_message_dict(msg),
        raw=resp,
    )


class LLM:
    """Provider LLM réutilisable. Lit la config depuis .env, surchargeable par args."""

    def __init__(self, model=None, api_key=None, base_url=None):
        cfg = config.resolve(api_key, base_url, model)
        self.model = cfg["model"]
        self.base_url = cfg["base_url"]
        self._client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])

    def complete(self, messages, tools=None, system=None, max_tokens=8000, **kwargs) -> LLMResponse:
        """Un tour de complétion. Émet un CallRecord (succès comme erreur)."""
        sent = list(messages)
        if system:
            sent = [{"role": "system", "content": system}] + sent
        params = dict(model=self.model, messages=sent, max_tokens=max_tokens, **kwargs)
        if tools:
            params["tools"] = tools

        start = time.perf_counter()
        rec = {"status": "ok", "error": None, "finish_reason": "", "usage": Usage()}
        try:
            resp = self._client.chat.completions.create(**params)
            out = _normalize(resp)
            rec["finish_reason"], rec["usage"] = out.finish_reason, out.usage
            return out
        except Exception as e:
            rec["status"], rec["error"] = "error", str(e)
            raise
        finally:
            emit(
                CallRecord(
                    ts=now_iso(),
                    provider="openai",
                    model=self.model,
                    latency_ms=int((time.perf_counter() - start) * 1000),
                    prompt_tokens=rec["usage"].prompt_tokens,
                    completion_tokens=rec["usage"].completion_tokens,
                    total_tokens=rec["usage"].total_tokens,
                    finish_reason=rec["finish_reason"],
                    status=rec["status"],
                    error=rec["error"],
                    n_messages=len(sent),
                    n_tools=len(tools or []),
                )
            )
