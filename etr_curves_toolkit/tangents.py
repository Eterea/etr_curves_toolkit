# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Tangents to 2 Circles

Two circles (closed splines whose shape is a circle) are picked:

  - Object Mode: two selected curve objects with one circle each, or one
    selected curve object with exactly two splines, both circles.
  - Edit Mode: the two splines that have selected points (any point of a
    spline picks it), in one curve or in two curves being edited.

The button draws the two outer tangents (the "belt" lines) as straight
Bezier segments with Vector handles. Options (F9):

  - Add Crossing Tangents: the two inner tangents too, the ones that cross
    between the circles (only when the circles do not overlap).
  - Connect & Close: the ends of the tangents are joined into closed shapes:
    the two outer tangents and the chords between their ends make an
    isosceles trapezoid; the crossing tangents, cut where they cross, and the
    chord on each circle make two triangles that meet at that point. Straight
    sides with Vector handles.

Where the lines go:
  - Object Mode: when both circles are splines of one object, into that
    object; when they are in two objects, into a new third object
    ("Tangents"), with the look and transform of the active one.
  - Edit Mode: into the curve being edited (the active one, when the circles
    are in two curves), and they are left selected.

The circles may be anywhere and rotated, but they must lie in one common
plane, and neither may be fully inside the other.

Tangents from Point (Edit Mode)
    One point (a stray point, or a control point of any spline) and one or
    more points of a circle are selected. The button draws the two straight
    lines that start at that point and touch the circle, as two Poly
    segments of two points each, independent (not merged with the circle),
    in the curve being edited. With Connect & Close (F9) they become one
    closed Poly triangle: the point and the two points where the lines
    touch the circle. The point may be out of the plane of the
    circle: the lines still touch it (they are tangent in 3D). A point
    inside the circle, or on it, has no tangents.
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
        best = None
        for cubic in self.cubics:
            t, d = _closest_on_cubic(cubic, p)
            if best is None or d < best[1]:
                best = (geo.bezier_point(*cubic, t), d)
        return tuple(p) if best is None else tuple(best[0])


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
        """The two outer tangents, as ((point on a, point on b), angle), the
        angle being the one of their common radial direction."""
        alpha = math.acos(max(-1.0, min(1.0, (self.a.radius - self.b.radius) / self.d)))
        out = []
        for angle in (alpha, -alpha):
            n = self.direction(angle)
            out.append(((self.a.snap(geo.add(self.a.center, geo.mul(n, self.a.radius))),
                         self.b.snap(geo.add(self.b.center, geo.mul(n, self.b.radius)))), angle))
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

    def crossing_point(self, inner):
        """Where the two crossing tangents (as given by crossing()) cross.

        On ideal circles it is the point of the line of the centers that
        divides it in the ratio of the radii; with the ends put on the real
        splines the two lines are crossed instead, so the two triangles meet
        exactly at a point of both."""
        (a0, b0), (a1, b1) = inner
        d0, d1 = geo.sub(b0, a0), geo.sub(b1, a1)
        # a0 + s d0 = a1 + t d1, solved in the plane (least squares in 3D).
        w = geo.sub(a1, a0)
        d00, d01, d11 = geo.dot(d0, d0), geo.dot(d0, d1), geo.dot(d1, d1)
        den = d00 * d11 - d01 * d01
        if abs(den) < 1e-300:
            k = self.a.radius / (self.a.radius + self.b.radius)
            return geo.add(self.a.center, geo.mul(self.u, self.d * k))
        s_ = (geo.dot(w, d0) * d11 - geo.dot(w, d1) * d01) / den
        return geo.add(a0, geo.mul(d0, s_))


def segment(a, b):
    """A straight Bezier segment from a to b, with Vector handles."""
    points = [
        sd.PointData(co=a, hl=geo.lerp(a, b, -1.0 / 3.0), hr=geo.lerp(a, b, 1.0 / 3.0),
                     hlt='VECTOR', hrt='VECTOR', select=True, select_left=True, select_right=True),
        sd.PointData(co=b, hl=geo.lerp(b, a, 1.0 / 3.0), hr=geo.lerp(b, a, -1.0 / 3.0),
                     hlt='VECTOR', hrt='VECTOR', select=True, select_left=True, select_right=True),
    ]
    return sd.SplineData('BEZIER', points, False, {})


