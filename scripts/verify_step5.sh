#!/bin/bash
# Step 5 E2E v2: two browser tabs in one room, shot from one, synced animation
# in both; screenshots + page errors. Single invocation (the sandbox reaps
# background processes between calls).
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
(cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8100 >/tmp/uv5.log 2>&1 &)
backend/.venv/bin/python /home/z/my-project/scripts/serve_frontend.py 8090 >/tmp/dev5.log 2>&1 &
for i in $(seq 1 60); do curl -sf http://127.0.0.1:8100/api/health >/dev/null 2>&1 && break; sleep 0.25; done
curl -sf http://127.0.0.1:8090/api/health >/dev/null && echo "  dev proxy OK"

echo "== 2. wait for numba warmup =="
ready=""
for i in $(seq 1 180); do
  if curl -s http://127.0.0.1:8100/api/health | grep -q '"physics_ready":true'; then
    ready=1; break
  fi
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
  MSG=$(ab eval "document.getElementById('lobby-msg').textContent")
  echo "CREATE FAILED: code=$CODE msg=$MSG"
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
  n=$(ab eval "document.querySelectorAll('#lobby-players li').length")
  [ "$n" = "2" ] && joined=1 && break
  sleep 0.5
done
[ -n "$joined" ] && echo "  Bob joined (2 players)" || echo "JOIN TIMEOUT"
ab tab t1
ab wait 400
ab eval "document.getElementById('btn-start').click()"
game=""
for i in $(seq 1 30); do
  g=$(ab eval "document.getElementById('lobby-game').hidden" | tr -d '"')
  [ "$g" = "false" ] && game=1 && break
  sleep 0.5
done
[ -n "$game" ] && echo "  game started" || { echo "START TIMEOUT"; ab errors; exit 1; }
ab wait 500

echo "-- tab1 game view + rack applied:"
ab eval "JSON.stringify({text: document.getElementById('lobby-game-text').textContent, cue: window.__pyramid.ballPositions().cue, aim: window.__pyramidGame.aimPhiDeg()})"
ab tab t2
ab wait 400
echo "-- tab2 game view + rack applied:"
ab eval "JSON.stringify({text: document.getElementById('lobby-game-text').textContent, cue: window.__pyramid.ballPositions().cue})"

echo "== 4. shot 1 from Alice (tab1, phi 90, power 12) =="
ab tab t1
ab eval "window.__pyramidGame.shoot(90, 12)"
started=""
for i in $(seq 1 30); do
  st=$(ab eval "window.__pyramid.isAnimating()" | tr -d '"')
  [ "$st" = "true" ] && started=1 && break
  sleep 0.3
done
[ -n "$started" ] && echo "  animation started" || echo "  ANIMATION NEVER STARTED"
echo "-- mid-animation:"
ab eval "JSON.stringify({animating: window.__pyramid.isAnimating(), cueNow: window.__pyramid.ballPositions().cue})"
ab eval "window.__pyramid.setAngledView(); 'angled'"
ab wait 250
ab screenshot /home/z/my-project/download/step5_midshot.png

echo "-- waiting for animation (<=60 s):"
done=""
for i in $(seq 1 50); do
  st=$(ab eval "window.__pyramid.isAnimating()" | tr -d '"')
  [ -z "$st" ] && break
  [ "$st" = "false" ] && done=1 && break
  sleep 0.5
done
[ -n "$done" ] && echo "  animation finished" || echo "  ANIMATION TIMEOUT"
ab wait 300
echo "-- tab1 after shot 1:"
ab eval "JSON.stringify({text: document.getElementById('lobby-game-text').textContent, cue: window.__pyramid.ballPositions().cue, locked: document.getElementById('btn-shoot').disabled})"
POS1=$(ab eval "JSON.stringify(window.__pyramid.ballPositions())")

echo "-- tab2 after shot 1 (synced?):"
ab tab t2
ab wait 400
ab eval "JSON.stringify({text: document.getElementById('lobby-game-text').textContent, cue: window.__pyramid.ballPositions().cue})"
POS2=$(ab eval "JSON.stringify(window.__pyramid.ballPositions())")
echo "-- positions equal across tabs:"
ab eval "(() => { const a = JSON.parse($POS1); const b = JSON.parse($POS2); if (Object.keys(a).length !== Object.keys(b).length) return JSON.stringify({error: 'count mismatch'}); let md = 0; for (const k of Object.keys(a)) { if (!b[k]) return JSON.stringify({error: 'missing ' + k}); md = Math.max(md, Math.hypot(a[k].x - b[k].x, a[k].z - b[k].z)); } return JSON.stringify({balls: Object.keys(a).length, maxDeltaM: +md.toFixed(9), same: md < 1e-9}); })()"

echo "== 5. shot 2 from Bob (tab2, phi 70, power 10) =="
ab eval "window.__pyramidGame.shoot(70, 10)"
ab wait 600
ab eval "window.__pyramid.isAnimating()"
done=""
for i in $(seq 1 50); do
  st=$(ab eval "window.__pyramid.isAnimating()" | tr -d '"')
  [ -z "$st" ] && break
  [ "$st" = "false" ] && done=1 && break
  sleep 0.5
done
[ -n "$done" ] && echo "  animation finished" || echo "  ANIMATION TIMEOUT"
ab wait 300
echo "-- tab2 after shot 2:"
ab eval "JSON.stringify({text: document.getElementById('lobby-game-text').textContent, cue: window.__pyramid.ballPositions().cue})"
ab eval "window.__pyramid.setAngledView(); 'angled'"
ab wait 350
ab screenshot /home/z/my-project/download/step5_after_shot2.png
ab tab t1
ab wait 400
echo "-- tab1 sees shot 2 result:"
ab eval "JSON.stringify({text: document.getElementById('lobby-game-text').textContent, cue: window.__pyramid.ballPositions().cue})"

echo "== 6. page errors =="
ab tab t1
ab errors
ab tab t2
ab errors

echo "== 7. stop servers =="
pkill -f "uvicorn app.main:app" 2>/dev/null
pkill -f "serve_frontend.py" 2>/dev/null
sleep 0.5
ss -tlnp 2>/dev/null | grep -E ':(8100|8090) ' || echo "ports free"
echo DONE
