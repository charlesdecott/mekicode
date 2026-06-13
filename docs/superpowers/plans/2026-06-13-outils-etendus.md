# Outils étendus de l'agent (read/write/edit/grep/glob) — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Donner à l'agent cinq outils de fichiers (`read`, `write`, `edit`, `grep`, `glob`) à côté de `bash`, confinés à un workspace (racine = `cwd` par défaut), et afficher leurs blocs dans le front.

**Architecture:** On **étend** `packages/mekicore/tools.py` (un helper `_safe_path` + 5 fonctions + schémas `TOOLS` + table `DISPATCH`). `run_agent` est inchangé (dispatch générique par nom). Le front **généralise** son bloc `[bash]` (`views.render_tool`) pour afficher n'importe quel outil. Tests réseau-free dans `tests/smoke_packages.py`.

**Tech Stack:** Python pur (`pathlib`, `re`, `subprocess`) ; NiceGUI pour le rendu ; tests assertions + `main()` (convention du repo).

**Référence design :** [`docs/superpowers/specs/2026-06-13-outils-etendus-design.md`](../specs/2026-06-13-outils-etendus-design.md)

---

## Structure des fichiers

| Fichier | Rôle |
|---------|------|
| `packages/mekicore/tools.py` (modif) | `_workspace`, `_safe_path`, `read_file`/`write_file`/`edit_file`/`grep_files`/`glob_files`, `_tool`, `TOOLS`, `DISPATCH` |
| `packages/mekicore/main.py` (modif) | `SYSTEM` : mentionner les outils fichiers |
| `packages/mekichat/app.py` (modif) | `SYSTEM` + branche `ToolStarted`/`ToolFinished` de `_render_event` (nom + résumé) |
| `packages/mekichat/views.py` (modif) | `render_tool(name, summary, …)` généralisé, helper `tool_summary`, `render_thread` |
| `tests/smoke_packages.py` (modif) | tests des 5 outils + `_safe_path` + routage `DISPATCH` |
| `docs/wiki-packages/mekicore.md`, `ROADMAP.md`, `README.md` (modif) | doc à jour |

