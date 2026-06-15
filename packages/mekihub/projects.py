"""projects.py — registre de projets (dépôts git externes), worktrees, résolution de workspace."""
from __future__ import annotations
import json, re, subprocess, uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_REGISTRY = _ROOT / ".mekicode" / "projects.json"
_DEFAULT_WT_BASE = _ROOT / ".mekicode-worktrees"

def _now() -> str: return datetime.now(timezone.utc).isoformat()

def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
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
        self.worktrees_base = Path(worktrees_base or _DEFAULT_WT_BASE)
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

def _wt_dir(project: Project, name: str, worktrees_base=None) -> Path:
    base = Path(worktrees_base or _DEFAULT_WT_BASE)
    return (base / project.slug / slugify(name)).resolve()

def add_worktree(project: Project, name: str, base=None, worktrees_base=None) -> Path:
    target = _wt_dir(project, name, worktrees_base)
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git","-C",project.repo_path,"worktree","add", str(target), "-b", slugify(name)]
    if base: cmd.append(base)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git worktree add a échoué : {r.stderr.strip()}")
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

def remove_worktree(project: Project, name: str, worktrees_base=None):
    target = _wt_dir(project, name, worktrees_base)
    subprocess.run(["git","-C",project.repo_path,"worktree","remove","--force",str(target)],
                   capture_output=True, text=True)

def workspace_for(session, registry) -> Path:
    project = registry.get(getattr(session, "project_id", None)) if registry else None
    if project is None:
        return _ROOT
    if getattr(session, "scope", "main") == "main":
        return Path(project.repo_path).resolve()
    return _wt_dir(project, session.scope, registry.worktrees_base)
