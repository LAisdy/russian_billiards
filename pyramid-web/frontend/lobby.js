// pyramid-web — lobby UI + WebSocket client (Steps 2, 6, 8 & 11).
//
// Connects to the same-origin /ws endpoint (proxied by nginx in production,
// by scripts/serve_frontend.py in local dev) and drives the lobby overlay:
// create room / join by 4-letter code / player list / host "Start game".
// Step 6: the host picks one of the four disciplines in the lobby; during
// play the server game snapshot drives the scoreboard, the turn indicator,
// Classic called shots («заказ»), ball-in-hand cue placement («с руки» /
// «с руки из дома»), and the game-over / rematch flow.
// Step 8: status moves into a dedicated top HUD bar (mode, scores, turn,
// thinking-time clock, remaining-ball chips, camera preset buttons); the
// side panel keeps only the controls and can collapse. The clock is
// informational (server-stamped turn_started_ms, skew-corrected client-side)
// and the "Your turn" toast fires on turn changes.
// Step 11 (client-side JS physics): Shoot starts the stroke LOCALLY —
// physics.js simulates it instantly at 60 FPS, the player watches real ball
// motion, and only when the balls stop does the terminal report (final
// resting positions + pocketed events) go to the server for judging. There
// is no server simulation wait anymore: no "Simulating…" ticker, no
// multi-stage watchdog — the UI can never freeze on a shot.

import { deriveHud, formatElapsed } from './ui_math.js';

const els = {
  lobby: document.getElementById('lobby'),
  name: document.getElementById('lobby-name'),
  codeInput: document.getElementById('lobby-code'),
  entry: document.getElementById('lobby-entry'),
  room: document.getElementById('lobby-room'),
  codeDisplay: document.getElementById('lobby-code-display'),
  players: document.getElementById('lobby-players'),
  modeGrid: document.getElementById('mode-grid'),
  modeNote: document.getElementById('mode-note'),
  start: document.getElementById('btn-start'),
  practice: document.getElementById('btn-practice'),
  rerack: document.getElementById('btn-rerack'),
  hint: document.getElementById('lobby-hint'),
  msg: document.getElementById('lobby-msg'),
  game: document.getElementById('lobby-game'),
  gameText: document.getElementById('lobby-game-text'),
  callRow: document.getElementById('call-row'),
  callBall: document.getElementById('call-ball'),
  callPocket: document.getElementById('call-pocket'),
  gameHint: document.getElementById('game-hint'),
  power: document.getElementById('power'),
  powerVal: document.getElementById('power-val'),
  shoot: document.getElementById('btn-shoot'),
  placeCue: document.getElementById('btn-place-cue'),
  gameOver: document.getElementById('game-over'),
  gameOverText: document.getElementById('game-over-text'),
  rematch: document.getElementById('btn-rematch'),
  // Step 8: HUD bar + panel collapse
  hud: document.getElementById('gamehud'),
  hudMode: document.getElementById('ghud-mode'),
  hudShot: document.getElementById('ghud-shot'),
  hudPlayers: document.getElementById('ghud-players'),
  hudTurn: document.getElementById('ghud-turn'),
  hudClock: document.getElementById('ghud-clock'),
  hudBalls: document.getElementById('ghud-balls'),
  hudCams: document.getElementById('ghud-cams'),
  toast: document.getElementById('turn-toast'),
  panelToggle: document.getElementById('btn-panel-toggle'),
};

const MODE_NAMES = {
  free: 'Free Pyramid',
  combined: 'Combined Pyramid',
  dynamic: 'Dynamic Pyramid',
  classic: 'Classic Pyramid',
  practice: 'Practice',
};

// Step 11: the only remaining wait is the server's rules round-trip after
// the local simulation finishes (the vendored rulesets judge in
// microseconds). This watchdog is purely informational and should never
// fire; it replaces the old multi-stage "simulating…" escalation.
const WATCHDOG_STAGES = [
  [
    15000,
    'Still no verdict from the server — it may be under heavy load. Waiting…',
  ],
];

const state = {
  ws: null,
  playerId: null,
  roomCode: null,
  players: [],
  mode: 'free',
  started: false,
  aimPhi: Math.PI / 2, // pooltool radians; default: straight towards the foot rail
  balls: null, // last authoritative on-table state from the server
  shotInFlight: false,
  game: null, // last server game snapshot (Step 6)
  placingCue: false, // table clicks place the cue ball (ball-in-hand)
  pendingCue: null, // cue_placed received mid-animation, applied after
  // Step 10: practice («Тренировка») + input/watchdog state
  practice: false, // the current game is a solo practice session
  practicePending: false, // create → joined → practice handshake in flight
  charging: false, // LMB power-charge drag in progress
  chargeStartY: 0,
  chargeStartPct: 0,
  watchdogTimer: null,
  // Step 8 HUD
  clockOffsetMs: 0, // server now - client now at the last snapshot (skew fix)
  clockTimer: null, // 500 ms HUD clock ticker
  lastTurnId: null, // for the "your turn" toast edge trigger
  chipEls: null, // the 15 remaining-ball chip spans (built once per game)
  toastTimer: null,
  keepaliveTimer: null, // periodic WS ping — see startKeepalive
};

