---
title: "shared.py · La bibliothèque commune"
phase: "Bibliothèque"
fichier: "src/shared.py"
lignes: 2566
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

## Les sections

| Lignes | Section | Contenu | Provenance |
|---|---|---|---|
| 1–41 | Docstring & imports | origine, organisation, `readline` optionnel | s20 |
| 42–84 | Config & console | env, `client`, `MODEL`, budgets, `terminal_print` | s01, s08, s11, s20 |
| 85–99 | Sécurité fichiers | `WORKDIR`, `safe_path` | s02 |
| 100–179 | Outils de base | bash/read/write/edit/glob, dispatch | s02 (+ `cwd` de s18) |
| 180–220 | Todos | `CURRENT_TODOS`, normalisation, `run_todo_write` | s05 |
| 221–316 | Permissions & hooks | registre 4 événements, deny list, enregistrements | s03 + s04 |
| 317–414 | Subagent one-shot | `SUB_TOOLS`, `extract_text`, `has_tool_use`, `spawn_subagent` | s06 (+ hooks de s20) |
| 415–481 | Skills | scan `SKILL.md`, catalogue, chargement à la demande | s07 |
| 482–515 | System prompt | `PROMPT_SECTIONS`, `assemble_system_prompt` | s10 |
| 516–692 | Compaction de contexte | budget → snip → micro → compact + `reactive_compact` | s08 (+ s11) |
| 693–978 | Mémoire | fichiers `.memory/*.md`, index, sélection, extraction, consolidation, `update_context` | **s09 (porté)** + s20 |
| 979–1040 | Récupération d'erreurs | `RecoveryState`, `with_retry`, détection prompt-too-long | s11 |
| 1041–1182 | Système de tâches | `Task`, create/claim/complete, dépendances, wrappers | s12 (+ `worktree` de s18) |
| 1183–1259 | Tâches d'arrière-plan | heuristique lenteur, worker, `task_notification` | s13 |
| 1260–1471 | Cron | matching 5 champs, validation, jobs durables, scheduler | s14 |
| 1472–1767 | Teams / MessageBus | mailboxes JSONL, `spawn_teammate_thread`, wrappers lead | s15 (+ s16/s17/s18) |
| 1768–1847 | Protocoles | `ProtocolState`, routage par `request_id`, outils lead | s16 |
| 1848–1903 | Agent autonome | `scan_unclaimed_tasks`, `idle_poll` | s17 |
| 1904–2037 | Worktrees | validation de noms, `run_git`, create/remove/keep | s18 |
| 2038–2162 | MCP | `MCPClient`, serveurs mock, `assemble_tool_pool` | s19 |
| 2163–2336 | Registres | `BUILTIN_TOOLS` (27 outils), `BUILTIN_HANDLERS` | s02 → s19 |
| 2337–2565 | Agent loop & helpers | `prepare_context`, `call_llm`, `agent_loop`, autorun cron | s20 (assemblage) |

## API publique par section

### Config & console (42–84)
- `client` (l. 48) — instance `Anthropic` (respecte `ANTHROPIC_BASE_URL`).
- `MODEL` / `PRIMARY_MODEL` / `FALLBACK_MODEL` (l. 49–51) — modèle principal (env `MODEL_ID`) et modèle de secours 529.
- Constantes (l. 55–64) — `DEFAULT_MAX_TOKENS`, `ESCALATED_MAX_TOKENS`, `MAX_RETRIES`, `MAX_CONSECUTIVE_529`, `MAX_RECOVERY_RETRIES`, `BASE_DELAY_MS`, `CONTEXT_LIMIT`, `KEEP_RECENT_TOOL_RESULTS`, `PERSIST_THRESHOLD`, `CONTINUATION_PROMPT` ; les seuils de contexte sont en **caractères JSON**, pas en tokens.
- `PROMPT` / `CLI_ACTIVE` (l. 65–66) — prompt ANSI et drapeau CLI consommés par `terminal_print` (les sessions CLI les positionnent).
- `terminal_print(text)` (l. 69) — affichage thread-safe qui redessine la ligne readline en cours de saisie.

### Sécurité fichiers (85–99)
- `WORKDIR` (l. 87) — racine du workspace (`Path.cwd()`), base de tous les confinements.
- `safe_path(p, cwd=None)` (l. 90) — résout un chemin et lève `ValueError` s'il s'échappe de la base (workspace ou worktree).

