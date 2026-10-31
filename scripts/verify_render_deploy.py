#!/usr/bin/env python3
"""verify_render_deploy.py — acceptance suite for the render.com deployment
addendum (post-Step-9).

Everything runs headless. Static mode (default) parses the deployment
artifacts and cross-references their contracts; --live additionally boots
the real backend on 127.0.0.1:8100 with the frontend mounted (the exact
single-container shape render.com runs) and probes it over HTTP + WS.

NO docker run, NO browser — per the project's standing verification policy.

Usage:
    /home/z/.venv/bin/python3 scripts/verify_render_deploy.py           # static
    /home/z/.venv/bin/python3 scripts/verify_render_deploy.py --live    # static + live
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

import yaml

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
PWEB = ROOT / "pyramid-web"
LIVE_PORT = 8100

RESULTS: list[tuple[bool, str]] = []


def check(label: str, ok: bool) -> bool:
    RESULTS.append((bool(ok), label))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
    return bool(ok)


def section(title: str) -> None:
    print(f"\n== {title} ==")


# ---------------------------------------------------------------------------
# A. render.yaml (Blueprint)
# ---------------------------------------------------------------------------


def check_render_yaml() -> None:
    section("A. render.yaml (Blueprint spec)")
    path = PWEB / "render.yaml"
    if not check("render.yaml exists", path.is_file()):
        return
    data = yaml.safe_load(path.read_text())
    check("parses as a YAML mapping", isinstance(data, dict))
    services = data.get("services") if isinstance(data, dict) else None
    check("exactly one service under 'services'",
          isinstance(services, list) and len(services) == 1)
    if not (isinstance(services, list) and len(services) == 1):
        return
    svc = services[0]
    check("type: web", svc.get("type") == "web")
    check("name: pyramid-web", svc.get("name") == "pyramid-web")
    check("runtime: docker (the current key; 'env' is deprecated)",
          svc.get("runtime") == "docker" and "env" not in svc)
    check("plan: free", svc.get("plan") == "free")
    dfp = svc.get("dockerfilePath", "")
    check("dockerfilePath points at the backend Dockerfile",
          dfp == "./docker/backend.Dockerfile" and (PWEB / dfp).is_file())
    check("dockerContext is the repo root '.'", svc.get("dockerContext") == ".")
    check("healthCheckPath is /api/health",
          svc.get("healthCheckPath") == "/api/health")
    check("no deprecated 'autoDeploy' key (use autoDeployTrigger)",
          "autoDeploy" not in svc)
    check("autoDeployTrigger: commit (or omitted = platform default)",
          svc.get("autoDeployTrigger", "commit") == "commit")


# ---------------------------------------------------------------------------
# B. backend.Dockerfile (render.com contract)
# ---------------------------------------------------------------------------


def check_backend_dockerfile() -> None:
    section("B. docker/backend.Dockerfile (single-container contract)")
    text = (PWEB / "docker/backend.Dockerfile").read_text()
    lines = text.splitlines()
    copy_ui = next((i for i, l in enumerate(lines) if "COPY frontend ./static" in l), -1)
    chown = next((i for i, l in enumerate(lines) if "chown -R appuser" in l), -1)
    check("frontend UI copied into the image (COPY frontend ./static)", copy_ui >= 0)
    check("frontend COPY happens before the chown layer (numba cache stays writable)",
          0 <= copy_ui < chown)
    check("PYRAMID_STATIC_DIR=/app/static baked into the image",
          "PYRAMID_STATIC_DIR=/app/static" in text)
    cmd = next((l for l in lines if l.startswith("CMD ")), "")
    check("shell-form CMD honoring ${PORT:-8000} (render.com $PORT, compose default 8000)",
          "PORT:-8000" in cmd and "0.0.0.0" in cmd)
    check("CMD still runs uvicorn app.main:app", "uvicorn app.main:app" in cmd)
    check("CMD has no --reload and no --workers",
          "--reload" not in cmd and "--workers" not in cmd)
    check("EXPOSE 8000 kept (compose/documentation contract)",
          any(l.startswith("EXPOSE 8000") for l in lines))


# ---------------------------------------------------------------------------
# C. backend/app/main.py (static hosting + route precedence)
# ---------------------------------------------------------------------------


def check_main_py() -> None:
    section("C. backend/app/main.py (static mount, gzip, precedence)")
    text = (PWEB / "backend/app/main.py").read_text()
    check('VERSION bumped to "0.7.0"', 'VERSION = "0.7.0"' in text)
    check("imports StaticFiles", "from fastapi.staticfiles import StaticFiles" in text)
    check("imports GZipMiddleware",
          "from starlette.middleware.gzip import GZipMiddleware" in text)
    ws_idx = text.find('@app.websocket("/ws")')
    mount_idx = text.find('app.mount("/",')
    check("the catch-all mount is registered AFTER every route (incl. /ws)",
          0 <= ws_idx < mount_idx)
    check("mount serves the tree with html=True (index.html at /)",
          'StaticFiles(directory=_frontend, html=True)' in text)
    check("PYRAMID_STATIC_DIR env var is honored first",
          'os.environ.get("PYRAMID_STATIC_DIR"' in text)
    check("mount is conditional: requires index.html to exist",
          '(cand / "index.html").is_file()' in text)
    check("gzip enabled in single-container mode (minimum_size=1024)",
          "app.add_middleware(GZipMiddleware, minimum_size=1024)" in text)


# ---------------------------------------------------------------------------
# D. frontend/lobby.js (keepalive ping)
# ---------------------------------------------------------------------------


def check_lobby_js() -> None:
    section("D. frontend/lobby.js (WS keepalive)")
    path = PWEB / "frontend/lobby.js"
    text = path.read_text()
    check("startKeepalive defined", "function startKeepalive(" in text)
    check("stopKeepalive defined", "function stopKeepalive(" in text)
    check("sends {type: 'ping'} (server answers pong)", "type: 'ping'" in text)
    check("55 s interval (< 15 min render.com idle window)",
          "55000" in text)
    check("started on socket open", "startKeepalive(ws)" in text.split("ws.onopen")[1].split("};")[0])
    check("stopped on close and on reset",
          text.count("stopKeepalive();") >= 3)
    proc = subprocess.run(
        ["node", "--check", str(path)], check=False, capture_output=True, text=True
    )
    check("node --check parses the file", proc.returncode == 0)


# ---------------------------------------------------------------------------
# E. README deployment section
# ---------------------------------------------------------------------------


def check_readme() -> None:
    section("E. README.md (render.com deployment guide)")
    text = (PWEB / "README.md").read_text()
    check("has a 'Deploy to render.com' section", "Deploy to render.com" in text)
    check("documents the Blueprint path (render.yaml)",
          "render.yaml" in text and "Blueprint" in text)
    check("documents the manual Web Service path with the Dockerfile path",
          "docker/backend.Dockerfile" in text)
    check("mentions the health check path /api/health", "/api/health" in text)
    check("warns about the 15-minute idle spin-down", "15 min" in text)
    check("explains that WebSocket messages count as traffic (keepalive ping)",
          "keepalive" in text)
    check("documents the 512 MB free instance", "512 MB" in text)
    check("documents in-memory rooms being wiped on spin-down",
          "in-memory" in text)
    check("mentions wss:// TLS termination by render.com", "wss://" in text)
    check("documents render.com's $PORT (default 10000)", "10000" in text)


# ---------------------------------------------------------------------------
# F. docker-compose.yml (unchanged local contract)
# ---------------------------------------------------------------------------


def check_compose() -> None:
    section("F. docker-compose.yml (local path unchanged)")
    text = (PWEB / "docker-compose.yml").read_text()
    check("still maps 8000:8000 (CMD default PORT:-8000 applies there)",
          '"8000:8000"' in text)
    check("frontend/nginx path untouched (still the primary local entry point)",
          '"8080:80"' in text)


# ---------------------------------------------------------------------------
# Live mode — the single-container shape render.com runs
# ---------------------------------------------------------------------------


def http_get(url: str, gzip_wanted: bool = False):
    req = urllib.request.Request(url)
    if gzip_wanted:
        req.add_header("Accept-Encoding", "gzip")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


async def ws_checks() -> tuple[bool, bool]:
    import websockets

    uri = f"ws://127.0.0.1:{LIVE_PORT}/ws"
    joined_ok = ping_ok = False
    async with websockets.connect(uri) as ws:
        # handshake first (exactly like the real client: create/join is the
        # first message; keepalive pings only start 55 s later, in-room)
        await ws.send(json.dumps({"type": "create", "name": "RenderProbe"}))
        reply = json.loads(await ws.recv())
        joined_ok = (
            reply.get("type") == "joined"
            and len(reply.get("room", "")) == 4
        )
        # then the keepalive round-trip
        await ws.send(json.dumps({"type": "ping"}))
        reply = json.loads(await ws.recv())
        ping_ok = reply.get("type") == "pong"
    return joined_ok, ping_ok


def run_live() -> None:
    section(f"G. LIVE — backend on :{LIVE_PORT} with frontend mounted")
    import asyncio

    env = dict(os.environ)
    env.update(
        PYTHONHASHSEED="0",
        PYRAMID_STATIC_DIR=str(PWEB / "frontend"),
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(LIVE_PORT)],
        cwd=str(PWEB / "backend"), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        # 1. health: poll until physics_ready (JIT warmup)
        deadline = time.time() + 60
        healthy = False
        while time.time() < deadline:
            try:
                status, _, body = http_get(f"http://127.0.0.1:{LIVE_PORT}/api/health")
                data = json.loads(body)
                if status == 200 and data.get("physics_ready"):
                    healthy = True
                    break
            except (urllib.error.URLError, OSError, json.JSONDecodeError):
                pass
            time.sleep(1.0)
        check("/api/health reports physics_ready (JIT warm)", healthy)

        # 2. the UI at /
        status, _, body = http_get(f"http://127.0.0.1:{LIVE_PORT}/")
        page = body.decode("utf-8", "replace")
        check("GET / serves index.html (importmap + canvas markers)",
              status == 200 and "vendor/three.module.js" in page
              and '<canvas id="scene">' in page)

        # 3. static sub-paths
        for path, label in [
            ("/style.css", "GET /style.css"),
            ("/main.js", "GET /main.js"),
            ("/lobby.js", "GET /lobby.js"),
            ("/vendor/three.module.js", "GET /vendor/three.module.js"),
        ]:
            status, _, _ = http_get(f"http://127.0.0.1:{LIVE_PORT}{path}")
            check(f"{label} -> 200", status == 200)

        # 4. gzip compression on / (case-insensitive header lookup — Starlette
        # sends lowercase field names, HTTP/1.1 semantics are case-insensitive)
        status, headers, _ = http_get(
            f"http://127.0.0.1:{LIVE_PORT}/", gzip_wanted=True
        )
        lower_headers = {k.lower(): v for k, v in headers.items()}
        check("GET / with Accept-Encoding: gzip -> Content-Encoding: gzip",
              status == 200
              and lower_headers.get("content-encoding") == "gzip")

        # 5. route precedence over the catch-all mount
        status, _, _ = http_get(f"http://127.0.0.1:{LIVE_PORT}/docs")
        check("GET /docs -> 200 (API routes keep precedence)", status == 200)
        status, _, _ = http_get(f"http://127.0.0.1:{LIVE_PORT}/definitely-missing")
        check("GET /definitely-missing -> 404 (no SPA masking)",
              status == 404)

        # 6. WebSocket: room create + keepalive ping on the same origin
        joined_ok, ping_ok = asyncio.run(ws_checks())
        check("WS create -> joined (4-letter room, same origin as the UI)",
              joined_ok)
        check("WS ping -> pong (keepalive round-trip, in-room)", ping_ok)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)


def main() -> None:
    print("pyramid-web — render.com deployment addendum verification")
    check_render_yaml()
    check_backend_dockerfile()
    check_main_py()
    check_lobby_js()
    check_readme()
    check_compose()
    if "--live" in sys.argv:
        run_live()
    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n{'ALL' if passed == total else 'FAILED'}: "
          f"{passed}/{total} checks passed")
    if passed != total:
        for ok, label in RESULTS:
            if not ok:
                print(f"  FAILED: {label}")
        sys.exit(1)


if __name__ == "__main__":
    main()
