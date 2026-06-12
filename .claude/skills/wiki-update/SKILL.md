---
name: wiki-update
description: Met à jour le wiki wiki-src-scratch/ après un changement dans src_scratch/ — réécrit les pages affectées, recale les numéros de lignes, met à jour _manifest.json et _graph.json, vérifie les wikilinks. À lancer après toute modification de src_scratch/.
---

# /wiki-update — Synchroniser wiki-src-scratch/ avec src_scratch/

Le wiki `.understand-anything/wiki-src-scratch/` documente le code de `src_scratch/` **avec des
numéros de lignes exacts**. Toute modification de `src_scratch/` le désynchronise. Cette skill le
remet à jour.

Cible unique : **`src_scratch/` (source) → `.understand-anything/wiki-src-scratch/` (wiki)**.
Le gabarit des pages, la carte des correspondances fichier→page et les règles de wikilinks
**vivent dans `.understand-anything/wiki-src-scratch/_conventions.md`** : le lire d'abord, à chaque run.

## Étape 1 — Identifier les fichiers modifiés

La liste de travail = les fichiers `src_scratch/*` modifiés/ajoutés/supprimés (via
`git diff --stat src_scratch/` et `git diff src_scratch/` pour le détail). ATTENTION : un changement
à nombre de lignes **constant** décale quand même les numéros de lignes internes et peut modifier du
code documenté — inclure ces fichiers (les repérer dans `git diff`, pas seulement dans `--stat`).

Hors git : pour chaque `src_scratch/*.py`, comparer le nombre de lignes physiques réel au champ
`lignes:` du frontmatter de sa page (carte dans `_conventions.md`). Tout écart = fichier à
retraiter. Ce contrôle attrape les changements de taille mais pas les modifications à taille
constante — en cas de doute, demander quels fichiers ont changé.

## Étape 2 — Mettre à jour les pages affectées

Pour chaque fichier modifié, retrouver sa page via la carte de `_conventions.md`, puis :

1. **Lire le fichier source en entier** (jamais de mémoire).
2. Mettre à jour la page en suivant STRICTEMENT le gabarit de `_conventions.md` :
   - réécrire les sections dont le contenu a changé (fonctions ajoutées/supprimées/modifiées) ;
   - **recaler tous les numéros de lignes** (`lignes X–Y` dans les titres `###`, tableau « Vue
     d'ensemble », extraits) — y compris le décalage induit par un ajout/retrait plus haut ;
   - mettre à jour `lignes:` du frontmatter (nombre de lignes physiques réel du fichier) ;
   - conserver les sections encore exactes (ne pas tout réécrire inutilement).
3. **Fonction/helper mutualisé déplacé entre fichiers** : documenter la nouvelle définition sur la
   page du fichier qui l'héberge désormais, et mettre à jour la section « Qui l'utilise » de cette
   page + les pages des fichiers qui la consomment maintenant (wikilinks croisés). (Ex. un helper du
   socle `core.py` → mettre à jour `core-py.md` ET les pages des modules qui le référencent.)
4. Fichier `src_scratch/` AJOUTÉ : créer sa page (gabarit + ajout à la carte de `_conventions.md`).
   Fichier SUPPRIMÉ : supprimer sa page et purger les wikilinks qui pointaient dessus.

Si plusieurs fichiers sont à retraiter, paralléliser avec des subagents (un par groupe de pages),
chacun recevant l'instruction de lire `_conventions.md` d'abord et de recalculer les numéros de
lignes sur le fichier réel. Garder pour soi (writer unique) `_manifest.json`, `_graph.json` et la
page d'accueil afin d'éviter les conflits d'écriture.

## Étape 3 — Mettre à jour les métadonnées du viewer

1. `_manifest.json` : recaler `lignes` de chaque page (et ajouter/retirer les entrées si des pages
   sont apparues/disparues). Champs : `page`, `title`, `phase`, `lignes`, `summary`.
2. `_graph.json` : recaler `value` = `round(sqrt(lignes), 2)` ; ajouter/retirer les nœuds et arêtes
   si la liste des fichiers ou des imports a changé (arêtes `imports`).
3. Page d'accueil (`Accueil`) : recaler tout total de lignes / décompte de fichiers qui y figure.

## Étape 4 — Valider

Exécuter ces contrôles et corriger jusqu'à zéro erreur :

```powershell
# wikilinks : 0 cassé attendu
node -e "
const fs=require('fs');const wiki='C:/Users/forma/Coding/mekicode/.understand-anything/wiki-src-scratch';
const pages=fs.readdirSync(wiki).filter(f=>f.endsWith('.md')&&!f.startsWith('_'));
const valid=new Set(pages.map(f=>f.replace(/\.md$/,'')));let broken=[],total=0;
for(const f of pages){const md=fs.readFileSync(wiki+'/'+f,'utf8');
for(const m of md.matchAll(/\[\[([^\]|]+)(?:\|[^\]]+)?\]\]/g)){total++;if(!valid.has(m[1].trim()))broken.push(f+' -> '+m[1]);}}
console.log('wikilinks:',total,'| cassés:',broken.length);broken.forEach(b=>console.log(' ',b));"

# cohérence lignes frontmatter vs fichiers réels : 0 écart attendu
node -e "
const fs=require('fs');const wiki='C:/Users/forma/Coding/mekicode/.understand-anything/wiki-src-scratch';
for(const f of fs.readdirSync(wiki).filter(f=>f.endsWith('.md')&&!f.startsWith('_'))){
const md=fs.readFileSync(wiki+'/'+f,'utf8');
const src=(md.match(/^fichier:\s*\x22?([^\x22\n]+)\x22?/m)||[])[1];
const decl=Number((md.match(/^lignes:\s*(\d+)/m)||[])[1]);
if(!src||!decl)continue;
const wcl=(fs.readFileSync('C:/Users/forma/Coding/mekicode/'+src,'utf8').match(/\n/g)||[]).length;
if(Math.abs(decl-wcl)>1)console.log('ÉCART',f,': frontmatter',decl,'vs wc -l',wcl);}
console.log('contrôle lignes terminé');"
```

Convention `lignes:` de wiki-src-scratch = `wc -l` (nombre de `\n`). Le contrôle ci-dessus tolère
un écart de 1 (newline final). Régler `lignes:` exactement sur la convention déjà en place —
recopier celle d'une page **non modifiée** du même wiki.

Vérifier aussi que `python -m py_compile` passe sur tout fichier `src_scratch/` touché.

## Étape 5 — Rapport

Résumer : fichiers traités, pages mises à jour/créées/supprimées, résultats des validations. Le
wiki est servi par `node .understand-anything/wiki-viewer/server.mjs 8088` — pas de redémarrage
(fichiers relus à chaque requête), un rafraîchissement navigateur suffit.
