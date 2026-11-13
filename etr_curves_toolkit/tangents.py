# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Tangents to 2 Circles

Two circles (closed splines whose shape is a circle) are picked:

  - Object Mode: two selected curve objects with one circle each, or one
    selected curve object with exactly two splines, both circles.
  - Edit Mode: the two splines that have selected points (any point of a
    spline picks it), in one curve or in two curves being edited.

Options (F9):

  - Main Tangents (on by default): the two outer tangents (the "belt" lines),
    the ones that do not cross.
  - Crossing Tangents (off by default): the two inner tangents, the ones that
    cross between the circles (only when the circles do not overlap).
  - Create External Loop(s) / Create Internal Loop(s) (off by default):
    instead of the lines, closed loops made of the tangents and the arcs of
    the circles between their ends: the arcs that face away from the other
    circle (external) or the ones that face it (internal). One loop for each
    kind of tangents that is on; with the crossing tangents the loop is a
    figure of eight (no point where the tangents cross).

The lines are straight Bezier segments with Vector handles. The arcs of the
loops are cut from the circles themselves (the same cubics, split where the
tangents touch them), so a loop lies exactly on its circles.

Where the new geometry goes (the circles are never removed nor hidden, only
deselected):
  - Object Mode: into a new third object ("Tangents"), with the look and
    transform of the active one, left selected and active.
  - Edit Mode: into the curve being edited (the active one, when the circles
    are in two curves), and it is left selected.

The circles may be anywhere and rotated, but they must lie in one common
plane, and neither may be fully inside the other.

Tangents from Point (Edit Mode)
    One point (a stray point, or a control point of any spline) and one or
    more points of a circle are selected. The button draws the two straight
    lines that start at that point and touch the circle, as two Poly
    segments of two points each, independent (not merged with the circle),
    in the curve being edited. With Create External Loop / Create Internal
    Loop (F9) they become closed Bezier loops instead: the two lines and the
    arc of the circle between the points where they touch it, the one that
    faces away from the point (external) or the one that faces it (internal).
    The point may be out of the plane of the circle: the lines still touch it
    (they are tangent in 3D). A point inside the circle, or on it, has no
    tangents.
