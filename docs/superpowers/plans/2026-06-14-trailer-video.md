# Trailer vidéo YouTube (≤ 40 s) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produire automatiquement `trailer/out/mekicode-trailer.mp4` (1080p/30 fps/H.264, muet, ≤ 40 s), trailer cyberpunk *Phosphore* du produit `mekicode`, + `poster.png` + `preview.gif`, et référencer la vidéo dans le `README.md`.

**Architecture:** Un `trailer.html` autoporté qui réutilise la **vraie** `packages/mekichat/static/mekichat.css` et expose `window.seek(tMs)` plaçant **toute** la motion comme fonction pure du temps. `render.py` (Playwright) sert le repo via `http.server`, charge la page, et pour chaque frame appelle `seek(t)` + recale les animations CSS (`getAnimations().currentTime=t`) puis screenshot. `build.py` orchestre render → `ffmpeg` → MP4 + poster + gif. Déterministe, hors-ligne, sans appel API.

**Tech Stack:** Python 3, Playwright (Chromium déjà installé), ffmpeg 7.1, HTML/CSS/JS (timeline maison), thème Phosphore existant.

**Convention de commit :** messages en français, **jamais** le nom de Claude / « Generated with ». Branche : `feat/trailer-video` (déjà créée). Vérifier `python -m py_compile` sur tout `.py` modifié.

---

## Structure des fichiers

```
trailer/
  trailer.html      scènes + timeline déterministe (window.seek) — réutilise mekichat.css
  assets/fonts/     Share Tech Mono + Chakra Petch (.woff2, bundlés offline)
  render.py         http.server + Playwright : seek(t)+recale anims → frames/f%05d.png
  build.py          render → ffmpeg → out/  (1 commande, tout automatique)
  scenes.js         (optionnel) si trailer.html devient gros : logique des scènes extraite
  frames/           PNG intermédiaires            [gitignoré]
  out/
    mekicode-trailer.mp4   livrable               [gitignoré]
    poster.png             miniature              [versionné]
    preview.gif            aperçu README          [versionné]
  README.md         régénération en 1 commande
```

Fichiers existants modifiés : `README.md` (section vidéo), `.gitignore` (entrées `trailer/`).

---

## Contrat `window.seek(t)` (le cœur du déterminisme)

`trailer.html` définit, dans un `<script>` :

```js
// ── Timeline globale (ms) ──────────────────────────────────────────────
const FPS = 30, DUR = 38000;                 // durée totale ≤ 40 s
const SC = {                                  // bornes de chaque scène (ms)
  boot:   [0,     4000],
  loop:   [4000,  11000],
  game:   [11000, 27000],
  organs: [27000, 33000],
  outro:  [33000, 38000],
};
// ── utilitaires d'animation (fonctions pures de t) ─────────────────────
const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
const lerp =(a,b,u)=>a+(b-a)*u;
const easeOut=u=>1-Math.pow(1-u,3);
const easeInOut=u=>u<.5?4*u*u*u:1-Math.pow(-2*u+2,3)/2;
// progression 0→1 entre deux bornes ms
const prog=(t,a,b)=>clamp((t-a)/(b-a),0,1);
// opacité d'apparition/disparition d'un élément sur une fenêtre [in0,in1 … out0,out1]
function win(t,in0,in1,out0,out1){
  if(t<in0||t>out1) return 0;
  if(t<in1) return easeOut(prog(t,in0,in1));
  if(t<out0) return 1;
  return 1-easeInOut(prog(t,out0,out1));
}
// révèle N premiers caractères d'un texte selon t (effet machine à écrire)
const typed=(full,t,a,b)=>full.slice(0, Math.round(full.length*easeOut(prog(t,a,b))));

// ── point d'entrée appelé par render.py pour chaque frame ──────────────
function seek(t){
  showScene('boot',   t); /* …une fn par scène, positionne ses éléments… */
  showScene('loop',   t);
  showScene('game',   t);
  showScene('organs', t);
  showScene('outro',  t);
}
// recale aussi les animations CSS d'ambiance (grille/glitch/scan) → frame exacte
window.seekFrame = function(t){
  seek(t);
  document.getAnimations().forEach(a=>{ try{ a.pause(); a.currentTime=t; }catch(e){} });
};
window.seek = seek; window.TL = {FPS, DUR, SC};
```

