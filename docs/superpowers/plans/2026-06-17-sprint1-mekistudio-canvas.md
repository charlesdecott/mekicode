# Sprint 1 — mekistudio canvas dans mekicode — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer un front studio à 3 modes (Chat / Canvas / Mix) en NiceGUI, où le canvas (nodes Kernel/Chat/Queue, câbles 45° à comètes) est piloté par notre harness (mekicore/mekihub), avec gouvernance de permissions s15 (3 tiers + couches + ask async) autour de l'exécution d'outils.

**Architecture:** Nouveau package front `packages/mekistudio/` regroupant le chat (déplacé) + un module canvas neuf ; `mekicore` gagne un HookBus + un moteur de permissions ; `mekihub` gagne l'événement `PermissionRequested` et la résolution async du tier *ask*. La géométrie des câbles (`cables.js`/`collision.js`) est vendorée verbatim de mekistudio (pure, testée `node --test`) ; le contenu des nodes est 100 % NiceGUI ; les comètes sont pilotées côté serveur via un helper `impulse_for` porté en Python.

**Tech Stack:** Python 3.11+, NiceGUI, Pydantic v2, PyYAML, asyncio/threading, JS pur (ES2015) + `node --test`, pytest-free smoke tests maison.

**Spec de référence:** `docs/superpowers/specs/2026-06-17-integration-mekistudio-canvas-design.md`

---

## Cartographie des fichiers (créés / modifiés / déplacés)

### mekicore (back, network-free, TDD)
- Créer `packages/mekicore/hooks.py` — `HookBus` (pre_tool vetoable / post_tool).
- Créer `packages/mekicore/permissions.py` — `Decision`, `check_permission`, `load_rules`, `make_permission_hook`.
- Créer `packages/mekicore/permissions.yaml` — règles 3 tiers (adaptées de `src_scratch/config.yaml`).
- Modifier `packages/mekicore/base.py:34-77` — `run_agent(..., hooks=None)` : gate pre_tool/post_tool autour de l'exécution d'outil.

### mekihub (back, network-free, TDD)
- Modifier `packages/mekihub/events.py` — ajouter `PermissionRequested`.
- Modifier `packages/mekihub/hub.py` — `PendingPermissions`, `resolve_permission()`, gate de permission tissé dans `_run_worker`, surcharges session/projet.
- Créer `packages/mekihub/permissions_store.py` — persistance projet `.mekicode/permissions/<project_id>.yaml`.

### Restructuration package (touche 7 fichiers — voir Task 8)
- Créer `packages/mekistudio/__init__.py`.
- Déplacer `packages/mekichat/` → `packages/mekistudio/mekichat/`.
- Modifier sys.path : `mekistudio/mekichat/app.py`, `mekistudio/mekichat/sessions.py`, `packages/mekihub/main.py`, `start-chat.ps1`, `tests/smoke_mekichat.py`.

### mekistudio/mekichat (front)
- Créer `packages/mekistudio/mekichat/component.py` — classe `ChatComponent` (extraite de `app.py:index()`).
- Modifier `packages/mekistudio/mekichat/app.py` — `index()` délègue à `ChatComponent`.
- Modifier `packages/mekistudio/mekichat/views.py` — `render_permission_request()` (carte façon Claude Code).

### mekistudio/mekicanvas (front, neuf)
- Créer `packages/mekistudio/mekicanvas/components/base.py` — `ComponentBase`, `Component` union.
- Créer `packages/mekistudio/mekicanvas/model.py` — `Node`, `CanvasState`.
- Créer `packages/mekistudio/mekicanvas/parenting.py` — `longest_prefix_id` (pur).
- Créer `packages/mekistudio/mekicanvas/registry.py` — `NODE_BUILDERS`, `CANONICAL_PARENT_KIND`, `derive_source_id`, `reconcile_source_links`.
- Créer `packages/mekistudio/mekicanvas/nodes/{kernel,chat,queue}.py` — builders.
- Créer `packages/mekistudio/mekicanvas/impulses.py` — `impulse_for` (porté, pur).
- Créer `packages/mekistudio/mekicanvas/canvas_page.py` — page NiceGUI (world + comètes).
- Vendorer `packages/mekistudio/mekicanvas/static/js/{cables,collision}.js` (+ `.test.js`).
- Créer `packages/mekistudio/mekicanvas/static/js/canvas.js` — pont pan/zoom + câbles + comètes.
- Créer `packages/mekistudio/mekicanvas/static/css/canvas.css`.

### Shell + entrée
- Créer `packages/mekistudio/shell.py` — sélecteur 3 modes + `set_focus`.
- Créer `packages/mekistudio/app.py` — entrée NiceGUI du studio (ui.run).
- Créer `start-studio.ps1` (racine).

### Tests (racine `tests/`)
- Créer `tests/smoke_mekicore_hooks.py`, `tests/smoke_permissions.py`, `tests/smoke_mekicanvas.py`.
- Étendre `tests/smoke_mekihub.py` (permission ask).
- Créer `tests/js/run_js_tests.ps1` (lance `node --test` sur la géométrie).

### Docs (fin de sprint)
- Modifier `ROADMAP.md`, `CLAUDE.md` (entrées), `docs/wiki-packages/` (manuel).

---

## Conventions de test du projet (à respecter)

Les smoke tests mekicode sont des **scripts Python autonomes** (pas pytest), lancés `python tests/<x>.py`, qui posent `sys.path` à la main et s'auto-exécutent via `if __name__ == "__main__"` en imprimant `OK` / `FAIL`. Modèle (cf. `tests/smoke_packages.py:8-24`) :

```python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "packages"
sys.path.insert(0, str(PKG))
sys.path.insert(0, str(PKG / "mekicore"))
```

Chaque nouveau smoke suit ce squelette + une fonction `def main()` qui `assert` les comportements et imprime `print("OK <nom>")`.

---

# PHASE 1 — mekicore : HookBus + Permissions (back, network-free)

## Task 1 : HookBus (pre_tool vetoable / post_tool)

**Files:**
- Create: `packages/mekicore/hooks.py`
- Test: `tests/smoke_mekicore_hooks.py`

- [ ] **Step 1 : Écrire le test qui échoue**

`tests/smoke_mekicore_hooks.py` :

```python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "mekicore"))

from hooks import HookBus  # noqa: E402


def test_post_tool_notify_runs_all():
    bus = HookBus()
    seen = []
    bus.on("post_tool", lambda p: seen.append(("a", p["tool"])))
    bus.on("post_tool", lambda p: seen.append(("b", p["tool"])))
    bus.emit_post_tool("bash", {"command": "ls"}, "out")
    assert seen == [("a", "bash"), ("b", "bash")]


def test_pre_tool_allows_when_no_subscriber():
    bus = HookBus()
    assert bus.emit_pre_tool("bash", {"command": "ls"}) is None


def test_pre_tool_deny_short_circuits():
    bus = HookBus()
    calls = []
    bus.on("pre_tool", lambda p: calls.append(1) or "Denied: nope")
    bus.on("pre_tool", lambda p: calls.append(2) or None)
    reason = bus.emit_pre_tool("bash", {"command": "rm -rf /"})
    assert reason == "Denied: nope"
    assert calls == [1]  # 2e abonné jamais appelé (court-circuit)


def test_pre_tool_subscriber_exception_is_ignored():
    bus = HookBus()
    def boom(_p):
        raise RuntimeError("x")
    bus.on("pre_tool", boom)
    assert bus.emit_pre_tool("read", {"path": "a"}) is None


def main():
    test_post_tool_notify_runs_all()
    test_pre_tool_allows_when_no_subscriber()
    test_pre_tool_deny_short_circuits()
    test_pre_tool_subscriber_exception_is_ignored()
    print("OK smoke_mekicore_hooks")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `python tests/smoke_mekicore_hooks.py`
Expected: `ModuleNotFoundError: No module named 'hooks'`

- [ ] **Step 3 : Implémenter le HookBus**

`packages/mekicore/hooks.py` :

```python
"""hooks.py — bus de hooks synchrone de mekicore.

Deux familles d'événements autour de l'exécution d'un outil :
  - `pre_tool`  : VETOABLE. Chaque abonné reçoit {tool, input} et renvoie soit None
                  (laisse passer), soit une chaîne « raison de refus » (bloque). Le
                  premier refus court-circuite (les abonnés suivants ne sont pas appelés).
  - `post_tool` : notification seule. {tool, input, output}. Renvoie ignoré.

Les permissions (s15) sont un abonné `pre_tool`. Le rendu (tool-cards, impulsions
canvas) n'utilise PAS ce bus : il dérive du flux d'événements mekihub.
"""
from __future__ import annotations

from typing import Any, Callable

PreToolFn = Callable[[dict], "str | None"]
PostToolFn = Callable[[dict], Any]


class HookBus:
    def __init__(self) -> None:
        self._subs: dict[str, list] = {"pre_tool": [], "post_tool": []}

    def on(self, event: str, fn: Callable) -> None:
        """Abonne `fn` à `event` ('pre_tool' | 'post_tool')."""
        self._subs.setdefault(event, []).append(fn)

    def emit_pre_tool(self, tool: str, tool_input: dict) -> "str | None":
        """Renvoie la raison de refus du premier abonné qui refuse, sinon None."""
        payload = {"tool": tool, "input": tool_input}
        for fn in self._subs.get("pre_tool", []):
            try:
                reason = fn(payload)
            except Exception:
                reason = None
            if reason:
                return str(reason)
        return None

    def emit_post_tool(self, tool: str, tool_input: dict, output: str) -> None:
        payload = {"tool": tool, "input": tool_input, "output": output}
        for fn in self._subs.get("post_tool", []):
            try:
                fn(payload)
            except Exception:
                pass
