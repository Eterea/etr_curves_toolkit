# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Tests of Curve Booleans and Curve Splits with Blender as a Python module:

    python test_phase3.py <folder that contains the etr_curves_toolkit package>
"""

import math
import sys
import traceback

sys.path.insert(0, sys.argv[1])

import bpy  # noqa: E402
from mathutils import Matrix, Vector  # noqa: E402

import etr_curves_toolkit as toolkit  # noqa: E402
from etr_curves_toolkit import booleans as bl  # noqa: E402
from etr_curves_toolkit import curve_engine as eng  # noqa: E402
from etr_curves_toolkit import spline_data as sd  # noqa: E402

toolkit.register()
ops = bpy.ops.etr
K = 4 / 3 * math.tan(math.pi / 8)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def make(name, splines, dims='2D', loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1)):
    curve = bpy.data.curves.new(name, 'CURVE')
    curve.dimensions = dims
    for spec in splines:
        sd.write_spline(curve, spec)
    obj = bpy.data.objects.new(name, curve)
    bpy.context.scene.collection.objects.link(obj)
    obj.location, obj.rotation_euler, obj.scale = loc, rot, scale
    bpy.context.view_layer.update()
    return obj


def poly(points, cyclic=True):
    return sd.SplineData('POLY', [sd.PointData(co=(x, y, 0.0)) for x, y in points], cyclic, {})


def square(x0, y0, x1, y1):
    return poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def circle(cx, cy, r, types='AUTO'):
    pts = []
    for i in range(4):
        a = i * math.pi / 2
        p = (cx + r * math.cos(a), cy + r * math.sin(a), 0.0)
        t = (-math.sin(a), math.cos(a), 0.0)
        pts.append(sd.PointData(co=p, hl=tuple(p[j] - K * r * t[j] for j in range(3)),
                                hr=tuple(p[j] + K * r * t[j] for j in range(3)), hlt=types, hrt=types))
    return sd.SplineData('BEZIER', pts, True, {})


def select(objs, active):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = active


def cancelled(op, **kw):
    try:
        return op(**kw) == {'CANCELLED'}
    except RuntimeError:
        return True


def world_loops(obj):
    """Engine segments of an object's splines, in world XY... of a plane
    given by the object's own matrix (returned in world 3D as 2D of its plane)."""
    return [bl.spline_segments(d)[0] for d in sd.read_all(obj.data)]


def area_of(obj, steps=200):
    """Unsigned area in the object's local units (even-odd regions summed
    with signs from orientation, so holes subtract when oriented)."""
    loops = world_loops(obj)
    tol = eng.tolerances_for([p for l in loops for p in eng.segs_points(l)])
    loops = eng.orient_region(loops, tol)
    total = 0.0
    for loop in loops:
        pts = [s.pt(i / steps) for s in loop for i in range(steps)]
        total += 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))
    return total


def world_samples(obj, steps=20):
    mw = obj.matrix_world
    out = []
    for loop in world_loops(obj):
        for s in loop:
            for i in range(steps + 1):
                x, y = s.pt(i / steps)
                out.append(mw @ Vector((x, y, 0)))
    return out


def on_curves(points, objs, tol=2e-5):
    """Every point lies on one of the objects' curves (world space)."""
    curves = []
    for o in objs:
        inv = o.matrix_world.inverted()
        curves.append((o, inv, [s for l in world_loops(o) for s in l]))
    for p in points:
        best = 1e9
        for o, inv, segs in curves:
            q = inv @ p
            if abs(q.z) > 1e-6:
                continue
            for s in segs:
                best = min(best, eng._closest_param(s, (q.x, q.y))[1])
        assert best < tol, (tuple(p), best)


def result():
    objs = [o for o in bpy.data.objects if o.name.startswith("Bool_")]
    assert len(objs) == 1, [o.name for o in bpy.data.objects]
    return objs[0]


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# -----------------------------------------------------------------------------
# Booleans
# -----------------------------------------------------------------------------

