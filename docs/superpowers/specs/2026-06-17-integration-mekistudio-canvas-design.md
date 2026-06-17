# Design — Intégration de mekistudio (canvas + nodes) dans mekicode

> Spec validée au brainstorming le 2026-06-17. Cible : un nouveau package front `packages/mekistudio/`
> (regroupe le chat + le canvas + la coquille), extensions de `mekicore` / `mekihub`. Approche **A**
> (canvas embarqué dans NiceGUI, tout modulaire), discipline **YAGNI/DRY** : on réutilise la géométrie
> *pure* de mekistudio et l'orchestration existante (mekihub), on ne réécrit pas le moteur.

## 0. Brief (l'ébauche, polie)

Intégrer **mekistudio** (le studio visuel à canvas infini : nodes reliées par des câbles « métro » 45°
avec impulsions) dans **mekicode**, mais piloté par **notre propre harness** (`mekicore`/`mekihub`) au
lieu du Claude Code CLI. Le front devient un **studio à 3 modes** : *Chat seul*, *Canvas seul*, *Mix*
(chat focus à gauche + canvas à droite ; cliquer une node de chat rebascule le chat affiché). Les
événements du canvas (comètes, lueurs) ne sont plus branchés sur les hooks de Claude Code mais sur
**nos hooks**. On garde le design des **câbles 45° à impulsions, sans overlap**, et les nodes
**éditeur/preview**. On adapte le **multi-user** et la **file d'attente**, et on crée de **nouvelles
nodes** (ex. la node *file d'attente*, sous le chat). On ajoute aussi **s15 — Permissions — gouvernance
3 tiers** autour de `dispatch_tools`. Tout est **modulaire en NiceGUI** : un composant `Chat` unique
réutilisé partout, des fonctions de hooks partagées chat/canvas, des nodes qui dérivent d'une node-parent
de base **et** se composent de composants réutilisables.

## 1. Objectif (Sprint 1)

Livrer une **tranche verticale démo-able** : une seule app NiceGUI, un seul port, **3 modes**
(Chat / Canvas / Mix). Le canvas affiche `Kernel → ChatNode → QueueNode` reliés par des câbles néon 45°
avec **comètes pilotées par nos hooks**. **s15 Permissions 3 tiers** branché autour de `dispatch_tools`,
avec un tier *ask* asynchrone (carte façon Claude Code). Fichiers / Terminal / Git / multi-canvas =
sprints suivants.

## 2. La vision complète (roadmap 4 sprints)

| Sprint | Contenu | Statut |
|---|---|---|
| **1 — Fondations + Canvas MVP** | Refactor `ChatComponent` ; **HookBus** mekicore ; **s15 permissions 3 tiers** ; coquille 3 modes ; canvas NiceGUI (pan/zoom + câbles 45° + comètes) ; `BaseNode`/`BaseComponent` + registry + parenting ; nodes Kernel/Chat/Queue ; impulsions | **ce spec** |
| **2 — Fichiers** | `ExplorerNode` (FileTree), `EditorNode` + **preview**, `FolderNode`, `SubcanvasNode`, éditeurs **éphémères** auto-spawn sur lecture (pin, TTL), impulsions fichier | conçu, à détailler |
| **3 — Multi-user temps réel canvas** | Présence/curseurs sur le canvas, file d'attente partagée dans la QueueNode (multi-auteurs), **sync canvas multi-clients**, `TerminalNode` (PTY) + `GitNode` | esquissé |
| **4 — Échelle & polish** | Multi-canvas (onglets), worktrees git = subcanvas imbriqués, QCM/`ask_user` agent en plein tour, palette d'ajout de nodes, thème, perfs | esquissé |

Chaque sprint : spec → plan → implémentation → vérif → validation humaine.

## 3. Décisions (cadrage validé)

| # | Décision | Choix |
|---|----------|-------|
| 1 | Stratégie d'intégration front | **A** — canvas **embarqué dans NiceGUI** (un serveur, un port), pas le JS mekistudio en bloc |
| 2 | Modularité | Tout NiceGUI : `BaseComponent`/`BaseNode`, composition + héritage ; `ChatComponent` **unique** partagé ; bus de hooks **unique** partagé chat/canvas |
| 3 | Modes d'affichage | **3 modes** : Chat / Canvas / **Mix** (clic sur ChatNode → `set_focus(session)` du chat de gauche) |
| 4 | Réutilisation canvas | Seule la **géométrie pure** de mekistudio est vendorée (`cables.js`, `collision.js`) ; le **contenu** des nodes est 100 % NiceGUI |
| 5 | Hooks | **Nos hooks** (`pre_tool` vetoable / `post_tool`) dans `dispatch_tools` ; rendu (tool-cards / impulsions) piloté par le flux d'events mekihub via helper partagé `impulse_for` |
| 6 | Permissions s15 | 3 tiers (deny→allow→ask→défaut allow) + **résolution en couches** (session → projet → global) ; tier *ask* **asynchrone** |
| 7 | Qui tranche un *ask* | **Auteur du run ou admin** (`MEKICODE_ADMIN_USER_ID`) ; `timeout → deny` |
| 8 | Portée d'une autorisation *ask* | Façon **Claude Code** : autoriser *une fois* / *cette session* / *ce projet* / refuser / refuser+**blacklist** |
| 9 | Multi-user / queue (Sprint 1) | **Réutilise mekihub** (file FIFO + présence **par session**) ; QueueNode **rend** la file ; canvas reflète la session sélectionnée ; **sync canvas multi-clients reportée au Sprint 3** |
| 10 | Structure | Nouveau package front **`packages/mekistudio/`** (chat + canvas + shell) ; `mekicore`/`mekillm`/`mekihub` restent **packages frères** (back/logique, partagés avec Discord) |
| 11 | Placement nodes (Sprint 1) | Déterministe simple (kernel haut → chat → queue) ; layout radial organique (`zonelayout.js`) reporté (Sprint 2/3) |

## 4. Structure des packages

```
packages/
  mekistudio/                  ← LE package front (« coquille studio »)
    __init__.py
    app.py                     ← entrée NiceGUI + coquille 3 modes
    shell.py                   ← sélecteur de mode (Chat/Canvas/Mix), set_focus(session), layout
    mekichat/                  ← module chat (déplacé depuis packages/mekichat/)
      chat_component.py        ← ChatComponent (NiceGUI réutilisable) — extrait de app.py/views.py
      queue_component.py       ← QueueComponent
      views.py, realtime.py, sessions.py
      static/                  ← mekichat.css (thème Phosphore)
    mekicanvas/                ← module canvas (neuf)
      base.py                  ← BaseComponent, BaseNode
      registry.py              ← kind → builder, parents canoniques
      parenting.py             ← dérivation du parent (non stocké)
      nodes/                   ← kernel.py, chat.py, queue.py
      impulses.py              ← impulse_for(event) (porté de impulseFor mekistudio)
      canvas_page.py           ← page NiceGUI : world, boucle hub.subscribe → run_javascript
      static/js/               ← cables.js, collision.js (vendorés MIT) + canvas.js (pan/zoom/SVG/comètes)
    static/                    ← assets front partagés
  ── back / logique (packages frères, inchangés sauf extension) ──
  mekicore/                    ← + hooks.py (HookBus) ; + permissions.py (s15) ; tools.py (gating dispatch)
  mekillm/                     ← inchangé
  mekihub/                     ← + event PermissionRequested ; + résolution ask dans le worker
```

> Entrée : `python packages/mekistudio/app.py` (remplace `packages/mekichat/app.py` / `start-chat.ps1`,
> à mettre à jour). Imports : `mekistudio` importe `mekicore`/`mekihub`/`mekillm` (jamais l'inverse).

## 5. Coquille 3 modes (`shell.py`)

- Sélecteur segmenté `Chat · Canvas · Mix` (état `mode` en `app.storage.user`).
- **Chat** : `ChatComponent` plein écran (mekichat actuel, intact fonctionnellement).
- **Canvas** : `canvas_page` plein écran.
- **Mix** : split — `ChatComponent` (focus) à gauche + `canvas_page` à droite. Clic sur une `ChatNode`
  → `shell.set_focus(session_id)` → le `ChatComponent` de gauche se relie à cette session.
- Le `ChatComponent` est **la même classe** dans les 3 usages (onglet, node, panneau focus) → une seule
  source de vérité d'UI de chat.

## 6. Modèle Node / Component (`mekicanvas/base.py`)

- `BaseComponent` : rendu NiceGUI, peut contenir d'autres composants **ou** des nodes. Sous-classes
  Sprint 1 : `HeaderComponent`, `ChatComponent` (importé de `mekichat`), `QueueComponent`.
- `BaseNode` : position `(x, y)`, `kind`, parent **dérivé** (non stocké), `collapsed`, se **compose** de
  composants. Sous-classes Sprint 1 : `KernelNode`, `ChatNode` (contient `ChatComponent`), `QueueNode`
  (contient `QueueComponent`).
- `registry.py` : `NODE_BUILDERS: dict[kind, builder]` + `CANONICAL_PARENT_KIND`.
- `parenting.py` : `derive_parent(node, all_nodes)` → câbles déduits de la hiérarchie (rien de stocké).

Invariant (repris de mekistudio) : **les câbles ne sont pas persistés**, ils dérivent du lien parent.

## 7. Plomberie canvas (le seul JS — `mekicanvas/static/js/`)

- **Nodes** = éléments NiceGUI positionnés en absolu dans un `world` (div transformé par CSS).
- **Pan/zoom** (`canvas.js`) = transform CSS + `scale`/`offset`, auto-fit.
- **Câbles** = overlay SVG. `canvas.js` lit les rects des nodes + liens parent, appelle la **géométrie
  pure vendorée** (`cables.js` : `subwayConnect`/`subwayPoints`/`assignLanes` + `collision.js` :
  segment-box) → trace les chemins 45° en rubans sans overlap. Redraw sur pan/zoom/drag/resize.
- **Comètes** = pilotées **côté serveur** : la page canvas a une boucle `hub.subscribe(session)` →
  `impulse_for(event)` (helper partagé) → intent `{kind:'comet'|'glow', target:{by,value}, level}` →
  `ui.run_javascript("MekiCanvas.impulse(<intent>)")` anime la comète le long du câble + glow de la node
  cible. (Équivalent serveur du `meki:impulse` de mekistudio.)
- **Géométrie testée hors DOM** : `cables.js`/`collision.js` restent purs → `node --test` (comme amont).
- **Placement Sprint 1** : déterministe simple en Python (kernel haut, chat dessous, queue sous le chat).
  Le layout radial organique est reporté.

## 8. HookBus (nos hooks — `mekicore/hooks.py`)

Bus synchrone, vetoable, branché dans `dispatch_tools` (`mekicore/tools.py`) :

```python
# pseudo-API
def on(name: str, fn) -> None: ...           # abonnement
def emit(name: str, payload: dict) -> bool:  # False si un abonné veto
    ok = True
    for fn in _subs.get(name, []):
        if fn(payload) is False:
            ok = False
    return ok
```

Dans `dispatch_tools`, **avant** d'exécuter un outil : `emit("pre_tool", {tool, input})` (vetoable) ;
**après** : `emit("post_tool", {tool, input, output})`. Les **permissions** sont un abonné `pre_tool`.
Le **rendu** (tool-cards chat / impulsions canvas) reste piloté par le flux d'events mekihub déjà diffusé
(`ToolStarted`/`ToolFinished`) → un vocabulaire de hooks **unique, partagé** chat + canvas.

> Remplace explicitement les hooks Claude Code (`PreToolUse`/`PostToolUse`) de mekistudio par **nos**
> hooks `pre_tool`/`post_tool`.

## 9. s15 — Permissions — gouvernance 3 tiers (`mekicore/permissions.py`)

### 9.1 Modèle

`check_permission(tool, input_str, ctx) -> Decision` où `Decision ∈ {ALLOW, DENY(reason), ASK(reason)}`.
Ordre d'évaluation (court-circuit) : **always_deny → always_allow → ask_user → défaut ALLOW**, regex
case-insensitive (depuis `config.yaml`, section `permissions`).

### 9.2 Résolution en couches

`ctx` porte `session_id` + `project_id`. La résolution consulte, dans l'ordre :

1. **surcharges session** (RAM, `dict[session_id] → règles`) ;
2. **surcharges projet** (persistées, `.mekicode/permissions/<project_id>.yaml`) ;
3. **règles globales** (`config.yaml`).

Une autorisation accordée écrit dans la couche correspondante (voir 9.4).

### 9.3 Tier *ask* asynchrone

`pre_tool` détecte un `ASK` → renvoie une sentinelle « pending » qui **interrompt** l'exécution du tool
sans le bloquer en synchrone. Le worker mekihub :

1. émet `PermissionRequested{request_id, item_id, tool, target, reason, options}` ;
2. **met le run en pause** (`await` sur un `asyncio.Event`/`Future` par `request_id`) ;
3. à réception de la décision (`hub.resolve_permission(request_id, choice, actor)`), reprend :
   - autorisé → exécute l'outil et continue le tour ;
   - refusé → injecte `Denied: <reason>` comme `tool_result` et continue.

`timeout` (configurable, ex. 120 s) → **deny** par défaut (équivalent du EOF→deny d'origine).

### 9.4 Carte de permission (UI, façon Claude Code)

Rendue dans le chat (réutilise le patron `WorktreeProposed` de `views.py`) + **glow** sur la `ChatNode`
du canvas. Boutons :

| Bouton | Effet | Persistance |
|---|---|---|
| Autoriser une fois | exécute ce seul appel | aucune |
| Autoriser dans cette session | ne redemande plus ce motif dans la session | RAM (couche session) |
| Autoriser dans ce projet | ne redemande plus pour ce projet | `.mekicode/permissions/<project_id>.yaml` |
| Refuser | bloque cet appel | aucune |
| Refuser et ne plus demander | bloque + blacklist le motif | → `always_deny` (couche projet) |

**Qui tranche** : l'**auteur du run** ou un **admin** (`MEKICODE_ADMIN_USER_ID`). Les autres voient la
carte en lecture seule.

### 9.5 Event

```python
@dataclass
class PermissionRequested:
    request_id: str
    item_id: str          # le run/queue item concerné
    tool: str
    target: str           # 1re valeur d'input (commande bash, chemin, …), tronquée
    reason: str
    options: list[str]    # ["once","session","project","deny","blacklist"]
    actor_id: str | None  # auteur autorisé à trancher (None = admin requis)
```

## 10. Multi-user & file d'attente (périmètre Sprint 1)

On **réutilise mekihub** tel quel : `PendingQueue` (FIFO) + présence **par session** + broadcast pub/sub.
- La `QueueNode`/`QueueComponent` **rend** la file (items multi-auteurs, couleurs) — alimentée par les
  events `QueueEnqueued`/`QueueItemDeleted`/`RunStarted` déjà émis par le hub.
- Le canvas **reflète la session sélectionnée** (en Mix, la session focus).
- La **sync canvas multi-clients** (positions de nodes partagées, curseurs) est **reportée au Sprint 3** :
  en Sprint 1 le layout est déterministe et identique pour tous, donc rien à synchroniser.

## 11. Réutilisation de mekistudio (provenance & licence)

Vendoré depuis `C:\mekistudio\mekistudio\frontend\static\js\` (projet **MIT**, voir `pyproject.toml`) :
- `cables.js` — routage métro 45°, lanes/rubans anti-overlap, évitement d'obstacles (pur, testé hors DOM) ;
- `collision.js` — tests segment-AABB / free-spot (dépendance de `cables.js`).

Porté/adapté (pas copié verbatim) : `impulse_for` (depuis `chat-impulses.js` `impulseFor`),
le squelette `canvas.js` (pan/zoom/SVG/comètes) réécrit pour être piloté **côté serveur NiceGUI** (et non
par un WebSocket d'events Claude). Les nodes/components mekistudio (Python, couplés au Claude SDK) sont
**ré-implémentés** en NiceGUI, pas réutilisés.

## 12. Modèle de données & events (récap)

- **Hooks** (`mekicore`) : `pre_tool{tool,input}` (vetoable), `post_tool{tool,input,output}`.
- **Impulse intent** (canvas) : `{kind:'comet'|'glow', target:{by:'kind'|'session'|'file', value}, level:'strong'|'soft'|'error', fallback?}`.
- **Permissions** : `Decision = ALLOW | DENY(reason) | ASK(reason)` ; event `PermissionRequested` (§9.5) ;
  surcharges projet `.mekicode/permissions/<project_id>.yaml` (mêmes 3 tiers que `config.yaml`).

## 13. Tests & vérification (réseau-free, sans clé API)

- **Géométrie JS pure** : `node --test` sur `cables.js`/`collision.js` (suites amont adaptées).
- **Python** : `python -m py_compile` sur tout fichier modifié ; smoke `tests/smoke_packages.py` étendu :
  - HookBus : abonnement, ordre, **veto** ;
  - permissions : 3 tiers + court-circuit + **résolution en couches** (session > projet > global) ;
  - registry/parenting : dérivation du parent, câbles déduits ;
  - flux *ask* : `pre_tool ASK → PermissionRequested → resolve → reprise` (pause/await mockée, sans réseau).
- **Front** : `tests/smoke_mekistudio.py` (remplace `smoke_mekichat.py`) — import du package, montage des
  3 modes, rendu d'une ChatNode + QueueNode sans serveur live.
- Vérif visuelle du front (captures Playwright analysées, pas un simple HTTP 200) avant de rapporter.
- **Validation humaine finale** : l'utilisateur valide à la main après ces vérifs.

## 14. Hors périmètre (reporté)

ExplorerNode / EditorNode / preview / FolderNode / SubcanvasNode (Sprint 2) ; présence et sync canvas
multi-clients, TerminalNode, GitNode (Sprint 3) ; multi-canvas, worktrees=subcanvas, `ask_user` agent,
palette de nodes (Sprint 4) ; layout radial organique (`zonelayout.js`) ; éditeurs éphémères.

## 15. Risques & points ouverts

- **Bridge NiceGUI ↔ canvas JS** = la partie la plus risquée : pousser des nodes NiceGUI dans un `world`
  transformé + lire leurs rects côté JS pour les câbles. *Mitigation* : Sprint 1 limité à 3 nodes,
  placement déterministe, géométrie réutilisée.
- **Pause/reprise du worker sur *ask*** : s'assurer que le `await` sur la décision ne bloque pas les
  autres sessions (le worker est **par session** dans mekihub, donc OK), et gérer le `timeout`.
- **Déplacement de `packages/mekichat/` → `packages/mekistudio/mekichat/`** : casse les imports et les
  entrées (`start-chat.ps1`, `tests/smoke_mekichat.py`, CLAUDE.md, docs). À traiter proprement dans le plan.
- **Naming** : `mekistudio` (notre package front) ≠ `C:\mekistudio` (source d'étude) — homonymie assumée.
```
