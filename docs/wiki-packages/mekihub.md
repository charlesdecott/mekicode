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
   │             dispatch_factory(workspace) → DISPATCH confiné par session
   │             approve_worktree / reject_worktree (worktree multi-projet)
   ▼
session.py   ── couche session canonique : Author, QueueItem, Session, SessionMeta, SessionState
   │             SessionStore (CRUD JSON, .sessions/ à la racine)
   │             add_user(content, *, author) : range l'auteur dans Session.authors, séparé des messages OpenAI
   │             champs projet : project_id, scope, discord_channel_id (Session) ; source (Author)
   ▼
projects.py  ── Project (dataclass) + ProjectRegistry (CRUD JSON .mekicode/projects.json)
   │             helpers worktree : add_worktree / list_worktrees / remove_worktree
   │             workspace_for(session, registry) → cwd absolu de la session
   ▼
events.py    ── événements émis par SessionHub, consommés par les adaptateurs
   │             Snapshot / PresenceChanged / QueueEnqueued / QueueItemDeleted
   │             RunStarted / MessagePosted(source) / AgentDelta / AgentDone
   │             ToolStarted / ToolFinished / RunFinished / RunError / Idle
   │             WorktreeProposed / WorktreeRejected / WorktreeCreated
   ▼
adapters/
  discord.py ── DiscordProvisioner : ensure_server/project/channel/reconcile (idempotent)
                 DiscordAdapter : mapping canal → session ; handle_message (source="discord:<canal>") ;
                 _render_loop avec anti-écho ; FakeDiscordClient étendu (guild/catégorie/canal)
