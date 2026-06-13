# Wiki — `packages/`

Documentation du code de `packages/` (mekillm + mekicore + mekichat) : ce que fait chaque fichier,
ses fonctions et variables, et surtout les **relations** entre eux.

> Numéros de ligne **indicatifs** (wiki rédigé à la main, il vieillit à chaque édition du code).
> La source fait foi.

## Sommaire des pages

| Page | Décrit |
|------|--------|
| [architecture.md](architecture.md) | **Vue d'ensemble.** Les deux paquets et leur dépendance (mekicore → mekillm), le format pivot OpenAI, le flux de données de bout en bout (REPL → `agent_loop` → `LLM.complete` → SDK openai → OpenRouter → normalisation → outils), et l'emplacement des données runtime (`.logs/` à la racine). À lire en premier. |
| [mekillm.md](mekillm.md) | **Le provider LLM** (`packages/mekillm/`). Détaille `config.py` (résolution de config), `client.py` (`LLM`, `complete` + `stream`, normalisation/réassemblage du flux, types `LLMResponse`/`ToolCall`/`Usage`), `observability.py` (`CallRecord`, `emit`, hooks, JSONL) et `__init__.py` (API publique + raccourci `complete`). Liste les variables d'environnement consommées. |
| [mekicore.md](mekicore.md) | **Le mini-harness** (`packages/mekicore/`). Détaille `tools.py` (six outils : `bash` + `read`/`write`/`edit`/`grep`/`glob` confinés au workspace via `_safe_path`, `TOOLS`, `DISPATCH`), `events.py` (événements), `base.py` (`run_agent` à événements + `agent_loop`, `dispatch_tools`), `main.py` (REPL, bootstrap `sys.path`). |
| [mekichat.md](mekichat.md) | **Le front web** (`packages/mekichat/`). Interface NiceGUI in-process, mode conversation type Discord. Détaille `sessions.py` (persistance JSON sous `.sessions/`), `static/mekichat.css` (thème Phosphore), `views.py` (helpers de rendu), `app.py` (page NiceGUI, port 8080). Phases 1-3 livrées : sessions + UI (1), chat + outil `bash` (2), streaming + markdown (3) ; puis **outils étendus** (blocs d'outils colorés/repliables pour les six outils, diff `edit`). |

## Carte rapide des fichiers

```
packages/
├── mekillm/                 → voir mekillm.md
│   ├── __init__.py          API publique : LLM, complete(), LLMResponse, ToolCall, Usage, observe
│   ├── config.py            resolve() : args > .env > défauts
│   ├── client.py            LLM.complete()/stream(), _normalize(), _consume_stream() ; dataclasses de réponse
│   └── observability.py     CallRecord, emit(), add_hook(), JSONL
├── mekicore/                → voir mekicore.md
│   ├── tools.py             run_bash() + read/write/edit/grep/glob (confinés via _safe_path), TOOLS (schéma OpenAI), DISPATCH
│   ├── events.py            ThinkingStarted/AssistantDelta/AssistantDone/ToolStarted/Finished/RunFinished/RunError
│   ├── base.py              run_agent() (boucle à événements), agent_loop(), dispatch_tools()
│   └── main.py              REPL + bootstrap import mekillm
└── mekichat/                → voir mekichat.md
    ├── app.py               page NiceGUI "/" (index + _refresh) ; ui.run(port=8080)
    ├── sessions.py          SessionStore.create/save/load/delete/list ; JSON sous .sessions/ (racine)
    ├── views.py             render_message() (markdown), render_tool(), render_thread(), render_stream_bubble()…
    └── static/
        └── mekichat.css     thème cyberpunk Phosphore
```
