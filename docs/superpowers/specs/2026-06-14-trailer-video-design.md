# Trailer vidéo de présentation (YouTube, ≤ 40 s) — design

**Date :** 2026-06-14
**Statut :** validé en direct (« je valide go »). Livrable 100 % automatique demandé par l'utilisateur
(« tout doit être automatique, je veux rien faire »).

## But

Produire une **vidéo de présentation YouTube de ≤ 40 s** du produit `mekicode` : très moderne, animée,
avec des screenshots et une « gameplay video » de l'appli. Elle doit être **cohérente avec la vision**
(construire son propre agent IA de zéro, pédagogie → produit, tout en français), **avec le design /
style CSS** (thème cyberpunk *Phosphore* de `mekichat`) et **avec le `README.md`** (qui décrira et
référencera la vidéo).

## Décisions cadrées (issues du brainstorming)

- **Livrable :** un **MP4 fini**, rendu **end-to-end dans l'environnement** (aucune action manuelle de
  l'utilisateur). Technique « HTML-trailer » : scènes animées en HTML/CSS → capture frame-par-frame
  Playwright → encodage `ffmpeg`.
- **Gameplay :** **rejeu déterministe** de la **vraie** `mekichat.css` + du **vrai markup** du front
  (pas d'enregistrement live, pas d'appel API). Pixel-identique au produit, timing parfait, reproductible.
- **Audio :** **muet + captions néon à l'écran**. Pas de musique générée/sourcée (licence) ; l'utilisateur
  posera sa propre piste par-dessus. Le rythme des scènes reste lisible sans son.
- **Outillage vérifié présent :** `ffmpeg` 7.1, `node` v24, `playwright` (python) + Chromium installé,
  clé `OPENROUTER_API_KEY` + `MEKILLM_MODEL` renseignés (non utilisés ici puisque gameplay déterministe).
- **Cohérence DRY :** la scène produit réutilise la **vraie** `packages/mekichat/static/mekichat.css`
  (injectée au build, pas de copie qui dériverait) et les **classes/structure DOM réelles**
  (`.app/.sidebar/.topbar/.tool.t-bash/.body.streaming/.diff`…). Glyphes + couleurs d'outils exacts.
- **Déterminisme :** `trailer.html` expose `window.seek(tMs)` qui positionne **toute** la motion comme
  fonction pure de `t` (opacité/transform inline, texte par slicing, blocs ouverts/fermés). Les FX
  d'ambiance en CSS (grille, glitch, scanlines, sweep) sont recalés par `render.py` via
  `document.getAnimations().forEach(a => { a.pause(); a.currentTime = t })` avant chaque capture →
  **frames exactes**, indépendantes de l'horloge réelle et des perfs machine.
- **Polices :** *Share Tech Mono* + *Chakra Petch* **bundlées en local** (`assets/fonts/*.woff2`) via
  `@font-face`, pour un rendu **reproductible hors-ligne** (le front les charge depuis Google Fonts ; on
  ne dépend pas du réseau au render). Fallback monospace/sans si le téléchargement initial échoue.

## A. Format & contraintes de sortie

