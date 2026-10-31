#!/usr/bin/env python3
"""Step 6 acceptance test (headless, in-process): the vendored rulesets
driven end-to-end through ``app.physics.run_shot_keyframes(game=...)`` and
``app.rules`` snapshots.

Run:
    cd backend && PYTHONHASHSEED=0 .venv/bin/python ../../scripts/verify_step6_rules.py

Covers, per discipline:
  free     legal break pot (score, turn continues) · NO_CONTACT foul (penalty
           ball removed, turn passes) · foul scratch (cue -> house +
           behind_line grant) · race-to-target game over + winner
  combined house-stroke violation (п. 21) and its legal counterpart
  dynamic  scratch -> ball_in_hand ANYWHERE · in-hand cue pot -> foul
  classic  called shot honored (score) · not honored (respot, no score) ·
           cue potted (foul, ±5 points, no penalty ball)
plus: mode registry, pocket ids, snapshot invariants, cue-placement
validation.

The ball states are handcrafted for determinism (this is a rules unit test;
room-flow integration is covered by verify_step6_ws.py / verify_step6.sh).
The Free game-over scenario temporarily patches the module-level
FREE_TARGET_SCORE (a test seam — no vendored file is modified).
"""

from __future__ import annotations

import math
import sys
from types import SimpleNamespace

sys.path.insert(0, "/home/z/my-project/pyramid-web/backend")

from app import physics, rules  # noqa: E402
import pooltool.ruleset.russian_pyramid as rp  # noqa: E402

P1 = SimpleNamespace(id="p1", name="Alice")
P2 = SimpleNamespace(id="p2", name="Bob")
PLAYERS = [P1, P2]

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


def new_game(mode: str):
    return rules.new_game(mode, PLAYERS)


def shoot(game, balls: dict, **params) -> dict:
    """One stroke through the rules-aware pipeline; returns the result.

    ``balls`` accepts both ``(x, y)`` tuples and the wire ``{"x": .., "y": ..}``
    format (the latter is what ``result["balls"]`` returns).
    """
    norm = {}
    for bid, pos in balls.items():
        norm[bid] = (pos["x"], pos["y"]) if isinstance(pos, dict) else (pos[0], pos[1])
    return physics.run_shot_keyframes(norm, game=game, **params)


def snap(mode: str, game) -> dict:
    return rules.game_snapshot(mode, game, PLAYERS)


def score_of(result: dict, pid: str) -> int:
    return result["rules"]["score"].get(pid, 0)


# --- A. registry -----------------------------------------------------------------

print("== A. mode registry ==")
check("4 modes registered", sorted(rules.MODES) == ["classic", "combined", "dynamic", "free"])
check(
    "race targets 8/8/8/71",
    [rules.MODES[m]["target"] for m in ("free", "combined", "dynamic", "classic")]
    == [8, 8, 8, 71],
)
check(
    "pocket ids from the physics spec",
    sorted(rules.POCKET_IDS) == ["lb", "lc", "lt", "rb", "rc", "rt"],
)
check("house line at 0.25 L", abs(rules.HOUSE_Y - 0.25 * physics.TABLE_L) < 1e-9)

# initial snapshot of a fresh game
g = new_game("free")
s = snap("free", g)
check(
    "initial snapshot: host breaks, behind_line, no call, 0-0",
    s["turn"]["id"] == "p1"
    and s["ball_in_hand"] == "behind_line"
    and s["call_shot"] is False
    and s["scores"] == [
        {"id": "p1", "name": "Alice", "score": 0},
        {"id": "p2", "name": "Bob", "score": 0},
    ]
    and s["game_over"] is False
    and s["last_shot"] is None,
    str(s),
)
check(
    "initial hittable = all 15 object balls",
    s["hittable"] == [str(i) for i in range(1, 16)],
)

# --- B. Free Pyramid --------------------------------------------------------------

print("== B. free pyramid ==")
g = new_game("free")
balls = {"cue": (0.30, 0.30), "1": (0.15, 0.15), "8": (0.12, 0.35), "9": (0.9, 2.0)}
r = shoot(g, balls, v0=1.5, phi=225.0, b=0.0)
check(
    "B1 legal break pot: legal, '1' pocketed, 1-0, turn stays",
    r["rules"]["legal"]
    and r["pocketed"] == ["1"]
    and score_of(r, "p1") == 1
    and score_of(r, "p2") == 0
    and r["rules"]["turn_over"] is False
    and r["rules"]["reason"] == "legal_break",
    str(r["rules"]),
)
check("B1 respotted/removed empty", r["respotted"] == [] and r["removed"] == [])
balls = r["balls"]
s = snap("free", g)
check(
    "B1 snapshot: turn p1, no BIH, hittable = live balls",
    s["turn"]["id"] == "p1"
    and s["ball_in_hand"] == "none"
    and s["hittable"] == ["8", "9"],
    str(s["turn"]) + str(s["hittable"]),
)

