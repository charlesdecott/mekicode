"""s19 · Plugin MCP — outils externes, protocole standard.

Concept : de s01 à s18, chaque outil de l'agent a été écrit à la main. MCP
(Model Context Protocol) fournit le protocole standard : un serveur expose
tools/list (découverte) et tools/call (invocation) ; côté agent, connect_mcp
instancie un MCPClient (mock pédagogique de cette couche transport), et
assemble_tool_pool fusionne les outils découverts avec BUILTIN_TOOLS sous le
namespace `mcp__{server}__{tool}` — noms assainis par normalize_mcp_name,
schémas traduits inputSchema (MCP) → input_schema (API Anthropic), et
handlers en lambdas à arguments par défaut qui figent client/outil courants
(le piège classique de capture tardive des closures Python).

Mapping vers l'original (inspiration/learn-claude-code/s19_mcp_plugin/
code.py) : MCPClient, mcp_clients, normalize_mcp_name, MOCK_SERVERS (docs en
lecture seule + deploy destructif), connect_mcp, assemble_tool_pool et
run_connect_mcp vivent dans shared.py (section « MCP »). Ce fichier ne garde
que le délta : la démo découverte → assemblage → invocation, SANS LLM — les
handlers du pool sont appelés directement, comme le ferait agent_loop.
"""

import json

from shared import (BUILTIN_TOOLS, MCPClient, assemble_system_prompt,
                    assemble_tool_pool, connect_mcp, mcp_clients,
                    normalize_mcp_name, update_context)


def show_pool(label):
    """Assemble le pool courant et liste ses outils MCP. Retourne handlers."""
    tools, handlers = assemble_tool_pool()
    mcp_names = [t["name"] for t in tools if t["name"].startswith("mcp__")]
    print(f"\n{label} : {len(tools)} outils "
          f"({len(BUILTIN_TOOLS)} natifs + {len(mcp_names)} MCP)")
    for name in mcp_names:
        print(f"   {name}")
    return tools, handlers


def main():
    print("s19 : plugin MCP — découverte, assemblage, invocation (sans LLM)")
    show_pool("1. Pool initial")

    # 2. Connexion = instanciation du client + découverte (mock de
    # tools/list). Idempotente, et l'erreur liste les serveurs disponibles.
    print("\n2. connect_mcp :")
    print("   " + connect_mcp("docs"))
    print("   " + connect_mcp("docs"))             # déjà connecté
    print("   " + connect_mcp("jira"))             # inconnu → liste utile
    print("   " + connect_mcp("deploy"))

    tools, handlers = show_pool("3. Pool après connexion")

    # 4. La traduction de schéma : inputSchema (camelCase MCP) est devenue
    # input_schema (snake_case Anthropic) dans la définition assemblée.
    search = next(t for t in tools if t["name"] == "mcp__docs__search")
    print("\n4. Définition traduite pour l'API :")
    print(json.dumps(search, indent=2))

    # 5. Invocation directe des handlers (exactement ce que fait agent_loop).
    # Chaque lambda a figé son client et son outil par arguments par défaut :
    # quatre appels, quatre serveurs/outils distincts, aucun cross-talk.
    print("\n5. Invocations via le pool :")
    for name, args in [
        ("mcp__docs__search", {"query": "agent loop"}),
        ("mcp__docs__get_version", {}),
        ("mcp__deploy__status", {"service": "api"}),
        ("mcp__deploy__trigger", {"service": "api"}),
    ]:
        print(f"   {name}({args}) → {handlers[name](**args)}")

    # 6. MCPClient en direct : un « serveur » maison au nom à assainir.
    # call_tool capture les erreurs en texte `MCP error: ...` (jamais
    # d'exception qui remonte — comme une réponse d'erreur JSON-RPC).
    meteo = MCPClient("météo!")
    meteo.register(
        tool_defs=[{"name": "prévision", "description": "Prévision locale.",
                    "inputSchema": {"type": "object",
                                    "properties": {"ville": {"type": "string"}},
                                    "required": ["ville"]}}],
        handlers={"prévision": lambda ville: f"[météo] {ville} : 21 °C"})
    mcp_clients["météo!"] = meteo
    print(f"\n6. normalize_mcp_name('météo!') → "
          f"{normalize_mcp_name('météo!')!r}")
    print(f"   call_tool inconnu → {meteo.call_tool('inconnu', {})}")
    _, handlers = show_pool("   Pool avec le serveur maison")
    custom = (f"mcp__{normalize_mcp_name('météo!')}"
              f"__{normalize_mcp_name('prévision')}")
    print(f"   {custom}(ville='Lyon') → {handlers[custom](ville='Lyon')}")

    # 7. Le system prompt vivant annonce les serveurs connectés au modèle —
    # c'est pourquoi il est ré-assemblé à chaque tour, sans mémoïsation.
    prompt = assemble_system_prompt(update_context({}, []))
    line = next((l for l in prompt.splitlines()
                 if l.startswith("Connected MCP servers")), "(absent)")
    print(f"\n7. Dans le system prompt : {line}")


if __name__ == "__main__":
    main()
