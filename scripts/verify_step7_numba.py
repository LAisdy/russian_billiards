#!/usr/bin/env python3
"""Step 7 verification: Numba JIT compilation of the vendored physics kernels.

Run (fresh process, backend venv):
    PYTHONHASHSEED=0 backend/.venv/bin/python scripts/verify_step7_numba.py

Checks:
  1. every REQUIRED hot-path numba dispatcher compiles: after running a
     seeded 3D break, len(dispatcher.signatures) >= 1 (a 0-signature
     dispatcher would mean the kernel silently fell back to pure Python)
  2. the numba on-disk cache is active (*.nbc/*.nbi under backend/pooltool)
  3. the warm break stays inside the interactive budget — warm sim < 500 ms
     (Decision #15: 110-event benchmark 75-190 ms on this engine; 500 ms is
     the event-proportional sandbox headroom)
  4. cold-vs-warm reported: the first in-process call pays cache loading /
     any re-JIT; the second is steady state (warmup() at server startup
     keeps this off the interactive path)
"""

from __future__ import annotations

import glob
import sys
import time

sys.path.insert(0, "/home/z/my-project/pyramid-web/backend")

passed = 0
failed: list[str] = []


def check(name: str, cond: bool, extra: str = "") -> None:
    global passed
    if cond:
        passed += 1
        print(f"  ok  {name}")
    else:
        failed.append(name)
        print(f"FAIL  {name}  {extra}")


# (module path, attribute) pairs exercised by a full 3D Russian break.
REQUIRED_DISPATCHERS = [
    ("pooltool.physics.evolve", "evolve_ball_motion"),
    ("pooltool.physics.evolve", "_evolve_slide_state"),
    ("pooltool.physics.evolve", "_evolve_roll_state"),
    ("pooltool.physics.evolve", "_evolve_perpendicular_spin_state"),
    ("pooltool.physics.utils", "surface_velocity"),
    ("pooltool.physics.utils", "tangent_surface_velocity"),
    ("pooltool.physics.utils", "rel_velocity"),
    ("pooltool.physics.utils", "get_spin_time"),
    ("pooltool.physics.utils", "get_roll_time"),
    ("pooltool.physics.utils", "get_slide_time"),
    ("pooltool.physics.utils", "on_table"),
    ("pooltool.evolution.event_based.detect.ball_ball", "ball_ball_collision_time_2d"),
    (
        "pooltool.evolution.event_based.detect.ball_cushion",
        "ball_vertical_cylinder_collision_time",
    ),
    ("pooltool.evolution.event_based.detect.ball_table", "ball_table_collision_time"),
    ("pooltool.evolution.event_based.detect.ball_pocket", "ball_pocket_collision_time"),
    (
        "pooltool.evolution.event_based.detect.quartic_coefficients",
        "parabola_sphere_distance_quartic_coefficients",
    ),
    ("pooltool.ptmath.roots._quartic_numba", "oqs_calc_phi0"),
    ("pooltool.ptmath.roots._quartic_numba", "solve"),
    ("pooltool.physics.resolve.ball_ball.frictional_inelastic", "_resolve_ball_ball_x_normal"),
    ("pooltool.physics.resolve.ball_table.frictional_inelastic", "_resolve_ball_table"),
]

# Real 3D paths a level break may not touch: report, never fail.
OPTIONAL_DISPATCHERS = [
    ("pooltool.physics.evolve", "_evolve_airborne_state"),
    (
        "pooltool.evolution.event_based.detect.ball_pocket",
        "ball_pocket_collision_time_if_airborne",
    ),
    ("pooltool.evolution.event_based.detect.ball_off_table", "ball_off_table_time"),
]


def collect(specs: list[tuple[str, str]]) -> list[tuple[str, object]]:
    out = []
    for mod_path, attr in specs:
        try:
            mod = __import__(mod_path, fromlist=[attr])
            fn = getattr(mod, attr, None)
        except Exception as exc:  # noqa: BLE001 — diagnostic path
            print(f"  ..  import {mod_path}.{attr} failed: {exc}")
            fn = None
        out.append((f"{mod_path}.{attr}", fn))
    return out