def polygon(points):
    """A closed Bezier spline through `points`, straight sides with Vector
    handles."""
    n = len(points)
    out = []
    for i, co in enumerate(points):
        prev, nxt = points[i - 1], points[(i + 1) % n]
        out.append(sd.PointData(co=co, hl=geo.lerp(co, prev, 1.0 / 3.0),
                                hr=geo.lerp(co, nxt, 1.0 / 3.0), hlt='VECTOR', hrt='VECTOR',
                                select=True, select_left=True, select_right=True))
    return sd.SplineData('BEZIER', out, True, {})


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
    """Draw the straight lines tangent to 2 circles (2 curve objects, or 2 splines of one curve). Options: the crossing tangents too, and Connect & Close, which joins their ends into closed shapes"""
    bl_idname = "etr.curve_toolkit_tangents_2_circles"
    bl_label = "Tangents to 2 Circles"
    bl_options = {'REGISTER', 'UNDO'}

    crossing: BoolProperty(
        name="Add Crossing Tangents",
        description="Also draw the two inner tangents, the ones that cross between the "
                    "circles (only when the circles do not overlap)",
        default=False,
    )
    connect_close: BoolProperty(
        name="Connect & Close",
        description="Join the ends of the tangents into closed shapes: the outer ones into "
                    "an isosceles trapezoid, the crossing ones into two triangles that meet "
                    "where they cross",
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
        layout.prop(self, "crossing")
        layout.prop(self, "connect_close")

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
        """SplineData (world space) to write."""
        outer = [points for points, _ in pair.outer()]
        inner = []
        if self.crossing:
            inner = pair.crossing()
            if not inner:
                self.report({'WARNING'}, "The circles overlap: there are no crossing tangents")
        if not self.connect_close:
            return [segment(*points) for points in outer + inner]
        # The outer tangents and the two chords between their ends: an
        # isosceles trapezoid. The crossing ones, cut where they cross, and
        # the chord on each circle: two triangles.
        (a_top, b_top), (a_bottom, b_bottom) = outer
        datas = [polygon([a_top, b_top, b_bottom, a_bottom])]
        if inner:
            (a0, b0), (a1, b1) = inner
            x = pair.crossing_point(inner)
            datas += [polygon([a0, x, a1]), polygon([b0, x, b1])]
        return datas

    # -- Object Mode ---------------------------------------------------------

    def _object(self, context):
        picked = self._picked_objects(context)
        pair = Pair(*(circle_of(obj, data) for obj, data in picked))
        datas = self._shapes(pair)
        (obj_a, _), (obj_b, _) = picked
        active = context.active_object if context.active_object in (obj_a, obj_b) else obj_a

        if obj_a is obj_b:
            to_local = world_matrix(obj_a).inverted()
            for d in datas:
                sd.write_spline(obj_a.data, transformed(d, to_local))
            self.report({'INFO'}, f"Added {len(datas)} spline(s) to '{obj_a.name}'")
            return {'FINISHED'}

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
        when the circles are in two curves), selected."""
        active = context.active_object
        with edit_scope(context) as objs:
            picked = self._picked_splines(objs)
            pair = Pair(*(circle_of(obj, data) for obj, data in picked))
            datas = self._shapes(pair)
            (obj_a, _), (obj_b, _) = picked
            target = active if active in (obj_a, obj_b) else obj_a
            to_local = world_matrix(target).inverted()
            for o in objs:
                _deselect_all(o.data)
            for d in datas:
                sd.write_spline(target.data, transformed(d, to_local))
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
    """Draw the two straight lines from a selected point that touch a circle (select the point and one or more points of the circle). Two Poly segments, in the same curve, or a closed triangle with Connect & Close. Edit Mode"""
    bl_idname = "etr.curve_toolkit_tangents_from_point"
    bl_label = "Tangents from Point"
    bl_options = {'REGISTER', 'UNDO'}

    connect_close: BoolProperty(
        name="Connect & Close",
        description="Join the two lines into a closed triangle: their ends on the circle "
                    "are joined, and their ends at the point are merged",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "connect_close")

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
            found.append((point, touch))
        if not found:
            if inside:
                raise Fail("the point is inside the circle (or on it): no line from it "
                           "touches the circle")
            raise Fail("select a single point outside the circle, and one or more points "
                       "of the circle")
        if len(found) > 1:
            raise Fail("both splines are circles and either point could be the one: select "
                       "more than one point of the circle")
        point, touch = found[0]
        target = context.active_object if context.active_object in objs else groups[0][0]
        to_local = world_matrix(target).inverted()
        for o in objs:
            _deselect_all(o.data)
        local = [tuple(to_local @ Vector(p)) for p in (point, *touch)]
        if self.connect_close:
            spline = sd.write_spline(target.data, sd.SplineData(
                'POLY', [sd.PointData(co=co, select=True) for co in local], True, {}))
            self.report({'INFO'}, f"{FROM_POINT}: a closed triangle")
        else:
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
