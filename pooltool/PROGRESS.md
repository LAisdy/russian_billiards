# PROGRESS.md — Russian Pyramid extension for pooltool

**Project:** extend the open-source [pooltool](https://github.com/ekiefl/pooltool)
library with full Russian pyramid («пирамида») support in 3D — **Free**,
**Combined**, **Dynamic** and **Classic** disciplines — with rule fidelity
suitable for official simulation (ФБСР rules) and real-time-safe performance
in Python.

> **Crash-recovery guardrail (read me first).** If the server crashes or
> context is lost, the next run MUST begin by reading this file, locate the
> first step whose status is not `DONE`, and continue from there. Never redo
> steps already marked `DONE` without an explicit reason. Never start a new
> step before the previous step has a dated entry in the **Step Log**.

## Task reference (immutable specs)

- **Disciplines & classes:** `RussianFreePyramid` (Свободная пирамида),
  `RussianCombinedPyramid` (Комбинированная / Московская),
  `RussianDynamicPyramid` (Динамичная / Невская),
  `RussianClassicPyramid` (Классическая).
- **Required Ruleset API per class:** `build_shot_info(shot) -> ShotInfo`,
  `next_shot_constraints(shot) -> ShotConstraints`,
  `initial_shot_constraints() -> ShotConstraints`, `respot_balls(shot) -> None`,
  `copy() -> Ruleset`.
- **Equipment:** playing surface 370 × 180 cm (12 × 6 ft); ball Ø 67 mm
  (older spec 68 mm), mass ≈ 255 g; object balls white, numbered 1–15; cue ball
  red or yellow; corner pocket gap ≈ 72–73 mm (only ≈ 3–5 mm wider than the
  ball); middle pocket ≈ 82–83 mm (≈ 12–13 mm wider).
- **Rules sources:** official ФБСР rules (or an equivalent authoritative
  source). Key points to verify and implement per discipline: legality of
  pocketing the cue ball («свояк») after contacting an object ball;
  called-shot requirements (or their absence); scoring (in some variants each
  potted ball scores its number, the 1-ball often scores 11, first to a
  threshold such as 71 points wins — verify exact scoring per discipline);
  break requirements (cushion contacts / potted ball).
- **Performance guardrails:** prefer vectorized NumPy for ball-state checks;
  no unnecessary Python loops; Numba (`@njit`, optionally `parallel=True`) only
  for collision-heavy hotspots justified by profiling, never called from dense
  Python loops; no fixed-time-step simulation loops; integrate with the
  existing `process_shot` / `advance` pipeline.
- **Deliverables:** `pooltool/ruleset/russian_pyramid.py` (+ utility modules if
  needed), updated `pooltool/game/datatypes.py` and
  `pooltool/ruleset/__init__.py`, `tests/test_russian_pyramid.py` (≥ 10
  scenarios per discipline + 500-shot fuzz per discipline),
  `README_RUSSIAN_PYRAMID.md`, `RULES_DEVIATIONS.md`, `PROGRESS.md`.

## Step table

| #  | Step                                                                                                                                                             | Status       |
|:--:|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------|:-------------|
| 0  | Checkpoint infrastructure: `PROGRESS.md` + `RULES_DEVIATIONS.md`, read/write verified                                                                             | DONE        |
| 1  | Codebase reconnaissance: `Ruleset` ABC, `ShotInfo` / `ShotConstraints`, `datatypes.py`, respot in `ruleset/utils.py`, `_ruleset_classes` registry; summary → Notes | DONE         |
| 2  | Skeleton: `pooltool/ruleset/russian_pyramid.py` with 4 stub Ruleset subclasses; `python -c "import pooltool.ruleset.russian_pyramid"` must pass                   | DONE         |
| 3  | Table & balls: 12 ft (370 × 180 cm) table, corner pockets ~72–73 mm, middle ~82–83 mm, Ø 67 mm / ~255 g balls, 15 white object balls + red cue ball; unit test    | DONE         |
| 4  | Registration: `GameType` entries + `_ruleset_classes` wiring; `get_ruleset(...)` verified for each new type                                                       | DONE         |
| 5  | Free Pyramid (Свободная) rules: full Ruleset implementation (all 5 methods), vectorized NumPy state checks, ФБСР rule points documented, deviations logged       | DONE         |
| 6  | Free Pyramid tests: ≥ 10 scripted scenarios (legal/illegal shots, «свояк», break, cue-ball-in-without-contact, score progression, turn switching, game end, respot); `pytest tests/test_russian_pyramid.py -k free` green | DONE |
| 7  | Combined Pyramid (Комбинированная / Московская): implementation + ≥ 10 tests, same scheme                                                                         | DONE         |
| 8  | Dynamic Pyramid (Динамичная / Невская): implementation + ≥ 10 tests, same scheme                                                                                     | DONE        |
| 9  | Classic Pyramid (Классическая): implementation (incl. called shots) + ≥ 10 tests, same scheme                                                                    | DONE         |
| 10 | Profiling & optimization: cProfile / pooltool built-in tools, vectorize remaining loops, selective Numba; before/after results → Performance section             | DONE         |
| 11 | Full simulations & fuzzing: 1 complete frame per discipline (headless if possible) + 500 random shots per discipline; reports → PROGRESS.md                      | TODO         |
| 12 | Documentation & finalization: `README_RUSSIAN_PYRAMID.md`, finalize `RULES_DEVIATIONS.md`, final `pytest tests/test_russian_pyramid.py`                           | TODO         |

**Status legend:** `TODO` — not started · `IN_PROGRESS` — started but unfinished
or blocked (Step Log entry must name the blocker) · `DONE` — artifacts written
and verification passed.

## Files

**Created**
- `PROGRESS.md` (repo root) — this checkpoint file
- `RULES_DEVIATIONS.md` (repo root) — deviations vs official ФБСР rules
- `pooltool/ruleset/russian_pyramid.py` — the four discipline ruleset classes
  (Free, Combined, Dynamic, Classic — all fully implemented)
- `pooltool/models/balls/russian_pyramid/` — ballset: `1.glb`–`15.glb` +
  `shadow.glb` (copied from `pooltool_pocket`), `red.glb` (copied from
  `billiard`), `conversion.json` mapping `"cue" → "red"`
- `tests/test_russian_pyramid.py` — 16 equipment tests (Step 3–4) + 19 Free
  Pyramid scenario tests in 5 `TestFreePyramid*` classes (Step 6) + 15 Combined
  Pyramid scenario tests in 5 `TestCombinedPyramid*` classes (Step 7) + 15
  Dynamic Pyramid scenario tests in 5 `TestDynamicPyramid*` classes (Step 8) +
  18 Classic Pyramid scenario tests in 5 `TestClassicPyramid*` classes
  (Step 9); Step 11 appends the 500-shot fuzz tests here

**Modified**
- `pooltool/objects/table/collection.py` — `TableName.RUSSIAN_PYRAMID_GENERIC`
  + `TABLE_SPECS` entry (12 ft Russian pyramid table); `_default_game_type_map`
  += 4 Russian GameTypes
- `pooltool/objects/ball/params.py` —
  `PrebuiltBallParams.RUSSIAN_PYRAMID_GENERIC` + `BALL_PARAMS` entry
  (Ø 67 mm, 255 g); `_default_map` += 4 Russian GameTypes
- `pooltool/game/datatypes.py` — 4 new `GameType` members
  (`RUSSIAN_PYRAMID_FREE/COMBINED/DYNAMIC/CLASSIC`)
- `pooltool/ruleset/__init__.py` — 4 public Russian ruleset classes imported,
  registered in `_ruleset_classes`, exported via `__all__`
- `pooltool/objects/cue/datatypes.py` —
  `PrebuiltCueSpecs.RUSSIAN_PYRAMID_GENERIC` + `CUE_MODELS`/`CUE_SPECS`/
  `_default_map` entries
- `pooltool/layouts.py` — `DEFAULT_RUSSIAN_BALLSET`,
  `_get_russian_pyramid_rack` (shared by Free/Combined/Dynamic),
  `_get_russian_classic_rack` (fixed п. 3 arrangement for Classic,
  Step 9), `_game_rack_map` += 4 Russian GameTypes

## Notes

### Decisions
- **Repo root:** `/home/z/my-project/pooltool` — shallow clone of
  `https://github.com/ekiefl/pooltool`, branch `main`, commit `7632b1c`
  (2026-10-11, "Off table mechanics (#396)"), cloned 2026-10-29 12:27 MSK.
  All work happens in this tree; `PROGRESS.md` sits at its root.
- **Layout confirmed on `main`:** `pooltool/ruleset/` (`eight_ball.py`,
  `nine_ball.py`, `snooker/`, `utils.py`, `datatypes.py`, `three_cushion.py`,
  `sum_to_three.py`, `sandbox.py`), `pooltool/game/datatypes.py`,
  `tests/ruleset/`, `pooltool/evolution/` (event-based engine), `pooltool/ani/`
  (Panda3D interface, incl. `ani/modes/call_shot.py`). The task's referenced
  layout exists on the default branch — no version pin needed for now.
- **Checkpoint protocol per step:** write artifacts to disk → update the step
  table → append a dated Step Log entry (commands + results) → stop and report.
  No git commits are made; the Step Log is the "commit-like" record required by
  the task statement.
- **Performance guardrails from day one:** vectorized NumPy for ball-state
  checks; no fixed-time-step simulation loops; Numba only where profiling
  justifies it and never invoked from dense Python loops.
- **Editable install (Step 1):** `uv pip install --python /home/z/.venv/bin/python3
  -e .` from the repo root → `pooltool-billiards 0.6.0` installed editable,
  resolving to `/home/z/my-project/pooltool/pooltool/__init__.py`; pulled in
  `msgpack-numpy 0.4.8`, `panda3d 1.11.0.dev4085+shaderpipeline.388`,
  `panda3d-gltf 1.3.0`, `panda3d-simplepbr 0.13.1`. Preexisting: numpy 2.1.3,
  numba 0.61.0, llvmlite 0.44.0, scipy 1.14.1, attrs/cattrs 26.1.0. Note:
  `import pooltool` requires panda3d at module level
  (`pooltool/__init__.py` → `ani.image.interface` → `panda3d.core`), so
  panda3d is a hard runtime requirement even for pure ruleset work. Install
  left `git status` clean apart from the two checkpoint files.
- **Class naming:** existing ruleset classes are underscore-private
  (`_EightBall`); the new Russian classes will be public
  (`RussianFreePyramid` etc.) and exported via `__all__`.
- **Cue ball ID:** `"cue"` — matches `ShotConstraints.cueball()` heuristic
  and existing rack conventions.

### Codebase map (Step 1 reconnaissance)

**`pooltool/ruleset/datatypes.py` — the ruleset core.**

- `Ruleset` (ABC), constructed with `players: list[Player] | None`. Base state:
  `players`, `active_idx`, `score: Counter[str]`, `shot_number`, `turn_number`,
  `shot_constraints` (initialized from `initial_shot_constraints()`), `shot_info`,
  `log: Log`. Properties `active_player` / `last_player`; `set_next_player()`
  sets `active_idx = turn_number % len(players)`.
- **Template methods** (do NOT need overriding unless adding log messages):
  - `process_shot(shot)` → `shot_info = build_shot_info(shot)` →
    `score = shot_info.score` → `respot_balls(shot)`.
  - `advance(shot)` → if `game_over`: log winner & return; if `turn_over`:
    `turn_number += 1`; `shot_number += 1`;
    `shot_constraints = next_shot_constraints(shot)`;
    `shot.cue.cue_ball_id = shot_constraints.cueball(shot.balls)`;
    `set_next_player()`. `process_and_advance(shot)` chains both.
- **The 5 abstract methods** (exactly what the task requires):
  `build_shot_info(shot) -> ShotInfo`, `next_shot_constraints(shot) ->
  ShotConstraints`, `initial_shot_constraints() -> ShotConstraints`,
  `respot_balls(shot) -> None`, `copy() -> Ruleset`.
- `ShotInfo` (frozen attrs): `player, legal, reason, turn_over, game_over,
  winner: Player | None, score: Counter[str]`.
- `ShotConstraints` (attrs): `ball_in_hand: BallInHandOptions`
  (`NONE | ANYWHERE | BEHIND_LINE | SEMICIRCLE`), `movable: list[str] | None`,
  `cueable: list[str] | None`, `hittable: tuple[str, ...]`, `call_shot: bool`,
  `ball_call`, `pocket_call`. Helper `cueball(balls)` returns `cueable[0]`, else
  first of `"cue"/"white"/"yellow"` found in `balls` — so **use ball ID
  `"cue"`** for the Russian pyramid cue ball (matches existing rack convention,
  e.g. 8-ball rack places `"cue"` at head string). `can_shoot()` checks call.
- `Player` (attrs): `name`, `ai`. `Log.add_msg(msg, sentiment=...)` for HUD.

**`pooltool/ruleset/utils.py` — reusable shot-introspection helpers.**

`get_pocketed_ball_ids_during_shot(shot, exclude)` (BALL_POCKET events),
`get_pocketed_ball_ids(shot)` (state == pocketed at end),
`get_id_of_first_ball_hit(shot, cue)` (first cue BALL_BALL event),
`is_ball_pocketed`, `is_ball_pocketed_in_pocket`, `is_target_group_hit_first`,
`respot(shot, ball_id, x, y, z=None)` (writes `rvw[0]` + state; FIXME: no
  overlap check — pyramid respot must handle blocking itself),
`get_ball_ids_on_table(shot, at_start, exclude)` (uses `ball.history[0|-1]`),
`StateProbe`, `get_lowest_ball` / `get_highest_ball`, `is_lowest_hit_first`,
`balls_that_hit_cushion(shot, exclude)` (LINEAR+CIRCULAR cushion events),
`is_ball_hit`, `is_numbered_ball_pocketed`, `is_shot_called_if_required`.
All event filtering goes through `pooltool.events.filter`
(`by_ball`, `by_type`, `by_time`, `filter_events`) on `shot.events` with
`EventType.{BALL_BALL, BALL_POCKET, BALL_LINEAR_CUSHION,
BALL_CIRCULAR_CUSHION}`.

**`pooltool/ruleset/__init__.py` — registry.** `_ruleset_classes:
dict[GameType, type[Ruleset]]` maps NINEBALL→`_NineBall`, EIGHTBALL→
`_EightBall`, THREECUSHION→`_ThreeCushion`, SNOOKER→`_Snooker`,
SUMTOTHREE→`_SumToThree`; `get_ruleset(game, enforce_rules=True)` returns
`_RulelessMode` when `enforce_rules=False`. Existing classes are
module-private with underscore prefix; new Russian classes will be exported
properly (public names, no underscore, added to `__all__`).

**`pooltool/game/datatypes.py` — `GameType(StrEnum)`** with 5 string-valued
members. Step 4 adds 4 members; **downstream consumers that must be updated
  in lock-step** (all raise/fail on unknown GameType):
1. `pooltool/ruleset/__init__.py`: `_ruleset_classes` registry.
2. `pooltool/objects/ball/params.py`: `_default_map: dict[GameType,
   PrebuiltBallParams]` — needs a new `PrebuiltBallParams` member (Russian
   pyramid: m ≈ 0.255 kg, R = 0.0335 m).
3. `pooltool/objects/table/collection.py`: `TABLE_SPECS` +
   `_default_game_type_map: dict[GameType, TableName]` — needs a new
   `TableName` member (12 ft table specs).
4. `pooltool/layouts.py`: `_game_rack_map: dict[GameType, GetRackProtocol]` —
   needs `_get_russian_pyramid_rack` (triangle of 15 + cue).
5. `pooltool/objects/cue/datatypes.py`: `_default_map: dict[GameType,
   PrebuiltCueSpecs]` + `Cue.from_game_type` — needs an entry (billiard-style
   cue).

**`pooltool/objects/` — equipment.** `PocketTableSpecs` (attrs, frozen) has
`l`, `w`, `cushion_width`, `corner_pocket_width` (jaw-to-jaw gap),
`corner_pocket_angle/depth/radius`, `corner_jaw_radius`, `side_pocket_*`,
`side_jaw_radius`, plus viz fields; `Table.from_table_specs(specs)` builds the
playable table. `BallParams` frozen attrs with `m`, `R`, friction/restitution
params; `BallParams.default(game_type)` goes through `_default_map`.
`BallSet` = directory of `.glb` models under `pooltool/models/balls/<name>/`
+ optional `conversion.json` (ball ID → model ID); available ballsets include
`pooltool_pocket` (numbered 1–15 + `cue`) and `billiard` (red/yellow/white,
no numbers). Russian pyramid needs 15 white numbered + red/yellow cue —
plan: create a `russian_pyramid` ballset dir (copies of `pooltool_pocket`
models for 1–15 + `billiard/red` for the cue ball, plus `conversion.json`
mapping `"cue"→"red"`). Ball IDs: `"1"…"15"` + `"cue"`.

**Existing ruleset structure pattern** (followed by both `_EightBall` and
`_Snooker`):
- Module-level pure functions `is_legal(shot, constraints, ...) ->
  tuple[bool, Reason|str]`, `is_turn_over(...)`, `is_game_over(...)`,
  `decide_winner(...)`; the Ruleset subclass composes them in
  `build_shot_info`.
- `initial_shot_constraints()`: break = ball-in-hand behind line (8-ball) or
  in semicircle (snooker), `call_shot=False`.
- `next_shot_constraints(shot)`: foul → opponent ball-in-hand (ANYWHERE for
  pool / SEMICIRCLE for snooker); `hittable` groups; `call_shot` flags.
- `respot_balls(shot)`: uses `respot()` + `get_ball_ids_on_table(shot,
  at_start=False)`; snooker respots colors + white at rule-defined spots
  (relative coords × table dims).
- `get_score(shot) -> Counter` accumulates points.
- `process_shot` overridden only to add HUD log messages.
- `copy()`: **both 8-ball and snooker raise NotImplementedError** — the
  Russian rulesets must implement a real `copy()` (score, counters,
  constraints, players) instead.
- Snooker keeps legality reasons in a `Reason` StrEnum (in
  `ruleset/snooker/utils.py`) — good pattern to adopt for pyramid.

**Game loop / GUI.** `System(cue, table, balls, t, events)`;
`System.example()`, `simulate(system, inplace=True)`, `system.simulated`.
GUI entry `pooltool.ani.animate.Game._create_system()` consumes
`settings.gameplay.game_type` → `get_ruleset() → get_rack(game_type, table,
...) → Cue.from_game_type(game_type)` — confirming all 5 GameType maps above
must gain Russian entries for the 3D interface to work (Step 11).
Headless rendering candidate: `sandbox/offscreen/offscreen.py`.

**Tests.** Existing ruleset tests: `tests/ruleset/test_three_cushion.py` with
`.msgpack` shot fixtures in `tests/ruleset/test_shots/`. pytest config:
`testpaths=["tests"]`, `pythonpath=["tests"]`, importlib import mode —
`tests/test_russian_pyramid.py` (task-specified location) is picked up fine.

### Open questions
- **Panda3D headless rendering for Step 11** — `sandbox/offscreen/offscreen.py`
  exists in the repo and looks promising; to be evaluated.
- **`respot()` overlap FIXME** — upstream `respot()` does not check whether
  the respot spot is occupied. Russian pyramid respots at the foot spot with
  fallback along the long string toward the foot rail; the occupancy check +
  fallback will be implemented in the pyramid module (deviation to be logged
  if the fallback order differs from ФБСР wording).
- **Ballset for rendering** — RESOLVED in Step 3: the `russian_pyramid` ballset
  directory was created and is auto-discovered; deviations logged (#1, #2 in
  `RULES_DEVIATIONS.md`).

*(Resolved in Step 1: pooltool importability — editable install, see
Decisions; tests location — `tests/test_russian_pyramid.py` works with pytest
`testpaths`; Numba availability — numba 0.61.0 installed.)*

## Performance

### Methodology

- Benchmark harness: `scripts/benchmark_step10.py` (persisted, re-runnable).
  Per discipline it simulates a full-rack break aimed dead-straight at the
  apex ball (V0 = 9 m/s), then measures on that simulated shot:
  `physics_ms` (median wall time of one `pt.simulate` stroke, baseline);
  `eval@break` (`build_shot_info` + `next_shot_constraints`, п. 12 break
  path); `eval@mid` (same on the п. 20 ordinary path, `shot_number = 5`,
  including the п. 21 house check in Combined/Classic); `process` (full
  `process_and_advance` on restored ball snapshots); `construct` (bare
  ruleset construction, reported so it can be discounted). Timing: best of
  3 rounds × 200–300 calls; raw data in `scripts/step10_before.json` /
  `scripts/step10_after.json`, cProfile dump in `scripts/step10_free.prof`.

### Baseline (before Step 10) — 2026-10-29

Per-stroke event inspection re-filtered `shot.events` with chained
`pooltool.events.filter` closures up to ~12 times per
`process_and_advance` round. cProfile (Free, break path): the `by_ball`
closure was ~22% and `by_type` ~16% of total evaluation time, plus
`Event.ids` tuple construction (~8%) and `by_time`'s O(n log n)
sortedness re-check on every time-sliced call.

| discipline | eval@break | eval@mid | process | ruleset share/stroke |
|------------|-----------:|---------:|--------:|---------------------:|
| free       |    92.6 µs | 160.3 µs | 275.9 µs |               0.24% |
| combined   |   137.7 µs | 271.6 µs | 332.6 µs |               0.25% |
| dynamic    |   124.0 µs | 192.8 µs | 319.6 µs |               0.28% |
| classic    |   139.8 µs | 249.4 µs | 326.0 µs |               0.30% |

(A simulated stroke is 105–144 ms — the ruleset was never the bottleneck;
the goal of Step 10 is measured headroom, not rescue.)

### After optimization — 2026-10-29

Change: one chronological single-pass event scan (`_EventScan` in
`pooltool/ruleset/russian_pyramid.py`) buckets every event kind (first
cue-ball contact, pockets + pocket map, off-table balls, cushion
contacts). Public helper signatures and semantics are unchanged; each
ruleset call (`build_shot_info` / `next_shot_constraints` /
`respot_balls`) now scans the event list exactly once instead of running
4–12 filter chains, and the generic closures (incl. `by_time`'s sort
check) are off the hot path.

| discipline | eval@break (Δ) | eval@mid (Δ) | process (Δ) | ruleset share/stroke |
|------------|---------------:|-------------:|------------:|---------------------:|
| free       |  54.7 µs (−41%) | 121.7 µs (−24%) | 250.6 µs (−9%)  |               0.17% |
| combined   |  47.5 µs (−66%) | 136.6 µs (−50%) | 234.6 µs (−29%) |               0.22% |
| dynamic    |  48.2 µs (−61%) | 113.8 µs (−41%) | 237.9 µs (−26%) |               0.21% |
| classic    |  70.4 µs (−50%) | 140.5 µs (−44%) | 262.0 µs (−20%) |               0.21% |

Post-change profile (Free, break path): the single-pass
`_EventScan.__init__` is now the largest ruleset term, followed by
upstream history access (`get_ball_ids_on_table` →
`BallHistory.__getitem__` → per-ball `BallState` copy, ~8 µs per
evaluation — shared `ruleset/utils.py` code used by other games,
deliberately left untouched).

### Numba assessment («selective Numba»)

`scripts/numba_eval_step10.py` jitted the only remaining pure-numeric
ruleset loop (the `_is_free` respot-clearance check): njit kernel
435 ns/call vs. 2 960 ns/call pure Python (7× faster, dispatch included);
the NumPy-vectorized variant is *slower* (4 057 ns — call overhead beats
vectorization at N ≤ 16). Despite the per-call win, Numba is **not**
applied to the ruleset paths: `_is_free` executes only a handful of times
per respot (≤ ~30 µs per stroke) inside a path that is ~0.2% of a
simulated stroke, while an njit ruleset would add first-call JIT latency
(~seconds) and a hard numba dependency to every ruleset import. Numba
stays where it already pays off — the physics engine's quartic solver.
`crossed_center_line` was already NumPy-vectorized per ball and is
unchanged.

### Bottom line

Ruleset overhead per simulated stroke is **~0.2% of physics time**
(234–262 µs `process_and_advance` vs. 105–144 ms stroke) with evaluation
20–66% faster than the pre-Step-10 baseline — real-time-safe by a wide
margin.

## Step Log

### [0] Checkpoint infrastructure — DONE

- **Date/time (Europe/Moscow):** 2026-10-29 12:27 MSK
- **What was done**
  - Environment check: Python 3.12.16 (`/home/z/.venv/bin/python3`), git
    2.47.3, pytest 9.0.2 available; pooltool not previously installed.
  - Acquired pooltool source: `git clone --depth 1
    https://github.com/ekiefl/pooltool.git /home/z/my-project/pooltool` →
    branch `main`, commit `7632b1c` (2026-10-11, "Off table mechanics (#396)").
    Confirmed presence of `pooltool/ruleset/` (+ `utils.py`),
    `pooltool/game/datatypes.py`, `tests/ruleset/`, `pooltool/evolution/`,
    `pooltool/ani/` (incl. `ani/modes/call_shot.py`).
  - Created `PROGRESS.md` (repo root): task reference, 13-row step table,
    Files / Notes / Performance / Step Log sections.
  - Created `RULES_DEVIATIONS.md` (repo root): policy + empty deviation-log
    table.
- **What was verified (command → result)**
  - `Read` tool on both files → full expected contents returned.
  - `bash: test -r <f> && test -s <f>` → `OK PROGRESS.md (8538 bytes)`,
    `OK RULES_DEVIATIONS.md (2097 bytes)`.
  - Python UTF-8 read probe → 8283 / 1941 chars, correct first lines on both.
- **Outcome:** Step 0 DONE. Stopped before Step 1 per protocol; awaiting
  continuation signal.

### [1] Codebase reconnaissance — DONE

- **Date/time (Europe/Moscow):** 2026-10-29 12:33–12:41 MSK
- **What was done**
  - Read in full: `pooltool/ruleset/datatypes.py` (Ruleset ABC, ShotInfo,
    ShotConstraints, Player, Log, BallInHandOptions), `pooltool/ruleset/__init__.py`
    (`_ruleset_classes` registry + `get_ruleset`), `pooltool/ruleset/utils.py`
    (all shot-introspection helpers incl. `respot`), `pooltool/game/datatypes.py`
    (GameType), `pooltool/ruleset/eight_ball.py` (full),
    `pooltool/ruleset/snooker/core.py` (respot/score/constraints patterns),
    `pyproject.toml` (deps, pytest config), plus targeted skims of
    `pooltool/objects/{ball,params,sets}.py`, `pooltool/objects/table/specs.py`,
    `pooltool/objects/table/collection.py`, `pooltool/layouts.py` (rack maps),
    `pooltool/objects/cue/datatypes.py` (`_default_map`),
    `pooltool/system/datatypes.py`, `pooltool/ani/animate.py` (Game loop),
    `pooltool/ani/constants.py`, `pooltool/ani/image/*`.
  - **Resolved the pooltool-importability open question:** editable-installed
    the project into the active venv with uv (see Decisions). All runtime
    deps now importable, including the pinned panda3d dev build.
  - Identified all five downstream GameType consumers that Step 4 must update
    in lock-step (ruleset registry, ball params map, table specs map, rack
    map, cue specs map).
  - Wrote the full reconnaissance summary into the Notes → "Codebase map"
    section of this file.
- **What was verified (command → result)**
  - `uv pip install --python /home/z/.venv/bin/python3 -e .` → resolved 22
    packages, installed 5, no errors.
  - `python3 -c "import pooltool; ..."` → `pooltool 0.6.0 ->
    /home/z/my-project/pooltool/pooltool/__init__.py`.
  - `get_ruleset()` for all 5 existing GameTypes → returns `_EightBall`,
    `_NineBall`, `_Snooker`, `_ThreeCushion`, `_SumToThree`; `System.example()`
    constructs.
  - `git status --porcelain` → only `?? PROGRESS.md`, `?? RULES_DEVIATIONS.md`
    (install did not dirty the tree).
- **Decisions / findings of note**
  - Use ball ID `"cue"` for the pyramid cue ball; object balls `"1"…"15"`.
  - New classes will be public (no underscore) and added to `__all__`.
  - 8-ball and snooker `copy()` both raise `NotImplementedError` — pyramid
    rulesets must implement real copies.
  - `respot()` has an upstream FIXME (no overlap check) → pyramid module will
    implement its own occupied-spot fallback.
- **Outcome:** Step 1 DONE. Stopped before Step 2 per protocol; awaiting
  continuation signal.

### [2] Module skeleton — DONE

- **Date/time (Europe/Moscow):** 2026-10-29 13:58–14:05 MSK
- **What was done**
  - Created `pooltool/ruleset/russian_pyramid.py`: module docstring covering
    the four disciplines («Свободная», «Комбинированная», «Динамичная»,
    «Классическая»), equipment summary, ФБСР target, and skeleton status;
    four public `Ruleset` subclasses — `RussianFreePyramid`,
    `RussianCombinedPyramid`, `RussianDynamicPyramid`, `RussianClassicPyramid`
    — each implementing all 5 required methods (`build_shot_info`,
    `next_shot_constraints`, `initial_shot_constraints`, `respot_balls`,
    `copy`) as `NotImplementedError` stubs whose messages reference the
    implementation step; alphabetical `__all__` (repo convention).
  - Persisted the reusable verification script at
    `/home/z/my-project/scripts/verify_russian_pyramid_module.py` (outside
    the repo; checks imports, class hierarchy, signatures via
    `inspect`+`get_type_hints`, stub behavior, instantiation surfacing).
  - Fixed one script bug pre-run (missing `import sys`); adjusted the
    `__all__` check to be order-insensitive (module uses alphabetical order
    like the repo's existing `ruleset/__init__.py`).
  - Auto-fixed ruff I001 (blank line between imports and `__all__`) and ran
    `ruff format` on the new module.
- **What was verified (command → result)**
  - `python -c "import pooltool.ruleset.russian_pyramid"` from `/tmp` → OK;
    from repo root → OK (`m.__file__` = repo source, editable install).
  - `python3 /home/z/my-project/scripts/verify_russian_pyramid_module.py` →
    RESULT: ALL CHECKS PASSED (106 checks: 4 classes × 5 methods × signature/
    annotation/stub/step-message, subclass-of-Ruleset, `__all__`, stub
    surfaced via `Ruleset.__init__` for each class).
  - `uvx ruff check pooltool/ruleset/russian_pyramid.py` → All checks passed.
  - `uvx ruff format --check pooltool/ruleset/russian_pyramid.py` → formatted.
  - `git status --porcelain` → only expected additions: `PROGRESS.md`,
    `RULES_DEVIATIONS.md`, `pooltool/ruleset/russian_pyramid.py`.
- **Outcome:** Step 2 DONE. Stopped before Step 3 per protocol; awaiting
  continuation signal.

### [3] Table & balls equipment — DONE

- **Date/time (Europe/Moscow):** 2026-10-29 11:24 MSK
- **What was done**
  - `pooltool/objects/table/collection.py`: added
    `TableName.RUSSIAN_PYRAMID_GENERIC` and the matching `TABLE_SPECS` entry —
    `PocketTableSpecs` with playing surface l = 3.70 m, w = 1.80 m, corner
    mouth 72.5 mm and middle mouth 82.5 mm (midpoints of the task bands),
    cushion height 0.64 × ball diameter, deep straight-jawed pocket geometry
    (pocket radius > half mouth width kept as an invariant), table height
    0.82 m, `model_descr = TableModelDescr.null()`.
  - `pooltool/objects/ball/params.py`: added
    `PrebuiltBallParams.RUSSIAN_PYRAMID_GENERIC` and the matching
    `BALL_PARAMS` entry — m = 0.255 kg, R = 0.0335 m (Ø 67 mm); friction and
    restitution reuse generic pool values pending Step 10 profiling.
  - Created the auto-discovered ballset `pooltool/models/balls/russian_pyramid/`:
    `1.glb`–`15.glb` + `shadow.glb` copied from `pooltool_pocket`, `red.glb`
    copied from `billiard`, `conversion.json` = `{"cue": "red"}`.
  - Created `tests/test_russian_pyramid.py` with 16 equipment tests across four
    classes (table specs, ball params, ballset, cross-equipment consistency).
  - Logged deviations #1 (colored object-ball models instead of all-white) and
    #2 (`null` table model) in `RULES_DEVIATIONS.md`.
  - GameType wiring (`_default_map`, `_default_game_type_map`, rack, cue specs)
    deliberately deferred to Step 4.
- **What was verified (command → result)**
  - `python -c "... Table.from_table_specs(TABLE_SPECS[RUSSIAN_PYRAMID_GENERIC])"`
    → specs OK; table builds with 18 linear + 12 circular cushion segments and
    6 pockets (no degenerate pocket geometry).
  - `python -c "... BallParams.prebuilt(RUSSIAN_PYRAMID_GENERIC)"` → m = 0.255 kg,
    diameter = 67.0 mm, attrs validators pass.
  - `python -c "... get_ballset('russian_pyramid')"` → auto-discovered; all 16
    ball IDs resolve; `cue → red.glb`.
  - `python -m pytest tests/test_russian_pyramid.py -v` → **16 passed** in 2.14 s.
  - `uvx ruff check` (3 touched files) → All checks passed; `uvx ruff format`
    applied once to the test file, then `--check` clean for all three.
- **Decisions / findings of note**
  - Pocket depth/radius/jaw values follow the deep, straight-jawed Russian
    pocket style; geometric self-consistency (radius > half mouth) is enforced
    by a unit test rather than trusting defaults.
  - `_default_table_type_map` untouched — the new table is reachable only via
    `TableName` / GameType mapping (Step 4), so no existing game changes
    behavior.
- **Outcome:** Step 3 DONE. Stopped before Step 4 per protocol; awaiting
  continuation signal.

### [4] Registration (GameType + full wiring) — DONE

- **Date/time (Europe/Moscow):** 2026-10-29 11:37–11:45 MSK
- **What was done**
  - `pooltool/game/datatypes.py`: added 4 `GameType` members —
    `RUSSIAN_PYRAMID_FREE/COMBINED/DYNAMIC/CLASSIC` with display strings
    "Free Pyramid" / "Combined Pyramid" / "Dynamic Pyramid" / "Classic
    Pyramid" (decision: explicit `RUSSIAN_PYRAMID_*` prefix, self-documenting
    and collision-free with future games).
  - `pooltool/ruleset/__init__.py`: imported the 4 public classes; registered
    them in `_ruleset_classes`; added them to `__all__` (ruff RUF022 then
    re-sorted `__all__` via `--fix`).
  - `pooltool/objects/cue/datatypes.py`: added
    `PrebuiltCueSpecs.RUSSIAN_PYRAMID_GENERIC` — M = 0.62 kg, length = 1.58 m
    (long/heavy Russian style), tip/shaft geometry copied from the pool cue,
    `end_mass = 0.255/30` (upstream ball-mass/30 convention),
    `CUE_MODELS → "cue"` (no dedicated Russian cue model exists); wired all 4
    GameTypes in `_default_map`.
  - `pooltool/objects/ball/params.py`: `_default_map` += 4 GameTypes →
    `RUSSIAN_PYRAMID_GENERIC`.
  - `pooltool/objects/table/collection.py`: `_default_game_type_map` += 4
    GameTypes → `RUSSIAN_PYRAMID_GENERIC`.
  - `pooltool/layouts.py`: added `DEFAULT_RUSSIAN_BALLSET` and
    `_get_russian_pyramid_rack` — 5-row/15-ball triangle via the same jump
    sequence as the snooker rack, apex on the foot spot (0.5, 0.75), every
    position accepts any of "1".."15" (ФБСР free arrangement), cue at
    (0.5, 0.23) behind the head string; one shared function mapped for all 4
    GameTypes in `_game_rack_map` (identical equipment across disciplines).
  - Persisted `/home/z/my-project/scripts/verify_rack.py` (reusable rack
    verification with vectorized overlap checks).
- **What was verified (command → result)**
  - `get_ruleset(...)` for all 9 GameTypes → correct class for each;
    `__abstractmethods__` empty for the 4 Russian classes (ABC-complete).
  - `BallParams.default(gt)` / `Cue.from_game_type(gt)` /
    `default_specs_from_game_type(gt)` for the 4 new types → (m=0.255,
    R=0.0335) / (M=0.62, len=1.58, model="cue") / (3.7 × 1.8); EIGHTBALL
    regression → unchanged pool values.
  - `python /home/z/my-project/scripts/verify_rack.py` → ALL CHECKS PASSED for
    all 4 types: 16 balls, in-bounds, min gap ≈ 67.03 mm ≥ 2R, apex on foot
    spot ≤ 0.032 mm, cue in head quarter.
  - Existing-game rack smoke test → EIGHTBALL 16, NINEBALL 10, THREECUSHION 3,
    SNOOKER 22, SUMTOTHREE 2 balls (layouts change regression-free).
  - `python -m pytest -q` (full repo suite) → **2302 passed, 18 skipped** in
    46.7 s.
  - `uvx ruff check` + `format --check` (6 touched files) → clean after one
    auto-fix (`__all__` ordering).
- **Decisions / findings of note**
  - In this codebase version the ball position accessor is `ball.xyz`
    (ndarray [x, y, z], z = R at rest); `Ball` has no `rvw` attribute —
    relevant for Steps 5–9 when adapting older respot/rack idioms.
  - `get_rack()` does not forward arbitrary kwargs (e.g. `seed`) to rack
    functions — Step 11 fuzzing should seed `np.random` directly.
  - Shared rack function across the four disciplines is safe because
    `BallParams.default()` resolves identically for all four.
- **Outcome:** Step 4 DONE. Stopped before Step 5 per protocol; awaiting
  continuation signal.

### [5] Free Pyramid (Свободная пирамида) implementation — DONE

- **Date/time (Europe/Moscow):** 2026-10-29 14:15–16:15 MSK
- **Artifact plan for this step:** 1/4 module foundation (constants, reason
  taxonomy, shared state-extraction helpers) → 2/4 legality & constraint
  machinery (`build_shot_info`, `initial_shot_constraints`,
  `next_shot_constraints`) → 3/4 `respot_balls` + `copy()` → 4/4 step
  verification (scripted scenarios on real systems) + `RULES_DEVIATIONS.md`
  entries + step log closure.
- **Verified rule points (Free Pyramid, «Свободная пирамида»/«Американка»)**
  — sourced from the official rule texts (Ministry of Sport order № 942 of
  2015-10-12, rev. № 740 of 2017-08-11; International Pyramid Confederation
  rules of 2006-01-01; cross-checked against fbsrf.ru / ebc-billiard.com /
  bcpolygon.ru transcripts):
  - **Race target:** first to **8 points** (NOT 71 — 71 is *Classic* only;
    the master task's "race to 71" is hereby corrected per discipline).
  - **Scoring:** every ball legally pocketed = 1 point; all balls potted on
    a legal stroke count for the shooter; no ball/pocket call required.
  - **Свояк:** potting the cue ball after it contacts an object ball is a
    legal stroke and scores 1 point; the potted cue ball is respotted per
    п. 25 (задняя отметка / spotting line) — "выставляется на общих
    основаниях". Cue ball potted WITHOUT contacting an object ball = foul
    (covered by «биток не коснулся ни одного прицельного шара»).
  - **Правильное завершение удара (п. 20):** after cue-object contact, some
    ball must (1) be potted, OR (2) bounce off a cushion then touch another
    cushion / drive a ball to another cushion / touch a ball frozen to
    another cushion, OR (3) cross the central line then touch a cushion /
    drive a ball to a cushion / touch a ball frozen to a cushion, OR
    (4) bounce off a cushion then cross the central line (or roll a ball
    across it). Otherwise — штраф.
  - **Начальный удар (п. 12, break):** from the house; legal if a ball is
    potted (свояк on the break also qualifies), OR ≥ 3 distinct object balls
    touch cushions, OR 2 distinct object balls touch cushions AND ≥ 1 object
    ball crosses the central line.
  - **Foul penalty:** +1 point to the opponent, AND the opponent removes any
    ball of their choice from the table as a «штрафной шар» onto their shelf
    (it counts toward their score; taken after all illegally potted / jumped
    balls are respotted). Turn passes.
  - **Выставление шаров (п. 25):** illegally potted and jumped balls are
    respotted at the задняя отметка; several balls go on the spotting line
    (задняя отметка → задний борт), as close as possible but not touching;
    occupied spot → closest free position along the line; no room between
    spot and cushion → continue the line toward the table center.
  - **Cue-ball selection:** official rules allow choosing ANY ball as биток
    before any stroke (п. 25.4 extends this to respotted balls). NOT
    implemented — fixed colored cue ball per master spec and п. 11.2; to be
    logged in `RULES_DEVIATIONS.md` (deviation #3, artifact 5/4).
- **Decisions of note**
  - Race target `FREE_TARGET_SCORE = 8` is a module constant with the
    correction documented in its docstring and here; README will restate it.
- **What was done (artifact 1/4)**
  - `pooltool/ruleset/russian_pyramid.py`: module docstring status →
    IN PROGRESS; imports (`ruleset.utils` helpers via the same submodule
    import idiom as `eight_ball.py` — circular-import safe);
    `CUE_BALL_ID = "cue"`; `FREE_TARGET_SCORE = 8`; `FreePyramidReason`
    StrEnum (NONE / LEGAL / LEGAL_BREAK / NO_CONTACT / ILLEGAL_COMPLETION /
    ILLEGAL_BREAK, mapping to п. 20 / п. 12 clauses); shared pure helpers
    `object_ball_ids`, `live_object_ball_ids`, `potted_ball_ids`,
    `potted_object_ball_ids`, `is_cue_ball_potted`, `first_object_contact`.
    The 4 ruleset classes remain stubs at this artifact.
  - Persisted `/home/z/my-project/scripts/verify_step5.py` (grows across
    5/1–5/4).
- **What was verified (command → result)**
  - `uvx ruff check` + `ruff format --check` on the module and script →
    clean.
  - `python /home/z/my-project/scripts/verify_step5.py` → foundation OK
    (6 reason members, numeric-order object ids, stubs intact) → ALL CHECKS
    PASSED.
  - `python -c "import pooltool.ruleset.russian_pyramid"` → OK.
  - `python -m pytest -q tests/test_russian_pyramid.py` → 16 passed
    (equipment regression green).
- **What was done (artifact 2/4)**
  - `pooltool/ruleset/russian_pyramid.py`: added the Free Pyramid legality
    machinery and implemented 3 of 5 `RussianFreePyramid` methods:
    - `first_contact_time` — time of the first cue→object BALL_BALL event;
    - `cushion_contacts(shot, after=...)` — per-ball set of distinct cushion
      segment IDs from BALL_LINEAR_CUSHION / BALL_CIRCULAR_CUSHION events,
      optionally restricted to contacts after the first contact;
    - `crossed_center_line(shot, after=...)` — vectorized (NumPy
      `searchsorted` + boolean side test over `BallHistory.rvws`) detection
      of balls whose trajectory crosses the central line (y = l/2);
    - `is_legal_break_shot` — п. 12 (pot / ≥3 object balls on cushions /
      2 on cushions + 1 crossing the central line; свояк on the break
      qualifies);
    - `satisfies_completion_requirements` — п. 20 (any ball potted / a ball
      on ≥2 distinct cushions / a ball on a cushion and across the central
      line in either order);
    - `evaluate_free_shot` — NO_CONTACT → ILLEGAL_BREAK/LEGAL_BREAK →
      ILLEGAL_COMPLETION/LEGAL;
    - `build_shot_info` — legal: shooter += len(all potted incl. свояк);
      foul: opponent += 1 (штрафной шар point); turn continues iff legal
      and ≥1 ball potted; game over at ≥8 (either player); winner = leader;
    - `next_shot_constraints` — NONE ball-in-hand, no call, hittable = live
      object balls; BEHIND_LINE + movable cue iff cue ball ended off table
      (foul scratch);
    - `initial_shot_constraints` — BEHIND_LINE, hittable = all 15, no call.
  - `scripts/verify_step5.py`: extended with constraint checks, a synthetic
    center-line crossing test (real rack balls, hand-built `BallHistory`
    rows, cutoff semantics), and a real-system integration check via
    `pt.System.example()` + `pt.simulate`.
- **What was verified (command → result)**
  - `uvx ruff check` + `format --check` (module + script) → clean (one
    missing `by_type` import caught by F821 and fixed; formatter reflowed
    3 signatures).
  - `python /home/z/my-project/scripts/verify_step5.py` → foundation OK
    (2/5 free methods still stubbed — correct), constraints OK, crossing
    semantics OK (cutoff before/after the crossing rows), real system OK:
    first contact t=0.331 s, cushion contacts {cue: 2, "1": 1}, example
    shot judged LEGAL (potted), no-contact stub judged NO_CONTACT foul →
    ALL CHECKS PASSED.
  - `python -m pytest -q tests/test_russian_pyramid.py` → 16 passed.
- **Interpretation decision (to formalize in RULES_DEVIATIONS.md at 5/4):**
  foul penalty = opponent +1 point, embodied by the «штрафной шар» removed
  from the table to the opponent's shelf (consistent with «штраф в размере
  одного шара» and shelf-based scoring; the ebc/IPC phrasing "along with
  one point added" is read as the same single point). Penalty-ball choice
  in autonomous simulation: deterministic policy to be implemented in
  artifact 3/4 (`respot_balls`).
- **What was done (artifact 3/4)**
  - `pooltool/ruleset/russian_pyramid.py` — respot machinery + the 2
    remaining `RussianFreePyramid` methods (all 5 now implemented):
    - New module constants: `REAR_SPOT_FRACTION = 0.75` (задняя отметка on
      the longitudinal centerline, matches the rack seed),
      `HOUSE_LINE_FRACTION = 0.25` (линия дома through the передняя
      отметка), `HOUSE_DEFAULT_Y_FRACTION = 0.23` (default scratch spot,
      matches the break spawn point), `_RESPOT_GAP = 1e-3` (п. 25.2
      "as close as possible, but not touching" clearance);
    - `balls_off_table` (state-based «выскочившие» object balls),
      `is_cue_ball_jumped` (event-based, BALL_OFF_TABLE);
    - `spot_line_position` — п. 25 placement scan on the longitudinal
      centerline: задняя отметка → slots toward the rear rail (one diameter
      + gap apart) → if the mark-to-rail segment is full, continuation
      toward the table center; explicit RuntimeError if the line is
      exhausted (unreachable, kept honest);
    - `house_default_position` — scratch placement scan from the break
      spawn point toward the front rail; head-ward scanning only (the
      default spot sits < 1 slot below the house line, so no admissible
      slot can exist between them — first draft's line-ward leg was dead
      code, caught by the verification script and removed);
    - `_sync_history` — appends the post-respot state to `ball.history` so
      history-based helpers (`live_object_ball_ids` reads
      `history[-1]`) stay consistent between `respot_balls` and the next
      `simulate` (which resets histories); `respot_on_spot_line`,
      `place_cue_ball_in_house` compose `ruleset.utils.respot` + sync;
    - `nearest_pocket` / `remove_penalty_ball` — «штрафной шар» removal:
      deterministic policy removes the live object ball **closest to any
      pocket center** (the pot the incoming opponent denies the shooter),
      ties → lowest number; ball marked pocketed at the nearest pocket
      center (pooltool's canonical out-of-play representation for the
      opponent's shelf); returns the ID or None;
    - `_copy_shot_constraints` helper (mutable lists rebuilt);
    - `respot_balls` — ordered administration per п. 22/25: (1) cue ball
      off table → legal («свояк») = spot line, foul = house default;
      (2) object balls: foul-potted («неправильно забитые») respotted,
      jumped respotted regardless of legality, ascending numeric order,
      first onto the mark; (3) штрафной шар removed **after** all respots,
      skipped when the game is already over;
    - `next_shot_constraints` (refinement of 2/4): scratch detection moved
      from "cue state off table" to event-based `is_cue_ball_potted` /
      `is_cue_ball_jumped` gated on `not shot_info.legal` — required
      because `respot_balls` now re-places the ball before constraints are
      built; a legally respotted свояк is correctly played as it lies;
    - `copy()` — real copy following the `nine_ball.py` idiom (deep-enough
      bookkeeping: score Counters deep-copied, ShotInfo evolved with a
      copied Counter, ShotConstraints lists rebuilt, log copied; players
      shared by reference as identity objects; fresh games without
      `shot_info` copy cleanly).
  - `scripts/verify_step5.py` — extended with `check_respot_machinery`
    (exact slot assertions for both scans incl. center-ward leg and packed
    RuntimeError paths, real-rack respot + history sync, penalty-ball
    removal, hand-built BALL_OFF_TABLE events), `check_svojyak_respot`
    (legal cue pot → exact mark / one-slot fallback, no penalty on legal
    strokes), `check_scratch_integration` (real simulated Russian-table
    scratch: dead-straight middle-pocket pot, no object contact →
    NO_CONTACT foul → full `process_and_advance` pipeline), and
    `check_copy` (independence + fresh-game safety).
- **What was verified (command → result)**
  - `uvx ruff check` + `ruff format` (module + script) → clean (script
    reformatted once).
  - `python /home/z/my-project/scripts/verify_step5.py` → foundation OK
    (0/5 free methods stubbed), constraints OK, crossing OK, real system
    OK, respot machinery OK, свояк respot OK, scratch integration OK
    (real sim: cue potted middle pocket, no contact → NO_CONTACT, opponent
    +1, cue at house default, штрафной шар = ball "9" (closest-to-pocket
    policy), BEHIND_LINE + 14 hittable, turn advanced), copy OK → ALL
    CHECKS PASSED.
  - `python -m pytest -q tests/test_russian_pyramid.py` → 16 passed.
  - `python -m pytest -q tests/test_layouts.py` → 21 passed (geometry
    regression insurance).
- **Decisions of note (3/4)**
  - Deterministic scratch placement: break spawn point
    (w/2, 0.23·l), scanning head-ward; house bound = ball edge inside the
    house line (y ≤ 0.25·l − R).
  - Deterministic штрафной шар policy: closest-to-pocket live object ball,
    lowest number on ties (a thinking opponent denies the easiest pot);
    removed after all respots; skipped on game-over shots.
  - Respot representation: state + history synced; penalty ball sits at
    the nearest pocket center with `pocketed` state (no `pocket.add` —
    the pocket's own `contains` list stays event-faithful).
  - **Discovered legality gap (logged for 5/4):** jumped balls
    («выскочившие», BALL_OFF_TABLE) are respotted per п. 25 by
    `respot_balls`, but the п. 20/п. 12 legality predicate does not yet
    treat a jump as a foul (общие правила: выскочивший биток/прицельный
    шар = штраф). To be fixed or formally deviated in artifact 4/4.
- **What was done (artifact 4/4) — step closure**
  - `pooltool/ruleset/russian_pyramid.py`:
    - **Jump-foul gap fixed (implemented, not deviated):** new
      `FreePyramidReason.JUMPED_BALL` member and event-based
      `jumped_ball_ids` helper (the BALL_OFF_TABLE detector only fires for
      balls that genuinely left the surface — a dropping ball gets the
      earlier, higher-priority BALL_POCKET event — so no ball can be
      flagged potted and jumped); `evaluate_free_shot` now fouls any stroke
      with a jump, break included, ordered after NO_CONTACT and before the
      п. 12/п. 20 branches. `respot_balls` docstring's "cue jump the
      predicate did not catch" caveat removed (the predicate now catches
      it); module docstring status updated (Free Pyramid fully
      implemented).
  - `RULES_DEVIATIONS.md` — entries #3 (fixed colored cue ball vs
    player-selectable биток), #4 (п. 20 driven-ball/frozen-ball sub-clauses
    omitted, conservative direction), #5 (autonomous-play determinism:
    closest-to-pocket штрафной шар + break-spawn scratch default; +1-point
    embodiment interpretation formalized here as decided in 2/4).
  - `scripts/verify_step5.py` — closure scenarios:
    `check_jump_foul` (object-ball and cue-ball jumps via hand-built
    BALL_OFF_TABLE events: reason precedence over break/completion,
    build_shot_info foul scoring, state-off-table ball respotted exactly
    onto the mark, penalty removal), `check_legal_completion_scenario`
    (real simulated п. 20 clause 2a: ball "2" to two distinct cushions,
    no pot → legal, turn passes, no respot/penalty, hittable ("1", "2")),
    `check_break_scenario` (real simulated break from the house at the
    rack apex: LEGAL_BREAK via 5 cushioned object balls, scoring = potted
    count, turn-over semantics).
  - Scenario-tooling findings (recorded for Steps 6–11): `Cue.phi` is in
    **degrees** (0 = +x, 90 = toward the foot rail) — use
    `pt.aim.at_ball(...)` rather than hand-computed radians; `get_rack`
    jitters positions (~1e-5) and randomizes rack arrangement per call, so
    scenario asserts must be tolerance-based; dead-straight full-ball pots
    in this physics engine always scratch the cue ball — legal-pot test
    fixtures should use cut/two-cushion geometry or the break instead.
- **What was verified (command → result)**
  - `uvx ruff check` + `ruff format --check` (module + script) → clean.
  - `python /home/z/my-project/scripts/verify_step5.py` → all 11 checks
    green: foundation (7 reasons, 0/5 stubs), constraints, center-line
    crossing, real 8-ball example system, respot machinery, свояк respot,
    scratch integration, copy, jump foul, legal completion, break → ALL
    CHECKS PASSED.
  - `python -m pytest -q tests/test_russian_pyramid.py
    tests/test_layouts.py` → 37 passed.
- **Outcome:** Step 5 **DONE** — `RussianFreePyramid` implements all five
  Ruleset methods with п. 12/п. 20/п. 22/п. 25 fidelity, verified on real
  simulated systems; deviations #3–#5 logged. Pausing per protocol;
  awaiting `NEXT` for Step 6 (Free Pyramid test suite: ≥ 10 scripted
  scenarios, `pytest tests/test_russian_pyramid.py -k free` green).

### [6] Free Pyramid test suite — DONE

- **Date/time (Europe/Moscow):** 2026-10-29 15:35–16:00 MSK
- **What was done**
  - `tests/test_russian_pyramid.py` — appended the Step 6 Free Pyramid
    scenario suite: **19 tests** in 5 classes (all selectable via
    `pytest -k free`; the 16 Step 3–4 equipment tests are untouched):
    - `TestFreePyramidBreak` (2): initial break constraints grant
      BEHIND_LINE house ball-in-hand with all 15 balls hittable and no call;
      real-simulated full-rack break (V0 = 9 at the rack apex) is judged
      LEGAL_BREAK, scores `len(potted)` (свояк included), and the breaker
      continues iff something was pocketed.
    - `TestFreePyramidLegality` (6, synthetic hand-built events on real
      unsimulated Systems): no contact is a foul on any stroke;
      contact-without-completion fouls both as п. 20 (ILLEGAL_COMPLETION)
      and as п. 12 (ILLEGAL_BREAK); break legal via 3 cushioned object
      balls; break with 2 cushioned balls flips ILLEGAL→LEGAL exactly when
      one of them crosses the central line (history-row fixture);
      break legal via a potted ball; a jumped ball («выскочивший»)
      fouls even when another ball was potted.
    - `TestFreePyramidScoring` (5, synthetic): two legal pots score +2 and
      continue the turn (legally potted balls stay pocketed — п. 25 respots
      fouls only); «свояк» scores +1, continues the turn, and the cue ball
      is respotted exactly onto the задняя отметка with ordinary
      (non-ball-in-hand) constraints; a no-contact foul awards the opponent
      +1, passes the turn, and the штрафной шар is removed; reaching
      FREE_TARGET_SCORE = 8 ends the game with the correct winner; a foul
      that lifts the opponent to 8 ends the game **without** removing the
      штрафной шар (game-over guard).
    - `TestFreePyramidRealShots` (3, full physics): dead-straight scratch
      into the right middle pocket with no object-ball contact → NO_CONTACT
      foul with the full administration chain (opponent +1, cue ball placed
      at the deterministic default house spot (w/2, 0.23·l), штрафной шар =
      the live ball closest to a pocket center, BEHIND_LINE ball-in-hand,
      hittable minus the removed ball, turn advanced); dead-straight pot of
      an object ball where the cue ball follows it in → legal «свояк» worth
      2 points with the cue respotted onto the free mark; п. 20 clause 2a
      completion (struck ball touches two distinct cushions, nothing
      potted) → legal, 0–0, turn passes, opponent plays the table as it
      lies.
    - `TestFreePyramidRespot` (3): a foul with two illegally potted balls
      respots them in ascending order (first exactly on the задняя отметка,
      second one diameter + `_RESPOT_GAP` behind it toward the rear rail)
      before the штрафной шар is taken from the remaining live balls; a
      jumped cue ball on a foul is placed in the house with
      BEHIND_LINE granted and `is_cue_ball_jumped` true; `copy()` returns a
      fully independent game state (deep-enough bookkeeping, shared
      `players`, fresh-game safe, mutation isolation both ways).
  - Test tooling notes: synthetic shots are real `pt.System` objects with
    hand-built `Event`s appended (BALL_BALL / BALL_LINEAR_CUSHION /
    BALL_POCKET / BALL_OFF_TABLE) and seeded `BallHistory` rows, so
    history-reading helpers (`live_object_ball_ids`) and event-reading
    helpers see a consistent end-of-shot view; each foul scenario keeps ≥ 1
    live object ball besides any penalty candidates (every mid-game foul
    removes one ball); `Pocket.center` is a 3-vector — slice `[:2]`.
- **What was verified (command → result)**
  - `uvx ruff check tests/test_russian_pyramid.py` → clean (after initial
    run caught nothing; one `ValueError` unpacking 3-vector
    `Pocket.center` and one missing-штрафной-шар fixture bug found by
    pytest and fixed).
  - `uvx ruff format tests/test_russian_pyramid.py` → 1 file reformatted
    (line-length reflows), then `--check` clean; repo-wide
    `uvx ruff check .` + `ruff format --check .` → 260 files formatted,
    all checks passed.
  - `python -m pytest -q tests/test_russian_pyramid.py -k free` →
    **19 passed** in 3.2 s.
  - `python -m pytest -q tests/test_russian_pyramid.py` → **35 passed**
    (16 equipment + 19 Free Pyramid).
  - `python /home/z/my-project/scripts/verify_step5.py` → ALL CHECKS
    PASSED (Step 5 regression intact).
  - `python -m pytest -q tests` → **2321 passed, 18 skipped** in 9.2 s
    (2302 pre-existing + 19 new).
- **Outcome:** Step 6 **DONE** — Free Pyramid behaviour is pinned by 19
  scenario tests covering every item of the step plan (legal/illegal
  strokes, «свояк», break, cue-ball-in without contact, score progression,
  turn switching, game end, respot). Pausing per protocol; awaiting `NEXT`
  for Step 7 (Combined Pyramid «Комбинированная / Московская»:
  implementation + ≥ 10 tests, same scheme).


### [7] Combined Pyramid (Комбинированная / Московская) — DONE

- **Date/time (Europe/Moscow):** 2026-10-29 16:00–16:10 MSK
- **Verified rule points (Combined Pyramid)** — sourced from the official
  ФБСР rules page (fbsrf.ru/node/185, «Комбинированная пирамида»), cross-
  checked against bc-champion.ru, probilliard.by and spb.weekend-billiard.ru
  transcripts:
  - **Race target:** first to **8 points** (п. 1 «Цель игры» — same as Free;
    the often-quoted 20/15-point figures belong to other variants/leagues).
  - **Свояк (п. 5.1/5.2):** the cue ball may be pocketed off any object
    ball. In exchange the **shooter** removes one object ball of their
    choice onto their shelf (+1) and continues with a **premium stroke
    from the house** (п. 21) — unlike Free, where the cue ball is respotted
    on the spotting line and play continues as it lies.
  - **п. 21 house strokes:** the cue ball may be placed anywhere in the
    house (not on the line, not touching balls); the stroke must first
    contact a ball standing **outside the house**; if all object balls
    stand in the house, the stroke is played from the opposite side.
  - **Scoring (п. 6):** each legally potted ball = 1 point; foul = +1 to
    the opponent. **Fouls (п. 7):** opponent takes the «штрафной шар»
    after all respots; a fouled scratch/jump is followed by the opponent's
    penalty stroke from the house. **Respotting (п. 8):** п. 25.
  - Break (п. 11/п. 12), completion (п. 5.4 → п. 20), no call shot (п. 5.3)
    — shared with Free Pyramid.
- **What was done (implementation)**
  - `pooltool/ruleset/russian_pyramid.py`:
    - `COMBINED_TARGET_SCORE = 8` (docstring cites ФБСР п. 1);
    - `CombinedPyramidReason` StrEnum — mirrors Free plus
      `HOUSE_FIRST_CONTACT` (п. 21 violation);
    - `violates_house_contact(shot)` — a stroke with the cue ball standing
      inside the house at start must first contact a ball outside the
      house; reads the contacted ball's position at the last history row
      at-or-before the first-contact time (exact for the first-contacted
      ball, which is stationary until contact; robust for dense simulated
      and sparse synthetic histories). The all-balls-in-house case lifts
      the restriction (п. 21 opposite-side exception);
    - `evaluate_combined_shot(shot, is_break)` — NO_CONTACT → JUMPED_BALL →
      HOUSE_FIRST_CONTACT (non-break) → п. 12/п. 20 (reuses the shared
      predicates);
    - `RussianCombinedPyramid` — all 5 Ruleset methods:
      `build_shot_info` (legal: shooter += potted object balls, +1 свояк
      compensation; foul: opponent +1; shooter continues iff a productive
      legal stroke — object pot or свояк; game over at 8); 
      `next_shot_constraints` (any potted/jumped cue ball → BEHIND_LINE
      house stroke: premium after legal свояк, penalty after foul;
      otherwise NONE); `initial_shot_constraints` (break from house);
      `respot_balls` (cue re-enters from the house in both свояк and foul
      cases; jumped object balls always respotted, illegally potted on
      fouls; свояк compensation ball and foul штрафной шар removed after
      respots, both skipped on game-over strokes); `copy()` (Free idiom).
  - `RULES_DEVIATIONS.md` — entries **#6** (deterministic свояк
    compensation-ball policy: live ball closest to a pocket center, ties →
    lowest number; symmetric with #5) and **#7** (п. 21 house placement
    default = break spawn point; opposite-side exception modeled as
    dropping the restriction instead of mirrored geometry).
