---
title: "s23 · Worktrees avancés"
session: 23
phase: "Entreprise"
fichier: "inspiration/claude-code-from-scratch/s23_worktree_advanced.py"
lignes: 467
tags: [worktree, git, isolation, parallelisme, conflits, cycle-de-vie]
prev: "s22-production-mailbox"
next: ""
---

# s23 · Worktrees avancés

> **En une phrase** : les worktrees jetables de [[s12-worktree-task-isolation]] gagnent un cycle de vie complet — garde detached-HEAD, sanitisation des noms de branches, purge des worktrees orphelins, démontage garanti par `try/finally` et détection de conflits entre tâches parallèles — pour que N agents travaillent sur le même dépôt sans casser l'état git ni se marcher dessus.

## Rôle dans le harness

[[s12-worktree-task-isolation]] a montré le principe : un `git worktree` par tâche parallèle, donc un répertoire et une branche par agent, zéro collision de fichiers. Mais la version basique suppose un monde idéal. Dans un vrai dépôt, tout déraille : l'arbre de travail a des modifications non commitées, un crash a laissé des métadonnées de worktree orphelines, un ID de tâche contient des caractères interdits dans un nom de branche, on est en detached HEAD, ou deux agents « isolés » ont modifié le même fichier et la fusion sera un champ de mines. La devise de s23 (ligne 5) donne la doctrine : *« Git state is sacred; every edge case handled »*.

C'est la dernière session du repo et la seconde de la phase « Enterprise Upgrades » du README (*« Replacing teaching implementations with production-grade alternatives »*) ; sa colonne « Upgrades » dit **« Replaces s12 basic worktrees »**, et le README liste la check-list couverte : dirty tree warning, stale pruning, branch conflict resolution, detached HEAD detection, parallel conflict detection, guaranteed cleanup via `try/finally`. Le docstring (lignes 12–22) ajoute un cinquième pilier moins visible : le **context switching** par `os.chdir`, pour que les chemins relatifs des outils `read`/`write` atterrissent dans le bon worktree.

Le vrai Claude Code suit la même trajectoire : l'isolement de ses agents parallèles repose aussi sur des worktrees git (avec création, branche dédiée et nettoyage automatique du worktree resté vierge), là où le repo pédagogique n'avait en s12 que l'analogue « file snapshots ». À noter : s23 n'utilise pas `stream_loop` de [[core-py]] — il ré-écrit sa boucle d'agent, précisément parce qu'il doit insérer la bascule `chdir → dispatch → restore` entre la réponse du modèle et l'exécution des outils, point d'insertion que `stream_loop` n'expose pas.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–28 | Shebang & docstring | Devise, 5 améliorations vs s12, commandes spéciales (`|`, `:list`, `:prune`) |
| 30–40 | Imports stdlib | `asyncio`, `json`, `os`, `re`, `shutil`, `subprocess`, `sys`, dataclasses, pathlib, typing |
| 42–49 | Imports core | `client`, `MODEL`, `EXTENDED_TOOLS`, `EXTENDED_DISPATCH`, `dispatch_tools` |
| 51–154 | **Helpers git** | `_git`, `is_git_repo`, `get_git_root`, `is_working_tree_dirty`, `get_current_branch`, `list_active_worktrees`, `prune_stale_worktrees` |
| 157–185 | **État de tâche** | dataclass `WTask` + sanitisation branche/chemin |
| 188–288 | **Cycle de vie** | `setup_isolated_worktree`, `teardown_worktree`, `analyze_parallel_conflicts` |
| 291–336 | **Agent isolé** | `run_agent_in_worktree` : boucle d'agent + bascule `os.chdir` |
| 339–405 | **Orchestration** | `orchestrate_parallel_tasks` : setup → gather → teardown → post-mortem |
| 408–459 | REPL | `main()` : commandes `:list` / `:prune`, découpage par `|` |
| 462–467 | Point d'entrée | `asyncio.run(main())` |

## Les fonctions, une à une

### `_git(args, cwd=None)` — lignes 53–74

Le wrapper unique de tous les appels git du fichier :

```python
    if isinstance(args, str):
        # Allow passing "status --porcelain" as a string for convenience
        args = args.split()

    result = subprocess.run(
        ["git"] + list(args),
        capture_output=True,
        text=True,
        cwd=cwd or os.getcwd()
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()
```

