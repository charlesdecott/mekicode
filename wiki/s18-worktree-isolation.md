---
title: "s18 · Isolation par worktree"
session: 18
phase: "Intégration & synthèse"
fichier: "inspiration/learn-claude-code/s18_worktree_isolation/code.py"
lignes: 997
tags: [git-worktree, isolation, parallélisme, event-log]
prev: "s17-autonomous-agents"
next: "s19-mcp-plugin"
---

# s18 · Isolation par worktree

> **En une phrase** : chaque tâche peut être liée à un git worktree (répertoire + branche dédiés) ; quand un teammate réclame une tâche liée, ses outils `bash`/`read_file`/`write_file` basculent automatiquement dans ce répertoire — deux agents ne s'écrasent plus mutuellement leurs fichiers.

## Rôle dans le harness

En [[s17-autonomous-agents]], Alice et Bob travaillent dans le **même répertoire**. Le README pose le scénario : Alice refactore le module auth, Bob refactore la page de login ; tous deux appellent `write_file("config.py", ...)` et s'écrasent mutuellement — sans rollback propre, impossible de dire à qui appartient quel changement. s15–s17 ont résolu « qui fait quoi » (task system) et « comment communiquer » (message bus), mais pas « **où** travailler ».

La réponse est `git worktree` : plusieurs répertoires de travail indépendants sur un même dépôt, chacun avec sa propre branche. Alice travaille dans `.worktrees/auth/` (branche `wt/auth`), Bob dans `.worktrees/ui/` (branche `wt/ui`). Le slogan du chapitre : *"Separate directories, no conflicts"* — *"Tasks own the goal, worktrees own the directory, bound by ID."* La liaison est minimale : un champ `worktree` sur la dataclass `Task`. Lier ne change **pas** le statut de la tâche — elle reste `pending`, et c'est l'auto-claim de s17 qui la fera passer `in_progress` ; le Lead peut donc pré-créer tâches et worktrees, les teammates s'orchestrent seuls en parallèle, chacun dans son répertoire.