```

- [ ] **Step 4 : Lancer le test, vérifier le succès**

Run: `python tests/smoke_mekicore_hooks.py`
Expected: `OK smoke_mekicore_hooks`

- [ ] **Step 5 : py_compile + commit**

```bash
python -m py_compile packages/mekicore/hooks.py tests/smoke_mekicore_hooks.py
git add packages/mekicore/hooks.py tests/smoke_mekicore_hooks.py
git commit -m "feat(mekicore): HookBus pre_tool (vetoable) / post_tool"
```

---

## Task 2 : Règles de permission (config YAML 3 tiers)

**Files:**
- Create: `packages/mekicore/permissions.yaml`

- [ ] **Step 1 : Écrire le fichier de règles**

Adapté de `src_scratch/config.yaml` (section `permissions`), motifs ajustés à NOS outils minuscules (`bash`/`read`/`write`/`edit`/`grep`/`glob`). Le motif est testé sur la **première valeur d'input** (commande pour bash, chemin pour les outils fichiers).

`packages/mekicore/permissions.yaml` :

```yaml
# Gouvernance s15 — 3 tiers. Évaluation : always_deny -> always_allow -> ask_user -> ALLOW par défaut.
# `pattern` = regex Python (re.IGNORECASE) testée sur la 1re valeur d'input de l'outil.
permissions:
  always_deny:
    - { pattern: "rm\\s+-rf\\s+[/~]",        reason: "Suppression récursive racine bloquée" }
    - { pattern: "\\bsudo\\b",                reason: "Élévation de privilèges bloquée" }
    - { pattern: "\\b(shutdown|reboot|halt)\\b", reason: "Commandes d'arrêt système bloquées" }
    - { pattern: ":\\(\\)\\s*\\{",            reason: "Fork bomb bloquée" }
  always_allow:
    - { pattern: "^ls( |$)",                  reason: "Lister un dossier est sûr" }
    - { pattern: "^git (status|log|diff|show|branch|tag)", reason: "Git lecture seule sûr" }
    - { pattern: "^(cat|head|tail|pwd|whoami|echo)\\b", reason: "Lecture/inspection sûre" }
  ask_user:
    - { pattern: "^rm ",                      reason: "Suppression de fichier" }
    - { pattern: "^git (commit|push|merge|rebase|reset)", reason: "Écriture git" }
    - { pattern: "\\.env",                    reason: "Accès à un fichier .env" }
    - { pattern: "\\b(curl|wget|Invoke-WebRequest)\\b", reason: "Accès réseau sortant" }
```

- [ ] **Step 2 : Vérifier que le YAML parse**

Run: `python -c "import yaml; print(list(yaml.safe_load(open('packages/mekicore/permissions.yaml'))['permissions']))"`
Expected: `['always_deny', 'always_allow', 'ask_user']`

- [ ] **Step 3 : Commit**

```bash
git add packages/mekicore/permissions.yaml
git commit -m "feat(mekicore): regles permissions s15 (3 tiers) en YAML"
```

---

## Task 3 : Moteur de permissions (check_permission + couches)

**Files:**
- Create: `packages/mekicore/permissions.py`
- Test: `tests/smoke_permissions.py`

- [ ] **Step 1 : Écrire le test qui échoue**

`tests/smoke_permissions.py` :

```python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "mekicore"))

from permissions import (  # noqa: E402
    ALLOW, ASK, DENY, Decision, check_permission, load_rules,
)

RULES = {
    "always_deny": [{"pattern": r"rm\s+-rf\s+/", "reason": "root"}],
    "always_allow": [{"pattern": r"^ls( |$)", "reason": "ls"}],
    "ask_user": [{"pattern": r"^rm ", "reason": "del"}],
}


def test_deny_wins():
    d = check_permission("bash", "rm -rf /", RULES)
    assert d.kind == DENY and "root" in d.reason


def test_allow():
    d = check_permission("bash", "ls -la", RULES)
    assert d.kind == ALLOW


def test_ask():
    d = check_permission("bash", "rm foo.txt", RULES)
    assert d.kind == ASK and "del" in d.reason


def test_default_allow():
    d = check_permission("bash", "echo hi", RULES)
    assert d.kind == ALLOW


def test_session_override_promotes_to_allow():
    # une surcharge session 'allow' du motif rm doit court-circuiter le ask
    overrides = {"always_allow": [{"pattern": r"^rm ", "reason": "ok session"}]}
    d = check_permission("bash", "rm foo.txt", RULES, overrides=overrides)
    assert d.kind == ALLOW


def test_project_override_blacklist():
    overrides = {"always_deny": [{"pattern": r"^git push", "reason": "no push"}]}
    d = check_permission("bash", "git push origin main", RULES, overrides=overrides)
    assert d.kind == DENY and "no push" in d.reason


def test_load_rules_from_yaml():
    rules = load_rules()  # lit packages/mekicore/permissions.yaml
    assert "always_deny" in rules and "ask_user" in rules


def main():
    for fn in (test_deny_wins, test_allow, test_ask, test_default_allow,
               test_session_override_promotes_to_allow, test_project_override_blacklist,
               test_load_rules_from_yaml):
        fn()
    print("OK smoke_permissions")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python tests/smoke_permissions.py`
Expected: `ModuleNotFoundError: No module named 'permissions'`

- [ ] **Step 3 : Implémenter le moteur**

`packages/mekicore/permissions.py` :

```python
"""permissions.py — gouvernance s15, 3 tiers + résolution en couches.

Ordre d'évaluation (court-circuit) : always_deny -> always_allow -> ask_user -> ALLOW.
Résolution en couches : on fusionne `overrides` (session puis projet) AVANT les règles
globales, en préfixant chaque tier. Une surcharge `always_allow` d'un motif l'emporte
donc sur un `ask_user` global (et inversement pour `always_deny`).

`check_permission` est PUR (aucune I/O, aucun input()). Le tier ASK est juste signalé ;
c'est l'appelant (mekihub) qui orchestre la demande asynchrone à l'utilisateur.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

ALLOW = "allow"
DENY = "deny"
ASK = "ask"

_TIERS = ("always_deny", "always_allow", "ask_user")
_RULES_PATH = Path(__file__).resolve().parent / "permissions.yaml"


@dataclass
class Decision:
    kind: str          # ALLOW | DENY | ASK
    reason: str = ""


def load_rules(path: Path | None = None) -> dict:
    """Section `permissions` du YAML — 3 tiers, listes vides par défaut."""
    p = path or _RULES_PATH
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    perms = data.get("permissions") or {}
    return {tier: list(perms.get(tier) or []) for tier in _TIERS}


def _merge(base: dict, overrides: dict | None) -> dict:
    """Fusionne overrides EN TÊTE de chaque tier (priorité aux surcharges)."""
    if not overrides:
        return base
    out: dict = {}
    for tier in _TIERS:
        out[tier] = list(overrides.get(tier) or []) + list(base.get(tier) or [])
    return out


def _hit(rules_tier: list, text: str) -> dict | None:
    for rule in rules_tier:
        if re.search(rule["pattern"], text, re.IGNORECASE):
            return rule
    return None


def check_permission(
    tool: str, input_str: str, rules: dict, *, overrides: dict | None = None
) -> Decision:
    """Décision pour un appel d'outil. Pur, sans effet de bord."""
    eff = _merge(rules, overrides)
    r = _hit(eff["always_deny"], input_str)
    if r:
        return Decision(DENY, f"Denied: {r.get('reason', 'blocked by policy')}")
    if _hit(eff["always_allow"], input_str):
        return Decision(ALLOW)
    r = _hit(eff["ask_user"], input_str)
    if r:
        return Decision(ASK, r.get("reason", "requires user confirmation"))
    return Decision(ALLOW)


def make_permission_hook(rules, ask_resolver, *, overrides_provider=None):
    """Fabrique un abonné `pre_tool` du HookBus.

    - `rules` : dict 3 tiers (load_rules()).
    - `ask_resolver(tool, target, reason) -> bool` : BLOQUANT. Renvoie True si autorisé.
      (mekihub fournit un resolver qui publie PermissionRequested + attend la décision.)
    - `overrides_provider() -> dict | None` : surcharges courantes (session+projet fusionnées).

    Renvoie une fonction hook(payload) -> str|None (raison de refus, ou None).
    """
    def hook(payload: dict) -> "str | None":
        tool = payload.get("tool", "")
        tool_input = payload.get("input") or {}
        target = str(next(iter(tool_input.values()), "")) if tool_input else ""
        ov = overrides_provider() if overrides_provider else None
        d = check_permission(tool, target, rules, overrides=ov)
        if d.kind == DENY:
            return d.reason
        if d.kind == ASK:
            allowed = ask_resolver(tool, target, d.reason)
            return None if allowed else f"Denied: refusé par l'utilisateur ({d.reason})"
        return None
    return hook
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `python tests/smoke_permissions.py`
Expected: `OK smoke_permissions`

- [ ] **Step 5 : py_compile + commit**

```bash
python -m py_compile packages/mekicore/permissions.py tests/smoke_permissions.py
git add packages/mekicore/permissions.py tests/smoke_permissions.py
git commit -m "feat(mekicore): moteur permissions s15 (check_permission + couches + make_permission_hook)"
```

---

## Task 4 : Brancher le HookBus dans `run_agent`

