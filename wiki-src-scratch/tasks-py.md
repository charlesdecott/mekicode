---
title: "tasks.py · Todos & graphe de tâches"
phase: "Contexte & tâches"
fichier: "src_scratch/tasks.py"
lignes: 221
tags: [todos, graphe-de-taches, dependances, board, claim, priorite]
---

# tasks.py · Todos & graphe de tâches

> **En une phrase** : trois niveaux de planification dans un seul module — la todo-list éphémère que le modèle s'écrit à lui-même (s03), le graphe de tâches persistant à dépendances et priorités (s07), et le board partagé que des workers autonomes réclament atomiquement (s11).

## Rôle dans le harness

La source étalait la planification sur trois sessions qui rejouaient chacune le socle : s03 introduisait `todo_write`/`todo_read` (le plan que le modèle maintient pour ne pas perdre le fil), s07 ajoutait un graphe persistant de tâches avec dépendances, et s11 transformait ce graphe en board multi-agents avec réclamation atomique. Ici, tout tient en 221 lignes autour d'un invariant unique : **toute lecture-modification-écriture du fichier de tâches se fait sous `_TASKS_LOCK`** — c'est ce qui rend `claim_next_task` sûr quand plusieurs threads workers de [[agents-py]] sondent le board en même temps.

Le module est aussi un fournisseur d'outils : cinq schémas (`todo_write`, `todo_read`, `task_add`, `task_list`, `task_complete`) sont enregistrés à l'import via `register_tool` de [[tools-py]] — le modèle planifie avec les mêmes primitives que les workers. Les fonctions réservées au harness (`claim_next_task`, `complete_task`, `fail_task`, `requeue`) ne sont volontairement *pas* exposées au modèle.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–14 | Docstring, imports, constantes | `TODO_FILE`, `TASKS_FILE`, `_TASKS_LOCK`, `_PRIORITY` |
| 17–37 | I/O JSON | `_load` (avec quarantaine `.bak`), `_save` |
| 40–56 | Todos (s03) | `todo_write`, `todo_read` |
| 59–131 | Graphe de tâches (s07) | `_next_id`, `_find`, `task_add`, `task_list`, `task_update`, `task_complete`, `_next_candidate`, `task_next` |
| 134–175 | Board autonome (s11) | `claim_next_task`, `_finish`, `complete_task`, `fail_task`, `requeue` |
| 178–221 | Outils modèle | 5 appels `register_tool` à l'import |

## Constantes et configuration

- **`TODO_FILE` / `TASKS_FILE` (lignes 11–12)** : `STATE_DIR / "todos.json"` et `STATE_DIR / "tasks.json"` — deux fichiers distincts : la todo-list est un brouillon écrasable, le graphe est un état durable.
- **`_TASKS_LOCK` (ligne 13)** : `threading.Lock()` unique pour tout le module — sérialise les accès concurrents au graphe.
- **`_PRIORITY` (ligne 14)** : `{"high": 0, "normal": 1, "medium": 1, "low": 2}` — `medium` est toléré comme alias de `normal` parce que l'enum de la source l'utilisait ; les anciennes données restent lisibles.

## Les fonctions, une à une

### `_load(path=TASKS_FILE)` — lignes 19–33

Toute lecture passe par ici. Le cas nominal est trivial (`json.loads`) ; l'intérêt est le chemin d'erreur :

```python
    except (json.JSONDecodeError, OSError) as e:
        bak = path.with_suffix(path.suffix + ".bak")
        try:
            path.replace(bak)
            print(paint(f"[tasks] {path.name} corrompu ({e}) — sauvegardé en {bak.name}", "yellow"))
        except OSError:
            print(paint(f"[tasks] {path.name} illisible : {e}", "red"))
        return []
```

Un fichier corrompu est **mis en quarantaine** (`tasks.json` → `tasks.json.bak`) avec avertissement jaune, et le module repart à vide — les données fautives restent inspectables. Si même le renommage échoue, on signale en rouge et on continue. Dans la source (s07), la corruption était fatale en silence : le `_save` suivant écrasait le graphe entier.

### `_save(data, path=TASKS_FILE)` — lignes 36–37

`json.dumps(indent=2, ensure_ascii=False)` — JSON lisible par un humain, accents en clair. Pas d'écriture atomique (pas de fichier temporaire + rename) : la protection contre la corruption est du côté lecture, dans `_load`.

### `todo_write(todos)` — lignes 42–49

Écrase la todo-list complète, au format s03 (items `{content, status}`). Les deux lignes de normalisation (44–46) acceptent les entrées molles du modèle : une chaîne nue devient `{"content": str(t)}`, un `status` absent devient `"pending"`. Le retour rejoue le plan numéroté complet — le modèle voit ce qu'il vient d'écrire et peut le corriger.

### `todo_read()` — lignes 52–56