# B2: NO_CONTACT foul -> opponent point, penalty ball removed, turn passes
r = shoot(g, balls, v0=0.5, phi=20.0)
check(
    "B2 no-contact foul: reason, 1-1, turn over",
    not r["rules"]["legal"]
    and r["rules"]["reason"] == "no_contact"
    and score_of(r, "p1") == 1
    and score_of(r, "p2") == 1
    and r["rules"]["turn_over"] is True,
    str(r["rules"]),
)
check(
    "B2 penalty ball removed = ball closest to a pocket ('8')",
    r["removed"] == ["8"],
    str(r["removed"]),
)
balls = r["balls"]
s = snap("free", g)
check("B2 snapshot: turn passed to p2", s["turn"]["id"] == "p2", str(s["turn"]))
check("B2 '9' still on the table", "9" in balls and "8" not in balls)

# B3: foul scratch -> cue respotted in the house + behind_line for p1
# (cue position constructed for determinism: aimed straight down the lb
# pocket diagonal with no object ball on the path)
balls = dict(r["balls"])
balls["cue"] = (0.30, 0.30)
r = shoot(g, balls, v0=1.5, phi=225.0, b=0.0)
check(
    "B3 scratch: no_contact foul, cue respotted (in balls), turn over",
    not r["rules"]["legal"]
    and r["rules"]["reason"] == "no_contact"
    and r["respotted"] == ["cue"]
    and "cue" in r["balls"]
    and r["rules"]["turn_over"] is True,
    str(r["rules"]) + str(r["respotted"]),
)
cue = r["balls"]["cue"]
check(
    "B3 cue placed at the default house position (0.9, 0.851)",
    abs(cue["x"] - 0.9) < 1e-6 and abs(cue["y"] - 0.851) < 1e-6,
    str(cue),
)
check(
    "B3 last live object ball removed as the penalty ball",
    r["removed"] == ["9"],
    str(r["removed"]),
)
s = snap("free", g)
check(
    "B3 snapshot: p1 to shoot with ball_in_hand behind_line",
    s["turn"]["id"] == "p1" and s["ball_in_hand"] == "behind_line",
    str(s["turn"]) + s["ball_in_hand"],
)

# --- C. Free game over (target patched to 2 — test seam only) ---------------------

print("== C. free game over ==")
old_target = rp.FREE_TARGET_SCORE
rp.FREE_TARGET_SCORE = 2
try:
    g = new_game("free")
    balls = {"cue": (0.30, 0.30), "1": (0.15, 0.15), "2": (1.20, 1.85)}
    r = shoot(g, balls, v0=1.5, phi=225.0, b=0.0)
    check("C1 first pot: 1-0, not over", score_of(r, "p1") == 1 and not r["rules"]["game_over"])
    balls = dict(r["balls"])
    # cue position constructed: straight at the rc middle pocket through '2'
    balls["cue"] = (1.10, 1.85)
    r = shoot(g, balls, v0=1.5, phi=0.0, b=0.0)
    check(
        "C2 second pot ends the game: game_over, winner p1, 2-0",
        r["rules"]["game_over"]
        and r["rules"]["winner"] == "p1"
        and score_of(r, "p1") == 2,
        str(r["rules"]),
    )
    s = snap("free", g)
    check(
        "C2 snapshot: winner mapped to Alice",
        s["game_over"] and s["winner"] == {"id": "p1", "name": "Alice"},
        str(s["winner"]),
    )
finally:
    rp.FREE_TARGET_SCORE = old_target

# --- D. Combined Pyramid: п. 21 house strokes --------------------------------------

