# `packages/mekichat/` — front web (NiceGUI)

Interface web in-process pour dialoguer avec l'agent, construite avec [NiceGUI](https://nicegui.io).
Mode conversation type « Discord » : historique scrollable, bulle par message, saisie en bas.
Pensé comme la couche présentation de [mekicore](mekicore.md), dont il sera le front visuel dès la phase 2.

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

Variables CSS centralisées (`--phosphore-*`) : fond sombre, accent vert phosphorescente,
typographie monospace. Stylise les bulles de messages (`.msg-user` / `.msg-assistant`),
la barre de saisie, le conteneur de l'historique.

## `views.py` — helpers de rendu (deux fonctions)

- `render_message(msg)` : affiche une **ligne de message** façon Discord (avatar + en-tête +
  corps), d'après `msg["role"]` ; les rôles `system` / `tool` ne sont pas affichés en phase 1.
- `render_session_item(meta, *, active, on_click)` : affiche un **item de la barre latérale**
  (titre + id + nombre de messages), marqué `active` pour la session courante.

## `app.py` — page NiceGUI

- Bootstrap `sys.path` (comme mekicore) pour résoudre `import sessions, views` en lancement direct.
- `@ui.page("/")` → `index()` : la page. L'UI (barre latérale, en-tête, fil, composer) est
  (re)construite par la closure interne `_refresh()` à chaque action (ouvrir, créer, envoyer).
- Le store est obtenu via `_get_store()` (singleton **paresseux** : évite de créer `.sessions/`
  au simple import du module).
- Démarre le serveur : `ui.run(... port=8080)` → **http://localhost:8080**.

## Lancer

```
python packages/mekichat/app.py     # ou .\start-chat.ps1 (depuis la racine)
```

Le serveur démarre sur **http://localhost:8080**. Pas de clé API nécessaire en phase 1
(UI statique, pas encore connectée au LLM).

## Statut

**Phase 1 livrée** : persistance des sessions JSON + UI statique (thème Phosphore, bulles, saisie).
Pas encore de LLM branché.

Phases suivantes :
- **Phase 2** — câblage LLM (appel `mekillm.LLM.complete`, outils, affichage des réponses en direct).
- **Phase 3** — streaming token par token (SSE / `ui.notify` progressif).

## Relations entrantes / sortantes

- Dépend de [mekillm](mekillm.md) (à venir en phase 2 : `LLM.complete`).
- Pendant de [mekicore](mekicore.md) (même agent, interface web au lieu du REPL terminal).
- Non-régression réseau-free : `tests/smoke_mekichat.py`.
