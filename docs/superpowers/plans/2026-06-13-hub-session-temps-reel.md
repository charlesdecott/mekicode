# Hub de session temps réel — plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire `packages/mekihub/` — un hub de session temps réel (salle partagée, file FIFO auto-drain, pub/sub mémoire) — puis brancher dessus le front NiceGUI multi-utilisateur et un adaptateur Discord.

**Architecture:** Un `SessionHub` async in-process, sans dépendance NiceGUI/Discord, expose `join/leave/submit/delete_pending/snapshot/subscribe`. Un worker `asyncio` par session draine une file FIFO et pilote le générateur **sync** `mekicore.run_agent` via `asyncio.to_thread(next, gen)`, publiant chaque événement à tous les abonnés. Le front (NiceGUI) et Discord sont des adaptateurs : ingèrent l'entrée → `submit`, s'abonnent → rendent dans leur idiome.

**Tech Stack:** Python 3.11+ (asyncio, dataclasses, stdlib `unittest`), NiceGUI 3.x (front), discord.py (adaptateur), Playwright (validation multi-client). Tests réseau-free, sans clé API (FakeLLM/FakeDiscordClient), conventions projet (`tests/` à la racine, `ensure_ascii` pour Windows).

**Référence spec :** `docs/superpowers/specs/2026-06-13-hub-session-temps-reel-design.md`

**Contraintes dures :**
- **100 % additif** : aucun fichier déplacé ni supprimé. `mekichat/sessions.py` devient un **ré-export**.
- Rester dans `mekicode/`. Aucun commit avec le nom de Claude (règle projet).
- `python -m py_compile` sur tout `.py` modifié avant de conclure une tâche.
- Tenir la doc `docs/wiki-packages/` à jour (hors pipeline understand-anything).

---

## Carte des fichiers (verrouillage de la décomposition)

**Créés :**
- `packages/mekihub/__init__.py` — exports publics (`SessionHub`, `Author`, `Session`, `SessionStore`, events).
- `packages/mekihub/session.py` — `Author`, `Session`, `SessionMeta`, `SessionStore`, `QueueItem`, `SessionState`.
- `packages/mekihub/events.py` — dataclasses d'événements de session.
- `packages/mekihub/hub.py` — `SessionHub` + `PendingQueue` + worker FIFO.
- `packages/mekihub/adapters/__init__.py` — vide (paquet).
- `packages/mekihub/adapters/discord.py` — `DiscordAdapter` + `FakeDiscordClient` (testable).
- `packages/mekihub/main.py` — entrypoint hub + adaptateurs activés par `.env`.
- `packages/mekichat/realtime.py` — helpers NiceGUI multi-client (présence, file UI, abonnement).
- `Dockerfile`, `docker-compose.yml` — déploiement (artefacts).
- `tests/smoke_mekihub.py` — unitaires réseau-free du hub.
- `tests/fakes.py` — `FakeLLM`, helpers de test partagés.
- `.refactor-tmp/diag_realtime.py` — diag Playwright multi-client (gitignoré).

**Modifiés :**
- `packages/mekichat/sessions.py` — ré-export depuis `mekihub.session` (additif).
- `packages/mekichat/app.py` — page branchée sur `SessionHub` (multi-client) au lieu de piloter `run_agent` en direct.
- `packages/mekichat/views.py` — ajouts : rendu file d'attente, présence, message attribué.
- `packages/mekichat/static/mekichat.css` — styles file d'attente / présence.
- `requirements.txt` — ajout `discord.py`.
- `docs/wiki-packages/README.md`, `architecture.md`, nouveau `docs/wiki-packages/mekihub.md`, `ROADMAP.md`.

---

## Task 1 : squelette `mekihub` + couche session (`session.py`)

**Files:**
- Create: `packages/mekihub/__init__.py`, `packages/mekihub/session.py`
- Test: `tests/smoke_mekihub.py`

- [ ] **Step 1 : test qui échoue — Author, QueueItem, SessionState**

Créer `tests/smoke_mekihub.py` :

```python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages"))

from mekihub.session import Author, QueueItem, Session, SessionState, SessionStore  # noqa: E402


def test_author_and_queueitem():
    a = Author(id="c1", name="alice", color="#39ff14")
    assert a.name == "alice"
    qi = QueueItem(item_id="q1", author=a, text="salut", ts="2099-01-01T00:00:00+00:00")
    assert qi.author.name == "alice" and qi.text == "salut"


def test_session_authors_separate_from_messages():
    s = Session(id="s1", title="(nouvelle session)", model="m", created_at="2099-01-01T00:00:00+00:00")
    a = Author(id="c1", name="bob", color="#ff2bd6")
    idx = s.add_user("bonjour", author=a)
    assert s.messages[idx] == {"role": "user", "content": "bonjour"}   # OpenAI pur, pas d'auteur
    assert s.authors[idx] == {"name": "bob", "color": "#ff2bd6"}       # attribution séparée


if __name__ == "__main__":
    test_author_and_queueitem()
    test_session_authors_separate_from_messages()
    print("OK - session")
```

- [ ] **Step 2 : lancer pour vérifier l'échec**

Run: `python tests/smoke_mekihub.py`
Expected: `ModuleNotFoundError: No module named 'mekihub'`

- [ ] **Step 3 : implémenter `session.py`**

```python
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

    def add_user(self, content: str, *, author: Author) -> int:
        """Ajoute un message user (OpenAI pur) + son attribution. Renvoie l'index du message."""
        self.messages.append({"role": "user", "content": content})
        idx = len(self.messages) - 1
        self.authors[str(idx)] = {"name": author.name, "color": author.color}
        if self.title == _DEFAULT_TITLE:
            first_line = (content.strip().splitlines() or [""])[0]
            self.title = first_line[:48] or _DEFAULT_TITLE
        return idx


@dataclass
class SessionMeta:
    id: str
    title: str
    model: str
    created_at: str
    n_messages: int


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

    def create(self, model: str, system: str | None = None) -> Session:
        s = Session(id=self._new_id(), title=_DEFAULT_TITLE, model=model, created_at=now_iso())
        if system:
            s.messages.append({"role": "system", "content": system})
        self.save(s)
        return s

    def save(self, session: Session) -> None:
        data = {"id": session.id, "title": session.title, "model": session.model,
                "created_at": session.created_at, "messages": session.messages,
                "authors": session.authors}
        self._path(session.id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, session_id: str) -> Session:
        d = json.loads(self._path(session_id).read_text(encoding="utf-8"))
        return Session(id=d["id"], title=d["title"], model=d["model"], created_at=d["created_at"],
                       messages=d.get("messages", []), authors=d.get("authors", {}))

    def delete(self, session_id: str) -> None:
        self._path(session_id).unlink(missing_ok=True)

    def list(self) -> list[SessionMeta]:
        metas: list[SessionMeta] = []
        for p in self.dir.glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                metas.append(SessionMeta(id=d["id"], title=d.get("title", _DEFAULT_TITLE),
                                         model=d.get("model", "?"), created_at=d.get("created_at", ""),
                                         n_messages=len(d.get("messages", []))))
            except (json.JSONDecodeError, OSError, KeyError):
                continue
        metas.sort(key=lambda m: m.created_at, reverse=True)
        return metas
```