@test
def union_square_circle():
    reset()
    sq = make("sq", [square(0, 0, 2, 2)])
    ci = make("ci", [circle(2, 2, 1)])
    select([sq, ci], ci)
    assert ops.curve_toolkit_boolean(operation='UNION') == {'FINISHED'}
    r = result()
    assert sq.hide_get() and ci.hide_get() and not r.hide_get()
    assert r.select_get() and bpy.context.view_layer.objects.active == r
    assert r.data.splines[0].type == 'BEZIER' and len(r.data.splines) == 1
    assert abs(area_of(r) - (4 + math.pi - math.pi / 4)) < 2e-3, area_of(r)
    on_curves(world_samples(r), [sq, ci])
    # Untouched circle points keep smooth (Aligned) handles; square corners are Vector.
    d = sd.read_spline(r.data.splines[0])
    types = {(round(p.co[0], 6), round(p.co[1], 6)): (p.hlt, p.hrt) for p in d.points}
    assert types[(3.0, 2.0)] == ('ALIGNED', 'ALIGNED'), types
    assert types[(0.0, 0.0)] == ('VECTOR', 'VECTOR'), types


@test
def all_poly_stays_poly_and_union_of_many():
    reset()
    a = make("a", [square(0, 0, 2, 2)])
    b = make("b", [square(1, 1, 3, 3)])
    c = make("c", [square(2.5, -1, 4, 2.5)])
    select([a, b, c], b)
    assert ops.curve_toolkit_boolean(operation='UNION') == {'FINISHED'}
    r = result()
    assert all(s.type == 'POLY' for s in r.data.splines) and len(r.data.splines) == 1
    # a U b = 7; c = 5.25; c overlaps b in [2.5, 3] x [1, 2.5] = 0.75.
    assert abs(area_of(r) - 11.5) < 1e-9, area_of(r)
    on_curves(world_samples(r), [a, b, c])


@test
def intersection_and_difference():
    reset()
    sq = make("sq", [square(0, 0, 2, 2)])
    ci = make("ci", [circle(2, 2, 1)])
    select([sq, ci], ci)
    assert ops.curve_toolkit_boolean(operation='INTERSECTION') == {'FINISHED'}
    assert abs(area_of(result()) - math.pi / 4) < 2e-3

    reset()
    sq = make("sq", [square(0, 0, 2, 2)])
    ci = make("ci", [circle(2, 2, 1)])
    select([sq, ci], ci)      # the active circle bites the square
    assert ops.curve_toolkit_boolean(operation='DIFFERENCE') == {'FINISHED'}
    assert abs(area_of(result()) - (4 - math.pi / 4)) < 2e-3

    reset()
    sq = make("sq", [square(0, 0, 2, 2)])
    ci = make("ci", [circle(2, 2, 1)])
    select([sq, ci], sq)      # the active square bites the circle
    ops.curve_toolkit_boolean(operation='DIFFERENCE')
    assert abs(area_of(result()) - (math.pi - math.pi / 4)) < 2e-3


@test
def difference_with_hole():
    reset()
    big = make("big", [square(0, 0, 4, 4)])
    hole = make("hole", [circle(2, 2, 1)])
    select([big, hole], hole)
    ops.curve_toolkit_boolean(operation='DIFFERENCE')
    r = result()
    assert len(r.data.splines) == 2
    assert abs(area_of(r) - (16 - math.pi)) < 2e-3


@test
def vertical_plane_rotated_and_scaled():
    """Curves in the XZ plane at y = 3, with different object transforms."""
    reset()
    rx = (math.pi / 2, 0, 0)
    sq = make("sq", [square(0, 0, 2, 2)], loc=(0, 3, 0), rot=rx)
    # Same plane: rotated about its own normal and scaled, placed elsewhere in it.
    ci = make("ci", [circle(0, 0, 0.5)], loc=(2, 3, 2), rot=(math.pi / 2, 0.7, 0), scale=(2, 2, 2))
    select([sq, ci], sq)
    assert ops.curve_toolkit_boolean(operation='UNION') == {'FINISHED'}
    r = result()
    assert all(abs(a - b) < 1e-6 for ra, rb in zip(r.matrix_world, sq.matrix_world) for a, b in zip(ra, rb))
    assert abs(area_of(r) - (4 + math.pi - math.pi / 4)) < 3e-3, area_of(r)
    on_curves(world_samples(r), [sq, ci])
    assert all(abs(p.y - 3) < 1e-6 for p in world_samples(r))


