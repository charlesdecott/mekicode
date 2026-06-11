---
title: "s17 · Agents autonomes"
session: 17
phase: "Multi-agents"
fichier: "inspiration/learn-claude-code/s17_autonomous_agents/code.py"
lignes: 813
tags: [autonomie, idle-poll, auto-claim, task-board, multi-agents]
prev: "s16-team-protocols"
next: "s18-worktree-isolation"
---

# s17 · Agents autonomes

> **En une phrase** : les teammates cessent d'attendre les ordres du Lead — quand ils sont inactifs, ils scrutent le tableau de tâches, s'auto-assignent (`auto-claim`) la première tâche disponible, et ne s'arrêtent qu'après 60 s sans travail (cycle de vie WORK → IDLE → SHUTDOWN).

## Rôle dans le harness

En [[s16-team-protocols]], les teammates savent communiquer et négocier un arrêt propre (handshake `shutdown_request` / `shutdown_response`). Mais chaque teammate attend que le Lead lui assigne une tâche : avec 10 tâches non réclamées sur le tableau, le Lead doit assigner 10 fois à la main. Le README résume le problème : *"This doesn't scale. Teammates should check the task board themselves, claim unowned tasks, and look for the next one when done."*

s17 introduit l'**autonomie** : le teammate qui termine son travail n'exit plus — il entre en phase IDLE et scrute toutes les 5 secondes (1) sa boîte aux lettres, (2) le tableau de tâches. S'il trouve une tâche `pending` sans propriétaire dont toutes les dépendances sont complétées, il la réclame lui-même et repart en phase WORK. Après 60 s sans rien trouver, il s'arrête et envoie son résumé au Lead. Le slogan du chapitre : *"Check the board, claim the task."*

Dans le vrai Claude Code, ce mécanisme n'est pas un polling unique mais la combinaison de quatre mécanismes (d'après le README) : `sendIdleNotification()` (notification d'inactivité au Lead), `waitForNextPromptOrShutdown()` (boucle de polling à 500 ms sur messages et tâches, avec priorité aux shutdown), `useTaskListWatcher` (surveillance `fs.watch()` du répertoire `.claude/tasks/` avec debounce de 1 s) et `tryClaimNextTask()` (claim actif pendant l'attente). La version pédagogique fusionne tout dans une seule fonction `idle_poll()` — une simplification assumée, la sémantique étant identique : trouver du travail quand on est inactif, réclamer quand les dépendances sont résolues, prioriser le shutdown.

L'autre apport de s17 côté Lead : `consume_lead_inbox()` injecte désormais les messages reçus (résumés des teammates, réponses de protocole) **dans l'historique de conversation** du Lead, et plus seulement dans le terminal — le LLM du Lead peut donc réagir aux résultats de son équipe.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–20 | Docstring | objectif, liste des changements vs s16, schéma ASCII du cycle de vie |
| 22–42 | Imports & init | readline, dotenv, client `Anthropic`, `MODEL`, `WORKDIR` |
| 44–137 | Task System (s12) | dataclass `Task`, CRUD JSON, `can_start`, `claim_task` (renforcé), `complete_task` |
| 140–171 | Prompt Assembly (s10) | `PROMPT_SECTIONS`, `assemble_system_prompt`, mémoïsation `get_system_prompt` |
| 174–210 | Outils de base (s15) | `safe_path`, `run_bash`, `run_read`, `run_write` |
| 213–242 | MessageBus (s15) | boîtes aux lettres `.jsonl`, `BUS`, `active_teammates` |
| 245–283 | Protocol State (s16) | `ProtocolState`, `pending_requests`, `new_request_id`, `match_response` |
| 286–346 | **Agent autonome (nouveau)** | constantes d'idle, `scan_unclaimed_tasks`, `idle_poll` |
| 349–538 | Thread teammate | `spawn_teammate_thread` (cycle WORK → IDLE → SHUTDOWN, 8 outils), `_teammate_submit_plan` |
| 541–578 | Outils protocole Lead (s16) | `run_request_shutdown`, `run_request_plan`, `run_review_plan` |
| 581–644 | Handlers Lead | `run_create_task` … `run_check_inbox`, **`consume_lead_inbox` (nouveau)** |
| 647–736 | Définitions d'outils | `TOOLS` (14 outils Lead), `TOOL_HANDLERS` |
| 739–749 | Contexte | `MEMORY_INDEX`, `update_context` (s09) |
| 752–782 | Boucle agent | `agent_loop` du Lead |
| 785–813 | REPL | boucle interactive + injection de l'inbox dans l'historique |