const PYRAMID = () => window.__pyramid || null;

function showMsg(text) {
  els.msg.textContent = text || '';
}

function readName() {
  return (els.name.value || '').trim().slice(0, 24) || 'Player';
}

function readCode() {
  return (els.codeInput.value || '').trim().toUpperCase();
}

function wsUrl() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${location.host}/ws`;
}

// Keepalive: a quiet WebSocket looks like "no inbound traffic" to idle-timeout
// infrastructure (render.com free instances spin a service down after 15
// minutes without any HTTP request OR WebSocket message; some NATs/proxies
// drop idle sockets even sooner). The server already answers ping with pong
// and the client's dispatcher ignores pong (default case), so this costs
// one tiny frame per interval and keeps a running game alive everywhere.
function startKeepalive(ws) {
  stopKeepalive();
  state.keepaliveTimer = setInterval(() => {
    if (ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'ping' }));
    }
  }, 55000);
}

function stopKeepalive() {
  if (state.keepaliveTimer) {
    clearInterval(state.keepaliveTimer);
    state.keepaliveTimer = null;
  }
}

function isHost() {
  const me = state.players.find((p) => p.id === state.playerId);
  return Boolean(me && me.is_host);
}

function myTurn() {
  return Boolean(
    state.game && state.game.turn && state.game.turn.id === state.playerId,
  );
}

function connect() {
  return new Promise((resolve, reject) => {
    let ws;
    try {
      ws = new WebSocket(wsUrl());
    } catch (err) {
      reject(err);
      return;
    }
    const timer = setTimeout(() => reject(new Error('connection timeout')), 5000);
    ws.onopen = () => {
      clearTimeout(timer);
      startKeepalive(ws);
      resolve(ws);
    };
    ws.onerror = () => {
      clearTimeout(timer);
      reject(new Error('WebSocket error'));
    };
    ws.onclose = () => {
      clearTimeout(timer);
      onClosed();
    };
    ws.onmessage = (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch (err) {
        // parse errors and handler errors are SEPARATE (Step 10): one big
        // try/catch used to mask handler bugs as "unparseable message".
        console.error('[pyramid] unparseable WS message', err, ev.data);
        return;
      }
      try {
        onMessage(msg);
      } catch (err) {
        console.error(`[pyramid] handler failed for ${msg && msg.type}`, err);
        showToast('UI error — see browser console');
      }
    };
    state.ws = ws;
  });
}

// Step 10 (A2): global error hooks — any UI crash lands in the console
// with a [pyramid] prefix instead of vanishing.
window.addEventListener('error', (ev) => {
  console.error('[pyramid] window.onerror', ev.message, ev.filename, ev.lineno);
});
window.addEventListener('unhandledrejection', (ev) => {
  console.error('[pyramid] unhandled rejection', ev.reason);
});

// --- Step 10: shot watchdog -------------------------------------------------------
function armShotWatchdog() {
  disarmShotWatchdog();
  const fire = (i) => {
    if (i >= WATCHDOG_STAGES.length) return;
    const [delay, text] = WATCHDOG_STAGES[i];
    state.watchdogTimer = setTimeout(() => {
      if (!state.shotInFlight) return; // result arrived meanwhile
      console.warn(`[pyramid] watchdog stage ${i} fired at`, Date.now() - state.shotSentAt, 'ms');
      els.gameHint.textContent = text;
      showToast('Still simulating…');
      fire(i + 1);
    }, delay);
  };
  fire(0);
}

function disarmShotWatchdog() {
  if (state.watchdogTimer) {
    clearTimeout(state.watchdogTimer);
    state.watchdogTimer = null;
  }
}

async function createRoom() {
  showMsg('');
  try {
    const ws = await connect();
    ws.send(JSON.stringify({ type: 'create', name: readName() }));
  } catch (err) {
    showMsg(`Cannot reach server: ${err.message}`);
  }
}

// Step 10: instant solo entry — create a room, then start practice in it.
async function startPractice() {
  showMsg('');
  state.practicePending = true;
  try {
    const ws = await connect();
    ws.send(JSON.stringify({ type: 'create', name: readName() }));
  } catch (err) {
    state.practicePending = false;
    showMsg(`Cannot reach server: ${err.message}`);
  }
}

async function joinRoom() {
  const code = readCode();
  if (code.length !== 4) {
    showMsg('Room code must be 4 letters.');
    return;
  }
  showMsg('');
  try {
    const ws = await connect();
    ws.send(JSON.stringify({ type: 'join', room: code, name: readName() }));
  } catch (err) {
    showMsg(`Cannot reach server: ${err.message}`);
  }
}

function powerToV0(pct) {
  // slider 1..100 % -> cue speed 0.3 .. 8.0 m/s (physics.js clamps at 8)
  return 0.3 + (pct / 100) * 7.7;
}

// --- Step 8: game HUD bar -------------------------------------------------------

const CAM_FALLBACK_LABELS = {
  orbit: 'Orbit',
  top: 'Top',
  south: 'Head end',
  north: 'Foot end',
};

function setGame(snapshot) {
  // Capture the clock skew the MOMENT a snapshot arrives (applyGameState may
  // be deferred behind the shot animation) and store the snapshot.
  state.game = snapshot;
  const now = Number(snapshot && snapshot.now_ms);
  state.clockOffsetMs = Number.isFinite(now) ? now - Date.now() : 0;
}

function hudNow() {
  return Date.now() + state.clockOffsetMs;
}

function buildChips() {
  // 15 chip spans, created once per game; renderGameHud only toggles classes
  state.chipEls = new Map();
  els.hudBalls.replaceChildren();
  for (let n = 1; n <= 15; n++) {
    const chip = document.createElement('span');
    chip.className = 'ball-chip';
    chip.textContent = String(n);
    chip.title = `Ball ${n}`;
    els.hudBalls.appendChild(chip);
    state.chipEls.set(String(n), chip);
  }
  const count = document.createElement('span');
  count.className = 'balls-count';
  count.id = 'ghud-balls-count';
  els.hudBalls.appendChild(count);
}

function buildCamButtons() {
  const game = PYRAMID();
  const names = (game && game.views ? game.views() : ['orbit', 'top', 'south', 'north']);
  const labels = (game && game.viewLabels ? game.viewLabels() : CAM_FALLBACK_LABELS);
  els.hudCams.replaceChildren(
    ...names.map((name) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'cam-btn';
      btn.dataset.view = name;
      btn.textContent = labels[name] || name;
      btn.title = `Camera: ${labels[name] || name}`;
      btn.addEventListener('click', () => {
        if (game && typeof game.setView === 'function') game.setView(name);
        syncCamButtons();
      });
      return btn;
    }),
  );
  syncCamButtons();
}

function syncCamButtons() {
  const game = PYRAMID();
  const active = game && typeof game.currentView === 'function' ? game.currentView() : null;
  for (const btn of els.hudCams.querySelectorAll('.cam-btn')) {
    btn.classList.toggle('selected', btn.dataset.view === active);
  }
}

function renderGameHud() {
  const hud = deriveHud(state.game, state.balls, state.playerId, hudNow());
  if (!hud) {
    els.hud.hidden = true;
    return;
  }
  els.hud.hidden = false;
  els.hudMode.textContent = hud.modeLine;
  els.hudShot.textContent = hud.shotLine;

  els.hudPlayers.replaceChildren(
    ...hud.players.map((p) => {
      const card = document.createElement('span');
      card.className = 'ghud-player';
      if (p.isTurn) card.classList.add('turn');
      if (p.isMe) card.classList.add('me');
      const name = document.createElement('span');
      name.className = 'gp-name';
      name.textContent = p.isMe ? `${p.name} (you)` : p.name;
      const score = document.createElement('span');
      score.className = 'gp-score';
      score.textContent = String(p.score);
      card.append(name, score);
      return card;
    }),
  );

  const g = state.game;
  const mine = myTurn();
  els.hudTurn.classList.toggle('mine', mine && !hud.gameOver);
  els.hudTurn.textContent = hud.gameOver
    ? 'Game over'
    : mine
      ? '\u25B6 Your turn'
      : `Waiting for ${g && g.turn ? g.turn.name : 'opponent'}\u2026`;

  updateHudClock(hud);

  if (!state.chipEls) buildChips();
  for (const { id, onTable } of hud.chips) {
    const chip = state.chipEls.get(id);
    if (chip) chip.classList.toggle('off', !onTable);
  }
  const count = document.getElementById('ghud-balls-count');
  if (count) count.textContent = `${hud.remainingCount} left`;

  // Turn toast: edge-triggered on the turn changing to ME mid-game.
  const turnId = g && g.turn ? g.turn.id : null;
  if (mine && !hud.gameOver && state.lastTurnId !== null && state.lastTurnId !== turnId) {
    showToast('Your turn');
  }
  if (turnId !== null) state.lastTurnId = turnId;
}

function updateHudClock(hud) {
  const ms = hud && hud.clockMs;
  els.hudClock.textContent =
    Number.isFinite(ms) ? `\u23F1 ${formatElapsed(ms)}` : '\u23F1 \u2014';
  els.hudClock.classList.toggle('long', Number.isFinite(ms) && ms >= 60_000);
}

function showToast(text) {
  els.toast.textContent = text;
  els.toast.hidden = false;
  els.toast.classList.remove('fade');
  if (state.toastTimer) clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => {
    els.toast.classList.add('fade');
    state.toastTimer = setTimeout(() => {
      els.toast.hidden = true;
      els.toast.classList.remove('fade');
      state.toastTimer = null;
    }, 450);
  }, 1400);
}

function startHudClock() {
  stopHudClock();
  state.clockTimer = setInterval(() => {
    if (!state.game) return;
    updateHudClock(deriveHud(state.game, state.balls, state.playerId, hudNow()));
    syncCamButtons();
  }, 500);
}

function stopHudClock() {
  if (state.clockTimer) {
    clearInterval(state.clockTimer);
    state.clockTimer = null;
  }
}

els.panelToggle.addEventListener('click', () => {
  els.game.classList.toggle('collapsed');
});

// --- Step 6: game-state rendering -----------------------------------------------

function populateCallBalls(hittable) {
  const live = (hittable || []).filter((id) => id !== 'cue');
  const prev = els.callBall.value;
  els.callBall.replaceChildren(
    ...live.map((id) => {
      const opt = document.createElement('option');
      opt.value = id;
      opt.textContent = `ball ${id}`;
      return opt;
    }),
  );
  if (live.includes(prev)) els.callBall.value = prev;
}

function updateControls() {
  const g = state.game;
  const gameOver = Boolean(g && g.game_over);
  const game = PYRAMID();
  const rolling = Boolean(game && game.physicsBusy && game.physicsBusy());
  const animating = Boolean(game && game.isAnimating && game.isAnimating());
  const mine = myTurn() && !gameOver;
  els.shoot.disabled = !mine || state.shotInFlight || animating;
  let hint;
  if (gameOver) {
    hint = 'Game over.';
  } else if (rolling) {
    hint = 'Balls rolling…';
  } else if (state.shotInFlight) {
    hint = 'Server is judging the shot…';
  } else if (animating) {
    hint = 'Balls dropping…';
  } else if (mine && state.placingCue) {
    hint = 'Ball in hand: click the table to place the cue ball.';
  } else if (mine && g && g.call_shot) {
    hint = 'Call ball + pocket, move the mouse to aim, then shoot.';
  } else if (mine) {
    hint =
      'Move the mouse to aim · hold the LEFT button and pull back to charge '
      + '· release to shoot. RIGHT-drag orbits the camera; Esc cancels.';
  } else {
    const who = g && g.turn ? g.turn.name : 'opponent';
    hint = `Waiting for ${who}…`;
  }
  els.gameHint.textContent = hint;
}

function applyGameState() {
  const g = state.game;
  if (!g) return;

  // Step 8: the HUD bar owns mode/score/turn/balls display.
  renderGameHud();

  // Classic called shots («заказ»): the server flags strokes that need one.
  const mine = myTurn();
  const needCall = mine && !g.game_over && g.call_shot;
  els.callRow.hidden = !needCall;
  if (needCall) populateCallBalls(g.hittable);

  // Ball-in-hand: show the toggle for the privileged player; the house
  // highlight marks the «с руки из дома» zone in the 3D scene.
  const bih = mine && !g.game_over ? g.ball_in_hand : 'none';
  els.placeCue.hidden = bih === 'none';
  state.placingCue = bih !== 'none';
  els.placeCue.textContent = `Placing cue ball: ${state.placingCue ? 'on' : 'off'}`;
  PYRAMID()?.setBallInHand(bih);

  // Game over banner + host rematch.
  els.gameOver.hidden = !g.game_over;
  if (g.game_over) {
    const finalScore = (g.scores || []).map((s) => s.score).join('–');
    els.gameOverText.textContent = g.winner
      ? `${g.winner.name} wins ${finalScore}!`
      : `Game over — tie ${finalScore}.`;
  }
  els.rematch.hidden = !(g.game_over && isHost());
  // Step 10: practice gets a Re-rack control instead of the rematch flow.
  els.rerack.hidden = !state.practice;
  els.rerack.disabled = !mine;
  // Step 10: hand the mouse to the player (LEFT = charge, camera on RIGHT)
  // and let the camera orbit drift onto the cue ball during their turn.
  const game = PYRAMID();
  if (game && typeof game.setPlayerControl === 'function') {
    game.setPlayerControl(mine);
  }
  if (game && typeof game.setCueCamFollow === 'function') {
    game.setCueCamFollow(mine && !gameOver);
  }
  updateControls();
}

function verdictText(msg) {
  const parts = [`Shot #${msg.shot_id} by ${msg.by_name}`];
  parts.push(msg.legal ? 'legal' : `FOUL: ${msg.reason}`);
  if (msg.pocketed && msg.pocketed.length) {
    parts.push(`pocketed: ${msg.pocketed.join(', ')}`);
  }
  if (msg.respotted && msg.respotted.length) {
    parts.push(`respotted: ${msg.respotted.join(', ')}`);
  }
  if (msg.removed && msg.removed.length) {
    parts.push(`removed (penalty): ${msg.removed.join(', ')}`);
  }
  return parts.join(' — ');
}

