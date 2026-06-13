# Design — Outils étendus de l'agent (read / write / edit / grep / glob)

> Date : 2026-06-13 · Statut : **validé, prêt pour le plan d'implémentation**
> Axe : « Agent plus puissant » (s14). Brique suivante prévue : Permissions (s15).

## 1. Objectif

Faire de l'agent un **vrai agent de code** : à côté de `bash`, lui donner cinq outils de fichiers au
format function-calling OpenAI — **`read`, `write`, `edit`, `grep`, `glob`** — pour lire, créer,
**modifier chirurgicalement** (str-replace) et chercher dans les fichiers. Les outils de fichiers sont
**confinés à un workspace** (le projet, `cwd` par défaut) ; `bash` reste l'échappatoire non confinée.

## 2. Décisions (verrouillées)

| Sujet | Décision |
|-------|----------|
| Jeu d'outils | `read` + `write` + `edit` (str-replace) + `grep` + `glob`, en plus de `bash` |
| Édition | `edit` = remplacement d'un fragment **exact et unique** (le *workhorse*, moins d'erreurs que réécrire tout le fichier) |
| Sûreté | **Confinement** des outils de fichiers à une racine workspace ; `bash` inchangé (non confiné) |
| Racine workspace | **`cwd`** par défaut, surchargeable par `MEKICORE_WORKSPACE` (ex. `./workspace/`, déjà gitignoré, pour un bac à sable) |
| Implémentation | **Python pur**, aucune dépendance externe |
| Hors périmètre | `revert` (suivi des états originaux), gouvernance des permissions (brique s15), confirmation interactive |

## 3. Architecture

- **`packages/mekicore/tools.py`** (étendu) : les 5 fonctions + un helper partagé **`_safe_path`** ;
  ajout de leurs schémas dans `TOOLS` et de leurs handlers dans `DISPATCH`. **`run_agent` ne change
  pas** (il dispatche déjà par nom, de façon générique).
- **`packages/mekichat/views.py`** : `render_tool` **généralisé** — aujourd'hui figé sur « bash »,
  il affichera `▣ <NOM> :: <résumé>` pour n'importe quel outil.
- **`packages/mekichat/app.py`** : la branche `ToolStarted` de `_render_event` passe le **nom de
  l'outil** + un **résumé** (le 1er argument : commande / chemin / motif) au lieu de juste la commande.
- **`SYSTEM`** (prompt de `app.py`/`main.py`) : mentionner les outils de fichiers disponibles.

Principe : la boucle agent et les événements restent **agnostiques de l'outil** ; seuls `tools.py`
(les outils) et le rendu (`render_tool`) connaissent les détails.

## 4. Les cinq outils

Tous **renvoient une chaîne** (jamais d'exception qui remonte — comme `run_bash`) ; tout chemin passe
par `_safe_path` (cf. §5). Sortie tronquée (≈ 50k caractères) comme `bash`.

| Outil | Signature | Comportement |
|-------|-----------|--------------|
| `read` | `read(path)` | renvoie le contenu du fichier ; `Error: fichier introuvable` sinon. |
| `write` | `write(path, content)` | crée les dossiers parents puis écrit/écrase ; renvoie `écrit N caractères dans <path>`. |
| `edit` | `edit(path, old, new)` | remplace `old` par `new` **si `old` apparaît exactement une fois** ; sinon `Error: texte introuvable` ou `Error: texte ambigu (k occurrences) — ajoute du contexte`. |
| `grep` | `grep(pattern, path=".")` | cherche la **regex** `pattern` dans les fichiers texte sous `path` ; renvoie des lignes `relpath:lineno: contenu` (nb de résultats borné). Ignore binaires/illisibles sans crasher. |
| `glob` | `glob(pattern)` | liste les fichiers correspondant au motif (`**/*.py`, `src/*.ts`…) sous la racine, chemins relatifs, triés (liste bornée). |

Schémas `TOOLS` : une `function` par outil (nom, description orientée agent, `parameters` JSON Schema
avec les `required`). `DISPATCH` : `{"read": lambda a: read(a["path"]), ...}`.

## 5. Confinement (`_safe_path`)

```python
_WORKSPACE = Path(os.environ.get("MEKICORE_WORKSPACE") or os.getcwd()).resolve()

def _safe_path(p: str) -> Path:
    target = (_WORKSPACE / p).resolve()           # gère relatif ET absolu
    if target != _WORKSPACE and _WORKSPACE not in target.parents:
        raise ValueError(f"chemin hors du workspace : {p}")
    return target
```

- Résout `p` relativement à la racine ; un chemin **absolu hors racine** ou un `../` qui **s'échappe**
  → `ValueError`, attrapée par l'outil → message `Error: chemin hors du workspace : <p>` (pas de crash).
- `bash` n'utilise **pas** `_safe_path` (échappatoire assumée, inchangée).

## 6. Rendu front

- `views.render_tool(name, summary, output="", status="RUN")` : bloc générique `▣ <NOM> :: <résumé>`
  (même style cyberpunk que l'actuel `[bash]` : repliable, statut `DONE`/`ERR`, sortie mono). Le
  `summary` = la valeur du 1er argument de l'outil (commande / chemin / motif).
- `app.py` (`_render_event`, `ToolStarted`) : `views.render_tool(ev.name, _summary(ev.args))` où
  `_summary` prend la 1re valeur du dict d'arguments.
- `views.render_thread` (rejeu de l'historique) : même généralisation — afficher le nom de l'outil
  depuis `tool_calls[i].function.name` et le 1er argument, plus seulement « bash ».

## 7. Gestion d'erreurs

- Chemin hors workspace, fichier introuvable, `edit` ambigu/introuvable, regex invalide → **chaîne
  `Error: …`** renvoyée comme sortie d'outil (l'agent la voit et peut réagir). Aucune exception ne
  remonte hors d'un outil.

## 8. Tests (réseau-free, dans `tests/`)

`tests/smoke_packages.py` (étend la couverture `mekicore`) :
1. `_safe_path` : rejette `../../etc/passwd` et un chemin absolu hors racine ; accepte un chemin
   relatif normal (sur une racine temp via `MEKICORE_WORKSPACE`).
2. `write` puis `read` round-trip ; `write` crée les dossiers parents.
3. `edit` : remplace une occurrence unique ; `Error` si absente ; `Error` si ambiguë (2+).
4. `grep` : trouve une regex et renvoie `fichier:ligne`.
5. `glob` : liste les fichiers d'un motif.
6. `DISPATCH`/`TOOLS` : chaque outil est présent et routable.

## 9. Hors périmètre (YAGNI)

- `revert` (annuler les modifs — nécessite de suivre l'état original des fichiers).
- Gouvernance des permissions (confirmation, 3 niveaux) — **brique s15 séparée**.
- `read` avec plage de lignes / numéros de ligne ; `grep` multi-fichiers avancé (contexte, options).
  → ajoutables plus tard si besoin.
