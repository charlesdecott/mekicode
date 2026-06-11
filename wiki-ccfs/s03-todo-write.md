---
title: "s03 · TodoWrite"
session: 03
phase: "Boucle d'agent"
fichier: "inspiration/claude-code-from-scratch/s03_todo_write.py"
lignes: 241
tags: [todo-write, planification, json, system-prompt, etat-persistant]
prev: "s02-tool-use"
next: "s04-subagent"
---

# s03 · TodoWrite

> **En une phrase** : trois outils (`todo_write`, `todo_read`, `todo_update`) persistent un plan dans un fichier JSON, et un prompt système impose de l'écrire *avant* d'agir — le pipeline « Think-Plan-Act » qui empêche l'agent de dériver sur les tâches longues.

## Rôle dans le harness

Le motto de la session : *« An agent without a plan drifts »*. Sur une tâche multi-étapes, un agent sans plan oublie des étapes, en refait certaines, ou se perd dans une exploration secondaire — l'historique de conversation s'allonge et la consigne initiale se dilue. La parade est de donner à l'agent une **source de vérité externe** : un plan écrit, relu et coché au fur et à mesure. La docstring le formule précisément : persister le plan « creates a "Source of Truth" for its progress, which significantly reduces hallucinations and logic errors in long-running tasks ».

L'enseignement central de la session n'est pourtant pas dans les outils, triviaux (trois fonctions JSON), mais dans la **répartition mécanisme/politique** : le harness fournit le mécanisme (les outils todo), et c'est le prompt système `SYSTEM` qui fournit la politique (« ALWAYS call todo_write first »). Sans ce prompt, les outils resteraient inutilisés ; sans les outils, le prompt serait un vœu pieux. C'est la première session du repo qui personnalise le paramètre `system` de `stream_loop`.

Dans le vrai Claude Code, l'analogue est l'outil **TodoWrite** (colonne « Claude Code Analog » du README) : la liste de tâches qu'on voit s'afficher et se cocher pendant les longues sessions, avec ses statuts `pending`/`in_progress`/`completed`. Le repo jumeau learn-claude-code a sa propre session TodoWrite (s05) ; sa version garde la liste en mémoire et la re-rend à chaque écriture, alors qu'ici le plan vit sur disque (`.agent_todo.json`) — il survit donc au redémarrage du process, prémisse du système de tâches fichier de [[s07-task-system]].

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–19 | Shebang & docstring | Motto « An agent without a plan drifts », les 3 nouveaux outils, le pipeline Think-Plan-Act |
| 21–25 | Imports stdlib | `os`, `json`, `sys`, `typing` |
| 27–32 | Imports core | `EXTENDED_TOOLS`, `EXTENDED_DISPATCH`, `stream_loop` |
| 34–47 | Configuration | `TODO_FILE` et `SYSTEM` — le prompt-politique |
| 49–139 | **Nouveau** | Les trois outils : `run_todo_write`, `run_todo_read`, `run_todo_update` |
| 142–186 | Schémas | `TODO_TOOLS` : `EXTENDED_TOOLS` + 3 définitions |
| 188–195 | Dispatch | `TODO_DISPATCH` : fusion `**EXTENDED_DISPATCH` + 3 handlers |
| 198–236 | REPL | `main()` : structure s02, mais avec `system=SYSTEM` |
| 239–241 | Point d'entrée | Garde `if __name__ == "__main__"` |

## Constantes et configuration

- **`TODO_FILE` (ligne 38)** : `".agent_todo.json"` — fichier caché dans le répertoire courant, pour ne pas encombrer l'espace de travail de l'utilisateur. C'est la seule mémoire de plan ; pas de copie en RAM.
- **`SYSTEM` (lignes 42–47)** : le prompt-politique, pièce maîtresse de la session :

```python
SYSTEM: str = (
    f"You are a coding agent at {os.getcwd()}. "
    "Before working on any multi-step task, ALWAYS call todo_write first "
    "to write your plan. Then execute each step and call todo_update after each one. "
    "This ensures you stay on track and don't skip steps."
)
```

  Trois injonctions : écrire le plan d'abord (`ALWAYS call todo_write first`), mettre à jour après *chaque* étape, et la justification donnée au modèle (« stay on track »). Le comportement de planification de l'agent repose à 100 % sur ces quatre lignes.

