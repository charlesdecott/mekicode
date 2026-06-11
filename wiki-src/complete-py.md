---
title: "complete.py · Le point d'entrée du harness"
phase: "Bibliothèque"
fichier: "src/complete.py"
lignes: 125
tags: [point-d-entrée, cli, harness]
prev: "shared-py"
---

# complete.py · Le point d'entrée du harness

> **En une phrase** : le CLI qui active TOUTES les features de [[shared-py]] en même temps —
> là où chaque démo `sessions/sNN.py` n'en montre qu'une.

## Rôle dans le harness

C'est le produit, pas la leçon. Les registres complets de [[shared-py]] (27 outils natifs +
pool MCP ré-assemblé à chaque tour), le system prompt vivant, les hooks et permissions, la
compaction automatique, la mémoire persistante, le cron autonome et le drainage d'inbox des
teammates tournent ensemble dans une seule boucle interactive. Par rapport au CLI de
[[s20-comprehensive]] (fidèle à l'original), `complete.py` ajoute la seule feature que s20
n'orchestrait pas : **les trois moments mémoire de [[s09-memory]]** autour du tour d'agent.

## Ce que fait ce fichier

### `AIDE` — lignes 41–46
Le texte des méta-commandes locales (`:aide`, `:memoire`, `:taches`), exécutées sans appel API.

### `inbox_label(msg)` — lignes 49–53
Étiquette d'un message d'inbox (type + `request_id` éventuel) pour l'affichage `[Inbox]` —
même helper local que dans [[s20-comprehensive]].

### `main()` — lignes 56–121
Le REPL complet. Dans l'ordre, à chaque tour :
1. **Méta-commandes** (lignes 73–87) : `:aide`, `:memoire` (index MEMORY.md), `:taches`
   (tableau `.tasks/`) ; `q`/`exit` quitte, une entrée vide ré-affiche le prompt (contrairement
   aux démos sNN où vide = quitter).
2. **Hook UserPromptSubmit + mémoire 1/3** (lignes 92–95) : `load_memories` confronte la
   conversation au catalogue (1 appel LLM, repli mots-clés) et préfixe le tour utilisateur
   du bloc `<relevant_memories>`.
3. **Tour d'agent sous `agent_lock`** (lignes 100–105) : `agent_loop(messages=, context=)`
   avec tools/handlers/system à `None` = registres complets + system vivant (mémoire 2/3 :
   l'index MEMORY.md y figure via `update_context`).
4. **Mémoire 3/3** (lignes 109–110) : `extract_memories` (anti-doublons, échec silencieux)
   puis `consolidate_memories`.
5. **Inbox du lead** (lignes 115–120) : `consume_lead_inbox(route_protocol=True)` route les
   réponses de protocole puis injecte le reste en `[Inbox]` dans l'historique.

En toile de fond : `shared.CLI_ACTIVE = True` (ligne 59, accès qualifié — rebind du module)
et le thread daemon `cron_autorun_loop` (lignes 66–68) qui partage `history`/`context` avec
la boucle humaine, sérialisé par `agent_lock`.

## Ce qui vient de [[shared-py]]

`from shared import (...)` : `PROMPT`, `agent_lock`, `agent_loop`, `consolidate_memories`,
`consume_lead_inbox`, `cron_autorun_loop`, `extract_memories`, `load_memories`,
`print_turn_assistants`, `read_memory_index`, `run_list_tasks`, `trigger_hooks`,
`update_context` — plus `import shared` pour le rebind de `CLI_ACTIVE`.

## Différences avec [[s20-comprehensive]]

- Intégration mémoire complète (les 3 moments de s09) — absente du CLI s20, fidèle à l'original.
- Méta-commandes locales `:aide`/`:memoire`/`:taches`.
- Entrée vide = continuer (au lieu de quitter) : comportement « produit ».

## Lancer

```bash
python src/complete.py    # exige ANTHROPIC_API_KEY et MODEL_ID dans .env
```

## Liens

- Bibliothèque : [[shared-py]]
- La version « leçon » : [[s20-comprehensive]]
- La mémoire qu'il intègre : [[s09-memory]]
