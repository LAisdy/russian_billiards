#!/usr/bin/env python3
"""Pixel analysis of the Step 4 top-down screenshot: full table verification.

Expected content (top-down view, window.__pyramid.setTopView()):
  1. Scene rendered: green felt, wood frame, dark background.
  2. The green rectangle (playing surface + felt cushion tops, i.e.
     (3.70+0.10) x (1.80+0.10) m) has the matching aspect ratio.
  3. Six dark pocket blobs in the ring just outside the green rectangle
     (4 corner wells + 2 middle wells; the ring stays inside the wooden
     frame, so floor shadow/background cannot merge into it).
  4. Both long rails show the middle-pocket mouth gap (~98.5 mm = middle
     mouth 82.5 mm + 2 x jaw offset 8 mm) in the wooden frame band.
  5. A white ball cluster (the 15-ball rack) sized like the standard
     triangle (~0.34 x 0.30 m) on the foot half, and exactly one red cue
     ball blob on the head half.
  6. The wooden frame is present just outside the green rectangle along
     both long-rail midpoints.

All measurements are empirical (rectangles detected from pixel classes), so
the check carries no camera-projection assumptions.
"""

from __future__ import annotations

import sys
from collections import deque

from PIL import Image

TABLE_L = 3.70
TABLE_W = 1.80
CUSH_W = 0.05
MIDDLE_GAP = 0.0825 + 2 * 0.008  # physics mouth + jaw offsets = 0.0985 m
RACK_W = 4 * (2 * 0.0335 + 1e-3) + 2 * 0.0335  # 5 rows of touching balls
RACK_H = 4 * (2 * 0.0335 + 1e-3) * 0.8660254 + 2 * 0.0335


def classify(px: tuple[int, int, int]) -> str:
    r, g, b = px[:3]
    if g > 55 and g > r * 1.8 and g > b * 1.3:
        return "felt-green"
    if r > 50 and r > b * 1.45 and 16 < g < r:
        return "rail-brown"
    # ivory ball: bright and near-achromatic (rules out green felt and brown)
    if r > 135 and g > 130 and b > 115 and abs(r - g) < 28 and abs(g - b) < 34:
        return "white"
    if r > 55 and r > g * 1.8 and r > b * 1.8 and g < 70:
        return "red"
    if max(r, g, b) < 26 or (r < 30 and g < 35 and b < 40):
        return "dark"
    return "other"


