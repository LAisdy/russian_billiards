"""Step 5 verification: Free Pyramid ruleset implementation.

Grows with each Step 5 artifact:
- 5/1: module foundation (constants, reason taxonomy, extraction helpers)
- 5/2: legality/constraint machinery + build_shot_info
- 5/3: respot_balls + copy() (п. 25 spotting line, scratch handling,
  штрафной шар policy, real-simulated scratch integration)
- 5/4: full scenario checks on real simulated shots
"""

from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

from pooltool.ruleset import russian_pyramid as rp
from pooltool.ruleset.datatypes import BallInHandOptions, Player, ShotInfo


def check_foundation() -> None:
    import inspect

    assert rp.CUE_BALL_ID == "cue"
    assert rp.FREE_TARGET_SCORE == 8

    reason_values = [r.value for r in rp.FreePyramidReason]
    assert len(reason_values) == len(set(reason_values)), "duplicate reason values"

    # object_ball_ids only touches shot.balls -> a stub suffices at this stage.
    balls = {"cue": object(), **{str(i): object() for i in range(1, 16)}}
    shot = SimpleNamespace(balls=balls)
    assert rp.object_ball_ids(shot) == [str(i) for i in range(1, 16)]

    stubs = rp.RussianFreePyramid  # class object must import cleanly
    method_names = (
        "build_shot_info",
        "next_shot_constraints",
        "initial_shot_constraints",
        "respot_balls",
        "copy",
    )
    stub_methods = [
        name
        for name in method_names
        if "NotImplementedError" in inspect.getsource(getattr(stubs, name))
    ]
    print(
        f"foundation OK | reasons={reason_values}"
        f" | stubbed_free_methods={len(stub_methods)}/5"
    )


def check_constraints() -> None:
    game = rp.RussianFreePyramid()
    c0 = game.initial_shot_constraints()

    assert c0.ball_in_hand == BallInHandOptions.BEHIND_LINE
    assert c0.movable == [rp.CUE_BALL_ID]
    assert c0.cueable == [rp.CUE_BALL_ID]
    assert c0.hittable == tuple(str(i) for i in range(1, 16))
    assert c0.call_shot is False
    assert c0.can_shoot()

    print("constraints OK | break: behind line, 15 hittable, no call")


def check_crossing() -> None:
    import numpy as np

    from pooltool.game.datatypes import GameType
    from pooltool.layouts import get_rack
    from pooltool.objects.ball.datatypes import BallState
    from pooltool.objects.table.collection import default_specs_from_game_type
    from pooltool.objects.table.datatypes import Table

    table = Table.from_table_specs(
        default_specs_from_game_type(GameType.RUSSIAN_PYRAMID_FREE)
    )
    balls = get_rack(GameType.RUSSIAN_PYRAMID_FREE, table)

    b = balls["1"]
    x, _, z = b.xyz
    half = table.l / 2
    b.history.add(
        BallState(
            rvw=np.array([[x, 0.4 * table.l, z], [0, 0, 0], [0, 0, 0]]), s=3, t=1.0
        )
    )
    b.history.add(
        BallState(
            rvw=np.array([[x, 0.6 * table.l, z], [0, 0, 0], [0, 0, 0]]), s=3, t=2.0
        )
    )

    shot = SimpleNamespace(balls=balls, table=table, events=[])

    crossed = rp.crossed_center_line(shot)
    assert "1" in crossed, "ball 1 must be flagged as crossing"
    assert "2" not in crossed, "stationary ball 2 must not be flagged"

    # Cutoff after the crossing rows -> no crossing in the remaining window.
    assert "1" not in rp.crossed_center_line(shot, after=1.5)
    # Cutoff before them -> crossing detected.
    assert "1" in rp.crossed_center_line(shot, after=0.5)

    assert half < 0.6 * table.l and 0.4 * table.l < half
    print("center-line crossing OK | cutoff semantics OK")


def check_real_system() -> None:
    import pooltool as pt

    system = pt.System.example()
    pt.simulate(system, inplace=True)

    t0 = rp.first_contact_time(system)
    assert t0 is not None, "example shot must include a cue ball collision"

    contacts = rp.cushion_contacts(system, after=t0)
    crossed = rp.crossed_center_line(system, after=t0)
    legal, reason = rp.evaluate_free_shot(system, is_break=False)

    # The example shot pockets balls, so п. 20 clause (1) applies.
    assert legal is True
    assert reason == rp.FreePyramidReason.LEGAL
    assert rp.potted_ball_ids(system), "example shot must pocket balls"

    no_contact_shot = SimpleNamespace(events=[], balls={}, table=system.table)
    legal2, reason2 = rp.evaluate_free_shot(no_contact_shot, is_break=False)
    assert legal2 is False
    assert reason2 == rp.FreePyramidReason.NO_CONTACT

    print(
        f"real system OK | first contact t={t0:.3f}s | "
        f"cushion contacts: { {b: len(c) for b, c in contacts.items()} } | "
        f"crossed: {sorted(crossed)}"
    )


