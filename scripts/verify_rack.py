"""Step 4 verification: Russian pyramid rack layout.

Checks, for each of the four Russian pyramid game types:
- get_rack returns exactly 16 balls: "cue" + "1".."15"
- all ball centers lie within the playing surface
- no two balls overlap (vectorized pairwise distance check, >= 2R)
- some ball sits (essentially) on the foot spot (0.5 w, 0.75 l)
- the cue ball spawns in the head quarter (y < 0.3 l)
"""

import numpy as np

from pooltool.game.datatypes import GameType
from pooltool.layouts import get_rack
from pooltool.objects.table.collection import default_specs_from_game_type
from pooltool.objects.table.datatypes import Table

R = 0.0335

GAME_TYPES = (
    GameType.RUSSIAN_PYRAMID_FREE,
    GameType.RUSSIAN_PYRAMID_COMBINED,
    GameType.RUSSIAN_PYRAMID_DYNAMIC,
    GameType.RUSSIAN_PYRAMID_CLASSIC,
)


def main() -> None:
    table = Table.from_table_specs(
        default_specs_from_game_type(GameType.RUSSIAN_PYRAMID_FREE)
    )

    for gt in GAME_TYPES:
        balls = get_rack(gt, table)
        ids = sorted(balls)
        expected = sorted(["cue"] + [str(i) for i in range(1, 16)])
        assert ids == expected, f"{gt}: unexpected ids {ids}"

        xy = np.array([balls[i].xyz[:2] for i in expected])

        assert (xy[:, 0] > 0).all() and (xy[:, 0] < table.w).all(), f"{gt}: x out of bounds"
        assert (xy[:, 1] > 0).all() and (xy[:, 1] < table.l).all(), f"{gt}: y out of bounds"

        d = np.linalg.norm(xy[:, None, :] - xy[None, :, :], axis=-1)
        iu = np.triu_indices(len(xy), k=1)
        assert (d[iu] >= 2 * R).all(), f"{gt}: overlap, min gap {d[iu].min()}"

        foot = np.array([0.5 * table.w, 0.75 * table.l])
        dist_foot = np.linalg.norm(xy - foot, axis=1)
        assert dist_foot.min() < 3 * R, f"{gt}: no ball near foot spot"

        assert balls["cue"].xyz[1] < 0.3 * table.l, f"{gt}: cue not in head quarter"

        print(
            f"{gt.name:<26} OK | 16 balls | min gap {d[iu].min() * 1000:.2f} mm"
            f" | apex-to-foot-spot {dist_foot.min() * 1000:.3f} mm"
        )

    print("RACK VERIFICATION: ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
