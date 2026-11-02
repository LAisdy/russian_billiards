// Probe: place a ball at points along the lb-pocket diagonal and step once,
// dumping every contact (bodies, world contact point, normal).
import * as CANNON from '/home/z/my-project/pyramid-web/frontend/vendor/cannon-es.js';
import { PyramidPhysics } from '/home/z/my-project/pyramid-web/frontend/physics.js';

const phys = new PyramidPhysics();
const world = phys.world;

function probe(x, y) {
  phys.syncBalls({ cue: { x, y } });
  const cue = phys.ballBodies.get('cue');
  // nudge it barely toward the corner so contacts resolve
  cue.velocity.set(-0.001, 0, -0.001);
  const before = world.contacts.length;
  world.step(1 / 1000);
  const cs = world.contacts;
  const label = (b) => (b.ballId ? `ball:${b.ballId}` : b.pocketId ? `sensor:${b.pocketId}` : b.cushionId ? `cush:${b.cushionId}` : b.id);
  if (cs.length) {
    for (const c of cs) {
      const p = new CANNON.Vec3();
      c.bi.position.vadd(c.ri, p);
      console.log(
        `probe (${x.toFixed(3)},${y.toFixed(3)}): ${label(c.bi)} <-> ${label(c.bj)} ` +
        `pt=(${p.x.toFixed(4)},${p.y.toFixed(4)},${p.z.toFixed(4)}) n=(${c.ni.x.toFixed(3)},${c.ni.y.toFixed(3)},${c.ni.z.toFixed(3)})`,
      );
    }
  } else {
    console.log(`probe (${x.toFixed(3)},${y.toFixed(3)}): no contacts`);
  }
}

for (const t of [0.3, 0.15, 0.08, 0.05, 0.03, 0.0, -0.02]) {
  probe(t, t);
}
