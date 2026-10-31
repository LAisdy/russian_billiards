# pyramid-web — Multiplayer Russian Pyramid (Billiards) for the Browser

A two-player online Russian Pyramid («пирамидка») game: the **pooltool**
physics engine is preserved verbatim (Numba-JIT, byte-identical vendoring)
and served behind a FastAPI backend; the browser renders a full 3D
12-ft table with Three.js — no plugins, no CDN, everything vendored.

**Four disciplines, enforced server-side** by the vendored rulesets:

| Mode | Russian | Race target | Signature rules |
|:--|:--|:--:|:--|
| Free | «Свободная» | 8 | any ball counts, fouls give a point + penalty-ball removal |
| Combined | «Комбинированная» / Московская | 8 | house-line ball-in-hand, first-contact fouls |
| Dynamic | «Динамичная» / Невская | 8 | ball-in-hand anywhere, scratch respots for both |
| Classic | «Классическая» | 71 | «заказ» — called ball and called pocket, −5/+5 scratch swing |

Other highlights: 4-letter room codes and lobbies, server-authoritative
simulation with keyframe broadcast (never per-tick), live HUD (turn, shot
clock, scores, remaining-ball chips), four camera presets with smooth
tweened transitions, permessage-deflate on the wire (breaks ship at ~6–12×
compression), and a UI that never blocks while a shot is simulated.

---

## Requirements

- **Docker 24+** with **Compose v2** (`docker compose version`) — this is
  the only dependency; both images build from official bases
  (`python:3.12-slim`, `node:22-alpine`, `nginx:1.27-alpine`) on x86-64 and
  ARM64 (Apple Silicon included).
- Free ports **8080** (web) and **8000** (API/docs) on the host.
- ~1.5 GB disk for images; the backend container is happiest with ~1 GB RAM
  (Numba JIT compilation is the peak).

## Quickstart

```bash
cd pyramid-web
docker compose up -d --build
```

Wait for the physics warmup (first build/boot compiles the JIT kernels;
~25 s cold, ~2 s once the numba disk cache is warm):

```bash
curl http://localhost:8000/api/health
# {"status":"ok",...,"physics_ready":true}   <- ready when true
```

Then open **http://localhost:8080** in TWO tabs/devices:

1. Player 1: enter a name → **Create room** → share the 4-letter code.
2. Player 2: enter a name → **Join room** → type the code.
3. Host picks a discipline → **Start game** → break off!

Direct backend access (optional): API docs at
http://localhost:8000/docs, health at http://localhost:8000/api/health,
room list at http://localhost:8000/api/rooms. The frontend proxies
`/api` and `/ws` to the backend internally, so browsers only need :8080.

Stop everything:

```bash
docker compose down        # add -v only if you want to drop anonymous volumes
```

## How to play

- **Aiming:** move the mouse on the table to set the direction (the aim line
  and 3D cue stick follow), drag to orbit the camera instead — a click aims,
  a drag orbits.
- **Power:** the slider maps 1–100 % to a 0.3–9.0 m/s cue speed; **Shoot**
  plays the strike and sends the shot to the server.
- **Ball-in-hand:** when the referee grants «с руки», press *Placing cue
  ball* then click a legal spot (the house is highlighted for
  behind-the-line grants; placement is validated server-side).
- **Classic «заказ»:** after the break, pick the ball and pocket you call —
  only that pot scores.
