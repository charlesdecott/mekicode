---
title: "s19 · Interruptions temps réel"
session: 19
phase: "Runtime async"
fichier: "inspiration/claude-code-from-scratch/s19_interrupts.py"
lignes: 239
tags: [interrupt, asyncio-queue, ctrl-c, steering, soft-interrupt]
prev: "s18-parallel-tools"
next: "s20-cache-optimization"
---

# s19 · Interruptions temps réel

> **En une phrase** : un Ctrl+C pendant que l'agent travaille ne tue plus le process — il dépose un message `[INTERRUPT]` dans une `asyncio.Queue` que la boucle consulte à deux points de contrôle, et le modèle, instruit par le prompt système, s'arrête proprement et résume où il en est.

## Rôle dans le harness

C'est le problème de l'**agent emballé** (« Runaway Agent », dit la docstring) : dans toutes les sessions précédentes, une fois la tâche lancée, l'utilisateur n'a que deux options — attendre la fin, ou tuer le process et perdre tout le contexte. Or piloter un agent, c'est précisément pouvoir dire « stop, pas comme ça » *au milieu* d'une séquence de dix appels d'outils, sans jeter la session.

La solution est une **interruption douce** (« soft interrupt ») : le signal n'arrête rien par la force. Le Ctrl+C est traduit en message texte, poussé dans une file hors-bande (`interrupt_queue`), et la boucle de l'agent — qui tourne comme une `asyncio.Task` séparée du REPL — vérifie cette file à deux moments charnières : avant d'appeler le modèle, et entre la réponse du modèle et l'exécution des outils. Si un message s'y trouve, il est injecté dans l'historique comme un tour `user` ordinaire ; c'est le **modèle** qui décide de s'arrêter, conformément au principe du README : le harness ne branche jamais sur la logique, il transporte l'information.

L'analogue dans le vrai Claude Code (colonne « Claude Code Analog ») est la **file de pilotage `h2A`** : la même file asynchrone qui alimente les tâches de fond de [[s08-background-tasks]] sert aussi à injecter les messages que l'utilisateur tape pendant que l'agent travaille — Esc pour interrompre, ou simplement un message glissé en plein vol. La phase « Runtime async » du README parle d'*« interrupt injection gives real-time steering »*. Pas d'équivalent dans learn-claude-code, qui ne couvre pas le pilotage en cours de tour.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–30 | Shebang & docstring | Le problème, les 2 points de contrôle, le flux opérationnel |
| 33–35 | Imports stdlib | `asyncio`, `sys`, typing |
| 39–44 | Imports core | `client`, `MODEL`, `EXTENDED_TOOLS`, `ASYNC_DISPATCH` |
| 49–55 | Configuration | `SYSTEM` : le contrat de comportement sur `[INTERRUPT]` |
| 59 | État global | `interrupt_queue` : le canal hors-bande |
| 64–94 | Exécution | `dispatch_one_tool()` : une coroutine par outil (cf. [[s18-parallel-tools]]) |
| 99–161 | **Le cœur** | `agent_loop_interruptible()` : la boucle à 2 points de contrôle |
| 166–231 | Point d'entrée | `main()` : le REPL qui distingue 3 sens du Ctrl+C |
| 234–239 | Garde | `asyncio.run(main())` |

## Constantes et configuration

