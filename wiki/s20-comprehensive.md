---
title: "s20 · Agent complet"
session: 20
phase: "Intégration & synthèse"
fichier: "inspiration/learn-claude-code/s20_comprehensive/code.py"
lignes: 2124
tags: [synthese, harness, orchestration, agent-loop, hub]
prev: "s19-mcp-plugin"
next: ""
---

# s20 · Agent complet

> **En une phrase** : la session finale ne crée aucun mécanisme nouveau — elle ré-assemble les 19 mécanismes précédents autour d'une seule boucle `while True`, et montre où chacun se branche.

## Rôle dans le harness

Les 19 premières sessions ajoutent chacune UN mécanisme à la fois : c'est la bonne façon d'apprendre, mais un agent réel ne tourne jamais avec un seul mécanisme activé. Le README l'énonce clairement : « *The hard part is not piling up features. The hard part is seeing where each mechanism belongs around the loop.* » s20 est le chapitre-terminus : chaque composant pédagogique est remis à sa place dans un harness unique et exécutable.

Le problème que résout s20 est donc un problème d'**orchestration** : dans quel ordre la compaction, l'injection cron, les notifications d'arrière-plan, les hooks et l'assemblage du system prompt doivent-ils s'exécuter autour de l'appel LLM ? Le README fournit la réponse sous forme de pipeline : `user input → UserPromptSubmit hooks → injection cron/background → compaction → mémoire + skills + MCP dans le system prompt → LLM → tool_use ? → PreToolUse + permission → handlers / MCP / background → PostToolUse → tool_result → tour suivant`.

C'est exactement ainsi que fonctionne le vrai Claude Code : sa complexité n'est pas « un autre cerveau d'agent », c'est la complexité d'un harness mature. Le modèle décide et choisit les actions ; le harness organise l'environnement, les outils, les permissions, la mémoire, les équipes et les capacités externes. Le cœur, lui, n'a pas bougé depuis [[s01-agent-loop]] :

```python
while True:
    response = LLM(messages, tools)
    if not has_tool_use(response.content):
        return
    results = execute_tools(response.content)
    messages.append(tool_results)
```

Détail repris du README et codé tel quel ici : la source de CC ne fait pas confiance à `stop_reason == "tool_use"` seul — c'est la **présence concrète d'un bloc `tool_use`** dans la réponse qui sert de signal de continuation (`has_tool_use`, lignes 1016–1020).

Cette page est le « hub » du wiki : chaque zone du fichier renvoie vers la session qui a introduit le mécanisme correspondant.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu | Session d'origine |
|---|---|---|---|
| 1–12 | Docstring | présentation du chapitre final, liste des mécanismes ré-assemblés | — |
| 14–32 | Imports & environnement | `readline` optionnel, `dotenv`, client Anthropic | [[s01-agent-loop]] |
| 34–55 | Configuration globale | modèles, répertoires, budgets de contexte, prompt CLI | s01, s08, s11 |
| 58–69 | `terminal_print` | affichage thread-safe qui redessine la ligne readline | **unique à s20** |
| 71–169 | Système de tâches | `Task`, create/claim/complete, dépendances `blockedBy` | [[s12-task-system]] |
| 172–282 | Worktrees | validation de noms, `run_git`, create/remove/keep | [[s18-worktree-isolation]] |
| 285–340 | Skills | scan des `SKILL.md`, catalogue, chargement à la demande | [[s07-skill-loading]] |
| 343–374 | Assemblage du system prompt | `PROMPT_SECTIONS`, `assemble_system_prompt` | [[s10-system-prompt]] |
| 377–487 | Outils de base + todos | bash/read/write/edit/glob, `safe_path`, `todo_write` | [[s02-tool-use]], [[s05-todo-write]] |
| 490–521 | MessageBus | boîtes aux lettres JSONL append-only | [[s15-agent-teams]] |
| 523–565 | État de protocole | `ProtocolState`, routage des réponses par `request_id` | [[s16-team-protocols]] |
| 568–619 | Agent autonome | `scan_unclaimed_tasks`, `idle_poll` | [[s17-autonomous-agents]] |
| 622–840 | Thread teammate | `spawn_teammate_thread`, gate d'approbation de plan | s15 + s16 + s17 + s18 fusionnées |
| 843–871 | Protocole côté lead | request_shutdown / request_plan / review_plan | [[s16-team-protocols]] |
| 874–959 | Hooks + permissions | registre 4 événements, `permission_hook`, enregistrements | [[s03-permission]], [[s04-hooks]] |
| 962–1052 | Sous-agent one-shot | `SUB_TOOLS`, `spawn_subagent`, `has_tool_use` | [[s06-subagent]] |
| 1055–1203 | Compaction | budget → snip → micro → compact + `reactive_compact` | [[s08-context-compact]] |
| 1206–1256 | Récupération d'erreurs | `RecoveryState`, `with_retry`, détection prompt-too-long | [[s11-error-recovery]] |
| 1259–1327 | Tâches d'arrière-plan | détection d'opérations lentes, placeholder, notifications | [[s13-background-tasks]] |
| 1330–1528 | Cron | matching 5 champs, validation, jobs durables, scheduler | [[s14-cron-scheduler]] |
| 1531–1645 | MCP | `MCPClient`, serveurs mock, `assemble_tool_pool` | [[s19-mcp-plugin]] |
| 1648–1718 | Wrappers d'outils | fonctions `run_*` exposées au pool | toutes |
| 1721–1890 | Définitions d'outils | `BUILTIN_TOOLS` (27 outils), `BUILTIN_HANDLERS` | [[s02-tool-use]] |
| 1893–1907 | Contexte & mémoire | `update_context` lit `.memory/MEMORY.md` | [[s09-memory]] |
| 1910–2058 | **Boucle agent finale** | `prepare_context`, `call_llm`, `agent_loop` complet | **assemblage unique à s20** |
| 2061–2085 | Pilotage cron autonome | `print_turn_assistants`, `cron_autorun_loop` | **unique à s20** |
| 2088–2123 | CLI `__main__` | double entrée (humain + cron), verrou, inbox du lead | **unique à s20** |

Le fichier est organisé en « couches » : d'abord tous les sous-systèmes (chacun ré-importé d'une session), puis les deux tables qui les exposent au modèle (`BUILTIN_TOOLS`/`BUILTIN_HANDLERS`), et enfin la boucle qui les orchestre. Comme le dit le commentaire des lignes 1723–1724 : « *The model sees tool schemas; Python executes handlers. S20 keeps both tables explicit so every added capability is visible in one place.* »

## Constantes et configuration

- `WORKDIR = Path.cwd()` (ligne 34) : racine du workspace, base de `safe_path`.
- `MODEL = os.environ["MODEL_ID"]`, `PRIMARY_MODEL`, `FALLBACK_MODEL` (lignes 36–38) : le modèle de secours vient de [[s11-error-recovery]] (bascule après 529 répétés).
- `SKILLS_DIR`, `TRANSCRIPT_DIR`, `TOOL_RESULTS_DIR` (lignes 40–42) : répertoires des skills ([[s07-skill-loading]]), des transcripts de compaction et des sorties persistées ([[s08-context-compact]]).
- `DEFAULT_MAX_TOKENS = 8000`, `ESCALATED_MAX_TOKENS = 16000`, `MAX_RETRIES = 3`, `MAX_CONSECUTIVE_529 = 2`, `MAX_RECOVERY_RETRIES = 2`, `BASE_DELAY_MS = 500` (lignes 44–49) : budgets de [[s11-error-recovery]].
- `CONTEXT_LIMIT = 50000`, `KEEP_RECENT_TOOL_RESULTS = 3`, `PERSIST_THRESHOLD = 30000` (lignes 50–52) : seuils de compaction de [[s08-context-compact]] — notez que ce sont des **caractères JSON**, pas des tokens.
- `CONTINUATION_PROMPT` (ligne 53) : message injecté pour reprendre après un arrêt `max_tokens`.
- `PROMPT = "\033[36ms20 >> \033[0m"` et `CLI_ACTIVE = False` (lignes 54–55) : `CLI_ACTIVE` passe à `True` dans `__main__` et conditionne le comportement de `terminal_print`.

