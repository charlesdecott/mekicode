---
title: "s22 · Mailbox de production"
session: 22
phase: "Entreprise"
fichier: "inspiration/claude-code-from-scratch/s22_production_mailbox.py"
lignes: 370
tags: [redis, pub-sub, mailbox, asyncio, multi-agents, fan-out]
prev: "s21-mcp-runtime"
next: "s23-worktree-advanced"
---

# s22 · Mailbox de production

> **En une phrase** : les boîtes aux lettres JSONL de [[s09-agent-teams]] deviennent des canaux Redis pub/sub cachés derrière une interface abstraite `MailboxBackend` — la logique des agents ne change pas d'une ligne, seul le transport change, et un repli `asyncio.Queue` garde la démo exécutable sans serveur Redis.

## Rôle dans le harness

Dans [[s09-agent-teams]], le lead et ses équipiers communiquent par fichiers JSONL sur disque : chaque agent **sonde** (poll) son fichier-inbox en boucle, avec les problèmes classiques du pattern — latence de polling, verrouillage de fichiers, et surtout impossibilité de sortir d'une seule machine. Le docstring de s22 (lignes 7–10) pose le diagnostic, et sa devise le résume : *« Redis pipes the messages; no JSONL file left waiting »* (ligne 5).

La session ouvre la phase « Enterprise Upgrades » du README : *« Replacing teaching implementations with production-grade alternatives »*. Sa colonne « Upgrades » est explicite — **« Replaces s09 JSONL mailboxes »**. Le pattern JSONL lui-même vient des sessions d'équipes d'agents de learn-claude-code (le repo dont celui-ci est dérivé) ; s22 en est la version industrialisée. Quatre idées structurent le fichier (docstring, lignes 12–21) : l'**abstraction d'interface** (le code agent est identique quel que soit le backend), le **pub/sub** (livraison poussée, plus de polling fichier), la **concurrence asyncio** (lead et équipiers tournent en parallèle dans le même event loop), et le **découplage** (avec Redis, les agents peuvent tourner sur des serveurs différents pourvu qu'ils voient la même instance).

L'idée architecturale durable est la première : `MailboxBackend` est un **port** au sens hexagonal, avec deux **adaptateurs** (`RedisMailbox`, `QueueMailbox`) choisis à l'exécution par une fabrique qui teste la connexion. Le vrai Claude Code, lui, fait communiquer ses subagents en-processus (files asynchrones type `h2A`) — il n'a pas besoin de Redis ; s22 va volontairement au-delà, vers le déploiement multi-machines.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–26 | Shebang & docstring | Devise, diagnostic s09, 4 concepts architecturaux, prérequis Redis |
| 28–35 | Imports stdlib | `asyncio`, `json`, `os`, `sys`, `ABC`, `datetime`, typing |
| 37–44 | Imports core | `client`, `MODEL`, `EXTENDED_TOOLS`, `EXTENDED_DISPATCH`, `async_bash` |
| 46–58 | Dépendance optionnelle | try-import de `redis.asyncio`, drapeau `HAS_REDIS`, `REDIS_URL` |
| 61–81 | **Interface** | `MailboxBackend` (ABC) : `send` / `receive` / `close` |
| 84–144 | **Backend production** | `RedisMailbox` : canaux pub/sub `agent:<nom>:inbox` |
| 147–176 | **Backend de repli** | `QueueMailbox` : files `asyncio.Queue` en mémoire |
| 179–193 | Fabrique | `initialize_mailbox()` : essaie Redis (PING), sinon Queue |
| 196–264 | Worker | `teammate_worker_loop()` : boucle d'agent autonome par équipier |
| 267–305 | Lead | `lead_orchestration_loop()` : fan-out / fan-in / synthèse |
| 308–362 | Runtime | `main()` : équipe alpha/beta, REPL, nettoyage `finally` |
| 365–370 | Point d'entrée | `asyncio.run(main())` |

## Constantes et configuration

- **`HAS_REDIS` (lignes 47–55)** : try-import de `redis.asyncio as aioredis`. Si le paquet manque, le drapeau passe à `False` et deux avertissements jaunes annoncent le repli sur `asyncio.Queue` — la démo reste exécutable sans aucune dépendance externe.
- **`REDIS_URL` (ligne 58)** : `os.getenv("REDIS_URL", "redis://localhost:6379")` — l'URL du serveur, surchargeables par variable d'environnement, défaut = Redis local sur le port standard.
- La composition de l'équipe (`TEAM_DEF`) n'est pas une constante de module : elle est locale à `main()` (lignes 320–323, voir plus bas).

## Les fonctions, une à une

### `MailboxBackend` (classe abstraite) — lignes 63–81

Le contrat de communication, et rien d'autre :

```python
class MailboxBackend(ABC):
    """
    Abstract Base Class defining the contract for agent communication.
    """

    @abstractmethod
    async def send(self, to_agent: str, message: Dict[str, Any]) -> None:
        """Sends a message to a specific agent's inbox."""
        pass

    @abstractmethod
    async def receive(self, agent_name: str, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        """Awaits and retrieves a message from the agent's inbox."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Cleans up backend resources (connections, threads, etc.)."""
        pass
```

Trois méthodes, toutes `async` : envoyer à un destinataire nommé, attendre un message avec timeout (retour `None` si rien), libérer les ressources. Les messages sont de simples `dict` — le format (`from`, `to`, `type`, `body`) est une convention des appelants, pas un schéma imposé par l'interface. C'est ce contrat minimal qui permet à `teammate_worker_loop` et `lead_orchestration_loop` d'ignorer totalement le transport.

### `RedisMailbox.__init__(url)` et `_get_channel_name(agent_name)` — lignes 89–98

```python
    def __init__(self, url: str):
        """Initializes the Redis connection."""
        # Create a Redis client with auto-decoding for string data
        self._redis = aioredis.from_url(url, decode_responses=True)
        # Store active PubSub subscription objects to prevent redundant subscriptions
        self._pubsubs: Dict[str, Any] = {}

    def _get_channel_name(self, agent_name: str) -> str:
        """Generates a Redis channel key for a given agent name."""
        return f"agent:{agent_name}:inbox"
```

- **Ligne 92** : `decode_responses=True` — le client renvoie des `str` et non des `bytes`, ce qui évite des `.decode()` partout en aval.
- **Ligne 94** : `_pubsubs` mémorise un objet PubSub **par nom d'agent** — l'abonnement à un canal n'est créé qu'une fois, au premier `receive()` (abonnement paresseux, voir Pièges).
- **Ligne 98** : la convention de nommage `agent:<nom>:inbox` espace de noms les canaux — c'est l'équivalent Redis du fichier `<nom>.jsonl` de s09.

### `RedisMailbox.send(to_agent, message)` — lignes 100–106

```python
    async def send(self, to_agent: str, message: Dict[str, Any]) -> None:
        """Publishes a JSON-encoded message to the recipient's Redis channel."""
        channel = self._get_channel_name(to_agent)
        # Add a standardized timestamp to every message
        payload = {**message, "timestamp": datetime.now().isoformat()}
        # Publish to Redis
        await self._redis.publish(channel, json.dumps(payload))
```

- **Ligne 104** : le backend estampille chaque message (`timestamp` ISO) par-dessus le dict de l'appelant — métadonnée de transport, ajoutée au même endroit dans `QueueMailbox` (ligne 164), donc invisible pour le code agent.
- **Ligne 106** : `publish` est de la **diffusion sans mémoire** : Redis livre aux abonnés *présents à cet instant* et oublie le message. Personne d'abonné = message perdu. C'est LA différence sémantique avec les fichiers JSONL de s09 (et avec `QueueMailbox`) — voir Pièges.

### `RedisMailbox.receive(agent_name, timeout=30.0)` — lignes 108–137

```python
        # Initialize PubSub subscription if this is the first time checking this inbox
        if agent_name not in self._pubsubs:
            ps = self._redis.pubsub()
            await ps.subscribe(channel)
            self._pubsubs[agent_name] = ps

        ps = self._pubsubs[agent_name]
        deadline = asyncio.get_event_loop().time() + timeout

        # Loop until a message is received or the timeout is reached
        while asyncio.get_event_loop().time() < deadline:
            # Check for a message without blocking the entire loop
            msg = await ps.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if msg and msg["type"] == "message":
                try:
                    # Parse the JSON payload
                    return json.loads(msg["data"])
                except json.JSONDecodeError:
                    # Fallback if data is raw text
                    return {"body": msg["data"]}
            # Small sleep to prevent high CPU usage during idle polling
            await asyncio.sleep(0.05)

        return None # Return None if no message arrived within the timeout
```

- **Lignes 115–118** : abonnement **paresseux** — le canal n'est souscrit qu'au premier `receive()` pour ce nom. Tant que personne n'a appelé `receive("lead")`, les messages publiés vers `lead` partent dans le vide.
- **Ligne 121** : l'échéance est calculée sur l'horloge de l'event loop (`get_event_loop().time()`), monotone — insensible aux changements d'heure système.
- **Ligne 126** : `get_message(..., timeout=0.1)` est non bloquant à 100 ms près ; combiné au `sleep(0.05)` de la ligne 135, le « push » pub/sub est en réalité consommé par **micro-polling** côté client — mais un polling mémoire/réseau à 50 ms, pas une relecture de fichier disque comme en s09.
- **Lignes 128–133** : le payload est décodé JSON ; si la donnée n'est pas du JSON valide, elle est enveloppée dans `{"body": ...}` plutôt que de faire planter le destinataire — une erreur de format devient une donnée.

### `RedisMailbox.close()` — lignes 139–144

Désabonne et ferme chaque PubSub mémorisé, puis `await self._redis.aclose()` ferme la connexion principale (lignes 141–144). Appelé dans le `finally` de `main()` — la fermeture est garantie même sur Ctrl+C.

### `QueueMailbox.__init__()` et `_get_queue(agent_name)` — lignes 152–160

Le backend de repli : un dict `nom → asyncio.Queue` (ligne 154), avec création paresseuse de la file au premier accès (lignes 158–159). Aucune dépendance, aucun réseau — mais aussi aucune sortie du processus.

### `QueueMailbox.send(to_agent, message)` — lignes 162–165

Même estampillage `timestamp` que la version Redis (ligne 164), puis `await self._get_queue(to_agent).put(payload)`. Différence cruciale : une `Queue` **tamponne** — un message envoyé avant que le destinataire n'écoute reste en attente au lieu d'être perdu.

### `QueueMailbox.receive(agent_name, timeout=30.0)` — lignes 167–172

```python
        try:
            return await asyncio.wait_for(self._get_queue(agent_name).get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
```

`asyncio.wait_for` transforme le `get()` bloquant en attente bornée ; le timeout devient `None`, exactement comme côté Redis — les deux backends honorent le même contrat observable.

### `QueueMailbox.close()` — lignes 174–176

`pass` : rien à libérer pour des files en mémoire. La méthode existe parce que l'interface l'exige — le code appelant ferme la mailbox sans savoir laquelle il tient.

### `initialize_mailbox()` — lignes 179–193

```python
    if HAS_REDIS:
        try:
            mb = RedisMailbox(REDIS_URL)
            # Test the connection with a PING
            await mb._redis.ping()
            print(f"\033[90m  [mailbox] Successfully connected to Redis at {REDIS_URL}\033[0m")
            return mb
        except Exception as e:
            print(f"\033[33m  [mailbox] Redis unavailable ({e}). Falling back to Queue.\033[0m")

    return QueueMailbox()
```

La fabrique applique une **dégradation gracieuse à deux étages** : paquet `redis` absent (`HAS_REDIS` faux) → Queue ; paquet présent mais serveur injoignable (le `PING` ligne 187 échoue) → Queue aussi, avec la raison affichée. Noter l'accès à l'attribut privé `mb._redis` depuis l'extérieur (ligne 187) — pragmatique, pas exemplaire. Le reste du programme reçoit un `MailboxBackend` et ne sait jamais lequel.

### `teammate_worker_loop(name, system_prompt, mailbox, stop_signal)` — lignes 198–264

La boucle de vie d'un équipier : attendre une tâche, dérouler un cycle d'agent autonome, renvoyer le résultat.

```python
    while not stop_signal.is_set():
        # Await a new task from the Lead
        msg = await mailbox.receive(name, timeout=2.0)
        if not msg:
            continue
```

- **Lignes 210–214** : le timeout court (2 s) n'est pas là pour la réactivité des messages mais pour **revenir tester `stop_signal`** régulièrement — sans lui, un worker bloqué en `receive` ne verrait jamais l'ordre d'arrêt.

Vient ensuite le cycle Thinking→Acting par tâche (lignes 222–253) — un historique neuf à chaque tâche (`history = [{"role": "user", "content": task_description}]`, ligne 222), donc **aucune contamination de contexte** entre deux tâches :

```python
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: client.messages.create(
                    model=MODEL,
                    system=system_prompt,
                    messages=history,
                    tools=EXTENDED_TOOLS,
                    max_tokens=4000,
                )
            )
```

- **Lignes 227–235** : `client.messages.create` est un appel bloquant du SDK — l'exécuter via `run_in_executor` le déporte dans un thread pour ne pas geler l'event loop pendant que l'autre équipier (et le lead) travaillent. C'est ce qui rend la « réflexion » des deux workers réellement parallèle.

```python
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    # Use the async_bash tool provided by core.py
                    cmd_output = await async_bash(block.input.get("command", ""))
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": cmd_output
                    })
```

- **Lignes 243–252** : le détail qui surprend — le modèle s'est vu annoncer les **six** outils d'`EXTENDED_TOOLS`, mais le worker exécute *tout* bloc `tool_use` comme du bash : `block.input.get("command", "")`. Un appel `read` ou `write` (dont l'input n'a pas de clé `command`) devient `async_bash("")`. Le commentaire du code l'assume (« Worker agents in s22 focus on bash-based actions »), et `EXTENDED_DISPATCH`, pourtant importé ligne 42, n'est jamais utilisé. Voir Pièges.
- **Ligne 256** : `final_answer = "".join(b.text for b in history[-1]["content"] if hasattr(b, "text"))` — extraction du texte du dernier tour assistant, en filtrant par `hasattr` (les blocs `tool_use` n'ont pas de `.text`).
- **Lignes 258–263** : le résultat repart vers `msg.get("from", "lead")` — l'équipier répond à l'**expéditeur**, pas à un « lead » codé en dur ; le protocole permettrait donc des échanges worker→worker.

### `lead_orchestration_loop(user_query, mailbox, teammate_names)` — lignes 269–305

Le lead de s22 n'est **pas un LLM** : c'est une fonction d'orchestration pure, en trois temps annoncés par les commentaires du code.

```python
    # 1. FAN-OUT: Send the sub-task to every specialist agent simultaneously
    for i, name in enumerate(teammate_names):
        await mailbox.send(name, {
            "from": "lead",
            "to": name,
            "type": "request",
            "body": f"Please contribute to this request from your specialty: {user_query}"
        })

    # 2. FAN-IN: Collect replies from the mailbox
    collected_results: Dict[str, str] = {}
    print(f"\033[90m  [lead] Waiting for {len(teammate_names)} replies...\033[0m")

    for _ in range(len(teammate_names)):
        # Wait up to 60 seconds for each specialist to finish
        msg = await mailbox.receive("lead", timeout=60.0)
        if msg:
            worker_name = msg.get("from", "unknown")
            collected_results[worker_name] = msg.get("body", "")
```

- **Lignes 282–288** : fan-out — la même requête part vers chaque spécialiste, préfixée de « contribute from your specialty » ; c'est le prompt système de chacun (alpha = qualité, beta = vitesse) qui différencie les réponses. La variable `i` de l'`enumerate` n'est jamais utilisée.
- **Lignes 294–299** : fan-in — exactement `len(teammate_names)` itérations de `receive("lead", timeout=60.0)`. On attend *N réponses*, pas *une réponse de chacun* : un timeout consomme une itération sans rien collecter, et le dict indexé par `worker_name` écrase les doublons.
- **Lignes 302–305** : synthèse minimale — si rien n'est arrivé, message d'erreur ; sinon concaténation `### Report from [nom]` par worker. Pas de passe LLM de synthèse : s22 concentre sa nouveauté sur le transport, pas sur l'orchestration (le protocole FSM, c'est [[s10-team-protocols]]).

### `main()` — lignes 310–362

```python
    # 2. Define Team Structure
    TEAM_DEF: Dict[str, str] = {
        "alpha": f"You are Alpha, a senior code analyst at {os.getcwd()}. Focus on quality.",
        "beta":  f"You are Beta, a specialized implementation agent at {os.getcwd()}. Focus on speed.",
    }

    # 3. Spawn Worker Tasks
    stop_event = asyncio.Event()
    worker_tasks = [
        asyncio.create_task(teammate_worker_loop(name, prompt, mailbox, stop_event))
        for name, prompt in TEAM_DEF.items()
    ]
```

- **Ligne 317** : la mailbox est créée **une fois** et partagée par référence entre lead et workers — en mode Queue c'est obligatoire (mémoire commune), en mode Redis chaque agent pourrait construire la sienne sur la même URL, y compris depuis une autre machine.
- **Lignes 327–330** : chaque équipier devient une `asyncio.Task` détachée — il vit en arrière-plan pendant tout le REPL, contrairement aux subagents jetables de s04.
- **Ligne 340** : `await loop.run_in_executor(None, lambda: input(...))` — même astuce que pour l'appel SDK : `input()` bloque un thread de pool, pas l'event loop, donc les workers continuent de tourner pendant que l'utilisateur tape.
- **Lignes 354–362** : le `finally` garantit l'arrêt propre dans l'ordre : `stop_event.set()` (signal coopératif), `t.cancel()` sur chaque task (coup de grâce pour celles bloquées en attente), puis `mailbox.close()` (connexions Redis). Double mécanisme signal + cancel : le signal seul mettrait jusqu'à 2 s par worker à être vu.

### Point d'entrée — lignes 365–370

`asyncio.run(main())` enveloppé d'un `try/except KeyboardInterrupt: pass` — un Ctrl+C au mauvais moment quitte sans traceback.

## Ce qui vient de [[core-py]]

Importés lignes 38–44 :

- **`client`** — le client Anthropic configuré (`.env`, proxy LiteLLM éventuel) ; utilisé par chaque worker via `run_in_executor`.
- **`MODEL`** — l'ID de modèle (`MODEL_ID`).
- **`EXTENDED_TOOLS`** — les 6 schémas d'outils annoncés aux workers (ligne 232).
- **`EXTENDED_DISPATCH`** — importé… et jamais utilisé : les workers court-circuitent la table de dispatch (voir Pièges).
- **`async_bash`** — la version asynchrone native de bash (sous-processus `asyncio`), seul outil réellement exécuté (ligne 247).

## Pièges et détails d'implémentation

- **`EXTENDED_DISPATCH` est importé mais mort** : le worker exécute chaque `tool_use` comme du bash via `block.input.get("command", "")` (ligne 247). Si le modèle appelle `read` ou `write` — outils pourtant annoncés dans `EXTENDED_TOOLS` — l'input n'a pas de clé `command` et c'est `async_bash("")` qui part. Le contrat annoncé au modèle et le contrat exécuté divergent.
- **Pub/sub Redis ≠ file d'attente** : `publish` ne livre qu'aux abonnés présents et n'archive rien. Avec l'abonnement paresseux de `receive()` (lignes 115–118), une réponse publiée vers `lead` avant son tout premier `receive("lead")` serait perdue. `QueueMailbox`, elle, tamponne — **le repli n'est donc pas sémantiquement identique** au backend de production ; pour garantir la livraison côté Redis, il faudrait des Streams ou des listes (`LPUSH`/`BRPOP`), pas du pub/sub.
- **La trace d'audit de s09 disparaît** : les fichiers JSONL gardaient l'historique complet des échanges sur disque ; les canaux Redis sont éphémères. Le gain en latence se paie en observabilité.
- **Le « push » est un micro-polling** : `receive()` côté Redis boucle sur `get_message(timeout=0.1)` + `sleep(0.05)` — on a remplacé la relecture de fichier par une sonde mémoire à 50 ms, pas par un vrai réveil événementiel (`listen()` aurait bloqué sans timeout).
- **Le fan-in compte des itérations, pas des répondants** : `for _ in range(len(teammate_names))` avec 60 s de timeout chacune — pire cas 2 minutes d'attente pour deux workers muets, et un worker bavard qui répondrait deux fois consommerait le créneau d'un autre.
- **`initialize_mailbox` teste la connexion via `mb._redis.ping()`** (ligne 187) — accès à un attribut privé depuis l'extérieur de la classe ; un `ping()` exposé par l'interface aurait été plus propre. À noter aussi : `sys` (ligne 32) et `Union` (ligne 35) sont importés mais inutilisés.

## Lancer la démo

```bash
# Optionnel — pour le mode production :
docker run -p 6379:6379 redis

python s22_production_mailbox.py
```

Prérequis : `.env` avec `ANTHROPIC_API_KEY` et `MODEL_ID` (ou proxy LiteLLM via `ANTHROPIC_BASE_URL`), et `pip install redis` pour le backend production (`redis>=5.0.0` dans `requirements.txt`). Sans le paquet ou sans serveur, la démo bascule d'elle-même sur `QueueMailbox` (message jaune). `REDIS_URL` permet de viser un autre serveur.

Au lancement : `[mailbox] Successfully connected to Redis at ...` (ou le repli), puis `Team active: alpha, beta | Protocol: Redis Pub/Sub`. Au prompt `s22 >>`, poser une question d'analyse du repo : les deux workers reçoivent la tâche en violet, déroulent chacun leur boucle bash en parallèle, et le lead affiche le rapport synthétisé `### Report from [alpha]` / `### Report from [beta]`. Quitter avec `q` déclenche le nettoyage du `finally`.

## Liens

- Socle : [[core-py]]
- Session précédente : [[s21-mcp-runtime]]
- Session suivante : [[s23-worktree-advanced]]
- Sessions liées : [[s09-agent-teams]] (les mailboxes JSONL que s22 remplace), [[s10-team-protocols]] (le protocole FSM qui pourrait coiffer ces canaux), [[s11-autonomous-agents]] (l'auto-assignation sur tableau de tâches), [[s08-background-tasks]] (les fondations de l'exécution en arrière-plan)
