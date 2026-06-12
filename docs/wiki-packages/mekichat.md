# `packages/mekichat/` — front web (NiceGUI)

Interface web in-process pour dialoguer avec l'agent, construite avec [NiceGUI](https://nicegui.io).
Mode conversation type « Discord » : historique scrollable, bulle par message, saisie en bas.
Couche présentation de [mekicore](mekicore.md) : son front visuel (l'agent + l'outil `bash`), à la place du REPL terminal.

> Numéros de ligne indicatifs (source = vérité).

## Vue des fichiers et de leurs relations

```
app.py      ── page NiceGUI "/" (index) ; closure _refresh() (re)construit l'UI
   │            bootstrap sys.path → import sessions, views
   │            store paresseux _get_store() ──▶ SessionStore
   │            rend chaque message/item via ──▶ views.render_message / render_session_item
   ▼
sessions.py ── Session, SessionMeta (dataclasses) + SessionStore (CRUD)
   │            JSON sous .sessions/<id>.json (à la racine du projet) ; pur Python, pas de NiceGUI
   │
views.py    ── render_message(msg)                 ligne de message façon Discord
   │            render_session_item(meta, …)        item de la barre latérale
   │
static/
   └── mekichat.css  ── thème cyberpunk Phosphore (variables CSS, bulles, barre de saisie)
```

## `sessions.py` — persistance JSON (pur Python, sans NiceGUI)

- `Session` (dataclass) : `id`, `title`, `model`, `created_at`, `messages` (liste de dicts).
  - `add(role, content, **extra) -> dict` : ajoute le message (dict `{"role", "content", **extra}`,
    format compatible OpenAI) ; au **premier message `user`**, renseigne `title` à partir de sa
    première ligne, tronquée à 48 caractères.
- `SessionMeta` (dataclass) : `id`, `title`, `model`, `created_at`, `n_messages` — vue légère
  pour la barre latérale (sans charger tout l'historique).
- `SessionStore(directory=None)` : CRUD, un fichier `<id>.json` par session. Le dossier est
  résolu depuis l'argument, sinon `MEKICHAT_SESSIONS_DIR`, sinon `.sessions/` à la racine du projet.
  - `create(model, system=None) -> Session` : génère un id court, sème éventuellement un message
    `system`, sauvegarde et renvoie la session.
  - `save(session) -> None` : écrit `.sessions/<id>.json`.
  - `load(session_id) -> Session` : relit le fichier JSON correspondant.
  - `list() -> list[SessionMeta]` : métadonnées, **plus récentes d'abord** ; ignore les fichiers
    corrompus / structurellement incomplets.

## `static/mekichat.css` — thème Phosphore

Palette pilotée par variables CSS (`--p1` vert phosphore, `--p2` magenta, `--warn` jaune) et
commutable via l'attribut `[data-theme]` (phosphor / blade / orange / acid). Look cyberpunk :
coins biseautés (`clip-path`), glitch, scanlines, ticker HUD. Stylise les lignes de messages
(`.msg.user` / `.msg.bot`), le bloc outil (`.tool`), la barre de saisie (`.input-wrap`) et le fil
(`.thread`).

## `views.py` — helpers de rendu

- `render_message(msg)` : une **ligne de message** façon Discord. Les réponses **assistant** sont
  rendues en **markdown** (`ui.markdown` : titres dégressifs h1-h3, listes, code, retours-ligne) ;
  les messages **user** en texte brut (retours-ligne préservés, pas de markdown).
- `render_session_item(meta, *, active, on_click)` : un **item de la barre latérale**.
- `render_tool(command, output, status)` : un **bloc `[bash]`** (commande + sortie + statut) ;
  renvoie `(label_statut, label_sortie)` pour remplissage différé.
- `fill_tool(handle, output, ok)` : remplit un bloc `[bash]` créé en statut `RUN` (chemin live).
- `render_thinking()` : l'indicateur animé **« PROCESSING… »** pendant un appel LLM (renvoie
  l'élément, supprimé via `.delete()` à la réponse).
- `render_thread(messages)` : rejoue tout un historique (texte + blocs `[bash]` appariés
  `tool_calls` ↔ messages `role:"tool"`) — chemin de rechargement de session.

## `app.py` — page NiceGUI

- Bootstrap `sys.path` pour résoudre `import sessions, views` **et** `mekillm` / `base` / `tools` /
  `events` en lancement direct.
- `@ui.page("/")` → `index()` : la page. L'UI (barre latérale, en-tête, fil, composer) est
  (re)construite par la closure `_refresh()` ; le fil d'une session rechargée est rejoué par
  `views.render_thread`.
- **Envoi** (`send`, async) : ajoute le message user, persiste, puis pilote `base.run_agent`
  **pas-à-pas** via `await run.io_bound(next, gen, _DONE)` (sans figer l'UI). Rend en direct :
  `ThinkingStarted` → « PROCESSING… », `AssistantDone` → bulle, `ToolStarted`/`ToolFinished` →
  bloc `[bash]`, `RunError` → bulle rouge. Persiste à la fin.
- `state["busy"]` empêche envois/bascules concurrents ; le rendu cesse proprement si l'onglet se
  ferme en plein run (garde « client supprimé »).
- Store et LLM en singletons **paresseux** (`_get_store` / `_get_llm`).
- Démarre le serveur : `ui.run(... port=8080)` → **http://localhost:8080**.

## Lancer

```
python packages/mekichat/app.py     # ou .\start-chat.ps1 (depuis la racine)
```

Le serveur démarre sur **http://localhost:8080**. Nécessite une clé `OPENROUTER_API_KEY` dans
`.env` (l'agent appelle le LLM) ; le modèle est celui résolu par mekillm (`MEKILLM_MODEL`). Sans
clé valide, l'envoi affiche une bulle d'erreur « LLM indisponible » (dégradation propre).

## Statut

**Phases 1 et 2 livrées.**
- Phase 1 : persistance des sessions JSON + UI statique (thème Phosphore).
- Phase 2 : chat branché sur l'agent — `mekillm.LLM.complete` via `base.run_agent` à événements,
  outil `bash` exécuté et affiché en blocs `[bash]`, indicateur « PROCESSING… », gestion d'erreur
  (bulle rouge), persistance par tour. **Non-streaming.**

Phase suivante :
- **Phase 3** — streaming token par token (`LLM.stream`, `AssistantDelta`, caret).

> Rendu **markdown** des réponses de l'agent (titres de tailles dégressives, listes, blocs de code,
> retours-ligne). Les messages utilisateur restent en texte brut.

## Relations entrantes / sortantes

- Dépend de [mekillm](mekillm.md) (`LLM.complete`) et de [mekicore](mekicore.md) (`base.run_agent`,
  `events`, outil `bash`).
- Pendant de [mekicore](mekicore.md) : même agent, interface web au lieu du REPL terminal.
- Non-régression réseau-free : `tests/smoke_mekichat.py` (sessions) + `tests/smoke_packages.py`
  (`run_agent`, événements).
