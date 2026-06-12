# mekichat — Phase 1 (sessions + UI statique) — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer la phase 1 de `packages/mekichat/` : un front NiceGUI au thème cyberpunk « Phosphore » qui crée, liste, charge et bascule des sessions de conversation persistées sur disque — **sans LLM** (l'envoi d'un message ajoute le message utilisateur et persiste, pas de réponse d'agent).

**Architecture:** Paquet Python autonome `packages/mekichat/`. Logique de persistance pure (`sessions.py`, testable sans réseau ni NiceGUI) + UI NiceGUI (`app.py` + helpers `views.py`) qui réutilise la feuille CSS de la maquette validée. Données runtime dans `.sessions/` à la racine (comme `.logs/`).

**Tech Stack:** Python 3, NiceGUI (web, in-process), dataclasses + JSON pour la persistance. Tests : assertions simples + `main()` (convention `tests/smoke_packages.py`), lancés par `python tests/smoke_mekichat.py`.

**Référence design :** [`docs/superpowers/specs/2026-06-12-front-chat-design.md`](../specs/2026-06-12-front-chat-design.md) · Maquette : [`docs/superpowers/specs/2026-06-12-mekichat-mockup.html`](../specs/2026-06-12-mekichat-mockup.html)

---

## Périmètre (phase 1 uniquement)

**Dans la phase 1 :** persistance des sessions, UI Phosphore (barre latérale + en-tête + fil + composer), nouvelle session, bascule de session, switch de palette, horloge live, envoi qui ajoute le message user et persiste.

**Hors phase 1 (phases 2-3) :** appel LLM, `run_agent`/événements, blocs `[bash]`, streaming, `LLM.stream`. Ne rien implémenter de tout ça ici.

## Structure des fichiers

| Fichier | Responsabilité | Testé |
|---------|----------------|-------|
| `packages/mekichat/__init__.py` | exports du paquet | — |
| `packages/mekichat/sessions.py` | `Session`, `SessionMeta`, `SessionStore` (persistance JSON) — **pur Python** | `tests/smoke_mekichat.py` |
| `packages/mekichat/static/mekichat.css` | feuille de style Phosphore (portée de la maquette) | visuel |
| `packages/mekichat/views.py` | helpers de rendu NiceGUI (un message, un item de session) | visuel |
| `packages/mekichat/app.py` | page NiceGUI : layout, câblage, états, entrée `ui.run` | visuel |
| `tests/smoke_mekichat.py` | smoke réseau-free du `SessionStore` | — |
| `requirements.txt` | + `nicegui` | — |
| `.gitignore` | + `.sessions/` | — |

**Contrainte clé :** `sessions.py` **ne doit jamais importer NiceGUI** (il reste testable seul, sans la dépendance). Seuls `app.py`/`views.py` importent `nicegui`.

---

### Task 1 : `SessionStore` — persistance pure (TDD)

**Files:**
- Create: `packages/mekichat/sessions.py`
- Create: `packages/mekichat/__init__.py`
- Test: `tests/smoke_mekichat.py`

- [ ] **Step 1 : Écrire le test smoke qui échoue**

Create `tests/smoke_mekichat.py` :

