# Conventions du wiki src/ (fichier interne — ne pas afficher dans la navigation)

## Objectif
Wiki markdown français, compatible Obsidian, documentant **notre code** dans `src/` :
`shared.py` (bibliothèque commune dédupliquée de learn-claude-code) et les sessions
`s01.py` à `s20.py` (démos exécutables, chacune = le délta d'une session).

## Carte des pages (noms EXACTS pour les wikilinks, sans .md)
| Page | Source | Phase |
|---|---|---|
| shared-py | src/shared.py | Bibliothèque |
| complete-py | src/complete.py | Bibliothèque |
| s01-agent-loop | src/sessions/s01.py | Fondamentaux |
| s02-tool-use | src/sessions/s02.py | Fondamentaux |
| s03-permission | src/sessions/s03.py | Fondamentaux |
| s04-hooks | src/sessions/s04.py | Fondamentaux |
| s05-todo-write | src/sessions/s05.py | Fondamentaux |
| s06-subagent | src/sessions/s06.py | Fondamentaux |
| s07-skill-loading | src/sessions/s07.py | Fondamentaux |
| s08-context-compact | src/sessions/s08.py | Contexte & mémoire |
| s09-memory | src/sessions/s09.py | Contexte & mémoire |
| s10-system-prompt | src/sessions/s10.py | Contexte & mémoire |
| s11-error-recovery | src/sessions/s11.py | Contexte & mémoire |
| s12-task-system | src/sessions/s12.py | Tâches & temps |
| s13-background-tasks | src/sessions/s13.py | Tâches & temps |
| s14-cron-scheduler | src/sessions/s14.py | Tâches & temps |
| s15-agent-teams | src/sessions/s15.py | Multi-agents |
| s16-team-protocols | src/sessions/s16.py | Multi-agents |
| s17-autonomous-agents | src/sessions/s17.py | Multi-agents |
| s18-worktree-isolation | src/sessions/s18.py | Intégration & synthèse |
| s19-mcp-plugin | src/sessions/s19.py | Intégration & synthèse |
| s20-comprehensive | src/sessions/s20.py | Intégration & synthèse |

Page d'accueil : `Accueil`. Page de la bibliothèque : `shared-py`.

## Gabarit des pages de session (OBLIGATOIRE)

```markdown
---
title: "sNN · Titre court"
session: NN
phase: "<phase de la carte>"
fichier: "src/sNN.py"
lignes: NNN
tags: [tag1, tag2]
prev: "<page précédente ou vide>"
next: "<page suivante ou vide>"
---

# sNN · Titre court

> **En une phrase** : ce que cette session démontre.

## Rôle dans le harness
1-2 paragraphes : le concept, pourquoi il compte pour notre harness.

## Ce que fait ce fichier
Pour CHAQUE fonction du fichier, sous-section `### nom() — lignes X–Y` avec
explication et extraits si non triviaux. Les fichiers sont courts : sois précis.

## Ce qui vient de [[shared-py]]
Liste des fonctions/classes importées depuis shared.py et leur rôle ici.

## Différences avec l'original learn-claude-code
2-5 puces : ce qu'on a simplifié/corrigé/déplacé vers shared.py par rapport à
`inspiration/learn-claude-code/sNN_*/code.py` (texte libre, PAS de wikilink vers
le wiki learn — les wikilinks ne traversent pas les projets).

## Lancer la démo
La commande (`python src/sNN.py`) et ce qu'on observe.

## Liens
- Bibliothèque : [[shared-py]]
- Session précédente / suivante : [[...]]
```

## Règles
1. Tout en français ; termes techniques standards en anglais.
2. Wikilinks `[[...]]` : uniquement les noms de la carte ci-dessus (projet src), jamais `.md`.
3. Numéros de lignes vérifiés sur le fichier réel de `src/`.
4. Extraits copiés du source, jamais réécrits de mémoire.
5. `lignes:` du frontmatter = nombre de lignes physiques réel du fichier source.
