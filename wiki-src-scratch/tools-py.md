---
title: "tools.py · Outils & registre"
phase: "Fondations"
fichier: "src_scratch/tools.py"
lignes: 272
tags: [tool-use, dispatch, registre, background, revert, snapshots]
---

# tools.py · Outils & registre

> **En une phrase** : les six outils natifs (bash, read, write, grep, glob, revert) en double exemplaire sync/async, le registre `register_tool` qui maintient les trois structures (`TOOLS`, `DISPATCH`, `ASYNC_DISPATCH`) cohérentes, et l'exécution en arrière-plan avec notifications.

## Rôle dans le harness

La source définissait ses outils deux fois (`BASIC_TOOLS` pédagogiques puis `EXTENDED_TOOLS` de s14) et son dispatch trois fois (sync, async, et des variantes par session). Ici, **une seule palette** : les six outils de `EXTENDED_TOOLS` (s02 pour le principe du dispatch, s14 pour write-avec-snapshot et revert), chacun en version synchrone et asynchrone. `BASIC_TOOLS`/`BASIC_DISPATCH` sont abandonnés — c'était un sous-ensemble pédagogique. S'y ajoutent le registre dynamique `register_tool` (notre généralisation du « add a tool, add just one handler » de la source) et l'exécution en arrière-plan de s08.

La convention du module, posée dès la docstring : **un handler de dispatch reçoit le dict `input` complet et renvoie une `str`**. C'est ce contrat unique qui permet à [[loop-py]] d'exécuter indifféremment un outil natif, un outil de [[tasks-py]] ou un outil MCP de [[mcp-runtime-py]] — tous enregistrés par la même porte.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–6 | Docstring | Contenu + contrat des handlers (input dict → str) |
| 7–16 | Imports | stdlib + `paint` depuis [[core-py]] |
| 18–22 | État module | `SNAPSHOTS` (s14), `_ALWAYS_BLOCK` |
| 25–114 | Implémentations sync | `run_bash`, `run_read`, `run_write`, `run_grep`, `run_glob`, `run_revert` |
| 117–155 | Wrappers async | `async_bash` natif + cinq `to_thread` |
| 158–202 | Schémas & dispatch | `TOOLS` (6 schémas), `DISPATCH`, `ASYNC_DISPATCH` |
| 205–221 | Registre | `register_tool` — la porte d'entrée des outils dynamiques |
| 224–262 | Arrière-plan (s08) | `NOTIFICATIONS`, `run_bash_background`, `drain_notifications` |
| 265–272 | Enregistrement | l'outil `bash_background` s'auto-enregistre à l'import |

## Constantes et configuration

- **`SNAPSHOTS` (ligne 19)** : `dict[str, Optional[str]]` chemin → contenu avant écriture ; `None` signifie « le fichier n'existait pas » (s14). En mémoire seulement : un seul niveau d'undo, perdu au redémarrage.
- **`_ALWAYS_BLOCK` (ligne 22)** : `["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/", ":(){ :|:& };:"]` — filet grossier testé **par sous-chaîne** ; la vraie politique est dans le `config.yaml` documenté sur [[core-py]].
- **`TOOLS` (lignes 160–184)** : les six schémas JSON annoncés au modèle (équivalent de `EXTENDED_TOOLS` source). Notez la description de `write` — *« Snapshots previous content automatically »* — qui annonce au modèle l'existence de `revert`.
- **`DISPATCH` / `ASYNC_DISPATCH` (lignes 186–193 / 195–202)** : nom → lambda qui déballe le dict input vers la signature de la fonction. **Mêmes six clés des deux côtés** — `revert` inclus (FIX, voir Bugs).
- **`NOTIFICATIONS` (ligne 226)** : `queue.Queue` thread-safe où les tâches de fond déposent leur résultat (s08).

## Les fonctions, une à une

### `run_bash(command)` — lignes 27–39

```python
    if any(b in command for b in _ALWAYS_BLOCK):
        return "Error: dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=os.getcwd(),
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
```

Le classique de s01/s02 : blocklist, timeout 120 s, stdout+stderr concaténés, cap 50 000 caractères, `"(no output)"` plutôt qu'une chaîne vide ambiguë. `cwd=os.getcwd()` est important pour [[worktree-py]] : le « chdir sandwich » des worktrees change le répertoire courant, et bash suit.

### `run_read(path, start_line=None, end_line=None)` — lignes 42–54

```python
        start = (start_line or 1) - 1
        end = end_line or len(lines)
        numbered = "".join(f"{start + 1 + i:4d}\t{line}" for i, line in enumerate(lines[start:end]))
        return numbered[:50000] or "(empty file)"
```

Différence notable avec le `read_file` de s02 (qui avait un simple `limit`) : tranche 1-indexée `start_line`/`end_line` et **numérotation absolue des lignes** (`start + 1 + i`) — le modèle peut citer « ligne 42 » de façon stable même en lisant un extrait. Encodage `utf-8/replace` : un fichier mal encodé donne des caractères de substitution, pas une exception.

