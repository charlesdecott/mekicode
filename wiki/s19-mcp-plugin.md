---
title: "s19 · Plugin MCP"
session: 19
phase: "Intégration & synthèse"
fichier: "inspiration/learn-claude-code/s19_mcp_plugin/code.py"
lignes: 1025
tags: [mcp, plugins, tool-pool, json-rpc, namespace]
prev: "s18-worktree-isolation"
next: "s20-comprehensive"
---

# s19 · Plugin MCP

> **En une phrase** : un système de plugins façon MCP (Model Context Protocol) — `connect_mcp` découvre les outils d'un serveur externe via `MCPClient`, `assemble_tool_pool` les fusionne avec les outils natifs sous le namespace `mcp__{server}__{tool}`, et `agent_loop` reconstruit dynamiquement son pool d'outils après chaque connexion.

## Rôle dans le harness

De [[s01-agent-loop]] à [[s18-worktree-isolation]], chaque outil de l'agent a été écrit à la main : bash, read, write, task, worktree… validation des entrées, logique d'exécution, gestion d'erreurs — tout ligne par ligne. Le README pose le problème d'échelle : vous devez intégrer l'API Jira de l'entreprise, un système de déploiement maison et la base Notion de l'équipe — sans réécrire du code d'outil pour chaque service. Il faut un **protocole standard** : tout service qui l'implémente devient appelable par l'agent, quel que soit son langage. Slogan du chapitre : *"External tools, standard protocol — Discover, assemble, invoke. Agent doesn't need to know who wrote them."*

C'est exactement ce que définit MCP : un serveur expose `tools/list` (découverte) et `tools/call` (invocation) en JSON-RPC ; un client côté agent s'y connecte, récupère les définitions d'outils et relaie les appels. La version pédagogique **mocke** la couche transport : `MCPClient.register()` simule la découverte `tools/list`, `MCPClient.call_tool()` simule l'invocation `tools/call`, et les « serveurs » sont des fonctions Python locales (`_mock_server_docs`, `_mock_server_deploy`). La vraie version lancerait des sous-processus et dialoguerait en JSON-RPC sur stdin/stdout — le mock permet d'exécuter le flux complet sans dépendance externe, au prix de ne pas voir la communication réseau ni la gestion de processus.

Le second mécanisme clé est l'**assemblage du pool d'outils** : `assemble_tool_pool()` part des `BUILTIN_TOOLS` et y ajoute chaque outil MCP sous le nom préfixé `mcp__{server}__{tool}` (noms normalisés par `normalize_mcp_name` pour éviter collisions et injections). Conséquence structurelle : la mémoïsation du prompt système (`get_system_prompt` de [[s10-system-prompt]]) disparaît — le pool étant dynamique, un cache deviendrait obsolète dès qu'une connexion ajoute `mcp__docs__search`. `agent_loop` ré-assemble pool et prompt après tout tour où `connect_mcp` a été appelé.

