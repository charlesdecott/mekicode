/* Vendoré de mekistudio (frontend/static/js) — géométrie pure, ne pas diverger sans raison. */
// Géométrie PURE de l'anti-collision (boîtes {x,y,w,h}, coords monde). Script classique :
// exposé pour le navigateur (window.MekiCollision) et pour node --test.
(function () {
  const GAP = 12;  // marge anti-contact + respiration (px monde)
  const EPS = 4;   // hystérésis : on relâche un node écarté au-delà de GAP+EPS

  function intersects(a, b, gap) {
    gap = gap || 0;
    return a.x < b.x + b.w + gap && b.x < a.x + a.w + gap
        && a.y < b.y + b.h + gap && b.y < a.y + a.h + gap;
  }
  function isFree(box, others, gap) {
    return !others.some((o) => intersects(box, o, gap));
  }

  // Déplacements (±) à appliquer à `obstacle` pour le sortir du couloir de `mover`, le long
  // de l'axe de pénétration MINIMALE (perpendiculaire au drag en cas d'égalité ~45°).
  // Renvoie 2 candidats, le plus court d'abord (départage : côté naturel).
  function partVector(mover, obstacle, dragDir, gap) {
    gap = gap || 0;
    const oxl = Math.min(mover.x + mover.w, obstacle.x + obstacle.w) - Math.max(mover.x, obstacle.x);
    const oyl = Math.min(mover.y + mover.h, obstacle.y + obstacle.h) - Math.max(mover.y, obstacle.y);
    let axis = oxl <= oyl ? 'x' : 'y';
    if (Math.abs(oxl - oyl) < 1 && dragDir) {
      axis = Math.abs(dragDir.x) >= Math.abs(dragDir.y) ? 'y' : 'x';  // perpendiculaire au drag
    }
    if (axis === 'y') {
      const up = (mover.y - gap) - (obstacle.y + obstacle.h);          // < 0 (monte l'obstacle)
      const down = (mover.y + mover.h + gap) - obstacle.y;             // > 0 (descend)
      const natural = (obstacle.y + obstacle.h / 2) >= (mover.y + mover.h / 2) ? 1 : -1;
      const cands = [{ x: 0, y: up }, { x: 0, y: down }];
      cands.sort((a, b) => (Math.abs(a.y) - Math.abs(b.y)) || (natural > 0 ? a.y - b.y : b.y - a.y));
      return cands;
    }
    const left = (mover.x - gap) - (obstacle.x + obstacle.w);          // < 0
    const right = (mover.x + mover.w + gap) - obstacle.x;              // > 0
    const natural = (obstacle.x + obstacle.w / 2) >= (mover.x + mover.w / 2) ? 1 : -1;
    const cands = [{ x: left, y: 0 }, { x: right, y: 0 }];
    cands.sort((a, b) => (Math.abs(a.x) - Math.abs(b.x)) || (natural > 0 ? a.x - b.x : b.x - a.x));
    return cands;
  }

  // MTV pour sortir `obstacle` d'un `grower` qui s'agrandit vers le bas-droite
  // (composantes négatives interdites). Renvoie le plus petit push autorisé.
  function pushVector(grower, obstacle, gap) {
    gap = gap || 0;
    const right = (grower.x + grower.w + gap) - obstacle.x;
    const down = (grower.y + grower.h + gap) - obstacle.y;
    return right <= down ? { x: right, y: 0 } : { x: 0, y: down };
  }

  // Borne `mover` (taille dans dragTo.w/h) au contact de `obstacle` : bloque l'axe de
  // pénétration MIN, laisse glisser l'autre. Renvoie la position bornée {x,y}.
  function clampAgainst(moverHome, dragTo, obstacle, gap) {
    gap = gap || 0;
    const w = dragTo.w, h = dragTo.h;
    const b = { x: dragTo.x, y: dragTo.y, w, h };
    if (!intersects(b, obstacle, gap)) return { x: dragTo.x, y: dragTo.y };
    const penX = Math.min(b.x + w, obstacle.x + obstacle.w) - Math.max(b.x, obstacle.x) + gap;
    const penY = Math.min(b.y + h, obstacle.y + obstacle.h) - Math.max(b.y, obstacle.y) + gap;
    let nx = dragTo.x, ny = dragTo.y;
    // côté de blocage = côté d'APPROCHE (home), pas la position courante (déjà pénétrée).
    if (penX <= penY) {
      nx = (moverHome.x + w / 2 <= obstacle.x + obstacle.w / 2)
        ? obstacle.x - gap - w : obstacle.x + obstacle.w + gap;
    } else {
      ny = (moverHome.y + h / 2 <= obstacle.y + obstacle.h / 2)
        ? obstacle.y - gap - h : obstacle.y + obstacle.h + gap;
    }
    return { x: nx, y: ny };
  }

  function minDist(b, others) {
    if (!others.length) return Infinity;
    let m = Infinity;
    for (const o of others) {
      const dx = Math.max(o.x - (b.x + b.w), b.x - (o.x + o.w), 0);
      const dy = Math.max(o.y - (b.y + b.h), b.y - (o.y + o.h), 0);
      m = Math.min(m, Math.hypot(dx, dy));
    }
    return m;
  }
  // 1er emplacement libre en spirale carrée autour de `anchor` ; repli déterministe
  // (le plus éloigné des autres dans le cap) si rien de libre. Jamais de boucle infinie.
  function findFreeSpot(anchor, size, others, gap) {
    gap = gap || 0;
    const at = (x, y) => ({ x, y, w: size.w, h: size.h });
    if (isFree(at(anchor.x, anchor.y), others, gap)) return { x: anchor.x, y: anchor.y };
    const step = Math.max(size.w, size.h) + gap;
    const CAP = 60;
    let best = null, bestD = -1;
    for (let r = 1; r <= CAP; r++) {
      for (let dy = -r; dy <= r; dy++) {
        for (let dx = -r; dx <= r; dx++) {
          if (Math.max(Math.abs(dx), Math.abs(dy)) !== r) continue;  // anneau de rayon r
          const x = anchor.x + dx * step, y = anchor.y + dy * step;
          if (isFree(at(x, y), others, gap)) return { x, y };
          const d = minDist(at(x, y), others);
          if (d > bestD) { bestD = d; best = { x, y }; }
        }
      }
    }
    return best || { x: anchor.x, y: anchor.y };
  }

  const MekiCollision = { GAP, EPS, intersects, isFree, partVector, pushVector, clampAgainst, findFreeSpot };
  if (typeof module !== 'undefined' && module.exports) module.exports = MekiCollision;
  if (typeof window !== 'undefined') window.MekiCollision = MekiCollision;
})();