def _russian_table_and_rack():
    from pooltool.game.datatypes import GameType
    from pooltool.layouts import get_rack
    from pooltool.objects.table.collection import default_specs_from_game_type
    from pooltool.objects.table.datatypes import Table

    table = Table.from_table_specs(
        default_specs_from_game_type(GameType.RUSSIAN_PYRAMID_FREE)
    )
    return table, get_rack(GameType.RUSSIAN_PYRAMID_FREE, table)


def check_respot_machinery() -> None:
    import numpy as np

    import pooltool.constants as const
    from pooltool.events.datatypes import Agent, AgentType, Event, EventType
    from pooltool.objects.ball.datatypes import BallHistory

    table, balls = _russian_table_and_rack()
    R = balls["1"].params.R
    w, l = table.w, table.l
    shot = SimpleNamespace(balls=balls, table=table, events=[], t=0.0)
    step = 2 * R + rp._RESPOT_GAP

    # -- spot_line_position: empty table -> exactly the задняя отметка --
    pos = rp.spot_line_position(shot, [], R)
    assert np.allclose(pos, (w / 2, rp.REAR_SPOT_FRACTION * l)), pos

    # -- mark occupied -> nearest free slot toward the rear rail --
    mark = (w / 2, rp.REAR_SPOT_FRACTION * l)
    pos = rp.spot_line_position(shot, [mark], R)
    assert np.allclose(pos, (w / 2, mark[1] + step)), pos

    # -- rear segment fully packed -> continuation toward the table center --
    k = 0
    occupied = []
    while mark[1] + k * step <= l - R:
        occupied.append((w / 2, mark[1] + k * step))
        k += 1
    pos = rp.spot_line_position(shot, occupied, R)
    assert np.allclose(pos, (w / 2, mark[1] - step)), pos

    # -- house_default_position: empty house -> the break spawn point --
    y0 = rp.HOUSE_DEFAULT_Y_FRACTION * l
    assert np.allclose(rp.house_default_position(shot, [], R), (w / 2, y0))

    # -- first two house slots blocked -> third slot head-ward is free --
    occupied = [(w / 2, y0), (w / 2, y0 - step)]
    pos = rp.house_default_position(shot, occupied, R)
    assert np.allclose(pos, (w / 2, y0 - 2 * step)), pos

    # -- completely packed house -> explicit RuntimeError (unreachable in play) --
    occupied = []
    while y0 - len(occupied) * step >= R:
        occupied.append((w / 2, y0 - len(occupied) * step))
    try:
        rp.house_default_position(shot, occupied, R)
        packed_raised = False
    except RuntimeError:
        packed_raised = True
    assert packed_raised, "packed house centerline must raise RuntimeError"

    # -- respot_on_spot_line on a real (minimal) rack + history sync --
    for i in range(2, 16):
        del balls[str(i)]
    balls["1"].state.rvw[0] = [0.2 * w, 0.2 * l, R]  # clear of the mark
    balls["1"].state.s = const.pocketed  # the ball being respotted
    hist_len = len(balls["1"].history)
    rp.respot_on_spot_line(shot, "1")
    assert np.allclose(balls["1"].xyz[:2], mark), balls["1"].xyz
    assert balls["1"].state.s == const.stationary
    assert len(balls["1"].history) == hist_len + 1
    assert balls["1"].history[-1].s == const.stationary
    assert balls["1"].history[-1].t == shot.t

    # -- remove_penalty_ball: single candidate is taken off the table --
    balls["1"].state.rvw[0] = [0.3 * w, 0.9 * l, R]
    balls["1"].state.s = const.stationary
    balls["1"].history = BallHistory()
    chosen = rp.remove_penalty_ball(shot)
    assert chosen == "1"
    pocket = rp.nearest_pocket(table, (0.3 * w, 0.9 * l))
    assert balls["1"].state.s == const.pocketed
    assert np.allclose(
        balls["1"].state.rvw[0], [pocket.center[0], pocket.center[1], -pocket.depth]
    )
    assert balls["1"].history[-1].s == const.pocketed

    # -- remove_penalty_ball: no object balls on the table -> None --
    assert rp.remove_penalty_ball(shot) is None

    # -- is_cue_ball_jumped: event-based detection --
    def jump_event(ball_id: str) -> Event:
        return Event(
            event_type=EventType.BALL_OFF_TABLE,
            agents=(Agent(id=ball_id, agent_type=AgentType.BALL),),
            time=0.5,
        )

    empty_shot = SimpleNamespace(balls={}, table=table, events=[])
    assert rp.is_cue_ball_jumped(empty_shot) is False
    obj_shot = SimpleNamespace(balls={}, table=table, events=[jump_event("7")])
    assert rp.is_cue_ball_jumped(obj_shot) is False
    cue_shot = SimpleNamespace(balls={}, table=table, events=[jump_event("cue")])
    assert rp.is_cue_ball_jumped(cue_shot) is True

    print("respot machinery OK | п.25 spot line, house scan, penalty ball, jumps")


