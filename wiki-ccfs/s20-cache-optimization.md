---
title: "s20 · Optimisation du cache"
session: 20
phase: "Runtime async"
fichier: "inspiration/claude-code-from-scratch/s20_cache_optimization.py"
lignes: 266
tags: [prompt-caching, cache-control, ephemeral, usage, tokens]
prev: "s19-interrupts"
next: "s21-mcp-runtime"
---

# s20 · Optimisation du cache

> **En une phrase** : en posant des marqueurs `cache_control: {"type": "ephemeral"}` sur le prompt système et sur le dernier outil, l'API Anthropic met en cache tout le préfixe stable de la requête — et une classe `CacheStats` rend visibles, tour par tour, les HIT (≈90 % d'économie) et les MISS.

## Rôle dans le harness

Un agent renvoie à chaque tour **tout** son contexte : prompt système, schémas des 6 outils, historique complet. Sur une session de 20 tours, le même préfixe de plusieurs milliers de tokens est retraité 20 fois — payé plein tarif, et reprocessé par le modèle (latence du premier token). La devise de la session : *« Never rebuild what you've already sent »*.

Le prompt caching d'Anthropic résout cela côté serveur : un marqueur `cache_control` dans la requête désigne un point de césure ; tout ce qui précède (dans l'ordre du prompt : outils, puis système, puis messages) est stocké en cache KV. À la requête suivante, si le préfixe est identique octet pour octet, le serveur le **lit** au lieu de le retraiter : facturation à ~10 % du tarif d'entrée et TTFT nettement plus court. Le cache est « ephemeral » : ~5 minutes de durée de vie, rafraîchies à chaque hit. La session ne change presque rien à la boucle — elle change la *forme* de ce qu'on envoie (système en liste de blocs, marqueur sur le dernier outil) et instrumente `response.usage` pour prouver l'économie.

Dans le vrai Claude Code (colonne « Claude Code Analog » : *92 % prefix reuse*), le caching est structurel : le gros system prompt, les définitions des 18 outils et le début de la conversation forment un préfixe stable réutilisé sur la quasi-totalité des appels — c'est l'une des raisons pour lesquelles CC est économiquement viable en sessions longues. Pas d'équivalent dans learn-claude-code, qui gère le coût du contexte par compression (son « compact ») plutôt que par cache serveur — les deux approches sont complémentaires, comme [[s06-context-compact]] et cette session.

**Note d'inventaire** : dans le dépôt publié, ce fichier est dupliqué tel quel sous le nom `s18_parallel_tools.py` (erreur d'empaquetage amont). La présente page couvre le versant caching ; le versant exécution parallèle du même code est analysé dans [[s18-parallel-tools]].

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–26 | Shebang & docstring | Concepts : blocs cache_control, caching des tools, ephemeral, usage |
| 28–33 | Imports stdlib | `asyncio`, `os`, `copy`, `sys`, typing |
| 35–42 | Imports core | `client`, `MODEL`, `EXTENDED_TOOLS`, `ASYNC_DISPATCH` |
| 44–67 | **Config cacheable** | `CACHED_SYSTEM` (48–60), `CACHED_TOOLS` (63–67) |
| 70–124 | **Instrumentation** | classe `CacheStats` (72–120) + instance `stats` (124) |
| 127–158 | Exécution | `dispatch_one_tool()` : une coroutine par outil (cf. [[s18-parallel-tools]]) |
| 161–214 | Boucle | `agent_loop_cached()` : stream + stats + gather |
| 217–258 | Point d'entrée | `main()` : REPL async, `finally: stats.summary()` |
| 261–266 | Garde | `asyncio.run(main())` |

## Constantes et configuration

**`CACHED_SYSTEM` — lignes 48–60.** Le prompt système change de forme : une chaîne ne peut pas porter de marqueur, il faut une **liste de blocs**.

```python
CACHED_SYSTEM: List[Dict[str, Any]] = [
    {
        "type": "text",
        "text": (
            f"You are a coding agent at {os.getcwd()}. "
            "Use tools to solve tasks. Be concise and precise.\n\n"
            "Tools available: bash, read, write, grep, glob, revert.\n"
            "Always read before writing. Always check your work."
        ),
        # This marker tells the API to cache everything up to this point
        "cache_control": {"type": "ephemeral"},
    }
]
```

- **Ligne 58** : le marqueur sur le **dernier** bloc système — l'API cache tout le préfixe jusqu'à ce point inclus (outils + système). « ephemeral » est aujourd'hui le seul type : ~5 min de TTL, rafraîchi à chaque lecture.
- **Ligne 52** : `os.getcwd()` est interpolé dans le texte — le préfixe caché dépend donc du répertoire de lancement ; relancer la démo depuis un autre dossier crée une entrée de cache distincte.

**`CACHED_TOOLS` — lignes 63–67.** Les outils aussi font partie du préfixe :

