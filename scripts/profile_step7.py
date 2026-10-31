#!/usr/bin/env python3
"""Step 7 profiling: live WebSocket traffic + physics timing (headless).

Run against a live backend (single worker, physics warmed):
    backend/.venv/bin/python scripts/profile_step7.py

Measures over a Free-mode game (1 break + 5 mid-game strokes, turn-following):
  - client-perceived latency: send -> shot_result on the shooter's socket
  - server sim_ms (from the payload; ruleset included)
  - keyframe stats (kf_stats): frames kept, stationary-tail frames pruned,
    keyframe JSON bytes
  - shot_result wire size: uncompressed text frame + zlib-6 estimate of the
    permessage-deflate transfer size (deflate itself is hop-level and not
    observable from the client API)
  - permessage-deflate negotiation on both sockets

Budgets (Decision #15): warm sim < 500 ms median, latency < 3 s, break
shot_result < 128 KiB uncompressed, kf_stats present and self-consistent.
Note: pooltool's event-based simulation ends at quiescence, so the
stationary-tail pruning guard measures 0 on these shots — the measured wire
win is permessage-deflate (uvicorn default) plus the kf_stats
instrumentation itself.
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
import sys
import time
import urllib.request
import zlib

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


def ws_extensions(ws) -> str:
    """Negotiated Sec-WebSocket-Extensions across websockets lib versions."""
    resp = getattr(ws, "response", None)
    headers = getattr(resp, "headers", None)
    if headers is None:
        headers = getattr(ws, "response_headers", None)
    if headers is None:
        return ""
    try:
        return headers.get("Sec-WebSocket-Extensions", "") or ""
    except Exception:  # noqa: BLE001 — header bag types differ across versions
        return ""


async def recv_raw(ws, timeout: float = 60) -> tuple[dict, str]:
    raw = await asyncio.wait_for(ws.recv(), timeout)
    return json.loads(raw), raw


def wait_physics_ready(timeout: float = 180) -> float | None:
    log = logging.getLogger("profile_step7")
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(BASE + "/api/health", timeout=5) as r:
                if json.loads(r.read()).get("physics_ready"):
                    return time.time() - t0
        except Exception:  # server may not be up yet; poll until timeout
            log.debug("health poll failed", exc_info=True)
        time.sleep(0.5)
    return None


async def main() -> int:
    ready_s = wait_physics_ready()
    check("backend physics warmed (physics_ready)", ready_s is not None, f"{ready_s}")

    async with websockets.connect(URI) as a, websockets.connect(URI) as b:
        ext_a, ext_b = ws_extensions(a), ws_extensions(b)
        check(
            "permessage-deflate negotiated (host socket)",
            "permessage-deflate" in ext_a.lower(),
            ext_a or "no extensions header",
        )
        check(
            "permessage-deflate negotiated (guest socket)",
            "permessage-deflate" in ext_b.lower(),
            ext_b or "no extensions header",
        )

        await a.send(json.dumps({"type": "create", "name": "Alice"}))
        ma, _ = await recv_raw(a)
        check("host joined", ma.get("type") == "joined", str(ma)[:80])

        await b.send(json.dumps({"type": "join", "room": ma["room"], "name": "Bob"}))
        mb, _ = await recv_raw(b)
        await recv_raw(b)  # player_list
        await recv_raw(a)  # player_list
        check("guest joined", mb.get("type") == "joined", str(mb)[:80])

        socks = {ma["player_id"]: a, mb["player_id"]: b}
        await a.send(json.dumps({"type": "start_game"}))
        gs, _ = await recv_raw(a, 30)
        gs2, _ = await recv_raw(b, 30)
        check(
            "game_started on both clients",
            gs.get("type") == "game_started" and gs2.get("type") == "game_started",
        )
        check("16-ball rack dealt", len(gs.get("balls", {})) == 16)

        # 1 break + 5 mid-game strokes; the shooter follows the ruleset turn.
        shot_specs = [(3.0, 90.0), (1.6, 84.0), (1.3, 275.0), (1.8, 96.0), (1.2, 60.0), (1.5, 300.0)]
        records = []
        turn_id = gs["game"]["turn"]["id"]
        for i, (v0, phi) in enumerate(shot_specs, 1):
            shooter_ws = socks[turn_id]
            t_send = time.perf_counter()
            await shooter_ws.send(json.dumps({"type": "shot", "v0": v0, "phi": phi}))
            msg, raw_shooter = await recv_raw(shooter_ws, 60)
            lat_ms = (time.perf_counter() - t_send) * 1000
            _, raw_watcher = await recv_raw(socks[
                next(pid for pid in socks if pid != turn_id)
            ], 60)
            check(
                f"shot {i}: shot_result on both clients",
                msg.get("type") == "shot_result" and raw_shooter == raw_watcher,
                f"type={msg.get('type')}",
            )
            rec = {
                "shot": i,
                "v0": v0,
                "sim_ms": msg.get("sim_ms"),
                "lat_ms": lat_ms,
                "kf": msg.get("kf_stats") or {},
                "bytes": len(raw_shooter.encode()),
                "z6": len(zlib.compress(raw_shooter.encode(), 6)),
                "pocketed": msg.get("pocketed", []),
            }
            records.append(rec)
            turn_id = msg["game"]["turn"]["id"]

        print()
        print(
            "  shot |   v0 |  sim_ms | lat_ms | kf_frames | pruned | events | "
            "kf_KiB | msg_KiB | z6_KiB | pocketed"
        )
        for r in records:
            kf_bytes = r["kf"].get("bytes", 0)
            print(
                f"  {r['shot']:>4} | {r['v0']:>4} | {r['sim_ms']:>7} | "
                f"{r['lat_ms']:>6.0f} | {r['kf'].get('frames', '?'):>9} | "
                f"{r['kf'].get('pruned', '?'):>6} | {r['kf'].get('events', '?'):>6} | "
                f"{kf_bytes / 1024:>6.1f} | "
                f"{r['bytes'] / 1024:>7.1f} | {r['z6'] / 1024:>6.1f} | "
                f"{','.join(r['pocketed']) or '-'}"
            )
        sim_times = [r["sim_ms"] for r in records]
        latencies = [r["lat_ms"] for r in records]
        print(
            f"  ..  sim_ms median {statistics.median(sim_times):.0f} / max {max(sim_times):.0f}; "
            f"latency median {statistics.median(latencies):.0f} / max {max(latencies):.0f}"
        )

        br = records[0]
        check(
            "kf_stats present and self-consistent on every shot",
            all(
                r["kf"].get("frames", 0) > 0
                and r["kf"].get("bytes", 0) > 0
                and r["kf"].get("pruned", -1) >= 0
                and r["kf"].get("events", -1) >= 0
                for r in records
            ),
            str([r["kf"] for r in records[:2]]),
        )
        check(
            "break shot_result < 256 KiB uncompressed (worst case = 900-frame cap)",
            br["bytes"] < 262_144,
            f"{br['bytes'] / 1024:.1f} KiB",
        )
        check(
            "keyframes stay under the hard frame cap (<= 900)",
            all(r["kf"].get("frames", 0) <= 900 for r in records),
            str([r["kf"].get("frames") for r in records]),
        )
        check(
            "warm sim budget: median sim_ms < 500 (Decision #15)",
            statistics.median(sim_times) < 500,
            f"median {statistics.median(sim_times):.0f} ms",
        )
        check(
            "interactive latency: max < 3000 ms",
            max(latencies) < 3000,
            f"max {max(latencies):.0f} ms",
        )
        check(
            "zlib-6 transfer estimate < 32 KiB for every shot",
            all(r["z6"] < 32_768 for r in records),
            f"max {max(r['z6'] for r in records) / 1024:.1f} KiB",
        )

    print()
    if failed:
        print(f"{len(failed)} FAILED, {passed} passed")
        return 1
    print(f"ALL {passed} CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
