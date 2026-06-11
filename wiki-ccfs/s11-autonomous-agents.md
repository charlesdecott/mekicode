---
title: "s11 · Agents autonomes"
session: 11
phase: "Async & multi-agents"
fichier: "inspiration/claude-code-from-scratch/s11_autonomous_agents.py"
lignes: 355
tags: [task-board, claim-atomique, threading, blackboard, autonomie, multi-agent]
prev: "s10-team-protocols"
next: "s12-worktree-task-isolation"
---

# s11 · Agents autonomes

> **En une phrase** : le lead ne délègue plus à des agents nommés — il poste des tâches sur un board JSON partagé, et des workers en threads les **réclament eux-mêmes** atomiquement (`threading.Lock`), résolvent les dépendances, exécutent et publient leur résultat : l'architecture « blackboard ».

## Rôle dans le harness

Toute la phase 3 attaque le plafond mono-agent (*« Breaking the single-agent ceiling »*, dit le README) : [[s08-background-tasks]] détache l'exécution en threads démons, [[s09-agent-teams]] crée des équipiers persistants avec des boîtes aux lettres JSONL, [[s10-team-protocols]] structure leur dialogue en FSM. Mais dans tous ces modèles, c'est le lead qui **assigne** : il connaît chaque équipier et lui adresse du travail. Dès que l'équipe grandit, le lead devient le goulot d'étranglement — chaque assignation passe par lui.

s11 inverse la responsabilité, c'est le motto du fichier : *« Teammates scan the board and claim tasks themselves »*. Le lead ne gère plus des individus, il gère un **tableau de tâches** (le fichier `.agent_tasks.json`, hérité de [[s07-task-system]]) : il y poste des entrées avec dépendances via un nouvel outil `post_task`. De l'autre côté, des workers anonymes tournent en boucle : scanner le board, repérer une tâche `pending` dont toutes les dépendances sont `done`, la réclamer, l'exécuter, écrire le résultat. Le point dur est la **réclamation atomique** : deux workers qui scannent au même instant ne doivent jamais réclamer la même tâche — d'où un `threading.Lock` global autour de chaque transition lecture-modification-écriture du fichier.

Le tableau « Claude Code Analog » du README est explicite : cette session est marquée *« Beyond real CC »*. Le vrai Claude Code ne pratique pas l'auto-assignation — ses sous-agents et équipes restent pilotés par un agent principal qui distribue le travail. s11 explore donc un cran d'autonomie **au-delà** du produit réel : un pattern blackboard classique des systèmes multi-agents, où la coordination passe par l'état partagé et non par des messages dirigés. C'est aussi le complément naturel de la résilience : une tâche dont le worker plante passe en `failed` au lieu de disparaître, et reste inspectable sur le board.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–26 | Shebang & docstring | Motto, 4 concepts clés (board partagé, claim atomique, auto-organisation, résilience), flux opérationnel |
| 28–36 | Imports stdlib | `json`, `threading`, `uuid`, `pathlib`… (`time` et `sys` importés mais jamais utilisés) |
| 38–47 | Imports core | 6 symboles de [[core-py]] |
| 49–55 | Configuration | `TASKS_FILE`, `_TASKS_LOCK` |
| 57–81 | I/O du board | `_load_tasks()`, `_save_tasks()` |
| 84–154 | Transitions d'état atomiques | `claim_next_task()`, `complete_task()`, `fail_task()` |
| 158–223 | Worker autonome | `run_autonomous_agent()` : poll → claim → boucle LLM → done/failed |
| 226–286 | Outillage du lead | `_post_new_task()`, `LEAD_TOOLS`, `LEAD_DISPATCH` |
| 289–355 | Point d'entrée | `main()` : 2 threads workers + REPL du lead, arrêt propre via `Event` |

## Constantes et configuration

