"""Persistance des conversations (s17) — save / resume / fork sous STATE_DIR/sessions.

Les blocs SDK (pydantic) sont aplatis via model_dump() à la sauvegarde ; au
rechargement ils restent des dicts purs, que l'API accepte tels quels. Un
fichier JSON lisible par session : meta {id, title, created, updated, turns}
+ messages.
"""
import json
import uuid
from datetime import datetime
from pathlib import Path

from core import STATE_DIR, paint, write_json

SESSIONS_DIR: Path = STATE_DIR / "sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

_META_KEYS = ("id", "title", "created", "updated", "turns")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _new_id() -> str:
    """Id court lisible : date + suffixe aléatoire (ex. 260611-a3f8)."""
    return f"{datetime.now():%y%m%d}-{uuid.uuid4().hex[:4]}"


def _path(sid: str) -> Path:
    return SESSIONS_DIR / f"{sid}.json"


def _read(sid: str) -> dict:
    p = _path(sid)
    if not p.exists():
        raise FileNotFoundError(f"session {sid} introuvable")
    return json.loads(p.read_text(encoding="utf-8"))


def _write(data: dict) -> None:
    data["updated"] = _now()
    write_json(_path(data["id"]), data)


def _serialize(messages: list[dict]) -> list[dict]:
    """Aplatit les blocs SDK en dicts JSON-sérialisables (idempotent sur des dicts)."""
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            c = [b.model_dump() if hasattr(b, "model_dump") else getattr(b, "__dict__", b)
                 for b in c]
        out.append({"role": m["role"], "content": c})
    return out


def save_session(messages: list[dict], sid: str | None = None, title: str | None = None) -> str:
    """Sauvegarde l'historique ; crée la session si sid est absent. Retourne l'id."""
    data: dict = {}
    if sid and _path(sid).exists():
        try:
            data = _read(sid)  # préserve created/title existants
        except (json.JSONDecodeError, OSError):
            print(paint(f"  [sessions] {sid}.json corrompu, réécrit proprement", "yellow"))
    sid = sid or _new_id()
    data["id"] = sid
    data.setdefault("created", _now())
    if title:
        data["title"] = title
    if not data.get("title"):  # auto-titrage : 1er message user texte (comme s17)
        first = next((m["content"] for m in messages
                      if m.get("role") == "user" and isinstance(m.get("content"), str)), "")
        data["title"] = first[:50] or "Session"
    data["turns"] = len(messages)
    data["messages"] = _serialize(messages)
    _write(data)
    return sid


def load_session(sid: str) -> tuple[list[dict], dict]:
    """Retourne (messages — dicts purs acceptés par l'API, meta)."""
    data = _read(sid)
    return data.get("messages", []), {k: data.get(k) for k in _META_KEYS}


def list_sessions() -> str:
    """Tableau lisible des sessions, les plus récemment mises à jour en tête."""
    rows = []
    for p in SESSIONS_DIR.glob("*.json"):
        try:
            rows.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:  # un fichier cassé ne casse pas le listing
            print(paint(f"  [sessions] fichier illisible ignoré : {p.name}", "yellow"))
    if not rows:
        return "(aucune session)"
    rows.sort(key=lambda d: d.get("updated", ""), reverse=True)
    lines = [f"{'ID':<13} {'MAJ':<17} {'TOURS':>5}  TITRE"]
    for d in rows:
        sid_col = paint(f"{str(d.get('id', '?')):<13}", "cyan")
        lines.append(f"{sid_col} {str(d.get('updated', ''))[:16]:<17} "
                     f"{d.get('turns', 0):>5}  {str(d.get('title', ''))[:40]}")
    return "\n".join(lines)


def fork_session(sid: str) -> str:
    """Copie la session sous un nouvel id ; les deux historiques divergent librement."""
    data = _read(sid)
    data["id"] = _new_id()
    data["title"] = f"Fork de {str(data.get('title', ''))[:30]}"
    data["created"] = _now()
    _write(data)
    return data["id"]


def set_title(sid: str, title: str) -> None:
    """Renomme la session (et rafraîchit updated)."""
    data = _read(sid)
    data["title"] = title
    _write(data)
