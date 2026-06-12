# Conventions du wiki src_scratch/ (fichier interne — ne pas afficher dans la navigation)

## Objectif
Wiki markdown français, compatible Obsidian, documentant **notre code** dans `src_scratch/` :
la refonte dédupliquée de `inspiration/claude-code-from-scratch/` (un socle + 23 sessions,
6 574 lignes) en 11 modules + 1 config.yaml (2 033 lignes de modules), sans perte de feature.
`main.py` est LE point d'entrée : un REPL où toutes les features sont actives.

## Carte des pages (noms EXACTS pour les wikilinks, sans .md)
| Page | Source | Phase | Lignes | Sessions source couvertes |
|---|---|---|---|---|
| core-py | src_scratch/core.py | Fondations | 158 | core + s15 + s16 |
| tools-py | src_scratch/tools.py | Fondations | 252 | core + s02 + s08 + s14 |
| loop-py | src_scratch/loop.py | Fondations | 242 | s01 + s13 + s15 + s16 + s18 + s19 + s20 |
| context-py | src_scratch/context.py | Contexte & tâches | 159 | s05 + s06 |
| tasks-py | src_scratch/tasks.py | Contexte & tâches | 221 | s03 + s07 + s11 (board) |
| mailbox-py | src_scratch/mailbox.py | Multi-agents | 170 | s09 + s22 |
| agents-py | src_scratch/agents.py | Multi-agents | 212 | s04 + s09 + s10 + s11 (workers) |
| worktree-py | src_scratch/worktree.py | Intégration | 172 | s12 + s23 |
| sessions-py | src_scratch/sessions.py | Intégration | 120 | s17 |
| mcp-runtime-py | src_scratch/mcp_runtime.py | Intégration | 146 | s21 |
| main-py | src_scratch/main.py | Intégration | 181 | s17 (REPL) + assemblage |

Page d'accueil : `Accueil`. La config (`config.yaml`, permissions 3 tiers + serveurs MCP)
est documentée dans la page core-py (qui la charge).

## Gabarit des pages de module (OBLIGATOIRE — mêmes sections, même ordre)

```markdown
---
title: "module.py · Titre court"
phase: "Fondations | Contexte & tâches | Multi-agents | Intégration"
fichier: "src_scratch/module.py"
lignes: NNN
tags: [tag1, tag2, tag3]
---

# module.py · Titre court

> **En une phrase** : ce que ce module apporte au harness.

## Rôle dans le harness
1-3 paragraphes : la responsabilité du module, pourquoi ce découpage,
ce qu'il remplace dans le repo source (sessions couvertes).

## Vue d'ensemble du fichier
Tableau des zones du fichier :
| Lignes | Zone | Contenu |
|---|---|---|

## Constantes et configuration
(Omettre s'il n'y en a pas.)

## Les fonctions, une à une
Pour CHAQUE fonction/classe du fichier, dans l'ordre :
### `nom(args)` — lignes X–Y
Explication + extrait du code réel pour les passages décisifs.

## Bugs de la source corrigés ici
Les `# FIX(mekicode):` du fichier, un par puce : le bug original (session source)
et la correction. (Omettre si aucun.)

## Qui l'utilise
Modules de src_scratch qui importent ce module, et pour quoi. Wikilinks.

## Pièges et détails d'implémentation
2-5 puces.

## Liens
- Modules liés : [[...]]
```

## Règles
1. Tout en français ; termes techniques standards en anglais (hook, tool use, worktree…).
2. Wikilinks `[[...]]` : uniquement les noms de la carte ci-dessus (projet src_scratch),
   jamais `.md`. PAS de wikilinks vers les autres wikis (learn, ccfs, src) — texte libre.
3. Numéros de lignes vérifiés sur le fichier réel de `src_scratch/`.
4. Extraits copiés du source, jamais réécrits de mémoire.
5. `lignes:` du frontmatter = nombre de lignes physiques réel du fichier source.
6. Le repo source de référence est `inspiration/claude-code-from-scratch/` et son wiki
   `wiki-ccfs/` — citer les sessions sNN en texte libre (ex. « s09 »), pas en wikilink.
7. Pas d'HTML ; tableaux et blocs de code standards uniquement.
