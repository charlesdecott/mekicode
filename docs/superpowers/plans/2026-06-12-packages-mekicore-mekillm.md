# packages/ mekicore + mekillm — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Créer `packages/mekillm` (provider LLM généraliste OpenRouter via SDK `openai`, avec observabilité) et `packages/mekicore` (le s01 de claude-code-from-scratch adapté, branché sur mekillm).

**Architecture :** Deux paquets sœurs sous `packages/`, import par chemin (pas de pyproject). mekillm enveloppe le SDK `openai` (base_url OpenRouter), normalise la réponse au format OpenAI et émet un `CallRecord` par appel vers 3 canaux (logging / JSONL / hook). mekicore est une boucle perception-action minimale qui travaille directement en format OpenAI (`tool_calls`, messages `role:"tool"`) et appelle mekillm.

**Tech Stack :** Python 3.x, SDK `openai>=1.0`, `python-dotenv`. Non-régression : `python -m py_compile` par fichier + un script smoke réseau-free (`packages/_smoke.py`), conformément à la convention du repo (pas de pytest).

**Conventions du repo à respecter (CLAUDE.md) :**
- Commits **sans** mention de Claude (`Co-Authored-By`, « Generated with… ») — exigence explicite.
- `python -m py_compile` sur chaque `.py` modifié avant de conclure (règle 4).
- La règle wiki-update (règle 1) cible `src/` et `src_scratch/` uniquement → **aucune** régénération de wiki pour `packages/`.
- Tout le contenu (docstrings, commentaires) en **français**.

Spec de référence : `docs/superpowers/specs/2026-06-12-packages-mekicore-mekillm-design.md`.

**⚠️ Isolation des commits (working tree sale — règle globale) :** le repo contient du travail en
cours de l'utilisateur (réorg wiki **déjà staged**, `.gitignore` racine modifié, `.env.example`
racine supprimé) qu'il ne faut **jamais** embarquer. Donc, pour CHAQUE étape « Commit » du plan,
ignorer la commande `git add`+`git commit` nue affichée et exécuter à la place, avec exactement le
message indiqué :

```bash
git add <les fichiers de la tâche>
git commit --only <les fichiers de la tâche> -m "<message du plan>"
```

