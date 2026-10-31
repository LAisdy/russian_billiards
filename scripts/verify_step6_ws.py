#!/usr/bin/env python3
"""Step 6 acceptance test: game modes & rulesets over the live WebSocket.

Run (backend listening on 127.0.0.1:8100, physics warmed):
    backend/.venv/bin/python scripts/verify_step6_ws.py

Covers: set_mode (host-only, validated, broadcast via player_list), the
game snapshot riding game_started / shot_result (identical on both
clients), turn enforcement (not_your_turn for shot AND place_cue), Classic
call validation (invalid_call), ball-in-hand placement (invalid_placement
+ cue_placed broadcast feeding the next shot), /api/modes, and REST
keyframes parity (the stateless endpoint must be unchanged by Step 6).
"""

from __future__ import annotations

import asyncio
import json
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


async def recv(ws, want: str | None = None, timeout: float = 60) -> dict:
    raw = await asyncio.wait_for(ws.recv(), timeout)
    msg = json.loads(raw)
    if want is not None:
        assert msg.get("type") == want, f"expected {want}, got {str(msg)[:200]}"
    return msg


def rest_get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as resp:
        return json.loads(resp.read())


def rest_post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


async def error_of(ws, payload: dict) -> dict:
    await ws.send(json.dumps(payload))
    while True:
        msg = await recv(ws)
        if msg.get("type") == "error":
            return msg


