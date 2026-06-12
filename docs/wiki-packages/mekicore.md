# `packages/mekicore/` — mini-harness (s01 adapté)

Le s01 de claude-code-from-scratch (boucle perception-action + outil `bash`), réécrit au format
OpenAI et branché sur [mekillm](mekillm.md). Trois fichiers fins.

> Numéros de ligne indicatifs (source = vérité).

## Vue des fichiers et de leurs relations

```
main.py  ── bootstrap sys.path ──▶ import mekillm
   │       instancie mekillm.LLM(), boucle REPL
   │       passe TOOLS + DISPATCH (de tools.py) à ─┐
   ▼                                               │
base.py  ── run_agent(messages, llm, tools, dispatch, stream=False)  ── générateur d'événements
   │           │  llm.complete(...) ou llm.stream(...) ─▶ (mekillm)
   │           ▼  émet les dataclasses d'events.py (AssistantDelta/Done, Tool*, …)
   │        agent_loop(...)  ── réexprimé sur run_agent (REPL : rend les événements en print)
   ▼
events.py ── événements consommés par le REPL ou le front mekichat
tools.py  ── DISPATCH["bash"] ─▶ run_bash() ; TOOLS = schéma function-calling OpenAI
```

## `tools.py` — l'outil et son schéma
- `_ALWAYS_BLOCK` (l.8) : fragments de commande interdits (`rm -rf /`, `sudo`, fork bomb, …).
- `run_bash(command) -> str` (l.11) : `subprocess.run(shell=True)`, timeout 120 s, sortie
  `stdout+stderr` tronquée à 50k ; renvoie un message d'erreur (jamais d'exception) si bloqué/timeout.
- `TOOLS` (l.29) : **schéma au format function-calling OpenAI** —
  `[{"type":"function","function":{"name":"bash","description":...,"parameters":{json schema}}}]`.
  C'est ce que `LLM.complete` transmet au modèle.
- `DISPATCH` (l.45) : table `nom d'outil → handler(args: dict) -> str`. Ici `{"bash": ... run_bash(args["command"])}`.

`TOOLS` (ce que le modèle voit) et `DISPATCH` (ce qu'on exécute) sont les deux faces d'un même outil.

## `events.py` — événements de la boucle agent
Dataclasses émises par `run_agent`, consommées par le REPL (`agent_loop`) ou le front
[mekichat](mekichat.md) :
- `ThinkingStarted` : un tour commence (appel LLM en cours).
- `AssistantDelta(text)` : fragment de texte assistant (**streaming**).
- `AssistantDone(text)` : texte complet d'un tour.
- `ToolStarted(id, name, args)` / `ToolFinished(id, name, output)` : un outil démarre / a répondu.
- `RunFinished` : la boucle est terminée. · `RunError(message)` : l'appel LLM a échoué (arrêt propre).

## `base.py` — les boucles et le dispatch
- `dispatch_tools(tool_calls, dispatch) -> list` : pour chaque `ToolCall`, récupère le handler
  (outil inconnu ⇒ message d'erreur, pas de crash), exécute `handler(tc.arguments)` (exception
  attrapée ⇒ message d'erreur), affiche en console, et renvoie un message
  `{"role":"tool","tool_call_id": tc.id, "content": str(output)}` par appel. **Conservé** pour
  l'API directe / le test ; `run_agent` a sa propre boucle (pour émettre les événements).
- **`run_agent(messages, llm, tools, dispatch, *, stream=False)`** : la boucle « penser-agir » **à
  événements** (générateur ; modifie `messages` en place). À chaque tour :
  1. émet `ThinkingStarted` ;
  2. obtient la réponse — `llm.complete(...)` (un seul `AssistantDone`) ou, si `stream=True`,
     `llm.stream(...)` (un `AssistantDelta` par token puis un `AssistantDone`) ; exception ⇒ `RunError` ;
  3. `messages.append(resp.message)` ;
  4. si `finish_reason != "tool_calls"` ⇒ `RunFinished`, fin (garde : `tool_calls` vide ⇒ `RunError`) ;
  5. sinon, par outil : `ToolStarted` → exécute le handler → append du message `role:"tool"` →
     `ToolFinished`, puis on reboucle.
- `agent_loop(messages, llm, tools, dispatch) -> None` : le **REPL console**, désormais **réexprimé
  sur `run_agent`** (non-streaming) — il consomme les événements et les rend en `print`
  (`> Thinking...`, en-tête `[heure · modèle]`, `[outil]`, erreurs). Comportement de boucle inchangé.

Détail du cycle multi-tours : voir [architecture.md](architecture.md).

## `main.py` — REPL et bootstrap
- **Bootstrap** (l.9) : `sys.path.insert(0, parent.parent)` ajoute `packages/` au path pour rendre
  `import mekillm` résoluble en lancement direct ; `base` et `tools` sont importables car leur
  dossier (`mekicore/`) est déjà `sys.path[0]`.
- `SYSTEM` (l.15) : prompt système (`"You are a coding agent at <cwd>. ... Act, don't explain."`).
- `main()` (l.18) : instancie `mekillm.LLM()` une fois, démarre l'historique avec le message
  `system`, puis REPL : prompt `mekicore >>`, append du message `user`, `agent_loop`, affichage,
  sortie propre sur `q`/`exit`/`quit` ou `Ctrl-C`/`Ctrl-D`.

## Lancer
```
python packages/mekicore/main.py     # ou ./start.sh  /  .\start.ps1 (depuis la racine)
```
Nécessite une clé dans le `.env` racine (voir `.env.example` : `OPENROUTER_API_KEY`, `MEKILLM_MODEL`).

## Relations entrantes / sortantes
- Dépend de [mekillm](mekillm.md) (`LLM.complete`/`stream`, types `LLMResponse`/`ToolCall`).
- `run_agent` + `events.py` sont consommés par le front [mekichat](mekichat.md) (rendu en direct des
  bulles, blocs `[bash]`, streaming).
- Non-régression réseau-free : `tests/smoke_packages.py` (`run_agent`, événements, streaming).
