"""Probe scenarios for Step 6 test design (Free Pyramid)."""

from __future__ import annotations

import time

import numpy as np

import pooltool as pt
import pooltool.constants as const
from pooltool.game.datatypes import GameType
from pooltool.layouts import get_rack
from pooltool.objects.table.collection import default_specs_from_game_type
from pooltool.objects.table.datatypes import Table
from pooltool.ruleset import russian_pyramid as rp


def russian_table_and_rack():
    table = Table.from_table_specs(
        default_specs_from_game_type(GameType.RUSSIAN_PYRAMID_FREE)
    )
    return table, get_rack(GameType.RUSSIAN_PYRAMID_FREE, table)


def main() -> None:
    table, balls = russian_table_and_rack()
    print("pocket centers:")
    for pid, pocket in table.pockets.items():
        print(f"  {pid}: ({float(pocket.center[0]):.4f}, {float(pocket.center[1]):.4f})")

    # --- probe 1: svoyak straight pot into the right middle pocket ---
    w, l = table.w, table.l
    table2, balls2 = russian_table_and_rack()
    for i in range(2, 16):
        del balls2[str(i)]
    R = balls2["1"].params.R
    rc = table2.pockets["rc"].center
    px, py = float(rc[0]), float(rc[1])
    # direction from pocket center into the table (unit-ish)
    d = np.array([w / 2 - px, l / 2 - py])
    d = d / np.linalg.norm(d)
    ball_xy = (px + 0.45 * d[0], py + 0.45 * d[1])
    cue_xy = (px + 0.90 * d[0], py + 0.90 * d[1])
    balls2["1"].state.rvw[0] = [ball_xy[0], ball_xy[1], R]
    balls2["cue"].state.rvw[0] = [cue_xy[0], cue_xy[1], R]
    import math

    phi = math.degrees(math.atan2(py - cue_xy[1], px - cue_xy[0]))
    cue = pt.Cue.default()
    cue.set_state(cue_ball_id="cue")
    system = pt.System(table=table2, balls=balls2, cue=cue)
    system.cue.set_state(V0=3.5, phi=phi)
    t0 = time.perf_counter()
    pt.simulate(system, inplace=True)
    dt = time.perf_counter() - t0
    potted = rp.potted_ball_ids(system)
    contact = rp.first_object_contact(system)
    legal, reason = rp.evaluate_free_shot(system, is_break=False)
    print(f"svoyak probe: potted={potted} contact={contact} legal={legal} "
          f"reason={reason} sim={dt:.2f}s cue_s={system.balls['cue'].state.s}")

    # --- probe 2: full-break sim timing ---
    table3, balls3 = russian_table_and_rack()
    cue3 = pt.Cue.default()
    cue3.set_state(cue_ball_id="cue")
    system3 = pt.System(table=table3, balls=balls3, cue=cue3)
    system3.cue.set_state(V0=9.0, phi=pt.aim.at_ball(system3, "1"))
    t0 = time.perf_counter()
    pt.simulate(system3, inplace=True)
    dt = time.perf_counter() - t0
    potted3 = rp.potted_ball_ids(system3)
    legal3, reason3 = rp.evaluate_free_shot(system3, is_break=True)
    print(f"break probe: potted={potted3} legal={legal3} reason={reason3} sim={dt:.2f}s")

    # --- probe 3: svoyak respot flow on probe-1 system ---
    game = rp.RussianFreePyramid(players=[pt.Player("A"), pt.Player("B")])
    game.process_and_advance(system)
    mark = (w / 2, rp.REAR_SPOT_FRACTION * l)
    cue_ball = system.balls["cue"]
    print(
        f"svoyak flow: score={dict(game.score)} turn_over={game.shot_info.turn_over} "
        f"cue_pos=({float(cue_ball.xyz[0]):.4f}, {float(cue_ball.xyz[1]):.4f}) "
        f"mark={mark} cue_s={cue_ball.state.s} "
        f"bih={game.shot_constraints.ball_in_hand} "
        f"hittable={game.shot_constraints.hittable}"
    )


if __name__ == "__main__":
    main()