```

## `projects.py` — registre multi-projet et worktrees

Nouveau module (branche `feat/multi-projet-worktree-discord`). Pur Python, sans réseau ni NiceGUI.
Registre persisté dans **`.mekicode/projects.json`** à la racine du dépôt hôte.

- **`Project`** (dataclass) : `id` (UUID court), `slug` (identifiant fichier-safe), `name`, `repo_path`
  (chemin absolu du dépôt git), `default_branch`, `discord` (dict de config Discord optionnel),
  `created_at`.
- **`ProjectRegistry(path=None, worktrees_base=None)`** : CRUD JSON du fichier `.mekicode/projects.json`.
  - `register(repo_path, name=None) -> Project` : refuse un chemin qui n'est pas un dépôt git
    (lève `ValueError`) ; génère le slug depuis le nom ou le basename du chemin ; persiste et renvoie
    le `Project`.
  - `list() -> list[Project]`, `get(id) -> Project | None`, `get_by_slug(slug) -> Project | None`.
  - `remove(id)`, `update(project)`.
  - `ensure_default() -> Project` : garantit l'existence d'un projet « mekicode » pointant la racine
    du dépôt courant (back-compat pour les sessions plates créées avant le multi-projet).
- **Helpers worktree :**
  - `slugify(name) -> str` : identifiant fichier-safe depuis un nom libre.
  - `_wt_dir(project, name, worktrees_base=None) -> Path` : chemin cible. **Défaut : `<repo>/.worktrees/<slug>`**
    (à la racine DU projet) ; `worktrees_base` (override, ex. tests) → `<base>/<slug-projet>/<slug>`.
  - `add_worktree(project, name, base=None, worktrees_base=None, copy_ignored=…) -> Path` : `git worktree add`
    (réutilise la branche `slugify(name)` si elle existe, sinon `-b`) ; **copie les fichiers RÉELLEMENT
    gitignorés** (`.env`… via `git check-ignore` — ni fichiers suivis ni secrets non-ignorés, jamais en
    silence) que `git worktree add` ne checkout pas ; pour les worktrees in-repo, garantit `.worktrees/`
    ignoré via **`.git/info/exclude`** (local, sans salir le `.gitignore` suivi). Renvoie le chemin.
  - `list_worktrees(project) -> list[dict]` : parse `git worktree list --porcelain`.
  - `remove_worktree(project, name, delete_branch=True)` : `git worktree remove --force` + `worktree prune`
    + suppression de la branche (cycle créer/supprimer/recréer idempotent).
- **`workspace_for(session, registry) -> Path`** : cwd absolu d'une session — racine du projet si
  `session.scope == "main"`, sinon `_wt_dir(project, session.scope)` ; repli sur la racine mekicode
  si le registre est absent ou si le projet est introuvable.

## `session.py` — couche session canonique

Superset de l'ancienne `packages/mekichat/sessions.py` (qui la ré-exporte désormais via un shim).
Pur Python, sans réseau ni NiceGUI. Données runtime dans `.sessions/` à la **racine du projet**
(jamais dans `packages/`).

- **`Author`** (dataclass, l.25) : participant éphémère de la salle. `id` = UUID de connexion (pas un
  compte permanent), `name`, `color` (couleur d'affichage libre), `source` (optionnel : `"discord:<canal>"`
  pour les messages provenant d'un canal Discord, `None` pour les messages locaux).
- **`QueueItem`** (dataclass, l.33) : item en attente dans la file. `item_id` (hex court), `author`
  (Author), `text`, `ts` (ISO UTC).
- **`Session`** (dataclass, l.41) :
  - `messages` : liste de dicts OpenAI **purs** (ce que l'agent voit ; pas de champ auteur).
  - `authors` : `dict` index_message → `{"name", "color"}` — **attribution séparée** des messages OpenAI.
  - `project_id` (défaut `"mekicode"`) : projet auquel appartient la session.
  - `scope` (défaut `"main"`) : `"main"` pour la branche principale, ou le nom du worktree.
  - `discord_channel_id` (optionnel) : canal Discord associé à cette session.
  - `add_user(content, *, author) -> int` (l.49) : ajoute le message user dans `messages` ET range
    l'attribution dans `authors[idx]` ; renseigne `title` à la première vraie saisie (48 car. max).
  - `add(role, content, **extra) -> dict` (l.59) : méthode compat historique (mekichat), sans auteur.
- **`SessionMeta`** (dataclass, l.70) : vue légère (`id`, `title`, `model`, `created_at`, `n_messages`,
  `project_id`, `scope`) pour les listes/barres latérales.
- **`SessionState`** (dataclass, l.79) : instantané partagé renvoyé par `SessionHub.snapshot()` :
  `messages`, `authors`, `queue` (list[QueueItem] en attente), `running` (QueueItem | None), `presence`
  (list[Author]).
- **`SessionStore`** (class, l.90) : CRUD, un fichier `<id>.json` par session. `authors` est persisté
  (clés int en mémoire → str sur disque, reconverties à la lecture) ; file et présence sont **éphémères**
  (non persistées). Résout le répertoire depuis l'argument, `MEKICHAT_SESSIONS_DIR`, ou `.sessions/`.
  Méthodes :
  - `create(model, system=None, *, project_id="mekicode", scope="main") -> Session` : génère un id
    court, sème éventuellement un message `system`, sauvegarde et renvoie la session.
  - `save(session)`, `load(session_id)`, `delete(session_id)`.
  - `list(project_id=None, scope=None) -> list[SessionMeta]` : plus récentes d'abord ; filtre
    optionnel par `project_id` et/ou `scope` ; ignore les fichiers corrompus. Migration douce :
    les anciens fichiers sans ces champs sont lus avec `project_id="mekicode"`, `scope="main"`.

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
| `MessagePosted` | `index`, `author_name`, `color`, `text`, `source` | Ajout du message user à la session (`source` = `"discord:<canal>"` ou `None`) |
| `AgentDelta` | `text` | Fragment de streaming (traduit depuis `AssistantDelta` mekicore) |
| `AgentDone` | `text` | Texte complet d'un tour (traduit depuis `AssistantDone`) |
| `ToolStarted` | `id`, `name`, `args` | Outil démarré (traduit depuis mekicore) |
| `ToolFinished` | `id`, `name`, `output` | Outil terminé (traduit depuis mekicore) |
| `RunFinished` | — | Fin normale du run |
| `RunError` | `message` | Erreur LLM ou exception attrapée (never-raise) |
| `Idle` | — | File vidée, rien en cours ni en attente |
| `WorktreeProposed` | `proposal_id`, `session_id`, `name`, `base` | L'agent a proposé la création d'un worktree (outil `spawn_worktree`) |
| `WorktreeRejected` | `proposal_id`, `session_id` | La proposition a été refusée |
| `WorktreeCreated` | `proposal_id`, `session_id`, `name`, `path`, `child_session_id` | Le worktree a été créé et sa session enfant démarrée |

## `hub.py` — SessionHub et PendingQueue

### `PendingQueue` (l.16)
File FIFO d'`QueueItem` supprimable par `item_id`. `pop_next()` est un coroutine qui attend (`Condition`)
si la file est vide. L'item **en cours** (déjà poppé) n'est plus dans `pending()` → `delete()` le refuse.
La notification du `Condition` est lancée dans la boucle asyncio courante (best-effort sans await).

### `SessionHub` (l.70)
Bus de conversation agnostique du transport (ni NiceGUI ni HTTP).

```python
SessionHub(store, llm_factory, tools, dispatch=None, *,
           dispatch_factory=None, registry=None, provisioner=None)
