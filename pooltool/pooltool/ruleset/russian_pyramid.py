"""Russian pyramid («Русская пирамида») rulesets.

This module implements the four major competitive disciplines of Russian
billiards as pooltool :class:`~pooltool.ruleset.datatypes.Ruleset` classes:

- ``RussianFreePyramid`` — «Свободная пирамида» (Free Pyramid). Simplified
  rules: any object ball may be struck first, called shots are not required,
  and pocketing the cue ball («свояк») after contacting an object ball is
  legal and scores.
- ``RussianCombinedPyramid`` — «Комбинированная пирамида» (Combined /
  Moscow). The cue ball may be pocketed («свояк») off any object ball; in
  exchange the shooter removes one object ball of their choice to their
  shelf and re-enters the cue ball with a stroke from the house (п. 21),
  whose first contact must lie outside the house.
- ``RussianDynamicPyramid`` — «Динамичная пирамида» (Dynamic / Nevskaya).
  Variations in shot legality and scoring (ball-number-based scoring).
- ``RussianClassicPyramid`` — «Классическая пирамида» (Classic). The
  strictest variant, typically requiring called («заказ») shots.

All four disciplines are played on a 12 ft × 6 ft table (370 × 180 cm
playing surface) with 16 balls of Ø 67 mm: 15 white object balls numbered
1–15 (IDs ``"1"``–``"15"``) and a single cue ball (ID ``"cue"``, rendered
red or yellow).

Rule fidelity targets the official rules of the Russian Billiards Federation
(ФБСР — Федерация бильярдного спорта России). Every intentional deviation
from the official rules is recorded in ``RULES_DEVIATIONS.md`` at the
repository root.

Performance (Step 10 of ``PROGRESS.md``): event inspection is single-pass
(:class:`_EventScan`), keeping the ruleset overhead per simulated stroke in
the tens-of-microseconds range — real-time-safe next to the physics engine.

Status
------
Fully implemented (steps 5–9 of the implementation plan — see
``PROGRESS.md`` at the repository root): all four disciplines —
**Free Pyramid** (Step 5), **Combined Pyramid** (Step 7), **Dynamic
Pyramid** (Step 8) and **Classic Pyramid** (Step 9) — implement the
general-pyramid legality predicates (п. 12 / п. 20), discipline-specific
call-shot and cue-ball rules, scoring, constraint handling, respot
machinery (п. 25) and foul administration.
"""

from __future__ import annotations

import copy

import attrs
import numpy as np

import pooltool.constants as const
from pooltool.events.datatypes import EventType
from pooltool.objects.ball.datatypes import BallState
from pooltool.objects.table.components import Pocket
from pooltool.objects.table.datatypes import Table
from pooltool.ruleset.datatypes import (
    BallInHandOptions,
    Player,
    Ruleset,
    ShotConstraints,
    ShotInfo,
)
from pooltool.ruleset.utils import get_ball_ids_on_table, respot
from pooltool.system.datatypes import System
from pooltool.utils.strenum import StrEnum, auto

__all__ = [
    "RussianClassicPyramid",
    "RussianCombinedPyramid",
    "RussianDynamicPyramid",
    "RussianFreePyramid",
]


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------

CUE_BALL_ID = "cue"
"""Identifier of the colored cue ball («биток»).

All four pyramid disciplines share a single colored cue ball (rendered red
via the ``russian_pyramid`` ballset) and 15 numbered white object balls with
IDs ``"1"`` .. ``"15"``. See ``pooltool/layouts.py`` for the rack layout.
"""

REAR_SPOT_FRACTION = 0.75
"""Longitudinal position of the задняя отметка (rear mark), as a fraction.

The rear mark lies on the longitudinal centerline a quarter of the playing
surface's length away from the rear (foot) rail; racked pyramid apexes and
respotted balls (п. 25) reference it. Matches the rack seed in
``pooltool.layouts._get_russian_pyramid_rack``.
"""

HOUSE_LINE_FRACTION = 0.25
"""Longitudinal position of the линия дома (house line), as a fraction.

The house line passes through the передняя отметка (front mark), one quarter
of the playing surface's length away from the front (head) rail. The house —
the area between this line and the front rail — is where the break is played
from (п. 12) and where a scratched cue ball is re-introduced (п. 22).
"""

HOUSE_DEFAULT_Y_FRACTION = 0.23
"""Default longitudinal cue-ball placement inside the house, as a fraction.

Deterministic default for autonomous play when the cue ball must be
re-introduced from the house after a scratch. Chosen to match the break
spawn point of ``pooltool.layouts._get_russian_pyramid_rack`` so that the
default scratch position coincides with the familiar break position.
"""

_RESPOT_GAP = 1e-3
"""Minimum clearance kept between respotted balls and neighbouring balls.

п. 25.2 requires respotted balls to be placed "as close as possible, but not
touching". One millimetre keeps the placement physically unambiguous while
remaining visually faithful to how referees place balls.
"""

FREE_TARGET_SCORE = 8
"""Winning score for Free Pyramid («Свободная пирамида» / «Американка»).

Verified against the official rules (International Pyramid Confederation
rules of 2006, aligned with the ФБСР amateur discipline): the game is a race
to **eight** points, where each legally pocketed ball — including a «свояк»
— is worth one point. This supersedes the initially assumed race-to-71,
which applies to *Classic* pyramid only (see ``PROGRESS.md``, Step 5
decisions, and ``RULES_DEVIATIONS.md``).
"""

COMBINED_TARGET_SCORE = 8
"""Winning score for Combined Pyramid («Комбинированная пирамида»).

Verified against the official ФБСР rules (п. 1 «Цель игры»: «Первым (раньше
соперника) набрать восемь очков», fbsrf.ru) and corroborating rule
transcripts. Each legally pocketed object ball counts one point; a legal
«свояк» is compensated by removing one object ball to the shooter's shelf
(also one point).
"""

DYNAMIC_TARGET_SCORE = 8
"""Winning score for Dynamic Pyramid («Динамичная пирамида» / «Невская»).

Verified against the official rules (п. 1 «Цель игры»: «Первым (раньше
соперника) набрать восемь очков» — IPC/ФБСР rule transcripts, duplet.news
rules library). Each legally pocketed object ball counts one point (п. 9); a
legal «свояк» is compensated by removing one object ball to the shooter's
shelf (one point, п. 5.2). The discipline's defining feature is the
table-wide ball-in-hand re-introduction of the cue ball (п. 6.1) and the
cue-ball potting ban on such introduction strokes (п. 6.4/6.5).
"""

CLASSIC_TARGET_SCORE = 71
"""Winning score for Classic Pyramid («Классическая пирамида»).

Verified against the official rules (п. 1 «Цель игры»: «Первым (раньше
соперника) набрать 71 или более очков» — ФБСР/МФБС rule transcripts,
probilliard.by / bayconur.ru / sbsnsk.ru). The 51- and 8-point variants
listed in some rule libraries are league modifications, not the ФБСР
discipline.
"""

CLASSIC_ONE_BALL_VALUE = 11
"""Point value of the 1-ball («единица» / «туз») in Classic Pyramid.

п. 5.1: «За каждый правильно забитый прицельный шар к текущему счету игрока
прибавляется число очков, равное его номеру, а за сыгранную единицу (туза) —
11 очков». Every other ball is worth its number, making the total pool 130
points; the last remaining object ball additionally carries
:data:`CLASSIC_LAST_BALL_BONUS` (10), bringing the full total to 140.
"""

CLASSIC_LAST_BALL_BONUS = 10
"""Bonus added to the last remaining object ball in Classic Pyramid.

п. 5.1: «К последнему оставшемуся на столе прицельному шару вне зависимости
от его номера прибавляется 10 очков». Implemented as: when exactly one
object ball is on the table at the start of the stroke and it is pocketed,
its value is increased by 10.
"""

CLASSIC_FOUL_POINTS = 5
"""Points transferred for each violation in Classic Pyramid.

п. 5.6: «За каждое нарушение с текущего счета нарушителя списывается
5 очков, а к текущему счету соперника прибавляется 5 очков». Unlike Free/
Combined/Dynamic, Classic has no «штрафной шар» — the penalty is purely
points-based (the general rules reserve the ball removal for those three
disciplines). Offender scores may go negative; the transferred points keep
the score sum constant.
"""


# ---------------------------------------------------------------------------
# Reason taxonomy
# ---------------------------------------------------------------------------


class FreePyramidReason(StrEnum):
    """Why a Free Pyramid shot was judged legal or illegal.

    Members mirror the violation taxonomy of the official rules so that
    :attr:`~pooltool.ruleset.datatypes.ShotInfo.reason` stays
    machine-readable while remaining human-readable (a ``StrEnum`` value
    is its own display string).
    """

    NONE = auto()
    """The shot has not been evaluated."""

    LEGAL = auto()
    """Legal shot satisfying «Общие правила пирамиды» п. 20."""

    LEGAL_BREAK = auto()
    """Legal opening break satisfying «Общие правила пирамиды» п. 12."""

    NO_CONTACT = auto()
    """The cue ball did not contact any object ball (foul)."""

    ILLEGAL_COMPLETION = auto()
    """Shot failed the п. 20 completion conditions (foul)."""

    ILLEGAL_BREAK = auto()
    """Opening break failed the п. 12 requirements (foul)."""

    JUMPED_BALL = auto()
    """A ball jumped off the table («выскочивший шар») — foul per the
    general foul list (п. 22: выскочивший биток или прицельный шар)."""


