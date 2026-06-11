---
name: wiki-update
description: Met à jour le wiki du projet src/ (wiki-src/) après des changements dans src/ — réécrit les pages affectées, recale les numéros de lignes, met à jour _manifest.json et _graph.json, vérifie les wikilinks. À lancer après toute modification de src/.
---

# /wiki-update — Synchroniser wiki-src/ avec src/

Le wiki `wiki-src/` documente le code de `src/` **avec des numéros de lignes exacts**.
Toute modification de `src/` le désynchronise. Cette skill le remet à jour.

## Étape 1 — Identifier les fichiers modifiés

1. Si le dossier est un repo git : `git status --porcelain src/` + `git diff --stat src/` (et
   `git diff` pour le détail). Les fichiers modifiés/ajoutés/supprimés de `src/` sont la liste de travail.
2. Sinon (pas de git) : comparer pour chaque `src/*.py` le nombre de lignes physiques réel
   avec le champ `lignes:` du frontmatter de sa page wiki (carte des correspondances dans
   `wiki-src/_conventions.md`). Tout écart = fichier à retraiter. Ce contrôle attrape les
   changements de taille mais pas les modifications à taille constante — en cas de doute,
   demander à l'utilisateur quels fichiers ont changé.
3. Si l'utilisateur a passé des arguments à la skill, c'est la liste de travail (chemins src/).

## Étape 2 — Mettre à jour les pages affectées

Pour chaque fichier modifié, retrouver sa page via la carte de `wiki-src/_conventions.md`, puis :

1. **Lire le fichier source en entier** (jamais de mémoire).
2. Mettre à jour la page en suivant STRICTEMENT le gabarit de `wiki-src/_conventions.md` :
   - réécrire les sections dont le contenu a changé (fonctions ajoutées/supprimées/modifiées) ;
   - **recaler tous les numéros de lignes** (`lignes X–Y` dans les titres `###`, extraits) ;
   - mettre à jour `lignes:` du frontmatter (nombre de lignes physiques réel) ;
   - conserver les sections encore exactes (ne pas tout réécrire inutilement).
3. Si `shared.py` a changé : mettre à jour `wiki-src/shared-py.md` (tableau des sections,
   plages de lignes, API publique) ET vérifier les pages de session qui référencent les
   éléments modifiés dans leur section « Ce qui vient de [[shared-py]] ».
4. Fichier src/ AJOUTÉ : créer sa page (gabarit + ajout à la carte de `_conventions.md`).
   Fichier SUPPRIMÉ : supprimer sa page et purger les wikilinks qui pointaient dessus.

Si plusieurs fichiers sont à retraiter, paralléliser avec des subagents (un par groupe de pages),
chacun recevant l'instruction de lire `wiki-src/_conventions.md` d'abord.

## Étape 3 — Mettre à jour les métadonnées du viewer

1. `wiki-src/_manifest.json` : recaler `lignes` de chaque page (et ajouter/retirer les entrées
   si des pages sont apparues/disparues). Les champs : `page`, `title`, `phase`, `lignes`, `summary`.
2. `wiki-src/_graph.json` : recaler `value` (≈ sqrt(lignes)) ; ajouter/retirer les nœuds et
   arêtes si la liste des fichiers a changé (arêtes `imports` sNN→shared-py + chaîne de progression).

## Étape 4 — Valider

Exécuter ces contrôles et corriger jusqu'à zéro erreur :

```powershell
# wikilinks : 0 cassé attendu
node -e "
const fs=require('fs');const wiki='C:/Users/forma/Coding/mekicode/wiki-src';
const pages=fs.readdirSync(wiki).filter(f=>f.endsWith('.md')&&!f.startsWith('_'));
const valid=new Set(pages.map(f=>f.replace(/\.md$/,'')));let broken=[],total=0;
for(const f of pages){const md=fs.readFileSync(wiki+'/'+f,'utf8');
for(const m of md.matchAll(/\[\[([^\]|]+)(?:\|[^\]]+)?\]\]/g)){total++;if(!valid.has(m[1].trim()))broken.push(f+' -> '+m[1]);}}
console.log('wikilinks:',total,'| cassés:',broken.length);broken.forEach(b=>console.log(' ',b));"

# cohérence lignes frontmatter vs fichiers réels : 0 écart attendu
node -e "
const fs=require('fs');const wiki='C:/Users/forma/Coding/mekicode/wiki-src';
for(const f of fs.readdirSync(wiki).filter(f=>f.endsWith('.md')&&!f.startsWith('_'))){
const md=fs.readFileSync(wiki+'/'+f,'utf8');
const src=(md.match(/^fichier:\s*\x22?([^\x22\n]+)\x22?/m)||[])[1];
const decl=Number((md.match(/^lignes:\s*(\d+)/m)||[])[1]);
if(!src)continue;
const real=fs.readFileSync('C:/Users/forma/Coding/mekicode/'+src,'utf8').split('\n').length;
if(real!==decl)console.log('ÉCART',f,': frontmatter',decl,'vs réel',real);}
console.log('contrôle lignes terminé');"
```

Vérifier aussi que `python -m py_compile` passe sur tout fichier src/ touché.

## Étape 5 — Rapport

Résumer : fichiers src/ traités, pages mises à jour/créées/supprimées, résultats des validations.
Le wiki est servi par `node wiki-viewer/server.mjs 8088` — pas de redémarrage nécessaire
(fichiers relus à chaque requête), un simple rafraîchissement navigateur suffit.
