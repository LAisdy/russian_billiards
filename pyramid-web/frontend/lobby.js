// pyramid-web — lobby UI + WebSocket client (Steps 2, 5, 6 & 8).
//
// Connects to the same-origin /ws endpoint (proxied by nginx in production,
// by scripts/serve_frontend.py in local dev) and drives the lobby overlay:
// create room / join by 4-letter code / player list / host "Start game".
// Step 5: on game_started the server-dealt rack is applied to the 3D scene;
// clicking the table aims the cue ball, the Shoot button sends the stroke
// over the socket, and every client animates the returned keyframes.
// Step 6: the host picks one of the four disciplines in the lobby; during
// play the server game snapshot drives the scoreboard, the turn indicator,
// Classic called shots («заказ»), ball-in-hand cue placement («с руки» /
// «с руки из дома»), and the game-over / rematch flow.
// Step 8: status moves into a dedicated top HUD bar (mode, scores, turn,
// thinking-time clock, remaining-ball chips, camera preset buttons); the
// side panel keeps only the controls and can collapse. The clock is
// informational (server-stamped turn_started_ms, skew-corrected client-side)
// and the "Your turn" toast fires on turn changes.

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
};

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
  // Step 8 HUD
  clockOffsetMs: 0, // server now - client now at the last snapshot (skew fix)
  clockTimer: null, // 500 ms HUD clock ticker
  lastTurnId: null, // for the "your turn" toast edge trigger
  chipEls: null, // the 15 remaining-ball chip spans (built once per game)
  toastTimer: null,
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
      try {
        onMessage(JSON.parse(ev.data));
      } catch (err) {
        console.error('unparseable message', err);
      }
    };
    state.ws = ws;
  });
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
  // slider 1..100 % -> cue speed 0.3 .. 9.0 m/s (API range is (0.05, 10])
  return 0.3 + (pct / 100) * 8.7;
}

// Step 7: live "Simulating… N ms" ticker. Purely informational — the canvas,
// camera and orbit controls stay fully interactive the whole time; the UI
// must never show a blocking "Calculating shot…" screen.
let simTicker = null;

function startSimTicker() {
  stopSimTicker();
  const t0 = performance.now();
  simTicker = setInterval(() => {
    els.gameHint.textContent = `Simulating shot… ${Math.round(performance.now() - t0)} ms`;
  }, 100);
}

