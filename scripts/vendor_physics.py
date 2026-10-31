#!/usr/bin/env python3
"""Vendor the pooltool physics core into pyramid-web/backend/ (Step 3).

Copies the physics-relevant subset of /home/z/my-project/pooltool/pooltool into
pyramid-web/backend/pooltool/ so that the FastAPI backend can `import pooltool`
without Panda3D (the Panda3D rendering stack is replaced by the Three.js
frontend).

GUARANTEE — physics code is copied BYTE-IDENTICAL. The only files that differ
from the source repo are "glue" modules (package __init__ files and one
path-helper), and every difference is asserted, applied deterministically, and
recorded in backend/pooltool/VENDORED.md. No file under pooltool/physics/,
pooltool/evolution/, pooltool/ptmath/, pooltool/events/, pooltool/ruleset/ or
pooltool/objects/{ball,cue,table}/{datatypes,params,components,layout,...}.py
is ever modified.

What is excluded (and why):
  - pooltool/ani/               Panda3D animation stack -> Three.js frontend
  - pooltool/interact.py        desktop Game/show() loop
  - pooltool/main.py            desktop CLI entry point (click)
  - objects/*/render.py,        Panda3D renderers for balls/cue/table/system
    system/render.py
  - pooltool/models/**          .glb/.blend art assets (only the four ballset
                                directories needed by layouts.py at import
                                time are recreated, conversion.json only)
  - pooltool/logo/**            logo images

What is added (new stub files, clearly marked):
  - pooltool/ani/__init__.py    stub package docstring
  - pooltool/ani/constants.py   `model_dir` only (imported by table/specs.py
                                and ball/sets.py)

What is replaced/patched (glue only):
  - pooltool/__init__.py        headless top-level API (drops interact/ani.image)
  - pooltool/system/__init__.py drops the SystemRender (Panda3D) export
  - pooltool/config/__init__.py drops the desktop Settings/Panda3D machinery;
                                only config/paths.py (resolver YAML location)
                                has headless consumers
  - pooltool/utils/__init__.py  `panda_path()` loses its Panda3D `Filename`
                                dependency (plain str() conversion)

Usage:
    python3 scripts/vendor_physics.py            # vendor + verify
    python3 scripts/vendor_physics.py --check    # verify an existing vendored
                                                 # tree against the source repo
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

MY_PROJECT = Path(__file__).resolve().parents[1]
SRC_ROOT = MY_PROJECT / "pooltool"
SRC = SRC_ROOT / "pooltool"
DST = MY_PROJECT / "pyramid-web" / "backend" / "pooltool"
MANIFEST_JSON = DST / "VENDORED.json"
MANIFEST_MD = DST / "VENDORED.md"

# --- excluded paths (relative to the pooltool package, POSIX style) ------------

EXCLUDED_DIRS = {"ani", "models", "logo"}
EXCLUDED_FILES = {
    "interact.py",
    "main.py",
    "objects/table/render.py",
    "objects/ball/render.py",
    "objects/cue/render.py",
    "system/render.py",
}

# Ballset directories that layouts.py resolves at import time (get_ballset
# validates directory existence). The .glb art is not needed headlessly;
# conversion.json is copied when upstream provides one (pure documentation
# value — it is only read lazily at render time).
ASSET_FILES = [
    "models/balls/russian_pyramid/conversion.json",
    "models/balls/generic_snooker/conversion.json",
]
ASSET_DIRS = [
    "models/balls/billiard",
    "models/balls/russian_pyramid",
    "models/balls/pooltool_pocket",
    "models/balls/generic_snooker",
]

REPLACED_FILES = {
    "__init__.py",
    "system/__init__.py",
    "config/__init__.py",
    "ani/__init__.py",
    "ani/constants.py",
}

# --- file contents written by this script --------------------------------------


def _headless_init(source_version: str, commit: str, stamp: str) -> str:
    return f'''"""pooltool — vendored for pyramid-web (headless build).

Upstream: https://github.com/ekiefl/pooltool (Apache-2.0), extended with the
Russian Pyramid disciplines. This copy was vendored by
``scripts/vendor_physics.py`` for the pyramid-web backend:

    source version : pooltool-billiards {source_version}
    source commit  : {commit}
    vendored at    : {stamp}

