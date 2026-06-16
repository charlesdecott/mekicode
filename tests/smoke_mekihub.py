import asyncio
import os
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


def test_project_registry_crud():
    import tempfile, subprocess
    from pathlib import Path
    from mekihub.projects import ProjectRegistry
    with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as repo:
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        reg = ProjectRegistry(path=str(Path(base) / "projects.json"))
        p = reg.register(repo, name="Mekipedia")
        assert p.slug == "mekipedia" and p.default_branch in ("main", "master")
        assert reg.get(p.id).repo_path == str(Path(repo).resolve())
        assert [x.id for x in reg.list()] == [p.id]
        reg.remove(p.id); assert reg.list() == []


def test_register_rejects_non_git():
    import tempfile
    from pathlib import Path
    from mekihub.projects import ProjectRegistry
    with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as d:
        reg = ProjectRegistry(path=str(Path(base) / "p.json"))
        try:
            reg.register(d); assert False, "doit refuser un non-repo"
        except ValueError:
            pass


def test_workspace_for_main_and_worktree():
    import tempfile, subprocess, os
    from pathlib import Path
    from mekihub.projects import ProjectRegistry, workspace_for, add_worktree
    from mekihub.session import Session
    with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as repo:
        subprocess.run(["git","init","-q"], cwd=repo, check=True)
        subprocess.run(["git","commit","--allow-empty","-q","-m","init"], cwd=repo,
                       env={**os.environ,"GIT_AUTHOR_NAME":"t","GIT_AUTHOR_EMAIL":"t@t",
                            "GIT_COMMITTER_NAME":"t","GIT_COMMITTER_EMAIL":"t@t"}, check=True)
        reg = ProjectRegistry(path=str(Path(base)/"p.json"), worktrees_base=str(Path(base)/"wt"))
        p = reg.register(repo, name="proj")
        s_main = Session(id="s1", title="t", model="m", created_at="t", project_id=p.id, scope="main")
        assert workspace_for(s_main, reg) == Path(repo).resolve()
        wt_dir = add_worktree(p, "featx", base=None, worktrees_base=str(Path(base)/"wt"))
        assert wt_dir.exists()
        s_wt = Session(id="s2", title="t", model="m", created_at="t", project_id=p.id, scope="featx")
        assert workspace_for(s_wt, reg) == wt_dir.resolve()


def test_session_project_fields_and_filtered_list():
    import tempfile
    from mekihub.session import SessionStore
    with tempfile.TemporaryDirectory() as d:
        store = SessionStore(directory=d)
        a = store.create(model="m", project_id="p1", scope="main")
        b = store.create(model="m", project_id="p1", scope="featx")
        c = store.create(model="m", project_id="p2", scope="main")
        assert store.load(a.id).project_id == "p1" and store.load(b.id).scope == "featx"
        assert {m.id for m in store.list(project_id="p1")} == {a.id, b.id}
        assert {m.id for m in store.list(project_id="p1", scope="main")} == {a.id}
        assert {m.id for m in store.list()} == {a.id, b.id, c.id}


def test_legacy_session_defaults_to_mekicode_project():
    import tempfile, json
    from pathlib import Path
    from mekihub.session import SessionStore
    with tempfile.TemporaryDirectory() as d:
        (Path(d)/"old123.json").write_text(json.dumps(
            {"id":"old123","title":"t","model":"m","created_at":"t","messages":[],"authors":{}}),
            encoding="utf-8")
        store = SessionStore(directory=d)
        s = store.load("old123")
        assert s.project_id == "mekicode" and s.scope == "main"


def test_author_has_source_default_none():
    from mekihub.session import Author
    a = Author(id="c1", name="alice", color="#fff")
    assert a.source is None
    b = Author(id="c2", name="bob", color="#fff", source="discord:chan1")
    assert b.source == "discord:chan1"


