"""Tests for the Russian pyramid («пирамида») extension.

This file holds the Step 3 equipment tests (table specs, ball params,
ballset) and, from Step 6 onward, the per-discipline ruleset scenario tests
(Free, Combined, Dynamic, Classic in Steps 6-9) and the 500-shot fuzz tests
in Step 11.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import ClassVar

import numpy as np
import pytest

import pooltool as pt
import pooltool.constants as const
from pooltool.events.datatypes import Agent, AgentType, Event, EventType
from pooltool.game.datatypes import GameType
from pooltool.layouts import get_rack
from pooltool.objects.ball.datatypes import BallState
from pooltool.objects.ball.params import BALL_PARAMS, BallParams, PrebuiltBallParams
from pooltool.objects.ball.sets import get_ballset, get_ballset_names
from pooltool.objects.table.collection import (
    TABLE_SPECS,
    TableName,
    default_specs_from_game_type,
)
from pooltool.objects.table.datatypes import Table
from pooltool.objects.table.specs import PocketTableSpecs
from pooltool.ruleset import russian_pyramid as rp
from pooltool.ruleset.datatypes import (
    BallInHandOptions,
    Player,
    ShotConstraints,
    ShotInfo,
)

RUSSIAN_TABLE = TableName.RUSSIAN_PYRAMID_GENERIC
RUSSIAN_BALL_PARAMS = PrebuiltBallParams.RUSSIAN_PYRAMID_GENERIC
RUSSIAN_BALLSET = "russian_pyramid"

RUSSIAN_BALL_IDS = ("cue",) + tuple(str(i) for i in range(1, 16))


class TestRussianTableSpecs:
    def test_member_exists(self) -> None:
        assert RUSSIAN_TABLE in TABLE_SPECS

    def test_specs_are_pocket_table_type(self) -> None:
        assert isinstance(TABLE_SPECS[RUSSIAN_TABLE], PocketTableSpecs)

    def test_playing_surface_dimensions(self) -> None:
        # Task spec: playing surface 370 x 180 cm (12 x 6 ft).
        specs = TABLE_SPECS[RUSSIAN_TABLE]
        assert specs.l == pytest.approx(3.70)
        assert specs.w == pytest.approx(1.80)

    def test_pocket_mouth_widths_match_task_spec(self) -> None:
        # Corner: 72-73 mm band; middle: 82-83 mm band.
        specs = TABLE_SPECS[RUSSIAN_TABLE]
        assert 0.072 <= specs.corner_pocket_width <= 0.073
        assert 0.082 <= specs.side_pocket_width <= 0.083

    def test_middle_pockets_wider_than_corner_pockets(self) -> None:
        specs = TABLE_SPECS[RUSSIAN_TABLE]
        assert specs.side_pocket_width > specs.corner_pocket_width

    def test_pocket_geometry_is_self_consistent(self) -> None:
        # The pocket back circle must exceed half the mouth width, otherwise
        # the generated pocket geometry degenerates.
        specs = TABLE_SPECS[RUSSIAN_TABLE]
        assert specs.corner_pocket_radius > specs.corner_pocket_width / 2
        assert specs.side_pocket_radius > specs.side_pocket_width / 2

    def test_table_builds_from_specs(self) -> None:
        table = Table.from_table_specs(TABLE_SPECS[RUSSIAN_TABLE])
        assert len(table.pockets) == 6
        assert len(table.cushion_segments.linear) > 0
        assert len(table.cushion_segments.circular) > 0


class TestRussianBallParams:
    def test_member_exists(self) -> None:
        assert RUSSIAN_BALL_PARAMS in BALL_PARAMS

    def test_mass_and_radius_match_task_spec(self) -> None:
        params = BALL_PARAMS[RUSSIAN_BALL_PARAMS]
        assert params.m == pytest.approx(0.255)
        assert params.R == pytest.approx(0.0335)
        assert 2 * params.R * 1000 == pytest.approx(67.0)

    def test_prebuilt_accessor_returns_same_object(self) -> None:
        assert (
            BallParams.prebuilt(RUSSIAN_BALL_PARAMS) is BALL_PARAMS[RUSSIAN_BALL_PARAMS]
        )

    def test_friction_parameters_positive(self) -> None:
        params = BALL_PARAMS[RUSSIAN_BALL_PARAMS]
        assert params.u_s > 0
        assert params.u_r > 0
        assert params.e_c > 0


class TestRussianBallset:
    def test_ballset_is_auto_discovered(self) -> None:
        assert RUSSIAN_BALLSET in get_ballset_names()

    def test_all_sixteen_ball_ids_resolve(self) -> None:
        ballset = get_ballset(RUSSIAN_BALLSET)
        for ball_id in RUSSIAN_BALL_IDS:
            path = ballset.ball_path(ball_id)
            assert path.exists(), f"missing model for ball id {ball_id!r}"

    def test_cue_ball_maps_to_red_model(self) -> None:
        ballset = get_ballset(RUSSIAN_BALLSET)
        assert ballset.ball_path("cue").name == "red.glb"


class TestEquipmentConsistency:
    def test_pocket_mouths_wider_than_ball(self) -> None:
        specs = TABLE_SPECS[RUSSIAN_TABLE]
        ball_diameter = 2 * BALL_PARAMS[RUSSIAN_BALL_PARAMS].R
        assert specs.corner_pocket_width > ball_diameter
        assert specs.side_pocket_width > ball_diameter

    def test_corner_pocket_is_tight(self) -> None:
        # Signature of Russian pyramid: the corner mouth is only a few
        # millimeters wider than the ball (task spec: ~3-5 mm band for
        # 72-73 mm mouths against a 67 mm ball).
        specs = TABLE_SPECS[RUSSIAN_TABLE]
        clearance = specs.corner_pocket_width - 2 * BALL_PARAMS[RUSSIAN_BALL_PARAMS].R
        assert 0 < clearance <= 0.01


# ---------------------------------------------------------------------------
# Step 6: Free Pyramid («Свободная пирамида») scenario tests
# ---------------------------------------------------------------------------
#
# Scenario coverage per the step plan: legal/illegal strokes, «свояк», the
# opening break (п. 12), cue-ball-in without contact, score progression,
# turn switching, game end, and respot administration (п. 22/п. 25).
# Synthetic shots append hand-built events to real (unsimulated) System
# objects; three scenarios run full physics simulations.


def _russian_rack() -> tuple[Table, dict]:
    table = Table.from_table_specs(
        default_specs_from_game_type(GameType.RUSSIAN_PYRAMID_FREE)
    )
    return table, get_rack(GameType.RUSSIAN_PYRAMID_FREE, table)


def _seed_histories(balls: dict, t: float = 0.0) -> None:
    """Append each ball's current state to its (initially empty) history.

    Ruleset helpers such as ``live_object_ball_ids`` read ``history[-1]``;
    on simulated systems that row is the end-of-shot state. Seeding the
    unsimulated state gives synthetic shots the same view.
    """
    for ball in balls.values():
        ball.history.add(BallState(rvw=ball.state.rvw.copy(), s=ball.state.s, t=t))


def _ball_agent(ball_id: str) -> Agent:
    return Agent(id=ball_id, agent_type=AgentType.BALL)


def _cushion_agent(cushion_id: str) -> Agent:
    return Agent(id=cushion_id, agent_type=AgentType.LINEAR_CUSHION_SEGMENT)


def _pocket_agent(pocket_id: str) -> Agent:
    return Agent(id=pocket_id, agent_type=AgentType.POCKET)


def _contact_event(t: float, obj: str = "1") -> Event:
    return Event(
        event_type=EventType.BALL_BALL,
        agents=(_ball_agent(rp.CUE_BALL_ID), _ball_agent(obj)),
        time=t,
    )


def _cushion_event(ball_id: str, cushion_id: str, t: float) -> Event:
    return Event(
        event_type=EventType.BALL_LINEAR_CUSHION,
        agents=(_ball_agent(ball_id), _cushion_agent(cushion_id)),
        time=t,
    )


def _make_system(
    keep: tuple[str, ...] | None = None,
    positions: dict[str, tuple[float, float]] | None = None,
) -> pt.System:
    """Real Russian pyramid system, pruned to ``keep`` and repositioned.

    ``keep=None`` keeps the full 16-ball rack. All ball histories are seeded
    with the (post-repositioning) state so history-based helpers work.
    """
    table, balls = _russian_rack()
    if keep is not None:
        for ball_id in list(balls):
            if ball_id not in keep:
                del balls[ball_id]
    for ball_id, (x, y) in (positions or {}).items():
        balls[ball_id].state.rvw[0] = [x, y, balls[ball_id].params.R]
    _seed_histories(balls)
    cue = pt.Cue.default()
    cue.set_state(cue_ball_id=rp.CUE_BALL_ID)
    return pt.System(cue=cue, table=table, balls=balls)


def _make_game(
    shot_number: int = 0,
    game_cls: type = rp.RussianFreePyramid,
) -> rp.Ruleset:
    """Two-player pyramid game; ``shot_number > 0`` = mid-game stroke."""
    game = game_cls(players=[Player("A"), Player("B")])
    game.shot_number = shot_number
    return game


def _mark_pocketed(system: pt.System, ball_id: str, pocket_id: str, t: float) -> None:
    """Send ``ball_id`` to ``pocket_id``: state, history row, and event."""
    ball = system.balls[ball_id]
    pocket = system.table.pockets[pocket_id]
    ball.state.rvw[:] = np.array(
        [
            [float(pocket.center[0]), float(pocket.center[1]), -pocket.depth],
            [0, 0, 0],
            [0, 0, 0],
        ]
    )
    ball.state.s = const.pocketed
    ball.history.add(BallState(rvw=ball.state.rvw.copy(), s=const.pocketed, t=t))
    system.events.append(
        Event(
            event_type=EventType.BALL_POCKET,
            agents=(_ball_agent(ball_id), _pocket_agent(pocket_id)),
            time=t,
        )
    )


def _mark_off_table(system: pt.System, ball_id: str, t: float) -> None:
    """Knock ``ball_id`` off the table: state, history row, and event."""
    ball = system.balls[ball_id]
    ball.state.rvw[:] = np.array([[2 * system.table.w, 0.0, 0.0], [0, 0, 0], [0, 0, 0]])
    ball.state.s = const.off_table
    ball.history.add(BallState(rvw=ball.state.rvw.copy(), s=const.off_table, t=t))
    system.events.append(
        Event(
            event_type=EventType.BALL_OFF_TABLE,
            agents=(_ball_agent(ball_id),),
            time=t,
        )
    )


def _touch_row(system: pt.System, ball_id: str, t: float) -> None:
    """Record ``ball_id``'s (unchanged) position as its state at time ``t``.

    Represents the instant of the cue-ball contact for house-stroke checks,
    which read the contacted ball's position at the first-contact time.
    """
    ball = system.balls[ball_id]
    ball.history.add(BallState(rvw=ball.state.rvw.copy(), s=ball.state.s, t=t))


def _dist_to_nearest_pocket_sq(system: pt.System, ball_id: str) -> float:
    x, y = (float(v) for v in system.balls[ball_id].state.rvw[0, :2])
    pocket = rp.nearest_pocket(system.table, (x, y))
    return (x - float(pocket.center[0])) ** 2 + (y - float(pocket.center[1])) ** 2


class TestFreePyramidBreak:
    def test_break_constraints_grant_house_ball_in_hand(self) -> None:
        game = rp.RussianFreePyramid(players=[Player("A"), Player("B")])
        c0 = game.initial_shot_constraints()

        assert c0.ball_in_hand == BallInHandOptions.BEHIND_LINE
        assert c0.movable == [rp.CUE_BALL_ID]
        assert c0.cueable == [rp.CUE_BALL_ID]
        assert c0.hittable == tuple(str(i) for i in range(1, 16))
        assert c0.call_shot is False
        assert c0.can_shoot()

        # The constructor installs the same break constraints.
        assert game.shot_constraints == c0

    def test_real_break_is_legal_and_scores_pots(self) -> None:
        system = _make_system()
        apex = min(
            (b for b in system.balls.values() if b.id != rp.CUE_BALL_ID),
            key=lambda b: (
                float(b.state.rvw[0, 0]) ** 2
                + (float(b.state.rvw[0, 1]) - rp.REAR_SPOT_FRACTION * system.table.l)
                ** 2
            ),
        )
        system.cue.set_state(V0=9.0, phi=pt.aim.at_ball(system, apex.id))
        pt.simulate(system, inplace=True)

        assert rp.first_object_contact(system) is not None
        potted = rp.potted_ball_ids(system)

        game = rp.RussianFreePyramid(players=[Player("A"), Player("B")])
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.FreePyramidReason.LEGAL_BREAK
        # Every ball potted on the legal break scores, свояк included.
        assert game.score["A"] == len(potted)
        # The breaker continues only when something was pocketed.
        assert info.turn_over == (len(potted) == 0)
        assert info.game_over is (len(potted) >= rp.FREE_TARGET_SCORE)
        assert game.shot_number == 1
        if info.turn_over:
            assert game.active_idx == 1
            assert game.shot_constraints.ball_in_hand == BallInHandOptions.NONE
        else:
            assert game.active_idx == 0


class TestFreePyramidLegality:
    """Synthetic event-based legality judgments (fast, deterministic)."""

    def test_no_contact_is_always_a_foul(self) -> None:
        system = _make_system()

        for is_break in (False, True):
            legal, reason = rp.evaluate_free_shot(system, is_break=is_break)
            assert not legal and reason == rp.FreePyramidReason.NO_CONTACT

        game = _make_game()
        info = game.build_shot_info(system)
        assert not info.legal
        assert info.reason == rp.FreePyramidReason.NO_CONTACT
        # Foul: opponent +1, shooter's turn over.
        assert info.score == Counter({"B": 1})
        assert info.turn_over and not info.game_over

    def test_contact_without_completion_is_a_foul(self) -> None:
        system = _make_system()
        system.events.append(_contact_event(t=0.2))

        # Ordinary stroke: contact happened but no ball was potted, no ball
        # reached a cushion, nothing crossed the central line -> п. 20 foul.
        legal, reason = rp.evaluate_free_shot(system, is_break=False)
        assert not legal and reason == rp.FreePyramidReason.ILLEGAL_COMPLETION

        # The very same stroke fails the break requirements (п. 12) too.
        legal, reason = rp.evaluate_free_shot(system, is_break=True)
        assert not legal and reason == rp.FreePyramidReason.ILLEGAL_BREAK

    def test_break_with_three_cushioned_balls_is_legal(self) -> None:
        system = _make_system()
        system.events.append(_contact_event(t=0.2))
        for ball_id, cushion_id, t in (
            ("1", "l1", 0.3),
            ("2", "l2", 0.4),
            ("3", "l3", 0.5),
        ):
            system.events.append(_cushion_event(ball_id, cushion_id, t))

        game = _make_game()  # shot_number == 0 -> break evaluation
        info = game.build_shot_info(system)
        assert info.legal and info.reason == rp.FreePyramidReason.LEGAL_BREAK
        # Nothing potted -> no score, turn passes.
        assert info.score == Counter() and info.turn_over

    def test_break_with_two_cushions_needs_central_crossing(self) -> None:
        system = _make_system()
        system.events.append(_contact_event(t=0.2))
        system.events.append(_cushion_event("1", "l1", 0.3))
        system.events.append(_cushion_event("2", "l2", 0.4))

        # Two cushioned object balls, none crossing the central line: foul.
        assert not rp.is_legal_break_shot(system)

        # Ball "2" (already cushioned) later crosses the central line.
        ball = system.balls["2"]
        ball.history.add(
            BallState(
                rvw=np.array(
                    [
                        [ball.state.rvw[0, 0], 0.4 * system.table.l, ball.params.R],
                        [0, 0, 0],
                        [0, 0, 0],
                    ]
                ),
                s=const.rolling,
                t=1.0,
            )
        )
        ball.history.add(
            BallState(
                rvw=np.array(
                    [
                        [ball.state.rvw[0, 0], 0.6 * system.table.l, ball.params.R],
                        [0, 0, 0],
                        [0, 0, 0],
                    ]
                ),
                s=const.rolling,
                t=2.0,
            )
        )
        assert rp.is_legal_break_shot(system)

    def test_break_with_potted_ball_is_legal(self) -> None:
        system = _make_system()
        system.events.append(_contact_event(t=0.2))
        _mark_pocketed(system, "5", "rb", t=0.5)

        legal, reason = rp.evaluate_free_shot(system, is_break=True)
        assert legal and reason == rp.FreePyramidReason.LEGAL_BREAK

    def test_jumped_ball_fouls_even_when_ball_is_potted(self) -> None:
        system = _make_system(keep=("cue", "1", "5", "7"))
        system.events.append(_contact_event(t=0.2))
        _mark_pocketed(system, "5", "rb", t=0.4)
        _mark_off_table(system, "7", t=0.6)

        for is_break in (False, True):
            legal, reason = rp.evaluate_free_shot(system, is_break=is_break)
            assert not legal and reason == rp.FreePyramidReason.JUMPED_BALL


class TestFreePyramidScoring:
    """Scoring, turn handling, and foul administration on synthetic shots."""

    def test_legal_pots_score_and_continue_turn(self) -> None:
        system = _make_system(keep=("cue", "1", "2", "3"), positions={"3": (0.5, 1.0)})
        system.events.append(_contact_event(t=0.2))
        _mark_pocketed(system, "1", "rb", t=0.4)
        _mark_pocketed(system, "2", "rt", t=0.5)

        game = _make_game(shot_number=3)  # mid-game: ordinary evaluation
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.FreePyramidReason.LEGAL
        # Both potted object balls score for the shooter.
        assert game.score == Counter({"A": 2})
        assert not info.turn_over and not info.game_over
        # The shooter continues: same player, ordinary constraints.
        assert game.active_idx == 0 and game.turn_number == 0
        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.NONE
        assert c.movable == [] and c.cueable == [rp.CUE_BALL_ID]
        assert c.hittable == ("3",)
        # Legally potted balls stay pocketed (п. 25 respots fouls only).
        assert system.balls["1"].state.s == const.pocketed
        assert system.balls["2"].state.s == const.pocketed

    def test_svoyak_scores_and_respots_cue_to_the_mark(self) -> None:
        # Cue ball pocketed after contacting an object ball: legal, +1.
        system = _make_system(keep=("cue", "1"), positions={"1": (0.5, 1.0)})
        system.events.append(_contact_event(t=0.2))
        _mark_pocketed(system, rp.CUE_BALL_ID, "rc", t=0.5)

        game = _make_game(shot_number=3)
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.FreePyramidReason.LEGAL
        assert game.score == Counter({"A": 1})
        # A «свояк» counts as a potted ball: the shooter continues.
        assert not info.turn_over

        # The cue ball was respotted on the (free) задняя отметка.
        cue = system.balls[rp.CUE_BALL_ID]
        assert cue.state.s == const.stationary
        assert cue.xyz[0] == pytest.approx(system.table.w / 2)
        assert cue.xyz[1] == pytest.approx(rp.REAR_SPOT_FRACTION * system.table.l)
        assert cue.history[-1].s == const.stationary

        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.NONE
        assert c.movable == []
        # The only live object ball remains hittable.
        assert c.hittable == ("1",)

    def test_foul_awards_opponent_and_passes_turn(self) -> None:
        # Two live balls: the штрафной шар takes "2" (closest to a pocket),
        # leaving "1" for the incoming opponent.
        system = _make_system(
            keep=("cue", "1", "2"),
            positions={"1": (0.5, 1.0), "2": (0.9, 1.85)},
        )

        game = _make_game(shot_number=3)
        game.process_and_advance(system)

        info = game.shot_info
        assert not info.legal and info.reason == rp.FreePyramidReason.NO_CONTACT
        assert game.score == Counter({"B": 1})
        assert info.turn_over and not info.game_over
        assert game.turn_number == 1 and game.active_idx == 1

        # No scratch: the opponent plays the table as it lies, minus the
        # removed штрафной шар.
        assert system.balls["2"].state.s == const.pocketed
        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.NONE and c.movable == []
        assert c.hittable == ("1",)

    def test_reaching_target_score_ends_game(self) -> None:
        system = _make_system(keep=("cue", "1", "2"), positions={"2": (0.5, 1.0)})
        system.events.append(_contact_event(t=0.2))
        _mark_pocketed(system, "1", "rb", t=0.4)

        game = _make_game(shot_number=3)
        game.score = Counter({"A": rp.FREE_TARGET_SCORE - 1})
        game.shot_info = game.build_shot_info(system)
        game.respot_balls(system)

        info = game.shot_info
        assert info.legal
        assert info.score == Counter({"A": rp.FREE_TARGET_SCORE})
        assert info.game_over and info.winner is game.players[0]

        # A legal stroke removes no штрафной шар and respots nothing.
        assert system.balls["1"].state.s == const.pocketed
        assert system.balls["2"].state.s == const.stationary

    def test_foul_at_target_score_ends_game_without_penalty(self) -> None:
        # Opponent sits at 7; any foul hands them the winning point.
        system = _make_system(keep=("cue", "1", "2", "3"))
        for ball_id in ("1", "2", "3"):
            system.balls[ball_id].state.rvw[0] = [
                0.9,
                1.85,
                system.balls[ball_id].params.R,
            ]

        game = _make_game(shot_number=3)
        game.score = Counter({"B": rp.FREE_TARGET_SCORE - 1})
        game.shot_info = game.build_shot_info(system)  # no events -> foul
        game.respot_balls(system)

        info = game.shot_info
        assert not info.legal
        assert info.score == Counter({"B": rp.FREE_TARGET_SCORE})
        assert info.game_over and info.winner is game.players[1]

        # Game over: the штрафной шар is NOT removed from the table.
        for ball_id in ("1", "2", "3"):
            assert system.balls[ball_id].state.s == const.stationary


class TestFreePyramidRealShots:
    """Full-physics scenarios (slow but faithful to the real engine)."""

    def test_scratch_without_contact_is_a_foul(self) -> None:
        # Cue ball driven dead-straight into the right middle pocket,
        # contacting no object ball: NO_CONTACT foul with full administration.
        system = _make_system()
        system.balls[rp.CUE_BALL_ID].state.rvw[0] = [
            system.table.w / 2,
            system.table.l / 2,
            system.balls[rp.CUE_BALL_ID].params.R,
        ]
        _seed_histories(system.balls)
        system.cue.set_state(V0=4.0, phi=0.0)
        pt.simulate(system, inplace=True)

        assert rp.is_cue_ball_potted(system)
        assert rp.first_object_contact(system) is None

        # Snapshot live object balls: the штрафной шар must be the live ball
        # closest to any pocket center (ties -> lowest number).
        live = sorted(
            (
                ball.id
                for ball in system.balls.values()
                if ball.id != rp.CUE_BALL_ID and ball.state.s in const.on_table
            ),
            key=int,
        )
        assert len(live) == 15
        expected_removed = min(
            live, key=lambda bid: _dist_to_nearest_pocket_sq(system, bid)
        )

        game = _make_game()
        game.process_and_advance(system)

        info = game.shot_info
        assert not info.legal and info.reason == rp.FreePyramidReason.NO_CONTACT
        assert info.turn_over and not info.game_over
        assert game.score == Counter({"B": 1})

        # Scratch: cue ball re-introduced at the default house spot.
        cue = system.balls[rp.CUE_BALL_ID]
        assert cue.state.s == const.stationary
        assert cue.xyz[0] == pytest.approx(system.table.w / 2)
        assert cue.xyz[1] == pytest.approx(rp.HOUSE_DEFAULT_Y_FRACTION * system.table.l)

        # Штрафной шар: exactly the policy-chosen ball was removed.
        removed = [
            ball.id
            for ball in system.balls.values()
            if ball.id != rp.CUE_BALL_ID and ball.state.s == const.pocketed
        ]
        assert removed == [expected_removed]

        # Incoming player: ball-in-hand behind the house line, the removed
        # ball is no longer hittable.
        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.BEHIND_LINE
        assert c.movable == [rp.CUE_BALL_ID] and c.cueable == [rp.CUE_BALL_ID]
        assert set(c.hittable) == set(live) - {expected_removed}
        assert game.turn_number == 1 and game.active_idx == 1

    def test_svoyak_straight_pot_scores_two_and_respots_cue(self) -> None:
        # Dead-straight pot: the object ball drops and the cue ball follows
        # it in («свояк») — legal stroke worth two points.
        system = _make_system(keep=("cue", "1", "2"), positions={"2": (0.5, 1.0)})
        table = system.table
        px, py = (float(v) for v in table.pockets["rc"].center[:2])
        direction = np.array([table.w / 2 - px, table.l / 2 - py])
        direction /= np.linalg.norm(direction)
        balls = system.balls
        R = balls["1"].params.R
        balls["1"].state.rvw[0] = [
            px + 0.45 * direction[0],
            py + 0.45 * direction[1],
            R,
        ]
        balls[rp.CUE_BALL_ID].state.rvw[0] = [
            px + 0.90 * direction[0],
            py + 0.90 * direction[1],
            R,
        ]
        _seed_histories(balls)
        system.cue.set_state(
            V0=3.5,
            phi=math.degrees(
                math.atan2(
                    py - balls[rp.CUE_BALL_ID].state.rvw[0, 1],
                    px - balls[rp.CUE_BALL_ID].state.rvw[0, 0],
                )
            ),
        )
        pt.simulate(system, inplace=True)

        assert rp.potted_ball_ids(system) == ["1", rp.CUE_BALL_ID]
        assert rp.first_object_contact(system) == "1"

        game = _make_game(shot_number=3)
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.FreePyramidReason.LEGAL
        # Object ball + свояк = two points; shooter continues.
        assert game.score == Counter({"A": 2})
        assert not info.turn_over and not info.game_over

        # The cue ball was respotted on the (now free) задняя отметка.
        cue = balls[rp.CUE_BALL_ID]
        assert cue.state.s == const.stationary
        assert cue.xyz[0] == pytest.approx(table.w / 2)
        assert cue.xyz[1] == pytest.approx(rp.REAR_SPOT_FRACTION * table.l)
        assert game.shot_constraints.hittable == ("2",)

    def test_completion_via_two_cushions_passes_turn(self) -> None:
        # п. 20 clause 2a: after cue-object contact the struck ball touches
        # two distinct cushions; nothing is potted, so the turn passes 0-0.
        system = _make_system(
            keep=("cue", "1", "2"),
            positions={
                "1": (0.90, 2.775),
                "2": (0.60, 1.50),
                rp.CUE_BALL_ID: (0.90, 0.90),
            },
        )
        system.cue.set_state(V0=4.0, phi=pt.aim.at_ball(system, "2"))
        pt.simulate(system, inplace=True)

        assert rp.potted_ball_ids(system) == []
        assert not rp.is_cue_ball_potted(system)
        legal, reason = rp.evaluate_free_shot(system, is_break=False)
        assert legal and reason == rp.FreePyramidReason.LEGAL

        game = _make_game(shot_number=3)
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.FreePyramidReason.LEGAL
        assert game.score == Counter()
        assert info.turn_over and not info.game_over

        # The opponent plays the table as it lies.
        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.NONE and c.movable == []
        assert c.hittable == ("1", "2")
        assert game.turn_number == 1 and game.active_idx == 1


class TestFreePyramidRespot:
    """п. 25 spotting-line respots and п. 22 foul administration."""

    def test_foul_respots_potted_balls_and_takes_penalty_ball(self) -> None:
        # Foul (no contact) with two illegally potted balls: both return to
        # the spotting line in ascending order, then the штрафной шар is
        # taken from the remaining live balls.
        system = _make_system(
            keep=("cue", "3", "4", "5"),
            positions={"5": (0.9, 1.85)},
        )
        _mark_pocketed(system, "3", "rb", t=0.4)
        _mark_pocketed(system, "4", "rt", t=0.5)

        game = _make_game(shot_number=3)
        game.process_and_advance(system)

        assert not game.shot_info.legal
        assert game.score == Counter({"B": 1})

        mark = (system.table.w / 2, rp.REAR_SPOT_FRACTION * system.table.l)
        step = 2 * system.balls["3"].params.R + rp._RESPOT_GAP
        # First respotted ball lands exactly on the задняя отметка...
        assert system.balls["3"].state.s == const.stationary
        assert system.balls["3"].xyz[0] == pytest.approx(mark[0])
        assert system.balls["3"].xyz[1] == pytest.approx(mark[1])
        # ...the second one diameter behind it toward the rear rail.
        assert system.balls["4"].state.s == const.stationary
        assert system.balls["4"].xyz[1] == pytest.approx(mark[1] + step)

        # Penalty: the live ball closest to a pocket ("5" at the center) is
        # removed; the respotted balls stay on the table.
        assert system.balls["5"].state.s == const.pocketed
        pocket = rp.nearest_pocket(system.table, (0.9, 1.85))
        assert system.balls["5"].xyz[0] == pytest.approx(float(pocket.center[0]))
        assert system.balls["5"].xyz[1] == pytest.approx(float(pocket.center[1]))

        c = game.shot_constraints
        assert set(c.hittable) == {"3", "4"}

    def test_cue_ball_jump_places_cue_in_house_with_behind_line(self) -> None:
        system = _make_system(
            keep=("cue", "1", "2"),
            positions={"1": (0.5, 1.0), "2": (0.9, 1.85)},
        )
        system.events.append(_contact_event(t=0.2))
        _mark_off_table(system, rp.CUE_BALL_ID, t=0.6)

        game = _make_game(shot_number=3)
        game.process_and_advance(system)

        info = game.shot_info
        assert not info.legal and info.reason == rp.FreePyramidReason.JUMPED_BALL
        assert rp.is_cue_ball_jumped(system)
        assert game.score == Counter({"B": 1})
        assert info.turn_over and not info.game_over

        # Jumped cue ball on a foul: deterministic house placement.
        cue = system.balls[rp.CUE_BALL_ID]
        assert cue.state.s == const.stationary
        assert cue.xyz[0] == pytest.approx(system.table.w / 2)
        assert cue.xyz[1] == pytest.approx(rp.HOUSE_DEFAULT_Y_FRACTION * system.table.l)
        assert cue.history[-1].s == const.stationary

        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.BEHIND_LINE
        assert c.movable == [rp.CUE_BALL_ID]

    def test_copy_is_independent(self) -> None:
        game = rp.RussianFreePyramid(players=[Player("A"), Player("B")])
        game.score = Counter({"A": 3, "B": 5})
        game.shot_number = 4
        game.turn_number = 7
        game.active_idx = 1
        game.shot_constraints = game.initial_shot_constraints()
        game.shot_info = ShotInfo(
            player=game.players[1],
            legal=False,
            reason=rp.FreePyramidReason.NO_CONTACT,
            turn_over=True,
            game_over=False,
            winner=None,
            score=Counter({"A": 3, "B": 5}),
        )
        game.log.add_msg("hello")

        clone = game.copy()

        assert isinstance(clone, rp.RussianFreePyramid)
        assert clone.score == game.score and clone.score is not game.score
        assert (clone.shot_number, clone.turn_number, clone.active_idx) == (4, 7, 1)
        assert clone.shot_constraints == game.shot_constraints
        assert clone.shot_constraints.movable is not game.shot_constraints.movable
        assert clone.shot_info == game.shot_info
        assert clone.shot_info.score is not game.shot_info.score
        assert clone.players is game.players
        assert clone.log is not game.log and len(clone.log.msgs) == 1

        # Mutating the copy must not leak into the original.
        clone.score["A"] += 10
        assert game.score["A"] == 3
        clone.shot_constraints.movable.append(rp.CUE_BALL_ID + "x")
        assert game.shot_constraints.movable == [rp.CUE_BALL_ID]
        clone.shot_info.score["B"] += 10
        assert game.shot_info.score["B"] == 5
        clone.log.add_msg("mutated")
        assert len(game.log.msgs) == 1

        # A fresh game (no shot_info yet) copies cleanly.
        fresh = rp.RussianFreePyramid(players=[Player("X"), Player("Y")])
        fresh_copy = fresh.copy()
        assert not hasattr(fresh_copy, "shot_info")
        assert fresh_copy.score == Counter()


# ---------------------------------------------------------------------------
# Step 7: Combined Pyramid («Комбинированная пирамида») scenario tests
# ---------------------------------------------------------------------------
#
# The Combined («Московская») discipline shares the general-pyramid
# machinery (п. 12 break, п. 20 completion, п. 25 respots, foul penalties)
# and differs in «свояк» administration: the shooter removes one object
# ball to their shelf and re-enters the cue ball from the house (п. 21),
# where the first contact must lie outside the house.


class TestCombinedPyramidBreak:
    def test_break_constraints_grant_house_ball_in_hand(self) -> None:
        game = rp.RussianCombinedPyramid(players=[Player("A"), Player("B")])
        c0 = game.initial_shot_constraints()

        assert c0.ball_in_hand == BallInHandOptions.BEHIND_LINE
        assert c0.movable == [rp.CUE_BALL_ID]
        assert c0.cueable == [rp.CUE_BALL_ID]
        assert c0.hittable == tuple(str(i) for i in range(1, 16))
        assert c0.call_shot is False
        assert c0.can_shoot()
        assert game.shot_constraints == c0

    def test_real_break_is_legal_and_scores(self) -> None:
        system = _make_system()
        apex = min(
            (b for b in system.balls.values() if b.id != rp.CUE_BALL_ID),
            key=lambda b: (
                float(b.state.rvw[0, 0]) ** 2
                + (float(b.state.rvw[0, 1]) - rp.REAR_SPOT_FRACTION * system.table.l)
                ** 2
            ),
        )
        system.cue.set_state(V0=9.0, phi=pt.aim.at_ball(system, apex.id))
        pt.simulate(system, inplace=True)

        assert rp.first_object_contact(system) is not None
        potted_objects = rp.potted_object_ball_ids(system)
        svojak = rp.is_cue_ball_potted(system)

        game = rp.RussianCombinedPyramid(players=[Player("A"), Player("B")])
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.CombinedPyramidReason.LEGAL_BREAK
        # Potted object balls score directly; a «свояк» on the break scores
        # via the compensation ball removed to the shooter's shelf (п. 5.2).
        assert game.score["A"] == len(potted_objects) + int(svojak)
        assert info.turn_over == (not potted_objects and not svojak)
        assert game.shot_number == 1
        if svojak:
            # Premium stroke from the house after the «свояк» (п. 21).
            assert game.shot_constraints.ball_in_hand == BallInHandOptions.BEHIND_LINE
            assert game.shot_constraints.movable == [rp.CUE_BALL_ID]
        elif info.turn_over:
            assert game.active_idx == 1
            assert game.shot_constraints.ball_in_hand == BallInHandOptions.NONE


class TestCombinedPyramidLegality:
    """Synthetic event-based legality judgments (fast, deterministic)."""

    def test_no_contact_and_jumped_ball_foul(self) -> None:
        system = _make_system(keep=("cue", "1"))
        game = _make_game(shot_number=3, game_cls=rp.RussianCombinedPyramid)
        info = game.build_shot_info(system)
        assert not info.legal
        assert info.reason == rp.CombinedPyramidReason.NO_CONTACT
        assert info.score == Counter({"B": 1})
        assert info.turn_over and not info.game_over

        jumped = _make_system(keep=("cue", "1"))
        jumped.events.append(_contact_event(t=0.2))
        _mark_off_table(jumped, "1", t=0.6)
        legal, reason = rp.evaluate_combined_shot(jumped, is_break=False)
        assert not legal and reason == rp.CombinedPyramidReason.JUMPED_BALL

    def test_house_stroke_contacting_inside_ball_is_a_foul(self) -> None:
        # The cue ball stands in the house (rack spawn y = 0.851 < 0.25·l);
        # the first ball contacted also stands inside the house: п. 21 foul.
        system = _make_system(
            keep=("cue", "1", "2"), positions={"1": (0.9, 0.5), "2": (0.5, 1.5)}
        )
        system.events.append(_contact_event(t=0.2))
        _touch_row(system, "1", t=0.2)

        assert rp.violates_house_contact(system)
        legal, reason = rp.evaluate_combined_shot(system, is_break=False)
        assert not legal and reason == rp.CombinedPyramidReason.HOUSE_FIRST_CONTACT

        game = _make_game(shot_number=3, game_cls=rp.RussianCombinedPyramid)
        info = game.build_shot_info(system)
        assert not info.legal and info.turn_over
        assert info.score == Counter({"B": 1})

    def test_house_stroke_with_outside_contact_completes_legally(self) -> None:
        # Same house stroke, but the first-contacted ball stands outside the
        # house; the stroke then completes per п. 20 clause 2a (two
        # distinct cushions) and is legal.
        system = _make_system(
            keep=("cue", "1", "2"), positions={"1": (0.9, 1.5), "2": (0.5, 2.5)}
        )
        system.events.append(_contact_event(t=0.2))
        _touch_row(system, "1", t=0.2)
        system.events.append(_cushion_event("1", "l1", 0.3))
        system.events.append(_cushion_event("1", "l2", 0.4))

        assert not rp.violates_house_contact(system)
        legal, reason = rp.evaluate_combined_shot(system, is_break=False)
        assert legal and reason == rp.CombinedPyramidReason.LEGAL

        game = _make_game(shot_number=3, game_cls=rp.RussianCombinedPyramid)
        game.process_and_advance(system)
        assert game.score == Counter()
        # Nothing potted -> the turn passes, opponent plays as it lies.
        assert game.shot_info.turn_over
        assert game.shot_constraints.ball_in_hand == BallInHandOptions.NONE
        assert game.shot_constraints.hittable == ("1", "2")

    def test_all_balls_in_house_lifts_house_restriction(self) -> None:
        # п. 21 exception: with every live object ball inside the house the
        # stroke is played from the opposite side — contacting an inside
        # ball is not the п. 21 violation (here the stroke instead fails
        # ordinary completion).
        system = _make_system(
            keep=("cue", "1", "2"), positions={"1": (0.9, 0.5), "2": (0.5, 0.6)}
        )
        system.events.append(_contact_event(t=0.2))
        _touch_row(system, "1", t=0.2)

        assert not rp.violates_house_contact(system)
        legal, reason = rp.evaluate_combined_shot(system, is_break=False)
        assert not legal
        assert reason == rp.CombinedPyramidReason.ILLEGAL_COMPLETION


class TestCombinedPyramidScoring:
    """«Свояк» compensation, direct pots, and foul penalties."""

    _POSITIONS: ClassVar[dict[str, tuple[float, float]]] = {
        "1": (0.5, 1.0),
        "2": (0.9, 1.85),
        "3": (0.5, 2.5),
    }

    def test_object_pot_scores_and_continues_from_position(self) -> None:
        system = _make_system(keep=("cue", "1", "2", "3"), positions=self._POSITIONS)
        system.events.append(_contact_event(t=0.2))
        _mark_pocketed(system, "1", "rb", t=0.4)

        game = _make_game(shot_number=3, game_cls=rp.RussianCombinedPyramid)
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.CombinedPyramidReason.LEGAL
        assert game.score == Counter({"A": 1})
        assert not info.turn_over and not info.game_over

        # No «свояк»: no compensation ball is removed, the shooter simply
        # continues from the resulting position.
        assert system.balls["2"].state.s == const.stationary
        assert system.balls["3"].state.s == const.stationary
        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.NONE and c.movable == []
        assert c.hittable == ("2", "3")

    def test_svoyak_removes_ball_and_grants_house_stroke(self) -> None:
        system = _make_system(keep=("cue", "1", "2", "3"), positions=self._POSITIONS)
        live = ("1", "2", "3")
        expected_removed = min(
            live, key=lambda bid: _dist_to_nearest_pocket_sq(system, bid)
        )
        system.events.append(_contact_event(t=0.2))
        _mark_pocketed(system, rp.CUE_BALL_ID, "rc", t=0.5)

        game = _make_game(shot_number=3, game_cls=rp.RussianCombinedPyramid)
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.CombinedPyramidReason.LEGAL
        # The «свояк» point is embodied by the removed object ball (п. 5.2).
        assert game.score == Counter({"A": 1})
        assert not info.turn_over

        removed = [
            ball_id
            for ball_id in live
            if system.balls[ball_id].state.s == const.pocketed
        ]
        assert removed == [expected_removed]

        # The cue ball re-enters from the house (п. 21 premium stroke).
        cue = system.balls[rp.CUE_BALL_ID]
        assert cue.state.s == const.stationary
        assert cue.xyz[0] == pytest.approx(system.table.w / 2)
        assert cue.xyz[1] == pytest.approx(rp.HOUSE_DEFAULT_Y_FRACTION * system.table.l)
        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.BEHIND_LINE
        assert c.movable == [rp.CUE_BALL_ID]
        assert set(c.hittable) == set(live) - {expected_removed}

    def test_svoyak_with_object_pot_scores_two(self) -> None:
        system = _make_system(keep=("cue", "1", "2", "3"), positions=self._POSITIONS)
        live = ("2", "3")  # ball "1" is potted by the stroke itself
        expected_removed = min(
            live, key=lambda bid: _dist_to_nearest_pocket_sq(system, bid)
        )
        system.events.append(_contact_event(t=0.2))
        _mark_pocketed(system, "1", "rb", t=0.4)
        _mark_pocketed(system, rp.CUE_BALL_ID, "rc", t=0.5)

        game = _make_game(shot_number=3, game_cls=rp.RussianCombinedPyramid)
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.CombinedPyramidReason.LEGAL
        # Object ball (direct) + «свояк» (compensation ball) = two points.
        assert game.score == Counter({"A": 2})
        assert not info.turn_over
        assert system.balls[expected_removed].state.s == const.pocketed
        assert game.shot_constraints.ball_in_hand == BallInHandOptions.BEHIND_LINE
        assert set(game.shot_constraints.hittable) == set(live) - {expected_removed}

    def test_foul_takes_penalty_and_passes_turn(self) -> None:
        system = _make_system(
            keep=("cue", "1", "2"), positions={"1": (0.5, 1.0), "2": (0.9, 1.85)}
        )
        live = ("1", "2")
        expected_removed = min(
            live, key=lambda bid: _dist_to_nearest_pocket_sq(system, bid)
        )

        game = _make_game(shot_number=3, game_cls=rp.RussianCombinedPyramid)
        game.process_and_advance(system)

        info = game.shot_info
        assert not info.legal and info.reason == rp.CombinedPyramidReason.NO_CONTACT
        assert game.score == Counter({"B": 1})
        assert info.turn_over and not info.game_over
        assert game.turn_number == 1 and game.active_idx == 1

        # «Штрафной шар» to the opponent's shelf; no scratch -> no
        # ball-in-hand privilege.
        assert system.balls[expected_removed].state.s == const.pocketed
        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.NONE and c.movable == []
        assert set(c.hittable) == set(live) - {expected_removed}


class TestCombinedPyramidEndgame:
    def test_reaching_target_score_ends_game(self) -> None:
        system = _make_system(
            keep=("cue", "1", "2"), positions={"1": (0.5, 1.0), "2": (0.9, 1.85)}
        )
        system.events.append(_contact_event(t=0.2))
        _mark_pocketed(system, "1", "rb", t=0.4)

        game = _make_game(shot_number=3, game_cls=rp.RussianCombinedPyramid)
        game.score = Counter({"A": rp.COMBINED_TARGET_SCORE - 1})
        game.shot_info = game.build_shot_info(system)
        game.respot_balls(system)

        info = game.shot_info
        assert info.legal
        assert info.score == Counter({"A": rp.COMBINED_TARGET_SCORE})
        assert info.game_over and info.winner is game.players[0]

        # Legal stroke without a «свояк»: no respots, no shelf balls taken.
        assert system.balls["1"].state.s == const.pocketed
        assert system.balls["2"].state.s == const.stationary

    def test_foul_at_target_score_ends_game_without_penalty(self) -> None:
        system = _make_system(
            keep=("cue", "1", "2"), positions={"1": (0.5, 1.0), "2": (0.9, 1.85)}
        )

        game = _make_game(shot_number=3, game_cls=rp.RussianCombinedPyramid)
        game.score = Counter({"B": rp.COMBINED_TARGET_SCORE - 1})
        game.shot_info = game.build_shot_info(system)  # no events -> foul
        game.respot_balls(system)

        info = game.shot_info
        assert not info.legal
        assert info.score == Counter({"B": rp.COMBINED_TARGET_SCORE})
        assert info.game_over and info.winner is game.players[1]

        # Game over: the «штрафной шар» is NOT removed from the table.
        assert system.balls["1"].state.s == const.stationary
        assert system.balls["2"].state.s == const.stationary

    def test_copy_is_independent(self) -> None:
        game = rp.RussianCombinedPyramid(players=[Player("A"), Player("B")])
        game.score = Counter({"A": 3, "B": 5})
        game.shot_number = 4
        game.turn_number = 7
        game.active_idx = 1
        game.shot_constraints = game.initial_shot_constraints()
        game.shot_info = ShotInfo(
            player=game.players[1],
            legal=False,
            reason=rp.CombinedPyramidReason.NO_CONTACT,
            turn_over=True,
            game_over=False,
            winner=None,
            score=Counter({"A": 3, "B": 5}),
        )
        game.log.add_msg("hello")

        clone = game.copy()

        assert isinstance(clone, rp.RussianCombinedPyramid)
        assert clone.score == game.score and clone.score is not game.score
        assert (clone.shot_number, clone.turn_number, clone.active_idx) == (4, 7, 1)
        assert clone.shot_constraints == game.shot_constraints
        assert clone.shot_constraints.movable is not game.shot_constraints.movable
        assert clone.shot_info == game.shot_info
        assert clone.shot_info.score is not game.shot_info.score
        assert clone.players is game.players
        assert clone.log is not game.log and len(clone.log.msgs) == 1

        clone.score["A"] += 10
        assert game.score["A"] == 3
        clone.shot_constraints.movable.append(rp.CUE_BALL_ID + "x")
        assert game.shot_constraints.movable == [rp.CUE_BALL_ID]
        clone.log.add_msg("mutated")
        assert len(game.log.msgs) == 1


class TestCombinedPyramidRealShots:
    """Full-physics scenarios (slow but faithful to the real engine)."""

    def test_svoyak_straight_pot_scores_two_and_removes_ball(self) -> None:
        # Dead-straight pot: the object ball drops and the cue ball follows
        # it in («свояк») — two points (direct pot + compensation ball),
        # one ball off the table, cue ball re-entered from the house.
        system = _make_system(
            keep=("cue", "1", "2", "3"),
            positions={"2": (0.9, 2.3), "3": (0.9, 2.5)},
        )
        table = system.table
        px, py = (float(v) for v in table.pockets["rc"].center[:2])
        direction = np.array([table.w / 2 - px, table.l / 2 - py])
        direction /= np.linalg.norm(direction)
        balls = system.balls
        R = balls["1"].params.R
        balls["1"].state.rvw[0] = [
            px + 0.45 * direction[0],
            py + 0.45 * direction[1],
            R,
        ]
        balls[rp.CUE_BALL_ID].state.rvw[0] = [
            px + 0.90 * direction[0],
            py + 0.90 * direction[1],
            R,
        ]
        _seed_histories(balls)
        system.cue.set_state(
            V0=3.5,
            phi=math.degrees(
                math.atan2(
                    py - balls[rp.CUE_BALL_ID].state.rvw[0, 1],
                    px - balls[rp.CUE_BALL_ID].state.rvw[0, 0],
                )
            ),
        )
        pt.simulate(system, inplace=True)

        assert rp.potted_ball_ids(system) == ["1", rp.CUE_BALL_ID]
        assert rp.first_object_contact(system) == "1"

        live = ("2", "3")
        expected_removed = min(
            live, key=lambda bid: _dist_to_nearest_pocket_sq(system, bid)
        )

        game = _make_game(shot_number=3, game_cls=rp.RussianCombinedPyramid)
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.CombinedPyramidReason.LEGAL
        assert game.score == Counter({"A": 2})
        assert not info.turn_over and not info.game_over

        assert system.balls[expected_removed].state.s == const.pocketed
        cue = balls[rp.CUE_BALL_ID]
        assert cue.state.s == const.stationary
        assert cue.xyz[0] == pytest.approx(table.w / 2)
        assert cue.xyz[1] == pytest.approx(rp.HOUSE_DEFAULT_Y_FRACTION * table.l)
        assert game.shot_constraints.ball_in_hand == BallInHandOptions.BEHIND_LINE
        assert set(game.shot_constraints.hittable) == set(live) - {expected_removed}

    def test_scratch_without_contact_is_a_foul(self) -> None:
        # Cue ball driven dead-straight into the right middle pocket,
        # contacting no object ball: NO_CONTACT foul with full administration.
        system = _make_system()
        system.balls[rp.CUE_BALL_ID].state.rvw[0] = [
            system.table.w / 2,
            system.table.l / 2,
            system.balls[rp.CUE_BALL_ID].params.R,
        ]
        _seed_histories(system.balls)
        system.cue.set_state(V0=4.0, phi=0.0)
        pt.simulate(system, inplace=True)

        assert rp.is_cue_ball_potted(system)
        assert rp.first_object_contact(system) is None

        live = sorted(
            (
                ball.id
                for ball in system.balls.values()
                if ball.id != rp.CUE_BALL_ID and ball.state.s in const.on_table
            ),
            key=int,
        )
        assert len(live) == 15
        expected_removed = min(
            live, key=lambda bid: _dist_to_nearest_pocket_sq(system, bid)
        )

        game = rp.RussianCombinedPyramid(players=[Player("A"), Player("B")])
        game.process_and_advance(system)

        info = game.shot_info
        assert not info.legal and info.reason == rp.CombinedPyramidReason.NO_CONTACT
        assert info.turn_over and not info.game_over
        assert game.score == Counter({"B": 1})

        # Penalty stroke from the house (п. 7/п. 21).
        cue = system.balls[rp.CUE_BALL_ID]
        assert cue.state.s == const.stationary
        assert cue.xyz[0] == pytest.approx(system.table.w / 2)
        assert cue.xyz[1] == pytest.approx(rp.HOUSE_DEFAULT_Y_FRACTION * system.table.l)
        removed = [
            ball.id
            for ball in system.balls.values()
            if ball.id != rp.CUE_BALL_ID and ball.state.s == const.pocketed
        ]
        assert removed == [expected_removed]

        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.BEHIND_LINE
        assert c.movable == [rp.CUE_BALL_ID] and c.cueable == [rp.CUE_BALL_ID]
        assert set(c.hittable) == set(live) - {expected_removed}
        assert game.turn_number == 1 and game.active_idx == 1


# ---------------------------------------------------------------------------
# Step 8: Dynamic Pyramid («Динамичная пирамида» / «Невская») scenario tests
# ---------------------------------------------------------------------------
#
# The Dynamic («Невская») discipline shares the general-pyramid machinery
# (п. 12 break, п. 20 completion, п. 25 respots, foul penalties) and differs
# in cue-ball administration: after a legal «свояк» the shooter removes one
# object ball to their shelf and re-introduces the cue ball with ball in hand
# from any point of the table (п. 6.1), on which only object balls may be
# pocketed (п. 6.4/6.5); the same table-wide ball-in-hand is granted to the
# opponent after a fouled scratch (п. 7.2a).


def _dist_sq(table: Table, xy: tuple[float, float]) -> float:
    """Squared distance from ``(x, y)`` to the nearest pocket center."""
    pocket = rp.nearest_pocket(table, xy)
    return (xy[0] - float(pocket.center[0])) ** 2 + (
        xy[1] - float(pocket.center[1])
    ) ** 2


def _in_hand_constraints(hittable: tuple[str, ...] | None = None) -> ShotConstraints:
    """Table-wide ball-in-hand constraints (п. 6.1 introduction stroke)."""
    return ShotConstraints(
        ball_in_hand=BallInHandOptions.ANYWHERE,
        movable=[rp.CUE_BALL_ID],
        cueable=[rp.CUE_BALL_ID],
        hittable=(
            hittable if hittable is not None else tuple(str(i) for i in range(1, 16))
        ),
        call_shot=False,
    )


class TestDynamicPyramidBreak:
    def test_break_constraints_grant_house_ball_in_hand(self) -> None:
        game = rp.RussianDynamicPyramid(players=[Player("A"), Player("B")])
        c0 = game.initial_shot_constraints()

        assert c0.ball_in_hand == BallInHandOptions.BEHIND_LINE
        assert c0.movable == [rp.CUE_BALL_ID]
        assert c0.cueable == [rp.CUE_BALL_ID]
        assert c0.hittable == tuple(str(i) for i in range(1, 16))
        assert c0.call_shot is False
        assert c0.can_shoot()
        assert game.shot_constraints == c0

    def test_real_break_is_legal_and_scores(self) -> None:
        system = _make_system()
        apex = min(
            (b for b in system.balls.values() if b.id != rp.CUE_BALL_ID),
            key=lambda b: (
                float(b.state.rvw[0, 0]) ** 2
                + (float(b.state.rvw[0, 1]) - rp.REAR_SPOT_FRACTION * system.table.l)
                ** 2
            ),
        )
        system.cue.set_state(V0=9.0, phi=pt.aim.at_ball(system, apex.id))
        pt.simulate(system, inplace=True)

        assert rp.first_object_contact(system) is not None
        potted_objects = rp.potted_object_ball_ids(system)
        svojak = rp.is_cue_ball_potted(system)

        game = rp.RussianDynamicPyramid(players=[Player("A"), Player("B")])
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.DynamicPyramidReason.LEGAL_BREAK
        # Potted object balls score directly; a «свояк» on the break scores
        # via the compensation ball removed to the shooter's shelf (п. 5.2).
        assert game.score["A"] == len(potted_objects) + int(svojak)
        assert info.turn_over == (not potted_objects and not svojak)
        assert game.shot_number == 1
        if svojak:
            # Table-wide ball-in-hand introduction stroke after the «свояк»
            # (п. 6.1) — the Dynamic signature, vs the house stroke of Combined.
            assert game.shot_constraints.ball_in_hand == BallInHandOptions.ANYWHERE
            assert game.shot_constraints.movable == [rp.CUE_BALL_ID]
        elif info.turn_over:
            assert game.active_idx == 1
            assert game.shot_constraints.ball_in_hand == BallInHandOptions.NONE


class TestDynamicPyramidLegality:
    """Synthetic event-based legality judgments (fast, deterministic)."""

    _POSITIONS: ClassVar[dict[str, tuple[float, float]]] = {
        "1": (0.5, 1.0),
        "2": (0.9, 1.85),
        "3": (0.5, 2.5),
    }

    def test_no_contact_and_jumped_ball_foul(self) -> None:
        system = _make_system(keep=("cue", "1"))
        game = _make_game(shot_number=3, game_cls=rp.RussianDynamicPyramid)
        info = game.build_shot_info(system)
        assert not info.legal
        assert info.reason == rp.DynamicPyramidReason.NO_CONTACT
        assert info.score == Counter({"B": 1})
        assert info.turn_over and not info.game_over

        jumped = _make_system(keep=("cue", "1"))
        jumped.events.append(_contact_event(t=0.2))
        _mark_off_table(jumped, "1", t=0.6)
        legal, reason = rp.evaluate_dynamic_shot(
            jumped, is_break=False, is_in_hand=False
        )
        assert not legal and reason == rp.DynamicPyramidReason.JUMPED_BALL

    def test_in_hand_stroke_pocketing_cue_ball_is_a_foul(self) -> None:
        # п. 6.4/6.5: on an introduction stroke («удар с руки», ball in hand
        # anywhere) the cue ball may not be pocketed — even though the stroke
        # contacted an object ball and would complete per п. 20.
        system = _make_system(keep=("cue", "1", "2", "3"), positions=self._POSITIONS)
        system.events.append(_contact_event(t=0.2))
        system.events.append(_cushion_event("1", "l1", t=0.3))
        system.events.append(_cushion_event("1", "l2", t=0.4))
        _mark_pocketed(system, rp.CUE_BALL_ID, "rc", t=0.5)

        # The same stroke judged without ball in hand would be a legal
        # «свояк»; the in-hand flag flips the verdict.
        legal, reason = rp.evaluate_dynamic_shot(
            system, is_break=False, is_in_hand=False
        )
        assert legal and reason == rp.DynamicPyramidReason.LEGAL
        legal, reason = rp.evaluate_dynamic_shot(
            system, is_break=False, is_in_hand=True
        )
        assert not legal and reason == rp.DynamicPyramidReason.IN_HAND_CUE_POT

        game = _make_game(shot_number=3, game_cls=rp.RussianDynamicPyramid)
        game.shot_constraints = _in_hand_constraints()
        game.process_and_advance(system)

        info = game.shot_info
        assert not info.legal
        assert info.reason == rp.DynamicPyramidReason.IN_HAND_CUE_POT
        assert info.score == Counter({"B": 1})
        assert info.turn_over and not info.game_over

        # Foul scratch: the opponent re-introduces the cue ball from anywhere
        # (п. 7.2a) — placed at the deterministic default position.
        cue = system.balls[rp.CUE_BALL_ID]
        assert cue.state.s == const.stationary
        assert cue.xyz[0] == pytest.approx(system.table.w / 2)
        assert cue.xyz[1] == pytest.approx(rp.HOUSE_DEFAULT_Y_FRACTION * system.table.l)
        live = ("1", "2", "3")
        expected_removed = min(
            live, key=lambda bid: _dist_to_nearest_pocket_sq(system, bid)
        )
        removed = [bid for bid in live if system.balls[bid].state.s == const.pocketed]
        assert removed == [expected_removed]

        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.ANYWHERE
        assert c.movable == [rp.CUE_BALL_ID]
        assert set(c.hittable) == set(live) - {expected_removed}

    def test_in_hand_stroke_pocketing_object_ball_is_legal(self) -> None:
        # п. 6.4: on an introduction stroke object balls may be pocketed —
        # they score, and the shooter continues from the resulting position.
        system = _make_system(keep=("cue", "1", "2", "3"), positions=self._POSITIONS)
        system.events.append(_contact_event(t=0.2))
        _mark_pocketed(system, "1", "rb", t=0.4)

        game = _make_game(shot_number=3, game_cls=rp.RussianDynamicPyramid)
        game.shot_constraints = _in_hand_constraints()
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.DynamicPyramidReason.LEGAL
        assert game.score == Counter({"A": 1})
        assert not info.turn_over and not info.game_over

        # Legally potted balls stay down; no shelf balls on a non-«свояк».
        assert system.balls["1"].state.s == const.pocketed
        assert system.balls["2"].state.s == const.stationary
        assert system.balls["3"].state.s == const.stationary
        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.NONE and c.movable == []
        assert c.hittable == ("2", "3")

    def test_in_hand_object_pot_alongside_cue_pot_not_counted(self) -> None:
        # п. 6.6: when an object ball falls alongside the cue ball on an
        # introduction stroke, it is not counted and is respotted per п. 25;
        # the stroke is a foul (штрафной шар, opponent ball in hand).
        system = _make_system(keep=("cue", "1", "2", "3"), positions=self._POSITIONS)
        system.events.append(_contact_event(t=0.2))
        _mark_pocketed(system, "1", "rb", t=0.4)
        _mark_pocketed(system, rp.CUE_BALL_ID, "rc", t=0.5)

        game = _make_game(shot_number=3, game_cls=rp.RussianDynamicPyramid)
        game.shot_constraints = _in_hand_constraints()
        game.process_and_advance(system)

        info = game.shot_info
        assert not info.legal
        assert info.reason == rp.DynamicPyramidReason.IN_HAND_CUE_POT
        # The shooter scores nothing; the opponent takes the foul point.
        assert info.score == Counter({"B": 1})
        assert info.turn_over

        # The illegally potted object ball is respotted onto the задняя
        # отметка (the mark is free here) before the штрафной шар is taken.
        table = system.table
        mark = (table.w / 2, rp.REAR_SPOT_FRACTION * table.l)
        assert system.balls["1"].state.s == const.stationary
        assert tuple(system.balls["1"].xyz[:2]) == pytest.approx(mark)

        final_pos: dict[str, tuple[float, float]] = {
            "1": mark,
            "2": self._POSITIONS["2"],
            "3": self._POSITIONS["3"],
        }
        expected_removed = min(
            ("1", "2", "3"), key=lambda bid: _dist_sq(table, final_pos[bid])
        )
        removed = [
            bid
            for bid in ("1", "2", "3")
            if system.balls[bid].state.s == const.pocketed
        ]
        assert removed == [expected_removed]


class TestDynamicPyramidScoring:
    """«Свояк» compensation, direct pots, and foul penalties."""

    _POSITIONS: ClassVar[dict[str, tuple[float, float]]] = {
        "1": (0.5, 1.0),
        "2": (0.9, 1.85),
        "3": (0.5, 2.5),
    }

    def test_object_pot_scores_and_continues_from_position(self) -> None:
        system = _make_system(keep=("cue", "1", "2", "3"), positions=self._POSITIONS)
        system.events.append(_contact_event(t=0.2))
        _mark_pocketed(system, "1", "rb", t=0.4)

        game = _make_game(shot_number=3, game_cls=rp.RussianDynamicPyramid)
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.DynamicPyramidReason.LEGAL
        assert game.score == Counter({"A": 1})
        assert not info.turn_over and not info.game_over

        # No «свояк»: no compensation ball is removed, the shooter simply
        # continues from the resulting position.
        assert system.balls["2"].state.s == const.stationary
        assert system.balls["3"].state.s == const.stationary
        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.NONE and c.movable == []
        assert c.hittable == ("2", "3")

    def test_svoyak_removes_ball_and_grants_table_wide_in_hand(self) -> None:
        system = _make_system(keep=("cue", "1", "2", "3"), positions=self._POSITIONS)
        live = ("1", "2", "3")
        expected_removed = min(
            live, key=lambda bid: _dist_to_nearest_pocket_sq(system, bid)
        )
        system.events.append(_contact_event(t=0.2))
        _mark_pocketed(system, rp.CUE_BALL_ID, "rc", t=0.5)

        game = _make_game(shot_number=3, game_cls=rp.RussianDynamicPyramid)
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.DynamicPyramidReason.LEGAL
        # The «свояк» point is embodied by the removed object ball (п. 5.2).
        assert game.score == Counter({"A": 1})
        assert not info.turn_over

        removed = [
            ball_id
            for ball_id in live
            if system.balls[ball_id].state.s == const.pocketed
        ]
        assert removed == [expected_removed]

        # The cue ball re-enters with ball in hand from anywhere (п. 6.1);
        # the deterministic default position is the break spawn point.
        cue = system.balls[rp.CUE_BALL_ID]
        assert cue.state.s == const.stationary
        assert cue.xyz[0] == pytest.approx(system.table.w / 2)
        assert cue.xyz[1] == pytest.approx(rp.HOUSE_DEFAULT_Y_FRACTION * system.table.l)
        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.ANYWHERE
        assert c.movable == [rp.CUE_BALL_ID]
        assert set(c.hittable) == set(live) - {expected_removed}

    def test_svoyak_with_object_pot_scores_two(self) -> None:
        system = _make_system(keep=("cue", "1", "2", "3"), positions=self._POSITIONS)
        live = ("2", "3")  # ball "1" is potted by the stroke itself
        expected_removed = min(
            live, key=lambda bid: _dist_to_nearest_pocket_sq(system, bid)
        )
        system.events.append(_contact_event(t=0.2))
        _mark_pocketed(system, "1", "rb", t=0.4)
        _mark_pocketed(system, rp.CUE_BALL_ID, "rc", t=0.5)

        game = _make_game(shot_number=3, game_cls=rp.RussianDynamicPyramid)
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.DynamicPyramidReason.LEGAL
        # Object ball (direct) + «свояк» (compensation ball) = two points.
        assert game.score == Counter({"A": 2})
        assert not info.turn_over
        assert system.balls[expected_removed].state.s == const.pocketed
        assert game.shot_constraints.ball_in_hand == BallInHandOptions.ANYWHERE
        assert set(game.shot_constraints.hittable) == set(live) - {expected_removed}

    def test_foul_with_cue_staying_grants_no_in_hand(self) -> None:
        # п. 7.3a: after a foul where the cue ball stayed on the table, the
        # opponent plays from where it lies (no ball-in-hand privilege).
        system = _make_system(
            keep=("cue", "1", "2"), positions={"1": (0.5, 1.0), "2": (0.9, 1.85)}
        )
        live = ("1", "2")
        expected_removed = min(
            live, key=lambda bid: _dist_to_nearest_pocket_sq(system, bid)
        )

        game = _make_game(shot_number=3, game_cls=rp.RussianDynamicPyramid)
        game.process_and_advance(system)

        info = game.shot_info
        assert not info.legal and info.reason == rp.DynamicPyramidReason.NO_CONTACT
        assert game.score == Counter({"B": 1})
        assert info.turn_over and not info.game_over
        assert game.turn_number == 1 and game.active_idx == 1

        # «Штрафной шар» to the opponent's shelf; the cue ball was not
        # potted/jumped -> no ball-in-hand privilege (п. 7.3a).
        assert system.balls[expected_removed].state.s == const.pocketed
        cue = system.balls[rp.CUE_BALL_ID]
        assert cue.state.s in const.on_table
        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.NONE and c.movable == []
        assert set(c.hittable) == set(live) - {expected_removed}


class TestDynamicPyramidEndgame:
    def test_reaching_target_score_ends_game(self) -> None:
        system = _make_system(
            keep=("cue", "1", "2"), positions={"1": (0.5, 1.0), "2": (0.9, 1.85)}
        )
        system.events.append(_contact_event(t=0.2))
        _mark_pocketed(system, "1", "rb", t=0.4)

        game = _make_game(shot_number=3, game_cls=rp.RussianDynamicPyramid)
        game.score = Counter({"A": rp.DYNAMIC_TARGET_SCORE - 1})
        game.shot_info = game.build_shot_info(system)
        game.respot_balls(system)

        info = game.shot_info
        assert info.legal
        assert info.score == Counter({"A": rp.DYNAMIC_TARGET_SCORE})
        assert info.game_over and info.winner is game.players[0]

        # Legal stroke without a «свояк»: no respots, no shelf balls taken.
        assert system.balls["1"].state.s == const.pocketed
        assert system.balls["2"].state.s == const.stationary

    def test_foul_at_target_score_ends_game_without_penalty(self) -> None:
        system = _make_system(
            keep=("cue", "1", "2"), positions={"1": (0.5, 1.0), "2": (0.9, 1.85)}
        )

        game = _make_game(shot_number=3, game_cls=rp.RussianDynamicPyramid)
        game.score = Counter({"B": rp.DYNAMIC_TARGET_SCORE - 1})
        game.shot_info = game.build_shot_info(system)  # no events -> foul
        game.respot_balls(system)

        info = game.shot_info
        assert not info.legal
        assert info.score == Counter({"B": rp.DYNAMIC_TARGET_SCORE})
        assert info.game_over and info.winner is game.players[1]

        # Game over: the «штрафной шар» is NOT removed from the table.
        assert system.balls["1"].state.s == const.stationary
        assert system.balls["2"].state.s == const.stationary

    def test_copy_is_independent(self) -> None:
        game = rp.RussianDynamicPyramid(players=[Player("A"), Player("B")])
        game.score = Counter({"A": 3, "B": 5})
        game.shot_number = 4
        game.turn_number = 7
        game.active_idx = 1
        game.shot_constraints = game.initial_shot_constraints()
        game.shot_info = ShotInfo(
            player=game.players[1],
            legal=False,
            reason=rp.DynamicPyramidReason.IN_HAND_CUE_POT,
            turn_over=True,
            game_over=False,
            winner=None,
            score=Counter({"A": 3, "B": 5}),
        )
        game.log.add_msg("hello")

        clone = game.copy()

        assert isinstance(clone, rp.RussianDynamicPyramid)
        assert clone.score == game.score and clone.score is not game.score
        assert (clone.shot_number, clone.turn_number, clone.active_idx) == (4, 7, 1)
        assert clone.shot_constraints == game.shot_constraints
        assert clone.shot_constraints.movable is not game.shot_constraints.movable
        assert clone.shot_info == game.shot_info
        assert clone.shot_info.score is not game.shot_info.score
        assert clone.players is game.players
        assert clone.log is not game.log and len(clone.log.msgs) == 1

        clone.score["A"] += 10
        assert game.score["A"] == 3
        clone.shot_constraints.movable.append(rp.CUE_BALL_ID + "x")
        assert game.shot_constraints.movable == [rp.CUE_BALL_ID]
        clone.log.add_msg("mutated")
        assert len(game.log.msgs) == 1


class TestDynamicPyramidRealShots:
    """Full-physics scenarios (slow but faithful to the real engine)."""

    def test_svoyak_straight_pot_scores_two_and_removes_ball(self) -> None:
        # Dead-straight pot: the object ball drops and the cue ball follows
        # it in («свояк») — two points (direct pot + compensation ball),
        # one ball off the table, cue ball re-introduced with table-wide
        # ball in hand (п. 6.1).
        system = _make_system(
            keep=("cue", "1", "2", "3"),
            positions={"2": (0.9, 2.3), "3": (0.9, 2.5)},
        )
        table = system.table
        px, py = (float(v) for v in table.pockets["rc"].center[:2])
        direction = np.array([table.w / 2 - px, table.l / 2 - py])
        direction /= np.linalg.norm(direction)
        balls = system.balls
        R = balls["1"].params.R
        balls["1"].state.rvw[0] = [
            px + 0.45 * direction[0],
            py + 0.45 * direction[1],
            R,
        ]
        balls[rp.CUE_BALL_ID].state.rvw[0] = [
            px + 0.90 * direction[0],
            py + 0.90 * direction[1],
            R,
        ]
        _seed_histories(balls)
        system.cue.set_state(
            V0=3.5,
            phi=math.degrees(
                math.atan2(
                    py - balls[rp.CUE_BALL_ID].state.rvw[0, 1],
                    px - balls[rp.CUE_BALL_ID].state.rvw[0, 0],
                )
            ),
        )
        pt.simulate(system, inplace=True)

        assert rp.potted_ball_ids(system) == ["1", rp.CUE_BALL_ID]
        assert rp.first_object_contact(system) == "1"

        live = ("2", "3")
        expected_removed = min(
            live, key=lambda bid: _dist_to_nearest_pocket_sq(system, bid)
        )

        game = _make_game(shot_number=3, game_cls=rp.RussianDynamicPyramid)
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.DynamicPyramidReason.LEGAL
        assert game.score == Counter({"A": 2})
        assert not info.turn_over and not info.game_over

        assert system.balls[expected_removed].state.s == const.pocketed
        cue = balls[rp.CUE_BALL_ID]
        assert cue.state.s == const.stationary
        assert cue.xyz[0] == pytest.approx(table.w / 2)
        assert cue.xyz[1] == pytest.approx(rp.HOUSE_DEFAULT_Y_FRACTION * table.l)
        assert game.shot_constraints.ball_in_hand == BallInHandOptions.ANYWHERE
        assert set(game.shot_constraints.hittable) == set(live) - {expected_removed}

    def test_scratch_without_contact_is_a_foul(self) -> None:
        # Cue ball driven dead-straight into the right middle pocket,
        # contacting no object ball: NO_CONTACT foul with full administration;
        # the opponent re-introduces the cue ball from anywhere (п. 7.2a).
        system = _make_system()
        system.balls[rp.CUE_BALL_ID].state.rvw[0] = [
            system.table.w / 2,
            system.table.l / 2,
            system.balls[rp.CUE_BALL_ID].params.R,
        ]
        _seed_histories(system.balls)
        system.cue.set_state(V0=4.0, phi=0.0)
        pt.simulate(system, inplace=True)

        assert rp.is_cue_ball_potted(system)
        assert rp.first_object_contact(system) is None

        live = sorted(
            (
                ball.id
                for ball in system.balls.values()
                if ball.id != rp.CUE_BALL_ID and ball.state.s in const.on_table
            ),
            key=int,
        )
        assert len(live) == 15
        expected_removed = min(
            live, key=lambda bid: _dist_to_nearest_pocket_sq(system, bid)
        )

        game = rp.RussianDynamicPyramid(players=[Player("A"), Player("B")])
        game.process_and_advance(system)

        info = game.shot_info
        assert not info.legal and info.reason == rp.DynamicPyramidReason.NO_CONTACT
        assert info.turn_over and not info.game_over
        assert game.score == Counter({"B": 1})

        # Table-wide ball-in-hand for the opponent (п. 7.2a), cue ball at
        # the deterministic default position.
        cue = system.balls[rp.CUE_BALL_ID]
        assert cue.state.s == const.stationary
        assert cue.xyz[0] == pytest.approx(system.table.w / 2)
        assert cue.xyz[1] == pytest.approx(rp.HOUSE_DEFAULT_Y_FRACTION * system.table.l)
        removed = [
            ball.id
            for ball in system.balls.values()
            if ball.id != rp.CUE_BALL_ID and ball.state.s == const.pocketed
        ]
        assert removed == [expected_removed]

        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.ANYWHERE
        assert c.movable == [rp.CUE_BALL_ID] and c.cueable == [rp.CUE_BALL_ID]
        assert set(c.hittable) == set(live) - {expected_removed}
        assert game.turn_number == 1 and game.active_idx == 1


# ---------------------------------------------------------------------------
# Step 9: Classic Pyramid («Классическая пирамида», 71 очко) scenario tests
# ---------------------------------------------------------------------------
#
# The Classic discipline shares the general-pyramid machinery (п. 12 break,
# п. 20 completion, п. 25 respots) and adds: called («заказ») shots with the
# called ball and pocket declared per п. 5.2, number-based scoring with the
# 1-ball worth 11 and a +10 bonus for the last remaining ball (п. 5.1), the
# cue-ball pot («свояк») as a foul (п. 5.5), the −5/+5 points foul penalty
# with no «штрафной шар» (п. 5.6), and the 70:70 tie-break (п. 5.7).


def _called_constraints(
    ball_call: str | None,
    pocket_call: str | None,
    ball_in_hand: BallInHandOptions = BallInHandOptions.NONE,
) -> ShotConstraints:
    """Constraints for a called (non-break) Classic stroke."""
    return ShotConstraints(
        ball_in_hand=ball_in_hand,
        movable=[rp.CUE_BALL_ID] if ball_in_hand != BallInHandOptions.NONE else [],
        cueable=[rp.CUE_BALL_ID],
        hittable=tuple(str(i) for i in range(1, 16)),
        call_shot=True,
        ball_call=ball_call,
        pocket_call=pocket_call,
    )


class TestClassicPyramidBreak:
    def test_break_constraints_need_no_call(self) -> None:
        game = rp.RussianClassicPyramid(players=[Player("A"), Player("B")])
        c0 = game.initial_shot_constraints()

        assert c0.ball_in_hand == BallInHandOptions.BEHIND_LINE
        assert c0.movable == [rp.CUE_BALL_ID]
        assert c0.cueable == [rp.CUE_BALL_ID]
        assert c0.hittable == tuple(str(i) for i in range(1, 16))
        assert c0.call_shot is False
        assert c0.can_shoot()
        assert game.shot_constraints == c0

    def test_real_break_scores_pots_by_value_and_continues(self) -> None:
        system = _make_system()
        apex = min(
            (b for b in system.balls.values() if b.id != rp.CUE_BALL_ID),
            key=lambda b: (
                float(b.state.rvw[0, 0]) ** 2
                + (float(b.state.rvw[0, 1]) - rp.REAR_SPOT_FRACTION * system.table.l)
                ** 2
            ),
        )
        system.cue.set_state(V0=9.0, phi=pt.aim.at_ball(system, apex.id))
        pt.simulate(system, inplace=True)

        assert rp.first_object_contact(system) is not None
        potted_objects = rp.potted_object_ball_ids(system)
        expected = sum(rp.ball_value(b) for b in potted_objects)

        game = rp.RussianClassicPyramid(players=[Player("A"), Player("B")])
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.ClassicPyramidReason.LEGAL_BREAK
        # Break pots score their number values (п. 5.1/п. 12.1(1)); no call
        # is required on the break.
        assert game.score["A"] == expected
        assert info.turn_over == (not potted_objects)
        assert game.shot_number == 1
        if potted_objects:
            # The breaker continues; the stroke is played as it lies (the
            # cue ball stayed on the table) with a call now required.
            assert not info.turn_over
            c = game.shot_constraints
            assert c.ball_in_hand == BallInHandOptions.NONE
            assert c.call_shot is True and c.ball_call is None
        else:
            assert game.active_idx == 1


class TestClassicPyramidLegality:
    """Synthetic event-based legality judgments (fast, deterministic)."""

    _POSITIONS: ClassVar[dict[str, tuple[float, float]]] = {
        "1": (0.5, 1.0),
        "2": (0.9, 1.85),
        "3": (0.5, 2.5),
    }

    def test_no_contact_jumped_and_cue_pot_are_fouls(self) -> None:
        system = _make_system(keep=("cue", "1"))
        game = _make_game(shot_number=3, game_cls=rp.RussianClassicPyramid)
        info = game.build_shot_info(system)
        assert not info.legal
        assert info.reason == rp.ClassicPyramidReason.NO_CONTACT
        # п. 5.6: five points transferred to the opponent.
        assert info.score == Counter({"A": -rp.CLASSIC_FOUL_POINTS, "B": 5})
        assert info.turn_over and not info.game_over

        jumped = _make_system(keep=("cue", "1"))
        jumped.events.append(_contact_event(t=0.2))
        _mark_off_table(jumped, "1", t=0.6)
        legal, reason = rp.evaluate_classic_shot(
            jumped, is_break=False, ball_call="1", pocket_call="rb"
        )
        assert not legal and reason == rp.ClassicPyramidReason.JUMPED_BALL

        # «Свояк» is a foul in the classic game (п. 5.5) — even with the
        # called ball pocketed exactly as ordered (the foul is judged
        # before the call).
        cue_pot = _make_system(
            keep=("cue", "1", "2"), positions={"1": (0.5, 1.0), "2": (0.9, 1.85)}
        )
        cue_pot.events.append(_contact_event(t=0.2))
        _mark_pocketed(cue_pot, "1", "rb", t=0.4)
        _mark_pocketed(cue_pot, rp.CUE_BALL_ID, "rc", t=0.5)
        legal, reason = rp.evaluate_classic_shot(
            cue_pot, is_break=False, ball_call="1", pocket_call="rb"
        )
        assert not legal and reason == rp.ClassicPyramidReason.CUE_POTTED

    def test_house_stroke_contacting_inside_ball_is_a_foul(self) -> None:
        # The cue ball stands in the house (rack spawn y = 0.23·l); the
        # first ball contacted also stands inside the house: п. 21 foul.
        system = _make_system(
            keep=("cue", "1", "2"), positions={"1": (0.9, 0.5), "2": (0.5, 1.5)}
        )
        system.events.append(_contact_event(t=0.2))
        _touch_row(system, "1", t=0.2)

        assert rp.violates_house_contact(system)
        legal, reason = rp.evaluate_classic_shot(
            system, is_break=False, ball_call="1", pocket_call="rb"
        )
        assert not legal and reason == rp.ClassicPyramidReason.HOUSE_FIRST_CONTACT

        game = _make_game(shot_number=3, game_cls=rp.RussianClassicPyramid)
        info = game.build_shot_info(system)
        assert not info.legal and info.turn_over
        assert info.score == Counter({"A": -5, "B": 5})

    def test_house_stroke_with_outside_call_pot_is_legal(self) -> None:
        # Same house stroke, but the called ball stands outside the house,
        # is pocketed as ordered, and the stroke completes: legal (п. 21
        # follows the contacted ball's position, as in Combined).
        system = _make_system(
            keep=("cue", "1", "2"), positions={"1": (0.9, 1.5), "2": (0.5, 2.5)}
        )
        system.events.append(_contact_event(t=0.2))
        _touch_row(system, "1", t=0.2)
        system.events.append(_cushion_event("1", "l1", 0.3))
        system.events.append(_cushion_event("1", "l2", 0.4))
        _mark_pocketed(system, "1", "rb", t=0.5)

        legal, reason = rp.evaluate_classic_shot(
            system, is_break=False, ball_call="1", pocket_call="rb"
        )
        assert legal and reason == rp.ClassicPyramidReason.LEGAL

        game = _make_game(shot_number=3, game_cls=rp.RussianClassicPyramid)
        game.shot_constraints = _called_constraints("1", "rb")
        game.process_and_advance(system)
        # The 1-ball («туз») scores 11 (п. 5.1).
        assert game.score == Counter({"A": rp.CLASSIC_ONE_BALL_VALUE})
        assert not game.shot_info.turn_over
        assert game.shot_constraints.ball_in_hand == BallInHandOptions.NONE
        assert game.shot_constraints.hittable == ("2",)

    def test_uncalled_pot_is_not_a_foul(self) -> None:
        # п. 5.4: an uncalled ball falls while another ball was ordered —
        # not a foul: no points, the ball is respotted, the turn passes.
        system = _make_system(
            keep=("cue", "1", "2"), positions={"1": (0.5, 1.0), "2": (0.9, 1.85)}
        )
        system.events.append(_contact_event(t=0.2))
        system.events.append(_cushion_event("1", "l1", 0.3))
        system.events.append(_cushion_event("1", "l2", 0.4))
        _mark_pocketed(system, "1", "rb", t=0.5)

        game = _make_game(shot_number=3, game_cls=rp.RussianClassicPyramid)
        game.score = Counter({"A": 4, "B": 2})
        game.shot_constraints = _called_constraints("2", "rb")
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.ClassicPyramidReason.UNCALLED_POT
        assert info.score == Counter({"A": 4, "B": 2})
        assert info.turn_over and not info.game_over

        # The uncalled pot is respotted onto the задняя отметка (п. 5.4 +
        # п. 25; the mark is free here).
        table = system.table
        mark = (table.w / 2, rp.REAR_SPOT_FRACTION * table.l)
        assert system.balls["1"].state.s == const.stationary
        assert tuple(system.balls["1"].xyz[:2]) == pytest.approx(mark)
        assert system.balls["2"].state.s == const.stationary

        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.NONE and c.call_shot is True
        assert c.hittable == ("1", "2")

    def test_called_ball_in_wrong_pocket_is_uncalled(self) -> None:
        # The call names the ball AND the pocket (п. 5.2): the called ball
        # falling into a different pocket does not honor the call.
        system = _make_system(
            keep=("cue", "1", "2"), positions={"1": (0.5, 1.0), "2": (0.9, 1.85)}
        )
        system.events.append(_contact_event(t=0.2))
        system.events.append(_cushion_event("1", "l1", 0.3))
        system.events.append(_cushion_event("1", "l2", 0.4))
        _mark_pocketed(system, "1", "lc", t=0.5)  # ordered "rb"

        game = _make_game(shot_number=3, game_cls=rp.RussianClassicPyramid)
        game.shot_constraints = _called_constraints("1", "rb")
        info = game.build_shot_info(system)

        assert info.legal
        assert info.reason == rp.ClassicPyramidReason.UNCALLED_POT
        assert info.score == Counter()
        assert info.turn_over


class TestClassicPyramidScoring:
    """Number values, the 1-ball's 11, the last-ball bonus, and penalties."""

    _POSITIONS: ClassVar[dict[str, tuple[float, float]]] = {
        "8": (0.5, 1.0),
        "2": (0.9, 1.85),
        "3": (0.5, 2.5),
    }

    def test_called_pot_scores_ball_value(self) -> None:
        system = _make_system(keep=("cue", "8", "2", "3"), positions=self._POSITIONS)
        system.events.append(_contact_event(t=0.2, obj="8"))
        _mark_pocketed(system, "8", "rb", t=0.4)

        game = _make_game(shot_number=3, game_cls=rp.RussianClassicPyramid)
        game.shot_constraints = _called_constraints("8", "rb")
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.ClassicPyramidReason.LEGAL
        assert game.score == Counter({"A": 8})
        assert not info.turn_over and not info.game_over

        # Legally potted called ball stays down; no ball is removed
        # (Classic has no «штрафной шар» / compensation ball).
        assert system.balls["8"].state.s == const.pocketed
        assert system.balls["2"].state.s == const.stationary
        assert system.balls["3"].state.s == const.stationary
        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.NONE and c.movable == []
        assert c.hittable == ("2", "3")

    def test_one_ball_scores_eleven(self) -> None:
        system = _make_system(
            keep=("cue", "1", "2", "3"),
            positions={"1": (0.5, 1.0), "2": (0.9, 1.85), "3": (0.5, 2.5)},
        )
        system.events.append(_contact_event(t=0.2))
        _mark_pocketed(system, "1", "rb", t=0.4)

        game = _make_game(shot_number=3, game_cls=rp.RussianClassicPyramid)
        game.shot_constraints = _called_constraints("1", "rb")
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.ClassicPyramidReason.LEGAL
        assert game.score == Counter({"A": rp.CLASSIC_ONE_BALL_VALUE})
        assert not info.turn_over

    def test_correct_call_counts_all_pots(self) -> None:
        # п. 5.3: when the called ball is pocketed as ordered, every ball
        # potted on the stroke scores (the uncalled "3" included).
        system = _make_system(
            keep=("cue", "8", "3"), positions={"8": (0.5, 1.0), "3": (0.9, 1.85)}
        )
        system.events.append(_contact_event(t=0.2, obj="8"))
        _mark_pocketed(system, "8", "rb", t=0.4)
        _mark_pocketed(system, "3", "lc", t=0.45)

        game = _make_game(shot_number=3, game_cls=rp.RussianClassicPyramid)
        game.shot_constraints = _called_constraints("8", "rb")
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.ClassicPyramidReason.LEGAL
        assert game.score == Counter({"A": 8 + 3})
        assert not info.turn_over
        assert system.balls["8"].state.s == const.pocketed
        assert system.balls["3"].state.s == const.pocketed

    def test_last_ball_bonus_applied(self) -> None:
        # п. 5.1: the last remaining object ball scores +10 extra.
        system = _make_system(keep=("cue", "7"), positions={"7": (0.5, 1.0)})
        system.events.append(_contact_event(t=0.2, obj="7"))
        _mark_pocketed(system, "7", "rb", t=0.4)

        game = _make_game(shot_number=3, game_cls=rp.RussianClassicPyramid)
        game.shot_constraints = _called_constraints("7", "rb")
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.ClassicPyramidReason.LEGAL
        assert game.score == Counter(
            {"A": rp.ball_value("7") + rp.CLASSIC_LAST_BALL_BONUS}
        )
        assert not info.turn_over
        assert system.balls["7"].state.s == const.pocketed

    def test_foul_transfers_five_points_and_allows_negative(self) -> None:
        system = _make_system(
            keep=("cue", "1", "2"), positions={"1": (0.5, 1.0), "2": (0.9, 1.85)}
        )
        live = ("1", "2")

        game = _make_game(shot_number=3, game_cls=rp.RussianClassicPyramid)
        game.score = Counter({"A": 3})
        game.process_and_advance(system)

        info = game.shot_info
        assert not info.legal and info.reason == rp.ClassicPyramidReason.NO_CONTACT
        # п. 5.6: five points transferred; the offender may go negative
        # (preset 3 -> 3 - 5 = -2).
        assert game.score == Counter({"A": -2, "B": 5})
        assert info.turn_over and not info.game_over
        assert game.turn_number == 1 and game.active_idx == 1

        # No «штрафной шар» in Classic: both object balls stay on the table.
        for ball_id in live:
            assert system.balls[ball_id].state.s in const.on_table
        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.NONE and c.movable == []
        assert c.hittable == live and c.call_shot is True


