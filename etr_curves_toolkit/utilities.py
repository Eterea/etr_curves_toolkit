# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Utilities

Small tools that work on any curve (Poly, Bezier, NURBS; 2D or 3D) unless
noted:

  - Set First Point   (Edit Mode)   selected point becomes point 0.
  - Invert Direction  (Object/Edit) reverse the order of the points.
  - Split at Control Points (Object/Edit) Object Mode: every segment goes to
                                    its own object. Edit Mode: the splines are
                                    cut at the selected points, in their curve.
                                    Poly and Bezier only. Its button is drawn
                                    with the Splits, and it shares their
                                    Backup / Sources / Results options.
  - Separate All Selected (Edit)    every selected spline goes to a new curve
                                    object of its own, leaving the curve it
                                    was in. Ends in Object Mode.
  - Join & Merge      (Object)      join curves and weld coincident end points
                                    into as few splines as possible.
                                    Poly and Bezier only.
  - Remove Doubles    (Object/Edit) merge consecutive points that overlap.
  - Remove Strays     (Object/Edit) delete the splines with a single point and
                                    those shorter than the Threshold.
  - Select Strays     (Edit)        select those stray splines, and only those.
  - Select by Type    (Edit)        select every Poly, Bezier or NURBS spline
                                    (stray points left out), or the strays.
  - Set Dimensions    (Object/Edit) 2D or 3D for every selected curve.
  - Set Resolution    (Object/Edit) the same Resolution U for many splines.
  - Change Origin     (Object/Edit) origin to curve start / midpoint / end /
                                    bounds center. Edit Mode: of the selected
                                    spline (Mid: of the segment between two
                                    consecutive selected points).
  - Origin To         (Object/Edit) origin to the world origin or to the 3D
                                    Cursor (To World Origin, To 3D Cursor).

All shapes are preserved: Blender cannot reorder or delete spline points in
place, so each tool rebuilds the affected splines from snapshots
(see spline_data.py).
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty
from mathutils import Vector

from . import geometry as geo
from . import spline_data as sd
from .context_utils import (
    EDIT_MODE,
    backup_splines,
    curves_in_edit_mode,
    edit_scope,
    finish_sources_and_results,
    has_active_curve,
    link_like,
    new_curve_object,
    selected_curves,
    world_distance,
    world_matrix,
    write_edit_result,
)


def _poll_object_or_edit(cls, context):
    return has_active_curve(context) and context.mode in {'OBJECT', EDIT_MODE}


def _poll_object(cls, context):
    return context.mode == 'OBJECT' and bool(selected_curves(context))


# -----------------------------------------------------------------------------
# Set First Point
# -----------------------------------------------------------------------------

class ETR_OT_curve_toolkit_set_first_point(bpy.types.Operator):
    """Make the selected control point the first point of its spline (index 0), keeping the shape. On an open curve only an end point can be selected, and the result is an inverted direction"""
    bl_idname = "etr.curve_toolkit_set_first_point"
    bl_label = "Set First Point"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == EDIT_MODE and has_active_curve(context)

    def execute(self, context):
        changed = skipped = 0
        with edit_scope(context) as objs:
            for obj in objs:
                datas = sd.read_all(obj.data)
                dirty = False
                for i, d in enumerate(datas):
                    selected = [k for k, p in enumerate(d.points) if p.select]
                    if not selected:
                        continue
                    if len(selected) > 1:
                        skipped += 1
                        continue
                    k = selected[0]
                    if d.cyclic:
                        if k:
                            datas[i] = sd.rotated(d, k)
                            dirty = True
                            changed += 1
                    elif k == 0:
                        pass  # already the first point
                    elif k == len(d.points) - 1:
                        datas[i] = sd.inverted(d)
                        dirty = True
                        changed += 1
                    else:
                        skipped += 1
                if dirty:
                    sd.replace_splines(obj.data, datas)
        if skipped:
            self.report(
                {'WARNING'},
                f"{skipped} spline(s) skipped: select exactly one point per spline "
                "(on open curves it must be an end point)",
            )
        if not changed and not skipped:
            self.report({'INFO'}, "Nothing to change")
            return {'CANCELLED'}
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Invert Direction
# -----------------------------------------------------------------------------

class ETR_OT_curve_toolkit_invert_direction(bpy.types.Operator):
    """Invert the direction of the curve, keeping its shape. On a closed spline point 0 stays point 0"""
    bl_idname = "etr.curve_toolkit_invert_direction"
    bl_label = "Invert Direction"
    bl_options = {'REGISTER', 'UNDO'}

    poll = classmethod(_poll_object_or_edit)

    def execute(self, context):
        in_edit = context.mode == EDIT_MODE
        count = 0

        def process(objs):
            nonlocal count
            for obj in objs:
                datas = sd.read_all(obj.data)
                dirty = False
                for i, d in enumerate(datas):
                    if in_edit and not any(p.select for p in d.points):
                        continue
                    datas[i] = sd.inverted(d)
                    dirty = True
                    count += 1
                if dirty:
                    sd.replace_splines(obj.data, datas)

        if in_edit:
            with edit_scope(context) as objs:
                process(objs)
        else:
            process(selected_curves(context))

        if not count:
            self.report({'WARNING'}, "No splines to invert (select some points in Edit Mode)")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Inverted {count} spline(s)")
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Split at Control Points
# -----------------------------------------------------------------------------

