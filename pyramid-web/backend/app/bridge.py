"""Terminal-state bridge for pyramid-web (Step 11 — client-side physics).

The architecture change: the shooter's browser simulates the stroke with its
own JavaScript physics (``frontend/physics.js``, vendored cannon-es) and the
server NEVER runs pooltool physics for gameplay anymore. When the balls come
to rest, the client sends one ``shot`` message carrying:

- ``final``   — resting positions of every on-table ball (pooltool meters),
- ``pocketed``— capture events ``[{ball, pocket, t}]`` in capture order,
- ``first_contact`` — the first object ball the cue ball touched ``{ball, t}``,
- ``cushions``— per-ball distinct cushion-segment ids contacted after the
  first contact (real pooltool segment ids, mirrored by the JS table),
- ``y_range`` — per-ball min/max y reached after the first contact (drives
  the rulesets' centre-line crossing checks),
- ``v0``/``phi``/``duration`` — informational stroke parameters.

This module validates that report and reconstructs the SYNTHETIC pooltool
``System`` the frozen rulesets judge (``Ruleset.process_and_advance``):

- every ball exists with its FINAL state (on-table or ``const.pocketed``),
- ``ball.history[0]`` is the PRE-SHOT state (the server's own authoritative
  pre-shot positions — never trusted from the client), plus post-first-contact
  y-extremes and the final entry so the centre-line / house / contact rules
  evaluate exactly as they did against simulated histories,
- ``system.events`` carries the compact synthetic event list
  (``ball_ball``, ``ball_linear_cushion`` / ``ball_circular_cushion``,
  ``ball_pocket``) with real table segment/pocket ids.

Anti-tamper note: final positions are geometry-validated (on-surface, no
overlaps, ball set exactly preserved) but a friendly game trusts the shooting
client's *outcomes*; server-side re-simulation as an anti-cheat measure is
deliberately out of scope (it would reintroduce the exact cost this step
removes).
"""

from __future__ import annotations

import time

import numpy as np

import pooltool as pt
import pooltool.constants as const
from pooltool.events.datatypes import Agent, AgentType, Event, EventType
from pooltool.objects.ball.datatypes import BallState

from . import physics

CUE = "cue"


class InvalidShot(ValueError):
    """A client shot report failed validation; surfaced as a lobby error."""