class CombinedPyramidReason(StrEnum):
    """Why a Combined Pyramid shot was judged legal or illegal.

    Mirrors :class:`FreePyramidReason` plus the п. 21 house-stroke
    violation specific to the Combined («Московская») discipline.
    """

    NONE = auto()
    """The shot has not been evaluated."""

    LEGAL = auto()
    """Legal shot satisfying «Общие правила пирамиды» п. 20."""

    LEGAL_BREAK = auto()
    """Legal opening break satisfying «Общие правила пирамиды» п. 12."""

    NO_CONTACT = auto()
    """The cue ball did not contact any object ball (foul)."""

    ILLEGAL_COMPLETION = auto()
    """Shot failed the п. 20 completion conditions (foul)."""

    ILLEGAL_BREAK = auto()
    """Opening break failed the п. 12 requirements (foul)."""

    JUMPED_BALL = auto()
    """A ball jumped off the table («выскочивший шар») — foul per the
    general foul list (п. 22: выскочивший биток или прицельный шар)."""

    HOUSE_FIRST_CONTACT = auto()
    """A stroke played from the house first contacted a ball standing
    inside the house (п. 21 violation)."""


class DynamicPyramidReason(StrEnum):
    """Why a Dynamic Pyramid shot was judged legal or illegal.

    Mirrors :class:`FreePyramidReason` plus the п. 6.4/6.5 violation specific
    to the ball-in-hand («удар с руки») introduction strokes of the Dynamic
    («Невская») discipline.
    """

    NONE = auto()
    """The shot has not been evaluated."""

    LEGAL = auto()
    """Legal shot satisfying «Общие правила пирамиды» п. 20."""

    LEGAL_BREAK = auto()
    """Legal opening break satisfying «Общие правила пирамиды» п. 12."""

    NO_CONTACT = auto()
    """The cue ball did not contact any object ball (foul)."""

    ILLEGAL_COMPLETION = auto()
    """Shot failed the п. 20 completion conditions (foul)."""

    ILLEGAL_BREAK = auto()
    """Opening break failed the п. 12 requirements (foul)."""

    JUMPED_BALL = auto()
    """A ball jumped off the table («выскочивший шар») — foul per the
    general foul list (п. 22: выскочивший биток или прицельный шар)."""

    IN_HAND_CUE_POT = auto()
    """The cue ball was pocketed on a ball-in-hand («удар с руки»)
    introduction stroke — foul per «Динамичная пирамида» п. 6.4/6.5: on a
    stroke with the cue ball in hand only object balls may be pocketed."""


class ClassicPyramidReason(StrEnum):
    """Why a Classic Pyramid shot was judged legal or illegal.

    Mirrors the shared foul taxonomy plus the Classic («Классическая»)
    specifics: pocketing the cue ball is always a foul (п. 5.5), house
    strokes follow п. 21, and the call-shot requirement («заказ», п. 5.2)
    adds the not-a-foul ``UNCALLED_POT`` outcome.
    """

    NONE = auto()
    """The shot has not been evaluated."""

    LEGAL = auto()
    """The called («заказанный») object ball was pocketed in the called
    pocket; every ball potted on the stroke scores (п. 5.2/5.3)."""

    LEGAL_BREAK = auto()
    """Legal opening break satisfying «Общие правила пирамиды» п. 12 (the
    break requires no call)."""

    NO_CONTACT = auto()
    """The cue ball did not contact any object ball (foul)."""

    ILLEGAL_COMPLETION = auto()
    """Shot failed the п. 20 completion conditions (foul)."""

    ILLEGAL_BREAK = auto()
    """Opening break failed the п. 12 requirements (foul)."""

    JUMPED_BALL = auto()
    """A ball jumped off the table («выскочивший шар») — foul per the
    general foul list (п. 22: выскочивший биток или прицельный шар)."""

    CUE_POTTED = auto()
    """The cue ball was pocketed («свояк») — foul per «Классическая
    пирамида» п. 5.5; the classic game has no legal «свояк»."""

    HOUSE_FIRST_CONTACT = auto()
    """A stroke played from the house (penalty stroke after a scratch,
    п. 5.5, or the 70:70 continuation stroke, п. 5.7) first contacted a
    ball standing inside the house (п. 21 violation)."""

    UNCALLED_POT = auto()
    """The stroke completed per п. 20 but the called ball was not pocketed
    in the called pocket (п. 5.4): not a foul — potted balls are respotted,
    no points are scored, and the turn passes."""


# ---------------------------------------------------------------------------
# Single-pass event scan (ruleset hot path)
# ---------------------------------------------------------------------------

_CUSHION_EVENT_TYPE_SET = frozenset(
    (EventType.BALL_LINEAR_CUSHION, EventType.BALL_CIRCULAR_CUSHION)
)


class _EventScan:
    """Single chronological pass over a shot's event list.

    Every event-based ruleset helper used to re-filter ``shot.events``
    through chained :mod:`pooltool.events.filter` closures — one full
    ``build_shot_info`` / ``next_shot_constraints`` / ``respot_balls``
    round walked the same list up to a dozen times. A single walk that
    buckets every event kind replaces those passes (profiled in Step 10 of
    ``PROGRESS.md``: the chained closures were ~40% of the ruleset
    evaluation cost).

    Chronological order is the invariant the simulation engine guarantees
    for event lists (``pooltool.events.filter.by_time`` enforces it);
    the scan relies on it only for the *first* cue-ball contact.
    """

    __slots__ = (
        "cushion_events",
        "first_contact_id",
        "first_contact_time",
        "off_table_ids",
        "pocket_map",
        "pocketed_ids",
    )

    def __init__(self, shot: System) -> None:
        first_time: float | None = None
        first_id: str | None = None
        pocketed: list[str] = []
        off_table: list[str] = []
        pocket_map: dict[str, str] = {}
        cushion_events: list[tuple[float, str, str]] = []

        ball_ball = EventType.BALL_BALL
        ball_pocket = EventType.BALL_POCKET
        ball_off_table = EventType.BALL_OFF_TABLE
        cue = CUE_BALL_ID

        for event in shot.events:
            event_type = event.event_type
            if event_type in _CUSHION_EVENT_TYPE_SET:
                agents = event.agents
                cushion_events.append((event.time, agents[0].id, agents[1].id))
            elif event_type == ball_ball:
                if first_time is None:
                    agents = event.agents
                    id1, id2 = agents[0].id, agents[1].id
                    if id1 == cue:
                        first_time, first_id = event.time, id2
                    elif id2 == cue:
                        first_time, first_id = event.time, id1
            elif event_type == ball_pocket:
                agents = event.agents
                pocketed.append(agents[0].id)
                pocket_map[agents[0].id] = agents[1].id
            elif event_type == ball_off_table:
                off_table.append(event.agents[0].id)

        self.first_contact_time = first_time
        self.first_contact_id = first_id
        self.pocketed_ids = pocketed
        self.off_table_ids = off_table
        self.pocket_map = pocket_map
        self.cushion_events = cushion_events

    def cushion_contacts(
        self,
        after: float | None = None,
        exclude: set[str] = frozenset(),
    ) -> dict[str, set[str]]:
        """Ball → set of distinct cushions contacted.

        Args:
            after: Only contacts strictly after this time are considered.
            exclude: Ball IDs left out of the mapping.
        """
        contacts: dict[str, set[str]] = {}
        for time, ball_id, cushion_id in self.cushion_events:
            if after is not None and time <= after:
                continue
            if ball_id in exclude:
                continue
            contacts.setdefault(ball_id, set()).add(cushion_id)
        return contacts

    def potted_object_ball_ids(self) -> list[str]:
        """Object balls pocketed during the shot, ascending numeric order."""
        return sorted(
            (ball_id for ball_id in self.pocketed_ids if ball_id != CUE_BALL_ID),
            key=int,
        )


# ---------------------------------------------------------------------------
# Shared state-extraction helpers (module-level, pure)
# ---------------------------------------------------------------------------


def object_ball_ids(shot: System) -> list[str]:
    """IDs of the numbered object balls tracked in the shot system.

    Returned in ascending numeric order (``"1"`` .. ``"15"``). The list
    includes balls already pocketed during the shot; use
    :func:`live_object_ball_ids` when only balls on the table are needed.
    """
    return sorted(
        (ball_id for ball_id in shot.balls if ball_id != CUE_BALL_ID),
        key=int,
    )


def live_object_ball_ids(shot: System, at_start: bool = False) -> list[str]:
    """IDs of object balls that are on the table (not pocketed).

    Args:
        shot: The shot data from the system.
        at_start: If True, evaluate the state at the start of the shot
            (``ball.history[0]``); if False (default), the end-of-shot state.
    """
    return sorted(
        get_ball_ids_on_table(shot, at_start, {CUE_BALL_ID}),
        key=int,
    )


def potted_ball_ids(shot: System) -> list[str]:
    """All ball IDs pocketed during the shot, in event order (cue included)."""
    return list(_EventScan(shot).pocketed_ids)


def potted_object_ball_ids(shot: System) -> list[str]:
    """Object ball IDs pocketed during the shot, in ascending numeric order."""
    return _EventScan(shot).potted_object_ball_ids()