Le vrai Claude Code va beaucoup plus loin (README, section « Deep Dive ») : 6 types de transport (`stdio`, `sse`, `http`, `ws`, `sse-ide`, `sdk`), fusion du pool avec déduplication où les outils natifs gagnent les collisions de nom (et tri séparé pour préserver le point de rupture du prompt caching API), annotations structurées readOnly/destructive branchées sur le système de permissions, priorités de configuration multi-sources (connectors claude.ai < plugin < settings utilisateur < `.mcp.json` projet < settings locaux), OAuth 2.0 + PKCE, et notifications inverses serveur → agent (`claude/channel`). La version pédagogique garde la même convention de nommage `mcp__<server>__<tool>` et la même règle de normalisation que CC (`mcpStringUtils.ts:50-52`, `normalization.ts:17-23`).

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–22 | Docstring | changements vs s18, flux ASCII (`connect_mcp → discover → assemble_tool_pool`) |
| 24–44 | Imports & init | client `Anthropic`, `MODEL`, `WORKDIR` |
| 46–139 | Task System (s12/s17/s18) | `Task` (avec `worktree`), CRUD, `can_start`, `claim_task`, `complete_task` |
| 142–243 | Worktree System (s18) | validation, `run_git`, `log_event`, create/bind/remove/keep |
| 246–270 | Prompt Assembly | `PROMPT_SECTIONS` (+ `connect_mcp`), `assemble_system_prompt` **+ section serveurs MCP** ; la mémoïsation `get_system_prompt` a disparu |
| 273–310 | Outils de base (s18) | `safe_path`, `run_bash`, `run_read`, `run_write` (paramètre `cwd`) |
| 313–342 | MessageBus (s15) | inchangé |
| 344–384 | Protocol State (s16/s17) | `ProtocolState`, `match_response` (silencieuse), `consume_lead_inbox` |
| 387–432 | Agent autonome (s17/s18) | `scan_unclaimed_tasks`, `idle_poll` |
| 435–624 | Thread teammate (s18) | `spawn_teammate_thread` avec `wt_ctx`, `_teammate_submit_plan` |
| 627–655 | Outils protocole Lead (s16) | shutdown / request_plan / review_plan |
| 658–770 | **Système MCP (nouveau)** | `MCPClient`, `mcp_clients`, `normalize_mcp_name`, serveurs mock, `MOCK_SERVERS`, `connect_mcp`, `assemble_tool_pool` |
| 773–834 | Handlers Lead | worktree, tâches, inbox, **`run_connect_mcp` (nouveau)** |
| 837–944 | Définitions d'outils | **`BUILTIN_TOOLS`** (18, ex-`TOOLS`), **`BUILTIN_HANDLERS`** (ex-`TOOL_HANDLERS`) |
| 947–957 | Contexte | `MEMORY_INDEX`, `update_context` (s09) |
| 960–995 | **Boucle agent (modifiée)** | `agent_loop` à pool dynamique, ré-assemblage après `connect_mcp` |
| 998–1025 | REPL | bannière `s19: mcp tools`, injection inbox (s17) |

## Constantes et configuration

- `mcp_clients: dict[str, MCPClient] = {}` (ligne 683) — **nouveau** : registre global des serveurs connectés, consulté par `assemble_tool_pool` et `assemble_system_prompt`.
- `_DISALLOWED_CHARS = re.compile(r'[^a-zA-Z0-9_-]')` (ligne 685) — **nouveau** : tout caractère hors `[a-zA-Z0-9_-]` sera remplacé par `_` dans les noms MCP.
- `MOCK_SERVERS = {"docs": _mock_server_docs, "deploy": _mock_server_deploy}` (lignes 733–736) — **nouveau** : catalogue des serveurs simulés, nom → factory.
- `BUILTIN_TOOLS` (lignes 839–929) — les 18 outils natifs du Lead : les 17 de s18 + `connect_mcp` (lignes 924–928). Renommage significatif : `TOOLS` → `BUILTIN_TOOLS`, car le pool réel est désormais calculé. `BUILTIN_HANDLERS` (lignes 931–944) suit le même renommage.
- `PROMPT_SECTIONS` (lignes 248–258) — la section `tools` ajoute `connect_mcp` et annonce la convention : *"MCP tools are prefixed mcp__{server}__{tool}."*
- Reprises de [[s18-worktree-isolation]] : `TASKS_DIR` (48–49), `WORKTREES_DIR` / `VALID_WT_NAME` (144–147), `MAILBOX_DIR` (315–316), `BUS` / `active_teammates` (341–342), `pending_requests` (357), `IDLE_POLL_INTERVAL` / `IDLE_TIMEOUT` (389–390), `MEMORY_DIR` / `MEMORY_INDEX` (949–950).

## Les fonctions, une à une

### `Task` (dataclass) — lignes 52–60
Avec champ `worktree`. Repris de [[s18-worktree-isolation]] sans modification.

### `_task_path` — lignes 63–64, `create_task` — lignes 67–76, `save_task` — lignes 79–80, `load_task` — lignes 83–84, `list_tasks` — lignes 87–89, `get_task_json` — lignes 92–93, `can_start` — lignes 96–103, `claim_task` — lignes 106–124, `complete_task` — lignes 127–139
Le Task System complet, repris de [[s18-worktree-isolation]] sans modification.