- Résolution **1920×1080**, **30 fps**, `deviceScaleFactor=1` (rendu natif 1080p, texte net).
- Durée **≤ 40 s** (cible ~38 s) → ~1140 frames.
- Encodage : `libx264`, `-pix_fmt yuv420p`, `-crf 18`, `-preset slow`, `-movflags +faststart`.
- **Pas de piste audio** (muet ; l'utilisateur ajoute la musique).
- `fps` et durée pilotés par une **table de timeline en ms** (un seul endroit à régler).

## B. Arborescence

```
trailer/
  trailer.html          scènes + timeline JS déterministe (window.seek)
  assets/
    fonts/*.woff2        Share Tech Mono + Chakra Petch (offline)
  render.py             Playwright : pour chaque frame, seek(t) + recale getAnimations() + screenshot
  build.py              orchestre : render → ffmpeg → out/ (1 commande)
  out/
    mekicode-trailer.mp4   le livrable (1080p/30/H.264, muet)         [gitignoré]
    poster.png             miniature cliquable YouTube                [versionné]
    preview.gif            aperçu animé inline README                 [versionné]
  frames/                  PNG intermédiaires                          [gitignoré]
  README.md             comment régénérer (1 commande)
```

- La **vraie** `mekichat.css` est lue depuis `packages/mekichat/static/mekichat.css` et **injectée**
  par `build.py`/`render.py` dans la page avant capture (source de vérité unique, jamais copiée).
- `.gitignore` : `trailer/frames/` et `trailer/out/*.mp4`. On **versionne** la source + `poster.png`
  + `preview.gif`.

## C. Pipeline de build (entièrement automatique)

`python trailer/build.py` :
1. **(setup)** s'assure que les polices `.woff2` sont présentes (sinon tente un téléchargement unique).
2. **render** : lance Chromium (Playwright), charge `trailer.html` (avec la vraie CSS injectée), boucle
   `t = 0 … durée` par pas de `1000/fps` ms ; à chaque pas : `page.evaluate('seek(t)')`, recale les
   animations CSS (`currentTime=t`), `page.screenshot()` → `frames/f%05d.png`.
3. **encode** : `ffmpeg -framerate 30 -i frames/f%05d.png -c:v libx264 -pix_fmt yuv420p -crf 18
   -preset slow -movflags +faststart -an out/mekicode-trailer.mp4`.
4. **derive** : extrait `out/poster.png` (une frame forte) + `out/preview.gif` (slice ~3–4 s downscalé
   ~960 px, bouclé) depuis la vidéo.
5. **(cleanup optionnel)** purge `frames/`.

## D. Storyboard (5 scènes, ~38 s)

| # | Temps | Scène | Contenu / motion | Captions (FR) |
|---|-------|-------|------------------|---------------|
| 0 | 0–4 s | **Boot / Logo** | Noir → grille en perspective monte (vrai `.bg .grid`) → wordmark **`mekicode`** s'assemble en glitch (`.glitch` magenta/vert), bande hazard, LED. | « Construis ton propre agent IA. » → « De zéro. En Python. » |
| 1 | 4–11 s | **L'idée : la boucle** | Diagramme néon qui se dessine progressivement : `TU ÉCRIS → RÉFLÉCHIT (LLM) → ⎇ RÉPONDRE ✅ / OUTIL→bash → OBSERVE 🔁` ; impulsion lumineuse le long du chemin. | « Un agent = une boucle. » / « Réfléchir → Agir → Observer. » / « comme Claude Code & Cursor — sans magie. » |
| 2 | 11–27 s | **GAMEPLAY (hero)** | Vraie UI mekichat (sidebar + main + FX). Un message se tape dans le composer → envoi (`charles //USER`) → **PROCESSING…** (barres) → bloc **bash** (ambre) qui s'ouvre, commande + sortie + métrique → **réponse markdown en streaming** (caret clignotant) → bloc **edit** (magenta) avec **diff rouge/vert**. | « Streaming en direct » · « 6 outils · confinés au workspace » · « Blocs colorés & repliables · diff chirurgical » |
| 3 | 27–33 s | **4 organes** | 4 cartes en cascade : 🗣️ **mekillm** (la voix & les oreilles) · 🧠 **mekicore** (le cerveau & les mains) · 🔀 **mekihub** (le central) · 🎭 **mekichat** (le visage) ; la chaîne `mekichat → mekihub → mekicore → mekillm` s'illumine. | « 4 paquets. 4 organes. Réutilisables. » + bandeau « temps réel multi-utilisateur · web + Discord · multi-modèle · observabilité » |
| 4 | 33–38 s | **Outro / CTA** | Retour logo `mekicode` ; les **4 palettes** (phosphor→blade→orange→acid) flashent puis reviennent au phosphor ; bloc terminal `$ pip install -r requirements.txt` / `$ ./start-chat.ps1 → :8080`. | « Tout en français. Tout fait main. 🛠️ » + lien repo |

**Prompt de démo (gameplay) :** « compte les fichiers Python du projet et résume l'architecture ».
Sortie bash simulée (déterministe) + réponse markdown courte (titre + liste) + un `edit` illustratif.

## E. Intégration README

Ajouter en haut du `README.md` (après le titre/tagline, avant « L'idée en une image ») :

```markdown
## 🎬 Voir mekicode en action (40 s)

[![mekicode — démo 40 s](trailer/out/poster.png)](https://youtu.be/XXXXXXXXXXX)

> ▶ 40 secondes : la boucle d'agent, le chat cyberpunk en streaming, les 4 paquets. *(clique → YouTube)*

![aperçu animé](trailer/out/preview.gif)
```

`https://youtu.be/XXXXXXXXXXX` = **placeholder** que l'utilisateur remplace après l'upload (signalé
explicitement). Pas d'autre dépendance externe.

## F. Vérification (avant de rapporter « fini »)

- `python -m py_compile` sur `render.py` + `build.py` (règle CLAUDE.md #3).
- `ffprobe` : durée ≤ 40 s, **1920×1080**, **30 fps**, codec h264.
- **Inspection visuelle** (consigne « verify-front-visually-before-reporting ») : ouvrir 1 keyframe par
  scène (0/1/2/3/4) + le `poster.png` et les regarder réellement — un fichier généré / un exit 0 ne
  suffit pas. Idéalement une planche-contact (montage des keyframes).
- Le `preview.gif` joue et la section README s'affiche correctement (liens/chemins valides).

## G. Hors-périmètre (YAGNI)

- Pas de musique / voix-off / sound-design (l'utilisateur ajoute sa piste).
- Pas d'enregistrement live de l'appli (gameplay déterministe).
- Pas de versions multi-formats (carré/vertical/Shorts) — uniquement 16:9 1080p YouTube.
- Pas de sous-titres `.srt` / multilingue (captions FR gravées à l'écran).

## H. Contraintes projet respectées

- **Pas le nom de Claude dans les commits** (CLAUDE.md #2 + mémoire).
- Aucune modif de `src_scratch/` → pas de `wiki-update`. Aucune modif de `packages/` (CSS lue en
  lecture seule) → pas de mise à jour de `docs/wiki-packages/`. Seule modif de fichier existant :
  `README.md` (ajout section vidéo) + `.gitignore` (entrées `trailer/`).
- Le code de build (`render.py`/`build.py`) vit sous `trailer/` : ce ne sont pas des tests de
  non-régression (qui, eux, restent dans `tests/`).
```
