---
title: "s20 · Agent complet"
session: 20
phase: "Intégration & synthèse"
fichier: "src/sessions/s20.py"
lignes: 96
tags: [synthese, cli, repl, orchestration, cron-autorun]
prev: "s19-mcp-plugin"
next: ""
---

# s20 · Agent complet

> **En une phrase** : la session finale n'ajoute aucun mécanisme — elle est le CLI à double entrée (saisie humaine + tours cron autonomes, sérialisés par `agent_lock` sur le même `history`) qui appelle `shared.agent_loop` avec les registres complets par défaut ; c'est le seul morceau de l'original que shared.py n'a volontairement pas absorbé.

## Rôle dans le harness

Le difficile n'est pas d'empiler des mécanismes, c'est de voir où chacun se branche autour de la boucle. Ce branchement vit déjà dans `shared.agent_loop` : injections (prompts cron tirés, notifications d'arrière-plan, rappel todo) → compaction (`prepare_context`) → system prompt vivant (mémoire + skills + MCP) → appel LLM sous `with_retry` → hooks `PreToolUse`/permission → handlers (natifs, MCP, ou détour arrière-plan) → `PostToolUse` → `tool_result` → tour suivant. Appelée avec `tools`/`handlers`/`system` à `None`, elle reconstitue exactement le comportement du capstone : pool builtin (27 outils) + MCP ré-assemblé à chaque tour, system prompt vivant.

Ce qui manque à la bibliothèque pour faire un agent *long-running*, c'est l'enveloppe : un REPL qui accepte la saisie humaine, un thread `cron_autorun_loop` qui lance des tours d'agent **tout seul** quand un job cron tire, le verrou qui sérialise ces deux entrées sur la même conversation, et le drainage de l'inbox du lead après chaque tour (les messages des teammates sont routés vers les états de protocole puis injectés en `[Inbox]`). C'est ce fichier — la reconstruction du bloc `__main__` original (lignes 2088–2123 de `s20_comprehensive/code.py`), le seul délta de la session.

## Ce que fait ce fichier

