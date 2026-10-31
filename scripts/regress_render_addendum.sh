#!/usr/bin/env bash
# Regression battery for the render.com deployment addendum.
# In-process suites first (no server), then one uvicorn on :8100 serving the
# step-5/6/8 live suites, then the render-deploy live suite (self-hosted).
# Everything happens inside THIS script: start -> poll -> test -> kill.
set -u
cd /home/z/my-project
PY=/home/z/.venv/bin/python3
FAIL=0

run() {
  echo ""
  echo "===================== $* ====================="
  "$@" || FAIL=1
}

# --- in-process suites (no server needed) ---
run $PY scripts/verify_step5_keyframes.py
run $PY scripts/verify_step6_rules.py
run $PY scripts/verify_step7_numba.py

# --- live server for the WS/UI suites ---
echo ""
echo "===================== booting uvicorn on :8100 ====================="
cd pyramid-web/backend
PYTHONHASHSEED=0 $PY -m uvicorn app.main:app --host 127.0.0.1 --port 8100 \
  >/tmp/uvicorn_regress.log 2>&1 &
SRV=$!
cd /home/z/my-project

READY=0
for _ in $(seq 1 60); do
  if curl -sf http://127.0.0.1:8100/api/health 2>/dev/null | grep -q '"physics_ready":true'; then
    READY=1
    break
  fi
  sleep 1
done
if [ "$READY" != "1" ]; then
  echo "FATAL: backend did not become physics_ready in 60 s"
  tail -5 /tmp/uvicorn_regress.log
  kill $SRV 2>/dev/null
  exit 1
fi
echo "backend ready (physics_ready: true)"

run $PY scripts/verify_step5_ws.py
run $PY scripts/verify_step6_ws.py
run $PY scripts/verify_step8_ui.py --live

kill $SRV 2>/dev/null
wait $SRV 2>/dev/null
echo ""
echo "===================== uvicorn stopped ====================="

# --- render-deploy live suite (boots and kills its own server) ---
run $PY scripts/verify_render_deploy.py --live

echo ""
if [ "$FAIL" = "0" ]; then
  echo "REGRESSION BATTERY: ALL SUITES PASSED"
else
  echo "REGRESSION BATTERY: AT LEAST ONE SUITE FAILED"
fi
exit $FAIL
