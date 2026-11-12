# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Perpendicular from Point

Edit Mode of a curve: for every selected control point of a Poly or Bezier
spline, a new straight segment through the point, perpendicular to the
curve. It is a Poly spline of its own (not connected to the curve), whatever
the type of the curve.

  - A smooth point (aligned handles, or a Poly point between two segments in
    line) gets the perpendicular to the curve. The segment goes to the left
    of the direction of the curve, as seen from the view.
  - A corner gets the bisector of the corner instead (of its two handles, on
    a Bezier spline; of its two segments, on a Poly one). The segment goes
    outwards, away from the inside of the corner.
  - An end point of an open spline gets the perpendicular to its only side.

Options (F9):
  - Length (positive): it starts at a quarter of the length of the spline of
    the first selected point.
  - Center (0 to 1, 0.5 by default): where the segment sits on the curve. At
    0 it starts at the point (its IN end on the curve) and goes the way
    described above; at 1 it ends at the point (its OUT end on the curve), on
    the other side; at 0.5 it is centered on the curve.

The segment stays in the plane of the view, as the Circles from Points do:
Top/Bottom XY, Front/Back XZ, Right/Left YZ, a free perspective and the
camera view as Top (the View can be changed in the F9 panel).
"""

import bpy
from bpy.props import EnumProperty, FloatProperty, FloatVectorProperty
from mathutils import Vector

from . import geometry as geo
from . import spline_data as sd
from .circles import VIEWS, _VIEW_ITEMS, read_view
from .context_utils import EDIT_MODE, edit_scope, has_active_curve, world_matrix

#: Two directions this close (as a cosine) to opposite are "in line".
SMOOTH = 1.0 - 1e-6


class Fail(Exception):
    """A message for the user; nothing has been changed."""


def _unit(v):
    return geo.normalized(v, 1e-12)


def side_directions(data, i, mw):
    """World directions from point i towards its two sides (handles, or
    neighbours), the missing ones as None."""
    pts = data.points
    n = len(pts)
    co = mw @ Vector(pts[i].co)
    prev = i - 1 if i > 0 else (n - 1 if data.cyclic and n > 1 else None)
    nxt = i + 1 if i < n - 1 else (0 if data.cyclic and n > 1 else None)

    def towards(index, handle):
        if index is None:
            return None
        if data.kind == 'BEZIER' and handle is not None:
            d = _unit(tuple(mw @ Vector(handle) - co))
            if d is not None:
                return d
        return _unit(tuple(mw @ Vector(pts[index].co) - co))

    if data.kind == 'BEZIER':
        return towards(prev, pts[i].hl), towards(nxt, pts[i].hr), tuple(co)
    return towards(prev, None), towards(nxt, None), tuple(co)


def in_plane(v, normal):
    return _unit(geo.sub(v, geo.mul(normal, geo.dot(v, normal))))


def direction(back, ahead, normal):
    """Unit direction of the perpendicular (or bisector) at a point whose two
    sides go `back` and `ahead` (either may be None), in the plane of
    `normal` (towards the viewer). None when it cannot be told."""
    if back is not None and ahead is not None and geo.dot(back, ahead) > -SMOOTH:
        # A corner: the bisector, outwards.
        inside = in_plane(geo.add(back, ahead), normal)
        if inside is not None:
            return geo.mul(inside, -1.0)
    # Smooth, or an end: the perpendicular, to the left of the direction of
    # travel as seen from the viewer.
    if ahead is not None:
        travel = ahead
    elif back is not None:
        travel = geo.mul(back, -1.0)
    else:
        return None
    travel = in_plane(travel, normal)
    if travel is None:
        return None
    return geo.cross(normal, travel)


def spline_length(data, mw):
    pts = [mw @ Vector(co) for co in sd.flatten(data, steps=12)]
    return sum((b - a).length for a, b in zip(pts, pts[1:]))


def _deselect_all(curve):
    for spline in curve.splines:
        if spline.type == 'BEZIER':
            for bp in spline.bezier_points:
                bp.select_control_point = bp.select_left_handle = bp.select_right_handle = False
        else:
            for p in spline.points:
                p.select = False


def straight(a, b):
    """A straight 2-point Poly spline from a to b."""
    return sd.SplineData('POLY', [sd.PointData(co=a, select=True),
                                  sd.PointData(co=b, select=True)], False, {})


class ETR_OT_curve_toolkit_perpendicular(bpy.types.Operator):
    """Draw a straight segment at every selected point, perpendicular to the curve (or along the bisector of a corner), in the plane of the view. Length and Center (where it sits on the curve) in the F9 panel"""
    bl_idname = "etr.curve_toolkit_perpendicular"
    bl_label = "Perpendicular from Point"
    bl_options = {'REGISTER', 'UNDO'}

    length: FloatProperty(
        name="Length",
        description="Length of the segment. It starts at a quarter of the length of the "
                    "spline",
        default=1.0,
        min=0.0,
        subtype='DISTANCE',
        unit='LENGTH',
        options={'SKIP_SAVE'},
    )
    center: FloatProperty(
        name="Center",
        description="Where the segment sits on the curve: 0 starts at the curve (its IN "
                    "end is on it), 1 ends at it (its OUT end is on it, so the segment is "
                    "on the other side), 0.5 is centered on the curve",
        default=0.5,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
        options={'SKIP_SAVE'},
    )
    view: EnumProperty(
        name="View",
        description="Plane the segment is drawn on, as seen from this view. It comes from the "
                    "3D Viewport when the button is clicked: a free perspective and the camera "
                    "view count as Top",
        items=_VIEW_ITEMS,
        default='TOP',
        options={'SKIP_SAVE'},
    )
    view_normal: FloatVectorProperty(size=3, default=(0.0, 0.0, 1.0),
                                     options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        if context.mode == EDIT_MODE and has_active_curve(context):
            return True
        cls.poll_message_set("Works in the Edit Mode of a curve, with control points selected")
        return False

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "length")
        layout.prop(self, "center")
        layout.separator()
        layout.prop(self, "view")

    def execute(self, context):
        props = self.properties
        if not props.is_property_set("view_normal"):
            name, normal, _ = read_view(context)
            self.view_normal = normal
            if not props.is_property_set("view"):
                self.view = name
        normal = VIEWS[self.view][0]
        try:
            return self._run(context, normal)
        except Fail as error:
            self.report({'ERROR'}, f"Perpendicular from Point: {error}")
            return {'CANCELLED'}

    def _run(self, context, normal):
        made = skipped = 0
        with edit_scope(context) as objs:
            jobs = []          # (obj, kind, start, unit direction), world space
            first_length = None
            for obj in objs:
                mw = world_matrix(obj)
                for data in sd.read_all(obj.data):
                    if data.kind == 'NURBS':
                        continue
                    for i, p in enumerate(data.points):
                        if not p.select:
                            continue
                        back, ahead, co = side_directions(data, i, mw)
                        d = direction(back, ahead, normal)
                        if d is None:
                            skipped += 1
                            continue
                        jobs.append((obj, co, d))
                        if first_length is None:
                            first_length = spline_length(data, mw)
            if not jobs:
                raise Fail("select one or more control points of a Poly or Bezier curve "
                           "(not seen edge-on from the view)")
            if not props_set(self, "length"):
                self.length = (first_length or 4.0) / 4.0
            if self.length < 1e-9:
                raise Fail("the Length cannot be 0")
            for o in objs:
                _deselect_all(o.data)
            for obj, co, d in jobs:
                # From the curve by default (Center 0), across it at 0.5, and
                # ending on it at 1.
                start = geo.add(co, geo.mul(d, -self.center * self.length))
                end = geo.add(co, geo.mul(d, (1.0 - self.center) * self.length))
                to_local = world_matrix(obj).inverted()
                a = tuple(to_local @ Vector(start))
                b = tuple(to_local @ Vector(end))
                sd.write_spline(obj.data, straight(a, b))
                made += 1
        if skipped:
            self.report({'WARNING'}, f"{made} segment(s); {skipped} point(s) skipped "
                                     "(their curve is seen edge-on from the view)")
        return {'FINISHED'}


def props_set(op, name):
    return op.properties.is_property_set(name)


classes = (ETR_OT_curve_toolkit_perpendicular,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
