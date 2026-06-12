---
title: "agents.py · Subagents, équipe, workers"
phase: "Multi-agents"
fichier: "src_scratch/agents.py"
lignes: 212
tags: [subagent, team, fsm, workers, delegation, req-id]
---

# agents.py · Subagents, équipe, workers

> **En une phrase** : les trois formes de délégation du harness — subagent éphémère (s04), équipe persistante dialoguant par mailbox avec FSM (s09/s10), workers autonomes qui réclament des tâches sur le board (s11) — toutes bâties sur la **même** brique : `loop.agent_loop`, la vraie boucle avec le vrai dispatch.

## Rôle dans le harness

Dans le repo source, chaque forme de délégation vit dans sa session avec sa propre copie de la boucle : s04 (subagent), s09 (équipiers + mailboxes), s10 (protocole FSM), s11 (workers sur le board), et s22 qui ré-implémente des workers distribués en exécutant… tout `tool_use` comme du bash. Ce module condense les quatre mécanismes en 212 lignes autour d'un principe unique, énoncé dès la docstring (lignes 4–5) : *« Équipiers et workers passent par loop.agent_loop (façade sync) : vraie boucle, vrai dispatch — pas le raccourci « tout tool_use = bash » de s22. »*

La concaténation des blocs texte d'une réponse API — utilisée trois fois ici, pour le retour du subagent, la réponse d'un équipier et le résultat de tâche d'un worker — n'est plus une fonction locale : c'est `text_of`, importée de [[core-py]] (ligne 14). Le helper privé `_text_of` qui vivait en tête de fichier a disparu au profit de cette brique partagée.

Trois étages, du plus simple au plus autonome. Le **subagent** : une boucle isolée à contexte vierge, lancée et attendue de façon synchrone, dont seul le texte final remonte — l'isolation de contexte comme service. L'**équipe** : des threads daemon persistants (explorer, writer) qui sondent leur boîte aux lettres ([[mailbox-py]]) et répondent au lead, avec un état consultable (FSM réduit à IDLE/RESPOND — réellement branché, contrairement à s10). Les **workers** : des threads qui réclament atomiquement des tâches sur le board de [[tasks-py]] (`claim_next_task`) et les traitent jusqu'à épuisement du board.

Le module expose aussi trois outils au modèle via `register_tool` de [[tools-py]] : `subagent` (à l'import), `send_to_teammate` et `list_teammates` (au démarrage de l'équipe, car l'enum des destinataires dépend de l'équipe réelle).

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–6 | Docstring | Les trois formes de délégation ; refus du raccourci s22 |
| 8–17 | Imports | `paint` et `text_of` de core, `agent_loop`, mailbox, tasks (claim/complete/fail), `register_tool` |
| 21–50 | Subagent (s04) | `SUBAGENT_SYSTEM`, `spawn_subagent`, enregistrement de l'outil `subagent` |
| 53–74 | Équipe — données | `TEAMMATES`, `_ACTIVE_TEAM`, `AgentState` (FSM s10) |
| 77–131 | Équipe — classe | `Team` : start / stop / status / `_teammate_loop` |
| 134–174 | Équipe — côté lead | `send_to_teammate` (corrélation `req_id`), `_register_team_tools` |
| 177–212 | Workers (s11) | `run_autonomous_agent`, `start_workers` |

## Constantes et configuration

- **`SUBAGENT_SYSTEM` (lignes 23–26)** : le system prompt des subagents — « working on a specific subtask at `os.getcwd()` … Summarize your result clearly at the end ». La consigne de résumé final n'est pas décorative : c'est ce résumé qui constitue la valeur de retour de l'outil.
- **`TEAMMATES` (lignes 55–66)** : les deux spécialistes repris des prompts de la source — `explorer` (compréhension de code : bash, read, glob, grep) et `writer` (création/édition : write, read, bash). Un dict nom → system prompt ; `Team` accepte n'importe quel dict de même forme.
- **`_ACTIVE_TEAM` (ligne 68)** : global de module désignant l'équipe visée par `send_to_teammate` — posé par `Team.start()`, effacé par `Team.stop()`. Une seule équipe active à la fois.

## Les fonctions, une à une

### `spawn_subagent(task, system=None, tools=None)` — lignes 29–36

```python
def spawn_subagent(task: str, system: str | None = None, tools: list[dict] | None = None) -> str:
    """Boucle isolée à contexte vierge ; seul le texte final remonte au parent."""
    print(paint(f"  [subagent] lancé pour: {task[:60]}…", "magenta"))
    final = agent_loop([{"role": "user", "content": task}],
                       tools=tools, system=system or SUBAGENT_SYSTEM)
    text = text_of(final)
```

