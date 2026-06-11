---
title: "s01 · La boucle perception-action"
session: 01
phase: "Boucle d'agent"
fichier: "inspiration/claude-code-from-scratch/s01_perception_action_loop.py"
lignes: 149
tags: [agent-loop, bash, stop-reason, tool-result, repl]
prev: ""
next: "s02-tool-use"
---

# s01 · La boucle perception-action

> **En une phrase** : un `while True` qui appelle le modèle, exécute l'outil demandé via `dispatch_tools`, renvoie le résultat, et recommence tant que `stop_reason == "tool_use"` — le cycle perception-action sur lequel les 22 sessions suivantes sont bâties sans jamais le modifier.

## Rôle dans le harness

Le README le pose d'emblée : *« The agent loop is the single architectural primitive everything else builds on. A while loop that calls the model, observes what it wants to do, executes it, and feeds the result back. »* Cette session implémente ce primitif dans sa forme la plus nue : un seul outil (`bash`), pas de streaming, pas de permissions, pas de plan. Le motto du fichier — *« One loop & bash is all you need »* — n'est pas une boutade : avec bash seul, l'agent peut déjà lire, écrire, chercher, compiler. Tout le reste du harness est de l'optimisation de ce cycle.

L'architecture suit le premier principe du harness engineering énoncé par le README : *le modèle est la seule source de décisions*. La boucle ne branche jamais sur le contenu de la réponse ; elle ne regarde qu'un champ de protocole, `stop_reason`. Si le modèle veut agir, le harness exécute et rend compte ; si le modèle a fini, le harness s'arrête. Aucune heuristique, aucun parsing de texte.

Dans le vrai Claude Code, l'analogue est la boucle maîtresse `nO` (colonne « Claude Code Analog » du README) — un générateur async streamé, avec compression de contexte et orchestration d'outils, mais le squelette est identique : appel modèle → blocs `tool_use` → exécution → `tool_result` → réinjection. Le repo jumeau learn-claude-code ouvre lui aussi sur cette même boucle (sa session s01), mais avec une différence d'organisation notable : là-bas, la session définit elle-même `run_bash` et le schéma de l'outil ; ici, tout cela vit déjà dans [[core-py]] et la session ne contient *que* la boucle — le code n'est pas cumulatif, c'est le socle qui mutualise.

Détail pédagogique : [[core-py]] expose déjà `stream_loop`, une version streaming de cette même boucle. s01 ne l'utilise volontairement pas — il réécrit la mécanique à la main avec `client.messages.create` pour qu'on voie les engrenages. Dès [[s02-tool-use]], la boucle manuelle disparaît au profit de `stream_loop`.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–18 | Shebang & docstring | Motto « One loop & bash is all you need », les 4 responsabilités de la boucle |
| 20–22 | Imports stdlib | `sys`, `typing` |
| 24–33 | Imports core | `client`, `MODEL`, `DEFAULT_SYSTEM`, `BASIC_TOOLS`, `BASIC_DISPATCH`, `dispatch_tools` |
| 36–87 | **Le cœur** | `agent_loop()` : le cycle perception-action complet |
| 90–143 | REPL | `main()` : saisie utilisateur, historique multi-tours, affichage de la réponse finale |
| 146–149 | Point d'entrée | Garde `if __name__ == "__main__"` |

## Les fonctions, une à une

### `agent_loop(messages, dispatch)` — lignes 38–87

La fonction centrale du repo entier. Elle prend l'historique de conversation (modifié **en place**, retour `None`) et une table de dispatch, puis tourne jusqu'à ce que le modèle rende la main.

```python
    while True:
        # Visual feedback for the user to indicate the LLM is processing
        print("\n\033[36m> Thinking...\033[0m") 
        
        # Request a completion from the Anthropic API
        # We pass the history, the system prompt, and the tool definitions
        response = client.messages.create(
            model=MODEL,             # Specify the AI model to use
            system=DEFAULT_SYSTEM,   # Provide high-level instructions
            messages=messages,       # Pass the full chat history for context
            tools=BASIC_TOOLS,       # Inform the model about available capabilities
            max_tokens=8000,         # Set a high limit for long-running tasks
        )
```

