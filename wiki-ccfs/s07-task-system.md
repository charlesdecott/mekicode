---
title: "s07 · Système de tâches"
session: 07
phase: "Connaissance & contexte"
fichier: "inspiration/claude-code-from-scratch/s07_task_system.py"
lignes: 313
tags: [tasks, dag, dependances, persistance, planning, json]
prev: "s06-context-compact"
next: "s08-background-tasks"
---

# s07 · Système de tâches

> **En une phrase** : quatre outils (`task_create`, `task_list`, `task_update`, `task_next`) remplacent la todo-list éphémère par un **graphe de dépendances persisté** dans `.agent_tasks.json` — le plan survit aux redémarrages et `task_next` calcule automatiquement la prochaine tâche débloquée.

## Rôle dans le harness

Le motto : *« Break big goals into small tasks, order them, persist to disk »*. La todo-list de [[s03-todo-write]] a deux limites structurelles : elle est **linéaire** (aucune notion de « B ne peut commencer qu'après A ») et **volatile** (elle vit dans la conversation ; fermez le terminal, le plan disparaît). Pour un projet multi-étapes qui s'étend sur plusieurs sessions, il faut un état de plan qui existe **en dehors du contexte** — c'est le troisième volet de la phase 2 du README : *« persisting task state across restarts »*.

La session apporte trois mécanismes (docstring, lignes 12–22) : un **DAG** (graphe orienté acyclique) où chaque tâche peut dépendre d'une ou plusieurs autres ; des **identifiants uniques** (8 caractères hex de UUID) qui lèvent toute ambiguïté lors des mises à jour ; et la **persistance JSON** qui permet de reprendre le travail après un redémarrage — ou de le **transmettre à d'autres agents** : le docstring annonce explicitement le handoff vers les sessions s09+, où le fichier de tâches devient le tableau partagé que les équipes ([[s09-agent-teams]]) et les agents autonomes ([[s11-autonomous-agents]]) consommeront.

Le tableau du README donne l'analogue Claude Code : **« Extended TodoWrite »** — la version musclée de l'outil de planification, avec dépendances et persistance en plus. La quatrième pièce, `task_next`, est la plus intéressante architecturalement : c'est le harness qui fait la **résolution de dépendances** (un calcul d'ensembles, déterministe), pas le modèle — on ne demande pas à un LLM de simuler un tri topologique à chaque tour, on lui donne un outil qui le fait exactement. Le projet jumeau learn-claude-code construit le même mécanisme dans sa session 12 (task system).

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–27 | Shebang & docstring | DAG, UUID, persistance, schéma de tâche (statuts, dépendances) |
| 29–35 | Imports stdlib | `json`, `uuid`, `Set`, etc. |
| 37–42 | Imports core | `EXTENDED_TOOLS`, `EXTENDED_DISPATCH`, `stream_loop` |
| 44–55 | Configuration | `TASKS_FILE`, `SYSTEM` |
| 57–88 | **Nouveau** | `_load_tasks()`, `_save_tasks()` : I/O du graphe |
| 91–203 | **Nouveau** | Les 4 outils : `run_task_create/list/update/next` |
| 206–267 | Schémas & dispatch | `TASK_TOOLS`, `TASK_DISPATCH` |
| 270–308 | REPL | `main()` |
| 311–313 | Point d'entrée | `if __name__ == "__main__"` |

## Constantes et configuration

- **`TASKS_FILE = Path(".agent_tasks.json")` (ligne 47)** : le graphe entier vit dans un seul fichier JSON, relatif au répertoire courant — un tableau de tâches par projet.
- **`SYSTEM` (lignes 50–55)** : le prompt système impose le protocole d'usage : *« Always call task_list or task_next before starting work to ensure you are working on the correct unblocked priority »* — consulter le tableau avant d'agir, comme s05 imposait de consulter les skills avant d'improviser. L'outil ne suffit pas ; il faut dire au modèle *quand* s'en servir.
- **`TASK_TOOLS` (lignes 209–250)** : `EXTENDED_TOOLS + [...]` — quatre schémas. `task_create` n'exige que `description` (`depends_on` et `priority` optionnels, `priority` contraint par `enum: ["high", "medium", "low"]`) ; `task_update` exige `task_id` + `status` (enum à 4 valeurs `pending/in_progress/done/failed`) ; `task_list` et `task_next` sont sans paramètre. Les enums dans les schémas sont la **validation côté modèle** — le harness, lui, ne revérifie pas (voir Pièges).
- **`TASK_DISPATCH` (lignes 253–267)** : `{**EXTENDED_DISPATCH, ...}` plus quatre lambdas qui déballent les arguments avec valeurs par défaut (`inp.get("priority", "medium")`, `inp.get("result", "")`) — la tolérance aux champs omis vit dans le dispatch, pas dans les fonctions.

