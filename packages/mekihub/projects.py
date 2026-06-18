"""projects.py — registre de projets (dépôts git externes), worktrees, résolution de workspace."""
from __future__ import annotations
import json, re, shutil, subprocess, sys, uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_REGISTRY = _ROOT / ".mekicode" / "projects.json"

def _now() -> str: return datetime.now(timezone.utc).isoformat()

def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9_]+", "-", name.lower()).strip("-_")   # underscore préservé (suffixe _uuid)
    return s or "projet"

@dataclass
class Project:
    id: str
    slug: str
    name: str
    repo_path: str
    default_branch: str = "main"
    discord: dict = field(default_factory=dict)
    created_at: str = ""

def _is_git_repo(path: Path) -> bool:
    if (path / ".git").exists():
        return True
    if not path.is_dir():
        return False
    r = subprocess.run(["git","-C",str(path),"rev-parse","--is-inside-work-tree"],
                       capture_output=True, text=True)
    return r.stdout.strip() == "true"

def _current_branch(path: Path) -> str:
    r = subprocess.run(["git","-C",str(path),"rev-parse","--abbrev-ref","HEAD"],
                       capture_output=True, text=True)
    b = r.stdout.strip()
    return b if b and b != "HEAD" else "main"

class ProjectRegistry:
    def __init__(self, path=None, worktrees_base=None):
        self.path = Path(path or _DEFAULT_REGISTRY)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # None => worktrees à la racine du projet (<repo>/.worktrees/) ; sinon override explicite
        self.worktrees_base = Path(worktrees_base) if worktrees_base else None
        self._projects: dict[str, Project] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for d in data.get("projects", []):
                self._projects[d["id"]] = Project(**d)

    def _save(self):
        data = {"projects": [asdict(p) for p in self._projects.values()]}
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def register(self, repo_path, name=None) -> Project:
        root = Path(repo_path).resolve()
        if not _is_git_repo(root):
            raise ValueError(f"pas un dépôt git : {repo_path}")
        name = name or root.name
        slug = slugify(name)
        pid = "p_" + uuid.uuid4().hex[:6]
        p = Project(id=pid, slug=slug, name=name, repo_path=str(root),
                    default_branch=_current_branch(root), created_at=_now())
        self._projects[pid] = p; self._save(); return p

    def list(self): return list(self._projects.values())
    def get(self, pid): return self._projects.get(pid)
    def get_by_slug(self, slug):
        return next((p for p in self._projects.values() if p.slug == slug), None)
    def remove(self, pid):
        self._projects.pop(pid, None); self._save()
    def update(self, p: Project):
        self._projects[p.id] = p; self._save()

    def ensure_default(self) -> Project:
        p = self.get_by_slug("mekicode")
        if p is None:
            p = Project(id="mekicode", slug="mekicode", name="mekicode",
                        repo_path=str(_ROOT), default_branch="main", created_at=_now())
            self._projects[p.id] = p; self._save()
        return p

_DEFAULT_COPY_IGNORED = (".env", ".env.local", ".env.development", ".env.production", ".env.test")

def _git(repo, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)

def _branch_exists(repo, branch: str) -> bool:
    return _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0

def _is_ignored(repo, rel: str) -> bool:
    """True si `rel` est ignoré par git dans `repo` (gitignore OU .git/info/exclude)."""
    return _git(repo, "check-ignore", "-q", "--", rel).returncode == 0

def _wt_dir(project: Project, name: str, worktrees_base=None) -> Path:
    """Emplacement d'un worktree. Défaut : `<repo>/.worktrees/<slug>` (racine DU projet).
    `worktrees_base` (override) : `<base>/<slug-projet>/<slug>` (emplacement externe ; tests)."""
    if worktrees_base:
        return (Path(worktrees_base) / project.slug / slugify(name)).resolve()
    return (Path(project.repo_path) / ".worktrees" / slugify(name)).resolve()

