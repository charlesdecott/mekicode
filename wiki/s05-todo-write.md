---
title: "s05 · TodoWrite, l'outil de planification"
session: 05
phase: "Fondamentaux"
fichier: "inspiration/learn-claude-code/s05_todo_write/code.py"
lignes: 305
tags: [todo-write, planification, nag-reminder, system-prompt]
prev: "s04-hooks"
next: "s06-subagent"
---

# s05 · TodoWrite, l'outil de planification

> **En une phrase** : un sixième outil, `todo_write`, qui n'exécute rien — il sert uniquement au modèle à poser et tenir son plan — complété par un « nag reminder » injecté quand le modèle oublie sa liste pendant 3 tours.

## Rôle dans le harness

Donnez à l'agent une tâche complexe : « renomme tous les fichiers Python en snake_case, lance les tests, corrige les échecs ». Il renomme trois fichiers, lance un test, trouve deux échecs, se met à corriger… et en corrigeant, il oublie l'objectif initial. Le README décrit le mécanisme de la dérive : *« The longer the conversation, the worse it gets: tool results keep filling the context, diluting the system prompt's influence. »* Plus le contexte se remplit de résultats d'outils, plus les étapes 4 à 10 du plan initial sont chassées de l'attention du modèle.

La parade tient en une idée contre-intuitive : un outil qui ne *fait* rien. `todo_write` ne lit pas de fichier, ne lance pas de commande — il enregistre une liste d'étapes avec leurs statuts (`pending` / `in_progress` / `completed`) et l'affiche. L'intérêt est le suivant : chaque appel à `todo_write` ré-écrit le plan **dans la conversation elle-même** (l'appel d'outil et son résultat restent dans `messages`), donc le plan revient périodiquement dans le champ d'attention du modèle au lieu d'être dilué. Le README résume : *« todo_write doesn't give the Agent any additional execution capability. What it adds is planning capability. »*

Deux mécanismes d'accompagnement : le prompt système ordonne explicitement de planifier avant d'exécuter, et un compteur dans la boucle injecte un rappel `<reminder>Update your todos.</reminder>` si le modèle passe 3 tours sans toucher à sa liste — le « nag ». Le README précise que ce seuil de 3 tours est purement pédagogique : le vrai Claude Code n'a pas de logique à compteur fixe ; le plus proche est un nudge de vérification quand 3+ todos sont tous `completed` sans item de vérification (`TodoWriteTool.ts:72-107`). CC fait aussi coexister deux systèmes : TodoWrite (V1, liste en mémoire, comme ici) et le Task System (V2, persistance fichier, graphe de dépendances, verrous — c'est [[s12-task-system]]).

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–29 | Docstring | Schéma du dispatch avec `todo_write`, inventaire des ajouts |
| 31–45 | Imports & env | + `ast`, `json` (pour `_normalize_todos`) ; bloc readline réduit à une ligne |
| 47–57 | Configuration | `WORKDIR`, client, `MODEL`, **`CURRENT_TODOS`**, `SYSTEM` enrichi |
| 64–117 | Repris de s02–s04 | `safe_path` + les 5 outils, inchangés |
| 124–155 | **Nouveau** | `_normalize_todos()` + `run_todo_write()` |
| 157–176 | Modifié | `TOOLS` (6 entrées) et `TOOL_HANDLERS` (+ `todo_write`) |
| 183–228 | Repris de s04 | Système de hooks (callbacks simplifiés, voir plus bas) |
| 235 | **Nouveau** | Compteur global `rounds_since_todo` |
| 237–283 | Boucle | `agent_loop()` : s04 + injection du nag + remise à zéro du compteur |
| 286–304 | Point d'entrée | REPL identique à s04 |

## Constantes et configuration

- **`CURRENT_TODOS` (ligne 50)** : `list[dict]` globale, l'état du plan. En mémoire processus uniquement — fermée la session, perdu le plan (le Task System de [[s12-task-system]] persistera sur disque).
- **`SYSTEM` (lignes 53–57)** : le prompt système gagne la consigne de planification :

```python
SYSTEM = (
    f"You are a coding agent at {WORKDIR}. "
    "Before starting any multi-step task, use todo_write to plan your steps. "
    "Update status as you go."
)
```

Sans cette phrase, le modèle ignorerait largement l'outil : un outil de pure discipline doit être *prescrit*, pas seulement disponible.

- **`TOOLS` (lignes 157–171)** : sixième entrée, la plus structurée du fichier — un tableau d'objets contraints :

```python
    {"name": "todo_write", "description": "Create and manage a task list for your current coding session.",
     "input_schema": {"type": "object", "properties": {"todos": {"type": "array", "items": {"type": "object",
         "properties": {"content": {"type": "string"},
                        "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}},
         "required": ["content", "status"]}}}, "required": ["todos"]}},
```

L'`enum` sur `status` verrouille le vocabulaire des états côté modèle. (La version CC a un champ de plus, `activeForm`, pour l'affichage du spinner — inutile ici.)

