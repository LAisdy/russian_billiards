"""pooltool physics bridge for pyramid-web (Step 3).

This module is one of the two places the backend touches the vendored pooltool
package (``backend/pooltool/`` — see its VENDORED.md; the other is
``app/rules.py``). It never modifies physics behavior: it constructs pooltool
objects and calls the public API (``get_rack``, ``simulate``).

Coordinate convention (pooltool's, exposed verbatim by the API):
  - x spans the table WIDTH,  0 .. 1.80 m  (x = 0 and x = w are cushion noses)
  - y spans the table LENGTH, 0 .. 3.70 m  (y = 0 is the head rail — where the
    cue ball breaks from — y = l is the foot rail where the pyramid is racked)

Seeded-rack determinism note: layouts.py assigns ball IDs with
``random.choice(list(<set of str>))`` — set iteration order depends on string
hash randomization, so cross-process reproducibility (same seed -> same rack,
e.g. server restart, or the original-repo comparison test) requires running
with ``PYTHONHASHSEED=0`` (set in docker/backend.Dockerfile and in the dev
recipes in README.md).

All four Russian Pyramid disciplines share identical equipment, so this module
always uses ``GameType.RUSSIAN_PYRAMID_FREE`` equipment. Rules enforcement is
mode-driven (Step 6): pass the vendored ``Ruleset`` instance to
``run_shot_keyframes`` and it is advanced by ``process_and_advance``.
"""

from __future__ import annotations

import json
import random
import threading
import time

import attrs
import numpy as np

import pooltool as pt
import pooltool.constants as const
from pooltool.error import SimulateError
from pooltool.events.datatypes import AgentType, EventType
from pooltool.evolution.engine import SimulationEngine
from pooltool.game.datatypes import GameType
from pooltool.objects.table.collection import TABLE_SPECS, TableName
from pooltool.objects.table.datatypes import Table
from pooltool.physics.resolve.resolver import Resolver
from pooltool.ruleset.datatypes import Ruleset

GAME_TYPE = GameType.RUSSIAN_PYRAMID_FREE

_TABLE_SPECS = TABLE_SPECS[TableName.RUSSIAN_PYRAMID_GENERIC]
_BALL_PARAMS = pt.BallParams.prebuilt(pt.PrebuiltBallParams.RUSSIAN_PYRAMID_GENERIC)
_BALL_PARAMS_KWARGS = attrs.asdict(_BALL_PARAMS)

#: The 3D engine the desktop app enables for play (benchmark: ~75-190 ms per
#: full Russian break, steady state). One immutable bundle, shared.
ENGINE_3D = SimulationEngine(is_3d=True, resolver=Resolver.default(is_3d=True))

#: Table prototype. ``Table.copy()`` per request — pockets accumulate
#: ``contains`` during simulation, so systems must never share a table.
_TABLE_PROTO = Table.from_table_specs(_TABLE_SPECS)

TABLE_L = float(_TABLE_PROTO.l)
TABLE_W = float(_TABLE_PROTO.w)
BALL_R = float(_BALL_PARAMS.R)
MIN_SEPARATION = 2 * BALL_R - 1e-4  # rack balls sit at ~2R apart (spacing 1e-3)

#: How far beyond the cushion noses an on-table ball may rest. Non-zero
#: because a ball can sit in a pocket mouth, against the jaws — physics-
#: produced states (Step 5+) must be acceptable API input. Pocket wells reach
#: ~0.1 m past the playing surface; 0.15 m rejects clearly-garbage input.
SURFACE_MARGIN = 0.15

#: api validation ranges (v0 mirrors the library cue; phi is degrees CCW from
#: the +x axis in the pooltool XY plane).
V0_RANGE = (0.05, 10.0)
PHI_RANGE = (0.0, 360.0)
SPIN_RANGE = (-1.0, 1.0)
THETA_RANGE = (0.0, 85.0)
#: library ``Cue`` defaults, used when the client omits spin parameters.
DEFAULT_A = 0.0
DEFAULT_B = 0.25
DEFAULT_THETA = 0.0

#: Motion-state names counting as "on the table" (Step 10: the practice-mode
#: post-processing in app/lobby.py filters the raw simulation output on these
#: plain strings instead of touching the vendored constants directly).
ON_TABLE_STATES = frozenset(const.state_dict[s] for s in const.on_table)

# layouts.get_rack() draws from the *global* `random` / `numpy.random` pools
# (the library's public entry point does not forward a seed), so rack
# generation is serialized and explicitly seeded.
_RACK_LOCK = threading.Lock()

_warmup_state = {"started": False, "ready": False}


