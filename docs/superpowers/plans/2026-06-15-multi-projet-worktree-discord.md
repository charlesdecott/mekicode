# Plan d'implémentation — mekicode multi-projet + worktree + Discord

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development pour
> implémenter ce plan tâche par tâche. Les étapes utilisent des cases à cocher (`- [ ]`).

**Goal :** transformer mekichat en orchestrateur multi-projet (dépôts git externes), avec worktree
par chat piloté par l'agent (gated), et miroir Discord (catégories/canaux auto, bidirectionnel).

**Architecture :** extension additive de `packages/mekihub` (Approche A). Le moteur worker/pub-sub par
session reste inchangé ; on ajoute `projects.py` (registre + worktrees + résolution de workspace),
un `dispatch_factory` workspace-aware dans le hub, un outil agent `spawn_worktree` gated par
validation, et un `DiscordProvisioner` idempotent.

**Tech Stack :** Python 3.14, stdlib (json, subprocess, asyncio, dataclasses), `discord.py` (optionnel,
réel uniquement), NiceGUI (front). Tests réseau-free style `__main__` dans `tests/`.

**Conventions du repo (rappel) :**
- Tests = fonctions appelées sous `if __name__ == "__main__"` (PAS pytest), dans `tests/` à la racine.
- `python -m py_compile` sur tout `.py` modifié avant de conclure une tâche.
- Commits : **jamais** le nom de Claude. Messages en français, préfixe `feat:`/`refactor:`/`test:`.
- `packages/` documenté à la main dans `docs/wiki-packages/` (à mettre à jour en fin de phase).
- Décision de stockage : sessions **à plat** dans `.sessions/` avec champs `project_id`/`scope`
  (simplification vs sous-dossiers du spec — garde `load` en O(1)).

---

## Vue des fichiers

| Fichier | Création / Modif | Responsabilité |
|---|---|---|
| `packages/mekihub/projects.py` | **Création** | `Project`, `ProjectRegistry`, helpers `git worktree`, `workspace_for`, `slugify` |
| `packages/mekicore/tools.py` | Modif | `make_dispatch(workspace)`, fonctions fichiers paramétrées par `ws` (back-compat env) |
| `packages/mekihub/session.py` | Modif | `Author.source`, champs `Session.project_id/scope/discord_channel_id`, `SessionStore.create/list` filtrables |
| `packages/mekihub/events.py` | Modif | `MessagePosted.source`, `WorktreeProposed/WorktreeRejected/WorktreeCreated` |
| `packages/mekihub/hub.py` | Modif | `dispatch_factory` + `registry`/`provisioner`, workspace par session, outil `spawn_worktree`, `approve_worktree`/`reject_worktree` |
| `packages/mekihub/adapters/discord.py` | Modif | `DiscordProvisioner`, mirroring bidirectionnel + anti-écho, `FakeDiscordClient` étendu |
| `packages/mekihub/main.py` | Modif | `build_hub()` câble registry + dispatch_factory + provisioner |
| `packages/mekichat/app.py` | Modif | sélecteur Projet→scope→session, hub avec registry, carte de validation worktree |
| `packages/mekichat/views.py` | Modif | rendu sélecteur projet + carte worktree |
| `tests/smoke_mekihub.py` | Modif | + tests projets/worktree/workspace/provisioner |
| `tests/smoke_packages.py` | Modif | + tests `make_dispatch` workspace |
| `docs/wiki-packages/mekihub.md` | Modif | doc des nouveautés |

---

# PHASE P1 — Fondation multi-projet

## Task 1 : `tools.py` workspace explicite (corrige la concurrence)

**Files :**
- Modify: `packages/mekicore/tools.py`
- Test: `tests/smoke_packages.py`

**Problème :** `_workspace()` lit un env global → deux sessions concurrentes dans des cwd différents se
marchent dessus. Solution : workspace explicite, lié par session via `make_dispatch`.

- [ ] **Step 1 — Test (échoue) :** ajouter à `tests/smoke_packages.py` :

