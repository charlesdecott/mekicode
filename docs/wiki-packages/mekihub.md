# `packages/mekihub/` — hub de session temps réel

Bus de conversation partagée, multi-utilisateur, multi-canal. `mekihub` introduit la notion de
**salle** : plusieurs participants (humains ou canaux) soumettent des messages vers une même session ;
un **worker asyncio** par session draine la file FIFO et pilote le générateur SYNC `mekicore.run_agent`
via `asyncio.to_thread`. Les abonnés (front NiceGUI, Discord…) reçoivent les événements de la salle
(**pub/sub en mémoire**) via un générateur asynchrone.

> Numéros de ligne indicatifs (source = vérité).

## Vue des fichiers et de leurs relations

```
main.py      ── entrypoint : build_hub() + main() (MEKIHUB_FRONT / MEKIHUB_DISCORD)
   │             active le front NiceGUI (mekichat) ou l'adaptateur Discord selon l'env
   ▼
hub.py       ── SessionHub : registre de salles, file FIFO, pub/sub, worker asyncio par session
   │             SessionHub.submit → PendingQueue → _run_worker → run_agent (mekicore, sync thread)
   │             SessionHub.subscribe → async gen (Snapshot + deltas)
   │             _translate : events mekicore → events mekihub (par type.__name__)
   ▼
session.py   ── couche session canonique : Author, QueueItem, Session, SessionMeta, SessionState
   │             SessionStore (CRUD JSON, .sessions/ à la racine)
   │             add_user(content, *, author) : range l'auteur dans Session.authors, séparé des messages OpenAI
   ▼
events.py    ── événements émis par SessionHub, consommés par les adaptateurs
   │             Snapshot / PresenceChanged / QueueEnqueued / QueueItemDeleted
   │             RunStarted / MessagePosted / AgentDelta / AgentDone
   │             ToolStarted / ToolFinished / RunFinished / RunError / Idle
   ▼
adapters/
  discord.py ── DiscordAdapter : mapping canal → session ; handle_message → hub.submit ;
                 _render_loop consomme hub.subscribe et poste/édite via le client Discord
                 FakeDiscordClient + FakeMessage pour tests réseau-free
```

## `session.py` — couche session canonique

Superset de l'ancienne `packages/mekichat/sessions.py` (qui la ré-exporte désormais via un shim).
Pur Python, sans réseau ni NiceGUI. Données runtime dans `.sessions/` à la **racine du projet**
(jamais dans `packages/`).

