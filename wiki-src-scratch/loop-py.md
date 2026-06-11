---
title: "loop.py · La boucle unique"
phase: "Fondations"
fichier: "src_scratch/loop.py"
lignes: 247
tags: [agent-loop, streaming, cache, interrupts, parallel, hooks, permissions]
---

# loop.py · La boucle unique

> **En une phrase** : LA boucle perception-action du harness — un seul moteur qui fusionne sept sessions de la source : streaming (s13), gardes permissions (s15) et hooks (s16), exécution parallèle (s18), interruptions Ctrl+C (s19), prompt caching et stats (s20), au-dessus de la boucle de base (s01).

## Rôle dans le harness

Dans la source, chaque session réécrivait *sa* boucle : celle de s13 streamait mais ne parallélisait pas, celle de s18 parallélisait sans cache, celle de s20 cachait sans interruptions… Sept variantes du même `while True`, aucune complète. Ici, **une seule boucle a tout** : `agent_loop_async` est le moteur unique, et chaque feature se débranche par paramètre (`parallel=False`, `cache=False`, `permissions=False`, `hooks=False` côté dispatch) au lieu d'exister en copie séparée.

Contrainte technique structurante, posée dès la docstring : le SDK `anthropic` utilisé est **synchrone**. Chaque appel streamé est donc déporté dans un thread via `asyncio.to_thread` (le pattern réel de s18/s20) — l'event loop reste libre pendant la génération, ce qui est la condition des interruptions s19 et du `gather` de s18.

La façade `agent_loop` (sync) existe pour les threads : équipiers et workers de [[agents-py]], tâches en worktree de [[worktree-py]]. Le REPL de [[main-py]], lui, appelle directement `agent_loop_async` sous un unique `asyncio.run` de session.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–7 | Docstring | Les sept sessions fusionnées + le choix to_thread |
| 8–15 | Imports | stdlib + [[core-py]] (client, gardes) + [[tools-py]] (palette) |
| 18–48 | Cache (s20) | `CacheStats` + instance globale `CACHE` |
| 51–90 | Interruptions (s19) | `Interrupts` + instance globale `INTERRUPTS` |
| 93–117 | Gardes communes | `_precheck` (hook + permission), `_finish` (post_tool + tool_result) |
| 120–166 | Dispatch | `dispatch_tools_async` (gather), `dispatch_tools` (séquentiel) |
| 169–200 | Appel API | `stream_turn` — streaming + stratégie de cache s20 |
| 203–219 | Injection user | `_inject_user` (FIX s19) |
| 222–247 | La boucle | `agent_loop_async` + façade `agent_loop` |

## Constantes et configuration

- **`CACHE` (ligne 48)** : instance globale de `CacheStats`, alimentée par `stream_turn`, lue par la commande `:cache` de [[main-py]].
- **`INTERRUPTS` (ligne 90)** : instance globale d'`Interrupts` ; le handler SIGINT n'est posé que si on appelle `INTERRUPTS.install()` (fait par [[main-py]] au boot).

## Les fonctions, une à une

### `class CacheStats` — lignes 20–45

Comptabilité s20 : `calls`, `hits`, `written` (tokens écrits en cache, MISS), `read` (tokens relus, HIT).

```python
    def record(self, usage) -> None:
        """Cumule les compteurs et affiche le verdict du tour, comme s20."""
        self.calls += 1
        written = getattr(usage, "cache_creation_input_tokens", 0) or 0
        read = getattr(usage, "cache_read_input_tokens", 0) or 0
```

- **`getattr(..., 0) or 0` (lignes 32–33)** : double filet — l'attribut peut être absent (backend sans cache) ou valoir `None`. Les stats tolèrent tout backend.
- **`if written: … elif read:` (lignes 38–41)** : un tour qui écrit ET lit n'affiche que le MISS — reproduction délibérée du if/elif de s20 (le premier tour après extension du prompt écrit le nouveau segment tout en relisant l'ancien).
- **`summary()` (lignes 43–45)** : la ligne de bilan, avec l'économie estimée `≈ read × 0.9` (lecture cache facturée ~10 % du prix).

### `class Interrupts` — lignes 53–87

Ctrl+C coopératif, version portable : `signal.signal` parce que `asyncio.add_signal_handler` **n'existe pas sous Windows** (docstring, lignes 54–57).

