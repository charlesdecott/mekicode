---
title: "s02 · Tool use et dispatch"
session: 02
phase: "Fondamentaux"
fichier: "src/sessions/s02.py"
lignes: 61
tags: [tool-use, dispatch, pool-fige]
prev: "s01-agent-loop"
next: "s03-permission"
---

# s02 · Tool use et dispatch

> **En une phrase** : deux tables parallèles — `TOOLS` (ce que le modèle voit) et `HANDLERS` (ce que le harness exécute) — câblées par `pick()` sur les registres de [[shared-py]] et passées à `shared.agent_loop` : ajouter un outil ne coûte qu'une entrée par table, la boucle n'est jamais touchée.

## Rôle dans le harness

Un agent qui n'a que bash doit traduire chaque intention en syntaxe shell (« lire ce fichier » → `cat ...`) : une couche de traduction qui gaspille des tokens et invite les erreurs. La réponse durable est architecturale : des outils spécialisés décrits par des schémas JSON, et un **dispatch par table** — la boucle cherche le handler dans un dict au lieu d'appeler une fonction en dur. La boucle devient un moteur générique ; les capacités deviennent des données.

Dans notre harness, les 27 schémas (`BUILTIN_TOOLS`) et la table miroir (`BUILTIN_HANDLERS`) vivent déjà dans [[shared-py]]. Le délta de session se réduit donc au **câblage d'un sous-ensemble** : `pick()` extrait 3 outils (`bash`, `read_file`, `write_file`) et `shared.agent_loop` est appelée en mode paramétré — `tools`/`handlers` fournis = pool figé (pas de ré-assemblage MCP à chaque tour), `system` fourni = system prompt figé (pas de system vivant).

## Ce que fait ce fichier

### pick() — lignes 26–28

Le helper emblématique des sessions :

```python
def pick(*names):
    """Sous-ensemble de BUILTIN_TOOLS par noms — le délta de chaque session."""
    return [t for t in BUILTIN_TOOLS if t["name"] in names]
```

Il filtre les schémas du registre par nom : la session ne réécrit aucun `input_schema`, elle choisit dans le catalogue.

### Câblage module — lignes 21–23 et 31–36

Les imports d'abord (lignes 21–23) : `from shared import (...)` nomme explicitement les cinq noms consommés, et `import shared` est conservé pour `shared.PROMPT`, que la session rebinde dans `main()` (une affectation sur un nom from-importé ne toucherait pas le module). Puis les tables :

```python
TOOL_NAMES = ("bash", "read_file", "write_file")
TOOLS = pick(*TOOL_NAMES)
HANDLERS = {name: BUILTIN_HANDLERS[name] for name in TOOL_NAMES}

SYSTEM = (f"You are a coding agent at {WORKDIR}. "
          "Use tools to solve tasks. Act, don't explain.")
```

Les deux tables parallèles de la session : `TOOLS` dit au *modèle* ce qui existe, `HANDLERS` dit au *harness* quoi exécuter. La compréhension de dict (ligne 33) garantit la symétrie : tout nom de `TOOL_NAMES` doit exister dans `BUILTIN_HANDLERS`, sinon `KeyError` à l'import — échec rapide plutôt qu'outil silencieusement inerte. Le `SYSTEM` reprend la consigne de l'original (« Use tools », « Act, don't explain »).

### main() — lignes 39–56

Le REPL : prompt `s02 >> ` (ligne 40), bannière listant le pool figé (lignes 41–42), boucle de saisie avec sortie sur `q`/Ctrl-C (lignes 45–51). Le tour d'agent :

```python
        turn_start = len(history)
        agent_loop(query, history,
                   tools=TOOLS, handlers=HANDLERS, system=SYSTEM)
        print_turn_assistants(history, turn_start)
```

`turn_start` mémorise la longueur de l'historique avant le tour ; `agent_loop` mute `history` en place (la question est ajoutée par le paramètre `user_input`) ; `print_turn_assistants` rend ensuite uniquement les textes assistants produits pendant ce tour. La garde `if __name__` occupe les lignes 59–60.

## Ce qui vient de [[shared-py]]

- `BUILTIN_TOOLS` / `BUILTIN_HANDLERS` — le catalogue des 27 outils et la table nom → fonction ; la session en extrait 3.
- `agent_loop(user_input, messages, *, tools, handlers, system)` — la boucle de synthèse, ici en mode pool figé + system figé.
- `print_turn_assistants(messages, turn_start)` — rendu des textes assistants du tour.
- `WORKDIR`, `PROMPT` — racine du workspace (dans `SYSTEM`) et prompt ANSI repositionné. Tout est from-importé explicitement (lignes 22–23), sauf `PROMPT` : la session le rebinde (ligne 40), l'accès reste donc qualifié `shared.PROMPT`.
- Implicitement : `call_tool_handler` (dispatch durci, `TypeError` → message d'erreur), `safe_path` (confinement de `read_file`/`write_file`), et les hooks enregistrés à l'import (`permission_hook`, `log_hook`…) — actifs sans une ligne de câblage ici.

## Différences avec l'original learn-claude-code

- Les ~100 lignes d'implémentations (`safe_path`, `run_bash`, `run_read`, `run_write`, `run_edit`, `run_glob`), les 5 schémas `TOOLS` et la table `TOOL_HANDLERS` de l'original vivent dans shared.py ; le fichier de session n'est plus que le câblage `pick()` + dict.
- Sous-ensemble resserré : 3 outils (`bash`, `read_file`, `write_file`) au lieu des 5 de l'original — assez pour démontrer le dispatch, et la réduction même démontre le pool *paramétrable*.
- La boucle `while` recopiée de s01 dans l'original est remplacée par `shared.agent_loop`, qui embarque au passage des mécanismes hérités des sessions ultérieures (compaction, retry, rappel todo, file cron) — le délta de session n'en câble aucun explicitement.
- Le dispatch `handler(**block.input)` nu de l'original est durci dans `shared.call_tool_handler` : un argument inattendu produit un message d'erreur pour le modèle au lieu d'un `TypeError` non rattrapé.
- Contrairement à l'original (aucun contrôle hors `safe_path`), les appels passent ici par `PreToolUse` : `shared.permission_hook` est déjà enregistré à l'import de shared.

## Lancer la démo

```
python src/sessions/s02.py
```

On observe : la bannière annonce le pool figé de 3 outils ; à chaque appel d'outil, la trace `[HOOK] <nom>` (le `log_hook` de shared) puis le nom en cyan et l'aperçu de sortie imprimés par `agent_loop`. Demander par exemple « liste les fichiers du dossier puis écris un résumé dans resume.txt » enchaîne bash → write_file dans le même tour. `q` pour quitter.

## Liens

- Bibliothèque : [[shared-py]]
- Session précédente : [[s01-agent-loop]]
- Session suivante : [[s03-permission]]