def test_hub_uses_per_session_workspace():
    import tempfile, subprocess
    from pathlib import Path
    sys.path.insert(0, str(ROOT / "tests")); from fakes import FakeLLM
    sys.path.insert(0, str(ROOT / "packages" / "mekicore")); import tools
    from mekihub.hub import SessionHub
    from mekihub.session import Author, SessionStore
    from mekihub.projects import ProjectRegistry
    async def scenario():
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as repo:
            subprocess.run(["git","init","-q"], cwd=repo, check=True)
            (Path(repo)/"marqueur.txt").write_text("ok", encoding="utf-8")
            reg = ProjectRegistry(path=str(Path(base)/"p.json"))
            p = reg.register(repo, name="proj")
            store = SessionStore(directory=str(Path(base)/"sess"))
            sess = store.create(model="m", system="sys", project_id=p.id, scope="main")
            hub = SessionHub(store=store, llm_factory=lambda: FakeLLM(reply="done"),
                             tools=tools.TOOLS, dispatch_factory=tools.make_dispatch, registry=reg)
            captured = []
            orig = tools.make_dispatch
            hub.dispatch_factory = lambda w, _o=orig, _c=captured: (_c.append(w), _o(w))[1]
            sub = hub.subscribe(sess.id); await sub.__anext__()
            async def collect():
                async for e in sub:
                    if type(e).__name__ == "Idle": break
            t = asyncio.create_task(collect())
            hub.submit(sess.id, "salut", author=Author(id="c",name="a",color="#fff"))
            await asyncio.wait_for(t, timeout=5)
            assert captured and captured[0] == Path(repo).resolve()
    asyncio.run(scenario())


def test_spawn_worktree_proposes_without_creating():
    import tempfile, subprocess
    from pathlib import Path
    sys.path.insert(0, str(ROOT / "tests")); from fakes import FakeToolLLM
    sys.path.insert(0, str(ROOT / "packages" / "mekicore")); import tools
    from mekihub.hub import SessionHub
    from mekihub.projects import ProjectRegistry, _wt_dir
    from mekihub.session import Author, SessionStore
    async def scenario():
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as repo:
            subprocess.run(["git","init","-q"], cwd=repo, check=True)
            reg = ProjectRegistry(path=str(Path(base)/"p.json"), worktrees_base=str(Path(base)/"wt"))
            p = reg.register(repo, name="proj")
            store = SessionStore(directory=str(Path(base)/"sess"))
            sess = store.create(model="m", system="sys", project_id=p.id, scope="main")
            llm = FakeToolLLM(tool_name="spawn_worktree",
                              tool_args={"nom":"featx","prompt_amorce":"code la feature X"},
                              final="proposé")
            hub = SessionHub(store=store, llm_factory=lambda: llm, tools=tools.TOOLS,
                             dispatch_factory=tools.make_dispatch, registry=reg)
            got = []
            sub = hub.subscribe(sess.id); await sub.__anext__()
            async def collect():
                async for e in sub:
                    got.append(type(e).__name__)
                    if got.count("Idle") >= 1: break
            t = asyncio.create_task(collect())
            hub.submit(sess.id, "fais la feature X", author=Author(id="c",name="a",color="#fff"))
            await asyncio.wait_for(t, timeout=5)
            assert "WorktreeProposed" in got, got
            assert not _wt_dir(p, "featx", str(Path(base)/"wt")).exists()   # RIEN créé
            assert len(hub._rooms[sess.id].pending_worktrees) == 1
    asyncio.run(scenario())


