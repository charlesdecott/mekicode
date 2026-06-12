# mekichat — Phase 2 (chat + outils, non-streaming) — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Brancher l'agent dans le front mekichat : envoyer un message déclenche la boucle agent (`run_agent` à événements, sur `mekillm.LLM.complete`), avec l'outil `bash` exécuté et affiché en blocs `[bash]` dans le fil. **Non-streaming** (la réponse arrive d'un bloc par tour).

**Architecture:** On ajoute à `mekicore` une boucle **à événements** (`events.py` + `run_agent`) — `agent_loop` (REPL) est réexprimé dessus sans changer son comportement. Le front (NiceGUI) pilote ce générateur pas-à-pas via `await run.io_bound(next, gen, _DONE)` (sans figer l'UI), rend les événements en direct (bulle assistant + bloc `[bash]`), persiste, et rejoue l'historique d'une session rechargée via `views.render_thread`.

**Tech Stack:** Python 3, NiceGUI 3.x (`run.io_bound`, handlers async), `mekillm` (OpenRouter), `mekicore` (bash). Tests réseau-free (StubLLM) + vérification visuelle Playwright (chromium déjà installé).

**Référence design :** [`docs/superpowers/specs/2026-06-12-front-chat-design.md`](../specs/2026-06-12-front-chat-design.md) §4.2, §6, §10 (phase 2).

---

## Périmètre (phase 2 uniquement)

**Dans la phase 2 :** `run_agent` (événements) + réexpression de `agent_loop` ; outil `bash` exécuté ; rendu live des bulles assistant et des blocs `[bash]` ; rendu de l'historique au rechargement ; gestion d'erreur (bulle rouge) ; persistance après chaque tour ; prompt système seedé.

**Hors phase 2 (phase 3) :** streaming token-par-token (`LLM.stream`, `AssistantDelta`, caret). On reste en **non-streaming** ici. Ne pas ajouter de `stream=`/`LLM.stream`.

## Structure des fichiers

| Fichier | Responsabilité | Testé |
|---------|----------------|-------|
| `packages/mekicore/events.py` | dataclasses d'événements (AssistantDone, ToolStarted, ToolFinished, RunFinished, RunError) | smoke_packages |
| `packages/mekicore/base.py` (modif) | `run_agent(...)` générateur d'événements ; `agent_loop` réexprimé dessus | smoke_packages |
| `packages/mekichat/views.py` (modif) | `render_tool`, `fill_tool`, `render_thread` (+ `import json`) | visuel |
| `packages/mekichat/app.py` (modif) | import LLM/agent ; `send` async pilotant `run_agent` ; rendu live + erreurs ; rechargement via `render_thread` | visuel |
| `packages/mekichat/static/mekichat.css` (modif) | `.run-error` (bulle d'erreur) | visuel |
| `tests/smoke_packages.py` (modif) | tests de `run_agent` (séquence d'événements + erreur), réseau-free | — |
| `docs/wiki-packages/mekichat.md`, `ROADMAP.md` (modif) | doc + statut phase 2 | — |

---

### Task 1 : `run_agent` à événements (mekicore) + réexpression d'`agent_loop` (TDD)

**Files:**
- Create: `packages/mekicore/events.py`
- Modify: `packages/mekicore/base.py`
- Test: `tests/smoke_packages.py`

- [ ] **Step 1 : Écrire les tests qui échouent**

Ajouter dans `tests/smoke_packages.py`, juste avant `def main():`, ces deux tests :

```python
def test_run_agent_events():
    seq = [
        LLMResponse(
            text="", tool_calls=[ToolCall("c1", "bash", {"command": "echo hi"})],
            finish_reason="tool_calls", usage=Usage(),
            message={"role": "assistant", "content": ""},
        ),
        LLMResponse(
            text="fini", tool_calls=[], finish_reason="stop", usage=Usage(),
            message={"role": "assistant", "content": "fini"},
        ),
    ]

    class StubLLM:
        def __init__(self):
            self.i = 0

        def complete(self, messages, tools=None):
            r = seq[self.i]
            self.i += 1
            return r

    msgs = [{"role": "user", "content": "go"}]
    evs = list(base.run_agent(msgs, StubLLM(), tools.TOOLS, tools.DISPATCH))
    assert [type(e).__name__ for e in evs] == ["ToolStarted", "ToolFinished", "AssistantDone", "RunFinished"]
    assert evs[0].name == "bash" and evs[0].args == {"command": "echo hi"}
    assert "hi" in evs[1].output
    assert evs[2].text == "fini"
    # messages mutés en place : message assistant + message role:'tool' + assistant final
    assert any(m.get("role") == "tool" and "hi" in m["content"] for m in msgs)
    assert msgs[-1]["content"] == "fini"


def test_run_agent_error():
    class BoomLLM:
        def complete(self, messages, tools=None):
            raise RuntimeError("boom")

    msgs = [{"role": "user", "content": "go"}]
    evs = list(base.run_agent(msgs, BoomLLM(), tools.TOOLS, tools.DISPATCH))
    assert [type(e).__name__ for e in evs] == ["RunError"]
    assert "boom" in evs[0].message
```

Et les appeler dans `main()` (ajouter ces deux lignes avant le `print("OK ...")`) :

```python
    test_run_agent_events()
    test_run_agent_error()
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python tests/smoke_packages.py`
Expected: `AttributeError: module 'base' has no attribute 'run_agent'` (run_agent n'existe pas encore).

- [ ] **Step 3 : Créer `packages/mekicore/events.py`**

```python
"""events.py — événements émis par run_agent (mekicore), consommés par un front ou le REPL.

Non-streaming (phase 2) : un tour assistant = un AssistantDone ; chaque appel d'outil =
ToolStarted puis ToolFinished ; fin de boucle = RunFinished ; erreur LLM = RunError.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AssistantDone:
    """Texte complet d'un tour assistant."""
    text: str


@dataclass
class ToolStarted:
    id: str
    name: str
    args: dict


@dataclass
class ToolFinished:
    id: str
    name: str
    output: str


@dataclass
class RunFinished:
    pass


@dataclass
class RunError:
    message: str
```

- [ ] **Step 4 : Ajouter `run_agent` + réexprimer `agent_loop` dans `packages/mekicore/base.py`**

Remplacer le contenu de `packages/mekicore/base.py` par :

```python
"""base.py — boucle perception-action (s01 adapté), branchée sur mekillm.

Travaille en format OpenAI : tool_calls normalisés en entrée, messages role:"tool"
en sortie. `run_agent` émet des événements (front/REPL agnostique) ; `agent_loop`
(REPL console) est réexprimé dessus.
"""
from __future__ import annotations

from datetime import datetime

from events import AssistantDone, RunError, RunFinished, ToolFinished, ToolStarted


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


def run_agent(messages, llm, tools, dispatch):
    """Boucle « penser-agir » émettant des événements (non-streaming).

    Mute `messages` en place (append du message assistant puis des messages role:'tool').
    Générateur : ToolStarted/ToolFinished par outil, AssistantDone par texte de tour,
    RunFinished à la fin, RunError si l'appel LLM lève.
    """
    while True:
        try:
            resp = llm.complete(messages, tools=tools)
        except Exception as e:
            yield RunError(str(e))
            return
        messages.append(resp.message)
        if resp.text:
            yield AssistantDone(resp.text)
        if resp.finish_reason != "tool_calls":
            yield RunFinished()
            return
        for tc in resp.tool_calls:
            yield ToolStarted(tc.id, tc.name, tc.arguments)
            handler = dispatch.get(tc.name)
            try:
                output = handler(tc.arguments) if handler else f"Error: Unknown tool '{tc.name}'"
            except Exception as e:
                output = f"Error during tool execution: {e}"
            output = str(output)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": output})
            yield ToolFinished(tc.id, tc.name, output)


def agent_loop(messages, llm, tools, dispatch) -> None:
    """REPL console : consomme run_agent et rend les événements en print (compat s01)."""
    model = getattr(llm, "model", "?")
    for ev in run_agent(messages, llm, tools, dispatch):
        if isinstance(ev, AssistantDone):
            print(f"\033[90m[{datetime.now().strftime('%H:%M:%S')} · {model}]\033[0m {ev.text}")
        elif isinstance(ev, ToolStarted):
            first = str(next(iter(ev.args.values()), ""))[:80] if ev.args else ""
            print(f"\033[33m[{ev.name}] {first}...\033[0m")
        elif isinstance(ev, ToolFinished):
            print(str(ev.output)[:300])
        elif isinstance(ev, RunError):
            print(f"\033[31m[error] {ev.message}\033[0m")
```

- [ ] **Step 5 : Lancer les tests, vérifier qu'ils passent**

Run: `python tests/smoke_packages.py`
Expected: `OK - tous les smoke tests passent` (les tests existants + `test_run_agent_events` + `test_run_agent_error`).

> Note : `test_agent_loop_with_stub` (existant) reste vert car `agent_loop` mute toujours `messages` de la même façon (réexprimé sur `run_agent`, qui utilise `llm.complete`).

- [ ] **Step 6 : `py_compile` + commit**

```bash
python -m py_compile packages/mekicore/events.py packages/mekicore/base.py tests/smoke_packages.py
git add packages/mekicore/events.py packages/mekicore/base.py tests/smoke_packages.py
git commit -m "mekicore: run_agent a evenements + agent_loop reexprime dessus (events.py)"
```

---

### Task 2 : rendu des blocs `[bash]` et de l'historique (`views.py`)

**Files:**
- Modify: `packages/mekichat/views.py`

- [ ] **Step 1 : Ajouter `render_tool`, `fill_tool`, `render_thread`**

En tête de `packages/mekichat/views.py`, ajouter `import json` sous `from __future__ import annotations` :

```python
from __future__ import annotations

import json

from nicegui import ui
```

Puis ajouter ces fonctions à la fin du fichier :

```python
def render_tool(command: str, output: str = "", status: str = "RUN"):
    """Bloc [bash] : commande + sortie + statut. Renvoie (label_statut, label_sortie)
    pour pouvoir remplir la sortie plus tard (chemin live)."""
    with ui.element("div").classes("tool"):
        with ui.element("div").classes("tool-head"):
            ui.label("▣ PROC :: bash").classes("ic")
            ui.label(command).classes("cmd")
            st = ui.label(status).classes("st done" if status == "DONE" else "st")
        out = ui.label(output).classes("tool-out")
    return st, out


def fill_tool(handle, output: str, ok: bool = True) -> None:
    """Remplit un bloc [bash] créé en statut RUN (chemin live)."""
    st, out = handle
    st.set_text("DONE" if ok else "ERR")
    st.classes(replace="st done" if ok else "st")
    out.set_text(output)


def render_thread(messages: list) -> None:
    """Rejoue tout un historique : texte (user/assistant) + blocs [bash] appariés
    (assistant.tool_calls ↔ messages role:'tool'). Chemin de rechargement de session."""
    outputs = {m.get("tool_call_id"): m.get("content", "")
               for m in messages if m.get("role") == "tool"}
    for m in messages:
        role = m.get("role")
        if role in ("user", "assistant") and m.get("content"):
            render_message(m)
        if role == "assistant":
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {})
                try:
                    cmd = json.loads(fn.get("arguments") or "{}").get("command", "")
                except (json.JSONDecodeError, AttributeError):
                    cmd = str(fn.get("arguments", ""))
                render_tool(cmd, output=outputs.get(tc.get("id"), ""), status="DONE")
```

- [ ] **Step 2 : `py_compile`**

Run: `python -m py_compile packages/mekichat/views.py`
Expected: pas d'erreur.

- [ ] **Step 3 : Commit**

```bash
git add packages/mekichat/views.py
git commit -m "mekichat: rendu des blocs [bash] (render_tool/fill_tool) + historique (render_thread)"
```

---

### Task 3 : câblage de l'agent dans la page (`app.py` + CSS erreur)

**Files:**
- Modify: `packages/mekichat/app.py` (réécriture complète ci-dessous)
- Modify: `packages/mekichat/static/mekichat.css` (ajout `.run-error`)

- [ ] **Step 1 : Ajouter le style de bulle d'erreur au CSS**

Dans `packages/mekichat/static/mekichat.css`, juste avant la ligne `.composer{flex:none;...}`, insérer :

```css
  .run-error{margin:10px 14px;padding:10px 14px;clip-path:var(--clip-sm);font-family:var(--mono);font-size:12.5px;color:#ff7a8a;border:1px solid color-mix(in srgb,#ff2247 50%,transparent);background:color-mix(in srgb,#ff2247 12%,transparent)}
```

- [ ] **Step 2 : Réécrire `packages/mekichat/app.py`**

Remplacer **tout** le contenu de `packages/mekichat/app.py` par :

```python
#!/usr/bin/env python3
"""app.py — front mekichat (NiceGUI). Phase 2 : chat + outils (bash), non-streaming."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))                      # import sessions, views
sys.path.insert(0, str(HERE.parent))               # import mekillm (packages/)
sys.path.insert(0, str(HERE.parent / "mekicore"))  # import base, tools, events

from nicegui import run, ui  # noqa: E402

import events  # noqa: E402
import mekillm  # noqa: E402
import sessions as sessions_mod  # noqa: E402
import views  # noqa: E402
from base import run_agent  # noqa: E402
from tools import DISPATCH, TOOLS  # noqa: E402

STATIC = HERE / "static"
DEFAULT_MODEL = mekillm.config.resolve()["model"]
SYSTEM = f"You are a coding agent at {Path.cwd()}. Use the bash tool to act. Be concise."
FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Chakra+Petch:wght@400;500;600;700&family=Share+Tech+Mono&display=swap" rel="stylesheet">'
)
_BG = (
    '<div class="bg"><div class="grid"></div><div class="vig"></div>'
    '<div class="scan"></div><div class="noise"></div><div class="sweep"></div>'
    '<div class="mosh"></div><div class="mosh b"></div></div>'
)
_DONE = object()  # sentinelle de fin de générateur pour run.io_bound(next, gen, _DONE)

_store: sessions_mod.SessionStore | None = None
_llm = None


def _get_store() -> sessions_mod.SessionStore:
    """Singleton paresseux : évite de créer .sessions/ au simple import du module."""
    global _store
    if _store is None:
        _store = sessions_mod.SessionStore()
    return _store


def _get_llm():
    """Singleton paresseux du provider LLM (peut lever si pas de clé : géré à l'appel)."""
    global _llm
    if _llm is None:
        _llm = mekillm.LLM()
    return _llm


def _ensure_current() -> sessions_mod.Session:
    """Charge la session la plus récente, ou en crée une (avec prompt système)."""
    store = _get_store()
    metas = store.list()
    return store.load(metas[0].id) if metas else store.create(model=DEFAULT_MODEL, system=SYSTEM)


def _now_hms() -> str:
    return datetime.now().strftime("%H:%M:%S")


@ui.page("/")
def index() -> None:
    ui.add_head_html(FONTS)
    ui.add_css((STATIC / "mekichat.css").read_text(encoding="utf-8"))
    ui.query("body").props('data-theme=phosphor')

    current = _ensure_current()
    clock_ref: dict[str, object] = {"label": None}
    thread_ref: dict[str, object] = {"inner": None}
    state = {"busy": False}

    def open_session(session_id: str) -> None:
        nonlocal current
        current = _get_store().load(session_id)
        _refresh()

    def new_session() -> None:
        nonlocal current
        current = _get_store().create(model=DEFAULT_MODEL, system=SYSTEM)
        _refresh()

    def _render_error(message: str) -> None:
        with ui.element("div").classes("run-error"):
            ui.label(f"⚠ {message}")

    def _render_event(ev, handles: dict) -> None:
        if isinstance(ev, events.AssistantDone):
            if ev.text:
                views.render_message({"role": "assistant", "content": ev.text})
        elif isinstance(ev, events.ToolStarted):
            cmd = str(ev.args.get("command", "")) if isinstance(ev.args, dict) else ""
            handles[ev.id] = views.render_tool(cmd)
        elif isinstance(ev, events.ToolFinished):
            handle = handles.get(ev.id)
            ok = not ev.output.startswith("Error")
            if handle is not None:
                views.fill_tool(handle, ev.output, ok=ok)
            else:
                views.render_tool("", output=ev.output, status="DONE")
        elif isinstance(ev, events.RunError):
            _render_error(ev.message)

    async def send(text: str) -> None:
        text = text.strip()
        if not text or state["busy"]:
            return
        state["busy"] = True
        try:
            store = _get_store()
            current.add("user", text)
            store.save(current)
            inner = thread_ref["inner"]
            with inner:
                views.render_message({"role": "user", "content": text})
            try:
                llm = _get_llm()
            except Exception as e:  # pas de clé / config invalide
                with inner:
                    _render_error(f"LLM indisponible : {e}")
                return
            gen = run_agent(current.messages, llm, TOOLS, DISPATCH)
            handles: dict = {}
            while True:
                ev = await run.io_bound(next, gen, _DONE)
                if ev is _DONE or isinstance(ev, events.RunFinished):
                    break
                with inner:
                    _render_event(ev, handles)
            store.save(current)
            _refresh_sidebar()
        finally:
            state["busy"] = False

    def _tick() -> None:
        label = clock_ref["label"]
        if label is not None:
            label.set_text(_now_hms())

    ui.html(_BG)  # fond animé plein écran (derrière l'UI)

    app_root = ui.element("div").classes("app")
    with app_root:
        sidebar = ui.element("aside").classes("sidebar")
        main = ui.element("section").classes("main")

    def _refresh_sidebar() -> None:
        store = _get_store()
        sidebar.clear()
        with sidebar:
            with ui.element("div").classes("brand"):
                with ui.element("div").classes("glyph"):
                    ui.label("M")
                with ui.element("div"):
                    ui.html('<div class="glitch" data-t="MEKICHAT">MEKICHAT</div>')
                    ui.label("// harness v0.1 :: ROOT").classes("ver")
            ui.button("+ nouvelle session", on_click=lambda _: new_session()).props("flat no-caps").classes("new-btn")
            metas = store.list()
            with ui.element("div").classes("sec-label"):
                ui.label("SESSIONS")
                ui.label(f"[{len(metas):02d}]").classes("n")
            with ui.element("div").classes("sessions"):
                for meta in metas:
                    views.render_session_item(
                        meta, active=(meta.id == current.id),
                        on_click=lambda _, sid=meta.id: open_session(sid),
                    )
            with ui.element("div").classes("sidebar-foot"):
                ui.element("span").classes("led")
                ui.label("OPENROUTER :: LINK_OK")

    def _refresh() -> None:
        _refresh_sidebar()
        main.clear()
        with main:
            with ui.element("header").classes("topbar"):
                with ui.element("div").classes("channel"):
                    ui.label("[#]").classes("br")
                    ui.html("<h1>conversation</h1>")
                    ui.label(f"// {current.title}").classes("sub")
                with ui.element("div").classes("chips"):
                    _chip("MODEL", current.model, "model")
                    _chip("SID", current.id, "sid")
                    _chip("TOK", "0↑ 0↓", "")
                    clock_ref["label"] = _chip("⌚", _now_hms(), "")
            with ui.element("div").classes("thread"):
                inner = ui.element("div").classes("thread-inner")
                thread_ref["inner"] = inner
                with inner:
                    views.render_thread(current.messages)
            with ui.element("div").classes("composer"):
                with ui.element("div").classes("composer-inner"):
                    with ui.element("div").classes("input-wrap"):
                        box = ui.textarea(placeholder="// message à mekicore (l'agent peut lancer des commandes bash)")
                        box.props("borderless autogrow").classes("ta")

                        async def _do_send(_=None) -> None:
                            value = box.value
                            box.set_value("")
                            await send(value)

                        ui.button("▸", on_click=_do_send).props("flat").classes("send")

    _refresh()
    ui.timer(1.0, _tick)


def _chip(key: str, value: str, extra: str):
    with ui.element("div").classes(f"chip {extra}"):
        ui.label(key).classes("k")
        lbl = ui.label(value)
    return lbl


if __name__ in {"__main__", "__mp_main__"}:   # garde requise par NiceGUI (reload/multiprocessing)
    ui.run(title="mekichat", port=8080, dark=True, reload=False, show=True)
```

- [ ] **Step 3 : `py_compile`**

Run: `python -m py_compile packages/mekichat/app.py`
Expected: pas d'erreur.

- [ ] **Step 4 : Commit**

```bash
git add packages/mekichat/app.py packages/mekichat/static/mekichat.css
git commit -m "mekichat: cabler l'agent (run_agent) dans la page — chat + blocs bash, gestion erreur"
```

---

### Task 4 : vérification (réseau-free + Playwright) et docs

**Files:**
- Create (jetable, gitignoré): `.refactor-tmp/diag_phase2.py`
- Modify: `docs/wiki-packages/mekichat.md`, `ROADMAP.md`

- [ ] **Step 1 : Non-régression réseau-free (les deux suites)**

Run: `python tests/smoke_packages.py`
Expected: `OK - tous les smoke tests passent` (inclut les tests run_agent).
Run: `python tests/smoke_mekichat.py`
Expected: `OK - smoke mekichat passe`.

- [ ] **Step 2 : Vérification visuelle DÉTERMINISTE des blocs `[bash]` (sans réseau)**

On fabrique une session pré-remplie (user + assistant avec tool_call + résultat bash + assistant final),
on la charge dans l'UI et on capture — ça valide `render_thread`/`render_tool` sans dépendre du LLM.

Create `.refactor-tmp/diag_phase2.py` :

```python
"""diag_phase2.py — vérifie le rendu d'une conversation avec bloc [bash] (déterministe, sans LLM)."""
import json
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

# 1) session pré-fabriquée dans un dossier temporaire
d = tempfile.mkdtemp(prefix="mekichat_diag_")
sid = "diag01"
session = {
    "id": sid, "title": "Compter les .py", "model": "openrouter/owl-alpha",
    "created_at": "2026-06-12T10:00:00+00:00",
    "messages": [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "Combien de fichiers .py dans packages/ ?"},
        {"role": "assistant", "content": "Je vérifie.",
         "tool_calls": [{"id": "t1", "type": "function",
                         "function": {"name": "bash", "arguments": json.dumps({"command": "find packages -name '*.py' | wc -l"})}}]},
        {"role": "tool", "tool_call_id": "t1", "content": "7"},
        {"role": "assistant", "content": "Il y a 7 fichiers Python dans packages/."},
    ],
}
Path(d, f"{sid}.json").write_text(json.dumps(session, ensure_ascii=False), encoding="utf-8")
print("session écrite dans", d)
print("Lance le serveur AVANT ce script avec :")
print(f'  MEKICHAT_SESSIONS_DIR="{d}" python packages/mekichat/app.py   (ou export selon le shell)')

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.goto("http://127.0.0.1:8080", wait_until="networkidle", timeout=20000)
    page.wait_for_timeout(1200)
    n_msg = page.eval_on_selector_all(".msg", "els => els.length")
    n_tool = page.eval_on_selector_all(".tool", "els => els.length")
    cmd = page.eval_on_selector(".tool .cmd", "el => el.textContent") if n_tool else None
    out = page.eval_on_selector(".tool .tool-out", "el => el.textContent") if n_tool else None
    page.screenshot(path=".refactor-tmp/phase2_thread.png", full_page=False)
    print(f".msg={n_msg}  .tool={n_tool}  cmd={cmd!r}  out={out!r}")
    b.close()
```

Lancer le serveur sur ce dossier temp, PUIS le script. En PowerShell (Windows) :
```powershell
# terminal 1 : démarrer le serveur sur le dossier de la session diag (récupérer le chemin imprimé par le script au 1er run)
$env:MEKICHAT_SESSIONS_DIR="<dossier temp imprimé>"; python packages/mekichat/app.py
# terminal 2 :
python .refactor-tmp/diag_phase2.py
```
Ou en bash : `MEKICHAT_SESSIONS_DIR=<dir> python packages/mekichat/app.py &` puis le script.

Expected: la sortie affiche `.msg=3  .tool=1  cmd='find packages -name ...'  out='7'`, et **lire l'image** `.refactor-tmp/phase2_thread.png` doit montrer : 2 bulles assistant + 1 bulle user + un bloc `[bash]` ambre (commande + sortie `7` + statut DONE). Itérer (corriger views/CSS) jusqu'à rendu correct. **Ne pas conclure sans avoir regardé l'image.**

- [ ] **Step 3 : Vérification LIVE (vraie réponse LLM)**

`.env` contient une clé (`mekillm.LLM()` se construit, modèle `openrouter/owl-alpha`). Démarrer le serveur normalement (`.\start-chat.ps1` ou `python packages/mekichat/app.py`, dossier `.sessions/` par défaut). Avec Playwright, créer une session, envoyer « Combien de fichiers .py dans packages/ ? utilise bash », attendre la réponse, capturer :

```python
# extrait à exécuter (adapter diag_phase2.py ou un nouveau script) :
page.click("button.new-btn"); page.wait_for_timeout(400)
page.fill(".input-wrap textarea", "Combien de fichiers .py dans packages/ ? utilise bash")
page.click("button.send")
page.wait_for_timeout(12000)  # laisser le tour LLM + bash se faire
print("msgs:", page.eval_on_selector_all(".msg", "e=>e.length"), " tools:", page.eval_on_selector_all(".tool", "e=>e.length"))
page.screenshot(path=".refactor-tmp/phase2_live.png")
```

Expected: au moins une bulle assistant apparaît (et idéalement un bloc `[bash]` si le modèle appelle l'outil). **Lire l'image.** Le résultat LLM est non-déterministe : l'objectif est de confirmer que le chemin live fonctionne (pas de traceback, réponse rendue), pas un contenu exact. Si le modèle n'appelle jamais bash, la Step 2 reste la preuve déterministe du rendu des blocs.

- [ ] **Step 4 : Mettre à jour la doc**

- `docs/wiki-packages/mekichat.md` : section « Statut » → phase 2 livrée (chat + outil bash, non-streaming) ; section `app.py` → mentionner `send` async pilotant `run_agent` via `run.io_bound`, et `views.render_tool`/`render_thread` ; ajouter `mekicore` (`run_agent`/`events.py`) dans les relations. Mettre à jour la liste des fonctions de `views.py` (ajout `render_tool`, `fill_tool`, `render_thread`). **Lire les fichiers réels d'abord** pour ne documenter que ce qui existe.
- `ROADMAP.md` : passer `packages/mekichat` phase 2 en livrée ; dans le tableau s01–s23, `packages/` : s02 (tool use) → ✅, s01 inchangé. Ajuster la phrase d'avancement.

- [ ] **Step 5 : Commit**

```bash
git add docs/wiki-packages/mekichat.md ROADMAP.md
git commit -m "doc: mekichat phase 2 livree (chat + outil bash) — wiki-packages + ROADMAP"
```

---

## Self-review (rempli pendant l'écriture)

**Couverture du spec (phase 2) :** `run_agent` + events → Task 1 ✅ ; `agent_loop` réexprimé sans régression → Task 1 (test existant conservé) ✅ ; outil bash exécuté + blocs `[bash]` → Tasks 1-3 ✅ ; rendu live (io_bound pas-à-pas) → Task 3 ✅ ; rechargement d'historique → Task 2 (`render_thread`) + Task 3 ✅ ; gestion d'erreur (RunError → bulle) → Tasks 1+3 ✅ ; persistance par tour → Task 3 (`store.save` après la boucle) ✅ ; prompt système → Task 3 (`SYSTEM`) ✅. Streaming exclu (phase 3) ✅.

**Placeholders :** le chip `TOK 0↑ 0↓` reste un affichage volontaire (les vrais tokens viendront via un hook `observe`, hors périmètre). Aucun placeholder de code.

**Cohérence des types/noms :** événements `AssistantDone(text)`, `ToolStarted(id,name,args)`, `ToolFinished(id,name,output)`, `RunFinished`, `RunError(message)` — utilisés identiquement dans `base.run_agent`, les tests, `_render_event`. `views.render_tool(command,output,status) -> (st,out)` et `views.fill_tool((st,out),output,ok)` cohérents. `run_agent(messages, llm, tools, dispatch)` signature unique. `run.io_bound(next, gen, _DONE)` + sentinelle `_DONE`.

**Risques :** (1) `await run.io_bound(next, gen, _DONE)` — vérifier en exécutant que NiceGUI 3.x accepte `run.io_bound(func, *args)` ; sinon envelopper dans `lambda: next(gen, _DONE)`. (2) Rendu d'une sortie bash avec retours-ligne dans `ui.label` `.tool-out` (le CSS a `white-space:pre-wrap`) — vérifié visuellement Step 2. (3) `mekillm.config` accessible comme attribut (importé par `client.py`) — sinon `from mekillm import config`.