class PhysicsError(ValueError):
    """Invalid shot/rack input; surfaced by the API as HTTP 422."""


def warm_ready() -> bool:
    return _warmup_state["ready"]


def table_dimensions() -> dict:
    """Table geometry echo (spec values, pocket centers from the physics)."""
    return {
        "length": TABLE_L,
        "width": TABLE_W,
        "cushion_width": float(_TABLE_SPECS.cushion_width),
        "pockets": {
            pid: {
                "x": float(p.a),
                "y": float(p.b),
                "radius": float(p.radius),
                "depth": float(p.depth),
            }
            for pid, p in _TABLE_PROTO.pockets.items()
        },
    }


def ball_params() -> dict:
    return {
        "radius": BALL_R,
        "diameter_mm": round(2 * BALL_R * 1000, 1),
        "mass": float(_BALL_PARAMS.m),
    }


def russian_rack(seed: int | None = None) -> dict[str, dict]:
    """Standard 15-ball Russian pyramid rack + cue ball (seeded => identical
    racks across the original repo, the vendored copy, and the HTTP API)."""
    with _RACK_LOCK:
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)
        balls = pt.get_rack(
            GAME_TYPE,
            table=_TABLE_PROTO.copy(),
            ball_params=_BALL_PARAMS,
            ballset=None,
            spacing_factor=1e-3,
        )
    return {
        ball_id: {"x": float(ball.state.rvw[0, 0]), "y": float(ball.state.rvw[0, 1])}
        for ball_id, ball in balls.items()
    }


def _validate_balls(balls: dict[str, tuple[float, float]]) -> None:
    if "cue" not in balls:
        raise PhysicsError("a ball with id 'cue' (the cue ball) is required")
    if not 1 <= len(balls) <= 16:
        raise PhysicsError("between 1 and 16 balls are required")
    for ball_id, (x, y) in balls.items():
        if not -SURFACE_MARGIN <= x <= TABLE_W + SURFACE_MARGIN:
            raise PhysicsError(
                f"ball '{ball_id}' x={x:.4f} is not on the table "
                f"(valid: {-SURFACE_MARGIN:.2f}..{TABLE_W + SURFACE_MARGIN:.2f})"
            )
        if not -SURFACE_MARGIN <= y <= TABLE_L + SURFACE_MARGIN:
            raise PhysicsError(
                f"ball '{ball_id}' y={y:.4f} is not on the table "
                f"(valid: {-SURFACE_MARGIN:.2f}..{TABLE_L + SURFACE_MARGIN:.2f})"
            )
    ids = list(balls)
    for i, id_a in enumerate(ids):
        for id_b in ids[i + 1 :]:
            ax, ay = balls[id_a]
            bx, by = balls[id_b]
            if ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 < MIN_SEPARATION:
                raise PhysicsError(
                    f"balls '{id_a}' and '{id_b}' overlap "
                    f"(minimum separation is {2 * BALL_R:.4f} m)"
                )


def _build_system(
    balls: dict[str, tuple[float, float]],
    *,
    v0: float,
    phi: float,
    a: float,
    b: float,
    theta: float,
) -> pt.System:
    cue = pt.Cue.from_game_type(GAME_TYPE)
    cue.set_state(V0=v0, phi=phi, a=a, b=b, theta=theta)
    return pt.System(
        cue=cue,
        table=_TABLE_PROTO.copy(),
        balls={
            ball_id: pt.Ball.create(
                ball_id,
                xy=(x, y),
                ballset=None,
                **_BALL_PARAMS_KWARGS,
            )
            for ball_id, (x, y) in balls.items()
        },
    )


def run_shot(
    balls: dict[str, tuple[float, float]],
    *,
    v0: float,
    phi: float,
    a: float = DEFAULT_A,
    b: float = DEFAULT_B,
    theta: float = DEFAULT_THETA,
) -> dict:
    """Simulate one cue stroke and return the final table state.

    Args:
        balls: on-table ball positions, pooltool coordinates (see module
            docstring). Pocketed balls must NOT be included.
        v0: cue impact speed (m/s).
        phi: strike direction, degrees counterclockwise from the +x axis in
            the pooltool XY plane (90 = straight towards the foot rail).
        a: side spin in [-1, 1] (-1 rightmost, +1 leftmost).
        b: top/bottom spin in [-1, 1] (-1 bottom, +1 top).
        theta: cue elevation (masse) angle in degrees, 0 = level.
    """
    _validate_balls(balls)

    system = _build_system(balls, v0=v0, phi=phi, a=a, b=b, theta=theta)

    start = time.perf_counter()
    try:
        simulated = pt.simulate(system, engine=ENGINE_3D)
    except SimulateError as exc:
        # e.g. balls overlapping a cushion or otherwise unresolvable input
        raise PhysicsError(f"physics rejected the shot: {exc}") from exc
    sim_ms = (time.perf_counter() - start) * 1000

    final = {
        ball_id: {
            "x": float(ball.state.rvw[0, 0]),
            "y": float(ball.state.rvw[0, 1]),
            "state": const.state_dict[ball.state.s],
        }
        for ball_id, ball in simulated.balls.items()
    }
    pocketed = sorted(
        ball_id
        for ball_id, ball in simulated.balls.items()
        if ball.state.s == const.pocketed
    )
    return {
        "balls": final,
        "pocketed": pocketed,
        "duration_s": float(simulated.t),
        "events": len(simulated.events),
        "sim_ms": round(sim_ms, 2),
    }


