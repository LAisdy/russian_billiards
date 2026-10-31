// Numeric cross-check of the unified-frame wrap arc math (mirrors main.js).
const L = 3.7,
  W = 1.8,
  CUSH_W = 0.05,
  PR = 0.045,
  SR = 0.044,
  CD = 0.045 / Math.SQRT2,
  SD = 0.05;
const CLR_C = PR + 0.003;
const CLR_S = SR + 0.0015;
const wrapRun = Math.sqrt(CLR_C ** 2 - (CUSH_W - CD) ** 2);
const depX = -CD + wrapRun;
const DELTA = Math.atan2(CUSH_W - CD, wrapRun);
const SWEEP = 1.5 * Math.PI - 2 * DELTA;
console.log(
  'wrapRun', wrapRun.toFixed(6),
  'depX', depX.toFixed(6),
  'DELTA_deg', ((DELTA * 180) / Math.PI).toFixed(3),
  'SWEEP_deg', ((SWEEP * 180) / Math.PI).toFixed(3),
);

const pt = (cx, cy, a) => [cx + CLR_C * Math.cos(a), cy + CLR_C * Math.sin(a)];
let ok = true;
for (const [name, cx, cy, a0] of [
  ['BL', -CD, -CD, Math.PI / 2 + DELTA],
  ['BR', W + CD, -CD, -Math.PI + DELTA],
  ['TR', W + CD, L + CD, -Math.PI / 2 + DELTA],
  ['TL', -CD, L + CD, DELTA],
]) {
  const [x0, y0] = pt(cx, cy, a0);
  const [x1, y1] = pt(cx, cy, a0 + SWEEP);
  const e = 1e-9;
  const railX = (x) => Math.abs(Math.abs(x) - (x < 0 ? CUSH_W : W + CUSH_W)) < e;
  const railY = (y) => Math.abs(Math.abs(y) - (y < 0 ? CUSH_W : L + CUSH_W)) < e ||
    Math.abs(y - (cy < L / 2 ? -CUSH_W : L + CUSH_W)) < e;
  const startOk = railX(x0) || railY(y0);
  const endOk = railX(x1) || railY(y1);
  console.log(
    name,
    'start', x0.toFixed(6), y0.toFixed(6),
    'end', x1.toFixed(6), y1.toFixed(6),
    'onRails:', startOk && endOk,
  );
  ok = ok && startOk && endOk;
}
// min clearance from the wrap arcs to the well circles (by construction)
console.log('corner clearance:', ((CLR_C - PR) * 1000).toFixed(2), 'mm; middle:', ((CLR_S - SR) * 1000).toFixed(2), 'mm');
// dense sample: min distance from the whole wrap arc to the well circle
let minD = 9;
for (const [cx, cy, a0] of [
  [-CD, -CD, Math.PI / 2 + DELTA],
  [W + CD, -CD, -Math.PI + DELTA],
  [W + CD, L + CD, -Math.PI / 2 + DELTA],
  [-CD, L + CD, DELTA],
]) {
  for (let i = 0; i <= 720; i++) {
    const a = a0 + (SWEEP * i) / 720;
    const [x, y] = pt(cx, cy, a);
    minD = Math.min(minD, Math.hypot(x - cx, y - cy) - PR);
  }
}
console.log('sampled min wrap->well clearance:', (minD * 1000).toFixed(3), 'mm (expect 3.0)');
console.log(ok ? 'WRAP ENDPOINTS ON RAIL EDGES: OK' : 'WRAP ENDPOINT MISMATCH');
