---
title: "worktree.py · Isolation git"
phase: "Intégration"
fichier: "src_scratch/worktree.py"
lignes: 172
tags: [worktree, git, isolation, parallélisme, threads]
---

# worktree.py · Isolation git

> **En une phrase** : chaque tâche reçoit une branche `task/<id>` et un répertoire jetable hors du dépôt, un `agent_loop` dédié y travaille, le résultat est commité et diffé, puis tout est démonté en `try/finally` — le cycle de vie complet de s23, avec ses trois bugs corrigés.

## Rôle dans le harness

Les workers de [[agents-py]] partagent tous le même arbre de fichiers : deux tâches qui touchent le même fichier se marchent dessus. Ce module apporte l'isolation manquante — la mécanique de s12 (créer/supprimer un worktree git) absorbée dans le cycle de vie complet de s23 (worktree → agent → commit → analyse de conflits → teardown). s12 n'a pas de page propre : tout ce qu'il faisait est ici.

Le module assume une **limite documentée** dès sa docstring (lignes 6–13) : `os.chdir` est global au process et les outils de [[tools-py]] résolvent leurs chemins relatifs au moment de l'appel. Le sandwich `chdir → agent_loop → restore` est donc protégé par un verrou module-level : les tâches « parallèles » sérialisent leur phase d'exécution d'agent, seuls le setup, le teardown git et l'analyse restent concurrents. C'est un choix explicite : l'isolation garantie prime sur le parallélisme réel, l'éliminer demanderait de passer le répertoire explicitement à chaque outil.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–14 | Docstring | Cycle de vie s23 + limite documentée du chdir global |
| 15–24 | Imports | stdlib + `paint` ([[core-py]]) et `agent_loop` ([[loop-py]]) |
| 26–30 | État module | `_REPO_CWD` figé à l'import (FIX), `_CHDIR_LOCK` |
| 33–37 | Helper | `_git()` — wrapper subprocess unique |
| 40–71 | Création | `create_worktree()` : sanitisation, suffixe, garde-fous |
| 74–84 | Démontage | `remove_worktree()` tolérant |
| 87–100 | Maintenance | `prune_stale()` — purge des restes de crashs |
| 103–144 | Cycle de vie | `run_task_in_worktree()` — le cœur du module |
| 147–172 | Parallélisme | `run_parallel_tasks()` + analyse de conflits |

## Constantes et configuration

- **`_REPO_CWD` (ligne 29)** : `os.getcwd()` capturé **une seule fois à l'import** — la référence stable de toutes les commandes git du dépôt principal (voir « Bugs corrigés »).
- **`_CHDIR_LOCK` (ligne 30)** : `threading.Lock` module-level qui sérialise les fenêtres `chdir`, puisque le répertoire courant est global au process.

## Les fonctions, une à une

### `_git(*args, cwd=None)` — lignes 33–37

L'unique point de passage vers git : `subprocess.run(["git", *args], ...)`, retourne `(succès, sortie)` — stdout si succès, stderr (ou stdout en repli) si échec. Détail décisif :

```python
    r = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd or _REPO_CWD)
```

Le `cwd` par défaut n'est **pas** le répertoire courant du process mais `_REPO_CWD` : une commande git « du dépôt principal » vise toujours le dépôt principal, même si un autre thread est en plein sandwich `chdir`. Les opérations dans un worktree passent `cwd=path` explicitement.

### `create_worktree(task_id)` — lignes 40–71

Crée la paire branche + répertoire, avec quatre garde-fous successifs :

