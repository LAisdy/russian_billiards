"""Step 10 benchmark: ruleset hot-path profiling for the Russian pyramid module.

Measures, per discipline (Free / Combined / Dynamic / Classic):

* ``physics_ms``      -- wall time of one simulated break stroke (baseline the
  ruleset cost is compared against).
* ``evaluate_break_us`` -- ``build_shot_info`` + ``next_shot_constraints`` on
  the simulated break shot (shot_number == 0, the п. 12 break path).
* ``evaluate_mid_us``   -- the same on the п. 20 ordinary-completion path
  (``shot_number`` preset to a mid-game value).
* ``process_us``      -- ``process_and_advance`` on restored ball snapshots
  (includes respot machinery + a fresh game object per iteration).
* ``construct_us``    -- bare ruleset construction, so the fresh-game overhead
  inside ``process_us`` can be discounted.

A cProfile section (Free discipline, break path) prints the functions that
dominate the ruleset cost and saves a ``.prof`` file next to this script.

Usage:
    python /home/z/my-project/scripts/benchmark_step10.py \
        [--repeats N] [--profile-reps M] [--json OUT] [--no-profile]

The script is read-only with respect to the repository (module timing uses
in-memory snapshots); run it before and after an optimization change to
produce the before/after table for ``PROGRESS.md``.
"""

from __future__ import annotations

import argparse
import copy
import cProfile
import io
import json
import pstats
import statistics
import time
from collections.abc import Callable

from pooltool.game.datatypes import GameType
from pooltool.layouts import get_rack
from pooltool.objects.cue.datatypes import Cue
from pooltool.objects.table.collection import default_specs_from_game_type
from pooltool.objects.table.datatypes import Table
from pooltool.ruleset import russian_pyramid as rp
from pooltool.ruleset.datatypes import Player

import pooltool as pt

GAME_TYPES: dict[str, GameType] = {
    "free": GameType.RUSSIAN_PYRAMID_FREE,
    "combined": GameType.RUSSIAN_PYRAMID_COMBINED,
    "dynamic": GameType.RUSSIAN_PYRAMID_DYNAMIC,
    "classic": GameType.RUSSIAN_PYRAMID_CLASSIC,
}

RULESET_CLASSES = {
    "free": rp.RussianFreePyramid,
    "combined": rp.RussianCombinedPyramid,
    "dynamic": rp.RussianDynamicPyramid,
    "classic": rp.RussianClassicPyramid,
}

REAR_MARK_FRACTION = rp.REAR_SPOT_FRACTION


def build_break_system(game_type: GameType) -> pt.System:
    """Full-rack Russian pyramid break aimed dead-straight at the apex ball."""
    table = Table.from_table_specs(default_specs_from_game_type(game_type))
    balls = get_rack(game_type, table)
    cue = Cue.default()
    cue.set_state(cue_ball_id="cue")
    system = pt.System(table=table, balls=balls, cue=cue)

    mark_y = REAR_MARK_FRACTION * table.l
    apex = min(
        (b for b in balls.values() if b.id != "cue"),
        key=lambda b: (
            float(b.state.rvw[0, 0]) ** 2 + (float(b.state.rvw[0, 1]) - mark_y) ** 2
        ),
    )
    system.cue.set_state(V0=9.0, phi=pt.aim.at_ball(system, apex.id))
    return system


def snapshot_balls(system: pt.System) -> dict:
    """Cheap mutable-state snapshot of every ball (state + history)."""
    return {
        ball_id: (ball.state.copy(), ball.history.copy())
        for ball_id, ball in system.balls.items()
    }


def restore_balls(system: pt.System, snap: dict) -> None:
    for ball_id, ball in system.balls.items():
        state, history = snap[ball_id]
        ball.state = state.copy()
        ball.history = history.copy()


def best_mean_us(fn: Callable[[], None], repeats: int, rounds: int = 3) -> float:
    """Mean microseconds per ``fn()`` call; best (min) of ``rounds`` rounds."""
    best = float("inf")
    for _ in range(rounds):
        t0 = time.perf_counter()
        for _ in range(repeats):
            fn()
        best = min(best, (time.perf_counter() - t0) / repeats)
    return best * 1e6


def median_ms(fn: Callable[[], None], repeats: int) -> float:
    samples = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1e3)
    return statistics.median(samples)


def make_game(key: str, mid_game: bool = False):
    game = RULESET_CLASSES[key](players=[Player("A"), Player("B")])
    if mid_game:
        game.shot_number = 5
    return game


