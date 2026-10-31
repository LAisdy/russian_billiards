// Empirical test of three.js ExtrudeGeometry bevel semantics (r187, vendored).
// Question: for shape S extruded with depth D, bevelThickness t, bevelSize s,
// bevelOffset o — where do the lids sit, and is the contour expanded or inset?
import * as THREE from '/home/z/my-project/pyramid-web/frontend/vendor/three.core.js';

function probe(label, opts) {
  const sq = new THREE.Shape();
  sq.moveTo(0, 0);
  sq.lineTo(1, 0);
  sq.lineTo(1, 1);
  sq.lineTo(0, 1);
  const geo = new THREE.ExtrudeGeometry(sq, opts);
  geo.computeBoundingBox();
  const bb = geo.boundingBox;
  const pos = geo.attributes.position;
  // contour extent near the bottom lid, top lid, and mid-height
  const zMin = bb.min.z, zMax = bb.max.z;
  let lidLo = { x0: 9, x1: -9 }, lidHi = { x0: 9, x1: -9 }, mid = { x0: 9, x1: -9 };
  const zMid = (zMin + zMax) / 2;
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i);
    if (Math.abs(z - zMin) < 1e-6) { lidLo.x0 = Math.min(lidLo.x0, x); lidLo.x1 = Math.max(lidLo.x1, x); }
    if (Math.abs(z - zMax) < 1e-6) { lidHi.x0 = Math.min(lidHi.x0, x); lidHi.x1 = Math.max(lidHi.x1, x); }
    if (Math.abs(z - zMid) < 1e-6) { mid.x0 = Math.min(mid.x0, x); mid.x1 = Math.max(mid.x1, x); }
  }
  console.log(label);
  console.log(`  z: [${zMin.toFixed(4)}, ${zMax.toFixed(4)}] total=${(zMax - zMin).toFixed(4)} (depth=${opts.depth})`);
  console.log(`  x @bottom lid: [${lidLo.x0.toFixed(4)}, ${lidLo.x1.toFixed(4)}]  @top lid: [${lidHi.x0.toFixed(4)}, ${lidHi.x1.toFixed(4)}]  @mid: [${mid.x0.toFixed(4)}, ${mid.x1.toFixed(4)}]`);
}

// 1) no bevel — reference
probe('A: no bevel (depth 1)', { depth: 1, bevelEnabled: false });
// 2) bevel, offset 0
probe('B: bevel t=0.2 s=0.1 off=0 (depth 1)', { depth: 1, bevelEnabled: true, bevelThickness: 0.2, bevelSize: 0.1, bevelOffset: 0, bevelSegments: 4 });
// 3) bevel with negative offset (the "chamfer keeps original size" trick)
probe('C: bevel t=0.2 s=0.1 off=-0.1 (depth 1)', { depth: 1, bevelEnabled: true, bevelThickness: 0.2, bevelSize: 0.1, bevelOffset: -0.1, bevelSegments: 4 });
// 4) hole behaviour: square with square hole, negative offset
{
  const sq = new THREE.Shape();
  sq.moveTo(0, 0); sq.lineTo(2, 0); sq.lineTo(2, 2); sq.lineTo(0, 2);
  const hole = new THREE.Path();
  hole.moveTo(0.5, 0.5); hole.lineTo(1.5, 0.5); hole.lineTo(1.5, 1.5); hole.lineTo(0.5, 1.5);
  sq.holes.push(hole);
  const geo = new THREE.ExtrudeGeometry(sq, { depth: 1, bevelEnabled: true, bevelThickness: 0.2, bevelSize: 0.1, bevelOffset: -0.1, bevelSegments: 4 });
  geo.computeBoundingBox();
  const bb = geo.boundingBox;
  const pos = geo.attributes.position;
  const zMin = bb.min.z, zMid = (bb.min.z + bb.max.z) / 2;
  let lidHole = 9, midHole = 9; // smallest x of hole-region vertices at lid / mid
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i);
    if (x > 0.2 && x < 1.8 && y > 0.2 && y < 1.8) { // hole boundary vertices only
      if (Math.abs(z - zMin) < 1e-6) lidHole = Math.min(lidHole, x);
      if (Math.abs(z - zMid) < 1e-6) midHole = Math.min(midHole, x);
    }
  }
  console.log('D: hole, t=0.2 s=0.1 off=-0.1');
  console.log(`  hole x @lid: ${lidHole.toFixed(4)}  @mid: ${midHole.toFixed(4)} (original hole edge x=0.5)`);
}
console.log('OK');
