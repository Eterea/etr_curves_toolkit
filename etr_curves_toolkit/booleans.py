# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Booleans & Splits (Object Mode and Edit Mode)

Booleans (Union, Intersection, Difference)
    2D boolean operations between closed Poly or Bezier shapes.
      - Object Mode: each selected object must be a 2D curve whose splines
        are all closed. An object with several splines (a shape with holes,
        or several islands) is one region, even-odd, the way Blender fills
        it. The result is a new object (Bool_Union_01, Bool_Inter_01,
        Bool_Diff_01...) with the look of the active object; the originals
        are hidden, never modified.
      - Edit Mode: the selected closed splines of one curve (one selected
        point of a spline is enough), each one a shape of its own. The
        result replaces them in that same curve, selected; the other splines
        are left alone. With "Backup Splines in Edit Mode" the splines that
        are replaced are kept, as a hidden object "Backup_<name>".
      - Union: any number. Intersection: exactly two.
      - Difference: exactly two; the active one (the active spline, in Edit
        Mode) bites the other one, and Toggle Goal (F9) swaps them.
    If every operand is Poly the result is Poly; otherwise it is Bezier (Poly
    parts get Vector handles, as Set Spline Type does).

Splits (Split Active, Split All)
    Cut open and closed Poly or Bezier splines where they cross.
      - Object Mode: every piece becomes a new object (Split_01, Split_02...)
        and all the selected originals are hidden.
          Split Active: only the active curve is cut (by all the others).
          Split All: every selected curve is cut by all the others, and every
          spline also where it crosses itself (a loop) or another spline of
          the same curve, so a single looping curve can be split on its own.
          It needs no active object (a Select All or a box selection leaves
          none).
      - Edit Mode: the selected splines of one curve. The pieces replace the
        spline(s) that are cut, selected, in the same curve.
          Split Active: one of the selected splines, Goal (F9), is cut by
          the others. Goal starts at the active spline (the one of the point
          clicked last) when it is selected, otherwise at 0.
          Split All: every selected spline is cut by the others and by
          itself.

The curves may be anywhere in space and rotated, as long as they all lie in
the same plane: in Object Mode they are brought into the local space of the
active object and checked there, and 3D curves that are flat in their local
XY plane are turned into 2D curves automatically. In Edit Mode the selected
splines must lie flat in the local XY plane of their curve. Optionally,
sources (or backups) and results are placed in the collections "Curve Boolean
Sources" and "Curve Boolean Results" (see context_utils). The geometry work is
done by curve_engine.py.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty
from mathutils import Vector

from . import curve_engine as eng
from . import geometry as geo
from . import spline_data as sd
from .context_utils import (
    EDIT_MODE,
    backup_splines,
    curves_in_edit_mode,
    edit_scope,
    finish_sources_and_results,
    has_active_curve,
    new_curve_object,
    selected_curves,
    world_matrix,
    write_edit_result,
)

#: Base name of the pieces of the Splits (Split_01, Split_02...).
SPLIT_NAME = "Split"


class Fail(Exception):
    """Validation error: its message is reported and nothing is changed."""


# -----------------------------------------------------------------------------
# Splines <-> engine segments
#
# Shared with the Curve Offset (offset.py), which reads and writes splines the
# same way: spline_segments(), segments_to_spline(), flat_in_local_xy(),
# make_2d() and Fail.
# -----------------------------------------------------------------------------

def spline_segments(data, matrix=None):
    """Engine segments of a spline snapshot.

    matrix: optional Matrix applied to the local points (x, y, 0). Returns
    (segments, largest |z| after the transform)."""
    pts = data.points
    n = len(pts)
    max_z = 0.0

    def tr(co):
        nonlocal max_z
        v = Vector((co[0], co[1], 0.0))
        if matrix is not None:
            v = matrix @ v
        max_z = max(max_z, abs(v.z))
        return (v.x, v.y)

    segs = []
    for i in range(n if data.cyclic else n - 1):
        a, b = pts[i], pts[(i + 1) % n]
        if data.kind == 'BEZIER':
            line = geo.is_straight_segment(a.co, a.hr, b.hl, b.co)
            segs.append(eng.Seg(tr(a.co), tr(a.hr), tr(b.hl), tr(b.co), line, (a, 'R'), (b, 'L')))
        else:
            segs.append(eng.line_seg(tr(a.co), tr(b.co), (a, 'R'), (b, 'L')))
    return segs, max_z


