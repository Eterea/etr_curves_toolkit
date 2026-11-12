# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Tests of the Phase 20 changes of Curve Toolkit (v0.20.0): Split All with
self-crossings and without an active object, Offset > Duplicate and its
Aligned handles, the Select All by Type menu, and the Sources collection
excluded from the View Layer. With Blender as a Python module:

    python test_phase18.py <folder that contains the etr_curves_toolkit package>
"""

import math
import sys
import traceback

sys.path.insert(0, sys.argv[1])

import bpy  # noqa: E402
import bmesh  # noqa: E402
from mathutils import Vector  # noqa: E402

import etr_curves_toolkit as toolkit  # noqa: E402
from etr_curves_toolkit.context_utils import layer_collection  # noqa: E402

toolkit.register()
ops = bpy.ops.etr
TOL = 1e-5


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if not hasattr(bpy.types.Scene, "etr_curves_toolkit"):
        toolkit.register()


def curve(name, splines, dims='2D'):
    """splines: [(kind, points, cyclic)]; a Bezier point is (co,) for Auto
    handles or (co, left, right) for Free ones (2D tuples)."""
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = dims
    for kind, pts, cyclic in splines:
        s = cu.splines.new(kind)
        if kind == 'BEZIER':
            s.bezier_points.add(len(pts) - 1)
            for bp, p in zip(s.bezier_points, pts):
                bp.co = (*p[0], 0)
                if len(p) == 3:
                    bp.handle_left_type = bp.handle_right_type = 'FREE'
                    bp.handle_left = (*p[1], 0)
                    bp.handle_right = (*p[2], 0)
                else:
                    bp.handle_left_type = bp.handle_right_type = 'AUTO'
        else:
            s.points.add(len(pts) - 1)
            for sp, p in zip(s.points, pts):
                sp.co = (p[0], p[1], 0, 1)
        s.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def select(objs, active=None):
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active


def pieces():
    return [o for o in bpy.data.objects if o.name.startswith("Split_")]


def figure_eight(n):
    return [(math.sin(2 * math.pi * i / n), 0.5 * math.sin(4 * math.pi * i / n)) for i in range(n)]


def run(call, **kwargs):
    try:
        return call(**kwargs)
    except RuntimeError:
        return {'CANCELLED'}


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# -----------------------------------------------------------------------------
# Split All
# -----------------------------------------------------------------------------

@test
def split_all_one_looping_curve_without_active():
    for n in (40, 41):          # crossing on a control point, and between them
        reset()
        o = curve("Eight", [('POLY', figure_eight(n), True)])
        select([o], None)
        assert ops.curve_toolkit_split_all.poll()
        assert not ops.curve_toolkit_split.poll()
        assert ops.curve_toolkit_split_all() == {'FINISHED'}
        got = pieces()
        assert len(got) == 2, (n, len(got))
        for p in got:
            pts = [v.co.xyz for v in p.data.splines[0].points]
            # Each lobe starts and ends at the crossing, the origin.
            assert pts[0].length < 1e-4 and pts[-1].length < 1e-4, n


@test
def split_all_four_loops_bezier():
    reset()
    pts = [((math.cos(t) + 0.9 * math.cos(3 * t), math.sin(t) - 0.9 * math.sin(3 * t)),)
           for t in (2 * math.pi * i / 32 for i in range(32))]
    o = curve("Rose", [('BEZIER', pts, True)])
    select([o], None)
    assert ops.curve_toolkit_split_all() == {'FINISHED'}
    assert len(pieces()) == 8, len(pieces())


@test
def split_all_loop_inside_one_cubic():
    reset()
    o = curve("Loop", [('BEZIER', [((0, 0), (-1, 0), (3, 2)), ((1, 0), (-2, 2), (2, 0))], False)])
    select([o], o)
    assert ops.curve_toolkit_split_all() == {'FINISHED'}
    assert len(pieces()) == 3


@test
def split_all_no_crossing_warns():
    reset()
    o = curve("Sq", [('POLY', [(0, 0), (1, 0), (1, 1), (0, 1)], True)])
    select([o], None)
    assert run(ops.curve_toolkit_split_all) == {'CANCELLED'}
    assert not pieces()


@test
def split_all_box_selection_without_active():
    reset()
    a = curve("A", [('POLY', [(0, 0), (4, 0)], False)])
    b = curve("B", [('POLY', [(1, -1), (1, 1)], False)])
    select([a, b], None)
    assert ops.curve_toolkit_split_all() == {'FINISHED'}
    assert len(pieces()) == 4
    # Split Active still needs the active object.
    reset()
    a = curve("A", [('POLY', [(0, 0), (4, 0)], False)])
    b = curve("B", [('POLY', [(1, -1), (1, 1)], False)])
    select([a, b], None)
    assert run(ops.curve_toolkit_split, mode='ACTIVE') == {'CANCELLED'}


@test
def split_all_cuts_splines_of_the_same_curve():
    reset()
    o = curve("Two", [('POLY', [(0, 0), (4, 0)], False), ('POLY', [(1, -1), (1, 1)], False)])
    select([o], o)
    assert ops.curve_toolkit_split_all() == {'FINISHED'}
    assert len(pieces()) == 4


@test
def split_active_keeps_its_behaviour():
    reset()
    a = curve("A", [('POLY', figure_eight(41), True)])
    b = curve("B", [('POLY', [(-2, 0.9), (2, 0.9)], False)])
    select([a, b], a)
    # The line does not touch the eight, and Split Active does not cut loops.
    assert run(ops.curve_toolkit_split, mode='ACTIVE') == {'CANCELLED'}


# -----------------------------------------------------------------------------
# Offset
# -----------------------------------------------------------------------------

def s_curve():
    return curve("S", [('BEZIER', [((-4, 0), (-5, -1), (-3, 1)),
                                   ((0, 1), (-1.5, 1.2), (1.5, 0.8)),
                                   ((4, 0), (2, 0), (6, 0))], False)])


def _collinear_opposite(bp):
    a = (bp.handle_left - bp.co).normalized()
    b = (bp.handle_right - bp.co).normalized()
    return a.dot(b) < -1 + 1e-6


@test
def offset_open_ends_are_aligned():
    reset()
    o = s_curve()
    select([o], o)
    assert ops.curve_toolkit_offset(distance=0.5) == {'FINISHED'}
    r = bpy.context.active_object
    assert r is not o
    s = r.data.splines[0]
    first, last = s.bezier_points[0], s.bezier_points[-1]
    for bp in (first, last):
        assert bp.handle_left_type == 'ALIGNED' and bp.handle_right_type == 'ALIGNED'
        assert _collinear_opposite(bp)
    # The outer handles take the length of the outer handles of the original.
    assert abs((first.handle_left - first.co).length - math.sqrt(2)) < 1e-4
    assert abs((last.handle_right - last.co).length - 2.0) < 1e-4


@test
def offset_both_sides_do_not_share_an_outer_handle():
    reset()
    o = s_curve()
    select([o], o)
    ops.curve_toolkit_offset(distance=0.5, both_sides=True)
    r = bpy.context.active_object
    ends = [s.bezier_points[-1].handle_right.copy() for s in r.data.splines]
    assert len(ends) == 2 and (ends[0] - ends[1]).length > 0.9


@test
def offset_join_arcs_aligned():
    reset()
    o = s_curve()
    select([o], o)
    ops.curve_toolkit_offset(distance=0.5, both_sides=True, join_arcs=True)
    r = bpy.context.active_object
    s = r.data.splines[0]
    assert s.use_cyclic_u
    smooth = [bp for bp in s.bezier_points if _collinear_opposite(bp)]
    assert len(smooth) >= 6
    assert all(bp.handle_left_type != 'FREE' and bp.handle_right_type != 'FREE' for bp in smooth)


@test
def offset_without_duplicate_object_mode():
    reset()
    o = s_curve()
    select([o], o)
    assert ops.curve_toolkit_offset(distance=0.5, duplicate=False) == {'FINISHED'}
    assert [x.name for x in bpy.data.objects] == ["S"]
    assert len(o.data.splines) == 1
    assert abs(o.data.splines[0].bezier_points[0].co.y - 0.5 * math.sqrt(0.5)) < 1e-4


@test
def offset_without_duplicate_shared_data():
    reset()
    o = s_curve()
    twin = bpy.data.objects.new("Twin", o.data)
    bpy.context.scene.collection.objects.link(twin)
    select([o], o)
    ops.curve_toolkit_offset(distance=0.5, duplicate=False)
    assert o.data is not twin.data
    assert abs(twin.data.splines[0].bezier_points[0].co.y) < TOL


@test
def offset_without_duplicate_edit_mode():
    reset()
    o = curve("E", [('POLY', [(0, 0), (4, 0)], False), ('POLY', [(0, 3), (4, 3)], False)])
    select([o], o)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.curve.select_all(action='DESELECT')
    bpy.ops.object.mode_set(mode='OBJECT')
    for p in o.data.splines[0].points:
        p.select = True
    bpy.ops.object.mode_set(mode='EDIT')
    assert ops.curve_toolkit_offset(distance=1.0, duplicate=False) == {'FINISHED'}
    assert o.mode == 'EDIT'
    bpy.ops.object.mode_set(mode='OBJECT')
    ys = sorted(round(s.points[0].co.y, 4) for s in o.data.splines)
    assert ys == [1.0, 3.0], ys


# -----------------------------------------------------------------------------
# Select All by Type
# -----------------------------------------------------------------------------

def _selected(obj):
    out = []
    for s in obj.data.splines:
        pts = s.bezier_points if s.type == 'BEZIER' else s.points
        attr = 'select_control_point' if s.type == 'BEZIER' else 'select'
        out.append(all(getattr(p, attr) for p in pts))
    return out


@test
def select_menu_on_curves():
    reset()
    o = curve("C", [('POLY', [(0, 0), (3, 0)], False),
                    ('BEZIER', [((0, 1),), ((3, 1),)], False),
                    ('POLY', [(5, 5)], False)], dims='3D')
    select([o], o)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.curve.select_all(action='SELECT')
    assert ops.curve_toolkit_select_by_type(kind='NONE') == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    assert _selected(o) == [False, False, False]
    bpy.ops.object.mode_set(mode='EDIT')
    ops.curve_toolkit_select_by_type(kind='STRAYS')
    bpy.ops.object.mode_set(mode='OBJECT')
    assert _selected(o) == [False, False, True]
    bpy.ops.object.mode_set(mode='EDIT')
    ops.curve_toolkit_select_by_type(kind='BEZIER')
    bpy.ops.object.mode_set(mode='OBJECT')
    assert _selected(o) == [False, True, False]


@test
def select_menu_on_meshes():
    reset()
    me = bpy.data.meshes.new("M")
    me.from_pydata([(0, 0, 0), (1, 0, 0), (5, 5, 5)], [(0, 1)], [])
    obj = bpy.data.objects.new("M", me)
    bpy.context.scene.collection.objects.link(obj)
    select([obj], obj)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    assert ops.curve_toolkit_select_by_type.poll()
    assert ops.curve_toolkit_select_by_type(kind='STRAYS') == {'FINISHED'}
    bm = bmesh.from_edit_mesh(me)
    assert [v.select for v in bm.verts] == [False, False, True]
    assert ops.curve_toolkit_select_by_type(kind='NONE') == {'FINISHED'}
    bm = bmesh.from_edit_mesh(me)
    assert not any(v.select for v in bm.verts)
    assert run(ops.curve_toolkit_select_by_type, kind='POLY') == {'CANCELLED'}


# -----------------------------------------------------------------------------
# Sources collection, panel
# -----------------------------------------------------------------------------

@test
def sources_collection_is_hidden_and_reused():
    reset()
    bpy.context.scene.etr_curves_toolkit.sources_in_collection = True
    sq = [(0, 0), (2, 0), (2, 2), (0, 2)]
    a = curve("A", [('POLY', sq, True)])
    b = curve("B", [('POLY', [(x + 1, y) for x, y in sq], True)])
    select([a, b], b)
    assert ops.curve_toolkit_boolean(operation='UNION') == {'FINISHED'}
    src = bpy.data.collections["Curve Boolean Sources"]
    lc = layer_collection(bpy.context.view_layer, src)
    # v0.26.0: hidden in the viewport, no longer excluded from the View Layer.
    assert lc.hide_viewport and not lc.exclude and set(src.objects) == {a, b}
    c = curve("C", [('POLY', [(5, 0), (9, 0)], False)])
    d = curve("D", [('POLY', [(6, -1), (6, 1)], False)])
    select([c, d], None)
    assert ops.curve_toolkit_split_all() == {'FINISHED'}
    assert lc.hide_viewport and set(src.objects) == {a, b, c, d}
    lc.hide_viewport = False
    assert not any(o.hide_get() for o in src.objects)


@test
def sources_hidden_without_collection():
    reset()
    a = curve("A", [('POLY', [(0, 0), (4, 0)], False)])
    b = curve("B", [('POLY', [(1, -1), (1, 1)], False)])
    select([a, b], a)
    ops.curve_toolkit_split_all()
    assert a.hide_get() and b.hide_get()
    assert "Curve Boolean Sources" not in bpy.data.collections


@test
def panel_split_all_and_select_menu():
    from unittest import mock
    from etr_curves_toolkit import panel
    reset()
    fake = mock.MagicMock()
    ctx = mock.MagicMock()
    ctx.scene = bpy.context.scene
    panel.ETR_PT_curve_toolkit_booleans.draw(fake, ctx)
    calls = [c for c in fake.mock_calls]
    assert any(c[1] and c[1][0] == "etr.curve_toolkit_split_all" for c in calls)
    fake = mock.MagicMock()
    ctx.mode = 'OBJECT'
    panel.ETR_PT_curve_toolkit_utilities.draw(fake, ctx)
    menus = [c for c in fake.mock_calls if c[0].endswith("operator_menu_enum")]
    assert menus and menus[0][1] == ("etr.curve_toolkit_select_by_type", "kind")
    items = [i.identifier for i in
             bpy.ops.etr.curve_toolkit_select_by_type.get_rna_type().properties["kind"].enum_items]
    assert items == ['NONE', 'STRAYS', 'POLY', 'BEZIER', 'NURBS']


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