Puis `packages/mekihub/__init__.py` :

```python
"""mekihub — hub de session temps réel (salle partagée, file FIFO, pub/sub)."""
from session import Author, QueueItem, Session, SessionMeta, SessionState, SessionStore  # type: ignore  # noqa
```

> Note d'import : `mekihub` est importé en ajoutant `packages/` au `sys.path` (comme mekillm). À
> l'intérieur du paquet, les imports sont **relatifs au dossier** via `sys.path` ; pour fiabiliser,
> `__init__.py` ajoute son propre dossier au path. **Remplacer le contenu de `__init__.py` par :**

```python
"""mekihub — hub de session temps réel (salle partagée, file FIFO, pub/sub)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))           # mekihub/ (session, events, hub)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))    # packages/ (mekillm)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mekicore"))  # base, tools, events de mekicore

from session import Author, QueueItem, Session, SessionMeta, SessionState, SessionStore  # noqa: E402,F401
```

- [ ] **Step 4 : lancer le test, vérifier le succès**

Run: `python tests/smoke_mekihub.py`
Expected: `OK - session`

- [ ] **Step 5 : py_compile + commit**

```bash
python -m py_compile packages/mekihub/__init__.py packages/mekihub/session.py
git add packages/mekihub/__init__.py packages/mekihub/session.py tests/smoke_mekihub.py
git commit -m "mekihub: couche session (Author, attribution separee des messages, SessionStore)"
```

---

## Task 2 : vocabulaire d'événements (`events.py`)

**Files:**
- Create: `packages/mekihub/events.py`
- Test: `tests/smoke_mekihub.py` (ajout)

- [ ] **Step 1 : test qui échoue**

Ajouter dans `tests/smoke_mekihub.py` (avant le `if __name__`) :

```python
from mekihub import events as hub_events  # noqa: E402


def test_events_exist():
    snap = hub_events.Snapshot(state=None)
    delta = hub_events.AgentDelta(text="hi")
    enq = hub_events.QueueEnqueued(item_id="q1", author_name="alice", color="#fff", text="hey", ts="t")
    deleted = hub_events.QueueItemDeleted(item_id="q1")
    posted = hub_events.MessagePosted(index=2, author_name="alice", color="#fff", text="hey")
    assert delta.text == "hi" and enq.item_id == "q1" and deleted.item_id == "q1"
    assert posted.index == 2 and snap.state is None
```

et l'appeler dans `__main__` : `test_events_exist()`.

- [ ] **Step 2 : lancer, vérifier l'échec**

Run: `python tests/smoke_mekihub.py`
Expected: `ModuleNotFoundError: No module named 'mekihub.events'` (ou `events` introuvable)

- [ ] **Step 3 : implémenter `events.py`**

```python
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
```

- [ ] **Step 4 : lancer, vérifier le succès**