- **What was done (tests, 15 in 5 classes, `-k combined` selectable)**
  - `TestCombinedPyramidBreak` (2): break constraints; real full-rack break
    (LEGAL_BREAK, score = object pots + свояк flag, premium-house-stroke
    constraints granted on a свояк break).
  - `TestCombinedPyramidLegality` (4): no-contact and jumped-ball fouls;
    house stroke contacting an inside ball → HOUSE_FIRST_CONTACT foul
    (opponent +1); the same stroke with outside first contact completes
    legally via п. 20 clause 2a and passes the turn; all-balls-in-house
    lifts the п. 21 restriction (falls through to ILLEGAL_COMPLETION).
  - `TestCombinedPyramidScoring` (4): object pot = +1, continues from the
    position, NO compensation ball (contrast with свояк); pure «свояк» =
    +1, deterministic ball removal, cue in house at (w/2, 0.23·l),
    BEHIND_LINE; «свояк» + object pot = +2 with one removal; foul =
    opponent +1, штрафной шар removed, turn passes, no ball-in-hand
    without a scratch.
  - `TestCombinedPyramidEndgame` (3): reaching 8 ends the game (winner,
    no shelf balls taken on a legal non-свояк stroke); foul lifting the
    opponent to 8 ends the game WITHOUT the штрафной шар; `copy()`
    independence.
  - `TestCombinedPyramidRealShots` (2): real simulated straight pot with
    the cue following in (свояк: +2, one ball removed, house re-entry);
    real simulated scratch without contact (full foul administration).
