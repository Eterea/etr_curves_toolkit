# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Extend Curve (Edit Mode)

Extends the open splines of a curve from their selected end points: each of
those points stays where it is and a new piece grows out of it, following the
direction the curve leaves with. The new end points are the ones left
selected, so the button can be pressed again to keep going. Every end point
gets the same settings, and a selected point that is not the end of an open
Poly or Bezier spline is simply left alone (the report says how many).

The piece is an arc of a circle, which is the shape that behaves at any
distance: it leaves the curve with the same tangent and keeps turning at the
same rate (a prolonged cubic would also leave with the same curvature, but it
shoots off as soon as the distance grows). On a Bezier spline, two ways to say
how much it turns:

  - Automatic   the curvature the curve arrives with: the radius of its
                osculating circle at that point, which depends on the handle
                that arrives and on the point and handle before it. The
                extension continues the bend as it is.
  - Manual      a Curvature angle, the turn of the arc itself: 0 leaves
                straight along the tangent, and up to a full circle either
                way (positive to the right). Exact angles come out exact, so
                it also builds arcs of 30, 45 or 120 degrees.

A Poly spline has no curvature to continue, so it is extended straight, with
one new point, in the direction of its last segment turned by the Direction
angle (0 keeps that direction, positive turns to the right).

Both angles turn in the plane the spline lies in, whatever its orientation, so
that left and right are the ones seen from the + side of that plane (+Z for a
curve in the XY plane). Only a warped 3D spline has no plane of its own, and
then the plane it is bending in, or the local XY plane, is used.

