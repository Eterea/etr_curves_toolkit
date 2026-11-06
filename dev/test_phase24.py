# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Tests of the Phase 24 changes of Curve Toolkit (v0.24.0): Symmetrize finishes
(so its F9 panel opens) when there is nothing on the side that is kept, the
new order of Shaping Splines and Utilities, and the palette icons (the PNG
files and the SVG sheet of make_icons.py). With Blender as a Python module:

    python test_phase24.py <folder that contains the etr_curves_toolkit package>
"""

import importlib.util
import re
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, sys.argv[1])

import bpy  # noqa: E402

import etr_curves_toolkit as toolkit  # noqa: E402

toolkit.register()
ops = bpy.ops.etr


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if not hasattr(bpy.types.Scene, "etr_curves_toolkit"):
        toolkit.register()


def run(op, **kw):
    try:
        return op(**kw)
    except RuntimeError:
        return {'CANCELLED'}


def make(name, points, cyclic=True):
    """A Poly curve on the XY plane, selected and active."""
    cu = bpy.data.curves.new(name, 'CURVE')
    s = cu.splines.new('POLY')
    s.points.add(len(points) - 1)
    for sp, (x, y) in zip(s.points, points):
        sp.co = (x, y, 0.0, 1.0)
    s.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, cu)
    bpy.context.scene.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# -----------------------------------------------------------------------------
# Symmetrize
# -----------------------------------------------------------------------------

@test
def symmetrize_nothing_kept_finishes_so_f9_opens():
    reset()
    src = make("R", [(1, 0), (3, 0), (3, 2), (1, 2)])
    assert run(ops.curve_toolkit_symmetrize, view='TOP',
               direction='LEFT_TO_RIGHT') == {'FINISHED'}
    # Nothing made, the source untouched.
    assert len(bpy.data.objects) == 1 and not src.hide_get()
    # What F9 does next: the same call with the other direction.
    assert run(ops.curve_toolkit_symmetrize, view='TOP',
               direction='RIGHT_TO_LEFT') == {'FINISHED'}
    assert len(bpy.data.objects) == 2 and src.hide_get()
    res = bpy.context.active_object
    assert res is not src
    # The square does not reach the axis: it stays, next to its mirror copy.
    assert len(res.data.splines) == 2
    xs = [p.co.x for s in res.data.splines for p in s.points]
    assert abs(min(xs) + 3) < 1e-5 and abs(max(xs) - 3) < 1e-5, xs


@test
def symmetrize_perspective_finishes_without_changes():
    reset()
    make("S", [(-2, -1), (1, -1), (1, 1)])
    assert run(ops.curve_toolkit_symmetrize, view='NONE') == {'FINISHED'}
    assert len(bpy.data.objects) == 1


@test
def symmetrize_not_flat_still_cancels():
    reset()
    cu = bpy.data.curves.new("N", 'CURVE')
    s = cu.splines.new('POLY')
    s.points.add(2)
    for sp, co in zip(s.points, ((-2, -1, 0), (1, -1, 1), (1, 1, 0))):
        sp.co = (*co, 1.0)
    s.use_cyclic_u = True
    obj = bpy.data.objects.new("N", cu)
    bpy.context.scene.collection.objects.link(obj)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    assert run(ops.curve_toolkit_symmetrize, view='TOP') == {'CANCELLED'}


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
    return [c[1][0] for c in fake.mock_calls
            if (c[0].endswith("operator") or c[0].endswith("operator_menu_enum")) and c[1]]


@test
def shaping_splines_handles_last():
    from etr_curves_toolkit import panel
    reset()
    assert _drawn(panel.ETR_PT_curve_toolkit_rounds) == [
        "etr.curve_toolkit_round_corners", "etr.curve_toolkit_bridge_curves",
        "etr.curve_toolkit_arcs_to_corners", "etr.curve_toolkit_offset",
        "etr.curve_toolkit_extend", "etr.curve_toolkit_slide_point",
        "etr.curve_toolkit_slice", "etr.curve_toolkit_undo_slice",
        "etr.curve_toolkit_handles_to_axis", "etr.curve_toolkit_handles_to_lines"]


@test
def utilities_order():
    from etr_curves_toolkit import panel
    reset()
    assert _drawn(panel.ETR_PT_curve_toolkit_utilities) == [
        "etr.curve_toolkit_select_by_type", "etr.curve_toolkit_separate",
        "curve.subdivide", "curve.decimate", "curve.dissolve_verts",
        "etr.curve_toolkit_set_first_point", "etr.curve_toolkit_invert_direction",
        "etr.curve_toolkit_snap_pair", "etr.curve_toolkit_merge_pair",
        "etr.curve_toolkit_swap_pair",
        "etr.curve_toolkit_merge_by_distance", "etr.curve_toolkit_join_merge",
        "etr.curve_toolkit_remove_doubles",
        "etr.curve_toolkit_set_resolution", "curve.cyclic_toggle"]


# -----------------------------------------------------------------------------
# Icons
# -----------------------------------------------------------------------------

def _make_icons():
    path = Path(__file__).with_name("make_icons.py")
    spec = importlib.util.spec_from_file_location("make_icons", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@test
def every_panel_icon_is_loaded():
    from etr_curves_toolkit import panel
    reset()
    mi = _make_icons()
    for name in mi.PALETTE_ORDER:
        assert name in panel._icons, name
        assert tuple(panel._icons[name].icon_size) == (32, 32), name


@test
def icon_sheet_is_in_panel_order_on_a_32_px_grid():
    mi = _make_icons()
    assert sorted(mi.PALETTE_ORDER) == sorted(mi.ICONS)
    svg = mi.sheet_svg([(n, mi.ICONS[n]()) for n in mi.PALETTE_ORDER])
    assert 'width="192" height="192"' in svg
    found = re.findall(r'<g id="([a-z_0-9]+)" transform="translate\((\d+) (\d+)\)">', svg)
    assert [n for n, _, _ in found] == list(mi.PALETTE_ORDER)
    for i, (_, x, y) in enumerate(found):
        assert (int(x), int(y)) == ((i % 6) * 32, (i // 6) * 32)
    # Clip paths of different icons never share an id.
    ids = re.findall(r'<clipPath id="([^"]+)"', svg)
    assert len(ids) == len(set(ids))
    with tempfile.TemporaryDirectory() as tmp:
        import xml.dom.minidom
        p = Path(tmp) / "sheet.svg"
        p.write_text(svg, encoding="utf-8")
        xml.dom.minidom.parse(str(p))       # well-formed


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
