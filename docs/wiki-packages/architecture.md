# Architecture de `packages/`

## Deux paquets, une dépendance

```
packages/
├── mekillm/   ← provider LLM généraliste, réutilisable, ne connaît PAS mekicore
└── mekicore/  ← mini-harness ; dépend de mekillm (import par chemin)
```

- **mekillm** est autonome : il ne sait rien d'un agent ni d'outils. Il prend des `messages`
  (format OpenAI) et rend une réponse normalisée. Il pourrait être importé par n'importe quel projet.
- **mekicore** est le consommateur : une boucle perception-action (le s01 de claude-code-from-scratch
  adapté) qui appelle mekillm et exécute des outils.

La dépendance est **à sens unique** : `mekicore → mekillm`. mekicore ne touche qu'à l'**interface
publique** de mekillm (`LLM`, `LLMResponse`, `ToolCall`) — jamais à ses internes.

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

## Données runtime
- mekillm écrit un **JSONL d'appels** dans `.logs/mekillm.jsonl` **à la racine du projet** (jamais
  dans `packages/`), surchargeable par `MEKILLM_LOG_FILE`. `packages/` ne contient que du code.
- mekicore n'écrit rien en propre ; seul l'outil `bash` écrit là où l'agent le décide (`cwd`).
- Config secrète : `.env` à la racine (lu par `load_dotenv` au moment de l'import de mekillm).

## Voir aussi
- [mekillm.md](mekillm.md) — détail du provider.
- [mekicore.md](mekicore.md) — détail du harness.
