"""config.py — résolution de la config mekillm : args explicites > .env > défauts."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv(override=True)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-4o-mini"


def resolve(api_key=None, base_url=None, model=None) -> dict:
    """Fusionne, par priorité décroissante : arguments explicites, env, défauts."""
    return {
        "api_key": api_key
        or os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("MEKILLM_API_KEY"),
        "base_url": base_url or os.environ.get("MEKILLM_BASE_URL") or DEFAULT_BASE_URL,
        "model": model or os.environ.get("MEKILLM_MODEL") or DEFAULT_MODEL,
    }