def _piece_indices(n, cyclic, cuts):
    """Index ranges (start, stop) of the pieces of a spline cut at `cuts`.

    `stop` may exceed n - 1 on a closed spline (the piece wraps around).
    """
    cuts = sorted(set(cuts))
    if cyclic:
        if not cuts:
            return []
        pieces = []
        for j, c in enumerate(cuts):
            nxt = cuts[j + 1] if j + 1 < len(cuts) else cuts[0] + n
            pieces.append((c, nxt))
        return pieces
    bounds = sorted(set(cuts) | {0, n - 1})
    return [(a, b) for a, b in zip(bounds, bounds[1:])]


def _make_piece(data, start, stop):
    """Open spline with the points start..stop (inclusive, wrapping)."""
    n = len(data.points)
    pts = [data.points[i % n] for i in range(start, stop + 1)]
    out = sd.SplineData(data.kind, [sd.replace(p) for p in pts], False, dict(data.settings))
    if data.kind == 'BEZIER':
        for p in (out.points[0], out.points[-1]):
            # An end point must keep both handles where they are. Vector
            # handles follow the neighbour, which is the same point as before.
            if not (p.hlt == 'VECTOR' and p.hrt == 'VECTOR'):
                p.hlt = p.hrt = 'FREE'
    return out


class ETR_OT_curve_toolkit_split_at_points(bpy.types.Operator):
    """Cut the curve at its control points. Object Mode: every segment becomes a new object and the original is kept, hidden. Edit Mode: the splines are cut at the selected points, in the same curve (a backup only with Backup Splines in Edit Mode). Poly and Bezier only"""
    bl_idname = "etr.curve_toolkit_split_at_points"
    bl_label = "Split at Control Points"
    bl_options = {'REGISTER', 'UNDO'}

    poll = classmethod(_poll_object_or_edit)

    def execute(self, context):
        in_edit = context.mode == EDIT_MODE
        targets = curves_in_edit_mode(context) if in_edit else selected_curves(context)
        for obj in targets:
            if any(s.type == 'NURBS' for s in obj.data.splines):
                self.report({'ERROR'}, f"'{obj.name}' has NURBS splines: Split at Control Points works only with Poly and Bezier curves")
                return {'CANCELLED'}
        if in_edit:
            return self._edit(context)
        return self._object(context, targets)

    def _object(self, context, objs):
        active = context.active_object
        created = []
        for obj in objs:
            pieces = []
            for d in sd.read_all(obj.data):
                n = len(d.points)
                for a, b in _piece_indices(n, d.cyclic, list(range(n))):
                    if b > a:
                        pieces.append(_make_piece(d, a, b))
            if pieces:
                created.append((obj, [new_curve_object(context, obj, [piece], "Split",
                                                       numbered=True) for piece in pieces]))
        if not created:
            self.report({'WARNING'}, "Nothing to split")
            return {'CANCELLED'}
        sources = [obj for obj, _ in created]
        results = [(new_obj, obj) for obj, new_objs in created for new_obj in new_objs]
        anchor = active if active in sources else sources[0]
        finish_sources_and_results(context, sources, results, anchor)
        self.report({'INFO'}, f"Created {len(results)} segment(s)")
        return {'FINISHED'}

    def _edit(self, context):
        """The splines with selected control points are cut there, in their
        own curve; the pieces are left selected and the Edit Mode is kept."""
        count = 0
        with edit_scope(context) as objs:
            for obj in objs:
                datas = sd.read_all(obj.data)
                changed, pieces = [], []
                for i, d in enumerate(datas):
                    cuts = [k for k, p in enumerate(d.points) if p.select]
                    if not cuts or len(d.points) < 2:
                        continue
                    if not d.cyclic and all(k in (0, len(d.points) - 1) for k in cuts):
                        continue          # only at its ends: nothing to cut
                    parts = [_make_piece(d, a, b)
                             for a, b in _piece_indices(len(d.points), d.cyclic, cuts)
                             if b > a]
                    if parts:
                        changed.append(i)
                        pieces += parts
                if not changed:
                    continue
                backup_splines(context, obj, [datas[i] for i in changed])
                write_edit_result(obj, datas, changed, pieces)
                count += len(pieces)
        if not count:
            self.report({'WARNING'}, "Nothing to split: select the control points to cut at")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Created {count} segment(s)")
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Join & Merge
# -----------------------------------------------------------------------------

