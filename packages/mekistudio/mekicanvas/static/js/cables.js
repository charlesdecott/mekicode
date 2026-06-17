/* Vendoré de mekistudio (frontend/static/js) — géométrie pure, ne pas diverger sans raison. */
// Géométrie PURE des câbles (subway 45° adaptatif + ruban). Script classique :
// exposé à la fois pour le navigateur (window.MekiCables) et pour node --test.
(function () {
  const STUB = 18;       // sortie perpendiculaire avant le connecteur (px monde)
  const GAP_LANE = 12;   // espacement de base entre lanes d'un même (node, côté)
  const MARGE = 10;      // garde une ancre sur la face du node
  const HIDE_DIST = 24;  // sous ce centre-à-centre, on masque le câble
  const RIBBON_GAP = 20; // écart mini entre deux câbles parallèles (anti-superposition)

  const cx = (b) => b.x + b.w / 2;
  const cy = (b) => b.y + b.h / 2;
  const sideLength = (b, side) => (side === 'left' || side === 'right') ? b.h : b.w;

  // Côté de sortie de a vers b par axe dominant des centres ; tie -> horizontal.
  function adaptiveSide(a, b) {
    const dx = cx(b) - cx(a), dy = cy(b) - cy(a);
    if (Math.abs(dx) >= Math.abs(dy)) return dx >= 0 ? 'right' : 'left';
    return dy >= 0 ? 'bottom' : 'top';
  }

  // Point d'ancrage sur un côté, décalé de off le long de la tangente, clampé.
  function sideAnchor(b, side, off) {
    const lim = Math.max(0, sideLength(b, side) / 2 - MARGE);
    const o = Math.max(-lim, Math.min(lim, off));
    switch (side) {
      case 'right': return { x: b.x + b.w, y: cy(b) + o };
      case 'left':  return { x: b.x,       y: cy(b) + o };
      case 'top':   return { x: cx(b) + o, y: b.y };
      default:      return { x: cx(b) + o, y: b.y + b.h }; // bottom
    }
  }

  // Attribue des offsets de lane (centrés) aux câbles partageant (node, côté).
  // cables: [{ neighbor:{x,y,w,h} }] ; retourne les offsets dans l'ordre d'entrée.
  function assignLanes(cables, box, side) {
    const n = cables.length;
    if (n <= 1) return cables.map(() => 0);
    const tan = (side === 'left' || side === 'right')
      ? (c) => cy(c.neighbor) : (c) => cx(c.neighbor);
    const order = cables.map((_, i) => i).sort((i, j) => tan(cables[i]) - tan(cables[j]));
    const gap = Math.min(GAP_LANE, (sideLength(box, side) - 2 * MARGE) / (n - 1));
    const offs = new Array(n);
    order.forEach((origIdx, rank) => { offs[origIdx] = (rank - (n - 1) / 2) * gap; });
    return offs;
  }

  function stubOut(p, side, len) {
    switch (side) {
      case 'right': return { x: p.x + len, y: p.y };
      case 'left':  return { x: p.x - len, y: p.y };
      case 'top':   return { x: p.x, y: p.y - len };
      default:      return { x: p.x, y: p.y + len };
    }
  }

  // Connecteur entre 2 points : segment droit + UNE diagonale 45° (longueur =
  // min(|dx|,|dy|)) + segment droit. La diagonale ne déborde jamais.
  function subwayConnect(B, P) {
    const dx = P.x - B.x, dy = P.y - B.y;
    const adx = Math.abs(dx), ady = Math.abs(dy);
    const sx = Math.sign(dx) || 1, sy = Math.sign(dy) || 1;
    if (adx >= ady) {                  // horizontal dominant : H - diag - H
      const m1 = { x: B.x + sx * (adx - ady) / 2, y: B.y };
      const m2 = { x: m1.x + sx * ady, y: P.y };
      return [B, m1, m2, P];
    }
    const m1 = { x: B.x, y: B.y + sy * (ady - adx) / 2 }; // vertical dominant : V - diag - V
    const m2 = { x: P.x, y: m1.y + sy * adx };
    return [B, m1, m2, P];
  }

  // Tracé complet : ancre -> stub ⟂ -> connecteur -> stub ⟂ -> ancre.
  // anchorA / anchorB sont DÉJÀ décalés (offsets de lane inclus).
  function subwayPoints(anchorA, sideA, anchorB, sideB) {
    const B = stubOut(anchorA, sideA, STUB);
    const P = stubOut(anchorB, sideB, STUB);
    return [anchorA].concat(subwayConnect(B, P)).concat([anchorB]);
  }

  function pointsToPath(pts) {
    return 'M ' + pts.map((p) => p.x.toFixed(1) + ' ' + p.y.toFixed(1)).join(' L ');
  }

  // Couleur du câble selon la RELATION (brique G) : git / explorateur→dossier-de-profondeur-1 /
  // dossier→dossier / fichier→(n'importe quoi). L'ordre compte (git d'abord, puis fichier).
  function cableClass(kindChild, kindParent) {
    if (kindChild === 'gitbranch' || kindParent === 'gitbranch') return 'cab-git';      // câbles de la node branche git
    if (kindChild === 'fileeditor') return 'cab-file';                                   // tout câble reliant un fichier
    if (kindChild === 'folder' && kindParent === 'fileexplorer') return 'cab-d1';        // explorateur → dossier profondeur 1
    if (kindChild === 'folder' && kindParent === 'folder') return 'cab-folder';          // dossier → dossier
    return 'cable-default';
  }

  // --- Raffinements routage : contournement d'obstacles + anti-superposition ---

  function pathLength(pts) {
    let L = 0;
    for (let i = 1; i < pts.length; i++) L += Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y);
    return L;
  }

  // Le segment p->q traverse-t-il la boîte b (AABB) ? Liang-Barsky (graze = hit -> routage prudent).
  function segHitsBox(p, q, b) {
    let t0 = 0, t1 = 1;
    const dx = q.x - p.x, dy = q.y - p.y;
    const checks = [[-dx, p.x - b.x], [dx, (b.x + b.w) - p.x], [-dy, p.y - b.y], [dy, (b.y + b.h) - p.y]];
    for (const [pk, qk] of checks) {
      if (pk === 0) { if (qk < 0) return false; continue; }   // parallèle & dehors
      const r = qk / pk;
      if (pk < 0) { if (r > t1) return false; if (r > t0) t0 = r; }
      else { if (r < t0) return false; if (r < t1) t1 = r; }
    }
    return t0 <= t1;
  }

  function pathHits(pts, boxes) {
    for (let i = 1; i < pts.length; i++)
      for (const b of boxes)
        if (segHitsBox(pts[i - 1], pts[i], b)) return true;
    return false;
  }

  // Réflexion x<->y : traiter le cas vertical-dominant via le cas horizontal.
  const swapPt = (p) => ({ x: p.y, y: p.x });
  const swapBox = (b) => ({ x: b.y, y: b.x, w: b.h, h: b.w });
  const swapSide = (s) => ({ top: 'left', left: 'top', bottom: 'right', right: 'bottom' }[s]);

  // Contournement horizontal-dominant "up-and-over" à 45° autour de l'UNION des
  // obstacles touchés. Renvoie un tracé dégagé, ou null si aucun couloir ne passe.
  function routeAroundH(aA, sA, aB, sB, obstacles) {
    const straight = subwayPoints(aA, sA, aB, sB);
    const hit = obstacles.filter((b) => pathHits(straight, [b]));
    if (!hit.length) return straight;
    const ux0 = Math.min(...hit.map((b) => b.x)), uy0 = Math.min(...hit.map((b) => b.y));
    const ux1 = Math.max(...hit.map((b) => b.x + b.w)), uy1 = Math.max(...hit.map((b) => b.y + b.h));
    const B = stubOut(aA, sA, STUB), P = stubOut(aB, sB, STUB);
    const G = STUB;
    const sx = Math.sign(P.x - B.x) || 1;
    const xNearB = sx > 0 ? ux0 - G : ux1 + G;   // bord de l'union côté B
    const xNearP = sx > 0 ? ux1 + G : ux0 - G;   // bord de l'union côté P
    let best = null, bl = Infinity;
    for (const yC of [uy0 - G, uy1 + G]) {        // couloir au-dessus / en dessous
      const riseL = Math.abs(yC - B.y), riseR = Math.abs(yC - P.y);
      if (sx * (xNearB - B.x) < riseL - 0.01) continue;  // pas la place pour la montée côté B
      if (sx * (P.x - xNearP) < riseR - 0.01) continue;  // ni côté P
      const pts = [aA, B,
        { x: xNearB - sx * riseL, y: B.y }, { x: xNearB, y: yC },   // montée 45° finie avant l'union
        { x: xNearP, y: yC }, { x: xNearP + sx * riseR, y: P.y },   // couloir puis descente 45°
        P, aB];
      if (pathHits(pts, obstacles)) continue;
      const l = pathLength(pts);
      if (l < bl) { bl = l; best = pts; }
    }
    return best;
  }

  // Contournement : tracé subway qui évite les boîtes `obstacles`. Repli gracieux
  // sur le tracé direct si rien ne dégage (jamais de crash).
  function routeAround(aA, sA, aB, sB, obstacles) {
    const straight = subwayPoints(aA, sA, aB, sB);
    if (!obstacles || !obstacles.length || !pathHits(straight, obstacles)) return straight;
    const B = stubOut(aA, sA, STUB), P = stubOut(aB, sB, STUB);
    if (Math.abs(P.x - B.x) >= Math.abs(P.y - B.y)) {
      return routeAroundH(aA, sA, aB, sB, obstacles) || straight;
    }
    const r = routeAroundH(swapPt(aA), swapSide(sA), swapPt(aB), swapSide(sB), obstacles.map(swapBox));
    return r ? r.map(swapPt) : straight;
  }

  // Diagonale (segment ni H ni V) d'un tracé, ou null.
  function diagOf(pts) {
    for (let i = 1; i < pts.length; i++) {
      const dx = pts[i].x - pts[i - 1].x, dy = pts[i].y - pts[i - 1].y;
      if (Math.abs(dx) > 1e-6 && Math.abs(dy) > 1e-6) return [pts[i - 1], pts[i]];
    }
    return null;
  }

  // Deux diagonales 45° se confondent-elles (même droite à eps près + projections qui se chevauchent) ?
  function diagsOverlap(d1, d2, eps) {
    eps = eps == null ? 4 : eps;
    if (!d1 || !d2) return false;
    const s1x = Math.sign(d1[1].x - d1[0].x), s1y = Math.sign(d1[1].y - d1[0].y);
    const s2x = Math.sign(d2[1].x - d2[0].x), s2y = Math.sign(d2[1].y - d2[0].y);
    if (s1x !== s2x || s1y !== s2y) return false;            // orientation 45° différente
    const inv = (p) => (s1x === s1y) ? p.x - p.y : p.x + p.y; // invariant de la droite 45°
    if (Math.abs(inv(d1[0]) - inv(d2[0])) > eps * Math.SQRT2) return false;
    const lo1 = Math.min(d1[0].x, d1[1].x), hi1 = Math.max(d1[0].x, d1[1].x);
    const lo2 = Math.min(d2[0].x, d2[1].x), hi2 = Math.max(d2[0].x, d2[1].x);
    return Math.min(hi1, hi2) - Math.max(lo1, lo2) > eps;
  }

  function segBBox(p, q) {
    return { x: Math.min(p.x, q.x), y: Math.min(p.y, q.y), w: Math.abs(q.x - p.x), h: Math.abs(q.y - p.y) };
  }
  function bboxesOverlap(a, b, pad) {
    pad = pad || 0;
    return a.x - pad < b.x + b.w + pad && b.x - pad < a.x + a.w + pad
        && a.y - pad < b.y + b.h + pad && b.y - pad < a.y + a.h + pad;
  }

  // Tracé 45° dégageant les obstacles, ou null si aucun couloir 45° (pas de repli straight).
  function route45OrNull(aA, sA, aB, sB, obstacles) {
    const straight = subwayPoints(aA, sA, aB, sB);
    if (!pathHits(straight, obstacles)) return straight;
    const B = stubOut(aA, sA, STUB), P = stubOut(aB, sB, STUB);
    if (Math.abs(P.x - B.x) >= Math.abs(P.y - B.y)) return routeAroundH(aA, sA, aB, sB, obstacles);
    const r = routeAroundH(swapPt(aA), swapSide(sA), swapPt(aB), swapSide(sB), obstacles.map(swapBox));
    return r ? r.map(swapPt) : null;
  }

  // Essaie la face naturelle, puis CHANGE la face de la node concernée (haut/bas/…) pour
  // contourner en pur 45° ; garde le tracé qui dégage le plus court (petite pénalité par
  // face changée). Repli (hit=true) seulement si AUCUNE face ne dégage. {pts, srcSide, tgtSide, hit}
  function routeAvoiding(srcBox, baseSrc, tgtBox, baseTgt, obstacles) {
    const faces = ['right', 'left', 'top', 'bottom'];
    const cand = [[baseSrc, baseTgt]];
    for (const s of faces) if (s !== baseSrc) cand.push([s, baseTgt]);          // change la sortie source
    for (const t of faces) if (t !== baseTgt) cand.push([baseSrc, t]);          // change l'entrée cible
    for (const s of faces) for (const t of faces) if (s !== baseSrc && t !== baseTgt) cand.push([s, t]);
    let best = null, bestScore = Infinity, bestSides = null;
    for (const [ss, ts] of cand) {
      const r = route45OrNull(sideAnchor(srcBox, ss, 0), ss, sideAnchor(tgtBox, ts, 0), ts, obstacles);
      if (!r || pathHits(r, obstacles)) continue;
      const changes = (ss !== baseSrc ? 1 : 0) + (ts !== baseTgt ? 1 : 0);
      const score = pathLength(r) + changes * 40; // court d'abord ; pénalise un changement de face
      if (score < bestScore) { bestScore = score; best = r; bestSides = [ss, ts]; }
    }
    if (best) return { pts: best, srcSide: bestSides[0], tgtSide: bestSides[1], hit: false };
    const sA = sideAnchor(srcBox, baseSrc, 0), sB = sideAnchor(tgtBox, baseTgt, 0);
    return { pts: subwayPoints(sA, baseSrc, sB, baseTgt), srcSide: baseSrc, tgtSide: baseTgt, hit: true };
  }

  // Deux segments PARALLÈLES, plus proches que minSep (distance perpendiculaire), dont les
  // projections se recouvrent → ils se « confondent » (ruban trop serré). Pentes différentes
  // (croisement ponctuel) → false (toléré).
  function segOverlap(p1, q1, p2, q2, minSep) {
    const d1x = q1.x - p1.x, d1y = q1.y - p1.y, l1 = Math.hypot(d1x, d1y);
    const d2x = q2.x - p2.x, d2y = q2.y - p2.y, l2 = Math.hypot(d2x, d2y);
    if (l1 < 1 || l2 < 1) return false;
    if (Math.abs(d1x * d2y - d1y * d2x) / (l1 * l2) > 0.08) return false;     // pas parallèle → croisement
    const perp = Math.abs((p2.x - p1.x) * d1y - (p2.y - p1.y) * d1x) / l1;
    if (perp >= minSep) return false;                                        // assez écartés
    const t = (p) => ((p.x - p1.x) * d1x + (p.y - p1.y) * d1y) / (l1 * l1);
    let b0 = t(p2), b1 = t(q2); if (b0 > b1) { const k = b0; b0 = b1; b1 = k; }
    const lo = Math.max(0, b0), hi = Math.min(1, b1);
    return (hi - lo) * l1 > minSep;                                          // recouvrement significatif
  }

  // Deux câbles (suites de points) se confondent-ils sur une portion ? (pré-filtre bbox côté appelant)
  function cablesOverlap(c1, c2, minSep) {
    for (let i = 1; i < c1.length; i++) {
      if (Math.hypot(c1[i].x - c1[i - 1].x, c1[i].y - c1[i - 1].y) < 2) continue;
      for (let j = 1; j < c2.length; j++) {
        if (Math.hypot(c2[j].x - c2[j - 1].x, c2[j].y - c2[j - 1].y) < 2) continue;
        if (segOverlap(c1[i - 1], c1[i], c2[j - 1], c2[j], minSep)) return true;
      }
    }
    return false;
  }

  // Chaîne d'ancêtres [id, parent, ..., racine] via source_id ; null si cycle.
  function ancestorChain(nodesById, id) {
    const chain = [], seen = new Set();
    let cur = id;
    while (cur != null && nodesById[cur]) {
      if (seen.has(cur)) return null; // cycle
      seen.add(cur);
      chain.push(cur);
      cur = nodesById[cur].source || null;
    }
    return chain;
  }

  // Câbles ORIENTÉS du chemin from->to : {childId, parentId, dir} (dir='up' enfant->parent
  // en montée, 'down' parent->enfant en descente). [] si from==to ; null si disjoint ou cycle.
  function pathBetween(nodesById, fromId, toId) {
    if (fromId === toId) return [];
    const a = ancestorChain(nodesById, fromId);
    const b = ancestorChain(nodesById, toId);
    if (!a || !b) return null;
    const bIdx = new Map(b.map((id, i) => [id, i]));
    let ia = -1, ib = -1;
    for (let i = 0; i < a.length; i++) {
      if (bIdx.has(a[i])) { ia = i; ib = bIdx.get(a[i]); break; }
    }
    if (ia === -1) return null; // pas d'ancêtre commun -> composantes disjointes
    const segs = [];
    for (let i = 0; i < ia; i++) segs.push({ childId: a[i], parentId: a[i + 1], dir: 'up' });
    for (let i = ib - 1; i >= 0; i--) segs.push({ childId: b[i], parentId: b[i + 1], dir: 'down' });
    return segs;
  }

  const MekiCables = {
    STUB, GAP_LANE, MARGE, HIDE_DIST, RIBBON_GAP, adaptiveSide, sideAnchor, assignLanes, subwayPoints, pointsToPath, cableClass,
    segHitsBox, pathHits, routeAround, diagOf, diagsOverlap, segBBox, bboxesOverlap,
    route45OrNull, routeAvoiding, segOverlap, cablesOverlap, pathBetween,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = MekiCables;
  if (typeof window !== 'undefined') window.MekiCables = MekiCables;
})();
