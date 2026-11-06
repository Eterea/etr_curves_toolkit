# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Generate the icons of the Curve Toolkit panel: 32x32 PNG files (what the
extension loads) and, optionally, the same icons as SVG files to edit them by
hand (Affinity, Inkscape, Illustrator...).

Usage:
    python make_icons.py <png_dir> [<preview.png>] [--svg <svg_dir>]
                         [--sheet <all_icons.svg>]

--sheet writes every icon into one SVG document, in the order of the panel,
on a grid of 32 x 32 px cells with no gaps (6 x 6 for the 33 icons, the last
three cells empty), to edit them all at once with 32 px slices.

Every icon is described once, as shapes (lines, cubic Bezier curves, circles,
rounded rectangles, points), and drawn by two backends:

  - PNG: rasterized at 512x512 and reduced with premultiplied alpha, so edges
    are smooth on any Blender theme.
  - SVG: a 32x32 document with the same shapes as real vector objects (cubic
    curves stay cubic, circles stay circles, strokes keep their width). The
    regions of the booleans and the gaps of the splits are clip paths, never
    SVG masks, which some programs ignore.

Shapes of some icons adjusted in v0.24.0 from the to_do_27
mockup (Line / Point, Bridge, Slice, Points Along Curve, Handles to Axis,
Tangents from Point, the inscribed and tangent circles, Tangents to 2
Circles and Perpendicular from Point).

