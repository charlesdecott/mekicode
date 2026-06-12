---
title: "s18 · Outils en parallèle"
session: 18
phase: "Runtime async"
fichier: "inspiration/claude-code-from-scratch/s18_parallel_tools.py"
lignes: 266
tags: [asyncio, gather, parallel, async-dispatch, tool-use]
prev: "s17-session-management"
next: "s19-interrupts"
---

# s18 · Outils en parallèle

> **En une phrase** : quand le modèle demande plusieurs outils dans le même tour, on ne les exécute plus l'un après l'autre — `asyncio.gather` lance toutes les coroutines en même temps, et un dictionnaire `id → résultat` réassemble les `tool_result` dans l'ordre attendu par l'API.

**Fait notable, à connaître avant de lire** : dans le dépôt tel que publié (vérifié sur le commit HEAD), `s18_parallel_tools.py` est **octet pour octet identique** à `s20_cache_optimization.py` — une erreur d'empaquetage en amont (le fichier porte même la docstring « s20_cache_optimization.py »). Le mécanisme que la session devait isoler — l'exécution parallèle par `asyncio.gather` — y est néanmoins bien présent (lignes 202–214) : c'est lui que cette page met au premier plan. Tout ce qui relève du prompt caching (`CACHED_SYSTEM`, `CACHED_TOOLS`, `CacheStats`) est traité en profondeur dans [[s20-cache-optimization]].

## Rôle dans le harness

Depuis [[s02-tool-use]], la boucle exécute les `tool_use` d'un tour **séquentiellement, dans l'ordre de `response.content`** : trois `read` de 200 ms chacun coûtent 600 ms. Or la plupart des appels d'un même tour sont indépendants — lire trois fichiers, lancer un `grep` et un `glob`. La latence s'additionne pour rien, et le mur s'aggrave avec les outils lents (un `bash` qui compile, un `grep` récursif).

La réponse de la phase « Runtime async » : basculer toute la boucle en asyncio. Le README la résume ainsi : *« parallel tool execution collapses multi-tool turns from sequential to concurrent »*. Concrètement, chaque `tool_use` devient une coroutine `dispatch_one_tool(block)` ; `asyncio.gather(*...)` les lance toutes et attend que la dernière finisse. Le tour ne coûte plus la **somme** des durées d'outils mais leur **maximum**.

Dans le vrai Claude Code (colonne « Claude Code Analog » du README : *CC parallel execution*), la parallélisation est plus prudente : les appels sont partitionnés en lots où seuls les outils sûrs en concurrence (`isConcurrencySafe()` — les lectures, pas les écritures) tournent ensemble. Ici, **tout** part en parallèle sans analyse de dépendances — y compris deux `write` sur le même fichier. C'est le compromis pédagogique assumé de la session.

Pas d'équivalent direct dans learn-claude-code : ce repo-là reste sur une exécution séquentielle des outils (sa session « background tasks » parallélise des commandes de fond, pas les `tool_use` d'un tour).

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–26 | Shebang & docstring | Docstring de s20 (duplication amont) : prompt caching, cache_control |
| 28–33 | Imports stdlib | `asyncio`, `os`, `copy`, `sys`, typing |
| 35–42 | Imports core | `client`, `MODEL`, `EXTENDED_TOOLS`, `ASYNC_DISPATCH` |
| 44–67 | Config cacheable | `CACHED_SYSTEM`, `CACHED_TOOLS` (voir [[s20-cache-optimization]]) |
| 70–124 | Statistiques | classe `CacheStats` + instance globale `stats` |
| 127–158 | **Le cœur de s18** | `dispatch_one_tool()` : un appel d'outil = une coroutine |
| 161–214 | Boucle | `agent_loop_cached()` : stream en thread + `asyncio.gather` (202–214) |
| 217–258 | Point d'entrée | `main()` : REPL async, `input()` via `run_in_executor` |
| 261–266 | Garde | `asyncio.run(main())` sous `if __name__ == "__main__"` |

## Constantes et configuration

- **`CACHED_SYSTEM` (lignes 48–60)** et **`CACHED_TOOLS` (lignes 63–67)** : le prompt système en liste de blocs et la copie profonde d'`EXTENDED_TOOLS` marquées `cache_control` — détaillées dans [[s20-cache-optimization]] ; pour la lecture « s18 », retenez seulement que la boucle les passe à l'API à la place de `DEFAULT_SYSTEM`/`EXTENDED_TOOLS`.
- **`stats = CacheStats()` (ligne 124)** : instance globale de comptage de tokens, lue dans `main()` via le `finally`.

## Les fonctions, une à une

### Classe `CacheStats` — lignes 72–120

Compteur de tokens cache (méthodes `__init__` 77–82, `record` 84–95, `show_turn` 97–113, `summary` 115–120). Elle appartient au mécanisme de [[s20-cache-optimization]], où chaque méthode est expliquée ligne par ligne ; elle n'interagit pas avec la parallélisation (elle ne fait que lire `response.usage` après chaque tour).

