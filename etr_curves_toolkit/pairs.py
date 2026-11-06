# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Snap Pair and Swap Pair (Edit Mode)

The two neighbours of Merge Pair. Both take exactly two selected points and
only move them: nothing is welded, so any two points will do, whatever their
place in their splines (start, middle or end, of open or closed splines), of
any curve type, in the same curve or in two different ones (multi-object
editing). Both also work on two selected vertices of a mesh, or of two.

  - Snap Pair  the two points go to the same place: their midpoint, point A
               or point B (the same choices as Merge Pair), and stay two.
  - Swap Pair  point A goes where point B was, and point B where A was.

Point A is the one that comes first: the lower index in the same spline (or
mesh), or the one in the first spline; across objects, the one in the object
whose name comes first.

On a Bezier point the handles travel with it, keeping their length and
direction, the way Merge Pair moves them.
"""

import bmesh
import bpy
from bpy.props import EnumProperty
from mathutils import Vector

from . import spline_data as sd
from .context_utils import EDIT_MODE, edit_scope, is_curve, world_matrix
from .merge import PLACEMENTS

EDIT_MESH = 'EDIT_MESH'


class Fail(Exception):
    """A message for the user; nothing has been changed."""


def _poll(cls, context):
    if context.mode == EDIT_MESH:
        return True
    if context.mode == EDIT_MODE and is_curve(context.active_object):
        return True
    cls.poll_message_set("Works in the Edit Mode of a curve (control points) or of a "
                         "mesh (vertices)")
    return False


def _inverse(obj):
    try:
        return world_matrix(obj).inverted()
    except ValueError:
        raise Fail(f"'{obj.name}' has a degenerate transform (zero scale)")


def _check_two(found, what, tool):
    if len(found) != 2:
        raise Fail(f"{tool} needs exactly two selected {what} ({len(found)} selected)")


# -----------------------------------------------------------------------------
# Curves
# -----------------------------------------------------------------------------

def _curve_pair(objs, tool):
    """The two selected control points, A first:
    [(obj, snapshots, spline index, point index, world co)]."""
    found = []
    for obj in sorted(objs, key=lambda o: o.name):
        datas = sd.read_all(obj.data)
        mw = world_matrix(obj)
        for i, data in enumerate(datas):
            for k, p in enumerate(data.points):
                if p.select:
                    found.append((obj, datas, i, k, mw @ Vector(p.co)))
    _check_two(found, "control points", tool)
    return found


def _move_curve_points(moves):
    """moves: [(pair entry, world target)]. Rewrites the curves involved."""
    touched = {}
    for (obj, datas, i, k, _), target in moves:
        local = tuple(_inverse(obj) @ target)
        datas[i].points[k] = sd.moved_to(datas[i].points[k], local)
        touched[obj.name] = (obj, datas)
    for obj, datas in touched.values():
        sd.replace_splines(obj.data, datas)


# -----------------------------------------------------------------------------
# Meshes
# -----------------------------------------------------------------------------

def _mesh_pair(context, tool):
    """The two selected vertices, A first: [(obj, bmesh, vertex, world co)]."""
    found = []
    meshes = [o for o in context.objects_in_mode_unique_data if o.type == 'MESH']
    for obj in sorted(meshes, key=lambda o: o.name):
        bm = bmesh.from_edit_mesh(obj.data)
        mw = world_matrix(obj)
        found += [(obj, bm, v, mw @ v.co) for v in bm.verts if v.select]
    _check_two(found, "vertices", tool)
    return found


def _move_mesh_points(moves):
    touched = {}
    for (obj, bm, v, _), target in moves:
        v.co = _inverse(obj) @ target
        touched[obj.name] = obj
    for obj in touched.values():
        bmesh.update_edit_mesh(obj.data)


# -----------------------------------------------------------------------------
# Operators
# -----------------------------------------------------------------------------

class _PairOperator:
    """What Snap Pair and Swap Pair share: find the two points, work out where
    each goes (self.targets), and move them."""

    tool = ""

    poll = classmethod(_poll)

    def targets(self, a, b):
        raise NotImplementedError

    def execute(self, context):
        try:
            if context.mode == EDIT_MESH:
                pair = _mesh_pair(context, self.tool)
                ta, tb = self.targets(pair[0][-1], pair[1][-1])
                _move_mesh_points([(pair[0], ta), (pair[1], tb)])
            else:
                with edit_scope(context) as objs:
                    pair = _curve_pair(objs, self.tool)
                    ta, tb = self.targets(pair[0][-1], pair[1][-1])
                    _move_curve_points([(pair[0], ta), (pair[1], tb)])
        except Fail as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        self.report({'INFO'}, self.done)
        return {'FINISHED'}


class ETR_OT_curve_toolkit_snap_pair(_PairOperator, bpy.types.Operator):
    """Put two selected points at the same place without welding them: at their center, at point A or at point B. Any point of any spline, any curve type, or two mesh vertices. Edit Mode"""
    bl_idname = "etr.curve_toolkit_snap_pair"
    bl_label = "Snap Pair"
    bl_options = {'REGISTER', 'UNDO'}

    tool = "Snap Pair"
    done = "Snap Pair: the two points are now at the same place"

    at: EnumProperty(
        name="Snap",
        description="Where the two points go",
        items=PLACEMENTS,
        default='CENTER',
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "at")

    def targets(self, a, b):
        if self.at == 'A':
            target = a.copy()
        elif self.at == 'B':
            target = b.copy()
        else:
            target = (a + b) * 0.5
        return target, target.copy()


class ETR_OT_curve_toolkit_swap_pair(_PairOperator, bpy.types.Operator):
    """Swap the places of two selected points: A goes where B was and B where A was. Any point of any spline, any curve type, or two mesh vertices. Edit Mode"""
    bl_idname = "etr.curve_toolkit_swap_pair"
    bl_label = "Swap Pair"
    bl_options = {'REGISTER', 'UNDO'}

    tool = "Swap Pair"
    done = "Swap Pair: the two points have swapped places"

    def targets(self, a, b):
        return b.copy(), a.copy()


classes = (
    ETR_OT_curve_toolkit_snap_pair,
    ETR_OT_curve_toolkit_swap_pair,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
