"""Generate the documentation icons of Eterea Curves Toolkit.

Every icon is defined here as SVG code, written to this folder as <name>.svg
and rendered to PNG in two sizes. See ../ICON_STYLE.md for the visual rules
(the same ones as the Eterea Blender Tools kit, plus the curve vocabulary).

Usage:  python3 build_icons.py   (requires: pip install cairosvg)
"""
import math
import os

# ---- Palette (shared with Eterea Blender Tools) -----------------------------
TILE      = "#2B2B2B"   # tile background
TILE_EDGE = "#3D3D3D"   # subtle inner border of the tile
G_LIGHT   = "#E3E3E3"   # main lines / primary shapes
G_MID     = "#A3A3A3"   # secondary lines
G_DARK    = "#6E6E6E"   # tertiary lines, "before" parts, guides
G_FILL    = "#484848"   # neutral filled surfaces
G_FILL2   = "#3A3A3A"   # deeper surfaces
ORANGE    = "#FFA31A"   # key accent: the result
ORANGE_D  = "#C2740A"   # darker orange (filled results)
BLUE      = "#4C9BF0"   # second accent: the action, the active point
BLUE_D    = "#2F64A8"   # darker blue

SIZE = 256
RADIUS = 25.6           # 10 % of the side


# ---- Shared helpers ---------------------------------------------------------

def tile():
    return (f'<rect x="0" y="0" width="{SIZE}" height="{SIZE}" rx="{RADIUS}" fill="{TILE}"/>'
            f'<rect x="2" y="2" width="{SIZE-4}" height="{SIZE-4}" rx="{RADIUS-2}" '
            f'fill="none" stroke="{TILE_EDGE}" stroke-width="4"/>')


def svg(body, defs=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{SIZE}" height="{SIZE}" '
            f'viewBox="0 0 {SIZE} {SIZE}">'
            + (f"<defs>{defs}</defs>" if defs else "")
            + tile() + body + "</svg>\n")


def pts(points):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def line(points, color=G_LIGHT, w=12, dash=None, closed=False):
    """Polyline (or polygon) stroke with round caps and joins."""
    tag = "polygon" if closed else "polyline"
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<{tag} points="{pts(points)}" fill="none" stroke="{color}" stroke-width="{w}" '
            f'stroke-linecap="round" stroke-linejoin="round"{d}/>')


def path(d, color=G_LIGHT, w=12, dash=None, fill="none"):
    da = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<path d="{d}" fill="{fill}" stroke="{color}" stroke-width="{w}" '
            f'stroke-linecap="round" stroke-linejoin="round"{da}/>')


def circle(cx, cy, r, color=G_LIGHT, w=12, fill="none", dash=None):
    da = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{fill}" stroke="{color}" '
            f'stroke-width="{w}"{da}/>')


def dot(x, y, color=G_LIGHT, r=12, ring=6):
    """A control point: a filled dot with a knockout ring in the tile color."""
    out = f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r + ring:.1f}" fill="{TILE}"/>' if ring else ""
    return out + f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{color}"/>'


def arrow(x1, y1, x2, y2, color=BLUE, w=10, head=24):
    """Straight arrow with a solid triangular head ending at (x2, y2)."""
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    bx, by = x2 - ux * head, y2 - uy * head
    px, py = -uy * head * 0.6, ux * head * 0.6
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{bx + ux * 2:.1f}" y2="{by + uy * 2:.1f}" '
            f'stroke="{color}" stroke-width="{w}" stroke-linecap="round"/>'
            f'<polygon points="{x2:.1f},{y2:.1f} {bx + px:.1f},{by + py:.1f} {bx - px:.1f},{by - py:.1f}" '
            f'fill="{color}" stroke="{color}" stroke-width="4" stroke-linejoin="round"/>')


