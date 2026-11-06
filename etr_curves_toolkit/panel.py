# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Sidebar panel

3D Viewport > Sidebar (N) > Eterea Curves

The tools are split into one top-level panel (header-only, its bl_label is
the "Eterea Curves Toolkit" title shown above everything else) and five
sub-panels, one per section (the first one, Create Curves, has four rows of
icon buttons: the primitives, the circles from points, the construction
lines (circle from a segment, tangents, perpendicular) and the construction
points; Shaping Splines holds the tools that reshape a spline: Round, Bridge,
Arcs to Corners, Offset, Extend, Slide Point, Slice and Undo Slice, and last
Handles to Axis and Handles to Lines; Utilities goes from whole splines
(Select All by Type, Separate) to points (Subdivide, Simplify, Dissolve, Set
First Point, Invert Direction, the pairs and the merges) and ends with
Resolution and Cyclic), each with its own native collapse arrow
(bl_parent_id), plus Global Settings at the bottom (the Threshold that tools
of several sections share). Utilities, Change Origin and Global Settings
start collapsed.

PANEL_CATEGORY is kept as its own constant (rather than hardcoded in every
panel class) so the sidebar tab can be renamed in one place if needed.
"""

from pathlib import Path

import bpy
import bpy.utils.previews

from .context_utils import resolution_source

PANEL_CATEGORY = "Eterea Curves"

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
    """Top-level, header-only panel: its bl_label is the title shown above
    every section when the "Eterea Curves" tab is open. All the tools live
    in its sub-panels below.
    """
    bl_idname = "ETR_PT_curve_toolkit"
    bl_label = "Eterea Curves Toolkit"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = PANEL_CATEGORY

    def draw(self, context):
        pass


class ETR_PT_curve_toolkit_primitives(bpy.types.Panel):
    bl_idname = "ETR_PT_curve_toolkit_primitives"
    bl_parent_id = "ETR_PT_curve_toolkit"
    bl_label = "Create Curves"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)

        for slot, (idname, icon) in zip(
            _equal_slots(col, 5, scale_y=1.4),
            (
                ("etr.curve_toolkit_add_line", 'line'),
                ("etr.curve_toolkit_add_bezier", 'bezier'),
                ("etr.curve_toolkit_add_rectangle", 'rectangle'),
                ("etr.curve_toolkit_add_polygon", 'polygon'),
                ("etr.curve_toolkit_add_circle", 'circle'),
            ),
        ):
            _operator(slot, idname, "", icon, icon='CURVE_DATA')

        # Second row: circles and arcs through points that are already in the
        # scene (Edit Mode of a mesh or of a curve).
        for slot, (idname, icon) in zip(
            _equal_slots(col, 5, scale_y=1.4),
            (
                ("etr.curve_toolkit_circle_center_point", 'circle_center_point'),
                ("etr.curve_toolkit_circle_2_points", 'circle_2_points'),
                ("etr.curve_toolkit_circle_3_points", 'circle_3_points'),
                ("etr.curve_toolkit_circle_inscribed", 'circle_inscribed'),
                ("etr.curve_toolkit_circle_tangent_2", 'circle_tangent_2'),
            ),
        ):
            _operator(slot, idname, "", icon, icon='MESH_CIRCLE')

        # Third row: construction lines from what is already there.
        for slot, (idname, icon) in zip(
            _equal_slots(col, 4, scale_y=1.4),
            (
                ("etr.curve_toolkit_circle_segment_center", 'circle_segment_center'),
                ("etr.curve_toolkit_tangents_2_circles", 'tangents_2_circles'),
                ("etr.curve_toolkit_tangents_from_point", 'tangents_from_point'),
                ("etr.curve_toolkit_perpendicular", 'perpendicular'),
            ),
        ):
            _operator(slot, idname, "", icon, icon='CURVE_DATA')

        # Fourth row: construction points (and the lines that join them).
        for slot, (idname, icon) in zip(
            _equal_slots(col, 4, scale_y=1.4),
            (
                ("etr.curve_toolkit_lines_from_points", 'lines_from_points'),
                ("etr.curve_toolkit_points_in_between", 'points_in_between'),
                ("etr.curve_toolkit_points_along_curve", 'points_along_curve'),
                ("etr.curve_toolkit_points_at_intersections", 'points_at_intersections'),
            ),
        ):
            _operator(slot, idname, "", icon, icon='CURVE_DATA')


class ETR_PT_curve_toolkit_booleans(bpy.types.Panel):
    bl_idname = "ETR_PT_curve_toolkit_booleans"
    bl_parent_id = "ETR_PT_curve_toolkit"
    bl_label = "Curve Booleans"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.etr_curves_toolkit

        for slot, (op, icon) in zip(
            _equal_slots(layout, 3, scale_y=1.4),
            (('UNION', 'union'), ('INTERSECTION', 'intersection'), ('DIFFERENCE', 'difference')),
        ):
            _operator(slot, "etr.curve_toolkit_boolean", "", icon, icon='MOD_BOOLEAN').operation = op

        # Part of the group, a little apart: it is neither a Boolean nor a
        # Split, but it works the same way (new curves, the originals kept).
        col = layout.column(align=True)
        col.separator(factor=0.5)
        _operator(col, "etr.curve_toolkit_symmetrize", "Symmetrize", "symmetrize", icon='MOD_MIRROR')

        col = layout.column(align=True)
        col.separator(factor=0.5)
        row = col.row(align=True)
        _operator(row, "etr.curve_toolkit_split", "Split Active", "split_active").mode = 'ACTIVE'
        _operator(row, "etr.curve_toolkit_split_all", "Split All", "split_all")
        col.operator("etr.curve_toolkit_split_at_points")
        col.operator("etr.curve_toolkit_split_at_stray_points")

        col = layout.column(align=True)
        col.prop(settings, "sources_in_collection")
        col.prop(settings, "results_in_collection")


class ETR_PT_curve_toolkit_rounds(bpy.types.Panel):
    """Shaping Splines (its idname keeps the old name of the section, Rounds,
    Bridge & Corners, so nothing that refers to it breaks)."""
    bl_idname = "ETR_PT_curve_toolkit_rounds"
    bl_parent_id = "ETR_PT_curve_toolkit"
    bl_label = "Shaping Splines"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout

        # Round and Bridge, with Arcs to Corners (the inverse of Round) glued
        # under them.
        col = layout.column(align=True)
        row = col.row(align=True)
        _operator(row, "etr.curve_toolkit_round_corners", "Round", "round")
        _operator(row, "etr.curve_toolkit_bridge_curves", "Bridge", "bridge")
        _operator(col, "etr.curve_toolkit_arcs_to_corners", "Arcs to Corners", "corner")

        # The tools that push a spline out, lengthen it, move one of its
        # points along it, or divide it with a seam (and take a seam away).
        col = layout.column(align=True)
        col.separator(factor=0.5)
        _operator(col, "etr.curve_toolkit_offset", "Offset", "offset")
        _operator(col, "etr.curve_toolkit_extend", "Extend", "extend")
        _operator(col, "etr.curve_toolkit_slide_point", "Slide Point", "slide_point")
        row = col.row(align=True)
        _operator(row, "etr.curve_toolkit_slice", "Slice", "slice")
        row.operator("etr.curve_toolkit_undo_slice", text="Undo Slice")

        # The handles, last: onto the axes, or drawn as lines.
        col = layout.column(align=True)
        col.separator(factor=0.5)
        _operator(col, "etr.curve_toolkit_handles_to_axis", "Handles to Axis", "handles_to_axis")
        _operator(col, "etr.curve_toolkit_handles_to_lines", "Handles to Lines",
                  "handles_to_lines")


class ETR_PT_curve_toolkit_utilities(bpy.types.Panel):
    bl_idname = "ETR_PT_curve_toolkit_utilities"
    bl_parent_id = "ETR_PT_curve_toolkit"
    bl_label = "Utilities"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        settings = context.scene.etr_curves_toolkit

        # Whole splines first (v0.24.0): pick them (the strays, or every
        # spline of one type, from a menu that runs as soon as an entry is
        # picked) and send the picked ones to objects of their own.
        col = layout.column(align=True)
        row = col.split(factor=0.55, align=True)
        row.label(text="Select All by Type")
        row.operator_menu_enum("etr.curve_toolkit_select_by_type", "kind", text="Type")
        col = layout.column(align=True)
        col.operator("etr.curve_toolkit_separate")

        # Blender's own Subdivide, Decimate Curve and Dissolve Vertices
        # (Edit Mode). Simplify and Dissolve both take points away, so they go
        # together under Subdivide, which puts them in.
        col = layout.column(align=True)
        col.operator("curve.subdivide")
        row = col.row(align=True)
        row.operator("curve.decimate", text="Simplify")
        row.operator("curve.dissolve_verts", text="Dissolve")

        # The order of the points.
        col = layout.column(align=True)
        col.operator("etr.curve_toolkit_set_first_point")
        col.operator("etr.curve_toolkit_invert_direction")

        # The pairs: two points, wherever they are, so the Threshold (Global
        # Settings) does not reach them. Snap and Swap only move the points;
        # Merge welds them.
        col = layout.column(align=True)
        col.operator("etr.curve_toolkit_snap_pair")
        col.operator("etr.curve_toolkit_merge_pair")
        col.operator("etr.curve_toolkit_swap_pair")

        # The merges that use the Threshold.
        col = layout.column(align=True)
        col.operator("etr.curve_toolkit_merge_by_distance")
        col.operator("etr.curve_toolkit_join_merge")
        col.operator("etr.curve_toolkit_remove_doubles")

        # Resolution U of many splines at once, on a row of its own (inside
        # a column, Resolution looked like a setting of the button above).
        row = layout.row(align=True)
        sub = row.row(align=True)
        sub.enabled = resolution_source(context) is not None
        sub.prop(settings, "resolution", text="Resolution")
        value = settings.resolution
        row.operator("etr.curve_toolkit_set_resolution", text="Set All").resolution = value

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


class ETR_PT_curve_toolkit_origin(bpy.types.Panel):
    bl_idname = "ETR_PT_curve_toolkit_origin"
    bl_parent_id = "ETR_PT_curve_toolkit"
    bl_label = "Change Origin"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        # Object and Edit Mode: the origin goes to the world origin or to the
        # 3D Cursor (each on a line of its own, so the text is not squeezed).
        col.operator("etr.curve_toolkit_origin_to_target", text="To World Origin").target = 'WORLD'
        col.operator("etr.curve_toolkit_origin_to_target", text="To 3D Cursor").target = 'CURSOR'
        # Edit Mode: the origin goes to the selected control point.
        col.operator("etr.curve_toolkit_origin_to_selected")
        # Object Mode: a place along the first spline of each curve (Geo: the
        # center of its bounds). Edit Mode: of the selected spline, and Mid
        # of the segment between two consecutive selected points.
        row = col.row(align=True)
        for mode, text in (('IN', "In"), ('MID', "Mid"), ('OUT', "Out"), ('GEOMETRY', "Geo")):
            row.operator("etr.curve_toolkit_change_origin", text=text).mode = mode


class ETR_PT_curve_toolkit_global(bpy.types.Panel):
    """Settings shared by tools of several sections."""
    bl_idname = "ETR_PT_curve_toolkit_global"
    bl_parent_id = "ETR_PT_curve_toolkit"
    bl_label = "Global Settings"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        settings = context.scene.etr_curves_toolkit
        col = self.layout.column(align=True)
        # Join & Merge, Remove Doubles, Remove Strays (Utilities) and Split
        # at Stray Points (Curve Booleans).
        col.prop(settings, "merge_threshold")


classes = (
    ETR_PT_curve_toolkit,
    ETR_PT_curve_toolkit_primitives,
    ETR_PT_curve_toolkit_booleans,
    ETR_PT_curve_toolkit_rounds,
    ETR_PT_curve_toolkit_utilities,
    ETR_PT_curve_toolkit_origin,
    ETR_PT_curve_toolkit_global,
)


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