Run: `python tests/smoke_mekihub.py`
Expected: `OK - session` (et pas d'erreur sur `test_events_exist`)

- [ ] **Step 5 : py_compile + commit**

```bash
python -m py_compile packages/mekihub/events.py
git add packages/mekihub/events.py tests/smoke_mekihub.py
git commit -m "mekihub: vocabulaire d'evenements de session (snapshot, file, presence, run)"
```

---

## Task 3 : `PendingQueue` (file FIFO supprimable)

**Files:**
- Create: `packages/mekihub/hub.py` (partie 1 : `PendingQueue`)
- Test: `tests/smoke_mekihub.py` (ajout, async)

- [ ] **Step 1 : test qui échoue (async)**

Ajouter dans `tests/smoke_mekihub.py` :

```python
import asyncio  # en tête de fichier


def test_pending_queue_fifo_and_delete():
    from mekihub.hub import PendingQueue

    async def scenario():
        q = PendingQueue()
        a = Author(id="c1", name="alice", color="#fff")
        i1 = QueueItem("q1", a, "un", "t1")
        i2 = QueueItem("q2", a, "deux", "t2")
        q.enqueue(i1)
        q.enqueue(i2)
        assert [i.item_id for i in q.pending()] == ["q1", "q2"]
        assert q.delete("q1") is True               # suppression d'un item en attente
        assert [i.item_id for i in q.pending()] == ["q2"]
        first = await q.pop_next()                  # pop l'item courant
        assert first.item_id == "q2"
        assert q.delete("q2") is False              # plus en attente (déjà poppé) → refus
    asyncio.run(scenario())
```

et l'appeler dans `__main__`.

- [ ] **Step 2 : lancer, vérifier l'échec**

Run: `python tests/smoke_mekihub.py`
Expected: `ImportError: cannot import name 'PendingQueue'`

- [ ] **Step 3 : implémenter `PendingQueue` dans `hub.py`**

```python
"""hub.py — SessionHub : registre de sessions, état partagé, pub/sub mémoire, worker FIFO."""
from __future__ import annotations

import asyncio
import uuid

from session import Author, QueueItem, Session, SessionState, SessionStore, now_iso
import events as ev


class PendingQueue:
    """File FIFO d'items en attente, supprimable par item_id. pop_next() attend si vide.

    L'item « en cours » (déjà poppé) n'est PAS dans `pending()` → delete() le refuse.
    """

    def __init__(self):
        self._items: list[QueueItem] = []
        self._cond = asyncio.Condition()

    def enqueue(self, item: QueueItem) -> None:
        self._items.append(item)
        # réveil best-effort (sans await) : notifie les attentes de pop_next
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._notify())
        except RuntimeError:
            pass  # hors boucle (test synchrone d'enqueue) : pop_next re-vérifiera

    async def _notify(self) -> None:
        async with self._cond:
            self._cond.notify_all()

    def delete(self, item_id: str) -> bool:
        for i, it in enumerate(self._items):
            if it.item_id == item_id:
                del self._items[i]
                return True
        return False

    def pending(self) -> list[QueueItem]:
        return list(self._items)

    async def pop_next(self) -> QueueItem:
        async with self._cond:
            while not self._items:
                await self._cond.wait()
            return self._items.pop(0)
```

- [ ] **Step 4 : lancer, vérifier le succès**

Run: `python tests/smoke_mekihub.py`
Expected: tous les tests passent.

> Note : `enqueue` planifie un `_notify` via `create_task` quand une boucle tourne ; sinon `pop_next`
> re-teste `self._items` à l'entrée (pas de blocage si déjà rempli). Le test ci-dessus enqueue **avant**
> `pop_next`, donc `pop_next` trouve la file non vide sans attendre — robuste.

- [ ] **Step 5 : py_compile + commit**

```bash
python -m py_compile packages/mekihub/hub.py
git add packages/mekihub/hub.py tests/smoke_mekihub.py
git commit -m "mekihub: PendingQueue (file FIFO supprimable, pop_next async)"
```

---

## Task 4 : `FakeLLM` de test + `SessionHub` (submit / subscribe / snapshot / worker)

**Files:**
- Create: `tests/fakes.py`
- Modify: `packages/mekihub/hub.py` (ajout `SessionHub`)
- Test: `tests/smoke_mekihub.py` (ajout)

- [ ] **Step 1 : `tests/fakes.py` — un LLM factice déterministe**

```python
"""fakes.py — doublures de test réseau-free pour mekihub (pas de SDK, pas de clé)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class _Resp:
    text: str
    tool_calls: list = field(default_factory=list)
    finish_reason: str = "stop"
    message: dict = field(default_factory=dict)


class FakeLLM:
    """Renvoie une réponse texte fixe sans outil. `model` exposé comme la vraie LLM.

    `reply` : texte renvoyé. `delay` : secondes de pause (synchrone) pour simuler un run lent
    et tester l'empilement de la file.
    """

    def __init__(self, reply: str = "réponse de test", delay: float = 0.0, model: str = "fake/model"):
        self.reply = reply
        self.delay = delay
        self.model = model

    def complete(self, messages, tools=None):
        import time
        if self.delay:
            time.sleep(self.delay)
        msg = {"role": "assistant", "content": self.reply}
        return _Resp(text=self.reply, tool_calls=[], finish_reason="stop", message=msg)

    def stream(self, messages, tools=None):
        import time
        for word in self.reply.split():
            if self.delay:
                time.sleep(self.delay)
            yield word + " "
        msg = {"role": "assistant", "content": self.reply}
        return _Resp(text=self.reply, tool_calls=[], finish_reason="stop", message=msg)
```

- [ ] **Step 2 : test qui échoue — un run complet via le hub**

Ajouter dans `tests/smoke_mekihub.py` :

```python
def test_hub_submit_run_and_subscribe():
    sys.path.insert(0, str(ROOT / "tests"))
    from fakes import FakeLLM
    from mekihub.hub import SessionHub

    async def scenario():
        store = SessionStore(directory=str(ROOT / ".sessions"))
        sess = store.create(model="fake/model", system="sys")
        hub = SessionHub(store=store, llm_factory=lambda: FakeLLM(reply="bonjour le monde"),
                         tools=[], dispatch={})
        alice = Author(id="c1", name="alice", color="#39ff14")

        received = []
        sub = hub.subscribe(sess.id)
        first = await sub.__anext__()                      # Snapshot d'amorçage
        assert isinstance(first, hub_events.Snapshot)

        async def collect():
            async for e in sub:
                received.append(e)
                if isinstance(e, hub_events.Idle):
                    break
        task = asyncio.create_task(collect())
        await asyncio.sleep(0.05)
        hub.submit(sess.id, "salut", author=alice)
        await asyncio.wait_for(task, timeout=5)

        kinds = [type(e).__name__ for e in received]
        assert "QueueEnqueued" in kinds
        assert "RunStarted" in kinds
        assert "MessagePosted" in kinds
        assert "AgentDone" in kinds
        assert "RunFinished" in kinds
        assert kinds[-1] == "Idle"
        # la session a bien le message user + la réponse assistant, sans champ auteur dans messages
        s2 = store.load(sess.id)
        assert {"role": "user", "content": "salut"} in s2.messages
        assert any(m.get("role") == "assistant" for m in s2.messages)
        assert all("author" not in m for m in s2.messages)
        store.delete(sess.id)
    asyncio.run(scenario())
```

et l'appeler dans `__main__`.

- [ ] **Step 3 : lancer, vérifier l'échec**

Run: `python tests/smoke_mekihub.py`
Expected: `ImportError: cannot import name 'SessionHub'`

- [ ] **Step 4 : implémenter `SessionHub` (suite de `hub.py`)**

Ajouter à `packages/mekihub/hub.py` :

```python
_DONE = object()


class _Room:
    """État runtime d'une session : worker, file, abonnés, présence."""

    def __init__(self):
        self.queue = PendingQueue()
        self.running: QueueItem | None = None
        self.presence: dict[str, Author] = {}      # author.id -> Author
        self.subscribers: set[asyncio.Queue] = set()
        self.worker: asyncio.Task | None = None


class SessionHub:
    """Bus de conversation à état partagé. Agnostique du transport (ni NiceGUI ni HTTP)."""

    def __init__(self, store: SessionStore, llm_factory, tools, dispatch):
        self.store = store
        self.llm_factory = llm_factory          # () -> objet avec .complete/.stream/.model
        self.tools = tools
        self.dispatch = dispatch
        self._rooms: dict[str, _Room] = {}

    def _room(self, session_id: str) -> _Room:
        room = self._rooms.get(session_id)
        if room is None:
            room = _Room()
            self._rooms[session_id] = room
        return room

    def _publish(self, session_id: str, event) -> None:
        room = self._room(session_id)
        for q in list(room.subscribers):
            q.put_nowait(event)

    def snapshot(self, session_id: str) -> SessionState:
        sess = self.store.load(session_id)
        room = self._room(session_id)
        return SessionState(id=sess.id, title=sess.title, messages=list(sess.messages),
                            authors=dict(sess.authors), queue=room.queue.pending(),
                            running=room.running, presence=list(room.presence.values()))

    def join(self, session_id: str, author: Author) -> None:
        room = self._room(session_id)
        room.presence[author.id] = author
        self._publish(session_id, ev.PresenceChanged(present=list(room.presence.values())))

    def leave(self, session_id: str, author: Author) -> None:
        room = self._room(session_id)
        room.presence.pop(author.id, None)
        self._publish(session_id, ev.PresenceChanged(present=list(room.presence.values())))

    def submit(self, session_id: str, text: str, author: Author) -> str:
        room = self._room(session_id)
        item = QueueItem(item_id=uuid.uuid4().hex[:8], author=author, text=text, ts=now_iso())
        room.queue.enqueue(item)
        self._publish(session_id, ev.QueueEnqueued(item_id=item.item_id, author_name=author.name,
                                                   color=author.color, text=text, ts=item.ts))
        self._ensure_worker(session_id)
        return item.item_id

    def delete_pending(self, session_id: str, item_id: str) -> bool:
        room = self._room(session_id)
        ok = room.queue.delete(item_id)
        if ok:
            self._publish(session_id, ev.QueueItemDeleted(item_id=item_id))
        return ok

    async def subscribe(self, session_id: str):
        room = self._room(session_id)
        q: asyncio.Queue = asyncio.Queue()
        room.subscribers.add(q)
        try:
            yield ev.Snapshot(state=self.snapshot(session_id))
            while True:
                yield await q.get()
        finally:
            room.subscribers.discard(q)

    def _ensure_worker(self, session_id: str) -> None:
        room = self._room(session_id)
        if room.worker is None or room.worker.done():
            room.worker = asyncio.create_task(self._run_worker(session_id))

    async def _run_worker(self, session_id: str) -> None:
        from base import run_agent  # mekicore (sys.path posé par __init__)
        room = self._room(session_id)
        llm = self.llm_factory()
        while room.queue.pending():
            item = await room.queue.pop_next()
            room.running = item
            self._publish(session_id, ev.RunStarted(item_id=item.item_id))
            sess = self.store.load(session_id)
            idx = sess.add_user(item.text, author=item.author)
            self.store.save(sess)
            self._publish(session_id, ev.MessagePosted(index=idx, author_name=item.author.name,
                                                       color=item.author.color, text=item.text))
            gen = run_agent(sess.messages, llm, self.tools, self.dispatch, stream=True)
            try:
                while True:
                    e = await asyncio.to_thread(next, gen, _DONE)
                    if e is _DONE:
                        break
                    self._publish(session_id, self._translate(e))
            except Exception as exc:  # never-raise : le run d'une session ne tue pas le hub
                self._publish(session_id, ev.RunError(str(exc)))
            self.store.save(sess)
            room.running = None
        self._publish(session_id, ev.Idle())

    @staticmethod
    def _translate(e):
        """Traduit un event mekicore en event mekihub."""
        import events as mc  # events.py de mekicore (même nom, résolu via sys.path mekicore)
        name = type(e).__name__
        if name == "AssistantDelta":
            return ev.AgentDelta(text=e.text)
        if name == "AssistantDone":
            return ev.AgentDone(text=e.text)
        if name == "ToolStarted":
            return ev.ToolStarted(id=e.id, name=e.name, args=e.args)
        if name == "ToolFinished":
            return ev.ToolFinished(id=e.id, name=e.name, output=e.output)
        if name == "RunFinished":
            return ev.RunFinished()
        if name == "RunError":
            return ev.RunError(message=e.message)
        if name == "ThinkingStarted":
            return ev.RunStarted(item_id="")     # déjà couvert ; mappe sans casser
        return ev.RunFinished()
```

> **Risque de collision de nom de module** : `mekihub/events.py` et `mekicore/events.py` ont le même nom.
> Dans `hub.py`, l'import `import events as ev` (en tête) résout `mekihub/events.py` car `__init__.py`
> insère `mekihub/` en tête de `sys.path`. Dans `_translate`, on ré-importe `events as mc` qui résout le
> **même** module mekihub — donc on **discrimine par `type(e).__name__`** (chaîne), pas par `isinstance`,
> pour éviter toute ambiguïté. Implémenter exactement comme ci-dessus (comparaison de noms).

- [ ] **Step 5 : lancer, vérifier le succès**

Run: `python tests/smoke_mekihub.py`
Expected: tous les tests passent (`OK - ...`).

- [ ] **Step 6 : py_compile + commit**

```bash
python -m py_compile packages/mekihub/hub.py tests/fakes.py
git add packages/mekihub/hub.py tests/fakes.py tests/smoke_mekihub.py
git commit -m "mekihub: SessionHub (submit/subscribe/snapshot + worker FIFO async, pont sync run_agent)"
```

---

## Task 5 : multi-abonnés + suppression de file + empilement (tests d'intégration hub)

**Files:**
- Test: `tests/smoke_mekihub.py` (ajout)

- [ ] **Step 1 : tests qui échouent — deux abonnés + delete pending + file pleine**

Ajouter dans `tests/smoke_mekihub.py` :

```python
def test_two_subscribers_and_queue_delete():
    sys.path.insert(0, str(ROOT / "tests"))
    from fakes import FakeLLM
    from mekihub.hub import SessionHub

    async def scenario():
        store = SessionStore(directory=str(ROOT / ".sessions"))
        sess = store.create(model="fake/model", system="sys")
        # delay > 0 : le 1er run dure, on a le temps d'empiler puis supprimer
        hub = SessionHub(store=store, llm_factory=lambda: FakeLLM(reply="ok", delay=0.2),
                         tools=[], dispatch={})
        alice = Author(id="c1", name="alice", color="#39ff14")
        bob = Author(id="c2", name="bob", color="#ff2bd6")

        sub_a = hub.subscribe(sess.id); await sub_a.__anext__()
        sub_b = hub.subscribe(sess.id); await sub_b.__anext__()
        got_a, got_b = [], []

        async def drain(sub, acc):
            async for e in sub:
                acc.append(type(e).__name__)
                if acc.count("Idle") >= 1:
                    break

        ta = asyncio.create_task(drain(sub_a, got_a))
        tb = asyncio.create_task(drain(sub_b, got_b))
        await asyncio.sleep(0.02)
        hub.submit(sess.id, "premier", author=alice)       # démarre le run (lent)
        await asyncio.sleep(0.02)
        qid2 = hub.submit(sess.id, "deuxieme", author=bob)  # s'empile (run en cours)
        await asyncio.sleep(0.02)
        assert hub.delete_pending(sess.id, qid2) is True    # supprime l'item EN ATTENTE
        await asyncio.wait_for(asyncio.gather(ta, tb), timeout=5)

        # les DEUX abonnés ont reçu le broadcast (QueueEnqueued + QueueItemDeleted + AgentDone)
        for got in (got_a, got_b):
            assert "QueueEnqueued" in got
            assert "QueueItemDeleted" in got
            assert "AgentDone" in got
        store.delete(sess.id)
    asyncio.run(scenario())
```

et l'appeler dans `__main__` ; ajouter une ligne finale `print("OK - tous les smoke mekihub passent")`.

- [ ] **Step 2 : lancer, vérifier l'échec puis le succès**

Run: `python tests/smoke_mekihub.py`
Expected: d'abord un échec si un comportement manque (ex. broadcast non reçu par les 2) ; corriger `hub.py` si besoin (le `_publish` itère déjà `room.subscribers`), puis : `OK - tous les smoke mekihub passent`.

- [ ] **Step 3 : non-régression des smokes existants**

Run: `python tests/smoke_packages.py` puis `python tests/smoke_mekichat.py`
Expected: `OK - tous les smoke tests passent` et `OK - smoke mekichat passe`.

- [ ] **Step 4 : commit**

```bash
git add tests/smoke_mekihub.py
git commit -m "mekihub: tests integration (multi-abonnes, delete pending, empilement file)"
```

---

## Task 6 : `mekichat/sessions.py` → ré-export de `mekihub` (additif, non destructif)

**Files:**
- Modify: `packages/mekichat/sessions.py` (remplacer le corps par un ré-export ; ne PAS supprimer le fichier)

- [ ] **Step 1 : test qui échoue — l'API historique vient maintenant de mekihub**

Ajouter à `tests/smoke_mekichat.py` un contrôle (au début de son `main`/première fonction) :

```python
def test_sessions_reexport_from_mekihub():
    import sessions as chat_sessions
    from mekihub import session as hub_session
    assert chat_sessions.SessionStore is hub_session.SessionStore   # même classe (ré-export)
```

> Vérifier d'abord comment `tests/smoke_mekichat.py` pose son `sys.path` ; ajouter
> `sys.path.insert(0, str(ROOT / "packages"))` si absent pour résoudre `mekihub`.

- [ ] **Step 2 : lancer, vérifier l'échec**

Run: `python tests/smoke_mekichat.py`
Expected: l'assertion `is` échoue (deux classes distinctes aujourd'hui).