- **Bugs found and fixed during verification**
  - `violates_house_contact` originally read the contacted ball's position
    at the first history row **at-or-after** the contact time — for a
    potted ball that row is the pocket position (false п. 21 violation on
    sparse synthetic histories). Fixed to the last row at-or-before t0
    (exact for a stationary-until-contact ball).
  - Real-sim fixture bug: ball "2" placed 5 cm from the cue ball's start
    (< 2R overlap) crashed the quartic collision solver; repositioned off
    the pot line.
- **What was verified (command → result)**
  - `uvx ruff check` + `ruff format` (module + tests) → clean; repo-wide
    `ruff check .` + `ruff format --check .` → all clean (260 files).
  - `python -m pytest -q tests/test_russian_pyramid.py -k combined` →
    **15 passed** in 3.4 s.
  - `python -m pytest -q tests/test_russian_pyramid.py` → **50 passed**
    (16 equipment + 19 Free + 15 Combined).
  - `python /home/z/my-project/scripts/verify_step5.py` → ALL CHECKS
    PASSED (Step 5 regression intact).
  - `python -m pytest -q tests` → **2336 passed, 18 skipped** in 10.0 s.
- **Outcome:** Step 7 **DONE** — `RussianCombinedPyramid` implements all
  five Ruleset methods with ФБСР fidelity, including the Combined-specific
  «свояк» compensation and п. 21 house-stroke restriction; deviations #6–#7
  logged. Pausing per protocol; awaiting `NEXT` for Step 8 (Dynamic
  Pyramid «Динамичная / Невская»: implementation + ≥ 10 tests, same
  scheme).

