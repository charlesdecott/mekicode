---
title: "s02 · Tool use et dispatch"
session: 02
phase: "Boucle d'agent"
fichier: "inspiration/claude-code-from-scratch/s02_tool_use.py"
lignes: 96
tags: [tool-use, dispatch-map, stream-loop, read, write, grep, glob, revert]
prev: "s01-perception-action-loop"
next: "s03-todo-write"
---

# s02 · Tool use et dispatch

> **En une phrase** : la boucle manuelle de [[s01-perception-action-loop]] disparaît dans `stream_loop` de [[core-py]] et l'agent passe de 1 à 6 outils — la session entière tient en un appel : brancher `EXTENDED_TOOLS` (ce que le modèle voit) sur `EXTENDED_DISPATCH` (ce que le harness exécute).

## Rôle dans le harness

Avec bash seul, le modèle doit traduire chaque intention en syntaxe shell : `cat` pour lire, `echo >` pour écrire, `grep -rn` pour chercher. Cette couche de traduction gaspille des tokens et multiplie les erreurs d'échappement et de quotes — surtout multi-plateformes. La réponse est le **dispatch map pattern**, motto de la session : *« Adding a tool means adding one handler »*. Deux structures parallèles suffisent : une liste de schémas JSON (`EXTENDED_TOOLS`) déclarée au modèle, et un dict nom → fonction (`EXTENDED_DISPATCH`) consulté par le harness. La boucle, elle, ne connaît aucun outil : elle est devenue un moteur générique.

La particularité de ce repo — par contraste avec learn-claude-code, dont la session s02 homologue *construit* dans son fichier `safe_path`, quatre outils et la table `TOOL_HANDLERS` — est que tout est déjà mutualisé dans [[core-py]]. Le fichier de session ne définit **rien** : il choisit. Ses 96 lignes contiennent une seule décision architecturale, visible dans l'appel `stream_loop(messages=..., tools=EXTENDED_TOOLS, dispatch=EXTENDED_DISPATCH)`. C'est l'illustration la plus pure du principe du README : *« every session contains only its one new concept »*.

Deuxième apport, plus discret : c'est la **première session qui streame**. `stream_loop` affiche les tokens au fil de l'eau au lieu d'attendre la réponse complète comme le `create()` de s01. Et l'arsenal inclut d'office `revert` : chaque `write` snapshote le contenu précédent dans `SNAPSHOTS`, ce qui rend les écritures réversibles dès maintenant ([[s14-tools-extended]] en fera la démonstration dédiée).

Dans le vrai Claude Code, l'analogue est le **registre de 18 outils** (colonne « Claude Code Analog » du README) : chaque outil y est un objet complet — schéma, validation, vérification de permissions, exécution, parallélisation des outils sûrs en concurrence. La version pédagogique exécute tout séquentiellement dans l'ordre de `response.content`, sans gouvernance ([[s15-permissions]] viendra) et sans parallélisme ([[s18-parallel-tools]] viendra).

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–22 | Shebang & docstring | Motto « Adding a tool means adding one handler », 3 concepts : séparation des responsabilités, scalabilité, abstraction |
| 24–26 | Imports stdlib | `sys`, `typing` |
| 28–34 | Imports core | `EXTENDED_TOOLS`, `EXTENDED_DISPATCH`, `stream_loop` — trois imports, c'est tout |
| 36–89 | REPL | `main()` : la seule fonction du fichier |
| 92–96 | Point d'entrée | Garde `if __name__ == "__main__"` |

Aucune constante, aucun outil, aucune boucle définis localement : le fichier est un *câblage*.

## Les fonctions, une à une

### `main()` — lignes 38–89

Structure REPL identique à [[s01-perception-action-loop]] : header gris (ligne 48, qui annonce la palette : `bash, read, write, grep, glob, revert`), `history` initialisé une fois (ligne 52), capture d'entrée avec sortie propre sur `Ctrl+C`/`Ctrl+D` (lignes 56–64), mots de sortie `q`/`exit`/`quit` (lignes 67–69). La différence tient en un appel :

```python
        # --- The Core Logic of Session 02 ---
        # Instead of manually checking tool_use (as in s01), we call `stream_loop`.
        # This function will:
        #   1. Call the Anthropic API with the current history.
        #   2. Stream the text output to the console in real-time.
        #   3. If the model calls a tool, look up the function in `EXTENDED_DISPATCH`.
        #   4. Execute the tool, append results, and repeat until the task is done.
        stream_loop(
            messages=history,            # Pass the mutated state
            tools=EXTENDED_TOOLS,        # Pass the full suite of file/shell tools
            dispatch=EXTENDED_DISPATCH   # Provide the routing map for those tools
        )
```

