---
title: "s21 · Runtime MCP"
session: 21
phase: "Runtime async"
fichier: "inspiration/claude-code-from-scratch/s21_mcp_runtime.py"
lignes: 344
tags: [mcp, stdio, json-rpc, tool-discovery, namespacing]
prev: "s20-cache-optimization"
next: "s22-production-mailbox"
---

# s21 · Runtime MCP

> **En une phrase** : au démarrage, l'agent lit `config/mcp_config.yaml`, lance chaque serveur MCP en sous-processus stdio, découvre leurs outils via le SDK officiel, les renomme `mcp__<serveur>__<outil>` et les fusionne avec les outils locaux — le registre d'outils devient extensible sans toucher une ligne de code.

## Rôle dans le harness

Jusqu'ici, ajouter un outil signifiait écrire un handler Python et une entrée de schéma — voir [[s02-tool-use]] et [[s14-tools-extended]]. Cette approche ne passe pas à l'échelle de l'écosystème : GitHub, bases de données, navigateurs, APIs internes... La devise de la session : *« Any server, any tool; the world connects here »*. Le Model Context Protocol standardise la réponse : un serveur MCP est un process qui expose ses outils (nom, description, JSON Schema) via JSON-RPC, et n'importe quel client peut les découvrir et les appeler sans rien connaître de leur implémentation.

La session implémente le **côté client** avec le SDK officiel (`pip install mcp`) : lecture d'un registre YAML déclaratif, connexion stdio à chaque serveur (le client *spawn* le process et lui parle par stdin/stdout), `list_tools()` pour la découverte, traduction des schémas MCP au format Anthropic, puis routage des appels — un `tool_use` dont le nom commence par `mcp__` part vers la session MCP correspondante, les autres restent sur `ASYNC_DISPATCH` local. Quatre principes du README s'incarnent ici d'un coup : la configuration est déclarative (le YAML), les outils restent l'unique interface avec le monde, et la boucle, elle, ne change toujours pas.

L'analogue est direct (colonne « Claude Code Analog » : *CC MCP support*) : le vrai Claude Code utilise exactement la même convention de nommage `mcp__<serveur>__<outil>` pour les serveurs déclarés dans `.mcp.json` ou `claude_code_settings`. learn-claude-code a aussi sa session MCP & plugins (sa s19), mais avec un client JSON-RPC artisanal ; ici c'est le SDK officiel qui gère le protocole — la session se concentre sur l'intégration au harness : découverte, préfixage, routage, cycle de vie.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–27 | Shebang & docstring | Découverte dynamique, préfixage, transport stdio, cycle de vie |
| 30–35 | Imports stdlib | `asyncio`, `os`, `yaml`, `sys`, `pathlib`, typing |
| 38–43 | Imports core | `client`, `MODEL`, `EXTENDED_TOOLS`, `ASYNC_DISPATCH` |
| 46–56 | Registres globaux | `_CONFIG_PATH` (48), `MCP_SESSIONS` (52), `MCP_TOOL_MAP` (56) |
| 58–69 | Import optionnel | `try: from mcp import ...` → drapeau `HAS_MCP` |
| 72–151 | **Découverte** | `connect_mcp_servers()` : spawn, init, list_tools, traduction |
| 154–188 | **Exécution distante** | `execute_mcp_tool()` : routage et appel JSON-RPC |
| 191–222 | **Routage unifié** | `dispatch_one_tool()` : local ou MCP selon le nom |
| 225–285 | Boucle | `agent_loop_mcp()` : boucle async avec toolset fusionné |
| 288–336 | Point d'entrée | `main()` : découverte → fusion → REPL → shutdown |
| 339–344 | Garde | `asyncio.run(main())` |

## Constantes et configuration

- **`_CONFIG_PATH` (ligne 48)** : `Path(__file__).parent.parent / "config" / "mcp_config.yaml"` — attention, `parent.parent` remonte d'un cran **au-dessus** du dossier du script ; le fichier `config/` doit donc se trouver à côté du dossier qui contient `s21_mcp_runtime.py` (même convention que `_PERM_CONFIG` dans [[core-py]] — héritage d'une arborescence `agents/` d'origine).
- **`MCP_SESSIONS` (ligne 52)** : dict global `nom_serveur → ClientSession` actif ; rempli à la connexion, parcouru au shutdown.
- **`MCP_TOOL_MAP` (ligne 56)** : la table de routage `"mcp__srv__tool" → (srv, tool)` — l'équivalent MCP du `TOOL_HANDLERS` de [[s02-tool-use]], sauf qu'elle se remplit **toute seule** à la découverte.
- **`HAS_MCP` (lignes 60–69)** : l'import du SDK est sous `try/except ImportError` ; sans le paquet `mcp`, un avertissement s'affiche et la démo continue avec les seuls outils locaux — dégradation gracieuse plutôt que crash à l'import.
- **`config/mcp_config.yaml` (22 lignes)** : le registre déclaratif. Tel que livré, **tous les serveurs sont commentés** (`servers:` ne contient que des exemples : `filesystem` via `npx @modelcontextprotocol/server-filesystem`, `git` via `uvx mcp-server-git`, et un serveur Python maison) — il faut en décommenter pour voir du MCP réel.