## Les fonctions, une à une

### `_load_tasks()` — lignes 59–74

Lit le graphe depuis le JSON :

```python
    if not TASKS_FILE.exists():
        return []
    try:
        # Load and parse the JSON task list
        return json.loads(TASKS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        # Fallback for corrupted files
        return []
```

Fichier absent **ou corrompu** → liste vide, sans distinction ni avertissement. Robuste en surface, dangereux en profondeur : un JSON corrompu rend un graphe vide, et la **prochaine sauvegarde écrase définitivement** les données illisibles (voir Pièges). Chaque outil rappelle `_load_tasks()` à chaque invocation — le fichier est la seule source de vérité, il n'y a pas d'état en mémoire.

### `_save_tasks(tasks)` — lignes 77–88

Sérialise avec `indent=2` — le commentaire assume le choix : lisibilité humaine pour le débogage (et, dès s09+, pour les autres agents). Une `IOError` est imprimée en rouge mais **pas levée ni renvoyée** : l'outil appelant retournera quand même son message de succès au modèle, qui croira la tâche sauvée.

### `run_task_create(description, depends_on, priority)` — lignes 93–122

```python
    # Generate a unique 8-character ID for the task
    task_id = uuid.uuid4().hex[:8]
    
    new_task = {
        "id":          task_id,
        "description": description,
        "status":      "pending",
        "priority":    priority,
        "depends_on":  depends_on or [],
        "result":      "", # To be filled upon completion
    }
```

- **Ligne 108** : `uuid.uuid4().hex[:8]` — 8 caractères hex (4 milliards de combinaisons) : collision improbable à l'échelle d'un projet, et **non vérifiée**.
- **Ligne 115** : `depends_on or []` normalise le `None` du paramètre optionnel. En revanche, rien ne vérifie que les IDs listés **existent** : une dépendance fantôme (faute de frappe du modèle) bloque la tâche pour toujours.
- **Ligne 116** : le champ `result` est réservé dès la création — c'est la mémoire du travail accompli, que `task_update` remplira ; pour un agent qui reprend le projet, lire les `result` des tâches `done` reconstitue l'historique sans relire toute la conversation.
- Pattern I/O : `_load_tasks()` → mutation → `_save_tasks()` — chaque opération relit et réécrit **tout le fichier**. Simple et sans état, mais non atomique (voir Pièges).
- Le retour `f"Created task {task_id}: {description}"` donne l'ID au modèle — indispensable pour qu'il puisse créer les dépendances suivantes (`depends_on: ["a1b2c3d4"]`).

### `run_task_list()` — lignes 125–144

Formate le tableau complet, une ligne par tâche : `[id] [status] [priority] [needs: ...] description` avec des largeurs fixes (`{t['status']:12s}`, `{t['priority']:6s}`) pour l'alignement en colonnes — lisible autant par l'humain dans le terminal que par le modèle dans le `tool_result`. Cas vide : `"(no tasks currently in the system)"`.

### `run_task_update(task_id, status, result)` — lignes 147–176

```python
    for t in tasks:
        # Support updating by full ID or a unique prefix
        if t["id"].startswith(task_id):
            t["status"] = status
            if result:
                t["result"] = result
            found = True
            actual_id = t["id"]
            break
```

- **Ligne 164** : la recherche par **préfixe** (`startswith`) est un confort pour le modèle — citer `a1b2` suffit. Mais le `break` au premier match rend le tirage dépendant de l'ordre d'insertion : un préfixe ambigu met à jour la mauvaise tâche sans avertissement, et le cas dégénéré `task_id=""` matche **la première tâche du fichier** (tout `str.startswith("")` est vrai).
- **Lignes 165–167** : `status` écrase toujours ; `result` seulement s'il est non vide — on peut changer un statut sans effacer le résultat enregistré.
- Le harness ne valide pas `status` contre l'enum : c'est le schéma API qui contraint le modèle ; un appel programmatique peut écrire n'importe quoi.
- Échec : `f"Error: Task with ID '{task_id}' not found."` — message d'erreur exploitable par le modèle (relancer `task_list`, corriger l'ID).

### `run_task_next()` — lignes 179–203

Le résolveur de dépendances — la valeur ajoutée algorithmique de la session :

```python
    # Create a set of IDs for tasks that are fully completed
    done_ids: Set[str] = {t["id"] for t in tasks if t["status"] == "done"}
    
    for t in tasks:
        # We only care about tasks that haven't started yet
        if t["status"] != "pending":
            continue
            
        # Check if every dependency for this task is in the 'done_ids' set
        dependencies = t.get("depends_on", [])
        if all(dep in done_ids for dep in dependencies):
            return f"Suggested Next Task: [{t['id']}] (Priority: {t['priority']}) - {t['description']}"
            
    return "No unblocked tasks available. Either all tasks are done or there is a dependency circularity."
```

