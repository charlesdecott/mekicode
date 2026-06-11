---
title: "s07 · Skill Loading"
session: 07
phase: "Fondamentaux"
fichier: "inspiration/learn-claude-code/s07_skill_loading/code.py"
lignes: 427
tags: [skills, chargement-a-la-demande, frontmatter, system-prompt]
prev: "s06-subagent"
next: "s08-context-compact"
---

# s07 · Skill Loading

> **En une phrase** : injection de connaissances en deux niveaux — un catalogue bon marché (noms + descriptions) dans le prompt système au démarrage, le contenu complet d'un skill chargé à la demande via `load_skill` en tool_result.

## Rôle dans le harness

Le README pose le problème avec un anti-exemple : un projet a une spec de composants React, un guide de style SQL, un doc de design d'API. L'idée naïve — tout concaténer dans le prompt système — donne 6 500 lignes que l'agent transporte **à chaque appel LLM**, qu'il change une couleur CSS ou corrige une requête SQL. « 99 % du contenu est sans rapport avec la tâche courante, des tokens brûlés pour rien. »

La solution suit le principe *« Load when needed, don't stuff the prompt »* avec un design à deux niveaux. **Niveau 1 (bon marché, toujours présent)** : au démarrage, `_scan_skills()` parcourt le dossier `skills/`, lit le frontmatter YAML de chaque `SKILL.md` et construit `SKILL_REGISTRY` ; `build_system()` injecte le catalogue (≈100 tokens par skill) dans le prompt système. **Niveau 2 (coûteux, à la demande)** : quand l'agent juge qu'il a besoin du détail, il appelle `load_skill("code-review")` et reçoit le `SKILL.md` complet (≈2000 tokens) **en tool_result** — donc dans l'historique de messages, pas dans le prompt système.

Cette distinction est la clé de voûte : le contenu du skill voyage ensuite avec l'historique jusqu'à compaction, troncature ou fin de session — ce qui prépare directement [[s08-context-compact]] : le chargement à la demande résout « ne pas transporter ce qu'on ne devrait pas », la compaction résoudra « comment lâcher ce qu'on devrait ».

Dans le vrai Claude Code (détail du README) : les skills viennent de sources multiples (user `~/.claude/skills/`, projet `.claude/skills/`, bundled, plugins, MCP), le frontmatter compte bien plus de champs (`when_to_use`, `allowed-tools`, `context: inline|fork`, `model`, `paths`…), le catalogue est budgété à ~1 % de la fenêtre de contexte (plafond 8 000 caractères), et l'outil s'appelle `Skill` avec les champs `skill` + `args`. La version pédagogique réduit tout cela à un dossier, deux champs et un paramètre `name`.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–27 | Docstring | Schéma des deux niveaux, changements vs s06 |
| 29–44 | Imports & env | + `yaml` (nouvelle dépendance pyyaml) |
| 46–50 | Globals | + `SKILLS_DIR = WORKDIR / "skills"` |
| 52–109 | **NOUVEAU s07** | `_parse_frontmatter`, `SKILL_REGISTRY`, `_scan_skills`, `list_skills`, `build_system`, `SYSTEM`, `SUB_SYSTEM` |
| 112–207 | Outils s02–s06 | `safe_path` … `run_todo_write`, `extract_text` |
| 210–262 | Subagent s06 | `SUB_TOOLS`, `SUB_HANDLERS`, `spawn_subagent` |
| 265–274 | **NOUVEAU s07** | `load_skill` |
| 277–305 | Registre d'outils | `TOOLS` (8 outils), `TOOL_HANDLERS` |
| 308–352 | Hooks s04 | registre, 4 hooks, enregistrements |
| 355–405 | Boucle | `rounds_since_todo`, `agent_loop` |
| 408–426 | `__main__` | REPL |

## Constantes et configuration

- `SKILLS_DIR = WORKDIR / "skills"` (ligne 47) — **nouveau** : la racine des skills, un sous-dossier par skill, chacun avec son `SKILL.md`.
- `SKILL_REGISTRY: dict[str, dict] = {}` (ligne 67) — **nouveau** : registre `{nom: {name, description, content}}` peuplé une fois au démarrage. C'est lui (et non le système de fichiers) que `load_skill` interroge — d'où l'absence de risque de path traversal.
- `SYSTEM = build_system()` (ligne 102) — le prompt système n'est plus une chaîne littérale : il est **construit** au démarrage avec le catalogue. Préfiguration de [[s10-system-prompt]].
- `SUB_SYSTEM` (lignes 105–109) — inchangé vs s06 ; le commentaire ligne 104 précise : pas de chargement de skill, pas de `task` pour le sous-agent.
- `TOOLS` (lignes 281–299) — désormais défini **statiquement** avec les 8 outils, y compris `task` et `load_skill` (plus de `TOOLS.append` comme en s06).
- `HOOKS` (312), `DENY_LIST` (324), `rounds_since_todo` (359) — repris de [[s04-hooks]] / [[s05-todo-write]].

