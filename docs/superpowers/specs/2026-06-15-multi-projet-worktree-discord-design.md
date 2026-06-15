# Design — mekicode multi-projet + worktree par chat + Discord

> Spec validée le 2026-06-15. Cible : `packages/` (extension de `mekihub`). Approche **A**
> (étendre le hub existant), discipline **YAGNI/DRY** : additif, sans doublon, réutilise le moteur.

## 1. Objectif

Transformer mekichat (front mono-projet, sessions plates) en orchestrateur **multi-projet** :

- on choisit un **projet** (dépôt git externe enregistré par chemin) et on voit ses sessions ;
- l'agent peut, en cours de conversation, **proposer de créer un worktree git** (nouvelle feature,
  changement ambitieux, debug — pour ne pas bloquer `main`) ou de reprendre un worktree existant ;
  après **validation humaine**, mekicode crée le worktree et **lance une session enfant** amorcée d'un
  prompt, en parallèle de `main` ;
- tout se reflète sur **Discord** : une catégorie `<projet>-main` + une catégorie `<projet>-worktrees`,
  un canal par conversation, **miroir bidirectionnel** (piloter depuis Discord ou le front).

## 2. Décisions (cadrage validé)

| # | Décision | Choix |
|---|----------|-------|
| 1 | Portée | Concevoir P1+P2+P3 ensemble, **implémenter P1→P2→P3** |
| 2 | Projet | **Dépôt git externe** par chemin ; `cwd` agent = racine projet (ou worktree) |
| 3 | Discord | **2 catégories/projet** : `<slug>-main` + `<slug>-worktrees` |
| 4 | Bootstrap serveur | **Auto** (`POST /guilds`) si possible, **sinon** serveur existant + invitation bot |
| 5 | Synchro | **Miroir bidirectionnel** (Discord ↔ front, multi-user) |
| 6 | Import historique | **Forward-only** pour l'instant ; backfill complet **différé** (§9) |
| 7 | Worktrees | **Outil agent gated** : agent propose → validation → worktree + canal + session enfant amorcée ; `main` reste vivante |
| 8 | Stockage sessions | **Centralisé** dans mekicode, rangé par projet (multi-user) |

## 3. Architecture (extension de `mekihub`)

Le moteur ne change pas : worker asyncio + pub/sub **par session**, et **N sessions tournent déjà en
parallèle** — c'est ce qui fait vivre `main` et les worktrees simultanément.

| Unité | Statut | Rôle |
|---|---|---|
| `projects.py` | **neuf** | `Project`, `ProjectRegistry` (CRUD JSON), helpers `git worktree`, `workspace_for(session)` |
| `adapters/discord.py` | **modifié** | + `DiscordProvisioner` (serveur/catégories/canaux, idempotent) ; mapping dynamique ; mirroring bidirectionnel anti-écho |
| `session.py` / `SessionStore` | **modifié** | champs `project_id`/`scope`/`workspace_path`/`discord_channel_id` ; rangement `.sessions/<project_id>/` |
| `hub.py` | **modifié (léger)** | events `WorktreeProposed`/`WorktreeRejected` + `approve_worktree()` ; injecte le `workspace` dans `run_agent` |
| `mekicore` `run_agent` + `tools.py` | **modifié** | param **`workspace` (cwd)** au lieu de `Path.cwd()` ; outils fichiers confinés à ce workspace |
| outil `spawn_worktree` | **neuf (petit)** | émet une proposition, **n'exécute pas** directement |
| front `mekichat` | **modifié** | navigation **Projet → scope → session** + carte de confirmation worktree (réutilise `views.py`) |

Principe d'isolation : chaque unité = *ce qu'elle fait / comment on l'utilise / ce dont elle dépend*.
`workspace_for` = un `if scope=="main"` (pas de module). Worktree = fin wrapper `git worktree` dans
`projects.py` (un worktree appartient à un projet). Provisioning Discord dans le fichier Discord existant.

## 4. Modèle de données

**Registre projets** — `.mekicode/projects.json` (racine mekicode) :

```json
{ "projects": [
  { "id": "p_8f3a", "slug": "mekipedia", "name": "Mekipedia",
    "repo_path": "C:/Coding/mekipedia", "default_branch": "main",
    "discord": { "guild_id": "…", "cat_main": "…", "cat_worktrees": "…" },
    "created_at": "2026-06-15T…" } ] }
```

**Sessions** — centralisées, `.sessions/<project_id>/<session_id>.json`. `Session` gagne `project_id`,
`scope` (`"main"` ou nom de worktree), `workspace_path` (cwd résolu), `discord_channel_id`.
*Back-compat :* les sessions plates actuelles sont migrées sous un projet `mekicode` au premier lancement.