**Règle d'or :** aucune motion de scène ne doit dépendre de l'horloge réelle. Tout passe par `t`.
Les `@keyframes` CSS ne servent QUE aux FX d'ambiance (`.bg`), recalés via `getAnimations()`.

---

## Task 1: Scaffold `trailer/` + bundler les polices

**Files:**
- Create: `trailer/assets/fonts/.gitkeep`
- Create: `trailer/fetch_fonts.py`

- [ ] **Step 1: Créer l'arborescence**

```bash
mkdir -p trailer/assets/fonts trailer/frames trailer/out
```

- [ ] **Step 2: Écrire `trailer/fetch_fonts.py`** (télécharge les .woff2 ; échec réseau toléré)

```python
#!/usr/bin/env python3
"""Télécharge Share Tech Mono + Chakra Petch (.woff2) dans assets/fonts/.
Best-effort : si le réseau échoue, trailer.html garde le <link> Google Fonts en repli."""
import re, sys, urllib.request
from pathlib import Path

DST = Path(__file__).resolve().parent / "assets" / "fonts"
CSS_URL = ("https://fonts.googleapis.com/css2?"
           "family=Chakra+Petch:wght@400;600;700&family=Share+Tech+Mono&display=swap")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}  # → woff2 modernes

def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    try:
        req = urllib.request.Request(CSS_URL, headers=UA)
        css = urllib.request.urlopen(req, timeout=20).read().decode("utf-8")
    except Exception as e:
        print(f"[fonts] CSS inaccessible ({e}) — repli sur le <link> réseau."); return 0
    urls = re.findall(r"url\((https://[^)]+\.woff2)\)", css)
    seen, faces = set(), []
    for i, u in enumerate(dict.fromkeys(urls)):
        name = f"font_{i:02d}.woff2"
        try:
            data = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20).read()
            (DST / name).write_bytes(data); seen.add(name)
        except Exception as e:
            print(f"[fonts] skip {u}: {e}")
    print(f"[fonts] {len(seen)} fichier(s) woff2 récupéré(s) dans {DST}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Lancer et compiler**

Run: `python -m py_compile trailer/fetch_fonts.py && python trailer/fetch_fonts.py`
Expected: compile OK ; affiche « N fichier(s) woff2 récupéré(s) » (ou message de repli si offline).

- [ ] **Step 4: Commit**

```bash
git add trailer/fetch_fonts.py trailer/assets/fonts/
git commit -m "trailer: scaffold + bundling des polices (offline-first)"
```

> Note d'exécution : les `@font-face` concrets (familles « Share Tech Mono » / « Chakra Petch » pointant
> sur les woff2 récupérés) seront écrits dans `trailer.html` (Task 2) une fois les noms de fichiers connus.
> Si 0 woff2 récupéré, on garde uniquement le `<link>` Google Fonts dans `trailer.html`.

---

## Task 2: `trailer.html` — harness (fond, timeline, `seek`, overlay debug)

**Files:**
- Create: `trailer/trailer.html`

- [ ] **Step 1: Écrire le squelette** avec : `<link>` vers la vraie CSS + Google Fonts, `@font-face` locaux (si woff2 présents), le fond `.bg` (réutilise les classes existantes), 5 sections de scènes vides, et le `<script>` du **contrat `seek`** ci-dessus, plus un overlay debug `#t` affichant `t`.

Structure (extrait clé du `<head>`/`<body>`) :