- **`Author`** (dataclass, l.25) : participant éphémère de la salle. `id` = UUID de connexion (pas un
  compte permanent), `name`, `color` (couleur d'affichage libre).
- **`QueueItem`** (dataclass, l.33) : item en attente dans la file. `item_id` (hex court), `author`
  (Author), `text`, `ts` (ISO UTC).
- **`Session`** (dataclass, l.41) :
  - `messages` : liste de dicts OpenAI **purs** (ce que l'agent voit ; pas de champ auteur).
  - `authors` : `dict` index_message → `{"name", "color"}` — **attribution séparée** des messages OpenAI.
  - `add_user(content, *, author) -> int` (l.49) : ajoute le message user dans `messages` ET range
    l'attribution dans `authors[idx]` ; renseigne `title` à la première vraie saisie (48 car. max).
  - `add(role, content, **extra) -> dict` (l.59) : méthode compat historique (mekichat), sans auteur.
- **`SessionMeta`** (dataclass, l.70) : vue légère (`id`, `title`, `model`, `created_at`, `n_messages`)
  pour les listes/barres latérales.
- **`SessionState`** (dataclass, l.79) : instantané partagé renvoyé par `SessionHub.snapshot()` :
  `messages`, `authors`, `queue` (list[QueueItem] en attente), `running` (QueueItem | None), `presence`
  (list[Author]).
- **`SessionStore`** (class, l.90) : CRUD, un fichier `<id>.json` par session. `authors` est persisté
  (clés int en mémoire → str sur disque, reconverties à la lecture) ; file et présence sont **éphémères**
  (non persistées). Résout le répertoire depuis l'argument, `MEKICHAT_SESSIONS_DIR`, ou `.sessions/`.
  Méthodes : `create(model, system=None)`, `save(session)`, `load(session_id)`, `delete(session_id)`,
  `list() -> list[SessionMeta]` (plus récentes d'abord, ignore les fichiers corrompus).

## `events.py` — événements de salle

Dataclasses Python émises par `SessionHub`, consommées par les adaptateurs (front NiceGUI, Discord…).
Sur-ensemble des events de mekicore : couvrent à la fois la **vie de la salle** (présence, file) et
le **run d'agent** (streaming, outils, fin).

| Événement | Champs | Déclencheur |
|-----------|--------|-------------|
| `Snapshot` | `state` (SessionState) | Premier event d'un `subscribe` : état complet |
| `PresenceChanged` | `present` (list[Author]) | `join` / `leave` |
| `QueueEnqueued` | `item_id`, `author_name`, `color`, `text`, `ts` | `submit` |
| `QueueItemDeleted` | `item_id` | `delete_pending` |
| `RunStarted` | `item_id` | Début du run d'un item dans le worker |
| `MessagePosted` | `index`, `author_name`, `color`, `text` | Ajout du message user à la session |
| `AgentDelta` | `text` | Fragment de streaming (traduit depuis `AssistantDelta` mekicore) |
| `AgentDone` | `text` | Texte complet d'un tour (traduit depuis `AssistantDone`) |
| `ToolStarted` | `id`, `name`, `args` | Outil démarré (traduit depuis mekicore) |
| `ToolFinished` | `id`, `name`, `output` | Outil terminé (traduit depuis mekicore) |
| `RunFinished` | — | Fin normale du run |
| `RunError` | `message` | Erreur LLM ou exception attrapée (never-raise) |
| `Idle` | — | File vidée, rien en cours ni en attente |

## `hub.py` — SessionHub et PendingQueue

### `PendingQueue` (l.16)
File FIFO d'`QueueItem` supprimable par `item_id`. `pop_next()` est un coroutine qui attend (`Condition`)
si la file est vide. L'item **en cours** (déjà poppé) n'est plus dans `pending()` → `delete()` le refuse.
La notification du `Condition` est lancée dans la boucle asyncio courante (best-effort sans await).

### `SessionHub` (l.70)
Bus de conversation agnostique du transport (ni NiceGUI ni HTTP).

```python
SessionHub(store, llm_factory, tools, dispatch)
```

- `store` : `SessionStore` — CRUD sessions.
- `llm_factory` : `() -> LLM` — fabrique un objet LLM (appelé à chaque worker).
- `tools` / `dispatch` : schémas et handlers d'outils de mekicore (`TOOLS`, `DISPATCH`).
- `_rooms` : `dict[session_id, _Room]` — état runtime par session (file, worker, présence, abonnés).

**Méthodes publiques :**
- `join(session_id, author)` (l.99) : ajoute à la présence, publie `PresenceChanged`.
- `leave(session_id, author)` (l.104) : retire de la présence, publie `PresenceChanged`.
- `submit(session_id, text, author) -> item_id` (l.109) : crée un `QueueItem`, l'enfile, publie
  `QueueEnqueued`, démarre le worker si besoin. Renvoie l'`item_id` (pour suppression ultérieure).
- `delete_pending(session_id, item_id) -> bool` (l.118) : supprime un item EN ATTENTE (pas en cours) ;
  publie `QueueItemDeleted` si trouvé.
- `snapshot(session_id) -> SessionState` (l.92) : instantané complet de la session (charge depuis le
  store + état runtime : file, running, présence).
- `subscribe(session_id)` (l.125) : **async generator**. Yield un `Snapshot` d'amorçage, puis les
  events publiés via `_publish` jusqu'à fermeture. S'auto-retire des abonnés dans le `finally`.

**Worker asyncio (`_run_worker`, l.141) :**
Une tâche asyncio par session, démarrée à la demande (`_ensure_worker`). Boucle tant que la file n'est
pas vide :
1. `pop_next()` (attend si vide) → `room.running = item`.
2. Publie `RunStarted`.
3. Charge la session, appelle `sess.add_user(item.text, author=item.author)`, sauvegarde.
4. Publie `MessagePosted`.
5. Appelle `mekicore.run_agent(sess.messages, llm, tools, dispatch, stream=True)` (SYNC) via
   `await asyncio.to_thread(next, gen, _DONE)` à chaque event.
6. Chaque event mekicore est traduit par `_translate` (par `type(e).__name__`, pas `isinstance`, pour
   éviter l'ambiguïté de nom de module avec mekicore/events.py) et publié si non None
   (`ThinkingStarted` et events non mappés → ignorés).
7. Exception attrapée → `RunError` publiée (never-raise : un run raté ne tue pas le hub).
8. Sauvegarde finale, `room.running = None`.
9. À la sortie de la boucle : publie `Idle`.

## `adapters/discord.py` — adaptateur Discord

### `FakeMessage` / `FakeDiscordClient`
Stubs réseau-free pour les tests. `FakeDiscordClient.send(channel_id, text) -> int` (index) ;
`edit(channel_id, message_id, text)` édite l'entrée ; `sent_texts()` renvoie tous les textes postés.

### `DiscordAdapter` (l.45)
Branche un client Discord (réel ou `FakeDiscordClient`) sur le `SessionHub`.

- `channel_session` : `dict[channel_id, session_id]` — mapping canal → session.
- `handle_message(msg: FakeMessage)` (l.54) : ignore les bots ; résout la session via `channel_session` ;
  construit un `Author` (couleur dérivée du hash de l'`author_id` via une palette de 6) ; démarre une
  tâche `_render_loop` si absente ou terminée ; appelle `hub.submit`.
- `_render_loop(channel_id, session_id)` (l.72) : consomme `hub.subscribe` (async gen) ; sur
  `RunStarted` envoie « … » via `client.send` (mémorise le `msg_id`) ; sur `AgentDelta` édite le
  message en cours ; sur `AgentDone` édite avec le texte final ; sur `Idle` sort de la boucle.
- `flush()` (l.91) : attend toutes les tâches de rendu en cours (`asyncio.gather`) — utile dans les
  tests pour s'assurer que les renders sont terminés avant de vérifier.
- `connect_real(token)` (l.96) : connexion Discord réelle (importe `discord` à la demande — dépendance
  optionnelle) ; câble `on_message` → `handle_message` ; appelle `client.start(token)`.

## `main.py` — entrypoint

- `build_hub()` (l.20) : construit un `SessionHub` câblé sur `mekillm.LLM` + les outils de mekicore
  (`TOOLS`, `DISPATCH` depuis `tools.py`).
- `main()` (l.29) : lit `MEKIHUB_FRONT` (défaut `on`) et `MEKIHUB_DISCORD` (défaut `off`).
  - Headless (`FRONT=off`, `DISCORD=on`) : boucle asyncio Discord seule.
  - Front activé : délègue à `mekichat/app.py` (qui a son propre hub module-level).
  - Guard : `__name__ in {"__main__", "__mp_main__"}` (compatible NiceGUI).

Variables d'environnement consommées :

| Variable | Défaut | Rôle |
|----------|--------|------|
| `MEKIHUB_FRONT` | `on` | Active le front NiceGUI |
| `MEKIHUB_DISCORD` | `off` | Active l'adaptateur Discord |
| `DISCORD_BOT_TOKEN` | — | Token bot Discord (requis si `MEKIHUB_DISCORD=on`) |
| `MEKICHAT_SESSIONS_DIR` | `.sessions/` | Répertoire des sessions JSON |

## Lancer

```bash
# Mode complet (front web)
python packages/mekihub/main.py          # ou MEKIHUB_FRONT=on python packages/mekichat/app.py

# Headless Discord
MEKIHUB_FRONT=off MEKIHUB_DISCORD=on DISCORD_BOT_TOKEN=<tok> python packages/mekihub/main.py
```

## Statut

**Hub temps réel livré.**
- Couche session canonique (`session.py`) : `Author`, `QueueItem`, `Session.add_user`, `SessionState`,
  `SessionStore` (authors persisté, présence/file éphémères).
- Events de salle (`events.py`) : 13 types couvrant la vie de la file, la présence et le run d'agent.
- Bus pub/sub + worker FIFO (`hub.py`) : `PendingQueue`, `SessionHub` (join/leave/submit/delete_pending/
  snapshot/subscribe), worker asyncio qui ponte le générateur SYNC mekicore via `asyncio.to_thread`.
- Adaptateur Discord (`adapters/discord.py`) : `DiscordAdapter` + stubs réseau-free.
- Front `mekichat` remanié en adaptateur NiceGUI multi-utilisateur (présence, broadcast live, UI file
  d'attente avec suppression de messages en attente).
- Non-régression réseau-free : `tests/smoke_mekihub.py` (FakeLLM + FakeDiscordClient).

## Relations entrantes / sortantes

- Dépend de [mekicore](mekicore.md) (`run_agent`, `events.py`, `TOOLS`, `DISPATCH`).
- Dépend de [mekillm](mekillm.md) indirectement (via `mekicore` + `mekillm.LLM` dans `build_hub`).
- [mekichat](mekichat.md) est devenu un **adaptateur** du `SessionHub` (son `sessions.py` ré-exporte
  la couche session de mekihub ; son `app.py` instancie un `SessionHub` module-level).
- L'adaptateur Discord (`adapters/discord.py`) consomme le hub depuis un canal Discord.
- Non-régression : `tests/smoke_mekihub.py` (tous les aspects : file, pub/sub, worker, Discord).