```

- `store` : `SessionStore` — CRUD sessions.
- `llm_factory` : `() -> LLM` — fabrique un objet LLM (appelé à chaque worker).
- `tools` : schémas d'outils de mekicore (`TOOLS`).
- `dispatch` : table des handlers (conservée pour back-compat standalone).
- `dispatch_factory(workspace) -> dict` : **prioritaire** sur `dispatch` — fabrique un DISPATCH
  confiné au `workspace` de la session (corrige la concurrence multi-session ; cf. `mekicore/tools.py`).
- `registry` : `ProjectRegistry | None` — si fourni, expose l'outil agent `spawn_worktree`
  (schéma `WORKTREE_TOOL`) et résout le `workspace_for` de chaque session.
- `provisioner` : `DiscordProvisioner | None` — appelé lors du `approve_worktree` pour créer le
  canal Discord de la session enfant.
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
- `approve_worktree(session_id, proposal_id)` (async) : exécute `git worktree add` via
  `projects.add_worktree`, crée une **session enfant** (`scope=nom_worktree`, `cwd=worktree`), l'amorce
  du prompt initial, lance son worker, appelle `provisioner.ensure_channel` si fourni, publie
  `WorktreeCreated`. La session **main** reste vivante et continue de traiter sa file.
- `reject_worktree(session_id, proposal_id)` (sync) : publie `WorktreeRejected`, aucun worktree créé.

**Worker asyncio (`_run_worker`, l.141) :**
Une tâche asyncio par session, démarrée à la demande (`_ensure_worker`). Résout `workspace_for(sess, registry)`,
appelle `dispatch_factory(workspace)` si fourni. Boucle tant que la file n'est pas vide :
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

### `DiscordProvisioner` (l.15)
Provisioning idempotent d'un serveur Discord pour un ou plusieurs projets. Toutes les méthodes
sont idempotentes : ré-appeler ne crée pas de doublon.

- `DiscordProvisioner(registry, client, *, guild_id=None, admin_user_id=None)` : lit `guild_id`
  depuis le paramètre ou l'env `DISCORD_GUILD_ID`.
- `ensure_server() -> guild_id` : utilise le guild existant (`DISCORD_GUILD_ID`) ou en crée un via
  `client.create_guild("mekicode")` ; mémorise l'id.
- `ensure_project(project)` : crée deux catégories dans le serveur — `<slug>-main` et
  `<slug>-worktrees` — si elles n'existent pas déjà.
- `ensure_channel(session) -> channel_id` : crée (ou retrouve) le canal textuel correspondant à la
  session dans la catégorie adéquate (`<slug>-main` si `scope=="main"`, sinon `<slug>-worktrees`) ;
  nom du canal : `main-<titre8>` ou `<worktree>-<id8>`. Retourne l'`channel_id`.
- `reconcile(store)` : parcourt toutes les sessions du store et crée les canaux manquants — point
  d'entrée pour la synchro initiale lors du démarrage.
- `provisioner_from_env(registry, client) -> DiscordProvisioner | None` : factory import-safe ;
  renvoie `None` si `DISCORD_BOT_TOKEN` est absent (dépendance optionnelle).

### `FakeDiscordClient` (étendu)
Stubs réseau-free pour les tests. En plus de `send` / `edit` / `sent_texts` :
`create_guild(name)`, `create_category(guild_id, name)`, `create_channel(guild_id, category_id, name)`,
`create_invite(channel_id)` ; compteurs d'appels pour valider l'idempotence dans les tests.

### `DiscordAdapter` (l.90)
Branche un client Discord (réel ou `FakeDiscordClient`) sur le `SessionHub`.

- `channel_session` : `dict[channel_id, session_id]` — mapping canal → session.
- `handle_message(msg: FakeMessage)` (l.99) : ignore les bots ; résout la session via `channel_session` ;
  construit un `Author` avec `source="discord:<channel_id>"` (couleur dérivée du hash de l'`author_id`
  via une palette de 6) ; démarre une tâche `_render_loop` si absente ou terminée ; appelle `hub.submit`.
- `_render_loop(channel_id, session_id)` (l.117) : consomme `hub.subscribe` (async gen) ; sur
  `RunStarted` envoie « … » via `client.send` (mémorise le `msg_id`) ; sur `AgentDelta` édite le
  message en cours ; sur `AgentDone` édite avec le texte final ; sur `Idle` sort de la boucle.
  **Anti-écho** : si `event.source == "discord:<channel_id>"`, le message n'est PAS reposté dans ce
  même canal (évite l'écho miroir d'un message arrivé de Discord).
- `flush()` (l.138) : attend toutes les tâches de rendu en cours (`asyncio.gather`) — utile dans les
  tests pour s'assurer que les renders sont terminés avant de vérifier.
- `_render_loop(..., persistent=False)` : si `persistent=True`, ne sort PAS sur `Idle` (miroir
  permanent entre les runs, requis pour refléter les messages venus du front web). `start_all()` démarre
  un rendu persistant par canal mappé ; `add_mapping(channel_id, session_id)` câble un canal à chaud.
- `connect_real(token)` : ancienne amorce de connexion réelle (conservée).

### `RealDiscordClient` + `run_discord` (intégration réelle)
- **`RealDiscordClient(discord.Client)`** : adapte un vrai client `discord.py` à l'interface attendue
  (`send`/`edit`/`create_guild`/`create_category`/`create_channel`/`create_invite`).
- **`run_discord(hub, registry, store, *, token, guild_id, admin_user_id, holder)`** : démarre le bot,
  câble `on_message → handle_message`, et à `on_ready` : `reconcile(store)` (crée catégories + canaux),
  reconstruit le mapping canal→session, lance `start_all()` (miroir bidirectionnel). `holder` reçoit
  `adapter`/`provisioner` pour le câblage à chaud des nouvelles sessions. **Validé en réel** (création
  live des catégories/canaux + miroir web↔Discord). Lancé par `mekichat/app.py` via `app.on_startup`
  si `DISCORD_BOT_TOKEN` est posé (sinon no-op).

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
| `DISCORD_GUILD_ID` | — | ID du serveur Discord cible (optionnel ; sinon création d'un nouveau serveur) |
| `MEKICODE_ADMIN_USER_ID` | — | ID utilisateur Discord invité automatiquement à la création du serveur |
| `MEKICHAT_SESSIONS_DIR` | `.sessions/` | Répertoire des sessions JSON |

## Lancer

```bash
# Mode complet (front web)
python packages/mekihub/main.py          # ou MEKIHUB_FRONT=on python packages/mekichat/app.py