```python
    def _handler(self, signum, frame):
        now = time.monotonic()
        if now - self._last < 2.0:
            raise KeyboardInterrupt  # double Ctrl+C rapproché = sortie
        self._last = now
        try:
            text = input(paint("\n[interrupt] instruction (vide = pause) > ", "red")).strip()
        except (EOFError, RuntimeError, KeyboardInterrupt):
            text = ""
        self._queue.put("[INTERRUPT] " + (text or ...))
```

- **Deux vitesses** : premier Ctrl+C → on demande une instruction et on la met en file pour le tour suivant ; deux Ctrl+C en moins de 2 s → `KeyboardInterrupt` normal (sortie). `time.monotonic` est insensible aux changements d'horloge.
- **`input()` dans le handler** : possible parce que la génération tourne dans un thread (`to_thread` de `stream_turn`) — le thread principal est libre de prendre la main. Le texte streamé peut continuer à s'afficher pendant la saisie (cosmétique, assumé).
- **Instruction vide → message par défaut** : « Stoppe ta séquence en cours, résume ton avancement et attends ses instructions » — l'interruption a toujours un contenu exploitable par le modèle.
- **`install()` (lignes 63–65)** : à appeler une fois, depuis le **thread principal** (contrainte de `signal.signal`). `drain()` (lignes 80–87) : vidage non bloquant, symétrique de `drain_notifications` de [[tools-py]].

### `_precheck(block, permissions, hooks)` — lignes 95–109

La garde commune aux deux dispatchs : affiche l'appel, applique le veto de hook puis la permission. Renvoie le contenu du tool_result **pré-fabriqué si bloqué**, `None` si l'exécution peut partir.

```python
    first = str(next(iter(block.input.values()), "")) if block.input else ""
    print(paint(f"[{block.name}] {first[:80]}", "yellow"))
    if hooks and not emit("pre_tool", {"tool": block.name, "input": block.input}):
        return "Blocked by hook"
    if permissions:
        # Jugement sur la PREMIÈRE valeur de l'input (sémantique s15) : c'est elle que
        # visent les motifs ancrés du config.yaml (^ls, ^rm…) — la repr du dict complet
        # commencerait par "{" et ne matcherait jamais.
        ok, reason = check_permission(block.name, first)
        if not ok:
            return reason if reason.startswith("Denied") else f"Denied: {reason}"
```

- **Ligne 98** : `first` = la **première valeur** du dict input (`next(iter(...), "")`, robuste au dict vide) — pour `bash` c'est la commande, pour `read`/`write` le chemin. Elle sert à la fois à l'affichage jaune (tronquée à 80 caractères) et au jugement de permission.
- **Ordre : hook avant permission** — un veto de hook économise même le prompt `ask_user`.
- **Ligne 106** : `check_permission` reçoit `first`, la valeur nue — exactement la sémantique de s15. Les motifs ancrés du `config.yaml` (`^ls( |$)`, `^rm `, `^git (commit|…)`) matchent donc pleinement (voir Bugs : notre première intégration passait la repr du dict).
- **Ligne 108** : normalisation du refus — `check_permission` renvoie déjà `"Denied: …"` pour un deny, mais « user decision » (refus au prompt) est réhabillé en `"Denied: user decision"`. Le modèle reçoit toujours un message homogène.

### `_finish(block, output, hooks)` — lignes 112–117

Le miroir de sortie : extrait de 300 caractères à l'écran, `emit("post_tool", …)` (observation seule — le veto n'aurait plus de sens après exécution), et fabrication du dict `{"type": "tool_result", "tool_use_id": block.id, "content": str(output)}`.

### `dispatch_tools_async(content, dispatch=None, permissions=True, hooks=True)` — lignes 120–147

L'exécuteur parallèle de s18, en trois temps :

1. **Gardes séquentielles** (lignes 129–134) : `_precheck` sur chaque bloc, dans l'ordre — les prompts `ask_user` sont interactifs et ne se parallélisent pas. Les bloqués reçoivent leur tool_result d'office, les autres vont dans `runnable`.
2. **Exécution concurrente** (lignes 136–146) :

```python
    async def _run(b):
        handler = dispatch.get(b.name)
        if handler is None:
            return f"Error: Unknown tool '{b.name}'"
        try:
            return str(await handler(b.input))
        except Exception as e:
            return f"Error: {e}"

    for b, out in zip(runnable, await asyncio.gather(*(_run(b) for b in runnable))):
        outputs[b.id] = out
```

