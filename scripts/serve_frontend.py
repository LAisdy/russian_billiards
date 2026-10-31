#!/usr/bin/env python3
"""Local dev server for pyramid-web/frontend (the sandbox has no Docker/nginx).

Mirrors docker/nginx.conf exactly, so the frontend code paths are identical
to the containerized deployment:

  - static files from pyramid-web/frontend/
  - /api/* -> http://127.0.0.1:8100/api/*   (HTTP reverse proxy)
  - /ws    -> ws://127.0.0.1:8100/ws        (bidirectional WebSocket relay)

Requires aiohttp (dev-only dependency — deliberately NOT in
backend/requirements.txt, because production containers use nginx for this):

    uv pip install --python backend/.venv/bin/python aiohttp

Usage:
    backend/.venv/bin/python scripts/serve_frontend.py [port]   # default 8090
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

FRONTEND_ROOT = Path("/home/z/my-project/pyramid-web/frontend").resolve()
BACKEND_HTTP = "http://127.0.0.1:8100"
BACKEND_WS = "ws://127.0.0.1:8100/ws"

HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


async def serve_index(_request: web.Request) -> web.StreamResponse:
    return web.FileResponse(FRONTEND_ROOT / "index.html")


async def api_proxy(request: web.Request) -> web.StreamResponse:
    """Forward /api/* to the backend (method, body, query string)."""
    url = f"{BACKEND_HTTP}{request.path_qs}"
    body = await request.read()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS}
    async with (
        ClientSession(timeout=ClientTimeout(total=30)) as session,
        session.request(request.method, url, data=body, headers=headers) as resp,
    ):
        payload = await resp.read()
        out = web.Response(status=resp.status, body=payload)
        for k, v in resp.headers.items():
            if k.lower() not in HOP_HEADERS:
                out.headers.add(k, v)
        return out


async def ws_relay(src, dst) -> None:
    """Pump WebSocket frames from src to dst until either side closes."""
    async for msg in src:
        if msg.type == WSMsgType.TEXT:
            await dst.send_str(msg.data)
        elif msg.type == WSMsgType.BINARY:
            await dst.send_bytes(msg.data)
        else:
            break


async def ws_proxy(request: web.Request) -> web.StreamResponse:
    """Relay a browser WebSocket to the backend's /ws endpoint."""
    client_ws = web.WebSocketResponse(heartbeat=30)
    await client_ws.prepare(request)
    async with ClientSession() as session:
        try:
            backend_ws = await session.ws_connect(BACKEND_WS, heartbeat=30)
        except OSError:
            await client_ws.close(code=1011, message=b"backend unavailable")
            return client_ws

        tasks = [
            asyncio.create_task(ws_relay(client_ws, backend_ws)),
            asyncio.create_task(ws_relay(backend_ws, client_ws)),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            if task.exception() is not None and not isinstance(
                task.exception(), (ConnectionError, RuntimeError)
            ):
                print(f"[dev] ws relay error: {task.exception()!r}", file=sys.stderr)
        if not backend_ws.closed:
            await backend_ws.close()
        if not client_ws.closed:
            await client_ws.close()
    return client_ws


async def static_files(request: web.Request) -> web.StreamResponse:
    """Catch-all GET handler serving files from FRONTEND_ROOT (traversal-safe)."""
    rel = request.path.lstrip("/")
    if not rel:
        return await serve_index(request)
    target = (FRONTEND_ROOT / rel).resolve()
    inside_root = str(target).startswith(str(FRONTEND_ROOT) + "/") or (
        target == FRONTEND_ROOT
    )
    if not inside_root or not target.is_file():
        raise web.HTTPNotFound(text="not found")
    return web.FileResponse(target)


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_route("*", "/api/{tail:.*}", api_proxy)
    app.router.add_get("/ws", ws_proxy)
    app.router.add_get("/{tail:.*}", static_files)
    return app


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    print(f"[dev] serving {FRONTEND_ROOT} at http://127.0.0.1:{port}")
    print(f"[dev] proxying /api/* -> {BACKEND_HTTP}/api and /ws -> {BACKEND_WS}")
    web.run_app(
        build_app(),
        host="127.0.0.1",
        port=port,
        print=lambda *args: None,
        access_log=None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
