---
title: "shared.py · La bibliothèque commune"
phase: "Bibliothèque"
fichier: "src/shared.py"
lignes: 1631
tags: [bibliothèque, harness]
---

# shared.py · La bibliothèque commune

> **En une phrase** : tout le harness dédupliqué de learn-claude-code dans un seul module importable — les sessions `src/sNN.py` n'écrivent plus que leur délta.

## Rôle

`shared.py` est obtenu en refactorisant le capstone `s20_comprehensive/code.py` (2124 lignes, qui ré-assemblait déjà les mécanismes de s01–s19) en **module bibliothèque** : pas de `main()`, pas de CLI, pas de REPL — uniquement fonctions, classes et registres. Le sous-système mémoire complet vient de `s09_memory/code.py` (s20 ne gardait que la lecture de `MEMORY.md`). Les noms publics d'origine sont conservés (`safe_path`, `run_bash`, `snip_compact`, `reactive_compact`, `MessageBus`, `spawn_subagent`, `BUILTIN_TOOLS`, `BUILTIN_HANDLERS`, `agent_loop`, …) : le wiki s'y réfère directement.

Deux adaptations bibliothèque :

1. **`agent_loop` paramétrable** — `agent_loop(user_input=None, messages=None, *, tools=None, handlers=None, system=None, context=None)`. Tout à `None` = comportement s20 (pool complet builtin + MCP ré-assemblé à chaque tour, system prompt vivant). Une session peut passer un sous-ensemble `tools`/`handlers` (pool figé) et/ou un `system` figé. La fonction retourne `messages`.
2. **État global module-level conservé tel quel** — registres, locks, `mkdir` des répertoires (`.tasks/`, `.worktrees/`, `.mailboxes/`, `.memory/`) et démarrage du thread cron à l'import, comme dans s20.

L'import exige `MODEL_ID` dans l'environnement (`.env` chargé par `load_dotenv`), comme l'original.

## Architecture interne (depuis le refactoring)

Le fichier a été compacté de 2566 à 1631 lignes **sans changer l'API** (mêmes 183 noms publics, mêmes signatures, même comportement). Ce que le lecteur du code rencontre de nouveau :

- **Factory `_tool(name, desc, _required=(), _schema_key="input_schema", /, **props)`** (l. 72) — fabrique tous les schémas d'outils du module (`SUB_TOOLS`, `TEAMMATE_TOOLS`, `BUILTIN_TOOLS`, serveurs MCP mock) ; le 4e argument positionnel permet d'émettre `inputSchema` pour les définitions MCP. Les raccourcis `_STR` / `_INT` / `_BOOL` (l. 77) servent de types de propriétés.
- **Docstrings une ligne** — chaque fonction garde une docstring, réduite à une phrase ; les commentaires de section (`# ── ... ──`) structurent le fichier.
- **Helpers privés factorisés** — `_ask_allow` (l. 179, confirmation [y/N] des hooks de permission), `_content_text` (l. 515, texte des blocs d'un content), `_llm_extract_items` (l. 519, appel LLM → liste JSON parsée, partagé par extraction et consolidation mémoire), `_write_mem_item` (l. 526, écriture d'une mémoire extraite), `_task_op` (l. 761, garde `FileNotFoundError` commune aux wrappers de tâche).
- **Alias directs pour les wrappers `run_*` triviaux** — quand le wrapper n'ajoutait rien, c'est une simple affectation : `run_cancel_cron = cancel_job` (l. 954), `run_spawn_teammate = spawn_teammate_thread` (l. 1134), `run_create_worktree` / `run_remove_worktree` / `run_keep_worktree` (l. 1330–1332), `run_connect_mcp = connect_mcp` (l. 1409).
- **Constantes groupées par point-virgule** — les budgets/seuils tiennent en 4 lignes (l. 41–44), idem pour plusieurs paires d'état module-level.
- **`TEAMMATE_TOOLS` hoisté au niveau module** (l. 984) — les 8 schémas d'outils des teammates ne sont plus reconstruits à chaque `spawn_teammate_thread`.

## Les sections