print("== D. combined pyramid (house strokes) ==")
g = new_game("combined")
# D1: scratch on the break (cue straight into the rb pocket diagonal, no
# object ball on the path) -> NO_CONTACT foul + cue to the house.
balls = {
    "cue": (1.50, 0.30),
    "1": (0.10, 0.10),
    "2": (0.9, 2.775),
    "3": (0.45, 0.70),
}
r = shoot(g, balls, v0=1.5, phi=315.0, b=0.0)
check(
    "D1 scratch break: foul, cue -> house, behind_line",
    not r["rules"]["legal"]
    and r["rules"]["reason"] == "no_contact"
    and r["respotted"] == ["cue"]
    and abs(r["balls"]["cue"]["y"] - 0.851) < 1e-6,
    str(r["rules"]) + str(r["balls"].get("cue")),
)
s = snap("combined", g)
check("D1 turn passes to p2 behind the line", s["turn"]["id"] == "p2" and s["ball_in_hand"] == "behind_line")
check("D1 penalty ball removed ('1', closest to a pocket)", r["removed"] == ["1"], str(r["removed"]))

balls = r["balls"]
# D2 (non-break, from the house): first contact INSIDE the house -> п. 21 foul.
# '3' stands in the house at (0.45, 0.70); the cue at the default house spot.
cue0 = balls["cue"]
phi = math.degrees(math.atan2(0.70 - cue0["y"], 0.45 - cue0["x"]))
r = shoot(g, balls, v0=1.2, phi=phi, b=0.0)
check(
    "D2 house stroke first contacts a ball in the house: house_first_contact",
    not r["rules"]["legal"] and r["rules"]["reason"] == "house_first_contact",
    str(r["rules"]),
)
balls = r["balls"]
s = snap("combined", g)
check("D2 turn passes to p1", s["turn"]["id"] == "p1")

# D3: house stroke whose first contact is OUTSIDE the house -> legal.
# The cue stopped at the D2 contact point (inside the house); '2' stands
# outside the house at (0.9, 2.775).
cue1 = balls["cue"]
phi = math.degrees(math.atan2(2.775 - cue1["y"], 0.9 - cue1["x"]))
r = shoot(g, balls, v0=2.0, phi=phi, b=0.0)
check(
    "D3 house stroke first contacts outside the house: legal",
    r["rules"]["legal"] and r["rules"]["reason"] == "legal",
    str(r["rules"]),
)

# --- E. Dynamic Pyramid: ball in hand anywhere + in-hand cue pot -------------------

print("== E. dynamic pyramid (ball in hand) ==")
g = new_game("dynamic")
# no ball on the cue->lb diagonal (the scratch must contact nothing); '1'
# stands closest to a pocket so IT is the E1 penalty ball, keeping '2' live
# for the E2 assertion.
balls = {"cue": (0.30, 0.30), "1": (0.10, 0.35), "2": (1.60, 1.00), "5": (0.5, 1.8)}
r = shoot(g, balls, v0=1.5, phi=225.0, b=0.0)  # scratch on the break
s = snap("dynamic", g)
check(
    "E1 scratch -> ball_in_hand ANYWHERE for the incoming player",
    s["turn"]["id"] == "p2" and s["ball_in_hand"] == "anywhere",
    s["ball_in_hand"],
)
check("E1 cue re-placed in the house by default", abs(r["balls"]["cue"]["y"] - 0.851) < 1e-6)
check("E1 penalty ball removed ('1')", r["removed"] == ["1"], str(r["removed"]))

# shot 2, played with cue in hand (constraints carry ANYWHERE): potting the cue
# after contacting an object ball is a foul (п. 6.4/6.5). Constructed state:
# cue and '5' on the lb pocket diagonal.
balls = dict(r["balls"])
balls["cue"] = (0.30, 0.30)
balls["5"] = (0.15, 0.15)
r = shoot(g, balls, v0=1.6, phi=225.0, b=0.9)
check(
    "E2 in-hand cue pot: foul in_hand_cue_pot",
    not r["rules"]["legal"] and r["rules"]["reason"] == "in_hand_cue_pot",
    str(r["rules"]),
)
check(
    "E2 cue and the pocketed '5' both respotted (foul pots come back)",
    r["respotted"] == ["5", "cue"] and "5" in r["balls"],
    str(r["respotted"]),
)
check(
    "E2 penalty ball removed ('2', closest to a pocket)",
    r["removed"] == ["2"],
    str(r["removed"]),
)
s = snap("dynamic", g)
check("E2 BIH anywhere persists for the incoming player", s["ball_in_hand"] == "anywhere")

# --- F. Classic Pyramid: called shots ----------------------------------------------

print("== F. classic pyramid (calls) ==")


def quiet_break(game):
    """A legal break that pots nothing (contact + cushion + line crossing).

    Cue (0.9, 0.851) -> '1' (0.9, 1.0) straight down the length: after the
    contact '1' runs to the foot cushion and crosses the central line.
    Returns the post-break on-table balls.
    """
    balls = {"cue": (0.9, 0.851), "1": (0.9, 1.0), "9": (0.95, 0.95)}
    r = shoot(game, balls, v0=3.0, phi=90.0, b=0.0)
    assert r["rules"]["legal"], f"quiet break must be legal: {r['rules']}"
    return r["balls"]


