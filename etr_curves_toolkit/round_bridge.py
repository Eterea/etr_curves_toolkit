# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Round Corners and Bridge Curves (Edit Mode)

Round Corners
    Replaces each selected corner by an arc tangent to both sides (a true
    fillet, also between curved segments), keeping the rest of the curve
    unchanged. Radius and Tension are editable in the Adjust Last Operation
    panel (F9): Tension 1.0 is a circular arc, 0.0 a straight bevel, higher
    values stretch the handles. Works on Poly and Bezier splines; a Poly spline
    becomes a Bezier spline (the untouched corners keep Vector handles).

Bridge Curves
    With exactly two end points selected (of two spline ends, in one or in two
    curve objects), creates a Bezier segment that leaves each end along its
    tangent. The Tension (default 1.0, no upper limit) sets the length of its
    handles: 0.0 gives a straight segment. Two splines of the same object are
    welded into a single Bezier spline; two curve objects produce a new
    "Bridge" object and the originals are not modified.
"""

import bpy
from bpy.props import FloatProperty
from mathutils import Vector

from . import geometry as geo
from . import spline_data as sd
from .context_utils import (
    EDIT_MODE,
    edit_scope,
    has_active_curve,
    link_like,
    new_curve_object,
    world_matrix,
)


def _poll_edit(cls, context):
    return context.mode == EDIT_MODE and has_active_curve(context)


# -----------------------------------------------------------------------------
# Corner analysis
# -----------------------------------------------------------------------------

def _neighbour_indices(d, i):
    """Indices of the previous and next points, or None where the spline ends."""
    n = len(d.points)
    prev = (i - 1) % n if (i > 0 or d.cyclic) else None
    nxt = (i + 1) % n if (i < n - 1 or d.cyclic) else None
    return prev, nxt


def _segment_is_straight(d, a, b):
    """True if the segment from point index a to b (consecutive) is straight."""
    if d.kind != 'BEZIER':
        return True
    pa, pb = d.points[a], d.points[b]
    return geo.is_straight_segment(pa.co, pa.hr, pb.hl, pb.co)


def _corner_kind(d, i):
    """Classify point i of a spline.

    Returns 'STRAIGHT' (corner between two straight segments), 'CURVED'
    (corner with at least one curved segment) or None (end point, or the
    tangents are continuous: not a corner).
    """
    prev, nxt = _neighbour_indices(d, i)
    # A closed spline of 2 points has the same point on both sides (two
    # segments between the same pair of points): still a valid corner.
    if prev is None or nxt is None or (prev == nxt and not d.cyclic):
        return None
    if _segment_is_straight(d, prev, i) and _segment_is_straight(d, i, nxt):
        return 'STRAIGHT'
    p, a, b = d.points[i], d.points[prev], d.points[nxt]
    t_in = geo.tangent_at_end(p.co, p.hl, a.co, a.hr)
    t_out = geo.tangent_at_end(p.co, p.hr, b.co, b.hl)
    if t_in is None or t_out is None:
        return None
    # t_in points back along the previous segment; for a smooth point it is
    # opposite to t_out.
    if geo.dot(t_in, t_out) < -1.0 + 1e-6:
        return None
    return 'CURVED'


# -----------------------------------------------------------------------------
# Round Corners
# -----------------------------------------------------------------------------

def _segment_controls(d, a, b):
    """Control points (p0, h0, h1, p1) of the segment from point a to b."""
    pa, pb = d.points[a], d.points[b]
    return pa.co, pa.hr, pb.hl, pb.co


def _round_spline(d, radius, tension):
    """Round the selected corners of a spline snapshot.

    Every corner is replaced by the anchors of its fillet (see
    geometry.fillet_anchors). The segments next to a rounded corner are cut
    exactly at the tangent points: straight segments stay straight lines, and
    curved ones are trimmed with de Casteljau, so their shape does not change.

    Returns (new SplineData or None if nothing changed, rounded, clamped,
    failed).
    """
    n = len(d.points)
    kinds = {i: _corner_kind(d, i) for i, p in enumerate(d.points) if p.select}
    corners = [i for i, k in kinds.items() if k is not None]
    if not corners:
        return None, 0, 0, 0

    work = sd.to_bezier(d) if d.kind == 'POLY' else d.copy()
    corner_set = set(corners)

    # 1. Fillet of every corner.
    fillets = {}
    clamped = failed = 0
    for i in corners:
        prev, nxt = _neighbour_indices(work, i)
        # When the neighbouring corner is also rounded, each fillet may use at
        # most half of the segment between them.
        shared_prev, shared_next = prev in corner_set, nxt in corner_set
        if kinds[i] == 'STRAIGHT':
            a, p, b = work.points[prev].co, work.points[i].co, work.points[nxt].co
            f = geo.fillet_straight_corner(
                a, p, b, radius,
                max_tangent_prev=geo.distance(a, p) * (0.5 if shared_prev else 1.0),
                max_tangent_next=geo.distance(b, p) * (0.5 if shared_next else 1.0),
            )
        else:
            f = geo.fillet_curved_corner(
                _segment_controls(work, prev, i),
                _segment_controls(work, i, nxt),
                radius,
                u_min=0.5 if shared_prev else 0.0,
                v_max=0.5 if shared_next else 1.0,
            )
        if f is None:
            failed += 1
            continue
        if f.radius < radius * (1.0 - 1e-6):
            clamped += 1
        fillets[i] = f

    if not fillets:
        return None, 0, 0, failed

    # 2. New point list: corners replaced by their fillet anchors.
    nodes = []
    touched = []
    first_of, last_of = {}, {}
    for i, p in enumerate(work.points):
        first_of[i] = len(nodes)
        if i in fillets:
            for pos, hl, hr in geo.fillet_anchors(fillets[i], tension):
                touched.append(len(nodes))
                q = sd.replace(p)
                q.co, q.hl, q.hr = pos, hl, hr
                q.hlt = q.hrt = 'FREE'
                q.w = 1.0
                q.select = q.select_left = q.select_right = True
                nodes.append(q)
        else:
            nodes.append(sd.replace(p))
        last_of[i] = len(nodes) - 1

    # 3. Segments next to a rounded corner: trim them at the tangent points.
    seg_count = n if work.cyclic else n - 1
    for k in range(seg_count):
        k2 = (k + 1) % n
        if k not in fillets and k2 not in fillets:
            continue
        a, b = nodes[last_of[k]], nodes[first_of[k2]]
        if _segment_is_straight(work, k, k2):
            a.hr, a.hrt = geo.lerp(a.co, b.co, 1.0 / 3.0), 'VECTOR'
            b.hl, b.hlt = geo.lerp(b.co, a.co, 1.0 / 3.0), 'VECTOR'
        else:
            s = fillets[k].v if k in fillets else 0.0
            e = fillets[k2].u if k2 in fillets else 1.0
            sub = geo.bezier_sub(*_segment_controls(work, k, k2), s, e)
            a.hr, a.hrt = sub[1], 'FREE'
            b.hl, b.hlt = sub[2], 'FREE'
        # An original point whose neighbour changed: freeze its other handle
        # (Auto and Aligned handles would be recalculated by Blender).
        if k not in fillets:
            a.hlt = sd.settle_handle_type(a.hlt)
        if k2 not in fillets:
            b.hrt = sd.settle_handle_type(b.hrt)

    # 4. A fillet that uses a whole segment ends on the next point: weld the
    #    two coincident points into one.
    nodes, touched = _weld_coincident(nodes, set(touched), work.cyclic)

    out = work.copy()
    out.points = nodes
    finalize_handle_types(out, sorted(touched))
    return out, len(fillets), clamped, failed


def _weld_coincident(nodes, touched, cyclic, eps=1e-8):
    """Merge consecutive coincident points. Returns (points, touched indices)."""
    out, out_touched = [], set()
    for i, q in enumerate(nodes):
        if out and geo.distance(out[-1].co, q.co) < eps:
            out[-1] = sd.merge_points(out[-1], q)
            if i in touched:
                out_touched.add(len(out) - 1)
            continue
        out.append(q)
        if i in touched:
            out_touched.add(len(out) - 1)
    if cyclic and len(out) > 2 and geo.distance(out[-1].co, out[0].co) < eps:
        last = len(out) - 1
        out[0] = sd.merge_points(out[-1], out[0])
        if last in out_touched:
            out_touched.discard(last)
            out_touched.add(0)
        out.pop()
    return out, out_touched


def finalize_handle_types(d, indices):
    """Handle types of the points created or joined by Round and Bridge.

    - A side that runs along a straight segment gets a Vector handle (at one
      third of the segment, like Blender does). This also turns the
      zero-length handles of a Tension 0.0 bevel or bridge into Vector ones,
      so those points can be selected and rounded again.
    - A point between two curved segments gets Aligned handles, so moving one
      handle moves the other and no pinch appears.
    - A curved side whose handle goes on in line with a straight side (the
      two ends of a round between straight segments) gets an Aligned handle
      next to the Vector one.
    - Any other curved side stays Free.
    Finally every Vector handle of the spline is placed at one third.
    """
    pts = d.points
    for i in indices:
        p = pts[i]
        prev, nxt = _neighbour_indices(d, i)
        left = None if prev is None else _segment_is_straight(d, prev, i)
        right = None if nxt is None else _segment_is_straight(d, i, nxt)
        if left is False and right is False:
            p.hlt = p.hrt = 'ALIGNED'
            continue
        if left is not None:
            p.hlt = 'VECTOR' if left else 'FREE'
        if right is not None:
            p.hrt = 'VECTOR' if right else 'FREE'
        # Where a straight side meets a curved one with tangent continuity
        # (the ends of a round), the curved handle is Aligned: Blender keeps
        # it in line with the Vector handle, so the joint stays smooth.
        if left and right is False and _continues(p.co, pts[prev].co, p.hr):
            p.hrt = 'ALIGNED'
        if right and left is False and _continues(p.co, pts[nxt].co, p.hl):
            p.hlt = 'ALIGNED'
        # At an open end, the outer handle follows the inner one when it is
        # a Vector handle (a straight end).
        if left is None and right:
            p.hlt = 'VECTOR'
        if right is None and left:
            p.hrt = 'VECTOR'
    _recompute_vector_handles(d)


def _continues(co, straight_to, handle, tol=1e-6):
    """True when `handle` points exactly away from `straight_to` (the far end
    of the straight side), so the curve goes on smoothly through `co`."""
    a = geo.normalized(geo.sub(straight_to, co))
    b = geo.normalized(geo.sub(handle, co))
    return a is not None and b is not None and geo.dot(a, b) < -1.0 + tol


def _recompute_vector_handles(d):
    """Put every Vector handle at one third of the way to its neighbour, as
    Blender does (the outer handle of an open end mirrors the inner one)."""
    pts = d.points
    for i, p in enumerate(pts):
        prev, nxt = _neighbour_indices(d, i)
        if p.hlt == 'VECTOR':
            if prev is not None:
                p.hl = geo.lerp(p.co, pts[prev].co, 1.0 / 3.0)
            elif nxt is not None:
                p.hl = geo.lerp(p.co, pts[nxt].co, -1.0 / 3.0)
        if p.hrt == 'VECTOR':
            if nxt is not None:
                p.hr = geo.lerp(p.co, pts[nxt].co, 1.0 / 3.0)
            elif prev is not None:
                p.hr = geo.lerp(p.co, pts[prev].co, -1.0 / 3.0)


class ETR_OT_curve_toolkit_round_corners(bpy.types.Operator):
    """Round the selected corners with arcs tangent to both sides, also between curved segments, without changing the rest of the curve. Radius and Tension in the F9 panel. Poly and Bezier"""
    bl_idname = "etr.curve_toolkit_round_corners"
    bl_label = "Round Corners"
    bl_options = {'REGISTER', 'UNDO'}

    radius: FloatProperty(
        name="Radius",
        description="Radius of the arcs. It is reduced where it does not fit",
        default=0.1,
        min=0.0001,
        precision=4,
        subtype='DISTANCE',
        unit='LENGTH',
    )
    tension: FloatProperty(
        name="Tension",
        description=(
            "Shape of the rounding: 1.0 is a circular arc, 0.0 a straight bevel, "
            "and higher values stretch the Bezier handles for a sharper rounding"
        ),
        default=1.0,
        min=0.0,
        soft_max=4.0,
        precision=3,
    )

    poll = classmethod(_poll_edit)

    def execute(self, context):
        rounded = clamped = failed = nurbs = 0
        with edit_scope(context) as objs:
            for obj in objs:
                datas = sd.read_all(obj.data)
                dirty = False
                for i, d in enumerate(datas):
                    if d.kind == 'NURBS':
                        nurbs += any(p.select for p in d.points)
                        continue
                    new, r, c, f = _round_spline(d, self.radius, self.tension)
                    rounded += r
                    clamped += c
                    failed += f
                    if new is not None:
                        datas[i] = new
                        dirty = True
                if dirty:
                    sd.replace_splines(obj.data, datas)

        if nurbs:
            self.report({'WARNING'}, "NURBS splines are not supported by Round Corners")
        if failed:
            self.report({'WARNING'}, f"{failed} corner(s) could not be rounded")
        if clamped:
            self.report({'INFO'}, f"Radius reduced on {clamped} corner(s) where it did not fit")
        if not rounded:
            if not (nurbs or failed):
                self.report({'WARNING'}, "No corners to round: select corner points in Edit Mode")
            return {'CANCELLED'}
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Bridge Curves
# -----------------------------------------------------------------------------

class _End:
    """A selected end point of an open spline."""

    def __init__(self, obj, spline_index, which, data):
        self.obj = obj
        self.spline_index = spline_index
        self.which = which            # 'start' or 'end'
        self.data = data              # SplineData (local space of obj)

    @property
    def point(self):
        return self.data.points[0 if self.which == 'start' else -1]

    def tangent_out(self):
        """Local-space unit tangent leaving the curve at this end."""
        pts = self.data.points
        if self.which == 'start':
            p, q = pts[0], pts[1]
            if self.data.kind == 'BEZIER':
                inward = geo.tangent_at_end(p.co, p.hr, q.co, q.hl)
            else:
                inward = geo.normalized(geo.sub(q.co, p.co))
        else:
            p, q = pts[-1], pts[-2]
            if self.data.kind == 'BEZIER':
                inward = geo.tangent_at_end(p.co, p.hl, q.co, q.hr)
            else:
                inward = geo.normalized(geo.sub(q.co, p.co))
        return None if inward is None else geo.mul(inward, -1.0)


def _to_space(end, ref):
    """(point, tangent) of an end expressed in the local space of `ref`."""
    p = Vector(end.point.co)
    t = end.tangent_out()
    if end.obj == ref:
        return tuple(p), t
    m = world_matrix(ref).inverted() @ world_matrix(end.obj)
    pt = m @ p
    tt = None if t is None else (m.to_3x3() @ Vector(t)).normalized()
    return tuple(pt), None if tt is None else tuple(tt)


def _bridge_handles(p0, t0, p1, t1, tension):
    """Handle positions of the bridge between p0 and p1 (tangents t0/t1 point
    away from their curves)."""
    dist = geo.distance(p0, p1)
    chord = geo.normalized(geo.sub(p1, p0))
    length = tension * dist / 3.0
    if t0 is None:
        t0 = chord or (1.0, 0.0, 0.0)
    if t1 is None:
        t1 = geo.mul(chord, -1.0) if chord else (-1.0, 0.0, 0.0)
    return geo.add(p0, geo.mul(t0, length)), geo.add(p1, geo.mul(t1, length))


class ETR_OT_curve_toolkit_bridge_curves(bpy.types.Operator):
    """Join two selected end points with a Bezier segment that follows the tangent of both curves. Tension in the F9 panel (0.0 straight, higher sharper)"""
    bl_idname = "etr.curve_toolkit_bridge_curves"
    bl_label = "Bridge Curves"
    bl_options = {'REGISTER', 'UNDO'}

    tension: FloatProperty(
        name="Tension",
        description="Curvature of the bridge: 0.0 is a straight segment, 1.0 a medium curvature, 2.0 and above sharper and sharper",
        default=1.0,
        min=0.0,
        soft_max=4.0,
        precision=3,
    )

    poll = classmethod(_poll_edit)

    def _collect_ends(self, objs):
        """Selected end points, or an error message."""
        ends = []
        for obj in objs:
            for si, d in enumerate(sd.read_all(obj.data)):
                chosen = [k for k, p in enumerate(d.points) if p.select]
                if not chosen:
                    continue
                if d.kind == 'NURBS':
                    return None, "Bridge works only with Poly and Bezier curves"
                n = len(d.points)
                for k in chosen:
                    if d.cyclic or n < 2 or k not in (0, n - 1):
                        return None, "Select only end points of open splines"
                    ends.append(_End(obj, si, 'start' if k == 0 else 'end', d))
        if len(ends) != 2:
            return None, f"Select exactly two end points (found {len(ends)})"
        return ends, None

    def execute(self, context):
        active = context.active_object
        with edit_scope(context) as objs:
            ends, error = self._collect_ends(objs)
            if error:
                self.report({'ERROR'}, error)
                return {'CANCELLED'}
            e0, e1 = ends
            ref = active if active in (e0.obj, e1.obj) else e0.obj
            if e0.obj == e1.obj and e0.spline_index == e1.spline_index and e0.which == e1.which:
                self.report({'ERROR'}, "Select two different end points")
                return {'CANCELLED'}

            if e0.obj != e1.obj:
                self._bridge_new_object(context, ref, e0, e1)
            else:
                self._bridge_same_object(e0, e1)
        return {'FINISHED'}

    # Two different curve objects: the bridge is a new object. ------------------

    def _bridge_new_object(self, context, ref, e0, e1):
        p0, t0 = _to_space(e0, ref)
        p1, t1 = _to_space(e1, ref)
        h0, h1 = _bridge_handles(p0, t0, p1, t1, self.tension)
        first = sd.PointData(co=p0, hl=p0, hr=h0, hlt='FREE', hrt='FREE', select=True)
        last = sd.PointData(co=p1, hl=h1, hr=p1, hlt='FREE', hrt='FREE', select=True)
        spline = sd.SplineData('BEZIER', [first, last], False, dict(e0.data.settings))
        finalize_handle_types(spline, [0, 1])
        obj = new_curve_object(context, ref, [spline], "Bridge")
        link_like(obj, ref, context)

    # Same object: both splines are welded into one Bezier spline. ---------------

    def _bridge_same_object(self, e0, e1):
        obj = e0.obj
        datas = sd.read_all(obj.data)
        p0, t0 = _to_space(e0, obj)
        p1, t1 = _to_space(e1, obj)
        h0, h1 = _bridge_handles(p0, t0, p1, t1, self.tension)

        if e0.spline_index == e1.spline_index:
            # Both ends of the same spline: the bridge closes it.
            d = sd.to_bezier(datas[e0.spline_index])
            tail, head = d.points[-1], d.points[0]
            # e0 is 'start' or 'end'; make `tail` match the end that is e-'end'.
            if e0.which == 'start':
                h_tail, h_head = h1, h0
            else:
                h_tail, h_head = h0, h1
            self._set_out_handle(tail, h_tail)
            self._set_in_handle(head, h_head)
            d.cyclic = True
            finalize_handle_types(d, [len(d.points) - 1, 0])
            datas[e0.spline_index] = d
        else:
            a_end, b_end = (e0, e1)
            a_h, b_h = h0, h1
            a = sd.to_bezier(datas[a_end.spline_index])
            b = sd.to_bezier(datas[b_end.spline_index])
            if a_end.which == 'start':
                a = sd.inverted(a)
            if b_end.which == 'end':
                b = sd.inverted(b)
            self._set_out_handle(a.points[-1], a_h)
            self._set_in_handle(b.points[0], b_h)
            merged = a.copy()
            merged.points = [sd.replace(p) for p in a.points] + [sd.replace(p) for p in b.points]
            finalize_handle_types(merged, [len(a.points) - 1, len(a.points)])
            lo, hi = sorted((a_end.spline_index, b_end.spline_index))
            datas[lo] = merged
            del datas[hi]
        sd.replace_splines(obj.data, datas)

    @staticmethod
    def _set_out_handle(point, handle):
        point.hlt = sd.settle_handle_type(point.hlt)
        point.hr = handle
        point.hrt = 'FREE'

    @staticmethod
    def _set_in_handle(point, handle):
        point.hrt = sd.settle_handle_type(point.hrt)
        point.hl = handle
        point.hlt = 'FREE'


# -----------------------------------------------------------------------------

classes = (
    ETR_OT_curve_toolkit_round_corners,
    ETR_OT_curve_toolkit_bridge_curves,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
