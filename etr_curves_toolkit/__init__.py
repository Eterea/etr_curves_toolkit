# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""etr_curves_toolkit - Curve Toolkit

Tools to create, refine and operate on curves (Poly, Bezier and NURBS):
primitive curves, 2D curve booleans and splits, round corners, bridge, offset,
extend, slide point, arc to corner, merges, and a set of utilities.

Independent Blender Extension with its own installation, documentation and
icons. Its panel lives in the 3D Viewport Sidebar (N) > Tool > Curve Toolkit.

This __init__.py implements nothing: it imports every module and calls its
own register() / unregister(), the same pattern the Eterea Blender Tools kit
uses.
"""

import importlib
import traceback

# Module names (without the .py extension), in registration order. The panel
# goes last. geometry, spline_data and context_utils are libraries (no
# register function), and so are curve_engine (the pure-Python 2D engine of
# the booleans and splits) and offset_engine (the one of the offset).
MODULES = (
    "properties",
    "primitives",
    "booleans",
    "offset",
    "extend",
    "slide",
    "utilities",
    "merge",
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
