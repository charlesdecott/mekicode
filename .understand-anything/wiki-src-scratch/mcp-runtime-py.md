---
title: "mcp_runtime.py · Runtime MCP"
phase: "Intégration"
fichier: "src_scratch/mcp_runtime.py"
lignes: 146
tags: [mcp, stdio, async, registre-outils, exitstack]
---

# mcp_runtime.py · Runtime MCP

> **En une phrase** : lit `mcp.servers` du config.yaml, lance chaque serveur en sous-processus stdio, découvre ses outils et les enregistre dans le registre de [[tools-py]] sous `mcp__<serveur>__<outil>` — avec un cycle de vie `AsyncExitStack` qui ferme enfin proprement ce que s21 laissait fuir.

## Rôle dans le harness

Le registre dynamique de [[tools-py]] (`register_tool`) permet d'ajouter des outils sans toucher la boucle ; ce module en est l'exploitation la plus spectaculaire : des outils qui n'existent même pas dans le code. Il reprend s21 — la connexion à des serveurs MCP (Model Context Protocol) en transport stdio — mais en remplace toute la plomberie de cycle de vie : là où la source appelait `__aenter__` à la main et ne refermait jamais rien, tout passe ici par des `AsyncExitStack`, du transport à la session.

La configuration vit dans le `config.yaml` unique (section `mcp.servers`, documentée dans [[core-py]] qui le charge) ; le démarrage est optionnel (`--mcp` au boot ou commande `:mcp` à la demande, dans [[main-py]]) et la dégradation gracieuse : sans paquet `mcp` installé ou sans serveur déclaré, le harness tourne avec ses outils locaux seuls.

Une contrainte structurelle traverse le module : les transports MCP (anyio) exigent que leurs cancel scopes se ferment **dans la tâche asyncio qui les a ouverts**. D'où l'architecture de [[main-py]] — un seul `asyncio.run` pour toute la session — qui garantit que `start_mcp()` et `stop_mcp()` partagent la même event loop.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–9 | Docstring | Rôle + note Windows (ProactorEventLoop, défaut depuis Python 3.8) |
| 11–15 | Imports | `AsyncExitStack`, `load_config`/`paint` ([[core-py]]), `register_tool` ([[tools-py]]) |
| 17–22 | Import gardé | `try: from mcp import …` → `HAS_MCP` (dégradation gracieuse) |
| 24–27 | État module | `MCP_SESSIONS`, `MCP_TOOL_MAP`, `_STACK` |
| 30–43 | Fabrique | `_make_handler()` — l'async_fn d'un outil MCP |
| 46–87 | Connexion | `_connect_one()` — un serveur, sa sous-pile, ses outils |
| 90–115 | API | `start_mcp()` |
| 118–133 | API | `stop_mcp()` |
| 136–146 | API | `mcp_status()` |

## Constantes et configuration

- **`HAS_MCP` (lignes 17–22)** : le paquet `mcp` est importé sous garde ; absent → `False` et chaque point d'entrée répond par un message clair (`pip install mcp`) au lieu d'un `ImportError`.
- **`MCP_SESSIONS` (ligne 25)** : `dict` serveur → `ClientSession` active — consulté **à chaque appel** d'outil, pas seulement à l'enregistrement.
- **`MCP_TOOL_MAP` (ligne 26)** : `"mcp__srv__tool"` → `(srv, tool)` — la table de routage inverse, qui sert aussi de compteur d'outils exposés.
- **`_STACK` (ligne 27)** : l'`AsyncExitStack` global, `None` tant que le runtime n'est pas démarré — son état fait office de booléen « démarré » (idempotence de `start_mcp`).

## Les fonctions, une à une

### `_make_handler(server_name, tool_name)` — lignes 30–43

Fabrique de fermetures : retourne l'`async_fn` qui sera enregistré pour un outil MCP donné.