D'autres constantes vivent dans leur zone : `TASKS_DIR` (ligne 75), `WORKTREES_DIR` et `VALID_WT_NAME` (lignes 176–179), `MAILBOX_DIR` (ligne 494), `IDLE_POLL_INTERVAL = 5` / `IDLE_TIMEOUT = 60` (lignes 570–571), `HOOKS` (lignes 878–879), `DENY_LIST` / `DESTRUCTIVE` (lignes 894–895), `DURABLE_PATH` (ligne 1334), `MEMORY_DIR` / `MEMORY_INDEX` (lignes 1895–1896), `rounds_since_todo` / `agent_lock` (lignes 1912–1913).

## Les fonctions, une à une

### `terminal_print(text)` — lignes 58–69

**Unique à s20.** Quand un thread d'arrière-plan (teammate, bus, cron) veut afficher quelque chose pendant que l'utilisateur tape au prompt, un `print` brut casserait la ligne en cours de saisie. Ce helper efface la ligne (`\r\033[K`), imprime le message, puis redessine le prompt avec le tampon readline courant :

```python
def terminal_print(text: str):
    if threading.current_thread() is threading.main_thread() or not CLI_ACTIVE:
        print(text)
        return
    line = ""
    if READLINE_AVAILABLE:
        try:
            line = readline.get_line_buffer()
        except Exception:
            line = ""
    print(f"\r\033[K{text}")
    print(PROMPT + line, end="", flush=True)
```

C'est la conséquence directe du fait que s20 est le premier harness où **plusieurs threads parlent en même temps** (teammates de [[s15-agent-teams]], scheduler de [[s14-cron-scheduler]], workers de [[s13-background-tasks]]).

**Zone : système de tâches — repris de [[s12-task-system]], champ `worktree` ajouté par [[s18-worktree-isolation]].** Les tâches sont de « petits enregistrements durables » (commentaire lignes 73–74) : des fichiers JSON sous `.tasks/`, sur lesquels les sessions suivantes ont greffé propriété, dépendances, worktrees et teammates.

### `class Task` — lignes 80–88

