// Debug: trace the cue ball's path and every contact event.
import * as CANNON from '/home/z/my-project/pyramid-web/frontend/vendor/cannon-es.js';
import { PyramidPhysics, POCKETS } from '/home/z/my-project/pyramid-web/frontend/physics.js';

const phys = new PyramidPhysics();
phys.syncBalls({ cue: { x: 0.4, y: 0.4 } });

// raw world event log
phys.world.addEventListener('beginContact', (ev) => {
  const a = ev.bodyA, b = ev.bodyB;
  const label = (o) => o.ballId ? `ball:${o.ballId}` : o.pocketId ? `sensor:${o.pocketId}` : o.cushionId ? `cush:${o.cushionId}` : o.id || '?';
  console.log(`  contact t=${phys.shot ? phys.shot.t.toFixed(3) : '?'} ${label(a)} <-> ${label(b)}`);
});

const target = POCKETS[0];
const phi = Math.atan2(target[2] - 0.4, target[1] - 0.4);
phys.beginShot(3.5, phi);

const cue = phys.ballBodies.get('cue');
let lastLog = -1;
let frames = 0;
while (!phys.done && frames < 6000) {
  phys.step(16.6);
  frames++;
  if (cue && phys.shot && Math.floor(phys.shot.t / 0.1) !== lastLog) {
    lastLog = Math.floor(phys.shot.t / 0.1);
    console.log(`t=${phys.shot.t.toFixed(2)} cue=(${cue.position.x.toFixed(4)}, ${cue.position.z.toFixed(4)}) v=${Math.hypot(cue.velocity.x, cue.velocity.z).toFixed(2)}`);
  }
  if (!cue) {
    console.log('cue body removed (captured?) at t=', phys.shot.t);
    break;
  }
}
console.log('done:', phys.done, 'result pocketed:', JSON.stringify(phys.result()?.pocketed));
console.log('cue final:', phys.result()?.final.cue);
