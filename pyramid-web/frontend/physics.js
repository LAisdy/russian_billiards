// pyramid-web — client-side billiards physics (Step 11 architecture change).
//
// The server no longer runs pooltool physics for gameplay: when a player
// shoots, THIS module simulates the stroke instantly in the shooter's
// browser (cannon-es, vendored in ./vendor/cannon-es.js), animates it at
// 60 FPS, and only the FINAL resting state + game events travel over the
// WebSocket (see backend/app/bridge.py which turns them into the synthetic
// pooltool System the frozen rulesets judge).
//
// Fidelity contract with the pooltool table (RUSSIAN_PYRAMID_GENERIC):
// every linear cushion segment (18) and circular jaw arc (12) of
// pooltool/objects/table/layout.py::create_pocket_table_cushion_segments is
// replicated here as a static collider with the SAME id, so cushion-contact
// events reported to the rulesets use the real segment ids. Pocket ids
// (lb/lc/lt/rb/rc/rt) and well centers come from the same spec.
//
// POCKETS — the "ball stuck half-inside the pocket" bug is impossible here
// by construction (user requirement):
//   1. Pocket holes contain NO solid collision geometry.
//   2. Each pocket has an invisible trigger zone (sensor body,
//      collisionResponse = false) centered on the well.
//   3. The moment a ball CENTER enters the zone (|center - well| < CAPTURE_R)
//      the ball is marked pocketed, its body is removed from the world and
//      its mesh plays a short drop animation. A ball can never rest on a
//      pocket edge or jam in the jaws of the hole.
//   4. CAPTURE_R = 55 mm (well radius 45/44 mm + margin) is sized so that
//      every possible ball-center path that enters a pocket mouth crosses
//      the zone before it can reach any void behind it (worst legal rest
//      positions are ≥ 65 mm out), while a ball rolling along a rail past a
//      pocket (≥ 65 mm from the well center) is never falsely captured.
//   5. A per-substep analytic distance check duplicates the sensor events —
//      a tunneling-proof backstop (fixed dt = 1 ms keeps per-step travel at
//      ≤ 8 mm << zone diameter), and invisible back walls behind every well
//      guarantee no ball can ever leave the world even if capture were
//      somehow missed (it would bounce back into the zone).
//
// Planar model: billiard balls roll on a plane — gravity is zero, every
// body is constrained to y = BALL_R (vy zeroed after each substep) and the
// rolling visual comes from omega = (v x up) / R. Cloth resistance is a
// constant deceleration (real rolling behaviour), not exponential damping.
// Everything is deterministic: fixed timestep, no randomness, no Math.random.

import * as CANNON from './vendor/cannon-es.js';

// --- equipment (pooltool RUSSIAN_PYRAMID_GENERIC, mirrors app/physics.py) ----
export const TABLE_L = 3.7; // playing surface length (m)
export const TABLE_W = 1.8; // playing surface width (m)
export const BALL_R = 0.0335; // ball radius (Ø 67 mm)
export const BALL_MASS = 0.255; // kg

// --- pocket capture (see header) ----------------------------------------------
export const CAPTURE_R = 0.055; // trigger zone radius around each well (m)
export const SENSOR_R = CAPTURE_R - BALL_R; // shape radius => center-entry semantics

// --- motion model ---------------------------------------------------------------
export const FIXED_DT = 1 / 1000; // fixed simulation step (s)
export const CLOTH_DECEL = 0.75; // rolling deceleration on the cloth (m/s^2)
export const STOP_SPEED = 0.03; // below this speed a ball is snapped to rest
export const SETTLE_TIME = 0.25; // stillness duration before the shot ends (s)
export const MAX_SHOT_TIME = 25.0; // hard cap (s) — force-stop safety net
export const MAX_BALL_SPEED = 8.0; // client clamp; server API range is 10

// ball-ball / ball-cushion contact behaviour
const BALL_BALL_RESTITUTION = 0.94;
const BALL_BALL_FRICTION = 0.03;
const BALL_CUSHION_RESTITUTION = 0.72;
const BALL_CUSHION_FRICTION = 0.12;
const CUSHION_BOX_H = 0.06; // collider height (m), centered on ball height
const CUSHION_BOX_D = 0.05; // collider depth behind the face (m)

