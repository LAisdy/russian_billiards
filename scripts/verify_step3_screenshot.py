#!/usr/bin/env python3
"""Pixel analysis of the Step 3 top-down screenshot: pockets verification.

Expected content (top-down view, window.__pyramid.setTopView()):
  1. Scene rendered: green felt, wood rails, dark background (Step-1 style
     ratio checks).
  2. The felt rectangle's aspect ratio is ~3.70/1.80 (table not distorted).
  3. At least 6 dark blobs in the rail ring around the felt — the pocket
     wells (4 corners + 2 middle).
  4. Both long rails show the middle-pocket mouth gap (~98.5 mm = middle
     mouth 82.5 mm + 2 x jaw offset 8 mm), measured in pixels against the
     felt-width-derived pixels-per-meter scale.

All measurements are empirical (felt rectangle detected from green pixels),
so the check carries no camera-projection assumptions.
"""

from __future__ import annotations

import sys
from collections import deque

from PIL import Image

TABLE_L = 3.70
TABLE_W = 1.80
RAIL_W = 0.14
MIDDLE_GAP = 0.0825 + 2 * 0.008  # physics mouth + jaw offsets = 0.0985 m


def classify(px: tuple[int, int, int]) -> str:
    r, g, b = px[:3]
    if g > 60 and g > r * 2.0 and g > b * 1.5:
        return "felt-green"
    # wood brown: red dominant over blue, mid brightness (rail faces are lit
    # unevenly, so the blue ratio is loose)
    if r > 55 and r > b * 1.5 and 20 < g < r:
        return "rail-brown"
    if r > 200 and g > 200 and b > 190:
        return "white"
    if r > 70 and r > g * 2.5 and r > b * 2.5 and g < 60:
        return "red"
    # near-black (pocket well / deep shadow / dark floor): everything very dark
    if max(r, g, b) < 26 or (r < 30 and g < 35 and b < 40):
        return "dark"
    return "other"


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/render/step3_top.png"
    img = Image.open(path).convert("RGB")
    w, h = img.size
    print(f"image: {w}x{h} — {path}")

    counts: dict[str, int] = {}
    green_xs: list[int] = []
    green_ys: list[int] = []
    dark: set[tuple[int, int]] = set()
    step = 2
    for y in range(0, h, step):
        for x in range(0, w, step):
            kind = classify(img.getpixel((x, y)))
            counts[kind] = counts.get(kind, 0) + 1
            if kind == "felt-green":
                green_xs.append(x)
                green_ys.append(y)
            elif kind == "dark":
                dark.add((x, y))
    total = sum(counts.values())

    def pct(k: str) -> float:
        return 100.0 * counts.get(k, 0) / total

    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<16} {v:>7}  ({pct(k):5.1f}%)")

    ok = True
    if pct("felt-green") < 3:
        print("[FAIL] green felt not visible (scene likely blank)")
        ok = False
    if pct("rail-brown") < 1:
        print("[FAIL] wood rails not visible")
        ok = False
    if pct("white") < 0.02 and pct("red") < 0.01:
        print("[FAIL] neither demo ball visible")
        ok = False

    if not green_xs:
        print("[FAIL] no felt pixels — cannot measure table geometry")
        return 1

    min_x, max_x = min(green_xs), max(green_xs)
    min_y, max_y = min(green_ys), max(green_ys)
    felt_w_px = max_x - min_x
    felt_h_px = max_y - min_y
    aspect = felt_w_px / max(1, felt_h_px)
    expected = TABLE_L / TABLE_W
    print(
        f"felt rect: {felt_w_px}x{felt_h_px}px, aspect {aspect:.2f} "
        f"(expected ~{expected:.2f})"
    )
    if abs(aspect - expected) / expected > 0.2:
        print("[FAIL] felt aspect ratio off — table distorted?")
        ok = False
    else:
        print("[PASS] felt aspect ratio matches 3.70/1.80")

    px_per_m = felt_w_px / TABLE_L

    # --- pocket wells: dark connected components in the rail ring -------------
    # Wells extend at most ~0.095 m beyond the felt edge; keep the ring inside
    # the table shadow that the lamp casts ~0.16-0.20 m beyond the felt.
    ring_out = 0.15 * px_per_m
    ring_in = 0.03 * px_per_m  # ignore the outermost felt edge (AA)
    ring = {
        (x, y)
        for (x, y) in dark
        if (
            min_x - ring_out <= x <= max_x + ring_out
            and min_y - ring_out <= y <= max_y + ring_out
            and not (
                min_x + ring_in <= x <= max_x - ring_in
                and min_y + ring_in <= y <= max_y - ring_in
            )
        )
    }
    blobs: list[tuple[int, int, int]] = []  # (size, cx, cy)
    seen: set[tuple[int, int]] = set()
    for pixel in ring:
        if pixel in seen:
            continue
        comp = [pixel]
        seen.add(pixel)
        queue = deque(comp)
        while queue:
            cx, cy = queue.popleft()
            # samples live on the step-2 grid -> neighbors are +/-step apart
            for nx, ny in (
                (cx + step, cy),
                (cx - step, cy),
                (cx, cy + step),
                (cx, cy - step),
            ):
                if (nx, ny) in ring and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    comp.append((nx, ny))
                    queue.append((nx, ny))
        if len(comp) >= 6:
            blobs.append(
                (
                    len(comp),
                    sum(p[0] for p in comp) / len(comp),
                    sum(p[1] for p in comp) / len(comp),
                )
            )
    blobs.sort(reverse=True)
    print(
        f"dark blobs in the rail ring: {len(blobs)} (largest: {[b[0] for b in blobs[:8]]})"
    )
    if len(blobs) >= 6:
        print("[PASS] >= 6 pocket wells visible around the felt")
    else:
        print("[FAIL] expected >= 6 pocket wells in the rail ring")
        ok = False

    # --- middle-pocket mouth gaps in the long rails -----------------------------
    for label, base_row in (("top", min_y), ("bottom", max_y)):
        margin = int(0.12 * px_per_m)
        center = (min_x + max_x) / 2
        best: list[float] = []
        for offset in (0.05, 0.07, 0.09, 0.11):
            row = (
                int(base_row + offset * px_per_m)
                if label == "bottom"
                else int(base_row - offset * px_per_m)
            )
            if not 0 <= row < h:
                continue
            runs: list[tuple[int, int]] = []
            run_start = None
            for x in range(min_x + margin, max_x - margin):
                kind = classify(img.getpixel((x, row)))
                if kind != "rail-brown":
                    if run_start is None:
                        run_start = x
                else:
                    if run_start is not None:
                        runs.append((run_start, x - run_start))
                        run_start = None
            if run_start is not None:
                runs.append((run_start, (max_x - margin) - run_start))
            mouths = [
                length / px_per_m * 1000
                for start, length in runs
                if abs(start + length / 2 - center) < 0.25 * px_per_m
                and 0.06 * px_per_m < length < 0.15 * px_per_m
            ]
            best.extend(mouths)
        if best:
            gap_mm = best[0]
            print(
                f"{label} rail middle-pocket gap: {gap_mm:.0f} mm "
                f"(physics: {MIDDLE_GAP * 1000:.0f} mm)"
            )
            if abs(gap_mm - MIDDLE_GAP * 1000) < 20:
                print(f"[PASS] {label} middle mouth ~{gap_mm:.0f} mm")
            else:
                print(f"[FAIL] {label} middle mouth {gap_mm:.0f} mm off")
                ok = False
        else:
            print(f"[FAIL] no middle-pocket gap found in the {label} rail")
            ok = False

    print("RESULT:", "PASS — table + pockets verified" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
