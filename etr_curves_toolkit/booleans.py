# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Curve Booleans and Curve Splits (Object Mode)

Curve Booleans (Union, Intersection, Difference)
    2D boolean operations between closed curve objects: each selected object
    must be a 2D curve whose splines are all closed Poly or Bezier ones. An
    object with several splines (a shape with holes, or several islands) is
    one region, even-odd, the way Blender fills it. The result
    is a new object, "Curve Boolean", with the look of the active object; the
    originals are hidden, never modified.
      - Union: any number of curves.
      - Intersection: exactly two curves.
      - Difference: exactly two curves; the active one bites the other one.
    If every curve is Poly the result is Poly; otherwise it is Bezier (Poly
    parts get Vector handles, as Set Spline Type does).

Curve Splits (Split Active, Split All)
    Cut curves where they cross other selected curves. Open and closed Poly or
    Bezier splines, in 2D curve objects. Every piece becomes a new object
    (Split_01, Split_02...) and all the selected originals are hidden.
      - Split Active: only the active curve is cut (by all the others).
      - Split All: every selected curve is cut by all the others, and every
        spline also where it crosses itself (a loop) or another spline of the
        same curve, so a single looping curve can be split on its own. It
        needs no active object (a Select All or a box selection leaves none).

The curves may be anywhere in space and rotated, as long as they all lie in
the same plane: they are brought into the local space of the active object
and checked there. 3D curves that are flat in their local XY plane are turned
into 2D curves automatically. Optionally, sources and results are placed in
the collections "Curve Boolean Sources" and "Curve Boolean Results" (see
context_utils.finish_sources_and_results). The geometry work is done by
curve_engine.py.
"""

import bpy
from bpy.props import EnumProperty
from mathutils import Vector

from . import curve_engine as eng
from . import geometry as geo
from . import spline_data as sd
from .context_utils import (
    finish_sources_and_results,
    new_curve_object,
    selected_curves,
    world_matrix,
)

BOOLEAN_NAME = "Curve Boolean"
SPLIT_PREFIX = "Split_"


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
# Curve Booleans
# -----------------------------------------------------------------------------

_BOOLEAN_INFO = {
    'UNION': ("Union", 2, 0,
              "Union of the selected closed 2D curves (any number). The result is a new "
              "'Curve Boolean' object and the originals are hidden. All the curves must be "
              "closed, Poly or Bezier, and lie in the same plane (flat 3D curves are "
              "converted to 2D)"),
    'INTERSECTION': ("Intersection", 2, 2,
                     "Intersection of two closed 2D curves. The result is a new 'Curve Boolean' "
                     "object and the originals are hidden. Both curves must be closed, Poly "
                     "or Bezier, and lie in the same plane (flat 3D curves are converted to 2D)"),
    'DIFFERENCE': ("Difference", 2, 2,
                   "The active curve bites the other selected one (two closed 2D curves). The "
                   "result is a new 'Curve Boolean' object and the originals are hidden. Both "
                   "curves must be closed, Poly or Bezier, and lie in the same plane (flat 3D "
                   "curves are converted to 2D)"),
}


class ETR_OT_curve_toolkit_boolean(bpy.types.Operator):
    """2D boolean operation between closed curves"""
    bl_idname = "etr.curve_toolkit_boolean"
    bl_label = "Curve Boolean"
    bl_options = {'REGISTER', 'UNDO'}

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
        return _BOOLEAN_INFO[properties.operation][3]

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and len(selected_curves(context)) >= 2

    def execute(self, context):
        title, min_n, max_n, _ = _BOOLEAN_INFO[self.operation]
        try:
            objs, active = _validate(context, title, min_n, max_n, closed_only=True)
            per_obj, tol = _to_active_space(objs, active)
        except Fail as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        # Every spline of an object is one loop of its region: a curve with
        # holes (two nested splines) or with several islands counts as one
        # shape, even-odd, the way Blender fills it.
        region = {o: [segs for _, segs in per_obj[o]] for o in objs}
        others = [o for o in objs if o is not active]
        if self.operation == 'UNION':
            loops = eng.union_all([region[active]] + [region[o] for o in others], tol)
        elif self.operation == 'INTERSECTION':
            loops = eng.boolean(region[others[0]], region[active], 'INTERSECTION', tol)
        else:
            loops = eng.boolean(region[others[0]], region[active], 'DIFFERENCE', tol)

        if not loops:
            self.report({'ERROR'}, f"{title}: the result is empty (do the curves overlap?)")
            return {'CANCELLED'}

        all_poly = all(d.kind == 'POLY' for o in objs for d, _ in per_obj[o])
        kind = 'POLY' if all_poly else 'BEZIER'
        settings = dict(per_obj[active][0][0].settings)
        datas = [segments_to_spline(loop, True, kind, settings) for loop in loops]

        converted = make_2d(objs)
        result = new_curve_object(context, active, datas, BOOLEAN_NAME)
        finish_sources_and_results(context, objs, [(result, active)])
        self.report({'INFO'}, f"{title}: {len(loops)} contour(s)" + _converted_note(converted))
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Curve Splits
# -----------------------------------------------------------------------------

_SPLIT_INFO = {
    'ACTIVE': ("Split Active",
               "Cut the active curve where it crosses the other selected curves. Every piece "
               "becomes a new object and all the selected originals are hidden. Poly or "
               "Bezier curves, open or closed, in the same plane (flat 3D curves are "
               "converted to 2D)"),
    'ALL': ("Split All",
            "Cut every selected curve where it crosses the others and where it crosses "
            "itself (a loop), so a single curve can be split too. Every piece becomes a new "
            "object and the originals are hidden. No active object needed. Poly or Bezier, "
            "in the same plane"),
}


class _SplitBase:
    """The work of both split operators; `mode` is a property of each."""

    def execute(self, context):
        split_all = self.mode == 'ALL'
        title = _SPLIT_INFO[self.mode][0]
        try:
            if split_all:
                objs, active = _validate(context, title, 1, 0, closed_only=False,
                                         need_active=False)
            else:
                objs, active = _validate(context, title, 2, 0, closed_only=False)
            per_obj, tol = _to_active_space(objs, active)
        except Fail as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

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
            if intervals[i] is None:
                pieces.append((obj, d.copy()))
                continue
            local, _ = spline_segments(d)
            for g0, g1 in intervals[i]:
                segs = eng.extract(local, d.cyclic, g0, g1)
                if segs:
                    pieces.append((obj, segments_to_spline(segs, False, d.kind, d.settings)))

        converted = make_2d(objs)
        created = []
        for k, (obj, data) in enumerate(pieces, start=1):
            created.append((new_curve_object(context, obj, [data], f"{SPLIT_PREFIX}{k:02d}"), obj))
        finish_sources_and_results(context, objs, created)
        self.report({'INFO'}, f"{title}: {len(created)} piece(s)" + _converted_note(converted))
        return {'FINISHED'}


# -----------------------------------------------------------------------------

class ETR_OT_curve_toolkit_split(_SplitBase, bpy.types.Operator):
    """Cut 2D curves where they cross each other"""
    bl_idname = "etr.curve_toolkit_split"
    bl_label = "Curve Split"
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
        return context.mode == 'OBJECT' and len(selected_curves(context)) >= 2


class ETR_OT_curve_toolkit_split_all(_SplitBase, bpy.types.Operator):
    """Cut every selected curve where it crosses the others and where it crosses itself (a loop), so a single curve can be split too. No active object needed. Poly or Bezier, in the same plane"""
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
        return context.mode == 'OBJECT' and len(selected_curves(context)) >= 1


classes = (
    ETR_OT_curve_toolkit_boolean,
    ETR_OT_curve_toolkit_split,
    ETR_OT_curve_toolkit_split_all,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
