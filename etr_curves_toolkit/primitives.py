# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Primitive Curves

Five icon buttons that add a simple curve to the scene:

  - Line        a straight Poly curve along the X axis, from -Radius to +Radius.
  - Bezier      the same two-point Bezier curve that Blender's Add > Curve >
                Bezier makes (same shape, same Aligned handles).
  - Rectangle   a closed Poly rectangle on the XY plane (Width x Height).
  - Polygon     a closed regular Poly polygon, first point at 12 o'clock
                (+Y axis), which stays there when Sides changes.
  - Circle      the same four-point Bezier circle that Blender's Add > Curve >
                Circle makes (same shape, same Auto handles).

Every one of them follows the conventions of Blender's own Add operators: the
size, Align (World / View / 3D Cursor), Location and Rotation can be edited
right after the click in the Adjust Last Operation panel (bottom left, or F9),
where the size comes first.

In Object Mode each one adds a new curve object. In the Edit Mode of a curve
they add their shape as one more spline inside that curve instead, where the
3D Cursor is, with the other splines left as they are and only the new one
selected. The size is the size in the scene: the shape is written in the local
space of the object, so the transform of the object is taken out of it (which
means a pre-distorted spline when the object has a non-uniform scale, the same
way Blender adds a mesh primitive in Edit Mode). In the Edit Mode of anything
that is not a curve the buttons are disabled.