| Lignes | Section | Contenu | Provenance |
|---|---|---|---|
| 1–27 | Docstring & imports | origine, organisation, `readline` optionnel | s20 |
| 28–58 | Config & console | env, `client`, `MODEL`, budgets, `terminal_print` | s01, s08, s11, s20 |
| 59–69 | Sécurité fichiers | `WORKDIR`, `safe_path` | s02 |
| 70–130 | Outils de base | factory `_tool`, bash/read/write/edit/glob, dispatch | s02 (+ `cwd` de s18) |
| 131–161 | Todos | `CURRENT_TODOS`, normalisation, `run_todo_write` | s05 |
| 162–229 | Permissions & hooks | registre 4 événements, deny list, enregistrements | s03 + s04 |
| 230–279 | Subagent one-shot | `SUB_TOOLS`, `extract_text`, `has_tool_use`, `spawn_subagent` | s06 (+ hooks de s20) |
| 280–320 | Skills | scan `SKILL.md`, catalogue, chargement à la demande | s07 |
| 321–348 | System prompt | `PROMPT_SECTIONS`, `assemble_system_prompt` | s10 |
| 349–467 | Compaction de contexte | budget → snip → micro → compact + `reactive_compact` | s08 (+ s11) |
| 468–638 | Mémoire | fichiers `.memory/*.md`, index, sélection, extraction, consolidation, `update_context` | **s09 (porté)** + s20 |
| 639–683 | Récupération d'erreurs | `RecoveryState`, `with_retry`, détection prompt-too-long | s11 |
| 684–769 | Système de tâches | `Task`, create/claim/complete, dépendances, wrappers | s12 (+ `worktree` de s18) |
| 770–823 | Tâches d'arrière-plan | heuristique lenteur, worker, `task_notification` | s13 |
| 824–959 | Cron | matching 5 champs, validation, jobs durables, scheduler | s14 |
| 960–1150 | Teams / MessageBus | mailboxes JSONL, `spawn_teammate_thread`, wrappers lead | s15 (+ s16/s17/s18) |
| 1151–1203 | Protocoles | `ProtocolState`, routage par `request_id`, outils lead | s16 |
| 1204–1244 | Agent autonome | `scan_unclaimed_tasks`, `idle_poll` | s17 |
| 1245–1333 | Worktrees | validation de noms, `run_git`, create/remove/keep | s18 |
| 1334–1410 | MCP | `MCPClient`, serveurs mock, `assemble_tool_pool` | s19 |
| 1411–1475 | Registres | `BUILTIN_TOOLS` (27 outils), `BUILTIN_HANDLERS` | s02 → s19 |
| 1476–1631 | Agent loop & helpers | `prepare_context`, `call_llm`, `agent_loop`, autorun cron | s20 (assemblage) |

## API publique par section

### Config & console (28–58)
- `client` (l. 34) — instance `Anthropic` (respecte `ANTHROPIC_BASE_URL`).
- `MODEL` / `PRIMARY_MODEL` / `FALLBACK_MODEL` (l. 35–37) — modèle principal (env `MODEL_ID`) et modèle de secours 529.
- Constantes (l. 41–44, groupées par point-virgule) — `DEFAULT_MAX_TOKENS`, `ESCALATED_MAX_TOKENS`, `MAX_RETRIES`, `MAX_CONSECUTIVE_529`, `MAX_RECOVERY_RETRIES`, `BASE_DELAY_MS`, `CONTEXT_LIMIT`, `KEEP_RECENT_TOOL_RESULTS`, `PERSIST_THRESHOLD`, `CONTINUATION_PROMPT` ; les seuils de contexte sont en **caractères JSON**, pas en tokens.
- `PROMPT` / `CLI_ACTIVE` (l. 45) — prompt ANSI et drapeau CLI consommés par `terminal_print` (les sessions CLI les positionnent).
- `terminal_print(text)` (l. 47) — affichage thread-safe qui redessine la ligne readline en cours de saisie.

### Sécurité fichiers (59–69)
- `WORKDIR` (l. 61) — racine du workspace (`Path.cwd()`), base de tous les confinements.
- `safe_path(p, cwd=None)` (l. 63) — résout un chemin et lève `ValueError` s'il s'échappe de la base (workspace ou worktree).