- **Ligne 63** : `client.messages.create` — appel **bloquant, non streamé**. On attend la réponse complète. C'est le seul endroit de tout le repo où la boucle d'agent est écrite sans streaming (hors sous-agents) ; `stream_loop` de [[core-py]] fait la même chose en streamant.
- **Ligne 67** : `tools=BASIC_TOOLS` — codé en dur, alors que `dispatch` est un *paramètre*. L'asymétrie est un piège réel : passer un autre dispatch à `agent_loop` sans changer `BASIC_TOOLS` désynchroniserait ce que le modèle *croit* pouvoir faire de ce que le harness *sait* exécuter.
- **Ligne 68** : `max_tokens=8000` — généreux, pour que les tours intermédiaires (raisonnement + appels d'outils) ne soient pas tronqués.

La suite est le protocole en quatre temps :

```python
        messages.append({"role": "assistant", "content": response.content})

        # Evaluate the 'stop_reason' provided by the API
        # 'tool_use' means the model wants to execute a function before continuing
        if response.stop_reason != "tool_use":
            # If the reason is 'end_turn' or 'max_tokens', we exit the loop
            break

        # If we reached this point, the model has requested one or more tool calls.
        # dispatch_tools iterates over response.content, finds 'tool_use', and runs it.
        results: List[Dict[str, Any]] = dispatch_tools(response.content, dispatch)
        
        # Append the results of the tool execution back into the history.
        # This is sent as a 'user' role but contains 'tool_result' blocks.
        messages.append({"role": "user", "content": results})
```

- **Ligne 73** : archivage du tour assistant **avant** le test de sortie — l'API exige que chaque `tool_use` du contenu assistant soit suivi d'un `tool_result` ; archiver d'abord garantit l'appariement. Notez que `response.content` contient des *objets SDK* (pas des dicts) : l'historique devient hétérogène, ce que `main()` devra gérer.
- **Ligne 77** : le seul branchement de la boucle. `!= "tool_use"` couvre `end_turn` (cas normal) mais aussi `max_tokens` — une réponse coupée en plein vol est traitée comme finale, sans avertissement.
- **Ligne 83** : `dispatch_tools` ([[core-py]]) fait tout le travail d'exécution : itération sur les blocs, lookup dans `dispatch`, capture des exceptions en chaînes `"Error: ..."`, construction des `tool_result`. La boucle ne sait même pas quels outils existent.
- **Ligne 87** : les résultats repartent sous `role: "user"` — du point de vue de l'API, le résultat d'un outil est une *perception*, au même titre qu'un message humain. C'est ça, le « perception-action » du titre.

### `main()` — lignes 92–143

Le REPL : capture l'entrée utilisateur, entretient l'historique, déclenche la boucle, affiche la réponse finale.

```python
    history: List[Dict[str, Any]] = []

    # Persistent loop to keep the interactive session alive
    while True:
        try:
            # Display a cyan-colored prompt to the user
            query: str = input("\033[36ms01 >> \033[0m").strip()
        except (EOFError, KeyboardInterrupt):
            # Gracefully handle Ctrl+D or Ctrl+C to exit the program
            print("\nExiting session.")
            sys.exit(0)
```

- **Ligne 104** : `history` est créé une fois et survit d'une requête à l'autre — la session est **multi-tours** : la deuxième question voit la première, ses appels d'outils et leurs sorties. Rien ne purge cet historique avant [[s06-context-compact]].
- **Lignes 110–114** : `Ctrl+C`/`Ctrl+D` quittent proprement ; `q`/`exit`/`quit` ou ligne vide cassent la boucle (lignes 117–119).
- **Ligne 125** : `agent_loop(history, BASIC_DISPATCH)` — c'est ici que la table `{"bash": ...}` est injectée.

L'affichage final (lignes 129–140) filtre les blocs texte du dernier message :

```python
        for block in last_message.get("content", []):
            # Ensure the block is a text-type block as defined by Anthropic API
            if hasattr(block, 'type') and block.type == "text":
                print(block.text)
            elif isinstance(block, dict) and block.get("type") == "text":
                print(block.get("text"))
```

Double test défensif : les blocs issus de `response.content` sont des objets SDK (accès par attribut, ligne 137), mais le code accepte aussi des dicts (ligne 139) — utile si l'historique a été construit ou rechargé à la main. Les blocs `tool_use` sont silencieusement ignorés : l'utilisateur ne voit que le texte.

### Point d'entrée — lignes 146–149

Garde standard `if __name__ == "__main__": main()` — permet d'importer le fichier sans déclencher le REPL.

## Ce qui vient de [[core-py]]

| Import | Définition dans core.py | Rôle ici |
|---|---|---|
| `client` | ligne 72 | Client Anthropic configuré (`.env`, `ANTHROPIC_BASE_URL` pour LiteLLM) |
| `MODEL` | ligne 75 | ID du modèle, lu depuis `MODEL_ID` |
| `DEFAULT_SYSTEM` | ligne 78 | « You are a coding agent at {cwd}. Use tools to solve tasks. Act, don't explain. » |
| `BASIC_TOOLS` | lignes 356–366 | Le schéma JSON du seul outil `bash` |
| `BASIC_DISPATCH` | lignes 431–433 | `{"bash": lambda inp: run_bash(inp["command"])}` — la table minimale |
| `dispatch_tools` | lignes 524–570 | Exécution des blocs `tool_use` : lookup, capture d'erreurs, format `tool_result` |

C'est `run_bash` (core.py, lignes 100–129) qui porte les garde-fous : liste noire `_ALWAYS_BLOCK` (`rm -rf /`, `sudo`, fork bomb…), timeout 120 s, troncature à 50 000 caractères, et la règle d'or — toute erreur devient une *chaîne* renvoyée au modèle, jamais une exception qui tue la boucle.

## Pièges et détails d'implémentation

- **`tools` codé en dur, `dispatch` injecté** (lignes 67 vs 38) : les deux moitiés du contrat — ce que le modèle voit / ce que le harness exécute — ne sont paramétrées qu'à moitié. Réutiliser `agent_loop` avec un autre dispatch exigerait de toucher au corps de la fonction.
- **`stop_reason == "max_tokens"` sort de la boucle comme `end_turn`** : une réponse tronquée passe pour une réponse finale. Aucune session du repo ne traite ce cas.
- **L'historique mélange objets SDK et dicts** : `agent_loop` y range des objets `ContentBlock` (tour assistant) et des dicts (`tool_result`, requêtes utilisateur). Le double test de `main()` (lignes 137–139) existe précisément pour ça.
- **Rien ne borne la boucle** : pas de compteur de tours, pas de budget. Un modèle qui enchaîne les appels d'outils tourne indéfiniment — acceptable en démo, à border en production.
- **Les erreurs d'outils sont des données** : `dispatch_tools` transforme exceptions et noms d'outils inconnus en texte renvoyé au modèle, qui s'auto-corrige au tour suivant. Le harness ne crashe jamais sur un outil.
- **La boucle exacte de ce fichier réapparaît telle quelle dans [[s04-subagent]]**, recopiée à l'intérieur d'un handler d'outil — preuve que le primitif est composable.

## Lancer la démo

```bash
cd inspiration/claude-code-from-scratch
python s01_perception_action_loop.py
```

Prérequis : `pip install -r requirements.txt`, puis un `.env` avec `ANTHROPIC_API_KEY` et `MODEL_ID` (ou `ANTHROPIC_BASE_URL=http://localhost:4000` vers un proxy LiteLLM pour tout autre fournisseur — voir le README du repo, option B).

On observe : le prompt cyan `s01 >> `, puis pour chaque tour `> Thinking...`, les appels d'outils en jaune (`[bash] ls...` suivi des 300 premiers caractères de sortie, affichage fait par `dispatch_tools`), et enfin `Final Answer:` en vert avec le texte seul. Essayez « liste les fichiers Python de ce dossier et compte leurs lignes » : le modèle enchaîne plusieurs tours bash avant de répondre.

## Liens

- Socle : [[core-py]]
- Session suivante : [[s02-tool-use]]
- Sessions liées : [[s04-subagent]] (la même boucle, encapsulée dans un outil), [[s13-streaming]] (le même cycle en version streamée), [[s18-parallel-tools]] (le même cycle en version async parallèle)
