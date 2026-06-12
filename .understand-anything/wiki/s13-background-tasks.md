---
title: "s13 · Tâches en arrière-plan"
session: 13
phase: "Tâches & temps"
fichier: "inspiration/learn-claude-code/s13_background_tasks/code.py"
lignes: 479
tags: [background, threads, notifications, async, tool-use]
prev: "s12-task-system"
next: "s14-cron-scheduler"
---

# s13 · Tâches en arrière-plan

> **En une phrase** : les commandes lentes partent dans un thread démon, l'agent reçoit immédiatement un `tool_result` placeholder et continue à travailler ; les résultats terminés sont réinjectés plus tard sous forme de notifications `<task_notification>`.

## Rôle dans le harness

Le README ouvre sur l'image de la machine à laver : on lance le programme et on va faire autre chose — on n'attend pas 30 minutes devant le hublot. L'outil `bash` de l'agent, lui, attend : `pip install torch` prend 10 minutes, `npm run build` 3 minutes, et pendant ce temps l'agent ne fait rien — alors que les appels LLM sont facturés au token, *« idle time is waste »*.

La solution : un double chemin d'exécution dans la boucle. Les opérations lentes partent dans un `threading.Thread` démon ; l'appel d'outil reçoit immédiatement un `tool_result` placeholder contenant un `bg_id` ; quand le thread se termine, le résultat est collecté et injecté **au tour suivant** comme bloc texte `<task_notification>` — jamais en réutilisant le `tool_use_id` d'origine, car l'API Messages exige exactement un `tool_result` par `tool_use`. La décision sync/async suit deux niveaux : la demande explicite du modèle via le nouveau paramètre `run_in_background` du schéma bash (prioritaire), sinon une heuristique par mots-clés (`install`, `build`, `test`…).

Le vrai Claude Code n'utilise pas de threads : Node.js/Bun est mono-thread, « background » signifie « ne pas `await` », et `ShellCommand.background()` redirige stdout/stderr vers des fichiers. CC définit 7 types de tâches de fond (`local_bash`, `local_agent`, `remote_agent`, `dream`…), une file de notifications (`messageQueueManager.ts`, priorités `next` > `later`), et un watchdog qui détecte les prompts interactifs `(y/n)` après 45 s sans nouvelle sortie. Le docstring (lignes 19–21) précise que, comme en s12, la boucle reste basique : la récupération d'erreurs de [[s11-error-recovery]] est omise pour rester concentré sur le sujet.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–22 | Docstring | changements depuis s12, format de notification |
| 24–45 | Imports & configuration | `threading` en plus, dotenv, chemins, client |
| 47–139 | Repris de [[s12-task-system]] | système de tâches complet (`Task`, CRUD, `can_start`, `claim`, `complete`), à l'identique |
| 141–173 | Repris de [[s10-system-prompt]] | assemblage de prompt + cache, à l'identique de s12 |
| 175–212 | Outils fichiers | `run_bash` **modifié** (paramètre `run_in_background`), `run_read`/`run_write` inchangés |
| 215–252 | Repris de s12 | wrappers d'outils tâches, à l'identique |
| 255–307 | Définitions d'outils | schéma bash **étendu**, 8 outils, `TOOL_HANDLERS` |
| 310–389 | **NOUVEAU : tâches en arrière-plan** | registres + verrou, heuristique, dispatch en thread, collecte de notifications |
| 392–405 | Contexte | `update_context` (repris de s10) |
| 408–457 | `agent_loop` | dispatch sync/async + injection de notifications |
| 460–478 | REPL | boucle interactive |

## Constantes et configuration