**Files:**
- Modify: `packages/mekicore/base.py:34-77`
- Test: `tests/smoke_mekicore_hooks.py` (étendre)

> Contexte : `run_agent` exécute les outils en ligne dans sa boucle (`for tc in resp.tool_calls`). On insère la gate pre_tool AVANT `handler(...)` et le notify post_tool APRÈS. `dispatch_tools` (base.py:14-31) reste tel quel (chemin REPL).

- [ ] **Step 1 : Étendre le test (gate de veto dans run_agent)**

Ajouter à `tests/smoke_mekicore_hooks.py` (avant `main`), avec une fausse LLM minimale :

```python
def test_run_agent_pre_tool_veto_blocks_handler():
    sys.path.insert(0, str(ROOT / "packages" / "mekicore"))
    from base import run_agent
    from events import ToolStarted, ToolFinished, RunFinished
    from hooks import HookBus

    class _Resp:
        def __init__(self, tool_calls, finish):
            self.message = {"role": "assistant", "content": ""}
            self.text = ""
            self.finish_reason = finish
            self.tool_calls = tool_calls

    class _TC:
        def __init__(self, id, name, args):
            self.id, self.name, self.arguments = id, name, args

    class _LLM:
        def __init__(self):
            self.n = 0
        def complete(self, messages, tools=None):
            self.n += 1
            if self.n == 1:
                return _Resp([_TC("1", "bash", {"command": "rm -rf /"})], "tool_calls")
            return _Resp([], "stop")

    executed = []
    dispatch = {"bash": lambda a: executed.append(a) or "ran"}
    bus = HookBus()
    bus.on("pre_tool", lambda p: "Denied: policy" if "rm -rf" in str(p["input"]) else None)

    events = list(run_agent([], _LLM(), [], dispatch, hooks=bus))
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert executed == []                       # handler jamais appelé
    assert finished and "Denied: policy" in finished[0].output
    assert any(isinstance(e, RunFinished) for e in events)
```

Et l'ajouter dans `main()` : `test_run_agent_pre_tool_veto_blocks_handler()`.

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python tests/smoke_mekicore_hooks.py`
Expected: `TypeError: run_agent() got an unexpected keyword argument 'hooks'`

- [ ] **Step 3 : Modifier `run_agent`**

Dans `packages/mekicore/base.py`, signature et boucle d'outils. Remplacer la signature `def run_agent(messages, llm, tools, dispatch, *, stream=False):` par :

```python
def run_agent(messages, llm, tools, dispatch, *, stream=False, hooks=None):
```

Et dans la boucle d'exécution des outils (l'actuelle `for tc in resp.tool_calls:`), remplacer le corps par :

```python
        for tc in resp.tool_calls:
            yield ToolStarted(tc.id, tc.name, tc.arguments)
            deny = hooks.emit_pre_tool(tc.name, tc.arguments) if hooks else None
            if deny:
                output = str(deny)
            else:
                handler = dispatch.get(tc.name)
                try:
                    output = handler(tc.arguments) if handler else f"Error: Unknown tool '{tc.name}'"
                except Exception as e:
                    output = f"Error during tool execution: {e}"
                output = str(output)
                if hooks:
                    hooks.emit_post_tool(tc.name, tc.arguments, output)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": output})
            yield ToolFinished(tc.id, tc.name, output)
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `python tests/smoke_mekicore_hooks.py`
Expected: `OK smoke_mekicore_hooks`

- [ ] **Step 5 : Non-régression existante + commit**

```bash
python tests/smoke_packages.py
python -m py_compile packages/mekicore/base.py
git add packages/mekicore/base.py tests/smoke_mekicore_hooks.py
git commit -m "feat(mekicore): run_agent accepte un HookBus (gate pre_tool / notify post_tool)"
```

---

# PHASE 2 — Restructuration du package front

## Task 5 : Déplacer mekichat sous packages/mekistudio/ et recâbler sys.path

**Files:**
- Create: `packages/mekistudio/__init__.py`
- Move: `packages/mekichat/` → `packages/mekistudio/mekichat/`
- Modify: `packages/mekistudio/mekichat/app.py` (sys.path), `packages/mekistudio/mekichat/sessions.py` (sys.path), `packages/mekihub/main.py:48`, `start-chat.ps1:5`, `tests/smoke_mekichat.py:11`

> ⚠️ Cette tâche ne change aucune logique — seulement l'emplacement et les `sys.path.insert()`. La vérif = les smoke tests passent et le front se lance.

- [ ] **Step 1 : Déplacer le dossier (git mv)**

```bash
git mv packages/mekichat packages/mekistudio_tmp
mkdir -p packages/mekistudio
git mv packages/mekistudio_tmp packages/mekistudio/mekichat
```

(Si `git mv` du dossier en deux temps pose souci sous Windows, faire : `mkdir packages/mekistudio` puis `git mv packages/mekichat packages/mekistudio/mekichat`.)

- [ ] **Step 2 : Créer `packages/mekistudio/__init__.py`**

```python
"""mekistudio — package front (NiceGUI) : chat + canvas + coquille 3 modes.

Regroupe les modules d'UI. La couche back/logique (mekicore, mekillm, mekihub)
reste en packages frères, importée par ce package (jamais l'inverse).
"""
```

- [ ] **Step 3 : Recâbler `packages/mekistudio/mekichat/app.py` (lignes 10-13)**

Remplacer le bloc sys.path actuel par (le fichier descend d'un niveau supplémentaire) :

```python
HERE = Path(__file__).resolve().parent            # packages/mekistudio/mekichat/
STUDIO = HERE.parent                              # packages/mekistudio/
PACKAGES = STUDIO.parent                          # packages/
sys.path.insert(0, str(HERE))                     # sessions, views, component (locaux)
sys.path.insert(0, str(PACKAGES))                 # mekillm, mekihub (packages/)
sys.path.insert(0, str(PACKAGES / "mekicore"))    # base, tools, events
```

- [ ] **Step 4 : Recâbler `packages/mekistudio/mekichat/sessions.py` (ligne 9)**

Remplacer :

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))   # packages/ → mekihub
```

- [ ] **Step 5 : Recâbler `packages/mekihub/main.py:48`**

```python
    sys.path.insert(0, str(HERE.parent / "mekistudio" / "mekichat"))
    import app  # noqa: F401
```

- [ ] **Step 6 : Recâbler `start-chat.ps1:5` et `tests/smoke_mekichat.py:11`**

`start-chat.ps1` ligne 5 : `python packages/mekistudio/mekichat/app.py`

`tests/smoke_mekichat.py` ligne 11 :
```python
sys.path.insert(0, str(ROOT / "packages" / "mekistudio" / "mekichat"))  # import sessions
```

- [ ] **Step 7 : Vérifier (smoke + lancement)**

```bash
python tests/smoke_mekichat.py     # Expected: OK ...
python tests/smoke_mekihub.py      # Expected: OK ...
python tests/smoke_packages.py     # Expected: OK ...
python -c "import sys; sys.path.insert(0,'packages'); sys.path.insert(0,'packages/mekistudio/mekichat'); import app; print('import app OK')"
```

- [ ] **Step 8 : Commit**

```bash
git add -A
git commit -m "refactor(front): mekichat -> packages/mekistudio/mekichat + recablage sys.path (7 fichiers)"
```

---

# PHASE 3 — mekihub : PermissionRequested + résolution async du tier ask

## Task 6 : Événement PermissionRequested

**Files:**
- Modify: `packages/mekihub/events.py`

- [ ] **Step 1 : Ajouter la dataclass**

Ajouter dans `packages/mekihub/events.py` :

```python
@dataclass
class PermissionRequested:
    request_id: str
    item_id: str           # run/queue item concerné
    tool: str
    target: str            # 1re valeur d'input, tronquée
    reason: str
    options: list          # ["once","session","project","deny","blacklist"]
    actor_id: str | None   # auteur autorisé à trancher (None => admin requis)
```

- [ ] **Step 2 : py_compile + commit**

```bash
python -m py_compile packages/mekihub/events.py
git add packages/mekihub/events.py
git commit -m "feat(mekihub): event PermissionRequested"
```

---

## Task 7 : Persistance des surcharges projet

**Files:**
- Create: `packages/mekihub/permissions_store.py`
- Test: `tests/smoke_permissions.py` (étendre)

- [ ] **Step 1 : Écrire le test qui échoue**

Ajouter dans `tests/smoke_permissions.py` :

```python
def test_project_permissions_roundtrip(tmp=Path(__file__).resolve().parent.parent / ".mekicode-test-perms"):
    sys.path.insert(0, str(ROOT / "packages"))
    from mekihub.permissions_store import load_project_overrides, add_project_rule
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    add_project_rule("proj1", "always_allow", r"^git push", "ok", base_dir=tmp)
    ov = load_project_overrides("proj1", base_dir=tmp)
    assert any(r["pattern"] == r"^git push" for r in ov["always_allow"])
    shutil.rmtree(tmp, ignore_errors=True)
```

Et l'appeler dans `main()`.

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python tests/smoke_permissions.py`
Expected: `ModuleNotFoundError: No module named 'mekihub.permissions_store'`

- [ ] **Step 3 : Implémenter**

`packages/mekihub/permissions_store.py` :

