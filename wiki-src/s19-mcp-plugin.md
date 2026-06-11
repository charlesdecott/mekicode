---
title: "s19 · Plugin MCP"
session: 19
phase: "Intégration & synthèse"
fichier: "src/s19.py"
lignes: 100
tags: [mcp, plugins, tool-pool, namespace]
prev: "s18-worktree-isolation"
next: "s20-comprehensive"
---

# s19 · Plugin MCP

> **En une phrase** : `connect_mcp` découvre les outils d'un serveur externe (mock de `tools/list`), `assemble_tool_pool` les fusionne avec les outils natifs sous le namespace `mcp__{server}__{tool}` — la démo déroule découverte → assemblage → invocation sans LLM, en appelant directement les handlers du pool comme le ferait `agent_loop`.

## Rôle dans le harness

De s01 à s18, chaque outil de l'agent a été écrit à la main. MCP (Model Context Protocol) fournit le protocole standard qui évite de réécrire du code d'outil pour chaque service : un serveur expose `tools/list` (découverte) et `tools/call` (invocation), un client côté agent relaie. La version pédagogique mocke la couche transport : `MCPClient.register()` tient lieu de découverte, `MCPClient.call_tool()` d'invocation, et les « serveurs » `MOCK_SERVERS` (`docs` en lecture seule, `deploy` avec un outil destructif) sont des lambdas locales.

Le second mécanisme est l'**assemblage** : `assemble_tool_pool()` part de copies de `BUILTIN_TOOLS`/`BUILTIN_HANDLERS` et ajoute chaque outil MCP sous le nom préfixé (noms assainis par `normalize_mcp_name`), en traduisant le schéma `inputSchema` (camelCase MCP) en `input_schema` (API Anthropic), et en câblant des lambdas à **arguments par défaut** (`c=mcp_client, t=tool_def["name"]`) — sans quoi le late binding des closures Python routerait tous les outils MCP vers le dernier enregistré. Dans shared, `agent_loop` ré-assemble ce pool à chaque tour : les outils découverts apparaissent au tour suivant un `connect_mcp`.

## Ce que fait ce fichier

### show_pool() — lignes 28–36
Assemble le pool courant et le mesure :

```python
    tools, handlers = assemble_tool_pool()
    mcp_names = [t["name"] for t in tools if t["name"].startswith("mcp__")]
    print(f"\n{label} : {len(tools)} outils "
          f"({len(BUILTIN_TOOLS)} natifs + {len(mcp_names)} MCP)")
```

Liste les noms `mcp__...` et retourne `(tools, handlers)` — appelée trois fois, elle matérialise la croissance du pool au fil des connexions.

### main() — lignes 39–95
La démo en sept temps numérotés comme à l'écran :

1. **Pool initial** (l. 41) : 27 outils natifs, 0 MCP.
2. **Connexions** (l. 43–49) : `connect_mcp("docs")` énumère les outils découverts ; la reconnexion est refusée (idempotence) ; `connect_mcp("jira")` échoue en **listant les serveurs disponibles** (le LLM pourrait se corriger au tour suivant) ; puis `connect_mcp("deploy")`.
3. **Pool après connexion** (l. 51) : 31 outils, dont `mcp__docs__search`, `mcp__docs__get_version`, `mcp__deploy__trigger`, `mcp__deploy__status`.
4. **Traduction de schéma** (l. 53–57) : la définition assemblée de `mcp__docs__search` est affichée en JSON — la clé est devenue `input_schema`, prête pour l'API Anthropic.
5. **Invocations via le pool** (l. 59–69) : quatre handlers appelés directement — exactement le dispatch d'`agent_loop` — et quatre réponses distinctes (`[docs] Found 3 results...`, `[docs] API v2.1.0`, `[deploy] api: running...`, `[deploy] Triggered: api`) : la preuve qu'aucune lambda n'a « fui » vers le dernier outil de la boucle.
6. **MCPClient en direct** (l. 71–88) : un serveur « maison » au nom volontairement sale est construit et enregistré :

```python
    meteo = MCPClient("météo!")
    meteo.register(
        tool_defs=[{"name": "prévision", "description": "Prévision locale.",
                    "inputSchema": {...}}],
        handlers={"prévision": lambda ville: f"[météo] {ville} : 21 °C"})
    mcp_clients["météo!"] = meteo
```

`normalize_mcp_name('météo!')` → `'m_t_o_'` (tout caractère hors `[a-zA-Z0-9_-]` devient `_`), `call_tool('inconnu', {})` → `MCP error: unknown tool 'inconnu'` (jamais d'exception : l'erreur revient en texte, comme une réponse d'erreur JSON-RPC), puis l'outil assaini `mcp__m_t_o___pr_vision` est invoqué via le pool ré-assemblé (l. 85–88). Notez que la lambda du pool appelle le serveur avec le nom **original** (`prévision`), pas le nom normalisé.
7. **Le system prompt vivant** (l. 90–95) : `assemble_system_prompt(update_context({}, []))` contient la ligne `Connected MCP servers: docs, deploy, météo!` — c'est pourquoi le prompt est ré-assemblé à chaque tour, sans mémoïsation : un cache servirait une liste d'outils périmée après une connexion.

## Ce qui vient de [[shared-py]]

- `MCPClient` — le client mock (register = `tools/list`, call_tool = `tools/call`, erreurs en texte).
- `mcp_clients` — le registre global des serveurs connectés, consulté par l'assemblage et le system prompt.
- `connect_mcp(name)` — connexion idempotente aux `MOCK_SERVERS` (`docs`, `deploy`), erreur listant les serveurs disponibles.
- `assemble_tool_pool()` — fusion builtin + MCP : copies défensives, conversion `inputSchema` → `input_schema`, lambdas à arguments par défaut.
- `normalize_mcp_name(name)` — l'hygiène des noms externes.
- `BUILTIN_TOOLS` — les 27 outils natifs, base du pool.
- `assemble_system_prompt` / `update_context` — le system prompt vivant qui annonce les serveurs connectés.

## Différences avec l'original learn-claude-code

- L'original `s19_mcp_plugin/code.py` (1025 lignes) re-portait toute la pile et démontrait MCP au travers d'un REPL + `agent_loop` ; ici 99 lignes, sans LLM : les handlers du pool sont appelés directement, ce qui rend visible (et vérifiable) l'absence de cross-talk entre lambdas.
- Ajout pédagogique absent de l'original : un `MCPClient` « maison » au nom accentué (`météo!` / `prévision`) pour exercer `normalize_mcp_name` et le chemin d'erreur de `call_tool`.
- Dans shared (comportement hérité du s20 original), le pool est ré-assemblé à **chaque** tour d'`agent_loop`, pas seulement après un tour contenant `connect_mcp` comme dans le s19 original.
- Toujours dans shared, `permission_hook` exige une confirmation pour tout outil MCP dont le nom contient `deploy` — le s19 original n'appliquait aucune permission aux outils MCP (annotation `(destructive)` purement textuelle).

## Lancer la démo

```
python src/s19.py
```

Sans appel LLM (l'import de shared exige `MODEL_ID` dans `.env`). On observe : le pool qui passe de 27 à 31 puis 32 outils, les messages d'idempotence et de serveur inconnu, la définition traduite de `mcp__docs__search`, quatre invocations sans cross-talk, l'assainissement `météo! → m_t_o_`, et la ligne `Connected MCP servers:` du system prompt.

## Liens

- Bibliothèque : [[shared-py]]
- Session précédente : [[s18-worktree-isolation]]
- Session suivante : [[s20-comprehensive]]
