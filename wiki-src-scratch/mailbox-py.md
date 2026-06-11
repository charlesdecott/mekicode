---
title: "mailbox.py · Messagerie unifiée"
phase: "Multi-agents"
fichier: "src_scratch/mailbox.py"
lignes: 170
tags: [mailbox, jsonl, queue, redis, pubsub, req-id, concurrence]
---

# mailbox.py · Messagerie unifiée

> **En une phrase** : trois backends de messagerie inter-agents — JSONL sur disque, files mémoire, Redis pub/sub — derrière une seule interface `Mailbox`, avec une enveloppe commune dont le champ `req_id` corrèle chaque réponse à sa requête.

## Rôle dans le harness

Dès qu'on a plusieurs agents (équipiers de [[agents-py]], lead du REPL), il faut un canal pour qu'ils se parlent. Dans le repo source, ce canal existe en deux exemplaires divergents : s09 implémente des boîtes aux lettres JSONL sur disque pour les équipiers, puis s22 réintroduit le concept avec Redis pub/sub et une file mémoire de repli — sans factoriser, et chacun avec ses bugs propres (lost update, ligne corrompue qui empoisonne la boucle, réponse tardive mal attribuée).

Ce module unifie tout : un `Protocol` `Mailbox` (deux méthodes, `send` et `receive`), trois implémentations interchangeables, et une fabrique `get_mailbox()` qui choisit le backend — y compris le mode « auto » de s22 (Redis si joignable, sinon dégradation gracieuse vers la file mémoire). Les messages portent tous la même enveloppe `{"from", "body", "ts", "req_id"}` ; la sémantique de `receive` est partout un **pop-all** : on relève la boîte entière, les messages relevés en sortent définitivement.

Le découpage est volontairement minimal : ce module ne sait rien des agents, des prompts ni des boucles — il transporte des dicts. C'est [[agents-py]] qui décide quoi en faire (corrélation `req_id`, FSM des équipiers), et [[main-py]] qui choisit le backend via le flag CLI `--backend`.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–5 | Docstring | Les trois backends, l'enveloppe commune, le rôle de `req_id` |
| 7–15 | Imports | stdlib (json, queue, threading, time…) + `STATE_DIR`, `paint` de [[core-py]] |
| 18–20 | Enveloppe | `_envelope()` — le format unique des messages (FIX `req_id`) |
| 23–27 | Interface | `Mailbox` (Protocol) : `send` / `receive` |
| 30–78 | Backend disque | `JsonlMailbox` (s09) — verrou par boîte, pop-all atomique |
| 81–104 | Backend mémoire | `QueueMailbox` — repli intra-processus, tamponne sans abonné |
| 107–148 | Backend Redis | `RedisMailbox` (s22) — pub/sub sur canaux `mailbox:<agent>` |
| 151–170 | Fabrique | `get_mailbox()` — « auto » avec dégradation gracieuse |

## Les fonctions, une à une

### `_envelope(frm, body, req_id)` — lignes 18–20

```python
def _envelope(frm: str, body: str, req_id: str | None) -> dict:
    # FIX(mekicode): champ req_id ajouté (s09 attribuait les réponses tardives au mauvais appel)
    return {"from": frm, "body": body, "ts": time.time(), "req_id": req_id}
```

Le seul endroit du harness où la forme d'un message est définie — les trois backends appellent ce helper dans leur `send`, donc impossible que les enveloppes divergent. Le champ `req_id` est `None` pour un message libre ; [[agents-py]] le renseigne pour chaque requête de `send_to_teammate` et exige le même `req_id` dans la réponse.

### `Mailbox` (Protocol) — lignes 23–27

```python
class Mailbox(Protocol):
    """Interface commune : envoyer à un agent, relever sa boîte (pop-all)."""

    def send(self, to: str, frm: str, body: str, req_id: str | None = None) -> None: ...
    def receive(self, agent: str, timeout: float = 0) -> list[dict]: ...
```

Typage **structurel** (`typing.Protocol`) : les trois backends ne déclarent aucun héritage, ils se contentent d'exposer les deux méthodes avec ces signatures. Le contrat de `receive` : avec `timeout=0`, relevé immédiat (liste possiblement vide) ; avec `timeout>0`, on attend au plus ce délai qu'au moins un message arrive, puis on draine tout ce qui est disponible.

### `JsonlMailbox` — lignes 30–78

