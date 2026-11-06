# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Symmetrize (Object Mode)

Mirror one side of the selected curves onto the other side and weld them on
the axis, as a new curve: the side that is kept is copied, mirrored, and the
other side is replaced by that copy.

Everything is relative to the view, which must be an orthographic axis view
(Top, Bottom, Front, Back, Right or Left; not a perspective or camera view):

  - Direction (four arrows): which side is copied onto which. When the
    curves have nothing on the side that is kept (or the view is not an axis
    view), nothing is made but the operator still finishes, with a warning,
    so the F9 panel opens and the Direction (or the View) can be changed.
      Left to Right: the left side is kept and mirrored onto the right one
                     (the default).
      Right to Left: the right side is kept and mirrored onto the left one.
      Top to Bottom: the upper side is kept and mirrored onto the lower one.
      Bottom to Top: the lower side is kept and mirrored onto the upper one.
    Left and right are those of the screen: the left of Front is the right
    of Back.
  - Center: where the mirror axis goes through: World Origin (the default),
    Object Origin (each curve uses its own) or 3D Cursor. The axis is the
    vertical line of the screen through it (Left / Right directions) or the
    horizontal one (Top / Bottom).

Closed splines are one region, even-odd, the way Blender fills them (a shape
with holes): the part of the region on the kept side is joined with its
mirror image, so the outline that crossed the axis becomes one symmetric
outline, welded where it meets the axis. Open splines are cut where they
cross the axis; every piece on the kept side gets its mirror image, welded to
it where the piece touches the axis (a piece with both ends on the axis
becomes a closed spline). A piece that does not reach the axis stays as it
is, next to its mirror copy. Stray points are mirrored too.

The curves must be flat, in a plane facing the view. Poly and Bezier
splines (Poly when every spline is Poly, otherwise Bezier). Points welded on
the axis get Free handles, so Blender does not realign them.

