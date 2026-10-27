# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Curve Offset (Object and Edit Mode)

Creates a curve parallel to every selected one, at a signed Distance: outwards
(positive) or inwards (negative) on closed curves, whichever way they turn, and
to the left or the right of the direction on open ones.

In Object Mode the originals are not modified and stay visible; the result is a
new object, "Curve Offset", with their look (bevel, fill, materials...) and
their transform.

In Edit Mode no new object is made: the offset of every selected spline goes
into the same curve, as a new spline right after the one it comes from, which
stays where it was. A spline with only some of its points selected is taken
whole (the Select Linked that one would do by hand), and only the offset is
left selected. One spline can give more than one, where Clean Overlaps cuts it
in two, and the object is never converted from 3D to 2D: the selected splines
simply have to be flat in the local XY plane.

Both Sides gives two parallels at once, one on each side, and then the sign of
the Distance means nothing. With Join Both with Arcs on top of it, the two
parallels of an *open* spline are closed at each end by a half circle of radius
equal to the Distance, so the pair comes out as a single closed curve (a closed
spline has no ends to join, and is left with its two parallels). Each half
circle is two quarters, that is one control point of its own.

Bezier curves stay Bezier: the parallel curve is approximated by cubics (extra
control points are added where one is not enough), instead of being turned into
a polyline as Blender's own offset does. Poly curves stay Poly, unless Round
corners or joining arcs are asked for, neither of which a Poly spline can hold.
As with the Booleans, this works on 2D curves (in Object Mode flat 3D curves
are turned into 2D automatically), Poly and Bezier, not NURBS.

The geometry work is done by offset_engine.py; the bridge between splines and
the segments of the engine is the one the Booleans use (see booleans.py).
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty
from mathutils import Vector

from . import curve_engine as eng
from . import offset_engine as off
from . import spline_data as sd
from .booleans import Fail, flat_in_local_xy, make_2d, segments_to_spline, spline_segments
from .context_utils import (
    EDIT_MODE,
    edit_scope,
    has_active_curve,
    link_like,
    new_curve_object,
    selected_curves,
    world_matrix,
)
from .primitives import unit_scale

OFFSET_NAME = "Curve Offset"

#: Said when Join Both with Arcs was asked for and the ends were not there.
_UNJOINED = (
    "%d spline(s) left unjoined: the Distance eats their ends away, so there "
    "is nothing for the arcs to close (lower it, or turn Clean Overlaps off)"
)


def _local_distance(obj, distance):
    """The Distance of the panel is a length in the scene; splines are offset
    in the local space of their object, so the scale has to be taken out.

    Returns (local distance, True when the scale of XY is not uniform).
    """
    mw = world_matrix(obj)
    sx = Vector((mw[0][0], mw[1][0], mw[2][0])).length
    sy = Vector((mw[0][1], mw[1][1], mw[2][1])).length
    scale = 0.5 * (sx + sy)
    if scale < 1e-9:
        return None, False
    return distance / scale, abs(sx - sy) > 1e-4 * max(sx, sy)


def _select_all(data, state=True):
    """Set the selection flags of every point of a snapshot."""
    for p in data.points:
        p.select = state
        p.select_left = p.select_right = state
    return data


def _flat_in_xy(data):
    """True when every point and handle of a snapshot has z = 0, so the
    spline can be offset in the XY plane without changing its shape."""
    coords = []
    for p in data.points:
        coords.append(p.co)
        if data.kind == 'BEZIER':
            coords += [p.hl, p.hr]
    if not coords:
        return True
    size = max(max(abs(c[0]), abs(c[1])) for c in coords)
    return all(abs(c[2]) <= 1e-6 * size + 1e-7 for c in coords)