- **`TODO_TOOLS` (lignes 146–186)** : `EXTENDED_TOOLS + [...]` — les 6 outils standards plus 3 schémas. À noter : `todo_read` a un schéma vide (`{"type": "object", "properties": {}}`, ligne 165) ; `todo_update` contraint `status` par un **enum** (`["pending", "in_progress", "done"]`, ligne 179) — c'est le schéma qui valide, pas le code Python.
- **`TODO_DISPATCH` (lignes 190–195)** : la fusion par déballage de dict :

```python
TODO_DISPATCH: Dict[str, Any] = {
    **EXTENDED_DISPATCH, # Unpack existing tools (bash, read, write, etc.)
    "todo_write":  lambda inp: run_todo_write(inp["tasks"]),
    "todo_read":   lambda inp: run_todo_read(),
    "todo_update": lambda inp: run_todo_update(inp["index"], inp["status"]),
}
```

  Le pattern d'extension canonique du repo : `**EXTENDED_DISPATCH` recopie la table du socle, puis on ajoute ses entrées. La boucle de [[core-py]] n'est jamais touchée — c'est la promesse de [[s02-tool-use]] tenue.

## Les fonctions, une à une

### `run_todo_write(tasks)` — lignes 51–77

Initialise un plan neuf et l'écrit sur disque. Écrase tout plan existant.

```python
    # Transform raw strings into a list of structured dictionaries with metadata
    data = [
        {"id": i, "task": t, "status": "pending"} 
        for i, t in enumerate(tasks)
    ]
    
    # Context manager ensures the file is closed properly after writing
    with open(TODO_FILE, "w", encoding="utf-8") as f:
        # Write the JSON data with indentation for human readability if opened manually
        json.dump(data, f, indent=2)
    
    # Construct a formatted preview of the plan for the agent's context
    lines = "\n".join(f"  [{i}] {t}" for i, t in enumerate(tasks))
    return f"Plan written ({len(tasks)} tasks):\n{lines}"
```

- **Lignes 65–68** : le modèle envoie de simples chaînes ; le harness les structure en `{"id": i, "task": t, "status": "pending"}`. L'`id` est l'index d'énumération — il coïncide avec la position dans la liste, ce dont `run_todo_update` dépendra.
- **Ligne 71** : mode `"w"` — chaque `todo_write` repart de zéro. Pas d'ajout incrémental : pour amender un plan, le modèle doit le réécrire entier.
- **Lignes 76–77** : le retour rejoue le plan formaté avec ses index `[i]` — c'est ce texte, archivé en `tool_result`, qui apprend au modèle quels index passer à `todo_update`. Le feedback d'outil sert de documentation d'usage.

### `run_todo_read()` — lignes 80–103

Relit le plan pour se resituer. Aucun argument.

```python
        # Format each task with its ID and status (padded to 12 chars for alignment)
        return "\n".join(
            f"[{t['id']}] [{t['status']:12s}] {t['task']}" for t in data
        )
    except FileNotFoundError:
        # Graceful handling if the agent tries to read before writing
        return "(no todo list found - please use todo_write first)"
```

- **Lignes 95–97** : format colonne `[id] [status      ] task` — le padding `:12s` aligne les statuts (`pending`, `in_progress`, `done`) pour une lecture visuelle rapide, par le modèle comme par l'humain.
- **Lignes 98–100** : `FileNotFoundError` ne devient pas une erreur sèche mais un message *prescriptif* — « please use todo_write first » — qui redirige le modèle vers le bon outil. Une erreur d'outil bien rédigée est un mini-prompt.

### `run_todo_update(index, status)` — lignes 106–139

Le cycle read-modify-write complet pour changer le statut d'une tâche.

```python
        # Read the current state to perform an in-memory update
        with open(TODO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Verify the index exists in the list to prevent out-of-bounds errors
        if 0 <= index < len(data):
            # Update the status value for the specific dictionary entry
            data[index]["status"] = status
            
            # Persist the modified list back to disk
            with open(TODO_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            
            return f"Updated task {index} status to: {status}"
        
        # Error if the provided index is invalid
        return f"Error: Task index {index} is out of range."
```

- **Ligne 123** : garde d'intervalle explicite — un index halluciné hors bornes produit un message d'erreur textuel, pas une `IndexError`.
- **Ligne 125** : `data[index]["status"] = status` — accès **positionnel**, pas par champ `id`. Ça fonctionne parce que `run_todo_write` garantit `id == position` ; toute évolution (suppression, réordonnancement) casserait ce contrat implicite.
- **Ligne 125 toujours** : `status` est écrit tel quel, sans validation Python — la contrainte `enum` ne vit que dans le schéma JSON, côté modèle.
- **Lignes 136–139** : `FileNotFoundError` (update avant write) et exceptions génériques sont rendues comme texte, fidèle à la philosophie « une erreur d'outil est une donnée ».