Each selected curve gives a new curve object with its look; the originals
are kept as backups, hidden or placed in "Curve Boolean Sources", and the
results go into "Curve Boolean Results", with the two options of the Curve
Booleans panel. The geometry work is done by curve_engine.py.
"""

import bpy
from bpy.props import EnumProperty
from mathutils import Vector

from . import curve_engine as eng
from . import curve_eval as ce
from . import geometry as geo
from . import spline_data as sd
from .booleans import segments_to_spline, spline_segments
from .circles import VIEWS
from .context_utils import (
    finish_sources_and_results,
    new_curve_object,
    selected_curves,
    world_matrix,
)

TITLE = "Symmetrize"

#: 2 x 2 maps from the screen (x right, y up) to a frame where the side that
#: is kept is x < 0 and the mirror is x -> -x. They are orthogonal, so the
#: way back is the transpose.
_FRAMES = {
    'LEFT_TO_RIGHT': ((1.0, 0.0), (0.0, 1.0)),
    'RIGHT_TO_LEFT': ((-1.0, 0.0), (0.0, 1.0)),
    'TOP_TO_BOTTOM': ((0.0, -1.0), (1.0, 0.0)),
    'BOTTOM_TO_TOP': ((0.0, 1.0), (1.0, 0.0)),
}

_VIEW_ITEMS = (
    ('NONE', "Perspective", "A perspective, camera or rotated view: Symmetrize does not work "
                            "there"),
    ('TOP', "Top", "Orthographic Top view"),
    ('BOTTOM', "Bottom", "Orthographic Bottom view"),
    ('FRONT', "Front", "Orthographic Front view"),
    ('BACK', "Back", "Orthographic Back view"),
    ('RIGHT', "Right", "Orthographic Right view"),
    ('LEFT', "Left", "Orthographic Left view"),
)


class Fail(Exception):
    """A message for the user; nothing has been changed."""


class Empty(Exception):
    """The curve has nothing on the side that is kept."""


# -----------------------------------------------------------------------------
# The frame of the mirror
# -----------------------------------------------------------------------------

class Frame:
    """The plane of the view, centered on the mirror axis.

    to_2d() takes a world point to the frame (x < 0: the side that is kept),
    to_world() takes it back, at the depth of the curve.
    """

    def __init__(self, view, direction, center):
        normal, up = VIEWS[view]
        self.normal = normal
        self.right, self.up = ce.screen_axes(normal, up)
        self.matrix = _FRAMES[direction]
        self.center = tuple(center)
        self.depth = 0.0

    def to_2d(self, p):
        d = geo.sub(p, self.center)
        x, y = geo.dot(d, self.right), geo.dot(d, self.up)
        (a, b), (c, e) = self.matrix
        return (a * x + b * y, c * x + e * y)

    def depth_of(self, p):
        return geo.dot(geo.sub(p, self.center), self.normal)

    def to_world(self, q):
        (a, b), (c, e) = self.matrix
        x, y = a * q[0] + c * q[1], b * q[0] + e * q[1]      # transpose
        return geo.add(self.center, geo.add(geo.add(geo.mul(self.right, x),
                                                    geo.mul(self.up, y)),
                                            geo.mul(self.normal, self.depth)))


def _flat_copy(data, mw, frame, depths):
    """Copy of a snapshot with every point and handle in the 2D frame (as
    (x, y, 0)). The depths of the points are appended to `depths`."""
    out = data.copy()
    for p in out.points:
        world = tuple(mw @ Vector(p.co))
        depths.append(frame.depth_of(world))
        p.co = (*frame.to_2d(world), 0.0)
        if p.hl is not None:
            p.hl = (*frame.to_2d(tuple(mw @ Vector(p.hl))), 0.0)
            p.hr = (*frame.to_2d(tuple(mw @ Vector(p.hr))), 0.0)
    return out


def _mirrored_point(p):
    q = sd.replace(p)
    q.co = (-p.co[0], p.co[1], 0.0)
    if p.hl is not None:
        q.hl = (-p.hl[0], p.hl[1], 0.0)
        q.hr = (-p.hr[0], p.hr[1], 0.0)
    return q


class _Mirror:
    """Mirror image of engine segments (x -> -x). The original points of
    their ends ("metas") are mirrored too, once each, so the open ends of the
    mirrored pieces keep their own outer handle."""

    def __init__(self):
        self._points = {}

    def _meta(self, meta):
        if meta is None:
            return None
        p, side = meta
        q = self._points.get(id(p))
        if q is None:
            q = self._points[id(p)] = (p, _mirrored_point(p))
        return (q[1], side)

    def seg(self, s):
        def m(v):
            return (-v[0], v[1])
        return eng.Seg(m(s.p0), m(s.h0), m(s.h1), m(s.p1), s.line,
                       self._meta(s.m0), self._meta(s.m1))

    def segs(self, segs):
        return [self.seg(s) for s in segs]


def _reversed(segs):
    return [s.reversed() for s in reversed(segs)]


def _snap_start(s):
    """Segment whose start is put exactly on the axis (x = 0), its handle
    moving with it."""
    dx = -s.p0[0]
    return eng.Seg((0.0, s.p0[1]), (s.h0[0] + dx, s.h0[1]), s.h1, s.p1, s.line, s.m0, s.m1)


def _snap_end(s):
    dx = -s.p1[0]
    return eng.Seg(s.p0, s.h0, (s.h1[0] + dx, s.h1[1]), (0.0, s.p1[1]), s.line, s.m0, s.m1)


# -----------------------------------------------------------------------------
# Closed splines: a region
# -----------------------------------------------------------------------------

def symmetric_region(loops, tol, reach):
    """Loops of the symmetric region: the part of the region on the kept side
    (x < 0), joined with its mirror image. `reach` is larger than any
    coordinate of the loops."""
    half = [(-reach, -reach), (0.0, -reach), (0.0, reach), (-reach, reach)]
    box = [eng.line_seg(a, b) for a, b in zip(half, half[1:] + half[:1])]
    kept = eng.boolean(loops, [box], 'INTERSECTION', tol)
    if not kept:
        return []
    mirror = _Mirror()
    return eng.boolean(kept, [mirror.segs(loop) for loop in kept], 'UNION', tol)


# -----------------------------------------------------------------------------
# Open splines: pieces
# -----------------------------------------------------------------------------

def symmetric_open(segs, tol, reach):
    """[(segments, cyclic)] made from an open path: its pieces on the kept
    side with their mirror images, welded on the axis."""
    path = eng.Path(segs, False, 0)
    axis = eng.line_seg((0.0, -reach), (0.0, reach))
    cuts = []
    for k, s in enumerate(segs):
        for t, _ in eng.intersect(s, axis, tol):
            g = eng._global_param(path, k, t, tol)
            if g is not None:
                cuts.append(g)
    cuts = eng._dedupe_params(path, sorted(cuts), tol)
    bounds = [0.0] + cuts + [float(len(segs))]
    near = 10.0 * tol.join
    mirror = _Mirror()
    out = []
    for g0, g1 in zip(bounds, bounds[1:]):
        piece = eng.extract(segs, False, g0, g1)
        if not piece:
            continue
        mid = eng.point_at(eng.Path(piece, False, 0), 0.5 * len(piece))
        if mid[0] > -near:
            continue        # on the side that goes away, or along the axis
        start_on = abs(piece[0].p0[0]) <= near
        end_on = abs(piece[-1].p1[0]) <= near
        if start_on:
            piece[0] = _snap_start(piece[0])
        if end_on:
            piece[-1] = _snap_end(piece[-1])
        image = _reversed(mirror.segs(piece))
        if start_on and end_on:
            out.append((piece + image, True))
        elif end_on:
            out.append((piece + image, False))
        elif start_on:
            out.append((image + piece, False))
        else:
            out.append((piece, False))
            out.append((_reversed(image), False))
    return out


def _free_on_axis(data, near):
    """Points welded on the axis get Free handles (Vector ones stay)."""
    for p in data.points:
        if abs(p.co[0]) <= near:
            if p.hlt in ('ALIGNED', 'AUTO'):
                p.hlt = 'FREE'
            if p.hrt in ('ALIGNED', 'AUTO'):
                p.hrt = 'FREE'


# -----------------------------------------------------------------------------
# One object
# -----------------------------------------------------------------------------

def symmetrize_object(obj, frame):
    """SplineData (local space of `obj`) of the symmetric curve, or Empty."""
    mw = world_matrix(obj)
    datas = sd.read_all(obj.data)
    if not datas:
        raise Empty()
    for d in datas:
        if d.kind == 'NURBS':
            raise Fail(f"'{obj.name}' has NURBS splines: {TITLE} works with Poly and Bezier "
                       "curves")
    depths = []
    flat = [_flat_copy(d, mw, frame, depths) for d in datas]
    coords = [c for d in flat for p in d.points
              for c in ((p.co,) if p.hl is None else (p.co, p.hl, p.hr))]
    tol = eng.tolerances_for(coords)
    if max(depths) - min(depths) > 1e-5 * tol.scale + 1e-6:
        raise Fail(f"'{obj.name}' is not flat in the plane of the view: {TITLE} needs curves "
                   "that lie in a plane facing the view")
    frame.depth = sum(depths) / len(depths)
    reach = 4.0 * max(max(abs(c[0]), abs(c[1])) for c in coords) + 1.0
    near = 10.0 * tol.join

    kind = 'POLY' if all(d.kind == 'POLY' for d in flat) else 'BEZIER'
    settings = dict(flat[0].settings)
    results = []

    loops = [spline_segments(d)[0] for d in flat if d.cyclic and len(d.points) > 1]
    if loops:
        for loop in symmetric_region(loops, tol, reach):
            results.append(segments_to_spline(loop, True, kind, settings))

    for d in flat:
        if d.cyclic and len(d.points) > 1:
            continue
        if len(d.points) == 1:
            p = d.points[0]
            if p.co[0] < -near:
                results += [_single(d, p), _single(d, _mirrored_point(p))]
            elif p.co[0] <= near:
                results.append(_single(d, p))
            continue
        segs, _ = spline_segments(d)
        for piece, cyclic in symmetric_open(segs, tol, reach):
            results.append(segments_to_spline(piece, cyclic, kind, d.settings))

    if not results:
        raise Empty()
    to_local = mw.inverted()

    def back(co):
        return tuple(to_local @ Vector(frame.to_world(co)))

    for data in results:
        _free_on_axis(data, near)
        for p in data.points:
            p.co = back(p.co)
            if p.hl is not None:
                p.hl, p.hr = back(p.hl), back(p.hr)
    return results


def _single(data, point):
    out = data.copy()
    q = sd.replace(point)
    q.select = q.select_left = q.select_right = False
    out.points = [q]
    return out


# -----------------------------------------------------------------------------
# Operator
# -----------------------------------------------------------------------------

class ETR_OT_curve_toolkit_symmetrize(bpy.types.Operator):
    """Mirror one side of the selected curves onto the other and weld them on the axis, as new curves (the originals are kept as backups). Relative to the view: works in an orthographic Top, Front, Right... view. Direction and Center in the F9 panel. Poly and Bezier, open or closed. Object Mode"""
    bl_idname = "etr.curve_toolkit_symmetrize"
    bl_label = "Symmetrize"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(
        name="Direction",
        description="Which side is copied onto which, as seen in the view",
        items=(
            ('LEFT_TO_RIGHT', "Left to Right", "The left side is mirrored onto the right "
                                               "side, which goes away", 'TRIA_RIGHT', 0),
            ('RIGHT_TO_LEFT', "Right to Left", "The right side is mirrored onto the left "
                                               "side, which goes away", 'TRIA_LEFT', 1),
            ('TOP_TO_BOTTOM', "Top to Bottom", "The upper side is mirrored onto the lower "
                                               "side, which goes away", 'TRIA_DOWN', 2),
            ('BOTTOM_TO_TOP', "Bottom to Top", "The lower side is mirrored onto the upper "
                                               "side, which goes away", 'TRIA_UP', 3),
        ),
        default='LEFT_TO_RIGHT',
    )
    center: EnumProperty(
        name="Center",
        description="Where the mirror axis goes through",
        items=(
            ('WORLD', "World Origin", "The world origin"),
            ('OBJECT', "Object Origin", "The origin of each curve"),
            ('CURSOR', "3D Cursor", "The 3D Cursor"),
        ),
        default='WORLD',
    )
    # The view, read from the 3D Viewport on the first run and kept for the
    # F9 panel, where it can no longer be read.
    view: EnumProperty(
        name="View",
        description="The view the mirror is relative to (where left, right, top and bottom "
                    "are). It comes from the 3D Viewport when the button is clicked",
        items=_VIEW_ITEMS,
        default='NONE',
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        if context.mode == 'OBJECT' and selected_curves(context):
            return True
        cls.poll_message_set("Select curves (Object Mode)")
        return False

    def draw(self, context):
        from .panel import _equal_slots
        layout = self.layout
        # The four arrows in a row, each a quarter of the width: icon-only
        # buttons are small squares in a row (and a column with the split
        # layout), but take the whole width inside the columns of a split.
        items = self.properties.bl_rna.properties["direction"].enum_items
        for slot, item in zip(_equal_slots(layout.column(align=True), 4), items):
            slot.prop_enum(self, "direction", item.identifier, text="", icon=item.icon)
        layout.separator(factor=0.5)
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "center")
        layout.prop(self, "view")

    def execute(self, context):
        if not self.properties.is_property_set("view"):
            name, _, _ = ce.axis_view(context)
            self.view = name or 'NONE'
        # The two cases below change nothing but still FINISH (with a
        # warning), so the F9 panel opens and the View or the Direction can be
        # changed there: a CANCELLED operator has no F9 panel.
        if self.view == 'NONE':
            self.report({'WARNING'}, f"{TITLE} works in an orthographic Top, Bottom, Front, "
                                     "Back, Right or Left view (not in a perspective or "
                                     "camera view). Pick the View in the F9 panel")
            return {'FINISHED'}

        objs = selected_curves(context)
        done, empty = [], []
        try:
            for obj in objs:
                frame = Frame(self.view, self.direction, self._center(context, obj))
                try:
                    done.append((obj, symmetrize_object(obj, frame)))
                except Empty:
                    empty.append(obj)
        except Fail as error:
            self.report({'ERROR'}, f"{TITLE}: {error}")
            return {'CANCELLED'}

        if not done:
            self.report({'WARNING'}, f"{TITLE}: nothing mirrored, the curves have nothing on "
                                     "the side that is kept. Change the Direction in the F9 "
                                     "panel")
            return {'FINISHED'}
        results = [(new_curve_object(context, obj, datas, TITLE), obj) for obj, datas in done]
        finish_sources_and_results(context, [obj for obj, _ in done], results)
        if empty:
            names = ", ".join(f"'{o.name}'" for o in empty)
            self.report({'WARNING'}, f"{TITLE}: {len(results)} curve(s). Left as they were "
                                     f"(nothing on the side that is kept): {names}")
        else:
            self.report({'INFO'}, f"{TITLE}: {len(results)} curve(s)")
        return {'FINISHED'}

    def _center(self, context, obj):
        if self.center == 'CURSOR':
            return tuple(context.scene.cursor.location)
        if self.center == 'OBJECT':
            return tuple(world_matrix(obj).translation)
        return (0.0, 0.0, 0.0)


classes = (ETR_OT_curve_toolkit_symmetrize,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
