---
title: "main.py · Le REPL unifié"
phase: "Intégration"
fichier: "src_scratch/main.py"
lignes: 181
tags: [repl, cli, assemblage, commandes, asyncio]
---

# main.py · Le REPL unifié

> **En une phrase** : LE point d'entrée du harness — un REPL où les 23 sessions du repo source sont actives en même temps, orchestrées par un seul `asyncio.run` pour toute la session.

## Rôle dans le harness

Le repo source impose de choisir sa démo : `python s09_...py` pour les équipiers, `s17` pour les sessions, `s21` pour MCP — jamais tout à la fois. `main.py` est la preuve que la dédup fonctionne : il n'implémente (presque) rien lui-même, il **assemble**. Le prompt système agrège mémoire et skills ([[context-py]]), l'historique part dans la boucle unique de [[loop-py]], la compaction et l'auto-save tournent après chaque tour, et chaque sous-système se pilote par une commande `:`.

Le choix architectural central est dans la docstring (lignes 3–7) : **un seul `asyncio.run` pour toute la session** (pattern s18). Le runtime MCP, la boucle d'agent et les commandes partagent la même event loop — indispensable pour [[mcp-runtime-py]], dont les transports doivent se fermer dans la tâche qui les a ouverts. Seules les saisies utilisateur partent dans un thread (`asyncio.to_thread(input, ...)`), pour que la boucle reste réactive ; les équipiers, workers et worktrees tournent dans leurs propres threads via la façade sync `loop.agent_loop`.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–10 | Docstring | Architecture asyncio + ligne d'usage |
| 11–22 | Imports | Les 9 autres modules du harness — main est le seul à tout voir |
| 24–35 | Constante | `HELP` — l'aide des commandes `:` |
| 38–47 | Prompt | `build_system()` |
| 50–57 | Helper | `_repair()` |
| 60–112 | Commandes | `handle_command()` — le dispatcher des `:` |
| 115–159 | Boucle | `repl()` — saisie, tour d'agent, compaction, auto-save |
| 162–177 | CLI | `main()` — argparse + `asyncio.run` |
| 180–181 | Entrée | `if __name__ == "__main__"` |

## Constantes et configuration

- **`HELP` (lignes 24–35)** : le texte de `:help`, qui sert aussi de spécification compacte du REPL — chaque ligne y correspond à une branche de `handle_command`.

## Les fonctions, une à une

### `build_system()` — lignes 38–47

Assemble le prompt système en quatre couches, jointes par des doubles sauts de ligne :

```python
    parts = [DEFAULT_SYSTEM]
    memory = context.load_memory()
    if memory:
        parts.append("## Memory from previous sessions\n" + memory[-4000:])
    parts.append("## Available skills (use the load_skill tool before specialized tasks)\n"
                 + context.skills_index())
    parts.append("For multi-step work, write a plan with todo_write first and keep it updated.")
```

1. `DEFAULT_SYSTEM` de [[core-py]] (« coding agent at <cwd>… »), 2. la mémoire persistante de [[context-py]] **tronquée aux 4 000 derniers caractères** (la fin du fichier = le plus récent, le prompt ne gonfle pas indéfiniment), 3. l'index des skills avec l'instruction d'utiliser `load_skill`, 4. le rappel todo de s03. Le prompt est construit une fois au boot — une mémoire enrichie en cours de session ne sera visible qu'au prochain lancement.

### `_repair(messages)` — lignes 50–57

Le filet de sécurité après une interruption ou une erreur en plein tour : si le dernier message est un tour assistant contenant des `tool_use` **sans** les `tool_result` correspondants, l'API refuserait tout l'historique au tour suivant. `_repair` retire ce message orphelin. Le test couvre les deux formes possibles d'un bloc — objet SDK (`getattr(b, "type", None)`) ou dict pur issu d'une session rechargée (`b.get("type")`), lignes 54–55.

> Note : la concaténation des blocs texte d'une réponse (l'ancien helper local `_text_of`) a été mutualisée — `repl` importe désormais `text_of` de [[core-py]] (ligne 20) pour le payload de l'événement `assistant_message`.

### `handle_command(cmd, state, args)` — lignes 60–112

Le dispatcher des commandes `:`. `state` est le dict partagé `{messages, sid, team}` ; `cmd` est découpé par `partition(" ")` en verbe + reste. Toute commande inconnue ou incomplète tombe sur le message jaune final (ligne 112) avec rappel de `:help`.

