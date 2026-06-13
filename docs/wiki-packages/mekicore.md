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
tools.py  ── DISPATCH[nom] ─▶ run_bash()/read_file()/… ; TOOLS = schémas function-calling OpenAI
            outils fichiers confinés au workspace via _safe_path ; bash non confiné
```

## `tools.py` — les outils et leurs schémas
**Six outils** : `bash` + cinq outils de fichiers (`read`/`write`/`edit`/`grep`/`glob`). Les outils de
fichiers sont **confinés à un workspace** ; `bash` reste l'échappatoire non confinée. Tous renvoient
**une chaîne** (jamais d'exception qui remonte) ; en cas de problème, une chaîne `Error: …` que l'agent
voit et peut corriger.

**Confinement (l.17-28).**
- `_workspace() -> Path` (l.17) : racine du workspace, **lue à chaque appel** (pas figée à l'import,
  pour la testabilité) — `MEKICORE_WORKSPACE` sinon `cwd`.
- `_safe_path(p) -> Path` (l.22) : résout `p` (relatif **ou** absolu) sous la racine ; lève
  `ValueError` s'il s'en échappe (`../…`, chemin absolu hors racine). Utilisé par les 5 outils
  fichiers, **pas** par `bash`.

**`bash`.**
- `_ALWAYS_BLOCK` (l.13) : fragments interdits (`rm -rf /`, `sudo`, fork bomb, …).
- `run_bash(command) -> str` (l.31) : `subprocess.run(shell=True)`, timeout 120 s, sortie
  `stdout+stderr` tronquée à 50k ; message d'erreur (jamais d'exception) si bloqué/timeout. **Non
  confiné** (`cwd` du process).

**Outils de fichiers (confinés).**
- `read_file(path)` (l.48) : lit un fichier texte (`errors="replace"`, tronqué à 50k) ; `Error` si
  introuvable / hors workspace.
- `write_file(path, content)` (l.62) : crée les dossiers parents puis écrit/écrase ; renvoie
  `écrit N caractères dans <path>`.
- `edit_file(path, old, new)` (l.76) : **str-replace** d'un fragment **exact et unique** ; `Error` si
  0 occurrence (introuvable), 2+ (ambigu), ou fichier non-UTF-8 / illisible.
- `grep_files(pattern, path=".")` (l.100) : regex sur les fichiers texte sous `path` ; lignes
  `relpath:ligne: contenu` (≤ 200, binaires sautés) ; `Error: regex invalide` sinon.
- `glob_files(pattern)` (l.131) : liste les fichiers d'un motif (`**/*.py`…) sous la racine, chemins
  relatifs triés (≤ 1000) ; **ignore les correspondances qui s'échappent** du workspace (`../`, absolus).

**Enregistrement.**
- `_tool(name, desc, props, required)` (l.148) : fabrique un schéma function-calling OpenAI.
- `TOOLS` (l.157) : la liste des **six** schémas (ce que le modèle voit).
- `DISPATCH` (l.173) : table `nom → handler(args: dict) -> str` (les six handlers).

`TOOLS` (ce que le modèle voit) et `DISPATCH` (ce qu'on exécute) sont les deux faces des outils.
`run_agent` (base.py) dispatche **génériquement par nom** : ajouter un outil = l'ajouter ici, rien
d'autre à toucher.

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
- `SYSTEM` (l.15) : prompt système — annonce les outils disponibles (`"You are a coding agent at
  <cwd>. Tools: bash, read, write, edit (str-replace), grep, glob. The file tools are confined to the
  workspace. Act, don't explain."`).
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
  bulles, blocs d'outils génériques `▣ <nom>`, streaming).
- Non-régression réseau-free : `tests/smoke_packages.py` (`run_agent`, événements, streaming).
