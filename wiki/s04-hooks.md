---
title: "s04 · Les hooks"
session: 04
phase: "Fondamentaux"
fichier: "inspiration/learn-claude-code/s04_hooks/code.py"
lignes: 294
tags: [hooks, pre-tool-use, post-tool-use, stop, extension]
prev: "s03-permission"
next: "s05-todo-write"
---

# s04 · Les hooks

> **En une phrase** : la logique d'extension (permissions, logs, contrôles) sort du corps de la boucle pour s'accrocher à un registre de hooks déclenchés à quatre moments du cycle — la boucle n'appelle plus que `trigger_hooks()`.

## Rôle dans le harness

L'agent de [[s03-permission]] vérifie les permissions — mais le contrôle est codé en dur dans `agent_loop`. Chaque nouveau besoin (« journaliser chaque appel bash », « lancer `git add` après chaque écriture », « notifier Slack ») obligerait à rouvrir la boucle et à y insérer une ligne. Le README montre la dérive : une boucle truffée de `log_to_file(block)`, `notify_slack(block)`, `auto_git_add(block)`… *« What you want to extend is the Agent's behavior, but what you're modifying is the loop itself. The loop should be a stable core; extensions should hang on the outside. »*

La solution est le patron observateur appliqué au cycle d'agent : un registre `HOOKS` (événement → liste de callbacks), une fonction `register_hook()` pour s'abonner, une fonction `trigger_hooks()` que la boucle appelle aux moments clés. Quatre événements couvrent un cycle complet :

| Événement | Moment | Usage typique |
|---|---|---|
| `UserPromptSubmit` | Après la saisie utilisateur, avant le LLM | Validation d'entrée, injection de contexte |
| `PreToolUse` | Avant l'exécution d'un outil | Permissions, journalisation |
| `PostToolUse` | Après l'exécution d'un outil | Effets de bord, contrôle de sortie |
| `Stop` | Quand la boucle va se terminer | Nettoyage, voire continuation forcée |

