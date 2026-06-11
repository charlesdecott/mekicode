---
title: "s05 · Skill Loading"
session: 05
phase: "Connaissance & contexte"
fichier: "inspiration/claude-code-from-scratch/s05_skill_loading.py"
lignes: 234
tags: [skills, lazy-loading, meta-tooling, system-prompt, contexte]
prev: "s04-subagent"
next: "s06-context-compact"
---

# s05 · Skill Loading

> **En une phrase** : un index léger des skills disponibles est injecté dans le prompt système, et deux méta-outils (`list_skills`, `load_skill`) permettent au modèle de charger le contenu complet d'un `SKILL.md` **à la demande** — des centaines de savoir-faire spécialisés deviennent accessibles sans gonfler le contexte.

## Rôle dans le harness

Le problème est le « context window bloat » : si on entasse chaque SOP, chaque guide de framework, chaque méthodologie dans le prompt système, on gaspille des tokens à chaque tour et on noie le modèle sous de l'information non pertinente. Le motto de la session le résume : *« Load knowledge when you need it, not upfront »*. C'est la première session de la phase « Knowledge & Context Management », dont le README donne le fil conducteur : *« loading domain knowledge on demand, compressing conversation history before it degrades reasoning quality, and persisting task state across restarts »* — s05 traite le premier volet.

La solution est un **meta-tooling** en deux niveaux. Niveau 1, la *découverte* : au démarrage, `discover_skills()` scanne `skills/` et construit un index « nom : description en une ligne » injecté dans le prompt système — quelques dizaines de tokens par skill. Niveau 2, le *chargement paresseux* : quand la tâche le justifie, le modèle appelle `load_skill(name)` et reçoit le `SKILL.md` complet comme `tool_result`. Le savoir entre dans le contexte uniquement quand il sert.

Le README donne l'analogue dans le vrai Claude Code : l'**Agent Skills system**. Même architecture de divulgation progressive : les métadonnées des skills (nom + description du frontmatter) sont toujours visibles dans le prompt système, le corps du `SKILL.md` n'est chargé que lors de l'invocation. Le dépôt livre trois skills d'exemple — `agent-builder` (patterns de harness engineering), `code-review` (méthodologie de revue en 5 étapes), `pdf` (arbre de décision des bibliothèques PDF). Le projet jumeau learn-claude-code traite le même mécanisme dans sa session 07 (skill loading), avec la même philosophie ; ici tout repose sur `stream_loop` de core.py au lieu d'une boucle locale.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–24 | Shebang & docstring | Motto, concepts (discovery, lazy loading, context efficiency), structure `skills/<nom>/SKILL.md` |
| 26–30 | Imports stdlib | `os`, `sys`, `Path`, typing |
| 32–37 | Imports core | `EXTENDED_TOOLS`, `EXTENDED_DISPATCH`, `stream_loop` |
| 39–43 | Configuration | `SKILLS_DIR` |
| 47–93 | **Nouveau** | `discover_skills()` : scan + extraction de descriptions |
| 96–133 | **Nouveau** | `run_list_skills()`, `run_load_skill()` : les deux méta-outils |
| 136–152 | **Nouveau** | Construction du prompt système dynamique (index injecté) |
| 154–187 | Schémas & dispatch | `SKILL_TOOLS`, `SKILL_DISPATCH` |
| 190–229 | REPL | `main()` |
| 232–234 | Point d'entrée | `if __name__ == "__main__"` |

## Constantes et configuration

- **`SKILLS_DIR` (ligne 43)** : `Path(__file__).parent.parent / "skills"` — attention, `parent.parent` remonte **au-dessus** du dépôt (voir Pièges).
- **`_initial_skills` / `_skill_index_str` (lignes 139–142)** : la découverte est exécutée **à l'import du module**, une seule fois ; l'index formaté retombe sur `"  (none currently installed)"` si aucun skill n'est trouvé.
- **`SYSTEM` (lignes 145–152)** : le prompt système assemblé dynamiquement :

```python
SYSTEM: str = (
    f"You are a coding agent at {os.getcwd()}.\n"
    "You have access to specialized 'Skills' (domain knowledge files). "
    "When a task requires specific knowledge (e.g., a specific framework, "
    "API, or language), call load_skill(name) to get full instructions. "
    "Do NOT guess or hallucinate details if a skill is available.\n\n"
    f"Available Skills Index:\n{_skill_index_str}"
)
```

