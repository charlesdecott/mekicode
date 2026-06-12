"""events.py — événements émis par run_agent (mekicore), consommés par un front ou le REPL.

Non-streaming (phase 2) : un tour assistant = un AssistantDone ; chaque appel d'outil =
ToolStarted puis ToolFinished ; fin de boucle = RunFinished ; erreur LLM = RunError.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ThinkingStarted:
    """Un tour commence : appel LLM en cours (avant complete())."""
    pass


@dataclass
class AssistantDelta:
    """Fragment de texte assistant (streaming)."""
    text: str


@dataclass
class AssistantDone:
    """Texte complet d'un tour assistant."""
    text: str


@dataclass
class ToolStarted:
    """Un outil va être exécuté."""
    id: str
    name: str
    args: dict


@dataclass
class ToolFinished:
    """Un outil a renvoyé sa sortie."""
    id: str
    name: str
    output: str


@dataclass
class RunFinished:
    """La boucle est terminée (plus d'appel d'outil)."""
    pass


@dataclass
class RunError:
    """L'appel LLM a échoué ; la boucle s'arrête."""
    message: str
