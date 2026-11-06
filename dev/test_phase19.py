# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Tests of the Phase 21 changes of Curve Toolkit (v0.21.0): Slice (named Fix Hole until v0.22.0: joins
and cuts, and what Fill Curve makes of them), Round
Corners on a closed spline of two points, the order of the Sources and
Results collections in the Outliner, and Separate All Selected apart from the
Select All by Type menu. With Blender as a Python module:

    python test_phase19.py <folder that contains the etr_curves_toolkit package>
"""

import math
import sys
import traceback

sys.path.insert(0, sys.argv[1])

import bpy  # noqa: E402
import bmesh  # noqa: E402

import etr_curves_toolkit as toolkit  # noqa: E402
from etr_curves_toolkit import spline_data as sd  # noqa: E402

toolkit.register()
ops = bpy.ops.etr
TOL = 1e-5
K = 0.5522847498      # Bezier circle handle factor


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if not hasattr(bpy.types.Scene, "etr_curves_toolkit"):
        toolkit.register()


def bezier_circle(r, cw=False, start=0):
    """Closed Bezier circle of 4 points, the first at 12 o'clock (counter
    clockwise, or clockwise), rotated to start at index `start`."""
    pts = []
    for i in range(4):
        a = math.pi / 2 + (-1 if cw else 1) * i * math.pi / 2
        c = (r * math.cos(a), r * math.sin(a))
        t = (-math.sin(a), math.cos(a)) if not cw else (math.sin(a), -math.cos(a))
        hl = (c[0] - K * r * t[0], c[1] - K * r * t[1])
        hr = (c[0] + K * r * t[0], c[1] + K * r * t[1])
        pts.append((c, hl, hr))
    return pts[start:] + pts[:start]


def square(h, cw=False):
    pts = [(-h, -h), (h, -h), (h, h), (-h, h)]
    return pts[::-1] if cw else pts


def curve(name, splines, handle_type='FREE'):
    """splines: [(kind, points, cyclic, selected indices)]."""
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '2D'
    for kind, pts, cyclic, sel in splines:
        s = cu.splines.new(kind)
        if kind == 'BEZIER':
            s.bezier_points.add(len(pts) - 1)
            for k, (bp, p) in enumerate(zip(s.bezier_points, pts)):
                bp.handle_left_type = bp.handle_right_type = 'FREE'
                bp.co = (*p[0], 0)
                bp.handle_left = (*p[1], 0)
                bp.handle_right = (*p[2], 0)
                bp.handle_left_type = bp.handle_right_type = handle_type
                bp.select_control_point = k in sel
                bp.select_left_handle = bp.select_right_handle = False
        else:
            s.points.add(len(pts) - 1)
            for k, (sp, p) in enumerate(zip(s.points, pts)):
                sp.co = (p[0], p[1], 0, 1)
                sp.select = k in sel
        s.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    return obj


def run_fix(obj):
    try:
        r = ops.curve_toolkit_slice()
    except RuntimeError:
        r = {'CANCELLED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    return r, sd.read_all(obj.data)


def flat(data):
    return [(p[0], p[1]) for p in sd.flatten(data, 16)]


def signed_area(poly):
    return 0.5 * sum(poly[i][0] * poly[(i + 1) % len(poly)][1]
                     - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))


def close(a, b):
    return all(abs(x - y) < TOL for x, y in zip(a, b))


def check_bridge(d, a_co, b_co):
    """The joined spline: a closed one, with A twice and B twice, consecutive
    A1 -> B1 and B2 -> A2 (cyclic), and Vector handles on the bridges."""
    assert d.cyclic
    pts = d.points
    n = len(pts)
    ia = [i for i, p in enumerate(pts) if close(p.co, a_co)]
    ib = [i for i, p in enumerate(pts) if close(p.co, b_co)]
    assert len(ia) == 2 and len(ib) == 2, (ia, ib)
    a2, a1 = ia[0], ia[1]
    assert a2 == 0
    b1, b2 = ib
    assert b1 == a1 + 1 and b2 == n - 1, (a1, b1, b2, n)
    if d.kind == 'BEZIER':
        assert pts[a1].hrt == 'VECTOR' and pts[b1].hlt == 'VECTOR'
        assert pts[b2].hrt == 'VECTOR' and pts[a2].hlt == 'VECTOR'
        assert close(pts[a1].hr, (2 * a_co[0] / 3 + b_co[0] / 3, 2 * a_co[1] / 3 + b_co[1] / 3))
    assert all(pts[i].select for i in (a1, a2, b1, b2))
    assert sum(p.select for p in pts) == 4
    return a1, b1


def fill_mesh(obj):
    """Fill Curve (Geometry Nodes) of a curve, as an evaluated mesh: the
    number of faces and of edges strictly inside the outline."""
    tree = bpy.data.node_groups.new("Fill", 'GeometryNodeTree')
    tree.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    tree.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    nin = tree.nodes.new("NodeGroupInput")
    nout = tree.nodes.new("NodeGroupOutput")
    fill = tree.nodes.new("GeometryNodeFillCurve")
    fill.inputs["Mode"].default_value = 'N-gons'
    tree.links.new(nin.outputs[0], fill.inputs["Curve"])
    tree.links.new(fill.outputs[0], nout.inputs[0])
    mod = obj.modifiers.new("Fill", 'NODES')
    mod.node_group = tree
    dg = bpy.context.evaluated_depsgraph_get()
    me = obj.evaluated_get(dg).to_mesh()
    bm = bmesh.new()
    bm.from_mesh(me)
    faces = len(bm.faces)
    inner = sum(1 for e in bm.edges if len(e.link_faces) > 1)
    bm.free()
    obj.evaluated_get(dg).to_mesh_clear()
    obj.modifiers.remove(mod)
    return faces, inner


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# -----------------------------------------------------------------------------
# Slice
# -----------------------------------------------------------------------------

@test
def slice_ring_opposite_directions():
    """The mockup: two circles, A at the top of the outer one and B at the top
    of the inner one, already in opposite directions."""
    reset()
    obj = curve("Ring", [('BEZIER', bezier_circle(1.0), True, {0}),
                         ('BEZIER', bezier_circle(0.6, cw=True), True, {0})])
    before = sd.read_all(obj.data)
    r, after = run_fix(obj)
    assert r == {'FINISHED'}
    assert len(after) == 1
    d = after[0]
    assert len(d.points) == 4 + 4 + 2
    check_bridge(d, (0, 1, 0), (0, 0.6, 0))
    # Shape kept: the original handles of A and B are in place.
    assert close(d.points[0].hr, before[0].points[0].hr)
    assert close(d.points[-1].hl, before[1].points[0].hl)
    # The outline is simple: its area is the ring's.
    ring = math.pi * (1.0 - 0.36)
    assert abs(abs(signed_area(flat(d))) - ring) < 0.01, signed_area(flat(d))


@test
def slice_ring_same_direction_inverts_hole():
    reset()
    obj = curve("Ring", [('BEZIER', bezier_circle(1.0), True, {0}),
                         ('BEZIER', bezier_circle(0.6, start=1), True, {3})])
    r, after = run_fix(obj)
    assert r == {'FINISHED'}
    d = after[0]
    check_bridge(d, (0, 1, 0), (0, 0.6, 0))
    ring = math.pi * (1.0 - 0.36)
    assert abs(abs(signed_area(flat(d))) - ring) < 0.01, signed_area(flat(d))


@test
def slice_selection_order_and_spline_order_do_not_matter():
    """The hole comes first in the curve: the outer spline still leads."""
    reset()
    obj = curve("Ring", [('BEZIER', bezier_circle(0.6), True, {0}),
                         ('BEZIER', bezier_circle(1.0), True, {0})])
    r, after = run_fix(obj)
    assert r == {'FINISHED'}
    d = after[0]
    check_bridge(d, (0, 1, 0), (0, 0.6, 0))
    ring = math.pi * (1.0 - 0.36)
    assert abs(abs(signed_area(flat(d))) - ring) < 0.01
    # Same direction as the outer spline (counter clockwise).
    assert signed_area(flat(d)) > 0


@test
def slice_auto_handles_become_free_and_shape_is_kept():
    reset()
    obj = curve("Ring", [('BEZIER', bezier_circle(1.0), True, {0}),
                         ('BEZIER', bezier_circle(0.6, cw=True), True, {0})],
                handle_type='ALIGNED')
    before = sd.read_all(obj.data)
    r, after = run_fix(obj)
    assert r == {'FINISHED'}
    d = after[0]
    a1, b1 = check_bridge(d, (0, 1, 0), (0, 0.6, 0))
    assert d.points[0].hrt == 'FREE' and d.points[a1].hlt == 'FREE'
    assert close(d.points[0].hr, before[0].points[0].hr)
    assert close(d.points[a1].hl, before[0].points[0].hl)
    assert close(d.points[b1].hr, before[1].points[0].hr)


@test
def slice_poly_square_with_square_hole():
    reset()
    obj = curve("Frame", [('POLY', square(1.0), True, {2}),
                          ('POLY', square(0.5), True, {2})])
    r, after = run_fix(obj)
    assert r == {'FINISHED'}
    d = after[0]
    assert d.kind == 'POLY' and len(d.points) == 10
    check_bridge(d, (1, 1, 0), (0.5, 0.5, 0))
    assert abs(abs(signed_area(flat(d))) - (4 - 1)) < 1e-6


@test
def slice_poly_and_bezier_become_bezier():
    reset()
    obj = curve("Mixed", [('POLY', square(1.0), True, {0}),
                          ('BEZIER', bezier_circle(0.5), True, {2})])
    r, after = run_fix(obj)
    assert r == {'FINISHED'}
    d = after[0]
    assert d.kind == 'BEZIER'
    check_bridge(d, (-1, -1, 0), (0, -0.5, 0))
    area = 4 - math.pi * 0.25
    assert abs(abs(signed_area(flat(d))) - area) < 0.01


@test
def slice_two_shapes_side_by_side():
    """Neither inside the other: they must travel in the same direction."""
    reset()
    left = [(x - 2, y) for x, y in square(0.5)]
    right = [(x + 2, y) for x, y in square(0.5, cw=True)]
    obj = curve("Pair", [('POLY', left, True, {1}), ('POLY', right, True, {0})])
    r, after = run_fix(obj)
    assert r == {'FINISHED'}
    d = after[0]
    assert abs(abs(signed_area(flat(d))) - 2.0) < 1e-6, signed_area(flat(d))


@test
def slice_other_splines_are_kept_in_place():
    reset()
    obj = curve("Many", [('POLY', [(5, 5), (6, 5)], False, set()),
                         ('BEZIER', bezier_circle(1.0), True, {0}),
                         ('POLY', [(7, 7), (8, 7), (8, 8)], True, set()),
                         ('BEZIER', bezier_circle(0.6, cw=True), True, {0})])
    r, after = run_fix(obj)
    assert r == {'FINISHED'}
    assert [len(d.points) for d in after] == [2, 10, 3]


@test
def slice_two_holes_one_after_the_other():
    """A shape with two holes: Slice twice leaves a single spline."""
    reset()
    outer = [((-2, -1), (-2, -1), (-2, -1)), ((2, -1), (2, -1), (2, -1)),
             ((2, 1), (2, 1), (2, 1)), ((-2, 1), (-2, 1), (-2, 1))]
    h1 = [((x - 1, y), (x - 1, y), (x - 1, y)) for x, y in square(0.4)]
    h2 = [((x + 1, y), (x + 1, y), (x + 1, y)) for x, y in square(0.4)]
    obj = curve("Plate", [('BEZIER', outer, True, {3}), ('BEZIER', h1, True, {3})],
                handle_type='VECTOR')
    bpy.ops.object.mode_set(mode='OBJECT')
    s = sd.read_all(obj.data)
    h2d = sd.SplineData('BEZIER', [sd.PointData(co=(*p[0], 0), hl=(*p[1], 0), hr=(*p[2], 0),
                                                hlt='VECTOR', hrt='VECTOR') for p in h2],
                        True, dict(s[1].settings))
    sd.replace_splines(obj.data, s + [h2d])
    bpy.ops.object.mode_set(mode='EDIT')
    r, after = run_fix(obj)
    assert r == {'FINISHED'} and len(after) == 2
    # Second hole: the top-right corner of the outline and of the hole.
    for d in after:
        for p in d.points:
            p.select = p.select_left = p.select_right = False
    for p in after[0].points:
        if close(p.co, (2, 1, 0)):
            p.select = True
    after[1].points[2].select = True
    sd.replace_splines(obj.data, after)
    bpy.ops.object.mode_set(mode='EDIT')
    r, after = run_fix(obj)
    assert r == {'FINISHED'} and len(after) == 1
    assert len(after[0].points) == 4 + 4 + 4 + 4
    area = 8 - 2 * 0.64
    assert abs(abs(signed_area(flat(after[0]))) - area) < 1e-6
    faces, inner = fill_mesh(obj)
    assert faces >= 1


@test
def slice_fill_curve_welds_the_bridge_into_the_picked_edge():
    """Fill Curve of the joined ring: the mesh area is the ring's, and the
    two coincident bridge segments are welded into one inner edge, A-B."""
    reset()
    obj = curve("Ring", [('BEZIER', bezier_circle(1.0), True, {0}),
                         ('BEZIER', bezier_circle(0.6, cw=True), True, {0})])
    r, _ = run_fix(obj)
    assert r == {'FINISHED'}
    tree = bpy.data.node_groups.new("Fill", 'GeometryNodeTree')
    tree.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    tree.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    nin, nout = tree.nodes.new("NodeGroupInput"), tree.nodes.new("NodeGroupOutput")
    fill = tree.nodes.new("GeometryNodeFillCurve")
    fill.inputs["Mode"].default_value = 'N-gons'
    tree.links.new(nin.outputs[0], fill.inputs["Curve"])
    tree.links.new(fill.outputs[0], nout.inputs[0])
    obj.modifiers.new("Fill", 'NODES').node_group = tree
    dg = bpy.context.evaluated_depsgraph_get()
    me = obj.evaluated_get(dg).to_mesh()
    area = sum(p.area for p in me.polygons)
    ring = math.pi * (1.0 - 0.36)
    assert abs(area - ring) < 0.05, area
    # Coincident points are welded, so one inner edge is exactly A-B.
    bm = bmesh.new()
    bm.from_mesh(me)
    inner = [sorted((round(v.co.x, 4), round(v.co.y, 4)) for v in e.verts)
             for e in bm.edges if len(e.link_faces) > 1]
    bm.free()
    assert [(0.0, 0.6), (0.0, 1.0)] in inner, inner
    SLICE_FILL_INFO.append((len(me.polygons), len(inner)))
    obj.evaluated_get(dg).to_mesh_clear()


SLICE_FILL_INFO = []


def select_at(obj, places):
    """Select (Object Mode) the control points at the given 2D places, one
    each: the first point found at every place."""
    datas = sd.read_all(obj.data)
    for d in datas:
        for p in d.points:
            p.select = p.select_left = p.select_right = False
    for place in places:
        hit = next(p for d in datas for p in d.points if close(p.co, (*place, 0)))
        hit.select = True
    sd.replace_splines(obj.data, datas)


def inner_edges(obj):
    """Fill Curve (N-gons) of a curve: (faces, inner edges as sorted 2D
    pairs, total area)."""
    tree = bpy.data.node_groups.new("Fill", 'GeometryNodeTree')
    tree.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    tree.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    nin, nout = tree.nodes.new("NodeGroupInput"), tree.nodes.new("NodeGroupOutput")
    fill = tree.nodes.new("GeometryNodeFillCurve")
    fill.inputs["Mode"].default_value = 'N-gons'
    tree.links.new(nin.outputs[0], fill.inputs["Curve"])
    tree.links.new(fill.outputs[0], nout.inputs[0])
    mod = obj.modifiers.new("Fill", 'NODES')
    mod.node_group = tree
    dg = bpy.context.evaluated_depsgraph_get()
    me = obj.evaluated_get(dg).to_mesh()
    bm = bmesh.new()
    bm.from_mesh(me)
    edges = sorted(sorted((round(v.co.x, 3) + 0.0, round(v.co.y, 3) + 0.0) for v in e.verts)
                   for e in bm.edges if len(e.link_faces) > 1)
    faces = len(bm.faces)
    area = sum(f.calc_area() for f in bm.faces)
    bm.free()
    obj.evaluated_get(dg).to_mesh_clear()
    obj.modifiers.remove(mod)
    return faces, edges, area


@test
def slice_seams_one_after_another():
    """The ring: top pair (join), then bottom pair (cut in two halves), then
    the left pair (one half cut again). Fill Curve has only the picked edges
    inside, and the area of the ring all along."""
    reset()
    obj = curve("Ring", [('BEZIER', bezier_circle(1.0), True, {0}),
                         ('BEZIER', bezier_circle(0.6, cw=True), True, {0})])
    r, after = run_fix(obj)
    assert r == {'FINISHED'} and len(after) == 1
    ring = math.pi * (1.0 - 0.36)

    select_at(obj, [(0, -1), (0, -0.6)])
    bpy.ops.object.mode_set(mode='EDIT')
    r, after = run_fix(obj)
    assert r == {'FINISHED'}, r
    assert len(after) == 2 and all(d.cyclic for d in after)
    assert [len(d.points) for d in after] == [6, 6]
    for d in after:
        assert abs(abs(signed_area(flat(d))) - ring / 2) < 0.01
        assert sum(p.select for p in d.points) == 2
        # Every half keeps the direction of the joined spline.
        assert signed_area(flat(d)) > 0
    faces, edges, area = inner_edges(obj)
    assert faces == 2, faces
    assert edges == [[(0.0, -1.0), (0.0, -0.6)], [(0.0, 0.6), (0.0, 1.0)]], edges
    assert abs(area - ring) < 0.05

    select_at(obj, [(-1, 0), (-0.6, 0)])
    bpy.ops.object.mode_set(mode='EDIT')
    r, after = run_fix(obj)
    assert r == {'FINISHED'}
    assert len(after) == 3
    faces, edges, area = inner_edges(obj)
    assert faces == 3, faces
    assert [(-1.0, 0.0), (-0.6, 0.0)] in edges and len(edges) == 3, edges
    assert abs(area - ring) < 0.05


@test
def slice_cut_bridge_handles_and_poly():
    reset()
    obj = curve("Sq", [('POLY', square(1.0), True, {0, 2})])
    r, after = run_fix(obj)
    assert r == {'FINISHED'}
    assert [d.kind for d in after] == ['POLY', 'POLY']
    assert [len(d.points) for d in after] == [3, 3]
    for d in after:
        assert abs(abs(signed_area(flat(d))) - 2.0) < 1e-6
    reset()
    obj = curve("Circle", [('BEZIER', bezier_circle(1.0), True, {1, 3})],
                handle_type='ALIGNED')
    before = sd.read_all(obj.data)[0]
    r, after = run_fix(obj)
    assert r == {'FINISHED'}
    first, second = after
    # first: P1 (left, index 1) .. Q1 (right, index 3); closed by Q1 -> P1.
    assert close(first.points[0].co, (-1, 0, 0)) and close(first.points[-1].co, (1, 0, 0))
    assert first.points[0].hlt == 'VECTOR' and first.points[-1].hrt == 'VECTOR'
    assert first.points[0].hrt == 'FREE'
    assert close(first.points[0].hr, before.points[1].hr)
    assert close(second.points[0].co, (1, 0, 0)) and close(second.points[-1].co, (-1, 0, 0))
    assert second.points[0].hlt == 'VECTOR' and second.points[-1].hrt == 'VECTOR'
    half = math.pi / 2
    for d in after:
        assert abs(abs(signed_area(flat(d))) - half) < 0.01


@test
def slice_cut_two_point_lens_curved_neighbours():
    """Neighbours joined by a curved segment can be cut: each half has an
    area."""
    reset()
    pts = [((-1, 0), (-0.5, -0.5), (-0.5, 0.5)), ((1, 0), (0.5, 0.5), (0.5, -0.5))]
    obj = curve("Lens", [('BEZIER', pts, True, {0, 1})])
    r, after = run_fix(obj)
    assert r == {'FINISHED'}
    assert [len(d.points) for d in after] == [2, 2]


@test
def slice_errors():
    cases = [
        ("one point", [('BEZIER', bezier_circle(1.0), True, {0}),
                       ('BEZIER', bezier_circle(0.6), True, set())]),
        ("three points", [('BEZIER', bezier_circle(1.0), True, {0, 1}),
                          ('BEZIER', bezier_circle(0.6), True, {0})]),
        ("straight neighbours", [('POLY', square(1.0), True, {0, 1})]),
        ("same place", [('POLY', square(1.0) + [(1.0, 1.0)], True, {2, 4})]),
        ("open same spline", [('POLY', square(1.0), False, {0, 2})]),
        ("open spline", [('BEZIER', bezier_circle(1.0), True, {0}),
                         ('BEZIER', bezier_circle(0.6), False, {0})]),
        ("nurbs", [('BEZIER', bezier_circle(1.0), True, {0}),
                   ('NURBS', square(0.5), True, {0})]),
    ]
    for label, splines in cases:
        reset()
        obj = curve("E", splines)
        before = [len(d.points) for d in sd.read_all(obj.data)]
        r, after = run_fix(obj)
        assert r == {'CANCELLED'}, label
        assert [len(d.points) for d in after] == before, label


@test
def slice_two_objects_refused():
    reset()
    a = curve("A", [('BEZIER', bezier_circle(1.0), True, {0})])
    bpy.ops.object.mode_set(mode='OBJECT')
    b = curve("B", [('BEZIER', bezier_circle(0.6), True, {0})])
    bpy.ops.object.mode_set(mode='OBJECT')
    for o in (a, b):
        o.select_set(True)
    bpy.context.view_layer.objects.active = a
    bpy.ops.object.mode_set(mode='EDIT')
    r, _ = run_fix(a)
    assert r == {'CANCELLED'}


@test
def slice_in_panel_after_slide_point():
    from unittest import mock
    from etr_curves_toolkit import panel
    fake = mock.MagicMock()
    panel.ETR_PT_curve_toolkit_rounds.draw(fake, mock.MagicMock())
    names = [c[1][0] for c in fake.mock_calls if c[0].endswith("operator") and c[1]]
    i = names.index("etr.curve_toolkit_slide_point")
    assert names[i + 1] == "etr.curve_toolkit_slice", names


# -----------------------------------------------------------------------------
# Round Corners on a closed spline of two points
# -----------------------------------------------------------------------------

@test
def round_two_point_closed_spline():
    """The drop of the bug report: a corner (Free handles) at the bottom and a
    smooth point (Aligned) at the top."""
    reset()
    pts = [((0, -0.5045), (0.3115, -0.1457), (-0.3115, -0.1457)),
           ((0, 0.2653), (-0.4659, 0.2653), (0.4659, 0.2653))]
    obj = curve("Drop", [('BEZIER', pts, True, {0})])
    obj.data.splines[0].bezier_points[1].handle_left_type = 'ALIGNED'
    obj.data.splines[0].bezier_points[1].handle_right_type = 'ALIGNED'
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.mode_set(mode='EDIT')
    assert ops.curve_toolkit_round_corners(radius=0.1) == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    d = sd.read_all(obj.data)[0]
    assert d.cyclic and len(d.points) == 4
    assert all(p.co[1] > -0.5045 + 0.01 for p in d.points)
    # The top point is still on the curve, smooth: its handles opposite.
    top = [p for p in d.points if close(p.co, (0, 0.2653, 0))]
    assert len(top) == 1


@test
def round_two_point_closed_spline_smooth_point_refused():
    reset()
    pts = [((0, -0.5045), (0.3115, -0.1457), (-0.3115, -0.1457)),
           ((0, 0.2653), (-0.4659, 0.2653), (0.4659, 0.2653))]
    curve("Drop", [('BEZIER', pts, True, {1})])
    try:
        r = ops.curve_toolkit_round_corners(radius=0.1)
    except RuntimeError:
        r = {'CANCELLED'}
    assert r == {'CANCELLED'}


@test
def round_two_point_closed_spline_both_corners():
    """A lens: two corners, both rounded."""
    reset()
    pts = [((-1, 0), (-0.5, -0.5), (-0.5, 0.5)), ((1, 0), (0.5, 0.5), (0.5, -0.5))]
    obj = curve("Lens", [('BEZIER', pts, True, {0, 1})])
    assert ops.curve_toolkit_round_corners(radius=0.1) == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    d = sd.read_all(obj.data)[0]
    assert len(d.points) >= 4
    assert all(abs(p.co[0]) < 1 - 1e-3 for p in d.points)


# -----------------------------------------------------------------------------
# Sources above Results in the Outliner
# -----------------------------------------------------------------------------

def _two_squares():
    bpy.ops.object.mode_set(mode='OBJECT') if bpy.context.mode != 'OBJECT' else None
    objs = []
    for name, dx in (("SqA", 0.0), ("SqB", 0.5)):
        cu = bpy.data.curves.new(name, 'CURVE')
        cu.dimensions = '2D'
        s = cu.splines.new('POLY')
        s.points.add(3)
        for sp, (x, y) in zip(s.points, square(0.5)):
            sp.co = (x + dx, y, 0, 1)
        s.use_cyclic_u = True
        o = bpy.data.objects.new(name, cu)
        bpy.context.scene.collection.objects.link(o)
        objs.append(o)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    return objs


def _children_names():
    return [c.name for c in bpy.context.scene.collection.children]


@test
def sources_collection_above_results():
    reset()
    st = bpy.context.scene.etr_curves_toolkit
    st.sources_in_collection = True
    st.results_in_collection = True
    _two_squares()
    assert ops.curve_toolkit_boolean(operation='UNION') == {'FINISHED'}
    names = _children_names()
    assert names.index("Curve Boolean Sources") < names.index("Curve Boolean Results"), names


@test
def sources_collection_moved_above_existing_results():
    """Results made first (Sources off), then Sources turned on: Results is
    moved below it, keeping its View Layer settings and hidden objects."""
    reset()
    st = bpy.context.scene.etr_curves_toolkit
    st.sources_in_collection = False
    st.results_in_collection = True
    _two_squares()
    assert ops.curve_toolkit_boolean(operation='UNION') == {'FINISHED'}
    results = bpy.data.collections["Curve Boolean Results"]
    first = list(results.objects)[0]
    first.hide_set(True)
    vl = bpy.context.view_layer
    from etr_curves_toolkit.context_utils import layer_collection
    layer_collection(vl, results).holdout = True
    st.sources_in_collection = True
    _two_squares()
    assert ops.curve_toolkit_boolean(operation='UNION') == {'FINISHED'}
    names = _children_names()
    assert names.index("Curve Boolean Sources") < names.index("Curve Boolean Results"), names
    assert layer_collection(vl, results).holdout
    assert first.hide_get()
    assert len(results.objects) == 2


# -----------------------------------------------------------------------------
# Panel: Separate All Selected in a column of its own
# -----------------------------------------------------------------------------

@test
def separate_apart_from_select_menu():
    from unittest import mock
    from etr_curves_toolkit import panel
    reset()
    fake = mock.MagicMock()
    ctx = mock.MagicMock()
    ctx.scene = bpy.context.scene
    ctx.mode = 'OBJECT'
    panel.ETR_PT_curve_toolkit_utilities.draw(fake, ctx)
    calls = [c[0] for c in fake.mock_calls]
    menu = next(i for i, c in enumerate(calls) if c.endswith("operator_menu_enum"))
    sep = next(i for i, c in enumerate(fake.mock_calls)
               if c[0].endswith("operator") and c[1] == ("etr.curve_toolkit_separate",))
    # A new column is opened from the layout between the menu and Separate.
    assert any(calls[i] == "layout.column" for i in range(menu, sep)), calls[menu:sep + 1]


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
    if SLICE_FILL_INFO:
        print("  Fill Curve of the fixed ring (faces, inner edges):", SLICE_FILL_INFO)
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)


main()
