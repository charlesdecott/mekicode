# `packages/mekistudio/` — front studio (NiceGUI, 3 modes)

Package **front** qui regroupe toute l'UI : le **chat** (composant réutilisable + page d'accueil
historique) et le **canvas** (nodes reliées par des câbles « métro » 45° à impulsions), assemblés par
une **coquille 3 modes** (Chat / Canvas / Mix). Intègre le canvas du projet d'étude `C:\mekistudio`,
mais piloté par **notre** harness (`mekicore` + `mekihub`) au lieu du Claude Code CLI.

> Issu du Sprint 1 (spec/plan : `docs/superpowers/specs|plans/2026-06-17-…mekistudio-canvas…`).
> La couche back/logique (`mekicore`, `mekillm`, `mekihub`) reste en **packages frères**, importée par
> ce package (jamais l'inverse). Numéros de ligne indicatifs (source = vérité).

## Carte des fichiers

```
packages/mekistudio/
├── app.py (n'existe pas — l'entrée est mekichat/app.py, voir ci-dessous)
├── shell.py            build_studio() : sélecteur 3 modes + scène ; ui.on('meki_focus') (pont JS→Python)
├── mekichat/           ── le chat (déplacé depuis packages/mekichat/) ──
│   ├── app.py          ENTRÉE NiceGUI (ui.run port 8080). Routes : "/" (accueil historique),
│   │                   "/studio" (coquille 3 modes), "/canvas" (canvas seul, temporaire).
│   │                   Singletons _get_hub/_get_store/_get_registry ; _llm_factory (LLM réel /
│   │                   MEKICHAT_FAKE_LLM / MEKICHAT_FAKE_TOOL).
│   ├── component.py    ChatComponent(container, hub, session_id, author) RÉUTILISABLE :
│   │                   fil + composer + file + présence + boucle d'abonnement + _render_hub_event
│   │                   (17 branches dont PermissionRequested) + send().
│   ├── views.py        render_message/_tool/_thread/_stream_bubble/_queue_item/_worktree_proposal
│   │                   + render_permission_request (carte s15, 5 choix).
│   ├── realtime.py     author_for_client() (identité éphémère par navigateur, app.storage)
│   ├── sessions.py     shim : ré-exporte mekihub.session
│   └── static/mekichat.css   thème cyberpunk Phosphore
└── mekicanvas/         ── le canvas ──
    ├── components/base.py   ComponentBase + union Component (Header/Layout/Node/Chat/Queue, pydantic)
    ├── model.py             Node (kind,x,y,w,h,source_id,…,root) + CanvasState
    ├── parenting.py         longest_prefix_id() (dérivation parent par préfixe-chemin, pur)
    ├── registry.py          NODE_BUILDERS, CANONICAL_PARENT_KIND, reconcile_source_links, default_canvas
    ├── nodes/               kernel.py / chat.py / queue.py (builders)
    ├── impulses.py          impulse_for() / impulse_from_hub_event() (event d'outil → intent, porté JS)
    ├── canvas_page.py        render_canvas() : kernel → folders (scopes) → chats groupés (NiceGUI)
    └── static/
        ├── js/cables.js,collision.js   géométrie PURE vendorée de mekistudio (MIT, node --test)
        ├── js/canvas.js                pont : pan/zoom + couche SVG câbles + comètes + drag/resize + clic-focus
        └── css/canvas.css              thème canvas (grille, nodes, folders, câbles, glow, resize-handle)
```

## La coquille 3 modes — `shell.py`

`build_studio(container, hub, store, author, *, make_session)` pose une barre (marque + 3 boutons de
mode + compteur de chats) et une **scène** :

| Mode | Contenu |
|------|---------|
| **Chat** | bouton qui **navigue vers `/`** (la page d'accueil mekicode historique, sidebar cyberpunk). |
| **Canvas** | `render_canvas` plein cadre : une node chat **par session**, groupées par espace de travail. |
| **Mix** | `ChatComponent` focus à gauche + `render_canvas` à droite. |

- **Clic sur une node chat** (en-tête, clic court) → `canvas.js` ajoute le highlight local **et** appelle
  `emitEvent('meki_focus', {session})`. Côté Python, `shell.py` enregistre `ui.on('meki_focus', …)` qui
  appelle `_focus(sid)` : mémorise la session focus (devient le chat de gauche au passage en Mix) et, si
  on est déjà en Mix, reconstruit **seulement** le panneau gauche (pas de reconstruction du canvas).
- Le mode est persisté dans `app.storage.user` (`'chat'` jamais persisté — c'est une navigation).

## Le chat réutilisable — `mekichat/component.py`

`ChatComponent` encapsule tout le chat live et s'instancie **à l'identique** dans l'onglet, dans la node
chat du canvas et dans le panneau focus du Mix (le même composant partout). `_render_hub_event` mappe les
events `mekihub` en mutations d'UI (Snapshot/Queue/Run/Message/AgentDelta/Done/Tool/RunError/Worktree*/
**PermissionRequested**/RunFinished/Idle). L'identité `author` est résolue **en amont** (contexte de page,
`realtime.author_for_client`) et injectée.

## Le canvas — `mekicanvas/`

- **Modèle** (`model.py`, `components/base.py`) : `Node` + arbre de `Component` (pydantic, union
  discriminée par `type`). Le parent (`source_id`) est **dérivé** (registry/parenting), pas stocké → les
  câbles en découlent.
- **Rendu** (`canvas_page.py`) : `render_canvas(container, hub, store, author, *, focus_sid, inject)`
  pose un `kernel`, un **folder par (projet, scope)** — `main` = repo de base (branche git affichée),
  autres = worktrees — et **une node chat par session** groupée sous son folder. Chaque node chat
  embarque un `ChatComponent`. IDs **stables** (`session_id` pour les chats, `folder:<projet>:<scope>`,
  `kernel`) → le drag/resize persiste par id.
- **Géométrie** (`static/js/cables.js`, `collision.js`) : vendorée verbatim de mekistudio (subway 45°,
  lanes/rubans anti-overlap, routage autour d'obstacles), **pure** et testée `node --test`.
- **Pont** (`static/js/canvas.js`, `window.MekiCanvas`) : `initWorld()` (pan/zoom, clamp [0.2, 4]),
  `redraw()` (lit les `.node-wrap` du DOM → géométrie → couche SVG `.cables`), `impulse(intent)` (comète /
  glow). Interactions : **en-tête** = clic court (focus) ou maintenu+bougé (déplacer) ; **coin bas-droite**
  (`.resize-handle`) = redimensionner ; **corps** = interaction chat ; **molette dans un chat** = scroll du
  fil, **molette ailleurs** = zoom. Position **et** taille persistées en `localStorage` (`meki:canvas:geo`).
- **Lecture au zoom** : au zoom-in, le contenu du chat est mis en page dans une zone plus large puis
  contre-scalé (`--mc-f = max(1, zoom)`, `.chat-scale`) → police écran ~constante mais **plus de texte par
  ligne** ; pas de scroll horizontal (wrap forcé).

## s15 — permissions (carte dans le chat)

Quand l'agent appelle un outil du tier *ask* (ex. `bash rm …`), `mekicore` met le run en pause et
`mekihub` émet `PermissionRequested`. `ChatComponent._render_hub_event` rend `views.render_permission_request`
(carte « ⚿ permission requise », 5 boutons : *autoriser une fois / session / projet*, *refuser*,
*refuser + ne plus demander*). Le clic appelle `hub.resolve_permission(request_id, choix, actor)` qui
applique la portée puis débloque le worker. *(Détail connu : en Mix, le chat est rendu 2× → 2 cartes ;
en résoudre une exécute l'action mais l'autre reste — à dédoublonner.)*

## Entrées & vérification

- **Lancement** : `python packages/mekistudio/mekichat/app.py` (ou `.\start-studio.ps1`) → `/` (accueil),
  **`/studio`** (3 modes), `/canvas` (canvas seul). `.\start-chat.ps1` lance le même serveur.
- **Tests réseau-free** : `tests/smoke_mekicanvas.py` (modèle/registry/parenting/impulses),
  `tests/smoke_mekichat.py` (sessions), géométrie `node --test …/static/js/*.test.js`. Vérification
  visuelle du front via Playwright (un HTTP 200 ne suffit pas).
