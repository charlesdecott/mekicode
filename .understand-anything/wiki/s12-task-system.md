---
title: "s12 · Système de tâches"
session: 12
phase: "Tâches & temps"
fichier: "inspiration/learn-claude-code/s12_task_system/code.py"
lignes: 377
tags: [taches, dag, persistance, dependances, claim]
prev: "s11-error-recovery"
next: "s13-background-tasks"
---

# s12 · Système de tâches

> **En une phrase** : un graphe de tâches persisté en JSON sur disque (`.tasks/`), avec dépendances `blockedBy`, revendication (`claim`) et déblocage en cascade — la fondation de la collaboration multi-agents.

## Rôle dans le harness

Le TodoWrite de [[s05-todo-write]] est une checklist d'exécution pour la tâche courante, vivant en mémoire de session. Le README pose le problème : l'agent reçoit un projet (base de données, API, tests), commence par l'API, réalise à mi-chemin que les tables n'existent pas, revient en arrière… *« You can't build the roof before laying the foundation »* — les tâches ont un **ordre**. Il faut un vrai système de tâches : chaque tâche est un fichier JSON, les tâches ont des dépendances `blockedBy`, et elles persistent sur disque entre les sessions.

Trois différences structurantes avec TodoWrite : la **persistance** (`.tasks/{id}.json` survit au processus), les **dépendances** (un graphe orienté — idéalement acyclique ; la version pédagogique vérifie `blockedBy` sans détecter les cycles), et la **coordination** (le champ `owner` + l'action `claim` préparent le scénario multi-agents de [[s15-agent-teams]] : qui travaille sur quoi, sans double revendication).

Dans le vrai Claude Code, le système est plus riche : `TaskRecord` a 9 champs (dont `activeForm`, `blocks` — le sens inverse de `blockedBy` — et `metadata`), les IDs sont des entiers croissants protégés par un fichier `.highwatermark` contre la réutilisation, et `claimTask()` utilise un double verrouillage (`proper-lockfile` sur le fichier de tâche + verrou de liste) contre les courses TOCTOU. Le README précise aussi une nuance : dans CC, `claimTask` ne fait que résoudre la compétition sur `owner` — le changement de statut passe par `TaskUpdate` ; la version pédagogique fusionne les deux en une seule action. Autre point du docstring (lignes 17–21) : la boucle d'agent redevient basique — la récupération d'erreurs de [[s11-error-recovery]] est omise volontairement, car dans CC `tasks.ts` et `withRetry` sont des couches indépendantes qui se composent naturellement.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–21 | Docstring | changements depuis s11, note sur l'omission de la récupération d'erreurs |
| 23–44 | Imports & configuration | `dataclass`/`asdict`, dotenv, chemins, client, `MODEL` |
| 46–139 | **NOUVEAU : système de tâches** | `Task`, CRUD fichiers, `can_start`, `claim_task`, `complete_task` |
| 142–173 | Repris de [[s10-system-prompt]] | `PROMPT_SECTIONS` (liste d'outils mise à jour), assemblage + cache |
| 176–212 | Repris de s02–s03 | `safe_path`, `run_bash`, `run_read`, `run_write` |
| 215–252 | **NOUVEAU : wrappers d'outils tâches** | `run_create_task` … `run_complete_task` |
| 255–305 | Définitions d'outils | 8 outils (3 fichiers + 5 tâches), `TOOL_HANDLERS` |
| 308–321 | Contexte | `update_context` (repris de s10) |
| 324–355 | `agent_loop` | boucle simplifiée, sans récupération d'erreurs |
| 358–376 | REPL | boucle interactive |

## Constantes et configuration

- `TASKS_DIR = WORKDIR / ".tasks"` — lignes 48–49, créé à l'import (`mkdir(exist_ok=True)`) : le répertoire de persistance, un fichier JSON par tâche.
- `MEMORY_DIR` / `MEMORY_INDEX` — lignes 41–42 : conservés pour la section mémoire du prompt (héritage s09/s10), en lecture seule ici.
- `PROMPT_SECTIONS` — lignes 144–150 : la section `tools` énumère désormais les 8 outils, y compris les 5 outils de tâches.
- `TOOLS` — lignes 255–298 : 8 schémas d'outils ; `TOOL_HANDLERS` — lignes 300–305.

## Les fonctions, une à une

### `class Task` — lignes 52–59

```python
@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str          # pending | in_progress | completed
    owner: str | None    # Agent name (multi-agent scenarios)
    blockedBy: list[str] # Dependency task IDs
```

Une dataclass à 6 champs. `status` est une chaîne libre (pas d'Enum — la validation se fait par les gardes de `claim_task`/`complete_task`). `owner` est `None` tant que personne n'a revendiqué la tâche. `blockedBy` liste les IDs des tâches **amont** dont la complétion est requise. La sérialisation est triviale : `asdict(task)` → JSON, `Task(**dict)` ← JSON.

### `_task_path(task_id)` — lignes 62–63

Convention de stockage : `.tasks/{task_id}.json`. Toute la persistance passe par ce seul helper.

### `create_task(subject, description="", blockedBy=None)` — lignes 66–77

```python
    task = Task(
        id=f"task_{int(time.time())}_{random.randint(0, 9999):04d}",
        subject=subject,
        description=description,
        status="pending",
        owner=None,
        blockedBy=blockedBy or [],
    )
    save_task(task)
    return task
```

- Ligne 69 : ID = timestamp Unix + 4 chiffres aléatoires (`:04d` garde le zéro de tête). Simple mais suffisant ; le README oppose les IDs séquentiels de CC protégés par `.highwatermark` contre la réutilisation après suppression. (Petit écart : le README parle de « random hex », le code utilise des chiffres décimaux.)
- Ligne 74 : `blockedBy or []` évite le piège du défaut mutable et normalise `None` → liste vide.
- Ligne 76 : la persistance est immédiate — pas d'état en mémoire qui pourrait se désynchroniser du disque.

### `save_task(task)` / `load_task(task_id)` — lignes 80–81 / 84–85

Aller-retour JSON d'une ligne chacun : `json.dumps(asdict(task), indent=2)` à l'écriture, `Task(**json.loads(...))` à la lecture. `load_task` lève `FileNotFoundError` si l'ID n'existe pas — voir Pièges.

### `list_tasks()` — lignes 88–90

Recharge **toutes** les tâches depuis le disque (`TASKS_DIR.glob("task_*.json")`, trié par nom de fichier — donc grossièrement par timestamp de création). Le disque est la seule source de vérité : deux processus qui partagent `.tasks/` voient les mêmes tâches.

### `get_task(task_id)` — lignes 93–96

Retourne le JSON complet (indenté) d'une tâche. Le README explique le besoin : `list_tasks` n'affiche qu'une ligne par tâche ; pour reprendre un travail entre sessions, l'agent doit relire la `description` complète.

### `can_start(task_id)` — lignes 99–108

Le cœur du graphe de dépendances :

```python
def can_start(task_id: str) -> bool:
    """Check if all blockedBy dependencies are completed.
    Missing dependencies are treated as blocked."""
    task = load_task(task_id)
    for dep_id in task.blockedBy:
        if not _task_path(dep_id).exists():
            return False
        if load_task(dep_id).status != "completed":
            return False
    return True
```

- Lignes 104–105 : une dépendance **inexistante** (fichier absent) bloque, au lieu de faire planter `load_task` — défense contre un LLM qui inventerait un ID.
- Lignes 106–107 : la seule condition de déblocage est `status == "completed"` pour **toutes** les dépendances ; `in_progress` ne suffit pas.
- Aucune détection de cycle : `A blockedBy B` + `B blockedBy A` reste bloqué pour toujours, sans erreur (limite assumée par le README).

### `claim_task(task_id, owner="agent")` — lignes 111–123

L'action `pending → in_progress` :

```python
    task = load_task(task_id)
    if task.status != "pending":
        return f"Task {task_id} is {task.status}, cannot claim"
    if not can_start(task_id):
        deps = [d for d in task.blockedBy
                if not _task_path(d).exists() or load_task(d).status != "completed"]
        return f"Blocked by: {deps}"
    task.owner = owner
    task.status = "in_progress"
    save_task(task)
```

- Lignes 113–114 : premier garde — seule une tâche `pending` est revendicable ; une tâche déjà `in_progress` (revendiquée par un autre agent) ou `completed` est refusée. Le refus est retourné comme **chaîne**, pas comme exception : le LLM lit le message et s'adapte.
- Lignes 115–118 : deuxième garde — si `can_start` échoue, la liste des dépendances bloquantes est recalculée pour produire un message actionnable (`Blocked by: [...]`), avec le même traitement des dépendances manquantes que `can_start`.
- Lignes 119–121 : la revendication couple `owner` + statut en une écriture. Sans verrou de fichier : deux processus simultanés peuvent se doubler (CC verrouille avec `proper-lockfile`, jusqu'à 30 retries).

### `complete_task(task_id)` — lignes 126–139

L'action `in_progress → completed`, avec rapport de déblocage :

```python
    task = load_task(task_id)
    if task.status != "in_progress":
        return f"Task {task_id} is {task.status}, cannot complete"
    task.status = "completed"
    save_task(task)
    unblocked = [t.subject for t in list_tasks()
                 if t.status == "pending" and t.blockedBy and can_start(t.id)]
    ...
    msg = f"Completed {task.id} ({task.subject})"
    if unblocked:
        msg += f"\nUnblocked: {', '.join(unblocked)}"
```

- Lignes 127–128 : on ne peut compléter qu'une tâche `in_progress` — le cycle claim → complete est obligatoire, pas de raccourci `pending → completed`.
- Lignes 131–132 : après la sauvegarde, un scan complet cherche les tâches `pending` **ayant des dépendances** (`t.blockedBy` non vide) désormais toutes satisfaites. Le filtre `t.blockedBy` évite de lister les tâches libres depuis toujours ; en revanche, une tâche débloquée par une complétion *antérieure* mais jamais revendiquée réapparaîtra à chaque complétion (voir Pièges).
- Lignes 135–138 : le déblocage est rapporté dans la valeur de retour de l'outil — c'est ainsi que le LLM apprend quelles tâches sont devenues disponibles, sans avoir à relancer `list_tasks`.

Le diagramme d'états du README : `pending ──claim──→ in_progress ──complete──→ completed`. Pas de chemin retour `in_progress → pending` : la version pédagogique omet le chemin de récupération de CC (quand un teammate meurt, CC remet ses tâches en `pending` et efface `owner`).

### `PROMPT_SECTIONS`, `assemble_system_prompt`, `get_system_prompt` — lignes 144–173 (repris de [[s10-system-prompt]])

Identiques à s10/s11, à deux détails près : la section `tools` (lignes 146–147) énumère les 8 outils, et `get_system_prompt` (166–173) a perdu ses `print` de log `[cache hit]`/`[assembled]` — le cache JSON reste.

### Outils fichiers — lignes 178–212 (repris de [[s02-tool-use]])

`safe_path` (178–182), `run_bash` (185–192), `run_read` (195–202), `run_write` (205–212) : inchangés (sandbox, timeout 120 s, troncatures).

### `run_create_task(subject, description="", blockedBy=None)` — lignes 217–222

Wrapper outil → domaine : appelle `create_task`, loggue `[create]` en couleur et retourne `"Created {id}: {subject}"` avec les dépendances éventuelles. La séparation wrapper/fonction métier garde les fonctions cœur testables sans I/O console.

### `run_list_tasks()` — lignes 225–237

Rendu texte de toutes les tâches, une par ligne, avec icône d'état (`○` pending, `●` in_progress, `✓` completed — lignes 231–232), owner entre crochets et dépendances. Message d'aide si la liste est vide (`"No tasks. Use create_task to add some."`, ligne 228) — il guide le LLM vers le bon outil.

### `run_get_task(task_id)` — lignes 240–244

Seul wrapper défensif : attrape `FileNotFoundError` et retourne `"Error: Task … not found"`. Les autres wrappers ne le font pas — voir Pièges.

### `run_claim_task(task_id)` / `run_complete_task(task_id)` — lignes 247–248 / 251–252

Délégation directe ; `run_claim_task` fixe `owner="agent"` (un seul agent dans cette session — le multi-agents donnera des owners distincts en [[s15-agent-teams]]).

### `TOOLS` / `TOOL_HANDLERS` — lignes 255–298 / 300–305

8 outils : les 3 outils fichiers plus `create_task` (seul `subject` requis, `blockedBy` en tableau de chaînes), `list_tasks` (aucun paramètre), `get_task`, `claim_task`, `complete_task` (un `task_id` requis chacun).

### `update_context(context, messages)` — lignes 310–321 (repris de [[s10-system-prompt]])

Inchangé : outils actifs, workspace, contenu de `MEMORY.md` si présent.

### `agent_loop(messages, context)` — lignes 326–355

Boucle volontairement basique : l'appel LLM est dans un `try/except` minimal qui consigne toute exception comme message assistant `[Error] …` puis sort (lignes 333–337) — pas de retry, pas d'escalade, pas de compact. Le commentaire de section (ligne 324) et le docstring du fichier assument : *focused on task system*. Le reste est la boucle standard : append de la réponse, sortie si `stop_reason != "tool_use"`, exécution des outils (sortie tronquée à 300 caractères pour l'affichage, ligne 350), puis `update_context` + `get_system_prompt` (lignes 354–355).

### REPL — lignes 358–376

Identique au REPL de s10 : seul le dernier message de l'historique est affiché (contrairement à s11 qui affichait tous les messages assistant du tour).

## Ce qui change par rapport à [[s11-error-recovery]]

- **Nouveau bloc « Task System »** (lignes 46–139) : dataclass `Task`, `_task_path`, `create_task`, `save_task`, `load_task`, `list_tasks`, `get_task`, `can_start`, `claim_task`, `complete_task`, plus `TASKS_DIR`.
- **5 nouveaux outils** (lignes 215–252, 255–298) : `create_task`, `list_tasks`, `get_task`, `claim_task`, `complete_task` — la palette passe de 3 à 8 ; `PROMPT_SECTIONS["tools"]` est mis à jour en conséquence.
- **Régression assumée de la boucle** : toute la machinerie s11 (`RecoveryState`, `with_retry`, `retry_delay`, escalade `max_tokens`, compact réactif, modèle de repli) disparaît au profit d'un `try/except` minimal. Le docstring (lignes 17–21) justifie : dans CC, le système de tâches (`tasks.ts`) et la récupération (`withRetry`) sont des couches orthogonales.
- **`get_system_prompt` sans logs** : les `print` `[cache hit]`/`[assembled]` de s10/s11 sont retirés.
- **Disparition de `FALLBACK_MODEL`** et des constantes de retry ; retour à un unique `MODEL` (ligne 44).
- **REPL** : retour à l'affichage du seul dernier message (s11 affichait tout le tour).

## Pièges et détails d'implémentation

- **`run_claim_task` et `run_complete_task` ne protègent pas contre un ID inexistant** : `load_task` lève `FileNotFoundError`, qui n'est attrapée ni par le wrapper ni par `agent_loop` (le `try` n'entoure que l'appel API) — un ID halluciné par le LLM fait **planter le programme**. Seul `run_get_task` a le garde-fou.
- **Pas de détection de cycle** : `blockedBy` mutuels = blocage perpétuel silencieux. Le README l'assume (« without cycle detection »).
- **« Unblocked » est recalculé, pas différentiel** : `complete_task` liste toute tâche `pending` à dépendances satisfaites, y compris celles débloquées par des complétions antérieures — le rapport peut répéter des tâches déjà annoncées comme débloquées.
- **Aucun verrouillage de fichiers** : deux agents qui partagent `.tasks/` peuvent revendiquer la même tâche entre le `load_task` et le `save_task` de `claim_task` (course TOCTOU). CC verrouille chaque fichier (30 retries, backoff 5–100 ms) plus un verrou de liste.
- **Collision d'ID possible** : deux `create_task` dans la même seconde ont 1 chance sur 10000 de produire le même suffixe — le second écraserait le premier sans erreur.
- **Pas de retour arrière** : aucune action `in_progress → pending` ni suppression de tâche n'est exposée ; une tâche revendiquée puis abandonnée reste `in_progress` pour toujours.

## Liens

- Session précédente : [[s11-error-recovery]]
- Session suivante : [[s13-background-tasks]]
- Sessions liées : [[s05-todo-write]] (la checklist en mémoire que le système de tâches dépasse), [[s15-agent-teams]] (le `owner`/`claim` prend tout son sens avec plusieurs agents), [[s16-team-protocols]] (protocoles de coordination autour des tâches partagées)
