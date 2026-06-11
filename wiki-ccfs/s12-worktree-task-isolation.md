---
title: "s12 · Isolation par worktree"
session: 12
phase: "Async & multi-agents"
fichier: "inspiration/claude-code-from-scratch/s12_worktree_task_isolation.py"
lignes: 276
tags: [worktree, git, isolation, threading, chdir, parallélisme]
prev: "s11-autonomous-agents"
next: "s13-streaming"
---

# s12 · Isolation par worktree

> **En une phrase** : chaque tâche parallèle reçoit son propre git worktree — une branche `task/<id>` et un répertoire jetable hors du repo — dans lequel les outils sont exécutés via `os.chdir`, puis tout est détruit : deux agents ne se marchent plus jamais sur les fichiers.

## Rôle dans le harness

Dès que [[s11-autonomous-agents]] fait travailler plusieurs agents en parallèle, un risque apparaît : ils partagent le même répertoire. Deux workers qui éditent `main.py` en même temps produisent un état corrompu — la docstring du fichier le dit sans détour : *« they may attempt to edit the same files, resulting in corrupted states »*. Le motto de la session : *« Each works in its own directory, no interference »*.

La réponse exploite une fonctionnalité native de git : le **worktree**, qui permet d'attacher plusieurs répertoires de travail au même dépôt, chacun sur sa propre branche. s12 en fait une recette en trois temps : *Task Start → branche + worktree*, *Agent Execution → travail dans le répertoire isolé*, *Task Completion → extraction du résultat + nettoyage complet (worktree et branche supprimés)*. La branche `task/<id>` garde `main` propre tant que le travail n'est pas vérifié ; le répertoire `../.worktree-<id>` est créé **hors** du repo pour ne pas polluer son `git status`.

Côté produit réel, le tableau « Claude Code Analog » du README associe s12 aux **file snapshots** — le mécanisme d'annulation par instantanés que la version pédagogique implémente dans [[s14-tools-extended]] (`SNAPSHOTS`/`revert` de [[core-py]]) : deux philosophies de la réversibilité, copie de fichiers d'un côté, copie d'arborescence versionnée de l'autre. Le Claude Code d'aujourd'hui expose d'ailleurs aussi de vrais worktrees pour isoler ses sous-agents. Attention enfin au statut de cette session : c'est la version **enseignement** du mécanisme. Le README liste tout ce qu'elle ne gère pas (working tree sale, worktrees périmés, conflits de branche, HEAD détaché, nettoyage garanti) — autant de cas couverts par [[s23-worktree-advanced]], qui la **remplace** en phase Entreprise.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–28 | Shebang & docstring | Motto, 4 concepts (worktree, isolation par branche, `os.chdir`, threads), flux opérationnel |
| 30–38 | Imports stdlib | `subprocess`, `threading`, `shutil`… (`json` et `sys` importés mais jamais utilisés) |
| 40–47 | Imports core | 5 symboles de [[core-py]] |
| 49–70 | Utilitaire git | `_git()` : wrapper subprocess générique |
| 73–125 | Gestion des worktrees | `create_worktree()`, `remove_worktree()` |
| 128–228 | Exécution isolée | `run_task_in_worktree()` : cycle de vie complet d'un agent dans son worktree |
| 231–271 | Point d'entrée | `main()` : 2 tâches de démo, un thread chacune, synthèse des résultats |
| 274–276 | Entrée script | `if __name__ == "__main__"` |

Pas de constante globale : tout l'état (chemins, branches, historiques) est local à chaque appel de `run_task_in_worktree` — c'est précisément le propos de la session.

## Les fonctions, une à une

### `_git(args, cwd=None)` — lignes 51–70

Le wrapper minimal autour du binaire git.

```python
    # Execute the command synchronously
    result = subprocess.run(
        ["git"] + args, 
        capture_output=True, 
        text=True, 
        cwd=cwd or os.getcwd()
    )
    # Return the execution code along with stripped output streams
    return result.returncode, result.stdout.strip(), result.stderr.strip()
```

- **Ligne 64** : `["git"] + args` en liste (pas `shell=True`) — pas d'interprétation shell, donc pas de problème de quoting sur les chemins Windows avec espaces.
- **Ligne 67** : `cwd or os.getcwd()` — par défaut, la commande s'exécute là où se trouve le processus *à cet instant* ; comme `run_task_in_worktree` joue du `os.chdir`, le « répertoire courant » est une cible mouvante (voir Pièges).
- **Ligne 70** : retour en triplet `(returncode, stdout, stderr)` — contrairement aux outils de [[core-py]] qui renvoient une chaîne pour le modèle, `_git` est un utilitaire **interne au harness** : l'appelant teste `rc != 0` lui-même.

