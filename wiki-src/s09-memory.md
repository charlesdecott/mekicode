---
title: "s09 · Mémoire persistante"
session: 09
phase: "Contexte & mémoire"
fichier: "src/s09.py"
lignes: 113
tags: [memoire, frontmatter, index, extraction, consolidation]
prev: "s08-context-compact"
next: "s10-system-prompt"
---

# s09 · Mémoire persistante

> **En une phrase** : un magasin `.memory/*.md` + index `MEMORY.md` qui survit à la compaction et aux sessions — ce fichier câble les trois moments mémoire (injection, tour, extraction) autour d'`agent_loop`.

## Rôle dans le harness

La compaction de [[s08-context-compact]] est **avec perte** : « utilise des tabs, pas des espaces » peut devenir « l'utilisateur a des préférences de style » dans le résumé, et une nouvelle session repart de zéro. Il faut une couche qui ne participe pas à la compression : un répertoire `.memory/` où chaque souvenir est un fichier Markdown avec frontmatter (`name`/`description`/`type` parmi `user|feedback|project|reference`), plus un index `MEMORY.md` d'une ligne par souvenir. Le design à deux niveaux de [[s07-skill-loading]] se répète : **l'index** (bon marché) vit dans le system prompt, **le contenu** est sélectionné et injecté à la demande par une side-query LLM (avec repli mots-clés sans API).

Tout le sous-système vit dans [[shared-py]] — c'est la seule section portée de s09 plutôt que de s20, qui l'avait amputée. Le délta de ce fichier : le câblage des trois moments autour d'un tour d'agent — **avant** le tour, `load_memories()` injecte les souvenirs pertinents dans le message utilisateur ; **pendant**, le system vivant (on passe `system=None`) embarque l'index via `update_context` ; **après**, `extract_memories()` capture les nouvelles préférences et `consolidate_memories()` fusionne au-delà de 10 fichiers — plus quatre commandes locales d'observation sans appel API.

## Ce que fait ce fichier

### pick() — lignes 28–30

Le helper commun. Pool de la session (lignes 33–35) : `bash`, `read_file`, `write_file`, `glob` — palette réduite, comme l'original, pour focaliser la session sur la mémoire.

### EXEMPLES — lignes 38–46

Deux mémoires d'amorçage (une `user`, une `project`), en ASCII : shared écrit et relit les fichiers mémoire avec `write_text`/`read_text` sans encodage explicite.

### seed() — lignes 49–56

```python
def seed():
    """Écrit les mémoires d'exemple via write_memory_file (l'index MEMORY.md
    est reconstruit à chaque écriture) — 0 appel API."""
    for name, mem_type, desc, body in EXEMPLES:
        path = write_memory_file(name, mem_type, desc, body)
        print(f"  écrit : {path.name} [{mem_type}]")
    print("index reconstruit :")
    print(read_memory_index())
```

Le point d'entrée déterministe du magasin : `write_memory_file` slugifie le nom, écrit le frontmatter et reconstruit `MEMORY.md` — l'invariant « index toujours synchronisé » tient parce que toute écriture passe par là. Relancer `:seed` écrase les mêmes fichiers (déduplication par construction).

### main() — lignes 59–108

Boucle interactive (`q` pour quitter). Quatre commandes locales, 0 appel API :

- `:seed` (72–74) — écrit les mémoires d'exemple.
- `:index` (75–77) — affiche `read_memory_index()` (ce que le system verra).
- `:fichiers` (78–81) — la liste détaillée de `list_memory_files()` : fichier, type, description.
- `:ctx` (82–87) — le dict de `update_context({}, history)` : l'index `MEMORY.md` (2 000 premiers caractères) + état vivant MCP/teammates — exactement ce que consomme `assemble_system_prompt`.

Le chemin texte libre déroule les trois moments mémoire :

```python
        # 1. Sélection : confronte la conversation récente au catalogue
        # (1 appel LLM, repli mots-clés) et charge le contenu des mémoires
        # retenues. Injecté dans le TOUR utilisateur, pas dans le system.
        probe = history + [{"role": "user", "content": user}]
        mem_block = load_memories(probe)
```