### [8] Dynamic Pyramid (Динамичная / Невская) — DONE

- **Date/time (Europe/Moscow):** 2026-10-29 16:21 MSK
- **Verified rule points (Dynamic Pyramid)** — sourced from the official
  rule text («Динамичная пирамида», IPC/ФБСР transcripts at
  duplet.news/ru/rules/pyramid/4212-pyr-dynamic-ru, cross-checked against
  the «Общие правила пирамиды» references used in Steps 5/7):
  - **Race target (п. 1):** first to **8 points** — same as Free/Combined
    (the task-reference "number scoring / 1-ball = 11 / race to 71" figures
    belong to *Classic* pyramid, confirmed on probilliard.by/bayconur.ru;
    not applicable here).
  - **Scoring (п. 9):** each correctly potted ball = 1 point; a foul adds
    +1 to the opponent's score when the «штрафной шар» is removed.
  - **«Свояк» (п. 5.1/5.2):** the cue ball may be pocketed off any object
    ball; in exchange the **shooter** removes one object ball of their
    choice onto their shelf (one point) and re-introduces the cue ball
    with a ball-in-hand stroke from **any point of the playing surface**
    (п. 6.1) — the Dynamic signature, vs Combined's house stroke.
  - **Introduction strokes («удар с руки», п. 6.4/6.5/6.6):** on any stroke
    played with ball in hand only object balls may be pocketed — a pocketed
    cue ball is a foul; an object ball falling alongside the cue ball is
    not counted and is respotted (п. 25), then the штрафной шар follows.
  - **Break (п. 4 → «Общие правила» п. 12/п. 13)**, completion (п. 5.4 →
    п. 20), no call shot (п. 5.3), respotting (п. 8 → п. 25) — shared with
    Free/Combined.
  - **Fouls (п. 7):** opponent removes the «штрафной шар» after all respots;
    if the cue ball was potted/jumped, the opponent re-introduces it with
    ball in hand from anywhere (п. 7.2a); otherwise plays as it lies
    (п. 7.3a). The pass-back options (п. 7.2b/п. 7.3b) are not modeled —
    deviation #8.