## Les fonctions, une à une

### `connect_mcp_servers()` — lignes 74–151

La séquence de boot : pour chaque serveur du YAML, spawn du process, poignée de main MCP, inventaire des outils, traduction des schémas. Les gardes d'abord (lignes 87–100) : sans SDK (`HAS_MCP`), sans fichier de config, ou sur YAML invalide, la fonction retourne `[]` — l'agent démarre quand même. Puis la boucle sur `config.get("servers") or []` (ligne 105 — le `or []` absorbe un YAML où `servers:` est vide, exactement le cas du fichier livré).

```python
            if srv_cfg.get("transport", "stdio") == "stdio":
                params = StdioServerParameters(
                    command=srv_cfg["command"],
                    args=srv_cfg.get("args", [])
                )
                read_stream, write_stream = await stdio_client(params).__aenter__()
                session = await ClientSession(read_stream, write_stream).__aenter__()
                await session.initialize()
                mcp_response = await session.list_tools()
                tool_list = mcp_response.tools
                MCP_SESSIONS[server_name] = session
```

- **Ligne 110** : seul le transport `stdio` est implémenté ; toute autre valeur tombe dans le `else` de la ligne 145 (message « not supported » — pas de SSE/HTTP ici).
- **Ligne 119** : `stdio_client(params).__aenter__()` appelé **à la main** — le pattern normal serait `async with stdio_client(params) as (r, w):`, mais un `async with` fermerait la connexion à la sortie du bloc, alors qu'on en a besoin pendant toute la session. Le commentaire du code l'assume (*« In a production long-running app, we manage __aenter__ manually »*). Le prix de ce raccourci est détaillé dans les pièges.
- **Lignes 122–123** : deuxième couche — la `ClientSession` parle JSON-RPC sur les deux flux, et `initialize()` exécute la poignée de main du protocole (échange de versions et de capacités). Obligatoire avant tout `list_tools`.
- **Ligne 126** : `list_tools()` — la découverte proprement dite : le serveur décrit ses outils, schémas compris.

La traduction (lignes 134–144) :

```python
                for tool in tool_list:
                    prefixed_name = f"mcp__{server_name}__{tool.name}"
                    MCP_TOOL_MAP[prefixed_name] = (server_name, tool.name)
                    discovered_tools.append({
                        "name": prefixed_name,
                        "description": f"[{server_name}] {tool.description or tool.name}",
                        "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
                    })
```

- **Ligne 135** : le préfixage `mcp__<serveur>__<outil>` évite toute collision entre serveurs (deux serveurs peuvent exposer un outil `search`) et avec les outils locaux — c'est mot pour mot la convention du vrai Claude Code.
- **Ligne 142** : la description est préfixée `[server_name]` pour que le **modèle** sache d'où vient l'outil ; ligne 143, un schéma vide mais valide est substitué si le serveur n'en fournit pas (l'API Anthropic exige un `input_schema`).
- **Lignes 147–149** : le `try/except` enveloppe **chaque serveur individuellement** — un serveur qui ne démarre pas (Node absent, paquet introuvable) est loggué en rouge et n'empêche pas les autres de se connecter. Isolation de panne dès le boot.

### `execute_mcp_tool(prefixed_name, arguments)` — lignes 154–188

Le chemin d'exécution distant : déréférencement, appel JSON-RPC, normalisation de la réponse.

```python
    if prefixed_name not in MCP_TOOL_MAP:
        return f"Error: MCP tool '{prefixed_name}' is not in the registry."
    srv_name, original_tool_name = MCP_TOOL_MAP[prefixed_name]
    session = MCP_SESSIONS.get(srv_name)
    if not session:
        return f"Error: MCP session for '{srv_name}' is inactive."
    try:
        result = await session.call_tool(original_tool_name, arguments)
        output_parts = [
            item.text for item in (result.content or [])
            if hasattr(item, "text")
        ]
        return "\n".join(output_parts)[:50000] or "(no output received)"
    except Exception as e:
        return f"Error during MCP execution: {e}"
```