// --- table geometry: pooltool create_pocket_table_cushion_segments --------------
// linear segments [id, x1, y1, x2, y2] (m) — noses, corner jaws (45°), and
// the middle-pocket jaw backs, exactly as the vendored spec.
const LINEAR_SEGMENTS = [
  ['1', 0.0013, -0.05, 0.0469, -0.0044],
  ['2', -0.05, 0.0013, -0.0044, 0.0469],
  ['3', 0.0, 0.0575, 0.0, 1.8008],
  ['4', -0.05, 1.8088, -0.008, 1.8088],
  ['5', -0.05, 1.8913, -0.008, 1.8913],
  ['6', 0.0, 1.8993, 0.0, 3.6425],
  ['7', -0.05, 3.6987, -0.0044, 3.6531],
  ['8', 0.0013, 3.75, 0.0469, 3.7044],
  ['9', 0.0575, 3.7, 1.7425, 3.7],
  ['10', 1.7987, 3.75, 1.7531, 3.7044],
  ['11', 1.85, 3.6987, 1.8044, 3.6531],
  ['12', 1.8, 1.8993, 1.8, 3.6425],
  ['13', 1.85, 1.8913, 1.808, 1.8913],
  ['14', 1.85, 1.8088, 1.808, 1.8088],
  ['15', 1.8, 0.0575, 1.8, 1.8008],
  ['16', 1.85, 0.0013, 1.8044, 0.0469],
  ['17', 1.7987, -0.05, 1.7531, -0.0044],
  ['18', 0.0575, 0.0, 1.7425, 0.0],
];

// circular jaw arcs [id, cx, cy, r] (m) — corner jaw tips (r=15 mm) and
// middle jaw tips (r=8 mm).
const CIRCULAR_SEGMENTS = [
  ['1t', 0.0575, -0.015, 0.015],
  ['2t', -0.015, 0.0575, 0.015],
  ['4t', -0.008, 1.8008, 0.008],
  ['5t', -0.008, 1.8993, 0.008],
  ['7t', -0.015, 3.6425, 0.015],
  ['8t', 0.0575, 3.715, 0.015],
  ['10t', 1.7425, 3.715, 0.015],
  ['11t', 1.815, 3.6425, 0.015],
  ['13t', 1.808, 1.8993, 0.008],
  ['14t', 1.808, 1.8008, 0.008],
  ['16t', 1.815, 0.0575, 0.015],
  ['17t', 1.7425, -0.015, 0.015],
];

// pocket wells [id, cx, cy, radius] (m) — pooltool create_pocket_table_pockets
export const POCKETS = [
  ['lb', -0.0318, -0.0318, 0.045],
  ['rb', 1.8318, -0.0318, 0.045],
  ['lc', -0.05, 1.85, 0.044],
  ['rc', 1.85, 1.85, 0.044],
  ['lt', -0.0318, 3.7318, 0.045],
  ['rt', 1.8318, 3.7318, 0.045],
];

export const KNOWN_CUSHION_IDS = new Set([
  ...LINEAR_SEGMENTS.map((s) => s[0]),
  ...CIRCULAR_SEGMENTS.map((s) => s[0]),
]);
export const KNOWN_POCKET_IDS = new Set(POCKETS.map((p) => p[0]));

// physics collision filter groups
const GROUP_BALL = 1;
const GROUP_CUSHION = 2;
const GROUP_SENSOR = 4;

const round4 = (v) => Math.round(v * 1e4) / 1e4;
const round3 = (v) => Math.round(v * 1e3) / 1e3;

export class PyramidPhysics {
  constructor() {
    this.world = this._buildWorld();
    this.ballBodies = new Map(); // id -> CANNON.Body
    this.simulating = false;
    this.done = true;
    this.onCapture = null; // (info: {ball, pocket, t}) => void
    this.onDone = null; // (result) => void
    this.shot = null;
    this._acc = 0; // fixed-step accumulator (s)
    this._settle = 0; // stillness timer (s)
    this._pendingCaptures = [];
    this._result = null;
  }

  // --- world construction -------------------------------------------------------