def is_cue_ball_potted(shot: System) -> bool:
    """Whether the cue ball («свояк» candidate) was pocketed during the shot."""
    return CUE_BALL_ID in _EventScan(shot).pocketed_ids


def first_object_contact(shot: System) -> str | None:
    """ID of the first object ball contacted by the cue ball, or None.

    Returns None when the cue ball contacted no object ball at all during
    the shot (a foul in every pyramid discipline).
    """
    return _EventScan(shot).first_contact_id


# ---------------------------------------------------------------------------
# Free Pyramid legality machinery
# ---------------------------------------------------------------------------


def first_contact_time(shot: System) -> float | None:
    """Time of the first cue-ball-to-object-ball collision, or None."""
    return _EventScan(shot).first_contact_time


def cushion_contacts(shot: System, after: float | None = None) -> dict[str, set[str]]:
    """Map each ball ID to the set of distinct cushions it contacted.

    Args:
        after: If given, only contacts strictly after this time are
            considered (used to ignore contacts made before the cue ball's
            first contact with an object ball).
    """
    return _EventScan(shot).cushion_contacts(after=after)


def crossed_center_line(shot: System, after: float | None = None) -> set[str]:
    """Ball IDs whose trajectory crossed the central line (``y = l / 2``).

    The central line is the transverse midline through the middle pockets.
    Vectorized per ball: a ball is flagged when its recorded history
    contains positions on both sides of the line (optionally restricted to
    states at or after ``after``). Between consecutive history samples the
    trajectory is treated as straight, which is exact for rolling motion
    and a close approximation while a ball slides.
    """
    half = shot.table.l / 2

    crossed: set[str] = set()
    for ball in shot.balls.values():
        ts = ball.history.ts
        if not len(ts):
            continue
        start = 0 if after is None else int(np.searchsorted(ts, after, side="left"))
        y = ball.history.rvws[start:, 0, 1]
        if len(y) < 2:
            continue
        sides = y > half
        if sides.any() and not sides.all():
            crossed.add(ball.id)
    return crossed


def _is_legal_break_shot(shot: System, scan: _EventScan) -> bool:
    """п. 12 core on a precomputed :class:`_EventScan`."""
    t0 = scan.first_contact_time
    if t0 is None:
        return False

    if scan.pocketed_ids:
        return True

    contacts = scan.cushion_contacts(after=t0, exclude={CUE_BALL_ID})
    cushioned = len(contacts)
    if cushioned >= 3:
        return True
    if cushioned < 2:
        return False

    crossed = crossed_center_line(shot, after=t0)
    return any(ball_id in crossed for ball_id in contacts)


def is_legal_break_shot(shot: System) -> bool:
    """«Общие правила пирамиды» п. 12 — correct opening break.

    The break is correct when a ball is potted (a «свояк» on the break also
    qualifies), or at least three distinct object balls touch a cushion, or
    two distinct object balls touch a cushion and at least one object ball
    crosses the central line.
    """
    return _is_legal_break_shot(shot, _EventScan(shot))


def _satisfies_completion(shot: System, scan: _EventScan) -> bool:
    """п. 20 core on a precomputed :class:`_EventScan`."""
    if scan.pocketed_ids:
        return True

    t0 = scan.first_contact_time
    if t0 is None:
        return False

    contacts = scan.cushion_contacts(after=t0)
    if not contacts:
        return False

    crossed = crossed_center_line(shot, after=t0)
    return any(
        len(cushions) >= 2 or (ball_id in crossed and cushions)
        for ball_id, cushions in contacts.items()
    )


def satisfies_completion_requirements(shot: System) -> bool:
    """«Общие правила пирамиды» п. 20 — correctly completed stroke.

    Implemented conditions, evaluated after the cue ball's first contact
    with an object ball: any ball is potted (clause 1), a ball touches two
    distinct cushions (clause 2a), or a ball touches a cushion and crosses
    the central line in either order (clauses 3a / 4a). The sub-clauses in
    which a ball drives another ball to a cushion or across the line, or
    touches a ball frozen to a cushion, are omitted — see
    ``RULES_DEVIATIONS.md``.
    """
    return _satisfies_completion(shot, _EventScan(shot))


def _judge_free(
    shot: System, is_break: bool, scan: _EventScan
) -> tuple[bool, FreePyramidReason]:
    """Free Pyramid judging on a precomputed :class:`_EventScan`."""
    if scan.first_contact_id is None:
        return False, FreePyramidReason.NO_CONTACT

    if scan.off_table_ids:
        return False, FreePyramidReason.JUMPED_BALL

    if is_break:
        legal = _is_legal_break_shot(shot, scan)
        return (
            legal,
            FreePyramidReason.LEGAL_BREAK if legal else FreePyramidReason.ILLEGAL_BREAK,
        )

    legal = _satisfies_completion(shot, scan)
    return (
        legal,
        FreePyramidReason.LEGAL if legal else FreePyramidReason.ILLEGAL_COMPLETION,
    )


def evaluate_free_shot(shot: System, is_break: bool) -> tuple[bool, FreePyramidReason]:
    """Judge a Free Pyramid stroke; returns ``(legal, reason)``.

    Evaluation order mirrors the general foul list: no contact first, then a
    jump («выскочивший шар» fouls on any stroke, break included), then the
    break-specific (п. 12) or ordinary completion (п. 20) requirements.
    """
    return _judge_free(shot, is_break, _EventScan(shot))


# ---------------------------------------------------------------------------
# Combined Pyramid legality machinery («Комбинированная пирамида»)
# ---------------------------------------------------------------------------


def _violates_house_contact(shot: System, scan: _EventScan) -> bool:
    """п. 21 core on a precomputed :class:`_EventScan`."""
    cue = shot.balls[CUE_BALL_ID]
    if not len(cue.history):
        return False

    house_y = HOUSE_LINE_FRACTION * shot.table.l
    if cue.history[0].rvw[0, 1] >= house_y:
        return False  # not a house stroke

    live = [
        ball
        for ball in shot.balls.values()
        if ball.id != CUE_BALL_ID
        and len(ball.history)
        and ball.history[0].s in const.on_table
    ]
    if live and all(ball.history[0].rvw[0, 1] < house_y for ball in live):
        return False  # all balls in the house: the opposite side becomes the house

    t0 = scan.first_contact_time
    if t0 is None:
        return False  # no contact at all is judged by the NO_CONTACT foul

    contacted = shot.balls[scan.first_contact_id]
    ts = contacted.history.ts
    if not len(ts):
        return False
    # The first-contacted ball is stationary until t0, so its position at
    # contact equals its last recorded position at or before t0 (robust for
    # both dense simulated histories and sparse synthetic ones).
    idx = min(int(np.searchsorted(ts, t0, side="right")) - 1, len(ts) - 1)
    idx = max(idx, 0)
    return bool(contacted.history.rvws[idx, 0, 1] < house_y)


def violates_house_contact(shot: System) -> bool:
    """п. 21 house-stroke restriction: first contact must be outside the house.

    A stroke played with the cue ball standing inside the house (the premium
    stroke after a legal «свояк», the penalty stroke after a foul scratch,
    or any stroke played as it lies from the house) must first contact an
    object ball standing outside the house; contacting a ball that is also
    inside the house is a violation. If at stroke start every live object
    ball stands inside the house, the stroke is played from the opposite
    side of the table, which temporarily becomes the house — the restriction
    does not apply.
    """
    return _violates_house_contact(shot, _EventScan(shot))


def _judge_combined(
    shot: System, is_break: bool, scan: _EventScan
) -> tuple[bool, CombinedPyramidReason]:
    """Combined Pyramid judging on a precomputed :class:`_EventScan`."""
    if scan.first_contact_id is None:
        return False, CombinedPyramidReason.NO_CONTACT

    if scan.off_table_ids:
        return False, CombinedPyramidReason.JUMPED_BALL

    if not is_break and _violates_house_contact(shot, scan):
        return False, CombinedPyramidReason.HOUSE_FIRST_CONTACT

    if is_break:
        legal = _is_legal_break_shot(shot, scan)
        return (
            legal,
            CombinedPyramidReason.LEGAL_BREAK
            if legal
            else CombinedPyramidReason.ILLEGAL_BREAK,
        )

    if _satisfies_completion(shot, scan):
        return True, CombinedPyramidReason.LEGAL
    return False, CombinedPyramidReason.ILLEGAL_COMPLETION


def evaluate_combined_shot(
    shot: System, is_break: bool
) -> tuple[bool, CombinedPyramidReason]:
    """Judge a Combined Pyramid stroke; returns ``(legal, reason)``.

    Evaluation order mirrors the general foul list: no contact first, then
    a jump («выскочивший шар» fouls on any stroke, break included), then
    the п. 21 house-stroke restriction (non-break strokes played from the
    house), then the break-specific (п. 12) or ordinary completion (п. 20)
    requirements.
    """
    return _judge_combined(shot, is_break, _EventScan(shot))


# ---------------------------------------------------------------------------
# Dynamic Pyramid legality machinery («Динамичная пирамида»)
# ---------------------------------------------------------------------------