```python
"""permissions_store.py — surcharges de permission persistées par projet.

Fichier : <base>/permissions/<project_id>.yaml, même schéma 3 tiers que mekicore.
Couche projet de la résolution en couches (session = RAM ; projet = ici ; global = mekicore).
"""
from __future__ import annotations

from pathlib import Path

import yaml

_TIERS = ("always_deny", "always_allow", "ask_user")
_DEFAULT_BASE = Path.cwd() / ".mekicode"


def _path(project_id: str, base_dir: Path | None) -> Path:
    base = base_dir or _DEFAULT_BASE
    return base / "permissions" / f"{project_id}.yaml"


def load_project_overrides(project_id: str, *, base_dir: Path | None = None) -> dict:
    p = _path(project_id, base_dir)
    if not p.exists():
        return {tier: [] for tier in _TIERS}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    perms = data.get("permissions") or {}
    return {tier: list(perms.get(tier) or []) for tier in _TIERS}


def add_project_rule(project_id: str, tier: str, pattern: str, reason: str,
                     *, base_dir: Path | None = None) -> None:
    assert tier in _TIERS, tier
    cur = load_project_overrides(project_id, base_dir=base_dir)
    if not any(r.get("pattern") == pattern for r in cur[tier]):
        cur[tier].append({"pattern": pattern, "reason": reason})
    p = _path(project_id, base_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump({"permissions": cur}, allow_unicode=True), encoding="utf-8")
```

- [ ] **Step 4 : Lancer, vérifier le succès**

Run: `python tests/smoke_permissions.py`
Expected: `OK smoke_permissions`

- [ ] **Step 5 : commit**

```bash
python -m py_compile packages/mekihub/permissions_store.py
git add packages/mekihub/permissions_store.py tests/smoke_permissions.py
git commit -m "feat(mekihub): surcharges permission persistees par projet"
```

---

## Task 8 : Résolution async du tier ask dans le worker

**Files:**
- Modify: `packages/mekihub/hub.py` (`_Room`, `_run_worker`, + `resolve_permission`)
- Test: `tests/smoke_mekihub.py` (étendre)

> Mécanique cross-thread : `run_agent` tourne dans un thread (`asyncio.to_thread(next, gen)`). Le hook de permission appelle `ask_resolver(...)` qui BLOQUE sur une `queue.Queue(maxsize=1)` par `request_id`, après avoir publié `PermissionRequested` sur la boucle asyncio via `loop.call_soon_threadsafe`. `resolve_permission()` (appelé depuis un handler UI) applique la portée choisie puis `q.put(decision)`, ce qui débloque le thread. `timeout` → deny.

- [ ] **Step 1 : Écrire le test (résolution « once = allow »)**

Ajouter dans `tests/smoke_mekihub.py` un test qui : construit un hub avec un `FakeLLM` qui demande l'outil `bash "rm x"` (motif `ask_user`), s'abonne, attend l'event `PermissionRequested`, appelle `resolve_permission(request_id, "once", actor)`, et vérifie que le run se termine sans `Denied`. (S'inspirer du squelette d'abonnement existant de `smoke_mekihub.py`.) Pseudostructure :

```python
async def test_permission_ask_allow_once():
    hub = _make_hub_with_fake_llm(reply_tool=("bash", {"command": "rm x.txt"}))
    sid = hub.store.create(...).id
    author = Author(id="u1", name="u1", color="#fff")
    seen = []
    async def consume():
        async for ev in hub.subscribe(sid):
            seen.append(ev)
            if type(ev).__name__ == "PermissionRequested":
                hub.resolve_permission(ev.request_id, "once", actor=author)
            if type(ev).__name__ == "Idle":
                return
    hub.submit(sid, "supprime x", author)
    await asyncio.wait_for(consume(), timeout=5)
    assert any(type(e).__name__ == "PermissionRequested" for e in seen)
    tool_fin = [e for e in seen if type(e).__name__ == "ToolFinished"]
    assert tool_fin and "Denied" not in tool_fin[0].output
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python tests/smoke_mekihub.py`
Expected: échec sur `hub.resolve_permission` (AttributeError) ou absence de `PermissionRequested`.

- [ ] **Step 3 : Ajouter l'état permission au `_Room`**

Dans `packages/mekihub/hub.py`, classe `_Room.__init__`, ajouter :

```python
        self.pending_permissions: dict = {}    # request_id -> queue.Queue(maxsize=1)
        self.session_overrides: dict = {"always_deny": [], "always_allow": [], "ask_user": []}
```

- [ ] **Step 4 : Construire le HookBus + gate dans `_run_worker`**

Dans `_run_worker`, là où `dispatch` est préparé (avant `gen = run_agent(...)`), insérer la construction du bus et passer `hooks=bus` à `run_agent`. Imports en tête de `hub.py` : `import queue, uuid`, et :

```python
        # --- gouvernance permissions (s15) ---
        import sys as _sys
        _sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "mekicore"))
        from hooks import HookBus
        from permissions import load_rules, make_permission_hook
        from mekihub.permissions_store import load_project_overrides

        loop = asyncio.get_running_loop()
        rules = load_rules()

        def _overrides_provider(_room=room, _sess=sess):
            proj = load_project_overrides(_sess.project_id)
            merged = {t: list(room.session_overrides.get(t, [])) + list(proj.get(t, []))
                      for t in ("always_deny", "always_allow", "ask_user")}
            return merged

        def _ask_resolver(tool, target, reason, _room=room, _item=item, _loop=loop, _sid=session_id):
            request_id = uuid.uuid4().hex[:8]
            q: "queue.Queue" = queue.Queue(maxsize=1)
            _room.pending_permissions[request_id] = q
            actor_id = _item.author.id if _item.author else None
            ev = events_mod.PermissionRequested(
                request_id=request_id, item_id=_item.item_id, tool=tool,
                target=target[:120], reason=reason,
                options=["once", "session", "project", "deny", "blacklist"], actor_id=actor_id,
            )
            _loop.call_soon_threadsafe(lambda: self._publish(_sid, ev))
            try:
                decision = q.get(timeout=120)      # bloque le thread run_agent
            except queue.Empty:
                decision = "deny"                  # timeout -> deny
            finally:
                _room.pending_permissions.pop(request_id, None)
            return decision in ("once", "session", "project")

        bus = HookBus()
        bus.on("pre_tool", make_permission_hook(rules, _ask_resolver, overrides_provider=_overrides_provider))
```