def merge_chains(datas, dist, threshold, allowed=None, at_center=False):
    """Weld the end points of open splines that lie within `threshold`.

    datas:      list of SplineData.
    dist:       function(co_a, co_b) -> distance in the units of `threshold`.
    allowed:    optional function(data, 'start' | 'end') -> bool, to leave some
                end points out of the welding (Merge by Distance uses it to
                weld only the selected ones). The selection flags travel with
                the points, so it keeps working on the splines welded along the
                way.
    at_center:  place every weld halfway between the two points it replaces,
                instead of leaving it where the first one was. Join & Merge
                welds points that are meant to be the same one already, so it
                keeps them put; Merge by Distance splits the difference.

    Repeatedly welds the closest pair of end points, so the result does not
    depend on the order of the splines. Two splines of different types are
    never welded to each other. Every weld takes exactly one point away, which
    is how the callers count them.
    """
    datas = list(datas)
    while True:
        ends = []
        for i, d in enumerate(datas):
            if d.cyclic or not d.points:
                continue
            if allowed is None or allowed(d, 'start'):
                ends.append((i, 'start', d.points[0].co))
            if len(d.points) > 1 and (allowed is None or allowed(d, 'end')):
                ends.append((i, 'end', d.points[-1].co))
        best = None
        for x in range(len(ends)):
            for y in range(x + 1, len(ends)):
                (i, si, ca), (j, sj, cb) = ends[x], ends[y]
                if i == j and len(datas[i].points) < 3:
                    continue
                if datas[i].kind != datas[j].kind:
                    continue
                dd = dist(ca, cb)
                if dd <= threshold and (best is None or dd < best[0]):
                    best = (dd, i, si, j, sj)
        if best is None:
            return datas
        _, i, si, j, sj = best

        def welded(left, right):
            """The point that replaces the two, placed as `at_center` says."""
            if at_center:
                target = sd.midpoint(left, right)
                left, right = sd.moved_to(left, target), sd.moved_to(right, target)
            return sd.merge_points(left, right)

        if i == j:
            d = datas[i]
            out = d.copy()
            out.points = ([welded(d.points[-1], d.points[0])]
                          + [sd.replace(p) for p in d.points[1:-1]])
            out.cyclic = True
            datas[i] = out
            continue
        a = datas[i] if si == 'end' else sd.inverted(datas[i])
        b = datas[j] if sj == 'start' else sd.inverted(datas[j])
        out = a.copy()
        out.points = (
            [sd.replace(p) for p in a.points[:-1]]
            + [welded(a.points[-1], b.points[0])]
            + [sd.replace(p) for p in b.points[1:]]
        )
        lo, hi = min(i, j), max(i, j)
        datas[lo] = out
        del datas[hi]


class ETR_OT_curve_toolkit_join_merge(bpy.types.Operator):
    """Join the selected curves (like Ctrl+J) and weld end points closer than the Threshold into as few splines as possible"""
    bl_idname = "etr.curve_toolkit_join_merge"
    bl_label = "Join & Merge"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and len(selected_curves(context)) >= 2

    def execute(self, context):
        objs = selected_curves(context)
        for obj in objs:
            if any(s.type == 'NURBS' for s in obj.data.splines):
                self.report({'ERROR'}, f"'{obj.name}' has NURBS splines: Join & Merge works only with Poly and Bezier curves")
                return {'CANCELLED'}

        active = context.active_object if context.active_object in objs else objs[0]
        with context.temp_override(
            active_object=active, object=active,
            selected_objects=objs, selected_editable_objects=objs,
        ):
            bpy.ops.object.join()
        context.view_layer.objects.active = active

        datas = sd.read_all(active.data)
        if any(d.kind == 'BEZIER' for d in datas):
            datas = [sd.to_bezier(d) if d.kind == 'POLY' else d for d in datas]

        threshold = context.scene.etr_curves_toolkit.merge_threshold
        before = len(datas)
        datas = merge_chains(datas, lambda a, b: world_distance(active, a, b), threshold)
        sd.replace_splines(active.data, datas)

        if len(datas) > 1:
            self.report(
                {'WARNING'},
                f"Joined {len(objs)} curves; {len(datas)} separate splines remain "
                f"(their end points are farther apart than the Threshold)",
            )
        else:
            self.report({'INFO'}, f"Joined {len(objs)} curves into one spline ({before - len(datas)} welds)")
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Remove Doubles
# -----------------------------------------------------------------------------

def _remove_doubles(d, close, only_selected):
    """Merge consecutive points of a spline that overlap. Returns
    (new SplineData, number of removed points)."""
    def can_merge(a, b):
        return (not only_selected or (a.select and b.select)) and close(a.co, b.co)

    pts = []
    for p in d.points:
        if pts and can_merge(pts[-1], p):
            pts[-1] = sd.merge_points(pts[-1], p)
        else:
            pts.append(sd.replace(p))
    if d.cyclic and len(pts) > 1 and can_merge(pts[-1], pts[0]):
        pts = [sd.merge_points(pts[-1], pts[0])] + pts[1:-1]
    out = d.copy()
    out.points = pts
    if len(pts) < 2:
        out.cyclic = False
    return out, len(d.points) - len(pts)


# -----------------------------------------------------------------------------
# Separate
# -----------------------------------------------------------------------------

class ETR_OT_curve_toolkit_separate(bpy.types.Operator):
    """Send every selected spline to a new curve object of its own, like Separate by Loose Parts does with mesh islands. A spline with only some points selected goes whole. In Object Mode, every spline of the selected curves. Any curve type"""
    bl_idname = "etr.curve_toolkit_separate"
    bl_label = "Separate All Selected"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode == 'OBJECT':
            return bool(selected_curves(context))
        return context.mode == EDIT_MODE and has_active_curve(context)

    def execute(self, context):
        if context.mode == 'OBJECT':
            return self._separate_objects(context)
        created, kept = [], []
        with edit_scope(context, reenter=False) as objs:
            for obj in objs:
                datas = sd.read_all(obj.data)
                picked = [i for i, d in enumerate(datas)
                          if any(sd.point_selected(p, d.kind) for p in d.points)]
                if not picked:
                    continue
                if len(picked) == len(datas):
                    # Nothing would be left of the curve, so one stays.
                    picked.pop()
                    kept.append(obj.name)
                if not picked:
                    continue
                for index in picked:
                    new_obj = new_curve_object(context, obj, [datas[index]], obj.name,
                                               numbered=True)
                    link_like(new_obj, obj, context)
                    created.append(new_obj)
                sd.replace_splines(
                    obj.data, [d for i, d in enumerate(datas) if i not in picked])

            if not created:
                self.report({'WARNING'}, "Select the spline(s) to separate")
                return {'CANCELLED'}

            for obj in context.selected_objects:
                obj.select_set(False)
            last = None
            for obj in created:
                try:
                    obj.select_set(True)
                    last = obj
                except RuntimeError:
                    pass
            if last is not None:
                context.view_layer.objects.active = last

        message = f"Separated {len(created)} spline(s)"
        if kept:
            message += f" (one spline was left in {', '.join(kept)})"
        self.report({'INFO'}, message)
        return {'FINISHED'}

    def _separate_objects(self, context):
        """Object Mode: every selected curve with several splines keeps its
        first one and sends each of the others to a new object. Nothing is
        hidden; the originals and the new objects end up selected."""
        created = []
        sources = [o for o in selected_curves(context) if len(o.data.splines) > 1]
        for obj in sources:
            if obj.data.users > 1:
                obj.data = obj.data.copy()   # do not empty the other users
            datas = sd.read_all(obj.data)
            for data in datas[1:]:
                new_obj = new_curve_object(context, obj, [data], obj.name, numbered=True)
                link_like(new_obj, obj, context)
                created.append(new_obj)
            sd.replace_splines(obj.data, datas[:1])
        if not created:
            self.report({'WARNING'}, "No selected curve has more than one spline")
            return {'CANCELLED'}
        for obj in created:
            try:
                obj.select_set(True)
            except RuntimeError:
                pass
        self.report({'INFO'}, f"Separated {len(created)} spline(s) from {len(sources)} curve(s)")
        return {'FINISHED'}


