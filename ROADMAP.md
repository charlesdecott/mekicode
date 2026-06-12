# ROADMAP — mekicode

> Dernière mise à jour : 2026-06-12

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
| s02 | tool use (appel d'outils structuré) | ✅ | ✅ (outil `bash` exécuté via `run_agent`, blocs `[bash]` dans le front) |
| s03 | todo write (todo-list interne) | ✅ | ⬜ |
| s04 | subagent (délégation à des sous-agents) | ✅ | ⬜ |
| s05 | skill loading (chargement de `SKILL.md`) | ✅ | ⬜ |
| s06 | context compact (compaction du contexte) | ✅ | ⬜ |
| s07 | task system (tâches suivies) | ✅ | ⬜ |
| s08 | background tasks (tâches en arrière-plan) | ✅ | ⬜ |
| s09 | agent teams (équipes d'agents) | ✅ | ⬜ |
| s10 | team protocols (communication d'équipe) | ✅ | ⬜ |
| s11 | autonomous agents (boucles autonomes) | ✅ | ⬜ |
| s12 | worktree task isolation (isolation git) | ✅ | ⬜ |
| s13 | streaming (réponses en flux) | ✅ | ⬜ |
| s14 | tools extended (read/write/grep/glob/revert) | ✅ | ⬜ |
| s15 | permissions (gouvernance 3 tiers) | ✅ | ⬜ |
| s16 | event bus (hooks d'événements) | ✅ | 🟡 cousin léger (hooks d'observabilité mekillm) |
| s17 | session management (persistance/reprise) | ✅ | ⬜ |
| s18 | parallel tools (exécution parallèle) | ✅ | ⬜ |
| s19 | interrupts (interruptions) | ✅ | ⬜ |
| s20 | cache optimization (prompt caching) | ✅ | ⬜ |
| s21 | mcp runtime (Model Context Protocol) | ✅ | ⬜ |
| s22 | production mailbox (file de messages) | ✅ | ⬜ |
| s23 | worktree advanced | ✅ | ⬜ |

Légende : ✅ implémenté · 🟡 partiel · ⬜ à faire.

**Avancement `packages/` vs s01–s23 : ≈ 2 / 23 ≈ 9 %** (s01 + s02 complets). C'est volontaire :
on reconstruit proprement à partir du socle, on ne recopie pas `src_scratch/`.

## Ce qui est implémenté dans `packages/`

### `packages/mekillm/` — provider LLM généraliste
- Wrapper du SDK `openai` pointé sur **OpenRouter** ; bascule **ollama / litellm** par le seul `.env`.
- Interface normalisée, agnostique du provider : `LLM.complete()` → `LLMResponse`
  (`text`, `tool_calls`, `finish_reason`, `usage`, `message`, `raw`).
- **Observabilité** intégrée (au-delà de ccfs) : chaque appel émet un `CallRecord` vers 3 canaux —
  `logging`, JSONL append-only (`.logs/` à la racine), et hooks personnalisables.
- Importable n'importe où : `mekillm.LLM`, `mekillm.complete`, `mekillm.observe`.

### `packages/mekicore/` — mini-harness (s01 adapté)
- Boucle perception-action au format OpenAI (`tool_calls` ↔ messages `role:"tool"`).
- `run_agent` : variante **à événements** (`events.py` : `ThinkingStarted`, `AssistantDone`,
  `ToolStarted`/`ToolFinished`, `RunFinished`, `RunError`) consommée par le front ; `agent_loop`
  (REPL console) est réexprimé dessus.
- Outil `bash` avec garde-fous, schéma function-calling, table de dispatch.
- REPL (`main.py`) ; en console : en-tête **heure + modèle** avant chaque réponse.

### `packages/mekichat/` — front web NiceGUI (phases 1-2 livrées)
- Interface web in-process, mode conversation type Discord (thème cyberpunk **Phosphore**).
- `sessions.py` : persistance JSON des sessions sous `.sessions/` (racine), format OpenAI.
- `views.py` : rendu des bulles, des blocs `[bash]`, de l'historique, de l'indicateur « PROCESSING… ».
- `app.py` : page NiceGUI (**http://localhost:8080**, lanceur `.\start-chat.ps1`) ; l'envoi pilote
  `base.run_agent` via `run.io_bound` et rend bulles + blocs `[bash]` en direct.
- **Phase 1** (sessions + UI statique) et **phase 2** (chat + outil `bash`, non-streaming) **livrées** ;
  phase 3 (streaming token par token) à venir.

### Confort projet
- Lanceurs `start.ps1` / `start.sh` (mekicore) et `start-chat.ps1` (mekichat) à la racine.
- Tests réseau-free : `python tests/smoke_packages.py` (mekillm + mekicore) et `python tests/smoke_mekichat.py` (mekichat).
- Données runtime (logs, sessions) à la racine (`.logs/`, `.sessions/`), jamais dans `packages/`.

## Ce qu'apporte `packages/` en plus de claude-code-from-scratch
- **Multi-backend** : ccfs est Anthropic-only ; mekillm parle OpenRouter/ollama/litellm.
- **Module réutilisable** : mekillm est conçu pour être importé hors du repo (pas un script de session).
- **Observabilité de premier plan** (monitor / profile / log) absente de ccfs.

## Reste à faire

### Court terme (porter les prochaines sessions dans `packages/`)
- [ ] mekichat phase 3 — streaming token par token (`LLM.stream` + affichage progressif NiceGUI).
- [ ] s14 — outils étendus (read / write / grep / glob / revert) au format OpenAI.
- [ ] s15 — gouvernance des permissions (3 tiers) autour de `dispatch_tools`.
- [ ] s13 — streaming dans `mekillm.complete` (token par token).
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
