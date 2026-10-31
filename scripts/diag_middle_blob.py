#!/usr/bin/env python3
"""Diagnose the middle-pocket blob detection failure in step4b_top.png."""
from PIL import Image

path = "/home/z/my-project/download/step4b_top.png"
img = Image.open(path).convert("RGB")
w, h = img.size


def classify(px):
    r, g, b = px[:3]
    if g > 55 and g > r * 1.8 and g > b * 1.3:
        return "G"
    if r > 50 and r > b * 1.45 and 16 < g < r:
        return "B"
    if r > 135 and g > 130 and b > 115 and abs(r - g) < 28 and abs(g - b) < 34:
        return "W"
    if r > 55 and r > g * 1.8 and r > b * 1.8 and g < 70:
        return "R"
    if max(r, g, b) < 26 or (r < 30 and g < 35 and b < 40):
        return "."
    return "?"


# green bbox (as the verifier computes it)
green = [
    (x, y)
    for y in range(0, h, 2)
    for x in range(0, w, 2)
    if classify(img.getpixel((x, y))) == "G"
]
xs = [p[0] for p in green]
ys = [p[1] for p in green]
min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
px_per_m = (max_x - min_x) / 3.8
cx_img = (min_x + max_x) / 2
print(f"bbox x[{min_x},{max_x}] y[{min_y},{max_y}] px_per_m={px_per_m:.1f} cx={cx_img}")

# ASCII map around the top-middle pocket: bbox center x, near min_y
print("\nTOP-MIDDLE region (x 690..750, y min_y-18 .. min_y+14):")
for y in range(min_y - 18, min_y + 15):
    row = "".join(classify(img.getpixel((x, y))) for x in range(690, 751))
    print(f"{y:4d} {row}")

print("\nBOTTOM-MIDDLE region (y max_y-14 .. max_y+18):")
for y in range(max_y - 14, max_y + 19):
    row = "".join(classify(img.getpixel((x, y))) for x in range(690, 751))
    print(f"{y:4d} {row}")

# sample a few raw pixel values in the blob
print("\nraw pixels near top-middle blob:")
for y in range(min_y - 12, min_y + 4, 3):
    for x in range(710, 731, 5):
        print(f"  ({x},{y}) = {img.getpixel((x, y))} -> {classify(img.getpixel((x, y)))}")