- `_bg_counter = 0` — ligne 312 : compteur global pour générer `bg_0001`, `bg_0002`…
- `background_tasks: dict[str, dict]` — ligne 313 : registre des tâches de fond, `bg_id → {tool_use_id, command, status}`.
- `background_results: dict[str, str]` — ligne 314 : sorties des tâches terminées, `bg_id → output`.
- `background_lock = threading.Lock()` — ligne 315 : protège les deux dicts contre les accès concurrents thread principal / threads workers.
- `TASKS_DIR` — lignes 49–50 : repris de s12 (persistance des tâches métier — à ne pas confondre avec les tâches *de fond*, qui ne vivent qu'en mémoire).
- `TOOLS` — lignes 255–300 : 8 outils ; le schéma de `bash` (lignes 256–261) gagne la propriété `run_in_background: boolean` (non requise).

## Les fonctions, une à une

### Système de tâches — lignes 53–138 (repris de [[s12-task-system]] sans modification)

`Task` (53–60), `_task_path` (63–64), `create_task` (67–76), `save_task` (79–80), `load_task` (83–84), `list_tasks` (87–89), `get_task` (92–95), `can_start` (98–107), `claim_task` (110–122), `complete_task` (125–138) : copie synchronisée de s12, expliquée en détail dans [[s12-task-system]].

### Assemblage de prompt — lignes 143–172 (repris de [[s10-system-prompt]] sans modification)

`PROMPT_SECTIONS` (143–149), `assemble_system_prompt` (152–159), `get_system_prompt` (165–172) : identiques à s12 (cache JSON, pas de logs). La liste d'outils du prompt ne mentionne pas `run_in_background` — le modèle le découvre via le schéma de l'outil.

### `run_bash(command, run_in_background=False)` — lignes 184–192 (**modifié**)

```python
def run_bash(command: str, run_in_background: bool = False) -> str:
    # run_in_background is handled by agent_loop dispatch, not here
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
```

Le corps est inchangé depuis [[s02-tool-use]] ; seule la **signature** change. Le paramètre est accepté mais ignoré (commentaire ligne 185) : la décision sync/async est prise par `agent_loop` *avant* d'appeler le handler. La signature doit pourtant l'accepter, car les handlers sont invoqués par `handler(**block.input)` — si le modèle envoie `run_in_background: true`, un `run_bash` sans ce paramètre lèverait `TypeError`.

### `run_read` / `run_write` — lignes 195–202 / 205–212 (repris de [[s02-tool-use]])

Inchangés.

### Wrappers d'outils tâches — lignes 217–252 (repris de [[s12-task-system]] sans modification)

`run_create_task` (217–222), `run_list_tasks` (225–237), `run_get_task` (240–244), `run_claim_task` (247–248), `run_complete_task` (251–252).

### `is_slow_operation(tool_name, tool_input)` — lignes 318–326

L'heuristique de repli :

```python
    if tool_name != "bash":
        return False
    cmd = tool_input.get("command", "").lower()
    slow_keywords = ["install", "build", "test", "deploy", "compile",
                     "docker build", "pip install", "npm install",
                     "cargo build", "pytest", "make"]
    return any(kw in cmd for kw in slow_keywords)
```

- Ligne 320 : seul `bash` peut être lent — lire un fichier est en millisecondes.
- Lignes 323–326 : détection par **sous-chaînes** sur la commande en minuscules. Grossier et assumé : `"test"` matche aussi `cat latest.log`, `"make"` matche `cmake --version` (voir Pièges). Le README est clair : le chemin principal est la demande explicite du modèle ; CC n'a pas d'heuristique du tout, c'est le modèle qui décide via le paramètre (`BashTool.tsx:241`).

### `should_run_background(tool_name, tool_input)` — lignes 329–333

```python
def should_run_background(tool_name: str, tool_input: dict) -> bool:
    """Model explicit request takes priority; fallback to heuristic."""
    if tool_input.get("run_in_background"):
        return True
    return is_slow_operation(tool_name, tool_input)
```

La hiérarchie de décision en 4 lignes : demande explicite du modèle d'abord, heuristique ensuite. Notez l'asymétrie : `run_in_background: false` ne force **pas** le synchrone — l'heuristique peut quand même envoyer la commande en arrière-plan (`if` vérifie la véracité, pas la présence).

### `execute_tool(block)` — lignes 336–341

Extraction de la résolution handler → exécution (auparavant inline dans la boucle) : `TOOL_HANDLERS.get(block.name)` puis `handler(**block.input)`. Cette factorisation est ce qui permet au worker de fond d'exécuter **n'importe quel** appel d'outil, pas seulement bash.

### `start_background_task(block)` — lignes 344–366

Le dispatch en thread :

```python
    global _bg_counter
    _bg_counter += 1
    bg_id = f"bg_{_bg_counter:04d}"
    cmd = block.input.get("command", block.name)

    def worker():
        result = execute_tool(block)
        with background_lock:
            background_tasks[bg_id]["status"] = "completed"
            background_results[bg_id] = result

    with background_lock:
        background_tasks[bg_id] = {
            "tool_use_id": block.id,
            "command": cmd,
            "status": "running",
        }
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    ...
    return bg_id
```

- Lignes 346–348 : ID séquentiel lisible (`bg_0001`). L'incrément n'est pas verrouillé — sans risque ici car seul le thread principal crée des tâches.
- Lignes 351–355 : `worker` est une **closure** qui capture `block` et `bg_id` ; à la fin, il marque `completed` et dépose la sortie, sous verrou.
- Lignes 357–362 : ordre décisif — l'**enregistrement précède le démarrage du thread**. Si le thread démarrait avant, un worker ultra-rapide pourrait écrire `background_tasks[bg_id]["status"]` avant que l'entrée n'existe → `KeyError`.
- Ligne 363 : `daemon=True` — les threads ne survivent pas au processus : quitter le REPL tue les installations en cours (voir Pièges).
- Ligne 366 : retourner `bg_id` (plutôt qu'un simple « lancé... ») donne au modèle une poignée pour raisonner sur la tâche. Le README note que CC va plus loin : `LocalShellTaskState`, sortie redirigée vers des fichiers, arrêt et lecture incrémentale possibles.

### `collect_background_results()` — lignes 369–389

La moisson des tâches terminées :

```python
    with background_lock:
        ready_ids = [bid for bid, task in background_tasks.items()
                     if task["status"] == "completed"]
    notifications = []
    for bg_id in ready_ids:
        with background_lock:
            task = background_tasks.pop(bg_id)
            output = background_results.pop(bg_id, "")
        summary = output[:200] if len(output) > 200 else output
        notifications.append(
            f"<task_notification>\n"
            f"  <task_id>{bg_id}</task_id>\n"
            f"  <status>completed</status>\n"
            f"  <command>{task['command']}</command>\n"
            f"  <summary>{summary}</summary>\n"
            f"</task_notification>")
```

- Lignes 371–373 : un premier passage sous verrou fige la liste des IDs prêts ; les `pop` se font ensuite, à nouveau sous verrou (lignes 376–378). Entre les deux, un worker peut seulement passer une tâche *running* → *completed* : elle sera ramassée au prochain appel, jamais perdue.
- Lignes 376–378 : `pop` = consommation unique ; le registre ne grossit pas indéfiniment. `background_results.pop(bg_id, "")` avec défaut, par prudence.
- Ligne 379 : résumé tronqué à 200 caractères — et le reste de la sortie est **définitivement perdu** puisqu'il vient d'être `pop`-é (voir Pièges). (Au passage, le ternaire est redondant : `output[:200]` suffirait.)
- Lignes 380–386 : le format `<task_notification>` reprend celui de CC (`enqueueTaskNotification`, `framework.ts:267`). Le point d'architecture, souligné partout : **le `tool_use_id` d'origine n'est pas réutilisé** — il a déjà reçu son placeholder ; la complétion est un événement indépendant, injecté comme texte.

### `update_context(context, messages)` — lignes 394–405 (repris de [[s10-system-prompt]])

Inchangé.

### `agent_loop(messages, context)` — lignes 410–457

La boucle s12, avec le dispatch à deux chemins et l'injection des notifications :

```python
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"\033[36m> {block.name}\033[0m")

            if should_run_background(block.name, block.input):
                bg_id = start_background_task(block)
                results.append({"type": "tool_result",
                                "tool_use_id": block.id,
                                "content": f"[Background task {bg_id} started] "
                                           f"Command: {block.input.get('command', '')}. "
                                           f"Result will be available when complete."})
            else:
                output = execute_tool(block)
                ...
```

- Lignes 433–439 : chemin asynchrone — le `tool_result` placeholder est produit **immédiatement**, avec le même `tool_use_id` que l'appel : l'appariement exigé par l'API est satisfait, et le texte dit explicitement au modèle que le résultat viendra plus tard. Le modèle peut donc enchaîner sur autre chose (lire un fichier, réclamer une tâche…).
- Lignes 441–445 : chemin synchrone — exécution directe comme en s12.

```python
        # Inject tool results + background notifications in one user message
        user_content = list(results)
        bg_notifications = collect_background_results()
        if bg_notifications:
            for notif in bg_notifications:
                user_content.append({"type": "text", "text": notif})
            ...
        messages.append({"role": "user", "content": user_content})
```

- Lignes 448–455 : à la fin de **chaque** salve d'outils, les notifications prêtes sont ajoutées comme blocs `text` au même message user que les `tool_results` du tour. Un seul message, contenu mixte — parfaitement légal pour l'API. Le scénario du README : tour 1, `npm install` part en fond ; tour 2, le modèle lit `package.json` (rapide, sync) et reçoit dans le même message la notification de fin d'install.
- C'est un **polling opportuniste** : la collecte n'a lieu que si le modèle continue à appeler des outils. S'il rend la main (`stop_reason != "tool_use"`, ligne 424), les tâches encore en cours devront attendre la prochaine salve d'outils du prochain tour utilisateur (voir Pièges). CC, lui, pousse les notifications via une file consommée entre les tours.
- Lignes 456–457 : `update_context` + `get_system_prompt` recalculés, comme en s12.

### REPL — lignes 460–478

Identique à s12 : affiche les blocs texte du dernier message de l'historique.

## Ce qui change par rapport à [[s12-task-system]]

- **Nouveau bloc « Background Tasks »** (lignes 310–389) : registres `background_tasks`/`background_results` + `background_lock`, `is_slow_operation`, `should_run_background`, `execute_tool`, `start_background_task`, `collect_background_results`. Import de `threading` (ligne 24).
- **Schéma bash étendu** (lignes 256–261) : propriété `run_in_background: boolean` ; signature de `run_bash` adaptée en conséquence (ligne 184), paramètre ignoré par le handler.
- **`agent_loop` réécrite côté outils** : dispatch sync/async par `should_run_background`, placeholder `tool_result` pour le chemin asynchrone, collecte et injection des notifications dans le message user de chaque salve.
- **Aucun nouvel outil** : toujours 8 outils — le tableau « Changes from s12 » du README insiste : c'est la *stratégie d'exécution* qui change, pas la palette.
- **Tout le reste est repris à l'identique** : système de tâches s12, assemblage de prompt s10, `update_context`, REPL.

## Pièges et détails d'implémentation

- **La sortie complète d'une tâche de fond est perdue** : `collect_background_results` `pop` le résultat et n'injecte que 200 caractères de résumé — impossible de relire le log complet ensuite. CC redirige la sortie vers des fichiers précisément pour pouvoir y revenir.
- **Notifications uniquement en fin de salve d'outils** : si le modèle répond en texte pur juste après avoir lancé une tâche de fond, la boucle se termine et la notification attendra la prochaine salve d'outils — potentiellement le prochain tour utilisateur. Et si l'utilisateur quitte, les threads démons meurent avec le processus : travail et résultat évaporés.
- **L'heuristique matche des sous-chaînes** : `cat latest.log` (« test »), `cmake --version` (« make ») partent en arrière-plan à tort. Le chemin fiable est `run_in_background` explicite ; l'heuristique n'est qu'un filet.
- **`run_in_background: false` ne garantit pas le synchrone** : `should_run_background` ne court-circuite que sur valeur vraie ; une commande contenant un mot-clé lent passe en fond même si le modèle a explicitement mis `false`.
- **Le timeout de 120 s s'applique aussi en arrière-plan** : le worker appelle le même `run_bash` (`subprocess.run(..., timeout=120)`) — un vrai `pip install torch` de 10 minutes échouera en « Error: Timeout (120s) », à rebours de la promesse du README. Pour de vraies tâches longues, il faudrait `Popen` sans timeout + redirection fichier.
- **Ordre d'injection** : le code place les `tool_results` d'abord puis les notifications (`user_content = list(results)` puis append) ; l'extrait du README montre l'ordre inverse (notifications d'abord). Sémantiquement équivalent pour l'API, mais l'extrait du README ne correspond pas au code.
- **`block` traverse les threads** : le worker capture l'objet `block` du SDK ; sûr ici car le thread principal ne le mute plus après dispatch, mais c'est un couplage à garder en tête si on étend le code.

## Liens

- Session précédente : [[s12-task-system]]
- Session suivante : [[s14-cron-scheduler]]
- Sessions liées : [[s02-tool-use]] (le contrat `tool_use`/`tool_result` que les notifications contournent proprement), [[s06-subagent]] (autre forme de travail délégué), [[s17-autonomous-agents]] (agents longue durée construits sur ces briques asynchrones)
