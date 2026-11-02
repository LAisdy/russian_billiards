// pyramid-web — Three.js scene.
//
// Step 1: skeleton render pipeline (vendored three.js, orbit camera, /api
//         health check in the HUD).
// Step 2: lobby overlay (see lobby.js) over the live scene.
// Step 3: physics-exact pocket wells + rail mouth gaps + procedural felt.
// Step 4: the full table model — bed with real pocket holes, felt cushions
//         with physics-exact noses and jaw arcs, apron + legs (table height
//         0.82 m), and all 16 balls (white numbered 1–15 + dark red cue)
//         placed in the standard rack fetched from GET /api/rack.
// Step 4b (visual rework, user request): the wooden frame is ONE unified
//         piece — a single THREE.Shape (rounded-rectangle outer perimeter,
//         playing-area inner contour that curls around all six pocket wells
//         on clearance arcs) driven through ONE ExtrudeGeometry. No seams:
//         the old 45° corner miters became unnecessary by construction, and
//         the wood wraps every pocket the way a real rail does. The cushions
//         are separate rubber prisms with a rounded bevel — physics nose at
//         mid-height, chamfered down toward the cloth at the base and back
//         under the rail cap at the top. Lighting gained ACES tone mapping
//         and a procedural PMREM environment; wood/felt got bump maps; balls
//         are clearcoated. NO table dimension was touched.
// Step 8: camera presets (orbit/top/head-end/foot-end) computed from the
//         viewport aspect (ui_math.js) with smooth cubic tweens, user-input
//         cancellation, resize re-framing and localStorage persistence —
//         the table stays in frame at every aspect ratio.
//
// Every table dimension below is taken from the pooltool physics spec, so
// what you see is what the engine simulates against:
//   - objects/table/collection.py :: RUSSIAN_PYRAMID_GENERIC
//       playing surface 3.70 x 1.80 m · cushion width 0.05 m
//       cushion height 0.64 x ball Ø (67 mm) = 42.88 mm
//       corner: mouth 72.5 mm, jaw r 15 mm, well r 45 mm, depth 45 mm
//       middle: mouth 82.5 mm, jaw r  8 mm, well r 44 mm, depth 50 mm
//       table height 0.82 m
//   - objects/table/layout.py :: create_pocket_table_cushion_segments /
//       create_pocket_table_pockets (nose endpoints, jaw arcs, well centers)
//   - layouts.py :: _get_russian_pyramid_rack (apex on the foot spot
//       (0.5, 0.75), cue ball behind the head string at (0.5, 0.23))
//
// pooltool coordinates (x across the width 0..1.80, y along the length
// 0..3.70) map to three.js as X = y - L/2, Z = x - W/2 (table top at Y=0).

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import {
  FOV_DEG,
  easeInOutCubic,
  fitDistance,
  topViewDistance,
} from './ui_math.js';

// --- equipment constants (pooltool RUSSIAN_PYRAMID_GENERIC) -------------------
const L = 3.7; // table length (m)
const W = 1.8; // table width (m)
const BALL_R = 0.0335; // ball radius (Ø 67 mm)

const CUSH_W = 0.05; // cushion width (nose line -> cushion back)
const CUSH_H = 0.64 * 2 * BALL_R; // cushion height = 42.88 mm

const PW = 0.0725; // corner pocket mouth width
const RC = 0.015; // corner jaw radius
const PR = 0.045; // corner pocket well radius
const PD = 0.045; // corner pocket depth
const SW = 0.0825; // middle pocket mouth width
const RS = 0.008; // middle jaw radius
const SR = 0.044; // middle pocket well radius
const SD = 0.05; // middle pocket depth

// layout.py: dc = rc / tan((90° + ca)/2) with ca = corner_pocket_angle + 45° = 45°
const DC = RC / Math.tan((67.5 * Math.PI) / 180); // corner jaw tangent run (6.21 mm)
const DS = RS / Math.tan((45 * Math.PI) / 180); // = RS (side pocket angle 0)
const PWC = PW * Math.SQRT1_2; // corner mouth projection on a rail
const CD = PD / Math.SQRT2; // corner well center offset beyond the corner

// cushion nose endpoints (layout.py linear segments), pooltool coords
const NOSE_A = PWC + DC; // long rails: first nose end (corner side)
const NOSE_B = (L - SW) / 2 - DS; // long rails: lower nose end (middle side)
const NOSE_C = (L + SW) / 2 + DS; // long rails: upper nose end
const CUSH_BACK = -CUSH_W;
const CORNER_JAW_TAN_X = -RC + RC * Math.cos(Math.PI / 4); // arc -> 45° line point
const CORNER_JAW_TAN_Y = NOSE_A - RC * Math.sin(Math.PI / 4);
const CORNER_JAW_BACK_Y = PWC - CUSH_W; // 45° line hits the cushion back

// frame (wooden rail top) construction
const FRAME_W = 0.11; // wooden frame width beyond the cushion backs
const FRAME_H = 0.048; // wooden frame top height (slightly above the cushions)
const OUTER = CUSH_W + FRAME_W; // bed outer margin beyond the playing surface
const BED_T = 0.04; // bed (slate) thickness
const TABLE_H = 0.82; // playing surface height above the floor (spec)

// --- renderer -----------------------------------------------------------------
const canvas = document.getElementById('scene');
let renderer;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
} catch (err) {
  document.getElementById('hud-three').textContent =
    `three.js: WebGL unavailable (${err instanceof Error ? err.message : err})`;
  throw err;
}
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.12;

// --- scene & camera -------------------------------------------------------------
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x101418);
scene.fog = new THREE.Fog(0x101418, 9, 22);

const camera = new THREE.PerspectiveCamera(
  FOV_DEG, window.innerWidth / window.innerHeight, 0.05, 100,
);
camera.position.set(0, 2.3, 3.4);

const controls = new OrbitControls(camera, canvas);
controls.target.set(0, -0.05, 0);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.maxPolarAngle = Math.PI * 0.495; // never dip below the table plane
controls.minDistance = 0.5;
controls.maxDistance = 15.0; // portrait top view needs ~9–14 m (aspect-safe fit)

// --- lights -------------------------------------------------------------------
scene.add(new THREE.AmbientLight(0xffffff, 0.5));

const lamp = new THREE.DirectionalLight(0xfff4e0, 1.7);
lamp.position.set(1.5, 4.5, 1.2);
lamp.castShadow = true;
lamp.shadow.mapSize.set(2048, 2048);
lamp.shadow.camera.left = -3;
lamp.shadow.camera.right = 3;
lamp.shadow.camera.top = 3;
lamp.shadow.camera.bottom = -3;
lamp.shadow.bias = -0.0004;
scene.add(lamp);

const fill = new THREE.DirectionalLight(0xdfe8ff, 0.45);
fill.position.set(-2.5, 3.0, -2.0);
scene.add(fill);

// --- procedural textures (no external assets) -----------------------------------
const maxAniso = renderer.capabilities.getMaxAnisotropy();

