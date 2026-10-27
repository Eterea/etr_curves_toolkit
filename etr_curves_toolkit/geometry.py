# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Pure-Python geometry helpers (no `bpy` / `mathutils` dependency).

Vectors are plain 3-tuples of floats, so this module can be unit-tested
outside Blender. Everything here is small and stateless.
"""

import math

EPS = 1e-9


# -----------------------------------------------------------------------------
# Vector helpers
# -----------------------------------------------------------------------------

def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def mul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def length(a):
    return math.sqrt(dot(a, a))


def distance(a, b):
    return length(sub(a, b))


def lerp(a, b, t):
    return (
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    )


def normalized(a, eps=EPS):
    """Return the unit vector of `a`, or None if `a` is (almost) zero."""
    n = length(a)
    if n < eps:
        return None
    return (a[0] / n, a[1] / n, a[2] / n)


# -----------------------------------------------------------------------------
# Tangents
# -----------------------------------------------------------------------------

def tangent_at_end(point, handle, neighbour, neighbour_handle=None):
    """Unit tangent that leaves a Bezier point *away* from its curve body.

    point:            the control point (the curve end or a corner).
    handle:           the handle of `point` that faces the segment we look at
                      (for the "in" tangent of a corner, its left handle).
    neighbour:        the control point at the other end of that segment.
    neighbour_handle: the neighbour's handle that faces this segment.

    Returns the direction pointing from `point` into the segment (so for a
    corner, the "in" tangent points back along the previous segment).
    Fallback chain: handle -> neighbour's handle -> neighbour.
    Returns None when everything is coincident.
    """
    d = normalized(sub(handle, point))
    if d is not None:
        return d
    if neighbour_handle is not None:
        d = normalized(sub(neighbour_handle, point))
        if d is not None:
            return d
    return normalized(sub(neighbour, point))


def is_straight_segment(p0, h0, h1, p1, tol=1e-5):
    """True if the cubic p0, h0, h1, p1 is a straight line.

    Both handles must lie on the line p0-p1 (within `tol`, relative to the
    segment length). Coincident p0 and p1 count as not straight.
    """
    chord = sub(p1, p0)
    chord_len = length(chord)
    if chord_len < EPS:
        return False
    for h in (h0, h1):
        off = cross(sub(h, p0), chord)
        if length(off) / chord_len > tol * max(chord_len, 1.0):
            return False
    return True


# -----------------------------------------------------------------------------
# Circular arcs as cubic Beziers
# -----------------------------------------------------------------------------

def arc_beziers(center, e1, e2, radius, sweep, max_step=math.pi / 2):
    """Approximate a circular arc with cubic Bezier segments.

    The arc starts at center + radius * e1 and turns towards e2 (e1 and e2
    must be orthonormal, spanning the arc's plane). `sweep` is the total angle
    in radians. Each cubic covers at most `max_step` (90 degrees by default),
    which keeps the radial error below 3e-4 of the radius.

    Returns a list of (point, handle_left, handle_right) tuples, one per
    anchor, from the arc start to the arc end. The outer handles of the first
    (left) and last (right) anchors are set equal to the anchor itself.
    """
    count = max(1, int(math.ceil(sweep / max_step - 1e-9)))
    step = sweep / count
    k = (4.0 / 3.0) * math.tan(step / 4.0) * radius

    def at(angle):
        c, s = math.cos(angle), math.sin(angle)
        pos = add(center, add(mul(e1, radius * c), mul(e2, radius * s)))
        tan = add(mul(e1, -s), mul(e2, c))  # unit tangent, direction of travel
        return pos, tan

    anchors = []
    for i in range(count + 1):
        pos, tan = at(step * i)
        hl = sub(pos, mul(tan, k)) if i > 0 else pos
        hr = add(pos, mul(tan, k)) if i < count else pos
        anchors.append((pos, hl, hr))
    return anchors


class Fillet:
    """A circular fillet between two curves, ready to be turned into Beziers.

    t1, t2:      tangent points (start and end of the arc).
    tau1, tau2:  unit tangents at t1 and t2, in the direction of travel
                 (from the previous point towards the next one).
    center:      center of the circle.
    e1, e2:      orthonormal basis of the arc: e1 = (t1 - center) / radius,
                 e2 = tau1. The arc turns from e1 towards e2.
    sweep:       angle of the arc, in radians.
    radius:      radius actually used (may be smaller than the requested one).
    u, v:        parameters of t1 on the incoming segment and of t2 on the
                 outgoing segment (None for straight corners, where they are
                 not needed).
    """

    __slots__ = ("t1", "t2", "tau1", "tau2", "center", "e1", "e2",
                 "sweep", "radius", "u", "v")

    def __init__(self, **kwargs):
        for name in self.__slots__:
            setattr(self, name, kwargs.get(name))


def fillet_straight_corner(prev_pt, corner, next_pt, radius,
                           max_tangent_prev=None, max_tangent_next=None,
                           min_angle=1e-4):
    """Fillet of the corner between two straight segments (exact, analytic).

    prev_pt, corner, next_pt: the three consecutive points (3-tuples).
    radius:                   requested arc radius.
    max_tangent_prev/next:    maximum distance from the corner along each
                              segment at which the arc may start (None = the
                              full segment length).

    Returns a Fillet, or None if the corner is (almost) straight or
    degenerate. The radius is reduced when it does not fit.
    """
    d1 = normalized(sub(prev_pt, corner))
    d2 = normalized(sub(next_pt, corner))
    if d1 is None or d2 is None:
        return None

    cos_theta = max(-1.0, min(1.0, dot(d1, d2)))
    theta = math.acos(cos_theta)            # interior angle at the corner
    if math.pi - theta < min_angle or theta < min_angle:
        return None                          # collinear / folded back

    half = theta / 2.0
    t_wanted = radius / math.tan(half)
    len1 = distance(prev_pt, corner)
    len2 = distance(next_pt, corner)
    t_cap1 = len1 if max_tangent_prev is None else min(len1, max_tangent_prev)
    t_cap2 = len2 if max_tangent_next is None else min(len2, max_tangent_next)
    t = min(t_wanted, t_cap1, t_cap2)
    r_eff = t * math.tan(half)
    if r_eff < EPS:
        return None

    t1 = add(corner, mul(d1, t))
    t2 = add(corner, mul(d2, t))
    bisector = normalized(add(d1, d2))
    center = add(corner, mul(bisector, r_eff / math.sin(half)))
    tau1 = mul(d1, -1.0)
    return Fillet(
        t1=t1, t2=t2, tau1=tau1, tau2=d2, center=center,
        e1=normalized(sub(t1, center)), e2=tau1,
        sweep=math.pi - theta, radius=r_eff,
    )


# --- Fillet between curved segments -------------------------------------------

def _segment_tangent(seg, u, h=1e-5):
    """Unit direction of travel of a cubic at parameter u (finite difference,
    so it also works where a handle has zero length)."""
    a, b = max(0.0, u - h), min(1.0, u + h)
    return normalized(sub(bezier_point(*seg, b), bezier_point(*seg, a)))


def fillet_curved_corner(seg_in, seg_out, radius, u_min=0.0, v_max=1.0,
                         samples=48, min_angle=1e-4):
    """Fillet of a corner where at least one of the segments is curved.

    seg_in:  (p0, h0, h1, p1) incoming cubic, ending at the corner.
    seg_out: (p0, h0, h1, p1) outgoing cubic, starting at the corner.
    radius:  requested radius.
    u_min:   the tangent point on seg_in must have a parameter >= u_min.
    v_max:   the tangent point on seg_out must have a parameter <= v_max.
             (0.5 when the neighbouring corner is also being rounded.)

    The center of the fillet is where the two curves, offset by the radius
    towards the inside of the corner, cross each other. That crossing is first
    found on sampled offset curves and then refined with Newton's method, so
    the circle is tangent to both curves. If the radius does not fit, the
    largest one that fits is found by bisection.

    The corner is solved in the plane of its two tangents (for 3D curves that
    are not planar around the corner, the result is the best fit in that plane).

    Returns a Fillet, or None.
    """
    corner = seg_in[3]
    d_in = _segment_tangent(seg_in, 1.0)
    d_out = _segment_tangent(seg_out, 0.0)
    if d_in is None or d_out is None:
        return None
    d_in = mul(d_in, -1.0)                   # from the corner back along seg_in
    angle = math.acos(max(-1.0, min(1.0, dot(d_in, d_out))))
    if math.pi - angle < min_angle or angle < min_angle:
        return None

    # 2D frame of the corner: x along the bisector (inside), y across it.
    ex = normalized(add(d_in, d_out))
    nz = normalized(cross(d_out, d_in))
    if ex is None or nz is None:
        return None
    ey = cross(nz, ex)

    def to2(p):
        q = sub(p, corner)
        return (dot(q, ex), dot(q, ey))

    def to3(x, y):
        return add(corner, add(mul(ex, x), mul(ey, y)))

    def curve2(seg, t):
        return to2(bezier_point(*seg, t))

    def tangent2(seg, t):
        d = _segment_tangent(seg, t)
        if d is None:
            return None
        x, y = dot(d, ex), dot(d, ey)
        n = math.hypot(x, y)
        return None if n < EPS else (x / n, y / n)

    # Side of each curve that faces the inside of the corner (constant along
    # the curve): the normal must point towards the bisector at the corner.
    t_in, t_out = tangent2(seg_in, 1.0), tangent2(seg_out, 0.0)
    if t_in is None or t_out is None:
        return None
    s1 = 1.0 if -t_in[1] > 0 else -1.0       # perp(t) = (-ty, tx), dot with (1, 0)
    s2 = 1.0 if -t_out[1] > 0 else -1.0

    def offset(seg, t, side, r):
        p = curve2(seg, t)
        tg = tangent2(seg, t)
        if tg is None:
            return None
        return (p[0] - side * r * tg[1], p[1] + side * r * tg[0])

    scale = max(
        distance(seg_in[0], seg_in[3]), distance(seg_out[0], seg_out[3]), radius, EPS)

    def solve(r):
        """(u, v) of the fillet of radius r, or None."""
        us = [u_min + (1.0 - u_min) * i / samples for i in range(samples + 1)]
        vs = [v_max * j / samples for j in range(samples + 1)]
        o1 = [offset(seg_in, u, s1, r) for u in us]
        o2 = [offset(seg_out, v, s2, r) for v in vs]
        best = None
        for i in range(samples):
            a0, a1 = o1[i], o1[i + 1]
            if a0 is None or a1 is None:
                continue
            for j in range(samples):
                b0, b1 = o2[j], o2[j + 1]
                if b0 is None or b1 is None:
                    continue
                hit = _segments_cross_2d(a0, a1, b0, b1)
                if hit is None:
                    continue
                u = us[i] + (us[i + 1] - us[i]) * hit[0]
                v = vs[j] + (vs[j + 1] - vs[j]) * hit[1]
                key = (1.0 - u) + v          # closest to the corner wins
                if best is None or key < best[0]:
                    best = (key, u, v)
        if best is None:
            return None
        u, v = best[1], best[2]
        # Newton refinement of offset1(u) == offset2(v).
        h = 1e-7
        for _ in range(12):
            p = offset(seg_in, u, s1, r)
            q = offset(seg_out, v, s2, r)
            if p is None or q is None:
                return None
            gx, gy = p[0] - q[0], p[1] - q[1]
            if math.hypot(gx, gy) < 1e-12 * scale:
                break
            du = h if u + h <= 1.0 else -h
            dv = h if v + h <= 1.0 else -h
            pu = offset(seg_in, u + du, s1, r)
            qv = offset(seg_out, v + dv, s2, r)
            if pu is None or qv is None:
                break
            j11, j21 = (pu[0] - p[0]) / du, (pu[1] - p[1]) / du
            j12, j22 = -(qv[0] - q[0]) / dv, -(qv[1] - q[1]) / dv
            det = j11 * j22 - j12 * j21
            if abs(det) < 1e-18:
                break
            u -= (gx * j22 - gy * j12) / det
            v -= (j11 * gy - j21 * gx) / det
            u = min(1.0, max(u_min, u))
            v = min(v_max, max(0.0, v))
        p = offset(seg_in, u, s1, r)
        q = offset(seg_out, v, s2, r)
        if p is None or q is None or math.hypot(p[0] - q[0], p[1] - q[1]) > 1e-6 * scale:
            return None
        # The circle must not cut into either curve (it happens when the
        # radius is larger than the curvature radius of a convex curve: the
        # offset curves then fold over themselves and still cross).
        for seg in (seg_in, seg_out):
            for k in range(samples * 2 + 1):
                c = curve2(seg, k / (samples * 2))
                if math.hypot(c[0] - p[0], c[1] - p[1]) < r * (1.0 - 1e-3):
                    return None
        return u, v

    sol = solve(radius)
    r_eff = radius
    if sol is None:
        lo, hi = 0.0, radius
        for _ in range(16):
            mid = 0.5 * (lo + hi)
            found = solve(mid)
            if found is not None:
                lo, sol = mid, found
            else:
                hi = mid
        r_eff = lo
        if sol is None or r_eff < radius * 1e-3:
            return None
    u, v = sol

    c2d = offset(seg_in, u, s1, r_eff)
    center = to3(*c2d)
    t1 = bezier_point(*seg_in, u)
    t2 = bezier_point(*seg_out, v)
    tg1, tg2 = tangent2(seg_in, u), tangent2(seg_out, v)
    tau1 = normalized(add(mul(ex, tg1[0]), mul(ey, tg1[1])))
    tau2 = normalized(add(mul(ex, tg2[0]), mul(ey, tg2[1])))
    p1 = curve2(seg_in, u)
    p2 = curve2(seg_out, v)
    e1 = normalized(sub(to3(*p1), center))
    e2 = tau1
    rel = sub(to3(*p2), center)
    sweep = math.atan2(dot(rel, e2), dot(rel, e1))
    if sweep <= 0.0:
        sweep += 2.0 * math.pi
    return Fillet(
        t1=t1, t2=t2, tau1=tau1, tau2=tau2, center=center, e1=e1, e2=e2,
        sweep=sweep, radius=r_eff, u=u, v=v,
    )


def _segments_cross_2d(a0, a1, b0, b1):
    """Parameters (s, t) in [0, 1] where segment a0-a1 crosses b0-b1, or None."""
    rx, ry = a1[0] - a0[0], a1[1] - a0[1]
    sx, sy = b1[0] - b0[0], b1[1] - b0[1]
    den = rx * sy - ry * sx
    if abs(den) < 1e-30:
        return None
    qx, qy = b0[0] - a0[0], b0[1] - a0[1]
    s = (qx * sy - qy * sx) / den
    t = (qx * ry - qy * rx) / den
    if -1e-9 <= s <= 1 + 1e-9 and -1e-9 <= t <= 1 + 1e-9:
        return s, t
    return None


# --- From a fillet to Bezier anchors -------------------------------------------

def fillet_anchors(fillet, tension=1.0):
    """Bezier anchors (point, handle_left, handle_right) of a fillet.

    tension 1.0: a circular arc (one cubic per 90 degrees, so it is a true
                 circle within 3e-4 of the radius).
    tension 0.0: a straight bevel between the two tangent points.
    other:       a single cubic whose handles, tangent to both curves, are
                 `tension` times the length that a circle would need. Above
                 1.0 the curve gets sharper.

    The outer handles of the first and last anchors are left at the anchors
    themselves; the caller sets them from the neighbouring segments.
    """
    f = fillet
    if abs(tension - 1.0) < 1e-9 or f.sweep > math.pi * 0.9:
        anchors = arc_beziers(f.center, f.e1, f.e2, f.radius, f.sweep)
        if abs(tension - 1.0) >= 1e-9:
            # Very wide arcs (more than ~160 degrees) keep their anchors and
            # scale every handle by the tension.
            anchors = [
                (p, add(p, mul(sub(hl, p), tension)), add(p, mul(sub(hr, p), tension)))
                for p, hl, hr in anchors
            ]
        # Snap the ends onto the exact tangent points (only relevant for 3D
        # curves that are not planar around the corner).
        anchors[0] = _moved(anchors[0], sub(f.t1, anchors[0][0]))
        anchors[-1] = _moved(anchors[-1], sub(f.t2, anchors[-1][0]))
        return anchors
    h = tension * (4.0 / 3.0) * math.tan(f.sweep / 4.0) * f.radius
    return [
        (f.t1, f.t1, add(f.t1, mul(f.tau1, h))),
        (f.t2, sub(f.t2, mul(f.tau2, h)), f.t2),
    ]


def _moved(anchor, delta):
    return tuple(add(p, delta) for p in anchor)


# -----------------------------------------------------------------------------
# Cubic Bezier evaluation
# -----------------------------------------------------------------------------

def bezier_point(p0, h0, h1, p1, t):
    u = 1.0 - t
    a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (
        a * p0[0] + b * h0[0] + c * h1[0] + d * p1[0],
        a * p0[1] + b * h0[1] + c * h1[1] + d * p1[1],
        a * p0[2] + b * h0[2] + c * h1[2] + d * p1[2],
    )


def bezier_split(p0, h0, h1, p1, t):
    """Split a cubic at t (de Casteljau). Returns the control points of the
    left part and of the right part; together they trace the same curve."""
    a, b, c = lerp(p0, h0, t), lerp(h0, h1, t), lerp(h1, p1, t)
    d, e = lerp(a, b, t), lerp(b, c, t)
    m = lerp(d, e, t)
    return (p0, a, d, m), (m, e, c, p1)


def bezier_sub(p0, h0, h1, p1, s, e):
    """Control points of the part of a cubic between parameters s and e."""
    if e < 1.0:
        p0, h0, h1, p1 = bezier_split(p0, h0, h1, p1, e)[0]
        s = s / e if e > EPS else 0.0
    if s > 0.0:
        p0, h0, h1, p1 = bezier_split(p0, h0, h1, p1, s)[1]
    return p0, h0, h1, p1


def sample_polyline(points):
    """Total length of a polyline and the cumulative length at each vertex."""
    cumulative = [0.0]
    for i in range(1, len(points)):
        cumulative.append(cumulative[-1] + distance(points[i - 1], points[i]))
    return cumulative[-1], cumulative


def point_at_factor(points, factor):
    """Point of a polyline at `factor` (0..1) of its total length."""
    total, cumulative = sample_polyline(points)
    if total < EPS:
        return points[0]
    target = max(0.0, min(1.0, factor)) * total
    for i in range(1, len(points)):
        if cumulative[i] >= target:
            seg = cumulative[i] - cumulative[i - 1]
            t = 0.0 if seg < EPS else (target - cumulative[i - 1]) / seg
            return lerp(points[i - 1], points[i], t)
    return points[-1]