- [ ] **Step 3 : transformer `packages/mekichat/sessions.py` en ré-export**

Remplacer **tout** le contenu de `packages/mekichat/sessions.py` par :

```python
"""sessions.py — ré-export de la couche session canonique (packages/mekihub/session.py).

Conservé pour compatibilité des imports existants (`import sessions`). La source unique de
vérité est désormais mekihub. (Retrait de ce shim = piste différée, cf. docs/refacto-differe.md.)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # packages/ → mekihub

from mekihub.session import (  # noqa: F401
    Author, QueueItem, Session, SessionMeta, SessionState, SessionStore,
)
```

- [ ] **Step 4 : lancer, vérifier le succès + non-régression**

Run: `python tests/smoke_mekichat.py`
Expected: `OK - smoke mekichat passe` (et le nouveau contrôle `is` passe).

- [ ] **Step 5 : py_compile + noter la piste différée + commit**

Ajouter une ligne à `docs/refacto-differe.md` (section adaptée) : « `mekichat/sessions.py` est un ré-export de `mekihub.session` ; suppression possible une fois tous les imports migrés vers `mekihub`. »

```bash
python -m py_compile packages/mekichat/sessions.py
git add packages/mekichat/sessions.py tests/smoke_mekichat.py docs/refacto-differe.md
git commit -m "mekichat: sessions.py devient un re-export de mekihub.session (additif)"
```