- **What was done (implementation)**
  - `pooltool/ruleset/russian_pyramid.py`:
    - `DYNAMIC_TARGET_SCORE = 8` (docstring cites п. 1 and the rule
      transcripts);
    - `DynamicPyramidReason` StrEnum — mirrors Free/Combined plus
      `IN_HAND_CUE_POT` (п. 6.4/6.5 violation on introduction strokes);
    - `evaluate_dynamic_shot(shot, is_break, is_in_hand)` — NO_CONTACT →
      JUMPED_BALL → IN_HAND_CUE_POT (only when the stroke was played with
      ball in hand) → п. 12/п. 20 (reuses the shared predicates); the
      in-hand flag is derived in `build_shot_info` from
      `self.shot_constraints.ball_in_hand == ANYWHERE`, which still holds
      the constraints of the stroke just played at evaluation time
      (verified against `Ruleset.process_shot`/`advance` ordering);
    - `RussianDynamicPyramid` — all 5 Ruleset methods:
      `build_shot_info` (legal: shooter += potted object balls, +1 свояк
      compensation; foul: opponent +1; shooter continues iff a productive
      legal stroke — object pot or свояк; game over at 8);
      `next_shot_constraints` (any potted/jumped cue ball → `ANYWHERE`
      table-wide ball-in-hand: the shooter's introduction stroke after a
      legal «свояк» (п. 6.1) or the opponent's stroke after a foul
      (п. 7.2a); cue ball stayed after a foul → `NONE` (п. 7.3a));
      `initial_shot_constraints` (break from house);
      `respot_balls` (cue re-entered at the deterministic default position
      in both свояк and foul cases; jumped object balls always respotted,
      illegally potted on fouls — including the п. 6.6 case; свояк
      compensation ball and foul штрафной шар removed after respots, both
      skipped on game-over strokes); `copy()` (Free/Combined idiom);
    - module docstring status updated (Free + Combined + Dynamic fully
      implemented).
  - `RULES_DEVIATIONS.md` — entries **#8** (п. 7.2b/7.3b pass-back options
    not modeled; deterministic option (a)) and **#9** (п. 6.1 default
    placement = break spawn point; п. 6.2 placement-touching foul N/A in
    autonomous simulation); entry **#6** scope extended to cover the
    Dynamic «свояк» compensation ball (same policy as Combined).