- **`TOOL_HANDLERS` (lignes 173–176)** : + `"todo_write": run_todo_write`. C'est la démonstration en acte de la promesse de [[s02-tool-use]] : un outil de plus = une entrée de plus, `agent_loop` n'a pas bougé d'une ligne pour le dispatch.
- **`rounds_since_todo` (ligne 235)** : compteur global de tours sans appel à `todo_write`.
- **`DENY_LIST` (ligne 196)** : reprise de s04 (six motifs).

## Les fonctions, une à une

### `safe_path` (64–67), `run_bash` (70–77), `run_read` (79–86), `run_write` (88–95), `run_edit` (97–106), `run_glob` (108–117)
Repris de [[s04-hooks]] sans modification.

### `_normalize_todos(todos)` — lignes 124–142

Le validateur défensif de l'entrée du modèle — la fonction la plus « production » du fichier :

```python
def _normalize_todos(todos):
    if isinstance(todos, str):
        try:
            todos = json.loads(todos)
        except json.JSONDecodeError:
            try:
                todos = ast.literal_eval(todos)
            except (SyntaxError, ValueError):
                return None, "Error: todos must be a list or JSON array string"
    if not isinstance(todos, list):
        return None, "Error: todos must be a list"
    for i, t in enumerate(todos):
        if not isinstance(t, dict):
            return None, f"Error: todos[{i}] must be an object"
        if "content" not in t or "status" not in t:
            return None, f"Error: todos[{i}] missing 'content' or 'status'"
        if t["status"] not in ("pending", "in_progress", "completed"):
            return None, f"Error: todos[{i}] has invalid status '{t['status']}'"
    return todos, None
```