### inbox_label() — lignes 35–41
Le helper local recréé (il était défini inline dans le `__main__` original et n'existe pas dans shared) :

```python
    req_id = msg.get("metadata", {}).get("request_id", "")
    suffix = f" req:{req_id}" if req_id else ""
    return f"{msg.get('type', 'message')}{suffix}"
```

Étiquette chaque message d'inbox avec son type et son `request_id` éventuel : le lead lit `From bob [plan_approval_request req:req_000123]: ...` et le modèle peut appeler `review_plan` avec le bon identifiant au tour suivant.

### main() — lignes 44–91
Le CLI complet, en trois zones :

**Mise en place** (l. 48–58) : `shared.CLI_ACTIVE = True` arme `terminal_print` — les threads d'arrière-plan (teammates, bus, cron) redessinent la ligne readline en cours de saisie au lieu de la casser. Puis `history` et `context` sont créés **partagés** et le thread cron démarre :

```python
    history: list = []
    context = update_context({}, [])
    threading.Thread(target=cron_autorun_loop,
                     args=(history, context), daemon=True).start()
```

`cron_autorun_loop` surveille `cron_queue` et, quand un job tire, prend `agent_lock` et lance un tour d'agent complet sur le **même** `history` — c'est ce partage (et le fait qu'`agent_loop` mute la liste en place via `messages[:] =`) qui rend l'agent réellement long-running pendant que l'humain ne tape rien.

**Le tour humain** (l. 60–78) : lecture au prompt (`q`, `exit`, chaîne vide, EOF ou Ctrl-C quittent), hook `UserPromptSubmit`, puis le tour sous verrou :

```python
        trigger_hooks("UserPromptSubmit", query)
        turn_start = len(history)
        history.append({"role": "user", "content": query})
        with agent_lock:
            agent_loop(messages=history, context=context)
            context = update_context(context, history)
            print_turn_assistants(history, turn_start)
```

`agent_loop` est appelée sans `tools`/`handlers`/`system` : registres complets par défaut. `print_turn_assistants` rend les textes assistants produits depuis `turn_start` — le rendu est découplé de la boucle, compatible threads.

**Après le tour** (l. 80–91) : `consume_lead_inbox(route_protocol=True)` draine l'inbox du lead — les `*_response` mettent à jour `pending_requests` même si le modèle n'a jamais appelé `check_inbox` — puis tout est injecté dans `history` comme message `[Inbox]`, formaté par `inbox_label` : le modèle le verra au prochain tour, sans relance automatique.

## Ce qui vient de [[shared-py]]

Tout le harness — ce fichier n'orchestre que des appels :

- `agent_loop(messages=..., context=...)` — LA boucle de synthèse, registres complets par défaut (27 outils natifs + MCP, system prompt vivant).
- `cron_autorun_loop(history, context)` — le thread des tours autonomes déclenchés par cron.
- `agent_lock` — le verrou qui sérialise tours humains et tours cron sur la même conversation.
- `update_context(context, messages)` — `MEMORY.md` + état vivant MCP/teammates, passé au system prompt.
- `print_turn_assistants(messages, turn_start)` — le rendu des textes assistants du tour.
- `trigger_hooks("UserPromptSubmit", query)` — le premier des 4 événements de hooks.
- `consume_lead_inbox(route_protocol=True)` — drainage + routage protocole de l'inbox lead.
- `CLI_ACTIVE` / `PROMPT` — les deux drapeaux console consommés par `terminal_print` et `input`. Seul `CLI_ACTIVE` reste accédé en qualifié (`import shared` + `shared.CLI_ACTIVE = True`) : `main()` **rebinde** ce nom, et l'affectation sur une copie from-importée ne toucherait pas le module ; tout le reste est from-importé explicitement.

## Différences avec l'original learn-claude-code

- Le délta est exactement inversé : l'original `s20_comprehensive/code.py` faisait 2124 lignes dont ~35 de `__main__` ; ici les ~2090 lignes de corps **sont** shared.py et le fichier ne reconstruit que le `__main__` (REPL + `inbox_label`), en 95 lignes commentées.
- `agent_loop` est appelée par mots-clés (`messages=history, context=context`) : la signature bibliothèque est devenue paramétrable (`user_input`, `tools`, `handlers`, `system` optionnels), là où l'original appelait `agent_loop(history, context)` positionnellement.
- Fidélité assumée, piège compris : comme dans l'original, le tour humain fait `context = update_context(...)` (rebind local) alors que `cron_autorun_loop` mute *sa* référence (`context.update(...)`) — après le premier tour humain, le thread cron continue donc avec le dict initial. Hérité tel quel, non corrigé.
- Les teammates spawnés depuis ce CLI bénéficient du FIX(mekicode) de shared (placeholders `[Deferred until plan approval]` pour les `tool_use` orphelins après `submit_plan`), absent de l'original.
- Bannière et commentaires francisés ; comportement d'entrée/sortie identique (`q`, `exit`, vide, EOF, Ctrl-C).

## Lancer la démo

```
python src/sessions/s20.py
```

C'est la seule démo de s16–s20 qui appelle réellement le modèle : il faut `MODEL_ID` (et une clé API valide) dans `.env`. On obtient le REPL `>>` ; chaque saisie traverse hooks, compaction, mémoire, skills et le pool complet d'outils. À essayer : `crée une tâche puis spawne un teammate alice pour la faire` (l'inbox `[Inbox]` apparaît après le tour), `connecte le serveur MCP docs puis cherche "agent loop"`, ou `planifie un rappel cron dans 2 minutes` puis ne rien taper — le thread `cron_autorun_loop` lancera le tour tout seul, et `terminal_print` redessinera la ligne de saisie.

## Liens

- Bibliothèque : [[shared-py]]
- Session précédente : [[s19-mcp-plugin]]
- Sessions liées : [[s16-team-protocols]] (l'inbox routée après chaque tour), [[s17-autonomous-agents]] (les teammates autonomes visibles depuis ce CLI), [[s14-cron-scheduler]] (les jobs qui alimentent `cron_autorun_loop`), [[s01-agent-loop]] (le cœur inchangé de la boucle)