def check_svojyak_respot() -> None:
    import numpy as np

    import pooltool.constants as const

    table, balls = _russian_table_and_rack()
    R = balls["cue"].params.R
    w, l = table.w, table.l
    mark = (w / 2, rp.REAR_SPOT_FRACTION * l)
    step = 2 * R + rp._RESPOT_GAP

    def make_game() -> rp.RussianFreePyramid:
        game = rp.RussianFreePyramid(players=[Player("A"), Player("B")])
        game.shot_info = ShotInfo(
            player=game.players[0],
            legal=True,
            reason=rp.FreePyramidReason.LEGAL,
            turn_over=False,
            game_over=False,
            winner=None,
            score=Counter(),
        )
        return game

    # (a) mark free -> cue lands exactly on the задняя отметка
    for i in range(2, 16):
        del balls[str(i)]
    balls["1"].state.rvw[0] = [0.2 * w, 0.2 * l, R]  # clear of the mark
    balls["cue"].state.rvw[0] = [w / 2, 0.1 * l, R]
    balls["cue"].state.s = const.pocketed  # свояк: cue ball potted legally
    make_game().respot_balls(
        SimpleNamespace(balls=balls, table=table, events=[], t=0.0)
    )
    assert balls["cue"].state.s == const.stationary
    assert np.allclose(balls["cue"].xyz[:2], mark), balls["cue"].xyz
    assert balls["cue"].history[-1].s == const.stationary

    # (b) mark occupied (apex ball) -> one slot toward the rear rail
    balls["1"].state.rvw[0] = [mark[0], mark[1], R]
    balls["1"].state.s = const.stationary
    balls["cue"].state.rvw[0] = [w / 2, 0.1 * l, R]
    balls["cue"].state.s = const.pocketed
    make_game().respot_balls(
        SimpleNamespace(balls=balls, table=table, events=[], t=0.0)
    )
    assert np.allclose(balls["cue"].xyz[:2], (w / 2, mark[1] + step)), balls["cue"].xyz

    # No penalty-ball removal on a legal stroke: ball 1 still on the table.
    assert balls["1"].state.s == const.stationary

    print("свояк respot OK | legal cue pot -> задняя отметка / spotting line")