(Adapter `events_mod` au nom déjà importé pour les events dans `hub.py` ; si c'est `import events as ev` côté hub, utiliser `ev.PermissionRequested`.) Puis modifier l'appel : `gen = run_agent(sess.messages, llm, tools_run, dispatch, stream=True, hooks=bus)`.

- [ ] **Step 5 : Implémenter `resolve_permission`**

Ajouter à la classe `SessionHub` :

```python
    def resolve_permission(self, request_id: str, choice: str, *, actor=None) -> bool:
        """Tranche un 'ask'. choice ∈ {once, session, project, deny, blacklist}.
        Applique la portée (session/projet/blacklist) puis débloque le worker.
        Renvoie False si request_id inconnu (déjà résolu / expiré)."""
        for sid, room in self._rooms.items():
            q = room.pending_permissions.get(request_id)
            if q is None:
                continue
            # portée
            if choice in ("session", "project", "blacklist"):
                # on a besoin du motif : ici on autorise/bloque le 'target' exact (ancrage litéral)
                import re as _re
                from mekihub.permissions_store import add_project_rule
                # le motif est fourni par l'appelant via _pending_targets (cf. note), fallback: literal
                pat, reason = self._pending_meta.get(request_id, ("", "ask"))
                pat = pat or _re.escape(self._pending_meta.get(request_id, ("", ""))[0])
                if choice == "session":
                    room.session_overrides["always_allow"].append({"pattern": pat, "reason": "session"})
                elif choice == "project":
                    sess = self.store.load(sid)
                    add_project_rule(sess.project_id, "always_allow", pat, "project")
                elif choice == "blacklist":
                    sess = self.store.load(sid)
                    add_project_rule(sess.project_id, "always_deny", pat, "blacklist")
            try:
                q.put_nowait(choice)
            except Exception:
                pass
            return True
        return False
```

> Note d'implémentation : pour porter le **motif** (et non le seul `target` littéral) dans `resolve_permission`, stocker dans `_ask_resolver` un `self._pending_meta[request_id] = (re.escape(target), reason)` au moment de la demande (ancrage littéral du target ; suffisant pour Sprint 1 — un raffinement « motif de la règle » est différé). Initialiser `self._pending_meta = {}` dans `SessionHub.__init__`.

- [ ] **Step 6 : Lancer, vérifier le succès**

Run: `python tests/smoke_mekihub.py`
Expected: `OK ...` (dont `test_permission_ask_allow_once`)

- [ ] **Step 7 : Vérifier deny par timeout (test rapide)**

Ajouter `test_permission_ask_timeout_denies` qui ne résout jamais et patche le timeout à ~1 s (paramétrer le timeout via une variable d'env `MEKICODE_ASK_TIMEOUT` lue dans `_ask_resolver`, défaut 120). Vérifier `Denied` dans le ToolFinished.

- [ ] **Step 8 : commit**

```bash
python -m py_compile packages/mekihub/hub.py
git add packages/mekihub/hub.py tests/smoke_mekihub.py
git commit -m "feat(mekihub): resolution async du tier ask (PermissionRequested + resolve_permission + couches)"
```

---

# PHASE 4 — ChatComponent (extraction)

## Task 9 : Extraire `ChatComponent` de `index()`

**Files:**
- Create: `packages/mekistudio/mekichat/component.py`
- Modify: `packages/mekistudio/mekichat/app.py:149-576`
- Test: visuel (Playwright) — voir Task 18

> `ChatComponent(container, hub, session_id, author)` encapsule thread + composer + queue + presence + `_subscribe_loop` + `_render_hub_event` + `send`. Reste **page-level** dans app.py : CSS, résolution `author_for_client()` (contexte de page), sidebar, navigation projet/scope/session.

- [ ] **Step 1 : Créer `component.py` (squelette + UI + boucle)**

`packages/mekistudio/mekichat/component.py` — déplacer le corps de `_subscribe_loop`, `_render_hub_event`, `send`, et les helpers `_rebuild_queue/_set_presence/_clear_thinking/_scroll_bottom` depuis `app.py`, en remplaçant les closures `*_ref` par des attributs `self.*`. Structure :

```python
"""component.py — ChatComponent NiceGUI réutilisable (onglet, node canvas, panneau focus)."""
from __future__ import annotations

import asyncio

from nicegui import ui

import views
from mekihub.hub import SessionHub
from mekihub.session import Author


class ChatComponent:
    def __init__(self, container: ui.element, hub: SessionHub, session_id: str, author: Author):
        self._hub = hub
        self._sid = session_id
        self._author = author
        self._thread_inner = None
        self._thinking = None
        self._stream = {"body": None, "lbl": None, "text": ""}
        self._bars = {"presence": None, "queue": None}
        self._queue_rows: dict = {}
        self._wt_cards: dict = {}
        self._handles: dict = {}
        self._build(container)
        ui.timer(0.1, self._subscribe_loop, once=True)

    def _build(self, container: ui.element) -> None:
        with container:
            self._thread_inner = ui.element("div").classes("thread-inner")
            with ui.element("div").classes("queue-bar") as qb:
                self._bars["queue"] = qb
            with ui.element("div").classes("presence-bar") as pb:
                self._bars["presence"] = pb
            with ui.element("div").classes("composer"):
                box = ui.textarea(placeholder="Écris à l'agent…").classes("composer-input")
                async def _send(_=None):
                    text = (box.value or "").strip()
                    if text:
                        box.value = ""
                        await self.send(text)
                box.on("keydown.enter", _send)
                ui.button("Envoyer", on_click=_send).classes("composer-send")

    async def send(self, text: str) -> None:
        self._hub.submit(self._sid, text, self._author)

    async def _subscribe_loop(self) -> None:
        self._hub.join(self._sid, self._author)
        try:
            async for event in self._hub.subscribe(self._sid):
                try:
                    self._render_hub_event(event)
                    self._scroll_bottom()
                except RuntimeError as exc:
                    if "deleted" in str(exc):
                        break
                    raise
        finally:
            self._hub.leave(self._sid, self._author)

    def _render_hub_event(self, event) -> None:
        ...  # déplacer le corps de app.py:_render_hub_event (16 branches), refs -> self.*
```

> Reprendre EXACTEMENT le mapping des 16 branches (Snapshot, PresenceChanged, QueueEnqueued, QueueItemDeleted, RunStarted, MessagePosted, AgentDelta, AgentDone, ToolStarted, ToolFinished, RunError, WorktreeProposed, WorktreeCreated, WorktreeRejected, RunFinished, Idle) de `app.py:280-420`, en remplaçant `thread_ref["inner"]`→`self._thread_inner`, `stream_ref`→`self._stream`, `bars_ref`→`self._bars`, `queue_rows`→`self._queue_rows`, `wt_cards`→`self._wt_cards`, `handles`→`self._handles`. La discrimination reste par `type(event).__name__` (collision de modules `events`, cf. gotcha #11 du rapport).

- [ ] **Step 2 : Ajouter la branche PermissionRequested**

Dans `_render_hub_event`, ajouter une 17e branche :

```python
        if name == "PermissionRequested":
            with self._thread_inner:
                card = views.render_permission_request(
                    event.tool, event.target, event.reason, event.options,
                    on_choice=lambda choice, rid=event.request_id: self._hub.resolve_permission(
                        rid, choice, actor=self._author),
                )
            self._handles["perm:" + event.request_id] = card
```

- [ ] **Step 3 : Alléger `index()` dans app.py**

Dans `app.py:index()`, garder CSS + chargement session + `author = realtime.author_for_client()` + sidebar + handlers navigation. Remplacer la construction UI principale (≈ lignes 454-572) par :

```python
        with main:
            # topbar conservée (channel + chips), puis :
            chat = ChatComponent(container=main, hub=_get_hub(),
                                 session_id=current.id, author=author_ref["author"])
```

Et supprimer de `index()` : `_subscribe_loop`, `_render_hub_event`, `send`, `_rebuild_queue`, `_set_presence`, `_clear_thinking`, `_scroll_bottom` (déplacés dans `ChatComponent`). Ajouter `from component import ChatComponent` en tête (import local, résolu par sys.path de l'app).

- [ ] **Step 4 : Vérifier le lancement (sans réseau, FakeLLM)**

Run: `python packages/mekistudio/mekichat/app.py` puis Ctrl+C après ~5 s (vérifier qu'il démarre sans exception d'import). Vérif visuelle complète déléguée à Task 18.

- [ ] **Step 5 : commit**

```bash
python -m py_compile packages/mekistudio/mekichat/component.py packages/mekistudio/mekichat/app.py
git add packages/mekistudio/mekichat/component.py packages/mekistudio/mekichat/app.py
git commit -m "refactor(mekichat): extraction ChatComponent reutilisable + branche PermissionRequested"
```

---

## Task 10 : Carte de permission (vue)

**Files:**
- Modify: `packages/mekistudio/mekichat/views.py`

- [ ] **Step 1 : Ajouter `render_permission_request`**

Calqué sur `render_worktree_proposal` (views.py:276-293). 5 boutons façon Claude Code :

```python
def render_permission_request(tool, target, reason, options, on_choice):
    """Carte de demande de permission (style Phosphore). `on_choice(choice)` au clic."""
    labels = {
        "once": "Autoriser une fois", "session": "Autoriser (session)",
        "project": "Autoriser (projet)", "deny": "Refuser",
        "blacklist": "Refuser + ne plus demander",
    }
    card = ui.element("div").classes("perm-request")
    with card:
        with ui.element("div").classes("perm-head"):
            ui.label(f"⚿ permission : {tool}").classes("perm-title")
        ui.label(f"{target}").classes("perm-target")
        ui.label(reason).classes("perm-reason")
        with ui.element("div").classes("perm-actions"):
            for opt in options:
                danger = opt in ("deny", "blacklist")
                btn = ui.button(labels.get(opt, opt),
                                on_click=lambda _=None, o=opt: (on_choice(o), card.delete()))
                btn.classes("perm-btn " + ("reject" if danger else "approve"))
    return card
```

(Corriger le glyphe titre en `"⚿ permission : "` ou similaire — pas d'emoji invalide.)

- [ ] **Step 2 : py_compile + commit**

```bash
python -m py_compile packages/mekistudio/mekichat/views.py
git add packages/mekistudio/mekichat/views.py
git commit -m "feat(mekichat): carte de permission (5 choix facon Claude Code)"
```

---

# PHASE 5 — mekicanvas : modèle, géométrie, impulsions (pur, TDD)

## Task 11 : Composants & modèle Node

**Files:**
- Create: `packages/mekistudio/mekicanvas/__init__.py`, `components/__init__.py`, `components/base.py`, `model.py`
- Test: `tests/smoke_mekicanvas.py`

- [ ] **Step 1 : Écrire le test qui échoue**

`tests/smoke_mekicanvas.py` :

```python
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "mekistudio"))

from mekicanvas.model import Node, CanvasState  # noqa: E402
from mekicanvas.components.base import HeaderComponent, NodeComponent  # noqa: E402


def test_node_serializes_roundtrip():
    n = Node(kind="kernel", x=1, y=2, root=NodeComponent(children=[HeaderComponent(text="K")]))
    js = n.model_dump_json()
    n2 = Node.model_validate_json(js)
    assert n2.kind == "kernel" and n2.root.children[0].type == "header"


def main():
    test_node_serializes_roundtrip()
    print("OK smoke_mekicanvas")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2 : Lancer, vérifier l'échec** — `python tests/smoke_mekicanvas.py` → `ModuleNotFoundError: mekicanvas`

- [ ] **Step 3 : Implémenter components/base.py + model.py**

`packages/mekistudio/mekicanvas/components/base.py` (Union discriminée minimale Sprint 1 : Header, Layout, Node, Chat, Queue) :

```python
from __future__ import annotations

import uuid
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


def new_id() -> str:
    return uuid.uuid4().hex


class ComponentBase(BaseModel):
    id: str = Field(default_factory=new_id)


class HeaderComponent(ComponentBase):
    type: Literal["header"] = "header"
    text: str = ""
    level: int = Field(default=1, ge=1, le=4)


class ChatComponentSpec(ComponentBase):
    type: Literal["chat"] = "chat"
    title: str = "chat"


class QueueComponentSpec(ComponentBase):
    type: Literal["queue"] = "queue"
    title: str = "file d'attente"


class LayoutComponent(ComponentBase):
    type: Literal["layout"] = "layout"
    direction: Literal["column", "row"] = "column"
    gap: int = 8
    children: list["Component"] = Field(default_factory=list)


class NodeComponent(ComponentBase):
    type: Literal["node"] = "node"
    children: list["Component"] = Field(default_factory=list)


Component = Annotated[
    Union[NodeComponent, LayoutComponent, HeaderComponent, ChatComponentSpec, QueueComponentSpec],
    Field(discriminator="type"),
]

LayoutComponent.model_rebuild()
NodeComponent.model_rebuild()
```

`packages/mekistudio/mekicanvas/components/__init__.py` :
```python
from .base import (  # noqa: F401
    ChatComponentSpec, Component, ComponentBase, HeaderComponent, LayoutComponent,
    NodeComponent, QueueComponentSpec, new_id,
)
```

`packages/mekistudio/mekicanvas/model.py` :
```python
from __future__ import annotations

from pydantic import BaseModel, Field

from .components.base import NodeComponent, new_id


class Node(BaseModel):
    id: str = Field(default_factory=new_id)
    kind: str
    x: float = 0.0
    y: float = 0.0
    w: float | None = None
    h: float | None = None
    source_id: str | None = None
    movable: bool = True
    resizable: bool = True
    collapsed: bool = False
    path: str | None = None
    root: NodeComponent


class CanvasState(BaseModel):
    schema_version: int = 1
    nodes: list[Node] = Field(default_factory=list)
```

`packages/mekistudio/mekicanvas/__init__.py` : vide (ou docstring).

- [ ] **Step 4 : Lancer, vérifier le succès** — `python tests/smoke_mekicanvas.py` → `OK smoke_mekicanvas`

- [ ] **Step 5 : commit**

```bash
python -m py_compile packages/mekistudio/mekicanvas/model.py packages/mekistudio/mekicanvas/components/base.py
git add packages/mekistudio/mekicanvas/
git commit -m "feat(mekicanvas): ComponentBase + Node/CanvasState (pydantic, union discriminee)"
```

---

## Task 12 : Parenting (longest_prefix_id) + registry + reconcile

**Files:**
- Create: `packages/mekistudio/mekicanvas/parenting.py`, `registry.py`, `nodes/__init__.py`, `nodes/kernel.py`, `nodes/chat.py`, `nodes/queue.py`
- Test: `tests/smoke_mekicanvas.py` (étendre)

- [ ] **Step 1 : Étendre le test**

```python
def test_default_canvas_parenting():
    from mekicanvas.registry import default_canvas, reconcile_source_links
    st = reconcile_source_links(default_canvas())
    by_kind = {n.kind: n for n in st.nodes}
    assert by_kind["kernel"].source_id is None
    assert by_kind["chat"].source_id == by_kind["kernel"].id
    assert by_kind["queue"].source_id == by_kind["chat"].id


def test_longest_prefix():
    from mekicanvas.parenting import longest_prefix_id
    cands = [("docs", "id1"), ("", "id2"), ("docs/super", "id3")]
    assert longest_prefix_id("docs/super/x.md", cands, strict=False) == "id3"
```

Ajouter au `main()`.

- [ ] **Step 2 : Lancer, vérifier l'échec** — `ModuleNotFoundError: mekicanvas.registry`

- [ ] **Step 3 : Implémenter parenting.py** (porté de mekistudio, pur)

```python
from __future__ import annotations


def _segments(path: str) -> list[str]:
    return [s for s in (path or "").replace("\\", "/").split("/") if s]


def is_prefix(prefix: str, target: str) -> bool:
    ps, ts = _segments(prefix), _segments(target)
    return ps == ts[: len(ps)]


def longest_prefix_id(target_path, candidates, *, strict: bool):
    target_segs = _segments(target_path)
    best_id, best_len = None, -1
    for path, cid in candidates:
        segs = _segments(path)
        if strict and segs == target_segs:
            continue
        if not is_prefix(path, target_path):
            continue
        n = len(segs)
        if n > best_len or (n == best_len and best_id is not None and cid < best_id):
            best_id, best_len = cid, n
    return best_id
```

- [ ] **Step 4 : Implémenter les builders nodes**

`nodes/kernel.py` :
```python
from ..components.base import HeaderComponent, LayoutComponent, NodeComponent
from ..model import Node

KIND = "kernel"


def build_kernel_node(x: float = 0.0, y: float = 0.0) -> Node:
    return Node(kind=KIND, x=x, y=y, movable=False, resizable=False,
                root=NodeComponent(children=[LayoutComponent(
                    children=[HeaderComponent(level=1, text="Kernel")])]))
```

`nodes/chat.py` :
```python
from ..components.base import ChatComponentSpec, LayoutComponent, NodeComponent
from ..model import Node

KIND = "chat"


def build_chat_node(x: float = 0.0, y: float = 200.0) -> Node:
    return Node(kind=KIND, x=x, y=y, w=400.0, h=520.0,
                root=NodeComponent(children=[LayoutComponent(children=[ChatComponentSpec()])]))
```

`nodes/queue.py` :
```python
from ..components.base import LayoutComponent, NodeComponent, QueueComponentSpec
from ..model import Node

KIND = "queue"


def build_queue_node(x: float = 0.0, y: float = 760.0) -> Node:
    return Node(kind=KIND, x=x, y=y, w=400.0, h=220.0, resizable=False,
                root=NodeComponent(children=[LayoutComponent(children=[QueueComponentSpec()])]))
```

`nodes/__init__.py` : vide.

- [ ] **Step 5 : Implémenter registry.py**

```python
from __future__ import annotations

from .model import CanvasState, Node
from .nodes import chat, kernel, queue

NODE_BUILDERS = {
    kernel.KIND: kernel.build_kernel_node,
    chat.KIND: chat.build_chat_node,
    queue.KIND: queue.build_queue_node,
}

CANONICAL_PARENT_KIND = {
    chat.KIND: kernel.KIND,
    queue.KIND: chat.KIND,
}


def _canonical_parent_id(state: CanvasState, kind: str) -> str | None:
    pk = CANONICAL_PARENT_KIND.get(kind)
    if pk is None:
        return None
    for n in state.nodes:
        if n.kind == pk:
            return n.id
    return None


def reconcile_source_links(state: CanvasState) -> CanvasState:
    by_id = {n.id: n for n in state.nodes}
    for node in state.nodes:
        if node.kind == kernel.KIND:
            node.source_id = None
            continue
        expected = CANONICAL_PARENT_KIND.get(node.kind)
        cur = by_id.get(node.source_id) if node.source_id else None
        dangling = node.source_id is None or node.source_id not in by_id
        wrong = cur is not None and expected is not None and cur.kind != expected
        if dangling or wrong:
            node.source_id = _canonical_parent_id(state, node.kind)
    return state


def default_canvas() -> CanvasState:
    k = kernel.build_kernel_node()
    c = chat.build_chat_node()
    q = queue.build_queue_node()
    return reconcile_source_links(CanvasState(nodes=[k, c, q]))
```

- [ ] **Step 6 : Lancer, vérifier le succès** — `python tests/smoke_mekicanvas.py` → `OK smoke_mekicanvas`

- [ ] **Step 7 : commit**

```bash
python -m py_compile packages/mekistudio/mekicanvas/registry.py packages/mekistudio/mekicanvas/parenting.py packages/mekistudio/mekicanvas/nodes/*.py
git add packages/mekistudio/mekicanvas/
git commit -m "feat(mekicanvas): registry + parenting + builders Kernel/Chat/Queue + default_canvas"
```

---

## Task 13 : `impulse_for` (porté en Python, pur)

**Files:**
- Create: `packages/mekistudio/mekicanvas/impulses.py`
- Test: `tests/smoke_mekicanvas.py` (étendre)

> Adapté à NOS outils minuscules : `READ_TOOLS = {"read", "grep", "glob"}` (pas de Write/Edit/Bash → null). L'enrichissement `file_path` se fait à partir des arguments de l'outil (clé `path`).

- [ ] **Step 1 : Étendre le test**

```python
def test_impulse_read_with_path():
    from mekicanvas.impulses import impulse_for
    it = impulse_for({"type": "tool_result", "name": "read", "file_path": "a/b.py"})
    assert it["kind"] == "comet" and it["target"] == {"by": "file", "value": "a/b.py"}
    assert it["level"] == "strong" and "fallback" in it


def test_impulse_non_read_is_none():
    from mekicanvas.impulses import impulse_for
    assert impulse_for({"type": "tool_result", "name": "write", "file_path": "a"}) is None


def test_impulse_turn_end_and_error():
    from mekicanvas.impulses import impulse_for
    assert impulse_for({"type": "turn_end"})["dismissable"] is True
    assert impulse_for({"type": "tool_result", "is_error": True})["level"] == "error"
```

Ajouter au `main()`.

- [ ] **Step 2 : Lancer, vérifier l'échec** — `ModuleNotFoundError: mekicanvas.impulses`

- [ ] **Step 3 : Implémenter impulses.py**

```python
"""impulses.py — mappe un event d'outil mekihub -> intent d'impulsion canvas.

Porté de chat-impulses.js (impulseFor). Pur. Seuls les outils de LECTURE déclenchent
une comète ; les écritures / bash ne produisent rien (UX silencieuse, comme l'amont).
"""
from __future__ import annotations

READ_TOOLS = {"read", "grep", "glob"}


def normalize_path(p: str) -> str:
    if not p:
        return ""
    p = p.replace("\\", "/")
    while "//" in p:
        p = p.replace("//", "/")
    return p.lstrip("./").rstrip("/")


def impulse_for(event: dict) -> dict | None:
    if not event:
        return None
    t = event.get("type")
    if t == "tool_result":
        if event.get("is_error"):
            return {"kind": "glow", "target": {"by": "kind", "value": "chat"}, "level": "error"}
        name = (event.get("name") or "").lower()
        if name not in READ_TOOLS:
            return None
        fp = event.get("file_path")
        if fp:
            return {"kind": "comet", "target": {"by": "file", "value": fp}, "level": "strong",
                    "fallback": {"kind": "comet", "target": {"by": "kind", "value": "fileexplorer"},
                                 "level": "strong"}}
        return {"kind": "comet", "target": {"by": "kind", "value": "fileexplorer"}, "level": "soft"}
    if t == "turn_end":
        return {"kind": "glow", "target": {"by": "kind", "value": "chat"}, "level": "strong",
                "dismissable": True}
    return None


def impulse_from_hub_event(event) -> dict | None:
    """Adapte un event mekihub (ToolFinished/RunError/RunFinished) -> impulse_for()."""
    name = type(event).__name__
    if name == "ToolFinished":
        args = getattr(event, "args", None) or {}
        is_error = str(getattr(event, "output", "")).startswith("Error") or "Denied" in str(getattr(event, "output", ""))
        return impulse_for({"type": "tool_result", "name": getattr(event, "name", ""),
                            "file_path": normalize_path(args.get("path", "")) or None,
                            "is_error": is_error})
    if name == "RunError":
        return impulse_for({"type": "tool_result", "is_error": True})
    if name in ("RunFinished", "Idle"):
        return impulse_for({"type": "turn_end"})
    return None
```

> Note : `ToolFinished` ne porte pas `args` aujourd'hui (events.py). Soit on enrichit l'event (ajouter `args` à `ToolStarted`/`ToolFinished` côté mekihub `_translate`), soit le canvas garde une table `id->args` depuis `ToolStarted`. Décision Sprint 1 : conserver `id->args` côté `canvas_page` (cf. Task 16). `impulse_from_hub_event` accepte donc un event déjà enrichi `{name, args}`.

- [ ] **Step 4 : Lancer, vérifier le succès** — `python tests/smoke_mekicanvas.py` → `OK smoke_mekicanvas`

- [ ] **Step 5 : commit**

```bash
python -m py_compile packages/mekistudio/mekicanvas/impulses.py
git add packages/mekistudio/mekicanvas/impulses.py tests/smoke_mekicanvas.py
git commit -m "feat(mekicanvas): impulse_for porte en Python (READ_TOOLS minuscules)"
```

---

## Task 14 : Vendorer la géométrie JS + tests `node --test`

**Files:**
- Create (copie verbatim): `packages/mekistudio/mekicanvas/static/js/cables.js`, `collision.js`, `cables.test.js`, `collision.test.js`
- Create: `tests/js/run_js_tests.ps1`

- [ ] **Step 1 : Copier les 4 fichiers verbatim**

```bash
mkdir -p packages/mekistudio/mekicanvas/static/js
cp C:/mekistudio/mekistudio/frontend/static/js/cables.js       packages/mekistudio/mekicanvas/static/js/
cp C:/mekistudio/mekistudio/frontend/static/js/collision.js    packages/mekistudio/mekicanvas/static/js/
cp C:/mekistudio/mekistudio/frontend/static/js/cables.test.js  packages/mekistudio/mekicanvas/static/js/
cp C:/mekistudio/mekistudio/frontend/static/js/collision.test.js packages/mekistudio/mekicanvas/static/js/
```

Ajouter en tête de `cables.js` et `collision.js` un commentaire de provenance :
```js
/* Vendoré de mekistudio (MIT/ISC) — géométrie pure, ne pas diverger sans raison. */
```

- [ ] **Step 2 : Créer le lanceur de tests JS**

`tests/js/run_js_tests.ps1` :
```powershell
$ErrorActionPreference = "Stop"
$js = Join-Path $PSScriptRoot "..\..\packages\mekistudio\mekicanvas\static\js"
node --test (Join-Path $js "cables.test.js") (Join-Path $js "collision.test.js")
```

- [ ] **Step 3 : Lancer les tests JS, vérifier le succès**

Run: `node --test packages/mekistudio/mekicanvas/static/js/cables.test.js packages/mekistudio/mekicanvas/static/js/collision.test.js`
Expected: `# pass 32` (25 + 7) — `# fail 0`

- [ ] **Step 4 : commit**

```bash
git add packages/mekistudio/mekicanvas/static/js/ tests/js/run_js_tests.ps1
git commit -m "vendor(mekicanvas): geometrie cables.js/collision.js + tests node --test"
```

---

# PHASE 6 — mekicanvas : page NiceGUI + pont JS + comètes

## Task 15 : Pont canvas JS (pan/zoom + câbles + comètes)

**Files:**
- Create: `packages/mekistudio/mekicanvas/static/js/canvas.js`
- Create: `packages/mekistudio/mekicanvas/static/css/canvas.css`

> Pilote la géométrie vendorée depuis le DOM des nodes NiceGUI. API exposée à NiceGUI : `window.MekiCanvas.redraw()`, `window.MekiCanvas.impulse(intent)`, init pan/zoom. Les nodes sont des `.node-wrap` positionnées en absolu (left/top en coords monde) dans `.mc-world`.

- [ ] **Step 1 : Écrire `canvas.js`**

Implémenter (≈150-250 lignes), en réutilisant `window.MekiCables`/`window.MekiCollision` :
- `initWorld()` : récupère `.mc-canvas` + `.mc-world`, pose `view={x,y,zoom}`, handlers `mousedown`(pan)/`wheel`(zoom ancré curseur) ⇒ `applyTransform()`.
- `readNodeBoxes()` : `Map<id,{box:{x,y,w,h},kind,source}>` depuis `.node-wrap[data-id|data-kind|data-source]` (x,y = `style.left/top` parsés ; w,h = `offsetWidth/Height`).
- `ensureCablesLayer()` : `<svg class="cables">` premier enfant de `.mc-world`.
- `redraw()` : porte les 6 phases de `drawCablesFrom` (Task report 3) — détecte câbles via `data-source`, `adaptiveSide`, `assignLanes`, `routeAround`, escape `routeAvoiding`, anti-ruban, trace `pointsToPath` dans `<g data-edge>`.
- `impulse(intent)` : porte `applyIntent` minimal Sprint 1 — `comet` ⇒ `pulseTo(chatId, targetId)` le long du chemin (`MekiCables.pathBetween`), `glow` ⇒ ajoute/retire classe `glow-<level>` sur la node cible ; `target.by==='kind'` ⇒ `kindId(value)` cherche `.node-wrap[data-kind=value]` ; `by==='file'` ⇒ pas de cible Sprint 1 ⇒ applique `fallback` ou ignore.
- `pulseTo(fromId,toId,level)` + `animateComet(seg)` : portés de canvas.js (SVG circle animé le long du segment).

Exposer : `window.MekiCanvas = { initWorld, redraw, impulse, view };`

- [ ] **Step 2 : Écrire `canvas.css`** (thème Phosphore : `.mc-canvas` grille, `.node-wrap`, `svg.cables .cable-core/.cable-halo`, `.glow-strong/.glow-soft/.glow-error`, keyframes comète).

- [ ] **Step 3 : Vérifier la syntaxe JS**

Run: `node --check packages/mekistudio/mekicanvas/static/js/canvas.js`
Expected: (aucune sortie = OK)

- [ ] **Step 4 : commit**

```bash
git add packages/mekistudio/mekicanvas/static/js/canvas.js packages/mekistudio/mekicanvas/static/css/canvas.css
git commit -m "feat(mekicanvas): pont canvas.js (pan/zoom + cables + cometes) + canvas.css"
```

---

## Task 16 : Page canvas NiceGUI (nodes + abonnement hub → comètes)

**Files:**
- Create: `packages/mekistudio/mekicanvas/canvas_page.py`

> Rend `default_canvas()` (Kernel/Chat/Queue) en `.node-wrap` NiceGUI dans `.mc-world`, charge cables.js/collision.js/canvas.js + canvas.css, appelle `MekiCanvas.initWorld()` puis `redraw()`. S'abonne au hub pour la session courante et, par event, calcule l'intent (`impulse_from_hub_event`) et déclenche `ui.run_javascript("window.MekiCanvas.impulse(<intent>)")`. La ChatNode embarque un `ChatComponent` ; la QueueNode embarque un `QueueComponent`.

- [ ] **Step 1 : Implémenter `canvas_page.py`**

```python
"""canvas_page.py — rend le canvas (Kernel/Chat/Queue) en NiceGUI + comètes serveur."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from nicegui import ui

from mekicanvas.registry import default_canvas
from mekicanvas.impulses import impulse_from_hub_event
from component import ChatComponent  # mekichat (même sys.path)

_JS = Path(__file__).resolve().parent / "static" / "js"
_CSS = Path(__file__).resolve().parent / "static" / "css" / "canvas.css"


def _load_assets() -> None:
    for f in ("cables.js", "collision.js", "canvas.js"):
        ui.add_body_html(f"<script>{(_JS / f).read_text(encoding='utf-8')}</script>")
    ui.add_css(_CSS.read_text(encoding="utf-8"))


def render_canvas(container, hub, session_id, author) -> None:
    _load_assets()
    state = default_canvas()
    by_kind = {n.kind: n for n in state.nodes}
    with container:
        world = ui.element("div").classes("mc-canvas")
        with world:
            inner = ui.element("div").classes("mc-world")
            with inner:
                for n in state.nodes:
                    wrap = ui.element("div").classes("node-wrap")
                    wrap.style(f"position:absolute;left:{n.x}px;top:{n.y}px;"
                               + (f"width:{n.w}px;" if n.w else "") + (f"height:{n.h}px;" if n.h else ""))
                    wrap.props(f'data-id="{n.id}" data-kind="{n.kind}" '
                               f'data-source="{n.source_id or ""}"')
                    with wrap:
                        if n.kind == "chat":
                            ChatComponent(container=wrap, hub=hub, session_id=session_id, author=author)
                        elif n.kind == "queue":
                            ui.label("file d'attente").classes("node-title")
                        else:
                            ui.label("Kernel").classes("node-title")
    ui.timer(0.2, lambda: ui.run_javascript("window.MekiCanvas.initWorld(); window.MekiCanvas.redraw();"), once=True)
    # abonnement comètes (enrichit id->args depuis ToolStarted)
    args_by_id: dict = {}

    async def _impulses() -> None:
        async for ev in hub.subscribe(session_id):
            name = type(ev).__name__
            if name == "ToolStarted":
                args_by_id[ev.id] = ev.args
            if name == "ToolFinished":
                setattr(ev, "args", args_by_id.get(ev.id, {}))
            intent = impulse_from_hub_event(ev)
            if intent:
                ui.run_javascript(f"window.MekiCanvas.impulse({json.dumps(intent)})")
    ui.timer(0.1, _impulses, once=True)
```

- [ ] **Step 2 : Vérifier l'import** — `python -c "import sys; [sys.path.insert(0,p) for p in ('packages','packages/mekistudio','packages/mekistudio/mekichat','packages/mekicore')]; import mekicanvas.canvas_page; print('OK')"`
Expected: `OK`

- [ ] **Step 3 : commit**

```bash
python -m py_compile packages/mekistudio/mekicanvas/canvas_page.py
git add packages/mekistudio/mekicanvas/canvas_page.py
git commit -m "feat(mekicanvas): page canvas NiceGUI (nodes + abonnement hub -> cometes)"
```

---

# PHASE 7 — Coquille 3 modes + intégration finale

## Task 17 : Shell 3 modes + entrée studio

**Files:**
- Create: `packages/mekistudio/shell.py`, `packages/mekistudio/app.py`, `start-studio.ps1`

- [ ] **Step 1 : Implémenter `app.py` (entrée + page + sys.path)**

`packages/mekistudio/app.py` :
```python
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent            # packages/mekistudio/
PACKAGES = HERE.parent                            # packages/
sys.path.insert(0, str(HERE))                     # shell, mekicanvas
sys.path.insert(0, str(HERE / "mekichat"))        # component, views, sessions, realtime
sys.path.insert(0, str(PACKAGES))                 # mekillm, mekihub
sys.path.insert(0, str(PACKAGES / "mekicore"))    # base, tools, events

from nicegui import ui  # noqa: E402

from shell import build_shell  # noqa: E402


@ui.page("/")
def index() -> None:
    build_shell()


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="mekistudio", port=8080, dark=True, reload=False, show=True,
           storage_secret="mekistudio-dev")
```

- [ ] **Step 2 : Implémenter `shell.py` (3 modes + focus)**

```python
"""shell.py — coquille studio : sélecteur Chat / Canvas / Mix + focus session."""
from __future__ import annotations

from nicegui import app, ui

import realtime
import sessions as sessions_mod
from component import ChatComponent
from mekicanvas.canvas_page import render_canvas


def _hub():
    import app as studio_app  # réutilise les singletons de l'app chat existante si présents
    return studio_app._get_hub() if hasattr(studio_app, "_get_hub") else _fallback_hub()


def build_shell() -> None:
    author = realtime.author_for_client()
    store = sessions_mod.SessionStore()
    current = (store.list() or [store.create()])[0]
    state = {"mode": app.storage.user.get("mode", "mix"), "focus": current.id}

    body = ui.element("div").classes("studio-body")

    def render() -> None:
        body.clear()
        hub = _hub()
        with body:
            with ui.element("div").classes("studio-modes"):
                for m in ("chat", "canvas", "mix"):
                    b = ui.button(m.capitalize(), on_click=lambda _=None, mm=m: _set_mode(mm))
                    b.classes("mode-btn" + (" on" if state["mode"] == m else ""))
            with ui.element("div").classes(f"studio-stage mode-{state['mode']}"):
                if state["mode"] in ("chat", "mix"):
                    with ui.element("div").classes("stage-chat") as c:
                        ChatComponent(container=c, hub=hub, session_id=state["focus"], author=author)
                if state["mode"] in ("canvas", "mix"):
                    with ui.element("div").classes("stage-canvas") as cv:
                        render_canvas(cv, hub, state["focus"], author)

    def _set_mode(m: str) -> None:
        state["mode"] = m
        app.storage.user["mode"] = m
        render()

    render()
```

> `set_focus` (clic ChatNode → chat de gauche) : la `ChatNode` du canvas appelle, via un handler NiceGUI sur son en-tête, `shell.set_focus(session_id)` qui met `state["focus"]` et `render()`. Pour Sprint 1 (une seule session affichée), exposer `set_focus` comme closure attachée à `app.storage` ou au module ; câblage complet du multi-ChatNode = Sprint 3. Implémenter `set_focus` a minima (change la session et re-render).

- [ ] **Step 3 : `start-studio.ps1`**
```powershell
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
python packages/mekistudio/app.py
```

- [ ] **Step 4 : Lancer, vérifier le démarrage** — `python packages/mekistudio/app.py` (Ctrl+C après ~5 s : aucune exception d'import/montage).

- [ ] **Step 5 : commit**

```bash
python -m py_compile packages/mekistudio/app.py packages/mekistudio/shell.py
git add packages/mekistudio/app.py packages/mekistudio/shell.py start-studio.ps1
git commit -m "feat(mekistudio): coquille 3 modes (Chat/Canvas/Mix) + entree studio"
```

---

## Task 18 : Vérification visuelle (Playwright) — réseau-free

**Files:**
- Create: `tests/visual_mekistudio.py` (script Playwright + FakeLLM)

> Conformément à la préférence « vérifier un front visuellement avant de rapporter » : lancer le studio avec un `FakeLLM` (de `tests/fakes.py`) qui répond avec un appel d'outil `read`, capturer chaque mode, et vérifier visuellement la node Chat, la QueueNode, un câble 45°, une comète, et la carte de permission (déclenchée par un `bash "rm x"`).

- [ ] **Step 1 : Écrire le script de capture** (lance le studio sur un port de test avec `MEKILLM` mocké, ouvre `/`, bascule les 3 modes, screenshot chaque, déclenche un run outil read et un run `rm` pour la carte de permission).

- [ ] **Step 2 : Lancer + analyser les captures** (vérifier : 3 modes OK, ChatNode rend le chat, QueueNode sous le chat, câble néon 45° sans overlap, comète visible sur lecture, carte de permission 5 boutons). Itérer le CSS/JS jusqu'à conformité.

- [ ] **Step 3 : commit**

```bash
git add tests/visual_mekistudio.py
git commit -m "test(mekistudio): verification visuelle Playwright (3 modes + cometes + carte permission)"
```

---

## Task 19 : Smoke global + docs

**Files:**
- Modify: `ROADMAP.md`, `CLAUDE.md` (entrées + structure), `docs/wiki-packages/` (manuel)

- [ ] **Step 1 : Lancer toute la non-régression**

```bash
python tests/smoke_packages.py
python tests/smoke_mekichat.py
python tests/smoke_mekihub.py
python tests/smoke_mekicore_hooks.py
python tests/smoke_permissions.py
python tests/smoke_mekicanvas.py
node --test packages/mekistudio/mekicanvas/static/js/cables.test.js packages/mekistudio/mekicanvas/static/js/collision.test.js
```
Expected: tous `OK` / `# fail 0`.

- [ ] **Step 2 : Mettre à jour la doc** — `CLAUDE.md` (structure `packages/`, nouvelle entrée `python packages/mekistudio/app.py`, `start-studio.ps1`), `ROADMAP.md` (Sprint 1 livré), `docs/wiki-packages/` (mekistudio/mekicanvas, manuel).

- [ ] **Step 3 : commit final**

```bash
git add -A
git commit -m "docs: Sprint 1 mekistudio canvas livre (structure, entrees, roadmap, wiki-packages)"
```

---

## Auto-revue (couverture spec)

| Exigence spec | Tâche(s) |
|---|---|
| Coquille 3 modes (Chat/Canvas/Mix) + focus | Task 17 |
| ChatComponent unique partagé | Task 9, 16, 17 |
| HookBus (pre_tool veto / post_tool) | Task 1, 4 |
| s15 Permissions 3 tiers | Task 2, 3 |
| Permissions en couches (session/projet/global) | Task 3, 7, 8 |
| Tier ask async + carte façon Claude Code + auteur/admin + timeout deny | Task 8, 10 |
| Canvas NiceGUI (pan/zoom + câbles 45° + comètes) | Task 15, 16 |
| Géométrie pure vendorée + node --test | Task 14 |
| impulse_for porté (nos hooks) | Task 13, 16 |
| BaseNode/BaseComponent + registry + parenting | Task 11, 12 |
| Nodes Kernel/Chat + QueueNode sous le chat | Task 12, 16 |
| Multi-user/queue réutilise mekihub | Task 9, 16 (QueueComponent rendu) |
| Package front `mekistudio/` ; back en frères | Task 5 |
| Tests réseau-free + vérif visuelle | Task 1-14, 18, 19 |

**Points laissés explicitement minimaux en Sprint 1 (cf. spec §14) :** QueueComponent dans la QueueNode = rendu basique (la file riche multi-auteurs temps réel sur le canvas est affinée au Sprint 3) ; `set_focus` multi-ChatNode a minima ; pas de drag/relayout organique ; pas d'éditeur/preview.