function stopSimTicker() {
  if (simTicker) {
    clearInterval(simTicker);
    simTicker = null;
  }
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
  const animating = Boolean(PYRAMID()?.isAnimating());
  const mine = myTurn() && !gameOver;
  els.shoot.disabled = !mine || state.shotInFlight || animating;
  let hint;
  if (gameOver) {
    hint = 'Game over.';
  } else if (state.shotInFlight) {
    hint = 'Simulating shot…';
  } else if (animating) {
    hint = 'Animating shot…';
  } else if (mine && state.placingCue) {
    hint = 'Ball in hand: click the table to place the cue ball.';
  } else if (mine && g && g.call_shot) {
    hint = 'Call ball + pocket, click the table to aim, then shoot.';
  } else if (mine) {
    hint = 'Click the table to aim, then shoot.';
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
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
  if (state.shotInFlight) return;
  const game = PYRAMID();
  if (game && game.isAnimating()) return; // previous stroke still animating
  if (!myTurn()) {
    showMsg('It is not your turn.');
    return;
  }
  const pct = Number(els.power.value);
  const phiDeg = ((state.aimPhi * 180) / Math.PI + 360) % 360;
  const payload = { type: 'shot', v0: powerToV0(pct), phi: phiDeg };
  if (!els.callRow.hidden) {
    payload.ball_call = els.callBall.value;
    payload.pocket_call = els.callPocket.value;
  }
  state.ws.send(JSON.stringify(payload));
  state.shotInFlight = true;
  updateControls();
  // Optimistic local feedback (Step 7): the cue stick lunges NOW; the balls
  // themselves animate from the authoritative server keyframes when the
  // result arrives.
  if (game && typeof game.playCueStrike === 'function') {
    game.playCueStrike(state.aimPhi);
  }
  startSimTicker();
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
      break;
    case 'player_list':
      state.players = msg.players;
      if (msg.mode) state.mode = msg.mode;
      renderRoom();
      break;
    case 'game_started': {
      state.started = true;
      state.mode = msg.mode || state.mode;
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
      els.gameText.textContent =
        `Game started — ${msg.mode_name} — ` +
        `${msg.players.map((p) => p.name).join(' vs ')}.`;
      buildCamButtons();
      applyGameState();
      startHudClock();
      break;
    }
    case 'shot_result': {
      if (msg.game) setGame(msg.game); // stamp captured at arrival, applied later
      state.balls = msg.balls;
      els.gameText.textContent = verdictText(msg);
      const game = PYRAMID();
      let applied = false;
      const applyAfter = () => {
        if (applied) return;
        applied = true;
        stopSimTicker();
        if (game && msg.balls) game.setBallPositions(msg.balls);
        if (state.pendingCue) {
          const place = state.pendingCue;
          state.pendingCue = null;
          place();
        }
        state.shotInFlight = false;
        applyGameState();
      };
      if (game && msg.keyframes) {
        const played = game.playKeyframes(msg.keyframes, applyAfter);
        if (played && !game.isAnimating()) {
          applyAfter(); // hidden-tab fast path already finished
        }
      } else {
        applyAfter();
      }
      break;
    }
    case 'cue_placed': {
      const apply = () => {
        if (state.balls) state.balls.cue = { x: msg.x, y: msg.y };
        PYRAMID()?.setBallPositions({ cue: { x: msg.x, y: msg.y } });
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
      stopSimTicker();
      stopHudClock();
      els.hud.hidden = true;
      els.lobby.classList.remove('playing');
      PYRAMID()?.setBallInHand('none');
      els.game.hidden = true;
      els.gameOver.hidden = true;
      els.room.hidden = false;
      renderRoom();
      break;
    case 'error':
      showMsg(`${msg.message} (${msg.code})`);
      state.shotInFlight = false;
      stopSimTicker();
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

  if (!isHostPlayer) {
    els.start.hidden = true;
    els.hint.textContent = 'Waiting for the host to start the game…';
  } else if (count < 2) {
    els.start.hidden = false;
    els.start.disabled = true;
    els.hint.textContent = 'Waiting for a second player… share the room code!';
  } else {
    els.start.hidden = false;
    els.start.disabled = false;
    els.hint.textContent = 'Both players ready — start when you like.';
  }
}

function onClosed() {
  if (state.roomCode) {
    showMsg('Connection closed — room left.');
  }
  resetToEntry();
}

function resetToEntry() {
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
  stopSimTicker();
  stopHudClock();
  els.hud.hidden = true;
  els.toast.hidden = true;
  els.lobby.classList.remove('playing');
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

// aim (not drag) on the table: with ball-in-hand the click places the cue
// ball; otherwise it sets the cue direction from the cue ball to the point
let downPos = null;
document.getElementById('scene').addEventListener('pointerdown', (ev) => {
  downPos = [ev.clientX, ev.clientY];
});
document.getElementById('scene').addEventListener('click', (ev) => {
  if (!state.started) return;
  if (downPos) {
    const dx = ev.clientX - downPos[0];
    const dy = ev.clientY - downPos[1];
    downPos = null;
    if (dx * dx + dy * dy > 36) return; // it was a camera drag, not a click
  }
  const game = PYRAMID();
  if (!game || game.isAnimating() || state.shotInFlight) return;
  const hit = game.tablePoint(ev.clientX, ev.clientY);
  if (!hit) return;
  if (state.placingCue && myTurn()) {
    sendPlaceCue(hit.x, hit.y);
    return;
  }
  const balls = game.ballPositions();
  const cue = balls && balls.cue;
  if (!cue) return;
  // world (mesh.position.x/z) -> pooltool (x = z + W/2, y = x + L/2)
  const cueX = cue.z + 1.8 / 2;
  const cueY = cue.x + 3.7 / 2;
  const phi = Math.atan2(hit.y - cueY, hit.x - cueX);
  state.aimPhi = (phi + Math.PI * 2) % (Math.PI * 2);
  game.setAim(state.aimPhi);
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