`git commit --only <chemins>` ne commite que ces chemins et **ignore** le reste de l'index (le WIP
wiki staged reste intact). Ne jamais lancer un `git commit` sans `--only`. Travailler sur `main`
(accord explicite de l'utilisateur).

---

### Task 1 : mekillm/observability.py — CallRecord + 3 canaux

**Files:**
- Create: `packages/mekillm/observability.py`

- [ ] **Step 1 : Créer le fichier d'observabilité**

```python
"""observability.py — monitor / profile / log de chaque appel LLM.

Trois canaux indépendants : logging standard (logger « mekillm »), JSONL
append-only, et hooks. Aucun basicConfig imposé : c'est au consommateur de
configurer le handler de logging.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("mekillm")

_DEFAULT_LOG = Path(__file__).parent / ".logs" / "calls.jsonl"
_HOOKS: list = []


@dataclass
class CallRecord:
    """Trace structurée d'un appel LLM (un par complete())."""

    ts: str
    provider: str
    model: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str
    status: str                 # "ok" | "error"
    error: str | None = None
    n_messages: int = 0
    n_tools: int = 0
    cost_usd: float | None = None


def now_iso() -> str:
    """Horodatage ISO 8601 en UTC."""
    return datetime.now(timezone.utc).isoformat()


def add_hook(fn) -> None:
    """Enregistre fn(record: CallRecord), appelé après chaque appel LLM."""
    _HOOKS.append(fn)


def _log_file() -> Path | None:
    """Chemin du JSONL : MEKILLM_LOG_FILE, défaut .logs/calls.jsonl, vide = désactivé."""
    raw = os.environ.get("MEKILLM_LOG_FILE", str(_DEFAULT_LOG))
    return Path(raw) if raw else None


def _append_jsonl(record: CallRecord) -> None:
    """Ajoute une ligne JSON au fichier de log (créé à la volée)."""
    path = _log_file()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")


def emit(record: CallRecord) -> None:
    """Diffuse `record` vers les trois canaux : logging, JSONL, hooks."""
    log.info(
        "%s · %dms · %d→%d tok · %s",
        record.model, record.latency_ms,
        record.prompt_tokens, record.completion_tokens, record.finish_reason,
    )
    _append_jsonl(record)
    for fn in _HOOKS:
        try:
            fn(record)
        except Exception as e:  # un hook fautif ne casse pas le flux
            log.warning("hook d'observabilité en erreur : %s", e)
```

- [ ] **Step 2 : Vérifier la syntaxe**

Run: `python -m py_compile packages/mekillm/observability.py`
Expected: aucune sortie (succès).

- [ ] **Step 3 : Commit**

```bash
git add packages/mekillm/observability.py
git commit -m "mekillm: couche observabilite (CallRecord, logging, JSONL, hooks)"
```

---

### Task 2 : mekillm/config.py — résolution .env

**Files:**
- Create: `packages/mekillm/config.py`

- [ ] **Step 1 : Créer le module de config**

```python
"""config.py — résolution de la config mekillm : args explicites > .env > défauts."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv(override=True)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-4o-mini"


def resolve(api_key=None, base_url=None, model=None) -> dict:
    """Fusionne, par priorité décroissante : arguments explicites, env, défauts."""
    return {
        "api_key": api_key
        or os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("MEKILLM_API_KEY"),
        "base_url": base_url or os.environ.get("MEKILLM_BASE_URL") or DEFAULT_BASE_URL,
        "model": model or os.environ.get("MEKILLM_MODEL") or DEFAULT_MODEL,
    }
```

- [ ] **Step 2 : Vérifier la syntaxe**

Run: `python -m py_compile packages/mekillm/config.py`
Expected: aucune sortie (succès).

- [ ] **Step 3 : Commit**

```bash
git add packages/mekillm/config.py
git commit -m "mekillm: resolution de config depuis .env (cle/base_url/modele)"
```

---

### Task 3 : mekillm/client.py + __init__.py — provider + normalisation

**Files:**
- Create: `packages/mekillm/client.py`
- Create: `packages/mekillm/__init__.py`

- [ ] **Step 1 : Créer le client**

> `Usage` est défini **dans ce fichier** (pas dans observability). N'importe d'observability que `CallRecord, emit, log, now_iso`.

```python
"""client.py — provider LLM généraliste : wrapper du SDK openai + normalisation.

Backend par défaut OpenRouter ; compatible ollama / litellm-proxy (tous parlent
l'API OpenAI). complete() renvoie un LLMResponse normalisé et émet un CallRecord.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from . import config
from .observability import CallRecord, emit, log, now_iso


@dataclass
class ToolCall:
    """Appel d'outil normalisé : arguments déjà parsés en dict."""

    id: str
    name: str
    arguments: dict


@dataclass
class Usage:
    """Comptage de tokens (0 si le backend ne le renvoie pas)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """Réponse normalisée, agnostique du provider."""

    text: str
    tool_calls: list            # list[ToolCall]
    finish_reason: str
    usage: Usage
    message: dict               # message assistant prêt à append à l'historique
    raw: Any = None


def _message_dict(msg) -> dict:
    """Convertit le message assistant du SDK en dict simple (sérialisable)."""
    d = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
    return d


def _normalize(resp) -> LLMResponse:
    """Transforme une réponse SDK openai en LLMResponse normalisé."""
    choice = resp.choices[0]
    msg = choice.message
    tool_calls = []
    for tc in (msg.tool_calls or []):
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            log.warning("arguments JSON invalides pour l'outil %s", tc.function.name)
            args = {}
        tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
    u = resp.usage
    usage = (
        Usage(
            prompt_tokens=getattr(u, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(u, "completion_tokens", 0) or 0,
            total_tokens=getattr(u, "total_tokens", 0) or 0,
        )
        if u
        else Usage()
    )
    return LLMResponse(
        text=msg.content or "",
        tool_calls=tool_calls,
        finish_reason=choice.finish_reason or "",
        usage=usage,
        message=_message_dict(msg),
        raw=resp,
    )


class LLM:
    """Provider LLM réutilisable. Lit la config depuis .env, surchargeable par args."""

    def __init__(self, model=None, api_key=None, base_url=None):
        cfg = config.resolve(api_key, base_url, model)
        self.model = cfg["model"]
        self.base_url = cfg["base_url"]
        self._client = OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])

    def complete(self, messages, tools=None, system=None, max_tokens=8000, **kwargs) -> LLMResponse:
        """Un tour de complétion. Émet un CallRecord (succès comme erreur)."""
        sent = list(messages)
        if system:
            sent = [{"role": "system", "content": system}] + sent
        params = dict(model=self.model, messages=sent, max_tokens=max_tokens, **kwargs)
        if tools:
            params["tools"] = tools

        start = time.perf_counter()
        rec = {"status": "ok", "error": None, "finish_reason": "", "usage": Usage()}
        try:
            resp = self._client.chat.completions.create(**params)
            out = _normalize(resp)
            rec["finish_reason"], rec["usage"] = out.finish_reason, out.usage
            return out
        except Exception as e:
            rec["status"], rec["error"] = "error", str(e)
            raise
        finally:
            emit(
                CallRecord(
                    ts=now_iso(),
                    provider="openai",
                    model=self.model,
                    latency_ms=int((time.perf_counter() - start) * 1000),
                    prompt_tokens=rec["usage"].prompt_tokens,
                    completion_tokens=rec["usage"].completion_tokens,
                    total_tokens=rec["usage"].total_tokens,
                    finish_reason=rec["finish_reason"],
                    status=rec["status"],
                    error=rec["error"],
                    n_messages=len(sent),
                    n_tools=len(tools or []),
                )
            )
```

- [ ] **Step 2 : Créer l'API publique du paquet**

```python
"""mekillm — provider LLM généraliste, importable n'importe où.

Backend par défaut : OpenRouter via le SDK openai (compatible ollama / litellm).
Observabilité intégrée : logging + JSONL + hooks (cf. mekillm.observe).
"""
from . import observability as observe
from .client import LLM, LLMResponse, ToolCall, Usage

__all__ = ["LLM", "LLMResponse", "ToolCall", "Usage", "observe", "complete"]

_default = None


def complete(messages, **kwargs):
    """Raccourci : appel via un singleton LLM paresseux (config .env)."""
    global _default
    if _default is None:
        _default = LLM()
    return _default.complete(messages, **kwargs)
```

- [ ] **Step 3 : Vérifier la syntaxe des deux fichiers**

Run: `python -m py_compile packages/mekillm/client.py packages/mekillm/__init__.py`
Expected: aucune sortie (succès).

- [ ] **Step 4 : Commit**

```bash
git add packages/mekillm/client.py packages/mekillm/__init__.py
git commit -m "mekillm: provider LLM (wrapper openai) + normalisation + API publique"
```

---

### Task 4 : mekicore/tools.py — outil bash (format OpenAI)

**Files:**
- Create: `packages/mekicore/tools.py`

- [ ] **Step 1 : Créer les outils**

```python
"""tools.py — outils de mekicore (s01 adapté), au format function-calling OpenAI."""
from __future__ import annotations

import os
import subprocess

# Fragments de commande toujours bloqués (sécurité, repris de s01).
_ALWAYS_BLOCK = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/", ":(){ :|:& };:"]


def run_bash(command: str) -> str:
    """Exécute une commande shell (timeout 120 s), sortie tronquée à 50k chars."""
    if any(b in command for b in _ALWAYS_BLOCK):
        return "Error: dangerous command blocked"
    try:
        r = subprocess.run(
            command, shell=True, cwd=os.getcwd(),
            capture_output=True, text=True, timeout=120,
        )
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: timeout (120s)"
    except Exception as e:
        return f"Error: {e}"


# Schéma au format function-calling OpenAI (lingua franca OpenRouter/ollama/litellm).
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run a shell command.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
]

# Table de routage nom d'outil → handler(args: dict) -> str.
DISPATCH = {"bash": lambda args: run_bash(args["command"])}
```

- [ ] **Step 2 : Vérifier la syntaxe**

Run: `python -m py_compile packages/mekicore/tools.py`
Expected: aucune sortie (succès).

- [ ] **Step 3 : Commit**

```bash
git add packages/mekicore/tools.py
git commit -m "mekicore: outil bash + schema OpenAI + table de dispatch"
```

---

### Task 5 : mekicore/base.py — boucle perception-action

**Files:**
- Create: `packages/mekicore/base.py`

- [ ] **Step 1 : Créer la boucle**

```python
"""base.py — boucle perception-action (s01 adapté), branchée sur mekillm.

Travaille directement en format OpenAI : tool_calls normalisés en entrée,
messages role:"tool" en sortie.
"""
from __future__ import annotations


def dispatch_tools(tool_calls, dispatch) -> list:
    """Exécute chaque ToolCall et renvoie les messages role:'tool' correspondants."""
    results = []
    for tc in tool_calls:
        handler = dispatch.get(tc.name)
        first = str(next(iter(tc.arguments.values()), ""))[:80] if tc.arguments else ""
        print(f"\033[33m[{tc.name}] {first}...\033[0m")
        if handler:
            try:
                output = handler(tc.arguments)
            except Exception as e:
                output = f"Error during tool execution: {e}"
        else:
            output = f"Error: Unknown tool '{tc.name}'"
        print(str(output)[:300])
        results.append({"role": "tool", "tool_call_id": tc.id, "content": str(output)})
    return results


def agent_loop(messages, llm, tools, dispatch) -> None:
    """Boucle « penser-agir » : complete → tools → complete … jusqu'à finish != tool_calls.

    Modifie `messages` en place.
    """
    while True:
        print("\n\033[36m> Thinking...\033[0m")
        resp = llm.complete(messages, tools=tools)
        messages.append(resp.message)
        if resp.text:
            print(resp.text)
        if resp.finish_reason != "tool_calls":
            return
        messages += dispatch_tools(resp.tool_calls, dispatch)
```

- [ ] **Step 2 : Vérifier la syntaxe**

Run: `python -m py_compile packages/mekicore/base.py`
Expected: aucune sortie (succès).

- [ ] **Step 3 : Commit**

```bash
git add packages/mekicore/base.py
git commit -m "mekicore: boucle perception-action (agent_loop + dispatch_tools)"
```

---

### Task 6 : mekicore/main.py — REPL + bootstrap

**Files:**
- Create: `packages/mekicore/main.py`

- [ ] **Step 1 : Créer le point d'entrée**

```python
#!/usr/bin/env python3
"""main.py — REPL de mekicore : le s01 de claude-code-from-scratch branché sur mekillm."""
from __future__ import annotations

import sys
from pathlib import Path

# Bootstrap : rend `import mekillm` résoluble en lancement direct (ajoute packages/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mekillm  # noqa: E402
from base import agent_loop  # noqa: E402
from tools import DISPATCH, TOOLS  # noqa: E402

SYSTEM = f"You are a coding agent at {Path.cwd()}. Use tools to solve tasks. Act, don't explain."


def main() -> None:
    """REPL : lit une requête, lance la boucle agent, recommence."""
    print("\033[90mmekicore: one loop + bash = an agent (LLM via mekillm)\033[0m\n")
    llm = mekillm.LLM()
    messages = [{"role": "system", "content": SYSTEM}]
    while True:
        try:
            query = input("\033[36mmekicore >> \033[0m").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting session.")
            return
        if not query or query.lower() in ("q", "exit", "quit"):
            print("Goodbye.")
            return
        messages.append({"role": "user", "content": query})
        agent_loop(messages, llm, TOOLS, DISPATCH)
        print()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2 : Vérifier la syntaxe**

Run: `python -m py_compile packages/mekicore/main.py`
Expected: aucune sortie (succès).

- [ ] **Step 3 : Commit**

```bash
git add packages/mekicore/main.py
git commit -m "mekicore: REPL + bootstrap sys.path vers mekillm"
```

---

### Task 7 : Config projet — requirements + fichiers autonomes packages/

> **Isolation git (working tree sale)** : le repo a des changements en cours de l'utilisateur
> (réorg wiki déjà *staged*, `.gitignore` racine modifié, `.env.example` racine supprimé). Pour
> ne JAMAIS happer ce WIP : (1) on ne touche pas au `.env.example`/`.gitignore` racine — on crée à
> la place des fichiers autonomes sous `packages/` ; (2) **tous** les commits du plan utilisent
> `git commit --only <chemins>` (jamais `git add` suivi d'un `git commit` nu, qui embarquerait
> l'index sale).

**Files:**
- Modify: `requirements.txt` (fichier propre, non modifié par l'utilisateur)
- Create: `packages/.env.example`
- Create: `packages/.gitignore`

- [ ] **Step 1 : Ajouter la dépendance openai**

Ajoute cette ligne à la fin de `requirements.txt` :

```
openai>=1.0                # SDK OpenAI — utilisé par packages/mekillm (backend OpenRouter)
```

- [ ] **Step 2 : Créer packages/.env.example (documentation des variables mekillm)**

```
# packages/mekillm — variables lues depuis le .env racine (load_dotenv remonte jusqu'à lui).
# Copier ces lignes dans le .env racine et remplir.
OPENROUTER_API_KEY=sk-or-...
MEKILLM_BASE_URL=https://openrouter.ai/api/v1
MEKILLM_MODEL=openai/gpt-4o-mini
# Optionnel : fichier de log JSONL des appels (vide = désactivé)
# MEKILLM_LOG_FILE=
```

- [ ] **Step 3 : Créer packages/.gitignore (ignore les logs JSONL)**

```
# Logs d'appels mekillm (générés à l'exécution)
mekillm/.logs/
```

- [ ] **Step 4 : Installer la dépendance (si environnement actif)**

Run: `pip install "openai>=1.0"`
Expected: openai installé (ou « already satisfied »).

- [ ] **Step 5 : Commit (isolé)**

```bash
git commit --only requirements.txt packages/.env.example packages/.gitignore -m "config: dependance openai + packages/.env.example + packages/.gitignore"
```

> `git commit --only` ajoute lui-même les chemins indiqués depuis le working tree et ignore le
> reste de l'index. Si git refuse un chemin non suivi avec `--only`, faire d'abord
> `git add packages/.env.example packages/.gitignore` puis
> `git commit --only requirements.txt packages/.env.example packages/.gitignore -m "..."`.

---

### Task 8 : packages/_smoke.py — non-régression réseau-free

**Files:**
- Create: `packages/_smoke.py`

- [ ] **Step 1 : Écrire le script smoke (tests d'abord)**

```python
"""_smoke.py — non-régression réseau-free de packages/ (mekillm + mekicore).

Aucune dépendance réseau ni clé API : on stubbe la réponse SDK et le provider.
Lancer : python packages/_smoke.py
"""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))                  # packages/         → import mekillm
sys.path.insert(0, str(ROOT / "mekicore"))     # packages/mekicore → import base, tools