Le backend persistant de s09 : une boîte = un fichier `<agent>.jsonl` sous `STATE_DIR/mailboxes/`, un message = une ligne JSON. Avantages hérités de la source : inspection à l'œil nu (`cat explorer.jsonl`), fonctionnement inter-processus. C'est le backend qui concentrait les trois bugs de concurrence de s09 — tous corrigés ici (voir la section dédiée).

### `JsonlMailbox.__init__(root=None)` — lignes 33–37

Crée le répertoire des boîtes (`STATE_DIR / "mailboxes"` par défaut, surchargeable pour les tests) et initialise la machinerie de verrouillage : un dict `_locks` (un `threading.Lock` par agent) protégé par un méta-verrou `_meta`.

### `JsonlMailbox._lock(agent)` — lignes 39–41

```python
    def _lock(self, agent: str) -> threading.Lock:
        with self._meta:
            return self._locks.setdefault(agent, threading.Lock())
```

Fabrique paresseuse des verrous par boîte. Le `setdefault` sous `_meta` garantit que deux threads demandant le verrou du même agent au même instant reçoivent **le même** objet `Lock` — sans le méta-verrou, chacun pourrait en créer un et croire la boîte protégée.

### `JsonlMailbox._path(agent)` — lignes 43–44

Helper d'une ligne : `self.root / f"{agent}.jsonl"`.

### `JsonlMailbox.send(to, frm, body, req_id=None)` — lignes 46–50

```python
    def send(self, to: str, frm: str, body: str, req_id: str | None = None) -> None:
        # FIX(mekicode): l'écriture prend le verrou du DESTINATAIRE (s09/s10 écrivaient sans
        # verrou → message appendu entre lecture et troncature silencieusement détruit)
        with self._lock(to), open(self._path(to), "a", encoding="utf-8") as f:
            f.write(json.dumps(_envelope(frm, body, req_id)) + "\n")
```

Append d'une ligne JSON, **sous le verrou de la boîte destinataire** — le même verrou que celui pris par `_pop_all`. C'est ce partage qui rend impossible le lost update de la source (détail dans « Bugs corrigés »).

### `JsonlMailbox.receive(agent, timeout=0)` — lignes 52–58

```python
    def receive(self, agent: str, timeout: float = 0) -> list[dict]:
        deadline = time.monotonic() + timeout
        while True:
            msgs = self._pop_all(agent)
            if msgs or time.monotonic() >= deadline:
                return msgs
            time.sleep(0.1)
```

Sondage à 0,1 s d'intervalle jusqu'au premier relevé non vide ou à l'échéance. `time.monotonic()` (et non `time.time()`) pour que l'échéance résiste aux ajustements d'horloge. Avec `timeout=0`, la condition de la ligne 56 est vraie dès le premier tour : un seul `_pop_all`, retour immédiat.

### `JsonlMailbox._pop_all(agent)` — lignes 60–78

Le cœur du backend, et le siège de deux corrections :

```python
        path = self._path(agent)
        with self._lock(agent):
            if not path.exists():
                return []
            lines = path.read_text(encoding="utf-8").splitlines()
            path.write_text("", encoding="utf-8")
        msgs = []
        for line in lines:
            if not line.strip():
                continue
            try:
                msgs.append(json.loads(line))
            except json.JSONDecodeError:
                print(paint(f"[mailbox] ligne corrompue ignorée ({agent}): {line[:60]}", "yellow"))
        return msgs
```

- **Lignes 65–69** : lecture **et** troncature dans la même section critique — le pop-all est atomique vis-à-vis de `send`, qui prend le même verrou.
- **Lignes 70–77** : le parsing JSON a lieu *après* la sortie du verrou, et surtout *après* la troncature. Une ligne illisible est signalée (warning jaune) puis ignorée ; comme le fichier est déjà vidé, elle ne sera jamais relue.

### `QueueMailbox` — lignes 81–104

Le repli de développement : des `queue.Queue` en mémoire, donc **intra-processus uniquement** — suffisant pour l'équipe de [[agents-py]], dont les équipiers sont des threads du même processus. Contrairement au pub/sub Redis, une `Queue` tamponne les messages même sans lecteur à l'écoute.

### `QueueMailbox.__init__()` — lignes 84–86

Même schéma de fabrique paresseuse que `JsonlMailbox` : un dict `_queues` protégé par un méta-verrou `_meta`.

### `QueueMailbox._q(agent)` — lignes 88–90

`setdefault` sous verrou — garantit une `Queue` unique par agent (même raisonnement que `_lock`).