## Constantes et configuration

- `WORKDIR = Path.cwd()` (ligne 40), `client = Anthropic(...)` (ligne 41), `MODEL = os.environ["MODEL_ID"]` (ligne 42) — initialisation standard depuis [[s01-agent-loop]].
- `TASKS_DIR = WORKDIR / ".tasks"` (lignes 46–47) — un fichier JSON par tâche, repris de [[s12-task-system]].
- `PROMPT_SECTIONS` (lignes 142–150) — sections du prompt système ; la section `tools` liste les 14 outils du Lead.
- `MAILBOX_DIR = WORKDIR / ".mailboxes"` (lignes 215–216) — boîtes `.jsonl` par agent, repris de [[s15-agent-teams]].
- `BUS = MessageBus()` et `active_teammates: dict[str, bool]` (lignes 241–242) — bus global et registre des teammates vivants.
- `pending_requests: dict[str, ProtocolState]` (ligne 258) — registre des requêtes de protocole en attente, repris de [[s16-team-protocols]].
- **`IDLE_POLL_INTERVAL = 5` et `IDLE_TIMEOUT = 60`** (lignes 288–289) — nouveau : période de polling et durée maximale d'inactivité. 12 sondages × 5 s = 60 s.
- `TOOLS` (lignes 649–725) — 14 définitions d'outils Lead (inchangé en nombre vs s16) ; `TOOL_HANDLERS` (lignes 727–736) — table nom → fonction.
- `MEMORY_DIR` / `MEMORY_INDEX` (lignes 741–742) — index mémoire de [[s09-memory]].

## Les fonctions, une à une

### `Task` (dataclass) — lignes 50–57
Schéma d'une tâche : `id`, `subject`, `description`, `status`, `owner`, `blockedBy`. Repris de [[s12-task-system]] sans modification. Le champ `owner` devient central en s17 : c'est lui qui matérialise le claim.

### `_task_path(task_id)` — lignes 60–61
Chemin du fichier JSON d'une tâche. Repris de [[s12-task-system]] sans modification.

### `create_task(subject, description, blockedBy)` — lignes 64–73
Crée une tâche `pending` sans owner, id horodaté + suffixe aléatoire. Repris de [[s12-task-system]] sans modification.

### `save_task(task)` / `load_task(task_id)` — lignes 76–77 / 80–81
Sérialisation/désérialisation JSON d'une tâche. Repris de [[s12-task-system]] sans modification.

### `list_tasks()` — lignes 84–86
Charge toutes les tâches triées par nom de fichier. Repris de [[s12-task-system]] sans modification.

### `get_task(task_id)` — lignes 89–91
Retourne le JSON complet d'une tâche. Repris de [[s12-task-system]] (sera renommé `get_task_json` en [[s18-worktree-isolation]]).

### `can_start(task_id)` — lignes 94–101
Vrai si toutes les dépendances `blockedBy` existent et sont `completed`. Repris de [[s12-task-system]] sans modification — mais s17 lui donne un rôle nouveau : c'est le filtre de `scan_unclaimed_tasks`.

### `claim_task(task_id, owner)` — lignes 104–122
**Modifiée en s17** : la vérification d'owner est ajoutée. C'est la garde anti-collision quand plusieurs teammates scrutent le même tableau.

```python
def claim_task(task_id: str, owner: str = "agent") -> str:
    task = load_task(task_id)
    if task.status != "pending":
        return f"Task {task_id} is {task.status}, cannot claim"
    if task.owner:
        return f"Task {task_id} already owned by {task.owner}"
    if not can_start(task_id):
        deps = [d for d in task.blockedBy
                if _task_path(d).exists() and load_task(d).status != "completed"]
        missing = [d for d in task.blockedBy if not _task_path(d).exists()]
        parts = []
        if deps: parts.append(f"blocked by: {deps}")
        if missing: parts.append(f"missing deps: {missing}")
        return "Cannot start — " + ", ".join(parts)
    task.owner = owner
    task.status = "in_progress"
    save_task(task)
```

