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
points; Booleans & Splits holds the three Booleans, Symmetrize Split, the
Splits and their Backup / Sources / Results options; Shaping Splines holds the tools that reshape a spline: Round, Bridge,
Arcs to Corners, Offset, Extend, Slide Point, Slice and Undo Slice, and last
the Handles row (To Axis, To Lines); Utilities goes from whole splines
(Select All by Type, Separate) to points (Subdivide / Simplify / Dissolve on
one row, Set First Point / Invert Direction on another, the Pair row with
Snap / Merge / Swap, and the merges) and ends with 2D / 3D, Resolution and
Cyclic),
each with its own native collapse arrow (bl_parent_id), plus Global Settings
(the Threshold that tools of several sections share) and Documentation (a
link to the online docs) at the bottom. Utilities, Change Origin, Global
Settings and Documentation start collapsed.

PANEL_CATEGORY is kept as its own constant (rather than hardcoded in every
panel class) so the sidebar tab can be renamed in one place if needed.
"""

from pathlib import Path

import blf
import bpy
import bpy.utils.previews

from .context_utils import resolution_source

PANEL_CATEGORY = "Eterea Curves"

#: Full documentation on GitHub (rendered Markdown), opened by the
#: Documentation sub-panel.
DOCUMENTATION_URL = (
    "https://github.com/Eterea/etr_curves_toolkit/blob/main/etr_curves_toolkit_docs/README.md"
)

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


def _active_curve_data(context):
    """Curve data of the active object, or None."""
    obj = context.active_object
    if obj is None or obj.type != 'CURVE':
        return None
    return obj.data


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


#: Extra room for a label of a labeled row, in UI units (the padding Blender
#: draws around a label, plus a small safety margin).
_LABEL_PADDING = 1.0

#: Width of the Sidebar that is not available to the rows of a sub-panel
#: (panel margins and the indentation of a sub-panel), in UI units. Erring on
#: the large side only makes the label a little wider, never truncated.
_PANEL_MARGINS = 2.0


def _labeled_row(layout, context, text):
    """A row whose first part is a plain label ("Pair", "Handles") and the
    rest a row of aligned buttons, which is returned. The label is not a
    button: it just names what the buttons after it have in common, so their
    own texts can be shorter.

    Blender has no fixed-width layout item: inside a row, ui_units_x is only a
    weight shared with the buttons, so a narrow Sidebar truncated the label.
    Instead, the real width of the text is measured with the UI font (blf) and
    turned into the factor of a split, using the width of the Sidebar. The
    label takes just what its text needs and the buttons all the rest.
    """
    split = layout.split(factor=_label_factor(context, text))
    split.label(text=text)
    return split.row(align=True)


def _label_factor(context, text):
    """Share of the row a label needs, from the width of its text."""
    try:
        scale = context.preferences.system.ui_scale
        unit = 20.0 * scale                       # one UI unit, in pixels
        points = context.preferences.ui_styles[0].widget.points
        blf.size(0, points * scale)
        text_width = blf.dimensions(0, text)[0]
        available = context.region.width - _PANEL_MARGINS * unit
        factor = (text_width + _LABEL_PADDING * unit) / max(available, 1.0)
    except (AttributeError, IndexError, TypeError):
        return 0.3                                # no region or no style
    return min(max(factor, 0.05), 0.5)


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
    """Booleans & Splits (its idname keeps the old name of the section,
    Curve Booleans, so nothing that refers to it breaks)."""
    bl_idname = "ETR_PT_curve_toolkit_booleans"
    bl_parent_id = "ETR_PT_curve_toolkit"
    bl_label = "Booleans & Splits"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'

    def draw(self, context):
        layout = self.layout
        settings = context.scene.etr_curves_toolkit

        # One operator per operation, so each tooltip says which one it is.
        for slot, (idname, icon) in zip(
            _equal_slots(layout, 3, scale_y=1.4),
            (
                ("etr.curve_toolkit_boolean_union", 'union'),
                ("etr.curve_toolkit_boolean_intersection", 'intersection'),
                ("etr.curve_toolkit_boolean_difference", 'difference'),
            ),
        ):
            _operator(slot, idname, "", icon, icon='MOD_BOOLEAN')

        # A Split too (what crosses the axis is cut there), drawn a little
        # apart.
        col = layout.column(align=True)
        col.separator(factor=0.5)
        _operator(col, "etr.curve_toolkit_symmetrize", "Symmetrize Split", "symmetrize",
                  icon='MOD_MIRROR')

        col = layout.column(align=True)
        col.separator(factor=0.5)
        row = col.row(align=True)
        _operator(row, "etr.curve_toolkit_split", "Split Active", "split_active").mode = 'ACTIVE'
        _operator(row, "etr.curve_toolkit_split_all", "Split All", "split_all")
        col.operator("etr.curve_toolkit_split_at_points")
        col.operator("etr.curve_toolkit_split_at_stray_points")

        # Object Mode always keeps the originals (and can place them and the
        # results in collections). Edit Mode keeps a backup only when asked,
        # and the results stay in the curve being edited.
        edit = context.mode == 'EDIT_CURVE'
        col = layout.column(align=True)
        sub = col.row(align=True)
        sub.enabled = edit
        sub.prop(settings, "backup_in_edit")
        sub = col.row(align=True)
        sub.enabled = not edit or settings.backup_in_edit
        sub.prop(settings, "sources_in_collection")
        sub = col.row(align=True)
        sub.enabled = not edit
        sub.prop(settings, "results_in_collection")


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

        # The handles, last: onto the axes, or drawn as lines (v0.25.0: one
        # row, "Handles" as a label in front of the two buttons).
        col = layout.column(align=True)
        col.separator(factor=0.5)
        # Text only: their icons (handles_to_axis, handles_to_lines) stay in
        # the icons folder for a later layout of the panel.
        row = _labeled_row(col, context, "Handles")
        row.operator("etr.curve_toolkit_handles_to_axis", text="To Axis")
        row.operator("etr.curve_toolkit_handles_to_lines", text="To Lines")


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
        # (Edit Mode), on one row: Subdivide puts points in, Simplify and
        # Dissolve take them away.
        col = layout.column(align=True)
        row = col.row(align=True)
        row.operator("curve.subdivide", text="Subdivide")
        row.operator("curve.decimate", text="Simplify")
        row.operator("curve.dissolve_verts", text="Dissolve")

        # The order of the points, on one row, a little apart from the row
        # above.
        col = layout.column(align=True)
        row = col.row(align=True)
        row.operator("etr.curve_toolkit_set_first_point")
        row.operator("etr.curve_toolkit_invert_direction")

        # The pairs: two points, wherever they are, so the Threshold (Global
        # Settings) does not reach them. Snap and Swap only move the points;
        # Merge welds them. One row, "Pair" as a label in front.
        col = layout.column(align=True)
        row = _labeled_row(col, context, "Pair")
        row.operator("etr.curve_toolkit_snap_pair", text="Snap")
        row.operator("etr.curve_toolkit_merge_pair", text="Merge")
        row.operator("etr.curve_toolkit_swap_pair", text="Swap")

        # The merges that use the Threshold.
        col = layout.column(align=True)
        col.operator("etr.curve_toolkit_merge_by_distance")
        col.operator("etr.curve_toolkit_join_merge")
        col.operator("etr.curve_toolkit_remove_doubles")

        # 2D or 3D, the curve setting of Object Data > Shape: the two buttons
        # show (and set) the one of the active curve, Set All gives it to
        # every selected curve. Three buttons of the same width.
        curve = _active_curve_data(context)
        slots = _equal_slots(layout.column(align=True), 3)
        for slot, value in zip(slots[:2], ('2D', '3D')):
            slot.enabled = curve is not None
            if curve is not None:
                slot.prop_enum(curve, "dimensions", value)
            else:
                slot.operator("etr.curve_toolkit_set_dimensions", text=value).dimensions = value
        op = slots[2].operator("etr.curve_toolkit_set_dimensions", text="Set All")
        if curve is not None:
            op.dimensions = curve.dimensions

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
        # at Stray Points (Booleans & Splits).
        col.prop(settings, "merge_threshold")


class ETR_PT_curve_toolkit_documentation(bpy.types.Panel):
    """Last sub-panel: a link to the online documentation, which is not part
    of the installed Extension (it lives on GitHub, in the
    etr_curves_toolkit_docs folder of the repository). It uses Blender's own
    wm.url_open operator and the same HELP icon as the Documentation panel of
    the Eterea Blender Tools kit."""
    bl_idname = "ETR_PT_curve_toolkit_documentation"
    bl_parent_id = "ETR_PT_curve_toolkit"
    bl_label = "Documentation"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        self.layout.operator(
            "wm.url_open", text="Open Online Documentation", icon='HELP'
        ).url = DOCUMENTATION_URL


classes = (
    ETR_PT_curve_toolkit,
    ETR_PT_curve_toolkit_primitives,
    ETR_PT_curve_toolkit_booleans,
    ETR_PT_curve_toolkit_rounds,
    ETR_PT_curve_toolkit_utilities,
    ETR_PT_curve_toolkit_origin,
    ETR_PT_curve_toolkit_global,
    ETR_PT_curve_toolkit_documentation,
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
