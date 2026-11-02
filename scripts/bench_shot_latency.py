"""Quantify the 16.8 s "Simulating shot..." delay: warm sim cost per shot
class + how early partial results become available (streaming feasibility).

Pure Python probe (no server, no browser). Read-only w.r.t. the repo.
"""
from __future__ import annotations

import os
import sys
import time

BACKEND = "/home/z/my-project/pyramid-web/backend"
sys.path.insert(0, BACKEND)
os.environ.setdefault("PYTHONHASHSEED", "0")

import json

import pooltool as pt
from pooltool.evolution.event_based.simulate import (  # noqa: E402
    INCLUDED_EVENTS,
    _SimulationState,
)

from app import physics  # noqa: E402


def rack_balls() -> dict:
    return {b: (p["x"], p["y"]) for b, p in physics.russian_rack(seed=7).items()}


def main() -> None:
    balls = rack_balls()

    # --- warm JIT (exactly what the baked image ships) -------------------
    t0 = time.perf_counter()
    physics.run_shot_keyframes(balls, v0=2.0, phi=60.0)
    t1 = time.perf_counter()
    physics.run_shot_keyframes(balls, v0=2.0, phi=60.0)
    t2 = time.perf_counter()
    print(f"warmup pass 1 (cold-ish): {t1 - t0:.2f}s   pass 2 (warm): {t2 - t1:.3f}s")

    # --- warm cost per shot class ----------------------------------------
    print(f"\n{'v0':>5} {'sim_ms':>9} {'kf_ms':>8} {'total_s':>8} "
          f"{'events':>7} {'frames':>7} {'kf_KB':>7} {'shot_s':>7}")
    for v0 in (1.8, 3.0, 5.0, 9.0):
        t0 = time.perf_counter()
        r = physics.run_shot_keyframes(balls, v0=v0, phi=90.0)
        total = time.perf_counter() - t0
        # kf_ms: time of the post-sim keyframe build alone, re-derived by
        # timing a second sim and subtracting (approximate but stable)
        print(f"{v0:>5.1f} {r['sim_ms']:>9.1f} {'':>8} {total:>8.3f} "
              f"{len(r['keyframes']['events']):>7} "
              f"{r['kf_stats']['frames']:>7} "
              f"{r['kf_stats']['bytes'] / 1024:>7.1f} "
              f"{r['keyframes']['duration_ms'] / 1000:>7.2f}")

    # --- streaming feasibility: wall time to first/25/50/100% of events ---
    print("\nincremental simulation (same step loop as pt.simulate):")
    for v0 in (3.0, 9.0):
        system = physics._build_system(balls, v0=v0, phi=90.0, a=0.0, b=0.25, theta=0.0)
        sim = _SimulationState(system.copy(), physics.ENGINE_3D, None, INCLUDED_EVENTS, 0)
        sim.init()
        marks: list[tuple[float, float]] = []  # (wall_s, sim_t)
        t0 = time.perf_counter()
        n_events = 0
        while not sim.done:
            ev = sim.step()
            if not sim.done:
                sim.update_caches(ev)
                marks.append((time.perf_counter() - t0, float(sim.shot.t)))
            n_events += 1
        total_wall = time.perf_counter() - t0
        n = len(marks)
        print(f"  v0={v0}: events={n_events} wall={total_wall:.3f}s "
              f"first_event@{marks[0][0]*1000:.0f}ms  "
              f"25%@{marks[n//4][0]:.3f}s  50%@{marks[n//2][0]:.3f}s  "
              f"90%@{marks[int(n*0.9)][0]:.3f}s  (sim duration {marks[-1][1]:.2f}s)")

    # --- equivalence check: incremental loop == pt.simulate ---------------
    a = physics._build_system(balls, v0=9.0, phi=90.0, a=0.0, b=0.25, theta=0.0)
    sim = _SimulationState(a, physics.ENGINE_3D, None, INCLUDED_EVENTS, 0)
    sim.init()
    while not sim.done:
        ev = sim.step()
        if not sim.done:
            sim.update_caches(ev)
    b = pt.simulate(
        physics._build_system(balls, v0=9.0, phi=90.0, a=0.0, b=0.25, theta=0.0),
        engine=physics.ENGINE_3D,
    )
    da = {bid: (round(float(x.state.rvw[0, 0]), 6), round(float(x.state.rvw[0, 1]), 6))
          for bid, x in sim.shot.balls.items()}
    db = {bid: (round(float(x.state.rvw[0, 0]), 6), round(float(x.state.rvw[0, 1]), 6))
          for bid, x in b.balls.items()}
    print(f"\nequivalence incremental vs pt.simulate (final positions, v0=9): "
          f"{'IDENTICAL' if da == db else 'DIFFERENT'}")

    # --- post-sim keyframe build cost alone -------------------------------
    system = physics._build_system(balls, v0=9.0, phi=90.0, a=0.0, b=0.25, theta=0.0)
    simulated = pt.simulate(system, engine=physics.ENGINE_3D)
    t0 = time.perf_counter()
    times = [i * 0.04 for i in range(int(float(simulated.t) / 0.04) + 1)]
    rows = []
    for bid in simulated.balls:
        states = pt.interpolate_ball_states(simulated.balls[bid], times, extrapolate=True)
        rows.append([(float(s.rvw[0, 0]), float(s.rvw[0, 1])) for s in states])
    t1 = time.perf_counter()
    payload = json.dumps({"t": [round(t * 1000) for t in times], "rows": rows})
    print(f"keyframe build (16 balls x {len(times)} times): {t1 - t0:.3f}s, "
          f"json {len(payload) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
