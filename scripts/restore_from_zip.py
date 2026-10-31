#!/usr/bin/env python3
"""Restore /home/z/my-project from the newest surviving backup archive.

Known backup locations (newest wins):
  /tmp/my-project/download/pooltool_russian.zip
  /home/z/my-project/download/pooltool_russian.zip

Restores every `my-project/**` entry EXCEPT `my-project/skills/**` and
`my-project/upload/**` (those are environment-managed dirs freshly recreated
by the reset and must not be overwritten with snapshot copies).

After restoring, run `cd pooltool && uv sync --frozen`, then re-run the
verification steps named in PROGRESS.md. If the restored archive predates the
2026-10-29 performance fixes (invalidate + JIT warmup), re-apply them —
see PROGRESS.md Step Log.
"""

from __future__ import annotations

import os
import time
import zipfile

ARCHIVE_CANDIDATES = (
    "/tmp/my-project/download/pooltool_russian.zip",
    "/home/z/my-project/download/pooltool_russian.zip",
)
DEST_ROOT = "/home/z"
SKIP_PREFIXES = ("my-project/skills/", "my-project/upload/")


def pick_archive() -> str:
    """Prefer the newest surviving archive across known backup locations."""
    import os

    candidates = [p for p in ARCHIVE_CANDIDATES if os.path.exists(p)]
    if not candidates:
        raise SystemExit(
            f"[error] no backup archive found in any of: {ARCHIVE_CANDIDATES}"
        )
    return max(candidates, key=os.path.getmtime)


ARCHIVE = pick_archive()


def main() -> int:
    started = time.time()
    with zipfile.ZipFile(ARCHIVE) as zf:
        bad = zf.testzip()
        if bad is not None:
            print(f"[error] corrupt entry: {bad}")
            return 1

        # A previous interrupted restore can leave read-only (e.g. git object,
        # mode 444) files behind; extractall cannot truncate those. Force u+w
        # on anything already present so re-extraction succeeds.
        fixed = 0
        for info in zf.infolist():
            if info.filename.startswith(SKIP_PREFIXES) or info.is_dir():
                continue
            path = os.path.join(DEST_ROOT, info.filename)
            if os.path.lexists(path) and not os.access(path, os.W_OK):
                try:
                    os.chmod(path, 0o644)
                    fixed += 1
                except OSError:
                    pass
        if fixed:
            print(f"re-opened {fixed} read-only leftover file(s)")

        members = [n for n in zf.namelist() if not n.startswith(SKIP_PREFIXES)]
        print(f"extracting {len(members)} entries to {DEST_ROOT} ...")
        zf.extractall(DEST_ROOT, members=members)

    # Archives/snapshots drop EMPTY directories, and the vendored pooltool
    # needs two of them: pooltool.layouts resolves these ballset names via
    # get_ballset at import time, which requires the directory to exist.
    for rel in (
        "pyramid-web/backend/pooltool/models/balls/pooltool_pocket",
        "pyramid-web/backend/pooltool/models/balls/billiard",
    ):
        path = os.path.join(DEST_ROOT, rel)
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
            print(f"recreated empty ballset dir {rel}")

    # Restore permissions lost by extractall (Python ignores external_attr).
    with zipfile.ZipFile(ARCHIVE) as zf:
        for info in zf.infolist():
            if info.filename.startswith(SKIP_PREFIXES) or info.is_dir():
                continue
            path = os.path.join(DEST_ROOT, info.filename)
            mode = (info.external_attr >> 16) & 0o777
            if mode:
                try:
                    os.chmod(path, mode)
                except OSError:
                    pass

    probes = [
        "/home/z/my-project/pooltool/pooltool/ruleset/russian_pyramid.py",
        "/home/z/my-project/pooltool/tests/test_russian_pyramid.py",
        "/home/z/my-project/pooltool/PROGRESS.md",
        "/home/z/my-project/pooltool/RULES_DEVIATIONS.md",
        "/home/z/my-project/scripts/make_project_zip.py",
        "/home/z/my-project/download/play.py",
    ]
    ok = True
    for p in probes:
        exists = os.path.exists(p)
        ok &= exists
        size = os.path.getsize(p) if exists else 0
        print(f"{'OK ' if exists else 'MISS'} {p} ({size:,} B)")

    # Count restored files.
    count = 0
    for dirpath, dirnames, filenames in os.walk("/home/z/my-project"):
        if dirpath.startswith("/home/z/my-project/skills"):
            dirnames[:] = []
            continue
        count += len(filenames)
    print(f"restored files under my-project (excl. skills): {count}")
    print(f"elapsed: {time.time() - started:.1f}s")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
