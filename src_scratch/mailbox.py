"""Messagerie unifiée des agents (s09 + s22) : JSONL, file mémoire, Redis pub/sub.

Tous les backends honorent la même interface `Mailbox` ; les messages portent
l'enveloppe {"from","body","ts","req_id"} (req_id = corrélation requête/réponse).
"""

import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Protocol

from core import STATE_DIR, paint


def _envelope(frm: str, body: str, req_id: str | None) -> dict:
    # FIX(mekicode): champ req_id ajouté (s09 attribuait les réponses tardives au mauvais appel)
    return {"from": frm, "body": body, "ts": time.time(), "req_id": req_id}


class Mailbox(Protocol):
    """Interface commune : envoyer à un agent, relever sa boîte (pop-all)."""

    def send(self, to: str, frm: str, body: str, req_id: str | None = None) -> None: ...
    def receive(self, agent: str, timeout: float = 0) -> list[dict]: ...


class JsonlMailbox:
    """Boîtes JSONL sur disque (s09), visibles dans STATE_DIR/mailboxes/."""

    def __init__(self, root: Path | None = None):
        self.root = root or STATE_DIR / "mailboxes"
        self.root.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._meta = threading.Lock()

    def _lock(self, agent: str) -> threading.Lock:
        with self._meta:
            return self._locks.setdefault(agent, threading.Lock())

    def _path(self, agent: str) -> Path:
        return self.root / f"{agent}.jsonl"

    def send(self, to: str, frm: str, body: str, req_id: str | None = None) -> None:
        # FIX(mekicode): l'écriture prend le verrou du DESTINATAIRE (s09/s10 écrivaient sans
        # verrou → message appendu entre lecture et troncature silencieusement détruit)
        with self._lock(to), open(self._path(to), "a", encoding="utf-8") as f:
            f.write(json.dumps(_envelope(frm, body, req_id)) + "\n")

    def receive(self, agent: str, timeout: float = 0) -> list[dict]:
        deadline = time.monotonic() + timeout
        while True:
            msgs = self._pop_all(agent)
            if msgs or time.monotonic() >= deadline:
                return msgs
            time.sleep(0.1)

    def _pop_all(self, agent: str) -> list[dict]:
        # FIX(mekicode): lecture + troncature sous le même verrou (pop-all atomique) ;
        # la troncature précède le parsing, donc une ligne corrompue ne reste pas
        # dans le fichier à empoisonner la boucle (s09 crashait en boucle dessus)
        path = self._path(agent)
        with self._lock(agent):
            if not path.exists():
                return []
            lines = path.read_text(encoding="utf-8").splitlines()
            path.write_text("", encoding="utf-8")
        msgs = []
        for line in lines:
            if not line.strip():
                continue
            try:
                msgs.append(json.loads(line))
            except json.JSONDecodeError:
                print(paint(f"[mailbox] ligne corrompue ignorée ({agent}): {line[:60]}", "yellow"))
        return msgs


class QueueMailbox:
    """Files mémoire (repli de développement, intra-processus). Tamponne sans abonné."""

    def __init__(self):
        self._queues: dict[str, queue.Queue] = {}
        self._meta = threading.Lock()

    def _q(self, agent: str) -> queue.Queue:
        with self._meta:
            return self._queues.setdefault(agent, queue.Queue())

    def send(self, to: str, frm: str, body: str, req_id: str | None = None) -> None:
        self._q(to).put(_envelope(frm, body, req_id))

    def receive(self, agent: str, timeout: float = 0) -> list[dict]:
        q, msgs = self._q(agent), []
        try:
            if timeout > 0:
                msgs.append(q.get(timeout=timeout))  # attend le 1er message
            while True:
                msgs.append(q.get_nowait())          # puis draine le reste
        except queue.Empty:
            pass
        return msgs


class RedisMailbox:
    """Pub/sub Redis (s22), canaux mailbox:<agent>. Import du paquet redis paresseux."""

    def __init__(self, url: str | None = None):
        import redis  # paresseux : le paquet n'est requis que pour ce backend

        self._redis = redis.Redis.from_url(
            url or os.getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
        self._pubsubs: dict = {}
        self._meta = threading.Lock()

    def ping(self) -> None:
        """Teste la connexion (sémantique s22 : utilisé par get_mailbox('auto'))."""
        self._redis.ping()

    def _channel(self, agent: str) -> str:
        return f"mailbox:{agent}"

    def _ps(self, agent: str):
        with self._meta:  # abonnement paresseux, un pubsub par agent
            if agent not in self._pubsubs:
                ps = self._redis.pubsub(ignore_subscribe_messages=True)
                ps.subscribe(self._channel(agent))
                self._pubsubs[agent] = ps
            return self._pubsubs[agent]

    def send(self, to: str, frm: str, body: str, req_id: str | None = None) -> None:
        self._redis.publish(self._channel(to), json.dumps(_envelope(frm, body, req_id)))

    def receive(self, agent: str, timeout: float = 0) -> list[dict]:
        ps, msgs = self._ps(agent), []
        deadline = time.monotonic() + timeout
        while True:
            raw = ps.get_message(timeout=0.1)
            if raw and raw.get("type") == "message":
                try:
                    msgs.append(json.loads(raw["data"]))
                except json.JSONDecodeError:
                    print(paint(f"[mailbox] message corrompu ignoré ({agent})", "yellow"))
                continue  # draine tout ce qui est arrivé
            if msgs or time.monotonic() >= deadline:
                return msgs


def get_mailbox(backend: str = "auto") -> Mailbox:
    """Fabrique. "auto" : Redis si paquet présent ET serveur joignable (ping), sinon Queue."""
    if backend == "jsonl":
        return JsonlMailbox()
    if backend == "queue":
        return QueueMailbox()
    if backend == "redis":
        mb = RedisMailbox()
        mb.ping()  # échec explicite si injoignable (choix assumé par l'appelant)
        return mb
    if backend != "auto":
        raise ValueError(f"backend inconnu: {backend!r}")
    try:
        mb = RedisMailbox()
        mb.ping()
        print(paint("[mailbox] Redis connecté", "dim"))
        return mb
    except Exception as e:  # paquet absent OU serveur injoignable → dégradation gracieuse (s22)
        print(paint(f"[mailbox] Redis indisponible ({e}) — repli QueueMailbox", "yellow"))
        return QueueMailbox()
