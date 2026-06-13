# Architecture de `packages/`

## Quatre paquets, une dépendance

```
packages/
├── mekillm/   ← provider LLM généraliste, réutilisable, ne connaît PAS mekicore
├── mekicore/  ← mini-harness (boucle agent à événements + outils bash/read/write/edit/grep/glob) ; dépend de mekillm
├── mekichat/  ← adaptateur NiceGUI multi-utilisateur (présence, file d'attente, broadcast) ; importe mekihub
└── mekihub/   ← hub de session temps réel (salle partagée, file FIFO, pub/sub, adaptateurs de canal)
```

- **mekillm** est autonome : il ne sait rien d'un agent ni d'outils. Il prend des `messages`
  (format OpenAI) et rend une réponse normalisée. Il pourrait être importé par n'importe quel projet.
- **mekicore** est le consommateur : une boucle perception-action **à événements** (`run_agent`,
  le s01 adapté) qui appelle mekillm et exécute des outils ; `agent_loop` (REPL) est réexprimé dessus.
- **mekihub** est le **hub temps réel** : bus de conversation multi-utilisateur, multi-canal. Il
  gère les salles partagées (présence, file FIFO auto-drain, pub/sub mémoire) et pilote `mekicore.run_agent`
  (via `asyncio.to_thread`) dans un worker asyncio par session. Les adaptateurs de canal (NiceGUI,
  Discord…) s'y branchent via `SessionHub.subscribe` (async generator).
- **mekichat** est devenu un **adaptateur NiceGUI** du `SessionHub` : présence en temps réel,
  broadcast live des événements, UI de la file d'attente avec suppression.

La dépendance est **à sens unique** : `mekichat → mekihub → mekicore → mekillm`. Chaque couche ne
touche qu'à l'**interface publique** de la précédente — jamais à ses internes.

### Hub temps réel (mekihub)

`mekihub` introduit la notion de **salle partagée** : plusieurs utilisateurs (ou canaux) soumettent
des messages vers une même session via `SessionHub.submit`. Un **worker asyncio** par session draine
la file FIFO (`PendingQueue`) et pilote le générateur SYNC `mekicore.run_agent` step-by-step via
`await asyncio.to_thread(next, gen)`. Les événements mekicore sont traduits en événements de salle
(par `type(e).__name__`, pas `isinstance`, pour éviter l'ambiguïté des modules homonymes) et diffusés
à tous les abonnés en mémoire (`asyncio.Queue` par abonné). Les adaptateurs de canal (`DiscordAdapter`,
`mekichat/app.py`) s'y abonnent via `SessionHub.subscribe`, qui rend un générateur asynchrone
(`Snapshot` d'amorçage + deltas en continu).

### Comment l'import fonctionne (import par chemin)
`mekicore/main.py` ajoute `packages/` au `sys.path` avant d'importer mekillm :

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # → packages/
import mekillm
from base import agent_loop      # base.py / tools.py sont dans le même dossier (sys.path[0] par défaut)
from tools import DISPATCH, TOOLS
```

Les tests font la même chose depuis `tests/smoke_packages.py` (en remontant à la racine puis vers
`packages/`).

## Le format pivot : OpenAI

Tout `packages/` parle le **format function-calling OpenAI** (`messages`, `tools:[{type:"function"}]`,
`tool_calls`, messages `role:"tool"`). C'est la *lingua franca* d'OpenRouter, ollama et litellm.
Conséquence : aucun bloc `content`/`stop_reason` à la Anthropic ici — mekillm normalise la réponse
du SDK openai et mekicore réinjecte directement les messages OpenAI dans l'historique.

## Flux de données de bout en bout

```
                      packages/mekicore                         packages/mekillm
                ┌───────────────────────────┐        ┌──────────────────────────────────┐
 utilisateur ─▶ main.py (REPL)               │        │                                  │
                │  messages = [system, user] │        │                                  │
                │           │                │        │                                  │
                │           ▼                │        │                                  │
                │  base.agent_loop ──────────┼──▶ LLM.complete(messages, tools)          │
                │     (boucle while True)     │       │   ├─ config.resolve (clé/url/modèle)
                │           ▲                │        │   ├─ openai SDK → OpenRouter      │
                │           │                │        │   ├─ _normalize() → LLMResponse   │
                │           │                │◀───────┼───┤      (.text/.tool_calls/...)  │
                │  append resp.message       │        │   └─ finally: observability.emit  │
                │           │                │        │         → log + JSONL + hooks     │
                │   finish == "tool_calls" ? │        └──────────────────────────────────┘
                │     │oui            │non
                │     ▼               ▼
                │  dispatch_tools   return (réponse finale, affichée
                │     │              avec [heure · modèle])
                │     ▼
                │  tools.run_bash (handler du DISPATCH)
                │     │
                │     ▼
                │  messages += [{role:"tool", tool_call_id, content}]  ──▶ (reboucle)
                └───────────────────────────┘
```

### Le cycle multi-tours
1. `agent_loop` appelle `llm.complete(messages, tools)`.
2. La réponse assistant (`resp.message`, format OpenAI, éventuellement avec `tool_calls`) est
   ajoutée à l'historique.
3. Si `finish_reason == "tool_calls"`, `dispatch_tools` exécute chaque outil et produit un message
   `role:"tool"` par appel (corrélé par `tool_call_id`), ajouté à l'historique.
4. On reboucle : le modèle voit les résultats d'outils et continue, jusqu'à une réponse sans outil
   (`finish_reason != "tool_calls"`), qui termine le tour.

### Boucle à événements et front web
Le cycle ci-dessus existe en deux formes dans `base.py` : `agent_loop` (REPL console) est **réexprimé**
sur **`run_agent`**, un générateur qui **émet des événements** (`events.py` : `AssistantDelta`/`Done`,
`ToolStarted`/`Finished`, `ThinkingStarted`, `RunFinished`, `RunError`) au lieu d'imprimer. Le front
[mekichat](mekichat.md) consomme ce même `run_agent` — en **`stream=True`** (`llm.stream` →
`AssistantDelta` token par token) — pour rendre la conversation **en direct** dans le navigateur
(bulles markdown, blocs d'outils colorés/repliables par outil — glyphe + couleur, diff `edit` —,
caret de streaming), avec persistance des sessions.

## Données runtime
- mekillm écrit un **JSONL d'appels** dans `.logs/mekillm.jsonl` **à la racine du projet** (jamais
  dans `packages/`), surchargeable par `MEKILLM_LOG_FILE`. `packages/` ne contient que du code.
- mekicore n'écrit rien en propre ; ce sont **ses outils** qui écrivent là où l'agent le décide :
  `write`/`edit` **confinés au workspace** (défaut `cwd`, surchargeable par `MEKICORE_WORKSPACE`) ;
  `bash` **non confiné** (`cwd` du process).
- Config secrète : `.env` à la racine (lu par `load_dotenv` au moment de l'import de mekillm).

## Voir aussi
- [mekillm.md](mekillm.md) — détail du provider (`complete` / `stream`).
- [mekicore.md](mekicore.md) — détail du harness (`run_agent`, `events.py`).
- [mekichat.md](mekichat.md) — détail du front web NiceGUI / adaptateur hub.
- [mekihub.md](mekihub.md) — détail du hub temps réel (salle, file, pub/sub, adaptateurs).
