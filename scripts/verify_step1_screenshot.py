#!/usr/bin/env python3
"""Pixel analysis of the Step 1 screenshot: verify the Three.js scene rendered.

Expected content (1280x800):
  - dark background (#101418-ish) around the table
  - green felt table rectangle in the middle (0x1c6b3f-ish)
  - wood-brown rails (0x54331f-ish) framing the felt
  - two balls: white-ish + dark red, with shadows
  - HUD panel (dark translucent) top-left with light text
"""

from __future__ import annotations

import sys

from PIL import Image


def classify(px: tuple[int, int, int]) -> str:
    r, g, b = px[:3]
    # felt green (lit #1c6b3f -> ~(32,85,49)): green dominant, green > 1.5x blue
    if g > 60 and g > r * 2.0 and g > b * 1.5:
        return "felt-green"
    # wood brown: red dominant over blue, mid brightness
    if r > 55 and r > b * 1.9 and 20 < g < r:
        return "rail-brown"
    # near-black background
    if r < 30 and g < 35 and b < 40:
        return "background-dark"
    # white-ish (ball or HUD text)
    if r > 200 and g > 200 and b > 190:
        return "white(ball/text)"
    # dark red cue ball
    if r > 70 and r > g * 2.5 and r > b * 2.5 and g < 60:
        return "red-cue-ball"
    return "other"


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/render/pyramid_step1.png"
    img = Image.open(path).convert("RGB")
    w, h = img.size
    counts: dict[str, int] = {}
    step = 4  # sample every 4th pixel
    total = 0
    for y in range(0, h, step):
        for x in range(0, w, step):
            counts[classify(img.getpixel((x, y)))] = (
                counts.get(classify(img.getpixel((x, y))), 0) + 1
            )
            total += 1

    print(f"image: {w}x{h}, sampled {total} pixels (step={step})")
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<18} {v:>7}  ({100.0 * v / total:5.1f}%)")

    ok = True

    def pct(k: str) -> float:
        return 100.0 * counts.get(k, 0) / total

    # Scene rendered = substantial felt + rails present
    if pct("felt-green") < 3:
        print("[FAIL] green felt not visible (scene likely blank)")
        ok = False
    if pct("rail-brown") < 1:
        print("[FAIL] wood rails not visible")
        ok = False
    if pct("white(ball/text)") < 0.03:
        print("[FAIL] no white pixels (no HUD text / object ball)")
        ok = False
    if pct("background-dark") < 15:
        print("[WARN] less dark background than expected (check fog/colors)")
    print("RESULT:", "PASS — scene rendered" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