Dataclass à 7 champs : `id`, `subject`, `description`, `status` (`pending` / `in_progress` / `completed`), `owner`, `blockedBy` (liste d'ids) et `worktree: str | None = None`. Ce dernier champ est l'intégration de [[s18-worktree-isolation]] dans le modèle de données de [[s12-task-system]] : une tâche peut être liée à un répertoire isolé.

### `_task_path(task_id)` — lignes 91–92

Helper d'une ligne : `TASKS_DIR / f"{task_id}.json"`. Repris de [[s12-task-system]] sans modification.

### `create_task(subject, description, blockedBy)` — lignes 95–104

Crée une `Task` avec id horodaté + aléa (`task_{int(time.time())}_{random.randint(0, 9999):04d}`), statut `pending`, sans propriétaire, et la persiste immédiatement. Repris de [[s12-task-system]].

### `save_task(task)` / `load_task(task_id)` — lignes 107–108 / 111–112

Sérialisation/désérialisation JSON via `asdict(task)` et `Task(**json.loads(...))`. L'état est **entièrement sur disque** : c'est ce qui permet aux teammates (threads séparés) de voir les mêmes tâches sans mémoire partagée.

### `list_tasks()` — lignes 115–117

Recharge toutes les `task_*.json` triées. Repris de [[s12-task-system]].

### `get_task_json(task_id)` — lignes 120–121

Retourne la tâche complète en JSON indenté (pour l'outil `get_task`).

### `can_start(task_id)` — lignes 124–133

La règle de dépendances, volontairement simple (commentaire lignes 125–126) : chaque bloqueur doit **exister** et être **`completed`**. Un bloqueur manquant bloque aussi — pas de dépendance fantôme. Voir [[s12-task-system]].

### `claim_task(task_id, owner)` — lignes 136–154

Revendication avec triple garde : statut `pending`, pas déjà de propriétaire, `can_start` vrai. En cas d'échec sur dépendances, le message distingue `blocked by:` (deps existantes non terminées) et `missing deps:` (deps inexistantes) — lignes 143–149. C'est la primitive que [[s17-autonomous-agents]] exploite pour la revendication autonome.

### `complete_task(task_id)` — lignes 157–169

Passe la tâche à `completed` puis calcule la liste des tâches **débloquées** par cette complétion (lignes 163–164) et l'ajoute au retour : le modèle apprend immédiatement quel travail devient disponible.

**Zone : worktrees — reprise de [[s18-worktree-isolation]].** Le commentaire des lignes 174–175 résume le risque : « les noms de worktrees deviennent des chemins du système de fichiers », donc la validation est stricte et partagée par create/remove/keep.

### `validate_worktree_name(name)` — lignes 182–190

Refuse vide, `.`, `..`, et tout ce qui ne matche pas `VALID_WT_NAME = ^[A-Za-z0-9._-]{1,64}$` (ligne 179). C'est une frontière de sécurité **au niveau outil**, pas une délégation à git (commentaire lignes 212–214 : « do it before git sees the name »).

### `run_git(args)` — lignes 193–199

Wrapper `subprocess.run(["git"] + args, cwd=WORKDIR, ..., timeout=30)` qui retourne `(succès, sortie tronquée à 5000 caractères)`. Repris de [[s18-worktree-isolation]].

### `log_event(event_type, worktree_name, task_id)` — lignes 203–208

Journal d'audit append-only `.worktrees/events.jsonl` : chaque create/remove/keep laisse une trace horodatée.

### `create_worktree(name, task_id)` — lignes 211–232

Valide le nom, vérifie que la tâche existe si `task_id` est fourni, refuse si le chemin existe déjà, puis `git worktree add <path> -b wt/<name> HEAD`. Si `task_id` est présent, appelle `bind_task_to_worktree` : c'est le **point de jonction tâches ↔ worktrees** introduit par [[s18-worktree-isolation]] et conservé ici.

### `bind_task_to_worktree(task_id, worktree_name)` — lignes 235–238

Écrit le nom du worktree dans le champ `worktree` de la tâche et sauvegarde. Quand un teammate revendiquera cette tâche, ses outils fichiers basculeront dans ce répertoire (voir `spawn_teammate_thread`).

### `_count_worktree_changes(path)` — lignes 241–251

Compte fichiers modifiés (`git status --porcelain`) et commits non poussés (`git log @{push}..HEAD --oneline`). Retourne `(-1, -1)` si la vérification échoue — valeur sentinelle exploitée par `remove_worktree`.

### `remove_worktree(name, discard_changes)` — lignes 254–274

Suppression **refusée par défaut** s'il reste des changements : c'est le garde-fou de [[s18-worktree-isolation]]. Si `_count_worktree_changes` retourne `-1`, le code refuse aussi (« Cannot verify status ») : l'incertitude est traitée comme un danger. Supprime ensuite worktree puis branche `wt/<name>`.

### `keep_worktree(name)` — lignes 277–282

Ne supprime rien : journalise l'événement `keep` et indique la branche à examiner. L'alternative explicite à la suppression forcée.

**Zone : skills — reprise de [[s07-skill-loading]].** Le principe de divulgation progressive est conservé : seul le **catalogue** (nom + description) entre dans le system prompt ; le contenu complet est chargé à la demande par l'outil `load_skill`.

### `_parse_frontmatter(text)` — lignes 290–300

Découpe un fichier markdown en `(métadonnées YAML, corps)` via `text.split("---", 2)` ; tolère le YAML invalide (`meta = {}`). Repris de [[s07-skill-loading]].

### `scan_skills()` — lignes 303–321 (appelé ligne 324)

Vide puis repeuple `SKILL_REGISTRY` (ligne 287) en parcourant `skills/*/SKILL.md`. Le nom vient du frontmatter (`meta.get("name", directory.name)`), la description du frontmatter ou de la première ligne du fichier. **Point d'intégration s20** : le scan s'exécute une seule fois à l'import (ligne 324), et `assemble_system_prompt` réinjecte le catalogue à **chaque tour** — le mécanisme de [[s07-skill-loading]] devient une section vivante du prompt de [[s10-system-prompt]].

### `list_skills()` — lignes 327–332

Formate le catalogue en puces `- nom: description`, ou `(no skills found)`.

### `load_skill(name)` — lignes 335–340

Retourne le contenu complet du `SKILL.md`, ou la liste des skills disponibles si le nom est inconnu — l'erreur est elle-même utile au modèle.

### `PROMPT_SECTIONS` — lignes 345–357

Dictionnaire des sections statiques du system prompt : identité (« You are a coding agent. Act, don't explain. »), liste des 27 outils, workspace, note sur la mémoire. Repris de [[s10-system-prompt]], avec la liste d'outils étendue à tout le pool de s20.

### `assemble_system_prompt(context)` — lignes 360–374

Le system prompt est **reconstruit à chaque tour** à partir de l'état vivant (commentaire lignes 361–362) :

```python
sections = [PROMPT_SECTIONS["identity"],
            PROMPT_SECTIONS["tools"],
            PROMPT_SECTIONS["workspace"]]
sections.append(f"Current time: {datetime.now().isoformat(timespec='seconds')}")
sections.append("Skills catalog:\n" + list_skills() +
                "\nUse load_skill(name) when a skill is relevant.")
if context.get("memories"):
    sections.append(f"Relevant memories:\n{context['memories']}")
mcp_names = list(mcp_clients.keys())
if mcp_names:
    sections.append(f"Connected MCP servers: {', '.join(mcp_names)}")
return "\n\n".join(sections)
```

C'est ici que **quatre sessions convergent** : la structure en sections vient de [[s10-system-prompt]], le catalogue de skills de [[s07-skill-loading]], les souvenirs de [[s09-memory]] (via `update_context`), et l'état MCP de [[s19-mcp-plugin]]. L'heure courante est injectée pour que le modèle puisse calculer des expressions cron correctes ([[s14-cron-scheduler]]).

**Zone : outils de base — repris de [[s02-tool-use]], avec le paramètre `cwd` ajouté par [[s18-worktree-isolation]].**

### `safe_path(p, cwd)` — lignes 379–386

Résout le chemin par rapport à `cwd or WORKDIR` et lève `ValueError` s'il s'échappe de la base (`is_relative_to`). Le commentaire (lignes 380–382) explique le partage des rôles : les outils fichiers restent confinés au workspace ou au worktree ; **bash reste puissant à dessein** et c'est le hook de permission ([[s03-permission]]) qui le contrôle.

### `run_bash(command, cwd, run_in_background)` — lignes 389–398

`subprocess.run(shell=True, timeout=120)`, sortie tronquée à 50 000 caractères. Subtilité : `run_in_background` figure dans la signature mais est **ignoré ici** — il est « consommé par le dispatcher » (commentaire ligne 391), c'est-à-dire par `should_run_background` dans la boucle ([[s13-background-tasks]]).

### `run_read(path, limit, offset, cwd)` — lignes 401–412

Lecture paginée avec marqueur `... (N more lines)` quand le fichier est tronqué. Repris de [[s02-tool-use]].

### `run_write(path, content, cwd)` — lignes 415–422

Crée les répertoires parents puis écrit. Repris de [[s02-tool-use]].

### `run_edit(path, old_text, new_text, cwd)` — lignes 425–435

Remplacement **exact et unique** (`text.replace(old_text, new_text, 1)`) avec erreur si le texte est introuvable — le pattern Edit de Claude Code en miniature.

### `run_glob(pattern, cwd)` — lignes 438–448

`glob.glob(pattern, root_dir=base)` avec re-filtrage `is_relative_to(base)` pour neutraliser les motifs qui s'échappent (`../...`).

### `call_tool_handler(handler, args, name)` — lignes 451–457

Le point de dispatch universel : `handler(**(args or {}))` avec capture des `TypeError` (arguments invalides envoyés par le modèle) transformés en message d'erreur retourné au modèle plutôt qu'en crash. Tout passe par lui : outils du lead, des sous-agents, des teammates, et workers d'arrière-plan.

### `_normalize_todos(todos)` — lignes 460–478

Robustesse face au modèle : accepte une liste, une chaîne JSON, ou même un littéral Python (`ast.literal_eval` en repli, lignes 464–468), puis valide chaque item (`content`, `status` ∈ {pending, in_progress, completed}). Durcissement s20 du `todo_write` de [[s05-todo-write]].

### `run_todo_write(todos)` — lignes 480–487

Remplace `CURRENT_TODOS` (ligne 77) en bloc — la liste de todos est volontairement **en mémoire seulement**, contrairement aux tâches durables : c'est la distinction des « deux couches de planification » du README (todo = plan léger de session, task graph = coordination inter-sessions).

**Zone : MessageBus — repris de [[s15-agent-teams]].** Commentaire lignes 492–493 : la communication d'équipe passe par des mailboxes JSONL append-only, « inspectables sur disque ».

### `class MessageBus` — lignes 498–517

Deux méthodes :

- `send(from_agent, to_agent, content, msg_type, metadata)` (lignes 499–508) : append d'une ligne JSON dans `.mailboxes/{to_agent}.jsonl`, avec trace `terminal_print` (adaptation s20 : les threads peuvent émettre sans casser le prompt).
- `read_inbox(agent)` (lignes 510–517) : lit toutes les lignes **puis supprime le fichier** (`inbox.unlink()`) — lecture destructive, les messages ne sont délivrés qu'une fois.

L'instance globale `BUS` et le registre `active_teammates` sont aux lignes 520–521.

**Zone : protocole — reprise de [[s16-team-protocols]].**

### `class ProtocolState` — lignes 525–533

Dataclass d'une requête de protocole : `request_id`, `type` (`shutdown` ou `plan_approval`), `sender`, `target`, `status`, `payload`, `created_at`. Stockée dans `pending_requests` (ligne 536).

### `new_request_id()` — lignes 539–540

`req_{random:06d}` — l'identifiant qui rend chaque réponse appariable.

### `match_response(response_type, request_id, approve)` — lignes 543–553

Apparie une réponse à sa requête **par `request_id` et par type** : une `shutdown_response` ne peut pas approuver une `plan_approval` (lignes 549–552). Le commentaire (lignes 544–545) explicite l'invariant : « one protocol reply cannot approve a different pending request ». Cœur de [[s16-team-protocols]].

### `consume_lead_inbox(route_protocol)` — lignes 556–565

Vide l'inbox du lead et, si `route_protocol`, route automatiquement tout message dont le type finit par `_response` vers `match_response`. **Intégration s20** : cette fonction est appelée à deux endroits du CLI (`run_check_inbox` ligne 1706 et `__main__` ligne 2111), si bien que les états de protocole se mettent à jour même quand le modèle ne consulte pas explicitement son inbox.

**Zone : agent autonome — reprise de [[s17-autonomous-agents]].**

### `scan_unclaimed_tasks()` — lignes 574–582

Parcourt les fichiers de tâches et retourne celles qui sont `pending`, sans `owner`, et démarrables (`can_start`). Lit le JSON brut (dicts) plutôt que des `Task` — suffisant pour le scan.

### `idle_poll(agent_name, messages, name, role, worktree_context)` — lignes 585–619

La boucle d'oisiveté d'un teammate : 12 cycles de 5 s (`IDLE_TIMEOUT // IDLE_POLL_INTERVAL`). Priorités, dans l'ordre (commentaire lignes 588–589) :

1. **Inbox d'abord** : un `shutdown_request` reçoit immédiatement une `shutdown_response` approuvée et retourne `"shutdown"` ; tout autre message est injecté comme `<inbox>…</inbox>` et retourne `"work"`.
2. **Tâches non revendiquées ensuite** : la première tâche libre est revendiquée ; si elle a un worktree, le chemin est écrit dans `worktree_context["path"]` (lignes 610–614) — c'est l'**adaptation s18→s20** : la revendication autonome de [[s17-autonomous-agents]] déclenche la bascule de répertoire de [[s18-worktree-isolation]].
3. Sinon, après 60 s : `"timeout"`, et le thread se termine.

### `spawn_teammate_thread(name, role, prompt)` — lignes 624–828

La plus grosse fonction du fichier : un mini-harness complet par teammate, fusion de quatre sessions. Refuse les doublons (`active_teammates`), puis définit :

- `protocol_ctx = {"waiting_plan": None}` (ligne 630) : le **gate d'approbation de plan** de [[s16-team-protocols]]. Le commentaire (lignes 628–629) est explicite : après `submit_plan`, le teammate « ne prend plus de pas modèle/outil » tant que le lead n'a pas répondu.
- `handle_inbox_message` (lignes 635–651) : répond aux `shutdown_request` (retourne `True` = arrêt), traite les `plan_approval_response` en levant le gate (`waiting_plan = None`) et en injectant `[Plan approved]` ou `[Plan rejected] …`.
- `run()` (lignes 653–824), le corps du thread :
  - `wt_ctx = {"path": None}` et `_wt_cwd()` (lignes 654–660) : toutes les fermetures `_run_bash` / `_run_read` / `_run_write` (lignes 662–669) passent ce `cwd` aux outils de base — « une fois la tâche à worktree revendiquée, tous les outils fichiers du teammate tournent de façon transparente dans ce répertoire isolé » (commentaire lignes 657–658).
  - `_run_claim_task` (lignes 680–686) recharge la tâche après revendication et positionne `wt_ctx["path"]` ; `_run_complete_task` (lignes 688–691) le remet à `None` : la liaison répertoire suit le cycle de vie de la tâche.
  - `sub_tools` (lignes 694–735) : 8 outils seulement — bash, read_file, write_file, send_message, **submit_plan**, list_tasks, claim_task, complete_task. Un teammate n'a ni cron, ni MCP, ni spawn : la hiérarchie des capacités est délibérée.
  - La boucle externe `while True` (ligne 747) ré-injecte une balise `<identity>` quand l'historique est court (lignes 748–751) — un teammate qui vient de se réveiller se rappelle qui il est.
  - La boucle interne `for _ in range(10)` (ligne 753) borne les tours modèle par rafale de travail. Avant chaque appel : drainage de l'inbox, et si `waiting_plan` est actif, **sommeil + continue** (lignes 762–766) — pas d'appel LLM pendant le gate.
  - Appel modèle avec fenêtre glissante `messages[-20:]` (ligne 775) : les teammates n'ont pas de pipeline de compaction, juste une fenêtre.
  - Traitement des `tool_use` (lignes 783–801) : `submit_plan` est intercepté **avant** le dispatch normal, l'id `req_…` est extrait par regex du retour, et dès que `waiting_plan` est posé, `break` — « les blocs tool_use suivants de la même réponse appartiennent à l'après-approbation » (commentaire lignes 799–800).
  - Après la rafale : `idle_poll` ([[s17-autonomous-agents]]) ; `shutdown` ou `timeout` terminent le thread.
  - Épilogue (lignes 813–824) : extraction du dernier texte assistant comme résumé, envoi au lead via `BUS.send(..., "result")`, retrait de `active_teammates`.

Le thread est démarré en daemon (ligne 827) : la mort du processus principal emporte tout le monde.

### `_teammate_submit_plan(from_name, plan)` — lignes 831–840

Crée la `ProtocolState` `plan_approval`, l'enregistre dans `pending_requests`, envoie le plan au lead avec le `request_id` en métadonnées, et retourne `Plan submitted (req_…)` — c'est ce texte que le teammate parse pour fermer son gate.

### `run_request_shutdown(teammate)` — lignes 845–853

Côté lead : crée la requête `shutdown` et l'envoie. L'arrêt est **négocié**, pas imposé — le teammate répond avant de s'arrêter ([[s16-team-protocols]]).

### `run_request_plan(teammate, task)` — lignes 856–858

Simple message demandant un plan ; c'est le teammate qui crée la requête formelle via `submit_plan`.

### `run_review_plan(request_id, approve, feedback)` — lignes 861–871

Met à jour la `ProtocolState` puis envoie la `plan_approval_response` avec `approve` et le feedback. C'est ce message qui lèvera le gate du teammate.

**Zone : hooks + permissions — fusion de [[s03-permission]] et [[s04-hooks]].** Le commentaire des lignes 876–877 donne la thèse architecturale : les hooks vivent **hors** des handlers d'outils ; la boucle peut ajouter permission, journalisation et comportement d'arrêt « sans modifier chaque outil individuellement ». Le README insiste : « *Permission is not hardcoded into the tool execution line. It is a PreToolUse hook.* »

### `register_hook(event, callback)` / `trigger_hooks(event, *args)` — lignes 882–883 / 886–891

Le registre `HOOKS` (lignes 878–879) connaît 4 événements : `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`.

```python
def trigger_hooks(event: str, *args):
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:
            return result
    return None
```

Sémantique cruciale : le **premier retour non-`None` court-circuite la chaîne**. Pour `PreToolUse`, retourner une chaîne = bloquer l'outil avec ce message comme `tool_result`. Repris de [[s04-hooks]].

### `permission_hook(block)` — lignes 898–923

Le système de [[s03-permission]] recâblé en hook, **étendu pour s20** :

```python
if block.name == "bash":
    command = block.input.get("command", "")
    for pattern in DENY_LIST:
        if pattern in command:
            return f"Permission denied: '{pattern}' is on the deny list"
    if any(token in command for token in DESTRUCTIVE):
        ...
        choice = input("  Allow? [y/N] ").strip().lower()
```

Trois familles de contrôles : (1) bash — deny list dure (`rm -rf /`, `sudo`, …) puis confirmation interactive pour les motifs destructeurs (`rm `, `> /etc/`, `chmod 777`) ; (2) `write_file` / `edit_file` — re-validation `safe_path` du chemin (lignes 912–917) ; (3) **nouveau en s20** : tout outil MCP dont le nom contient `deploy` exige une confirmation utilisateur (lignes 918–922) — la frontière de permission de s03 est étendue aux outils externes de [[s19-mcp-plugin]].

### `log_hook(block)` — lignes 926–928

Affiche `[HOOK] {nom}` et retourne `None` (laisse passer). Démonstrateur minimal de [[s04-hooks]].

### `large_output_hook(block, output)` — lignes 931–935

`PostToolUse` : avertit si une sortie dépasse 100 000 caractères. Observation sans blocage.

### `user_prompt_hook(query)` — lignes 938–940

`UserPromptSubmit` : trace l'arrivée d'une entrée utilisateur.

### `stop_hook(messages)` — lignes 943–952

`Stop` : compte les `tool_result` de toute la conversation et affiche la statistique — le point d'audit de fin de tour.

Les enregistrements (lignes 955–959) fixent l'ordre : `permission_hook` **avant** `log_hook` sur `PreToolUse` — un outil refusé n'est donc jamais loggé par `log_hook` (court-circuit).

**Zone : sous-agent one-shot — reprise de [[s06-subagent]].**

### `SUB_SYSTEM` / `SUB_TOOLS` / `SUB_HANDLERS` — lignes 964–968 / 971–997 / 1000–1004

Le sous-agent reçoit 5 outils (bash, read_file, write_file, edit_file, glob), un system prompt qui interdit la récursion (« Do not spawn more agents ») et exige un résumé final concis.

### `extract_text(content)` — lignes 1007–1013

Concatène les blocs `text` d'une réponse. Utilisé pour les résumés (sous-agent, compaction).

### `has_tool_use(content)` — lignes 1016–1020

```python
def has_tool_use(content) -> bool:
    # Do not rely on stop_reason alone; the concrete tool_use block is the
    # continuation signal used by the loop.
    return any(getattr(block, "type", None) == "tool_use"
               for block in content)
```

LE prédicat de [[s01-agent-loop]] : la présence d'un bloc, pas le `stop_reason`, décide de la continuation.

### `spawn_subagent(description)` — lignes 1023–1052

Boucle agent isolée (max 30 tours) avec ses propres `messages` — le contexte intermédiaire est jeté, seul le **dernier texte assistant** remonte au parent. **Adaptation s20** : contrairement à [[s06-subagent]], chaque outil du sous-agent passe lui aussi par `trigger_hooks("PreToolUse"/"PostToolUse")` (lignes 1036–1042) — la frontière de permission s'applique aussi aux agents délégués.

**Zone : compaction — reprise de [[s08-context-compact]]** (réutilisée par [[s09-memory]] et [[s11-error-recovery]]). Le commentaire des lignes 1057–1059 décrit la stratégie en couches : réduire d'abord les sorties d'outils surdimensionnées, puis tailler les vieilles plages de messages, et n'appeler le modèle pour un résumé que si le contexte reste trop gros ou si le modèle demande explicitement `compact`.

### `estimate_size(messages)` — lignes 1060–1061

`len(json.dumps(messages, default=str))` : approximation en caractères, comparée à `CONTEXT_LIMIT` (50 000).

### `block_type(block)` — lignes 1063–1064

Helper tolérant : lit `type` que le bloc soit un dict (résultats fabriqués par le harness) ou un objet SDK (réponses du modèle). Cette dualité dict/objet traverse tout le fichier.

### `message_has_tool_use(message)` / `is_tool_result_message(message)` — lignes 1067–1073 / 1076–1083

Prédicats de structure : message assistant contenant un `tool_use` / message user contenant un `tool_result`. Servent à protéger les **paires tool_use ↔ tool_result** pendant les découpes — casser une paire provoque une erreur API.

### `collect_tool_results(messages)` — lignes 1086–1095

Liste tous les blocs `tool_result` avec leurs indices `(message, bloc, bloc)`.

### `persist_large_output(tool_use_id, output)` — lignes 1098–1106

Si la sortie dépasse `PERSIST_THRESHOLD` (30 000), elle est écrite dans `.task_outputs/tool-results/{id}.txt` et remplacée par un `<persisted-output>` contenant le chemin + 2 000 caractères d'aperçu. Rien n'est perdu : le modèle peut relire le fichier.

### `tool_result_budget(messages, max_bytes=200_000)` — lignes 1109–1130

Première couche du pipeline : si les `tool_result` du **dernier message** dépassent 200 ko cumulés, les plus gros sont persistés sur disque un à un jusqu'à repasser sous le budget. Subtilité d'adaptation : la version s08 sautait explicitement les blocs sous `PERSIST_THRESHOLD` ; la version s20 ne le fait plus — `persist_large_output` les retourne alors inchangés, et si tous les blocs sont petits mais nombreux, le dépassement est silencieusement toléré.

### `snip_compact(messages, max_messages=50)` — lignes 1133–1149

Deuxième couche : conserve la tête (3 messages) et la queue, remplace le milieu par `[snipped N messages]`. Les ajustements des lignes 1137–1143 déplacent les bornes pour ne **jamais couper une paire tool_use/tool_result** : si le dernier message de tête est un assistant à `tool_use`, la tête s'étend pour englober ses résultats ; si la queue commence par un `tool_result`, elle recule d'un cran pour inclure le `tool_use` correspondant. Repris de [[s08-context-compact]] quasiment à l'identique.

### `micro_compact(messages)` — lignes 1152–1159

Troisième couche : tous les `tool_result` sauf les `KEEP_RECENT_TOOL_RESULTS = 3` derniers sont remplacés par `[Earlier tool result compacted. Re-run if needed.]` (s'ils dépassent 120 caractères). L'information reste récupérable : il suffit de relancer l'outil.

### `write_transcript(messages)` — lignes 1162–1168

Avant toute compaction destructive, l'historique complet est sauvé en JSONL dans `.transcripts/` — l'assurance-vie du contexte.

### `summarize_history(messages)` — lignes 1171–1180

Appel LLM dédié (sans outils, 2 000 tokens max) sur les 80 000 premiers caractères de la conversation, avec consigne de préserver objectif, découvertes, fichiers modifiés, travail restant et contraintes utilisateur.

### `compact_history(messages)` — lignes 1183–1187

Quatrième couche (la plus destructive) : transcript + résumé, et l'historique entier devient UN message `[Compacted]\n\n{summary}`.

### `reactive_compact(messages)` — lignes 1190–1203

La compaction **d'urgence**, déclenchée par l'erreur « prompt too long » ([[s11-error-recovery]]). Différences avec `compact_history` : elle conserve les ~5 derniers messages bruts après le résumé (avec le même ajustement de paire tool_use/tool_result, lignes 1198–1201), et — **durcissement s20** — le résumé est enveloppé dans un `try/except` (lignes 1193–1196) : si même l'appel de résumé échoue (le contexte est peut-être trop gros pour être résumé), un texte de repli est utilisé plutôt que de planter la récupération.

**Zone : récupération d'erreurs — reprise de [[s11-error-recovery]].**

### `class RecoveryState` — lignes 1208–1214

Cinq champs d'état par conversation : `has_escalated` (escalade max_tokens déjà tentée), `recovery_count` (continuations), `consecutive_529`, `has_attempted_reactive_compact` (la compaction réactive n'est tentée qu'**une fois**), `current_model` (peut basculer vers `FALLBACK_MODEL`).

### `retry_delay(attempt)` — lignes 1217–1219

Backoff exponentiel plafonné à 32 s, plus un jitter aléatoire de 0–25 % — le pattern standard anti-troupeau.

### `with_retry(fn, state)` — lignes 1222–1249

Jusqu'à 3 tentatives. Classification par **inspection du texte d'erreur** (`"429" in msg`, `"overloaded" in msg`…) : 429 → backoff simple ; 529 → backoff + compteur, et après `MAX_CONSECUTIVE_529 = 2` échecs consécutifs, bascule sur `FALLBACK_MODEL` si configuré (lignes 1239–1242). Toute autre exception est relancée immédiatement — on ne réessaie que ce qui est réessayable.

### `is_prompt_too_long_error(e)` — lignes 1252–1256

Détecte les trois formulations de l'erreur de contexte (`prompt…long`, `context_length_exceeded`, `max_context_window`). Déclencheur de `reactive_compact` dans la boucle.

**Zone : tâches d'arrière-plan — reprise de [[s13-background-tasks]].** Commentaire lignes 1261–1262 : les outils lents retournent un placeholder immédiat ; la vraie sortie revient plus tard comme `task_notification`.

### `is_slow_operation(tool_name, tool_input)` — lignes 1269–1276

Heuristique par mots-clés (`install`, `build`, `test`, `pytest`, `make`…) sur les commandes bash uniquement.

### `should_run_background(tool_name, tool_input)` — lignes 1279–1282

Un bash part en arrière-plan si le modèle l'a **demandé** (`run_in_background: true`) OU si l'heuristique le juge lent. Le choix explicite du modèle et la protection automatique du harness coexistent.

### `start_background_task(block, handlers)` — lignes 1285–1307

Génère un id `bg_NNNN`, enregistre la tâche `running` sous `background_lock`, et lance un thread daemon `worker` qui exécute le handler, **déclenche quand même `PostToolUse`** (ligne 1294), puis dépose le résultat dans `background_results`. Le placeholder retourné au modèle est fabriqué par l'appelant (`agent_loop`, lignes 2035–2036).

### `collect_background_results()` — lignes 1310–1327

Draine les tâches `completed` et les formate en blocs XML `<task_notification>` (id, statut, commande, résumé tronqué à 200 caractères). Deux consommateurs : `build_user_content` et `inject_background_notifications` (voir plus bas).

**Zone : cron — reprise de [[s14-cron-scheduler]].** Commentaire lignes 1332–1333 : les jobs vivent hors de l'historique de conversation ; quand un job se déclenche, il devient un prompt planifié réinjecté dans la même boucle agent.

### `class CronJob` — lignes 1337–1344

Dataclass : `id`, `cron` (expression 5 champs), `prompt`, `recurring`, `durable`. Les jobs durables survivent au redémarrage via `.scheduled_tasks.json`.

### `_cron_field_matches(field, value)` — lignes 1352–1364

Matching récursif d'un champ : `*`, pas `*/n`, listes `a,b,c`, plages `a-b`, valeur exacte.

### `cron_matches(cron_expr, dt)` — lignes 1367–1386

Matching complet avec la **sémantique OU dom/dow du vrai cron** (lignes 1380–1386) : si jour-du-mois ET jour-de-semaine sont tous deux restreints, il suffit que l'un des deux matche. La conversion `dow_val = (dt.weekday() + 1) % 7` (ligne 1372) traduit le lundi=0 de Python en dimanche=0 de cron.

### `_validate_cron_field(field, lo, hi)` / `validate_cron(cron_expr)` — lignes 1389–1418 / 1421–1431

Validation complète à la création (bornes par champ, pas > 0, plages ordonnées) avec messages d'erreur nommant le champ fautif — le modèle peut corriger son expression.

### `save_durable_jobs()` / `load_durable_jobs()` — lignes 1434–1436 / 1439–1448

Persistance des seuls jobs `durable`. Au rechargement, chaque job est **re-validé** (ligne 1445) : un fichier corrompu ne réinstalle pas de job invalide.

### `schedule_job(cron, prompt, recurring, durable)` — lignes 1451–1464

Valide, crée le `CronJob`, l'enregistre sous `cron_lock`, persiste si durable. Retourne le job ou la chaîne d'erreur (union de types discriminée par `isinstance` dans `run_schedule_cron`).

### `cancel_job(job_id)` — lignes 1467–1474

Retrait + re-persistance si le job était durable.

### `cron_scheduler_loop()` — lignes 1477–1493

Le thread daemon (démarré ligne 1528) : tick chaque seconde, et anti-double-déclenchement par marqueur **à la minute** (`_last_fired[job.id] != marker`, ligne 1485) — 60 ticks par minute, mais un seul déclenchement. Les jobs non récurrents sont retirés au premier tir (lignes 1488–1491).

### `consume_cron_queue()` — lignes 1496–1500

Vide atomiquement `cron_queue` sous verrou. Deux consommateurs : `agent_loop` (pendant un tour) et `cron_autorun_loop` (entre les tours).

### `run_schedule_cron` / `run_list_crons` / `run_cancel_cron` — lignes 1503–1508 / 1511–1520 / 1523–1524

Wrappers exposés au modèle. `run_list_crons` annote chaque job `[recurring|one-shot, durable|session]`. L'amorçage (lignes 1527–1528) recharge les jobs durables et démarre le scheduler **à l'import**.

**Zone : MCP — reprise de [[s19-mcp-plugin]].** Commentaire lignes 1533–1534 : MCP est modélisé comme des « outils à liaison tardive » — connexion d'abord, puis fusion des outils découverts dans le pool normal sous le nom `mcp__server__tool`.

### `class MCPClient` — lignes 1535–1555

Client mock pédagogique : `register(tool_defs, handlers)` enregistre les définitions, `call_tool(tool_name, args)` dispatch avec capture d'exception en `MCP error: …`. L'état global `mcp_clients` (ligne 1558) est consulté par `assemble_system_prompt` et `assemble_tool_pool`.

### `normalize_mcp_name(name)` — lignes 1563–1565

Remplace tout caractère hors `[a-zA-Z0-9_-]` par `_` : les noms de serveurs/outils externes sont assainis avant d'entrer dans l'espace de noms d'outils.

### `_mock_server_docs()` / `_mock_server_deploy()` — lignes 1568–1584 / 1587–1605

Deux serveurs simulés : `docs` (2 outils readOnly : `search`, `get_version`) et `deploy` (`trigger`, marqué « destructive — requires approval in real CC », et `status`). Le marquage destructif de `deploy.trigger` est précisément ce que `permission_hook` intercepte (lignes 918–922). Registre `MOCK_SERVERS` lignes 1608–1611.

### `connect_mcp(name)` — lignes 1614–1626

Idempotent (refuse la double connexion), instancie le client via la factory, et retourne au modèle la liste des outils découverts. Les nouveaux outils ne sont utilisables qu'au **tour suivant**, quand `assemble_tool_pool` est ré-exécuté.

### `assemble_tool_pool()` — lignes 1629–1645

Le point d'assemblage dynamique du pool, ré-exécuté à chaque tour de boucle :

```python
def assemble_tool_pool() -> tuple[list[dict], dict]:
    """Merge builtin tools + all MCP tools into one pool."""
    tools = list(BUILTIN_TOOLS)
    handlers = dict(BUILTIN_HANDLERS)
    for server_name, mcp_client in mcp_clients.items():
        safe_server = normalize_mcp_name(server_name)
        for tool_def in mcp_client.tools:
            safe_tool = normalize_mcp_name(tool_def["name"])
            prefixed = f"mcp__{safe_server}__{safe_tool}"
            tools.append({
                "name": prefixed,
                "description": tool_def.get("description", ""),
                "input_schema": tool_def.get("inputSchema", {}),
            })
            handlers[prefixed] = (
                lambda *, c=mcp_client, t=tool_def["name"], **kw: c.call_tool(t, kw))
    return tools, handlers
```

Détails : copies défensives de `BUILTIN_TOOLS`/`BUILTIN_HANDLERS` (les listes globales ne sont jamais mutées) ; conversion `inputSchema` (convention MCP) → `input_schema` (convention API Anthropic) ; et surtout la lambda à **arguments par défaut** `c=mcp_client, t=tool_def["name"]` qui fige les valeurs courantes de la boucle — sans cela, toutes les lambdas pointeraient sur le dernier serveur/outil itéré (piège classique de capture tardive en Python). Voir [[s19-mcp-plugin]].

### `run_create_worktree` / `run_remove_worktree` / `run_keep_worktree` — lignes 1650–1657

Wrappers d'une ligne exposant la zone worktree au pool. Repris de [[s18-worktree-isolation]] sans modification.

### `run_create_task(subject, description, blockedBy)` — lignes 1662–1667

Wrapper de `create_task` avec affichage console et mention des dépendances dans le retour.

### `run_list_tasks()` — lignes 1670–1677

Liste formatée `id: sujet [statut] (wt:nom)` — l'annotation worktree rend la liaison s12↔s18 visible pour le modèle.

### `run_get_task` / `run_claim_task` / `run_complete_task` — lignes 1680–1684 / 1686–1690 / 1692–1696

Wrappers qui convertissent `FileNotFoundError` en message d'erreur lisible (id de tâche inventé par le modèle → réponse exploitable, pas un crash).

### `run_spawn_teammate(name, role, prompt)` — lignes 1698–1699

Délègue à `spawn_teammate_thread`.

### `run_send_message(to, content)` — lignes 1701–1703

Le lead poste sur le bus ([[s15-agent-teams]]).

### `run_check_inbox()` — lignes 1705–1715

Draine l'inbox du lead **avec routage protocole** (`route_protocol=True`) et formate chaque message avec son type et son `request_id` — le modèle voit `req:req_000123` et peut appeler `review_plan` avec le bon identifiant.

### `run_connect_mcp(name)` — lignes 1717–1718

Wrapper de `connect_mcp`.

### `BUILTIN_TOOLS` — lignes 1725–1869

La table des **27 outils natifs**, schémas JSON complets : 5 outils fichiers/shell ([[s02-tool-use]]), `todo_write` ([[s05-todo-write]]), `task` ([[s06-subagent]]), `load_skill` ([[s07-skill-loading]]), `compact` ([[s08-context-compact]]), 5 outils de tâches ([[s12-task-system]]), 3 outils cron ([[s14-cron-scheduler]]), 3 outils d'équipe ([[s15-agent-teams]]), 3 outils de protocole ([[s16-team-protocols]]), 3 outils worktree ([[s18-worktree-isolation]]), `connect_mcp` ([[s19-mcp-plugin]]). À noter : la description de `schedule_cron` (lignes 1800–1802) enseigne au modèle comment fabriquer un rappel one-shot (« compute the target minute and set recurring=false ») — la doc d'outil comme canal de pédagogie du modèle.

### `BUILTIN_HANDLERS` — lignes 1871–1890

La table miroir nom → fonction Python. Remarquez `"task": spawn_subagent` et `"load_skill": load_skill` : certains handlers sont les fonctions de zone elles-mêmes, d'autres des wrappers `run_*`. `compact` n'y figure **pas** : il est intercepté directement dans `agent_loop` (ligne 2019) car il doit manipuler `messages`, ce qu'un handler ordinaire ne voit pas.

### `update_context(context, messages)` — lignes 1899–1907

Reprise de [[s09-memory]], enrichie pour s20 : relit `.memory/MEMORY.md` (2 000 premiers caractères) à chaque tour, et ajoute l'état vivant `connected_mcp` et `active_teammates`. C'est le dict passé à `assemble_system_prompt`.

**Zone : boucle agent finale — l'assemblage UNIQUE à s20.** Tout ce qui précède converge ici.

### `prepare_context(messages)` — lignes 1916–1923

**Unique à s20** : le pipeline de compaction de [[s08-context-compact]], ordonné et appliqué **en place** avant chaque appel LLM :

```python
def prepare_context(messages: list) -> list:
    # Every LLM turn enters through the same context budget pipeline.
    messages[:] = tool_result_budget(messages)
    messages[:] = snip_compact(messages)
    messages[:] = micro_compact(messages)
    if estimate_size(messages) > CONTEXT_LIMIT:
        messages[:] = compact_history(messages)
    return messages
```

L'ordre est du moins destructif au plus destructif : persister les grosses sorties → couper le milieu → effacer les vieux résultats → résumer tout. L'affectation par tranche `messages[:] =` est essentielle : la liste `history` est partagée avec `__main__` et `cron_autorun_loop`, donc elle doit être mutée, pas remplacée.

### `build_user_content(results)` — lignes 1926–1932

**Unique à s20** : fusionne les `tool_result` du tour avec les `<task_notification>` d'arrière-plan arrivées entre-temps, en un seul message user (commentaire lignes 1927–1928 : les deux « reviennent au modèle comme contenu côté user, conformément à la boucle de feedback tool_result »). Intégration [[s13-background-tasks]] → [[s01-agent-loop]].

### `inject_background_notifications(messages)` — lignes 1935–1939

**Unique à s20** : le second canal de livraison — si des résultats d'arrière-plan sont prêts en **début** de tour (avant l'appel LLM), ils sont injectés comme message user autonome. Avec `build_user_content`, cela garantit que les notifications sont livrées au plus tôt, qu'il y ait eu des outils exécutés ou non.

### `call_llm(messages, context, tools, state, max_tokens)` — lignes 1942–1952

**Unique à s20** dans sa composition : assemble le system prompt vivant ([[s10-system-prompt]]) puis enveloppe l'appel API dans `with_retry` ([[s11-error-recovery]]) avec le modèle courant de `state` (qui a pu basculer sur le fallback) :

```python
def call_llm(messages: list, context: dict, tools: list,
             state: RecoveryState, max_tokens: int):
    system = assemble_system_prompt(context)
    return with_retry(
        lambda: client.messages.create(
            model=state.current_model,
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=max_tokens),
        state)
```

### `agent_loop(messages, context)` — lignes 1955–2058

LA fonction de synthèse. Un cycle complet (commentaire lignes 1962–1963 : « inject scheduled/background work, prepare context, call the model, execute tool_use blocks, append tool_results, repeat ») :

**1. Injections avant LLM** (lignes 1964–1975) :

```python
fired = consume_cron_queue()
for job in fired:
    messages.append({"role": "user",
                     "content": f"[Scheduled] {job.prompt}"})
    ...
inject_background_notifications(messages)

if rounds_since_todo >= 3:
    messages.append({"role": "user",
                     "content": "<reminder>Update your todos.</reminder>"})
    rounds_since_todo = 0
```

Trois sessions injectent ici : les prompts cron de [[s14-cron-scheduler]], les notifications de [[s13-background-tasks]], et le rappel todo de [[s05-todo-write]] (compteur global `rounds_since_todo`).

**2. Préparation du contexte** (lignes 1977–1979) : `prepare_context` (compaction), `update_context` (mémoire/MCP/teammates), et **ré-assemblage du pool d'outils** `tools, handlers = assemble_tool_pool()` — c'est cette ligne, exécutée à chaque tour, qui fait apparaître les outils MCP au tour suivant un `connect_mcp` ([[s19-mcp-plugin]]).

**3. Appel LLM et récupération** (lignes 1981–2003) :

```python
try:
    response = call_llm(messages, context, tools, state, max_tokens)
except Exception as e:
    if is_prompt_too_long_error(e) and not state.has_attempted_reactive_compact:
        messages[:] = reactive_compact(messages)
        state.has_attempted_reactive_compact = True
        continue
    messages.append({"role": "assistant", "content": [
        {"type": "text", "text": f"[Error] {type(e).__name__}: {e}"}]})
    return

if response.stop_reason == "max_tokens":
    if not state.has_escalated:
        max_tokens = ESCALATED_MAX_TOKENS
        state.has_escalated = True
        ...
        continue
    messages.append({"role": "assistant", "content": response.content})
    if state.recovery_count < MAX_RECOVERY_RETRIES:
        messages.append({"role": "user", "content": CONTINUATION_PROMPT})
        state.recovery_count += 1
        continue
    return
```

Toute la machinerie de [[s11-error-recovery]] est branchée ici : prompt-too-long → `reactive_compact` (une seule fois) ; `max_tokens` → escalade à 16 000 puis, si insuffisant, prompt de continuation (2 fois max). Les erreurs non récupérables deviennent un message assistant `[Error] …` visible et la boucle rend la main.

**4. Sortie ou exécution** (lignes 2005–2010) : reset des budgets, append de la réponse, et si pas de `tool_use` → `trigger_hooks("Stop", messages)` puis `return` — la condition de sortie de [[s01-agent-loop]], décorée par [[s04-hooks]].

**5. Dispatch des outils** (lignes 2012–2053), quatre chemins par bloc :

```python
if block.name == "compact":
    messages[:] = compact_history(messages)
    messages.append({"role": "user",
                     "content": "[Compacted. Continue with summarized context.]"})
    compacted_now = True
    break

blocked = trigger_hooks("PreToolUse", block)
if blocked:
    results.append({..., "content": str(blocked)})
    continue

if should_run_background(block.name, block.input):
    bg_id = start_background_task(block, handlers)
    output = (f"[Background task {bg_id} started] "
              "Result will arrive as a task_notification.")
    results.append({..., "content": output})
    continue

handler = handlers.get(block.name)
output = call_tool_handler(handler, block.input, block.name)
trigger_hooks("PostToolUse", block, output)
```

Dans l'ordre : (a) `compact` est un **outil méta** traité hors table — il remplace tout l'historique et `break` abandonne les blocs restants (ils disparaissent avec l'historique compacté, donc pas de tool_result orphelin) ; (b) le couple hooks/permission de [[s03-permission]]+[[s04-hooks]] — un blocage produit un `tool_result` d'erreur, le modèle est informé ; (c) le détour arrière-plan de [[s13-background-tasks]] avec placeholder immédiat ; (d) le dispatch normal de [[s02-tool-use]] suivi de `PostToolUse`. Les lignes 2047–2050 entretiennent le compteur todo de [[s05-todo-write]].

**6. Retour au modèle** (ligne 2058) : `messages.append({"role": "user", "content": build_user_content(results)})` — résultats + notifications, et tour suivant.

### `print_turn_assistants(messages, turn_start)` — lignes 2061–2067

**Unique à s20** : après un tour complet, affiche tous les textes assistants produits depuis `turn_start`, via `terminal_print` (compatible threads). Le rendu est découplé de la boucle.

### `cron_autorun_loop(history, context)` — lignes 2070–2085

**Unique à s20** — la pièce qui rend l'agent réellement *long-running* :

```python
def cron_autorun_loop(history: list, context: dict):
    while True:
        time.sleep(1)
        fired = consume_cron_queue()
        if not fired:
            continue
        with agent_lock:
            turn_start = len(history)
            for job in fired:
                history.append({"role": "user",
                                "content": f"[Scheduled] {job.prompt}"})
                ...
            agent_loop(history, context)
            context.update(update_context(context, history))
            print_turn_assistants(history, turn_start)
```

Pendant que l'utilisateur ne tape rien, ce thread daemon surveille `cron_queue` et, quand un job tire, **lance un tour d'agent complet tout seul** sur le même `history`, sous `agent_lock`. [[s14-cron-scheduler]] avait introduit l'idée ; s20 la fait cohabiter avec la saisie humaine : le verrou sérialise les deux entrées (humain et cron) sur la même conversation, et `terminal_print` évite de massacrer la ligne en cours de frappe.

### Bloc `__main__` — lignes 2088–2123

Le CLI final : active `CLI_ACTIVE`, crée `history` et `context` **partagés**, démarre `cron_autorun_loop` en daemon, puis boucle sur `input(PROMPT)` :

```python
trigger_hooks("UserPromptSubmit", query)
turn_start = len(history)
history.append({"role": "user", "content": query})
with agent_lock:
    agent_loop(history, context)
    context = update_context(context, history)
    print_turn_assistants(history, turn_start)

inbox = consume_lead_inbox(route_protocol=True)
if inbox:
    ...
    history.append({"role": "user",
                    "content": f"[Inbox]\n{inbox_text}"})
```

Chaque saisie traverse d'abord le hook `UserPromptSubmit` ([[s04-hooks]]), puis un tour verrouillé. **Après** le tour, l'inbox du lead est drainée : les messages des teammates (résultats, demandes d'approbation de plan de [[s16-team-protocols]]) sont routés vers les états de protocole ET ajoutés à `history` comme `[Inbox]` — le modèle les verra au prochain tour, sans relance automatique. La boucle se quitte sur `q`, `exit`, chaîne vide, EOF ou Ctrl-C.

## Ce qui change par rapport à [[s19-mcp-plugin]]

s19 avait élagué son corps pédagogique pour se concentrer sur MCP ; s20 **restaure tout** et n'ajoute aucun mécanisme nouveau — seulement l'orchestration. Le tableau du README :

- **Pool d'outils** : built-in + MCP, mais avec les outils de s01–s18 réintégrés → 27 outils natifs (s19 n'exposait que le sous-ensemble multi-agents + MCP).
- **Permission** : omise dans s19 → réinstallée comme hook `PreToolUse` (lignes 898–923), étendue aux outils MCP destructeurs.
- **Hooks** : omis dans s19 → les 4 événements `UserPromptSubmit` / `PreToolUse` / `PostToolUse` / `Stop` reviennent (lignes 874–959).
- **Todo** : omis → `todo_write` + rappel tous les 3 tours (lignes 460–487, 1972–1975).
- **Skills** : omis → catalogue dans le system prompt + `load_skill` (lignes 285–340).
- **Compaction** : omise → pipeline pré-LLM `prepare_context` + outil `compact` + `reactive_compact` (lignes 1055–1203, 1916–1923, 2019–2024).
- **Récupération d'erreurs** : simple try/except dans s19 → retry/escalade/continuation/compaction réactive complets (lignes 1206–1256, 1981–2003).
- **Arrière-plan** : omis → thread d'opérations lentes + `task_notification` (lignes 1259–1327).
- **Cron** : omis → scheduler daemon + jobs durables + **`cron_autorun_loop`** qui déclenche des tours autonomes (lignes 1330–1528, 2070–2085).
- **Multi-agents / worktrees / MCP** : conservés de s15–s19, avec les teammates qui utilisent les outils de base dans leurs répertoires isolés.
- **Nouveau pur s20** : `terminal_print` (affichage multi-thread), `prepare_context` / `build_user_content` / `inject_background_notifications` / `call_llm` (les quatre fonctions d'orchestration), `print_turn_assistants`, `cron_autorun_loop`, et le CLI à double entrée sous `agent_lock`.

## Pièges et détails d'implémentation

- **Le fichier fait 2123 lignes physiques**, pas 1780 : le décompte « 1780 » de la carte du wiki correspond aux lignes non vides. Les références de cette page utilisent les numéros de lignes physiques (ceux d'un éditeur).
- **`compact` n'est pas dans `BUILTIN_HANDLERS`** : il est dans `BUILTIN_TOOLS` (le modèle le voit) mais intercepté par `agent_loop` (ligne 2019) avant le dispatch, car il doit réécrire `messages` — un handler ordinaire ne reçoit que ses arguments. Le `break` qui suit abandonne les `tool_use` restants du même tour ; c'est sain uniquement parce que l'historique entier (y compris l'assistant à `tool_use`) vient d'être remplacé par le résumé.
- **Ordre des hooks = politique** : `permission_hook` est enregistré avant `log_hook` (lignes 956–957) et `trigger_hooks` court-circuite au premier retour non-`None` — un outil refusé n'est donc jamais loggé. Inverser les deux lignes changerait le comportement observable.
- **Les vérifications de permission sont des recherches de sous-chaînes naïves** : `"sudo" in command` bloque aussi `visudo` ; `"rm "` (avec espace) déclenche la confirmation pour n'importe quelle commande contenant ces trois caractères. Volontairement simple — le vrai Claude Code analyse les commandes.
- **Deux canaux pour les notifications d'arrière-plan** : `inject_background_notifications` (avant LLM, message autonome) et `build_user_content` (avec les tool_results du tour). Sans le second, une notification arrivée pendant l'exécution des outils attendrait un tour de plus.
- **`tool_result_budget` s20 a perdu un garde de s08** : la version de [[s08-context-compact]] sautait les blocs sous `PERSIST_THRESHOLD` ; ici ils sont passés à `persist_large_output` qui les retourne inchangés — si le dépassement vient de nombreux petits blocs, le budget est silencieusement dépassé.
- **`messages[:] =` partout dans `prepare_context` et la boucle** : la liste `history` est partagée entre `__main__` et `cron_autorun_loop` ; une réaffectation simple (`messages = …`) casserait ce partage. Même logique pour `agent_lock`, qui sérialise les tours humains et les tours cron sur la même conversation.
- **La lecture d'inbox est destructive** (`inbox.unlink()`, ligne 516) : un message lu mais non traité (crash entre lecture et traitement) est perdu. Acceptable pour la pédagogie, rédhibitoire en production.
- **Le gate de plan d'un teammate fige aussi les tool_use frères** : après `submit_plan`, les blocs `tool_use` suivants de la même réponse sont ignorés (`break`, lignes 798–801) — ils ne reçoivent donc jamais de `tool_result`, mais le teammate sort de sa boucle interne avant le prochain appel API, et l'inbox/identité réinjectées masquent l'historique bancal derrière la fenêtre `messages[-20:]`.
- **Le scheduler cron tire à la minute, pas à la seconde** : tick de 1 s mais marqueur `_last_fired` au format `%Y-%m-%d %H:%M` — un job ne tire qu'une fois par minute correspondante, même avec 60 ticks.

## Liens

- Session précédente : [[s19-mcp-plugin]]
- Sessions liées — Fondamentaux : [[s01-agent-loop]] (la boucle et `has_tool_use`), [[s02-tool-use]] (outils de base et dispatch), [[s03-permission]] (deny list et confirmations), [[s04-hooks]] (les 4 points d'extension), [[s05-todo-write]] (todos + rappel), [[s06-subagent]] (`task` one-shot), [[s07-skill-loading]] (catalogue + `load_skill`)
- Sessions liées — Contexte & mémoire : [[s08-context-compact]] (pipeline de compaction), [[s09-memory]] (`.memory/MEMORY.md` via `update_context`), [[s10-system-prompt]] (assemblage par sections), [[s11-error-recovery]] (`with_retry`, escalade, compaction réactive)
- Sessions liées — Tâches & temps : [[s12-task-system]] (graphe de tâches durable), [[s13-background-tasks]] (placeholder + `task_notification`), [[s14-cron-scheduler]] (matching cron, jobs durables, autorun)
- Sessions liées — Multi-agents : [[s15-agent-teams]] (`MessageBus`, teammates), [[s16-team-protocols]] (`request_id`, approbation de plan), [[s17-autonomous-agents]] (`idle_poll`, revendication autonome)
- Sessions liées — Intégration : [[s18-worktree-isolation]] (worktrees liés aux tâches), [[s19-mcp-plugin]] (`assemble_tool_pool`, outils `mcp__…`)