```python
def test_make_dispatch_confines_to_workspace():
    import tempfile, os
    from pathlib import Path
    sys.path.insert(0, str(ROOT / "packages" / "mekicore"))
    import tools
    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        (Path(a) / "x.txt").write_text("dans_A", encoding="utf-8")
        (Path(b) / "x.txt").write_text("dans_B", encoding="utf-8")
        da = tools.make_dispatch(Path(a))
        db = tools.make_dispatch(Path(b))
        assert da["read"]({"path": "x.txt"}) == "dans_A"
        assert db["read"]({"path": "x.txt"}) == "dans_B"          # pas de fuite entre workspaces
        assert "hors du workspace" in da["read"]({"path": "../x.txt"})  # confinement
        # bash s'exécute dans le workspace
        out = da["bash"]({"command": "pwd || cd"})
        assert os.path.basename(a) in out or a.replace("\\\\", "/").split("/")[-1] in out
```

- [ ] **Step 2 — Lancer, vérifier l'échec** : `python tests/smoke_packages.py` → AttributeError `make_dispatch`.

- [ ] **Step 3 — Implémentation.** Refactor : chaque fonction fichier prend `ws: Path` ; garder
les fonctions publiques back-compat (`ws=None → _workspace()`). Ajouter :

```python
def _safe_path(p: str, ws: Path) -> Path:
    target = (ws / p).resolve()
    if target != ws and ws not in target.parents:
        raise ValueError(f"chemin hors du workspace : {p}")
    return target

def read_file(path, ws=None):
    ws = ws or _workspace()
    try: p = _safe_path(path, ws)
    except ValueError as e: return f"Error: {e}"
    ...  # idem write/edit/grep/glob : tous prennent ws, défaut _workspace()

def run_bash(command, cwd=None):
    if any(b in command for b in _ALWAYS_BLOCK): return "Error: dangerous command blocked"
    cwd = str(cwd) if cwd else os.getcwd()
    try:
        r = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True, timeout=120)
        ...

def make_dispatch(workspace) -> dict:
    ws = Path(workspace).resolve()
    return {
        "bash":  lambda a: run_bash(a["command"], cwd=ws),
        "read":  lambda a: read_file(a["path"], ws),
        "write": lambda a: write_file(a["path"], a["content"], ws),
        "edit":  lambda a: edit_file(a["path"], a["old"], a["new"], ws),
        "grep":  lambda a: grep_files(a["pattern"], a.get("path", "."), ws),
        "glob":  lambda a: glob_files(a["pattern"], ws),
    }
```

Garder `TOOLS` et le `DISPATCH` global (env-based) inchangés pour le mode standalone.

- [ ] **Step 4 — Lancer, vérifier le succès** : `python tests/smoke_packages.py` → tous OK.
- [ ] **Step 5 — `py_compile`** : `python -m py_compile packages/mekicore/tools.py`.
- [ ] **Step 6 — Commit** : `feat(mekicore): make_dispatch(workspace) — confinement outils par session`.

## Task 2 : `projects.py` — registre + worktrees + workspace_for

**Files :**
- Create: `packages/mekihub/projects.py`
- Test: `tests/smoke_mekihub.py`

- [ ] **Step 1 — Tests (échouent)** dans `tests/smoke_mekihub.py` :

```python
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
        # refus si pas un repo git
        try:
            reg.register(base + "/not_a_repo"); assert False
        except ValueError: pass
        reg.remove(p.id); assert reg.list() == []

def test_register_rejects_non_git():
    import tempfile
    from mekihub.projects import ProjectRegistry
    with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as d:
        reg = ProjectRegistry(path=str(Path(base) / "p.json"))
        try: reg.register(d); assert False, "doit refuser un non-repo"
        except ValueError: pass

def test_workspace_for_main_and_worktree():
    import tempfile, subprocess
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
```

- [ ] **Step 2 — Échec** : `python tests/smoke_mekihub.py` → ImportError `mekihub.projects`.

- [ ] **Step 3 — Implémentation** `packages/mekihub/projects.py` :

```python
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
    discord: dict = field(default_factory=dict)   # {guild_id, cat_main, cat_worktrees}
    created_at: str = ""

def _is_git_repo(path: Path) -> bool:
    return (path / ".git").exists() or (path.is_dir() and
        subprocess.run(["git","-C",str(path),"rev-parse","--is-inside-work-tree"],
                       capture_output=True, text=True).stdout.strip() == "true")

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
        """Projet 'mekicode' (racine) pour la back-compat des sessions plates."""
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

def workspace_for(session, registry: ProjectRegistry) -> Path:
    """cwd absolu d'une session : racine projet (main) ou dossier worktree."""
    project = registry.get(getattr(session, "project_id", None)) if registry else None
    if project is None:
        return _ROOT
    if getattr(session, "scope", "main") == "main":
        return Path(project.repo_path).resolve()
    return _wt_dir(project, session.scope, registry.worktrees_base)
```