function sendShot() {
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
    showToast('Not connected.');
    return;
  }
  if (state.shotInFlight) return;
  const game = PYRAMID();
  if (game && game.isAnimating()) return; // previous stroke still resolving
  if (!myTurn()) {
    showToast('It is not your turn.');
    return;
  }
  const pct = Number(els.power.value);
  // Step 10: the live (smoothed) aim drives the stroke, not the last target
  const aim = game && typeof game.currentAim === 'function'
    ? game.currentAim()
    : state.aimPhi;
  // Step 11: the stroke is simulated LOCALLY and instantly — physics.js
  // animates the real ball motion at 60 FPS; nothing is sent until the balls
  // stop. The UI can never freeze waiting for a server simulation.
  const started = game && typeof game.beginShot === 'function'
    ? game.beginShot(powerToV0(pct), aim, onLocalShotComplete)
    : false;
  if (!started) {
    showToast('Cannot start the shot.');
    return;
  }
  state.shotInFlight = true;
  state.shotSentAt = Date.now();
  state.charging = false;
  // NOTE: setCueCharge(null) is deliberately NOT called here —
  // playCueStrike below consumes the charged pull so the lunge launches
  // from the dragged-back position.
  console.info('[pyramid] local shot started', {
    v0: Number(powerToV0(pct).toFixed(2)),
    phi_deg: Number((((aim * 180) / Math.PI + 360) % 360).toFixed(1)),
  });
  updateControls();
  // Instant local feedback: the cue stick lunges NOW (from the charged
  // position when charging) while the balls are already rolling.
  if (game && typeof game.playCueStrike === 'function') {
    game.playCueStrike(aim);
  }
}

