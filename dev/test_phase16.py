# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Tests of the Phase 16 tools of Curve Toolkit (Tangents to 2 Circles,
Perpendicular from Point, Handles to Lines), with Blender as a Python module:

    python test_phase16.py <folder that contains the etr_curves_toolkit package>
"""

import math
import sys
import traceback

sys.path.insert(0, sys.argv[1])

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

import etr_curves_toolkit as toolkit  # noqa: E402
from etr_curves_toolkit import spline_data as sd  # noqa: E402
from etr_curves_toolkit import tangents as tg  # noqa: E402

toolkit.register()
ops = bpy.ops.etr
TOL = 1e-4
TOP = dict(view='TOP', view_normal=(0, 0, 1))


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if not hasattr(bpy.types.Scene, "etr_curves_toolkit"):
        toolkit.register()


def make(name, datas, location=(0, 0, 0)):
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    sd.replace_splines(cu, datas)
    obj = bpy.data.objects.new(name, cu)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    return obj


def circle(cx, cy, r, select=False):
    k = 0.5522847 * r
    pts = []
    for (x, y), (tx, ty) in (((cx - r, cy), (0, 1)), ((cx, cy + r), (1, 0)),
                             ((cx + r, cy), (0, -1)), ((cx, cy - r), (-1, 0))):
        pts.append(sd.PointData(co=(x, y, 0), hl=(x - tx * k, y - ty * k, 0), hr=(x + tx * k, y + ty * k, 0),
                                hlt='ALIGNED', hrt='ALIGNED', select=select))
    return sd.SplineData('BEZIER', pts, True, {})


def select_only(*objs, active=None):
    for o in bpy.context.scene.objects:
        o.select_set(o in objs)
    bpy.context.view_layer.objects.active = active or objs[-1]


def world_splines(obj):
    mw = obj.matrix_world
    return [[mw @ (bp.co if s.type == 'BEZIER' else bp.co.xyz)
             for bp in (s.bezier_points if s.type == 'BEZIER' else s.points)] for s in obj.data.splines]


def on_circle(p, c, r):
    return abs((p - Vector(c)).length - r) < 2e-3 * r


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


@test
def fit_circle_rejects_ellipses():
    reset()
    a = make("A", [circle(0, 0, 2)])
    a.scale = (2, 1, 1)
    bpy.context.view_layer.update()
    try:
        tg.circle_of(a, sd.read_spline(a.data.splines[0]))
    except tg.Fail:
        return
    raise AssertionError("an ellipse passed as a circle")


@test
def two_objects_outer_tangents():
    reset()
    a = make("A", [circle(0, 0, 2)])
    b = make("B", [circle(0, 0, 1)], location=(6, 0, 0))
    select_only(a, b)
    assert ops.curve_toolkit_tangents_2_circles() == {'FINISHED'}
    res = bpy.context.active_object
    assert res not in (a, b)
    lines = world_splines(res)
    assert len(lines) == 2
    for p, q in lines:
        assert on_circle(p, (0, 0, 0), 2) and on_circle(q, (6, 0, 0), 1)
        # Tangent: radius at the contact perpendicular to the line.
        assert abs(p.normalized().dot((q - p).normalized())) < 1e-3
    bp = res.data.splines[0].bezier_points[0]
    assert bp.handle_left_type == 'VECTOR'


@test
def same_object_with_crossing():
    reset()
    a = make("A", [circle(0, 0, 2), circle(7, 0, 1)])
    select_only(a)
    assert ops.curve_toolkit_tangents_2_circles(crossing=True) == {'FINISHED'}
    assert len(a.data.splines) == 2 + 4
    for p, q in world_splines(a)[2:]:
        assert on_circle(p, (0, 0, 0), 2) and on_circle(q, (7, 0, 0), 1)


@test
def crossing_skipped_when_overlapping():
    reset()
    a = make("A", [circle(0, 0, 2), circle(2.5, 0, 1)])
    select_only(a)
    ops.curve_toolkit_tangents_2_circles(crossing=True)
    assert len(a.data.splines) == 2 + 2


@test
def inside_is_refused():
    reset()
    a = make("A", [circle(0, 0, 3), circle(0.5, 0, 1)])
    select_only(a)
    try:
        r = ops.curve_toolkit_tangents_2_circles()
    except RuntimeError:
        r = {'CANCELLED'}
    assert r == {'CANCELLED'}


@test
def boolean_all_belt():
    reset()
    a = make("A", [circle(0, 0, 2), circle(6, 0, 1)])
    select_only(a)
    assert ops.curve_toolkit_tangents_2_circles(boolean_all=True) == {'FINISHED'}
    res = bpy.context.active_object
    assert res is not a and len(a.data.splines) == 2
    assert a.hide_get() and not res.hide_get()                 # only the belt in view
    assert len(res.data.splines) == 1 and res.data.splines[0].use_cyclic_u
    data = sd.read_spline(res.data.splines[0])
    samples = sd.flatten(data, steps=24)
    xs = [p[0] for p in samples]
    assert abs(min(xs) + 2) < 5e-3 and abs(max(xs) - 7) < 5e-3
    kinds = [(p.hlt, p.hrt) for p in data.points]
    assert kinds.count(('VECTOR', 'ALIGNED')) == 2 and kinds.count(('ALIGNED', 'VECTOR')) == 2


@test
def edit_mode_two_splines():
    reset()
    a = make("A", [circle(0, 0, 2, select=True), circle(6, 0, 1, select=True), circle(0, 9, 1)])
    select_only(a)
    bpy.ops.object.mode_set(mode='EDIT')
    assert ops.curve_toolkit_tangents_2_circles() == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    assert len(a.data.splines) == 5


def poly(coords, selected=()):
    return sd.SplineData('POLY', [sd.PointData(co=c, select=i in selected) for i, c in enumerate(coords)],
                         False, {})


@test
def perpendicular_on_poly():
    reset()
    a = make("A", [poly([(0, 0, 0), (4, 0, 0), (8, 0, 0)], {1})])
    select_only(a)
    bpy.ops.object.mode_set(mode='EDIT')
    assert ops.curve_toolkit_perpendicular(**TOP) == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    s = a.data.splines[1]
    assert s.type == 'POLY'
    p, q = [x.co.xyz for x in s.points]
    assert (p - Vector((4, 0, 0))).length < TOL
    assert (q - Vector((4, 2, 0))).length < TOL         # length / 4, to the left


@test
def perpendicular_negative_and_bisector():
    reset()
    a = make("A", [poly([(0, 4, 0), (4, 0, 0), (0, -4, 0)], {1})])
    select_only(a)
    bpy.ops.object.mode_set(mode='EDIT')
    ops.curve_toolkit_perpendicular(length=-2.0, **TOP)
    bpy.ops.object.mode_set(mode='OBJECT')
    p, q = [x.co.xyz for x in a.data.splines[1].points]
    assert (q - Vector((2, 0, 0))).length < TOL          # inwards, along the bisector
    reset()
    a = make("A", [poly([(0, 4, 0), (4, 0, 0), (0, -4, 0)], {1})])
    select_only(a)
    bpy.ops.object.mode_set(mode='EDIT')
    ops.curve_toolkit_perpendicular(length=2.0, **TOP)
    bpy.ops.object.mode_set(mode='OBJECT')
    q = a.data.splines[1].points[1].co.xyz
    assert (q - Vector((6, 0, 0))).length < TOL          # outwards


@test
def perpendicular_on_bezier_is_poly():
    reset()
    d = circle(0, 0, 2)
    d.cyclic = True
    d.points[0].select = True
    a = make("A", [d])
    select_only(a)
    bpy.ops.object.mode_set(mode='EDIT')
    ops.curve_toolkit_perpendicular(length=1.0, **TOP)
    bpy.ops.object.mode_set(mode='OBJECT')
    s = a.data.splines[1]
    assert s.type == 'POLY'
    q = s.points[1].co.xyz
    # Point 0 at (-2, 0) going up (+Y): the left is -X.
    assert (q - Vector((-3, 0, 0))).length < TOL


@test
def handles_object_mode():
    reset()
    a = make("A", [circle(0, 0, 2)])
    select_only(a)
    assert ops.curve_toolkit_handles_to_lines() == {'FINISHED'}
    res = bpy.context.active_object
    assert res.name.startswith("A_Handles")
    assert len(res.data.splines) == 4
    assert all(s.type == 'POLY' and len(s.points) == 3 for s in res.data.splines)


@test
def handles_edit_mode_selection():
    reset()
    d = circle(0, 0, 2)
    d.points[0].select = True                       # point: both handles
    d.points[1].select_right = True                 # one handle only
    a = make("A", [d])
    select_only(a)
    bpy.ops.object.mode_set(mode='EDIT')
    assert ops.curve_toolkit_handles_to_lines() == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    lines = [s for s in a.data.splines if s.type == 'POLY']
    assert sorted(len(s.points) for s in lines) == [2, 3]


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