- **Lignes 64–66** : double signature pratique — `"status --porcelain"` en chaîne (découpée par `split()`) ou liste explicite. La forme liste est obligatoire dès qu'un argument peut contenir des espaces (chemins de worktrees), d'où les appels `_git(["worktree", "remove", "--force", path])` plus bas.
- **Ligne 74** : retour systématique du triplet `(code, stdout, stderr)` strippé — chaque appelant choisit ce qu'il regarde : le code (`is_git_repo`), stdout (`get_git_root`), ou stderr (message d'erreur de `setup_isolated_worktree`). Aucune exception ne s'échappe : un échec git est une valeur, pas un crash.

### `is_git_repo()` — lignes 77–79

`_git("rev-parse --git-dir")[0] == 0` — git lui-même répond à la question ; aucun test fragile sur l'existence d'un dossier `.git` (qui échouerait justement… dans un worktree, où `.git` est un fichier).

### `get_git_root()` — lignes 82–84

`rev-parse --show-toplevel` → chemin absolu de la racine du dépôt. C'est la référence de `prune_stale_worktrees` (ne pas se purger soi-même) et de `_generate_safe_filesystem_path` (placer les worktrees *à côté* du dépôt).

### `is_working_tree_dirty()` — lignes 87–90

`bool(_git("status --porcelain")[1])` — le format `--porcelain` est stable et vide si l'arbre est propre ; le moindre fichier modifié ou non suivi rend la chaîne non vide, donc `True`.

### `get_current_branch()` — lignes 93–105

```python
    rc, name, _ = _git("symbolic-ref --short HEAD")
    if rc != 0:
        # If not on a branch, get the short SHA of the current commit
        _, sha, _ = _git("rev-parse --short HEAD")
        return f"(detached:{sha})"
    return name
```

- **Ligne 100** : `symbolic-ref` échoue précisément quand HEAD ne pointe pas sur une branche — l'échec *est* l'information. Le format de retour `(detached:<sha>)` est ensuite testé par préfixe dans `setup_isolated_worktree` (ligne 207) : créer une branche depuis un detached HEAD produirait des tâches forkées d'un commit sans nom, d'où le refus.

### `list_active_worktrees()` — lignes 108–132

Parseur du format machine `git worktree list --porcelain` :

```python
    for line in out.splitlines():
        if line.startswith("worktree "):
            if current_item:
                worktrees.append(current_item)
            current_item = {"path": line[9:]}
        elif line.startswith("HEAD "):
            current_item["head"] = line[5:]
        elif line.startswith("branch "):
            current_item["branch"] = line[7:]
        elif line == "detached":
            current_item["detached"] = True
```

- **Lignes 119–122** : chaque bloc commence par une ligne `worktree <path>` — sa rencontre clôt le dict précédent et en ouvre un nouveau. Les découpages `line[9:]`, `line[5:]`, `line[7:]` sautent les préfixes fixes (`"worktree "`, `"HEAD "`, `"branch "`).
- **Lignes 130–131** : le dernier bloc n'est suivi d'aucune ligne `worktree` — il faut le pousser après la boucle, le classique du parsing par blocs. Le premier élément retourné est toujours le dépôt principal lui-même (git le liste comme un worktree).

### `prune_stale_worktrees()` — lignes 135–154

```python
    for wt in list_active_worktrees():
        path = wt.get("path", "")
        # Don't prune the main repository root
        if path and path != root and not Path(path).exists():
            _git(["worktree", "remove", "--force", path])
            pruned_count += 1

    # Final internal Git cleanup
    _git("worktree prune")
```