- Trois gardes successives : statut non-`pending` (déjà réclamée ou finie), **owner déjà posé** (nouveau — évite le « last writer wins » le plus évident), dépendances non résolues.
- Le message d'échec distingue les dépendances *incomplètes* (`blocked by`) des dépendances *inexistantes* (`missing deps`) — diagnostic précieux pour le LLM.
- En cas de succès, l'écriture pose `owner` **et** passe `status` à `in_progress` en une seule sauvegarde.
- Pas de verrou fichier : deux threads qui lisent la même tâche au même instant peuvent encore se la voler (TOCTOU). Le README précise que le vrai CC fait le read-modify-write sous verrou `proper-lockfile` (`utils/tasks.ts:541-612`).

### `complete_task(task_id)` — lignes 125–137
Passe une tâche `in_progress` à `completed`, puis calcule la liste des tâches **débloquées** par cette complétion (lignes 131–132 : `pending`, avec `blockedBy` non vide, et désormais `can_start`). Le message retourné inclut `Unblocked: ...` — le LLM apprend immédiatement quelles tâches sont devenues réclamables. Repris de [[s12-task-system]] sans modification.

### `assemble_system_prompt(context)` — lignes 153–159
Concatène identité + outils + workspace + mémoires éventuelles. Repris de [[s10-system-prompt]] sans modification (seule la liste d'outils dans `PROMPT_SECTIONS` a grandi).

### `get_system_prompt(context)` — lignes 165–171
Mémoïsation du prompt système sur hash JSON du contexte. Repris de [[s10-system-prompt]] sans modification.

### `safe_path(p)` — lignes 176–180
Anti-évasion du workspace via `resolve()` + `is_relative_to`. Repris de [[s03-permission]] sans modification.

### `run_bash(command)` / `run_read(path, limit)` / `run_write(path, content)` — lignes 183–190 / 193–200 / 203–210
Les trois outils de base (timeout 120 s, troncature 50 000 caractères, création des dossiers parents). Repris de [[s15-agent-teams]] sans modification.

### `MessageBus` (classe) — lignes 219–238
`send()` (lignes 220–229) ajoute une ligne JSON dans `.mailboxes/{to}.jsonl` ; `read_inbox()` (lignes 231–238) lit puis **supprime** le fichier (lecture destructive). Repris de [[s15-agent-teams]] sans modification.

### `ProtocolState` (dataclass) — lignes 247–255
État d'une requête de protocole (`request_id`, `type`, `sender`, `target`, `status`, `payload`, `created_at`). Repris de [[s16-team-protocols]] sans modification.

### `new_request_id()` — lignes 261–262
Identifiant `req_NNNNNN` aléatoire. Repris de [[s16-team-protocols]] sans modification.

### `match_response(response_type, request_id, approve)` — lignes 265–283
Corrèle une réponse à sa requête via `request_id`, vérifie la cohérence des types (`shutdown` ↔ `shutdown_response`, `plan_approval` ↔ `plan_approval_response`), met à jour `status`. Repris de [[s16-team-protocols]] sans modification.

### `scan_unclaimed_tasks()` — lignes 292–301
**Nouvelle.** Le cœur de l'auto-assignation : trouver les tâches réclamables.

```python
def scan_unclaimed_tasks() -> list[dict]:
    """Find pending, unowned tasks with all dependencies completed."""
    unclaimed = []
    for f in sorted(TASKS_DIR.glob("task_*.json")):
        task = json.loads(f.read_text())
        if (task.get("status") == "pending"
                and not task.get("owner")
                and can_start(task["id"])):
            unclaimed.append(task)
    return unclaimed
```

- Trois conditions cumulatives : `status == "pending"`, pas d'`owner`, et `can_start()` vrai (toutes les dépendances `completed`).
- Subtilité sémantique soulignée par le README : avoir des dépendances n'empêche pas de démarrer — seules les dépendances *non résolues* bloquent. Une tâche avec `blockedBy` rempli devient réclamable dès que ses dépendances passent à `completed`.
- La fonction lit les JSON bruts (`dict`, pas `Task`) — c'est pour cela que `idle_poll` manipule `task["id"]` et non `task.id`.
- Tri par nom de fichier (donc par timestamp de création) : le « premier arrivé » du tableau est réclamé en premier. Le vrai CC remplace ce scan par `useTaskListWatcher` (`fs.watch()`) et protège le claim par verrou fichier.

### `idle_poll(agent_name, messages, name, role)` — lignes 304–346
**Nouvelle.** La boucle d'inactivité : 12 itérations de 5 s, trois sorties possibles : `"work"`, `"shutdown"`, `"timeout"`.

```python
def idle_poll(agent_name: str, messages: list,
              name: str, role: str) -> str:
    """Poll for 60s. Return 'work', 'shutdown', or 'timeout'."""
    for _ in range(IDLE_TIMEOUT // IDLE_POLL_INTERVAL):
        time.sleep(IDLE_POLL_INTERVAL)

        # Check inbox — dispatch protocol messages first
        inbox = BUS.read_inbox(agent_name)
        if inbox:
            # Check for shutdown_request
            for msg in inbox:
                if msg.get("type") == "shutdown_request":
                    req_id = msg.get("metadata", {}).get("request_id", "")
                    BUS.send(name, "lead", "Shutting down gracefully.",
                             "shutdown_response",
                             {"request_id": req_id, "approve": True})
                    ...
                    return "shutdown"

            # Non-protocol inbox: inject and resume work
            messages.append({"role": "user",
                "content": "<inbox>" + json.dumps(inbox) + "</inbox>"})
            ...
            return "work"

        # Scan task board
        unclaimed = scan_unclaimed_tasks()
        if unclaimed:
            task = unclaimed[0]
            result = claim_task(task["id"], agent_name)
            if "Claimed" in result:
                messages.append({"role": "user",
                    "content": f"<auto-claimed>Task {task['id']}: "
                               f"{task['subject']}</auto-claimed>"})
                ...
                return "work"
            print(f"  \033[33m[idle] {name} claim failed: "
                  f"{result}\033[0m")

    print(f"  \033[31m[idle] {name} timeout ({IDLE_TIMEOUT}s)\033[0m")
    return "timeout"
```

- Ligne 307 : `IDLE_TIMEOUT // IDLE_POLL_INTERVAL` = 12 tours ; le `time.sleep` est en *début* de tour — un teammate fraîchement idle attend donc 5 s avant son premier scan.
- **L'inbox est prioritaire sur le tableau** : il peut contenir un `shutdown_request` de protocole, qui doit être traité immédiatement (réponse `shutdown_response` avec `approve: True` corrélée par `request_id`, puis `return "shutdown"`). Sans cela, un teammate idle ignorerait les demandes d'arrêt du Lead jusqu'au timeout.
- Les messages non-protocole sont injectés en bloc dans l'historique sous balise `<inbox>...</inbox>` puis `return "work"` — le teammate retourne en phase WORK pour y réagir.
- L'auto-claim ne réclame que `unclaimed[0]` (le plus ancien), et **vérifie la valeur de retour** : `if "Claimed" in result`. Si un autre teammate a réclamé la tâche entre le scan et le claim, le claim échoue proprement et la boucle continue (le message `claim failed` est seulement affiché, pas injecté).
- La balise `<auto-claimed>Task ...: ...</auto-claimed>` injectée comme message user est la seule chose qui dit au LLM quoi faire ensuite — c'est l'équivalent autonome d'un prompt d'assignation du Lead.
- Détail de signature : `agent_name` et `name` reçoivent toujours la même valeur aux deux appels du fichier, et `role` n'est jamais utilisé — paramètres redondants (voir Pièges).

### `spawn_teammate_thread(name, role, prompt)` — lignes 351–525
**Fortement modifiée** : le thread teammate passe d'un cycle « travailler puis mourir » (s16) au cycle de vie **WORK → IDLE → SHUTDOWN**. Structure interne :

- prompt système du teammate (lignes 354–358) : mentionne explicitement *"You can list and claim tasks from the board."* ;
- `handle_inbox_message(name, msg, messages)` (lignes 360–382) : dispatch des messages de protocole pendant la phase WORK — `shutdown_request` → réponse approuvée + `return True` (signal d'arrêt) ; `plan_approval_response` → injection de `[Plan approved]` ou `[Plan rejected] Feedback: ...` dans l'historique. Repris de [[s16-team-protocols]] ;
- `sub_tools` (lignes 386–426) : **8 outils** au lieu de 5 — s'ajoutent `list_tasks`, `claim_task`, `complete_task` (commentaire ligne 411 : `# s17 new: teammates can list, claim, and complete tasks`) ;
- handlers locaux `_run_list_tasks` / `_run_claim_task` / `_run_complete_task` (lignes 428–440) : `_run_claim_task` appelle `claim_task(task_id, owner=name)` — le claim manuel par outil porte le **nom du teammate**, exactement comme l'auto-claim ;
- `sub_handlers` (lignes 442–450) : table de dispatch, `send_message` et `submit_plan` en lambdas.

Le cœur nouveau est la boucle externe (lignes 452–505) :

```python
        # Outer loop: WORK → IDLE cycle
        while True:
            # Identity re-injection (s17)
            if len(messages) <= 3:
                messages.insert(0, {"role": "user",
                    "content": f"<identity>You are '{name}', role: {role}. "
                               f"Continue your work.</identity>"})

            # WORK phase
            should_shutdown = False
            for _ in range(10):
                inbox = BUS.read_inbox(name)
                for msg in inbox:
                    stopped = handle_inbox_message(name, msg, messages)
                    if stopped:
                        should_shutdown = True
                        break
                ...
                try:
                    response = client.messages.create(
                        model=MODEL, system=system, messages=messages[-20:],
                        tools=sub_tools, max_tokens=8000)
                except Exception:
                    break
                messages.append({"role": "assistant", "content": response.content})
                if response.stop_reason != "tool_use":
                    break
                ...

            if should_shutdown:
                break

            # IDLE phase (s17 new)
            idle_result = idle_poll(name, messages, name, role)
            if idle_result == "shutdown":
                break
            if idle_result == "timeout":
                break
```

- **`while True` externe** : alternance WORK ↔ IDLE jusqu'à shutdown ou timeout. C'est ce qui empêche le teammate de mourir après sa première tâche.
- **`for _ in range(10)` interne** : la phase WORK est plafonnée à 10 tours LLM (anti-boucle infinie). En sortie de WORK (fin naturelle `stop_reason != "tool_use"`, épuisement des 10 tours, ou exception API avalée par le `except Exception: break`), on tombe en IDLE.
- **Ré-injection d'identité** (lignes 455–458) : si l'historique est court (`len(messages) <= 3`), un message `<identity>` est inséré en tête. L'intention (README) : après une compression de contexte type [[s08-context-compact]], un historique réduit à un résumé ferait perdre au teammate son nom et son rôle. En pratique dans ce fichier, la condition ne se déclenche qu'au premier tour (voir Pièges).
- **`messages[-20:]`** : seuls les 20 derniers messages sont envoyés à l'API — fenêtre glissante grossière en guise de gestion de contexte.
- Le `shutdown_request` est donc traité **dans les deux phases** : en WORK via `handle_inbox_message`, en IDLE via `idle_poll` directement.
- Épilogue SHUTDOWN (lignes 507–520) : extraction du dernier bloc texte assistant comme résumé (construction `for/else` imbriquée), envoi au Lead avec `msg_type="result"`, retrait de `active_teammates`. Le résumé part **toujours**, quelle que soit la cause de l'arrêt.
- Lignes 522–525 : enregistrement dans `active_teammates`, démarrage du `threading.Thread(daemon=True)`, retour immédiat `(autonomous)` au Lead.

### `_teammate_submit_plan(from_name, plan)` — lignes 528–538
Crée un `ProtocolState` de type `plan_approval` et envoie `plan_approval_request` au Lead. Repris de [[s16-team-protocols]] sans modification.

### `run_request_shutdown(teammate)` — lignes 543–554
Côté Lead : crée le `ProtocolState` de type `shutdown` et envoie `shutdown_request` avec `request_id`. Repris de [[s16-team-protocols]] sans modification.

### `run_request_plan(teammate, task)` — lignes 557–561
Simple message (pas de `ProtocolState` : la corrélation naît quand le teammate soumet son plan). Repris de [[s16-team-protocols]] sans modification.

### `run_review_plan(request_id, approve, feedback)` — lignes 564–578
Vérifie l'existence et le statut `pending` de la requête, met à jour l'état, envoie `plan_approval_response`. Repris de [[s16-team-protocols]] sans modification.

### `run_create_task(...)` — lignes 583–588, `run_list_tasks()` — lignes 591–597, `run_get_task(task_id)` — lignes 600–601, `run_claim_task(task_id)` — lignes 604–605, `run_complete_task(task_id)` — lignes 608–609
Wrappers d'outils côté Lead autour des fonctions du Task System. Repris de [[s12-task-system]] sans modification notable (`run_claim_task` du Lead réclame sous l'owner générique `"agent"`).

### `run_spawn_teammate(name, role, prompt)` — lignes 612–613 et `run_send_message(to, content)` — lignes 616–618
Wrappers vers `spawn_teammate_thread` et `BUS.send`. Repris de [[s15-agent-teams]] sans modification.

### `consume_lead_inbox(route_protocol=True)` — lignes 621–631
**Nouvelle.** Le consommateur unifié de l'inbox du Lead — utilisé à la fois par l'outil `check_inbox` et par la boucle REPL.

```python
def consume_lead_inbox(route_protocol=True) -> list[dict]:
    """Read Lead inbox: route protocol responses, return all messages."""
    msgs = BUS.read_inbox("lead")
    if route_protocol:
        for msg in msgs:
            meta = msg.get("metadata", {})
            req_id = meta.get("request_id", "")
            msg_type = msg.get("type", "")
            if req_id and msg_type.endswith("_response"):
                match_response(msg_type, req_id, meta.get("approve", False))
    return msgs
```

- Deux responsabilités : (1) **router** les réponses de protocole (tout message porteur d'un `request_id` et d'un type `*_response`) vers `match_response` pour mettre à jour `pending_requests` ; (2) **retourner tous les messages** à l'appelant, qui décide quoi en faire (affichage pour `check_inbox`, injection dans l'historique pour le REPL).
- En s16, les messages des teammates n'étaient qu'affichés au terminal — le LLM du Lead ne les voyait pas. s17 corrige cela : les résumés et résultats des teammates entrent dans le contexte du Lead, qui peut coordonner la suite.
- Attention : `read_inbox` est destructif (le fichier est supprimé) — chaque message n'est consommé qu'une fois, par le premier appelant.

