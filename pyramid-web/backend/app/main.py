"""pyramid-web backend — FastAPI application entry point.

Step 1: health/hello endpoints.
Step 2: lobby system — WebSocket endpoint ``/ws`` (create/join/start_game
        protocol, see ``app/lobby.py``) plus room-introspection REST
        endpoints under ``/api/rooms``.
Step 3: physics — the vendored pooltool engine (``backend/pooltool/``, see
        its ``VENDORED.md``) behind ``GET /api/rack`` and ``POST /api/shot``
        (cue angle + force -> final ball coordinates); numba kernels are
        JIT-warmed in a background thread at startup.
Step 5: shot synchronization — rooms carry the current ball state;
        ``shot`` WS messages run the simulation off the event loop and
        broadcast ``shot_result`` with trajectory keyframes (uniform 40 ms
        grid + every event time, each keyframe the exact physics state);
        ``POST /api/shot`` can return the same keyframes via
        ``"keyframes": true`` for headless testing.
Step 6: game modes & rulesets — ``GET /api/modes`` lists the four
        disciplines; the room's vendored ruleset (see ``app/rules.py``)
        enforces turns, calls, respotting, ball-in-hand and scoring on the
        WS protocol (``set_mode`` / ``place_cue`` / call fields on ``shot``);
        every ``game_started`` / ``shot_result`` broadcast carries the full
        game-state snapshot.
Step 7: high-performance optimization — keyframe payloads are pruned
        (stationary-tail frames dropped; frame 0, the final frame and every
        event-time frame always kept) and every ``shot_result`` carries
        ``kf_stats`` (frames/events/bytes/pruned) for traffic profiling;
        WebSocket permessage-deflate is on by default (uvicorn) and its
        negotiation is asserted by ``scripts/profile_step7.py``; JIT
        compilation of the numba kernels is verified by
        ``scripts/verify_step7_numba.py``. The client gets instant local
        strike feedback (cue-stick lunge) and a live non-blocking
        "Simulating…" ticker — the UI never shows a blocking
        "Calculating shot…" screen.
Step 8: UI polish & camera — every game snapshot additionally carries the
        turn clock (``turn_started_ms`` + ``now_ms``, informational only:
        the vendored rulesets define no shot-clock rule, so the server does
        not enforce one); the client renders the HUD bar (scores, turn,
        remaining-ball chips), camera presets with smooth tweens, and
        aspect-ratio-responsive layout.

Run (dev):  uvicorn app.main:app --host 127.0.0.1 --port 8100
Run (docker): see docker/backend.Dockerfile
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field

from . import physics, rules
from .lobby import LobbyError, Session, manager
from .physics import PhysicsError

logger = logging.getLogger(__name__)

APP_NAME = "pyramid-web-backend"
VERSION = "0.6.0"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # JIT-compile the physics kernels off the critical path (see
    # app/physics.py::warmup — first un-warmed shot costs ~25 s of numba
    # compilation, steady state is 75-190 ms).
    threading.Thread(target=physics.warmup, name="physics-warmup", daemon=True).start()
    yield


app = FastAPI(
    title=APP_NAME,
    version=VERSION,
    description="Multiplayer Russian Pyramid (billiards) backend",
    lifespan=lifespan,
)


@app.get("/api/health")
def health() -> dict:
    """Liveness probe; also used by the frontend HUD to prove the /api proxy path."""
    return {
        "status": "ok",
        "service": APP_NAME,
        "version": VERSION,
        "time": time.time(),
        "physics_ready": physics.warm_ready(),
    }


@app.get("/api/hello")
def hello() -> dict:
    return {"message": "Hello from pyramid-web backend (Step 1 skeleton)"}


@app.get("/api/rooms")
async def list_rooms() -> dict:
    """All room summaries (debug/monitoring)."""
    return {"rooms": [room.summary() for room in manager.rooms()]}


@app.get("/api/rooms/{code}")
async def room_info(code: str) -> dict:
    room = manager.get(code.strip().upper())
    if room is None:
        raise HTTPException(status_code=404, detail="room not found")
    return room.summary()


@app.get("/api/modes")
def modes() -> dict:
    """The four selectable disciplines (Step 6) with their race targets."""
    return {
        "modes": [
            {
                "mode": mode,
                "name": meta["name"],
                "name_ru": meta["name_ru"],
                "target_score": meta["target"],
                "blurb": meta["blurb"],
            }
            for mode, meta in rules.MODES.items()
        ],
        "pockets": sorted(rules.POCKET_IDS),
        "default": rules.DEFAULT_MODE,
    }


# --- physics (Step 3) -----------------------------------------------------------


class BallIn(BaseModel):
    """An on-table ball position (pooltool coordinates: x across the width,
    y along the length; see app/physics.py)."""

    model_config = ConfigDict(extra="forbid")

    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


class ShotIn(BaseModel):
    """A cue stroke: direction (phi) + force (v0), optional spin."""

    model_config = ConfigDict(extra="forbid")

    balls: dict[str, BallIn] = Field(min_length=1, max_length=16)
    v0: float = Field(
        gt=physics.V0_RANGE[0],
        le=physics.V0_RANGE[1],
        allow_inf_nan=False,
        description="cue impact speed, m/s",
    )
    phi: float = Field(
        ge=physics.PHI_RANGE[0],
        lt=physics.PHI_RANGE[1],
        allow_inf_nan=False,
        description="strike direction, degrees CCW from +x (90 = towards foot rail)",
    )
    a: float = Field(
        default=physics.DEFAULT_A,
        ge=physics.SPIN_RANGE[0],
        le=physics.SPIN_RANGE[1],
        allow_inf_nan=False,
        description="side spin, -1 (right) .. +1 (left)",
    )
    b: float = Field(
        default=physics.DEFAULT_B,
        ge=physics.SPIN_RANGE[0],
        le=physics.SPIN_RANGE[1],
        allow_inf_nan=False,
        description="top/bottom spin, -1 (bottom) .. +1 (top)",
    )
    theta: float = Field(
        default=physics.DEFAULT_THETA,
        ge=physics.THETA_RANGE[0],
        le=physics.THETA_RANGE[1],
        allow_inf_nan=False,
        description="cue elevation (masse) angle, degrees",
    )
    keyframes: bool = Field(
        default=False,
        description="also return animation keyframes (Step 5 payload)",
    )


@app.get("/api/rack")
def rack(
    seed: int | None = Query(
        default=None,
        ge=0,
        le=2_147_483_647,
        description="optional RNG seed — same seed, same rack (deterministic)",
    ),
) -> dict:
    """The standard 15-ball Russian pyramid rack + cue ball.

    Without ``seed`` the rack is random (per the rules — placement within the
    pyramid is free). With ``seed`` it is bit-reproducible across the
    original pooltool repo, the vendored copy, and this API.
    """
    return {
        "balls": physics.russian_rack(seed),
        "table": physics.table_dimensions(),
        "ball": physics.ball_params(),
    }


@app.post("/api/shot")
def shot(body: ShotIn) -> dict:
    """Simulate one stroke: cue angle + force -> final ball coordinates.

    Stateless: the caller passes the full on-table ball state and receives
    the post-shot state. With ``"keyframes": true`` the response also
    carries the animation keyframes (Step 5); room-bound shots arrive over
    the ``/ws`` socket instead.
    """
    kwargs = {
        "v0": body.v0,
        "phi": body.phi,
        "a": body.a,
        "b": body.b,
        "theta": body.theta,
    }
    try:
        if body.keyframes:
            return physics.run_shot_keyframes(
                {ball_id: (pos.x, pos.y) for ball_id, pos in body.balls.items()},
                **kwargs,
            )
        return physics.run_shot(
            {ball_id: (pos.x, pos.y) for ball_id, pos in body.balls.items()},
            **kwargs,
        )
    except PhysicsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _recv(ws: WebSocket) -> dict | None:
    """Receive one JSON message.

    Returns None on client disconnect, or a marker dict when the payload is
    not a JSON object (the caller replies invalid_json and carries on).
    """
    try:
        msg = await ws.receive_json()
    except WebSocketDisconnect:
        return None
    except ValueError:
        return {"type": "__invalid_json__"}
    if not isinstance(msg, dict):
        return {"type": "__invalid_json__"}
    return msg


async def _reply(ws: WebSocket, payload: dict) -> None:
    try:
        await ws.send_json(payload)
    except Exception:
        # Deliberately broad (dead-socket error types vary by ASGI stack);
        # the socket's own handler cleans up membership.
        logger.debug("reply to dead socket failed", exc_info=True)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    session: Session | None = None
    try:
        # Handshake: the first message must create or join a room.
        while session is None:
            msg = await _recv(ws)
            if msg is None:
                return
            if msg.get("type") == "__invalid_json__":
                await _reply(
                    ws,
                    {
                        "type": "error",
                        "code": "invalid_json",
                        "message": "messages must be JSON objects",
                    },
                )
                continue
            try:
                if msg.get("type") == "create":
                    session = await manager.create_room(ws, msg)
                elif msg.get("type") == "join":
                    session = await manager.join_room(ws, msg)
                else:
                    raise LobbyError(
                        "invalid_message", "first message must be create or join"
                    )
            except LobbyError as exc:
                # Non-fatal: the client may retry (e.g. retype the room code)
                # on the same connection.
                await _reply(
                    ws,
                    {"type": "error", "code": exc.code, "message": exc.message},
                )

        # In-room loop: start_game / ping / ...
        while True:
            msg = await _recv(ws)
            if msg is None:
                return
            if msg.get("type") == "__invalid_json__":
                await _reply(
                    ws,
                    {
                        "type": "error",
                        "code": "invalid_json",
                        "message": "messages must be JSON objects",
                    },
                )
                continue
            try:
                await manager.handle(session, msg)
            except LobbyError as exc:
                await _reply(
                    ws,
                    {"type": "error", "code": exc.code, "message": exc.message},
                )
    finally:
        if session is not None:
            await manager.leave(session)