def evaluate_once(game, shot) -> None:
    """Read-only ruleset evaluation mirroring ``process_shot`` + ``advance``."""
    game.shot_info = game.build_shot_info(shot)
    game.next_shot_constraints(shot)


def measure_discipline(key: str, repeats: int, physics_runs: int) -> dict:
    # Physics baseline (numba quartic solver is warmed up by the caller).
    template = build_break_system(GAME_TYPES[key])

    def simulate_fresh() -> None:
        sim = copy.deepcopy(template)
        pt.simulate(sim, inplace=True)

    physics_ms = median_ms(simulate_fresh, physics_runs)

    # The simulated shot the ruleset is benchmarked against.
    shot = copy.deepcopy(template)
    pt.simulate(shot, inplace=True)
    snap = snapshot_balls(shot)

    break_game = make_game(key)
    mid_game = make_game(key, mid_game=True)

    def eval_break() -> None:
        evaluate_once(break_game, shot)

    def eval_mid() -> None:
        evaluate_once(mid_game, shot)

    def full_process() -> None:
        restore_balls(shot, snap)
        make_game(key).process_and_advance(shot)

    def construct() -> None:
        make_game(key)

    results = {
        "physics_ms": round(physics_ms, 3),
        "evaluate_break_us": round(best_mean_us(eval_break, repeats), 2),
        "evaluate_mid_us": round(best_mean_us(eval_mid, repeats), 2),
        "process_us": round(best_mean_us(full_process, repeats), 2),
        "construct_us": round(best_mean_us(construct, repeats), 2),
        "events": len(shot.events),
        "potted": len(rp.potted_ball_ids(shot)),
    }
    results["ruleset_share_pct"] = round(
        100.0
        * (results["process_us"] - results["construct_us"])
        / 1000.0
        / results["physics_ms"],
        3,
    )
    return results


def profile_free(profile_reps: int, prof_path: str) -> str:
    """cProfile the Free Pyramid break evaluation; returns a pstats report."""
    shot = build_break_system(GAME_TYPES["free"])
    pt.simulate(shot, inplace=True)
    game = make_game("free")

    def loop() -> None:
        for _ in range(profile_reps):
            evaluate_once(game, shot)

    profiler = cProfile.Profile()
    profiler.enable()
    loop()
    profiler.disable()
    profiler.dump_stats(prof_path)

    for sort_key in ("cumulative", "tottime"):
        stream = io.StringIO()
        stats = pstats.Stats(profiler, stream=stream)
        stats.sort_stats(sort_key).print_stats(12)
        text = stream.getvalue()
        # Keep only the useful middle section of the pstats table.
        lines = text.splitlines()
        start = next((i for i, ln in enumerate(lines) if "ncalls" in ln), 0)
        print(f"\n--- cProfile (free, break path, {profile_reps} reps, {sort_key}) ---")
        print("\n".join(lines[start : start + 16]))

    return prof_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=300)
    parser.add_argument("--profile-reps", type=int, default=300)
    parser.add_argument("--physics-runs", type=int, default=5)
    parser.add_argument("--json", dest="json_out", default=None)
    parser.add_argument("--no-profile", action="store_true")
    args = parser.parse_args()

    # Warm up the numba-compiled physics paths before any timing.
    warm = build_break_system(GAME_TYPES["free"])
    pt.simulate(warm, inplace=True)

    results: dict[str, dict] = {}
    for key in GAME_TYPES:
        results[key] = measure_discipline(key, args.repeats, args.physics_runs)

    print()
    header = (
        f"{'discipline':<10} {'physics':>10} {'eval@break':>11} {'eval@mid':>10} "
        f"{'process':>9} {'construct':>10} {'events':>7} {'share':>7}"
    )
    print(header)
    print("-" * len(header))
    for key, r in results.items():
        print(
            f"{key:<10} {r['physics_ms']:>8.2f}ms {r['evaluate_break_us']:>9.1f}us "
            f"{r['evaluate_mid_us']:>8.1f}us {r['process_us']:>7.1f}us "
            f"{r['construct_us']:>8.1f}us {r['events']:>7} "
            f"{r['ruleset_share_pct']:>6.2f}%"
        )

    if not args.no_profile:
        prof_path = "/home/z/my-project/scripts/step10_free.prof"
        profile_free(args.profile_reps, prof_path)

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nresults written to {args.json_out}")


if __name__ == "__main__":
    main()
