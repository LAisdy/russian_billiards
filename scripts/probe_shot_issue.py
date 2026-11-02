#!/usr/bin/env python3
"""Live probe for the "Shoot does nothing" bug report (render.com deployment).

Reproduces the exact client flow over a real WebSocket connection:
  A creates, B joins, A starts a FREE-pyramid game, A places the cue ball
  (break ball-in-hand), A shoots -> expects shot_result with keyframes;
  then B shoots -> expects shot_result. Every message is dumped/summarized
  so a silent server exception or a malformed payload shows up immediately.

Usage: python probe_shot_issue.py [port]
"""

from __future__ import annotations

import asyncio
import json
import sys
import time

import websockets

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8100
URI = f"ws://127.0.0.1:{PORT}/ws"


def summarize(msg: dict) -> str:
    t = msg.get("type", "?")
    if t == "shot_result":
        kf = msg.get("keyframes") or {}
        return (
            f"shot_result id={msg.get('shot_id')} by={msg.get('by_name')} "
            f"legal={msg.get('legal')} reason={msg.get('reason')!r} "
            f"pocketed={msg.get('pocketed')} respotted={msg.get('respotted')} "
            f"removed={msg.get('removed')} sim_ms={msg.get('sim_ms')} "
            f"kf_frames={len(kf.get('frames', []))} "
            f"kf_events={len(kf.get('events', []))} "
            f"kf_duration_ms={kf.get('duration_ms')} "
            f"balls={len(msg.get('balls', {}))} "
            f"turn={(msg.get('game') or {}).get('turn', {}).get('name')}"
        )
    if t == "error":
        return f"ERROR code={msg.get('code')} message={msg.get('message')!r}"
    if t == "game_started":
        return f"game_started mode={msg.get('mode')} balls={len(msg.get('balls', {}))}"
    return f"{t}: {json.dumps(msg)[:160]}"


async def recv(ws, label: str, timeout: float = 90) -> dict:
    t0 = time.perf_counter()
    raw = await asyncio.wait_for(ws.recv(), timeout)
    dt = (time.perf_counter() - t0) * 1000
    msg = json.loads(raw)
    print(f"  [{label} +{dt:7.1f}ms] {summarize(msg)}")
    return msg


async def wait_for(ws, label: str, want_type: str, timeout: float = 90) -> dict:
    while True:
        msg = await recv(ws, label, timeout)
        if msg.get("type") == want_type:
            return msg


async def player(ws: websockets.WebSocketClientProtocol, label: str) -> dict:
    return {
        "ws": ws,
        "label": label,
        "id": None,
        "room": None,
    }


async def main() -> int:
    print(f"connecting to {URI}")
    async with websockets.connect(URI, max_size=50 * 1024 * 1024) as aw, \
               websockets.connect(URI, max_size=50 * 1024 * 1024) as bw:
        A = await player(aw, "A(host)")
        B = await player(bw, "B(guest)")

        await A["ws"].send(json.dumps({"type": "create", "name": "Hoster"}))
        m = await wait_for(A["ws"], "A", "joined")
        A["id"], A["room"] = m["player_id"], m["room"]
        print(f"A created room {A['room']} (id={A['id']})")

        await B["ws"].send(json.dumps({"type": "join", "room": A["room"], "name": "Guester"}))
        await wait_for(B["ws"], "B", "joined")
        m = await wait_for(B["ws"], "B", "player_list")
        B["id"] = m["players"][1]["id"]
        await wait_for(A["ws"], "A", "player_list")

        # default mode = free; start
        await A["ws"].send(json.dumps({"type": "start_game"}))
        ga = await wait_for(A["ws"], "A", "game_started")
        await wait_for(B["ws"], "B", "game_started")
        snap = ga["game"]
        print(f"  snapshot: turn={snap['turn']['name']} bih={snap['ball_in_hand']} "
              f"call_shot={snap['call_shot']}")

        # break: ball-in-hand behind the line — the real client place_cue's first
        cue = ga["balls"]["cue"]
        print(f"  rack cue at ({cue['x']:.4f}, {cue['y']:.4f})")
        await A["ws"].send(json.dumps(
            {"type": "place_cue", "x": cue["x"], "y": cue["y"]}))
        await wait_for(A["ws"], "A", "cue_placed")
        await wait_for(B["ws"], "B", "cue_placed")

        # A shoots the break exactly like the web client does
        t0 = time.perf_counter()
        await A["ws"].send(json.dumps({"type": "shot", "v0": 2.5, "phi": 90.0}))
        res_a = await wait_for(A["ws"], "A", "shot_result")
        print(f"  >>> break shot_result round-trip: {(time.perf_counter() - t0) * 1000:.0f} ms")
        await wait_for(B["ws"], "B", "shot_result")

        # whose turn now? shoot again from the OTHER player (turn_over expected)
        snap = res_a["game"]
        turn_id = snap["turn"]["id"]
        who = A if turn_id == A["id"] else B
        print(f"  next turn: {snap['turn']['name']} (probe shoots as {who['label']})")
        bih = snap["ball_in_hand"]
        if bih != "none":
            balls = res_a["balls"]
            cue = balls["cue"]
            await who["ws"].send(json.dumps(
                {"type": "place_cue", "x": cue["x"], "y": cue["y"]}))
            await wait_for(who["ws"], who["label"], "cue_placed")
        await who["ws"].send(json.dumps({"type": "shot", "v0": 3.0, "phi": 45.0}))
        res2 = await wait_for(who["ws"], who["label"], "shot_result")

        print("\nPROBE OK — backend shot path works end-to-end")
        return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        print(f"\nPROBE FAILED: {type(exc).__name__}: {exc}")
        rc = 1
    sys.exit(rc)