### `create_worktree(task_id)` — lignes 75–106

Création de la paire branche + répertoire isolé.

```python
    # Define a unique branch name for this specific task
    branch_name: str = f"task/{task_id}"
    
    # Define a path for the worktree outside of the main project root
    # e.g., ../.worktree-abc123
    worktree_path: str = str(Path(os.getcwd()).parent / f".worktree-{task_id[:8]}")
    
    # Pre-emptive Cleanup: If the directory exists from a crashed run, remove it
    if Path(worktree_path).exists():
        shutil.rmtree(worktree_path, ignore_errors=True)
        _git(["worktree", "remove", "--force", worktree_path])
        
    # Attempt to add the worktree with a new branch (-b)
    rc, out, err = _git(["worktree", "add", "-b", branch_name, worktree_path])
    
    if rc != 0:
        # If branch already exists (rare), delete branch and force create
        print(f"\033[33m  [worktree] Branch conflict. Resetting branch: {branch_name}\033[0m")
        _git(["branch", "-D", branch_name])
        _git(["worktree", "add", "-b", branch_name, worktree_path])
        
    return worktree_path, branch_name
```

- **Ligne 90** : le worktree atterrit dans le **répertoire parent** du repo (`../.worktree-abc123`) — sinon il apparaîtrait comme répertoire non suivi dans le repo principal et les `glob` des autres agents le verraient.
- **Lignes 93–95** : nettoyage préventif des restes d'un run crashé — d'abord `rmtree`, puis `git worktree remove --force`. L'ordre est discutable (git râle quand on lui demande d'oublier un worktree dont le répertoire a déjà disparu ; `git worktree prune` serait l'outil idoine) mais les erreurs sont ignorées.
- **Ligne 98** : `git worktree add -b task/<id> <chemin>` crée branche et checkout en une commande, à partir du HEAD courant.
- **Lignes 100–104** : si la branche existe déjà (run précédent mal nettoyé), on la supprime (`branch -D`) et on retente — mais le **code de retour du second essai n'est pas vérifié** : en cas de double échec, la fonction retourne quand même un chemin qui n'existe pas (voir Pièges).

### `remove_worktree(path, branch)` — lignes 109–125

Le démontage symétrique, en trois coups :

```python
    # Forcefully remove the worktree from Git's internal tracking
    _git(["worktree", "remove", "--force", path])
    
    # Remove the physical directory if Git didn't clear it
    if Path(path).exists():
        shutil.rmtree(path, ignore_errors=True)
        
    # Delete the local branch to keep the repo clean
    _git(["branch", "-D", branch])
```

`--force` passe outre les modifications non commitées dans le worktree ; le `rmtree` de rattrapage couvre les cas où git laisse des fichiers (verrous Windows notamment) ; `branch -D` (majuscule = force) supprime la branche **même si elle n'est mergée nulle part**. Conséquence assumée : tout ce que l'agent a produit dans le worktree est perdu — voir Pièges.

### `run_task_in_worktree(task)` — lignes 130–228

La pièce maîtresse : tout le cycle de vie d'un agent isolé, de la création du worktree à sa destruction garantie.

**Étape 1 — provisioning avec replis (lignes 143–154)** :

```python
    # Step 1: Initialize Worktree
    # Fallback to CWD if we are not currently in a Git repository
    if not Path(".git").exists() and not Path(os.getcwd()).parent.joinpath(".git").exists():
        print(f"\033[33m  [worktree] No Git repo detected. Running in CWD.\033[0m")
        wt_path, wt_branch = os.getcwd(), None
    else:
        try:
            wt_path, wt_branch = create_worktree(task_id)
            print(f"\033[32m  [worktree] Created isolated environment at: {wt_path}\033[0m")
        except Exception as e:
            print(f"\033[31m  [worktree] Setup failed: {e}. Falling back to CWD.\033[0m")
            wt_path, wt_branch = os.getcwd(), None
```

