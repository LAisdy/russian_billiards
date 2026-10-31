# RULES_DEVIATIONS.md — Russian Pyramid Multiplayer Web (`pyramid-web`)

Companion log to the web multiplayer port. It records every deliberate or
pragmatic deviation **introduced by the web architecture** (network play,
keyframe animation, browser rendering, lobby flow) relative to the official
rules of the Russian Billiards Federation (ФБСР) and relative to the
reference `pooltool` desktop implementation.

## Policy

1. **No silent deviations.** Any rule that is simplified, approximated, or
   omitted because of the web medium (e.g., referee judgment, physically
   declared shots, timing rules) must be logged here **before** the
   corresponding `PROGRESS.md` step is marked DONE.
2. Each entry records: rule area, official/desktop behavior, web-port
   behavior, and rationale.
3. **Ruleset-level deviations are NOT tracked here.** They live in the
   library's authoritative log:
   `/home/z/my-project/pooltool/RULES_DEVIATIONS.md` (11 entries:
   deterministic penalty-ball policies, house-stroke defaults, pass-back
   option, lag tie-break, last-ball bonus attribution, etc.). The web port
   inherits all of them unchanged, because it runs the same
   `russian_pyramid.py` rulesets server-side.

## Resolved by the web port

| Library deviation | Status in the web port |
|:--|:--|
| #1 — object balls rendered with American pool models (visual only) | **Resolved in Step 4:** Three.js renders plain white balls with black numbers 1–15 |
| #2 — no Russian table 3D model (`TableModelDescr.null()`) | **Resolved in Step 4:** Three.js builds a 12 ft × 6 ft (370 × 180 cm) table mesh with deep pockets from the `PocketTableSpecs` values |

## Deviation log (web-port-specific)

| # | Discipline | Rule area | Official / desktop behavior | Web-port behavior | Rationale | Added in step |
|:--|:-----------|:----------|:----------------------------|:------------------|:----------|:--------------|
| — | — | — | *(none yet — entries are added here as they arise, per the policy above)* | | | |