def _side_type(orig, meta, seg, other):
    """Handle type for the side of a point that goes along `seg`."""
    if seg is None:
        return 'FREE'
    if seg.line:
        return 'VECTOR'
    if orig is None or meta is None:
        return 'FREE'
    t = orig.hlt if meta[1] == 'L' else orig.hrt
    if t in ('AUTO', 'ALIGNED'):
        # Still aligned (cuts keep the direction of the handles), unless the
        # other side is a straight line with a Vector handle.
        return 'FREE' if (other is not None and other.line) else 'ALIGNED'
    return 'FREE'


def _xy(co):
    return (co[0], co[1], 0.0)


def segments_to_spline(segs, cyclic, kind, settings):
    """SplineData from engine segments (2D, z = 0).

    Original points that reach the result untouched keep their radius, tilt,
    weight and (when it is still valid) their handle type; points created by
    the cuts are corners with Free handles. Straight sides get Vector handles.
    """
    n = len(segs)
    out = sd.SplineData(kind, [], cyclic, dict(settings))
    for i in range(n if cyclic else n + 1):
        prev = segs[i - 1] if (i > 0 or cyclic) else None
        nxt = segs[i] if i < n else None
        m_in = prev.m1 if prev is not None else None
        m_out = nxt.m0 if nxt is not None else None

        if m_in and m_out and m_in[0] is m_out[0]:
            orig = m_in[0]
        elif prev is None and m_out:
            orig = m_out[0]
        elif nxt is None and m_in:
            orig = m_in[0]
        else:
            orig = None
        base = orig or (m_out or m_in or (None,))[0]
        q = sd.replace(base) if base is not None else sd.PointData(co=(0.0, 0.0, 0.0))
        co = nxt.p0 if nxt is not None else prev.p1
        q.co = _xy(co)
        q.w = 1.0
        q.select = q.select_left = q.select_right = False

        if kind == 'BEZIER':
            q.hlt = _side_type(orig, m_in, prev, nxt)
            q.hrt = _side_type(orig, m_out, nxt, prev)
            q.hl = _xy(prev.h1) if prev is not None else None
            q.hr = _xy(nxt.h0) if nxt is not None else None
            # Outer handle of an open end: the original one, or none.
            if q.hl is None:
                q.hl, q.hlt = _outer_handle(orig, m_out, q.co, nxt)
            if q.hr is None:
                q.hr, q.hrt = _outer_handle(orig, m_in, q.co, prev)
        out.points.append(q)
    return out


def _outer_handle(orig, inner_meta, co, inner_seg):
    if orig is None or inner_meta is None:
        return co, 'FREE'
    # The outer side is the opposite of the side used by the inner segment.
    if inner_meta[1] == 'R':
        h, t = orig.hl, orig.hlt
    else:
        h, t = orig.hr, orig.hrt
    if h is None:
        # The original point is a Poly point, which has no handles. A Vector
        # handle is recomputed by Blender from the neighbour (as Set Spline
        # Type does), so where it is stored does not matter.
        return co, 'VECTOR' if (inner_seg is not None and inner_seg.line) else 'FREE'
    if t == 'VECTOR' and inner_seg is not None and inner_seg.line:
        return _xy(h), 'VECTOR'
    return _xy(h), 'FREE'


# -----------------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------------

def _validate(context, title, min_count, max_count, closed_only, need_active=True):
    """Selected curve objects and active object, or raise Fail.

    With need_active=False the selection may have no active object (after a
    Select All or a box selection): the first selected curve stands in for it,
    as the reference space.
    """
    objs = selected_curves(context)
    if not objs:
        raise Fail(f"{title} needs at least {min_count} curve object(s) selected")
    active = context.active_object
    if active not in objs:
        if need_active:
            raise Fail(f"{title}: the active object must be one of the selected curves")
        active = objs[0]
    if len(objs) < min_count:
        raise Fail(f"{title} needs at least {min_count} curve objects selected")
    if max_count and len(objs) > max_count:
        raise Fail(f"{title} works with exactly {max_count} curve objects")
    for obj in objs:
        if obj.data.dimensions != '2D' and not flat_in_local_xy(obj.data):
            raise Fail(
                f"'{obj.name}' is a 3D curve that is not flat in its local XY plane, so it "
                f"cannot be converted to 2D automatically ({title} works with 2D curves)")
        splines = obj.data.splines
        if not len(splines):
            raise Fail(f"'{obj.name}' has no splines")
        for s in splines:
            if s.type not in ('POLY', 'BEZIER'):
                raise Fail(f"'{obj.name}' has {s.type} splines: {title} works only with Poly and Bezier curves")
            if len(s.bezier_points if s.type == 'BEZIER' else s.points) < 2:
                raise Fail(f"'{obj.name}' has a spline with a single point")
        if closed_only and not all(s.use_cyclic_u for s in splines):
            raise Fail(f"'{obj.name}' has open splines: {title} works only with closed "
                       "(Cyclic) splines")
    return objs, active


