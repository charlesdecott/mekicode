---
title: "s12 · Système de tâches"
session: 12
phase: "Tâches & temps"
fichier: "src/sessions/s12.py"
lignes: 83
tags: [taches, dag, persistance, dependances, claim]
prev: "s11-error-recovery"
next: "s13-background-tasks"
---

# s12 · Système de tâches

> **En une phrase** : un graphe de tâches durable (un fichier JSON par tâche sous `.tasks/`), avec dépendances `blockedBy`, revendication `claim` et déblocage en cascade — câblé ici en 5 outils dans `agent_loop`, plus une démo hors-ligne du graphe.

## Rôle dans le harness

Le `todo_write` de [[s05-todo-write]] est une checklist en mémoire de session ; il ne survit ni au redémarrage ni au partage. Le système de tâches résout trois problèmes que la checklist ignore : la **persistance** (`.tasks/{id}.json` survit au processus), l'**ordre** (les dépendances `blockedBy` forment un graphe orienté — on ne construit pas le toit avant les fondations), et la **coordination** (le champ `owner` et l'action `claim` empêchent deux agents de prendre la même tâche — la fondation du multi-agents de [[s15-agent-teams]]).

Tout le moteur (dataclass `Task`, CRUD disque, `can_start`, `claim_task`, `complete_task`, wrappers outils) vit dans [[shared-py]] ; ce fichier ne fait que choisir les 8 outils, figer un prompt système qui explique le workflow au modèle, et fournir une démo hors-ligne qui rend le cycle de vie observable sans LLM.

## Ce que fait ce fichier

### pick() — lignes 22–23

Filtre `BUILTIN_TOOLS` par nom — le helper standard des sessions.

### Câblage module — lignes 26–35

`TOOL_NAMES` (lignes 26–28) : les 3 outils fichiers + les 5 outils tâches (`create_task`, `list_tasks`, `get_task`, `claim_task`, `complete_task`). `SYSTEM` (lignes 31–35) décrit le workflow au modèle :

```python
SYSTEM = ("You are a project agent with a durable task system. "
          "Tasks persist as JSON under .tasks/ and survive restarts. "
          "Workflow: create_task (blockedBy = dependency ids), claim_task, "
          "complete_task. A task is claimable only when every blockedBy "
          f"task is completed. Workspace: {WORKDIR}.")
```

### demo_graph() — lignes 38–53

La démo hors-ligne du graphe de dépendances, entièrement déterministe :

```python
    a = create_task("Schéma de base de données",
                    "Créer les tables users et sessions")
    b = create_task("API REST", "Endpoints CRUD sur le schéma",
                    blockedBy=[a.id])
```

Puis la séquence commentée : `claim_task(b.id)` est **refusé** (`Cannot start — blocked by: [...]`, la garde `can_start`), `claim_task(a.id)` passe (`pending → in_progress`), `complete_task(a.id)` rapporte `Unblocked: API REST` (le scan de déblocage en cascade), `claim_task(b.id)` passe désormais, et le re-claim final de `a` est refusé (`Task ... is completed, cannot claim`). Les trois gardes de `claim_task` (statut `pending`, pas d'`owner`, `can_start`) et le rapport de déblocage de `complete_task` sont ainsi tous visibles en une commande.

### main() — lignes 56–78

Boucle interactive : `demo` lance le graphe hors-ligne, `ls` affiche `run_list_tasks()` (l'état du disque — relancer le programme après un `demo` montre la persistance), tout autre texte part dans `agent_loop` avec le pool figé (`tools=TOOLS, handlers=HANDLERS, system=SYSTEM`). `q` quitte.

## Ce qui vient de [[shared-py]]

Tout est importé explicitement (`from shared import (...)`, lignes 15–19) :

- `create_task` / `claim_task` / `complete_task` — le moteur : ils manipulent la dataclass `Task` à 7 champs (dont `worktree`, héritage s18 — non importée ici, on ne reçoit que ses instances), triple garde de revendication, complétion avec liste des tâches débloquées.
- `run_create_task`, `run_list_tasks`, `run_get_task`, `run_claim_task`, `run_complete_task` — les wrappers outils (tous protègent le `FileNotFoundError` d'un ID halluciné, contrairement à l'original).
- `agent_loop(user_input, messages, tools=, handlers=, system=)` — la boucle complète (compaction, hooks, récupération d'erreurs) avec pool figé.
- `BUILTIN_TOOLS` / `BUILTIN_HANDLERS`, `WORKDIR`, `PROMPT`, `print_turn_assistants`.

## Différences avec l'original learn-claude-code

- L'original (377 lignes) recopiait le système de tâches entier plus outils fichiers, prompt s10 et sa propre boucle ; ici 82 lignes de câblage et de démo.
- L'original plantait sur un ID halluciné (`load_task` → `FileNotFoundError` non attrapée dans `run_claim_task`/`run_complete_task`) ; les wrappers de shared.py attrapent tous l'erreur et la retournent au modèle en texte.
- Le `claim_task` de shared.py a une garde de plus : une tâche déjà possédée (`owner` non vide) est refusée explicitement, et le message d'échec distingue dépendances bloquantes et dépendances **manquantes**.
- La boucle utilisée n'est plus « volontairement basique » : `agent_loop` de shared.py embarque la récupération d'erreurs de [[s11-error-recovery]] — les couches se composent au lieu de s'exclure.
- La démo `demo_graph` n'existait pas : l'original ne montrait le cycle de vie qu'à travers des prompts LLM.

## Lancer la démo

```
python src/sessions/s12.py
```

`demo` et `ls` fonctionnent sans clé API. `demo` déroule le cycle complet create → claim refusé → claim/complete amont → déblocage → claim/complete aval ; `ls` relu après redémarrage prouve la persistance. Avec une clé, demander par exemple « crée 3 tâches : schéma, API (dépend du schéma), tests (dépendent de l'API), puis traite-les dans l'ordre ».

## Liens

- Bibliothèque : [[shared-py]]
- Session précédente : [[s11-error-recovery]]
- Session suivante : [[s13-background-tasks]]
- Sessions liées : [[s05-todo-write]] (la checklist volatile que ce système dépasse), [[s15-agent-teams]] (où `owner`/`claim` prennent tout leur sens), [[s17-autonomous-agents]] (revendication autonome des tâches libres)
