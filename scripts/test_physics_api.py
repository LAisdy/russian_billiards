#!/usr/bin/env python3
"""Step 3 acceptance test: the physics REST API + in-process vendored copy.

Expects uvicorn (app.main:app) already running on 127.0.0.1:8100 — the
one-shot Bash recipe is logged in pyramid-web/PROGRESS.md (Step 3). Run with
the BACKEND venv:

    pyramid-web/backend/.venv/bin/python scripts/test_physics_api.py

What it proves:
  1. GET /api/rack — 16 balls, correct ids, on-surface, non-overlapping,
     deterministic for a fixed seed; equipment echo (370x180, 67 mm, pockets).
  2. POST /api/shot — a full seeded 16-ball break returns a sane final state
     (all balls at rest, pocketed subset, bounds) and is deterministic.
  3. The HTTP result is IDENTICAL to running the same shot through the
     in-process vendored pooltool (same floats).
  4. Validation: bad input -> 422 with a clear message.
  5. Warmup: physics_ready flips true (numba kernels compiled at startup).

Writes /tmp/step3_http.json and /tmp/step3_vendored.json for the follow-up
original-repo comparison (scripts/test_physics_original.py).
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8100"
BACKEND_DIR = Path(__file__).resolve().parents[1] / "pyramid-web" / "backend"
SEED = 42
SHOT = {"v0": 4.0, "phi": 90.0}  # straight break towards the pyramid apex

TABLE_L = 3.70
TABLE_W = 1.80
BALL_R = 0.0335

checks: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> bool:
    ok = bool(cond)
    checks.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=60) as resp:
        return json.loads(resp.read())


def post(path: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"raw": body.decode("utf-8", "replace")}


def wait_for_warmup(timeout: float = 150.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if get("/api/health").get("physics_ready"):
                return True
        except OSError:
            pass
        time.sleep(2.0)
    return False


def balls_moved(a: dict, b: dict) -> int:
    return sum(
        1
        for ball_id in a
        if abs(a[ball_id]["x"] - b[ball_id]["x"]) > 1e-9
        or abs(a[ball_id]["y"] - b[ball_id]["y"]) > 1e-9
    )


def main() -> int:
    # --- health & warmup -------------------------------------------------------
    health = get("/api/health")
    check("health: status ok", health.get("status") == "ok")
    check(
        "health: version 0.3.0",
        health.get("version") == "0.3.0",
        health.get("version", "?"),
    )
    check("warmup: physics_ready becomes true", wait_for_warmup())

    # --- rack ------------------------------------------------------------------
    rack = get("/api/rack?seed=42")
    balls = rack["balls"]
    check(
        "rack: 16 balls with correct ids",
        len(balls) == 16 and set(balls) == {"cue"} | {str(i) for i in range(1, 16)},
    )
    on_surface = all(
        BALL_R - 1e-4 <= p["x"] <= TABLE_W - BALL_R + 1e-4
        and BALL_R - 1e-4 <= p["y"] <= TABLE_L - BALL_R + 1e-4
        for p in balls.values()
    )
    check("rack: every ball on the playing surface", on_surface)
    xy = [(p["x"], p["y"]) for p in balls.values()]
    min_dist = min(
        ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
        for i, (ax, ay) in enumerate(xy)
        for bx, by in xy[i + 1 :]
    )
    check(
        "rack: no overlapping balls",
        min_dist >= 2 * BALL_R - 1e-4,
        f"min dist {min_dist:.5f} m",
    )
    cue = balls["cue"]
    check(
        "rack: cue behind head string, apex at foot spot",
        abs(cue["x"] - 0.9) < 0.01 and abs(cue["y"] - 0.851) < 0.01,
        f"cue at ({cue['x']:.3f}, {cue['y']:.3f})",
    )
    apex_y = min(p["y"] for bid, p in balls.items() if bid != "cue")
    check(
        "rack: apex on foot spot (0.75*l)",
        abs(apex_y - 2.775) < 0.01,
        f"apex y={apex_y:.3f}",
    )
    table = rack["table"]
    check(
        "rack: equipment echo (370x180, 6 pockets, 67 mm ball)",
        table["length"] == 3.70
        and table["width"] == 1.80
        and len(table["pockets"]) == 6
        and rack["ball"]["diameter_mm"] == 67.0,
    )
    corner = table["pockets"]["lt"]
    check(
        "rack: pocket geometry matches physics layout",
        abs(corner["x"] + 0.0318) < 1e-3
        and abs(corner["y"] - 3.7318) < 1e-3
        and abs(corner["radius"] - 0.045) < 1e-6,
    )
    rack_again = get("/api/rack?seed=42")["balls"]
    check("rack: deterministic for a fixed seed", rack_again == balls)

    # --- break shot over HTTP ---------------------------------------------------
    status, resp = post("/api/shot", {"balls": balls, **SHOT})
    check("shot: HTTP 200", status == 200, f"status {status}")
    if status != 200:
        print(resp)
        return 1
    final, pocketed = resp["balls"], resp["pocketed"]
    check("shot: all 16 balls in the response", set(final) == set(balls))
    at_rest = all(
        b["state"] in {"stationary", "pocketed", "off_table"} for b in final.values()
    )
    check("shot: every ball reached a resting state", at_rest)
    check(
        "shot: non-pocketed balls stayed on the table",
        all(
            -0.15 <= b["x"] <= TABLE_W + 0.15 and -0.15 <= b["y"] <= TABLE_L + 0.15
            for bid, b in final.items()
            if bid not in pocketed
        ),
    )
    check("shot: pocketed is a subset of ball ids", set(pocketed) <= set(balls))
    check(
        "shot: break produced a substantial event stream",
        resp["events"] > 100,
        f"{resp['events']} events",
    )
    check(
        "shot: simulated duration plausible",
        1.0 < resp["duration_s"] < 60.0,
        f"{resp['duration_s']:.2f} s",
    )
    moved = balls_moved(balls, final)
    check("shot: the break scattered the rack", moved >= 10, f"{moved} balls moved")
    check(
        "shot: simulation time proportional to event count (JIT-warmed)",
        resp["sim_ms"] < max(2500.0, resp["events"] * 3.0),
        f"sim_ms={resp['sim_ms']} for {resp['events']} events "
        f"(~{resp['sim_ms'] / max(1, resp['events']):.2f} ms/event; library benchmark "
        "is ~1 ms/event for 3D)",
    )

    # --- determinism over HTTP --------------------------------------------------
    status2, resp2 = post("/api/shot", {"balls": balls, **SHOT})
    deterministic = status2 == 200 and {
        k: resp2[k] for k in ("balls", "pocketed", "duration_s", "events")
    } == {k: resp[k] for k in ("balls", "pocketed", "duration_s", "events")}
    check("shot: deterministic (repeat request)", deterministic)

    # --- small shot sanity -------------------------------------------------------
    mini = {"cue": {"x": 0.9, "y": 0.851}, "1": {"x": 0.9, "y": 1.5}}
    status3, resp3 = post("/api/shot", {"balls": mini, "v0": 2.0, "phi": 90.0})
    check("shot: 2-ball stroke accepted", status3 == 200, f"status {status3}")
    if status3 == 200:
        check(
            "shot: 2-ball stroke moved the object ball",
            balls_moved(mini, resp3["balls"]) >= 1,
            f"object ball now ({resp3['balls']['1']['x']:.3f}, {resp3['balls']['1']['y']:.3f})",
        )
        check(
            "shot: light stroke is fast (< 800 ms)",
            resp3["sim_ms"] < 800,
            f"sim_ms={resp3['sim_ms']} for {resp3['events']} events",
        )

    # --- in-process vendored copy: identical result ------------------------------
    sys.path.insert(0, str(BACKEND_DIR))
    from app.physics import run_shot

    vendored = run_shot(
        {bid: (p["x"], p["y"]) for bid, p in balls.items()},
        v0=SHOT["v0"],
        phi=SHOT["phi"],
    )
    identical = (
        vendored["balls"] == resp["balls"] and vendored["pocketed"] == resp["pocketed"]
    )
    max_diff = 0.0
    if not identical:
        for bid in resp["balls"]:
            max_diff = max(
                max_diff,
                abs(resp["balls"][bid]["x"] - vendored["balls"][bid]["x"]),
                abs(resp["balls"][bid]["y"] - vendored["balls"][bid]["y"]),
            )
    check(
        "vendored: in-process result identical to HTTP result",
        identical,
        f"max coord diff {max_diff:.2e}" if not identical else "float-exact",
    )

    Path("/tmp/step3_http.json").write_text(json.dumps(resp, indent=2))
    Path("/tmp/step3_input.json").write_text(json.dumps(balls, indent=2))
    vendored_out = {
        k: vendored[k] for k in ("balls", "pocketed", "duration_s", "events")
    }
    Path("/tmp/step3_vendored.json").write_text(json.dumps(vendored_out, indent=2))

    # --- validation -> 422 -------------------------------------------------------
    bad_cases = [
        ("no cue ball", {"1": {"x": 0.9, "y": 2.0}, "2": {"x": 0.5, "y": 2.0}}),
        (
            "ball off the table",
            {"cue": {"x": -0.9, "y": 0.851}, "1": {"x": 0.9, "y": 2.0}},
        ),
        (
            "overlapping balls",
            {"cue": {"x": 0.9, "y": 0.851}, "1": {"x": 0.9, "y": 0.87}},
        ),
    ]
    for label, bad_balls in bad_cases:
        status_bad, body = post("/api/shot", {"balls": bad_balls, **SHOT})
        check(
            f"validation: {label} -> 422",
            status_bad == 422 and "detail" in body,
            str(body.get("detail", ""))[:70],
        )

    for label, payload in [
        ("v0=0", {"balls": balls, "v0": 0.0, "phi": 90.0}),
        ("v0=11 (too strong)", {"balls": balls, "v0": 11.0, "phi": 90.0}),
        ("phi=360", {"balls": balls, "v0": 2.0, "phi": 360.0}),
        ("spin a=1.5", {"balls": balls, "v0": 2.0, "phi": 90.0, "a": 1.5}),
        ("unknown field", {"balls": balls, "v0": 2.0, "phi": 90.0, "power": 5}),
        ("empty balls", {"balls": {}, "v0": 2.0, "phi": 90.0}),
    ]:
        status_bad, body = post("/api/shot", payload)
        check(
            f"validation: {label} -> 422",
            status_bad == 422,
            str(body.get("detail", ""))[:70],
        )

    failed = [name for name, ok, _ in checks if not ok]
    print(
        f"\n{'=' * 60}\n"
        f"{len(checks) - len(failed)}/{len(checks)} checks passed"
        + (f"; FAILED: {failed}" if failed else " — ALL GREEN")
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