- **What was done (tests, 15 in 5 classes, `-k dynamic` selectable)**
  - `TestDynamicPyramidBreak` (2): break constraints (BEHIND_LINE, 15
    hittable, no call); real full-rack break (LEGAL_BREAK, score = object
    pots + свояк flag, `ANYWHERE` granted on a свояк break).
  - `TestDynamicPyramidLegality` (4): no-contact and jumped-ball fouls;
    the п. 6.4/6.5 in-hand cue-pot foul — the same stroke flips LEGAL
    («свояк») ↔ IN_HAND_CUE_POT exactly when the in-hand flag is set, with
    full foul administration (`ANYWHERE`, default cue placement, штрафной
    шар); an in-hand stroke pocketing an object ball is legal and scores;
    the п. 6.6 case (object ball falling alongside the cue ball on an
    in-hand stroke) — not counted, respotted onto the задняя отметка,
    штрафной шар from the remaining live balls.
  - `TestDynamicPyramidScoring` (4): object pot = +1, continues from the
    position, NO compensation ball; pure «свояк» = +1, deterministic ball
    removal, cue at the default position, `ANYWHERE`; «свояк» + object pot
    = +2 with one removal; foul with the cue staying on the table →
    opponent +1, штрафной шар removed, turn passes, NO ball-in-hand
    (п. 7.3a contrast).
  - `TestDynamicPyramidEndgame` (3): reaching 8 ends the game (winner, no
    shelf balls on a legal non-свояк stroke); foul lifting the opponent to
    8 ends the game WITHOUT the штрафной шар; `copy()` independence.
  - `TestDynamicPyramidRealShots` (2): real simulated straight pot with the
    cue following in («свояк»: +2, one ball removed, `ANYWHERE` re-entry);
    real simulated scratch without contact (full foul administration with
    `ANYWHERE`, contrasting Combined's `BEHIND_LINE`).
- **What was verified (command → result)**
  - `uvx ruff check pooltool/ruleset/russian_pyramid.py` + `ruff format` →
    clean (one reflow applied); `uvx ruff check tests/test_russian_pyramid.py`
    + `ruff format` → clean (one reflow applied).
  - `python -m pytest -q tests/test_russian_pyramid.py -k dynamic` →
    **15 passed** in 3.5 s.
  - `python -m pytest -q tests/test_russian_pyramid.py` → **65 passed**
    (16 equipment + 19 Free + 15 Combined + 15 Dynamic).
  - `python /home/z/my-project/scripts/verify_step5.py` → ALL CHECKS
    PASSED (Step 5 regression intact).
  - `uvx ruff check .` + `ruff format --check .` → all clean (260 files).
  - `python -m pytest -q tests` → **2351 passed, 18 skipped** in 10.1 s.
- **Decisions of note**
  - Introduction-stroke detection reads `self.shot_constraints.ball_in_hand`
    (the constraints under which the current stroke was played) rather than
    adding mutable game flags — consistent with the base-class update
    ordering (`process_shot` → `build_shot_info`/`respot_balls` → `advance`
    → `next_shot_constraints`) and requires no new state.
  - The свояк compensation in Dynamic scores +1 (embodied by the removed
    shelf ball) and the cue ball itself is NOT a direct point — mirrors the
    verified Combined reading of the identical п. 5.2 wording; the
    discipline's difference is purely the re-entry geometry (table-wide
    ball-in-hand vs the house) plus the п. 6.4/6.5 in-hand cue-pot ban.
  - Foul-scratch re-entry: the cue ball is placed at the deterministic
    default position (break spawn point) while `next_shot_constraints`
    grants `ANYWHERE` — the placement is merely where the ball rests when
    the player does not reposition; deviation #9.
