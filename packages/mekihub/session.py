"""session.py — couche session canonique de mekihub (salle partagée, identité légère).

Superset de packages/mekichat/sessions.py : ajoute Author, QueueItem, SessionState et
l'attribution d'auteur (séparée des messages OpenAI). Pur Python, sans réseau ni NiceGUI.
Données runtime à la RACINE du projet (.sessions/), jamais dans packages/.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_DIR = Path(__file__).resolve().parents[2] / ".sessions"
_DEFAULT_TITLE = "(nouvelle session)"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Author:
    """Participant éphémère d'une salle (pas de compte). id = uuid de connexion."""
    id: str
    name: str
    color: str
    source: str | None = None


@dataclass
class QueueItem:
    item_id: str
    author: Author
    text: str
    ts: str


@dataclass
class Session:
    id: str
    title: str
    model: str
    created_at: str
    messages: list = field(default_factory=list)      # OpenAI pur (ce que voit l'agent)
    authors: dict = field(default_factory=dict)        # index_message(str) -> {"name","color"}
    project_id: str = "mekicode"
    scope: str = "main"
    discord_channel_id: str | None = None

    def _maybe_set_title(self, content: str) -> None:
        if self.title == _DEFAULT_TITLE:
            first_line = (content.strip().splitlines() or [""])[0]
            self.title = first_line[:48] or _DEFAULT_TITLE

    def add_user(self, content: str, *, author: Author) -> int:
        """Ajoute un message user (OpenAI pur) + son attribution. Renvoie l'index du message."""
        self.messages.append({"role": "user", "content": content})
        idx = len(self.messages) - 1
        self.authors[idx] = {"name": author.name, "color": author.color}
        self._maybe_set_title(content)
        return idx

    def add(self, role: str, content: str, **extra) -> dict:
        """Ajoute un message générique (compat historique mekichat). Renseigne le titre au 1er user."""
        msg = {"role": role, "content": content, **extra}
        self.messages.append(msg)
        if role == "user":
            self._maybe_set_title(content)
        return msg


@dataclass
class SessionMeta:
    id: str
    title: str
    model: str
    created_at: str
    n_messages: int
    project_id: str = "mekicode"
    scope: str = "main"


@dataclass
class SessionState:
    """Instantané partagé : ce que renvoie SessionHub.snapshot()."""
    id: str
    title: str
    messages: list
    authors: dict
    queue: list           # list[QueueItem] en attente
    running: QueueItem | None
    presence: list        # list[Author]


class SessionStore:
    """CRUD : un fichier <id>.json par session. authors persisté ; file/présence NON (éphémères)."""

    def __init__(self, directory: str | Path | None = None):
        raw = directory or os.environ.get("MEKICHAT_SESSIONS_DIR") or _DEFAULT_DIR
        self.dir = Path(raw)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.dir / f"{session_id}.json"

    def _new_id(self) -> str:
        while True:
            candidate = uuid.uuid4().hex[:6]
            if not self._path(candidate).exists():
                return candidate

    def create(self, model: str, system: str | None = None, *,
               project_id: str = "mekicode", scope: str = "main") -> Session:
        s = Session(id=self._new_id(), title=_DEFAULT_TITLE, model=model, created_at=now_iso(),
                    project_id=project_id, scope=scope)
        if system:
            s.messages.append({"role": "system", "content": system})
        self.save(s)
        return s

    def save(self, session: Session) -> None:
        # Les clés de authors sont des int en mémoire ; json.dumps les convertit en str automatiquement.
        data = {"id": session.id, "title": session.title, "model": session.model,
                "created_at": session.created_at, "messages": session.messages,
                "authors": {str(k): v for k, v in session.authors.items()},
                "project_id": session.project_id, "scope": session.scope,
                "discord_channel_id": session.discord_channel_id}
        self._path(session.id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, session_id: str) -> Session:
        d = json.loads(self._path(session_id).read_text(encoding="utf-8"))
        # Reconvertir les clés str -> int pour cohérence avec add_user (retourne int).
        raw_authors = d.get("authors", {})
        authors = {}
        for k, v in raw_authors.items():
            try:
                authors[int(k)] = v
            except (ValueError, TypeError):
                authors[k] = v
        return Session(id=d["id"], title=d["title"], model=d["model"], created_at=d["created_at"],
                       messages=d.get("messages", []), authors=authors,
                       project_id=d.get("project_id", "mekicode"),
                       scope=d.get("scope", "main"),
                       discord_channel_id=d.get("discord_channel_id"))

    def delete(self, session_id: str) -> None:
        self._path(session_id).unlink(missing_ok=True)

    def list(self, project_id: str | None = None, scope: str | None = None) -> list[SessionMeta]:
        metas: list[SessionMeta] = []
        for p in self.dir.glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                pid = d.get("project_id", "mekicode")
                sc = d.get("scope", "main")
                if project_id is not None and pid != project_id:
                    continue
                if scope is not None and sc != scope:
                    continue
                metas.append(SessionMeta(id=d["id"], title=d.get("title", _DEFAULT_TITLE),
                                         model=d.get("model", "?"), created_at=d.get("created_at", ""),
                                         n_messages=len(d.get("messages", [])),
                                         project_id=pid, scope=sc))
            except (json.JSONDecodeError, OSError, KeyError):
                continue
        metas.sort(key=lambda m: m.created_at, reverse=True)
        return metas