```python
    async def _call(inp: dict) -> str:
        session = MCP_SESSIONS.get(server_name)
        if session is None:
            return f"Erreur : session MCP '{server_name}' inactive."
        try:
            result = await session.call_tool(tool_name, inp or {})
            # On ne garde que les blocs texte ; cap 50 000 car. comme run_bash.
            parts = [c.text for c in (result.content or []) if hasattr(c, "text")]
            return "\n".join(parts)[:50000] or "(aucune sortie)"
        except Exception as e:
            return f"Erreur d'exécution MCP : {e}"
```

- **Ligne 33** : la session est résolue **au moment de l'appel**, pas capturée à l'enregistrement — après `stop_mcp()`, un handler encore présent dans le dispatch répond « session inactive » au lieu de planter sur un transport fermé.
- **Lignes 39–40** : seuls les blocs texte du résultat sont conservés (images et autres types sont jetés), avec le même cap de 50 000 caractères que `run_bash` de [[tools-py]] et le même refus du vide ambigu (`"(aucune sortie)"`).
- **Lignes 41–42** : toute exception devient une chaîne d'erreur — une donnée pour le modèle, jamais un crash de la boucle.

### `_connect_one(srv_cfg)` — lignes 46–87

Connecte **un** serveur stdio et enregistre ses outils ; retourne leur nombre. Deux refus précoces : nom déjà connecté (ligne 55, voir « Bugs corrigés ») et transport non-stdio (lignes 58–60) — warning jaune, serveur ignoré, retour 0. Puis le cœur du FIX de cycle de vie :

```python
    params = StdioServerParameters(command=srv_cfg["command"], args=srv_cfg.get("args", []))
    sub = AsyncExitStack()
    try:
        read, write = await sub.enter_async_context(stdio_client(params))
        session = await sub.enter_async_context(ClientSession(read, write))
        await session.initialize()  # poignée de main obligatoire avant list_tools
        tools = (await session.list_tools()).tools
    except BaseException:
        await sub.aclose()
        raise
    _STACK.push_async_callback(sub.pop_all().aclose)
```

- **Sous-pile par serveur** : transport et session entrent dans une `AsyncExitStack` locale. Échec à n'importe quelle étape (spawn, handshake, `list_tools`) → le `except BaseException` referme immédiatement ce qui était ouvert, puis relance — `start_mcp` attrape, loggue, passe au serveur suivant.
- **Ligne 72** : en cas de succès, `sub.pop_all()` transfère la responsabilité de fermeture vers la pile globale `_STACK` — c'est `stop_mcp()` qui refermera, en LIFO.
- **Lignes 75–85** : chaque outil découvert est enregistré via `register_tool` sous le nom préfixé `mcp__<srv>__<tool>` (la convention du vrai Claude Code), description préfixée `[srv]`, et `tool.inputSchema or {"type": "object", "properties": {}}` en repli — certains serveurs déclarent des outils sans schéma. Seul `async_fn` est fourni : `register_tool` dérive le sync via `asyncio.run`, mais ces outils sont en pratique async-only (voir Pièges).

### `start_mcp()` — lignes 90–115

Le point d'entrée. Quatre sorties rapides : `HAS_MCP` faux (message d'installation), déjà démarré (**idempotent** : `_STACK is not None` → retourne le compte actuel, ligne 101–102), pas de section `mcp.servers` dans le config.yaml, ou liste vide. Sinon :

```python
    _STACK = AsyncExitStack()
    total = 0
    for srv in servers:
        try:
            total += await _connect_one(srv)
        except Exception as e:
            print(paint(f"  [MCP] échec connexion '{srv.get('name', '?')}': {e}", "red"))
    return total
```

Un serveur indisponible est loggué en rouge et **n'empêche pas les autres de monter** — le `try/except` par serveur isole les pannes. La lecture de la config est défensive : `(load_config().get("mcp") or {}).get("servers") or []` survit à une section absente ou nulle.

### `stop_mcp()` — lignes 118–133

```python
    stack, _STACK = _STACK, None
    MCP_SESSIONS.clear()   # les handlers déjà enregistrés répondront "session inactive"
    MCP_TOOL_MAP.clear()
    try:
        await stack.aclose()
    except Exception as e:
        print(paint(f"[MCP] fermeture imparfaite : {e}", "yellow"))
```

