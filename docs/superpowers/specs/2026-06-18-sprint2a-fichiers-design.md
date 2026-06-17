# Design — Sprint 2a : Explorateur + Éditeur + spawn auto sur lecture

> Validé au brainstorming le 2026-06-18 (suite du Sprint 1). Cible : `packages/mekistudio/mekicanvas/`
> (+ helpers fs). Approche **A** : 100 % NiceGUI côté serveur (`ui.tree` + `ui.codemirror` natifs,
> NiceGUI 3.13), piloté par nos outils/hooks ; aucune route REST, aucun éditeur JS vendoré.

## 0. Contexte / réutilisation

Déjà en place (Sprint 1) : canvas NiceGUI (drag/resize/focus), modèle Node/Component, `parenting.py`
(`longest_prefix_id`/`is_prefix`), `impulses.py` (`impulse_for` renvoie déjà une comète → fichier sur
`read`/`grep`/`glob`), `canvas.js` (`pulseTo`/`pathBetween`/`redraw`/glow), outils fichiers de mekicore
sandboxés au workspace. Sprint 2a ajoute la **matérialisation des fichiers** sur le canvas.

## 1. Topologie

Chaque node **folder (workspace)** (repo main / worktree) gagne un enfant **`ExplorerNode`** = l'arbre
fichiers de ce workspace (sandboxé à son chemin). Les **`EditorNode`** se parentent à l'explorateur de
leur workspace. *(En 2b : nodes `dir` par préfixe de chemin entre explorateur et éditeurs.)*

⚠️ Naming : notre node **`folder`** = *espace de travail* ; les dossiers FS s'appelleront **`dir`**
(réservé 2b). En 2a, pas de node `dir`.

## 2. Helpers fs — `mekicanvas/fs.py` (purs, sandboxés)

- `safe_path(root, rel) -> Path` : résout `rel` sous `root`, **rejette** `..`/absolu/hors-root.
- `list_dir(root, rel="", excludes=(…)) -> list[dict]` : `{name, kind: 'dir'|'file', path}`, dossiers
  d'abord puis fichiers (alpha), exclusions (`__pycache__`, `.git`, `.venv`, …).
- `read_text(root, rel) -> str` : UTF-8, **≤ 1 Mo**, refuse le binaire.
- `write_text(root, rel, content)` : écriture **atomique** (tmp UUID + `replace`).

## 3. `ExplorerNode`

Node `kind="explorer"` ; corps = arbre lazy construit avec `ui.expansion` (dossiers, enfants chargés au
1er expand via `list_dir`) + lignes fichiers. **Double-clic fichier → ouvre un éditeur épinglé** (non
éphémère). Un explorateur par workspace, sandboxé à son chemin. Exclusions par défaut.

## 4. `EditorNode`

Node `kind="editor"` ; barre (nom · point "modifié" · 💾 sauver · ✕ fermer) + `ui.codemirror`
(coloration par extension : py/js/ts/json/md/css/html/…). Contenu via `read_text` ; **Ctrl+S / bouton**
→ `write_text` ; fermer = supprime la node. `path` (posix relatif) stocké sur le Node (clé de dédup +
parentage). Pas de live-sync en 2a.

## 5. Spawn auto sur lecture (la « magie »)

Le canvas ouvre un **abonnement par session affichée** (`hub.subscribe`). Sur un `ToolFinished` de
`read`/`grep`/`glob` portant un chemin (extrait des args via la table `id→args` de `ToolStarted`, comme
en Sprint 1), `impulse_for` produit l'intent comète→fichier. Côté serveur :
1. normaliser le chemin (relatif posix au workspace de la session) ;
2. si un `EditorNode` est déjà ouvert pour ce fichier → ré-cibler (comète + réarmer TTL) ;
3. sinon **spawn un `EditorNode` éphémère** (TTL ~10 min, **épinglable d'un clic**) sous l'explorateur du
   workspace, ajouté dynamiquement au `.mc-world`, puis `redraw()` + **comète** de la node chat de cette
   session → l'éditeur (`MekiCanvas.impulse`/`pulseTo`). Dédup par (workspace, chemin).
- TTL simple (les 3 modes capped/unlimited de mekistudio = différés). Purge des éphémères expirés.

## 6. Intégration canvas_page

`render_canvas` expose le conteneur `.mc-world` + un `spawn_editor(workspace, rel, from_chat_id,
ephemeral)`. Registre `{(workspace, path): node_id}` pour la dédup. Les abonnements par session sont
lancés via `ui.timer(once=True)`. Le workspace d'une session = `workspace_for(session, registry)`
(main = repo projet ; worktree = dossier worktree).

## 7. Tests (réseau-free)

- `tests/smoke_mekicanvas_fs.py` : `fs.py` — `list_dir` (tri, exclusions), `read_text` (limite/binaire),
  `write_text` (atomique, round-trip), `safe_path` **rejette** `..`/absolu/hors-root.
- `impulse_for` : déjà couvert (`smoke_mekicanvas`).
- Spawn : test du flux `event → impulse_for → décision spawn/recible` sans navigateur (mock du registre).
- **Vérif visuelle Playwright** (obligatoire) : explorateur déplié, double-clic → éditeur (codemirror),
  édition + save, et **comète + éditeur éphémère qui apparaît quand l'agent lit un fichier**
  (via `MEKICHAT_FAKE_TOOL` adapté à un `read`).

## 8. Hors périmètre 2a (→ 2b/2c)

Nodes `dir` (chaîne de dossiers, mode compact), subcanvas conteneur, 3 modes TTL (capped/unlimited),
preview markdown, diff vs HEAD, live-sync de l'éditeur sur édition par l'agent.