def _num(value: object, name: str, *, default: float | None = None) -> float:
    if value is None and default is not None:
        return float(default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidShot(f"'{name}' must be a number")
    return float(value)


def _xy(value: object, name: str) -> tuple[float, float]:
    if not isinstance(value, dict):
        raise InvalidShot(f"'{name}' must be an object with x and y")
    x = _num(value.get("x"), f"{name}.x")
    y = _num(value.get("y"), f"{name}.y")
    if not (np.isfinite(x) and np.isfinite(y)):
        raise InvalidShot(f"'{name}' must be finite")
    return x, y


def parse_report(msg: dict, live_ids: set[str]) -> dict:
    """Validate a client ``shot`` message into a strict report dict.

    ``live_ids`` is the authoritative pre-shot on-table ball id set (the
    server's own state). The report must account for EVERY live ball: each
    is either still on the table (``final``) or in ``pocketed`` — nothing
    more, nothing less.
    """
    if not isinstance(msg, dict):
        raise InvalidShot("shot must be a JSON object")

    final_raw = msg.get("final")
    if not isinstance(final_raw, dict) or not final_raw:
        raise InvalidShot("'final' must be a non-empty object of ball positions")
    final: dict[str, tuple[float, float]] = {}
    for ball_id, pos in final_raw.items():
        if not isinstance(ball_id, str) or ball_id not in live_ids:
            raise InvalidShot(f"unknown ball id in 'final': {ball_id!r}")
        final[ball_id] = _xy(pos, f"final.{ball_id}")

    pocketed_raw = msg.get("pocketed", [])
    if not isinstance(pocketed_raw, list):
        raise InvalidShot("'pocketed' must be a list")
    pocketed: list[dict] = []
    for entry in pocketed_raw:
        if not isinstance(entry, dict):
            raise InvalidShot("each 'pocketed' entry must be an object")
        ball_id = entry.get("ball")
        if not isinstance(ball_id, str) or ball_id not in live_ids:
            raise InvalidShot(f"unknown pocketed ball id: {ball_id!r}")
        pocket = entry.get("pocket")
        if not isinstance(pocket, str) or pocket not in physics.POCKET_IDS:
            raise InvalidShot(f"unknown pocket id: {pocket!r}")
        pocketed.append(
            {
                "ball": ball_id,
                "pocket": pocket,
                "t": max(0.0, _num(entry.get("t"), "pocketed.t", default=0.0)),
            }
        )
    if len({p["ball"] for p in pocketed}) != len(pocketed):
        raise InvalidShot("a ball was reported pocketed twice")

    accounted = set(final) | {p["ball"] for p in pocketed}
    if accounted != live_ids:
        missing = sorted(live_ids - accounted)
        extra = sorted(accounted - live_ids)
        raise InvalidShot(
            "shot report must account for every ball "
            f"(missing: {missing or '—'}, unknown: {extra or '—'})"
        )
    if CUE in {p["ball"] for p in pocketed} and CUE in final:
        raise InvalidShot("the cue ball cannot be both pocketed and on the table")

    duration = max(0.0, _num(msg.get("duration"), "duration", default=0.0))

    first_contact_raw = msg.get("first_contact")
    first_contact: dict | None = None
    if first_contact_raw is not None:
        if not isinstance(first_contact_raw, dict):
            raise InvalidShot("'first_contact' must be an object")
        ball_id = first_contact_raw.get("ball")
        if not isinstance(ball_id, str) or ball_id not in live_ids or ball_id == CUE:
            raise InvalidShot(f"invalid first_contact ball: {ball_id!r}")
        first_contact = {
            "ball": ball_id,
            "t": max(0.0, _num(first_contact_raw.get("t"), "first_contact.t", default=0.0)),
        }
    if any(p["ball"] != CUE for p in pocketed) and first_contact is None:
        # an object ball cannot be pocketed without the cue ball touching a
        # ball first — treat such a report as malformed (a cue-only pot with
        # no object contact is legitimate: NO_CONTACT foul territory)
        raise InvalidShot("'first_contact' is required when an object ball was pocketed")

    cushions_raw = msg.get("cushions", {})
    if not isinstance(cushions_raw, dict):
        raise InvalidShot("'cushions' must be an object")
    known_segments = physics.CUSHION_SEGMENT_IDS
    cushions: dict[str, list[str]] = {}
    for ball_id, segs in cushions_raw.items():
        if not isinstance(ball_id, str) or ball_id not in live_ids:
            raise InvalidShot(f"unknown ball id in 'cushions': {ball_id!r}")
        if not isinstance(segs, list):
            raise InvalidShot(f"'cushions.{ball_id}' must be a list")
        cleaned: list[str] = []
        for seg in segs:
            if not isinstance(seg, str) or seg not in known_segments:
                raise InvalidShot(f"unknown cushion segment id: {seg!r}")
            if seg not in cleaned:
                cleaned.append(seg)
        if cleaned:
            cushions[ball_id] = cleaned

    y_range_raw = msg.get("y_range", {})
    if not isinstance(y_range_raw, dict):
        raise InvalidShot("'y_range' must be an object")
    y_range: dict[str, tuple[float, float]] = {}
    for ball_id, extrema in y_range_raw.items():
        if not isinstance(ball_id, str) or ball_id not in live_ids:
            raise InvalidShot(f"unknown ball id in 'y_range': {ball_id!r}")
        if not isinstance(extrema, dict):
            raise InvalidShot(f"'y_range.{ball_id}' must be an object")
        lo = _num(extrema.get("min"), f"y_range.{ball_id}.min")
        hi = _num(extrema.get("max"), f"y_range.{ball_id}.max")
        if lo > hi:
            raise InvalidShot(f"'y_range.{ball_id}' min must not exceed max")
        y_range[ball_id] = (lo, hi)

    _validate_positions(final, require_cue=CUE in final)

    return {
        "final": final,
        "pocketed": pocketed,
        "first_contact": first_contact,
        "cushions": cushions,
        "y_range": y_range,
        "v0": _num(msg.get("v0"), "v0", default=0.0),
        "phi": _num(msg.get("phi"), "phi", default=0.0),
        "duration": duration,
    }


def _validate_positions(balls: dict[str, tuple[float, float]], *, require_cue: bool) -> None:
    """Geometry validation (mirrors app/physics.py; cue-optional variant)."""
    if require_cue and CUE not in balls:
        raise InvalidShot("a ball with id 'cue' (the cue ball) is required")
    if not 1 <= len(balls) <= 16:
        raise InvalidShot("between 1 and 16 balls are required")
    margin = physics.SURFACE_MARGIN
    for ball_id, (x, y) in balls.items():
        if not -margin <= x <= physics.TABLE_W + margin:
            raise InvalidShot(
                f"ball '{ball_id}' x={x:.4f} is not on the table"
            )
        if not -margin <= y <= physics.TABLE_L + margin:
            raise InvalidShot(
                f"ball '{ball_id}' y={y:.4f} is not on the table"
            )
    ids = list(balls)
    for i, id_a in enumerate(ids):
        for id_b in ids[i + 1 :]:
            ax, ay = balls[id_a]
            bx, by = balls[id_b]
            if ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 < physics.MIN_SEPARATION:
                raise InvalidShot(
                    f"balls '{id_a}' and '{id_b}' overlap in the reported state"
                )


# --- synthetic System construction ------------------------------------------------


def _add_history(ball: pt.Ball, *, final_xy: tuple[float, float] | None, final_s: int,
                 first_contact_t: float | None, duration: float,
                 y_extrema: tuple[float, float] | None) -> None:
    """history[0] is the pre-shot state (already there from creation); append
    the post-first-contact y extrema and the final state so the rulesets'
    history walks (centre-line crossing, house contact, ``at_start`` reads)
    see exactly what a simulated history would have shown."""
    t0 = first_contact_t
    if t0 is not None and y_extrema is not None and duration > 0.01:
        span = duration - t0
        if span > 1e-6:
            lo, hi = y_extrema
            for frac, y in ((0.25, lo), (0.5, hi)):
                t = t0 + frac * span
                state = ball.history[0]
                ball.history.add(
                    BallState(
                        rvw=np.array([[state.rvw[0, 0], y, ball.params.R],
                                      [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]),
                        s=state.s,
                        t=t,
                    )
                )
    if final_xy is not None:
        ball.history.add(
            BallState(
                rvw=np.array(
                    [[final_xy[0], final_xy[1], ball.params.R],
                     [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
                ),
                s=final_s,
                t=max(duration, ball.history.ts[-1] if len(ball.history.ts) else 0.0),
            )
        )


def build_system(report: dict, pre_balls: dict[str, dict[str, float]]) -> pt.System:
    """Synthetic pooltool System from a validated report + the server's own
    pre-shot ball state."""
    table = physics.fresh_table()
    final = report["final"]
    pocketed = {p["ball"]: p for p in report["pocketed"]}
    first_contact_t = (
        report["first_contact"]["t"] if report["first_contact"] else None
    )

    balls: dict[str, pt.Ball] = {}
    for ball_id, pre in pre_balls.items():
        pre_xy = (float(pre["x"]), float(pre["y"]))
        ball = physics.make_ball(ball_id, pre_xy)
        # seed history[0] = the PRE-SHOT state (the server's own authoritative
        # position) — the rulesets read it for house/at-start checks
        ball.history.add(
            BallState(rvw=ball.state.rvw.copy(), s=const.stationary, t=0.0)
        )
        if ball_id in final:
            x, y = final[ball_id]
            ball.state.rvw[0, 0] = x
            ball.state.rvw[0, 1] = y
            extrema = report["y_range"].get(ball_id)
            _add_history(
                ball,
                final_xy=(x, y),
                final_s=const.stationary,
                first_contact_t=first_contact_t,
                duration=report["duration"],
                y_extrema=extrema,
            )
        else:
            cap = pocketed[ball_id]
            pocket = table.pockets[cap["pocket"]]
            ball.state.rvw[0, 0] = float(pocket.center[0])
            ball.state.rvw[0, 1] = float(pocket.center[1])
            ball.state.rvw[0, 2] = -float(pocket.depth)
            ball.state.s = const.pocketed
            _add_history(
                ball,
                final_xy=(float(pocket.center[0]), float(pocket.center[1])),
                final_s=const.pocketed,
                first_contact_t=first_contact_t,
                duration=report["duration"],
                y_extrema=report["y_range"].get(ball_id),
            )
        balls[ball_id] = ball

    events = _synth_events(report, table)
    system = pt.System(cue=pt.Cue(), table=table, balls=balls)
    system.events = events
    return system


def _synth_events(report: dict, table: pt.Table) -> list[Event]:
    """Compact chronological event list the rulesets' single-pass scan reads."""
    events: list[Event] = []
    fc = report["first_contact"]
    duration = report["duration"]
    if fc is not None:
        t0 = min(fc["t"], duration)
        events.append(
            Event(
                event_type=EventType.BALL_BALL,
                agents=(Agent(CUE, AgentType.BALL), Agent(fc["ball"], AgentType.BALL)),
                time=t0,
            )
        )
        linear_ids = set(table.cushion_segments.linear)
        entries: list[tuple[float, str, str, bool]] = []
        for ball_id in sorted(report["cushions"]):
            for seg_id in report["cushions"][ball_id]:
                entries.append((t0, ball_id, seg_id, seg_id in linear_ids))
        # deterministic strictly-increasing times after first contact
        for k, (_, ball_id, seg_id, is_linear) in enumerate(entries):
            t = t0 + (k + 1) * 1e-3
            events.append(
                Event(
                    event_type=EventType.BALL_LINEAR_CUSHION
                    if is_linear
                    else EventType.BALL_CIRCULAR_CUSHION,
                    agents=(
                        Agent(ball_id, AgentType.BALL),
                        Agent(
                            seg_id,
                            AgentType.LINEAR_CUSHION_SEGMENT
                            if is_linear
                            else AgentType.CIRCULAR_CUSHION_SEGMENT,
                        ),
                    ),
                    time=t,
                )
            )
    for cap in sorted(report["pocketed"], key=lambda p: (p["t"], p["ball"])):
        events.append(
            Event(
                event_type=EventType.BALL_POCKET,
                agents=(
                    Agent(cap["ball"], AgentType.BALL),
                    Agent(cap["pocket"], AgentType.POCKET),
                ),
                time=min(cap["t"], duration),
            )
        )
    events.sort(key=lambda ev: ev.time)
    return events


# --- outcomes ------------------------------------------------------------------------


def apply_ruleset(report: dict, pre_balls: dict[str, dict[str, float]],
                  game: object) -> dict:
    """Judge the terminal report with the room's vendored ruleset.

    Returns the outcome dict the lobby broadcasts; the ruleset instance is
    advanced in place (scores / turn / respots / removals).
    """
    started = time.perf_counter()
    system = build_system(report, pre_balls)
    try:
        game.process_and_advance(system)
    except Exception as exc:  # ruleset machinery (respot line etc.)
        raise InvalidShot(f"ruleset rejected the shot: {exc}") from exc

    final_ids = set(report["final"])
    pocketed_ids = [p["ball"] for p in report["pocketed"]]
    post_on_table = {
        ball_id
        for ball_id, ball in system.balls.items()
        if ball.state.s in const.on_table
    }
    info = game.shot_info
    return {
        # authoritative on-table state after respots / removals
        "balls": {
            ball_id: {
                "x": float(system.balls[ball_id].state.rvw[0, 0]),
                "y": float(system.balls[ball_id].state.rvw[0, 1]),
            }
            for ball_id in sorted(post_on_table, key=physics.ball_id_key)
        },
        "pocketed": pocketed_ids,
        # potted during the shot but returned to the table by the ruleset
        "respotted": sorted(set(pocketed_ids) & post_on_table,
                            key=physics.ball_id_key),
        # taken off the table by the ruleset («штрафной шар» / shelf ball)
        "removed": sorted(final_ids - post_on_table, key=physics.ball_id_key),
        "judge_ms": round((time.perf_counter() - started) * 1000, 2),
        "legal": bool(info.legal),
        "reason": str(info.reason),
    }
