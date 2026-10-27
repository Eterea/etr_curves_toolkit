# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Arcs to Corners (Edit Mode)

The inverse of Round Corners: it brings back the hard corner a curved segment
was rounded from.

For every pair of consecutive selected control points, the two handles that
shape the segment between them are prolonged until they meet, and a new
control point with Vector handles is placed at that meeting point. Both sides
of the corner come out straight, because that point lies on the line each
handle defines.

A segment is left alone when its handles do not meet in front of both points:
a straight segment and a half turn give parallel handles, an S shape gives
handles that meet behind the points, and in 3D two handles that are not in the
same plane never meet. No plane is asked of the spline as a whole: every
segment is solved on its own, so a flat segment of a warped 3D spline works
too, whatever its orientation.

The two original control points are left selected with their handles and the
new corner unselected, so that a Dissolve right after (by hand, or with the
*Dissolve Originals* option of the F9 panel) removes exactly those two points
and leaves the hard corner alone.

The handles that now aim at the corner become Free (Vector ones stay Vector),
and so does any Auto handle of the two points: Blender recomputes an Auto
handle from the neighbouring points, and the corner is a new neighbour that
would bend what has to stay straight.
"""

import math

import bpy
from bpy.props import BoolProperty

from . import geometry as geo
from . import spline_data as sd
from .context_utils import EDIT_MODE, edit_scope, has_active_curve

# How far the corner may land from each of the two points, as a multiple of
# the distance between them. Only the two near-degenerate families reach past
# it: a segment that is almost straight, and one that turns almost half a
# circle. Both would put the corner absurdly far away (an exact half turn,
# like an exactly straight segment, gives parallel handles and no meeting
# point at all).
MAX_REACH = 100.0

# Widest gap between the two handle lines still counted as a meeting point, as
# a fraction of the distance between the points. Curve coordinates are single
# precision, so an exact crossing arrives with some noise; two skew handles of
# a real 3D spline miss each other by orders of magnitude more than this.
MEET_TOL = 1e-4

# Smallest sine of the angle between the two handles. Below it they count as
# parallel and nothing is done.
SIN_TOL = 1e-7


# -----------------------------------------------------------------------------
# Geometry
# -----------------------------------------------------------------------------

def corner_point(a_co, a_hr, b_hl, b_co):
    """Point where the handles of the segment a -> b meet, or None.

    `a_hr` is the right handle of the first point and `b_hl` the left handle of
    the second one, so the two lines are the ones the Bezier segment leaves
    along. The result is the midpoint of the closest points of both lines,
    which is the crossing itself when they do cross.
    """
    chord = geo.distance(a_co, b_co)
    if chord < geo.EPS:
        return None                      # coincident points: nothing to undo
    u = geo.sub(a_hr, a_co)              # line of the outgoing handle
    v = geo.sub(b_hl, b_co)              # line of the incoming handle
    uu, vv = geo.dot(u, u), geo.dot(v, v)
    if uu < geo.EPS or vv < geo.EPS:
        return None                      # a handle sitting on its own point
    uv = geo.dot(u, v)
    denom = uu * vv - uv * uv            # equals uu * vv * sin(angle)**2
    if denom <= uu * vv * SIN_TOL ** 2:
        return None                      # parallel: straight, or a half turn
    w = geo.sub(a_co, b_co)
    wu, wv = geo.dot(w, u), geo.dot(w, v)
    s = (wv * uv - wu * vv) / denom      # along u, from the first point
    t = (wv * uu - wu * uv) / denom      # along v, from the second one
    if s <= 0.0 or t <= 0.0:
        return None                      # they would meet behind the points
    reach = MAX_REACH * chord
    if s * math.sqrt(uu) > reach or t * math.sqrt(vv) > reach:
        return None                      # almost straight, or almost a half turn
    p = geo.add(a_co, geo.mul(u, s))
    q = geo.add(b_co, geo.mul(v, t))
    if geo.distance(p, q) > MEET_TOL * chord:
        return None                      # skew handles: they never meet
    return geo.lerp(p, q, 0.5)


def _corner_data(a, b, co):
    """The new control point of the corner, between the points `a` and `b`.

    Vector handles, so each side stays aimed at its neighbour and the two
    straight sides of the corner are kept even if the points are moved later.
    Radius, tilt and softbody weight are the average of both points, so a
    bevel or a taper along the curve does not jump at the corner.
    """
    return sd.PointData(
        co=co,
        hl=geo.lerp(co, a.co, 1.0 / 3.0),
        hr=geo.lerp(co, b.co, 1.0 / 3.0),
        hlt='VECTOR',
        hrt='VECTOR',
        radius=(a.radius + b.radius) * 0.5,
        tilt=(a.tilt + b.tilt) * 0.5,
        weight_softbody=(a.weight_softbody + b.weight_softbody) * 0.5,
        select=False,
    )


def with_corners(data):
    """Copy of the Bezier spline `data` with a corner in every selected segment.

    Returns (new spline, corners made, segments left alone). The new spline is
    None when no corner could be made, and then nothing of the original is
    touched.
    """
    pts = data.points
    n = len(pts)
    if data.kind != 'BEZIER' or n < 2:
        return None, 0, 0

    # A segment counts when both of its control points are selected: a handle
    # on its own does not pick a segment, the pair of points does.
    corners = {}
    skipped = 0
    for i in range(n if data.cyclic else n - 1):
        j = (i + 1) % n
        if not (pts[i].select and pts[j].select):
            continue
        co = corner_point(pts[i].co, pts[i].hr, pts[j].hl, pts[j].co)
        if co is None:
            skipped += 1
            continue
        corners[i] = co
    if not corners:
        return None, 0, skipped

    out = data.copy()
    members = set()
    for i in corners:
        members.update((i, (i + 1) % n))

    # Auto handles of the two points, on both sides, are pinned where they are:
    # the corner becomes a new neighbour, and Blender would recompute them from
    # it, bending the previous and the next segment as well.
    for k in members:
        p = out.points[k]
        if p.hlt == 'AUTO':
            p.hlt = 'FREE'
        if p.hrt == 'AUTO':
            p.hrt = 'FREE'

    # The handles that shaped the segment now aim at the corner, at a third of
    # the way, which is the straight-line length Vector handles would take.
    for i, co in corners.items():
        a, b = out.points[i], out.points[(i + 1) % n]
        a.hr = geo.lerp(a.co, co, 1.0 / 3.0)
        a.hrt = sd.settle_handle_type(a.hrt)
        b.hl = geo.lerp(b.co, co, 1.0 / 3.0)
        b.hlt = sd.settle_handle_type(b.hlt)

    # The selection is left saying exactly which points the corners came from,
    # so that a Dissolve right after removes those and nothing else.
    for p in out.points:
        p.select = p.select_left = p.select_right = False
    for k in members:
        p = out.points[k]
        p.select = p.select_left = p.select_right = True

    points = []
    for i, p in enumerate(out.points):
        points.append(p)
        if i in corners:
            points.append(_corner_data(p, out.points[(i + 1) % n], corners[i]))
    out.points = points
    return out, len(corners), skipped


def _has_selected_pair(data):
    """True when the spline has two consecutive selected control points."""
    pts = data.points
    n = len(pts)
    if n < 2:
        return False
    return any(pts[i].select and pts[(i + 1) % n].select
               for i in range(n if data.cyclic else n - 1))


# -----------------------------------------------------------------------------
# Operator
# -----------------------------------------------------------------------------

class ETR_OT_curve_toolkit_arcs_to_corners(bpy.types.Operator):
    """Bring back the hard corner a curved segment was rounded from: for every pair of consecutive selected control points, the two handles of the segment between them are prolonged until they meet and a new control point with Vector handles is placed there, so both sides of the corner are straight. A segment whose handles do not meet in front of both points (a straight one, a half turn, an S shape, or handles not in the same plane in 3D) is left alone. The two original points stay selected and the corner does not, so a Dissolve afterwards leaves only the corner. Bezier splines"""
    bl_idname = "etr.curve_toolkit_arcs_to_corners"
    bl_label = "Arcs to Corners"
    bl_options = {'REGISTER', 'UNDO'}

    dissolve_originals: BoolProperty(
        name="Dissolve Originals",
        description=(
            "Remove the two original control points right away, leaving only "
            "the new corner (Blender's own Dissolve Vertices, which refits the "
            "segments around it). Off by default, so the curvature next to the "
            "corner can be looked at first"
        ),
        default=False,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == EDIT_MODE and has_active_curve(context)

    def execute(self, context):
        made = skipped = other_types = 0

        with edit_scope(context) as objs:
            for obj in objs:
                datas = sd.read_all(obj.data)
                dirty = False
                for i, d in enumerate(datas):
                    if d.kind != 'BEZIER':
                        other_types += _has_selected_pair(d)
                        continue
                    new, n_made, n_skipped = with_corners(d)
                    made += n_made
                    skipped += n_skipped
                    if new is not None:
                        datas[i] = new
                        dirty = True
                if dirty:
                    sd.replace_splines(obj.data, datas)

        if other_types:
            self.report(
                {'WARNING'},
                f"{other_types} Poly or NURBS spline(s) ignored: Arcs to Corners "
                "needs Bezier handles (Curve > Set Spline Type > Bezier)",
            )
        if not made:
            if not (skipped or other_types):
                self.report(
                    {'WARNING'},
                    "Select two consecutive control points of a curved segment",
                )
            elif skipped:
                self.report(
                    {'WARNING'},
                    f"{skipped} segment(s) left alone: their handles do not meet "
                    "in front of both points",
                )
            return {'CANCELLED'}

        if self.dissolve_originals and context.mode == EDIT_MODE:
            try:
                bpy.ops.curve.dissolve_verts()
            except RuntimeError:
                self.report({'WARNING'}, "The original points could not be dissolved")

        message = f"{made} corner(s) created"
        if skipped:
            message += (f"; {skipped} segment(s) left alone (their handles do not "
                        "meet in front of both points)")
        self.report({'INFO'}, message)
        return {'FINISHED'}


# -----------------------------------------------------------------------------

classes = (ETR_OT_curve_toolkit_arcs_to_corners,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