def arc_arrow(cx, cy, r, a0, a1, color=BLUE, w=10, head=24):
    """Circular arrow from angle a0 to a1 (degrees, clockwise screen coords)."""
    p = lambda a: (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
    sweep = 1 if a1 > a0 else 0
    large = 1 if abs(a1 - a0) > 180 else 0
    sgn = 1 if a1 > a0 else -1
    a_stop = a1 - sgn * math.degrees(head * 0.8 / r)
    x0, y0 = p(a0)
    xs, ys = p(a_stop)
    xt, yt = p(a1)
    tx, ty = -math.sin(math.radians(a1)) * sgn, math.cos(math.radians(a1)) * sgn
    bx, by = xt - tx * head, yt - ty * head
    nx, ny = -ty * head * 0.6, tx * head * 0.6
    return (f'<path d="M{x0:.1f},{y0:.1f} A{r},{r} 0 {large} {sweep} {xs:.1f},{ys:.1f}" fill="none" '
            f'stroke="{color}" stroke-width="{w}" stroke-linecap="round"/>'
            f'<polygon points="{xt:.1f},{yt:.1f} {bx + nx:.1f},{by + ny:.1f} {bx - nx:.1f},{by - ny:.1f}" '
            f'fill="{color}" stroke="{color}" stroke-width="4" stroke-linejoin="round"/>')


def minus_badge(cx, cy, r=28):
    """Orange 'remove' badge with a knockout ring (motif of the other kit)."""
    return (f'<circle cx="{cx}" cy="{cy}" r="{r + 8}" fill="{TILE}"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{ORANGE}"/>'
            f'<line x1="{cx - r * 0.5}" y1="{cy}" x2="{cx + r * 0.5}" y2="{cy}" stroke="{TILE}" '
            f'stroke-width="10" stroke-linecap="round"/>')


def origin_mark(x, y, color=ORANGE):
    """Blender's object origin: a small ring with a dot."""
    return (f'<circle cx="{x}" cy="{y}" r="22" fill="{TILE}"/>'
            f'<circle cx="{x}" cy="{y}" r="14" fill="none" stroke="{color}" stroke-width="8"/>'
            f'<circle cx="{x}" cy="{y}" r="4" fill="{color}"/>')


def on_circle(cx, cy, r, deg):
    """Point of a circle at an angle measured clockwise from 12 o'clock."""
    a = math.radians(deg)
    return cx + r * math.sin(a), cy - r * math.cos(a)


def regular(cx, cy, r, n, start=0):
    return [on_circle(cx, cy, r, start + 360 * i / n) for i in range(n)]


def wrench(cx, cy, s, color=G_LIGHT):
    """A simple wrench (the Utilities group)."""
    return (f'<g transform="translate({cx},{cy}) rotate(45) scale({s})">'
            f'<rect x="-9" y="-6" width="18" height="70" rx="9" fill="{color}"/>'
            f'<path d="M-30,-40 a32,32 0 1 0 60,0 l-14,0 l0,18 l-32,0 l0,-18 z" fill="{color}"/>'
            f'</g>')


icons = {}

# =============================================================================
# Create Curves: the primitives (the shape in orange, its points in light grey)
# =============================================================================

icons["line"] = svg(line([(60, 196), (196, 60)], ORANGE) + dot(60, 196) + dot(196, 60))

icons["bezier"] = svg(
    line([(52, 168), (110, 76)], G_DARK, 6) + line([(146, 180), (204, 88)], G_DARK, 6)
    + dot(110, 76, G_MID, 8, 4) + dot(146, 180, G_MID, 8, 4)
    + path("M52,168 C110,76 146,180 204,88", ORANGE) + dot(52, 168) + dot(204, 88))

R = [(56, 72), (200, 72), (200, 184), (56, 184)]
icons["rectangle"] = svg(line(R, ORANGE, closed=True) + "".join(dot(x, y) for x, y in R))

H = regular(128, 128, 82, 6)
icons["polygon"] = svg(line(H, ORANGE, closed=True) + "".join(dot(x, y) for x, y in H))

C4 = regular(128, 128, 80, 4)
icons["circle"] = svg(circle(128, 128, 80, ORANGE) + "".join(dot(x, y) for x, y in C4))

# =============================================================================
# Create Curves: from points (picked points in light grey, the active one in
# blue, what the tool makes in orange)
# =============================================================================

icons["points_in_between"] = svg(
    line([(60, 60), (196, 196)], G_DARK, 6, dash="4 16")
    + dot(94, 94, G_MID, 10) + dot(162, 162, G_MID, 10)
    + dot(128, 128, ORANGE, 15) + dot(60, 60, G_LIGHT, 15) + dot(196, 196, G_LIGHT, 15))

LQ = [(52, 84), (184, 52), (212, 196), (76, 172)]
icons["lines_from_points"] = svg(line(LQ, ORANGE, closed=True) + "".join(dot(x, y) for x, y in LQ))

icons["circle_center_point"] = svg(
    circle(128, 132, 76, ORANGE) + line([(128, 132), (128, 56)], G_DARK, 6, dash="10 12")
    + dot(128, 56) + dot(128, 132, BLUE, 16))

icons["circle_2_points"] = svg(
    circle(128, 128, 80, ORANGE) + line([(128, 48), (128, 208)], G_DARK, 6, dash="10 12")
    + dot(128, 48) + dot(128, 208, BLUE, 16))

P3 = [on_circle(128, 128, 80, a) for a in (0, 105, 235)]
icons["circle_3_points"] = svg(
    circle(128, 128, 80, ORANGE) + dot(*P3[1]) + dot(*P3[2]) + dot(*P3[0], BLUE, 16))

icons["circle_segment_center"] = svg(
    circle(128, 140, 68, ORANGE) + line([(48, 72), (208, 72)], G_LIGHT)
    + dot(48, 72) + dot(208, 72) + dot(128, 72, ORANGE, 8, 4) + dot(128, 140, BLUE, 16))


def _incircle(a, b, c):
    la, lb, lc = math.dist(b, c), math.dist(a, c), math.dist(a, b)
    per = la + lb + lc
    center = ((la * a[0] + lb * b[0] + lc * c[0]) / per, (la * a[1] + lb * b[1] + lc * c[1]) / per)
    area2 = abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]))
    return center, area2 / per