### Outils de base (100–179)
- `run_bash(command, cwd=None, run_in_background=False)` (l. 102) — shell avec timeout 120 s, sortie tronquée à 50 000 caractères ; `run_in_background` est consommé par le dispatcher.
- `run_read(path, limit=None, offset=0, cwd=None)` (l. 115) — lecture paginée avec marqueur de troncature.
- `run_write(path, content, cwd=None)` (l. 130) — écriture avec création des parents.
- `run_edit(path, old_text, new_text, cwd=None)` (l. 141) — remplacement exact et unique.
- `run_glob(pattern, cwd=None)` (l. 155) — glob confiné (re-filtrage `is_relative_to`).
- `call_tool_handler(handler, args, name)` (l. 169) — dispatch universel ; `TypeError` → message d'erreur pour le modèle.

### Todos (180–220)
- `CURRENT_TODOS` (l. 184) — liste en mémoire seulement (plan léger de session).
- `run_todo_write(todos)` (l. 210) — remplace la liste en bloc après normalisation (liste, JSON ou littéral Python).

### Permissions & hooks (221–316)
- `HOOKS` (l. 225) — registre des 4 événements `UserPromptSubmit` / `PreToolUse` / `PostToolUse` / `Stop`.
- `register_hook(event, callback)` (l. 229) / `trigger_hooks(event, *args)` (l. 233) — le premier retour non-`None` court-circuite ; pour `PreToolUse`, une chaîne = blocage.
- `DENY_LIST` / `DESTRUCTIVE` (l. 243–244) — motifs interdits / à confirmation (recherches de sous-chaînes naïves, volontairement).
- `permission_hook(block)` (l. 247) — deny list bash, confirmation des destructifs, re-validation `safe_path`, confirmation des outils MCP « deploy ».
- `log_hook` (l. 275), `large_output_hook` (l. 281), `user_prompt_hook` (l. 289), `stop_hook` (l. 295) — hooks d'observation ; enregistrés l. 309–313 (`permission_hook` **avant** `log_hook` : un outil refusé n'est jamais loggé).

