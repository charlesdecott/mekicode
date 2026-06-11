# mekicode — agent harness

Projet : construire notre propre agent harness en Python, en s'inspirant des 3 repos
clonés dans `inspiration/` (gitignoré). Tout le contenu (docs, wiki, commentaires) est en **français**.

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
- `wiki/` — wiki du projet d'inspiration learn-claude-code (vault Obsidian, ne pas modifier sauf demande)
- `wiki-ccfs/` — wiki du repo d'inspiration claude-code-from-scratch
- `wiki-src/` — wiki de NOTRE code src/ (mêmes conventions : `wiki-src/_conventions.md`)
- `wiki-src-scratch/` — wiki de NOTRE code src_scratch/ (conventions : `wiki-src-scratch/_conventions.md`)
- `wiki-viewer/` — viewer navigateur multi-projets : `node wiki-viewer/server.mjs 8088`
- `inspiration/` — repos d'étude + leurs graphes understand-anything (`.understand-anything/`)

## Règles
1. **Après TOUTE modification de `src/`, exécuter la skill `wiki-update`** pour resynchroniser
   `wiki-src/` (pages, numéros de lignes, _manifest.json, _graph.json). Le wiki documente le code
   avec des numéros de lignes exacts — il se périme à chaque édition.
2. **Jamais le nom de Claude dans les commits** : pas de `Co-Authored-By: Claude...`, pas de
   « Generated with Claude Code » (exigence explicite de l'utilisateur).
3. Les fichiers `src/sNN.py` restent des démos fines : la logique réutilisable va dans `shared.py`.
4. Vérifier `python -m py_compile` sur tout fichier Python modifié avant de conclure.
