# VENDORED pooltool — pyramid-web backend (Step 3)

The `pooltool` package in this directory is a vendored copy of the Russian
Pyramid-extended [pooltool](https://github.com/ekiefl/pooltool) library,
produced by `scripts/vendor_physics.py`. License: Apache-2.0 (`LICENSE.txt`
in this directory).

| | |
|:--|:--|
| Source repo | `/home/z/my-project/pooltool` |
| Source version | pooltool-billiards 0.6.0 |
| Source commit | `7632b1c66f19159741a4cfe48b23d18f079d9a87` |
| Vendored at | 2026-10-30T12:51:20Z |
| Files copied verbatim | 119 (all physics, rulesets, layouts) |
| Total Python files | 124 |
| Tree size | 682 KiB |

## Removed (Panda3D desktop stack — replaced by the Three.js frontend)

- `pooltool/ani/` — replaced by a stub that only provides `model_dir`
- `pooltool/interact.py`, `pooltool/main.py` — desktop entry points
- `objects/{table,ball,cue}/render.py`, `system/render.py` — Panda3D renderers
- `pooltool/models/**` — art assets (only the 4 ballset directories that
  `layouts.py` resolves at import time are kept, `conversion.json` only)
- `pooltool/logo/**`

## Replaced (glue `__init__` files; physics is never touched)

- `pooltool/__init__.py` — headless top-level API (drops `interact` /
  `ani.image` imports, which require Panda3D; pins `__version__`)
- `pooltool/system/__init__.py` — drops the `SystemRender` (Panda3D) export
- `pooltool/config/__init__.py` — drops desktop Settings/`loadPrcFileData`
  machinery; the headless stack only needs `pooltool/config/paths.py`
- `pooltool/ani/__init__.py`, `pooltool/ani/constants.py` — new stubs

## Patched (surgical, asserted string replacements)

- `pooltool/utils/__init__.py` — `panda_path()` loses the Panda3D `Filename`
  dependency (plain `str()`); the result was only consumed by Panda3D loaders

## Verification

`python scripts/vendor_physics.py --check` re-verifies that every vendored
file (minus the glue above) is byte-identical to the source repo. Step 3's
acceptance test additionally proves that the HTTP endpoint, the in-process
vendored copy, and the original repo produce identical simulation results for
a seeded Russian break.
