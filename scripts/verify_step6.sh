#!/bin/bash
# Step 6 E2E: two browser tabs, one room — mode selection, game snapshot UI
# (scoreboard/turn), ball-in-hand cue placement, shot + turn switching.
# Single invocation (the sandbox reaps background processes between calls).
set -u
cd /home/z/my-project/pyramid-web

ab() { timeout 25 agent-browser "$@"; }

ab close >/dev/null 2>&1

echo "== 0. free ports =="
for port in 8100 8090; do
  pids=$(ss -tlnp 2>/dev/null | grep ":$port " | grep -oP 'pid=\K[0-9]+' | sort -u)
  if [ -n "$pids" ]; then kill $pids 2>/dev/null; echo "killed on :$port: $pids"; fi
done
sleep 0.5

echo "== 1. servers =="
(cd backend && PYTHONHASHSEED=0 .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8100 >/tmp/uv6b.log 2>&1 &)
backend/.venv/bin/python /home/z/my-project/scripts/serve_frontend.py 8090 >/tmp/dev6.log 2>&1 &
for i in $(seq 1 60); do curl -sf http://127.0.0.1:8100/api/health >/dev/null 2>&1 && break; sleep 0.25; done
curl -sf http://127.0.0.1:8090/api/health >/dev/null && echo "  dev proxy OK"

echo "== 2. wait for numba warmup =="
ready=""
for i in $(seq 1 180); do
  if curl -s http://127.0.0.1:8100/api/health | grep -q '"physics_ready":true'; then ready=1; break; fi
  sleep 0.5
done
[ -n "$ready" ] && echo "  physics_ready: true" || { echo "WARMUP TIMEOUT"; exit 1; }

echo "== 3. two tabs, one room =="
ab set viewport 1440 900
ab open http://127.0.0.1:8090
ab wait 2800
ab eval "document.getElementById('lobby-name').value='Alice'"
ab eval "document.getElementById('btn-create').click()"
CODE=""
for i in $(seq 1 40); do
  CODE=$(ab eval "document.getElementById('lobby-code-display').textContent" | tr -d '"')
  [[ "$CODE" =~ ^[A-Z]{4}$ ]] && break
  sleep 0.5
done
if [[ ! "$CODE" =~ ^[A-Z]{4}$ ]]; then
  echo "CREATE FAILED: code=$CODE"
  ab errors
  exit 1
fi
echo "  room code: $CODE"

ab tab new http://127.0.0.1:8090
ab wait 2800
ab eval "document.getElementById('lobby-name').value='Bob'"
ab eval "document.getElementById('lobby-code').value='$CODE'"
ab eval "document.getElementById('btn-join').click()"
joined=""
for i in $(seq 1 30); do
  n=$(ab eval "document.querySelectorAll('#lobby-players li').length" | tr -d '"')
  [ "$n" = "2" ] && joined=1 && break
  sleep 0.5
done
[ -n "$joined" ] && echo "  Bob joined (2 players)" || { echo "JOIN TIMEOUT"; ab errors; exit 1; }

echo "== 4. host picks Dynamic; both tabs must show it =="
ab tab t1
ab eval "document.querySelector('.mode-btn[data-mode=dynamic]').click()" >/dev/null
mode2=""
ab tab t2
ab wait 300
for i in $(seq 1 20); do
  mode2=$(ab eval "document.getElementById('mode-note').textContent" | tr -d '"')
  echo "$mode2" | grep -q "Dynamic" && mode2=ok && break
  sleep 0.5
done
[ "$mode2" = "ok" ] && echo "  tab2 sees: mode = Dynamic (server broadcast)" || echo "  MODE SYNC TIMEOUT: '$mode2'"
ab eval "document.querySelector('.mode-btn[data-mode=dynamic]').classList.contains('selected')" | tr -d '"'

echo "== 5. start game =="
ab tab t1
ab eval "document.getElementById('btn-start').click()"
game=""
for i in $(seq 1 30); do
  g=$(ab eval "document.getElementById('lobby-game').hidden" | tr -d '"')
  [ "$g" = "false" ] && game=1 && break
  sleep 0.5
done
[ -n "$game" ] && echo "  game started" || { echo "START TIMEOUT"; ab errors; exit 1; }
ab wait 500

echo "-- tab1 game view:"
ab eval "JSON.stringify({mode: document.getElementById('game-mode-line').textContent, score: document.getElementById('game-scorebar').textContent, turn: document.getElementById('game-turn').textContent, shootDisabled: document.getElementById('btn-shoot').disabled, placeCueHidden: document.getElementById('btn-place-cue').hidden})"
echo "-- tab2 game view:"
ab tab t2
ab wait 400
ab eval "JSON.stringify({mode: document.getElementById('game-mode-line').textContent, score: document.getElementById('game-scorebar').textContent, turn: document.getElementById('game-turn').textContent, shootDisabled: document.getElementById('btn-shoot').disabled, placeCueHidden: document.getElementById('btn-place-cue').hidden})"

