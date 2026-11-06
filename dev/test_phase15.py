# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Tests of the Phase 15 changes of Curve Toolkit (Goal, Normal Rotation, Stray
Points at Contact, Circle Inscribed in a Triangle, Circle Tangent to 2
Segments, Select Strays), with
Blender as a Python module:

    python test_phase15.py <folder that contains the etr_curves_toolkit package>

There is no 3D Viewport in background mode, so the tests pass the view
themselves (view, view_normal, view_up), as the button does on its first run.
"""

import math
import sys
import traceback

sys.path.insert(0, sys.argv[1])

import bpy  # noqa: E402
import bmesh  # noqa: E402
from mathutils import Vector  # noqa: E402

import etr_curves_toolkit as toolkit  # noqa: E402
from etr_curves_toolkit import circles  # noqa: E402

toolkit.register()
ops = bpy.ops.etr

TOL = 1e-5

VIEW = {name: dict(view=name, view_normal=n, view_up=u) for name, (n, u) in circles.VIEWS.items()}


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if not hasattr(bpy.types.Scene, "etr_curves_toolkit"):
        toolkit.register()


def mesh_edit(coords, order, location=(0.0, 0.0, 0.0)):
    """Mesh with loose vertices, in Edit Mode, the ones in `order` selected in
    that order (the last one active)."""
    me = bpy.data.meshes.new("M")
    me.from_pydata([tuple(c) for c in coords], [], [])
    obj = bpy.data.objects.new("M", me)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bm = bmesh.from_edit_mesh(me)
    bm.verts.ensure_lookup_table()
    for v in bm.verts:
        v.select = False
    bm.select_history.clear()
    for i in order:
        bm.verts[i].select = True
        bm.select_history.add(bm.verts[i])
    bmesh.update_edit_mesh(me)
    return obj


def curve_edit(splines, active_spline=None):
    """Curve object with Poly splines [(coords, selected indices)], in Edit Mode."""
    cu = bpy.data.curves.new("C", 'CURVE')
    cu.dimensions = '3D'
    for coords, selected in splines:
        s = cu.splines.new('POLY')
        s.points.add(len(coords) - 1)
        for i, (p, co) in enumerate(zip(s.points, coords)):
            p.co = (*co, 1.0)
            p.select = i in selected
    obj = bpy.data.objects.new("C", cu)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    if active_spline is not None:
        cu.splines.active = cu.splines[active_spline]
    bpy.ops.object.mode_set(mode='EDIT')
    return obj


def world_points(obj, spline=-1):
    mw = obj.matrix_world
    s = obj.data.splines[spline]
    return [mw @ bp.co for bp in s.bezier_points], s


def check_circle(pts, center, radius, normal=None):
    for p in pts:
        assert abs((p - Vector(center)).length - radius) < TOL, (p, center, radius)
        if normal is not None:
            assert abs((p - Vector(center)).dot(Vector(normal))) < TOL


def close(a, b, tol=TOL):
    return (Vector(a) - Vector(b)).length < tol


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def result(op, **kw):
    op(**kw, **VIEW['TOP'])
    obj = bpy.context.active_object
    bpy.ops.object.mode_set(mode='OBJECT')
    return obj


def stray_splines(obj):
    # v0.23: helper points are Poly splines of a single point.
    return [s for s in obj.data.splines
            if s.type == 'POLY' and len(s.points) == 1]


# A 3-4-5 right triangle: inradius 1, incenter (1, 1).
TRI = [(0, 0, 0), (4, 0, 0), (0, 3, 0)]


@test
def mesh_toggle_goal():
    reset()
    mesh_edit([(3, 1, 0), (1, 1, 0)], order=[0, 1])        # 1 active: center
    obj = result(ops.curve_toolkit_circle_center_point, toggle_goal=True)
    pts, _ = world_points(obj, 0)
    check_circle(pts, (3, 1, 0), 2.0)                       # now 0 is the center
    assert close(pts[0], (1, 1, 0))


@test
def mesh_goal_three():
    reset()
    mesh_edit([(-3, 5, 0), (4, 5, 0), (1, 1, 0)], order=[0, 1, 2])
    obj = result(ops.curve_toolkit_circle_segment_center, goal='1')  # center (-3, 5)
    pts, _ = world_points(obj, 0)
    # The line through (4, 5) and (1, 1): distance from (-3, 5) is 28 / 5.
    check_circle(pts, (-3, 5, 0), 28 / 5)


@test
def normal_rotation():
    reset()
    mesh_edit([(0, 2, 0), (0, 0, 0)], order=[0, 1])
    obj = result(ops.curve_toolkit_circle_center_point, normal_rotation=math.radians(90))
    pts, _ = world_points(obj, 0)
    assert close(pts[0], (2, 0, 0))                         # clockwise, seen from the top


@test
def inscribed():
    reset()
    mesh_edit(TRI, order=[1, 2, 0])                         # (0, 0) active
    obj = result(ops.curve_toolkit_circle_inscribed, helper_points=True)
    pts, _ = world_points(obj, 0)
    check_circle(pts, (1, 1, 0), 1.0, (0, 0, 1))
    # Starts on the side opposite (0, 0): the hypotenuse.
    assert close(pts[0], (1 + 0.6, 1 + 0.8, 0))
    strays = stray_splines(obj)
    assert len(strays) == 4                                 # 3 contacts + the center
    mw = obj.matrix_world
    contacts = sorted(tuple(round(c, 5) for c in mw @ s.points[0].co.xyz) for s in strays)
    assert contacts == sorted([(1.6, 1.8, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)]), contacts
    assert all(s.type == 'POLY' for s in strays)


@test
def inscribed_goal():
    reset()
    mesh_edit(TRI, order=[1, 2, 0])
    obj = result(ops.curve_toolkit_circle_inscribed, goal='1')   # opposite (4, 0): x = 0
    pts, _ = world_points(obj, 0)
    order = [tuple(round(c, 5) for c in p) for p in (Vector(TRI[1]), Vector(TRI[2]), Vector(TRI[0]))]
    assert order[0] == (4.0, 0.0, 0.0)
    assert close(pts[0], (0, 1, 0)), pts[0]


@test
def tangent_two_default_is_incircle():
    reset()
    mesh_edit(TRI, order=[1, 2, 0])                         # corner (0, 0)
    obj = result(ops.curve_toolkit_circle_tangent_2)
    pts, _ = world_points(obj, 0)
    check_circle(pts, (1, 1, 0), 1.0)


@test
def tangent_two_radius():
    reset()
    mesh_edit(TRI, order=[1, 2, 0])
    obj = result(ops.curve_toolkit_circle_tangent_2, radius=2.0, helper_points=True)
    pts, _ = world_points(obj, 0)
    check_circle(pts, (2, 2, 0), 2.0)
    mw = obj.matrix_world
    contacts = sorted(tuple(round(c, 5) for c in mw @ s.points[0].co.xyz)
                      for s in stray_splines(obj))
    assert contacts == [(0.0, 2.0, 0.0), (2.0, 0.0, 0.0), (2.0, 2.0, 0.0)], contacts


@test
def curve_strays_go_in_the_same_curve():
    reset()
    obj = curve_edit([([TRI[0], TRI[1], TRI[2]], {0, 1, 2})], 0)
    ops.curve_toolkit_circle_inscribed(helper_points=True, **VIEW['TOP'])
    bpy.ops.object.mode_set(mode='OBJECT')
    assert len(obj.data.splines) == 1 + 1 + 4


@test
def select_strays_curve():
    reset()
    obj = curve_edit([([(0, 0, 0), (5, 0, 0)], {0, 1}), ([(9, 9, 0)], set())])
    assert ops.curve_toolkit_select_strays() == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    assert not any(p.select for p in obj.data.splines[0].points)
    assert obj.data.splines[1].points[0].select


@test
def select_strays_mesh():
    reset()
    obj = mesh_edit([(0, 0, 0), (1, 0, 0), (5, 5, 5)], order=[0, 1])
    bpy.ops.object.mode_set(mode='OBJECT')
    obj.data.edges.add(1)
    obj.data.edges[0].vertices = (0, 1)
    bpy.ops.object.mode_set(mode='EDIT')
    ops.curve_toolkit_select_strays()
    bm = bmesh.from_edit_mesh(obj.data)
    assert [v.select for v in bm.verts] == [False, False, True]


@test
def origin_to_selected():
    reset()
    obj = curve_edit([([(0, 0, 0), (4, 2, 0), (6, 0, 0)], {1})])
    bpy.ops.object.mode_set(mode='OBJECT')
    obj.location = (1, 1, 1)
    bpy.context.view_layer.update()
    bpy.ops.object.mode_set(mode='EDIT')
    assert ops.curve_toolkit_origin_to_selected() == {'FINISHED'}
    assert obj.mode == 'EDIT'
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.update()
    assert close(obj.location, (5, 3, 1))
    world = [obj.matrix_world @ p.co.xyz for p in obj.data.splines[0].points]
    assert close(world[0], (1, 1, 1)) and close(world[2], (7, 1, 1))
    assert obj.data.splines[0].points[1].select


@test
def f9_order():
    from unittest import mock
    from etr_curves_toolkit import circles as c
    expected = {
        c.ETR_OT_curve_toolkit_circle_center_point: ["oriented", "toggle_goal", "arc", "angle", "normal_rotation", "view"],
        c.ETR_OT_curve_toolkit_circle_2_points: ["oriented", "toggle_goal", "arc", "angle", "normal_rotation", "helper_points", "view"],
        c.ETR_OT_curve_toolkit_circle_3_points: ["oriented", "goal", "arc", "angle", "normal_rotation", "helper_points"],
        c.ETR_OT_curve_toolkit_circle_segment_center: ["oriented", "goal", "arc", "angle", "normal_rotation", "helper_points", "view"],
        c.ETR_OT_curve_toolkit_circle_inscribed: ["oriented", "goal", "arc", "angle", "normal_rotation", "helper_points"],
        c.ETR_OT_curve_toolkit_circle_tangent_2: ["radius", "oriented", "goal", "arc", "angle", "normal_rotation", "helper_points"],
    }
    for cls, names in expected.items():
        fake = mock.MagicMock()
        fake.count, fake.planar, fake.helpers = cls.count, cls.planar, cls.helpers
        fake.draw_extra = lambda layout, cls=cls: cls.draw_extra(fake, layout)
        cls.draw(fake, None)
        drawn = [call[1][1] for call in fake.layout.mock_calls
                 if call[0].endswith("prop") and len(call[1]) > 1]
        assert drawn == names, (cls.__name__, drawn)


@test
def helper_center_only():
    reset()
    mesh_edit([(0, 4, 0), (0, 0, 0)], order=[0, 1])
    obj = result(ops.curve_toolkit_circle_2_points, helper_points=True)
    strays = stray_splines(obj)
    assert len(strays) == 1
    assert close(obj.matrix_world @ strays[0].points[0].co.xyz, (0, 2, 0))
    reset()
    mesh_edit([(0, 4, 0), (0, 0, 0), (3, 1, 0)], order=[0, 1, 2])
    obj = result(ops.curve_toolkit_circle_segment_center, helper_points=True)
    assert len(stray_splines(obj)) == 1                     # the contact; the center was given


@test
def booleans_with_holes():
    from etr_curves_toolkit import spline_data as sd
    reset()

    def square(x0, y0, x1, y1):
        pts = [sd.PointData(co=c) for c in ((x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0))]
        return sd.SplineData('POLY', pts, True, {})

    def make(name, datas):
        cu = bpy.data.curves.new(name, 'CURVE')
        cu.dimensions = '2D'
        sd.replace_splines(cu, datas)
        o = bpy.data.objects.new(name, cu)
        bpy.context.scene.collection.objects.link(o)
        return o

    a = make("A", [square(0, 0, 10, 10), square(2, 2, 4, 4)])     # a square with a hole
    b = make("B", [square(8, 8, 12, 12)])
    for o in (a, b):
        o.select_set(True)
    bpy.context.view_layer.objects.active = b
    assert ops.curve_toolkit_boolean(operation='UNION') == {'FINISHED'}
    res = bpy.context.active_object
    assert len(res.data.splines) == 2                       # outline + the hole
    bpy.context.view_layer.objects.active = b
    for o in bpy.context.selected_objects:
        o.select_set(False)
    reset()
    a = make("A", [square(0, 0, 10, 10), square(2, 2, 4, 4)])
    b = make("B", [square(3, 3, 6, 6)])
    for o in (a, b):
        o.select_set(True)
    bpy.context.view_layer.objects.active = b
    assert ops.curve_toolkit_boolean(operation='DIFFERENCE') == {'FINISHED'}
    res = bpy.context.active_object
    assert len(res.data.splines) == 2                       # outline + the merged hole


@test
def separate_objects():
    from etr_curves_toolkit import spline_data as sd
    reset()
    cu = bpy.data.curves.new("S", 'CURVE')
    datas = []
    for x in (0, 3, 6):
        datas.append(sd.SplineData('POLY', [sd.PointData(co=(x, 0, 0)), sd.PointData(co=(x + 1, 0, 0))], False, {}))
    sd.replace_splines(cu, datas)
    obj = bpy.data.objects.new("S", cu)
    bpy.context.scene.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    assert ops.curve_toolkit_separate() == {'FINISHED'}
    assert len(obj.data.splines) == 1
    curves = [o for o in bpy.context.scene.objects if o.type == 'CURVE']
    assert len(curves) == 3 and all(len(o.data.splines) == 1 for o in curves)
    assert all(o.select_get() for o in curves)


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
