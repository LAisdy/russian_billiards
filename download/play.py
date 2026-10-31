#!/usr/bin/env python3
"""Launch the pooltool 3D interface for Russian Free Pyramid (Американка).

Usage (from the pooltool repo root, where ``pyproject.toml`` lives):

    uv run python play.py

or, once the package is installed in the active environment:

    python play.py

This script persists the following into ``~/.config/pooltool/general.yaml``:

* ``game_type``            -> ``GameType.RUSSIAN_PYRAMID_FREE``  (Американка)
* ``table_name``           -> ``TableName.RUSSIAN_PYRAMID_GENERIC`` (12 ft × 6 ft,
  370 × 180 cm playing surface, corner pockets ~72-73 mm, middle ~82-83 mm)
* ``enforce_rules``        -> ``True``  (active :class:`RussianFreePyramid`
  ruleset: «свояк» is legal, race to 8, foul = +1 point + «штрафной шар»)
* ``three_dimensional``    -> ``True``  (use the 3D physics resolver — airborne
  balls, cushion nose height, etc.)

Then it boots :class:`pooltool.ani.animate.Game`, which opens the Panda3D
window with the menu -> break-stroke -> aim -> stroke loop.

NOTE on the enum name: the constant in ``pooltool.game.datatypes.GameType`` is
``RUSSIAN_PYRAMID_FREE`` (not ``RUSSIAN_FREE_PYRAMID``) — the four Russian
Pyramid members all share the ``RUSSIAN_PYRAMID_*`` prefix.

Press ESC to quit the interface.
"""

from __future__ import annotations

from pooltool.ani.animate import Game, ShowBaseConfig
from pooltool.config import settings
from pooltool.game.datatypes import GameType
from pooltool.objects.table.collection import TableName


def main() -> int:
    # Persist the gameplay selection. ``settings`` is a lazy proxy that re-reads
    # ``~/.config/pooltool/general.yaml`` on each attribute access; the
    # ``write()`` context manager yields a writable snapshot and saves it back
    # atomically on exit.
    with settings.write() as s:
        s.gameplay.game_type = GameType.RUSSIAN_PYRAMID_FREE
        s.gameplay.table_name = TableName.RUSSIAN_PYRAMID_GENERIC
        s.gameplay.enforce_rules = True
        s.gameplay.three_dimensional = True

    print("Starting pooltool 3D interface")
    print(f"  game_type        : {settings.gameplay.game_type.value}")
    print(f"  table_name       : {settings.gameplay.table_name.value}")
    print(f"  enforce_rules    : {settings.gameplay.enforce_rules}")
    print(f"  three_dimensional: {settings.gameplay.three_dimensional}")
    print("(Press ESC inside the window to exit.)")

    Game(ShowBaseConfig.default()).start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