The arc comes from geometry.arc_beziers(), the same one Round Corners uses, so
an extension that turns more than 90 degrees comes in as several cubics.
"""

import math

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty
from mathutils import Vector

from . import geometry as geo
from . import spline_data as sd
from .booleans import Fail
from .context_utils import EDIT_MODE, edit_scope, has_active_curve, world_matrix
from .primitives import unit_scale

# Share of the size of the spline the default Distance comes in at.
DEFAULT_SHARE = 0.15
# Widest arc a single cubic is asked to cover. A hair over 90 degrees on
# purpose: an angle typed as 90 is stored in a single-precision property, and
# comes back as 90.0000003, which would otherwise be cut into two cubics.
MAX_STEP = math.pi / 2.0 * (1.0 + 1e-6)
# Mantissas a default Distance is rounded to (times a power of ten).
_NICE = (1.0, 1.5, 2.0, 3.0, 5.0, 7.5, 10.0)


# -----------------------------------------------------------------------------
# Lengths
# -----------------------------------------------------------------------------

def nice_length(value):
    """A round-ish number near `value`: 1, 1.5, 2, 3, 5 or 7.5 times a power
    of ten (0.16489 -> 0.15)."""
    if value <= 0.0:
        return 0.0
    exponent = math.floor(math.log10(value))
    base = 10.0 ** exponent
    mantissa = value / base
    return min(_NICE, key=lambda step: abs(step - mantissa)) * base


def spline_size(data):
    """Largest side of the bounding box of the control points of a spline."""
    pts = [p.co for p in data.points]
    if not pts:
        return 0.0
    return max(max(c[i] for c in pts) - min(c[i] for c in pts) for i in range(3))


def _average_scale(obj):
    """(average scale of the object, True when it is not uniform).

    The Distance of the panel is a length in the scene, and the spline is
    extended in the local space of its object.
    """
    mw = world_matrix(obj)
    axes = [Vector((mw[0][i], mw[1][i], mw[2][i])).length for i in range(3)]
    average = sum(axes) / 3.0
    if average < 1e-9:
        return None, False
    return average, (max(axes) - min(axes)) > 1e-4 * max(axes)


# -----------------------------------------------------------------------------
# The circle the curve arrives with
# -----------------------------------------------------------------------------

def frame_at_end(data):
    """How the spline leaves its last point.

    Returns (tangent, centre direction, curvature):
      tangent           unit vector leaving the curve at the last point.
      centre direction  unit vector from that point towards the centre of the
                        osculating circle, or None when the curve arrives
                        straight (a Poly spline always does).
      curvature         1 / radius of that circle, 0.0 when straight.
    Raises Fail when not even a direction can be worked out.
    """
    pts = data.points
    end = pts[-1]

    if data.kind != 'BEZIER':
        for prev in reversed(pts[:-1]):
            tangent = geo.normalized(geo.sub(end.co, prev.co))
            if tangent is not None:
                return tangent, None, 0.0
        raise Fail("every point of that spline is in the same place, so it has no direction")

    prev = pts[-2]
    p1, p2, p3 = prev.hr, end.hl, end.co
    # Derivatives of the cubic at its end: B'(1) = 3 (P3 - P2) and
    # B''(1) = 6 (P1 - 2 P2 + P3).
    d1 = geo.mul(geo.sub(p3, p2), 3.0)
    d2 = geo.mul(geo.add(geo.sub(p3, geo.mul(p2, 2.0)), p1), 6.0)
    tangent = geo.normalized(d1)
    if tangent is None:
        # The handle that arrives sits on the point itself, so the cubic has
        # no speed there: look further back, as the tangent of a corner does.
        inward = geo.tangent_at_end(p3, p2, prev.co, p1)
        if inward is None:
            raise Fail("that end point and its neighbour are in the same place, "
                       "so the curve has no direction there")
        return geo.mul(inward, -1.0), None, 0.0

    # The part of B'' across the tangent points at the centre of the circle.
    centre = geo.normalized(geo.sub(d2, geo.mul(tangent, geo.dot(d2, tangent))))
    speed = geo.length(d1)
    curvature = geo.length(geo.cross(d1, d2)) / (speed ** 3)
    if centre is None or curvature < 1e-9:
        return tangent, None, 0.0
    return tangent, centre, curvature


def spline_plane(data, tol=1e-6):
    """Unit normal of the plane the spline lies in, or None when it is warped
    (or too small to say, as a straight spline of two points is).

    The side the normal points to does not depend on the order of the points:
    it is chosen towards +Z, +Y or +X, whichever axis the plane faces most. So
    a curve in the XY plane always gives +Z, and left and right never flip
    between one press of the button and the next.
    """
    coords = _coords(data)
    if len(coords) < 3:
        return None
    origin = coords[0]
    size = max(geo.distance(c, origin) for c in coords)
    if size < geo.EPS:
        return None
    # The farthest point gives the steadiest first direction, and the point
    # farthest from that line the second one.
    along = geo.normalized(geo.sub(max(coords, key=lambda c: geo.distance(c, origin)), origin))
    if along is None:
        return None
    best, normal = 0.0, None
    for c in coords[1:]:
        candidate = geo.cross(along, geo.sub(c, origin))
        extent = geo.length(candidate)
        if extent > best:
            best, normal = extent, candidate
    normal = geo.normalized(normal) if normal is not None else None
    if normal is None:
        return None
    if any(abs(geo.dot(geo.sub(c, origin), normal)) > tol * size for c in coords):
        return None                                   # warped: no plane
    axis = max((2, 1, 0), key=lambda i: abs(normal[i]))
    return normal if normal[axis] > 0.0 else geo.mul(normal, -1.0)


def bend_normal(data, tangent):
    """Unit normal of the plane the extension turns in.

    The plane of the spline when it has one, so that left and right are the
    ones seen from the + side of that plane. Otherwise (a warped spline, or a
    straight one of two points) the local XY plane, the plane the curve is
    bending in, or the first axis that is not along the tangent, in that order.
    """
    plane = spline_plane(data)
    if plane is not None:
        normal = _across(tangent, plane)
        if normal is not None:
            return normal
    if _flat_in_xy(data):
        normal = _across(tangent, (0.0, 0.0, 1.0))
        if normal is not None:
            return normal
    _, centre, curvature = frame_at_end(data)
    if centre is not None and curvature > 1e-9:
        binormal = geo.normalized(geo.cross(tangent, centre))
        if binormal is not None:
            return binormal
    for axis in ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)):
        normal = _across(tangent, axis)
        if normal is not None:
            return normal
    return (0.0, 0.0, 1.0)


def aimed(tangent, normal, angle):
    """Tangent turned by `angle` inside the plane of `normal`.

    A positive angle turns to the right, which is clockwise seen from the +
    side of the normal (so from +Z on a curve in the XY plane).
    """
    if abs(angle) < 1e-9:
        return tangent
    left = geo.normalized(geo.cross(normal, tangent))
    if left is None:
        return tangent
    turned = geo.add(
        geo.mul(tangent, math.cos(angle)), geo.mul(left, -math.sin(angle)))
    return geo.normalized(turned) or tangent


def _across(tangent, axis):
    """Unit part of `axis` across `tangent`, or None if they are parallel."""
    return geo.normalized(geo.sub(axis, geo.mul(tangent, geo.dot(axis, tangent))))


def _coords(data):
    coords = [p.co for p in data.points]
    if data.kind == 'BEZIER':
        coords += [p.hl for p in data.points] + [p.hr for p in data.points]
    return coords


def _flat_in_xy(data):
    coords = _coords(data)
    size = max((max(abs(c[0]), abs(c[1])) for c in coords), default=0.0)
    return all(abs(c[2]) <= 1e-6 * size + 1e-7 for c in coords)


# -----------------------------------------------------------------------------
# The new piece
# -----------------------------------------------------------------------------

def extension_anchors(point, tangent, centre, curvature, length):
    """Anchors (point, handle left, handle right) of the extension, from the
    end point of the curve to the new end point.

    Returns (anchors, straight). A straight extension gives two anchors, an
    arc gives one more every 90 degrees.
    """
    if centre is None or curvature < 1e-9:
        end = geo.add(point, geo.mul(tangent, length))
        k = length / 3.0
        return [
            (point, point, geo.add(point, geo.mul(tangent, k))),
            (end, geo.sub(end, geo.mul(tangent, k)), end),
        ], True

    radius = 1.0 / curvature
    # A full turn is as far as this goes: more would just wind over itself.
    # At exactly one turn the new end point lands on the one it grew from.
    sweep = min(curvature * length, 2.0 * math.pi)
    anchors = geo.arc_beziers(
        geo.add(point, geo.mul(centre, radius)),
        geo.mul(centre, -1.0), tangent, radius, sweep, max_step=MAX_STEP)
    return anchors, False


def extended(data, tangent, centre, curvature, length):
    """Snapshot of `data` with the extension added after its last point.

    The end point of the curve keeps its place and the handle that arrives at
    it, so the shape that was there does not move. Its outgoing handle is the
    one the extension needs, which means an Auto or Aligned handle on that
    side becomes Free (Blender would recalculate it and pull the last segment
    out of shape).

    Only the point it grows from is deselected, and the new end point is
    selected, so extending both ends of one spline leaves both new ends
    selected.
    """
    anchors, straight = extension_anchors(
        data.points[-1].co, tangent, centre, curvature, length)

    out = data.copy()
    end = out.points[-1]
    end.select = end.select_left = end.select_right = False

    if out.kind != 'BEZIER':
        out.points.append(sd.replace(end, co=anchors[-1][0], select=True))
        return out

    end.hlt = sd.settle_handle_type(end.hlt)
    end.hr = anchors[0][2]
    # A straight piece is exactly what a Vector handle does: it points at the
    # next control point, at a third of the way.
    end.hrt = 'VECTOR' if straight else 'FREE'

    for position, hl, hr in anchors[1:-1]:
        out.points.append(sd.replace(
            end, co=position, hl=hl, hr=hr, hlt='FREE', hrt='FREE',
            select=False, select_left=False, select_right=False))

    position, hl, _ = anchors[-1]
    out.points.append(sd.replace(
        end, co=position, hl=hl,
        # Nothing comes after, so the free side mirrors the one that arrives.
        hr=geo.add(position, geo.sub(position, hl)),
        hlt='ALIGNED', hrt='ALIGNED',
        select=True, select_left=True, select_right=True))
    return out


# -----------------------------------------------------------------------------
# Operator
# -----------------------------------------------------------------------------

class ETR_OT_curve_toolkit_extend(bpy.types.Operator):
    """Extend the open curves from their selected end points, with a new arc that leaves with the same tangent. Automatic or Manual curvature for Bezier, a Direction angle for Poly. Several end points at a time"""
    bl_idname = "etr.curve_toolkit_extend"
    bl_label = "Extend"
    bl_options = {'REGISTER', 'UNDO'}

    distance: FloatProperty(
        name="Distance",
        description=(
            "Length of the new piece, measured along it. The default is about "
            "15% of the size of the spline, rounded"
        ),
        default=0.1,
        min=0.0,
        soft_max=10.0,
        precision=4,
        subtype='DISTANCE',
        unit='LENGTH',
    )
    mode: EnumProperty(
        name="Curvature",
        description="How much the new piece turns, on a Bezier spline",
        items=(
            ('AUTOMATIC', "Automatic",
             "Keep turning as the curve does where it arrives, at the radius of "
             "its osculating circle"),
            ('MANUAL', "Manual", "Take the turn from the Curvature angle"),
        ),
        default='AUTOMATIC',
    )
    curvature: FloatProperty(
        name="Curvature",
        description=(
            "Angle the new piece turns, with Curvature set to Manual: 0 leaves "
            "straight along the tangent, positive turns to the right and "
            "negative to the left, up to a full circle either way. An exact "
            "angle gives an exact arc, so this also draws arcs of 30, 45 or "
            "120 degrees"
        ),
        default=0.0,
        min=-2.0 * math.pi,
        max=2.0 * math.pi,
        subtype='ANGLE',
        unit='ROTATION',
    )
    direction: FloatProperty(
        name="Direction",
        description=(
            "Angle the straight piece of a Poly spline leaves at: 0 keeps the "
            "direction of its last segment, positive turns to the right and "
            "negative to the left, up to half a turn either way"
        ),
        default=0.0,
        min=-math.pi,
        max=math.pi,
        subtype='ANGLE',
        unit='ROTATION',
    )
    #: Kinds of spline among the end points that were extended, so that the
    #: settings that do not apply are greyed out. Set by execute(), read by
    #: draw().
    has_bezier: BoolProperty(default=True, options={'HIDDEN'})
    has_poly: BoolProperty(default=True, options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return context.mode == EDIT_MODE and has_active_curve(context)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "distance")

        column = layout.column()
        column.enabled = self.has_bezier
        column.prop(self, "mode")
        row = column.row()
        row.enabled = self.mode == 'MANUAL'
        row.prop(self, "curvature")

        row = layout.row()
        row.enabled = self.has_poly
        row.prop(self, "direction")

    # -- the end points to extend from ---------------------------------------

    def _targets(self, objs):
        """({object: {spline index: [at_end, ...]}}, points left alone).

        Every selected point that is the start or the end of an open Poly or
        Bezier spline of two points or more is an end point to extend. Any
        other selected point (one in the middle, one of a closed spline, one
        of a NURBS spline) is left alone and counted.
        """
        targets, ignored = {}, 0
        for obj in objs:
            for index, data in enumerate(sd.read_all(obj.data)):
                last = len(data.points) - 1
                extendable = (
                    data.kind in ('POLY', 'BEZIER') and not data.cyclic and last >= 1)
                for position, point in enumerate(data.points):
                    if not point.select:
                        continue
                    if extendable and position in (0, last):
                        targets.setdefault(obj, {}).setdefault(index, []).append(
                            position == last)
                    else:
                        ignored += 1
        if not targets:
            if ignored:
                raise Fail(
                    "none of the selected points is the end of an open Poly or Bezier "
                    "spline: Extend grows a curve from its end points")
            raise Fail("Select the end point of an open curve to extend from")
        return targets, ignored

    def _default_distance(self, context, targets, scales):
        """Distance of the first click: a share of the largest spline being
        extended, in the units of the scene, rounded to a round number."""
        size = 0.0
        for obj, splines in targets.items():
            datas = sd.read_all(obj.data)
            for index in splines:
                size = max(size, spline_size(datas[index]) * scales[obj])
        return nice_length(DEFAULT_SHARE * size) or unit_scale(context) * 0.1

    # -- work ----------------------------------------------------------------

    def _turn(self, data, tangent, centre, curvature, length):
        """(centre direction, curvature) of the arc to add. A Poly spline has
        no curvature to continue, so it is extended straight."""
        if data.kind != 'BEZIER':
            return None, 0.0
        if self.mode == 'AUTOMATIC':
            return centre, curvature
        sweep = abs(self.curvature)
        if sweep < 1e-9:
            return None, 0.0
        left = geo.normalized(geo.cross(bend_normal(data, tangent), tangent))
        if left is None:
            return None, 0.0
        return geo.mul(left, -1.0 if self.curvature > 0.0 else 1.0), sweep / length

    def _grow(self, data, at_end, length):
        """Snapshot of `data` with one of its ends extended.

        Everything is worked out as if the point to extend were the last one;
        a start point is handled on the reversed spline and reversed back, so
        the order of the points is kept.
        """
        working = data if at_end else sd.inverted(data)
        tangent, centre, curvature = frame_at_end(working)
        if working.kind != 'BEZIER':
            # The straight piece leaves at the Direction angle.
            tangent = aimed(tangent, bend_normal(working, tangent), self.direction)
        centre, curvature = self._turn(working, tangent, centre, curvature, length)
        grown = extended(working, tangent, centre, curvature, length)
        return grown if at_end else sd.inverted(grown)

    def execute(self, context):
        done = 0
        ignored = 0
        stretched = []
        with edit_scope(context) as objs:
            if not objs:
                self.report({'ERROR'}, "Extend needs a curve in Edit Mode")
                return {'CANCELLED'}
            try:
                targets, ignored = self._targets(objs)
                scales = {}
                for obj in targets:
                    scale, non_uniform = _average_scale(obj)
                    if scale is None:
                        raise Fail(f"'{obj.name}' has a degenerate transform (zero scale)")
                    scales[obj] = scale
                    if non_uniform:
                        stretched.append(obj.name)

                self.has_bezier = self.has_poly = False
                for obj, splines in targets.items():
                    datas = sd.read_all(obj.data)
                    for index in splines:
                        if datas[index].kind == 'BEZIER':
                            self.has_bezier = True
                        else:
                            self.has_poly = True

                if not self.properties.is_property_set("distance", ghost=False):
                    self.distance = self._default_distance(context, targets, scales)

                plans = {}
                for obj, splines in targets.items():
                    length = self.distance / scales[obj]
                    if length < 1e-9:
                        continue
                    datas = sd.read_all(obj.data)
                    for index, ends in splines.items():
                        data = datas[index]
                        # The end first, then the start: extending one end
                        # does not change the frame of the other.
                        for at_end in sorted(ends, reverse=True):
                            data = self._grow(data, at_end, length)
                            done += 1
                        datas[index] = data
                    plans[obj] = datas
            except Fail as exc:
                self.report({'ERROR'}, str(exc))
                return {'CANCELLED'}

            if not done:
                self.report({'INFO'}, "Distance is 0: nothing to extend")
                return {'CANCELLED'}
            for obj, datas in plans.items():
                sd.replace_splines(obj.data, datas)

        notes = []
        if ignored:
            notes.append(f"{ignored} selected point(s) are not end points, left alone")
        if stretched:
            notes.append(
                f"non-uniform scale in {', '.join(stretched)}: the length cannot be exact")
        message = f"Extended {done} end point(s)"
        if notes:
            message += " (" + "; ".join(notes) + ")"
        self.report({'WARNING'} if notes else {'INFO'}, message)
        return {'FINISHED'}


# -----------------------------------------------------------------------------

classes = (ETR_OT_curve_toolkit_extend,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
