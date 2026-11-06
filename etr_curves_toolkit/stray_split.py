# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Split at Stray Points

Cut the splines of a curve where stray points (Poly splines of a single
point, like the ones Points at Intersections, Points Along Curve or Points
in Between add) lie on them, instead of at their own control points (that is
Split at Control Points). Every piece becomes a new object (Split_01,
Split_02...), and the original curve is kept as a backup, hidden or in the
"Curve Boolean Sources" collection, the same way as the Booleans and the
other Splits (Place Sources / Place Results).

  - Object Mode: every selected curve that has stray points on its splines.
    Only the stray points of the same object count (stray points cannot be
    seen in Object Mode, so other objects are left out). Splines that no
    stray point touches become objects of their own too, unchanged, so
    nothing but the stray points goes out of sight.
  - Edit Mode: only the splines with a selected control point are cut, and
    only by the selected stray points. Each curve being edited is cut by its
    own stray points. It ends in Object Mode, with the pieces selected.

When a stray point is on a spline is decided by the view:
  - In an orthographic axis view (Top, Bottom, Front, Back, Right, Left) it
    is enough for the point to be seen on the spline: distances are measured
    on the screen, so a point drawn on the plane of the view cuts a spline
    that is in front of or behind it.
  - In a perspective or camera view, the point has to really touch the
    spline in 3D.
Either way "on" means within the Threshold of Global Settings, measured in
the world. A stray point near a control point cuts at that control point.

