#!/usr/bin/env python3
"""Cross-process numba disk-cache proof for the 16-second-shot fix.

Run this script TWICE (two separate OS processes). With a healthy disk
cache the FIRST shot of the SECOND process must already be fast — that is
exactly the situation of a freshly restarted Render container carrying the
Dockerfile's baked JIT cache.

    PYTHONHASHSEED=0 python jit_cache_crosscheck.py   # run 1
    PYTHONHASHSEED=0 python jit_cache_crosscheck.py   # run 2 (cache prebaked)

Prints, per process:
  import+first-break wall time (cold path: cache load + any re-JIT)
  second-break wall time      (steady state)
  exit code 0 iff first < 3000 ms and second < 500 ms (Decision #15 headroom)
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, "/home/z/my-project/pyramid-web/backend")
os.environ.setdefault("PYTHONHASHSEED", "0")

T_IMPORT0 = time.perf_counter()
from app import physics  # noqa: E402  (deliberate late import for timing)

T_IMPORT_MS = (time.perf_counter() - T_IMPORT0) * 1000

rack = physics.russian_rack(seed=7)
balls_in = {bid: (p["x"], p["y"]) for bid, p in rack.items()}

t0 = time.perf_counter()
r1 = physics.run_shot_keyframes(balls_in, v0=3.0, phi=90.0)
first_ms = (time.perf_counter() - t0) * 1000

t0 = time.perf_counter()
r2 = physics.run_shot_keyframes(balls_in, v0=3.0, phi=90.0)
second_ms = (time.perf_counter() - t0) * 1000

print(f"import+attrs setup : {T_IMPORT_MS:8.1f} ms")
print(f"FIRST keyframes shot: {first_ms:8.1f} ms ({r1['sim_ms']:.1f} ms sim, "
      f"{len(r1['keyframes']['frames'])} frames, {r1['kf_stats']['bytes']} B)")
print(f"SECOND shot        : {second_ms:8.1f} ms ({r2['sim_ms']:.1f} ms sim)")

ok = first_ms < 3000 and second_ms < 500
print("CACHE VERDICT:", "HOT (disk cache effective — no per-shot JIT)" if ok
      else "COLD (JIT recompilation happened — bake/cache broken)")
sys.exit(0 if ok else 1)
