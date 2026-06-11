---
title: "s05 · TodoWrite, l'outil de planification"
session: 05
phase: "Fondamentaux"
fichier: "src/s05.py"
lignes: 91
tags: [todo-write, planification, nag-reminder]
prev: "s04-hooks"
next: "s06-subagent"
---

# s05 · TodoWrite, l'outil de planification

> **En une phrase** : `todo_write` n'exécute rien — sa valeur est son *passage dans le contexte* : chaque appel ré-écrit le plan complet dans la conversation et le ramène dans le champ d'attention du modèle ; la session prescrit la planification dans le `SYSTEM`, câble l'outil, et ré-affiche le plan que [[shared-py]] ne montre plus qu'en compteur.

## Rôle dans le harness

Sur une tâche multi-étapes, le modèle dérive : les résultats d'outils remplissent le contexte et diluent le plan initial — les étapes 4 à 10 sortent de son attention. La parade est contre-intuitive : un outil sans aucune capacité d'exécution. `todo_write` remplace en bloc une liste d'étapes (`pending` / `in_progress` / `completed`) ; comme l'appel et son résultat restent dans `messages`, le plan entier revient périodiquement sous les yeux du modèle.

Deux mécanismes d'accompagnement vivent déjà dans [[shared-py]] : la validation défensive (`_normalize_todos` accepte liste, chaîne JSON ou littéral Python et renvoie des erreurs indexées) et le « nag » — `shared.agent_loop` injecte `<reminder>Update your todos.</reminder>` quand son compteur `rounds_since_todo` atteint 3, et le remet à zéro à chaque appel de `todo_write`. Le délta de session est discipline pure : *prescrire* la planification dans le system prompt (un outil de pure discipline doit être prescrit, pas seulement disponible), inclure `todo_write` dans le pool, et rendre le plan visible pour l'humain.

## Ce que fait ce fichier

### pick() — lignes 37–39

Le helper standard de session : sous-ensemble de `BUILTIN_TOOLS` par noms.

### Câblage module — lignes 32–34 et 42–52

Les imports (lignes 32–34) : `from shared import (...)` nomme les six noms consommés ; `import shared` reste pour les deux noms qui doivent passer par le module — `shared.PROMPT` (rebindé par la session) et `shared.CURRENT_TODOS` (rebindé par shared, voir `afficher_todos`). Puis le câblage :

```python
TOOL_NAMES = ("bash", "read_file", "write_file", "edit_file", "glob",
              "todo_write")
TOOLS = pick(*TOOL_NAMES)
HANDLERS = {name: BUILTIN_HANDLERS[name] for name in TOOL_NAMES}

# La consigne de planification : sans elle, le modèle ignore largement l'outil.
SYSTEM = (f"You are a coding agent at {WORKDIR}. "
          "Before starting any multi-step task, use todo_write to plan "
          "your steps. Update status as you go.")
```

Les 6 outils de l'original — les 5 outils d'exécution plus `todo_write` (dont le schéma, avec son `enum` de statuts, vient du registre). Le `SYSTEM` porte la consigne « plan before execute » ; `ICONES` (ligne 52) mappe les trois statuts vers ` `/`>`/`x` pour le rendu terminal (ASCII portable, pas de glyphes).

### afficher_todos() — lignes 55–63

```python
def afficher_todos():
    # via le module : shared rebinde ce nom à l'exécution (run_todo_write)
    if not shared.CURRENT_TODOS:
        return
    print("\033[33m## Plan courant\033[0m")
    for todo in shared.CURRENT_TODOS:
        print(f"  [{ICONES[todo['status']]}] {todo['content']}")
```

Le rendu du plan pour l'humain, appelé après chaque tour. Il lit `shared.CURRENT_TODOS` — l'attribut de module que `run_todo_write` rebinde (`global CURRENT_TODOS`) à chaque mise à jour — d'où la lecture qualifiée `shared.` à chaque appel : une copie from-importée resterait figée sur la liste de l'import. Le modèle, lui, n'a pas besoin de ce rendu : sa liste figure déjà dans son propre bloc `tool_use`, et `run_todo_write` ne lui renvoie que `"Updated N todos"`.

