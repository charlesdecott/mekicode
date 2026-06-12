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
base.py  ── agent_loop(messages, llm, tools, dispatch)
   │           │  llm.complete(...) ─▶ (mekillm)
   │           ▼  dispatch_tools(resp.tool_calls, dispatch)
   ▼                     │  appelle ─▶ handler du DISPATCH
tools.py ── DISPATCH["bash"] ─▶ run_bash() ; TOOLS = schéma function-calling OpenAI
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

## `base.py` — la boucle et le dispatch
- `dispatch_tools(tool_calls, dispatch) -> list` (l.11) : pour chaque `ToolCall`,
  - récupère le handler dans `dispatch` (outil inconnu ⇒ message d'erreur, pas de crash) ;
  - exécute `handler(tc.arguments)` (exception attrapée ⇒ message d'erreur) ;
  - affiche l'appel et un extrait de sortie en console ;
  - renvoie un message `{"role":"tool","tool_call_id": tc.id, "content": str(output)}` par appel
    (le `tool_call_id` corrèle résultat ↔ appel côté modèle).
- `agent_loop(messages, llm, tools, dispatch) -> None` (l.30) : la boucle `while True` (modifie
  `messages` en place) —
  1. `resp = llm.complete(messages, tools=tools)` ;
  2. `messages.append(resp.message)` (le message assistant brut OpenAI) ;
  3. si `resp.text` : affiche **`[heure · modèle] <texte>`** (l.42-43 ; modèle lu sur `resp.raw.model`,
     repli sur `llm.model`) ;
  4. `if resp.finish_reason != "tool_calls": return` (réponse finale) ;
  5. sinon `messages += dispatch_tools(resp.tool_calls, dispatch)` et on reboucle.

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
- Dépend de [mekillm](mekillm.md) (`LLM`, et indirectement les `ToolCall` qu'il consomme).
- Non-régression réseau-free : `tests/smoke_packages.py`.