| Commande | Lignes | Effet | Module sollicité |
|---|---|---|---|
| `:help` | 64–65 | affiche `HELP` | — |
| `:sessions` | 66–67 | liste les sessions sauvegardées | [[sessions-py]] |
| `:resume <id>` | 68–72 | recharge l'historique et le sid | [[sessions-py]] |
| `:fork <id>` | 68–72 | duplique puis recharge le fork | [[sessions-py]] |
| `:title <texte>` | 73–75 | (re)nomme la session courante | [[sessions-py]] |
| `:save` | 76–78 | sauvegarde manuelle | [[sessions-py]] |
| `:todos` | 79–80 | plan courant (todo_read) | [[tasks-py]] |
| `:tasks` | 81–82 | graphe de tâches persistant | [[tasks-py]] |
| `:requeue` | 83–84 | repasse les tâches failed en pending | [[tasks-py]] |
| `:team on\|off\|status` | 85–93 | équipiers persistants (explorer, writer) | [[agents-py]] + [[mailbox-py]] |
| `:workers <n>` | 94–97 | n workers autonomes sur le board (défaut 2) | [[agents-py]] |
| `:wt <t1> \| <t2> ...` | 98–102 | une tâche par worktree git isolé | [[worktree-py]] |
| `:compact` | 103–104 | compaction forcée du contexte | [[context-py]] |
| `:cache` | 105–106 | stats du prompt caching | [[loop-py]] |
| `:mcp` | 107–110 | démarrage paresseux + état des serveurs | [[mcp-runtime-py]] |
| `:quit` / `:q` / `:exit` | (dans `repl`, ligne 132) | quitter | — |

Trois détails notables :

- **`:resume` et `:fork` partagent une branche** (lignes 68–72) : fork = `fork_session(rest)` puis chargement du nouvel id ; resume = chargement direct. Dans les deux cas `state["messages"]` et `state["sid"]` sont remplacés d'un coup.
- **`:team on`** (lignes 86–88) construit la `Team` avec la mailbox du backend choisi en CLI : `state["team"].start(get_mailbox(args.backend))`. Tout autre argument (`status`, vide…) affiche `status()` ou un rappel.
- **`:wt`** (lignes 98–102) découpe sur `|`, puis `await asyncio.to_thread(worktree.run_parallel_tasks, jobs)` — les threads et leurs `join` bloquants ne doivent pas geler l'event loop.

### `repl(args)` — lignes 115–159

La boucle de vie complète. Au boot : `INTERRUPTS.install()` (le handler SIGINT de [[loop-py]]), `emit("session_start")`, démarrage MCP si `--mcp`, construction du prompt système. Puis le tour type :

```python
            user = raw.lstrip("﻿").strip()  # BOM d'un pipe PowerShell éventuel
            if not user:  # FIX(mekicode) s17 : l'entrée vide partait à l'API (erreur content:"")
                continue
```

```python
            try:
                final = await agent_loop_async(state["messages"], system=system,
                                               parallel=not args.seq, cache=not args.no_cache)
                emit("assistant_message", {"text": text_of(final)})
            except KeyboardInterrupt:
                print(paint("\n[interrompu] tour abandonné — l'historique reste cohérent", "red"))
                _repair(state["messages"])
            except Exception as e:
                print(paint(f"\n[erreur] {e}", "red"))
                _repair(state["messages"])
            state["messages"][:] = context.maybe_compact(state["messages"])
            state["sid"] = sessions.save_session(state["messages"], state["sid"])  # auto-save s17
```

- **Saisie** (ligne 126) : `await asyncio.to_thread(input, ...)` — l'`input` bloquant tourne dans un thread ; `EOFError`/`KeyboardInterrupt` sur la saisie = sortie propre de la boucle.
- **Tour d'agent** (lignes 139–148) : `agent_loop_async` de [[loop-py]] avec `parallel` et `cache` pilotés par les flags ; `text_of` de [[core-py]] extrait le texte de la réponse pour l'événement `assistant_message`. Un double Ctrl+C (le `KeyboardInterrupt` de `Interrupts`) ou une exception quelconque abandonne le tour mais **répare l'historique** (`_repair`) — la conversation continue.
- **Après chaque tour** (lignes 149–150) : `maybe_compact` (la coupe propre de [[context-py]]) puis auto-save — l'affectation par tranche `state["messages"][:] = ...` mute la liste en place, toutes les références restent valides.
- **`finally`** (lignes 151–159) : arrêt de l'équipe, `await mcp_runtime.stop_mcp()` (même tâche asyncio que le démarrage — la contrainte anyio de [[mcp-runtime-py]]), `emit("session_end")`, résumé du cache si utilisé, et le rappel `:resume <sid>` pour la prochaine fois.

Les événements s16 émis ici — `session_start`, `user_message`, `assistant_message`, `session_end` — complètent les `pre_tool`/`post_tool` émis par [[loop-py]] : le bus de [[core-py]] couvre tout le cycle.

### `main()` — lignes 162–177

L'analyse CLI et le lancement :

| Flag | Effet | Défaut |
|---|---|---|
| `--seq` | dispatch d'outils séquentiel sync au lieu du gather parallèle | parallèle |
| `--no-cache` | désactive le prompt caching (et son résumé de sortie) | cache actif |
| `--mcp` | démarre les serveurs MCP du config.yaml au boot | démarrage paresseux via `:mcp` |
| `--backend auto\|jsonl\|queue\|redis` | backend des mailboxes d'équipe | `auto` |