---

## Task 7 : front NiceGUI multi-utilisateur — présence + abonnement broadcast

**Files:**
- Create: `packages/mekichat/realtime.py`
- Modify: `packages/mekichat/app.py`, `packages/mekichat/views.py`, `packages/mekichat/static/mekichat.css`
- Test: `.refactor-tmp/diag_realtime.py` (Playwright, manuel via le serveur)

> Cette tâche change le pilotage du front : au lieu d'appeler `run_agent` directement dans `send`,
> `app.py` instancie **un `SessionHub` partagé au niveau module** et chaque client (page) **s'abonne**.

- [ ] **Step 1 : `realtime.py` — author par client + helper d'abonnement**

```python
"""realtime.py — colle NiceGUI ↔ SessionHub : identité par client, boucle d'abonnement.

Aucune logique métier ici (elle est dans mekihub) : uniquement le rendu live côté NiceGUI.
"""
from __future__ import annotations

import random
import uuid

from nicegui import app

_COLORS = ["#39ff14", "#ff2bd6", "#19e0ff", "#f7ff12", "#b06bff", "#4d8cff", "#2bff88"]


def author_for_client():
    """Crée/restaure un Author éphémère pour ce navigateur (stocké dans app.storage.user)."""
    from mekihub.session import Author
    store = app.storage.user
    if "author_id" not in store:
        store["author_id"] = uuid.uuid4().hex[:8]
        store["author_name"] = "anon-" + store["author_id"][:4]
        store["author_color"] = random.choice(_COLORS)
    return Author(id=store["author_id"], name=store["author_name"], color=store["author_color"])
```

- [ ] **Step 2 : brancher `app.py` sur un `SessionHub` module-level**

Dans `packages/mekichat/app.py`, après les imports, ajouter `packages/` au path et instancier le hub une seule fois :

```python
sys.path.insert(0, str(HERE.parent))               # packages/ (mekihub, mekillm)
import realtime  # noqa: E402
from mekihub.hub import SessionHub  # noqa: E402
from mekihub.session import SessionStore  # noqa: E402

_HUB = None
def _get_hub():
    global _HUB
    if _HUB is None:
        _HUB = SessionHub(store=SessionStore(), llm_factory=mekillm.LLM, tools=TOOLS, dispatch=DISPATCH)
    return _HUB
```

Remplacer la logique de `send` : au lieu de piloter `run_agent`, faire `_get_hub().submit(current.id, text, author=realtime.author_for_client())`. Le rendu vient de la boucle d'abonnement (Step 3), pas de `send`.

Dans `index()`, après construction du fil, démarrer l'abonnement (voir Step 3). Activer le stockage NiceGUI : `ui.run(..., storage_secret="mekichat-dev")` (requis par `app.storage.user`).

- [ ] **Step 3 : boucle d'abonnement live (dans `index()` de `app.py`)**

```python
async def _subscribe_loop():
    author = realtime.author_for_client()
    hub = _get_hub()
    hub.join(current.id, author)
    handles: dict = {}
    try:
        async for event in hub.subscribe(current.id):
            try:
                _render_hub_event(event, handles)
                _scroll_bottom()
            except RuntimeError as exc:      # onglet fermé pendant le run
                if "deleted" in str(exc):
                    break
                raise
    finally:
        hub.leave(current.id, author)

# au bas de _refresh(), une fois le fil construit : lancer la coroutine d'abonnement liée au client
# via un ui.timer one-shot à callback async (NiceGUI exécute le callback dans le contexte du client,
# donc les mutations d'UI déclenchées par les events sont poussées au bon client).
ui.timer(0.1, _subscribe_loop, once=True)
```

> Le `_render_hub_event` (Step 4) crée/complète les blocs. La fonction `render_thread` reste pour
> l'historique au chargement ; `Snapshot` au début de l'abonnement rejoue le fil + la file.

- [ ] **Step 4 : `_render_hub_event` + rendu file/présence (`views.py`)**

Dans `views.py`, ajouter `render_queue_item(item, on_delete)`, `render_presence(present)`, et
`render_user_message(text, name, color)`. Dans `app.py`, ajouter `_render_hub_event(event, handles)`
qui mappe : `Snapshot` → reconstruit fil+file+présence ; `QueueEnqueued` → ajoute une ligne file (avec ✕
appelant `_get_hub().delete_pending`) ; `QueueItemDeleted` → retire la ligne ; `MessagePosted` → bulle
user attribuée ; `AgentDelta`/`AgentDone` → bulle de streaming/markdown ; `ToolStarted`/`ToolFinished` →
bloc d'outil (réutilise `render_tool`/`fill_tool`) ; `PresenceChanged` → maj pastilles ; `Idle` → retire
l'indicateur d'activité.

Code de `views.py` (ajouts) :