def _judge_dynamic(
    shot: System, is_break: bool, is_in_hand: bool, scan: _EventScan
) -> tuple[bool, DynamicPyramidReason]:
    """Dynamic Pyramid judging on a precomputed :class:`_EventScan`."""
    if scan.first_contact_id is None:
        return False, DynamicPyramidReason.NO_CONTACT

    if scan.off_table_ids:
        return False, DynamicPyramidReason.JUMPED_BALL

    if is_in_hand and CUE_BALL_ID in scan.pocketed_ids:
        return False, DynamicPyramidReason.IN_HAND_CUE_POT

    if is_break:
        legal = _is_legal_break_shot(shot, scan)
        return (
            legal,
            DynamicPyramidReason.LEGAL_BREAK
            if legal
            else DynamicPyramidReason.ILLEGAL_BREAK,
        )

    if _satisfies_completion(shot, scan):
        return True, DynamicPyramidReason.LEGAL
    return False, DynamicPyramidReason.ILLEGAL_COMPLETION


def evaluate_dynamic_shot(
    shot: System, is_break: bool, is_in_hand: bool
) -> tuple[bool, DynamicPyramidReason]:
    """Judge a Dynamic Pyramid stroke; returns ``(legal, reason)``.

    Evaluation order mirrors the general foul list: no contact first, then a
    jump («выскочивший шар» fouls on any stroke, break included), then the
    introduction-stroke restriction of the Dynamic discipline — the cue ball
    may not be pocketed on a stroke played with ball in hand
    («Динамичная пирамида» п. 6.4/6.5) — then the break-specific (п. 12) or
    ordinary completion (п. 20) requirements.
    """
    return _judge_dynamic(shot, is_break, is_in_hand, _EventScan(shot))


# ---------------------------------------------------------------------------
# Classic Pyramid legality machinery («Классическая пирамида»)
# ---------------------------------------------------------------------------


def ball_value(ball_id: str) -> int:
    """Point value of a potted object ball («Классическая пирамида» п. 5.1).

    Every ball scores its number; the 1-ball («единица» / «туз») scores
    :data:`CLASSIC_ONE_BALL_VALUE` (11) points.
    """
    return CLASSIC_ONE_BALL_VALUE if ball_id == "1" else int(ball_id)


def last_remaining_object_ball(shot: System) -> str | None:
    """The sole object ball on the table at the start of the stroke, or None.

    The +10 bonus of «Классическая пирамида» п. 5.1 attaches to «последний
    оставшийся на столе прицельный шар» — the ball that is the only object
    ball left. Returns None when zero or several object balls were live at
    the start (a simultaneous pot of the final two balls therefore earns no
    bonus — see ``RULES_DEVIATIONS.md``).
    """
    live_at_start = live_object_ball_ids(shot, at_start=True)
    return live_at_start[0] if len(live_at_start) == 1 else None


def classic_pot_points(shot: System, potted_objects: list[str]) -> int:
    """Total Classic Pyramid points earned for the stroke's potted balls.

    Each ball scores :func:`ball_value`; the last remaining object ball
    (when it is among the potted) additionally scores
    :data:`CLASSIC_LAST_BALL_BONUS` (п. 5.1).
    """
    last = last_remaining_object_ball(shot)
    return sum(
        ball_value(ball_id) + (CLASSIC_LAST_BALL_BONUS if ball_id == last else 0)
        for ball_id in potted_objects
    )


def potted_ball_pocket_map(shot: System) -> dict[str, str]:
    """Map each ball pocketed during the shot to the pocket it fell into.

    Built from the BALL_POCKET events; when a ball appears in several events
    (not producible by the event-based engine), the last event wins.
    """
    return dict(_EventScan(shot).pocket_map)


def called_ball_potted_as_ordered(
    shot: System,
    ball_call: str | None,
    pocket_call: str | None,
) -> bool:
    """Whether the called («заказанный») ball fell into the called pocket.

    «Классическая пирамида» п. 5.2: before the stroke the player declares a
    specific object ball and a specific pocket. The call is honored only
    when that exact ball is pocketed in that exact pocket (п. 5.3
    «правильное сыгрывание заказанного шара»). A missing call never
    honors.
    """
    if ball_call is None or pocket_call is None:
        return False
    return potted_ball_pocket_map(shot).get(ball_call) == pocket_call


def _judge_classic(
    shot: System,
    is_break: bool,
    ball_call: str | None,
    pocket_call: str | None,
    scan: _EventScan,
) -> tuple[bool, ClassicPyramidReason]:
    """Classic Pyramid judging on a precomputed :class:`_EventScan`."""
    if scan.first_contact_id is None:
        return False, ClassicPyramidReason.NO_CONTACT

    if scan.off_table_ids:
        return False, ClassicPyramidReason.JUMPED_BALL

    if CUE_BALL_ID in scan.pocketed_ids:
        return False, ClassicPyramidReason.CUE_POTTED

    if not is_break and _violates_house_contact(shot, scan):
        return False, ClassicPyramidReason.HOUSE_FIRST_CONTACT

    if is_break:
        legal = _is_legal_break_shot(shot, scan)
        return (
            legal,
            ClassicPyramidReason.LEGAL_BREAK
            if legal
            else ClassicPyramidReason.ILLEGAL_BREAK,
        )

    if not _satisfies_completion(shot, scan):
        return False, ClassicPyramidReason.ILLEGAL_COMPLETION

    if (
        ball_call is not None
        and pocket_call is not None
        and scan.pocket_map.get(ball_call) == pocket_call
    ):
        return True, ClassicPyramidReason.LEGAL
    return True, ClassicPyramidReason.UNCALLED_POT


def evaluate_classic_shot(
    shot: System,
    is_break: bool,
    ball_call: str | None,
    pocket_call: str | None,
) -> tuple[bool, ClassicPyramidReason]:
    """Judge a Classic Pyramid stroke; returns ``(legal, reason)``.

    Evaluation order: the shared foul list first (no contact; a jump;
    pocketing the cue ball — п. 5.5 makes the «свояк» a foul on any stroke,
    break included; the п. 21 house restriction, detected position-based
    like in Combined), then the break-specific (п. 12) or ordinary
    completion (п. 20) requirements, and finally the call check: a stroke
    that completed per п. 20 but did not pocket the called ball in the
    called pocket is an ``UNCALLED_POT`` — not a foul, but unproductive
    (п. 5.4).
    """
    return _judge_classic(shot, is_break, ball_call, pocket_call, _EventScan(shot))


# ---------------------------------------------------------------------------
# Free Pyramid respot machinery («Общие правила пирамиды» п. 25)
# ---------------------------------------------------------------------------


def balls_off_table(shot: System) -> list[str]:
    """IDs of object balls that jumped off the table («выскочившие шары»)."""
    return sorted(
        (
            ball.id
            for ball in shot.balls.values()
            if ball.id != CUE_BALL_ID and ball.state.s == const.off_table
        ),
        key=int,
    )


def is_cue_ball_jumped(shot: System) -> bool:
    """Whether the cue ball jumped off the table during the shot."""
    return CUE_BALL_ID in _EventScan(shot).off_table_ids


def jumped_ball_ids(shot: System) -> list[str]:
    """IDs of all balls (cue included) that jumped off the table.

    The event-based detector only fires BALL_OFF_TABLE for balls that
    genuinely left the playing surface: a ball dropping into a pocket gets
    the earlier, higher-priority BALL_POCKET event instead, so no ball can
    be flagged as both potted and jumped.
    """
    return list(_EventScan(shot).off_table_ids)


def _live_positions(shot: System, exclude: set[str]) -> list[tuple[float, float]]:
    """(x, y) positions of all balls currently on the table, except ``exclude``."""
    return [
        (float(ball.state.rvw[0, 0]), float(ball.state.rvw[0, 1]))
        for ball in shot.balls.values()
        if ball.id not in exclude and ball.state.s in const.on_table
    ]


def _is_free(
    xy: tuple[float, float],
    occupied: list[tuple[float, float]],
    min_dist_sq: float,
) -> bool:
    """Whether a candidate position keeps ``min_dist`` clearance to all others."""
    return all(
        (xy[0] - ox) ** 2 + (xy[1] - oy) ** 2 >= min_dist_sq for ox, oy in occupied
    )


def spot_line_position(
    shot: System,
    occupied: list[tuple[float, float]],
    radius: float,
) -> tuple[float, float]:
    """First free position on the spotting line per «Общие правила» п. 25.

    The placement sequence on the longitudinal centerline (``x = w / 2``):

    (1) the задняя отметка itself (``REAR_SPOT_FRACTION * l``);
    (2) positions behind the mark toward the rear rail, spaced one ball
        diameter apart plus :data:`_RESPOT_GAP`;
    (3) if no room remains between the mark and the rear rail, the
        continuation of the line from the mark toward the table center.

    Raises:
        RuntimeError: If the whole line is exhausted. Unreachable in practice
            (the line holds far more than 16 slots), but kept explicit rather
            than silently degrading.
    """
    x = shot.table.w / 2
    y_mark = REAR_SPOT_FRACTION * shot.table.l
    step = 2 * radius + _RESPOT_GAP
    min_dist_sq = step**2
    y_max = shot.table.l - radius
    y_min = radius

    k = 0
    while (y := y_mark + k * step) <= y_max:
        if _is_free((x, y), occupied, min_dist_sq):
            return x, y
        k += 1

    k = 1
    while (y := y_mark - k * step) >= y_min:
        if _is_free((x, y), occupied, min_dist_sq):
            return x, y
        k += 1

    raise RuntimeError(
        "No free position along the spotting line (п. 25). "
        "This is unreachable on any real table and signals a bug."
    )