- **Cameras:** HUD buttons — `orbit` (free orbit), `top` (plan view),
  `south`/`north` (each player's chair). Transitions tween smoothly and any
  mouse grab cancels the tween; your last view is remembered.
- **Scoring & turns** are decided by the vendored rulesets and broadcast to
  both clients; the HUD shows turn, shot clock, scores and the balls still
  on the table. First to the race target wins; the host can start a rematch.

## Architecture

```
 browser tab A ─┐                      ┌─ static Three.js app (vendored ES modules)
 browser tab B ─┼── :8080 nginx ───────┤
                │      │  location /        (index.html, main.js, lobby.js,
                │      │                     ui_math.js, vendor/three.*)
                │      ├─ location /api/ ──► :8000 FastAPI (REST: health, rooms,
                │      │                      modes, rack, shot)
                │      └─ location /ws  ──► :8000 WebSocket /ws
                │                            (lobby + game protocol,
                │                             permessage-deflate end-to-end)
                │
                └─ backend container: uvicorn, SINGLE worker
                     app/lobby.py   rooms, players, turn gates, broadcasts
                     app/rules.py   the four vendored Ruleset classes
                     app/physics.py pooltool engine → keyframes
                     pooltool/      vendored physics (JIT, byte-identical)
```

The backend image also ships the frontend tree (`PYRAMID_STATIC_DIR`): run
standalone, it serves the UI itself at `/` (with gzip) next to `/api` and
`/ws` — the single-container shape used on render.com (see below). Under
docker-compose, nginx stays the primary entry point and nothing changes.

Why it feels instant: the server runs the event-based simulation (typical
stroke 5–26 ms, worst measured break 660 ms round-trip), converts the
trajectory into keyframes on a 40 ms grid **plus every collision instant**
(exact physics states, not linearizations), and every client interpolates
through them at 60 fps. The wire carries only keyframes (~20 KiB on the
wire for a full break after permessage-deflate). The UI never blocks — a
"Simulating… N ms" ticker runs while the shot is in flight, and the canvas
stays interactive.

Configuration is intentionally minimal:

| Setting | Value | Where |
|:--|:--|:--|
| Web port | 8080 → 80 (nginx) | `docker-compose.yml` |
| API/docs port | 8000 → 8000 (uvicorn) | `docker-compose.yml` |
| `PORT` | uvicorn port override: unset → 8000; render.com injects 10000 and the image honors it | `docker/backend.Dockerfile` CMD |
| `PYTHONHASHSEED` | `0` (baked into the image) | `docker/backend.Dockerfile` |
| Workers | exactly 1 (in-memory rooms + JIT cache) | `docker/backend.Dockerfile` CMD |
| Persistence | none needed — rooms live in process memory | — |

To change ports, copy `docker-compose.yml` to an override or edit the
`ports:` lines — no other file references them.

## Deploy to render.com

One web service runs the whole game: the backend image serves the frontend
UI at `/` next to `/api` and `/ws`, so there is a single URL and both
players open it (`wss://` WebSocket and TLS are handled by Render
automatically). No database, no environment variables, no disks — rooms
live in process memory.

**What you need:** this `pyramid-web/` folder pushed to a GitHub or GitLab
repository, and a free [render.com](https://render.com/) account.

Push the project first (from the repo root):

```bash
git init && git add -A && git commit -m "pyramid-web"
git remote add origin git@github.com:<you>/pyramid-web.git
git push -u origin main
```

### Option A — Blueprint (uses render.yaml, recommended)

1. Dashboard → **New +** → **Blueprint** → pick the repository.
2. Render reads `render.yaml` and pre-fills everything: runtime **Docker**,
   Dockerfile path `docker/backend.Dockerfile`, health check
   `/api/health`, instance type **Free**.
3. **Apply** — the first build installs the pinned pip stack and bakes the
   numba JIT cache into an image layer (a few minutes).
4. When the service shows **Live**, open
   `https://pyramid-web-xxxx.onrender.com` — that URL *is* the game. Send
   it to the second player (or open it on the phone).

### Option B — Manual web service

1. Dashboard → **New +** → **Web Service** → connect the repository.
2. Runtime: **Docker**; **Dockerfile Path**: `docker/backend.Dockerfile`
   (build context = repo root). Leave **Docker Command** empty — the image
   honors Render's injected `PORT` (default 10000) by itself.
3. **Health Check Path**: `/api/health`. Instance type: **Free**.
4. **Create Web Service** → wait for **Live**.

Both options deploy identical images; `render.yaml` merely automates the
form. Every push to the selected branch redeploys (auto-deploy on commit).

### Free-tier behavior to expect

| Aspect | What happens |
|:--|:--|
| Sleep | a Free service spins down after **15 min** with no inbound HTTP request *and* no WebSocket message; the client's built-in 55 s keepalive ping keeps an open game alive, but an untouched lobby will sleep |
| Wake-up | the next request spins it back up (~1 min); after that the health endpoint may still report `physics_ready: false` for a moment while the JIT cache warms (~2 s warm, up to ~25 s truly cold) |
| Rooms | rooms are **in-memory** — every spin-down wipes them; players simply re-join with a fresh 4-letter code |
| Size | Free = 512 MB RAM, shared CPU; the backend is a single uvicorn worker and fits comfortably |
| Hours | 750 free instance hours per workspace per month; hours are consumed only while the service is up (spun-down time is free) |
| Allowances | Free bandwidth and build minutes are monthly allowances; without a payment method Render suspends free services that exceed them until the next month |

Two players must use the same service URL — there is exactly one instance,
and rooms are not shared across instances. WebSockets are supported on all
plans; paid plans simply don't spin down.

## Troubleshooting

| Symptom | Cause / fix |
|:--|:--|
| `/api/health` says `physics_ready: false` for ~25 s | normal cold JIT warmup (background thread; ~2 s when the numba disk cache in the image layer is already warm) |
| Frontend up but "backend: down" in the HUD | backend still warming or crashed — `docker compose logs backend`; the healthcheck gates the frontend start anyway |
| "room not found" after a backend restart | rooms are in-memory by design; refresh and create a new room |
| On render.com: slow first page load after a while | the Free instance had spun down (15 min idle) — ~1 min wake-up; keep the tab open, the keepalive ping prevents sleeps *during* a game |
| WebSocket drops on very long idle | nginx keeps game sockets alive 3600 s; behind your own reverse proxy raise `proxy_read_timeout` similarly |
| Seeded rack differs between two containers | don't override `PYTHONHASHSEED`; the image fixes it to 0 (rack IDs come from `random.choice(list(<set>))`) |
| Port 8080/8000 already in use | change the host side of the mapping in `docker-compose.yml` |
| Apple Silicon | supported (multi-arch bases); numba wheels exist for arm64 |

## Development without Docker

```bash
cd pyramid-web/backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
pip install aiohttp              # dev-only: the static/dev proxy needs it

# backend with in-process physics on :8100 (PYTHONHASHSEED=0 matters here too)
PYTHONHASHSEED=0 uvicorn app.main:app --host 127.0.0.1 --port 8100

# second terminal: dev frontend on :8090 (static + /api + /ws proxy,
# mirrors docker/nginx.conf behavior)
. .venv/bin/activate
python ../scripts/serve_frontend.py 8090
# open http://127.0.0.1:8090 in two tabs to play
```

The production containers use nginx; `serve_frontend.py` exists only so the
browser code paths can be exercised identically during development.

## Verification suite

All acceptance checks run headless (in-process or against a live
`uvicorn` on :8100 — no browser required):

| Script | Checks | Proves |
|:--|:--:|:--|
| `scripts/verify_render_deploy.py` | 46 + 11 live | render.com Blueprint/Dockerfile contracts, single-container UI serving, gzip, WS keepalive |
| `scripts/verify_step9_docker.py` | 89 | multi-stage Dockerfiles, compose wiring, nginx contracts, cross-references |
| `scripts/verify_step8_ui.py --static` | 47 | HUD/camera/responsive wiring, markup↔JS↔CSS consistency |
| `scripts/verify_step8_ui.py --live` | 18 | turn clock broadcast, remaining-ball arithmetic, snapshot identity |
| `scripts/verify_step7_numba.py` | 5 | 20 hot JIT kernels compiled, warm break < 500 ms |
| `scripts/profile_step7.py` | 19 | latency/traffic budgets, deflate negotiation |
| `scripts/verify_step6_rules.py` | 44 | all four rulesets: fouls, calls, respots, race end |
| `scripts/verify_step6_ws.py` | 27 | full multiplayer protocol regression |
| `scripts/verify_step5_keyframes.py` | 18 | keyframe physics exactness + pruning invariants |
| `scripts/verify_step5_ws.py` | 18 | byte-identical broadcast, shot chaining, REST parity |

Run the file-only checks anywhere (they only parse files):

```bash
python ../scripts/verify_render_deploy.py          # render.com addendum
python ../scripts/verify_step9_docker.py           # docker artifacts
```

## Project layout

```
pyramid-web/
├── backend/
│   ├── app/            FastAPI: main.py (HTTP+WS), lobby.py, rules.py, physics.py
│   ├── pooltool/       vendored engine (119 files byte-identical; VENDORED.md)
│   └── requirements.txt
├── frontend/           index.html, main.js, lobby.js, ui_math.js, style.css,
│                       vendor/ (three.js 0.187.0 + OrbitControls + LICENSE)
├── docker/             backend.Dockerfile (2-stage, ships the UI, honors $PORT),
│                       frontend.Dockerfile (node gate → nginx), nginx.conf
├── docker-compose.yml  backend :8000 + frontend :8080, healthcheck-gated
├── render.yaml         render.com Blueprint (one web service, free plan)
├── .dockerignore       keeps .venv/__pycache__/.git out of the build context
├── PROGRESS.md         full step-by-step build log (steps 0–9) with evidence
└── RULES_DEVIATIONS.md web-port ruleset deviations (none in force)
```

## Physics provenance & license

`backend/pooltool/` is generated by `scripts/vendor_physics.py` from
[pooltool](https://github.com/ekiefl/pooltool) commit `7632b1c66f19`
(v0.6.0), **Apache-2.0** — see `backend/pooltool/VENDORED.md` and
`backend/pooltool/LICENSE`. The vendoring is byte-identical for all 119
physics/ruleset/layout files (re-verify with
`python scripts/vendor_physics.py --check`); only 6 Panda3D-glue files are
shimmed, none of them physics. The acceptance test proved the original
repo, the vendored copy, and the HTTP API produce float-exact identical
results on a seeded 1728-event 3D break.
