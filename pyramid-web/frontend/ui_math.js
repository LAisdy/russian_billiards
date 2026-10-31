// pyramid-web — pure UI & camera math (Step 8).
//
// Deliberately DOM-free and three.js-free so it can be unit-tested directly
// in Node (`node scripts/test_step8_ui_math.mjs`): camera fit distances,
// tween easing, clock formatting and the HUD-state derivation shared by
// main.js (camera) and lobby.js (HUD bar).

// Camera vertical field of view — must match the PerspectiveCamera in main.js.
export const FOV_DEG = 50;

const RAD = Math.PI / 180;

// Horizontal fov for a vertical fov + viewport aspect (width / height).
export function hFovDeg(vFovDeg, aspect) {
  return 2 * Math.atan(Math.tan((vFovDeg / 2) * RAD) * aspect) / RAD;
}

/**
 * Distance at which a bounding sphere of `radius` (centered on the orbit
 * target) fits the whole frustum. Exact fit: d = R / sin(min(fov)/2);
 * `margin` > 1 leaves breathing room. Valid at ANY viewport aspect.
 */
export function fitDistance(radius, vFovDeg, aspect, margin = 1.06) {
  const vHalf = Math.abs((vFovDeg / 2) * RAD);
  const hHalf = Math.abs((hFovDeg(vFovDeg, aspect) / 2) * RAD);
  const half = Math.min(vHalf, hHalf);
  if (half <= 0 || radius <= 0) return Infinity;
  return (radius / Math.sin(half)) * margin;
}

/**
 * Straight-down (top) view: the table is a flat rectangle of sizeX x sizeZ
 * on the ground plane; the vertical screen axis maps to sizeZ and the
 * horizontal axis to sizeX. Returns the minimal camera height so both fit.
 */
export function topViewDistance(sizeX, sizeZ, vFovDeg, aspect, margin = 1.06) {
  const tanHalf = Math.abs(Math.tan((vFovDeg / 2) * RAD));
  if (tanHalf <= 0 || aspect <= 0) return Infinity;
  const needZ = sizeZ / (2 * tanHalf);
  const needX = sizeX / (2 * tanHalf * aspect);
  return Math.max(needZ, needX) * margin;
}

// Smooth 0..1 ease for camera tweens (cubic in-out), clamped outside [0,1].
export function easeInOutCubic(t) {
  if (!(t > 0)) return 0;
  if (t >= 1) return 1;
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

// Elapsed ms -> "m:ss" (never negative, NaN-safe).
export function formatElapsed(ms) {
  const total = Number.isFinite(ms) && ms > 0 ? Math.floor(ms / 1000) : 0;
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

// Object-ball ids 1..15 in rack order (the cue ball is never a chip).
export const ALL_BALL_IDS = Array.from({ length: 15 }, (_, i) => String(i + 1));

/**
 * Remaining-ball chips for the HUD: [{ id, onTable }] for 1..15, ordered.
 * `balls` is the authoritative on-table state ({id: {x, y}}) — pocketed and
 * penalty-removed balls are absent from it. `null` balls (pre-game) = all on.
 */
export function ballChips(balls) {
  return ALL_BALL_IDS.map((id) => ({
    id,
    onTable: !balls || Boolean(balls[id]),
  }));
}

/**
 * Aggregate the server game snapshot + on-table balls into the flat state
 * the HUD bar renders. Returns null when there is no game (HUD hidden).
 *
 * `nowServerMs` — the caller's skew-corrected "server now" (client
 * Date.now() + the offset captured when the snapshot arrived:
 * offset = snapshot.now_ms - Date.now()). Falls back to the snapshot's own
 * stamp when omitted, so the clock still shows the right base value.
 */
export function deriveHud(game, balls, playerId, nowServerMs = null) {
  if (!game) return null;
  const scores = Array.isArray(game.scores) ? game.scores : [];
  const turnId = game.turn ? game.turn.id : null;

  const start = Number(game.turn_started_ms);
  const stampedNow = Number(game.now_ms);
  let clockMs = null;
  const liveNow = Number.isFinite(nowServerMs) ? nowServerMs : stampedNow;
  if (
    Number.isFinite(start) &&
    start > 0 &&
    Number.isFinite(liveNow) &&
    liveNow >= start
  ) {
    clockMs = liveNow - start;
  }

  const chips = ballChips(balls);
  // pooltool counts shots/turns from 0 (0 = the break) — display 1-based.
  const shotNum = Number.isFinite(game.shot_number) ? game.shot_number + 1 : null;
  const turnNum = Number.isFinite(game.turn_number) ? game.turn_number + 1 : null;
  return {
    modeLine: `${game.mode_name || '?'} · first to ${game.target_score ?? '?'}`,
    shotLine:
      shotNum !== null && turnNum !== null
        ? `shot ${shotNum} · turn ${turnNum}`
        : '',
    gameOver: Boolean(game.game_over),
    targetScore: game.target_score ?? null,
    players: scores.map((s) => ({
      id: s.id,
      name: s.name,
      score: s.score,
      isTurn: s.id === turnId && !game.game_over,
      isMe: s.id === playerId,
    })),
    clockMs,
    remainingCount: chips.filter((c) => c.onTable).length,
    chips,
  };
}