def house_default_position(
    shot: System,
    occupied: list[tuple[float, float]],
    radius: float,
) -> tuple[float, float]:
    """Deterministic default cue-ball position in the house after a scratch.

    Starts at the break spawn point (``x = w / 2``,
    ``HOUSE_DEFAULT_Y_FRACTION * l``) and scans along the longitudinal
    centerline toward the front rail until a position clear of all
    ``occupied`` balls is found. Scanning only head-ward is sufficient: the
    default spot lies less than one ball slot below the house line, so no
    admissible slot can exist between it and the line (the ball's edge must
    stay within the house, п. 22: «с руки из дома»).

    Raises:
        RuntimeError: If the house centerline is completely packed.
            Unreachable in practice, kept explicit rather than silent.
    """
    x = shot.table.w / 2
    y0 = HOUSE_DEFAULT_Y_FRACTION * shot.table.l
    step = 2 * radius + _RESPOT_GAP
    min_dist_sq = step**2
    y_min = radius

    k = 0
    while (y := y0 - k * step) >= y_min:
        if _is_free((x, y), occupied, min_dist_sq):
            return x, y
        k += 1

    raise RuntimeError(
        "No free position in the house for the scratched cue ball. "
        "This is unreachable on any real table and signals a bug."
    )


def _sync_history(shot: System, ball_id: str) -> None:
    """Append a ball's current state to its history.

    :func:`pooltool.ruleset.utils.respot` mutates only ``ball.state``, while
    history-based helpers (e.g. :func:`live_object_ball_ids`) read
    ``ball.history[-1]``. Appending the respotted state keeps both views
    consistent between ``respot_balls`` and the next ``simulate`` call (which
    resets histories anyway).
    """
    ball = shot.balls[ball_id]
    t = shot.t
    if len(ball.history) and ball.history[-1].t > t:
        t = ball.history[-1].t
    ball.history.add(BallState(rvw=ball.state.rvw.copy(), s=ball.state.s, t=t))


def respot_on_spot_line(shot: System, ball_id: str) -> None:
    """Respot one ball per п. 25 (задняя отметка / spotting line) + sync history."""
    radius = shot.balls[ball_id].params.R
    occupied = _live_positions(shot, exclude={ball_id})
    x, y = spot_line_position(shot, occupied, radius)
    respot(shot, ball_id, x, y)
    _sync_history(shot, ball_id)


def place_cue_ball_in_house(shot: System) -> None:
    """Place the cue ball at the deterministic default house position.

    Used after a scratch (cue ball potted or jumped on a foul): the incoming
    player plays «с руки из дома» (п. 22), so the ball is placed in the house;
    ``next_shot_constraints`` grants :attr:`BallInHandOptions.BEHIND_LINE` so
    interactive players can reposition it freely within the house.
    """
    radius = shot.balls[CUE_BALL_ID].params.R
    occupied = _live_positions(shot, exclude={CUE_BALL_ID})
    x, y = house_default_position(shot, occupied, radius)
    respot(shot, CUE_BALL_ID, x, y)
    _sync_history(shot, CUE_BALL_ID)


def nearest_pocket(table: Table, xy: tuple[float, float]) -> Pocket:
    """The pocket whose center is closest to ``(x, y)`` (deterministic)."""
    return min(
        table.pockets.values(),
        key=lambda pocket: (
            (float(pocket.center[0]) - xy[0]) ** 2
            + (float(pocket.center[1]) - xy[1]) ** 2
        ),
    )


def remove_penalty_ball(shot: System) -> str | None:
    """Remove the «штрафной шар» from the table; returns its ID or None.

    On a foul the opponent removes any one object ball of their choice from
    the table (п. 22 — it counts toward their score, which
    :meth:`RussianFreePyramid.build_shot_info` has already awarded). Because
    autonomous simulation cannot model preference, the deterministic policy
    removes the live object ball **closest to any pocket center** — the ball
    the incoming opponent would find easiest to pot and therefore the one a
    thinking opponent denies the shooter — with ties broken by the lowest
    ball number. The ball is marked pocketed at the nearest pocket center,
    the canonical out-of-play representation in pooltool (its true resting
    place being the opponent's shelf, which the model has no geometry for).

    Per the rules the removal happens **after** all illegally potted and
    jumped balls have been respotted; callers must respect that order.
    """
    candidates = [
        ball.id
        for ball in shot.balls.values()
        if ball.id != CUE_BALL_ID and ball.state.s in const.on_table
    ]
    if not candidates:
        return None

    def distance_sq_to_nearest_pocket(ball_id: str) -> float:
        x, y = shot.balls[ball_id].state.rvw[0, :2]
        pocket = nearest_pocket(shot.table, (float(x), float(y)))
        return (float(x) - float(pocket.center[0])) ** 2 + (
            float(y) - float(pocket.center[1])
        ) ** 2

    # min() over ascending IDs resolves distance ties deterministically.
    chosen = min(sorted(candidates, key=int), key=distance_sq_to_nearest_pocket)
    ball = shot.balls[chosen]
    pocket = nearest_pocket(
        shot.table, (float(ball.state.rvw[0, 0]), float(ball.state.rvw[0, 1]))
    )

    ball.state.rvw[:] = np.array(
        [
            [float(pocket.center[0]), float(pocket.center[1]), -pocket.depth],
            [0, 0, 0],
            [0, 0, 0],
        ]
    )
    ball.state.s = const.pocketed
    _sync_history(shot, chosen)

    return chosen


def _copy_shot_constraints(constraints: ShotConstraints) -> ShotConstraints:
    """Deep-enough copy of a :class:`ShotConstraints` (mutable lists rebuilt)."""
    return attrs.evolve(
        constraints,
        movable=None if constraints.movable is None else list(constraints.movable),
        cueable=None if constraints.cueable is None else list(constraints.cueable),
        hittable=tuple(constraints.hittable),
    )


class RussianFreePyramid(Ruleset):
    """«Свободная пирамида» — Free Pyramid.

    The most widespread discipline of Russian billiards. Simplified rules:
    the first object ball contacted may be any ball on the table, called
    shots are not required, and — the defining feature — pocketing the cue
    ball («свояк») is not a foul when played legally after contacting an
    object ball: it scores for the shooter.

    Race target: first to :data:`FREE_TARGET_SCORE` (8) points. Foul
    penalty: +1 point to the opponent, embodied by the «штрафной шар» taken
    from the table onto the opponent's shelf.

    Foul administration (deterministic policies for autonomous play are
    documented on the methods): fouls award the opponent one point and one
    «штрафной шар» (a ball removed from the table by ``respot_balls`` after
    all respots); a scratched cue ball is re-introduced from the house
    («с руки из дома», п. 22), while a legally potted cue ball («свояк») is
    respotted on the spotting line per «Общие правила пирамиды» п. 25.
    """

    def build_shot_info(self, shot: System) -> ShotInfo:
        scan = _EventScan(shot)
        legal, reason = _judge_free(shot, is_break=self.shot_number == 0, scan=scan)

        shooter = self.active_player
        opponent = self.last_player

        potted = scan.pocketed_ids

        score = self.score.copy()
        if legal:
            # Every ball potted on a legal stroke scores for the shooter,
            # including a «свояк» (cue ball pocketed after contacting an
            # object ball).
            score[shooter.name] += len(potted)
        else:
            # Foul: the opponent receives one point. The point is embodied
            # by the «штрафной шар» taken from the table onto the opponent's
            # shelf (the removal happens in ``respot_balls``).
            score[opponent.name] += 1

        # The shooter continues only when a ball was pocketed on a legal
        # stroke (a «свояк» counts as a potted ball).
        turn_over = not (legal and len(potted))

        game_over = (
            score[shooter.name] >= FREE_TARGET_SCORE
            or score[opponent.name] >= FREE_TARGET_SCORE
        )
        winner: Player | None = None
        if game_over:
            winner = (
                shooter if score[shooter.name] >= score[opponent.name] else opponent
            )

        return ShotInfo(
            player=shooter,
            legal=legal,
            reason=reason,
            turn_over=turn_over,
            game_over=game_over,
            winner=winner,
            score=score,
        )

    def next_shot_constraints(self, shot: System) -> ShotConstraints:
        """Constraints for the stroke following the current one.

        Ordinary strokes carry no ball-in-hand privilege: any live object
        ball may be struck first and no call is required. If the shooter
        fouled **and** scratched (cue ball potted or jumped — detected from
        the shot's events, since ``respot_balls`` has already re-placed the
        ball by the time this method runs), the incoming player introduces
        the cue ball with a stroke from the house («с руки из дома», п. 22);
        it has been placed at a deterministic default house position. A cue
        ball legally potted as «свояк» was respotted on the spotting line and
        is played as it lies.
        """
        scan = _EventScan(shot)
        hittable = tuple(live_object_ball_ids(shot))
        cueable = [CUE_BALL_ID]

        if not self.shot_info.legal and (
            CUE_BALL_ID in scan.pocketed_ids or CUE_BALL_ID in scan.off_table_ids
        ):
            return ShotConstraints(
                ball_in_hand=BallInHandOptions.BEHIND_LINE,
                movable=[CUE_BALL_ID],
                cueable=cueable,
                hittable=hittable,
                call_shot=False,
            )

        return ShotConstraints(
            ball_in_hand=BallInHandOptions.NONE,
            movable=[],
            cueable=cueable,
            hittable=hittable,
            call_shot=False,
        )

    def initial_shot_constraints(self) -> ShotConstraints:
        """Break stroke: cue ball in hand from the house (п. 11 / п. 12).

        Any object ball may be struck first and no shot needs to be called.
        """
        return ShotConstraints(
            ball_in_hand=BallInHandOptions.BEHIND_LINE,
            movable=[CUE_BALL_ID],
            cueable=[CUE_BALL_ID],
            hittable=tuple(str(i) for i in range(1, 16)),
            call_shot=False,
        )

    def respot_balls(self, shot: System) -> None:
        """Respot and administer balls after the shot («Общие правила» п. 22/25).

        Executed in this order:

        (1) **Cue ball.** If it finished off the table: on a legal stroke
            («свояк») it is respotted on the spotting line per п. 25
            («выставляется на общих основаниях»); on a foul it is placed at
            a deterministic default position in the house, and
            ``next_shot_constraints`` grants ball-in-hand behind the house
            line so the incoming player can reposition it (п. 22).
        (2) **Object balls.** On a foul, every ball potted during the shot
            («неправильно забитые») is respotted per п. 25; balls that jumped
            off the table («выскочившие») are respotted regardless of the
            shot's legality. Multiple balls are respotted in ascending
            numeric order, the first onto the задняя отметка itself, the
            rest along the spotting line.
        (3) **Штрафной шар.** On a foul (and only while the game continues),
            one live object ball is removed from the table by the
            deterministic policy of :func:`remove_penalty_ball` — always
            *after* the respots, per the rules.
        """
        legal = self.shot_info.legal
        scan = _EventScan(shot)

        cue = shot.balls[CUE_BALL_ID]
        if cue.state.s not in const.on_table:
            if legal:
                respot_on_spot_line(shot, CUE_BALL_ID)
            else:
                place_cue_ball_in_house(shot)

        respot_ids: set[str] = set(balls_off_table(shot))
        if not legal:
            respot_ids.update(scan.potted_object_ball_ids())

        for ball_id in sorted(respot_ids, key=int):
            respot_on_spot_line(shot, ball_id)

        if not legal and not self.shot_info.game_over:
            remove_penalty_ball(shot)

    def copy(self) -> RussianFreePyramid:
        """Create a real, independent copy of the game state.

        Follows the :class:`~pooltool.ruleset.nine_ball.NineBall` idiom: the
        mutable bookkeeping (score counters, shot info, constraints, log) is
        deep-enough copied, while :attr:`players` is shared by reference
        (players are identity objects, matching upstream semantics).
        """
        game = RussianFreePyramid()
        game.score = copy.deepcopy(self.score)
        game.shot_number = self.shot_number
        game.turn_number = self.turn_number
        game.shot_constraints = _copy_shot_constraints(self.shot_constraints)
        if hasattr(self, "shot_info"):
            game.shot_info = attrs.evolve(
                self.shot_info,
                score=copy.deepcopy(self.shot_info.score),
            )
        game.players = self.players
        game.active_idx = self.active_idx
        game.log = self.log.copy()
        return game