T = [(44, 116), (188, 44), (212, 212)]
(icx, icy), ir = _incircle(*T)
icons["circle_inscribed"] = svg(
    line(T, G_LIGHT, closed=True) + circle(icx, icy, ir, ORANGE) + "".join(dot(x, y) for x, y in T))

# Tangent to 2 segments: the circle slides along the bisector of the corner.
A, K, B = (44, 112), (196, 44), (212, 212)
u1 = ((A[0] - K[0]) / math.dist(A, K), (A[1] - K[1]) / math.dist(A, K))
u2 = ((B[0] - K[0]) / math.dist(B, K), (B[1] - K[1]) / math.dist(B, K))
half = math.acos(u1[0] * u2[0] + u1[1] * u2[1]) / 2
bis = (u1[0] + u2[0], u1[1] + u2[1])
nb = math.hypot(*bis)
tr = 52
tc = (K[0] + bis[0] / nb * tr / math.sin(half), K[1] + bis[1] / nb * tr / math.sin(half))
tip = on_circle(tc[0], tc[1], tr, 225)
icons["circle_tangent_2"] = svg(
    line([A, K, B], G_LIGHT) + circle(tc[0], tc[1], tr, ORANGE)
    + line([tc, tip], BLUE, 8) + dot(*A) + dot(*B) + dot(*K, BLUE, 14) + dot(*tc, BLUE, 9, 4))

# =============================================================================
# Create Curves: construction lines
# =============================================================================

def _outer_tangents(c1, r1, c2, r2):
    d = math.dist(c1, c2)
    ang = math.atan2(c2[1] - c1[1], c2[0] - c1[0])
    alpha = math.acos((r1 - r2) / d)
    out = []
    for sign in (1, -1):
        a = ang + sign * alpha
        n = (math.cos(a), math.sin(a))
        out.append(((c1[0] + r1 * n[0], c1[1] + r1 * n[1]), (c2[0] + r2 * n[0], c2[1] + r2 * n[1])))
    return out


_t2c = _outer_tangents((88, 100), 46, (184, 164), 28)
icons["tangents_2_circles"] = svg(
    circle(88, 100, 46, G_LIGHT) + circle(184, 164, 28, G_LIGHT)
    + "".join(line([p, q], ORANGE) for p, q in _t2c)
    + "".join(dot(*p, ORANGE, 10) + dot(*q, ORANGE, 10) for p, q in _t2c))

# The point of the S curve at t = 0.5, and the normal there.
_s = ((44, 196), (124, 212), (132, 44), (212, 60))
_mid = (0.125 * _s[0][0] + 0.375 * _s[1][0] + 0.375 * _s[2][0] + 0.125 * _s[3][0],
        0.125 * _s[0][1] + 0.375 * _s[1][1] + 0.375 * _s[2][1] + 0.125 * _s[3][1])
_tan = (_s[3][0] + _s[2][0] - _s[1][0] - _s[0][0], _s[3][1] + _s[2][1] - _s[1][1] - _s[0][1])
_tl = math.hypot(*_tan)
_nrm = (_tan[1] / _tl, -_tan[0] / _tl)
icons["perpendicular"] = svg(
    path("M44,196 C124,212 132,44 212,60", G_LIGHT)
    + line([_mid, (_mid[0] + _nrm[0] * 84, _mid[1] + _nrm[1] * 84)], ORANGE)
    + line([_mid, (_mid[0] - _nrm[0] * 56, _mid[1] - _nrm[1] * 56)], ORANGE_D, 8, dash="10 14")
    + dot(*_mid, BLUE, 14) + dot(44, 196) + dot(212, 60))

icons["handles_to_lines"] = svg(
    path("M48,184 C104,212 164,40 196,120", G_LIGHT, 8)
    + line([(48, 184), (104, 212)], ORANGE) + line([(196, 120), (164, 40)], ORANGE)
    + dot(104, 212, ORANGE, 11) + dot(164, 40, ORANGE, 11)
    + dot(48, 184) + dot(196, 120))

