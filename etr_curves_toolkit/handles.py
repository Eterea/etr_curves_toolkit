# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Handles to Lines and Handles to Axis

A construction aid: the handles of Bezier splines drawn as Poly lines.

  - Object Mode: every handle of every Bezier spline of the selected curves,
    in a new curve object per curve (`<name>_Handles`), with the transform of
    the curve and no bevel, next to it.
  - Edit Mode: only the handles of the selected points, as new splines of the
    same curve. A selected control point gives both of its handles; a handle
    picked on its own (its control point not selected) gives only the line
    from that handle to its point.

The two handles of a point make one spline (left handle, point, right
handle), not two. A handle of length zero is not drawn. Nothing is merged
with the curve.

Handles to Axis: every Bezier handle that points almost along an axis of the
curve object (its local X, Y or Z, within the Threshold angle of the F9
panel) is turned onto that axis. Its length is kept, and the control points
do not move.

  - Object Mode: every handle of the selected curves.
  - Edit Mode: the handles of the selected points. A selected control point
    (or both handles selected) takes both handles; a handle picked on its own
    takes only that handle.

Vector handles are left alone (they belong to straight segments). Two
Aligned or Auto handles that are still opposite after the change become
Aligned; otherwise both become Free, so Blender does not move the handle
that was not picked.
"""

import math

import bpy
from bpy.props import FloatProperty

from . import geometry as geo
from . import spline_data as sd
from .context_utils import (
    EDIT_MODE,
    edit_scope,
    has_active_curve,
    link_like,
    selected_curves,
)

#: Shorter handles (relative to the size of the curve) count as zero.
ZERO = 1e-9


def handle_lines(data, only_selected):
    """Poly SplineData of the handles of a Bezier spline snapshot."""
    if data.kind != 'BEZIER':
        return []
    lines = []
    for p in data.points:
        if only_selected and not p.select:
            left, right = p.select_left, p.select_right
        else:
            left = right = True
        if only_selected and not (p.select or p.select_left or p.select_right):
            continue
        coords = []
        if left and geo.distance(p.hl, p.co) > ZERO:
            coords.append(p.hl)
        coords.append(p.co)
        if right and geo.distance(p.hr, p.co) > ZERO:
            coords.append(p.hr)
        if len(coords) < 2:
            continue
        points = [sd.PointData(co=tuple(c), select=True) for c in coords]
        lines.append(sd.SplineData('POLY', points, False, {}))
    return lines


def _deselect_all(curve):
    for spline in curve.splines:
        if spline.type == 'BEZIER':
            for bp in spline.bezier_points:
                bp.select_control_point = bp.select_left_handle = bp.select_right_handle = False
        else:
            for p in spline.points:
                p.select = False


class ETR_OT_curve_toolkit_handles_to_lines(bpy.types.Operator):
    """Draw the handles of Bezier curves as Poly lines, a construction aid. Object Mode: all of them, in a new object. Edit Mode: those of the selected points, in the same curve"""
    bl_idname = "etr.curve_toolkit_handles_to_lines"
    bl_label = "Handles to Lines"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode == 'OBJECT' and selected_curves(context):
            return True
        if context.mode == EDIT_MODE and has_active_curve(context):
            return True
        cls.poll_message_set("Select Bezier curves (Object Mode) or their points (Edit Mode)")
        return False

    def execute(self, context):
        if context.mode == EDIT_MODE:
            return self._edit(context)
        return self._object(context)

    def _object(self, context):
        created = []
        for obj in selected_curves(context):
            lines = []
            for data in sd.read_all(obj.data):
                lines += handle_lines(data, only_selected=False)
            if not lines:
                continue
            curve = bpy.data.curves.new(f"{obj.name}_Handles", 'CURVE')
            curve.dimensions = '3D'
            sd.replace_splines(curve, lines)
            new_obj = bpy.data.objects.new(f"{obj.name}_Handles", curve)
            new_obj.matrix_basis = obj.matrix_basis.copy()
            new_obj.parent = obj.parent
            new_obj.matrix_parent_inverse = obj.matrix_parent_inverse.copy()
            link_like(new_obj, obj, context)
            created.append(new_obj)
        if not created:
            self.report({'WARNING'}, "Handles to Lines: no Bezier handles to draw")
            return {'CANCELLED'}
        for obj in context.selected_objects:
            obj.select_set(False)
        for obj in created:
            obj.select_set(True)
        context.view_layer.objects.active = created[-1]
        self.report({'INFO'}, f"Handles to Lines: {len(created)} object(s)")
        return {'FINISHED'}

    def _edit(self, context):
        count = 0
        with edit_scope(context) as objs:
            per_obj = []
            for obj in objs:
                lines = []
                for data in sd.read_all(obj.data):
                    lines += handle_lines(data, only_selected=True)
                per_obj.append((obj, lines))
                count += len(lines)
            if not count:
                self.report({'WARNING'}, "Handles to Lines: select Bezier points or handles "
                                         "(handles of length zero are not drawn)")
                return {'CANCELLED'}
            for obj, lines in per_obj:
                _deselect_all(obj.data)
                for line in lines:
                    sd.write_spline(obj.data, line)
        self.report({'INFO'}, f"Handles to Lines: {count} line(s)")
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Handles to Axis
# -----------------------------------------------------------------------------

AXES = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
        (-1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, -1.0))

#: Two handles count as opposite (still aligned) within this cosine.
OPPOSITE = 1.0 - 1e-9


def _angle(a, b):
    la, lb = geo.length(a), geo.length(b)
    return math.acos(max(-1.0, min(1.0, geo.dot(a, b) / (la * lb))))


def snapped_handle(co, handle, threshold):
    """Where a handle goes when it points within `threshold` (radians) of a
    local axis: on that axis, with the same length. None when it stays."""
    v = geo.sub(handle, co)
    length = geo.length(v)
    if length <= ZERO:
        return None
    best = None
    for axis in AXES:
        a = _angle(v, axis)
        if a <= threshold + 1e-12 and (best is None or a < best[0]):
            best = (a, axis)
    if best is None:
        return None
    new = geo.add(co, geo.mul(best[1], length))
    if geo.distance(new, handle) <= 1e-9 * max(length, 1.0):
        return None
    return new


def _sides(bp, only_selected):
    """Which handles of a point the tool may turn: (left, right)."""
    if not only_selected or bp.select_control_point:
        return True, True
    return bp.select_left_handle, bp.select_right_handle


def axis_handles(spline, threshold, only_selected):
    """Turn the handles of a Bezier spline onto the axes. Returns how many
    handles moved."""
    if spline.type != 'BEZIER':
        return 0
    moved = 0
    for bp in spline.bezier_points:
        left, right = _sides(bp, only_selected)
        co = tuple(bp.co)
        hl, hr = tuple(bp.handle_left), tuple(bp.handle_right)
        tl, tr = bp.handle_left_type, bp.handle_right_type
        new_l = snapped_handle(co, hl, threshold) if left and tl != 'VECTOR' else None
        new_r = snapped_handle(co, hr, threshold) if right and tr != 'VECTOR' else None
        if new_l is None and new_r is None:
            continue
        final_l = new_l or hl
        final_r = new_r or hr
        types = {tl, tr}
        if types <= {'ALIGNED', 'AUTO'}:
            dl, dr = geo.normalized(geo.sub(final_l, co)), geo.normalized(geo.sub(final_r, co))
            opposite = dl is not None and dr is not None and geo.dot(dl, dr) <= -OPPOSITE
            tl = tr = 'ALIGNED' if opposite else 'FREE'
        else:
            tl = 'FREE' if tl in ('ALIGNED', 'AUTO') else tl
            tr = 'FREE' if tr in ('ALIGNED', 'AUTO') else tr
        bp.handle_left_type = bp.handle_right_type = 'FREE'
        bp.handle_left = final_l
        bp.handle_right = final_r
        bp.handle_left_type = tl
        bp.handle_right_type = tr
        moved += (new_l is not None) + (new_r is not None)
    return moved


class ETR_OT_curve_toolkit_handles_to_axis(bpy.types.Operator):
    """Turn the Bezier handles that point almost along an axis (local X, Y or Z, within the Threshold) onto that axis, keeping their length. Object Mode: all the handles of the selected curves. Edit Mode: those of the selected points, or a handle picked on its own"""
    bl_idname = "etr.curve_toolkit_handles_to_axis"
    bl_label = "Handles to Axis"
    bl_options = {'REGISTER', 'UNDO'}

    threshold: FloatProperty(
        name="Threshold",
        description="Largest angle between a handle and an axis (on either side) for the "
                    "handle to be turned onto the axis",
        default=math.radians(5.0),
        min=0.0,
        soft_max=math.radians(30.0),
        max=math.radians(45.0),
        subtype='ANGLE',
    )

    @classmethod
    def poll(cls, context):
        if context.mode == 'OBJECT' and selected_curves(context):
            return True
        if context.mode == EDIT_MODE and has_active_curve(context):
            return True
        cls.poll_message_set("Select Bezier curves (Object Mode) or their points (Edit Mode)")
        return False

    def execute(self, context):
        edit = context.mode == EDIT_MODE
        moved = 0
        if edit:
            with edit_scope(context) as objs:
                for curve in {o.data for o in objs}:
                    for spline in curve.splines:
                        moved += axis_handles(spline, self.threshold, True)
        else:
            for curve in {o.data for o in selected_curves(context)}:
                for spline in curve.splines:
                    moved += axis_handles(spline, self.threshold, False)
        if not moved:
            self.report({'WARNING'}, "Handles to Axis: no handle within the Threshold of an "
                                     "axis" + (" among the selected points" if edit else ""))
            return {'FINISHED'}
        self.report({'INFO'}, f"Handles to Axis: {moved} handle(s) on the axes")
        return {'FINISHED'}


classes = (ETR_OT_curve_toolkit_handles_to_lines, ETR_OT_curve_toolkit_handles_to_axis)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
