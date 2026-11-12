# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Tests of the Phase 12 tool of Curve Toolkit (Slide Point), with Blender as a
Python module:

    python test_phase12.py <folder that contains the etr_curves_toolkit package>

The shape is checked by sampling the curve before and after and measuring how
far the new one strays from the old one, which is the only thing this tool
promises. Note that `INVOKE_DEFAULT` does not reach invoke() in background
mode, so the tests always pass the factor themselves; the reading of the
current position is checked through current_factor() instead.
"""

import math
import sys
import traceback

sys.path.insert(0, sys.argv[1])

import bpy  # noqa: E402

import etr_curves_toolkit as toolkit  # noqa: E402
from etr_curves_toolkit import geometry as geo  # noqa: E402
from etr_curves_toolkit import slide as sl  # noqa: E402
from etr_curves_toolkit import spline_data as sd  # noqa: E402

toolkit.register()
ops = bpy.ops.etr

#: Handle length of a quarter of a circle of radius 1, as a cubic.
QUARTER = 4.0 / 3.0 * math.tan(math.pi / 8.0)

#: Sampling error of the shape comparison below, relative to the span. A curve
#: that did not move at all still measures this much.
NOISE = 1.0e-4


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if not hasattr(bpy.types.Scene, "etr_curves_toolkit"):
        toolkit.register()


def bezier(points, handles, cyclic=False, select=(), types=('FREE', 'FREE')):
    pts = []
    for i, (co, (hl, hr)) in enumerate(zip(points, handles)):
        pts.append(sd.PointData(
            co=tuple(co), hl=tuple(hl), hr=tuple(hr), hlt=types[0], hrt=types[1],
            select=(i in select), select_left=(i in select),
            select_right=(i in select)))
    return sd.SplineData('BEZIER', pts, cyclic, {"resolution_u": 12})


def smooth(points, cyclic=False, select=(), tension=1.0 / 3.0, types=('FREE', 'FREE')):
    """Bezier spline whose handles point along the chord between the two
    neighbours of each point, so every point is smooth (not a corner)."""
    n = len(points)
    handles = []
    for i, p in enumerate(points):
        before = points[i - 1] if (i or cyclic) else p
        after = points[(i + 1) % n] if (i < n - 1 or cyclic) else p
        direction = geo.normalized(geo.sub(after, before)) or (1.0, 0.0, 0.0)
        reach = tension * geo.distance(before, after)
        handles.append((geo.sub(p, geo.mul(direction, reach)),
                        geo.add(p, geo.mul(direction, reach))))
    return bezier(points, handles, cyclic, select, types)


def subdivided_cubic(whole, at=0.35, select=(1,)):
    """The three points a cubic cut in two leaves behind, which Slide Point
    must be able to move without changing the shape at all."""
    a, b = geo.bezier_split(*whole, at)
    return bezier(
        [a[0], a[3], b[3]],
        [(geo.lerp(a[0], a[1], -1.0), a[1]), (a[2], b[1]),
         (b[2], geo.lerp(b[3], b[2], -1.0))],
        select=select)


def poly(points, select=()):
    pts = [sd.PointData(co=tuple(p), select=(i in select)) for i, p in enumerate(points)]
    return sd.SplineData('POLY', pts, False, {"resolution_u": 12})


def nurbs(points, select=()):
    pts = [sd.PointData(co=tuple(p), select=(i in select)) for i, p in enumerate(points)]
    return sd.SplineData('NURBS', pts, False, {"resolution_u": 12, "order_u": 3})


def make_curve(splines, dims='3D', loc=(0, 0, 0), scale=(1, 1, 1)):
    curve = bpy.data.curves.new("C", 'CURVE')
    curve.dimensions = dims
    curve.resolution_u = 12
    for spec in splines:
        sd.write_spline(curve, spec)
    obj = bpy.data.objects.new("C", curve)
    bpy.context.scene.collection.objects.link(obj)
    obj.location, obj.scale = loc, scale
    bpy.context.view_layer.update()
    return obj


def edit(obj):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')


def object_mode():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


def data_of(obj, index=0):
    return sd.read_spline(obj.data.splines[index])


def near(a, b, tol=1e-5):
    return geo.distance(a, b) <= tol


def cancelled(op, **kwargs):
    try:
        return op(**kwargs) == {'CANCELLED'}
    except RuntimeError:
        return True


def outline(data, steps=80):
    return sd.flatten(data, steps=steps)


def strays(after, before):
    """Largest distance from the new outline to the old one."""
    return max(sl.distance_to_polyline(p, before) for p in after)


def span_length(data, k):
    return sl.chain_length(sl.span_of(data, k)[0])


def slid(spline, factor, k=1, dims='3D', **kwargs):
    """Run Slide Point on a fresh curve and give back (before, after, object)."""
    reset()
    obj = make_curve([spline], dims=dims, **kwargs)
    before = outline(spline)
    edit(obj)
    ops.curve_toolkit_slide_point(factor=factor)
    object_mode()
    return before, data_of(obj), obj


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# -----------------------------------------------------------------------------
# The maths on its own
# -----------------------------------------------------------------------------

@test
def the_parent_of_two_pieces_of_one_cubic_is_found():
    whole = ((0, 0, 0), (1, 2, 0), (3, 2, 0), (4, 0, 0))
    for at in (0.15, 0.35, 0.5, 0.85):
        a, b = geo.bezier_split(*whole, at)
        found = sl.parent_cubic(a, b, 1e-9)
        assert found is not None, at
        parent, tau = found
        assert abs(tau - at) < 1e-9, (at, tau)
        assert max(geo.distance(x, y) for x, y in zip(parent, whole)) < 1e-9


@test
def two_cubics_that_are_not_one_are_not_mistaken_for_it():
    k = QUARTER
    halves = (((1, 0, 0), (1, k, 0), (k, 1, 0), (0, 1, 0)),
              ((0, 1, 0), (-k, 1, 0), (-1, k, 0), (-1, 0, 0)))
    assert sl.parent_cubic(*halves, 1e-5 * math.pi) is None, "a half circle is not one cubic"
    pair = (((0, 0, 0), (0.5, 1, 0), (1.5, 1.5, 0), (2, 1.5, 0)),
            ((2, 1.5, 0), (2.5, 1.5, 0), (3.2, 0.8, 0), (4, 0, 0)))
    assert sl.parent_cubic(*pair, 1e-5 * 5.15) is None


@test
def the_factor_and_the_parameter_are_inverses():
    chain = list(geo.bezier_split(*((0, 0, 0), (1, 2, 0), (3, 2, 0), (4, 0, 0)), 0.35))
    for g in (0.2, 0.75, 1.0, 1.4, 1.9):
        f = sl.factor_at_param(chain, g)
        assert abs(sl.param_at_factor(chain, f) - g) < 1e-3, (g, f)


@test
def a_fitted_cubic_keeps_the_ends_and_both_tangents():
    pieces = [((0, 0, 0), (0.5, 1, 0), (1.5, 1.5, 0), (2, 1.5, 0)),
              ((2, 1.5, 0), (2.5, 1.5, 0), (3.2, 0.8, 0), (4, 0, 0))]
    fitted = sl.fit_one_cubic(pieces)
    assert near(fitted[0], pieces[0][0]) and near(fitted[3], pieces[-1][3])
    assert near(sl.tangent_at(fitted, 0.0), sl.tangent_at(pieces[0], 0.0), 1e-6)
    assert near(sl.tangent_at(fitted, 1.0), sl.tangent_at(pieces[-1], 1.0), 1e-6)


@test
def the_fit_follows_the_stretch_it_stands_for():
    pieces = [((0, 0, 0), (0.5, 1, 0), (1.5, 1.5, 0), (2, 1.5, 0)),
              ((2, 1.5, 0), (2.5, 1.5, 0), (3.2, 0.8, 0), (4, 0, 0))]
    fitted = sl.fit_one_cubic(pieces)
    length = sl.chain_length(pieces)
    assert sl.drift([fitted], pieces) / length < 0.025, "the fit should stay within 2.5%"


# -----------------------------------------------------------------------------
# The exact cases
# -----------------------------------------------------------------------------

@test
def a_subdivided_cubic_slides_without_changing_shape():
    whole = ((0, 0, 0), (1, 2, 0), (3, 2, 0), (4, 0, 0))
    spline = subdivided_cubic(whole)
    length = sl.chain_length(sl.span_of(spline, 1)[0])
    for factor in (0.1, 0.3, 0.5, 0.7, 0.9):
        before, after, _ = slid(spline, factor)
        assert strays(outline(after), before) / length < NOISE, (
            factor, strays(outline(after), before) / length)


@test
def a_subdivided_cubic_really_moves_the_point():
    whole = ((0, 0, 0), (1, 2, 0), (3, 2, 0), (4, 0, 0))
    spline = subdivided_cubic(whole)
    was = spline.points[1].co
    _, after, _ = slid(spline, 0.9)
    assert geo.distance(after.points[1].co, was) > 0.5, "the point did not move"
    assert len(after.points) == 3, len(after.points)


@test
def sliding_an_end_point_is_exact_and_shortens_the_curve():
    spline = smooth([(0, 0, 0), (2, 2, 0), (5, 2, 0), (7, 0, 0)], select=(0,))
    before = outline(spline)
    whole_length = sl.chain_length([sl._segment(spline, i, i + 1) for i in range(3)])
    for factor in (0.2, 0.5, 0.8):
        _, after, _ = slid(spline, factor, k=0)
        # Every point of the shorter curve is still on the original one.
        assert strays(outline(after), before) / whole_length < NOISE, factor
        # And it really is shorter.
        shorter = sl.chain_length([sl._segment(after, i, i + 1) for i in range(3)])
        assert shorter < whole_length - 0.1, (factor, shorter, whole_length)


@test
def sliding_the_last_point_is_exact_too():
    spline = smooth([(0, 0, 0), (2, 2, 0), (5, 2, 0), (7, 0, 0)], select=(3,))
    before = outline(spline)
    whole = sl.chain_length([sl._segment(spline, i, i + 1) for i in range(3)])
    _, after, _ = slid(spline, 0.6, k=3)
    assert strays(outline(after), before) / whole < NOISE
    assert sl.chain_length([sl._segment(after, i, i + 1) for i in range(3)]) < whole - 0.1
    # The first point has not moved at all.
    assert near(after.points[0].co, (0, 0, 0))


@test
def sliding_to_where_the_point_already_is_changes_nothing():
    whole = ((0, 0, 0), (1, 2, 0), (3, 2, 0), (4, 0, 0))
    for spline in (subdivided_cubic(whole),
                   smooth([(0, 0, 0), (2, 2, 0), (5, 2, 0), (7, 0, 0)], select=(1,))):
        here = sl.current_factor(spline, 1)
        length = sl.chain_length(sl.span_of(spline, 1)[0])
        before, after, _ = slid(spline, here)
        assert strays(outline(after), before) / length < NOISE, here
        assert near(after.points[1].co, spline.points[1].co, 1e-4)


@test
def current_factor_reads_where_the_point_sits():
    # Of a cubic cut at 0.35, the first piece holds a bit over a third of the
    # length, which is what the slider has to open at.
    whole = ((0, 0, 0), (1, 2, 0), (3, 2, 0), (4, 0, 0))
    spline = subdivided_cubic(whole, at=0.35)
    f = sl.current_factor(spline, 1)
    assert 0.3 < f < 0.45, f
    # An end point sits at 0 of its own segment.
    assert sl.current_factor(spline, 0) == 0.0


# -----------------------------------------------------------------------------
# The fitted case
# -----------------------------------------------------------------------------

@test
def a_smooth_point_that_is_not_exact_stays_close():
    spline = smooth([(0, 0, 0), (2, 2, 0), (5, 2, 0), (7, 0, 0)], select=(1,))
    length = sl.chain_length(sl.span_of(spline, 1)[0])
    for factor in (0.15, 0.5, 0.85):
        before, after, _ = slid(spline, factor)
        away = strays(outline(after), before) / length
        assert away < 0.03, f"factor {factor} drifted {100 * away:.2f}%"


@test
def a_3d_curve_slides_too():
    spline = smooth([(0, 0, 0), (2, 2, 1), (5, 2, 2), (7, 0, 1)], select=(1, ))
    length = sl.chain_length(sl.span_of(spline, 1)[0])
    before, after, _ = slid(spline, 0.5)
    assert abs(after.points[1].co[2]) > 1e-6, "the point should have kept its height"
    assert strays(outline(after), before) / length < 0.03


@test
def the_neighbours_do_not_move():
    spline = smooth([(0, 0, 0), (2, 2, 0), (5, 2, 0), (7, 0, 0)], select=(1,))
    _, after, _ = slid(spline, 0.8)
    assert near(after.points[0].co, (0, 0, 0))
    assert near(after.points[2].co, (5, 2, 0))
    assert near(after.points[3].co, (7, 0, 0))


@test
def the_number_of_points_never_changes():
    spline = smooth([(0, 0, 0), (2, 2, 0), (5, 2, 0), (7, 0, 0)], select=(1,))
    _, after, _ = slid(spline, 0.2)
    assert len(after.points) == 4, len(after.points)


@test
def a_closed_spline_slides_like_an_open_one():
    spline = smooth([(0, 0, 0), (4, 0, 0), (4, 4, 0), (0, 4, 0)],
                    cyclic=True, select=(1,))
    length = sl.chain_length(sl.span_of(spline, 1)[0])
    before, after, _ = slid(spline, 0.75)
    assert after.cyclic and len(after.points) == 4
    assert strays(outline(after), before) / length < 0.03


@test
def point_zero_of_a_closed_spline_has_two_neighbours():
    spline = smooth([(0, 0, 0), (4, 0, 0), (4, 4, 0), (0, 4, 0)],
                    cyclic=True, select=(0,))
    length = sl.chain_length(sl.span_of(spline, 0)[0])
    before, after, _ = slid(spline, 0.7, k=0)
    assert strays(outline(after), before) / length < 0.03
    assert not near(after.points[0].co, (0, 0, 0)), "the point should have moved"


@test
def the_shape_is_kept_whatever_the_object_transform():
    spline = smooth([(0, 0, 0), (2, 2, 0), (5, 2, 0), (7, 0, 0)], select=(1,))
    plain = slid(spline, 0.7)[1].points[1].co
    moved = slid(spline, 0.7, loc=(10, -5, 3), scale=(2, 2, 2))[1].points[1].co
    # Slide works in the local space of the curve, so the local result is the
    # same wherever the object sits.
    assert near(plain, moved, 1e-5), (plain, moved)


# -----------------------------------------------------------------------------
# Handles
# -----------------------------------------------------------------------------

@test
def the_slid_point_comes_out_smooth():
    spline = smooth([(0, 0, 0), (2, 2, 0), (5, 2, 0), (7, 0, 0)], select=(1,))
    _, after, _ = slid(spline, 0.65)
    p = after.points[1]
    arriving = geo.normalized(geo.sub(p.co, p.hl))
    leaving = geo.normalized(geo.sub(p.hr, p.co))
    angle = math.degrees(math.acos(max(-1.0, min(1.0, geo.dot(arriving, leaving)))))
    assert angle < 0.5, f"the slid point turns {angle:.2f} degrees"
    assert p.hlt == p.hrt == 'ALIGNED', (p.hlt, p.hrt)


@test
def auto_handles_of_the_neighbours_are_frozen():
    # An Auto handle would be recomputed now that its neighbour has moved,
    # which would change a segment that is none of our business.
    spline = smooth([(0, 0, 0), (2, 2, 0), (5, 2, 0), (7, 0, 0)],
                    select=(1,), types=('AUTO', 'AUTO'))
    _, after, _ = slid(spline, 0.7)
    assert after.points[0].hlt == 'FREE', after.points[0].hlt
    assert after.points[2].hrt == 'FREE', after.points[2].hrt


@test
def a_straight_span_keeps_vector_handles():
    spline = bezier(
        [(0, 0, 0), (3, 0, 0), (9, 0, 0)],
        [((-1, 0, 0), (1, 0, 0)), ((2, 0, 0), (5, 0, 0)), ((7, 0, 0), (11, 0, 0))],
        select=(1,), types=('VECTOR', 'VECTOR'))
    _, after, _ = slid(spline, 0.5)
    p = after.points[1]
    assert near(p.co, (4.5, 0, 0)), p.co
    assert p.hlt == p.hrt == 'VECTOR', (p.hlt, p.hrt)


@test
def the_outer_handle_of_an_end_point_mirrors_the_inner_one():
    # v0.26.0: at Position 0 nothing moves; as soon as the point slides, the
    # outer handle is the mirror image of the inner one (in line, as long).
    for k, outer, inner in ((0, "hl", "hr"), (3, "hr", "hl")):
        spline = smooth([(0, 0, 0), (2, 2, 0), (5, 2, 0), (7, 0, 0)], select=(k,))
        offset = geo.sub(getattr(spline.points[k], outer), spline.points[k].co)
        _, after, _ = slid(spline, 0.0, k=k)
        assert near(geo.sub(getattr(after.points[k], outer), after.points[k].co), offset, 1e-5)
        for factor in (0.2, 0.5, 1.0):
            _, after, _ = slid(spline, factor, k=k)
            p = after.points[k]
            mirror = geo.sub(p.co, getattr(p, inner))
            assert near(geo.sub(getattr(p, outer), p.co), mirror, 1e-4), factor


# -----------------------------------------------------------------------------
# What has to be refused
# -----------------------------------------------------------------------------

@test
def a_corner_is_refused():
    # The handles of point 1 meet at a right angle: a real corner.
    spline = bezier(
        [(0, 0, 0), (3, 3, 0), (6, 0, 0)],
        [((-1, -1, 0), (1, 1, 0)), ((2, 2, 0), (4, 2, 0)), ((5, 1, 0), (7, -1, 0))],
        select=(1,))
    reset()
    obj = make_curve([spline])
    edit(obj)
    assert cancelled(ops.curve_toolkit_slide_point, factor=0.5)
    object_mode()
    assert near(data_of(obj).points[1].co, (3, 3, 0)), "the curve should be untouched"


@test
def an_almost_aligned_point_is_still_allowed():
    # Half a degree of turn is not a corner.
    turn = math.radians(0.5)
    spline = bezier(
        [(0, 0, 0), (3, 0, 0), (6, 0, 0)],
        [((-1, 0, 0), (1, 0, 0)),
         ((2, 0, 0), (3 + math.cos(turn), math.sin(turn), 0)),
         ((5, 0, 0), (7, 0, 0))],
        select=(1,))
    reset()
    obj = make_curve([spline])
    edit(obj)
    assert ops.curve_toolkit_slide_point(factor=0.4) == {'FINISHED'}
    object_mode()


@test
def poly_and_nurbs_are_refused():
    for spline in (poly([(0, 0, 0), (3, 1, 0), (6, 0, 0)], select=(1,)),
                   nurbs([(0, 0, 0), (3, 1, 0), (6, 0, 0)], select=(1,))):
        reset()
        obj = make_curve([spline])
        edit(obj)
        assert cancelled(ops.curve_toolkit_slide_point, factor=0.5), spline.kind
        object_mode()


@test
def two_neighbouring_points_are_refused():
    spline = smooth([(0, 0, 0), (2, 2, 0), (5, 2, 0), (7, 0, 0)], select=(1, 2))
    reset()
    obj = make_curve([spline])
    edit(obj)
    assert cancelled(ops.curve_toolkit_slide_point, factor=0.5)
    object_mode()
    assert near(data_of(obj).points[1].co, (2, 2, 0))


@test
def nothing_selected_is_refused():
    spline = smooth([(0, 0, 0), (2, 2, 0), (5, 2, 0), (7, 0, 0)])
    reset()
    obj = make_curve([spline])
    edit(obj)
    assert cancelled(ops.curve_toolkit_slide_point, factor=0.5)
    object_mode()


@test
def a_closed_spline_of_two_points_is_refused():
    spline = smooth([(0, 0, 0), (4, 0, 0)], cyclic=True, select=(0,))
    reset()
    obj = make_curve([spline])
    edit(obj)
    assert cancelled(ops.curve_toolkit_slide_point, factor=0.5)
    object_mode()


# -----------------------------------------------------------------------------
# Several points at once
# -----------------------------------------------------------------------------

@test
def two_points_far_enough_apart_slide_together():
    spline = smooth([(0, 0, 0), (2, 2, 0), (5, 3, 0), (8, 2, 0), (10, 0, 0)],
                    select=(1, 3))
    before = outline(spline)
    reset()
    obj = make_curve([spline])
    edit(obj)
    assert ops.curve_toolkit_slide_point(factor=0.8) == {'FINISHED'}
    object_mode()
    after = data_of(obj)
    assert len(after.points) == 5
    assert not near(after.points[1].co, (2, 2, 0)), "point 1 should have moved"
    assert not near(after.points[3].co, (8, 2, 0)), "point 3 should have moved"
    # The curve as a whole is still close to what it was.
    whole = sl.chain_length([sl._segment(spline, i, i + 1) for i in range(4)])
    assert strays(outline(after), before) / whole < 0.03


@test
def only_the_selected_spline_is_touched():
    moving = smooth([(0, 0, 0), (2, 2, 0), (5, 2, 0), (7, 0, 0)], select=(1,))
    still = smooth([(0, 9, 0), (2, 11, 0), (5, 11, 0), (7, 9, 0)])
    reset()
    obj = make_curve([moving, still])
    edit(obj)
    ops.curve_toolkit_slide_point(factor=0.8)
    object_mode()
    second = data_of(obj, 1)
    for p, q in zip(second.points, still.points):
        assert near(p.co, q.co), "the other spline should be untouched"


# -----------------------------------------------------------------------------
# Registration and the panel
# -----------------------------------------------------------------------------

@test
def the_operator_has_a_factor_between_zero_and_one():
    props = ops.curve_toolkit_slide_point.get_rna_type().properties
    assert "factor" in props
    assert props["factor"].hard_min == 0.0 and props["factor"].hard_max == 1.0


@test
def slide_point_survives_a_register_cycle():
    reset()
    toolkit.unregister()
    toolkit.register()
    assert hasattr(ops, "curve_toolkit_slide_point")


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
