import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages"))

from mekihub.session import Author, QueueItem, Session, SessionState, SessionStore  # noqa: E402
from mekihub import events as hub_events  # noqa: E402


def test_events_exist():
    snap = hub_events.Snapshot(state=None)
    delta = hub_events.AgentDelta(text="hi")
    enq = hub_events.QueueEnqueued(item_id="q1", author_name="alice", color="#fff", text="hey", ts="t")
    deleted = hub_events.QueueItemDeleted(item_id="q1")
    posted = hub_events.MessagePosted(index=2, author_name="alice", color="#fff", text="hey")
    assert delta.text == "hi" and enq.item_id == "q1" and deleted.item_id == "q1"
    assert posted.index == 2 and snap.state is None


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


if __name__ == "__main__":
    test_author_and_queueitem()
    test_session_authors_separate_from_messages()
    test_events_exist()
    test_pending_queue_fifo_and_delete()
    print("OK - session")