# =============================================================================
# Curve Booleans and Splits (the square and the circle, as the panel icons)
# =============================================================================

SQ = (52, 52, 136, 136)            # x, y, w, h
CI = (156, 156, 56)                # cx, cy, r
_sq = f'<rect x="{SQ[0]}" y="{SQ[1]}" width="{SQ[2]}" height="{SQ[3]}"/>'
_ci = f'<circle cx="{CI[0]}" cy="{CI[1]}" r="{CI[2]}"/>'
_defs = (f'<clipPath id="sq">{_sq}</clipPath><clipPath id="ci">{_ci}</clipPath>'
         f'<mask id="not_ci"><rect width="256" height="256" fill="white"/>'
         f'<circle cx="{CI[0]}" cy="{CI[1]}" r="{CI[2]}" fill="black"/></mask>'
         f'<mask id="not_sq"><rect width="256" height="256" fill="white"/>'
         f'<rect x="{SQ[0]}" y="{SQ[1]}" width="{SQ[2]}" height="{SQ[3]}" fill="black"/></mask>')


def _sq_stroke(color, w=12, extra=""):
    return (f'<rect x="{SQ[0]}" y="{SQ[1]}" width="{SQ[2]}" height="{SQ[3]}" fill="none" '
            f'stroke="{color}" stroke-width="{w}" stroke-linejoin="round"{extra}/>')


def _ci_stroke(color, w=12, extra=""):
    return (f'<circle cx="{CI[0]}" cy="{CI[1]}" r="{CI[2]}" fill="none" stroke="{color}" '
            f'stroke-width="{w}"{extra}/>')


# Flat overlaps: shapes are painted over each other in the tile color or in the
# fill color (no masks, which not every SVG renderer supports).
_sq_fill = lambda color, inset=0: (
    f'<rect x="{SQ[0] + inset}" y="{SQ[1] + inset}" width="{SQ[2] - 2 * inset}" '
    f'height="{SQ[3] - 2 * inset}" fill="{color}"/>')
_ci_fill = lambda color, grow=0: f'<circle cx="{CI[0]}" cy="{CI[1]}" r="{CI[2] + grow}" fill="{color}"/>'

icons["union"] = svg(
    _sq_fill(ORANGE_D) + _ci_fill(ORANGE_D) + _sq_stroke(ORANGE) + _ci_stroke(ORANGE)
    + _ci_fill(ORANGE_D, -6) + f'<g clip-path="url(#ci)">' + _sq_fill(ORANGE_D) + '</g>'
    + _sq_fill(ORANGE_D, 6) + f'<g clip-path="url(#sq)">' + _ci_fill(ORANGE_D, -6) + '</g>', _defs)

icons["intersection"] = svg(
    _sq_stroke(G_DARK, 6) + _ci_stroke(G_DARK, 6)
    + f'<g clip-path="url(#sq)"><circle cx="{CI[0]}" cy="{CI[1]}" r="{CI[2]}" fill="{ORANGE_D}"/>'
    + _ci_stroke(ORANGE) + '</g>'
    + f'<g clip-path="url(#ci)">' + _sq_stroke(ORANGE) + '</g>', _defs)

icons["difference"] = svg(
    _sq_fill(ORANGE_D) + _sq_stroke(ORANGE) + _ci_fill(TILE, 6)
    + _ci_stroke(BLUE, 6, ' stroke-dasharray="10 12"')
    + f'<g clip-path="url(#sq)">' + _ci_fill(TILE, 6) + _ci_stroke(ORANGE) + '</g>', _defs)

# Splits: the circle is cut where the line crosses it (blue cut points).
_cx, _cy, _r = 128, 136, 72
_gap = 24


def _arc(a0, a1, color):
    p0 = on_circle(_cx, _cy, _r, a0)
    p1 = on_circle(_cx, _cy, _r, a1)
    large = 1 if (a1 - a0) % 360 > 180 else 0
    return path(f"M{p0[0]:.1f},{p0[1]:.1f} A{_r},{_r} 0 {large} 1 {p1[0]:.1f},{p1[1]:.1f}", color)


_cut = 61                                  # angle where y = 101 crosses the circle
_c1, _c2 = on_circle(_cx, _cy, _r, -_cut), on_circle(_cx, _cy, _r, _cut)
icons["split_active"] = svg(
    _arc(-_cut + _gap, _cut - _gap, ORANGE) + _arc(_cut + _gap, 360 - _cut - _gap, ORANGE)
    + line([(44, _c1[1]), (212, _c1[1])], G_MID, 8)
    + dot(*_c1, BLUE, 11) + dot(*_c2, BLUE, 11))