@test
def errors_leave_everything_untouched():
    cases = []
    # different height
    reset()
    a = make("a", [square(0, 0, 2, 2)])
    b = make("b", [circle(2, 2, 1)], loc=(0, 0, 0.5))
    cases.append(([a, b], 'UNION'))
    for objs, op in cases:
        select(objs, objs[-1])
        assert cancelled(ops.curve_toolkit_boolean, operation=op)
        assert not any(o.hide_get() for o in objs)
        assert not any(o.name.startswith("Bool_") for o in bpy.data.objects)

    reset()  # tilted plane
    a = make("a", [square(0, 0, 2, 2)])
    b = make("b", [circle(2, 2, 1)], rot=(0.3, 0, 0))
    select([a, b], b)
    assert cancelled(ops.curve_toolkit_boolean, operation='UNION')

    reset()  # open spline
    a = make("a", [square(0, 0, 2, 2)])
    b = make("b", [poly([(0, 0), (3, 3)], cyclic=False)])
    select([a, b], b)
    assert cancelled(ops.curve_toolkit_boolean, operation='UNION')

    reset()  # NURBS
    a = make("a", [square(0, 0, 2, 2)])
    n = sd.SplineData('NURBS', [sd.PointData(co=(x, y, 0)) for x, y in ((0, 0), (1, 0), (1, 1), (0, 1))], True, {})
    b = make("b", [n])
    select([a, b], b)
    assert cancelled(ops.curve_toolkit_boolean, operation='UNION')

    reset()  # an open spline next to a closed one (several closed ones are fine)
    a = make("a", [square(0, 0, 2, 2)])
    b = make("b", [circle(2, 2, 1), sd.SplineData(
        'POLY', [sd.PointData(co=(5, 5, 0)), sd.PointData(co=(6, 5, 0))], False, {})])
    select([a, b], b)
    assert cancelled(ops.curve_toolkit_boolean, operation='UNION')

    reset()  # three curves for an intersection
    a, b, c = make("a", [square(0, 0, 2, 2)]), make("b", [circle(2, 2, 1)]), make("c", [circle(1, 1, 1)])
    select([a, b, c], c)
    assert cancelled(ops.curve_toolkit_boolean, operation='INTERSECTION')

    reset()  # no overlap: empty intersection
    a, b = make("a", [square(0, 0, 1, 1)]), make("b", [square(3, 3, 4, 4)])
    select([a, b], b)
    assert cancelled(ops.curve_toolkit_boolean, operation='INTERSECTION')
    assert not a.hide_get() and not b.hide_get()


@test
def result_keeps_the_look_of_the_active():
    reset()
    a = make("a", [square(0, 0, 2, 2)])
    b = make("b", [circle(2, 2, 1)])
    b.data.bevel_depth = 0.05
    b.data.fill_mode = 'BOTH'
    select([a, b], b)
    ops.curve_toolkit_boolean(operation='UNION')
    r = result()
    assert abs(r.data.bevel_depth - 0.05) < 1e-9 and r.data.fill_mode == 'BOTH'
    assert r.data.dimensions == '2D'


# -----------------------------------------------------------------------------
# Splits
# -----------------------------------------------------------------------------

def pieces():
    return sorted((o for o in bpy.data.objects if o.name.startswith("Split_")), key=lambda o: o.name)


def length_world(objs, steps=200):
    total = 0.0
    for o in objs:
        mw = o.matrix_world
        for d in sd.read_all(o.data):
            segs, _ = bl.spline_segments(d)
            pts = [mw @ Vector((*s.pt(i / steps), 0)) for s in segs for i in range(steps + 1)]
            total += sum((a - b).length for a, b in zip(pts, pts[1:]))
    return total


def _split_scene():
    sq = make("sq", [square(0, 0, 2, 2)])
    ci = make("ci", [circle(2, 2, 1)])
    ln = make("ln", [poly([(-1, 1.5), (4, 1.5)], cyclic=False)])
    return sq, ci, ln


@test
def split_all():
    reset()
    sq, ci, ln = _split_scene()
    total = length_world([sq, ci, ln])
    select([sq, ci, ln], ci)
    assert ops.curve_toolkit_split(mode='ALL') == {'FINISHED'}
    ps = pieces()
    assert len(ps) == 4 + 4 + 5, len(ps)
    assert [p.name for p in ps][:2] == ["Split_01", "Split_02"]
    assert all(o.hide_get() for o in (sq, ci, ln))
    assert all(not p.data.splines[0].use_cyclic_u for p in ps)
    assert abs(length_world(ps) - total) < 1e-3 * total
    on_curves([v for p in ps for v in world_samples(p)], [sq, ci, ln])
    kinds = {p.data.splines[0].type for p in ps}
    assert kinds == {'POLY', 'BEZIER'}, kinds    # every piece keeps the type of its source