### `dispatch_one_tool(block)` — lignes 129–158

L'unité de parallélisme : **un appel d'outil = une coroutine autonome**, qui loggue, exécute et rapporte sans rien savoir de ses voisines.

```python
async def dispatch_one_tool(block: Any) -> Tuple[str, str]:
    tool_input = block.input
    tool_name = block.name
    handler = ASYNC_DISPATCH.get(tool_name)
    first_val = str(list(tool_input.values())[0])[:80] if tool_input else ""
    print(f"\033[33m[{tool_name}] {first_val}...\033[0m")
    try:
        output = await handler(tool_input) if handler else f"Error: Unknown tool {tool_name}"
    except Exception as e:
        output = f"Execution Error: {e}"
    print(str(output)[:200])
    return block.id, str(output)
```

- **Ligne 143** : `ASYNC_DISPATCH.get(tool_name)` — la table de dispatch **asynchrone** de [[core-py]] remplace `EXTENDED_DISPATCH`. `.get()` pour ne pas lever de `KeyError` sur un nom halluciné.
- **Ligne 151** : `await handler(tool_input) if handler else ...` — le `await` ne porte que sur la branche vraie ; si le handler manque, la chaîne d'erreur est renvoyée telle quelle (pas de coroutine à attendre).
- **Lignes 149–153** : le `try/except` est **dans** la coroutine, pas autour du `gather`. C'est décisif : une exception attrapée ici devient une chaîne `"Execution Error: ..."` retournée normalement, donc `asyncio.gather` (qui par défaut propage la première exception et laisse les autres tâches orphelines) ne voit jamais d'échec. Chaque outil échoue individuellement, le tour survit.
- **Ligne 158** : la coroutine retourne le couple `(block.id, output)` — pas un `tool_result` formaté. La séparation exécution / formatage permet à la boucle de réassembler les résultats par identifiant, peu importe l'ordre d'achèvement.
- **Lignes 147 et 156** : les `print` de plusieurs coroutines concurrentes **s'entrelacent** dans le terminal — c'est d'ailleurs le signe visible que la parallélisation fonctionne.

### `agent_loop_cached(messages)` — lignes 163–214

La boucle perception-action, version async. Deux idées : sortir l'appel API bloquant de l'event loop, et remplacer le `for block in response.content` séquentiel par un `gather`.

```python
        def _blocking_stream_call():
            with client.messages.stream(
                model=MODEL,
                system=CACHED_SYSTEM,
                messages=messages,
                tools=CACHED_TOOLS,
                max_tokens=8000,
            ) as stream:
                for text in stream.text_stream:
                    print(text, end="", flush=True)
                return stream.get_final_message()

        response = await asyncio.get_event_loop().run_in_executor(None, _blocking_stream_call)
```

- **Lignes 173–184** : le SDK Anthropic synchrone bloquerait l'event loop pendant tout le streaming ; on l'enferme dans une closure exécutée par `run_in_executor(None, ...)` (ligne 187) — le thread pool par défaut. L'event loop reste libre (ce qui deviendra vital dans [[s19-interrupts]], où il doit pouvoir réagir pendant que le modèle « pense »).

Le cœur de la session, lignes 202–214 :

```python
        # Parallel Tool Execution
        tool_blocks = [b for b in response.content if b.type == "tool_use"]
        execution_pairs = await asyncio.gather(*[dispatch_one_tool(b) for b in tool_blocks])

        # Map results back to the tool use IDs
        results_map = dict(execution_pairs)
        turn_results = [
            {"type": "tool_result", "tool_use_id": b.id, "content": results_map[b.id]}
            for b in tool_blocks
        ]
        messages.append({"role": "user", "content": turn_results})
```

- **Ligne 203** : on filtre d'abord les blocs `tool_use` (les blocs texte sont déjà affichés par le stream) — contrairement à `dispatch_tools()` de [[core-py]] qui faisait le tri en marchant.
- **Ligne 204** : `asyncio.gather(*[...])` — la liste en compréhension crée N coroutines, le `*` les déballe en arguments. Toutes démarrent « en même temps » (concurrence coopérative ; le vrai parallélisme vient des sous-processus de `async_bash` et des threads des wrappers `async_read`/`async_write`). `gather` retourne les résultats **dans l'ordre des arguments**, pas dans l'ordre d'achèvement.
- **Lignes 207–211** : double sécurité d'appariement — `dict(execution_pairs)` indexe par `tool_use_id`, puis la compréhension reconstruit `turn_results` en itérant sur `tool_blocks` (l'ordre du modèle). Même si `gather` garantissait déjà l'ordre, ce réassemblage par id rend le code robuste à un futur passage à `as_completed`.
- **Ligne 214** : un seul message `user` contenant tous les `tool_result` — exactement le format exigé par l'API (chaque `tool_use` du tour assistant doit trouver son `tool_result` dans le message suivant).