function onLocalShotComplete(result) {
  // The balls stopped: send the terminal report. The server judges it with
  // the vendored ruleset and broadcasts the authoritative verdict.
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
    state.shotInFlight = false;
    updateControls();
    return;
  }
  const payload = { type: 'shot', ...result };
  if (!els.callRow.hidden) {
    payload.ball_call = els.callBall.value;
    payload.pocket_call = els.callPocket.value;
  }
  console.info('[pyramid] sending shot report', JSON.stringify({
    pocketed: result.pocketed,
    scratch: result.scratch,
    duration: result.duration,
  }));
  state.ws.send(JSON.stringify(payload));
  armShotWatchdog(); // covers only the (microsecond-fast) rules round-trip
}

function sendPlaceCue(x, y) {
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
  if (!myTurn() || !state.placingCue) return;
  state.ws.send(
    JSON.stringify({ type: 'place_cue', x: Number(x.toFixed(4)), y: Number(y.toFixed(4)) }),
  );
}

// E2E/debug hook: aim (degrees) + power (1..100 %) + send, in one call.
window.__pyramidGame = {
  shoot(angleDeg, powerPct) {
    state.aimPhi = (Number(angleDeg) * Math.PI) / 180;
    if (Number.isFinite(powerPct) && powerPct >= 1 && powerPct <= 100) {
      els.power.value = String(Math.round(powerPct));
    }
    PYRAMID()?.setAim(state.aimPhi);
    sendShot();
  },
  aimPhiDeg: () => ((state.aimPhi * 180) / Math.PI + 360) % 360,
  powerPct: () => Number(els.power.value),
  // Step 6 additions
  state: () => JSON.parse(JSON.stringify({ mode: state.mode, game: state.game })),
  myTurn,
  placeCue(x, y) {
    sendPlaceCue(Number(x), Number(y));
  },
  setMode(mode) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({ type: 'set_mode', mode }));
    }
  },
  call(ball, pocket) {
    els.callBall.value = String(ball);
    els.callPocket.value = String(pocket);
  },
  rematch() {
    els.rematch.click();
  },
  // Step 8 additions
  setView(name) {
    PYRAMID()?.setView(name);
  },
  // Flat snapshot of the HUD bar for headless verification.
  hud: () => ({
    hidden: els.hud.hidden,
    mode: els.hudMode.textContent,
    shot: els.hudShot.textContent,
    turn: els.hudTurn.textContent,
    clock: els.hudClock.textContent,
    players: [...els.hudPlayers.children].map((c) => c.textContent),
    chipsOnTable: [...els.hudBalls.querySelectorAll('.ball-chip')].map(
      (c) => !c.classList.contains('off'),
    ),
    ballsCount:
      document.getElementById('ghud-balls-count')?.textContent ?? '',
    views: [...els.hudCams.querySelectorAll('.cam-btn')].map(
      (b) => `${b.dataset.view}:${b.classList.contains('selected') ? 1 : 0}`,
    ),
    toastHidden: els.toast.hidden,
    panelCollapsed: els.game.classList.contains('collapsed'),
  }),
};