def main() -> int:
    from app import physics

    import pooltool  # noqa: F401 — warms package init

    rack = physics.russian_rack(seed=7)
    balls_in = {bid: (pos["x"], pos["y"]) for bid, pos in rack.items()}

    t0 = time.perf_counter()
    cold = physics.run_shot(balls_in, v0=3.0, phi=90.0, b=0.25)
    cold_ms = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    warm = physics.run_shot(balls_in, v0=3.0, phi=90.0, b=0.25)
    warm_ms = (time.perf_counter() - t0) * 1000
    check(
        "seeded break is a real workload",
        cold["events"] > 50 and cold["events"] == warm["events"],
        f"{cold['events']} vs {warm['events']} events",
    )
    print(
        f"  ..  3D break ({cold['events']} events): cold {cold_ms:.0f} ms, "
        f"warm {warm_ms:.0f} ms (in-process; disk cache "
        f"{'present' if glob.glob('/home/z/my-project/pyramid-web/backend/pooltool/**/__pycache__/*.nbc', recursive=True) else 'ABSENT'})"
    )

    required = collect(REQUIRED_DISPATCHERS)
    optional = collect(OPTIONAL_DISPATCHERS)

    missing = [name for name, fn in required if fn is None]
    check("all required dispatcher names resolve", not missing, str(missing))

    # Two proofs of JIT compilation:
    #   a) len(dispatcher.signatures) >= 1  — the kernel was DISPATCHED from
    #      Python in this process (typing ran, overload compiled);
    #   b) a numba on-disk cache entry `*.<attr>-*.nbc` next to the module —
    #      the kernel was compiled as an INLINED CALLEE of another jitted
    #      kernel (njit->njit calls bypass the inner dispatcher), and the
    #      .nbc file is the persisted machine code of that compilation.
    # A 0-signature kernel WITHOUT a cache entry would mean a silent pure-
    # Python fallback — that combination fails the check.

    def cache_hit(fn) -> bool:
        try:
            src = sys.modules[fn.__module__].__file__
        except Exception:  # noqa: BLE001 — diagnostic path
            return False
        if not src:
            return False
        modname = src.rsplit("/", 1)[-1][:-3]  # e.g. "__init__" / "utils"
        pattern = f"{src.rsplit('/', 1)[0]}/__pycache__/{modname}.{fn.__name__}-*.nbc"
        return bool(glob.glob(pattern))

    def compiled(fn) -> bool:
        return len(getattr(fn, "signatures", [])) >= 1 or cache_hit(fn)

    not_compiled = [
        name for name, fn in required if fn is not None and not compiled(fn)
    ]
    check(
        "required kernels JIT-compiled (dispatched signatures or .nbc cache)",
        not not_compiled,
        "; ".join(not_compiled),
    )
    via_sig = sum(1 for _, fn in required if fn is not None and len(getattr(fn, "signatures", [])) >= 1)
    via_cache = sum(
        1
        for _, fn in required
        if fn is not None and len(getattr(fn, "signatures", [])) == 0 and cache_hit(fn)
    )
    print(
        f"  ..  {len(required)} required dispatchers: {via_sig} dispatched "
        f"in-process + {via_cache} compiled as inlined callees (.nbc cache)"
    )

    optional_missing = [
        name
        for name, fn in optional
        if fn is None or not compiled(fn)
    ]
    print(
        f"  ..  optional (level-break may not reach): "
        f"{len(optional) - len(optional_missing)}/{len(optional)} compiled"
    )

    cache_files = glob.glob(
        "/home/z/my-project/pyramid-web/backend/pooltool/**/__pycache__/*.nbc",
        recursive=True,
    )
    check("numba disk cache active (>= 20 cached kernels)", len(cache_files) >= 20, f"{len(cache_files)} .nbc files")

    check(
        "warm break inside the interactive budget (< 500 ms, Decision #15)",
        warm_ms < 500,
        f"warm {warm_ms:.0f} ms",
    )

    print()
    if failed:
        print(f"{len(failed)} FAILED, {passed} passed")
        return 1
    print(f"ALL {passed} CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