Une incompatibilité est arbitrée à la main (lignes 170–173) :

```python
    if args.mcp and args.seq:
        # Les outils MCP sont async-only (liés à l'event loop) : le mode --seq les casserait.
        print(paint("[main] --mcp force le dispatch parallèle (outils MCP async)", "yellow"))
        args.seq = False
```

Puis `asyncio.run(repl(args))` — l'unique entrée dans le monde async — avec un dernier `except KeyboardInterrupt` qui transforme un Ctrl+C de sortie en `bye` discret.

## Bugs de la source corrigés ici

- **Entrée vide au REPL (lignes 129–131)** — dans s17, une ligne vide (ou un simple Entrée) devenait un message `{"role": "user", "content": ""}` envoyé à l'API, qui le refuse (erreur sur `content` vide). Correction : `if not user: continue` après strip — et au passage `lstrip("﻿")` avale le BOM qu'un pipe PowerShell peut préfixer à la première ligne.

## Ce qu'il branche

`main.py` est le seul module à importer tous les autres (lignes 11–22). La checklist de non-régression — chaque feature des 23 sessions du repo source et le module qui la porte :

| Session source | Feature | Où dans src_scratch |
|---|---|---|
| s01 | boucle perception-action | [[loop-py]] `agent_loop` |
| s02 | dispatch d'outils | [[tools-py]] `DISPATCH` / `register_tool` |
| s03 | TodoWrite | [[tasks-py]] (`todo_*`) |
| s04 | subagent | [[agents-py]] `spawn_subagent` |
| s05 | skills à la demande | [[context-py]] (`skills_index` / `load_skill`) |
| s06 | compaction + mémoire | [[context-py]] `maybe_compact` |
| s07 | graphe de tâches | [[tasks-py]] (`task_*`) |
| s08 | bash en arrière-plan + notifications | [[tools-py]] `run_bash_background` + [[loop-py]] (drain) |
| s09 | équipiers + mailboxes | [[agents-py]] `Team` + [[mailbox-py]] `JsonlMailbox` |
| s10 | protocole FSM | [[agents-py]] `Team` (boucle équipier) |
| s11 | workers autonomes | [[agents-py]] `run_autonomous_agent` + [[tasks-py]] `claim_next_task` |
| s12/s23 | worktrees (cycle complet) | [[worktree-py]] |
| s13 | streaming | [[loop-py]] `stream_turn` |
| s14 | outils étendus + revert | [[tools-py]] (`SNAPSHOTS`, revert sync+async) |
| s15 | permissions YAML | [[core-py]] `check_permission` + [[loop-py]] (gate) |
| s16 | event bus + hooks veto | [[core-py]] `on`/`emit` + [[loop-py]] (`pre/post_tool`) + main (`session_*`) |
| s17 | sessions resume/fork | [[sessions-py]] + main (commandes) |
| s18 | outils en parallèle | [[loop-py]] `dispatch_tools_async` (gather) |
| s19 | interruptions Ctrl+C | [[loop-py]] `Interrupts` |
| s20 | prompt caching + stats | [[loop-py]] `stream_turn` + `CacheStats` |
| s21 | runtime MCP | [[mcp-runtime-py]] |
| s22 | mailbox Redis/Queue | [[mailbox-py]] `RedisMailbox` / `QueueMailbox` |

Personne n'importe `main.py` : c'est la feuille terminale du graphe, exécutable uniquement (`python main.py`).

## Pièges et détails d'implémentation

- **Un seul `asyncio.run` pour toute la session** : démarrer/arrêter MCP dans des `asyncio.run` séparés casserait les cancel scopes anyio des transports. Toute évolution du REPL doit préserver cette invariante.
- **`state["messages"][:] = ...`** (lignes 104 et 149) : affectation par tranche, pas réaffectation — la compaction remplace le *contenu* de la liste que d'autres closures pourraient référencer.
- **`_repair` est le garant de la cohérence** : sans lui, un Ctrl+C en plein dispatch laisserait un `tool_use` orphelin et l'API rejetterait tous les tours suivants. Si on ajoute des chemins d'erreur, penser à le rappeler.
- **Le prompt système est figé au boot** : mémoire et index des skills sont lus une fois dans `build_system()` ; une skill ajoutée en cours de session n'apparaîtra pas dans l'index avant relance (mais `load_skill` peut toujours la charger par son nom).
- **`:title` avant tout message crée une session vide** : la branche passe par `save_session(..., title=rest)`, qui crée le fichier si besoin — comportement voulu (réserver un titre), mais la session listera 0 tours.

## Liens

- Modules liés : [[loop-py]] (la boucle qu'il pilote), [[core-py]] (`DEFAULT_SYSTEM`, `emit`, `paint`, `text_of` — import ligne 20), [[context-py]], [[sessions-py]], [[tasks-py]], [[agents-py]], [[mailbox-py]], [[worktree-py]], [[mcp-runtime-py]], [[tools-py]] (indirect : le registre que la boucle consomme)