icons["split_all"] = svg(
    _arc(-_cut + _gap, _cut - _gap, ORANGE) + _arc(_cut + _gap, 360 - _cut - _gap, ORANGE)
    + line([(44, _c1[1]), (_c1[0] - 18, _c1[1])], ORANGE_D, 10)
    + line([(_c1[0] + 18, _c1[1]), (_c2[0] - 18, _c2[1])], ORANGE_D, 10)
    + line([(_c2[0] + 18, _c2[1]), (212, _c2[1])], ORANGE_D, 10)
    + dot(*_c1, BLUE, 11) + dot(*_c2, BLUE, 11))

# =============================================================================
# Rounds, Bridge & Corners
# =============================================================================

icons["round_corners"] = svg(
    line([(196, 76), (68, 76), (68, 204)], G_DARK, 6, dash="10 12")
    + line([(196, 76), (140, 76)], G_LIGHT) + line([(68, 148), (68, 204)], G_LIGHT)
    + path("M140,76 A72,72 0 0 0 68,148", ORANGE)
    + dot(140, 76, ORANGE, 11) + dot(68, 148, ORANGE, 11) + dot(196, 76) + dot(68, 204))

icons["bridge_curves"] = svg(
    path("M44,204 C52,176 68,152 88,140", G_LIGHT) + path("M212,204 C204,176 188,152 168,140", G_LIGHT)
    + path("M88,140 C104,72 152,72 168,140", ORANGE)
    + dot(44, 204) + dot(212, 204) + dot(88, 140, BLUE, 12) + dot(168, 140, BLUE, 12))

icons["arcs_to_corners"] = svg(
    path("M140,76 A72,72 0 0 0 68,148", G_DARK, 6, dash="10 12")
    + line([(140, 76), (68, 76), (68, 148)], ORANGE)
    + line([(204, 76), (140, 76)], G_LIGHT) + line([(68, 148), (68, 212)], G_LIGHT)
    + dot(68, 76, ORANGE, 14) + dot(140, 76, BLUE, 10) + dot(68, 148, BLUE, 10))

# =============================================================================
# Offset, Extend, Slide Point, Slice, Merges
# =============================================================================

icons["offset"] = svg(
    f'<rect x="84" y="84" width="88" height="88" rx="10" fill="none" stroke="{G_LIGHT}" stroke-width="12"/>'
    f'<rect x="48" y="48" width="160" height="160" rx="46" fill="none" stroke="{ORANGE}" stroke-width="12"/>'
    + arrow(128, 92, 128, 60, BLUE, 8, 18) + arrow(164, 128, 196, 128, BLUE, 8, 18))

icons["extend"] = svg(
    path("M44,196 C84,196 112,176 128,140", G_LIGHT)
    + path("M128,140 C140,112 150,84 156,64", ORANGE, dash="18 14")
    + arrow(170, 120, 196, 56, BLUE, 8, 20) + dot(128, 140, BLUE, 13) + dot(44, 196))

icons["slide_point"] = svg(
    path("M44,180 C80,60 176,60 212,180", G_LIGHT)
    + dot(92, 98, G_DARK, 12) + arc_arrow(128, 190, 130, 247, 273, BLUE, 8, 18)
    + dot(152, 90, ORANGE, 14) + dot(44, 180) + dot(212, 180))

# Slice (Fix Hole until v0.22.0): a ring (an outer spline and its hole) joined
# by the seam the tool adds, in orange, between the two picked points.
icons["slice"] = svg(
    circle(128, 144, 84, G_LIGHT) + circle(128, 144, 26, G_LIGHT)
    + line([(128, 60), (128, 118)], ORANGE)
    + dot(128, 60, G_LIGHT, 11) + dot(128, 118, G_LIGHT, 11))

icons["merge_pair"] = svg(
    line([(44, 168), (76, 128)], G_LIGHT) + line([(212, 168), (180, 128)], G_LIGHT)
    + arrow(80, 120, 112, 90, BLUE, 8, 18) + arrow(176, 120, 144, 90, BLUE, 8, 18)
    + dot(76, 128, G_DARK, 11) + dot(180, 128, G_DARK, 11) + dot(128, 76, ORANGE, 16))

# Snap Pair: an end point snaps onto a point in the middle of another spline
# (which Merge Pair would refuse); the two stay two points: an orange ring
# around the light one.
icons["snap_pair"] = svg(
    line([(44, 176), (128, 176), (212, 176)], G_LIGHT) + dot(44, 176) + dot(212, 176)
    + path("M60,52 C100,52 132,76 140,104", G_LIGHT) + dot(60, 52)
    + dot(140, 104, G_DARK, 11) + arrow(138, 118, 130, 146, BLUE, 8, 18)
    + circle(128, 176, 24, ORANGE, 8) + dot(128, 176, G_LIGHT, 11, 0))