@test
def split_active_and_collection():
    reset()
    sq, ci, ln = _split_scene()
    bpy.context.scene.etr_curves_toolkit.results_in_collection = True
    select([sq, ci, ln], ci)
    assert ops.curve_toolkit_split(mode='ACTIVE') == {'FINISHED'}
    ps = pieces()
    assert len(ps) == 4
    assert all(p.data.splines[0].type == 'BEZIER' for p in ps)
    coll = bpy.data.collections.get("Curve Boolean Results")
    assert coll and set(coll.objects) == set(ps)
    assert all(o.hide_get() for o in (sq, ci, ln)), "all the originals are hidden"
    assert abs(length_world(ps) - length_world([ci])) < 1e-3


@test
def split_open_curves_and_rotated_plane():
    reset()
    rot = (0, math.pi / 2, 0)      # YZ plane
    a = make("a", [poly([(0, 0), (4, 4)], cyclic=False)], loc=(1, 0, 0), rot=rot)
    b = make("b", [poly([(0, 4), (4, 0)], cyclic=False)], loc=(1, 0, 0), rot=rot)
    c = make("c", [poly([(0, 2), (4, 2)], cyclic=False)], loc=(1, 0, 0), rot=rot)
    select([a, b, c], a)
    assert ops.curve_toolkit_split(mode='ALL') == {'FINISHED'}
    ps = pieces()
    # The three lines cross at one point (2, 2): each is cut once -> 6 pieces.
    assert len(ps) == 6, len(ps)
    on_curves([v for p in ps for v in world_samples(p)], [a, b, c])


@test
def split_keeps_untouched_handles_and_errors():
    reset()
    ci = make("ci", [circle(0, 0, 1)])
    ln = make("ln", [poly([(-2, 0.5), (2, 0.5)], cyclic=False)])
    select([ci, ln], ci)
    ops.curve_toolkit_split(mode='ACTIVE')
    ps = pieces()
    assert len(ps) == 2
    big = max(ps, key=lambda p: len(p.data.splines[0].bezier_points))
    d = sd.read_spline(big.data.splines[0])
    inner = d.points[1:-1]
    assert inner and all(p.hlt == 'ALIGNED' and p.hrt == 'ALIGNED' for p in inner)

    reset()   # no crossings
    a = make("a", [square(0, 0, 1, 1)])
    b = make("b", [square(3, 3, 4, 4)])
    select([a, b], a)
    assert cancelled(ops.curve_toolkit_split, mode='ALL')
    assert not a.hide_get() and not pieces()

    reset()   # not coplanar
    a = make("a", [square(0, 0, 2, 2)])
    b = make("b", [circle(2, 2, 1)], loc=(0, 0, 1))
    select([a, b], a)
    assert cancelled(ops.curve_toolkit_split, mode='ALL')


@test
def split_touching_end_is_not_a_cut():
    reset()
    a = make("a", [poly([(0, 0), (2, 0)], cyclic=False)])
    b = make("b", [poly([(1, 0), (1, 2)], cyclic=False)])     # T junction: b starts on a
    select([a, b], a)
    assert ops.curve_toolkit_split(mode='ALL') == {'FINISHED'}
    ps = pieces()
    assert len(ps) == 3, len(ps)    # a is cut in two, b stays whole


@test
def flat_3d_curves_are_converted_to_2d():
    reset()
    a = make("a", [square(0, 0, 2, 2)], dims='3D')
    b = make("b", [circle(2, 2, 1)], dims='3D')
    select([a, b], b)
    assert ops.curve_toolkit_boolean(operation='UNION') == {'FINISHED'}
    assert a.data.dimensions == '2D' and b.data.dimensions == '2D'
    assert result().data.dimensions == '2D'
    assert abs(area_of(result()) - (4 + math.pi - math.pi / 4)) < 2e-3

    reset()   # a 3D curve that is not flat in its local XY: error, nothing changes
    a = make("a", [square(0, 0, 2, 2)])
    bent = circle(2, 2, 1)
    bent.points[0].co = (3, 2, 0.5)
    b = make("b", [bent], dims='3D')
    select([a, b], b)
    assert cancelled(ops.curve_toolkit_boolean, operation='UNION')
    assert b.data.dimensions == '3D' and not a.hide_get() and not b.hide_get()

    reset()   # splits too
    a = make("a", [square(0, 0, 2, 2)], dims='3D')
    l = make("l", [poly([(-1, 1), (3, 1)], cyclic=False)], dims='3D')
    select([a, l], a)
    assert ops.curve_toolkit_split(mode='ALL') == {'FINISHED'}
    assert a.data.dimensions == '2D' and l.data.dimensions == '2D'


