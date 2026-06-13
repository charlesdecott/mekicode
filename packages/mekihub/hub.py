"""hub.py — SessionHub : registre de sessions, état partagé, pub/sub mémoire, worker FIFO."""
from __future__ import annotations

import asyncio
import uuid

from session import Author, QueueItem, Session, SessionState, SessionStore, now_iso  # noqa: F401
import events as ev  # noqa: F401


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
