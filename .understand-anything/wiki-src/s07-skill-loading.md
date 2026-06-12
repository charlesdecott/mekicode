---
title: "s07 · Skill Loading"
session: 07
phase: "Fondamentaux"
fichier: "src/sessions/s07.py"
lignes: 114
tags: [skills, chargement-a-la-demande, frontmatter, catalogue]
prev: "s06-subagent"
next: "s08-context-compact"
---

# s07 · Skill Loading

> **En une phrase** : divulgation progressive — le catalogue (nom + description) entre dans le system prompt, le contenu complet d'un skill n'arrive qu'à la demande via l'outil `load_skill`, en tool_result.

## Rôle dans le harness

Concaténer toutes les connaissances du projet dans le system prompt fait transporter des milliers de tokens hors sujet à chaque appel. La parade tient en deux niveaux : **niveau 1**, un catalogue bon marché (~1 ligne par skill, issu du frontmatter de chaque `SKILL.md`) injecté dans le system ; **niveau 2**, le contenu complet chargé seulement quand l'agent le juge utile, via `load_skill(name)` — il atterrit alors **dans l'historique** (tool_result), où la compaction de [[s08-context-compact]] pourra le reprendre, et non dans le system rejoué à chaque tour.

Tout le mécanisme (scan, registre, catalogue, chargement) vit dans [[shared-py]], qui définit `SKILLS_DIR = WORKDIR / "skills"` et scanne **à l'import**. Le délta de ce fichier : créer un dossier de démo `skills-demo/` (2 skills, écriture idempotente), **repointer** `shared.SKILLS_DIR` dessus puis rescanner — `scan_skills()` lit la globale du module, la réaffecter suffit. La sécurité est structurelle : `load_skill` interroge le registre (`dict.get`), jamais le disque — pas de path traversal possible.

## Ce que fait ce fichier

### pick() — lignes 24–26

Le helper commun : sous-ensemble de `BUILTIN_TOOLS` par nom. Pool de la session (lignes 29–31) : `bash`, `read_file`, `glob`, `load_skill`.

### Câblage module — lignes 29–58

- `TOOL_NAMES` / `TOOLS` / `HANDLERS` (29–31) : 4 outils ; `load_skill` est déjà câblé sur `shared.load_skill` dans `BUILTIN_HANDLERS`.
- `SKILLS_DEMO_DIR = WORKDIR / "skills-demo"` (33) : le dossier de démo, distinct du `skills/` par défaut.
- `DEMO_SKILLS` (37–58) : deux skills embarqués (`commit-style`, `code-review`), chacun un `SKILL.md` complet avec frontmatter `name`/`description`. Contenus volontairement ASCII : shared lit les fichiers avec `read_text()` sans encodage explicite (encodage locale sous Windows).

### ensure_demo_skills() — lignes 61–70

```python
def ensure_demo_skills():
    """Écrit les SKILL.md de démo (idempotent), repointe shared.SKILLS_DIR
    vers skills-demo/ et repeuple SKILL_REGISTRY via scan_skills()."""
    for slug, content in DEMO_SKILLS.items():
        manifest = SKILLS_DEMO_DIR / slug / "SKILL.md"
        if not manifest.exists():
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(content)
    shared.SKILLS_DIR = SKILLS_DEMO_DIR
    scan_skills()
```

Le cœur du délta. Les fichiers ne sont écrits que s'ils manquent (relancer la démo ne les écrase pas — on peut les éditer à la main entre deux lancements). Les deux dernières lignes sont le repointage : shared a déjà scanné `skills/` (inexistant) à l'import ; on réaffecte la globale puis on rescanne, et `SKILL_REGISTRY` contient le catalogue de démo. C'est pour cette réaffectation que le fichier garde `import shared` : `shared.SKILLS_DIR = ...` doit toucher la globale du module — une affectation sur un nom from-importé n'aurait modifié qu'une copie locale.

### build_system() — lignes 73–78

