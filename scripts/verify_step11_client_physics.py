"""Step 11 acceptance battery — client-side JS physics protocol (terminal
state sync) against a REAL uvicorn server over real WebSockets.

Run (single bash invocation — the server is a child of THIS process):
    cd pyramid-web/backend && /home/z/.venv/bin/python3 ../../scripts/verify_step11_client_physics.py

Architecture under test: the client simulates the stroke locally and sends
ONE ``shot`` message when the balls stop (final positions + pocketed +
first-contact + cushion events). The server judges it with the vendored
rulesets (no pooltool physics on the gameplay path) and broadcasts
``shot_result`` WITHOUT keyframes.

Batteries:
  B1 legal pot (break): report pots one object ball -> shot_result on BOTH
     clients, legal=True, score +1, shooter continues, potted ball gone from
     the authoritative state, NO keyframes/sim fields on the wire.
  B2 foul (no contact): static report -> ILLEGAL_COMPLETION foul, opponent
     +1, «штрафной шар» removed, turn passes.
  B3 out-of-turn report rejected with a structured error.
  B4 malformed reports rejected (ball off table / unknown id / unaccounted
     ball) — room state untouched afterwards.
  B5 scratch without object contact: cue-only pot -> foul, cue respotted in
     the house, ball_in_hand=behind_line for the incoming player.
  B6 practice: pot -> gone; scratch -> deterministic respot + ball-in-hand
     anywhere; place_cue accepted; re-rack.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, "/home/z/my-project/pyramid-web/backend")
os.environ.setdefault("PYTHONHASHSEED", "0")

import websockets

URI = "ws://127.0.0.1:8101/ws"
PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))


async def recv_until(ws, want_type: str, timeout: float = 30.0):
    """Collect messages until one of `want_type` arrives (others returned)."""
    deadline = time.monotonic() + timeout
    seen = []
    while time.monotonic() < deadline:
        left = deadline - time.monotonic()
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=left)
        except (TimeoutError, asyncio.TimeoutError):
            break
        msg = json.loads(raw)
        if msg.get("type") == want_type:
            return msg, seen
        seen.append(msg)
    seen_types = [m.get("type") for m in seen]
    raise TimeoutError(f"no {want_type!r} within {timeout}s; saw: {seen_types}")


def find(seen: list[dict], want: str):
    for m in seen:
        if m.get("type") == want:
            return m
    return None


POCKET_POINTS = {
    "lb": (0.0, 0.0),
    "rb": (1.8, 0.0),
    "lc": (0.0, 1.85),
    "rc": (1.8, 1.85),
    "lt": (0.0, 3.7),
    "rt": (1.8, 3.7),
}


def nearest_pocket(pos: dict) -> str:
    return min(
        POCKET_POINTS,
        key=lambda pid: (pos["x"] - POCKET_POINTS[pid][0]) ** 2
        + (pos["y"] - POCKET_POINTS[pid][1]) ** 2,
    )


def make_report(
    pre: dict,
    *,
    final: dict | None = None,
    pocketed: list | None = None,
    first_contact: dict | None = None,
    cushions: dict | None = None,
    y_range: dict | None = None,
    duration: float = 2.5,
    v0: float = 3.2,
    phi: float = 90.0,
) -> dict:
    return {
        "type": "shot",
        "v0": v0,
        "phi": phi,
        "duration": duration,
        "final": final if final is not None else {k: dict(v) for k, v in pre.items()},
        "pocketed": pocketed or [],
        "first_contact": first_contact,
        "cushions": cushions or {},
        "y_range": y_range or {},
    }


def without(pre: dict, *ids: str) -> dict:
    return {k: dict(v) for k, v in pre.items() if k not in ids}


async def b1_legal_pot_break() -> None:
    print("B1: legal pot on the break (terminal-state report)")
    a, b = await websockets.connect(URI), await websockets.connect(URI)
    await a.send(json.dumps({"type": "create", "name": "Alice"}))
    joined, _ = await recv_until(a, "joined", 10)
    code = joined["room"]
    await b.send(json.dumps({"type": "join", "room": code, "name": "Bob"}))
    await recv_until(b, "joined", 10)
    await a.send(json.dumps({"type": "start_game"}))
    gs, _ = await recv_until(a, "game_started", 30)
    await recv_until(b, "game_started", 10)
    pre = gs["balls"]
    check("game_started carries the rack", len(pre) == 16, f"{len(pre)} balls")

    # pot the object ball nearest to any pocket (a legal break because a
    # ball is potted, «Общие правила» п. 12 clause 1)
    victim = min(
        (i for i in pre if i != "cue"),
        key=lambda i: min(
            (pre[i]["x"] - px) ** 2 + (pre[i]["y"] - py) ** 2
            for px, py in POCKET_POINTS.values()
        ),
    )
    pocket = nearest_pocket(pre[victim])
    report = make_report(
        pre,
        final=without(pre, victim),
        pocketed=[{"ball": victim, "pocket": pocket, "t": 1.2}],
        first_contact={"ball": victim, "t": 0.35},
        cushions={victim: ["18"]},
        y_range={victim: {"min": pre[victim]["y"], "max": pre[victim]["y"] + 0.3}},
    )
    await a.send(json.dumps(report))
    res, seen = await recv_until(a, "shot_result", 30)
    res_b, _ = await recv_until(b, "shot_result", 10)
    check("shot_result on both clients", bool(res) and bool(res_b))
    check(
        "protocol hygiene: no keyframes/sim fields",
        not any(k in res for k in ("keyframes", "kf_stats", "sim_ms")),
        str([k for k in res if k in ("keyframes", "kf_stats", "sim_ms")]),
    )
    check("judge_ms present (rules timing)", isinstance(res.get("judge_ms"), (int, float)))
    check("game snapshot rides the verdict", isinstance(res.get("game"), dict))
    check("legal pot judged legal", res["legal"] is True, res["reason"])
    check("shooter scored 1", any(s["score"] == 1 for s in res["game"]["scores"]))
    check("shooter continues (turn not over)", res["game"]["turn"]["id"] == joined["player_id"])
    check("potted ball left the table", victim not in res["balls"])
    check("cue still on the table", "cue" in res["balls"])
    # B1 keeps the sockets open for B2/B3 via a global list
    B1_STATE["a"], B1_STATE["b"], B1_STATE["pre"], B1_STATE["joined"] = (
        a, b, res["balls"], joined,
    )


B1_STATE: dict = {}


async def b2_foul_no_contact() -> None:
    print("B2: no-contact stroke is a foul («штрафной шар», turn passes)")
    a, b, pre, joined = B1_STATE["a"], B1_STATE["b"], B1_STATE["pre"], B1_STATE["joined"]
    report = make_report(pre)  # nothing happens at all
    await a.send(json.dumps(report))
    res, _ = await recv_until(a, "shot_result", 30)
    check("foul judged", res["legal"] is False, res["reason"])
    reason = res["reason"].lower()
    check(
        "reason is a rules foul",
        "illegal_completion" in reason or "no_contact" in reason,
        res["reason"],
    )
    check("opponent awarded the foul point", res["removed"], f"removed={res['removed']}")
    check("turn passed to Bob", res["game"]["turn"]["id"] != joined["player_id"])
    B1_STATE["pre"] = res["balls"]


async def b3_out_of_turn() -> None:
    print("B3: out-of-turn report is rejected")
    a = B1_STATE["a"]
    report = make_report(B1_STATE["pre"])
    await a.send(json.dumps(report))
    err, _ = await recv_until(a, "error", 10)
    check("structured error", err.get("code") == "not_your_turn", err.get("code"))


async def b4_malformed_reports() -> None:
    print("B4: malformed reports are rejected, state untouched")
    b = B1_STATE["b"]
    pre = B1_STATE["pre"]
    live_ids = set(pre)

    # ball off the table
    bad = make_report(pre)
    bad["final"]["cue"] = {"x": 9.9, "y": 9.9}
    await b.send(json.dumps(bad))
    err, _ = await recv_until(b, "error", 10)
    check("off-table position rejected", err.get("code") == "invalid_shot", str(err.get("message"))[:80])

    # unknown ball id
    bad = make_report(pre)
    bad["final"]["42"] = {"x": 0.9, "y": 1.0}
    await b.send(json.dumps(bad))
    err, _ = await recv_until(b, "error", 10)
    check("unknown ball id rejected", err.get("code") == "invalid_shot", "")

    # unaccounted ball (dropped from final without a pocket entry)
    bad = make_report(pre)
    bad["final"] = without(pre, "cue")
    await b.send(json.dumps(bad))
    err, _ = await recv_until(b, "error", 10)
    check("unaccounted ball rejected", err.get("code") == "invalid_shot", "")

    # object ball pocketed without first contact
    victim = next(i for i in pre if i != "cue")
    bad = make_report(
        pre,
        final=without(pre, victim),
        pocketed=[{"ball": victim, "pocket": "lb", "t": 1.0}],
        first_contact=None,
    )
    await b.send(json.dumps(bad))
    err, _ = await recv_until(b, "error", 10)
    check("pot without contact rejected", err.get("code") == "invalid_shot", "")

    # the room state survived all four rejections (no crash, no broadcasts)
    try:
        await recv_until(b, "player_list", 2)
        check("no broadcast storm after rejections", False, "unexpected player_list")
    except (TimeoutError, asyncio.TimeoutError):
        check("no broadcast storm after rejections", True)


async def b5_scratch_no_contact() -> None:
    print("B5: scratch without object contact -> house respot + ball in hand")
    b, pre = B1_STATE["b"], B1_STATE["pre"]
    report = make_report(
        pre,
        final=without(pre, "cue"),
        pocketed=[{"ball": "cue", "pocket": "lc", "t": 1.8}],
        first_contact=None,
    )
    await b.send(json.dumps(report))
    res, _ = await recv_until(b, "shot_result", 30)
    check("scratch judged foul", res["legal"] is False, res["reason"])
    check("cue respotted on the table", "cue" in res["balls"])
    cue = res["balls"]["cue"]
    check("cue in the house (y <= 0.25 L)", cue["y"] <= 0.25 * 3.7 + 1e-9, f"y={cue['y']:.3f}")
    check("ball_in_hand behind_line", res["game"]["ball_in_hand"] == "behind_line")
    check("turn passed back to Alice", res["game"]["turn"]["id"] == B1_STATE["joined"]["player_id"])
    B1_STATE["pre"] = res["balls"]


async def b6_practice() -> None:
    print("B6: practice mode (pot / scratch respot / place_cue / re-rack)")
    c = await websockets.connect(URI)
    await c.send(json.dumps({"type": "create", "name": "Solo"}))
    joined, _ = await recv_until(c, "joined", 10)
    await c.send(json.dumps({"type": "practice"}))
    gs, _ = await recv_until(c, "game_started", 10)
    check("practice started", gs.get("practice") is True and gs["mode"] == "practice")
    pre = gs["balls"]

    victim = min(
        (i for i in pre if i != "cue"),
        key=lambda i: min(
            (pre[i]["x"] - px) ** 2 + (pre[i]["y"] - py) ** 2
            for px, py in POCKET_POINTS.values()
        ),
    )
    report = make_report(
        pre,
        final=without(pre, victim),
        pocketed=[{"ball": victim, "pocket": nearest_pocket(pre[victim]), "t": 0.9}],
        first_contact={"ball": victim, "t": 0.2},
    )
    await c.send(json.dumps(report))
    res, _ = await recv_until(c, "shot_result", 30)
    check("practice pot removed the ball", victim not in res["balls"] and res["legal"] is True)

    # scratch (cue-only pot, no contact) -> deterministic respot + bih
    pre2 = res["balls"]
    report = make_report(
        pre2,
        final=without(pre2, "cue"),
        pocketed=[{"ball": "cue", "pocket": "rc", "t": 1.1}],
        first_contact=None,
    )
    await c.send(json.dumps(report))
    res, _ = await recv_until(c, "shot_result", 30)
    check("practice scratch respots the cue", "cue" in res["balls"])
    check("scratch reason", "scratch" in res["reason"], res["reason"])
    check("ball-in-hand anywhere", res["game"]["ball_in_hand"] == "anywhere")

    await c.send(json.dumps({"type": "place_cue", "x": 0.5, "y": 1.2}))
    placed, _ = await recv_until(c, "cue_placed", 10)
    check("place_cue accepted mid-game", placed["x"] == 0.5 and placed["y"] == 1.2)

    await c.send(json.dumps({"type": "practice"}))
    gs, _ = await recv_until(c, "game_started", 10)
    check("re-rack deals a fresh rack", len(gs["balls"]) == 16)
    await c.close()


async def main() -> None:
    try:
        await b1_legal_pot_break()
        await b2_foul_no_contact()
        await b3_out_of_turn()
        await b4_malformed_reports()
        await b5_scratch_no_contact()
    finally:
        for key in ("a", "b"):
            ws = B1_STATE.get(key)
            if ws is not None:
                await ws.close()
    await b6_practice()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  - ")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