- **Outcome:** Step 8 **DONE** — `RussianDynamicPyramid` implements all
  five Ruleset methods with ФБСР fidelity, including the table-wide
  ball-in-hand introduction strokes (п. 6) and the opponent's post-foul
  re-introduction (п. 7.2a); deviations #8–#9 logged, #6 scope extended.
  Pausing per protocol; awaiting `NEXT` for Step 9 (Classic Pyramid
  «Классическая»: implementation incl. called shots + ≥ 10 tests, same
  scheme).

### [9] Classic Pyramid (Классическая пирамида, 71 очко) — DONE

- **Date/time (Europe/Moscow):** 2026-10-29 16:39 MSK
- **Verified rule points (Classic Pyramid)** — sourced from the ФБСР/МФБС
  family rule transcripts (probilliard.by, bayconur.ru, sbsnsk.ru — the
  sbsnsk article explicitly references the ФБСР site and confirms the
  «свояк = штраф» reading; cross-checked against the «Общие правила
  пирамиды» text at sportbox.ru and the polkovnik-bayron transcript):
  - **Race target (п. 1):** first to **71 or more points** (the 51- and
    8-point «classic» variants in some libraries are league modifications).
  - **Scoring (п. 5.1):** each correctly potted ball = its number; the
    1-ball («единица»/«туз») = 11; total pool 130; **the last remaining
    object ball carries +10** regardless of its number (full pool 140).
  - **Called shots («заказ», п. 5.2/5.3/5.4):** before every stroke except
    the break the player declares a specific object ball AND pocket; when
    the called ball falls into the called pocket, **all** balls potted on
    the stroke count; an uncalled pot (or the called ball in a wrong
    pocket) is not a foul — the balls are respotted, no points, «игра
    продолжается на общих основаниях» (the turn passes per the general
    pot-→-continue principle).
  - **«Свояк» (п. 5.5):** pocketing the cue ball is a **foul** on any
    stroke (break included) — the classic game has no legal «свояк»
    (sbsnsk: «за каждого забитого свояка налагается штраф»); a fouled
    scratch/jump hands the opponent the penalty stroke from the house
    (п. 21).
  - **Foul penalty (п. 5.6):** every violation transfers **−5/+5 points**;
    Classic has **no «штрафной шар»** (the general rules п. 6 reserve the
    ball removal for Free/Combined/Dynamic). Offender scores may go
    negative; the transfer keeps the score sum constant.
  - **Break (п. 4 → п. 11/п. 12):** from the house, no call; п. 12.1(1)
    makes a correct break via «правильно забитые» balls — break pots score
    their number values (documented interpretation, textual grounding).
  - **Tie-break (п. 5.7):** at 70:70 (reachable only when the full 140
    pool is scored) the last potted ball returns to the задняя отметка,
    the next stroke is played from the house, and the game runs until a
    ball is potted or a foul (any pot/penalty then immediately produces a
    ≥71 leader).
  - **Rack (п. 3):** fixed arrangement — row 1: 4; row 2: 5, 6; row 3:
    7, 15, 8; row 4: 9, 14, 13, 10; row 5: 2, 1, 12, 11, 3.
  - **Variant note:** the Ukrainian ФБСУ «Русская классическая» treats a
    potted биток leniently (play from anywhere, no points); the ФБСР-family
    sources above were followed instead, per the task's ФБСР authority.
- **What was done (implementation)**
  - `pooltool/ruleset/russian_pyramid.py`:
    - `CLASSIC_TARGET_SCORE = 71`, `CLASSIC_ONE_BALL_VALUE = 11`,
      `CLASSIC_LAST_BALL_BONUS = 10`, `CLASSIC_FOUL_POINTS = 5` (docstrings
      cite the rule texts);
    - `ClassicPyramidReason` StrEnum — the shared taxonomy plus `CUE_POTTED`
      (п. 5.5), `HOUSE_FIRST_CONTACT` (п. 21) and `UNCALLED_POT` (п. 5.4,
      not a foul but unproductive);
    - helpers: `ball_value`, `last_remaining_object_ball` (exactly one live
      object ball at stroke start — the п. 5.1 bonus condition),
      `classic_pot_points`, `potted_ball_pocket_map` (BALL_POCKET events →
      ball→pocket), `called_ball_potted_as_ordered` (ball AND pocket must
      match; a missing call never honors);
    - `evaluate_classic_shot(shot, is_break, ball_call, pocket_call)` —
      NO_CONTACT → JUMPED_BALL → CUE_POTTED → п. 21 house restriction
      (position-based, same as Combined) → п. 12/п. 20 → call check
      (LEGAL vs UNCALLED_POT);
    - `RussianClassicPyramid` — all 5 Ruleset methods:
      `build_shot_info` (LEGAL/LEGAL_BREAK: shooter += classic_pot_points,
      continue after an honored call / after break pots; UNCALLED_POT: no
      points, turn passes; fouls: shooter −5, opponent +5, turn passes;
      game over at ≥71 either side; 70:70 forces turn_over=True — the
      deterministic lag replacement); `next_shot_constraints`
      (call_shot=True on every non-break stroke; BEHIND_LINE after a
      fouled scratch/jump and at 70:70; else NONE);
      `initial_shot_constraints` (break from the house, call_shot=False);
      `respot_balls` (cue re-placed in the house after a foul scratch AND
      at 70:70 even when it stayed on the table; foul-potted and jumped
      object balls respotted; UNCALLED_POT respots the stroke's pots; the
      70:70 LEGAL stroke respots the last potted ball onto the mark; **no
      ball is ever removed**); `copy()` (shared idiom);
    - module docstring status → all four disciplines fully implemented.
  - `pooltool/layouts.py` — extracted `_RUSSIAN_PYRAMID_JUMPS`; added
    `_RUSSIAN_CLASSIC_RACK_ORDER` (the п. 3 fixed arrangement in blueprint
    generation order), a `fixed_order` flag on `_get_russian_pyramid_rack`
    (singleton slot sets → deterministic assignment) and
    `_get_russian_classic_rack`; `RUSSIAN_PYRAMID_CLASSIC` remapped to it.
  - `RULES_DEVIATIONS.md` — entries **#10** (п. 5.7 lag → deterministic
    turn pass) and **#11** (last-ball bonus not awarded when the final two
    balls fall on one stroke); scopes of **#4** (п. 20 sub-clauses) and
    **#7** (house-stroke placement) extended to Classic, **#8** (pass-back)
    extended to Classic per the general rules п. 6.