def test_approve_worktree_creates_child_session():
    import tempfile, subprocess
    from pathlib import Path
    sys.path.insert(0, str(ROOT / "tests")); from fakes import FakeToolLLM
    sys.path.insert(0, str(ROOT / "packages" / "mekicore")); import tools
    from mekihub.hub import SessionHub
    from mekihub.projects import ProjectRegistry, _wt_dir
    from mekihub.session import Author, SessionStore
    async def scenario():
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as repo:
            subprocess.run(["git","init","-q"], cwd=repo, check=True)
            subprocess.run(["git","commit","--allow-empty","-q","-m","init"], cwd=repo,
                           env={**os.environ,"GIT_AUTHOR_NAME":"t","GIT_AUTHOR_EMAIL":"t@t",
                                "GIT_COMMITTER_NAME":"t","GIT_COMMITTER_EMAIL":"t@t"}, check=True)
            reg = ProjectRegistry(path=str(Path(base)/"p.json"), worktrees_base=str(Path(base)/"wt"))
            p = reg.register(repo, name="proj")
            store = SessionStore(directory=str(Path(base)/"sess"))
            sess = store.create(model="m", system="sys", project_id=p.id, scope="main")
            llm = FakeToolLLM(tool_name="spawn_worktree",
                              tool_args={"nom":"featx","prompt_amorce":"code la feature X"}, final="ok")
            hub = SessionHub(store=store, llm_factory=lambda: llm, tools=tools.TOOLS,
                             dispatch_factory=tools.make_dispatch, registry=reg)
            sub = hub.subscribe(sess.id); await sub.__anext__()
            async def collect():
                async for e in sub:
                    if type(e).__name__ == "Idle": break
            t = asyncio.create_task(collect())
            hub.submit(sess.id, "fais la feature X", author=Author(id="c",name="a",color="#fff"))
            await asyncio.wait_for(t, timeout=5)
            pid = next(iter(hub._rooms[sess.id].pending_worktrees))
            child_id = await hub.approve_worktree(sess.id, pid)
            assert child_id
            assert _wt_dir(p, "featx", str(Path(base)/"wt")).exists()
            assert pid not in hub._rooms[sess.id].pending_worktrees
            child = store.load(child_id)
            assert child.scope == "featx" and child.project_id == p.id
            # le worker enfant ajoute le prompt d'amorçage en asynchrone → poll
            found = False
            for _ in range(100):
                c = store.load(child_id)
                if any(m.get("role")=="user" and "feature X" in (m.get("content") or "") for m in c.messages):
                    found = True; break
                await asyncio.sleep(0.02)
            assert found, "le prompt d'amorçage doit devenir le 1er message user de l'enfant"
    asyncio.run(scenario())


def test_reject_worktree_creates_nothing():
    import tempfile, subprocess
    from pathlib import Path
    sys.path.insert(0, str(ROOT / "tests")); from fakes import FakeToolLLM
    sys.path.insert(0, str(ROOT / "packages" / "mekicore")); import tools
    from mekihub.hub import SessionHub
    from mekihub.projects import ProjectRegistry, _wt_dir
    from mekihub.session import Author, SessionStore
    async def scenario():
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as repo:
            subprocess.run(["git","init","-q"], cwd=repo, check=True)
            reg = ProjectRegistry(path=str(Path(base)/"p.json"), worktrees_base=str(Path(base)/"wt"))
            p = reg.register(repo, name="proj")
            store = SessionStore(directory=str(Path(base)/"sess"))
            sess = store.create(model="m", system="sys", project_id=p.id, scope="main")
            llm = FakeToolLLM(tool_name="spawn_worktree",
                              tool_args={"nom":"featy","prompt_amorce":"x"}, final="ok")
            hub = SessionHub(store=store, llm_factory=lambda: llm, tools=tools.TOOLS,
                             dispatch_factory=tools.make_dispatch, registry=reg)
            sub = hub.subscribe(sess.id); await sub.__anext__()
            async def collect():
                async for e in sub:
                    if type(e).__name__ == "Idle": break
            t = asyncio.create_task(collect())
            hub.submit(sess.id, "go", author=Author(id="c",name="a",color="#fff"))
            await asyncio.wait_for(t, timeout=5)
            pid = next(iter(hub._rooms[sess.id].pending_worktrees))
            assert hub.reject_worktree(sess.id, pid) is True
            assert pid not in hub._rooms[sess.id].pending_worktrees
            assert not _wt_dir(p, "featy", str(Path(base)/"wt")).exists()
    asyncio.run(scenario())