```html
<!doctype html><html lang="fr"><head><meta charset="utf-8">
<link rel="stylesheet" href="../packages/mekichat/static/mekichat.css">
<link href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@400;600;700&family=Share+Tech+Mono&display=swap" rel="stylesheet">
<style>
  /* @font-face locaux ajoutés ici si assets/fonts/*.woff2 présents (repli offline) */
  html,body{width:1920px;height:1080px;overflow:hidden;background:var(--bg)}
  body{cursor:none}
  .scene{position:fixed;inset:0;z-index:2;display:grid;place-items:center;will-change:opacity,transform}
  #t{position:fixed;left:8px;bottom:6px;z-index:99;font:11px var(--mono);color:#0f0;opacity:.0}
  /* (#t.opacity passe à .6 en mode debug ; 0 au render) */
  .cap{font-family:var(--ui);font-weight:700;text-shadow:var(--p1-glow)} /* captions néon */
</style></head>
<body data-theme="phosphor">
  <!-- fond animé identique au front -->
  <div class="bg"><div class="grid"></div><div class="vig"></div><div class="scan"></div>
       <div class="noise"></div><div class="sweep"></div><div class="mosh"></div><div class="mosh b"></div></div>
  <section class="scene" id="sc-boot"></section>
  <section class="scene" id="sc-loop"></section>
  <section class="scene" id="sc-game"></section>
  <section class="scene" id="sc-organs"></section>
  <section class="scene" id="sc-outro"></section>
  <div id="t"></div>
  <script> /* … contrat seek() + showScene() squelette (no-op par scène pour l'instant) … */ </script>
</body></html>
```

- [ ] **Step 2: Implémenter `showScene(name,t)` minimal** : pose l'opacité de chaque `<section>` à `win(t, SC[name][0], SC[name][0]+400, SC[name][1]-400, SC[name][1])` et met `#t.textContent = (t/1000).toFixed(2)+'s'`. Scènes encore vides → on valide juste l'enchaînement des fondus.

- [ ] **Step 3: Vérifier dans un navigateur** (manuel rapide via Playwright en Task 3) — ici, juste s'assurer que le fichier est bien formé (pas d'erreur de syntaxe JS).

Run: `node -e "require('fs').readFileSync('trailer/trailer.html','utf8'); console.log('html lu OK')"`
Expected: « html lu OK » (sanity check de lecture ; la validation visuelle vient en Task 3).

- [ ] **Step 4: Commit**

```bash
git add trailer/trailer.html
git commit -m "trailer: harness HTML (fond Phosphore + timeline deterministe seek())"
```

---

## Task 3: `render.py` — capture déterministe + smoke 3 frames

**Files:**
- Create: `trailer/render.py`

- [ ] **Step 1: Écrire `render.py`**

```python
#!/usr/bin/env python3
"""render.py — sert le repo en HTTP local et capture chaque frame du trailer via Playwright.
Déterministe : pour chaque frame, seek(t) + recale les animations CSS à currentTime=t."""
from __future__ import annotations
import functools, http.server, socketserver, threading
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent          # racine du repo
TRAILER = Path(__file__).resolve().parent
FRAMES = TRAILER / "frames"
W, H = 1920, 1080

def _serve() -> tuple[socketserver.TCPServer, int]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)   # port libre
    httpd.RequestHandlerClass.log_message = lambda *a, **k: None  # silencieux
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]

def render(fps: int | None = None, dur_ms: int | None = None, limit: int | None = None) -> int:
    FRAMES.mkdir(parents=True, exist_ok=True)
    for old in FRAMES.glob("f*.png"): old.unlink()
    httpd, port = _serve()
    url = f"http://127.0.0.1:{port}/trailer/trailer.html"
    n_total = None
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(args=["--force-color-profile=srgb", "--hide-scrollbars",
                                        "--disable-lcd-text"])
            pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
            pg.goto(url, wait_until="networkidle")
            pg.wait_for_function("typeof window.seekFrame === 'function'")
            tl = pg.evaluate("window.TL")
            fps = fps or tl["FPS"]; dur_ms = dur_ms or tl["DUR"]
            n = int(dur_ms * fps / 1000)
            if limit: n = min(n, limit)
            n_total = n
            for i in range(n):
                t = round(i * 1000 / fps)
                pg.evaluate("(t)=>window.seekFrame(t)", t)
                pg.screenshot(path=str(FRAMES / f"f{i:05d}.png"), animations="disabled")
            b.close()
    finally:
        httpd.shutdown()
    print(f"[render] {n_total} frames → {FRAMES}")
    return 0

if __name__ == "__main__":
    import sys
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    raise SystemExit(render(limit=lim))
```

