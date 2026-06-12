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
| [`wiki-packages/architecture.md`](wiki-packages/architecture.md) | Vue d'ensemble des deux paquets, format pivot OpenAI, flux de données complet (REPL → boucle → LLM → outils), et où vont les données runtime. |
| [`wiki-packages/mekillm.md`](wiki-packages/mekillm.md) | Le provider LLM : `config.py`, `client.py`, `observability.py`, `__init__.py` — symboles, types normalisés (`LLMResponse`/`ToolCall`/`Usage`/`CallRecord`), variables d'environnement et relations entre fonctions. |
| [`wiki-packages/mekicore.md`](wiki-packages/mekicore.md) | Le mini-harness : `tools.py`, `base.py`, `main.py` — l'outil `bash`, la boucle `agent_loop`, le dispatch des `tool_calls`, le REPL et le bootstrap d'import. |

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