class RussianCombinedPyramid(Ruleset):
    """«Комбинированная пирамида» — Combined Pyramid (Moscow variant).

    Played per the ФБСР rules: any object ball may be pocketed, and the cue
    ball may be pocketed («свояк») off any object ball. In exchange for a
    legally pocketed cue ball the shooter removes one object ball of their
    choice from the table onto their shelf (one point) and re-enters the
    cue ball with a premium stroke from the house (п. 21 «Общих правил»):
    the cue ball may be placed anywhere in the house, and the stroke must
    first contact a ball standing outside the house.

    Race target: first to :data:`COMBINED_TARGET_SCORE` (8) points. Foul
    penalty: +1 point to the opponent, embodied by the «штрафной шар» taken
    from the table onto the opponent's shelf; a fouled scratch or jump is
    followed by the opponent's penalty stroke from the house (п. 7/п. 21).

    Foul administration (deterministic policies for autonomous play are
    documented on the methods and in ``RULES_DEVIATIONS.md``): a potted or
    jumped cue ball — legal «свояк» or foul — is always re-introduced from
    the house; legally potted object balls stay down, while illegally
    potted and jumped object balls are respotted on the spotting line per
    п. 25.
    """

    def build_shot_info(self, shot: System) -> ShotInfo:
        scan = _EventScan(shot)
        legal, reason = _judge_combined(shot, is_break=self.shot_number == 0, scan=scan)

        shooter = self.active_player
        opponent = self.last_player

        potted_objects = scan.potted_object_ball_ids()
        svojak = legal and CUE_BALL_ID in scan.pocketed_ids

        score = self.score.copy()
        if legal:
            # Every legally potted object ball scores for the shooter (п. 6).
            score[shooter.name] += len(potted_objects)
            if svojak:
                # п. 5.2: in exchange for the pocketed cue ball the shooter
                # removes one object ball onto their shelf — one point
                # (the removal itself happens in ``respot_balls``).
                score[shooter.name] += 1
        else:
            # Foul: the opponent receives one point (п. 6), embodied by the
            # «штрафной шар» removed in ``respot_balls``.
            score[opponent.name] += 1

        # The shooter continues after any productive legal stroke: potted
        # object balls are played from the resulting position (п. 5.2), a
        # «свояк» grants the premium house stroke (п. 21). Otherwise the
        # turn passes.
        turn_over = not (legal and (bool(potted_objects) or svojak))

        game_over = (
            score[shooter.name] >= COMBINED_TARGET_SCORE
            or score[opponent.name] >= COMBINED_TARGET_SCORE
        )
        winner: Player | None = None
        if game_over:
            winner = (
                shooter if score[shooter.name] >= score[opponent.name] else opponent
            )

        return ShotInfo(
            player=shooter,
            legal=legal,
            reason=reason,
            turn_over=turn_over,
            game_over=game_over,
            winner=winner,
            score=score,
        )

    def next_shot_constraints(self, shot: System) -> ShotConstraints:
        """Constraints for the stroke following the current one.

        A potted or jumped cue ball always leads to a stroke from the house
        (п. 21): the premium stroke after a legal «свояк» (п. 5.2) or the
        penalty stroke after a foul (п. 7). The cue ball has been placed at
        a deterministic default house position by ``respot_balls``;
        :attr:`BallInHandOptions.BEHIND_LINE` lets interactive players
        reposition it anywhere inside the house. Ordinary strokes are played
        from the resulting position with no ball-in-hand privilege.
        """
        scan = _EventScan(shot)
        hittable = tuple(live_object_ball_ids(shot))
        cueable = [CUE_BALL_ID]

        if CUE_BALL_ID in scan.pocketed_ids or CUE_BALL_ID in scan.off_table_ids:
            return ShotConstraints(
                ball_in_hand=BallInHandOptions.BEHIND_LINE,
                movable=[CUE_BALL_ID],
                cueable=cueable,
                hittable=hittable,
                call_shot=False,
            )

        return ShotConstraints(
            ball_in_hand=BallInHandOptions.NONE,
            movable=[],
            cueable=cueable,
            hittable=hittable,
            call_shot=False,
        )

    def initial_shot_constraints(self) -> ShotConstraints:
        """Break stroke: cue ball in hand from the house (п. 4 / п. 11 / п. 12).

        Any object ball may be struck first and no shot needs to be called.
        """
        return ShotConstraints(
            ball_in_hand=BallInHandOptions.BEHIND_LINE,
            movable=[CUE_BALL_ID],
            cueable=[CUE_BALL_ID],
            hittable=tuple(str(i) for i in range(1, 16)),
            call_shot=False,
        )

    def respot_balls(self, shot: System) -> None:
        """Respot and administer balls after the shot (п. 5.2 / п. 7 / п. 25).

        Executed in this order:

        (1) **Cue ball.** Whether it was legally pocketed («свояк») or
            potted/jumped on a foul, it re-enters the game with a stroke
            from the house (п. 21): placed at a deterministic default
            house position, with ``next_shot_constraints`` granting
            ball-in-hand behind the house line.
        (2) **Object balls.** On a foul, every ball potted during the shot
            («неправильно забитые») is respotted per п. 25; balls that
            jumped off the table («выскочившие») are respotted regardless
            of the shot's legality; ascending numeric order.
        (3) **Shelf balls** (only while the game continues): after a legal
            «свояк» the shooter removes one object ball of their choice
            (п. 5.2 — one point, already scored by ``build_shot_info``);
            after a foul the opponent takes the «штрафной шар» (п. 7),
            always after the respots.
        """
        legal = self.shot_info.legal
        scan = _EventScan(shot)

        cue = shot.balls[CUE_BALL_ID]
        if cue.state.s not in const.on_table:
            place_cue_ball_in_house(shot)

        respot_ids: set[str] = set(balls_off_table(shot))
        if not legal:
            respot_ids.update(scan.potted_object_ball_ids())

        for ball_id in sorted(respot_ids, key=int):
            respot_on_spot_line(shot, ball_id)

        if self.shot_info.game_over:
            return

        if legal and CUE_BALL_ID in scan.pocketed_ids:
            # п. 5.2: the shooter's compensation ball for the «свояк».
            remove_penalty_ball(shot)
        if not legal:
            # п. 7: the «штрафной шар» to the opponent's shelf.
            remove_penalty_ball(shot)

    def copy(self) -> RussianCombinedPyramid:
        """Create a real, independent copy of the game state.

        Follows the :class:`RussianFreePyramid` idiom: the mutable
        bookkeeping (score counters, shot info, constraints, log) is
        deep-enough copied, while :attr:`players` is shared by reference
        (players are identity objects, matching upstream semantics).
        """
        game = RussianCombinedPyramid()
        game.score = copy.deepcopy(self.score)
        game.shot_number = self.shot_number
        game.turn_number = self.turn_number
        game.shot_constraints = _copy_shot_constraints(self.shot_constraints)
        if hasattr(self, "shot_info"):
            game.shot_info = attrs.evolve(
                self.shot_info,
                score=copy.deepcopy(self.shot_info.score),
            )
        game.players = self.players
        game.active_idx = self.active_idx
        game.log = self.log.copy()
        return game