```python
CACHED_TOOLS: List[Dict[str, Any]] = copy.deepcopy(EXTENDED_TOOLS)
CACHED_TOOLS[-1]["cache_control"] = {"type": "ephemeral"}
```

- **Ligne 63** : `deepcopy` — on ne mute pas `EXTENDED_TOOLS` de [[core-py]], qui est un objet partagé ; une copie superficielle ne suffirait pas car on modifie un dict *à l'intérieur* de la liste.
- **Ligne 67** : marqueur sur le **dernier** outil de la liste (ici `revert`) : la règle Anthropic est « tout ce qui précède le marqueur est caché », donc marquer le dernier élément cache l'ensemble des schémas. Deux marqueurs au total (outils + système) sur les 4 points de césure autorisés par requête.

**`stats = CacheStats()` — ligne 124** : l'instance globale, alimentée à chaque tour, résumée à la sortie.

## Les fonctions, une à une

### Classe `CacheStats` — lignes 72–120

L'instrumentation qui transforme une optimisation invisible en chiffres affichés.

**`__init__()` — lignes 77–82** : quatre compteurs — `created` (tokens écrits en cache, les MISS), `read` (tokens relus, les HIT), `uncached` (tokens d'entrée hors cache) et `calls` (nombre de tours API).

**`record(usage)` — lignes 84–95** :

```python
    def record(self, usage: Any) -> None:
        self.calls += 1
        self.created += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.read += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.uncached += getattr(usage, "input_tokens", 0) or 0
```

- **Lignes 93–95** : double défense — `getattr(..., 0)` si le champ n'existe pas dans la réponse (vieux SDK, proxy non-Anthropic), `or 0` si le champ existe mais vaut `None`. C'est ce qui permet à la démo de tourner derrière LiteLLM avec un modèle sans caching : les compteurs restent à zéro au lieu de planter.
- Les trois champs sont la comptabilité officielle de l'API : `cache_creation_input_tokens` (écrits, facturés ~125 % du tarif d'entrée), `cache_read_input_tokens` (relus, ~10 %), `input_tokens` (la part non cachée, plein tarif).

**`show_turn(usage)` — lignes 97–113** : le feedback immédiat.

```python
        if created > 0:
            print(f"\033[90m  [cache] MISS → {created} tokens written to cache\033[0m")
        elif read > 0:
            saved = int(read * 0.9)
            print(f"\033[90m  [cache] HIT  → {read} tokens read (saved ≈{saved} tokens)\033[0m")
```

- **Ligne 107 vs 111** : `if/elif` — un tour qui écrit *et* lit (préfixe partiellement réutilisé, extension du cache) ne montre que le MISS. Et si les deux valent zéro (caching indisponible, ou prompt sous le minimum cacheable), **rien** ne s'affiche — silence qui vaut diagnostic.
- **Ligne 112** : `saved = int(read * 0.9)` — une *estimation* (les tokens relus coûtent ~10 % du tarif), pas une lecture de facture.

**`summary()` — lignes 115–120** : le bilan de session — `turns`, `written`, `hits` et l'économie estimée — imprimé par le `finally` de `main()`, donc même après un Ctrl+C.

### `dispatch_one_tool(block)` — lignes 129–158

La coroutine d'exécution d'un outil : handler depuis `ASYNC_DISPATCH` (ligne 143), `await` sous `try/except` (149–153), retour `(block.id, output)` (ligne 158). Identique à celle de [[s18-parallel-tools]], où elle est expliquée ligne par ligne — le caching ne la concerne pas.

### `agent_loop_cached(messages)` — lignes 163–214

La boucle perception-action async. Ce qui est propre à s20 tient en deux endroits. D'abord l'appel API (lignes 173–184) :

```python
        def _blocking_stream_call():
            with client.messages.stream(
                model=MODEL,
                system=CACHED_SYSTEM,   # Provide the list of blocks with cache_control
                messages=messages,
                tools=CACHED_TOOLS,     # Provide the tools with the last-tool marker
                max_tokens=8000,
            ) as stream:
```

- **Lignes 177 et 179** : les deux seules différences avec une boucle ordinaire — `system=` reçoit la **liste de blocs** marquée, `tools=` la copie marquée. Tout le mécanisme de cache tient dans ces deux arguments ; le serveur fait le reste.

Ensuite l'instrumentation, juste après la réponse (lignes 191–193) :

```python
        if hasattr(response, "usage"):
            stats.record(response.usage)
            stats.show_turn(response.usage)
```

- **Ligne 191** : garde `hasattr` — encore la tolérance aux backends qui ne renvoient pas d'`usage`.