```python
"""smoke_mekichat.py — non-régression réseau-free de packages/mekichat/.

Aucune dépendance réseau, clé API ni NiceGUI : on ne teste que la persistance pure.
Lancer depuis la racine : python tests/smoke_mekichat.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "mekichat"))  # import sessions

import sessions as S  # noqa: E402


def test_create_and_load():
    with tempfile.TemporaryDirectory() as d:
        store = S.SessionStore(d)
        s = store.create(model="gpt-4o-mini", system="sys prompt")
        assert s.id
        assert s.messages[0] == {"role": "system", "content": "sys prompt"}
        loaded = store.load(s.id)
        assert loaded.id == s.id
        assert loaded.model == "gpt-4o-mini"
        assert loaded.messages == s.messages


def test_title_set_from_first_user_message():
    with tempfile.TemporaryDirectory() as d:
        store = S.SessionStore(d)
        s = store.create(model="m")
        assert s.title == S._DEFAULT_TITLE
        s.add("user", "Liste les fichiers .py\net compte les lignes")
        assert s.title == "Liste les fichiers .py"      # 1re ligne, tronquée
        s.add("user", "deuxième")
        assert s.title == "Liste les fichiers .py"      # ne change plus ensuite


def test_round_trip_messages():
    with tempfile.TemporaryDirectory() as d:
        store = S.SessionStore(d)
        s = store.create(model="m")
        s.add("user", "salut")
        s.add("assistant", "bonjour")
        store.save(s)
        loaded = store.load(s.id)
        assert [m["content"] for m in loaded.messages] == ["salut", "bonjour"]


def test_list_sorted_recent_first():
    with tempfile.TemporaryDirectory() as d:
        store = S.SessionStore(d)
        a = store.create(model="m")
        a.created_at = "2026-01-01T00:00:00+00:00"; store.save(a)
        b = store.create(model="m")
        b.created_at = "2026-06-01T00:00:00+00:00"; store.save(b)
        metas = store.list()
        assert [m.id for m in metas] == [b.id, a.id]
        assert metas[0].n_messages == len(b.messages)


def test_list_ignores_bad_files():
    with tempfile.TemporaryDirectory() as d:
        store = S.SessionStore(d)
        store.create(model="m")
        (Path(d) / "junk.json").write_text("{not json", encoding="utf-8")
        assert len(store.list()) == 1   # le fichier corrompu est ignoré, pas de crash


def main():
    test_create_and_load()
    test_title_set_from_first_user_message()
    test_round_trip_messages()
    test_list_sorted_recent_first()
    test_list_ignores_bad_files()
    print("OK - smoke mekichat passe")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2 : Lancer le test, vérifier qu'il échoue**

Run: `python tests/smoke_mekichat.py`
Expected: `ModuleNotFoundError: No module named 'sessions'` (le fichier n'existe pas encore).

- [ ] **Step 3 : Écrire `packages/mekichat/sessions.py`**

```python
"""sessions.py — sessions persistées de mekichat (un fichier JSON par session).

Pur Python : aucune dépendance NiceGUI ni réseau → testable seul.
Données runtime à la RACINE du projet (.sessions/), jamais dans packages/.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# parents[2] = racine, depuis packages/mekichat/sessions.py. Surchargeable par env.
_DEFAULT_DIR = Path(__file__).resolve().parents[2] / ".sessions"
_DEFAULT_TITLE = "(nouvelle session)"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Session:
    id: str
    title: str
    model: str
    created_at: str
    messages: list = field(default_factory=list)

    def add(self, role: str, content: str, **extra) -> dict:
        """Ajoute un message ; renseigne le titre au 1er message utilisateur."""
        msg = {"role": role, "content": content, **extra}
        self.messages.append(msg)
        if role == "user" and self.title == _DEFAULT_TITLE:
            first_line = (content.strip().splitlines() or [""])[0]
            self.title = first_line[:48] or _DEFAULT_TITLE
        return msg


@dataclass
class SessionMeta:
    """Vue légère pour la barre latérale (sans charger tout l'historique)."""
    id: str
    title: str
    model: str
    created_at: str
    n_messages: int


class SessionStore:
    """CRUD : un fichier <id>.json par session sous le dossier runtime."""

    def __init__(self, directory: str | Path | None = None):
        raw = directory or os.environ.get("MEKICHAT_SESSIONS_DIR") or _DEFAULT_DIR
        self.dir = Path(raw)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self.dir / f"{session_id}.json"

    def create(self, model: str, system: str | None = None) -> Session:
        s = Session(id=uuid.uuid4().hex[:6], title=_DEFAULT_TITLE, model=model, created_at=_now_iso())
        if system:
            s.messages.append({"role": "system", "content": system})
        self.save(s)
        return s

    def save(self, session: Session) -> None:
        self._path(session.id).write_text(
            json.dumps(asdict(session), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def load(self, session_id: str) -> Session:
        data = json.loads(self._path(session_id).read_text(encoding="utf-8"))
        return Session(**data)

    def list(self) -> list[SessionMeta]:
        metas: list[SessionMeta] = []
        for p in self.dir.glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue   # fichier corrompu/illisible : on l'ignore
            metas.append(SessionMeta(
                id=d["id"], title=d.get("title", _DEFAULT_TITLE), model=d.get("model", "?"),
                created_at=d.get("created_at", ""), n_messages=len(d.get("messages", [])),
            ))
        metas.sort(key=lambda m: m.created_at, reverse=True)
        return metas
```

Create `packages/mekichat/__init__.py` :

```python
"""mekichat — front web (NiceGUI) du harness packages/.

Phase 1 : sessions persistées + UI statique. La logique de persistance
(sessions.py) est importable seule, sans NiceGUI.
"""
from .sessions import Session, SessionMeta, SessionStore

__all__ = ["Session", "SessionMeta", "SessionStore"]
```

- [ ] **Step 4 : Lancer le test, vérifier qu'il passe**

Run: `python tests/smoke_mekichat.py`
Expected: `OK - smoke mekichat passe`

- [ ] **Step 5 : `py_compile` puis commit**

```bash
python -m py_compile packages/mekichat/sessions.py packages/mekichat/__init__.py tests/smoke_mekichat.py
git add packages/mekichat/sessions.py packages/mekichat/__init__.py tests/smoke_mekichat.py
git commit -m "mekichat: SessionStore (persistance JSON des sessions) + smoke"
```

---

### Task 2 : feuille de style Phosphore

**Files:**
- Create: `packages/mekichat/static/mekichat.css`

- [ ] **Step 1 : Porter le CSS de la maquette**

Copier le **contenu du bloc `<style>…</style>`** de `docs/superpowers/specs/2026-06-12-mekichat-mockup.html`
dans `packages/mekichat/static/mekichat.css`, avec ces **seules adaptations** :

1. Mettre la **palette Phosphore par défaut** dans `:root` (pour ne pas dépendre d'un attribut initial) :
   remplacer le bloc `--p1:#00e5ff; --p2:#ff2a3d; --warn:#ff8a00;` de `:root` par
   `--p1:#39ff14; --p2:#ff2bd6; --warn:#f7ff12;` et `--bg:#05060c;` par `--bg:#050a06;`.
2. **Conserver** les 4 blocs `body[data-theme="…"]` tels quels (ils servent au switch de palette).
3. Ne pas copier les balises `<style>`/`</style>` ni le reste du HTML — uniquement les règles CSS.
4. Ajouter en fin de fichier ce **reset des conteneurs NiceGUI** (NiceGUI insère un conteneur `.nicegui-content` avec padding/gap qu'il faut neutraliser) :

```css
/* neutralise le conteneur par défaut de NiceGUI pour reprendre la pleine page */
.nicegui-content { padding: 0 !important; gap: 0 !important; max-width: none !important; }
.q-page, .q-layout { min-height: 0 !important; }
```

- [ ] **Step 2 : Vérifier la syntaxe (pas de test auto)**

Ouvrir `packages/mekichat/static/mekichat.css` et vérifier visuellement que le `:root` commence bien par
la palette phosphore et que les 4 blocs `body[data-theme]` sont présents.

- [ ] **Step 3 : Commit**

```bash
git add packages/mekichat/static/mekichat.css
git commit -m "mekichat: feuille de style Phosphore (portee de la maquette)"
```

---

### Task 3 : helpers de rendu `views.py`

**Files:**
- Create: `packages/mekichat/views.py`

- [ ] **Step 1 : Écrire `views.py`**

Fonctions qui construisent les éléments NiceGUI correspondant aux classes CSS de la maquette. On
utilise `ui.element('div')` (et balises sémantiques) pour garder le contrôle total du markup.

```python
"""views.py — helpers de rendu NiceGUI (mappés sur les classes CSS de la maquette)."""
from __future__ import annotations

from nicegui import ui

_AVATARS = {"user": ("user", "CD"), "assistant": ("bot", "M"), "tool": ("bot", "M")}
_WHO = {"user": "charles", "assistant": "mekicore", "tool": "mekicore"}
_TAG = {"user": "//USER", "assistant": "//AGENT", "tool": "//TOOL"}


def render_message(msg: dict) -> None:
    """Affiche une ligne de message (avatar + en-tête + corps), façon Discord."""
    role = msg.get("role", "assistant")
    if role == "system":
        return  # le prompt système n'est pas affiché dans le fil
    kind, initials = _AVATARS.get(role, ("bot", "M"))
    with ui.element("div").classes(f"msg {kind}"):
        ui.element("div").classes(f"avatar {kind}").style("").props("").add_slot  # placeholder remplacé ci-dessous
```

> Note d'implémentation : `ui.element('div')` n'a pas de texte par défaut. Pour mettre du texte dans un
> conteneur stylé, imbriquer un `ui.label(...)` ou utiliser `ui.html(...)`. Version concrète complète :

```python
"""views.py — helpers de rendu NiceGUI (mappés sur les classes CSS de la maquette)."""
from __future__ import annotations

from nicegui import ui

_AVATARS = {"user": ("user", "CD"), "assistant": ("bot", "M")}
_WHO = {"user": "charles", "assistant": "mekicore"}
_TAG = {"user": "//USER", "assistant": "//AGENT"}


def render_message(msg: dict) -> None:
    """Affiche une ligne de message (avatar + en-tête + corps), façon Discord."""
    role = msg.get("role", "assistant")
    if role not in ("user", "assistant"):
        return  # system / tool non affichés en phase 1
    kind, initials = _AVATARS[role]
    with ui.element("div").classes(f"msg {kind}"):
        with ui.element("div").classes(f"avatar {kind}"):
            ui.label(initials)
        with ui.element("div"):
            with ui.element("div").classes("head"):
                ui.label(_WHO[role]).classes("who")
                ui.label(_TAG[role]).classes("tag")
            with ui.element("div").classes("body"):
                ui.label(msg.get("content", ""))


def render_session_item(meta, *, active: bool, on_click) -> None:
    """Affiche un item de la barre latérale (titre + id + nb msg)."""
    classes = "session active" if active else "session"
    with ui.element("div").classes(classes).on("click", on_click):
        with ui.element("div").classes("s-title"):
            ui.label(">_").classes("mk")
            ui.label(meta.title)
        ui.label(f"{meta.id} · {meta.n_messages} msg").classes("s-meta")
```

- [ ] **Step 2 : `py_compile`**

Run: `python -m py_compile packages/mekichat/views.py`
Expected: pas d'erreur.

- [ ] **Step 3 : Commit**

```bash
git add packages/mekichat/views.py
git commit -m "mekichat: helpers de rendu NiceGUI (message, item de session)"
```

---

### Task 4 : page NiceGUI `app.py`

**Files:**
- Create: `packages/mekichat/app.py`

- [ ] **Step 1 : Écrire `app.py`**

```python
#!/usr/bin/env python3
"""app.py — front mekichat (NiceGUI). Phase 1 : sessions + UI statique (sans LLM)."""
from __future__ import annotations

import sys
from pathlib import Path

# Lancement direct : rend `import sessions, views` résoluble (comme mekicore/main.py).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nicegui import ui  # noqa: E402

import sessions as sessions_mod  # noqa: E402
import views  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
DEFAULT_MODEL = "gpt-4o-mini"
FONTS = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Chakra+Petch:wght@400;500;600;700&family=Share+Tech+Mono&display=swap" rel="stylesheet">'
)
PALETTES = [("phosphor", "PHOSPHORE"), ("blade", "BLADE RUNNER"),
            ("orange", "ORANGE/TEAL"), ("acid", "ACIDE")]

store = sessions_mod.SessionStore()


def _ensure_current() -> sessions_mod.Session:
    """Charge la session la plus récente, ou en crée une."""
    metas = store.list()
    return store.load(metas[0].id) if metas else store.create(model=DEFAULT_MODEL)


@ui.page("/")
def index() -> None:
    ui.add_head_html(FONTS)
    ui.add_css((STATIC / "mekichat.css").read_text(encoding="utf-8"))
    ui.query("body").props('data-theme=phosphor')

    current = _ensure_current()

    def switch_theme(key: str) -> None:
        ui.run_javascript(f"document.body.setAttribute('data-theme','{key}')")

    def open_session(session_id: str) -> None:
        nonlocal current
        current = store.load(session_id)
        _refresh()

    def new_session() -> None:
        nonlocal current
        current = store.create(model=DEFAULT_MODEL)
        _refresh()

    def send(text: str) -> None:
        text = text.strip()
        if not text:
            return
        current.add("user", text)         # phase 1 : pas de réponse LLM
        store.save(current)
        _refresh()

    # ---- barre d'outils palettes ----
    with ui.element("div").classes("toolbar"):
        ui.label("PALETTE //").classes("lbl")
        for key, label in PALETTES:
            ui.button(label, on_click=lambda _, k=key: switch_theme(k)).props("flat no-caps").classes("sw")
        ui.element("div").classes("spacer")
        ui.label("phase 1 · UI statique").classes("meta")

    # ---- coquille principale (grille latérale + main) ----
    app_root = ui.element("div").classes("app")
    with app_root:
        sidebar = ui.element("aside").classes("sidebar")
        main = ui.element("section").classes("main")

    def _refresh() -> None:
        """Reconstruit barre latérale + zone principale pour la session courante."""
        sidebar.clear()
        main.clear()
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

        with main:
            # en-tête
            with ui.element("header").classes("topbar"):
                with ui.element("div").classes("channel"):
                    ui.label("[#]").classes("br")
                    ui.label("conversation").classes("")  # h1 via CSS sur .channel h1 — voir note
                    ui.label(f"// {current.title}").classes("sub")
                with ui.element("div").classes("chips"):
                    _chip("MODEL", current.model, "model")
                    _chip("SID", current.id, "sid")
                    _chip("TOK", "0↑ 0↓", "")          # placeholder phase 1
                    clock = _chip("⌚", "--:--:--", "")
            ui.timer(1.0, lambda: clock.set_text(_now_hms()))
            # fil
            with ui.element("div").classes("thread"):
                with ui.element("div").classes("thread-inner"):
                    for msg in current.messages:
                        views.render_message(msg)
            # composer
            with ui.element("div").classes("composer"):
                with ui.element("div").classes("composer-inner"):
                    with ui.element("div").classes("input-wrap"):
                        box = ui.textarea(placeholder="// message à mekicore (phase 1 : pas encore de réponse)")
                        box.props("borderless autogrow").classes("ta")
                        ui.button("▸", on_click=lambda _: (send(box.value), box.set_value(""))).props("flat").classes("send")

    _refresh()


def _now_hms() -> str:
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S")


def _chip(key: str, value: str, extra: str):
    with ui.element("div").classes(f"chip {extra}"):
        ui.label(key).classes("k")
        lbl = ui.label(value)
    return lbl


if __name__ in {"__main__", "__mp_main__"}:   # garde requise par NiceGUI (reload/multiprocessing)
    ui.run(title="mekichat", port=8080, dark=True, reload=False, show=True)
```

> **Notes d'implémentation NiceGUI (à ajuster en lançant) :**
> - Le titre `conversation` doit apparaître via `.channel h1` : remplacer `ui.label("conversation")` par
>   `ui.html('<h1>conversation</h1>')` si le sélecteur CSS cible `h1`. Vérifier au rendu.
> - `_chip` renvoie le `ui.label` de valeur pour pouvoir mettre à jour l'horloge (`clock.set_text`).
> - Si NiceGUI ajoute des marges/paddings parasites, le reset `.nicegui-content` (Task 2) doit les
>   neutraliser ; sinon ajouter les sélecteurs Quasar manquants dans le CSS.

- [ ] **Step 2 : `py_compile`**

Run: `python -m py_compile packages/mekichat/app.py`
Expected: pas d'erreur.

- [ ] **Step 3 : Lancer l'app et vérifier visuellement**

Run: `python packages/mekichat/app.py`
Ouvrir `http://localhost:8080`. Vérifier (comparer à la maquette `…-mockup.html`) :
- thème Phosphore par défaut ; le toolbar bascule bien les 4 palettes ;
- barre latérale : marque `MEKICHAT` (glitch), bouton *nouvelle session*, liste des sessions ;
- en-tête : `MODEL`, `SID`, `TOK`, horloge qui avance ;
- fil : les messages de la session s'affichent (vide si nouvelle) ;
- composer : taper un texte + ▸ → le message apparaît, le titre de session se met à jour, et un
  fichier `.sessions/<id>.json` est créé/à jour à la racine ;
- cliquer une autre session dans la barre latérale la charge.

Ajuster les classes/markup NiceGUI jusqu'à correspondance raisonnable avec la maquette.

- [ ] **Step 4 : Commit**

```bash
git add packages/mekichat/app.py
git commit -m "mekichat: page NiceGUI phase 1 (sidebar + header + fil + composer, sans LLM)"
```

---

### Task 5 : dépendance, gitignore, lanceur, doc

**Files:**
- Modify: `requirements.txt`
- Modify: `.gitignore`
- Create: `start-chat.ps1`
- Modify: `docs/wiki-packages/` (doc manuelle de `packages/`) et `ROADMAP.md`

- [ ] **Step 1 : Ajouter NiceGUI aux dépendances**

Modifier `requirements.txt`, ajouter après la ligne `openai>=1.0 …` :

```
nicegui>=2.0            # front web in-process de packages/mekichat (UI en Python)
```

- [ ] **Step 2 : Installer et vérifier l'import**

Run: `pip install -r requirements.txt`
Run: `python -c "import nicegui; print(nicegui.__version__)"`
Expected: une version s'affiche sans erreur.

- [ ] **Step 3 : Ignorer les données runtime des sessions**

Modifier `.gitignore`, ajouter sous le bloc `.logs/` :

```
# Sessions de mekichat (générées à l'exécution, à la racine)
.sessions/
```

- [ ] **Step 4 : Lanceur PowerShell**

Create `start-chat.ps1` :

```powershell
# start-chat.ps1 - lance le front web mekichat (NiceGUI).
# Usage : .\start-chat.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot   # racine du projet (pour trouver .env et .sessions/)
python packages/mekichat/app.py
```

- [ ] **Step 5 : Re-vérifier la non-régression globale**

Run: `python tests/smoke_packages.py`
Expected: `OK - tous les smoke tests passent` (rien de `packages/` existant n'a été touché).
Run: `python tests/smoke_mekichat.py`
Expected: `OK - smoke mekichat passe`

- [ ] **Step 6 : Mettre à jour la doc manuelle de `packages/` et la ROADMAP**

- Dans `docs/wiki-packages/` : ajouter une page/section `mekichat` décrivant le paquet (rôle, lancement
  `python packages/mekichat/app.py`, `sessions.py`/`app.py`/`views.py`, thème Phosphore, statut phase 1).
- Dans `ROADMAP.md` : noter `packages/mekichat/` (front NiceGUI) comme **phase 1 livrée** (sessions +
  UI statique ; phases 2-3 = chat/outils puis streaming à venir).

- [ ] **Step 7 : Commit**

```bash
git add requirements.txt .gitignore start-chat.ps1 docs/wiki-packages ROADMAP.md
git commit -m "mekichat: dependance nicegui, gitignore .sessions, lanceur start-chat, doc"
```

---

## Self-review (rempli pendant l'écriture)

**Couverture du spec (phase 1) :**
- Persistance sessions → Task 1 ✅ · UI Phosphore → Tasks 2-4 ✅ · multi-sessions (liste/nouvelle/bascule)
  → Task 4 ✅ · en-tête modèle/SID/horloge → Task 4 ✅ · switch palettes → Task 4 ✅ · `.sessions/`
  gitignoré + dépendance + lanceur + doc → Task 5 ✅.
- Hors phase 1 (LLM, `run_agent`, blocs bash, streaming) : volontairement absents (phases 2-3).

**Placeholders :** le `TOK 0↑ 0↓` de l'en-tête est un **affichage** volontaire (les tokens viennent du
LLM, phase 2), pas un placeholder de plan. Tout le code logique est complet. Le premier brouillon de
`render_message` dans Task 3 est explicitement remplacé par la version complète juste en dessous.

**Cohérence des types/noms :** `SessionStore.create/save/load/list`, `Session.add`, `SessionMeta(id,
title, model, created_at, n_messages)`, `views.render_message(msg)` / `views.render_session_item(meta,
active, on_click)` — utilisés de façon cohérente entre `sessions.py`, `views.py`, `app.py` et les tests.

**Risque NiceGUI :** la fidélité visuelle exacte dépend de quelques détails Quasar (reset des
conteneurs, `h1` du titre). Le reset CSS (Task 2) + les notes d'implémentation (Task 4) le couvrent ;
vérification visuelle à l'étape 3 de Task 4.
