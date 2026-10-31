"""pooltool — vendored for pyramid-web (headless build).

Upstream: https://github.com/ekiefl/pooltool (Apache-2.0), extended with the
Russian Pyramid disciplines. This copy was vendored by
``scripts/vendor_physics.py`` for the pyramid-web backend:

    source version : pooltool-billiards 0.6.0
    source commit  : 7632b1c66f19159741a4cfe48b23d18f079d9a87
    vendored at    : 2026-10-30T12:51:20Z

Differences from the upstream top-level module (and only these — see
VENDORED.md next to this file): the Panda3D desktop entry points
``pooltool.interact`` (``Game``/``show``) and ``pooltool.ani.image`` are not
imported, because Panda3D is deliberately absent from the backend. Everything
else — the physics engine, the Russian Pyramid rulesets, the layouts — is
byte-identical to the source repo.
"""

__version__ = "0.6.0"

VENDORED_FOR = "pyramid-web"
VENDORED_FROM_COMMIT = "7632b1c66f19159741a4cfe48b23d18f079d9a87"
VENDORED_AT = "2026-10-30T12:51:20Z"

import pooltool.ai as ai
import pooltool.ai.aim as aim
import pooltool.ai.pot as pot
import pooltool.constants as constants
import pooltool.events as events
import pooltool.evolution as evolution
import pooltool.game as game
import pooltool.layouts as layouts
import pooltool.objects as objects
import pooltool.physics as physics
import pooltool.ptmath as ptmath
import pooltool.ruleset as ruleset
import pooltool.serialize as serialize
import pooltool.system as system
import pooltool.utils as utils
from pooltool.events import EventType
from pooltool.evolution import continuize, interpolate_ball_states, simulate
from pooltool.game.datatypes import GameType
from pooltool.layouts import generate_layout, get_rack
from pooltool.objects import (
    Ball,
    BallParams,
    Cue,
    PrebuiltBallParams,
    Table,
    TableType,
)
from pooltool.ruleset import Player, get_ruleset
from pooltool.system import MultiSystem, System

__all__ = [
    "Ball",
    "BallParams",
    "Cue",
    "EventType",
    "GameType",
    "MultiSystem",
    "Player",
    "PrebuiltBallParams",
    "System",
    "Table",
    "TableType",
    "ai",
    "aim",
    "constants",
    "continuize",
    "events",
    "evolution",
    "game",
    "generate_layout",
    "get_rack",
    "get_ruleset",
    "interpolate_ball_states",
    "layouts",
    "objects",
    "physics",
    "pot",
    "ptmath",
    "ruleset",
    "serialize",
    "simulate",
    "system",
    "utils",
]