class RussianDynamicPyramid(Ruleset):
    """«Динамичная пирамида» — Dynamic Pyramid (Nevskaya variant).

    Played per the ФБСР rules: any object ball may be pocketed, and the cue
    ball may be pocketed («свояк») off any object ball. In exchange for a
    legally pocketed cue ball the shooter removes one object ball of their
    choice from the table onto their shelf (one point) and re-introduces the
    cue ball with a ball-in-hand stroke from **any point of the playing
    surface** (п. 6.1) — unlike Combined, which re-enters from the house. On
    any such introduction stroke only object balls may be pocketed: a cue
    ball pocketed with ball in hand is a foul (п. 6.4/6.5), and an object
    ball pocketed alongside it is not counted and is respotted (п. 6.6).

    Race target: first to :data:`DYNAMIC_TARGET_SCORE` (8) points. Foul
    penalty: +1 point to the opponent, embodied by the «штрафной шар» taken
    from the table onto the opponent's shelf (п. 7.1/п. 9). If the cue ball
    was pocketed or jumped on the foul, the incoming opponent re-introduces
    it with ball in hand from any point of the table (п. 7.2a); otherwise
    the stroke is played from where the cue ball lies (п. 7.3a).

    Deterministic policies for autonomous play are documented on the methods
    and in ``RULES_DEVIATIONS.md``: the pass-back options (п. 7.2b/п. 7.3b)
    are not modeled — option (a) is always taken — and the default
    ball-in-hand placement is the break spawn point.
    """

    def build_shot_info(self, shot: System) -> ShotInfo:
        # The stroke just played was an introduction stroke («удар с руки»)
        # iff it was played under table-wide ball-in-hand privileges: the
        # cue-ball potting ban of п. 6.4/6.5 applies to it (and only to it —
        # the break is played from behind the house line, ordinary strokes
        # as they lie).
        is_break = self.shot_number == 0
        is_in_hand = self.shot_constraints.ball_in_hand == BallInHandOptions.ANYWHERE
        scan = _EventScan(shot)
        legal, reason = _judge_dynamic(shot, is_break, is_in_hand, scan=scan)

        shooter = self.active_player
        opponent = self.last_player

        potted_objects = scan.potted_object_ball_ids()
        svojak = legal and CUE_BALL_ID in scan.pocketed_ids

        score = self.score.copy()
        if legal:
            # Every legally potted object ball scores for the shooter (п. 9).
            score[shooter.name] += len(potted_objects)
            if svojak:
                # п. 5.2: in exchange for the pocketed cue ball the shooter
                # removes one object ball onto their shelf — one point
                # (the removal itself happens in ``respot_balls``).
                score[shooter.name] += 1
        else:
            # Foul: the opponent receives one point (п. 9), embodied by the
            # «штрафной шар» removed in ``respot_balls`` (п. 7.1).
            score[opponent.name] += 1

        # The shooter continues after any productive legal stroke: potted
        # object balls are played from the resulting position, a «свояк»
        # grants the table-wide ball-in-hand introduction stroke
        # (п. 5.2/п. 6.1). Otherwise the turn passes.
        turn_over = not (legal and (bool(potted_objects) or svojak))

        game_over = (
            score[shooter.name] >= DYNAMIC_TARGET_SCORE
            or score[opponent.name] >= DYNAMIC_TARGET_SCORE
        )
        winner: Player | None = None
        if game_over:
            winner = (
                shooter if score[shooter.name] >= score[opponent.name] else opponent
            )

        return ShotInfo(
            player=shooter,
            legal=legal,
            reason=reason,
            turn_over=turn_over,
            game_over=game_over,
            winner=winner,
            score=score,
        )

    def next_shot_constraints(self, shot: System) -> ShotConstraints:
        """Constraints for the stroke following the current one.

        A potted or jumped cue ball always leads to a ball-in-hand stroke
        from any point of the playing surface (п. 6.1): the shooter's
        introduction stroke after a legal «свояк» (п. 5.2) or the incoming
        opponent's stroke after a foul (п. 7.2a). If the cue ball stayed on
        the table after a foul, the stroke is played from where it lies
        (п. 7.3a — the pass-back options of п. 7.2b/п. 7.3b are not modeled,
        see ``RULES_DEVIATIONS.md``). The cue ball has been placed at a
        deterministic default position by ``respot_balls``;
        :attr:`BallInHandOptions.ANYWHERE` lets interactive players
        reposition it anywhere on the table.
        """
        scan = _EventScan(shot)
        hittable = tuple(live_object_ball_ids(shot))
        cueable = [CUE_BALL_ID]

        if CUE_BALL_ID in scan.pocketed_ids or CUE_BALL_ID in scan.off_table_ids:
            return ShotConstraints(
                ball_in_hand=BallInHandOptions.ANYWHERE,
                movable=[CUE_BALL_ID],
                cueable=cueable,
                hittable=hittable,
                call_shot=False,
            )

        return ShotConstraints(
            ball_in_hand=BallInHandOptions.NONE,
            movable=[],
            cueable=cueable,
            hittable=hittable,
            call_shot=False,
        )

    def initial_shot_constraints(self) -> ShotConstraints:
        """Break stroke: cue ball in hand from the house (п. 4 / п. 12).

        Any object ball may be struck first and no shot needs to be called.
        """
        return ShotConstraints(
            ball_in_hand=BallInHandOptions.BEHIND_LINE,
            movable=[CUE_BALL_ID],
            cueable=[CUE_BALL_ID],
            hittable=tuple(str(i) for i in range(1, 16)),
            call_shot=False,
        )

    def respot_balls(self, shot: System) -> None:
        """Respot and administer balls after the shot (п. 5.2 / п. 6 / п. 7 / п. 25).

        Executed in this order:

        (1) **Cue ball.** Whether it was legally pocketed («свояк») or
            potted/jumped on a foul, it re-enters the game with a ball-in-hand
            stroke from any point of the table (п. 6.1 / п. 7.2a): it is
            placed at a deterministic default position (the break spawn
            point), with ``next_shot_constraints`` granting
            :attr:`BallInHandOptions.ANYWHERE` for full repositioning.
        (2) **Object balls.** On a foul, every ball potted during the shot
            («неправильно забитые», including the п. 6.6 case of an object
            ball falling alongside the cue ball on an introduction stroke)
            is respotted per п. 25; balls that jumped off the table
            («выскочившие») are respotted regardless of the shot's legality;
            ascending numeric order.
        (3) **Shelf balls** (only while the game continues): after a legal
            «свояк» the shooter removes one object ball of their choice
            (п. 5.2 — one point, already scored by ``build_shot_info``);
            after a foul the opponent takes the «штрафной шар» (п. 7.1),
            always after the respots.
        """
        legal = self.shot_info.legal
        scan = _EventScan(shot)

        cue = shot.balls[CUE_BALL_ID]
        if cue.state.s not in const.on_table:
            place_cue_ball_in_house(shot)

        respot_ids: set[str] = set(balls_off_table(shot))
        if not legal:
            respot_ids.update(scan.potted_object_ball_ids())

        for ball_id in sorted(respot_ids, key=int):
            respot_on_spot_line(shot, ball_id)

        if self.shot_info.game_over:
            return

        if legal and CUE_BALL_ID in scan.pocketed_ids:
            # п. 5.2: the shooter's compensation ball for the «свояк».
            remove_penalty_ball(shot)
        if not legal:
            # п. 7.1: the «штрафной шар» to the opponent's shelf.
            remove_penalty_ball(shot)

    def copy(self) -> RussianDynamicPyramid:
        """Create a real, independent copy of the game state.

        Follows the :class:`RussianFreePyramid` idiom: the mutable
        bookkeeping (score counters, shot info, constraints, log) is
        deep-enough copied, while :attr:`players` is shared by reference
        (players are identity objects, matching upstream semantics).
        """
        game = RussianDynamicPyramid()
        game.score = copy.deepcopy(self.score)
        game.shot_number = self.shot_number
        game.turn_number = self.turn_number
        game.shot_constraints = _copy_shot_constraints(self.shot_constraints)
        if hasattr(self, "shot_info"):
            game.shot_info = attrs.evolve(
                self.shot_info,
                score=copy.deepcopy(self.shot_info.score),
            )
        game.players = self.players
        game.active_idx = self.active_idx
        game.log = self.log.copy()
        return game