Le cycle de vie complet est couvert : création (`create_worktree`, avec validation du nom contre la traversée de chemin), liaison (`bind_task_to_worktree`), bascule de cwd côté teammate (dict `wt_ctx`), puis nettoyage en fin de tâche — `remove_worktree` (qui **refuse** par défaut s'il reste des changements non commités) ou `keep_worktree` (conservation pour revue manuelle). Chaque opération est journalisée dans `.worktrees/events.jsonl`.

Dans le vrai Claude Code (d'après le README), il existe deux chemins : **EnterWorktree** (la session courante bascule dedans via `process.chdir()` — un vrai changement de répertoire processus, pas une suggestion de prompt) et **l'isolation AgentTool** (`isolation: "worktree"` crée un worktree pour le sous-agent et enveloppe son exécution avec `cwdOverridePath`, sans toucher au cwd global). CC ne lie pas worktree et tâche par un champ : ce sont deux systèmes indépendants reliés par la compréhension contextuelle de l'agent — le champ `Task.worktree` est une simplification pédagogique.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–27 | Docstring | changements vs s17, topologie ASCII (`.worktrees/auth/`, `.tasks/`, `events.jsonl`) |
| 29–49 | Imports & init | + `re` (validation des noms), client `Anthropic`, `MODEL` |
| 51–145 | Task System (s12 + s18) | dataclass `Task` **+ champ `worktree`**, CRUD, `can_start`, `claim_task`, `complete_task` |
| 148–263 | **Worktree System (nouveau)** | `VALID_WT_NAME`, `validate_worktree_name`, `run_git`, `log_event`, `create_worktree`, `bind_task_to_worktree`, `_count_worktree_changes`, `remove_worktree`, `keep_worktree` |
| 266–298 | Prompt Assembly (s10) | `PROMPT_SECTIONS` (17 outils), mémoïsation |
| 301–337 | Outils de base | `safe_path`, `run_bash`, `run_read`, `run_write` — **tous gagnent un paramètre `cwd`** |
| 341–370 | MessageBus (s15) | inchangé |
| 372–421 | Protocol State (s16/s17) | `ProtocolState`, `match_response`, `consume_lead_inbox` |
| 424–484 | Agent autonome (s17) | `scan_unclaimed_tasks`, `idle_poll` (+ info worktree dans l'auto-claim) |
| 487–700 | Thread teammate | `spawn_teammate_thread` avec **`wt_ctx` et bascule de cwd**, `_teammate_submit_plan` |
| 703–739 | Outils protocole Lead (s16) | `run_request_shutdown`, `run_request_plan`, `run_review_plan` |
| 742–753 | **Outils worktree Lead (nouveau)** | `run_create_worktree`, `run_remove_worktree`, `run_keep_worktree` |
| 756–807 | Handlers Lead | `run_create_task` … `run_check_inbox` |
| 810–920 | Définitions d'outils | `TOOLS` (**17** outils, +3), `TOOL_HANDLERS` |
| 923–933 | Contexte | `MEMORY_INDEX`, `update_context` (s09) |
| 936–966 | Boucle agent | `agent_loop` du Lead |
| 969–997 | REPL | identique à s17 (injection inbox) |

## Constantes et configuration

- `WORKTREES_DIR = WORKDIR / ".worktrees"` (lignes 150–151) — **nouveau** : racine de tous les worktrees, créée au démarrage. Le journal `events.jsonl` y vit aussi.
- `VALID_WT_NAME = re.compile(r'^[A-Za-z0-9._-]{1,64}$')` (ligne 153) — **nouveau** : caractères autorisés dans un nom de worktree. Même règle que le vrai CC (`worktree.ts:76-84`, d'après le README).
- `TASKS_DIR` (lignes 53–54), `PROMPT_SECTIONS` (lignes 268–277, liste désormais 17 outils), `MAILBOX_DIR` (lignes 343–344), `BUS` / `active_teammates` (lignes 369–370), `pending_requests` (ligne 385), `IDLE_POLL_INTERVAL` / `IDLE_TIMEOUT` (lignes 426–427), `MEMORY_DIR` / `MEMORY_INDEX` (lignes 925–926) — repris de [[s17-autonomous-agents]].
- `TOOLS` (lignes 812–906) : 17 définitions — les 14 de s17 + `create_worktree`, `remove_worktree`, `keep_worktree` (lignes 888–905, commentées `# s18 new: worktree tools`). `TOOL_HANDLERS` (lignes 908–920) enregistre les trois nouveaux handlers.

## Les fonctions, une à une

### `Task` (dataclass) — lignes 57–65
**Modifiée** : un septième champ apparaît.

```python
@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str
    owner: str | None
    blockedBy: list[str]
    worktree: str | None = None      # s18: bound worktree name
```

La valeur par défaut `None` rend le champ optionnel : les anciens JSON de tâches (sans `worktree`) restent désérialisables par `Task(**json.loads(...))`. C'est tout le « binding » : un nom de worktree rangé dans la tâche.

### `_task_path` — lignes 68–69, `create_task` — lignes 72–81, `save_task` — lignes 84–85, `load_task` — lignes 88–89, `list_tasks` — lignes 92–94
CRUD des tâches, repris de [[s12-task-system]] sans modification (`create_task` ne pose jamais `worktree` : la liaison est une étape séparée).

### `get_task_json(task_id)` — lignes 97–99
Renommage de `get_task` (s17) pour éviter la collision de nom avec l'outil. Comportement identique.

### `can_start(task_id)` — lignes 102–109, `claim_task(task_id, owner)` — lignes 112–130, `complete_task(task_id)` — lignes 133–145
Repris de [[s17-autonomous-agents]] sans modification (gardes statut/owner/dépendances, calcul des tâches débloquées).

### `validate_worktree_name(name)` — lignes 156–165
**Nouvelle.** Première ligne de défense du cycle de vie : refuser les noms dangereux **avant** de toucher au système de fichiers ou à git.

```python
def validate_worktree_name(name: str) -> str | None:
    """Return error message if invalid, None if valid."""
    if not name:
        return "Worktree name cannot be empty"
    if name == "." or name == "..":
        return f"'{name}' is not a valid worktree name"
    if not VALID_WT_NAME.match(name):
        return (f"Invalid worktree name '{name}': "
                "only letters, digits, dots, underscores, dashes (1-64 chars)")
    return None
```

- Convention de retour inversée : `None` = valide, chaîne = message d'erreur (prêt à renvoyer au LLM).
- Trois rejets : nom vide ; `.` et `..` (traversée de répertoire — `..` passerait pourtant la regex puisque les points sont autorisés, d'où le test explicite) ; tout caractère hors `[A-Za-z0-9._-]` ou longueur > 64. Les `/`, `\`, espaces et autres sont donc exclus : `WORKTREES_DIR / name` ne peut pas s'échapper de `.worktrees/`.
- Le vrai CC applique la même règle de slug (rejet de `./..`, alphabet `[a-zA-Z0-9._-]`).

### `run_git(args)` — lignes 168–177
**Nouvelle.** Wrapper git qui retourne un couple `(ok, output)` au lieu d'une simple chaîne.

```python
def run_git(args: list[str]) -> tuple[bool, str]:
    """Run git command. Return (ok, output)."""
    try:
        r = subprocess.run(["git"] + args, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=30)
        out = (r.stdout + r.stderr).strip()
        out = out[:5000] if out else "(no output)"
        return r.returncode == 0, out
    except subprocess.TimeoutExpired:
        return False, "Error: git timeout"
```

- `["git"] + args` sans `shell=True` : pas d'interprétation shell, donc pas d'injection possible via les arguments — contraste voulu avec `run_bash`.
- Le booléen `ok` (`returncode == 0`) permet aux appelants de **ne journaliser un événement qu'après un succès git réel** : le log reflète l'état effectif, pas l'intention (point souligné par le README).
- Timeout 30 s, sortie tronquée à 5 000 caractères, toujours exécuté depuis `WORKDIR` (le dépôt principal).

### `log_event(event_type, worktree_name, task_id)` — lignes 180–186
**Nouvelle.** Journal d'audit en append-only :

```python
def log_event(event_type: str, worktree_name: str, task_id: str = ""):
    """Append a lifecycle event to events.jsonl."""
    event = {"type": event_type, "worktree": worktree_name,
             "task_id": task_id, "ts": time.time()}
    events_file = WORKTREES_DIR / "events.jsonl"
    with open(events_file, "a") as f:
        f.write(json.dumps(event) + "\n")
```

Trois types d'événements dans le fichier : `create`, `remove`, `keep`. Une ligne JSON par événement, horodatée — même format que les boîtes aux lettres de [[s15-agent-teams]]. Le README précise la limite : c'est un journal pour audit manuel ; une vraie reprise après crash exigerait un index ou un scan `git worktree list`.

### `create_worktree(name, task_id)` — lignes 189–204
**Nouvelle.** La création, cœur du cycle de vie :

```python
def create_worktree(name: str, task_id: str = "") -> str:
    """Create a git worktree with a dedicated branch. Optionally bind to a task."""
    err = validate_worktree_name(name)
    if err:
        return f"Error: {err}"
    path = WORKTREES_DIR / name
    if path.exists():
        return f"Worktree '{name}' already exists at {path}"
    ok, result = run_git(["worktree", "add", str(path), "-b", f"wt/{name}", "HEAD"])
    if not ok:
        return f"Git error: {result}"
    if task_id:
        bind_task_to_worktree(task_id, name)
    log_event("create", name, task_id)
    print(f"  \033[33m[worktree] created: {name} at {path}\033[0m")
    return f"Worktree '{name}' created at {path}"
```

Lecture ligne à ligne :
- lignes 191–193 : validation du nom d'abord — toute erreur est retournée comme texte d'outil, jamais levée ;
- lignes 194–196 : idempotence grossière — si le répertoire existe déjà, on ne tente rien ;
- ligne 197 : `git worktree add <path> -b wt/<name> HEAD` — crée le répertoire **et** une branche neuve `wt/{name}` à partir du HEAD courant. Une branche par worktree : les commits de chaque agent restent séparés et fusionnables. (Le vrai CC utilise `.claude/worktrees/`, des branches `worktree-{slug}` et `git worktree add -B` en préférant `origin/<defaultBranch>` à HEAD.) ;
- lignes 198–199 : si git échoue (pas un dépôt, branche existante…), l'erreur git brute est remontée au LLM et **rien n'est journalisé** ;
- lignes 200–201 : liaison optionnelle à une tâche — la création et la liaison se font en un seul appel d'outil si `task_id` est fourni ;
- ligne 202 : `log_event("create", ...)` seulement après succès.

### `bind_task_to_worktree(task_id, worktree_name)` — lignes 207–212
**Nouvelle.** La liaison minimale :

```python
def bind_task_to_worktree(task_id: str, worktree_name: str):
    """Write worktree field to task. Keep status as pending for auto-claim."""
    task = load_task(task_id)
    task.worktree = worktree_name
    save_task(task)
    print(f"  \033[33m[bind] {task.subject} → worktree:{worktree_name}\033[0m")
```

Le point de design crucial est dans la docstring : **on n'écrit que le champ `worktree`, le statut reste `pending`**. La tâche demeure visible par `scan_unclaimed_tasks` de [[s17-autonomous-agents]] : un teammate en IDLE la réclamera naturellement, et c'est le claim qui la passera `in_progress`. Lier ≠ assigner. Attention : `load_task` lève `FileNotFoundError` si `task_id` n'existe pas — non rattrapée (voir Pièges).

### `_count_worktree_changes(path)` — lignes 215–226
**Nouvelle.** Mesure ce qu'on perdrait en supprimant un worktree :

```python
def _count_worktree_changes(path: Path) -> tuple[int, int]:
    """Count uncommitted files and commits in a worktree."""
    try:
        r1 = subprocess.run(["git", "status", "--porcelain"],
                            cwd=path, capture_output=True, text=True, timeout=10)
        files = len([l for l in r1.stdout.strip().splitlines() if l.strip()])
        r2 = subprocess.run(["git", "log", "@{push}..HEAD", "--oneline"],
                            cwd=path, capture_output=True, text=True, timeout=10)
        commits = len([l for l in r2.stdout.strip().splitlines() if l.strip()])
        return files, commits
    except Exception:
        return -1, -1
```

- `git status --porcelain` exécuté **dans le worktree** (`cwd=path`) : une ligne par fichier modifié/non suivi.
- `git log @{push}..HEAD --oneline` : commits locaux non poussés. Subtilité importante : sur une branche `wt/{name}` fraîchement créée par `-b`, il n'y a **pas d'upstream configuré** — `@{push}` échoue, mais comme `subprocess.run` ne lève pas d'exception sur code retour non nul, `stdout` est vide et `commits` vaut silencieusement 0 (voir Pièges).
- Le sentinel `(-1, -1)` signale « impossible de vérifier » (exception réelle : timeout, répertoire disparu…) et déclenche un refus prudent côté `remove_worktree`.

### `remove_worktree(name, discard_changes)` — lignes 229–253
**Nouvelle.** La suppression, protégée par un garde-fou :

```python
def remove_worktree(name: str, discard_changes: bool = False) -> str:
    """Remove worktree. Refuses if uncommitted changes unless discard_changes."""
    err = validate_worktree_name(name)
    if err:
        return err
    path = WORKTREES_DIR / name
    if not path.exists():
        return f"Worktree '{name}' not found"
    if not discard_changes:
        files, commits = _count_worktree_changes(path)
        if files < 0:
            return (f"Cannot verify worktree '{name}' status. "
                    "Use discard_changes=true to force removal.")
        if files > 0 or commits > 0:
            return (f"Worktree '{name}' has {files} uncommitted file(s) "
                    f"and {commits} unpushed commit(s). "
                    "Use discard_changes=true to force removal, "
                    "or keep_worktree to preserve for review.")
    ok1, _ = run_git(["worktree", "remove", str(path), "--force"])
    if not ok1:
        return f"Failed to remove worktree directory for '{name}'"
    run_git(["branch", "-D", f"wt/{name}"])
    log_event("remove", name)
    ...
    return f"Worktree '{name}' removed"
```

- Le garde-fou ne s'exécute que si `discard_changes` est faux : par défaut, **refus** s'il reste des fichiers non commités ou des commits non poussés, avec un message qui propose les deux issues (`discard_changes=true` ou `keep_worktree`). Le doute (`files < 0`) est traité comme un refus — sécurité par défaut.
- Une fois le garde passé (ou contourné), la suppression utilise quand même `--force` : la vérification est faite en Python, git n'a plus à re-vérifier.
- `git branch -D wt/{name}` supprime la branche associée — son code retour est ignoré (si la branche a déjà disparu, tant pis).
- `log_event("remove", name)` après le succès uniquement. La suppression ne touche **pas** au statut de la tâche liée : pas d'auto-complete, c'est `complete_task` du teammate qui fait foi (choix explicite du README).

### `keep_worktree(name)` — lignes 256–263
**Nouvelle.** L'alternative à la suppression :

```python
def keep_worktree(name: str) -> str:
    """Keep worktree for manual review. Branch preserved."""
    err = validate_worktree_name(name)
    if err:
        return err
    log_event("keep", name)
    print(f"  \033[36m[worktree] kept: {name}\033[0m")
    return f"Worktree '{name}' kept for review (branch: wt/{name})"
```

Aucune opération git : « garder » consiste à **ne rien faire** et à le consigner. L'événement `keep` dans le journal documente la décision ; le répertoire et la branche `wt/{name}` restent disponibles pour revue et merge manuels. (La fonction ne vérifie même pas que le worktree existe.)

### `assemble_system_prompt` — lignes 280–286, `get_system_prompt` — lignes 292–298
Repris de [[s10-system-prompt]] sans modification (la mémoïsation par hash de contexte est toujours là).

### `safe_path(p, cwd=None)` — lignes 303–308
**Modifiée** : un paramètre `cwd` optionnel remplace le `WORKDIR` codé en dur.

```python
def safe_path(p: str, cwd: Path = None) -> Path:
    base = cwd or WORKDIR
    path = (base / p).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"Path escapes workspace: {p}")
    return path
```

Quand un teammate travaille dans un worktree, la base de résolution **et** la borne anti-évasion deviennent le worktree lui-même : le teammate isolé ne peut pas écrire hors de son répertoire via `../`.

### `run_bash(command, cwd=None)` — lignes 311–318, `run_read(path, limit, cwd=None)` — lignes 321–328, `run_write(path, content, cwd=None)` — lignes 331–337
**Modifiées** : même ajout du paramètre `cwd` (`cwd or WORKDIR`). C'est le mécanisme d'isolation effectif : il suffit de passer le chemin du worktree pour que commandes shell, lectures et écritures s'y déroulent. Le Lead, lui, continue d'appeler ces fonctions sans `cwd` (ses handlers `TOOL_HANDLERS` pointent directement sur elles) : il reste dans `WORKDIR`.

### `MessageBus` (classe) — lignes 347–366
Repris de [[s15-agent-teams]] sans modification.

### `ProtocolState` — lignes 374–382, `new_request_id` — lignes 388–389, `match_response` — lignes 392–409
Repris de [[s16-team-protocols]] sans modification.

### `consume_lead_inbox(route_protocol=True)` — lignes 412–421
Repris de [[s17-autonomous-agents]] sans modification (routage des `*_response` vers `match_response`, retour de tous les messages). Notez le déplacement dans le fichier : la fonction vit désormais à côté du protocole, plus près de `match_response`.

### `scan_unclaimed_tasks()` — lignes 430–439
Repris de [[s17-autonomous-agents]] sans modification (filtre `pending` + sans owner + `can_start`).

### `idle_poll(agent_name, messages, name, role)` — lignes 442–484
Repris de [[s17-autonomous-agents]] avec **un ajout** : lors de l'auto-claim, si la tâche est liée à un worktree, le chemin de travail est injecté dans le message `<auto-claimed>` :

```python
            result = claim_task(task_data["id"], agent_name)
            if "Claimed" in result:
                wt_info = ""
                if task_data.get("worktree"):
                    wt_path = WORKTREES_DIR / task_data["worktree"]
                    wt_info = f"\nWork directory: {wt_path}"
                messages.append({"role": "user",
                    "content": f"<auto-claimed>Task {task_data['id']}: "
                               f"{task_data['subject']}{wt_info}</auto-claimed>"})
```

Le LLM du teammate apprend ainsi *où* il travaille — information purement déclarative ici, car la bascule technique du cwd passe par `wt_ctx` (ci-dessous). Subtilité : l'auto-claim en IDLE appelle `claim_task` directement (pas `_run_claim_task`), donc **ne met pas à jour `wt_ctx`** — voir Pièges.

### `spawn_teammate_thread(name, role, prompt)` — lignes 489–688
**Modifiée** : le thread teammate gagne la mécanique de bascule de répertoire. Le prompt système (lignes 493–496) dit désormais *"If a task has a worktree, work in that directory."* ; `handle_inbox_message` (lignes 498–519) est repris de s17 sans modification. Le nouveau cœur est en tête de `run()` :

```python
    def run():
        # Track current worktree for this teammate's cwd
        wt_ctx = {"path": None}

        def _wt_cwd() -> Path | None:
            p = wt_ctx["path"]
            return Path(p) if p else None

        def _run_bash(command: str) -> str:
            return run_bash(command, cwd=_wt_cwd())

        def _run_read(path: str) -> str:
            return run_read(path, cwd=_wt_cwd())

        def _run_write(path: str, content: str) -> str:
            return run_write(path, content, cwd=_wt_cwd())
```

- `wt_ctx` est un dict (et non une variable) pour être **mutable depuis les closures** — l'idiome Python qui évite `nonlocal`. Chaque thread teammate a le sien : l'isolation est par agent.
- `_run_bash`/`_run_read`/`_run_write` enveloppent les outils de base en injectant le cwd courant : `None` → `WORKDIR` (comportement s17), chemin → worktree.

La bascule se fait dans les handlers de claim/complete (lignes 547–561) :

```python
        def _run_claim_task(task_id: str):
            result = claim_task(task_id, owner=name)
            if "Claimed" in result:
                # Set worktree cwd if task has one
                task = load_task(task_id)
                if task.worktree:
                    wt_ctx["path"] = str(WORKTREES_DIR / task.worktree)
                else:
                    wt_ctx["path"] = None
            return result

        def _run_complete_task(task_id: str):
            result = complete_task(task_id)
            wt_ctx["path"] = None
            return result
```

- Au claim réussi, la tâche est rechargée et son champ `worktree` détermine le cwd ; une tâche sans worktree **réinitialise** explicitement le chemin (on ne traîne pas le worktree de la tâche précédente).
- À la complétion, retour inconditionnel à `WORKDIR` — même si `complete_task` a échoué (voir Pièges).
- Le README contraste avec le vrai CC : `EnterWorktree` fait un `process.chdir()` (changement de répertoire au niveau processus), l'isolation AgentTool passe par `cwdOverride` — ici, c'est une simple indirection de paramètre, suffisante car tous les accès passent par les trois wrappers.

Le reste — `sub_tools` (lignes 564–603, 8 outils comme en s17), `sub_handlers` (lignes 605–614), boucle WORK → IDLE (lignes 616–668), résumé final et envoi au Lead (lignes 670–683), lancement du thread (lignes 685–688) — est repris de [[s17-autonomous-agents]] sans modification structurelle ; `_run_list_tasks` (lignes 538–545) affiche en plus le suffixe `(wt:...)` pour les tâches liées.

### `_teammate_submit_plan(from_name, plan)` — lignes 691–700
Repris de [[s16-team-protocols]] sans modification.

### `run_request_shutdown` — lignes 705–716, `run_request_plan` — lignes 719–722, `run_review_plan` — lignes 725–739
Outils de protocole du Lead, repris de [[s16-team-protocols]] sans modification.

### `run_create_worktree(name, task_id)` — lignes 744–745, `run_remove_worktree(name, discard_changes)` — lignes 748–749, `run_keep_worktree(name)` — lignes 752–753
**Nouvelles.** Wrappers d'outils Lead, délégation pure vers les fonctions du Worktree System. Seul le Lead dispose de ces trois outils — les teammates subissent l'isolation, ils ne la gèrent pas.

### `run_create_task` — lignes 758–763, `run_list_tasks` — lignes 766–773, `run_get_task` — lignes 776–777, `run_claim_task` — lignes 780–781, `run_complete_task` — lignes 784–785, `run_spawn_teammate` — lignes 788–789, `run_send_message` — lignes 792–794, `run_check_inbox` — lignes 797–807
Handlers Lead repris de [[s17-autonomous-agents]] ; seule `run_list_tasks` change : elle affiche `(wt:{t.worktree})` à côté des tâches liées (ligne 772).

### `update_context(context, messages)` — lignes 929–933
Repris de [[s09-memory]] sans modification.

### `agent_loop(messages, context)` — lignes 938–966
Boucle d'agent du Lead, reprise de [[s17-autonomous-agents]] sans modification.

### Bloc `if __name__ == "__main__":` — lignes 969–997
REPL identique à s17 (bannière `s18: worktree isolation`, injection de l'inbox dans `history` via `consume_lead_inbox`).

## Ce qui change par rapport à [[s17-autonomous-agents]]

- **Nouvelle zone « Worktree System »** (lignes 148–263) : `validate_worktree_name`, `run_git`, `log_event`, `create_worktree`, `bind_task_to_worktree`, `_count_worktree_changes`, `remove_worktree`, `keep_worktree`.
- **`Task` gagne le champ `worktree: str | None = None`** (ligne 65) — la liaison tâche ↔ répertoire.
- **`safe_path`/`run_bash`/`run_read`/`run_write` gagnent un paramètre `cwd`** (lignes 303–337) — l'isolation effective.
- **`wt_ctx` dans le thread teammate** (lignes 522–561) : bascule automatique du cwd au claim d'une tâche liée, retour à `WORKDIR` au complete.
- **`idle_poll` enrichit le message `<auto-claimed>`** avec `Work directory: ...` quand la tâche a un worktree (lignes 470–476).
- **Outils Lead : 14 → 17** (+`create_worktree`, `remove_worktree`, `keep_worktree`) ; outils teammate : 8, inchangés (mais `bash`/`read`/`write` s'exécutent dans le worktree).
- **Journal `events.jsonl`** : audit du cycle de vie (`create`/`remove`/`keep`), écrit uniquement après succès git grâce au retour `(ok, output)` de `run_git`.
- **`get_task` renommée `get_task_json`** (lignes 97–99).
- Import `re` ajouté (ligne 29) pour la validation des noms.

## Pièges et détails d'implémentation

- **La détection des commits non poussés est inopérante sur les branches `wt/`** : `git log @{push}..HEAD` exige un upstream, que les branches créées par `git worktree add -b` n'ont jamais. La commande échoue, `subprocess.run` ne lève rien, et `commits` vaut silencieusement 0 — en pratique, seul le compte de fichiers non commités (`git status --porcelain`) protège contre `remove_worktree`. Un worktree dont tout le travail est commité (mais jamais poussé) peut donc être supprimé sans avertissement, branche comprise (`branch -D`).
- **`bind_task_to_worktree` peut faire planter tout le programme** : `load_task` lève `FileNotFoundError` pour un `task_id` inexistant ; ni `create_worktree` ni `agent_loop` (le `handler(**block.input)` de la ligne 960 n'est pas dans un try) ne rattrapent l'exception — elle remonte jusqu'au REPL et tue le processus. Un LLM qui invente un `task_id` suffit.
- **L'auto-claim en IDLE ne bascule pas `wt_ctx`** : `idle_poll` appelle `claim_task` directement, pas le `_run_claim_task` local du thread. Le LLM reçoit `Work directory: ...` en texte, mais ses outils restent sur le cwd précédent tant qu'il ne re-claim pas via l'outil. Les chemins relatifs continuent alors de résoudre dans `WORKDIR` — l'isolation repose sur le fait que le modèle suive l'indication textuelle (par exemple via `bash` et `cd`), ce qui est fragile.
- **`_run_complete_task` réinitialise le cwd même en cas d'échec** : si `complete_task` retourne « cannot complete » (tâche pas `in_progress`), `wt_ctx["path"]` est quand même remis à `None` — le teammate perd son répertoire de travail alors que la tâche n'est pas terminée.
- **`keep_worktree` ne vérifie pas l'existence** : on peut « garder » un worktree inexistant ; seul un événement `keep` fantôme est journalisé.
- **La suppression utilise toujours `--force`** : le garde-fou est purement applicatif ; si l'état change entre `_count_worktree_changes` et `git worktree remove` (course), git ne protégera pas. De même, l'échec de `branch -D` est ignoré sans message.

## Liens

- Session précédente : [[s17-autonomous-agents]]
- Session suivante : [[s19-mcp-plugin]]
- Sessions liées : [[s12-task-system]] (le tableau de tâches que le champ `worktree` étend), [[s15-agent-teams]] (threads teammates et MessageBus), [[s03-permission]] (l'ancêtre de `safe_path`), [[s20-comprehensive]] (réutilise worktrees + tâches dans le harness final)
