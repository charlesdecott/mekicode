# Conventions du wiki (fichier interne — ne pas afficher dans la navigation)

## Objectif
Wiki markdown français, compatible Obsidian, expliquant en profondeur chacune des 20 sessions de
`inspiration/learn-claude-code/` : chaque partie du fichier, chaque fonction/classe, et les lignes
de code importantes.

## Carte des pages (noms EXACTS pour les wikilinks, sans .md)
| Page | Source | Phase | Lignes |
|---|---|---|---|
| s01-agent-loop | inspiration/learn-claude-code/s01_agent_loop/code.py | Fondamentaux | 113 |
| s02-tool-use | inspiration/learn-claude-code/s02_tool_use/code.py | Fondamentaux | 153 |
| s03-permission | inspiration/learn-claude-code/s03_permission/code.py | Fondamentaux | 198 |
| s04-hooks | inspiration/learn-claude-code/s04_hooks/code.py | Fondamentaux | 248 |
| s05-todo-write | inspiration/learn-claude-code/s05_todo_write/code.py | Fondamentaux | 254 |
| s06-subagent | inspiration/learn-claude-code/s06_subagent/code.py | Fondamentaux | 324 |
| s07-skill-loading | inspiration/learn-claude-code/s07_skill_loading/code.py | Fondamentaux | 360 |
| s08-context-compact | inspiration/learn-claude-code/s08_context_compact/code.py | Contexte & mémoire | 446 |
| s09-memory | inspiration/learn-claude-code/s09_memory/code.py | Contexte & mémoire | 559 |
| s10-system-prompt | inspiration/learn-claude-code/s10_system_prompt/code.py | Contexte & mémoire | 174 |
| s11-error-recovery | inspiration/learn-claude-code/s11_error_recovery/code.py | Contexte & mémoire | 305 |
| s12-task-system | inspiration/learn-claude-code/s12_task_system/code.py | Tâches & temps | 304 |
| s13-background-tasks | inspiration/learn-claude-code/s13_background_tasks/code.py | Tâches & temps | 389 |
| s14-cron-scheduler | inspiration/learn-claude-code/s14_cron_scheduler/code.py | Tâches & temps | 666 |
| s15-agent-teams | inspiration/learn-claude-code/s15_agent_teams/code.py | Multi-agents | 774 |
| s16-team-protocols | inspiration/learn-claude-code/s16_team_protocols/code.py | Multi-agents | 737 |
| s17-autonomous-agents | inspiration/learn-claude-code/s17_autonomous_agents/code.py | Multi-agents | 672 |
| s18-worktree-isolation | inspiration/learn-claude-code/s18_worktree_isolation/code.py | Intégration & synthèse | 825 |
| s19-mcp-plugin | inspiration/learn-claude-code/s19_mcp_plugin/code.py | Intégration & synthèse | 851 |
| s20-comprehensive | inspiration/learn-claude-code/s20_comprehensive/code.py | Intégration & synthèse | 1780 |

Page d'accueil : `Accueil` (rédigée séparément).

## Gabarit de page (OBLIGATOIRE — mêmes sections, même ordre)

```markdown
---
title: "sNN · Titre court"
session: NN
phase: "Fondamentaux | Contexte & mémoire | Tâches & temps | Multi-agents | Intégration & synthèse"
fichier: "inspiration/learn-claude-code/sNN_xxx/code.py"
lignes: NNN
tags: [tag1, tag2, tag3]
prev: "sNN-1-xxx ou vide pour s01"
next: "sNN+1-xxx ou vide pour s20"
---

# sNN · Titre court

> **En une phrase** : ce que cette session apporte au harness.

## Rôle dans le harness
2-4 paragraphes : le problème que cette session résout, pourquoi il se pose,
comment Claude Code (le vrai) traite ce problème.

## Vue d'ensemble du fichier
Tableau des zones du fichier :
| Lignes | Zone | Contenu |
|---|---|---|
| 1–15 | Imports & docstring | ... |
...

## Constantes et configuration
Chaque constante/structure globale, avec sa valeur et son rôle (lignes précises).
(Omettre la section s'il n'y en a pas.)

## Les fonctions, une à une
Pour CHAQUE fonction et classe du fichier, dans l'ordre du fichier :

### `nom_fonction(args)` — lignes X–Y
Ce qu'elle fait, pourquoi, comment. Inclure un extrait du code réel (pas le fichier
entier — les passages décisifs) en bloc ```python, suivi d'une explication
ligne-par-ligne des passages non triviaux. Signaler les subtilités
(gestion d'erreurs, cas limites, choix de design).

## Ce qui change par rapport à [[page-précédente]]
Liste précise des ajouts/modifications vs la session précédente
(le code est cumulatif : chaque session reprend la précédente et ajoute UN mécanisme).

## Pièges et détails d'implémentation
3-6 puces : les détails qu'on rate à la première lecture.

## Liens
- Session précédente : [[sNN-1-xxx]] (omettre pour s01)
- Session suivante : [[sNN+1-xxx]] (omettre pour s20)
- Sessions liées : [[...]] thématiquement (voir carte ci-dessus)
```

## Règles
1. **Tout en français** ; termes techniques standards en anglais (hook, tool use, prompt caching, worktree…).
2. **Wikilinks** : format `[[s02-tool-use]]` — exactement les noms de la carte, jamais d'extension `.md`.
3. **Lignes précises** : chaque fonction est référencée `lignes X–Y` d'après le fichier source réel — VÉRIFIER en lisant le fichier, ne pas estimer.
4. **Extraits réels** : le code cité doit être copié du fichier source, pas réécrit de mémoire.
5. **Exhaustivité** : chaque fonction/classe du fichier a sa sous-section `###`. Les helpers répétés
   d'une session à l'autre (repris sans modification) peuvent être traités brièvement avec un renvoi
   `repris de [[sNN-xxx]] sans modification` — mais les fonctions NOUVELLES ou MODIFIÉES sont expliquées à fond.
6. Lire aussi le `README.en.md` du dossier de la session pour le narratif, et citer ses idées clés.
7. Pas d'HTML dans le markdown ; tableaux et blocs de code standards uniquement.