- **Lignes 166–173** : deux vérifications distinctes — outil inconnu du registre, puis session absente — chacune avec son message d'erreur précis. Comme partout dans le repo, l'erreur est une **chaîne renvoyée au modèle**, jamais une exception qui remonte.
- **Ligne 177** : `session.call_tool(nom_original, arguments)` — on dé-préfixe avant d'appeler : le serveur ne connaît que `read_file`, pas `mcp__filesystem__read_file`. Les arguments du modèle passent tels quels (c'est le serveur qui valide contre son propre schéma).
- **Lignes 180–183** : une réponse MCP est une liste de blocs de contenu typés (texte, image, ressource) ; on ne garde que ceux qui ont un attribut `.text` — les blocs binaires sont silencieusement ignorés.
- **Ligne 185** : troncature à 50 000 caractères (la même discipline de contexte que `run_bash` dans [[core-py]]) et placeholder `"(no output received)"` — jamais de vide ambigu vers le modèle.

### `dispatch_one_tool(block, mcp_names)` — lignes 193–222

La variante s21 de la coroutine d'exécution (cf. [[s18-parallel-tools]] pour la version de base) : elle gagne un **aiguillage**.

```python
    if tool_name in mcp_names:
        # Route to external MCP server
        output = await execute_mcp_tool(tool_name, tool_input)
    else:
        # Route to local core.py implementation
        handler = ASYNC_DISPATCH.get(tool_name)
        output = await handler(tool_input) if handler else f"Error: Unknown tool {tool_name}"
```

- **Ligne 212** : le test d'appartenance à un `set` (O(1)) décide de la destination : MCP distant ou `ASYNC_DISPATCH` local. Le modèle, lui, ne voit aucune différence — un outil est un outil ; la frontière local/distant est un détail de routage du harness.
- À noter : contrairement à s18/s19/s20, il n'y a **pas** de `try/except` autour de la branche locale (lignes 217–218) — `execute_mcp_tool` attrape ses erreurs en interne, mais une exception d'un handler local remonterait jusqu'au `asyncio.gather` de la boucle. Petite régression de robustesse par rapport aux sessions jumelles.

### `agent_loop_mcp(messages, all_tool_definitions)` — lignes 227–285

La boucle async de la phase, avec trois particularités s21 :

- **Ligne 236** : `mcp_tool_names = set(MCP_TOOL_MAP.keys())` — le set de routage est figé à l'entrée de boucle (pas de découverte à chaud : un serveur connecté après coup serait invisible).
- **Lignes 239–244** : le prompt système est reconstruit pour annoncer la convention au modèle : *« MCP tools are prefixed with `mcp__<server>__<tool>`. Use them for external services... »* — sans cette phrase, le modèle pourrait ignorer ces noms exotiques.
- **Ligne 255** : `tools=all_tool_definitions` — le toolset **fusionné** (locaux + découverts) passé à l'API ; ligne 275, chaque bloc part dans `dispatch_one_tool(b, mcp_tool_names)` et le `asyncio.gather` (ligne 277) exécute locaux et distants **mélangés en parallèle** — un `grep` local et un appel GitHub distant tournent ensemble.

Le reste — stream dans un thread (`_blocking_stream`, lignes 250–260), archivage, sortie sur `stop_reason`, réassemblage des `tool_result` par id (lignes 281–285) — est la mécanique commune de la phase, détaillée dans [[s18-parallel-tools]].

### `main()` — lignes 290–336

Le cycle de vie complet en trois temps, calqué sur un démarrage de service :

```python
    # 1. Boot-time MCP Server Discovery
    mcp_extra_tools = await connect_mcp_servers()
    # 2. Merge local core tools with discovered remote tools
    all_tools = EXTENDED_TOOLS + mcp_extra_tools
    print(f"\033[90m  Environment Ready: built-in={len(EXTENDED_TOOLS)} | MCP={len(mcp_extra_tools)} | total={len(all_tools)}\033[0m\n")
```

- **Lignes 298–301** : découverte puis fusion par simple concaténation de listes — `EXTENDED_TOOLS` n'est pas muté (contrairement à s20 qui devait le `deepcopy`er pour le modifier, ici `+` crée une liste neuve).
- **Lignes 309–326** : le REPL async standard (input en thread, `q`/`exit`/`quit`, `agent_loop_mcp(history, all_tools)`).
- **Lignes 328–336** : le `finally` ferme chaque session par `await session.__aexit__(None, None, None)` sous `try/except Exception: pass` — l'arrêt ne doit jamais échouer bruyamment, même si un serveur est déjà mort.

