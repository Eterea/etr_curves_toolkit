# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Lines from Points

Joins every selected point with straight lines, without merging anything: the
new lines get points of their own, laid exactly over the selected ones. Meant
for construction guides, so the points do not have to be on one plane.

  - 2 points: one open, straight segment.
  - 3 or more: a closed shape through all of them (Closed, in F9, leaves it
    open instead). If they all lie on one straight line, an open line from
    one end to the other, since a closed shape would only fold back on itself.

  - Edit Mode of a curve: selected control points (handles do not count), of
    one curve or of several (multi-object editing). The lines are a new Poly
    spline of the active curve.
  - Edit Mode of a mesh: selected vertices, of one mesh or of several. The
    lines are new vertices and edges of the active mesh.

The Edit Mode is kept, and only the new points end up selected.

The order of the points
-----------------------
Blender does not keep the order in which control points are picked, so the
order is worked out from where the points are: the closed path through all of
them that has the shortest length (the "travelling salesman" tour). On a
plane, the shortest closed path never crosses itself, and when every point is
on the outline of a convex shape it is exactly that outline, in order. It
also goes in and out of some concave shapes (a cross, for one), when walking
the outline is shorter than cutting across.

Shapes drawn along the axes (a T, an H, an L, a stair...) are the exception:
their shortest path does cut across. So, when the points lie on an axis plane
(XY, XZ or YZ), they are first tried as the corners of an outline whose sides
all run along the axes. Such an outline is unique: on every line parallel to
an axis its corners pair up, first with second, third with fourth... When
those sides make one closed path through every point, with no crossings,
that is the shape.

