// Step 11 client-physics battery (Node, headless — no DOM/THREE needed).
//
// Invariants under test:
//   A. Break shot at max power: quiescence, no escapes, no overlaps, no NaN.
//   B. NEVER-STUCK: no live ball ever rests inside a pocket trigger zone
//      (the user-reported bug: ball half-inside the pocket, not pocketed).
//   C. Pocket capture on all six pockets with the correct pocket id.
//   D. Rail-hugging balls are NOT falsely captured.
//   E. A ball rolling slowly into a pocket mouth is ALWAYS captured before
//      it can come to rest half-inside (capture zone covers the whole mouth).
//   F. Soft jaw-rattle shots end either pocketed or legally at rest.
//   G. Determinism: identical inputs -> bit-identical results.
//   H. syncBalls add/remove semantics (respot / pocketed removal).
//   I. fastForward (hidden-tab path) matches stepped results.

import { PyramidPhysics, POCKETS, TABLE_W, TABLE_L, BALL_R, CAPTURE_R } from '/home/z/my-project/pyramid-web/frontend/physics.js';

let passed = 0;
let failed = 0;
const fail = (name, detail) => {
  failed++;
  console.error(`FAIL ${name}: ${detail}`);
};
const ok = (name) => {
  passed++;
  console.log(`ok   ${name}`);
};

const assert = (cond, name, detail) => {
  if (cond) ok(name);
  else fail(name, detail);
};