Poly and Bezier splines; NURBS splines are never cut (they are kept whole).
The cut keeps the shape exactly: a Bezier segment is divided with de
Casteljau, and the new point gets Aligned handles.
"""

import bpy
from bpy.props import EnumProperty, FloatVectorProperty
from mathutils import Vector

from . import curve_eval as ce
from . import geometry as geo
from . import spline_data as sd
from .context_utils import (
    EDIT_MODE,
    curves_in_edit_mode,
    edit_scope,
    finish_sources_and_results,
    has_active_curve,
    new_curve_object,
    selected_curves,
    world_matrix,
)
from .utilities import _make_piece, _piece_indices

TITLE = "Split at Stray Points"
SPLIT_PREFIX = "Split_"

#: Samples per segment before the closest point is refined.
_SAMPLES = 32
#: A cut this close (in parameter) to a control point is made at that point.
_AT_POINT = 1e-6

_VIEW_ITEMS = (
    ('NONE', "Perspective", "A perspective, camera or rotated view: only the stray points "
                            "that really touch a spline cut it"),
    ('TOP', "Top", "Orthographic Top view"),
    ('BOTTOM', "Bottom", "Orthographic Bottom view"),
    ('FRONT', "Front", "Orthographic Front view"),
    ('BACK', "Back", "Orthographic Back view"),
    ('RIGHT', "Right", "Orthographic Right view"),
    ('LEFT', "Left", "Orthographic Left view"),
)


class Fail(Exception):
    """A message for the user; nothing has been changed."""


# -----------------------------------------------------------------------------
# Where the stray points are on the splines
# -----------------------------------------------------------------------------

def _projector(view_name):
    """Function that puts a world point where distances are measured: on the
    screen of an orthographic axis view, or left in 3D (None)."""
    if view_name is None:
        return lambda p: p
    normal, up = ce.VIEWS[view_name]
    right, up = ce.screen_axes(normal, up)
    return lambda p: (geo.dot(p, right), geo.dot(p, up), 0.0)


def _closest(cubic, p, project):
    """(parameter, distance) of the point of a cubic closest to p, both
    measured after `project`."""
    def dist(t):
        return geo.distance(project(cubic.pt(t)), p)

    if cubic.line:
        a, b = project(cubic.p0), project(cubic.p1)
        ab = geo.sub(b, a)
        length2 = geo.dot(ab, ab)
        t = 0.0 if length2 <= 1e-300 else geo.dot(geo.sub(p, a), ab) / length2
        t = min(1.0, max(0.0, t))
        return t, dist(t)
    best = min(range(_SAMPLES + 1), key=lambda i: dist(i / _SAMPLES))
    lo = max(0.0, (best - 1) / _SAMPLES)
    hi = min(1.0, (best + 1) / _SAMPLES)
    # Golden-section search on the bracket around the best sample.
    g = 0.6180339887498949
    x1, x2 = hi - g * (hi - lo), lo + g * (hi - lo)
    f1, f2 = dist(x1), dist(x2)
    for _ in range(60):
        if f1 < f2:
            hi, x2, f2 = x2, x1, f1
            x1 = hi - g * (hi - lo)
            f1 = dist(x1)
        else:
            lo, x1, f1 = x1, x2, f2
            x2 = lo + g * (hi - lo)
            f2 = dist(x2)
    t = 0.5 * (lo + hi)
    return t, dist(t)


def find_cuts(cubics, strays, threshold, view_name=None):
    """Cuts of one spline: a list of (segment index, parameter).

    cubics: the world cubics of the spline (ce.world_cubics).
    strays: world points of the stray points.
    """
    project = _projector(view_name)
    cuts = []
    for p in strays:
        q = project(p)
        for k, cubic in enumerate(cubics):
            t, d = _closest(cubic, q, project)
            if d <= threshold:
                cuts.append((k, t))
    return cuts


# -----------------------------------------------------------------------------
# Cutting a snapshot
# -----------------------------------------------------------------------------

def _after_cut(handle_type, straight):
    """Handle type of a handle moved by a cut, so that Blender does not move
    it again: Auto handles become Aligned, and a Vector handle of a curved
    segment becomes Free (Vector would point it at the new point)."""
    if handle_type == 'AUTO':
        return 'ALIGNED'
    if handle_type == 'VECTOR' and not straight:
        return 'FREE'
    return handle_type


def insert_cuts(data, cuts):
    """Snapshot with a new point at every cut, and the indices of the points
    where it has to be cut (new or already there).

    cuts: (segment index, parameter) pairs; segment k goes from point k to
    point k + 1 (the closing one of a closed spline is k = n - 1).
    """
    n = len(data.points)
    nsegs = n if data.cyclic else n - 1
    at_points = set()
    inner = {}
    for k, t in cuts:
        if k < 0 or k >= nsegs:
            continue
        if t <= _AT_POINT:
            at_points.add(k)
        elif t >= 1.0 - _AT_POINT:
            at_points.add((k + 1) % n)
        else:
            inner.setdefault(k, []).append(t)

    out = [sd.replace(p) for p in data.points]
    # Points of the new list: the original ones, with the new ones after the
    # point their segment starts at.
    new_points = []
    index_of = {}
    cut_indices = set()
    for i in range(n):
        index_of[i] = len(new_points)
        new_points.append(out[i])
        ts = sorted(inner.get(i, []))
        merged = []
        for t in ts:
            if not merged or t - merged[-1] > _AT_POINT:
                merged.append(t)
        if not merged:
            continue
        a, b = out[i], out[(i + 1) % n]
        if data.kind == 'BEZIER':
            straight = geo.is_straight_segment(a.co, a.hr, b.hl, b.co)
            rest = (a.co, a.hr, b.hl, b.co)
            done = 0.0
            left_end = a
            for t in merged:
                local = (t - done) / (1.0 - done)
                (p0, h0, h1, m), (m2, e, c, p1) = geo.bezier_split(*rest, local)
                left_end.hr = h0
                left_end.hrt = _after_cut(left_end.hrt, straight)
                point = sd.PointData(
                    co=m, hl=h1, hr=e,
                    hlt='VECTOR' if straight else 'ALIGNED',
                    hrt='VECTOR' if straight else 'ALIGNED',
                    radius=a.radius + (b.radius - a.radius) * t,
                    tilt=a.tilt + (b.tilt - a.tilt) * t,
                )
                new_points.append(point)
                cut_indices.add(len(new_points) - 1)
                left_end = point
                rest = (m, e, c, p1)
                done = t
            b.hl = rest[2]
            b.hlt = _after_cut(b.hlt, straight)
        else:
            for t in merged:
                new_points.append(sd.PointData(
                    co=geo.lerp(a.co, b.co, t),
                    w=a.w + (b.w - a.w) * t,
                    radius=a.radius + (b.radius - a.radius) * t,
                    tilt=a.tilt + (b.tilt - a.tilt) * t,
                ))
                cut_indices.add(len(new_points) - 1)
    cut_indices |= {index_of[i] for i in at_points}
    result = sd.SplineData(data.kind, new_points, data.cyclic, dict(data.settings))
    return result, sorted(cut_indices)


def split_spline(data, cuts):
    """Pieces (SplineData) of a spline cut at `cuts`, or None when the cuts
    do not divide it (none, or only at the ends of an open spline)."""
    if not cuts:
        return None
    full, indices = insert_cuts(data, cuts)
    n = len(full.points)
    if not full.cyclic:
        indices = [i for i in indices if 0 < i < n - 1]
    if not indices:
        return None
    return [_make_piece(full, a, b) for a, b in _piece_indices(n, full.cyclic, indices)
            if b > a]


# -----------------------------------------------------------------------------
# The operator
# -----------------------------------------------------------------------------

def _is_stray(data):
    return len(data.points) == 1


class ETR_OT_curve_toolkit_split_at_stray_points(bpy.types.Operator):
    """Cut the splines where stray points of the same curve lie on them (within the Threshold of Global Settings). Every piece becomes a new object; the original is kept, hidden. Object Mode: the selected curves. Edit Mode: the selected splines, by the selected stray points. In an orthographic Top, Front or Right view it is enough for a point to be seen on a spline. Poly and Bezier"""
    bl_idname = "etr.curve_toolkit_split_at_stray_points"
    bl_label = "Split at Stray Points"
    bl_options = {'REGISTER', 'UNDO'}

    view: EnumProperty(
        name="View",
        description="The view the button was clicked in. In an orthographic axis view, a "
                    "stray point seen on a spline cuts it even if it is in front of or "
                    "behind it",
        items=_VIEW_ITEMS,
        default='NONE',
        options={'SKIP_SAVE'},
    )
    view_normal: FloatVectorProperty(size=3, default=(0.0, 0.0, 1.0),
                                     options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        if context.mode == 'OBJECT' and selected_curves(context):
            return True
        if context.mode == EDIT_MODE and has_active_curve(context):
            return True
        cls.poll_message_set("Select curves with stray points (Object Mode), or the splines "
                             "and stray points to use (Edit Mode)")
        return False

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "view")

    def _read_view(self, context):
        if self.properties.is_property_set("view"):
            return
        name, normal, _ = ce.axis_view(context)
        self.view = name or 'NONE'
        self.view_normal = normal

    def execute(self, context):
        self._read_view(context)
        view_name = None if self.view == 'NONE' else self.view
        threshold = context.scene.etr_curves_toolkit.merge_threshold
        edit = context.mode == EDIT_MODE
        active = context.active_object
        try:
            if edit:
                editing = curves_in_edit_mode(context)
                try:
                    with edit_scope(context, reenter=False) as objs:
                        created, nurbs = self._split(context, objs, True, view_name,
                                                     threshold)
                except Fail:
                    # Nothing was changed: back to the Edit Mode it came from.
                    for o in editing:
                        o.select_set(True)
                    context.view_layer.objects.active = active
                    bpy.ops.object.mode_set(mode='EDIT')
                    raise
            else:
                objs = selected_curves(context)
                created, nurbs = self._split(context, objs, False, view_name, threshold)
        except Fail as error:
            self.report({'ERROR'}, f"{TITLE}: {error}")
            return {'CANCELLED'}

        sources = [obj for obj, _ in created]
        results = [(new, obj) for obj, news in created for new in news]
        anchor = active if active in sources else sources[0]
        finish_sources_and_results(context, sources, results, anchor)
        note = f" ({nurbs} NURBS spline(s) left whole)" if nurbs else ""
        self.report({'INFO'}, f"{TITLE}: {len(results)} piece(s){note}")
        return {'FINISHED'}

    def _split(self, context, objs, edit, view_name, threshold):
        """[(source object, [new objects])] and how many NURBS splines were
        on the way. Raises Fail when nothing is cut."""
        created = []
        nurbs = 0
        any_strays = False
        counter = 0
        for obj in objs:
            datas = sd.read_all(obj.data)
            mw = world_matrix(obj)
            strays = [tuple(mw @ Vector(d.points[0].co)) for d in datas
                      if _is_stray(d) and (not edit or d.points[0].select)]
            if not strays:
                continue
            any_strays = True
            pieces = []
            cut_any = False
            for d in datas:
                if _is_stray(d) or not d.points:
                    continue
                if edit and not any(sd.point_selected(p, d.kind) for p in d.points):
                    continue
                if d.kind == 'NURBS':
                    nurbs += 1
                    pieces.append(d.copy())
                    continue
                cubics = ce.world_cubics(context, obj, d)
                cuts = find_cuts(cubics, strays, threshold, view_name)
                split = split_spline(d, cuts)
                if split is None:
                    pieces.append(d.copy())
                else:
                    pieces += split
                    cut_any = True
            if not cut_any:
                continue
            news = []
            for piece in pieces:
                counter += 1
                news.append(new_curve_object(context, obj, [piece],
                                             f"{SPLIT_PREFIX}{counter:02d}"))
            created.append((obj, news))
        if not created:
            if not any_strays:
                raise Fail("there are no stray points" + (" selected" if edit else "")
                           + " in the curve")
            raise Fail("no stray point is on a spline (within the Threshold of Global "
                       "Settings" + ("; select the splines too" if edit else "") + ")")
        return created, nurbs


classes = (ETR_OT_curve_toolkit_split_at_stray_points,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