def test_reconcile_creates_missing_channels():
    import tempfile, subprocess
    from pathlib import Path
    from mekihub.adapters.discord import DiscordProvisioner, FakeDiscordClient
    from mekihub.projects import ProjectRegistry
    from mekihub.session import SessionStore
    async def scenario():
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as repo:
            subprocess.run(["git","init","-q"], cwd=repo, check=True)
            reg = ProjectRegistry(path=str(Path(base)/"p.json"))
            p = reg.register(repo, name="proj")
            store = SessionStore(directory=str(Path(base)/"sess"))
            store.create(model="m", project_id=p.id, scope="main")
            store.create(model="m", project_id=p.id, scope="main")
            client = FakeDiscordClient()
            prov = DiscordProvisioner(registry=reg, client=client, guild_id="g1")
            mapping = {}
            n = await prov.reconcile(store, mapping=mapping)
            assert n == 2 and client.channel_count() >= 2
            assert len(mapping) == 2                     # mapping canal→session rempli en un seul scan
            assert await prov.reconcile(store) == 0     # idempotent : tout est déjà posé
    asyncio.run(scenario())


def test_discord_antiecho_on_messageposted():
    sys.path.insert(0, str(ROOT / "tests")); from fakes import FakeLLM
    from mekihub.hub import SessionHub
    from mekihub.session import SessionStore
    from mekihub.adapters.discord import DiscordAdapter, FakeDiscordClient, FakeMessage
    async def scenario():
        store = SessionStore(directory=str(ROOT / ".sessions"))
        sess = store.create(model="m", system="sys")
        hub = SessionHub(store=store, llm_factory=lambda: FakeLLM(reply="ok"), tools=[], dispatch={})
        client = FakeDiscordClient()
        adapter = DiscordAdapter(hub=hub, client=client, channel_session={"chan1": sess.id})
        await adapter.handle_message(FakeMessage(channel_id="chan1", author_name="dom",
                                     author_id="42", is_bot=False, content="depuis discord"))
        await asyncio.sleep(0.3); await adapter.flush()
        texts = client.sent_texts()
        # anti-écho : le message né dans chan1 n'est PAS reposté dans chan1
        assert all("depuis discord" not in t for t in texts), texts
        assert any("ok" in t for t in texts)     # la réponse de l'agent est postée
        store.delete(sess.id)
    asyncio.run(scenario())


def test_provisioner_creates_categories_and_channels_idempotent():
    import tempfile, subprocess
    from pathlib import Path
    from mekihub.adapters.discord import DiscordProvisioner, FakeDiscordClient
    from mekihub.projects import ProjectRegistry
    from mekihub.session import Session
    async def scenario():
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as repo:
            subprocess.run(["git","init","-q"], cwd=repo, check=True)
            reg = ProjectRegistry(path=str(Path(base)/"p.json"))
            p = reg.register(repo, name="Mekipedia")
            client = FakeDiscordClient()
            prov = DiscordProvisioner(registry=reg, client=client, guild_id="g1")
            await prov.ensure_project(p)
            p2 = reg.get(p.id)
            assert p2.discord["cat_main"] and p2.discord["cat_worktrees"]
            cats_before = client.category_count()
            await prov.ensure_project(p)                     # idempotent
            assert client.category_count() == cats_before    # pas de doublon
            s = Session(id="s1", title="rev auth", model="m", created_at="t",
                        project_id=p.id, scope="main")
            ch = await prov.ensure_channel(s)
            assert ch and s.discord_channel_id == ch
            assert client.channel_name(ch).startswith("main-")
            ch_again = await prov.ensure_channel(s)           # idempotent (canal déjà posé)
            assert ch_again == ch and client.channel_count() == 1
            sw = Session(id="s2", title="t", model="m", created_at="t",
                         project_id=p.id, scope="featx")
            chw = await prov.ensure_channel(sw)
            assert client.channel_name(chw).startswith("featx-")
    asyncio.run(scenario())


