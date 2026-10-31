// Step 8 unit tests for frontend/ui_math.js — run with: node scripts/test_step8_ui_math.mjs
// Pure-math verification, no DOM and no browser: the camera-fit formulas are
// checked against their exact trig definitions, the easing against its
// closed form, and the HUD derivation against synthetic snapshots.

import assert from 'node:assert/strict';
import {
  FOV_DEG,
  ballChips,
  deriveHud,
  easeInOutCubic,
  fitDistance,
  formatElapsed,
  hFovDeg,
  topViewDistance,
} from '../pyramid-web/frontend/ui_math.js';

let passed = 0;
const check = (name, fn) => {
  fn();
  passed += 1;
  console.log(`ok  ${name}`);
};

const RAD = Math.PI / 180;

// --- hFovDeg -------------------------------------------------------------------
check('hFovDeg: square viewport keeps the fov', () => {
  assert.ok(Math.abs(hFovDeg(50, 1) - 50) < 1e-9);
});
check('hFovDeg: 16:9 widens the horizontal fov', () => {
  const expected = 2 * Math.atan(Math.tan(25 * RAD) * (16 / 9)) / RAD;
  assert.ok(Math.abs(hFovDeg(50, 16 / 9) - expected) < 1e-9);
  assert.ok(hFovDeg(50, 16 / 9) > 50);
});

// --- fitDistance (bounding-sphere fit for the angled presets) -------------------
const ASPECTS = [0.4, 0.75, 1.0, 1.6, 1.9, 2.39, 3.2, 4.0];
check('fitDistance: exact at margin 1 (d * sin(minHalf) == R) at every aspect', () => {
  for (const aspect of ASPECTS) {
    for (const R of [1.0, 2.2, 2.35]) {
      const d = fitDistance(R, FOV_DEG, aspect, 1.0);
      const vHalf = (FOV_DEG / 2) * RAD;
      const hHalf = (hFovDeg(FOV_DEG, aspect) / 2) * RAD;
      assert.ok(
        Math.abs(d * Math.sin(Math.min(vHalf, hHalf)) - R) < 1e-9,
        `aspect ${aspect}`,
      );
    }
  }
});
check('fitDistance: margin > 1 strictly fits the sphere', () => {
  for (const aspect of ASPECTS) {
    const d = fitDistance(2.35, FOV_DEG, aspect, 1.06);
    const vHalf = (FOV_DEG / 2) * RAD;
    const hHalf = (hFovDeg(FOV_DEG, aspect) / 2) * RAD;
    assert.ok(d * Math.sin(Math.min(vHalf, hHalf)) > 2.35, `aspect ${aspect}`);
  }
});

// --- topViewDistance (straight-down fit) ----------------------------------------
check('topViewDistance: both plan axes fit and the bound is tight', () => {
  const SX = 4.02; // L + 2*OUTER
  const SZ = 2.12; // W + 2*OUTER
  for (const aspect of ASPECTS) {
    const d = topViewDistance(SX, SZ, FOV_DEG, aspect, 1.0);
    const tanHalf = Math.tan((FOV_DEG / 2) * RAD);
    const visZ = 2 * d * tanHalf;
    const visX = visZ * aspect;
    assert.ok(visZ >= SZ - 1e-9, `Z fits at aspect ${aspect}`);
    assert.ok(visX >= SX - 1e-9, `X fits at aspect ${aspect}`);
    const bound = Math.max(SZ / (2 * tanHalf), SX / (2 * tanHalf * aspect));
    assert.ok(Math.abs(d - bound) < 1e-9, `tight at aspect ${aspect}`);
  }
});
check('topViewDistance: 16:9 and common portrait aspects stay under maxDistance', () => {
  // controls.maxDistance is 15 in main.js — the presets must never exceed it
  for (const aspect of [1.6, 16 / 9, 2.0, 0.75, 0.5, 0.46, 0.4]) {
    const d = topViewDistance(4.02, 2.12, FOV_DEG, aspect, 1.04);
    assert.ok(d < 15, `aspect ${aspect.toFixed(2)} -> ${d.toFixed(2)} m`);
  }
});

// --- easeInOutCubic ---------------------------------------------------------------
check('easeInOutCubic: endpoints and midpoint', () => {
  assert.equal(easeInOutCubic(0), 0);
  assert.equal(easeInOutCubic(1), 1);
  assert.ok(Math.abs(easeInOutCubic(0.5) - 0.5) < 1e-12);
});
check('easeInOutCubic: clamped and monotonic', () => {
  assert.equal(easeInOutCubic(-0.3), 0);
  assert.equal(easeInOutCubic(1.7), 1);
  let prev = -Infinity;
  for (let i = 0; i <= 200; i++) {
    const v = easeInOutCubic(i / 200);
    assert.ok(v >= prev);
    prev = v;
  }
});

