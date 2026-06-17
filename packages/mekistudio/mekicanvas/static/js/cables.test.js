const test = require('node:test');
const assert = require('node:assert');
const C = require('./cables.js');

const box = (x, y, w, h) => ({ x, y, w, h });

test('adaptiveSide: axe dominant + tie horizontal', () => {
  const a = box(0, 0, 100, 100);
  assert.equal(C.adaptiveSide(a, box(300, 0, 100, 100)), 'right');
  assert.equal(C.adaptiveSide(a, box(-300, 0, 100, 100)), 'left');
  assert.equal(C.adaptiveSide(a, box(0, 300, 100, 100)), 'bottom');
  assert.equal(C.adaptiveSide(a, box(0, -300, 100, 100)), 'top');
  // tie |dx|==|dy| -> horizontal
  assert.equal(C.adaptiveSide(a, box(200, 200, 100, 100)), 'right');
});

test('sideAnchor: point sur la face + clamp sur la longueur du côté', () => {
  const b = box(0, 0, 100, 40);
  assert.deepEqual(C.sideAnchor(b, 'right', 0), { x: 100, y: 20 });
  assert.deepEqual(C.sideAnchor(b, 'left', 0), { x: 0, y: 20 });
  // offset énorme -> clampé sur la face (hauteur 40, marge 10 -> +-10 max)
  assert.equal(C.sideAnchor(b, 'right', 999).y, 30);
  assert.equal(C.sideAnchor(b, 'right', -999).y, 10);
});

test('assignLanes: offsets centrés, triés par le voisin, gap clampé, jamais égaux', () => {
  const box = (x, y, w, h) => ({ x, y, w, h });
  const node = box(0, 0, 100, 300); // côté droit long
  // 3 voisins dans le désordre vertical -> lanes triées de haut en bas
  const cables = [
    { neighbor: box(400, 200, 50, 50) },
    { neighbor: box(400, 0, 50, 50) },
    { neighbor: box(400, 100, 50, 50) },
  ];
  const offs = C.assignLanes(cables, node, 'right');
  // l'entrée du voisin le plus haut (y=0, index 1) doit avoir l'offset le plus négatif
  assert.ok(offs[1] < offs[2] && offs[2] < offs[0]);
  // centrés autour de 0
  assert.ok(Math.abs(offs[0] + offs[1] + offs[2]) < 1e-9);
  // 2 lanes ne partagent jamais la même valeur
  assert.equal(new Set(offs).size, 3);
  // 1 seul câble -> offset 0
  assert.deepEqual(C.assignLanes([{ neighbor: box(400, 0, 10, 10) }], node, 'right'), [0]);
});

function segs(points) {
  const out = [];
  for (let i = 1; i < points.length; i++) {
    out.push({ dx: points[i].x - points[i - 1].x, dy: points[i].y - points[i - 1].y });
  }
  return out;
}

test('subwayPoints: exactement une diagonale 45° stricte, reste axis-aligned', () => {
  const A = { x: 100, y: 100 }, B = { x: 400, y: 220 };
  const pts = C.subwayPoints(A, 'right', B, 'left');
  const s = segs(pts);
  const diag = s.filter((g) => Math.abs(g.dx) > 0.001 && Math.abs(g.dy) > 0.001);
  assert.equal(diag.length, 1, 'une seule diagonale');
  assert.ok(Math.abs(Math.abs(diag[0].dx) - Math.abs(diag[0].dy)) < 0.001, '45° strict');
  // les autres segments sont horizontaux ou verticaux
  s.filter((g) => g !== diag[0]).forEach((g) => {
    assert.ok(Math.abs(g.dx) < 0.001 || Math.abs(g.dy) < 0.001);
  });
});

test('subwayPoints: run vertical dominant gère le 45° sans déborder', () => {
  const A = { x: 100, y: 100 }, B = { x: 140, y: 400 };
  const s = segs(C.subwayPoints(A, 'right', B, 'left'));
  const diag = s.filter((g) => Math.abs(g.dx) > 0.001 && Math.abs(g.dy) > 0.001);
  assert.equal(diag.length, 1);
  assert.ok(Math.abs(Math.abs(diag[0].dx) - Math.abs(diag[0].dy)) < 0.001);
});

test('pointsToPath: M..L.. uniquement, segments = points-1', () => {
  const d = C.pointsToPath([{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 20, y: 10 }]);
  assert.match(d, /^M [\d.]+ [\d.]+( L [\d.]+ [\d.]+)+$/);
  assert.equal((d.match(/L/g) || []).length, 2);
  assert.ok(!/[CQA]/.test(d), 'pas de courbe');
});