@test
def sources_and_results_collections():
    reset()
    scene = bpy.context.scene
    parent = bpy.data.collections.new("Work")
    scene.collection.children.link(parent)
    sq = make("sq", [square(0, 0, 2, 2)])
    ci = make("ci", [circle(2, 2, 1)])
    for o in (sq, ci):
        scene.collection.objects.unlink(o)
        parent.objects.link(o)
    settings = scene.etr_curves_toolkit
    settings.sources_in_collection = settings.results_in_collection = True
    select([sq, ci], ci)
    assert ops.curve_toolkit_boolean(operation='UNION') == {'FINISHED'}
    src = bpy.data.collections["Curve Boolean Sources"]
    res = bpy.data.collections["Curve Boolean Results"]
    # Created inside the collection of the sources.
    assert src.name in parent.children and res.name in parent.children
    assert set(src.objects) == {sq, ci} and list(sq.users_collection) == [src]
    assert list(res.objects) == [result()]
    # The Sources collection is hidden in the viewport (v0.26.0; it used to be
    # excluded from the View Layer), instead of hiding the curves one by one.
    lc = bpy.context.view_layer.layer_collection.children["Work"].children[src.name]
    assert lc.hide_viewport and not lc.exclude
    assert not sq.hide_get() and not ci.hide_get()
    assert not result().hide_get()

    # The user moves the collections and hides the Sources one: they are reused
    # where they are, and their visibility is not touched.
    scene.collection.children.link(src)
    parent.children.unlink(src)
    src.hide_viewport = True
    a = make("a", [square(5, 0, 7, 2)])
    b = make("b", [circle(7, 2, 1)])
    select([a, b], b)
    assert ops.curve_toolkit_boolean(operation='INTERSECTION') == {'FINISHED'}
    assert len([c for c in bpy.data.collections if c.name.startswith("Curve Boolean Sources")]) == 1
    assert src.name in scene.collection.children and src.hide_viewport is True
    assert {a, b} <= set(src.objects)
    assert len(res.objects) == 2

    # A Sources collection excluded by an older version: it is brought back
    # into the View Layer and hidden in the viewport instead.
    reset()
    settings = bpy.context.scene.etr_curves_toolkit
    settings.sources_in_collection = True
    src = bpy.data.collections.new("Curve Boolean Sources")
    bpy.context.scene.collection.children.link(src)
    bpy.context.view_layer.layer_collection.children[src.name].exclude = True
    a = make("a", [square(0, 0, 2, 2)])
    b = make("b", [circle(2, 2, 1)])
    select([a, b], b)
    assert ops.curve_toolkit_boolean(operation='DIFFERENCE') == {'FINISHED'}
    assert set(src.objects) == {a, b}
    lc = bpy.context.view_layer.layer_collection.children[src.name]
    assert lc.exclude is False and lc.hide_viewport is True


@test
def panel_and_registration():
    from unittest import mock
    from etr_curves_toolkit import panel
    reset()
    layout = mock.MagicMock()
    fake = mock.MagicMock()
    fake.layout = layout
    ctx = mock.MagicMock()
    ctx.scene = bpy.context.scene
    for cls in panel.classes:
        cls.draw(fake, ctx)
    calls = [c for c in layout.mock_calls + layout.row().mock_calls + layout.column().mock_calls
             + layout.column().row().mock_calls]
    idnames = {c[1][0] for c in calls if c[0].endswith("operator") and c[1]}
    assert {"etr.curve_toolkit_boolean_union", "etr.curve_toolkit_split"} <= idnames, idnames
    props = bpy.context.scene.etr_curves_toolkit.bl_rna.properties
    assert "sources_in_collection" in props and "results_in_collection" in props
    toolkit.unregister()
    toolkit.register()


def main():
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    toolkit.unregister()
    sys.exit(1 if failed else 0)


main()
