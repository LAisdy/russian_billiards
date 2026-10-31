"""The system container and its associated objects.

[pyramid-web vendored] ``SystemRender`` (Panda3D) is removed in the headless
build — the Three.js frontend renders systems instead.
"""

from pooltool.system.datatypes import MultiSystem, System, multisystem

__all__ = [
    "MultiSystem",
    "System",
    "multisystem",
]
