---
name: wiki-update
description: Met à jour le wiki d'un de nos projets de code après changement — src/ → wiki-src/ OU src_scratch/ → wiki-src-scratch/. Réécrit les pages affectées, recale les numéros de lignes, met à jour _manifest.json et _graph.json, vérifie les wikilinks. À lancer après toute modification de src/ ou src_scratch/.
---

# /wiki-update — Synchroniser un wiki de code avec sa source

Nos wikis de code documentent le code **avec des numéros de lignes exacts**. Toute
modification de la source les désynchronise. Cette skill remet le wiki à jour.

## Cibles (paire source → wiki → conventions)

| `<src>` (source) | `<wiki>` (dossier wiki) | Gabarit & carte des pages |
|---|---|---|
| `src/`         | `.understand-anything/wiki-src/`         | `.understand-anything/wiki-src/_conventions.md` |
| `src_scratch/` | `.understand-anything/wiki-src-scratch/` | `.understand-anything/wiki-src-scratch/_conventions.md` |

Dans toute la suite, `<src>` et `<wiki>` désignent la paire choisie à l'étape 0.
Le gabarit des pages, la carte des correspondances fichier→page et les règles de
wikilinks **vivent dans le `_conventions.md` du wiki visé** : le lire d'abord, à chaque run.

## Étape 0 — Choisir la cible

1. Si l'utilisateur a passé des arguments : ils désignent les fichiers/dossiers modifiés →
   en déduire la paire (`src/...` → wiki-src ; `src_scratch/...` → wiki-src-scratch).
2. Sinon, dans un repo git : `git status --porcelain src/ src_scratch/`. Traiter chaque
   arbre qui a des changements (les deux si les deux ont bougé, une passe complète par wiki).
3. Hors git : pour chaque `<src>/*.py`, comparer le nombre de lignes physiques réel au champ
   `lignes:` du frontmatter de sa page (carte dans `<wiki>/_conventions.md`). Tout écart =
   fichier à retraiter. Ce contrôle attrape les changements de taille mais pas les
   modifications à taille constante — en cas de doute, demander quels fichiers ont changé.

## Étape 1 — Identifier les fichiers modifiés

La liste de travail = les fichiers `<src>/*` modifiés/ajoutés/supprimés (via `git diff --stat <src>`
et `git diff <src>` pour le détail). ATTENTION : un changement à nombre de lignes **constant**
décale quand même les numéros de lignes internes et peut modifier du code documenté — inclure
ces fichiers (les repérer dans `git diff`, pas seulement dans `--stat`).

## Étape 2 — Mettre à jour les pages affectées

Pour chaque fichier modifié, retrouver sa page via la carte de `<wiki>/_conventions.md`, puis :

