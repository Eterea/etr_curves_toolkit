# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Tests of the Phase 23 changes of Curve Toolkit (v0.23.0): Change Origin
(Bounds Center, Edit Mode per spline and per segment), Points Along Curve on a
segment, Points at Intersections ending in Edit Mode, the Threshold in Global
Settings, Split at Control Points (renamed), Split at Stray Points, Poly
helper points and Add Line / Point. With Blender as a Python module:

    python test_phase23.py <folder that contains the etr_curves_toolkit package>

There is no 3D Viewport in background mode, so the tests pass the view
themselves (view='TOP', ...), as the buttons store it on their first run.
"""

import math
import sys
import traceback

sys.path.insert(0, sys.argv[1])

import bpy  # noqa: E402

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


def close(a, b, tol=TOL):
    return all(abs(x - y) < tol for x, y in zip(a, b))


def make(name, splines, dims='3D', location=(0.0, 0.0, 0.0), select=True):
    """splines: [(kind, points, cyclic, selected indices)]. Poly points are
    (x, y[, z]); Bezier points are (co, left handle, right handle[, type])."""
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = dims
    for kind, pts, cyclic, sel in splines:
        s = cu.splines.new(kind)
        if kind == 'BEZIER':
            s.bezier_points.add(len(pts) - 1)
            for k, (bp, p) in enumerate(zip(s.bezier_points, pts)):
                bp.handle_left_type = bp.handle_right_type = 'FREE'
                bp.co = _xyz(p[0])
                bp.handle_left = _xyz(p[1])
                bp.handle_right = _xyz(p[2])
                if len(p) > 3:
                    bp.handle_left_type = bp.handle_right_type = p[3]
                bp.select_control_point = k in sel
                bp.select_left_handle = bp.select_right_handle = False
        else:
            s.points.add(len(pts) - 1)
            for k, (sp, p) in enumerate(zip(s.points, pts)):
                sp.co = (*_xyz(p), 1.0)
                sp.select = k in sel
        s.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, cu)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    if select:
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
    return obj


def _xyz(p):
    return (p[0], p[1], p[2] if len(p) > 2 else 0.0)


def bezier_circle(r, center=(0.0, 0.0), cw=False):
    pts = []
    for i in range(4):
        a = math.pi / 2 + (-1 if cw else 1) * i * math.pi / 2
        c = (center[0] + r * math.cos(a), center[1] + r * math.sin(a))
        t = (-math.sin(a), math.cos(a)) if not cw else (math.sin(a), -math.cos(a))
        pts.append((c, (c[0] - K * r * t[0], c[1] - K * r * t[1]),
                    (c[0] + K * r * t[0], c[1] + K * r * t[1])))
    return pts


def edit(obj):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')


def run(op, **kw):
    try:
        return op(**kw)
    except RuntimeError:
        return {'CANCELLED'}


def strays(obj):
    """World positions of the stray points of a curve object."""
    mw = obj.matrix_world
    return [tuple(mw @ s.points[0].co.xyz) for s in obj.data.splines
            if s.type == 'POLY' and len(s.points) == 1]


def has(points, target, tol=1e-4):
    return any(close(p, target, tol) for p in points)


def flat(data, steps=24):
    return sd.flatten(data, steps)


def to_polyline(p, poly):
    """Distance from a point to a polyline."""
    best = float("inf")
    for a, b in zip(poly, poly[1:]):
        ab = [b[i] - a[i] for i in range(3)]
        ap = [p[i] - a[i] for i in range(3)]
        den = sum(c * c for c in ab) or 1e-300
        t = max(0.0, min(1.0, sum(x * y for x, y in zip(ab, ap)) / den))
        best = min(best, math.dist(p, [a[i] + ab[i] * t for i in range(3)]))
    return best


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn



def origin(obj):
    return tuple(obj.matrix_world.translation)


def world_shape(obj):
    mw = obj.matrix_world
    return [tuple(mw @ __import__("mathutils").Vector(p)) for d in sd.read_all(obj.data)
            for p in flat(d, 8)]


# -----------------------------------------------------------------------------
# Change Origin
# -----------------------------------------------------------------------------

@test
def origin_geo_is_bounds_center_object_mode():
    reset()
    # Points weighted to the left: the median is not the center of the box.
    obj = make("G", [('POLY', [(0, 0), (0.1, 0), (0.2, 0), (4, 2)], False, ())])
    before = world_shape(obj)
    assert ops.curve_toolkit_change_origin(mode='GEOMETRY') == {'FINISHED'}
    assert close(origin(obj), (2, 1, 0)), origin(obj)
    assert all(close(a, b) for a, b in zip(before, world_shape(obj)))


@test
def origin_geo_ignores_bezier_handles():
    reset()
    # Long handles sticking out above: the box is the one of the curve itself.
    obj = make("H", [('BEZIER', [((0, 0), (-1, 0), (0, 5)), ((2, 0), (2, 5), (3, 0))],
                      False, ())])
    assert ops.curve_toolkit_change_origin(mode='GEOMETRY') == {'FINISHED'}
    o = origin(obj)
    assert abs(o[0] - 1.0) < 1e-4 and o[1] < 2.5, o


@test
def origin_edit_mode_selected_spline():
    reset()
    obj = make("E", [('POLY', [(0, 0), (2, 0)], False, ()),
                     ('POLY', [(10, 0), (10, 4)], False, (0,))])
    edit(obj)
    for mode, target in (('IN', (10, 0, 0)), ('OUT', (10, 4, 0)), ('MID', (10, 2, 0)),
                         ('GEOMETRY', (10, 2, 0))):
        assert ops.curve_toolkit_change_origin(mode=mode) == {'FINISHED'}, mode
        assert bpy.context.mode == 'EDIT_CURVE'
        assert close(origin(obj), target), (mode, origin(obj))


@test
def origin_edit_mode_mid_of_segment():
    reset()
    obj = make("S", [('POLY', [(0, 0), (2, 0), (2, 6), (0, 6)], False, (1, 2))])
    edit(obj)
    assert ops.curve_toolkit_change_origin(mode='MID') == {'FINISHED'}
    assert close(origin(obj), (2, 3, 0)), origin(obj)
    # Not consecutive: the midpoint of the whole spline (length 10, at 5).
    reset()
    obj = make("S", [('POLY', [(0, 0), (2, 0), (2, 6), (0, 6)], False, (0, 2))])
    edit(obj)
    assert ops.curve_toolkit_change_origin(mode='MID') == {'FINISHED'}
    assert close(origin(obj), (2, 3, 0)), origin(obj)
    # Closing segment of a closed spline (last and first).
    reset()
    obj = make("S", [('POLY', [(0, 0), (4, 0), (4, 4), (0, 4)], True, (0, 3))])
    edit(obj)
    assert ops.curve_toolkit_change_origin(mode='MID') == {'FINISHED'}
    assert close(origin(obj), (0, 2, 0)), origin(obj)
    # In and Out keep the whole spline.
    reset()
    obj = make("S", [('POLY', [(0, 0), (2, 0), (2, 6)], False, (1, 2))])
    edit(obj)
    assert ops.curve_toolkit_change_origin(mode='OUT') == {'FINISHED'}
    assert close(origin(obj), (2, 6, 0)), origin(obj)


@test
def origin_edit_mode_bezier_segment_mid_is_on_the_curve():
    reset()
    obj = make("B", [('BEZIER', [((0, 0), (-1, 0), (1, 2)), ((3, 0), (2, 2), (4, 0)),
                                 ((6, 0), (5, 0), (7, 0))], False, (0, 1))])
    edit(obj)
    assert ops.curve_toolkit_change_origin(mode='MID') == {'FINISHED'}
    o = origin(obj)
    assert abs(o[0] - 1.5) < 1e-3 and o[1] > 1.0, o


@test
def origin_edit_mode_needs_a_selection():
    reset()
    obj = make("N", [('POLY', [(0, 0), (2, 0)], False, ())])
    edit(obj)
    assert run(ops.curve_toolkit_change_origin, mode='IN') == {'CANCELLED'}
    assert bpy.context.mode == 'EDIT_CURVE'


# -----------------------------------------------------------------------------
# Points Along Curve on a segment, Points at Intersections in Edit Mode
# -----------------------------------------------------------------------------

@test
def along_segment_of_two_consecutive_points():
    reset()
    obj = make("A", [('POLY', [(0, 0), (4, 0), (4, 4)], False, (1, 2))])
    edit(obj)
    assert ops.curve_toolkit_points_along_curve(count=3) == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    pts = strays(obj)
    assert len(pts) == 3 and all(has(pts, (4, y, 0)) for y in (1, 2, 3)), pts
    # Not consecutive: along the whole spline.
    reset()
    obj = make("A", [('POLY', [(0, 0), (4, 0), (4, 4)], False, (0, 2))])
    edit(obj)
    assert ops.curve_toolkit_points_along_curve(count=1) == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    assert has(strays(obj), (4, 0, 0))


@test
def along_segment_closing_and_bezier():
    reset()
    obj = make("C", [('BEZIER', bezier_circle(1.0), True, (0, 3))])
    edit(obj)
    assert ops.curve_toolkit_points_along_curve(count=1) == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    pts = strays(obj)
    # Between the last point (0 degrees) and the first (90): at 45 degrees.
    a = math.radians(45)
    assert len(pts) == 1 and close(pts[0], (math.cos(a), math.sin(a), 0), 2e-3), pts


@test
def intersections_and_along_object_mode_end_in_edit_mode():
    reset()
    make("A", [('POLY', [(-1, 0), (1, 0)], False, ())])
    make("B", [('POLY', [(0, -1), (0, 1)], False, ())])
    assert ops.curve_toolkit_points_at_intersections() == {'FINISHED'}
    assert bpy.context.mode == 'EDIT_CURVE'
    assert bpy.context.active_object.name.startswith("Intersection Points")
    assert len(bpy.context.objects_in_mode) == 1
    reset()
    make("A", [('POLY', [(-1, 0), (1, 0)], False, ())])
    assert ops.curve_toolkit_points_along_curve() == {'FINISHED'}
    assert bpy.context.mode == 'EDIT_CURVE'


# -----------------------------------------------------------------------------
# Helper points, Add Line / Point
# -----------------------------------------------------------------------------

@test
def circle_helper_points_are_poly():
    reset()
    obj = make("T", [('POLY', [(0, 0), (4, 0), (0, 3)], True, (0, 1, 2))])
    edit(obj)
    assert ops.curve_toolkit_circle_inscribed(view='TOP', helper_points=True) == {'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    singles = [s for s in obj.data.splines if len(s.points) + len(s.bezier_points) == 1]
    assert len(singles) == 4, len(singles)          # 3 contacts and the center
    assert all(s.type == 'POLY' for s in singles)
    # The inscribed circle of the 3-4-5 triangle has radius 1, center (1, 1).
    assert has(strays(obj), (1, 1, 0))


@test
def add_line_points():
    reset()
    assert ops.curve_toolkit_add_line() == {'FINISHED'}
    obj = bpy.context.active_object
    assert obj.name == "Line" and [tuple(p.co.xyz) for p in obj.data.splines[0].points] == [
        (-1, 0, 0), (1, 0, 0)]
    reset()
    assert ops.curve_toolkit_add_line(points=1) == {'FINISHED'}
    obj = bpy.context.active_object
    assert obj.name == "Point" and len(obj.data.splines) == 1
    assert obj.data.splines[0].type == 'POLY' and len(obj.data.splines[0].points) == 1
    reset()
    assert ops.curve_toolkit_add_line(points=5, radius=2.0) == {'FINISHED'}
    xs = [round(p.co.x, 6) for p in bpy.context.active_object.data.splines[0].points]
    assert xs == [-2, -1, 0, 1, 2], xs
    assert bpy.types.ETR_OT_curve_toolkit_add_line.bl_label == "Add Line / Point"


@test
def add_point_in_edit_mode():
    reset()
    obj = make("E", [('POLY', [(0, 0), (2, 0)], False, (0,))])
    bpy.context.scene.cursor.location = (5, 5, 0)
    edit(obj)
    assert ops.curve_toolkit_add_line(points=1, align='WORLD', location=(5, 5, 0)) == {
        'FINISHED'}
    bpy.ops.object.mode_set(mode='OBJECT')
    assert has(strays(obj), (5, 5, 0)) and len(obj.data.splines) == 2


# -----------------------------------------------------------------------------
# Splits
# -----------------------------------------------------------------------------

def _pieces():
    return sorted((o for o in bpy.context.scene.objects
                   if o.name.startswith("Split_") and o.visible_get()), key=lambda o: o.name)


@test
def split_at_control_points_renamed():
    assert bpy.types.ETR_OT_curve_toolkit_split_at_points.bl_label == "Split at Control Points"


@test
def stray_split_object_mode():
    reset()
    obj = make("S", [('POLY', [(0, 0), (4, 0)], False, ()),
                     ('POLY', [(1, 0)], False, ()),
                     ('POLY', [(3, 0.0004)], False, ()),        # within 0.001
                     ('POLY', [(2, 0.5)], False, ())])          # off the line
    assert ops.curve_toolkit_split_at_stray_points() == {'FINISHED'}
    pieces = _pieces()
    assert len(pieces) == 3, pieces
    ends = sorted(round(p.data.splines[0].points[0].co.x, 4) for p in pieces)
    assert ends == [0, 1, 3], ends
    assert not obj.visible_get()        # the original kept as a backup
    total = sum(len(p.data.splines) for p in pieces)
    assert total == 3


@test
def stray_split_keeps_untouched_splines_and_ignores_other_objects():
    reset()
    obj = make("S", [('POLY', [(0, 0), (4, 0)], False, ()),
                     ('POLY', [(0, 2), (4, 2)], False, ()),
                     ('POLY', [(2, 0)], False, ())])
    make("Other", [('POLY', [(2, 2)], False, ())], select=False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    assert ops.curve_toolkit_split_at_stray_points() == {'FINISHED'}
    pieces = _pieces()
    assert len(pieces) == 3, pieces           # 2 halves + the untouched line
    lens = sorted(len(p.data.splines[0].points) for p in pieces)
    assert lens == [2, 2, 2]


@test
def stray_split_bezier_keeps_the_shape():
    reset()
    circle = bezier_circle(1.0)
    a = math.radians(30)
    obj = make("C", [('BEZIER', circle, True, ()),
                     ('POLY', [(math.cos(a), math.sin(a))], False, ()),
                     ('POLY', [(-1, 0)], False, ())])            # on a control point
    shape = flat(sd.read_all(obj.data)[0], 400)
    assert ops.curve_toolkit_split_at_stray_points() == {'FINISHED'}
    pieces = _pieces()
    assert len(pieces) == 2, pieces
    for p in pieces:
        d = sd.read_all(p.data)[0]
        assert not d.cyclic
        for q in flat(d, 50):
            assert to_polyline(q, shape) < 1e-4
    starts = [tuple(p.data.splines[0].bezier_points[0].co) for p in pieces]
    assert has(starts, (math.cos(a), math.sin(a), 0), 1e-3) and has(starts, (-1, 0, 0))


@test
def stray_split_threshold_from_global_settings():
    reset()
    make("S", [('POLY', [(0, 0), (4, 0)], False, ()), ('POLY', [(2, 0.05)], False, ())])
    assert run(ops.curve_toolkit_split_at_stray_points) == {'CANCELLED'}
    bpy.context.scene.etr_curves_toolkit.merge_threshold = 0.1
    assert ops.curve_toolkit_split_at_stray_points() == {'FINISHED'}
    assert len(_pieces()) == 2


@test
def stray_split_ortho_view_counts_apparent_points():
    reset()
    make("S", [('POLY', [(0, 0, 3), (4, 0, 3)], False, ()),
               ('POLY', [(2, 0, 0)], False, ())])                # below the line
    assert run(ops.curve_toolkit_split_at_stray_points, view='NONE') == {'CANCELLED'}
    assert ops.curve_toolkit_split_at_stray_points(view='TOP') == {'FINISHED'}
    pieces = _pieces()
    assert len(pieces) == 2
    # The cut is on the line itself, at its height.
    cos = [tuple(p.data.splines[0].points[k].co.xyz) for p in pieces for k in (0, 1)]
    assert has(cos, (2, 0, 3)), cos
    # From the side it does not cut.
    reset()
    make("S", [('POLY', [(0, 0, 3), (4, 0, 3)], False, ()),
               ('POLY', [(2, 0, 0)], False, ())])
    assert run(ops.curve_toolkit_split_at_stray_points, view='RIGHT') == {'CANCELLED'}


@test
def stray_split_edit_mode_only_selected():
    reset()
    obj = make("E", [('POLY', [(0, 0), (4, 0)], False, (0,)),
                     ('POLY', [(0, 2), (4, 2)], False, ()),          # not selected
                     ('POLY', [(1, 0)], False, (0,)),
                     ('POLY', [(3, 0)], False, ()),                  # stray not selected
                     ('POLY', [(2, 2)], False, (0,))])
    edit(obj)
    assert ops.curve_toolkit_split_at_stray_points() == {'FINISHED'}
    assert bpy.context.mode == 'OBJECT'
    pieces = _pieces()
    assert len(pieces) == 2, pieces           # only the first line, at x = 1
    xs = sorted(round(p.data.splines[0].points[-1].co.x, 4) for p in pieces)
    assert xs == [1, 4], xs
    assert not obj.visible_get()


@test
def stray_split_edit_mode_nothing_stays_in_edit_mode():
    reset()
    obj = make("E", [('POLY', [(0, 0), (4, 0)], False, (0,)),
                     ('POLY', [(2, 1)], False, (0,))])
    edit(obj)
    assert run(ops.curve_toolkit_split_at_stray_points) == {'CANCELLED'}
    assert bpy.context.mode == 'EDIT_CURVE'


@test
def stray_split_sources_and_results_collections():
    reset()
    s = bpy.context.scene.etr_curves_toolkit
    s.sources_in_collection = s.results_in_collection = True
    obj = make("S", [('POLY', [(0, 0), (4, 0)], False, ()), ('POLY', [(2, 0)], False, ())])
    assert ops.curve_toolkit_split_at_stray_points() == {'FINISHED'}
    assert obj.users_collection[0].name == "Curve Boolean Sources"
    res = bpy.data.collections["Curve Boolean Results"]
    assert len(res.objects) == 2


@test
def stray_split_closed_poly_one_point_opens_it():
    reset()
    make("Q", [('POLY', [(0, 0), (2, 0), (2, 2), (0, 2)], True, ()),
               ('POLY', [(1, 0)], False, ())])
    assert ops.curve_toolkit_split_at_stray_points() == {'FINISHED'}
    pieces = _pieces()
    assert len(pieces) == 1
    sp = pieces[0].data.splines[0]
    assert not sp.use_cyclic_u and len(sp.points) == 6
    assert close(sp.points[0].co.xyz, (1, 0, 0)) and close(sp.points[-1].co.xyz, (1, 0, 0))


# -----------------------------------------------------------------------------
# Panel
# -----------------------------------------------------------------------------

def _drawn(panel_cls, mode='OBJECT'):
    from unittest import mock
    fake = mock.MagicMock()
    ctx = mock.MagicMock()
    ctx.scene = bpy.context.scene
    ctx.mode = mode
    panel_cls.draw(fake, ctx)
    return fake, [c[1][0] for c in fake.mock_calls if c[0].endswith("operator") and c[1]]


@test
def panel_global_settings():
    from etr_curves_toolkit import panel
    reset()
    fake, _ = _drawn(panel.ETR_PT_curve_toolkit_utilities)
    props = [c[1][1] for c in fake.mock_calls if c[0].endswith(".prop") and len(c[1]) > 1]
    assert "merge_threshold" not in props, props
    fake, _ = _drawn(panel.ETR_PT_curve_toolkit_global)
    props = [c[1][1] for c in fake.mock_calls if c[0].endswith(".prop") and len(c[1]) > 1]
    assert props == ["merge_threshold"], props
    assert 'DEFAULT_CLOSED' in panel.ETR_PT_curve_toolkit_global.bl_options
    assert panel.classes[-1] is panel.ETR_PT_curve_toolkit_global
    assert panel.classes[-2] is panel.ETR_PT_curve_toolkit_origin
    _, drawn = _drawn(panel.ETR_PT_curve_toolkit_booleans)
    i = drawn.index("etr.curve_toolkit_split_at_points")
    assert drawn[i + 1] == "etr.curve_toolkit_split_at_stray_points", drawn
    fake, _ = _drawn(panel.ETR_PT_curve_toolkit_booleans)
    call = next(c for c in fake.mock_calls if c[0].endswith("operator") and c[1]
                and c[1][0] == "etr.curve_toolkit_split_at_stray_points")
    assert "icon_value" not in call[2]


@test
def register_unregister_cycle():
    toolkit.unregister()
    assert not hasattr(bpy.types, "ETR_OT_curve_toolkit_split_at_stray_points")
    toolkit.register()
    assert hasattr(bpy.types, "ETR_OT_curve_toolkit_split_at_stray_points")
    assert hasattr(bpy.types, "ETR_PT_curve_toolkit_global")


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