- **What was done (tests, 18 in 5 classes, `-k classic` selectable)**
  - `TestClassicPyramidBreak` (2): break constraints (BEHIND_LINE, no
    call); real full-rack break (LEGAL_BREAK, score = Σ ball values of
    potted balls, breaker continues iff something was potted, next stroke
    requires a call).
  - `TestClassicPyramidLegality` (5): no-contact / jumped-ball /
    «свояк»-despite-honored-call fouls (п. 5.5 precedence over the call);
    house stroke contacting an inside ball (п. 21 foul, −5/+5); the same
    house stroke with an outside called pot is legal and scores 11;
    uncalled pot is not a foul (no points, respot onto the задняя
    отметка, turn passes); the called ball in the wrong pocket is
    UNCALLED_POT.
  - `TestClassicPyramidScoring` (5): called pot = ball value (8);
    1-ball = 11; correct call counts all pots on the stroke (8+3);
    last-ball bonus (+10 → 17); foul transfers 5 points with a negative
    offender score and NO ball removal.
  - `TestClassicPyramidEndgame` (4): reaching 71+ ends the game; a −5/+5
    foul crossing the target ends it (A 66→61, B 68→73); the 70:70
    tie-break respots the last potted ball exactly onto the mark, re-places
    the cue in the house, grants BEHIND_LINE with a call required and
    passes the turn; `copy()` independence.
  - `TestClassicPyramidRealShots` (2): real simulated dead-straight pot of
    the called ball with the cue following in → CUE_POTTED foul despite
    the honored call (−5/+5, respot, house penalty stroke); real simulated
    scratch without contact → NO_CONTACT, −5/+5, all 15 object balls stay
    on the table (no «штрафной шар»), BEHIND_LINE with a call required.
- **What was verified (command → result)**
  - `uvx ruff check` + `ruff format` on the module, layouts and tests →
    clean (2 SIM114 auto-suggestions applied by hand; formatter reflowed
    the test file once).
  - `python -m pytest -q tests/test_russian_pyramid.py -k classic` →
    **18 passed** in 3.5 s (one test-arithmetic bug in a fixture found by
    pytest and fixed: preset 3 → 3−5 = −2, not −5).
  - `python -m pytest -q tests/test_russian_pyramid.py` → **83 passed**
    (16 equipment + 19 Free + 15 Combined + 15 Dynamic + 18 Classic).
  - `python /home/z/my-project/scripts/verify_rack.py` → ALL CHECKS
    PASSED for all 4 disciplines (Classic: 16 balls, min gap 67.03 mm,
    apex on the mark; fixed arrangement verified row-by-row separately).
  - `python /home/z/my-project/scripts/verify_step5.py` → ALL CHECKS
    PASSED (Step 5 regression intact).
  - `uvx ruff check .` + `ruff format --check .` → all clean (260 files).
  - `python -m pytest -q tests` → **2369 passed, 18 skipped** in 10.0 s.
- **Decisions of note**
  - Break pots score their number values: grounded in п. 12.1(1) («один из
    шаров правильно забит в любую лузу» legalizes the break through
    correctly potted balls) plus the п. 5.1 scoring text; no source
    exempts the break from scoring.
  - UNCALLED_POT carries `legal=True` (it is not a violation) while being
    unproductive: scoring/respot logic keys on the reason, keeping the
    foul penalty exclusively on the −5/+5 path (п. 5.6).
  - The 70:70 tie is detected from the score alone (both == target − 1),
    reachable only when the full 140 pool is scored; the continuation
    stroke re-places the cue in the house even when it stayed on the
    table, and the lag is replaced by a deterministic turn pass
    (deviation #10).
  - The п. 21 house restriction is position-based (cue standing in the
    house at stroke start), identical to Combined — the discipline shares
    `violates_house_contact`.
- **Outcome:** Step 9 **DONE** — `RussianClassicPyramid` implements all
  five Ruleset methods with ФБСР fidelity, including called shots
  («заказ»: ball + pocket), number-based scoring with the 1-ball = 11 and
  the last-ball +10 bonus, the −5/+5 foul transfer with no «штрафной
  шар», the fixed п. 3 rack, and the 70:70 tie-break; deviations #10–#11
  logged, #4/#7/#8 scopes extended. All four disciplines are now fully
  implemented. Pausing per protocol; awaiting `NEXT` for Step 10
  (profiling & optimization: cProfile, vectorization, selective Numba;
  before/after results → Performance section).

### [10] Profiling & optimization — DONE

- **Date/time (Europe/Moscow):** 2026-10-29 17:05 MSK
- **What was done**
  - New benchmark harness `scripts/benchmark_step10.py` (persisted,
    re-runnable): per-discipline simulated break stroke, physics baseline,
    break/mid evaluation timing, full `process_and_advance` timing on
    restored ball snapshots, cProfile section, `--json` output; raw data
    in `scripts/step10_before.json` / `scripts/step10_after.json` /
    `scripts/step10_free.prof`.
  - Baseline profile (Free, break path): the `by_ball` closure was ~22%
    and `by_type` ~16% of evaluation time — the ruleset re-filtered
    `shot.events` with chained `pooltool.events.filter` closures up to
    ~12× per `process_and_advance` round, plus `by_time`'s O(n log n)
    sortedness re-check and `Event.ids` tuple construction per event.
  - Optimization: single-pass chronological event scan `_EventScan`
    (`pooltool/ruleset/russian_pyramid.py`) bucketing the first cue-ball
    contact (time + other ball), pockets + ball→pocket map, off-table
    balls and cushion contacts. Public helper signatures and semantics
    unchanged; `_judge_free` / `_judge_combined` / `_judge_dynamic` /
    `_judge_classic` (+ `_is_legal_break_shot`, `_satisfies_completion`,
    `_violates_house_contact`) operate on one shared scan, and each
    ruleset call scans events exactly once. `crossed_center_line` (already
    NumPy-vectorized) and the п. 25 spotting machinery stay as they were.
  - «Selective Numba» evaluated with `scripts/numba_eval_step10.py`: an
    njit `_is_free` kernel runs 435 ns/call vs. 2 960 ns/call pure Python
    (7×, dispatch included); NumPy variant 4 057 ns/call (vectorization
    loses at N ≤ 16). **Not applied**: the loop runs only a few times per
    respot (≤ ~30 µs/stroke) inside a ~0.2%-of-a-stroke path — first-call
    JIT latency and a hard numba dependency on every ruleset import are
    not justified. Numba remains in the physics quartic solver, where it
    already pays off.
- **What was verified (command → result)**
  - `python /home/z/my-project/scripts/benchmark_step10.py --json
    /home/z/my-project/scripts/step10_before.json` (pre-change) →
    eval@break 92.6–139.8 µs, eval@mid 160.3–271.6 µs, process
    275.9–332.6 µs; ruleset share 0.24–0.30% of a 108–130 ms stroke.
  - Same, post-change (`step10_after.json`) → eval@break 47.5–70.4 µs
    (−41…−66%), eval@mid 113.8–140.5 µs (−24…−50%), process 234.6–262.0 µs
    (−9…−29%); ruleset share 0.17–0.22% of a 105–144 ms stroke.
  - `uvx ruff check pooltool/ruleset/russian_pyramid.py` + `ruff format`
    → clean (1 reflow).
  - `python -m pytest -q tests/test_russian_pyramid.py` → **83 passed**
    in 4.1 s.
  - `python /home/z/my-project/scripts/verify_step5.py` → ALL CHECKS
    PASSED (Step 5 regression intact, including the real-system break:
    LEGAL_BREAK, potted=1, 7 cushioned object balls).
  - `python /home/z/my-project/scripts/verify_rack.py` → ALL CHECKS
    PASSED (all 4 disciplines, 16 balls, min gap ~67 mm).
  - `python -m pytest -q tests` → **2369 passed, 18 skipped** in 10.2 s —
    identical to the pre-change baseline (no behavioral drift).
  - `uvx ruff check .` + `ruff format --check .` → all clean (260 files).
- **Decisions of note**
  - Optimization target chosen by measurement: the ruleset was already
    ~0.25% of a stroke, so the deliverable is documented headroom plus
    removal of the one structural inefficiency (repeated full-list event
    filtering) without any semantic change. All 83 pyramid tests and the
    full 2369-test suite pass byte-identically (same pass/skip counts).
  - `cushion_contacts(after=...)` no longer raises on non-chronological
    event lists (the old `by_time` behavior): the engine guarantees
    chronology, no test or caller relied on the raise, and the per-event
    `time > after` comparison preserves the strict-after semantics
    exactly. Documented on `_EventScan`.
  - Numba rejected for ruleset paths with measured evidence (Performance
    section); recorded as an engineering decision rather than applied for
    its own sake. Not a rules deviation — `RULES_DEVIATIONS.md` unchanged.
- **Outcome:** Step 10 **DONE** — benchmark harness persisted, single-pass
  event scan landed (evaluation 20–66% faster, per-stroke ruleset share
  ~0.2%), all suites green, before/after recorded in the Performance
  section. Pausing per protocol; awaiting `NEXT` for Step 11 (full
  simulations & fuzzing: 1 complete frame per discipline headless + 500
  random shots per discipline; reports → PROGRESS.md).

---

## Recovery Log

### Workspace reset #2 + performance fixes re-applied (MSK 2026-10-30, 14:40)

The sandbox was reset again (`pooltool/` wiped); the surviving `/tmp` backup
zip predated the 2026-10-29 performance fixes, so after restoring, the two
lost edits were re-applied by hand:

```
python /home/z/my-project/scripts/restore_from_zip.py   # 1076 entries, probes OK
# re-applied pooltool/evolution/event_based/cache.py -> CollisionCache.invalidate hot path
# re-applied pooltool/ani/animate.py -> _warmup_system() + full-rack JIT warmup
uvx ruff check + format                                  # clean
uv sync --frozen
uv run pytest tests/test_russian_pyramid.py tests/ruleset tests/evolution -q
  -> 169 passed in 41.96s
uv run python /home/z/my-project/scripts/profile_break.py
  -> 3D break steady 74.9 ms; invalidate ~11 ms/shot (was 102 ms)
```

`scripts/make_project_zip.py` now excludes `.venv/` (28k files / ~1 GiB of
wheels were being archived uselessly); the refreshed backup is
`download/pooltool_russian.zip` (2153 files, 629.4 MiB, CRC-verified) and
**includes** the performance fixes. `scripts/restore_from_zip.py` now picks
the newest archive across `/tmp/my-project/download/` and `download/`.

**Pivot note:** development now continues on the web multiplayer port
(`../pyramid-web/PROGRESS.md`, steps 0–9). This library is frozen as the
physics/rules engine for that port. Desktop Panda3D rendering issues
#2 (table model), #3 (ball assets), #4 (aspect ratio) are superseded by the
Three.js frontend and will not be fixed here.
