"""Game modes & rulesets glue for pyramid-web (Step 6).

This module is the bridge between the web lobby (sessions, player identity)
and the vendored pooltool rulesets (``backend/pooltool/ruleset/``). It never
re-implements rules — it instantiates the vendored ``Ruleset`` classes, feeds
them the lobby players, and translates their state into wire-friendly
snapshots.

Design notes (logged in pyramid-web/PROGRESS.md, Step 6):

- pooltool's ``Ruleset`` keys scores by ``Player.name`` (a
  ``Counter[str]``), so the lobby registers each web player under their
  *player id* (uuid4 hex[:8] — unique by construction). Snapshots map ids
  back to display names.
- The vendored rulesets are frozen: their documented deterministic policies
  (penalty-ball choice, default ball-in-hand placement, no pass-back option,
  no lag) are inherited verbatim — see RULES_DEVIATIONS.md in both repos.
- Wire modes: ``free`` / ``combined`` / ``dynamic`` / ``classic`` map to the
  four vendored disciplines.
- Ball-in-hand placement validation mirrors the rules the vendored rulesets
  assume for interactive play («с руки из дома» = whole ball behind the
  house line; «с руки» = anywhere on the playing surface), with a 1 mm
  clearance to every other ball.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pooltool.ruleset.datatypes import BallInHandOptions
from pooltool.ruleset.datatypes import Player as RulesetPlayer
from pooltool.ruleset.russian_pyramid import (
    HOUSE_LINE_FRACTION,
    RussianClassicPyramid,
    RussianCombinedPyramid,
    RussianDynamicPyramid,
    RussianFreePyramid,
)

from . import physics

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pooltool.ruleset.datatypes import Ruleset

    from .lobby import Player


#: House line position (m): the house spans y in [0, HOUSE_Y]; the vendored
#: rulesets use the same fraction (``HOUSE_LINE_FRACTION``) of table length.
HOUSE_Y = HOUSE_LINE_FRACTION * physics.TABLE_L

#: Clearance a hand-placed cue ball must keep from every other ball (m).
#: Matches the respot machinery's "as close as possible, but not touching"
#: spirit (п. 25.2 uses 1 mm).
PLACE_GAP = 1e-3


class Modes:
    """The four Russian Pyramid disciplines as wire modes."""

    FREE = "free"
    COMBINED = "combined"
    DYNAMIC = "dynamic"
    CLASSIC = "classic"


#: Default discipline for fresh rooms (the host changes it via ``set_mode``).
DEFAULT_MODE = Modes.FREE


#: mode -> {class, display name, Russian name, race target, one-line blurb}
MODES: dict[str, dict] = {
    Modes.FREE: {
        "cls": RussianFreePyramid,
        "name": "Free Pyramid",
        "name_ru": "Свободная",
        "target": 8,
        "blurb": "any ball first; «свояк» scores; race to 8",
    },
    Modes.COMBINED: {
        "cls": RussianCombinedPyramid,
        "name": "Combined Pyramid",
        "name_ru": "Комбинированная",
        "target": 8,
        "blurb": "«свояк» → take a ball + stroke from the house; race to 8",
    },
    Modes.DYNAMIC: {
        "cls": RussianDynamicPyramid,
        "name": "Dynamic Pyramid",
        "name_ru": "Динамичная",
        "target": 8,
        "blurb": "«свояк» → ball in hand anywhere; race to 8",
    },
    Modes.CLASSIC: {
        "cls": RussianClassicPyramid,
        "name": "Classic Pyramid",
        "name_ru": "Классическая",
        "target": 71,
        "blurb": "called shots; ball values; race to 71",
    },
}

#: Valid pocket identifiers (from the physics table spec — never hardcoded).
POCKET_IDS: frozenset[str] = frozenset(physics.table_dimensions()["pockets"])

#: BallInHandOptions -> wire string (explicit mapping; no reliance on
#: StrEnum ``auto()`` details).
_BIH_WIRE = {
    BallInHandOptions.NONE: "none",
    BallInHandOptions.ANYWHERE: "anywhere",
    BallInHandOptions.BEHIND_LINE: "behind_line",
}

_BIH_ENUM = {v: k for k, v in _BIH_WIRE.items()}


def is_valid_mode(mode: object) -> bool:
    return isinstance(mode, str) and mode in MODES


def new_game(mode: str, players: list[Player]) -> Ruleset:
    """Instantiate the vendored ruleset for ``mode`` with the lobby players.

    Ruleset players are keyed by lobby player **id** (unique), in room order;
    the first player (the host) takes the opening break.
    """
    return MODES[mode]["cls"](players=[RulesetPlayer(name=p.id) for p in players])


def game_snapshot(mode: str, game: Ruleset, players: list[Player]) -> dict:
    """Wire snapshot of the ruleset state, broadcast with every game event.

    ``turn`` is the player who may shoot next (host on the break);
    ``ball_in_hand``/``call_shot``/``hittable`` describe the *upcoming*
    stroke's constraints; ``last_shot`` summarizes the stroke just played
    (``None`` before the first shot); ``scores`` is in room player order.
    """
    names = {p.id: p.name for p in players}
    active_id = game.active_player.name
    info = getattr(game, "shot_info", None)
    constraints = game.shot_constraints

    winner = None
    game_over = bool(info is not None and info.game_over)
    if game_over and info.winner is not None:
        winner = {"id": info.winner.name, "name": names.get(info.winner.name, "?")}

    return {
        "mode": mode,
        "mode_name": MODES[mode]["name"],
        "target_score": MODES[mode]["target"],
        "shot_number": game.shot_number,
        "turn_number": game.turn_number,
        "turn": {"id": active_id, "name": names.get(active_id, "?")},
        "scores": [
            {"id": p.id, "name": p.name, "score": int(game.score.get(p.id, 0))}
            for p in players
        ],
        "ball_in_hand": _BIH_WIRE[constraints.ball_in_hand],
        "call_shot": bool(constraints.call_shot),
        "hittable": list(constraints.hittable),
        "game_over": game_over,
        "winner": winner,
        "last_shot": None
        if info is None
        else {
            "legal": bool(info.legal),
            "reason": str(info.reason),
            "turn_over": bool(info.turn_over),
        },
    }


def validate_cue_placement(
    ball_in_hand: str,
    x: object,
    y: object,
    others: dict[str, tuple[float, float]],
) -> tuple[float, float]:
    """Validate a hand placement of the cue ball; return the cleaned (x, y).

    ``others`` maps every OTHER on-table ball id to its (x, y).

    Raises:
        TypeError: when ``x``/``y`` are not numbers.
        ValueError: with a human-readable reason when the placement is
            illegal for the granted ball-in-hand option.
    """
    try:
        bih = _BIH_ENUM[ball_in_hand]
    except KeyError as exc:
        raise ValueError(f"unknown ball-in-hand option: {ball_in_hand!r}") from exc
    if bih is BallInHandOptions.NONE:
        raise ValueError("no ball-in-hand privilege is active")
    if (
        isinstance(x, bool)
        or isinstance(y, bool)
        or not isinstance(x, (int, float))
        or not isinstance(y, (int, float))
    ):
        raise TypeError("'x' and 'y' must be numbers")

    r = physics.BALL_R
    x, y = float(x), float(y)
    lo_x, hi_x = r, physics.TABLE_W - r
    lo_y, hi_y = (
        r,
        HOUSE_Y - r if bih is BallInHandOptions.BEHIND_LINE else physics.TABLE_L - r,
    )
    if not lo_x <= x <= hi_x:
        raise ValueError(f"x must be in [{lo_x:.3f}, {hi_x:.3f}] m")
    if not lo_y <= y <= hi_y:
        where = (
            "the house (behind the line)"
            if bih is BallInHandOptions.BEHIND_LINE
            else "the playing surface"
        )
        raise ValueError(f"y must be in [{lo_y:.3f}, {hi_y:.3f}] m — {where}")

    min_dist = 2 * r + PLACE_GAP
    for ball_id, (ox, oy) in others.items():
        if (x - ox) ** 2 + (y - oy) ** 2 < min_dist**2:
            raise ValueError(
                f"overlaps ball '{ball_id}' (need {min_dist * 1000:.0f} mm clearance)"
            )
    return x, y


def is_game_finished(game: Ruleset | None) -> bool:
    """Whether the room's game is over (a rematch may then be started)."""
    if game is None:
        return False
    info = getattr(game, "shot_info", None)
    return bool(info is not None and info.game_over)