Up to EXACT_LIMIT points the shortest path is found exactly (Held-Karp
dynamic programming). Beyond that, a very good one is found by building paths
from several starting points and improving them with 2-opt (which, with
straight-line distances, removes every crossing) and Or-opt moves.
"""

import itertools
import math

import bmesh
import bpy
from bpy.props import BoolProperty
from mathutils import Vector

from . import spline_data as sd
from .context_utils import EDIT_MODE, edit_scope, is_curve, world_matrix

EDIT_MESH = 'EDIT_MESH'

#: Largest number of points whose shortest closed path is found exactly.
EXACT_LIMIT = 12

#: Points closer than this (world units) count as the same point.
SAME_POINT = 1e-6


class Fail(Exception):
    """A message for the user; nothing has been changed."""


# -----------------------------------------------------------------------------
# Order of the points (pure Python, on tuples)
# -----------------------------------------------------------------------------

def _dist(a, b):
    return math.dist(a, b)


def _tour_length(points, order, dist=_dist, closed=True):
    total = sum(dist(points[i], points[j]) for i, j in zip(order, order[1:]))
    if closed and len(order) > 2:
        total += dist(points[order[-1]], points[order[0]])
    return total


def _held_karp(points, dist=_dist):
    """Exact shortest closed tour through every point (n >= 3).

    O(n^2 2^n): fine for the dozen points EXACT_LIMIT allows.
    """
    n = len(points)
    d = [[dist(a, b) for b in points] for a in points]
    # cost[(mask, j)]: shortest path from point 0 through the points of mask
    # (bits 1..n-1), ending at j.
    cost = {}
    for j in range(1, n):
        cost[(1 << j, j)] = (d[0][j], 0)
    for size in range(2, n):
        for subset in itertools.combinations(range(1, n), size):
            mask = 0
            for j in subset:
                mask |= 1 << j
            for j in subset:
                prev_mask = mask & ~(1 << j)
                best = None
                for k in subset:
                    if k == j:
                        continue
                    c = cost[(prev_mask, k)][0] + d[k][j]
                    if best is None or c < best[0]:
                        best = (c, k)
                cost[(mask, j)] = best
    full = (1 << n) - 2
    best_end = min(range(1, n), key=lambda j: cost[(full, j)][0] + d[j][0])
    order = []
    mask, j = full, best_end
    while j != 0:
        order.append(j)
        mask, j = mask & ~(1 << j), cost[(mask, j)][1]
    order.append(0)
    order.reverse()
    return order


def _nearest_neighbour(points, start, dist):
    left = set(range(len(points)))
    left.discard(start)
    order = [start]
    while left:
        last = points[order[-1]]
        nxt = min(left, key=lambda i: dist(last, points[i]))
        order.append(nxt)
        left.discard(nxt)
    return order


def _two_opt(points, order, dist):
    """Reverse stretches of the tour while that makes it shorter. With the
    straight-line distance, a tour that crosses itself can always be shortened
    this way, so none is left."""
    n = len(order)
    improved = True
    while improved:
        improved = False
        for i in range(n - 1):
            a, b = points[order[i]], points[order[i + 1]]
            for j in range(i + 2, n if i else n - 1):
                c, e = points[order[j]], points[order[(j + 1) % n]]
                delta = dist(a, c) + dist(b, e) - dist(a, b) - dist(c, e)
                if delta < -1e-12:
                    order[i + 1:j + 1] = reversed(order[i + 1:j + 1])
                    improved = True
                    a, b = points[order[i]], points[order[i + 1]]
    return order


def _or_opt(points, order, dist):
    """Move stretches of 1 to 3 points elsewhere in the tour (either way
    round) while that makes it shorter."""
    n = len(order)
    improved = True
    while improved:
        improved = False
        for length in (1, 2, 3):
            for i in range(n):
                if improved:
                    break
                seg = [order[(i + k) % n] for k in range(length)]
                prev, nxt = order[(i - 1) % n], order[(i + length) % n]
                if nxt in seg or prev in seg:
                    continue
                removed = (dist(points[prev], points[seg[0]])
                           + dist(points[seg[-1]], points[nxt])
                           - dist(points[prev], points[nxt]))
                rest = [p for p in order if p not in seg]
                for k in range(len(rest)):
                    u, v = rest[k], rest[(k + 1) % len(rest)]
                    if (u, v) == (prev, nxt):
                        continue
                    for piece in (seg, seg[::-1]):
                        added = (dist(points[u], points[piece[0]])
                                 + dist(points[piece[-1]], points[v])
                                 - dist(points[u], points[v]))
                        if added < removed - 1e-12:
                            order[:] = rest[:k + 1] + piece + rest[k + 1:]
                            improved = True
                            break
                    if improved:
                        break
    return order


def _heuristic_tour(points, dist=_dist, starts=8):
    n = len(points)
    step = max(1, n // starts)
    best = None
    for start in range(0, n, step):
        order = _nearest_neighbour(points, start, dist)
        for _ in range(4):
            before = _tour_length(points, order, dist)
            _two_opt(points, order, dist)
            _or_opt(points, order, dist)
            if _tour_length(points, order, dist) >= before - 1e-12:
                break
        _two_opt(points, order, dist)
        length = _tour_length(points, order, dist)
        if best is None or length < best[0]:
            best = (length, order)
    return best[1]


def _shortest_tour(points, dist=_dist):
    if len(points) <= EXACT_LIMIT:
        return _held_karp(points, dist)
    return _heuristic_tour(points, dist)


def _line_direction(points, tol):
    """Direction of the straight line every point lies on, or None.

    `tol` is a distance: a point farther than that from the line through the
    two most distant points means they are not in line.
    """
    a = points[0]
    far = max(points, key=lambda p: _dist(a, p))
    b = max(points, key=lambda p: _dist(far, p))
    length = _dist(far, b)
    if length < SAME_POINT:
        return None
    u = tuple((y - x) / length for x, y in zip(far, b))
    for p in points:
        v = tuple(y - x for x, y in zip(far, p))
        along = sum(x * y for x, y in zip(v, u))
        off = math.sqrt(max(0.0, sum(x * x for x in v) - along * along))
        if off > tol:
            return None
    return u


def _flat_axes(points, tol):
    """The two axes of the axis-aligned plane (XY, XZ or YZ) all the points
    lie on, or None."""
    for axis in range(3):
        if max(p[axis] for p in points) - min(p[axis] for p in points) <= tol:
            return [i for i in range(3) if i != axis]
    return None


def _segments_cross(p, q, r, s):
    """True when 2D segments p-q and r-s cross or overlap (other than at a
    shared end)."""
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def on_segment(a, b, c):
        return (min(a[0], b[0]) <= c[0] <= max(a[0], b[0])
                and min(a[1], b[1]) <= c[1] <= max(a[1], b[1]))

    o1, o2 = orient(p, q, r), orient(p, q, s)
    o3, o4 = orient(r, s, p), orient(r, s, q)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    # Collinear overlaps (two segments of one straight side going back over
    # each other).
    for a, b, c, o in ((p, q, r, o1), (p, q, s, o2), (r, s, p, o3), (r, s, q, o4)):
        if o == 0 and on_segment(a, b, c) and c not in (a, b):
            return True
    return False


def _self_crossing(points2d, order):
    n = len(order)
    edges = [(points2d[order[i]], points2d[order[(i + 1) % n]]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                continue
            if _segments_cross(*edges[i], *edges[j]):
                return True
    return False


def _pair_along(points, axis_key, axis_sort, tol):
    """Edges of an orthogonal outline along one direction: the points are
    grouped by the coordinate `axis_key` (those on one line parallel to the
    other axis), sorted along `axis_sort`, and paired 1st-2nd, 3rd-4th...
    None when a line holds an odd number of points."""
    groups = []
    for i in sorted(range(len(points)), key=lambda i: points[i][axis_key]):
        if groups and abs(points[i][axis_key] - points[groups[-1][0]][axis_key]) <= tol:
            groups[-1].append(i)
        else:
            groups.append([i])
    edges = []
    for group in groups:
        if len(group) % 2:
            return None
        group.sort(key=lambda i: points[i][axis_sort])
        edges += [(group[k], group[k + 1]) for k in range(0, len(group), 2)]
    return edges


def _orthogonal_tour(points, tol):
    """Outline along the axes through every point, or None.

    For shapes drawn along the axes of a view (a T, an H, an L, a stair...),
    which the shortest path cuts across with slanted segments. When the
    points lie on an axis plane and every one of them is a corner of such an
    outline, the outline is unique: on every line parallel to an axis the
    points pair up 1st-2nd, 3rd-4th..., which gives every point one side along
    each axis. It is used when those sides make a single closed path through
    all the points that does not cross itself.
    """
    flat = _flat_axes(points, tol)
    if flat is None:
        return None
    u, v = flat
    along_v = _pair_along(points, u, v, tol)   # sides parallel to v
    along_u = _pair_along(points, v, u, tol)   # sides parallel to u
    if along_v is None or along_u is None:
        return None
    n = len(points)
    links = [[] for _ in range(n)]
    for a, b in along_v + along_u:
        links[a].append(b)
        links[b].append(a)
    if any(len(link) != 2 for link in links):
        return None
    order, prev = [0], None
    while True:
        cur = order[-1]
        nxt = links[cur][0] if links[cur][0] != prev else links[cur][1]
        if nxt == 0:
            break
        order.append(nxt)
        prev = cur
        if len(order) > n:
            return None
    if len(order) != n:
        return None            # several separate outlines
    if _self_crossing([(p[u], p[v]) for p in points], order):
        return None
    return order


def order_points(points, closed=True):
    """Order in which to join `points` (tuples) and whether the result is
    closed: (list of indices, closed).

    2 points: open. All in line: open, from one end to the other. Points on
    an axis plane that are the corners of an outline along the axes: that
    outline. Otherwise
    the shortest closed path. When `closed` is False, the closed path is
    opened at its longest segment.
    """
    n = len(points)
    if n < 2:
        raise ValueError("at least 2 points")
    if n == 2:
        return [0, 1], False
    size = max(_dist(points[0], p) for p in points)
    tol = max(size, 1.0) * 1e-6
    direction = _line_direction(points, tol)
    if direction is not None:
        key = [sum(x * y for x, y in zip(p, direction)) for p in points]
        return sorted(range(n), key=key.__getitem__), False
    order = _orthogonal_tour(points, tol) or _shortest_tour(points)
    if closed:
        return order, True
    # Open it at its longest segment.
    gaps = [_dist(points[order[i]], points[order[(i + 1) % n]]) for i in range(n)]
    cut = max(range(n), key=gaps.__getitem__)
    return order[cut + 1:] + order[:cut + 1], False


def unique_points(points):
    """Points without the ones that repeat an earlier one (within SAME_POINT):
    (kept points, how many were dropped)."""
    kept = []
    for p in points:
        if all(_dist(p, q) > SAME_POINT for q in kept):
            kept.append(p)
    return kept, len(points) - len(kept)


# -----------------------------------------------------------------------------
# Operator
# -----------------------------------------------------------------------------

def _selected_curve_points(objs):
    points = []
    for obj in objs:
        mw = world_matrix(obj)
        for spline in obj.data.splines:
            if spline.type == 'BEZIER':
                points += [tuple(mw @ bp.co) for bp in spline.bezier_points
                           if bp.select_control_point]
            else:
                points += [tuple(mw @ p.co.xyz) for p in spline.points if p.select]
    return points


def _deselect_all(curve):
    for spline in curve.splines:
        if spline.type == 'BEZIER':
            for bp in spline.bezier_points:
                bp.select_control_point = False
                bp.select_left_handle = False
                bp.select_right_handle = False
        else:
            for p in spline.points:
                p.select = False


class ETR_OT_curve_toolkit_lines_from_points(bpy.types.Operator):
    """Join the selected points with straight lines, without merging them: 2 points make a segment, 3 or more a closed shape with no crossings. A Poly spline in a curve, edges in a mesh. Edit Mode"""
    bl_idname = "etr.curve_toolkit_lines_from_points"
    bl_label = "Lines from Points"
    bl_options = {'REGISTER', 'UNDO'}

    closed: BoolProperty(
        name="Closed",
        description="With 3 points or more, close the shape. Off: an open line "
                    "(the shortest one through all the points). Points that are "
                    "all in line always make an open line",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        if context.mode == EDIT_MESH:
            return True
        if context.mode == EDIT_MODE and is_curve(context.active_object):
            return True
        cls.poll_message_set("Works in the Edit Mode of a curve (control points) or of a "
                             "mesh (vertices)")
        return False

    def execute(self, context):
        try:
            if context.mode == EDIT_MESH:
                count, closed, dropped = self._in_mesh(context)
            else:
                count, closed, dropped = self._in_curve(context)
        except Fail as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}
        shape = "closed shape" if closed else ("segment" if count == 2 else "open line")
        message = f"Lines from Points: {shape} through {count} points"
        if dropped:
            message += f" ({dropped} repeated point(s) skipped)"
        self.report({'INFO'}, message)
        return {'FINISHED'}

    def _order(self, points, what):
        points, dropped = unique_points(points)
        if len(points) < 2:
            raise Fail(f"Lines from Points: select at least 2 {what} "
                       f"({len(points)} distinct selected)")
        order, closed = order_points(points, self.closed)
        return [points[i] for i in order], closed, dropped

    def _in_curve(self, context):
        obj = context.active_object
        try:
            to_local = world_matrix(obj).inverted()
        except ValueError:
            raise Fail(f"'{obj.name}' has a degenerate transform (zero scale)")
        with edit_scope(context) as objs:
            points, closed, dropped = self._order(_selected_curve_points(objs),
                                                  "control points")
            for o in objs:
                _deselect_all(o.data)
            data = sd.SplineData(
                'POLY',
                [sd.PointData(co=tuple(to_local @ Vector(co)), select=True) for co in points],
                closed,
                {},
            )
            obj.data.splines.active = sd.write_spline(obj.data, data)
        return len(points), closed, dropped

    def _in_mesh(self, context):
        obj = context.active_object
        try:
            to_local = world_matrix(obj).inverted()
        except ValueError:
            raise Fail(f"'{obj.name}' has a degenerate transform (zero scale)")
        meshes = [o for o in context.objects_in_mode_unique_data if o.type == 'MESH']
        found = []
        for o in meshes:
            bm = bmesh.from_edit_mesh(o.data)
            mw = world_matrix(o)
            found += [tuple(mw @ v.co) for v in bm.verts if v.select]
        points, closed, dropped = self._order(found, "vertices")

        for o in meshes:
            bm = bmesh.from_edit_mesh(o.data)
            for elems in (bm.verts, bm.edges, bm.faces):
                for e in elems:
                    e.select = False
            bm.select_history.clear()
            if o != obj:
                bmesh.update_edit_mesh(o.data, loop_triangles=False, destructive=False)
        bm = bmesh.from_edit_mesh(obj.data)
        verts = [bm.verts.new(to_local @ Vector(co)) for co in points]
        pairs = list(zip(verts, verts[1:]))
        if closed:
            pairs.append((verts[-1], verts[0]))
        for a, b in pairs:
            bm.edges.new((a, b)).select = True
        for v in verts:
            v.select = True
        bm.select_flush_mode()
        bmesh.update_edit_mesh(obj.data)
        return len(points), closed, dropped


classes = (ETR_OT_curve_toolkit_lines_from_points,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