def _ensure_worktrees_excluded(repo_root: Path) -> None:
    """Garantit que `.worktrees/` est ignoré SANS toucher au `.gitignore` SUIVI : si ce n'est pas déjà
    le cas (gitignore du projet), on l'ajoute à `.git/info/exclude` (exclusion locale, non versionnée).
    No-op si déjà ignoré — ne salit donc jamais le working tree d'un dépôt tiers."""
    if _is_ignored(repo_root, ".worktrees/"):
        return
    gp = _git(repo_root, "rev-parse", "--git-path", "info/exclude")
    exclude = Path(gp.stdout.strip() or ".git/info/exclude")
    if not exclude.is_absolute():
        exclude = repo_root / exclude
    try:
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if any(ln.strip().strip("/") == ".worktrees" for ln in existing.splitlines()):
            return
        exclude.parent.mkdir(parents=True, exist_ok=True)
        sep = "" if (existing == "" or existing.endswith("\n")) else "\n"
        with exclude.open("a", encoding="utf-8") as f:
            f.write(f"{sep}.worktrees/\n")
    except OSError as e:
        print(f"[mekihub] avertissement : exclusion .worktrees/ impossible ({e!r})", file=sys.stderr)

def _copy_ignored_files(repo_root: Path, target: Path, names) -> list:
    """Copie dans le worktree les fichiers que `git worktree add` ne checkout PAS : uniquement les
    fichiers réellement GITIGNORÉS (ex. .env). On ignore les fichiers suivis (déjà checkout — ne pas
    les écraser) et les non-ignorés (ne pas introduire de secret committable). Renvoie les fichiers copiés."""
    copied, errors = [], []
    for rel in (names or ()):
        src = repo_root / rel
        if not src.is_file() or not _is_ignored(repo_root, rel):
            continue
        dst = target / rel
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(rel)
        except OSError as e:
            errors.append((rel, e))
    for rel, e in errors:                 # jamais silencieux : la copie de .env est critique
        print(f"[mekihub] avertissement : échec copie {rel} → worktree ({e!r})", file=sys.stderr)
    return copied

def add_worktree(project: Project, name: str, base=None, worktrees_base=None,
                 copy_ignored=_DEFAULT_COPY_IGNORED) -> Path:
    repo_root = Path(project.repo_path)
    target = _wt_dir(project, name, worktrees_base)
    target.parent.mkdir(parents=True, exist_ok=True)
    branch = slugify(name)
    if _branch_exists(repo_root, branch):
        cmd = ["git", "-C", str(repo_root), "worktree", "add", str(target), branch]   # réutilise la branche
    else:
        cmd = ["git", "-C", str(repo_root), "worktree", "add", str(target), "-b", branch]
        if base:
            cmd.append(base)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git worktree add a échoué : {r.stderr.strip()}")
    if not worktrees_base:                # worktrees in-repo → garantir qu'ils sont ignorés (sans salir git)
        _ensure_worktrees_excluded(repo_root)
    _copy_ignored_files(repo_root, target, copy_ignored)   # .env & co (gitignorés)
    return target

def list_worktrees(project: Project) -> list[dict]:
    r = subprocess.run(["git","-C",project.repo_path,"worktree","list","--porcelain"],
                       capture_output=True, text=True)
    out, cur = [], {}
    for line in r.stdout.splitlines():
        if line.startswith("worktree "): cur = {"path": line[9:]}
        elif line.startswith("branch "): cur["branch"] = line[7:]; out.append(cur)
        elif line == "" and cur: cur = {}
    return out

def remove_worktree(project: Project, name: str, worktrees_base=None, delete_branch: bool = True):
    """Retire le worktree ET (par défaut) sa branche, pour rendre le cycle create/remove/create idempotent."""
    repo_root = Path(project.repo_path)
    target = _wt_dir(project, name, worktrees_base)
    _git(repo_root, "worktree", "remove", "--force", str(target))
    _git(repo_root, "worktree", "prune")                       # nettoie les métadonnées orphelines
    if delete_branch:
        _git(repo_root, "branch", "-D", slugify(name))         # échec ignoré (branche absente / checkout ailleurs)

def workspace_for(session, registry) -> Path:
    project = registry.get(getattr(session, "project_id", None)) if registry else None
    if project is None:
        return _ROOT
    if getattr(session, "scope", "main") == "main":
        return Path(project.repo_path).resolve()
    wt = _wt_dir(project, session.scope, registry.worktrees_base)
    # repli sur la racine du projet si le worktree n'existe pas sur le disque (cwd toujours valide)
    return wt if wt.exists() else Path(project.repo_path).resolve()
