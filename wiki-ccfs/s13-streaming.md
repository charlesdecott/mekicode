---
title: "s13 · Streaming"
session: 13
phase: "Durcissement production"
fichier: "inspiration/claude-code-from-scratch/s13_streaming.py"
lignes: 140
tags: [streaming, text-stream, ttft, context-manager, repl]
prev: "s12-worktree-task-isolation"
next: "s14-tools-extended"
---

# s13 · Streaming

> **En une phrase** : la boucle d'agent passe de `messages.create()` (bloquant) à `client.messages.stream()` — les tokens s'affichent au fil de leur génération, et `stream.get_final_message()` reconstitue à la fin le même objet `Message` que la version bloquante, donc rien d'autre ne change.

## Rôle dans le harness

Jusqu'ici (s01–s12 de ce repo), chaque tour de boucle est un appel bloquant : l'utilisateur fixe un terminal muet pendant que le modèle génère, puis tout le texte tombe d'un coup. Le problème n'est pas le débit total mais la **latence perçue** : le docstring du fichier (lignes 21–22) parle de réduire le *Time To First Token* (TTFT) à quelques millisecondes — le terminal « feels alive », dit la devise de la session (ligne 5).

La session ouvre la phase « Durcissement production » du README : *« the gap between a working agent and a deployable one »*. Dans la colonne « Claude Code Analog », le streaming est marqué **« Always-on in CC »** — le vrai Claude Code ne propose même pas de mode bloquant ; tout son rendu terminal (texte, spinners, affichage incrémental des tool calls) est construit sur le flux d'événements de l'API.

Particularité pédagogique assumée par le docstring (lignes 24–26) : `core.stream_loop()` fait déjà exactement cela pour les autres sessions. s13 **ré-implémente la boucle à la main** pour rendre le mécanisme visible — c'est la seule session de la phase qui n'appelle pas `stream_loop`, alors que [[s14-tools-extended]], [[s15-permissions]] et [[s17-session-management]] lui délèguent tout. Comparer `agent_loop_streaming` (ci-dessous) avec `stream_loop` de [[core-py]] : c'est ligne pour ligne la même structure.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–27 | Shebang & docstring | Motto, 4 concepts (UI événementielle, context manager, finalisation, TTFT) |
| 29–31 | Imports stdlib | `sys`, `typing` |
| 33–42 | Imports core | `client`, `MODEL`, `DEFAULT_SYSTEM`, `EXTENDED_TOOLS`, `EXTENDED_DISPATCH`, `dispatch_tools` |
| 45–99 | **Le mécanisme** | `agent_loop_streaming()` : la boucle ré-écrite en mode flux |
| 102–135 | REPL | `main()` : saisie utilisateur, historique, relance de la boucle |
| 138–140 | Point d'entrée | `if __name__ == "__main__"` |

## Les fonctions, une à une

### `agent_loop_streaming(messages)` — lignes 47–99

La boucle Thinking→Acting classique, mais dont la phase « appel API » est un flux. Le cœur :

```python
        with client.messages.stream(
            model=MODEL,               # The LLM engine
            system=DEFAULT_SYSTEM,     # Persona and behavioral constraints
            messages=messages,         # History for context
            tools=EXTENDED_TOOLS,      # Available capabilities
            max_tokens=8000,           # Response limit
        ) as stream:
            # Iterate over the text fragments as they arrive from the Anthropic API
            for text in stream.text_stream:
                # Print the partial text without a newline
                # flush=True ensures the token appears immediately in the terminal
                print(text, end="", flush=True)

            # After the stream finishes, retrieve the fully assembled Message object
            # This object contains the full 'text' and any 'tool_use' blocks
            response = stream.get_final_message()
```

- **Ligne 65** : `client.messages.stream(...)` dans un `with` — le context manager garantit que la connexion HTTP est ouverte puis fermée proprement, même si une exception interrompt l'itération (concept n° 2 du docstring).
- **Lignes 73–76** : `stream.text_stream` est un itérateur de **fragments de texte uniquement** — le SDK filtre pour nous les événements bas niveau (`content_block_delta`, etc.) et ne livre que les deltas textuels. `print(text, end="", flush=True)` : pas de retour à la ligne entre les fragments, et `flush=True` court-circuite le buffering de stdout pour que chaque token apparaisse immédiatement.
- **Ligne 80** : `stream.get_final_message()` — le point décisif de la session. Le SDK a accumulé tous les événements pendant l'itération et reconstitue le `Message` complet : texte assemblé, **blocs `tool_use`** (qui ne passent jamais par `text_stream`), `stop_reason`, métadonnées d'usage. Tout l'aval de la boucle travaille sur cet objet exactement comme si l'appel avait été bloquant.
- **Lignes 87–92** : archivage du tour assistant (`messages.append`) puis test `response.stop_reason != "tool_use"` → `return`. Identique aux sessions précédentes : le streaming ne change que la *perception*, pas le contrat de la boucle.
- **Lignes 96–99** : l'exécution des outils est entièrement déléguée à `dispatch_tools(response.content, EXTENDED_DISPATCH)` de [[core-py]], et les `tool_result` repartent dans l'historique comme un tour `user`. Les outils, eux, ne streament pas : leur sortie tombe en bloc une fois exécutée — seul le texte du modèle est progressif.