**Worktrees sur disque** — `.mekicode-worktrees/<slug>/<nom>/` (un `git worktree` du dépôt externe,
hors du repo pour ne pas le salir, mais rattaché à son `.git`).

**Nommage canaux Discord** (lowercase/hyphénés, dédup par suffixe court) : main `main-<titre-slug>`
(fallback `main-<id8>`) ; worktree `<worktree-slug>-<id8>` (ex. `featx-1a2b`).

## 5. Flux worktree-spawn (P2)

1. L'agent appelle **`spawn_worktree(nom, prompt_amorce, base?)`**.
2. L'outil **n'exécute rien** : publie `WorktreeProposed`, rend « en attente de validation ». Le tour finit.
3. Front + Discord affichent **Approuver / Refuser**.
4. *Approuver* → `hub.approve_worktree(...)` : `git worktree add .mekicode-worktrees/<slug>/<nom> -b <nom>`
   → crée la **session enfant** (scope=`<nom>`, cwd=worktree) amorcée du prompt → `ensure_channel`
   (`<nom>-<id8>` sous `<slug>-worktrees`) → démarre son worker. **`main` reste vivante.**
5. *Refuser* → `WorktreeRejected`, rien créé.

Réutilise : le hub démarre déjà un worker par session ; la session enfant reçoit le prompt comme
premier message user.

## 6. Provisioning + synchro Discord (P3)

`DiscordProvisioner` (idempotent, piloté par les ids mémorisés dans le registre → **jamais de doublon**) :

- `ensure_server()` : `DISCORD_GUILD_ID` posé → l'utilise ; sinon `POST /guilds` (auto) ; échec
  (≥10 serveurs) → loggue + génère un **lien d'invitation** du bot pour l'admin (`MEKICODE_ADMIN_USER_ID`).
- `ensure_project()` : crée les 2 catégories, mémorise leurs ids.
- `ensure_channel(session)` : crée le canal dans la bonne catégorie selon `scope`, stocke `discord_channel_id`.
- `reconcile()` au démarrage : parcourt projets+sessions, crée **ce qui manque**. C'est la **synchro**.

**Messages bidirectionnels** (`DiscordAdapter` étendu) : entrant Discord → `hub.submit` (déjà fait) ;
sortant → render loop poste/édite la réponse (déjà fait) **+** rend `MessagePosted` (messages humains).
**Anti-écho** : origine taguée sur l'`Author` (`source="discord:<canal>"`) ; un message né dans Discord
n'est pas re-posté dans son canal.

## 7. Gestion d'erreurs (never-raise, comme le hub aujourd'hui)

- Chemin non-git → refus net à l'enregistrement, message clair.
- `git worktree add` échoue (nom/branche pris) → event d'erreur, agent informé, rien cassé.
- **Discord absent/sans token → hub + front fonctionnent sans Discord** (adaptateur optionnel, déjà le
  cas) ; provisioning loggue et réessaie au prochain `reconcile`.
- Rate limit Discord → throttle/backoff dans provisioner et render loop.

## 8. Tests (réseau-free, sans clé, dans `tests/`)

Étendre `tests/smoke_mekihub.py` : `ProjectRegistry` CRUD, `workspace_for`, worktree sur repo git
temporaire, flux `spawn_worktree`→approve avec `FakeLLM`, provisioning avec `FakeDiscordClient`
(catégories/canaux/**idempotence**/anti-écho). `tests/smoke_packages.py` et `tests/smoke_mekichat.py`
restent verts (session plate migrée sous un projet `mekicode`). `python -m py_compile` sur tout `.py`
modifié.

## 9. Évolutions différées (notées, hors périmètre immédiat)

- **Backfill complet de l'historique Discord** (option 1 de la décision 6) : reposter tout l'historique
  d'une session dans le canal au moment de l'import (découpage 2000 car + throttle rate-limit).
- **Convs perso locales vs partagées centralisées** : possibilité future de sessions stockées dans
  `<projet>/.mekicode/` (perso) en plus du store central (partagé multi-user).
- **Transfert de propriété** du serveur auto-créé (bot → admin) : manuel (UI Discord + 2FA).

## 10. Séquençage d'implémentation

- **P1 — Fondation** : `ProjectRegistry`, `workspace_for`, `run_agent(workspace=…)`, `SessionStore`
  project-scoped + migration, front navigation Projet→scope→session.
- **P2 — Worktree** : helpers git, outil `spawn_worktree`, events + `approve_worktree`, UI confirmation,
  session enfant amorcée.
- **P3 — Discord** : `DiscordProvisioner` (server/catégories/canaux/reconcile), mirroring bidirectionnel
  anti-écho, intégration au démarrage.

Chaque phase : code + tests réseau-free verts + `py_compile` + mise à jour manuelle de
`docs/wiki-packages/`.