class RussianClassicPyramid(Ruleset):
    """«Классическая пирамида» — Classic Pyramid («Малая русская», 71 очко).

    The strictest pyramid discipline, played per the ФБСР rules with called
    («заказ») shots: before every stroke (except the break) the player
    declares a specific object ball and a specific pocket (п. 5.2). Only a
    ball pocketed exactly as ordered honors the call; when it does, every
    ball potted on the stroke scores (п. 5.3). A stroke that completed per
    п. 20 but did not honor the call is not a foul: the potted balls are
    respotted, no points are scored, and the turn passes (п. 5.4).

    Scoring (п. 5.1): each correctly potted ball scores its number, the
    1-ball («туз») scores 11, and the last remaining object ball carries a
    +10 bonus — a pool of 140 points. Race target: first to
    :data:`CLASSIC_TARGET_SCORE` (71) or more.

    Fouls: pocketing the cue ball («свояк» — the classic game has none) or
    jumping it off the table hands the opponent a penalty stroke from the
    house (п. 5.5/п. 21); every violation transfers
    :data:`CLASSIC_FOUL_POINTS` (5) points from the offender's score to the
    opponent's (п. 5.6) — Classic has no «штрафной шар». The п. 21
    house-stroke restriction (first contact outside the house) applies to
    penalty and tiebreak strokes.

    Tie-break (п. 5.7): at 70:70 the last potted ball returns to the задняя
    отметка, the next stroke is played from the house, and the game runs
    until a ball is pocketed or a foul occurs.

    Deterministic policies for autonomous play are documented on the methods
    and in ``RULES_DEVIATIONS.md``: the pass-back option of the general
    rules («уступить удар») is not modeled, the розыгрыш (lag) of п. 5.7 is
    replaced by a deterministic turn pass, and the default ball-in-hand
    placement is the break spawn point.
    """

    def build_shot_info(self, shot: System) -> ShotInfo:
        is_break = self.shot_number == 0
        scan = _EventScan(shot)
        legal, reason = _judge_classic(
            shot,
            is_break=is_break,
            ball_call=self.shot_constraints.ball_call,
            pocket_call=self.shot_constraints.pocket_call,
            scan=scan,
        )

        shooter = self.active_player
        opponent = self.last_player

        potted_objects = scan.potted_object_ball_ids()

        score = self.score.copy()
        if reason in (ClassicPyramidReason.LEGAL, ClassicPyramidReason.LEGAL_BREAK):
            # п. 5.1/5.3: every ball potted on the stroke scores its value
            # (the 1-ball 11, the last remaining ball +10). The break
            # requires no call, so pots on a correct break score as well
            # (п. 12.1(1) counts «правильно забитые» balls on the break).
            score[shooter.name] += classic_pot_points(shot, potted_objects)
            # The shooter continues after honoring the call; on the break,
            # after potting at least one ball.
            turn_over = (
                reason == ClassicPyramidReason.LEGAL_BREAK and not potted_objects
            )
        elif reason == ClassicPyramidReason.UNCALLED_POT:
            # п. 5.4: the stroke completed but the call was not honored —
            # no points, potted balls respotted (``respot_balls``), the
            # turn passes («игра продолжается на общих основаниях»).
            turn_over = True
        else:
            # п. 5.6: every violation transfers five points from the
            # offender to the opponent (Classic has no «штрафной шар»).
            score[shooter.name] -= CLASSIC_FOUL_POINTS
            score[opponent.name] += CLASSIC_FOUL_POINTS
            turn_over = True

        game_over = (
            score[shooter.name] >= CLASSIC_TARGET_SCORE
            or score[opponent.name] >= CLASSIC_TARGET_SCORE
        )
        winner: Player | None = None
        if game_over:
            winner = (
                shooter if score[shooter.name] >= score[opponent.name] else opponent
            )

        # п. 5.7: at 70:70 the game continues with the last potted ball
        # respotted and the next stroke from the house; the lag decides
        # who plays — replaced by a deterministic turn pass (see
        # ``RULES_DEVIATIONS.md``).
        tie_break = (
            not game_over
            and bool(score)
            and all(value == CLASSIC_TARGET_SCORE - 1 for value in score.values())
        )
        if tie_break:
            turn_over = True

        return ShotInfo(
            player=shooter,
            legal=legal,
            reason=reason,
            turn_over=turn_over,
            game_over=game_over,
            winner=winner,
            score=score,
        )

    def next_shot_constraints(self, shot: System) -> ShotConstraints:
        """Constraints for the stroke following the current one.

        Every non-break stroke requires a call («заказ», п. 5.2). A potted
        or jumped cue ball hands the incoming opponent the penalty stroke
        from the house (п. 5.5/п. 21). At 70:70 the continuation stroke is
        likewise played from the house (п. 5.7). Otherwise the stroke is
        played from where the cue ball lies (the general pass-back option
        is not modeled — see ``RULES_DEVIATIONS.md``).
        """
        scan = _EventScan(shot)
        hittable = tuple(live_object_ball_ids(shot))
        cueable = [CUE_BALL_ID]

        if CUE_BALL_ID in scan.pocketed_ids or CUE_BALL_ID in scan.off_table_ids:
            return ShotConstraints(
                ball_in_hand=BallInHandOptions.BEHIND_LINE,
                movable=[CUE_BALL_ID],
                cueable=cueable,
                hittable=hittable,
                call_shot=True,
            )

        score = self.shot_info.score
        tie_break = bool(score) and all(
            value == CLASSIC_TARGET_SCORE - 1 for value in score.values()
        )
        if tie_break:
            return ShotConstraints(
                ball_in_hand=BallInHandOptions.BEHIND_LINE,
                movable=[CUE_BALL_ID],
                cueable=cueable,
                hittable=hittable,
                call_shot=True,
            )

        return ShotConstraints(
            ball_in_hand=BallInHandOptions.NONE,
            movable=[],
            cueable=cueable,
            hittable=hittable,
            call_shot=True,
        )

    def initial_shot_constraints(self) -> ShotConstraints:
        """Break stroke: cue ball in hand from the house (п. 4 / п. 11/п. 12).

        The break requires no call («заказ»).
        """
        return ShotConstraints(
            ball_in_hand=BallInHandOptions.BEHIND_LINE,
            movable=[CUE_BALL_ID],
            cueable=[CUE_BALL_ID],
            hittable=tuple(str(i) for i in range(1, 16)),
            call_shot=False,
        )

    def respot_balls(self, shot: System) -> None:
        """Respot and administer balls after the shot (п. 5.4/5.5/5.7/п. 25).

        Executed in this order:

        (1) **Cue ball.** It can only finish off the table on a foul
            («свояк»/jump, п. 5.5): the opponent plays the penalty stroke
            from the house, so it is placed at a deterministic default house
            position. At 70:70 the continuation stroke is likewise played
            from the house (п. 5.7), so the cue ball is re-placed there even
            when it stayed on the table.
        (2) **Object balls.** On a foul, every ball potted during the shot
            («неправильно забитые») is respotted per п. 25, as are balls
            that jumped off the table; a stroke that did not honor the call
            (п. 5.4) respots its potted balls too; at 70:70 reached with a
            correct call, the last potted ball returns to the задняя
            отметка (п. 5.7). Ascending numeric order.
        (3) **No «штрафной шар».** The Classic foul penalty is purely the
            points transfer applied by ``build_shot_info`` (п. 5.6); no
            ball is removed from the table.
        """
        legal = self.shot_info.legal
        reason = self.shot_info.reason
        scan = _EventScan(shot)

        score = self.shot_info.score
        tie_break = (
            not self.shot_info.game_over
            and bool(score)
            and all(value == CLASSIC_TARGET_SCORE - 1 for value in score.values())
        )

        cue = shot.balls[CUE_BALL_ID]
        if cue.state.s not in const.on_table or tie_break:
            # A cue ball finishing off the table always implies a foul
            # («свояк»/jump, п. 5.5): the opponent plays the penalty stroke
            # from the house. At 70:70 the continuation stroke is likewise
            # played from the house (п. 5.7) even when the cue stayed on the
            # table.
            place_cue_ball_in_house(shot)

        respot_ids: set[str] = set(balls_off_table(shot))
        if tie_break and reason == ClassicPyramidReason.LEGAL:
            # п. 5.7: the last potted ball returns to the задняя отметка.
            respot_ids.update(scan.potted_object_ball_ids())
        elif not legal or reason == ClassicPyramidReason.UNCALLED_POT:
            # Fouls: «неправильно забитые» balls are respotted (п. 25); an
            # unhonored call respots the stroke's potted balls (п. 5.4).
            respot_ids.update(scan.potted_object_ball_ids())

        for ball_id in sorted(respot_ids, key=int):
            respot_on_spot_line(shot, ball_id)

    def copy(self) -> RussianClassicPyramid:
        """Create a real, independent copy of the game state.

        Follows the :class:`RussianFreePyramid` idiom: the mutable
        bookkeeping (score counters, shot info, constraints, log) is
        deep-enough copied, while :attr:`players` is shared by reference
        (players are identity objects, matching upstream semantics).
        """
        game = RussianClassicPyramid()
        game.score = copy.deepcopy(self.score)
        game.shot_number = self.shot_number
        game.turn_number = self.turn_number
        game.shot_constraints = _copy_shot_constraints(self.shot_constraints)
        if hasattr(self, "shot_info"):
            game.shot_info = attrs.evolve(
                self.shot_info,
                score=copy.deepcopy(self.shot_info.score),
            )
        game.players = self.players
        game.active_idx = self.active_idx
        game.log = self.log.copy()
        return game