1. **Lignes 46–48** : `rev-parse --show-toplevel` — pas un dépôt git → `RuntimeError`.
2. **Lignes 49–50** : `symbolic-ref --short HEAD` échoue → HEAD détaché → `RuntimeError` (une branche `task/...` forkée d'un HEAD détaché serait ambiguë).
3. **Lignes 51–53** : arbre sale → simple **warning** jaune : la branche forke du dernier commit, les modifs non commitées n'y seront pas. On n'empêche pas, on prévient.
4. **Lignes 54–61** : sanitisation du nom (`re.sub(r"[^a-zA-Z0-9_-]", "-", task_id)[:40]`) puis recherche d'un nom de branche libre :

```python
    branch, n = f"task/{safe}", 1
    while _git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")[0]:
        n += 1
        branch = f"task/{safe}-{n}"
```

Le répertoire est créé **hors du dépôt**, en frère (`Path(root).parent / f".worktree-{safe[:20]}{suffix}"`, ligne 63) : un worktree interne polluerait `git status` et les globs des agents. S'il existe déjà (reste d'un run crashé), nettoyage préventif `worktree remove --force` + `rmtree` (lignes 64–66) avant le `git worktree add -b branch path` final.

### `remove_worktree(path, branch, keep_branch=False)` — lignes 74–84

Démontage **tolérant** : chaque étape tente sa part, aucune ne bloque les autres. `worktree remove --force`, puis `rmtree(ignore_errors=True)` en rattrapage si le répertoire survit (verrous de fichiers Windows), puis `branch -D` (sauf `keep_branch`), et enfin `git worktree prune` pour purger les métadonnées si `remove` a échoué avant le `rmtree`.

### `prune_stale()` — lignes 87–100

Maintenance préventive : parcourt `git worktree list --porcelain` et supprime toute entrée dont le répertoire a disparu (crash d'un run précédent). La ligne `worktree <chemin>` est découpée par `line[9:]` (longueur du préfixe), et la racine du dépôt elle-même est exclue (`p != root`, ligne 96). Retourne le compte ; appelée en tête de `run_parallel_tasks`.

### `run_task_in_worktree(task, task_id=None)` — lignes 103–144

Le cœur du module : le cycle de vie complet d'une tâche isolée, qui retourne toujours un dict `{id, task, status, result, error, files}` (`status` initialisé à `"failed"`, ligne 111 — on ne passe à `"done"` qu'en fin de parcours heureux). Le setup qui échoue retourne tôt sans rien à nettoyer (lignes 112–117). Ensuite :

```python
    base = _git("rev-parse", "HEAD", cwd=path)[1]  # point de fork, pour le diff final
    try:
        system = (f"Tu es un agent de code dans le worktree isolé {path}. "
                  f"Objectif : {task}. Résume tes changements à la fin.")
        with _CHDIR_LOCK:  # voir docstring module : fenêtre chdir sérialisée
            old = os.getcwd()
            try:
                os.chdir(path)
                final = agent_loop([{"role": "user", "content": task}], system=system)
            finally:
                os.chdir(old)
```

- **Ligne 118** : le SHA du point de fork est mémorisé avant tout travail — c'est la borne gauche du diff final.
- **Lignes 122–128** : le sandwich `chdir` sous `_CHDIR_LOCK`, avec un `finally` interne qui restaure le répertoire même si l'agent crashe. L'agent utilise la façade sync `agent_loop` de [[loop-py]] — on est dans un thread, pas dans l'event loop principale.
- **Lignes 130–132** : si l'arbre du worktree est sale après le passage de l'agent, `add -A` + `commit` — sans commit, le diff ne verrait rien.
- **Lignes 133–136** : `git diff --name-only base..branch` relève les fichiers touchés, **avant** le teardown (voir « Bugs corrigés »). Le diff tourne depuis `_REPO_CWD` : la branche existe encore à ce moment-là.
- **Ligne 143** : `remove_worktree(path, branch)` dans le `finally` externe — nettoyage garanti, succès ou crash.

### `run_parallel_tasks(tasks)` — lignes 147–172

Une tâche par thread daemon (lignes 157–162), chacune dans son worktree (`task_id=f"T-{i + 1}"`), résultats rangés par index dans une liste pré-allouée — pas de partage d'état mutable entre threads au-delà de `results[i]`. Avant le lancement, `prune_stale()` purge les restes éventuels. Après le `join`, l'analyse de conflits croise les listes `files` déjà relevées :