- **Ligne 127** : l'échange `stack, _STACK = _STACK, None` rend l'arrêt réentrant — un deuxième appel trouve `None` et retourne aussitôt.
- **Lignes 128–129** : les tables sont vidées **avant** la fermeture : pendant le `aclose()` (qui peut prendre du temps), tout appel d'outil tombe déjà sur « session inactive ».
- **Ligne 131** : `stack.aclose()` déroule la pile en LIFO — sessions puis transports stdio, donc sous-processus terminés. Une fermeture qui proteste est logguée en jaune, jamais propagée : on est dans le `finally` de [[main-py]], rien ne doit empêcher la fin de session.

### `mcp_status()` — lignes 136–146

Résumé lisible pour la commande `:mcp` : indisponible / arrêté / actif avec, par serveur, la liste de ses outils (noms d'origine, reconstruits en filtrant `MCP_TOOL_MAP` par serveur, ligne 144).

## Bugs de la source corrigés ici

- **Transports stdio jamais fermés (lignes 46–72, 118–133)** — s21 appelait `__aenter__` à la main sur `stdio_client` et `ClientSession` et ne refermait jamais les transports : sous-processus orphelins à chaque session. Correction : une sous-pile `AsyncExitStack` par serveur (échec partiel → refermeture immédiate ; succès → transfert dans `_STACK`), et `stop_mcp()` qui déroule tout en LIFO, transports compris.
- **Fermeture partielle à l'arrêt (lignes 121–122)** — corollaire du précédent : la source ne fermait que les `ClientSession`. Ici `aclose()` déroule aussi les `stdio_client` — plus de sous-processus orphelins.
- **Serveurs homonymes écrasés en silence (lignes 55–57)** — dans la source, deux serveurs du même nom s'écrasaient mutuellement dans le dict des sessions : le premier devenait injoignable mais ses outils restaient enregistrés et routaient vers le second. Correction : le doublon est ignoré avec un warning jaune explicite.

## Qui l'utilise

- [[main-py]] — seul importeur. Le flag `--mcp` appelle `start_mcp()` au boot, la commande `:mcp` le fait à la demande (démarrage paresseux) puis affiche `mcp_status()`, et le `finally` du REPL appelle `await mcp_runtime.stop_mcp()` à la sortie — toujours dans la même tâche asyncio, comme l'exige la contrainte anyio.

## Pièges et détails d'implémentation

- **`start_mcp` et `stop_mcp` doivent partager la même boucle ET la même tâche asyncio** : les cancel scopes anyio des transports se ferment là où ils ont ouvert. Un `asyncio.run` par appel (au lieu du `asyncio.run` unique de [[main-py]]) ferait planter la fermeture.
- **Les outils MCP sont async-only en pratique** : le sync dérivé par `register_tool` (`asyncio.run(async_fn(...))`) tenterait de créer une boucle alors que la session vit dans celle du REPL. C'est pour ça que [[main-py]] force le dispatch parallèle quand `--mcp` est posé (`--seq` ignoré avec warning).
- **`stop_mcp` ne désenregistre pas les outils** : ils restent dans `TOOLS`/dispatch de [[tools-py]], et leurs handlers répondent « session inactive ». Au redémarrage, `register_tool` *remplace* les entrées homonymes — pas de doublon.
- **`except BaseException` (ligne 69), pas `Exception`** : une annulation asyncio (`CancelledError` hérite de `BaseException`) pendant le handshake doit aussi refermer la sous-pile avant de se propager.
- **Windows** : le spawn de sous-processus asyncio exige le ProactorEventLoop — c'est le défaut depuis Python 3.8, la docstring le rappelle pour qu'on ne « répare » pas ce qui marche.

## Liens

- Modules liés : [[tools-py]] (`register_tool`, le registre où atterrissent les outils découverts), [[core-py]] (`load_config` — la section `mcp.servers` du config.yaml, `paint`), [[main-py]] (`--mcp`, `:mcp`, arrêt en fin de session), [[loop-py]] (le dispatch async qui exécute les handlers MCP)