### Subagent one-shot (317–414)
- `SUB_SYSTEM` / `SUB_TOOLS` / `SUB_HANDLERS` (l. 319 / 326 / 355) — 5 outils, system anti-récursion.
- `extract_text(content)` (l. 362) — concatène les blocs `text` d'une réponse.
- `has_tool_use(content)` (l. 372) — LE prédicat de continuation de la boucle (présence d'un bloc, pas `stop_reason`).
- `spawn_subagent(description)` (l. 379) — boucle isolée (30 tours max), hooks appliqués, seul le dernier texte assistant remonte.

### Skills (415–481)
- `SKILLS_DIR` / `SKILL_REGISTRY` (l. 419–420) — répertoire `skills/` et catalogue en mémoire.
- `_parse_frontmatter(text)` (l. 423) — découpe markdown en (méta YAML, corps) ; **partagé** par skills et mémoire.
- `scan_skills()` (l. 438, appelé l. 460) — repeuple le catalogue depuis `skills/*/SKILL.md`.
- `list_skills()` (l. 463) / `load_skill(name)` (l. 472) — catalogue en puces / contenu complet à la demande.

### System prompt (482–515)
- `PROMPT_SECTIONS` (l. 484) — sections statiques (identité, liste des 27 outils, workspace, note mémoire).
- `assemble_system_prompt(context)` (l. 499) — reconstruit le system prompt à chaque tour : heure courante, catalogue skills, mémoires, serveurs MCP connectés.

### Compaction de contexte (516–692)
- `TRANSCRIPT_DIR` / `TOOL_RESULTS_DIR` (l. 521–522) — transcripts JSONL et sorties persistées.
- `estimate_size(messages)` (l. 525) — approximation en caractères JSON.
- `block_type` (l. 530), `message_has_tool_use` (l. 535), `is_tool_result_message` (l. 544), `collect_tool_results` (l. 554) — prédicats de structure (protection des paires tool_use ↔ tool_result).
- `persist_large_output(tool_use_id, output)` (l. 567) — sorties > 30 000 caractères écrites sur disque, remplacées par `<persisted-output>`.
- `tool_result_budget(messages, max_bytes=200_000)` (l. 580) — couche 1 : persiste les plus gros résultats du dernier message.
- `snip_compact(messages, max_messages=50)` (l. 608) — couche 2 : coupe le milieu sans casser une paire tool_use/tool_result.
- `micro_compact(messages)` (l. 630) — couche 3 : efface les vieux tool_result (sauf les 3 derniers).
- `write_transcript(messages)` (l. 642) — assurance-vie JSONL avant toute compaction destructive.
- `summarize_history(messages)` (l. 652) — appel LLM dédié de résumé.
- `compact_history(messages)` (l. 666) — couche 4 : tout l'historique devient UN message `[Compacted]`.
- `reactive_compact(messages)` (l. 675) — compaction d'urgence post « prompt too long », résumé sous try/except avec texte de repli.

### Mémoire (693–978) — portée de s09
- `MEMORY_DIR` / `MEMORY_INDEX` / `MEMORY_TYPES` (l. 699–703) — `.memory/`, `MEMORY.md`, types `user|feedback|project|reference`.
- `write_memory_file(name, mem_type, description, body)` (l. 706) — écrit un fichier mémoire (frontmatter) et reconstruit l'index.
- `read_memory_index()` (l. 732) / `read_memory_file(filename)` (l. 740) / `list_memory_files()` (l. 748) — lecture index / fichier / liste avec métadonnées.
- `select_relevant_memories(messages, max_items=5)` (l. 766) — sélection par LLM avec repli mots-clés.
- `load_memories(messages)` (l. 838) — contenu des mémoires pertinentes en bloc `<relevant_memories>`.
- `extract_memories(messages)` (l. 853) — extraction post-tour de nouvelles mémoires (anti-doublons).
- `consolidate_memories()` (l. 917) — fusion/purge quand `CONSOLIDATE_THRESHOLD` (10) fichiers est atteint.
- `update_context(context, messages)` (l. 966) — version s20 : `MEMORY.md` (2000 premiers caractères) + état vivant MCP/teammates ; c'est le dict passé à `assemble_system_prompt`.

### Récupération d'erreurs (979–1040)
- `RecoveryState` (l. 981) — escalade, continuations, 529 consécutifs, compaction réactive (une fois), modèle courant.
- `retry_delay(attempt)` (l. 994) — backoff exponentiel plafonné + jitter.
- `with_retry(fn, state)` (l. 1000) — 429 → backoff ; 529 → backoff + bascule `FALLBACK_MODEL` ; le reste relancé.
- `is_prompt_too_long_error(e)` (l. 1032) — déclencheur de `reactive_compact` dans la boucle.

### Système de tâches (1041–1182)
- `TASKS_DIR` (l. 1045) / `Task` (l. 1050) — enregistrements JSON durables sous `.tasks/`, champ `worktree` inclus.
- `create_task` (l. 1064), `save_task` (l. 1077), `load_task` (l. 1081), `list_tasks` (l. 1085), `get_task_json` (l. 1090) — CRUD sur disque.
- `can_start(task_id)` (l. 1094) — chaque bloqueur doit exister et être `completed`.
- `claim_task(task_id, owner)` (l. 1106) / `complete_task(task_id)` (l. 1128) — revendication à triple garde / complétion avec liste des tâches débloquées.
- Wrappers outils : `run_create_task` (l. 1144), `run_list_tasks` (l. 1152), `run_get_task` (l. 1162), `run_claim_task` (l. 1169), `run_complete_task` (l. 1176).

### Tâches d'arrière-plan (1183–1259)
- `background_tasks` / `background_results` / `background_lock` (l. 1188–1190) — état partagé des workers.
- `is_slow_operation(tool_name, tool_input)` (l. 1193) — heuristique mots-clés (install, build, test, …).
- `should_run_background(tool_name, tool_input)` (l. 1204) — demande du modèle OU heuristique.
- `start_background_task(block, handlers)` (l. 1212) — worker daemon, `PostToolUse` déclenché quand même.
- `collect_background_results()` (l. 1239) — draine en blocs `<task_notification>`.

### Cron (1260–1471)
- `DURABLE_PATH` / `CronJob` / `scheduled_jobs` / `cron_queue` / `cron_lock` (l. 1264–1278) — état du scheduler.
- `cron_matches(cron_expr, dt)` (l. 1298) — matching 5 champs avec sémantique OU dom/dow du vrai cron.
- `validate_cron(cron_expr)` (l. 1354) — validation complète, messages nommant le champ fautif.
- `save_durable_jobs` (l. 1368) / `load_durable_jobs` (l. 1373) — persistance des seuls jobs durables, re-validés au rechargement.
- `schedule_job` (l. 1386) / `cancel_job` (l. 1404) — création (retourne `CronJob | str`) / annulation.
- `cron_scheduler_loop()` (l. 1414) — tick 1 s, anti-double-déclenchement par marqueur à la minute.
- `consume_cron_queue()` (l. 1435) — drainage atomique de la file.
- Wrappers outils : `run_schedule_cron` (l. 1443), `run_list_crons` (l. 1451), `run_cancel_cron` (l. 1463). Amorçage à l'import l. 1468–1469 (jobs durables + thread daemon).

### Teams / MessageBus (1472–1767)
- `MAILBOX_DIR` (l. 1476) / `MessageBus` (l. 1480) — mailboxes JSONL append-only ; `read_inbox` est **destructive** (unlink).
- `BUS` / `active_teammates` (l. 1503–1504) — instance globale et registre des teammates vivants.
- `spawn_teammate_thread(name, role, prompt)` (l. 1507) — mini-harness par teammate : 8 outils, gate d'approbation de plan, bascule worktree, fenêtre `messages[-20:]`, `idle_poll` entre les rafales. Contient le FIX(mekicode) (voir plus bas).
- `_teammate_submit_plan(from_name, plan)` (l. 1730) — crée la requête `plan_approval` et l'envoie au lead.
- Wrappers lead : `run_spawn_teammate` (l. 1744), `run_send_message` (l. 1748), `run_check_inbox` (l. 1753).

### Protocoles (1768–1847)
- `ProtocolState` (l. 1771) / `pending_requests` (l. 1781) — requêtes de protocole en cours.
- `new_request_id()` (l. 1784) — identifiant appariable `req_NNNNNN`.
- `match_response(response_type, request_id, approve)` (l. 1788) — appariement par id ET par type.
- `consume_lead_inbox(route_protocol=True)` (l. 1801) — drainage de l'inbox lead avec routage automatique des `*_response`.
- `run_request_shutdown` (l. 1815), `run_request_plan` (l. 1827), `run_review_plan` (l. 1833) — outils de protocole côté lead.

### Agent autonome (1848–1903)
- `IDLE_POLL_INTERVAL` / `IDLE_TIMEOUT` (l. 1850–1851) — 12 cycles de 5 s.
- `scan_unclaimed_tasks()` (l. 1854) — tâches pending, sans owner, démarrables.
- `idle_poll(agent_name, messages, name, role, worktree_context=None)` (l. 1866) — inbox d'abord, revendication autonome ensuite, sinon timeout.

### Worktrees (1904–2037)
- `WORKTREES_DIR` / `VALID_WT_NAME` (l. 1908–1911) — répertoire `.worktrees/` et regex de noms.
- `validate_worktree_name(name)` (l. 1914) — frontière de sécurité au niveau outil, avant git.
- `run_git(args)` (l. 1926) — wrapper subprocess → (succès, sortie tronquée).
- `log_event` (l. 1937) — journal d'audit `events.jsonl`.
- `create_worktree` (l. 1946), `bind_task_to_worktree` (l. 1970), `remove_worktree` (l. 1992, refus par défaut si changements), `keep_worktree` (l. 2017).
- Wrappers outils : `run_create_worktree` (l. 2026), `run_remove_worktree` (l. 2030), `run_keep_worktree` (l. 2034).

### MCP (2038–2162)
- `MCPClient` (l. 2042) / `mcp_clients` (l. 2065) — client mock et registre des connexions.
- `normalize_mcp_name(name)` (l. 2070) — assainissement des noms externes.
- `MOCK_SERVERS` (l. 2115) — serveurs simulés `docs` (readOnly) et `deploy` (destructif).
- `connect_mcp(name)` (l. 2121) — connexion idempotente ; outils visibles au tour suivant.
- `assemble_tool_pool()` (l. 2138) — fusion builtin + MCP (copies défensives, conversion `inputSchema` → `input_schema`, lambdas à arguments par défaut contre la capture tardive).
- `run_connect_mcp(name)` (l. 2159).

### Registres (2163–2336)
- `BUILTIN_TOOLS` (l. 2167) — les 27 outils natifs avec schémas JSON complets.
- `BUILTIN_HANDLERS` (l. 2315) — table miroir nom → fonction ; `compact` n'y figure pas (outil méta intercepté par `agent_loop`).

### Agent loop & helpers (2337–2565)
- `rounds_since_todo` / `agent_lock` (l. 2339–2340) — compteur de rappel todo et verrou qui sérialise tours humains et tours cron.
- `prepare_context(messages)` (l. 2343) — pipeline de compaction en place (`messages[:] =`), du moins au plus destructif.
- `build_user_content(results)` (l. 2355) — tool_results + notifications d'arrière-plan en un message user.
- `inject_background_notifications(messages)` (l. 2364) — second canal de livraison, en début de tour.
- `call_llm(messages, context, tools, state, max_tokens, system=None)` (l. 2373) — system vivant (ou figé) + `with_retry` avec le modèle courant.
- `agent_loop(user_input=None, messages=None, *, tools=None, handlers=None, system=None, context=None)` (l. 2388) — la boucle de synthèse paramétrable ; retourne `messages`.
- `print_turn_assistants(messages, turn_start)` (l. 2536) — rendu des textes assistants d'un tour, compatible threads.
- `cron_autorun_loop(history, context)` (l. 2547) — thread qui lance des tours d'agent autonomes quand un cron tire, sous `agent_lock`.

## FIX(mekicode) appliqués

Un seul, dans `spawn_teammate_thread` (l. 1685–1697) :

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
