---
title: "s04 · Les hooks"
session: 04
phase: "Fondamentaux"
fichier: "src/sessions/s04.py"
lignes: 112
tags: [hooks, pre-tool-use, post-tool-use, stop]
prev: "s03-permission"
next: "s05-todo-write"
---

# s04 · Les hooks

> **En une phrase** : la boucle n'appelle plus que `trigger_hooks()` à quatre moments du cycle (`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`) — la session affiche le registre câblé par [[shared-py]], y empile deux hooks custom (compteur + bilan) et déclenche elle-même l'événement qui appartient au REPL.

## Rôle dans le harness

Chaque nouveau besoin transversal (journaliser, contrôler, notifier) ne doit pas rouvrir la boucle : la boucle est un noyau stable, les extensions s'accrochent à l'extérieur. C'est le patron observateur appliqué au cycle d'agent — un registre `HOOKS` (événement → liste de callbacks), `register_hook()` pour s'abonner, `trigger_hooks()` déclenché aux moments clés. Convention de retour : `None` = laisser passer ; le premier retour non-`None` court-circuite la chaîne (pour `PreToolUse`, la chaîne retournée devient le `tool_result` de blocage).

Dans notre harness, le mécanisme *et* les hooks de base vivent dans [[shared-py]] : `permission_hook`, `log_hook`, `large_output_hook`, `user_prompt_hook` et `stop_hook` y sont enregistrés à l'import, et `shared.agent_loop` déclenche `PreToolUse`/`PostToolUse`/`Stop` aux bons endroits. Le délta de session tient en trois gestes : rendre le câblage visible (`afficher_registre`), s'abonner depuis l'extérieur (deux hooks custom à état partagé), et déclencher `UserPromptSubmit` dans le REPL — le seul des quatre événements qui appartient au CLI, pas à la boucle.

## Ce que fait ce fichier

### pick() — lignes 35–37

Le helper standard de session : sous-ensemble de `BUILTIN_TOOLS` par noms.

### Câblage module — lignes 29–32, 40–48 et 75–76

Les imports (lignes 29–32) : `from shared import (...)` nomme les huit noms consommés ; `import shared` reste pour `shared.PROMPT`, rebindé par la session dans `main()`. Puis `TOOL_NAMES = ("bash", "read_file", "write_file", "glob")` (ligne 40), tables `TOOLS`/`HANDLERS` (41–42), `SYSTEM` standard (44–45), et l'état partagé des hooks custom :

```python
USAGE_PAR_OUTIL: dict[str, int] = {}
```

Les abonnements (lignes 75–76) sont le geste central de la session :

```python
register_hook("PostToolUse", compteur_hook)
register_hook("Stop", bilan_hook)
```

Ils s'ajoutent *derrière* les hooks de shared dans les listes du registre — l'ordre d'enregistrement est l'ordre d'exécution.

### compteur_hook() — lignes 51–59

```python
def compteur_hook(block, output):
    USAGE_PAR_OUTIL[block.name] = USAGE_PAR_OUTIL.get(block.name, 0) + 1
    return None
```

Hook `PostToolUse` d'observation pure : il incrémente le tally par nom d'outil et retourne toujours `None` (ne court-circuite jamais). Sa docstring souligne un effet de l'architecture : il ne voit que les outils *réellement exécutés* — un appel bloqué par `permission_hook` en `PreToolUse` ne passe jamais par `PostToolUse`.

### bilan_hook() — lignes 62–72

Hook `Stop` : si le tally n'est pas vide, il l'affiche en une ligne (`bash x3, read_file x1`). Il retourne `None` = autoriser l'arrêt ; le contrat du hook `Stop` veut qu'une valeur non-`None` force la continuation — mais voir « Différences » : `shared.agent_loop` ignore ce retour.

### afficher_registre() — lignes 79–84

