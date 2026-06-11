---
title: "s02 · Tool use et dispatch"
session: 02
phase: "Fondamentaux"
fichier: "inspiration/learn-claude-code/s02_tool_use/code.py"
lignes: 191
tags: [tool-use, dispatch, safe-path, read, write, edit, glob]
prev: "s01-agent-loop"
next: "s03-permission"
---

# s02 · Tool use et dispatch

> **En une phrase** : la boucle de [[s01-agent-loop]] reste identique ; on passe de 1 à 5 outils grâce à une table de dispatch `TOOL_HANDLERS` — ajouter un outil ne coûte plus qu'une entrée de définition et une ligne de mapping.

## Rôle dans le harness

L'agent de s01 n'a que bash. Pour lire un fichier, il doit produire `cat chemin/fichier` ; pour écrire, `echo "..." > fichier.py` ; pour chercher, `find`. Le modèle pense « lire ce fichier » mais doit traduire cette intention en syntaxe shell : une couche de traduction qui gaspille des tokens et multiplie les erreurs (échappement, quotes, différences de plateformes). Le README le résume : *« An extra layer of translation that wastes tokens and invites errors. »*

La session apporte deux choses. D'abord **quatre outils spécialisés** (`read_file`, `write_file`, `edit_file`, `glob`) avec des schémas dédiés : le modèle exprime directement son intention. Ensuite, et c'est l'idée architecturale durable, **le dispatch par table** : au lieu d'appeler `run_bash` en dur dans la boucle, on cherche le handler dans un dict `TOOL_HANDLERS[block.name]`. La boucle ne connaît plus aucun outil ; elle devient un moteur générique. *« Add a tool, add just one handler »* — c'est le slogan de la session.

Dans le vrai Claude Code, chaque outil est un objet complet construit par `buildTool()` (schéma Zod, validation, permissions, exécution) et l'exécution est bien plus sophistiquée : `partitionToolCalls()` découpe les appels en lots consécutifs où les outils sûrs en concurrence (`isConcurrencySafe()`) tournent en parallèle, et `StreamingToolExecutor` démarre les outils pendant que le modèle génère encore. La version pédagogique exécute tout séquentiellement, dans l'ordre de `response.content` — clarté conceptuelle avant performance.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–14 | Docstring | Inventaire des ajouts vs s01 (4 outils, dispatch, `safe_path`) |
| 16–33 | Imports & env | Identique à s01 + `pathlib.Path` |
| 35–39 | Configuration | `WORKDIR`, client, `MODEL`, `SYSTEM` (« Use tools », au pluriel) |
| 46–59 | Repris de s01 | `run_bash()` (légèrement modifié : encodage UTF-8) |
| 66–114 | **Nouveau** | `safe_path()` + 4 outils fichiers : `run_read`, `run_write`, `run_edit`, `run_glob` |
| 121–132 | **Nouveau** | `TOOLS` : 5 définitions au lieu d'une |
| 138–141 | **Nouveau** | `TOOL_HANDLERS` : la table de dispatch |
| 150–170 | Boucle | `agent_loop()` : structure s01, exécution via dispatch |
| 173–190 | Point d'entrée | REPL identique à s01 (affichage final simplifié) |

## Constantes et configuration