### `run_check_inbox()` — lignes 634–644
Réécrite sur `consume_lead_inbox(route_protocol=True)` : formate chaque message en `[from] [type req:id] contenu` (tronqué à 200 caractères). Le routage protocole se fait donc aussi quand le LLM appelle l'outil.

### `update_context(context, messages)` — lignes 745–749
Recharge `MEMORY.md` (2 000 premiers caractères). Repris de [[s09-memory]] sans modification.

### `agent_loop(messages, context)` — lignes 754–782
Boucle d'agent du Lead : appel API, exécution des `tool_use`, ré-assemblage du prompt système à chaque tour. Repris de [[s16-team-protocols]] sans modification.

### Bloc `if __name__ == "__main__":` — lignes 785–813
REPL du Lead, **modifié** : après chaque tour, l'inbox est consommée et injectée dans l'historique.

```python
        # Consume lead inbox: route protocol + inject into history
        inbox = consume_lead_inbox(route_protocol=True)
        if inbox:
            inbox_text = "\n".join(
                f"From {m['from']} [{m.get('type', 'message')}]: "
                f"{m['content'][:200]}" for m in inbox)
            history.append({"role": "user",
                            "content": f"[Inbox]\n{inbox_text}"})
```

Le bloc `[Inbox]` devient un message user dans `history` : au tour suivant, le Lead « voit » les résumés de ses teammates. Limite : l'injection n'a lieu qu'après un tour de REPL — si les teammates terminent pendant que l'humain ne tape rien, les messages attendent dans `.mailboxes/lead.jsonl`.

