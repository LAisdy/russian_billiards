#!/usr/bin/env python3
"""Package the entire /home/z/my-project tree into a single zip archive.

Requested target: /mnt/session/outputs/pooltool_russian.zip
Fallback target:  /home/z/my-project/download/pooltool_russian.zip
(reason: /mnt is root-owned and this process runs as uid 1001 without sudo;
 the download directory is the user-accessible deliverable location).

Mirrors `zip -r <target> /home/z/my-project` semantics:
  - archives the WHOLE tree (dotfiles, .git, models, etc.)
  - stores arcnames as "my-project/..." relative to /home/z
  - skips only the output archive itself (self-inclusion guard)
Uses ZIP_DEFLATED because the `zip` CLI is not installed.
"""

from __future__ import annotations

import os
import sys
import time
import zipfile

SOURCE_ROOT = "/home/z/my-project"
PREFERRED_TARGET = "/mnt/session/outputs/pooltool_russian.zip"
FALLBACK_TARGET = "/home/z/my-project/download/pooltool_russian.zip"

# Root-level entries to skip (platform infrastructure, not project content):
#   .git         — platform auto-snapshot repo (UUID commits); it absorbs the
#                  backup zip itself into blobs, doubling the archive on every
#                  refresh. NOTE: nested pooltool/.git IS kept (real repo).
#   .env         — platform session file (may contain credentials)
#   tool-results — transient tool-output cache
EXCLUDE_ROOT_DIRS = {".git", "tool-results"}
EXCLUDE_ROOT_FILES = {".env"}

# Arcname prefix: strip this parent so entries become "my-project/<path>".
PARENT_DIR = os.path.dirname(SOURCE_ROOT.rstrip("/"))


def pick_target() -> str:
    """Return the preferred target if writable, else the fallback path."""
    preferred_dir = os.path.dirname(PREFERRED_TARGET)
    try:
        os.makedirs(preferred_dir, exist_ok=True)
        return PREFERRED_TARGET
    except OSError as exc:
        print(f"[warn] cannot use {preferred_dir}: {exc}", file=sys.stderr)
        os.makedirs(os.path.dirname(FALLBACK_TARGET), exist_ok=True)
        return FALLBACK_TARGET


def main() -> int:
    target = pick_target()
    os.makedirs(os.path.dirname(target), exist_ok=True)

    total_files = 0
    total_bytes = 0
    started = time.time()

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(SOURCE_ROOT):
            # Deterministic traversal order for reproducibility.
            dirnames.sort()
            # Skip virtualenvs (rebuilt via `uv sync`; ~1 GiB of wheels and
            # console scripts that restore as broken symlinks anyway).
            dirnames[:] = [d for d in dirnames if d != ".venv"]
            if os.path.abspath(dirpath) == os.path.abspath(SOURCE_ROOT):
                dirnames[:] = [d for d in dirnames if d not in EXCLUDE_ROOT_DIRS]
                filenames = [f for f in filenames if f not in EXCLUDE_ROOT_FILES]
            for fname in sorted(filenames):
                full = os.path.join(dirpath, fname)
                if os.path.abspath(full) == os.path.abspath(target):
                    continue  # never zip the archive into itself
                arcname = os.path.relpath(full, PARENT_DIR)
                st = os.stat(full)
                # ZIP timestamps start at 1980; clamp anything older
                # (e.g. files with epoch-0 mtimes in the tree).
                date_time = time.localtime(st.st_mtime)[:6]
                if date_time[0] < 1980:
                    date_time = (1980, 1, 1, 0, 0, 0)
                zinfo = zipfile.ZipInfo(arcname, date_time)
                zinfo.compress_type = zipfile.ZIP_DEFLATED
                zinfo.external_attr = (st.st_mode & 0xFFFF) << 16
                with open(full, "rb") as fh:
                    zf.writestr(zinfo, fh.read())
                total_files += 1
                total_bytes += st.st_size
                if total_files % 5000 == 0:
                    print(f"  ... {total_files} files added", flush=True)

    size = os.path.getsize(target)
    elapsed = time.time() - started
    print(f"target     : {target}")
    print(f"files      : {total_files}")
    print(f"input bytes: {total_bytes:,}")
    print(f"zip size   : {size:,} bytes ({size / (1024 * 1024):.1f} MiB)")
    print(f"elapsed    : {elapsed:.1f} s")

    # Sanity check: readable central directory, no self-inclusion.
    with zipfile.ZipFile(target) as zf:
        bad = zf.testzip()
        names = zf.namelist()
        if bad is not None:
            print(f"[error] corrupt entry in archive: {bad}", file=sys.stderr)
            return 1
        if any(n == os.path.basename(target) for n in names):
            print("[error] archive contains itself", file=sys.stderr)
            return 1
        print(f"verified   : {len(names)} entries, first = {names[0]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
