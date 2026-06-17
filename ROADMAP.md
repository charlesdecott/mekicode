# ROADMAP — mekicode

> Dernière mise à jour : 2026-06-15

État d'avancement du projet et feuille de route. Pour comprendre le code, voir la documentation
dans [`docs/`](docs/README.md).

## Où on en est

`mekicode` s'est construit en plusieurs bases de code parallèles. `src/` (refonte de
learn-claude-code) a depuis été **retirée** ; il reste deux bases actives, du plus pédagogique au
plus réutilisable :

| Base | Rôle | Inspiration | Backend LLM | Statut |
|------|------|-------------|-------------|--------|
| ~~`src/`~~ | refonte d'étude (démos par mécanisme) | learn-claude-code | — | **retirée** (au profit de `src_scratch/` + `packages/`) |
| `src_scratch/` | refonte dédupliquée complète | claude-code-from-scratch | Anthropic | **s01–s23 (100 %)** |
| `packages/` | **cible « produit »** : paquets autonomes réutilisables | (repart de s01) | OpenRouter (+ ollama/litellm) | **en cours** |

La direction actuelle du projet est **`packages/`** : sortir une base propre, importable n'importe
où, multi-backend, avec observabilité — au lieu d'un script d'étude couplé à Anthropic.

## Features claude-code-from-scratch (s01–s23)

`src_scratch/` est une refonte **complète** des 23 sessions de `inspiration/claude-code-from-scratch/`.
Le tableau ci-dessous suit où chaque feature en est **dans la base produit `packages/`** (le reste
existe déjà, validé, dans `src_scratch/`).

