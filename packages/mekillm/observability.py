"""observability.py — monitor / profile / log de chaque appel LLM.

Trois canaux indépendants : logging standard (logger « mekillm »), JSONL
append-only, et hooks. Aucun basicConfig imposé : c'est au consommateur de
configurer le handler de logging.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("mekillm")

_DEFAULT_LOG = Path(__file__).parent / ".logs" / "calls.jsonl"
_HOOKS: list = []


@dataclass
class CallRecord:
    """Trace structurée d'un appel LLM (un par complete())."""

    ts: str
    provider: str
    model: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str
    status: str                 # "ok" | "error"
    error: str | None = None
    n_messages: int = 0
    n_tools: int = 0
    cost_usd: float | None = None


def now_iso() -> str:
    """Horodatage ISO 8601 en UTC."""
    return datetime.now(timezone.utc).isoformat()


def add_hook(fn) -> None:
    """Enregistre fn(record: CallRecord), appelé après chaque appel LLM."""
    _HOOKS.append(fn)


def _log_file() -> Path | None:
    """Chemin du JSONL : MEKILLM_LOG_FILE, défaut .logs/calls.jsonl, vide = désactivé."""
    raw = os.environ.get("MEKILLM_LOG_FILE", str(_DEFAULT_LOG))
    return Path(raw) if raw else None


def _append_jsonl(record: CallRecord) -> None:
    """Ajoute une ligne JSON au fichier de log (créé à la volée)."""
    path = _log_file()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")


def emit(record: CallRecord) -> None:
    """Diffuse `record` vers les trois canaux : logging, JSONL, hooks."""
    log.info(
        "%s · %dms · %d→%d tok · %s",
        record.model, record.latency_ms,
        record.prompt_tokens, record.completion_tokens, record.finish_reason,
    )
    _append_jsonl(record)
    for fn in _HOOKS:
        try:
            fn(record)
        except Exception as e:  # un hook fautif ne casse pas le flux
            log.warning("hook d'observabilité en erreur : %s", e)