class ETR_OT_curve_toolkit_remove_doubles(bpy.types.Operator):
    """Merge consecutive points that are closer than the Threshold, keeping the shape. In Edit Mode only the selected points are considered"""
    bl_idname = "etr.curve_toolkit_remove_doubles"
    bl_label = "Remove Doubles"
    bl_options = {'REGISTER', 'UNDO'}

    poll = classmethod(_poll_object_or_edit)

    def execute(self, context):
        in_edit = context.mode == EDIT_MODE
        threshold = context.scene.etr_curves_toolkit.merge_threshold
        removed = 0

        def process(objs):
            nonlocal removed
            for obj in objs:
                close = lambda a, b, o=obj: world_distance(o, a, b) <= threshold
                datas = sd.read_all(obj.data)
                dirty = False
                for i, d in enumerate(datas):
                    new, n = _remove_doubles(d, close, in_edit)
                    if n:
                        datas[i] = new
                        removed += n
                        dirty = True
                if dirty:
                    sd.replace_splines(obj.data, datas)

        if in_edit:
            with edit_scope(context) as objs:
                process(objs)
        else:
            process(selected_curves(context))

        if not removed:
            self.report({'INFO'}, "No doubles found")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Removed {removed} point(s)")
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Remove Strays
# -----------------------------------------------------------------------------

def _spline_length(obj, data, steps=8):
    """Length of a spline, measured in world space.

    A Bezier spline is sampled; of a Poly or NURBS spline the control polygon
    is measured, which is never shorter than the curve itself, so a NURBS
    spline is only called a stray when it really is one.
    """
    mw = world_matrix(obj)
    pts = [mw @ Vector(co) for co in sd.flatten(data, steps=steps)]
    return sum((b - a).length for a, b in zip(pts, pts[1:]))


def _is_stray(obj, data, threshold):
    """A spline with a single point, or shorter than the Threshold."""
    return len(data.points) < 2 or _spline_length(obj, data) <= threshold


def _remove_stray_vertices(context):
    """Delete the loose vertices (no edge) of every mesh in Edit Mode.
    Returns how many went."""
    import bmesh
    removed = 0
    for obj in context.objects_in_mode_unique_data:
        if obj.type != 'MESH':
            continue
        bm = bmesh.from_edit_mesh(obj.data)
        loose = [v for v in bm.verts if not v.link_edges]
        if not loose:
            continue
        bmesh.ops.delete(bm, geom=loose, context='VERTS')
        bmesh.update_edit_mesh(obj.data)
        removed += len(loose)
    return removed


class ETR_OT_curve_toolkit_remove_strays(bpy.types.Operator):
    """Remove the stray splines that booleans, offsets and splits can leave behind: single-point splines and ones shorter than the Threshold. Any curve type. In the Edit Mode of a mesh, its stray (loose) vertices"""
    bl_idname = "etr.curve_toolkit_remove_strays"
    bl_label = "Remove Strays"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH' or _poll_object_or_edit(cls, context)

    def execute(self, context):
        if context.mode == 'EDIT_MESH':
            removed = _remove_stray_vertices(context)
            if not removed:
                self.report({'INFO'}, "No stray vertices found")
                return {'CANCELLED'}
            self.report({'INFO'}, f"Removed {removed} stray vertex(es)")
            return {'FINISHED'}

        threshold = context.scene.etr_curves_toolkit.merge_threshold
        removed = 0
        emptied = []

        def process(objs):
            nonlocal removed
            for obj in objs:
                datas = sd.read_all(obj.data)
                kept = [d for d in datas if not _is_stray(obj, d, threshold)]
                if len(kept) == len(datas):
                    continue
                removed += len(datas) - len(kept)
                if not kept:
                    emptied.append(obj.name)
                sd.replace_splines(obj.data, kept)

        if context.mode == EDIT_MODE:
            with edit_scope(context) as objs:
                process(objs)
        else:
            process(selected_curves(context))

        if not removed:
            self.report({'INFO'}, "No stray splines found")
            return {'CANCELLED'}
        if emptied:
            self.report(
                {'WARNING'},
                f"Removed {removed} stray spline(s); nothing is left of "
                f"{', '.join(emptied)}",
            )
        else:
            self.report({'INFO'}, f"Removed {removed} stray spline(s)")
        return {'FINISHED'}