Style (v0.23.0, from the to_do_26 mockup): only two tones, white and grey,
with no accent colors. As a rule, what the tool makes or acts on is white and
the context is grey. Every line has the same width (STROKE) and every point
the same size (DOT); cuts are drawn as gaps (transparent dots). These
constants are the knobs to tune the whole set at once.
"""

import math
import sys
from pathlib import Path as FsPath

import numpy as np
from PIL import Image, ImageDraw

BIG = 512
OUT = 32

GRAY = (128, 128, 128)
FILL = (101, 101, 101)
WHITE = (255, 255, 255)

# The icons are drawn on a 0..1 square that is then fitted inside the icon
# with a small margin (FIT), so the points at its edges are not cut off. The
# sizes below are measured before that: in the icon they are FIT times them
# (STROKE 0.087 is 2.56 px of the 32 px icon, DOT 0.103 a radius of 3.03 px).
FIT = 0.92
STROKE = 0.087           # width of every line
DOT = 0.103              # radius of every point
GAP = 0.075              # radius of the gap of a cut
CLEAR = 0.035            # space left between a grey ring and the white lines
                         # it sits next to (inscribed / tangent circles)
SQUARE = (0.08, 0.08, 0.63, 0.63)
CIRCLE_C = (0.62, 0.62)
CIRCLE_R = 0.29


# -----------------------------------------------------------------------------
# Paths: sampled points (for the PNG and for the geometry of the icons) that
# remember their exact segments (for the SVG)
# -----------------------------------------------------------------------------

class Path(list):
    """A list of points along a path, with its exact segments in `segs`:
    ('L', point) or ('C', handle, handle, point), from `start`."""

    def __init__(self, start, segs, closed=False, samples=120):
        self.start = start
        self.segs = list(segs)
        self.closed = closed
        pts = [start]
        prev = start
        for seg in self.segs:
            if seg[0] == 'L':
                pts += _densify_pair(prev, seg[1])
            else:
                _, h0, h1, p = seg
                pts += [_cubic(prev, h0, h1, p, i / samples) for i in range(1, samples + 1)]
            prev = seg[-1]
        if closed:
            pts += _densify_pair(prev, start)
        super().__init__(pts)

    def __add__(self, other):
        """The two paths one after the other (the second one starts where
        the first one ends)."""
        segs = list(self.segs)
        if math.dist(self.end(), other.start) > 1e-9:
            segs.append(('L', other.start))
        return Path(self.start, segs + other.segs)

    def end(self):
        return self.segs[-1][-1] if self.segs else self.start

    def mapped(self, fn):
        """The same path with every point (and handle) through `fn`."""
        return Path(fn(self.start),
                    [(s[0],) + tuple(fn(p) for p in s[1:]) for s in self.segs], self.closed)


def _cubic(p0, p1, p2, p3, t):
    u = 1 - t
    return (u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
            u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1])


def _densify_pair(a, b, step=0.003):
    n = max(1, int(math.dist(a, b) / step))
    return [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
            for i in range(1, n + 1)]


def bezier(p0, p1, p2, p3):
    return Path(p0, [('C', p1, p2, p3)])


def polyline(points, closed=False):
    return Path(points[0], [('L', p) for p in points[1:]], closed)


def regular_polygon(center, radius, sides, start_angle=math.pi / 2):
    """Vertices of a regular polygon, first one at `start_angle` (default the
    +Y axis, at 12 o'clock, as the Polygon primitive makes it)."""
    cx, cy = center
    return [(cx + radius * math.cos(start_angle + 2 * math.pi * i / sides),
             cy - radius * math.sin(start_angle + 2 * math.pi * i / sides))
            for i in range(sides)]


# -----------------------------------------------------------------------------
# Shapes. Rings and rectangles are stroked inwards: their outer edge is the
# size given (radius, box), the way the first icons were drawn.
# -----------------------------------------------------------------------------

def circle(center, radius):
    return ('circle', center, radius)


def rect(lo, hi, radius=0.0):
    """lo, hi: (x, y) corners; radius: of the rounded corners (outer edge)."""
    return ('rect', lo, hi, radius)


def polygon(points):
    return ('polygon', list(points))


def square_shape():
    return rect(SQUARE[:2], SQUARE[2:])


def circle_shape():
    return circle(CIRCLE_C, CIRCLE_R)


# -----------------------------------------------------------------------------
# The drawing: a list of operations, drawn by both backends
# -----------------------------------------------------------------------------

class Drawing:
    """Operations of one icon, in painting order:
      ('stroke', color, shape or Path, clips)
      ('fill',   color, shape, clips)
      ('erase',  shape)                  a transparent gap in what is below
    clips: tuple of (shape, inside), all of which must hold: the area of the
    shape (inside=True) or everything out of it (inside=False).
    """

    def __init__(self):
        self.ops = []

    # -- Building --------------------------------------------------------------

    def line(self, color, points, closed=False, clips=()):
        path = points if isinstance(points, Path) else polyline(points, closed)
        self.ops.append(('stroke', color, path, tuple(clips)))

    def ring(self, color, center, radius, clips=()):
        """A ring whose OUTER edge has the given radius (stroked inwards)."""
        self.ops.append(('stroke', color, circle(center, radius), tuple(clips)))

    def ring_mid(self, color, center, radius, clips=()):
        """A ring whose CENTER LINE has the given radius, so points and lines
        that touch it at that radius sit on the middle of the stroke."""
        self.ring(color, center, radius + STROKE / 2, clips)

    def stroke(self, color, shape, clips=()):
        self.ops.append(('stroke', color, shape, tuple(clips)))

    def fill(self, color, shape, clips=()):
        self.ops.append(('fill', color, shape, tuple(clips)))

    def dots(self, color, points, radius=DOT):
        for p in points:
            self.fill(color, circle(p, radius))

    def erase(self, shape):
        self.ops.append(('erase', shape))

    # -- PNG -------------------------------------------------------------------

    def to_png(self):
        rgb = np.zeros((BIG, BIG, 3), dtype=np.float32)
        alpha = np.zeros((BIG, BIG), dtype=np.float32)
        for op in self.ops:
            if op[0] == 'erase':
                alpha *= 1 - _fill_mask(op[1])
                continue
            kind, color, shape, clips = op
            mask = _stroke_mask(shape) if kind == 'stroke' else _fill_mask(shape)
            for clip, inside in clips:
                area = _fill_mask(clip) > 0.5
                mask = mask * (area if inside else ~area)
            col = np.array(color, dtype=np.float32) / 255.0
            rgb = rgb * (1 - mask[..., None]) + col * mask[..., None]
            alpha = alpha * (1 - mask) + mask
        # Premultiplied downsample (no dark halos on transparent edges), after
        # fitting the drawing inside the margin.
        pre = np.dstack([_fitted(rgb[..., i] * alpha) for i in range(3)])
        alpha = _fitted(alpha)
        k = BIG // OUT
        pre = pre.reshape(OUT, k, OUT, k, 3).mean(axis=(1, 3))
        a = alpha.reshape(OUT, k, OUT, k).mean(axis=(1, 3))
        out_rgb = np.where(a[..., None] > 1e-6, pre / np.maximum(a[..., None], 1e-6), 0)
        out = np.dstack([out_rgb, a])
        return Image.fromarray((np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA")

    # -- SVG -------------------------------------------------------------------

    def to_svg(self, title=""):
        defs, body = self.svg_parts()
        lines = ['<?xml version="1.0" encoding="UTF-8"?>',
                 f'<svg xmlns="http://www.w3.org/2000/svg" width="{OUT}" height="{OUT}" '
                 f'viewBox="0 0 {OUT} {OUT}">']
        if title:
            lines.append(f'  <title>{title}</title>')
        if defs:
            lines.append('  <defs>')
            lines += ['    ' + d for d in defs]
            lines.append('  </defs>')
        lines += ['  ' + e for e in body]
        lines.append('</svg>')
        return "\n".join(lines) + "\n"

    def svg_parts(self, prefix=""):
        """(defs, body): the clip paths and the elements of the icon, in the
        coordinates of its 32 x 32 document. `prefix` goes in front of the
        ids of the clip paths, so several icons can share one document."""
        defs, body = [], []
        clip_ids = {}

        def clip_id(clip):
            key = repr(clip)
            if key not in clip_ids:
                shape, inside = clip
                cid = f"{prefix}clip{len(clip_ids) + 1}"
                clip_ids[key] = cid
                if inside:
                    inner = _svg_shape(shape, fill=True)
                else:
                    # Everything but the shape: a frame around the icon with
                    # the shape as a hole (even-odd).
                    inner = (f'<path clip-rule="evenodd" d="M-1 -1H{OUT + 1}V{OUT + 1}H-1Z '
                             f'{_svg_outline(shape)}"/>')
                defs.append(f'<clipPath id="{cid}">{inner}</clipPath>')
            return clip_ids[key]

        for op in self.ops:
            if op[0] == 'erase':
                cid = clip_id((op[1], False))
                body = [f'<g clip-path="url(#{cid})">'] + ["  " + e for e in body] + ['</g>']
                continue
            kind, color, shape, clips = op
            element = _svg_shape(shape, fill=(kind == 'fill'), color=_hex(color))
            for clip in clips:
                element = f'<g clip-path="url(#{clip_id(clip)})">{element}</g>'
            body.append(element)
        return defs, body


# -- PNG helpers ----------------------------------------------------------------

def _px(v):
    return v * BIG


def _blank():
    return Image.new("L", (BIG, BIG), 0)


def _array(img):
    return np.asarray(img, dtype=np.float32) / 255.0


def _width():
    return round(_px(STROKE))


def _fill_mask(shape):
    img = _blank()
    d = ImageDraw.Draw(img)
    if shape[0] == 'circle':
        _, (x, y), r = shape
        d.ellipse([_px(x - r), _px(y - r), _px(x + r), _px(y + r)], fill=255)
    elif shape[0] == 'rect':
        _, lo, hi, r = shape
        box = [_px(lo[0]), _px(lo[1]), _px(hi[0]), _px(hi[1])]
        if r > 0:
            d.rounded_rectangle(box, radius=_px(r), fill=255)
        else:
            d.rectangle(box, fill=255)
    else:  # polygon
        d.polygon([(_px(x), _px(y)) for x, y in shape[1]], fill=255)
    return _array(img)


def _stroke_mask(shape):
    img = _blank()
    d = ImageDraw.Draw(img)
    if isinstance(shape, Path):
        r = _px(STROKE) / 2
        for x, y in shape:
            d.ellipse([_px(x) - r, _px(y) - r, _px(x) + r, _px(y) + r], fill=255)
    elif shape[0] == 'circle':
        _, (x, y), r = shape
        d.ellipse([_px(x - r), _px(y - r), _px(x + r), _px(y + r)], outline=255,
                  width=_width())
    elif shape[0] == 'rect':
        _, lo, hi, r = shape
        box = [_px(lo[0]), _px(lo[1]), _px(hi[0]), _px(hi[1])]
        if r > 0:
            d.rounded_rectangle(box, radius=_px(r), outline=255, width=_width())
        else:
            d.rectangle(box, outline=255, width=_width())
    return _array(img)


def _fitted(channel):
    """A channel of the canvas shrunk by FIT about its center (margin)."""
    n = round(BIG * FIT)
    small = Image.fromarray(channel.astype(np.float32), "F").resize((n, n), Image.BOX)
    out = np.zeros((BIG, BIG), dtype=np.float32)
    off = (BIG - n) // 2
    out[off:off + n, off:off + n] = np.asarray(small)
    return out


# -- SVG helpers ----------------------------------------------------------------

def _x(v):
    """Coordinate of the 0..1 square in the 32 px icon (margin included)."""
    return (0.5 + (v - 0.5) * FIT) * OUT


def _len(v):
    return v * FIT * OUT


def _n(v):
    return f"{v:.3f}".rstrip("0").rstrip(".")


def _pt(p):
    return f"{_n(_x(p[0]))} {_n(_x(p[1]))}"


def _hex(color):
    return "#%02x%02x%02x" % color


def _svg_path_d(path):
    d = [f"M{_pt(path.start)}"]
    for seg in path.segs:
        if seg[0] == 'L':
            d.append(f"L{_pt(seg[1])}")
        else:
            d.append(f"C{_pt(seg[1])} {_pt(seg[2])} {_pt(seg[3])}")
    if path.closed:
        d.append("Z")
    return " ".join(d)


def _svg_outline(shape):
    """Path data of the area of a shape, as a hole: counter-clockwise on the
    screen, against the clockwise frame around it, so the hole is there with
    either fill rule (some programs ignore clip-rule)."""
    if shape[0] == 'circle':
        _, (x, y), r = shape
        cx, cy, rr = _x(x), _x(y), _len(r)
        return (f"M{_n(cx - rr)} {_n(cy)}A{_n(rr)} {_n(rr)} 0 1 0 {_n(cx + rr)} {_n(cy)}"
                f"A{_n(rr)} {_n(rr)} 0 1 0 {_n(cx - rr)} {_n(cy)}Z")
    if shape[0] == 'rect':
        _, lo, hi, _r = shape
        return f"M{_pt(lo)}V{_n(_x(hi[1]))}H{_n(_x(hi[0]))}V{_n(_x(lo[1]))}Z"
    pts = list(shape[1])
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))
    if area > 0:                    # clockwise on the screen (y down)
        pts.reverse()
    return "M" + "L".join(_pt(p) for p in pts) + "Z"


def _svg_shape(shape, fill, color="#000000"):
    """One SVG element. Strokes of rings and rectangles go inwards, as in the
    PNG: the element is drawn half a stroke smaller."""
    w = _len(STROKE)
    paint = (f'fill="{color}"' if fill else
             f'fill="none" stroke="{color}" stroke-width="{_n(w)}" '
             'stroke-linecap="round" stroke-linejoin="round"')
    if isinstance(shape, Path):
        return f'<path d="{_svg_path_d(shape)}" {paint}/>'
    inset = 0.0 if fill else w / 2
    if shape[0] == 'circle':
        _, (x, y), r = shape
        return (f'<circle cx="{_n(_x(x))}" cy="{_n(_x(y))}" r="{_n(_len(r) - inset)}" '
                f'{paint}/>')
    if shape[0] == 'rect':
        _, lo, hi, r = shape
        x0, y0 = _x(lo[0]) + inset, _x(lo[1]) + inset
        x1, y1 = _x(hi[0]) - inset, _x(hi[1]) - inset
        rx = f' rx="{_n(max(_len(r) - inset, 0.0))}"' if r > 0 else ""
        if not fill and r == 0:
            paint = paint.replace('stroke-linejoin="round"', 'stroke-linejoin="miter"')
        return (f'<rect x="{_n(x0)}" y="{_n(y0)}" width="{_n(x1 - x0)}" '
                f'height="{_n(y1 - y0)}"{rx} {paint}/>')
    pts = " ".join(_pt(p) for p in shape[1])
    return f'<polygon points="{pts}" {paint}/>'


# -----------------------------------------------------------------------------
# Icons
# -----------------------------------------------------------------------------

def _on_circle(center, radius, degrees):
    """Point of a circle at an angle measured clockwise from 12 o'clock."""
    a = math.radians(degrees)
    return (center[0] + radius * math.sin(a), center[1] - radius * math.cos(a))


def _line_cross(a, b, c, d):
    """Crossing point of the lines a-b and c-d."""
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    t = ((c[0] - a[0]) * sy - (c[1] - a[1]) * sx) / (rx * sy - ry * sx)
    return (a[0] + rx * t, a[1] + ry * t)


def _even_along(points, count):
    """`count` points spread along a polyline at equal lengths, ends
    excluded."""
    lengths = [0.0]
    for a, b in zip(points, points[1:]):
        lengths.append(lengths[-1] + math.dist(a, b))
    out = []
    for i in range(1, count + 1):
        target = lengths[-1] * i / (count + 1)
        k = next(k for k in range(1, len(lengths)) if lengths[k] >= target)
        t = (target - lengths[k - 1]) / max(lengths[k] - lengths[k - 1], 1e-12)
        a, b = points[k - 1], points[k]
        out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


def _arrow_head(tip, direction, size=0.20):
    """Solid triangular arrow head pointing along `direction` from `tip`."""
    dx, dy = direction
    n = math.hypot(dx, dy)
    ux, uy = dx / n, dy / n
    bx, by = tip[0] - ux * size, tip[1] - uy * size
    w = size * 0.62
    return polygon([tip, (bx - uy * w, by + ux * w), (bx + uy * w, by - ux * w)])


# --- Create Curves: primitives ------------------------------------------------

def line_icon():
    """Line / Point: a line of three points, a line of two and a single
    point."""
    cv = Drawing()
    # v0.24.0 (to_do_27 mockup): a shorter short line, near the corner, and
    # the single point at its mirror place across the long one.
    long_line = ((0.12, 0.12), (0.50, 0.50), (0.88, 0.88))
    short_line = ((0.12, 0.645), (0.345, 0.875))
    cv.line(WHITE, (long_line[0], long_line[-1]))
    cv.line(WHITE, short_line)
    cv.dots(WHITE, long_line + short_line + ((0.78, 0.23),))
    return cv


def bezier_icon():
    a, b = (0.12, 0.16), (0.88, 0.88)
    cv = Drawing()
    cv.line(WHITE, bezier(a, (0.42, 0.02), (0.66, 0.58), b))
    cv.dots(WHITE, (a, b))
    return cv


def rectangle_icon():
    lo, hi = 0.12, 0.88
    corners = [(lo, lo), (hi, lo), (hi, hi), (lo, hi)]
    cv = Drawing()
    cv.line(WHITE, corners, closed=True)
    cv.dots(WHITE, corners)
    return cv


def polygon_icon(sides=6, radius=0.40):
    center = (0.5, 0.5)
    verts = regular_polygon(center, radius, sides)
    cv = Drawing()
    cv.line(WHITE, verts, closed=True)
    cv.dots(WHITE, verts + [center])
    return cv


def circle_icon(radius=0.40):
    center = (0.5, 0.5)
    cv = Drawing()
    cv.ring(WHITE, center, radius)
    cv.dots(WHITE, regular_polygon(center, radius, 4) + [center])
    return cv


# --- Create Curves: circles from points ---------------------------------------
#
# The circle in grey, the picked points (and the lines they make) in white.

CIRC_C = (0.5, 0.5)
CIRC_R = 0.40


def circle_center_point_icon():
    cv = Drawing()
    cv.ring(GRAY, CIRC_C, CIRC_R)
    cv.dots(WHITE, (_on_circle(CIRC_C, CIRC_R, 0), CIRC_C))
    return cv


def circle_2_points_icon():
    cv = Drawing()
    cv.ring(GRAY, CIRC_C, CIRC_R)
    cv.dots(WHITE, (_on_circle(CIRC_C, CIRC_R, 0), _on_circle(CIRC_C, CIRC_R, 180)))
    return cv


def circle_3_points_icon():
    cv = Drawing()
    cv.ring(GRAY, CIRC_C, CIRC_R)
    cv.dots(WHITE, [_on_circle(CIRC_C, CIRC_R, a) for a in (0, 101, 238)])
    return cv


def circle_segment_center_icon():
    center, radius = (0.5, 0.56), 0.36
    y = center[1] - radius
    a, b = (0.10, y), (0.90, y)
    cv = Drawing()
    cv.ring(GRAY, center, radius)
    cv.line(WHITE, (a, b))
    cv.dots(WHITE, (a, b, center))
    return cv


def _incircle_2d(a, b, c):
    la, lb, lc = math.dist(b, c), math.dist(a, c), math.dist(a, b)
    per = la + lb + lc
    center = ((la * a[0] + lb * b[0] + lc * c[0]) / per,
              (la * a[1] + lb * b[1] + lc * c[1]) / per)
    area2 = abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]))
    return center, area2 / per