```python
def render_presence(present):
    with ui.element("div").classes("presence") as box:
        for a in present:
            chip = ui.label(a.name).classes("pres-chip")
            chip.style(f"--ac:{a.color}")
    return box


def render_queue_item(item_id, name, color, text, on_delete):
    row = ui.element("div").classes("qitem")
    with row:
        ui.label(name).classes("q-author").style(f"--ac:{color}")
        ui.label(text).classes("q-text")
        btn = ui.button("✕").props("flat dense").classes("q-del")
        btn.on("click", lambda _: on_delete(item_id))
    return row


def render_user_message(text, name, color):
    el = ui.element("div").classes("msg user attrib")
    with el:
        ui.label(name).classes("msg-author").style(f"--ac:{color}")
        ui.label(text).classes("msg-body")
    return el
```

- [ ] **Step 5 : styles file/présence (`static/mekichat.css`)**

Ajouter (cohérent avec le thème Phosphore) :

```css
.presence{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0}
.pres-chip{font-family:var(--mono);font-size:10.5px;padding:1px 7px;border:1px solid var(--ac);
  color:var(--ac);border-radius:2px;text-transform:uppercase;letter-spacing:.1em}
.qitem{display:flex;align-items:center;gap:8px;padding:4px 8px;border-left:2px solid var(--ac,#6c8595);
  background:rgba(0,0,0,.35);margin:2px 0}
.q-author{color:var(--ac);font-weight:700;font-size:11px}
.q-text{color:var(--muted);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.q-del{color:#ff6b6b !important;min-width:0 !important}
.msg.user.attrib .msg-author{color:var(--ac);font-weight:700;font-size:11px;margin-right:6px}
```

- [ ] **Step 6 : valider visuellement (Playwright, 2 clients) — `.refactor-tmp/diag_realtime.py`**

Lancer le serveur (`python packages/mekichat/app.py` en arrière-plan, attendre le port 8080), puis :

```python
"""diag_realtime.py — 2 contextes navigateur sur la même session : broadcast + file + présence."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx1 = b.new_context(); ctx2 = b.new_context()
    p1 = ctx1.new_page(); p2 = ctx2.new_page()
    p1.goto("http://127.0.0.1:8080", wait_until="networkidle", timeout=20000)
    p2.goto("http://127.0.0.1:8080", wait_until="networkidle", timeout=20000)
    p1.wait_for_timeout(1500)
    # poster depuis le client 1
    p1.fill(".ta textarea", "bonjour depuis A")
    p1.click(".send")
    p2.wait_for_timeout(2500)
    # le message de A doit apparaître chez B
    text_b = p2.inner_text(".thread-inner")
    p1.screenshot(path=str(ROOT / ".refactor-tmp" / "rt_a.png"), full_page=True)
    p2.screenshot(path=str(ROOT / ".refactor-tmp" / "rt_b.png"), full_page=True)
    print(json.dumps({"B_voit_message_de_A": "bonjour depuis A" in text_b}, ensure_ascii=True))
    b.close()
```

Run: `python .refactor-tmp/diag_realtime.py`
Expected: `{"B_voit_message_de_A": true}` ; **lire `rt_a.png` et `rt_b.png`** et confirmer que le message + la réponse de l'agent apparaissent **dans les deux** fenêtres (un HTTP 200 ne suffit pas). Itérer sur la boucle d'abonnement jusqu'à rendu correct dans les 2 clients.

- [ ] **Step 7 : py_compile + commit**

```bash
python -m py_compile packages/mekichat/realtime.py packages/mekichat/app.py packages/mekichat/views.py
git add packages/mekichat/realtime.py packages/mekichat/app.py packages/mekichat/views.py packages/mekichat/static/mekichat.css
git commit -m "mekichat: front multi-utilisateur temps reel (presence + abonnement SessionHub + UI file)"
```

---

## Task 8 : UI file d'attente live + suppression (validation Playwright)

**Files:**
- Test: `.refactor-tmp/diag_queue.py` (Playwright)
- Modify si besoin: `packages/mekichat/app.py`, `views.py`

- [ ] **Step 1 : forcer un run lent pour observer la file**

Pour la validation, lancer le serveur avec un LLM lent : exposer une variable d'env `MEKICHAT_FAKE_LLM=1`
lue dans `_get_hub()` qui, si présente, utilise `llm_factory=lambda: __import__("sys").modules` —
**non**. À la place : ajouter dans `app.py` un `llm_factory` conditionnel :

```python
def _llm_factory():
    import os
    if os.environ.get("MEKICHAT_FAKE_LLM"):
        sys.path.insert(0, str(HERE.parent.parent / "tests"))
        from fakes import FakeLLM
        return FakeLLM(reply="reponse simulee lente", delay=0.6)
    return mekillm.LLM()
```

et utiliser `llm_factory=_llm_factory` dans `_get_hub()`.

- [ ] **Step 2 : diag file d'attente (2 messages, suppression)**

```python
"""diag_queue.py — empilement de la file + suppression, vus en multi-client."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 1000})
    page.goto("http://127.0.0.1:8080", wait_until="networkidle", timeout=20000)
    page.wait_for_timeout(1500)
    page.fill(".ta textarea", "message un"); page.click(".send")
    page.wait_for_timeout(150)
    page.fill(".ta textarea", "message deux"); page.click(".send")  # s'empile (run lent en cours)
    page.wait_for_timeout(400)
    n_queue = page.eval_on_selector_all(".qitem", "els => els.length")
    page.screenshot(path=str(ROOT / ".refactor-tmp" / "queue_full.png"), full_page=True)
    # supprimer le 1er item en attente
    page.eval_on_selector_all(".qitem .q-del", "els => { if (els[0]) els[0].click(); }")
    page.wait_for_timeout(400)
    n_after = page.eval_on_selector_all(".qitem", "els => els.length")
    page.screenshot(path=str(ROOT / ".refactor-tmp" / "queue_after_delete.png"), full_page=True)
    print(json.dumps({"queue_avant": n_queue, "queue_apres_suppression": n_after}, ensure_ascii=True))
    b.close()
```

Run (serveur lancé avec `MEKICHAT_FAKE_LLM=1`) : `python .refactor-tmp/diag_queue.py`
Expected: `{"queue_avant": 1, "queue_apres_suppression": 0}` (1 en attente pendant que l'autre tourne ;
0 après suppression). **Lire `queue_full.png` / `queue_after_delete.png`** : item en attente visible avec
✕, puis disparu. Itérer si l'UI file ne se met pas à jour.

- [ ] **Step 3 : commit**

```bash
git add packages/mekichat/app.py packages/mekichat/views.py
git commit -m "mekichat: file d'attente live (empilement + suppression) validee Playwright"
```

---

## Task 9 : adaptateur Discord (logique testable réseau-free)

**Files:**
- Create: `packages/mekihub/adapters/__init__.py`, `packages/mekihub/adapters/discord.py`
- Modify: `requirements.txt`
- Test: `tests/smoke_mekihub.py` (ajout `FakeDiscordClient`)

