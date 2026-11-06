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
  - Boolean All: instead of the lines, the closed shape of the two circles
    and their outer tangents, joined and merged (a belt around two pulleys):
    Vector handles along the straight sides, Aligned ones on the arcs. It
    always goes to a new object, so the circles are never touched; they are
    hidden, and only the new shape is left in view.

Where the lines go: when both circles are splines of one object, into that
object; when they are in two objects, into a new third object, with the look
and transform of the active one.

The circles may be anywhere and rotated, but they must lie in one common
plane, and neither may be fully inside the other.

Tangents from Point (Edit Mode)
    One point (a stray point, or a control point of any spline) and one or
    more points of a circle are selected. The button draws the two straight
    lines that start at that point and touch the circle, as two Poly
    segments of two points each, independent (not merged with the circle),
    in the curve being edited. The point may be out of the plane of the
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
    """center, radius and unit normal of a circle, in world space."""

    def __init__(self, center, radius, normal):
        self.center = center
        self.radius = radius
        self.normal = normal


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
    return fit_circle([tuple(mw @ Vector(p)) for p in local], name)


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
            out.append(((geo.add(self.a.center, geo.mul(n, self.a.radius)),
                         geo.add(self.b.center, geo.mul(n, self.b.radius))), angle))
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
            out.append((geo.add(self.a.center, geo.mul(n, self.a.radius)),
                        geo.sub(self.b.center, geo.mul(n, self.b.radius))))
        return out

    def belt(self):
        """Closed Bezier SplineData of the two circles and their outer
        tangents: arcs with Aligned handles, straight sides with Vector ones.
        It turns clockwise in the (u, v) frame."""
        (top, alpha), (bottom, _) = self.outer()
        a_top, b_top = top
        a_bottom, b_bottom = bottom

        def arc(circle, start_angle, sweep):
            e1 = self.direction(start_angle)
            e2 = geo.mul(geo.cross(self.normal, e1), -1.0)   # decreasing angle
            return geo.arc_beziers(circle.center, e1, e2, circle.radius, sweep)

        arc_b = arc(self.b, alpha, 2.0 * alpha)                      # far side of b
        arc_a = arc(self.a, -alpha, 2.0 * math.pi - 2.0 * alpha)     # far side of a
        points = []
        for anchors, before, after in ((arc_b, a_top, a_bottom), (arc_a, b_bottom, b_top)):
            last = len(anchors) - 1
            for i, (co, hl, hr) in enumerate(anchors):
                p = sd.PointData(co=co, hl=hl, hr=hr, hlt='ALIGNED', hrt='ALIGNED', select=True,
                                 select_left=True, select_right=True)
                if i == 0:
                    p.hl, p.hlt = geo.lerp(co, before, 1.0 / 3.0), 'VECTOR'
                if i == last:
                    p.hr, p.hrt = geo.lerp(co, after, 1.0 / 3.0), 'VECTOR'
                points.append(p)
        return sd.SplineData('BEZIER', points, True, {})


def segment(a, b):
    """A straight Bezier segment from a to b, with Vector handles."""
    points = [
        sd.PointData(co=a, hl=geo.lerp(a, b, -1.0 / 3.0), hr=geo.lerp(a, b, 1.0 / 3.0),
                     hlt='VECTOR', hrt='VECTOR', select=True, select_left=True, select_right=True),
        sd.PointData(co=b, hl=geo.lerp(b, a, 1.0 / 3.0), hr=geo.lerp(b, a, -1.0 / 3.0),
                     hlt='VECTOR', hrt='VECTOR', select=True, select_left=True, select_right=True),
    ]
    return sd.SplineData('BEZIER', points, False, {})


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


def _hide(objs):
    """Hide the source objects of the belt shape (in the View Layer)."""
    for obj in objs:
        try:
            obj.select_set(False)
            obj.hide_set(True)
        except RuntimeError:
            pass   # not in the View Layer


# -----------------------------------------------------------------------------
# Operator
# -----------------------------------------------------------------------------

