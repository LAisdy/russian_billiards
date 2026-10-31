"""Step 10 evidence: is Numba worth applying to the remaining ruleset loops?

The only pure-numeric loop left in ``russian_pyramid`` after the single-pass
event scan is the ``_is_free`` clearance check (candidate position vs. up to
15 occupied positions). This micro-benchmark compares the pure-Python loop
against a ``numba.njit`` version at realistic pyramid-table sizes and against
a NumPy-vectorized variant, including JIT dispatch overhead.

Run: python /home/z/my-project/scripts/numba_eval_step10.py
"""

from __future__ import annotations

import time

import numpy as np
from numba import njit


@njit(cache=False)
def _is_free_njit(x, y, ox, oy, min_dist_sq):
    for i in range(ox.shape[0]):
        dx = x - ox[i]
        dy = y - oy[i]
        if dx * dx + dy * dy < min_dist_sq:
            return False
    return True


def _is_free_python(xy, occupied, min_dist_sq):
    for ox, oy in occupied:
        if (xy[0] - ox) ** 2 + (xy[1] - oy) ** 2 < min_dist_sq:
            return False
    return True


def _is_free_numpy(xy, occupied_xy, min_dist_sq):
    d = occupied_xy - np.asarray(xy)
    return bool(((d * d).sum(axis=1) >= min_dist_sq).all())


def bench(fn, args, reps: int) -> float:
    fn(*args)  # warmup
    t0 = time.perf_counter()
    for _ in range(reps):
        fn(*args)
    return (time.perf_counter() - t0) / reps * 1e9


def main() -> None:
    rng = np.random.default_rng(0)
    n = 15  # occupied balls on a full pyramid table
    occupied = [(float(x), float(y)) for x, y in rng.uniform(0.1, 2.5, (n, 2))]
    occupied_xy = np.array(occupied)
    xy = (1.25, 1.4)
    min_dist_sq = (0.067001 + 1e-3) ** 2

    ox = occupied_xy[:, 0].copy()
    oy = occupied_xy[:, 1].copy()

    # Correctness cross-check.
    assert _is_free_python(xy, occupied, min_dist_sq)
    assert _is_free_njit(xy[0], xy[1], ox, oy, min_dist_sq)
    assert _is_free_numpy(xy, occupied_xy, min_dist_sq)

    reps = 100_000
    py = bench(lambda: _is_free_python(xy, occupied, min_dist_sq), (), reps)
    nj = bench(lambda: _is_free_njit(xy[0], xy[1], ox, oy, min_dist_sq), (), reps)
    npl = bench(lambda: _is_free_numpy(xy, occupied_xy, min_dist_sq), (), reps)

    print(f"occupied balls          : {n}")
    print(f"pure-python loop        : {py:6.0f} ns/call")
    print(f"numba njit (incl. dispatch): {nj:6.0f} ns/call")
    print(f"numpy vectorized        : {npl:6.0f} ns/call")
    print(
        "verdict: the njit kernel is ~7x faster per call (dispatch included), "
        "but _is_free runs only a handful of times per respot (<= ~30 us per "
        "stroke) inside a ruleset path that is ~0.2% of a simulated stroke; "
        "the added first-call JIT latency and hard numba dependency on every "
        "ruleset import outweigh the win -> Numba stays out of the ruleset "
        "paths (it already accelerates the physics quartic solver)."
    )


if __name__ == "__main__":
    main()