def flat_in_local_xy(curve):
    """True if every point and handle of the curve has z = 0 (so turning it
    into a 2D curve does not change its shape)."""
    coords = []
    for s in curve.splines:
        if s.type == 'BEZIER':
            for p in s.bezier_points:
                coords += [p.co, p.handle_left, p.handle_right]
        else:
            coords += [p.co for p in s.points]
    if not coords:
        return True
    size = max(max(abs(c[0]), abs(c[1])) for c in coords)
    return all(abs(c[2]) <= 1e-6 * size + 1e-7 for c in coords)


def make_2d(objs):
    """Turn the (flat) 3D curves into 2D curves. Returns how many changed."""
    changed = 0
    for curve in {o.data for o in objs}:
        if curve.dimensions != '2D':
            curve.dimensions = '2D'
            changed += 1
    return changed


def _to_active_space(objs, active):
    """Engine segments of every spline, in the 2D space of the active object.

    Returns ({object: [(SplineData, segments), ...]}, Tolerances). Raises
    Fail if the curves are not in the same plane."""
    try:
        to_ref = world_matrix(active).inverted()
    except ValueError:
        raise Fail(f"'{active.name}' has a degenerate transform (zero scale)")
    per_obj = {}
    max_z = 0.0
    for obj in objs:
        m = to_ref @ world_matrix(obj)
        items = []
        for d in sd.read_all(obj.data):
            segs, z = spline_segments(d, m)
            max_z = max(max_z, z)
            items.append((d, segs))
        per_obj[obj] = items
    tol = eng.tolerances_for(
        p for items in per_obj.values() for _, segs in items for p in eng.segs_points(segs))
    if max_z > 1e-5 * tol.scale + 1e-6:
        raise Fail(
            "The curves are not in the same plane (different height or rotation). "
            "They must lie in one common plane")
    return per_obj, tol


def _converted_note(count):
    return f" ({count} curve(s) converted from 3D to 2D)" if count else ""


# -----------------------------------------------------------------------------
# Edit Mode: the selected splines of one curve
# -----------------------------------------------------------------------------

def active_spline_indices(context):
    """{object name: index of its active spline (the one of the point clicked
    last), or None}, for the curves in Edit Mode. Read it in Edit Mode, before
    edit_scope()."""
    out = {}
    for obj in curves_in_edit_mode(context):
        active = obj.data.splines.active
        out[obj.name] = None
        if active is not None:
            for i, spline in enumerate(obj.data.splines):
                if spline == active:
                    out[obj.name] = i
                    break
    return out


def picked_in_edit(objs, title):
    """(object, snapshots of all its splines, indices of the picked ones): the
    splines with a selected point (a handle is enough), which must all be in
    one curve. Raises Fail."""
    found = []
    for obj in objs:
        datas = sd.read_all(obj.data)
        picked = [i for i, d in enumerate(datas)
                  if any(sd.point_selected(p, d.kind) for p in d.points)]
        if picked:
            found.append((obj, datas, picked))
    if not found:
        raise Fail(f"{title}: select the splines to use (one point of each is enough)")
    if len(found) > 1:
        raise Fail(f"{title}: in Edit Mode the selected splines must be in one curve "
                   f"({len(found)} curves have selected points)")
    return found[0]


