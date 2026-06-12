# mekichat — Phase 3 (streaming token-par-token) — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Streamer les réponses de l'agent **token par token** : `mekillm.LLM.stream()` (la pièce s13), un événement `AssistantDelta`, un mode streaming de `run_agent`, et un rendu front qui construit la bulle en direct avec un **caret clignotant**, finalisé en markdown à la fin du tour.

**Architecture:** `mekillm` gagne `stream()` (générateur de tokens qui **réassemble** texte + `tool_calls` + `finish_reason` en un `LLMResponse` final, via une fonction pure `_consume_stream` testable). `mekicore` gagne l'événement `AssistantDelta` et un paramètre `stream=True` de `run_agent` (les outils marchent comme avant — c'est juste le **texte** qui arrive en flux). Le front, déjà piloté pas-à-pas via `run.io_bound(next, gen)`, rend chaque `AssistantDelta` dans une bulle de streaming (texte brut + caret), puis la **finalise en markdown** sur `AssistantDone`.

**Tech Stack:** Python 3, SDK `openai` (`stream=True`, chunks `delta`), NiceGUI. Tests réseau-free (faux chunks / StubLLM) + vérification visuelle Playwright (caret + flux).

**Référence design :** [`docs/superpowers/specs/2026-06-12-front-chat-design.md`](../specs/2026-06-12-front-chat-design.md) §4.1, §10 (phase 3).

---

## Périmètre (phase 3 uniquement)

**Dans la phase 3 :** `LLM.stream()` + `_consume_stream` (réassemblage) ; événement `AssistantDelta` ; `run_agent(stream=True)` ; rendu front en flux (bulle de streaming + caret, finalisée en markdown) ; le REPL `agent_loop` reste **non-streaming** (inchangé). Les outils (`bash`) fonctionnent en streaming comme en non-streaming.