def _select_stray_vertices(context):
    """Select the loose vertices (no edge) of every mesh in Edit Mode, and
    only those. Returns how many there are."""
    import bmesh
    found = 0
    for obj in context.objects_in_mode_unique_data:
        if obj.type != 'MESH':
            continue
        bm = bmesh.from_edit_mesh(obj.data)
        for elems in (bm.edges, bm.faces):
            for e in elems:
                e.select = False
        for v in bm.verts:
            v.select = not v.link_edges
            found += v.select
        bm.select_history.clear()
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
    return found


def select_strays(context):
    """Select the stray points, and only those (Select Strays). Returns (how
    many, what they are)."""
    if context.mode == 'EDIT_MESH':
        return _select_stray_vertices(context), "stray vertex(es)"
    threshold = context.scene.etr_curves_toolkit.merge_threshold
    found = 0
    with edit_scope(context) as objs:
        for obj in objs:
            for spline in obj.data.splines:
                stray = _is_stray(obj, sd.read_spline(spline), threshold)
                found += stray
                _select_spline(spline, stray)
    return found, "stray spline(s)"


def _report_found(op, found, what):
    if not found:
        op.report({'INFO'}, f"No {what.replace('(es)', 'es').replace('(s)', 's')} found")
    else:
        op.report({'INFO'}, f"Selected {found} {what}")


class ETR_OT_curve_toolkit_select_strays(bpy.types.Operator):
    """Select the stray points, and only those, so they can be checked before deleting them: single-point splines and splines shorter than the Threshold in a curve, loose vertices in a mesh. Edit Mode"""
    bl_idname = "etr.curve_toolkit_select_strays"
    bl_label = "Select Strays"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode == 'EDIT_MESH':
            return True
        if context.mode == EDIT_MODE and has_active_curve(context):
            return True
        cls.poll_message_set("Works in the Edit Mode of a curve or of a mesh")
        return False

    def execute(self, context):
        found, what = select_strays(context)
        _report_found(self, found, what)
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Select by Type
# -----------------------------------------------------------------------------

#: Spline types of Select by Type: (type, name in the reports).
_TYPE_NAMES = {'POLY': "Poly", 'BEZIER': "Bezier", 'NURBS': "NURBS"}

#: The choices of the Select All by Type menu of the panel.
SELECT_CHOICES = (
    ('NONE', "None", "Deselect everything, in every curve or mesh being edited"),
    ('STRAYS', "Strays", "Select the stray points, and only those: single-point "
                         "splines and splines shorter than the Threshold in a curve, "
                         "loose vertices in a mesh"),
    ('POLY', "Polys", "Select every Poly spline, and only those (not the stray points)"),
    ('BEZIER', "Beziers", "Select every Bezier spline, and only those (not the stray "
                          "points)"),
    ('NURBS', "NURBS", "Select every NURBS spline, and only those (not the stray points)"),
)


def _select_spline(spline, state):
    if spline.type == 'BEZIER':
        for bp in spline.bezier_points:
            bp.select_control_point = state
            bp.select_left_handle = state
            bp.select_right_handle = state
    else:
        for p in spline.points:
            p.select = state


def _deselect_meshes(context):
    import bmesh
    for obj in context.objects_in_mode_unique_data:
        if obj.type != 'MESH':
            continue
        bm = bmesh.from_edit_mesh(obj.data)
        for elems in (bm.verts, bm.edges, bm.faces):
            for e in elems:
                e.select = False
        bm.select_history.clear()
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)