def test_workspace_for_falls_back_when_worktree_missing():
    """Une session dont le scope ne correspond à aucun worktree sur disque retombe sur la racine
    projet (cwd toujours valide) — évite le WinError 267 quand bash s'exécute."""
    import tempfile, subprocess
    from pathlib import Path
    from mekihub.projects import ProjectRegistry, workspace_for
    from mekihub.session import Session
    with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as repo:
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        reg = ProjectRegistry(path=str(Path(base) / "p.json"), worktrees_base=str(Path(base) / "wt"))
        p = reg.register(repo, name="proj")
        s = Session(id="s1", title="t", model="m", created_at="t",
                    project_id=p.id, scope="worktrees")     # aucun worktree "worktrees" créé
        assert workspace_for(s, reg) == Path(repo).resolve()


def test_discord_renders_tool_calls():
    """Les appels d'outils (ToolStarted/ToolFinished) apparaissent dans le canal Discord."""
    sys.path.insert(0, str(ROOT / "tests")); from fakes import FakeToolLLM
    from mekihub.hub import SessionHub
    from mekihub.session import SessionStore
    from mekihub.adapters.discord import DiscordAdapter, FakeDiscordClient, FakeMessage
    async def scenario():
        store = SessionStore(directory=str(ROOT / ".sessions"))
        sess = store.create(model="m", system="sys")
        dispatch = {"echo": lambda a: "resultat-echo-XYZ"}
        hub = SessionHub(store=store, llm_factory=lambda: FakeToolLLM(
            tool_name="echo", tool_args={"x": "hi"}, final="termine"),
            tools=[], dispatch=dispatch)
        client = FakeDiscordClient()
        adapter = DiscordAdapter(hub=hub, client=client, channel_session={"chan1": sess.id})
        await adapter.handle_message(FakeMessage(channel_id="chan1", author_name="dom",
                                     author_id="42", is_bot=False, content="go"))
        await asyncio.sleep(0.3); await adapter.flush()
        texts = client.sent_texts()
        assert any("echo" in t for t in texts), texts                 # en-tête de l'outil
        assert any("resultat-echo-XYZ" in t for t in texts), texts    # sortie de l'outil
        assert any("termine" in t for t in texts), texts              # réponse finale
        store.delete(sess.id)
    asyncio.run(scenario())


def test_tool_embed_color_per_tool():
    """Chaque type d'outil a une couleur distincte ; une erreur vire au rouge."""
    from mekihub.adapters.discord import _tool_embed
    assert _tool_embed("bash", "ls", "ok", "x")["color"] != _tool_embed("read", "f", "ok", "x")["color"]
    assert _tool_embed("write", "f", "ok", "x")["color"] != _tool_embed("edit", "f", "ok", "x")["color"]
    assert _tool_embed("bash", "ls", "err", "Error")["color"] == 0xFF3B3B   # erreur = rouge
    assert _tool_embed("inconnu", "x", "ok", "x")["color"] == 0x8899AA      # repli outil inconnu


def test_discord_renders_tool_calls_as_embed():
    """En mode tool_style='embed', l'appel d'outil apparaît comme une carte (embed) avec sa sortie."""
    sys.path.insert(0, str(ROOT / "tests")); from fakes import FakeToolLLM
    from mekihub.hub import SessionHub
    from mekihub.session import SessionStore
    from mekihub.adapters.discord import DiscordAdapter, FakeDiscordClient, FakeMessage
    async def scenario():
        store = SessionStore(directory=str(ROOT / ".sessions"))
        sess = store.create(model="m", system="sys")
        dispatch = {"echo": lambda a: "resultat-embed-XYZ"}
        hub = SessionHub(store=store, llm_factory=lambda: FakeToolLLM(
            tool_name="echo", tool_args={"x": "hi"}, final="termine"),
            tools=[], dispatch=dispatch)
        client = FakeDiscordClient()
        adapter = DiscordAdapter(hub=hub, client=client, channel_session={"chan1": sess.id},
                                 tool_style="embed")
        await adapter.handle_message(FakeMessage(channel_id="chan1", author_name="dom",
                                     author_id="42", is_bot=False, content="go"))
        await asyncio.sleep(0.3); await adapter.flush()
        embeds = client.sent_embeds()
        assert embeds, "au moins une carte embed attendue"
        assert any("echo" in (e.get("title") or "") for e in embeds), embeds
        field_vals = [f["value"] for e in embeds for f in e.get("fields", [])]
        assert any("resultat-embed-XYZ" in v for v in field_vals), field_vals
        store.delete(sess.id)
    asyncio.run(scenario())


