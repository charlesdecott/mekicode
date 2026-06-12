"""sessions.py — sessions persistées de mekichat (un fichier JSON par session).

Pur Python : aucune dépendance NiceGUI ni réseau → testable seul.
Données runtime à la RACINE du projet (.sessions/), jamais dans packages/.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# parents[2] = racine du projet (même convention que packages/mekillm pour .logs/). Surchargeable par MEKICHAT_SESSIONS_DIR.
_DEFAULT_DIR = Path(__file__).resolve().parents[2] / ".sessions"
_DEFAULT_TITLE = "(nouvelle session)"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Session:
    id: str
    title: str
    model: str
    created_at: str
    messages: list = field(default_factory=list)

    def add(self, role: str, content: str, **extra) -> dict:
        """Ajoute un message ; renseigne le titre au 1er message utilisateur."""
        msg = {"role": role, "content": content, **extra}
        self.messages.append(msg)
        if role == "user" and self.title == _DEFAULT_TITLE:
            first_line = (content.strip().splitlines() or [""])[0]
            self.title = first_line[:48] or _DEFAULT_TITLE
        return msg


@dataclass
class SessionMeta:
    """Vue légère pour la barre latérale (sans charger tout l'historique)."""
    id: str
    title: str
    model: str
    created_at: str
    n_messages: int


class SessionStore:
    """CRUD : un fichier <id>.json par session sous le dossier runtime."""

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

    def create(self, model: str, system: str | None = None) -> Session:
        s = Session(id=self._new_id(), title=_DEFAULT_TITLE, model=model, created_at=_now_iso())
        if system:
            s.messages.append({"role": "system", "content": system})
        self.save(s)
        return s

    def save(self, session: Session) -> None:
        self._path(session.id).write_text(
            json.dumps(asdict(session), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def load(self, session_id: str) -> Session:
        data = json.loads(self._path(session_id).read_text(encoding="utf-8"))
        return Session(**data)

    def delete(self, session_id: str) -> None:
        """Supprime le fichier de la session (sans erreur si déjà absent)."""
        self._path(session_id).unlink(missing_ok=True)

    def list(self) -> list[SessionMeta]:
        metas: list[SessionMeta] = []
        for p in self.dir.glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                metas.append(SessionMeta(
                    id=d["id"], title=d.get("title", _DEFAULT_TITLE), model=d.get("model", "?"),
                    created_at=d.get("created_at", ""), n_messages=len(d.get("messages", [])),
                ))
            except (json.JSONDecodeError, OSError, KeyError):
                continue   # fichier corrompu / structurellement incomplet : on l'ignore
        metas.sort(key=lambda m: m.created_at, reverse=True)
        return metas
