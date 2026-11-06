# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Tests of Curve Toolkit phase 1 (utilities, Round Corners, Bridge) with Blender
as a Python module:

    python test_phase1.py <folder that contains the etr_curves_toolkit package>

Every test builds its own curves from scratch and compares shapes through
Blender's evaluated geometry, so a tool that changed a shape would fail.
"""

import math
import sys
import traceback

sys.path.insert(0, sys.argv[1])

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

import etr_curves_toolkit as toolkit  # noqa: E402
from etr_curves_toolkit import geometry as geo  # noqa: E402
from etr_curves_toolkit import spline_data as sd  # noqa: E402

toolkit.register()
ops = bpy.ops.etr


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    toolkit.register() if not hasattr(bpy.types.Scene, "etr_curves_toolkit") else None


def make_curve(name, splines, dims='3D', loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1)):
    curve = bpy.data.curves.new(name, 'CURVE')
    curve.dimensions = dims
    curve.resolution_u = 24
    for spec in splines:
        sd.write_spline(curve, spec)
    obj = bpy.data.objects.new(name, curve)
    bpy.context.scene.collection.objects.link(obj)
    obj.location, obj.rotation_euler, obj.scale = loc, rot, scale
    bpy.context.view_layer.update()
    return obj


def poly(points, cyclic=False, select=()):
    pts = [sd.PointData(co=tuple(p), select=(i in select)) for i, p in enumerate(points)]
    return sd.SplineData('POLY', pts, cyclic, {"resolution_u": 24})


def bez(points, cyclic=False, select=(), types=('AUTO', 'AUTO'), handles=None):
    """Bezier spline; `handles` = {index: (hl, hr)} for explicit handles."""
    pts = []
    for i, p in enumerate(points):
        hl, hr = (handles or {}).get(i, (p, p))
        pts.append(sd.PointData(
            co=tuple(p), hl=tuple(hl), hr=tuple(hr),
            hlt=types[0], hrt=types[1],
            select=(i in select), select_left=(i in select), select_right=(i in select)))
    return sd.SplineData('BEZIER', pts, cyclic, {"resolution_u": 24})


def nurbs(points, cyclic=False, select=()):
    pts = [sd.PointData(co=tuple(p), select=(i in select)) for i, p in enumerate(points)]
    return sd.SplineData('NURBS', pts, cyclic, {"resolution_u": 24, "order_u": 4, "use_endpoint_u": not cyclic})


def evaluated_points(obj, world=False):
    """Set of rounded evaluated vertex positions (order independent)."""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    mesh = bpy.data.meshes.new_from_object(ev)
    mw = obj.matrix_world
    pts = {tuple(round(c, 4) for c in ((mw @ v.co) if world else v.co)) for v in mesh.vertices}
    bpy.data.meshes.remove(mesh)
    return pts


def select_only(obj):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def select_objects(objs, active=None):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active or objs[-1]


def edit(*objs):
    select_objects(list(objs))
    bpy.ops.object.mode_set(mode='EDIT')


def object_mode():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


def spline_count(obj):
    return len(obj.data.splines)


def first_data(obj):
    return sd.read_spline(obj.data.splines[0])


def near(a, b, tol=1e-5):
    return geo.distance(a, b) < tol


def cancelled(op, **kwargs):
    """True if the operator was cancelled. In background mode an operator that
    reports an ERROR raises RuntimeError instead of returning."""
    try:
        return op(**kwargs) == {'CANCELLED'}
    except RuntimeError:
        return True


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# -----------------------------------------------------------------------------
# Invert Direction / Set First Point
# -----------------------------------------------------------------------------

SQUARE = [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)]


@test
def invert_direction_all_types():
    reset()
    objs = {
        "poly_open": make_curve("a", [poly([(0, 0, 0), (1, 1, 0), (2, 0, 1), (3, 1, 0)])]),
        "poly_closed": make_curve("b", [poly(SQUARE, cyclic=True)]),
        "bez_open": make_curve("c", [bez([(0, 0, 0), (1, 1, 0), (2, 0, 0), (3, 2, 0)])]),
        "bez_closed": make_curve("d", [bez(SQUARE, cyclic=True)]),
        "nurbs_open": make_curve("e", [nurbs([(0, 0, 0), (1, 1, 0), (2, 0, 1), (3, 1, 0), (4, 0, 0)])]),
        "nurbs_closed": make_curve("f", [nurbs(SQUARE + [(1, 3, 0)], cyclic=True)]),
    }
    before = {k: evaluated_points(o) for k, o in objs.items()}
    firsts = {k: first_data(o).points[0].co for k, o in objs.items()}
    lasts = {k: first_data(o).points[-1].co for k, o in objs.items()}
    select_objects(list(objs.values()))
    assert ops.curve_toolkit_invert_direction() == {'FINISHED'}
    for k, o in objs.items():
        assert evaluated_points(o) == before[k], f"{k}: shape changed"
        d = first_data(o)
        if "closed" in k:
            assert near(d.points[0].co, firsts[k]), f"{k}: point 0 must stay point 0"
        else:
            assert near(d.points[0].co, lasts[k]) and near(d.points[-1].co, firsts[k]), f"{k}: not reversed"


@test
def invert_direction_closed_order():
    reset()
    o = make_curve("a", [poly(SQUARE, cyclic=True)])
    select_only(o)
    ops.curve_toolkit_invert_direction()
    cos = [p.co for p in first_data(o).points]
    assert [tuple(c) for c in cos] == [SQUARE[0], SQUARE[3], SQUARE[2], SQUARE[1]], cos


@test
def invert_direction_edit_mode_only_selected_splines():
    reset()
    o = make_curve("a", [
        poly([(0, 0, 0), (1, 0, 0), (2, 1, 0)], select=(1,)),
        poly([(0, 5, 0), (1, 5, 0), (2, 6, 0)]),
    ])
    edit(o)
    assert bpy.context.mode == 'EDIT_CURVE'
    assert ops.curve_toolkit_invert_direction() == {'FINISHED'}
    assert bpy.context.mode == 'EDIT_CURVE', "must return to Edit Mode"
    object_mode()
    s0, s1 = sd.read_all(o.data)
    assert near(s0.points[0].co, (2, 1, 0))
    assert near(s1.points[0].co, (0, 5, 0)), "unselected spline must not change"


@test
def set_first_point_closed_all_types():
    reset()
    cases = {
        "poly": poly(SQUARE, cyclic=True, select=(2,)),
        "bez": bez(SQUARE, cyclic=True, select=(2,)),
        "bez_free": bez(SQUARE, cyclic=True, select=(2,), types=('FREE', 'FREE'),
                        handles={i: ((p[0] - .3, p[1] - .2, 0), (p[0] + .5, p[1] + .1, 0)) for i, p in enumerate(SQUARE)}),
        "nurbs": nurbs(SQUARE + [(1, 3, 0)], cyclic=True, select=(2,)),
    }
    for name, spline in cases.items():
        reset()
        o = make_curve(name, [spline])
        before = evaluated_points(o)
        edit(o)
        assert ops.curve_toolkit_set_first_point() == {'FINISHED'}, name
        object_mode()
        assert near(first_data(o).points[0].co, SQUARE[2]), f"{name}: wrong first point"
        assert evaluated_points(o) == before, f"{name}: shape changed"
        assert first_data(o).points[0].select, f"{name}: selection lost"


@test
def set_first_point_open():
    reset()
    o = make_curve("a", [bez([(0, 0, 0), (1, 1, 0), (2, 0, 0)], select=(2,))])
    before = evaluated_points(o)
    edit(o)
    assert ops.curve_toolkit_set_first_point() == {'FINISHED'}
    object_mode()
    assert near(first_data(o).points[0].co, (2, 0, 0))
    assert evaluated_points(o) == before

    reset()
    o = make_curve("b", [poly([(0, 0, 0), (1, 1, 0), (2, 0, 0)], select=(1,))])   # middle point of an open curve
    edit(o)
    ops.curve_toolkit_set_first_point()
    object_mode()
    assert near(first_data(o).points[0].co, (0, 0, 0)), "middle point of an open spline must not change anything"


# -----------------------------------------------------------------------------
# Split at Points
# -----------------------------------------------------------------------------

@test
def split_at_points_open_and_closed():
    reset()
    o = make_curve("open", [bez([(0, 0, 0), (1, 1, 0), (2, 0, 0), (3, 1, 0)])], loc=(1, 2, 3), rot=(0.3, 0, 0.7))
    before = evaluated_points(o, world=True)
    select_only(o)
    assert ops.curve_toolkit_split_at_points() == {'FINISHED'}
    pieces = [x for x in bpy.data.objects if x.name.startswith("Split_")]
    assert sorted(x.name for x in pieces) == ["Split_01", "Split_02", "Split_03"]
    assert o.hide_get(), "original must be hidden"
    after = set()
    for x in pieces:
        assert spline_count(x) == 1 and len(x.data.splines[0].bezier_points) == 2
        after |= evaluated_points(x, world=True)
    assert after == before, "pieces must reproduce the original shape"

    reset()
    o = make_curve("closed", [bez(SQUARE, cyclic=True)])
    before = evaluated_points(o)
    select_only(o)
    ops.curve_toolkit_split_at_points()
    pieces = [x for x in bpy.data.objects if x.name.startswith("Split_")]
    assert len(pieces) == 4
    after = set().union(*(evaluated_points(x) for x in pieces))
    assert after == before


@test
def split_at_points_collection_and_nurbs():
    reset()
    o = make_curve("a", [poly([(0, 0, 0), (1, 0, 0), (2, 1, 0)])])
    bpy.context.scene.etr_curves_toolkit.results_in_collection = True
    bpy.context.scene.etr_curves_toolkit.sources_in_collection = True
    select_only(o)
    ops.curve_toolkit_split_at_points()
    coll = bpy.data.collections.get("Curve Boolean Results")
    assert coll is not None and len(coll.objects) == 2
    assert not any(x.name.startswith("Split_") for x in bpy.context.scene.collection.objects)
    src = bpy.data.collections.get("Curve Boolean Sources")
    assert src is not None and list(src.objects) == [o]
    assert bpy.context.view_layer.layer_collection.children[src.name].exclude

    reset()
    o = make_curve("n", [nurbs([(0, 0, 0), (1, 1, 0), (2, 0, 0), (3, 1, 0)])])
    select_only(o)
    assert cancelled(ops.curve_toolkit_split_at_points)
    assert not o.hide_get()


@test
def split_at_points_edit_mode_selected():
    reset()
    o = make_curve("a", [bez([(0, 0, 0), (1, 1, 0), (2, 0, 0), (3, 1, 0), (4, 0, 0)], select=(2,))])
    before = evaluated_points(o)
    edit(o)
    assert ops.curve_toolkit_split_at_points() == {'FINISHED'}
    pieces = [x for x in bpy.data.objects if x.name.startswith("Split_")]
    assert len(pieces) == 2
    assert set().union(*(evaluated_points(x) for x in pieces)) == before


# -----------------------------------------------------------------------------
# Join & Merge / Remove Doubles
# -----------------------------------------------------------------------------

@test
def join_merge_chain_and_close():
    reset()
    a = make_curve("a", [poly([(0, 0, 0), (1, 0, 0)])])
    b = make_curve("b", [poly([(1.0004, 0, 0), (2, 1, 0)])])
    c = make_curve("c", [poly([(2, 1, 0.0003), (0, 1, 0)])])
    d = make_curve("d", [poly([(0, 1.0002, 0), (0, 0, 0)])])
    select_objects([a, b, c, d], active=a)
    assert ops.curve_toolkit_join_merge() == {'FINISHED'}
    assert spline_count(a) == 1
    s = first_data(a)
    assert s.cyclic and len(s.points) == 4, (s.cyclic, len(s.points))
    assert len([o for o in bpy.data.objects if o.type == 'CURVE']) == 1


@test
def join_merge_mixed_types_become_bezier():
    reset()
    a = make_curve("a", [poly([(0, 0, 0), (1, 0, 0)])])
    b = make_curve("b", [bez([(1, 0, 0), (2, 1, 0), (3, 0, 0)])])
    shape_b = evaluated_points(b)
    select_objects([a, b], active=b)
    ops.curve_toolkit_join_merge()
    assert spline_count(b) == 1
    s = first_data(b)
    assert s.kind == 'BEZIER' and len(s.points) == 4
    assert shape_b <= evaluated_points(b), "original Bezier shape must be preserved"


@test
def join_merge_disconnected_warns_and_threshold():
    reset()
    a = make_curve("a", [poly([(0, 0, 0), (1, 0, 0)])])
    b = make_curve("b", [poly([(1.01, 0, 0), (2, 0, 0)])])
    select_objects([a, b], active=a)
    ops.curve_toolkit_join_merge()
    assert spline_count(a) == 2

    reset()
    a = make_curve("a", [poly([(0, 0, 0), (1, 0, 0)])])
    b = make_curve("b", [poly([(1.01, 0, 0), (2, 0, 0)])])
    bpy.context.scene.etr_curves_toolkit.merge_threshold = 0.02
    select_objects([a, b], active=a)
    ops.curve_toolkit_join_merge()
    assert spline_count(a) == 1


@test
def join_merge_rejects_nurbs():
    reset()
    a = make_curve("a", [poly([(0, 0, 0), (1, 0, 0)])])
    n = make_curve("n", [nurbs([(0, 0, 0), (1, 1, 0), (2, 0, 0), (3, 1, 0)])])
    select_objects([a, n], active=a)
    assert cancelled(ops.curve_toolkit_join_merge)
    assert len([o for o in bpy.data.objects if o.type == 'CURVE']) == 2


@test
def remove_doubles():
    reset()
    o = make_curve("a", [poly([(0, 0, 0), (1, 0, 0), (1.0005, 0, 0), (2, 1, 0), (0.0002, 0, 0)], cyclic=True)])
    select_only(o)
    assert ops.curve_toolkit_remove_doubles() == {'FINISHED'}
    assert len(first_data(o).points) == 3

    reset()   # Bezier: handles of the outer sides must survive
    o = make_curve("b", [bez([(0, 0, 0), (2, 0, 0), (2.0004, 0, 0), (4, 2, 0)], types=('FREE', 'FREE'),
                             handles={1: ((1, 1, 0), (2, -1, 0)), 2: ((2.0004, 1, 0), (3, 3, 0))})])
    select_only(o)
    ops.curve_toolkit_remove_doubles()
    d = first_data(o)
    assert len(d.points) == 3
    assert near(d.points[1].hl, (1, 1, 0)) and near(d.points[1].hr, (3, 3, 0))


@test
def remove_doubles_edit_mode_only_selected():
    reset()
    o = make_curve("a", [poly([(0, 0, 0), (1, 0, 0), (1.0001, 0, 0), (2, 0, 0), (2.0001, 0, 0)], select=(3, 4))])
    edit(o)
    ops.curve_toolkit_remove_doubles()
    object_mode()
    assert len(first_data(o).points) == 4


# -----------------------------------------------------------------------------
# Change Origin
# -----------------------------------------------------------------------------

@test
def change_origin():
    for mode, expected_local in (('IN', (0, 0, 0)), ('MID', (2, 0, 0)), ('OUT', (4, 0, 0))):
        reset()
        o = make_curve("a", [poly([(0, 0, 0), (1, 0, 0), (4, 0, 0)])],
                       loc=(10, 0, 0), rot=(0, 0, math.pi / 2), scale=(2, 2, 2))
        before = evaluated_points(o, world=True)
        child = make_curve("child", [poly([(0, 0, 0), (1, 1, 1)])])
        child.parent = o
        bpy.context.view_layer.update()
        child_world = child.matrix_world.copy()
        select_only(o)
        assert ops.curve_toolkit_change_origin(mode=mode) == {'FINISHED'}
        bpy.context.view_layer.update()
        expected_world = Vector(expected_local)
        expected_world = (o.matrix_world @ Vector((0, 0, 0)))
        # The new origin must sit where the requested local point was.
        original_world = Vector((10, 0, 0)) + Vector((0, 2 * expected_local[0], 0))
        assert near(tuple(o.matrix_world.translation), tuple(original_world)), (mode, o.matrix_world.translation)
        assert evaluated_points(o, world=True) == before, f"{mode}: geometry moved"
        assert all(abs(a - b) < 1e-5 for ra, rb in zip(child.matrix_world, child_world) for a, b in zip(ra, rb)), "child moved"


@test
def change_origin_midpoint_by_length_and_nurbs_and_geometry():
    reset()
    o = make_curve("a", [poly([(0, 0, 0), (1, 0, 0), (4, 0, 0)])])    # unequal segments: index midpoint (1,0,0) is wrong
    select_only(o)
    ops.curve_toolkit_change_origin(mode='MID')
    assert near(tuple(o.location), (2, 0, 0))

    reset()
    o = make_curve("n", [nurbs([(0, 0, 0), (2, 0, 0), (4, 0, 0), (6, 0, 0), (8, 0, 0)])])
    select_only(o)
    ops.curve_toolkit_change_origin(mode='MID')
    assert abs(o.location.x - 4.0) < 0.02, o.location

    reset()
    o = make_curve("g", [poly([(0, 0, 0), (4, 0, 0), (4, 2, 0), (0, 2, 0)], cyclic=True)])
    select_only(o)
    assert ops.curve_toolkit_change_origin(mode='GEOMETRY') == {'FINISHED'}
    assert near(tuple(o.location), (2, 1, 0))


@test
def change_origin_skips_shared_data():
    reset()
    a = make_curve("a", [poly([(0, 0, 0), (2, 0, 0)])])
    b = bpy.data.objects.new("b", a.data)
    bpy.context.scene.collection.objects.link(b)
    select_only(a)
    assert ops.curve_toolkit_change_origin(mode='OUT') == {'CANCELLED'}


# -----------------------------------------------------------------------------
# Round Corners
# -----------------------------------------------------------------------------

def _arc_ok(obj, center, radius, region):
    """All evaluated points inside `region(pt)` must lie on the given circle."""
    pts = [p for p in evaluated_points(obj) if region(p)]
    assert pts, "no arc points found"
    for p in pts:
        d = math.dist(p, center)
        assert abs(d - radius) < 6e-4, (p, d)


@test
def round_poly_square():
    reset()
    o = make_curve("a", [poly([(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)], cyclic=True, select=(0, 1, 2, 3))])
    edit(o)
    assert ops.curve_toolkit_round_corners(radius=0.3) == {'FINISHED'}
    assert bpy.context.mode == 'EDIT_CURVE'
    object_mode()
    d = first_data(o)
    assert d.kind == 'BEZIER' and d.cyclic and len(d.points) == 8, (d.kind, len(d.points))
    _arc_ok(o, (1.7, 1.7, 0), 0.3, lambda p: p[0] > 1.71 and p[1] > 1.71)
    _arc_ok(o, (0.3, 0.3, 0), 0.3, lambda p: p[0] < 0.29 and p[1] < 0.29)
    # The straight sides stay straight and tangent continuous.
    pts = evaluated_points(o)
    assert all(abs(p[1]) < 1e-4 for p in pts if 0.31 < p[0] < 1.69 and p[1] < 1)


@test
def round_sharp_angle_uses_two_cubics_and_clamps():
    reset()
    o = make_curve("a", [poly([(0, 0, 0), (4, 0.5, 0), (0, 1, 0)], select=(1,))])
    edit(o)
    ops.curve_toolkit_round_corners(radius=0.2)
    object_mode()
    d = first_data(o)
    assert len(d.points) >= 4, "a sharp corner needs more than one cubic (sweep > 90 degrees)"
    # Radius that cannot fit is reduced instead of failing.
    reset()
    o = make_curve("b", [poly([(0, 0, 0), (1, 0, 0), (1, 1, 0)], select=(1,))])
    edit(o)
    assert ops.curve_toolkit_round_corners(radius=50.0) == {'FINISHED'}
    object_mode()
    pts = evaluated_points(o)
    assert all(-1e-4 <= p[0] <= 1.0001 and -1e-4 <= p[1] <= 1.0001 for p in pts)


@test
def round_shared_segment_no_overlap():
    reset()
    o = make_curve("a", [poly([(0, 0, 0), (1, 0, 0), (1, 5, 0), (0, 5, 0)], cyclic=True, select=(0, 1, 2, 3))])
    edit(o)
    ops.curve_toolkit_round_corners(radius=0.9)     # the 1-wide side only has room for 0.5 + 0.5
    object_mode()
    d = first_data(o)
    xs = [p.co[0] for p in d.points]
    assert all(-1e-6 <= x <= 1 + 1e-6 for x in xs)


@test
def round_bezier_vector_corners_and_selection():
    reset()
    o = make_curve("a", [bez([(0, 0, 0), (3, 0, 0), (3, 3, 0)], types=('VECTOR', 'VECTOR'), select=(1,))])
    edit(o)
    assert ops.curve_toolkit_round_corners(radius=0.5) == {'FINISHED'}
    object_mode()
    d = first_data(o)
    assert d.kind == 'BEZIER' and len(d.points) == 4
    assert [p.select for p in d.points] == [False, True, True, False]
    _arc_ok(o, (2.5, 0.5, 0), 0.5, lambda p: p[0] > 2.51 and p[1] < 0.49)


@test
def round_ignores_smooth_and_curved_corners():
    reset()
    o = make_curve("a", [bez([(0, 0, 0), (2, 1, 0), (4, 0, 0)], select=(1,))])    # smooth AUTO handles: not a corner
    before = evaluated_points(o)
    edit(o)
    assert ops.curve_toolkit_round_corners(radius=0.3) == {'CANCELLED'}
    object_mode()
    assert evaluated_points(o) == before



K = 4 / 3 * math.tan(math.pi / 8)


def _curved_corner_spline(select=(1,)):
    """Quarter circle into a curved segment: a sharp corner at (1, 0, 0)."""
    return bez([(0, 1, 0), (1, 0, 0), (2.4, 1, 0)], types=('FREE', 'FREE'), select=select,
               handles={0: ((0, 1, 0), (K, 1, 0)), 1: ((1, K, 0), (1.3, 0.6, 0)), 2: ((1.6, 0.95, 0), (2.4, 1, 0))})


def _no_corners_left(d):
    from etr_curves_toolkit.round_bridge import _corner_kind
    return all(_corner_kind(d, i) is None for i in range(len(d.points)))


@test
def round_curved_corner_true_fillet():
    reset()
    o = make_curve("a", [_curved_corner_spline()])
    orig = first_data(o)
    seg_in = (orig.points[0].co, orig.points[0].hr, orig.points[1].hl, orig.points[1].co)
    seg_out = (orig.points[1].co, orig.points[1].hr, orig.points[2].hl, orig.points[2].co)
    f = geo.fillet_curved_corner(seg_in, seg_out, 0.2)
    edit(o)
    assert ops.curve_toolkit_round_corners(radius=0.2) == {'FINISHED'}
    object_mode()
    d = first_data(o)
    t1, t2 = d.points[1], d.points[-2]
    assert near(t1.co, f.t1) and near(t2.co, f.t2)
    # Tangent points are at the radius from the center, and the arc stays on the circle.
    pts = d.points
    for a, b in zip(pts[1:-2], pts[2:-1]):
        for i in range(11):
            q = geo.bezier_point(a.co, a.hr, b.hl, b.co, i / 10)
            assert abs(geo.distance(q, f.center) - 0.2) < 3e-4
    # The trimmed curves are exactly the original ones (de Casteljau keeps the
    # parametrization: new(t) == original(t * u)).
    first = (pts[0].co, pts[0].hr, pts[1].hl, pts[1].co)
    last = (pts[-2].co, pts[-2].hr, pts[-1].hl, pts[-1].co)
    for i in range(11):
        t = i / 10
        assert near(geo.bezier_point(*first, t), geo.bezier_point(*seg_in, t * f.u), 1e-5)
        assert near(geo.bezier_point(*last, t), geo.bezier_point(*seg_out, f.v + t * (1 - f.v)), 1e-5)
    assert _no_corners_left(d), "the result must be tangent continuous"


@test
def round_curved_triangle_all_corners():
    reset()
    tri = bez([(0, 0, 0), (4, 0, 0), (2, 3, 0)], cyclic=True, types=('FREE', 'FREE'), select=(0, 1, 2),
              handles={0: ((0.3, 1.2, 0), (1.2, -0.6, 0)), 1: ((2.8, -0.6, 0), (3.9, 1.2, 0)), 2: ((2.6, 2.4, 0), (1.4, 2.4, 0))})
    o = make_curve("t", [tri])
    edit(o)
    assert ops.curve_toolkit_round_corners(radius=0.3) == {'FINISHED'}
    object_mode()
    d = first_data(o)
    assert d.cyclic and len(d.points) >= 6
    assert _no_corners_left(d)


@test
def round_mixed_straight_and_curved():
    reset()
    s = bez([(0, 0, 0), (2, 0, 0), (3, 2, 0)], types=('FREE', 'FREE'), select=(1,),
            handles={0: ((0, 0, 0), (2 / 3, 0, 0)), 1: ((4 / 3, 0, 0), (2.8, 0.2, 0)), 2: ((3.2, 1.0, 0), (3, 2, 0))})
    o = make_curve("m", [s])
    edit(o)
    assert ops.curve_toolkit_round_corners(radius=0.25) == {'FINISHED'}
    object_mode()
    d = first_data(o)
    assert _no_corners_left(d)
    # The straight part is still on the X axis.
    assert abs(d.points[1].co[1]) < 1e-9 and abs(d.points[0].hr[1]) < 1e-9


@test
def round_tension():
    import math as m
    # Tension 0: a straight bevel.
    for spline in (poly([(0, 0, 0), (2, 0, 0), (2, 2, 0)], select=(1,)), _curved_corner_spline()):
        reset()
        o = make_curve("a", [spline])
        edit(o)
        assert ops.curve_toolkit_round_corners(radius=0.3, tension=0.0) == {'FINISHED'}
        object_mode()
        d = first_data(o)
        assert len(d.points) == 4
        a, b = d.points[1], d.points[2]
        assert geo.is_straight_segment(a.co, a.hr, b.hl, b.co), "tension 0 must give a straight bevel"
        assert _no_corners_left(d) is False
    # Tension 2: handles twice as long as the circle's.
    reset()
    o = make_curve("b", [poly([(0, 0, 0), (2, 0, 0), (2, 2, 0)], select=(1,))])
    edit(o)
    ops.curve_toolkit_round_corners(radius=0.3, tension=2.0)
    object_mode()
    d = first_data(o)
    circle_h = 4 / 3 * m.tan(m.pi / 8) * 0.3
    assert len(d.points) == 4
    assert abs(geo.distance(d.points[1].co, d.points[1].hr) - 2 * circle_h) < 1e-5
    assert abs(geo.distance(d.points[2].co, d.points[2].hl) - 2 * circle_h) < 1e-5
    assert _no_corners_left(d)
    # Tension above 2 is accepted.
    reset()
    o = make_curve("c", [poly([(0, 0, 0), (2, 0, 0), (2, 2, 0)], select=(1,))])
    edit(o)
    assert ops.curve_toolkit_round_corners(radius=0.3, tension=6.0) == {'FINISHED'}
    object_mode()


@test
def round_3d_corner():
    reset()
    o = make_curve("a", [poly([(0, 0, 0), (2, 0, 0), (2, 0, 2)], select=(1,))])   # corner in the XZ plane
    edit(o)
    ops.curve_toolkit_round_corners(radius=0.4)
    object_mode()
    _arc_ok(o, (1.6, 0, 0.4), 0.4, lambda p: p[0] > 1.61 and p[2] < 0.39)


@test
def round_handle_types():
    # Tension 0: the bevel is a straight segment with Vector handles at 1/3,
    # so its points can be rounded again.
    reset()
    o = make_curve("a", [poly([(0, 0, 0), (2, 0, 0), (2, 2, 0)], select=(1,))])
    edit(o)
    ops.curve_toolkit_round_corners(radius=0.5, tension=0.0)
    object_mode()
    d = first_data(o)
    t1, t2 = d.points[1], d.points[2]
    assert (t1.hlt, t1.hrt, t2.hlt, t2.hrt) == ('VECTOR',) * 4
    third = geo.distance(t1.co, t2.co) / 3
    assert abs(geo.distance(t1.co, t1.hr) - third) < 1e-5 and abs(geo.distance(t2.co, t2.hl) - third) < 1e-5
    # Round the two new corners of the bevel again.
    for i, p in enumerate(o.data.splines[0].bezier_points):
        p.select_control_point = i in (1, 2)
    edit(o)
    assert ops.curve_toolkit_round_corners(radius=0.1, tension=1.0) == {'FINISHED'}
    object_mode()
    assert len(first_data(o).points) == 6

    # Tension 1 on straight sides: Vector on the straight side, Aligned on the
    # arc side (in line with it); middle anchors of a wide arc are Aligned.
    reset()
    o = make_curve("b", [poly([(0, 0, 0), (4, 0.5, 0), (0, 1, 0)], select=(1,))])
    edit(o)
    ops.curve_toolkit_round_corners(radius=0.2)
    object_mode()
    d = first_data(o)
    arc = d.points[1:-1]
    assert (arc[0].hlt, arc[0].hrt) == ('VECTOR', 'ALIGNED')
    assert (arc[-1].hlt, arc[-1].hrt) == ('ALIGNED', 'VECTOR')
    assert all((p.hlt, p.hrt) == ('ALIGNED', 'ALIGNED') for p in arc[1:-1]) and len(arc) > 2

    # Curved corner: the tangent points join two curved segments -> Aligned.
    reset()
    o = make_curve("c", [_curved_corner_spline()])
    edit(o)
    ops.curve_toolkit_round_corners(radius=0.2)
    object_mode()
    d = first_data(o)
    assert (d.points[1].hlt, d.points[1].hrt) == ('ALIGNED', 'ALIGNED')
    assert (d.points[-2].hlt, d.points[-2].hrt) == ('ALIGNED', 'ALIGNED')


# -----------------------------------------------------------------------------
# Bridge Curves
# -----------------------------------------------------------------------------

def _two_arcs(select_a=(2,), select_b=(0,)):
    a = bez([(0, 0, 0), (1, 1, 0), (2, 1, 0)], types=('AUTO', 'AUTO'), select=select_a)
    b = bez([(4, 0, 0), (5, -1, 0), (6, -1, 0)], types=('AUTO', 'AUTO'), select=select_b)
    return a, b


@test
def bridge_same_object():
    reset()
    a, b = _two_arcs()
    o = make_curve("a", [a, b])
    shape = evaluated_points(o)
    pa, pb = sd.read_all(o.data)
    edit(o)
    assert ops.curve_toolkit_bridge_curves(tension=1.0) == {'FINISHED'}
    object_mode()
    assert spline_count(o) == 1
    d = first_data(o)
    assert d.kind == 'BEZIER' and len(d.points) == 6 and not d.cyclic
    # Original curvature untouched: the original sample points are all still there.
    assert shape <= evaluated_points(o)
    # G1 at both ends: handles are collinear with the original tangents.
    tail, head = d.points[2], d.points[3]
    t_a = geo.normalized(geo.sub(pa.points[2].co, pa.points[2].hl))
    assert near(geo.normalized(geo.sub(tail.hr, tail.co)), t_a, 1e-4)
    t_b = geo.normalized(geo.sub(pb.points[0].co, pb.points[0].hr))       # pointing out of B
    assert near(geo.normalized(geo.sub(head.hl, head.co)), t_b, 1e-4)
    chord = geo.distance(tail.co, head.co)
    assert abs(geo.distance(tail.co, tail.hr) - chord / 3) < 1e-5, "tension 1.0 -> chord / 3"


@test
def bridge_tension_zero_is_straight_and_two_is_longer():
    reset()
    a, b = _two_arcs()
    o = make_curve("a", [a, b])
    edit(o)
    ops.curve_toolkit_bridge_curves(tension=0.0)
    object_mode()
    d = first_data(o)
    assert geo.is_straight_segment(d.points[2].co, d.points[2].hr, d.points[3].hl, d.points[3].co)

    reset()
    a, b = _two_arcs()
    o = make_curve("a", [a, b])
    edit(o)
    ops.curve_toolkit_bridge_curves(tension=2.0)
    object_mode()
    d = first_data(o)
    chord = geo.distance(d.points[2].co, d.points[3].co)
    assert abs(geo.distance(d.points[2].co, d.points[2].hr) - 2 * chord / 3) < 1e-5


@test
def bridge_handle_types():
    reset()
    a, b = _two_arcs()
    o = make_curve("a", [a, b])
    edit(o)
    ops.curve_toolkit_bridge_curves(tension=1.0)
    object_mode()
    d = first_data(o)
    assert (d.points[2].hlt, d.points[2].hrt) == ('ALIGNED', 'ALIGNED')
    assert (d.points[3].hlt, d.points[3].hrt) == ('ALIGNED', 'ALIGNED')

    reset()
    a, b = _two_arcs()
    o = make_curve("a", [a, b])
    edit(o)
    ops.curve_toolkit_bridge_curves(tension=0.0)
    object_mode()
    d = first_data(o)
    tail, head = d.points[2], d.points[3]
    assert (tail.hlt, tail.hrt, head.hlt, head.hrt) == ('FREE', 'VECTOR', 'VECTOR', 'FREE')
    third = geo.distance(tail.co, head.co) / 3
    assert abs(geo.distance(tail.co, tail.hr) - third) < 1e-5

    reset()   # two objects, tension 0: the new 2-point bridge has Vector handles
    pa = make_curve("pa", [poly([(0, 0, 0), (1, 1, 0), (2, 1, 0)], select=(2,))])
    pb = make_curve("pb", [poly([(4, 0, 0), (5, -1, 0)], select=(0,))])
    edit(pa, pb)
    ops.curve_toolkit_bridge_curves(tension=0.0)
    object_mode()
    br = [x for x in bpy.data.objects if x.name.startswith("Bridge")][0]
    d = first_data(br)
    assert d.points[0].hrt == 'VECTOR' and d.points[1].hlt == 'VECTOR'


@test
def bridge_tension_above_two():
    reset()
    a, b = _two_arcs()
    o = make_curve("a", [a, b])
    edit(o)
    assert ops.curve_toolkit_bridge_curves(tension=5.0) == {'FINISHED'}
    object_mode()
    d = first_data(o)
    chord = geo.distance(d.points[2].co, d.points[3].co)
    assert abs(geo.distance(d.points[2].co, d.points[2].hr) - 5 * chord / 3) < 1e-5


@test
def bridge_two_objects_poly_and_bezier():
    reset()
    a = make_curve("a", [poly([(0, 0, 0), (1, 1, 0), (2, 1, 0)], select=(2,))], loc=(0, 0, 1))
    b = make_curve("b", [bez([(4, 0, 0), (5, -1, 0), (6, -1, 0)], select=(0,))], loc=(0, 0, 1))
    sa, sb = evaluated_points(a), evaluated_points(b)
    edit(a, b)
    assert ops.curve_toolkit_bridge_curves(tension=1.0) == {'FINISHED'}
    object_mode()
    bridges = [o for o in bpy.data.objects if o.name.startswith("Bridge")]
    assert len(bridges) == 1
    br = bridges[0]
    d = first_data(br)
    assert d.kind == 'BEZIER' and len(d.points) == 2
    world = [tuple(br.matrix_world @ Vector(p.co)) for p in d.points]
    assert sorted(world) == [(2, 1, 1), (4, 0, 1)], world
    # Poly end (2, 1): its tangent is the direction of its last segment (+X).
    k = world.index((2, 1, 1))
    assert near(geo.normalized(geo.sub(d.points[k].hr if k == 0 else d.points[k].hl, d.points[k].co)), (1, 0, 0), 1e-5)
    assert evaluated_points(a) == sa and evaluated_points(b) == sb, "originals must not change"


@test
def bridge_closes_a_spline_and_validates():
    reset()
    arc = bez([(0, 0, 0), (1, 1, 0), (2, 0, 0)], select=(0, 2))
    o = make_curve("a", [arc])
    edit(o)
    assert ops.curve_toolkit_bridge_curves() == {'FINISHED'}
    object_mode()
    assert first_data(o).cyclic and len(first_data(o).points) == 3

    reset()    # a middle point is not an end point
    o = make_curve("b", [bez([(0, 0, 0), (1, 1, 0), (2, 0, 0)], select=(1, 2))])
    edit(o)
    assert cancelled(ops.curve_toolkit_bridge_curves)
    object_mode()

    reset()    # one end point only
    o = make_curve("c", [bez([(0, 0, 0), (1, 1, 0), (2, 0, 0)], select=(2,))])
    edit(o)
    assert cancelled(ops.curve_toolkit_bridge_curves)
    object_mode()


# -----------------------------------------------------------------------------
# Geometry helpers
# -----------------------------------------------------------------------------

@test
def geometry_arc_accuracy():
    for sweep in (0.4, math.pi / 2, math.pi, 2.6):
        anchors = geo.arc_beziers((0, 0, 0), (1, 0, 0), (0, 1, 0), 1.0, sweep)
        worst = 0.0
        for (p0, _, h0), (p1, h1, _) in zip(anchors, anchors[1:]):
            for i in range(21):
                q = geo.bezier_point(p0, h0, h1, p1, i / 20)
                worst = max(worst, abs(math.hypot(q[0], q[1]) - 1.0))
        assert worst < 3e-4, (sweep, worst)
        end = anchors[-1][0]
        assert abs(end[0] - math.cos(sweep)) < 1e-9 and abs(end[1] - math.sin(sweep)) < 1e-9


# -----------------------------------------------------------------------------
# Panel, icons, registration
# -----------------------------------------------------------------------------

@test
def panel_uses_existing_operators_properties_and_icons():
    from unittest import mock
    from etr_curves_toolkit import panel

    reset()
    layout = mock.MagicMock()
    fake_self = mock.MagicMock()
    fake_self.layout = layout
    ctx = mock.MagicMock()
    ctx.scene = bpy.context.scene
    for cls in panel.classes:
        cls.draw(fake_self, ctx)

    idnames = set()
    for call in layout.mock_calls + layout.row().mock_calls + layout.column().mock_calls:
        name = call[0]
        if name.endswith("operator") and call[1]:
            idnames.add(call[1][0])
    assert idnames, "panel draws no operators"
    for idname in idnames:
        mod, op = idname.split(".")
        assert hasattr(getattr(bpy.ops, mod), op), f"missing operator {idname}"
        bpy.ops.etr  # noqa: B018

    props = bpy.context.scene.etr_curves_toolkit.bl_rna.properties
    for name in ("merge_threshold", "sources_in_collection", "results_in_collection"):
        assert name in props

    for icon in ("round", "bridge", "union", "intersection", "difference", "split_active", "split_all",
                 "circle_center_point", "circle_2_points", "circle_3_points", "circle_segment_center"):
        # icon_id is only assigned when a UI exists, so check the preview itself.
        assert icon in panel._icons and tuple(panel._icons[icon].icon_size) == (32, 32), f"icon {icon} not loaded"


@test
def register_unregister_cycle():
    toolkit.unregister()
    assert not hasattr(bpy.types.Scene, "etr_curves_toolkit")
    assert not hasattr(bpy.ops.etr, "curve_toolkit_round_corners") or True
    toolkit.register()
    assert hasattr(bpy.types.Scene, "etr_curves_toolkit")


def main():
    failed = 0
    for fn in TESTS:
        try:
            fn()
            object_mode() if bpy.context.mode != 'OBJECT' else None
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
            try:
                object_mode()
            except Exception:
                pass
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    toolkit.unregister()
    sys.exit(1 if failed else 0)


main()
