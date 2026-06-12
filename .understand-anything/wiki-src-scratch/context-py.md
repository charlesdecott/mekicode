---
title: "context.py · Skills & compaction"
phase: "Contexte & tâches"
fichier: "src_scratch/context.py"
lignes: 159
tags: [skills, compaction, memoire, frontmatter, tokens]
---

# context.py · Skills & compaction

> **En une phrase** : ce module gère ce que le modèle *sait* — chargement de connaissances spécialisées à la demande (skills, s05) et survie au-delà de la fenêtre de contexte (compaction de l'historique + mémoire persistante, s06).

## Rôle dans le harness

Deux mécanismes de la source partagent le même problème : la fenêtre de contexte est finie. Les **skills** (s05) résolvent le côté entrée — plutôt que de gonfler le prompt système avec toutes les procédures possibles, on n'y met qu'un index léger (`skills_index`) et le modèle charge le contenu complet via l'outil `load_skill` quand il en a besoin. La **compaction** (s06) résout le côté accumulation — quand l'historique dépasse `COMPACT_THRESHOLD`, la partie ancienne est résumée par un appel LLM dédié et le résumé est persisté dans `MEMORY.md`, relu au démarrage de la session suivante par [[main-py]].

Le module remplace les sessions s05 et s06 du repo source (`inspiration/claude-code-from-scratch/`), qui dupliquaient chacune le socle complet. Ici, il ne reste que le delta : 159 lignes au lieu de deux fichiers de session, et cinq bugs de la source corrigés au passage (voir plus bas). L'enregistrement de l'outil `load_skill` se fait **à l'import** via `register_tool` de [[tools-py]] — importer `context` suffit pour que le modèle gagne l'outil.

## Vue d'ensemble du fichier

| Lignes | Zone | Contenu |
|---|---|---|
| 1–11 | Docstring & imports | json, datetime, yaml ; `MODEL/ROOT/STATE_DIR/client/paint/text_of` de core, `register_tool` de tools |
| 13–17 | Constantes | `SKILLS_DIR`, `MEMORY_FILE`, `COMPACT_THRESHOLD`, `KEEP_RECENT` |
| 20–85 | Skills (s05) | `_skill_description`, `skills_index`, `load_skill` + enregistrement de l'outil |
| 88–159 | Compaction & mémoire (s06) | `load_memory`, `estimate_tokens`, `_flatten`, `_summarize`, `_has_tool_result`, `maybe_compact` |

## Constantes et configuration

- **`SKILLS_DIR` (ligne 14)** : `ROOT / "skills"` — *dans* le repo, contrairement à la source (premier FIX du fichier).
- **`MEMORY_FILE` (ligne 15)** : `STATE_DIR / "MEMORY.md"` — l'état runtime est centralisé sous `.state/` géré par [[core-py]].
- **`COMPACT_THRESHOLD` (ligne 16)** : `40_000` — même valeur que s06, mais le commentaire précise « ici en tokens estimés » : le seuil s'applique au résultat d'`estimate_tokens`, soit ≈ 160 000 caractères de JSON.
- **`KEEP_RECENT` (ligne 17)** : `6` — nombre de messages gardés verbatim lors d'une compaction.

## Les fonctions, une à une

### `_skill_description(md)` — lignes 22–40

Extrait la description d'un `SKILL.md` pour l'index.

```python
    if md.startswith("---"):
        end = md.find("\n---", 3)
        if end != -1:
            body = md[end + 4:]
            try:
                meta = yaml.safe_load(md[3:end])
            except yaml.YAMLError:
                meta = None
            if isinstance(meta, dict) and meta.get("description"):
                return str(meta["description"]).strip()
```

- **Lignes 26–35** : si le fichier ouvre sur `---`, le frontmatter YAML est parsé et `description` est retournée — c'est la voie nominale, et la correction du bug s05 (la source lisait le corps).
- **Lignes 36–39** : repli si pas de frontmatter ou pas de clé `description` — première ligne non vide et non titre du corps, tronquée à 100 caractères. Dernier filet ligne 40 : `"No description available."`.
- Un YAML invalide ne fait pas planter l'index : `yaml.YAMLError` est attrapée et on bascule silencieusement sur le repli.

### `skills_index()` — lignes 43–55

Construit l'index léger « `- nom: description` » injecté dans le prompt système par [[main-py]]. Itère sur `sorted(SKILLS_DIR.iterdir())` et ne retient que les répertoires contenant un `SKILL.md` (ligne 50). Chaque skill est lu dans son propre `try/except` (lignes 51–54) : un skill illisible produit une ligne `- nom: Error reading metadata: …` au lieu de casser l'index entier. Deux sorties dégradées identiques — `"(none currently installed)"` — si le répertoire n'existe pas (ligne 46) ou s'il est vide (ligne 55).

### `load_skill(name)` — lignes 58–67

Le corps de l'outil exposé au modèle : charge le contenu complet d'un skill dans le contexte.

```python
    path = (SKILLS_DIR / name / "SKILL.md").resolve()
    # FIX(mekicode): vraie garde anti-traversée (la source l'annonçait sans la faire)
    if SKILLS_DIR.resolve() not in path.parents or not path.exists():
        return f"Error: skill '{name}' not found. Available:\n{skills_index()}"
```

- **Ligne 62** : après `.resolve()`, le répertoire des skills doit figurer parmi les `parents` du chemin — un `name` du type `../../secret` est rejeté. Garde réelle là où la source se contentait de l'annoncer.
- Le message d'erreur **rejoue l'index** : le modèle qui se trompe de nom reçoit immédiatement la liste des skills valides et peut se corriger au tour suivant.
- **Ligne 65** : le contenu est encadré par des sentinelles `=== SKILL: name ===` / `=== END SKILL ===` — le modèle distingue le corps du skill du reste du `tool_result`.

### Enregistrement de l'outil `load_skill` — lignes 70–85

Appel à `register_tool` de [[tools-py]] au moment de l'import du module : schéma (un seul paramètre `name`, requis) + handler `lambda inp: load_skill(inp["name"])`. La description envoyée au modèle (« *Use this before starting a task requiring specialized domain knowledge* ») est la consigne d'usage : charger avant d'agir.

### `load_memory()` — lignes 90–92

Une ligne utile : le contenu de `MEMORY_FILE`, ou `""` si absent. [[main-py]] l'appelle au démarrage pour injecter la mémoire (tronquée aux 4 000 derniers caractères de son côté) dans le prompt système.

### `estimate_tokens(messages)` — lignes 95–97

```python
    return len(json.dumps(messages, default=str, ensure_ascii=False)) // 4
```

L'heuristique de la source : ≈ 4 caractères de JSON par token. `default=str` évite le crash sur des objets non sérialisables (blocs SDK), `ensure_ascii=False` garde les accents en clair plutôt qu'en `\uXXXX` (estimation plus juste en français).

### `_flatten(messages)` — lignes 100–112

Aplatit l'historique en texte `[role]: contenu` pour le compresseur. La partie délicate (lignes 105–110) : un `content` peut être une chaîne, une liste de dicts (`tool_result`, blocs sérialisés) ou une liste d'objets SDK — d'où la double branche `b.get("text") or str(b.get("content", ""))` pour les dicts et `getattr(b, "text", "")` pour les objets. Tout autre cas retombe sur une liste vide.

### `_summarize(messages)` — lignes 115–126

Le résumé LLM one-shot : un `client.messages.create` **direct**, hors boucle d'agent — pas d'outils, pas de dispatch, juste de la compression. Le prompt système cadre ce qu'il faut retenir : *« Retain all critical technical decisions, file paths mentioned, code changes made, and pending tasks. Ignore trivial back-and-forth. »* L'entrée est plafonnée à 20 000 caractères (`_flatten(messages)[:20000]`, ligne 123) et la sortie à `max_tokens=2000`.

```python
    return text_of(response)
```

Le texte de la réponse est extrait par `text_of` de [[core-py]] (ligne 126) — la même brique partagée que les agents délégués utilisent pour aplatir une réponse API en chaîne, là où la source concaténait les blocs à la main. À ne pas confondre avec le `getattr(b, "text", "")` de `_flatten` juste au-dessus, qui relève d'une autre logique (aplatir un historique de messages, pas une réponse unique).

### `_has_tool_result(msg)` — lignes 129–133

Le prédicat de la frontière interdite : vrai si le message est un tour `user` dont le contenu liste contient au moins un bloc `tool_result`. C'est l'outil de la correction du bug de découpe de s06 (voir ci-dessous).

### `maybe_compact(messages, keep_recent=KEEP_RECENT, force=False)` — lignes 136–159

Le chef d'orchestre de la compaction, appelé par [[main-py]] après chaque tour (mode automatique) et par la commande `:compact` (mode `force=True`).

```python
    if (not force and estimate_tokens(messages) < COMPACT_THRESHOLD) or len(messages) <= keep_recent:
        return messages
    # FIX(mekicode): la coupe recule jusqu'à une frontière propre — le premier message
    # gardé ne peut pas être un tool_result dont le tool_use assistant serait résumé
    cut = len(messages) - keep_recent
    while cut > 0 and _has_tool_result(messages[cut]):
        cut -= 1
    if cut <= 0:
        return messages
```

- **Ligne 139** : double garde — sous le seuil (sauf `force`) ou trop peu de messages, on rend la liste inchangée.
- **Lignes 143–145** : le point de coupe recule tant que le premier message qui serait *gardé* est un `tool_result` — sinon l'API rejetterait un `tool_result` dont le `tool_use` assistant a été résumé. Si la marche arrière atteint 0, on renonce à compacter (ligne 146–147) plutôt que de produire un historique invalide.
- **Lignes 152–156** : la mémoire est écrite en **append** (`open("a")`), datée `## Compaction du %Y-%m-%d %H:%M` ; un échec d'écriture est signalé en rouge mais ne bloque pas la compaction en cours.
- **Lignes 158–159** : retour `[résumé] + recent` — le résumé est réinjecté comme message `user` préfixé `[Context summary of previous turns]:`, pas comme prompt système.

## Bugs de la source corrigés ici

- **`SKILLS_DIR` hors du dépôt (s05)** — ligne 13. La source calculait le chemin avec `parent.parent`, qui remontait au-dessus du repo : le répertoire visé n'existait pas et l'index était silencieusement vide. Ici : `ROOT / "skills"`, ancré sur `Path(__file__).parent` via [[core-py]].
- **Description lue au mauvais endroit (s05)** — lignes 23–24. La source lisait la description d'un skill dans le *corps* du `SKILL.md` alors qu'elle vit dans le frontmatter YAML. `_skill_description` parse désormais le frontmatter (avec repli sur la première ligne utile du corps).
- **Garde anti-traversée fictive (s05)** — ligne 61. La source annonçait une protection contre l'évasion de chemin dans `load_skill` sans l'implémenter. Ici : `.resolve()` puis vérification que `SKILLS_DIR.resolve()` figure dans `path.parents`.
- **Découpe qui orpheline des `tool_result` (s06)** — lignes 141–142. La source coupait brutalement `[-KEEP_RECENT:]` : si la frontière tombait au milieu d'un échange outil, le premier message gardé était un `tool_result` sans son `tool_use` — erreur API garantie au tour suivant. `maybe_compact` recule la coupe jusqu'à une frontière propre.
- **Mémoire « datée » avec un chemin (s06)** — ligne 151. La source écrivait `os.getcwd()` en guise d'horodatage dans le fichier mémoire. Ici : vraie date `datetime.now():%Y-%m-%d %H:%M`, et écriture en append plutôt qu'en écrasement.

## Qui l'utilise

- **[[main-py]]** — le seul importateur direct (`import context`). `build_system()` assemble le prompt système avec `load_memory()` et `skills_index()` ; la boucle REPL appelle `maybe_compact(state["messages"])` après chaque tour, et la commande `:compact` force la compaction avec `force=True`.
- **Indirectement, tout le harness** : l'outil `load_skill` enregistré à l'import entre dans le registre `TOOLS`/`DISPATCH` de [[tools-py]], donc toute boucle de [[loop-py]] qui utilise les outils par défaut l'expose au modèle.

## Pièges et détails d'implémentation

- **L'import a un effet de bord** : `register_tool("load_skill", …)` s'exécute au chargement du module. Importer `context` pour `estimate_tokens` seulement enregistre quand même l'outil.
- **`estimate_tokens` est une louche, pas une balance** : ÷4 sur le JSON surestime le code dense et sous-estime la prose unicode. Le seuil de 40 000 « tokens » est calibré pour cette heuristique, pas pour le vrai compteur de l'API.
- **`_summarize` tronque à 20 000 caractères** : un historique ancien très volumineux n'est que partiellement résumé — ce qui dépasse la fenêtre du compresseur est perdu pour le résumé (mais reste dans `MEMORY.md` des compactions précédentes).
- **La marche arrière peut tout annuler** : si les `keep_recent` derniers messages et tout ce qui précède immédiatement sont des `tool_result` en chaîne, `cut` atteint 0 et la fonction rend l'historique inchangé — la compaction est différée, pas garantie.
- **La mémoire grossit sans borne** : chaque compaction *appende* à `MEMORY.md`. C'est [[main-py]] qui se protège en n'injectant que les 4 000 derniers caractères dans le prompt système.

## Liens

- Modules liés : [[core-py]] (client, chemins, `paint`, `text_of` pour le retour de `_summarize`), [[tools-py]] (`register_tool`), [[main-py]] (assemblage du prompt et déclenchement de la compaction), [[loop-py]] (expose `load_skill` au modèle via le registre)
- Page voisine de la phase : [[tasks-py]]
