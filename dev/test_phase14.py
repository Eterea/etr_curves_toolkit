# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Tests of the Phase 14 tools of Curve Toolkit (Points in Between, and Remove
Strays on meshes), with Blender as a Python module:

    python test_phase14.py <folder that contains the etr_curves_toolkit package>
"""

import sys
import traceback

sys.path.insert(0, sys.argv[1])

import bpy  # noqa: E402
import bmesh  # noqa: E402
from mathutils import Vector  # noqa: E402

import etr_curves_toolkit as toolkit  # noqa: E402

toolkit.register()
ops = bpy.ops.etr
TOL = 1e-5


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if not hasattr(bpy.types.Scene, "etr_curves_toolkit"):
        toolkit.register()


def mesh_edit(coords, edges=(), selected=(), location=(0, 0, 0), scale=(1, 1, 1)):
    me = bpy.data.meshes.new("M")
    me.from_pydata([tuple(c) for c in coords], list(edges), [])
    obj = bpy.data.objects.new("M", me)
    obj.location, obj.scale = location, scale
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bm = bmesh.from_edit_mesh(me)
    bm.verts.ensure_lookup_table()
    for v in bm.verts:
        v.select = v.index in selected
    bm.select_flush_mode()
    bmesh.update_edit_mesh(me)
    return obj


def curve_edit(splines, location=(0, 0, 0)):
    cu = bpy.data.curves.new("C", 'CURVE')
    cu.dimensions = '3D'
    for coords, selected in splines:
        s = cu.splines.new('POLY')
        s.points.add(len(coords) - 1)
        for i, (p, co) in enumerate(zip(s.points, coords)):
            p.co = (*co, 1.0)
            p.select = i in selected
    obj = bpy.data.objects.new("C", cu)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    return obj


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


@test
def curve_middle_point():
    reset()
    obj = curve_edit([([(0, 0, 0), (9, 9, 9)], {0}), ([(4, 2, 6)], {0})], location=(1, 1, 1))
    assert ops.curve_toolkit_points_in_between() == {'FINISHED'}
    assert obj.mode == 'EDIT'
    bpy.ops.object.mode_set(mode='OBJECT')
    assert len(obj.data.splines) == 3
    s = obj.data.splines[2]
    assert s.type == 'POLY' and len(s.points) == 1
    p = s.points[0]
    assert (p.co.xyz - Vector((2, 1, 3))).length < TOL
    assert p.select
    assert not any(p.select for sp in obj.data.splines[:2] for p in sp.points)


@test
def curve_count():
    reset()
    obj = curve_edit([([(0, 0, 0), (3, 0, 6)], {0, 1})])
    ops.curve_toolkit_points_in_between(count=2)
    bpy.ops.object.mode_set(mode='OBJECT')
    news = [s.points[0].co.xyz for s in obj.data.splines[1:]]
    assert len(news) == 2
    assert (news[0] - Vector((1, 0, 2))).length < TOL
    assert (news[1] - Vector((2, 0, 4))).length < TOL


@test
def curve_wrong_selection():
    reset()
    curve_edit([([(0, 0, 0), (3, 0, 6), (5, 5, 5)], {0, 1, 2})])
    try:
        result = ops.curve_toolkit_points_in_between()
    except RuntimeError:
        result = {'CANCELLED'}
    assert result == {'CANCELLED'}


@test
def mesh_points():
    reset()
    obj = mesh_edit([(0, 0, 0), (4, 0, 0), (9, 9, 9)], [(0, 1)], selected={0, 1},
                    location=(10, 0, 0), scale=(2, 2, 2))
    ops.curve_toolkit_points_in_between(count=3)
    assert obj.mode == 'EDIT'
    bm = bmesh.from_edit_mesh(obj.data)
    selected = sorted((tuple(v.co) for v in bm.verts if v.select))
    assert len(bm.verts) == 6 and len(selected) == 3
    for co, x in zip(selected, (1, 2, 3)):
        assert (Vector(co) - Vector((x, 0, 0))).length < TOL, co


@test
def mesh_remove_strays():
    reset()
    obj = mesh_edit([(0, 0, 0), (1, 0, 0), (2, 2, 2), (3, 3, 3)], [(0, 1)], selected=set())
    assert ops.curve_toolkit_remove_strays.poll()
    assert ops.curve_toolkit_remove_strays() == {'FINISHED'}
    bm = bmesh.from_edit_mesh(obj.data)
    assert len(bm.verts) == 2 and len(bm.edges) == 1


@test
def curve_remove_strays_takes_the_new_points():
    reset()
    obj = curve_edit([([(0, 0, 0), (3, 0, 6)], {0, 1})])
    ops.curve_toolkit_points_in_between(count=4)
    ops.curve_toolkit_remove_strays()
    bpy.ops.object.mode_set(mode='OBJECT')
    assert len(obj.data.splines) == 1


@test
def disabled_in_object_mode():
    reset()
    curve_edit([([(0, 0, 0), (3, 0, 6)], {0, 1})])
    bpy.ops.object.mode_set(mode='OBJECT')
    assert not ops.curve_toolkit_points_in_between.poll()


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