  _buildWorld() {
    const world = new CANNON.World({ gravity: new CANNON.Vec3(0, 0, 0) });
    world.broadphase = new CANNON.SAPBroadphase(world);
    world.allowSleep = false;
    world.solver.iterations = 14;

    const ballMat = new CANNON.Material('ball');
    const cushMat = new CANNON.Material('cushion');
    this._ballMat = ballMat;
    world.addContactMaterial(
      new CANNON.ContactMaterial(ballMat, ballMat, {
        restitution: BALL_BALL_RESTITUTION,
        friction: BALL_BALL_FRICTION,
      }),
    );
    world.addContactMaterial(
      new CANNON.ContactMaterial(ballMat, cushMat, {
        restitution: BALL_CUSHION_RESTITUTION,
        friction: BALL_CUSHION_FRICTION,
      }),
    );

    this._addCushions(world, cushMat);
    this._addPocketSensors(world);
    this._addPocketBackWalls(world, cushMat);

    // trigger + bookkeeping events
    world.addEventListener('beginContact', (ev) => this._onBeginContact(ev));
    return world;
  }

  _addCushions(world, cushMat) {
    // static bodies are only created once — the table never changes
    const EPS = 0.001;
    const inRect = (x, y) =>
      x >= -1e-9 && x <= TABLE_W + 1e-9 && y >= -1e-9 && y <= TABLE_L + 1e-9;
    for (const [id, x1, y1, x2, y2] of LINEAR_SEGMENTS) {
      const dx = x2 - x1;
      const dy = y2 - y1;
      const len = Math.hypot(dx, dy);
      const dirX = dx / len;
      const dirY = dy / len;
      const mx = (x1 + x2) / 2;
      const my = (y1 + y2) / 2;
      // The face normal must point to the side BALLS can occupy:
      //  - segments on the playfield boundary (the six noses): face the
      //    rectangle interior (the box body sits outside the playfield);
      //  - segments outside the rectangle (corner jaws, middle jaw backs):
      //    face their nearest pocket well (balls occupy the throat side).
      let nx = -dirY;
      let ny = dirX;
      if (inRect(x1, y1) && inRect(x2, y2)) {
        const tx = Math.min(TABLE_W - EPS, Math.max(EPS, mx));
        const ty = Math.min(TABLE_L - EPS, Math.max(EPS, my));
        if (nx * (tx - mx) + ny * (ty - my) < 0) {
          nx = -nx;
          ny = -ny;
        }
      } else {
        let wx = 0;
        let wy = 0;
        let best = Infinity;
        for (const [, px, py] of POCKETS) {
          const d = (px - mx) ** 2 + (py - my) ** 2;
          if (d < best) {
            best = d;
            wx = px;
            wy = py;
          }
        }
        if (nx * (wx - mx) + ny * (wy - my) < 0) {
          nx = -nx;
          ny = -ny;
        }
      }
      const bx = mx - nx * (CUSHION_BOX_D / 2);
      const by = my - ny * (CUSHION_BOX_D / 2);
      const body = new CANNON.Body({
        type: CANNON.Body.STATIC,
        material: cushMat,
        collisionFilterGroup: GROUP_CUSHION,
        collisionFilterMask: GROUP_BALL,
      });
      // local X along the segment direction; Y up; Z across
      body.addShape(
        new CANNON.Box(new CANNON.Vec3(len / 2, CUSHION_BOX_H / 2, CUSHION_BOX_D / 2)),
      );
      body.position.set(bx, CUSHION_BOX_H / 2, by);
      body.quaternion.setFromAxisAngle(new CANNON.Vec3(0, 1, 0), -Math.atan2(dirY, dirX));
      body.cushionId = id;
      body.isCircular = false;
      world.addBody(body);
    }
    for (const [id, cx, cy, r] of CIRCULAR_SEGMENTS) {
      const body = new CANNON.Body({
        type: CANNON.Body.STATIC,
        material: cushMat,
        collisionFilterGroup: GROUP_CUSHION,
        collisionFilterMask: GROUP_BALL,
      });
      body.addShape(new CANNON.Sphere(r));
      body.position.set(cx, BALL_R, cy);
      body.cushionId = id;
      body.isCircular = true;
      world.addBody(body);
    }
  }

  _addPocketSensors(world) {
    // The trigger zones: NO solid pocket colliders exist anywhere — these
    // sensor bodies only DETECT the ball center entering the pocket zone.
    for (const [id, cx, cy] of POCKETS) {
      const body = new CANNON.Body({
        type: CANNON.Body.STATIC,
        collisionFilterGroup: GROUP_SENSOR,
        collisionFilterMask: GROUP_BALL,
      });
      body.addShape(new CANNON.Sphere(SENSOR_R));
      body.position.set(cx, BALL_R, cy);
      body.collisionResponse = false; // pure trigger: balls pass through
      body.pocketId = id;
      world.addBody(body);
    }
  }

