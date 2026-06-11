"""Runtime MCP (s21) : découverte stdio, enregistrement dynamique, cycle de vie propre.

Lit la section `mcp.servers` du config.yaml unique, lance chaque serveur en
sous-processus stdio, découvre ses outils et les enregistre dans le registre
de tools.py sous le nom `mcp__<serveur>__<outil>`.

Windows : le spawn de sous-processus asyncio exige le ProactorEventLoop —
c'est le défaut depuis Python 3.8, rien à configurer.
"""

from contextlib import AsyncExitStack
from typing import Any

from core import load_config, paint
from tools import register_tool

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    HAS_MCP = True
except ImportError:  # dégradation gracieuse : outils locaux seuls
    HAS_MCP = False

# État module : sessions actives, table de routage, pile de fermeture.
MCP_SESSIONS: dict[str, Any] = {}                 # serveur -> ClientSession
MCP_TOOL_MAP: dict[str, tuple[str, str]] = {}     # "mcp__srv__tool" -> (srv, tool)
_STACK: AsyncExitStack | None = None


def _make_handler(server_name: str, tool_name: str):
    """Fabrique l'async_fn d'un outil MCP (fermeture par outil, route call_tool)."""
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
    return _call


async def _connect_one(srv_cfg: dict) -> int:
    """Connecte UN serveur stdio et enregistre ses outils. Retourne leur nombre.

    # FIX(mekicode): sous-pile AsyncExitStack par serveur — la source appelait
    # __aenter__ à la main et ne fermait JAMAIS les transports stdio. Ici :
    # échec partiel -> la sous-pile referme tout de suite ; succès -> les
    # callbacks sont transférés dans _STACK, fermés par stop_mcp().
    """
    name = srv_cfg.get("name", "sans_nom")
    if name in MCP_SESSIONS:  # FIX(mekicode): homonyme = écrasement muet dans la source
        print(paint(f"  [MCP] {name}: nom déjà connecté, serveur ignoré", "yellow"))
        return 0
    if srv_cfg.get("transport", "stdio") != "stdio":
        print(paint(f"  [MCP] {name}: transport '{srv_cfg['transport']}' non supporté", "yellow"))
        return 0

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
    MCP_SESSIONS[name] = session

    for tool in tools:
        prefixed = f"mcp__{name}__{tool.name}"
        MCP_TOOL_MAP[prefixed] = (name, tool.name)
        register_tool(
            {
                "name": prefixed,
                "description": f"[{name}] {tool.description or tool.name}",
                "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
            },
            async_fn=_make_handler(name, tool.name),
        )
    print(paint(f"  [MCP] {name}: connecté ({len(tools)} outils)", "dim"))
    return len(tools)


async def start_mcp() -> int:
    """Démarre les serveurs de `mcp.servers` (config.yaml). Retourne le nb d'outils.

    Un serveur indisponible est loggué et n'empêche pas les autres de monter.
    À appeler depuis la même boucle/tâche asyncio que stop_mcp() (contrainte
    anyio : les cancel scopes du transport doivent se fermer là où ils ont ouvert).
    """
    global _STACK
    if not HAS_MCP:
        print(paint("[MCP] paquet 'mcp' absent (pip install mcp) — outils locaux seuls", "yellow"))
        return 0
    if _STACK is not None:  # déjà démarré : idempotent
        return len(MCP_TOOL_MAP)
    servers = (load_config().get("mcp") or {}).get("servers") or []
    if not servers:
        print(paint("[MCP] aucun serveur déclaré sous mcp.servers dans config.yaml", "dim"))
        return 0

    _STACK = AsyncExitStack()
    total = 0
    for srv in servers:
        try:
            total += await _connect_one(srv)
        except Exception as e:
            print(paint(f"  [MCP] échec connexion '{srv.get('name', '?')}': {e}", "red"))
    return total


async def stop_mcp() -> None:
    """Ferme transports et sessions via l'AsyncExitStack (ordre LIFO).

    # FIX(mekicode): la source ne fermait que les ClientSession ; ici aclose()
    # déroule aussi les stdio_client -> plus de sous-processus orphelins.
    """
    global _STACK
    if _STACK is None:
        return
    stack, _STACK = _STACK, None
    MCP_SESSIONS.clear()   # les handlers déjà enregistrés répondront "session inactive"
    MCP_TOOL_MAP.clear()
    try:
        await stack.aclose()
    except Exception as e:
        print(paint(f"[MCP] fermeture imparfaite : {e}", "yellow"))


def mcp_status() -> str:
    """Résumé lisible : serveurs connectés et outils exposés."""
    if not HAS_MCP:
        return "MCP indisponible (paquet 'mcp' non installé)."
    if not MCP_SESSIONS:
        return "MCP arrêté — aucun serveur connecté."
    lines = [f"MCP actif — {len(MCP_SESSIONS)} serveur(s), {len(MCP_TOOL_MAP)} outil(s) :"]
    for srv in MCP_SESSIONS:
        tools = [orig for s, orig in MCP_TOOL_MAP.values() if s == srv]
        lines.append(f"  - {srv}: {', '.join(tools) or '(aucun outil)'}")
    return "\n".join(lines)
