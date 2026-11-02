// Smoke test: build the physics world in Node, sync a mini rack, fire the
// cue ball at a corner pocket, verify capture + result shape.
import { PyramidPhysics, POCKETS, TABLE_W, TABLE_L } from '/home/z/my-project/pyramid-web/frontend/physics.js';

const phys = new PyramidPhysics();
console.log('world built; pockets:', POCKETS.map((p) => p[0]).join(','));

// mini rack: cue ball on the corner-pocket diagonal + one object ball mid-table
const ok = phys.syncBalls({
  cue: { x: 0.4, y: 0.4 },
  1: { x: TABLE_W / 2, y: TABLE_L / 2 },
});
console.log('sync ok:', ok, 'bodies:', phys.ballBodies.size);

const captures = [];
phys.onCapture = (info) => captures.push(info);

// aim straight down the bottom-left corner pocket (lb) diagonal
const target = POCKETS[0]; // lb
const dx = target[1] - 0.4;
const dy = target[2] - 0.4;
const phi = Math.atan2(dy, dx);
const started = phys.beginShot(3.5, phi);
console.log('beginShot:', started);

// step in 16.6 ms frames until done
let frames = 0;
while (!phys.done && frames < 20000) {
  phys.step(16.6);
  frames++;
}
const res = phys.result();
console.log('done after frames:', frames, 'sim seconds:', res && res.duration);
console.log('captures:', JSON.stringify(captures));
console.log('pocketed:', JSON.stringify(res.pocketed));
console.log('final ids:', Object.keys(res.final).join(','));
console.log('first_contact:', JSON.stringify(res.first_contact));
console.log('cushions:', JSON.stringify(res.cushions));
if (!res.pocketed.some((p) => p.ball === 'cue' && p.pocket === 'lb')) {
  console.error('FAIL: cue ball was not captured in pocket lb');
  console.log('final:', JSON.stringify(res.final, null, 1));
  process.exit(1);
}
console.log('SMOKE OK');