#: The three points of the triangle (and of the two segments) of the mockup,
#: kept far enough from the edges for the points not to be cut off.
TRI = ((0.10, 0.48), (0.74, 0.10), (0.89, 0.89))


def circle_inscribed_icon():
    a, b, c = TRI
    center, radius = _incircle_2d(a, b, c)
    cv = Drawing()
    # A little smaller than the incircle, so it does not touch the sides.
    cv.ring(GRAY, center, radius - STROKE / 2 - CLEAR)
    cv.line(WHITE, (a, b, c), closed=True)
    cv.dots(WHITE, (a, b, c))
    return cv


def circle_tangent_2_icon():
    """Two white segments meeting at a corner, the grey circle tangent to
    both and its center."""
    a, corner, b = TRI
    u1 = (a[0] - corner[0], a[1] - corner[1])
    u2 = (b[0] - corner[0], b[1] - corner[1])
    n1, n2 = math.hypot(*u1), math.hypot(*u2)
    u1, u2 = (u1[0] / n1, u1[1] / n1), (u2[0] / n2, u2[1] / n2)
    half = math.acos(u1[0] * u2[0] + u1[1] * u2[1]) / 2
    bis = (u1[0] + u2[0], u1[1] + u2[1])
    nb = math.hypot(*bis)
    radius = 0.25
    # The circle stands CLEAR away from both segments (it does not touch them).
    d = (radius + STROKE / 2 + CLEAR) / math.sin(half)
    center = (corner[0] + bis[0] / nb * d, corner[1] + bis[1] / nb * d)
    cv = Drawing()
    cv.ring(GRAY, center, radius)
    cv.line(WHITE, (a, corner, b))
    cv.dots(WHITE, (a, corner, b, center))
    return cv