## Ce qui change par rapport à [[s16-team-protocols]]

- **Nouvelles fonctions** : `scan_unclaimed_tasks` (lignes 292–301), `idle_poll` (lignes 304–346), `consume_lead_inbox` (lignes 621–631).
- **Nouvelles constantes** : `IDLE_POLL_INTERVAL = 5`, `IDLE_TIMEOUT = 60` (lignes 288–289).
- **Cycle de vie teammate** : WORK-ou-exit → WORK → IDLE (polling 60 s) → SHUTDOWN ; boucle externe `while True` dans `spawn_teammate_thread`.
- **Outils teammate : 5 → 8** : ajout de `list_tasks`, `claim_task`, `complete_task` dans `sub_tools` (lignes 411–425). Outils Lead : 14, inchangé.
- **`claim_task`** : ajout du contrôle d'owner (ligne 108–109) — une tâche déjà possédée est refusée.
- **`shutdown_request` traité en phase IDLE** : `idle_poll` répond et sort immédiatement, sans attendre le retour en WORK.
- **Inbox du Lead** : de l'affichage terminal seul à l'injection dans `history` via `consume_lead_inbox` (REPL, lignes 804–811).
- **Ré-injection d'identité** (lignes 454–458) : garde-fou contre la perte d'identité après compression de contexte.
- **Assignation** : le Lead n'assigne plus manuellement — il crée des tâches et spawne des teammates ; l'attribution émerge de l'auto-claim.