### Garde `if __name__ == "__main__"` — lignes 339–344

`asyncio.run(main())` sous `try/except KeyboardInterrupt: pass` — mais notez qu'un Ctrl+C qui interrompt `asyncio.run` peut court-circuiter le `finally` async de `main()` avant que toutes les sessions soient fermées proprement.

## Ce qui vient de [[core-py]]

- **`client`** : le client Anthropic — il ne voit que des schémas d'outils ; que certains soient des proxys MCP lui est invisible.
- **`MODEL`** : l'identifiant du modèle.
- **`EXTENDED_TOOLS`** : les 6 outils locaux (bash, read, write, grep, glob, revert), concaténés avec les outils MCP découverts pour former `all_tools`.
- **`ASYNC_DISPATCH`** : la table des handlers locaux — la branche `else` du routage de `dispatch_one_tool`.

## Pièges et détails d'implémentation

- **`__aenter__` manuel = cycle de vie bancal** : le context manager de `stdio_client` n'est jamais stocké, donc son `__aexit__` n'est **jamais** appelé — seule la `ClientSession` est fermée au shutdown. Les sous-processus serveurs peuvent survivre, et le SDK MCP (basé sur anyio) peut protester quand on sort un scope d'annulation depuis une autre tâche que celle qui l'a ouvert. C'est le compromis « démo » le plus lourd du fichier.
- **Avec le YAML livré, la démo est un no-op MCP** : tous les serveurs sont commentés → `built-in=6 | MCP=0`. Décommentez `filesystem` (exige Node.js/npx) ou `git` (exige uv/uvx) pour voir la découverte réelle.
- **Pas de découverte à chaud** : `MCP_TOOL_MAP` est rempli au boot et le set de routage figé à l'entrée de `agent_loop_mcp` ; un serveur ajouté au YAML en cours de session n'existe pas. Le vrai CC sait, lui, recharger ses serveurs.
- **Pas de gouvernance sur les outils distants** : aucun passage par `check_permission` de [[core-py]] — un serveur MCP malveillant ou trop permissif a les mains libres. Croiser avec [[s15-permissions]] serait l'exercice naturel.
- **La branche locale du routage n'attrape pas les exceptions** : un handler local qui lève fait échouer le `gather` du tour entier — contrairement aux coroutines blindées de [[s18-parallel-tools]] et [[s19-interrupts]].
- **`revert` toujours orphelin** : présent dans `EXTENDED_TOOLS` mais absent d'`ASYNC_DISPATCH` (qui n'a que bash/read/write/grep/glob) — un appel `revert` répond `Error: Unknown tool revert`. Défaut hérité de [[core-py]], commun à toute la phase async.
- **Deux serveurs homonymes s'écrasent** : `MCP_SESSIONS[server_name] = session` sans contrôle de doublon — le second remplace le premier dans le registre des sessions, alors que les noms d'outils préfixés des deux peuvent coexister dans `MCP_TOOL_MAP`.

## Lancer la démo

```bash
cd inspiration/claude-code-from-scratch
pip install mcp                 # le SDK officiel (sinon : mode dégradé, outils locaux seuls)
python s21_mcp_runtime.py
```

Prérequis : `.env` avec `ANTHROPIC_API_KEY` + `MODEL_ID` (ou proxy LiteLLM) ; `config/mcp_config.yaml` avec au moins un serveur décommenté — par exemple `filesystem` (Node.js requis) :

```yaml
servers:
  - name: filesystem
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
```

À observer : au boot, `[MCP] filesystem: Connected (N tools)` puis `Environment Ready: built-in=6 | MCP=N | total=...`. Demandez ensuite « liste les fichiers avec l'outil filesystem » : le modèle appelle `mcp__filesystem__list_directory`, la ligne jaune affiche le nom préfixé, et la réponse revient du sous-processus Node comme si c'était un outil local. `q` pour sortir : `[MCP] Shutting down active server sessions...`.

## Liens

- Socle : [[core-py]]
- Session précédente : [[s20-cache-optimization]]
- Session suivante : [[s22-production-mailbox]]
- Sessions liées : [[s02-tool-use]] (la table de dispatch que MCP remplit dynamiquement), [[s14-tools-extended]] (l'arsenal local que MCP étend), [[s15-permissions]] (la gouvernance qui manque aux outils distants), [[s18-parallel-tools]] (le `gather` qui mélange outils locaux et distants)