function onMessage(msg) {
  switch (msg.type) {
    case 'joined':
      state.playerId = msg.player_id;
      state.roomCode = msg.room;
      state.players = msg.players;
      state.mode = msg.mode || 'free';
      state.started = false;
      els.codeDisplay.textContent = msg.room;
      els.entry.hidden = true;
      els.game.hidden = true;
      els.room.hidden = false;
      renderRoom();
      console.info('[pyramid] joined room', msg.room, 'as', msg.player_id);
      if (state.practicePending) {
        // Instant solo entry: the room exists, start the practice session.
        state.practicePending = false;
        state.ws.send(JSON.stringify({ type: 'practice' }));
      }
      break;
    case 'player_list':
      state.players = msg.players;
      if (msg.mode) state.mode = msg.mode;
      renderRoom();
      break;
    case 'game_started': {
      state.started = true;
      state.mode = msg.mode || state.mode;
      state.practice = Boolean(msg.practice);
      setGame(msg.game || null);
      state.pendingCue = null;
      state.balls = msg.balls || state.balls;
      state.lastTurnId = null; // no "your turn" toast on a fresh game
      state.chipEls = null; // rebuild the remaining-ball chips
      els.room.hidden = true;
      els.entry.hidden = true;
      els.game.hidden = false;
      els.gameOver.hidden = true;
      els.lobby.classList.add('playing'); // canvas clicks reach the table
      const game = PYRAMID();
      if (game && msg.balls) {
        game.showAllBalls();
        game.setBallPositions(msg.balls);
        state.aimPhi = Math.PI / 2;
        game.setAim(state.aimPhi);
      }
      els.gameText.textContent = state.practice
        ? `Practice mode («Тренировка») — solo session. Miss nothing, the table is yours.`
        : `Game started — ${msg.mode_name} — `
          + `${msg.players.map((p) => p.name).join(' vs ')}.`;
      buildCamButtons();
      applyGameState();
      startHudClock();
      break;
    }
    case 'shot_result': {
      disarmShotWatchdog();
      console.info('[pyramid] shot_result', {
        shot_id: msg.shot_id,
        legal: msg.legal,
        reason: msg.reason,
        pocketed: msg.pocketed,
        respotted: msg.respotted,
        removed: msg.removed,
        judge_ms: msg.judge_ms,
        latency_ms: state.shotSentAt ? Date.now() - state.shotSentAt : null,
      });
      if (msg.game) setGame(msg.game); // stamp captured at arrival, applied later
      state.balls = msg.balls;
      els.gameText.textContent = verdictText(msg);
      const game = PYRAMID();
      let applied = false;
      const applyAfter = () => {
        if (applied) return;
        applied = true;
        // Authoritative post-rules state for EVERYONE: the shooter's local
        // view is corrected (respots / penalty removals), the opponent's
        // board snaps to the final state instantly.
        if (game && msg.balls) game.setBallPositions(msg.balls);
        if (state.pendingCue) {
          const place = state.pendingCue;
          state.pendingCue = null;
          place();
        }
        state.shotInFlight = false;
        applyGameState();
      };
      // Step 11: no keyframes travel the wire. If pocket-drop animations are
      // still draining locally (sub-second cosmetics), let them finish so a
      // respotted ball does not snap back mid-drop.
      if (game && game.isAnimating()) {
        const drain = () => {
          if (!game.isAnimating()) applyAfter();
          else setTimeout(drain, 50);
        };
        drain();
      } else {
        applyAfter();
      }
      break;
    }
    case 'cue_placed': {
      const apply = () => {
        if (state.balls) state.balls.cue = { x: msg.x, y: msg.y };
        PYRAMID()?.setBallPositions({ cue: { x: msg.x, y: msg.y } }, { partial: true });
        PYRAMID()?.setAim(state.aimPhi);
      };
      if (PYRAMID()?.isAnimating()) {
        state.pendingCue = apply; // the running animation owns the cue ball
      } else {
        apply();
      }
      break;
    }
    case 'game_aborted':
      state.started = false;
      state.game = null;
      state.pendingCue = null;
      state.lastTurnId = null;
      state.chipEls = null;
      state.practice = false;
      disarmShotWatchdog();
      stopHudClock();
      els.hud.hidden = true;
      els.lobby.classList.remove('playing');
      PYRAMID()?.setBallInHand('none');
      PYRAMID()?.setCueCharge(null);
      state.charging = false;
      els.game.hidden = true;
      els.gameOver.hidden = true;
      els.room.hidden = false;
      renderRoom();
      break;
    case 'error':
      // Step 10 (A2): server errors are shown where the player IS — the
      // toast + game hint — not only in the lobby entry's hidden msg line.
      console.error('[pyramid] server error', msg);
      showMsg(`${msg.message} (${msg.code})`);
      showToast(msg.message || 'Server error');
      if (state.started) {
        els.gameHint.textContent = `⚠ ${msg.message}`;
      }
      state.shotInFlight = false;
      disarmShotWatchdog();
      updateControls();
      break;
    default:
      break;
  }
}