- **Ligne 191** : l'ensemble `done_ids` rend le test de déblocage O(1) par dépendance — seul `done` débloque ; `in_progress` ou `failed` ne comptent pas.
- **Lignes 199–201** : `all(dep in done_ids ...)` — sur une liste vide, `all()` vaut `True` : une tâche sans dépendance est toujours éligible. C'est ce qui amorce le graphe.
- **Première trouvée, première servie** : le parcours suit l'ordre du fichier (ordre de création) et s'arrête au premier match. La `priority` est *affichée* dans la suggestion mais **n'influence pas le choix** — une tâche `low` créée avant une `high` sera proposée d'abord. L'étiquette est cosmétique.
- **Ligne 203** : le message final attribue le blocage à « all tasks are done or … dependency circularity » — en réalité il couvre aussi les cas non cités : dépendance `failed` (jamais débloquée), dépendance inexistante. Et aucune détection de cycle n'existe réellement dans le code : le message nomme un problème que rien ne diagnostique.

### `main()` — lignes 272–308

Le REPL standard du dépôt : bandeau gris annonçant le fichier de tâches (ligne 277), prompt cyan `s07 >> `, sortie sur `EOFError`/`KeyboardInterrupt`, mots de sortie, puis pour chaque requête `stream_loop(messages=history, tools=TASK_TOOLS, dispatch=TASK_DISPATCH, system=SYSTEM)`. Comme en s05, toute la spécificité tient dans les trois arguments. Point d'entrée : lignes 311–313.

## Ce qui vient de [[core-py]]

- **`EXTENDED_TOOLS`** : les 6 schémas de base, que `TASK_TOOLS` étend par concaténation — l'agent garde bash/read/write/grep/glob/revert pour *exécuter* les tâches qu'il planifie.
- **`EXTENDED_DISPATCH`** : les handlers de base, hérités par `**` dans `TASK_DISPATCH`.
- **`stream_loop`** : la boucle agentique complète — la session ne contient que des outils et leur état, zéro logique de boucle.

## Pièges et détails d'implémentation

- **Corruption = effacement différé** : `_load_tasks()` transforme un JSON corrompu en liste vide sans bruit ; le premier `_save_tasks()` suivant écrase le fichier — les données illisibles deviennent des données détruites.
- **Le préfixe vide matche tout** : `t["id"].startswith("")` est vrai pour toutes les tâches — `task_update("", "done")` marque la première tâche du fichier comme faite. Aucun contrôle d'ambiguïté de préfixe non plus.
- **`priority` est décorative dans `task_next`** : elle est rangée, affichée, contrainte par enum… mais le choix de la prochaine tâche est purement l'ordre d'insertion. Le nom du paramètre promet plus que l'algorithme ne tient.
- **`failed` est un cul-de-sac** : seules les tâches `done` débloquent leurs dépendantes ; une dépendance `failed` bloque sa descendance pour toujours, sans mécanisme de retry ni message dédié.
- **`depends_on` non validé à la création** : un ID inexistant (hallucination, faute de frappe) crée une tâche définitivement inéligible — et le message de `task_next` accusera à tort une « circularité ».
- **Load-modify-save sans verrou** : chaque outil relit et réécrit tout le fichier sans verrouillage ni écriture atomique. Inoffensif en mono-agent ; dès que plusieurs agents partagent le tableau (le handoff s09+ annoncé par le docstring), deux écritures concurrentes se perdent mutuellement.

## Lancer la démo

```bash
python s07_task_system.py
```

Prérequis : `.env` avec `ANTHROPIC_API_KEY` et `MODEL_ID` (ou proxy LiteLLM, cf. README). Aucun autre fichier — `.agent_tasks.json` naît dans le répertoire courant à la première création de tâche.

Ce qu'on observe : demander par exemple « plan the refactor of core.py in 3 steps, with dependencies » — le modèle enchaîne les `task_create` (la deuxième tâche citant l'ID de la première dans `depends_on`), puis `task_next` lui suggère la seule tâche débloquée. Au fil du travail : `task_update(id, "in_progress")` puis `task_update(id, "done", result=...)`, et `task_next` débloque la suivante. Ouvrir `.agent_tasks.json` pendant la session : le graphe complet est là, lisible, avec statuts et résultats. Quitter, relancer, demander « what's left? » — `task_list` répond depuis le disque : le plan a survécu au redémarrage.

## Liens

- Socle : [[core-py]]
- Session précédente : [[s06-context-compact]]
- Session suivante : [[s08-background-tasks]]
- Sessions liées : [[s03-todo-write]] (la todo-list éphémère et linéaire que s07 rend durable et ordonnée), [[s09-agent-teams]] (le fichier de tâches devient tableau partagé d'une équipe), [[s11-autonomous-agents]] (les agents s'auto-assignent les tâches débloquées du graphe)