### `validate_worktree_name` — lignes 150–158, `run_git` — lignes 161–168, `log_event` — lignes 171–176, `create_worktree` — lignes 179–193, `bind_task_to_worktree` — lignes 196–199, `_count_worktree_changes` — lignes 202–212, `remove_worktree` — lignes 215–235, `keep_worktree` — lignes 238–243
Le Worktree System, repris de [[s18-worktree-isolation]] sans changement fonctionnel — seuls quelques `print` de trace et messages ont été raccourcis (`bind_task_to_worktree` et `keep_worktree` n'affichent plus rien).

### `assemble_system_prompt(context)` — lignes 261–270
**Modifiée** : une section dynamique liste les serveurs MCP connectés.

```python
def assemble_system_prompt(context: dict) -> str:
    sections = [PROMPT_SECTIONS["identity"],
                PROMPT_SECTIONS["tools"],
                PROMPT_SECTIONS["workspace"]]
    if context.get("memories"):
        sections.append(f"Relevant memories:\n{context['memories']}")
    mcp_names = list(mcp_clients.keys())
    if mcp_names:
        sections.append(f"Connected MCP servers: {', '.join(mcp_names)}")
    return "\n\n".join(sections)
```

Le prompt système dépend maintenant d'un **état global mutable** (`mcp_clients`), pas seulement du `context` passé en argument. C'est précisément pourquoi la mémoïsation `get_system_prompt` de [[s10-system-prompt]] a été supprimée : son hash ne portait que sur `context` et aurait servi un prompt périmé après une connexion MCP.

### `safe_path` — lignes 275–280, `run_bash` — lignes 283–290, `run_read` — lignes 293–300, `run_write` — lignes 303–310
Outils de base avec paramètre `cwd`, repris de [[s18-worktree-isolation]] sans modification.

### `MessageBus` (classe) — lignes 319–338
Repris de [[s15-agent-teams]] sans modification.

### `ProtocolState` — lignes 346–354, `new_request_id` — lignes 360–361
Repris de [[s16-team-protocols]] sans modification.

### `match_response(response_type, request_id, approve)` — lignes 364–372
Reprise de [[s16-team-protocols]] mais **silencieuse** : les trois branches d'erreur (request_id inconnu, types incohérents) font un simple `return` sans plus afficher de diagnostic, et la confirmation colorée a disparu. Simplification de place — au prix de l'observabilité (voir Pièges).

### `consume_lead_inbox(route_protocol=True)` — lignes 375–384
Repris de [[s17-autonomous-agents]] sans modification.

### `scan_unclaimed_tasks()` — lignes 393–401
Repris de [[s17-autonomous-agents]] sans modification.

### `idle_poll(agent_name, messages, name, role)` — lignes 404–432
Repris de [[s18-worktree-isolation]] (avec l'info `Work directory:` dans `<auto-claimed>`), versions des prints raccourcies, le log d'échec de claim a disparu.

### `spawn_teammate_thread(name, role, prompt)` — lignes 437–612
Repris de [[s18-worktree-isolation]] sans changement de structure : `handle_inbox_message` (445–459), `wt_ctx` et les wrappers cwd (462–475), `_run_claim_task`/`_run_complete_task` avec bascule de worktree (486–497), `sub_tools` — toujours **8 outils, sans aucun outil MCP** (500–539), `sub_handlers` (541–550), cycle WORK → IDLE (552–595), résumé final (597–607). Le README insiste : dans la version pédagogique, **les outils MCP sont réservés au Lead** — `assemble_tool_pool` ne sert que `agent_loop` ; dans le vrai CC, les sous-agents héritent de la configuration MCP du parent.

### `_teammate_submit_plan` — lignes 615–624, `run_request_shutdown` — lignes 629–637, `run_request_plan` — lignes 640–642, `run_review_plan` — lignes 645–655
Protocole Lead/teammate repris de [[s16-team-protocols]] ; à noter que `run_review_plan` a perdu la garde `if state.status != "pending"` qu'avait s18 (re-review possible, voir Pièges).

### `MCPClient` (classe) — lignes 660–680
**Nouvelle.** Le client MCP côté agent — la pièce qui, en production, parlerait JSON-RPC à un sous-processus.

```python
class MCPClient:
    """Discovers and calls tools on an MCP server (mock for teaching)."""

    def __init__(self, name: str):
        self.name = name
        self.tools: list[dict] = []
        self._handlers: dict[str, callable] = {}

    def register(self, tool_defs: list[dict],
                 handlers: dict[str, callable]):
        self.tools = tool_defs
        self._handlers = handlers

    def call_tool(self, tool_name: str, args: dict) -> str:
        handler = self._handlers.get(tool_name)
        if not handler:
            return f"MCP error: unknown tool '{tool_name}'"
        try:
            return handler(**args)
        except Exception as e:
            return f"MCP error: {e}"
```

- `__init__` (lignes 663–666) : un client = un serveur nommé, une liste de définitions d'outils (`tools`) et une table privée de handlers (`_handlers` — le underscore marque le détail d'implémentation du mock).
- `register()` (lignes 668–671) tient lieu de **découverte** : dans le protocole réel, c'est la réponse à la requête JSON-RPC `tools/list` (après `initialize`) qui remplirait `self.tools`. Les définitions utilisent la clé MCP `inputSchema` (camelCase), pas le `input_schema` de l'API Anthropic — la traduction se fait dans `assemble_tool_pool`.
- `call_tool()` (lignes 673–680) tient lieu d'**invocation** : l'équivalent d'une requête `tools/call` avec `{"name": tool_name, "arguments": args}`. Deux protections : outil inconnu → message d'erreur (pas d'exception), et tout échec du handler est capturé et renvoyé comme texte `MCP error: ...` — l'agent reçoit l'erreur dans le `tool_result` au lieu de planter, comme le ferait une vraie réponse d'erreur JSON-RPC.

### `normalize_mcp_name(name)` — lignes 688–690
**Nouvelle.** L'hygiène des noms avant assemblage :

```python
_DISALLOWED_CHARS = re.compile(r'[^a-zA-Z0-9_-]')


def normalize_mcp_name(name: str) -> str:
    """Replace non [a-zA-Z0-9_-] with underscore."""
    return _DISALLOWED_CHARS.sub('_', name)
```

Tout caractère hors `[a-zA-Z0-9_-]` devient `_`. Deux raisons : l'API des outils impose des noms sûrs, et des caractères spéciaux dans un nom de serveur ou d'outil pourraient casser le schéma `mcp__server__tool` ou créer des injections de nom. Même règle que CC (`normalization.ts:17-23`). Effet de bord : la normalisation peut **créer** des collisions (`a.b` et `a_b` donnent tous deux `a_b`) — non gérées ici, voir Pièges.

### `_mock_server_docs()` — lignes 693–709
**Nouvelle.** Premier serveur simulé : documentation, deux outils en lecture seule.

```python
def _mock_server_docs():
    client = MCPClient("docs")
    client.register(
        tool_defs=[
            {"name": "search", "description": "Search documentation. (readOnly)",
             "inputSchema": {"type": "object",
                             "properties": {"query": {"type": "string"}},
                             "required": ["query"]}},
            {"name": "get_version", "description": "Get API version. (readOnly)",
             "inputSchema": {"type": "object", "properties": {},
                             "required": []}},
        ],
        handlers={
            "search": lambda query: f"[docs] Found 3 results for '{query}'",
            "get_version": lambda: "[docs] API v2.1.0",
        })
    return client
```

Les descriptions portent l'annotation textuelle `(readOnly)` : dans le vrai CC, ce sont des annotations structurées exploitées par le système de permissions ([[s03-permission]]) ; ici, c'est une indication pour le LLM, sans aucune application technique. Les handlers sont des lambdas qui fabriquent des réponses plausibles — aucun vrai backend.

### `_mock_server_deploy()` — lignes 712–730
**Nouvelle.** Second serveur simulé : déploiement, avec un outil **destructif**.

```python
            {"name": "trigger",
             "description": "Trigger a deployment. (destructive — requires approval in real CC)",
             "inputSchema": {"type": "object",
                             "properties": {"service": {"type": "string"}},
                             "required": ["service"]}},
```

Le contraste pédagogique avec `docs` : `trigger` est annoté `(destructive — requires approval in real CC)` tandis que `status` est `(readOnly)`. La version pédagogique laisse passer l'appel sans confirmation ; CC déciderait d'exiger une validation utilisateur d'après la déclaration de l'outil.

### `MOCK_SERVERS` — lignes 733–736
Catalogue nom → factory. Chaque connexion appelle la factory et obtient un `MCPClient` **neuf** — se connecter, c'est instancier.

### `connect_mcp(name)` — lignes 739–751
**Nouvelle.** L'outil de connexion + découverte :

```python
def connect_mcp(name: str) -> str:
    if name in mcp_clients:
        return f"MCP server '{name}' already connected"
    factory = MOCK_SERVERS.get(name)
    if not factory:
        available = ", ".join(MOCK_SERVERS.keys())
        return f"Unknown server '{name}'. Available: {available}"
    mcp_client = factory()
    mcp_clients[name] = mcp_client
    tool_names = [t["name"] for t in mcp_client.tools]
    print(f"  \033[31m[mcp] connected: {name} → {tool_names}\033[0m")
    return (f"Connected to MCP server '{name}'. "
            f"Discovered {len(mcp_client.tools)} tools: {', '.join(tool_names)}")
```

- Idempotence : reconnexion refusée si déjà dans `mcp_clients`.
- Serveur inconnu : le message d'erreur **liste les serveurs disponibles** — le LLM peut se corriger au tour suivant.
- Le retour énumère les outils découverts : le modèle sait immédiatement ce que la connexion lui apporte, avant même que le pool ne soit ré-assemblé.
- Dans le vrai CC, cette étape couvrirait le lancement du sous-processus (stdio) ou la connexion HTTP/SSE/WebSocket, le handshake `initialize`, puis `tools/list` — avec connexions par lots (3 serveurs locaux / 20 distants en parallèle) et toute la gestion d'erreurs et de reconnexion (`client.ts:1266-1402`).

### `assemble_tool_pool()` — lignes 754–770
**Nouvelle.** Le cœur de l'assemblage — natifs + MCP dans un pool unique :

```python
def assemble_tool_pool() -> tuple[list[dict], dict]:
    """Assemble builtin tools + all MCP tools into one pool."""
    tools = list(BUILTIN_TOOLS)
    handlers = dict(BUILTIN_HANDLERS)
    for server_name, mcp_client in mcp_clients.items():
        safe_server = normalize_mcp_name(server_name)
        for tool_def in mcp_client.tools:
            safe_tool = normalize_mcp_name(tool_def["name"])
            prefixed = f"mcp__{safe_server}__{safe_tool}"
            tools.append({
                "name": prefixed,
                "description": tool_def.get("description", ""),
                "input_schema": tool_def.get("inputSchema", {}),
            })
            handlers[prefixed] = (
                lambda *, c=mcp_client, t=tool_def["name"], **kw: c.call_tool(t, kw))
    return tools, handlers
```

Lecture ligne à ligne :
- lignes 756–757 : **copies** de `BUILTIN_TOOLS` / `BUILTIN_HANDLERS` (`list(...)`, `dict(...)`) — les structures globales ne sont jamais mutées, chaque assemblage repart de zéro ;
- lignes 758–762 : double boucle serveurs × outils ; serveur et outil sont normalisés séparément puis assemblés en `mcp__{server}__{tool}`. Le double underscore sépare les trois segments, et le préfixe garantit qu'un outil `search` de `docs` ne heurtera jamais un futur `search` de `jira` ;
- lignes 763–767 : **traduction de schéma** — la clé MCP `inputSchema` (camelCase) devient `input_schema` (la convention de l'API Anthropic). C'est le pont concret entre les deux protocoles ;
- lignes 768–769 : le handler est une lambda à la signature remarquable. `lambda *, c=mcp_client, t=tool_def["name"], **kw:` — le `*` initial rend tout keyword-only (les arguments du LLM arrivent via `handler(**block.input)`), et les **arguments par défaut `c=` et `t=` capturent les valeurs courantes de la boucle**. Sans cela, le piège classique des closures Python ferait que toutes les lambdas partageraient les *dernières* valeurs de `mcp_client` et `tool_def` après la boucle — tous les outils MCP appelleraient le dernier outil du dernier serveur. Notez que la lambda appelle `c.call_tool(t, kw)` avec le nom **original** de l'outil (`tool_def["name"]`), pas le nom normalisé : le serveur reçoit le nom qu'il a déclaré.
- Le retour `(tools, handlers)` est consommé par `agent_loop`. Le vrai CC fait l'équivalent dans `assembleToolPool()` (`tools.ts:345-364`) avec une déduplication `uniqBy` où **les outils natifs gagnent** en cas de collision, et un tri séparé natifs/MCP pour ne pas déplacer le point de rupture du prompt caching API.

### `run_create_worktree` — lignes 775–776, `run_remove_worktree` — lignes 778–779, `run_keep_worktree` — lignes 781–782
Wrappers worktree du Lead, repris de [[s18-worktree-isolation]] sans modification.

### `run_create_task` — lignes 787–792, `run_list_tasks` — lignes 795–802, `run_get_task` — lignes 805–806, `run_claim_task` — lignes 808–809, `run_complete_task` — lignes 811–812, `run_spawn_teammate` — lignes 814–815, `run_send_message` — lignes 817–819, `run_check_inbox` — lignes 821–831
Handlers Lead, repris de [[s18-worktree-isolation]] sans modification.

### `run_connect_mcp(name)` — lignes 833–834
**Nouvelle.** Wrapper d'outil minimal vers `connect_mcp` — c'est le 18e outil natif du Lead.

### `update_context(context, messages)` — lignes 953–957
Repris de [[s09-memory]] sans modification.

### `agent_loop(messages, context)` — lignes 962–995
**Modifiée** : la boucle du Lead passe au pool dynamique. Le commentaire de zone (ligne 960) annonce : `Agent Loop (s19: dynamic tool pool, no prompt cache)`.

```python
def agent_loop(messages: list, context: dict):
    tools, handlers = assemble_tool_pool()
    system = assemble_system_prompt(context)
    while True:
        try:
            response = client.messages.create(
                model=MODEL, system=system, messages=messages,
                tools=tools, max_tokens=8000)
        ...
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"\033[36m> {block.name}\033[0m")
            handler = handlers.get(block.name)
            output = handler(**block.input) if handler else "Unknown"
            ...
        messages.append({"role": "user", "content": results})

        if any(b.name == "connect_mcp" for b in response.content
               if b.type == "tool_use"):
            tools, handlers = assemble_tool_pool()
            context = update_context(context, messages)
            system = assemble_system_prompt(context)
```

- Ligne 963 : le pool est assemblé **à l'entrée de chaque conversation** — les serveurs connectés aux tours précédents restent disponibles (état global `mcp_clients`).
- Ligne 964 : appel direct à `assemble_system_prompt` — la mémoïsation `get_system_prompt` (et ses globales `_last_context_hash`/`_last_prompt`) a été **supprimée du fichier**. « No prompt cache » désigne ce cache applicatif local hérité de [[s10-system-prompt]], pas le prompt caching de l'API. Raison (README) : après `connect_mcp`, le pool change — servir une liste d'outils en cache rendrait les nouveaux `mcp__docs__*` inappelables.
- Lignes 991–995 : la ré-assemblée est **conditionnelle et ciblée** — uniquement si l'un des `tool_use` du tour était `connect_mcp`. Le coût de re-sérialisation n'est payé que quand le pool a réellement pu changer. Dès le tour suivant du `while True`, l'appel API part avec les outils MCP fraîchement découverts et un prompt système qui liste les serveurs connectés.
- Le dispatch (ligne 984) interroge `handlers` (le pool assemblé), plus une table globale figée : un même code exécute outils natifs et outils MCP — l'agent « ne sait pas qui les a écrits ».

### Bloc `if __name__ == "__main__":` — lignes 998–1025
REPL repris de [[s17-autonomous-agents]] (bannière `s19: mcp tools`, consommation de l'inbox du Lead et injection `[Inbox]` dans l'historique).

## Ce qui change par rapport à [[s18-worktree-isolation]]

- **Nouvelle zone « MCP System »** (lignes 658–770) : classe `MCPClient`, registre `mcp_clients`, `normalize_mcp_name`, `_mock_server_docs`, `_mock_server_deploy`, `MOCK_SERVERS`, `connect_mcp`, `assemble_tool_pool`.
- **`TOOLS` → `BUILTIN_TOOLS`, `TOOL_HANDLERS` → `BUILTIN_HANDLERS`** (lignes 839–944) : les structures globales deviennent la *base* d'un pool calculé. 18 outils natifs (+`connect_mcp`).
- **`agent_loop` à pool dynamique** (lignes 962–995) : assemblage à l'entrée, ré-assemblage après tout tour contenant `connect_mcp`, dispatch via le dict `handlers` local.
- **Suppression de `get_system_prompt`** et de ses globales de mémoïsation (présentes en s18 lignes 289–298) : le prompt système est ré-assemblé à chaque fois.
- **`assemble_system_prompt`** ajoute la section `Connected MCP servers: ...` (lignes 267–269) ; `PROMPT_SECTIONS["tools"]` documente le préfixe `mcp__{server}__{tool}`.
- **Namespace** : convention `mcp__{server}__{tool}` avec normalisation `[a-zA-Z0-9_-]` — identique au vrai CC.
- **Annotations** `(readOnly)` / `(destructive)` dans les descriptions des outils MCP — textuelles, sans application par le code.
- Outils teammate : 8, inchangés — les outils MCP sont réservés au Lead (simplification pédagogique).
- Simplifications silencieuses au passage : `match_response` perd ses diagnostics, `run_review_plan` perd la garde anti-double-review, plusieurs `print` de trace disparaissent.

## Pièges et détails d'implémentation

- **La capture par arguments par défaut dans la lambda** (ligne 769) est le détail le plus facile à rater : `lambda *, c=mcp_client, t=tool_def["name"], **kw` fige les valeurs *au moment de l'itération*. Une lambda naïve `lambda **kw: mcp_client.call_tool(tool_def["name"], kw)` compilerait sans erreur mais routerait **tous** les outils MCP vers le dernier outil enregistré — le bug de late binding des closures Python.
- **`inputSchema` ≠ `input_schema`** : MCP parle camelCase, l'API Anthropic snake_case. L'oubli de cette traduction (ligne 766) produirait des outils sans schéma — le `get("inputSchema", {})` avec défaut masquerait d'ailleurs un schéma manquant au lieu d'échouer.
- **La normalisation peut créer des collisions** : `normalize_mcp_name` projette `a.b`, `a b` et `a_b` sur le même `a_b`. Deux outils distincts d'un même serveur (ou deux serveurs aux noms proches) s'écraseraient dans `handlers` — le dernier gagne, silencieusement. De même, rien n'empêche un nom MCP préfixé d'entrer en collision avec un outil natif (CC déduplique avec priorité aux natifs ; ici `handlers[prefixed] = ...` écraserait le natif).
- **Le pool n'est ré-assemblé qu'après `connect_mcp`** : correct ici car c'est la seule mutation possible de `mcp_clients` — mais toute future fonctionnalité de déconnexion ou de rafraîchissement d'outils devrait penser à étendre la condition de la ligne 991.
- **« No prompt cache » prête à confusion** : c'est la mémoïsation *locale* du prompt système (l'astuce `_last_context_hash` de [[s10-system-prompt]]) qui disparaît. Le vrai CC garde au contraire un point de rupture de prompt caching API après le dernier outil natif — et c'est précisément pour le préserver qu'il trie natifs et MCP séparément.
- **Régressions d'observabilité et de garde** héritées du resserrement du code : `match_response` (lignes 364–372) échoue désormais en silence (request_id inconnu ou type incohérent ne produisent plus aucun message), et `run_review_plan` (lignes 645–655) ne vérifie plus que la requête est encore `pending` — un plan peut être « ré-approuvé » ou contredit après coup.
- **Les annotations de sûreté ne protègent rien** : `mcp__deploy__trigger` est marqué `(destructive)` mais s'exécute sans confirmation — le hook de permission de [[s03-permission]] n'est pas branché sur les outils MCP dans cette version.

## Liens

- Session précédente : [[s18-worktree-isolation]]
- Session suivante : [[s20-comprehensive]]
- Sessions liées : [[s02-tool-use]] (la mécanique de base des outils que MCP étend), [[s03-permission]] (où brancheraient les annotations readOnly/destructive), [[s10-system-prompt]] (la mémoïsation supprimée ici), [[s20-comprehensive]] (intègre MCP au harness complet)