class ETR_OT_curve_toolkit_tangents_2_circles(bpy.types.Operator):
    """Draw the straight lines tangent to 2 circles (2 curve objects, or 2 splines of one curve). Options: the crossing tangents too, or the whole belt shape joined and merged"""
    bl_idname = "etr.curve_toolkit_tangents_2_circles"
    bl_label = "Tangents to 2 Circles"
    bl_options = {'REGISTER', 'UNDO'}

    crossing: BoolProperty(
        name="Add Crossing Tangents",
        description="Also draw the two inner tangents, the ones that cross between the "
                    "circles (only when the circles do not overlap)",
        default=False,
    )
    boolean_all: BoolProperty(
        name="Boolean All",
        description="Instead of the lines, the closed shape of the two circles and their outer "
                    "tangents, joined and merged, as a new object",
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
        row = layout.row()
        row.enabled = not self.boolean_all
        row.prop(self, "crossing")
        layout.prop(self, "boolean_all")

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
        """SplineData (world space) to write, and how many tangents."""
        if self.boolean_all:
            return [pair.belt()]
        datas = [segment(*points) for points, _ in pair.outer()]
        if self.crossing:
            inner = pair.crossing()
            if not inner:
                self.report({'WARNING'}, "The circles overlap: there are no crossing tangents")
            datas += [segment(*points) for points in inner]
        return datas

    # -- Object Mode ---------------------------------------------------------

    def _object(self, context):
        picked = self._picked_objects(context)
        pair = Pair(*(circle_of(obj, data) for obj, data in picked))
        datas = self._shapes(pair)
        (obj_a, _), (obj_b, _) = picked
        active = context.active_object if context.active_object in (obj_a, obj_b) else obj_a

        if obj_a is obj_b and not self.boolean_all:
            to_local = world_matrix(obj_a).inverted()
            for d in datas:
                sd.write_spline(obj_a.data, transformed(d, to_local))
            self.report({'INFO'}, f"Added {len(datas)} tangent(s) to '{obj_a.name}'")
            return {'FINISHED'}

        name = "Belt" if self.boolean_all else "Tangents"
        to_local = world_matrix(active).inverted()
        result = new_curve_object(context, active, [transformed(d, to_local) for d in datas], name)
        link_like(result, active, context)
        for obj in context.selected_objects:
            obj.select_set(False)
        result.select_set(True)
        context.view_layer.objects.active = result
        if self.boolean_all:
            _hide({obj_a, obj_b})
        return {'FINISHED'}

    # -- Edit Mode -----------------------------------------------------------

    def _edit(self, context):
        active = context.active_object
        new_object = None
        with edit_scope(context) as objs:
            picked = self._picked_splines(objs)
            pair = Pair(*(circle_of(obj, data) for obj, data in picked))
            datas = self._shapes(pair)
            (obj_a, _), (obj_b, _) = picked
            if obj_a is obj_b and not self.boolean_all:
                to_local = world_matrix(obj_a).inverted()
                for o in objs:
                    _deselect_all(o.data)
                for d in datas:
                    sd.write_spline(obj_a.data, transformed(d, to_local))
                return {'FINISHED'}
            source = active if active in (obj_a, obj_b) else obj_a
            to_local = world_matrix(source).inverted()
            name = "Belt" if self.boolean_all else "Tangents"
            new_object = new_curve_object(
                context, source, [transformed(d, to_local) for d in datas], name)
            link_like(new_object, source, context)
        # The new object is left selected in Object Mode, next to the circles
        # (which are hidden when it is the belt shape).
        bpy.ops.object.mode_set(mode='OBJECT')
        for obj in context.selected_objects:
            obj.select_set(False)
        new_object.select_set(True)
        context.view_layer.objects.active = new_object
        if self.boolean_all:
            _hide({obj_a, obj_b})
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
    return [geo.add(c, geo.mul(geo.add(geo.mul(e1, cos_a), geo.mul(e2, side * sin_a)), r))
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
    """Draw the two straight lines from a selected point that touch a circle (select the point and one or more points of the circle). Two Poly segments, in the same curve. Edit Mode"""
    bl_idname = "etr.curve_toolkit_tangents_from_point"
    bl_label = "Tangents from Point"
    bl_options = {'REGISTER', 'UNDO'}

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
        spline = None
        for t in touch:
            spline = sd.write_spline(target.data, poly_segment(to_local @ Vector(point),
                                                               to_local @ Vector(t)))
        target.data.splines.active = spline
        self.report({'INFO'}, f"{FROM_POINT}: 2 lines")


classes = (ETR_OT_curve_toolkit_tangents_2_circles, ETR_OT_curve_toolkit_tangents_from_point)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