### Outils de base (70–130)
- `_tool(...)` (l. 72) et `_STR`/`_INT`/`_BOOL` (l. 77) — la factory de schémas d'outils (voir « Architecture interne »).
- `run_bash(command, cwd=None, run_in_background=False)` (l. 79) — shell avec timeout 120 s, sortie tronquée à 50 000 caractères ; `run_in_background` est consommé par le dispatcher.
- `run_read(path, limit=None, offset=0, cwd=None)` (l. 87) — lecture paginée avec marqueur de troncature.
- `run_write(path, content, cwd=None)` (l. 97) — écriture avec création des parents.
- `run_edit(path, old_text, new_text, cwd=None)` (l. 106) — remplacement exact et unique.
- `run_glob(pattern, cwd=None)` (l. 116) — glob confiné (re-filtrage `is_relative_to`).
- `call_tool_handler(handler, args, name)` (l. 125) — dispatch universel ; `TypeError` → message d'erreur pour le modèle.

### Todos (131–161)
- `CURRENT_TODOS` (l. 134) — liste en mémoire seulement (plan léger de session).
- `run_todo_write(todos)` (l. 153) — remplace la liste en bloc après normalisation par `_normalize_todos` (l. 136 : liste, JSON ou littéral Python).

### Permissions & hooks (162–229)
- `HOOKS` (l. 165) — registre des 4 événements `UserPromptSubmit` / `PreToolUse` / `PostToolUse` / `Stop`.
- `register_hook(event, callback)` (l. 167) / `trigger_hooks(event, *args)` (l. 169) — le premier retour non-`None` court-circuite ; pour `PreToolUse`, une chaîne = blocage.
- `DENY_LIST` / `DESTRUCTIVE` (l. 176–177) — motifs interdits / à confirmation (recherches de sous-chaînes naïves, volontairement).
- `permission_hook(block)` (l. 183) — deny list bash, confirmation des destructifs (via `_ask_allow`, l. 179), re-validation `safe_path`, confirmation des outils MCP « deploy ».
- `log_hook` (l. 201), `large_output_hook` (l. 206), `user_prompt_hook` (l. 212), `stop_hook` (l. 217) — hooks d'observation ; enregistrés l. 226–228 (`permission_hook` **avant** `log_hook` : un outil refusé n'est jamais loggé).

