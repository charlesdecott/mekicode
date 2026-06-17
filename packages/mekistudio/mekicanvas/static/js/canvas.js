/* canvas.js — pont NiceGUI <-> géométrie vendorée.
 * Les nodes sont des .node-wrap NiceGUI (position absolue, coords MONDE via style.left/top)
 * dans .mc-world (div transformée pan/zoom). Cette couche : pan/zoom, câbles SVG 45°, comètes.
 * API exposée : window.MekiCanvas.{initWorld, redraw, impulse, fitView}. */
(function () {
  const SVGNS = 'http://www.w3.org/2000/svg';
  const state = { view: { x: 0, y: 0, zoom: 1 }, panning: false, last: { x: 0, y: 0 }, pulses: 0 };

  const canvasEl = () => document.querySelector('.mc-canvas');
  const worldEl = () => document.querySelector('.mc-world');

  function applyTransform() {
    const w = worldEl(); if (!w) return;
    w.style.transform = `translate(${state.view.x}px, ${state.view.y}px) scale(${state.view.zoom})`;
    // facteur de "densité de texte" du chat : au zoom-in (zoom>1), le contenu chat est mis en page
    // dans une zone plus large puis contre-scalé → police écran ~constante, MAIS plus de texte par
    // ligne (moins de retours à la ligne). Au zoom-out (zoom<=1) : facteur 1 = comportement normal.
    w.style.setProperty('--mc-f', String(Math.max(1, state.view.zoom)));
    const cv = canvasEl();
    if (cv) {
      const s = 40 * state.view.zoom;
      cv.style.backgroundSize = `${s}px ${s}px`;
      cv.style.backgroundPosition = `${state.view.x}px ${state.view.y}px`;
    }
  }

  function nodeBoxes() {
    const map = new Map();
    document.querySelectorAll('.node-wrap').forEach((wrap) => {
      map.set(wrap.dataset.id, {
        box: { x: parseFloat(wrap.style.left) || 0, y: parseFloat(wrap.style.top) || 0,
               w: wrap.offsetWidth, h: wrap.offsetHeight },
        kind: wrap.dataset.kind || '', source: wrap.dataset.source || '',
      });
    });
    return map;
  }

  function ensureCablesLayer() {
    const world = worldEl(); if (!world) return null;
    let svg = world.querySelector('svg.cables');
    if (!svg) { svg = document.createElementNS(SVGNS, 'svg'); svg.setAttribute('class', 'cables'); }
    if (world.firstChild !== svg) world.insertBefore(svg, world.firstChild);
    return svg;
  }

  function redraw() {
    const C = window.MekiCables; const svg = ensureCablesLayer();
    if (!svg || !C) return;
    const nodes = nodeBoxes();
    const cables = [];
    nodes.forEach((info, id) => {
      if (info.source && nodes.has(info.source)) cables.push({ id, parent: info.source });
    });
    const sides = cables.map((cab) => ({
      child: C.adaptiveSide(nodes.get(cab.id).box, nodes.get(cab.parent).box),
      parent: C.adaptiveSide(nodes.get(cab.parent).box, nodes.get(cab.id).box),
    }));
    // lanes : regroupe par (node, côté)
    const groups = new Map();
    const push = (k, v) => { if (!groups.has(k)) groups.set(k, []); groups.get(k).push(v); };
    cables.forEach((cab, i) => {
      push(cab.id + '|' + sides[i].child, { neighbor: nodes.get(cab.parent).box, i, end: 'c' });
      push(cab.parent + '|' + sides[i].parent, { neighbor: nodes.get(cab.id).box, i, end: 'p' });
    });
    const offC = new Array(cables.length).fill(0), offP = new Array(cables.length).fill(0);
    groups.forEach((list, key) => {
      const idx = key.lastIndexOf('|');
      const nid = key.slice(0, idx), side = key.slice(idx + 1);
      const offs = C.assignLanes(list, nodes.get(nid).box, side);
      list.forEach((item, j) => { if (item.end === 'c') offC[item.i] = offs[j]; else offP[item.i] = offs[j]; });
    });
    const seen = new Set();
    cables.forEach((cab, i) => {
      const a = nodes.get(cab.id), b = nodes.get(cab.parent);
      const dcx = (a.box.x + a.box.w / 2) - (b.box.x + b.box.w / 2);
      const dcy = (a.box.y + a.box.h / 2) - (b.box.y + b.box.h / 2);
      if (Math.hypot(dcx, dcy) < C.HIDE_DIST) return;
      const obstacles = [];
      nodes.forEach((info, oid) => {
        if (oid === cab.id || oid === cab.parent) return;
        const o = info.box;
        obstacles.push({ x: o.x - C.STUB, y: o.y - C.STUB, w: o.w + 2 * C.STUB, h: o.h + 2 * C.STUB });
      });
      let s = sides[i];
      const aA = C.sideAnchor(a.box, s.child, offC[i]);
      const aB = C.sideAnchor(b.box, s.parent, offP[i]);
      let route = C.routeAround(aA, s.child, aB, s.parent, obstacles);
      if (obstacles.length && C.pathHits(route, obstacles)) {
        const av = C.routeAvoiding(a.box, s.child, b.box, s.parent, obstacles);
        route = av.pts;
      }
      const d = C.pointsToPath(route);
      const cls = C.cableClass(a.kind, b.kind);
      let g = svg.querySelector(`g[data-edge="${cab.id}"]`);
      if (!g) {
        g = document.createElementNS(SVGNS, 'g'); g.setAttribute('data-edge', cab.id);
        const halo = document.createElementNS(SVGNS, 'path'); halo.setAttribute('class', 'cable-halo');
        const core = document.createElementNS(SVGNS, 'path'); core.setAttribute('class', 'cable-core ' + cls);
        g.appendChild(halo); g.appendChild(core); svg.appendChild(g);
      } else {
        g.querySelector('.cable-core').setAttribute('class', 'cable-core ' + cls);
      }
      g.querySelectorAll('path').forEach((p) => p.setAttribute('d', d));
      seen.add(cab.id);
    });
    svg.querySelectorAll('g[data-edge]').forEach((g) => {
      if (!seen.has(g.getAttribute('data-edge'))) g.remove();
    });
  }

  function fitView() {
    const nodes = nodeBoxes(); const cv = canvasEl();
    if (!nodes.size || !cv) return;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    nodes.forEach((info) => {
      x0 = Math.min(x0, info.box.x); y0 = Math.min(y0, info.box.y);
      x1 = Math.max(x1, info.box.x + info.box.w); y1 = Math.max(y1, info.box.y + info.box.h);
    });
    const rect = cv.getBoundingClientRect(); const pad = 90;
    const bw = Math.max(1, x1 - x0), bh = Math.max(1, y1 - y0);
    const zoom = Math.min(4, Math.max(0.2, Math.min((rect.width - pad) / bw, (rect.height - pad) / bh, 1.1)));
    state.view.zoom = zoom;
    state.view.x = rect.width / 2 - (x0 + bw / 2) * zoom;
    state.view.y = rect.height / 2 - (y0 + bh / 2) * zoom;
  }

  // positions persistées côté client (drag des nodes), par id de node stable
  const POS_KEY = 'meki:canvas:pos';
  function loadPos() { try { return JSON.parse(localStorage.getItem(POS_KEY) || '{}'); } catch (e) { return {}; } }
  function savePos(id, x, y) {
    const p = loadPos(); p[id] = { x, y };
    try { localStorage.setItem(POS_KEY, JSON.stringify(p)); } catch (e) { /* quota */ }
  }
  function applySaved() {
    const p = loadPos();
    document.querySelectorAll('.node-wrap').forEach((w) => {
      const s = p[w.dataset.id];
      if (s) { w.style.left = s.x + 'px'; w.style.top = s.y + 'px'; }
    });
  }

  function initWorld() {
    const cv = canvasEl(); if (!cv) return;
    if (cv._mekiInit) { applySaved(); fitView(); applyTransform(); redraw(); return; }
    cv._mekiInit = true;
    let drag = null;
    cv.addEventListener('mousedown', (e) => {
      const head = e.target.closest('.nhead');
      if (head && !e.target.closest('.focus-dot')) {            // poignée = en-tête (hors pastille focus)
        const wrap = head.closest('.node-wrap');
        if (wrap) {
          e.preventDefault();
          drag = { wrap, sx: e.clientX, sy: e.clientY,
                   ox: parseFloat(wrap.style.left) || 0, oy: parseFloat(wrap.style.top) || 0, moved: false };
          wrap.classList.add('dragging');
          return;
        }
      }
      if (e.target.closest('.node-wrap')) return;                // clic dans le corps d'une node → ni pan ni drag
      state.panning = true; state.last = { x: e.clientX, y: e.clientY }; cv.classList.add('panning');
    });
    window.addEventListener('mousemove', (e) => {
      if (drag) {
        const z = state.view.zoom || 1;
        drag.wrap.style.left = (drag.ox + (e.clientX - drag.sx) / z) + 'px';
        drag.wrap.style.top = (drag.oy + (e.clientY - drag.sy) / z) + 'px';
        drag.moved = true; redraw(); return;
      }
      if (!state.panning) return;
      state.view.x += e.clientX - state.last.x; state.view.y += e.clientY - state.last.y;
      state.last = { x: e.clientX, y: e.clientY }; applyTransform();
    });
    window.addEventListener('mouseup', () => {
      if (drag) {
        drag.wrap.classList.remove('dragging');
        if (drag.moved) savePos(drag.wrap.dataset.id, parseFloat(drag.wrap.style.left) || 0, parseFloat(drag.wrap.style.top) || 0);
        drag = null; return;
      }
      state.panning = false; cv.classList.remove('panning');
    });
    cv.addEventListener('wheel', (e) => {
      // molette à l'intérieur d'un chat → on laisse défiler le fil de CE chat (scroll natif), pas de zoom
      if (e.target.closest('.nbody-chat')) return;
      e.preventDefault();
      const f = e.deltaY < 0 ? 1.1 : 0.9;
      const nz = Math.min(4, Math.max(0.2, state.view.zoom * f));
      const rect = cv.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const wx = (mx - state.view.x) / state.view.zoom, wy = (my - state.view.y) / state.view.zoom;
      state.view.x = mx - wx * nz; state.view.y = my - wy * nz; state.view.zoom = nz; applyTransform();
    }, { passive: false });
    applySaved(); fitView(); applyTransform(); redraw();
  }

  // --- impulsions ---
  const kindId = (kind) => {
    const w = document.querySelector(`.node-wrap[data-kind="${kind}"]`); return w ? w.dataset.id : null;
  };
  const center = (id) => {
    const w = document.querySelector(`.node-wrap[data-id="${id}"]`); if (!w) return null;
    return { x: (parseFloat(w.style.left) || 0) + w.offsetWidth / 2,
             y: (parseFloat(w.style.top) || 0) + w.offsetHeight / 2 };
  };
  function glow(id, level, ms) {
    const w = document.querySelector(`.node-wrap[data-id="${id}"]`); if (!w) return;
    ['glow-soft', 'glow-strong', 'glow-error', 'glow-notif'].forEach((c) => w.classList.remove(c));
    w.classList.add('glow-' + level);
    if (ms > 0) setTimeout(() => w.classList.remove('glow-' + level), ms);
  }
  function animateComet(seg) {
    return new Promise((resolve) => {
      const svg = ensureCablesLayer();
      const from = center(seg.dir === 'up' ? seg.childId : seg.parentId);
      const to = center(seg.dir === 'up' ? seg.parentId : seg.childId);
      if (!svg || !from || !to) { resolve(); return; }
      const dot = document.createElementNS(SVGNS, 'circle');
      dot.setAttribute('r', '5'); dot.setAttribute('class', 'comet'); svg.appendChild(dot);
      const t0 = performance.now(), dur = 430;
      const step = (t) => {
        const k = Math.min(1, (t - t0) / dur);
        dot.setAttribute('cx', from.x + (to.x - from.x) * k);
        dot.setAttribute('cy', from.y + (to.y - from.y) * k);
        if (k < 1) requestAnimationFrame(step); else { dot.remove(); resolve(); }
      };
      requestAnimationFrame(step);
    });
  }
  async function pulseTo(fromId, toId, level) {
    const C = window.MekiCables;
    if (!fromId || !toId || fromId === toId || state.pulses >= 24) return;
    const nodes = nodeBoxes(); const byId = {};
    nodes.forEach((info, id) => { byId[id] = { id, source: info.source || null }; });
    const path = C.pathBetween(byId, fromId, toId);
    if (!path || !path.length) return;
    state.pulses++;
    try { for (const seg of path) await animateComet(seg); glow(toId, level || 'strong', 1500); }
    finally { state.pulses--; }
  }
  function impulse(intent) {
    if (!intent) return;
    if (intent.kind === 'glow') {
      const id = intent.target.by === 'kind' ? kindId(intent.target.value) : intent.target.value;
      if (id) glow(id, intent.level, intent.level === 'soft' ? 600 : 1500);
      return;
    }
    if (intent.kind === 'comet') {
      const chatId = kindId('chat');
      const toId = intent.target.by === 'kind' ? kindId(intent.target.value) : null;
      if (!toId) { if (intent.fallback) impulse(intent.fallback); return; }
      pulseTo(chatId, toId, intent.level);
    }
  }

  window.MekiCanvas = { initWorld, redraw, impulse, fitView, _state: state };
})();