def check_scratch_integration() -> None:
    import numpy as np

    import pooltool as pt
    import pooltool.constants as const
    from pooltool.objects.cue.datatypes import Cue

    table, balls = _russian_table_and_rack()
    R = balls["cue"].params.R

    # Mid-game position: cue ball at the table center, a dead-straight
    # object-ball-free pot into the right middle pocket -> NO_CONTACT foul.
    # phi is in degrees (Cue docs): 0 = +x, which points from the center row
    # straight into the right middle pocket.
    balls["cue"].state.rvw[0] = [table.w / 2, table.l / 2, R]
    cue = Cue.default()
    cue.set_state(cue_ball_id="cue")
    system = pt.System(table=table, balls=balls, cue=cue)
    system.cue.set_state(V0=4.0, phi=0.0)
    pt.simulate(system, inplace=True)

    assert rp.is_cue_ball_potted(system), "cue ball must drop in the middle pocket"
    assert rp.first_object_contact(system) is None, "shot must contact no object ball"
    legal, reason = rp.evaluate_free_shot(system, is_break=False)
    assert not legal and reason == rp.FreePyramidReason.NO_CONTACT

    # Snapshot the live object balls before processing: the penalty ball must
    # be the live ball closest to any pocket center (lowest ID on ties).
    live = {
        ball.id: (float(ball.state.rvw[0, 0]), float(ball.state.rvw[0, 1]))
        for ball in system.balls.values()
        if ball.id != "cue" and ball.state.s in const.on_table
    }
    assert len(live) == 15

    def pocket_dist_sq(ball_id: str) -> float:
        x, y = live[ball_id]
        pocket = rp.nearest_pocket(table, (x, y))
        return (x - float(pocket.center[0])) ** 2 + (y - float(pocket.center[1])) ** 2

    expected_removed = min(sorted(live, key=int), key=pocket_dist_sq)

    game = rp.RussianFreePyramid(players=[Player("A"), Player("B")])
    game.process_and_advance(system)

    # Scoring: foul -> opponent +1, turn over, game continues.
    info = game.shot_info
    assert not info.legal and info.reason == rp.FreePyramidReason.NO_CONTACT
    assert info.turn_over and not info.game_over
    assert game.score["A"] == 0 and game.score["B"] == 1

    # Scratch handling: cue ball placed at the default house spot (free here).
    cue = system.balls["cue"]
    assert cue.state.s == const.stationary
    assert np.allclose(
        cue.xyz[:2],
        (table.w / 2, rp.HOUSE_DEFAULT_Y_FRACTION * table.l),
    ), cue.xyz
    assert cue.history[-1].s == const.stationary

    # Штрафной шар: exactly one live ball removed, the policy-chosen one.
    removed = [
        ball.id
        for ball in system.balls.values()
        if ball.id != "cue" and ball.state.s == const.pocketed
    ]
    assert removed == [expected_removed], (removed, expected_removed)
    pocket = rp.nearest_pocket(table, live[expected_removed])
    assert np.allclose(
        system.balls[expected_removed].state.rvw[0],
        [pocket.center[0], pocket.center[1], -pocket.depth],
    )

    # Constraints: ball-in-hand behind the house line, removed ball not hittable.
    c = game.shot_constraints
    assert c.ball_in_hand == BallInHandOptions.BEHIND_LINE
    assert c.movable == ["cue"] and c.cueable == ["cue"]
    assert set(c.hittable) == set(live) - {expected_removed}

    # Turn advanced to the opponent.
    assert game.turn_number == 1 and game.shot_number == 1
    assert game.active_idx == 1

    print(
        f"scratch integration OK | foul scratch -> house + штрафной шар "
        f"{expected_removed} removed, BEHIND_LINE granted"
    )


def check_copy() -> None:
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

    cp = game.copy()

    assert isinstance(cp, rp.RussianFreePyramid)
    assert cp.score == game.score and cp.score is not game.score
    assert (cp.shot_number, cp.turn_number, cp.active_idx) == (4, 7, 1)
    assert cp.shot_constraints == game.shot_constraints
    assert cp.shot_constraints.movable is not game.shot_constraints.movable
    assert cp.shot_info == game.shot_info
    assert cp.shot_info.score is not game.shot_info.score
    assert cp.players is game.players, "players are shared identity objects"
    assert cp.log is not game.log and len(cp.log.msgs) == 1

    # Independence: mutating the copy must not leak into the original.
    cp.score["A"] += 10
    assert game.score["A"] == 3
    cp.shot_constraints.movable.append("1")
    assert "1" not in game.shot_constraints.movable
    cp.shot_info.score["B"] += 10
    assert game.shot_info.score["B"] == 5
    cp.log.add_msg("mutated")
    assert len(game.log.msgs) == 1

    # A fresh game (no shot_info yet) copies cleanly.
    fresh = rp.RussianFreePyramid(players=[Player("X"), Player("Y")])
    fresh_cp = fresh.copy()
    assert not hasattr(fresh_cp, "shot_info")
    assert fresh_cp.score == Counter()

    print("copy OK | independent bookkeeping, shared players, fresh-game safe")