# --- Create Curves: construction lines ----------------------------------------

def tangents_2_circles_icon():
    """Two grey circles along the diagonal and their two outer tangents in
    white (v0.24.0, to_do_27 mockup: larger circles, on the diagonal).
    The radii are those of the center lines of the rings, where the tangents
    touch them."""
    c1, r1 = (0.315, 0.31), 0.265
    c2, r2 = (0.735, 0.79), 0.16
    cv = Drawing()
    for c, r in ((c1, r1), (c2, r2)):
        cv.ring_mid(GRAY, c, r)
    d = math.dist(c1, c2)
    ux, uy = (c2[0] - c1[0]) / d, (c2[1] - c1[1]) / d
    alpha = math.acos((r1 - r2) / d)
    for sign in (1, -1):
        a = math.atan2(uy, ux) + sign * alpha
        nx, ny = math.cos(a), math.sin(a)
        p1 = (c1[0] + r1 * nx, c1[1] + r1 * ny)
        p2 = (c2[0] + r2 * nx, c2[1] + r2 * ny)
        cv.line(WHITE, (p1, p2))
        cv.dots(WHITE, (p1, p2))
    return cv


def tangents_from_point_icon():
    """A grey circle, a point outside it and the two white lines from the
    point that touch the circle (v0.24.0: a larger circle). The radius is the
    one of the center line of the ring, where the lines touch it."""
    c, r = (0.42, 0.385), 0.31
    p = (0.87, 0.88)
    dx, dy = p[0] - c[0], p[1] - c[1]
    d = math.hypot(dx, dy)
    base = math.atan2(dy, dx)
    spread = math.acos(r / d)
    touch = [(c[0] + r * math.cos(base + s * spread), c[1] + r * math.sin(base + s * spread))
             for s in (1, -1)]
    cv = Drawing()
    cv.ring_mid(GRAY, c, r)
    for t in touch:
        cv.line(WHITE, (p, t))
    cv.dots(WHITE, touch + [p])
    return cv