```python
def build_system():
    """Niveau 1 de la divulgation : le CATALOGUE entre dans le system prompt
    (~1 ligne par skill), jamais le contenu complet."""
    return (f"You are a coding agent at {WORKDIR}.\n"
            f"Skills available:\n{list_skills()}\n"
            "Use load_skill(name) to get the full instructions when relevant.")
```

L'équivalent du `build_system()` de l'original : catalogue dans le system, mécanisme de chargement annoncé. Le system est figé au début de `main()` — après le rescannage, donc à jour.

### main() — lignes 81–109

Initialisation (`ensure_demo_skills()` puis `build_system()`, lignes 82–83), affichage du catalogue scanné, puis boucle interactive (`q` pour quitter) à trois chemins :

- `:list` (98–100) — réaffiche `list_skills()` (le niveau 1, local, 0 appel API).
- `:load <nom>` (101–105) — appelle `load_skill()` en local : la **même fonction** que celle câblée derrière l'outil ; un nom inconnu renvoie la liste des skills disponibles (l'erreur est elle-même utile).
- Texte libre (106–109) — tour d'`agent_loop` avec pool et system figés ; si le modèle juge un skill pertinent, on voit `> load_skill` puis le contenu complet arriver en tool_result.

## Ce qui vient de [[shared-py]]

Imports explicites (`from shared import (...)`), sauf `SKILLS_DIR` : le fichier le **rebinde** (`shared.SKILLS_DIR = SKILLS_DEMO_DIR`), donc l'accès reste qualifié via `import shared`.

- `SKILLS_DIR` / `SKILL_REGISTRY` — répertoire scanné et catalogue en mémoire (repointés/repeuplés ici ; `SKILLS_DIR` accédé en `shared.SKILLS_DIR`).
- `scan_skills()` — vide puis repeuple le registre depuis `skills-demo/*/SKILL.md` (frontmatter via `_parse_frontmatter`, YAML toléré).
- `list_skills()` — le catalogue en puces `- nom: description` (niveau 1).
- `load_skill(name)` — le contenu complet à la demande (niveau 2), aussi le handler de l'outil.
- `BUILTIN_TOOLS` / `BUILTIN_HANDLERS`, `agent_loop`, `print_turn_assistants`, `PROMPT`, `WORKDIR`.

## Différences avec l'original learn-claude-code

- L'original (`s07_skill_loading/code.py`, 427 lignes) ré-implémentait tout s02–s06 ; ici 113 lignes de câblage, le mécanisme skills vit dans shared.py.
- L'original scannait `skills/` une seule fois à l'import et figeait `SYSTEM` — ajouter un skill exigeait un redémarrage ; ici la démo crée son propre `skills-demo/`, repointe `SKILLS_DIR` et rescanne au lancement de `main()`.
- Le `load_skill` de shared renvoie la liste des skills disponibles quand le nom est inconnu ; l'original répondait juste `Skill not found: <name>`.
- L'original n'avait pas de skills livrés avec le code ; ici deux `SKILL.md` de démo sont embarqués et écrits de façon idempotente.
- Pool réduit à 4 outils (pas de `task` ni `todo_write`) : la session se concentre sur la divulgation progressive.

## Lancer la démo

```
python src/sessions/s07.py
```

Au lancement : le dossier `skills-demo/` est créé et le catalogue scanné s'affiche. `:load code-review` montre le niveau 2 sans appel API ; `:load inexistant` montre l'erreur-catalogue. En texte libre, demander « relis ce diff comme en revue de code » : le modèle voit le catalogue dans son system, appelle `load_skill("code-review")` et applique la checklist.

## Liens

- Bibliothèque : [[shared-py]]
- Session précédente : [[s06-subagent]]
- Session suivante : [[s08-context-compact]]
- Sessions liées : [[s10-system-prompt]] (l'assemblage du system généralisé — le catalogue y entre via `assemble_system_prompt`), [[s09-memory]] (même patron index léger + contenu à la demande)