class ETR_OT_curve_toolkit_select_by_type(bpy.types.Operator):
    """Select All by Type: every spline of one type (Poly, Bezier or NURBS), the stray points, or nothing (None), in every curve being edited. Edit Mode"""
    bl_idname = "etr.curve_toolkit_select_by_type"
    bl_label = "Select by Type"
    bl_options = {'REGISTER', 'UNDO'}

    kind: EnumProperty(
        name="Type",
        description="What to select",
        items=SELECT_CHOICES,
        default='POLY',
    )
    extend: BoolProperty(
        name="Extend",
        description="Keep what was already selected, instead of selecting only the "
                    "splines of this type",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        if context.mode == 'EDIT_MESH':
            return True
        if context.mode == EDIT_MODE and has_active_curve(context):
            return True
        cls.poll_message_set("Works in the Edit Mode of a curve (or of a mesh, for "
                             "None and Strays)")
        return False

    @classmethod
    def description(cls, context, properties):
        if properties is None or not properties.is_property_set("kind"):
            return cls.__doc__
        text = dict((k, d) for k, _, d in SELECT_CHOICES)[properties.kind]
        return f"{text}. Edit Mode"

    def execute(self, context):
        if self.kind == 'STRAYS':
            found, what = select_strays(context)
            _report_found(self, found, what)
            return {'FINISHED'}
        if context.mode == 'EDIT_MESH':
            if self.kind != 'NONE':
                self.report({'ERROR'}, "In a mesh, only None and Strays can be selected")
                return {'CANCELLED'}
            _deselect_meshes(context)
            return {'FINISHED'}
        if self.kind == 'NONE':
            with edit_scope(context) as objs:
                for obj in objs:
                    for spline in obj.data.splines:
                        _select_spline(spline, False)
            return {'FINISHED'}
        found = 0
        threshold = context.scene.etr_curves_toolkit.merge_threshold
        with edit_scope(context) as objs:
            for obj in objs:
                for spline in obj.data.splines:
                    # Stray points are left to Strays: Polys, Beziers and NURBS
                    # are the real splines of that type.
                    if spline.type == self.kind and not _is_stray(
                            obj, sd.read_spline(spline), threshold):
                        _select_spline(spline, True)
                        found += 1
                    elif not self.extend:
                        _select_spline(spline, False)
        name = _TYPE_NAMES[self.kind]
        if not found:
            self.report({'INFO'}, f"No {name} splines found")
        else:
            self.report({'INFO'}, f"Selected {found} {name} spline(s)")
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Set Resolution
# -----------------------------------------------------------------------------

def _live_point_selected(point, kind):
    """spline_data.point_selected() for a point of a live Blender spline."""
    if kind == 'BEZIER':
        return (point.select_control_point or point.select_left_handle
                or point.select_right_handle)
    return point.select


def _live_points(spline):
    return spline.bezier_points if spline.type == 'BEZIER' else spline.points


class ETR_OT_curve_toolkit_set_resolution(bpy.types.Operator):
    """Give the same Resolution U to many splines at once (the points Blender computes between control points). Set All applies it to every selected spline. Any curve type"""
    bl_idname = "etr.curve_toolkit_set_resolution"
    bl_label = "Set Resolution"
    bl_options = {'REGISTER', 'UNDO'}

    resolution: IntProperty(
        name="Resolution",
        description=(
            "Points computed between every pair of control points. A lower "
            "value draws the curve with fewer and longer straight pieces"
        ),
        default=12,
        min=1,
        soft_max=64,
        max=1024,
    )

    poll = classmethod(_poll_object_or_edit)

    def execute(self, context):
        changed = 0

        if context.mode == EDIT_MODE:
            for obj in curves_in_edit_mode(context):
                for spline in obj.data.splines:
                    if not any(_live_point_selected(p, spline.type)
                               for p in _live_points(spline)):
                        continue
                    if spline.resolution_u != self.resolution:
                        spline.resolution_u = self.resolution
                        changed += 1
            if not changed:
                self.report({'INFO'}, "No spline to change: select at least one point")
                return {'CANCELLED'}
        else:
            for obj in selected_curves(context):
                for spline in obj.data.splines:
                    if spline.resolution_u != self.resolution:
                        spline.resolution_u = self.resolution
                        changed += 1
                # The curve data keeps its own value, the one the Object Data
                # properties show, and new splines are born with it.
                obj.data.resolution_u = self.resolution

        self.report({'INFO'}, f"Resolution {self.resolution} on {changed} spline(s)")
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Set Dimensions (2D / 3D)
# -----------------------------------------------------------------------------

class ETR_OT_curve_toolkit_set_dimensions(bpy.types.Operator):
    """Make every selected curve 2D or 3D at once (the setting of Object Data > Shape). The 2D and 3D buttons next to it show and set the one of the active curve"""
    bl_idname = "etr.curve_toolkit_set_dimensions"
    bl_label = "Set Dimensions"
    bl_options = {'REGISTER', 'UNDO'}

    dimensions: EnumProperty(
        name="Dimensions",
        description="2D: flat curves, filled when closed. 3D: free in space (a 3D curve "
                    "made 2D is flattened onto its local XY plane)",
        items=(
            ('2D', "2D", "Flat curves, in their local XY plane"),
            ('3D', "3D", "Curves free in space"),
        ),
        default='2D',
    )

    poll = classmethod(_poll_object_or_edit)

    def execute(self, context):
        if context.mode == EDIT_MODE:
            objs = curves_in_edit_mode(context)
        else:
            objs = selected_curves(context)
        changed = 0
        for curve in {o.data for o in objs}:
            if curve.dimensions != self.dimensions:
                curve.dimensions = self.dimensions
                changed += 1
        self.report({'INFO'}, f"{self.dimensions} on {changed} curve(s)")
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Change Origin
# -----------------------------------------------------------------------------

_ORIGIN_DESCRIPTIONS = {
    'IN': "Move the origin to the start of the curve (Factor 0.0). Object Mode: the first "
          "spline of each selected curve. Edit Mode: the selected spline",
    'MID': "Move the origin to the midpoint of the curve (Factor 0.5, measured along its "
           "length). Object Mode: the first spline of each selected curve. Edit Mode: the "
           "selected spline, or the segment between two consecutive selected points",
    'OUT': "Move the origin to the end of the curve (Factor 1.0). Object Mode: the first "
           "spline of each selected curve. Edit Mode: the selected spline",
    'GEOMETRY': "Move the origin to the center of the bounding box of the curve (its real "
                "shape, not its handles). Object Mode: every spline of each selected "
                "curve. Edit Mode: the selected splines",
}


def _nurbs_polyline(context, obj, spline_data):
    """Evaluated points of a NURBS spline (Blender evaluates the knots)."""
    curve = bpy.data.curves.new("etr_tmp", 'CURVE')
    curve.dimensions = obj.data.dimensions
    data = spline_data.copy()
    data.settings['resolution_u'] = 64
    sd.write_spline(curve, data)
    tmp = bpy.data.objects.new("etr_tmp", curve)
    context.scene.collection.objects.link(tmp)
    try:
        context.view_layer.update()
        evaluated = tmp.evaluated_get(context.evaluated_depsgraph_get())
        mesh = bpy.data.meshes.new_from_object(evaluated)
        pts = [tuple(v.co) for v in mesh.vertices]
        bpy.data.meshes.remove(mesh)
    finally:
        bpy.data.objects.remove(tmp)
        bpy.data.curves.remove(curve)
    if data.cyclic and pts:
        pts.append(pts[0])
    return pts


def _polyline(context, obj, d):
    """Local-space polyline of a spline snapshot (its real shape)."""
    if d.kind == 'NURBS' and len(d.points) > 1:
        return _nurbs_polyline(context, obj, d)
    return sd.flatten(d, steps=64)


def _segment(d, k):
    """Open snapshot of segment k of a spline (points k and k + 1)."""
    n = len(d.points)
    return sd.SplineData(d.kind, [sd.replace(d.points[k]), sd.replace(d.points[(k + 1) % n])],
                         False, dict(d.settings))


def _origin_point(context, obj, mode, datas, segment=None):
    """Local-space point for the origin.

    datas: the splines it is taken from (for In, Mid and Out, only the first
    one counts). segment: index of a segment of that first spline, for a Mid
    taken on that segment only.
    """
    if not datas:
        return None
    if mode == 'GEOMETRY':
        pts = [p for d in datas for p in _polyline(context, obj, d)]
        if not pts:
            return None
        return tuple((min(p[i] for p in pts) + max(p[i] for p in pts)) / 2.0
                     for i in range(3))
    d = datas[0]
    if segment is not None and d.kind != 'NURBS':
        d = _segment(d, segment)
    factor = {'IN': 0.0, 'MID': 0.5, 'OUT': 1.0}[mode]
    pts = _polyline(context, obj, d)
    if not pts:
        return None
    return geo.point_at_factor(pts, factor)


def _picked_for_origin(obj):
    """(splines, segment) Change Origin uses in Edit Mode.

    The splines with a selected point, the active spline first when it is
    one of them (In, Mid and Out use only that first one). segment is the
    segment picked by selecting its two ends (see sd.selected_segment) on
    that first spline, or None.
    """
    splines = list(obj.data.splines)
    datas = sd.read_all(obj.data)
    picked = [i for i, d in enumerate(datas)
              if any(sd.point_selected(p, d.kind) for p in d.points)]
    try:
        active = splines.index(obj.data.splines.active)
    except ValueError:
        active = None
    if active in picked:
        picked.remove(active)
        picked.insert(0, active)
    chosen = [datas[i] for i in picked]
    segment = sd.selected_segment(chosen[0]) if chosen else None
    return chosen, segment


def _shift_geometry(curve, offset):
    """Translate every point and handle of the curve by -offset."""
    datas = sd.read_all(curve)
    for d in datas:
        for p in d.points:
            p.co = geo.sub(p.co, offset)
            if p.hl is not None:
                p.hl = geo.sub(p.hl, offset)
                p.hr = geo.sub(p.hr, offset)
    sd.replace_splines(curve, datas)


def _set_origin_local(context, obj, offset):
    """Put the origin of `obj` at a point of its local space, without moving
    its geometry or its children."""
    children = [(c, world_matrix(c)) for c in obj.children]
    _shift_geometry(obj.data, offset)
    mw = world_matrix(obj)
    mw.translation = mw @ Vector(offset)
    obj.matrix_world = mw
    context.view_layer.update()
    for child, child_mw in children:
        child.matrix_world = child_mw


class ETR_OT_curve_toolkit_change_origin(bpy.types.Operator):
    """Change the origin of the curves. The geometry does not move"""
    bl_idname = "etr.curve_toolkit_change_origin"
    bl_label = "Change Origin"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="Origin",
        items=(
            ('IN', "Curve In", "Factor 0.0"),
            ('MID', "Curve Midpoint", "Factor 0.5"),
            ('OUT', "Curve Out", "Factor 1.0"),
            ('GEOMETRY', "Bounds Center", "Center of the bounding box"),
        ),
        default='IN',
    )

    @classmethod
    def description(cls, context, properties):
        return _ORIGIN_DESCRIPTIONS.get(properties.mode, cls.__doc__)

    @classmethod
    def poll(cls, context):
        if context.mode == 'OBJECT' and selected_curves(context):
            return True
        if context.mode == EDIT_MODE and has_active_curve(context):
            return True
        cls.poll_message_set("Select curves (Object Mode), or a point of a spline (Edit Mode)")
        return False

    def execute(self, context):
        if context.mode == EDIT_MODE:
            return self._edit(context)

        moved = skipped = 0
        for obj in selected_curves(context):
            if obj.data.users > 1:
                skipped += 1
                continue
            offset = _origin_point(context, obj, self.mode, sd.read_all(obj.data))
            if offset is None:
                skipped += 1
                continue
            _set_origin_local(context, obj, offset)
            moved += 1

        if skipped:
            self.report({'WARNING'}, f"{skipped} curve(s) skipped (empty or sharing data with other objects)")
        return {'FINISHED'} if moved else {'CANCELLED'}

    def _edit(self, context):
        """The active curve, from its selected spline (or segment)."""
        obj = context.active_object
        if obj.data.users > 1:
            self.report({'ERROR'}, f"'{obj.name}' shares its curve data with other objects")
            return {'CANCELLED'}
        with edit_scope(context):
            datas, segment = _picked_for_origin(obj)
            if not datas:
                self.report({'ERROR'}, "Change Origin: select a point of the spline")
                return {'CANCELLED'}
            if self.mode != 'MID':
                segment = None
            offset = _origin_point(context, obj, self.mode, datas, segment)
            if offset is None:
                self.report({'ERROR'}, "Change Origin: the selected spline is empty")
                return {'CANCELLED'}
            _set_origin_local(context, obj, offset)
        if segment is not None:
            self.report({'INFO'}, "Origin at the midpoint of the selected segment")
        elif self.mode != 'GEOMETRY' and len(datas) > 1:
            self.report({'INFO'}, "Several splines selected: the active one (or the first) "
                                  "was used")
        return {'FINISHED'}