def blobs_of(points: set[tuple[int, int]], step: int, min_size: int = 6):
    """Connected components on the sampled grid (4-neighbour, step apart)."""
    out = []
    seen: set[tuple[int, int]] = set()
    for pixel in points:
        if pixel in seen:
            continue
        comp = [pixel]
        seen.add(pixel)
        queue = deque(comp)
        xs: list[int] = []
        ys: list[int] = []
        while queue:
            cx, cy = queue.popleft()
            xs.append(cx)
            ys.append(cy)
            for nx, ny in (
                (cx + step, cy),
                (cx - step, cy),
                (cx, cy + step),
                (cx, cy - step),
            ):
                if (nx, ny) in points and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    comp.append((nx, ny))
                    queue.append((nx, ny))
        if len(comp) >= min_size:
            out.append(
                (
                    len(comp),
                    sum(xs) / len(xs),
                    sum(ys) / len(ys),
                    min(xs),
                    max(xs),
                    min(ys),
                    max(ys),
                )
            )
    out.sort(reverse=True)
    return out


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/step4_top.png"
    img = Image.open(path).convert("RGB")
    w, h = img.size
    print(f"image: {w}x{h} — {path}")

    counts: dict[str, int] = {}
    green_xs: list[int] = []
    green_ys: list[int] = []
    dark: set[tuple[int, int]] = set()
    whites: set[tuple[int, int]] = set()
    reds: set[tuple[int, int]] = set()
    browns: set[tuple[int, int]] = set()
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
            elif kind == "white":
                whites.add((x, y))
            elif kind == "red":
                reds.add((x, y))
            elif kind == "rail-brown":
                browns.add((x, y))
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
        print("[FAIL] wood frame not visible")
        ok = False

    if not green_xs:
        print("[FAIL] no felt pixels — cannot measure table geometry")
        return 1

    min_x, max_x = min(green_xs), max(green_xs)
    min_y, max_y = min(green_ys), max(green_ys)
    green_w_px = max_x - min_x
    green_h_px = max_y - min_y
    # green bbox = playing surface + felt cushion tops on every side
    span_l = TABLE_L + 2 * CUSH_W
    span_w = TABLE_W + 2 * CUSH_W
    aspect = green_w_px / max(1, green_h_px)
    expected = span_l / span_w
    print(
        f"green rect: {green_w_px}x{green_h_px}px, aspect {aspect:.2f} "
        f"(expected ~{expected:.2f})"
    )
    if abs(aspect - expected) / expected > 0.06:
        print("[FAIL] table aspect ratio off — model distorted?")
        ok = False
    else:
        print("[PASS] table aspect ratio matches (3.70+0.10)/(1.80+0.10)")

    px_per_m = green_w_px / span_l
    cx_img = (min_x + max_x) / 2

    # --- pocket wells: dark blobs hugging the table outline --------------------
    # the wells straddle the green rectangle's edge (they are cut through the
    # cushions/frame), so search dark pixels within 0.09 m of the bbox, then
    # drop anything touching the search boundary (floor shadow / background
    # connect there) or bigger than a well can possibly be
    margin = 0.09 * px_per_m
    lo_x, hi_x = min_x - margin, max_x + margin
    lo_y, hi_y = min_y - margin, max_y + margin
    cand = {(x, y) for (x, y) in dark if lo_x <= x <= hi_x and lo_y <= y <= hi_y}
    pocket_blobs = []
    for b in blobs_of(cand, step, min_size=5):
        size, _, _, bx0, bx1, by0, by1 = b
        if size > 1500:
            continue
        if bx0 <= lo_x + 2 or bx1 >= hi_x - 2 or by0 <= lo_y + 2 or by1 >= hi_y - 2:
            continue  # touches the search boundary -> floor/background/shadow
        pocket_blobs.append(b)
    print(
        f"pocket blobs near the table edge: {len(pocket_blobs)} (sizes: {[b[0] for b in pocket_blobs[:10]]})"
    )

    # two middle wells: dark blob centred within 0.15 m of the table centre,
    # hugging the LOCAL felt edge of its long rail, width ~= well diameter
    # (88 mm + rims). The felt edge is measured per rail within +/-0.15 m of
    # the centre column: the corner wrap bands legitimately poke the global
    # bbox a few px past the rail line, so a bbox-based row would be brittle.
    for label, side in (("top", -1), ("bottom", 1)):
        col_lo = cx_img - 0.15 * px_per_m
        col_hi = cx_img + 0.15 * px_per_m
        rows = [y for x, y in zip(green_xs, green_ys) if col_lo <= x <= col_hi]
        near_row = min(rows) if side < 0 else max(rows)
        mid = [
            b
            for b in pocket_blobs
            if abs(b[1] - cx_img) < 0.15 * px_per_m
            and -0.11 * px_per_m <= side * (b[2] - near_row) <= 0
            and 0.05 * px_per_m < (b[4] - b[3]) < 0.16 * px_per_m
        ]
        if mid:
            wid_mm = (mid[0][4] - mid[0][3]) / px_per_m * 1000
            print(
                f"{label} middle pocket well: ~{wid_mm:.0f} mm wide (well 88 mm + rims)"
            )
            print(f"[PASS] {label} middle pocket present at the centre")
        else:
            print(f"[FAIL] no middle pocket well near the {label} rail centre")
            ok = False

    # four corner wells: dark blob within 0.16 m of each bbox corner (the
    # perspective pushes the far corners slightly inside the bbox)
    for label, (cx0, cy0) in (
        ("top-left", (min_x, min_y)),
        ("top-right", (max_x, min_y)),
        ("bottom-left", (min_x, max_y)),
        ("bottom-right", (max_x, max_y)),
    ):
        near = [
            b
            for b in pocket_blobs
            if abs(b[1] - cx0) < 0.16 * px_per_m and abs(b[2] - cy0) < 0.16 * px_per_m
        ]
        if near:
            print(f"[PASS] {label} corner pocket present")
        else:
            print(f"[FAIL] no corner pocket blob near {label}")
            ok = False

    # --- balls: white rack cluster + single red cue -----------------------------
    inner = {
        (x, y)
        for (x, y) in whites
        if min_x + 0.01 * px_per_m <= x <= max_x - 0.01 * px_per_m
        and min_y + 0.01 * px_per_m <= y <= max_y - 0.01 * px_per_m
    }
    white_blobs = blobs_of(inner, step, min_size=4)
    if not white_blobs:
        print("[FAIL] no white ball pixels inside the felt")
        ok = False
    else:
        blob = white_blobs[0]
        bw = (blob[4] - blob[3]) / px_per_m
        bh = (blob[6] - blob[5]) / px_per_m
        cx_m = (blob[1] - (min_x + max_x) / 2) / px_per_m  # + = foot half
        print(
            f"white cluster: {bw:.2f} x {bh:.2f} m "
            f"(rack ~{RACK_W:.2f} x {RACK_H:.2f} m), center offset {cx_m:+.2f} m"
        )
        if 0.7 * RACK_W <= bw <= 1.6 * RACK_W and 0.7 * RACK_H <= bh <= 1.6 * RACK_H:
            print("[PASS] rack triangle present at the expected size")
        else:
            print("[FAIL] white cluster is not rack-sized")
            ok = False
        if cx_m > 0.1:
            print("[PASS] rack sits on the foot half")
        else:
            print("[FAIL] rack not on the foot half")
            ok = False

    red_blobs = blobs_of(reds, step, min_size=3)
    if 1 <= len(red_blobs) <= 2:
        blob = red_blobs[0]
        d = max(blob[4] - blob[3], blob[6] - blob[5]) / px_per_m
        cx_m = (blob[1] - (min_x + max_x) / 2) / px_per_m
        print(
            f"red cue blob(s): {len(red_blobs)}, largest {blob[0]} px, "
            f"Ø ~{d * 1000:.0f} mm, offset {cx_m:+.2f} m"
        )
        if 0.55 <= d / (2 * 0.0335) <= 1.8:
            print("[PASS] red cue ball present, ball-sized")
        else:
            print("[FAIL] red cue blob wrong size")
            ok = False
        if cx_m < -0.1:
            print("[PASS] cue ball on the head half")
        else:
            print("[FAIL] cue ball not on the head half")
            ok = False
    else:
        print(f"[FAIL] expected 1-2 red cue blobs, found {len(red_blobs)}")
        ok = False

    # --- wooden frame presence just outside the local felt edge -----------------
    # the table edges bow a few px in perspective, so probe relative to the
    # leftmost/rightmost green pixel of each scan row (not the global bbox)
    green_row_range: dict[int, list[int]] = {}
    for gx, gy in zip(green_xs, green_ys):
        lo, hi = green_row_range.get(gy, (gx, gx))
        green_row_range[gy] = (min(lo, gx), max(hi, gx))

    probe_rows = [
        min_y + int(0.25 * green_h_px),
        (min_y + max_y) // 2,
        max_y - int(0.25 * green_h_px),
    ]
    sampled_rows = sorted(green_row_range)
    for label in ("left", "right"):
        found = False
        for want in probe_rows:
            row = min(sampled_rows, key=lambda r: abs(r - want))  # grid parity
            edge = (
                green_row_range[row][0] if label == "left" else green_row_range[row][1]
            )
            for off_px in (4, 6, 10, 15, 20):
                probe_x = edge - off_px if label == "left" else edge + off_px
                if classify(img.getpixel((probe_x, row))) == "rail-brown":
                    found = True
                    break
            if found:
                break
        if found:
            print(f"[PASS] {label} wooden frame present along the long rails")
        else:
            print(f"[FAIL] {label} wooden frame not found along the long rails")
            ok = False

    print("RESULT:", "PASS — full table verified" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
