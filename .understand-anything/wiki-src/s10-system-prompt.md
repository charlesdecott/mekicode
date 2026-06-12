---
title: "s10 · System Prompt"
session: 10
phase: "Contexte & mémoire"
fichier: "src/sessions/s10.py"
lignes: 111
tags: [system-prompt, assemblage, sections, cache]
prev: "s09-memory"
next: "s11-error-recovery"
---

# s10 · System Prompt

> **En une phrase** : le system prompt est une configuration assemblée depuis `PROMPT_SECTIONS` selon l'état réel — ce fichier montre le system vivant de s20 face à un system de démo figé, mis en cache, et passé tel quel à `agent_loop`.

## Rôle dans le harness

Un system prompt codé en dur ne passe pas à l'échelle : changer de projet oblige à tout réécrire, une modification peut en contredire une autre, et chaque requête transporte des sections inutiles. La thèse de la session : *le prompt est assemblé, pas codé en dur* — des sections toujours chargées (identité, outils, workspace, dans un ordre fixe : un préfixe stable est la condition du prompt caching API) et des sections conditionnelles pilotées par **l'état réel** (la section mémoire n'apparaît que si `.memory/MEMORY.md` existe et a du contenu), jamais par des mots-clés devinés dans la conversation.

[[shared-py]] fournit les fragments (`PROMPT_SECTIONS`) et l'assemblage **vivant** de s20 (`assemble_system_prompt` : horloge, catalogue skills, mémoires, MCP connectés — reconstruit à chaque tour), plus `update_context` qui dérive le contexte de l'état réel. Le délta de ce fichier : un assemblage de démo fidèle à l'original s10 (3 sections fixes + mémoire conditionnelle), le **cache à un emplacement** `get_system_prompt()` — pièce de l'original volontairement non portée dans shared.py, réimplémentée ici —, et le passage d'un system **figé** à `agent_loop(system=...)` : la boucle n'assemble alors plus rien, le prompt est stable pour tout le tour.

## Ce que fait ce fichier

### pick() — lignes 28–30

Le helper commun. Pool minimal de la session (lignes 33–35) : `bash`, `read_file`, `write_file` — les 3 outils de l'original.

### assemble_demo_prompt() — lignes 38–49

```python
def assemble_demo_prompt(context):
    """Version s10 de l'assemblage : 3 sections toujours chargées (ordre
    fixe = préfixe stable, condition du prompt caching API) + la section
    mémoire si et seulement si l'état réel la justifie."""
    sections = [
        PROMPT_SECTIONS["identity"],
        f"Available tools: {', '.join(TOOL_NAMES)}.",
        PROMPT_SECTIONS["workspace"],
    ]
    if context.get("memories"):
        sections.append(f"Relevant memories:\n{context['memories']}")
    return "\n\n".join(sections)
```

Les sections `identity` et `workspace` viennent de `PROMPT_SECTIONS` ; la ligne tools est **réécrite localement** car celle de shared liste les 27 outils du pool complet — faux pour ce sous-ensemble de 3. La section mémoire est conditionnelle : `context["memories"]` n'est non vide que si `MEMORY.md` existe et a du contenu (cf. `update_context`). Comme dans l'original, `PROMPT_SECTIONS["memory"]` reste une clé morte — l'assemblage fabrique sa propre chaîne.

### get_system_prompt() — lignes 56–70 (slots 52–53)

```python
def get_system_prompt(context):
    """Cache à un emplacement (le délta s10 absent de shared.py) : même
    contexte → même chaîne, sans réassemblage. La clé est json.dumps trié."""
    global _last_key, _last_prompt
    key = json.dumps(context, sort_keys=True, ensure_ascii=False, default=str)
    if key == _last_key and _last_prompt:
        print("  \033[90m[cache hit] system prompt inchangé\033[0m")
        return _last_prompt
```

La clé est le contexte sérialisé en JSON **déterministe** (`sort_keys=True` neutralise l'ordre d'insertion, `default=str` absorbe les types non sérialisables) — pas `hash()`, randomisé par processus et `TypeError` sur les structures imbriquées. Hit → trace grise et chaîne mémorisée ; miss → réassemblage, mémorisation, et trace verte listant les sections chargées (lignes 64–70). C'est la pièce manquante de shared.py : inutile pour le system vivant de s20 (l'horloge l'invaliderait à la seconde), elle redevient pertinente dès que le system est figé.

### main() — lignes 73–106

Boucle interactive (`q` pour quitter) :

- `:sections` (85–88) — les fragments de `PROMPT_SECTIONS` (nom, taille, début du texte).
- `:vivant` (89–93) — `assemble_system_prompt(update_context({}, history))` : le system s20, reconstruit à **chaque** appel (horloge, catalogue skills, MCP) ; le relancer deux fois montre pourquoi le mettre en cache serait vain.
- `:fige` (94–96) — `get_system_prompt(...)` : le system de démo, avec ses traces `[assemblé]`/`[cache hit]`.
- Texte libre (101–106) — le tour complet :

```python
        context = update_context({}, history)
        system = get_system_prompt(context)
        turn_start = len(history)
        agent_loop(user, history,
                   tools=TOOLS, handlers=HANDLERS, system=system)
```

Le contexte est dérivé de l'état réel **une fois par tour utilisateur**, le system est figé pour tout le tour (`agent_loop` ne ré-assemble rien quand `system` est fourni). Relancer un prompt sans changement d'état → `[cache hit]` ; créer `.memory/MEMORY.md` entre deux tours (à la main ou via [[s09-memory]]) → réassemblage avec la section `memory` en plus.

## Ce qui vient de [[shared-py]]

Tout est importé explicitement (`from shared import (...)`) — le fichier ne rebinde aucune globale de shared (ses propres slots de cache `_last_key`/`_last_prompt` sont locaux au module).

- `PROMPT_SECTIONS` — les fragments thématiques (`identity` et `workspace` réutilisés tels quels ici).
- `assemble_system_prompt(context)` — l'assemblage vivant de s20, montré par `:vivant` comme point de comparaison.
- `update_context(context, messages)` — la dérivation du contexte depuis l'état réel (`MEMORY.md`, MCP, teammates).
- `agent_loop(..., system=...)` — le mode system figé de la boucle paramétrable.
- `BUILTIN_TOOLS` / `BUILTIN_HANDLERS`, `print_turn_assistants`, `PROMPT`.

## Différences avec l'original learn-claude-code

- L'original (`s10_system_prompt/code.py`, 219 lignes) cassait volontairement la chaîne cumulative (3 outils, boucle nue) ; ici le même esprit, mais la boucle vient de shared.py et le fichier ne garde que l'assemblage + le cache (110 lignes).
- `get_system_prompt` et ses slots `_last_context_key`/`_last_prompt` n'ont **pas** été portés dans shared.py (le system vivant de s20 change à chaque seconde via l'horloge) — réimplémentés ici à l'identique, clé `json.dumps` comprise.
- L'`update_context` original recalculait `enabled_tools` localement ; celui de shared retourne `memories`/`connected_mcp`/`active_teammates` — la clé de cache reste sensible aux mêmes changements d'état réel.
- L'original réévaluait contexte et prompt **après chaque tour d'outils** dans la boucle ; ici le system est figé pour tout le tour utilisateur (contrainte de `agent_loop(system=...)`) — un `MEMORY.md` créé en plein tour n'est vu qu'au tour suivant.
- Ajout démo : `:vivant` met côte à côte le system s20 (jamais cachable) et le system s10 (cachable), ce que l'original ne pouvait pas montrer.

## Lancer la démo

```
python src/sessions/s10.py
```

`:fige` deux fois de suite : `[assemblé] sections : identity, tools, workspace` puis `[cache hit]`. `:vivant` deux fois : deux prompts différents (l'horloge). En texte libre, poser une question, puis créer une mémoire (`python src/sessions/s09.py` + `:seed`, ou écrire `.memory/MEMORY.md` à la main) et reposer une question : `[assemblé] sections : identity, tools, workspace, memory` — la section mémoire est apparue parce que l'état réel a changé, pas parce qu'on a parlé de mémoire.

## Liens

- Bibliothèque : [[shared-py]]
- Session précédente : [[s09-memory]]
- Session suivante : [[s11-error-recovery]]
- Sessions liées : [[s07-skill-loading]] (première injection dynamique dans le system), [[s09-memory]] (produit le `MEMORY.md` que la section conditionnelle consomme)
