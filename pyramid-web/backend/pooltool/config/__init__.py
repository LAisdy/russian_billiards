"""pooltool configuration.

[pyramid-web vendored] The desktop ``Settings``/Panda3D machinery (graphics
options, loadPrcFileData) is removed in the headless build. The only headless
consumer of this package is ``pooltool.config.paths`` (used by
physics/resolve/resolver.py to locate the resolver YAML), which is copied
unchanged.
"""