`gather` préserve l'ordre des awaitables, donc le `zip` réassocie chaque sortie à son bloc. Toute exception de handler devient un tool_result `"Error: …"` — **un outil qui crashe ne fait jamais tomber le lot** (même philosophie que s01 : l'erreur est une donnée pour le modèle).

3. **Finalisation ordonnée** (ligne 147) : `_finish` dans l'ordre **original** des blocs (`for b in blocks`), pas dans l'ordre d'achèvement — l'affichage et la liste de tool_results restent déterministes.

### `dispatch_tools(content, dispatch=None, permissions=True, hooks=True)` — lignes 150–166

L'équivalent séquentiel synchrone, mêmes gardes (`_precheck`/`_finish`), défaut `DISPATCH` au lieu d'`ASYNC_DISPATCH`. C'est la voie de `parallel=False` — utile pour déboguer (ordre d'exécution = ordre du contenu, comme s02) ou quand les outils ont des dépendances implicites entre eux.

### `stream_turn(messages, tools, system, cache=True, extra_kwargs=None)` — lignes 171–200

UN appel API streamé ; renvoie le `Message` final. Deux responsabilités fusionnées : le streaming de s13 et le cache de s20.

```python
    if cache:
        if isinstance(system, str):
            system = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        if tools:
            tools = copy.deepcopy(tools)
            tools[-1]["cache_control"] = {"type": "ephemeral"}
```

