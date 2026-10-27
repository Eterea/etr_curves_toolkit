# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Merge Pair and Merge by Distance (Edit Mode)

Two ways of welding the control points of a curve, the way Merge does with the
vertices of a mesh, which Blender does not offer for curves:

  - Merge Pair         two selected points become one, wherever they are: at
                       their midpoint, at the first one or at the second one.
                       No Threshold: the points can be as far apart as they
                       like.
  - Merge by Distance  every pair of end points closer than the Threshold is
                       welded, which chains open splines together (and closes
                       one onto itself when its own two ends meet).

Both only ever weld points that can be welded without tearing the spline apart:

  - two consecutive points of the same spline (open or closed; on a closed one
    the last point and point 0 are consecutive too),
  - the two end points of the same open spline, which closes it,
  - the end points of two different open splines, which joins them into one.

Two points in the middle of a spline that are not neighbours would cut it in
two, and two middle points of different splines cannot be welded at all without
inventing a connection, so both are rejected instead of guessed at.

On a Bezier spline the handles travel with their point, keeping their length
and direction, so the curve arrives at the weld exactly as it did before. Of
the two handles that meet there, the incoming one of the first point and the
outgoing one of the second survive, which is what keeps the shape of the two
segments that stay.

Merge by Distance only looks at end points: two points that happen to overlap
in the middle of a spline are left alone (Remove Doubles is the tool for
those). It shares the Threshold of the panel with Join & Merge, which does the
same welding in Object Mode after joining the curves.
"""

import bpy
from bpy.props import EnumProperty

from . import spline_data as sd
from .context_utils import (
    EDIT_MODE,
    edit_scope,
    has_active_curve,
    world_distance,
)
from .utilities import merge_chains

#: Ways of placing the point that Merge Pair leaves behind.
PLACEMENTS = (
    ('CENTER', "At Center", "Halfway between the two points"),
    ('A', "At Point A", "At point A: the one that comes first (the lower index, "
                        "or the one in the first spline)"),
    ('B', "At Point B", "At point B: the one that comes second (the higher index, "
                        "or the one in the second spline)"),
)


def _poll_edit(cls, context):
    return context.mode == EDIT_MODE and has_active_curve(context)


def _clamp_order(data):
    """Lower order_u of a NURBS spline when it is above the number of points.

    Blender refuses an order higher than the point count, and a merge always
    takes one point away.
    """
    if data.kind != 'NURBS':
        return
    order = data.settings.get("order_u")
    if order is not None and order > len(data.points):
        data.settings["order_u"] = max(2, len(data.points))


# -----------------------------------------------------------------------------
# Merge Pair
# -----------------------------------------------------------------------------

class Rejected(Exception):
    """A pair of points that cannot be welded, with the reason for the user."""


def _selected_points(datas):
    """[(spline index, point index)] of the selected control points.

    Only the control point counts here, not its handles: Merge Pair moves
    points, so picking a handle alone is not asking for one to be welded.
    """
    return [(i, k)
            for i, d in enumerate(datas)
            for k, p in enumerate(d.points)
            if p.select]


def _consecutive(data, a, b):
    """True when points `a` and `b` of a spline are neighbours (on a closed
    spline the last point and point 0 are neighbours too)."""
    n = len(data.points)
    if abs(a - b) == 1:
        return True
    return data.cyclic and n > 2 and {a, b} == {0, n - 1}


def _check_pair(datas, first, second):
    """Make sure the two selected points can be welded, or raise Rejected."""
    (sa, ia), (sb, ib) = first, second
    da, db = datas[sa], datas[sb]

    if sa == sb:
        n = len(da.points)
        if _consecutive(da, ia, ib):
            if n < 3:
                raise Rejected(
                    "the spline has only two points: welding them would leave a "
                    "single point")
            return 'CONSECUTIVE'
        if da.cyclic:
            raise Rejected(
                "the two points are not neighbours on a closed spline: welding "
                "them would cut it in two")
        if {ia, ib} == {0, n - 1}:
            return 'CLOSE'
        raise Rejected(
            "the two points are in the middle of the same spline and are not "
            "neighbours: welding them would cut it in two")

    for d in (da, db):
        if d.cyclic:
            raise Rejected(
                "one of the points is on a closed spline: only the end points of "
                "open splines can be welded across splines")
    if ia not in (0, len(da.points) - 1) or ib not in (0, len(db.points) - 1):
        raise Rejected(
            "both points have to be end points of their spline: a point in the "
            "middle cannot be welded to another spline")
    if da.kind != db.kind:
        raise Rejected(
            f"the two splines are of different types ({da.kind} and {db.kind}): "
            "convert one of them first")
    if len(da.points) + len(db.points) < 3:
        raise Rejected("both splines have a single point")
    return 'JOIN'


def _weld_consecutive(data, ia, ib, target):
    """Weld two neighbouring points of one spline. Returns the new snapshot."""
    n = len(data.points)
    # In the direction of the spline, `left` comes first and `right` second,
    # which decides whose handles survive the weld.
    if {ia, ib} == {0, n - 1} and data.cyclic and n > 2:
        left, right = n - 1, 0
    else:
        left, right = min(ia, ib), max(ia, ib)

    pts = data.points
    merged = sd.merge_points(
        sd.moved_to(pts[left], target),
        sd.moved_to(pts[right], target),
    )
    out = data.copy()
    if right == 0:   # the closing pair of a cyclic spline
        out.points = [merged] + [sd.replace(p) for p in pts[1:n - 1]]
    else:
        out.points = (
            [sd.replace(p) for p in pts[:left]]
            + [merged]
            + [sd.replace(p) for p in pts[right + 1:]]
        )
    _clamp_order(out)
    return out


def _weld_ends(data, target):
    """Weld the two end points of one open spline, closing it."""
    pts = data.points
    merged = sd.merge_points(
        sd.moved_to(pts[-1], target),
        sd.moved_to(pts[0], target),
    )
    out = data.copy()
    out.points = [merged] + [sd.replace(p) for p in pts[1:-1]]
    out.cyclic = True
    _clamp_order(out)
    return out


def _weld_splines(da, ia, db, ib, target):
    """Weld an end point of `da` to an end point of `db`, joining both into one
    open spline. `da` is laid out first, so it is inverted when its welded
    point is its start, and `db` when its welded point is its end."""
    a = da if ia else sd.inverted(da)
    b = db if not ib else sd.inverted(db)
    merged = sd.merge_points(
        sd.moved_to(a.points[-1], target),
        sd.moved_to(b.points[0], target),
    )
    out = a.copy()
    out.points = (
        [sd.replace(p) for p in a.points[:-1]]
        + [merged]
        + [sd.replace(p) for p in b.points[1:]]
    )
    out.cyclic = False
    _clamp_order(out)
    return out


class ETR_OT_curve_toolkit_merge_pair(bpy.types.Operator):
    """Weld two selected control points into one, however far apart they are, the way Merge does with the vertices of a mesh. The points have to be two neighbours of the same spline, the two ends of the same open spline (which closes it) or the end points of two different open splines (which joins them into one): any other pair would cut a spline in two. On Bezier curves the handles travel with their point, so the segments that stay keep their shape. Any curve type"""
    bl_idname = "etr.curve_toolkit_merge_pair"
    bl_label = "Merge Pair"
    bl_options = {'REGISTER', 'UNDO'}

    at: EnumProperty(
        name="Merge",
        description="Where the point that replaces the two is placed",
        items=PLACEMENTS,
        default='CENTER',
    )

    poll = classmethod(_poll_edit)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "at")

    def _target(self, datas, first, second):
        """Where the welded point goes, in the local space of the curve."""
        a = datas[first[0]].points[first[1]].co
        b = datas[second[0]].points[second[1]].co
        if self.at == 'A':
            return tuple(a)
        if self.at == 'B':
            return tuple(b)
        return tuple(0.5 * (x + y) for x, y in zip(a, b))

    def _merge(self, datas, first, second, kind, target):
        """New list of snapshots with the two points welded."""
        (sa, ia), (sb, ib) = first, second
        if kind == 'CONSECUTIVE':
            datas[sa] = _weld_consecutive(datas[sa], ia, ib, target)
            return datas
        if kind == 'CLOSE':
            datas[sa] = _weld_ends(datas[sa], target)
            return datas
        datas[sa] = _weld_splines(datas[sa], ia, datas[sb], ib, target)
        del datas[sb]
        return datas

    def execute(self, context):
        with edit_scope(context) as objs:
            found = [(obj, sd.read_all(obj.data)) for obj in objs]
            picked = [(obj, datas, _selected_points(datas)) for obj, datas in found]
            busy = [item for item in picked if item[2]]

            total = sum(len(item[2]) for item in busy)
            if total != 2:
                self.report(
                    {'ERROR' if total else 'WARNING'},
                    f"Merge Pair needs exactly two selected control points ({total} selected)")
                return {'CANCELLED'}
            if len(busy) != 1:
                self.report(
                    {'ERROR'},
                    "Both points have to be in the same curve object")
                return {'CANCELLED'}

            obj, datas, points = busy[0]
            first, second = sorted(points)
            try:
                kind = _check_pair(datas, first, second)
            except Rejected as exc:
                self.report({'ERROR'}, f"These two points cannot be welded: {exc}")
                return {'CANCELLED'}

            target = self._target(datas, first, second)
            sd.replace_splines(obj.data, self._merge(datas, first, second, kind, target))

        notes = {
            'CONSECUTIVE': "two points welded into one",
            'CLOSE': "the two ends welded: the spline is now closed",
            'JOIN': "two splines welded into one",
        }
        self.report({'INFO'}, f"Merge Pair: {notes[kind]}")
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Merge by Distance
# -----------------------------------------------------------------------------

def _end_selected(data, which):
    """True when that end point of an open spline is selected.

    Only the control point counts, not its handles: a handle on its own is not
    asking for the point to be moved.
    """
    if data.cyclic or not data.points:
        return False
    return (data.points[0] if which == 'start' else data.points[-1]).select


def _point_count(datas):
    return sum(len(d.points) for d in datas)


class ETR_OT_curve_toolkit_merge_by_distance(bpy.types.Operator):
    """Weld the selected end points of open splines that are closer to each other than the Threshold, chaining the splines into as few as possible (a spline whose own two ends meet is closed). Only end points are welded: two points that overlap in the middle of a spline are left alone, which is what Remove Doubles is for. Select the end points to consider (A takes them all). Splines of different types are never welded to each other"""
    bl_idname = "etr.curve_toolkit_merge_by_distance"
    bl_label = "Merge by Distance"
    bl_options = {'REGISTER', 'UNDO'}

    poll = classmethod(_poll_edit)

    def execute(self, context):
        threshold = context.scene.etr_curves_toolkit.merge_threshold
        welds = 0
        seen = False

        with edit_scope(context) as objs:
            for obj in objs:
                datas = sd.read_all(obj.data)
                if not any(_end_selected(d, w) for d in datas for w in ('start', 'end')):
                    continue
                seen = True
                merged = merge_chains(
                    datas,
                    lambda a, b, o=obj: world_distance(o, a, b),
                    threshold,
                    allowed=_end_selected,
                    at_center=True,
                )
                # Every weld takes exactly one point away, whether it chained
                # two splines or closed one onto itself.
                count = _point_count(datas) - _point_count(merged)
                if not count:
                    continue
                welds += count
                sd.replace_splines(obj.data, merged)

        if not seen:
            self.report(
                {'WARNING'},
                "Select the end points to merge (A selects them all)")
            return {'CANCELLED'}
        if not welds:
            self.report(
                {'INFO'},
                "No end points closer than the Threshold")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Merged {welds} pair(s) of end points")
        return {'FINISHED'}


# -----------------------------------------------------------------------------

classes = (
    ETR_OT_curve_toolkit_merge_pair,
    ETR_OT_curve_toolkit_merge_by_distance,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
