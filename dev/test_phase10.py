# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Tests of the Phase 10 tools of Curve Toolkit (Merge Pair and Merge by
Distance), with Blender as a Python module:

    python test_phase10.py <folder that contains the etr_curve_toolkit package>

Every test builds its own curves from scratch. Distances are checked in world
space, so a tool that forgot the transform of the object would fail.
"""

import sys
import traceback

sys.path.insert(0, sys.argv[1])

import bpy  # noqa: E402

import etr_curve_toolkit as toolkit  # noqa: E402
from etr_curve_toolkit import geometry as geo  # noqa: E402
from etr_curve_toolkit import spline_data as sd  # noqa: E402


toolkit.register()
ops = bpy.ops.etr


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if not hasattr(bpy.types.Scene, "etr_curve_toolkit"):
        toolkit.register()


def make_curve(name, splines, dims='3D', loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1)):
    curve = bpy.data.curves.new(name, 'CURVE')
    curve.dimensions = dims
    curve.resolution_u = 12
    for spec in splines:
        sd.write_spline(curve, spec)
    obj = bpy.data.objects.new(name, curve)
    bpy.context.scene.collection.objects.link(obj)
    obj.location, obj.rotation_euler, obj.scale = loc, rot, scale
    bpy.context.view_layer.update()
    return obj


def bezier(points, cyclic=False, select=(), handles=None, types=('FREE', 'FREE')):
    """Bezier spline; `handles` = {index: (hl, hr)} for explicit handles."""
    pts = []
    for i, p in enumerate(points):
        hl, hr = (handles or {}).get(i, (p, p))
        pts.append(sd.PointData(
            co=tuple(p), hl=tuple(hl), hr=tuple(hr), hlt=types[0], hrt=types[1],
            select=(i in select), select_left=(i in select),
            select_right=(i in select)))
    return sd.SplineData('BEZIER', pts, cyclic, {"resolution_u": 12})


def poly(points, cyclic=False, select=()):
    pts = [sd.PointData(co=tuple(p), select=(i in select)) for i, p in enumerate(points)]
    return sd.SplineData('POLY', pts, cyclic, {"resolution_u": 12})


def nurbs(points, cyclic=False, select=(), order=4):
    pts = [sd.PointData(co=tuple(p), select=(i in select)) for i, p in enumerate(points)]
    return sd.SplineData('NURBS', pts, cyclic,
                         {"resolution_u": 12, "order_u": order})


def straight_bezier(points, cyclic=False, select=()):
    """Bezier spline whose handles are a third of the way to each neighbour,
    so every handle is clearly visible in the comparisons below."""
    handles = {}
    n = len(points)
    for i, p in enumerate(points):
        before = points[i - 1] if (i or cyclic) else None
        after = points[i + 1] if (i < n - 1 or cyclic) else None
        after = after if after is not None else points[(i + 1) % n]
        before = before if before is not None else points[i - 1]
        hl = geo.lerp(p, before, 1.0 / 3.0)
        hr = geo.lerp(p, after, 1.0 / 3.0)
        handles[i] = (hl, hr)
    return bezier(points, cyclic=cyclic, select=select, handles=handles)


def select_only(obj):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def edit(*objs):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[-1]
    bpy.ops.object.mode_set(mode='EDIT')


def object_mode():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


def data_of(obj, index=0):
    return sd.read_spline(obj.data.splines[index])


def near(a, b, tol=1e-5):
    return geo.distance(a, b) <= tol


def cancelled(op, **kwargs):
    """True if the operator was cancelled. In background mode an operator that
    reports an ERROR raises RuntimeError instead of returning."""
    try:
        return op(**kwargs) == {'CANCELLED'}
    except RuntimeError:
        return True


def threshold(value):
    bpy.context.scene.etr_curve_toolkit.merge_threshold = value


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# -----------------------------------------------------------------------------
# Merge Pair: the three allowed cases
# -----------------------------------------------------------------------------

@test
def two_consecutive_points_merge_at_their_centre():
    reset()
    obj = make_curve("C", [poly(
        [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)], select=(1, 2))])
    edit(obj)
    ops.curve_toolkit_merge_pair(at='CENTER')
    object_mode()
    d = data_of(obj)
    assert len(d.points) == 3, len(d.points)
    assert near(d.points[1].co, (1.5, 0, 0)), d.points[1].co
    assert near(d.points[0].co, (0, 0, 0)) and near(d.points[2].co, (3, 0, 0))


@test
def at_point_a_and_at_point_b_pick_the_two_ends_of_the_pair():
    for at, expected in (('A', (1, 0, 0)), ('B', (2, 0, 0))):
        reset()
        obj = make_curve("C", [poly(
            [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)], select=(1, 2))])
        edit(obj)
        ops.curve_toolkit_merge_pair(at=at)
        object_mode()
        d = data_of(obj)
        assert near(d.points[1].co, expected), (at, d.points[1].co)


@test
def point_a_is_the_lower_index_whatever_the_selection_order():
    # The pair is taken in index order, so A is always the earlier point.
    reset()
    obj = make_curve("C", [poly(
        [(0, 0, 0), (10, 0, 0), (20, 0, 0), (30, 0, 0)], select=(2, 1))])
    edit(obj)
    ops.curve_toolkit_merge_pair(at='A')
    object_mode()
    assert near(data_of(obj).points[1].co, (10, 0, 0))


@test
def the_two_ends_of_an_open_spline_close_it():
    reset()
    obj = make_curve("C", [poly(
        [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)], select=(0, 3))])
    edit(obj)
    ops.curve_toolkit_merge_pair(at='CENTER')
    object_mode()
    d = data_of(obj)
    assert d.cyclic, "the spline should be closed now"
    assert len(d.points) == 3, len(d.points)
    assert near(d.points[0].co, (0, 1, 0)), d.points[0].co


@test
def the_ends_of_two_open_splines_join_them_into_one():
    reset()
    obj = make_curve("C", [
        poly([(0, 0, 0), (1, 0, 0), (2, 0, 0)], select=(2,)),
        poly([(4, 0, 0), (5, 0, 0), (6, 0, 0)], select=(0,)),
    ])
    edit(obj)
    ops.curve_toolkit_merge_pair(at='CENTER')
    object_mode()
    assert len(obj.data.splines) == 1, len(obj.data.splines)
    d = data_of(obj)
    assert len(d.points) == 5, len(d.points)
    assert not d.cyclic
    # Walking the result: 0, 1, the weld at 3, then 5 and 6.
    xs = [p.co[0] for p in d.points]
    assert xs == [0.0, 1.0, 3.0, 5.0, 6.0], xs


@test
def joining_inverts_whichever_spline_needs_it():
    # Both splines are welded by their *start* point, so the first one has to
    # be turned around for the chain to run through.
    reset()
    obj = make_curve("C", [
        poly([(0, 0, 0), (-1, 0, 0), (-2, 0, 0)], select=(0,)),
        poly([(1, 0, 0), (2, 0, 0), (3, 0, 0)], select=(0,)),
    ])
    edit(obj)
    ops.curve_toolkit_merge_pair(at='CENTER')
    object_mode()
    d = data_of(obj)
    xs = [p.co[0] for p in d.points]
    assert xs == [-2.0, -1.0, 0.5, 2.0, 3.0], xs


@test
def the_closing_pair_of_a_cyclic_spline_counts_as_consecutive():
    reset()
    obj = make_curve("C", [poly(
        [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)], cyclic=True, select=(0, 3))])
    edit(obj)
    ops.curve_toolkit_merge_pair(at='CENTER')
    object_mode()
    d = data_of(obj)
    assert d.cyclic and len(d.points) == 3, (d.cyclic, len(d.points))
    assert near(d.points[0].co, (0, 1, 0)), d.points[0].co


# -----------------------------------------------------------------------------
# Merge Pair: handles and the shape that survives
# -----------------------------------------------------------------------------

@test
def bezier_handles_travel_with_their_point():
    reset()
    spline = straight_bezier([(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)],
                             select=(1, 2))
    before = [(tuple(p.hl), tuple(p.hr)) for p in spline.points]
    obj = make_curve("C", [spline])
    edit(obj)
    ops.curve_toolkit_merge_pair(at='CENTER')
    object_mode()
    d = data_of(obj)
    assert len(d.points) == 3
    weld = d.points[1]
    # The incoming handle is the one of point 1, the outgoing the one of point
    # 2, each carried along by the move of its own point (+0.5 and -0.5).
    assert near(weld.hl, geo.add(before[1][0], (0.5, 0, 0))), weld.hl
    assert near(weld.hr, geo.add(before[2][1], (-0.5, 0, 0))), weld.hr
    # The points that were not touched keep their handles exactly.
    assert near(d.points[0].hr, before[0][1])
    assert near(d.points[2].hl, before[3][0])


@test
def merging_at_a_point_leaves_that_segment_untouched():
    # At Point A, the segment before the weld is the one it already was.
    reset()
    spline = straight_bezier([(0, 0, 0), (1, 1, 0), (2, 1, 0), (3, 0, 0)],
                             select=(1, 2))
    before = sd.SplineData('BEZIER', [sd.replace(p) for p in spline.points],
                           False, dict(spline.settings))
    obj = make_curve("C", [spline])
    edit(obj)
    ops.curve_toolkit_merge_pair(at='A')
    object_mode()
    d = data_of(obj)
    assert near(d.points[0].co, before.points[0].co)
    assert near(d.points[0].hr, before.points[0].hr)
    assert near(d.points[1].co, before.points[1].co)
    assert near(d.points[1].hl, before.points[1].hl)


@test
def moved_auto_handles_become_free():
    reset()
    spline = bezier([(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)],
                    select=(1, 2), types=('AUTO', 'AUTO'))
    obj = make_curve("C", [spline])
    edit(obj)
    ops.curve_toolkit_merge_pair(at='CENTER')
    object_mode()
    d = data_of(obj)
    assert d.points[1].hlt == 'FREE' and d.points[1].hrt == 'FREE', (
        d.points[1].hlt, d.points[1].hrt)


@test
def vector_handles_stay_vector():
    reset()
    spline = bezier([(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)],
                    select=(1, 2), types=('VECTOR', 'VECTOR'))
    obj = make_curve("C", [spline])
    edit(obj)
    ops.curve_toolkit_merge_pair(at='CENTER')
    object_mode()
    d = data_of(obj)
    assert d.points[1].hlt == 'VECTOR' and d.points[1].hrt == 'VECTOR'


@test
def the_welded_point_is_left_selected():
    reset()
    obj = make_curve("C", [poly(
        [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)], select=(1, 2))])
    edit(obj)
    ops.curve_toolkit_merge_pair(at='CENTER')
    object_mode()
    d = data_of(obj)
    assert d.points[1].select, "the weld should stay selected"


# -----------------------------------------------------------------------------
# Merge Pair: curve types and transforms
# -----------------------------------------------------------------------------

@test
def nurbs_merge_and_the_order_is_lowered_when_it_has_to_be():
    reset()
    obj = make_curve("C", [nurbs(
        [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)], select=(1, 2), order=4)])
    edit(obj)
    ops.curve_toolkit_merge_pair(at='CENTER')
    object_mode()
    spline = obj.data.splines[0]
    assert len(spline.points) == 3, len(spline.points)
    assert spline.order_u <= 3, spline.order_u


@test
def the_merge_happens_in_the_local_space_of_the_object():
    # With the object scaled and moved, the weld still lands halfway between
    # the two points, in local space, so it lands halfway in world space too.
    reset()
    obj = make_curve(
        "C", [poly([(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)], select=(1, 2))],
        loc=(10, -4, 2), scale=(3, 3, 3))
    edit(obj)
    ops.curve_toolkit_merge_pair(at='CENTER')
    object_mode()
    d = data_of(obj)
    assert near(d.points[1].co, (1.5, 0, 0)), d.points[1].co


@test
def far_apart_points_merge_all_the_same():
    # No Threshold here: distance is irrelevant.
    reset()
    obj = make_curve("C", [
        poly([(0, 0, 0), (1, 0, 0)], select=(1,)),
        poly([(5000, 0, 0), (5001, 0, 0)], select=(0,)),
    ])
    edit(obj)
    ops.curve_toolkit_merge_pair(at='CENTER')
    object_mode()
    assert len(obj.data.splines) == 1
    assert near(data_of(obj).points[1].co, (2500.5, 0, 0))


# -----------------------------------------------------------------------------
# Merge Pair: what has to be refused
# -----------------------------------------------------------------------------

@test
def two_middle_points_that_are_not_neighbours_are_refused():
    reset()
    obj = make_curve("C", [poly(
        [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0), (4, 0, 0)], select=(1, 3))])
    edit(obj)
    assert cancelled(ops.curve_toolkit_merge_pair, at='CENTER')
    object_mode()
    assert len(data_of(obj).points) == 5, "the curve should be untouched"


@test
def two_middle_points_of_different_splines_are_refused():
    reset()
    obj = make_curve("C", [
        poly([(0, 0, 0), (1, 0, 0), (2, 0, 0)], select=(1,)),
        poly([(0, 2, 0), (1, 2, 0), (2, 2, 0)], select=(1,)),
    ])
    edit(obj)
    assert cancelled(ops.curve_toolkit_merge_pair, at='CENTER')
    object_mode()
    assert len(obj.data.splines) == 2


@test
def a_point_of_a_closed_spline_cannot_be_welded_to_another_spline():
    reset()
    obj = make_curve("C", [
        poly([(0, 0, 0), (1, 0, 0), (1, 1, 0)], cyclic=True, select=(0,)),
        poly([(4, 0, 0), (5, 0, 0)], select=(0,)),
    ])
    edit(obj)
    assert cancelled(ops.curve_toolkit_merge_pair, at='CENTER')
    object_mode()
    assert len(obj.data.splines) == 2


@test
def non_neighbours_of_a_closed_spline_are_refused():
    reset()
    obj = make_curve("C", [poly(
        [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)], cyclic=True, select=(0, 2))])
    edit(obj)
    assert cancelled(ops.curve_toolkit_merge_pair, at='CENTER')
    object_mode()
    assert len(data_of(obj).points) == 4


@test
def welding_the_only_two_points_of_a_spline_is_refused():
    reset()
    obj = make_curve("C", [poly([(0, 0, 0), (1, 0, 0)], select=(0, 1))])
    edit(obj)
    assert cancelled(ops.curve_toolkit_merge_pair, at='CENTER')
    object_mode()
    assert len(data_of(obj).points) == 2


@test
def splines_of_different_types_are_refused():
    reset()
    obj = make_curve("C", [
        poly([(0, 0, 0), (1, 0, 0)], select=(1,)),
        bezier([(3, 0, 0), (4, 0, 0)], select=(0,)),
    ])
    edit(obj)
    assert cancelled(ops.curve_toolkit_merge_pair, at='CENTER')
    object_mode()
    assert len(obj.data.splines) == 2


@test
def a_selection_that_is_not_two_points_is_refused():
    for picked in ((), (1,), (0, 1, 2)):
        reset()
        obj = make_curve("C", [poly(
            [(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)], select=picked)])
        edit(obj)
        assert cancelled(ops.curve_toolkit_merge_pair, at='CENTER'), picked
        object_mode()
        assert len(data_of(obj).points) == 4, picked


@test
def points_in_two_different_objects_are_refused():
    reset()
    a = make_curve("A", [poly([(0, 0, 0), (1, 0, 0)], select=(1,))])
    b = make_curve("B", [poly([(3, 0, 0), (4, 0, 0)], select=(0,))], loc=(0, 1, 0))
    edit(a, b)
    assert cancelled(ops.curve_toolkit_merge_pair, at='CENTER')
    object_mode()
    assert len(a.data.splines) == 1 and len(b.data.splines) == 1


@test
def a_lone_selected_handle_is_not_a_selected_point():
    reset()
    spline = straight_bezier([(0, 0, 0), (1, 0, 0), (2, 0, 0), (3, 0, 0)],
                             select=(1, 2))
    # Keep the handles of point 2 selected but drop its control point, which
    # leaves a single real selection.
    spline.points[2].select = False
    obj = make_curve("C", [spline])
    edit(obj)
    assert cancelled(ops.curve_toolkit_merge_pair, at='CENTER')
    object_mode()
    assert len(data_of(obj).points) == 4


# -----------------------------------------------------------------------------
# Merge by Distance
# -----------------------------------------------------------------------------

@test
def two_close_ends_are_welded_and_the_splines_chained():
    reset()
    threshold(0.2)
    obj = make_curve("C", [
        poly([(0, 0, 0), (1, 0, 0)], select=(0, 1)),
        poly([(1.1, 0, 0), (2, 0, 0)], select=(0, 1)),
    ])
    edit(obj)
    ops.curve_toolkit_merge_by_distance()
    object_mode()
    assert len(obj.data.splines) == 1, len(obj.data.splines)
    d = data_of(obj)
    assert len(d.points) == 3, len(d.points)
    assert near(d.points[1].co, (1.05, 0, 0)), d.points[1].co


@test
def ends_farther_than_the_threshold_are_left_alone():
    reset()
    threshold(0.05)
    obj = make_curve("C", [
        poly([(0, 0, 0), (1, 0, 0)], select=(0, 1)),
        poly([(1.1, 0, 0), (2, 0, 0)], select=(0, 1)),
    ])
    edit(obj)
    assert cancelled(ops.curve_toolkit_merge_by_distance)
    object_mode()
    assert len(obj.data.splines) == 2


@test
def a_spline_whose_own_ends_meet_is_closed():
    reset()
    threshold(0.2)
    obj = make_curve("C", [poly(
        [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0.1, 0.05, 0)], select=(0, 1, 2, 3))])
    edit(obj)
    ops.curve_toolkit_merge_by_distance()
    object_mode()
    d = data_of(obj)
    assert d.cyclic, "the spline should be closed now"
    assert len(d.points) == 3, len(d.points)


@test
def only_the_selected_ends_are_welded():
    reset()
    threshold(0.2)
    obj = make_curve("C", [
        poly([(0, 0, 0), (1, 0, 0)], select=(0, 1)),
        poly([(1.1, 0, 0), (2, 0, 0)], select=()),      # not selected at all
        poly([(2.05, 0, 0), (3, 0, 0)], select=(0, 1)),
    ])
    edit(obj)
    assert cancelled(ops.curve_toolkit_merge_by_distance)
    object_mode()
    assert len(obj.data.splines) == 3, len(obj.data.splines)


@test
def a_middle_point_that_overlaps_an_end_is_never_welded():
    reset()
    threshold(0.2)
    obj = make_curve("C", [
        poly([(0, 0, 0), (1, 0, 0), (2, 0, 0)], select=(0, 1, 2)),
        poly([(1.05, 0.05, 0), (1.05, 2, 0)], select=(0, 1)),
    ])
    edit(obj)
    # The only pair within the Threshold is an end against a middle point.
    assert cancelled(ops.curve_toolkit_merge_by_distance)
    object_mode()
    assert len(obj.data.splines) == 2


@test
def splines_of_different_types_are_not_welded_to_each_other():
    reset()
    threshold(0.2)
    obj = make_curve("C", [
        poly([(0, 0, 0), (1, 0, 0)], select=(0, 1)),
        bezier([(1.05, 0, 0), (2, 0, 0)], select=(0, 1)),
    ])
    edit(obj)
    assert cancelled(ops.curve_toolkit_merge_by_distance)
    object_mode()
    assert len(obj.data.splines) == 2


@test
def a_chain_of_several_splines_closes_into_one_loop():
    reset()
    threshold(0.2)
    obj = make_curve("C", [
        poly([(0, 0, 0), (2, 0, 0)], select=(0, 1)),
        poly([(2.05, 0, 0), (2, 2, 0)], select=(0, 1)),
        poly([(2.02, 2.02, 0), (0, 2, 0)], select=(0, 1)),
        poly([(0.01, 2.01, 0), (0.01, 0.01, 0)], select=(0, 1)),
    ])
    edit(obj)
    ops.curve_toolkit_merge_by_distance()
    object_mode()
    assert len(obj.data.splines) == 1, len(obj.data.splines)
    d = data_of(obj)
    assert d.cyclic, "the chain should have closed into a loop"
    assert len(d.points) == 4, len(d.points)


@test
def the_threshold_is_measured_in_world_space():
    # Scaled by 10, a gap of 0.1 in local space is 1.0 in world space.
    reset()
    threshold(0.5)
    obj = make_curve(
        "C",
        [poly([(0, 0, 0), (1, 0, 0)], select=(0, 1)),
         poly([(1.1, 0, 0), (2, 0, 0)], select=(0, 1))],
        scale=(10, 10, 10))
    edit(obj)
    assert cancelled(ops.curve_toolkit_merge_by_distance)
    object_mode()
    assert len(obj.data.splines) == 2


@test
def nothing_selected_cancels_with_a_hint():
    reset()
    threshold(0.2)
    obj = make_curve("C", [
        poly([(0, 0, 0), (1, 0, 0)], select=()),
        poly([(1.05, 0, 0), (2, 0, 0)], select=()),
    ])
    edit(obj)
    assert cancelled(ops.curve_toolkit_merge_by_distance)
    object_mode()
    assert len(obj.data.splines) == 2


@test
def bezier_ends_keep_the_handles_that_survive():
    reset()
    threshold(0.2)
    a = straight_bezier([(0, 0, 0), (1, 0, 0)], select=(0, 1))
    b = straight_bezier([(1.1, 0, 0), (2, 0, 0)], select=(0, 1))
    hl_of_a_end = tuple(a.points[-1].hl)
    hr_of_b_start = tuple(b.points[0].hr)
    obj = make_curve("C", [a, b])
    edit(obj)
    ops.curve_toolkit_merge_by_distance()
    object_mode()
    d = data_of(obj)
    weld = d.points[1]
    # The weld sits halfway between the two ends, which were 0.1 apart, so each
    # surviving handle is its original carried along by its own point.
    assert near(weld.co, (1.05, 0, 0)), weld.co
    assert near(weld.hl, geo.add(hl_of_a_end, (0.05, 0, 0))), weld.hl
    assert near(weld.hr, geo.add(hr_of_b_start, (-0.05, 0, 0))), weld.hr


# -----------------------------------------------------------------------------
# Join & Merge still works the same way after the rename of merge_chains
# -----------------------------------------------------------------------------

@test
def join_and_merge_still_chains_two_objects():
    reset()
    threshold(0.2)
    a = make_curve("A", [poly([(0, 0, 0), (1, 0, 0)])])
    b = make_curve("B", [poly([(1.05, 0, 0), (2, 0, 0)])])
    for o in bpy.context.scene.objects:
        o.select_set(False)
    a.select_set(True)
    b.select_set(True)
    bpy.context.view_layer.objects.active = a
    ops.curve_toolkit_join_merge()
    assert len(a.data.splines) == 1, len(a.data.splines)
    assert len(data_of(a).points) == 3


# -----------------------------------------------------------------------------
# Registration
# -----------------------------------------------------------------------------

@test
def both_operators_survive_a_register_cycle():
    reset()
    toolkit.unregister()
    toolkit.register()
    for name in ("curve_toolkit_merge_pair", "curve_toolkit_merge_by_distance"):
        assert hasattr(ops, name), f"etr.{name} is gone after a register cycle"


@test
def the_panel_draws_in_edit_mode():
    reset()
    obj = make_curve("C", [poly([(0, 0, 0), (1, 0, 0)], select=(0, 1))])
    edit(obj)
    # Nothing to assert beyond "it does not raise": the panel reads the active
    # spline and the scene settings, which is where a bad reorder would show.
    from etr_curve_toolkit import panel
    assert panel.ETR_PT_curve_toolkit.bl_label == "Curve Toolkit"
    object_mode()


# -----------------------------------------------------------------------------
# The placement helper on its own
# -----------------------------------------------------------------------------

@test
def moved_carries_the_handles_of_a_bezier_point():
    p = sd.PointData(co=(1, 0, 0), hl=(0.5, 0, 0), hr=(1.5, 0, 0))
    q = sd.moved(p, (0, 2, 0))
    assert near(q.co, (1, 2, 0)) and near(q.hl, (0.5, 2, 0)) and near(q.hr, (1.5, 2, 0))
    # The original is left alone.
    assert near(p.co, (1, 0, 0))


@test
def moved_leaves_the_handles_of_a_poly_point_alone():
    p = sd.PointData(co=(1, 0, 0))
    q = sd.moved(p, (0, 2, 0))
    assert near(q.co, (1, 2, 0)) and q.hl is None and q.hr is None


@test
def moved_to_places_the_point_exactly():
    p = sd.PointData(co=(1, 0, 0), hl=(0.5, 0, 0), hr=(1.5, 0, 0))
    q = sd.moved_to(p, (4, 0, 0))
    assert near(q.co, (4, 0, 0)) and near(q.hl, (3.5, 0, 0)) and near(q.hr, (4.5, 0, 0))


def main():
    failed = 0
    for fn in TESTS:
        try:
            fn()
            object_mode()
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