- **Ligne 145** : détection heuristique du repo — `.git` dans le cwd **ou dans son parent** (le second test couvre le cas où on lance la démo depuis un sous-répertoire... d'un cran seulement). Hors repo, la démo dégrade gracieusement : exécution dans le cwd, sans isolation.
- **`wt_branch = None`** sert de sentinelle : c'est elle qui désactivera le nettoyage dans le `finally` final.

**Étape 2 — persona (lignes 157–161)** : le system prompt annonce au modèle son répertoire isolé et affirme *« Any file changes you make are isolated in this directory's branch »* — vrai pour les chemins relatifs seulement (voir Pièges).

**Étape 3 — la boucle d'agent avec bascule de répertoire (lignes 167–219)**, le passage décisif :

```python
            # Process tool calls with strict directory context switching
            results: List[Dict[str, Any]] = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                
                # Capture current working directory to restore later
                original_cwd = os.getcwd()
                
                try:
                    # Switch context to the worktree so bash/file commands execute there
                    os.chdir(wt_path)
                    
                    # Log the tool call in Yellow (\033[33m)
                    first_arg = str(list(block.input.values())[0])[:60]
                    print(f"\033[33m  [{task_id[:6]}][{block.name}] {first_arg}\033[0m")
                    
                    # Execute the handler
                    if block.name == "bash":
                        output = run_bash(block.input["command"])
                    else:
                        # Fetch handler from the extended dispatch map
                        handler = EXTENDED_DISPATCH.get(block.name, lambda _: "Error: Unknown tool")
                        output = handler(block.input)
                finally:
                    # ALWAYS restore the original directory even if the tool crashed
                    os.chdir(original_cwd)
```

- **Lignes 190–209** : le sandwich `chdir(wt_path)` → outil → `chdir(original_cwd)` dans un `try/finally` — chaque appel d'outil, pris isolément, s'exécute bien dans le worktree, et le répertoire est restauré même si l'outil lève. C'est ce qui fait fonctionner les outils de [[core-py]] sans modification : `run_bash` lance ses commandes avec `cwd=os.getcwd()`, et `run_read`/`run_write` résolvent les chemins relatifs contre le cwd.
- **Lignes 201–206** : `bash` est court-circuité vers `run_bash` importé directement — redondant, puisque `EXTENDED_DISPATCH["bash"]` pointe déjà sur la même fonction ; le court-circuit rend juste la dépendance explicite. Le `.get(block.name, lambda _: "Error: Unknown tool")` couvre les noms d'outils hallucinés sans `KeyError`.
- Cette session **n'utilise pas** `dispatch_tools` de core.py : elle réimplémente la boucle d'exécution pour pouvoir insérer le chdir autour de **chaque** appel — le helper mutualisé n'a pas de point d'extension pour ça (il faudra attendre les hooks de [[s16-event-bus]] pour ce genre d'instrumentation).

**Sortie et nettoyage garanti (lignes 221–228)** :

```python
        # Extract the final textual response
        return "".join(b.text for b in messages[-1]["content"] if hasattr(b, "text"))
        
    finally:
        # Step 3: Cleanup isolated environment
        if wt_branch:
            print(f"\033[90m  [worktree] Cleaning up {wt_path}...\033[0m")
            remove_worktree(wt_path, wt_branch)
```

Le `finally` englobe toute la boucle d'agent : crash API ou non, le worktree est démonté — sauf en mode dégradé (`wt_branch is None`), où il n'y a rien à nettoyer. L'extraction du texte final est le même duck-typing `hasattr(b, "text")` que dans [[s11-autonomous-agents]].

### `main()` — lignes 233–271

La démo : deux tâches **en lecture seule** (compter les fichiers Python, lister les TODO), un thread par tâche.

```python
    # Function to be executed by each thread
    def _thread_worker(task_obj: Dict[str, str]):
        result_text = run_task_in_worktree(task_obj)
        execution_results[task_obj["id"]] = result_text

    # Spawn a thread for each task
    for task in demo_tasks:
        t = threading.Thread(target=_thread_worker, args=(task,), daemon=True)
        threads.append(t)
        t.start()

    # Wait for all threads to finish execution
    for t in threads:
        t.join()
```

- **Lignes 240–243** : IDs générés par `uuid.uuid4().hex[:8]` (l'import `uuid` est local à `main`, ligne 237).
- **`_thread_worker` (lignes 253–255)** : la closure qui dépose le résultat dans le dict partagé `execution_results` — écritures sur des clés distinctes, sûres sous GIL.
- **Lignes 264–265** : contrairement à [[s11-autonomous-agents]], ici on `join()` tous les threads — la démo est un batch fini, pas un service : on attend, puis on imprime la synthèse `Parallel Execution Results` (lignes 268–271).

### Point d'entrée `if __name__ == "__main__"` — lignes 274–276

Appel direct de `main()`.

## Ce qui vient de [[core-py]]

Importés aux lignes 41–47 :

- **`client`** : le client Anthropic — appelé en direct (`client.messages.create`, ligne 170), pas de streaming dans les workers.
- **`MODEL`** : l'ID du modèle, partagé par toutes les sessions.
- **`EXTENDED_TOOLS`** : les 6 schémas d'outils proposés au modèle (ligne 174).
- **`EXTENDED_DISPATCH`** : la table nom → handler, consultée pour tout outil non-bash (ligne 205).
- **`run_bash`** : l'exécuteur shell synchrone — point crucial ici : il lance ses sous-processus avec `cwd=os.getcwd()`, c'est donc le `os.chdir(wt_path)` qui redirige les commandes du modèle vers le worktree, sans toucher une ligne de core.py.

## Pièges et détails d'implémentation

- **`os.chdir` est global au processus, pas au thread** : c'est LA limite de la session. Avec 2 threads, le thread B peut faire son `chdir` entre le `chdir(wt_path)` du thread A et l'exécution de son outil — l'outil de A tourne alors dans le worktree de B. Pire, `original_cwd` capturé pendant la fenêtre d'un autre thread « restaure » un mauvais répertoire. L'isolation est probabiliste, pas garantie — et [[s23-worktree-advanced]] conserve le même `os.chdir` (la course n'est éliminée que si l'on passe le répertoire explicitement à chaque outil, comme le fait le vrai Claude Code).
- **Le travail de l'agent est jeté** : le `finally` appelle `remove_worktree`, qui supprime répertoire **et** branche (`branch -D`). Rien n'est mergé, rien ne survit — seul le **texte** final de l'agent remonte. Les deux tâches de démo sont en lecture seule précisément pour ça ; la récolte des changements est le problème de [[s23-worktree-advanced]].
- **Échec de création non détecté** : si les deux tentatives de `worktree add` échouent (repo sans aucun commit → pas de HEAD valide, par exemple), `create_worktree` retourne quand même son chemin ; le premier `os.chdir(wt_path)` lèvera `FileNotFoundError`, l'exception traverse `run_task_in_worktree`, tue le thread, et le récapitulatif final omet silencieusement la tâche.
- **Les chemins absolus percent l'isolation** : le system prompt promet l'isolation, mais si le modèle écrit `/tmp/x` ou `C:\...`, ni `chdir` ni le worktree ne l'arrêtent — il n'y a pas de `safe_path` ici, les outils de core.py acceptent n'importe quel chemin.
- **Le worktree partage l'index du repo principal pour les branches** : créer `task/<id>` puis la supprimer à chaud pollue le reflog du repo réel ; et le nettoyage préventif `branch -D` (ligne 103) supprimerait sans sommation une branche homonyme à vous.
- **`max_tokens=8000`** ici contre 4000 pour les workers de s11 — les tâches « repo entier » produisent des sorties longues (listings de fichiers, TODO) ; détail facile à rater en comparant les deux sessions.

## Lancer la démo

```bash
python s12_worktree_task_isolation.py
```

Prérequis : `.env` avec `ANTHROPIC_API_KEY` et `MODEL_ID` (ou proxy LiteLLM), et surtout **un dépôt git avec au moins un commit** — sans repo, la démo bascule en mode dégradé (« No Git repo detected. Running in CWD. ») et perd tout son intérêt ; sans commit, la création de worktree échoue.

Démo non interactive : pas de REPL. On observe deux lignes vertes `[worktree] Created isolated environment at: ../.worktree-XXXXXXXX`, puis les appels d'outils des deux agents entrelacés en jaune, préfixés des 6 premiers caractères de leur task ID. À la fin : les lignes grises de nettoyage, puis le bloc `Parallel Execution Results` avec le texte final de chaque tâche. Vérifiez après coup : `git worktree list` ne montre plus que le repo principal, `git branch` ne contient plus de `task/...`.

## Liens

- Socle : [[core-py]]
- Session précédente : [[s11-autonomous-agents]]
- Session suivante : [[s13-streaming]]
- Sessions liées : [[s23-worktree-advanced]] (la version production qui remplace cette session : working tree sale, pruning, conflits de branche, HEAD détaché, nettoyage garanti), [[s14-tools-extended]] (les file snapshots, l'« analog » Claude Code du README), [[s18-parallel-tools]] (l'autre parallélisme : les outils d'un même tour), [[s16-event-bus]] (les hooks qui permettraient d'instrumenter `dispatch_tools` au lieu de le réécrire)