Le vrai Claude Code compte **27 événements de hooks** (`coreTypes.ts:25-53`) — SessionStart/End, SubagentStart/Stop, PreCompact/PostCompact, TaskCreated… — et un `HookResult` à 14 champs (modification de l'input, décision de permission, contexte additionnel…). La version pédagogique garde les 4 événements qui couvrent les nœuds critiques du cycle ; les 23 autres suivent le même patron. CC impose aussi un invariant de sécurité absent ici : un hook qui répond `allow` ne peut pas contourner les règles deny/ask de settings.json.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–49 | Docstring | Diagramme ASCII du cycle avec les 4 points de hook, inventaire des ajouts |
| 51–68 | Imports & env | Identiques à s03 |
| 70–74 | Configuration | `WORKDIR`, client, `MODEL`, `SYSTEM` |
| 81–134 | Repris de s02–s03 | `safe_path` + les 5 outils, inchangés vs s03 |
| 136–152 | Repris de s02 | `TOOLS` et `TOOL_HANDLERS`, inchangés |
| 159–169 | **Nouveau** | Le mécanisme : `HOOKS`, `register_hook()`, `trigger_hooks()` |
| 173–223 | **Nouveau** | Les 5 callbacks : `permission_hook`, `log_hook`, `large_output_hook`, `context_inject_hook`, `summary_hook` |
| 225–229 | **Nouveau** | Les 5 enregistrements `register_hook(...)` |
| 238–272 | Boucle | `agent_loop()` : `check_permission()` remplacé par `trigger_hooks()` + hook Stop |
| 275–293 | Point d'entrée | REPL + déclenchement `UserPromptSubmit` |

## Constantes et configuration

- **`HOOKS` (ligne 159)** : `{"UserPromptSubmit": [], "PreToolUse": [], "PostToolUse": [], "Stop": []}` — le registre. Des listes, pas des callbacks uniques : plusieurs hooks peuvent écouter le même événement, exécutés dans l'ordre d'enregistrement.
- **`DENY_LIST` (ligne 173)** : reprise de s03, amputée de `"> /dev/sda"` (six motifs au lieu de sept).
- **`DESTRUCTIVE` (ligne 174)** : `["rm ", "> /etc/", "chmod 777"]` — les mots-clés de l'ancienne `PERMISSION_RULES` de s03, promus en constante puisque la règle bash vit maintenant dans `permission_hook`.
- **Enregistrements (lignes 225–229)** : exécutés à l'import, ils câblent la configuration par défaut :

```python
register_hook("UserPromptSubmit", context_inject_hook)
register_hook("PreToolUse", permission_hook)
register_hook("PreToolUse", log_hook)
register_hook("PostToolUse", large_output_hook)
register_hook("Stop", summary_hook)
```

L'ordre compte : `permission_hook` est enregistré **avant** `log_hook`, donc un appel bloqué n'est jamais journalisé (voir Pièges).

## Les fonctions, une à une

### `safe_path` (81–85), `run_bash` (87–94), `run_read` (96–103), `run_write` (105–112), `run_edit` (114–123), `run_glob` (125–134)
Repris de [[s03-permission]] sans modification. `TOOLS` (136–147) et `TOOL_HANDLERS` (149–152) idem.

### `register_hook(event, callback)` — lignes 161–162

```python
def register_hook(event: str, callback):
    HOOKS[event].append(callback)
```

Une ligne : ajouter le callback à la liste de l'événement. Accès direct `HOOKS[event]` : un nom d'événement inconnu lève `KeyError` immédiatement — erreur de programmation détectée au démarrage plutôt qu'un hook silencieusement jamais appelé.

### `trigger_hooks(event, *args)` — lignes 164–169

Le moteur du système, six lignes :

```python
def trigger_hooks(event: str, *args):
    for callback in HOOKS[event]:
        result = callback(*args)
        if result is not None:  # teaching shortcut: block this tool call
            return result
    return None
```

- **Ligne 164** : `*args` — chaque événement a sa propre signature (`PreToolUse` reçoit `block`, `PostToolUse` reçoit `block, output`, `Stop` reçoit `messages`…). Le variadique évite une signature par événement ; en contrepartie, rien ne vérifie la cohérence callback/événement.
- **Lignes 166–168** : la convention de retour, clef de voûte du système : **`None` = laisser passer, non-`None` = court-circuit**. Le premier hook qui renvoie autre chose que `None` interrompt la chaîne et sa valeur remonte à l'appelant. La sémantique de cette valeur dépend de l'événement : pour `PreToolUse`, c'est un message de blocage ; pour `Stop`, c'est un message de continuation forcée. Le commentaire `teaching shortcut` l'assume : le `HookResult` du vrai CC est un objet riche à 14 champs (dont `updatedInput` pour modifier l'input ou `permissionBehavior` pour rendre une décision), pas une simple valeur.

### `permission_hook(block)` — lignes 176–198

Toute la logique de `check_permission` + `check_rules` + `ask_user` de [[s03-permission]], fusionnée dans un seul callback `PreToolUse` :

```python
def permission_hook(block):
    """PreToolUse: s03 check_permission() logic moved here."""
    if block.name == "bash":
        for pattern in DENY_LIST:
            if pattern in block.input.get("command", ""):
                print(f"\n\033[31m⛔ Blocked: '{pattern}'\033[0m")
                return "Permission denied by deny list"
        for kw in DESTRUCTIVE:
            if kw in block.input.get("command", ""):
                print(f"\n\033[33m⚠  Potentially destructive command\033[0m")
                print(f"   Tool: {block.name}({block.input})")
                choice = input("   Allow? [y/N] ").strip().lower()
                if choice not in ("y", "yes"):
                    return "Permission denied by user"
    if block.name in ("write_file", "edit_file"):
        path = block.input.get("path", "")
        if not (WORKDIR / path).resolve().is_relative_to(WORKDIR):
            ...
            choice = input("   Allow? [y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                return "Permission denied by user"
    return None
```

