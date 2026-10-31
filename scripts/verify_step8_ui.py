#!/usr/bin/env python3
"""Step 8 acceptance test: UI polish & camera.

Two parts, both browser-free (the standing no-browser rule):

``--static``  (default: runs first, no server needed)
  - node --check on all three frontend JS files
  - py_compile + ruff on the touched backend files
  - node scripts/test_step8_ui_math.mjs (19 pure-math unit checks)
  - index.html <-> lobby.js element-id cross-check (every el the client
    grabs must exist in the markup; the retired ids must be GONE)
  - style.css presence checks (HUD bar, chips, cameras, responsive queries)
  - behavioral greps on main.js / lobby.js / backend (tween wiring,
    user-cancel, persistence, clock stamping in both broadcasts, ...)

``--live``    (backend listening on 127.0.0.1:8100, physics warmed)
  - game_started snapshot carries the turn clock (turn_started_ms /
    now_ms, sane against the local clock)
  - a break shot + a mid-game stroke refresh the clock every result
  - remaining-ball arithmetic: len(balls) matches pocketed/respotted/
    removed exactly (this is what the HUD chips render)
  - both clients receive identical game snapshots (Step 5/6 invariant)
  - kf_stats still present on every shot (Step 7 intact)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # /home/z/my-project
PWEB = ROOT / "pyramid-web"
FRONT = PWEB / "frontend"
BACKEND_APP = PWEB / "backend" / "app"

URI = "ws://127.0.0.1:8100/ws"
BASE = "http://127.0.0.1:8100"

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


# ---------------------------------------------------------------------------
# static part
# ---------------------------------------------------------------------------


def run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,  # the return code IS the result
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def static_checks() -> None:
    print("== static: syntax ==")
    for js in ("main.js", "lobby.js", "ui_math.js"):
        code, out = run(["node", "--check", str(FRONT / js)])
        check(f"node --check {js}", code == 0, out[:200])

    code, out = run(
        [
            sys.executable,
            "-m",
            "py_compile",
            str(BACKEND_APP / "lobby.py"),
            str(BACKEND_APP / "main.py"),
            str(BACKEND_APP / "rules.py"),
        ]
    )
    check("py_compile backend/app", code == 0, out[:200])

    code, out = run(["uvx", "ruff", "check", str(BACKEND_APP), str(Path(__file__))])
    check("ruff check (backend/app + verifier)", code == 0, out[:300])

    print("== static: ui_math unit tests ==")
    code, out = run(["node", str(ROOT / "scripts" / "test_step8_ui_math.mjs")])
    check(
        "node scripts/test_step8_ui_math.mjs",
        code == 0 and "all 19 ui_math checks passed" in out,
        out[-300:],
    )

    print("== static: markup <-> client cross-check ==")
    html = (FRONT / "index.html").read_text()
    lobby_js = (FRONT / "lobby.js").read_text()
    main_js = (FRONT / "main.js").read_text()
    css = (FRONT / "style.css").read_text()

    grabbed = set(re.findall(r"getElementById\('([^']+)'\)", lobby_js))
    grabbed |= set(re.findall(r"getElementById\('([^']+)'\)", main_js))
    # ids created at runtime by lobby.js, never present in the static markup
    DYNAMIC_IDS = {"ghud-balls-count"}
    missing = [
        gid
        for gid in sorted(grabbed)
        if gid not in DYNAMIC_IDS and f'id="{gid}"' not in html
    ]
    check("every getElementById id exists in index.html", not missing, str(missing))

    retired = [gid for gid in ("game-mode-line", "game-scorebar", "game-turn") if f'id="{gid}"' in html]
    check("retired panel-status ids removed from index.html", not retired, str(retired))

    for needed in (
        'id="gamehud"',
        'id="ghud-mode"',
        'id="ghud-shot"',
        'id="ghud-players"',
        'id="ghud-turn"',
        'id="ghud-clock"',
        'id="ghud-balls"',
        'id="ghud-cams"',
        'id="turn-toast"',
        'id="btn-panel-toggle"',
        'id="panel-body"',
    ):
        check(f"index.html has {needed}", needed in html)

    print("== static: style.css ==")
    for needed in (
        "#gamehud",
        ".ghud-player.turn",
        ".ball-chip.off",
        ".cam-btn.selected",
        "#turn-toast.fade",
        "#lobby-game.collapsed #panel-body",
        "@media (max-width: 980px)",
        "@media (max-width: 700px), (orientation: portrait) and (max-width: 820px)",
        "@media (min-aspect-ratio: 21/9)",
        "@media (prefers-reduced-motion: reduce)",
    ):
        check(f"style.css has {needed}", needed in css)
    # braces balance: a cheap syntax tripwire
    check("style.css braces balanced", css.count("{") == css.count("}"))

    print("== static: behavior greps ==")
    behavior = [
        (main_js, "FOV_DEG,", "main.js imports the shared FOV constant"),
        (main_js, "controls.addEventListener('start', cancelCamTween)", "user input cancels the camera tween"),
        (main_js, "if (camTween) stepCamTween();", "tween stepped in the render loop"),
        (main_js, "localStorage.setItem(VIEW_STORAGE_KEY", "view persisted to localStorage"),
        (main_js, "scene.fog.near = d * 1.6;", "fog scales with the framing distance"),
        (main_js, "controls.maxDistance = 15.0;", "maxDistance raised for portrait fits"),
        (main_js, "setView,\n  views: () => [...VIEW_NAMES],", "__pyramid exports setView/views"),
        (main_js, "const VIEW_NAMES = ['orbit', 'top', 'south', 'north'];", "four camera presets defined"),
        (lobby_js, "import { deriveHud, formatElapsed } from './ui_math.js'", "lobby.js imports the shared math"),
        (lobby_js, "buildCamButtons();", "camera buttons built on game start"),
        (lobby_js, "startHudClock();", "HUD clock ticker started on game start"),
        (lobby_js, "state.clockOffsetMs = Number.isFinite(now) ? now - Date.now() : 0;", "clock skew captured at snapshot arrival"),
        (lobby_js, "els.game.classList.toggle('collapsed')", "panel collapse wired"),
        (lobby_js, "showToast('Your turn')", "turn toast wired"),
        (lobby_js, "hud: () => ({", "hud() debug hook exported"),
    ]
    for haystack, needle, label in behavior:
        check(label, needle in haystack, needle[:60])

    lobby_py = (BACKEND_APP / "lobby.py").read_text()
    for needle, label in (
        ("room.stamp_turn_clock(", "backend stamps the turn clock on snapshots"),
        (
            "room.turn_started_ms = int(time.time() * 1000)",
            "clock refreshed after every shot",
        ),
    ):
        check(label, needle in lobby_py, needle[:60])


def rest_get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as resp:
        return json.loads(resp.read())


async def recv(ws, want: str | None = None, timeout: float = 90) -> dict:
    raw = await asyncio.wait_for(ws.recv(), timeout)
    msg = json.loads(raw)
    if want is not None:
        assert msg.get("type") == want, f"expected {want}, got {str(msg)[:200]}"
    return msg


async def live_checks() -> None:
    import websockets

    health = rest_get("/api/health")
    check("backend healthy + physics warmed", health.get("physics_ready") is True)

    async with websockets.connect(URI) as a, websockets.connect(URI) as b:
        await a.send(json.dumps({"type": "create", "name": "Alice"}))
        joined = await recv(a, "joined")
        code = joined["room"]
        await b.send(json.dumps({"type": "join", "room": code, "name": "Bob"}))
        await recv(b, "joined")
        await recv(b, "player_list")
        await recv(a, "player_list")

        await a.send(json.dumps({"type": "start_game"}))
        gs_a = await recv(a, "game_started")
        gs_b = await recv(b, "game_started")
        snap = gs_a["game"]

        print("== live: turn clock on game_started ==")
        t0 = snap.get("turn_started_ms")
        n0 = snap.get("now_ms")
        check("snapshot carries turn_started_ms (int > 0)", isinstance(t0, int) and t0 > 0)
        check("snapshot carries now_ms (int > 0)", isinstance(n0, int) and n0 > 0)
        skew = abs(n0 - int(time.time() * 1000))
        check("now_ms within 10 s of the local clock", skew < 10_000, f"skew {skew} ms")
        check("turn_started_ms <= now_ms", t0 <= n0)

        print("== live: Step 6 snapshot fields intact ==")
        check(
            "mode/target/turn/scores present",
            snap.get("mode_name") == "Free Pyramid"
            and snap.get("target_score") == 8
            and isinstance(snap.get("turn"), dict)
            and len(snap.get("scores", [])) == 2,
        )
        check(
            "game snapshots identical on both clients",
            json.dumps(gs_a["game"], sort_keys=True) == json.dumps(gs_b["game"], sort_keys=True),
        )

        # --- break shot -------------------------------------------------------
        shooter = snap["turn"]["id"]
        ws_by_id = a if joined["player_id"] == shooter else b
        await ws_by_id.send(json.dumps({"type": "shot", "v0": 9.0, "phi": 90.0}))
        sr1 = await recv(a, "shot_result")
        sr1_b = await recv(b, "shot_result")
        s1 = sr1["game"]

        print("== live: break shot refreshes the clock ==")
        t1 = s1.get("turn_started_ms")
        n1 = s1.get("now_ms")
        check("turn_started_ms refreshed (>= game start)", isinstance(t1, int) and t1 >= t0)
        check("now_ms fresh (>= turn_started_ms)", isinstance(n1, int) and n1 >= t1)
        check("clock just reset (< 5 s)", n1 - t1 < 5_000, f"{n1 - t1} ms")

        print("== live: remaining-ball arithmetic (HUD chips source) ==")
        balls = sr1["balls"]
        pocketed, respotted, removed = sr1["pocketed"], sr1["respotted"], sr1["removed"]
        expected = 16 - (len(pocketed) - len(respotted)) - len(removed)
        check(
            f"len(balls) == 16 - pocketed - removed + respotted ({expected})",
            len(balls) == expected,
            f"got {len(balls)}",
        )
        object_ids = [k for k in balls if k != "cue"]
        check("object-ball ids stay within 1..15", all(k in {str(n) for n in range(1, 16)} for k in object_ids))
        check("kf_stats present on the shot (Step 7 intact)", isinstance(sr1.get("kf_stats"), dict))

        print("== live: mid-game stroke ==")
        shooter2 = s1["turn"]["id"]
        ws2 = a if joined["player_id"] == shooter2 else b
        await ws2.send(json.dumps({"type": "shot", "v0": 4.5, "phi": 15.0}))
        sr2 = await recv(a, "shot_result")
        sr2_b = await recv(b, "shot_result")
        s2 = sr2["game"]
        t2, n2 = s2.get("turn_started_ms"), s2.get("now_ms")
        check("second shot refreshes the clock again", isinstance(t2, int) and t2 >= t1 and n2 >= t2)
        check("second shot clock just reset (< 5 s)", n2 - t2 < 5_000, f"{n2 - t2} ms")
        check(
            "identical snapshots after the stroke",
            json.dumps(sr1["game"], sort_keys=True) == json.dumps(sr1_b["game"], sort_keys=True)
            and json.dumps(sr2["game"], sort_keys=True) == json.dumps(sr2_b["game"], sort_keys=True),
        )
        balls2 = sr2["balls"]
        exp2 = expected - (len(sr2["pocketed"]) - len(sr2["respotted"])) - len(sr2["removed"])
        check(f"balls shrank consistently again ({exp2})", len(balls2) == exp2, f"got {len(balls2)}")

        print("== live: chips math against live data ==")
        # mirrors frontend ballChips(): count of 1..15 present in balls
        chips_on = [n for n in range(1, 16) if str(n) in balls2]
        check(
            "chip count == object balls on table",
            len(chips_on) == len(balls2) - ("cue" in balls2),
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--static", action="store_true", help="static checks only")
    ap.add_argument("--live", action="store_true", help="live WS checks only")
    args = ap.parse_args()

    if not args.live:
        static_checks()
    if not args.static:
        asyncio.run(live_checks())

    print(f"\n{passed} checks passed, {len(failed)} failed")
    if failed:
        for name in failed:
            print(f"  FAILED: {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