- **`WORKDIR` (ligne 35)** : `Path.cwd()` capturé une fois au démarrage — la racine de l'espace de travail, référence de toutes les vérifications de chemins.
- **`SYSTEM` (ligne 39)** : passe de « Use bash to solve tasks » à « Use **tools** to solve tasks » — le prompt système suit l'élargissement de la palette.
- **`TOOLS` (lignes 121–132)** : cinq définitions JSON Schema. Notez les paramètres optionnels (`limit` de `read_file` n'est pas dans `required`) et la description d'`edit_file` : *« Replace exact text in a file once »* — le « once » est un contrat de comportement annoncé au modèle (une seule occurrence remplacée).
- **`TOOL_HANDLERS` (lignes 138–141)** : le pivot de la session.

```python
TOOL_HANDLERS = {
    "bash": run_bash, "read_file": run_read, "write_file": run_write,
    "edit_file": run_edit, "glob": run_glob,
}
```

Deux structures parallèles : `TOOLS` dit au *modèle* ce qui existe, `TOOL_HANDLERS` dit au *harness* quoi exécuter. Ajouter un outil = une entrée dans chacune. La boucle n'est jamais touchée.

## Les fonctions, une à une

### `run_bash(command)` — lignes 46–59

Repris de [[s01-agent-loop]] avec une modification discrète mais réelle : l'appel `subprocess.run` gagne `encoding="utf-8", errors="replace"` (ligne 53), ce qui rend le décodage de la sortie déterministe quel que soit l'encodage par défaut de la plateforme (important sous Windows, où le défaut est cp1252). La liste `dangerous`, le timeout de 120 s et la troncature à 50 000 caractères sont inchangés.

### `safe_path(p)` — lignes 66–70

Le garde-fou commun à tous les outils fichiers : empêche l'évasion hors de l'espace de travail.

```python
def safe_path(p: str) -> Path:
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path
```

- **Ligne 67** : `WORKDIR / p` — si `p` est relatif, il est ancré dans `WORKDIR` ; si `p` est absolu, l'opérateur `/` de `pathlib` *ignore* la partie gauche et garde le chemin absolu. Puis `.resolve()` normalise (résout les `..`, les liens symboliques).
- **Ligne 68** : `is_relative_to(WORKDIR)` vérifie que le chemin résolu est bien *sous* la racine. `../../etc/passwd` comme `/etc/passwd` sont rejetés.
- **Ligne 69** : contrairement aux outils, ce helper *lève* une exception — mais chaque outil l'attrape dans son `try/except` et la transforme en chaîne `"Error: ..."` pour le modèle. La division du travail est nette : `safe_path` signale, l'outil rapporte.

À noter : seul les outils fichiers passent par `safe_path`. **bash reste sans restriction de chemin** — c'est le trou que [[s03-permission]] vient boucher.

### `run_read(path, limit=None)` — lignes 73–80

```python
def run_read(path: str, limit: int | None = None) -> str:
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"
```

- **Ligne 76–77** : si `limit` est fourni *et* inférieur au nombre de lignes, on tronque et on ajoute un marqueur `... (N more lines)` — le modèle sait qu'il manque du contenu et combien, il peut décider de relire avec une limite plus grande.
- **Ligne 79** : `except Exception` attrape tout — fichier inexistant, problème d'encodage, `ValueError` de `safe_path` — et le renvoie comme texte. Même philosophie que s01 : une erreur d'outil est une donnée pour le modèle, jamais un crash du harness.

### `run_write(path, content)` — lignes 83–90

```python
def run_write(path: str, content: str) -> str:
    try:
        file_path = safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
```

- **Ligne 86** : `mkdir(parents=True, exist_ok=True)` crée les répertoires intermédiaires manquants — le modèle peut écrire `src/utils/helper.py` sans créer `src/` puis `src/utils/` au préalable. Petit confort qui économise des allers-retours de boucle.
- **Ligne 88** : le retour confirme l'action avec une mesure concrète (`len(content)` octets) — feedback vérifiable plutôt qu'un simple « OK ».
- Écrasement silencieux : si le fichier existe, il est remplacé sans avertissement (le vrai Claude Code, lui, exige d'avoir lu un fichier avant de l'écraser).

### `run_edit(path, old_text, new_text)` — lignes 93–102

```python
def run_edit(path: str, old_text: str, new_text: str) -> str:
    try:
        file_path = safe_path(path)
        text = file_path.read_text()
        if old_text not in text:
            return f"Error: text not found in {path}"
        file_path.write_text(text.replace(old_text, new_text, 1))
        return f"Edited {path}"
```

- **Lignes 97–98** : vérification d'existence du texte cible *avant* d'écrire — si `old_text` est introuvable, on renvoie une erreur explicite et le fichier n'est pas touché.
- **Ligne 99** : `text.replace(old_text, new_text, 1)` — le `1` final limite à **une seule occurrence** (la première), conformément au contrat « once » de la description. Pas de vérification d'unicité en revanche : si `old_text` apparaît trois fois, la première est remplacée sans prévenir (l'Edit du vrai CC exige l'unicité ou un `replace_all` explicite).
- Ce modèle « remplacement exact de chaîne » est exactement celui de l'outil Edit de Claude Code : il force le modèle à citer le code existant à l'identique, ce qui rend l'édition vérifiable.

### `run_glob(pattern)` — lignes 105–114

```python
def run_glob(pattern: str) -> str:
    import glob as g
    try:
        results = []
        for match in g.glob(pattern, root_dir=WORKDIR):
            if (WORKDIR / match).resolve().is_relative_to(WORKDIR):
                results.append(match)
        return "\n".join(results) if results else "(no matches)"
```

- **Ligne 106** : import local `import glob as g` — évite la collision avec le nom d'outil `glob` et n'importe le module que si l'outil est utilisé.
- **Ligne 109** : `root_dir=WORKDIR` ancre la recherche dans l'espace de travail (paramètre Python 3.10+).
- **Ligne 110** : re-vérification que chaque résultat reste sous `WORKDIR` — défense en profondeur contre les motifs contenant `..`.
- **Ligne 112** : `"(no matches)"` plutôt qu'une chaîne vide, pour la même raison que le `"(no output)"` de `run_bash` : ne jamais renvoyer du vide ambigu au modèle.

### `agent_loop(messages)` — lignes 150–170

Structurellement identique à [[s01-agent-loop]] — appel API, archivage du tour assistant, test `stop_reason`, collecte des `tool_result`, rétro-alimentation. **Une seule zone change**, l'exécution :

```python
        for block in response.content:
            if block.type == "tool_use":
                print(f"\033[33m> {block.name}\033[0m")
                handler = TOOL_HANDLERS.get(block.name)
                output = handler(**block.input) if handler else f"Unknown: {block.name}"
                print(str(output)[:200])
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": output})
```

- **Ligne 165** : `TOOL_HANDLERS.get(block.name)` — recherche dans la table au lieu d'un appel codé en dur. `.get()` (et non `[...]`) pour ne pas lever de `KeyError` si le modèle hallucine un nom d'outil.
- **Ligne 166** : `handler(**block.input)` — le dict d'arguments produit par le modèle est déballé directement en arguments nommés ; les signatures Python des handlers correspondent exactement aux propriétés des `input_schema`. Si le handler est inconnu : message `Unknown: ...` renvoyé au modèle, qui se corrigera. Risque assumé : si le modèle envoie un argument non prévu par la signature, le `**` lèverait un `TypeError` non attrapé — les schémas `required` rendent le cas rare en pratique.
- Les appels multiples d'un même tour sont exécutés **séquentiellement, dans l'ordre du contenu** — le vrai CC, lui, parallélise par lots les outils sûrs en concurrence (voir l'annexe du README, `toolOrchestration.ts:91-115`).

### Point d'entrée `if __name__ == "__main__"` — lignes 173–190

Repris de [[s01-agent-loop]] quasi à l'identique. Seule simplification : l'affichage final itère directement sur `history[-1]["content"]` (lignes 187–189) sans le garde `isinstance(..., list)` de s01 — le code suppose que le dernier message est toujours un tour assistant à contenu structuré, ce qui est vrai tant que `agent_loop` se termine normalement.

## Ce qui change par rapport à [[s01-agent-loop]]

- **+ `safe_path()`** (lignes 66–70) : validation d'ancrage des chemins dans `WORKDIR`.
- **+ 4 outils** : `run_read` (73–80), `run_write` (83–90), `run_edit` (93–102), `run_glob` (105–114).
- **`TOOLS` passe de 1 à 5 entrées** (lignes 121–132).
- **+ `TOOL_HANDLERS`** (lignes 138–141) : table nom → fonction.
- **`agent_loop` : une seule ligne de fond change** — `output = run_bash(block.input["command"])` devient `handler = TOOL_HANDLERS.get(block.name)` puis `handler(**block.input)`.
- **`run_bash` modifié** : ajout de `encoding="utf-8", errors="replace"`.
- **`SYSTEM`** : « Use bash » → « Use tools ».
- Le `while True` + `stop_reason`, l'archivage des messages et le format `tool_result` : inchangés au mot près.

## Pièges et détails d'implémentation

- **`safe_path` ne protège que les outils fichiers** : bash peut toujours écrire n'importe où (`echo x > /etc/...`). L'asymétrie est volontaire — elle motive [[s03-permission]].
- **`handler(**block.input)`** : le contrat implicite est que les noms de propriétés des schémas JSON et les noms de paramètres Python coïncident exactement. Renommer l'un sans l'autre casse silencieusement l'outil à l'exécution.
- **`(WORKDIR / p)` avec un chemin absolu** : l'opérateur `/` de `pathlib` *remplace* la base quand l'opérande droit est absolu — c'est précisément pour ça que le test `is_relative_to` est indispensable derrière.
- **`replace(..., 1)` sans contrôle d'unicité** : un `old_text` présent plusieurs fois modifie la première occurrence seulement, sans erreur — divergence subtile avec l'outil Edit du vrai CC.
- **L'ordre d'exécution = l'ordre de `response.content`** : le modèle compte souvent sur cet ordre (lire avant d'éditer). Tout passage à l'exécution parallèle doit respecter les dépendances — d'où l'algorithme de partition par lots consécutifs de CC.

## Liens

- Session précédente : [[s01-agent-loop]]
- Session suivante : [[s03-permission]]
- Sessions liées : [[s04-hooks]] (le dispatch s'enrichit de points d'extension), [[s05-todo-write]] (preuve par l'exemple : un 6e outil s'ajoute sans toucher la boucle), [[s12-task-system]] (outils à état persistant)