```python
    done = [r for r in results if r.get("status") == "done"]
    for i, a in enumerate(done):  # intersections paire à paire sur les diffs déjà relevés
        for b in done[i + 1:]:
            common = sorted(set(a["files"]) & set(b["files"]))
```

Tout fichier touché par ≥ 2 tâches produit un message `T-1 <-> T-2 : fichiers…` (affiché en jaune, 5 fichiers max), ajouté au champ `conflicts` des **deux** résultats concernés (lignes 168–171). Aucune commande git ici : les branches sont déjà supprimées, mais les données nécessaires ont été capturées pendant le cycle de vie.

## Bugs de la source corrigés ici

- **`_REPO_CWD` figé à l'import (lignes 26–30)** — dans s23, les commandes git « du dépôt principal » utilisaient le répertoire courant du process. Or pendant le sandwich `chdir` d'un autre thread, `os.getcwd()` pointe dans *son* worktree : les commandes du dépôt principal visaient le mauvais répertoire. Correction : le cwd du dépôt est capturé une fois à l'import et passé explicitement par `_git()`.
- **Branche homonyme → suffixe (lignes 55–61)** — s23 détruisait la branche préexistante via `branch -D`, y compris une éventuelle branche de travail humaine qui portait le même nom. Correction : on cherche un nom libre en suffixant `-2`, `-3`… ; rien d'existant n'est jamais détruit à la création.
- **Fichiers relevés AVANT la suppression de la branche (lignes 133–136)** — s23 lançait l'analyse de conflits *après* le teardown : le `branch -D` la neutralisait (diff sur une branche disparue), la feature était annoncée mais morte. Correction : chaque tâche relève son `git diff --name-only` dans le `try`, avant le `finally` qui démonte ; `run_parallel_tasks` n'a plus qu'à intersecter des listes en mémoire.

## Qui l'utilise

- [[main-py]] — `import worktree` ; la commande `:wt <t1> | <t2> ...` appelle `run_parallel_tasks` via `asyncio.to_thread` (les threads et le `join` bloquant ne doivent pas geler l'event loop du REPL).

C'est le seul importeur : le module est une feuille de l'architecture, branchée directement sur le REPL.

## Pièges et détails d'implémentation

- **Le « parallélisme » est partiel** : `_CHDIR_LOCK` sérialise la phase `agent_loop` de chaque tâche. Avec 3 tâches, les agents tournent l'un après l'autre ; seuls setup git, commit, diff et teardown se recouvrent. C'est le prix du `os.chdir` global, assumé dans la docstring.
- **Le diff final exige que la branche existe encore** : `_git("diff", "--name-only", base, branch)` tourne depuis le dépôt principal — déplacer cet appel après `remove_worktree` recréerait exactement le bug de s23.
- **Threads daemon** : si le process principal meurt brutalement, les `finally` peuvent ne pas s'exécuter — c'est `prune_stale()` qui rattrape les worktrees orphelins au run suivant.
- **Arbre sale = warning, pas blocage** : la branche forke du dernier commit ; des modifs locales non commitées n'apparaîtront pas dans le worktree. Le message jaune (lignes 52–53) est le seul filet.
- **`remove_worktree` avant `rmtree`** : sous Windows, des verrous de fichiers peuvent faire échouer `git worktree remove` ; le `rmtree(ignore_errors=True)` de rattrapage puis le `worktree prune` final garantissent qu'on ne laisse ni répertoire ni métadonnées.

## Liens

- Modules liés : [[loop-py]] (la façade sync `agent_loop` exécutée dans chaque worktree), [[core-py]] (`paint`), [[main-py]] (commande `:wt`), [[agents-py]] (l'autre modèle de parallélisme — workers sans isolation, sur l'arbre partagé)