- [ ] **Step 4 — Succès** : `python tests/smoke_mekihub.py` → OK (ajouter les 3 nouveaux tests à `main()`).
- [ ] **Step 5 — `py_compile`** : `python -m py_compile packages/mekihub/projects.py`.
- [ ] **Step 6 — Commit** : `feat(mekihub): projects.py — registre projets + worktrees + workspace_for`.

## Task 3 : champs projet sur `Session`/`SessionStore`

**Files :** Modify `packages/mekihub/session.py` ; Test `tests/smoke_mekihub.py`, `tests/smoke_mekichat.py`.

- [ ] **Step 1 — Tests (échouent)** (smoke_mekihub) :

```python
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
        assert {m.id for m in store.list()} == {a.id, b.id, c.id}   # sans filtre = tout

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
        assert s.project_id == "mekicode" and s.scope == "main"   # migration douce
```

- [ ] **Step 2 — Échec** (AttributeError project_id).
- [ ] **Step 3 — Implémentation** : sur `Session` ajouter `project_id: str = "mekicode"`,
`scope: str = "main"`, `discord_channel_id: str | None = None`. Sur `Author` ajouter
`source: str | None = None`. `SessionStore.create(self, model, system=None, *, project_id="mekicode",
scope="main")` ; `save` persiste les 3 champs ; `load` les lit avec défauts (`d.get("project_id","mekicode")`,
`d.get("scope","main")`, `d.get("discord_channel_id")`). `SessionMeta` gagne `project_id`, `scope` (lus
dans `list`). `list(self, project_id=None, scope=None)` filtre. Garder le tri récent d'abord.

- [ ] **Step 4 — Succès** : `python tests/smoke_mekihub.py` ET `python tests/smoke_mekichat.py` verts.
- [ ] **Step 5 — `py_compile`** `packages/mekihub/session.py`.
- [ ] **Step 6 — Commit** : `feat(mekihub): champs project_id/scope/source sur Session/Author + list filtrable`.

## Task 4 : hub workspace-aware (`dispatch_factory` + `registry`)

**Files :** Modify `packages/mekihub/hub.py` ; Test `tests/smoke_mekihub.py`.

- [ ] **Step 1 — Test (échoue)** :

```python
def test_hub_uses_per_session_workspace():
    import tempfile, subprocess
    from pathlib import Path
    sys.path.insert(0, str(ROOT / "tests")); from fakes import FakeLLM
    sys.path.insert(0, str(ROOT / "packages" / "mekicore")); import tools
    from mekihub.hub import SessionHub
    from mekihub.projects import ProjectRegistry
    async def scenario():
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as repo:
            subprocess.run(["git","init","-q"], cwd=repo, check=True)
            (Path(repo)/"marqueur.txt").write_text("ok", encoding="utf-8")
            reg = ProjectRegistry(path=str(Path(base)/"p.json"))
            p = reg.register(repo, name="proj")
            store = SessionStore(directory=str(Path(base)/"sess"))
            sess = store.create(model="m", system="sys", project_id=p.id, scope="main")
            # FakeLLM qui appelle l'outil read sur marqueur.txt puis répond
            hub = SessionHub(store=store, llm_factory=lambda: FakeLLM(reply="done"),
                             tools=tools.TOOLS, dispatch_factory=tools.make_dispatch, registry=reg)
            # vérifie que make_dispatch reçoit bien le workspace du projet
            ws = []
            orig = tools.make_dispatch
            hub.dispatch_factory = lambda w: (ws.append(w), orig(w))[1]
            from mekihub.session import Author
            sub = hub.subscribe(sess.id); await sub.__anext__()
            async def collect():
                async for e in sub:
                    if type(e).__name__ == "Idle": break
            t = asyncio.create_task(collect())
            hub.submit(sess.id, "salut", author=Author(id="c",name="a",color="#fff"))
            await asyncio.wait_for(t, timeout=5)
            assert ws and ws[0] == Path(repo).resolve()
    asyncio.run(scenario())
```

