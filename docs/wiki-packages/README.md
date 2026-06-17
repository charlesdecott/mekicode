# Wiki — `packages/`

Documentation du code de `packages/` : back/logique (mekillm + mekicore + mekihub) + front
(**mekistudio** = chat + canvas, 3 modes). Ce que fait chaque fichier, ses fonctions et variables, et
surtout les **relations** entre eux.

> ⚠️ Restructure Sprint 1 : `packages/mekichat/` a été **déplacé** sous `packages/mekistudio/mekichat/`
> ; `mekistudio.md` décrit le package front complet (coquille 3 modes + canvas + chat embarqué).

> Numéros de ligne **indicatifs** (wiki rédigé à la main, il vieillit à chaque édition du code).
> La source fait foi.

## Sommaire des pages

| Page | Décrit |
|------|--------|
| [architecture.md](architecture.md) | **Vue d'ensemble.** Les deux paquets et leur dépendance (mekicore → mekillm), le format pivot OpenAI, le flux de données de bout en bout (REPL → `agent_loop` → `LLM.complete` → SDK openai → OpenRouter → normalisation → outils), et l'emplacement des données runtime (`.logs/` à la racine). À lire en premier. |
| [mekillm.md](mekillm.md) | **Le provider LLM** (`packages/mekillm/`). Détaille `config.py` (résolution de config), `client.py` (`LLM`, `complete` + `stream`, normalisation/réassemblage du flux, types `LLMResponse`/`ToolCall`/`Usage`), `observability.py` (`CallRecord`, `emit`, hooks, JSONL) et `__init__.py` (API publique + raccourci `complete`). Liste les variables d'environnement consommées. |
| [mekicore.md](mekicore.md) | **Le mini-harness** (`packages/mekicore/`). Détaille `tools.py` (six outils : `bash` + `read`/`write`/`edit`/`grep`/`glob` confinés au workspace via `_safe_path`, `TOOLS`, `DISPATCH`), `events.py` (événements), `base.py` (`run_agent` à événements + `agent_loop`, `dispatch_tools`), `main.py` (REPL, bootstrap `sys.path`). |
| [mekichat.md](mekichat.md) | **Le front web** (`packages/mekichat/`). Interface NiceGUI in-process, mode conversation type Discord. Détaille `sessions.py` (persistance JSON sous `.sessions/`), `static/mekichat.css` (thème Phosphore), `views.py` (helpers de rendu), `app.py` (page NiceGUI, port 8080). Phases 1-3 livrées : sessions + UI (1), chat + outil `bash` (2), streaming + markdown (3) ; puis **outils étendus** (blocs d'outils colorés/repliables pour les six outils, diff `edit`). Devenu adaptateur NiceGUI du hub. |
| [mekihub.md](mekihub.md) | **Le hub temps réel** (`packages/mekihub/`). Bus de session multi-utilisateur multi-canal : salle partagée, file FIFO auto-drain, pub/sub mémoire, adaptateurs de canal. Détaille `session.py` (couche session canonique : `Author`, `QueueItem`, `Session`, `SessionState`, `SessionStore`), `events.py` (13 events de salle + run **+ `PermissionRequested`**), `hub.py` (`PendingQueue`, `SessionHub`, worker asyncio, **`resolve_permission` / tier ask async**), `permissions_store.py` (surcharges projet), `adapters/discord.py`. |
| [mekistudio.md](mekistudio.md) | **Le front studio** (`packages/mekistudio/`, Sprint 1). Coquille **3 modes** (Chat / Canvas / Mix) regroupant le chat (`mekichat/` : `ChatComponent` réutilisable + accueil `/` + carte permission s15) et le **canvas** (`mekicanvas/` : modèle Node/Component pydantic, registry/parenting, nodes Kernel/Chat/Queue groupées par espace de travail, géométrie câbles 45° vendorée + pont `canvas.js` pan/zoom/comètes/**drag-resize-focus**). Entrée : `/studio`. |

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
├── mekichat/                → voir mekichat.md
│   ├── app.py               page NiceGUI "/" (index + _refresh) ; ui.run(port=8080) ; adaptateur NiceGUI du hub
│   ├── sessions.py          ré-export de mekihub.session (shim compat)
│   ├── views.py             render_message() (markdown), render_tool(), render_thread(), render_stream_bubble()…
│   └── static/
│       └── mekichat.css     thème cyberpunk Phosphore
└── mekihub/                 → voir mekihub.md
    ├── session.py           Author, QueueItem, Session (+add_user), SessionMeta, SessionState, SessionStore
    ├── events.py            13 events : Snapshot/PresenceChanged/QueueEnqueued/QueueItemDeleted/RunStarted/
    │                        MessagePosted/AgentDelta/AgentDone/ToolStarted/ToolFinished/RunFinished/RunError/Idle
    ├── hub.py               PendingQueue (FIFO supprimable) + SessionHub (join/leave/submit/delete_pending/
    │                        snapshot/subscribe) + worker asyncio (drain file → run_agent via to_thread)
    ├── main.py              entrypoint : build_hub() + main() (MEKIHUB_FRONT / MEKIHUB_DISCORD)
    └── adapters/
        └── discord.py       DiscordAdapter (canal→session, handle_message, _render_loop) + FakeDiscordClient
```