- **Lignes 125–132** : le cas réel qui motive tout : il arrive que le modèle envoie `todos` comme **chaîne** (`'[{"content": ...}]'`) au lieu d'un tableau JSON natif. Premier essai : `json.loads`. S'il échoue (par exemple quotes simples à la Python), second essai : `ast.literal_eval`, qui parse les littéraux Python en toute sécurité (contrairement à `eval`, il n'exécute rien). Double filet pour récupérer un input « presque bon » plutôt que de le rejeter.
- **Lignes 133–141** : validation structurelle élément par élément, avec des messages d'erreur **indexés** (`todos[2] has invalid status 'done'`) — le modèle sait exactement quoi corriger au tour suivant. C'est le pendant manuel de la validation Zod du vrai CC.
- **Ligne 142** : retour en tuple `(valeur, erreur)` à la Go — un des deux est toujours `None`. Le préfixe `_` signale un helper interne, non exposé comme outil.

### `run_todo_write(todos)` — lignes 144–155

```python
def run_todo_write(todos: list) -> str:
    global CURRENT_TODOS
    todos, error = _normalize_todos(todos)
    if error:
        return error
    CURRENT_TODOS = todos
    lines = ["\n\033[33m## Current Tasks\033[0m"]
    for t in CURRENT_TODOS:
        icon = {"pending": " ", "in_progress": "\033[36m▸\033[0m", "completed": "\033[32m✓\033[0m"}[t["status"]]
        lines.append(f"  [{icon}] {t['content']}")
    print("\n".join(lines))
    return f"Updated {len(CURRENT_TODOS)} tasks"
```

- **Ligne 149** : `CURRENT_TODOS = todos` — **remplacement intégral**, pas de fusion : chaque appel envoie un instantané complet de la liste. Le modèle doit donc re-soumettre *toutes* les tâches avec leurs statuts à jour, ce qui est exactement l'effet recherché : ré-énoncer le plan entier à chaque mise à jour le ramène dans le contexte.
- **Lignes 150–154** : rendu terminal — case vide pour `pending`, `▸` cyan pour `in_progress`, `✓` verte pour `completed`. Affichage pour l'humain uniquement.
- **Ligne 155** : le modèle, lui, ne reçoit que `"Updated N tasks"` — il n'a pas besoin de relire sa propre liste, elle figure déjà dans son appel `tool_use`.

### Système de hooks — lignes 183–228

`HOOKS` (183), `register_hook` (185–186), `trigger_hooks` (188–193) : repris de [[s04-hooks]] sans modification. Les callbacks, en revanche, sont **simplifiés en silence** malgré le commentaire `# s04 hooks preserved` :

- `permission_hook` (198–205) : ne garde que la deny list dure ; la confirmation interactive des commandes destructrices et le contrôle d'écriture hors workspace de s04 ont disparu.
- `log_hook` (207–210) : n'affiche plus que le nom de l'outil (plus d'aperçu des arguments).
- `context_inject_hook` (212–215) et `summary_hook` (217–223) : inchangés.
- `large_output_hook` : **supprimé** — quatre enregistrements (225–228) au lieu de cinq, plus aucun hook `PostToolUse` (l'appel `trigger_hooks("PostToolUse", ...)` ligne 274 tourne à vide).

### `agent_loop(messages)` — lignes 237–283

La boucle de s04, plus le mécanisme de nag. Trois insertions :

```python
rounds_since_todo = 0

def agent_loop(messages: list):
    global rounds_since_todo
    while True:
        # s05: nag reminder — inject if model hasn't updated todos for 3 rounds
        if rounds_since_todo >= 3 and messages:
            messages.append({"role": "user",
                             "content": "<reminder>Update your todos.</reminder>"})
            rounds_since_todo = 0
```

- **Lignes 241–244** : *avant* chaque appel LLM, si le compteur atteint 3, un message utilisateur synthétique `<reminder>...</reminder>` est injecté, puis le compteur repart à zéro (sinon le rappel serait répété à chaque tour suivant). Les balises pseudo-XML signalent au modèle un message machine, distinct d'une vraie parole utilisateur — la même convention que les `<system-reminder>` du vrai Claude Code. À noter : ce message s'ajoute souvent juste après le message de `tool_result` (deux messages `user` consécutifs, fusionnés par l'API).

```python
        rounds_since_todo += 1
```

- **Ligne 259** : le compteur s'incrémente une fois **par tour d'outils** (par réponse du modèle contenant des `tool_use`), pas par appel d'outil individuel. Un tour avec 4 lectures de fichiers compte pour 1. Placé après le test `stop_reason`, un tour purement textuel n'incrémente pas.

```python
            # s05: reset nag counter when todo_write is called
            if block.name == "todo_write":
                rounds_since_todo = 0
```

- **Lignes 277–278** : tout appel à `todo_write` dans le tour remet le compteur à zéro. La remise à zéro se fait *après* l'incrément de la ligne 259, donc l'ordre net d'un tour avec `todo_write` est : +1 puis 0 — correct. Notez que le reset a lieu même si la mise à jour a échoué à la validation (`_normalize_todos` renvoie une erreur) : l'intention de mise à jour suffit à calmer le nag.

Le reste — appel API, archivage, hook `Stop` avec continuation forcée, `PreToolUse`/`PostToolUse`, collecte des `tool_result` — est identique à [[s04-hooks]].

### Point d'entrée `if __name__ == "__main__"` — lignes 286–304
Repris de [[s04-hooks]] sans modification (bannière mise à part). Détail : `rounds_since_todo` étant global, il survit d'une question utilisateur à l'autre dans la même session.

## Ce qui change par rapport à [[s04-hooks]]

- **+ `CURRENT_TODOS`** (ligne 50) : l'état du plan, en mémoire.
- **+ `_normalize_todos()`** (124–142) et **+ `run_todo_write()`** (144–155).
- **`TOOLS`** : 5 → 6 entrées (la définition `todo_write` avec `enum` de statuts, lignes 169–170) ; **`TOOL_HANDLERS`** : +1 mapping.
- **`SYSTEM`** : ajout de la consigne « plan before execute » (lignes 53–57).
- **`agent_loop`** : + compteur `rounds_since_todo` (235), + injection du `<reminder>` (241–244), + incrément par tour (259), + remise à zéro sur `todo_write` (277–278).
- **Hooks allégés (non documenté dans la docstring)** : `permission_hook` réduit à la deny list, `log_hook` réduit au nom d'outil, `large_output_hook` supprimé — la session resserre le focus sur la planification.
- **Imports** : + `ast`, + `json`.

## Pièges et détails d'implémentation

- **Un outil sans capacité d'exécution est quand même un outil** : la valeur de `todo_write` n'est pas son effet (aucun) mais son *passage dans le contexte* — chaque appel ré-imprime le plan dans la fenêtre d'attention du modèle.
- **Remplacement intégral, pas delta** : le modèle doit renvoyer la liste complète à chaque mise à jour. Oublier une tâche dans l'instantané la supprime du plan — c'est aussi le comportement du TodoWrite de CC.
- **Le nag s'injecte comme message `user`** : il suit le format conversationnel normal ; le modèle ne distingue le rappel machine que par la convention `<reminder>`. Deux messages `user` consécutifs peuvent en résulter (tool_results puis reminder) — l'API les accepte.
- **Compteur par tour, pas par outil** — et global : il n'est pas remis à zéro entre deux questions de l'utilisateur ; une nouvelle question peut hériter d'un compteur déjà à 2.
- **Le reset ignore le succès** : `todo_write` appelé avec un input invalide (erreur de `_normalize_todos`) remet quand même le compteur à zéro (lignes 277–278 testent le nom, pas le résultat).
- **Régression silencieuse des hooks** : le commentaire `# s04 hooks preserved` (ligne 195) est inexact — les confirmations interactives et `large_output_hook` ont été retirés. Dans une série « cumulative », c'est le principal écart entre la promesse et le code.

## Liens

- Session précédente : [[s04-hooks]]
- Session suivante : [[s06-subagent]]
- Sessions liées : [[s02-tool-use]] (le dispatch qui rend l'ajout indolore), [[s10-system-prompt]] (prescrire un comportement par le prompt système), [[s12-task-system]] (la V2 : persistance fichier, dépendances `blockedBy`, verrous), [[s08-context-compact]] (l'autre réponse à la dilution du contexte)