def check_jump_foul() -> None:
    """Jumped balls («выскочившие») foul the stroke and get respotted (5/4)."""
    import numpy as np

    import pooltool.constants as const
    from pooltool.events.datatypes import Agent, AgentType, Event, EventType

    table, balls = _russian_table_and_rack()

    def ball_agent(ball_id: str) -> Agent:
        return Agent(id=ball_id, agent_type=AgentType.BALL)

    def contact_then_jump(jumper: str) -> list[Event]:
        return [
            Event(
                event_type=EventType.BALL_BALL,
                agents=(ball_agent("cue"), ball_agent("5")),
                time=0.2,
            ),
            Event(
                event_type=EventType.BALL_OFF_TABLE,
                agents=(ball_agent(jumper),),
                time=0.6,
            ),
        ]

    # (a) Object ball jump: contact happened, so the jump reason wins.
    shot = SimpleNamespace(
        balls=balls, table=table, events=contact_then_jump("7"), t=1.0
    )
    assert rp.first_object_contact(shot) == "5"
    legal, reason = rp.evaluate_free_shot(shot, is_break=False)
    assert not legal and reason == rp.FreePyramidReason.JUMPED_BALL
    legal, reason = rp.evaluate_free_shot(shot, is_break=True)
    assert not legal and reason == rp.FreePyramidReason.JUMPED_BALL, (
        "jump fouls the break too"
    )

    # (b) Cue-ball jump: foul; the cue is a jumped ball for constraint logic.
    cue_jump = SimpleNamespace(
        balls=balls, table=table, events=contact_then_jump("cue"), t=1.0
    )
    legal, reason = rp.evaluate_free_shot(cue_jump, is_break=False)
    assert not legal and reason == rp.FreePyramidReason.JUMPED_BALL
    assert rp.is_cue_ball_jumped(cue_jump)

    # (c) Same contact without a jump -> ordinary completion path is reached.
    no_jump = SimpleNamespace(
        balls=balls,
        table=table,
        events=contact_then_jump("7")[:1],
        t=1.0,
    )
    legal, reason = rp.evaluate_free_shot(no_jump, is_break=False)
    assert not legal and reason == rp.FreePyramidReason.ILLEGAL_COMPLETION

    # (d) build_shot_info on a jump foul: opponent +1, turn over.
    game = rp.RussianFreePyramid(players=[Player("A"), Player("B")])
    info = game.build_shot_info(shot)
    assert not info.legal and info.reason == rp.FreePyramidReason.JUMPED_BALL
    assert info.turn_over
    assert info.score["B"] == 1 and info.score["A"] == 0

    # (e) respot_balls respots the jumped ball (state off_table) per п. 25.
    R = balls["2"].params.R
    for i in range(4, 16):
        del balls[str(i)]
    del balls["1"]  # clear the задняя отметка so the jump lands exactly on it
    balls["2"].state.rvw[0] = [0.3 * table.w, 0.3 * table.l, R]
    balls["2"].state.s = const.off_table  # «выскочивший шар»
    balls["3"].state.rvw[0] = [0.6 * table.w, 0.6 * table.l, R]
    balls["3"].state.s = const.stationary
    balls["cue"].state.rvw[0] = [0.7 * table.w, 0.4 * table.l, R]
    balls["cue"].state.s = const.stationary
    foul_game = rp.RussianFreePyramid(players=[Player("A"), Player("B")])
    foul_game.shot_info = ShotInfo(
        player=foul_game.players[0],
        legal=False,
        reason=rp.FreePyramidReason.JUMPED_BALL,
        turn_over=True,
        game_over=False,
        winner=None,
        score=Counter(),
    )
    foul_game.respot_balls(SimpleNamespace(balls=balls, table=table, events=[], t=0.0))
    mark = (table.w / 2, rp.REAR_SPOT_FRACTION * table.l)
    assert balls["2"].state.s == const.stationary
    assert np.allclose(balls["2"].xyz[:2], mark), balls["2"].xyz
    assert balls["2"].history[-1].s == const.stationary
    # The foul also removes the штрафной шар: exactly one live ball left.
    live = [
        b.id for b in balls.values() if b.id != "cue" and b.state.s in const.on_table
    ]
    assert len(live) == 1, live

    print("jump foul OK | JUMPED_BALL reason, break included, respot + penalty")