def perpendicular_icon():
    """A grey S curve and the white perpendicular through one of its points
    (v0.24.0: a taller S, the point lower on its rising part)."""
    curve = bezier((0.10, 0.92), (0.38, 0.93), (0.37, -0.11), (0.89, 0.08))
    target = (0.45, 0.345)
    k = min(range(2, len(curve) - 2), key=lambda i: math.dist(curve[i], target))
    mid = curve[k]
    a, b = curve[k - 2], curve[k + 2]
    tx, ty = b[0] - a[0], b[1] - a[1]
    n = math.hypot(tx, ty)
    nx, ny = -ty / n, tx / n
    half = 0.36
    cv = Drawing()
    cv.line(GRAY, curve)
    cv.line(WHITE, ((mid[0] + nx * half, mid[1] + ny * half),
                    (mid[0] - nx * half, mid[1] - ny * half)))
    cv.dots(WHITE, (mid,))
    return cv


# --- Create Curves: construction points ---------------------------------------

def lines_from_points_icon():
    """As the Rectangle, but an irregular four-sided shape."""
    corners = [(0.10, 0.22), (0.74, 0.10), (0.90, 0.86), (0.30, 0.72)]
    cv = Drawing()
    cv.line(WHITE, corners, closed=True)
    cv.dots(WHITE, corners)
    return cv