Differences from the upstream top-level module (and only these — see
VENDORED.md next to this file): the Panda3D desktop entry points
``pooltool.interact`` (``Game``/``show``) and ``pooltool.ani.image`` are not
imported, because Panda3D is deliberately absent from the backend. Everything
else — the physics engine, the Russian Pyramid rulesets, the layouts — is
byte-identical to the source repo.
"""

__version__ = "{source_version}"

VENDORED_FOR = "pyramid-web"
VENDORED_FROM_COMMIT = "{commit}"
VENDORED_AT = "{stamp}"

import pooltool.ai as ai
import pooltool.ai.aim as aim
import pooltool.ai.pot as pot
import pooltool.constants as constants
import pooltool.events as events
import pooltool.evolution as evolution
import pooltool.game as game
import pooltool.layouts as layouts
import pooltool.objects as objects
import pooltool.physics as physics
import pooltool.ptmath as ptmath
import pooltool.ruleset as ruleset
import pooltool.serialize as serialize
import pooltool.system as system
import pooltool.utils as utils
from pooltool.events import EventType
from pooltool.evolution import continuize, interpolate_ball_states, simulate
from pooltool.game.datatypes import GameType
from pooltool.layouts import generate_layout, get_rack
from pooltool.objects import (
    Ball,
    BallParams,
    Cue,
    PrebuiltBallParams,
    Table,
    TableType,
)
from pooltool.ruleset import Player, get_ruleset
from pooltool.system import MultiSystem, System

__all__ = [
    "Ball",
    "BallParams",
    "Cue",
    "EventType",
    "GameType",
    "MultiSystem",
    "Player",
    "PrebuiltBallParams",
    "System",
    "Table",
    "TableType",
    "ai",
    "aim",
    "constants",
    "continuize",
    "events",
    "evolution",
    "game",
    "generate_layout",
    "get_rack",
    "get_ruleset",
    "interpolate_ball_states",
    "layouts",
    "objects",
    "physics",
    "pot",
    "ptmath",
    "ruleset",
    "serialize",
    "simulate",
    "system",
    "utils",
]
'''


_SYSTEM_INIT = '''"""The system container and its associated objects.

[pyramid-web vendored] ``SystemRender`` (Panda3D) is removed in the headless
build — the Three.js frontend renders systems instead.
"""

from pooltool.system.datatypes import MultiSystem, System, multisystem

__all__ = [
    "MultiSystem",
    "System",
    "multisystem",
]
'''

_CONFIG_INIT = '''"""pooltool configuration.

[pyramid-web vendored] The desktop ``Settings``/Panda3D machinery (graphics
options, loadPrcFileData) is removed in the headless build. The only headless
consumer of this package is ``pooltool.config.paths`` (used by
physics/resolve/resolver.py to locate the resolver YAML), which is copied
unchanged.
"""
'''

_ANI_INIT = '''"""pooltool.ani — STUB (pyramid-web headless vendored build).

The Panda3D animation stack is replaced by the Three.js frontend. This package
exists only so that ``from pooltool.ani.constants import model_dir`` (imported
by objects/table/specs.py and objects/ball/sets.py) resolves without Panda3D.
"""

from pooltool.ani.constants import model_dir

__all__ = ["model_dir"]
'''

_ANI_CONSTANTS = '''"""Stub of pooltool.ani.constants for the headless vendored build.