Deux choses à noter : l'injonction *« Do NOT guess or hallucinate details if a skill is available »* — le prompt ne se contente pas de décrire l'outil, il impose un protocole (consulter avant d'improviser) ; et l'index en fin de prompt, seule partie variable — tout ce que le modèle sait des skills avant d'en charger un.

- **`SKILL_TOOLS` (lignes 157–180)** : `EXTENDED_TOOLS + [...]` — les 6 outils de base plus `list_skills` (schéma sans paramètre) et `load_skill` (un seul paramètre `name`, requis). La description de `load_skill` dit *quand* l'utiliser : *« Use this before starting a task requiring specialized domain knowledge »*.
- **`SKILL_DISPATCH` (lignes 183–187)** : `{**EXTENDED_DISPATCH, ...}` — héritage par étalement de dict, plus deux lambdas. Même mécanique d'extension que dans [[s02-tool-use]] : ajouter une capacité = une entrée de schéma + une entrée de dispatch, la boucle n'est jamais touchée.

## Les fonctions, une à une

### `discover_skills()` — lignes 47–93

Scanne `SKILLS_DIR` et produit le dict `{nom_de_skill: description_courte}`. Ne sont retenus que les sous-répertoires contenant un `SKILL.md` (test ligne 68). Le cœur est l'extraction de la description :

```python
                for line in lines:
                    stripped = line.strip()
                    # Toggle frontmatter state (skipping YAML headers)
                    if stripped == "---":
                        in_frontmatter = not in_frontmatter
                        continue
                    
                    # Ignore empty lines, headers (#), and frontmatter content
                    if not in_frontmatter and stripped and not stripped.startswith("#"):
                        description = stripped[:100]  # Cap length for prompt brevity
                        break
```

- **Lignes 79–81** : chaque `---` bascule l'état `in_frontmatter` — le bloc YAML d'en-tête est entièrement sauté.
- **Ligne 84** : on cherche la première ligne qui n'est ni vide, ni un titre `#`, ni du frontmatter — c'est elle qui devient la description, plafonnée à 100 caractères (ligne 85) pour garder l'index compact.
- Conséquence subtile : le champ `description:` du frontmatter YAML (présent dans les trois skills livrés) est **ignoré** — la description affichée est la première phrase du corps. Pour `agent-builder`, ce sera « Load this skill when the user wants to: », pas la riche description du YAML. Le vrai Claude Code, lui, lit précisément le frontmatter.
- **Lignes 89–91** : un skill illisible n'est pas masqué — son nom reste dans l'index avec `"Error reading metadata: ..."` comme description. La panne est visible plutôt que silencieuse.
- **Lignes 60–61** : si `SKILLS_DIR` n'existe pas, retour d'un dict vide sans erreur ; **ligne 64** : `sorted(...)` rend l'index déterministe.

### `run_list_skills()` — lignes 96–108

Le handler de l'outil `list_skills` : rappelle `discover_skills()` **à chaque invocation** (re-scan du disque — un skill ajouté en cours de session apparaît, contrairement à l'index du prompt, figé à l'import) et formate en liste à puces `  - nom: description`. Cas vide : `"(no skills found in skills/ directory)"` — jamais de chaîne vide ambiguë renvoyée au modèle.

### `run_load_skill(name)` — lignes 111–133

Le handler de `load_skill` : injecte le contenu complet d'un skill dans la conversation.

```python
    # Sanitize and build the path to the skill file
    skill_path = SKILLS_DIR / name / "SKILL.md"
    
    # Check for existence and potential directory traversal attempts
    if not skill_path.exists():
        return f"Error: skill '{name}' not found. Use list_skills to see valid names."
    
    try:
        # Load the full documentation
        content = skill_path.read_text(encoding="utf-8")
        return f"=== SKILL: {name} ===\n\n{content}\n\n=== END SKILL ==="
```

- **Ligne 126** : le message d'erreur enseigne l'action corrective — *« Use list_skills to see valid names »*. Une erreur d'outil bien rédigée est un prompt : le modèle hallucine un nom, l'erreur le renvoie vers la liste, il se corrige au tour suivant.
- **Ligne 131** : le contenu est encadré par `=== SKILL: name ===` / `=== END SKILL ===` — des bornes explicites qui délimitent le savoir injecté dans le transcript ; le modèle distingue où commence et où finit le document chargé.
- **Piège** : le commentaire ligne 124 annonce un contrôle de *« directory traversal attempts »*… qui n'existe pas. `skill_path.exists()` est la seule vérification : un `name` contenant `../` s'échappe de `skills/` et chargera n'importe quel `SKILL.md` atteignable. La promesse du commentaire n'est pas tenue par le code (comparer avec le `safe_path` documenté côté learn-claude-code).

### `main()` — lignes 192–229

Le REPL standard du dépôt : bandeau gris (ligne 197), prompt cyan `s05 >> ` (ligne 206), sortie propre sur `EOFError`/`KeyboardInterrupt` via `sys.exit(0)` (lignes 207–210), mots de sortie `q`/`exit`/`quit` ou ligne vide (ligne 213). Chaque requête est ajoutée à `history` puis confiée à la boucle du socle :

```python
        stream_loop(
            messages=history,
            tools=SKILL_TOOLS,
            dispatch=SKILL_DISPATCH,
            system=SYSTEM
        )
```

Toute la spécificité de la session tient dans ces trois arguments : la palette élargie, le dispatch élargi, le prompt à index. La boucle elle-même (streaming, exécution des outils, rétro-alimentation) vit dans core.py. Le point d'entrée (lignes 232–234) appelle simplement `main()`.

## Ce qui vient de [[core-py]]

- **`EXTENDED_TOOLS`** : les 6 schémas de base (`bash`, `read`, `write`, `grep`, `glob`, `revert`) — `SKILL_TOOLS` les étend par concaténation de liste.
- **`EXTENDED_DISPATCH`** : les handlers correspondants — `SKILL_DISPATCH` les hérite par `**` et ajoute les deux méta-outils.
- **`stream_loop`** : la boucle agentique complète (appel API streamé, affichage token par token, `dispatch_tools`, rétro-alimentation des `tool_result`) ; la session ne contient **aucune** logique de boucle. `client` et `MODEL` sont utilisés indirectement à travers elle.

## Pièges et détails d'implémentation

- **`SKILLS_DIR` pointe au-dessus du dépôt** : `Path(__file__).parent.parent / "skills"` suppose que les scripts vivent dans un sous-répertoire (le docstring de core.py trahit la structure d'origine : `agents/core.py`). Dans le clone tel que publié — scripts et `skills/` côte à côte à la racine — le chemin résolu est `../skills`, qui n'existe pas : l'agent démarre avec « (none currently installed) ». Même motif pour `_PERM_CONFIG` dans core.py.
- **Index figé vs liste vivante** : `SYSTEM` est construit à l'import, `run_list_skills()` re-scanne à chaque appel — un skill ajouté en cours de session est visible par l'outil mais absent de l'index du prompt. Désynchronisation bénigne mais réelle.
- **Pas de garde anti-traversée** malgré le commentaire « Check for … directory traversal attempts » (ligne 124) — seul `exists()` filtre.
- **La description vient du corps, pas du YAML** : le champ `description:` du frontmatter — pourtant soigneusement rédigé dans les trois skills livrés — n'est jamais lu.
- **Le lazy loading économise l'entrée, pas la suite** : un skill chargé reste dans l'historique pour toujours (le `code-review` fait ~100 lignes injectées à chaque tour suivant). Recharger le même skill le **duplique** — aucune déduplication. C'est [[s06-context-compact]] qui fournira la soupape.

## Lancer la démo

```bash
python s05_skill_loading.py
```

Prérequis : un `.env` avec `ANTHROPIC_API_KEY` et `MODEL_ID` (ou le proxy LiteLLM du README avec `ANTHROPIC_BASE_URL=http://localhost:4000`), et surtout un dossier `skills/` à l'endroit où `SKILLS_DIR` le cherche — dans le clone actuel, il faut déplacer les scripts dans un sous-répertoire ou ajuster la ligne 43, sinon l'index affiche « (none currently installed) ».

Ce qu'on observe : au prompt `s05 >> `, demander par exemple « review core.py » — le modèle appelle `load_skill` avec `code-review`, le `tool_result` encadré `=== SKILL: code-review ===` apparaît, puis la revue suit fidèlement la méthodologie en 5 étapes du skill (lecture complète, catégories BUG/SECURITY/PERF/STYLE/SUGGEST, synthèse). Sans le skill, la revue serait improvisée ; avec, elle est structurée — c'est tout l'intérêt du mécanisme, visible à l'œil nu.

## Liens

- Socle : [[core-py]]
- Session précédente : [[s04-subagent]]
- Session suivante : [[s06-context-compact]]
- Sessions liées : [[s02-tool-use]] (la mécanique d'extension schéma + dispatch que s05 réutilise), [[s21-mcp-runtime]] (l'autre voie d'extension dynamique des capacités : serveurs externes plutôt que fichiers locaux)