def points_in_between_icon():
    """The two picked points in grey at the ends of a diagonal, the new ones
    between them in white."""
    a, b = (0.12, 0.12), (0.88, 0.88)
    pts = [(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
           for t in (0.0, 0.25, 0.5, 0.75, 1.0)]
    cv = Drawing()
    cv.dots(GRAY, (pts[0], pts[-1]))
    cv.dots(WHITE, pts[1:-1])
    return cv


def points_along_curve_icon():
    """A grey arc open to the left and the white points spread along it
    (v0.24.0, to_do_27 mockup)."""
    curve = bezier((0.15, 0.18), (0.83, -0.175), (1.16, 0.71), (0.45, 0.94))
    cv = Drawing()
    cv.line(GRAY, curve)
    cv.dots(WHITE, _even_along(curve, 3))
    return cv


def points_at_intersections_icon():
    long_line = ((0.17, 0.10), (0.92, 0.87))
    shorts = (((0.08, 0.47), (0.73, 0.22)), ((0.49, 0.90), (0.91, 0.40)))
    cv = Drawing()
    for line in (long_line, *shorts):
        cv.line(GRAY, line)
    cv.dots(WHITE, [_line_cross(*long_line, *s) for s in shorts])
    return cv


# --- Curve Booleans -----------------------------------------------------------

def boolean_icon(kind):
    """The result filled, its outline in white; the rest of the lines in
    grey."""
    sq, ci = square_shape(), circle_shape()
    in_s, out_s, in_c, out_c = (sq, True), (sq, False), (ci, True), (ci, False)
    cv = Drawing()
    if kind == 'union':
        cv.fill(FILL, sq)
        cv.fill(FILL, ci)
        cv.stroke(GRAY, sq, (in_c,))
        cv.stroke(WHITE, sq, (out_c,))
        cv.stroke(WHITE, ci, (out_s,))
    elif kind == 'intersection':
        cv.stroke(GRAY, sq, (out_c,))
        cv.stroke(GRAY, ci, (out_s,))
        cv.fill(FILL, sq, (in_c,))
        cv.stroke(WHITE, sq, (in_c,))
        cv.stroke(WHITE, ci, (in_s,))
    else:  # difference: the square bitten by the circle
        cv.stroke(GRAY, ci, (out_s,))
        cv.fill(FILL, sq, (out_c,))
        cv.stroke(GRAY, sq, (in_c,))
        cv.stroke(WHITE, sq, (out_c,))
        cv.stroke(WHITE, ci, (in_s,))
    return cv


def split_icon(split_all):
    """The square and the circle cut where they cross (two gaps). Split
    Active: only the square (the active curve) in white."""
    cv = Drawing()
    cv.stroke(WHITE if split_all else GRAY, circle_shape())
    cv.stroke(WHITE, square_shape())
    cx, cy = CIRCLE_C
    hi = SQUARE[2]
    # Where the circle crosses the right and the bottom side of the square.
    dx = math.sqrt(CIRCLE_R ** 2 - (hi - cx) ** 2)
    for p in ((hi, cy - dx), (cx - dx, hi)):
        cv.erase(circle(p, GAP))
    return cv


def symmetrize_icon():
    """A heart: the kept half in grey, the mirrored one in white, the dotted
    axis in grey and the two welded points on it in white."""
    top, tip = (0.5, 0.25), (0.5, 0.86)
    left = (bezier(top, (0.40, 0.06), (0.06, 0.08), (0.07, 0.34))
            + bezier((0.07, 0.34), (0.08, 0.56), (0.42, 0.66), tip))
    right = left.mapped(lambda p: (1.0 - p[0], p[1]))
    cv = Drawing()
    cv.dots(GRAY, [(0.5, 0.03 + i * 0.105) for i in range(10)], 0.03)
    cv.line(GRAY, left)
    cv.line(WHITE, right)
    cv.dots(WHITE, (top, tip))
    return cv


# --- Shaping Splines ----------------------------------------------------------

def round_icon():
    """A rounded square: the rounded corners in white, the straight sides in
    grey, and four points inside."""
    lo, hi, r = 0.10, 0.90, 0.20
    shape = rect((lo, lo), (hi, hi), r)
    # The corners: out of the vertical and of the horizontal middle bands.
    bands = ((rect((lo + r, 0.0), (hi - r, 1.0)), False),
             (rect((0.0, lo + r), (1.0, hi - r)), False))
    cv = Drawing()
    cv.stroke(GRAY, shape)
    cv.stroke(WHITE, shape, bands)
    cv.dots(WHITE, ((0.33, 0.33), (0.67, 0.33), (0.33, 0.67), (0.67, 0.67)))
    return cv


def bridge_icon():
    """Two grey curves and the white bridge between their ends (v0.24.0,
    to_do_27 mockup: smaller, the bridge a tighter hook)."""
    def at(p):
        return (p[0] + 0.10, p[1] + 0.05)
    a = bezier(at((0.05, 0.755)), at((0.20, 0.65)), at((0.33, 0.686)), at((0.413, 0.704)))
    b = bezier(at((0.515, 0.14)), at((0.613, 0.229)), at((0.646, 0.296)), at((0.702, 0.443)))
    bridge = bezier(a.end(), at((0.47, 0.79)), at((0.79, 0.765)), b.end())
    cv = Drawing()
    cv.line(GRAY, a)
    cv.line(GRAY, b)
    cv.line(WHITE, bridge)
    cv.dots(WHITE, (a.end(), b.end()))
    return cv


def corner_icon():
    """Arcs to Corners: the rounded corner in grey, the hard corner it turns
    into in white, with its three points."""
    a, b = (0.40, 0.85), (0.85, 0.42)        # ends of the arc
    corner = (0.85, 0.85)
    arc = bezier(a, (a[0] + 0.25, a[1]), (b[0], b[1] + 0.24), b)
    cv = Drawing()
    cv.line(GRAY, ((0.08, 0.85), a))
    cv.line(GRAY, (b, (0.85, 0.08)))
    cv.line(GRAY, arc)
    cv.line(WHITE, (a, corner, b))
    cv.dots(WHITE, (a, corner, b))
    return cv


def handles_to_axis_icon():
    """A grey curve leaving a point; its old, tilted handle in grey and the
    handle turned onto the axis in white (v0.24.0: lower and narrower, and a
    shorter old handle)."""
    point = (0.14, 0.21)
    old_end, new_end = (0.835, 0.395), (0.87, 0.21)
    slope = (old_end[1] - point[1]) / (old_end[0] - point[0])
    curve = bezier(point, (0.43, point[1] + 0.29 * slope), (0.63, 0.40), (0.61, 0.92))
    cv = Drawing()
    cv.line(GRAY, curve)
    cv.line(GRAY, (point, old_end))
    cv.dots(GRAY, (old_end,))
    cv.line(WHITE, (point, new_end))
    cv.dots(WHITE, (point, new_end))
    return cv


def handles_to_lines_icon():
    """A grey Bezier curve and its two handles as white lines."""
    p0, h0, h1, p1 = (0.08, 0.85), (0.35, 0.89), (0.67, 0.15), (0.92, 0.51)
    cv = Drawing()
    cv.line(GRAY, bezier(p0, h0, h1, p1))
    for a, b in ((p0, h0), (p1, h1)):
        cv.line(WHITE, (a, b))
        cv.dots(WHITE, (a, b))
    return cv


def offset_icon():
    """A grey square and, around it, its offset in white with rounded
    corners."""
    lo, hi = 0.32, 0.68
    cv = Drawing()
    cv.line(GRAY, [(lo, lo), (hi, lo), (hi, hi), (lo, hi)], closed=True)
    cv.stroke(WHITE, rect((0.08, 0.08), (0.92, 0.92), 0.26))
    return cv


def extend_icon():
    """A grey curve, its end point and the extension in white, following its
    direction, with an arrow head."""
    start = (0.08, 0.90)
    curve = bezier(start, (0.36, 0.90), (0.48, 0.74), (0.55, 0.55))
    end = curve.end()
    tip = (0.82, 0.10)
    direction = (tip[0] - end[0], tip[1] - end[1])
    cv = Drawing()
    cv.line(GRAY, curve)
    cv.dots(GRAY, (start,))
    cv.line(WHITE, (end, (0.75, 0.22)))
    cv.fill(WHITE, _arrow_head(tip, direction, 0.24))
    cv.dots(WHITE, (end,))
    return cv


def slide_point_icon():
    """A grey arch with its end points, the slid point in white and a white
    arrow above it, in the direction it slides."""
    curve = bezier((0.08, 0.88), (0.24, 0.32), (0.76, 0.32), (0.92, 0.88))
    cv = Drawing()
    cv.line(GRAY, curve)
    cv.dots(GRAY, (curve.start, curve.end()))
    cv.line(WHITE, ((0.22, 0.18), (0.62, 0.18)))
    cv.fill(WHITE, _arrow_head((0.84, 0.18), (1, 0), 0.26))
    cv.dots(WHITE, (curve[72],))
    return cv


def slice_icon():
    """A grey ring (the outer spline and its hole) and the seam between them
    in white, with its two points on the center lines of the rings (v0.24.0:
    a larger hole)."""
    center = (0.5, 0.5)
    outer_r, inner_r = 0.375, 0.15         # center lines
    cv = Drawing()
    cv.ring_mid(GRAY, center, outer_r)
    cv.ring_mid(GRAY, center, inner_r)
    top_outer = (center[0], center[1] - outer_r)
    top_inner = (center[0], center[1] - inner_r)
    cv.line(WHITE, (top_outer, top_inner))
    cv.dots(WHITE, (top_outer, top_inner))
    return cv


ICONS = {
    "line": line_icon,
    "bezier": bezier_icon,
    "rectangle": rectangle_icon,
    "polygon": polygon_icon,
    "circle": circle_icon,
    "circle_center_point": circle_center_point_icon,
    "circle_2_points": circle_2_points_icon,
    "circle_3_points": circle_3_points_icon,
    "circle_inscribed": circle_inscribed_icon,
    "circle_tangent_2": circle_tangent_2_icon,
    "circle_segment_center": circle_segment_center_icon,
    "tangents_2_circles": tangents_2_circles_icon,
    "tangents_from_point": tangents_from_point_icon,
    "perpendicular": perpendicular_icon,
    "lines_from_points": lines_from_points_icon,
    "points_in_between": points_in_between_icon,
    "points_along_curve": points_along_curve_icon,
    "points_at_intersections": points_at_intersections_icon,
    "union": lambda: boolean_icon('union'),
    "intersection": lambda: boolean_icon('intersection'),
    "difference": lambda: boolean_icon('difference'),
    "split_active": lambda: split_icon(False),
    "split_all": lambda: split_icon(True),
    "symmetrize": symmetrize_icon,
    "round": round_icon,
    "bridge": bridge_icon,
    "corner": corner_icon,
    "handles_to_axis": handles_to_axis_icon,
    "handles_to_lines": handles_to_lines_icon,
    "offset": offset_icon,
    "extend": extend_icon,
    "slide_point": slide_point_icon,
    "slice": slice_icon,
}


#: The icons in the order of the panel: the four rows of Create Curves, then
#: Curve Booleans and Shaping Splines from top to bottom.
PALETTE_ORDER = (
    "line", "bezier", "rectangle", "polygon", "circle",
    "circle_center_point", "circle_2_points", "circle_3_points", "circle_inscribed",
    "circle_tangent_2",
    "circle_segment_center", "tangents_2_circles", "tangents_from_point", "perpendicular",
    "lines_from_points", "points_in_between", "points_along_curve", "points_at_intersections",
    "union", "intersection", "difference", "symmetrize", "split_active", "split_all",
    "round", "bridge", "corner", "offset", "extend", "slide_point", "slice",
    "handles_to_axis", "handles_to_lines",
)


def sheet_svg(drawings):
    """One SVG document with every icon, in the order of the panel, on a grid
    of 32 x 32 px cells with no gaps (as square as possible), so slices of
    32 px can be laid over it. The cells after the last icon stay empty."""
    count = len(drawings)
    cols = math.ceil(math.sqrt(count))
    rows = math.ceil(count / cols)
    w, h = cols * OUT, rows * OUT
    defs, groups = [], []
    for i, (name, drawing) in enumerate(drawings):
        d, body = drawing.svg_parts(prefix=f"{name}_")
        defs += d
        x, y = (i % cols) * OUT, (i // cols) * OUT
        groups.append(f'<g id="{name}" transform="translate({x} {y})">')
        groups += ['  ' + e for e in body]
        groups.append('</g>')
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
             f'viewBox="0 0 {w} {h}">']
    if defs:
        lines.append('  <defs>')
        lines += ['    ' + d for d in defs]
        lines.append('  </defs>')
    lines += ['  ' + e for e in groups]
    lines.append('</svg>')
    return "\n".join(lines) + "\n"


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
    args = sys.argv[1:]
    svg_dir = sheet = None
    if "--sheet" in args:
        i = args.index("--sheet")
        sheet = FsPath(args[i + 1])
        del args[i:i + 2]
    if "--svg" in args:
        i = args.index("--svg")
        svg_dir = FsPath(args[i + 1])
        del args[i:i + 2]
    out_dir = FsPath(args[0])
    out_dir.mkdir(parents=True, exist_ok=True)
    if svg_dir is not None:
        svg_dir.mkdir(parents=True, exist_ok=True)
    assert sorted(PALETTE_ORDER) == sorted(ICONS), "PALETTE_ORDER and ICONS differ"
    images, drawings = [], []
    for name in PALETTE_ORDER:
        drawing = ICONS[name]()
        drawings.append((name, drawing))
        img = drawing.to_png()
        img.save(out_dir / f"{name}.png")
        images.append(img)
        if svg_dir is not None:
            (svg_dir / f"{name}.svg").write_text(drawing.to_svg(name), encoding="utf-8")
    if sheet is not None:
        sheet.parent.mkdir(parents=True, exist_ok=True)
        sheet.write_text(sheet_svg(drawings), encoding="utf-8")
    if len(args) > 1:
        preview_sheet(images).save(args[1])


if __name__ == "__main__":
    main()
