// Full z-profile of ExtrudeGeometry bevel: contour x-extent at every z level.
import * as THREE from '/home/z/my-project/pyramid-web/frontend/vendor/three.core.js';

function profile(label, opts, build) {
  const shape = build();
  const geo = new THREE.ExtrudeGeometry(shape, opts);
  const pos = geo.attributes.position;
  const byZ = new Map();
  for (let i = 0; i < pos.count; i++) {
    const z = pos.getZ(i).toFixed(4);
    const x = pos.getX(i);
    if (!byZ.has(z)) byZ.set(z, { x0: 9, x1: -9, n: 0 });
    const e = byZ.get(z);
    e.x0 = Math.min(e.x0, x); e.x1 = Math.max(e.x1, x); e.n++;
  }
  console.log(label);
  for (const [z, e] of [...byZ.entries()].sort((a, b) => a[0] - b[0])) {
    console.log(`  z=${z}  x:[${e.x0.toFixed(4)}, ${e.x1.toFixed(4)}]  n=${e.n}`);
  }
}

profile(
  'SOLID square 1x1, depth=1, t=0.2 s=0.1 off=-0.1:',
  { depth: 1, bevelEnabled: true, bevelThickness: 0.2, bevelSize: 0.1, bevelOffset: -0.1, bevelSegments: 4 },
  () => {
    const s = new THREE.Shape();
    s.moveTo(0, 0); s.lineTo(1, 0); s.lineTo(1, 1); s.lineTo(0, 1);
    return s;
  },
);

profile(
  'RING: 2x2 square with 1x1 hole, depth=1, t=0.2 s=0.1 off=-0.1:',
  { depth: 1, bevelEnabled: true, bevelThickness: 0.2, bevelSize: 0.1, bevelOffset: -0.1, bevelSegments: 4 },
  () => {
    const s = new THREE.Shape();
    s.moveTo(0, 0); s.lineTo(2, 0); s.lineTo(2, 2); s.lineTo(0, 2);
    const h = new THREE.Path();
    h.moveTo(0.5, 0.5); h.lineTo(1.5, 0.5); h.lineTo(1.5, 1.5); h.lineTo(0.5, 1.5);
    s.holes.push(h);
    return s;
  },
);
console.log('OK');