def test_discord_agent_reply_references_question():
    """La réponse de l'agent référence (reply) le message Discord de la question."""
    sys.path.insert(0, str(ROOT / "tests")); from fakes import FakeLLM
    from mekihub.hub import SessionHub
    from mekihub.session import SessionStore
    from mekihub.adapters.discord import DiscordAdapter, FakeDiscordClient, FakeMessage
    async def scenario():
        store = SessionStore(directory=str(ROOT / ".sessions"))
        sess = store.create(model="m", system="sys")
        hub = SessionHub(store=store, llm_factory=lambda: FakeLLM(reply="voici la reponse"),
                         tools=[], dispatch={})
        client = FakeDiscordClient()
        adapter = DiscordAdapter(hub=hub, client=client, channel_session={"chan1": sess.id})
        await adapter.handle_message(FakeMessage(channel_id="chan1", author_name="dom",
                                     author_id="42", is_bot=False, content="salut", message_id="MSG_Q"))
        await asyncio.sleep(0.3); await adapter.flush()
        replied = [m for m in client._messages
                   if m.get("reply_to") == "MSG_Q" and "voici la reponse" in (m.get("text") or "")]
        assert replied, client._messages
        store.delete(sess.id)
    asyncio.run(scenario())


def test_discord_queue_shows_pending():
    """Un 2e message envoyé pendant un run en cours apparaît dans l'embed « file d'attente »."""
    sys.path.insert(0, str(ROOT / "tests")); from fakes import FakeLLM
    from mekihub.hub import SessionHub
    from mekihub.session import SessionStore
    from mekihub.adapters.discord import DiscordAdapter, FakeDiscordClient, FakeMessage
    async def scenario():
        store = SessionStore(directory=str(ROOT / ".sessions"))
        sess = store.create(model="m", system="sys")
        hub = SessionHub(store=store, llm_factory=lambda: FakeLLM(reply="ok", delay=0.3),
                         tools=[], dispatch={})
        client = FakeDiscordClient()
        adapter = DiscordAdapter(hub=hub, client=client, channel_session={"chan1": sess.id})
        await adapter.handle_message(FakeMessage(channel_id="chan1", author_name="alice",
                                     author_id="u1", is_bot=False, content="premier"))
        await asyncio.sleep(0.08)        # le 1er run est en cours
        await adapter.handle_message(FakeMessage(channel_id="chan1", author_name="bob",
                                     author_id="u2", is_bot=False, content="deuxieme"))
        await asyncio.sleep(0.08)        # le 2e est en file d'attente
        qembeds = [e for e in client.sent_embeds() if "attente" in (e.get("title") or "")]
        assert qembeds, ("pas d'embed file d'attente", client.sent_embeds())
        assert any("deuxieme" in str(e) for e in qembeds), qembeds
        await adapter.flush()
        store.delete(sess.id)
    asyncio.run(scenario())


