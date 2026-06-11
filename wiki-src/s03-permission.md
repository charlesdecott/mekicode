---
title: "s03 · Le système de permission"
session: 03
phase: "Fondamentaux"
fichier: "src/s03.py"
lignes: 99
tags: [permission, deny-list, safe-path, securite]
prev: "s02-tool-use"
next: "s04-hooks"
---

# s03 · Le système de permission

> **En une phrase** : la sécurité est du code, pas de la confiance — trois barrières (`DENY_LIST` sans appel, `DESTRUCTIVE` à confirmation humaine, `safe_path` pour les fichiers) vivent dans le `permission_hook` de [[shared-py]] ; la session expose la politique active, la durcit d'un motif, et empile une règle locale par `register_hook`.

## Rôle dans le harness

Avec bash dans le pool, le modèle peut produire n'importe quelle commande — y compris `rm -rf /` si on lui demande de « nettoyer le projet ». La parade n'est pas de faire confiance au modèle mais d'exécuter un contrôle *dans le harness*, avant chaque outil : interdits absolus refusés sans question (deny list), opérations douteuses soumises à l'humain (`Allow? [y/N]`, refus par défaut), chemins de fichiers confinés au workspace (`safe_path`).

Dans notre harness, ce pipeline est déjà fusionné dans `shared.permission_hook`, enregistré sur l'événement `PreToolUse` à l'import de shared — **avant** `log_hook`, donc un outil refusé n'est jamais loggé (l'ordre d'enregistrement est une politique). La session ne recâble rien : elle rend la politique visible, montre qu'elle est une *donnée* (on ajoute un motif à `DENY_LIST` à chaud) et qu'une règle de session s'empile par `register_hook` sans toucher à la bibliothèque.

## Ce que fait ce fichier

### pick() — lignes 32–34

Même helper qu'en [[s02-tool-use]] : extrait les schémas de `BUILTIN_TOOLS` par nom.

### Câblage module — lignes 26–29, 37–46 et 62

Les imports (lignes 26–29) : `from shared import (...)` nomme les neuf noms consommés ; `import shared` reste pour `shared.PROMPT`, rebindé par la session dans `main()`. Puis les tables :

```python
TOOL_NAMES = ("bash", "read_file", "write_file", "edit_file", "glob")
TOOLS = pick(*TOOL_NAMES)
HANDLERS = {name: BUILTIN_HANDLERS[name] for name in TOOL_NAMES}

SYSTEM = (f"You are a coding agent at {WORKDIR}. "
          "All destructive operations require user approval.")
```

Les 5 outils de l'original. Le `SYSTEM` annonce la règle du jeu au modèle — information, pas protection : la vraie barrière est dans le code. Ligne 46, le durcissement de session :

```python
DENY_LIST.append("format c:")
```

La politique est une liste Python mutable : une session peut l'étendre sans rouvrir le hook (recherche de sous-chaînes naïve, assumée comme dans l'original). `DENY_LIST` étant from-importé, la mutation `append` touche bien la liste partagée du module — c'est le même objet, seul un *rebind* exigerait l'accès qualifié. Ligne 62, `register_hook("PreToolUse", pipe_shell_hook)` empile la règle locale décrite ci-dessous.

### pipe_shell_hook() — lignes 49–59

```python
def pipe_shell_hook(block):
    if block.name == "bash":
        command = block.input.get("command", "")
        if any(dl in command for dl in ("curl", "wget")) and "| sh" in command:
            return "Permission denied: piping a download into a shell"
    return None
```

Une règle de session : refuser les téléchargements exécutés à la volée (`curl ... | sh`). Convention des hooks `PreToolUse` : retourner une chaîne = bloquer l'outil avec ce message en `tool_result` ; `None` = laisser passer. Enregistré *après* `permission_hook` et `log_hook` de shared, il ne voit que les appels déjà passés par la politique globale (et déjà loggés).

### demo_safe_path() — lignes 65–72

La barrière fichiers, démontrée hors LLM (sans dépenser un token) au lancement : `safe_path("notes.txt")` résout sous le workspace et passe ; `safe_path("../hors-workspace.txt")` lève `ValueError` (« Path escapes workspace »), attrapée et affichée (lignes 69–72). Dans le flux réel, ce même contrôle est appliqué deux fois : par `permission_hook` (re-validation des chemins de `write_file`/`edit_file`) et dans les handlers eux-mêmes.

### main() — lignes 75–94

Affiche la politique active — deny list (incluant le `format c:` ajouté), motifs à confirmation — puis appelle `demo_safe_path()` (lignes 77–80) avant le REPL habituel : `agent_loop(query, history, tools=TOOLS, handlers=HANDLERS, system=SYSTEM)` puis `print_turn_assistants` (lignes 90–93). Garde `if __name__` lignes 97–98.

## Ce qui vient de [[shared-py]]

- `DENY_LIST` / `DESTRUCTIVE` — les motifs interdits / à confirmation ; la session étend la première.
- `permission_hook` — le pipeline complet (deny bash, confirmation des destructifs, re-validation `safe_path`, garde MCP « deploy »), pré-enregistré sur `PreToolUse` à l'import.
- `register_hook(event, callback)` — utilisé ligne 62 pour empiler `pipe_shell_hook`.
- `safe_path(p)` — le confinement au workspace, démontré directement.
- `BUILTIN_TOOLS` / `BUILTIN_HANDLERS`, `agent_loop`, `print_turn_assistants`, `WORKDIR`, `PROMPT` — le câblage standard de session. Tout est from-importé explicitement (lignes 27–29), sauf `PROMPT`, rebindé par la session (ligne 76) donc accédé via `shared.PROMPT`.

## Différences avec l'original learn-claude-code

- Le pipeline à trois barrières de l'original (`check_deny_list` + `PERMISSION_RULES`/`check_rules` + `ask_user` + `check_permission`, ~50 lignes) est fusionné dans `shared.permission_hook` — déjà sous la forme *hook* que l'original n'introduisait qu'en s04 ; l'insertion `if not check_permission(block)` dans la boucle correspond au `trigger_hooks("PreToolUse", block)` de `shared.agent_loop`.
- Le format déclaratif `PERMISSION_RULES` a disparu au refactoring : la politique tient dans les deux constantes `DENY_LIST`/`DESTRUCTIVE` (et la deny list de shared ne contient plus `"> /dev/sda"`, comme dans le s04 original).
- Deux ajouts propres à notre session, absents de l'original : l'extension à chaud `DENY_LIST.append("format c:")` et la règle locale `pipe_shell_hook` via `register_hook`.
- `demo_safe_path()` est nouvelle : l'original ne montrait le confinement qu'indirectement, à travers les handlers.
- Les régressions du s03 original (`run_bash` perdant l'encodage UTF-8 et le rattrapage d'`OSError`) sont sans objet : il n'y a plus qu'un `run_bash`, celui de shared.

## Lancer la démo

```
python src/s03.py
```

Au lancement : la deny list et les motifs à confirmation s'affichent, puis la démonstration `safe_path` (chemin interne accepté, `../` rejeté). Ensuite, trois essais parlants : « lance sudo ls » → refus sec (`Permission denied: 'sudo' is on the deny list`) ; « supprime le dossier tmp » → pause `Allow? [y/N]` (Entrée = refus, *fail closed*) ; « écris dans ../dehors.txt » → `Permission denied: path escapes workspace`. Dans tous les cas le modèle reçoit le refus en `tool_result` et peut proposer une alternative. `q` pour quitter.

## Liens

- Bibliothèque : [[shared-py]]
- Session précédente : [[s02-tool-use]]
- Session suivante : [[s04-hooks]]