### `main()` — lignes 200–236

REPL structurellement identique à [[s02-tool-use]] — header (ligne 205), `history` local, capture d'entrée, mots de sortie. La nouveauté tient au quatrième argument :

```python
        # Execute the agent loop. 
        # Crucially, we pass the custom SYSTEM prompt here to enforce planning behavior.
        stream_loop(
            messages=history,
            tools=TODO_TOOLS,
            dispatch=TODO_DISPATCH,
            system=SYSTEM
        )
```

- **Ligne 232** : `system=SYSTEM` — première utilisation du paramètre optionnel de `stream_loop` (qui retombait sur `DEFAULT_SYSTEM` jusqu'ici). Le trio `tools`/`dispatch`/`system` forme désormais la signature complète d'une « personnalité » d'agent : capacités + routage + politique.

### Point d'entrée — lignes 239–241

Garde standard `if __name__ == "__main__": main()`.

## Ce qui vient de [[core-py]]

| Import | Définition dans core.py | Rôle ici |
|---|---|---|
| `EXTENDED_TOOLS` | lignes 369–426 | Les 6 schémas de base (bash, read, write, grep, glob, revert), socle de `TODO_TOOLS` |
| `EXTENDED_DISPATCH` | lignes 436–443 | La table de routage de base, déballée dans `TODO_DISPATCH` |
| `stream_loop` | lignes 573–626 | La boucle streaming complète ; son paramètre `system` est exploité pour la première fois |

## Pièges et détails d'implémentation

- **Le plan survit au process — et entre les démos** : `.agent_todo.json` reste dans le répertoire courant après la sortie. Au prochain lancement, `todo_read` relira l'ancien plan tel quel ; seul un `todo_write` l'écrase. Persistance voulue, mais sans notion de session.
- **L'enum `status` n'est validé que par le schéma** : `run_todo_update` écrirait n'importe quelle chaîne reçue. La défense repose sur la conformité du modèle au JSON Schema — suffisant en pratique, pas une garantie.
- **`id` n'est pas une clé, c'est une position** : `run_todo_update` indexe `data[index]` directement. Le contrat tient parce que `todo_write` réécrit toujours tout depuis zéro avec `id == index`.
- **Read-modify-write non atomique** : entre la lecture et la réécriture du JSON, rien ne verrouille le fichier. Sans conséquence en mono-agent synchrone, mais c'est précisément la faille que [[s07-task-system]] (verrouillage de tâches par fichier) puis les mailboxes de [[s09-agent-teams]] devront traiter en multi-agents.
- **Le mécanisme sans la politique ne fait rien** : retirez `system=SYSTEM` et le modèle dispose des outils todo mais ne s'en sert quasiment jamais. Le couple outil + prompt est indivisible — c'est la vraie leçon de la session.
- **`todo_read` ignore son input** : `lambda inp: run_todo_read()` — le paramètre `inp` est jeté. Cohérent avec son schéma vide, mais le pattern montre que la lambda d'adaptation peut aussi *filtrer*.

## Lancer la démo

```bash
cd inspiration/claude-code-from-scratch
python s03_todo_write.py
```

Prérequis : `pip install -r requirements.txt` et un `.env` avec `ANTHROPIC_API_KEY` + `MODEL_ID` (ou proxy LiteLLM via `ANTHROPIC_BASE_URL`).

Donnez une tâche multi-étapes — par exemple « crée un module calculatrice avec ses tests, lance-les, puis écris un README ». On observe : `[todo_write]` appelé en premier avec le plan complet, puis l'alternance exécution / `[todo_update] 0 → in_progress` / `[todo_update] 0 → done`… Le fichier `.agent_todo.json` apparaît dans le répertoire courant ; ouvrez-le pendant la run pour voir les statuts changer en direct.

## Liens

- Socle : [[core-py]]
- Session précédente : [[s02-tool-use]]
- Session suivante : [[s04-subagent]]
- Sessions liées : [[s07-task-system]] (le plan devient graphe de dépendances persistant), [[s11-autonomous-agents]] (le tableau de tâches partagé où les agents s'auto-assignent)
