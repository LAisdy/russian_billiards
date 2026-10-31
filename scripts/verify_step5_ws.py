#!/usr/bin/env python3
"""Step 5 acceptance test: shot synchronization over the live WebSocket.

Run (backend listening on 127.0.0.1:8100, physics warmed):
    backend/.venv/bin/python scripts/verify_step5_ws.py

Covers: shot before start -> error, game_started carries a 16-ball rack,
shot -> shot_result broadcast to BOTH clients with identical valid keyframes,
keyframe last frame == authoritative balls, consecutive shots chain from the
previous final state, invalid shot -> non-fatal error, REST keyframes mode.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import math
import sys
import urllib.request

import websockets

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


async def recv(ws, want: str | None = None, timeout: float = 30) -> dict:
    raw = await asyncio.wait_for(ws.recv(), timeout)
    msg = json.loads(raw)
    if want is not None:
        assert msg.get("type") == want, f"expected {want}, got {str(msg)[:200]}"
    return msg


def rest_post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def valid_keyframes(kf: dict, n_balls: int) -> str | None:
    """Structural validation; returns None when valid else a reason."""
    if set(kf) != {"ids", "dt_ms", "duration_ms", "frames", "events"}:
        return f"unexpected keys: {sorted(kf)}"
    if len(kf["ids"]) != n_balls or kf["ids"][-1] != "cue":
        return f"ids wrong: {kf['ids']}"
    frames = kf["frames"]
    if len(frames) < 2:
        return "needs >= 2 frames"
    times = [f[0] for f in frames]
    if any(b <= a for a, b in itertools.pairwise(times)):
        return "frame times not strictly increasing"
    if times[0] != 0 or times[-1] != kf["duration_ms"]:
        return f"t0={times[0]} tN={times[-1]} vs dur={kf['duration_ms']}"
    for f in frames:
        if len(f) != 1 + 2 * n_balls:
            return f"row width {len(f)} != {1 + 2 * n_balls}"
        for v in f:
            if (
                not isinstance(v, (int, float))
                or isinstance(v, bool)
                or not math.isfinite(v)
            ):
                return f"bad value {v!r}"
    for ev in kf["events"]:
        if set(ev) != {"t_ms", "type", "balls"}:
            return f"bad event {ev}"
    return None


async def main() -> int:
    async with websockets.connect(URI) as a, websockets.connect(URI) as b:
        await a.send(json.dumps({"type": "create", "name": "Alice"}))
        m = await recv(a, "joined")
        code = m["room"]

        await b.send(json.dumps({"type": "join", "room": code, "name": "Bob"}))
        await recv(b, "joined")
        await recv(b, "player_list")  # join broadcast
        await recv(a, "player_list")  # join broadcast

        # 1. shot before the game starts -> non-fatal error
        await b.send(json.dumps({"type": "shot", "v0": 2.0, "phi": 90.0}))
        m = await recv(b)
        check(
            "shot before start -> error not_playing",
            m.get("type") == "error" and m.get("code") == "not_playing",
            str(m)[:120],
        )

        # 2. start -> game_started carries the SAME rack to both clients
        await a.send(json.dumps({"type": "start_game"}))
        ga = await recv(a, "game_started")
        gb = await recv(b, "game_started")
        check(
            "game_started carries a 16-ball rack (incl. cue) to the host",
            len(ga.get("balls", {})) == 16 and "cue" in ga["balls"],
        )
        check(
            "both clients see the identical rack",
            ga["balls"] == gb["balls"],
        )

        # 3. invalid shot -> non-fatal error, socket still usable
        await a.send(json.dumps({"type": "shot", "v0": 99.0, "phi": 90.0}))
        m = await recv(a)
        check(
            "invalid v0 -> error invalid_shot",
            m.get("type") == "error" and m.get("code") == "invalid_shot",
            str(m)[:120],
        )

        # 4. Alice shoots -> BOTH receive shot_result with identical keyframes
        await a.send(json.dumps({"type": "shot", "v0": 1.4, "phi": 92.0}))
        ra = await recv(a, "shot_result", timeout=60)
        rb = await recv(b, "shot_result", timeout=60)
        check(
            "shot_result: shot_id 1 by Alice",
            ra["shot_id"] == 1 and ra["by_name"] == "Alice",
        )
        check(
            "Bob receives the same shot_id",
            rb["shot_id"] == 1 and rb["by_name"] == "Alice",
        )
        # Keyframes ids are the PRE-shot on-table set; msg.balls is POST-shot
        # (scored balls gone, penalty balls removed, scratches respotted).
        # Structural validity therefore anchors on the dealt rack (Step 6
        # made the post-shot set diverge legitimately).
        vk1 = valid_keyframes(ra["keyframes"], len(ga["balls"]))
        check("keyframes structurally valid (pre-shot rack)", vk1 is None, str(vk1))
        check(
            "kf ids == pre-shot on-table set (cue last)",
            set(ra["keyframes"]["ids"]) == set(ga["balls"])
            and ra["keyframes"]["ids"][-1] == "cue",
        )
        check(
            "identical keyframes broadcast to both clients",
            json.dumps(ra["keyframes"], sort_keys=True)
            == json.dumps(rb["keyframes"], sort_keys=True),
        )
        check(
            "identical authoritative balls on both clients",
            ra["balls"] == rb["balls"],
        )
        check(
            "pocketed list present (may be empty)",
            isinstance(ra["pocketed"], list),
        )
        # last keyframe == authoritative state for every on-table ball.
        # Step 6: balls the ruleset RESPOTTED (scratch cue, «свояк») sit at
        # their post-ruleset spots in msg.balls while the keyframes keep the
        # in-pocket trajectory — the client snaps to msg.balls after the
        # animation, so respotted ids are exempt from this comparison.
        kf = ra["keyframes"]
        col = {bid: i for i, bid in enumerate(kf["ids"])}
        last = kf["frames"][-1]
        respotted = set(ra.get("respotted") or [])
        mism = []
        for bid, p in ra["balls"].items():
            if bid in respotted:
                continue
            i = col[bid]
            if (
                abs(last[1 + 2 * i] - p["x"]) > 1e-3
                or abs(last[2 + 2 * i] - p["y"]) > 1e-3
            ):
                mism.append(bid)
        check(
            "last keyframe == authoritative balls (<=1 mm, respotted exempt)",
            not mism,
            str(mism),
        )
        # frame 0 == the rack the clients saw (server chained from its state)
        gs_balls = ga["balls"]
        mism = []
        for bid, p in gs_balls.items():
            i = col[bid]
            if (
                abs(kf["frames"][0][1 + 2 * i] - p["x"]) > 1e-3
                or abs(kf["frames"][0][2 + 2 * i] - p["y"]) > 1e-3
            ):
                mism.append(bid)
        check("first keyframe == game_started rack (<=1 mm)", not mism, str(mism))
        cue_before = gs_balls["cue"]
        cue_after = ra["balls"]["cue"]
        moved = (
            (cue_after["x"] - cue_before["x"]) ** 2
            + (cue_after["y"] - cue_before["y"]) ** 2
        ) ** 0.5
        check("cue ball actually moved", moved > 0.05, f"{moved:.3f} m")
        final1 = ra["balls"]

        # 5. second shot chains from the previous final state
        await b.send(json.dumps({"type": "shot", "v0": 1.2, "phi": 70.0}))
        rb2 = await recv(b, "shot_result", timeout=60)
        ra2 = await recv(a, "shot_result", timeout=60)
        check(
            "second shot: shot_id 2 by Bob",
            rb2["shot_id"] == 2 and rb2["by_name"] == "Bob",
        )
        kf2 = rb2["keyframes"]
        col2 = {bid: i for i, bid in enumerate(kf2["ids"])}
        first2 = kf2["frames"][0]
        mism = []
        for bid, p in final1.items():
            i = col2[bid]
            if (
                abs(first2[1 + 2 * i] - p["x"]) > 1e-3
                or abs(first2[2 + 2 * i] - p["y"]) > 1e-3
            ):
                mism.append(bid)
        check(
            "shot 2 starts from shot 1's final state (<=1 mm)",
            not mism,
            str(mism),
        )
        vk2 = valid_keyframes(kf2, len(final1))
        check(
            "shot 2 keyframes valid and identical for both clients",
            vk2 is None
            and json.dumps(ra2["keyframes"], sort_keys=True)
            == json.dumps(rb2["keyframes"], sort_keys=True),
            f"valid={vk2!r} "
            f"identical={json.dumps(ra2['keyframes'], sort_keys=True) == json.dumps(rb2['keyframes'], sort_keys=True)}",
        )

    # 6. REST keyframes mode (stun shot: only the object ball drops)
    out = rest_post(
        "/api/shot",
        {
            "balls": {"cue": {"x": 0.30, "y": 0.30}, "1": {"x": 0.15, "y": 0.15}},
            "v0": 1.5,
            "phi": 225.0,
            "b": 0.0,
            "keyframes": True,
        },
    )
    check(
        "REST keyframes mode: structure + pocketed ['1']",
        valid_keyframes(out["keyframes"], 2) is None and out["pocketed"] == ["1"],
        str(out.get("pocketed")),
    )

    print()
    if failed:
        print(f"{len(failed)} FAILED, {passed} passed")
        return 1
    print(f"ALL {passed} CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