**Note clé (testabilité) :** la racine workspace est lue **à chaque appel** via `_workspace()` (pas une constante figée à l'import), pour que les tests puissent pointer `MEKICORE_WORKSPACE` sur un dossier temporaire.

---

### Task 1 : `_workspace` + `_safe_path` (confinement) — TDD

**Files:** Modify `packages/mekicore/tools.py` · Test `tests/smoke_packages.py`

- [ ] **Step 1 : Écrire les tests qui échouent**

Dans `tests/smoke_packages.py`, ajouter en tête (après les imports existants) un context manager utilitaire :

```python
import contextlib  # (ajouter aux imports si absent)


@contextlib.contextmanager
def _ws(d):
    """Pointe MEKICORE_WORKSPACE sur d le temps du bloc (restauré ensuite)."""
    old = os.environ.get("MEKICORE_WORKSPACE")
    os.environ["MEKICORE_WORKSPACE"] = str(d)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("MEKICORE_WORKSPACE", None)
        else:
            os.environ["MEKICORE_WORKSPACE"] = old
```

Puis, avant `def main():`, ajouter :

```python
def test_safe_path_confine():
    with tempfile.TemporaryDirectory() as d, _ws(d):
        root = Path(d).resolve()
        assert tools._safe_path("a/b.txt") == root / "a" / "b.txt"   # relatif → OK
        assert tools._safe_path(".") == root                          # la racine elle-même
        for bad in ["../escape.txt", "../../etc/passwd"]:
            try:
                tools._safe_path(bad)
                assert False, f"aurait dû refuser {bad}"
            except ValueError:
                pass
```

Et l'appeler dans `main()` (avant le print) :

```python
    test_safe_path_confine()
```

> `tools`, `os`, `tempfile` sont déjà importés en tête de `tests/smoke_packages.py`. Ajouter
> `from pathlib import Path` si absent (il l'est déjà) et `import contextlib`.

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python tests/smoke_packages.py`
Expected: `AttributeError: module 'tools' has no attribute '_safe_path'`.

- [ ] **Step 3 : Implémenter dans `packages/mekicore/tools.py`**

Remplacer l'en-tête + le bloc `_ALWAYS_BLOCK` actuel par :

```python
"""tools.py — outils de mekicore au format function-calling OpenAI.

bash + outils de fichiers (read/write/edit/grep/glob) **confinés à un workspace**
(racine = cwd par défaut, surchargeable par MEKICORE_WORKSPACE). bash reste non confiné.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

_ALWAYS_BLOCK = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/", ":(){ :|:& };:"]
_MAX_OUT = 50000


def _workspace() -> Path:
    """Racine du workspace (lue à chaque appel : surchargeable par MEKICORE_WORKSPACE)."""
    return Path(os.environ.get("MEKICORE_WORKSPACE") or os.getcwd()).resolve()


def _safe_path(p: str) -> Path:
    """Résout p dans le workspace ; lève ValueError s'il s'en échappe (absolu hors racine, ../)."""
    ws = _workspace()
    target = (ws / p).resolve()
    if target != ws and ws not in target.parents:
        raise ValueError(f"chemin hors du workspace : {p}")
    return target
```

(Garder `run_bash` tel quel juste en dessous.)

- [ ] **Step 4 : Lancer, vérifier que ça passe**

Run: `python tests/smoke_packages.py`
Expected: `OK - tous les smoke tests passent`.

- [ ] **Step 5 : `py_compile` + commit**

```bash
python -m py_compile packages/mekicore/tools.py tests/smoke_packages.py
git add packages/mekicore/tools.py tests/smoke_packages.py
git commit -m "mekicore: workspace + _safe_path (confinement des outils fichiers)"
```

---

### Task 2 : `read` / `write` / `edit` — TDD

**Files:** Modify `packages/mekicore/tools.py` · Test `tests/smoke_packages.py`

- [ ] **Step 1 : Écrire les tests qui échouent** (avant `def main():`)

```python
def test_write_read_roundtrip():
    with tempfile.TemporaryDirectory() as d, _ws(d):
        assert tools.write_file("sub/a.txt", "café ☕").startswith("écrit")   # crée le dossier parent
        assert (Path(d) / "sub" / "a.txt").is_file()
        assert tools.read_file("sub/a.txt") == "café ☕"
        assert tools.read_file("absent.txt").startswith("Error")
        assert tools.write_file("../escape.txt", "x").startswith("Error")     # confiné


def test_edit_unique_and_ambiguous():
    with tempfile.TemporaryDirectory() as d, _ws(d):
        tools.write_file("f.py", "a = 1\nb = 2\na = 1\n")
        assert tools.edit_file("f.py", "b = 2", "b = 3") == "édité f.py"
        assert tools.read_file("f.py") == "a = 1\nb = 3\na = 1\n"
        assert tools.edit_file("f.py", "a = 1", "a = 9").startswith("Error")  # 2 occurrences → ambigu
        assert tools.edit_file("f.py", "zzz", "x").startswith("Error")        # introuvable
```

Appeler dans `main()` :

```python
    test_write_read_roundtrip()
    test_edit_unique_and_ambiguous()
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python tests/smoke_packages.py`
Expected: `AttributeError: module 'tools' has no attribute 'write_file'`.

- [ ] **Step 3 : Implémenter (après `run_bash` dans `tools.py`)**

```python
def read_file(path: str) -> str:
    """Lit un fichier texte (confiné au workspace)."""
    try:
        p = _safe_path(path)
    except ValueError as e:
        return f"Error: {e}"
    if not p.is_file():
        return f"Error: fichier introuvable : {path}"
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:_MAX_OUT]
    except OSError as e:
        return f"Error: {e}"


def write_file(path: str, content: str) -> str:
    """Crée ou écrase un fichier texte (crée les dossiers parents)."""
    try:
        p = _safe_path(path)
    except ValueError as e:
        return f"Error: {e}"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    except OSError as e:
        return f"Error: {e}"
    return f"écrit {len(content)} caractères dans {path}"


def edit_file(path: str, old: str, new: str) -> str:
    """Remplace `old` par `new` si `old` apparaît exactement une fois (str-replace)."""
    try:
        p = _safe_path(path)
    except ValueError as e:
        return f"Error: {e}"
    if not p.is_file():
        return f"Error: fichier introuvable : {path}"
    content = p.read_text(encoding="utf-8")
    count = content.count(old)
    if count == 0:
        return "Error: texte introuvable (old)"
    if count > 1:
        return f"Error: texte ambigu ({count} occurrences) — ajoute du contexte"
    p.write_text(content.replace(old, new, 1), encoding="utf-8")
    return f"édité {path}"
```

- [ ] **Step 4 : Lancer, vérifier que ça passe**

Run: `python tests/smoke_packages.py` → `OK - tous les smoke tests passent`.

- [ ] **Step 5 : `py_compile` + commit**

```bash
python -m py_compile packages/mekicore/tools.py tests/smoke_packages.py
git add packages/mekicore/tools.py tests/smoke_packages.py
git commit -m "mekicore: outils read/write/edit (confines au workspace)"
```

---

### Task 3 : `grep` / `glob` — TDD

**Files:** Modify `packages/mekicore/tools.py` · Test `tests/smoke_packages.py`

- [ ] **Step 1 : Écrire les tests qui échouent** (avant `def main():`)

```python
def test_grep_and_glob():
    with tempfile.TemporaryDirectory() as d, _ws(d):
        tools.write_file("pkg/a.py", "import os\ndef hello():\n    return 42\n")
        tools.write_file("pkg/b.py", "x = 1\n")
        tools.write_file("notes.txt", "rien\n")
        g = tools.grep_files(r"def \w+", "pkg")
        assert "a.py:2" in g and "def hello" in g
        assert tools.grep_files("zzznope", ".") == "(aucun résultat)"
        assert tools.grep_files("(", ".").startswith("Error")          # regex invalide
        files = tools.glob_files("pkg/*.py")
        assert "pkg/a.py" in files and "pkg/b.py" in files and "notes.txt" not in files
        assert tools.glob_files("**/*.py").count("\n") >= 1            # récursif
```

Appeler dans `main()` :

```python
    test_grep_and_glob()
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python tests/smoke_packages.py`
Expected: `AttributeError: module 'tools' has no attribute 'grep_files'`.

- [ ] **Step 3 : Implémenter (après `edit_file`)**

```python
def grep_files(pattern: str, path: str = ".") -> str:
    """Cherche une regex dans les fichiers texte sous `path` (confiné). Renvoie relpath:ligne: contenu."""
    try:
        root = _safe_path(path)
        rx = re.compile(pattern)
    except ValueError as e:
        return f"Error: {e}"
    except re.error as e:
        return f"Error: regex invalide : {e}"
    ws = _workspace()
    candidates = [root] if root.is_file() else sorted(root.rglob("*"))
    results: list[str] = []
    for f in candidates:
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # binaire / illisible : on saute
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                results.append(f"{f.relative_to(ws)}:{i}: {line.strip()[:200]}")
                if len(results) >= 200:
                    break
        if len(results) >= 200:
            break
    if not results:
        return "(aucun résultat)"
    return "\n".join(results)[:_MAX_OUT]


def glob_files(pattern: str) -> str:
    """Liste les fichiers correspondant au motif (ex. **/*.py) sous le workspace, chemins relatifs."""
    ws = _workspace()
    try:
        matches = sorted(str(p.relative_to(ws)) for p in ws.glob(pattern) if p.is_file())
    except ValueError as e:
        return f"Error: motif invalide : {e}"
    if not matches:
        return "(aucun fichier)"
    return "\n".join(matches[:1000])
```

- [ ] **Step 4 : Lancer, vérifier que ça passe**

Run: `python tests/smoke_packages.py` → `OK - tous les smoke tests passent`.

> Note Windows : `relative_to(ws)` produit des séparateurs `\`. Le test vérifie `pkg/a.py` ; si l'OS
> rend `pkg\a.py`, **normaliser dans le test** en comparant `g.replace("\\", "/")`. Ajuster le test si
> besoin (ce n'est pas un bug de l'outil, juste l'affichage du séparateur).

- [ ] **Step 5 : `py_compile` + commit**

```bash
python -m py_compile packages/mekicore/tools.py tests/smoke_packages.py
git add packages/mekicore/tools.py tests/smoke_packages.py
git commit -m "mekicore: outils grep/glob (confines au workspace)"
```

---

### Task 4 : schémas `TOOLS` + `DISPATCH` + prompts `SYSTEM` — TDD (routage)

**Files:** Modify `packages/mekicore/tools.py`, `packages/mekicore/main.py`, `packages/mekichat/app.py` · Test `tests/smoke_packages.py`

- [ ] **Step 1 : Écrire le test qui échoue** (avant `def main():`)

```python
def test_tools_registered():
    names = {t["function"]["name"] for t in tools.TOOLS}
    assert names == {"bash", "read", "write", "edit", "grep", "glob"}
    assert set(tools.DISPATCH) == names
    with tempfile.TemporaryDirectory() as d, _ws(d):
        # routage : chaque handler est appelable via DISPATCH avec ses arguments
        assert tools.DISPATCH["write"]({"path": "x.txt", "content": "hi"}).startswith("écrit")
        assert tools.DISPATCH["read"]({"path": "x.txt"}) == "hi"
        assert tools.DISPATCH["glob"]({"pattern": "*.txt"}) == "x.txt"
```

Appeler dans `main()` :

```python
    test_tools_registered()
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python tests/smoke_packages.py`
Expected: `AssertionError` (TOOLS ne contient encore que `bash`).

- [ ] **Step 3 : Remplacer le bloc `TOOLS`/`DISPATCH` à la fin de `tools.py`** par :

```python
def _tool(name: str, desc: str, props: dict, required: list) -> dict:
    """Construit un schéma function-calling OpenAI."""
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props, "required": required},
    }}


# Schémas au format function-calling OpenAI (ce que le modèle voit).
TOOLS = [
    _tool("bash", "Run a shell command.", {"command": {"type": "string"}}, ["command"]),
    _tool("read", "Read a text file (path relative to the workspace).",
          {"path": {"type": "string"}}, ["path"]),
    _tool("write", "Create or overwrite a text file (path relative to the workspace).",
          {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
    _tool("edit", "Replace an exact, unique snippet in a file (str-replace).",
          {"path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
          ["path", "old", "new"]),
    _tool("grep", "Search a regex in files under a path (relative to the workspace).",
          {"pattern": {"type": "string"}, "path": {"type": "string"}}, ["pattern"]),
    _tool("glob", "List files matching a glob pattern (e.g. **/*.py) under the workspace.",
          {"pattern": {"type": "string"}}, ["pattern"]),
]