### `main()` — lignes 104–135

Le REPL standard du repo : bannière grise (ligne 109), historique vide (ligne 112), puis boucle infinie de saisie.

```python
        try:
            # User Prompt in Cyan
            query: str = input("\033[36ms13 >> \033[0m").strip()
        except (EOFError, KeyboardInterrupt):
            # Handle Ctrl+C/D gracefully
            print("\nExiting session.")
            sys.exit(0)

        # Basic exit handling
        if not query or query.lower() in ("q", "exit", "quit"):
            break
```

- **Lignes 116–122** : Ctrl+C / Ctrl+D sont attrapés autour du `input()` et provoquent un `sys.exit(0)` propre — mais un Ctrl+C **pendant le streaming** n'est pas attrapé, lui (voir Pièges).
- **Ligne 125** : entrée vide ou `q`/`exit`/`quit` → sortie par `break`. Noter le garde `not query` : il disparaîtra dans [[s17-session-management]], avec des conséquences.
- **Lignes 129–132** : la requête est ajoutée à `history` puis `agent_loop_streaming(history)` prend la main jusqu'à ce que le modèle rende un tour sans tool use. `history` persiste entre les tours du REPL : c'est une vraie conversation multi-tours, en mémoire seulement (la persistance disque arrive en [[s17-session-management]]).

### Point d'entrée — lignes 138–140

`if __name__ == "__main__": main()` — protection standard, rien de plus.

## Ce qui vient de [[core-py]]

Importés lignes 35–42 :

- **`client`** — le client Anthropic configuré (`.env`, `ANTHROPIC_BASE_URL` pour LiteLLM) ; c'est sur lui qu'on appelle `.messages.stream()`.
- **`MODEL`** — l'ID de modèle lu dans `MODEL_ID`.
- **`DEFAULT_SYSTEM`** — le prompt système générique (« You are a coding agent at <cwd>… ») ; s13 ne le personnalise pas.
- **`EXTENDED_TOOLS`** — les 6 schémas d'outils (bash, read, write, grep, glob, revert) annoncés au modèle.
- **`EXTENDED_DISPATCH`** — la table nom → handler correspondante.
- **`dispatch_tools`** — l'exécuteur de blocs `tool_use` (itération, affichage jaune, gestion d'erreurs, format `tool_result`) ; s13 ré-écrit la boucle mais pas le dispatch.

## Pièges et détails d'implémentation

- **`text_stream` ne contient pas les tool calls** : si le modèle ne génère *que* des `tool_use` sans texte, la boucle `for text in ...` ne produit rien à l'écran — le tour semble silencieux jusqu'au `[tool]` jaune de `dispatch_tools`. Les blocs outils n'existent que dans `get_final_message()`.
- **`get_final_message()` est obligatoire, pas optionnel** : sans lui, on n'a ni `stop_reason` ni `response.content` à archiver. Le streaming « pur affichage » sans finalisation casserait la boucle.
- **Le `with` doit englober `get_final_message()`** : l'appel se fait avant la sortie du context manager, pendant que le flux est encore vivant côté SDK.
- **Ctrl+C pendant la génération n'est pas géré** : le `try/except KeyboardInterrupt` de `main()` n'entoure que `input()`. Une interruption en plein stream remonte et tue le process — l'injection d'interruptions propre est précisément le sujet de [[s19-interrupts]].
- **Double maintien de l'état d'affichage** : ici le texte est seulement imprimé ; [[s16-event-bus]] reprendra la même boucle en accumulant les fragments (`text_chunks.append`) pour pouvoir émettre l'événement `agent_response` avec le texte complet.
- **Redondance assumée avec `stream_loop`** : tout ce fichier équivaut à `stream_loop(history, EXTENDED_TOOLS, EXTENDED_DISPATCH)` — une ligne. La valeur de s13 est de montrer ce que cette ligne cache.

## Lancer la démo

```bash
python s13_streaming.py
```

Prérequis : `.env` avec `ANTHROPIC_API_KEY` et `MODEL_ID` (ou proxy LiteLLM via `ANTHROPIC_BASE_URL`), dépendances de `requirements.txt`. Au prompt `s13 >>`, poser une question longue (« explique-moi ce repo ») : le texte apparaît token par token au lieu de tomber en bloc ; demander une action fichier pour voir les tool calls s'intercaler entre les passages streamés.

## Liens

- Socle : [[core-py]]
- Session précédente : [[s12-worktree-task-isolation]]
- Session suivante : [[s14-tools-extended]]
- Sessions liées : [[s19-interrupts]] (interrompre le flux en cours de génération), [[s18-parallel-tools]] (la version asynchrone de la boucle), [[s16-event-bus]] (la même boucle streaming, instrumentée d'événements)