Sizes come in at one unit of the length shown in the interface: 1 m in a
metric scene, 1 cm when the Length is set to Centimeters, 1 ft in an imperial
one (see unit_scale). The closed primitives turn counter-clockwise seen from
+Z, so Offset, Round Corners and the Booleans see them all the same way.
"""

import math

import bpy
from bpy.props import FloatProperty, IntProperty
from bpy_extras import object_utils
from mathutils import Vector

from . import spline_data as sd
from .context_utils import EDIT_MODE, edit_scope, has_active_curve, world_matrix

# Handle length of a four-point Bezier circle of radius 1, as Blender's own
# Auto handles compute it: sqrt(2) / 2.5614 (see calchandleNurb_intern).
CIRCLE_HANDLE = math.sqrt(2.0) / 2.5614


# -----------------------------------------------------------------------------
# Units
# -----------------------------------------------------------------------------

# One unit of each length unit, in meters.
_METRIC = {
    'KILOMETERS': 1000.0,
    'METERS': 1.0,
    'CENTIMETERS': 0.01,
    'MILLIMETERS': 0.001,
    'MICROMETERS': 0.000001,
}
_IMPERIAL = {
    'MILES': 1609.344,
    'FEET': 0.3048,
    'INCHES': 0.0254,
    'THOU': 0.0000254,
}


def unit_scale(context):
    """Blender units of one unit of the length shown in the interface.

    A default of 1.0 reads as "1 m" in a metric scene, "1 cm" when the Length
    of the scene is set to Centimeters, "1 ft" in an imperial one, and so on.
    With Length set to Adaptive the base unit of the system is used (meter or
    foot), which is what Blender's own Add operators do. The Unit Scale of the
    scene is taken into account. Without units, the grid of the viewport is.
    """
    unit = context.scene.unit_settings
    if unit.system == 'METRIC':
        meters = _METRIC.get(unit.length_unit, 1.0)
    elif unit.system == 'IMPERIAL':
        meters = _IMPERIAL.get(unit.length_unit, 0.3048)
    else:
        space = context.space_data
        if space is not None and space.type == 'VIEW_3D':
            return space.overlay.grid_scale
        return 1.0
    return meters / max(unit.scale_length, 1e-9)


# -----------------------------------------------------------------------------
# Shared behaviour
# -----------------------------------------------------------------------------

def _point(co, handles=None, handle_type='ALIGNED'):
    """A selected control point, as a new primitive comes in."""
    point = sd.PointData(co=co, select=True)
    if handles is not None:
        point.hl, point.hr = handles
        point.hlt = point.hrt = handle_type
        point.select_left = point.select_right = True
    return point


def _poly(coords, cyclic):
    return sd.SplineData('POLY', [_point(co) for co in coords], cyclic, {})


class AddCurvePrimitive(object_utils.AddObjectHelper):
    """Shared behaviour of the Primitive Curves.

    Subclasses give a name, the names of their size properties (so their
    defaults can follow the units of the scene, and so they are drawn before
    Align, Location and Rotation) and a build() that returns the SplineData of
    the curve, centered on the origin.
    """

    bl_options = {'REGISTER', 'UNDO'}

    #: Size properties (subtype DISTANCE) scaled by the unit of the scene.
    unit_properties = ()
    #: Properties drawn before Align, Location and Rotation. Defaults to
    #: unit_properties, in that order.
    size_properties = ()
    #: Name of the new object and of its curve data.
    curve_name = "Curve"

    @classmethod
    def poll(cls, context):
        if context.mode == EDIT_MODE:
            return has_active_curve(context)
        return context.mode == 'OBJECT'

    def invoke(self, context, event):
        # Only on a fresh click: a tweak in the Adjust Last Operation panel
        # calls execute() with the values already on screen. This is what
        # Blender does for every Add operator (WM_operator_view3d_unit_defaults).
        scale = unit_scale(context)
        if scale != 1.0:
            for name in self.unit_properties:
                if not self.properties.is_property_set(name, ghost=False):
                    setattr(self, name, getattr(self, name) * scale)
        return self.execute(context)

    def draw(self, context):
        """Size first, then the usual Align, Location and Rotation.

        Without this, the properties of AddObjectHelper would come first,
        because they are declared in the base class.
        """
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        for name in (self.size_properties or self.unit_properties):
            layout.prop(self, name)
        layout.separator()
        layout.prop(self, "align")
        layout.prop(self, "location")
        layout.prop(self, "rotation")

    def execute(self, context):
        if context.mode == EDIT_MODE:
            return self.execute_edit(context)
        curve = bpy.data.curves.new(self.curve_name, 'CURVE')
        curve.dimensions = '3D'       # as Blender's own curve primitives
        sd.replace_splines(curve, [self.build()])
        object_utils.object_data_add(context, curve, operator=self, name=self.curve_name)
        return {'FINISHED'}

    # -- Edit Mode -----------------------------------------------------------

    def execute_edit(self, context):
        """Add the primitive as one more spline of the curve being edited."""
        obj = context.active_object
        # Where the new object would have gone in Object Mode (it reads Align,
        # Location and Rotation, and fills them in on a fresh click).
        placement = object_utils.add_object_align_init(context, self)
        try:
            to_local = world_matrix(obj).inverted()
        except ValueError:
            self.report({'ERROR'}, f"'{obj.name}' has a degenerate transform (zero scale)")
            return {'CANCELLED'}

        data = _transformed(self.build(), to_local @ placement)
        flat = _flat_in_xy(data)

        with edit_scope(context):
            curve = obj.data
            _deselect_all(curve)
            sd.write_spline(curve, data)

        if not flat and obj.data.dimensions == '2D':
            self.report(
                {'WARNING'},
                f"'{obj.name}' is a 2D curve: the height of the new spline is ignored, so "
                "the Rotation of the primitive cannot be seen")
        return {'FINISHED'}

    def build(self):
        raise NotImplementedError


def _transformed(data, matrix):
    """Snapshot with every point and handle through `matrix`."""
    for p in data.points:
        p.co = tuple(matrix @ Vector(p.co))
        if data.kind == 'BEZIER':
            p.hl = tuple(matrix @ Vector(p.hl))
            p.hr = tuple(matrix @ Vector(p.hr))
    return data


def _flat_in_xy(data):
    """True when the snapshot lies in the z = 0 plane."""
    coords = [p.co for p in data.points]
    if data.kind == 'BEZIER':
        coords += [p.hl for p in data.points] + [p.hr for p in data.points]
    size = max((max(abs(c[0]), abs(c[1])) for c in coords), default=0.0)
    return all(abs(c[2]) <= 1e-6 * size + 1e-7 for c in coords)


def _deselect_all(curve):
    """Clear the selection of every point of a curve, so that only the spline
    that comes next is selected."""
    for spline in curve.splines:
        if spline.type == 'BEZIER':
            for bp in spline.bezier_points:
                bp.select_control_point = False
                bp.select_left_handle = False
                bp.select_right_handle = False
        else:
            for p in spline.points:
                p.select = False


def _radius_property(description):
    return FloatProperty(
        name="Radius",
        description=description,
        default=1.0,
        min=0.0,
        soft_max=100.0,
        subtype='DISTANCE',
        unit='LENGTH',
    )


# -----------------------------------------------------------------------------
# Line
# -----------------------------------------------------------------------------

class ETR_OT_curve_toolkit_add_line(AddCurvePrimitive, bpy.types.Operator):
    """Add a straight line on the X axis, as a Poly curve with two points, from -Radius to +Radius. In the Edit Mode of a curve, as one more spline inside it"""
    bl_idname = "etr.curve_toolkit_add_line"
    bl_label = "Add Line"

    radius: _radius_property("Half the length of the line")

    unit_properties = ("radius",)
    curve_name = "Line"

    def build(self):
        r = self.radius
        return _poly([(-r, 0.0, 0.0), (r, 0.0, 0.0)], False)


# -----------------------------------------------------------------------------
# Bezier
# -----------------------------------------------------------------------------

class ETR_OT_curve_toolkit_add_bezier(AddCurvePrimitive, bpy.types.Operator):
    """Add a Bezier curve with two points, the same one as Add > Curve > Bezier. In the Edit Mode of a curve, as one more spline inside it"""
    bl_idname = "etr.curve_toolkit_add_bezier"
    bl_label = "Add Bezier"

    radius: _radius_property("Half the width of the curve")

    unit_properties = ("radius",)
    curve_name = "Bezier"

    def build(self):
        r = self.radius
        points = [
            _point((-r, 0.0, 0.0), ((-1.5 * r, -0.5 * r, 0.0), (-0.5 * r, 0.5 * r, 0.0))),
            _point((r, 0.0, 0.0), ((0.0, 0.0, 0.0), (2.0 * r, 0.0, 0.0))),
        ]
        return sd.SplineData('BEZIER', points, False, {})


# -----------------------------------------------------------------------------
# Rectangle
# -----------------------------------------------------------------------------

class ETR_OT_curve_toolkit_add_rectangle(AddCurvePrimitive, bpy.types.Operator):
    """Add a closed rectangle on the XY plane, as a Poly curve with four points. In the Edit Mode of a curve, as one more spline inside it"""
    bl_idname = "etr.curve_toolkit_add_rectangle"
    bl_label = "Add Rectangle"

    width: FloatProperty(
        name="Width",
        description="Size of the rectangle along the X axis",
        default=2.0, min=0.0, soft_max=100.0,
        subtype='DISTANCE', unit='LENGTH',
    )
    height: FloatProperty(
        name="Height",
        description="Size of the rectangle along the Y axis",
        default=2.0, min=0.0, soft_max=100.0,
        subtype='DISTANCE', unit='LENGTH',
    )

    unit_properties = ("width", "height")
    curve_name = "Rectangle"

    def build(self):
        x = self.width / 2.0
        y = self.height / 2.0
        return _poly([(-x, -y, 0.0), (x, -y, 0.0), (x, y, 0.0), (-x, y, 0.0)], True)


# -----------------------------------------------------------------------------
# Polygon
# -----------------------------------------------------------------------------

class ETR_OT_curve_toolkit_add_polygon(AddCurvePrimitive, bpy.types.Operator):
    """Add a closed regular polygon on the XY plane, as a Poly curve. The first point is on the +Y axis (at 12 o'clock) and stays there when the number of sides changes. In the Edit Mode of a curve, as one more spline inside it"""
    bl_idname = "etr.curve_toolkit_add_polygon"
    bl_label = "Add Polygon"

    sides: IntProperty(
        name="Sides",
        description="Number of sides of the polygon",
        default=6, min=3, soft_max=64, max=1024,
    )
    radius: _radius_property("Distance from the center to every point")

    unit_properties = ("radius",)
    # Sides before Radius, as in Blender's own Add > Mesh > Circle.
    size_properties = ("sides", "radius")
    curve_name = "Polygon"

    def build(self):
        r = self.radius
        n = self.sides
        coords = []
        for i in range(n):
            angle = math.pi / 2.0 + 2.0 * math.pi * i / n
            coords.append((r * math.cos(angle), r * math.sin(angle), 0.0))
        return _poly(coords, True)


# -----------------------------------------------------------------------------
# Circle
# -----------------------------------------------------------------------------

class ETR_OT_curve_toolkit_add_circle(AddCurvePrimitive, bpy.types.Operator):
    """Add a closed circle on the XY plane, the same four-point Bezier circle as Add > Curve > Circle. In the Edit Mode of a curve, as one more spline inside it"""
    bl_idname = "etr.curve_toolkit_add_circle"
    bl_label = "Add Circle"

    radius: _radius_property("Radius of the circle")

    unit_properties = ("radius",)
    curve_name = "Circle"

    def build(self):
        r = self.radius
        k = CIRCLE_HANDLE * r
        # Left, bottom, right and top, counter-clockwise seen from +Z. Each
        # handle is tangent to the circle, as Blender's Auto handles leave it.
        points = [
            _point((-r, 0.0, 0.0), ((-r, k, 0.0), (-r, -k, 0.0)), 'AUTO'),
            _point((0.0, -r, 0.0), ((-k, -r, 0.0), (k, -r, 0.0)), 'AUTO'),
            _point((r, 0.0, 0.0), ((r, -k, 0.0), (r, k, 0.0)), 'AUTO'),
            _point((0.0, r, 0.0), ((k, r, 0.0), (-k, r, 0.0)), 'AUTO'),
        ]
        return sd.SplineData('BEZIER', points, True, {})


# -----------------------------------------------------------------------------

classes = (
    ETR_OT_curve_toolkit_add_line,
    ETR_OT_curve_toolkit_add_bezier,
    ETR_OT_curve_toolkit_add_rectangle,
    ETR_OT_curve_toolkit_add_polygon,
    ETR_OT_curve_toolkit_add_circle,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
