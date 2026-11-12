# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Points at Intersections and Points Along Curve

Two construction aids that add stray points (Poly splines of a single point)
without cutting or reshaping the curves they are taken from.

Points at Intersections
    A stray point exactly where two splines cross (also a spline with
    itself, and splines of the same object). Poly and Bezier splines are
    exact; NURBS splines are evaluated by Blender into a dense polyline, so
    their crossings are a very close approximation.

    Splines that only seem to cross (they are at different depths) are
    handled by the view:
      - In an orthographic axis view (Top, Bottom, Front, Back, Right,
        Left), the point goes where they cross on the screen, on the plane
        of the view through the world origin: Z = 0 in Top and Bottom,
        Y = 0 in Front and Back, X = 0 in Right and Left.
      - In a perspective or camera view no point is added for them, and a
        warning says so.
    Splines that really touch always get the point at its real place.

Points Along Curve
    Count points spread along each spline at equal lengths, without
    splitting it: 1 point at the middle, 2 points at 1/3 and 2/3, and so on
    (also on closed splines, measured from the first point). Add at Extremes
    also adds one at each end of an open spline, or one at the first point
    of a closed spline. Poly and Bezier are exact; NURBS are measured on
    their evaluated polyline. In Edit Mode, a spline with exactly two
    consecutive control points selected (N and N+1, or the last and the
    first of a closed spline) gets the points only along that segment,
    measured from N (Add at Extremes then adds N and N+1 too). One point,
    two points apart or three or more: the whole spline, as usual. Poly and
    Bezier only (a NURBS spline always gets them along all of it).

Both tools:
  - Object Mode: the selected curves; the points go into a new curve object,
    which is left selected, active and in Edit Mode (stray points cannot be
    seen in Object Mode).
  - Edit Mode: the splines with a selected point (one point per spline is
    enough); the points go into the curve being edited, and only they are
    left selected.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatVectorProperty, IntProperty
from mathutils import Vector

from . import curve_engine as eng
from . import curve_eval as ce
from . import geometry as geo
from . import spline_data as sd
from .between import _deselect_all, _stray_point
from .circles import VIEWS
from .context_utils import (
    EDIT_MODE,
    edit_scope,
    has_active_curve,
    link_like,
    selected_curves,
    unique_name,
    world_matrix,
)

INTERSECTIONS = "Points at Intersections"
ALONG = "Points Along Curve"

_VIEW_ITEMS = (
    ('NONE', "Perspective", "A perspective, camera or rotated view: only the splines that "
                            "really touch get a point"),
    ('TOP', "Top", "Orthographic Top view"),
    ('BOTTOM', "Bottom", "Orthographic Bottom view"),
    ('FRONT', "Front", "Orthographic Front view"),
    ('BACK', "Back", "Orthographic Back view"),
    ('RIGHT', "Right", "Orthographic Right view"),
    ('LEFT', "Left", "Orthographic Left view"),
)


class Fail(Exception):
    """A message for the user; nothing has been changed."""


def _poll(cls, context):
    if context.mode == 'OBJECT' and selected_curves(context):
        return True
    if context.mode == EDIT_MODE and has_active_curve(context):
        return True
    cls.poll_message_set("Select curves (Object Mode), or a point of each spline (Edit Mode)")
    return False


def _picked_splines(context, objs, edit):
    """[(object, SplineData)] of the splines the tool works on: all of them in
    Object Mode, those with a selected point in Edit Mode."""
    picked = []
    for obj in objs:
        for data in sd.read_all(obj.data):
            if edit and not any(sd.point_selected(p, data.kind) for p in data.points):
                continue
            picked.append((obj, data))
    return picked


