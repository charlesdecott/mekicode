---
title: "s14 · Outils étendus"
session: 14
phase: "Durcissement production"
fichier: "inspiration/claude-code-from-scratch/s14_tools_extended.py"
lignes: 110
tags: [tools, snapshots, revert, read, write, grep, glob, system-prompt]
prev: "s13-streaming"
next: "s15-permissions"
---

# s14 · Outils étendus

> **En une phrase** : la session active l'arsenal complet de [[core-py]] (bash, read, write, grep, glob, **revert**) et le rend *réversible* — chaque `write` snapshote l'ancien contenu, et un prompt système dédié ordonne au modèle de préférer ces outils gérés au bash brut.

## Rôle dans le harness

Un agent qui ne dispose que de bash manipule les fichiers en aveugle pour le harness : `sed -i`, `echo > fichier` ou `cat` sont **destructifs et opaques** — le docstring le dit explicitement (lignes 23–27) : *« Raw bash commands like `sed` or `echo > file` are destructive and opaque to the harness. Specialized tools provide the harness with hooks for logging, security filtering, and state management. »* Tant que l'action passe par une chaîne shell, impossible d'y greffer journalisation, permissions ou undo.

La réponse de s14 tient en deux idées, énoncées par la devise *« More hands, but every touch is reversible »* (ligne 6). D'une part des **outils spécialisés** : `read` renvoie des numéros de ligne 1-indexés (le modèle peut citer « ligne 42 » de façon fiable), `grep`/`glob` remplacent des pipelines shell fragiles. D'autre part la **réversibilité** : avant chaque écrasement, `run_write` de core.py sauvegarde le contenu original dans le dictionnaire `SNAPSHOTS`, et l'outil `revert` le restaure — y compris en *supprimant* un fichier qui n'existait pas avant le `write`.

Le README (tableau Phase 4) donne l'analogie : **« CC's 18-tool arsenal »**. Le vrai Claude Code expose une vingtaine d'outils typés (Read, Write, Edit, Glob, Grep, Bash…) précisément pour les mêmes raisons : chaque action devient observable, filtrable et validable. Le repo jumeau learn-claude-code introduit ses outils fichiers dès sa session 2 ; ici la mécanique vit dans core.py depuis le début, et s14 est la session qui la met en scène et l'explique.

Le fichier lui-même est le plus court de la phase : tout le mécanisme (snapshots, handlers, schémas) est dans [[core-py]], et s14 n'apporte que la *politique* — un prompt système qui oriente le modèle vers les bons outils. C'est une leçon de harness engineering en soi : quand l'infrastructure est mutualisée, activer une capacité coûte un prompt et un choix de dispatch, pas du code.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–27 | Shebang & docstring | Motto, 4 concepts (snapshots, réversibilité, sortie structurée, efficacité), « Why prefer these over Bash? » |
| 29–32 | Imports stdlib | `os`, `sys`, `typing` |
| 34–40 | Imports core | `EXTENDED_TOOLS`, `EXTENDED_DISPATCH`, `stream_loop` |
| 42–53 | Configuration | `SYSTEM` : le prompt « Safety-First » |
| 55–104 | REPL | `main()` : bannière listant les outils actifs, boucle de saisie, délégation à `stream_loop` |
| 107–110 | Point d'entrée | `if __name__ == "__main__"` |

## Constantes et configuration

- **`SYSTEM` (lignes 46–53)** : le seul vrai « delta » de la session.

```python
SYSTEM: str = (
    f"You are a coding agent at {os.getcwd()}. "
    "You have access to a suite of specialized file tools. "
    "PREFER using 'read', 'write', 'grep', and 'glob' over raw bash commands "
    "for file operations. These tools provide better formatting and "
    "automatic snapshots. If you make a mistake or break the code, "
    "use the 'revert' tool to restore the previous state immediately."
)
```

Trois consignes : préférer les outils gérés au bash (« PREFER » en capitales — emphase de prompt, pas de syntaxe), annoncer le bénéfice (formatage + snapshots automatiques) et **enseigner le réflexe `revert`** en cas d'erreur. Les schémas exposent bash de toute façon ; c'est le prompt, pas le code, qui infléchit le comportement. C'est la même approche que le vrai Claude Code, dont le prompt système décrit longuement quand utiliser quel outil.

## Les fonctions, une à une

### `main()` — lignes 57–104

L'unique fonction du fichier. La bannière d'abord :

```python
    # UI Header: Extract names of active tools for display in Gray (\033[90m)
    active_tool_names: List[str] = [tool["name"] for tool in EXTENDED_TOOLS]
    print(f"\033[90ms14: extended tools | {', '.join(active_tool_names)} | snapshots active\033[0m\n")
```

- **Lignes 65–66** : la liste des outils affichée est *dérivée* de `EXTENDED_TOOLS` plutôt que codée en dur — si core.py gagne un outil, la bannière suit automatiquement. On y lit `bash, read, write, grep, glob, revert`.