### `QueueMailbox.send(to, frm, body, req_id=None)` — lignes 92–93

Une ligne : `self._q(to).put(_envelope(frm, body, req_id))`. `queue.Queue` étant thread-safe, aucun verrou supplémentaire n'est nécessaire.

### `QueueMailbox.receive(agent, timeout=0)` — lignes 95–104

```python
    def receive(self, agent: str, timeout: float = 0) -> list[dict]:
        q, msgs = self._q(agent), []
        try:
            if timeout > 0:
                msgs.append(q.get(timeout=timeout))  # attend le 1er message
            while True:
                msgs.append(q.get_nowait())          # puis draine le reste
        except queue.Empty:
            pass
        return msgs
```

Pas de sondage ici : `q.get(timeout=...)` fournit l'attente bloquante native de `queue.Queue` pour le premier message, puis `get_nowait()` draine le reliquat jusqu'à `queue.Empty`. Profil de latence meilleur que le poll à 0,1 s du backend JSONL — l'attente se termine à l'instant où le message arrive.

### `RedisMailbox` — lignes 107–148

Le backend distribué de s22 : pub/sub Redis, un canal `mailbox:<agent>` par destinataire. Permet des agents répartis sur plusieurs processus ou machines — au prix de la sémantique pub/sub : un message publié sans abonné à l'écoute est **perdu** (pas de tampon), voir les pièges.

### `RedisMailbox.__init__(url=None)` — lignes 110–116

```python
    def __init__(self, url: str | None = None):
        import redis  # paresseux : le paquet n'est requis que pour ce backend

        self._redis = redis.Redis.from_url(
            url or os.getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
```

L'`import redis` est **local** : le paquet n'est une dépendance que si l'on instancie ce backend — le reste du harness fonctionne sans lui (c'est ce qui rend le mode « auto » de la fabrique possible). URL résolue en cascade : argument > variable d'environnement `REDIS_URL` > `redis://localhost:6379`. `decode_responses=True` évite de manipuler des bytes.

### `RedisMailbox.ping()` — lignes 118–120

Délègue à `self._redis.ping()` : lève si le serveur est injoignable. C'est la sonde qu'utilise `get_mailbox` pour décider entre Redis et le repli (sémantique s22).

### `RedisMailbox._channel(agent)` — lignes 122–123

Helper d'une ligne : `f"mailbox:{agent}"`.

### `RedisMailbox._ps(agent)` — lignes 125–131

Abonnement **paresseux** : le premier `receive` d'un agent crée son objet pubsub (`ignore_subscribe_messages=True` pour ne pas polluer le flux avec les accusés d'abonnement), s'abonne au canal, et le met en cache sous `_meta`. Les `receive` suivants réutilisent le même abonnement.

### `RedisMailbox.send(to, frm, body, req_id=None)` — lignes 133–134

Une ligne : `publish` de l'enveloppe sérialisée sur le canal du destinataire.

### `RedisMailbox.receive(agent, timeout=0)` — lignes 136–148

```python
    def receive(self, agent: str, timeout: float = 0) -> list[dict]:
        ps, msgs = self._ps(agent), []
        deadline = time.monotonic() + timeout
        while True:
            raw = ps.get_message(timeout=0.1)
            if raw and raw.get("type") == "message":
                try:
                    msgs.append(json.loads(raw["data"]))
                except json.JSONDecodeError:
                    print(paint(f"[mailbox] message corrompu ignoré ({agent})", "yellow"))
                continue  # draine tout ce qui est arrivé
            if msgs or time.monotonic() >= deadline:
                return msgs
```

Même contrat pop-all que les autres backends, reconstruit au-dessus de `get_message` : tant qu'un message arrive, le `continue` (ligne 146) reboucle immédiatement pour drainer la rafale ; dès que le flux se tarit (`raw` vide), on retourne si on a quelque chose ou si l'échéance est passée. Un payload illisible est ignoré avec warning — même politique que `JsonlMailbox._pop_all`.

### `get_mailbox(backend="auto")` — lignes 151–170

La fabrique, seule fonction que les consommateurs ont besoin de connaître.

```python
    try:
        mb = RedisMailbox()
        mb.ping()
        print(paint("[mailbox] Redis connecté", "dim"))
        return mb
    except Exception as e:  # paquet absent OU serveur injoignable → dégradation gracieuse (s22)
        print(paint(f"[mailbox] Redis indisponible ({e}) — repli QueueMailbox", "yellow"))
        return QueueMailbox()
```