def check_edit_splines(obj, datas, picked, title, closed_only):
    """Raise Fail unless every picked spline can take part: Poly or Bezier,
    two points or more, closed (with closed_only), and all of them flat in the
    local XY plane of the curve."""
    for i in picked:
        d = datas[i]
        if d.kind not in ('POLY', 'BEZIER'):
            raise Fail(f"{title}: a selected spline of '{obj.name}' is {d.kind}; it works "
                       "only with Poly and Bezier splines")
        if len(d.points) < 2:
            raise Fail(f"{title}: a selected spline of '{obj.name}' has a single point "
                       "(deselect the stray points)")
        if closed_only and not d.cyclic:
            raise Fail(f"{title}: a selected spline of '{obj.name}' is open; it works only "
                       "with closed (Cyclic) splines")
    coords = []
    for i in picked:
        for p in datas[i].points:
            coords += [p.co] if p.hl is None else [p.co, p.hl, p.hr]
    size = max(max(abs(c[0]), abs(c[1])) for c in coords)
    if any(abs(c[2]) > 1e-6 * size + 1e-7 for c in coords):
        raise Fail(f"{title}: the selected splines must lie flat in the local XY plane of "
                   f"'{obj.name}'")


def edit_goal(picked, active_index):
    """Position, among the picked splines, of the active spline, or None."""
    if active_index is not None and active_index in picked:
        return picked.index(active_index)
    return None


def _edit_tolerances(datas, picked):
    segs = {i: spline_segments(datas[i])[0] for i in picked}
    tol = eng.tolerances_for(p for i in picked for p in eng.segs_points(segs[i]))
    return segs, tol


# -----------------------------------------------------------------------------
# Curve Booleans
# -----------------------------------------------------------------------------

#: operation: (title, name of the result, least count, most count (0: any),
#: description)
_BOOLEAN_INFO = {
    'UNION': ("Union", "Bool_Union", 2, 0,
              "Union of the selected closed curves (any number). Object Mode: a new curve "
              "and the originals are hidden. Edit Mode: of the selected splines of one "
              "curve, in that curve. Poly or Bezier, in one plane"),
    'INTERSECTION': ("Intersection", "Bool_Inter", 2, 2,
                     "Intersection of two closed curves. Object Mode: a new curve and the "
                     "originals are hidden. Edit Mode: of two selected splines of one curve, "
                     "in that curve. Poly or Bezier, in one plane"),
    'DIFFERENCE': ("Difference", "Bool_Diff", 2, 2,
                   "One closed curve bites the other (the active one, by default; Toggle "
                   "Goal in F9 swaps them). Object Mode: a new curve and the originals are "
                   "hidden. Edit Mode: two selected splines of one curve, in that curve"),
}


def _boolean_poll(cls, context):
    if context.mode == 'OBJECT' and len(selected_curves(context)) >= 2:
        return True
    if context.mode == EDIT_MODE and has_active_curve(context):
        return True
    cls.poll_message_set("Select two or more closed curves (Object Mode), or closed splines "
                         "of one curve (Edit Mode)")
    return False


