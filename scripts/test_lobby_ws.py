#!/usr/bin/env python3
"""Step 2 acceptance test: lobby WebSocket protocol against the live backend.

Covers: create/join handshake, player-list broadcasts, host-only start_game,
error codes (non-fatal — socket stays usable), mid-game leave -> game_aborted
-> room back to lobby, host promotion, room deletion when empty, REST
introspection endpoints.

Run (backend listening on 127.0.0.1:8100):
    backend/.venv/bin/python scripts/test_lobby_ws.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import urllib.error
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


async def recv(ws, want: str | None = None, timeout: float = 5) -> dict:
    raw = await asyncio.wait_for(ws.recv(), timeout)
    msg = json.loads(raw)
    assert isinstance(msg, dict), f"expected dict, got {msg!r}"
    if want is not None:
        assert msg.get("type") == want, f"expected {want}, got {msg}"
    return msg


def rest(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=5) as resp:
        return json.loads(resp.read())


async def main() -> int:
    async with websockets.connect(URI) as a:
        # 1. invalid first message -> error, connection stays open
        await a.send(json.dumps({"type": "ping"}))
        m = await recv(a)
        check(
            "invalid first message -> error invalid_message",
            m.get("type") == "error" and m.get("code") == "invalid_message",
            str(m),
        )

        # 2. create room
        await a.send(json.dumps({"type": "create", "name": "Alice"}))
        m = await recv(a, "joined")
        code = m["room"]
        pid_a = m["player_id"]
        check(
            "create -> joined (host, 1 player)",
            m["is_host"] is True
            and len(m["players"]) == 1
            and m["players"][0]["name"] == "Alice",
            str(m),
        )
        check(
            "room code is 4 uppercase letters",
            len(code) == 4 and code.isalpha() and code.isupper(),
            code,
        )

        async with websockets.connect(URI) as b:
            # 3. join (lowercase code) + broadcasts
            await b.send(
                json.dumps({"type": "join", "room": code.lower(), "name": "Bob"})
            )
            m = await recv(b, "joined")
            check(
                "join (lowercase code) -> joined (not host, 2 players)",
                m["is_host"] is False and len(m["players"]) == 2,
                str(m),
            )
            m = await recv(b, "player_list")
            check(
                "joiner also receives player_list broadcast",
                len(m["players"]) == 2,
                str(m),
            )
            m = await recv(a, "player_list")
            check(
                "host receives player_list broadcast [Alice, Bob]",
                [p["name"] for p in m["players"]] == ["Alice", "Bob"],
                str(m),
            )

            # 4. REST introspection
            info = rest(f"/api/rooms/{code}")
            check(
                "REST room info: code/state/players",
                info["code"] == code
                and info["state"] == "lobby"
                and len(info["players"]) == 2,
                str(info),
            )
            listing = rest("/api/rooms")
            check(
                "REST room list contains the room",
                any(r["code"] == code for r in listing["rooms"]),
            )

            # 5. non-host cannot start
            await b.send(json.dumps({"type": "start_game"}))
            m = await recv(b)
            check(
                "non-host start -> error not_host",
                m.get("type") == "error" and m.get("code") == "not_host",
                str(m),
            )
            try:
                await asyncio.wait_for(a.recv(), 0.3)
                check("host got NO game_started from rogue start", False)
            except TimeoutError:
                check("host got NO game_started from rogue start", True)

            # 6. room full (third connection)
            async with websockets.connect(URI) as c:
                await c.send(
                    json.dumps({"type": "join", "room": code, "name": "Carol"})
                )
                m = await recv(c)
                check(
                    "third join -> error room_full",
                    m.get("type") == "error" and m.get("code") == "room_full",
                    str(m),
                )
                # errors are non-fatal: same socket may create its own room
                await c.send(json.dumps({"type": "create", "name": "Carol"}))
                m = await recv(c, "joined")
                check(
                    "after error, same socket can create a room",
                    len(m["players"]) == 1,
                    str(m),
                )
            await asyncio.sleep(0.3)  # let the server clean up Carol's room

            # 7. host starts the game
            await a.send(json.dumps({"type": "start_game"}))
            m = await recv(a, "game_started")
            check(
                "host receives game_started (mode free)",
                m["mode"] == "free" and len(m["players"]) == 2,
                str(m),
            )
            m = await recv(b, "game_started")
            check("joiner receives game_started", m["type"] == "game_started", str(m))

            # 8. double start
            await a.send(json.dumps({"type": "start_game"}))
            m = await recv(a)
            check(
                "second start -> error game_in_progress",
                m.get("type") == "error" and m.get("code") == "game_in_progress",
                str(m),
            )

            # 9. join while playing
            async with websockets.connect(URI) as d:
                await d.send(json.dumps({"type": "join", "room": code, "name": "Dave"}))
                m = await recv(d)
                check(
                    "join during game -> error game_in_progress",
                    m.get("type") == "error" and m.get("code") == "game_in_progress",
                    str(m),
                )

            # 10. joiner leaves mid-game -> game_aborted + room back to lobby
            await b.close()
            m = await recv(a, "game_aborted")
            check(
                "mid-game leave -> game_aborted",
                m.get("reason") == "player_left",
                str(m),
            )
            m = await recv(a, "player_list")
            check(
                "host sees 1 player after leave, still host",
                len(m["players"]) == 1
                and m["players"][0]["is_host"]
                and m["players"][0]["id"] == pid_a,
                str(m),
            )
            await asyncio.sleep(0.2)
            info = rest(f"/api/rooms/{code}")
            check(
                "room returns to lobby state after mid-game leave",
                info["state"] == "lobby" and len(info["players"]) == 1,
                str(info),
            )

        # 11. host leaves -> room deleted (404)
        await a.close()
        await asyncio.sleep(0.3)
        try:
            rest(f"/api/rooms/{code}")
            check("empty room is deleted (HTTP 404)", False)
        except urllib.error.HTTPError as exc:
            check("empty room is deleted (HTTP 404)", exc.code == 404)

    # 12. join a nonexistent room
    async with websockets.connect(URI) as eve:
        await eve.send(json.dumps({"type": "join", "room": "ZZZZ", "name": "Eve"}))
        m = await recv(eve)
        check(
            "join nonexistent room -> error room_not_found",
            m.get("type") == "error" and m.get("code") == "room_not_found",
            str(m),
        )

    # 13. name validation
    async with websockets.connect(URI) as frank:
        await frank.send(json.dumps({"type": "create", "name": "   "}))
        m = await recv(frank)
        check(
            "whitespace-only name -> error invalid_name",
            m.get("type") == "error" and m.get("code") == "invalid_name",
            str(m),
        )
        await frank.send(json.dumps({"type": "create", "name": "X" * 40}))
        m = await recv(frank, "joined")
        check(
            "over-long name truncated to 24 chars",
            m["players"][0]["name"] == "X" * 24,
            str(m),
        )

    print()
    if failed:
        print(f"{len(failed)} FAILED, {passed} passed")
        return 1
    print(f"ALL {passed} CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