function renderRoom() {
  if (state.started) return;
  els.players.replaceChildren(
    ...state.players.map((p) => {
      const li = document.createElement('li');
      const host = p.is_host ? ' · host' : '';
      const you = p.id === state.playerId ? ' — you' : '';
      li.textContent = `${p.name}${host}${you}`;
      return li;
    }),
  );
  const me = state.players.find((p) => p.id === state.playerId);
  const isHostPlayer = Boolean(me && me.is_host);
  const count = state.players.length;

  for (const btn of els.modeGrid.querySelectorAll('.mode-btn')) {
    btn.classList.toggle('selected', btn.dataset.mode === state.mode);
    btn.disabled = !isHostPlayer;
  }
  els.modeNote.textContent = isHostPlayer
    ? 'You pick the game mode.'
    : `Host picks the mode — currently ${MODE_NAMES[state.mode] || state.mode}.`;

  // Step 10: practice entry — host-only, available at any room size.
  els.practice.hidden = !isHostPlayer;
  if (!isHostPlayer) {
    els.start.hidden = true;
    els.hint.textContent = 'Waiting for the host to start the game…';
  } else if (count < 2) {
    els.start.hidden = false;
    els.start.disabled = true;
    els.hint.textContent =
      'Waiting for a second player… share the code, or start Practice mode!';
  } else {
    els.start.hidden = false;
    els.start.disabled = false;
    els.hint.textContent = 'Both players ready — start when you like.';
  }
}