# Routage nom d'outil → handler(args: dict) -> str.
DISPATCH = {
    "bash": lambda a: run_bash(a["command"]),
    "read": lambda a: read_file(a["path"]),
    "write": lambda a: write_file(a["path"], a["content"]),
    "edit": lambda a: edit_file(a["path"], a["old"], a["new"]),
    "grep": lambda a: grep_files(a["pattern"], a.get("path", ".")),
    "glob": lambda a: glob_files(a["pattern"]),
}
```

- [ ] **Step 4 : Mettre à jour les prompts `SYSTEM`**

`packages/mekicore/main.py` — remplacer la ligne `SYSTEM = ...` par :
```python
SYSTEM = (
    f"You are a coding agent at {Path.cwd()}. Tools: bash, read, write, edit (str-replace), "
    "grep, glob. The file tools are confined to the workspace. Act, don't explain."
)
```

`packages/mekichat/app.py` — remplacer la ligne `SYSTEM = ...` par :
```python
SYSTEM = (
    f"You are a coding agent at {Path.cwd()}. Tools: bash, read, write, edit (str-replace), "
    "grep, glob (file tools are confined to the workspace). Be concise."
)
```

- [ ] **Step 5 : Lancer, vérifier que ça passe**

Run: `python tests/smoke_packages.py` → `OK - tous les smoke tests passent`.
(Vérifie aussi que `test_dispatch_tools`/`test_run_agent_*` existants restent verts : `bash` est toujours là.)

- [ ] **Step 6 : `py_compile` + commit**

```bash
python -m py_compile packages/mekicore/tools.py packages/mekicore/main.py packages/mekichat/app.py tests/smoke_packages.py
git add packages/mekicore/tools.py packages/mekicore/main.py packages/mekichat/app.py tests/smoke_packages.py
git commit -m "mekicore: enregistrer read/write/edit/grep/glob (TOOLS + DISPATCH) + prompts SYSTEM"
```

---

### Task 5 : généraliser le rendu des outils dans le front

**Files:** Modify `packages/mekichat/views.py`, `packages/mekichat/app.py`

- [ ] **Step 1 : `views.py` — `render_tool` générique + `tool_summary`**

Remplacer la fonction `render_tool` par :

```python
def tool_summary(args) -> str:
    """Résumé d'un appel d'outil pour l'affichage : la commande / le chemin / le motif."""
    if not isinstance(args, dict):
        return ""
    for k in ("command", "path", "pattern"):
        if k in args:
            return str(args[k])
    return str(next(iter(args.values()), ""))