# --- keyframes (Step 5): event-based trajectory -> animation keyframes ---------

#: keyframe grid spacing (s) and hard frame cap. The client interpolates
#: linearly between keyframes; 40 ms keeps the discretization error of the
#: fastest sliding phase far below one ball radius while a full break stays
#: at ~150 frames (16 balls x 2 floats each) instead of every physics tick.
KF_DT = 0.04
KF_MAX_FRAMES = 900


def _prune_stationary_frames(frames: list[list]) -> tuple[list[list], int]:
    """Drop frames byte-identical to the previously kept one (Step 7).

    Any frame whose full row equals the previously kept row carries zero
    animation information (every ball frozen to the 0.1 mm grid) and is
    dropped; frame 0 and the FINAL frame (t == duration_ms, the client's
    authoritative snap target) always survive. Collision-event frames are
    kept by nature — a collision implies motion, so their rows differ — and
    sub-ms event clusters collapse within the clients' ±1 ms event-time
    tolerance. Spares wire bytes whenever the engine yields frozen frames
    (e.g. trajectory thinning on marathon shots); measured 0 on the six
    representative Step 7 profile shots (pooltool's event-based simulation
    already ends at quiescence) — kept as a correctness guard.

    Returns ``(kept_frames, pruned_count)``.
    """
    kept: list[list] = []
    last_idx = len(frames) - 1
    for i, row in enumerate(frames):
        if i == 0 or i == last_idx or row != kept[-1]:
            kept.append(row)
    return kept, len(frames) - len(kept)


def _ball_id_key(ball_id: str) -> tuple[int, str]:
    """Sort key: object balls in numeric order, non-numeric (cue) last."""
    return (int(ball_id) if ball_id.isdigit() else 10**9, ball_id)


def _ball_id_order(balls: dict[str, tuple[float, float]]) -> list[str]:
    """Stable keyframe column order: object balls 1..15 (numeric), cue last."""
    others = [b for b in balls if b != "cue"]
    return sorted(others, key=_ball_id_key) + ["cue"]


