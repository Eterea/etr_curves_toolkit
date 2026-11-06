# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Tests of the Phase 11 tool of Curve Toolkit (Offset > Both Sides and Join Both
with Arcs), with Blender as a Python module:

    python test_phase11.py <folder that contains the etr_curves_toolkit package>

The geometry of the half-turns is checked against the exact circles they are
meant to be, in world space, so a tool that forgot the transform of the object
would fail.
"""

import math
import sys
import traceback

sys.path.insert(0, sys.argv[1])

import bpy  # noqa: E402

import etr_curves_toolkit as toolkit  # noqa: E402
from etr_curves_toolkit import curve_engine as eng  # noqa: E402
from etr_curves_toolkit import geometry as geo  # noqa: E402
from etr_curves_toolkit import offset_engine as off  # noqa: E402
from etr_curves_toolkit import spline_data as sd  # noqa: E402

toolkit.register()
ops = bpy.ops.etr

#: Handle length of a quarter of a circle of radius 1, as a cubic.
QUARTER = 4.0 / 3.0 * math.tan(math.pi / 8.0)

#: Largest error of a quarter circle approximated by one cubic, as a fraction
#: of the radius. The half-turns are two of those, so they stay under it.
ARC_ERROR = 3.0e-4


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if not hasattr(bpy.types.Scene, "etr_curves_toolkit"):
        toolkit.register()


def make_curve(name, splines, dims='2D', loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1)):
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


def quarter_arc(select=()):
    """A quarter of a circle of radius 1 (exact as a cubic), from (1, 0) to
    (0, 1), centred on the origin."""
    return bezier(
        [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], select=select,
        handles={
            0: ((1.0, -QUARTER, 0.0), (1.0, QUARTER, 0.0)),
            1: ((QUARTER, 1.0, 0.0), (-QUARTER, 1.0, 0.0)),
        },
    )


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


def result_of(source):
    """The 'Curve Offset' object the operator made out of `source`."""
    for obj in bpy.context.scene.objects:
        if obj is not source and obj.name.startswith("Curve Offset"):
            return obj
    raise AssertionError("no Curve Offset object was created")


def data_of(obj, index=0):
    return sd.read_spline(obj.data.splines[index])


def near(a, b, tol=1e-5):
    return geo.distance(a, b) <= tol


def cancelled(op, **kwargs):
    try:
        return op(**kwargs) == {'CANCELLED'}
    except RuntimeError:
        return True


def samples(data, steps=24):
    """Points along a spline snapshot, in its own local space."""
    return sd.flatten(data, steps=steps)


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# -----------------------------------------------------------------------------
# The half-turn on its own (pure geometry, no Blender)
# -----------------------------------------------------------------------------

@test
def a_half_turn_is_two_quarters_and_one_extra_point():
    tol = eng.tolerances_for([(0, 0), (1, 1)])
    arc = off._half_turn((0.0, 0.0), (0.0, 1.0), (0.0, -1.0), (1.0, 0.0), 1.0, tol)
    assert len(arc) == 2, f"{len(arc)} segments, expected two quarters"
    # It starts and ends where it was asked to, and passes through the far side.
    assert near(arc[0].p0 + (0.0,), (0.0, 1.0, 0.0)), arc[0].p0
    assert near(arc[-1].p1 + (0.0,), (0.0, -1.0, 0.0)), arc[-1].p1
    assert near(arc[0].p1 + (0.0,), (1.0, 0.0, 0.0)), arc[0].p1


@test
def every_point_of_a_half_turn_is_on_its_circle():
    tol = eng.tolerances_for([(0, 0), (1, 1)])
    arc = off._half_turn((0.0, 0.0), (0.0, 1.0), (0.0, -1.0), (1.0, 0.0), 1.0, tol)
    worst = max(abs(math.hypot(*s.pt(i / 32.0)) - 1.0)
                for s in arc for i in range(33))
    assert worst < ARC_ERROR, f"worst error {worst:.2e}"


@test
def a_half_turn_bulges_the_way_it_is_told_to():
    tol = eng.tolerances_for([(0, 0), (1, 1)])
    for outwards in ((1.0, 0.0), (-1.0, 0.0)):
        arc = off._half_turn((0.0, 0.0), (0.0, 1.0), (0.0, -1.0), outwards, 1.0, tol)
        middle = arc[0].p1
        assert middle[0] * outwards[0] > 0.9, (outwards, middle)


# -----------------------------------------------------------------------------
# close_both_sides on its own
# -----------------------------------------------------------------------------

def both_sides_loop(segs, d):
    tol = eng.tolerances_for(eng.segs_points(segs))
    return off.close_both_sides(
        segs,
        off.offset_path(segs, False, d, tol=tol),
        off.offset_path(segs, False, -d, tol=tol),
        d, tol), tol


@test
def the_loop_of_a_straight_line_is_a_stadium():
    line = [eng.line_seg((0.0, 0.0), (10.0, 0.0))]
    d = 1.0
    loop, _ = both_sides_loop(line, d)
    assert loop is not None
    # Two straight sides and two half-turns of two quarters each.
    assert len(loop) == 6, len(loop)
    worst = 0.0
    for s in loop:
        for i in range(33):
            x, y = s.pt(i / 32.0)
            worst = max(worst, min(
                abs(abs(y) - d) if 0.0 <= x <= 10.0 else 1e9,
                abs(math.hypot(x, y) - d),
                abs(math.hypot(x - 10.0, y) - d)))
    assert worst < ARC_ERROR * d, f"worst error {worst:.2e}"


@test
def the_loop_closes_exactly():
    line = [eng.line_seg((0.0, 0.0), (10.0, 0.0))]
    loop, _ = both_sides_loop(line, 1.0)
    assert eng._dist(loop[-1].p1, loop[0].p0) < 1e-12


@test
def the_loop_of_a_quarter_circle_is_two_arcs_and_two_caps():
    k = QUARTER
    arc = [eng.Seg((1.0, 0.0), (1.0, k), (k, 1.0), (0.0, 1.0))]
    d = 0.2
    loop, _ = both_sides_loop(arc, d)
    assert loop is not None
    worst = 0.0
    for s in loop:
        for i in range(33):
            x, y = s.pt(i / 32.0)
            worst = max(worst, min(
                abs(math.hypot(x, y) - (1.0 + d)),
                abs(math.hypot(x, y) - (1.0 - d)),
                abs(math.hypot(x - 1.0, y) - d),
                abs(math.hypot(x, y - 1.0) - d)))
    # The sides are fitted cubics, so the tolerance of the fit applies to them.
    assert worst < 2.0e-3 * d + 1.0e-3, f"worst error {worst:.2e}"


@test
def no_loop_when_the_distance_eats_an_end():
    # A hairpin: offset far enough to one side and the cleaning pass leaves
    # the ends somewhere else than the exact offset of the ends.
    segs = [
        eng.line_seg((0.0, 0.0), (10.0, 0.0)),
        eng.line_seg((10.0, 0.0), (10.0, 0.4)),
        eng.line_seg((10.0, 0.4), (0.0, 0.4)),
    ]
    loop, _ = both_sides_loop(segs, 1.0)
    assert loop is None, "the arcs should not have been built here"


# -----------------------------------------------------------------------------
# Both Sides in Object Mode
# -----------------------------------------------------------------------------

@test
def both_sides_makes_two_parallels_in_one_object():
    reset()
    src = make_curve("C", [poly([(0, 0, 0), (10, 0, 0)])])
    select_only(src)
    ops.curve_toolkit_offset(distance=1.0, both_sides=True, join_arcs=False)
    out = result_of(src)
    assert len(out.data.splines) == 2, len(out.data.splines)
    ys = sorted(round(data_of(out, i).points[0].co[1], 6) for i in range(2))
    assert ys == [-1.0, 1.0], ys
    # The original is left alone and visible.
    assert len(src.data.splines) == 1 and not src.hide_get()


@test
def the_sign_of_the_distance_does_not_matter_with_both_sides():
    shapes = {}
    for distance in (1.0, -1.0):
        reset()
        src = make_curve("C", [poly([(0, 0, 0), (10, 0, 0)])])
        select_only(src)
        ops.curve_toolkit_offset(distance=distance, both_sides=True, join_arcs=False)
        out = result_of(src)
        shapes[distance] = sorted(
            tuple(round(c, 6) for c in data_of(out, i).points[0].co) for i in range(2))
    assert shapes[1.0] == shapes[-1.0], shapes


@test
def join_arcs_gives_one_closed_spline():
    reset()
    src = make_curve("C", [poly([(0, 0, 0), (10, 0, 0)])])
    select_only(src)
    ops.curve_toolkit_offset(distance=1.0, both_sides=True, join_arcs=True)
    out = result_of(src)
    assert len(out.data.splines) == 1, len(out.data.splines)
    d = data_of(out)
    assert d.cyclic, "the result should be a closed curve"
    assert d.kind == 'BEZIER', d.kind
    # Two straight sides and two half-turns of two quarters each: six points.
    assert len(d.points) == 6, len(d.points)


@test
def the_arcs_are_exactly_round():
    reset()
    src = make_curve("C", [poly([(0, 0, 0), (10, 0, 0)])])
    select_only(src)
    ops.curve_toolkit_offset(distance=1.0, both_sides=True, join_arcs=True)
    out = result_of(src)
    worst = 0.0
    for x, y, _ in samples(data_of(out), steps=24):
        worst = max(worst, min(
            abs(abs(y) - 1.0) if 0.0 <= x <= 10.0 else 1e9,
            abs(math.hypot(x, y) - 1.0),
            abs(math.hypot(x - 10.0, y) - 1.0)))
    assert worst < ARC_ERROR, f"worst error {worst:.2e}"


@test
def a_poly_curve_becomes_bezier_only_when_the_arcs_are_added():
    reset()
    src = make_curve("C", [poly([(0, 0, 0), (10, 0, 0), (10, 5, 0)])])
    select_only(src)
    ops.curve_toolkit_offset(distance=0.5, both_sides=True, join_arcs=False,
                             corners='MITER')
    out = result_of(src)
    assert all(s.type == 'POLY' for s in out.data.splines), \
        [s.type for s in out.data.splines]

    reset()
    src = make_curve("C", [poly([(0, 0, 0), (10, 0, 0), (10, 5, 0)])])
    select_only(src)
    ops.curve_toolkit_offset(distance=0.5, both_sides=True, join_arcs=True,
                             corners='MITER')
    out = result_of(src)
    assert [s.type for s in out.data.splines] == ['BEZIER'], \
        [s.type for s in out.data.splines]


@test
def a_closed_curve_gets_two_parallels_and_no_arcs():
    reset()
    src = make_curve("C", [poly(
        [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)], cyclic=True)])
    select_only(src)
    ops.curve_toolkit_offset(distance=1.0, both_sides=True, join_arcs=True)
    out = result_of(src)
    assert len(out.data.splines) == 2, len(out.data.splines)
    assert all(s.use_cyclic_u for s in out.data.splines)
    # One outside the square and one inside it, so their sizes differ by 2 * d
    # on each axis.
    widths = sorted(
        max(p.co[0] for p in data_of(out, i).points)
        - min(p.co[0] for p in data_of(out, i).points) for i in range(2))
    assert abs(widths[0] - 8.0) < 1e-6 and abs(widths[1] - 12.0) < 1e-6, widths


@test
def a_bezier_curve_keeps_its_arcs_and_closes():
    reset()
    src = make_curve("C", [quarter_arc()])
    select_only(src)
    ops.curve_toolkit_offset(distance=0.2, both_sides=True, join_arcs=True)
    out = result_of(src)
    assert len(out.data.splines) == 1 and out.data.splines[0].use_cyclic_u
    worst = 0.0
    for x, y, _ in samples(data_of(out), steps=24):
        worst = max(worst, min(
            abs(math.hypot(x, y) - 1.2), abs(math.hypot(x, y) - 0.8),
            abs(math.hypot(x - 1.0, y) - 0.2), abs(math.hypot(x, y - 1.0) - 0.2)))
    assert worst < 2.0e-3, f"worst error {worst:.2e}"


@test
def both_sides_off_still_makes_a_single_parallel():
    reset()
    src = make_curve("C", [poly([(0, 0, 0), (10, 0, 0)])])
    select_only(src)
    ops.curve_toolkit_offset(distance=1.0)
    out = result_of(src)
    assert len(out.data.splines) == 1
    assert abs(data_of(out).points[0].co[1] - 1.0) < 1e-6


@test
def the_distance_is_measured_in_world_space():
    reset()
    src = make_curve("C", [poly([(0, 0, 0), (10, 0, 0)])], scale=(2, 2, 2))
    select_only(src)
    ops.curve_toolkit_offset(distance=1.0, both_sides=True, join_arcs=True)
    out = result_of(src)
    # In local space the half width has to be 0.5, so that it is 1.0 once the
    # object scale of 2 is applied.
    ys = [p.co[1] for p in data_of(out).points]
    assert abs(max(ys) - 0.5) < 1e-6 and abs(min(ys) + 0.5) < 1e-6, ys


@test
def several_curves_at_once_each_get_their_own_object():
    reset()
    a = make_curve("A", [poly([(0, 0, 0), (10, 0, 0)])])
    b = make_curve("B", [poly([(0, 20, 0), (10, 20, 0)])])
    for o in bpy.context.scene.objects:
        o.select_set(False)
    a.select_set(True)
    b.select_set(True)
    bpy.context.view_layer.objects.active = a
    ops.curve_toolkit_offset(distance=1.0, both_sides=True, join_arcs=True)
    made = [o for o in bpy.context.scene.objects if o.name.startswith("Curve Offset")]
    assert len(made) == 2, len(made)
    assert all(len(o.data.splines) == 1 and o.data.splines[0].use_cyclic_u for o in made)


# -----------------------------------------------------------------------------
# Both Sides in Edit Mode
# -----------------------------------------------------------------------------

@test
def edit_mode_puts_both_parallels_in_the_same_curve():
    reset()
    obj = make_curve("C", [poly([(0, 0, 0), (10, 0, 0)], select=(0, 1))])
    edit(obj)
    ops.curve_toolkit_offset(distance=1.0, both_sides=True, join_arcs=False)
    object_mode()
    assert len(obj.data.splines) == 3, len(obj.data.splines)   # original + two
    ys = sorted(round(data_of(obj, i).points[0].co[1], 6) for i in range(3))
    assert ys == [-1.0, 0.0, 1.0], ys


@test
def edit_mode_join_arcs_adds_one_closed_spline():
    reset()
    obj = make_curve("C", [poly([(0, 0, 0), (10, 0, 0)], select=(0, 1))])
    edit(obj)
    ops.curve_toolkit_offset(distance=1.0, both_sides=True, join_arcs=True)
    object_mode()
    assert len(obj.data.splines) == 2, len(obj.data.splines)
    assert not obj.data.splines[0].use_cyclic_u, "the original should stay open"
    assert obj.data.splines[1].use_cyclic_u, "the offset should be closed"
    assert len(data_of(obj, 1).points) == 6, len(data_of(obj, 1).points)


@test
def edit_mode_leaves_only_the_offset_selected():
    reset()
    obj = make_curve("C", [poly([(0, 0, 0), (10, 0, 0)], select=(0, 1))])
    edit(obj)
    ops.curve_toolkit_offset(distance=1.0, both_sides=True, join_arcs=True)
    object_mode()
    assert not any(p.select for p in data_of(obj, 0).points)
    assert all(p.select for p in data_of(obj, 1).points)


@test
def edit_mode_only_touches_the_selected_splines():
    reset()
    obj = make_curve("C", [
        poly([(0, 0, 0), (10, 0, 0)], select=(0, 1)),
        poly([(0, 20, 0), (10, 20, 0)], select=()),
    ])
    edit(obj)
    ops.curve_toolkit_offset(distance=1.0, both_sides=True, join_arcs=True)
    object_mode()
    assert len(obj.data.splines) == 3, len(obj.data.splines)
    assert sum(1 for s in obj.data.splines if s.use_cyclic_u) == 1


# -----------------------------------------------------------------------------
# The fallback when the arcs cannot be built
# -----------------------------------------------------------------------------

@test
def an_eaten_end_falls_back_to_the_two_parallels():
    reset()
    # A hairpin whose two sides are closer than the Distance: the cleaning
    # pass cuts the offset, and there is nothing left for the arcs to close.
    obj = make_curve("C", [poly([(0, 0, 0), (10, 0, 0), (10, 0.4, 0), (0, 0.4, 0)])])
    select_only(obj)
    ops.curve_toolkit_offset(distance=1.0, both_sides=True, join_arcs=True)
    out = result_of(obj)
    assert not any(s.use_cyclic_u for s in out.data.splines), \
        "no closed loop should have been built here"
    assert len(out.data.splines) >= 1, len(out.data.splines)


@test
def a_distance_of_zero_is_still_refused():
    reset()
    obj = make_curve("C", [poly([(0, 0, 0), (10, 0, 0)])])
    select_only(obj)
    assert cancelled(ops.curve_toolkit_offset, distance=0.0,
                     both_sides=True, join_arcs=True)


@test
def nurbs_are_still_refused():
    reset()
    curve = bpy.data.curves.new("C", 'CURVE')
    curve.dimensions = '2D'
    spline = curve.splines.new('NURBS')
    spline.points.add(2)
    for p, co in zip(spline.points, ((0, 0, 0, 1), (5, 5, 0, 1), (10, 0, 0, 1))):
        p.co = co
    obj = bpy.data.objects.new("C", curve)
    bpy.context.scene.collection.objects.link(obj)
    select_only(obj)
    assert cancelled(ops.curve_toolkit_offset, distance=1.0,
                     both_sides=True, join_arcs=True)


# -----------------------------------------------------------------------------
# Registration and the redo panel
# -----------------------------------------------------------------------------

@test
def the_operator_has_the_two_new_properties():
    props = ops.curve_toolkit_offset.get_rna_type().properties
    for name in ("both_sides", "join_arcs"):
        assert name in props, f"{name} is missing from the operator"
        assert props[name].default is False, f"{name} should default to off"


@test
def offset_survives_a_register_cycle():
    reset()
    toolkit.unregister()
    toolkit.register()
    assert hasattr(ops, "curve_toolkit_offset")


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
