# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Tests of the Phase 26 changes of Curve Toolkit (v0.26.0): Booleans & Splits
in Edit Mode (Backup Splines in Edit Mode, Sources collection hidden in the
viewport), Toggle Goal of the Difference, the new names of the results, Select
All by Type without the stray points, 2D / 3D, Tangents from Point with
Connect & Close and the Capable Arc of Circle from 3 Points. With Blender as a
Python module:

    python test_phase26.py <folder that contains the etr_curves_toolkit package>
"""

import math
import sys
import traceback

sys.path.insert(0, sys.argv[1])

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

import etr_curves_toolkit as toolkit  # noqa: E402
from etr_curves_toolkit import context_utils as cu  # noqa: E402

toolkit.register()
ops = bpy.ops.etr
TOL = 1e-4


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if not hasattr(bpy.types.Scene, "etr_curves_toolkit"):
        toolkit.register()


def close(a, b, tol=TOL):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def make(name, splines, dims='2D', select=True, active=None):
    """splines: [(kind, points (x, y[, z]), cyclic, selected indices)], Poly
    or Bezier with Vector handles."""
    data = bpy.data.curves.new(name, 'CURVE')
    data.dimensions = dims
    for kind, pts, cyclic, sel in splines:
        s = data.splines.new(kind)
        pts = [(p[0], p[1], p[2] if len(p) > 2 else 0.0) for p in pts]
        if kind == 'BEZIER':
            s.bezier_points.add(len(pts) - 1)
            for k, (bp, p) in enumerate(zip(s.bezier_points, pts)):
                bp.co = p
                bp.handle_left_type = bp.handle_right_type = 'VECTOR'
                bp.select_control_point = k in sel
        else:
            s.points.add(len(pts) - 1)
            for k, (sp, p) in enumerate(zip(s.points, pts)):
                sp.co = (*p, 1.0)
                sp.select = k in sel
        s.use_cyclic_u = cyclic
    if active is not None:
        data.splines.active = data.splines[active]
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    if select:
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
    return obj


def square(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def edit(obj):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')


def object_mode():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


def run(op, **kw):
    try:
        return op(**kw)
    except RuntimeError:
        return {'CANCELLED'}


def selected(spline):
    pts = spline.bezier_points if spline.type == 'BEZIER' else spline.points
    return any(p.select_control_point if spline.type == 'BEZIER' else p.select for p in pts)


def area(spline):
    pts = [p.co.xyz for p in (spline.bezier_points if spline.type == 'BEZIER' else spline.points)]
    return abs(sum(a.x * b.y - b.x * a.y for a, b in zip(pts, pts[1:] + pts[:1]))) / 2.0


def settings():
    return bpy.context.scene.etr_curves_toolkit


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# -----------------------------------------------------------------------------
# Booleans in Edit Mode
# -----------------------------------------------------------------------------

@test
def union_in_edit_mode_without_backup():
    reset()
    obj = make("C", [('POLY', square(0, 0, 2, 2), True, (0,)),
                     ('POLY', square(1, 1, 3, 3), True, (2,)),
                     ('POLY', square(10, 0, 11, 1), True, ())])
    edit(obj)
    assert ops.curve_toolkit_boolean_union() == {'FINISHED'}
    assert bpy.context.mode == 'EDIT_CURVE' and bpy.context.active_object == obj
    object_mode()
    splines = list(obj.data.splines)
    assert len(splines) == 2
    assert not selected(splines[0]) and abs(area(splines[0]) - 1.0) < TOL   # left alone
    assert selected(splines[1]) and abs(area(splines[1]) - 7.0) < TOL       # the union
    assert not any(o.name.startswith("Backup_") for o in bpy.data.objects)
    assert len(bpy.data.objects) == 1


@test
def union_in_edit_mode_with_backup_and_collection():
    reset()
    settings().backup_in_edit = True
    settings().sources_in_collection = True
    settings().results_in_collection = True       # does not apply in Edit Mode
    obj = make("C", [('POLY', square(0, 0, 2, 2), True, (0,)),
                     ('POLY', square(1, 1, 3, 3), True, (0,))])
    edit(obj)
    assert ops.curve_toolkit_boolean_union() == {'FINISHED'}
    assert bpy.context.mode == 'EDIT_CURVE' and bpy.context.active_object == obj
    object_mode()
    backup = bpy.data.objects["Backup_C"]
    assert len(backup.data.splines) == 2
    src = bpy.data.collections["Curve Boolean Sources"]
    assert list(src.objects) == [backup]
    lc = cu.layer_collection(bpy.context.view_layer, src)
    assert lc.hide_viewport and not lc.exclude
    assert "Curve Boolean Results" not in bpy.data.collections
    assert len(obj.data.splines) == 1 and obj.users_collection[0] == bpy.context.scene.collection


@test
def edit_mode_booleans_refuse_open_splines():
    reset()
    obj = make("C", [('POLY', square(0, 0, 2, 2), True, (0,)),
                     ('POLY', [(0, 0), (5, 5)], False, (1,))])
    edit(obj)
    assert run(ops.curve_toolkit_boolean_union) == {'CANCELLED'}
    assert bpy.context.mode == 'EDIT_CURVE'
    object_mode()
    assert len(obj.data.splines) == 2


@test
def edit_mode_intersection_needs_two():
    reset()
    obj = make("C", [('POLY', square(0, 0, 2, 2), True, (0,)),
                     ('POLY', square(1, 1, 3, 3), True, (0,)),
                     ('POLY', square(1, 0, 3, 1), True, (0,))])
    edit(obj)
    assert run(ops.curve_toolkit_boolean_intersection) == {'CANCELLED'}
    object_mode()
    assert len(obj.data.splines) == 3


@test
def edit_mode_difference_active_spline_and_toggle_goal():
    # The active spline (1, the big one) bites the small one: nothing is left
    # of it, so the result is empty, and Toggle Goal swaps them.
    reset()
    obj = make("C", [('POLY', square(1, 1, 2, 2), True, (0,)),
                     ('POLY', square(0, 0, 3, 3), True, (0,))], active=1)
    edit(obj)
    assert ops.curve_toolkit_boolean_difference() == {'FINISHED'}     # empty, F9 open
    object_mode()
    assert len(obj.data.splines) == 2
    edit(obj)
    assert ops.curve_toolkit_boolean_difference(toggle_goal=True) == {'FINISHED'}
    object_mode()
    # The big one bitten by the small one: a square with a hole.
    assert len(obj.data.splines) == 2
    assert sorted(round(area(s), 4) for s in obj.data.splines) == [1.0, 9.0]
    assert all(selected(s) for s in obj.data.splines)
    # With no active spline among them, the first one bites.
    reset()
    obj = make("C", [('POLY', square(0, 0, 2, 2), True, (0,)),
                     ('POLY', square(1, 0, 3, 2), True, (0,))])
    obj.data.splines.active = None
    edit(obj)
    assert ops.curve_toolkit_boolean_difference() == {'FINISHED'}
    object_mode()
    assert len(obj.data.splines) == 1
    xs = sorted(p.co.x for p in obj.data.splines[0].points)
    assert close((xs[0], xs[-1]), (2, 3))


@test
def edit_mode_needs_one_curve():
    reset()
    a = make("A", [('POLY', square(0, 0, 2, 2), True, (0,))])
    b = make("B", [('POLY', square(1, 1, 3, 3), True, (0,))])
    a.select_set(True)
    edit(b)
    assert run(ops.curve_toolkit_boolean_union) == {'CANCELLED'}


# -----------------------------------------------------------------------------
# Booleans in Object Mode: names, Toggle Goal, the sources collection
# -----------------------------------------------------------------------------

@test
def object_mode_names_and_toggle_goal():
    reset()
    a = make("A", [('POLY', square(0, 0, 2, 2), True, ())])
    b = make("B", [('POLY', square(1, 0, 3, 2), True, ())])
    for o in (a, b):
        o.select_set(True)
    bpy.context.view_layer.objects.active = b
    assert ops.curve_toolkit_boolean_difference() == {'FINISHED'}
    r = bpy.context.active_object
    assert r.name == "Bool_Diff_01" and r.data.name == "Bool_Diff_01"
    xs = sorted(p.co.x for p in r.data.splines[0].points)
    assert close((xs[0], xs[-1]), (0, 1))                 # B (active) bit A
    reset()
    a = make("A", [('POLY', square(0, 0, 2, 2), True, ())])
    b = make("B", [('POLY', square(1, 0, 3, 2), True, ())])
    for o in (a, b):
        o.select_set(True)
    bpy.context.view_layer.objects.active = b
    assert ops.curve_toolkit_boolean_difference(toggle_goal=True) == {'FINISHED'}
    xs = sorted(p.co.x for p in bpy.context.active_object.data.splines[0].points)
    assert close((xs[0], xs[-1]), (2, 3))                 # A bit B
    # Union and Intersection, numbered in series.
    for name in ("Bool_Union_01", "Bool_Union_02"):
        c = make("C", [('POLY', square(5, 5, 6, 6), True, ())])
        d = make("D", [('POLY', square(5.5, 5, 7, 6), True, ())])
        for o in bpy.context.scene.objects:
            o.select_set(o in (c, d))
        assert ops.curve_toolkit_boolean_union() == {'FINISHED'}
        assert bpy.context.active_object.name == name
    c = make("E", [('POLY', square(5, 5, 6, 6), True, ())])
    d = make("F", [('POLY', square(5.5, 5, 7, 6), True, ())])
    for o in bpy.context.scene.objects:
        o.select_set(o in (c, d))
    assert ops.curve_toolkit_boolean_intersection() == {'FINISHED'}
    assert bpy.context.active_object.name == "Bool_Inter_01"


@test
def tooltips_and_labels():
    from etr_curves_toolkit import booleans as bl, symmetrize
    assert bl.ETR_OT_curve_toolkit_boolean_union.bl_label == "Union"
    assert bl.ETR_OT_curve_toolkit_boolean_intersection.bl_label == "Intersection"
    assert bl.ETR_OT_curve_toolkit_boolean_difference.bl_label == "Difference"
    assert symmetrize.ETR_OT_curve_toolkit_symmetrize.bl_label == "Symmetrize Split"


@test
def object_mode_sources_hidden_not_excluded():
    reset()
    settings().sources_in_collection = True
    a = make("A", [('POLY', [(0, 0), (4, 0)], False, ())])
    b = make("B", [('POLY', [(2, -1), (2, 1)], False, ())])
    for o in (a, b):
        o.select_set(True)
    assert ops.curve_toolkit_split_all() == {'FINISHED'}
    src = bpy.data.collections["Curve Boolean Sources"]
    lc = cu.layer_collection(bpy.context.view_layer, src)
    assert lc.hide_viewport and not lc.exclude
    assert not a.hide_get() and not b.hide_get()        # the collection hides them
    names = sorted(o.name for o in bpy.data.objects if o.name.startswith("Split_"))
    assert names == ["Split_01", "Split_02", "Split_03", "Split_04"]


# -----------------------------------------------------------------------------
# Splits in Edit Mode
# -----------------------------------------------------------------------------

@test
def split_active_in_edit_mode_with_goal():
    reset()
    obj = make("C", [('POLY', [(0, 0), (4, 0)], False, (0,)),
                     ('POLY', [(2, -1), (2, 1)], False, (0,)),
                     ('POLY', [(0, 5), (4, 5)], False, ())], active=1)
    edit(obj)
    # The active spline (1) is the Goal: it is cut by the other one.
    assert ops.curve_toolkit_split() == {'FINISHED'}
    object_mode()
    splines = list(obj.data.splines)
    assert len(splines) == 4
    cut = [s for s in splines if selected(s)]
    assert len(cut) == 2 and all(abs(p.co.x - 2) < TOL for s in cut for p in s.points)
    # Goal 0: the horizontal line is cut instead.
    reset()
    obj = make("C", [('POLY', [(0, 0), (4, 0)], False, (0,)),
                     ('POLY', [(2, -1), (2, 1)], False, (0,))], active=1)
    edit(obj)
    assert ops.curve_toolkit_split(goal=0) == {'FINISHED'}
    object_mode()
    cut = [s for s in obj.data.splines if selected(s)]
    assert len(cut) == 2 and all(abs(p.co.y) < TOL for s in cut for p in s.points)


@test
def split_active_goal_has_a_hard_limit():
    reset()
    obj = make("C", [('POLY', [(0, 0), (4, 0)], False, (0,)),
                     ('POLY', [(2, -1), (2, 1)], False, (0,)),
                     ('POLY', [(3, -1), (3, 1)], False, (0,))])
    edit(obj)
    assert ops.curve_toolkit_split(goal=7) == {'FINISHED'}
    object_mode()
    # Goal 7 with 3 splines is the last one (2): the line at x = 3 is cut.
    cut = [s for s in obj.data.splines if selected(s)]
    assert len(cut) == 2 and all(abs(p.co.x - 3) < TOL for s in cut for p in s.points)


@test
def split_active_in_edit_mode_not_crossed_finishes():
    reset()
    obj = make("C", [('POLY', [(0, 0), (4, 0)], False, (0,)),
                     ('POLY', [(0, 2), (4, 2)], False, (0,))])
    edit(obj)
    assert ops.curve_toolkit_split() == {'FINISHED'}     # nothing, F9 stays open
    object_mode()
    assert len(obj.data.splines) == 2


@test
def split_all_in_edit_mode_with_backup():
    reset()
    settings().backup_in_edit = True
    obj = make("C", [('POLY', [(0, 0), (4, 0)], False, (0,)),
                     ('POLY', [(2, -1), (2, 1)], False, (0,))])
    edit(obj)
    assert ops.curve_toolkit_split_all() == {'FINISHED'}
    object_mode()
    assert len(obj.data.splines) == 4 and all(selected(s) for s in obj.data.splines)
    backup = bpy.data.objects["Backup_C"]
    assert len(backup.data.splines) == 2 and backup.hide_get()
    assert not any(p.select for s in backup.data.splines for p in s.points)


@test
def split_at_control_points_in_edit_mode():
    reset()
    obj = make("C", [('POLY', [(0, 0), (1, 0), (2, 0), (3, 0)], False, (1,)),
                     ('POLY', [(0, 5), (3, 5)], False, ())])
    edit(obj)
    assert ops.curve_toolkit_split_at_points() == {'FINISHED'}
    assert bpy.context.mode == 'EDIT_CURVE'
    object_mode()
    assert [len(s.points) for s in obj.data.splines] == [2, 2, 3]
    assert [selected(s) for s in obj.data.splines] == [False, True, True]
    assert len(bpy.data.objects) == 1


@test
def symmetrize_split_in_edit_mode():
    reset()
    obj = make("C", [('POLY', [(-3, 1), (1, 1)], False, (0,)),
                     ('POLY', [(-3, 5), (-1, 5)], False, ())])
    edit(obj)
    assert ops.curve_toolkit_symmetrize(view='TOP') == {'FINISHED'}
    object_mode()
    splines = list(obj.data.splines)
    assert len(splines) == 2 and not selected(splines[0])
    xs = sorted(round(p.co.x, 4) for p in splines[1].points)
    assert xs == [-3, 0, 3], xs
    assert not any(o.name.startswith("Sym") for o in bpy.data.objects)
    # Object Mode names its results Sym_01...
    reset()
    make("D", [('POLY', [(-3, 1), (1, 1)], False, ())])
    assert ops.curve_toolkit_symmetrize(view='TOP') == {'FINISHED'}
    assert bpy.context.active_object.name == "Sym_01"


@test
def symmetrize_overlapping_splines_around_their_origin():
    # Two overlapping circles, the mirror axis through the origin of the
    # object, crossing one of them: each closed spline is mirrored on its own.
    import math as m
    reset()
    k = 0.5522847498

    def circle(cx, cy):
        return [(cx + m.cos(a), cy + m.sin(a)) for a in (m.pi / 2, 0, -m.pi / 2, m.pi)]
    from etr_curves_toolkit import spline_data as sd, symmetrize as sy
    for ox, oy in ((1.2, 2.17), (2.198, 0.94), (1.75, 0.31), (2.5, 2.1)):
        datas = []
        for cx, cy in ((1.80, 1.86), (2.44, 1.32)):
            pts = []
            for i, (x, y) in enumerate(circle(cx - ox, cy - oy)):
                a = m.pi / 2 - i * m.pi / 2
                tx, ty = m.sin(a) * k, -m.cos(a) * k
                pts.append(sd.PointData(co=(x, y, 0), hl=(x - tx, y - ty, 0),
                                        hr=(x + tx, y + ty, 0), hlt='ALIGNED', hrt='ALIGNED'))
            datas.append(sd.SplineData('BEZIER', pts, True, {}))
        o = make("C", [('POLY', [(0, 0), (1, 0)], False, ())])
        o.location = (ox, oy, 0)
        frame = sy.Frame('TOP', 'RIGHT_TO_LEFT', (ox, oy, 0))
        res = sy.symmetrize_object(o, frame, datas)
        xs = [p.co[0] for d in res for p in d.points]
        # Everything right of the axis is kept (circle 2 reaches 3.44), and
        # mirrored onto the left.
        assert abs(max(xs) - (3.44 - ox)) < 1e-3 and abs(min(xs) + (3.44 - ox)) < 1e-3, (ox, oy)
        bpy.data.objects.remove(o)


@test
def tangents_shapes_take_booleans():
    # The closed shapes of Tangents to 2 Circles share points with the
    # circles: they must still take every Boolean with them.
    reset()
    for loc, r in (((0, 0, 0), 2), ((6, 1, 0), 1)):
        bpy.ops.curve.primitive_bezier_circle_add(radius=r, location=loc)
    a, b = sorted(bpy.context.scene.objects, key=lambda o: o.location.x)
    for o in bpy.context.scene.objects:
        o.select_set(True)
    assert ops.curve_toolkit_tangents_2_circles(connect_close=True, crossing=True) == {'FINISHED'}
    t = bpy.context.active_object
    for o in bpy.context.scene.objects:
        o.select_set(o is t)
    bpy.ops.object.mode_set(mode='EDIT')
    ops.curve_toolkit_separate()
    object_mode()
    shapes = sorted((o for o in bpy.context.scene.objects if o.name.startswith("Tangents")),
                    key=lambda o: len(o.data.splines[0].bezier_points), reverse=True)
    trapezoid, tri_1, tri_2 = shapes[0], *sorted(shapes[1:], key=lambda o: o.matrix_world.translation.x
                                                  + sum(p.co.x for p in o.data.splines[0].bezier_points))
    for pair in ((a, trapezoid), (b, trapezoid), (a, tri_1), (b, tri_2)):
        for op in (ops.curve_toolkit_boolean_union, ops.curve_toolkit_boolean_intersection,
                   ops.curve_toolkit_boolean_difference):
            for o in bpy.context.scene.objects:
                o.hide_set(False)
                o.select_set(o in pair)
            bpy.context.view_layer.objects.active = pair[1]
            n = len(bpy.data.objects)
            assert op() == {'FINISHED'}, (pair, op)
            assert len(bpy.data.objects) == n + 1, (pair, op)
    # All three at once, too.
    for o in bpy.context.scene.objects:
        o.hide_set(False)
        o.select_set(o in (a, b, trapezoid))
    bpy.context.view_layer.objects.active = trapezoid
    assert ops.curve_toolkit_boolean_union() == {'FINISHED'}
    assert len(bpy.context.active_object.data.splines) == 1


# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------

@test
def select_by_type_leaves_the_strays_out():
    reset()
    obj = make("C", [('POLY', [(0, 0), (4, 0)], False, ()),
                     ('POLY', [(2, 2)], False, ()),
                     ('BEZIER', [(0, 3), (4, 3)], False, ()),
                     ('BEZIER', [(9, 9)], False, ())])
    edit(obj)
    ops.curve_toolkit_select_by_type(kind='POLY')
    object_mode()
    assert [selected(s) for s in obj.data.splines] == [True, False, False, False]
    edit(obj)
    ops.curve_toolkit_select_by_type(kind='BEZIER')
    object_mode()
    assert [selected(s) for s in obj.data.splines] == [False, False, True, False]
    edit(obj)
    ops.curve_toolkit_select_by_type(kind='STRAYS')
    object_mode()
    assert [selected(s) for s in obj.data.splines] == [False, True, False, True]


@test
def set_dimensions():
    reset()
    a = make("A", [('POLY', [(0, 0), (1, 0)], False, ())], dims='3D')
    b = make("B", [('POLY', [(0, 0), (1, 0)], False, ())], dims='3D')
    a.select_set(True)
    assert ops.curve_toolkit_set_dimensions(dimensions='2D') == {'FINISHED'}
    assert a.data.dimensions == b.data.dimensions == '2D'
    edit(b)
    assert ops.curve_toolkit_set_dimensions(dimensions='3D') == {'FINISHED'}
    object_mode()
    assert a.data.dimensions == b.data.dimensions == '3D'


@test
def unique_names_use_an_underscore():
    reset()
    assert cu.unique_name("Tangents") == "Tangents"
    assert cu.unique_name("Split", numbered=True) == "Split_01"
    make("Tangents", [('POLY', [(0, 0), (1, 0)], False, ())])
    assert cu.unique_name("Tangents") == "Tangents_01"
    bpy.data.curves.new("Tangents_01", 'CURVE')            # taken by a curve
    assert cu.unique_name("Tangents") == "Tangents_02"


# -----------------------------------------------------------------------------
# Create Curves
# -----------------------------------------------------------------------------

@test
def tangents_from_point_connect_and_close():
    reset()
    k = 0.5522847498
    circle = []
    for a in range(4):
        t = a * math.pi / 2
        c = (math.cos(t), math.sin(t))
        tg = (-math.sin(t) * k, math.cos(t) * k)
        circle.append((c, tg))
    data = bpy.data.curves.new("C", 'CURVE')
    s = data.splines.new('BEZIER')
    s.bezier_points.add(3)
    for bp, (c, tg) in zip(s.bezier_points, circle):
        bp.handle_left_type = bp.handle_right_type = 'FREE'
        bp.co = (*c, 0)
        bp.handle_left = (c[0] - tg[0], c[1] - tg[1], 0)
        bp.handle_right = (c[0] + tg[0], c[1] + tg[1], 0)
        bp.select_control_point = True
    s.use_cyclic_u = True
    p = data.splines.new('POLY')
    p.points[0].co = (3, 0, 0, 1)
    p.points[0].select = True
    obj = bpy.data.objects.new("C", data)
    bpy.context.scene.collection.objects.link(obj)
    obj.select_set(True)
    edit(obj)
    assert ops.curve_toolkit_tangents_from_point(connect_close=True) == {'FINISHED'}
    object_mode()
    tri = obj.data.splines[-1]
    assert len(obj.data.splines) == 3 and tri.type == 'POLY' and tri.use_cyclic_u
    pts = [q.co.xyz for q in tri.points]
    assert close(pts[0], (3, 0, 0))
    for q in pts[1:]:
        assert abs(q.length - 1) < 1e-3 and abs(q.dot(q - Vector((3, 0, 0)))) < 1e-3


@test
def capable_arc():
    reset()
    bpy.ops.mesh.primitive_plane_add()
    bpy.ops.object.mode_set(mode='EDIT')
    import bmesh
    obj = bpy.context.active_object
    bm = bmesh.from_edit_mesh(obj.data)
    for v in list(bm.verts):
        bm.verts.remove(v)
    # On the unit circle: A at 90, B at 0, C at -90 degrees (picked in order).
    vs = [bm.verts.new(co) for co in ((0, 1, 0), (1, 0, 0), (0, -1, 0))]
    for v in vs:
        v.select = True
        bm.select_history.add(v)
    bmesh.update_edit_mesh(obj.data)
    assert ops.curve_toolkit_circle_3_points(arc=True, capable_arc=True,
                                             angle=0.3, normal_rotation=1.0) == {'FINISHED'}
    arc = bpy.context.active_object
    s = arc.data.splines[0]
    mw = arc.matrix_world
    pts = [mw @ p.co for p in s.bezier_points]
    assert not s.use_cyclic_u
    assert close(pts[0], (0, 1, 0)) and close(pts[-1], (0, -1, 0)), pts
    # It goes through B (1, 0, 0), the right half, whatever Angle says.
    assert all(p.x > -TOL for p in pts)
    assert any(close(p, (1, 0, 0)) for p in pts)


@test
def panel_booleans_and_utilities():
    from unittest import mock
    from etr_curves_toolkit import panel
    assert panel.ETR_PT_curve_toolkit_booleans.bl_label == "Booleans & Splits"
    for mode in ('OBJECT', 'EDIT_CURVE'):
        reset()
        fake, ctx = mock.MagicMock(), mock.MagicMock()
        ctx.scene, ctx.mode = bpy.context.scene, mode
        panel.ETR_PT_curve_toolkit_booleans.draw(fake, ctx)
        props = [c[1][1] for c in fake.mock_calls if c[0].endswith(".prop")]
        assert props == ["backup_in_edit", "sources_in_collection", "results_in_collection"]
        ops_drawn = [c[1][1] if len(c[1]) > 1 else c[1][0] for c in fake.mock_calls
                     if c[0].endswith("operator") and c[1]]
        assert any("boolean_union" in str(o) for o in ops_drawn), ops_drawn


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