# Swap Pair: two points trade places, one blue arrow each way.
icons["swap_pair"] = svg(
    line([(44, 196), (76, 160)], G_LIGHT) + line([(212, 196), (180, 160)], G_LIGHT)
    + arc_arrow(128, 168, 60, 210, 330, BLUE, 8, 18)
    + arc_arrow(128, 152, 60, 30, 150, BLUE, 8, 18)
    + dot(76, 160, ORANGE, 15) + dot(180, 160, G_LIGHT, 15))

icons["merge_by_distance"] = svg(
    path("M44,196 C64,140 92,128 120,128", G_LIGHT) + path("M212,196 C192,140 164,128 136,128", G_LIGHT)
    + circle(128, 128, 40, BLUE, 6, dash="8 10") + dot(128, 128, ORANGE, 15))

# =============================================================================
# New in v0.22.0: construction points, tangents from a point, handles to axis,
# Symmetrize
# =============================================================================

def _cross(a, b, c, d):
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    t = ((c[0] - a[0]) * sy - (c[1] - a[1]) * sx) / (rx * sy - ry * sx)
    return (a[0] + rx * t, a[1] + ry * t)


_long = ((60, 48), (204, 212))
_shorts = (((44, 136), (180, 76)), ((116, 216), (212, 124)))
icons["points_at_intersections"] = svg(
    "".join(line([a, b], G_LIGHT) for a, b in (_long, *_shorts))
    + "".join(dot(*_cross(*_long, a, b), ORANGE, 15) for a, b in _shorts))


def _bezier_pts(p0, p1, p2, p3, n=200):
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                    u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return out


def _even(points, count):
    acc = [0.0]
    for a, b in zip(points, points[1:]):
        acc.append(acc[-1] + math.dist(a, b))
    out = []
    for i in range(1, count + 1):
        target = acc[-1] * i / (count + 1)
        k = next(k for k in range(1, len(acc)) if acc[k] >= target)
        t = (target - acc[k - 1]) / max(acc[k] - acc[k - 1], 1e-9)
        a, b = points[k - 1], points[k]
        out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return out


_along = ((48, 64), (148, 40), (116, 208), (208, 200))
icons["points_along_curve"] = svg(
    path("M48,64 C148,40 116,208 208,200", G_LIGHT)
    + "".join(dot(x, y, ORANGE, 13) for x, y in _even(_bezier_pts(*_along), 3))
    + dot(48, 64) + dot(208, 200))

icons["handles_to_axis"] = svg(
    path("M56,80 C128,84 168,132 168,212", G_LIGHT)
    + line([(56, 80), (204, 116)], G_DARK, 6, dash="10 12") + dot(204, 116, G_DARK, 10)
    + line([(56, 80), (204, 80)], ORANGE) + dot(204, 80, ORANGE, 12)
    + dot(56, 80, G_LIGHT, 14))

_tc, _tr, _tp = (100, 100), 56, (204, 200)
_td = math.dist(_tc, _tp)
_tb = math.atan2(_tp[1] - _tc[1], _tp[0] - _tc[0])
_ts = math.acos(_tr / _td)
_touch = [(_tc[0] + _tr * math.cos(_tb + k * _ts), _tc[1] + _tr * math.sin(_tb + k * _ts))
          for k in (1, -1)]
icons["tangents_from_point"] = svg(
    circle(*_tc, _tr, G_LIGHT)
    + "".join(line([_tp, t], ORANGE) for t in _touch)
    + "".join(dot(*t, ORANGE, 11) for t in _touch)
    + dot(*_tp, BLUE, 15))

_heart_left = "M128,92 C112,52 48,52 48,104 C48,148 104,172 128,212"
_heart_right = "M128,92 C144,52 208,52 208,104 C208,148 152,172 128,212"
icons["symmetrize"] = svg(
    line([(128, 40), (128, 224)], G_DARK, 6, dash="4 12")
    + path(_heart_left, G_LIGHT) + path(_heart_right, ORANGE)
    + dot(128, 92, BLUE, 12) + dot(128, 212, BLUE, 12))


# =============================================================================
# Utilities
# =============================================================================

C6 = regular(128, 128, 76, 6)
icons["set_first_point"] = svg(
    circle(128, 128, 76, G_LIGHT) + "".join(dot(x, y, G_MID, 9) for x, y in C6[1:])
    + arc_arrow(128, 128, 104, -80, -30, BLUE, 8, 18) + dot(*C6[0], ORANGE, 16))