## Pièges et détails d'implémentation

- **La signature de `idle_poll` est redondante** : `agent_name` et `name` reçoivent toujours la même valeur (l'appel ligne 501 est `idle_poll(name, messages, name, role)`) et `role` n'est jamais lu dans le corps. Vestige de refactoring, sans effet fonctionnel.
- **La ré-injection d'identité ne se déclenche en réalité qu'au démarrage** : `len(messages) <= 3` n'est vrai qu'au premier passage (l'historique ne fait que croître, et s17 ne contient aucun code de compression). Le scénario visé — réinjecter l'identité après un autoCompact de [[s08-context-compact]] — n'est pas câblé dans ce fichier ; le vrai CC préserve le prompt système lors de la compaction.
- **`messages[-20:]` peut couper une paire tool_use/tool_result** : si la fenêtre de 20 messages commence sur un `tool_result` orphelin, l'API renvoie une erreur 400… avalée par le `except Exception: break` (ligne 482–483), qui envoie silencieusement le teammate en IDLE. Aucun log : un teammate qui « ne fait plus rien » peut être victime de ce découpage.
- **Le claim reste une course TOCTOU** : entre `scan_unclaimed_tasks` et `claim_task`, un autre thread peut réclamer la tâche ; pire, deux `claim_task` simultanés peuvent tous deux lire `owner=None` avant les deux écritures. La vérification du retour (`if "Claimed" in result`) atténue le premier cas, pas le second. CC utilise `proper-lockfile` (verrou tâche + verrou liste, `claimTaskWithBusyCheck` pour éviter le TOCTOU).
- **`read_inbox` destructif + deux consommateurs** : l'outil `check_inbox` et le REPL consomment la même boîte `lead.jsonl` ; un message lu par l'un est invisible pour l'autre. L'unification dans `consume_lead_inbox` garantit au moins que le routage protocole a toujours lieu.
- **Détection de chaîne magique** : `if "Claimed" in result` couple l'appelant au texte du message de retour de `claim_task` — fragile si on traduit ou reformule le message (un retour structuré serait plus sûr).

## Liens

- Session précédente : [[s16-team-protocols]]
- Session suivante : [[s18-worktree-isolation]]
- Sessions liées : [[s12-task-system]] (tableau de tâches et `can_start`), [[s15-agent-teams]] (MessageBus et threads teammates), [[s08-context-compact]] (la compression qui motive la ré-injection d'identité), [[s09-memory]] (contexte mémoire du Lead)