echo "== 6. ball in hand: Alice places the cue (house) =="
ab tab t1
ab eval "window.__pyramidGame.placeCue(0.9, 0.5)" >/dev/null
cue1=""
for i in $(seq 1 20); do
  cue1=$(ab eval "JSON.stringify(window.__pyramid.ballPositions().cue)" | tr -d '"')
  # NB: agent-browser escapes inner quotes (\"x\"), so match the bare value
  echo "$cue1" | grep -q -- '-1.35' && cue1=ok && break
  sleep 0.5
done
[ "$cue1" = "ok" ] && echo "  tab1 cue moved to the placed spot (x=-1.35 world)" || echo "  TAB1 CUE TIMEOUT: $cue1"
cue2=""
ab tab t2
ab wait 300
for i in $(seq 1 20); do
  cue2=$(ab eval "JSON.stringify(window.__pyramid.ballPositions().cue)" | tr -d '"')
  echo "$cue2" | grep -q -- '-1.35' && cue2=ok && break
  sleep 0.5
done
[ "$cue2" = "ok" ] && echo "  tab2 cue synced (cue_placed broadcast)" || echo "  TAB2 CUE TIMEOUT: $cue2"
ab tab t1
ab eval "window.__pyramid.setAngledView(); 'angled'" >/dev/null
ab wait 300
ab screenshot /home/z/my-project/download/step6_ball_in_hand.png
echo "  screenshot: step6_ball_in_hand.png (house highlight + placed cue)"

echo "== 7. Alice breaks (phi 90, power 15) =="
ab tab t1
ab eval "window.__pyramidGame.shoot(90, 15)"
done=""
for i in $(seq 1 100); do
  st=$(ab eval "window.__pyramid.isAnimating()" | tr -d '"')
  [ -z "$st" ] && break
  [ "$st" = "false" ] && done=1 && break
  sleep 0.5
done
[ -n "$done" ] && echo "  animation finished" || echo "  ANIMATION TIMEOUT"
ab wait 500
echo "-- tab1 after the break:"
ab eval "JSON.stringify({verdict: document.getElementById('lobby-game-text').textContent, score: document.getElementById('game-scorebar').textContent, turn: document.getElementById('game-turn').textContent, gameOverHidden: document.getElementById('game-over').hidden})"
STATE1=$(ab eval "window.__pyramidGame.state().game.turn.name" | tr -d '"')
echo "  server says next shooter: $STATE1"
echo "-- tab2 after the break:"
ab tab t2
ab wait 400
ab eval "JSON.stringify({verdict: document.getElementById('lobby-game-text').textContent, score: document.getElementById('game-scorebar').textContent, turn: document.getElementById('game-turn').textContent})"
STATE2=$(ab eval "window.__pyramidGame.state().game.turn.name" | tr -d '"')
echo "  server says next shooter: $STATE2"
if [ "$STATE1" = "$STATE2" ] && [ -n "$STATE1" ]; then
  echo "  turn state CONSISTENT across tabs: $STATE1"
else
  echo "  TURN MISMATCH: '$STATE1' vs '$STATE2'"
fi
ab eval "window.__pyramid.setAngledView(); 'angled'" >/dev/null
ab wait 350
ab screenshot /home/z/my-project/download/step6_after_break.png
echo "  screenshot: step6_after_break.png"

echo "== 8. cross-tab ball consistency =="
ab tab t1
POS1=$(ab eval "JSON.stringify(window.__pyramid.ballPositions())")
ab tab t2
POS2=$(ab eval "JSON.stringify(window.__pyramid.ballPositions())")
ab eval "(() => { const a = JSON.parse($POS1); const b = JSON.parse($POS2); if (Object.keys(a).length !== Object.keys(b).length) return JSON.stringify({error: 'count mismatch'}); let md = 0; for (const k of Object.keys(a)) { if (!b[k]) return JSON.stringify({error: 'missing ' + k}); md = Math.max(md, Math.hypot(a[k].x - b[k].x, a[k].z - b[k].z)); } return JSON.stringify({balls: Object.keys(a).length, maxDeltaM: +md.toFixed(9), same: md < 1e-9}); })()"

echo "== 9. page errors =="
ab tab t1
ab errors
ab tab t2
ab errors

echo "== 10. stop servers =="
pids=$(ss -tlnp 2>/dev/null | grep -E ':(8100|8090) ' | grep -oP 'pid=\K[0-9]+' | sort -u)
[ -n "$pids" ] && kill $pids 2>/dev/null
sleep 0.5
ss -tlnp 2>/dev/null | grep -E ':(8100|8090) ' || echo "ports free"
echo DONE
