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


def _consume_stream(chunks):
    """Réassemble un flux de chunks SDK en LLMResponse. Générateur : yield chaque token de
    texte, **return** le LLMResponse final (texte + tool_calls reconstruits + finish_reason)."""
    text_parts: list[str] = []
    tool_acc: dict = {}  # index -> dict(id, name, args)
    finish_reason = ""
    usage = Usage()
    for chunk in chunks:
        u = getattr(chunk, "usage", None)
        if u:
            usage = Usage(
                prompt_tokens=getattr(u, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(u, "completion_tokens", 0) or 0,
                total_tokens=getattr(u, "total_tokens", 0) or 0,
            )
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        choice = choices[0]
        if getattr(choice, "finish_reason", None):
            finish_reason = choice.finish_reason
        delta = getattr(choice, "delta", None)
        if delta is None:                       # certains backends : chunk sans delta (finish-only)
            continue
        if getattr(delta, "content", None):
            text_parts.append(delta.content)
            yield delta.content
        for tc in (getattr(delta, "tool_calls", None) or []):
            idx = getattr(tc, "index", None)
            if idx is None:                      # backend qui omet l'index : tout dans le bucket 0
                idx = 0
            acc = tool_acc.setdefault(idx, {"id": "", "name": "", "args": ""})
            if getattr(tc, "id", None):
                acc["id"] = tc.id
            fn = getattr(tc, "function", None)
            if fn is not None:
                if getattr(fn, "name", None):
                    acc["name"] = fn.name
                if getattr(fn, "arguments", None):
                    acc["args"] += fn.arguments

    text = "".join(text_parts)
    tool_calls = []
    msg_tool_calls = []
    for idx in sorted(tool_acc):
        acc = tool_acc[idx]
        try:
            args = json.loads(acc["args"] or "{}")
        except json.JSONDecodeError:
            log.warning("arguments JSON invalides (stream) pour l'outil %s", acc["name"])
            args = {}
        tool_calls.append(ToolCall(id=acc["id"], name=acc["name"], arguments=args))
        msg_tool_calls.append({
            "id": acc["id"], "type": "function",
            "function": {"name": acc["name"], "arguments": acc["args"]},
        })
    message = {"role": "assistant", "content": text}
    if msg_tool_calls:
        message["tool_calls"] = msg_tool_calls
    return LLMResponse(
        text=text, tool_calls=tool_calls, finish_reason=finish_reason,
        usage=usage, message=message, raw=None,
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

    def stream(self, messages, tools=None, system=None, max_tokens=8000, **kwargs):
        """Comme complete(), mais en flux : générateur de tokens de texte ; return le
        LLMResponse final. Émet un CallRecord (usage à 0 en streaming). Réassemble les tool_calls."""
        sent = list(messages)
        if system:
            sent = [{"role": "system", "content": system}] + sent
        params = dict(model=self.model, messages=sent, max_tokens=max_tokens, stream=True, **kwargs)
        if tools:
            params["tools"] = tools

        start = time.perf_counter()
        rec = {"status": "ok", "error": None, "finish_reason": "", "usage": Usage()}
        try:
            chunks = self._client.chat.completions.create(**params)
            out = yield from _consume_stream(chunks)
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