Le reste (lignes 196–214) est la mécanique standard de la phase : archivage du message assistant, sortie sur `stop_reason != "tool_use"`, exécution parallèle par `asyncio.gather` et réassemblage des `tool_result` par id — analysés dans [[s18-parallel-tools]]. Point important pour le cache : l'historique ne grandit que **par ajout en fin** (`messages.append`), jamais par réécriture — c'est ce qui garde le préfixe stable d'un tour à l'autre et permet les HIT en rafale.

### `main()` — lignes 219–258

REPL async classique : `input()` via `run_in_executor` (236–238), sortie sur `q`/`exit`/`quit`/vide (244), append de la requête et appel d'`agent_loop_cached` (248–251). La spécificité s20 est la structure `try/finally` (231–258) : **`stats.summary()` s'imprime toujours** (ligne 258), que la session se termine proprement ou par Ctrl+C — le bilan d'économie est la raison d'être de la démo.

### Garde `if __name__ == "__main__"` — lignes 261–266

`asyncio.run(main())` sous `try/except KeyboardInterrupt: pass` : sortie silencieuse, le `finally` de `main()` ayant déjà affiché le résumé.

## Ce qui vient de [[core-py]]

- **`client`** : le client Anthropic — c'est lui qui transporte les `cache_control` jusqu'à l'API.
- **`MODEL`** : l'identifiant du modèle (le caching exige un modèle Anthropic qui le supporte).
- **`EXTENDED_TOOLS`** : les 6 schémas d'outils, copiés profondément en `CACHED_TOOLS` avant marquage — l'original reste vierge pour les autres sessions.
- **`ASYNC_DISPATCH`** : les handlers async des outils, consommés par `dispatch_one_tool`.

Ni `stream_loop` ni `dispatch_tools` : la boucle de core.py passe `system` en chaîne et ne lit pas `usage` ; il fallait la réécrire pour brancher les deux.

## Pièges et détails d'implémentation

- **Le cache est exact au token près** : le moindre changement dans le préfixe (un mot du système, l'ordre des outils, `os.getcwd()` différent) invalide tout — MISS complet. C'est pourquoi le marqueur est posé sur des éléments *immuables* pendant la session, jamais sur le dernier message utilisateur.
- **En dessous d'un minimum, le marqueur est ignoré en silence** : l'API n'écrit pas en cache les préfixes trop courts (~1024 tokens selon le modèle). Symptôme : ni MISS ni HIT ne s'affichent — le `if/elif` de `show_turn` ne passe nulle part.
- **Un MISS n'est pas gratuit, c'est un investissement** : l'écriture en cache est facturée ~125 % du tarif d'entrée. Le caching n'est rentable qu'à partir du deuxième appel dans la fenêtre des 5 minutes — exactement le profil d'une boucle d'agent multi-tours.
- **`deepcopy` est indispensable, pas décoratif** : marquer `EXTENDED_TOOLS[-1]` directement muterait l'objet partagé de [[core-py]] pour tout importateur du même process.
- **Incohérence héritée de core.py** : `CACHED_SYSTEM` annonce `revert` parmi les outils et `CACHED_TOOLS` en contient le schéma, mais `ASYNC_DISPATCH` n'a **pas** de handler `revert` — un appel du modèle à `revert` répond `Error: Unknown tool revert`. (La table synchrone `EXTENDED_DISPATCH`, elle, l'a.)
- **Derrière LiteLLM, la démo tourne mais ne démontre rien** : un backend non-Anthropic ignore `cache_control` ; grâce aux `getattr`/`or 0`, tout fonctionne — avec des compteurs à zéro et un `summary` vide de sens.

## Lancer la démo

```bash
cd inspiration/claude-code-from-scratch
python s20_cache_optimization.py
```

Prérequis : `.env` avec `ANTHROPIC_API_KEY` + `MODEL_ID` pointant sur un modèle Anthropic supportant le prompt caching (via LiteLLM, les marqueurs seront ignorés — voir pièges).

À observer (exemple du README) :

```
[cache] MISS → 1,847 tokens written
[cache] HIT  → 1,847 tokens read (saved ~1,662 tokens)
[cache summary] 6 calls | written=1,847 | hits=5 | total saved≈8,310 tokens
```

Premier tour : MISS (le préfixe s'écrit). Tours suivants, et chaque itération interne de la boucle d'outils : HIT — c'est là que l'économie explose, car une tâche agentique enchaîne les appels API à quelques secondes d'intervalle, pile dans la fenêtre ephemeral. Quittez avec `q` : le `[cache total]` tombe, imprimé par le `finally`.

## Liens

- Socle : [[core-py]]
- Session précédente : [[s19-interrupts]]
- Session suivante : [[s21-mcp-runtime]]
- Sessions liées : [[s18-parallel-tools]] (fichier jumeau — le versant exécution parallèle de ce même code), [[s06-context-compact]] (l'autre levier d'économie de contexte : compresser au lieu de cacher), [[s13-streaming]] (le streaming, ici déporté en thread)
