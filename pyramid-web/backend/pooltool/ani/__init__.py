"""pooltool.ani — STUB (pyramid-web headless vendored build).

The Panda3D animation stack is replaced by the Three.js frontend. This package
exists only so that ``from pooltool.ani.constants import model_dir`` (imported
by objects/table/specs.py and objects/ball/sets.py) resolves without Panda3D.
"""

from pooltool.ani.constants import model_dir

__all__ = ["model_dir"]
