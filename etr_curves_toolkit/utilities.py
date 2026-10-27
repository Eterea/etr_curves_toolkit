# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Utilities

Small tools that work on any curve (Poly, Bezier, NURBS; 2D or 3D) unless
noted:

  - Set First Point   (Edit Mode)   selected point becomes point 0.
  - Invert Direction  (Object/Edit) reverse the order of the points.
  - Split at Points   (Object/Edit) every segment goes to its own object.
                                    Poly and Bezier only. Its button is drawn
                                    with the Splits, and it shares their
                                    Sources / Results collection options.
  - Separate All Selected (Edit)    every selected spline goes to a new curve
                                    object of its own, leaving the curve it
                                    was in. Ends in Object Mode.
  - Join & Merge      (Object)      join curves and weld coincident end points
                                    into as few splines as possible.
                                    Poly and Bezier only.
  - Remove Doubles    (Object/Edit) merge consecutive points that overlap.
  - Remove Strays     (Object/Edit) delete the splines with a single point and
                                    those shorter than the Threshold.
  - Set Resolution    (Object/Edit) the same Resolution U for many splines.
  - Change Origin     (Object)      origin to curve start / midpoint / end /
                                    geometry.

All shapes are preserved: Blender cannot reorder or delete spline points in
place, so each tool rebuilds the affected splines from snapshots
(see spline_data.py).
"""

import bpy
from bpy.props import EnumProperty, IntProperty
from mathutils import Vector

from . import geometry as geo
from . import spline_data as sd
from .context_utils import (
    EDIT_MODE,
    curves_in_edit_mode,
    edit_scope,
    finish_sources_and_results,
    has_active_curve,
    link_like,
    new_curve_object,
    selected_curves,
    world_distance,
    world_matrix,
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
    """Invert the direction of the curve, keeping its shape. In Object Mode all the splines of the selected curves are inverted; in Edit Mode, the splines that have selected points. On a closed spline point 0 stays point 0"""
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
# Split at Points
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
    """Cut the curve at its control points: every segment becomes a new curve object. The original is kept, hidden. In Edit Mode only the selected points are used. Poly and Bezier only (not NURBS). The Sources / Results collection options apply"""
    bl_idname = "etr.curve_toolkit_split_at_points"
    bl_label = "Split at Points"
    bl_options = {'REGISTER', 'UNDO'}

    poll = classmethod(_poll_object_or_edit)

    def execute(self, context):
        in_edit = context.mode == EDIT_MODE
        active = context.active_object

        targets = (
            [o for o in context.objects_in_mode_unique_data if o.type == 'CURVE']
            if in_edit else selected_curves(context)
        )
        for obj in targets:
            if any(s.type == 'NURBS' for s in obj.data.splines):
                self.report({'ERROR'}, f"'{obj.name}' has NURBS splines: Split at Points works only with Poly and Bezier curves")
                return {'CANCELLED'}

        created = []
        scope = edit_scope(context, reenter=False) if in_edit else _null_scope(targets)
        with scope as objs:
            counter = 0
            for obj in objs:
                pieces_data = []
                for d in sd.read_all(obj.data):
                    n = len(d.points)
                    if in_edit:
                        cuts = [k for k, p in enumerate(d.points) if p.select]
                        if not cuts:
                            continue
                    else:
                        cuts = list(range(n))
                    for a, b in _piece_indices(n, d.cyclic, cuts):
                        if b > a:
                            pieces_data.append(_make_piece(d, a, b))
                if not pieces_data:
                    continue
                new_objs = []
                for piece in pieces_data:
                    counter += 1
                    new_objs.append(new_curve_object(context, obj, [piece], f"Split_{counter:02d}"))
                created.append((obj, new_objs))

            if not created:
                self.report({'WARNING'}, "Nothing to split")
                if in_edit:
                    bpy.ops.object.mode_set(mode='EDIT')
                return {'CANCELLED'}

            sources = [obj for obj, _ in created]
            results = [(new_obj, obj) for obj, new_objs in created for new_obj in new_objs]
            anchor = active if active in sources else sources[0]
            finish_sources_and_results(context, sources, results, anchor)

        self.report({'INFO'}, f"Created {len(results)} segment(s)")
        return {'FINISHED'}


class _null_scope:
    """Stand-in for edit_scope() when we are already in Object Mode."""

    def __init__(self, objs):
        self.objs = objs

    def __enter__(self):
        return self.objs

    def __exit__(self, *exc):
        return False


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
    """Join the selected curve objects (like Join, Ctrl+J) and weld the end points that are closer than the Threshold, so they become as few splines as possible. Poly and Bezier only (a mix is converted to Bezier)"""
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
    """Send every selected spline to a new curve object of its own, the way Separate by Loose Parts does with the islands of a mesh (Blender's own Separate puts them all in one object instead, and cuts a partly selected spline). A spline with only some of its points selected goes whole. The splines leave the curve they were in, which keeps the ones that were not selected; when every spline is selected, one is left behind so that the object does not end up empty. Ends in Object Mode, with the new objects selected. Any curve type"""
    bl_idname = "etr.curve_toolkit_separate"
    bl_label = "Separate All Selected"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return context.mode == EDIT_MODE and has_active_curve(context)

    def execute(self, context):
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
                for number, index in enumerate(picked, start=1):
                    new_obj = new_curve_object(
                        context, obj, [datas[index]], f"{obj.name}_{number:02d}")
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


class ETR_OT_curve_toolkit_remove_strays(bpy.types.Operator):
    """Remove the stray splines that booleans, offsets and splits can leave behind: those with a single point and those shorter than the Threshold. In Object Mode every spline of the selected curves is looked at; in Edit Mode, every spline of the curves being edited, selected or not, because a stray spline is hard to see and harder to pick. A curve whose splines are all strays is left with none. Any curve type"""
    bl_idname = "etr.curve_toolkit_remove_strays"
    bl_label = "Remove Strays"
    bl_options = {'REGISTER', 'UNDO'}

    poll = classmethod(_poll_object_or_edit)

    def execute(self, context):
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
    """Give the same Resolution U to many splines at once: the number of points Blender computes between every pair of control points (its default is 12). In Object Mode it goes to every spline of the selected curves and to the Resolution Preview U of their curve data; in Edit Mode, to every spline that has a selected point or handle. The field next to the button holds the value that is applied: the one of the active spline in Edit Mode, the one of the curve data in Object Mode. Any curve type"""
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
# Change Origin
# -----------------------------------------------------------------------------

_ORIGIN_DESCRIPTIONS = {
    'IN': "Move the origin of the selected curves to their start (Factor 0.0 of the first spline)",
    'MID': "Move the origin of the selected curves to their midpoint (Factor 0.5 of the first spline, measured along its length)",
    'OUT': "Move the origin of the selected curves to their end (Factor 1.0 of the first spline)",
    'GEOMETRY': "Move the origin of the selected curves to their geometric center (same as Object > Set Origin > Origin to Geometry)",
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


def _origin_point(context, obj, mode):
    """Local-space point of the first spline at the requested place."""
    splines = sd.read_all(obj.data)
    if not splines:
        return None
    d = splines[0]
    factor = {'IN': 0.0, 'MID': 0.5, 'OUT': 1.0}[mode]
    if d.kind == 'NURBS':
        pts = _nurbs_polyline(context, obj, d)
    else:
        pts = sd.flatten(d, steps=64)
    if not pts:
        return None
    return geo.point_at_factor(pts, factor)


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


class ETR_OT_curve_toolkit_change_origin(bpy.types.Operator):
    """Change the origin of the selected curves"""
    bl_idname = "etr.curve_toolkit_change_origin"
    bl_label = "Change Origin"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="Origin",
        items=(
            ('IN', "Curve In", "Factor 0.0"),
            ('MID', "Curve Midpoint", "Factor 0.5"),
            ('OUT', "Curve Out", "Factor 1.0"),
            ('GEOMETRY', "Geometry", "Geometric center"),
        ),
        default='IN',
    )

    @classmethod
    def description(cls, context, properties):
        return _ORIGIN_DESCRIPTIONS.get(properties.mode, cls.__doc__)

    poll = classmethod(_poll_object)

    def execute(self, context):
        objs = selected_curves(context)

        if self.mode == 'GEOMETRY':
            with context.temp_override(
                selected_editable_objects=objs, selected_objects=objs,
            ):
                return bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY')

        moved = skipped = 0
        for obj in objs:
            if obj.data.users > 1:
                skipped += 1
                continue
            offset = _origin_point(context, obj, self.mode)
            if offset is None:
                skipped += 1
                continue
            children = [(c, world_matrix(c)) for c in obj.children]
            _shift_geometry(obj.data, offset)
            mw = world_matrix(obj)
            mw.translation = mw @ Vector(offset)
            obj.matrix_world = mw
            context.view_layer.update()
            for child, child_mw in children:
                child.matrix_world = child_mw
            moved += 1

        if skipped:
            self.report({'WARNING'}, f"{skipped} curve(s) skipped (empty or sharing data with other objects)")
        return {'FINISHED'} if moved else {'CANCELLED'}


# -----------------------------------------------------------------------------

classes = (
    ETR_OT_curve_toolkit_set_first_point,
    ETR_OT_curve_toolkit_invert_direction,
    ETR_OT_curve_toolkit_split_at_points,
    ETR_OT_curve_toolkit_join_merge,
    ETR_OT_curve_toolkit_separate,
    ETR_OT_curve_toolkit_remove_doubles,
    ETR_OT_curve_toolkit_remove_strays,
    ETR_OT_curve_toolkit_set_resolution,
    ETR_OT_curve_toolkit_change_origin,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