def _points_object(context, name, world_points):
    """A new curve object at the world origin with a stray point at every
    world point. Linked next to the active curve, selected and active, and
    left in Edit Mode: stray points cannot be seen in Object Mode."""
    name = unique_name(name)
    curve = bpy.data.curves.new(name, 'CURVE')
    curve.dimensions = '3D'
    for co in world_points:
        sd.write_spline(curve, _stray_point(tuple(co)))
    obj = bpy.data.objects.new(name, curve)
    source = context.active_object if context.active_object is not None else None
    if source is not None and source.users_collection:
        link_like(obj, source, context)
    else:
        (context.collection or context.scene.collection).objects.link(obj)
    for other in context.selected_objects:
        other.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    return obj


def _add_strays(obj, world_points):
    """Stray points (selected) in `obj`, from world positions. Returns the
    last spline added, or None."""
    to_local = world_matrix(obj).inverted()
    spline = None
    for co in world_points:
        spline = sd.write_spline(obj.data, _stray_point(tuple(to_local @ Vector(co))))
    if spline is not None:
        obj.data.splines.active = spline
    return spline


def _dedupe(points, tol):
    out = []
    for p in points:
        if all(geo.distance(p, q) > tol for q in out):
            out.append(p)
    return out


def _scale(points):
    if not points:
        return 1.0
    return max(max(p[i] for p in points) - min(p[i] for p in points) for i in range(3)) or 1.0


# -----------------------------------------------------------------------------
# Points at Intersections
# -----------------------------------------------------------------------------

def find_intersections(paths, view_name=None, view_normal=(0.0, 0.0, 1.0)):
    """Crossings of a set of paths in world space.

    paths: [(list of ce.Cubic, cyclic)].
    view_name: an axis view ('TOP', ...) or None (perspective).
    view_normal: towards the viewer, for a perspective view.

    Returns (points, skipped): the world points, and how many crossings were
    only apparent (seen from the view, not touching) and were left out
    because the view is not an orthographic axis view.
    """
    all_pts = [p for cubics, _ in paths for c in cubics for p in (c.p0, c.h0, c.h1, c.p1)]
    if not all_pts:
        return [], 0
    touch = 1e-5 * _scale(all_pts)
    if view_name is not None:
        # Only the direction of the projection matters, so the usual up of
        # the view does (a rolled view projects the same way).
        normal, up = VIEWS[view_name]
        points, skipped = _crossings(paths, normal, up, touch, apparent=True)
        return _dedupe(points, 10.0 * touch), skipped
    # Perspective: seen along the view, to tell which crossings are only
    # apparent; and in the plane that fits the curves best, which finds the
    # real ones even when the view looks at that plane edge-on.
    normal = geo.normalized(view_normal) or (0.0, 0.0, 1.0)
    points, skipped = _crossings(paths, normal, ce.any_up(normal), touch, apparent=False)
    fitted = ce.best_plane(all_pts)
    if fitted is not None:
        more, _ = _crossings(paths, fitted, ce.any_up(fitted), touch, apparent=False)
        points += more
    return _dedupe(points, 10.0 * touch), skipped


def _crossings(paths, normal, up, touch, apparent):
    """Crossings of the paths projected along `normal`: (points, skipped).
    A crossing whose two curves do not touch in 3D goes on the plane of the
    projection through the world origin when `apparent`, otherwise it is
    only counted in `skipped`."""
    right, up = ce.screen_axes(normal, up)

    def flat(p):
        return (geo.dot(p, right), geo.dot(p, up))

    segs = []
    for cubics, cyclic in paths:
        segs.append([eng.Seg(flat(c.p0), flat(c.h0), flat(c.h1), flat(c.p1), c.line)
                     for c in cubics])
    tol = eng.tolerances_for(p for ss in segs for p in eng.segs_points(ss))
    boxes = [[s.bbox() for s in ss] for ss in segs]

    hits = []      # (cubic a, s, cubic b, t)
    for i, ss in enumerate(segs):
        cubics, cyclic = paths[i]
        # The path with itself.
        for g0, g1 in _pairs(eng._self_crossings(eng.Path(ss, cyclic, i), boxes[i], tol)):
            ka, sa = _local(g0, len(cubics))
            kb, sb = _local(g1, len(cubics))
            hits.append((cubics[ka], sa, cubics[kb], sb))
        # With the paths after it.
        for j in range(i + 1, len(segs)):
            for k, a in enumerate(ss):
                for m, b in enumerate(segs[j]):
                    if not eng._boxes_overlap(boxes[i][k], boxes[j][m], tol.join):
                        continue
                    for s, t in eng.intersect(a, b, tol):
                        hits.append((cubics[k], s, paths[j][0][m], t))

    points, skipped = [], 0
    for ca, s, cb, t in hits:
        pa, pb = ca.pt(s), cb.pt(t)
        if geo.distance(pa, pb) <= touch:
            points.append(geo.lerp(pa, pb, 0.5))
        elif apparent:
            x, y = flat(pa)
            points.append(geo.add(geo.mul(right, x), geo.mul(up, y)))
        else:
            skipped += 1
    return points, skipped