## Les fonctions, une à une

### `_parse_frontmatter(text)` — lignes 53–64
**Nouvelle** : découpe un `SKILL.md` en `(meta, body)`.

```python
def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from SKILL.md. Returns (meta, body)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, parts[2].strip()
```

- Lignes 55–56 : pas de `---` initial → pas de frontmatter, tout est corps.
- Ligne 57 : `split("---", 2)` produit `["", "<yaml>", "<body>"]` — le `maxsplit=2` protège les `---` éventuels dans le corps.
- Lignes 60–63 : parsing YAML tolérant — un YAML invalide donne `meta = {}` au lieu de faire planter le scan. Le `or {}` couvre le cas d'un frontmatter vide (`yaml.safe_load("")` renvoie `None`). Subtilité : si le YAML est valide mais n'est **pas un mapping** (p. ex. une simple chaîne), `meta` n'est pas un dict et le `meta.get(...)` de `_scan_skills` lèverait `AttributeError` — cas limite non couvert.

### `_scan_skills()` — lignes 69–84
**Nouvelle** : remplit `SKILL_REGISTRY` au démarrage (appel ligne 84, au moment de l'import).

```python
def _scan_skills():
    """Scan skills/ dir, populate SKILL_REGISTRY with name/description/content."""
    if not SKILLS_DIR.exists():
        return
    for d in sorted(SKILLS_DIR.iterdir()):
        if not d.is_dir():
            continue
        manifest = d / "SKILL.md"
        if manifest.exists():
            raw = manifest.read_text()
            meta, body = _parse_frontmatter(raw)
            name = meta.get("name", d.name)
            desc = meta.get("description", raw.split("\n")[0].lstrip("#").strip())
            SKILL_REGISTRY[name] = {"name": name, "description": desc, "content": raw}
```

- Ligne 71–72 : pas de dossier `skills/` → registre vide, l'agent fonctionne sans skills (et `list_skills` renverra `"(no skills found)"`).
- Ligne 73 : `sorted(...)` garantit un ordre de catalogue déterministe — important pour la stabilité du prompt système (et donc du prompt caching côté API).
- Lignes 80–81 : doubles valeurs de repli — sans champ `name`, le nom du dossier ; sans `description`, la première ligne du fichier débarrassée de ses `#` (titre markdown).
- Ligne 82 : on stocke `raw` (le fichier **entier**, frontmatter compris) comme `content` — c'est ce que `load_skill` renverra ; `body` est calculé mais inutilisé.

### `list_skills()` — lignes 86–90
**Nouvelle** : formate le catalogue en liste markdown `- **nom**: description`, une ligne par skill — la matérialisation du « niveau 1 » à ~100 tokens par skill.

### `build_system()` — lignes 93–102
**Nouvelle** : assemble le prompt système avec le catalogue.

```python
def build_system() -> str:
    """Build SYSTEM prompt with skill catalog injected at startup."""
    catalog = list_skills()
    return (
        f"You are a coding agent at {WORKDIR}. "
        f"Skills available:\n{catalog}\n"
        "Use load_skill to get full details when needed."
    )

SYSTEM = build_system()
```

L'agent voit donc **à chaque tour** quels skills existent, sans aucun appel API supplémentaire, et la dernière phrase lui indique le mécanisme de chargement. `SYSTEM` est figé à l'import (ligne 102) : ajouter un skill exige un redémarrage.

### `safe_path(p)` — lignes 116–119
### `run_bash(command)` — lignes 122–129
### `run_read(path, limit=None)` — lignes 131–138
### `run_write(path, content)` — lignes 140–147
### `run_edit(path, old_text, new_text)` — lignes 149–158
### `run_glob(pattern)` — lignes 160–169
### `_normalize_todos(todos)` — lignes 171–189
### `run_todo_write(todos)` — lignes 191–202
Tous repris de [[s02-tool-use]] / [[s05-todo-write]] sans modification.

### `extract_text(content)` — lignes 204–207
Reprise de [[s06-subagent]] sans modification (la docstring d'une ligne a disparu, le code est identique). Notez son déplacement : elle vit maintenant dans la zone « outils » plutôt que dans la zone subagent.

### `spawn_subagent(description)` — lignes 229–262
Reprise de [[s06-subagent]] sans modification de logique : messages frais, 30 tours max, hooks appliqués, repli arrière si la limite tombe en plein `tool_use`. Seule la mise en forme a été compactée (appel API sur 2 lignes au lieu de 4) et les commentaires `Issue 1`/`Issue 5` ont été retirés. `SUB_TOOLS` (214–225) et `SUB_HANDLERS` (226–227) sont identiques à s06.

### `load_skill(name)` — lignes 269–274
**La** nouveauté côté exécution — quatre lignes qui matérialisent le « niveau 2 ».

```python
def load_skill(name: str) -> str:
    """Load full skill content. Lookup via registry — no path traversal."""
    skill = SKILL_REGISTRY.get(name)
    if not skill:
        return f"Skill not found: {name}"
    return skill["content"]
```

- Ligne 271 : la recherche se fait **dans le registre**, jamais sur le disque. Le modèle ne peut pas demander `load_skill("../../etc/passwd")` : si la clé n'existe pas dans le dict, c'est `Skill not found`. Comparer avec `safe_path` qui doit, lui, normaliser et vérifier de vrais chemins.
- Ligne 274 : le contenu renvoyé devient un `tool_result` dans `messages` — il sera transporté par l'historique à chaque tour suivant, jusqu'à ce qu'une compaction ([[s08-context-compact]]) le remplace par un placeholder.

### `TOOLS` et `TOOL_HANDLERS` — lignes 281–305
Le registre passe à 8 outils. La déclaration de `load_skill` (lignes 297–298) est minimale :

```python
    # s07: skill tool (catalog is already in SYSTEM prompt, this loads full content)
    {"name": "load_skill", "description": "Load the full content of a skill by name.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
```

Le commentaire résume l'architecture : le catalogue est déjà dans `SYSTEM`, l'outil ne sert qu'au contenu complet. Comme pour `task` en s06, **la boucle ne change pas** : `load_skill` se dispatch via `TOOL_HANDLERS[block.name]` (ligne 304).

### `register_hook(event, callback)` — lignes 314–315
### `trigger_hooks(event, *args)` — lignes 317–322
### `permission_hook(block)` — lignes 326–332
### `log_hook(block)` — lignes 334–336
### `context_inject_hook(query)` — lignes 338–340
### `summary_hook(messages)` — lignes 342–347
Système de hooks repris de [[s04-hooks]] sans modification (registre ligne 312, enregistrements lignes 349–352). Les docstrings d'une ligne ont été retirées.

### `agent_loop(messages)` — lignes 361–405
Reprise de [[s05-todo-write]]/[[s06-subagent]] sans modification : nag reminder, hooks `Stop`, dispatch générique.

### Bloc `__main__` — lignes 408–426
REPL identique à s06, bannière mise à jour : `"s07: Skill Loading — catalog in SYSTEM, content on demand"`.

## Ce qui change par rapport à [[s06-subagent]]

- **Nouveau** : import `yaml` (ligne 31) — dépendance pyyaml ajoutée (cf. docstring ligne 26).
- **Nouveau** : `SKILLS_DIR` (47), `_parse_frontmatter()` (53–64), `SKILL_REGISTRY` (67), `_scan_skills()` (69–84, exécutée à l'import ligne 84), `list_skills()` (86–90).
- **Nouveau** : `build_system()` (93–102) — le prompt système devient une valeur construite ; `SYSTEM = build_system()`.
- **Nouveau** : `load_skill()` (269–274) et son entrée dans `TOOLS`/`TOOL_HANDLERS` — 7 outils deviennent 8.
- **Modifié (forme seulement)** : `TOOLS` redevient une liste statique incluant `task` (en s06, `task` était ajouté par `TOOLS.append`).
- **Inchangé** : outils s02–s05, subagent s06, hooks s04, `agent_loop`, REPL.

## Pièges et détails d'implémentation

- **Tool_result, pas prompt système** : le contenu du skill chargé entre dans `messages` comme résultat d'outil. Il est donc soumis aux mécanismes d'historique (compaction en [[s08-context-compact]]) — alors que le catalogue, lui, est rejoué à chaque appel via `SYSTEM`.
- **Le registre fige tout au démarrage** : `content` est lu une seule fois par `_scan_skills()`. Modifier un `SKILL.md` en cours de session n'a aucun effet sur `load_skill` — le disque n'est jamais relu.
- **Anti-traversal par construction** : la sécurité ne vient pas d'une validation de chemin mais du fait que `load_skill` ne manipule pas de chemins du tout — un simple `dict.get`.
- **Replis de métadonnées** : sans frontmatter, le skill existe quand même (nom = dossier, description = première ligne sans `#`). Un frontmatter YAML scalaire (non-mapping) ferait en revanche planter `_scan_skills` à l'import (`meta.get` sur une chaîne).
- **Les sous-agents n'ont pas de skills** : ni `load_skill` dans `SUB_TOOLS`, ni catalogue dans `SUB_SYSTEM`. Un sous-agent chargé d'une tâche « skillée » devra recevoir les instructions dans sa `description`.
- **Collision de noms silencieuse** : deux dossiers déclarant le même `name:` en frontmatter — le dernier scanné (ordre alphabétique) écrase le premier dans `SKILL_REGISTRY`.

## Liens

- Session précédente : [[s06-subagent]]
- Session suivante : [[s08-context-compact]]
- Sessions liées : [[s10-system-prompt]] (assemblage du prompt système généralisé), [[s09-memory]] (même motif registre + frontmatter pour la mémoire), [[s19-mcp-plugin]] (skills distribués via plugins/MCP)
