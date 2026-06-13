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


def test_main_importable():
    """Vérifie que main.py est importable sans effet de bord (pas de serveur, pas de boucle)."""
    import importlib
    sys.path.insert(0, str(ROOT / "packages" / "mekihub"))
    m = importlib.import_module("main")
    assert hasattr(m, "build_hub") and hasattr(m, "main")


if __name__ == "__main__":
    test_author_and_queueitem()
    test_session_authors_separate_from_messages()
    test_events_exist()
    test_pending_queue_fifo_and_delete()
    test_hub_submit_run_and_subscribe()
    test_two_subscribers_and_queue_delete()
    test_discord_adapter_with_fake_client()
    test_main_importable()
    print("OK - tous les smoke mekihub passent")