def _pairs(values):
    return [(values[i], values[i + 1]) for i in range(0, len(values) - 1, 2)]


def _local(g, n):
    k = int(g)
    if k >= n:
        return n - 1, 1.0
    return k, g - k


class _ViewProps:
    """The view, read from the 3D Viewport on the first run and kept for the
    F9 panel, where it can no longer be read."""

    view: EnumProperty(
        name="View",
        description="The view the button was clicked in. In an orthographic axis view, "
                    "curves that only seem to cross get a point on the plane of the view "
                    "through the world origin",
        items=_VIEW_ITEMS,
        default='NONE',
        options={'SKIP_SAVE'},
    )
    view_normal: FloatVectorProperty(size=3, default=(0.0, 0.0, 1.0),
                                     options={'HIDDEN', 'SKIP_SAVE'})
    view_up: FloatVectorProperty(size=3, default=(0.0, 1.0, 0.0),
                                 options={'HIDDEN', 'SKIP_SAVE'})

    def _read_view(self, context):
        if self.properties.is_property_set("view"):
            return
        name, normal, up = ce.axis_view(context)
        self.view = name or 'NONE'
        self.view_normal = normal
        self.view_up = up

    def _view(self):
        return (None if self.view == 'NONE' else self.view,
                tuple(self.view_normal), tuple(self.view_up))


class ETR_OT_curve_toolkit_points_at_intersections(_ViewProps, bpy.types.Operator):
    """Add a stray point exactly where splines cross, without cutting or changing them. Object Mode: the selected curves, into a new object. Edit Mode: the splines with a selected point, into the same curve. In an orthographic Top, Front or Right view, curves that only seem to cross get a point on the plane of the view"""
    bl_idname = "etr.curve_toolkit_points_at_intersections"
    bl_label = "Points at Intersections"
    bl_options = {'REGISTER', 'UNDO'}

    poll = classmethod(_poll)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "view")

    def execute(self, context):
        self._read_view(context)
        try:
            if context.mode == EDIT_MODE:
                added, skipped = self._edit(context)
            else:
                added, skipped = self._object(context)
        except Fail as error:
            self.report({'ERROR'}, f"{INTERSECTIONS}: {error}")
            return {'CANCELLED'}
        if skipped:
            self.report({'WARNING'}, f"{INTERSECTIONS}: {added} point(s). {skipped} crossing(s) "
                        "left out: the curves only seem to cross from this view (they do not "
                        "touch). Use an orthographic Top, Front or Right view to add them")
        else:
            self.report({'INFO'}, f"{INTERSECTIONS}: {added} point(s)")
        return {'FINISHED'}

    def _find(self, context, picked):
        paths = [(ce.world_cubics(context, obj, data), data.cyclic) for obj, data in picked]
        paths = [p for p in paths if p[0]]
        view_name, normal, _ = self._view()
        points, skipped = find_intersections(paths, view_name, normal)
        if not points:
            if skipped:
                raise Fail("the curves only seem to cross from this view, they do not touch. "
                           "In an orthographic Top, Front or Right view the points are added "
                           "on the plane of the view")
            raise Fail("the curves do not cross")
        return points, skipped

    def _object(self, context):
        objs = selected_curves(context)
        points, skipped = self._find(context, _picked_splines(context, objs, edit=False))
        _points_object(context, "Intersection Points", points)
        return len(points), skipped

    def _edit(self, context):
        obj = context.active_object
        with edit_scope(context) as objs:
            picked = _picked_splines(context, objs, edit=True)
            if not picked:
                raise Fail("select a point of each spline")
            points, skipped = self._find(context, picked)
            for o in objs:
                _deselect_all(o.data)
            _add_strays(obj, points)
        return len(points), skipped


