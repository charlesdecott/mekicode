# Hub de session temps réel + adaptateurs multi-canal — design

> Sous-projet **#1** d'un chantier plus large (« envoyer/recevoir/streamer le chat depuis n'importe où »).
> Découpage global : **#1 hub temps réel** (ce doc) → #2 front multi-utilisateur → #3 adaptateur Discord
> → (futur) #4 canvas collaboratif → (plus tard) #5 mail / Telegram / API publique / SDK.
> Ce doc couvre #1 **et** ses deux premiers consommateurs (front web multi-utilisateur + Discord),
> car ils prouvent l'architecture de bout en bout.

**Date :** 2026-06-13
**Statut :** validé (sections A–B validées en direct ; C–H rédigées en autonomie sur délégation).

## But

Unifier l'envoi/réception/streaming des messages du chat derrière **un bus de conversation à état
partagé** (le *hub*), pour que **plusieurs humains + l'agent** partagent une même session en temps réel,
et que **n'importe quel canal** (web, Discord, plus tard mail/Telegram/API) ne soit qu'un **adaptateur**
branché sur ce hub.

## Décisions cadrées (issues du brainstorming)

- **Approche 1** : hub **async in-process** dans le serveur (NiceGUI est déjà asyncio/FastAPI). Pas de
  broker externe ni d'API réseau **maintenant**, mais interface du hub **agnostique du transport** pour
  ne fermer aucune porte (WebSocket → brique #B, Redis, canvas réutilisent le même pub/sub).
- **Modèle collab** : *salle partagée + identité légère*. Une session = une salle ; chaque participant a
  un `author` éphémère `{id, pseudo, couleur}` ; **pas d'auth/login**.
- **File d'attente** : **FIFO auto-drain**, 1 message à la fois par session ; items **en attente**
  supprimables ; l'item **en cours** ne l'est pas.
- **Déploiement** : un seul process, **conteneur Docker** = frontière d'isolation réelle pour `bash`
  (non confiné) et les outils fichiers.
- **Front/back séparables plus tard** : le hub **ne dépend jamais** de NiceGUI ; le front est un
  adaptateur **optionnel** ; le backend (+ Discord) tourne **sans front** (headless).
- **Contrainte d'exécution** : tout est **additif** — aucun fichier déplacé/supprimé ; `mekichat/
  sessions.py` devient un **ré-export** de `mekihub`.

## A. Structure des paquets & frontière front/back

Nouveau paquet **`packages/mekihub/`** (zéro import NiceGUI/Discord) :

| Fichier | Rôle |
|---|---|
| `session.py` | `Author`, `Session`, `SessionMeta`, `SessionStore` — couche session **canonique** (JSON persistant). Superset de l'actuelle `mekichat/sessions.py`. |
| `events.py` | événements **de session** (dataclasses) : `Snapshot`, `MessagePosted`, `QueueEnqueued`, `QueueItemDeleted`, `RunStarted`, `AgentDelta`, `AgentDone`, `ToolStarted`, `ToolFinished`, `RunFinished`, `RunError`, `PresenceChanged`, `Idle`. |
| `hub.py` | `SessionHub` : registre des sessions, état partagé, pub/sub mémoire, **worker FIFO par session**. |
| `adapters/__init__.py` | base/utilitaires d'adaptateur. |
| `adapters/discord.py` | adaptateur Discord (discord.py). Logique testable avec un client factice. |
| `main.py` | entrypoint : démarre le hub + adaptateurs **activés par `.env`/flags** (front on/off, discord on/off). Headless possible. |

- `mekicore` **inchangé**. `mekichat` devient un **adaptateur NiceGUI** ; `mekichat/sessions.py` →
  `from mekihub.session import *` (ré-export, additif).
- Dépendances : `mekichat` / `adapters.discord` → **`mekihub`** → `mekicore` → `mekillm`.
- **Demain** (#B) : `mekihub/adapters/websocket.py` expose `submit`/`subscribe` en WS ; `mekichat` se
  branche en client distant → front-service + back-service, **sans toucher au hub**.

## B. Interface du hub (agnostique du transport)

```python
class SessionHub:
    def __init__(self, store: SessionStore, llm_factory, tools, dispatch): ...
    def join(self, session_id: str, author: Author) -> None
    def leave(self, session_id: str, author: Author) -> None
    def submit(self, session_id: str, text: str, author: Author) -> str      # enfile, réveille le worker, renvoie item_id ; NON bloquant
    def delete_pending(self, session_id: str, item_id: str) -> bool          # retire un item EN ATTENTE (jamais l'item en cours)
    def snapshot(self, session_id: str) -> SessionState                      # état complet : fil + file + présence + item en cours
    async def subscribe(self, session_id: str) -> AsyncIterator[Event]       # 1er event = Snapshot, puis deltas
```

- `submit` non bloquant : les réponses arrivent **uniquement** via `subscribe` → **tous** les abonnés
  les voient (pas seulement l'émetteur). Le front n'affiche **pas** localement à l'envoi ; il attend le
  broadcast (cohérence inter-clients).
- `subscribe` émet d'abord un **`Snapshot`** (amorçage) puis le flux incrémental → un client en retard
  voit tout le fil + la file en cours.

## C. Modèle d'état & identité

```python
@dataclass
class Author:        # éphémère, par connexion ; NON persisté en présence
    id: str          # uuid de connexion
    name: str        # pseudo choisi
    color: str       # couleur (hex), pour l'affichage

@dataclass
class QueueItem:
    item_id: str
    author: Author
    text: str
    ts: str

@dataclass
class SessionState:  # = ce que renvoie snapshot() / l'event Snapshot
    id: str
    title: str
    messages: list           # format OpenAI pur (ce que voit l'agent)
    authors: dict[int, dict] # index de message -> {name, color} (user uniquement) ; PAS dans `messages`
    queue: list[QueueItem]   # en attente (hors item en cours)
    running: QueueItem | None
    presence: list[Author]
```

- **Séparation agent / affichage** : `Session.messages` reste **OpenAI pur** (mutée en place par
  `run_agent`). L'attribution d'auteur vit dans `Session.authors` (dict `index_message → {name,color}`),
  jamais injectée dans `messages` → **l'agent ne voit jamais** de champ `author` (pas de risque 400 côté
  API). Robuste car les messages `user` ne sont ajoutés que par le hub (append-only, index stables).
- **Persistance** : `messages` + `authors` + `title` persistés via `SessionStore` (JSON). **File +
  présence + item en cours = en mémoire** (éphémères, remis à zéro au redémarrage — acceptable : ce sont
  des états transitoires).

## D. Worker / drain FIFO (machine à états)

Par session, une **tâche async** (`asyncio`) :

```
boucle worker(session):
    item = await pending.pop_next()          # bloque jusqu'à un item (asyncio.Condition)
    running = item ; publish(RunStarted(item))
    idx = append user message(item.text) + authors[idx] = {item.author}
    persist ; publish(MessagePosted(idx, author, text))
    gen = run_agent(session.messages, llm, tools, dispatch, stream=True)   # générateur SYNC de mekicore
    while (ev := await asyncio.to_thread(next, gen, _DONE)) is not _DONE:
        publish(translate(ev))                # Agent*/Tool*/RunFinished/RunError
    persist ; running = None ; publish(Idle if pending vide else continue)
```

- **Pont sync→async sans NiceGUI** : `await asyncio.to_thread(next, gen, _DONE)` step le générateur sync
  hors de la boucle, **un événement à la fois** (stdlib only ; pas de dépendance NiceGUI dans le hub).
- **`pending`** = `PendingQueue` (liste ordonnée + `asyncio.Condition`) : `enqueue(item)`,
  `delete(item_id)` (refusé si == item en cours), `pop_next()` (await jusqu'à non-vide). `asyncio.Queue`
  ne permet pas la suppression ciblée → liste ordonnée explicite.
- **Auto-drain** : à la fin d'un run, le worker reprend `pop_next()` → vide la file dans l'ordre.
- L'item **en cours** n'est pas supprimable (annulation d'un run en cours = s19 « interrupts », **hors
  périmètre**).

## E. Fan-out temps réel NiceGUI (risque technique n°1)

- À la connexion d'un client (page `@ui.page`) : restaurer/choisir un `author` (pseudo+couleur via
  `app.storage.user`), `hub.join`, rendre le `Snapshot`, puis **consommer `hub.subscribe` dans une tâche
  liée au client** (`async for ev in hub.subscribe(...)`) et muter l'UI **par événement** — NiceGUI pousse
  le diff par WebSocket à **ce** client. Chaque client a sa propre boucle d'abonnement.
- **Garde déconnexion** : on réutilise le pattern existant (`RuntimeError` « client deleted » → on cesse
  de rendre, `hub.leave`).
- **Envoi** : composer → `hub.submit` ; aucun rendu local (cohérence : tout passe par le broadcast).
- **UI file d'attente** : panneau listant les items en attente (chip auteur + texte + ✕). ✕ →
  `hub.delete_pending`. L'item **en cours** affiché distinctement (pas de ✕, indicateur « en cours »).
- **UI présence** : pastilles des pseudos connectés (couleur par auteur), messages teintés par auteur.

## F. Adaptateur Discord (#3, canal prioritaire)

- `adapters/discord.py` (discord.py) : mapping **canal Discord → session** (`DISCORD_CHANNEL_SESSION_MAP`,
  ou « 1 session par canal »). `on_message` (dans un canal mappé, hors bots) → `author` depuis l'auteur
  Discord (`name` + couleur déterministe depuis l'id) → `hub.submit`. Une tâche par session mappée
  consomme `hub.subscribe` → poste un message « réflexion… » puis **l'édite** au fil de `AgentDelta`
  (throttle pour les rate-limits Discord), finalise sur `AgentDone`. `ToolStarted` → ligne compacte
  optionnelle.
- **Test réseau-free** : `FakeDiscordClient` capture `send`/`edit` ; on injecte un message entrant et on
  vérifie `hub.submit` + le rendu de la sortie agent. **Connexion réelle = étape de validation manuelle**
  (nécessite `DISCORD_BOT_TOKEN`).

## G. Déploiement / isolation (Docker)

- `Dockerfile` (racine) : base python, `pip install -r requirements.txt`, copie `packages/`, entrypoint
  `python packages/mekihub/main.py`. Le **conteneur = frontière d'isolation** pour `bash`/outils fichiers
  (`MEKICORE_WORKSPACE` = dossier interne au conteneur).
- `docker-compose.yml` (optionnel) : service hub, env depuis `.env`, expose `8080` (web). Redis **différé**.
- Flags d'activation (`.env`) : `MEKIHUB_FRONT=on|off`, `MEKIHUB_DISCORD=on|off`.
- **Construire/lancer Docker = étape manuelle de l'utilisateur** ; la validation automatique (TDD +
  Playwright) tourne en local (process python), pas dans Docker.

## H. Tests (TDD + Playwright)

**Unitaires réseau-free** (stub LLM, dans `tests/`, conventions du projet : sans clé API, `ensure_ascii`) :
- `tests/smoke_mekihub.py` : ordre FIFO ; auto-drain ; `delete_pending` (succès en attente / refus sur
  l'item en cours) ; `subscribe` reçoit `Snapshot` puis deltas ; **plusieurs abonnés** reçoivent tous les
  events ; présence join/leave ; `authors` persistés et **absents** de `messages` ; un **FakeLLM** émet
  une séquence connue (avec délai contrôlable pour tester l'empilement de la file).
- `FakeDiscordClient` : ingestion d'un message → `hub.submit` ; rendu de la sortie agent.
- Maintien des smokes existants (`smoke_packages.py`, `smoke_mekichat.py`) au vert.

**Playwright** (multi-client, captures analysées — exigence projet) :
- **Broadcast** : 2 contextes navigateur sur la même session ; poster dans A → apparaît dans B.
- **File d'attente** : agent « occupé » (FakeLLM lent) ; poster 2 messages → la file montre 2 items dans
  les 2 clients ; supprimer un item → disparaît des 2 ; le restant **draine**.
- **Présence** : B rejoint → visible chez A.
- Scripts diag déterministes sous `.refactor-tmp/` (gitignoré), captures lues et analysées avant de
  conclure (un HTTP 200 ne suffit pas).

## Hors périmètre (explicite)

- Auth/comptes réels ; multi-process / scale horizontal ; broker Redis ; API WebSocket publique + SDK ;
  **canvas collaboratif** (nodes/câbles, CRDT/OT) ; mail / Telegram ; annulation d'un run en cours
  (interrupts s19). Le modèle d'état et le pub/sub sont conçus pour les **accueillir plus tard**.

## Risques

1. **Fan-out NiceGUI multi-client** (E) — point délicat ; à prototyper et valider Playwright **tôt**.
2. **Pont sync→async** du générateur `run_agent` (D) — `asyncio.to_thread(next, gen)` ; vérifier qu'aucun
   état partagé n'est muté concurremment (1 worker par session sérialise déjà).
3. **Rate-limits Discord** (F) — throttle des éditions de message.