class TestClassicPyramidEndgame:
    def test_reaching_target_ends_game(self) -> None:
        system = _make_system(
            keep=("cue", "5", "2"), positions={"5": (0.5, 1.0), "2": (0.9, 1.85)}
        )
        system.events.append(_contact_event(t=0.2, obj="5"))
        _mark_pocketed(system, "5", "rb", t=0.4)

        game = _make_game(shot_number=3, game_cls=rp.RussianClassicPyramid)
        game.score = Counter({"A": rp.CLASSIC_TARGET_SCORE - 1})
        game.shot_constraints = _called_constraints("5", "rb")
        game.shot_info = game.build_shot_info(system)
        game.respot_balls(system)

        info = game.shot_info
        assert info.legal
        assert info.score == Counter(
            {"A": rp.CLASSIC_TARGET_SCORE - 1 + rp.ball_value("5"), "B": 0}
        )
        assert info.game_over and info.winner is game.players[0]

        # Legal stroke: no respots, no ball removal (п. 5.6 is points-only).
        assert system.balls["5"].state.s == const.pocketed
        assert system.balls["2"].state.s == const.stationary

    def test_foul_crossing_target_ends_game(self) -> None:
        system = _make_system(
            keep=("cue", "1", "2"), positions={"1": (0.5, 1.0), "2": (0.9, 1.85)}
        )

        game = _make_game(shot_number=3, game_cls=rp.RussianClassicPyramid)
        game.score = Counter({"A": 66, "B": 68})
        game.shot_info = game.build_shot_info(system)  # no events -> foul
        game.respot_balls(system)

        info = game.shot_info
        assert not info.legal
        assert info.score == Counter({"A": 61, "B": 73})
        assert info.game_over and info.winner is game.players[1]

        # Game over, and still no ball removed (Classic has none).
        assert system.balls["1"].state.s == const.stationary
        assert system.balls["2"].state.s == const.stationary

    def test_tiebreak_at_70_70_respots_last_ball_and_grants_house(self) -> None:
        # п. 5.7: the pot that lifts both players to 70 respots the last
        # potted ball onto the задняя отметка; the continuation stroke is
        # played from the house; the lag (deterministically: the turn pass)
        # decides who plays.
        system = _make_system(keep=("cue", "6"), positions={"6": (0.5, 1.0)})
        system.events.append(_contact_event(t=0.2, obj="6"))
        _mark_pocketed(system, "6", "rb", t=0.4)

        game = _make_game(shot_number=3, game_cls=rp.RussianClassicPyramid)
        game.score = Counter(
            {"A": 70 - rp.ball_value("6") - rp.CLASSIC_LAST_BALL_BONUS, "B": 70}
        )
        game.shot_constraints = _called_constraints("6", "rb")
        game.process_and_advance(system)

        info = game.shot_info
        assert info.legal and info.reason == rp.ClassicPyramidReason.LEGAL
        assert info.score == Counter({"A": 70, "B": 70})
        assert not info.game_over and info.winner is None
        # Deterministic lag replacement: the turn passes.
        assert info.turn_over

        # The last potted ball returns to the задняя отметка; the cue ball
        # is re-placed in the house for the continuation stroke.
        table = system.table
        mark = (table.w / 2, rp.REAR_SPOT_FRACTION * table.l)
        assert system.balls["6"].state.s == const.stationary
        assert tuple(system.balls["6"].xyz[:2]) == pytest.approx(mark)
        cue = system.balls[rp.CUE_BALL_ID]
        assert cue.state.s == const.stationary
        assert cue.xyz[0] == pytest.approx(table.w / 2)
        assert cue.xyz[1] == pytest.approx(rp.HOUSE_DEFAULT_Y_FRACTION * table.l)

        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.BEHIND_LINE
        assert c.movable == [rp.CUE_BALL_ID]
        assert c.call_shot is True
        assert c.hittable == ("6",)
        assert game.active_idx == 1 and game.turn_number == 1

    def test_copy_is_independent(self) -> None:
        game = rp.RussianClassicPyramid(players=[Player("A"), Player("B")])
        game.score = Counter({"A": 3, "B": 5})
        game.shot_number = 4
        game.turn_number = 7
        game.active_idx = 1
        game.shot_constraints = game.initial_shot_constraints()
        game.shot_info = ShotInfo(
            player=game.players[1],
            legal=False,
            reason=rp.ClassicPyramidReason.CUE_POTTED,
            turn_over=True,
            game_over=False,
            winner=None,
            score=Counter({"A": 3, "B": 5}),
        )
        game.log.add_msg("hello")

        clone = game.copy()

        assert isinstance(clone, rp.RussianClassicPyramid)
        assert clone.score == game.score and clone.score is not game.score
        assert (clone.shot_number, clone.turn_number, clone.active_idx) == (4, 7, 1)
        assert clone.shot_constraints == game.shot_constraints
        assert clone.shot_constraints.movable is not game.shot_constraints.movable
        assert clone.shot_info == game.shot_info
        assert clone.shot_info.score is not game.shot_info.score
        assert clone.players is game.players
        assert clone.log is not game.log and len(clone.log.msgs) == 1

        clone.score["A"] += 10
        assert game.score["A"] == 3
        clone.shot_constraints.movable.append(rp.CUE_BALL_ID + "x")
        assert game.shot_constraints.movable == [rp.CUE_BALL_ID]
        clone.log.add_msg("mutated")
        assert len(game.log.msgs) == 1