async def main() -> int:
    async with websockets.connect(URI) as a, websockets.connect(URI) as b:
        await a.send(json.dumps({"type": "create", "name": "Alice"}))
        m = await recv(a, "joined")
        code = m["room"]
        check("joined carries the default mode", m.get("mode") == "free")

        await b.send(json.dumps({"type": "join", "room": code, "name": "Bob"}))
        await recv(b, "joined")
        await recv(b, "player_list")
        await recv(a, "player_list")

        # 1. mode selection
        await a.send(json.dumps({"type": "set_mode", "mode": "dynamic"}))
        ma = await recv(a, "player_list")
        mb = await recv(b, "player_list")
        check(
            "set_mode broadcast to both players",
            ma.get("mode") == "dynamic" and mb.get("mode") == "dynamic",
            str(ma),
        )
        m = await error_of(a, {"type": "set_mode", "mode": "nonsense"})
        check("invalid mode rejected", m.get("code") == "invalid_mode", str(m))
        m = await error_of(b, {"type": "set_mode", "mode": "classic"})
        check("non-host cannot set the mode", m.get("code") == "not_host", str(m))

        # 2. start: game_started carries mode + full game snapshot
        await a.send(json.dumps({"type": "start_game"}))
        ga = await recv(a, "game_started")
        gb = await recv(b, "game_started")
        check(
            "game_started: mode dynamic, target 8, 16-ball rack",
            ga["mode"] == "dynamic"
            and ga["target_score"] == 8
            and len(ga["balls"]) == 16,
            str(ga.get("mode")),
        )
        check("both clients see the identical rack + game", ga["balls"] == gb["balls"] and ga["game"] == gb["game"])
        g = ga["game"]
        host_id = ga["players"][0]["id"]
        check(
            "initial snapshot: host breaks with ball in hand behind the line",
            g["turn"]["id"] == host_id
            and g["turn"]["name"] == "Alice"
            and g["ball_in_hand"] == "behind_line"
            and g["call_shot"] is False
            and g["scores"] == [
                {"id": host_id, "name": "Alice", "score": 0},
                {"id": ga["players"][1]["id"], "name": "Bob", "score": 0},
            ]
            and g["game_over"] is False
            and len(g["hittable"]) == 15,
            str(g["turn"]) + g["ball_in_hand"],
        )

        # 3. turn enforcement (Bob is not the active player)
        m = await error_of(b, {"type": "shot", "v0": 2.0, "phi": 90.0})
        check("non-active player cannot shoot", m.get("code") == "not_your_turn", str(m))
        m = await error_of(b, {"type": "place_cue", "x": 0.9, "y": 0.5})
        check("non-active player cannot place the cue", m.get("code") == "not_your_turn", str(m))

        # 4. ball-in-hand placement
        m = await error_of(a, {"type": "place_cue", "x": 0.9, "y": 1.5})
        check("placement beyond the house line rejected", m.get("code") == "invalid_placement", str(m))
        m = await error_of(a, {"type": "place_cue", "x": 0.01, "y": 0.5})
        check("placement inside the cushion rejected", m.get("code") == "invalid_placement", str(m))
        await a.send(json.dumps({"type": "place_cue", "x": 0.9, "y": 0.5}))
        pa = await recv(a, "cue_placed")
        pb = await recv(b, "cue_placed")
        check(
            "cue_placed broadcast identically",
            pa == pb and pa["by_name"] == "Alice" and pa["x"] == 0.9 and pa["y"] == 0.5,
            str(pa),
        )

        # 5. Alice breaks; the placement feeds the shot
        await a.send(json.dumps({"type": "shot", "v0": 2.0, "phi": 90.0}))
        ra = await recv(a, "shot_result")
        rb = await recv(b, "shot_result")
        check("shot_result identical on both clients", ra == rb)
        check(
            "shot_result carries the verdict + respotted/removed lists",
            isinstance(ra["legal"], bool)
            and isinstance(ra["reason"], str)
            and isinstance(ra["respotted"], list)
            and isinstance(ra["removed"], list),
            str({k: ra.get(k) for k in ("legal", "reason", "respotted", "removed")}),
        )
        kf = ra["keyframes"]
        col = kf["ids"].index("cue")
        first = kf["frames"][0]
        check(
            "the shot started from the placed cue position",
            abs(first[1 + 2 * col] - 0.9) < 1e-3 and abs(first[2 + 2 * col] - 0.5) < 1e-3,
            str(first[1 + 2 * col : 3 + 2 * col]),
        )
        g2 = ra["game"]
        check(
            "post-shot game snapshot: scores tallied, turn defined",
            sum(s["score"] for s in g2["scores"]) >= 0
            and g2["turn"]["id"] in {p["id"] for p in ga["players"]}
            and g2["shot_number"] == 1
            and g2["last_shot"]["legal"] == ra["legal"],
            str(g2),
        )
        # whoever is NOT to shoot must be rejected
        noturn_ws, noturn_payload = (
            (b, {"type": "shot", "v0": 2.0, "phi": 45.0})
            if g2["turn"]["id"] == host_id
            else (a, {"type": "shot", "v0": 2.0, "phi": 45.0})
        )
        m = await error_of(noturn_ws, noturn_payload)
        check("turn enforcement after the shot", m.get("code") == "not_your_turn", str(m))

    # 6. Classic room: call validation
    async with websockets.connect(URI) as c, websockets.connect(URI) as d:
        await c.send(json.dumps({"type": "create", "name": "Carla"}))
        code = (await recv(c, "joined"))["room"]
        await d.send(json.dumps({"type": "join", "room": code, "name": "Dave"}))
        await recv(d, "joined")
        await recv(d, "player_list")
        await recv(c, "player_list")
        await c.send(json.dumps({"type": "set_mode", "mode": "classic"}))
        await recv(c, "player_list")
        await recv(d, "player_list")
        await c.send(json.dumps({"type": "start_game"}))
        gc = await recv(c, "game_started")
        check("classic room: mode + target 71", gc["mode"] == "classic" and gc["target_score"] == 71)

        # break (no call required on the break)
        await c.send(json.dumps({"type": "shot", "v0": 3.0, "phi": 90.0}))
        rc = await recv(c, "shot_result")
        g3 = rc["game"]
        check(
            "after the break Classic requires called shots",
            g3["call_shot"] is True and not g3["game_over"],
            str(g3.get("call_shot")),
        )
        turn_ws = c if g3["turn"]["id"] == gc["players"][0]["id"] else d
        other_ws = d if turn_ws is c else c
        m = await error_of(other_ws, {"type": "shot", "v0": 2.0, "phi": 90.0})
        check("classic: non-turn player rejected", m.get("code") == "not_your_turn", str(m))
        m = await error_of(turn_ws, {"type": "shot", "v0": 2.0, "phi": 90.0})
        check("classic: shot without a call rejected", m.get("code") == "invalid_call", str(m))
        m = await error_of(
            turn_ws, {"type": "shot", "v0": 2.0, "phi": 90.0, "ball_call": "99", "pocket_call": "lb"}
        )
        check("classic: call of a dead ball rejected", m.get("code") == "invalid_call", str(m))
        m = await error_of(
            turn_ws, {"type": "shot", "v0": 2.0, "phi": 90.0, "ball_call": "cue", "pocket_call": "lb"}
        )
        check("classic: call of the cue ball rejected", m.get("code") == "invalid_call", str(m))
        m = await error_of(
            turn_ws, {"type": "shot", "v0": 2.0, "phi": 90.0, "ball_call": g3["hittable"][0], "pocket_call": "xx"}
        )
        check("classic: call of an unknown pocket rejected", m.get("code") == "invalid_call", str(m))
        await turn_ws.send(
            json.dumps(
                {
                    "type": "shot",
                    "v0": 1.5,
                    "phi": 90.0,
                    "ball_call": g3["hittable"][0],
                    "pocket_call": "lb",
                }
            )
        )
        rok = await recv(turn_ws, "shot_result")
        check(
            "classic: valid call accepted, reason is a Classic verdict",
            rok["reason"]
            in {
                "legal",
                "legal_break",
                "no_contact",
                "illegal_completion",
                "illegal_break",
                "jumped_ball",
                "cue_potted",
                "house_first_contact",
                "uncalled_pot",
            },
            str(rok["reason"]),
        )

    # 7. REST parity + modes endpoint
    modes = rest_get("/api/modes")
    check(
        "/api/modes lists the four disciplines + pockets",
        [m["mode"] for m in modes["modes"]] == ["free", "combined", "dynamic", "classic"]
        and sorted(modes["pockets"]) == ["lb", "lc", "lt", "rb", "rc", "rt"],
        str(modes),
    )
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
        "REST /api/shot unchanged by Step 6 (no rules block, states included)",
        "rules" not in out
        and out["pocketed"] == ["1"]
        and out["balls"]["1"]["state"] == "pocketed",
        str(out.get("rules")),
    )

    print()
    if failed:
        print(f"{len(failed)} FAILED, {passed} passed")
        return 1
    print(f"ALL {passed} CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