// cloth: green base + mottling + fine grain (Step 3 texture, kept)
const makeFeltTexture = () => {
  const size = 512;
  const cnv = document.createElement('canvas');
  cnv.width = size;
  cnv.height = size;
  const ctx = cnv.getContext('2d');
  ctx.fillStyle = '#1c6b3f';
  ctx.fillRect(0, 0, size, size);
  for (let i = 0; i < 240; i++) {
    const cx = Math.random() * size;
    const cy = Math.random() * size;
    const r = 6 + Math.random() * 26;
    const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
    grad.addColorStop(
      0,
      Math.random() > 0.5 ? 'rgba(255,255,255,0.035)' : 'rgba(0,0,0,0.05)',
    );
    grad.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = grad;
    ctx.fillRect(cx - r, cy - r, 2 * r, 2 * r);
  }
  const image = ctx.getImageData(0, 0, size, size);
  const data = image.data;
  for (let i = 0; i < data.length; i += 4) {
    const n = (Math.random() - 0.5) * 26;
    data[i] = Math.min(255, Math.max(0, data[i] + n));
    data[i + 1] = Math.min(255, Math.max(0, data[i + 1] + n));
    data[i + 2] = Math.min(255, Math.max(0, data[i + 2] + n));
  }
  ctx.putImageData(image, 0, 0);
  const texture = new THREE.CanvasTexture(cnv);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(2, 2); // extrude UVs are in meters -> 0.5 m tile
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = maxAniso;
  return texture;
};

// wood: brown base + long grain streaks (grain runs along canvas Y, which
// maps to the table length for the extruded plan pieces)
const makeWoodCanvas = () => {
  const size = 512;
  const cnv = document.createElement('canvas');
  cnv.width = size;
  cnv.height = size;
  const ctx = cnv.getContext('2d');
  ctx.fillStyle = '#5a3a22';
  ctx.fillRect(0, 0, size, size);
  for (let i = 0; i < 170; i++) {
    const x0 = Math.random() * size;
    const alpha = 0.04 + Math.random() * 0.12;
    ctx.strokeStyle =
      Math.random() > 0.5
        ? `rgba(28,16,7,${alpha})`
        : `rgba(158,110,64,${alpha})`;
    ctx.lineWidth = 1 + Math.random() * 3;
    ctx.beginPath();
    ctx.moveTo(x0, 0);
    for (let yy = 0; yy <= size; yy += 16) {
      ctx.lineTo(x0 + Math.sin(yy * 0.02 + i * 1.7) * 3.5, yy);
    }
    ctx.stroke();
  }
  const image = ctx.getImageData(0, 0, size, size);
  const data = image.data;
  for (let i = 0; i < data.length; i += 4) {
    const n = (Math.random() - 0.5) * 18;
    data[i] = Math.min(255, Math.max(0, data[i] + n));
    data[i + 1] = Math.min(255, Math.max(0, data[i + 1] + n));
    data[i + 2] = Math.min(255, Math.max(0, data[i + 2] + n));
  }
  ctx.putImageData(image, 0, 0);
  return cnv;
};

