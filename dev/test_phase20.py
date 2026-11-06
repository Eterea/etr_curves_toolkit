# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Tests of the Phase 22 changes of Curve Toolkit (v0.22.0): Change Origin To
World Origin / To 3D Cursor, Round without a soft limit on its Radius, Slice
(the old Fix Hole) and Undo Slice, Points at Intersections, Points Along
Curve, Handles to Axis, Tangents from Point, Symmetrize and the new layout of
the panel. With Blender as a Python module:

    python test_phase20.py <folder that contains the etr_curves_toolkit package>

There is no 3D Viewport in background mode, so the tests pass the view
themselves (view='TOP', ...), as the buttons store it on their first run.
"""

import math
import sys
import traceback

sys.path.insert(0, sys.argv[1])

import bpy  # noqa: E402

import etr_curves_toolkit as toolkit  # noqa: E402
from etr_curves_toolkit import spline_data as sd  # noqa: E402

toolkit.register()
ops = bpy.ops.etr
TOL = 1e-5
K = 0.5522847498      # Bezier circle handle factor


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if not hasattr(bpy.types.Scene, "etr_curves_toolkit"):
        toolkit.register()


def close(a, b, tol=TOL):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def make(name, splines, dims='3D', location=(0.0, 0.0, 0.0), select=True):
    """splines: [(kind, points, cyclic, selected indices)]. Poly points are
    (x, y[, z]); Bezier points are (co, left handle, right handle[, type])."""
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = dims
    for kind, pts, cyclic, sel in splines:
        s = cu.splines.new(kind)
        if kind == 'BEZIER':
            s.bezier_points.add(len(pts) - 1)
            for k, (bp, p) in enumerate(zip(s.bezier_points, pts)):
                bp.handle_left_type = bp.handle_right_type = 'FREE'
                bp.co = _xyz(p[0])
                bp.handle_left = _xyz(p[1])
                bp.handle_right = _xyz(p[2])
                if len(p) > 3:
                    bp.handle_left_type = bp.handle_right_type = p[3]
                bp.select_control_point = k in sel
                bp.select_left_handle = bp.select_right_handle = False
        else:
            s.points.add(len(pts) - 1)
            for k, (sp, p) in enumerate(zip(s.points, pts)):
                sp.co = (*_xyz(p), 1.0)
                sp.select = k in sel
        s.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, cu)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    if select:
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
    return obj


def _xyz(p):
    return (p[0], p[1], p[2] if len(p) > 2 else 0.0)


def bezier_circle(r, center=(0.0, 0.0), cw=False):
    pts = []
    for i in range(4):
        a = math.pi / 2 + (-1 if cw else 1) * i * math.pi / 2
        c = (center[0] + r * math.cos(a), center[1] + r * math.sin(a))
        t = (-math.sin(a), math.cos(a)) if not cw else (math.sin(a), -math.cos(a))
        pts.append((c, (c[0] - K * r * t[0], c[1] - K * r * t[1]),
                    (c[0] + K * r * t[0], c[1] + K * r * t[1])))
    return pts


def edit(obj):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')


def run(op, **kw):
    try:
        return op(**kw)
    except RuntimeError:
        return {'CANCELLED'}


def strays(obj):
    """World positions of the stray points of a curve object."""
    mw = obj.matrix_world
    return [tuple(mw @ s.points[0].co.xyz) for s in obj.data.splines
            if s.type == 'POLY' and len(s.points) == 1]


def has(points, target, tol=1e-4):
    return any(close(p, target, tol) for p in points)


def flat(data, steps=24):
    return sd.flatten(data, steps)


def to_polyline(p, poly):
    """Distance from a point to a polyline."""
    best = float("inf")
    for a, b in zip(poly, poly[1:]):
        ab = [b[i] - a[i] for i in range(3)]
        ap = [p[i] - a[i] for i in range(3)]
        den = sum(c * c for c in ab) or 1e-300
        t = max(0.0, min(1.0, sum(x * y for x, y in zip(ab, ap)) / den))
        best = min(best, math.dist(p, [a[i] + ab[i] * t for i in range(3)]))
    return best


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# -----------------------------------------------------------------------------
# Change Origin: To World Origin / To 3D Cursor
# -----------------------------------------------------------------------------

@test
def origin_to_world_object_mode():
    reset()
    obj = make("C", [('POLY', [(0, 0), (1, 0), (1, 1)], False, ())], location=(2, 3, 4))
    assert ops.curve_toolkit_origin_to_target(target='WORLD') == {'FINISHED'}
    bpy.context.view_layer.update()
    assert close(obj.location, (0, 0, 0))
    pts = [tuple(obj.matrix_world @ p.co.xyz) for p in obj.data.splines[0].points]
    assert close(pts[0], (2, 3, 4)) and close(pts[2], (3, 4, 4)), pts


@test
def origin_to_cursor_edit_mode_keeps_edit_mode():
    reset()
    obj = make("C", [('POLY', [(0, 0), (1, 0)], False, (0,))], location=(1, 0, 0))
    bpy.context.scene.cursor.location = (5, 5, 0)
    edit(obj)
    assert ops.curve_toolkit_origin_to_target(target='CURSOR') == {'FINISHED'}
    assert bpy.context.mode == 'EDIT_CURVE'
    bpy.ops.object.mode_set(mode='OBJECT')
    assert close(obj.location, (5, 5, 0))
    pts = [tuple(obj.matrix_world @ p.co.xyz) for p in obj.data.splines[0].points]
    assert close(pts[0], (1, 0, 0)) and close(pts[1], (2, 0, 0)), pts
    # The selection is kept.
    assert obj.data.splines[0].points[0].select


@test
def round_radius_has_no_soft_limit():
    from etr_curves_toolkit import round_bridge
    assert round_bridge   # the module of Round Corners
    prop = ops.curve_toolkit_round_corners.get_rna_type().properties["radius"]
    assert prop.soft_max > 1e30, prop.soft_max
    reset()
    obj = make("Sq", [('POLY', [(0, 0), (100, 0), (100, 100), (0, 100)], True, (1,))])
    edit(obj)
    assert ops.curve_toolkit_round_corners(radius=20.0) == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    d = sd.read_all(obj.data)[0]
    assert len(d.points) == 5


# -----------------------------------------------------------------------------
# Slice and Undo Slice
# -----------------------------------------------------------------------------

def _ring(sel_outer=(0,), sel_hole=(0,), kind='BEZIER'):
    if kind == 'BEZIER':
        return make("Ring", [('BEZIER', bezier_circle(2.0), True, sel_outer),
                             ('BEZIER', bezier_circle(0.5, cw=True), True, sel_hole)], '2D')
    outer = [(-2, -2), (2, -2), (2, 2), (-2, 2)]
    hole = [(-0.5, 0.5), (0.5, 0.5), (0.5, -0.5), (-0.5, -0.5)]
    return make("Ring", [('POLY', outer, True, sel_outer), ('POLY', hole, True, sel_hole)], '2D')


def _select_points(obj, coords):
    """Select exactly the control points at the given places (Object Mode)."""
    for s in obj.data.splines:
        pts = s.bezier_points if s.type == 'BEZIER' else s.points
        for p in pts:
            co = tuple(p.co)[:3]
            on = any(close(co, (*c, 0.0)) for c in coords)
            if s.type == 'BEZIER':
                p.select_control_point = on
                p.select_left_handle = p.select_right_handle = False
            else:
                p.select = on


def _shape(obj):
    return sorted((round(x, 4), round(y, 4)) for d in sd.read_all(obj.data)
                  for x, y, _ in flat(d))


@test
def slice_operator_renamed():
    assert hasattr(bpy.types, "ETR_OT_curve_toolkit_slice")
    assert not hasattr(bpy.types, "ETR_OT_curve_toolkit_fix_hole")
    assert bpy.types.ETR_OT_curve_toolkit_slice.bl_label == "Slice"


@test
def undo_slice_restores_a_hole():
    for kind in ('BEZIER', 'POLY'):
        reset()
        obj = _ring(kind=kind)
        before = [d.copy() for d in sd.read_all(obj.data)]
        edit(obj)
        assert ops.curve_toolkit_slice() == {'FINISHED'}
        bpy.ops.object.mode_set(mode='OBJECT')
        assert len(obj.data.splines) == 1
        a = before[0].points[0].co[:2]
        b = before[1].points[0].co[:2]
        _select_points(obj, [a, b])
        edit(obj)
        assert ops.curve_toolkit_undo_slice() == {'FINISHED'}, kind
        bpy.ops.object.mode_set(mode='OBJECT')
        after = sd.read_all(obj.data)
        assert len(after) == 2, kind
        assert all(d.cyclic and d.kind == kind for d in after)
        assert sorted(len(d.points) for d in after) == [4, 4]
        # Same shape as before the Slice.
        for d_before in before:
            match = [d for d in after if len(d.points) == len(d_before.points)
                     and all(has([q.co for q in d.points], p.co) for p in d_before.points)]
            assert match, kind
            got = sorted((round(x, 4), round(y, 4)) for x, y, _ in flat(match[0]))
            want = sorted((round(x, 4), round(y, 4)) for x, y, _ in flat(d_before))
            assert got == want, kind
        # Only the two merged points are selected.
        assert sum(p.select for d in after for p in d.points) == 2


@test
def undo_slice_with_one_point_of_each_pair():
    reset()
    obj = _ring(kind='POLY')
    edit(obj)
    assert ops.curve_toolkit_slice() == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    s = obj.data.splines[0]
    for p in s.points:
        p.select = False
    # One point at A and one at B (clicking selects only one of two
    # coincident points).
    s.points[0].select = True
    k = next(i for i, p in enumerate(s.points) if close(tuple(p.co)[:2], (-0.5, 0.5)))
    s.points[k].select = True
    edit(obj)
    assert ops.curve_toolkit_undo_slice() == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    assert len(obj.data.splines) == 2


@test
def undo_slice_rejoins_a_cut():
    reset()
    sq = [(0, 0), (4, 0), (4, 4), (0, 4)]
    obj = make("Sq", [('POLY', sq, True, (0, 2))], '2D')
    shape = _shape(obj)
    edit(obj)
    assert ops.curve_toolkit_slice() == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    assert len(obj.data.splines) == 2
    _select_points(obj, [(0, 0), (4, 4)])
    edit(obj)
    assert ops.curve_toolkit_undo_slice() == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    after = sd.read_all(obj.data)
    assert len(after) == 1 and len(after[0].points) == 4 and after[0].cyclic
    assert _shape(obj) == shape


@test
def undo_slice_one_seam_of_four():
    """Four seams on a ring (12, 3, 6 and 9 o'clock); two are taken away."""
    reset()
    obj = _ring(kind='BEZIER')
    edit(obj)
    assert ops.curve_toolkit_slice() == {'FINISHED'}            # 12 o'clock
    bpy.ops.object.mode_set(mode='OBJECT')
    for (a, b) in (((2, 0), (0.5, 0)), ((0, -2), (0, -0.5)), ((-2, 0), (-0.5, 0))):
        _select_points(obj, [a, b])
        # Only one point of each place: the first one found.
        for s in obj.data.splines:
            for p in s.bezier_points:
                p.select_control_point = False
        done = set()
        for s in obj.data.splines:
            for p in s.bezier_points:
                for c in (a, b):
                    if c not in done and close(tuple(p.co)[:2], c):
                        p.select_control_point = True
                        done.add(c)
        edit(obj)
        assert ops.curve_toolkit_slice() == {'FINISHED'}
        bpy.ops.object.mode_set(mode='OBJECT')
    assert len(obj.data.splines) == 4
    _select_points(obj, [(2, 0), (0.5, 0)])
    edit(obj)
    assert ops.curve_toolkit_undo_slice() == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    assert len(obj.data.splines) == 3
    _select_points(obj, [(-2, 0), (-0.5, 0)])
    edit(obj)
    assert ops.curve_toolkit_undo_slice() == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    assert len(obj.data.splines) == 2
    assert all(d.cyclic for d in sd.read_all(obj.data))


@test
def undo_slice_errors():
    reset()
    obj = _ring(kind='POLY', sel_outer=(0, 1), sel_hole=())
    edit(obj)
    assert run(ops.curve_toolkit_undo_slice) == {'CANCELLED'}     # no coincident points
    bpy.ops.object.mode_set(mode='OBJECT')
    reset()
    # Two pairs of coincident points that are not a seam.
    obj = make("Two", [('POLY', [(0, 0), (1, 0)], False, (0, 1)),
                       ('POLY', [(0, 0), (1, 0)], False, (0, 1))])
    edit(obj)
    assert run(ops.curve_toolkit_undo_slice) == {'CANCELLED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    assert len(obj.data.splines) == 2


# -----------------------------------------------------------------------------
# Points at Intersections
# -----------------------------------------------------------------------------

@test
def intersections_object_mode_new_object():
    reset()
    a = make("A", [('POLY', [(-1, 0), (1, 0)], False, ())])
    b = make("B", [('POLY', [(0.25, -1), (0.25, 1)], False, ())])
    c = make("C", [('POLY', [(-1, -1), (1, 1)], False, ())])
    assert ops.curve_toolkit_points_at_intersections() == {'FINISHED'}
    new = bpy.context.active_object
    assert new not in (a, b, c) and new.select_get() and not a.select_get()
    pts = strays(new)
    assert len(pts) == 3, pts
    assert has(pts, (0, 0, 0)) and has(pts, (0.25, 0, 0)) and has(pts, (0.25, 0.25, 0))
    # The curves are untouched.
    assert len(a.data.splines[0].points) == 2


@test
def intersections_bezier_circle_and_line_are_on_both_curves():
    reset()
    circ = make("Circle", [('BEZIER', bezier_circle(1.0), True, ())])
    make("Line", [('POLY', [(-2, 0.3), (2, 0.3)], False, ())])
    circ.select_set(True)
    assert ops.curve_toolkit_points_at_intersections() == {'FINISHED'}
    pts = strays(bpy.context.active_object)
    assert len(pts) == 2
    d = sd.read_all(circ.data)[0]
    poly = flat(d, 400)
    for p in pts:
        assert abs(p[1] - 0.3) < 1e-6
        assert to_polyline(p, poly) < 1e-5


@test
def intersections_self_crossing_and_same_object():
    reset()
    # A figure eight (crosses itself once) and, in the same object, a line.
    make("F", [('POLY', [(0, 0), (1, 1), (1, 0), (0, 1)], True, ()),
               ('POLY', [(-1, 0.25), (2, 0.25)], False, ())])
    assert ops.curve_toolkit_points_at_intersections() == {'FINISHED'}
    pts = strays(bpy.context.active_object)
    assert has(pts, (0.5, 0.5, 0))
    assert has(pts, (0.25, 0.25, 0)) and has(pts, (0.75, 0.25, 0))
    assert has(pts, (0, 0.25, 0)) and has(pts, (1, 0.25, 0))
    assert len(pts) == 5, pts


@test
def intersections_apparent_in_ortho_views():
    for view, b_pts, want in (
        ('TOP', [(0.5, -1, 2), (0.5, 1, 2)], (0.5, 0, 0)),
        ('FRONT', [(0.5, 3, -1), (0.5, 3, 1)], (0.5, 0, 0)),
        ('RIGHT', [(4, 0.5, -1), (4, 0.5, 1)], (0, 0.5, 0)),
    ):
        reset()
        if view == 'RIGHT':
            make("A", [('POLY', [(0, -1, 0), (0, 1, 0)], False, ())])
        else:
            make("A", [('POLY', [(-1, 0, 0), (1, 0, 0)], False, ())])
        b = make("B", [('POLY', b_pts, False, ())])
        b.select_set(True)
        assert ops.curve_toolkit_points_at_intersections(view=view) == {'FINISHED'}, view
        pts = strays(bpy.context.active_object)
        assert len(pts) == 1 and close(pts[0], want), (view, pts)


@test
def intersections_apparent_in_perspective_are_refused():
    reset()
    make("A", [('POLY', [(-1, 0), (1, 0)], False, ())])
    make("B", [('POLY', [(0.5, -1, 2), (0.5, 1, 2)], False, ())])
    bpy.data.objects["A"].select_set(True)
    assert run(ops.curve_toolkit_points_at_intersections, view='NONE') == {'CANCELLED'}
    assert len(bpy.data.objects) == 2


@test
def intersections_real_ones_at_their_height():
    """Curves that really touch at Z = 3 keep their point there, even in Top."""
    reset()
    make("A", [('POLY', [(-1, 0, 3), (1, 0, 3)], False, ())])
    make("B", [('POLY', [(0, -1, 3), (0, 1, 3)], False, ())])
    bpy.data.objects["A"].select_set(True)
    for view in ('TOP', 'NONE'):
        assert ops.curve_toolkit_points_at_intersections(view=view) == {'FINISHED'}
        pts = strays(bpy.context.active_object)
        assert len(pts) == 1 and close(pts[0], (0, 0, 3)), pts
        bpy.ops.object.mode_set(mode='OBJECT')      # v0.23: it ends in Edit Mode
        for o in bpy.data.objects:
            o.select_set(o.name in ("A", "B"))


@test
def intersections_real_ones_in_a_tilted_plane():
    """Perspective: two lines in a tilted plane, seen from above."""
    reset()
    make("A", [('POLY', [(-1, 0, -1), (1, 0, 1)], False, ())])
    make("B", [('POLY', [(0, -1, 0), (0, 1, 0)], False, ())])
    bpy.data.objects["A"].select_set(True)
    assert ops.curve_toolkit_points_at_intersections(view='NONE') == {'FINISHED'}
    pts = strays(bpy.context.active_object)
    assert len(pts) == 1 and close(pts[0], (0, 0, 0)), pts


@test
def intersections_edit_mode():
    reset()
    obj = make("E", [('POLY', [(-1, 0), (1, 0)], False, (0,)),
                     ('POLY', [(0, -1), (0, 1)], False, (1,)),
                     ('POLY', [(0.5, -1), (0.5, 1)], False, ())], location=(1, 1, 0))
    edit(obj)
    assert ops.curve_toolkit_points_at_intersections() == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    datas = sd.read_all(obj.data)
    assert len(datas) == 4
    new = datas[3]
    assert len(new.points) == 1 and close(new.points[0].co, (0, 0, 0)) and new.points[0].select
    assert sum(p.select for d in datas for p in d.points) == 1


@test
def intersections_nurbs_are_close():
    reset()
    bpy.ops.curve.primitive_nurbs_circle_add(radius=1.0)
    make("L", [('POLY', [(-2, 0.2), (2, 0.2)], False, ())])
    bpy.data.objects["NurbsCircle"].select_set(True)
    assert ops.curve_toolkit_points_at_intersections() == {'FINISHED'}
    pts = strays(bpy.context.active_object)
    assert len(pts) == 2
    for p in pts:
        assert abs(p[1] - 0.2) < 1e-6


@test
def intersections_none():
    reset()
    make("A", [('POLY', [(-1, 0), (1, 0)], False, ())])
    make("B", [('POLY', [(-1, 1), (1, 1)], False, ())])
    bpy.data.objects["A"].select_set(True)
    assert run(ops.curve_toolkit_points_at_intersections, view='TOP') == {'CANCELLED'}


# -----------------------------------------------------------------------------
# Points Along Curve
# -----------------------------------------------------------------------------

@test
def along_open_poly_with_extremes():
    reset()
    make("P", [('POLY', [(0, 0), (2, 0), (2, 1)], False, ())])
    assert ops.curve_toolkit_points_along_curve(count=2) == {'FINISHED'}
    pts = strays(bpy.context.active_object)
    assert len(pts) == 2 and has(pts, (1, 0, 0)) and has(pts, (2, 0, 0))
    reset()
    make("P", [('POLY', [(0, 0), (3, 0)], False, ())])
    assert ops.curve_toolkit_points_along_curve(count=1, extremes=True) == {'FINISHED'}
    pts = strays(bpy.context.active_object)
    assert len(pts) == 3 and has(pts, (0, 0, 0)) and has(pts, (1.5, 0, 0)) and has(pts, (3, 0, 0))


@test
def along_default_count_is_four():
    reset()
    make("P", [('POLY', [(0, 0), (5, 0)], False, ())])
    assert ops.curve_toolkit_points_along_curve() == {'FINISHED'}
    pts = sorted(strays(bpy.context.active_object))
    assert [round(p[0], 6) for p in pts] == [1, 2, 3, 4]


@test
def along_closed_bezier_circle_equal_lengths():
    reset()
    make("C", [('BEZIER', bezier_circle(1.0), True, ())])
    assert ops.curve_toolkit_points_along_curve(count=3, extremes=True) == {'FINISHED'}
    pts = strays(bpy.context.active_object)
    assert len(pts) == 4                    # one at the first point, not two
    angles = sorted(round(math.degrees(math.atan2(p[1], p[0]) + 1e-9) % 360, 2) for p in pts)
    assert angles == [0.0, 90.0, 180.0, 270.0], angles


@test
def along_bezier_points_are_on_the_curve():
    reset()
    obj = make("S", [('BEZIER', [((0, 0), (-1, 0), (1, 2)), ((3, 0), (2, -2), (4, 0))],
                      False, ())])
    assert ops.curve_toolkit_points_along_curve(count=5) == {'FINISHED'}
    pts = strays(bpy.context.active_object)
    poly = flat(sd.read_all(obj.data)[0], 2000)
    for p in pts:
        assert min(math.dist(p, q) for q in poly) < 2e-3
    # Equal lengths: the arc between neighbours is the same.
    from etr_curves_toolkit import geometry as geo
    total, cum = geo.sample_polyline(poly)

    def at(p):
        i = min(range(len(poly)), key=lambda k: math.dist(p, poly[k]))
        return cum[i]

    arcs = sorted(at(p) for p in pts)
    steps = [b - a for a, b in zip([0] + arcs, arcs + [total])]
    assert max(steps) - min(steps) < 5e-3 * total, steps


@test
def along_edit_mode_only_picked_splines():
    reset()
    obj = make("E", [('POLY', [(0, 0), (2, 0)], False, (1,)),
                     ('POLY', [(0, 1), (2, 1)], False, ())])
    edit(obj)
    assert ops.curve_toolkit_points_along_curve(count=1) == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    datas = sd.read_all(obj.data)
    assert len(datas) == 3 and close(datas[2].points[0].co, (1, 0, 0))
    assert sum(p.select for d in datas for p in d.points) == 1


# -----------------------------------------------------------------------------
# Handles to Axis
# -----------------------------------------------------------------------------

def _tilted(deg, types='ALIGNED', length=1.0):
    t = math.tan(math.radians(deg))
    return [((0, 0), (-length, -length * t), (length, length * t), types),
            ((3, 0), (2, 1), (4, -1), 'FREE')]


@test
def handles_to_axis_object_mode():
    reset()
    obj = make("H", [('BEZIER', _tilted(3), False, ())])
    assert ops.curve_toolkit_handles_to_axis() == {'FINISHED'}
    bp = obj.data.splines[0].bezier_points[0]
    L = math.hypot(1, math.tan(math.radians(3)))
    assert close(bp.handle_right, (L, 0, 0)) and close(bp.handle_left, (-L, 0, 0))
    assert bp.handle_left_type == bp.handle_right_type == 'ALIGNED'
    assert close(bp.co, (0, 0, 0))
    # 45 degrees: out of the default Threshold.
    other = obj.data.splines[0].bezier_points[1]
    assert close(other.handle_left, (2, 1, 0))


@test
def handles_to_axis_threshold():
    reset()
    obj = make("H", [('BEZIER', _tilted(8), False, ())])
    ops.curve_toolkit_handles_to_axis()
    assert not close(obj.data.splines[0].bezier_points[0].handle_right[1:], (0, 0))
    reset()
    obj = make("H", [('BEZIER', _tilted(8), False, ())])
    ops.curve_toolkit_handles_to_axis(threshold=math.radians(10))
    assert close(obj.data.splines[0].bezier_points[0].handle_right[1:], (0, 0))


@test
def handles_to_axis_uses_local_axes():
    reset()
    obj = make("H", [('BEZIER', _tilted(3), False, ())])
    obj.rotation_euler = (0, 0, math.radians(30))
    ops.curve_toolkit_handles_to_axis()
    bp = obj.data.splines[0].bezier_points[0]
    assert abs(bp.handle_right[1]) < 1e-6 and bp.handle_right[0] > 0


@test
def handles_to_axis_one_handle_in_edit_mode():
    reset()
    obj = make("H", [('BEZIER', _tilted(3), False, ())])
    bp = obj.data.splines[0].bezier_points[0]
    bp.select_control_point = bp.select_left_handle = False
    bp.select_right_handle = True
    old_left = tuple(bp.handle_left)
    edit(obj)
    assert ops.curve_toolkit_handles_to_axis() == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    bp = obj.data.splines[0].bezier_points[0]
    assert abs(bp.handle_right[1]) < 1e-6
    assert close(bp.handle_left, old_left)
    assert bp.handle_left_type == bp.handle_right_type == 'FREE'


@test
def handles_to_axis_vector_and_unselected_untouched():
    reset()
    obj = make("H", [('BEZIER', _tilted(3, 'VECTOR'), False, ()),
                     ('BEZIER', _tilted(3), False, ())])
    obj.data.splines[1].bezier_points[0].select_control_point = True
    edit(obj)
    ops.curve_toolkit_handles_to_axis()
    bpy.ops.object.mode_set(mode='OBJECT')
    s0, s1 = obj.data.splines
    assert s0.bezier_points[0].handle_right_type == 'VECTOR'
    assert abs(s1.bezier_points[0].handle_right[1]) < 1e-6


# -----------------------------------------------------------------------------
# Tangents from Point
# -----------------------------------------------------------------------------

def _circle_and_point(point, sel_circle=(0,)):
    return make("CP", [('BEZIER', bezier_circle(1.0), True, sel_circle),
                       ('POLY', [point], False, (0,))])


@test
def tangents_from_point_draws_two_poly_lines():
    reset()
    obj = _circle_and_point((3, 0))
    edit(obj)
    assert ops.curve_toolkit_tangents_from_point() == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    datas = sd.read_all(obj.data)
    assert len(datas) == 4
    lines = datas[2:]
    for d in lines:
        assert d.kind == 'POLY' and len(d.points) == 2 and not d.cyclic
        p, t = d.points[0].co, d.points[1].co
        assert close(p, (3, 0, 0))
        # Tangent: the radius to the contact point is perpendicular to the line.
        assert abs((t[0] - p[0]) * t[0] + (t[1] - p[1]) * t[1]) < 1e-3
        assert abs(math.hypot(t[0], t[1]) - 1.0) < 1e-3
    assert {round(d.points[1].co[1], 3) for d in lines} == {0.943, -0.943}
    assert sum(p.select for d in datas for p in d.points) == 4


@test
def tangents_from_point_out_of_plane():
    reset()
    obj = _circle_and_point((2, 0, 1.5))
    edit(obj)
    assert ops.curve_toolkit_tangents_from_point() == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    for d in sd.read_all(obj.data)[2:]:
        p, t = d.points[0].co, d.points[1].co
        assert abs((t[0] - p[0]) * t[0] + (t[1] - p[1]) * t[1] + (t[2] - p[2]) * t[2]) < 1e-3


@test
def tangents_from_point_errors():
    reset()
    obj = _circle_and_point((0.2, 0.1))
    edit(obj)
    assert run(ops.curve_toolkit_tangents_from_point) == {'CANCELLED'}     # inside
    bpy.ops.object.mode_set(mode='OBJECT')
    reset()
    obj = make("Two", [('POLY', [(0, 0), (1, 0)], False, (0,)),
                       ('POLY', [(3, 0)], False, (0,))])
    edit(obj)
    assert run(ops.curve_toolkit_tangents_from_point) == {'CANCELLED'}     # no circle


# -----------------------------------------------------------------------------
# Symmetrize
# -----------------------------------------------------------------------------

def _result():
    obj = bpy.context.active_object
    mw = obj.matrix_world
    out = []
    for d in sd.read_all(obj.data):
        out.append((d, [tuple(round(c, 4) for c in (mw @ __import__("mathutils").Vector(p.co)))
                        for p in d.points]))
    return obj, out


@test
def symmetrize_closed_square_left_to_right():
    reset()
    src = make("Sq", [('POLY', [(-2, -1), (1, -1), (1, 1), (-2, 1)], True, ())], '2D')
    assert ops.curve_toolkit_symmetrize(view='TOP') == {'FINISHED'}
    obj, res = _result()
    assert obj is not src and src.hide_get()
    assert len(res) == 1
    d, pts = res[0]
    assert d.cyclic and d.kind == 'POLY'
    xs = sorted(p[0] for p in pts)
    assert xs[0] == -2 and xs[-1] == 2
    assert has(pts, (0, 1, 0)) and has(pts, (0, -1, 0))


@test
def symmetrize_directions():
    shape = [(-2, -1), (1, -1), (1, 3), (-2, 3)]
    for direction, check in (
        ('LEFT_TO_RIGHT', lambda xs, ys: (min(xs), max(xs)) == (-2, 2)),
        ('RIGHT_TO_LEFT', lambda xs, ys: (min(xs), max(xs)) == (-1, 1)),
        ('TOP_TO_BOTTOM', lambda xs, ys: (min(ys), max(ys)) == (-3, 3)),
        ('BOTTOM_TO_TOP', lambda xs, ys: (min(ys), max(ys)) == (-1, 1)),
    ):
        reset()
        make("S", [('POLY', shape, True, ())], '2D')
        assert ops.curve_toolkit_symmetrize(view='TOP', direction=direction) == {'FINISHED'}
        _, res = _result()
        xs = [p[0] for _, pts in res for p in pts]
        ys = [p[1] for _, pts in res for p in pts]
        assert check(xs, ys), (direction, xs, ys)


@test
def symmetrize_back_view_is_mirrored():
    """The left of Back is +X: Left to Right keeps the +X side."""
    reset()
    make("B", [('POLY', [(-2, 0, -1), (1, 0, -1), (1, 0, 1), (-2, 0, 1)], True, ())])
    assert ops.curve_toolkit_symmetrize(view='BACK') == {'FINISHED'}
    _, res = _result()
    xs = [p[0] for _, pts in res for p in pts]
    assert (min(xs), max(xs)) == (-1, 1)


@test
def symmetrize_centers():
    # At x = 5 the curve is all on the right of the world origin: nothing to
    # keep with the World Origin as the center.
    for center, want in (('WORLD', None), ('OBJECT', (3, 7)), ('CURSOR', (3, 9))):
        reset()
        bpy.context.scene.cursor.location = (6, 0, 0)
        make("S", [('POLY', [(-2, -1), (1, -1), (1, 1), (-2, 1)], True, ())], '2D',
             location=(5, 0, 0))
        if want is None:
            # v0.24.0: nothing made, but FINISHED (so the F9 panel opens).
            assert run(ops.curve_toolkit_symmetrize, view='TOP', center=center) == {'FINISHED'}
            assert len(bpy.data.objects) == 1
            continue
        assert ops.curve_toolkit_symmetrize(view='TOP', center=center) == {'FINISHED'}
        _, res = _result()
        xs = [p[0] for _, pts in res for p in pts]
        assert (min(xs), max(xs)) == want, (center, xs)


@test
def symmetrize_open_half_heart_becomes_closed():
    reset()
    make("H", [('POLY', [(0, 1), (-1, 2), (-2, 1), (0, -2)], False, ())])
    assert ops.curve_toolkit_symmetrize(view='TOP') == {'FINISHED'}
    _, res = _result()
    assert len(res) == 1
    d, pts = res[0]
    assert d.cyclic and len(pts) == 6
    assert has(pts, (2, 1, 0)) and has(pts, (1, 2, 0))


@test
def symmetrize_open_one_end_on_axis_and_crossing():
    reset()
    make("O", [('POLY', [(0, 0), (-1, 1), (-2, 0)], False, ())])
    assert ops.curve_toolkit_symmetrize(view='TOP') == {'FINISHED'}
    _, res = _result()
    assert len(res) == 1 and not res[0][0].cyclic and len(res[0][1]) == 5
    reset()
    make("X", [('POLY', [(-2, 0), (2, 1)], False, ())])
    assert ops.curve_toolkit_symmetrize(view='TOP') == {'FINISHED'}
    _, res = _result()
    assert len(res) == 1 and res[0][1] == [(-2, 0, 0), (0, 0.5, 0), (2, 0, 0)]


@test
def symmetrize_no_overlap_keeps_both_copies():
    reset()
    make("L", [('POLY', [(-3, 0), (-2, 0), (-2, 1)], True, ())])
    assert ops.curve_toolkit_symmetrize(view='TOP') == {'FINISHED'}
    _, res = _result()
    assert len(res) == 2


@test
def symmetrize_nothing_on_the_kept_side():
    reset()
    src = make("R", [('POLY', [(3, 0), (2, 0), (2, 1)], True, ())])
    assert run(ops.curve_toolkit_symmetrize, view='TOP') == {'FINISHED'}   # v0.24.0
    assert not src.hide_get() and len(bpy.data.objects) == 1


@test
def symmetrize_needs_an_axis_view_and_flat_curves():
    reset()
    make("S", [('POLY', [(-2, -1), (1, -1), (1, 1)], True, ())])
    assert run(ops.curve_toolkit_symmetrize, view='NONE') == {'FINISHED'}  # v0.24.0
    assert len(bpy.data.objects) == 1
    reset()
    make("S", [('POLY', [(-2, -1, 0), (1, -1, 1), (1, 1, 0)], True, ())])
    assert run(ops.curve_toolkit_symmetrize, view='TOP') == {'CANCELLED'}


@test
def symmetrize_bezier_circle_welds_with_free_handles():
    reset()
    make("C", [('BEZIER', bezier_circle(1.0, center=(-0.5, 0)), True, ())], '2D')
    assert ops.curve_toolkit_symmetrize(view='TOP') == {'FINISHED'}
    obj, res = _result()
    d, pts = res[0]
    assert d.kind == 'BEZIER' and d.cyclic
    on_axis = [p for p, w in zip(d.points, pts) if abs(w[0]) < 1e-6]
    assert len(on_axis) == 2
    assert all(p.hlt == 'FREE' and p.hrt == 'FREE' for p in on_axis)
    # Symmetric outline.
    poly = [(round(x, 3), round(y, 3)) for x, y, _ in flat(d, 32)]
    for x, y in poly:
        assert min(math.hypot(-x - u, y - v) for u, v in poly) < 2e-2


@test
def symmetrize_ring_keeps_its_hole():
    reset()
    make("Ring", [('BEZIER', bezier_circle(2.0, center=(-0.5, 0)), True, ()),
                  ('BEZIER', bezier_circle(0.5, center=(-1.0, 0), cw=True), True, ())], '2D')
    assert ops.curve_toolkit_symmetrize(view='TOP') == {'FINISHED'}
    _, res = _result()
    assert len(res) == 3, len(res)     # the outline and two holes


@test
def symmetrize_sources_and_results_collections():
    reset()
    st = bpy.context.scene.etr_curves_toolkit
    st.sources_in_collection = st.results_in_collection = True
    src = make("S", [('POLY', [(-2, -1), (1, -1), (1, 1), (-2, 1)], True, ())], '2D')
    assert ops.curve_toolkit_symmetrize(view='TOP') == {'FINISHED'}
    assert src.users_collection[0].name == "Curve Boolean Sources"
    assert bpy.context.active_object.users_collection[0].name == "Curve Boolean Results"


@test
def symmetrize_two_objects_object_origins():
    reset()
    make("A", [('POLY', [(-2, -1), (1, -1), (1, 1), (-2, 1)], True, ())], '2D')
    make("B", [('POLY', [(-1, -1), (2, -1), (2, 1), (-1, 1)], True, ())], '2D',
         location=(10, 0, 0))
    bpy.data.objects["A"].select_set(True)
    assert ops.curve_toolkit_symmetrize(view='TOP', center='OBJECT') == {'FINISHED'}
    results = [o for o in bpy.context.selected_objects]
    assert len(results) == 2


# -----------------------------------------------------------------------------
# Panel
# -----------------------------------------------------------------------------

def _drawn(panel_cls, mode='OBJECT'):
    from unittest import mock
    fake = mock.MagicMock()
    ctx = mock.MagicMock()
    ctx.scene = bpy.context.scene
    ctx.mode = mode
    panel_cls.draw(fake, ctx)
    return fake, [c[1][0] for c in fake.mock_calls if c[0].endswith("operator") and c[1]]


@test
def panel_layout():
    from etr_curves_toolkit import panel
    reset()
    _, drawn = _drawn(panel.ETR_PT_curve_toolkit_primitives)
    assert drawn[10:] == [
        "etr.curve_toolkit_circle_segment_center", "etr.curve_toolkit_tangents_2_circles",
        "etr.curve_toolkit_tangents_from_point", "etr.curve_toolkit_perpendicular",
        "etr.curve_toolkit_lines_from_points", "etr.curve_toolkit_points_in_between",
        "etr.curve_toolkit_points_along_curve",
        "etr.curve_toolkit_points_at_intersections"], drawn
    _, drawn = _drawn(panel.ETR_PT_curve_toolkit_booleans)
    assert drawn[3] == "etr.curve_toolkit_symmetrize", drawn
    _, drawn = _drawn(panel.ETR_PT_curve_toolkit_rounds)
    assert drawn == [
        "etr.curve_toolkit_round_corners", "etr.curve_toolkit_bridge_curves",
        "etr.curve_toolkit_arcs_to_corners", "etr.curve_toolkit_offset",
        "etr.curve_toolkit_extend", "etr.curve_toolkit_slide_point",
        "etr.curve_toolkit_slice", "etr.curve_toolkit_undo_slice",
        "etr.curve_toolkit_handles_to_axis", "etr.curve_toolkit_handles_to_lines"], drawn
    _, drawn = _drawn(panel.ETR_PT_curve_toolkit_origin)
    assert drawn[:3] == ["etr.curve_toolkit_origin_to_target",
                         "etr.curve_toolkit_origin_to_target",
                         "etr.curve_toolkit_origin_to_selected"], drawn
    for icon in ("slice", "points_at_intersections", "points_along_curve", "handles_to_axis",
                 "tangents_from_point", "symmetrize"):
        assert icon in panel._icons and tuple(panel._icons[icon].icon_size) == (32, 32), icon


@test
def undo_slice_has_no_icon():
    from etr_curves_toolkit import panel
    reset()
    fake, _ = _drawn(panel.ETR_PT_curve_toolkit_rounds)
    call = next(c for c in fake.mock_calls if c[0].endswith("operator") and c[1]
                and c[1][0] == "etr.curve_toolkit_undo_slice")
    assert call[2] == {"text": "Undo Slice"}, call


@test
def register_unregister_cycle():
    toolkit.unregister()
    assert not hasattr(bpy.types, "ETR_OT_curve_toolkit_symmetrize")
    toolkit.register()
    for name in ("slice", "undo_slice", "points_at_intersections", "points_along_curve",
                 "handles_to_axis", "tangents_from_point", "symmetrize", "origin_to_target"):
        assert hasattr(bpy.types, f"ETR_OT_curve_toolkit_{name}"), name


def main():
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"  ok   {fn.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)


main()