- **Ligne 83** : `messages=history` — `stream_loop` mute la liste en place, exactement comme `agent_loop` de s01 ; au retour, `history` contient tous les tours intermédiaires (assistant + `tool_result`), pas seulement la réponse finale.
- **Lignes 84–85** : le couple `tools`/`dispatch` est passé *ensemble* — contrairement au `agent_loop` de s01 qui codait `BASIC_TOOLS` en dur et ne paramétrait que le dispatch. La désynchronisation possible entre « ce que le modèle voit » et « ce que le harness exécute » est ici résolue par l'appelant.
- **Pas de paramètre `system`** : `stream_loop` retombe sur `DEFAULT_SYSTEM` de [[core-py]]. [[s03-todo-write]] sera la première session à le personnaliser.
- Pas d'affichage « Final Answer » comme en s01 : le streaming a déjà tout imprimé au fil de l'eau ; il ne reste qu'un `print()` de séparation (ligne 89).

### Point d'entrée — lignes 92–96

Garde standard, avec un commentaire qui explicite l'intention : permettre l'import du fichier par d'autres sessions sans déclencher le REPL.

## Ce qui vient de [[core-py]]

| Import | Définition dans core.py | Rôle ici |
|---|---|---|
| `EXTENDED_TOOLS` | lignes 369–426 | `BASIC_TOOLS` + 5 schémas : `read` (plages `start_line`/`end_line` 1-indexées), `write` (« Snapshots previous content automatically »), `grep` (regex, `recursive` par défaut), `glob` (motifs `**/*.py`), `revert` (restaure l'état d'avant le dernier `write`) |
| `EXTENDED_DISPATCH` | lignes 436–443 | La table de routage : six lambdas qui adaptent le dict d'input du modèle aux signatures Python (`inp["path"]`, `inp.get("start_line")`…) |
| `stream_loop` | lignes 573–626 | La boucle complète : `client.messages.stream`, affichage token par token, archivage, test `stop_reason`, appel de `dispatch_tools`, réinjection des `tool_result` |

Derrière la table, les implémentations (toujours core.py) : `run_bash` (100–129, liste noire + timeout 120 s), `run_read` (132–166, numérotation des lignes façon `cat -n`), `run_write` (169–201, snapshot dans `SNAPSHOTS` avant écrasement, `makedirs` automatique), `run_grep` (204–240, `grep -n` avec **fallback `findstr`** pour Windows), `run_glob` (243–258, tri + plafond 200 résultats), `run_revert` (261–292, restaure ou supprime selon que le fichier préexistait).

## Pièges et détails d'implémentation

- **L'adaptation d'arguments se fait par lambda, pas par `**input`** : `lambda inp: run_read(inp["path"], inp.get("start_line"), inp.get("end_line"))`. Conséquence : un argument halluciné en trop est *silencieusement ignoré* (là où un `handler(**block.input)` lèverait `TypeError`), et un argument requis manquant lève `KeyError` — mais `dispatch_tools` attrape l'exception et la renvoie au modèle comme texte.
- **Aucune restriction de chemin** : pas d'équivalent du `safe_path` de learn-claude-code. `write` et `read` acceptent n'importe quel chemin absolu, et bash n'est filtré que par la courte liste `_ALWAYS_BLOCK`. La gouvernance déclarative n'arrive qu'en [[s15-permissions]].
- **`SNAPSHOTS` est en mémoire seulement** : le filet de sécurité de `revert` disparaît au redémarrage du process, et il ne retient que *le dernier* état d'avant-écriture par chemin (pas un historique).
- **Troncatures asymétriques** : à l'écran, `dispatch_tools` n'affiche que 300 caractères de sortie d'outil ; le modèle, lui, reçoit jusqu'à 50 000 caractères (10 000 pour `grep`). Ce qu'on voit dans le terminal n'est pas ce que voit le modèle.
- **`grep` dépend du système** : binaire `grep` requis ; le fallback Windows `findstr` ne couvre que `*.py`, `*.js`, `*.md` — des résultats différents selon la plateforme pour la même requête du modèle.
- **Exécution strictement séquentielle** : plusieurs `tool_use` dans un même tour sont exécutés dans l'ordre de `response.content`. Le passage au parallèle ([[s18-parallel-tools]]) devra préserver les dépendances implicites (lire avant d'éditer).

## Lancer la démo

```bash
cd inspiration/claude-code-from-scratch
python s02_tool_use.py
```

Prérequis : `pip install -r requirements.txt` et un `.env` avec `ANTHROPIC_API_KEY` + `MODEL_ID` (ou proxy LiteLLM via `ANTHROPIC_BASE_URL`).

On observe : le texte du modèle qui **streame** token par token (nouveauté vs s01), et les outils en jaune au format `[read] core.py...`, `[grep] def run_...`. Bon test : « trouve toutes les fonctions async de core.py et écris leur liste dans async_report.md » — le modèle enchaîne `grep`, `read`, `write` ; demandez ensuite « annule » pour voir `revert` restaurer le fichier.

## Liens

- Socle : [[core-py]]
- Session précédente : [[s01-perception-action-loop]]
- Session suivante : [[s03-todo-write]]
- Sessions liées : [[s14-tools-extended]] (l'arsenal et `revert` en démonstration dédiée), [[s15-permissions]] (la gouvernance qui manque au dispatch), [[s18-parallel-tools]] (la même table en version async), [[s21-mcp-runtime]] (le registre s'ouvre aux serveurs MCP externes)