const woodCanvas = makeWoodCanvas();
const makeWoodTexture = (repeatX, repeatY) => {
  const texture = new THREE.CanvasTexture(woodCanvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(repeatX, repeatY);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = maxAniso;
  return texture;
};

// --- materials ------------------------------------------------------------------
const feltTexBed = makeFeltTexture();
const feltMat = new THREE.MeshStandardMaterial({
  map: feltTexBed,
  bumpMap: feltTexBed, // grain relief so the cloth is not flat plastic
  bumpScale: 0.12,
  roughness: 0.95,
});
const feltTexCushion = makeFeltTexture();
const cushionMat = new THREE.MeshStandardMaterial({
  map: feltTexCushion,
  bumpMap: feltTexCushion,
  bumpScale: 0.12,
  color: 0xe9f3ec, // a touch cooler than the bed: the rubber cushion reads
  roughness: 0.92, //   as its own piece against bed, wood and pocket darkness
  envMapIntensity: 0.5,
});
const woodTexRail = makeWoodTexture(1.25, 1.25); // extrude UVs are meters -> 0.8 m tile
const woodMat = new THREE.MeshStandardMaterial({
  map: woodTexRail,
  bumpMap: woodTexRail,
  bumpScale: 0.35,
  roughness: 0.5,
  envMapIntensity: 0.75,
});
const bodyWoodTex = makeWoodTexture(3, 1.2); // box UVs are 0..1 per face
const bodyWoodMat = new THREE.MeshStandardMaterial({
  map: bodyWoodTex,
  bumpMap: bodyWoodTex,
  bumpScale: 0.35,
  roughness: 0.5,
  envMapIntensity: 0.6,
});

// --- environment: procedural studio equirect -> PMREM ----------------------------
// A dark hall with warm lamp blobs over the table: gives the lacquered wood,
// the cloth and especially the balls real specular sheen (no external assets).
{
  const env = document.createElement('canvas');
  env.width = 512;
  env.height = 256;
  const ectx = env.getContext('2d');
  const bg = ectx.createLinearGradient(0, 0, 0, 256);
  bg.addColorStop(0, '#3a3f46');
  bg.addColorStop(0.5, '#14181d');
  bg.addColorStop(1, '#07090b');
  ectx.fillStyle = bg;
  ectx.fillRect(0, 0, 512, 256);
  for (const [ex, ey, er, ea] of [
    [150, 42, 72, 0.95],
    [300, 42, 72, 0.95],
    [225, 58, 95, 0.5],
  ]) {
    const g = ectx.createRadialGradient(ex, ey, 0, ex, ey, er);
    g.addColorStop(0, `rgba(255,240,210,${ea})`);
    g.addColorStop(1, 'rgba(255,240,210,0)');
    ectx.fillStyle = g;
    ectx.fillRect(0, 0, 512, 256);
  }
  const envTex = new THREE.CanvasTexture(env);
  envTex.mapping = THREE.EquirectangularReflectionMapping;
  envTex.colorSpace = THREE.SRGBColorSpace;
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromEquirectangular(envTex).texture;
  scene.environmentIntensity = 0.5;
  pmrem.dispose();
}
const throatMat = new THREE.MeshStandardMaterial({
  color: 0x0a0a0a,
  roughness: 1.0,
  side: THREE.DoubleSide,
});
const pocketFloorMat = new THREE.MeshStandardMaterial({
  color: 0x060606,
  roughness: 1.0,
});
const rimMat = new THREE.MeshStandardMaterial({
  color: 0x15120e,
  roughness: 0.9,
  side: THREE.DoubleSide,
});

// --- plan-view construction helper ------------------------------------------------
// All table pieces are 2D polygons in pooltool coordinates (x -> shape X,
// y -> shape Y) extruded upward. Two nested groups rotate the plan into the
// scene: local (u, v, w) -> world (v - L/2, w, u - W/2).
const plan = new THREE.Group(); // shapes live in pooltool XY here
const planOrient = new THREE.Group();
planOrient.rotation.y = -Math.PI / 2;
planOrient.position.set(-L / 2, 0, -W / 2);
plan.rotation.x = -Math.PI / 2;
planOrient.add(plan);
scene.add(planOrient);

// polygon ops: P = line-to point, A = absarc (pooltool-xy angles)
const P = (x, y) => ({ t: 'L', x, y });
const A = (cx, cy, r, a0, a1, cw) => ({ t: 'A', cx, cy, r, a0, a1, cw });

const mirrorY = (ops) =>
  ops.map((o) =>
    o.t === 'L'
      ? { ...o, y: L - o.y }
      : { ...o, cy: L - o.cy, a0: -o.a0, a1: -o.a1, cw: !o.cw },
  );
const mirrorX = (ops) =>
  ops.map((o) =>
    o.t === 'L'
      ? { ...o, x: W - o.x }
      : { ...o, cx: W - o.cx, a0: Math.PI - o.a0, a1: Math.PI - o.a1, cw: !o.cw },
  );

const shapeFromOps = (ops) => {
  const shape = new THREE.Shape();
  ops.forEach((o, i) => {
    if (o.t === 'L') {
      if (i === 0) shape.moveTo(o.x, o.y);
      else shape.lineTo(o.x, o.y);
    } else {
      shape.absarc(o.cx, o.cy, o.r, o.a0, o.a1, o.cw);
    }
  });
  shape.closePath();
  return shape;
};

const circleHole = (cx, cy, r) => {
  const path = new THREE.Path();
  path.absarc(cx, cy, r, 0, Math.PI * 2, true);
  return path;
};

const addPlanPiece = (shape, material, height, opts = {}) => {
  // opts.bevel: rounded chamfer height (m) applied to BOTH extrusion ends.
  // With bevelOffset = -bevelInset the wall keeps the exact contour (physics
  // nose / rail line) while the top and bottom lids pull back by bevelInset.
  const bevel = opts.bevel ?? 0;
  const inset = opts.bevelInset ?? bevel * 0.75;
  const geo = new THREE.ExtrudeGeometry(shape, {
    depth: height - 2 * bevel,
    bevelEnabled: bevel > 0,
    bevelThickness: bevel || undefined,
    bevelSize: inset || undefined,
    bevelOffset: inset ? -inset : undefined,
    bevelSegments: 4,
    curveSegments: opts.curveSegments ?? 24,
  });
  const mesh = new THREE.Mesh(geo, material);
  // the bevel extends the solid bevel-thickness beyond [0, depth] on both ends
  mesh.position.z = (opts.baseZ ?? 0) + bevel; // local z = world Y (plan group)
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  plan.add(mesh);
  return mesh;
};

// --- cushions (6 felt prisms, physics-exact noses + jaw arcs) ---------------------
// left-lower cushion (nose on x=0 from NOSE_A to NOSE_B): back edge, side jaw
// (perpendicular, sa=0) with tip arc r=RS, nose line, corner jaw (45°) with
// tip arc r=RC. The other five are mirrors of this one / of the bottom one.
const cushLeftLower = [
  P(CUSH_BACK, CORNER_JAW_BACK_Y), // back, corner end
  P(CUSH_BACK, NOSE_B + RS), // back, middle end (side jaw line y = NOSE_B + RS)
  P(-RS, NOSE_B + RS), // side jaw inner end
  A(-RS, NOSE_B, RS, Math.PI / 2, 0, true), // tip arc down to the nose
  P(0, NOSE_B), // nose, middle end
  P(0, NOSE_A), // nose, corner end
  A(-RC, NOSE_A, RC, 0, -Math.PI / 4, true), // tip arc onto the 45° jaw line
  // closePath draws the 45° jaw line back to the start
];

const cushBottom = [
  P(CORNER_JAW_BACK_Y, CUSH_BACK), // back-left (45° jaw line end)
  P(W - CORNER_JAW_BACK_Y, CUSH_BACK), // back-right
  P(W - CORNER_JAW_TAN_Y, CORNER_JAW_TAN_X), // right jaw tangent point
  A(W - NOSE_A, -RC, RC, Math.PI / 4, Math.PI / 2, false), // tip arc to nose
  P(W - NOSE_A, 0), // nose, right end
  P(NOSE_A, 0), // nose, left end
  A(NOSE_A, -RC, RC, Math.PI / 2, (3 * Math.PI) / 4, false), // tip arc to jaw
  P(CORNER_JAW_TAN_Y, CORNER_JAW_TAN_X), // left jaw tangent point
  // closePath draws the 45° jaw line back to the start
];

const cushionOps = [
  cushLeftLower,
  mirrorY(cushLeftLower),
  mirrorX(cushLeftLower),
  mirrorX(mirrorY(cushLeftLower)),
  cushBottom,
  mirrorY(cushBottom),
];
// Rounded rubber profile: the wall keeps the physics nose line, the top lid
// tucks back under the wooden rail cap, the base opens an angle pointing down
// towards the cloth — the cushions read as separate rubber pieces.
const CUSH_BEVEL = 0.012; // chamfer height (m)
const CUSH_INSET = 0.009; // lid pull-back from the nose (m)
const cushionShapes = cushionOps.map(shapeFromOps);
for (const shape of cushionShapes) {
  addPlanPiece(shape, cushionMat, CUSH_H, {
    bevel: CUSH_BEVEL,
    bevelInset: CUSH_INSET,
    curveSegments: 32,
  });
}

// --- bed (slate + felt) with real pocket holes ------------------------------------
const R_OUT = 0.07; // rounded outer corner radius (bed + unified frame share it)

const roundedRectShape = (x0, y0, x1, y1, r) => {
  const s = new THREE.Shape();
  s.moveTo(x0 + r, y0);
  s.lineTo(x1 - r, y0);
  s.absarc(x1 - r, y0 + r, r, -Math.PI / 2, 0, false);
  s.lineTo(x1, y1 - r);
  s.absarc(x1 - r, y1 - r, r, 0, Math.PI / 2, false);
  s.lineTo(x0 + r, y1);
  s.absarc(x0 + r, y1 - r, r, Math.PI / 2, Math.PI, false);
  s.lineTo(x0, y0 + r);
  s.absarc(x0 + r, y0 + r, r, Math.PI, 1.5 * Math.PI, false);
  s.closePath();
  return s;
};

const bedShape = roundedRectShape(-OUTER, -OUTER, W + OUTER, L + OUTER, R_OUT);
// pocket well circles (layout.py :: create_pocket_table_pockets)
const WELL_CENTERS = [
  [-CD, -CD, PR],
  [W + CD, -CD, PR],
  [-CD, L + CD, PR],
  [W + CD, L + CD, PR],
  [-SD, L / 2, SR],
  [W + SD, L / 2, SR],
];
for (const [cx, cy, r] of WELL_CENTERS) bedShape.holes.push(circleHole(cx, cy, r));
addPlanPiece(bedShape, feltMat, BED_T, { baseZ: -BED_T });

// --- wooden frame: ONE unified ring ------------------------------------------------
// A single THREE.Shape: rounded-rectangle outer perimeter + ONE inner contour
// (the playing-area hole) that runs along the cushion backs and CURLS AROUND
// all six pocket wells on clearance arcs — 3 mm over the corner wells, 1.5 mm
// over the middle wells. One ExtrudeGeometry, zero seams: the old 45° corner
// miters are unnecessary by construction and the wood wraps every pocket the
// way a real rail does. A 5 mm bevel rounds the top edges of the whole ring.
const CLR_C = PR + 0.003; // corner wrap arc radius (clear of the Ø 90 mm well)
const CLR_S = SR + 0.0015; // middle wrap arc radius (clear of the Ø 88 mm well)
const wrapRun = Math.sqrt(CLR_C ** 2 - (CUSH_W - CD) ** 2); // along-rail run
const depX = -CD + wrapRun; // wrap departure point along a rail edge (12.6 mm)
const DELTA = Math.atan2(CUSH_W - CD, wrapRun); // rail-crossing radius angle
const SWEEP_C = 1.5 * Math.PI - 2 * DELTA; // corner wrap sweep (225.4°)

const frameShape = roundedRectShape(-OUTER, -OUTER, W + OUTER, L + OUTER, R_OUT);

// inner contour: cushion backs + six pocket wraps (one closed hole)
const frameHoleOps = [
  P(depX, -CUSH_W), // bottom rail, left end
  P(W - depX, -CUSH_W), // bottom rail, right end
  A(W + CD, -CD, CLR_C, -Math.PI + DELTA, -Math.PI + DELTA + SWEEP_C, false), // BR wrap
  P(W + CUSH_W, L / 2 - CLR_S), // right rail, lower end
  A(W + SD, L / 2, CLR_S, -Math.PI / 2, Math.PI / 2, false), // right middle wrap
  P(W + CUSH_W, L - depX), // right rail, upper end
  A(W + CD, L + CD, CLR_C, -Math.PI / 2 + DELTA, -Math.PI / 2 + DELTA + SWEEP_C, false), // TR wrap
  P(depX, L + CUSH_W), // top rail, right end
  A(-CD, L + CD, CLR_C, DELTA, DELTA + SWEEP_C, false), // TL wrap
  P(-CUSH_W, L / 2 + CLR_S), // left rail, upper end
  A(-SD, L / 2, CLR_S, Math.PI / 2, 1.5 * Math.PI, false), // left middle wrap
  P(-CUSH_W, depX), // left rail, lower end
  A(-CD, -CD, CLR_C, Math.PI / 2 + DELTA, Math.PI / 2 + DELTA + SWEEP_C, false), // BL wrap
];
frameShape.holes.push(shapeFromOps(frameHoleOps));
const frameMesh = addPlanPiece(frameShape, woodMat, FRAME_H, {
  bevel: 0.005,
  bevelInset: 0.004,
  curveSegments: 48,
});

// --- pocket throats (below the bed holes) + rim rings ------------------------------
const pocketWells = WELL_CENTERS.map(([px, py, r]) => ({
  x: py - L / 2, // pooltool -> three.js: X = y - L/2, Z = x - W/2
  z: px - W / 2,
  r,
}));
const TUBE_TOP = 0.002;
const TUBE_BOTTOM = -0.038; // pocket floor sits just above the apron top
for (const p of pocketWells) {
  const tube = new THREE.Mesh(
    new THREE.CylinderGeometry(p.r + 0.0008, p.r + 0.0008, TUBE_TOP - TUBE_BOTTOM, 32, 1, true),
    throatMat,
  );
  tube.position.set(p.x, (TUBE_TOP + TUBE_BOTTOM) / 2, p.z);
  scene.add(tube);
  const floorDisc = new THREE.Mesh(new THREE.CircleGeometry(p.r, 32), pocketFloorMat);
  floorDisc.rotation.x = -Math.PI / 2;
  floorDisc.position.set(p.x, TUBE_BOTTOM, p.z);
  scene.add(floorDisc);
  const rim = new THREE.Mesh(new THREE.RingGeometry(p.r, p.r + 0.012, 36), rimMat);
  rim.rotation.x = -Math.PI / 2;
  rim.position.set(p.x, 0.0006, p.z);
  rim.receiveShadow = true;
  scene.add(rim);
}

// --- table body: apron + legs (playing surface 0.82 m above the floor) -------------
const apron = new THREE.Mesh(
  // inset 18 mm per side: the unified rail cap overhangs the body like on a
  // real table (playing surface / table dims untouched)
  new THREE.BoxGeometry(L + 2 * OUTER - 0.036, 0.1, W + 2 * OUTER - 0.036),
  bodyWoodMat,
);
apron.position.y = -BED_T - 0.05;
apron.castShadow = true;
apron.receiveShadow = true;
scene.add(apron);

const legGeo = new THREE.CylinderGeometry(0.105, 0.14, TABLE_H - BED_T - 0.1, 4, 1); // tapered square leg
const legY = -BED_T - 0.1 - (TABLE_H - BED_T - 0.1) / 2;
for (const [lx, lz] of [
  [-1.55, -0.55], [1.55, -0.55], [-1.55, 0.55], [1.55, 0.55], [0, -0.62], [0, 0.62],
]) {
  const leg = new THREE.Mesh(legGeo, bodyWoodMat);
  leg.rotation.y = Math.PI / 4; // align the square faces with the table
  leg.position.set(lx, legY, lz);
  leg.castShadow = true;
  scene.add(leg);
}

// dark floor at the real table height
const floor = new THREE.Mesh(
  new THREE.PlaneGeometry(30, 30),
  new THREE.MeshStandardMaterial({ color: 0x0a0c0e, roughness: 1.0 }),
);
floor.rotation.x = -Math.PI / 2;
floor.position.y = -TABLE_H;
floor.receiveShadow = true;
scene.add(floor);

// --- table markings: head string + spots -------------------------------------------
const markMat = new THREE.MeshStandardMaterial({ color: 0x11402a, roughness: 1.0 });
for (const [mx, my] of [[0.5 * W, 0.75 * L], [0.5 * W, 0.5 * L], [0.5 * W, 0.25 * L]]) {
  const spot = new THREE.Mesh(new THREE.CircleGeometry(0.007, 24), markMat);
  spot.rotation.x = -Math.PI / 2;
  spot.position.set(my - L / 2, 0.0005, mx - W / 2);
  scene.add(spot);
}
const headString = new THREE.Mesh(new THREE.PlaneGeometry(0.003, W - 2 * CUSH_W), markMat);
headString.rotation.x = -Math.PI / 2;
headString.rotation.z = Math.PI / 2;
headString.position.set(0.25 * L - L / 2, 0.0005, W / 2 - W / 2);
scene.add(headString);

// --- Step 6: ball-in-hand house highlight ---------------------------------------
// While the active player holds «с руки из дома» (behind the house line),
// a faint golden wash marks the legal placement zone (the house: y < 0.25 L,
// i.e. world X < -L/2 + 0.925). "anywhere" (Dynamic) needs no marker.
const HOUSE_Y = 0.25 * L; // house line, pooltool coordinates
const houseHighlight = new THREE.Mesh(
  new THREE.PlaneGeometry(HOUSE_Y, W),
  new THREE.MeshBasicMaterial({
    color: 0xffd54f,
    transparent: true,
    opacity: 0.14,
    depthWrite: false,
  }),
);
houseHighlight.rotation.x = -Math.PI / 2;
houseHighlight.position.set(-L / 2 + HOUSE_Y / 2, 0.0012, 0);
houseHighlight.visible = false;
scene.add(houseHighlight);

const setBallInHand = (mode) => {
  houseHighlight.visible = mode === 'behind_line';
};

// --- balls: white numbered 1–15 + dark red cue, standard rack ----------------------
const ballGeo = new THREE.SphereGeometry(BALL_R, 48, 32);

// number decal: two circles on the equator (u = 0.25 / 0.75) like a real set
const makeBallTexture = (num) => {
  const cnv = document.createElement('canvas');
  cnv.width = 256;
  cnv.height = 128;
  const ctx = cnv.getContext('2d');
  ctx.fillStyle = '#f4f1e6';
  ctx.fillRect(0, 0, 256, 128);
  for (const cx of [64, 192]) {
    ctx.beginPath();
    ctx.arc(cx, 64, 21, 0, Math.PI * 2);
    ctx.fillStyle = '#faf8f0';
    ctx.fill();
    ctx.lineWidth = 2.5;
    ctx.strokeStyle = '#1a1a1a';
    ctx.stroke();
    ctx.fillStyle = '#101010';
    ctx.font = 'bold 30px Arial, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(String(num), cx, 66);
  }
  const texture = new THREE.CanvasTexture(cnv);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = maxAniso;
  return texture;
};

const ballMeshes = new Map();
for (let n = 1; n <= 15; n++) {
  const mesh = new THREE.Mesh(
    ballGeo,
    new THREE.MeshPhysicalMaterial({
      map: makeBallTexture(n),
      roughness: 0.16,
      clearcoat: 0.65, // phenolic-ball sheen: sharp lamp highlight + env
      clearcoatRoughness: 0.25,
      envMapIntensity: 1.1,
    }),
  );
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  mesh.rotation.y = n * 2.399; // spread the number decals around the rack
  ballMeshes.set(String(n), mesh);
  scene.add(mesh);
}
const cueMesh = new THREE.Mesh(
  ballGeo,
  new THREE.MeshPhysicalMaterial({
    color: 0x7a1417,
    roughness: 0.16,
    clearcoat: 0.65,
    clearcoatRoughness: 0.25,
    envMapIntensity: 1.1,
  }),
);
cueMesh.castShadow = true;
cueMesh.receiveShadow = true;
ballMeshes.set('cue', cueMesh);
scene.add(cueMesh);

// pooltool (x, y) -> scene position. Placing a ball also makes it visible:
// a respotted ball (foul pot, «с руки» placement) reappears after the shot
// animation hid the pocketed ones.
const setBallPositions = (positions) => {
  for (const [id, pos] of Object.entries(positions)) {
    const mesh = ballMeshes.get(id);
    if (!mesh || typeof pos.x !== 'number' || typeof pos.y !== 'number') continue;
    mesh.visible = true;
    mesh.position.set(pos.y - L / 2, BALL_R, pos.x - W / 2);
  }
};

// deterministic local fallback (same geometry as layouts.py) if the backend
// is unreachable — the scene must never render without its rack
const mulberry32 = (seed) => () => {
  seed |= 0;
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};
const localRack = () => {
  const rng = mulberry32(7);
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
        x: 0.5 * W - row * (BALL_R + 5e-4) + j * (2 * BALL_R + 1e-3),
        y: 0.75 * L + row * dy,
      };
    }
  }
  positions.cue = { x: 0.5 * W, y: 0.23 * L };
  setBallPositions(positions);
};