import mekillm  # noqa: E402
from mekillm import Usage  # noqa: E402
from mekillm import observability as observe  # noqa: E402
from mekillm.client import LLMResponse, ToolCall, _normalize  # noqa: E402

import base  # noqa: E402
import tools  # noqa: E402


def test_normalize_text():
    resp = NS(
        choices=[NS(message=NS(content="hi", tool_calls=None), finish_reason="stop")],
        usage=NS(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    out = _normalize(resp)
    assert out.text == "hi"
    assert out.tool_calls == []
    assert out.finish_reason == "stop"
    assert out.usage.total_tokens == 15
    assert out.message == {"role": "assistant", "content": "hi"}


def test_normalize_tool_call():
    tc = NS(id="call_1", function=NS(name="bash", arguments='{"command": "ls"}'))
    resp = NS(
        choices=[NS(message=NS(content=None, tool_calls=[tc]), finish_reason="tool_calls")],
        usage=None,
    )
    out = _normalize(resp)
    assert out.tool_calls[0].name == "bash"
    assert out.tool_calls[0].arguments == {"command": "ls"}
    assert out.finish_reason == "tool_calls"
    assert out.usage.total_tokens == 0
    assert out.message["tool_calls"][0]["function"]["name"] == "bash"


def test_normalize_bad_json_args():
    tc = NS(id="c", function=NS(name="bash", arguments="{not json"))
    resp = NS(
        choices=[NS(message=NS(content=None, tool_calls=[tc]), finish_reason="tool_calls")],
        usage=None,
    )
    out = _normalize(resp)
    assert out.tool_calls[0].arguments == {}  # JSON invalide → dict vide, pas de crash


def test_observability_hook_and_jsonl(log_path):
    seen = []
    observe.add_hook(seen.append)
    rec = observe.CallRecord(
        ts="t", provider="p", model="m", latency_ms=1,
        prompt_tokens=1, completion_tokens=2, total_tokens=3,
        finish_reason="stop", status="ok",
    )
    observe.emit(rec)
    assert seen and seen[0].model == "m"
    assert log_path.exists()
    assert '"model": "m"' in log_path.read_text(encoding="utf-8")


def test_run_bash():
    assert "hello" in tools.run_bash("echo hello")
    assert tools.run_bash("sudo rm") == "Error: dangerous command blocked"


def test_dispatch_tools():
    tc = ToolCall(id="c1", name="bash", arguments={"command": "echo hi"})
    msgs = base.dispatch_tools([tc], tools.DISPATCH)
    assert msgs[0]["role"] == "tool"
    assert msgs[0]["tool_call_id"] == "c1"
    assert "hi" in msgs[0]["content"]


def test_dispatch_unknown_tool():
    tc = ToolCall(id="c2", name="nope", arguments={})
    msgs = base.dispatch_tools([tc], tools.DISPATCH)
    assert "Unknown tool" in msgs[0]["content"]


def test_agent_loop_with_stub():
    seq = [
        LLMResponse(
            text="", tool_calls=[ToolCall("c1", "bash", {"command": "echo hi"})],
            finish_reason="tool_calls", usage=Usage(),
            message={"role": "assistant", "content": ""},
        ),
        LLMResponse(
            text="done", tool_calls=[], finish_reason="stop", usage=Usage(),
            message={"role": "assistant", "content": "done"},
        ),
    ]

    class StubLLM:
        def __init__(self):
            self.i = 0

        def complete(self, messages, tools=None):
            r = seq[self.i]
            self.i += 1
            return r

    messages = [{"role": "user", "content": "go"}]
    base.agent_loop(messages, StubLLM(), tools.TOOLS, tools.DISPATCH)
    assert messages[-1]["content"] == "done"
    assert any(m.get("role") == "tool" for m in messages)


def main():
    log_path = Path(tempfile.gettempdir()) / "mekillm_smoke.jsonl"
    if log_path.exists():
        log_path.unlink()
    os.environ["MEKILLM_LOG_FILE"] = str(log_path)

    test_normalize_text()
    test_normalize_tool_call()
    test_normalize_bad_json_args()
    test_observability_hook_and_jsonl(log_path)
    test_run_bash()
    test_dispatch_tools()
    test_dispatch_unknown_tool()
    test_agent_loop_with_stub()
    print("OK — tous les smoke tests passent")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2 : Lancer le smoke et vérifier qu'il passe**

Run: `python packages/_smoke.py`
Expected: `OK — tous les smoke tests passent` (et aucune AssertionError / traceback).

> Si `ModuleNotFoundError: openai` apparaît : exécuter d'abord `pip install "openai>=1.0"` (Task 7 Step 4).

- [ ] **Step 3 : Vérification finale py_compile de tout packages/**

Run: `python -m py_compile packages/mekillm/observability.py packages/mekillm/config.py packages/mekillm/client.py packages/mekillm/__init__.py packages/mekicore/tools.py packages/mekicore/base.py packages/mekicore/main.py packages/_smoke.py`
Expected: aucune sortie (succès).

- [ ] **Step 4 : Commit**

```bash
git add packages/_smoke.py
git commit -m "packages: smoke reseau-free (normalisation, observabilite, outils, boucle)"
```

---

## Vérification manuelle (optionnelle, nécessite une clé OpenRouter)

Avec un `.env` contenant une `OPENROUTER_API_KEY` valide :

```bash
python packages/mekicore/main.py
# puis taper : list the python files in the current directory
```

Attendu : le modèle appelle l'outil `bash`, le résultat s'affiche, puis une réponse texte finale.
Un fichier `packages/mekillm/.logs/calls.jsonl` doit contenir une ligne par appel LLM.

---

## Self-Review (rempli par l'auteur du plan)

**Couverture de la spec :**
- Arborescence (4 fichiers mekillm + 3 mekicore) → Tasks 1-6. ✅
- Interface publique mekillm (LLM, complete, LLMResponse, ToolCall, Usage, observe) → Task 3. ✅
- Normalisation (args parsés, fallback JSON, usage tolérant, message dict) → Task 3 + tests Task 8. ✅
- Observabilité 3 canaux (logging/JSONL/hook) → Task 1 + test Task 8. ✅
- mekicore tools/base/main au format OpenAI → Tasks 4-6. ✅
- Config (requirements openai, .env.example MEKILLM_*, .gitignore .logs) → Task 7. ✅
- Non-régression py_compile + smoke → Tasks 1-8. ✅
- Bascule ollama via .env, zéro code → couverte par config.resolve (Task 2). ✅

**Scan placeholders :** le seul « placeholder » est le faux import volontaire de Task 3 Step 1, immédiatement annulé par la consigne de remplacement intégral — le code final complet est fourni juste après. Aucun TODO/TBD réel.

**Cohérence des types :** `ToolCall(id, name, arguments)`, `Usage(prompt_tokens, completion_tokens, total_tokens)`, `LLMResponse(text, tool_calls, finish_reason, usage, message, raw)`, `CallRecord(...)` — noms identiques entre Task 1/3 (définition), Task 5 (usage `tc.name`/`tc.id`/`tc.arguments`, `resp.message`/`resp.text`/`resp.finish_reason`/`resp.tool_calls`) et Task 8 (tests). `dispatch_tools` / `agent_loop` nommés de façon constante. ✅
