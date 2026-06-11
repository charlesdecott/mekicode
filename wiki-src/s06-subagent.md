---
title: "s06 · Subagent"
session: 06
phase: "Fondamentaux"
fichier: "src/sessions/s06.py"
lignes: 67
tags: [subagent, task-tool, isolation-de-contexte, delegation]
prev: "s05-todo-write"
next: "s07-skill-loading"
---

# s06 · Subagent

> **En une phrase** : l'outil `task` délègue un sous-problème à `shared.spawn_subagent()` — une boucle agent isolée à `messages[]` vierge dont seul le résumé final remonte au parent.

## Rôle dans le harness

Un agent qui trace une chaîne d'appels lit 30 fichiers et accumule des dizaines d'entrées intermédiaires dans son historique — du contexte brûlé pour rien une fois la conclusion trouvée. La parade : déléguer le sous-problème à un sous-agent qui démarre avec une conversation **fraîche** (`[{"role": "user", "content": description}]`), travaille en autonomie (30 tours max), puis ne renvoie **que son dernier texte assistant**. L'historique du sous-agent est jeté ; seuls les effets de bord disque (fichiers écrits, commandes lancées) persistent.

Deux gardes structurent le mécanisme dans [[shared-py]] : l'anti-récursion (`SUB_TOOLS` ne contient que 5 outils, sans `task` — un sous-agent ne peut pas en engendrer un autre) et le fait que **l'isolation de contexte n'est pas une isolation de permissions** : chaque outil du sous-agent passe par les mêmes hooks `PreToolUse`/`PostToolUse` que le parent. Ce fichier ne contient que le délta de session : le câblage d'un pool parent figé (5 outils de base + `task`) sur `agent_loop` paramétrée, et un raccourci de démo pour observer le sous-agent seul.

## Ce que fait ce fichier

### pick() — lignes 22–24

```python
def pick(*names):
    """Sous-ensemble de BUILTIN_TOOLS par nom (schémas JSON complets)."""
    return [t for t in BUILTIN_TOOLS if t["name"] in names]
```

Le helper commun des sessions : il extrait de `BUILTIN_TOOLS` les schémas des seuls outils voulus. Le miroir `HANDLERS` (ligne 29) fait pareil côté dispatch.

### Câblage module — lignes 27–37

- `TOOL_NAMES` / `TOOLS` / `HANDLERS` (27–29) : les 5 outils de base + `task`. Dans `BUILTIN_HANDLERS`, `task` pointe déjà sur `spawn_subagent` — aucun enregistrement à faire ici.
- `SYSTEM` (33–37) : un system **figé** (le pool est figé, pas besoin du system vivant de s20) qui annonce la délégation, comme le `SYSTEM` de l'original :

```python
SYSTEM = (
    f"You are a coding agent at {WORKDIR}. "
    "For complex sub-problems, use the task tool to spawn a subagent "
    "with a fresh context. Keep your final answers concise."
)
```

### main() — lignes 40–62

La boucle interactive (`q` pour quitter). Deux chemins :

- `:sub <description>` (lignes 53–58) — appel **direct** de `spawn_subagent`, sans passer par le modèle parent. On voit le sous-agent dérouler ses outils (préfixés par les hooks de shared) puis seul le résumé revenir ; `history` n'est pas touché :

```python
        if user.startswith(":sub "):
            # Démo directe : un sous-agent one-shot, sans le parent. On ne
            # récupère que le résumé — l'historique du sous-agent est jeté.
            summary = spawn_subagent(user[len(":sub "):].strip())
            print(f"\n\033[35m[résumé du sous-agent]\033[0m\n{summary}\n")
            continue
```

- Texte libre (lignes 59–62) — un tour d'`agent_loop` **paramétrée** : `tools=TOOLS, handlers=HANDLERS, system=SYSTEM` fige le pool ; quand le modèle appelle `task`, le dispatch générique exécute `spawn_subagent` comme n'importe quel handler — la boucle ne sait pas qu'elle vient de déclencher 30 appels API potentiels :

```python
        agent_loop(user, history,
                   tools=TOOLS, handlers=HANDLERS, system=SYSTEM)
        print_turn_assistants(history, turn_start)
```

## Ce qui vient de [[shared-py]]

Tout est importé explicitement (`from shared import (...)`) — le fichier ne rebinde aucune globale de shared.

- `spawn_subagent(description)` — la boucle isolée : messages frais, `SUB_SYSTEM` anti-délégation, 30 tours max, hooks appliqués, balayage arrière pour le dernier texte assistant.
- `SUB_TOOLS` / `SUB_HANDLERS` — les 5 outils du sous-agent (sans `task`), utilisés en interne par `spawn_subagent`.
- `BUILTIN_TOOLS` / `BUILTIN_HANDLERS` — la source des schémas et handlers du parent (`task` → `spawn_subagent` y est déjà câblé).
- `agent_loop(user_input, messages, *, tools, handlers, system)` — la boucle de synthèse, ici en mode pool figé + system figé.
- `print_turn_assistants`, `PROMPT`, `WORKDIR` — rendu du tour, prompt ANSI, racine du workspace.

## Différences avec l'original learn-claude-code

- L'original (`s06_subagent/code.py`, 384 lignes) ré-implémentait tout le harness s02–s05 ; ici tout vit dans shared.py, le fichier ne garde que le câblage (66 lignes).
- L'original ajoutait `task` par `TOOLS.append(...)` après coup ; ici l'outil est déjà déclaré dans `BUILTIN_TOOLS` et on le sélectionne via `pick()`.
- Le `read_file` du sous-agent original n'exposait pas `limit` ; le `SUB_TOOLS` de shared expose `limit` **et** `offset` — la divergence parent/sous-agent a disparu.
- Le `spawn_subagent` de shared boucle sur `has_tool_use(response.content)` (le bloc concret) au lieu de `stop_reason != "tool_use"`, et remplace le double repli « Issue 5 » par un unique balayage arrière systématique.
- Ajout démo : le raccourci `:sub` permet d'observer un sous-agent one-shot sans dépendre de la décision de délégation du modèle parent.

## Lancer la démo

```
python src/sessions/s06.py
```

Avec `:sub liste les fichiers de src/ et résume leur rôle`, on voit le sous-agent enchaîner ses outils puis un unique bloc `[résumé du sous-agent]` — rien d'autre ne survit. En texte libre, demander une tâche en deux volets indépendants incite le parent à appeler `task` (visible en `> task` cyan) ; le parent reste suspendu pendant la délégation (synchrone).

## Liens

- Bibliothèque : [[shared-py]]
- Session précédente : [[s05-todo-write]]
- Session suivante : [[s07-skill-loading]]
- Sessions liées : [[s04-hooks]] (les hooks traversent la frontière du sous-agent), [[s13-background-tasks]] (délégation asynchrone), [[s15-agent-teams]] (généralisation multi-agents)