g = new_game("classic")
balls = quiet_break(g)
s = snap("classic", g)
check(
    "F0 quiet legal break: no score, turn passed, call now required",
    s["scores"][0]["score"] == 0
    and s["turn"]["id"] == "p2"
    and s["call_shot"] is True,
    str(s["scores"]) + s["turn"]["id"],
)

# F1: honored call -> LEGAL, ball value scored
balls = dict(balls)
balls["cue"] = (1.05, 1.05)
balls["9"] = (0.95, 0.95)
g.shot_constraints.ball_call = "9"
g.shot_constraints.pocket_call = "lb"
r = shoot(g, balls, v0=2.0, phi=225.0, b=0.0)
check(
    "F1 honored call: legal, '9' (value 9) scored",
    r["rules"]["legal"]
    and r["rules"]["reason"] == "legal"
    and score_of(r, "p2") == 9,
    str(r["rules"]),
)

# F2: not honored -> UNCALLED_POT: respot, no score, turn passes
g = new_game("classic")
balls = quiet_break(g)
balls = dict(balls)
balls["cue"] = (1.05, 1.05)
balls["9"] = (0.95, 0.95)
g.shot_constraints.ball_call = "9"
g.shot_constraints.pocket_call = "rb"  # wrong pocket
r = shoot(g, balls, v0=2.0, phi=225.0, b=0.0)
check(
    "F2 unhonored call: uncalled_pot, respotted, no score, turn over",
    r["rules"]["reason"] == "uncalled_pot"
    and r["respotted"] == ["9"]
    and score_of(r, "p2") == 0
    and r["rules"]["turn_over"] is True,
    str(r["rules"]) + str(r["respotted"]),
)

# F3: cue potted -> CUE_POTTED foul: -5/+5, respot, no penalty ball
g = new_game("classic")
balls = quiet_break(g)
balls = dict(balls)
balls["cue"] = (1.05, 1.05)
balls["9"] = (0.95, 0.95)
g.shot_constraints.ball_call = "9"
g.shot_constraints.pocket_call = "lb"
r = shoot(g, balls, v0=2.0, phi=225.0, b=0.9)
check(
    "F3 cue potted: foul cue_potted, -5/+5 transferred",
    not r["rules"]["legal"]
    and r["rules"]["reason"] == "cue_potted"
    and score_of(r, "p2") == -5
    and score_of(r, "p1") == 5,
    str(r["rules"]),
)
check(
    "F3 classic has no penalty ball; '9' and the cue both respotted",
    r["removed"] == []
    and "9" in r["respotted"]
    and "cue" in r["respotted"]
    and abs(r["balls"]["cue"]["y"] - 0.851) < 1e-6,
    str(r["removed"]) + str(r["respotted"]),
)
s = snap("classic", g)
check("F3 penalty stroke from the house (behind_line)", s["ball_in_hand"] == "behind_line")

# --- G. cue placement validation ---------------------------------------------------

print("== G. cue placement ==")
try:
    rules.validate_cue_placement("behind_line", 0.9, 1.0, {})
    check("G1 behind_line rejects y past the house line", False, "no error raised")
except ValueError:
    check("G1 behind_line rejects y past the house line", True)
try:
    rules.validate_cue_placement("anywhere", 0.02, 1.0, {})
    check("G2 anywhere rejects x inside the cushion", False, "no error raised")
except ValueError:
    check("G2 anywhere rejects x inside the cushion", True)
try:
    rules.validate_cue_placement("behind_line", 0.5, 0.5, {"1": (0.52, 0.5)})
    check("G3 rejects overlap with another ball", False, "no error raised")
except ValueError:
    check("G3 rejects overlap with another ball", True)
pos = rules.validate_cue_placement("behind_line", 0.9, 0.85, {"1": (0.2, 0.2)})
check("G4 valid house placement accepted", pos == (0.9, 0.85))
pos = rules.validate_cue_placement("anywhere", 1.2, 2.0, {"1": (0.2, 0.2)})
check("G5 valid anywhere placement accepted", pos == (1.2, 2.0))

print()
if failed:
    print(f"{len(failed)} FAILED, {passed} passed")
    sys.exit(1)
print(f"ALL {passed} CHECKS PASSED")
