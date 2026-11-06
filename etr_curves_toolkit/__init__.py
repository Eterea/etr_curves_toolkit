# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""etr_curves_toolkit - Curve Toolkit

Tools to create, refine and operate on curves (Poly, Bezier and NURBS):
primitive curves, circles and arcs from points, lines from points, points in
between, tangents to 2 circles, perpendiculars, handles to lines, 2D curve
booleans and splits (also at control points and at stray points), round corners, bridge, arc to corner, offset, extend,
slide point, slice and undo slice, snap / merge / swap pairs, and a set of utilities.

Independent Blender Extension with its own installation, documentation and
icons. Its panel lives in the 3D Viewport Sidebar (N) > Eterea Curves.

This __init__.py implements nothing: it imports every module and calls its
own register() / unregister(), the same pattern the Eterea Blender Tools kit
uses.
"""

import importlib
import traceback

# Module names (without the .py extension), in registration order. The panel
# goes last. geometry, spline_data and context_utils are libraries (no
# register function), and so are curve_engine (the pure-Python 2D engine of
# the booleans and splits), offset_engine (the one of the offset) and
# curve_eval (splines as world-space cubics, and the axis views).
MODULES = (
    "properties",
    "primitives",
    "circles",
    "between",
    "points_tools",
    "lines",
    "tangents",
    "perpendicular",
    "handles",
    "booleans",
    "symmetrize",
    "offset",
    "extend",
    "slide",
    "slice",
    "utilities",
    "stray_split",
    "merge",
    "pairs",
    "round_bridge",
    "arcs_to_corners",
    "panel",
)

_submodules = []


def _report_error(action, name):
    print(f"[etr_curves_toolkit] Error {action} '{name}':")
    traceback.print_exc()


def register():
    _submodules.clear()
    for name in MODULES:
        try:
            module = importlib.import_module(f".{name}", __name__)
        except Exception:
            _report_error("importing", name)
            continue
        _submodules.append(module)
    for module in _submodules:
        try:
            module.register()
        except Exception:
            _report_error("registering", module.__name__)


def unregister():
    for module in reversed(_submodules):
        try:
            module.unregister()
        except Exception:
            _report_error("unregistering", module.__name__)
    _submodules.clear()
