"""Stub of pooltool.ani.constants for the headless vendored build.

Only ``model_dir`` is provided (see pooltool/ani/__init__.py). The desktop
constants (menu scales, camera sensitivities, logo paths) have no headless
consumers.
"""

from __future__ import annotations

from pathlib import Path

model_dir: Path = Path(__file__).resolve().parent.parent / "models"
