# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Generate the 32x32 PNG icons of Curve Toolkit.

Usage:  python make_icons.py <output_dir> [<preview.png>]

Icons are drawn at 512x512 and reduced with premultiplied alpha, so edges are
smooth on any Blender theme. The optional preview sheet shows them enlarged
over Blender's default dark and light panel colors.
"""

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

BIG = 512
OUT = 32

GRAY = (138, 138, 138)
FILL = (92, 92, 92)
WHITE = (255, 255, 255)
ORANGE = (255, 127, 0)
GREEN = (128, 255, 0)
BLUE = (0, 140, 255)
PURPLE = (170, 0, 255)

STROKE = 0.075           # stroke width (fraction of the icon)
SQUARE = (0.10, 0.10, 0.62, 0.62)
CIRCLE_C = (0.62, 0.62)
CIRCLE_R = 0.28


def px(v):
    return v * BIG


def blank():
    return Image.new("L", (BIG, BIG), 0)


def mask_array(img):
    return np.asarray(img, dtype=np.float32) / 255.0


def square_masks():
    fill, line = blank(), blank()
    box = [px(v) for v in SQUARE]
    ImageDraw.Draw(fill).rectangle(box, fill=255)
    ImageDraw.Draw(line).rectangle(box, outline=255, width=round(px(STROKE)))
    return mask_array(fill), mask_array(line)


def circle_masks(center=CIRCLE_C, radius=CIRCLE_R):
    fill, line = blank(), blank()
    box = [px(center[0] - radius), px(center[1] - radius),
           px(center[0] + radius), px(center[1] + radius)]
    ImageDraw.Draw(fill).ellipse(box, fill=255)
    ImageDraw.Draw(line).ellipse(box, outline=255, width=round(px(STROKE)))
    return mask_array(fill), mask_array(line)


def thick_polyline(points, width):
    img = blank()
    d = ImageDraw.Draw(img)
    r = px(width) / 2
    for (x, y) in points:
        d.ellipse([px(x) - r, px(y) - r, px(x) + r, px(y) + r], fill=255)
    return mask_array(img)


def densify(points, closed=False, step=0.003):
    """Points of a polyline with extra samples along every segment, so that
    thick_polyline() can draw it as a continuous stroke."""
    pts = list(points) + ([points[0]] if closed else [])
    out = []
    for a, b in zip(pts, pts[1:]):
        n = max(1, int(math.dist(a, b) / step))
        for i in range(n):
            t = i / n
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    out.append(pts[-1])
    return out


def regular_polygon(center, radius, sides, start_angle=math.pi / 2):
    """Vertices of a regular polygon, first one at `start_angle` (default the
    +Y axis, at 12 o'clock, as the Polygon primitive makes it)."""
    cx, cy = center
    return [
        (cx + radius * math.cos(start_angle + 2 * math.pi * i / sides),
         cy - radius * math.sin(start_angle + 2 * math.pi * i / sides))
        for i in range(sides)
    ]


def dot(x, y, radius=0.07):
    img = blank()
    ImageDraw.Draw(img).ellipse(
        [px(x - radius), px(y - radius), px(x + radius), px(y + radius)], fill=255)
    return mask_array(img)


def bezier(p0, p1, p2, p3, n=120):
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        pts.append((
            u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
            u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
        ))
    return pts


class Canvas:
    """RGBA float canvas painted with (color, mask) layers."""

    def __init__(self):
        self.rgb = np.zeros((BIG, BIG, 3), dtype=np.float32)
        self.a = np.zeros((BIG, BIG), dtype=np.float32)

    def paint(self, color, mask):
        mask = np.clip(mask, 0, 1)
        col = np.array(color, dtype=np.float32) / 255.0
        self.rgb = self.rgb * (1 - mask[..., None]) + col * mask[..., None]
        self.a = self.a * (1 - mask) + mask

    def to_image(self, size=OUT):
        # Premultiplied downsample to avoid dark halos on transparent edges.
        pre = self.rgb * self.a[..., None]
        k = BIG // size
        pre = pre.reshape(size, k, size, k, 3).mean(axis=(1, 3))
        a = self.a.reshape(size, k, size, k).mean(axis=(1, 3))
        rgb = np.where(a[..., None] > 1e-6, pre / np.maximum(a[..., None], 1e-6), 0)
        out = np.dstack([rgb, a])
        return Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA")


# -----------------------------------------------------------------------------
# Icons
# -----------------------------------------------------------------------------

def boolean_icon(kind):
    s_fill, s_line = square_masks()
    c_fill, c_line = circle_masks()
    inS, inC = s_fill > 0.5, c_fill > 0.5
    if kind == 'union':
        region = inS | inC
        white = s_line * (~inC) + c_line * (~inS)
    elif kind == 'intersection':
        region = inS & inC
        white = s_line * inC + c_line * inS
    else:  # difference: the square bitten by the circle
        region = inS & ~inC
        white = s_line * (~inC) + c_line * inS
    cv = Canvas()
    cv.paint(FILL, region.astype(np.float32))
    cv.paint(GRAY, np.maximum(s_line, c_line))
    cv.paint(WHITE, np.clip(white, 0, 1))
    return cv.to_image()


def split_icon(split_all):
    s_fill, s_line = square_masks()
    c_fill, c_line = circle_masks()
    inS, inC = s_fill > 0.5, c_fill > 0.5
    cv = Canvas()
    if split_all:
        cv.paint(BLUE, c_line * (~inS))
        cv.paint(PURPLE, c_line * inS)
    else:
        cv.paint(GRAY, c_line)
    cv.paint(ORANGE, s_line * (~inC))
    cv.paint(GREEN, s_line * inC)
    cx, cy = CIRCLE_C
    for (x, y) in ((cx, cy - CIRCLE_R), (cx - CIRCLE_R, cy)):
        cv.paint(WHITE, dot(x, y))
    return cv.to_image()


def round_icon():
    lo, hi, r = 0.10, 0.90, 0.22
    line = blank()
    ImageDraw.Draw(line).rounded_rectangle(
        [px(lo), px(lo), px(hi), px(hi)], radius=px(r), outline=255, width=round(px(STROKE)))
    line = mask_array(line)
    yy, xx = np.mgrid[0:BIG, 0:BIG] / BIG
    near_x = (xx < lo + r) | (xx > hi - r)
    near_y = (yy < lo + r) | (yy > hi - r)
    corners = (near_x & near_y).astype(np.float32)
    cv = Canvas()
    cv.paint(GRAY, line)
    cv.paint(WHITE, line * corners)
    for (x, y) in ((0.32, 0.32), (0.68, 0.32), (0.32, 0.68), (0.68, 0.68)):
        cv.paint(WHITE, dot(x, y, 0.055))
    return cv.to_image()


def corner_icon():
    """Arcs to Corners: in grey the rounded corner and what comes before and
    after it, in orange the two sides of the hard corner it came from, and the
    three points: the two the arc ends at and the corner between them."""
    a, b = (0.42, 0.72), (0.78, 0.36)        # ends of the arc
    corner = (0.78, 0.72)                    # where their handles meet
    k = 0.36 * 0.5523                        # handles of a quarter of a circle
    arc = bezier(a, (a[0] + k, a[1]), (b[0], b[1] + k), b)
    cv = Canvas()
    cv.paint(GRAY, thick_polyline(densify(((0.08, 0.72), a)), STROKE))
    cv.paint(GRAY, thick_polyline(arc, STROKE))
    cv.paint(GRAY, thick_polyline(densify((b, (0.78, 0.06))), STROKE))
    cv.paint(ORANGE, thick_polyline(densify((a, corner, b)), STROKE * 1.15))
    for (x, y) in (a, b, corner):
        cv.paint(WHITE, dot(x, y, 0.075))
    return cv.to_image()


def bridge_icon():
    a = bezier((0.06, 0.84), (0.20, 0.66), (0.36, 0.64), (0.50, 0.74))
    b = bezier((0.46, 0.08), (0.70, 0.22), (0.82, 0.40), (0.80, 0.58))
    bridge = bezier((0.50, 0.74), (0.66, 0.86), (0.84, 0.78), (0.80, 0.58))
    cv = Canvas()
    cv.paint(GRAY, thick_polyline(a, STROKE))
    cv.paint(GRAY, thick_polyline(b, STROKE))
    cv.paint(ORANGE, thick_polyline(bridge, STROKE * 1.15))
    cv.paint(WHITE, dot(*a[-1], 0.075))
    cv.paint(WHITE, dot(*b[-1], 0.075))
    return cv.to_image()


# --- Primitive curves ---------------------------------------------------------

PRIM_DOT = 0.08         # radius of the control points of the primitives
PRIM_VERTEX = 0.07      # the same, where there are many of them
PRIM_CENTER = 0.05      # radius of the origin dot of the closed primitives


def line_icon():
    a, b = (0.19, 0.21), (0.81, 0.79)
    cv = Canvas()
    cv.paint(GRAY, thick_polyline(densify((a, b)), STROKE))
    cv.paint(WHITE, dot(*a, PRIM_DOT))
    cv.paint(WHITE, dot(*b, PRIM_DOT))
    return cv.to_image()


def bezier_icon():
    a, b = (0.14, 0.26), (0.84, 0.76)
    curve = bezier(a, (0.44, 0.17), (0.54, 0.85), b)
    cv = Canvas()
    cv.paint(GRAY, thick_polyline(curve, STROKE))
    cv.paint(WHITE, dot(*a, PRIM_DOT))
    cv.paint(WHITE, dot(*b, PRIM_DOT))
    return cv.to_image()


def rectangle_icon():
    lo, hi = 0.16, 0.84
    corners = [(lo, lo), (hi, lo), (hi, hi), (lo, hi)]
    cv = Canvas()
    cv.paint(GRAY, thick_polyline(densify(corners, closed=True), STROKE))
    for (x, y) in corners:
        cv.paint(WHITE, dot(x, y, PRIM_DOT))
    return cv.to_image()


def polygon_icon(sides=6, radius=0.38):
    center = (0.5, 0.5)
    verts = regular_polygon(center, radius, sides)
    cv = Canvas()
    cv.paint(GRAY, thick_polyline(densify(verts, closed=True), STROKE))
    for (x, y) in verts:
        cv.paint(WHITE, dot(x, y, PRIM_VERTEX))
    cv.paint(WHITE, dot(*center, PRIM_CENTER))
    return cv.to_image()


def circle_icon(radius=0.37):
    center = (0.5, 0.5)
    _, line = circle_masks(center, radius)
    cv = Canvas()
    cv.paint(GRAY, line)
    for (x, y) in regular_polygon(center, radius, 4):
        cv.paint(WHITE, dot(x, y, PRIM_VERTEX))
    cv.paint(WHITE, dot(*center, PRIM_CENTER))
    return cv.to_image()


ICONS = {
    "line": line_icon,
    "bezier": bezier_icon,
    "rectangle": rectangle_icon,
    "polygon": polygon_icon,
    "circle": circle_icon,
    "union": lambda: boolean_icon('union'),
    "intersection": lambda: boolean_icon('intersection'),
    "difference": lambda: boolean_icon('difference'),
    "split_active": lambda: split_icon(False),
    "split_all": lambda: split_icon(True),
    "round": round_icon,
    "bridge": bridge_icon,
    "corner": corner_icon,
}


def preview_sheet(images, scale=6):
    pad = 8
    w = len(images) * (OUT * scale + pad) + pad
    sheet = Image.new("RGBA", (w, 2 * (OUT * scale + pad) + pad), (0, 0, 0, 255))
    for row, bg in enumerate(((61, 61, 61, 255), (190, 190, 190, 255))):
        for i, img in enumerate(images):
            x = pad + i * (OUT * scale + pad)
            y = pad + row * (OUT * scale + pad)
            tile = Image.new("RGBA", (OUT * scale, OUT * scale), bg)
            big = img.resize((OUT * scale, OUT * scale), Image.NEAREST)
            tile.alpha_composite(big)
            sheet.paste(tile, (x, y))
    return sheet


def main():
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    images = []
    for name, make in ICONS.items():
        img = make()
        img.save(out_dir / f"{name}.png")
        images.append(img)
    if len(sys.argv) > 2:
        preview_sheet(images).save(sys.argv[2])


if __name__ == "__main__":
    main()
