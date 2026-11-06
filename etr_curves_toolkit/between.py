# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Points in Between

With two points selected, adds Count new points evenly spaced on the straight
line between them, in 3D space: one point at the exact middle with Count 1,
two at 1/3 and 2/3 with Count 2, and so on. Useful to find centers and to lay
out divisions to snap to.

  - Edit Mode of a curve: two selected control points (handles do not count),
    in one spline or in different ones. Each new point is a stray point: a
    Poly spline of its own with a single point, added to the active curve
    (extruding it makes straight segments, with no handles to tidy up).
  - Edit Mode of a mesh: two selected vertices. The new points are loose
    vertices of the active mesh.

Either way the Edit Mode is kept, and only the new points end up selected.
The points may belong to different objects in multi-object editing; the new
ones always go into the active object, at the right place in the world.
"""

import bmesh
import bpy
from bpy.props import IntProperty
from mathutils import Vector

from . import geometry as geo
from . import spline_data as sd
from .context_utils import EDIT_MODE, edit_scope, is_curve, world_matrix

EDIT_MESH = 'EDIT_MESH'


class Fail(Exception):
    """A message for the user; nothing has been changed."""


def in_between(a, b, count):
    """`count` points evenly spaced between a and b (both excluded)."""
    return [geo.lerp(a, b, i / (count + 1)) for i in range(1, count + 1)]


def _selected_curve_points(objs):
    points = []
    for obj in objs:
        mw = world_matrix(obj)
        for spline in obj.data.splines:
            if spline.type == 'BEZIER':
                points += [mw @ bp.co for bp in spline.bezier_points if bp.select_control_point]
            else:
                points += [mw @ p.co.xyz for p in spline.points if p.select]
    return points


def _stray_point(co):
    """A Poly spline of its own with a single point."""
    return sd.SplineData('POLY', [sd.PointData(co=co, select=True)], False, {})


def _deselect_all(curve):
    for spline in curve.splines:
        if spline.type == 'BEZIER':
            for bp in spline.bezier_points:
                bp.select_control_point = False
                bp.select_left_handle = False
                bp.select_right_handle = False
        else:
            for p in spline.points:
                p.select = False


class ETR_OT_curve_toolkit_points_in_between(bpy.types.Operator):
    """Add evenly spaced points on the straight line between 2 selected points: stray control points in a curve, loose vertices in a mesh. Edit Mode"""
    bl_idname = "etr.curve_toolkit_points_in_between"
    bl_label = "Points in Between"
    bl_options = {'REGISTER', 'UNDO'}

    count: IntProperty(
        name="Count",
        description="Number of points added between the two selected ones, evenly "
                    "spaced: 1 puts one at the middle, 2 at 1/3 and 2/3, and so on",
        default=1,
        min=1,
        soft_max=100,
        max=10000,
    )

    @classmethod
    def poll(cls, context):
        if context.mode == EDIT_MESH:
            return True
        if context.mode == EDIT_MODE and is_curve(context.active_object):
            return True
        cls.poll_message_set("Works in the Edit Mode of a curve (control points) or of a "
                             "mesh (vertices)")
        return False

    def execute(self, context):
        try:
            if context.mode == EDIT_MESH:
                added = self._in_mesh(context)
            else:
                added = self._in_curve(context)
        except Fail as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, f"Added {added} point(s)")
        return {'FINISHED'}

    def _check(self, points, what):
        if len(points) != 2:
            raise Fail(f"Points in Between: select exactly 2 {what} ({len(points)} selected)")
        if (points[0] - points[1]).length < 1e-9:
            raise Fail("Points in Between: the two points are at the same place")

    def _in_curve(self, context):
        obj = context.active_object
        try:
            to_local = world_matrix(obj).inverted()
        except ValueError:
            raise Fail(f"'{obj.name}' has a degenerate transform (zero scale)")
        with edit_scope(context) as objs:
            points = _selected_curve_points(objs)
            self._check(points, "control points")
            new = in_between(tuple(points[0]), tuple(points[1]), self.count)
            for o in objs:
                _deselect_all(o.data)
            spline = None
            for co in new:
                spline = sd.write_spline(obj.data, _stray_point(tuple(to_local @ Vector(co))))
            if spline is not None:
                obj.data.splines.active = spline
        return len(new)

    def _in_mesh(self, context):
        obj = context.active_object
        try:
            to_local = world_matrix(obj).inverted()
        except ValueError:
            raise Fail(f"'{obj.name}' has a degenerate transform (zero scale)")
        meshes = [o for o in context.objects_in_mode_unique_data if o.type == 'MESH']
        points = []
        for o in meshes:
            bm = bmesh.from_edit_mesh(o.data)
            mw = world_matrix(o)
            points += [mw @ v.co for v in bm.verts if v.select]
        self._check(points, "vertices")
        new = in_between(tuple(points[0]), tuple(points[1]), self.count)

        for o in meshes:
            bm = bmesh.from_edit_mesh(o.data)
            for elems in (bm.verts, bm.edges, bm.faces):
                for e in elems:
                    e.select = False
            bm.select_history.clear()
            if o != obj:
                bmesh.update_edit_mesh(o.data, loop_triangles=False, destructive=False)
        bm = bmesh.from_edit_mesh(obj.data)
        for co in new:
            v = bm.verts.new(to_local @ Vector(co))
            v.select = True
        bm.select_flush_mode()
        bmesh.update_edit_mesh(obj.data)
        return len(new)


classes = (ETR_OT_curve_toolkit_points_in_between,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