  _addPocketBackWalls(world, cushMat) {
    // Safety net only: with capture guaranteed these never trigger; if a
    // capture were ever missed a ball would bounce back into the zone
    // instead of leaving the world.
    for (const [id, cx, cy, r] of POCKETS) {
      const body = new CANNON.Body({
        type: CANNON.Body.STATIC,
        material: cushMat,
        collisionFilterGroup: GROUP_CUSHION,
        collisionFilterMask: GROUP_BALL,
      });
      const isCorner = id.length === 2;
      if (isCorner) {
        const dx = Math.sign(cx) || 1;
        const dy = Math.sign(cy) || 1;
        const len = Math.hypot(dx, dy);
        const dirX = dx / len;
        const dirY = dy / len;
        body.addShape(
          new CANNON.Box(new CANNON.Vec3(0.085, CUSHION_BOX_H / 2, 0.012)),
        );
        body.position.set(
          cx + dirX * (CAPTURE_R + 0.012),
          CUSHION_BOX_H / 2,
          cy + dirY * (CAPTURE_R + 0.012),
        );
        body.quaternion.setFromAxisAngle(
          new CANNON.Vec3(0, 1, 0),
          -Math.atan2(dirY, dirX),
        );
      } else {
        const sx = Math.sign(cx - TABLE_W / 2) || 1;
        body.addShape(
          new CANNON.Box(new CANNON.Vec3(0.012, CUSHION_BOX_H / 2, 0.065)),
        );
        body.position.set(cx + sx * (CAPTURE_R + 0.012), CUSHION_BOX_H / 2, cy);
      }
      body.cushionId = `${id}_wall`;
      body.isCircular = false;
      world.addBody(body);
    }
  }

  // --- ball bodies ---------------------------------------------------------------

  _createBall(id, x, y) {
    const body = new CANNON.Body({
      mass: BALL_MASS,
      material: this._ballMat,
      collisionFilterGroup: GROUP_BALL,
      collisionFilterMask: GROUP_BALL | GROUP_CUSHION | GROUP_SENSOR,
      linearDamping: 0, // cloth resistance is applied explicitly (constant decel)
      angularDamping: 0,
    });
    body.addShape(new CANNON.Sphere(BALL_R));
    body.position.set(x, BALL_R, y);
    body.ballId = id;
    this.world.addBody(body);
    return body;
  }

  /** Authoritative ball-state sync (game start / shot verdict / cue placement).
   *
   * positions: {id: {x, y}} in pooltool meters. Bodies for ids absent from
   * the payload are removed (pocketed balls); existing ones are repositioned
   * (a respot). Returns false while a shot is simulating.
   */
  syncBalls(positions) {
    if (this.simulating) return false;
    const keep = new Set();
    for (const [id, pos] of Object.entries(positions)) {
      if (
        !pos ||
        !Number.isFinite(pos.x) ||
        !Number.isFinite(pos.y) ||
        typeof id !== 'string' ||
        !id
      ) {
        continue;
      }
      keep.add(id);
      const body = this.ballBodies.get(id);
      if (body) {
        body.position.set(pos.x, BALL_R, pos.y);
      } else {
        this.ballBodies.set(id, this._createBall(id, pos.x, pos.y));
      }
      this._stopBody(this.ballBodies.get(id));
    }
    for (const [id, body] of [...this.ballBodies]) {
      if (!keep.has(id)) {
        this.world.removeBody(body);
        this.ballBodies.delete(id);
      }
    }
    return true;
  }

  hasBall(id) {
    return this.ballBodies.has(id);
  }

  /** Current pooltool-coords positions of every live body. */
  positions() {
    const out = {};
    for (const [id, body] of this.ballBodies) {
      out[id] = { x: body.position.x, y: body.position.z };
    }
    return out;
  }

  // --- shot lifecycle --------------------------------------------------------------