let rackSource = 'loading';
fetch('/api/rack?seed=7') // fixed seed for a stable demo rack (game play re-racks)
  .then((resp) => {
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.json();
  })
  .then((data) => {
    setBallPositions(data.balls);
    rackSource = 'api';
  })
  .catch(() => {
    localRack();
    rackSource = 'local-fallback';
  })
  .finally(() => {
    document.getElementById('hud-table').textContent =
      `table: ${L.toFixed(2)} × ${W.toFixed(2)} m · ${ballMeshes.size} balls ` +
      `(rack: ${rackSource}) · pockets ${(PW * 1000).toFixed(1)}/${(SW * 1000).toFixed(1)} mm`;
  });

// --- shot animation: server keyframes -> client interpolation (Step 5) ---------
// The server samples the event-based trajectory onto a 40 ms grid plus every
// event time, each keyframe being the EXACT physics state. This client
// interpolates linearly between keyframes (never a per-tick stream) and snaps
// to the authoritative final state, hiding pocketed balls on completion.
let animState = null;

const aimLine = (() => {
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
  const line = new THREE.Line(
    geo,
    new THREE.LineBasicMaterial({ color: 0xffe28a, transparent: true, opacity: 0.85 }),
  );
  line.visible = false;
  line.frustumCulled = false;
  scene.add(line);
  return line;
})();