test('cableClass: couleur par relation (brique G)', () => {
  // git : tout câble touchant la node branche git
  assert.equal(C.cableClass('gitbranch', 'kernel'), 'cab-git');
  assert.equal(C.cableClass('fileexplorer', 'gitbranch'), 'cab-git');
  assert.equal(C.cableClass('chat', 'gitbranch'), 'cab-git');
  // fichier : tout câble reliant un éditeur (l'éditeur est toujours l'enfant/feuille)
  assert.equal(C.cableClass('fileeditor', 'folder'), 'cab-file');
  assert.equal(C.cableClass('fileeditor', 'fileexplorer'), 'cab-file');   // fichier à la racine
  // explorateur → dossier de profondeur 1
  assert.equal(C.cableClass('folder', 'fileexplorer'), 'cab-d1');
  // dossier → dossier
  assert.equal(C.cableClass('folder', 'folder'), 'cab-folder');
  // fallback neutre
  assert.equal(C.cableClass('chat', ''), 'cable-default');
});

// --- Raffinements routage : contournement d'obstacles + anti-superposition ---

test('segHitsBox: traverse vs dehors', () => {
  const O = { x: 200, y: 90, w: 40, h: 40 };
  assert.equal(C.segHitsBox({ x: 100, y: 100 }, { x: 400, y: 100 }, O), true);  // traverse
  assert.equal(C.segHitsBox({ x: 100, y: 100 }, { x: 150, y: 100 }, O), false); // s'arrête avant
  assert.equal(C.segHitsBox({ x: 100, y: 50 }, { x: 400, y: 50 }, O), false);   // passe au-dessus
});

test('routeAround: sans obstacle -> tracé direct inchangé', () => {
  const aA = { x: 100, y: 100 }, aB = { x: 400, y: 100 };
  assert.deepEqual(C.routeAround(aA, 'right', aB, 'left', []),
                   C.subwayPoints(aA, 'right', aB, 'left'));
});

test('routeAround: contourne un node sur la trajectoire (dégagé + 45°)', () => {
  const aA = { x: 100, y: 100 }, aB = { x: 400, y: 100 };
  const O = { x: 200, y: 90, w: 40, h: 40 };
  assert.equal(C.pathHits(C.subwayPoints(aA, 'right', aB, 'left'), [O]), true); // direct traverse
  const pts = C.routeAround(aA, 'right', aB, 'left', [O]);
  assert.equal(C.pathHits(pts, [O]), false);                                    // contournement dégage
  for (let i = 1; i < pts.length; i++) {                                        // segments H/V/45° seulement
    const dx = Math.abs(pts[i].x - pts[i - 1].x), dy = Math.abs(pts[i].y - pts[i - 1].y);
    assert.ok(dx < 1e-6 || dy < 1e-6 || Math.abs(dx - dy) < 1e-6, `segment ${i} non H/V/45`);
  }
});

test('routeAround: cas vertical (node au-dessus du parent) contourne aussi', () => {
  const aA = { x: 100, y: 100 }, aB = { x: 100, y: 400 };
  const O = { x: 90, y: 200, w: 40, h: 40 };
  const pts = C.routeAround(aA, 'bottom', aB, 'top', [O]);
  assert.equal(C.pathHits(pts, [O]), false);
});

test('diagOf: extrait la diagonale', () => {
  assert.deepEqual(C.diagOf([{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 30, y: 20 }, { x: 50, y: 20 }]),
                   [{ x: 10, y: 0 }, { x: 30, y: 20 }]);
  assert.equal(C.diagOf([{ x: 0, y: 0 }, { x: 10, y: 0 }]), null);
});

test('diagsOverlap: collinéaire vs parallèle-loin vs pente opposée', () => {
  const d1 = [{ x: 0, y: 0 }, { x: 50, y: 50 }];
  assert.equal(C.diagsOverlap(d1, [{ x: 10, y: 8 }, { x: 60, y: 58 }], 4), true);   // ~même droite, chevauche
  assert.equal(C.diagsOverlap(d1, [{ x: 0, y: 100 }, { x: 50, y: 150 }], 4), false);// parallèle, loin
  assert.equal(C.diagsOverlap(d1, [{ x: 0, y: 50 }, { x: 50, y: 0 }], 4), false);   // pente opposée
});

test('bboxesOverlap', () => {
  assert.equal(C.bboxesOverlap({ x: 0, y: 0, w: 10, h: 10 }, { x: 5, y: 5, w: 10, h: 10 }), true);
  assert.equal(C.bboxesOverlap({ x: 0, y: 0, w: 10, h: 10 }, { x: 50, y: 50, w: 10, h: 10 }), false);
});

// --- routeAvoiding : pur 45° + changement de face de la node la plus proche ---

function all45(pts) { // segments uniquement H / V / 45°
  for (let i = 1; i < pts.length; i++) {
    const dx = Math.abs(pts[i].x - pts[i - 1].x), dy = Math.abs(pts[i].y - pts[i - 1].y);
    if (!(dx < 1e-6 || dy < 1e-6 || Math.abs(dx - dy) < 1e-6)) return false;
  }
  return true;
}

test('routeAvoiding: sans obstacle -> faces naturelles, tracé direct', () => {
  const src = { x: 0, y: 0, w: 100, h: 100 }, tgt = { x: 400, y: 0, w: 100, h: 100 };
  const r = C.routeAvoiding(src, 'right', tgt, 'left', []);
  assert.equal(r.hit, false);
  assert.equal(r.srcSide, 'right'); assert.equal(r.tgtSide, 'left');
});