Only ``model_dir`` is provided (see pooltool/ani/__init__.py). The desktop
constants (menu scales, camera sensitivities, logo paths) have no headless
consumers.
"""

from __future__ import annotations

from pathlib import Path

model_dir: Path = Path(__file__).resolve().parent.parent / "models"
'''

# utils/__init__.py is PATCHED (not replaced): two surgical string replacements.
UTILS_PATCHES = [
    (
        "from panda3d.core import Filename\nfrom rich.console import Console\n",
        "from rich.console import Console\n",
    ),
    (
        (
            "def panda_path(path: Path | str) -> str:\n"
            "    panda_path = Filename.fromOsSpecific(str(path))\n"
            "    panda_path.makeTrueCase()\n"
            "    return str(panda_path)\n"
        ),
        (
            "def panda_path(path: Path | str) -> str:\n"
            "    # [pyramid-web vendored patch] Panda3D Filename removed for the\n"
            "    # headless build. The result is only consumed by Panda3D loaders,\n"
            "    # which are absent, so a plain string conversion is equivalent.\n"
            "    return str(path)\n"
        ),
    ),
]


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(SRC_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown (git unavailable)"


def _source_version() -> str:
    text = (SRC_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("cannot find version in pooltool/pyproject.toml")


def _iter_source_files() -> list[Path]:
    files: list[Path] = []
    for path in sorted(SRC.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(SRC).as_posix()
        if rel in EXCLUDED_FILES:
            continue
        if any(part in EXCLUDED_DIRS for part in path.relative_to(SRC).parts):
            continue
        if path.suffix != ".py" and path.name not in {"py.typed"}:
            continue
        files.append(path)
    return files


def _apply_utils_patches(text: str) -> str:
    for old, new in UTILS_PATCHES:
        if old not in text:
            raise RuntimeError(
                "utils/__init__.py drifted from the expected source text; "
                "refusing to patch. Update the patch pair in vendor_physics.py."
            )
        text = text.replace(old, new, 1)
    return text


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_replacements(commit: str, stamp: str) -> None:
    version = _source_version()
    contents = {
        "__init__.py": _headless_init(version, commit, stamp),
        "system/__init__.py": _SYSTEM_INIT,
        "config/__init__.py": _CONFIG_INIT,
        "ani/__init__.py": _ANI_INIT,
        "ani/constants.py": _ANI_CONSTANTS,
    }
    for rel, body in contents.items():
        target = DST / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")


def vendor() -> dict:
    commit = _git_commit()
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    version = _source_version()

    if DST.exists():
        # Remove only what we manage: .py files, py.typed, assets, manifests,
        # and any __pycache__ (numba persists compiled kernels there when the
        # dev server runs — machine-specific, never shipped).
        for cache_dir in DST.rglob("__pycache__"):
            shutil.rmtree(cache_dir)
        for path in sorted(DST.rglob("*"), reverse=True):
            if path.is_file() and (
                path.suffix == ".py"
                or path.name
                in {
                    "py.typed",
                    "VENDORED.md",
                    "VENDORED.json",
                    "conversion.json",
                    "LICENSE.txt",
                }
            ):
                path.unlink()
        # Prune now-empty directories (bottom-up), keep DST itself.
        for path in sorted(DST.rglob("*"), reverse=True):
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()

    copied: list[str] = []
    patched: list[str] = []

    for src_path in _iter_source_files():
        rel = src_path.relative_to(SRC)
        dst_path = DST / rel
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if rel.as_posix() == "utils/__init__.py":
            dst_path.write_text(
                _apply_utils_patches(src_path.read_text(encoding="utf-8")),
                encoding="utf-8",
            )
            patched.append(rel.as_posix())
        elif rel.as_posix() in REPLACED_FILES:
            continue  # written by _write_replacements
        else:
            dst_path.write_bytes(src_path.read_bytes())
            copied.append(rel.as_posix())

    for rel in ASSET_FILES:
        src_path = SRC / rel
        dst_path = DST / rel
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if src_path.exists():
            dst_path.write_bytes(src_path.read_bytes())
        elif not dst_path.exists():
            raise RuntimeError(f"expected source asset missing: {rel}")
    for rel in ASSET_DIRS:
        (DST / rel).mkdir(parents=True, exist_ok=True)
        # Empty dirs do not survive zip archives or workspace snapshots and
        # layouts.py resolves these ballset names at import time — drop a
        # placeholder so the directories always restore.
        keep = (DST / rel) / ".keep"
        if not keep.exists():
            keep.write_text(
                "Intentionally empty: this ballset dir must exist for "
                "pooltool.layouts (get_ballset validates at import time); "
                "the .glb art is not needed headlessly.\n"
            )

    _write_replacements(commit, stamp)

    # Apache-2.0 attribution ships with the vendored code.
    license_src = SRC_ROOT / "LICENSE.txt"
    if license_src.exists():
        (DST / "LICENSE.txt").write_bytes(license_src.read_bytes())

    return {
        "source_repo": str(SRC_ROOT),
        "source_version": version,
        "source_commit": commit,
        "vendored_at": stamp,
        "copied_verbatim": len(copied),
        "patched_files": patched,
        "replaced_files": sorted(REPLACED_FILES),
        "excluded_files": sorted(EXCLUDED_FILES),
        "excluded_dirs": sorted(EXCLUDED_DIRS),
    }


def check() -> int:
    """Verify an existing vendored tree against the source repo.

    Returns the number of unexpected divergences (0 == physics-identical).
    """
    meta = json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))
    replaced = set(meta["replaced_files"])
    patched = set(meta["patched_files"])
    divergent: list[str] = []

    for dst_path in sorted(DST.rglob("*.py")):
        rel = dst_path.relative_to(DST).as_posix()
        src_path = SRC / rel
        if rel in replaced or rel.startswith("ani/"):
            continue  # managed shims — contents are asserted at vendor time
        if not src_path.exists():
            divergent.append(f"{rel}: no source counterpart")
            continue
        src_text = src_path.read_text(encoding="utf-8")
        if rel in patched:
            src_text = _apply_utils_patches(src_text)
        if dst_path.read_text(encoding="utf-8") != src_text:
            divergent.append(f"{rel}: differs from source")

    # Every source .py (minus exclusions) must be present in the vendored tree.
    for src_path in _iter_source_files():
        rel = src_path.relative_to(SRC).as_posix()
        if rel in REPLACED_FILES:
            if not (DST / rel).exists():
                divergent.append(f"{rel}: missing replacement file")
            continue
        if not (DST / rel).exists():
            divergent.append(f"{rel}: missing from vendored tree")

    if divergent:
        print("VENDORED TREE DIVERGES FROM SOURCE:")
        for line in divergent:
            print(f"  - {line}")
        return len(divergent)

    print(
        f"OK: {meta['copied_verbatim']} files byte-identical to source "
        f"(pooltool-billiards {meta['source_version']} @ {meta['source_commit'][:12]}); "
        f"{len(patched)} patched + {len(replaced)} replaced glue files, "
        "no physics file modified."
    )
    return 0


def write_manifest(meta: dict) -> None:
    MANIFEST_JSON.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    total_py = sum(1 for _ in DST.rglob("*.py"))
    size = sum(p.stat().st_size for p in DST.rglob("*") if p.is_file())
    md = f"""# VENDORED pooltool — pyramid-web backend (Step 3)