// --- formatElapsed -----------------------------------------------------------------
check('formatElapsed: typical values', () => {
  assert.equal(formatElapsed(0), '0:00');
  assert.equal(formatElapsed(37_400), '0:37');
  assert.equal(formatElapsed(60_000), '1:00');
  assert.equal(formatElapsed(3_661_000), '61:01');
});
check('formatElapsed: negative / NaN safe', () => {
  assert.equal(formatElapsed(-5), '0:00');
  assert.equal(formatElapsed(NaN), '0:00');
});

// --- ballChips ---------------------------------------------------------------------
check('ballChips: null balls -> all 15 on the table', () => {
  const chips = ballChips(null);
  assert.equal(chips.length, 15);
  assert.ok(chips.every((c) => c.onTable));
  assert.deepEqual(chips.map((c) => c.id), Array.from({ length: 15 }, (_, i) => String(i + 1)));
});
check('ballChips: pocketed balls grey out; cue ignored', () => {
  const balls = { cue: { x: 0.5, y: 0.3 } };
  for (let n = 1; n <= 15; n++) {
    if (n === 3 || n === 7 || n === 15) continue;
    balls[String(n)] = { x: 0.1 * n, y: 0.2 * n };
  }
  const chips = ballChips(balls);
  assert.equal(chips.filter((c) => c.onTable).length, 12);
  assert.equal(chips.find((c) => c.id === '3').onTable, false);
  assert.equal(chips.find((c) => c.id === '7').onTable, false);
  assert.equal(chips.find((c) => c.id === '15').onTable, false);
});

// --- deriveHud ----------------------------------------------------------------------
const SNAPSHOT = {
  mode_name: 'Free Pyramid',
  target_score: 8,
  shot_number: 0,
  turn_number: 1,
  turn: { id: 'p1', name: 'Alice' },
  scores: [
    { id: 'p1', name: 'Alice', score: 3 },
    { id: 'p2', name: 'Bob', score: 1 },
  ],
  turn_started_ms: 1_000_000,
  now_ms: 1_005_000,
  game_over: false,
  ball_in_hand: 'none',
  call_shot: false,
  hittable: ['1', '2'],
};

check('deriveHud: null game -> null (HUD hidden)', () => {
  assert.equal(deriveHud(null, null, 'p1'), null);
});
check('deriveHud: mode/shot lines, 1-based numbering', () => {
  const hud = deriveHud(SNAPSHOT, null, 'p1');
  assert.equal(hud.modeLine, 'Free Pyramid · first to 8');
  assert.equal(hud.shotLine, 'shot 1 · turn 2'); // 0-based internals + 1
});
check('deriveHud: player cards with turn + me flags', () => {
  const hud = deriveHud(SNAPSHOT, null, 'p2');
  assert.equal(hud.players.length, 2);
  assert.equal(hud.players[0].isTurn, true);
  assert.equal(hud.players[0].isMe, false);
  assert.equal(hud.players[1].isMe, true);
  assert.equal(hud.players[1].isTurn, false);
});
check('deriveHud: clock uses the caller-supplied skew-corrected server now', () => {
  const hud = deriveHud(SNAPSHOT, null, 'p1', 1_009_500);
  assert.equal(hud.clockMs, 9_500);
});
check('deriveHud: clock falls back to the snapshot stamp', () => {
  const hud = deriveHud(SNAPSHOT, null, 'p1');
  assert.equal(hud.clockMs, 5_000);
});
check('deriveHud: clock null without stamps', () => {
  const noClock = { ...SNAPSHOT };
  delete noClock.turn_started_ms;
  delete noClock.now_ms;
  assert.equal(deriveHud(noClock, null, 'p1').clockMs, null);
  assert.equal(deriveHud({ ...SNAPSHOT, turn_started_ms: 0 }, null, 'p1').clockMs, null);
});
check('deriveHud: remaining count from the authoritative balls', () => {
  const balls = { cue: { x: 0.5, y: 0.3 } };
  for (let n = 1; n <= 12; n++) balls[String(n)] = { x: 0.1, y: 0.2 };
  const hud = deriveHud(SNAPSHOT, balls, 'p1');
  assert.equal(hud.remainingCount, 12);
  assert.equal(hud.chips.length, 15);
});

console.log(`\nall ${passed} ui_math checks passed`);