"""

import math

import bpy
from bpy.props import BoolProperty
from mathutils import Vector

from . import geometry as geo
from . import spline_data as sd
from .context_utils import (
    EDIT_MODE,
    curves_in_edit_mode,
    edit_scope,
    link_like,
    new_curve_object,
    selected_curves,
    world_matrix,
)

#: How far (relative to the radius) the samples of a spline may stray from
#: the fitted circle. Blender's four-point Bezier circle strays 2.7e-4.
CIRCLE_TOLERANCE = 2e-3

#: How far (relative to the size) the two circles may be out of one plane.
PLANE_TOLERANCE = 1e-4


class Fail(Exception):
    """A message for the user; nothing has been changed."""


# -----------------------------------------------------------------------------
# Circles
# -----------------------------------------------------------------------------

class FittedCircle:
    """center, radius and unit normal of a circle, in world space.

    cubics: the spline itself, as world-space cubics (p0, h0, h1, p1), so
    that a point computed on the ideal circle can be put on the real curve
    (see snap): a Bezier circle strays from the ideal one by up to 2.7e-4 of
    its radius, and a tangent point left there is just inside or just outside
    the spline, which the Booleans cannot tell from a crossing.
    """

    def __init__(self, center, radius, normal, cubics=()):
        self.center = center
        self.radius = radius
        self.normal = normal
        self.cubics = list(cubics)

    def snap(self, p):
        """The point of the spline closest to p (p itself without cubics)."""
        if not self.cubics:
            return tuple(p)
        i, t = self.locate(p)
        return tuple(geo.bezier_point(*self.cubics[i], t))

    def locate(self, p):
        """Where the point of the spline closest to p is, as a position
        along the spline: (index of the cubic, parameter in it)."""
        best = None
        for i, cubic in enumerate(self.cubics):
            t, d = _closest_on_cubic(cubic, p)
            if best is None or d < best[2]:
                best = (i, t, d)
        return best[0], best[1]

    def _position(self, p):
        """locate() as one number: index + parameter, in [0, n)."""
        i, t = self.locate(p)
        return (i + t) % len(self.cubics)

    def _walk(self, s0, s1):
        """The cubics of the spline from position s0 forwards to s1 (pieces of
        cubics where they start or end inside one)."""
        n = len(self.cubics)
        span = (s1 - s0) % n
        out = []
        k = math.floor(s0)
        while k < s0 + span:
            a, b = max(s0, k), min(s0 + span, k + 1)
            if b - a > 1e-9:
                out.append(_sub_cubic(self.cubics[k % n], a - k, b - k))
            k += 1
        return out

    def arc(self, a, b, other, external):
        """The arc of the spline from a to b (two points on it), as cubics in
        the direction a -> b.

        Of the two arcs between a and b, the external one is the one that
        faces away from `other` (a point in or near the plane of the circle:
        the center of the other circle, or the point of Tangents from
        Point), and the internal one the one that faces it. a and b are
        symmetric about the line from the center to `other`, so each arc
        holds one of the two points where that line crosses the circle: the
        external one holds the far one.
        """
        n = len(self.cubics)
        toward = geo.sub(other, self.center)
        toward = geo.sub(toward, geo.mul(self.normal, geo.dot(toward, self.normal)))
        toward = geo.normalized(toward) or (1.0, 0.0, 0.0)
        far = self._position(geo.sub(self.center, geo.mul(toward, self.radius)))
        sa, sb = self._position(a), self._position(b)
        holds_far = (far - sa) % n < (sb - sa) % n
        if holds_far == external:
            cubics = self._walk(sa, sb)
        else:
            cubics = [tuple(reversed(c)) for c in reversed(self._walk(sb, sa))]
        # The ends exactly where the lines end.
        if cubics:
            cubics[0] = (tuple(a),) + tuple(cubics[0][1:])
            cubics[-1] = tuple(cubics[-1][:3]) + (tuple(b),)
        return cubics


#: Samples per cubic before the closest point is refined.
_SNAP_SAMPLES = 48


def _closest_on_cubic(cubic, p):
    """(parameter, distance) of the point of a cubic closest to p."""
    def dist(t):
        return geo.distance(geo.bezier_point(*cubic, t), p)

    best = min(range(_SNAP_SAMPLES + 1), key=lambda i: dist(i / _SNAP_SAMPLES))
    lo = max(0.0, (best - 1) / _SNAP_SAMPLES)
    hi = min(1.0, (best + 1) / _SNAP_SAMPLES)
    g = 0.6180339887498949
    x1, x2 = hi - g * (hi - lo), lo + g * (hi - lo)
    f1, f2 = dist(x1), dist(x2)
    for _ in range(80):
        if f1 < f2:
            hi, x2, f2 = x2, x1, f1
            x1 = hi - g * (hi - lo)
            f1 = dist(x1)
        else:
            lo, x1, f1 = x1, x2, f2
            x2 = lo + g * (hi - lo)
            f2 = dist(x2)
    t = 0.5 * (lo + hi)
    return t, dist(t)


def _split_cubic(cubic, t):
    """De Casteljau: the two halves of a cubic (p0, h0, h1, p1) at t."""
    p0, h0, h1, p1 = cubic
    a, b, c = geo.lerp(p0, h0, t), geo.lerp(h0, h1, t), geo.lerp(h1, p1, t)
    d, e = geo.lerp(a, b, t), geo.lerp(b, c, t)
    m = geo.lerp(d, e, t)
    return (tuple(p0), a, d, m), (m, e, c, tuple(p1))


def _sub_cubic(cubic, t0, t1):
    """The piece of a cubic between the parameters t0 < t1."""
    if t1 < 1.0 - 1e-12:
        cubic = _split_cubic(cubic, t1)[0]
        t0 = t0 / t1
    if t0 > 1e-12:
        cubic = _split_cubic(cubic, t0)[1]
    return tuple(tuple(c) for c in cubic)


def _world_cubics(data, mw):
    """The segments of a closed spline as world-space cubics."""
    pts = data.points
    n = len(pts)
    out = []
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        if data.kind == 'BEZIER':
            cubic = (a.co, a.hr, b.hl, b.co)
        else:
            cubic = (a.co, geo.lerp(a.co, b.co, 1.0 / 3.0), geo.lerp(a.co, b.co, 2.0 / 3.0), b.co)
        out.append(tuple(tuple(mw @ Vector(c)) for c in cubic))
    return out


def _solve3(m, v):
    """Solve the 3 x 3 system m x = v (Cramer). None when it is singular."""
    def det(a):
        return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
                - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
                + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    d = det(m)
    if abs(d) < 1e-300:
        return None
    out = []
    for k in range(3):
        mk = [row[:] for row in m]
        for i in range(3):
            mk[i][k] = v[i]
        out.append(det(mk) / d)
    return out


def fit_circle(points, name):
    """The circle through a closed polyline (world space), or Fail."""
    n = len(points)
    if n < 4:
        raise Fail(f"{name} is not a circle")
    centroid = tuple(sum(p[i] for p in points) / n for i in range(3))
    # Newell's normal of the polygon.
    normal = (0.0, 0.0, 0.0)
    for a, b in zip(points, points[1:] + points[:1]):
        normal = geo.add(normal, ((a[1] - b[1]) * (a[2] + b[2]),
                                  (a[2] - b[2]) * (a[0] + b[0]),
                                  (a[0] - b[0]) * (a[1] + b[1])))
    normal = geo.normalized(normal)
    if normal is None:
        raise Fail(f"{name} is not a circle")
    ex = geo.normalized(geo.sub(points[0], centroid))
    if ex is None:
        raise Fail(f"{name} is not a circle")
    ex = geo.normalized(geo.sub(ex, geo.mul(normal, geo.dot(ex, normal))))
    ey = geo.cross(normal, ex)
    xy = [(geo.dot(geo.sub(p, centroid), ex), geo.dot(geo.sub(p, centroid), ey)) for p in points]
    # Algebraic fit: x^2 + y^2 + D x + E y + F = 0, in least squares.
    sxx = sum(x * x for x, _ in xy)
    syy = sum(y * y for _, y in xy)
    sxy = sum(x * y for x, y in xy)
    sx = sum(x for x, _ in xy)
    sy = sum(y for _, y in xy)
    z = [x * x + y * y for x, y in xy]
    sol = _solve3([[sxx, sxy, sx], [sxy, syy, sy], [sx, sy, n]],
                  [-sum(zi * x for zi, (x, _) in zip(z, xy)),
                   -sum(zi * y for zi, (_, y) in zip(z, xy)),
                   -sum(z)])
    if sol is None:
        raise Fail(f"{name} is not a circle")
    d, e, f = sol
    cx, cy = -d / 2.0, -e / 2.0
    r2 = cx * cx + cy * cy - f
    if r2 <= 0.0:
        raise Fail(f"{name} is not a circle")
    radius = math.sqrt(r2)
    worst = max(abs(math.hypot(x - cx, y - cy) - radius) for x, y in xy)
    flat = max(abs(geo.dot(geo.sub(p, centroid), normal)) for p in points)
    if worst > CIRCLE_TOLERANCE * radius or flat > CIRCLE_TOLERANCE * radius:
        raise Fail(f"{name} is not a circle (or it is not round in the scene: a non-uniform "
                   "scale turns a circle into an ellipse)")
    center = geo.add(centroid, geo.add(geo.mul(ex, cx), geo.mul(ey, cy)))
    return FittedCircle(center, radius, normal)


def circle_of(obj, data):
    """FittedCircle of a spline of `obj`, or Fail."""
    name = f"A spline of '{obj.name}'"
    if not data.cyclic:
        raise Fail(f"{name} is open: Tangents to 2 Circles needs two closed circles")
    if data.kind == 'NURBS':
        raise Fail(f"{name} is a NURBS spline: only Poly and Bezier circles are supported")
    mw = world_matrix(obj)
    local = sd.flatten(data, steps=16)
    if len(local) > 1 and geo.distance(local[0], local[-1]) < 1e-12:
        local = local[:-1]
    circle = fit_circle([tuple(mw @ Vector(p)) for p in local], name)
    circle.cubics = _world_cubics(data, mw)
    return circle


# -----------------------------------------------------------------------------
# Tangents
# -----------------------------------------------------------------------------

class Pair:
    """Two coplanar circles, in the 2D frame (u from the first center to the
    second, v across) of their common plane."""

    def __init__(self, a, b):
        self.a, self.b = a, b
        size = max(a.radius, b.radius, geo.distance(a.center, b.center))
        if abs(geo.dot(a.normal, b.normal)) < 1.0 - PLANE_TOLERANCE or \
                abs(geo.dot(geo.sub(b.center, a.center), a.normal)) > PLANE_TOLERANCE * size:
            raise Fail("The two circles are not in the same plane")
        self.normal = a.normal
        self.d = geo.distance(a.center, b.center)
        if self.d <= abs(a.radius - b.radius) + 1e-9 * size:
            raise Fail("One circle is inside the other: they have no tangents in common")
        self.u = geo.mul(geo.sub(b.center, a.center), 1.0 / self.d)
        self.v = geo.cross(self.normal, self.u)

    def direction(self, angle):
        return geo.add(geo.mul(self.u, math.cos(angle)), geo.mul(self.v, math.sin(angle)))

    def outer(self):
        """The two outer (main) tangents, as (point on a, point on b)."""
        alpha = math.acos(max(-1.0, min(1.0, (self.a.radius - self.b.radius) / self.d)))
        out = []
        for angle in (alpha, -alpha):
            n = self.direction(angle)
            out.append((self.a.snap(geo.add(self.a.center, geo.mul(n, self.a.radius))),
                        self.b.snap(geo.add(self.b.center, geo.mul(n, self.b.radius)))))
        return out

    def crossing(self):
        """The two inner (crossing) tangents, or [] when the circles overlap."""
        ratio = (self.a.radius + self.b.radius) / self.d
        if ratio >= 1.0:
            return []
        alpha = math.acos(ratio)
        out = []
        for angle in (alpha, -alpha):
            n = self.direction(angle)
            out.append((self.a.snap(geo.add(self.a.center, geo.mul(n, self.a.radius))),
                        self.b.snap(geo.sub(self.b.center, geo.mul(n, self.b.radius)))))
        return out


def segment(a, b):
    """A straight Bezier segment from a to b, with Vector handles."""
    points = [
        sd.PointData(co=a, hl=geo.lerp(a, b, -1.0 / 3.0), hr=geo.lerp(a, b, 1.0 / 3.0),
                     hlt='VECTOR', hrt='VECTOR', select=True, select_left=True, select_right=True),
        sd.PointData(co=b, hl=geo.lerp(b, a, 1.0 / 3.0), hr=geo.lerp(b, a, -1.0 / 3.0),
                     hlt='VECTOR', hrt='VECTOR', select=True, select_left=True, select_right=True),
    ]
    return sd.SplineData('BEZIER', points, False, {})


def line_cubic(a, b):
    """A straight cubic from a to b, its handles at the thirds."""
    return (tuple(a), geo.lerp(a, b, 1.0 / 3.0), geo.lerp(a, b, 2.0 / 3.0), tuple(b))


def _is_straight(cubic):
    """True when a cubic is a straight line with its handles at the thirds,
    which is what a Vector handle gives."""
    p0, h0, h1, p1 = cubic
    size = geo.distance(p0, p1)
    tol = 1e-6 * max(size, 1e-9)
    return (geo.distance(h0, geo.lerp(p0, p1, 1.0 / 3.0)) < tol
            and geo.distance(h1, geo.lerp(p0, p1, 2.0 / 3.0)) < tol)


def loop(cubics):
    """A closed Bezier spline from a chain of cubics, each one starting where
    the one before it ends, selected.

    Handle types: Vector on the side of a straight piece; Aligned where two
    curved pieces go on smoothly (inside an arc); Free elsewhere (where a
    line meets an arc: tangent, but left as it is)."""
    cubics = [c for c in cubics if geo.distance(c[0], c[3]) > 1e-9
              or geo.distance(c[0], c[1]) > 1e-9 or geo.distance(c[0], c[2]) > 1e-9]
    points = []
    for k, cubic in enumerate(cubics):
        prev = cubics[k - 1]
        co, hl, hr = cubic[0], prev[2], cubic[1]
        in_straight, out_straight = _is_straight(prev), _is_straight(cubic)
        hlt = 'VECTOR' if in_straight else 'FREE'
        hrt = 'VECTOR' if out_straight else 'FREE'
        if not in_straight and not out_straight:
            back = geo.normalized(geo.sub(hl, co))
            ahead = geo.normalized(geo.sub(hr, co))
            if back is not None and ahead is not None and geo.dot(back, ahead) < -1.0 + 1e-6:
                hlt = hrt = 'ALIGNED'
        points.append(sd.PointData(co=tuple(co), hl=tuple(hl), hr=tuple(hr), hlt=hlt, hrt=hrt,
                                   select=True, select_left=True, select_right=True))
    return sd.SplineData('BEZIER', points, True, {})


def transformed(data, matrix):
    for p in data.points:
        p.co = tuple(matrix @ Vector(p.co))
        if p.hl is not None:
            p.hl = tuple(matrix @ Vector(p.hl))
            p.hr = tuple(matrix @ Vector(p.hr))
    return data


def _deselect_all(curve):
    for spline in curve.splines:
        if spline.type == 'BEZIER':
            for bp in spline.bezier_points:
                bp.select_control_point = bp.select_left_handle = bp.select_right_handle = False
        else:
            for p in spline.points:
                p.select = False


# -----------------------------------------------------------------------------
# Operator
# -----------------------------------------------------------------------------

class ETR_OT_curve_toolkit_tangents_2_circles(bpy.types.Operator):
    """Draw the straight lines tangent to 2 circles (2 curve objects, or 2 splines of one curve): the main ones and/or the crossing ones, or closed loops made of them and the external or internal arcs of the circles"""
    bl_idname = "etr.curve_toolkit_tangents_2_circles"
    bl_label = "Tangents to 2 Circles"
    bl_options = {'REGISTER', 'UNDO'}

    main: BoolProperty(
        name="Main Tangents",
        description="The two outer tangents, the ones that do not cross",
        default=True,
    )
    crossing: BoolProperty(
        name="Crossing Tangents",
        description="The two inner tangents, the ones that cross between the circles "
                    "(only when the circles do not overlap)",
        default=False,
    )
    external_loop: BoolProperty(
        name="Create External Loop(s)",
        description="Instead of the lines, a closed loop for each kind of tangents that is "
                    "on: the tangents and the arcs of the circles that face away from the "
                    "other circle (a figure of eight with the crossing tangents)",
        default=False,
    )
    internal_loop: BoolProperty(
        name="Create Internal Loop(s)",
        description="Instead of the lines, a closed loop for each kind of tangents that is "
                    "on: the tangents and the arcs of the circles that face the other circle "
                    "(a figure of eight with the crossing tangents)",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        if context.mode == 'OBJECT' and selected_curves(context):
            return True
        if context.mode == EDIT_MODE and curves_in_edit_mode(context):
            return True
        cls.poll_message_set("Select two circles: two curve objects, or two splines of one curve")
        return False

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "main")
        layout.prop(self, "crossing")
        layout.prop(self, "external_loop")
        layout.prop(self, "internal_loop")

    def execute(self, context):
        try:
            if context.mode == EDIT_MODE:
                return self._edit(context)
            return self._object(context)
        except Fail as error:
            self.report({'ERROR'}, f"Tangents to 2 Circles: {error}")
            return {'CANCELLED'}

    # -- Picking -------------------------------------------------------------

    @staticmethod
    def _picked_objects(context):
        objs = selected_curves(context)
        picked = []
        for obj in objs:
            for data in sd.read_all(obj.data):
                picked.append((obj, data))
        if len(picked) != 2:
            raise Fail("select two circles: two curve objects with one spline each, or one "
                       f"curve object with two splines ({len(picked)} splines selected)")
        return picked

    @staticmethod
    def _picked_splines(objs):
        picked = []
        for obj in objs:
            for data in sd.read_all(obj.data):
                if any(sd.point_selected(p, data.kind) for p in data.points):
                    picked.append((obj, data))
        if len(picked) != 2:
            raise Fail("select a point of each of the two circles "
                       f"({len(picked)} splines have selected points)")
        return picked

    def _shapes(self, pair):
        """SplineData (world space) to write; [] (with a warning) when there
        is nothing to draw."""
        sets = []
        if self.main:
            sets.append(pair.outer())
        if self.crossing:
            inner = pair.crossing()
            if inner:
                sets.append(inner)
            else:
                self.report({'WARNING'}, "The circles overlap: there are no crossing tangents")
        if not self.main and not self.crossing:
            self.report({'WARNING'}, "Nothing to draw: turn on Main Tangents or Crossing "
                                     "Tangents")
        kinds = [k for k, on in ((True, self.external_loop), (False, self.internal_loop)) if on]
        if not kinds:
            return [segment(*points) for lines in sets for points in lines]
        # Each loop: the arc of the first circle between the ends of the two
        # tangents, the second tangent, the arc of the second circle back, and
        # the first tangent. With the crossing tangents the two tangents cross:
        # a figure of eight.
        datas = []
        for (a0, b0), (a1, b1) in sets:
            for external in kinds:
                datas.append(loop(pair.a.arc(a0, a1, pair.b.center, external)
                                  + [line_cubic(a1, b1)]
                                  + pair.b.arc(b1, b0, pair.a.center, external)
                                  + [line_cubic(b0, a0)]))
        return datas

    # -- Object Mode ---------------------------------------------------------

    def _object(self, context):
        """The new splines go into a new third object; the circles stay, only
        deselected."""
        picked = self._picked_objects(context)
        pair = Pair(*(circle_of(obj, data) for obj, data in picked))
        datas = self._shapes(pair)
        if not datas:
            return {'FINISHED'}
        (obj_a, _), (obj_b, _) = picked
        active = context.active_object if context.active_object in (obj_a, obj_b) else obj_a
        to_local = world_matrix(active).inverted()
        result = new_curve_object(context, active, [transformed(d, to_local) for d in datas],
                                  "Tangents")
        link_like(result, active, context)
        for obj in context.selected_objects:
            obj.select_set(False)
        result.select_set(True)
        context.view_layer.objects.active = result
        return {'FINISHED'}

    # -- Edit Mode -----------------------------------------------------------

    def _edit(self, context):
        """The new splines go into the curve being edited (the active one,
        when the circles are in two curves), selected; the circles stay, only
        deselected."""
        active = context.active_object
        with edit_scope(context) as objs:
            picked = self._picked_splines(objs)
            pair = Pair(*(circle_of(obj, data) for obj, data in picked))
            datas = self._shapes(pair)
            if not datas:
                return {'FINISHED'}
            (obj_a, _), (obj_b, _) = picked
            target = active if active in (obj_a, obj_b) else obj_a
            to_local = world_matrix(target).inverted()
            for o in objs:
                _deselect_all(o.data)
            for d in datas:
                spline = sd.write_spline(target.data, transformed(d, to_local))
            target.data.splines.active = spline
        self.report({'INFO'}, f"Added {len(datas)} spline(s) to '{target.name}'")
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Tangents from Point
# -----------------------------------------------------------------------------

FROM_POINT = "Tangents from Point"


def tangent_points(point, circle):
    """The two points where the lines from `point` (world) touch `circle`
    (a FittedCircle), or None when the point is inside it or on it."""
    c, r, n = circle.center, circle.radius, circle.normal
    d = geo.sub(point, c)
    flat = geo.sub(d, geo.mul(n, geo.dot(d, n)))
    dist = geo.length(flat)
    if dist <= r * (1.0 + 1e-6):
        return None
    e1 = geo.mul(flat, 1.0 / dist)
    e2 = geo.cross(n, e1)
    cos_a = r / dist
    sin_a = math.sqrt(max(0.0, 1.0 - cos_a * cos_a))
    return [circle.snap(geo.add(c, geo.mul(geo.add(geo.mul(e1, cos_a), geo.mul(e2, side * sin_a)),
                                           r)))
            for side in (1.0, -1.0)]


def poly_segment(a, b):
    """A Poly spline of two points (selected), from a to b."""
    return sd.SplineData('POLY', [sd.PointData(co=tuple(a), select=True),
                                  sd.PointData(co=tuple(b), select=True)], False, {})


def _try_circle(obj, data):
    try:
        return circle_of(obj, data)
    except Fail:
        return None


class ETR_OT_curve_toolkit_tangents_from_point(bpy.types.Operator):
    """Draw the two straight lines from a selected point that touch a circle (select the point and one or more points of the circle): two Poly segments in the same curve, or closed loops with the external or internal arc of the circle. Edit Mode"""
    bl_idname = "etr.curve_toolkit_tangents_from_point"
    bl_label = "Tangents from Point"
    bl_options = {'REGISTER', 'UNDO'}

    external_loop: BoolProperty(
        name="Create External Loop",
        description="Instead of the lines, a closed loop: the two lines and the arc of the "
                    "circle that faces away from the point",
        default=False,
    )
    internal_loop: BoolProperty(
        name="Create Internal Loop",
        description="Instead of the lines, a closed loop: the two lines and the arc of the "
                    "circle that faces the point",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "external_loop")
        layout.prop(self, "internal_loop")

    @classmethod
    def poll(cls, context):
        if context.mode == EDIT_MODE and curves_in_edit_mode(context):
            return True
        cls.poll_message_set("Works in the Edit Mode of a curve: select a point and a point "
                             "of a circle")
        return False

    def execute(self, context):
        try:
            with edit_scope(context) as objs:
                self._run(context, objs)
        except Fail as error:
            self.report({'ERROR'}, f"{FROM_POINT}: {error}")
            return {'CANCELLED'}
        return {'FINISHED'}

    def _run(self, context, objs):
        groups = []      # (object, SplineData, selected control points)
        for obj in objs:
            for data in sd.read_all(obj.data):
                sel = [p for p in data.points if p.select]
                if sel:
                    groups.append((obj, data, sel))
        if len(groups) != 2:
            raise Fail("select one point and one or more points of a circle "
                       f"({len(groups)} splines have selected points)")
        circles = [_try_circle(obj, data) for obj, data, _ in groups]
        if not any(circles):
            raise Fail("neither of the two splines is a circle (a closed Poly or Bezier "
                       "spline whose shape is a circle)")
        found = []
        inside = False
        for i in (0, 1):
            circle, (obj, _, sel) = circles[1 - i], groups[i]
            if circle is None or len(sel) != 1:
                continue
            point = tuple(world_matrix(obj) @ Vector(sel[0].co))
            touch = tangent_points(point, circle)
            if touch is None:
                inside = True
                continue
            found.append((point, touch, circle))
        if not found:
            if inside:
                raise Fail("the point is inside the circle (or on it): no line from it "
                           "touches the circle")
            raise Fail("select a single point outside the circle, and one or more points "
                       "of the circle")
        if len(found) > 1:
            raise Fail("both splines are circles and either point could be the one: select "
                       "more than one point of the circle")
        point, touch, circle = found[0]
        target = context.active_object if context.active_object in objs else groups[0][0]
        to_local = world_matrix(target).inverted()
        for o in objs:
            _deselect_all(o.data)
        kinds = [k for k, on in ((True, self.external_loop), (False, self.internal_loop)) if on]
        if kinds:
            t0, t1 = touch
            for external in kinds:
                data = loop([line_cubic(point, t0)] + circle.arc(t0, t1, point, external)
                            + [line_cubic(t1, point)])
                spline = sd.write_spline(target.data, transformed(data, to_local))
            self.report({'INFO'}, f"{FROM_POINT}: {len(kinds)} closed loop(s)")
        else:
            local = [tuple(to_local @ Vector(p)) for p in (point, *touch)]
            for t in local[1:]:
                spline = sd.write_spline(target.data, poly_segment(local[0], t))
            self.report({'INFO'}, f"{FROM_POINT}: 2 lines")
        target.data.splines.active = spline


classes = (ETR_OT_curve_toolkit_tangents_2_circles, ETR_OT_curve_toolkit_tangents_from_point)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
