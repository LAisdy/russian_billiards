#!/bin/bash
# Step 4b E2E: fresh backend + dev server + headless browser screenshots, one shot.
set -u
cd /home/z/my-project/pyramid-web

echo "== 0. free ports =="
for port in 8100 8090; do
  pids=$(ss -tlnp 2>/dev/null | grep ":$port " | grep -oP 'pid=\K[0-9]+' | sort -u)
  if [ -n "$pids" ]; then kill $pids 2>/dev/null; echo "killed on :$port: $pids"; fi
done
sleep 0.5

echo "== 1. servers =="
(cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8100 >/tmp/uv4b.log 2>&1 &)
backend/.venv/bin/python /home/z/my-project/scripts/serve_frontend.py 8090 >/tmp/dev4b.log 2>&1 &
for i in $(seq 1 60); do curl -sf http://127.0.0.1:8100/api/health >/dev/null 2>&1 && break; sleep 0.25; done
curl -sf http://127.0.0.1:8090/api/health && echo "  <- dev proxy OK"

echo "== 2. browser E2E =="
agent-browser set viewport 1440 900
agent-browser open http://127.0.0.1:8090
agent-browser wait 3200
agent-browser eval "document.getElementById('lobby').style.display='none'; 'lobby hidden'"
echo "-- stats:"; agent-browser eval "JSON.stringify(window.__pyramid.stats())"
echo "-- frameCheck:"; agent-browser eval "JSON.stringify(window.__pyramid.frameCheck())"
echo "-- HUD:"; agent-browser eval "document.getElementById('hud-table').textContent + ' | ' + document.getElementById('hud-backend').textContent"

echo "== 3. screenshots =="
agent-browser eval "window.__pyramid.setTopView(); 'top'"
agent-browser wait 800
agent-browser screenshot /home/z/my-project/download/step4b_top.png
agent-browser eval "window.__pyramid.setAngledView(); 'angled'"
agent-browser wait 800
agent-browser screenshot /home/z/my-project/download/step4b_angled.png
agent-browser eval "window.__pyramid.setPocketZoom(0); 'corner pocket'"
agent-browser wait 800
agent-browser screenshot /home/z/my-project/download/step4b_pocket_corner.png
agent-browser eval "window.__pyramid.setPocketZoom(4); 'middle pocket'"
agent-browser wait 800
agent-browser screenshot /home/z/my-project/download/step4b_pocket_middle.png
agent-browser eval "window.__pyramid.setBallView('8'); 'ball'"
agent-browser wait 800
agent-browser screenshot /home/z/my-project/download/step4b_ball.png

echo "== 4. page errors =="
agent-browser errors

echo "== 5. stop servers =="
pkill -f "uvicorn app.main:app" 2>/dev/null
pkill -f "serve_frontend.py" 2>/dev/null
sleep 0.5
ss -tlnp 2>/dev/null | grep -E ':(8100|8090) ' || echo "ports free"
echo DONE