- **Injection** (92–97) : `load_memories` est appelée sur `probe` (l'historique + le message en cours, pas encore appendu) pour que la sélection voie la question du tour ; si des souvenirs sont retenus, le bloc `<relevant_memories>` est préfixé au texte utilisateur (`user_input = f"{mem_block}\n\n{user}"`, ligne 97). Une seule side-query par tour utilisateur.
- **Tour** (101–103) : `agent_loop(user_input, history, tools=TOOLS, handlers=HANDLERS)` — sans `system` : le system **vivant** de shared est utilisé, et `update_context` y place l'index `MEMORY.md` à chaque tour.
- **Post-tour** (107–108) : `extract_memories(history)` (side-query d'extraction, anti-doublons via la liste des mémoires existantes, échec silencieux) puis `consolidate_memories()` (fusion/purge à partir de `CONSOLIDATE_THRESHOLD = 10` fichiers).

## Ce qui vient de [[shared-py]]

Tout est importé explicitement (`from shared import (...)`) — le fichier ne rebinde aucune globale de shared.

- `write_memory_file(name, mem_type, description, body)` — écriture frontmatter + reconstruction d'index (`_rebuild_index`).
- `read_memory_index()` / `list_memory_files()` — lecture de l'index et catalogue détaillé.
- `load_memories(messages)` → `select_relevant_memories` — sélection LLM (repli mots-clés) et bloc `<relevant_memories>`.
- `extract_memories(messages)` — extraction post-tour de nouvelles mémoires.
- `consolidate_memories()` — fusion des doublons au-delà du seuil.
- `update_context(context, messages)` — l'index dans le dict de contexte du system vivant ; `MEMORY_DIR`, `MEMORY_INDEX` (créés à l'import de shared).
- `BUILTIN_TOOLS` / `BUILTIN_HANDLERS`, `agent_loop`, `print_turn_assistants`, `PROMPT`.

## Différences avec l'original learn-claude-code

- L'original (`s09_memory/code.py`, 656 lignes) embarquait tout le sous-système mémoire + le pipeline s08 ; ici 112 lignes, tout vit dans shared.py (qui a porté la mémoire **depuis s09**, s20 n'en gardait que la lecture d'index).
- L'injection originale passait par une copie de `messages` avec remplacement du message à l'indice `memory_turn` (garde contre la compaction en plein tour) ; ici, plus simple : le bloc est préfixé à `user_input` **avant** d'entrer dans `agent_loop` — pas d'indice à protéger.
- L'extraction originale se déclenchait dans la boucle sur `stop_reason != "tool_use"`, avec un snapshot pré-compression ; ici elle court après le retour d'`agent_loop`, sur l'historique tel quel (les tool_result déjà compactés sont perdus pour l'extraction — compromis assumé, l'original n'était fidèle que pour l'itération courante).
- Le `build_system()` original (index dans un system maison) disparaît : le system vivant de shared (`assemble_system_prompt` + `update_context`) fait ce travail.
- Ajout démo : `:seed`/`:index`/`:fichiers`/`:ctx` permettent d'inspecter le magasin sans appel API ; l'original n'offrait que le REPL.

## Lancer la démo

```
python src/s09.py
```

`:seed` puis `:index` montrent le magasin et son index. Poser une question contenant « français » ou « mekicode » : la ligne jaune `[mémoire] N fichier(s) injecté(s) dans le tour` confirme la sélection (LLM ou repli mots-clés). Dire « retiens que je préfère les tests avant le code » : après la réponse, `[Memory: extracted N new memories]` apparaît et `:fichiers` montre le nouveau fichier. Au-delà de 10 fichiers, la consolidation se déclenche en fin de tour.

## Liens

- Bibliothèque : [[shared-py]]
- Session précédente : [[s08-context-compact]]
- Session suivante : [[s10-system-prompt]]
- Sessions liées : [[s07-skill-loading]] (même patron index léger + contenu à la demande), [[s10-system-prompt]] (la section mémoire du system assemblé)