class ETR_OT_curve_toolkit_origin_to_selected(bpy.types.Operator):
    """Move the origin of the curve being edited to the selected control point (the center of them, if there are several). The geometry does not move and the Edit Mode is kept"""
    bl_idname = "etr.curve_toolkit_origin_to_selected"
    bl_label = "To Selected Point"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode == EDIT_MODE and has_active_curve(context):
            return True
        cls.poll_message_set("Works in the Edit Mode of a curve, with a control point selected")
        return False

    def execute(self, context):
        obj = context.active_object
        if obj.data.users > 1:
            self.report({'ERROR'}, f"'{obj.name}' shares its curve data with other objects")
            return {'CANCELLED'}
        with edit_scope(context):
            cos = []
            for spline in obj.data.splines:
                if spline.type == 'BEZIER':
                    cos += [tuple(bp.co) for bp in spline.bezier_points if bp.select_control_point]
                else:
                    cos += [tuple(p.co)[:3] for p in spline.points if p.select]
            if not cos:
                self.report({'ERROR'}, "To Selected Point: select a control point of the "
                                       "active curve")
                return {'CANCELLED'}
            offset = geo.mul(tuple(sum(c[i] for c in cos) for i in range(3)), 1.0 / len(cos))
            children = [(c, world_matrix(c)) for c in obj.children]
            _shift_geometry(obj.data, offset)
            mw = world_matrix(obj)
            mw.translation = mw @ Vector(offset)
            obj.matrix_world = mw
            context.view_layer.update()
            for child, child_mw in children:
                child.matrix_world = child_mw
        if len(cos) > 1:
            self.report({'INFO'}, f"Origin at the center of {len(cos)} selected points")
        return {'FINISHED'}