Tout s04 en huit lignes : un historique neuf (`[{"role": "user", ...}]`), la boucle complète de [[loop-py]] (permissions, hooks, dispatch parallèle, cache compris), et au retour seulement le texte du dernier tour, extrait par `text_of` de [[core-py]] (le pont entre une réponse API structurée et la chaîne qu'attendent les canaux inter-agents ; il écarte les blocs `tool_use` résiduels). Le parent ne voit jamais les tours intermédiaires du subagent — c'est ça, l'isolation de contexte : explorer dix fichiers coûte au parent la taille du résumé, pas celle de l'exploration. Bloquant : l'appelant attend la fin de la sous-boucle.

### Enregistrement de l'outil `subagent` — lignes 39–50

```python
register_tool({
    "name": "subagent",
    "description": ("Spawn a fresh subagent to handle a subtask in an isolated context. "
                    "Use for exploration, risky operations, or tasks that shouldn't "
                    "pollute the main conversation history."),
    ...
}, sync_fn=lambda inp: spawn_subagent(inp["task"]))
```

Exécuté **à l'import du module** : importer `agents` suffit à donner l'outil `subagent` au modèle (les deux autres outils, eux, attendent `Team.start()`). La description guide l'usage : exploration, opérations risquées, tâches qui pollueraient l'historique principal.

### `AgentState` (Enum) — lignes 71–74

```python
class AgentState(Enum):
    """FSM s10 réduit aux états réellement exercés par la boucle équipier."""
    IDLE = "idle"
    RESPOND = "respond"
```

La FSM de s10 ramenée à sa partie vivante. La source déclarait un protocole d'états plus riche (dont un WAITING qui était une impasse : aucun chemin n'en sortait) mais ne l'appliquait jamais au flux réel — code mort. Ici, deux états seulement, mais **réellement** posés et lus (voir `_teammate_loop` et `status`).

### `Team` — lignes 77–131

Un thread daemon par équipier, un dialogue par mailbox, des états consultables. La classe est construite pour être démarrée/arrêtée à la demande (commande `:team on|off` du REPL).

### `Team.__init__(teammates=None)` — lignes 80–85

État minimal : le dict des équipiers (défaut `TEAMMATES`), une mailbox encore nulle (choisie au `start`), un `threading.Event` d'arrêt, la liste des threads et le dict des états FSM.

### `Team.start(mailbox=None)` — lignes 87–98

```python
    def start(self, mailbox: Mailbox | None = None) -> None:
        global _ACTIVE_TEAM
        self.mailbox = mailbox or get_mailbox("auto")
        self._stop.clear()
        for name, prompt in self.teammates.items():
            self._states[name] = AgentState.IDLE
            t = threading.Thread(target=self._teammate_loop, args=(name, prompt), daemon=True)
            t.start()
            self._threads.append(t)
        _ACTIVE_TEAM = self
        _register_team_tools(self.teammates)  # enum des destinataires bâti sur l'équipe
```

Trois actes : choisir le backend de messagerie (celui passé par [[main-py]] via `--backend`, sinon « auto »), lancer un thread daemon par équipier (chacun démarre en `IDLE`), puis se déclarer équipe active et enregistrer les outils du lead. L'ordre compte : les threads sondent déjà leur boîte quand `send_to_teammate` devient disponible — aucun message ne peut partir vers une équipe pas encore à l'écoute.

### `Team.stop()` — lignes 100–108