test('routeAvoiding: obstacle dense -> ne passe PAS sous le node (45° strict)', () => {
  const src = { x: 300, y: 0, w: 300, h: 380 };   // explorer
  const tgt = { x: 1400, y: 0, w: 520, h: 440 };  // editor2 lointain
  const O = { x: 700 - 18, y: -40 - 18, w: 520 + 36, h: 440 + 36 }; // editor1 gonflé, au milieu
  const r = C.routeAvoiding(src, 'right', tgt, 'left', [O]);
  assert.equal(C.pathHits(r.pts, [O]), false);
  assert.ok(all45(r.pts));
});

test('routeAvoiding: obstacle collé à la source -> change la face de sortie', () => {
  const src = { x: 300, y: 200, w: 150, h: 120 }, tgt = { x: 1000, y: 210, w: 150, h: 110 };
  const O = { x: 452, y: 130, w: 220, h: 260 };   // collé au bord droit de src (src.right = 450)
  const r = C.routeAvoiding(src, 'right', tgt, 'left', [O]);
  assert.equal(C.pathHits(r.pts, [O]), false);
  assert.notEqual(r.srcSide, 'right');            // a dû changer de face source
  assert.ok(all45(r.pts));
});

// --- anti-superposition des câbles (ruban) : segOverlap / cablesOverlap ---

test('segOverlap: parallèles proches qui se recouvrent vs loin vs croisement', () => {
  const G = C.RIBBON_GAP;
  const a0 = { x: 0, y: 0 }, a1 = { x: 100, y: 0 };          // horizontal
  // parallèle, à 5px (< RIBBON_GAP), recouvrement -> true
  assert.equal(C.segOverlap(a0, a1, { x: 20, y: 5 }, { x: 120, y: 5 }, G), true);
  // parallèle mais à 40px (> RIBBON_GAP) -> false
  assert.equal(C.segOverlap(a0, a1, { x: 20, y: 40 }, { x: 120, y: 40 }, G), false);
  // même droite mais bout-à-bout (pas de recouvrement) -> false
  assert.equal(C.segOverlap(a0, a1, { x: 200, y: 0 }, { x: 300, y: 0 }, G), false);
  // croisement (perpendiculaire) -> false (toléré)
  assert.equal(C.segOverlap(a0, a1, { x: 50, y: -50 }, { x: 50, y: 50 }, G), false);
});

test('cablesOverlap: deux câbles quasi-confondus vs croisement', () => {
  const G = C.RIBBON_GAP;
  const c1 = C.subwayPoints({ x: 0, y: 0 }, 'right', { x: 400, y: 200 }, 'left');
  const close = C.subwayPoints({ x: 0, y: 6 }, 'right', { x: 400, y: 206 }, 'left');  // ~6px à côté
  const crossing = C.subwayPoints({ x: 0, y: 200 }, 'right', { x: 400, y: 0 }, 'left'); // pente opposée
  assert.equal(C.cablesOverlap(c1, close, G), true);
  assert.equal(C.cablesOverlap(c1, crossing, G), false);
});

// --- pathBetween : chemin orienté dans l'arbre source_id (impulsions) ---
const TREE = {
  k: { id: 'k', source: null },
  e: { id: 'e', source: 'k' },
  a: { id: 'a', source: 'e' },
  b: { id: 'b', source: 'e' },
};
test('pathBetween: from==to -> []', () => {
  assert.deepEqual(C.pathBetween(TREE, 'a', 'a'), []);
});
test('pathBetween: descente pure kernel -> feuille', () => {
  assert.deepEqual(C.pathBetween(TREE, 'k', 'a'),
    [{ childId: 'e', parentId: 'k', dir: 'down' }, { childId: 'a', parentId: 'e', dir: 'down' }]);
});
test('pathBetween: montée pure feuille -> kernel', () => {
  assert.deepEqual(C.pathBetween(TREE, 'a', 'k'),
    [{ childId: 'a', parentId: 'e', dir: 'up' }, { childId: 'e', parentId: 'k', dir: 'up' }]);
});
test('pathBetween: frère -> frère (montée puis descente via LCA)', () => {
  assert.deepEqual(C.pathBetween(TREE, 'a', 'b'),
    [{ childId: 'a', parentId: 'e', dir: 'up' }, { childId: 'b', parentId: 'e', dir: 'down' }]);
});
test('pathBetween: composantes disjointes -> null', () => {
  assert.equal(C.pathBetween({ a: { id: 'a', source: null }, b: { id: 'b', source: null } }, 'a', 'b'), null);
});
test('pathBetween: cycle -> null (pas de boucle infinie)', () => {
  assert.equal(C.pathBetween({ a: { id: 'a', source: 'b' }, b: { id: 'b', source: 'a' } }, 'a', 'b'), null);
});