**Hors périmètre :** comptage de tokens en streaming (l'usage restera `0` sans `stream_options`, limitation assumée) ; interruption d'un flux en cours (s19).

## Structure des fichiers

| Fichier | Responsabilité | Testé |
|---------|----------------|-------|
| `packages/mekillm/client.py` (modif) | `_consume_stream(chunks)` (réassemblage pur) + `LLM.stream()` | smoke_packages |
| `packages/mekicore/events.py` (modif) | événement `AssistantDelta(text)` | smoke_packages |
| `packages/mekicore/base.py` (modif) | `run_agent(..., stream=False)` : mode streaming | smoke_packages |
| `packages/mekichat/views.py` (modif) | `render_stream_bubble()`, `finalize_stream()` | visuel |
| `packages/mekichat/static/mekichat.css` (modif) | caret de streaming (`.body.streaming::after`) | visuel |
| `packages/mekichat/app.py` (modif) | rendu des `AssistantDelta` (bulle live) + finalisation | visuel |
| `tests/smoke_packages.py` (modif) | tests `_consume_stream` + `run_agent(stream=True)` | — |
| `docs/wiki-packages/mekichat.md`, `ROADMAP.md` (modif) | doc + statut phase 3 | — |

---

### Task 1 : `mekillm.LLM.stream()` + réassemblage `_consume_stream` (TDD)

**Files:**
- Modify: `packages/mekillm/client.py`
- Test: `tests/smoke_packages.py`

- [ ] **Step 1 : Écrire les tests qui échouent**

Dans `tests/smoke_packages.py`, ajouter avant `def main():` :

```python
def test_consume_stream_text():
    from mekillm.client import _consume_stream
    chunks = [
        NS(choices=[NS(delta=NS(content="Bon", tool_calls=None), finish_reason=None)], usage=None),
        NS(choices=[NS(delta=NS(content="jour", tool_calls=None), finish_reason=None)], usage=None),
        NS(choices=[NS(delta=NS(content=None, tool_calls=None), finish_reason="stop")], usage=None),
    ]
    gen = _consume_stream(iter(chunks))
    tokens = []
    try:
        while True:
            tokens.append(next(gen))
    except StopIteration as stop:
        resp = stop.value
    assert tokens == ["Bon", "jour"]
    assert resp.text == "Bonjour"
    assert resp.finish_reason == "stop"
    assert resp.tool_calls == []
    assert resp.message == {"role": "assistant", "content": "Bonjour"}


def test_consume_stream_tool_call():
    from mekillm.client import _consume_stream
    # arguments fragmentés sur plusieurs chunks ; id/name dans le premier
    chunks = [
        NS(choices=[NS(delta=NS(content=None, tool_calls=[
            NS(index=0, id="call_1", function=NS(name="bash", arguments='{"comm'))]), finish_reason=None)], usage=None),
        NS(choices=[NS(delta=NS(content=None, tool_calls=[
            NS(index=0, id=None, function=NS(name=None, arguments='and": "ls"}'))]), finish_reason=None)], usage=None),
        NS(choices=[NS(delta=NS(content=None, tool_calls=None), finish_reason="tool_calls")], usage=None),
    ]
    gen = _consume_stream(iter(chunks))
    tokens = list(_drain(gen))
    resp = _drain.value
    assert tokens == []  # pas de texte
    assert resp.finish_reason == "tool_calls"
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].id == "call_1"
    assert resp.tool_calls[0].name == "bash"
    assert resp.tool_calls[0].arguments == {"command": "ls"}
    assert resp.message["tool_calls"][0]["function"]["arguments"] == '{"command": "ls"}'
```

Et ajouter ce petit utilitaire de test (draine un générateur et mémorise sa valeur de retour) **au-dessus** de ces tests :

```python
def _drain(gen):
    """Itère gen jusqu'au bout ; mémorise la valeur de return dans _drain.value."""
    try:
        while True:
            yield next(gen)
    except StopIteration as stop:
        _drain.value = stop.value
```

Et les appeler dans `main()` (avant le print) :

```python
    test_consume_stream_text()
    test_consume_stream_tool_call()
```

> `NS` est `types.SimpleNamespace`, déjà importé en tête de `tests/smoke_packages.py` (`from types import SimpleNamespace as NS`).

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python tests/smoke_packages.py`
Expected: `ImportError: cannot import name '_consume_stream' from 'mekillm.client'`.

- [ ] **Step 3 : Ajouter `_consume_stream` + `LLM.stream` dans `packages/mekillm/client.py`**

Ajouter cette fonction au niveau module (après `_normalize`) :

```python
def _consume_stream(chunks):
    """Réassemble un flux de chunks SDK en LLMResponse. Générateur : yield chaque token de
    texte, **return** le LLMResponse final (texte + tool_calls reconstruits + finish_reason)."""
    text_parts: list[str] = []
    tool_acc: dict = {}  # index -> {"id", "name", "args"}
    finish_reason = ""
    usage = Usage()
    for chunk in chunks:
        u = getattr(chunk, "usage", None)
        if u:
            usage = Usage(
                prompt_tokens=getattr(u, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(u, "completion_tokens", 0) or 0,
                total_tokens=getattr(u, "total_tokens", 0) or 0,
            )
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        choice = choices[0]
        delta = choice.delta
        if getattr(delta, "content", None):
            text_parts.append(delta.content)
            yield delta.content
        for tc in (getattr(delta, "tool_calls", None) or []):
            acc = tool_acc.setdefault(tc.index, {"id": "", "name": "", "args": ""})
            if getattr(tc, "id", None):
                acc["id"] = tc.id
            fn = getattr(tc, "function", None)
            if fn is not None:
                if getattr(fn, "name", None):
                    acc["name"] = fn.name
                if getattr(fn, "arguments", None):
                    acc["args"] += fn.arguments
        if getattr(choice, "finish_reason", None):
            finish_reason = choice.finish_reason

    text = "".join(text_parts)
    tool_calls = []
    msg_tool_calls = []
    for idx in sorted(tool_acc):
        acc = tool_acc[idx]
        try:
            args = json.loads(acc["args"] or "{}")
        except json.JSONDecodeError:
            log.warning("arguments JSON invalides (stream) pour l'outil %s", acc["name"])
            args = {}
        tool_calls.append(ToolCall(id=acc["id"], name=acc["name"], arguments=args))
        msg_tool_calls.append({
            "id": acc["id"], "type": "function",
            "function": {"name": acc["name"], "arguments": acc["args"]},
        })
    message = {"role": "assistant", "content": text}
    if msg_tool_calls:
        message["tool_calls"] = msg_tool_calls
    return LLMResponse(
        text=text, tool_calls=tool_calls, finish_reason=finish_reason,
        usage=usage, message=message, raw=None,
    )
```

Ajouter la méthode `stream` à la classe `LLM` (juste après `complete`) :

```python
    def stream(self, messages, tools=None, system=None, max_tokens=8000, **kwargs):
        """Comme complete(), mais en flux : générateur de tokens de texte ; return le
        LLMResponse final. Émet un CallRecord (usage à 0 en streaming). Réassemble les tool_calls."""
        sent = list(messages)
        if system:
            sent = [{"role": "system", "content": system}] + sent
        params = dict(model=self.model, messages=sent, max_tokens=max_tokens, stream=True, **kwargs)
        if tools:
            params["tools"] = tools

        start = time.perf_counter()
        rec = {"status": "ok", "error": None, "finish_reason": "", "usage": Usage()}
        try:
            chunks = self._client.chat.completions.create(**params)
            out = yield from _consume_stream(chunks)
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

- [ ] **Step 4 : Lancer, vérifier que ça passe**

Run: `python tests/smoke_packages.py`
Expected: `OK - tous les smoke tests passent`.

- [ ] **Step 5 : `py_compile` + commit**

```bash
python -m py_compile packages/mekillm/client.py tests/smoke_packages.py
git add packages/mekillm/client.py tests/smoke_packages.py
git commit -m "mekillm: LLM.stream() + reassemblage du flux (_consume_stream) — s13"
```

---

### Task 2 : événement `AssistantDelta` + mode streaming de `run_agent` (TDD)

**Files:**
- Modify: `packages/mekicore/events.py`
- Modify: `packages/mekicore/base.py`
- Test: `tests/smoke_packages.py`

- [ ] **Step 1 : Écrire le test qui échoue**

Dans `tests/smoke_packages.py`, ajouter avant `def main():` :

```python
def test_run_agent_streaming():
    class StubLLM:
        model = "stub"

        def stream(self, messages, tools=None):
            for t in ["Sa", "lut"]:
                yield t
            return LLMResponse(
                text="Salut", tool_calls=[], finish_reason="stop", usage=Usage(),
                message={"role": "assistant", "content": "Salut"},
            )

    msgs = [{"role": "user", "content": "hi"}]
    evs = list(base.run_agent(msgs, StubLLM(), tools.TOOLS, tools.DISPATCH, stream=True))
    assert [type(e).__name__ for e in evs] == [
        "ThinkingStarted", "AssistantDelta", "AssistantDelta", "AssistantDone", "RunFinished",
    ]
    assert evs[1].text == "Sa" and evs[2].text == "lut"
    assert evs[3].text == "Salut"
    assert msgs[-1]["content"] == "Salut"
```

Et l'appeler dans `main()` (avant le print) :

```python
    test_run_agent_streaming()
```

- [ ] **Step 2 : Lancer, vérifier l'échec**

Run: `python tests/smoke_packages.py`
Expected: échec — `TypeError: run_agent() got an unexpected keyword argument 'stream'` (ou `AttributeError` sur `AssistantDelta`).

- [ ] **Step 3 : Ajouter `AssistantDelta` à `events.py`**

Dans `packages/mekicore/events.py`, ajouter (au-dessus de `AssistantDone`) :

```python
@dataclass
class AssistantDelta:
    """Fragment de texte assistant (streaming)."""
    text: str
```

- [ ] **Step 4 : Ajouter le mode streaming à `run_agent` dans `base.py`**

Mettre à jour l'import en tête de `packages/mekicore/base.py` :

```python
from events import AssistantDelta, AssistantDone, RunError, RunFinished, ThinkingStarted, ToolFinished, ToolStarted
```

Remplacer la signature et le bloc d'obtention de `resp` dans `run_agent`. La fonction devient :

```python
def run_agent(messages, llm, tools, dispatch, *, stream=False):
    """Boucle « penser-agir » émettant des événements.

    Mute `messages` en place. Si `stream=True`, le texte assistant arrive en `AssistantDelta`
    (puis un `AssistantDone` final) via `llm.stream()` ; sinon un seul `AssistantDone` via
    `llm.complete()`. Les outils fonctionnent dans les deux cas.
    """
    while True:
        yield ThinkingStarted()
        try:
            if stream:
                gen = llm.stream(messages, tools=tools)
                while True:
                    try:
                        token = next(gen)
                    except StopIteration as stop:
                        resp = stop.value
                        break
                    yield AssistantDelta(token)
            else:
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
        if not resp.tool_calls:           # réponse provider malformée : éviter la boucle infinie
            yield RunError("finish_reason='tool_calls' mais tool_calls vide")
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
```

> `agent_loop` (REPL) reste inchangé : il appelle `run_agent(...)` sans `stream`, donc `stream=False`, donc comportement non-streaming identique. Les tests existants (`test_run_agent_events`, etc.) restent verts.

- [ ] **Step 5 : Lancer, vérifier que ça passe**

Run: `python tests/smoke_packages.py`
Expected: `OK - tous les smoke tests passent`.

- [ ] **Step 6 : `py_compile` + commit**

```bash
python -m py_compile packages/mekicore/events.py packages/mekicore/base.py tests/smoke_packages.py
git add packages/mekicore/events.py packages/mekicore/base.py tests/smoke_packages.py
git commit -m "mekicore: run_agent(stream=True) + evenement AssistantDelta"
```

---

### Task 3 : rendu du streaming dans le front (`views.py` + CSS + `app.py`)

**Files:**
- Modify: `packages/mekichat/views.py`
- Modify: `packages/mekichat/static/mekichat.css`
- Modify: `packages/mekichat/app.py`

- [ ] **Step 1 : Helpers de bulle de streaming dans `views.py`**

Ajouter à la fin de `packages/mekichat/views.py` :

```python
def render_stream_bubble():
    """Bulle assistant en cours de streaming. Renvoie (conteneur_body, label_texte) :
    on met à jour le label à chaque token, puis on finalise via finalize_stream()."""
    with ui.element("div").classes("msg bot"):
        with ui.element("div").classes("avatar bot"):
            ui.label("M")
        with ui.element("div"):
            with ui.element("div").classes("head"):
                ui.label("mekicore").classes("who")
                ui.label("//AGENT").classes("tag")
            body = ui.element("div").classes("body streaming")
            with body:
                lbl = ui.label("")
    return body, lbl


def finalize_stream(body, text: str) -> None:
    """Remplace le texte brut streamé par le rendu markdown final (retire le caret)."""
    body.classes(remove="streaming")
    body.clear()
    with body:
        ui.markdown(text, extras=["fenced-code-blocks", "tables", "break-on-newline"])
```

- [ ] **Step 2 : Caret de streaming dans le CSS**

Dans `packages/mekichat/static/mekichat.css`, juste après la ligne `.body.plain{white-space:pre-wrap;word-break:break-word}`, ajouter :

```css
  .body.streaming{white-space:pre-wrap;word-break:break-word}
  .body.streaming::after{content:"";display:inline-block;width:8px;height:1.05em;vertical-align:text-bottom;margin-left:2px;background:var(--p1);box-shadow:var(--p1-glow);animation:cblink 1s steps(1) infinite}
```

- [ ] **Step 3 : Câbler le streaming dans `app.py`**

Dans `packages/mekichat/app.py`, faire trois modifications ciblées :

(a) Activer le streaming à l'appel de `run_agent` dans `send()` — remplacer la ligne :
```python
            gen = run_agent(current.messages, llm, TOOLS, DISPATCH)
```
par :
```python
            gen = run_agent(current.messages, llm, TOOLS, DISPATCH, stream=True)
```

(b) Ajouter un état de bulle de streaming. Juste après la ligne `thinking_ref: dict[str, object] = {"el": None}` (dans `index()`), ajouter :
```python
    stream_ref: dict[str, object] = {"body": None, "lbl": None, "text": ""}
```

(c) Gérer `AssistantDelta` et adapter `AssistantDone` dans `_render_event`. Remplacer le corps de `_render_event` (la partie après `with inner:`) par :
```python
        _clear_thinking()
        with inner:
            if isinstance(ev, events.AssistantDelta):
                if stream_ref["body"] is None:
                    body, lbl = views.render_stream_bubble()
                    stream_ref["body"], stream_ref["lbl"], stream_ref["text"] = body, lbl, ""
                stream_ref["text"] = stream_ref["text"] + ev.text
                stream_ref["lbl"].set_text(stream_ref["text"])
            elif isinstance(ev, events.AssistantDone):
                if stream_ref["body"] is not None:
                    views.finalize_stream(stream_ref["body"], ev.text)
                    stream_ref["body"] = None
                elif ev.text:
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
                if stream_ref["body"] is not None:   # fige la bulle partielle (retire le caret)
                    views.finalize_stream(stream_ref["body"], stream_ref["text"])
                    stream_ref["body"] = None
                _render_error(ev.message)
```

(d) Réinitialiser l'état de streaming au début d'un envoi. Dans `send()`, juste après `state["busy"] = True`, ajouter :
```python
        stream_ref["body"] = None
```
Et dans `_refresh()`, juste après `thinking_ref["el"] = None`, ajouter :
```python
        stream_ref["body"] = None
```

> Note : `_render_event` doit voir `stream_ref` et `views` — ils sont déjà dans la portée de `index()` (closure). `render_stream_bubble`/`finalize_stream` viennent de `views` (Step 1).

- [ ] **Step 4 : `py_compile`**

Run: `python -m py_compile packages/mekichat/app.py packages/mekichat/views.py`
Expected: pas d'erreur.

- [ ] **Step 5 : Commit**

```bash
git add packages/mekichat/views.py packages/mekichat/static/mekichat.css packages/mekichat/app.py
git commit -m "mekichat: rendu du streaming (bulle live + caret, finalisee en markdown)"
```

---

### Task 4 : vérification (Playwright) + docs

**Files:**
- Create (jetable, gitignoré): `.refactor-tmp/diag_stream.py`
- Modify: `docs/wiki-packages/mekichat.md`, `ROADMAP.md`

- [ ] **Step 1 : Non-régression réseau-free**

Run: `python tests/smoke_packages.py` → `OK - tous les smoke tests passent` (inclut `_consume_stream` + `run_agent(stream=True)`).
Run: `python tests/smoke_mekichat.py` → `OK - smoke mekichat passe`.

- [ ] **Step 2 : Vérification LIVE du streaming (Playwright)**

Démarrer le serveur (`python packages/mekichat/app.py`, tuer d'abord tout process sur 8080). Script `.refactor-tmp/diag_stream.py` : envoie un message qui appelle une longue réponse, échantillonne la longueur du texte de la bulle de streaming **plusieurs fois** pour prouver qu'elle **grossit progressivement** (= streaming), vérifie la présence du caret pendant le flux puis son absence à la fin, et capture.

```python
"""diag_stream.py — prouve le streaming : la bulle grossit token par token, caret pendant le flux."""
import json
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.goto("http://127.0.0.1:8080", wait_until="networkidle", timeout=20000)
    page.wait_for_timeout(1200)
    page.click("button.new-btn"); page.wait_for_timeout(500)
    page.fill(".input-wrap textarea", "Explique en 5 phrases ce qu'est une boucle agent perception-action.")
    page.click("button.send")
    lengths, caret_seen = [], False
    for _ in range(40):
        page.wait_for_timeout(700)
        if page.query_selector(".body.streaming"):
            caret_seen = True
            txt = page.eval_on_selector(".body.streaming", "e=>e.textContent") or ""
            lengths.append(len(txt))
        elif page.query_selector_all(".msg .body") and len(page.query_selector_all(".msg .body")) >= 2:
            break
    page.wait_for_timeout(800)
    res = {
        "caret_pendant_flux": caret_seen,
        "longueurs_echantillonnees": lengths,
        "croissance": len(lengths) >= 2 and lengths[-1] > lengths[0],
        "caret_apres": page.query_selector(".body.streaming") is not None,
        "msg_bodies": len(page.query_selector_all(".msg .body")),
        "rendu_markdown_final": page.query_selector(".msg.bot .body") is not None,
    }
    page.screenshot(path=".refactor-tmp/stream.png")
    print(json.dumps(res, ensure_ascii=False, indent=2))
    b.close()
```

Lancer : `python .refactor-tmp/diag_stream.py`.
Expected: `caret_pendant_flux=true`, `longueurs_echantillonnees` croissante (`croissance=true`), `caret_apres=false` (caret retiré à la fin), et **lire `.refactor-tmp/stream.png`** : la réponse est rendue en markdown, sans caret résiduel. Itérer jusqu'à rendu correct. **Ne pas conclure sans avoir regardé l'image.**

> Si le modèle configuré ne supporte pas `stream=True`, l'envoi affichera une bulle d'erreur : le noter, et s'appuyer sur les tests réseau-free (Task 1/2) comme preuve du réassemblage. Vérifier le log serveur : aucun traceback.

- [ ] **Step 3 : Mettre à jour la doc**

- `docs/wiki-packages/mekichat.md` : statut → **phase 3 livrée (streaming)** ; section `app.py` → mentionner le rendu des `AssistantDelta` (bulle live + caret, finalisée markdown via `views.render_stream_bubble`/`finalize_stream`) ; section `views.py` → ajouter ces deux fonctions. Section relations : `mekillm.LLM.stream`. **Lire les fichiers réels d'abord.**
- `ROADMAP.md` : `packages/mekichat` → phases 1-3 livrées ; tableau s01–s23 : **s13 (streaming)** `packages/` → ✅ ; retirer le todo « mekichat phase 3 » ; ajuster la phrase d'avancement (≈ 3 / 23).

- [ ] **Step 4 : Commit**

```bash
git add docs/wiki-packages/mekichat.md ROADMAP.md
git commit -m "doc: mekichat phase 3 livree (streaming) — wiki-packages + ROADMAP"
```

---

## Self-review (rempli pendant l'écriture)

**Couverture du spec (phase 3) :** `LLM.stream` + réassemblage → Task 1 ✅ ; `AssistantDelta` → Task 2 ✅ ; `run_agent(stream=True)` → Task 2 ✅ ; rendu front live + caret + finalisation markdown → Task 3 ✅ ; REPL inchangé (non-streaming) → Task 2 (note) ✅ ; vérif flux visible → Task 4 ✅. Outils en streaming : `run_agent` réassemble les `tool_calls` via `_consume_stream` puis suit le même chemin outils → couvert (test `test_consume_stream_tool_call`).

**Placeholders :** aucun. `usage=0` en streaming est une limitation **assumée et documentée** (pas de `stream_options`), pas un placeholder.

**Cohérence des types/noms :** `_consume_stream(chunks)` (générateur → return `LLMResponse`) ; `LLM.stream(...)` (`yield from _consume_stream`) ; `AssistantDelta(text)` ; `run_agent(..., *, stream=False)` ; `views.render_stream_bubble() -> (body, lbl)` / `views.finalize_stream(body, text)` ; `stream_ref={"body","lbl","text"}`. Cohérents entre client.py, base.py, app.py, views.py et les tests.

**Risques :** (1) `out = yield from _consume_stream(...)` capture bien la valeur de return (Python 3.3+) — couvert par les tests `_drain`. (2) Le modèle OpenRouter doit accepter `stream=True` ; sinon erreur gérée (RunError → bulle) + tests réseau-free comme filet. (3) Un token par `run.io_bound(next, gen)` = un aller-retour thread/UI par token : acceptable en local ; si saccadé, on pourra batcher (hors périmètre). (4) Finalisation de la bulle partielle sur `RunError` pour ne pas laisser un caret clignotant.