def test_approve_worktree_failure_is_graceful():
    """B1 : si git worktree add échoue (branche déjà prise), approve_worktree ne crash pas,
    retire la proposition, publie WorktreeRejected + RunError, et renvoie None (never-raise)."""
    import tempfile, subprocess
    from pathlib import Path
    sys.path.insert(0, str(ROOT / "tests")); from fakes import FakeToolLLM
    sys.path.insert(0, str(ROOT / "packages" / "mekicore")); import tools
    from mekihub.hub import SessionHub
    from mekihub.projects import ProjectRegistry, add_worktree
    from mekihub.session import Author, SessionStore
    async def scenario():
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as repo:
            subprocess.run(["git","init","-q"], cwd=repo, check=True)
            subprocess.run(["git","commit","--allow-empty","-q","-m","init"], cwd=repo,
                           env={**os.environ,"GIT_AUTHOR_NAME":"t","GIT_AUTHOR_EMAIL":"t@t",
                                "GIT_COMMITTER_NAME":"t","GIT_COMMITTER_EMAIL":"t@t"}, check=True)
            reg = ProjectRegistry(path=str(Path(base)/"p.json"), worktrees_base=str(Path(base)/"wt"))
            p = reg.register(repo, name="proj")
            add_worktree(p, "dup", None, str(Path(base)/"wt"))     # la branche "dup" existe déjà
            store = SessionStore(directory=str(Path(base)/"sess"))
            sess = store.create(model="m", system="sys", project_id=p.id, scope="main")
            llm = FakeToolLLM(tool_name="spawn_worktree",
                              tool_args={"nom":"dup","prompt_amorce":"x"}, final="ok")
            hub = SessionHub(store=store, llm_factory=lambda: llm, tools=tools.TOOLS,
                             dispatch_factory=tools.make_dispatch, registry=reg)
            sub = hub.subscribe(sess.id); await sub.__anext__()
            async def collect():
                async for e in sub:
                    if type(e).__name__ == "Idle": break
            t = asyncio.create_task(collect())
            hub.submit(sess.id, "go", author=Author(id="c",name="a",color="#fff"))
            await asyncio.wait_for(t, timeout=5)
            pid = next(iter(hub._rooms[sess.id].pending_worktrees))
            # un abonné frais pour capter WorktreeRejected/RunError publiés pendant l'approbation
            got = []
            sub2 = hub.subscribe(sess.id); await sub2.__anext__()
            async def collect2():
                async for e in sub2:
                    got.append(type(e).__name__)
                    if "RunError" in got: break
            t2 = asyncio.create_task(collect2())
            await asyncio.sleep(0.02)
            res = await hub.approve_worktree(sess.id, pid)        # git échoue → gracieux
            await asyncio.wait_for(t2, timeout=5)
            assert res is None
            assert pid not in hub._rooms[sess.id].pending_worktrees
            assert "WorktreeRejected" in got and "RunError" in got
    asyncio.run(scenario())


if __name__ == "__main__":
    test_author_and_queueitem()
    test_session_authors_separate_from_messages()
    test_events_exist()
    test_pending_queue_fifo_and_delete()
    test_hub_submit_run_and_subscribe()
    test_two_subscribers_and_queue_delete()
    test_discord_adapter_with_fake_client()
    test_main_importable()
    test_project_registry_crud()
    test_register_rejects_non_git()
    test_workspace_for_main_and_worktree()
    test_session_project_fields_and_filtered_list()
    test_legacy_session_defaults_to_mekicode_project()
    test_author_has_source_default_none()
    test_hub_uses_per_session_workspace()
    test_spawn_worktree_proposes_without_creating()
    test_approve_worktree_creates_child_session()
    test_reject_worktree_creates_nothing()
    test_provisioner_creates_categories_and_channels_idempotent()
    test_discord_antiecho_on_messageposted()
    test_reconcile_creates_missing_channels()
    test_workspace_for_falls_back_when_worktree_missing()
    test_discord_renders_tool_calls()
    test_tool_embed_color_per_tool()
    test_discord_renders_tool_calls_as_embed()
    test_discord_queue_shows_pending()
    test_discord_agent_reply_references_question()
    test_approve_worktree_failure_is_graceful()
    print("OK - tous les smoke mekihub passent")
