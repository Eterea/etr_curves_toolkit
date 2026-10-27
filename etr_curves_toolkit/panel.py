# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Sidebar panel

3D Viewport > Sidebar (N) > Tool > Curve Toolkit

PANEL_CATEGORY is kept as its own constant (rather than hardcoded in every
panel class) so the sidebar tab can be renamed in one place if needed.
"""

from pathlib import Path

import bpy
import bpy.utils.previews

from .context_utils import resolution_source

PANEL_CATEGORY = "Tool"

_ICONS_DIR = Path(__file__).parent / "icons"
_icons = None  # bpy.utils.previews collection


def _icon(name):
    """Icon id of a custom icon, or 0 if it could not be loaded."""
    if _icons is not None and name in _icons:
        return _icons[name].icon_id
    return 0


def _operator(layout, idname, text="", icon_name=None, icon='NONE'):
    kwargs = {"text": text}
    if icon_name and _icon(icon_name):
        kwargs["icon_value"] = _icon(icon_name)
    else:
        kwargs["icon"] = icon
    return layout.operator(idname, **kwargs)


def _active_spline(context):
    """Active spline of the curve being edited, or None.

    It also exists in Object Mode, where it points at a spline that cannot be
    seen or picked, so the row that shows it is drawn disabled there.
    """
    obj = context.active_object
    if obj is None or obj.type != 'CURVE' or not len(obj.data.splines):
        return None
    return obj.data.splines.active or obj.data.splines[0]


def _equal_slots(layout, count, scale_y=None):
    """`count` slots of equal width that fill the width of the panel.

    Icon-only buttons are square inside a row; inside the column of a split
    they take the whole width, like the buttons that have a text.
    """
    slots = []
    rest = layout
    for divisor in range(count, 1, -1):
        split = rest.split(factor=1.0 / divisor, align=True)
        if scale_y is not None and rest is layout:
            split.scale_y = scale_y
        slots.append(split.column(align=True))
        rest = split.column(align=True)
    slots.append(rest)
    return slots


class ETR_PT_curve_toolkit(bpy.types.Panel):
    bl_idname = "ETR_PT_curve_toolkit"
    bl_label = "Curve Toolkit"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY

    def draw(self, context):
        layout = self.layout
        settings = context.scene.etr_curves_toolkit

        # --- Primitive Curves ----------------------------------------------------
        layout.label(text="Primitive Curves")
        for slot, (idname, icon) in zip(
            _equal_slots(layout, 5, scale_y=1.4),
            (
                ("etr.curve_toolkit_add_line", 'line'),
                ("etr.curve_toolkit_add_bezier", 'bezier'),
                ("etr.curve_toolkit_add_rectangle", 'rectangle'),
                ("etr.curve_toolkit_add_polygon", 'polygon'),
                ("etr.curve_toolkit_add_circle", 'circle'),
            ),
        ):
            _operator(slot, idname, "", icon, icon='CURVE_DATA')

        # --- Curve Booleans and Splits -------------------------------------------
        layout.separator()
        layout.label(text="Curve Booleans")
        for slot, (op, icon) in zip(
            _equal_slots(layout, 3, scale_y=1.4),
            (('UNION', 'union'), ('INTERSECTION', 'intersection'), ('DIFFERENCE', 'difference')),
        ):
            _operator(slot, "etr.curve_toolkit_boolean", "", icon, icon='MOD_BOOLEAN').operation = op

        col = layout.column(align=True)
        col.separator(factor=0.5)
        row = col.row(align=True)
        _operator(row, "etr.curve_toolkit_split", "Split Active", "split_active").mode = 'ACTIVE'
        _operator(row, "etr.curve_toolkit_split", "Split All", "split_all").mode = 'ALL'
        col.operator("etr.curve_toolkit_split_at_points")

        col = layout.column(align=True)
        col.prop(settings, "sources_in_collection")
        col.prop(settings, "results_in_collection")

        # --- Rounds, Bridge & Corners -------------------------------------------
        layout.separator()
        layout.label(text="Rounds, Bridge & Corners")
        row = layout.row(align=True)
        _operator(row, "etr.curve_toolkit_round_corners", "Round", "round")
        _operator(row, "etr.curve_toolkit_bridge_curves", "Bridge", "bridge")

        # Slightly apart from the two above: it is the inverse of Round, and it
        # takes a pair of points instead of a corner or two ends.
        col = layout.column(align=True)
        col.separator(factor=0.5)
        _operator(col, "etr.curve_toolkit_arcs_to_corners", "Arcs to Corners", "corner")

        # --- Utilities ----------------------------------------------------------
        layout.separator()
        layout.label(text="Utilities")
        col = layout.column(align=True)
        col.operator("etr.curve_toolkit_offset")
        col.operator("etr.curve_toolkit_extend")
        col.operator("etr.curve_toolkit_slide_point")

        col = layout.column(align=True)
        col.operator("etr.curve_toolkit_set_first_point")
        col.operator("etr.curve_toolkit_invert_direction")

        # Blender's own Subdivide, Decimate Curve and Dissolve Vertices
        # (Edit Mode). Simplify and Dissolve both take points away, so they go
        # together under Subdivide, which puts them in.
        col = layout.column(align=True)
        col.operator("curve.subdivide")
        row = col.row(align=True)
        row.operator("curve.decimate", text="Simplify")
        row.operator("curve.dissolve_verts", text="Dissolve")

        # Resolution U of many splines at once, on a row of its own: inside the
        # column above, reading down, Resolution looked like a setting of
        # Simplify and Set All like one of Dissolve.
        row = layout.row(align=True)
        sub = row.row(align=True)
        sub.enabled = resolution_source(context) is not None
        sub.prop(settings, "resolution", text="Resolution")
        value = settings.resolution
        row.operator("etr.curve_toolkit_set_resolution", text="Set All").resolution = value

        # On its own: it takes whole splines out of the curve, instead of
        # changing the points of one.
        col = layout.column(align=True)
        col.separator(factor=0.5)
        col.operator("etr.curve_toolkit_separate")
        col.separator(factor=0.5)

        # Merge Pair takes a pair of points wherever they are, so it is the one
        # of the merges the Threshold does not reach: slightly apart from the
        # three below, which it does.
        col = layout.column(align=True)
        col.operator("etr.curve_toolkit_merge_pair")
        col.separator(factor=0.5)

        col = layout.column(align=True)
        col.operator("etr.curve_toolkit_merge_by_distance")
        col.operator("etr.curve_toolkit_join_merge")
        col.operator("etr.curve_toolkit_remove_doubles")
        col.operator("etr.curve_toolkit_remove_strays")
        col.prop(settings, "merge_threshold")

        # Blender's own Cyclic U of the active spline (Sidebar > Item > Active
        # Spline), with its Toggle Cyclic operator next to it, which acts on
        # every selected spline instead of only the active one.
        row = layout.row(align=True)
        spline = _active_spline(context)
        sub = row.row(align=True)
        sub.enabled = context.mode == 'EDIT_CURVE' and spline is not None
        if spline is not None:
            sub.prop(spline, "use_cyclic_u", text="Cyclic")
        else:
            sub.label(text="Cyclic")
        row.operator("curve.cyclic_toggle", text="Toggle All")

        # --- Change Origin ------------------------------------------------------
        layout.separator()
        layout.label(text="Change Origin")
        row = layout.row(align=True)
        for mode, text in (('IN', "In"), ('MID', "Mid"), ('OUT', "Out"), ('GEOMETRY', "Geo")):
            row.operator("etr.curve_toolkit_change_origin", text=text).mode = mode


classes = (ETR_PT_curve_toolkit,)


def register():
    global _icons
    _icons = bpy.utils.previews.new()
    if _ICONS_DIR.is_dir():
        for path in sorted(_ICONS_DIR.glob("*.png")):
            _icons.load(path.stem, str(path), 'IMAGE')
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    global _icons
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    if _icons is not None:
        bpy.utils.previews.remove(_icons)
        _icons = None
