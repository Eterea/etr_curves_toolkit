# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Tests of the Phase 27 changes of Curve Toolkit (v0.27.0): Tangents to 2
Circles with Main / Crossing Tangents and External / Internal Loops (always a
new object in Object Mode), Tangents from Point with External / Internal Loop,
and the Curvature of Extend with no soft limits. With Blender as a Python
module:

    python test_phase27.py <folder that contains the etr_curves_toolkit package>
"""

import math
import sys
import traceback

sys.path.insert(0, sys.argv[1])

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

import etr_curves_toolkit as toolkit  # noqa: E402
from etr_curves_toolkit import spline_data as sd  # noqa: E402

toolkit.register()
ops = bpy.ops.etr
TOL = 1e-4


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if not hasattr(bpy.types.Scene, "etr_curves_toolkit"):
        toolkit.register()


def make(name, datas, location=(0, 0, 0), rotation=(0, 0, 0)):
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    sd.replace_splines(cu, datas)
    obj = bpy.data.objects.new(name, cu)
    obj.location = location
    obj.rotation_euler = rotation
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.update()
    return obj


def circle(cx, cy, r, select=False):
    k = 0.5522847 * r
    pts = []
    for (x, y), (tx, ty) in (((cx - r, cy), (0, 1)), ((cx, cy + r), (1, 0)),
                             ((cx + r, cy), (0, -1)), ((cx, cy - r), (-1, 0))):
        pts.append(sd.PointData(co=(x, y, 0), hl=(x - tx * k, y - ty * k, 0),
                                hr=(x + tx * k, y + ty * k, 0),
                                hlt='ALIGNED', hrt='ALIGNED', select=select))
    return sd.SplineData('BEZIER', pts, True, {})


def poly_circle(cx, cy, r, n=48, select=False):
    return sd.SplineData('POLY', [sd.PointData(co=(cx + r * math.cos(2 * math.pi * i / n),
                                                   cy + r * math.sin(2 * math.pi * i / n), 0),
                                               select=select) for i in range(n)], True, {})


def select_only(*objs, active=None):
    for o in bpy.context.scene.objects:
        o.select_set(o in objs)
    bpy.context.view_layer.objects.active = active or objs[-1]


def object_mode():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


def samples(obj, spline, n=24):
    """World-space points along a spline."""
    mw = obj.matrix_world
    if spline.type != 'BEZIER':
        return [mw @ p.co.xyz for p in spline.points]
    bps = list(spline.bezier_points)
    out = []
    count = len(bps) if spline.use_cyclic_u else len(bps) - 1
    for i in range(count):
        a, b = bps[i], bps[(i + 1) % len(bps)]
        p0, h0, h1, p1 = a.co, a.handle_right, b.handle_left, b.co
        for k in range(n):
            t = k / n
            s = 1 - t
            out.append(mw @ (s * s * s * p0 + 3 * s * s * t * h0 + 3 * s * t * t * h1
                             + t * t * t * p1))
    return out


def passes(obj, spline, point, tol=1e-2):
    return min((p - Vector(point)).length for p in samples(obj, spline)) < tol


def two_circles(**kw):
    """Circle A (r 2) at the origin and circle B (r 1) at (6, 0), two
    objects, both selected; runs the operator; returns (a, b, result)."""
    reset()
    a = make("A", [circle(0, 0, 2)])
    b = make("B", [circle(0, 0, 1)], location=(6, 0, 0))
    select_only(a, b)
    assert ops.curve_toolkit_tangents_2_circles(**kw) == {'FINISHED'}
    return a, b, bpy.context.active_object


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# -----------------------------------------------------------------------------
# Tangents to 2 Circles
# -----------------------------------------------------------------------------

@test
def defaults_main_tangents_only():
    props = ops.curve_toolkit_tangents_2_circles.get_rna_type().properties
    assert props["main"].default is True
    assert not props["crossing"].default
    assert not props["external_loop"].default and not props["internal_loop"].default
    a, b, res = two_circles()
    assert res not in (a, b) and res.name == "Tangents"
    assert len(res.data.splines) == 2 and not any(s.use_cyclic_u for s in res.data.splines)
    assert not a.select_get() and not b.select_get() and res.select_get()
    assert not a.hide_get() and not b.hide_get()


@test
def one_object_goes_to_a_new_object():
    reset()
    a = make("A", [circle(0, 0, 2), circle(6, 0, 1)])
    select_only(a)
    assert ops.curve_toolkit_tangents_2_circles(external_loop=True) == {'FINISHED'}
    res = bpy.context.active_object
    assert res is not a and len(a.data.splines) == 2 and len(res.data.splines) == 1
    assert not a.select_get()


@test
def external_loop_of_main_tangents():
    a, b, res = two_circles(external_loop=True)
    splines = list(res.data.splines)
    assert len(splines) == 1 and splines[0].use_cyclic_u and splines[0].type == 'BEZIER'
    s = splines[0]
    # The arcs that face away from the other circle: the belt.
    assert passes(res, s, (-2, 0, 0)) and passes(res, s, (7, 0, 0))
    assert not passes(res, s, (2, 0, 0)) and not passes(res, s, (5, 0, 0))
    # Every point is on a circle or on a tangent: on a circle, the radius.
    for p in samples(res, s):
        on_a = abs(p.length - 2) < 1e-3
        on_b = abs((p - Vector((6, 0, 0))).length - 1) < 1e-3
        assert on_a or on_b or abs(p.y) > 0.5, p


@test
def internal_loop_of_main_tangents():
    a, b, res = two_circles(internal_loop=True)
    s = res.data.splines[0]
    assert len(res.data.splines) == 1 and s.use_cyclic_u
    assert passes(res, s, (2, 0, 0)) and passes(res, s, (5, 0, 0))
    assert not passes(res, s, (-2, 0, 0)) and not passes(res, s, (7, 0, 0))


@test
def crossing_loops_are_figures_of_eight():
    for external, inside, outside in ((True, ((-2, 0, 0), (7, 0, 0)), ((2, 0, 0), (5, 0, 0))),
                                      (False, ((2, 0, 0), (5, 0, 0)), ((-2, 0, 0), (7, 0, 0)))):
        a, b, res = two_circles(main=False, crossing=True, external_loop=external,
                                internal_loop=not external)
        assert len(res.data.splines) == 1
        s = res.data.splines[0]
        for p in inside:
            assert passes(res, s, p), (external, p)
        for p in outside:
            assert not passes(res, s, p), (external, p)
        # No point where the tangents cross (4 on 2 / 1 divides 0-6 at 4).
        assert all((p.co - Vector((4, 0, 0))).length > 0.1 for p in s.bezier_points)
        # ...but the loop goes through it.
        assert passes(res, s, (4, 0, 0))


@test
def all_options_make_four_loops():
    a, b, res = two_circles(crossing=True, external_loop=True, internal_loop=True)
    assert len(res.data.splines) == 4 and all(s.use_cyclic_u for s in res.data.splines)
    assert all(p.select_control_point for s in res.data.splines for p in s.bezier_points)


@test
def handle_types_of_the_loops():
    a, b, res = two_circles(external_loop=True)
    s = res.data.splines[0]
    kinds = {(p.handle_left_type, p.handle_right_type) for p in s.bezier_points}
    # Where a tangent meets an arc: Vector on the side of the line.
    assert ('VECTOR', 'FREE') in kinds and ('FREE', 'VECTOR') in kinds, kinds
    # Inside an arc (the points of the circles): Aligned.
    assert ('ALIGNED', 'ALIGNED') in kinds, kinds


@test
def arcs_lie_on_the_circles():
    # The arcs are cut from the splines themselves: their points are the
    # points of the circles.
    a, b, res = two_circles(external_loop=True)
    s = res.data.splines[0]
    cos = [res.matrix_world @ p.co for p in s.bezier_points]
    for corner in ((-2, 0, 0), (0, 2, 0), (0, -2, 0), (7, 0, 0)):
        assert any((co - Vector(corner)).length < 1e-4 for co in cos), corner


@test
def nothing_to_draw():
    reset()
    a = make("A", [circle(0, 0, 2)])
    b = make("B", [circle(0, 0, 1)], location=(6, 0, 0))
    select_only(a, b)
    n = len(bpy.data.objects)
    assert ops.curve_toolkit_tangents_2_circles(main=False) == {'FINISHED'}
    assert len(bpy.data.objects) == n


@test
def edit_mode_loops_into_the_curve():
    reset()
    a = make("A", [circle(0, 0, 2, select=True), circle(6, 0, 1, select=True)])
    select_only(a)
    bpy.ops.object.mode_set(mode='EDIT')
    assert ops.curve_toolkit_tangents_2_circles(internal_loop=True, crossing=True) == {'FINISHED'}
    assert bpy.context.mode == 'EDIT_CURVE'
    object_mode()
    assert len(a.data.splines) == 4
    assert all(s.use_cyclic_u for s in a.data.splines[2:])
    assert all(p.select_control_point for s in a.data.splines[2:] for p in s.bezier_points)
    assert not any(p.select_control_point for s in a.data.splines[:2] for p in s.bezier_points)
    assert not any(o.name.startswith("Tangents") for o in bpy.data.objects)


@test
def rotated_and_poly_circles():
    reset()
    rot = (math.radians(90), 0, math.radians(30))
    a = make("A", [poly_circle(0, 0, 2)], location=(1, 2, 3), rotation=rot)
    b = make("B", [circle(5, 1, 1)], location=(1, 2, 3), rotation=rot)
    select_only(a, b)
    assert ops.curve_toolkit_tangents_2_circles(external_loop=True) == {'FINISHED'}
    res = bpy.context.active_object
    ca = a.matrix_world @ Vector((0, 0, 0))
    cb = b.matrix_world @ Vector((5, 1, 0))
    for p in samples(res, res.data.splines[0]):
        da, db = abs((p - ca).length - 2), abs((p - cb).length - 1)
        # On a circle (a Poly one is a polygon), or on a tangent, outside both.
        assert da < 2e-2 or db < 1e-3 or ((p - ca).length > 2 and (p - cb).length > 1), p


@test
def loops_take_booleans():
    reset()
    for loc, r in (((0, 0, 0), 2), ((6, 1, 0), 1)):
        bpy.ops.curve.primitive_bezier_circle_add(radius=r, location=loc)
    a, b = sorted(bpy.context.scene.objects, key=lambda o: o.location.x)
    for internal in (False, True):
        select_only(a, b)
        assert ops.curve_toolkit_tangents_2_circles(external_loop=not internal,
                                                    internal_loop=internal) == {'FINISHED'}
        t = bpy.context.active_object
        for other in (a, b):
            # The internal loop lies outside both circles (it only shares an
            # arc with each): no Intersection to make.
            names = ("union", "difference") if internal else ("union", "intersection",
                                                               "difference")
            for name in names:
                op = getattr(ops, f"curve_toolkit_boolean_{name}")
                for o in bpy.context.scene.objects:
                    o.hide_set(False)
                select_only(other, t, active=t)
                n = len(bpy.data.objects)
                assert op() == {'FINISHED'}, (internal, other.name, name)
                made = len(bpy.data.objects) - n
                # A Difference may be empty (the belt covers circle A).
                assert made == 1 or (made == 0 and name == "difference"), \
                    (internal, other.name, name)
        bpy.data.objects.remove(t)


# -----------------------------------------------------------------------------
# Tangents from Point
# -----------------------------------------------------------------------------

def _circle_and_point(point):
    data = circle(0, 0, 1)
    data.points[0].select = True
    return make("CP", [data, sd.SplineData('POLY', [sd.PointData(co=point, select=True)],
                                           False, {})])


def _from_point(**kw):
    reset()
    obj = _circle_and_point((3, 0, 0))
    select_only(obj)
    bpy.ops.object.mode_set(mode='EDIT')
    assert ops.curve_toolkit_tangents_from_point(**kw) == {'FINISHED'}
    object_mode()
    return obj


@test
def from_point_lines_by_default():
    props = ops.curve_toolkit_tangents_from_point.get_rna_type().properties
    assert "connect_close" not in props
    assert not props["external_loop"].default and not props["internal_loop"].default
    obj = _from_point()
    assert len(obj.data.splines) == 4
    assert all(s.type == 'POLY' and len(s.points) == 2 for s in obj.data.splines[2:])


@test
def from_point_loops():
    obj = _from_point(external_loop=True)
    assert len(obj.data.splines) == 3
    s = obj.data.splines[2]
    assert s.type == 'BEZIER' and s.use_cyclic_u
    assert passes(obj, s, (-1, 0, 0)) and passes(obj, s, (3, 0, 0))
    assert not passes(obj, s, (1, 0, 0))
    assert all(p.select_control_point for p in s.bezier_points)
    tip = [p for p in s.bezier_points if (p.co - Vector((3, 0, 0))).length < TOL]
    assert len(tip) == 1 and tip[0].handle_left_type == tip[0].handle_right_type == 'VECTOR'

    obj = _from_point(internal_loop=True)
    s = obj.data.splines[2]
    assert passes(obj, s, (1, 0, 0)) and not passes(obj, s, (-1, 0, 0))

    obj = _from_point(external_loop=True, internal_loop=True)
    assert len(obj.data.splines) == 4


@test
def from_point_loop_out_of_plane():
    reset()
    obj = _circle_and_point((2, 0, 1.5))
    select_only(obj)
    bpy.ops.object.mode_set(mode='EDIT')
    assert ops.curve_toolkit_tangents_from_point(external_loop=True) == {'FINISHED'}
    object_mode()
    s = obj.data.splines[2]
    assert passes(obj, s, (-1, 0, 0)) and passes(obj, s, (2, 0, 1.5))


# -----------------------------------------------------------------------------
# Extend
# -----------------------------------------------------------------------------

@test
def extend_curvature_without_soft_limits():
    prop = ops.curve_toolkit_extend.get_rna_type().properties["curvature"]
    assert abs(prop.hard_min + 2 * math.pi) < 1e-6 and abs(prop.hard_max - 2 * math.pi) < 1e-6
    assert prop.soft_min == prop.hard_min and prop.soft_max == prop.hard_max


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
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
