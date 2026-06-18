"""smoke_worktree_copy — worktrees à la racine du projet (<repo>/.worktrees/<nom>) :
- copie des fichiers RÉELLEMENT gitignorés (.env) que git worktree ne checkout pas ;
- exclusion via .git/info/exclude (local) SANS salir le .gitignore suivi ;
- fichier suivi (gabarit .env.test versionné) NON écrasé ;
- workspace_for résout vers le worktree in-repo ;
- cycle create → remove → recreate du même nom (branche supprimée au remove) ;
- override worktrees_base (emplacement externe, .gitignore/exclude intacts).
Réseau-free, sans clé API.
"""
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "mekihub"))

from projects import (ProjectRegistry, add_worktree, remove_worktree, workspace_for,  # noqa: E402
                      _wt_dir, _is_ignored)


def _git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          check=check)


def _init_repo(repo: Path, gitignore=".env\n"):
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("# repo\n", encoding="utf-8")
    (repo / ".gitignore").write_text(gitignore, encoding="utf-8")
    _git(repo, "add", "README.md", ".gitignore")
    _git(repo, "commit", "-m", "init")


def test_inrepo_copy_env_and_local_exclude():
    with tempfile.TemporaryDirectory() as base:
        repo = Path(base) / "monprojet"
        _init_repo(repo)
        (repo / ".env").write_text("SECRET=42\n", encoding="utf-8")        # gitignoré
        gi_before = (repo / ".gitignore").read_text(encoding="utf-8")

        reg = ProjectRegistry(path=str(Path(base) / "p.json"))
        assert reg.worktrees_base is None
        proj = reg.register(str(repo), name="monprojet")

        target = add_worktree(proj, "ma-feature")

        assert target == (repo / ".worktrees" / "ma-feature").resolve()
        assert target.exists() and (target / "README.md").exists()
        # .env (gitignoré) copié à l'identique
        assert (target / ".env").read_text(encoding="utf-8") == "SECRET=42\n"
        # le .gitignore SUIVI n'est PAS modifié (pas de working tree sali)
        assert (repo / ".gitignore").read_text(encoding="utf-8") == gi_before
        assert _git(repo, "status", "--porcelain").stdout.strip() == "", "working tree sali !"
        # .worktrees/ ignoré via .git/info/exclude (local)
        excl = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        assert ".worktrees/" in excl
        assert _is_ignored(repo, ".worktrees/")
        # .env reste ignoré DANS le worktree (pas de secret committable)
        assert _is_ignored(target, ".env")
    print("OK inrepo_copy_env_and_local_exclude")


def test_tracked_template_not_overwritten():
    """Un .env.test VERSIONNÉ (gabarit) ne doit pas être écrasé par la version du working tree parent."""
    with tempfile.TemporaryDirectory() as base:
        repo = Path(base) / "p"
        _init_repo(repo)
        (repo / ".env.test").write_text("TRACKED=v1\n", encoding="utf-8")
        _git(repo, "add", ".env.test")
        _git(repo, "commit", "-m", "track env.test")
        (repo / ".env.test").write_text("WORKING=v2\n", encoding="utf-8")   # modif parent non commitée
        reg = ProjectRegistry(path=str(Path(base) / "p.json"))
        proj = reg.register(str(repo))
        target = add_worktree(proj, "feat")
        # le worktree garde la version CHECKOUT (HEAD), pas la copie parent
        assert (target / ".env.test").read_text(encoding="utf-8") == "TRACKED=v1\n"
        assert _git(target, "status", "--porcelain").stdout.strip() == "", "worktree sali par la copie"
    print("OK tracked_template_not_overwritten")


def test_workspace_for_inrepo():
    with tempfile.TemporaryDirectory() as base:
        repo = Path(base) / "p"
        _init_repo(repo)
        reg = ProjectRegistry(path=str(Path(base) / "p.json"))
        proj = reg.register(str(repo))
        add_worktree(proj, "Ma Feature")          # slug -> ma-feature
        s_main = SimpleNamespace(project_id=proj.id, scope="main")
        s_wt = SimpleNamespace(project_id=proj.id, scope="Ma Feature")
        assert workspace_for(s_main, reg) == Path(repo).resolve()
        assert workspace_for(s_wt, reg) == (repo / ".worktrees" / "ma-feature").resolve()
    print("OK workspace_for_inrepo")


def test_create_remove_recreate_cycle():
    with tempfile.TemporaryDirectory() as base:
        repo = Path(base) / "p"
        _init_repo(repo)
        reg = ProjectRegistry(path=str(Path(base) / "p.json"))
        proj = reg.register(str(repo))
        t1 = add_worktree(proj, "cyc")
        assert t1.exists()
        remove_worktree(proj, "cyc")              # supprime worktree + branche
        assert not t1.exists()
        assert not _branch_listed(repo, "cyc"), "branche orpheline après remove"
        t2 = add_worktree(proj, "cyc")            # recréation du même nom : ne doit PAS échouer
        assert t2.exists()
    print("OK create_remove_recreate_cycle")


def test_override_base_untouched_gitignore():
    with tempfile.TemporaryDirectory() as base:
        repo = Path(base) / "p"
        _init_repo(repo)
        (repo / ".env").write_text("K=1\n", encoding="utf-8")
        gi_before = (repo / ".gitignore").read_text(encoding="utf-8")
        ext = Path(base) / "wt"
        reg = ProjectRegistry(path=str(Path(base) / "p.json"), worktrees_base=str(ext))
        proj = reg.register(str(repo))
        target = add_worktree(proj, "ext", worktrees_base=str(ext))
        assert target == (ext / proj.slug / "ext").resolve()
        assert (target / ".env").read_text(encoding="utf-8") == "K=1\n"     # .env copié quand même
        assert (repo / ".gitignore").read_text(encoding="utf-8") == gi_before
        excl = repo / ".git" / "info" / "exclude"
        assert (not excl.exists()) or ".worktrees/" not in excl.read_text(encoding="utf-8")
    print("OK override_base_untouched_gitignore")


def _branch_listed(repo, branch):
    out = _git(repo, "branch", "--list", branch, check=False).stdout
    return branch in out


if __name__ == "__main__":
    test_inrepo_copy_env_and_local_exclude()
    test_tracked_template_not_overwritten()
    test_workspace_for_inrepo()
    test_create_remove_recreate_cycle()
    test_override_base_untouched_gitignore()
    print("OK smoke_worktree_copy")