| Session | Feature | `src_scratch/` | `packages/` |
|---------|---------|:---:|:---:|
| s01 | boucle perception-action + outil bash | ✅ | ✅ |
| s02 | tool use (appel d'outils structuré) | ✅ | ✅ (outils exécutés via `run_agent`, blocs d'outils colorés/repliables par outil dans le front) |
| s03 | todo write (todo-list interne) | ✅ | ⬜ |
| s04 | subagent (délégation à des sous-agents) | ✅ | ⬜ |
| s05 | skill loading (chargement de `SKILL.md`) | ✅ | ⬜ |
| s06 | context compact (compaction du contexte) | ✅ | ⬜ |
| s07 | task system (tâches suivies) | ✅ | ⬜ |
| s08 | background tasks (tâches en arrière-plan) | ✅ | ⬜ |
| s09 | agent teams (équipes d'agents) | ✅ | ⬜ |
| s10 | team protocols (communication d'équipe) | ✅ | ⬜ |
| s11 | autonomous agents (boucles autonomes) | ✅ | ⬜ |
| s12 | worktree task isolation (isolation git) | ✅ | 🟡 `projects.py` : `add_worktree`/`list_worktrees`/`remove_worktree` + `workspace_for` ; outil `spawn_worktree` propose/approve/reject via le hub (validation humaine requise) |
| s13 | streaming (réponses en flux) | ✅ | ✅ (`LLM.stream` + streaming dans le front mekichat) |
| s14 | tools extended (read/write/grep/glob/revert) | ✅ | 🟡 read/write/edit/grep/glob **confinés au workspace** (revert hors périmètre — YAGNI) |
| s15 | permissions (gouvernance 3 tiers) | ✅ | ✅ (HookBus + couches session/projet/global, tier *ask* async, carte 5 choix) |
| s16 | event bus (hooks d'événements) | ✅ | 🟡 mekihub = bus de session pub/sub (events de salle + run) ; hooks d'observabilité mekillm côté LLM |
| s17 | session management (persistance/reprise) | ✅ | ⬜ |
| s18 | parallel tools (exécution parallèle) | ✅ | ⬜ |
| s19 | interrupts (interruptions) | ✅ | ⬜ |
| s20 | cache optimization (prompt caching) | ✅ | ⬜ |
| s21 | mcp runtime (Model Context Protocol) | ✅ | ⬜ |
| s22 | production mailbox (file de messages) | ✅ | ⬜ |
| s23 | worktree advanced | ✅ | ⬜ |

Légende : ✅ implémenté · 🟡 partiel · ⬜ à faire.

**Avancement `packages/` vs s01–s23 : ≈ 5 / 23 ≈ 22 %** (s01 + s02 + s13 complets, s14 quasi complet —
read/write/edit/grep/glob confinés, sans revert ; s12 partiel — worktree avec validation humaine).
C'est volontaire : on reconstruit proprement à partir du socle, on ne recopie pas `src_scratch/`.

## Ce qui est implémenté dans `packages/`

### `packages/mekillm/` — provider LLM généraliste
- Wrapper du SDK `openai` pointé sur **OpenRouter** ; bascule **ollama / litellm** par le seul `.env`.
- Interface normalisée, agnostique du provider : `LLM.complete()` → `LLMResponse`
  (`text`, `tool_calls`, `finish_reason`, `usage`, `message`, `raw`).
- **Streaming** (s13) : `LLM.stream()` — générateur de tokens, réassemble texte + `tool_calls` en
  `LLMResponse` final (réassemblage robuste multi-backend).
- **Observabilité** intégrée (au-delà de ccfs) : chaque appel émet un `CallRecord` vers 3 canaux —
  `logging`, JSONL append-only (`.logs/` à la racine), et hooks personnalisables.
- Importable n'importe où : `mekillm.LLM`, `mekillm.complete`, `mekillm.observe`.

### `packages/mekicore/` — mini-harness (s01 adapté)
- Boucle perception-action au format OpenAI (`tool_calls` ↔ messages `role:"tool"`).
- `run_agent` : variante **à événements** (`events.py` : `ThinkingStarted`, `AssistantDone`,
  `ToolStarted`/`ToolFinished`, `RunFinished`, `RunError`) consommée par le front ; `agent_loop`
  (REPL console) est réexprimé dessus.
- **Six outils** au format function-calling : `bash` (garde-fous, non confiné) + `read`/`write`/`edit`
  (str-replace)/`grep`/`glob` **confinés à un workspace** (`_safe_path`, racine = `cwd` par défaut,
  surchargeable par `MEKICORE_WORKSPACE`). Schémas `TOOLS` + table `DISPATCH` ; `run_agent` dispatche
  génériquement par nom.
- REPL (`main.py`) ; en console : en-tête **heure + modèle** avant chaque réponse.

### `packages/mekihub/` — hub de session temps réel (multi-utilisateur, multi-canal, multi-projet)
- Bus de conversation partagée : **salle partagée** multi-utilisateur (présence, pseudos colorés éphémères).
- `session.py` : couche session canonique — `Author` (+ `source`), `QueueItem`, `Session.add_user`
  (attribution séparée des messages OpenAI), `SessionState`, `SessionStore` (authors persisté ;
  présence/file éphémères ; champs `project_id`, `scope`, `discord_channel_id` ; migration douce).
- `projects.py` : **NOUVEAU** — `Project` (dataclass), `ProjectRegistry` (CRUD JSON dans
  `.mekicode/projects.json`), `workspace_for(session, registry)`, helpers worktree
  (`add_worktree`, `list_worktrees`, `remove_worktree`, `slugify`).
- `events.py` : 16 types — 13 originaux + `WorktreeProposed`/`WorktreeRejected`/`WorktreeCreated` ;
  `MessagePosted` enrichi du champ `source`.
- `hub.py` : `PendingQueue` (FIFO supprimable, `pop_next` async), `SessionHub` (constructeur étendu :
  `dispatch_factory`, `registry`, `provisioner` ; méthodes : `approve_worktree`, `reject_worktree` ;
  workspace confiné par session ; outil agent `spawn_worktree`).
- `adapters/discord.py` : `DiscordProvisioner` (provisioning idempotent : `ensure_server`,
  `ensure_project`, `ensure_channel`, `reconcile`) + `DiscordAdapter` (mapping canal→session,
  handle_message avec `source="discord:<canal>"`, `_render_loop` avec anti-écho) +
  `FakeDiscordClient` étendu (guild/catégorie/canal/invite) + `FakeMessage` (tests réseau-free).
- `main.py` : `build_hub()` + `main()` (front/discord pilotés par `MEKIHUB_FRONT`/`MEKIHUB_DISCORD`).
- Chaîne de dépendance : `mekichat` / `adapters.discord` → **mekihub** → `mekicore` → `mekillm`.
- Non-régression réseau-free : `tests/smoke_mekihub.py` (FakeLLM + FakeDiscordClient étendu ;
  projets, workspace, worktree propose/approve/reject, provisioner idempotent, anti-écho, reconcile).
- Validation Discord RÉELLE : manuelle (token bot requis) — backfill historique et transfert de
  propriété serveur différés.

### `packages/mekichat/` — front web NiceGUI (phases 1-4 livrées)
- Interface web in-process, mode conversation type Discord (thème cyberpunk **Phosphore**), réponses en markdown.
- `sessions.py` : **ré-export** de la couche session canonique de mekihub (shim de compatibilité).
- `views.py` : rendu des bulles (markdown), des **blocs d'outils colorés/repliables par outil**
  (glyphe + couleur dédiés aux six outils ; **repliés par défaut**, clic = ouvrir ; métrique d'en-tête ;
  diff `---`/`+++` pour `edit`), du streaming (caret), de l'historique, du **sélecteur multi-projet**
  (`render_project_selector` : Projet→scope→session + bouton « + projet ») et de la **carte worktree**
  (`render_worktree_proposal` : Approuver/Refuser, bandeau de confirmation).
- `app.py` : page NiceGUI (**http://localhost:8080**, lanceur `.\start-chat.ps1`) ; **adaptateur
  NiceGUI multi-utilisateur** du `SessionHub` (présence, broadcast live, UI file d'attente avec
  suppression de messages en attente) ; hub câblé sur `dispatch_factory` + `registry`.
- **Phases 1-3 livrées** : sessions + UI statique (1) ; chat + outil `bash` (2) ; streaming token-par-token (3).
- **Phase 4 livrée** : navigation multi-projet + carte de validation worktree.
- **Outils étendus** (post-phase-3) : les six outils de mekicore rendus en blocs colorés/repliables.

### `packages/mekistudio/` — front studio 3 modes (Sprints 1 + 2 + extraits 3/4 livrés)
Intègre le canvas de **mekistudio** (projet d'étude `C:\mekistudio`) dans notre harness. Spec/plan :
`docs/superpowers/specs/2026-06-17-…` et `docs/superpowers/plans/2026-06-17-sprint1-mekistudio-canvas.md`.
- **Restructure** : `packages/mekichat/` → `packages/mekistudio/mekichat/` ; nouveau module
  `packages/mekistudio/mekicanvas/` ; back (`mekicore`/`mekillm`/`mekihub`) en packages frères.
- **`ChatComponent`** réutilisable (extrait du chat monolithique) : utilisé dans l'onglet, la node chat
  du canvas et le panneau focus. Carte de permission s15 intégrée.
- **Canvas NiceGUI** : géométrie câbles 45° vendorée (MIT, testée `node --test`), pont `canvas.js`
  (pan/zoom + comètes + **drag/resize** des nodes, positions persistées localStorage), modèle
  Node/Component (pydantic) + registry/parenting.
- **Coquille 3 modes** (`shell.py`) : **Chat** (= accueil historique `/`), **Canvas** (une node chat
  par session, **groupées par espace de travail** : folder = repo main / worktrees + branche affichée),
  **Mix** (chat focus à gauche + canvas) ; **clic sur un chat = focus/highlight**, repris à gauche en Mix.
- **Lecture au zoom** : zoom-in densifie le texte du chat (plus de texte/ligne) ; molette dans un chat
  = scroll du fil ; pas de scroll horizontal. Entrées : `python packages/mekistudio/mekichat/app.py`
  (`/` accueil, **`/studio`** 3 modes) ou `.\start-studio.ps1`.
- **Sprint 2 — Fichiers (livré, vérifié Playwright)** : `mekicanvas/fs.py` (helpers sandboxés
  list/read/write atomique, `smoke_mekicanvas_fs`), **ExplorerNode** (`explorer.py`, arbre lazy
  `ui.expansion`, clic fichier→éditeur), **EditorNode** (`editor.py`, `ui.codemirror` coloré par
  extension, sauvegarde, **pin** des éphémères, **aperçu markdown**, **diff vs HEAD** coloré),
  **spawn auto d'un éditeur éphémère + comète quand l'agent `read` un fichier**, **nodes dossiers**
  (groupement organique : éditeur→dossier→explorateur, dédup par dossier parent).
- **Sprint 3 — Nodes outils (livré)** : **node Git** (branche + ahead/behind + modifs, rafraîchie),
  **node Terminal** (`terminal.py`, runner de commandes shell dans le workspace, non-bloquant).
- **Sprint 4 — Interactivité (livré)** : outil agent **`ask_user`** (QCM/réponse libre en plein tour,
  bloque jusqu'à la réponse ; event `AskRequested` + `SessionHub.resolve_ask` + carte chat),
  **palette de nodes** (`+` → Terminal / Ouvrir un fichier par chemin).
- **Reste (multi-utilisateur temps réel, le plus lourd)** : présence/curseurs sur le canvas, sync des
  positions de nodes entre clients (actuellement localStorage par navigateur), subcanvas conteneur,
  multi-canvas (onglets). Polish : dédup accueil `/`→`ChatComponent`, carte permission/ask dédupliquée
  en Mix (2 instances), chaîne de dossiers multi-niveaux (actuellement 1 niveau).
- Modes test front : `MEKICHAT_FAKE_READ=1` (agent lit CLAUDE.md → éditeur), `MEKICHAT_FAKE_ASK=1`
  (agent pose une question QCM), `MEKICHAT_FAKE_TOOL=1` (bash `rm` → carte permission).

### Confort projet
- Lanceurs `start.ps1` / `start.sh` (mekicore) et `start-chat.ps1` (mekichat) à la racine.
- Tests réseau-free : `python tests/smoke_packages.py` (mekillm + mekicore), `python tests/smoke_mekichat.py`
  (mekichat) et `python tests/smoke_mekihub.py` (mekihub + Discord).
- Données runtime (logs, sessions) à la racine (`.logs/`, `.sessions/`), jamais dans `packages/`.
- Docker : `Dockerfile` + `docker-compose.yml` à la racine (conteneur = isolation de l'agent).

## Ce qu'apporte `packages/` en plus de claude-code-from-scratch
- **Multi-backend** : ccfs est Anthropic-only ; mekillm parle OpenRouter/ollama/litellm.
- **Module réutilisable** : mekillm est conçu pour être importé hors du repo (pas un script de session).
- **Observabilité de premier plan** (monitor / profile / log) absente de ccfs.

## Reste à faire

### Court terme (porter les prochaines sessions dans `packages/`)
- [x] s14 — outils étendus : **read / write / edit / grep / glob** au format OpenAI, confinés au
  workspace (`MEKICORE_WORKSPACE`, défaut `cwd`) + rendu générique dans le front. *revert* hors périmètre (YAGNI).
- [x] s12 (partiel) — **multi-projet + worktree par chat** : `ProjectRegistry`, `workspace_for`,
  `spawn_worktree` (propose/approve/reject via le hub), navigation Projet→scope→session dans mekichat,
  `DiscordProvisioner` (provisioning idempotent), anti-écho Discord.
  - Différé : validation Discord live (token bot requis), backfill historique de sessions existantes,
    transfert de propriété serveur.
- [x] s15 — gouvernance des permissions (3 tiers) autour de l'exécution d'outils : **livré** (Sprint 1).
  `mekicore` HookBus (`pre_tool` vetoable) + `permissions.py`/`permissions.yaml` (deny/allow/ask +
  résolution en couches session→projet→global) ; `mekihub` `PermissionRequested` + `resolve_permission`
  (tier *ask* async cross-thread, timeout→deny, gate auteur/admin) ; carte 5 choix dans le chat.
- [ ] s06 — compaction du contexte quand l'historique grossit.

### Moyen terme
- [ ] s04 / s09 / s10 — sous-agents et équipes.
- [ ] s07 / s08 / s11 — système de tâches, arrière-plan, boucles autonomes.
- [ ] s21 — runtime MCP.

### Transverse / qualité
- [ ] Coût `$` par appel (champ `CallRecord.cost_usd`, aujourd'hui `None`).
- [ ] Backend **ollama** réellement testé (l'architecture le permet via `.env`).
- [ ] Packaging pip (`pyproject.toml`) si on veut un vrai `pip install mekillm` (aujourd'hui import par chemin).
- [ ] Wiki understand-anything généré pour `packages/` (aujourd'hui doc rédigée à la main dans `docs/`).
