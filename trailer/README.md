# `trailer/` — vidéo de présentation mekicode

Génère `out/mekicode-trailer.mp4` : **1920×1080, 30 fps, ≤ 40 s, muet** (dépose ta piste musicale
par-dessus au montage). Style **Phosphore** identique au produit : la scène « gameplay » réutilise la
**vraie** `packages/mekichat/static/mekichat.css` et le markup réel du front → rendu pixel-fidèle.

## Régénérer (tout automatique)

```bash
python trailer/build.py
```

Produit dans `out/` :
- `mekicode-trailer.mp4` — le livrable (gitignoré, lourd)
- `poster.png` — miniature cliquable du README
- `preview.gif` — aperçu animé inline du README

## Comment ça marche

- **`trailer.html`** — 5 scènes (boot → la boucle → gameplay → 4 organes → outro/CTA) + une **timeline
  déterministe** : `window.seek(t)` positionne *toute* la motion comme fonction pure du temps `t`
  (opacité, transform, texte streamé, blocs ouverts). Aucune dépendance à l'horloge réelle.
- **`render.py`** — sert le repo en HTTP local et capture chaque frame avec Playwright : pour chaque
  image, `window.seekFrame(t)` appelle `seek(t)` **puis** recale les `@keyframes` CSS d'ambiance
  (`getAnimations().currentTime = t`) → frames exactes et reproductibles.
  - `python trailer/render.py` — toutes les frames
  - `python trailer/render.py 30` — smoke (30 premières frames)
  - `python trailer/render.py --at 19000` — une frame à t=19 s (inspection) → `frames/at.png`
  - `python trailer/render.py --at 8000,16000,31000` — plusieurs → `frames/at_<ms>.png`
  - ouvrir `trailer.html?debug=1` dans un navigateur : horloge visible + scrub à la souris.
- **`build.py`** — orchestre : (polices) → render → `ffmpeg` (H.264) → MP4 + poster + gif.
- **`fetch_fonts.py`** — bundle *Share Tech Mono* + *Chakra Petch* en `.woff2` (rendu offline
  reproductible) ; si le réseau échoue, le `<link>` Google Fonts de `trailer.html` prend le relais.

## Régler la vidéo

La timeline est dans `trailer.html` (`FPS`, `DUR`, et l'objet `SC` = bornes ms de chaque scène).
Le **gameplay est rejoué** (scripté, déterministe) : zéro appel API, aucune clé requise.

> ▶ Le `README.md` racine pointe vers la vidéo publiée :
> **https://www.youtube.com/watch?v=5g4Q0RTS20E** (mise à jour après l'upload de `mekicode-trailer.mp4`).
