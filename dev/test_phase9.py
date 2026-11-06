# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Tests of the Phase 9 tools of Curve Toolkit (Arcs to Corners, Remove Strays and
Set Resolution), with Blender as a Python module:

    python test_phase9.py <folder that contains the etr_curves_toolkit package>

Every test builds its own curves from scratch. Lengths are checked in world
space, so a tool that forgot the transform of the object would fail.
"""

import math
import sys
import traceback

sys.path.insert(0, sys.argv[1])

import bpy  # noqa: E402

import etr_curves_toolkit as toolkit  # noqa: E402
from etr_curves_toolkit import arcs_to_corners as a2c  # noqa: E402
from etr_curves_toolkit import geometry as geo  # noqa: E402
from etr_curves_toolkit import context_utils as cu  # noqa: E402
from etr_curves_toolkit import panel  # noqa: E402
from etr_curves_toolkit import spline_data as sd  # noqa: E402

toolkit.register()
ops = bpy.ops.etr

#: Handle length of a quarter of a circle of radius 1, as a cubic.
QUARTER = 4.0 / 3.0 * math.tan(math.pi / 8.0)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if not hasattr(bpy.types.Scene, "etr_curves_toolkit"):
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


def quarter_arc(select=(0, 1)):
    """A quarter of a circle of radius 1 (exact as a cubic), from (1, 0) to
    (0, 1). Its handles meet at (1, 1): the corner it was rounded from."""
    return bezier(
        [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], select=select,
        handles={
            0: ((1.0, -QUARTER, 0.0), (1.0, QUARTER, 0.0)),
            1: ((QUARTER, 1.0, 0.0), (-QUARTER, 1.0, 0.0)),
        },
    )


def rounded_rectangle(radius=0.25, select=()):
    """Closed Bezier rectangle of 2 x 1 with the four corners rounded by exact
    quarter arcs: eight points, four arcs and four straight sides. The corners
    it was rounded from are (+-1, +-0.5)."""
    r, h = radius, radius * QUARTER
    pts, handles = [], {}
    corners = ((1.0, 0.5), (-1.0, 0.5), (-1.0, -0.5), (1.0, -0.5))
    # Each corner contributes the end of the arc that comes in and the start
    # of the one that goes out, walking the rectangle counter-clockwise.
    arrivals = ((1.0 - r, 0.5), (-1.0, 0.5 - r), (-1.0 + r, -0.5), (1.0, -0.5 + r))
    exits = ((-1.0 + r, 0.5), (-1.0, -0.5 + r), (1.0 - r, -0.5), (1.0, 0.5 - r))
    order = []
    for k, (cx, cy) in enumerate(corners):
        after = exits[k - 1]            # point where the arc of this corner starts
        before = arrivals[k]            # point where it ends
        order.append((after, before, (cx, cy)))
    for start, end, (cx, cy) in order:
        i = len(pts)
        # Tangent of the arc at `start` points at the corner, and at `end` away
        # from it, each handle h long.
        to_corner = geo.normalized(geo.sub((cx, cy, 0.0), (start[0], start[1], 0.0)))
        from_corner = geo.normalized(geo.sub((end[0], end[1], 0.0), (cx, cy, 0.0)))
        s = (start[0], start[1], 0.0)
        e = (end[0], end[1], 0.0)
        pts += [s, e]
        handles[i] = (geo.sub(s, geo.mul(to_corner, h)), geo.add(s, geo.mul(to_corner, h)))
        handles[i + 1] = (geo.sub(e, geo.mul(from_corner, h)),
                          geo.add(e, geo.mul(from_corner, h)))
    return bezier(pts, cyclic=True, select=select, handles=handles)


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


def sampled(data, a, b, steps=16):
    """Points of the segment from index a to b of a Bezier spline."""
    pa, pb = data.points[a], data.points[b]
    return [geo.bezier_point(pa.co, pa.hr, pb.hl, pb.co, s / steps)
            for s in range(steps + 1)]


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# -----------------------------------------------------------------------------
# Arcs to Corners: the geometry on its own
# -----------------------------------------------------------------------------

@test
def corner_of_a_quarter_arc_is_the_square_corner():
    arc = quarter_arc()
    a, b = arc.points
    co = a2c.corner_point(a.co, a.hr, b.hl, b.co)
    assert co is not None and near(co, (1.0, 1.0, 0.0)), co


@test
def corner_of_a_shallow_and_of_a_wide_arc():
    # An arc of angle t has its corner at tan(t/2) from each end, on the
    # tangent lines; both ends are checked against that distance.
    for angle in (math.radians(10.0), math.radians(90.0), math.radians(170.0)):
        half = angle * 0.5
        h = 4.0 / 3.0 * math.tan(angle * 0.25)
        a_co = (math.cos(half), -math.sin(half), 0.0)
        b_co = (math.cos(half), math.sin(half), 0.0)
        a_hr = geo.add(a_co, geo.mul((math.sin(half), math.cos(half), 0.0), h))
        b_hl = geo.add(b_co, geo.mul((-math.sin(half), math.cos(half), 0.0), -h))
        # Hmm: the incoming handle of b points back along the tangent at b.
        b_hl = geo.sub(b_co, geo.mul((math.sin(half), -math.cos(half), 0.0), -h))
        co = a2c.corner_point(a_co, a_hr, b_hl, b_co)
        assert co is not None, f"no corner at {math.degrees(angle)} degrees"
        expected = 1.0 / math.cos(half)      # the corner of the tangent lines
        assert abs(geo.length(co) - expected) < 1e-6 * max(1.0, expected), (
            math.degrees(angle), co, expected)


@test
def a_straight_segment_is_left_alone():
    assert a2c.corner_point(
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 0.0, 0.0)) is None


@test
def parallel_handles_are_left_alone():
    # A half turn: both handles leave in the same direction and never meet.
    assert a2c.corner_point(
        (0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (2.0, 1.0, 0.0), (2.0, 0.0, 0.0)) is None


@test
def handles_meeting_behind_are_left_alone():
    # The lines do cross at (2, 0), but behind the handle of the first point.
    assert a2c.corner_point(
        (0.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (2.0, 1.0, 0.0), (2.0, 2.0, 0.0)) is None


@test
def a_very_shallow_arc_still_gives_its_corner():
    # A corner of 179.8 degrees rounded away leaves an almost straight
    # segment, and its corner is a hair off the line, right in the middle.
    tiny = math.tan(math.radians(0.1))
    co = a2c.corner_point(
        (0.0, 0.0, 0.0), (1.0, tiny, 0.0), (2.0, tiny, 0.0), (3.0, 0.0, 0.0))
    assert co is not None and near(co, (1.5, 1.5 * tiny, 0.0)), co


@test
def an_almost_half_turn_is_left_alone():
    # An arc of 179.9 degrees: the handles are nearly parallel and their
    # meeting point is more than five hundred chords away, far past the reach
    # the tool accepts.
    angle = math.radians(179.9)
    half = angle * 0.5
    h = 4.0 / 3.0 * math.tan(angle * 0.25)
    a_co = (math.cos(half), -math.sin(half), 0.0)
    b_co = (math.cos(half), math.sin(half), 0.0)
    a_hr = geo.add(a_co, geo.mul((math.sin(half), math.cos(half), 0.0), h))
    b_hl = geo.add(b_co, geo.mul((math.sin(half), -math.cos(half), 0.0), h))
    assert a2c.corner_point(a_co, a_hr, b_hl, b_co) is None


@test
def handles_that_would_meet_very_far_are_left_alone():
    # Two handles a thousandth of a degree from parallel: they do cross, a
    # thousand chords away, which is no corner of this segment.
    a = math.tan(math.radians(0.001))
    assert a2c.corner_point(
        (0.0, 0.0, 0.0), (1.0, -a, 0.0),
        (2.0, a * 1.001, 0.0), (3.0, 0.0, 0.0)) is None


@test
def skew_handles_in_3d_are_left_alone():
    # The handle of the first point runs along X, the one of the second along
    # Z, two units apart: they never meet.
    assert a2c.corner_point(
        (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 2.0, 1.0), (2.0, 2.0, 0.0)) is None


@test
def a_flat_segment_is_solved_in_its_own_plane():
    # Quarter arc of the XY plane, turned 30 degrees around X and 20 around Y,
    # so neither the plane nor the corner is axis-aligned.
    from mathutils import Euler, Vector
    rot = Euler((math.radians(30.0), math.radians(20.0), 0.0)).to_matrix()
    turn = lambda p: tuple(rot @ Vector(p))
    arc = quarter_arc()
    a, b = arc.points
    co = a2c.corner_point(turn(a.co), turn(a.hr), turn(b.hl), turn(b.co))
    assert co is not None and near(co, turn((1.0, 1.0, 0.0))), co


# -----------------------------------------------------------------------------
# Arcs to Corners: the operator
# -----------------------------------------------------------------------------

@test
def a_rounded_corner_comes_back():
    reset()
    obj = make_curve("c", [quarter_arc(select=(0, 1))])
    edit(obj)
    assert ops.curve_toolkit_arcs_to_corners() == {'FINISHED'}
    object_mode()
    d = data_of(obj)
    assert len(d.points) == 3, len(d.points)
    a, corner, b = d.points
    assert near(corner.co, (1.0, 1.0, 0.0)), corner.co
    # Both sides of the corner are straight lines.
    assert geo.is_straight_segment(a.co, a.hr, corner.hl, corner.co)
    assert geo.is_straight_segment(corner.co, corner.hr, b.hl, b.co)
    # The ends of the arc have not moved, and the outer handles are untouched.
    assert near(a.co, (1.0, 0.0, 0.0)) and near(b.co, (0.0, 1.0, 0.0))
    assert near(a.hl, (1.0, -QUARTER, 0.0)) and near(b.hr, (-QUARTER, 1.0, 0.0))


@test
def the_corner_has_vector_handles_and_the_others_are_not_auto():
    reset()
    obj = make_curve("c", [quarter_arc(select=(0, 1))])
    edit(obj)
    ops.curve_toolkit_arcs_to_corners()
    object_mode()
    a, corner, b = data_of(obj).points
    assert (corner.hlt, corner.hrt) == ('VECTOR', 'VECTOR'), (corner.hlt, corner.hrt)
    assert a.hrt in {'FREE', 'VECTOR'} and b.hlt in {'FREE', 'VECTOR'}
    assert a.hrt != 'AUTO' and b.hlt != 'AUTO'


@test
def the_originals_stay_selected_and_the_corner_does_not():
    reset()
    obj = make_curve("c", [quarter_arc(select=(0, 1))])
    edit(obj)
    ops.curve_toolkit_arcs_to_corners()
    object_mode()
    a, corner, b = data_of(obj).points
    for p in (a, b):
        assert p.select and p.select_left and p.select_right
    assert not (corner.select or corner.select_left or corner.select_right)


@test
def a_point_that_was_not_part_of_a_pair_is_deselected():
    # Three points: the pair 0-1 is an arc and 2 hangs behind, selected. The
    # selection left behind has to name only the points of the new corner, so
    # that a Dissolve right after takes those and nothing else.
    reset()
    arc = quarter_arc(select=(0, 1))
    arc.points.append(sd.PointData(
        co=(-1.0, 1.0, 0.0), hl=(-0.8, 1.0, 0.0), hr=(-1.2, 1.0, 0.0),
        hlt='FREE', hrt='FREE', select=True, select_left=True, select_right=True))
    obj = make_curve("c", [arc])
    edit(obj)
    ops.curve_toolkit_arcs_to_corners()
    object_mode()
    d = data_of(obj)
    assert len(d.points) == 4, len(d.points)
    assert [p.select for p in d.points] == [True, False, True, False]


@test
def every_corner_of_a_rounded_rectangle_comes_back():
    reset()
    obj = make_curve("c", [rounded_rectangle(select=tuple(range(8)))])
    edit(obj)
    assert ops.curve_toolkit_arcs_to_corners() == {'FINISHED'}
    object_mode()
    d = data_of(obj)
    assert len(d.points) == 12, len(d.points)      # 8 originals + 4 corners
    corners = [p.co for p in d.points if not p.select]
    assert len(corners) == 4, corners
    expected = {(1.0, 0.5), (-1.0, 0.5), (-1.0, -0.5), (1.0, -0.5)}
    for co in corners:
        assert any(near(co, (x, y, 0.0)) for x, y in expected), co
    assert d.cyclic


@test
def a_corner_on_the_closing_segment_of_a_cyclic_spline():
    # Cyclic spline whose arc is the segment from the last point to the first.
    reset()
    arc = quarter_arc(select=())
    arc.cyclic = True
    arc.points = [arc.points[1], arc.points[0]]    # the arc closes the spline
    arc.points[0].select = arc.points[1].select = True
    obj = make_curve("c", [arc])
    edit(obj)
    assert ops.curve_toolkit_arcs_to_corners() == {'FINISHED'}
    object_mode()
    d = data_of(obj)
    assert len(d.points) == 3 and d.cyclic
    assert near(d.points[2].co, (1.0, 1.0, 0.0)), d.points[2].co


@test
def auto_handles_of_the_pair_are_pinned():
    # Four points with Auto handles: the pair in the middle gets a corner, and
    # the two segments around it have to keep their shape, which they would
    # not if Blender recomputed the Auto handles from the new neighbour.
    reset()
    # Four points on the unit circle, 45 degrees apart: the Auto handles come
    # out tangent to it, so the middle segment is an arc with a real corner.
    ring = [(math.cos(math.radians(k * 45.0)), math.sin(math.radians(k * 45.0)), 0.0)
            for k in range(4)]
    spline = bezier(ring, select=(1, 2), types=('AUTO', 'AUTO'))
    obj = make_curve("c", [spline])
    before = data_of(obj)                          # the Auto handles Blender made
    first = sampled(before, 0, 1)
    last = sampled(before, 2, 3)
    edit(obj)
    assert ops.curve_toolkit_arcs_to_corners() == {'FINISHED'}
    object_mode()
    after = data_of(obj)
    assert len(after.points) == 5, len(after.points)
    for got, want in zip(sampled(after, 0, 1), first):
        assert near(got, want, 1e-5), (got, want)
    for got, want in zip(sampled(after, 3, 4), last):
        assert near(got, want, 1e-5), (got, want)
    for p in (after.points[1], after.points[3]):
        assert p.hlt != 'AUTO' and p.hrt != 'AUTO', (p.hlt, p.hrt)


@test
def aligned_handles_keep_the_segments_around_the_corner():
    # The outer handles of the pair stay Aligned, and the inner ones become
    # Free: the direction of the inner handle does not change, so Blender has
    # nothing to re-align and the previous and next segments keep their shape.
    reset()
    ring = [(math.cos(math.radians(k * 45.0)), math.sin(math.radians(k * 45.0)), 0.0)
            for k in range(4)]
    spline = bezier(ring, select=(1, 2), types=('AUTO', 'AUTO'))
    obj = make_curve("c", [spline])
    data = data_of(obj)                            # the Auto handles Blender made
    for p in data.points:
        p.hlt = p.hrt = 'ALIGNED'
    obj.data.splines.clear()
    sd.write_spline(obj.data, data)
    before = data_of(obj)
    first, last = sampled(before, 0, 1), sampled(before, 2, 3)
    edit(obj)
    assert ops.curve_toolkit_arcs_to_corners() == {'FINISHED'}
    object_mode()
    after = data_of(obj)
    assert len(after.points) == 5, len(after.points)
    for got, want in zip(sampled(after, 0, 1), first):
        assert near(got, want, 1e-5), (got, want)
    for got, want in zip(sampled(after, 3, 4), last):
        assert near(got, want, 1e-5), (got, want)
    assert geo.is_straight_segment(
        after.points[1].co, after.points[1].hr,
        after.points[2].hl, after.points[2].co)


@test
def dissolve_originals_leaves_only_the_corner():
    reset()
    spline = bezier(
        [(-2.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (-2.0, 3.0, 0.0)],
        select=(1, 2),
        handles={
            0: ((-2.2, 0.0, 0.0), (-1.8, 0.0, 0.0)),
            1: ((1.0, -QUARTER, 0.0), (1.0, QUARTER, 0.0)),
            2: ((QUARTER, 1.0, 0.0), (-QUARTER, 1.0, 0.0)),
            3: ((-1.8, 2.8, 0.0), (-2.2, 3.2, 0.0)),
        },
    )
    obj = make_curve("c", [spline])
    edit(obj)
    assert ops.curve_toolkit_arcs_to_corners(dissolve_originals=True) == {'FINISHED'}
    object_mode()
    d = data_of(obj)
    assert len(d.points) == 3, [p.co for p in d.points]
    assert near(d.points[1].co, (1.0, 1.0, 0.0)), d.points[1].co


@test
def round_corners_and_back_again():
    # The round trip the tool is for: Round Corners leaves its two new points
    # selected, so Arcs to Corners can be pressed right after, and with Dissolve
    # Originals the square is exactly the one it started as.
    reset()
    obj = make_curve("c", [poly(
        [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], cyclic=True, select=(2,))])
    edit(obj)
    assert ops.curve_toolkit_round_corners(radius=0.4) == {'FINISHED'}
    assert ops.curve_toolkit_arcs_to_corners(dissolve_originals=True) == {'FINISHED'}
    object_mode()
    d = data_of(obj)
    assert len(d.points) == 4, [p.co for p in d.points]
    for p, want in zip(d.points, [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)]):
        assert near(p.co, want), (p.co, want)


@test
def a_straight_corner_of_a_square_is_left_alone():
    # Two consecutive points of a straight-sided Bezier square: nothing to
    # bring back, and the operator says so instead of inventing a point.
    reset()
    spline = bezier(
        [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (2.0, 2.0, 0.0)], select=(0, 1),
        handles={
            0: ((-0.7, 0.0, 0.0), (0.7, 0.0, 0.0)),
            1: ((1.3, 0.0, 0.0), (2.0, 0.0, 0.0)),
            2: ((2.0, 1.3, 0.0), (2.0, 2.7, 0.0)),
        },
    )
    obj = make_curve("c", [spline])
    edit(obj)
    assert cancelled(ops.curve_toolkit_arcs_to_corners)
    object_mode()
    assert len(data_of(obj).points) == 3


@test
def a_single_selected_point_does_nothing():
    reset()
    obj = make_curve("c", [quarter_arc(select=(0,))])
    edit(obj)
    assert cancelled(ops.curve_toolkit_arcs_to_corners)
    object_mode()
    assert len(data_of(obj).points) == 2


@test
def poly_and_nurbs_splines_are_left_alone():
    reset()
    obj = make_curve("c", [poly([(0, 0, 0), (1, 0, 0), (1, 1, 0)], select=(0, 1))])
    edit(obj)
    assert cancelled(ops.curve_toolkit_arcs_to_corners)
    object_mode()
    d = data_of(obj)
    assert d.kind == 'POLY' and len(d.points) == 3


@test
def the_transform_of_the_object_does_not_matter():
    # The corner is built in the local space of the curve, so a moved, turned
    # and scaled object gives the same local result.
    reset()
    obj = make_curve("c", [quarter_arc(select=(0, 1))],
                     loc=(5.0, -3.0, 2.0), rot=(0.4, 0.2, 1.1), scale=(2.0, 3.0, 0.5))
    edit(obj)
    ops.curve_toolkit_arcs_to_corners()
    object_mode()
    d = data_of(obj)
    assert len(d.points) == 3 and near(d.points[1].co, (1.0, 1.0, 0.0)), d.points[1].co


# -----------------------------------------------------------------------------
# Remove Strays
# -----------------------------------------------------------------------------

def strays_scene(threshold=0.001, scale=(1, 1, 1)):
    """A curve with a good square, a single-point spline and a tiny one."""
    reset()
    bpy.context.scene.etr_curves_toolkit.merge_threshold = threshold
    good = poly([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], cyclic=True)
    alone = poly([(3, 0, 0)])
    tiny = poly([(5, 0, 0), (5.0002, 0, 0)])
    return make_curve("c", [good, alone, tiny], scale=scale)


@test
def a_single_point_and_a_tiny_spline_go_away():
    obj = strays_scene()
    select_only(obj)
    assert ops.curve_toolkit_remove_strays() == {'FINISHED'}
    assert len(obj.data.splines) == 1
    assert len(obj.data.splines[0].points) == 4


@test
def remove_strays_follows_the_threshold():
    obj = strays_scene(threshold=0.0001)
    select_only(obj)
    ops.curve_toolkit_remove_strays()
    # The tiny spline is 0.2 mm long, longer than the threshold now, so only
    # the single-point one goes.
    assert len(obj.data.splines) == 2, len(obj.data.splines)


@test
def remove_strays_measures_in_world_space():
    # The same tiny spline inside an object scaled by 100 is 2 cm long in the
    # world, so it is not a stray any more.
    obj = strays_scene(scale=(100.0, 100.0, 100.0))
    select_only(obj)
    ops.curve_toolkit_remove_strays()
    assert len(obj.data.splines) == 2, len(obj.data.splines)


@test
def remove_strays_in_edit_mode_looks_at_every_spline():
    obj = strays_scene()
    edit(obj)
    bpy.ops.curve.select_all(action='DESELECT')
    assert ops.curve_toolkit_remove_strays() == {'FINISHED'}
    object_mode()
    assert len(obj.data.splines) == 1


@test
def a_curve_of_only_strays_is_left_empty():
    reset()
    bpy.context.scene.etr_curves_toolkit.merge_threshold = 0.001
    obj = make_curve("c", [poly([(0, 0, 0)]), poly([(2, 0, 0), (2.0001, 0, 0)])])
    select_only(obj)
    assert ops.curve_toolkit_remove_strays() == {'FINISHED'}
    assert len(obj.data.splines) == 0


@test
def remove_strays_cancels_when_there_is_nothing_to_remove():
    reset()
    obj = make_curve("c", [poly([(0, 0, 0), (1, 0, 0)])])
    select_only(obj)
    assert cancelled(ops.curve_toolkit_remove_strays)
    assert len(obj.data.splines) == 1


@test
def remove_strays_keeps_the_good_splines_untouched():
    obj = strays_scene()
    before = [tuple(p.co) for p in data_of(obj).points]
    select_only(obj)
    ops.curve_toolkit_remove_strays()
    after = [tuple(p.co) for p in data_of(obj).points]
    assert before == after


# -----------------------------------------------------------------------------
# Set Resolution
# -----------------------------------------------------------------------------

@test
def set_resolution_in_object_mode_reaches_every_spline():
    reset()
    obj = make_curve("c", [poly([(0, 0, 0), (1, 0, 0)]), poly([(0, 2, 0), (1, 2, 0)])])
    select_only(obj)
    assert ops.curve_toolkit_set_resolution(resolution=6) == {'FINISHED'}
    assert [s.resolution_u for s in obj.data.splines] == [6, 6]
    assert obj.data.resolution_u == 6


@test
def set_resolution_in_object_mode_reaches_every_selected_curve():
    reset()
    first = make_curve("a", [poly([(0, 0, 0), (1, 0, 0)])])
    second = make_curve("b", [poly([(0, 2, 0), (1, 2, 0)])])
    for o in (first, second):
        o.select_set(True)
    bpy.context.view_layer.objects.active = second
    ops.curve_toolkit_set_resolution(resolution=24)
    assert first.data.splines[0].resolution_u == 24
    assert second.data.splines[0].resolution_u == 24


@test
def set_resolution_in_edit_mode_only_touches_selected_splines():
    reset()
    obj = make_curve("c", [
        poly([(0, 0, 0), (1, 0, 0)], select=(0,)),
        poly([(0, 2, 0), (1, 2, 0)]),
    ])
    edit(obj)
    assert ops.curve_toolkit_set_resolution(resolution=3) == {'FINISHED'}
    object_mode()
    assert [s.resolution_u for s in obj.data.splines] == [3, 12]
    # The curve data keeps its own value in Edit Mode.
    assert obj.data.resolution_u == 12


@test
def set_resolution_cancels_in_edit_mode_without_a_selection():
    reset()
    obj = make_curve("c", [poly([(0, 0, 0), (1, 0, 0)])])
    edit(obj)
    bpy.ops.curve.select_all(action='DESELECT')
    assert cancelled(ops.curve_toolkit_set_resolution, resolution=5)
    object_mode()
    assert obj.data.splines[0].resolution_u == 12


@test
def a_selected_handle_is_enough_in_edit_mode():
    reset()
    spline = quarter_arc(select=())
    spline.points[0].select_right = True
    obj = make_curve("c", [spline, poly([(0, 5, 0), (1, 5, 0)])])
    edit(obj)
    ops.curve_toolkit_set_resolution(resolution=8)
    object_mode()
    assert [s.resolution_u for s in obj.data.splines] == [8, 12]


@test
def the_panel_field_reads_the_right_resolution():
    reset()
    obj = make_curve("c", [poly([(0, 0, 0), (1, 0, 0)]), poly([(0, 2, 0), (1, 2, 0)])])
    obj.data.splines[1].resolution_u = 9
    select_only(obj)
    assert cu.resolution_source(bpy.context) is obj.data
    edit(obj)
    obj.data.splines.active = obj.data.splines[1]
    source = cu.resolution_source(bpy.context)
    assert source is not None and source.resolution_u == 9, source
    object_mode()


@test
def the_panel_field_falls_back_to_the_curve_data():
    # With no spline made active in Edit Mode there is nothing to talk about
    # per spline, so the field shows the value of the curve, which is the 12
    # of a new curve and not whatever the first spline happens to hold.
    reset()
    obj = make_curve("c", [poly([(0, 0, 0), (1, 0, 0)])])
    obj.data.splines[0].resolution_u = 3
    edit(obj)
    obj.data.splines.active = None
    source = cu.resolution_source(bpy.context)
    assert source is obj.data and source.resolution_u == 12, source
    object_mode()


@test
def the_panel_shows_nothing_without_a_curve():
    reset()
    bpy.ops.mesh.primitive_cube_add()
    assert cu.resolution_source(bpy.context) is None


@test
def the_resolution_field_resets_to_twelve():
    # What Backspace over the field gives, and the reason the field is a
    # property of the kit instead of Spline.resolution_u, whose own default
    # comes back as 0 and lands on 1.
    reset()
    prop = bpy.context.scene.etr_curves_toolkit.bl_rna.properties["resolution"]
    assert prop.default == 12, prop.default
    assert bpy.types.Spline.bl_rna.properties["resolution_u"].default == 0
    assert bpy.types.Curve.bl_rna.properties["resolution_u"].default == 12


@test
def the_resolution_field_writes_where_it_reads():
    reset()
    obj = make_curve("c", [poly([(0, 0, 0), (1, 0, 0)]), poly([(0, 2, 0), (1, 2, 0)])])
    settings = bpy.context.scene.etr_curves_toolkit
    select_only(obj)
    assert settings.resolution == 12
    # Object Mode: the curve itself, which Blender passes on to every spline.
    settings.resolution = 7
    assert obj.data.resolution_u == 7
    assert [s.resolution_u for s in obj.data.splines] == [7, 7]
    # Edit Mode with an active spline: only that one.
    edit(obj)
    obj.data.splines.active = obj.data.splines[1]
    assert settings.resolution == 7
    settings.resolution = 4
    assert [s.resolution_u for s in obj.data.splines] == [7, 4]
    assert obj.data.resolution_u == 7
    object_mode()


@test
def the_resolution_field_holds_up_without_a_curve():
    reset()
    bpy.ops.mesh.primitive_cube_add()
    settings = bpy.context.scene.etr_curves_toolkit
    assert settings.resolution == 12
    settings.resolution = 5          # nowhere to write it: no error either
    assert settings.resolution == 12


# -----------------------------------------------------------------------------
# Panel and registration
# -----------------------------------------------------------------------------

@test
def the_panel_draws_the_new_tools():
    from unittest import mock

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
        if (call[0].endswith("operator") or call[0].endswith("operator_menu_enum")) and call[1]:
            idnames.add(call[1][0])
    for idname in ("etr.curve_toolkit_arcs_to_corners",
                   "etr.curve_toolkit_select_by_type",
                   "etr.curve_toolkit_set_resolution"):
        assert idname in idnames, f"{idname} is not drawn by the panel"
        module, name = idname.split(".")
        assert hasattr(getattr(bpy.ops, module), name), f"{idname} does not exist"

    # icon_id is only assigned when a UI exists, so check the preview itself.
    assert "corner" in panel._icons, "the corner icon is not loaded"
    assert tuple(panel._icons["corner"].icon_size) == (32, 32)


@test
def register_unregister_cycle():
    toolkit.unregister()
    toolkit.register()
    for name in ("curve_toolkit_arcs_to_corners", "curve_toolkit_remove_strays",
                 "curve_toolkit_set_resolution"):
        assert hasattr(ops, name), f"etr.{name} is gone after a register cycle"


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
