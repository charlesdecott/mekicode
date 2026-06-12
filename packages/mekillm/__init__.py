"""mekillm — provider LLM généraliste, importable n'importe où.

Backend par défaut : OpenRouter via le SDK openai (compatible ollama / litellm).
Observabilité intégrée : logging + JSONL + hooks (cf. mekillm.observe).
"""
from . import observability as observe
from .client import LLM, LLMResponse, ToolCall, Usage

__all__ = ["LLM", "LLMResponse", "ToolCall", "Usage", "observe", "complete"]

_default = None


def complete(messages, **kwargs):
    """Raccourci : appel via un singleton LLM paresseux (config .env)."""
    global _default
    if _default is None:
        _default = LLM()
    return _default.complete(messages, **kwargs)