- **Stratégie s20 reproduite exactement** : le system devient une liste de blocs avec `cache_control` ephemeral, et le **dernier outil** porte le marqueur — tout ce qui précède (la liste d'outils entière + le system) est mis en cache côté API.
- **`copy.deepcopy(tools)` (ligne 185)** : décisif. `tools` est par défaut LA liste partagée de [[tools-py]], maintenue en place par `register_tool` — y poser `cache_control` directement la muterait pour tout le monde (et le marqueur s'empilerait à chaque tour). On marque une copie, jamais l'objet partagé.

```python
    def _blocking_stream():
        with client.messages.stream(model=MODEL, system=system, messages=messages,
                                    tools=tools, max_tokens=8000, **extra_kwargs) as stream:
            for text in stream.text_stream:
                print(text, end="", flush=True)
            return stream.get_final_message()

    response = await asyncio.to_thread(_blocking_stream)
```

- Le `with client.messages.stream(...)` du SDK sync est enfermé dans une closure exécutée par `to_thread` : le texte s'affiche au fil de l'eau (`flush=True`) pendant que l'event loop reste disponible (interrupts, autres coroutines).
- `stream.get_final_message()` reconstitue le `Message` complet (blocs `tool_use` compris) — la boucle n'a pas à assembler les deltas elle-même.
- **Lignes 198–199** : `CACHE.record(response.usage)` seulement si `cache=True` — désactiver le cache désactive aussi la comptabilité.

### `_inject_user(messages, texts)` — lignes 205–219

Le porteur du FIX s19 (voir Bugs). Injecte des textes côté user **en bloc complet** :

```python
    blocks = [{"type": "text", "text": t} for t in texts]
    if messages and messages[-1]["role"] == "user":
        prev = messages[-1]["content"]
        if isinstance(prev, str):
            prev = [{"type": "text", "text": prev}]
        messages[-1]["content"] = list(prev) + blocks
    else:
        messages.append({"role": "user", "content": blocks})
```

Si le dernier message est déjà `user` (cas normal : la requête initiale ou les tool_results du tour précédent), les textes y sont **ajoutés comme blocs** — on préserve l'alternance stricte user/assistant exigée par l'API, et un message de tool_results n'est jamais séparé de son tour assistant `tool_use`. La normalisation `str → [{"type": "text", …}]` gère la requête initiale écrite en chaîne simple.

### `agent_loop_async(messages, tools=None, dispatch=None, system=None, parallel=True, cache=True)` — lignes 222–242

La boucle elle-même — douze lignes de corps, tout le reste du fichier est à son service :

```python
    while True:
        pending = [f"[notification] {n}" for n in drain_notifications()] + INTERRUPTS.drain()
        _inject_user(messages, pending)
        response = await stream_turn(messages, tools, system, cache=cache)
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            return response
        if parallel:
            results = await dispatch_tools_async(response.content, dispatch)
        else:
            results = dispatch_tools(response.content, dispatch)
        messages.append({"role": "user", "content": results})
```

- **Tête de tour (lignes 232–233)** : les notifications de fond (s08, préfixées `[notification]`) et les interruptions (s19, déjà préfixées `[INTERRUPT]`) sont drainées et injectées comme contenu user — le modèle les voit au prochain appel, dans le fil normal de la conversation.
- **Défauts (lignes 227–230)** : `tools if tools is not None else TOOLS` — le test `is not None` (et non la truthiness) permet de passer explicitement `[]` pour une boucle sans outils. `dispatch` par défaut suit `parallel` : `ASYNC_DISPATCH` ou `DISPATCH` de [[tools-py]].
- **`messages` est muté en place** : l'appelant garde l'historique complet (c'est ce que [[sessions-py]] sérialise et ce que la compaction de [[context-py]] retravaille).
- **Sortie** : `stop_reason != "tool_use"` — `end_turn`, `max_tokens`… tout ce qui n'est pas une demande d'outil rend la main.

### `agent_loop(messages, **kw)` — lignes 245–247

```python
def agent_loop(messages, **kw):
    """Façade synchrone : asyncio.run — utilisable depuis un thread (équipiers, workers)."""
    return asyncio.run(agent_loop_async(messages, **kw))
```

Chaque appel crée son propre event loop — c'est précisément ce qui la rend utilisable depuis les threads de [[agents-py]] et [[worktree-py]] (un `asyncio.run` par thread, aucun partage de loop).

## Bugs de la source corrigés ici

- **`_inject_user` (lignes 205–219)** — en s19, l'interruption était injectée comme **message user séparé**, qui pouvait s'intercaler entre le tour assistant contenant les `tool_use` et le message user contenant leurs `tool_result` : l'API rejette cet historique (chaque `tool_use` doit trouver ses résultats dans le message immédiatement suivant). Correction : si le dernier message est déjà user, les textes sont fusionnés dedans comme blocs supplémentaires — jamais de message « à cheval » sur un échange tool_use/tool_result, et l'alternance des rôles est préservée.
- **`_precheck` juge la première valeur de l'input (lignes 98 et 103–106)** — divergence introduite par **notre première intégration**, pas par la source : nous passions `str(block.input)` à `check_permission`, soit la repr du dict (`{'command': 'ls'}`), qui commence par `{` — les motifs ancrés du `config.yaml` (`^ls( |$)`, `^rm `, `^git (commit|…)`) ne matchaient donc jamais, neutralisant les tiers allow/ask. Détectée à la relecture (comparaison avec s15, qui passait `str(list(inp.values())[0])`), corrigée en repassant la **première valeur** de l'input — la commande ou le chemin nus — avec un commentaire explicatif dans le code.

## Qui l'utilise

- [[main-py]] — `CACHE`, `INTERRUPTS`, `agent_loop_async` : le REPL pose le handler SIGINT, lance la boucle async et affiche `CACHE.summary()` sur `:cache`.
- [[agents-py]] — `agent_loop` : subagents (s04), équipiers (s09/s10) et workers autonomes (s11) tournent chacun leur boucle dans leur thread.
- [[worktree-py]] — `agent_loop` : une boucle dédiée par tâche en worktree (s23).

## Pièges et détails d'implémentation

- **Les prompts `ask_user` sont séquentiels même en mode parallèle** : par construction (`_precheck` avant le `gather`). Deux confirmations s'enchaînent à l'écran, elles ne s'entremêlent pas.
- **`CACHE` est global et sans verrou** : les boucles concurrentes (équipiers, workers, worktrees) cumulent leurs `usage` dans la même instance depuis plusieurs threads. Pour des statistiques c'est bénin, mais ne pas s'en servir comme métrique exacte sous forte concurrence.
- **`INTERRUPTS.install()` n'est jamais appelé par loop.py** : sans appel explicite depuis le thread principal ([[main-py]] le fait), Ctrl+C garde son comportement Python standard — `KeyboardInterrupt` immédiat au premier appui.
- **`deepcopy(tools)` à chaque tour** : coût modeste mais réel sur de grosses palettes (outils MCP nombreux) ; c'est le prix de l'immutabilité de la liste partagée — ne pas « optimiser » en marquant l'original.

## Liens

- Modules liés : [[core-py]] (client, `check_permission`, `emit`, `paint`), [[tools-py]] (palette par défaut, notifications de fond), [[agents-py]] / [[worktree-py]] (consommateurs de la façade sync), [[main-py]] (consommateur async + Ctrl+C), [[sessions-py]] (sérialise l'historique muté), [[context-py]] (compacte ce même historique)
