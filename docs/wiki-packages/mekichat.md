# `packages/mekichat/` — front web (NiceGUI)

Interface web in-process pour dialoguer avec l'agent, construite avec [NiceGUI](https://nicegui.io).
Mode conversation type « Discord » : historique scrollable, bulle par message, saisie en bas.
Pensé comme la couche présentation de [mekicore](mekicore.md), dont il sera le front visuel dès la phase 2.

> Numéros de ligne indicatifs (source = vérité).

## Vue des fichiers et de leurs relations

```
app.py      ── page NiceGUI "/" ──▶ importe views.py (render_message, build_ui)
   │            bootstrap sys.path, charge .env
   │            lit/écrit les sessions via ─┐
   ▼                                        │
sessions.py ── load_session(), save_session(), new_session_id()
   │            JSON sous .sessions/<id>.json (à la racine du projet)
   │
static/
   └── mekichat.css  ── thème cyberpunk Phosphore (variables CSS, bulles, barre de saisie)
views.py    ── render_message(role, text)  helper de rendu NiceGUI par rôle
               build_ui(session_id)        construit la page (historique + saisie)
```

## `sessions.py` — persistance JSON

- `new_session_id() -> str` : génère un identifiant horodaté (`session-YYYYMMDD-HHMMSS`).
- `load_session(session_id, sessions_dir) -> list[dict]` : lit `.sessions/<id>.json` ;
  renvoie `[]` si le fichier n'existe pas encore.
- `save_session(session_id, messages, sessions_dir) -> None` : écrit (ou écrase) le fichier
  JSON correspondant ; crée le répertoire si nécessaire.
- Les sessions sont des listes de dicts `{"role": "user"|"assistant", "content": "..."}`,
  format compatible OpenAI — prêtes à être passées à `mekillm.LLM.complete()` (phase 2).

## `static/mekichat.css` — thème Phosphore

Variables CSS centralisées (`--phosphore-*`) : fond sombre, accent vert phosphorescente,
typographie monospace. Stylise les bulles de messages (`.msg-user` / `.msg-assistant`),
la barre de saisie, le conteneur de l'historique.

## `views.py` — helpers de rendu

- `render_message(role, text)` : émet un élément NiceGUI (`ui.chat_message` ou équivalent)
  avec la classe CSS appropriée selon le rôle.
- `build_ui(session_id)` : construit la page complète (historique chargé depuis `sessions.py`,
  barre de saisie, bouton envoi).

## `app.py` — page NiceGUI

- Bootstrap `sys.path` (identique à mekicore) pour résoudre `import mekichat.*` sans packaging.
- Charge `.env` via `python-dotenv` (même fichier racine que mekicore/mekillm).
- Déclare la route `"/"` NiceGUI, instancie une session, délègue à `build_ui`.
- Démarre le serveur : `ui.run(port=8080)` → **http://localhost:8080**.

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