- **Lignes 179–182** : barrière 1 de s03 (deny dur, sans question) — retour d'une chaîne = blocage.
- **Lignes 183–189** : barrière 2+3 pour bash (mots-clés `DESTRUCTIVE` → confirmation interactive).
- **Lignes 190–197** : barrière 2+3 pour l'écriture hors workspace.
- **Ligne 198** : `return None` — rien à signaler, l'exécution peut avoir lieu.
- Changement de forme notable : s03 séparait politique (`PERMISSION_RULES` déclaratif) et mécanique (`check_rules`) ; s04 réinline tout en impératif dans le hook. La leçon de la session n'est pas la structure interne du contrôle mais son *emplacement* : dans un callback, plus dans la boucle. Les messages de refus sont aussi plus précis qu'en s03 (`"Permission denied by deny list"` / `"by user"` au lieu d'un générique) — le modèle sait *qui* a refusé.

### `log_hook(block)` — lignes 200–204

```python
def log_hook(block):
    """PreToolUse: log every tool call."""
    args_preview = str(list(block.input.values())[:2])[:60]
    print(f"\033[90m[HOOK] {block.name}({args_preview})\033[0m")
    return None
```

Deuxième hook `PreToolUse` : journalise chaque appel (nom + aperçu des 2 premières valeurs d'arguments, tronqué à 60 caractères pour ne pas inonder le terminal). Renvoie toujours `None` : un hook d'observation pure ne bloque jamais. Démonstration du multi-abonnement : deux hooks sur le même événement, le premier décide, le second observe.

### `large_output_hook(block, output)` — lignes 206–210

```python
def large_output_hook(block, output):
    """PostToolUse: warn on large output."""
    if len(str(output)) > 100000:
        print(f"\033[33m[HOOK] ⚠ Large output from {block.name}: {len(str(output))} chars\033[0m")
    return None
```

Hook `PostToolUse` : avertit quand une sortie d'outil dépasse 100 000 caractères. Simple alerte console — il ne tronque ni ne modifie rien (le retour de `trigger_hooks("PostToolUse", ...)` est d'ailleurs ignoré par la boucle). Préfigure la gestion sérieuse du volume de contexte de [[s08-context-compact]]. Note : `run_bash` tronque déjà à 50 000, mais `run_read` sur un très gros fichier peut dépasser le seuil.

### `context_inject_hook(query)` — lignes 213–215

```python
def context_inject_hook(query: str):
    print(f"\033[90m[HOOK] UserPromptSubmit: working in {WORKDIR}\033[0m")
    return None
```

Hook `UserPromptSubmit`, déclenché dans le REPL juste après la saisie (ligne 287), avant que la question n'entre dans l'historique. Malgré son nom, il n'injecte rien : il journalise. Le README précise que dans CC, ce point d'accroche permet réellement d'intercepter ou d'enrichir le prompt ; ici on montre seulement *où* se trouve la prise.

### `summary_hook(messages)` — lignes 218–223

```python
def summary_hook(messages: list):
    tool_count = sum(1 for m in messages
                     for b in (m.get("content") if isinstance(m.get("content"), list) else [])
                     if isinstance(b, dict) and b.get("type") == "tool_result")
    print(f"\033[90m[HOOK] Stop: session used {tool_count} tool calls\033[0m")
    return None
```

Hook `Stop` : compte les appels d'outils de la session en parcourant l'historique. La double compréhension mérite un arrêt :

- pour chaque message `m`, on n'itère sur `m["content"]` que si c'est une liste (les questions utilisateur sont des `str` → liste vide à la place) ;
- on ne compte que les éléments qui sont des `dict` avec `type == "tool_result"`. Pourquoi ce test `isinstance(b, dict)` ? Parce que l'historique mélange deux natures : les tours assistant contiennent des **objets SDK** (`TextBlock`, `ToolUseBlock`), les messages de résultats contiennent des **dicts** construits par la boucle. Compter les `tool_result` (dicts) plutôt que les `tool_use` (objets) simplifie le test.
- Retour `None` = autoriser l'arrêt. **Un retour non-`None` aurait forcé la boucle à continuer** — c'est le contrat côté `agent_loop`.

### `agent_loop(messages)` — lignes 238–272

La boucle de s03, avec deux changements. D'abord, à la sortie :

```python
        if response.stop_reason != "tool_use":
            force = trigger_hooks("Stop", messages)
            if force:
                messages.append({"role": "user", "content": force})
                continue
            return
```

- **Lignes 246–251** : avant de quitter, la boucle consulte les hooks `Stop`. Si l'un d'eux renvoie une valeur, celle-ci est injectée **comme message utilisateur** et le `continue` relance un appel LLM : le hook a empêché l'arrêt (par exemple « les tests ne passent pas encore, continue »). C'est le mécanisme que CC appelle stop hooks — avec, chez CC, un garde-fou `stopHookActive` contre la boucle infinie (hook force → modèle répond → hook force encore…) que la version pédagogique n'a pas, son `summary_hook` renvoyant toujours `None`.

Ensuite, autour de l'exécution des outils :

```python
            # s04 change: hook replaces hard-coded check_permission()
            blocked = trigger_hooks("PreToolUse", block)
            if blocked:
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": str(blocked)})
                continue

            handler = TOOL_HANDLERS.get(block.name)
            output = handler(**block.input) if handler else f"Unknown: {block.name}"

            trigger_hooks("PostToolUse", block, output)
```

- **Lignes 259–263** : `trigger_hooks("PreToolUse", block)` remplace le `check_permission(block)` de s03. La valeur de blocage (chaîne du hook) devient directement le contenu du `tool_result` — le modèle lit la raison exacte du refus. La boucle ne sait plus *rien* des permissions : elle sait juste qu'un hook peut s'opposer.
- **Ligne 268** : `trigger_hooks("PostToolUse", block, output)` après l'exécution — la valeur de retour est ignorée : en version pédagogique, `PostToolUse` observe sans pouvoir modifier `output` (CC le permet via `updatedMCPToolOutput`).

### Point d'entrée `if __name__ == "__main__"` — lignes 275–293

Repris de s03 avec un ajout, ligne 287 : `trigger_hooks("UserPromptSubmit", query)` est appelé entre la saisie et l'ajout à l'historique — quatrième et dernier point d'accroche du cycle. Les bannières passent par ailleurs du chinois à l'anglais (lignes 276–277).

## Ce qui change par rapport à [[s03-permission]]

- **+ `HOOKS`** (ligne 159), **+ `register_hook()`** (161–162), **+ `trigger_hooks()`** (164–169) : le mécanisme.
- **+ 5 callbacks** : `permission_hook` (176–198, absorbe `check_deny_list`+`check_rules`+`ask_user`+`check_permission` de s03), `log_hook` (200–204), `large_output_hook` (206–210), `context_inject_hook` (213–215), `summary_hook` (218–223).
- **− `check_permission()` et toute la famille s03** : supprimées du fichier ; la logique vit dans `permission_hook`, déclenchée via `PreToolUse`.
- **`agent_loop`** : `if not check_permission(block)` → `blocked = trigger_hooks("PreToolUse", block)` ; ajout du déclenchement `PostToolUse` (ligne 268) et du hook `Stop` avec continuation forcée possible (lignes 246–251).
- **REPL** : ajout de `trigger_hooks("UserPromptSubmit", query)` (ligne 287).
- **`DENY_LIST`** perd `"> /dev/sda"` ; les mots-clés de règles deviennent la constante `DESTRUCTIVE`.

## Pièges et détails d'implémentation

- **Le court-circuit coupe toute la chaîne** : `trigger_hooks` s'arrête au premier retour non-`None`. Comme `permission_hook` est enregistré avant `log_hook`, **un appel bloqué n'apparaît jamais dans les logs** — l'ordre d'enregistrement est une décision de comportement, pas un détail.
- **Une seule convention de retour, deux sens opposés** : non-`None` signifie « bloquer » pour `PreToolUse` mais « continuer de force » pour `Stop`. Même mécanisme, sémantique inversée selon l'événement — lisible ici, source de confusion à grande échelle (d'où l'objet `HookResult` structuré de CC).
- **Pas de garde anti-boucle sur Stop** : un hook `Stop` qui renverrait systématiquement une chaîne créerait une boucle infinie (continuation → réponse → Stop → continuation…). CC s'en protège avec le drapeau `stopHookActive` (`query.ts:212,1300`).
- **Le retour de `PostToolUse` est ignoré** : contrairement à `PreToolUse`, la ligne 268 n'exploite pas la valeur — un hook post ne peut ni modifier ni censurer la sortie dans cette version.
- **Un hook `allow` ne devrait pas être souverain** : dans CC, même si un hook approuve, les règles deny/ask de settings.json s'appliquent encore (`toolHooks.ts:325-331`). La version pédagogique laisse le premier hook tout décider — acceptable ici, vulnérabilité en production.
- **Les hooks peuvent bloquer… le terminal** : `permission_hook` fait un `input()` au milieu du cycle ; tout hook est synchrone et bloquant pour la boucle.

## Liens

- Session précédente : [[s03-permission]]
- Session suivante : [[s05-todo-write]]
- Sessions liées : [[s01-agent-loop]] (les points d'accroche s'insèrent dans cette boucle), [[s08-context-compact]] (suite logique de `large_output_hook`), [[s12-task-system]] (hooks TaskCreated/TaskCompleted chez CC), [[s17-autonomous-agents]] (stop hooks comme moteur d'autonomie)
