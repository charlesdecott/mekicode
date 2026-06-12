"""events.py — événements émis par run_agent (mekicore), consommés par un front ou le REPL.

Non-streaming (phase 2) : un tour assistant = un AssistantDone ; chaque appel d'outil =
ToolStarted puis ToolFinished ; fin de boucle = RunFinished ; erreur LLM = RunError.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AssistantDone:
    """Texte complet d'un tour assistant."""
    text: str


@dataclass
class ToolStarted:
    id: str
    name: str
    args: dict


@dataclass
class ToolFinished:
    id: str
    name: str
    output: str


@dataclass
class RunFinished:
    pass


@dataclass
class RunError:
    message: str