// --- Step 10: smoothed aim (Panda3D-style sweep) --------------------------------
// The cue direction is a smoothly-approached TARGET, not a snap: lobby.js
// feeds aim targets (mouse hover over the felt), and every rendered frame
// eases the live angle toward it (exponential, frame-rate independent).
// setAim() stays the INSTANT variant (game start / cue placement / test
// hooks); setAimTarget() requests the sweep used by the live aiming UX.
let aimCur = Math.PI / 2; // live angle driving stick + aim line
let aimTgt = Math.PI / 2; // requested angle
const AIM_SMOOTH_PER_S = 14; // higher = snappier sweep
const CUE_CHARGE_TRAVEL = 0.35; // extra stick pull at 100 % charge (m)
let chargePct = null; // null = not charging (power-charge visual, Step 10)

const shortestArc = (d) =>
  (((d + Math.PI) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI) - Math.PI;

const redrawAim = () => {
  const cue = ballMeshes.get('cue');
  if (!cue || animState) return;
  const p = cue.position;
  // pooltool direction (cos φ, sin φ) in (x, y) -> world (X = y, Z = x)
  const dX = Math.sin(aimCur);
  const dZ = Math.cos(aimCur);
  const pos = aimLine.geometry.attributes.position;
  const len = 1.1;
  pos.setXYZ(0, p.x, 0.004, p.z);
  pos.setXYZ(1, p.x + dX * len, 0.004, p.z + dZ * len);
  pos.needsUpdate = true;
  aimLine.visible = true;
  if (!strikeState) {
    cueStick.visible = true;
    placeStick(
      aimCur,
      CUE_REST_PULLBACK +
        (chargePct !== null ? (chargePct / 100) * CUE_CHARGE_TRAVEL : 0),
    );
  }
};

// per-frame aim easing; also repaints while charging (stick pull follows)
const stepAim = (dtMs) => {
  if (animState) return;
  if (chargePct !== null) {
    redrawAim();
    return;
  }
  const d = shortestArc(aimTgt - aimCur);
  if (Math.abs(d) < 1e-4) {
    if (aimCur !== aimTgt) {
      aimCur = aimTgt;
      redrawAim();
    }
    return;
  }
  aimCur =
    (aimCur + d * (1 - Math.exp(-AIM_SMOOTH_PER_S * (dtMs / 1000))) +
      2 * Math.PI) %
    (2 * Math.PI);
  redrawAim();
};

const setAim = (phiRad) => {
  if (phiRad === null || phiRad === undefined || animState) {
    aimLine.visible = false;
    if (!strikeState) cueStick.visible = false; // never kill a live strike
    return;
  }
  aimTgt = aimCur = ((phiRad % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
  redrawAim();
};

const setAimTarget = (phiRad) => {
  if (phiRad === null || phiRad === undefined || animState) return;
  aimTgt = ((phiRad % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
};

// power-charge visual: the stick pulls back (and re-seats) with the drag
const setCueCharge = (pct) => {
  chargePct =
    pct === null || pct === undefined
      ? null
      : Math.max(0, Math.min(100, Number(pct) || 0));
  if (animState) return;
  if (chargePct !== null) redrawAim();
  else if (!strikeState) placeStick(aimCur, CUE_REST_PULLBACK);
};

const currentAim = () => aimCur;

// --- cue stick: aim visual + optimistic strike feedback (Step 7) ----------------
// The stroke itself stays server-authoritative (keyframes animate the real
// physics); the stick only gives INSTANT local feedback the moment Shoot is
// pressed, so the client never stares at a frozen scene waiting for the
// simulation. A lunge into the ball (130 ms, accelerating), a short
// follow-through past contact, then a fade.
const CUE_REST_PULLBACK = 0.09; // resting tip gap behind the cue ball (m)
const STRIKE_LUNGE_MS = 130;
const STRIKE_FADE_MS = 250;

const cueStick = (() => {
  const group = new THREE.Group();
  const shaftLen = 1.45;
  const shaftMat = new THREE.MeshStandardMaterial({
    color: 0x9a6a38,
    roughness: 0.5,
    metalness: 0.05,
    transparent: true,
    opacity: 0.96,
  });
  const shaft = new THREE.Mesh(
    new THREE.CylinderGeometry(0.006, 0.0105, shaftLen, 16),
    shaftMat,
  );
  shaft.rotation.x = Math.PI / 2; // cylinder Y-axis -> local +Z
  const tipMat = new THREE.MeshStandardMaterial({
    color: 0x3d6fa8,
    roughness: 0.85,
    transparent: true,
    opacity: 0.96,
  });
  const tip = new THREE.Mesh(new THREE.CylinderGeometry(0.006, 0.006, 0.014, 12), tipMat);
  tip.rotation.x = Math.PI / 2;
  group.add(shaft, tip);
  group.visible = false;
  scene.add(group);
  return group;
})();

let strikeState = null; // { t0, phi } while the strike lunge plays

const placeStick = (phiRad, pullback) => {
  const cue = ballMeshes.get('cue');
  if (!cue) return;
  const dX = Math.sin(phiRad);
  const dZ = Math.cos(phiRad);
  // hover just above the cloth, behind the cue ball, along the aim line
  cueStick.position.set(cue.position.x, 0.028, cue.position.z);
  cueStick.rotation.y = Math.atan2(dX, dZ);
  const shaft = cueStick.children[0];
  const tip = cueStick.children[1];
  shaft.position.z = -(1.45 / 2) - pullback; // spans butt .. tip at -pullback
  tip.position.z = -pullback - 0.004;
};

const playCueStrike = (phiRad) => {
  if (!ballMeshes.get('cue')) return false;
  // launch the lunge from wherever the stick currently is (a charged drag
  // sweeps into the ball from the pulled-back position)
  const startPull =
    CUE_REST_PULLBACK +
    (chargePct !== null ? (chargePct / 100) * CUE_CHARGE_TRAVEL : 0);
  chargePct = null;
  strikeState = { t0: performance.now(), phi: phiRad, startPull };
  cueStick.children[0].material.opacity = 0.96; // reset after a previous fade
  cueStick.children[1].material.opacity = 0.96;
  cueStick.visible = true;
  placeStick(phiRad, startPull);
  return true;
};

const stepCueStrike = () => {
  const s = strikeState;
  const t = performance.now() - s.t0;
  if (t >= STRIKE_LUNGE_MS + STRIKE_FADE_MS) {
    strikeState = null;
    cueStick.visible = false;
    return;
  }
  if (t <= STRIKE_LUNGE_MS) {
    const u = t / STRIKE_LUNGE_MS;
    placeStick(s.phi, s.startPull * (1 - u * u)); // accelerate into contact
  } else {
    // follow-through past contact + fade out
    const v = (t - STRIKE_LUNGE_MS) / STRIKE_FADE_MS;
    placeStick(s.phi, -0.06 * v);
    const opacity = 0.96 * (1 - v);
    cueStick.children[0].material.opacity = opacity;
    cueStick.children[1].material.opacity = opacity;
  }
};

const raycaster = new THREE.Raycaster();
const ndc = new THREE.Vector2();
const tablePoint = (clientX, clientY) => {
  const rect = canvas.getBoundingClientRect();
  ndc.x = ((clientX - rect.left) / rect.width) * 2 - 1;
  ndc.y = -((clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(ndc, camera);
  if (raycaster.ray.direction.y >= -1e-6) return null; // pointing up
  const t = -raycaster.ray.origin.y / raycaster.ray.direction.y; // plane y=0
  const hit = raycaster.ray.origin
    .clone()
    .addScaledVector(raycaster.ray.direction, t);
  const px = hit.z + W / 2; // world -> pooltool
  const py = hit.x + L / 2;
  if (px < -0.1 || px > W + 0.1 || py < -0.1 || py > L + 0.1) return null;
  return { x: px, y: py };
};

const finishAnimation = () => {
  const a = animState;
  const last = a.frames[a.frames.length - 1];
  for (let i = 0; i < a.ids.length; i++) {
    const mesh = ballMeshes.get(a.ids[i]);
    if (!mesh) continue;
    mesh.position.set(last[2 + 2 * i] - L / 2, BALL_R, last[1 + 2 * i] - W / 2);
  }
  for (const id of a.pocketed) {
    const mesh = ballMeshes.get(id);
    if (mesh) mesh.visible = false;
  }
  animState = null;
  if (a.onDone) a.onDone();
};

const stepAnimation = () => {
  const a = animState;
  const now = performance.now() - a.t0;
  const times = a.times;
  const n = times.length;
  if (now >= times[n - 1]) {
    finishAnimation();
    return;
  }
  // binary search: times[lo] <= now < times[hi]
  let lo = 0;
  let hi = n - 1;
  while (lo + 1 < hi) {
    const mid = (lo + hi) >> 1;
    if (times[mid] <= now) lo = mid;
    else hi = mid;
  }
  const t0 = times[lo];
  const t1 = times[hi];
  const u = t1 > t0 ? (now - t0) / (t1 - t0) : 0;
  const f0 = a.frames[lo];
  const f1 = a.frames[hi];
  for (let i = 0; i < a.ids.length; i++) {
    const mesh = ballMeshes.get(a.ids[i]);
    if (!mesh) continue;
    const o = 1 + 2 * i;
    const px = f0[o] + (f1[o] - f0[o]) * u; // pooltool x
    const py = f0[o + 1] + (f1[o + 1] - f0[o + 1]) * u; // pooltool y
    mesh.position.set(py - L / 2, BALL_R, px - W / 2);
  }
};

const playKeyframes = (kf, onDone) => {
  if (
    !kf ||
    !Array.isArray(kf.ids) ||
    !Array.isArray(kf.frames) ||
    kf.frames.length < 2
  ) {
    return false;
  }
  if (animState) finishAnimation(); // a new shot supersedes a running one
  animState = {
    ids: kf.ids,
    frames: kf.frames,
    times: kf.frames.map((row) => row[0]),
    pocketed: Array.isArray(kf.pocketed) ? kf.pocketed : [],
    t0: performance.now(),
    onDone: typeof onDone === 'function' ? onDone : null,
  };
  aimLine.visible = false;
  cueStick.visible = false;
  strikeState = null;
  if (document.hidden) {
    // A hidden tab cannot render: jump to the authoritative final state so
    // positions are correct the moment the tab returns.
    finishAnimation();
  }
  return true;
};

document.addEventListener('visibilitychange', () => {
  if (!document.hidden && animState) finishAnimation();
});

const showAllBalls = () => {
  animState = null;
  aimLine.visible = false;
  for (const mesh of ballMeshes.values()) mesh.visible = true;
};

// --- Step 8: camera presets, smooth switching, aspect-safe framing --------------
// Four named views (orbit = free/spectator, top, and one elevated view per
// player end). Every preset computes its distance from the CURRENT viewport
// aspect (ui_math.js), so the whole table stays in frame from a portrait
// phone to an ultra-wide monitor. Switching tweens position + target with a
// cubic ease; ANY user interaction (OrbitControls 'start') cancels the tween
// and hands control back — the camera must never fight the user.
const FRAME_SX = L + 2 * OUTER; // framed plan size incl. the wooden frame
const FRAME_SZ = W + 2 * OUTER;
const SPHERE_R = 2.35; // bounding sphere of bed + rails at the orbit target
const ORBIT_ELEV = (33 * Math.PI) / 180; // default angled view elevation
const PLAYER_ELEV = (26 * Math.PI) / 180; // TV-style end-on view elevation
const VIEW_NAMES = ['orbit', 'top', 'south', 'north'];
const VIEW_LABELS = { orbit: 'Orbit', top: 'Top', south: 'Head end', north: 'Foot end' };
const VIEW_STORAGE_KEY = 'pyr_view';

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

// preset -> { position, target } for the current viewport aspect
const computeView = (name, aspect) => {
  if (name === 'top') {
    const d = topViewDistance(FRAME_SX, FRAME_SZ, FOV_DEG, aspect, 1.04);
    return {
      position: new THREE.Vector3(0, d, 0.0001),
      target: new THREE.Vector3(0, 0, 0),
    };
  }
  if (name === 'south' || name === 'north') {
    const d = fitDistance(SPHERE_R, FOV_DEG, aspect, 1.05);
    const endX = (name === 'south' ? -1 : 1) * d * Math.cos(PLAYER_ELEV);
    return {
      position: new THREE.Vector3(endX, d * Math.sin(PLAYER_ELEV) - 0.1, 0),
      target: new THREE.Vector3(0, -0.1, 0),
    };
  }
  // 'orbit': the default angled view; clamp keeps it cinematic on desktop
  // while the fit distance guarantees the table fits on extreme aspects.
  const d = clamp(fitDistance(SPHERE_R, FOV_DEG, aspect, 1.0), 3.9, 9.5);
  return {
    position: new THREE.Vector3(
      0,
      d * Math.sin(ORBIT_ELEV),
      d * Math.cos(ORBIT_ELEV),
    ),
    target: new THREE.Vector3(0, -0.05, 0),
  };
};

let camTween = null; // { t0, dur, fromPos, toPos, fromTgt, toTgt }
let activeView = null; // preset name, or null once the user takes over

const cancelCamTween = () => {
  camTween = null;
  activeView = null; // user input => free orbiting takes precedence
};

const applyViewNow = (name) => {
  const aspect = window.innerWidth / Math.max(1, window.innerHeight);
  const v = computeView(name, aspect);
  camera.position.copy(v.position);
  controls.target.copy(v.target);
  controls.update();
  // keep the hall fog relative to the framing: a portrait top view stands
  // ~13 m away, and the fixed 9..22 range would fog the table out
  const d = camera.position.distanceTo(controls.target);
  scene.fog.near = d * 1.6;
  scene.fog.far = d * 3.4;
};

const setView = (name, opts = {}) => {
  if (!VIEW_NAMES.includes(name)) return false;
  activeView = name;
  try {
    localStorage.setItem(VIEW_STORAGE_KEY, name);
  } catch {
    /* private mode: persistence is best-effort */
  }
  if (opts.instant) {
    camTween = null;
    applyViewNow(name);
    return true;
  }
  const v = computeView(name, window.innerWidth / Math.max(1, window.innerHeight));
  camTween = {
    t0: performance.now(),
    dur: 850,
    fromPos: camera.position.clone(),
    toPos: v.position,
    fromTgt: controls.target.clone(),
    toTgt: v.target,
  };
  return true;
};

const stepCamTween = () => {
  const tw = camTween;
  const u = easeInOutCubic((performance.now() - tw.t0) / tw.dur);
  camera.position.lerpVectors(tw.fromPos, tw.toPos, u);
  controls.target.lerpVectors(tw.fromTgt, tw.toTgt, u);
  if (u >= 1) camTween = null;
};

// user grabs the camera mid-tween -> the tween loses immediately
controls.addEventListener('start', cancelCamTween);

// --- Step 10: player-control switching + cue-ball camera follow -----------------
// While it is the player's turn the LEFT button is reserved for the power
// charge (lobby.js) and one-finger touch aims — so the camera orbit moves to
// the RIGHT button (mouse) / two fingers (touch); the wheel keeps zooming.
// The orbit target also drifts (lerped) onto the cue ball, so orbiting
// inspects the actual stroke position ("camera orbits the cue ball"). Any
// camera preset button re-frames and the follow re-centers from there.
controls.mouseButtons.RIGHT = THREE.MOUSE.ROTATE;
let cueCamFollow = false;

const setPlayerControl = (on) => {
  controls.mouseButtons.LEFT = on ? -1 : THREE.MOUSE.ROTATE;
  controls.touches.ONE = on ? -1 : THREE.TOUCH.ROTATE;
};

const setCueCamFollow = (on) => {
  cueCamFollow = Boolean(on);
};

// re-frame the active preset on viewport changes (instant: a resize wants
// the new framing NOW, not an animation); free-orbited views are untouched
window.addEventListener('resize', () => {
  if (activeView && !camTween) applyViewNow(activeView);
});

// restore the persisted view (or default to the angled orbit view)
try {
  const saved = localStorage.getItem(VIEW_STORAGE_KEY);
  setView(VIEW_NAMES.includes(saved) ? saved : 'orbit', { instant: true });
} catch {
  setView('orbit', { instant: true });
}

// keyboard shortcuts 1..4 (ignored while typing in lobby inputs)
document.addEventListener('keydown', (ev) => {
  if (ev.defaultPrevented || ev.ctrlKey || ev.altKey || ev.metaKey) return;
  if (/input|select|textarea/i.test(ev.target?.tagName || '')) return;
  const idx = ['1', '2', '3', '4'].indexOf(ev.key);
  if (idx >= 0) setView(VIEW_NAMES[idx]);
});

// --- HUD: three.js + backend health --------------------------------------------
document.getElementById('hud-three').textContent =
  `three.js r${THREE.REVISION} (vendored 0.187.0)`;

fetch('/api/health')
  .then((resp) => resp.json())
  .then((data) => {
    document.getElementById('hud-backend').textContent =
      `backend: ${data.status} · ${data.service} v${data.version} · ` +
      `engine ${data.physics_ready ? 'ready' : 'warming'}`;
  })
  .catch(() => {
    document.getElementById('hud-backend').textContent = 'backend: unreachable';
  });

// --- resize (canvas) + render loop ------------------------------------------------
window.addEventListener('resize', () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

let lastFrameMs = performance.now();
renderer.setAnimationLoop(() => {
  const now = performance.now();
  const dtMs = Math.min(100, now - lastFrameMs); // clamp tab-switch spikes
  lastFrameMs = now;
  if (camTween) stepCamTween();
  if (cueCamFollow && !camTween) {
    const cue = ballMeshes.get('cue');
    if (cue) {
      const k = 1 - Math.exp(-6 * (dtMs / 1000));
      controls.target.lerp(
        new THREE.Vector3(cue.position.x, BALL_R, cue.position.z),
        k,
      );
    }
  }
  controls.update();
  stepAim(dtMs);
  if (animState) stepAnimation();
  if (strikeState) stepCueStrike();
  renderer.render(scene, camera);
});

// --- test/debug hooks (used by the screenshot verification scripts) -----------
// Usage from the browser console or agent-browser eval:
//   window.__pyramid.setView('orbit'|'top'|'south'|'north' [, {instant}])
//   window.__pyramid.currentView()     — active preset name (null = free)
//   window.__pyramid.camBusy()         — a view tween is playing
//   window.__pyramid.setTopView()      — legacy hook = instant top view
//   window.__pyramid.setAngledView()   — legacy hook = instant orbit view
//   window.__pyramid.setPocketZoom(i)  — close-up of pocket i (0..5)
//   window.__pyramid.setBallView(id)   — close-up reading a ball's number
//   window.__pyramid.stats()           — scene summary
//   window.__pyramid.ballPositions()   — current ball placements
window.__pyramid = {
  setView,
  views: () => [...VIEW_NAMES],
  viewLabels: () => ({ ...VIEW_LABELS }),
  currentView: () => activeView,
  camBusy: () => camTween !== null,
  setTopView() {
    setView('top', { instant: true });
  },
  setAngledView() {
    setView('orbit', { instant: true });
  },
  setPocketZoom(i) {
    cancelCamTween(); // debug views are free-orbit: survive resizes
    const p = pocketWells[Math.max(0, Math.min(5, i | 0))] || pocketWells[4];
    camera.position.set(p.x, 1.1, p.z + 0.0001);
    controls.target.set(p.x, 0, p.z);
    controls.update();
  },
  setBallView(id) {
    cancelCamTween(); // debug views are free-orbit: survive resizes
    const mesh = ballMeshes.get(String(id)) || cueMesh;
    const p = mesh.position;
    camera.position.set(p.x + 0.28, 0.22, p.z + 0.28);
    controls.target.set(p.x, BALL_R, p.z);
    controls.update();
  },
  frameCheck() {
    // geometry self-test for the unified frame (all distances in mm):
    //  - clearance between the inner contour and every pocket well circle
    //  - min gap between the inner contour and the cushion contours (>0:
    //    wood and rubber never interpenetrate)
    //  - the inner contour stays strictly inside the outer perimeter
    const holePts = shapeFromOps(frameHoleOps).getPoints(64);
    const cushPts = cushionShapes.flatMap((s) => s.getPoints(32));
    const dist2 = (ax, ay, bx, by) => Math.hypot(ax - bx, ay - by);
    let corner = 9,
      middle = 9,
      cush = 9,
      inside = true;
    for (const p of holePts) {
      for (const [cx, cy, r] of WELL_CENTERS) {
        const d = dist2(p.x, p.y, cx, cy) - r;
        const isCorner = r === PR;
        if (isCorner) corner = Math.min(corner, d);
        else middle = Math.min(middle, d);
      }
      for (const q of cushPts) cush = Math.min(cush, dist2(p.x, p.y, q.x, q.y));
      if (
        p.x < -OUTER + 1e-4 ||
        p.x > W + OUTER - 1e-4 ||
        p.y < -OUTER + 1e-4 ||
        p.y > L + OUTER - 1e-4
      ) {
        inside = false;
      }
    }
    return {
      cornerClearanceMm: Number((corner * 1000).toFixed(2)),
      middleClearanceMm: Number((middle * 1000).toFixed(2)),
      cushionGapMm: Number((cush * 1000).toFixed(2)),
      holeInsideOuter: inside,
      frameMeshes: frameMesh ? 1 : 0,
    };
  },
  stats() {
    let meshes = 0;
    scene.traverse((obj) => {
      if (obj.isMesh) meshes += 1;
    });
    return {
      meshes,
      balls: ballMeshes.size,
      rackSource,
      pockets: pocketWells.length,
      unifiedFrame: true,
      cornerMouthMm: Number((PW * 1000).toFixed(1)),
      middleMouthMm: Number((SW * 1000).toFixed(1)),
      ballDiameterMm: Math.round(2 * BALL_R * 1000),
      cushionHeightMm: Math.round(CUSH_H * 1000),
      tableHeightCm: Math.round(TABLE_H * 100),
      tableM: [L, W],
      cushions: 6,
    };
  },
  ballPositions() {
    const out = {};
    for (const [id, mesh] of ballMeshes) {
      out[id] = { x: mesh.position.x, z: mesh.position.z };
    }
    return out;
  },
  setBallPositions,
  playKeyframes,
  isAnimating: () => animState !== null,
  playCueStrike,
  stickVisible: () => cueStick.visible,
  setAim,
  setAimTarget,
  currentAim,
  setCueCharge,
  setPlayerControl,
  setCueCamFollow,
  tablePoint,
  showAllBalls,
  setBallInHand,
};
