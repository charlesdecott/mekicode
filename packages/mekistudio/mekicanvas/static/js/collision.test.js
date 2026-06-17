const test = require('node:test');
const assert = require('node:assert');
const M = require('./collision.js');
const box = (x, y, w, h) => ({ x, y, w, h });

test('intersects: recouvrement, contact, séparé, effet gap', () => {
  assert.equal(M.intersects(box(0, 0, 100, 100), box(50, 50, 100, 100)), true);
  assert.equal(M.intersects(box(0, 0, 100, 100), box(200, 0, 100, 100)), false);
  assert.equal(M.intersects(box(0, 0, 100, 100), box(110, 0, 100, 100)), false);
  assert.equal(M.intersects(box(0, 0, 100, 100), box(110, 0, 100, 100), 12), true);
});

test('isFree: libre vs occupé', () => {
  const others = [box(200, 0, 100, 100)];
  assert.equal(M.isFree(box(0, 0, 100, 100), others, 12), true);
  assert.equal(M.isFree(box(150, 0, 100, 100), others, 12), false);
});

test('partVector: écarte l\'obstacle, côté court d\'abord, 2 candidats', () => {
  const mover = box(0, 0, 200, 100);
  const obstacle = box(150, 60, 100, 100);
  const cands = M.partVector(mover, obstacle, { x: 1, y: 0 }, 12);
  assert.equal(cands.length, 2);
  const moved = { ...obstacle, x: obstacle.x + cands[0].x, y: obstacle.y + cands[0].y };
  assert.equal(M.intersects(mover, moved, 12), false);
  const mag = (v) => Math.abs(v.x) + Math.abs(v.y);
  assert.ok(mag(cands[0]) <= mag(cands[1]));
});

test('pushVector: pousse l\'obstacle bas/droite seulement', () => {
  const grower = box(0, 0, 200, 200);
  const obstacle = box(150, 150, 100, 100);
  const v = M.pushVector(grower, obstacle, 12);
  assert.ok(v.x >= 0 && v.y >= 0);
  const moved = { ...obstacle, x: obstacle.x + v.x, y: obstacle.y + v.y };
  assert.equal(M.intersects(grower, moved, 12), false);
});

test('clampAgainst: bloque l\'axe de pénétration min, glisse sur l\'autre', () => {
  const obstacle = box(200, 0, 100, 300);
  const clamped = M.clampAgainst(box(0, 0, 100, 100), { x: 250, y: 80, w: 100, h: 100 }, obstacle, 12);
  assert.ok(clamped.x + 100 <= obstacle.x - 12 + 0.01);
  assert.equal(clamped.y, 80);
});

test('findFreeSpot: ancre libre rendue telle quelle', () => {
  const spot = M.findFreeSpot({ x: 0, y: 0 }, { w: 100, h: 100 }, [box(500, 500, 100, 100)], 12);
  assert.deepEqual(spot, { x: 0, y: 0 });
});

test('findFreeSpot: ancre occupée -> trou libre proche, résultat libre', () => {
  const others = [box(0, 0, 100, 100), box(112, 0, 100, 100)];
  const spot = M.findFreeSpot({ x: 0, y: 0 }, { w: 100, h: 100 }, others, 12);
  assert.equal(M.isFree({ x: spot.x, y: spot.y, w: 100, h: 100 }, others, 12), true);
});