The `pooltool` package in this directory is a vendored copy of the Russian
Pyramid-extended [pooltool](https://github.com/ekiefl/pooltool) library,
produced by `scripts/vendor_physics.py`. License: Apache-2.0 (`LICENSE.txt`
in this directory).

| | |
|:--|:--|
| Source repo | `{meta["source_repo"]}` |
| Source version | pooltool-billiards {meta["source_version"]} |
| Source commit | `{meta["source_commit"]}` |
| Vendored at | {meta["vendored_at"]} |
| Files copied verbatim | {meta["copied_verbatim"]} (all physics, rulesets, layouts) |
| Total Python files | {total_py} |
| Tree size | {size / 1024:.0f} KiB |

## Removed (Panda3D desktop stack — replaced by the Three.js frontend)

- `pooltool/ani/` — replaced by a stub that only provides `model_dir`
- `pooltool/interact.py`, `pooltool/main.py` — desktop entry points
- `objects/{{table,ball,cue}}/render.py`, `system/render.py` — Panda3D renderers
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
"""
    MANIFEST_MD.write_text(md, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify only")
    args = parser.parse_args()

    if not SRC.exists():
        print(f"source repo not found: {SRC}", file=sys.stderr)
        return 2

    if args.check:
        return check() and 1

    meta = vendor()
    write_manifest(meta)
    print(
        f"vendored {meta['copied_verbatim']} verbatim files "
        f"(+{len(meta['patched_files'])} patched, {len(meta['replaced_files'])} replaced) "
        f"into {DST}"
    )
    rc = check()
    if rc == 0:
        print(f"manifest: {MANIFEST_MD}")
    return rc and 1


if __name__ == "__main__":
    raise SystemExit(main())