- [ ] **Step 1 : test qui échoue — ingestion + rendu via client factice**

Ajouter dans `tests/smoke_mekihub.py` :

```python
def test_discord_adapter_with_fake_client():
    sys.path.insert(0, str(ROOT / "tests"))
    from fakes import FakeLLM
    from mekihub.hub import SessionHub
    from mekihub.adapters.discord import DiscordAdapter, FakeDiscordClient, FakeMessage

    async def scenario():
        store = SessionStore(directory=str(ROOT / ".sessions"))
        sess = store.create(model="fake/model", system="sys")
        hub = SessionHub(store=store, llm_factory=lambda: FakeLLM(reply="salut discord"),
                         tools=[], dispatch={})
        client = FakeDiscordClient()
        adapter = DiscordAdapter(hub=hub, client=client, channel_session={"chan1": sess.id})
        await adapter.handle_message(FakeMessage(channel_id="chan1", author_name="dom",
                                                 author_id="42", is_bot=False, content="coucou"))
        await asyncio.sleep(0.3)
        await adapter.flush()                      # laisse la tâche d'abonnement rendre
        # le client factice a posté/édité au moins un message contenant la réponse de l'agent
        assert any("salut discord" in m for m in client.sent_texts())
        store.delete(sess.id)
    asyncio.run(scenario())
```

et l'appeler dans `__main__`.

- [ ] **Step 2 : lancer, vérifier l'échec**

Run: `python tests/smoke_mekihub.py`
Expected: `ModuleNotFoundError: No module named 'mekihub.adapters'`

- [ ] **Step 3 : implémenter l'adaptateur + les doublures**

`packages/mekihub/adapters/__init__.py` : fichier vide.

`packages/mekihub/adapters/discord.py` :

```python
"""discord.py — adaptateur Discord du SessionHub.

Mapping canal Discord -> session. Un message entrant -> hub.submit. Une tâche par session
mappée consomme hub.subscribe et rend la sortie agent (post/edit). discord.py n'est PAS importé
au niveau module (optionnel) : `connect_real()` l'importe à la demande. La logique est testable
via FakeDiscordClient (réseau-free).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class FakeMessage:
    channel_id: str
    author_name: str
    author_id: str
    is_bot: bool
    content: str


class FakeDiscordClient:
    """Capture les envois/éditions au lieu d'appeler Discord."""

    def __init__(self):
        self._messages: list[dict] = []   # {channel_id, text}

    async def send(self, channel_id: str, text: str) -> int:
        self._messages.append({"channel_id": channel_id, "text": text})
        return len(self._messages) - 1     # "message id" = index

    async def edit(self, channel_id: str, message_id: int, text: str) -> None:
        self._messages[message_id]["text"] = text

    def sent_texts(self) -> list[str]:
        return [m["text"] for m in self._messages]


def _color_from_id(author_id: str) -> str:
    palette = ["#39ff14", "#ff2bd6", "#19e0ff", "#f7ff12", "#b06bff", "#4d8cff"]
    return palette[sum(ord(c) for c in author_id) % len(palette)]


class DiscordAdapter:
    """Branche un client Discord (réel ou factice) sur le SessionHub."""

    def __init__(self, hub, client, channel_session: dict):
        self.hub = hub
        self.client = client
        self.channel_session = channel_session     # channel_id -> session_id
        self._tasks: dict[str, asyncio.Task] = {}

    async def handle_message(self, msg: FakeMessage) -> None:
        if msg.is_bot:
            return
        session_id = self.channel_session.get(msg.channel_id)
        if session_id is None:
            return
        from session import Author
        author = Author(id=msg.author_id, name=msg.author_name, color=_color_from_id(msg.author_id))
        # s'assurer qu'une tâche d'abonnement rend la sortie de ce canal
        if msg.channel_id not in self._tasks or self._tasks[msg.channel_id].done():
            self._tasks[msg.channel_id] = asyncio.create_task(self._render_loop(msg.channel_id, session_id))
        self.hub.submit(session_id, msg.content, author=author)

    async def _render_loop(self, channel_id: str, session_id: str) -> None:
        import events as ev
        msg_id = None
        buffer = ""
        async for event in self.hub.subscribe(session_id):
            name = type(event).__name__
            if name == "RunStarted":
                buffer = ""
                msg_id = await self.client.send(channel_id, "…")
            elif name == "AgentDelta":
                buffer += event.text
                if msg_id is not None:
                    await self.client.edit(channel_id, msg_id, buffer)
            elif name == "AgentDone":
                if msg_id is not None:
                    await self.client.edit(channel_id, msg_id, event.text)
                msg_id = None
            elif name == "Idle":
                break

    async def flush(self) -> None:
        """Attend que les tâches de rendu en cours se terminent (tests)."""
        await asyncio.gather(*[t for t in self._tasks.values() if not t.done()], return_exceptions=True)

    async def connect_real(self, token: str) -> None:
        """Connexion Discord réelle (discord.py). Importé à la demande ; validation manuelle."""
        import discord  # importé seulement ici (dépendance optionnelle)
        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)

        @client.event
        async def on_message(message):  # noqa: ANN001
            await self.handle_message(FakeMessage(
                channel_id=str(message.channel.id), author_name=message.author.display_name,
                author_id=str(message.author.id), is_bot=message.author.bot, content=message.content))

        # NB : self.client doit alors être un wrapper qui appelle channel.send/edit ; câblage réel
        # finalisé lors de la validation manuelle avec un vrai token.
        await client.start(token)
```

- [ ] **Step 4 : lancer, vérifier le succès**

Run: `python tests/smoke_mekihub.py`
Expected: tous les tests passent, dont `test_discord_adapter_with_fake_client`.

- [ ] **Step 5 : ajouter la dépendance**

Ajouter `discord.py` à `requirements.txt` (une ligne `discord.py>=2.3`).

- [ ] **Step 6 : py_compile + commit**

```bash
python -m py_compile packages/mekihub/adapters/discord.py packages/mekihub/adapters/__init__.py
git add packages/mekihub/adapters requirements.txt tests/smoke_mekihub.py
git commit -m "mekihub: adaptateur Discord (logique testable via FakeDiscordClient, connexion reelle a la demande)"
```

---

## Task 10 : entrypoint `mekihub/main.py` + Docker

**Files:**
- Create: `packages/mekihub/main.py`, `Dockerfile`, `docker-compose.yml`
- Test: `tests/smoke_mekihub.py` (import smoke de main)

- [ ] **Step 1 : test qui échoue — main importable sans effet de bord**

Ajouter dans `tests/smoke_mekihub.py` :

```python
def test_main_importable():
    import importlib
    sys.path.insert(0, str(ROOT / "packages" / "mekihub"))
    m = importlib.import_module("main")
    assert hasattr(m, "build_hub") and hasattr(m, "main")
```

et l'appeler dans `__main__`.

- [ ] **Step 2 : lancer, vérifier l'échec**

