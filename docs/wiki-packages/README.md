# Wiki — `packages/`

Documentation du code de `packages/` (mekillm + mekicore) : ce que fait chaque fichier, ses
fonctions et variables, et surtout les **relations** entre eux.

> Numéros de ligne **indicatifs** (wiki rédigé à la main, il vieillit à chaque édition du code).
> La source fait foi.

## Sommaire des pages

| Page | Décrit |
|------|--------|
| [architecture.md](architecture.md) | **Vue d'ensemble.** Les deux paquets et leur dépendance (mekicore → mekillm), le format pivot OpenAI, le flux de données de bout en bout (REPL → `agent_loop` → `LLM.complete` → SDK openai → OpenRouter → normalisation → outils), et l'emplacement des données runtime (`.logs/` à la racine). À lire en premier. |
| [mekillm.md](mekillm.md) | **Le provider LLM** (`packages/mekillm/`). Détaille `config.py` (résolution de config), `client.py` (`LLM`, `complete`, normalisation, types `LLMResponse`/`ToolCall`/`Usage`), `observability.py` (`CallRecord`, `emit`, hooks, JSONL) et `__init__.py` (API publique + raccourci `complete`). Liste les variables d'environnement consommées. |
| [mekicore.md](mekicore.md) | **Le mini-harness** (`packages/mekicore/`). Détaille `tools.py` (outil `bash`, `TOOLS`, `DISPATCH`), `base.py` (`agent_loop`, `dispatch_tools` et le cycle OpenAI à plusieurs tours), `main.py` (REPL, bootstrap `sys.path`, en-tête console heure + modèle). |

## Carte rapide des fichiers

```
packages/
├── mekillm/                 → voir mekillm.md
│   ├── __init__.py          API publique : LLM, complete(), LLMResponse, ToolCall, Usage, observe
│   ├── config.py            resolve() : args > .env > défauts
│   ├── client.py            LLM.complete(), _normalize(), _message_dict() ; dataclasses de réponse
│   └── observability.py     CallRecord, emit(), add_hook(), JSONL
└── mekicore/                → voir mekicore.md
    ├── tools.py             run_bash(), TOOLS (schéma OpenAI), DISPATCH
    ├── base.py              agent_loop(), dispatch_tools()
    └── main.py              REPL + bootstrap import mekillm
```
