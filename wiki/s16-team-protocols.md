---
title: "s16 · Team Protocols"
session: 16
phase: "Multi-agents"
fichier: "inspiration/learn-claude-code/s16_team_protocols/code.py"
lignes: 881
tags: [protocoles, machine-a-etats, request-id, shutdown, plan-approval]
prev: "s15-agent-teams"
next: "s17-autonomous-agents"
---

# s16 · Team Protocols

> **En une phrase** : les échanges Lead–teammate deviennent des protocoles requête–réponse corrélés par `request_id` et suivis par une machine à états (`pending → approved | rejected`) — arrêt négocié (*shutdown handshake*) et approbation de plan — tandis que les teammates passent d'une borne de 10 tours à une boucle d'attente (*idle loop*).

## Rôle dans le harness

Les teammates de [[s15-agent-teams]] savent travailler et se parler, mais la coordination reste lâche : du texte libre, sans structure. Le README isole deux scénarios qui exposent le manque. **L'arrêt** : le Lead veut qu'Alice s'arrête ; tuer son thread brutalement peut laisser des fichiers à moitié écrits — il faut une poignée de main : le Lead envoie une requête, Alice confirme après avoir terminé proprement. **L'approbation de plan** : Bob veut refactorer le module d'authentification, opération risquée ; le Lead doit relire le plan de Bob et l'approuver avant que Bob agisse.

Les deux scénarios partagent la même structure : un côté envoie une requête, l'autre répond, les deux messages étant liés par le même identifiant. D'où le triptyque de la session : **`ProtocolState`** (un enregistrement par requête en vol, dans `pending_requests`), un **dispatch par type de message** côté teammate (la fonction `handle_inbox_message`, que la docstring appelle `dispatch_message`), et **`match_response`** côté Lead, qui corrèle la réponse à la requête via `request_id` en validant que le type de réponse correspond au type de requête. La machine à états est minimale et unique pour les deux protocoles : `pending → approved | rejected`, sans retour en arrière, avec rejet des doublons.

