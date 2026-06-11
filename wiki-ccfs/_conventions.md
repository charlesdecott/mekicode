# Conventions du wiki claude-code-from-scratch (fichier interne — ne pas afficher dans la navigation)

## Objectif
Wiki markdown français, compatible Obsidian, expliquant en profondeur le repo
`inspiration/claude-code-from-scratch/` : le socle `core.py` et les 23 sessions
`s01` à `s23`. Contrairement à learn-claude-code, **le code n'est pas cumulatif** :
chaque session est une démo autonome qui importe `core.py` et ajoute UN mécanisme.

## Carte des pages (noms EXACTS pour les wikilinks, sans .md)
| Page | Source | Phase | Lignes |
|---|---|---|---|
| core-py | inspiration/claude-code-from-scratch/core.py | Socle | 626 |
| s01-perception-action-loop | inspiration/claude-code-from-scratch/s01_perception_action_loop.py | Boucle d'agent | 149 |
| s02-tool-use | inspiration/claude-code-from-scratch/s02_tool_use.py | Boucle d'agent | 96 |
| s03-todo-write | inspiration/claude-code-from-scratch/s03_todo_write.py | Boucle d'agent | 241 |
| s04-subagent | inspiration/claude-code-from-scratch/s04_subagent.py | Boucle d'agent | 190 |
| s05-skill-loading | inspiration/claude-code-from-scratch/s05_skill_loading.py | Connaissance & contexte | 234 |
| s06-context-compact | inspiration/claude-code-from-scratch/s06_context_compact.py | Connaissance & contexte | 252 |
| s07-task-system | inspiration/claude-code-from-scratch/s07_task_system.py | Connaissance & contexte | 313 |
| s08-background-tasks | inspiration/claude-code-from-scratch/s08_background_tasks.py | Async & multi-agents | 236 |
| s09-agent-teams | inspiration/claude-code-from-scratch/s09_agent_teams.py | Async & multi-agents | 317 |
| s10-team-protocols | inspiration/claude-code-from-scratch/s10_team_protocols.py | Async & multi-agents | 316 |
| s11-autonomous-agents | inspiration/claude-code-from-scratch/s11_autonomous_agents.py | Async & multi-agents | 355 |
| s12-worktree-task-isolation | inspiration/claude-code-from-scratch/s12_worktree_task_isolation.py | Async & multi-agents | 276 |
| s13-streaming | inspiration/claude-code-from-scratch/s13_streaming.py | Durcissement production | 140 |
| s14-tools-extended | inspiration/claude-code-from-scratch/s14_tools_extended.py | Durcissement production | 110 |
| s15-permissions | inspiration/claude-code-from-scratch/s15_permissions.py | Durcissement production | 169 |
| s16-event-bus | inspiration/claude-code-from-scratch/s16_event_bus.py | Durcissement production | 301 |
| s17-session-management | inspiration/claude-code-from-scratch/s17_session_management.py | Durcissement production | 301 |
| s18-parallel-tools | inspiration/claude-code-from-scratch/s18_parallel_tools.py | Runtime async | 266 |
| s19-interrupts | inspiration/claude-code-from-scratch/s19_interrupts.py | Runtime async | 239 |
| s20-cache-optimization | inspiration/claude-code-from-scratch/s20_cache_optimization.py | Runtime async | 266 |
| s21-mcp-runtime | inspiration/claude-code-from-scratch/s21_mcp_runtime.py | Runtime async | 344 |
| s22-production-mailbox | inspiration/claude-code-from-scratch/s22_production_mailbox.py | Entreprise | 370 |
| s23-worktree-advanced | inspiration/claude-code-from-scratch/s23_worktree_advanced.py | Entreprise | 467 |

Page d'accueil : `Accueil` (rédigée séparément). Page du socle : `core-py`.

## Gabarit des pages de session (OBLIGATOIRE — mêmes sections, même ordre)

```markdown
---
title: "sNN · Titre court"
session: NN
phase: "Boucle d'agent | Connaissance & contexte | Async & multi-agents | Durcissement production | Runtime async | Entreprise"
fichier: "inspiration/claude-code-from-scratch/sNN_xxx.py"
lignes: NNN
tags: [tag1, tag2, tag3]
prev: "sNN-1-xxx ou vide pour s01"
next: "sNN+1-xxx ou vide pour s23"
---

# sNN · Titre court

> **En une phrase** : ce que cette session apporte au harness.

## Rôle dans le harness
2-4 paragraphes : le problème que cette session résout, pourquoi il se pose,
comment Claude Code (le vrai) traite ce problème. Si la session a un équivalent
dans learn-claude-code, le signaler en texte libre (PAS de wikilink inter-projets).

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

## Ce qui vient de [[core-py]]
Liste des fonctions/constantes importées depuis core.py et leur rôle ici
(le code n'est pas cumulatif : c'est core.py qui mutualise, pas la session précédente).

## Pièges et détails d'implémentation
3-6 puces : les détails qu'on rate à la première lecture.

## Lancer la démo
La commande (`python sNN_xxx.py` depuis le repo), les prérequis (.env, proxy LiteLLM,
Redis pour s22, dépôt git pour s12/s23, fichiers config/ pour s15/s16/s21…)
et ce qu'on observe.

## Liens
- Socle : [[core-py]]
- Session précédente : [[sNN-1-xxx]] (omettre pour s01)
- Session suivante : [[sNN+1-xxx]] (omettre pour s23)
- Sessions liées : [[...]] thématiquement (voir carte ci-dessus)
```

## Gabarit de la page core-py
Mêmes sections que les sessions SAUF : pas de `session:`/`prev:`/`next:` dans le
frontmatter (`phase: "Socle"`), pas de section « Ce qui vient de core-py » ; à la
place, une section `## Qui importe quoi` listant les groupes d'exports et les
sessions qui les consomment. La section « Lancer la démo » devient
`## Utilisation` (core.py ne se lance pas seul).

## Règles
1. **Tout en français** ; termes techniques standards en anglais (hook, tool use, prompt caching, worktree…).
2. **Wikilinks** : format `[[s02-tool-use]]` — exactement les noms de la carte, jamais d'extension `.md`.
3. **Lignes précises** : chaque fonction est référencée `lignes X–Y` d'après le fichier source réel — VÉRIFIER en lisant le fichier, ne pas estimer.
4. **Extraits réels** : le code cité doit être copié du fichier source, pas réécrit de mémoire.
5. **Exhaustivité** : chaque fonction/classe du fichier a sa sous-section `###`. Les imports de core.py
   sont traités dans « Ce qui vient de [[core-py]] » avec un renvoi, pas re-expliqués en détail.
6. Lire aussi le `README.md` du repo pour le narratif de la phase, et citer ses idées clés
   (analogie avec le vrai Claude Code : colonne « Claude Code Analog »).
7. Pas d'HTML dans le markdown ; tableaux et blocs de code standards uniquement.
8. `lignes:` du frontmatter = nombre de lignes physiques réel du fichier source.
