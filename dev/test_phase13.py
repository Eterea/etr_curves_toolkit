# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Tests of the Phase 13 tools of Curve Toolkit (Circles from Points), with
Blender as a Python module:

    python test_phase13.py <folder that contains the etr_curves_toolkit package>

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


# -----------------------------------------------------------------------------

@test
def mesh_center_point_top():
    reset()
    mesh_edit([(3, 1, 5), (1, 1, 2)], order=[0, 1])        # 1 is the center
    assert ops.curve_toolkit_circle_center_point(**VIEW['TOP']) == {'FINISHED'}
    obj = bpy.context.active_object
    assert obj.type == 'CURVE' and obj.mode == 'EDIT'
    bpy.ops.object.mode_set(mode='OBJECT')
    pts, s = world_points(obj)
    assert s.use_cyclic_u and len(pts) == 4
    check_circle(pts, (1, 1, 2), 2.0, (0, 0, 1))
    assert close(pts[0], (3, 1, 2))                         # starts at the point
    assert close(pts[1], (1, -1, 2))                        # then clockwise
    assert close(obj.location, (1, 1, 2))
    assert all(bp.handle_left_type == 'AUTO' for bp in s.bezier_points)


@test
def mesh_not_oriented():
    reset()
    mesh_edit([(3, 1, 5), (1, 1, 2)], order=[0, 1])
    ops.curve_toolkit_circle_center_point(oriented=False, **VIEW['TOP'])
    obj = bpy.context.active_object
    bpy.ops.object.mode_set(mode='OBJECT')
    pts, _ = world_points(obj)
    assert close(pts[0], (1, 3, 2)) and close(pts[1], (3, 1, 2))


@test
def mesh_front_and_right():
    reset()
    mesh_edit([(2, 7, 3), (0, 1, 0)], order=[0, 1])
    ops.curve_toolkit_circle_center_point(**VIEW['FRONT'])
    obj = bpy.context.active_object
    bpy.ops.object.mode_set(mode='OBJECT')
    pts, _ = world_points(obj)
    r = math.hypot(2, 3)
    check_circle(pts, (0, 1, 0), r, (0, 1, 0))
    assert close(pts[0], (2, 1, 3))
    assert [round(math.degrees(a)) for a in obj.rotation_euler] == [90, 0, 0]
    reset()
    mesh_edit([(5, 0, 2), (1, 0, 0)], order=[0, 1])
    ops.curve_toolkit_circle_center_point(**VIEW['RIGHT'])
    obj = bpy.context.active_object
    bpy.ops.object.mode_set(mode='OBJECT')
    pts, _ = world_points(obj)
    check_circle(pts, (1, 0, 0), 2.0, (1, 0, 0))
    # Local XY holds the circle (Offset and the Booleans want it there).
    assert all(abs(bp.co.z) < TOL for bp in obj.data.splines[0].bezier_points)


@test
def mesh_two_points():
    reset()
    mesh_edit([(0, 4, 9), (0, 0, 1)], order=[0, 1])        # 1 at 6 o'clock
    ops.curve_toolkit_circle_2_points(**VIEW['TOP'])
    obj = bpy.context.active_object
    bpy.ops.object.mode_set(mode='OBJECT')
    pts, _ = world_points(obj)
    check_circle(pts, (0, 2, 1), 2.0)
    assert close(pts[0], (0, 4, 1)) and close(pts[2], (0, 0, 1))


@test
def mesh_three_points():
    reset()
    a, b, c = Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))
    mesh_edit([b, c, a], order=[0, 1, 2])                   # a is active
    ops.curve_toolkit_circle_3_points(**VIEW['TOP'])
    obj = bpy.context.active_object
    bpy.ops.object.mode_set(mode='OBJECT')
    pts, _ = world_points(obj)
    center = (a + b + c) / 3
    check_circle(pts, center, (a - center).length, Vector((1, 1, 1)).normalized())
    assert close(pts[0], a)
    # Clockwise seen from the viewer (+Z side).
    n = Vector((1, 1, 1))
    assert (pts[0] - center).cross(pts[1] - center).dot(n) < 0


@test
def mesh_three_points_collinear():
    reset()
    mesh_edit([(0, 0, 0), (1, 1, 1), (2, 2, 2)], order=[0, 1, 2])
    assert_cancel(lambda: ops.curve_toolkit_circle_3_points(**VIEW['TOP']))


@test
def mesh_segment_center():
    reset()
    mesh_edit([(-3, 5, 0), (4, 5, 0), (1, 1, 3)], order=[0, 1, 2])
    ops.curve_toolkit_circle_segment_center(**VIEW['TOP'])
    obj = bpy.context.active_object
    bpy.ops.object.mode_set(mode='OBJECT')
    pts, _ = world_points(obj)
    check_circle(pts, (1, 1, 3), 4.0)
    assert close(pts[0], (1, 5, 3))


@test
def mesh_segment_center_on_line():
    reset()
    mesh_edit([(-3, 5, 0), (4, 5, 0), (1, 5, 3)], order=[0, 1, 2])
    assert_cancel(lambda: ops.curve_toolkit_circle_segment_center(**VIEW['TOP']))


