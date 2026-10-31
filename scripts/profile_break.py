#!/usr/bin/env python3
"""Diagnose Issue 1: measure end-to-end simulate() cost for a Russian break.

Times, in sequence:
  1. import + first-call JIT warmup (System.example(), the same warmup the GUI does)
  2. Russian 16-ball break shot with the 2D resolver
  3. Russian 16-ball break shot with the 3D resolver (what play.py enables)
  4. cProfile breakdown of a second 3D break (post-warmup steady state)

This tells us whether the numba kernels are hot and where the residual wall time
goes (detector vs evolve vs resolve vs continuize).
"""

from __future__ import annotations

import cProfile
import io
import pstats
import time

import pooltool as pt
from pooltool.evolution import simulate
from pooltool.evolution.engine import SimulationEngine
from pooltool.game.datatypes import GameType
from pooltool.layouts import get_rack
from pooltool.objects.table.collection import TableName, prebuilt_specs
from pooltool.objects.table.datatypes import Table
from pooltool.physics.resolve import Resolver


def make_break_system() -> pt.System:
    table = Table.from_table_specs(prebuilt_specs(TableName.RUSSIAN_PYRAMID_GENERIC))
    balls = get_rack(
        game_type=GameType.RUSSIAN_PYRAMID_FREE,
        table=table,
        ball_params=None,
        ballset=None,
        spacing_factor=1e-3,
    )
    apex = min(
        (b for b in balls.values() if b.id != "cue"),
        key=lambda b: float(b.state.rvw[0, 0]),
    )
    cue = pt.Cue(cue_ball_id="cue")
    system = pt.System(cue=cue, table=table, balls=balls)
    cue.set_state(V0=3.5, phi=pt.aim.at_ball(system, apex.id))
    return system


def time_sim(system: pt.System, is_3d: bool, label: str) -> float:
    engine = SimulationEngine(is_3d=is_3d, resolver=Resolver.default(is_3d=is_3d))
    t0 = time.perf_counter()
    simulate(system, engine=engine, inplace=True)
    dt = time.perf_counter() - t0
    n_events = len(system.events)
    print(f"{label:38s} {dt * 1000:8.1f} ms   ({n_events} events)")
    return dt


def main() -> int:
    t0 = time.perf_counter()
    warm = pt.System.example()
    simulate(warm, inplace=True)  # JIT warmup, same as GUI _enter_game does
    print(
        f"{'warmup (System.example, 2D)':38s} "
        f"{(time.perf_counter() - t0) * 1000:8.1f} ms"
    )

    # Steady-state 2D
    time_sim(make_break_system(), is_3d=False, label="break 2D (steady)")
    # First 3D shot (new kernels may compile here)
    t0 = time.perf_counter()
    time_sim(make_break_system(), is_3d=True, label="break 3D (first, may compile)")
    print(
        f"  ^ 3D first-shot wall incl. any JIT: "
        f"{(time.perf_counter() - t0) * 1000:.1f} ms"
    )
    # Steady-state 3D
    time_sim(make_break_system(), is_3d=True, label="break 3D (steady)")

    # Profile steady-state 3D
    system = make_break_system()
    engine = SimulationEngine(is_3d=True, resolver=Resolver.default(is_3d=True))
    pr = cProfile.Profile()
    pr.enable()
    simulate(system, engine=engine, inplace=True)
    pr.disable()
    buf = io.StringIO()
    stats = pstats.Stats(pr, stream=buf).sort_stats("cumulative")
    stats.print_stats(18)
    print("==== cProfile (3D break, steady state) ====")
    print(buf.getvalue())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