// --- standard rack (mirrors layouts.py / main.js localRack) --------------------
function rackPositions(seed = 7) {
  let s = seed | 0;
  const rng = () => {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const ids = Array.from({ length: 15 }, (_, i) => String(i + 1));
  for (let i = ids.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [ids[i], ids[j]] = [ids[j], ids[i]];
  }
  const positions = {};
  const dy = (2 * BALL_R + 1e-3) * (Math.sqrt(3) / 2);
  let k = 0;
  for (let row = 0; row < 5; row++) {
    for (let j = 0; j <= row; j++) {
      positions[ids[k++]] = {
        x: 0.5 * TABLE_W - row * (BALL_R + 5e-4) + j * (2 * BALL_R + 1e-3),
        y: 0.75 * TABLE_L + row * dy,
      };
    }
  }
  positions.cue = { x: 0.5 * TABLE_W, y: 0.23 * TABLE_L };
  return positions;
}

// --- shared invariant checks -----------------------------------------------------
function checkStateInvariants(name, phys, res) {
  const wells = POCKETS;
  let bad = [];
  for (const [id, pos] of Object.entries(res.final)) {
    if (!Number.isFinite(pos.x) || !Number.isFinite(pos.y)) bad.push(`${id}:NaN`);
    if (pos.x < -0.15 || pos.x > TABLE_W + 0.15 || pos.y < -0.15 || pos.y > TABLE_L + 0.15) {
      bad.push(`${id}:escaped(${pos.x.toFixed(3)},${pos.y.toFixed(3)})`);
    }
    for (const [pid, wx, wy] of wells) {
      const d = Math.hypot(pos.x - wx, pos.y - wy);
      if (d < CAPTURE_R - 1e-6) {
        bad.push(`${id}:stuck-in-${pid}(d=${d.toFixed(4)})`);
      }
    }
  }
  const ids = Object.keys(res.final);
  for (let i = 0; i < ids.length; i++) {
    for (let j = i + 1; j < ids.length; j++) {
      const a = res.final[ids[i]];
      const b = res.final[ids[j]];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      if (d < 2 * BALL_R - 5e-4) bad.push(`overlap:${ids[i]}-${ids[j]}(d=${d.toFixed(4)})`);
    }
  }
  assert(bad.length === 0, name, bad.join('; '));
}

function runShot(phys, positions, v0, phi, onCapture) {
  phys.syncBalls(positions);
  const captures = [];
  phys.onCapture = (info) => {
    captures.push(info);
    if (onCapture) onCapture(info);
  };
  if (!phys.beginShot(v0, phi)) throw new Error('beginShot failed');
  let frames = 0;
  while (!phys.done && frames < 40000) {
    phys.step(16.6);
    frames++;
  }
  assert(phys.done, `${frames < 40000}`, 'shot did not finish');
  return { res: phys.result(), captures, frames };
}

// --- A + B: full-power break from the standard rack ------------------------------
{
  const phys = new PyramidPhysics();
  const { res, captures } = runShot(phys, rackPositions(), 8.0, Math.PI / 2);
  assert(res.duration > 1 && res.duration < 25, 'A: break quiesces in realistic time', `duration=${res.duration}`);
  checkStateInvariants('A/B: break — on-surface, no NaN, no overlap, never stuck in a pocket', phys, res);
  assert(res.first_contact !== null, 'A: break reports first contact', JSON.stringify(res.first_contact));
  assert(Object.keys(res.cushions).length >= 3, 'A: break reports cushion contacts', JSON.stringify(res.cushions));
  assert(
    res.pocketed.every((p) => POCKETS.some(([pid]) => pid === p.pocket)),
    'A: pocket ids valid', JSON.stringify(res.pocketed),
  );
  // pocketed balls must not appear in final; final must not contain them
  const pocketedIds = new Set(res.pocketed.map((p) => p.ball));
  assert(
    Object.keys(res.final).every((id) => !pocketedIds.has(id)),
    'A: pocketed balls removed from final state', '',
  );
  assert(
    res.first_contact && res.first_contact.ball !== 'cue',
    'A: first contact is an object ball', '',
  );
  if (captures.length === res.pocketed.length) ok('A: onCapture fired once per pocketed ball');
  else fail('A: onCapture count', `${captures.length} vs ${res.pocketed.length}`);
}

// --- C: all six pockets capture a straight diagonal shot --------------------------
{
  const phys = new PyramidPhysics();
  const shots = [
    ['lb', 0.4, 0.4, Math.atan2(POCKETS[0][2] - 0.4, POCKETS[0][1] - 0.4)],
    ['rb', 1.4, 0.4, Math.atan2(POCKETS[1][2] - 0.4, POCKETS[1][1] - 1.4)],
    ['lc', 0.5, 1.85, Math.PI], // straight at the left middle pocket
    ['rc', 1.3, 1.85, 0], // straight at the right middle pocket
    ['lt', 0.4, 3.3, Math.atan2(POCKETS[4][2] - 3.3, POCKETS[4][1] - 0.4)],
    ['rt', 1.4, 3.3, Math.atan2(POCKETS[5][2] - 3.3, POCKETS[5][1] - 1.4)],
  ];
  for (const [pid, x, y, phi] of shots) {
    const { res } = runShot(phys, { cue: { x, y } }, 3.5, phi);
    const got = res.pocketed.some((p) => p.ball === 'cue' && p.pocket === pid);
    assert(got, `C: cue captured in ${pid}`, JSON.stringify(res.pocketed) + ' final=' + JSON.stringify(res.final));
  }
}

// --- D: rail-hugger must NOT be pocketed -------------------------------------------
{
  const phys = new PyramidPhysics();
  // ball rolling along the LEFT rail (x = BALL_R) straight past the left
  // middle pocket: real behaviour = stays on the table
  const { res } = runShot(phys, { cue: { x: BALL_R + 1e-4, y: 0.8 } }, 2.5, Math.PI / 2);
  assert(res.pocketed.length === 0, 'D: rail-hugger past middle pocket survives', JSON.stringify(res.pocketed));
  checkStateInvariants('D: rail-hugger invariants', phys, res);
  // same along the bottom rail into the corner: the jaw may drop it (legal)
  // but it must never rest stuck — covered by the never-stuck check:
  const phys2 = new PyramidPhysics();
  const r2 = runShot(phys2, { cue: { x: 1.0, y: BALL_R + 1e-4 } }, 2.5, Math.PI);
  checkStateInvariants('D: end-rail roller invariants', phys2, r2.res);
}

// --- E: slow roll into a pocket mouth is ALWAYS captured (the reported bug) --------
{
  const phys = new PyramidPhysics();
  // slow middle-pocket approach: without capture the ball would stop half
  // inside the mouth (cloth decel from 0.35 m/s reaches ~8 cm)
  const { res } = runShot(phys, { cue: { x: 0.06, y: 1.85 } }, 0.35, Math.PI);
  assert(
    res.pocketed.some((p) => p.ball === 'cue' && p.pocket === 'lc'),
    'E: slow ball rolling into the middle mouth is captured',
    JSON.stringify(res.pocketed) + ' final=' + JSON.stringify(res.final),
  );
  // slow corner approach along the diagonal: from 71 mm out the ball would
  // coast to rest inside the mouth — it must be captured instead
  const phys2 = new PyramidPhysics();
  const phi = Math.atan2(POCKETS[0][2] - 0.1, POCKETS[0][1] - 0.1);
  const r2 = runShot(phys2, { cue: { x: 0.1, y: 0.1 } }, 0.5, phi);
  assert(
    r2.res.pocketed.some((p) => p.ball === 'cue' && p.pocket === 'lb'),
    'E: slow ball rolling into the corner mouth is captured',
    JSON.stringify(r2.res.pocketed) + ' final=' + JSON.stringify(r2.res.final),
  );
}

// --- F: soft jaw-rattle ends pocketed or legally at rest ----------------------------
{
  const phys = new PyramidPhysics();
  // angled entry that hits the corner jaws off-center
  const phi = Math.atan2(POCKETS[0][2] - 0.5, POCKETS[0][1] - 0.75);
  const { res } = runShot(phys, { cue: { x: 0.75, y: 0.5 } }, 1.6, phi);
  checkStateInvariants('F: jaw rattle never sticks', phys, res);
  assert(res.duration > 0, 'F: completed', '');
}

// --- G: determinism ------------------------------------------------------------------
{
  const run = () => {
    const phys = new PyramidPhysics();
    const { res } = runShot(phys, rackPositions(11), 6.0, Math.PI / 2 + 0.01);
    return JSON.stringify(res);
  };
  const a = run();
  const b = run();
  assert(a === b, 'G: identical shots are bit-identical', '');
}

// --- H: syncBalls semantics -----------------------------------------------------------
{
  const phys = new PyramidPhysics();
  phys.syncBalls({ cue: { x: 0.9, y: 0.5 }, 1: { x: 0.9, y: 1.0 }, 2: { x: 0.9, y: 1.5 } });
  assert(phys.ballBodies.size === 3, 'H: three bodies created', String(phys.ballBodies.size));
  phys.syncBalls({ cue: { x: 0.9, y: 0.6 }, 1: { x: 0.9, y: 1.0 } }); // ball 2 pocketed, cue respotted
  assert(phys.ballBodies.size === 2, 'H: removed body is gone', String(phys.ballBodies.size));
  const cue = phys.ballBodies.get('cue');
  assert(Math.abs(cue.position.x - 0.9) < 1e-9 && Math.abs(cue.position.z - 0.6) < 1e-9, 'H: respotted cue moved', '');
  assert(cue.velocity.length() === 0, 'H: synced balls are at rest', '');
  phys.beginShot(2, 0);
  assert(phys.syncBalls({ cue: { x: 0.5, y: 0.5 } }) === false, 'H: sync refused while simulating', '');
  phys.fastForward();
  assert(phys.done, 'H: fastForward completes the shot', '');
}

// --- I: fastForward equals stepped sim ---------------------------------------------------
{
  const a = new PyramidPhysics();
  const ra = runShot(a, rackPositions(3), 5.0, Math.PI / 2);
  const b = new PyramidPhysics();
  b.syncBalls(rackPositions(3));
  b.beginShot(5.0, Math.PI / 2);
  b.fastForward();
  assert(
    JSON.stringify(a.result()) === JSON.stringify(b.result()),
    'I: fastForward result equals stepped result', '',
  );
}

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