- [ ] **Step 2: py_compile + smoke 3 frames**

Run: `python -m py_compile trailer/render.py && python trailer/render.py 3`
Expected: compile OK ; « [render] 3 frames → … » ; 3 PNG `f00000..f00002.png` créés.

- [ ] **Step 3: Inspection visuelle (obligatoire)** — ouvrir `trailer/frames/f00000.png` avec l'outil Read (image) et confirmer : fond Phosphore (grille verte/magenta, vignette), 1920×1080. *(Consigne mémoire : vérifier visuellement, pas seulement l'existence du fichier.)*

- [ ] **Step 4: Commit**

```bash
git add trailer/render.py
git commit -m "trailer: render.py (http.server + capture Playwright deterministe)"
```

---

## Tasks 4–8 : les 5 scènes (implémentation + capture keyframe + inspection visuelle)

> **Méthode commune à chaque scène** (motion = fonction pure de `t`, cf. contrat) :
> 1. Construire le DOM de la scène dans son `<section>` (statique) au chargement.
> 2. Implémenter `showScene('<nom>', t)` : pilote opacités/transforms/texte via `win/typed/lerp`.
> 3. **Rendre une keyframe** au milieu de la scène : `python trailer/render.py` puis screenshot ciblé —
>    pratique : ajouter un mode `python trailer/render.py --at <ms>` qui ne rend qu'une frame à `t=<ms>`.
> 4. **Inspecter visuellement** la frame (Read image) et ajuster jusqu'à ce que ce soit propre.
> 5. Commit.

Ajouter d'abord à `render.py` un mode 1-frame (Step commun) :

```python
# dans render(), avant la boucle, si at_ms is not None: rendre une seule frame à t=at_ms → frames/at.png
```
Run de contrôle d'une scène : `python trailer/render.py --at 13000` → `frames/at.png` → Read image.

### Task 4: Scène 0 — Boot / Logo (0–4 s)
**Files:** Modify `trailer/trailer.html`
- [ ] DOM : un wordmark `mekicode` (réutilise `.glitch` avec `data-t="mekicode"` + un `.glyph` `>_`), une bande hazard (`--haz`), une LED (`.led`), 2 captions.
- [ ] `showScene('boot',t)` : grille déjà visible (fond) ; le logo `scale/opacity` monte sur 0→1.2 s (easeOut) ; caption A « Construis ton propre agent IA. » sur 1.3–2.6 s ; caption B « De zéro. En Python. » sur 2.5–4 s ; sortie globale 3.6–4 s.
- [ ] Keyframe `--at 1500` → inspecter (logo glitch lisible, néon).
- [ ] Commit : `trailer: scene 0 boot/logo`.

### Task 5: Scène 1 — La boucle (4–11 s)
**Files:** Modify `trailer/trailer.html`
- [ ] DOM : un diagramme de boucle (nœuds en `clip-path:var(--clip)` Phosphore : `TU ÉCRIS`, `RÉFLÉCHIT (LLM)`, `RÉPONDRE ✅`, `OUTIL → bash`, `OBSERVE 🔁`) + connecteurs (SVG `<path>` ou divs lignes).
- [ ] `showScene('loop',t)` : les nœuds apparaissent en cascade (`win` décalés) ; les connecteurs « se dessinent » via `stroke-dashoffset` piloté par `t` (SVG) ; impulsion lumineuse = un point qui parcourt le chemin (position = `lerp` le long du path) ; captions « Un agent = une boucle. » puis « Réfléchir → Agir → Observer. ».
- [ ] Keyframe `--at 8000` → inspecter (chemin tracé, nœuds lisibles).
- [ ] Commit : `trailer: scene 1 boucle d'agent`.