- **Ligne 148** : un worktree est « orphelin » si git le connaît encore mais que son répertoire a disparu (crash, suppression manuelle, `shutil.rmtree` d'un run précédent). Le garde `path != root` protège le dépôt principal.
- **Lignes 149–153** : double nettoyage — `worktree remove --force` entrée par entrée, puis `worktree prune` final pour les métadonnées résiduelles que `remove` n'aurait pas traitées. Appelé à la fois en début d'orchestration (auto-réparation, ligne 350) et à la demande via `:prune` (ligne 446).

### `WTask` (dataclass) — lignes 159–170

```python
@dataclass
class WTask:
    task_id: str
    description: str
    branch: str = ""
    path:   str = ""
    status: str = "pending"
    result: str = ""
    error:  str = ""
```

Le dossier d'état d'une tâche isolée. `status` traverse `pending → running → done|failed` au fil de l'orchestration ; `branch` et `path` sont remplis par `setup_isolated_worktree` ; `result` et `error` alimentent le rapport JSON final. Pur conteneur, aucune méthode — l'état est manipulé par les fonctions du cycle de vie.

### `_generate_safe_git_name(task_id)` — lignes 173–177

```python
    safe = re.sub(r'[^a-zA-Z0-9_-]', '-', task_id)
    return f"task/{safe[:40]}"
```

Tout caractère hors `[a-zA-Z0-9_-]` devient un tiret (espaces, accents, `/`, `:` — autant de pièges des refnames git), tronqué à 40 caractères et préfixé `task/` — l'espace de noms regroupe les branches temporaires et évite d'écraser une branche de travail humaine… sauf homonymie exacte (voir Pièges).

### `_generate_safe_filesystem_path(task_id)` — lignes 180–185

```python
    root = get_git_root()
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", task_id)
    # Put the worktree in the parent directory to avoid recursive git issues
    return str(Path(root).parent / f".worktree-{safe[:20]}")
```

- **Ligne 185** : le worktree vit dans le répertoire **parent** du dépôt (`../.worktree-T-1`), pas dedans — un worktree créé *dans* le dépôt apparaîtrait comme répertoire non suivi, polluerait `status`, et risquerait d'être ramassé par les globs des agents. Même sanitisation que pour la branche, mais tronquée à 20 caractères.

### `setup_isolated_worktree(task)` — lignes 188–225

Le protocole de création, en quatre temps commentés dans le code :

```python
    # 1. Safety Guard: Disallow branching from a detached HEAD
    cb = get_current_branch()
    if cb.startswith("(detached:"):
        return False, f"Detached HEAD detected ({cb}). Please checkout a branch before running tasks."

    # 2. Cleanup: Remove existing worktree directory if it persists from a crash
    if Path(path).exists():
        _git(["worktree", "remove", "--force", path])
        shutil.rmtree(path, ignore_errors=True)

    # 3. Cleanup: Remove the branch if it already exists (ensures a clean slate)
    # We ignore the error if the branch doesn't exist
    _git(["branch", "-D", branch])

    # 4. Git Operation: Create the worktree linked to a new branch
    rc, _, err = _git(["worktree", "add", "-b", branch, path])
    if rc != 0:
        return False, f"Git worktree creation failed: {err}"
```

- **Lignes 201–203** : la fonction remplit `task.branch` / `task.path` *avant* toute opération — même en cas d'échec, le teardown saura quoi nettoyer.
- **Lignes 206–208** : garde detached HEAD — seul cas de refus définitif ; tout le reste est de l'auto-réparation.
- **Lignes 211–217** : nettoyage préventif idempotent — répertoire fantôme d'un crash (`worktree remove --force` puis `rmtree(ignore_errors=True)` en ceinture-bretelles) et branche homonyme (`branch -D`, dont l'échec « n'existe pas » est ignoré par construction). Relancer la même tâche deux fois ne demande aucune intervention manuelle.
- **Ligne 220** : `worktree add -b <branche> <chemin>` fait les deux opérations d'un coup : créer la branche **depuis le commit HEAD courant** et y attacher un nouveau répertoire de travail. Le retour `(False, err)` remonte le stderr git brut vers l'orchestrateur, qui l'affiche et marque la tâche `failed`.

### `teardown_worktree(task, force=False)` — lignes 228–250

```python
    flags = ["--force"] if force else []

    # 1. Remove from Git tracking
    _git(["worktree", "remove"] + flags + [task.path])

    # 2. Remove physical directory
    if Path(task.path).exists():
        shutil.rmtree(task.path, ignore_errors=True)

    # 3. Delete the temporary task branch
    if task.branch:
        _git(["branch", "-D", task.branch])
```

- **Ligne 236** : garde `if not task.path: return` (lignes 236–237) — une tâche jamais installée n'a rien à démonter.
- **Ligne 239** : `force` n'est vrai que pour les tâches en échec ; pour une tâche réussie, `worktree remove` *sans* `--force` **refuse** si le worktree contient des modifications non commitées — et comme les agents ne committent pas spontanément, ce refus est fréquent. Le `rmtree` suivant supprime quand même le répertoire, laissant des métadonnées orphelines… que `prune_stale_worktrees` rattrapera au run suivant. L'enchaînement est volontairement tolérant : chaque étape tente sa part, aucune ne bloque les autres.
- **Ligne 250** : `branch -D` (majuscule = forcée) supprime la branche même non fusionnée — sauf si git la considère encore « checked out » par le worktree dont le remove a échoué. Cette cascade d'échecs silencieux a une conséquence inattendue sur la détection de conflits (voir Pièges).

### `analyze_parallel_conflicts(tasks)` — lignes 253–288

Le post-mortem : deux tâches « isolées » ont-elles touché les mêmes fichiers ?

```python
    for t in tasks:
        if t.status != "done" or not t.branch:
            continue

        # Get list of files changed in this branch compared to current HEAD
        rc, out, _ = _git(["diff", "--name-only", "HEAD", t.branch])
        if rc == 0 and out:
            file_changes[t.task_id] = set(out.splitlines())
```

puis comparaison de toutes les paires :

```python
    for i in range(len(task_ids)):
        for j in range(i + 1, len(task_ids)):
            id_a, id_b = task_ids[i], task_ids[j]
            # Set intersection identifies overlapping files
            overlapping_files = file_changes[id_a] & file_changes[id_b]

            if overlapping_files:
                file_list = ", ".join(sorted(overlapping_files)[:5])
                conflicts.append(f"{id_a} ↔ {id_b}: {file_list}")
```

- **Ligne 270** : `git diff --name-only HEAD <branche>` liste les fichiers qui diffèrent entre le tronc et la pointe de la branche de tâche — donc uniquement les changements **commités** par l'agent ; un fichier modifié mais jamais commité dans le worktree est invisible ici.
- **Ligne 271** : le garde `rc == 0` avale silencieusement le cas « branche déjà supprimée » — fréquent, puisque le teardown tourne avant l'analyse (voir Pièges).
- **Lignes 278–286** : intersection d'ensembles paire par paire, O(n²) sur le nombre de tâches — trivial pour une poignée d'agents. Le rapport tronque à 5 fichiers par paire. C'est une **alerte**, pas une fusion : l'outil signale le chevauchement, l'humain décide.

### `run_agent_in_worktree(task)` — lignes 293–336

La boucle d'agent classique, avec deux particularités : un prompt système ancré dans le worktree, et la bascule de répertoire autour du dispatch.

```python
    system_prompt = (
        f"You are a coding agent working in isolated worktree: {task.path}. "
        f"Goal: {task.description}. Summarize your changes and results when finished."
    )
```

- **Lignes 308–316** : comme en s22, l'appel `client.messages.create` (bloquant) passe par `run_in_executor` — c'est ce qui permet à N agents de « réfléchir » simultanément dans le même event loop.

```python
        # --- Context Switch ---
        # Temporarily change directory to the worktree for tool execution
        original_cwd = os.getcwd()
        try:
            os.chdir(task.path)
            # Execute standard tools (bash, read, write, etc.) in the worktree
            results = dispatch_tools(response.content, EXTENDED_DISPATCH)
        finally:
            # Restore original project root
            os.chdir(original_cwd)
```

- **Lignes 325–332** : le cœur du mécanisme. Les outils de [[core-py]] résolvent leurs chemins relativement au répertoire courant (`run_bash` passe `cwd=os.getcwd()` au sous-processus) : en basculant `os.chdir(task.path)` juste avant `dispatch_tools` et en restaurant dans un `finally`, tous les `read`/`write`/`bash` du tour atterrissent dans le worktree — sans modifier une ligne de core.py. Le `finally` garantit la restauration même si un handler lève.
- Subtilité de concurrence : `dispatch_tools` est **synchrone** et s'exécute dans le thread de l'event loop — aucune autre coroutine ne peut s'intercaler entre le `chdir` et sa restauration, la fenêtre est donc atomique pour les tâches parallèles. Le prix : pendant qu'un agent exécute ses outils, *tous* les autres sont gelés (voir Pièges).
- **Ligne 336** : extraction du texte final par `hasattr(block, "text")`, comme dans les autres sessions.

### `orchestrate_parallel_tasks(task_descriptions)` — lignes 339–405

Le chef d'orchestre du cycle de vie complet. D'abord les pré-vols :

```python
    if not is_git_repo():
        return {"error": "Target directory is not a Git repository."}

    if is_working_tree_dirty():
        print("\033[33mWarning: Uncommitted changes detected. Parallel branches will fork from HEAD.\033[0m")

    # Pre-clean stale data
    pruned = prune_stale_worktrees()
```

- **Lignes 346–347** : l'arbre sale ne **bloque pas** — le warning explique la conséquence : les branches forkeront du dernier *commit*, pas de l'état du répertoire ; les modifications non commitées du tronc n'existeront dans aucun worktree.
- **Lignes 355–367** : phase setup — un `WTask` par description (`T-1`, `T-2`, …), et seules les tâches dont le setup réussit passent en `running` et rejoignent `active_tasks` ; les autres sont marquées `failed` avec le message d'erreur, sans faire tomber le lot.

Puis l'exécution parallèle, via la fermeture interne `_safe_run` (lignes 370–381) :

```python
    async def _safe_run(t: WTask):
        try:
            t.result = await run_agent_in_worktree(t)
            t.status = "done"
            print(f"\033[32m  [{t.task_id}] Task completed successfully.\033[0m")
        except Exception as e:
            t.status = "failed"
            t.error = str(e)
            print(f"\033[31m  [{t.task_id}] Execution crashed: {e}\033[0m")
        finally:
            # 3. Teardown Phase
            teardown_worktree(t, force=(t.status == "failed"))

    # Launch all workers concurrently
    await asyncio.gather(*[_safe_run(t) for t in active_tasks])
```

- **Lignes 370–381** : c'est le « guaranteed cleanup via try/finally » de la check-list du README — crash de l'API, exception d'outil, peu importe : le worktree est démonté, en mode `force` si la tâche a échoué. Le succès relâche en douceur, l'échec passe au bulldozer.
- **Ligne 384** : `asyncio.gather` lance toutes les tâches actives de front — l'équivalent worktree du fan-out de [[s18-parallel-tools]].
- **Lignes 387–391** : post-mortem de conflits sur les seules tâches `done`, affiché en jaune puce par puce.
- **Lignes 394–405** : retour structuré `{summary, tasks, conflicts}` — comptes de succès/échecs et résultats tronqués à 150 caractères, sérialisé en JSON par `main()`.

### `main()` — lignes 410–459

Le REPL de pilotage. Refus net hors dépôt git (lignes 418–420, `sys.exit(1)`), puis affichage du tableau de bord initial : racine, branche courante, état dirty (lignes 422–424). La boucle reconnaît trois formes d'entrée :

```python
        # Command: List active worktrees
        if query == ":list":
            for wt in list_active_worktrees():
                print(f"  Path: {wt.get('path','?')}  [Branch: {wt.get('branch','?')}]")
            continue

        # Command: Manual prune
        if query == ":prune":
            count = prune_stale_worktrees()
            print(f"  Successfully pruned {count} stale entries."); continue

        # Parallel Operation: Split query by pipe character '|'
        subtask_descriptions = [t.strip() for t in query.split("|") if t.strip()]
```

- **Lignes 439–447** : deux commandes d'administration directe — inspection (`:list`) et réparation (`:prune`) — qui exposent à l'utilisateur les mêmes helpers que l'orchestration utilise en interne.
- **Ligne 450** : tout le reste est découpé sur `|` : `corrige le bug X | ajoute des tests | mets à jour le README` lance trois agents dans trois worktrees ; une entrée sans `|` lance simplement un agent isolé unique.
- **Ligne 458** : le rapport final est imprimé en `json.dumps(results, indent=2)` — sortie structurée, lisible et exploitable en script.

### Point d'entrée — lignes 462–467

`asyncio.run(main())` sous `try/except KeyboardInterrupt: pass` — sortie silencieuse sur Ctrl+C.

## Ce qui vient de [[core-py]]

Importés lignes 43–49 :

- **`client`** — le client Anthropic configuré ; appelé en direct (`messages.create`) via `run_in_executor` dans `run_agent_in_worktree`.
- **`MODEL`** — l'ID de modèle (`MODEL_ID`).
- **`EXTENDED_TOOLS`** — les 6 schémas (bash, read, write, grep, glob, revert) annoncés à chaque agent isolé.
- **`EXTENDED_DISPATCH`** — la table nom → handler, réellement exécutée ici (contrairement à [[s22-production-mailbox]] qui l'importe sans s'en servir).
- **`dispatch_tools`** — l'exécuteur de blocs `tool_use` de core ; s23 l'encadre par la bascule `os.chdir` au lieu de le réécrire.

## Pièges et détails d'implémentation

- **La détection de conflits arrive après le teardown** : `teardown_worktree` (dans le `finally` de `_safe_run`) supprime la branche via `branch -D` *avant* qu'`analyze_parallel_conflicts` ne tourne, et le diff `HEAD..branche` ne voit que les changements **commités**. En pratique, l'alerte ne se déclenche que si l'agent a commité son travail *et* que la branche a survécu (typiquement parce que `worktree remove` sans `--force` a échoué sur un worktree sale, laissant la branche « checked out »). La mécanique de la fonction est correcte ; c'est l'ordonnancement du cycle de vie qui la neutralise souvent.
- **`os.chdir` est global au process** : la fenêtre `chdir → dispatch_tools → chdir` est atomique pour les coroutines (dispatch synchrone dans le thread de l'event loop), donc pas de course entre tâches — mais un outil long (bash a 120 s de timeout dans core) **gèle tous les agents parallèles**. Seule la phase « réflexion » (appels modèle dans des threads) est réellement concurrente.
- **Les worktrees vivent hors du dépôt** : `../.worktree-<id>` dans le répertoire *parent* de la racine — à savoir pour les retrouver sur disque. Et la sanitisation tronque (40 caractères pour la branche, 20 pour le chemin) : deux IDs longs au même préfixe collisionneraient — impossible avec les IDs générés `T-1`, `T-2`, mais le risque existe si on réutilise ces helpers ailleurs.
- **Le fork part du commit HEAD, pas de l'état du répertoire** : les modifications non commitées du tronc n'apparaissent dans aucun worktree — c'est exactement ce que le warning « dirty » (lignes 346–347) signale, sans bloquer.
- **Les nettoyages git échouent en silence** : le `branch -D` préventif du setup (ligne 217) détruirait sans sommation une branche `task/...` homonyme préexistante, et aucun code retour de nettoyage n'est vérifié — philosophie « chaque étape tente sa part », compensée par le prune d'auto-réparation au début de chaque orchestration.
- **Cosmétique du rapport** : `t.result[:150] + "..."` (ligne 401) ajoute toujours `...`, même à un résultat vide ou court, et `json.dumps` sans `ensure_ascii=False` affiche le `↔` des conflits en séquence échappée `\u2194` dans le JSON (la version lisible est imprimée à part, lignes 389–391). À noter aussi : `field` (ligne 38) est importé mais inutilisé.

## Lancer la démo

```bash
python s23_worktree_advanced.py
```

Prérequis : `.env` avec `ANTHROPIC_API_KEY` et `MODEL_ID` (ou proxy LiteLLM), le binaire `git` dans le PATH, et surtout **être dans un dépôt git** avec au moins un commit et une branche active — hors dépôt le programme sort en `sys.exit(1)`, et en detached HEAD chaque setup de tâche est refusé.

Au lancement : racine du dépôt, branche courante et état dirty. Au prompt `s23 >>`, entrer `tâche A | tâche B | tâche C` : trois worktrees `../.worktree-T-*` apparaissent (lignes grises `[worktree] Created ...`), trois agents tournent en parallèle, puis chaque tâche s'affiche en vert (`done`) ou rouge (`failed`), les worktrees disparaissent, une éventuelle alerte `[Conflict Alert]` liste les fichiers chevauchants, et le rapport JSON `{summary, tasks, conflicts}` clôt le tour. `:list` montre les worktrees actifs (pendant un run, depuis un autre terminal : `git worktree list`), `:prune` force le nettoyage des métadonnées orphelines.

## Liens

- Socle : [[core-py]]
- Session précédente : [[s22-production-mailbox]]
- Sessions liées : [[s12-worktree-task-isolation]] (la version basique que s23 remplace), [[s18-parallel-tools]] (le même `asyncio.gather`, appliqué aux outils d'un tour), [[s14-tools-extended]] (l'arsenal `EXTENDED_DISPATCH` exécuté dans chaque worktree), [[s11-autonomous-agents]] (l'auto-assignation qui pourrait alimenter ces tâches parallèles)