  /** Start a stroke: launch the cue ball at v0 m/s along phi (radians CCW
   * from +x, pooltool convention). Returns false when busy or no cue ball. */
  beginShot(v0, phiRad) {
    if (this.simulating || !this.done) return false;
    const cue = this.ballBodies.get('cue');
    if (!cue) return false;
    const speed = Math.max(0.05, Math.min(MAX_BALL_SPEED, Number(v0) || 0));
    const dirX = Math.cos(phiRad);
    const dirY = Math.sin(phiRad);

    this.shot = {
      v0: speed,
      phi: phiRad,
      t: 0,
      firstContact: null, // {ball, t}
      cushions: new Map(), // ballId -> Set(segment ids) after first contact
      yRange: new Map(), // ballId -> {min, max} after first contact
      pocketed: [], // [{ball, pocket, t}] in capture order
      scratch: false,
    };
    this._result = null;
    this._acc = 0;
    this._settle = 0;
    this._pendingCaptures = [];
    this.done = false;
    this.simulating = true;

    cue.wakeUp();
    cue.velocity.set(speed * dirX, 0, speed * dirY);
    this._syncRolling(cue);
    return true;
  }

  /** Advance the simulation by dtMs of real time (called from the render
   * loop). Runs fixed 1 ms substeps; returns true while the shot is alive. */
  step(dtMs) {
    if (!this.simulating) return false;
    this._acc += Math.min(100, Math.max(0, dtMs)) / 1000;
    let steps = 0;
    while (this._acc >= FIXED_DT && this.simulating) {
      this._acc -= FIXED_DT;
      this._substep();
      if (++steps > 400) break; // runaway guard (fastForward covers spikes)
    }
    return this.simulating;
  }

  /** Run the shot to completion synchronously (hidden-tab fast path). */
  fastForward() {
    if (!this.simulating) return;
    let guard = 0;
    while (this.simulating && guard++ < (MAX_SHOT_TIME / FIXED_DT) | 0) {
      this._substep();
    }
  }

  _stopBody(body) {
    body.velocity.set(0, 0, 0);
    body.angularVelocity.set(0, 0, 0);
    body.force.set(0, 0, 0);
    body.torque.set(0, 0, 0);
  }

  _syncRolling(body) {
    // rolling without slipping: omega = (v x up) / R
    const vx = body.velocity.x;
    const vz = body.velocity.z;
    body.angularVelocity.set(-vz / BALL_R, 0, vx / BALL_R);
  }

  _substep() {
    const shot = this.shot;
    const bodies = [...this.ballBodies.values()];

    // cloth resistance + rolling visual (pre-step)
    for (const body of bodies) {
      const speed = Math.hypot(body.velocity.x, body.velocity.z);
      if (speed > 0) {
        const next = speed - CLOTH_DECEL * FIXED_DT;
        if (next <= STOP_SPEED) {
          this._stopBody(body);
        } else {
          const k = next / speed;
          body.velocity.x *= k;
          body.velocity.z *= k;
          this._syncRolling(body);
        }
      }
    }

    this.world.step(FIXED_DT);

    // post-step: planar constraint + capture checks
    for (const body of bodies) {
      if (!this.ballBodies.has(body.ballId)) continue; // captured meanwhile
      if (body.position.y !== BALL_R) body.position.y = BALL_R;
      if (body.velocity.y !== 0) body.velocity.y = 0;
      this._checkCapture(body);
    }
    this._processPendingCaptures();

    if (this.simulating) {
      shot.t += FIXED_DT;
      this._trackRanges();
    }

    // quiescence: every live ball snapped to rest
    let moving = false;
    for (const body of this.ballBodies.values()) {
      if (body.velocity.x !== 0 || body.velocity.z !== 0) {
        moving = true;
        break;
      }
    }
    if (!moving) {
      this._settle += FIXED_DT;
      if (this._settle >= SETTLE_TIME) this._finish();
    } else {
      this._settle = 0;
    }
    if (this.simulating && shot.t >= MAX_SHOT_TIME) {
      for (const body of this.ballBodies.values()) this._stopBody(body);
      this._finish();
    }
  }

  // --- contacts & capture --------------------------------------------------------

  _onBeginContact(ev) {
    if (!this.simulating || !this.shot) return;
    const a = ev.bodyA;
    const b = ev.bodyB;
    if (!a || !b) return;
    if (a.pocketId && b.ballId) {
      this._pendingCaptures.push({ ball: b.ballId, pocket: a.pocketId });
    } else if (b.pocketId && a.ballId) {
      this._pendingCaptures.push({ ball: a.ballId, pocket: b.pocketId });
    } else if (a.ballId && b.ballId) {
      // ball-ball: first object ball contacted by the cue
      if (!this.shot.firstContact) {
        if (a.ballId === 'cue' && b.ballId !== 'cue') {
          this.shot.firstContact = { ball: b.ballId, t: this.shot.t };
        } else if (b.ballId === 'cue' && a.ballId !== 'cue') {
          this.shot.firstContact = { ball: a.ballId, t: this.shot.t };
        }
      }
    } else if (a.cushionId && b.ballId) {
      this._recordCushion(b.ballId, a.cushionId);
    } else if (b.cushionId && a.ballId) {
      this._recordCushion(a.ballId, b.cushionId);
    }
  }