Dans le vrai Claude Code (`teammateMailbox.ts`, 1184 lignes), la structure de cœur est la même — `request_id` + requête/réponse approve/reject — avec des différences notables : le shutdown y est une communication à trois temps (`shutdown_request` → `shutdown_approved` **ou** `shutdown_rejected` avec raison → `teammate_terminated` diffusé), suivie du nettoyage système (pane tmux, désassignation des tâches, retrait du membre de la config d'équipe) ; l'approbation de plan est générée par la sortie du *plan mode* (`ExitPlanModeV2Tool.ts`) et peut fixer un `permissionMode` ; et surtout, le vrai CC a un **gating d'exécution** : les opérations à risque non approuvées sont interceptées au niveau des outils. La version pédagogique, elle, ne démontre que le flux de messages — la docstring de `_teammate_submit_plan` l'assume noir sur blanc : c'est une requête « protocolaire », pas une barrière dans le code.

## Vue d'ensemble du fichier

Le fichier compte 880 lignes physiques (numérotation utilisée ci-dessous) ; la carte du wiki indique 737 lignes hors lignes vides. Particularité structurelle : **tout le bloc cron de s14/s15 a été retiré** (scheduler, file, outils), le fichier se recentre sur l'équipe.

| Lignes | Zone | Contenu |
|---|---|---|
| 1–25 | Docstring | Changements vs s15, schéma ASCII du flux requête–réponse |
| 27–49 | Imports & init | Ajout de `field` (dataclasses) pour `created_at` |
| 51–142 | Task system | Repris de [[s12-task-system]] |
| 145–178 | Prompt assembly | Liste d'outils mise à jour (cron retiré, protocoles ajoutés) |
| 181–218 | Outils de base | `safe_path`, `run_bash`, `run_read`, `run_write` |
| 221–258 | Handlers d'outils tâches | `run_create_task` … `run_complete_task` |
| 261–331 | Background tasks | Repris de [[s13-background-tasks]] ; `execute_tool` déplacé plus bas |
| 334–367 | MessageBus | Repris de [[s15-agent-teams]], **+ paramètre `metadata`** |
| 369–413 | **Machine à états (nouveau)** | `ProtocolState`, `pending_requests`, `new_request_id`, `match_response` |
| 416–435 | **Consommateur unifié (nouveau)** | `consume_lead_inbox` |
| 438–595 | **Thread teammate (réécrit)** | Idle loop + `handle_inbox_message` + outil `submit_plan` |
| 598–616 | **`_teammate_submit_plan` (nouveau)** | Le teammate ouvre une requête `plan_approval` |
| 619–654 | **Outils protocole du Lead (nouveau)** | `run_request_shutdown`, `run_request_plan`, `run_review_plan` |
| 657–679 | Autres handlers Lead | `run_spawn_teammate`, `run_send_message`, `run_check_inbox` (modifié) |
| 682–698 | `execute_tool` | Déplacé ici ; outils cron retirés, protocoles ajoutés |
| 701–785 | `TOOLS` | 14 définitions (11 communes + 3 protocoles, cron sorti) |
| 788–801 | Contexte | `update_context` |
| 804–850 | `agent_loop` | **Sans** consommation de `cron_queue` (le cron n'existe plus) |
| 853–880 | REPL `__main__` | Injection d'inbox via `consume_lead_inbox` |

## Constantes et configuration

- **Ligne 30** : `from dataclasses import dataclass, asdict, field` — `field` est nouveau, nécessaire au `default_factory` de `ProtocolState.created_at`. (`from datetime import datetime`, ligne 29, est conservé mais n'est plus utilisé depuis le retrait du cron.)
- **Lignes 147–155** : `PROMPT_SECTIONS` — la liste d'outils perd `schedule_cron, list_crons, cancel_cron` et gagne `request_shutdown, request_plan, review_plan`.
- **Lignes 263–266** : état background, repris de [[s13-background-tasks]].
- **Lignes 336–337** : `MAILBOX_DIR = WORKDIR / ".mailboxes"`, repris de [[s15-agent-teams]].
- **Lignes 366–367** : `BUS = MessageBus()` et `active_teammates` — repris de s15.
- **Ligne 382** : `pending_requests: dict[str, ProtocolState] = {}` — **la table des requêtes en vol**, indexée par `request_id`. C'est l'état partagé de la machine à états ; Lead et teammates (threads du même processus) y lisent et écrivent directement.
- **Lignes 703–785** : `TOOLS` — 14 outils : bash/read/write (704–719), les 5 outils tâches (720–747), les 3 outils équipe de s15 (748–765), et les 3 nouveaux outils protocole : `request_shutdown` (766–770), `request_plan` (771–776), `review_plan` (777–784, avec `request_id`, `approve` booléen, `feedback` optionnel).

## Les fonctions, une à une

### `Task` (dataclass) — lignes 57–64
Reprise de [[s12-task-system]] sans modification.

### `_task_path(task_id)` — lignes 67–68
Reprise de [[s12-task-system]] sans modification.

### `create_task(subject, description, blockedBy)` — lignes 71–80
Reprise de [[s12-task-system]] sans modification.

### `save_task(task)` / `load_task(task_id)` — lignes 83–84 / 87–88
Reprises de [[s12-task-system]] sans modification.

### `list_tasks()` — lignes 91–93
Reprise de [[s12-task-system]] sans modification.

### `get_task(task_id)` — lignes 96–99
Reprise de [[s12-task-system]] sans modification.

### `can_start(task_id)` — lignes 102–111
Reprise de [[s12-task-system]] sans modification.

### `claim_task(task_id, owner)` — lignes 114–126
Reprise de [[s12-task-system]] sans modification.

### `complete_task(task_id)` — lignes 129–142
Reprise de [[s12-task-system]] sans modification.

### `assemble_system_prompt(context)` — lignes 158–165
Reprise de [[s10-system-prompt]] sans modification.

### `get_system_prompt(context)` — lignes 171–178
Reprise de [[s10-system-prompt]] sans modification.

### `safe_path(p)` — lignes 183–187
Reprise des sessions fondamentales (voir [[s03-permission]]) sans modification.

### `run_bash` / `run_read` / `run_write` — lignes 190–198 / 201–208 / 211–218
Reprises de [[s13-background-tasks]] / [[s02-tool-use]] sans modification.

### `run_create_task` … `run_complete_task` — lignes 223–258
Handlers repris de [[s12-task-system]] sans modification : `run_create_task` (223–228), `run_list_tasks` (231–243), `run_get_task` (246–250), `run_claim_task` (253–254), `run_complete_task` (257–258).

### `is_slow_operation` / `should_run_background` — lignes 269–277 / 280–284
Reprises de [[s13-background-tasks]] sans modification.

### `start_background_task(block)` — lignes 287–308
Reprise de [[s13-background-tasks]] sans modification. Notez qu'elle appelle `execute_tool`, défini ici **après** elle (ligne 684) — résolu à l'exécution.

### `collect_background_results()` — lignes 311–331
Reprise de [[s13-background-tasks]] sans modification.

### `MessageBus` (classe) — lignes 340–363

Reprise de [[s15-agent-teams]] avec **une extension décisive** : le paramètre `metadata`.

```python
    def send(self, from_agent: str, to_agent: str, content: str,
             msg_type: str = "message", metadata: dict = None):
        msg = {"from": from_agent, "to": to_agent,
               "content": content, "type": msg_type,
               "ts": time.time(), "metadata": metadata or {}}
```

`send` (345–354) embarque désormais un dict `metadata` (défaut `{}` via `metadata or {}`) — c'est là que voyagent `request_id` et `approve`, les deux champs qui font tenir tout le protocole. Le log console affiche aussi le type : `[bus] lead → alice: (shutdown_request) ...`. `read_inbox` (356–363) est inchangée : lecture destructive (read + unlink), toujours sans verrou fichier.

### `ProtocolState` (dataclass) — lignes 371–379 — NOUVEAU

L'état d'une requête protocolaire — le nœud de la machine à états :

```python
@dataclass
class ProtocolState:
    request_id: str
    type: str       # "shutdown" | "plan_approval"
    sender: str
    target: str
    status: str     # pending | approved | rejected
    payload: str    # plan text or shutdown reason
    created_at: float = field(default_factory=time.time)
```

Chaque requête naît en `status="pending"` et ne connaît que deux transitions possibles, toutes deux terminales : `pending → approved` ou `pending → rejected`. Le `type` discrimine les deux protocoles supportés ; le `payload` porte le texte du plan (ou la raison du shutdown) ; `created_at` est rempli automatiquement par `default_factory=time.time` (d'où l'import de `field`). `sender`/`target` documentent le sens de la requête : `lead → teammate` pour shutdown, `teammate → lead` pour plan_approval.

### `new_request_id()` — lignes 385–386 — NOUVEAU
Génère `req_{6 chiffres aléatoires}` — la clé de corrélation qui voyagera dans `metadata` à l'aller comme au retour. Même réserve d'unicité que les ids cron de [[s14-cron-scheduler]] : purement probabiliste.

### `match_response(response_type, request_id, approve)` — lignes 389–413 — NOUVEAU

Côté Lead, l'unique point de transition de la machine à états :

```python
def match_response(response_type: str, request_id: str, approve: bool):
    state = pending_requests.get(request_id)
    if not state:
        print(f"  \033[31m[protocol] unknown request_id: {request_id}\033[0m")
        return
    # Validate response type matches request type
    if state.type == "shutdown" and response_type != "shutdown_response":
        ...
        return
    if state.type == "plan_approval" and response_type != "plan_approval_response":
        ...
        return
    if state.status != "pending":
        print(f"  \033[33m[protocol] {request_id} already {state.status}, "
              f"ignoring duplicate\033[0m")
        return
    state.status = "approved" if approve else "rejected"
```

Quatre gardes successives avant la transition, chacune répondant à une attaque ou un accident précis :
- **392–395** : `request_id` inconnu → on ignore (réponse à une requête jamais émise, ou déjà nettoyée).
- **397–404** : **validation croisée du type** — une `shutdown_response` ne peut pas résoudre une requête `plan_approval`, et inversement. Le README insiste : sans cette garde, une réponse de shutdown égarée pourrait « approuver » un plan.
- **405–408** : protection contre les doublons — si le statut n'est plus `pending`, la machine à états est déjà résolue ; le message est loggué et ignoré. Les transitions sont à sens unique.
- **409** : la transition elle-même, pilotée par le booléen `approve` venu des `metadata`.

À noter : la fonction ne **supprime pas** l'entrée de `pending_requests` — les requêtes résolues restent consultables (au prix d'une table qui ne se vide jamais).

### `consume_lead_inbox(route_protocol)` — lignes 420–435 — NOUVEAU

Le correctif d'architecture de la session (le commentaire de bloc 416–418 l'annonce comme « s16 fix ») :

```python
def consume_lead_inbox(route_protocol: bool = True) -> list[dict]:
    """Read Lead's inbox. Route protocol responses, return all messages.
    Called by both run_check_inbox() and main loop to avoid
    messages being consumed without protocol routing."""
    msgs = BUS.read_inbox("lead")
    if not msgs:
        return []
    if route_protocol:
        for msg in msgs:
            meta = msg.get("metadata", {})
            req_id = meta.get("request_id", "")
            msg_type = msg.get("type", "")
            if req_id and msg_type.endswith("_response"):
                approve = meta.get("approve", False)
                match_response(msg_type, req_id, approve)
    return msgs
```

Le problème résolu : la lecture d'inbox étant **destructive** (read + unlink), si l'outil `check_inbox` et la boucle principale lisaient chacun de leur côté, l'un pourrait consommer une réponse protocolaire sans mettre à jour `pending_requests` — la requête resterait `pending` pour toujours. La solution : un seul point de consommation, qui route d'abord (lignes 428–434 : tout message porteur d'un `request_id` et dont le type se termine par `_response` passe par `match_response`), puis retourne **tous** les messages (protocolaires inclus) à l'appelant pour affichage/injection. Le suffixe `_response` sert de convention de nommage extensible — un futur `foo_approval_response` serait routé sans changer cette fonction.

### `spawn_teammate_thread(name, role, prompt)` — lignes 440–595 — RÉÉCRIT

Reprise de [[s15-agent-teams]], profondément remaniée : le teammate ne s'arrête plus après 10 tours, il **attend**. Le prompt système (447–449) mentionne désormais les messages de protocole.

#### `handle_inbox_message(name, msg, messages)` (fermeture interne) — lignes 451–475

Le *dispatcher* côté teammate — c'est la fonction que la docstring du fichier appelle `dispatch_message` :

```python
    def handle_inbox_message(name: str, msg: dict, messages: list) -> bool:
        """Dispatch incoming protocol messages by type.
        Returns True if teammate should stop."""
        msg_type = msg.get("type", "message")
        meta = msg.get("metadata", {})
        req_id = meta.get("request_id", "")

        if msg_type == "shutdown_request":
            BUS.send(name, "lead", "Shutting down gracefully.",
                     "shutdown_response",
                     {"request_id": req_id, "approve": True})
            return True  # stop the loop

        if msg_type == "plan_approval_response":
            approve = meta.get("approve", False)
            if approve:
                messages.append({"role": "user",
                    "content": f"[Plan approved] Proceed with the task."})
            else:
                messages.append({"role": "user",
                    "content": f"[Plan rejected] Feedback: {msg['content']}"})

        return False  # continue
```

- **458–464** : sur `shutdown_request`, le teammate répond immédiatement `shutdown_response` avec **le même `request_id`** (recopié des metadata entrantes — c'est ce recopiage qui boucle la corrélation) et `approve: True`, puis retourne `True` → arrêt de la boucle. Version simplifiée et toujours docile : le vrai CC distingue `shutdown_approved` / `shutdown_rejected` (avec raison) — ici le teammate ne refuse jamais.
- **466–473** : sur `plan_approval_response`, le verdict est traduit en message utilisateur dans l'historique du teammate : `[Plan approved] Proceed...` ou `[Plan rejected] Feedback: ...`. C'est le LLM qui en tire les conséquences — aucun blocage de code.
- Le booléen de retour fait office de signal de vie : `True` = s'arrêter, `False` = continuer. Ajouter un protocole = ajouter une branche `if`.

#### La boucle `run()` avec idle loop — lignes 477–590

Structure générale : `while not shutdown_requested:` (513) remplace le `for _ in range(10)` de s15.

Phase 1 — tri de l'inbox avant chaque tour LLM (514–531) :

```python
            inbox = BUS.read_inbox(name)
            should_stop = False
            non_protocol = []
            for msg in inbox:
                if msg.get("type") in ("shutdown_request", "plan_approval_response"):
                    should_stop = handle_inbox_message(name, msg, messages)
                    if should_stop:
                        break
                else:
                    non_protocol.append(msg)
            if should_stop:
                shutdown_requested = True
                break
            if non_protocol:
                inbox_json = json.dumps(non_protocol)
                messages.append({"role": "user",
                    "content": "<inbox>" + inbox_json + "</inbox>"})
```

Les messages sont **séparés en deux flux** : les protocolaires passent par le dispatcher (et peuvent stopper le thread), les autres sont injectés en bloc `<inbox>` comme en s15. Un `shutdown_request` reçu ici court-circuite tout.

Phase 2 — le tour LLM (534–539), identique à s15 (`messages[-20:]`, `except Exception: break`).

Phase 3 — **l'idle loop**, la nouveauté centrale (542–564) :

```python
            if response.stop_reason != "tool_use":
                # Idle: wait for inbox messages instead of exiting
                # Real CC sends idle_notification to Lead here
                while not shutdown_requested:
                    time.sleep(1)
                    inbox = BUS.read_inbox(name)
                    if not inbox:
                        continue
                    for msg in inbox:
                        if msg.get("type") in ("shutdown_request", "plan_approval_response"):
                            should_stop = handle_inbox_message(name, msg, messages)
                            if should_stop:
                                shutdown_requested = True
                                break
                        else:
                            non_protocol.append(msg)
                    if shutdown_requested:
                        break
                    if non_protocol:
                        ...
                        break  # back to LLM turn with new messages
```

Quand le modèle rend la main (pas de `tool_use`), le teammate de s15 mourait ; celui de s16 **scrute son inbox chaque seconde**. Trois sorties possibles : `shutdown_request` → fin propre ; nouveau message ordinaire → injection en `<inbox>` puis `break` pour relancer un tour LLM ; sinon, attente indéfinie. Le commentaire (544) situe l'écart avec le vrai CC : à cet endroit, le teammate réel enverrait `idle_notification` au Lead, qui saurait ainsi qu'il est disponible pour une nouvelle tâche.

Deux fragilités dans cette phase (voir Pièges) : la liste `non_protocol`, déjà injectée en phase 1, **n'est pas réinitialisée** avant l'idle loop ; et au `break` de reprise, l'exécution retombe dans la phase 4 avec l'ancienne `response` sans `tool_use`.

Phase 4 — exécution des tool calls (566–575), identique à s15, suivie de l'épilogue (577–590) repris de s15 : extraction du dernier texte assistant (for/else imbriqués), envoi du résumé `result` au Lead, désinscription de `active_teammates`.

Le jeu d'outils du teammate (479–504) gagne un cinquième outil : **`submit_plan`** (499–503), branché sur `_teammate_submit_plan` via lambda (509).

### `_teammate_submit_plan(from_name, plan)` — lignes 598–616 — NOUVEAU

Le côté teammate du protocole d'approbation de plan :

```python
    req_id = new_request_id()
    pending_requests[req_id] = ProtocolState(
        request_id=req_id, type="plan_approval",
        sender=from_name, target="lead",
        status="pending", payload=plan)
    BUS.send(from_name, "lead", plan,
             "plan_approval_request",
             {"request_id": req_id})
    return f"Plan submitted ({req_id}). Waiting for approval..."
```

C'est ici que naît la requête : id frais, `ProtocolState` enregistré **directement dans `pending_requests`** — possible uniquement parce que les teammates sont des threads du même processus, qui partagent la mémoire ; dans une architecture multi-processus (le vrai CC), cet état devrait transiter par messages. La longue docstring (599–607) est la plus importante du fichier : « This is a protocol-level request, not a code-level gate. After submitting, the teammate's thread continues running — it can still call bash/write/etc. Real enforcement relies on the model waiting for the approval response before acting. » Le respect du protocole repose sur l'obéissance du LLM au `"Waiting for approval..."` retourné — un vrai gating exigerait de bloquer le dispatch d'outils du teammate jusqu'à la réponse.

### `run_request_shutdown(teammate)` — lignes 621–632 — NOUVEAU

Le côté Lead du handshake d'arrêt :

```python
    req_id = new_request_id()
    pending_requests[req_id] = ProtocolState(
        request_id=req_id, type="shutdown",
        sender="lead", target=teammate,
        status="pending", payload="")
    BUS.send("lead", teammate, "Please shut down gracefully.",
             "shutdown_request",
             {"request_id": req_id})
```

Symétrique de `_teammate_submit_plan` : créer l'état `pending`, envoyer la requête avec le `request_id` en metadata. La résolution viendra plus tard, quand `consume_lead_inbox` croisera la `shutdown_response` du teammate et que `match_response` fera passer le statut à `approved`.

### `run_request_plan(teammate, task)` — lignes 635–639 — NOUVEAU
Demande à un teammate de soumettre un plan — mais, asymétrie voulue : ce message part en simple `"message"` (texte libre), **sans** `request_id` ni `ProtocolState`. C'est le teammate qui, en appelant `submit_plan`, ouvrira formellement la requête protocolaire. Le Lead ne fait ici que suggérer.

### `run_review_plan(request_id, approve, feedback)` — lignes 642–654 — NOUVEAU

Le verdict du Lead sur un plan soumis :

```python
    state = pending_requests.get(request_id)
    if not state:
        return f"Request {request_id} not found"
    if state.status != "pending":
        return f"Request {request_id} already {state.status}"
    state.status = "approved" if approve else "rejected"
    BUS.send("lead", state.sender, feedback or ("Approved" if approve else "Rejected"),
             "plan_approval_response",
             {"request_id": request_id, "approve": approve})
```

Particularité : pour ce protocole, c'est le **Lead qui fait lui-même la transition d'état** (ligne 648) avant d'envoyer la `plan_approval_response` au teammate — logique, puisque la requête est de sens teammate→lead, le résolveur est le Lead. Mêmes gardes que `match_response` (inconnu, déjà résolu). Le `feedback` optionnel voyage dans le `content` ; côté teammate, il sera réinjecté dans `[Plan rejected] Feedback: ...`. Dans le vrai CC, la réponse peut en plus fixer le `permissionMode` du teammate (« approuvé, mais reste en plan mode »).

### `run_spawn_teammate(name, role, prompt)` — lignes 659–660
Repris de [[s15-agent-teams]] sans modification.

### `run_send_message(to, content)` — lignes 663–665
Repris de [[s15-agent-teams]] sans modification (expéditeur `"lead"` codé en dur).

### `run_check_inbox()` — lignes 668–679 — MODIFIÉ

Réécrit sur `consume_lead_inbox(route_protocol=True)` : la consultation d'inbox par l'outil **route donc aussi** les réponses protocolaires (plus de risque de consommer une réponse sans transition d'état). L'affichage est enrichi du type et du `request_id` : `[alice] [shutdown_response req:req_004281] Shutting down gracefully.`

### `execute_tool(block)` — lignes 684–698 — MODIFIÉ
Déplacé après tous les handlers (en s15 il était dans le bloc background). La table perd les trois entrées cron et gagne `request_shutdown`, `request_plan`, `review_plan` (693–694).

### `TOOLS` — lignes 703–785
14 définitions : voir « Constantes et configuration ». Solde inchangé par rapport à s15 (14), mais composition différente : − 3 cron, + 3 protocole.

### `update_context(context, messages)` — lignes 790–801
Reprise de s15 sans modification.

### `agent_loop(messages, context)` — lignes 806–850
Reprise de [[s15-agent-teams]], **moins** la consommation de `cron_queue` en tête de boucle (le cron n'existe plus dans ce fichier). Le reste est identique : dispatch background, fusion des `tool_result` et notifications en un message user unique.

### Bloc `__main__` — lignes 853–880

Identique au REPL de s15 à une substitution près (lignes 872–879) :

```python
        # Check inbox → route protocol + inject into history
        inbox_msgs = consume_lead_inbox(route_protocol=True)
        if inbox_msgs:
            inbox_text = "\n".join(
                f"From {m['from']}: {m['content'][:200]}" for m in inbox_msgs)
            history.append({"role": "user",
                            "content": f"[Inbox]\n{inbox_text}"})
```

Le `BUS.read_inbox("lead")` direct de s15 est remplacé par `consume_lead_inbox` : la boucle principale et l'outil `check_inbox` passent par le même entonnoir — routage protocolaire garanti avant injection dans `history`.

## Ce qui change par rapport à [[s15-agent-teams]]

- **Nouvelle machine à états** : `ProtocolState` (371–379), `pending_requests` (382), `new_request_id` (385–386), `match_response` (389–413) — corrélation par `request_id`, validation de type, transitions `pending → approved | rejected` à sens unique, doublons ignorés.
- **`MessageBus.send` étendu** : paramètre `metadata` (345–354) pour transporter `request_id` et `approve` ; le type du message apparaît dans les logs.
- **Teammate réécrit** : la borne `for _ in range(10)` devient `while not shutdown_requested` + **idle loop** (542–564) — le teammate inactif scrute son inbox chaque seconde au lieu de mourir ; dispatch des messages protocolaires par `handle_inbox_message` (451–475) ; nouvel outil teammate `submit_plan` (499–503, handler 509), soit 5 outils au lieu de 4.
- **Nouveau point de consommation unifié** `consume_lead_inbox` (420–435), utilisé par `run_check_inbox` (668–679) et le `__main__` (873).
- **3 nouveaux outils Lead** : `request_shutdown` (621–632), `request_plan` (635–639), `review_plan` (642–654).
- **Nouveaux types de messages** : `shutdown_request`/`shutdown_response`, `plan_approval_request`/`plan_approval_response` s'ajoutent à `message`/`result`.
- **Retrait complet du cron** : `CronJob`, matching, validation, scheduler, file, persistance et les 3 outils `schedule_cron`/`list_crons`/`cancel_cron` de [[s14-cron-scheduler]] disparaissent (l'import `datetime` reste, désormais inutilisé). Le nombre d'outils Lead reste 14.

## Pièges et détails d'implémentation

- **Protocole ≠ barrière** : après `submit_plan`, rien dans le code n'empêche le teammate d'appeler `bash` ou `write_file` sans attendre l'approbation — seule la consigne textuelle retient le modèle. Le vrai CC intercepte réellement les opérations non approuvées (docstring de `_teammate_submit_plan`, lignes 599–607).
- **Reprise après idle fragile** : quand l'idle loop sort par `break` (nouveau message, ligne 564), l'exécution retombe dans la phase « Execute tool calls » avec **l'ancienne réponse** sans `tool_use` → `results` vide → `messages.append({"role": "user", "content": []})` (575). Ce message user à contenu vide risque un rejet API au tour suivant, avalé par `except Exception: break` : le chemin « le teammate idle reprend du travail » peut donc échouer silencieusement. (Sur le chemin shutdown, le message vide est appendu mais jamais envoyé — sans conséquence.)
- **`non_protocol` n'est pas réinitialisée entre la phase pré-tour et l'idle loop** : des messages déjà injectés en `<inbox>` avant le tour LLM peuvent être réinjectés une seconde fois si le teammate passe en idle et reçoit du nouveau courrier — doublons possibles dans son historique.
- **L'état protocolaire vit en mémoire partagée** : `_teammate_submit_plan` (thread teammate) écrit directement dans `pending_requests`, que lit le Lead. Ça ne marche que parce que tout est dans un seul processus ; le `request_id` dans les `metadata` est, lui, le mécanisme qui survivrait à une vraie séparation par processus.
- **Deux résolveurs pour une même machine à états** : la requête `shutdown` est résolue par `match_response` (côté Lead, à la lecture de la réponse), la requête `plan_approval` par `run_review_plan` (côté Lead, à l'émission du verdict). Même table, mêmes états, mais deux chemins de transition — facile à confondre à la première lecture.
- **Nommage docstring vs code** : la docstring du fichier (ligne 13) et le README annoncent `dispatch_message`, `handle_shutdown_request`, `handle_plan_response` ; le code implémente tout cela dans l'unique fermeture `handle_inbox_message`. De même, le teammate répond `shutdown_response` là où le vrai CC distingue `shutdown_approved`/`shutdown_rejected` (et mélange `request_id`/`requestId` selon les protocoles).
- **`pending_requests` ne se vide jamais** : les requêtes résolues restent en mémoire — pratique pour l'audit, fuite lente en théorie.

## Liens

- Session précédente : [[s15-agent-teams]]
- Session suivante : [[s17-autonomous-agents]]
- Sessions liées : [[s03-permission]] (l'ancêtre mono-agent de l'approbation d'opérations), [[s05-todo-write]] et [[s12-task-system]] (l'état structuré comme contrat), [[s14-cron-scheduler]] (le bloc cron retiré ici), [[s20-comprehensive]] (synthèse finale)