### Subagent one-shot (230–279)
- `SUB_SYSTEM` / `SUB_TOOLS` / `SUB_HANDLERS` (l. 232 / 235 / 244) — 5 outils, system anti-récursion.
- `extract_text(content)` (l. 247) — concatène les blocs `text` d'une réponse.
- `has_tool_use(content)` (l. 252) — LE prédicat de continuation de la boucle (présence d'un bloc, pas `stop_reason`).
- `spawn_subagent(description)` (l. 256) — boucle isolée (30 tours max), hooks appliqués, seul le dernier texte assistant remonte.

### Skills (280–320)
- `SKILLS_DIR` / `SKILL_REGISTRY` (l. 283–284) — répertoire `skills/` et catalogue en mémoire.
- `_parse_frontmatter(text)` (l. 286) — découpe markdown en (méta YAML, corps) ; **partagé** par skills et mémoire.
- `scan_skills()` (l. 295, appelé l. 308) — repeuple le catalogue depuis `skills/*/SKILL.md`.
- `list_skills()` (l. 310) / `load_skill(name)` (l. 315) — catalogue en puces / contenu complet à la demande.

### System prompt (321–348)
- `PROMPT_SECTIONS` (l. 323) — sections statiques (identité, liste des 27 outils, workspace, note mémoire).
- `assemble_system_prompt(context)` (l. 337) — reconstruit le system prompt à chaque tour : heure courante, catalogue skills, mémoires, serveurs MCP connectés.

### Compaction de contexte (349–467)
- `TRANSCRIPT_DIR` / `TOOL_RESULTS_DIR` (l. 353) — transcripts JSONL et sorties persistées.
- `estimate_size(messages)` (l. 355) — approximation en caractères JSON.
- `block_type` (l. 359), `message_has_tool_use` (l. 363), `is_tool_result_message` (l. 368), `collect_tool_results` (l. 373) — prédicats de structure (protection des paires tool_use ↔ tool_result).
- `persist_large_output(tool_use_id, output)` (l. 383) — sorties > 30 000 caractères écrites sur disque, remplacées par `<persisted-output>`.
- `tool_result_budget(messages, max_bytes=200_000)` (l. 391) — couche 1 : persiste les plus gros résultats du dernier message.
- `snip_compact(messages, max_messages=50)` (l. 408) — couche 2 : coupe le milieu sans casser une paire tool_use/tool_result.
- `micro_compact(messages)` (l. 423) — couche 3 : efface les vieux tool_result (sauf les 3 derniers).
- `write_transcript(messages)` (l. 432) — assurance-vie JSONL avant toute compaction destructive.
- `summarize_history(messages)` (l. 441) — appel LLM dédié de résumé.
- `compact_history(messages)` (l. 449) — couche 4 : tout l'historique devient UN message `[Compacted]`.
- `reactive_compact(messages)` (l. 455) — compaction d'urgence post « prompt too long », résumé sous try/except avec texte de repli.

### Mémoire (468–638) — portée de s09
- `MEMORY_DIR` / `MEMORY_INDEX` / `MEMORY_TYPES` (l. 472–474) — `.memory/`, `MEMORY.md`, types `user|feedback|project|reference`.
- `write_memory_file(name, mem_type, description, body)` (l. 476) — écrit un fichier mémoire (frontmatter) et reconstruit l'index (`_rebuild_index`, l. 484).
- `read_memory_index()` (l. 494) / `read_memory_file(filename)` (l. 499) / `list_memory_files()` (l. 504) — lecture index / fichier / liste avec métadonnées.
- `select_relevant_memories(messages, max_items=5)` (l. 534) — sélection par LLM avec repli mots-clés.
- `load_memories(messages)` (l. 569) — contenu des mémoires pertinentes en bloc `<relevant_memories>`.
- `extract_memories(messages)` (l. 578) — extraction post-tour de nouvelles mémoires (anti-doublons) ; s'appuie sur `_llm_extract_items` (l. 519) et `_write_mem_item` (l. 526).
- `consolidate_memories()` (l. 609) — fusion/purge quand `CONSOLIDATE_THRESHOLD` (10, l. 607) fichiers est atteint.
- `update_context(context, messages)` (l. 633) — version s20 : `MEMORY.md` (2000 premiers caractères) + état vivant MCP/teammates ; c'est le dict passé à `assemble_system_prompt`.

### Récupération d'erreurs (639–683)
- `RecoveryState` (l. 641) — escalade, continuations, 529 consécutifs, compaction réactive (une fois), modèle courant.
- `retry_delay(attempt)` (l. 649) — backoff exponentiel plafonné + jitter.
- `with_retry(fn, state)` (l. 654) — 429 → backoff ; 529 → backoff + bascule `FALLBACK_MODEL` ; le reste relancé.
- `is_prompt_too_long_error(e)` (l. 679) — déclencheur de `reactive_compact` dans la boucle.

### Système de tâches (684–769)
- `TASKS_DIR` (l. 688) / `Task` (l. 691) — enregistrements JSON durables sous `.tasks/`, champ `worktree` inclus.
- `create_task` (l. 698), `save_task` (l. 706), `load_task` (l. 708), `list_tasks` (l. 710), `get_task_json` (l. 713) — CRUD sur disque.
- `can_start(task_id)` (l. 715) — chaque bloqueur doit exister et être `completed`.
- `claim_task(task_id, owner)` (l. 720) / `complete_task(task_id)` (l. 738) — revendication à triple garde / complétion avec liste des tâches débloquées.
- Wrappers outils : `run_create_task` (l. 749), `run_list_tasks` (l. 755), puis `run_get_task` / `run_claim_task` / `run_complete_task` (l. 766–768), une ligne chacun via `_task_op` (l. 761).

### Tâches d'arrière-plan (770–823)
- `background_tasks` / `background_results` / `background_lock` (l. 774–775) — état partagé des workers.
- `is_slow_operation(tool_name, tool_input)` (l. 777) — heuristique mots-clés (install, build, test, …).
- `should_run_background(tool_name, tool_input)` (l. 784) — demande du modèle OU heuristique.
- `start_background_task(block, handlers)` (l. 789) — worker daemon, `PostToolUse` déclenché quand même.
- `collect_background_results()` (l. 809) — draine en blocs `<task_notification>`.

### Cron (824–959)
- `DURABLE_PATH` / `CronJob` / `scheduled_jobs` / `cron_queue` / `cron_lock` (l. 827–834) — état du scheduler.
- `cron_matches(cron_expr, dt)` (l. 849) — matching 5 champs avec sémantique OU dom/dow du vrai cron.
- `validate_cron(cron_expr)` (l. 881) — validation complète, messages nommant le champ fautif.
- `save_durable_jobs` (l. 890) / `load_durable_jobs` (l. 894) — persistance des seuls jobs durables, re-validés au rechargement.
- `schedule_job` (l. 904) / `cancel_job` (l. 914) — création (retourne `CronJob | str`) / annulation.
- `cron_scheduler_loop()` (l. 920) — tick 1 s, anti-double-déclenchement par marqueur à la minute.
- `consume_cron_queue()` (l. 938) — drainage atomique de la file.
- Wrappers outils : `run_schedule_cron` (l. 943), `run_list_crons` (l. 947), `run_cancel_cron` (alias direct de `cancel_job`, l. 954). Amorçage à l'import l. 957–958 (jobs durables + thread daemon).

### Teams / MessageBus (960–1150)
- `MAILBOX_DIR` (l. 963) / `MessageBus` (l. 965) — mailboxes JSONL append-only ; `read_inbox` est **destructive** (unlink).
- `BUS` / `active_teammates` (l. 981–982) — instance globale et registre des teammates vivants.
- `TEAMMATE_TOOLS` (l. 984) — les 8 schémas d'outils des teammates, au niveau module (construits par `_tool`).
- `spawn_teammate_thread(name, role, prompt)` (l. 995) — mini-harness par teammate : 8 outils, gate d'approbation de plan, bascule worktree, fenêtre `messages[-20:]`, `idle_poll` entre les rafales. Contient le FIX(mekicode) (voir plus bas).
- `_teammate_submit_plan(from_name, plan)` (l. 1126) — crée la requête `plan_approval` et l'envoie au lead.
- Wrappers lead : `run_spawn_teammate` (alias direct, l. 1134), `run_send_message` (l. 1136), `run_check_inbox` (l. 1140).

### Protocoles (1151–1203)
- `ProtocolState` (l. 1154) / `pending_requests` (l. 1158) — requêtes de protocole en cours.
- `new_request_id()` (l. 1160) — identifiant appariable `req_NNNNNN`.
- `match_response(response_type, request_id, approve)` (l. 1162) — appariement par id ET par type.
- `consume_lead_inbox(route_protocol=True)` (l. 1170) — drainage de l'inbox lead avec routage automatique des `*_response`.
- `run_request_shutdown` (l. 1182), `run_request_plan` (l. 1190), `run_review_plan` (l. 1195) — outils de protocole côté lead.

### Agent autonome (1204–1244)
- `IDLE_POLL_INTERVAL` / `IDLE_TIMEOUT` (l. 1206) — 12 cycles de 5 s.
- `scan_unclaimed_tasks()` (l. 1208) — tâches pending, sans owner, démarrables.
- `idle_poll(agent_name, messages, name, role, worktree_context=None)` (l. 1214) — inbox d'abord, revendication autonome ensuite, sinon timeout.

### Worktrees (1245–1333)
- `WORKTREES_DIR` / `VALID_WT_NAME` (l. 1248–1249) — répertoire `.worktrees/` et regex de noms.
- `validate_worktree_name(name)` (l. 1251) — frontière de sécurité au niveau outil, avant git.
- `run_git(args)` (l. 1260) — wrapper subprocess → (succès, sortie tronquée).
- `log_event` (l. 1268) — journal d'audit `events.jsonl`.
- `create_worktree` (l. 1273), `bind_task_to_worktree` (l. 1289), `remove_worktree` (l. 1304, refus par défaut si changements), `keep_worktree` (l. 1323).
- Wrappers outils : `run_create_worktree` / `run_remove_worktree` / `run_keep_worktree` (alias directs, l. 1330–1332).

### MCP (1334–1410)
- `MCPClient` (l. 1337) / `mcp_clients` (l. 1352) — client mock et registre des connexions.
- `normalize_mcp_name(name)` (l. 1355) — assainissement des noms externes.
- `MOCK_SERVERS` (l. 1382) — serveurs simulés `docs` (readOnly) et `deploy` (destructif).
- `connect_mcp(name)` (l. 1384) — connexion idempotente ; outils visibles au tour suivant.
- `assemble_tool_pool()` (l. 1396) — fusion builtin + MCP (copies défensives, conversion `inputSchema` → `input_schema`, lambdas à arguments par défaut contre la capture tardive).
- `run_connect_mcp` (alias direct, l. 1409).

### Registres (1411–1475)
- `BUILTIN_TOOLS` (l. 1414) — les 27 outils natifs, schémas construits par `_tool`.
- `BUILTIN_HANDLERS` (l. 1461) — table miroir nom → fonction ; `compact` n'y figure pas (outil méta intercepté par `agent_loop`).

### Agent loop & helpers (1476–1631)
- `rounds_since_todo` / `agent_lock` (l. 1478–1479) — compteur de rappel todo et verrou qui sérialise tours humains et tours cron.
- `prepare_context(messages)` (l. 1481) — pipeline de compaction en place (`messages[:] =`), du moins au plus destructif.
- `build_user_content(results)` (l. 1490) — tool_results + notifications d'arrière-plan en un message user.
- `inject_background_notifications(messages)` (l. 1494) — second canal de livraison, en début de tour.
- `call_llm(messages, context, tools, state, max_tokens, system=None)` (l. 1500) — system vivant (ou figé) + `with_retry` avec le modèle courant.
- `agent_loop(user_input=None, messages=None, *, tools=None, handlers=None, system=None, context=None)` (l. 1508) — la boucle de synthèse paramétrable ; retourne `messages`.
- `print_turn_assistants(messages, turn_start)` (l. 1609) — rendu des textes assistants d'un tour, compatible threads.
- `cron_autorun_loop(history, context)` (l. 1617) — thread qui lance des tours d'agent autonomes quand un cron tire, sous `agent_lock`.

## FIX(mekicode) appliqués

Un seul, dans `spawn_teammate_thread` (l. 1090–1100) :

- **Tool_use orphelins après `submit_plan`** — dans s20, quand un teammate soumettait un plan, les blocs `tool_use` *suivants* de la même réponse étaient abandonnés sans `tool_result` (`break` sec). L'API exige un `tool_result` par `tool_use` : dès que la paire bancale restait dans la fenêtre `messages[-20:]`, l'appel suivant échouait en 400. Le fix répond à chaque bloc restant par un placeholder `[Deferred until plan approval]` avant de fermer le gate. (Piège documenté dans la page s20 du wiki learn.)

Pièges documentés **portés tels quels** (pas des crashs, choix pédagogiques) : `tool_result_budget` tolère silencieusement un dépassement fait de petits blocs ; lecture d'inbox destructive ; permissions par sous-chaînes naïves ; ordre des hooks = politique ; `compact` hors de `BUILTIN_HANDLERS`.

## Provenance des mécanismes

Format texte (sessions du repo learn-claude-code) :

- **s01** : la boucle `while True` + `has_tool_use` (le bloc concret, pas `stop_reason`).
- **s02** : outils de base bash/read/write/edit/glob, `safe_path`, dispatch.
- **s03** : deny list, confirmations destructives (recâblées en hook `PreToolUse`).
- **s04** : registre de hooks à 4 événements, court-circuit au premier non-`None`.
- **s05** : `todo_write` + rappel tous les 3 tours.
- **s06** : subagent one-shot `task` (étendu : hooks appliqués aux sous-agents).
- **s07** : skills à divulgation progressive (catalogue + `load_skill`).
- **s08** : pipeline de compaction (budget → snip → micro → compact), transcripts.
- **s09** : tout le sous-système mémoire (fichiers, index, sélection, extraction, consolidation) — porté intégralement car amputé dans s20.
- **s10** : assemblage du system prompt par sections.
- **s11** : `RecoveryState`, `with_retry`, escalade max_tokens, `reactive_compact`, modèle de secours.
- **s12** : task graph durable (`Task`, dépendances `blockedBy`).
- **s13** : tâches d'arrière-plan (placeholder + `task_notification`).
- **s14** : cron (matching, validation, jobs durables, scheduler, autorun).
- **s15** : `MessageBus`, teammates en thread.
- **s16** : protocoles (`request_id`, gate d'approbation de plan).
- **s17** : agent autonome (`idle_poll`, revendication de tâches libres).
- **s18** : worktrees git liés aux tâches, paramètre `cwd` des outils fichiers.
- **s19** : MCP (`MCPClient`, `assemble_tool_pool`, noms `mcp__server__tool`).
- **s20** : l'orchestration unique — `terminal_print`, `prepare_context`, `build_user_content`, `inject_background_notifications`, `call_llm`, `agent_loop`, `print_turn_assistants`, `cron_autorun_loop` (le CLI `__main__` de s20 n'est volontairement **pas** porté).

## Liens

- Accueil du wiki : [[Accueil]]