### `run_write(path, content)` — lignes 57–72

```python
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                SNAPSHOTS[path] = f.read()
            action = "updated"
        else:
            SNAPSHOTS[path] = None
            action = "created"
```

Le cœur de s14 : **snapshot avant chaque écriture**. Fichier existant → son contenu est sauvé ; fichier neuf → `None` (le revert saura qu'il faut le supprimer). Puis `os.makedirs(..., exist_ok=True)` sur le parent (chemin absolutisé, ligne 67) et écriture. Le message de retour — `(snapshot saved — use revert to undo)` — enseigne au modèle que l'action est réversible.

### `run_grep(pattern, path=".", recursive=True)` — lignes 75–92

Stratégie à deux étages : `grep -n [-r]` système d'abord ; si le binaire n'existe pas (`FileNotFoundError`, cas Windows nu), repli `findstr /S /N` limité aux `*.py`, `*.js`, `*.md`. Timeout 30 s, sortie plafonnée à 10 000 caractères, `"(no matches)"` si vide. Le repli est volontairement rustique — les regex `findstr` ne sont pas celles de `grep`.

### `run_glob(pattern)` — lignes 95–98

```python
def run_glob(pattern: str) -> str:
    """Fichiers correspondant au motif glob (récursif), triés, cap 200 chemins."""
    matches = _glob.glob(pattern, recursive=True)
    return "\n".join(sorted(matches)[:200]) if matches else "(no matches)"
```

Quatre lignes : `recursive=True` active `**`, tri pour un ordre déterministe, cap 200 chemins. L'import `glob as _glob` (ligne 8) évite la collision avec le nom de l'outil.

### `run_revert(path)` — lignes 101–114

```python
    if path not in SNAPSHOTS:
        return f"Error: no snapshot for {path}"
    original = SNAPSHOTS.pop(path)
    try:
        if original is None:
            os.remove(path)
            return f"reverted: deleted {path} (it was a new file)"
```

- **`pop` (ligne 105)** : le snapshot est **consommé** — un second revert sur le même chemin renverra « no snapshot ». Undo à un niveau, pas une pile.
- **`None` → `os.remove`** : annuler la création d'un fichier, c'est le supprimer. C'est tout l'intérêt du `SNAPSHOTS[path] = None` posé par `run_write`.

### `async_bash(command)` — lignes 119–133

Le seul wrapper async **natif** : `asyncio.create_subprocess_shell` + `wait_for(proc.communicate(), timeout=120)` — le sous-processus ne bloque pas l'event loop, condition du `gather` parallèle de s18. La blocklist est dupliquée en tête (voir Pièges). Décodage par `.decode()` sur les bytes, mêmes caps et messages que la version sync.

### `async_read` / `async_write` / `async_grep` / `async_glob` — lignes 136–149

Quatre délégations identiques : `await asyncio.to_thread(run_xxx, …)`. Les I/O fichiers et le `subprocess.run` de grep partent dans le thread pool ; pas de réécriture async des implémentations.

### `async_revert(path)` — lignes 152–155

```python
async def async_revert(path: str) -> str:
    # FIX(mekicode): manquait à l'ASYNC_DISPATCH de la source — `revert` était
    # annoncé au modèle mais répondait "Unknown tool" dans les sessions async.
    return await asyncio.to_thread(run_revert, path)
```

Mécaniquement identique aux quatre précédents — il n'existe que parce que la source l'avait oublié (voir Bugs).

### `register_tool(schema, sync_fn=None, async_fn=None)` — lignes 205–221

La porte d'entrée de **tous** les outils dynamiques du harness ([[tasks-py]], [[context-py]], [[agents-py]], [[mcp-runtime-py]], et `bash_background` ci-dessous).

```python
    if async_fn is None:
        async_fn = lambda inp: asyncio.to_thread(sync_fn, inp)  # noqa: E731
    if sync_fn is None:
        sync_fn = lambda inp: asyncio.run(async_fn(inp))  # noqa: E731
    TOOLS[:] = [t for t in TOOLS if t["name"] != name] + [schema]
    DISPATCH[name] = sync_fn
    ASYNC_DISPATCH[name] = async_fn
```

- **Dérivation croisée (lignes 216–218)** : fournir une seule version suffit — l'async dérivée passe par `to_thread`, la sync dérivée par `asyncio.run`. Fournir au moins l'une des deux est obligatoire (`ValueError` sinon, ligne 214).
- **`TOOLS[:] = …` (ligne 219)** : le détail décisif du fichier. [[loop-py]] fait `from tools import TOOLS` — un alias vers **le même objet liste**. L'affectation par tranche mute la liste en place : tout module qui détient la référence voit instantanément le nouvel outil. Un `TOOLS = …` classique aurait rebindé le nom local sans rien propager. La compréhension filtre d'abord l'ancien schéma du même nom : ré-enregistrer un outil le **remplace** (idempotent — utile aux re-démarrages MCP).

### `run_bash_background(command)` — lignes 229–252

```python
    if any(b in command for b in _ALWAYS_BLOCK):
        return "Error: dangerous command blocked"
    bg_id = uuid.uuid4().hex[:6]

    def _worker():
        print(paint(f"  [bg {bg_id}] démarré : {command[:60]}", "dim"))
        ...
        NOTIFICATIONS.put(f"[bg {bg_id}] terminé: {out}")

    threading.Thread(target=_worker, daemon=True).start()
    return f"Background task [{bg_id}] started: ..."
```

Le pattern s08 : retour **immédiat** avec un id court (6 hex), exécution dans un thread daemon (timeout généreux de 300 s, sortie plafonnée à 2 000 caractères), résultat déposé dans `NOTIFICATIONS`. C'est [[loop-py]] qui ferme la boucle : `agent_loop_async` draine la file en tête de chaque tour et injecte `[notification] [bg xxxxxx] terminé: …` comme contenu user — le modèle apprend le résultat au tour suivant.

### `drain_notifications()` — lignes 255–262

Vidage non bloquant de la file : boucle `get_nowait()` jusqu'à `queue.Empty`, renvoie la liste (souvent vide). Appelée par [[loop-py]] à chaque tour.

### Auto-enregistrement de `bash_background` — lignes 265–272

À l'import du module, `register_tool` est appelé avec le schéma de `bash_background` et `sync_fn` seule — la version async est dérivée automatiquement. Démonstration par l'exemple du registre : l'outil n'apparaît ni dans le littéral `TOOLS` ni dans les littéraux de dispatch, et pourtant tout harness qui importe `tools` l'expose au modèle.

## Bugs de la source corrigés ici

- **`async_revert` ajouté (lignes 152–155, et clé `revert` de `ASYNC_DISPATCH` ligne 201)** — dans le core de la source, `revert` figurait dans `EXTENDED_TOOLS` (donc annoncé au modèle) mais pas dans `ASYNC_DISPATCH` : dans toutes les sessions async (s18, s22…), un appel à `revert` recevait « Unknown tool ». Les deux tables ont désormais exactement les mêmes six clés.
- **`run_bash_background` applique `_ALWAYS_BLOCK` (lignes 235–236)** — en s08, la version background n'avait pas la blocklist du bash synchrone : il suffisait de demander l'exécution « en arrière-plan » pour contourner le filet (`sudo …` refusé au premier plan, accepté en fond). Le même test ouvre désormais la fonction.

## Qui l'utilise

- [[loop-py]] — `TOOLS`, `DISPATCH`, `ASYNC_DISPATCH`, `drain_notifications` : la boucle consomme la palette et draine les notifications de fond.
- [[tasks-py]] — `register_tool` (todo_write, todo_read, task_add, task_list, task_complete).
- [[context-py]] — `register_tool` (load_skill).
- [[agents-py]] — `register_tool` (subagent, send_to_teammate, list_teammates).
- [[mcp-runtime-py]] — `register_tool` (chaque outil distant sous le nom `mcp__<srv>__<tool>`).

## Pièges et détails d'implémentation

- **`TOOLS[:] =` est porteur** : remplacer cette affectation par tranche par un rebinding (`TOOLS = …`) casserait silencieusement tout l'enregistrement dynamique — [[loop-py]] garderait l'ancienne liste. Même contrainte pour quiconque manipule `TOOLS` de l'extérieur.
- **La blocklist existe en trois exemplaires** : `run_bash` (ligne 29), `async_bash` (ligne 121), `run_bash_background` (ligne 235). Ajouter un motif à `_ALWAYS_BLOCK` suffit, mais ajouter un *nouveau point d'exécution* de commandes impose de penser au test — c'est précisément l'oubli qui a produit le bug s08.
- **Test par sous-chaîne, pas par regex** : `_ALWAYS_BLOCK` bloque `echo "sudo"` (faux positif) et laisse passer `rm -rf /home` (vrai négatif — seul `rm -rf /` exact est listé). C'est un filet, pas une politique : la gouvernance fine est dans le `config.yaml` de [[core-py]].
- **`SNAPSHOTS` n'a qu'un niveau** : deux `write` successifs sur le même chemin écrasent le snapshot du premier — `revert` ramène à l'état d'avant le *dernier* write, pas à l'origine. Et `run_revert` consomme le snapshot (`pop`).
- **La `sync_fn` dérivée par `asyncio.run`** (ligne 218) lèverait `RuntimeError` si on l'appelait depuis un event loop déjà actif. En pratique le dispatch sync n'est utilisé que hors contexte async (`agent_loop(parallel=False)`), mais ne pas appeler `DISPATCH[name]` d'un outil async-only depuis une coroutine.

## Liens

- Modules liés : [[core-py]] (`paint`, et la politique fine du config.yaml), [[loop-py]] (consomme les trois structures, draine `NOTIFICATIONS`), [[tasks-py]] / [[context-py]] / [[agents-py]] / [[mcp-runtime-py]] (clients de `register_tool`)