### main() — lignes 66–86

REPL standard : bannière avec le pool (lignes 68–70), `trigger_hooks("UserPromptSubmit", query)` (ligne 80, fidèle au REPL de l'original), puis le tour :

```python
        agent_loop(query, history,
                   tools=TOOLS, handlers=HANDLERS, system=SYSTEM)
        print_turn_assistants(history, turn_start)
        afficher_todos()
```

`afficher_todos()` (ligne 85) montre l'état du plan après chaque réponse — la trace visible de la discipline. Garde `if __name__` lignes 89–90.

## Ce qui vient de [[shared-py]]

- `CURRENT_TODOS` — l'état du plan, en mémoire seulement (plan léger de session ; la persistance inter-sessions est le rôle du task graph durable). Jamais from-importé : `run_todo_write` rebinde ce nom à l'exécution, la lecture passe par `shared.CURRENT_TODOS`.
- `run_todo_write(todos)` — le handler : normalisation puis remplacement en bloc ; câblé via `BUILTIN_HANDLERS`.
- `_normalize_todos` — la validation défensive (liste / JSON / littéral Python, erreurs indexées), appelée par `run_todo_write`.
- Le « nag » — `rounds_since_todo`, l'injection du `<reminder>` et la remise à zéro sur `todo_write` sont intégrés à `agent_loop` : la session n'a rien à câbler pour en bénéficier.
- `trigger_hooks`, `BUILTIN_TOOLS` / `BUILTIN_HANDLERS`, `agent_loop`, `print_turn_assistants`, `WORKDIR`, `PROMPT` — le câblage standard de session, from-importé explicitement (lignes 33–34) sauf `PROMPT`, rebindé par la session (ligne 67) donc accédé via `shared.PROMPT`.

## Différences avec l'original learn-claude-code

- `CURRENT_TODOS`, `_normalize_todos` et `run_todo_write` sont portés dans shared.py ; le compteur `rounds_since_todo` et l'injection du `<reminder>` sont intégrés à `shared.agent_loop` — le fichier de session ne contient plus aucune mécanique todo.
- **La granularité du compteur a changé** : l'original incrémentait une fois *par tour* contenant des `tool_use` ; `shared.agent_loop` incrémente *par appel d'outil* autre que `todo_write` (et remet à zéro sur chaque `todo_write`). Le rappel arrive donc plus vite quand un tour enchaîne plusieurs outils. Comme dans l'original, le reset teste le nom, pas le succès de la validation.
- Le rendu checklist ANSI (`## Current Tasks`) de l'original vivait *dans* `run_todo_write` ; `shared.run_todo_write` n'affiche qu'un compteur — notre `afficher_todos()` recrée le rendu côté session, après le tour (l'affichage est un choix de session, pas d'outil).
- Les hooks ne sont pas amputés : l'original s05 avait silencieusement réduit `permission_hook` et supprimé `large_output_hook` ; ici le câblage complet de shared reste actif.
- Effet de bibliothèque à connaître : le nag étant dans `agent_loop`, il s'injecte aussi dans les sessions *sans* `todo_write` au pool ([[s02-tool-use]] à [[s04-hooks]]) après 3 appels d'outils — le modèle y reçoit un rappel qu'il ne peut pas honorer. Choix assumé du refactoring : la boucle de synthèse est unique.

## Lancer la démo

```
python src/s05.py
```

Demander une tâche multi-étapes — par exemple « renomme les fichiers .txt en .md puis vérifie le résultat ». On observe : le modèle appelle `todo_write` d'abord (trace `[todo] updated N item(s)` de shared), le bloc `## Plan courant` s'affiche après chaque tour avec les statuts qui avancent (` ` → `>` → `x`), et si le modèle enchaîne 3 appels d'outils sans toucher au plan, le `<reminder>` injecté par `agent_loop` le rappelle à l'ordre. `q` pour quitter.

## Liens

- Bibliothèque : [[shared-py]]
- Session précédente : [[s04-hooks]]
- Session suivante : [[s06-subagent]]