def render_tool(name: str, summary: str = "", output: str = "", status: str = "RUN"):
    """Bloc d'outil générique : ▣ <NOM> :: <résumé>. Renvoie (label_statut, label_sortie)."""
    with ui.element("div").classes("tool"):
        with ui.element("div").classes("tool-head"):
            ui.label(f"▣ {name}").classes("ic")
            ui.label(summary).classes("cmd")
            st = ui.label(status).classes("st done" if status == "DONE" else "st")
        out = ui.label(output).classes("tool-out")
    return st, out
```

- [ ] **Step 2 : `views.py` — `render_thread` (rejeu de l'historique)**

Remplacer la branche `tool_calls` de `render_thread` par :

```python
        if role == "assistant":
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                render_tool(fn.get("name", "tool"), tool_summary(args),
                            output=outputs.get(tc.get("id"), ""), status="DONE")
```

- [ ] **Step 3 : `app.py` — `_render_event` (live)**

Dans `_render_event`, remplacer les deux branches outil :

```python
            elif isinstance(ev, events.ToolStarted):
                handles[ev.id] = views.render_tool(ev.name, views.tool_summary(ev.args))
            elif isinstance(ev, events.ToolFinished):
                handle = handles.get(ev.id)
                ok = not ev.output.startswith("Error")
                if handle is not None:
                    views.fill_tool(handle, ev.output, ok=ok)
                else:
                    views.render_tool(ev.name, "", output=ev.output, status="DONE")