Relit la liste et la met en forme `[i] [status] content` (le `:12s` aligne la colonne statut). Liste absente ou vide → `"(no todo list found - please use todo_write first)"` : l'erreur enseigne le bon usage au modèle au lieu de renvoyer du vide.

### `_next_id(tasks)` — lignes 61–65

Ids courts `t1, t2…` — la source utilisait des hex UUID peu lisibles pour le modèle. Le max est calculé sur les seuls ids au format `tN` (lignes 63–64) : un id exotique dans le fichier est ignoré sans crash, et `max(nums, default=0) + 1` démarre à `t1` sur un graphe vide.

### `_find(tasks, task_id)` — lignes 68–75

Résolution d'id en deux temps : correspondance exacte d'abord, puis préfixe **unique**.

```python
    pref = [t for t in tasks if task_id and t["id"].startswith(task_id)]
    return pref[0] if len(pref) == 1 else None
```

Le `task_id and` rejette le préfixe vide, et `len(pref) == 1` rejette l'ambigu — la source matchait la première tâche du fichier dans les deux cas (deuxième FIX du fichier). L'exact gagne toujours : `"t1"` désigne `t1` même si `t10` existe (la boucle des lignes 71–73 retourne avant le test de préfixe).

### `task_add(description, deps=None, priority="normal")` — lignes 78–88

Crée une tâche `{id, description, status: "pending", priority, depends_on, result: ""}` sous verrou. Les dépendances inconnues ne sont **pas** rejetées : elles sont signalées dans le retour (`(warning: unknown deps [...])`, lignes 81–82 et 87) — le modèle peut créer les tâches dans le désordre, mais il est prévenu qu'une dep fantôme bloquera la tâche à jamais.

### `task_list()` — lignes 91–100

Vue texte du graphe : `[id] [status] [priority] [needs: deps] description`, colonnes alignées. C'est le retour de la commande `:tasks` de [[main-py]] et de l'outil `task_list` du modèle. Graphe vide → `"(no tasks currently in the system)"`.

### `task_update(task_id, status)` — lignes 103–111

Le mutateur générique : résout via `_find` (donc accepte les préfixes uniques), écrit le nouveau statut sous verrou. Le retour cite `t['id']` résolu, pas le `task_id` saisi — le modèle apprend l'id canonique. Aucune validation du `status` : c'est une chaîne libre.

### `task_complete(task_id)` — lignes 114–115

Sucre : `task_update(task_id, "done")`. C'est la version exposée au modèle (l'outil enregistre celle-ci, pas `task_update`).

### `_next_candidate(tasks)` — lignes 118–126

Le cœur de l'ordonnancement : la prochaine tâche `pending` dont toutes les deps sont `done`.

```python
    done = {t["id"] for t in tasks if t["status"] == "done"}
    ready = [(i, t) for i, t in enumerate(tasks)
             if t["status"] == "pending" and all(d in done for d in t.get("depends_on", []))]
    if not ready:
        return None
    return min(ready, key=lambda it: (_PRIORITY.get(it[1].get("priority", "normal"), 1), it[0]))[1]
```

- La clé de tri est le tuple `(priorité, indice d'insertion)` : `high` passe avant `normal` avant `low`, et à priorité égale c'est l'ordre d'arrivée (FIFO stable). La source ignorait totalement `priority` (troisième FIX).
- Une priorité inconnue retombe sur 1 (= normal) via le défaut de `.get` — donnée sale tolérée.
- Pas de verrou ici : c'est un helper pur ; les appelants (`task_next`, `claim_next_task`) verrouillent.

### `task_next()` — lignes 129–131

Lecture seule sous verrou : `_next_candidate(_load())`. Donne « la prochaine tâche » sans la réclamer — utile pour inspecter sans muter.

### `claim_next_task(agent)` — lignes 136–144

La primitive s11 : **réclamation atomique**. Sous `_TASKS_LOCK`, on charge, on choisit, on marque `in_progress` + `claimed_by`, on sauve — le tout d'un bloc :

```python
    with _TASKS_LOCK:
        tasks = _load()
        t = _next_candidate(tasks)
        if t:
            t["status"], t["claimed_by"] = "in_progress", agent
            _save(tasks)
        return t
```

Deux workers qui appellent en même temps ne peuvent pas réclamer la même tâche : le second entre dans le verrou après le `_save` du premier et voit la tâche déjà `in_progress`. C'est le contrat dont dépend `run_autonomous_agent` de [[agents-py]].

### `_finish(task_id, status, key, value)` — lignes 147–153

Factorisation des deux issues d'une tâche : sous verrou, retrouve la tâche et écrit `status` + un champ libre (`result` ou `error`). Une tâche introuvable est ignorée sans bruit — le worker n'a rien d'utile à faire de cette erreur.

### `complete_task(task_id, result="")` / `fail_task(task_id, error="")` — lignes 156–157 et 160–161