class _BooleanBase:
    """The work of the Boolean operators; `operation` is a property of each."""

    bl_options = {'REGISTER', 'UNDO'}

    toggle_goal: BoolProperty(
        name="Toggle Goal",
        description="Difference: swap the curves (or splines), so the one that was bitten "
                    "bites the other",
        default=False,
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return _boolean_poll(cls, context)

    def draw(self, context):
        layout = self.layout
        if self.operation == 'DIFFERENCE':
            layout.use_property_split = True
            layout.use_property_decorate = False
            layout.prop(self, "toggle_goal")

    def execute(self, context):
        title = _BOOLEAN_INFO[self.operation][0]
        try:
            if context.mode == EDIT_MODE:
                return self._edit(context, title)
            return self._object(context, title)
        except Fail as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

    def _empty(self, title):
        """No result. A Difference finishes anyway (nothing changed), so its
        F9 panel opens and Toggle Goal can be tried."""
        if self.operation == 'DIFFERENCE':
            self.report({'WARNING'}, f"{title}: the result is empty (the bitten one is "
                                     "covered by the other). Try Toggle Goal in the F9 panel")
            return {'FINISHED'}
        raise Fail(f"{title}: the result is empty (do the curves overlap?)")

    def _loops(self, regions, biter):
        """Contours of the result. regions: one list of loops per operand;
        biter: index of the one that bites, for a Difference."""
        tol = self._tol
        if self.operation == 'UNION':
            return eng.union_all(regions, tol)
        if self.operation == 'INTERSECTION':
            return eng.boolean(regions[0], regions[1], 'INTERSECTION', tol)
        return eng.boolean(regions[1 - biter], regions[biter], 'DIFFERENCE', tol)

    # -- Object Mode ---------------------------------------------------------

    def _object(self, context, title):
        _, name, min_n, max_n, _ = _BOOLEAN_INFO[self.operation]
        objs, active = _validate(context, title, min_n, max_n, closed_only=True)
        per_obj, self._tol = _to_active_space(objs, active)

        # Every spline of an object is one loop of its region: a curve with
        # holes (two nested splines) or with several islands counts as one
        # shape, even-odd, the way Blender fills it.
        order = [active] + [o for o in objs if o is not active]
        regions = [[segs for _, segs in per_obj[o]] for o in order]
        # The active curve bites (index 0), unless Toggle Goal.
        loops = self._loops(regions, 1 if self.toggle_goal else 0)
        if not loops:
            return self._empty(title)

        all_poly = all(d.kind == 'POLY' for o in objs for d, _ in per_obj[o])
        kind = 'POLY' if all_poly else 'BEZIER'
        settings = dict(per_obj[active][0][0].settings)
        datas = [segments_to_spline(loop, True, kind, settings) for loop in loops]

        converted = make_2d(objs)
        result = new_curve_object(context, active, datas, name, numbered=True)
        finish_sources_and_results(context, objs, [(result, active)])
        self.report({'INFO'}, f"{title}: {len(loops)} contour(s)" + _converted_note(converted))
        return {'FINISHED'}

    # -- Edit Mode -----------------------------------------------------------

    def _edit(self, context, title):
        _, _, min_n, max_n, _ = _BOOLEAN_INFO[self.operation]
        actives = active_spline_indices(context)
        with edit_scope(context) as objs:
            obj, datas, picked = picked_in_edit(objs, title)
            if len(picked) < min_n:
                raise Fail(f"{title} needs at least {min_n} closed splines selected")
            if max_n and len(picked) > max_n:
                raise Fail(f"{title} works with exactly {max_n} closed splines "
                           f"({len(picked)} selected)")
            check_edit_splines(obj, datas, picked, title, closed_only=True)
            segs, self._tol = _edit_tolerances(datas, picked)

            # Each spline is one operand. The active spline bites, when it is
            # one of the two; otherwise the first one. Toggle Goal swaps them.
            biter = edit_goal(picked, actives.get(obj.name)) or 0
            if self.toggle_goal:
                biter = 1 - biter
            loops = self._loops([[segs[i]] for i in picked], biter)
            if not loops:
                return self._empty(title)

            kind = 'POLY' if all(datas[i].kind == 'POLY' for i in picked) else 'BEZIER'
            settings = dict(datas[picked[biter if max_n else 0]].settings)
            results = [segments_to_spline(loop, True, kind, settings) for loop in loops]
            backup_splines(context, obj, [datas[i] for i in picked])
            write_edit_result(obj, datas, picked, results)
        self.report({'INFO'}, f"{title}: {len(loops)} contour(s)")
        return {'FINISHED'}


class ETR_OT_curve_toolkit_boolean(_BooleanBase, bpy.types.Operator):
    """2D boolean operation between closed curves (Object Mode) or closed splines of one curve (Edit Mode)"""
    bl_idname = "etr.curve_toolkit_boolean"
    bl_label = "Curve Boolean"

    operation: EnumProperty(
        name="Operation",
        items=(
            ('UNION', "Union", ""),
            ('INTERSECTION', "Intersection", ""),
            ('DIFFERENCE', "Difference", ""),
        ),
        default='UNION',
    )

    @classmethod
    def description(cls, context, properties):
        return _BOOLEAN_INFO[properties.operation][4]


def _fixed_operation(identifier):
    return EnumProperty(
        name="Operation",
        items=((identifier, _BOOLEAN_INFO[identifier][0], ""),),
        default=identifier,
        options={'HIDDEN'},
    )


# The buttons of the panel: the same operator, one per operation, so that the
# tooltip and the F9 panel carry the name of the operation.

class ETR_OT_curve_toolkit_boolean_union(_BooleanBase, bpy.types.Operator):
    bl_idname = "etr.curve_toolkit_boolean_union"
    bl_label = "Union"
    bl_description = _BOOLEAN_INFO['UNION'][4]
    operation: _fixed_operation('UNION')


class ETR_OT_curve_toolkit_boolean_intersection(_BooleanBase, bpy.types.Operator):
    bl_idname = "etr.curve_toolkit_boolean_intersection"
    bl_label = "Intersection"
    bl_description = _BOOLEAN_INFO['INTERSECTION'][4]
    operation: _fixed_operation('INTERSECTION')


class ETR_OT_curve_toolkit_boolean_difference(_BooleanBase, bpy.types.Operator):
    bl_idname = "etr.curve_toolkit_boolean_difference"
    bl_label = "Difference"
    bl_description = _BOOLEAN_INFO['DIFFERENCE'][4]
    operation: _fixed_operation('DIFFERENCE')


# -----------------------------------------------------------------------------
# Curve Splits
# -----------------------------------------------------------------------------

_SPLIT_INFO = {
    'ACTIVE': ("Split Active",
               "Cut the active curve where it crosses the other selected ones. Object Mode: "
               "every piece becomes a new object and the originals are hidden. Edit Mode: "
               "one of the selected splines (Goal in F9) is cut by the others. Poly or "
               "Bezier, in one plane"),
    'ALL': ("Split All",
            "Cut every selected curve where it crosses the others and itself (a loop). "
            "Object Mode: every piece becomes a new object and the originals are hidden; "
            "no active object needed. Edit Mode: the selected splines of one curve. Poly "
            "or Bezier, in one plane"),
}


class _SplitBase:
    """The work of both split operators; `mode` is a property of each."""

    goal: IntProperty(
        name="Goal",
        description="Edit Mode: which of the selected splines is cut by the others, "
                    "counted from 0 in the order of the curve (up to their number minus "
                    "1). It starts at the active spline (the one of the point clicked "
                    "last), or at 0",
        default=0,
        min=0,
        options={'SKIP_SAVE'},
    )

    def draw(self, context):
        layout = self.layout
        if self.mode == 'ACTIVE' and context.mode == EDIT_MODE:
            layout.use_property_split = True
            layout.use_property_decorate = False
            layout.prop(self, "goal")

    def execute(self, context):
        title = _SPLIT_INFO[self.mode][0]
        try:
            if context.mode == EDIT_MODE:
                return self._edit(context, title)
            return self._object(context, title)
        except Fail as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

    # -- Object Mode ---------------------------------------------------------

    def _object(self, context, title):
        split_all = self.mode == 'ALL'
        if split_all:
            objs, active = _validate(context, title, 1, 0, closed_only=False,
                                     need_active=False)
        else:
            objs, active = _validate(context, title, 2, 0, closed_only=False)
        per_obj, tol = _to_active_space(objs, active)

        # One engine path per spline. Split Active: the owner is the object,
        # so splines of the same object do not cut each other. Split All:
        # every spline is its own owner and is also cut where it crosses
        # itself, so everything is cut by everything.
        paths, sources = [], []
        for obj in objs:
            for d, segs in per_obj[obj]:
                owner = len(paths) if split_all else obj.name
                paths.append(eng.Path(segs, d.cyclic, owner))
                sources.append((obj, d))
        targets = [i for i, (obj, _) in enumerate(sources)
                   if split_all or obj is active]
        intervals = eng.split_intervals(paths, targets, tol, self_cuts=split_all)

        if all(intervals[i] is None for i in targets):
            self.report({'WARNING'}, f"{title}: the curves do not cross each other"
                        + (" nor themselves" if split_all else ""))
            return {'CANCELLED'}

        pieces = []   # (source object, SplineData)
        for i in targets:
            obj, d = sources[i]
            pieces += [(obj, piece) for piece in _pieces(d, intervals[i])]

        converted = make_2d(objs)
        created = [(new_curve_object(context, obj, [data], SPLIT_NAME, numbered=True), obj)
                   for obj, data in pieces]
        finish_sources_and_results(context, objs, created)
        self.report({'INFO'}, f"{title}: {len(created)} piece(s)" + _converted_note(converted))
        return {'FINISHED'}

    # -- Edit Mode -----------------------------------------------------------

    def _edit(self, context, title):
        split_all = self.mode == 'ALL'
        actives = active_spline_indices(context)
        with edit_scope(context) as objs:
            obj, datas, picked = picked_in_edit(objs, title)
            if not split_all and len(picked) < 2:
                raise Fail(f"{title} needs at least 2 splines selected: one is cut by the "
                           "others")
            check_edit_splines(obj, datas, picked, title, closed_only=False)
            segs, tol = _edit_tolerances(datas, picked)

            # Every spline is its own owner, so the splines of the curve cut
            # each other.
            paths = [eng.Path(segs[i], datas[i].cyclic, k) for k, i in enumerate(picked)]
            if split_all:
                targets = list(range(len(picked)))
            else:
                if not self.properties.is_property_set("goal"):
                    self.goal = edit_goal(picked, actives.get(obj.name)) or 0
                # A hard limit: a property cannot have a maximum that changes
                # with the selection, so a Goal past the last spline is put
                # back on it, and the F9 field shows that.
                if self.goal > len(picked) - 1:
                    self.goal = len(picked) - 1
                targets = [self.goal]
            intervals = eng.split_intervals(paths, targets, tol, self_cuts=split_all)

            if all(intervals[k] is None for k in targets):
                if split_all:
                    raise Fail(f"{title}: the selected splines do not cross each other "
                               "nor themselves")
                # Nothing changed, but it finishes, so the Goal can be changed
                # in the F9 panel.
                self.report({'WARNING'}, f"{title}: spline {targets[0]} (Goal) is not "
                                         "crossed by the others. Change the Goal in the "
                                         "F9 panel")
                return {'FINISHED'}

            results = []
            for k in targets:
                results += _pieces(datas[picked[k]], intervals[k])
            changed = [picked[k] for k in targets]
            backup_splines(context, obj, [datas[i] for i in changed])
            write_edit_result(obj, datas, changed, results)
        self.report({'INFO'}, f"{title}: {len(results)} piece(s)")
        return {'FINISHED'}


def _pieces(data, intervals):
    """The pieces of a spline cut at `intervals` (or the spline itself)."""
    if intervals is None:
        return [data.copy()]
    local, _ = spline_segments(data)
    out = []
    for g0, g1 in intervals:
        segs = eng.extract(local, data.cyclic, g0, g1)
        if segs:
            out.append(segments_to_spline(segs, False, data.kind, data.settings))
    return out


def _split_poll(cls, context, least):
    if context.mode == 'OBJECT' and len(selected_curves(context)) >= least:
        return True
    if context.mode == EDIT_MODE and has_active_curve(context):
        return True
    cls.poll_message_set(f"Select {least} or more curves (Object Mode), or splines of one "
                         "curve (Edit Mode)")
    return False


# -----------------------------------------------------------------------------

class ETR_OT_curve_toolkit_split(_SplitBase, bpy.types.Operator):
    """Cut 2D curves where they cross each other"""
    bl_idname = "etr.curve_toolkit_split"
    bl_label = "Split Active"
    bl_options = {'REGISTER', 'UNDO'}

    mode: EnumProperty(
        name="Mode",
        items=(
            ('ACTIVE', "Split Active", ""),
            ('ALL', "Split All", ""),
        ),
        default='ACTIVE',
    )

    @classmethod
    def description(cls, context, properties):
        return _SPLIT_INFO[properties.mode][1]

    @classmethod
    def poll(cls, context):
        return _split_poll(cls, context, 2)


class ETR_OT_curve_toolkit_split_all(_SplitBase, bpy.types.Operator):
    """Cut every selected curve where it crosses the others and itself (a loop). Object Mode: every piece becomes a new object and the originals are hidden; no active object needed. Edit Mode: the selected splines of one curve. Poly or Bezier, in one plane"""
    bl_idname = "etr.curve_toolkit_split_all"
    bl_label = "Split All"
    bl_options = {'REGISTER', 'UNDO'}

    # The button of the panel. Same operator as Curve Split with Mode = All,
    # with a poll of its own: one curve is enough, since a loop can split
    # itself (Split Active still needs two).
    mode: EnumProperty(
        name="Mode",
        items=(('ALL', "Split All", ""),),
        default='ALL',
        options={'HIDDEN'},
    )

    @classmethod
    def description(cls, context, properties):
        return _SPLIT_INFO['ALL'][1]

    @classmethod
    def poll(cls, context):
        return _split_poll(cls, context, 1)


classes = (
    ETR_OT_curve_toolkit_boolean,
    ETR_OT_curve_toolkit_boolean_union,
    ETR_OT_curve_toolkit_boolean_intersection,
    ETR_OT_curve_toolkit_boolean_difference,
    ETR_OT_curve_toolkit_split,
    ETR_OT_curve_toolkit_split_all,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
