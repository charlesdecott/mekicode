# Documentation — mekicode

Sommaire de la documentation du projet. Pour l'état d'avancement et la feuille de route, voir
[`../ROADMAP.md`](../ROADMAP.md).

## Sommaire

### Wiki de `packages/` — [`wiki-packages/`](wiki-packages/README.md)
Documentation du code de `packages/` : rôle de chaque fichier, fonctions, variables et **relations**
entre eux. Commencer par le sommaire du wiki : [`wiki-packages/README.md`](wiki-packages/README.md).

| Page | Contenu |
|------|---------|
| [`wiki-packages/README.md`](wiki-packages/README.md) | Sommaire du wiki : décrit chaque page ci-dessous. |
| [`wiki-packages/architecture.md`](wiki-packages/architecture.md) | Vue d'ensemble des paquets, format pivot OpenAI, flux de données complet (REPL/front → boucle à événements → LLM → outils), et où vont les données runtime. |
| [`wiki-packages/mekillm.md`](wiki-packages/mekillm.md) | Le provider LLM : `config.py`, `client.py` (`complete` + `stream`), `observability.py`, `__init__.py` — types normalisés (`LLMResponse`/`ToolCall`/`Usage`/`CallRecord`), variables d'environnement et relations. |
| [`wiki-packages/mekicore.md`](wiki-packages/mekicore.md) | Le mini-harness : `tools.py`, `events.py`, `base.py` (`run_agent` à événements + `agent_loop`), `main.py` — les six outils (`bash` + `read`/`write`/`edit`/`grep`/`glob` confinés au workspace), le dispatch des `tool_calls`, le REPL et le bootstrap d'import. |
| [`wiki-packages/mekichat.md`](wiki-packages/mekichat.md) | Le front web NiceGUI : `sessions.py`, `views.py`, `app.py`, le thème Phosphore — chat branché sur l'agent (outils en blocs colorés/repliables par outil + diff `edit`, streaming, markdown), sessions persistées. Devenu adaptateur NiceGUI du hub temps réel. |
| [`wiki-packages/mekihub.md`](wiki-packages/mekihub.md) | Le hub temps réel : `session.py` (couche session canonique : `Author`, `QueueItem`, `Session`, `SessionState`, `SessionStore`), `events.py` (13 events), `hub.py` (`PendingQueue`, `SessionHub`, worker asyncio), `adapters/discord.py` (`DiscordAdapter`). Bus de session multi-utilisateur multi-canal. |

### Specs & plans — [`superpowers/`](superpowers/)
Artefacts de conception (historique daté, ne se périment pas) :

| Dossier | Contenu |
|---------|---------|
| [`superpowers/specs/`](superpowers/specs/) | Specs de conception validées (ex. design de `packages/`). |
| [`superpowers/plans/`](superpowers/plans/) | Plans d'implémentation détaillés, tâche par tâche. |

## Conventions
- Tout en **français** (comme le reste du projet).
- Le wiki documente le code avec des numéros de ligne **indicatifs** (rédigé à la main : vérifier la
  source en cas de doute, les ancres bougent à chaque édition).
- `CLAUDE.md` (racine) renvoie ici pour la documentation détaillée.