def _move_origin(context, obj, target):
    """Put the origin of `obj` at `target` (a world-space point) without
    moving its geometry or its children."""
    mw = world_matrix(obj)
    offset = tuple(mw.inverted() @ Vector(target))
    children = [(c, world_matrix(c)) for c in obj.children]
    _shift_geometry(obj.data, offset)
    mw.translation = mw @ Vector(offset)
    obj.matrix_world = mw
    context.view_layer.update()
    for child, child_mw in children:
        child.matrix_world = child_mw


_TARGETS = {
    'WORLD': ("To World Origin", "the world origin"),
    'CURSOR': ("To 3D Cursor", "the 3D Cursor"),
}


class ETR_OT_curve_toolkit_origin_to_target(bpy.types.Operator):
    """Move the origin of the curves to the world origin or to the 3D Cursor. The geometry does not move. Object Mode: the selected curves. Edit Mode: the curves being edited, and the Edit Mode is kept"""
    bl_idname = "etr.curve_toolkit_origin_to_target"
    bl_label = "Origin To"
    bl_options = {'REGISTER', 'UNDO'}

    target: EnumProperty(
        name="Target",
        items=(
            ('WORLD', "To World Origin", "The world origin (0, 0, 0)"),
            ('CURSOR', "To 3D Cursor", "The location of the 3D Cursor"),
        ),
        default='WORLD',
    )

    @classmethod
    def description(cls, context, properties):
        return (f"Move the origin of the curves to {_TARGETS[properties.target][1]}. The "
                "geometry does not move. Object Mode: the selected curves. Edit Mode: the "
                "curves being edited (the Edit Mode is kept)")

    @classmethod
    def poll(cls, context):
        if context.mode == 'OBJECT' and selected_curves(context):
            return True
        if context.mode == EDIT_MODE and has_active_curve(context):
            return True
        cls.poll_message_set("Select curves (Object Mode) or edit a curve")
        return False

    def execute(self, context):
        if self.target == 'CURSOR':
            target = tuple(context.scene.cursor.location)
        else:
            target = (0.0, 0.0, 0.0)
        title = _TARGETS[self.target][0]
        moved = skipped = 0
        if context.mode == EDIT_MODE:
            with edit_scope(context) as objs:
                for obj in objs:
                    if obj.data.users > 1:
                        skipped += 1
                        continue
                    _move_origin(context, obj, target)
                    moved += 1
        else:
            for obj in selected_curves(context):
                if obj.data.users > 1:
                    skipped += 1
                    continue
                _move_origin(context, obj, target)
                moved += 1
        if skipped:
            self.report({'WARNING'}, f"{title}: {skipped} curve(s) skipped (sharing data with "
                                     "other objects)")
        return {'FINISHED'} if moved else {'CANCELLED'}


# -----------------------------------------------------------------------------

classes = (
    ETR_OT_curve_toolkit_set_first_point,
    ETR_OT_curve_toolkit_invert_direction,
    ETR_OT_curve_toolkit_split_at_points,
    ETR_OT_curve_toolkit_set_dimensions,
    ETR_OT_curve_toolkit_join_merge,
    ETR_OT_curve_toolkit_separate,
    ETR_OT_curve_toolkit_remove_doubles,
    ETR_OT_curve_toolkit_remove_strays,
    ETR_OT_curve_toolkit_select_strays,
    ETR_OT_curve_toolkit_select_by_type,
    ETR_OT_curve_toolkit_set_resolution,
    ETR_OT_curve_toolkit_change_origin,
    ETR_OT_curve_toolkit_origin_to_selected,
    ETR_OT_curve_toolkit_origin_to_target,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