Introspection du câblage au lancement : pour chacun des quatre événements, la liste des callbacks par `__name__`. On y lit d'un coup d'œil la politique complète — les cinq hooks de shared plus les deux de la session :

```
    UserPromptSubmit: user_prompt_hook
    PreToolUse: permission_hook, log_hook
    PostToolUse: large_output_hook, compteur_hook
    Stop: stop_hook, bilan_hook
```

### main() — lignes 87–107

REPL standard avec une ligne en plus, le quatrième point d'accroche (ligne 102) :

```python
        trigger_hooks("UserPromptSubmit", query)
```

déclenché entre la saisie et l'entrée du message dans l'historique — `shared.agent_loop` ne déclenche pas cet événement, c'est au CLI de le faire (comme dans le REPL de l'original). Suivent `agent_loop` en pool figé et `print_turn_assistants` (lignes 103–106). Garde `if __name__` lignes 110–111.

## Ce qui vient de [[shared-py]]

- `HOOKS` — le registre à 4 événements, lu par `afficher_registre()`.
- `register_hook` / `trigger_hooks` — l'abonnement (lignes 75–76) et le déclenchement manuel (ligne 102) ; `agent_loop` appelle `trigger_hooks` pour les trois autres événements.
- `log_hook`, `large_output_hook` — les démonstrateurs d'observation, déjà enregistrés à l'import (trace de chaque outil ; alerte au-delà de 100 000 caractères).
- `permission_hook`, `user_prompt_hook`, `stop_hook` — le reste du câblage par défaut, visible dans le registre.
- `BUILTIN_TOOLS` / `BUILTIN_HANDLERS`, `agent_loop`, `print_turn_assistants`, `WORKDIR`, `PROMPT` — le câblage standard de session. Tout est from-importé explicitement (lignes 30–32), sauf `PROMPT`, rebindé par la session (ligne 88) donc accédé via `shared.PROMPT`.

## Différences avec l'original learn-claude-code

- Le mécanisme (`HOOKS`, `register_hook`, `trigger_hooks`) et les cinq callbacks de l'original sont portés tels quels dans shared.py — avec deux renommages : `context_inject_hook` → `user_prompt_hook`, `summary_hook` → `stop_hook`. Le fichier de session ne définit plus que ses hooks à lui.
- Les hooks custom `compteur_hook`/`bilan_hook` n'existent pas dans l'original : ils remplacent la démonstration « plusieurs hooks par événement » et prouvent qu'une session s'abonne sans toucher à la bibliothèque (y compris avec un état partagé entre deux événements).
- **La continuation forcée du hook `Stop` a disparu** : l'original faisait `force = trigger_hooks("Stop", messages)` et réinjectait la valeur comme message user ; `shared.agent_loop` appelle `trigger_hooks("Stop", ...)` mais ignore le retour. Un hook `Stop` de notre harness observe, il ne peut pas relancer la boucle.
- `afficher_registre()` est nouvelle — l'introspection du câblage n'existait pas dans l'original.
- La confirmation interactive des destructifs et le contrôle d'écriture hors workspace, présents dans le `permission_hook` de l'original s04, sont intacts dans celui de shared (l'original s05 les avait silencieusement perdus).

## Lancer la démo

```
python src/sessions/s04.py
```

Au lancement, le registre complet s'affiche (5 hooks de shared + 2 de la session). À chaque question : la trace `[HOOK] UserPromptSubmit` (déclenchée par le REPL), puis `[HOOK] <outil>` avant chaque exécution (`log_hook`), et en fin de tour les lignes `[HOOK] Stop: N tool result(s)` (shared) puis `[HOOK] bilan outils : bash x2, ...` (notre hook). Demander une tâche bloquée (« lance sudo ls ») montre le court-circuit : refusé par `permission_hook`, l'appel n'est ni loggé ni compté. `q` pour quitter.

## Liens

- Bibliothèque : [[shared-py]]
- Session précédente : [[s03-permission]]
- Session suivante : [[s05-todo-write]]