function onClosed() {
  stopKeepalive();
  if (state.roomCode) {
    showMsg('Connection closed — room left.');
  }
  resetToEntry();
}

function resetToEntry() {
  stopKeepalive();
  state.ws = null;
  state.playerId = null;
  state.roomCode = null;
  state.players = [];
  state.started = false;
  state.balls = null;
  state.shotInFlight = false;
  state.aimPhi = Math.PI / 2;
  state.game = null;
  state.placingCue = false;
  state.pendingCue = null;
  state.lastTurnId = null;
  state.chipEls = null;
  state.practice = false;
  state.practicePending = false;
  state.charging = false;
  disarmShotWatchdog();
  stopHudClock();
  els.hud.hidden = true;
  els.toast.hidden = true;
  els.lobby.classList.remove('playing');
  PYRAMID()?.setCueCharge(null);
  PYRAMID()?.setPlayerControl(false);
  PYRAMID()?.setCueCamFollow(false);
  els.room.hidden = true;
  els.game.hidden = true;
  els.gameOver.hidden = true;
  els.entry.hidden = false;
  els.codeDisplay.textContent = '----';
  els.players.replaceChildren();
}

els.start.addEventListener('click', () => {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({ type: 'start_game' }));
    els.start.disabled = true;
    els.hint.textContent = 'Starting…';
  }
});

els.rematch.addEventListener('click', () => {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({ type: 'start_game' }));
  }
});

// Step 10: practice entries — lobby entry button (instant solo room) and
// the in-game Re-rack control (same message; the server re-racks).
els.practice.addEventListener('click', startPractice);
els.rerack.addEventListener('click', () => {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    els.rerack.disabled = true;
    state.ws.send(JSON.stringify({ type: 'practice' }));
  }
});

els.modeGrid.addEventListener('click', (ev) => {
  const btn = ev.target.closest('.mode-btn');
  if (!btn || btn.disabled) return;
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({ type: 'set_mode', mode: btn.dataset.mode }));
  }
});

els.placeCue.addEventListener('click', () => {
  state.placingCue = !state.placingCue;
  els.placeCue.textContent = `Placing cue ball: ${state.placingCue ? 'on' : 'off'}`;
  updateControls();
});

// --- Step 10: Panda3D-style aiming input state machine ---------------------------
// mousemove (no buttons)  -> the aim sweeps toward the cursor's table point
//                            (smoothed per render frame in main.js)
// LMB press-drag          -> power charge: vertical pull maps 1..100 %, the
//                            stick pulls back visually, release under 2 %
//                            cancels, any other release shoots the live aim
// RIGHT-drag / wheel      -> camera orbit/zoom (target lerps onto the cue
//                            ball during your turn — main.js)
// touch one-finger drag   -> aim; two fingers -> camera; slider + Shoot fire
// click (tap, no drag)    -> ball-in-hand cue placement (when placingCue)
// Esc                     -> cancel the charge
const sceneEl = document.getElementById('scene');

sceneEl.addEventListener('contextmenu', (ev) => ev.preventDefault());

// CAPTURE phase at document level: the charge start must reach the canvas
// BEFORE OrbitControls' own listener (same element) — stopping propagation
// here keeps OrbitControls completely unaware of power-charge drags.
document.addEventListener(
  'pointerdown',
  (ev) => {
    if (ev.target !== sceneEl || ev.button !== 0) return;
    if (ev.pointerType === 'touch') return; // touch aims via one-finger drag
    if (!state.started) return;
    const game = PYRAMID();
    if (!game || game.isAnimating() || state.shotInFlight) return;
    if (!myTurn() || state.placingCue) return; // camera / placement own the click
    ev.stopPropagation();
    try {
      sceneEl.setPointerCapture(ev.pointerId);
    } catch {
      /* capture is best-effort; the move/up handlers still work */
    }
    state.charging = true;
    state.chargeStartY = ev.clientY;
    state.chargeStartPct = Number(els.power.value);
    console.debug('[pyramid] charge start at', state.chargeStartPct, '%');
  },
  true,
);