- `"jsonl"` et `"queue"` (lignes 153–156) : instanciation directe.
- `"redis"` explicite (lignes 157–160) : le `ping()` est appelé hors `try` — si le serveur est injoignable, l'exception remonte à l'appelant. Choix assumé : qui demande Redis nommément veut savoir qu'il manque.
- `"auto"` (lignes 163–170) : tentative Redis (le `try` couvre aussi l'`ImportError` du paquet absent, grâce à l'import paresseux du constructeur), repli silencieux mais **annoncé** vers `QueueMailbox`. C'est la dégradation gracieuse de s22, ici généralisée à tout le harness.
- Un nom inconnu (lignes 161–162) lève `ValueError` plutôt que de retomber dans « auto » sans prévenir.

## Bugs de la source corrigés ici

- **Réponse tardive mal attribuée (ligne 19, champ `req_id`)** — dans s09, quand `send_to_teammate` expirait, la réponse de l'équipier finissait quand même dans la boîte du lead ; l'appel *suivant* la drainait et la présentait comme sa propre réponse — dialogue décalé d'un cran, silencieusement. L'enveloppe porte désormais un `req_id` de corrélation ; c'est [[agents-py]] (`send_to_teammate`) qui le génère, le vérifie au retour et **jette** toute réponse au `req_id` inattendu.
- **Lost update à l'écriture (lignes 47–48, `JsonlMailbox.send`)** — s09/s10 écrivaient dans le fichier sans aucun verrou. Or le pop-all du lecteur procède en deux temps (lire, puis tronquer) : un message appendu par un autre thread *entre* ces deux temps était détruit par la troncature, sans trace. Ici `send` prend le verrou du destinataire — le même que `_pop_all` — l'entrelacement fatal est impossible.
- **Pop-all non atomique et ligne corrompue empoisonnante (lignes 61–63, `JsonlMailbox._pop_all`)** — double défaut dans s09 : lecture et troncature n'étaient pas dans la même section critique, et le parsing JSON se faisait *avant* la troncature — une ligne corrompue levait une exception, le fichier n'était jamais vidé, et chaque relevé suivant rejouait le crash : boucle d'erreurs infinie. Ici : lecture + troncature sous le même verrou, parsing après coup, ligne illisible ignorée avec warning (lignes 74–77).

## Qui l'utilise

- [[agents-py]] — `from mailbox import Mailbox, get_mailbox` : `Team.start()` prend `get_mailbox("auto")` par défaut, la boucle des équipiers relève leur boîte (`receive(name, timeout=0.5)`) et `send_to_teammate` dialogue avec eux via la boîte « lead », `req_id` à l'appui.
- [[main-py]] — `from mailbox import get_mailbox` (ligne 22) : le flag CLI `--backend auto|jsonl|queue|redis` est transmis à l'équipe au démarrage (`state["team"].start(get_mailbox(args.backend))`, ligne 92).

## Pièges et détails d'implémentation

- **Le pub/sub Redis ne tamponne pas** : un message publié avant le premier `receive` du destinataire (donc avant son abonnement paresseux `_ps`) est perdu, contrairement à `QueueMailbox` et `JsonlMailbox` qui stockent. En pratique la fenêtre est étroite (les équipiers de [[agents-py]] sondent dès leur démarrage), mais elle existe au tout premier échange.
- **`QueueMailbox` est intra-processus** : parfait pour les threads de `Team`, inutilisable entre processus séparés. Pour du multi-processus sans Redis, choisir explicitement `--backend jsonl`.
- **Trois profils de latence** : JSONL sonde à 0,1 s, `Queue` se réveille à l'arrivée du message, Redis sonde le socket par tranches de 0,1 s. Même contrat, réactivités différentes.
- **Les verrous par agent ne sont jamais libérés** : `_locks` (et `_queues`, `_pubsubs`) croissent avec le nombre d'agents distincts. Borné en pratique (quelques équipiers et workers), mais à connaître si on génère des noms d'agents dynamiques en masse.
- **`Mailbox` est un Protocol, pas une classe de base** : aucune vérification à l'exécution qu'un backend est conforme — c'est du typage structurel, vérifiable statiquement seulement.

## Liens

- Modules liés : [[agents-py]] (consommateur principal : équipe et lead), [[main-py]] (choix du backend via `--backend`), [[core-py]] (`STATE_DIR`, `paint`)