- **`SYSTEM` (lignes 49–55)** : le prompt système est la moitié du mécanisme. Il définit un protocole : *« If you receive a message starting with [INTERRUPT], you must stop your current sequence of actions immediately. Summarize the work you have completed so far, what remains to be done, and then wait... »*. Le harness ne force rien — il compte sur ce contrat. Sans cette phrase, le message `[INTERRUPT]` serait une requête utilisateur comme une autre.
- **`interrupt_queue` (ligne 59)** : `asyncio.Queue()` globale, le canal hors-bande entre le REPL (producteur, dans le `except KeyboardInterrupt`) et la boucle d'agent (consommatrice). Le commentaire du code la dit « thread-safe » — c'est inexact (`asyncio.Queue` ne l'est pas), mais sans conséquence ici : producteur et consommateur vivent sur le même event loop.

## Les fonctions, une à une

### `dispatch_one_tool(block)` — lignes 64–94

Copie conforme de la coroutine de [[s18-parallel-tools]] (le code n'étant pas cumulatif, chaque session embarque la sienne) : récupération du handler dans `ASYNC_DISPATCH` (ligne 78), log jaune, `await handler(tool_input)` sous `try/except` (lignes 84–89) pour qu'aucune exception n'atteigne le `gather`, retour du couple `(block.id, output)` (ligne 94). Voir la page s18 pour l'explication ligne à ligne ; rien ne change ici.

### `agent_loop_interruptible(messages)` — lignes 99–161

La boucle standard, augmentée de deux points de contrôle. **Point 1, avant l'appel au modèle** (lignes 108–113) :

```python
        # 1. PRE-MODEL CHECK: Check if an interrupt arrived while we were idling
        if not interrupt_queue.empty():
            # Retrieve the interrupt message
            interrupt_msg = await interrupt_queue.get()
            print(f"\n\033[31m[INTERRUPT] {interrupt_msg}\033[0m")
            # Inject the interrupt into the conversation history
            messages.append({"role": "user", "content": interrupt_msg})
```

- **Ligne 108** : `empty()` puis `get()` — un poll non bloquant. On ne fait jamais `await queue.get()` à vide, ce qui suspendrait la boucle en attendant un interrupt qui n'arrivera peut-être jamais.
- **Ligne 113** : l'interrupt devient un message `user` **ordinaire** dans l'historique. Pas de canal magique : le modèle le lira au prochain appel API, comme n'importe quel tour, et le prompt `SYSTEM` lui dicte la réaction.

Suit l'appel API (lignes 116–129) : la closure `_blocking_stream_call` streame la réponse du SDK synchrone, exécutée via `run_in_executor` — **c'est ce déport en thread qui rend l'interruption possible** : pendant que le modèle génère, l'event loop est libre et le `await active_agent_task` de `main()` peut recevoir le `KeyboardInterrupt`.

**Point 2, entre la réponse et les outils** (lignes 140–145) :

```python
        # 2. PRE-TOOL CHECK: Check if an interrupt arrived while the model was thinking
        if not interrupt_queue.empty():
            interrupt_msg = await interrupt_queue.get()
            print(f"\n\033[31m[INTERRUPT] Stopping before tool execution: {interrupt_msg}\033[0m")
            # Inject interrupt. The loop continues to next iteration where model sees this.
            messages.append({"role": "user", "content": interrupt_msg})
            continue
```

- C'est le point le plus précieux : le modèle vient de demander des outils (`stop_reason == "tool_use"`, testé ligne 136), mais **rien n'a encore été exécuté**. L'interrupt empêche des actions indésirables, pas seulement du temps perdu.
- **Ligne 145** : `continue` saute l'exécution des outils et reboucle ; au tour suivant, le modèle voit l'interrupt et (par contrat `SYSTEM`) résume au lieu de continuer.
- **Subtilité non gérée** : le dernier message assistant contient des blocs `tool_use`, et le message `user` injecté est du texte **sans les `tool_result` correspondants**. L'API Anthropic exige qu'à chaque `tool_use` réponde un `tool_result` dans le message suivant — ce chemin produit donc un historique invalide (erreur 400 probable au prochain appel). Le vrai Claude Code injecte des `tool_result` synthétiques « interrupted by user » pour garder l'historique bien formé ; une version robuste de cette démo ferait pareil.

Enfin l'exécution parallèle (lignes 148–161) : filtrage des `tool_blocks`, `asyncio.gather` sur `dispatch_one_tool`, réassemblage `id → résultat` et append du message `user` de `tool_result` — le mécanisme de [[s18-parallel-tools]], inchangé.

### `main()` — lignes 166–231

Le REPL distingue **trois significations** du même Ctrl+C, uniquement d'après l'`await` actif au moment où le `KeyboardInterrupt` émerge.

```python
        try:
            query = await loop.run_in_executor(None, lambda: input("\033[36ms19 >> \033[0m").strip())
        except KeyboardInterrupt:
            # Case 1: Ctrl+C pressed at the command prompt -> Exit program
            print("\n  User requested exit. Goodbye.")
            if active_agent_task and not active_agent_task.done():
                active_agent_task.cancel()
            break
```

- **Cas 1 (lignes 184–190)** : Ctrl+C au prompt = sortie du programme (avec annulation défensive d'une éventuelle tâche d'agent résiduelle). **Cas 2 (lignes 191–193)** : Ctrl+D (`EOFError`) = sortie aussi.
- **Ligne 203** : `asyncio.create_task(agent_loop_interruptible(history))` — la boucle d'agent devient une tâche **détachée** du REPL. C'est l'architecture clé de la session : si on faisait `await agent_loop_interruptible(history)` directement, il n'y aurait aucun « ailleurs » où attraper le Ctrl+C.

**Cas 3, le Ctrl+C pendant le travail** (lignes 211–228) :

```python
        except KeyboardInterrupt:
            # Case 3: Ctrl+C pressed while the agent is active -> Inject Interrupt
            interrupt_instruction = (
                "[INTERRUPT] The user has requested an immediate pause by pressing Ctrl+C. "
                "Stop your current sequence, summarize your progress, and wait for instructions."
            )
            await interrupt_queue.put(interrupt_instruction)
            print("\033[31m\n  Interrupt detected! Queuing stop command — agent will respond after current tool.\033[0m")
            try:
                # Give the agent 30 seconds to finish its current tool and summarize
                await asyncio.wait_for(active_agent_task, timeout=30)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                print("  System: Agent failed to summarize within timeout. Forcing task cancellation.")
                if not active_agent_task.done():
                    active_agent_task.cancel()
```

- **Lignes 213–218** : le signal est converti en **instruction en langage naturel** préfixée `[INTERRUPT]` (le préfixe que `SYSTEM` reconnaît), puis déposé dans la file. Le harness n'arrête rien lui-même.
- **Lignes 222–228** : la dégradation en escalier — d'abord la voie douce (30 s pour finir l'outil en cours et résumer), puis la voie dure (`task.cancel()`) si l'agent ne coopère pas. Soft d'abord, hard en dernier recours : le pattern exact d'un arrêt gracieux de service.
- **Ligne 208** : le `except asyncio.CancelledError: pass` autour de l'`await` initial absorbe le cas où la tâche a été annulée par ailleurs.

### Garde `if __name__ == "__main__"` — lignes 234–239

`asyncio.run(main())` sous `try/except KeyboardInterrupt: pass` — le filet final pour un Ctrl+C qui surgirait hors de tout `await` géré (pendant le démarrage ou l'arrêt de l'event loop).

## Ce qui vient de [[core-py]]

- **`client`** : le client Anthropic (utilisé dans `_blocking_stream_call`, via thread).
- **`MODEL`** : l'identifiant du modèle.
- **`EXTENDED_TOOLS`** : les 6 schémas d'outils passés tels quels à l'API (pas de variante cachée ici, contrairement à [[s20-cache-optimization]]).
- **`ASYNC_DISPATCH`** : les handlers async (`async_bash` en sous-processus, les autres en thread pool) consommés par `dispatch_one_tool`.

Ni `stream_loop` ni `dispatch_tools` : la boucle synchrone de core.py n'offre aucun point d'insertion pour les contrôles de file — il fallait la réécrire en async.

## Pièges et détails d'implémentation

- **L'interruption n'est jamais préemptive** : un `bash` de 100 secondes court jusqu'au bout — la file n'est consultée qu'aux deux points de contrôle. Le « temps réel » du titre est un temps réel *de tour*, pas d'instruction ; seule l'escalade `wait_for(..., 30)` + `cancel()` coupe vraiment.
- **Le chemin pré-outils casse le contrat `tool_use`/`tool_result`** : injecter du texte à la place des `tool_result` attendus rend l'historique invalide pour l'API (voir l'analyse des lignes 140–145). C'est LE détail que le vrai CC traite avec des résultats synthétiques.
- **L'arrêt repose sur l'obéissance du modèle** : `[INTERRUPT]` n'est qu'un message ; un modèle qui ignore le prompt `SYSTEM` continuerait sa séquence. Le filet est le timeout de 30 s, pas le message.
- **La distinction des trois Ctrl+C est positionnelle** : même signal, trois sens, selon l'`await` actif quand `KeyboardInterrupt` émerge dans le thread principal. Comportement qui dépend de la plateforme et de la version de Python (la livraison de SIGINT dans asyncio est notoirement délicate, surtout sous Windows).
- **`input()` reste bloqué dans son thread** : le REPL lit via `run_in_executor` ; après un Ctrl+C, le thread du pool peut rester suspendu sur `input()` jusqu'au prochain Entrée — source classique de sorties de process qui « traînent ».
- **Un seul interrupt à la fois est traité par point de contrôle** : `get()` ne vide pas la file ; deux Ctrl+C rapprochés laissent un second message qui ne sera consommé qu'au point de contrôle suivant.

## Lancer la démo

```bash
cd inspiration/claude-code-from-scratch
python s19_interrupts.py
```

Prérequis : `.env` avec `ANTHROPIC_API_KEY` + `MODEL_ID` (ou proxy LiteLLM). Aucun fichier de config.

À observer : lancez une tâche longue (« explore tout le repo et résume chaque fichier »), puis Ctrl+C pendant que les outils défilent. Le message rouge `Interrupt detected! Queuing stop command...` apparaît, l'outil en cours se termine, puis le modèle imprime un résumé de l'avancement et rend la main au prompt `s19 >>`. Un Ctrl+C *au prompt* affiche `User requested exit. Goodbye.` et quitte — même touche, deux destins.

## Liens

- Socle : [[core-py]]
- Session précédente : [[s18-parallel-tools]]
- Session suivante : [[s20-cache-optimization]]
- Sessions liées : [[s08-background-tasks]] (l'autre usage de la file h2A : notifications de fond), [[s16-event-bus]] (autre canal hors-bande : les hooks observent, ici la file pilote), [[s13-streaming]] (le streaming que la boucle déporte en thread pour rester interruptible)