  _recordCushion(ballId, cushionId) {
    const shot = this.shot;
    // only contacts at/after the cue's first object contact matter to the
    // rulesets (they filter by `after = first_contact.t` anyway)
    if (!shot.firstContact) return;
    let set = shot.cushions.get(ballId);
    if (!set) {
      set = new Set();
      shot.cushions.set(ballId, set);
    }
    set.add(cushionId);
  }

  _checkCapture(body) {
    // Analytic backstop for the sensor triggers: exact center-entry test
    // every substep (per-step travel <= 8 mm << zone diameter => a fast ball
    // cannot tunnel past the zone unnoticed).
    for (const [pid, cx, cy] of POCKETS) {
      const dx = body.position.x - cx;
      const dy = body.position.z - cy;
      if (dx * dx + dy * dy < CAPTURE_R * CAPTURE_R) {
        this._pendingCaptures.push({ ball: body.ballId, pocket: pid });
        return;
      }
    }
  }

  _processPendingCaptures() {
    if (!this._pendingCaptures.length) return;
    const removed = new Set();
    for (const cap of this._pendingCaptures) {
      const body = this.ballBodies.get(cap.ball);
      if (!body || removed.has(cap.ball)) continue; // already gone
      removed.add(cap.ball);
      this.shot.pocketed.push({
        ball: cap.ball,
        pocket: cap.pocket,
        t: this.shot.t,
      });
      if (cap.ball === 'cue') this.shot.scratch = true;
      this.world.removeBody(body);
      this.ballBodies.delete(cap.ball);
      if (this.onCapture) {
        try {
          this.onCapture({ ball: cap.ball, pocket: cap.pocket, t: this.shot.t });
        } catch (err) {
          console.error('[pyramid-physics] onCapture handler failed', err);
        }
      }
    }
    this._pendingCaptures = [];
  }

  _trackRanges() {
    const shot = this.shot;
    if (!shot.firstContact) return; // ranges only count post-contact motion
    for (const body of this.ballBodies.values()) {
      const y = body.position.z;
      const range = shot.yRange.get(body.ballId);
      if (!range) {
        shot.yRange.set(body.ballId, { min: y, max: y });
      } else {
        if (y < range.min) range.min = y;
        if (y > range.max) range.max = y;
      }
    }
  }

  // --- finish & result -------------------------------------------------------------

  _finish() {
    if (!this.simulating) return;
    this.simulating = false;
    this.done = true;
    this._result = this._buildResult();
    if (this.onDone) {
      const cb = this.onDone;
      this.onDone = null;
      try {
        cb(this._result);
      } catch (err) {
        console.error('[pyramid-physics] onDone handler failed', err);
      }
    }
  }

  _buildResult() {
    const shot = this.shot;
    const final = {};
    for (const [id, body] of this.ballBodies) {
      final[id] = { x: round4(body.position.x), y: round4(body.position.z) };
    }
    const cushions = {};
    for (const [ballId, set] of shot.cushions) cushions[ballId] = [...set];
    const yRange = {};
    for (const [ballId, range] of shot.yRange) {
      if (range.max - range.min > 1e-9) {
        yRange[ballId] = { min: round4(range.min), max: round4(range.max) };
      }
    }
    return {
      v0: round3(shot.v0),
      phi: round3(shot.phi),
      duration: round3(shot.t),
      final,
      pocketed: shot.pocketed.map((p) => ({
        ball: p.ball,
        pocket: p.pocket,
        t: round3(p.t),
      })),
      scratch: shot.scratch,
      first_contact: shot.firstContact
        ? { ball: shot.firstContact.ball, t: round3(shot.firstContact.t) }
        : null,
      cushions,
      y_range: yRange,
    };
  }

  /** The terminal-state report of the finished shot (null while playing). */
  result() {
    return this._result;
  }

  /** True while local meshes may still be animating (sim or pocket falls are
   * owned by the caller; this only tracks the simulation itself). */
  isIdle() {
    return !this.simulating && this.done;
  }
}
