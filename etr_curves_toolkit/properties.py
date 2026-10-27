# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""Scene settings shared by the Curve Toolkit panel and operators."""

import bpy
from bpy.props import BoolProperty, FloatProperty, IntProperty, PointerProperty

from .context_utils import resolution_source

#: Resolution U of a new curve, which is the default of Curve.resolution_u.
DEFAULT_RESOLUTION = 12


def _get_resolution(self):
    """Resolution U of whatever the panel is pointing at (see
    context_utils.resolution_source), or the one of a new curve."""
    try:
        source = resolution_source(bpy.context)
    except AttributeError:
        return DEFAULT_RESOLUTION          # a context without a view layer
    return source.resolution_u if source is not None else DEFAULT_RESOLUTION


def _set_resolution(self, value):
    """Write it back where it came from, as editing the native field does.

    Going through this pair instead of drawing Spline.resolution_u itself is
    what makes Backspace over the field give 12: Blender resets a field to the
    default of its property, and Spline.resolution_u has none (it comes back
    as 0, which the field clamps to 1), while Curve.resolution_u has 12. Here
    the default is 12 whichever of the two the field is showing.
    """
    source = resolution_source(bpy.context)
    if source is not None:
        source.resolution_u = value


class ETR_CurveToolkitSettings(bpy.types.PropertyGroup):
    merge_threshold: FloatProperty(
        name="Threshold",
        description=(
            "Maximum distance between two points to be merged, and longest "
            "spline Remove Strays takes away. Shared by Join & Merge, "
            "Remove Doubles and Remove Strays"
        ),
        default=0.001,
        min=0.0,
        soft_max=1.0,
        precision=4,
        subtype='DISTANCE',
        unit='LENGTH',
    )
    sources_in_collection: BoolProperty(
        name="Place Sources inside a Collection",
        description=(
            "Booleans and Splits: move the original curves into the collection "
            "'Curve Boolean Sources' (created if needed, reused if it exists)"
        ),
        default=False,
    )
    resolution: IntProperty(
        name="Resolution",
        description=(
            "Resolution U: the points Blender computes between every pair of "
            "control points. It reads and writes the active spline in Edit "
            "Mode and the curve itself in Object Mode, the same values as "
            "Sidebar > Item and Object Data > Shape. Set All next to it "
            "gives this value to many splines at once"
        ),
        default=DEFAULT_RESOLUTION,
        min=1,
        soft_max=64,
        max=1024,
        get=_get_resolution,
        set=_set_resolution,
    )
    results_in_collection: BoolProperty(
        name="Place Results inside a Collection",
        description=(
            "Booleans and Splits: put the resulting curves into the collection "
            "'Curve Boolean Results' (created if needed, reused if it exists)"
        ),
        default=False,
    )


classes = (ETR_CurveToolkitSettings,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.etr_curves_toolkit = PointerProperty(type=ETR_CurveToolkitSettings)


def unregister():
    del bpy.types.Scene.etr_curves_toolkit
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