@test
def arcs():
    reset()
    mesh_edit([(0, 2, 0), (0, 0, 0)], order=[0, 1])
    ops.curve_toolkit_circle_center_point(arc=True, **VIEW['TOP'])
    obj = bpy.context.active_object
    bpy.ops.object.mode_set(mode='OBJECT')
    pts, s = world_points(obj)
    assert not s.use_cyclic_u and len(pts) == 3, (s.use_cyclic_u, len(pts), obj.name, [tuple(p) for p in pts])
    assert obj.name.startswith("Arc")
    assert close(pts[0], (0, 2, 0)) and close(pts[1], (2, 0, 0)) and close(pts[2], (0, -2, 0))
    k = 4 / 3 * math.tan(math.pi / 8) * 2
    bp = s.bezier_points[0]
    assert abs((bp.handle_right - bp.co).length - k) < TOL
    assert abs((bp.handle_left - bp.co).length - k) < TOL          # outer handle
    reset()
    mesh_edit([(0, 2, 0), (0, 0, 0)], order=[0, 1])
    ops.curve_toolkit_circle_center_point(arc=True, angle=math.radians(-135), **VIEW['TOP'])
    obj = bpy.context.active_object
    bpy.ops.object.mode_set(mode='OBJECT')
    pts, s = world_points(obj)
    assert len(pts) == 3 and pts[1].x < 0                           # counter-clockwise
    end = Vector((2 * math.sin(math.radians(-135)), 2 * math.cos(math.radians(-135)), 0))
    assert close(pts[-1], end)
    reset()
    mesh_edit([(0, 2, 0), (0, 0, 0)], order=[0, 1])
    ops.curve_toolkit_circle_center_point(arc=True, angle=2 * math.pi, **VIEW['TOP'])
    obj = bpy.context.active_object
    assert obj.data.splines[0].use_cyclic_u


@test
def wrong_count():
    reset()
    mesh_edit([(0, 0, 0), (1, 0, 0), (2, 1, 0)], order=[0, 1, 2])
    assert_cancel(lambda: ops.curve_toolkit_circle_center_point(**VIEW['TOP']))


@test
def curve_active_from_spline():
    reset()
    # Point of spline 0 and point of spline 1; spline 1 is active -> center.
    obj = curve_edit([([(4, 0, 0), (9, 9, 0)], {0}), ([(1, 0, 0), (7, 7, 0)], {0})], 1)
    ops.curve_toolkit_circle_center_point(**VIEW['TOP'])
    assert bpy.context.active_object == obj and obj.mode == 'EDIT'
    bpy.ops.object.mode_set(mode='OBJECT')
    assert len(obj.data.splines) == 3
    pts, s = world_points(obj)
    check_circle(pts, (1, 0, 0), 3.0)
    assert all(bp.select_control_point for bp in s.bezier_points)
    assert not any(p.select for p in obj.data.splines[0].points)


@test
def curve_guessed_and_picked():
    reset()
    # Both points in one spline: the last one by index is taken as the center.
    obj = curve_edit([([(4, 0, 0), (1, 0, 0)], {0, 1})], 0)
    ops.curve_toolkit_circle_center_point(**VIEW['TOP'])
    bpy.ops.object.mode_set(mode='OBJECT')
    pts, _ = world_points(obj)
    check_circle(pts, (1, 0, 0), 3.0)
    reset()
    obj = curve_edit([([(4, 0, 0), (1, 0, 0)], {0, 1})], 0)
    ops.curve_toolkit_circle_center_point(toggle_goal=True, **VIEW['TOP'])
    bpy.ops.object.mode_set(mode='OBJECT')
    pts, _ = world_points(obj)
    check_circle(pts, (4, 0, 0), 3.0)


@test
def curve_local_space():
    reset()
    obj = curve_edit([([(2, 0, 0)], {0}), ([(0, 0, 0)], {0})], 1)
    bpy.ops.object.mode_set(mode='OBJECT')
    obj.location = (10, 0, 0)
    obj.scale = (2, 2, 2)
    bpy.context.view_layer.update()
    obj.data.splines.active = obj.data.splines[1]
    bpy.ops.object.mode_set(mode='EDIT')
    ops.curve_toolkit_circle_center_point(**VIEW['TOP'])
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.update()
    pts, _ = world_points(obj)
    check_circle(pts, (10, 0, 0), 4.0)


@test
def disabled_in_object_mode():
    reset()
    mesh_edit([(0, 0, 0), (1, 0, 0)], order=[0, 1])
    bpy.ops.object.mode_set(mode='OBJECT')
    assert not ops.curve_toolkit_circle_center_point.poll()


@test
def panel_second_row():
    from unittest import mock
    from etr_curves_toolkit import panel
    reset()
    assert panel.ETR_PT_curve_toolkit_primitives.bl_label == "Create Curves"
    fake = mock.MagicMock()
    ctx = mock.MagicMock()
    ctx.scene = bpy.context.scene
    panel.ETR_PT_curve_toolkit_primitives.draw(fake, ctx)
    drawn = [c[1][0] for c in fake.layout.mock_calls if c[0].endswith("operator") and c[1]]
    assert drawn[5:] == [
        "etr.curve_toolkit_circle_center_point", "etr.curve_toolkit_circle_2_points",
        "etr.curve_toolkit_circle_3_points", "etr.curve_toolkit_circle_inscribed",
        "etr.curve_toolkit_circle_tangent_2",
        "etr.curve_toolkit_circle_segment_center", "etr.curve_toolkit_tangents_2_circles",
        "etr.curve_toolkit_tangents_from_point", "etr.curve_toolkit_perpendicular",
        "etr.curve_toolkit_lines_from_points", "etr.curve_toolkit_points_in_between",
        "etr.curve_toolkit_points_along_curve",
        "etr.curve_toolkit_points_at_intersections"], drawn   # layout of v0.22.0


def assert_cancel(call):
    try:
        result = call()
    except RuntimeError:
        return
    assert result == {'CANCELLED'}, result


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
