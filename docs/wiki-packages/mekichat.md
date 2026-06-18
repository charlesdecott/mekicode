# `packages/mekichat/` — front web (NiceGUI)

Interface web in-process pour dialoguer avec l'agent, construite avec [NiceGUI](https://nicegui.io).
Mode conversation type « Discord » : historique scrollable, bulle par message, saisie en bas.
Couche présentation de [mekicore](mekicore.md) : son front visuel (l'agent + ses outils : `bash`,
`read`, `write`, `edit`, `grep`, `glob`), à la place du REPL terminal.

> Numéros de ligne indicatifs (source = vérité).

## Vue des fichiers et de leurs relations

```
app.py      ── page NiceGUI "/" (index) ; closure _refresh() (re)construit l'UI
   │            bootstrap sys.path → import sessions, views
   │            _get_hub() câblé sur dispatch_factory=make_dispatch + registry (ProjectRegistry)
   │            _get_store() ──▶ SessionStore (sessions filtrées par projet+scope)
   │            rend chaque message via ──▶ views.render_message ; sidebar via render_worktree_tree
   │            consomme WorktreeProposed/Created/Rejected via ──▶ views.render_worktree_proposal
   ▼
sessions.py ── shim : ré-exporte Session, SessionMeta, SessionStore depuis mekihub.session
   │
views.py    ── render_message(msg)                   ligne de message façon Discord
   │            render_worktree_tree(…)               sidebar hiérarchique main + worktrees
   │            render_project_selector(…)            sélecteur Projet → scope → session
   │            render_worktree_proposal(event, hub)  carte validation worktree (Approuver/Refuser)
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
  - `delete(session_id) -> None` : supprime le fichier de la session (sans erreur si absent).
  - `list() -> list[SessionMeta]` : métadonnées, **plus récentes d'abord** ; ignore les fichiers
    corrompus / structurellement incomplets.

## `static/mekichat.css` — thème Phosphore

Palette pilotée par variables CSS (`--p1` vert phosphore, `--p2` magenta, `--warn` jaune) et
commutable via l'attribut `[data-theme]` (phosphor / blade / orange / acid). Look cyberpunk :
coins biseautés (`clip-path`), glitch, scanlines, ticker HUD. Stylise les lignes de messages
(`.msg.user` / `.msg.bot`), le bloc outil (`.tool`), la barre de saisie (`.input-wrap`) et le fil
(`.thread`).

## `views.py` — helpers de rendu

- `render_project_selector(registry, store, *, on_select)` : sélecteur **Projet → scope (main |
  worktrees) → session** affiché dans la barre latérale. Bouton « + projet » : ouvre un dialogue
  de saisie de chemin de dépôt, appelle `registry.register(path)`. Sessions filtrées par
  `project_id` et `scope` sélectionnés.
- `render_worktree_proposal(event, hub)` : carte de validation worktree insérée dans le fil lors
  d'un `WorktreeProposed`. Affiche le nom proposé et la branche de base. Boutons **Approuver**
  (`hub.approve_worktree`) et **Refuser** (`hub.reject_worktree`) ; la carte se remplace par un
  bandeau de confirmation ou de refus une fois l'action prise.
- `render_message(msg)` : une **ligne de message** façon Discord. Les réponses **assistant** sont
  rendues en **markdown** (`ui.markdown` : titres dégressifs h1-h3, listes, code, retours-ligne) ;
  les messages **user** en texte brut (retours-ligne préservés, pas de markdown).
- `render_worktree_tree(main_sessions, worktrees, current_sid, …)` : **sidebar hiérarchique** (Design C) — catégorie main + worktrees repliables → sessions.
- `tool_summary(args)` : extrait le **résumé** d'un appel d'outil pour l'affichage (1er de
  `command` / `path` / `pattern`, sinon 1er argument).
- `_render_diff(old, new)` : pour l'outil `edit`, affiche le changement en **diff** — `--- ancien`
  (lignes `-`, rouge) puis `+++ nouveau` (lignes `+`, vert), multi-lignes.
- `tool_metric(name, output)` : **info compacte d'en-tête** (visible surtout quand le bloc est replié) —
  `N lignes` (read/bash), `N car.` (write), `N résultats` (grep), `N fichiers` (glob) ; `edit` →
  `+ajoutées -retirées` (depuis `old`/`new`).
- `render_tool(name, summary, output, status, *, old, new)` : un **bloc d'outil** `<glyphe> <NOM>`
  **coloré par outil** (`_TOOL_GLYPH` : `❯_`/`▤`/`✎`/`±`/`⌕`/`✲` ; couleur via la classe CSS `t-<nom>`),
  **replié par défaut** (clic sur l'en-tête → ouvre/ferme, classe `collapsed` + chevron). En-tête :
  glyphe + NOM + résumé + métrique + statut. Pour `edit`, le corps est le diff (depuis `old`/`new`).
  Renvoie `(label_statut, label_sortie, label_métrique)` pour remplissage différé.
- `fill_tool(handle, output, ok, name)` : remplit un bloc créé en statut `RUN` (statut `DONE`/`ERR`,
  sortie, et **métrique** calculée via `tool_metric`).
- `render_thinking()` : l'indicateur animé **« PROCESSING… »** pendant un appel LLM (renvoie
  l'élément, supprimé via `.delete()` à la réponse).
- `render_thread(messages)` : rejoue tout un historique (texte + blocs d'outils appariés
  `tool_calls` ↔ messages `role:"tool"`, nom + résumé via `tool_summary`) — chemin de rechargement
  de session.
- `render_stream_bubble()` → `(body, lbl)` : bulle assistant en cours de **streaming** (texte brut
  + caret clignotant) ; le label est mis à jour à chaque token.
- `finalize_stream(body, text)` : remplace le texte streamé par le rendu **markdown** final (retire le caret).

## `app.py` — page NiceGUI

- Bootstrap `sys.path` pour résoudre `import sessions, views` **et** `mekillm` / `base` / `tools` /
  `events` en lancement direct.
- `@ui.page("/")` → `index()` : la page. L'UI (barre latérale, en-tête, fil, composer) est
  (re)construite par la closure `_refresh()` ; le fil d'une session rechargée est rejoué par
  `views.render_thread`.
- **Hub multi-projet** : `_get_hub()` (singleton paresseux) construit un `SessionHub` câblé sur
  `dispatch_factory=make_dispatch` (workspace confiné par session) et `registry=ProjectRegistry()`
  (lit `.mekicode/projects.json`). Appelle `registry.ensure_default()` au démarrage.
- **Envoi** (`send`, async) : ajoute le message user, persiste, puis pilote `base.run_agent`
  (en **`stream=True`**) **pas-à-pas** via `await run.io_bound(next, gen, _DONE)` (sans figer l'UI).
  Rend en direct : `ThinkingStarted` → « PROCESSING… », `AssistantDelta` → bulle de **streaming**
  (texte + caret), `AssistantDone` → **finalisation markdown**, `ToolStarted`/`ToolFinished` → bloc
  d'outil **coloré/repliable par outil** (`render_tool`/`fill_tool` ; `old`/`new` pour le diff `edit`),
  `RunError` → bulle rouge (et fige la bulle partielle). Persiste à la fin.
  Sur `WorktreeProposed` → affiche la carte de validation (`views.render_worktree_proposal`).
- `state["busy"]` empêche envois/bascules concurrents ; le rendu cesse proprement si l'onglet se
  ferme en plein run (garde « client supprimé »).
- Store et registre en singletons **paresseux** (`_get_store` / `_get_registry`) ; le LLM est fabriqué par `_llm_factory` (provider réel ou doublure de test).
- **UX** : **Entrée** envoie (Maj+Entrée = nouvelle ligne) ; le fil **scrolle auto** en bas à chaque
  message/token ; chaque session a un **×** (au survol) pour la supprimer dans la barre latérale.
- Démarre le serveur : `ui.run(... port=8080)` → **http://localhost:8080**.

## Lancer

```
python packages/mekichat/app.py     # ou .\start-chat.ps1 (depuis la racine)
```

Le serveur démarre sur **http://localhost:8080**. Nécessite une clé `OPENROUTER_API_KEY` dans
`.env` (l'agent appelle le LLM) ; le modèle est celui résolu par mekillm (`MEKILLM_MODEL`). Sans
clé valide, l'envoi affiche une bulle d'erreur « LLM indisponible » (dégradation propre).

## Statut

**Phases 1, 2 et 3 livrées. Phase 4 (multi-projet + worktree) livrée.**
- Phase 1 : persistance des sessions JSON + UI statique (thème Phosphore).
- Phase 2 : chat branché sur l'agent (`base.run_agent` à événements sur `mekillm.LLM.complete`),
  outil `bash` en blocs `[bash]`, indicateur « PROCESSING… », gestion d'erreur, persistance par tour.
- Phase 3 : **streaming token par token** — `mekillm.LLM.stream`, événement `AssistantDelta`,
  `run_agent(stream=True)` ; la bulle se construit en direct avec un **caret**, finalisée en markdown.
- Phase 4 : **navigation multi-projet** — sélecteur Projet→scope→session dans la sidebar ; bouton
  « + projet » (enregistrement d'un dépôt git) ; hub câblé sur `dispatch_factory` (workspace confiné
  par session) + `registry` ; carte de validation worktree (`WorktreeProposed`/`Created`/`Rejected`).

> Rendu **markdown** des réponses de l'agent (titres dégressifs, listes, blocs de code, retours-ligne).
> Les messages utilisateur restent en texte brut.

> **Outils étendus** (post-phase-3) : l'agent dispose désormais de `read`/`write`/`edit`/`grep`/`glob`
> en plus de `bash` (cf. [mekicore](mekicore.md)). Le front les affiche via un **bloc d'outil coloré
> par outil** (`<glyphe> <NOM>` + couleur dédiée : bash=ambre, read=cyan, write=vert, edit=magenta,
> grep=violet, glob=bleu) ; l'outil `edit` montre son changement en **diff** `---`/`+++` (rouge/vert).

## Relations entrantes / sortantes

- Dépend de [mekillm](mekillm.md) (`LLM.complete` / `LLM.stream`) et de [mekicore](mekicore.md)
  (`base.run_agent`, `events`, outils `bash`/`read`/`write`/`edit`/`grep`/`glob`).
- Pendant de [mekicore](mekicore.md) : même agent, interface web au lieu du REPL terminal.
- Non-régression réseau-free : `tests/smoke_mekichat.py` (sessions) + `tests/smoke_packages.py`
  (`run_agent`, événements).