Les deux façades de `_finish` : `("done", "result", …)` et `("failed", "error", …)`. Appelées par le cycle worker de [[agents-py]] avec le texte final de l'`agent_loop` (succès) ou le message d'exception (échec).

### `requeue(task_id=None)` — lignes 164–175

La porte de sortie du cul-de-sac s11 : repasse les tâches `failed` en `pending` (toutes, ou une seule si `task_id` est fourni), en purgeant `claimed_by` et `error` (ligne 172) pour qu'elles repartent propres. Retourne le nombre de tâches relancées — c'est ce qu'affiche la commande `:requeue` de [[main-py]]. Le `_save` n'a lieu que si quelque chose a changé (lignes 173–174).

### Enregistrement des outils modèle — lignes 180–221

Cinq `register_tool` à l'import : `todo_write` (180–189, avec le schéma imbriqué des items `{content, status}`), `todo_read` (191–195), `task_add` (197–207, paramètres `description`/`depends_on`/`priority` avec enum `["high", "normal", "low"]`), `task_list` (209–213), `task_complete` (215–221). Les handlers sont des lambdas qui déballent l'input — `task_add` montre le motif des optionnels : `inp.get("depends_on")` et `inp.get("priority", "normal")`.

## Bugs de la source corrigés ici

- **Graphe écrasé sur JSON corrompu (s07)** — lignes 20–21, dans `_load`. Dans la source, un `tasks.json` invalide levait une exception non gérée ou, pire, repartait à vide et le `_save` suivant écrasait définitivement les données. Ici : le fichier fautif est renommé en `.bak` avec avertissement, rien n'est perdu.
- **Résolution d'id trop laxiste (s07)** — lignes 69–70, dans `_find`. La source faisait un match par préfixe sans contrôle : un préfixe vide ou partagé par plusieurs tâches désignait la *première tâche du fichier* — `task_complete("")` pouvait clore n'importe quoi. Ici : préfixe vide rejeté, préfixe ambigu rejeté, seule une correspondance unique passe.
- **`priority` jamais respectée (s07)** — ligne 120, dans `_next_candidate`. La source acceptait une priorité à la création mais `task_next` rendait la première tâche débloquée dans l'ordre du fichier. Ici : tri `high > normal > low` puis ordre d'insertion.
- **`failed` = impasse définitive (s11)** — lignes 165–166, `requeue`. Dans la source, une tâche échouée restait `failed` pour toujours : ses dépendantes ne se débloquaient jamais et aucun worker ne pouvait la reprendre. `requeue` la repasse en `pending` (champs `claimed_by`/`error` purgés), re-claimable au prochain sondage.

## Qui l'utilise

- **[[agents-py]]** — `from tasks import claim_next_task, complete_task, fail_task` : le cycle des workers autonomes (`run_autonomous_agent`) réclame une tâche, lance un `agent_loop` dessus, puis la clôt en succès ou en échec.
- **[[main-py]]** — `import tasks` : les commandes REPL `:todos` (→ `todo_read`), `:tasks` (→ `task_list`) et `:requeue` (→ `requeue`).
- **Indirectement, le modèle** : les cinq outils enregistrés à l'import entrent dans le registre de [[tools-py]] et sont servis par les boucles de [[loop-py]].

## Pièges et détails d'implémentation

- **Le verrou est intra-processus** : `threading.Lock` protège les threads (workers de [[agents-py]], REPL) du même processus Python. Deux *processus* distincts partageant le même `tasks.json` se marcheraient dessus — hors périmètre du harness actuel.
- **`_save` n'est pas atomique** : un crash en pleine écriture peut laisser un JSON tronqué. Le filet est en aval : au prochain `_load`, le fichier part en `.bak` et le graphe repart à vide — récupérable à la main, mais pas automatiquement.
- **`task_update` ne valide pas le statut** : `task_update("t1", "bananas")` passe. Comme l'outil modèle n'expose que `task_complete`, seul le code du harness peut introduire un statut exotique — qui rendrait la tâche invisible pour `_next_candidate` (ni `pending`, ni `done`).
- **Une dep inconnue bloque sans bruit après la création** : `task_add` avertit une fois dans son retour, mais une tâche dont une dépendance n'existe pas restera `pending` éternellement (`all(d in done …)` ne sera jamais vrai). `task_list` permet de le diagnostiquer via la colonne `[needs: …]`.
- **`todo_write` écrase tout** : c'est le contrat s03 (la description de l'outil le dit : *« Overwrites the whole list »*). Le modèle doit renvoyer la liste complète à chaque mise à jour de statut — pas de mise à jour incrémentale.

## Liens

- Modules liés : [[core-py]] (`STATE_DIR`, `paint`), [[tools-py]] (`register_tool`), [[agents-py]] (workers consommateurs du board), [[main-py]] (commandes `:todos`, `:tasks`, `:requeue`), [[loop-py]] (sert les outils au modèle)
- Page voisine de la phase : [[context-py]]
