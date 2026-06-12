# mekicode — agent harness

Projet : construire notre propre agent harness en Python, en s'inspirant des 3 repos
clonés dans `inspiration/` (gitignoré). Tout le contenu (docs, wiki, commentaires) est en **français**.

## Vision
Trois bases de code parallèles, du plus pédagogique au plus réutilisable :
- `src/` + `src_scratch/` — refontes d'étude des repos d'inspiration (démos par mécanisme,
  features s01–s23), backend **Anthropic**.
- `packages/` — la cible « produit » : des paquets **autonomes et réutilisables** (provider LLM
  généraliste + mini-harness), backend **OpenRouter** (compatible ollama/litellm), pensés pour être
  importés depuis n'importe quel projet.

Chaque base est documentée par un wiki understand-anything dédié sous `.understand-anything/`
(graphes de connaissance en français) ; `inspiration/` garde les repos sources d'étude.

## Structure
- `src/shared.py` — bibliothèque commune du harness (code dédupliqué de learn-claude-code)
- `src/complete.py` — LE point d'entrée : toutes les features actives (CLI s20 + mémoire s09)
- `src/sessions/s01.py` … `s20.py` — démos exécutables, une par mécanisme (délta de chaque
  session ; `_bootstrap.py` rend src/ importable en lancement direct)
- `.understand-anything/verify-shared.py` + `smoke-sessions.py` — portail de non-régression
  de shared.py (noms/signatures/import réel) : à lancer après tout changement de src/
- `src_scratch/` — refonte dédupliquée de claude-code-from-scratch : 11 modules + config.yaml
  (~2 000 lignes, toutes les features s01–s23, bugs source corrigés `FIX(mekicode)`) ;
  entrée : `python src_scratch/main.py` ; non-régression : `python .refactor-tmp/smoke_all.py`
- `packages/` — paquets autonomes réutilisables, importables par chemin (3ᵉ base, à côté de `src/`
  et `src_scratch/`) :
  - `packages/mekillm/` — provider LLM généraliste : wrapper du SDK `openai` → OpenRouter
    (bascule ollama/litellm via le seul `.env`), avec observabilité intégrée (logging + JSONL +
    hooks). Importable n'importe où (`mekillm.LLM`, `mekillm.complete`, `mekillm.observe`).
  - `packages/mekicore/` — mini-harness = le s01 de claude-code-from-scratch adapté, branché sur
    mekillm (format OpenAI tool-calling, outil `bash`). Entrée : `python packages/mekicore/main.py`.
- `tests/` — tests du projet, à la racine. Non-régression de `packages/` (réseau-free, sans clé
  API) : `python tests/smoke_packages.py`
- `.understand-anything/` — graphes understand-anything du projet **+ tous les wikis et le viewer**
  (regroupés ici pour alléger la racine) :
  - `.understand-anything/wiki/` — wiki du projet d'inspiration learn-claude-code (vault Obsidian, ne pas modifier sauf demande)
  - `.understand-anything/wiki-ccfs/` — wiki du repo d'inspiration claude-code-from-scratch
  - `.understand-anything/wiki-src/` — wiki de NOTRE code src/ (conventions : `.understand-anything/wiki-src/_conventions.md`)
  - `.understand-anything/wiki-src-scratch/` — wiki de NOTRE code src_scratch/ (conventions : `.understand-anything/wiki-src-scratch/_conventions.md`)
  - `.understand-anything/wiki-viewer/` — viewer navigateur multi-projets
  - `.understand-anything/lancer-wiki-viewer.ps1` — script de lancement : `.understand-anything/lancer-wiki-viewer.ps1 [port]` (défaut 8088)
- `inspiration/` — repos d'étude + leurs graphes understand-anything (`.understand-anything/` propre à chaque repo)

## Règles
1. **Après TOUTE modification de `src/` OU `src_scratch/`, exécuter la skill `wiki-update`** pour
   resynchroniser le wiki correspondant — `src/` → `.understand-anything/wiki-src/`, `src_scratch/` → `.understand-anything/wiki-src-scratch/`
   (pages, numéros de lignes, _manifest.json, _graph.json). Les wikis documentent le code avec des
   numéros de lignes exacts — ils se périment à chaque édition. (`packages/` n'a pas encore de wiki :
   la règle ne s'y applique pas.)
2. **Jamais le nom de Claude dans les commits** : pas de `Co-Authored-By: Claude...`, pas de
   « Generated with Claude Code » (exigence explicite de l'utilisateur).
3. Les fichiers `src/sNN.py` restent des démos fines : la logique réutilisable va dans `shared.py`.
4. Vérifier `python -m py_compile` sur tout fichier Python modifié avant de conclure.
5. **Les tests (smoke, non-régression) vivent dans `tests/` à la racine** — pas dans les dossiers de
   code. De même, `.env`, `.env.example` et `.gitignore` restent à la racine.