icons["invert_direction"] = svg(
    line([(52, 96), (180, 96)], G_LIGHT) + arrow(150, 96, 206, 96, G_LIGHT, 12, 28)
    + line([(204, 164), (76, 164)], ORANGE) + arrow(106, 164, 50, 164, ORANGE, 12, 28)
    + dot(52, 96) + dot(204, 164, ORANGE, 11))

_wave = "M44,170 C84,60 172,60 212,170"
icons["subdivide"] = svg(
    path(_wave, G_LIGHT) + dot(44, 170) + dot(212, 170) + dot(128, 87.5)
    + dot(78, 112, ORANGE, 12) + dot(178, 112, ORANGE, 12))

icons["simplify"] = svg(
    path(_wave, G_LIGHT)
    + "".join(dot(x, y, G_DARK, 7, 4) for x, y in [(60, 136), (96, 98), (160, 98), (196, 136)])
    + dot(44, 170, ORANGE, 13) + dot(128, 87.5, ORANGE, 13) + dot(212, 170, ORANGE, 13))

icons["dissolve"] = svg(
    line([(44, 180), (128, 72), (212, 180)], G_DARK, 6, dash="10 12")
    + line([(44, 180), (212, 180)], ORANGE)
    + dot(44, 180) + dot(212, 180) + minus_badge(128, 72))

icons["split_at_points"] = svg(
    line([(44, 180), (80, 104)], ORANGE) + line([(100, 96), (156, 96)], G_LIGHT)
    + line([(176, 104), (212, 180)], ORANGE)
    + dot(44, 180) + dot(90, 96, BLUE, 12) + dot(166, 96, BLUE, 12) + dot(212, 180))

icons["join_merge"] = svg(
    path("M44,180 C60,110 92,100 120,112", G_LIGHT)
    + path("M212,180 C196,110 164,100 136,112", ORANGE_D)
    + arrow(184, 72, 146, 96, BLUE, 8, 18) + arrow(72, 72, 110, 96, BLUE, 8, 18)
    + dot(128, 112, ORANGE, 15))

icons["separate"] = svg(
    f'<rect x="40" y="40" width="96" height="96" rx="12" fill="none" stroke="{G_DARK}" '
    f'stroke-width="6" stroke-dasharray="10 12"/>'
    + circle(88, 88, 28, G_LIGHT)
    + circle(176, 176, 32, ORANGE) + arrow(118, 118, 148, 148, BLUE, 8, 18))

icons["remove_doubles"] = svg(
    line([(44, 168), (212, 168)], G_LIGHT) + dot(44, 168) + dot(212, 168)
    + dot(118, 168, G_DARK, 14) + dot(138, 168, ORANGE, 14) + minus_badge(128, 92))

_strays = [(176, 64), (204, 112), (160, 124)]
icons["select_strays"] = svg(
    path("M44,200 C64,120 108,100 128,150", G_LIGHT) + dot(44, 200, G_MID, 10) + dot(128, 150, G_MID, 10)
    + "".join(dot(x, y, ORANGE, 14) for x, y in _strays))

icons["remove_strays"] = svg(
    path("M44,200 C64,120 108,100 128,150", G_LIGHT) + dot(44, 200, G_MID, 10) + dot(128, 150, G_MID, 10)
    + dot(176, 64, G_DARK, 12) + dot(204, 112, G_DARK, 12) + minus_badge(176, 168))

# Select by Type: the splines of that type in orange (selected), another one
# in dark grey. Poly: a zigzag with corner points; Bezier: an arch with its
# handles; NURBS: an arch inside its dashed control polygon.
_poly = [(48, 204), (100, 148), (152, 204), (208, 148)]


def _select_type(selected):
    def poly(color):
        return line(_poly, color, 10) + "".join(dot(x, y, color, 10, 4) for x, y in _poly)

    def bezier(color):
        return (line([(48, 116), (84, 44)], color, 6) + line([(208, 116), (172, 44)], color, 6)
                + dot(84, 44, color, 8, 4) + dot(172, 44, color, 8, 4)
                + path("M48,116 C84,44 172,44 208,116", color, 10)
                + dot(48, 116, color, 11, 4) + dot(208, 116, color, 11, 4))

    def nurbs(color):
        cage = [(48, 116), (92, 44), (164, 44), (208, 116)]
        return (line(cage, G_MID, 6, dash="8 10")
                + path("M48,116 C92,44 164,44 208,116", color, 10)
                + "".join(dot(x, y, color, 10, 4) for x, y in cage))

    if selected == "poly":
        return svg(bezier(G_DARK) + poly(ORANGE))
    if selected == "bezier":
        return svg(bezier(ORANGE) + poly(G_DARK))
    return svg(nurbs(ORANGE) + poly(G_DARK))