# -----------------------------------------------------------------------------
# Points Along Curve
# -----------------------------------------------------------------------------

def along_points(cubics, cyclic, count, extremes):
    """World points spread along a path at equal lengths (see the module
    docstring), in their order along it."""
    if not cubics:
        return []
    table = ce.length_table(cubics)
    total = table[-1][2]
    if total <= 1e-12:
        return []
    lengths = [total * i / (count + 1) for i in range(1, count + 1)]
    if extremes:
        lengths = [0.0] + lengths + ([] if cyclic else [total])
    return [ce.point_at_length(cubics, table, s) for s in lengths]


class ETR_OT_curve_toolkit_points_along_curve(bpy.types.Operator):
    """Add Count stray points along each spline, at equal lengths, without splitting it. Object Mode: the selected curves, into a new object. Edit Mode: the splines with a selected point, into the same curve; with two consecutive control points selected, only along the segment between them"""
    bl_idname = "etr.curve_toolkit_points_along_curve"
    bl_label = "Points Along Curve"
    bl_options = {'REGISTER', 'UNDO'}

    count: IntProperty(
        name="Count",
        description="Points on each spline, at equal lengths: 1 at the middle, 2 at 1/3 "
                    "and 2/3, and so on (also on closed splines, from the first point)",
        default=4,
        min=1,
        soft_max=99,
        max=10000,
    )
    extremes: BoolProperty(
        name="Add at Extremes",
        description="Also add a point at each end of an open spline, or one at the first "
                    "point (which is also the last) of a closed spline",
        default=False,
    )

    poll = classmethod(_poll)

    def execute(self, context):
        try:
            if context.mode == EDIT_MODE:
                added = self._edit(context)
            else:
                added = self._object(context)
        except Fail as error:
            self.report({'ERROR'}, f"{ALONG}: {error}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"{ALONG}: {added} point(s)")
        return {'FINISHED'}

    def _points(self, context, obj, data, edit=False):
        cubics = ce.world_cubics(context, obj, data)
        if edit and data.kind != 'NURBS':
            # Two consecutive control points selected: only the segment
            # between them, as an open path of its own.
            k = sd.selected_segment(data)
            if k is not None and k < len(cubics):
                return along_points([cubics[k]], False, self.count, self.extremes)
        return along_points(cubics, data.cyclic, self.count, self.extremes)

    def _object(self, context):
        points = []
        for obj, data in _picked_splines(context, selected_curves(context), edit=False):
            points += self._points(context, obj, data)
        if not points:
            raise Fail("the selected curves have no length")
        _points_object(context, "Curve Points", points)
        return len(points)

    def _edit(self, context):
        with edit_scope(context) as objs:
            picked = _picked_splines(context, objs, edit=True)
            if not picked:
                raise Fail("select a point of each spline")
            per_obj = {}
            for obj, data in picked:
                per_obj.setdefault(obj, []).extend(self._points(context, obj, data, edit=True))
            added = sum(len(p) for p in per_obj.values())
            if not added:
                raise Fail("the selected splines have no length")
            for o in objs:
                _deselect_all(o.data)
            for obj, points in per_obj.items():
                _add_strays(obj, points)
        return added


classes = (
    ETR_OT_curve_toolkit_points_at_intersections,
    ETR_OT_curve_toolkit_points_along_curve,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
