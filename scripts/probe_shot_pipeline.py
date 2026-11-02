"""Probe: single-player ruleset viability for Practice Mode (Issue 3).

Checks that RussianFreePyramid works with ONE player (advance/last_player/
build_shot_info must not assume 2 players), plus the exact two-shot pipeline
Issue 2 depends on.
"""

from __future__ import annotations

import os
import sys
import time
import traceback

BACKEND = "/home/z/my-project/pyramid-web/backend"
sys.path.insert(0, BACKEND)
os.environ.setdefault("PYTHONHASHSEED", "0")

from app import physics, rules


class FakePlayer:
    def __init__(self, pid, name):
        self.id = pid
        self.name = name


print("[1] two-player pipeline (Issue 2 baseline)")
players2 = [FakePlayer("aaa1", "Alice"), FakePlayer("bbb2", "Bob")]
game = rules.new_game("free", players2)
rack = physics.russian_rack()
balls_in = {bid: (p["x"], p["y"]) for bid, p in rack.items()}
t0 = time.perf_counter()
r1 = physics.run_shot_keyframes(balls_in, game=game, v0=3.0, phi=90.0)
print(f"    break OK {time.perf_counter()-t0:.2f}s rules={r1['rules']}")
snap = rules.game_snapshot("free", game, players2)
print(f"    turn after break: {snap['turn']}")
balls2 = {bid: (p["x"], p["y"]) for bid, p in r1["balls"].items()}
r2 = physics.run_shot_keyframes(balls2, game=game, v0=1.8, phi=200.0)
print(f"    shot 2 OK, pocketed={r2['pocketed']}")

print("[2] single-player ruleset (Practice Mode)")
solo = [FakePlayer("solo1", "Sam")]
try:
    g1 = rules.new_game("free", solo)
    snap = rules.game_snapshot("free", g1, solo)
    print(f"    new_game OK — turn={snap['turn']} bih={snap['ball_in_hand']}")
    rack = physics.russian_rack()
    balls_in = {bid: (p["x"], p["y"]) for bid, p in rack.items()}
    r = physics.run_shot_keyframes(balls_in, game=g1, v0=2.5, phi=75.0)
    print(f"    shot OK — pocketed={r['pocketed']} rules={r['rules']}")
    snap = rules.game_snapshot("free", g1, solo)
    print(f"    snapshot after shot: turn={snap['turn']} shot_number={snap['shot_number']}")
    balls2 = {bid: (p["x"], p["y"]) for bid, p in r["balls"].items()}
    r = physics.run_shot_keyframes(balls2, game=g1, v0=1.5, phi=150.0)
    print(f"    shot 2 OK — turn stays: {rules.game_snapshot('free', g1, solo)['turn']}")
    print("[3] SINGLE-PLAYER RULESET VIABLE — no ghost player needed")
except Exception:  # noqa: BLE001 — probe: report any failure shape
    print("    !!! single-player ruleset FAILED:")
    traceback.print_exc()
    print("[3] SINGLE-PLAYER NOT VIABLE — will need ghost-player approach")