def run_shot_keyframes(
    balls: dict[str, tuple[float, float]],
    *,
    v0: float,
    phi: float,
    a: float = DEFAULT_A,
    b: float = DEFAULT_B,
    theta: float = DEFAULT_THETA,
    dt: float = KF_DT,
    game: Ruleset | None = None,
) -> dict:
    """Simulate one stroke and return the final state plus animation keyframes.

    The trajectory is NOT streamed per physics tick: keyframes are sampled on
    a uniform ``dt`` grid plus every event time (ball-ball, cushion, pocket,
    motion transitions), so collisions are hit exactly and the client's linear
    interpolation between keyframes stays visually faithful. Each keyframe is
    the EXACT physics state (via ``interpolate_ball_states``, which evolves
    from the preceding event state with the real motion model), not a
    linearization.

    Keyframe payload::

        {
          "ids": ["1", "10", ..., "cue"],        # column order of frames
          "dt_ms": 40,                           # grid spacing (info only)
          "duration_ms": 3521,                   # last frame time
          "frames": [[t_ms, x1, y1, x2, y2, ...], ...],
          "events": [{"t_ms": 812, "type": "ball_ball", "balls": ["1","cue"]}],
        }

    Stationary-tail pruning (Step 7): frames byte-identical to the
    previously kept one are dropped (frame 0 and the final frame always
    survive; collision instants survive by nature — a collision implies
    motion). Measured 0 frames saved on the representative profile shots
    (the event-based simulation already ends at quiescence); it guards
    marathon-shot thinning and future engine changes.

    Pocketed balls keep their post-pocket resting spot in the frames (the
    client hides them when the animation completes).

    The result also carries ``kf_stats`` (Step 7 traffic profiling):
    ``{frames, events, bytes, pruned}`` — the keyframe JSON size as it is
    serialized onto the wire (default ``json.dumps`` separators).

    With ``game`` (Step 6) the vendored ruleset drives the post-shot world:
    ``game.process_and_advance(system)`` judges the stroke, updates the
    score/turn, and respots/removes balls («неправильно забитые», jumped
    balls, «штрафной шар», scratched cue ball). The returned ``balls`` are
    then the AUTHORITATIVE post-ruleset on-table state (plain ``{x, y}``,
    pocketed balls excluded — respotted ones included at their new spots),
    plus a ``rules`` block (legal/reason/turn_over/game_over/winner/score)
    and ``respotted``/``removed`` id lists for UI messaging. Without
    ``game`` the response keeps the raw simulation payload (REST endpoint).
    """
    _validate_balls(balls)
    system = _build_system(balls, v0=v0, phi=phi, a=a, b=b, theta=theta)

    start = time.perf_counter()
    try:
        simulated = pt.simulate(system, engine=ENGINE_3D)
    except SimulateError as exc:
        raise PhysicsError(f"physics rejected the shot: {exc}") from exc
    sim_ms = (time.perf_counter() - start) * 1000

    duration_s = float(simulated.t)
    duration_ms = round(duration_s * 1000)
    ids = _ball_id_order(balls)

    # sample times: uniform grid + event times (exact collision instants).
    # Quantize to whole milliseconds BEFORE interpolating: the wire format
    # carries ms integers, and two sub-ms event times would otherwise
    # collapse into duplicate frames (breaking the client's binary search).
    raw_ms = [i * dt * 1000 for i in range(int(duration_s / dt) + 1)]
    raw_ms.extend(
        float(ev.time) * 1000
        for ev in simulated.events
        if 0.0 < float(ev.time) < duration_s
    )
    raw_ms.append(duration_ms)
    times_ms = sorted({min(round(t), duration_ms) for t in raw_ms})
    if len(times_ms) > KF_MAX_FRAMES:  # pathological marathon shot: thin it out
        stride = len(times_ms) / KF_MAX_FRAMES
        thinned = [times_ms[int(i * stride)] for i in range(KF_MAX_FRAMES)]
        if thinned[-1] != duration_ms:
            thinned[-1] = duration_ms
        times_ms = sorted(set(thinned))
    times = [t / 1000.0 for t in times_ms]

    per_ball: dict[str, list[tuple[float, float]]] = {}
    for ball_id in ids:
        states = pt.interpolate_ball_states(
            simulated.balls[ball_id], times, extrapolate=True
        )
        per_ball[ball_id] = [(float(s.rvw[0, 0]), float(s.rvw[0, 1])) for s in states]

    frames = []
    for i, t_ms in enumerate(times_ms):
        row = [t_ms]
        for ball_id in ids:
            x, y = per_ball[ball_id][i]
            row.append(round(x, 4))
            row.append(round(y, 4))
        frames.append(row)

    events = [
        {
            "t_ms": round(ev.time * 1000),
            "type": str(ev.event_type.value)
            if hasattr(ev.event_type, "value")
            else str(ev.event_type),
            "balls": [
                agent.id for agent in ev.agents if agent.agent_type == AgentType.BALL
            ],
        }
        for ev in simulated.events
        if ev.event_type != EventType.NONE
    ]

    pocketed = sorted(
        ball_id
        for ball_id, ball in simulated.balls.items()
        if ball.state.s == const.pocketed
    )

    frames, pruned = _prune_stationary_frames(frames)

    keyframes = {
        "ids": ids,
        "dt_ms": round(dt * 1000),
        "duration_ms": round(duration_s * 1000),
        "frames": frames,
        "events": events,
        # Step 10 (A4): the client's finishAnimation hides these ids when the
        # animation completes — without this key the field defaulted to []
        # and potted ball meshes stayed visible at the pocket mouth.
        "pocketed": pocketed,
    }
    kf_stats = {
        "frames": len(frames),
        "events": len(events),
        "bytes": len(json.dumps(keyframes)),
        "pruned": pruned,
    }

    if game is None:
        final = {
            ball_id: {
                "x": float(ball.state.rvw[0, 0]),
                "y": float(ball.state.rvw[0, 1]),
                "state": const.state_dict[ball.state.s],
            }
            for ball_id, ball in simulated.balls.items()
        }
        return {
            "balls": final,
            "pocketed": pocketed,
            "duration_s": duration_s,
            "sim_ms": round(sim_ms, 2),
            "keyframes": keyframes,
            "kf_stats": kf_stats,
        }

    # --- ruleset mode (Step 6) -------------------------------------------
    # On-table ids BEFORE the ruleset runs (penalty-ball removal diffing).
    sim_on_table = {
        ball_id
        for ball_id, ball in simulated.balls.items()
        if ball.state.s in const.on_table
    }
    try:
        game.process_and_advance(simulated)
    except Exception as exc:  # ruleset machinery (respot line etc.)
        raise PhysicsError(f"ruleset rejected the shot: {exc}") from exc

    post_on_table = {
        ball_id
        for ball_id, ball in simulated.balls.items()
        if ball.state.s in const.on_table
    }
    info = game.shot_info
    return {
        # authoritative on-table state after respots / removals
        "balls": {
            ball_id: {
                "x": float(simulated.balls[ball_id].state.rvw[0, 0]),
                "y": float(simulated.balls[ball_id].state.rvw[0, 1]),
            }
            for ball_id in sorted(post_on_table, key=_ball_id_key)
        },
        "pocketed": pocketed,
        # potted during the shot but returned to the table by the ruleset
        "respotted": sorted(set(pocketed) & post_on_table, key=_ball_id_key),
        # taken off the table by the ruleset (штрафной шар / shelf ball)
        "removed": sorted(sim_on_table - post_on_table, key=_ball_id_key),
        "duration_s": duration_s,
        "sim_ms": round(sim_ms, 2),
        "keyframes": keyframes,
        "kf_stats": kf_stats,
        "rules": {
            "legal": bool(info.legal),
            "reason": str(info.reason),
            "turn_over": bool(info.turn_over),
            "game_over": bool(info.game_over),
            "winner": info.winner.name if info.winner is not None else None,
            "score": {player_id: int(pts) for player_id, pts in info.score.items()},
        },
    }


