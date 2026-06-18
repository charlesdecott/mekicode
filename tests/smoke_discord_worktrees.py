"""smoke_discord_worktrees — Discord par worktree (réseau-free, FakeDiscordClient) :
- UNE catégorie « 🌳 <nom> » par worktree, un canal par session dedans (main → catégorie main) ;
- suppression du canal d'une session ;
- `hub.delete_worktree` : supprime les sessions du worktree, leurs canaux, et la catégorie ;
- garde-fou : on ne supprime jamais 'main'.
"""
import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))
sys.path.insert(0, str(ROOT / "packages" / "mekicore"))

from fakes import init_git_repo                            # noqa: E402
from mekihub.projects import ProjectRegistry               # noqa: E402
from mekihub.session import SessionStore                   # noqa: E402
from mekihub.adapters.discord import (DiscordProvisioner, FakeDiscordClient,  # noqa: E402
                                      _wt_category_name)


def _repo(base):
    repo = Path(base) / "proj"
    repo.mkdir()
    init_git_repo(repo, commit=True)
    return repo


async def _scenario():
    with tempfile.TemporaryDirectory() as base:
        repo = _repo(base)
        reg = ProjectRegistry(path=str(Path(base) / "p.json"), worktrees_base=str(Path(base) / "wt"))
        proj = reg.register(str(repo), name="proj")
        store = SessionStore(directory=str(Path(base) / "sess"))
        client = FakeDiscordClient()
        prov = DiscordProvisioner(registry=reg, client=client)

        # main → catégorie main
        s_main = store.create(model="m", project_id=proj.id, scope="main")
        await prov.ensure_channel(s_main); store.save(s_main)

        # worktree feat-a : 2 sessions → MÊME catégorie, 2 canaux ; feat-b : 1 session → AUTRE catégorie
        a1 = store.create(model="m", project_id=proj.id, scope="feat-a_aaa111")
        a2 = store.create(model="m", project_id=proj.id, scope="feat-a_aaa111")
        b1 = store.create(model="m", project_id=proj.id, scope="feat-b_bbb222")
        cha1 = await prov.ensure_channel(a1); store.save(a1)
        cha2 = await prov.ensure_channel(a2); store.save(a2)
        await prov.ensure_channel(b1); store.save(b1)

        proj = reg.get(proj.id)
        wt_cats = proj.discord["wt_cats"]
        assert set(wt_cats) == {"feat-a_aaa111", "feat-b_bbb222"}, wt_cats
        cat_a = wt_cats["feat-a_aaa111"]
        assert cat_a != wt_cats["feat-b_bbb222"]                         # une catégorie par worktree
        assert client._channels[cha1][1] == cat_a == client._channels[cha2][1]   # même catégorie
        assert client._categories[cat_a][1] == _wt_category_name("feat-a_aaa111") == "🌳 feat-a"
        assert client._channels[s_main.discord_channel_id][1] == proj.discord["cat_main"]
        assert "cat_worktrees" not in proj.discord

        # suppression du canal d'une session
        await prov.delete_channel(a1)
        assert cha1 in client._deleted_channels and cha1 not in client._channels

        # === hub.delete_worktree (bout en bout) ===
        import tools
        from mekihub.hub import SessionHub
        hub = SessionHub(store=store, llm_factory=lambda: None, tools=tools.TOOLS,
                         dispatch_factory=tools.make_dispatch, registry=reg, provisioner=prov)
        assert {m.id for m in store.list() if m.scope == "feat-a_aaa111"}        # a1, a2 présents
        n = await hub.delete_worktree(proj.id, "feat-a_aaa111")
        assert n == 2
        assert not [m for m in store.list() if m.scope == "feat-a_aaa111"]       # sessions supprimées
        assert cha2 in client._deleted_channels                                  # canal restant supprimé
        proj = reg.get(proj.id)
        assert "feat-a_aaa111" not in proj.discord["wt_cats"]
        assert cat_a in client._deleted_categories

        # garde-fou : on ne supprime jamais 'main'
        assert await hub.delete_worktree(proj.id, "main") == 0
        assert [m for m in store.list() if m.scope == "main"]

    print("OK smoke_discord_worktrees")


if __name__ == "__main__":
    asyncio.run(_scenario())