class TestClassicPyramidRealShots:
    """Full-physics scenarios (slow but faithful to the real engine)."""

    def test_real_cue_pot_is_a_foul_despite_correct_call(self) -> None:
        # Dead-straight pot: the called ball drops as ordered, but the cue
        # ball follows it in — «свояк» is a foul in the classic game
        # (п. 5.5), overriding the honored call; −5/+5, the potted ball is
        # respotted and the opponent plays the penalty stroke from the
        # house (п. 21).
        system = _make_system(
            keep=("cue", "1", "2", "3"),
            positions={"2": (0.9, 2.3), "3": (0.9, 2.5)},
        )
        table = system.table
        px, py = (float(v) for v in table.pockets["rc"].center[:2])
        direction = np.array([table.w / 2 - px, table.l / 2 - py])
        direction /= np.linalg.norm(direction)
        balls = system.balls
        R = balls["1"].params.R
        balls["1"].state.rvw[0] = [
            px + 0.45 * direction[0],
            py + 0.45 * direction[1],
            R,
        ]
        balls[rp.CUE_BALL_ID].state.rvw[0] = [
            px + 0.90 * direction[0],
            py + 0.90 * direction[1],
            R,
        ]
        _seed_histories(balls)
        system.cue.set_state(
            V0=3.5,
            phi=math.degrees(
                math.atan2(
                    py - balls[rp.CUE_BALL_ID].state.rvw[0, 1],
                    px - balls[rp.CUE_BALL_ID].state.rvw[0, 0],
                )
            ),
        )
        pt.simulate(system, inplace=True)

        assert rp.potted_ball_ids(system) == ["1", rp.CUE_BALL_ID]

        game = _make_game(shot_number=3, game_cls=rp.RussianClassicPyramid)
        game.score = Counter({"A": 10})
        game.shot_constraints = _called_constraints("1", "rc")
        game.process_and_advance(system)

        info = game.shot_info
        assert not info.legal
        assert info.reason == rp.ClassicPyramidReason.CUE_POTTED
        assert game.score == Counter({"A": 5, "B": 5})
        assert info.turn_over and not info.game_over

        # The foul-potted object ball is respotted onto the задняя отметка
        # (free here); the cue ball re-enters from the house.
        mark = (table.w / 2, rp.REAR_SPOT_FRACTION * table.l)
        assert system.balls["1"].state.s == const.stationary
        assert tuple(system.balls["1"].xyz[:2]) == pytest.approx(mark)
        cue = balls[rp.CUE_BALL_ID]
        assert cue.state.s == const.stationary
        assert cue.xyz[0] == pytest.approx(table.w / 2)
        assert cue.xyz[1] == pytest.approx(rp.HOUSE_DEFAULT_Y_FRACTION * table.l)

        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.BEHIND_LINE
        assert c.movable == [rp.CUE_BALL_ID] and c.call_shot is True
        assert c.hittable == ("1", "2", "3")
        assert game.active_idx == 1

    def test_real_scratch_without_contact_is_a_foul(self) -> None:
        # Cue ball driven dead-straight into the right middle pocket,
        # contacting no object ball: NO_CONTACT foul with the −5/+5 penalty
        # and NO ball removal (Classic has no «штрафной шар»).
        system = _make_system()
        system.balls[rp.CUE_BALL_ID].state.rvw[0] = [
            system.table.w / 2,
            system.table.l / 2,
            system.balls[rp.CUE_BALL_ID].params.R,
        ]
        _seed_histories(system.balls)
        system.cue.set_state(V0=4.0, phi=0.0)
        pt.simulate(system, inplace=True)

        assert rp.is_cue_ball_potted(system)
        assert rp.first_object_contact(system) is None

        game = rp.RussianClassicPyramid(players=[Player("A"), Player("B")])
        game.process_and_advance(system)

        info = game.shot_info
        assert not info.legal and info.reason == rp.ClassicPyramidReason.NO_CONTACT
        assert info.turn_over and not info.game_over
        assert game.score == Counter({"A": -5, "B": 5})

        # Penalty stroke from the house (п. 5.5/п. 21); all 15 object
        # balls remain on the table.
        cue = system.balls[rp.CUE_BALL_ID]
        assert cue.state.s == const.stationary
        assert cue.xyz[0] == pytest.approx(system.table.w / 2)
        assert cue.xyz[1] == pytest.approx(rp.HOUSE_DEFAULT_Y_FRACTION * system.table.l)
        live = [
            ball.id
            for ball in system.balls.values()
            if ball.id != rp.CUE_BALL_ID and ball.state.s in const.on_table
        ]
        assert len(live) == 15

        c = game.shot_constraints
        assert c.ball_in_hand == BallInHandOptions.BEHIND_LINE
        assert c.movable == [rp.CUE_BALL_ID] and c.cueable == [rp.CUE_BALL_ID]
        assert c.call_shot is True
        assert c.hittable == tuple(str(i) for i in range(1, 16))
        assert game.turn_number == 1 and game.active_idx == 1