def respot_cue_position(balls: dict[str, tuple[float, float]]) -> tuple[float, float]:
    """Legacy cue-ball respot (pre-rules placeholder; kept for compat tests).

    Superseded in Step 6 by the vendored rulesets' respot machinery
    (``RussianXxxPyramid.respot_balls`` via ``run_shot_keyframes(game=...)``):
    a scratched cue ball now goes to the deterministic default house position
    with a ball-in-hand grant, and a legal «свояк» to the spotting line.

    Places the cue ball on the head spot (0.25 L) and nudges it towards the
    head rail in ball-diameter steps until it neither overlaps another ball
    nor leaves the validated surface margin.
    """
    x = TABLE_W / 2
    y = 0.25 * TABLE_L
    step = 2 * BALL_R + 0.005
    for _ in range(60):
        overlap = any(
            bid != "cue" and ((x - bx) ** 2 + (y - by) ** 2) ** 0.5 < MIN_SEPARATION
            for bid, (bx, by) in balls.items()
        )
        if not overlap and y >= -SURFACE_MARGIN:
            return x, y
        y -= step
    raise PhysicsError("no free position to respot the cue ball")


def warmup() -> None:
    """Compile the numba kernels (2D example + full 3D Russian break + the
    keyframe interpolation path) in a background thread so the first real
    request is not billed seconds of JIT.

    Mirrors the desktop app's startup strategy (see pooltool PROGRESS.md:
    "full-rack JIT warmup"): System.example() covers the 2D/shared kernels,
    then a seeded 3D break compiles every hot 3D path with a realistic event
    mix, and a keyframe-format stroke compiles the interpolation machinery
    the wire payload uses (Step 10: the web game's shot path must never pay
    JIT inside a request). ~25-30 s total; steady-state shots are 75-190 ms.
    """
    if _warmup_state["started"]:
        return
    _warmup_state["started"] = True
    start = time.perf_counter()
    try:
        pt.simulate(pt.System.example())  # shared + 2D kernels
        rack = russian_rack(seed=0)
        shot = run_shot(
            {bid: (pos["x"], pos["y"]) for bid, pos in rack.items()},
            v0=3.0,
            phi=90.0,
        )
        # Step 10 (A2): compile the keyframe/interpolation path too — it is
        # the ONLY shot format the web game uses, and before this warmup it
        # still JIT-compiled inside the first real request.
        kf_shot = run_shot_keyframes(
            {bid: (pos["x"], pos["y"]) for bid, pos in rack.items()},
            v0=2.0,
            phi=60.0,
        )
        _warmup_state["ready"] = True
        print(
            f"[physics] warmup complete in {time.perf_counter() - start:.1f}s "
            f"({shot['events']} events, pocketed={shot['pocketed']}; "
            f"keyframe path: {len(kf_shot['keyframes']['frames'])} frames)",
            flush=True,
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception("physics warmup failed")