### Task 6: Scène 2 — GAMEPLAY (11–27 s) — la plus importante
**Files:** Modify `trailer/trailer.html`
- [ ] DOM : reproduire **fidèlement** le markup mekichat (cf. `app.py`/`views.py`) dans `#sc-game` :
  `.app > (.sidebar, .main)`. Sidebar : `.brand` (`.glyph` « M », `.glitch` `data-t="MEKICHAT"`, `.ver` « // harness v0.1 :: ROOT »), `.new-btn`, `.sec-label` « SESSIONS [03] », 2–3 `.session` (dont une `.active`), `.sidebar-foot` (`.led` + « OPENROUTER :: LINK_OK »). Main : `.topbar` (`.channel` `[#]` `<h1>conversation</h1>` `.sub`, `.chips` MODEL/SID + `.presence` 2 chips), `.thread > .thread-inner`, `.composer`.
- [ ] Contenu rejoué dans `.thread-inner` (tous présents dans le DOM, **révélés par `t`**) :
  1. `.msg.user` (avatar « CD », who « charles », tag « //USER ») texte = `typed("compte les fichiers Python du projet et résume l'architecture", t, 11000, 12800)`.
  2. `render_thinking` `.thinking` « PROCESSING… » visible 13000–15000.
  3. `.tool.t-bash` : en-tête glyphe `❯_` + `BASH` + cmd `find . -name '*.py' | wc -l` + métrique « 1 lignes » + statut `DONE` ; passe de `collapsed` à ouvert (`.tool-out` = `42`) vers 15500–16500.
  4. `.msg.bot` `.body.streaming` : réponse markdown `typed(...)` 17000–22000 (caret via `.streaming::after`), puis `.body` markdown figé (titre « ## Architecture » + liste à puces : mekillm/mekicore/mekihub/mekichat).
  5. `.tool.t-edit` : glyphe `±` + `EDIT` + `.diff` (`--- ancien` lignes `.del`, `+++ nouveau` lignes `.add`) + métrique `+1 -1` ; apparaît 23000–24500, s'ouvre.
  - 3 captions néon flottantes (`.cap`) ancrées : « Streaming en direct » (≈18 s), « 6 outils · confinés au workspace » (≈16 s), « Blocs colorés & repliables · diff » (≈24 s).
- [ ] `showScene('game',t)` : fondu d'entrée de `.app` 11000–11600 ; chaque sous-élément piloté par `win`/`typed` aux bornes ci-dessus ; léger « scroll » du `.thread-inner` (translateY négatif) au fil de l'ajout pour garder le bas visible.
- [ ] Keyframes `--at 16000`, `--at 19000`, `--at 24000` → inspecter chacune (UI pixel-cohérente avec le front, couleurs d'outils correctes : bash ambre, edit magenta).
- [ ] Commit : `trailer: scene 2 gameplay (vraie UI mekichat rejouee)`.

### Task 7: Scène 3 — 4 organes (27–33 s)
**Files:** Modify `trailer/trailer.html`
- [ ] DOM : 4 cartes (`clip-path:var(--clip)`, bord néon) : 🗣️ **mekillm** / la voix & les oreilles ; 🧠 **mekicore** / le cerveau & les mains ; 🔀 **mekihub** / le central ; 🎭 **mekichat** / le visage. + une ligne `mekichat → mekihub → mekicore → mekillm` qui s'illumine maillon par maillon. + bandeau features.
- [ ] `showScene('organs',t)` : cartes en cascade (translateY+opacity, `win` décalés de ~250 ms) ; la chaîne s'allume maillon par maillon (couleur/glow piloté par `t`) ; caption « 4 paquets. 4 organes. Réutilisables. » + bandeau « temps réel multi-utilisateur · web + Discord · multi-modèle · observabilité ».
- [ ] Keyframe `--at 31000` → inspecter (4 cartes lisibles, chaîne illuminée).
- [ ] Commit : `trailer: scene 3 quatre organes (paquets)`.

### Task 8: Scène 4 — Outro / CTA (33–38 s)
**Files:** Modify `trailer/trailer.html`
- [ ] DOM : logo `mekicode` (réutilise le glitch), un bloc terminal (`.body pre` style) `$ pip install -r requirements.txt` / `$ ./start-chat.ps1  → http://localhost:8080`, caption « Tout en français. Tout fait main. 🛠️ », ligne repo.
- [ ] `showScene('outro',t)` : retour logo (fade/scale) ; **flash des 4 palettes** en changeant `document.body.dataset.theme` selon `t` (`phosphor`→`blade`→`orange`→`acid`→`phosphor`, paliers ~250 ms entre 34000–35500) — change les variables CSS → recolore grille + logo ; bloc terminal `typed` 35000–37000 ; tout reste affiché jusqu'à 38000.
- [ ] Keyframe `--at 34800` (sur une palette non-phosphor) + `--at 37000` → inspecter.
- [ ] Commit : `trailer: scene 4 outro/CTA + flash des 4 palettes`.

---

## Task 9: `build.py` — render complet + encodage + poster + preview.gif

**Files:**
- Create: `trailer/build.py`

- [ ] **Step 1: Écrire `build.py`**

```python
#!/usr/bin/env python3
"""build.py — pipeline complet : (fonts) → render frames → ffmpeg MP4 → poster.png + preview.gif.
100% automatique : `python trailer/build.py`."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import render as render_mod   # même dossier

HERE = Path(__file__).resolve().parent
FRAMES, OUT = HERE / "frames", HERE / "out"
MP4 = OUT / "mekicode-trailer.mp4"
POSTER = OUT / "poster.png"
GIF = OUT / "preview.gif"
FPS = 30

def _run(cmd: list[str]) -> None:
    print("[ffmpeg]", " ".join(cmd[:6]), "…")
    subprocess.run(cmd, check=True)

def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    # 1) polices (best-effort)
    subprocess.run([sys.executable, str(HERE / "fetch_fonts.py")], check=False)
    # 2) frames
    render_mod.render()
    pattern = str(FRAMES / "f%05d.png")
    # 3) MP4 (muet)
    _run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", pattern,
          "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "slow",
          "-movflags", "+faststart", "-an", str(MP4)])
    # 4) poster : une frame forte (gameplay ~ t=19s → frame 19*FPS)
    poster_frame = FRAMES / f"f{19*FPS:05d}.png"
    _run(["ffmpeg", "-y", "-i", str(poster_frame), str(POSTER)])
    # 5) preview.gif : slice gameplay ~3,5 s, downscale 960px, palette propre
    _run(["ffmpeg", "-y", "-ss", "15", "-t", "3.5", "-i", str(MP4),
          "-vf", "fps=15,scale=960:-1:flags=lanczos,split[s0][s1];"
                 "[s0]palettegen[p];[s1][p]paletteuse", str(GIF)])
    print(f"[build] OK → {MP4}\n              {POSTER}\n              {GIF}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: py_compile + run complet**

Run: `python -m py_compile trailer/build.py && python trailer/build.py`
Expected: render ~1140 frames, puis MP4 + poster.png + preview.gif créés sous `trailer/out/`.

- [ ] **Step 3: Commit** (sans le MP4 lourd — cf. .gitignore Task 10)

```bash
git add trailer/build.py
git commit -m "trailer: build.py (render -> ffmpeg MP4 + poster + preview.gif)"
```

---

## Task 10: README + .gitignore

**Files:**
- Modify: `README.md` (après le bloc titre/citation, avant « ## 🧠 L'idée en une image »)
- Modify: `.gitignore`

- [ ] **Step 1: Ajouter la section vidéo au README** (juste après les lignes 9–11, avant `## 🧠`)

```markdown
## 🎬 Voir mekicode en action (40 s)

[![mekicode — démo 40 s](trailer/out/poster.png)](https://youtu.be/XXXXXXXXXXX)

> ▶ 40 secondes : la boucle d'agent, le chat cyberpunk en streaming, les 4 paquets. *(clique → YouTube)*

![aperçu animé](trailer/out/preview.gif)

> 🔁 Régénérer la vidéo : `python trailer/build.py` (→ `trailer/out/mekicode-trailer.mp4`).
```

⚠ `https://youtu.be/XXXXXXXXXXX` est un **placeholder** : le remplacer par l'URL réelle après upload.

- [ ] **Step 2: Ajouter à `.gitignore`**

```
# trailer (artefacts lourds : on versionne seulement poster.png + preview.gif)
trailer/frames/
trailer/out/*.mp4
```

- [ ] **Step 3: Commit**

```bash
git add README.md .gitignore trailer/out/poster.png trailer/out/preview.gif
git commit -m "doc: README reference la video de presentation (poster + apercu anime)"
```

---

## Task 11: Vérification finale (ffprobe + visuel) + crée `trailer/README.md`

**Files:**
- Create: `trailer/README.md`

- [ ] **Step 1: `ffprobe`** — durée/format

Run: `ffprobe -v error -show_entries format=duration:stream=width,height,codec_name,avg_frame_rate -of default=nw=1 trailer/out/mekicode-trailer.mp4`
Expected: `duration` ≤ 40 ; `width=1920 height=1080` ; `codec_name=h264` ; `avg_frame_rate=30/1`.

- [ ] **Step 2: Planche-contact + inspection visuelle (obligatoire)** — extraire 1 image par scène et les regarder

Run:
```bash
ffmpeg -y -i trailer/out/mekicode-trailer.mp4 -vf "select='eq(n\,60)+eq(n\,240)+eq(n\,570)+eq(n\,900)+eq(n\,1050)',tile=5x1" -frames:v 1 trailer/frames/contact.png
```
Puis **ouvrir `trailer/frames/contact.png` avec Read (image)** et confirmer : les 5 scènes sont lisibles, néon Phosphore cohérent, gameplay fidèle au front, pas de texte coupé. *(Un fichier généré ≠ une vidéo correcte : on regarde réellement.)*

- [ ] **Step 3: Écrire `trailer/README.md`** (régénération, format, où est le livrable)

```markdown
# trailer/ — vidéo de présentation mekicode

Génère `out/mekicode-trailer.mp4` (1920×1080, 30 fps, ≤ 40 s, **muet** — ajoute ta musique au montage).

## Régénérer (tout automatique)
    python trailer/build.py

Produit : `out/mekicode-trailer.mp4` (gitignoré), `out/poster.png`, `out/preview.gif`.

## Comment ça marche
- `trailer.html` : 5 scènes + timeline déterministe `window.seek(t)` ; réutilise la **vraie**
  `packages/mekichat/static/mekichat.css` (thème Phosphore) → gameplay pixel-fidèle.
- `render.py` : sert le repo en HTTP local, capture chaque frame via Playwright (seek(t) + recale
  des animations CSS) → `frames/`.
- `build.py` : render → `ffmpeg` (H.264) → MP4 + poster + gif.

Muet par choix : dépose ta piste musicale par-dessus dans ton éditeur. Le placeholder YouTube du
README racine est à remplacer après upload.
```

- [ ] **Step 4: Commit final**

```bash
git add trailer/README.md
git commit -m "trailer: README (regeneration + format) ; verification ffprobe+visuelle OK"
```

---

## Self-review (couverture spec → plan)

- **Spec A (format 1080p/30/≤40s/muet)** → Task 3 (render W/H), Task 9 (ffmpeg yuv420p/crf/-an), Task 11 (ffprobe). ✅
- **Spec B (arborescence + CSS réelle non copiée)** → Task 1/2 (`<link>` relatif vers la vraie CSS), Task 3 (sert le repo → CSS résolue). ✅
- **Spec C (pipeline auto 1 commande)** → Task 9 `build.py`. ✅
- **Spec D (5 scènes storyboard)** → Tasks 4–8 (une par scène, bornes ms = celles de `SC`). ✅
- **Spec E (README + placeholder YouTube)** → Task 10. ✅
- **Spec F (vérif py_compile + ffprobe + visuel)** → py_compile à chaque task .py ; Task 11. ✅
- **Spec déterminisme (seek + getAnimations)** → contrat + Task 3 `seekFrame`. ✅
- **Spec polices offline** → Task 1 `fetch_fonts.py` + `@font-face`/`<link>` repli Task 2. ✅
- **Spec H (pas de nom Claude ; pas de wiki-update ; build hors tests/)** → respecté (commits FR, aucune modif src_scratch/ ni packages/). ✅
- **Placeholder scan :** seul placeholder = URL YouTube (voulu, signalé). Pas de TODO/TBD orphelin. ✅
- **Cohérence des noms :** `seek`/`seekFrame`/`window.TL`/`SC`/`render()`/`build.main()` cohérents entre tasks. ✅
```