sceneEl.addEventListener('pointermove', (ev) => {
  if (!state.started) return;
  const game = PYRAMID();
  if (!game || game.isAnimating() || state.shotInFlight) return;

  if (state.charging) {
    // pull DOWN the cue (downwards drag) to charge; the slider stays synced
    const dy = ev.clientY - state.chargeStartY;
    const pct = Math.max(
      1,
      Math.min(100, Math.round(state.chargeStartPct + dy * 0.35)),
    );
    els.power.value = String(pct);
    els.powerVal.textContent = `${pct}%`;
    if (typeof game.setCueCharge === 'function') game.setCueCharge(pct);
    return;
  }

  if (ev.pointerType === 'touch') {
    // one-finger drag aims (two-finger camera gestures reach OrbitControls)
    if (!ev.isPrimary || !myTurn() || state.placingCue) return;
    const hit = game.tablePoint(ev.clientX, ev.clientY);
    if (!hit) return;
    const balls = game.ballPositions();
    const cue = balls && balls.cue;
    if (!cue) return;
    state.aimPhi = aimPhiTo(hit, cue);
    game.setAimTarget(state.aimPhi);
    return;
  }

  if (ev.buttons !== 0) return; // camera drag — never re-aims
  if (state.placingCue || !myTurn()) return;
  const hit = game.tablePoint(ev.clientX, ev.clientY);
  if (!hit) return;
  const balls = game.ballPositions();
  const cue = balls && balls.cue;
  if (!cue) return;
  state.aimPhi = aimPhiTo(hit, cue);
  game.setAimTarget(state.aimPhi);
});

// world/queue mapping: scene hit point + cue ball world pos -> pooltool phi
function aimPhiTo(hit, cue) {
  // world (mesh.position.x/z) -> pooltool (x = z + W/2, y = x + L/2)
  const cueX = cue.z + 1.8 / 2;
  const cueY = cue.x + 3.7 / 2;
  const phi = Math.atan2(hit.y - cueY, hit.x - cueX);
  return (phi + Math.PI * 2) % (Math.PI * 2);
}

function endCharge(ev) {
  if (!state.charging) return;
  state.charging = false;
  const game = PYRAMID();
  const pulled = Math.abs(ev.clientY - state.chargeStartY);
  const pct = Number(els.power.value);
  if (pulled < 6 || pct < 2) {
    // cancel: re-seat the stick (a tap or a micro-jolt must not fire)
    if (game && typeof game.setCueCharge === 'function') game.setCueCharge(null);
    console.debug('[pyramid] charge cancelled', { pulled, pct });
    updateControls();
    return;
  }
  sendShot(); // playCueStrike inside consumes the charged pull
}

sceneEl.addEventListener('pointerup', endCharge);
sceneEl.addEventListener('pointercancel', () => {
  if (!state.charging) return;
  state.charging = false;
  PYRAMID()?.setCueCharge(null);
  updateControls();
});

// Esc cancels an in-progress charge
document.addEventListener('keydown', (ev) => {
  if (ev.key !== 'Escape' || !state.charging) return;
  state.charging = false;
  PYRAMID()?.setCueCharge(null);
  updateControls();
});

// ball-in-hand placement: a genuine click (not a camera drag) on the felt
let downPos = null;
sceneEl.addEventListener('pointerdown', (ev) => {
  downPos = [ev.clientX, ev.clientY];
});
sceneEl.addEventListener('click', (ev) => {
  if (!state.started) return;
  if (downPos) {
    const dx = ev.clientX - downPos[0];
    const dy = ev.clientY - downPos[1];
    downPos = null;
    if (dx * dx + dy * dy > 36) return; // it was a camera drag, not a click
  }
  const game = PYRAMID();
  if (!game || game.isAnimating() || state.shotInFlight) return;
  if (!(state.placingCue && myTurn())) return; // aiming moved to pointermove
  const hit = game.tablePoint(ev.clientX, ev.clientY);
  if (hit) sendPlaceCue(hit.x, hit.y);
});

els.power.addEventListener('input', () => {
  els.powerVal.textContent = `${els.power.value}%`;
});
els.shoot.addEventListener('click', sendShot);

document.getElementById('btn-create').addEventListener('click', createRoom);
document.getElementById('btn-join').addEventListener('click', joinRoom);

els.name.addEventListener('keydown', (ev) => {
  if (ev.key === 'Enter') createRoom();
});
els.codeInput.addEventListener('keydown', (ev) => {
  if (ev.key === 'Enter') joinRoom();
});
els.codeInput.addEventListener('input', () => {
  // Uppercase as you type; keep letters only.
  const cleaned = els.codeInput.value.toUpperCase().replace(/[^A-Z]/g, '');
  if (cleaned !== els.codeInput.value) {
    els.codeInput.value = cleaned;
  }
});