- [ ] **Step 2 — Échec** (constructeur n'accepte pas `dispatch_factory`/`registry`).
- [ ] **Step 3 — Implémentation** :

```python
def __init__(self, store, llm_factory, tools, dispatch=None, *,
             dispatch_factory=None, registry=None, provisioner=None):
    self.store = store; self.llm_factory = llm_factory; self.tools = tools
    if dispatch_factory is None:
        d = dispatch or {}
        dispatch_factory = lambda ws: d          # back-compat API dispatch=
    self.dispatch_factory = dispatch_factory
    self.registry = registry
    self.provisioner = provisioner
    self._rooms = {}
```

Dans `_run_worker`, avant `run_agent` :

```python
from projects import workspace_for          # mekihub (sys.path posé par __init__)
workspace = workspace_for(sess, self.registry) if self.registry else None
dispatch = self.dispatch_factory(workspace)
gen = run_agent(sess.messages, llm, self.tools, dispatch, stream=True)
```

(L'outil `spawn_worktree` et `approve_worktree` arrivent en Task 5/6 — ne pas les ajouter ici.)

- [ ] **Step 4 — Succès** : `python tests/smoke_mekihub.py` (tous, anciens inclus : l'API `dispatch=` reste).
- [ ] **Step 5 — `py_compile`** `packages/mekihub/hub.py`.
- [ ] **Step 6 — Commit** : `feat(mekihub): workspace par session via dispatch_factory + registry`.

## Task 5 : câblage front P1 (sélecteur Projet→scope→session)

**Files :** Modify `packages/mekichat/app.py`, `packages/mekichat/views.py`, `packages/mekihub/main.py`.

> UI NiceGUI : pas de test unitaire de rendu. Critère = `python tests/smoke_mekichat.py` vert +
> import sans effet de bord + lancement manuel non requis pour la non-régression.

- [ ] **Step 1** — `main.py` `build_hub()` :

```python
def build_hub():
    import mekillm
    import tools as core_tools
    from hub import SessionHub
    from session import SessionStore
    from projects import ProjectRegistry
    reg = ProjectRegistry(); reg.ensure_default()
    return SessionHub(store=SessionStore(), llm_factory=mekillm.LLM, tools=core_tools.TOOLS,
                      dispatch_factory=core_tools.make_dispatch, registry=reg)
```

- [ ] **Step 2** — `app.py` :
  - importer `make_dispatch` (`from tools import make_dispatch`) et `ProjectRegistry` ;
  - `_get_registry()` singleton (`ProjectRegistry()` + `ensure_default()`), exposé module-level ;
  - `_get_hub()` : `SessionHub(store=_HubSessionStore(), llm_factory=_llm_factory, tools=TOOLS,
    dispatch_factory=make_dispatch, registry=_get_registry())` ;
  - état courant : ajouter `current_project` (Project) et `current_scope` ("main" par défaut) ;
  - `new_session()` : `create(model=DEFAULT_MODEL, system=_system_for(project, scope),
    project_id=current_project.id, scope=current_scope)` où `_system_for` reprend le SYSTEM en
    injectant `workspace_for(...)` ;
  - `_ensure_current()` : charge la session la plus récente **du projet courant** (`store.list(project_id=...)`).

- [ ] **Step 3** — `views.py` : `render_project_selector(projects, current_id, scopes, current_scope,
  on_pick_project, on_pick_scope)` (deux `ui.select` ou listes stylées Phosphore), inséré en tête de
  `_refresh_sidebar`. La liste SESSIONS est filtrée par `store.list(project_id=current_project.id,
  scope=current_scope)`. Bouton « + Projet » → dialog demandant un chemin → `registry.register(path)`.

- [ ] **Step 4 — Vérifs** :
```bash
python tests/smoke_mekichat.py
python tests/smoke_packages.py
python tests/smoke_mekihub.py
python -c "import sys; sys.path[:0]=['packages','packages/mekicore','packages/mekichat']; import app"
```
Tous verts / import sans exception.
- [ ] **Step 5 — `py_compile`** app.py, views.py, main.py.
- [ ] **Step 6 — Commit** : `feat(mekichat): sélecteur Projet→scope→session + hub multi-projet`.

---

# PHASE P2 — Worktree par chat (outil agent gated)

## Task 6 : events + outil `spawn_worktree` + proposition

**Files :** Modify `packages/mekihub/events.py`, `packages/mekihub/hub.py` ; Test `tests/smoke_mekihub.py`.

- [ ] **Step 1 — Test (échoue)** : un FakeLLM qui appelle l'outil `spawn_worktree`, puis on vérifie
qu'un `WorktreeProposed` est publié et stocké, et que **rien n'est créé** avant approbation.

```python
def test_spawn_worktree_proposes_without_creating():
    import tempfile, subprocess
    from pathlib import Path
    sys.path.insert(0, str(ROOT / "tests")); from fakes import FakeLLM, FakeToolLLM
    sys.path.insert(0, str(ROOT / "packages" / "mekicore")); import tools
    from mekihub.hub import SessionHub
    from mekihub.projects import ProjectRegistry, _wt_dir
    from mekihub.session import Author
    async def scenario():
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as repo:
            subprocess.run(["git","init","-q"], cwd=repo, check=True)
            reg = ProjectRegistry(path=str(Path(base)/"p.json"), worktrees_base=str(Path(base)/"wt"))
            p = reg.register(repo, name="proj")
            store = SessionStore(directory=str(Path(base)/"sess"))
            sess = store.create(model="m", system="sys", project_id=p.id, scope="main")
            # FakeToolLLM : 1er tour appelle spawn_worktree, 2e tour répond du texte
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
            assert "WorktreeProposed" in got
            assert not _wt_dir(p, "featx", str(Path(base)/"wt")).exists()   # rien créé
            room = hub._rooms[sess.id]
            assert len(room.pending_worktrees) == 1
    asyncio.run(scenario())
```

Ajouter à `tests/fakes.py` un `FakeToolLLM` (un tour `tool_calls` puis un tour texte) si absent.

- [ ] **Step 2 — Échec.**
- [ ] **Step 3 — Implémentation** :
  - `events.py` : `MessagePosted` gagne `source: str | None = None` ; ajouter
    `@dataclass WorktreeProposed: proposal_id:str; session_id:str; name:str; prompt:str; base:str|None`,
    `WorktreeRejected: proposal_id:str`, `WorktreeCreated: proposal_id:str; child_session_id:str;
    channel_id:str|None`.
  - `hub.py` :
    - `_Room.__init__` : `self.pending_worktrees = {}`.
    - schéma outil (constante module) :
      ```python
      WORKTREE_TOOL = {"type":"function","function":{"name":"spawn_worktree",
        "description":"Propose la création d'un worktree git isolé (nouvelle feature/debug) "
          "et le lancement d'un agent dedans. Nécessite la validation de l'utilisateur.",
        "parameters":{"type":"object","properties":{
          "nom":{"type":"string","description":"nom court du worktree/branche"},
          "prompt_amorce":{"type":"string","description":"consigne initiale de l'agent enfant"},
          "base":{"type":"string","description":"branche de base (optionnel)"}},
          "required":["nom","prompt_amorce"]}}}
      ```
    - dans `_run_worker`, si `self.registry` : `tools_run = self.tools + [WORKTREE_TOOL]`,
      `proposals = []`, `dispatch = {**self.dispatch_factory(workspace),
      "spawn_worktree": lambda a, _p=proposals: _record_proposal(_p, a)}`.
      Sinon `tools_run = self.tools`.
    - `_record_proposal(proposals, args)` (fonction module) : `pid = uuid.uuid4().hex[:8]`,
      append `{"proposal_id":pid, **args}`, retourne `f"Proposition de worktree '{args.get('nom')}'
      envoyée pour validation."`.
    - après la boucle d'events (avant `room.running=None`) : pour chaque `pr` dans `proposals` :
      `room.pending_worktrees[pr["proposal_id"]] = pr` ; publier
      `ev.WorktreeProposed(proposal_id=pr["proposal_id"], session_id=session_id, name=pr["nom"],
      prompt=pr["prompt_amorce"], base=pr.get("base"))`.
    - `MessagePosted` publié dans `_run_worker` : ajouter `source=item.author.source`.

- [ ] **Step 4 — Succès** `python tests/smoke_mekihub.py`.
- [ ] **Step 5 — `py_compile`** events.py, hub.py.
- [ ] **Step 6 — Commit** : `feat(mekihub): outil spawn_worktree gated + events WorktreeProposed`.

## Task 7 : `approve_worktree` / `reject_worktree`

**Files :** Modify `packages/mekihub/hub.py` ; Test `tests/smoke_mekihub.py`.

- [ ] **Step 1 — Test (échoue)** : depuis l'état de Task 6, appeler `await hub.approve_worktree(sess.id,
pid)` et vérifier : le dossier worktree existe, une **session enfant** existe (`store.list(project_id=p.id,
scope="featx")` non vide), son premier message user == le prompt d'amorçage, et un `WorktreeCreated`
est publié. Puis un autre test : `reject_worktree` → `WorktreeRejected`, rien créé, `pending_worktrees` vidé.

```python
def test_approve_worktree_creates_child_session():
    # ... reprendre le setup de Task 6 jusqu'à obtenir pid dans room.pending_worktrees ...
    child_id = await hub.approve_worktree(sess.id, pid)
    assert _wt_dir(p, "featx", str(Path(base)/"wt")).exists()
    child = store.load(child_id)
    assert child.scope == "featx" and child.project_id == p.id
    assert any(m.get("role")=="user" and "feature X" in m["content"] for m in child.messages)
    assert pid not in hub._rooms[sess.id].pending_worktrees
```

- [ ] **Step 2 — Échec** (pas de méthode).
- [ ] **Step 3 — Implémentation** :

```python
async def approve_worktree(self, session_id, proposal_id):
    room = self._room(session_id)
    pr = room.pending_worktrees.pop(proposal_id, None)
    if pr is None: return None
    parent = self.store.load(session_id)
    from projects import add_worktree, workspace_for  # mekihub
    project = self.registry.get(parent.project_id)
    # git worktree add (bloquant) hors boucle
    await asyncio.to_thread(add_worktree, project, pr["nom"], pr.get("base"),
                            self.registry.worktrees_base)
    child = self.store.create(model=parent.model, system=parent.messages[0]["content"]
                              if parent.messages and parent.messages[0]["role"]=="system" else None,
                              project_id=project.id, scope=pr["nom"])
    channel_id = None
    if self.provisioner is not None:
        try: channel_id = await self.provisioner.ensure_channel(child)
        except Exception: channel_id = None     # never-raise : Discord optionnel
    self._publish(session_id, ev.WorktreeCreated(proposal_id=proposal_id,
                  child_session_id=child.id, channel_id=channel_id))
    # amorce l'agent enfant
    sys_author = Author(id="system", name="mekicode", color="#39ff14", source="system")
    self.submit(child.id, pr["prompt_amorce"], author=sys_author)
    return child.id

def reject_worktree(self, session_id, proposal_id):
    room = self._room(session_id)
    if room.pending_worktrees.pop(proposal_id, None) is not None:
        self._publish(session_id, ev.WorktreeRejected(proposal_id=proposal_id))
        return True
    return False
```

- [ ] **Step 4 — Succès** `python tests/smoke_mekihub.py`.
- [ ] **Step 5 — `py_compile`** hub.py.
- [ ] **Step 6 — Commit** : `feat(mekihub): approve_worktree/reject_worktree + spawn session enfant amorcée`.

## Task 8 : UI validation worktree (front)

**Files :** Modify `packages/mekichat/app.py`, `packages/mekichat/views.py`.

- [ ] **Step 1** — `views.py` : `render_worktree_proposal(name, prompt, on_approve, on_reject)` →
carte Phosphore avec 2 boutons (Approuver / Refuser).
- [ ] **Step 2** — `app.py` `_render_hub_event` : ajouter
  - `WorktreeProposed` → rendre la carte ; `on_approve = lambda: asyncio.create_task(
    _get_hub().approve_worktree(current.id, event.proposal_id))`, `on_reject = lambda:
    _get_hub().reject_worktree(current.id, event.proposal_id)` ;
  - `WorktreeCreated` → toast/info « worktree prêt » + `_refresh_sidebar()` (la session enfant apparaît
    sous le scope worktree) ;
  - `WorktreeRejected` → retire la carte.
- [ ] **Step 3 — Vérifs** : `python tests/smoke_mekichat.py` + import app sans exception.
- [ ] **Step 4 — `py_compile`** app.py, views.py.
- [ ] **Step 5 — Commit** : `feat(mekichat): carte de validation worktree (approuver/refuser)`.

---

# PHASE P3 — Provisioning + synchro Discord

## Task 9 : `FakeDiscordClient` étendu + `DiscordProvisioner`

**Files :** Modify `packages/mekihub/adapters/discord.py` ; Test `tests/smoke_mekihub.py`.

- [ ] **Step 1 — Tests (échouent)** :

```python
def test_provisioner_creates_categories_and_channels_idempotent():
    import tempfile, subprocess
    from pathlib import Path
    from mekihub.adapters.discord import DiscordProvisioner, FakeDiscordClient
    from mekihub.projects import ProjectRegistry
    from mekihub.session import Session, SessionStore
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
            sw = Session(id="s2", title="t", model="m", created_at="t",
                         project_id=p.id, scope="featx")
            chw = await prov.ensure_channel(sw)
            assert client.channel_name(chw).startswith("featx-")
    asyncio.run(scenario())
```

- [ ] **Step 2 — Échec.**
- [ ] **Step 3 — Implémentation** dans `adapters/discord.py` :
  - Étendre `FakeDiscordClient` : `async create_guild(name)->str`, `async create_category(guild_id,
    name)->str`, `async create_channel(guild_id, category_id, name)->str`, `async create_invite(
    channel_id)->str` ; structures internes ; helpers test `category_count()`, `channel_name(id)`.
    Conserver `send`/`edit`/`sent_texts`.
  - `slug` canal : helper `_channel_name(session)` → main `f"main-{slugify(title or id)[:80]}"` (fallback
    `f"main-{id[:8]}"`), worktree `f"{slugify(scope)}-{id[:8]}"`. Réutiliser `slugify` de projects.
  - `DiscordProvisioner` :
    ```python
    class DiscordProvisioner:
        def __init__(self, registry, client, *, guild_id=None, admin_user_id=None):
            self.registry, self.client = registry, client
            self.guild_id, self.admin_user_id = guild_id, admin_user_id
            self._store = None     # SessionStore optionnel pour reconcile
        async def ensure_server(self):
            if self.guild_id: return self.guild_id
            if hasattr(self.client, "create_guild"):
                self.guild_id = await self.client.create_guild("mekicode")
                return self.guild_id
            return None
        async def ensure_project(self, project):
            gid = await self.ensure_server()
            d = dict(project.discord or {})
            if not d.get("cat_main"):
                d["cat_main"] = await self.client.create_category(gid, f"{project.slug}-main")
            if not d.get("cat_worktrees"):
                d["cat_worktrees"] = await self.client.create_category(gid, f"{project.slug}-worktrees")
            d["guild_id"] = gid
            project.discord = d; self.registry.update(project)
            return d["cat_main"], d["cat_worktrees"]
        async def ensure_channel(self, session):
            project = self.registry.get(session.project_id)
            cat_main, cat_wt = await self.ensure_project(project)
            cat = cat_main if session.scope == "main" else cat_wt
            ch = await self.client.create_channel(project.discord["guild_id"], cat,
                                                  _channel_name(session))
            session.discord_channel_id = ch
            return ch
    ```
  - **Idempotence** : `ensure_project` ne crée que si l'id n'existe pas (lu dans `project.discord`).
    Pour les canaux, l'idempotence vit dans la session (`discord_channel_id`) — `ensure_channel` ne
    recrée pas si déjà posé : ajouter en tête `if session.discord_channel_id: return
    session.discord_channel_id`.

- [ ] **Step 4 — Succès** `python tests/smoke_mekihub.py`.
- [ ] **Step 5 — `py_compile`** adapters/discord.py.
- [ ] **Step 6 — Commit** : `feat(mekihub): DiscordProvisioner idempotent (serveur/catégories/canaux)`.

## Task 10 : mirroring bidirectionnel + anti-écho

**Files :** Modify `packages/mekihub/adapters/discord.py` ; Test `tests/smoke_mekihub.py`.

- [ ] **Step 1 — Test (échoue)** : un message **né dans Discord** ne doit pas être re-posté dans son
canal (anti-écho) ; un message né côté front (source != ce canal) doit, lui, être reflété.

```python
def test_discord_antiecho_on_messageposted():
    sys.path.insert(0, str(ROOT / "tests")); from fakes import FakeLLM
    from mekihub.hub import SessionHub
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
        # le message "depuis discord" ne doit PAS avoir été reposté par le bot (anti-écho)
        assert sum(1 for t in texts if t == "depuis discord") == 0
        assert any("ok" in t for t in texts)     # la réponse agent est bien postée
        store.delete(sess.id)
    asyncio.run(scenario())
```

- [ ] **Step 2 — Échec** (si on ajoute naïvement le rendu de MessagePosted sans garde).
- [ ] **Step 3 — Implémentation** : dans `handle_message`, construire l'`Author` avec
`source=f"discord:{msg.channel_id}"`. Dans `_render_loop`, gérer `MessagePosted` :
```python
elif name == "MessagePosted":
    if getattr(event, "source", None) != f"discord:{channel_id}":
        await self.client.send(channel_id, f"**{event.author_name}**: {event.text}")
```
(le message né dans ce canal a `source==f"discord:{channel_id}"` → ignoré).

- [ ] **Step 4 — Succès** `python tests/smoke_mekihub.py` (et `test_discord_adapter_with_fake_client` reste vert).
- [ ] **Step 5 — `py_compile`** adapters/discord.py.
- [ ] **Step 6 — Commit** : `feat(mekihub): miroir bidirectionnel Discord + anti-écho`.

## Task 11 : intégration provisioner au hub + reconcile au démarrage

**Files :** Modify `packages/mekihub/hub.py` (déjà accepte `provisioner`), `packages/mekihub/main.py`,
`packages/mekichat/app.py` ; Test `tests/smoke_mekihub.py`.

- [ ] **Step 1 — Test (échoue)** : `reconcile()` parcourt projets+sessions et crée les canaux manquants
(idempotent), avec `FakeDiscordClient`.

```python
def test_reconcile_creates_missing_channels():
    import tempfile, subprocess
    from pathlib import Path
    from mekihub.adapters.discord import DiscordProvisioner, FakeDiscordClient
    from mekihub.projects import ProjectRegistry
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
            n = await prov.reconcile(store)
            assert n == 2 and client.channel_count() >= 2
            assert await prov.reconcile(store) == 0     # idempotent : rien à recréer
    asyncio.run(scenario())
```

- [ ] **Step 2 — Échec.**
- [ ] **Step 3 — Implémentation** : `DiscordProvisioner.reconcile(store)` : pour chaque projet du
registre, `ensure_project` ; pour chaque session (`store.list(project_id=p.id)`) **sans**
`discord_channel_id`, charger la session complète, `ensure_channel`, **persister** (`store.save`) ;
compter les créations ; renvoyer le total. Ajouter `channel_count()` à `FakeDiscordClient`.
Câbler (optionnel, garde token) dans `main.py`/`app.py` : si `DISCORD_BOT_TOKEN`, construire un
provisioner réel et le passer au hub + appeler `reconcile` au démarrage ; sinon `provisioner=None`
(le hub et le front marchent sans Discord — déjà géré par les `try/except` de Task 7).

- [ ] **Step 4 — Succès** `python tests/smoke_mekihub.py`.
- [ ] **Step 5 — `py_compile`** hub.py, main.py, app.py.
- [ ] **Step 6 — Commit** : `feat(mekihub): reconcile Discord au démarrage (idempotent, optionnel)`.

## Task 12 : doc + non-régression globale

**Files :** Modify `docs/wiki-packages/mekihub.md`, `docs/wiki-packages/mekichat.md`, `ROADMAP.md`.

- [ ] **Step 1** — Documenter à la main (convention repo) : nouveau `projects.py`, champs session,
`dispatch_factory`, flux worktree, `DiscordProvisioner`, variables d'env
(`DISCORD_GUILD_ID`, `MEKICODE_ADMIN_USER_ID`).
- [ ] **Step 2 — Non-régression complète** :
```bash
python tests/smoke_packages.py
python tests/smoke_mekichat.py
python tests/smoke_mekihub.py
python -m py_compile packages/mekicore/tools.py packages/mekihub/projects.py packages/mekihub/session.py packages/mekihub/events.py packages/mekihub/hub.py packages/mekihub/adapters/discord.py packages/mekihub/main.py packages/mekichat/app.py packages/mekichat/views.py
```
Tout vert.
- [ ] **Step 3 — Commit** : `docs: multi-projet + worktree + Discord (wiki-packages, ROADMAP)`.

---

## Évolutions différées (rappel spec §9, hors plan)
- Backfill complet de l'historique Discord à l'import (option 1 décision 6).
- Convs perso locales (`<projet>/.mekicode/`) vs partagées centralisées.
- Transfert de propriété d'un serveur auto-créé (manuel, 2FA).
- **Validation Discord réelle** : nécessite un `DISCORD_BOT_TOKEN` + serveur → **manuelle** (hors
  périmètre réseau-free ; `connect_real` couvre le câblage).

## Self-review (couverture spec)
- §3 unités → Tasks 1-11 ✓ · §4 modèle données → Tasks 2-3 ✓ · §5 worktree → Tasks 6-8 ✓ ·
  §6 Discord → Tasks 9-11 ✓ · §7 erreurs → never-raise Task 7/11 + refus non-git Task 2 ✓ ·
  §8 tests → chaque task ✓. Pas de placeholder. Signatures cohérentes
  (`make_dispatch`, `workspace_for`, `ensure_channel`, `approve_worktree`) réutilisées telles quelles.
