# pyramid-web — Multiplayer Russian Pyramid (billiards) for the browser

Web port of the [pooltool](https://github.com/ekiefl/pooltool)-based Russian
Pyramid extension (physics engine preserved verbatim — see
[`../pooltool/`](../pooltool/) and its `PROGRESS.md`).

- **Backend:** FastAPI (Python) + vendored pooltool physics — `backend/`
- **Frontend:** Three.js (ES modules, vendored — no CDN needed) — `frontend/`
- **Deployment:** Docker Compose — `docker-compose.yml`, `docker/`

Status: Steps 1–3 done (skeleton, lobby/WebSockets, physics engine; see
`PROGRESS.md` for the full 0–9 roadmap).

## Physics engine (Step 3)

The Russian-Pyramid-extended pooltool engine is **vendored** into
`backend/pooltool/` — 119 physics files byte-identical to the source repo
(provenance, diff policy, and the 6 Panda3D-glue shims are documented in
`backend/pooltool/VENDORED.md`; regenerate/verify with
`python scripts/vendor_physics.py [--check]`). The acceptance test proved the
original repo, the vendored copy, and the HTTP API produce **identical**
(float-exact) simulation results for a seeded 16-ball 3D break.

REST API (all state in pooltool coordinates: `x` across the table width
0..1.80 m, `y` along the length 0..3.70 m, y=0 = head rail):

- `GET /api/rack?seed=N` — the standard 15-ball pyramid rack + cue ball
  (seeded = bit-reproducible; unseeded = random placement per the rules).
  Also echoes table/ball equipment (pocket centers & radii included).
- `POST /api/shot` — simulate one stroke:

  ```json
  {
    "balls": {"cue": {"x": 0.9, "y": 0.851}, "1": {"x": 0.9, "y": 2.775}},
    "v0": 4.0,                    // cue impact speed, m/s (0.05..10)
    "phi": 90.0,                  // direction, degrees CCW from +x
    "a": 0.0, "b": 0.25,          // optional spin, -1..1 (library defaults)
    "theta": 0.0                  // optional masse elevation, degrees
  }
  ```

  Response: final `balls` positions + per-ball state, `pocketed` ids,
  `duration_s`, `events`, `sim_ms`. Invalid input → 422.

Notes:

- The backend runs a startup **JIT warmup** (2D example + a full 3D break,
  ~2 s with numba's disk cache, ~25 s cold) in a background thread;
  `/api/health` reports `physics_ready`.
- Seeded racks are only reproducible **across processes** with
  `PYTHONHASHSEED=0` (set in `docker/backend.Dockerfile` and the dev recipes
  below; see `backend/app/physics.py` for why).
- Single worker process only (in-memory lobby state + numba cache).

## Run with Docker (target machines)

```bash
docker-compose up -d --build
# frontend:  http://localhost:8080   (Three.js scene)
# backend:   http://localhost:8000/api/health
```

## Run locally without Docker (development)

```bash
# backend (FastAPI + lobby WebSockets + physics on :8100)
cd backend
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
# dev-only dep for the frontend dev server (production uses nginx):
uv pip install --python .venv/bin/python aiohttp
PYTHONHASHSEED=0 .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8100

# frontend dev server (static + /api + /ws proxy on :8090, mirrors docker/nginx.conf)
.venv/bin/python ../../scripts/serve_frontend.py 8090
# open http://127.0.0.1:8090 — create a room, then join from a second tab

# tests (backend must be running on :8100)
.venv/bin/python ../../scripts/test_lobby_ws.py            # lobby protocol
PYTHONHASHSEED=0 .venv/bin/python ../../scripts/test_physics_api.py
# then, with the pooltool source venv (original-vs-vendored comparison):
PYTHONHASHSEED=0 ../pooltool/.venv/bin/python ../../scripts/test_physics_original.py
```