```

- [ ] **Step 4 : `py_compile`**

Run: `python -m py_compile packages/mekichat/views.py packages/mekichat/app.py`
Expected: pas d'erreur.

- [ ] **Step 5 : Commit**

```bash
git add packages/mekichat/views.py packages/mekichat/app.py
git commit -m "mekichat: rendu generique des outils (read/write/edit/grep/glob), plus seulement bash"
```

---

### Task 6 : vérification (Playwright) + docs

**Files:** Create (jetable, gitignoré) `.refactor-tmp/diag_tools.py` · Modify `docs/wiki-packages/mekicore.md`, `ROADMAP.md`, `README.md`

- [ ] **Step 1 : Non-régression réseau-free**

Run: `python tests/smoke_packages.py` → `OK - tous les smoke tests passent` (inclut `_safe_path`, read/write/edit, grep/glob, routage).
Run: `python tests/smoke_mekichat.py` → `OK - smoke mekichat passe`.

- [ ] **Step 2 : Vérification visuelle DÉTERMINISTE d'un bloc d'outil non-bash**

Fabriquer une session avec un appel `read` (sans LLM), la charger, capturer — valide le rendu générique.

```python
"""diag_tools.py — vérifie le rendu d'un bloc d'outil non-bash (read), déterministe, sans LLM."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SESS = ROOT / ".sessions"; SESS.mkdir(exist_ok=True)
pre = {"id": "diagtools", "title": "Outils (pré-fab)", "model": "openrouter/owl-alpha",
       "created_at": "2099-09-09T00:00:00+00:00",
       "messages": [
           {"role": "system", "content": "sys"},
           {"role": "user", "content": "Lis le README."},
           {"role": "assistant", "content": "",
            "tool_calls": [{"id": "t1", "type": "function",
                            "function": {"name": "read", "arguments": json.dumps({"path": "README.md"})}}]},
           {"role": "tool", "tool_call_id": "t1", "content": "# mekicode 🤖\n..."},
           {"role": "assistant", "content": "Voici le début du README."},
       ]}
(SESS / "diagtools.json").write_text(json.dumps(pre, ensure_ascii=False), encoding="utf-8")
with sync_playwright() as p:
    b = p.chromium.launch(); page = b.new_page(viewport={"width": 1440, "height": 900})
    page.goto("http://127.0.0.1:8080", wait_until="networkidle", timeout=20000); page.wait_for_timeout(1500)
    res = {
        "tools": page.eval_on_selector_all(".tool", "e=>e.length"),
        "ic": page.eval_on_selector(".tool .ic", "e=>e.textContent") if page.query_selector(".tool") else None,
        "cmd": page.eval_on_selector(".tool .cmd", "e=>e.textContent") if page.query_selector(".tool") else None,
    }
    page.screenshot(path=".refactor-tmp/tools.png")
    print(json.dumps(res, ensure_ascii=False))
    b.close()
```

Démarrer le serveur (`python packages/mekichat/app.py`, tuer d'abord tout process sur 8080), puis
`python .refactor-tmp/diag_tools.py`.
Expected : `tools=1`, `ic` contient `▣ read`, `cmd` = `README.md`. **Lire `.refactor-tmp/tools.png`** :
un bloc `▣ read :: README.md` avec la sortie. Supprimer ensuite `.sessions/diagtools.json`.

- [ ] **Step 3 : Vérification LIVE (l'agent utilise un outil fichier)**

Avec le serveur lancé, via Playwright : nouvelle session, envoyer « Combien de fichiers .py dans
packages/ ? Utilise glob. » ; attendre la réponse ; vérifier qu'au moins un bloc d'outil apparaît
(`.tool`) et capturer `.refactor-tmp/tools_live.png`. **Lire l'image.** (Le modèle peut préférer un
autre outil — l'objectif est de confirmer que le chemin live marche, pas un outil exact.)

- [ ] **Step 4 : Mettre à jour la doc**

- `docs/wiki-packages/mekicore.md` : section `tools.py` → lister les 5 outils + `_safe_path` (confinement,
  `MEKICORE_WORKSPACE`) ; préciser que `bash` reste non confiné.
- `ROADMAP.md` : s14 `packages/` → 🟡/✅ (« read/write/edit/grep/glob, confinés au workspace ») ; ajuster l'avancement.
- `README.md` : la section « Ce que ça sait faire » → mentionner que l'agent **lit/écrit/édite des
  fichiers** (plus seulement bash).

- [ ] **Step 5 : Commit**

```bash
git add docs/wiki-packages/mekicore.md ROADMAP.md README.md
git commit -m "doc: outils etendus de l'agent (read/write/edit/grep/glob) — mekicore, ROADMAP, README"
```

---

## Self-review (rempli pendant l'écriture)

**Couverture du spec :** §3 architecture → tous les tasks ; §4 les 5 outils → Tasks 2-3 (+ schémas Task 4) ; §5 confinement `_safe_path` → Task 1 ; §6 rendu front → Task 5 ; §7 erreurs → chaque outil renvoie `Error: …` (Tasks 2-3) ; §8 tests → Tasks 1-4 ; §9 hors périmètre (revert/permissions) volontairement absent.

**Placeholders :** aucun. Note Windows sur le séparateur `grep` (Task 3) = consigne réelle, pas un placeholder.

**Cohérence des types/noms :** fonctions `read_file`/`write_file`/`edit_file`/`grep_files`/`glob_files` (noms internes) ↔ outils `read/write/edit/grep/glob` (via `DISPATCH`) — cohérent entre Tasks 2-4 et les tests. `_safe_path`/`_workspace`/`_tool` cohérents. `views.render_tool(name, summary, output, status)` + `views.tool_summary(args)` utilisés identiquement en Task 5 (app.py + render_thread). `MEKICORE_WORKSPACE` partout.

**Risque :** le séparateur de chemin Windows dans `grep`/`glob` (affichage `\` vs `/`) — couvert par la note de Task 3 (normaliser dans le test, pas un bug outil). Rendu live non-déterministe (le modèle choisit l'outil) — d'où la preuve déterministe en Step 2.