def check_legal_completion_scenario() -> None:
    """Real simulated legal completion without a pot (п. 20 two-cushion clause).

    A dead-straight pot always scratches in this physics engine, so the
    ordinary-legal path is verified via clause 2a: after cue-object contact,
    ball "2" travels to two distinct cushions. Scoring on a legal pot is
    covered by ``check_break_scenario``.
    """

    import pooltool as pt
    import pooltool.constants as const
    from pooltool.objects.cue.datatypes import Cue

    table, balls = _russian_table_and_rack()
    R = balls["1"].params.R

    for i in range(3, 16):
        del balls[str(i)]
    balls["2"].state.rvw[0] = [0.60, 1.50, R]
    balls["2"].state.s = const.stationary
    balls["cue"].state.rvw[0] = [0.90, 0.90, R]

    cue = Cue.default()
    cue.set_state(cue_ball_id="cue")
    system = pt.System(table=table, balls=balls, cue=cue)
    system.cue.set_state(V0=4.0, phi=pt.aim.at_ball(system, "2"))
    pt.simulate(system, inplace=True)

    assert rp.potted_ball_ids(system) == [], "nothing must be potted"
    assert not rp.is_cue_ball_potted(system)
    legal, reason = rp.evaluate_free_shot(system, is_break=False)
    assert legal and reason == rp.FreePyramidReason.LEGAL, (
        "ball 2 on two distinct cushions must complete the shot"
    )

    game = rp.RussianFreePyramid(players=[Player("A"), Player("B")])
    game.shot_number = 3  # mid-game: ordinary (non-break) evaluation
    game.process_and_advance(system)

    info = game.shot_info
    assert info.legal and info.reason == rp.FreePyramidReason.LEGAL
    assert game.score["A"] == 0 and game.score["B"] == 0
    # Legal but nothing potted -> the turn passes, game continues.
    assert info.turn_over and not info.game_over

    # No respots, no penalty ball on a legal stroke.
    live = [
        b.id
        for b in system.balls.values()
        if b.id != "cue" and b.state.s in const.on_table
    ]
    assert set(live) == {"1", "2"}

    # Opponent plays the table as it lies; both object balls are hittable.
    c = game.shot_constraints
    assert c.ball_in_hand == BallInHandOptions.NONE
    assert c.movable == [] and c.cueable == ["cue"]
    assert c.hittable == ("1", "2")
    assert game.active_idx == 1 and game.turn_number == 1
    assert game.shot_number == 4

    print("legal completion OK | п.20 two-cushion clause, no pot -> turn passes")


def check_break_scenario() -> None:
    """Real simulated break from the house: legal per п. 12, breaker continues."""

    import pooltool as pt
    from pooltool.objects.cue.datatypes import Cue

    table, balls = _russian_table_and_rack()

    # Break from the break spawn point straight into the apex ball. The rack
    # generator jitters positions (~1e-5), so assert house membership.
    cue_x, cue_y = (float(v) for v in balls["cue"].xyz[:2])
    assert abs(cue_x - table.w / 2) < 1e-3
    assert abs(cue_y - rp.HOUSE_DEFAULT_Y_FRACTION * table.l) < 1e-3
    cue = Cue.default()
    cue.set_state(cue_ball_id="cue")
    system = pt.System(table=table, balls=balls, cue=cue)
    # Straight at the apex ball (the rack ball nearest the задняя отметка).
    mark = (table.w / 2, rp.REAR_SPOT_FRACTION * table.l)
    apex = min(
        (b for b in balls.values() if b.id != "cue"),
        key=lambda b: (
            float(b.state.rvw[0, 0]) ** 2 + (float(b.state.rvw[0, 1]) - mark[1]) ** 2
        ),
    )
    system.cue.set_state(V0=9.0, phi=pt.aim.at_ball(system, apex.id))
    pt.simulate(system, inplace=True)

    t0 = rp.first_contact_time(system)
    assert t0 is not None, "break must contact the apex ball"
    contacts = rp.cushion_contacts(system, after=t0)
    num_cushioned = len([b for b in contacts if b != "cue"])
    potted = rp.potted_ball_ids(system)
    legal, reason = rp.evaluate_free_shot(system, is_break=True)

    assert legal, f"break must be legal (potted={potted}, cushioned={num_cushioned})"
    assert reason == rp.FreePyramidReason.LEGAL_BREAK

    game = rp.RussianFreePyramid(players=[Player("A"), Player("B")])
    game.process_and_advance(system)
    assert game.shot_info.legal
    assert game.score["A"] == len(potted), "each potted ball scores on the break"
    # The breaker continues only if something was potted.
    assert game.shot_info.turn_over == (len(potted) == 0)

    print(
        f"break OK | LEGAL_BREAK (potted={len(potted)}, "
        f"cushioned object balls={num_cushioned})"
    )


def main() -> None:
    check_foundation()
    check_constraints()
    check_crossing()
    check_real_system()
    check_respot_machinery()
    check_svojyak_respot()
    check_scratch_integration()
    check_copy()
    check_jump_foul()
    check_legal_completion_scenario()
    check_break_scenario()
    print("STEP 5 (artifact 4/4) VERIFICATION: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
