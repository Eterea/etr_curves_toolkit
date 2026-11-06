# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Tests of the Phase 19 tools of Curve Toolkit (v0.19.0) (Lines from Points, Snap Pair,
Swap Pair, Select by Type, and the new layout of the panel), with Blender as
a Python module:

    python test_phase17.py <folder that contains the etr_curves_toolkit package>
"""

import random
import sys
import traceback

sys.path.insert(0, sys.argv[1])

import bpy  # noqa: E402
import bmesh  # noqa: E402
from mathutils import Vector  # noqa: E402

import etr_curves_toolkit as toolkit  # noqa: E402
from etr_curves_toolkit import lines  # noqa: E402

toolkit.register()
ops = bpy.ops.etr
TOL = 1e-5


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if not hasattr(bpy.types.Scene, "etr_curves_toolkit"):
        toolkit.register()


def mesh_obj(coords, edges=(), selected=(), location=(0, 0, 0), name="M"):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(c) for c in coords], list(edges), [])
    obj = bpy.data.objects.new(name, me)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    for v in me.vertices:
        v.select = v.index in selected
    for e in me.edges:
        e.select = False
    return obj


def curve_obj(splines, location=(0, 0, 0), name="C"):
    """splines: [(kind, coords, selected indices, cyclic)]"""
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '3D'
    for kind, coords, selected, cyclic in splines:
        s = cu.splines.new(kind)
        if kind == 'BEZIER':
            s.bezier_points.add(len(coords) - 1)
            for i, (bp, co) in enumerate(zip(s.bezier_points, coords)):
                bp.handle_left_type = bp.handle_right_type = 'FREE'
                bp.co = co
                bp.handle_left = Vector(co) + Vector((-0.5, 0.2, 0))
                bp.handle_right = Vector(co) + Vector((0.5, -0.2, 0))
                bp.select_control_point = i in selected
                bp.select_left_handle = bp.select_right_handle = False
        else:
            s.points.add(len(coords) - 1)
            for i, (p, co) in enumerate(zip(s.points, coords)):
                p.co = (*co, 1.0)
                p.select = i in selected
        s.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, cu)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    return obj


def edit(*objs):
    """Enter the Edit Mode of objs (the last one active)."""
    for o in bpy.context.selected_objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[-1]
    bpy.ops.object.mode_set(mode='EDIT')


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
# Order of the points (pure Python)
# -----------------------------------------------------------------------------

def _edges(points, order, closed):
    n = len(order)
    pairs = [(order[i], order[i + 1]) for i in range(n - 1)]
    if closed:
        pairs.append((order[-1], order[0]))
    return {frozenset((tuple(points[a]), tuple(points[b]))) for a, b in pairs}


def _outline(coords):
    pts = [(x, y, 0.0) for x, y in coords]
    return {frozenset((pts[i], pts[(i + 1) % len(pts)])) for i in range(len(pts))}


SHAPES = {
    "square": [(0, 0), (2, 0), (2, 2), (0, 2)],
    "irregular": [(0, 0), (3, 0.4), (3.6, 2.5), (0.5, 2)],
    "hexagon": [(2, 0), (1, 1.7), (-1, 1.7), (-2, 0), (-1, -1.7), (1, -1.7)],
    "cross": [(1, 0), (2, 0), (2, 1), (3, 1), (3, 2), (2, 2), (2, 3), (1, 3),
              (1, 2), (0, 2), (0, 1), (1, 1)],
    "T": [(0, 3), (3, 3), (3, 2), (2, 2), (2, 0), (1, 0), (1, 2), (0, 2)],
    "H": [(0, 0), (1, 0), (1, 1), (2, 1), (2, 0), (3, 0), (3, 3), (2, 3),
          (2, 2), (1, 2), (1, 3), (0, 3)],
    "L": [(0, 0), (2, 0), (2, 1), (1, 1), (1, 3), (0, 3)],
    "stair": [(0, 0), (3, 0), (3, 1), (2, 1), (2, 2), (1, 2), (1, 3), (0, 3)],
}


@test
def order_follows_the_outline_of_shapes():
    rng = random.Random(7)
    for name, coords in SHAPES.items():
        pts = [(x, y, 0.0) for x, y in coords]
        shuffled = pts[:]
        rng.shuffle(shuffled)
        order, closed = lines.order_points(shuffled)
        assert closed, name
        assert sorted(order) == list(range(len(pts))), name
        assert _edges(shuffled, order, True) == _outline(coords), name


@test
def order_of_shapes_on_other_planes():
    for name in ("T", "cross"):
        pts = [(x, 5.0, y) for x, y in SHAPES[name]]
        order, _ = lines.order_points(pts[::-1])
        got = _edges(pts[::-1], order, True)
        want = {frozenset((pts[i], pts[(i + 1) % len(pts)])) for i in range(len(pts))}
        assert got == want, name


@test
def rotated_shape_falls_back_to_the_shortest_path():
    import math
    c, s = math.cos(0.4), math.sin(0.4)
    pts = [(x * c - y * s, x * s + y * c, 0.0) for x, y in SHAPES["irregular"]]
    order, closed = lines.order_points(pts[::-1])
    assert closed
    assert _edges(pts[::-1], order, True) == {
        frozenset((pts[i], pts[(i + 1) % 4])) for i in range(4)}


@test
def order_never_crosses_on_random_points():
    rng = random.Random(3)
    for n in (5, 9, 12, 13, 25, 40):
        pts = [(rng.random(), rng.random(), 0.0) for _ in range(n)]
        order, _ = lines.order_points(pts)
        assert sorted(order) == list(range(n))
        assert not lines._self_crossing([p[:2] for p in pts], order), n


@test
def order_two_points_and_collinear():
    assert lines.order_points([(0, 0, 0), (1, 1, 1)]) == ([0, 1], False)
    order, closed = lines.order_points([(2, 2, 2), (0, 0, 0), (1, 1, 1), (3, 3, 3)])
    assert not closed and order in ([1, 2, 0, 3], [3, 0, 2, 1])


@test
def order_open():
    pts = [(0, 0, 0), (4, 0, 0), (4, 1, 0), (0, 1, 0)]
    order, closed = lines.order_points(pts, closed=False)
    assert not closed
    # Opened at one of the long sides.
    ends = {order[0], order[-1]}
    assert ends in ({0, 1}, {2, 3}), order


@test
def unique_points_drops_repeats():
    kept, dropped = lines.unique_points([(0, 0, 0), (1, 0, 0), (0, 0, 1e-9)])
    assert len(kept) == 2 and dropped == 1


# -----------------------------------------------------------------------------
# Lines from Points
# -----------------------------------------------------------------------------

@test
def lines_curve_two_points():
    reset()
    obj = curve_obj([('POLY', [(0, 0, 0), (3, 0, 0), (5, 5, 0)], {0, 2}, False)],
                    location=(1, 0, 0))
    edit(obj)
    assert ops.curve_toolkit_lines_from_points() == {'FINISHED'}
    assert obj.mode == 'EDIT'
    bpy.ops.object.mode_set(mode='OBJECT')
    assert len(obj.data.splines) == 2
    s = obj.data.splines[1]
    assert s.type == 'POLY' and len(s.points) == 2 and not s.use_cyclic_u
    cos = sorted(tuple(round(c, 5) for c in p.co.xyz) for p in s.points)
    assert cos == [(0, 0, 0), (5, 5, 0)], cos
    assert all(p.select for p in s.points)
    assert not any(p.select for p in obj.data.splines[0].points)
    # Nothing was merged: the original spline keeps its 3 points.
    assert len(obj.data.splines[0].points) == 3


@test
def lines_curve_closed_shape_from_bezier_and_poly():
    reset()
    obj = curve_obj([
        ('BEZIER', [(0, 0, 0), (2, 0, 0)], {0, 1}, False),
        ('POLY', [(2, 2, 0), (0, 2, 0)], {0, 1}, False),
    ])
    edit(obj)
    ops.curve_toolkit_lines_from_points()
    bpy.ops.object.mode_set(mode='OBJECT')
    s = obj.data.splines[2]
    assert s.type == 'POLY' and len(s.points) == 4 and s.use_cyclic_u
    pts = [tuple(round(c, 5) for c in p.co.xyz) for p in s.points]
    assert _edges(pts, range(4), True) == _outline(SHAPES["square"])


@test
def lines_curve_open_option():
    reset()
    obj = curve_obj([('POLY', [(0, 0, 0), (1, 0, 0), (1, 1, 0)], {0, 1, 2}, False)])
    edit(obj)
    ops.curve_toolkit_lines_from_points(closed=False)
    bpy.ops.object.mode_set(mode='OBJECT')
    assert not obj.data.splines[1].use_cyclic_u
    assert len(obj.data.splines[1].points) == 3


@test
def lines_curve_several_objects():
    reset()
    a = curve_obj([('POLY', [(0, 0, 0), (1, 0, 0)], {0, 1}, False)], name="A")
    b = curve_obj([('POLY', [(0, 0, 0), (1, 0, 0)], {0, 1}, False)],
                  location=(0, 0, 3), name="B")
    edit(a, b)
    assert ops.curve_toolkit_lines_from_points() == {'FINISHED'}
    assert a.mode == 'EDIT' and b.mode == 'EDIT'
    bpy.ops.object.mode_set(mode='OBJECT')
    assert len(a.data.splines) == 1 and len(b.data.splines) == 2
    s = b.data.splines[1]
    assert len(s.points) == 4 and s.use_cyclic_u
    world = sorted(tuple(round(c, 5) for c in (b.matrix_world @ p.co.xyz)) for p in s.points)
    assert world == [(0, 0, 0), (0, 0, 3), (1, 0, 0), (1, 0, 3)], world


@test
def lines_curve_needs_two_points():
    reset()
    obj = curve_obj([('POLY', [(0, 0, 0), (1, 0, 0)], {0}, False)])
    edit(obj)
    assert run(ops.curve_toolkit_lines_from_points) == {'CANCELLED'}


@test
def lines_mesh_shape():
    reset()
    coords = [(x, y, 0) for x, y in SHAPES["T"]]
    order = [3, 0, 6, 1, 7, 4, 2, 5]
    obj = mesh_obj([coords[i] for i in order], selected=set(range(8)), location=(0, 0, 1))
    edit(obj)
    assert ops.curve_toolkit_lines_from_points() == {'FINISHED'}
    bm = bmesh.from_edit_mesh(obj.data)
    assert len(bm.verts) == 16 and len(bm.edges) == 8
    edges = {frozenset((tuple(round(c, 5) for c in e.verts[0].co),
                        tuple(round(c, 5) for c in e.verts[1].co))) for e in bm.edges}
    want = {frozenset(((float(a[0]), float(a[1]), 0.0), (float(b[0]), float(b[1]), 0.0)))
            for a, b in zip(SHAPES["T"], SHAPES["T"][1:] + SHAPES["T"][:1])}
    assert edges == want
    assert sum(v.select for v in bm.verts) == 8


@test
def lines_mesh_several_objects():
    reset()
    a = mesh_obj([(0, 0, 0)], selected={0}, name="A")
    b = mesh_obj([(0, 0, 0), (9, 9, 9)], selected={0}, location=(2, 0, 0), name="B")
    edit(a, b)
    assert ops.curve_toolkit_lines_from_points() == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    assert len(a.data.vertices) == 1
    assert len(b.data.vertices) == 4 and len(b.data.edges) == 1
    ends = sorted(tuple(round(c, 5) for c in (b.matrix_world @ v.co)) for v in b.data.vertices[2:])
    assert ends == [(0, 0, 0), (2, 0, 0)], ends


# -----------------------------------------------------------------------------
# Snap Pair and Swap Pair
# -----------------------------------------------------------------------------

@test
def snap_pair_middle_points_of_two_splines():
    reset()
    obj = curve_obj([
        ('POLY', [(0, 0, 0), (1, 0, 0), (2, 0, 0)], {1}, True),
        ('POLY', [(0, 3, 0), (1, 3, 0), (2, 3, 0)], {1}, False),
    ])
    edit(obj)
    assert ops.curve_toolkit_snap_pair() == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    s0, s1 = obj.data.splines
    assert len(s0.points) == 3 and len(s1.points) == 3
    assert (s0.points[1].co.xyz - Vector((1, 1.5, 0))).length < TOL
    assert (s1.points[1].co.xyz - Vector((1, 1.5, 0))).length < TOL
    assert s0.use_cyclic_u


@test
def snap_pair_at_a_and_b():
    for at, want in (('A', (0, 0, 0)), ('B', (4, 2, 0))):
        reset()
        obj = curve_obj([('POLY', [(0, 0, 0), (1, 0, 0), (2, 0, 0), (4, 2, 0)],
                          {0, 3}, False)])
        edit(obj)
        ops.curve_toolkit_snap_pair(at=at)
        bpy.ops.object.mode_set(mode='OBJECT')
        pts = obj.data.splines[0].points
        assert (pts[0].co.xyz - Vector(want)).length < TOL, at
        assert (pts[3].co.xyz - Vector(want)).length < TOL, at
        assert len(pts) == 4


@test
def snap_pair_bezier_handles_travel():
    reset()
    obj = curve_obj([('BEZIER', [(0, 0, 0), (2, 0, 0), (4, 0, 0)], {0, 2}, False)])
    edit(obj)
    ops.curve_toolkit_snap_pair()
    bpy.ops.object.mode_set(mode='OBJECT')
    bps = obj.data.splines[0].bezier_points
    for bp in (bps[0], bps[2]):
        assert (bp.co - Vector((2, 0, 0))).length < TOL
        assert (bp.handle_left - bp.co - Vector((-0.5, 0.2, 0))).length < TOL
        assert (bp.handle_right - bp.co - Vector((0.5, -0.2, 0))).length < TOL


@test
def snap_pair_across_objects():
    reset()
    a = curve_obj([('POLY', [(0, 0, 0), (1, 0, 0)], {1}, False)], name="A")
    b = curve_obj([('NURBS', [(0, 0, 0), (1, 0, 0), (2, 0, 0)], {0}, False)],
                  location=(0, 4, 0), name="B")
    edit(a, b)
    ops.curve_toolkit_snap_pair(at='A')
    bpy.ops.object.mode_set(mode='OBJECT')
    p = b.data.splines[0].points[0]
    assert ((b.matrix_world @ p.co.xyz) - Vector((1, 0, 0))).length < TOL
    assert abs(p.co[3] - 1.0) < TOL


@test
def snap_pair_needs_two():
    reset()
    obj = curve_obj([('POLY', [(0, 0, 0), (1, 0, 0), (2, 0, 0)], {0, 1, 2}, False)])
    edit(obj)
    assert run(ops.curve_toolkit_snap_pair) == {'CANCELLED'}
    assert run(ops.curve_toolkit_swap_pair) == {'CANCELLED'}


@test
def swap_pair_curve():
    reset()
    obj = curve_obj([('BEZIER', [(0, 0, 0), (2, 0, 0), (4, 1, 0)], {0, 2}, False)])
    edit(obj)
    assert ops.curve_toolkit_swap_pair() == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    bps = obj.data.splines[0].bezier_points
    assert (bps[0].co - Vector((4, 1, 0))).length < TOL
    assert (bps[2].co - Vector((0, 0, 0))).length < TOL
    assert (bps[0].handle_left - bps[0].co - Vector((-0.5, 0.2, 0))).length < TOL


@test
def snap_and_swap_mesh():
    reset()
    obj = mesh_obj([(0, 0, 0), (2, 0, 0), (2, 2, 0)], [(0, 1), (1, 2)], selected={0, 2})
    edit(obj)
    assert ops.curve_toolkit_swap_pair() == {'FINISHED'}
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    assert (bm.verts[0].co - Vector((2, 2, 0))).length < TOL
    assert (bm.verts[2].co - Vector((0, 0, 0))).length < TOL
    assert ops.curve_toolkit_snap_pair(at='B') == {'FINISHED'}
    bm = bmesh.from_edit_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    assert len(bm.verts) == 3
    assert (bm.verts[0].co - Vector((0, 0, 0))).length < TOL
    assert (bm.verts[2].co - Vector((0, 0, 0))).length < TOL


@test
def snap_mesh_across_objects():
    reset()
    a = mesh_obj([(0, 0, 0)], selected={0}, name="A")
    b = mesh_obj([(0, 0, 0)], selected={0}, location=(4, 0, 0), name="B")
    edit(a, b)
    ops.curve_toolkit_snap_pair()
    bpy.ops.object.mode_set(mode='OBJECT')
    assert ((a.matrix_world @ a.data.vertices[0].co) - Vector((2, 0, 0))).length < TOL
    assert ((b.matrix_world @ b.data.vertices[0].co) - Vector((2, 0, 0))).length < TOL


# -----------------------------------------------------------------------------
# Select by Type, Points in Between, panel
# -----------------------------------------------------------------------------

def _selected_kinds(obj):
    out = []
    for s in obj.data.splines:
        pts = s.bezier_points if s.type == 'BEZIER' else s.points
        attr = 'select_control_point' if s.type == 'BEZIER' else 'select'
        if all(getattr(p, attr) for p in pts):
            out.append(s.type)
        else:
            assert not any(getattr(p, attr) for p in pts)
    return out


@test
def select_by_type():
    reset()
    obj = curve_obj([
        ('POLY', [(0, 0, 0), (1, 0, 0)], {0}, False),
        ('BEZIER', [(0, 1, 0), (1, 1, 0)], {1}, False),
        ('NURBS', [(0, 2, 0), (1, 2, 0), (2, 2, 0)], set(), False),
        ('POLY', [(0, 3, 0), (1, 3, 0)], set(), False),
    ])
    edit(obj)
    for kind, want in (('POLY', ['POLY', 'POLY']), ('BEZIER', ['BEZIER']), ('NURBS', ['NURBS'])):
        assert ops.curve_toolkit_select_by_type(kind=kind) == {'FINISHED'}
        assert obj.mode == 'EDIT'
        bpy.ops.object.mode_set(mode='OBJECT')
        assert _selected_kinds(obj) == want, (kind, _selected_kinds(obj))
        bpy.ops.object.mode_set(mode='EDIT')
    ops.curve_toolkit_select_by_type(kind='POLY', extend=True)
    bpy.ops.object.mode_set(mode='OBJECT')
    assert _selected_kinds(obj) == ['POLY', 'NURBS', 'POLY']


@test
def points_in_between_are_poly():
    reset()
    obj = curve_obj([('BEZIER', [(0, 0, 0), (4, 0, 0)], {0, 1}, False)])
    edit(obj)
    ops.curve_toolkit_points_in_between(count=3)
    bpy.ops.object.mode_set(mode='OBJECT')
    news = obj.data.splines[1:]
    assert len(news) == 3 and all(s.type == 'POLY' and len(s.points) == 1 for s in news)


def _drawn(panel_cls):
    from unittest import mock
    fake = mock.MagicMock()
    ctx = mock.MagicMock()
    ctx.scene = bpy.context.scene
    ctx.mode = 'OBJECT'
    panel_cls.draw(fake, ctx)
    return [c[1][0] for c in fake.layout.mock_calls
            if (c[0].endswith("operator") or c[0].endswith("operator_menu_enum")) and c[1]]


@test
def panel_layout():
    from etr_curves_toolkit import panel
    reset()
    drawn = _drawn(panel.ETR_PT_curve_toolkit_primitives)
    # Layout of v0.22.0: the construction points are the last row.
    assert drawn[-4:] == ["etr.curve_toolkit_lines_from_points",
                          "etr.curve_toolkit_points_in_between",
                          "etr.curve_toolkit_points_along_curve",
                          "etr.curve_toolkit_points_at_intersections"], drawn
    assert panel.ETR_PT_curve_toolkit_rounds.bl_label == "Shaping Splines"
    assert 'DEFAULT_CLOSED' not in getattr(panel.ETR_PT_curve_toolkit_rounds, "bl_options", set())
    assert _drawn(panel.ETR_PT_curve_toolkit_rounds) == [
        "etr.curve_toolkit_round_corners", "etr.curve_toolkit_bridge_curves",
        "etr.curve_toolkit_arcs_to_corners", "etr.curve_toolkit_offset",
        "etr.curve_toolkit_extend", "etr.curve_toolkit_slide_point",
        "etr.curve_toolkit_slice", "etr.curve_toolkit_undo_slice",
        "etr.curve_toolkit_handles_to_axis", "etr.curve_toolkit_handles_to_lines"]
    util = _drawn(panel.ETR_PT_curve_toolkit_utilities)
    assert "etr.curve_toolkit_offset" not in util
    # Order of v0.24.0 (see test_phase24.py for the whole list).
    i = util.index("etr.curve_toolkit_select_by_type")
    assert i == 0 and util[1] == "etr.curve_toolkit_separate", util
    assert util.index("etr.curve_toolkit_set_resolution") > util.index(
        "etr.curve_toolkit_remove_doubles"), util
    for icon in ("offset", "extend", "slide_point", "lines_from_points"):
        assert icon in panel._icons and tuple(panel._icons[icon].icon_size) == (32, 32), icon


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
