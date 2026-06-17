"""events.py — événements de session émis par SessionHub, consommés par les adaptateurs.

Sur-ensemble des events de mekicore (run d'agent) + events de salle (file, présence, snapshot).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Snapshot:
    """Premier event reçu par un abonné : état complet de la session."""
    state: object               # SessionState (évite l'import circulaire)


@dataclass
class PresenceChanged:
    present: list               # list[Author]


@dataclass
class QueueEnqueued:
    item_id: str
    author_name: str
    color: str
    text: str
    ts: str


@dataclass
class QueueItemDeleted:
    item_id: str


@dataclass
class RunStarted:
    item_id: str


@dataclass
class MessagePosted:
    index: int
    author_name: str
    color: str
    text: str
    source: str | None = None


@dataclass
class AgentDelta:
    text: str


@dataclass
class AgentDone:
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


@dataclass
class Idle:
    """Plus rien en cours ni en attente."""
    pass


@dataclass
class WorktreeProposed:
    proposal_id: str
    session_id: str
    name: str
    prompt: str
    base: str | None = None


@dataclass
class WorktreeRejected:
    proposal_id: str


@dataclass
class WorktreeCreated:
    proposal_id: str
    child_session_id: str
    channel_id: str | None = None


@dataclass
class AskRequested:
    """L'agent a appelé l'outil `ask_user` : question posée en plein tour, le run attend la réponse
    (`SessionHub.resolve_ask(request_id, answer)`)."""
    request_id: str
    item_id: str
    question: str
    options: list           # choix proposés (vide => réponse libre)
    actor_id: str | None


@dataclass
class PermissionRequested:
    """Un appel d'outil a déclenché le tier `ask` (s15). Le run est en pause jusqu'à
    `SessionHub.resolve_permission(request_id, choice, actor)`."""
    request_id: str
    item_id: str            # run/queue item concerné
    tool: str
    target: str             # 1re valeur d'input, tronquée
    reason: str
    options: list           # ["once", "session", "project", "deny", "blacklist"]
    actor_id: str | None    # auteur autorisé à trancher (None => admin requis)