- **`TASKS_FILE` (ligne 52)** : `Path(".agent_tasks.json")` — le board persistant, **le même fichier** que le graphe de tâches introduit par [[s07-task-system]] (le commentaire du source le rappelle). C'est l'état partagé du blackboard : lead et workers ne communiquent que par lui.
- **`_TASKS_LOCK` (ligne 55)** : `threading.Lock()` global — sérialise tous les accès au fichier entre les threads du processus. Chaque fonction de transition prend le verrou pour la séquence complète *lire → modifier → écrire*, jamais pour une seule moitié.
- **`LEAD_TOOLS` (lignes 250–273)** : `EXTENDED_TOOLS + [...]` — la palette standard de [[core-py]] enrichie de deux outils réservés au lead : `post_task` (avec `description` obligatoire, `depends_on` en tableau d'IDs et `priority` en enum `high/medium/low`) et `task_status` (schéma vide : aucun paramètre).
- **`LEAD_DISPATCH` (lignes 276–286)** : la table de routage du lead, par extension de dict :

```python
LEAD_DISPATCH: Dict[str, Any] = {
    **EXTENDED_DISPATCH,
    "post_task": lambda inp: _post_new_task(
        inp["description"], 
        inp.get("depends_on"), 
        inp.get("priority", "medium")
    ),
    "task_status": lambda inp: "\n".join(
        f"[{t['id']}] [{t['status']:12}] {t['description']}" for t in _load_tasks()
    ) or "(the task board is currently empty)"
}
```

`task_status` est implémenté **directement dans la lambda** : un rendu une-ligne-par-tâche avec le statut paddé sur 12 caractères (`{t['status']:12}` aligne les colonnes). Notez que cette lambda appelle `_load_tasks()` **sans prendre `_TASKS_LOCK`** — une lecture seule, tolérée mais théoriquement concurrente d'une écriture worker.

## Les fonctions, une à une

### `_load_tasks()` — lignes 59–71

Lit le board depuis le JSON. Deux garde-fous : fichier absent → `[]` ; fichier corrompu → `[]` aussi.

```python
    if not TASKS_FILE.exists():
        return []
    try:
        return json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return []
```

Le `except (json.JSONDecodeError, IOError)` rend la lecture infaillible mais **silencieusement destructrice** : un board corrompu est traité comme un board vide, et la prochaine `_save_tasks` écrasera définitivement le contenu illisible. Robustesse au prix de la perte de données — un choix pédagogique assumé.

### `_save_tasks(tasks)` — lignes 74–81

```python
    TASKS_FILE.write_text(json.dumps(tasks, indent=2), encoding="utf-8")
```

Réécriture intégrale du fichier à chaque transition (pas d'append, pas de patch). `indent=2` garde le board lisible à l'œil nu — on peut l'ouvrir dans un éditeur pendant que les agents tournent. Pas d'écriture atomique (fichier temporaire + rename) : un crash au milieu du `write_text` laisse un JSON tronqué, que `_load_tasks` traduira en board vide.

### `claim_next_task(agent_id)` — lignes 86–119

Le cœur de la session : la réclamation atomique.

```python
    # Enter critical section to prevent double-claiming by separate threads
    with _TASKS_LOCK:
        tasks = _load_tasks()
        
        # Identify all successfully completed task IDs
        done_ids = {t["id"] for t in tasks if t["status"] == "done"}
        
        for t in tasks:
            # We only care about tasks awaiting an agent
            if t["status"] != "pending":
                continue
                
            # Check if all dependencies are satisfied
            dependencies = t.get("depends_on", [])
            if all(dep in done_ids for dep in dependencies):
                # Transition state immediately to prevent other agents from seeing it as pending
                t["status"] = "in_progress"
                t["claimed_by"] = agent_id
                _save_tasks(tasks)
                return t
                
    return None
```

- **Ligne 99** : tout le cycle *charger → chercher → marquer → sauver* est dans le `with _TASKS_LOCK` — c'est ce qui rend le claim atomique. Si le verrou n'entourait que la sauvegarde, deux workers pourraient charger le même board, voir la même tâche `pending` et la réclamer tous les deux.
- **Ligne 103** : `done_ids` est un set des tâches terminées — une tâche est « débloquée » si tous ses `depends_on` y figurent (lignes 111–112, `all(...)`). Une liste de dépendances vide passe trivialement le `all`.
- **Lignes 114–116** : la transition `pending → in_progress` + `claimed_by` est écrite sur disque **avant** de retourner la tâche — au moment où un autre worker obtiendra le verrou, il ne verra plus cette tâche comme disponible.
- À noter : le champ `priority` posté par le lead n'est **jamais consulté** — les tâches sont parcourues dans l'ordre d'insertion du fichier, la première débloquée gagne.

### `complete_task(task_id, result)` — lignes 122–137

Sous verrou : recherche la tâche par ID, passe `status` à `"done"`, stocke le texte final dans `result`, sauve, `break`. C'est cette écriture qui débloque en cascade les tâches dépendantes — au prochain poll d'un worker, `done_ids` contiendra ce nouvel ID.

### `fail_task(task_id, error_message)` — lignes 140–154

Symétrique de `complete_task` : `status = "failed"`, message dans `error`. La docstring du module parle de *retry logic* « manuelle ou automatisée » — mais rien dans le code ne retente : une tâche `failed` reste `failed`, visible via `task_status`, et **bloque pour toujours** ses dépendantes (seul `done` alimente `done_ids`).

### `run_autonomous_agent(agent_name, stop_event)` — lignes 160–223

La boucle de vie d'un worker, exécutée dans son propre thread.

```python
    while not stop_event.is_set():
        # Attempt to claim a piece of work
        task = claim_next_task(agent_name)
        
        if not task:
            # No work available; back off for 1 second to save CPU/API calls
            stop_event.wait(timeout=1.0)
            continue
```

- **Ligne 186** : `stop_event.wait(timeout=1.0)` au lieu de `time.sleep(1)` — même délai, mais le wait se débloque **immédiatement** si l'événement d'arrêt est levé pendant l'attente. C'est ce qui rend le shutdown réactif (et ce qui rend l'import `time` de la ligne 32 inutile).
- **Ligne 193** : chaque tâche réclamée démarre un **historique neuf** (`worker_messages = [{"role": "user", "content": task["description"]}]`) — le worker n'a aucune mémoire d'une tâche à l'autre, exactement comme un sous-agent de [[s04-subagent]] : contexte isolé, jeté après usage.

La boucle interne (lignes 197–213) est un cycle think-act classique mais **non streamé** : `client.messages.create` direct (pas `stream_loop`), `max_tokens=4000`, outils standard `EXTENDED_TOOLS` exécutés par `dispatch_tools` de [[core-py]]. Le worker n'a pas accès à `post_task` : il exécute, il ne planifie pas.

```python
            # Extract final text and update the shared task board
            final_output = "".join(b.text for b in worker_messages[-1]["content"] if hasattr(b, "text"))
            complete_task(task["id"], final_output)
            print(f"\033[32m  [{agent_name}] completed: {task['id']}\033[0m")
            
        except Exception as e:
            # If the LLM loop crashes, mark the task as failed so it can be investigated
            fail_task(task["id"], str(e))
```

- **Ligne 216** : extraction du texte final par duck-typing (`hasattr(b, "text")`) sur les blocs du dernier message assistant — les blocs `tool_use` n'ont pas d'attribut `text` et sont filtrés.
- **Lignes 220–222** : le `try/except` englobe toute la boucle LLM — une exception (API, réseau, outil) ne tue pas le thread : la tâche passe en `failed` avec son message d'erreur, et le worker retourne poller le board. La résilience promise par la docstring tient en ces trois lignes.

### `_post_new_task(description, depends_on=None, priority="medium")` — lignes 228–246

L'implémentation de l'outil `post_task` du lead.

```python
    with _TASKS_LOCK:
        tasks = _load_tasks()
        task_id = uuid.uuid4().hex[:8]
        new_task = {
            "id":          task_id, 
            "description": description,
            "status":      "pending", 
            "priority":    priority,
            "depends_on":  depends_on or [], 
            "result":      ""
        }
        tasks.append(new_task)
        _save_tasks(tasks)
```

- **Ligne 234** : ID = 8 premiers hex d'un UUID4 — court, lisible dans les logs, collision improbable à cette échelle.
- **Ligne 246** : le retour `f"Task posted with ID {task_id}: ..."` renvoie l'ID **au modèle lead** — indispensable pour qu'il puisse poster la tâche suivante avec `depends_on: ["<cet id>"]` et construire le graphe de dépendances tour après tour.
- Même discipline que les autres transitions : tout sous `_TASKS_LOCK`, car les workers peuvent écrire le board au même moment.

### `main()` — lignes 291–350

Le chef d'orchestre : spawn des workers, puis REPL du lead.

```python
    NUM_WORKERS: int = 2
    stop_signal = threading.Event()
    worker_threads: List[threading.Thread] = []

    # 2. Spawn Autonomous Background Agents
    for i in range(NUM_WORKERS):
        worker_id = f"agent-{i+1}"
        thread = threading.Thread(
            target=run_autonomous_agent,
            args=(worker_id, stop_signal),
            daemon=True # Threads will stop when the main process dies
        )
        thread.start()
```

- **Lignes 301–309** : deux workers `agent-1`/`agent-2` partagent le **même** `stop_signal` — un seul `set()` arrête toute la flotte. `daemon=True` garantit que le processus peut mourir même si un worker est en plein appel API.
- **Lignes 315–320** : le system prompt du lead lui interdit explicitement d'implémenter : *« Do NOT perform implementation tasks yourself; let your autonomous team handle the claiming and execution of work. »* La division du travail est imposée par le prompt, pas par le code — le lead a pourtant `EXTENDED_TOOLS` dans sa palette.
- **Lignes 324–345** : REPL classique (`s11 >> `), tour du lead via `stream_loop` de [[core-py]] avec `LEAD_TOOLS`/`LEAD_DISPATCH`. L'historique `history` persiste entre les tours : le lead se souvient des IDs qu'il a postés.
- **Lignes 347–350** : le `finally` lève `stop_signal.set()` — mais ne fait **aucun `join()`** sur les threads : on signale, on n'attend pas (voir Pièges).

### Point d'entrée `if __name__ == "__main__"` — lignes 353–355

Appel direct de `main()` — pas de logique supplémentaire.

## Ce qui vient de [[core-py]]

Importés aux lignes 40–47 :

- **`client`** : le client Anthropic partagé — utilisé en direct (`client.messages.create`) par les workers, ligne 198.
- **`MODEL`** : l'ID de modèle (`MODEL_ID` du `.env`) — même modèle pour le lead et les workers.
- **`EXTENDED_TOOLS`** : les 6 schémas d'outils (bash, read, write, grep, glob, revert) — palette des workers, et base de `LEAD_TOOLS`.
- **`EXTENDED_DISPATCH`** : la table nom → handler correspondante — base de `LEAD_DISPATCH`.
- **`dispatch_tools`** : exécution des blocs `tool_use` + construction des `tool_result` — utilisé par les workers (ligne 212) ; c'est lui qui imprime les appels d'outils en jaune dans le terminal.
- **`stream_loop`** : la boucle streamée complète — réservée au **lead** (ligne 339), dont les réponses s'affichent token par token ; les workers, eux, restent silencieux entre deux logs de claim/complete.

## Pièges et détails d'implémentation

- **Le verrou est intra-processus seulement** : `threading.Lock` protège les threads d'un même interpréteur. Si deux *processus* s11 tournent sur le même répertoire (ou un s11 et un s07), le claim n'est plus atomique — double assignation possible. La version production de la coordination, c'est [[s22-production-mailbox]] (Redis).
- **Tâches `in_progress` orphelines** : à la sortie (`stop_signal.set()` sans `join`), un worker en plein travail est tué net par la fin du processus (`daemon=True`). Sa tâche reste `in_progress` sur le disque — et comme `claim_next_task` ne regarde que `pending`, **personne ne la reprendra jamais** au prochain lancement. Il faut éditer `.agent_tasks.json` à la main.
- **`.agent_tasks.json` survit entre les runs** : au démarrage, les workers pollent immédiatement — des tâches `pending` laissées par une session précédente (ou par [[s07-task-system]], même fichier) sont exécutées **avant même votre premier prompt**.
- **`failed` bloque la cascade** : `done_ids` ne contient que les `done` ; toute tâche dépendant d'une tâche `failed` reste `pending` pour toujours. Aucun mécanisme de retry malgré la promesse de la docstring.
- **`priority` est décorative** : stockée, affichée nulle part, jamais utilisée pour ordonner les claims — l'ordre du fichier fait loi.
- **Sorties de terminal entremêlées** : le lead streame pendant que les workers loggent leurs claims/outils — les lignes violettes/vertes des workers peuvent couper le texte cyan du lead en plein milieu. C'est inhérent au modèle « tout le monde écrit sur stdout » ; le vrai Claude Code sérialise l'affichage.

## Lancer la démo

```bash
python s11_autonomous_agents.py
```

Prérequis : `.env` avec `ANTHROPIC_API_KEY` et `MODEL_ID` (ou le proxy LiteLLM, voir le README). Supprimez un éventuel `.agent_tasks.json` résiduel avant de lancer, sinon les workers attaquent les vieilles tâches dès la seconde 0.

Au lancement : deux lignes grises `[agent-1] online — polling for tasks...`. Tapez une demande au prompt `s11 >> ` (ex. « analyse ce repo puis écris un résumé ») : le lead la découpe en `post_task` (visibles en jaune), puis — dans la seconde — les workers réclament (`claimed:` en violet), exécutent leurs outils, et terminent (`completed:` en vert). Demandez « task status » pour voir le board avec les statuts alignés. `q`, `exit` ou Ctrl+C pour sortir : `stop_signal` est levé et la session se ferme.

## Liens

- Socle : [[core-py]]
- Session précédente : [[s10-team-protocols]]
- Session suivante : [[s12-worktree-task-isolation]]
- Sessions liées : [[s07-task-system]] (le board `.agent_tasks.json` et son graphe de dépendances), [[s08-background-tasks]] (les threads démons), [[s09-agent-teams]] (le modèle « délégation » que s11 dépasse), [[s04-subagent]] (le contexte jeté par tâche), [[s22-production-mailbox]] (la coordination version production)