class ETR_OT_curve_toolkit_offset(bpy.types.Operator):
    """Create a curve parallel to every selected 2D curve, at the given Distance: outwards (positive) or inwards (negative) on closed curves, to one side or the other on open ones. Both Sides gives one parallel on each side, and Join Both with Arcs then closes the two of an open curve with a half circle at each end. Bezier curves stay Bezier. In Object Mode the offset is a new object; in Edit Mode it is a new spline inside the same curve (a partly selected spline is taken whole). The originals are never modified. Poly and Bezier only (not NURBS)"""
    bl_idname = "etr.curve_toolkit_offset"
    bl_label = "Offset"
    bl_options = {'REGISTER', 'UNDO'}

    distance: FloatProperty(
        name="Distance",
        description=(
            "How far the parallel curve goes. On a closed curve, positive is "
            "outwards and negative inwards, whichever way the curve turns; on an "
            "open curve, to the left or to the right of its direction"
        ),
        default=0.1,
        soft_min=-10.0,
        soft_max=10.0,
        precision=4,
        subtype='DISTANCE',
        unit='LENGTH',
    )
    corners: EnumProperty(
        name="Corners",
        description="How the corners that open a gap are closed",
        items=(
            ('MITER', "Miter", "Prolong both sides until they meet, up to the Miter Limit"),
            ('ROUND', "Round", "An arc of radius equal to the Distance, the exact offset of the corner"),
            ('BEVEL', "Bevel", "A straight segment between the two sides"),
        ),
        default='MITER',
    )
    miter_limit: FloatProperty(
        name="Miter Limit",
        description=(
            "Longest miter, as a multiple of the Distance. A sharper corner, "
            "whose miter would shoot out further than this, gets a bevel instead"
        ),
        default=4.0,
        min=1.0,
        soft_max=20.0,
    )
    clean_overlaps: BoolProperty(
        name="Clean Overlaps",
        description=(
            "Remove the parts that fold over the curve, which appear on "
            "concavities tighter than the Distance. Turn it off to see the raw "
            "offset of every segment"
        ),
        default=True,
    )
    both_sides: BoolProperty(
        name="Both Sides",
        description=(
            "Offset every curve to both sides at once, which gives two "
            "parallels instead of one. The sign of the Distance is ignored"
        ),
        default=False,
    )
    join_arcs: BoolProperty(
        name="Join Both with Arcs",
        description=(
            "Close the two parallels of an open curve with a half circle of "
            "radius equal to the Distance at each end, so that they become a "
            "single closed curve. A closed curve has no ends to join, so "
            "nothing is added to it"
        ),
        default=False,
    )

    @classmethod
    def poll(cls, context):
        if context.mode == EDIT_MODE:
            return has_active_curve(context)
        return context.mode == 'OBJECT' and bool(selected_curves(context))

    def invoke(self, context, event):
        if not self.properties.is_property_set("distance", ghost=False):
            self.distance *= unit_scale(context)
        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "distance")
        layout.prop(self, "corners")
        row = layout.row()
        row.enabled = self.corners == 'MITER'
        row.prop(self, "miter_limit")
        layout.prop(self, "clean_overlaps")
        layout.prop(self, "both_sides")
        row = layout.row()
        row.enabled = self.both_sides
        row.prop(self, "join_arcs")

    # -- validation ----------------------------------------------------------

    def _curves(self, context):
        objs = selected_curves(context)
        if not objs:
            raise Fail("Offset needs at least one curve object selected")
        for obj in objs:
            if obj.data.dimensions != '2D' and not flat_in_local_xy(obj.data):
                raise Fail(
                    f"'{obj.name}' is a 3D curve that is not flat in its local XY plane, so it "
                    "cannot be converted to 2D automatically (Offset works with 2D curves)")
            if not len(obj.data.splines):
                raise Fail(f"'{obj.name}' has no splines")
            for spline in obj.data.splines:
                if spline.type not in ('POLY', 'BEZIER'):
                    raise Fail(
                        f"'{obj.name}' has {spline.type} splines: Offset works only with "
                        "Poly and Bezier curves")
                points = spline.bezier_points if spline.type == 'BEZIER' else spline.points
                if len(points) < 2:
                    raise Fail(f"'{obj.name}' has a spline with a single point")
        return objs

    # -- work ----------------------------------------------------------------

    def _to_splines(self, data, paths):
        """Spline snapshots of the paths the engine gave back.

        A Poly spline stays Poly while the offset is made of straight segments
        only; a Round corner or a joining arc turns it into a Bezier one, since
        an arc cannot be a Poly spline without being approximated.
        """
        out = []
        for path, closed in paths:
            poly = data.kind == 'POLY' and all(s.line for s in path)
            out.append(segments_to_spline(
                path, closed, 'POLY' if poly else 'BEZIER', data.settings))
        return out

    def _paths(self, segs, cyclic, distance, tol):
        return off.offset_path(
            segs, cyclic, distance,
            corners=self.corners,
            miter_limit=self.miter_limit,
            clean=self.clean_overlaps,
            tol=tol,
        )

    def _offset_spline(self, data, distance):
        """(spline snapshots of the offset of one spline, arcs were asked for
        but could not be built).

        There are none when nothing is left of the spline, one, or several when
        the offset cuts it in pieces - and twice as many with Both Sides.
        """
        segs, _ = spline_segments(data)
        if not segs:
            return [], False
        tol = eng.tolerances_for(eng.segs_points(segs))

        if not self.both_sides:
            return self._to_splines(data, self._paths(segs, data.cyclic, distance, tol)), False

        # With Both Sides the sign means nothing: there is one parallel on each
        # side of the curve, whichever way it turns.
        width = abs(distance)
        plus = self._paths(segs, data.cyclic, width, tol)
        minus = self._paths(segs, data.cyclic, -width, tol)

        if self.join_arcs and not data.cyclic:
            loop = off.close_both_sides(segs, plus, minus, width, tol)
            if loop is not None:
                return self._to_splines(data, [(loop, True)]), False
            # The cleaning pass cut an offset in pieces or ate an end away, so
            # there is nothing left for the half-turns to close onto.
            return self._to_splines(data, plus + minus), True

        return self._to_splines(data, plus + minus), False

    def _offset_curve(self, obj):
        """Spline snapshots of the offset of one whole curve object."""
        distance, stretched = _local_distance(obj, self.distance)
        if distance is None:
            return [], stretched, 0
        datas, unjoined = [], 0
        for data in sd.read_all(obj.data):
            pieces, missed = self._offset_spline(data, distance)
            datas += pieces
            unjoined += bool(missed)
        return datas, stretched, unjoined

    def execute(self, context):
        if context.mode == EDIT_MODE:
            return self.execute_edit(context)
        try:
            objs = self._curves(context)
        except Fail as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        if abs(self.distance) < 1e-9:
            self.report({'INFO'}, "Distance is 0: nothing to offset")
            return {'CANCELLED'}

        converted = make_2d(objs)
        created, empty, stretched = [], [], []
        unjoined = 0
        for obj in objs:
            datas, non_uniform, missed = self._offset_curve(obj)
            unjoined += missed
            if non_uniform:
                stretched.append(obj.name)
            if datas:
                created.append((new_curve_object(context, obj, datas, OFFSET_NAME), obj))
            else:
                empty.append(obj.name)

        if not created:
            self.report(
                {'WARNING'},
                "Nothing is left of the offset: the Distance is larger than the curve(s)")
            return {'CANCELLED'}

        for new_obj, source in created:
            link_like(new_obj, source, context)
        for obj in context.selected_objects:
            obj.select_set(False)
        last = None
        for new_obj, _ in created:
            try:
                new_obj.select_set(True)
                last = new_obj
            except RuntimeError:
                pass
        if last is not None:
            context.view_layer.objects.active = last

        notes = []
        if converted:
            notes.append(f"{converted} curve(s) converted from 3D to 2D")
        if empty:
            notes.append(f"nothing left of {', '.join(empty)}")
        if stretched:
            notes.append(
                f"non-uniform scale in {', '.join(stretched)}: the distance cannot be exact")
        if unjoined:
            notes.append(_UNJOINED % unjoined)
        message = f"Created {len(created)} offset curve(s)"
        if notes:
            message += " (" + "; ".join(notes) + ")"
        self.report({'WARNING'} if (empty or stretched or unjoined) else {'INFO'}, message)
        return {'FINISHED'}

    # -- Edit Mode -----------------------------------------------------------

    def _check_selected(self, obj, datas, picked):
        """Validate the splines of `obj` that are going to be offset."""
        for index in picked:
            data = datas[index]
            if data.kind not in ('POLY', 'BEZIER'):
                raise Fail(
                    f"'{obj.name}' has a {data.kind} spline selected: Offset works only "
                    "with Poly and Bezier curves")
            if len(data.points) < 2:
                raise Fail(f"'{obj.name}' has a spline with a single point selected")
            if not _flat_in_xy(data):
                raise Fail(
                    f"'{obj.name}' has a selected spline that is not flat in its local XY "
                    "plane: in Edit Mode, Offset works in the XY plane of the curve and "
                    "does not convert the object to 2D")

    def _selected_splines(self, obj):
        """(snapshots, indices of the splines to offset) of `obj`.

        A spline enters whole as soon as one of its points is selected, which
        is the Select Linked one would do by hand. Called in Object Mode,
        inside edit_scope(), so the selection flags of the points have already
        been flushed to the data.
        """
        datas = sd.read_all(obj.data)
        picked = [i for i, d in enumerate(datas)
                  if any(sd.point_selected(p, d.kind) for p in d.points)]
        if picked:
            self._check_selected(obj, datas, picked)
        return datas, picked

    def _offset_in_place(self, obj, datas, picked):
        """Replace the selected splines of `obj` by their offset.

        Returns (splines offset, splines left as they were, non-uniform scale,
        splines whose arcs could not be built).
        """
        distance, non_uniform = _local_distance(obj, self.distance)
        if distance is None:
            return 0, 0, non_uniform, 0

        result, done, lost, unjoined = [], 0, 0, 0
        for index, data in enumerate(datas):
            if index not in picked:
                result.append(data)
                continue
            pieces, missed = self._offset_spline(data, distance)
            unjoined += bool(missed)
            if not pieces:
                # The Distance eats the whole spline: leave it as it was.
                result.append(data)
                lost += 1
                continue
            # The original stays where it is, and the offset goes in right
            # after it. Only the offset is left selected.
            result.append(_select_all(data, False))
            result += [_select_all(p) for p in pieces]
            done += 1
        if done:
            sd.replace_splines(obj.data, result)
        return done, lost, non_uniform, unjoined

    def execute_edit(self, context):
        if abs(self.distance) < 1e-9:
            self.report({'INFO'}, "Distance is 0: nothing to offset")
            return {'CANCELLED'}

        done = lost = unjoined = 0
        stretched = []
        with edit_scope(context) as objs:
            if not objs:
                self.report({'ERROR'}, "Offset needs a curve in Edit Mode")
                return {'CANCELLED'}
            # Everything is read and validated before anything is written, so
            # that a curve that cannot be offset leaves the rest untouched.
            plans = []
            try:
                for obj in objs:
                    datas, picked = self._selected_splines(obj)
                    if picked:
                        plans.append((obj, datas, picked))
            except Fail as exc:
                self.report({'ERROR'}, str(exc))
                return {'CANCELLED'}
            if not plans:
                self.report({'WARNING'}, "Select the spline(s) to offset")
                return {'CANCELLED'}
            for obj, datas, picked in plans:
                count, missing, non_uniform, missed = self._offset_in_place(
                    obj, datas, picked)
                done += count
                lost += missing
                unjoined += missed
                if non_uniform and count:
                    stretched.append(obj.name)

        if not done:
            self.report(
                {'WARNING'},
                "Nothing is left of the offset: the Distance is larger than the "
                "selected spline(s)")
            return {'CANCELLED'}

        notes = []
        if lost:
            notes.append(f"{lost} spline(s) left as they were (the Distance is larger)")
        if stretched:
            notes.append(
                f"non-uniform scale in {', '.join(stretched)}: the distance cannot be exact")
        if unjoined:
            notes.append(_UNJOINED % unjoined)
        message = f"Offset {done} spline(s)"
        if notes:
            message += " (" + "; ".join(notes) + ")"
        self.report({'WARNING'} if notes else {'INFO'}, message)
        return {'FINISHED'}


# -----------------------------------------------------------------------------

classes = (ETR_OT_curve_toolkit_offset,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