Lève l'`Event` d'arrêt, attend chaque thread au plus 2 s (`join(timeout=2)` — un équipier en plein `agent_loop` ne s'interrompt pas en plein vol, mais les threads sont daemon : ils ne retiendront pas le processus), vide la liste des threads et libère `_ACTIVE_TEAM` — seulement si c'est bien cette équipe qui était active (`if _ACTIVE_TEAM is self`), pour ne pas écraser une équipe relancée entre-temps.

### `Team.status()` — lignes 110–113

Rend visible la FSM : `(équipe arrêtée)` si aucun thread, sinon une ligne `- nom: état` par équipier (`idle` ou `respond`). C'est la sortie de la commande `:team status` du REPL.

### `Team._teammate_loop(name, prompt)` — lignes 115–131

La boucle de vie d'un équipier — et la correction du code mort de s10 :

```python
    def _teammate_loop(self, name: str, prompt: str) -> None:
        # FIX(mekicode): FSM s10 réellement branché sur le flux (code mort dans la source) —
        # IDLE pendant le sondage, RESPOND pendant le traitement, retour IDLE garanti.
        while not self._stop.is_set():
            for msg in self.mailbox.receive(name, timeout=0.5):
                self._states[name] = AgentState.RESPOND
                sender = msg.get("from", "lead")
                ...
                try:
                    reply = text_of(agent_loop([{"role": "user", "content": msg["body"]}],
                                               system=prompt))
                except Exception as e:
                    reply = f"Erreur de l'équipier {name}: {e}"
                finally:
                    self._states[name] = AgentState.IDLE
                self.mailbox.send(sender, name, reply, req_id=msg.get("req_id"))
```

- **Sondage** : `receive(name, timeout=0.5)` — réactif sans busy-wait, et l'`Event` d'arrêt est re-testé toutes les 0,5 s au pire.
- **Traitement** : chaque message déclenche une **vraie** boucle agent (contexte vierge, system prompt du spécialiste). L'état passe à `RESPOND` pendant le travail ; le `finally` garantit le retour à `IDLE` même si la boucle lève.
- **Réponse** : une exception devient une réponse d'erreur textuelle — le lead reçoit toujours quelque chose, jamais un silence. Et la réponse reprend le `req_id` de la requête (`req_id=msg.get("req_id")`) : c'est la moitié « équipier » du contrat de corrélation, l'autre moitié étant dans `send_to_teammate`.

### `send_to_teammate(name, message, timeout=120)` — lignes 134–153

Le côté lead du dialogue : délégation **bloquante**, corrélée par `req_id`.

```python
    req_id = uuid.uuid4().hex[:8]
    team.mailbox.send(name, "lead", message, req_id=req_id)
    print(paint(f"  [lead] attend la réponse de {name}…", "dim"))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for r in team.mailbox.receive("lead", timeout=1.0):
            if r.get("req_id") == req_id:
                return f"Réponse de {r.get('from', name)}:\n{r['body']}"
            # FIX(mekicode): réponse tardive d'une requête expirée → JETÉE (s09 la
            # drainait et la présentait comme la réponse de l'appel suivant)
            print(paint(f"  [lead] réponse tardive de {r.get('from', '?')} ignorée "
                        f"(req_id {r.get('req_id')} ≠ {req_id})", "yellow"))
    return f"Timeout: '{name}' n'a pas répondu en {timeout:.0f} s."
```

- **Gardes d'entrée (lignes 136–140)** : pas d'équipe active ou destinataire inconnu → message d'erreur textuel (donnée pour le modèle, pas exception).
- **Corrélation (lignes 141–152)** : un `req_id` de 8 hexas par requête ; seule la réponse portant **ce** `req_id` est acceptée. Toute autre réponse trouvée dans la boîte du lead est signalée et jetée.
- **Timeout (ligne 153)** : au-delà de 120 s, retour explicite — et grâce au `req_id`, la réponse qui arriverait après coup sera reconnue comme étrangère par l'appel suivant au lieu de lui être attribuée.

### `_register_team_tools(teammates)` — lignes 156–174

Enregistre les deux outils du lead, **au `start()`** et non à l'import :

```python
            "properties": {
                "name": {"type": "string", "enum": list(teammates)},
```

L'enum des destinataires est construit sur l'équipe réellement démarrée — le modèle ne peut syntaxiquement pas adresser un équipier qui n'existe pas. `list_teammates` rend la liste des spécialistes avec les 80 premiers caractères de leur prompt (assez pour saisir le rôle). Redémarrer une équipe différente ré-enregistre les outils : `register_tool` de [[tools-py]] remplace l'entrée existante, l'enum suit l'équipe.

### `run_autonomous_agent(name, max_idle=3)` — lignes 179–202

Le cycle s11 : réclamer, traiter, marquer — sans aucun message ni supervision.

```python
    idle = 0
    while idle < max_idle:
        task = claim_next_task(name)
        if task is None:
            idle += 1
            time.sleep(1.0)
            continue
        idle = 0
        ...
        try:
            # FIX(mekicode): vraie boucle + vrai dispatch (s22 exécutait tout tool_use comme bash)
            final = agent_loop([{"role": "user", "content": task["description"]}], system=system)
            complete_task(task["id"], text_of(final))
        except Exception as e:
            fail_task(task["id"], str(e))
```

- **`claim_next_task(name)`** ([[tasks-py]]) est atomique sous verrou : deux workers ne peuvent pas réclamer la même tâche — c'est le board qui coordonne, pas les agents entre eux.
- **Compteur d'oisiveté** : `max_idle` tours vides espacés d'une seconde, puis arrêt propre — un worker ne sonde pas le board pour l'éternité. Toute tâche obtenue remet le compteur à zéro.
- **Issue garantie** : chaque tâche réclamée finit `complete` (avec le texte final comme résultat) ou `failed` (avec l'erreur) — jamais bloquée en `in_progress`.

### `start_workers(n=2)` — lignes 205–212

Lance `n` workers (`worker-1`, `worker-2`, …) en threads daemon et retourne les threads — l'appelant peut les `join` ou les laisser vivre. C'est la cible de la commande `:workers <n>` de [[main-py]].

## Bugs de la source corrigés ici

- **FSM s10 jamais branchée (lignes 116–117, `_teammate_loop`)** — s10 définissait une machine à états complète mais le flux réel des messages ne la consultait ni ne la mettait à jour : code mort, et l'état WAITING était une impasse sans transition sortante. Ici la FSM est réduite aux deux états réellement exercés (`IDLE`/`RESPOND`), posés autour du traitement avec retour à `IDLE` garanti par un `finally`, et rendus observables par `Team.status()`. Une FSM minuscule mais vivante plutôt qu'un protocole riche et mort.
- **Réponse tardive mal attribuée (lignes 149–152, `send_to_teammate`)** — dans s09, après un timeout, la réponse de l'équipier restait dans la boîte du lead ; l'appel suivant la drainait et la présentait comme la sienne — toutes les conversations suivantes décalées d'un cran. Ici chaque requête porte un `req_id` (champ ajouté dans l'enveloppe de [[mailbox-py]]) ; une réponse au `req_id` inattendu est **jetée** avec un warning jaune, jamais attribuée.
- **« Tout tool_use = bash » (ligne 195, `run_autonomous_agent`)** — s22 importait `EXTENDED_DISPATCH` mais sa boucle worker exécutait chaque `tool_use` comme une commande bash, quel que soit l'outil demandé : `read`, `write`, `grep` partaient dans un shell. Ici workers **et** équipiers passent par `loop.agent_loop` — la boucle unique avec le vrai dispatch, les permissions et les hooks. La docstring du module (lignes 4–5) en fait une règle de conception, pas un correctif ponctuel.

## Qui l'utilise

- [[main-py]] — `import agents` (ligne 14), seul importateur dans `src_scratch/` : la commande `:team on|off|status` crée `agents.Team()` et la démarre avec `get_mailbox(args.backend)` (lignes 91–92), `:workers <n>` appelle `agents.start_workers(n)` (ligne 100). Et l'import lui-même enregistre l'outil `subagent` — disponible dans le REPL dès le boot, sans équipe.

## Pièges et détails d'implémentation

- **Effet de bord à l'import** : le `register_tool` des lignes 39–50 s'exécute quand le module est importé — importer `agents` modifie les registres globaux de [[tools-py]]. Voulu (c'est le mécanisme d'extension du harness), mais à savoir : pas d'outil `subagent` tant que personne n'importe `agents`.
- **`_ACTIVE_TEAM` est un singleton de fait** : démarrer une seconde équipe rebinde le global ; `send_to_teammate` parle toujours à la **dernière** équipe démarrée. `stop()` ne libère le global que si l'équipe arrêtée est encore l'active.
- **Appels concurrents de `send_to_teammate`** : tous les leads relèvent la même boîte « lead », et une réponse au mauvais `req_id` est jetée, pas remise en boîte. Deux délégations en parallèle (possible : le dispatch parallèle de [[loop-py]] exécute les outils en `gather`) peuvent donc se manger mutuellement leurs réponses. Le `req_id` protège de la *mauvaise attribution* (le bug s09), pas de la *perte* en cas de concurrence sur la boîte du lead.
- **`stop()` n'interrompt pas un équipier en plein travail** : l'`Event` n'est testé qu'entre deux sondages ; un `agent_loop` en cours va à son terme. Le `join(timeout=2)` rend l'arrêt non bloquant et les threads daemon garantissent que le processus peut quitter.
- **`os.getcwd()` capturé à l'import** : `SUBAGENT_SYSTEM` et `TEAMMATES` figent le répertoire courant dans leurs prompts — lancer le harness depuis `src_scratch/` (convention générale de la spec, cf. [[core-py]]).
- **`agent_loop` = `asyncio.run` par appel** : chaque équipier/worker crée sa propre boucle d'événements dans son thread. C'est précisément la raison d'être de la façade synchrone de [[loop-py]] — `agent_loop_async` ne serait pas appelable directement depuis ces threads.

## Liens

- Modules liés : [[core-py]] (`paint` et `text_of` — concaténation des blocs texte d'une réponse API, utilisé pour le retour du subagent, des équipiers et des workers), [[mailbox-py]] (le canal de l'équipe), [[loop-py]] (la boucle unique que tout agent délégué exécute), [[tasks-py]] (`claim_next_task` / `complete_task` / `fail_task` pour les workers), [[tools-py]] (`register_tool` des trois outils), [[main-py]] (commandes `:team` et `:workers`)
