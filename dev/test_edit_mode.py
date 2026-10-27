# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Tests of the Edit Mode tools of Curve Toolkit (Primitive Curves as new
splines, Offset as a new spline, Extend Curve), of the order of the Adjust
Last Operation panel and of context_utils.world_matrix(), with Blender as a
Python module:

    python test_edit_mode.py <folder that contains the etr_curve_toolkit package>

Every test builds its own curves from scratch. Shapes are checked in world
space, so a tool that forgot the transform of the object would fail.
"""

import math
import sys
import traceback

sys.path.insert(0, sys.argv[1])

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

import etr_curve_toolkit as toolkit  # noqa: E402
from etr_curve_toolkit import spline_data as sd  # noqa: E402
from etr_curve_toolkit import primitives as prim  # noqa: E402
from etr_curve_toolkit import extend as ext  # noqa: E402
from etr_curve_toolkit.context_utils import world_matrix  # noqa: E402

toolkit.register()
ops = bpy.ops.etr


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if not hasattr(bpy.types.Scene, "etr_curve_toolkit"):
        toolkit.register()


def make_curve(name, splines, dims='3D', loc=(0, 0, 0), rot=(0, 0, 0), scale=(1, 1, 1)):
    curve = bpy.data.curves.new(name, 'CURVE')
    curve.dimensions = dims
    curve.resolution_u = 12
    for spec in splines:
        sd.write_spline(curve, spec)
    obj = bpy.data.objects.new(name, curve)
    bpy.context.scene.collection.objects.link(obj)
    obj.location, obj.rotation_euler, obj.scale = loc, rot, scale
    bpy.context.view_layer.update()
    return obj


def poly(points, cyclic=False, select=()):
    pts = [sd.PointData(co=tuple(p), select=(i in select)) for i, p in enumerate(points)]
    return sd.SplineData('POLY', pts, cyclic, {"resolution_u": 12})


def nurbs(points, cyclic=False, select=()):
    pts = [sd.PointData(co=tuple(p), select=(i in select)) for i, p in enumerate(points)]
    return sd.SplineData(
        'NURBS', pts, cyclic,
        {"resolution_u": 12, "order_u": 4, "use_endpoint_u": not cyclic})


def square(half, center=(0.0, 0.0), z=0.0, select=()):
    x, y = center
    return poly([
        (x - half, y - half, z), (x + half, y - half, z),
        (x + half, y + half, z), (x - half, y + half, z),
    ], cyclic=True, select=select)


def select_only(obj):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def edit(*objs):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[-1]
    bpy.ops.object.mode_set(mode='EDIT')


def object_mode():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')


def spline_count(obj):
    return len(obj.data.splines)


def data_of(obj, index=0):
    return sd.read_spline(obj.data.splines[index])


def world_points(obj, index=0):
    """Control points of a spline of `obj`, in world space."""
    mw = world_matrix(obj)
    return [mw @ Vector(p.co) for p in data_of(obj, index).points]


def coords(data):
    return [tuple(round(c, 6) for c in p.co) for p in data.points]


def all_selected(data):
    return all(p.select for p in data.points)


def none_selected(data):
    return not any(p.select or p.select_left or p.select_right for p in data.points)


def cancelled(op, **kwargs):
    """True if the operator was cancelled. In background mode an operator that
    reports an ERROR raises RuntimeError instead of returning."""
    try:
        return op(**kwargs) == {'CANCELLED'}
    except RuntimeError:
        return True


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# -----------------------------------------------------------------------------
# world_matrix(): the transform of an object without the depsgraph
# -----------------------------------------------------------------------------

@test
def world_matrix_reads_the_transform_that_is_there():
    """matrix_world is runtime data and lags behind until the scene is
    evaluated again, which is what an operator sees when it runs from the
    Adjust Last Operation panel. world_matrix() never lags."""
    reset()
    obj = make_curve("c", [square(1.0)], loc=(3.0, 1.0, 0.0))
    assert world_matrix(obj).translation == Vector((3.0, 1.0, 0.0))

    obj.location = (5.0, 5.0, 5.0)        # no view_layer.update() on purpose
    assert obj.matrix_world.translation == Vector((3.0, 1.0, 0.0)), "matrix_world should lag"
    assert world_matrix(obj).translation == Vector((5.0, 5.0, 5.0))

    bpy.context.view_layer.update()
    assert obj.matrix_world.translation == Vector((5.0, 5.0, 5.0))


@test
def world_matrix_follows_the_parent_chain():
    reset()
    grandparent = bpy.data.objects.new("gp", None)
    parent = bpy.data.objects.new("p", None)
    for o in (grandparent, parent):
        bpy.context.scene.collection.objects.link(o)
    grandparent.location = (1.0, 0.0, 0.0)
    grandparent.scale = (2.0, 2.0, 2.0)
    parent.parent = grandparent
    parent.location = (0.0, 3.0, 0.0)
    parent.rotation_euler = (0.0, 0.0, math.radians(90.0))

    child = make_curve("c", [square(1.0)], loc=(0.0, 0.0, 4.0))
    child.parent = parent
    child.matrix_parent_inverse = Vector((0.0, 0.0, 0.0)).to_track_quat('Z', 'Y').to_matrix().to_4x4()
    bpy.context.view_layer.update()

    for obj in (grandparent, parent, child):
        got = world_matrix(obj)
        want = obj.matrix_world
        assert all(abs(got[r][c] - want[r][c]) < 1e-6 for r in range(4) for c in range(4)), (
            f"{obj.name}: {got} != {want}")


@test
def world_matrix_falls_back_with_constraints():
    reset()
    target = bpy.data.objects.new("t", None)
    bpy.context.scene.collection.objects.link(target)
    target.location = (7.0, 0.0, 0.0)
    obj = make_curve("c", [square(1.0)])
    obj.constraints.new('COPY_LOCATION').target = target
    bpy.context.view_layer.update()
    # A constraint is only in the evaluated matrix, so that is the one to use.
    assert world_matrix(obj).translation == obj.matrix_world.translation
    assert abs(world_matrix(obj).translation.x - 7.0) < 1e-6


# -----------------------------------------------------------------------------
# Offset in Object Mode: the result lands on its source
# -----------------------------------------------------------------------------

@test
def offset_in_object_mode_lands_on_the_source():
    reset()
    obj = make_curve("c", [square(1.0)], loc=(3.0, 1.0, 0.0))
    select_only(obj)
    ops.curve_toolkit_offset(distance=0.5)
    result = bpy.context.active_object
    assert result is not obj and result.name.startswith("Curve Offset")
    assert (Vector(result.location) - Vector((3.0, 1.0, 0.0))).length < 1e-6
    assert (world_matrix(result).translation - Vector((3.0, 1.0, 0.0))).length < 1e-6
    # Outwards: the square of half 1 becomes a square of half 1.5.
    half = max(abs(c) for p in world_points(result) for c in (p.x - 3.0, p.y - 1.0))
    assert abs(half - 1.5) < 1e-5, half


@test
def offset_in_object_mode_survives_a_stale_matrix():
    """The regression of the origin jumping to 0,0,0 when the Distance was
    tweaked in the Adjust Last Operation panel: the operator ran again before
    the scene had been evaluated, so matrix_world was not there yet."""
    reset()
    obj = make_curve("c", [square(1.0)], loc=(3.0, 1.0, 0.0))
    select_only(obj)
    obj.location = (-4.0, 2.0, 1.0)       # no view_layer.update() on purpose
    ops.curve_toolkit_offset(distance=0.25)
    result = bpy.context.active_object
    assert (Vector(result.location) - Vector((-4.0, 2.0, 1.0))).length < 1e-6, (
        f"the offset was placed at {tuple(result.location)}")


@test
def offset_in_object_mode_uses_the_scale_of_the_source():
    reset()
    obj = make_curve("c", [square(1.0)], loc=(0.0, 0.0, 0.0), scale=(2.0, 2.0, 2.0))
    select_only(obj)
    obj.location = (1.0, 0.0, 0.0)        # stale on purpose, as above
    ops.curve_toolkit_offset(distance=1.0)
    result = bpy.context.active_object
    # 1 m in the scene with an object scaled by 2 is 0.5 in local space, so the
    # square of half 1 (2 in world) becomes 2.5 in world.
    half = max(abs(c) for p in world_points(result) for c in (p.x - 1.0, p.y))
    assert abs(half - 3.0) < 1e-5, half


# -----------------------------------------------------------------------------
# Offset in Edit Mode
# -----------------------------------------------------------------------------

@test
def offset_in_edit_mode_keeps_the_original_and_adds_the_offset():
    reset()
    obj = make_curve("c", [square(1.0, select=(0,))], dims='2D', loc=(3.0, 1.0, 0.0))
    objects_before = len(bpy.context.scene.objects)
    before = coords(data_of(obj))
    edit(obj)
    ops.curve_toolkit_offset(distance=0.5)
    object_mode()

    assert len(bpy.context.scene.objects) == objects_before, "no new object in Edit Mode"
    assert spline_count(obj) == 2, f"{spline_count(obj)} splines"
    original = data_of(obj, 0)
    assert coords(original) == before, "the original spline must stay where it was"
    assert none_selected(original), "the original should be left deselected"
    data = data_of(obj, 1)
    assert data.kind == 'POLY' and data.cyclic and len(data.points) == 4
    half = max(abs(c) for p in data.points for c in p.co[:2])
    assert abs(half - 1.5) < 1e-5, half
    assert all_selected(data), "the result of the offset should stay selected"


@test
def offset_in_edit_mode_takes_a_partly_selected_spline_whole():
    """One point selected is enough: the whole spline is offset, which is the
    Select Linked one would do by hand."""
    reset()
    obj = make_curve("c", [square(1.0, select=(2,))])
    edit(obj)
    ops.curve_toolkit_offset(distance=-0.25)
    object_mode()
    assert spline_count(obj) == 2
    data = data_of(obj, 1)
    half = max(abs(c) for p in data.points for c in p.co[:2])
    assert abs(half - 0.75) < 1e-5, half


@test
def offset_in_edit_mode_leaves_the_other_splines_alone_and_in_order():
    reset()
    obj = make_curve("c", [
        square(1.0, center=(-5.0, 0.0)),            # untouched
        square(1.0, center=(0.0, 0.0), select=(1,)),  # offset
        square(1.0, center=(5.0, 0.0)),             # untouched
    ])
    first, third = coords(data_of(obj, 0)), coords(data_of(obj, 2))
    edit(obj)
    ops.curve_toolkit_offset(distance=0.5)
    object_mode()

    # The offset of the middle spline goes in right after it: A, B, B', C.
    assert spline_count(obj) == 4, f"{spline_count(obj)} splines"
    assert coords(data_of(obj, 0)) == first, "the first spline moved"
    assert coords(data_of(obj, 3)) == third, "the last spline moved"
    assert none_selected(data_of(obj, 0)) and none_selected(data_of(obj, 3))
    assert none_selected(data_of(obj, 1)), "the spline that was offset stays, deselected"
    offset = data_of(obj, 2)
    half = max(abs(p.co[0]) for p in offset.points)
    assert abs(half - 1.5) < 1e-5, half
    assert all_selected(offset)


@test
def offset_in_edit_mode_honours_the_scale_of_the_object():
    reset()
    obj = make_curve("c", [square(1.0, select=(0,))], scale=(2.0, 2.0, 2.0))
    edit(obj)
    ops.curve_toolkit_offset(distance=1.0)
    object_mode()
    # 1 m in the scene, so in world the square of half 2 becomes half 3.
    half = max(abs(c) for p in world_points(obj, 1) for c in (p.x, p.y))
    assert abs(half - 3.0) < 1e-5, half


@test
def offset_in_edit_mode_needs_a_selection():
    reset()
    obj = make_curve("c", [square(1.0)])
    before = coords(data_of(obj))
    edit(obj)
    assert cancelled(ops.curve_toolkit_offset, distance=0.5)
    object_mode()
    assert coords(data_of(obj)) == before


@test
def offset_in_edit_mode_rejects_nurbs_and_non_flat_splines():
    reset()
    obj = make_curve("c", [nurbs([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], select=(0,))])
    before = coords(data_of(obj))
    edit(obj)
    assert cancelled(ops.curve_toolkit_offset, distance=0.5)
    object_mode()
    assert coords(data_of(obj)) == before, "a rejected offset must change nothing"

    reset()
    obj = make_curve("c", [square(1.0, z=1.0, select=(0,))])   # flat, but not at z = 0
    before = coords(data_of(obj))
    edit(obj)
    assert cancelled(ops.curve_toolkit_offset, distance=0.5)
    object_mode()
    assert coords(data_of(obj)) == before


@test
def offset_in_edit_mode_does_not_convert_the_object_to_2d():
    reset()
    obj = make_curve("c", [square(1.0, select=(0,))], dims='3D')
    edit(obj)
    ops.curve_toolkit_offset(distance=0.5)
    object_mode()
    assert spline_count(obj) == 2
    assert obj.data.dimensions == '3D', "the Shape of the object is none of our business"


@test
def offset_in_edit_mode_keeps_a_spline_the_distance_would_eat():
    reset()
    obj = make_curve("c", [square(0.1, select=(0,))])
    before = coords(data_of(obj))
    edit(obj)
    assert cancelled(ops.curve_toolkit_offset, distance=-0.5)
    object_mode()
    assert coords(data_of(obj)) == before, "nothing is left, so nothing changes"


@test
def offset_in_edit_mode_cuts_a_spline_in_pieces():
    """A dumbbell shape shrunk past its waist falls apart, and both pieces end
    up in the same object, in the place of the one that was there (the same
    shape as test_offset.shrinking_can_split_a_curve_in_two)."""
    reset()
    dumbbell = poly([
        (-3.0, -1.0, 0.0), (-1.0, -1.0, 0.0), (-1.0, -0.25, 0.0), (1.0, -0.25, 0.0),
        (1.0, -1.0, 0.0), (3.0, -1.0, 0.0), (3.0, 1.0, 0.0), (1.0, 1.0, 0.0),
        (1.0, 0.25, 0.0), (-1.0, 0.25, 0.0), (-1.0, 1.0, 0.0), (-3.0, 1.0, 0.0),
    ], cyclic=True, select=(0,))
    obj = make_curve("c", [dumbbell, square(1.0, center=(20.0, 0.0))])
    edit(obj)
    ops.curve_toolkit_offset(distance=-0.4)
    object_mode()
    # The dumbbell, its two offset pieces, and the untouched square.
    assert spline_count(obj) == 4, f"{spline_count(obj)} splines"
    assert none_selected(data_of(obj, 0)), "the dumbbell stays, deselected"
    assert all_selected(data_of(obj, 1)) and all_selected(data_of(obj, 2))
    assert none_selected(data_of(obj, 3)), "the untouched square keeps its place, last"


# -----------------------------------------------------------------------------
# Primitive Curves: the panel order
# -----------------------------------------------------------------------------

@test
def primitives_draw_their_size_before_align_location_rotation():
    expected = {
        "ETR_OT_curve_toolkit_add_line": ("radius",),
        "ETR_OT_curve_toolkit_add_bezier": ("radius",),
        "ETR_OT_curve_toolkit_add_rectangle": ("width", "height"),
        "ETR_OT_curve_toolkit_add_polygon": ("sides", "radius"),
        "ETR_OT_curve_toolkit_add_circle": ("radius",),
    }
    for cls in prim.classes:
        names = tuple(cls.size_properties or cls.unit_properties)
        assert names == expected[cls.__name__], f"{cls.__name__}: {names}"
        assert "draw" in vars(prim.AddCurvePrimitive), "the order needs a draw() of our own"
        props = cls.__annotations__ if hasattr(cls, "__annotations__") else {}
        for name in names:
            assert name in props or hasattr(cls, name), f"{cls.__name__} has no '{name}'"


# -----------------------------------------------------------------------------
# Primitive Curves in Object Mode
# -----------------------------------------------------------------------------

@test
def primitives_in_object_mode_make_one_object_each():
    reset()
    cases = (
        (ops.curve_toolkit_add_line, {"radius": 1.0}, 'POLY', 2, False),
        (ops.curve_toolkit_add_bezier, {"radius": 1.0}, 'BEZIER', 2, False),
        (ops.curve_toolkit_add_rectangle, {"width": 2.0, "height": 4.0}, 'POLY', 4, True),
        (ops.curve_toolkit_add_polygon, {"sides": 5, "radius": 1.0}, 'POLY', 5, True),
        (ops.curve_toolkit_add_circle, {"radius": 1.0}, 'BEZIER', 4, True),
    )
    for index, (op, kwargs, kind, count, cyclic) in enumerate(cases, start=1):
        op(**kwargs)
        assert len(bpy.context.scene.objects) == index
        obj = bpy.context.active_object
        assert obj.type == 'CURVE' and spline_count(obj) == 1
        data = data_of(obj)
        assert data.kind == kind and len(data.points) == count and data.cyclic is cyclic
        assert all_selected(data)


# -----------------------------------------------------------------------------
# Primitive Curves in Edit Mode
# -----------------------------------------------------------------------------

@test
def primitives_in_edit_mode_add_a_spline_to_the_curve():
    reset()
    obj = make_curve("host", [poly([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])])
    before = coords(data_of(obj))
    objects_before = len(bpy.context.scene.objects)
    edit(obj)
    ops.curve_toolkit_add_circle(radius=1.0, location=(0.0, 0.0, 0.0))
    object_mode()

    assert len(bpy.context.scene.objects) == objects_before, "no new object in Edit Mode"
    assert spline_count(obj) == 2
    assert coords(data_of(obj, 0)) == before, "the spline that was there changed"
    assert none_selected(data_of(obj, 0)), "only the new spline should be selected"
    new = data_of(obj, 1)
    assert new.kind == 'BEZIER' and new.cyclic and len(new.points) == 4
    assert all_selected(new)


@test
def primitives_in_edit_mode_land_on_the_cursor_in_world_space():
    """Size and position are the ones of the scene: the transform of the object
    being edited is taken out of the shape."""
    reset()
    obj = make_curve(
        "host", [poly([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])],
        loc=(2.0, -1.0, 0.5), rot=(0.0, 0.0, math.radians(37.0)), scale=(2.0, 2.0, 2.0))
    edit(obj)
    ops.curve_toolkit_add_circle(radius=1.0, location=(5.0, 4.0, 3.0))
    object_mode()

    pts = world_points(obj, 1)
    center = sum(pts, Vector()) / len(pts)
    assert (center - Vector((5.0, 4.0, 3.0))).length < 1e-5, tuple(center)
    for p in pts:
        assert abs((p - center).length - 1.0) < 1e-5, (p - center).length


@test
def primitives_in_edit_mode_compensate_a_non_uniform_scale():
    reset()
    obj = make_curve(
        "host", [poly([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])], scale=(3.0, 1.0, 1.0))
    edit(obj)
    ops.curve_toolkit_add_polygon(sides=4, radius=1.0, location=(0.0, 0.0, 0.0))
    object_mode()

    pts = world_points(obj, 1)
    for p in pts:
        assert abs(p.length - 1.0) < 1e-5, f"world radius {p.length}"


@test
def primitives_in_edit_mode_use_the_3d_cursor_by_default():
    reset()
    bpy.context.scene.cursor.location = (1.0, 2.0, 3.0)
    obj = make_curve("host", [poly([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])], loc=(4.0, 0.0, 0.0))
    edit(obj)
    ops.curve_toolkit_add_rectangle(width=2.0, height=2.0)
    object_mode()

    pts = world_points(obj, 1)
    center = sum(pts, Vector()) / len(pts)
    assert (center - Vector((1.0, 2.0, 3.0))).length < 1e-5, tuple(center)


@test
def primitives_are_disabled_in_the_edit_mode_of_a_mesh():
    reset()
    mesh = bpy.data.meshes.new("m")
    mesh.from_pydata([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], [(0, 1)], [])
    obj = bpy.data.objects.new("m", mesh)
    bpy.context.scene.collection.objects.link(obj)
    select_only(obj)
    bpy.ops.object.mode_set(mode='EDIT')
    for op in (ops.curve_toolkit_add_line, ops.curve_toolkit_add_circle,
               ops.curve_toolkit_add_rectangle, ops.curve_toolkit_add_polygon,
               ops.curve_toolkit_add_bezier):
        assert cancelled(op), f"{op} should not poll in the Edit Mode of a mesh"
    object_mode()
    assert len(mesh.vertices) == 2


@test
def primitives_in_edit_mode_warn_on_a_2d_curve_and_still_add_the_spline():
    reset()
    obj = make_curve("host", [square(1.0)], dims='2D')
    edit(obj)
    ops.curve_toolkit_add_circle(radius=1.0, rotation=(math.radians(90.0), 0.0, 0.0))
    object_mode()
    assert spline_count(obj) == 2
    new = data_of(obj, 1)
    assert any(abs(p.co[2]) > 1e-6 for p in new.points), "the rotation is still written"


# -----------------------------------------------------------------------------
# Extend Curve
# -----------------------------------------------------------------------------

def bezier(points, cyclic=False, select=(), handles=None, types=('AUTO', 'AUTO')):
    """Bezier spline; `handles` = {index: (hl, hr)} for explicit handles."""
    pts = []
    for i, p in enumerate(points):
        hl, hr = (handles or {}).get(i, (p, p))
        pts.append(sd.PointData(
            co=tuple(p), hl=tuple(hl), hr=tuple(hr), hlt=types[0], hrt=types[1],
            select=(i in select), select_left=(i in select), select_right=(i in select)))
    return sd.SplineData('BEZIER', pts, cyclic, {"resolution_u": 12})


#: Handle length of a quarter of a circle of radius 1, as a cubic.
QUARTER = 4.0 / 3.0 * math.tan(math.pi / 8.0)


def quarter_arc(select=()):
    """An exact-as-a-cubic quarter of a circle of radius 1, from (1, 0) to
    (0, 1), turning counter-clockwise (so it bends to the left)."""
    return bezier(
        [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], select=select,
        handles={
            0: ((1.0, -QUARTER, 0.0), (1.0, QUARTER, 0.0)),
            1: ((QUARTER, 1.0, 0.0), (-QUARTER, 1.0, 0.0)),
        },
        types=('FREE', 'FREE'))


@test
def nice_length_rounds_to_a_round_number():
    assert abs(ext.nice_length(0.16489) - 0.15) < 1e-12, ext.nice_length(0.16489)
    assert abs(ext.nice_length(1.0989) - 1.0) < 1e-12
    assert abs(ext.nice_length(0.0234) - 0.02) < 1e-12
    assert abs(ext.nice_length(12.0) - 10.0) < 1e-12
    assert abs(ext.nice_length(2.8) - 3.0) < 1e-12
    assert ext.nice_length(0.0) == 0.0


@test
def extend_poly_goes_straight_on():
    reset()
    obj = make_curve("c", [poly([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], select=(1,))])
    edit(obj)
    ops.curve_toolkit_extend(distance=0.5)
    object_mode()

    data = data_of(obj)
    assert len(data.points) == 3, len(data.points)
    assert data.points[0].co[0] == 0.0 and data.points[1].co[0] == 1.0, "the curve moved"
    assert abs(data.points[2].co[0] - 1.5) < 1e-6, data.points[2].co
    assert data.points[2].select, "the new end point should be the selected one"
    assert not data.points[1].select, "the point it grew from should be deselected"


@test
def extend_from_the_start_point_keeps_the_order():
    reset()
    obj = make_curve("c", [poly([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], select=(0,))])
    edit(obj)
    ops.curve_toolkit_extend(distance=0.5)
    object_mode()

    data = data_of(obj)
    xs = [round(p.co[0], 6) for p in data.points]
    assert xs == [-0.5, 0.0, 1.0], xs
    assert data.points[0].select and not data.points[1].select


@test
def extend_takes_its_default_distance_from_the_size_of_the_spline():
    """15% of the largest side of the bounding box, rounded: 1.0989 -> 0.15."""
    reset()
    obj = make_curve("c", [poly([(0.0, 0.0, 0.0), (1.0989, 0.0, 0.0)], select=(1,))])
    edit(obj)
    ops.curve_toolkit_extend()
    object_mode()
    data = data_of(obj)
    assert abs(data.points[2].co[0] - (1.0989 + 0.15)) < 1e-5, data.points[2].co


@test
def extend_default_distance_follows_the_scale_of_the_object():
    reset()
    obj = make_curve("c", [poly([(0.0, 0.0, 0.0), (1.0989, 0.0, 0.0)], select=(1,))],
                     scale=(2.0, 2.0, 2.0))
    edit(obj)
    ops.curve_toolkit_extend()
    object_mode()
    # The spline is 2.1978 in the scene: 15% is 0.3297, rounded to 0.3, which
    # is 0.15 in the local space of the object.
    data = data_of(obj)
    assert abs(data.points[2].co[0] - (1.0989 + 0.15)) < 1e-5, data.points[2].co


@test
def extend_poly_works_in_3d():
    reset()
    direction = Vector((1.0, 2.0, 3.0)).normalized()
    start = Vector((0.0, 0.0, 0.0))
    end = start + direction * 2.0
    obj = make_curve("c", [poly([tuple(start), tuple(end)], select=(1,))])
    edit(obj)
    ops.curve_toolkit_extend(distance=1.0)
    object_mode()
    data = data_of(obj)
    assert (Vector(data.points[2].co) - (end + direction)).length < 1e-5, data.points[2].co


@test
def extend_bezier_automatic_continues_the_circle():
    """A quarter of a circle of radius 1 extended by another quarter of its
    length lands on the circle, a quarter further round."""
    reset()
    obj = make_curve("c", [quarter_arc(select=(1,))])
    edit(obj)
    ops.curve_toolkit_extend(distance=math.pi / 2.0, mode='AUTOMATIC')
    object_mode()

    data = data_of(obj)
    assert len(data.points) == 3, f"{len(data.points)} points (one arc, one new point)"
    assert data.points[1].co == (0.0, 1.0, 0.0), "the curve moved"
    # The curvature read from a cubic quarter circle is 0.9785 instead of 1, so
    # the new end lands a couple of percent short of (-1, 0, 0).
    end = Vector(data.points[2].co)
    assert (end - Vector((-1.0, 0.0, 0.0))).length < 0.05, tuple(end)
    assert abs(end.z) < 1e-9, "a flat curve must stay flat"


@test
def extend_bezier_automatic_keeps_the_shape_that_was_there():
    reset()
    arc = quarter_arc(select=(1,))
    arc.points[0].hlt = arc.points[0].hrt = 'AUTO'
    arc.points[1].hlt = arc.points[1].hrt = 'AUTO'
    obj = make_curve("c", [arc])
    before = data_of(obj)
    edit(obj)
    ops.curve_toolkit_extend(distance=0.5)
    object_mode()

    data = data_of(obj)
    end = data.points[1]
    assert end.co == before.points[1].co
    assert all(abs(a - b) < 1e-6 for a, b in zip(end.hl, before.points[1].hl)), (
        f"the handle that arrives moved: {end.hl} != {before.points[1].hl}")
    assert end.hlt == 'FREE', (
        f"an Auto handle must be frozen as Free, not {end.hlt}, or Blender recalculates it")
    assert all(abs(a - b) < 1e-6 for a, b in zip(data.points[0].hr, before.points[0].hr)), (
        "the handle of the point before moved")


@test
def extend_manual_bends_to_the_right_and_to_the_left():
    """The Curvature angle is the turn of the arc itself: a quarter of a
    circle of arc length 1 has radius 2 / pi."""
    for sign, name in ((1.0, "right"), (-1.0, "left")):
        reset()
        line = bezier(
            [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], select=(1,),
            handles={0: ((-1.0 / 3.0, 0.0, 0.0), (1.0 / 3.0, 0.0, 0.0)),
                     1: ((2.0 / 3.0, 0.0, 0.0), (4.0 / 3.0, 0.0, 0.0))},
            types=('FREE', 'FREE'))
        obj = make_curve("c", [line])
        edit(obj)
        ops.curve_toolkit_extend(
            distance=1.0, mode='MANUAL', curvature=sign * math.pi / 2.0)
        object_mode()

        data = data_of(obj)
        end = Vector(data.points[-1].co)
        # A quarter of a circle of arc length 1: radius 2/pi, so the end point
        # is one radius further along X and one radius to the side.
        radius = 1.0 / (math.pi / 2.0)
        want = Vector((1.0 + radius, -sign * radius, 0.0))
        assert (end - want).length < 1e-4, f"{name}: {tuple(end)} != {tuple(want)}"


@test
def extend_manual_with_zero_curvature_goes_straight():
    reset()
    line = bezier(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], select=(1,),
        handles={0: ((-1.0 / 3.0, 0.0, 0.0), (1.0 / 3.0, 0.0, 0.0)),
                 1: ((2.0 / 3.0, 0.0, 0.0), (4.0 / 3.0, 0.0, 0.0))},
        types=('FREE', 'FREE'))
    obj = make_curve("c", [line])
    edit(obj)
    ops.curve_toolkit_extend(distance=0.9, mode='MANUAL', curvature=0.0)
    object_mode()

    data = data_of(obj)
    assert len(data.points) == 3
    assert abs(data.points[2].co[0] - 1.9) < 1e-6, data.points[2].co
    assert data.points[1].hrt == 'VECTOR', (
        f"a straight piece is what a Vector handle does, not {data.points[1].hrt}")


@test
def extend_a_turn_of_more_than_90_degrees_comes_in_as_several_cubics():
    reset()
    obj = make_curve("c", [quarter_arc(select=(1,))])
    edit(obj)
    # Three quarters of the circle: about 270 degrees, so three cubics.
    ops.curve_toolkit_extend(distance=3.0 * math.pi / 2.0, mode='AUTOMATIC')
    object_mode()
    data = data_of(obj)
    assert len(data.points) == 5, f"{len(data.points)} points"
    for p in data.points[2:]:
        assert abs(Vector(p.co).length - 1.0) < 0.05, "every new point sits on the circle"


@test
def extend_manual_bends_in_the_plane_of_a_3d_curve():
    """A curve that does not lie in the local XY plane bends in the plane it
    is bending in, so the extension stays in it."""
    reset()
    arc = quarter_arc(select=(1,))
    for p in arc.points:                       # the same arc, in the XZ plane
        p.co = (p.co[0], 0.0, p.co[1])
        p.hl = (p.hl[0], 0.0, p.hl[1])
        p.hr = (p.hr[0], 0.0, p.hr[1])
    obj = make_curve("c", [arc])
    edit(obj)
    ops.curve_toolkit_extend(distance=1.0, mode='MANUAL', curvature=math.pi / 2.0)
    object_mode()

    data = data_of(obj)
    assert len(data.points) == 3
    for p in data.points:
        assert abs(p.co[1]) < 1e-6, f"the extension left the plane of the curve: {p.co}"


@test
def spline_plane_finds_the_plane_and_always_the_same_side():
    square_xy = square(1.0)
    assert ext.spline_plane(square_xy) == (0.0, 0.0, 1.0)
    # The order of the points must not flip the side.
    assert ext.spline_plane(sd.inverted(square_xy)) == (0.0, 0.0, 1.0)

    in_xz = poly([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0)])
    assert ext.spline_plane(in_xz) == (0.0, 1.0, 0.0), ext.spline_plane(in_xz)

    tilted = poly([(0.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 1.0, 1.0)])
    normal = ext.spline_plane(tilted)
    assert normal is not None and normal[2] > 0.0, normal

    warped = poly([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 1.0)])
    assert ext.spline_plane(warped) is None, "a warped spline has no plane"

    straight = poly([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])
    assert ext.spline_plane(straight) is None, "two points do not make a plane"


@test
def extend_poly_direction_turns_to_the_right_and_to_the_left():
    for sign, side in ((1.0, -1.0), (-1.0, 1.0)):     # positive turns right (-Y)
        reset()
        obj = make_curve("c", [poly([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], select=(1,))])
        edit(obj)
        ops.curve_toolkit_extend(distance=2.0, direction=sign * math.pi / 2.0)
        object_mode()
        end = Vector(data_of(obj).points[2].co)
        assert (end - Vector((1.0, side * 2.0, 0.0))).length < 1e-5, tuple(end)


@test
def extend_poly_direction_at_45_degrees():
    reset()
    obj = make_curve("c", [poly([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], select=(1,))])
    edit(obj)
    ops.curve_toolkit_extend(distance=math.sqrt(2.0), direction=math.radians(45.0))
    object_mode()
    end = Vector(data_of(obj).points[2].co)
    assert (end - Vector((2.0, -1.0, 0.0))).length < 1e-5, tuple(end)


@test
def extend_poly_direction_uses_the_plane_of_the_spline():
    """A Poly in the XZ plane turns inside it, not in the XY plane."""
    reset()
    obj = make_curve("c", [poly(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 1.0)], select=(2,))])
    edit(obj)
    ops.curve_toolkit_extend(distance=1.0, direction=math.radians(90.0))
    object_mode()
    data = data_of(obj)
    assert len(data.points) == 4
    end = Vector(data.points[3].co)
    assert abs(end.y) < 1e-6, f"the extension left the plane of the spline: {tuple(end)}"
    # The plane of this spline faces +Y, and seen from +Y with +Z up, +X is to
    # the left: travelling along +Z, a turn to the right goes to -X.
    assert (end - Vector((0.0, 0.0, 1.0))).length < 1e-5, tuple(end)


@test
def extend_manual_in_degrees_draws_an_exact_arc():
    """A 90 degree turn leaves the end tangent square to the start one."""
    reset()
    obj = make_curve("c", [quarter_arc(select=(1,))])
    edit(obj)
    ops.curve_toolkit_extend(distance=1.0, mode='MANUAL', curvature=math.radians(90.0))
    object_mode()
    data = data_of(obj)
    end = data.points[-1]
    start_tangent = Vector(data.points[1].hr) - Vector(data.points[1].co)
    end_tangent = Vector(end.co) - Vector(end.hl)
    angle = start_tangent.angle(end_tangent)
    assert abs(math.degrees(angle) - 90.0) < 0.1, math.degrees(angle)


@test
def extend_manual_a_full_circle_lands_where_it_started():
    reset()
    obj = make_curve("c", [quarter_arc(select=(1,))])
    edit(obj)
    ops.curve_toolkit_extend(distance=2.0, mode='MANUAL', curvature=math.radians(360.0))
    object_mode()
    data = data_of(obj)
    assert len(data.points) == 6, f"{len(data.points)} points (four cubics)"
    assert (Vector(data.points[-1].co) - Vector((0.0, 1.0, 0.0))).length < 1e-5, (
        "a full turn must land on the point it grew from")
    assert not data.cyclic, "the spline stays open, as asked"


@test
def extend_works_on_several_end_points_at_once():
    reset()
    obj = make_curve("c", [
        poly([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], select=(1,)),
        poly([(0.0, 5.0, 0.0), (1.0, 5.0, 0.0)], select=(1,)),
    ])
    edit(obj)
    ops.curve_toolkit_extend(distance=0.5)
    object_mode()
    for index in (0, 1):
        data = data_of(obj, index)
        assert len(data.points) == 3, f"spline {index}: {len(data.points)} points"
        assert abs(data.points[2].co[0] - 1.5) < 1e-6
        assert data.points[2].select and not data.points[1].select


@test
def extend_both_ends_of_one_spline():
    reset()
    obj = make_curve("c", [poly([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], select=(0, 1))])
    edit(obj)
    ops.curve_toolkit_extend(distance=0.5)
    object_mode()
    data = data_of(obj)
    xs = [round(p.co[0], 6) for p in data.points]
    assert xs == [-0.5, 0.0, 1.0, 1.5], xs
    assert data.points[0].select and data.points[3].select, (
        "both new ends stay selected, so the extension can be chained")
    assert not data.points[1].select and not data.points[2].select


@test
def extend_leaves_alone_the_points_that_are_not_end_points():
    reset()
    obj = make_curve("c", [poly(
        [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)], select=(1, 2))])
    edit(obj)
    ops.curve_toolkit_extend(distance=0.5)
    object_mode()
    data = data_of(obj)
    xs = [round(p.co[0], 6) for p in data.points]
    assert xs == [0.0, 1.0, 2.0, 2.5], xs
    assert data.points[1].select, "the point in the middle keeps its selection"
    assert data.points[3].select and not data.points[2].select


@test
def extend_can_be_chained():
    reset()
    obj = make_curve("c", [poly([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], select=(1,))])
    edit(obj)
    ops.curve_toolkit_extend(distance=0.5)
    ops.curve_toolkit_extend(distance=0.5)
    object_mode()
    xs = [round(p.co[0], 6) for p in data_of(obj).points]
    assert xs == [0.0, 1.0, 1.5, 2.0], xs


@test
def extend_refuses_what_it_cannot_extend():
    # Nothing selected.
    reset()
    obj = make_curve("c", [poly([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])])
    edit(obj)
    assert cancelled(ops.curve_toolkit_extend, distance=0.5)
    object_mode()
    assert len(data_of(obj).points) == 2

    # A point in the middle.
    reset()
    obj = make_curve(
        "c", [poly([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)], select=(1,))])
    edit(obj)
    assert cancelled(ops.curve_toolkit_extend, distance=0.5)
    object_mode()
    assert len(data_of(obj).points) == 3

    # A closed spline has no end point.
    reset()
    obj = make_curve("c", [square(1.0, select=(0,))])
    edit(obj)
    assert cancelled(ops.curve_toolkit_extend, distance=0.5)
    object_mode()
    assert len(data_of(obj).points) == 4

    # NURBS.
    reset()
    obj = make_curve("c", [nurbs([(0, 0, 0), (1, 0, 0), (2, 1, 0)], select=(2,))])
    edit(obj)
    assert cancelled(ops.curve_toolkit_extend, distance=0.5)
    object_mode()
    assert len(data_of(obj).points) == 3


@test
def extend_is_only_available_in_edit_mode():
    reset()
    obj = make_curve("c", [poly([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], select=(1,))])
    select_only(obj)
    assert cancelled(ops.curve_toolkit_extend, distance=0.5)
    assert len(data_of(obj).points) == 2


# -----------------------------------------------------------------------------
# Separate
# -----------------------------------------------------------------------------

@test
def separate_sends_every_selected_spline_to_its_own_object():
    reset()
    obj = make_curve("c", [
        square(1.0, center=(0.0, 0.0), select=(0,)),     # picked
        square(1.0, center=(5.0, 0.0)),                  # stays
        square(1.0, center=(10.0, 0.0), select=(2,)),    # picked, by one point
    ])
    middle = coords(data_of(obj, 1))
    edit(obj)
    ops.curve_toolkit_separate()

    assert bpy.context.mode == 'OBJECT', "Separate ends in Object Mode"
    names = sorted(o.name for o in bpy.context.scene.objects)
    assert names == ["c", "c_01", "c_02"], names
    assert spline_count(obj) == 1 and coords(data_of(obj)) == middle
    for name, x in (("c_01", 0.0), ("c_02", 10.0)):
        new = bpy.data.objects[name]
        assert spline_count(new) == 1
        xs = [p.co[0] for p in data_of(new).points]
        assert abs(sum(xs) / len(xs) - x) < 1e-6, (name, xs)
    selected = sorted(o.name for o in bpy.context.selected_objects)
    assert selected == ["c_01", "c_02"], f"the new objects are the selected ones: {selected}"


@test
def separate_leaves_one_spline_when_all_are_selected():
    reset()
    obj = make_curve("c", [
        square(1.0, center=(0.0, 0.0), select=(0,)),
        square(1.0, center=(5.0, 0.0), select=(0,)),
        square(1.0, center=(10.0, 0.0), select=(0,)),
    ])
    edit(obj)
    ops.curve_toolkit_separate()
    object_mode()
    assert spline_count(obj) == 1, "one spline stays, so the object is not left empty"
    assert len(bpy.context.scene.objects) == 3


@test
def separate_does_nothing_with_a_single_spline():
    reset()
    obj = make_curve("c", [square(1.0, select=(0,))])
    before = coords(data_of(obj))
    edit(obj)
    assert cancelled(ops.curve_toolkit_separate)
    object_mode()
    assert len(bpy.context.scene.objects) == 1
    assert coords(data_of(obj)) == before


@test
def separate_needs_a_selection():
    reset()
    obj = make_curve("c", [square(1.0), square(1.0, center=(5.0, 0.0))])
    edit(obj)
    assert cancelled(ops.curve_toolkit_separate)
    object_mode()
    assert spline_count(obj) == 2
    assert len(bpy.context.scene.objects) == 1


@test
def separate_works_with_any_curve_type():
    reset()
    obj = make_curve("c", [
        nurbs([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], select=(0,)),
        square(1.0, center=(5.0, 0.0)),
    ])
    edit(obj)
    ops.curve_toolkit_separate()
    object_mode()
    new = bpy.data.objects["c_01"]
    data = data_of(new)
    assert data.kind == 'NURBS' and len(data.points) == 4, (data.kind, len(data.points))
    assert data.settings.get("order_u") == 4, data.settings


@test
def separate_keeps_the_look_and_the_place_of_the_source():
    reset()
    obj = make_curve(
        "c", [square(1.0, select=(0,)), square(1.0, center=(5.0, 0.0))],
        loc=(3.0, 1.0, 0.0), scale=(2.0, 2.0, 2.0))
    obj.data.bevel_depth = 0.25
    material = bpy.data.materials.new("m")
    obj.data.materials.append(material)
    edit(obj)
    ops.curve_toolkit_separate()
    object_mode()

    new = bpy.data.objects["c_01"]
    assert abs(new.data.bevel_depth - 0.25) < 1e-9
    assert new.data.materials and new.data.materials[0] is material
    assert (Vector(new.location) - Vector((3.0, 1.0, 0.0))).length < 1e-6
    assert abs(new.scale[0] - 2.0) < 1e-6
    assert new.users_collection == obj.users_collection


# -----------------------------------------------------------------------------
# Panel
# -----------------------------------------------------------------------------

@test
def panel_cyclic_row_finds_the_active_spline():
    from etr_curve_toolkit import panel

    reset()
    assert panel._active_spline(bpy.context) is None, "no curve, no spline"

    obj = make_curve("c", [square(1.0), poly([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])])
    select_only(obj)
    assert panel._active_spline(bpy.context) is not None, "falls back to the first spline"
    edit(obj)
    spline = panel._active_spline(bpy.context)
    assert spline is not None and spline.type in ('POLY', 'NURBS', 'BEZIER')
    assert not bpy.types.Spline.bl_rna.properties["use_cyclic_u"].is_readonly
    object_mode()


@test
def panel_uses_existing_operators():
    for idname in ("curve.subdivide", "curve.decimate", "curve.dissolve_verts",
                   "curve.cyclic_toggle"):
        module, name = idname.split(".")
        assert hasattr(getattr(bpy.ops, module), name), f"{idname} does not exist"
    for idname in ("curve_toolkit_offset", "curve_toolkit_extend",
                   "curve_toolkit_separate",
                   "curve_toolkit_add_line", "curve_toolkit_add_bezier",
                   "curve_toolkit_add_rectangle", "curve_toolkit_add_polygon",
                   "curve_toolkit_add_circle"):
        assert hasattr(ops, idname), f"etr.{idname} does not exist"


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
            try:
                object_mode()
            except Exception:
                pass
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    toolkit.unregister()
    sys.exit(1 if failed else 0)


main()