Puis le REPL (lignes 73–104) : saisie cyan avec `try/except (EOFError, KeyboardInterrupt)` → `sys.exit(0)` (lignes 74–80), sortie sur entrée vide ou `q`/`exit`/`quit` avec un « Goodbye. » (lignes 83–85), archivage de la requête dans `history` (ligne 88), et enfin la délégation complète :

```python
        stream_loop(
            messages=history,
            tools=EXTENDED_TOOLS,
            dispatch=EXTENDED_DISPATCH,
            system=SYSTEM
        )
```

- **Lignes 96–101** : contrairement à [[s13-streaming]] qui ré-écrivait la boucle pour l'exposer, s14 consomme `stream_loop` de [[core-py]] tel quel — streaming, dispatch, ré-injection des `tool_result`, tout est mutualisé. Le commentaire au-dessus de l'appel (lignes 90–95) résume d'ailleurs les 4 étapes du contrat de `stream_loop`. La session ne fournit que les trois paramètres qui la caractérisent : les schémas, la table de dispatch, et son prompt système « Safety-First ».

### Point d'entrée — lignes 107–110

`if __name__ == "__main__": main()` — protection standard.

## Ce qui vient de [[core-py]]

Importés lignes 36–40 — c'est ici que vit *tout* le mécanisme de la session :

- **`EXTENDED_TOOLS`** — les 6 schémas JSON (bash, read, write, grep, glob, revert). La description de `write` annonce déjà le contrat au modèle : *« Snapshots previous content automatically »* ; celle de `revert` : *« Restore a file to its state before the last write »*.
- **`EXTENDED_DISPATCH`** — la table nom → handler vers `run_bash`, `run_read` (numérotation des lignes, plage `start_line`/`end_line`), `run_write` (**snapshot dans `SNAPSHOTS` avant écriture** ; `None` si le fichier est nouveau), `run_grep` (grep système avec repli `findstr` sous Windows), `run_glob`, `run_revert` (réécrit le contenu snapshoté, ou supprime le fichier s'il a été créé par le `write`). Détail complet sur la page [[core-py]].
- **`stream_loop`** — la boucle streaming + dispatch + ré-injection, le moteur que s14 se contente de paramétrer.

## Pièges et détails d'implémentation

- **Les snapshots sont en mémoire uniquement** : `SNAPSHOTS` est un dict Python de core.py. Fermer le process = perdre tout l'historique d'undo. Une isolation durable passe par git — c'est l'approche de [[s12-worktree-task-isolation]] et [[s23-worktree-advanced]].
- **Un seul niveau d'undo par fichier** : chaque `write` écrase le snapshot précédent du même chemin. Deux écritures successives puis un `revert` ne restaurent que l'état d'avant la *dernière* écriture, pas l'original. Et `run_revert` fait un `SNAPSHOTS.pop()` : un second `revert` sur le même chemin répond « no snapshot ».
- **`revert` d'un fichier *créé* le supprime** : `run_write` stocke `None` quand le fichier n'existait pas, et `run_revert` interprète `None` comme « supprimer ». L'undo est donc complet dans les deux sens — création comme modification.
- **bash reste dans l'arsenal** : le prompt dit « PREFER », pas « never ». Un `echo > fichier` via bash contourne entièrement les snapshots — aucune barrière technique ici ; la vraie gouvernance arrive avec [[s15-permissions]].
- **Il n'y a pas d'outil `edit`** : contrairement au vrai Claude Code (et à learn-claude-code), pas de remplacement exact de chaîne — le modèle doit ré-écrire le fichier entier via `write`. Les numéros de ligne de `read` compensent en partie.
- **`os` n'est importé que pour `os.getcwd()`** dans le prompt système (ligne 47) ; `Optional` est importé (ligne 32) mais jamais utilisé — scorie de gabarit.

## Lancer la démo

```bash
python s14_tools_extended.py
```

Prérequis : `.env` avec `ANTHROPIC_API_KEY` et `MODEL_ID` (ou proxy LiteLLM). Scénario type au prompt `s14 >>` : demander « crée un fichier hello.py qui affiche bonjour » (le `write` confirme `created: ... (snapshot saved — use revert to undo)`), puis « modifie-le pour afficher l'heure » (`updated`), puis « finalement reviens en arrière » — le modèle appelle `revert` et le fichier retrouve son état précédent. La bannière confirme `snapshots active`.

## Liens

- Socle : [[core-py]]
- Session précédente : [[s13-streaming]]
- Session suivante : [[s15-permissions]]
- Sessions liées : [[s02-tool-use]] (la naissance du dispatch par table), [[s12-worktree-task-isolation]] (réversibilité par git plutôt qu'en mémoire), [[s18-parallel-tools]] (les mêmes outils en version asynchrone)