Run: `python tests/smoke_mekihub.py`
Expected: `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3 : implémenter `packages/mekihub/main.py`**

```python
#!/usr/bin/env python3
"""main.py — entrypoint mekihub : hub + adaptateurs activés par .env (front/discord on/off).

MEKIHUB_FRONT=on|off   lance le front NiceGUI (in-process)
MEKIHUB_DISCORD=on|off lance l'adaptateur Discord (nécessite DISCORD_BOT_TOKEN)
Headless possible : MEKIHUB_FRONT=off MEKIHUB_DISCORD=on
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))                 # session, events, hub
sys.path.insert(0, str(HERE.parent))          # packages/ (mekillm, mekihub)
sys.path.insert(0, str(HERE.parent / "mekicore"))  # base, tools, events de mekicore


def build_hub():
    """Construit un SessionHub câblé sur mekillm + les outils de mekicore."""
    import mekillm
    from tools import DISPATCH, TOOLS
    from hub import SessionHub
    from session import SessionStore
    return SessionHub(store=SessionStore(), llm_factory=mekillm.LLM, tools=TOOLS, dispatch=DISPATCH)


def main() -> None:
    front = os.environ.get("MEKIHUB_FRONT", "on").lower() != "off"
    discord_on = os.environ.get("MEKIHUB_DISCORD", "off").lower() == "on"
    if discord_on and not front:
        # headless : boucle asyncio Discord seule
        import asyncio
        from adapters.discord import DiscordAdapter
        hub = build_hub()
        token = os.environ["DISCORD_BOT_TOKEN"]
        mapping = {}  # à renseigner via DISCORD_CHANNEL_SESSION_MAP (clé=canal, val=session)
        adapter = DiscordAdapter(hub=hub, client=None, channel_session=mapping)
        asyncio.run(adapter.connect_real(token))
        return
    # front activé : déléguer à l'app NiceGUI (qui crée son propre hub module-level)
    sys.path.insert(0, str(HERE.parent / "mekichat"))
    import app  # noqa: F401  (app.py appelle ui.run sous son garde __main__)
    print("mekihub: front mekichat — lancer via `python packages/mekichat/app.py`")


if __name__ in {"__main__", "__mp_main__"}:
    main()
```

- [ ] **Step 4 : lancer, vérifier le succès**

Run: `python tests/smoke_mekihub.py`
Expected: tous les tests passent.

- [ ] **Step 5 : `Dockerfile` + `docker-compose.yml`**

`Dockerfile` :

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY packages/ ./packages/
ENV MEKICORE_WORKSPACE=/app/workspace
RUN mkdir -p /app/workspace
EXPOSE 8080
CMD ["python", "packages/mekichat/app.py"]
```

`docker-compose.yml` :

```yaml
services:
  mekihub:
    build: .
    ports:
      - "8080:8080"
    env_file:
      - .env
    environment:
      MEKIHUB_FRONT: "on"
      MEKIHUB_DISCORD: "off"
```

> Construire/lancer Docker = **étape manuelle** ; non exécutée par la validation automatique.

- [ ] **Step 6 : py_compile + commit**

```bash
python -m py_compile packages/mekihub/main.py
git add packages/mekihub/main.py Dockerfile docker-compose.yml tests/smoke_mekihub.py
git commit -m "mekihub: entrypoint (front/discord par .env, headless) + Docker (isolation agent)"
```

---

## Task 11 : documentation + non-régression finale

**Files:**
- Create: `docs/wiki-packages/mekihub.md`
- Modify: `docs/wiki-packages/README.md`, `docs/wiki-packages/architecture.md`, `docs/README.md`, `ROADMAP.md`, `README.md`

- [ ] **Step 1 : page wiki `docs/wiki-packages/mekihub.md`**

Documenter (style des pages existantes) : rôle du paquet, `session.py` (Author/Session/SessionStore,
attribution séparée), `events.py` (liste), `hub.py` (`SessionHub` : join/leave/submit/delete_pending/
snapshot/subscribe + worker FIFO + pont `asyncio.to_thread(next, gen)`), `adapters/discord.py`,
`main.py`, relations (`mekichat`/Discord → mekihub → mekicore → mekillm), tests
(`tests/smoke_mekihub.py`). Numéros de ligne indicatifs.

- [ ] **Step 2 : mettre à jour les sommaires + ROADMAP + README**

- `docs/wiki-packages/README.md` : ajouter la ligne `mekihub.md` au sommaire + à la carte des fichiers.
- `docs/wiki-packages/architecture.md` : ajouter mekihub à la dépendance (`mekichat`/Discord → mekihub →
  mekicore → mekillm) et un paragraphe « hub temps réel (salle partagée, file FIFO, pub/sub) ».
- `docs/README.md` : ligne mekihub dans le sommaire wiki.
- `ROADMAP.md` : s16 (event bus) → mettre à jour (le hub est un bus de session pub/sub) ; ajouter une
  entrée « hub temps réel multi-canal » dans la section `packages/` ; recalculer la mention d'avancement.
- `README.md` (racine) : ajouter mekihub dans le tableau des paquets + une puce « chat temps réel
  multi-utilisateur / multi-canal (Discord) » dans « Ce que ça sait faire ».

- [ ] **Step 3 : non-régression complète**

Run (dans l'ordre) :
```
python tests/smoke_packages.py
python tests/smoke_mekichat.py
python tests/smoke_mekihub.py
```
Expected: les trois affichent leur ligne `OK` finale.

- [ ] **Step 4 : commit**

```bash
git add docs/ ROADMAP.md README.md
git commit -m "doc: mekihub (hub temps reel) — wiki-packages, architecture, ROADMAP, README"
```

---

## Revue finale (après toutes les tâches)

- Dispatcher un **code-reviewer** sur l'ensemble du diff de la branche `feat/hub-temps-reel`.
- Vérifier les **propriétés clés** : (a) `mekihub` n'importe ni `nicegui` ni `discord` au niveau module ;
  (b) l'agent ne voit **jamais** de champ auteur dans `messages` ; (c) un item **en cours** n'est pas
  supprimable ; (d) les broadcasts atteignent **tous** les abonnés ; (e) aucun fichier déplacé/supprimé.
- Puis `superpowers:finishing-a-development-branch` (merge `main` + push, selon le flux habituel).

## Validation manuelle (hors CI, nécessite des secrets/réseau)

- **Front réel** : `python packages/mekichat/app.py`, ouvrir 2 onglets, vérifier broadcast + file + présence.
- **Discord réel** : `DISCORD_BOT_TOKEN` + un canal mappé ; câbler `self.client` réel dans `connect_real`
  (wrapper `send`/`edit` sur `channel`), lancer `MEKIHUB_FRONT=off MEKIHUB_DISCORD=on python packages/mekihub/main.py`.
- **Docker** : `docker compose up --build`, ouvrir http://localhost:8080.