# Headless Discord
MEKIHUB_FRONT=off MEKIHUB_DISCORD=on DISCORD_BOT_TOKEN=<tok> python packages/mekihub/main.py
```

## Statut

**Hub temps réel livré + multi-projet + worktree par chat + provisioning Discord.**
- Couche session canonique (`session.py`) : `Author` (+ `source`), `QueueItem`, `Session.add_user`,
  `SessionState`, `SessionStore` (authors persisté, présence/file éphémères ; champs `project_id`,
  `scope`, `discord_channel_id` ; migration douce des anciens fichiers).
- Registre multi-projet (`projects.py`) : `Project`, `ProjectRegistry` (CRUD JSON), `workspace_for`,
  helpers worktree (`add_worktree`, `list_worktrees`, `remove_worktree`).
- Events de salle (`events.py`) : 16 types — 13 originaux + `WorktreeProposed`, `WorktreeRejected`,
  `WorktreeCreated` ; `MessagePosted` enrichi du champ `source`.
- Bus pub/sub + worker FIFO (`hub.py`) : `PendingQueue`, `SessionHub` (constructeur étendu :
  `dispatch_factory`, `registry`, `provisioner` ; nouvelles méthodes : `approve_worktree`,
  `reject_worktree`), workspace confiné par session, outil agent `spawn_worktree`.
- Provisioning Discord (`adapters/discord.py`) : `DiscordProvisioner` (idempotent : serveur, projet,
  canal, reconcile) + `DiscordAdapter` avec anti-écho + `FakeDiscordClient` étendu.
- Front `mekichat` remanié en adaptateur NiceGUI multi-utilisateur (présence, broadcast live, UI file
  d'attente, sélecteur Projet→scope→session, carte de validation worktree).
- Non-régression réseau-free : `tests/smoke_mekihub.py` (FakeLLM + FakeDiscordClient étendu ; projets,
  workspace, worktree propose/approve/reject, provisioner idempotent, anti-écho, reconcile).
- Validation Discord RÉELLE : manuelle (nécessite un token bot Discord valide).

## Relations entrantes / sortantes

- Dépend de [mekicore](mekicore.md) (`run_agent`, `events.py`, `TOOLS`, `DISPATCH`).
- Dépend de [mekillm](mekillm.md) indirectement (via `mekicore` + `mekillm.LLM` dans `build_hub`).
- [mekichat](mekichat.md) est devenu un **adaptateur** du `SessionHub` (son `sessions.py` ré-exporte
  la couche session de mekihub ; son `app.py` instancie un `SessionHub` module-level).
- L'adaptateur Discord (`adapters/discord.py`) consomme le hub depuis un canal Discord.
- Non-régression : `tests/smoke_mekihub.py` (tous les aspects : file, pub/sub, worker, Discord).
