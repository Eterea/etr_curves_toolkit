# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Splines as world-space cubics, and the axis views

A library (no operators) shared by Points at Intersections, Points Along
Curve and Symmetrize.

  - world_cubics()   the segments of a spline snapshot as cubic Bezier
                     segments in world space: exact for Bezier and Poly
                     splines (a Poly segment is a straight cubic). A NURBS
                     spline is evaluated by Blender into a dense polyline
                     (64 points per control point), so it is a very close
                     approximation, not the exact curve.
  - axis_view()      which orthographic axis view (Top, Front, Right...) the
                     3D Viewport shows, if any, with the axes of the screen
                     (right, up) and the normal towards the viewer.
"""

import math

from mathutils import Vector

from . import geometry as geo
from .circles import VIEWS, _region_3d, snapped_up
from .context_utils import world_matrix

#: How close (as a cosine) the view has to be to an axis to count as that view.
_ALIGNED = 1.0 - 1e-5

#: Steps of the arc-length table of a curved segment.
LENGTH_STEPS = 64


class Cubic:
    """A cubic Bezier segment in 3D (world space). `line` marks a straight
    one (a Poly segment, or a Bezier one with its handles on the chord)."""

    __slots__ = ("p0", "h0", "h1", "p1", "line")

    def __init__(self, p0, h0, h1, p1, line=False):
        self.p0, self.h0, self.h1, self.p1 = p0, h0, h1, p1
        self.line = line

    @classmethod
    def straight(cls, a, b):
        return cls(a, geo.lerp(a, b, 1.0 / 3.0), geo.lerp(a, b, 2.0 / 3.0), b, True)

    def pt(self, t):
        if self.line:
            return geo.lerp(self.p0, self.p1, t)
        return geo.bezier_point(self.p0, self.h0, self.h1, self.p1, t)


def world_cubics(context, obj, data):
    """Cubic segments (world space) of a spline snapshot of `obj`.

    The closing segment of a closed spline is included. A spline with a
    single point has none.
    """
    mw = world_matrix(obj)

    def w(co):
        return tuple(mw @ Vector(co))

    pts = data.points
    n = len(pts)
    if n < 2:
        return []
    if data.kind == 'NURBS':
        from .utilities import _nurbs_polyline
        poly = [w(c) for c in _nurbs_polyline(context, obj, data)]
        return [Cubic.straight(a, b) for a, b in zip(poly, poly[1:])
                if geo.distance(a, b) > 1e-12]
    out = []
    for i in range(n if data.cyclic else n - 1):
        a, b = pts[i], pts[(i + 1) % n]
        if data.kind == 'BEZIER':
            p0, h0, h1, p1 = w(a.co), w(a.hr), w(b.hl), w(b.co)
            line = geo.is_straight_segment(a.co, a.hr, b.hl, b.co)
            out.append(Cubic.straight(p0, p1) if line else Cubic(p0, h0, h1, p1))
        else:
            out.append(Cubic.straight(w(a.co), w(b.co)))
    return out


# -----------------------------------------------------------------------------
# Arc length
# -----------------------------------------------------------------------------

def length_table(cubics, steps=LENGTH_STEPS):
    """[(segment index, parameter, length from the start)] along the cubics,
    from the start (0) to the end of the last one."""
    table = [(0, 0.0, 0.0)]
    total = 0.0
    for k, c in enumerate(cubics):
        n = 1 if c.line else steps
        prev = c.p0
        for i in range(1, n + 1):
            t = i / n
            p = c.pt(t)
            total += geo.distance(prev, p)
            table.append((k, t, total))
            prev = p
    return table


def point_at_length(cubics, table, s):
    """World point at arc length `s` from the start (on the curve itself:
    the parameter is interpolated in the table, then the cubic evaluated)."""
    total = table[-1][2]
    s = min(max(s, 0.0), total)
    lo, hi = 0, len(table) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if table[mid][2] < s:
            lo = mid
        else:
            hi = mid
    k1, t1, s1 = table[hi]
    k0, t0, s0 = table[lo]
    if k0 != k1:            # the step starts at the beginning of segment k1
        t0 = 0.0
    f = 0.0 if s1 - s0 <= 1e-300 else (s - s0) / (s1 - s0)
    return cubics[k1].pt(t0 + (t1 - t0) * f)


# -----------------------------------------------------------------------------
# The view
# -----------------------------------------------------------------------------

def axis_view(context):
    """(name, normal, up) of the 3D Viewport.

    name is one of VIEWS ('TOP', 'FRONT', ...) only when the view is
    orthographic and looks along an axis; it is None in a perspective view,
    in the camera view, in a rotated orthographic view and without a 3D
    Viewport. normal points towards the viewer and up is up on the screen,
    both snapped to the axes for an axis view.
    """
    rv3d = _region_3d(context)
    if rv3d is None:
        return None, (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)
    rotation = rv3d.view_rotation
    normal = tuple(rotation @ Vector((0.0, 0.0, 1.0)))
    up = tuple(rotation @ Vector((0.0, 1.0, 0.0)))
    if rv3d.view_perspective != 'ORTHO':
        return None, normal, up
    for name, (axis, _) in VIEWS.items():
        if geo.dot(normal, axis) > _ALIGNED:
            return name, axis, snapped_up(name, normal, up)
    return None, normal, up


def screen_axes(normal, up):
    """(right, up) of a view, both unit and perpendicular to `normal`."""
    up = geo.normalized(geo.sub(up, geo.mul(normal, geo.dot(up, normal))))
    return geo.cross(up, normal), up


def best_plane(points):
    """Unit normal of the plane that best fits the points (the direction in
    which they spread the least), or None when they are too few."""
    n = len(points)
    if n < 3:
        return None
    c = tuple(sum(p[i] for p in points) / n for i in range(3))
    m = [[0.0] * 3 for _ in range(3)]
    for p in points:
        d = geo.sub(p, c)
        for i in range(3):
            for j in range(3):
                m[i][j] += d[i] * d[j]
    try:
        import numpy as np
        values, vectors = np.linalg.eigh(np.array(m))
    except ImportError:
        return None
    if values[-1] <= 1e-24:
        return None
    v = vectors[:, 0]
    normal = geo.normalized((float(v[0]), float(v[1]), float(v[2])))
    if normal is None:
        return None
    # A stable sign: towards +Z, +Y or +X.
    for i in (2, 1, 0):
        if abs(normal[i]) > 1e-9:
            return normal if normal[i] > 0 else geo.mul(normal, -1.0)
    return normal


def any_up(normal):
    """An up direction perpendicular to `normal`: world Z, Y or X, made
    perpendicular."""
    for up in ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)):
        flat = geo.normalized(geo.sub(up, geo.mul(normal, geo.dot(up, normal))), 1e-3)
        if flat is not None:
            return flat
    return (0.0, 1.0, 0.0)


def angle_between(a, b):
    """Angle (radians) between two non-zero vectors."""
    la, lb = geo.length(a), geo.length(b)
    if la <= 1e-300 or lb <= 1e-300:
        return 0.0
    return math.acos(max(-1.0, min(1.0, geo.dot(a, b) / (la * lb))))
