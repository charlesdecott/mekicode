---
title: "s06 · Subagent"
session: 06
phase: "Fondamentaux"
fichier: "inspiration/learn-claude-code/s06_subagent/code.py"
lignes: 384
tags: [subagent, isolation-de-contexte, task-tool, delegation]
prev: "s05-todo-write"
next: "s07-skill-loading"
---

# s06 · Subagent

> **En une phrase** : un outil `task` permet à l'agent de déléguer un sous-problème à un sous-agent doté d'un `messages[]` vierge — seul le résumé final remonte, tous les pas intermédiaires sont jetés.

## Rôle dans le harness

Le README de la session pose le problème ainsi : l'agent corrige un bug, lit 30 fichiers pour tracer une chaîne d'appels, accumule 120 entrées dans `messages` — dont l'écrasante majorité sont des étapes intermédiaires sans rapport avec l'objectif final. Ces étapes occupent le contexte et rendent l'agent « de plus en plus oublieux » : il ne se souvient plus du problème d'origine. La métaphore du README : quand vous tracez une chaîne d'appels, vous ouvrez un nouveau terminal ; une fois fini, vous le fermez et notez la conclusion. L'agent a besoin de la même capacité.

La solution : *« Break large tasks small, each with clean context »*. Le nouvel outil `task` lance `spawn_subagent()`, qui crée une conversation **fraîche** (`messages = [{"role": "user", "content": description}]`), exécute sa propre boucle agentique (jusqu'à 30 tours), puis ne renvoie au parent **que le texte final**. L'historique du sous-agent est jeté ; seuls les effets de bord sur le disque (fichiers écrits, commandes exécutées) persistent.

Trois décisions de design structurent le fichier : isolation de contexte (messages frais), retour de la seule conclusion (`extract_text` du dernier message), et interdiction de récursion (le sous-agent n'a pas l'outil `task`). Quatrième point crucial : **l'isolation de contexte n'est pas une isolation de permissions** — les appels d'outils du sous-agent passent toujours par les hooks `PreToolUse`/`PostToolUse` de [[s04-hooks]].

Dans le vrai Claude Code, le mécanisme est plus riche (détail dans le README) : trois modes d'exécution (subagent normal, *fork subagent* qui partage le prompt cache via `buildForkedMessages()`, general-purpose), un `readFileState` cloné du parent, une protection anti-récursion plus nuancée, le *permission bubbling* et des sous-agents asynchrones (`run_in_background`). La version pédagogique garde volontairement le seul mode synchrone à contexte frais.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–29 | Docstring | Schéma ASCII parent/subagent, liste des changements vs s05 |
| 31–45 | Imports & env | `readline`, `anthropic`, `dotenv`, purge de `ANTHROPIC_AUTH_TOKEN` |
| 47–50 | Globals | `WORKDIR`, `client`, `MODEL`, `CURRENT_TODOS` |
| 52–62 | Prompts système | `SYSTEM` (parent) et `SUB_SYSTEM` (sous-agent) |
| 65–175 | Outils s02–s05 | `safe_path` … `run_todo_write`, `TOOLS`, `TOOL_HANDLERS` |
| 178–257 | **NOUVEAU s06** | `SUB_TOOLS`, `SUB_HANDLERS`, `extract_text`, `spawn_subagent`, enregistrement de `task` |
| 260–308 | Hooks s04 | `HOOKS`, `register_hook`, `trigger_hooks`, 4 hooks et leur enregistrement |
| 311–362 | Boucle | `rounds_since_todo`, `agent_loop` (identique à s05) |
| 365–383 | `__main__` | REPL avec hooks `UserPromptSubmit` |

## Constantes et configuration

- `WORKDIR = Path.cwd()` (ligne 47), `client` (48), `MODEL = os.environ["MODEL_ID"]` (49), `CURRENT_TODOS` (50) — repris de [[s05-todo-write]].
- `SYSTEM` (lignes 52–55) — modifié : il annonce désormais la délégation : `"For complex sub-problems, use the task tool to spawn a subagent."`
- `SUB_SYSTEM` (lignes 58–62) — **nouveau** : le prompt système du sous-agent. Il exige un résumé concis et interdit explicitement la délégation : `"Complete the task you were given, then return a concise summary. Do not delegate further."`
- `TOOLS` (lignes 157–170) et `TOOL_HANDLERS` (172–175) — les 6 outils de s05 ; `task` y est ajouté dynamiquement aux lignes 252–257.
- `SUB_TOOLS` (lignes 182–193) — **nouveau** : les 5 outils du sous-agent (`bash`, `read_file`, `write_file`, `edit_file`, `glob`). Le commentaire ligne 194 dit tout : `# NO "task" tool — prevent recursive spawning`. Détail : le `read_file` du sous-agent n'expose pas le paramètre `limit` que possède celui du parent.
- `SUB_HANDLERS` (lignes 196–199) — **nouveau** : table de dispatch du sous-agent, sans `todo_write` ni `task`.
- `HOOKS` (264), `DENY_LIST` (276), `rounds_since_todo` (315) — repris de [[s04-hooks]] et [[s05-todo-write]].

## Les fonctions, une à une

### `safe_path(p)` — lignes 69–73
Confinement des chemins dans `WORKDIR` (resolve + `is_relative_to`). Reprise de [[s02-tool-use]] sans modification.

### `run_bash(command)` — lignes 75–82
Exécute une commande shell (timeout 120 s, sortie tronquée à 50 000 caractères). Reprise de [[s02-tool-use]] sans modification.

### `run_read(path, limit=None)` — lignes 84–91
Lit un fichier, avec troncature optionnelle. Reprise de [[s02-tool-use]] sans modification.

### `run_write(path, content)` — lignes 93–100
Écrit un fichier en créant les dossiers parents. Reprise de [[s02-tool-use]] sans modification.

### `run_edit(path, old_text, new_text)` — lignes 102–111
Remplacement exact d'un texte, une seule occurrence. Reprise de [[s02-tool-use]] sans modification.

### `run_glob(pattern)` — lignes 113–122
Recherche de fichiers par motif glob, filtrée dans `WORKDIR`. Reprise de [[s02-tool-use]] sans modification.

### `_normalize_todos(todos)` — lignes 124–142
Validation/normalisation de la liste de todos (accepte une chaîne JSON ou un littéral Python). Reprise de [[s05-todo-write]] sans modification.

### `run_todo_write(todos)` — lignes 144–155
Met à jour `CURRENT_TODOS` et affiche la liste avec icônes ANSI. Reprise de [[s05-todo-write]] sans modification.

### `extract_text(content)` — lignes 201–205
**Nouvelle** petite fonction utilitaire, mais indispensable au mécanisme de retour du sous-agent.

```python
def extract_text(content) -> str:
    """Extract text from message content blocks."""
    if not isinstance(content, list):
        return str(content)
    return "\n".join(getattr(b, "text", "") for b in content if getattr(b, "type", None) == "text")
```

- Ligne 203–204 : si le contenu n'est pas une liste (p. ex. une simple chaîne), on le renvoie tel quel.
- Ligne 205 : on concatène le `.text` des blocs de type `text`. L'usage de `getattr(b, "type", None)` est délibéré : les blocs **assistant** sont des objets du SDK Anthropic (attributs `type`/`text`), tandis que les blocs **tool_result** stockés côté user sont des `dict` Python — `getattr` sur un dict renvoie la valeur par défaut, donc un message user composé de tool_results donne `""`. C'est précisément ce comportement qui déclenche le repli de fin de `spawn_subagent`.

### `spawn_subagent(description)` — lignes 207–249
**Le cœur de la session.** Une boucle agentique complète, miniature, avec son propre contexte.

```python
def spawn_subagent(description: str) -> str:
    """Spawn a subagent with fresh messages[], return summary only."""
    print(f"\n\033[35m[Subagent spawned]\033[0m")
    messages = [{"role": "user", "content": description}]  # fresh context

    for _ in range(30):  # safety limit
        response = client.messages.create(
            model=MODEL, system=SUB_SYSTEM,
            messages=messages, tools=SUB_TOOLS, max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason != "tool_use":
            break
```

- Ligne 210 : le `messages[]` **frais** — la description de la tâche est le seul contenu. Rien de l'historique parent ne fuit vers l'enfant (et inversement).
- Ligne 212 : `for _ in range(30)` au lieu du `while True` du parent — un sous-agent qui boucle ne peut pas consommer l'API indéfiniment.
- Lignes 213–216 : même client, même modèle, mais `SUB_SYSTEM` et `SUB_TOOLS` — prompt et outils restreints.

```python
        results = []
        for block in response.content:
            if block.type == "tool_use":
                # Issue 1: subagent also runs hooks (permissions apply)
                blocked = trigger_hooks("PreToolUse", block)
                if blocked:
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": str(blocked)})
                    continue
                handler = SUB_HANDLERS.get(block.name)
                output = handler(**block.input) if handler else f"Unknown: {block.name}"
                trigger_hooks("PostToolUse", block, output)
                print(f"  \033[90m[sub] {block.name}: {str(output)[:100]}\033[0m")
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": output})
        messages.append({"role": "user", "content": results})
```

- Lignes 224–228 : le sous-agent passe par les **mêmes hooks globaux** que le parent (le commentaire `Issue 1` du code le souligne) : la deny-list de `permission_hook` s'applique. Isolation de contexte ≠ isolation de sécurité.
- Ligne 229 : dispatch via `SUB_HANDLERS` — un appel à `task` tomberait dans `Unknown: task`, double sécurité avec l'absence de `task` dans `SUB_TOOLS`.
- Ligne 232 : chaque appel d'outil du sous-agent s'affiche préfixé `[sub]`, tronqué à 100 caractères — observabilité sans pollution.

```python
    # Issue 5: fallback if safety limit hit during tool_use
    result = extract_text(messages[-1]["content"])
    if not result:
        # last message is tool_result, look backwards for assistant text
        for msg in reversed(messages):
            if msg["role"] == "assistant":
                result = extract_text(msg["content"])
                if result:
                    break
        if not result:
            result = "Subagent stopped after 30 turns without final answer."
    print(f"\033[35m[Subagent done]\033[0m")
    return result  # only summary, entire message history discarded
```

- Ligne 238 : cas nominal — le dernier message est la réponse texte finale de l'assistant.
- Lignes 239–245 : si la limite des 30 tours est atteinte **pendant** un `tool_use`, le dernier message est un user/tool_result et `extract_text` renvoie `""` (cf. ci-dessus). On remonte alors l'historique à la recherche du dernier texte d'assistant.
- Ligne 247 : ultime repli, un message explicite plutôt qu'une chaîne vide.
- Ligne 249 : le `return` est le seul canal vers le parent — `messages` (potentiellement 60 entrées) sort de portée et est garbage-collecté.

### Enregistrement de l'outil `task` — lignes 252–257

```python
TOOLS.append({
    "name": "task",
    "description": "Launch a subagent to handle a complex subtask. Returns only the final conclusion.",
    "input_schema": {"type": "object", "properties": {"description": {"type": "string"}}, "required": ["description"]},
})
TOOL_HANDLERS["task"] = spawn_subagent
```

Le point pédagogique : **la boucle ne change pas**. `task` est un outil comme un autre — `agent_loop` le dispatch via `TOOL_HANDLERS[block.name]` sans savoir qu'il déclenche 30 appels API. Le nom du paramètre (`description`) correspond exactement à la signature `spawn_subagent(description: str)`, condition nécessaire au `handler(**block.input)`.

### `register_hook(event, callback)` — lignes 266–267
### `trigger_hooks(event, *args)` — lignes 269–274
### `permission_hook(block)` — lignes 278–285
### `log_hook(block)` — lignes 287–290
### `context_inject_hook(query)` — lignes 292–295
### `summary_hook(messages)` — lignes 297–303
Tout le système de hooks (registre `HOOKS` ligne 264, deny-list ligne 276, enregistrements lignes 305–308) est repris de [[s04-hooks]] sans modification. Seule nouveauté d'usage : `trigger_hooks` est désormais appelé aussi **depuis le sous-agent**.

### `agent_loop(messages)` — lignes 317–362
Reprise de [[s05-todo-write]] sans modification : nag reminder après 3 tours sans `todo_write` (lignes 321–324), appel API (326–329), hooks `Stop` pouvant forcer la continuation (333–336), dispatch des `tool_use` avec `PreToolUse`/`PostToolUse` (341–360). Quand le modèle appelle `task`, la ligne 352 (`output = handler(**block.input)`) **bloque** jusqu'au retour du sous-agent — la délégation est synchrone.

### Bloc `__main__` — lignes 365–383
REPL identique à s05 : lecture du prompt, hook `UserPromptSubmit`, appel `agent_loop(history)`, affichage des blocs texte de la dernière réponse. Sortie sur `q`, `exit`, chaîne vide ou Ctrl-C/Ctrl-D.

## Ce qui change par rapport à [[s05-todo-write]]

- **Nouveau** : `SUB_SYSTEM` (58–62) — prompt système dédié au sous-agent, anti-délégation.
- **Nouveau** : `SUB_TOOLS` (182–193) et `SUB_HANDLERS` (196–199) — 5 outils, sans `task` ni `todo_write`.
- **Nouveau** : `extract_text()` (201–205) — extraction du texte des blocs de contenu.
- **Nouveau** : `spawn_subagent()` (207–249) — boucle agentique isolée, 30 tours max, retour du seul résumé.
- **Nouveau** : outil `task` ajouté à `TOOLS` et `TOOL_HANDLERS` (252–257) — 6 outils deviennent 7.
- **Modifié** : `SYSTEM` (52–55) mentionne l'outil `task`.
- **Inchangé** : tous les outils s02–s05, le système de hooks de s04, `agent_loop` et le REPL.

## Pièges et détails d'implémentation

- **L'isolation de contexte n'isole pas les permissions** : `spawn_subagent` appelle `trigger_hooks("PreToolUse", ...)` comme le parent (lignes 224–228). Un `sudo` lancé par le sous-agent est bloqué par la même deny-list.
- **Le repli « Issue 5 »** : si la limite de 30 tours tombe en plein `tool_use`, le dernier message ne contient aucun texte ; sans le balayage arrière des lignes 239–245, le parent recevrait une chaîne vide.
- **`extract_text` repose sur une asymétrie discrète** : blocs assistant = objets SDK (avec `.text`), blocs tool_result = dicts. `getattr` sur un dict renvoie le défaut, donc les messages user sont naturellement filtrés.
- **Les effets de bord survivent à l'oubli** : la conversation du sous-agent est jetée, mais ses `write_file`/`bash` ont modifié le disque. Le parent peut vérifier le travail (3e prompt d'essai du README).
- **Pas de `limit` dans le `read_file` du sous-agent** : le schéma de `SUB_TOOLS` omet ce paramètre présent côté parent — divergence mineure mais réelle entre les deux jeux d'outils.
- **Délégation synchrone uniquement** : le parent est suspendu pendant toute l'exécution du sous-agent. Le vrai Claude Code propose aussi un mode asynchrone (`run_in_background`) — introduit plus tard dans [[s13-background-tasks]].

## Liens

- Session précédente : [[s05-todo-write]]
- Session suivante : [[s07-skill-loading]]
- Sessions liées : [[s04-hooks]] (les hooks traversent la frontière du sous-agent), [[s13-background-tasks]] (sous-agents asynchrones), [[s15-agent-teams]] (généralisation multi-agents), [[s12-task-system]] (registre de tâches)