icons["select_polys"] = _select_type("poly")
icons["select_beziers"] = _select_type("bezier")
icons["select_nurbs"] = _select_type("nurbs")

_res = [on_circle(128, 196, 140, a) for a in (-48, -32, -16, 0, 16, 32, 48)]
icons["set_resolution"] = svg(
    path("M44,180 C80,60 176,60 212,180", G_DARK, 6, dash="10 12")
    + line(_res, ORANGE, 10) + "".join(dot(x, y, ORANGE_D, 7, 4) for x, y in _res[1:-1])
    + dot(*_res[0]) + dot(*_res[-1]))

icons["cyclic"] = svg(
    path(f"M{on_circle(128, 128, 76, 35)[0]:.1f},{on_circle(128, 128, 76, 35)[1]:.1f} "
         f"A76,76 0 1 1 {on_circle(128, 128, 76, -35)[0]:.1f},{on_circle(128, 128, 76, -35)[1]:.1f}", G_LIGHT)
    + path(f"M{on_circle(128, 128, 76, -35)[0]:.1f},{on_circle(128, 128, 76, -35)[1]:.1f} "
           f"A76,76 0 0 1 {on_circle(128, 128, 76, 35)[0]:.1f},{on_circle(128, 128, 76, 35)[1]:.1f}", ORANGE)
    + dot(*on_circle(128, 128, 76, -35)) + dot(*on_circle(128, 128, 76, 35)))

# =============================================================================
# Change Origin
# =============================================================================

icons["origin_to_selected"] = svg(
    path("M44,190 C80,70 176,70 212,190", G_LIGHT) + dot(44, 190) + dot(212, 190)
    + f'<circle cx="128" cy="196" r="12" fill="none" stroke="{G_DARK}" stroke-width="6"/>'
    + arrow(128, 176, 128, 120, BLUE, 8, 18) + origin_mark(128, 100))

icons["change_origin"] = svg(
    path("M44,190 C80,70 176,70 212,190", G_LIGHT) + dot(212, 190)
    + f'<circle cx="128" cy="196" r="12" fill="none" stroke="{G_DARK}" stroke-width="6"/>'
    + arrow(116, 192, 70, 192, BLUE, 8, 18) + origin_mark(44, 190))

# =============================================================================
# Group icons (repository README)
# =============================================================================

icons["create_curves"] = svg(
    f'<rect x="48" y="48" width="96" height="96" fill="none" stroke="{G_LIGHT}" stroke-width="12" '
    f'stroke-linejoin="round"/>'
    + circle(160, 160, 52, ORANGE) + dot(48, 48) + dot(144, 144, G_LIGHT, 10)
    + dot(160, 108, G_LIGHT, 10) + dot(212, 160, G_LIGHT, 10))

icons["utilities"] = svg(
    path("M56,218 C96,218 104,142 140,142 C176,142 184,82 224,82", ORANGE)
    + dot(56, 218) + dot(224, 82) + wrench(101, 94, 1.15))

# ---- Output -------------------------------------------------------------------
# Folder layout (relative to this script, in etr_curves_toolkit_docs/icons/src/):
#   etr_curves_toolkit_docs/icons/src/<name>.svg   vector sources (256 x 256)
#   etr_curves_toolkit_docs/icons/<name>.png       large icons, 256 px (full documentation README)
#   icons/<name>.png                               small icons, 64 px (repository README)
HERE = os.path.dirname(os.path.abspath(__file__))
LARGE_DIR = os.path.normpath(os.path.join(HERE, ".."))
SMALL_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "..", "icons"))
LARGE_PX, SMALL_PX = 256, 64

if __name__ == "__main__":
    import cairosvg  # pip install cairosvg
    os.makedirs(SMALL_DIR, exist_ok=True)
    for name, data in icons.items():
        svg_path = os.path.join(HERE, f"{name}.svg")
        with open(svg_path, "w") as f:
            f.write(data)
        # Both sizes are rendered from the vector source, so the small ones stay crisp.
        cairosvg.svg2png(url=svg_path, write_to=os.path.join(LARGE_DIR, f"{name}.png"),
                         output_width=LARGE_PX, output_height=LARGE_PX)
        cairosvg.svg2png(url=svg_path, write_to=os.path.join(SMALL_DIR, f"{name}.png"),
                         output_width=SMALL_PX, output_height=SMALL_PX)
    print(f"{len(icons)} icons written")
