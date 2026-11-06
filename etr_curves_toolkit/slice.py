# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Slice and Undo Slice (Edit Mode)

Slice divides a shape with "partition walls": double seams placed exactly
where the user wants them. It removes holes (the hole becomes part of its
outer spline) and it breaks a complex closed shape into simpler ones, the way
a field is divided into plots. Undo Slice takes a seam away again, at any
later moment (it is not Blender's undo: the user picks the seam to remove).

A curve with a hole (a closed spline inside another, in the same object) is
filled by Geometry Nodes' Fill Curve as one N-gon, and the edges it adds to
reach the hole land wherever the triangulation puts them. Once the N-gon is
extruded and bevelled, those unpredictable edges are the source of artifacts.

Two points on two different closed splines: Slice joins them into one with
a "double connection" at the place the user chooses: point A on one spline and point B on the other
are linked by two straight segments, one going and one coming back. A and B
are duplicated (A1, A2 and B1, B2), and each pair is coincident but not
merged. Topologically the hole is no longer a hole: it is the inside of a
single closed outline, opened by a slit of zero width along A-B, and the only
inner edge is the one the user picked.

    outer:  ... -> A1 -> B1 -> (around the hole) -> B2 -> A2 -> ...

The two bridge segments have Vector handles. The other handle of A1, A2, B1
and B2 keeps its place (Auto and Aligned handles become Free, so Blender does
not recalculate them), so the shape of both splines is unchanged.

Two points on the same closed spline: the same double connection cuts it in
two along the straight line between them. The spline becomes two closed ones,
each with its own copy of the segment P-Q, again coincident and not merged:

    spline:  P -> ... -> Q -> ... -> (back to P)
    first:   P1 -> ... -> Q1 -> (P1)       second:  Q2 -> ... -> P2 -> (Q2)

That is how further seams are added once a hole is joined (its two points
now belong to the same spline), as many as the user wants and wherever they
want them: with two seams per hole Fill Curve has no edge left to place.

What Fill Curve makes of it: it welds coincident points, and a face of
Blender cannot pass through the same vertex twice, so a ring is always at
least two faces. After one Slice, one of the edges inside is the A-B the
user picked and Fill Curve still places the other one.

For the joined outline to be simple, the hole has to be travelled in the
opposite direction to the outer spline; its direction is inverted when it is
not. Two closed splines side by side (neither inside the other) can be joined
the same way: they then travel in the same direction.

Bezier and Poly splines (a Poly one joined to a Bezier one becomes Bezier).

Undo Slice: the user selects the two pairs of coincident points of a seam
(A1 and A2, B1 and B2; selecting one point of each pair is enough, its
coincident partner is found). The two straight segments of the seam are
removed and each pair is merged back into a single point, so the splines are
what they were before the Slice: a joined hole becomes a hole again, and a
spline cut in two becomes one. The merged points keep the incoming and
outgoing handles of the shape (Free, since the Slice made them Free), so
the shape does not change.
"""

import bpy

from . import geometry as geo
from . import spline_data as sd
from .context_utils import EDIT_MODE, edit_scope, has_active_curve

TOOL = "Slice"
_FLATTEN_STEPS = 12


class Fail(Exception):
    """A message for the user; nothing has been changed."""


def _poll(cls, context):
    if context.mode == EDIT_MODE and has_active_curve(context):
        return True
    cls.poll_message_set("Works in the Edit Mode of a curve: select two points of "
                         "closed splines (Slice) or the two pairs of points of a seam "
                         "(Undo Slice)")
    return False


# -----------------------------------------------------------------------------
# Plane, orientation and containment of the two splines
# -----------------------------------------------------------------------------

def _newell(poly):
    """Newell normal of a closed polyline (its length is twice the area)."""
    nx = ny = nz = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0, z0 = poly[i]
        x1, y1, z1 = poly[(i + 1) % n]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    return (nx, ny, nz)


def _basis(normal):
    """Two unit vectors spanning the plane perpendicular to `normal`."""
    n = geo.normalized(normal)
    helper = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = geo.normalized(geo.cross(helper, n))
    v = geo.cross(n, u)
    return u, v


def _signed_area(poly2d):
    area = 0.0
    n = len(poly2d)
    for i in range(n):
        x0, y0 = poly2d[i]
        x1, y1 = poly2d[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    return 0.5 * area


def _inside(pt, poly2d):
    """Even-odd point in polygon test."""
    x, y = pt
    inside = False
    n = len(poly2d)
    for i in range(n):
        x0, y0 = poly2d[i]
        x1, y1 = poly2d[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            if x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                inside = not inside
    return inside


def _polyline(data):
    pts = sd.flatten(data, _FLATTEN_STEPS)
    if len(pts) > 1 and geo.distance(pts[0], pts[-1]) < 1e-12:
        pts = pts[:-1]
    return pts


def _relation(first, second):
    """How two closed splines sit: (outer index (0 or 1), nested, same
    direction)."""
    p1, p2 = _polyline(first), _polyline(second)
    n1, n2 = _newell(p1), _newell(p2)
    ref = n1 if geo.length(n1) >= geo.length(n2) else n2
    if geo.length(ref) < 1e-12:
        raise Fail(f"{TOOL}: the splines have no area")
    u, v = _basis(ref)
    flat1 = [(geo.dot(p, u), geo.dot(p, v)) for p in p1]
    flat2 = [(geo.dot(p, u), geo.dot(p, v)) for p in p2]
    a1, a2 = _signed_area(flat1), _signed_area(flat2)
    same = (a1 > 0.0) == (a2 > 0.0)
    if _inside(_centroid_probe(flat2), flat1) and abs(a1) >= abs(a2):
        return 0, True, same
    if _inside(_centroid_probe(flat1), flat2) and abs(a2) >= abs(a1):
        return 1, True, same
    # Side by side: the bigger one leads.
    return (0 if abs(a1) >= abs(a2) else 1), False, same


def _centroid_probe(poly2d):
    """A point that belongs to the outline (its first vertex). Any point of a
    hole is inside the outer spline, so one is enough."""
    return poly2d[0]


# -----------------------------------------------------------------------------
# Join
# -----------------------------------------------------------------------------

def _bridge_point(p, towards, side):
    """Copy of point `p` whose handle on `side` ('LEFT' or 'RIGHT') becomes a
    Vector handle pointing at `towards`; the other one keeps its place."""
    q = sd.replace(p)
    vector = geo.lerp(p.co, towards, 1.0 / 3.0)
    if side == 'LEFT':
        q.hl, q.hlt = vector, 'VECTOR'
        q.hrt = sd.settle_handle_type(p.hrt)
    else:
        q.hr, q.hrt = vector, 'VECTOR'
        q.hlt = sd.settle_handle_type(p.hlt)
    q.select = True
    q.select_left = q.select_right = False
    return q


def join_splines(outer, a, hole, b):
    """Join two closed splines with a double connection between point `a` of
    `outer` and point `b` of `hole`. `hole` must already travel in the right
    direction. Returns the new SplineData."""
    kind = 'BEZIER' if 'BEZIER' in (outer.kind, hole.kind) else 'POLY'
    if kind == 'BEZIER':
        outer, hole = sd.to_bezier(outer), sd.to_bezier(hole)
    o = sd.rotated(outer, a).points
    h = sd.rotated(hole, b).points
    pa, pb = o[0], h[0]

    if kind == 'BEZIER':
        a2 = _bridge_point(pa, pb.co, 'LEFT')      # comes back from B2
        a1 = _bridge_point(pa, pb.co, 'RIGHT')     # goes to B1
        b1 = _bridge_point(pb, pa.co, 'LEFT')      # comes from A1
        b2 = _bridge_point(pb, pa.co, 'RIGHT')     # goes back to A2
    else:
        a1, a2, b1, b2 = (sd.replace(p, select=True) for p in (pa, pa, pb, pb))

    out = outer.copy()
    out.kind = kind
    out.cyclic = True
    out.points = [a2, *o[1:], a1, b1, *h[1:], b2]
    return out


def cut_spline(data, p, q):
    """Cut a closed spline in two along the straight segment between its points
    `p` and `q` (p < q). Returns the two new SplineData: p..q and q..p, each
    closed by its own copy of the segment."""
    kind = data.kind
    pts = data.points
    pp, pq = pts[p], pts[q]
    if kind == 'BEZIER':
        p1 = _bridge_point(pp, pq.co, 'LEFT')     # first loop: comes from Q1
        q1 = _bridge_point(pq, pp.co, 'RIGHT')    # goes back to P1
        q2 = _bridge_point(pq, pp.co, 'LEFT')     # second loop: comes from P2
        p2 = _bridge_point(pp, pq.co, 'RIGHT')    # goes back to Q2
    else:
        p1, q1, q2, p2 = (sd.replace(x, select=True) for x in (pp, pq, pq, pp))
    first, second = data.copy(), data.copy()
    first.points = [p1, *pts[p + 1:q], q1]
    second.points = [q2, *pts[q + 1:], *pts[:p], p2]
    first.cyclic = second.cyclic = True
    return first, second


def _check_cut(data, p, q):
    """Refuse cuts that would leave a loop with no area."""
    n = len(data.points)
    if geo.distance(data.points[p].co, data.points[q].co) < 1e-9:
        raise Fail(f"{TOOL}: the two points are at the same place")
    # A loop made of a single segment plus the cut only has an area when that
    # segment is curved.
    for a, b in ((p, q), (q, p)):
        if (b - a) % n == 1:
            pa, pb = data.points[a], data.points[b]
            if data.kind != 'BEZIER' or geo.is_straight_segment(pa.co, pa.hr, pb.hl, pb.co):
                raise Fail(f"{TOOL}: the two points are neighbours joined by a straight "
                           "segment; there is nothing to cut")


def _selected_points(objs):
    """[(obj, snapshots, spline index, point index)] of the selected control
    points."""
    found = []
    for obj in objs:
        datas = sd.read_all(obj.data)
        for i, data in enumerate(datas):
            for k, p in enumerate(data.points):
                if p.select:
                    found.append((obj, datas, i, k))
    return found


def _check(found):
    if len(found) != 2:
        raise Fail(f"{TOOL} needs exactly two selected points ({len(found)} selected)")
    (obj1, datas, i1, _), (obj2, _, i2, _) = found
    if obj1 != obj2:
        raise Fail(f"{TOOL}: both points must be in the same curve object "
                   "(join the curves first)")
    for i in {i1, i2}:
        d = datas[i]
        if d.kind == 'NURBS':
            raise Fail(f"{TOOL}: NURBS splines are not supported")
        if not d.cyclic:
            raise Fail(f"{TOOL}: the splines must be closed (Cyclic)")
        if len(d.points) < 2:
            raise Fail(f"{TOOL}: a spline needs at least two points")


class ETR_OT_curve_toolkit_slice(bpy.types.Operator):
    """Divide a shape with a double seam between two selected points: two coincident straight segments, not merged. On a hole and its outer spline it joins them (no more hole); on the same closed spline it cuts it in two simpler shapes. Places the seams Fill Curve would otherwise choose. Bezier and Poly. Edit Mode"""
    bl_idname = "etr.curve_toolkit_slice"
    bl_label = "Slice"
    bl_options = {'REGISTER', 'UNDO'}

    poll = classmethod(_poll)

    def _cut(self, obj, datas, i, p, q):
        data = datas[i]
        _check_cut(data, p, q)
        for pt in data.points:
            pt.select = pt.select_left = pt.select_right = False
        first, second = cut_spline(data, p, q)
        datas[i:i + 1] = [first, second]
        sd.replace_splines(obj.data, datas)
        self.report({'INFO'}, f"{TOOL}: the spline is now two, cut between the two points")

    def execute(self, context):
        try:
            with edit_scope(context) as objs:
                found = _selected_points(objs)
                _check(found)
                (obj, datas, i1, k1), (_, _, i2, k2) = found
                if i1 == i2:
                    self._cut(obj, datas, i1, *sorted((k1, k2)))
                    return {'FINISHED'}
                first, second = datas[i1], datas[i2]
                lead, nested, same = _relation(first, second)
                if lead == 1:
                    (i1, k1), (i2, k2) = (i2, k2), (i1, k1)
                    first, second = second, first
                # Nested: opposite directions. Side by side: the same one.
                if same == nested:
                    second = sd.inverted(second)
                    k2 = (len(second.points) - k2) % len(second.points)
                for d in (first, second):
                    for p in d.points:
                        p.select = p.select_left = p.select_right = False
                joined = join_splines(first, k1, second, k2)
                keep = min(i1, i2)
                drop = max(i1, i2)
                datas[keep] = joined
                del datas[drop]
                sd.replace_splines(obj.data, datas)
        except Fail as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        if nested:
            self.report({'INFO'}, f"{TOOL}: the hole is now part of its outer spline")
        else:
            self.report({'INFO'}, f"{TOOL}: the two splines are now one closed spline")
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Undo Slice
# -----------------------------------------------------------------------------

UNDO = "Undo Slice"


def _size(datas):
    """Largest extent of the snapshots (for relative tolerances)."""
    coords = [p.co for d in datas for p in d.points]
    if not coords:
        return 1.0
    return max(max(c[i] for c in coords) - min(c[i] for c in coords) for i in range(3)) or 1.0


def _complete_pairs(datas, picks, tol):
    """The picked points plus, for every picked point that has no coincident
    partner among them, its coincident partner in the curve (there must be
    exactly one). Clicking on two coincident points selects only one of
    them, so one point per pair is enough."""
    picks = list(picks)
    out = list(picks)
    for s, k in picks:
        co = datas[s].points[k].co
        if any((t, m) != (s, k) and geo.distance(co, datas[t].points[m].co) <= tol
               for t, m in picks):
            continue
        partners = [(t, m) for t, d in enumerate(datas) for m, p in enumerate(d.points)
                    if (t, m) != (s, k) and geo.distance(co, p.co) <= tol]
        if len(partners) != 1:
            raise Fail(f"{UNDO}: every selected point must have exactly one coincident "
                       f"point (the other side of the seam); one has {len(partners)}")
        out.append(partners[0])
    return out


def _two_pairs(datas, picks, tol):
    """{(spline, point): pair id (0 or 1)} for four picks that make two pairs
    of coincident points, at two different places."""
    if len(picks) != 4:
        raise Fail(f"{UNDO} needs the two pairs of coincident points of a seam "
                   f"({len(picks)} points selected)")
    co = [datas[s].points[k].co for s, k in picks]
    for a, b, c, d in ((0, 1, 2, 3), (0, 2, 1, 3), (0, 3, 1, 2)):
        if (geo.distance(co[a], co[b]) <= tol and geo.distance(co[c], co[d]) <= tol
                and geo.distance(co[a], co[c]) > tol):
            return {picks[a]: 0, picks[b]: 0, picks[c]: 1, picks[d]: 1}
    raise Fail(f"{UNDO}: the selected points are not two pairs of coincident points "
               "at two different places")


def _chains(datas, pair_of):
    """The pieces of the involved splines once the two straight segments of
    the seam are taken away: lists of (spline, point), each going from one
    end of the seam to the next one."""
    splines = sorted({s for s, _ in pair_of})
    chains = []
    bridges = 0
    for s in splines:
        n = len(datas[s].points)
        starts = [k for k in range(n)
                  if (s, k) in pair_of and (s, (k + 1) % n) in pair_of
                  and pair_of[(s, k)] != pair_of[(s, (k + 1) % n)]]
        bridges += len(starts)
        for i, k in enumerate(starts):
            end = starts[(i + 1) % len(starts)]
            chain = [(s, (k + 1) % n)]
            while chain[-1][1] != end:
                chain.append((s, (chain[-1][1] + 1) % n))
            chains.append(chain)
    ends = [c[0] for c in chains] + [c[-1] for c in chains]
    if bridges != 2 or sorted(ends) != sorted(pair_of):
        raise Fail(f"{UNDO}: the selected points are not the two ends of a seam made by "
                   "Slice (two coincident straight segments between them)")
    return chains


def undo_slice(datas, picks, tol):
    """New list of snapshots with the seam between the picked points removed.
    Returns (datas, number of splines before, number after)."""
    pair_of = _two_pairs(datas, picks, tol)
    involved = sorted({s for s, _ in pair_of})
    for s in involved:
        d = datas[s]
        if d.kind == 'NURBS':
            raise Fail(f"{UNDO}: NURBS splines are not supported")
        if not d.cyclic:
            raise Fail(f"{UNDO}: the seam must be on closed (Cyclic) splines")
    kind = 'BEZIER' if any(datas[s].kind == 'BEZIER' for s in involved) else 'POLY'
    work = {s: (sd.to_bezier(datas[s]) if kind == 'BEZIER' else datas[s].copy())
            for s in involved}
    chains = _chains(datas, pair_of)

    def point(ref):
        return work[ref[0]].points[ref[1]]

    partner = {}
    for ref, pid in pair_of.items():
        partner[ref] = next(r for r, q in pair_of.items() if q == pid and r != ref)
    by_first = {c[0]: i for i, c in enumerate(chains)}

    loops = []
    done = set()
    for start in range(len(chains)):
        if start in done:
            continue
        order = []
        i = start
        while i not in done:
            done.add(i)
            order.append(chains[i])
            nxt = partner[chains[i][-1]]
            if nxt not in by_first:
                raise Fail(f"{UNDO}: the seam cannot be removed from these points")
            i = by_first[nxt]
        if i != start:
            raise Fail(f"{UNDO}: the seam cannot be removed from these points")
        pts = []
        for j, chain in enumerate(order):
            merged = sd.merge_points(point(order[j - 1][-1]), point(chain[0]))
            merged.select = True
            merged.select_left = merged.select_right = False
            pts.append(merged)
            pts += [sd.replace(point(ref)) for ref in chain[1:-1]]
        if len(pts) < 2:
            raise Fail(f"{UNDO}: the seam cannot be removed from these points")
        loop = work[involved[0]].copy()
        loop.kind = kind
        loop.cyclic = True
        loop.points = pts
        loops.append(loop)

    out = []
    for s, d in enumerate(datas):
        if s == involved[0]:
            out += loops
        elif s not in involved:
            out.append(d)
    return out, len(involved), len(loops)


class ETR_OT_curve_toolkit_undo_slice(bpy.types.Operator):
    """Remove a seam made by Slice, at any moment: select its two pairs of coincident points (one point of each pair is enough). Each pair is merged back into one point and the shape is what it was before that Slice. Bezier and Poly. Edit Mode"""
    bl_idname = "etr.curve_toolkit_undo_slice"
    bl_label = "Undo Slice"
    bl_options = {'REGISTER', 'UNDO'}

    poll = classmethod(_poll)

    def execute(self, context):
        try:
            with edit_scope(context) as objs:
                found = _selected_points(objs)
                if not found:
                    raise Fail(f"{UNDO}: select the two pairs of coincident points of a seam")
                if len({id(obj) for obj, _, _, _ in found}) > 1:
                    raise Fail(f"{UNDO}: the points must be in the same curve object")
                obj, datas = found[0][0], found[0][1]
                tol = 1e-6 * _size(datas)
                picks = _complete_pairs(datas, [(i, k) for _, _, i, k in found], tol)
                for d in datas:
                    for p in d.points:
                        p.select = p.select_left = p.select_right = False
                new, before, after = undo_slice(datas, picks, tol)
                sd.replace_splines(obj.data, new)
        except Fail as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        if before == 1:
            self.report({'INFO'}, f"{UNDO}: the seam is gone; the spline is two again")
        else:
            self.report({'INFO'}, f"{UNDO}: the seam is gone; the two splines are one again")
        return {'FINISHED'}


classes = (
    ETR_OT_curve_toolkit_slice,
    ETR_OT_curve_toolkit_undo_slice,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