Le reste de la boucle (lignes 191–200) — enregistrement des stats de cache, archivage du message assistant, sortie sur `stop_reason != "tool_use"` — est la mécanique standard, annotée en détail dans [[s20-cache-optimization]].

### `main()` — lignes 219–258

REPL asynchrone : l'`input()` bloquant passe lui aussi par `run_in_executor` (lignes 236–238), `q`/`exit`/`quit` ou une ligne vide sortent (ligne 244), chaque requête est ajoutée à `history` puis confiée à `agent_loop_cached` (lignes 248–251). Le `try/finally` (231–258) garantit l'affichage de `stats.summary()` même sur Ctrl+C.

### Garde `if __name__ == "__main__"` — lignes 261–266

`asyncio.run(main())` enveloppé d'un `try/except KeyboardInterrupt: pass` — un Ctrl+C qui s'échappe de l'event loop meurt en silence au lieu d'imprimer une traceback.

## Ce qui vient de [[core-py]]

- **`client`** : le client Anthropic configuré (`.env`, `ANTHROPIC_BASE_URL` pour LiteLLM).
- **`MODEL`** : l'identifiant de modèle (`MODEL_ID` de l'environnement).
- **`EXTENDED_TOOLS`** : les 6 schémas d'outils (bash, read, write, grep, glob, revert) — copiés profondément en `CACHED_TOOLS`.
- **`ASYNC_DISPATCH`** : la table nom → handler **async** : `async_bash` est un vrai sous-processus asyncio (`create_subprocess_shell`), tandis qu'`async_read`/`async_write`/`async_grep`/`async_glob` sont les fonctions synchrones poussées dans le thread pool via `run_in_executor`. C'est cette table qui rend `gather` utile : avec des handlers synchrones, la « parallélisation » serait un tour de file d'attente.

À noter : la session n'importe **pas** `stream_loop`/`dispatch_tools` de core.py — ces helpers sont synchrones et séquentiels ; toute la boucle est réécrite ici en async.

## Pièges et détails d'implémentation

- **Le fichier est une copie de s20** : docstring, en-tête (`s20: prompt caching ...`, ligne 224) et prompt du REPL (`s20 >>`, ligne 237) parlent tous de s20. Le contenu prévu pour s18 (« `asyncio.gather` all tool calls », dit le README) existe dans le code dupliqué, mais une démo « pure parallélisme » sans la couche caching n'existe pas dans le dépôt.
- **Aucune partition de sûreté** : deux `write` sur le même fichier, ou un `read` et le `write` qui le modifie, partent en concurrence sans garde-fou. Le vrai CC partitionne par `isConcurrencySafe()` ; ici l'invariant « l'ordre du contenu est l'ordre d'exécution » de [[s02-tool-use]] est silencieusement abandonné.
- **`gather` ne voit jamais d'exception** : tout est attrapé dans `dispatch_one_tool`. Si on retirait ce `try/except`, la première exception annulerait le `await` et les `tool_result` ne seraient jamais renvoyés — l'API rejetterait le tour suivant.
- **Parallélisme réel vs coopératif** : seuls `async_bash` (sous-processus) et les wrappers thread-pool travaillent vraiment en même temps. Une fonction async qui calculerait en pur Python bloquerait les autres malgré `gather`.
- **`SNAPSHOTS` de core.py n'est pas verrouillé** : deux `write` parallèles mutent le dict global des snapshots depuis des threads du pool — bénin en pratique (GIL, clés distinctes), mais c'est le genre d'état partagé qu'un runtime parallèle sérieux protégerait.
- **Sorties entrelacées** : les `print` des coroutines concurrentes se mélangent ; c'est cosmétique mais déroutant la première fois — et c'est aussi la preuve visuelle que les outils tournent ensemble.

## Lancer la démo

```bash
cd inspiration/claude-code-from-scratch
python s18_parallel_tools.py
```

Prérequis : `.env` avec `ANTHROPIC_API_KEY` + `MODEL_ID` (ou le proxy LiteLLM, voir le README du repo). Aucun fichier de config supplémentaire.

À observer : demandez une tâche multi-fichiers (« lis ces trois fichiers et compare-les ») — le modèle émet plusieurs `tool_use` dans le même tour, et les lignes jaunes `[read] ...` apparaissent d'un bloc, leurs sorties entrelacées, au lieu de défiler une par une. Vous verrez aussi les lignes `[cache] MISS/HIT` (héritage de la duplication avec s20) et le prompt `s20 >>`.

## Liens

- Socle : [[core-py]]
- Session précédente : [[s17-session-management]]
- Session suivante : [[s19-interrupts]]
- Sessions liées : [[s20-cache-optimization]] (fichier jumeau — la moitié caching de ce code), [[s02-tool-use]] (le dispatch séquentiel que cette session parallélise), [[s08-background-tasks]] (l'autre voie vers la concurrence : threads de fond), [[s13-streaming]] (le streaming que la boucle déporte ici dans un thread)