1. **Lire le fichier source en entier** (jamais de mémoire).
2. Mettre à jour la page en suivant STRICTEMENT le gabarit de `<wiki>/_conventions.md` :
   - réécrire les sections dont le contenu a changé (fonctions ajoutées/supprimées/modifiées) ;
   - **recaler tous les numéros de lignes** (`lignes X–Y` dans les titres `###`, tableau « Vue
     d'ensemble », extraits) — y compris le décalage induit par un ajout/retrait plus haut ;
   - mettre à jour `lignes:` du frontmatter (nombre de lignes physiques réel du fichier) ;
   - conserver les sections encore exactes (ne pas tout réécrire inutilement).
3. **Fonction/helper mutualisé déplacé entre fichiers** : documenter la nouvelle définition sur
   la page du fichier qui l'héberge désormais, et mettre à jour la section « Qui l'utilise » de
   cette page + les pages des fichiers qui la consomment maintenant (wikilinks croisés).
   (Pour wiki-src : c'est le cas de `shared.py` → mettre à jour `shared-py.md` ET les pages de
   session qui le référencent dans « Ce qui vient de [[shared-py]] ».)
4. Fichier `<src>` AJOUTÉ : créer sa page (gabarit + ajout à la carte de `<wiki>/_conventions.md`).
   Fichier SUPPRIMÉ : supprimer sa page et purger les wikilinks qui pointaient dessus.

Si plusieurs fichiers sont à retraiter, paralléliser avec des subagents (un par groupe de pages),
chacun recevant l'instruction de lire `<wiki>/_conventions.md` d'abord et de recalculer les
numéros de lignes sur le fichier réel. Garder pour soi (writer unique) `_manifest.json`,
`_graph.json` et la page d'accueil afin d'éviter les conflits d'écriture.

## Étape 3 — Mettre à jour les métadonnées du viewer

1. `<wiki>/_manifest.json` : recaler `lignes` de chaque page (et ajouter/retirer les entrées si
   des pages sont apparues/disparues). Champs : `page`, `title`, `phase`, `lignes`, `summary`.
2. `<wiki>/_graph.json` : recaler `value` = `round(sqrt(lignes), 2)` ; ajouter/retirer les nœuds
   et arêtes si la liste des fichiers ou des imports a changé (arêtes `imports`).
3. Page d'accueil (`Accueil`) : recaler tout total de lignes / décompte de fichiers qui y figure.

## Étape 4 — Valider

Adapter `wiki` au dossier visé puis exécuter ces contrôles, et corriger jusqu'à zéro erreur :

```powershell
# wikilinks : 0 cassé attendu — remplacer <wiki> par wiki-src ou wiki-src-scratch
node -e "
const fs=require('fs');const wiki='C:/Users/forma/Coding/mekicode/.understand-anything/<wiki>';
const pages=fs.readdirSync(wiki).filter(f=>f.endsWith('.md')&&!f.startsWith('_'));
const valid=new Set(pages.map(f=>f.replace(/\.md$/,'')));let broken=[],total=0;
for(const f of pages){const md=fs.readFileSync(wiki+'/'+f,'utf8');
for(const m of md.matchAll(/\[\[([^\]|]+)(?:\|[^\]]+)?\]\]/g)){total++;if(!valid.has(m[1].trim()))broken.push(f+' -> '+m[1]);}}
console.log('wikilinks:',total,'| cassés:',broken.length);broken.forEach(b=>console.log(' ',b));"

# cohérence lignes frontmatter vs fichiers réels : 0 écart attendu
node -e "
const fs=require('fs');const wiki='C:/Users/forma/Coding/mekicode/.understand-anything/<wiki>';
for(const f of fs.readdirSync(wiki).filter(f=>f.endsWith('.md')&&!f.startsWith('_'))){
const md=fs.readFileSync(wiki+'/'+f,'utf8');
const src=(md.match(/^fichier:\s*\x22?([^\x22\n]+)\x22?/m)||[])[1];
const decl=Number((md.match(/^lignes:\s*(\d+)/m)||[])[1]);
if(!src||!decl)continue;
const wcl=(fs.readFileSync('C:/Users/forma/Coding/mekicode/'+src,'utf8').match(/\n/g)||[]).length;
if(Math.abs(decl-wcl)>1)console.log('ÉCART',f,': frontmatter',decl,'vs wc -l',wcl);}
console.log('contrôle lignes terminé');"
```

Note : la convention `lignes:` diffère selon le wiki — **wiki-src** compte `split('\n').length`
(= wc -l + 1), **wiki-src-scratch** compte `wc -l`. Le contrôle ci-dessus tolère cet écart de 1
(newline final) et ne signale que les vrais décalages. Régler `lignes:` exactement sur la
convention déjà en place dans le wiki visé — recopier celle d'une page **non modifiée** du
même wiki.

Vérifier aussi que `python -m py_compile` passe sur tout fichier `<src>` touché.

## Étape 5 — Rapport

Résumer : cible (`<src>`/`<wiki>`), fichiers traités, pages mises à jour/créées/supprimées,
résultats des validations. Le wiki est servi par `node .understand-anything/wiki-viewer/server.mjs 8088` — pas de
redémarrage (fichiers relus à chaque requête), un rafraîchissement navigateur suffit.
