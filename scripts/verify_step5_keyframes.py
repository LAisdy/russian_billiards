#!/usr/bin/env python3
"""Step 5 headless verification: trajectory keyframes from the physics bridge.

Run:
    PYTHONHASHSEED=0 backend/.venv/bin/python scripts/verify_step5_keyframes.py

Validates (against a seeded full break):
  1. frame times are strictly increasing, start at 0, end at duration_ms
  2. frame 0 == input rack positions; last frame == run_shot final positions
  3. every event time appears as a keyframe time (collision instants included)
  4. per-frame displacement implies a plausible speed (no teleporting balls)
  5. pocketed balls rest near their pocket centers and are excluded from the
     on-table final state
  6. ids column order is stable and covers every ball
  7. REST keyframes mode returns the same structure
  8. respot_cue_position finds a free spot next to an occupied head spot
  9. Step 7 stationary-tail pruning: no two consecutive rows are identical
     (frame 0, the final frame and event-time frames still all present)
"""

from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, "/home/z/my-project/pyramid-web/backend")

import itertools

from app import physics

passed = 0
failed: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global passed
    if cond:
        passed += 1
        print(f"  ok  {name}")
    else:
        failed.append(name)
        print(f"FAIL  {name}  {extra}")


def main() -> int:
    rack = physics.russian_rack(seed=7)
    balls_in = {bid: (pos["x"], pos["y"]) for bid, pos in rack.items()}
    check("rack has 16 balls incl. cue", len(balls_in) == 16 and "cue" in balls_in)

    t0 = time.perf_counter()
    res = physics.run_shot_keyframes(
        balls_in, v0=3.0, phi=90.0, b=0.25
    )  # the warmup-style break
    wall_ms = (time.perf_counter() - t0) * 1000
    kf = res["keyframes"]
    print(
        f"  ..  break: {res['duration_s']:.2f}s, {len(kf['frames'])} keyframes, "
        f"{len(kf['events'])} events, sim {res['sim_ms']:.0f} ms, "
        f"total {wall_ms:.0f} ms, payload {len(json.dumps(kf)) / 1024:.1f} KiB"
    )

    ids = kf["ids"]
    frames = kf["frames"]
    times = [f[0] for f in frames]

    check(
        "ids cover every ball, cue last", set(ids) == set(balls_in) and ids[-1] == "cue"
    )
    check(
        "frame times strictly increasing",
        all(b > a for a, b in itertools.pairwise(times)),
    )
    check("first frame at t=0", times[0] == 0)
    check(
        "last frame at duration",
        times[-1] == round(res["duration_s"] * 1000),
        f"{times[-1]} vs {res['duration_s']}",
    )
    check("frames cover the anchors (>= 2: t0 + duration)", len(frames) >= 2)
    check(
        "stationary frames pruned (interior rows distinct; only the mandated "
        "duration anchor may repeat, Step 7)",
        all(frames[i] != frames[i - 1] for i in range(1, len(frames) - 1)),
    )

    col = {bid: i for i, bid in enumerate(ids)}

    def pos(frame: list, bid: str) -> tuple[float, float]:
        o = 1 + 2 * col[bid]
        return frame[o], frame[o + 1]

    def near(a: tuple[float, float], b: tuple[float, float], tol: float) -> bool:
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 <= tol

    first = frames[0]
    check(
        "frame 0 == rack positions (<=0.2 mm)",
        all(
            near(pos(first, bid), (balls_in[bid][0], balls_in[bid][1]), 2e-4)
            for bid in ids
        ),
    )

    plain = physics.run_shot(balls_in, v0=3.0, phi=90.0, b=0.25)
    last = frames[-1]
    check(
        "last frame == run_shot final (<=1 mm)",
        all(
            near(
                pos(last, bid),
                (plain["balls"][bid]["x"], plain["balls"][bid]["y"]),
                1e-3,
            )
            for bid in ids
        ),
    )
    check(
        "pocketed sets match",
        sorted(plain["pocketed"]) == sorted(res["pocketed"]),
        f"{res['pocketed']} vs {plain['pocketed']}",
    )

    # every event time hits a keyframe within 1 ms (they ARE keyframe times).
    # Step 7: collision events must survive pruning exactly — a collision
    # implies motion, so their rows differ from their neighbours. Motion
    # TRANSITIONS (slide/roll/spin/stationary) may sit on frozen rows and be
    # pruned; they carry no position information, so only collisions are
    # asserted here.
    collision_types = {
        "ball_ball",
        "ball_linear_cushion",
        "ball_circular_cushion",
        "ball_pocket",
        "stick_ball",
        "ball_table",
        "ball_off_table",
    }
    kf_times = set(times)
    misses = [
        ev
        for ev in kf["events"]
        if ev["type"] in collision_types
        and not any(abs(ev["t_ms"] - t) <= 1 for t in kf_times)
    ]
    check("all COLLISION event times are keyframe times", not misses, str(misses[:3]))

    # plausible speeds: 40 ms -> max displacement ~ v_max * dt (+keyframe rounding)
    max_disp = 0.0
    for i in range(len(frames) - 1):
        for bid in ids:
            x0, y0 = pos(frames[i], bid)
            x1, y1 = pos(frames[i + 1], bid)
            max_disp = max(max_disp, ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5)
    check(
        "no teleporting: max per-40ms move <= 0.55 m (~13.8 m/s)",
        max_disp <= 0.55,
        f"max {max_disp * 1000:.0f} mm",
    )

    # pocketed balls rest near their pocket centers (final frames keep them there)
    pockets = physics.table_dimensions()["pockets"]
    for bid in res["pocketed"]:
        px, py = pos(last, bid)
        best = min(
            ((p["x"], p["y"]) for p in pockets.values()),
            key=lambda c: ((px - c[0]) ** 2 + (py - c[1]) ** 2) ** 0.5,
        )
        check(
            f"pocketed '{bid}' rests near a pocket center (<= 60 mm)",
            near((px, py), best, 0.06),
            f"dist {((px - best[0]) ** 2 + (py - best[1]) ** 2) ** 0.5 * 1000:.0f} mm",
        )
    if not res["pocketed"]:
        print("  ..  (break pocketed nothing; pocket-rest checks skipped)")
    check(
        "on-table final excludes pocketed",
        all(bid not in res["pocketed"] for bid in res["balls"]),
    )

    # soft shot: single fast path, few frames, still consistent
    soft = physics.run_shot_keyframes(balls_in, v0=0.8, phi=45.0)
    check(
        "soft shot: >=2 frames, last frame matches duration",
        len(soft["keyframes"]["frames"]) >= 2
        and soft["keyframes"]["frames"][-1][0] == round(soft["duration_s"] * 1000),
    )

    # deterministic pot: "1" sits on the corner-pocket diagonal, cue dead behind
    # it with a stun shot (b=0) so the cue stops instead of following the ball
    # into the pocket -> exactly one ball must drop
    pot = physics.run_shot_keyframes(
        {"cue": (0.30, 0.30), "1": (0.15, 0.15)}, v0=1.5, phi=225.0, b=0.0
    )
    check(
        "diagonal pot pockets ball '1'", pot["pocketed"] == ["1"], str(pot["pocketed"])
    )
    pkf = pot["keyframes"]
    p_last = pkf["frames"][-1]
    p_col = {bid: i for i, bid in enumerate(pkf["ids"])}
    px, py = p_last[1 + 2 * p_col["1"]], p_last[2 + 2 * p_col["1"]]
    pockets2 = physics.table_dimensions()["pockets"]
    best = min(
        ((p["x"], p["y"]) for p in pockets2.values()),
        key=lambda c: ((px - c[0]) ** 2 + (py - c[1]) ** 2) ** 0.5,
    )
    check(
        "pocketed ball's last keyframe rests at the pocket (<= 60 mm)",
        ((px - best[0]) ** 2 + (py - best[1]) ** 2) ** 0.5 <= 0.06,
        f"dist {((px - best[0]) ** 2 + (py - best[1]) ** 2) ** 0.5 * 1000:.0f} mm",
    )
    check(
        "cue ball stays on the table after the pot",
        "cue" not in pot["pocketed"] and "cue" in pot["balls"],
    )

    # respot helper: head spot occupied -> nearest free spot towards the head rail
    occupied = {"1": (physics.TABLE_W / 2, 0.25 * physics.TABLE_L)}
    rx, ry = physics.respot_cue_position(occupied)
    clear = ((rx - occupied["1"][0]) ** 2 + (ry - occupied["1"][1]) ** 2) ** 0.5
    check(
        "respot nudges off the occupied head spot (>= 2R-eps)",
        clear >= physics.MIN_SEPARATION - 1e-9 and ry < 0.25 * physics.TABLE_L,
        f"dist {clear * 1000:.0f} mm",
    )

    print()
    if failed:
        print(f"{len(failed)} FAILED, {passed} passed")
        return 1
    print(f"ALL {passed} CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
