"""hub.py — SessionHub : registre de sessions, état partagé, pub/sub mémoire, worker FIFO."""
from __future__ import annotations

import asyncio
import uuid

from session import Author, QueueItem, Session, SessionState, SessionStore, now_iso  # noqa: F401

# Événements de salle mekihub (Snapshot, QueueEnqueued, ...). On importe le sous-module DU PACKAGE
# (`mekihub.events`) plutôt qu'un `import events` nu : ce dernier résout, selon l'ordre des insertions
# de sys.path posées par __init__.py, le module homonyme de mekicore (mekicore/events.py). Passer par
# le package garantit le bon module ET l'identité de classe partagée avec ce qu'importent les tests.
from mekihub import events as ev  # noqa: F401


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


_DONE = object()

WORKTREE_TOOL = {"type": "function", "function": {"name": "spawn_worktree",
  "description": "Propose la création d'un worktree git isolé (nouvelle feature/changement ambitieux/"
    "debug, pour ne pas bloquer main) et le lancement d'un agent dedans. Nécessite la validation "
    "de l'utilisateur avant toute création.",
  "parameters": {"type": "object", "properties": {
    "nom": {"type": "string", "description": "nom court du worktree/branche (ex: featx)"},
    "prompt_amorce": {"type": "string", "description": "consigne initiale de l'agent enfant"},
    "base": {"type": "string", "description": "branche de base (optionnel)"}},
    "required": ["nom", "prompt_amorce"]}}}


def _record_proposal(proposals, args):
    pid = uuid.uuid4().hex[:8]
    proposals.append({"proposal_id": pid, "nom": args.get("nom"),
                      "prompt_amorce": args.get("prompt_amorce"), "base": args.get("base")})
    return f"Proposition de worktree '{args.get('nom')}' envoyée pour validation."


class _Room:
    """État runtime d'une session : worker, file, abonnés, présence."""

    def __init__(self):
        self.queue = PendingQueue()
        self.running: QueueItem | None = None
        self.presence: dict[str, Author] = {}      # author.id -> Author
        self.subscribers: set[asyncio.Queue] = set()
        self.worker: asyncio.Task | None = None
        self.pending_worktrees: dict = {}          # proposal_id -> proposal dict


class SessionHub:
    """Bus de conversation à état partagé. Agnostique du transport (ni NiceGUI ni HTTP)."""

    def __init__(self, store: SessionStore, llm_factory, tools, dispatch=None, *,
                 dispatch_factory=None, registry=None, provisioner=None):
        self.store = store
        self.llm_factory = llm_factory          # () -> objet avec .complete/.stream/.model
        self.tools = tools
        if dispatch_factory is None:
            d = dispatch or {}
            dispatch_factory = lambda ws: d     # back-compat de l'API dispatch=
        self.dispatch_factory = dispatch_factory
        self.registry = registry
        self.provisioner = provisioner
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

    async def approve_worktree(self, session_id: str, proposal_id: str):
        room = self._room(session_id)
        pr = room.pending_worktrees.pop(proposal_id, None)
        if pr is None:
            return None
        try:
            from projects import add_worktree     # mekihub (sys.path déjà posé)
            parent = self.store.load(session_id)
            project = self.registry.get(parent.project_id) if self.registry else None
            if project is None:
                raise RuntimeError("projet introuvable pour cette session")
            # git worktree add (bloquant) hors boucle ; peut lever (branche déjà prise, etc.)
            await asyncio.to_thread(add_worktree, project, pr["nom"], pr.get("base"),
                                    self.registry.worktrees_base)
            system = (parent.messages[0]["content"]
                      if parent.messages and parent.messages[0].get("role") == "system" else None)
            child = self.store.create(model=parent.model, system=system,
                                      project_id=project.id, scope=pr["nom"])
        except Exception as exc:    # never-raise : échec de création → retire la carte + informe
            self._publish(session_id, ev.WorktreeRejected(proposal_id=proposal_id))
            self._publish(session_id, ev.RunError(message=f"worktree '{pr.get('nom')}' : {exc}"))
            return None
        channel_id = None
        if self.provisioner is not None:
            try:
                channel_id = await self.provisioner.ensure_channel(child)
                self.store.save(child)
            except Exception:
                channel_id = None      # never-raise : Discord optionnel
        self._publish(session_id, ev.WorktreeCreated(
            proposal_id=proposal_id, child_session_id=child.id, channel_id=channel_id))
        sys_author = Author(id="system", name="mekicode", color="#39ff14", source="system")
        self.submit(child.id, pr["prompt_amorce"], author=sys_author)
        return child.id

    def reject_worktree(self, session_id: str, proposal_id: str) -> bool:
        room = self._room(session_id)
        if room.pending_worktrees.pop(proposal_id, None) is not None:
            self._publish(session_id, ev.WorktreeRejected(proposal_id=proposal_id))
            return True
        return False

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
            from projects import workspace_for   # mekihub (sys.path déjà posé)
            workspace = workspace_for(sess, self.registry) if self.registry else None
            dispatch = self.dispatch_factory(workspace)
            idx = sess.add_user(item.text, author=item.author)
            self.store.save(sess)
            self._publish(session_id, ev.MessagePosted(index=idx, author_name=item.author.name,
                                                       color=item.author.color, text=item.text,
                                                       source=item.author.source))
            proposals = []
            if self.registry is not None:
                tools_run = list(self.tools) + [WORKTREE_TOOL]
                dispatch = {**dispatch, "spawn_worktree": lambda a, _p=proposals: _record_proposal(_p, a)}
            else:
                tools_run = self.tools
            gen = run_agent(sess.messages, llm, tools_run, dispatch, stream=True)
            try:
                while True:
                    e = await asyncio.to_thread(next, gen, _DONE)
                    if e is _DONE:
                        break
                    translated = self._translate(e)
                    if translated is not None:      # ThinkingStarted/non mappé → ignoré
                        self._publish(session_id, translated)
            except Exception as exc:  # never-raise : le run d'une session ne tue pas le hub
                self._publish(session_id, ev.RunError(str(exc)))
            self.store.save(sess)
            for pr in proposals:
                room.pending_worktrees[pr["proposal_id"]] = pr
                self._publish(session_id, ev.WorktreeProposed(
                    proposal_id=pr["proposal_id"], session_id=session_id,
                    name=pr["nom"], prompt=pr["prompt_amorce"], base=pr.get("base")))
            room.running = None
        self._publish(session_id, ev.Idle())

    @staticmethod
    def _translate(e):
        """Traduit un event mekicore en event mekihub.

        Discrimine par `type(e).__name__` (chaîne) et NON par isinstance : mekihub/events.py et
        mekicore/events.py ont le même nom de module, donc isinstance serait ambigu selon l'ordre
        de résolution de sys.path.
        """
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
        # ThinkingStarted (et tout event mekicore non mappé) : ignoré. Le worker publie déjà son
        # propre RunStarted ; re-publier ici créerait des RunStarted parasites (double send côté
        # adaptateurs). Renvoyer None → le worker filtre.
        return None
