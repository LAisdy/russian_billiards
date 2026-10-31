#!/usr/bin/env python3
"""Step 3 acceptance test (part 2): original pooltool repo vs the web backend.

Run with the POOLTOOL venv (the original library, not the vendored copy):

    pooltool/.venv/bin/python scripts/test_physics_original.py

Requires /tmp/step3_input.json + /tmp/step3_http.json + /tmp/step3_vendored.json
produced beforehand by scripts/test_physics_api.py.

What it proves:
  1. The original repo generates the SAME rack for seed=42 as the backend
     (layouts.py determinism survives vendoring byte-for-byte).
  2. The original repo, simulating the very same shot, produces IDENTICAL
     final coordinates / pocketed balls / duration / event count as both the
     HTTP endpoint and the in-process vendored copy.

This is the Step 3 acceptance criterion: the vendored physics is provably the
original physics.
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1] / "pooltool"
sys.path.insert(0, str(REPO))

import attrs
import numpy as np
import pooltool.constants as const
from pooltool.evolution.engine import SimulationEngine
from pooltool.game.datatypes import GameType
from pooltool.objects.ball.params import PrebuiltBallParams
from pooltool.objects.table.collection import (
    TABLE_SPECS,
    TableName,
)
from pooltool.objects.table.datatypes import Table
from pooltool.physics.resolve.resolver import Resolver

import pooltool as pt

GAME_TYPE = GameType.RUSSIAN_PYRAMID_FREE
SHOT = {"v0": 4.0, "phi": 90.0, "a": 0.0, "b": 0.25, "theta": 0.0}

checks: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> bool:
    ok = bool(cond)
    checks.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    print(f"pooltool {pt.__version__} from {Path(pt.__file__).parent}")
    check(
        "running the ORIGINAL repo copy",
        Path(pt.__file__).parent == REPO / "pooltool",
        str(Path(pt.__file__).parent),
    )

    input_balls = json.loads(Path("/tmp/step3_input.json").read_text())
    http = json.loads(Path("/tmp/step3_http.json").read_text())
    vendored = json.loads(Path("/tmp/step3_vendored.json").read_text())

    # --- 1. rack determinism across original vs vendored -----------------------
    params = pt.BallParams.prebuilt(PrebuiltBallParams.RUSSIAN_PYRAMID_GENERIC)
    random.seed(42)
    np.random.seed(42)
    table = Table.from_table_specs(TABLE_SPECS[TableName.RUSSIAN_PYRAMID_GENERIC])
    rack = pt.get_rack(
        GAME_TYPE, table=table, ball_params=params, ballset=None, spacing_factor=1e-3
    )
    orig_rack = {
        bid: {"x": float(b.state.rvw[0, 0]), "y": float(b.state.rvw[0, 1])}
        for bid, b in rack.items()
    }
    check("original: seed-42 rack identical to the backend's", orig_rack == input_balls)

    # --- 2. same shot through the original library ------------------------------
    kwargs = attrs.asdict(params)
    cue = pt.Cue.from_game_type(GAME_TYPE)
    cue.set_state(
        V0=SHOT["v0"], phi=SHOT["phi"], a=SHOT["a"], b=SHOT["b"], theta=SHOT["theta"]
    )
    system = pt.System(
        cue=cue,
        table=Table.from_table_specs(TABLE_SPECS[TableName.RUSSIAN_PYRAMID_GENERIC]),
        balls={
            bid: pt.Ball.create(bid, xy=(p["x"], p["y"]), ballset=None, **kwargs)
            for bid, p in input_balls.items()
        },
    )
    engine = SimulationEngine(is_3d=True, resolver=Resolver.default(is_3d=True))
    t0 = time.perf_counter()
    simulated = pt.simulate(system, engine=engine)
    wall_ms = (time.perf_counter() - t0) * 1000

    original = {
        "balls": {
            bid: {
                "x": float(b.state.rvw[0, 0]),
                "y": float(b.state.rvw[0, 1]),
                "state": const.state_dict[b.state.s],
            }
            for bid, b in simulated.balls.items()
        },
        "pocketed": sorted(
            bid for bid, b in simulated.balls.items() if b.state.s == const.pocketed
        ),
        "duration_s": float(simulated.t),
        "events": len(simulated.events),
    }

    # --- 3. three-way comparison --------------------------------------------------
    def compare(label: str, other: dict) -> None:
        max_diff = 0.0
        state_diffs = []
        for bid, b in original["balls"].items():
            o = other["balls"][bid]
            max_diff = max(max_diff, abs(b["x"] - o["x"]), abs(b["y"] - o["y"]))
            if b["state"] != o["state"]:
                state_diffs.append(f"{bid}: {b['state']} vs {o['state']}")
        check(
            f"original vs {label}: identical final coordinates",
            max_diff == 0.0,
            f"max diff {max_diff:.2e} m",
        )
        check(
            f"original vs {label}: identical ball states",
            not state_diffs,
            "; ".join(state_diffs[:3]),
        )
        check(
            f"original vs {label}: same pocketed balls",
            original["pocketed"] == other["pocketed"],
            f"{original['pocketed']} vs {other['pocketed']}",
        )
        check(
            f"original vs {label}: same duration & event count",
            original["duration_s"] == other["duration_s"]
            and original["events"] == other["events"],
            f"{original['duration_s']:.3f}s/{original['events']} vs "
            f"{other['duration_s']:.3f}s/{other['events']}",
        )

    print(
        f"\noriginal break: {wall_ms:.0f} ms wall, {original['events']} events, "
        f"pocketed={original['pocketed']}, duration={original['duration_s']:.2f}s"
    )
    compare("vendored (in-process)", vendored)
    compare("HTTP /api/shot", http)

    Path("/tmp/step3_original.json").write_text(json.dumps(original, indent=2))

    failed = [name for name, ok, _ in checks if not ok]
    print(
        f"\n{'=' * 60}\n"
        f"{len(checks) - len(failed)}/{len(checks)} checks passed"
        + (f"; FAILED: {failed}" if failed else " — ALL GREEN")
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
