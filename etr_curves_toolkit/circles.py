# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Circles from Points

Six icon buttons (second row of Create Curves) that draw a Bezier circle, or
an arc of it, from points that are already in the scene:

  - Center & Point      2 points: the active one is the center, the other one
                        is on the circle.
  - 2 Points            2 points at the ends of a diameter: the active one at
                        6 o'clock, the other one at 12 o'clock.
  - 3 Points            3 points on the circle (the only circle through them).
                        The active one is where the circle starts.
  - Segment & Center    3 points: the active one is the center, the other two
                        give a straight line the circle is tangent to.
  - Inscribed           3 points: the circle inscribed in their triangle. It
                        starts on the side opposite the active one.
  - Tangent to 2        3 points: a circle tangent to the two segments that
                        meet at the active one, with an editable Radius (the
                        one of the inscribed circle to begin with).

The points are the selected vertices of a mesh (Edit Mode of a mesh) or the
selected control points of a curve (Edit Mode of a curve; handles do not
count). From a mesh, a new curve object is made, and it is left in Edit Mode.
From a curve, the circle goes into that same curve as one more spline, and
the Edit Mode is kept. In Object Mode, or in the Edit Mode of anything else,
the buttons are disabled.

Plane. Except for 3 Points, Inscribed and Tangent to 2 (whose plane is the
one of their points), the circle
is drawn on a world plane chosen by the view of the 3D Viewport: Top/Bottom
give XY, Front/Back XZ, Right/Left YZ (in orthographic or perspective), and a
free perspective or the camera view count as Top. The points are projected
onto that plane, at the height of the active point along its normal. The view
is read when the button is clicked and can be changed afterwards in the
Adjust Last Operation panel (F9).

Start and direction. The spline starts at 12 o'clock and turns clockwise, as
seen from the view:

  - Oriented (default on): 12 o'clock is the "start point" of the tool: the
    point on the circle (Center & Point), the non-active point (2 Points), the
    active point (3 Points) or the point where the circle touches the line
    (Segment & Center).
  - Without it, the four points sit on the axes of the plane, with 12 o'clock
    up on the screen.
  - Normal Rotation (default 0): turns it about its center, in its plane.
  - Arc (default off): only Angle degrees of it, from 12 o'clock, clockwise
    for a positive angle and counter-clockwise for a negative one.
  - Capable Arc (3 Points, with Arc): the only arc that goes through the 3
    points, from the first one, through the second, to the third, the Goal
    (the points taken in order, around, so that the Goal is the last one).
    Oriented, Angle and Normal Rotation do not apply and are greyed out.
  - Add Helper Points (every tool but Center & Point): stray control points
    (Poly splines of a single point) at every point where the circle touches a
    line, and at its center when the center was not one of the picked points.

Selection order. Blender keeps the order in which mesh vertices are picked
(select history), so with a mesh the active vertex is always known. For curves
Blender does not give add-ons the active control point, only the active
spline (the one of the point clicked last). So the active point is found as
the only selected point of the active spline. When that does not tell it
(two of the points in the same spline, or a box selection), the points are
taken in the order of the curve, the last one as the active one.

Goal. Whatever the active point is, the F9 panel lets the user change his
mind: "Toggle Goal" swaps the parts of the two points of the 2-point tools,
and "Goal" (1, 2 or 3) picks which of the 3 points plays the part of the
active one in the 3-point tools.
"""

import math

import bmesh
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty
from mathutils import Matrix, Vector

from . import geometry as geo
from . import spline_data as sd
from .context_utils import EDIT_MODE, edit_scope, is_curve, unique_name, world_matrix
from .primitives import CIRCLE_HANDLE

EDIT_MESH = 'EDIT_MESH'

#: The six axis views: normal of the plane (towards the viewer) and the axis
#: that is up on the screen, as Blender's Numpad views leave them.
VIEWS = {
    'TOP': ((0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    'BOTTOM': ((0.0, 0.0, -1.0), (0.0, -1.0, 0.0)),
    'FRONT': ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    'BACK': ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    'RIGHT': ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    'LEFT': ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
}

_VIEW_ITEMS = (
    ('TOP', "Top", "XY plane, seen from above (also a free perspective and the camera view)"),
    ('BOTTOM', "Bottom", "XY plane, seen from below"),
    ('FRONT', "Front", "XZ plane, seen from the front (-Y)"),
    ('BACK', "Back", "XZ plane, seen from the back (+Y)"),
    ('RIGHT', "Right", "YZ plane, seen from the right (+X)"),
    ('LEFT', "Left", "YZ plane, seen from the left (-X)"),
)

#: How close (as a cosine) the view has to be to an axis to count as that view.
_ALIGNED = 1.0 - 1e-5

#: An arc this close to a whole turn is drawn as a closed circle.
_FULL_TURN = 2.0 * math.pi - 1e-6

#: Largest angle of one Bezier piece of an arc (a quarter of a turn).
_MAX_STEP = math.pi / 2.0 * (1.0 + 1e-6)


class Fail(Exception):
    """A message for the user; nothing has been changed."""


# -----------------------------------------------------------------------------
# The view
# -----------------------------------------------------------------------------

def _region_3d(context):
    space = context.space_data
    if space is not None and space.type == 'VIEW_3D':
        return space.region_3d
    rv3d = getattr(context, "region_data", None)
    if isinstance(rv3d, bpy.types.RegionView3D):
        return rv3d
    screen = context.screen
    for area in (screen.areas if screen is not None else ()):
        if area.type == 'VIEW_3D':
            return area.spaces.active.region_3d
    return None


def read_view(context):
    """(view name, normal towards the viewer, up on the screen) of the 3D
    Viewport. The name is one of VIEWS: a free view and the camera view give
    'TOP'. Without a 3D Viewport, Top."""
    rv3d = _region_3d(context)
    if rv3d is None:
        normal, up = VIEWS['TOP']
        return 'TOP', normal, up
    rotation = rv3d.view_rotation
    camera = context.scene.camera
    if rv3d.view_perspective == 'CAMERA' and camera is not None:
        rotation = world_matrix(camera).to_quaternion()
    normal = tuple(rotation @ Vector((0.0, 0.0, 1.0)))
    up = tuple(rotation @ Vector((0.0, 1.0, 0.0)))
    if rv3d.view_perspective != 'CAMERA':
        for name, (axis, _) in VIEWS.items():
            if geo.dot(normal, axis) > _ALIGNED:
                return name, normal, up
    return 'TOP', normal, up


def snapped_up(view, view_normal, view_up):
    """12 o'clock of a circle drawn in the plane of `view`.

    When the 3D Viewport really is in that view, the axis of the plane that is
    up on the screen (so a rolled view is followed). Otherwise, the usual one
    of the view (+Y for Top, +Z for Front...).
    """
    normal, default = VIEWS[view]
    if geo.dot(view_normal, normal) > _ALIGNED:
        flat = geo.sub(view_up, geo.mul(normal, geo.dot(view_up, normal)))
        best, best_dot = None, 0.5
        for axis in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
            for sign in (1.0, -1.0):
                d = geo.dot(flat, geo.mul(axis, sign))
                if d > best_dot:
                    best, best_dot = geo.mul(axis, sign), d
        if best is not None:
            return best
    return default


def up_in_plane(normal, view_up):
    """12 o'clock of a circle in a plane of any orientation: what is up on the
    screen, brought into the plane; failing that, world Z, Y or X."""
    for up in (view_up, (0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)):
        flat = geo.normalized(geo.sub(up, geo.mul(normal, geo.dot(up, normal))), 1e-4)
        if flat is not None:
            return flat
    return (0.0, 1.0, 0.0)


# -----------------------------------------------------------------------------
# The points
# -----------------------------------------------------------------------------

class Picked:
    """Selected points in world space, in their order, and which one is the
    active one (an index into `points`, or None when it cannot be told)."""

    def __init__(self, points, active):
        self.points = points
        self.active = active


def picked_in_meshes(context):
    """Selected vertices of the meshes in Edit Mode.

    The select history of the active mesh gives the active vertex. The order is
    that history first (the order of picking), then the rest by index.
    """
    points, active = [], None
    active_obj = context.active_object
    objs = [o for o in context.objects_in_mode_unique_data if o.type == 'MESH']
    objs.sort(key=lambda o: o != active_obj)
    for obj in objs:
        bm = bmesh.from_edit_mesh(obj.data)
        mw = world_matrix(obj)
        ordered = [e for e in bm.select_history if isinstance(e, bmesh.types.BMVert) and e.select]
        seen = set(ordered)
        ordered += [v for v in bm.verts if v.select and v not in seen]
        last = bm.select_history.active
        for v in ordered:
            if obj == active_obj and v is last:
                active = len(points)
            points.append(tuple(mw @ v.co))
    return Picked(points, active)


def active_spline_index(curve):
    """Index of the active spline of a curve (the one of the point clicked
    last), or None. Read in Edit Mode, before edit_scope()."""
    active = curve.splines.active
    if active is None:
        return None
    for i, spline in enumerate(curve.splines):
        if spline == active:
            return i
    return None


def picked_in_curves(objs, active_obj, active_index):
    """Selected control points of the curves in Edit Mode (read inside
    edit_scope()), in the order of the curve.

    The active point is the only selected point of the active spline, when
    there is only one.
    """
    points, candidates = [], []
    for obj in sorted(objs, key=lambda o: o != active_obj):
        mw = world_matrix(obj)
        for si, spline in enumerate(obj.data.splines):
            if spline.type == 'BEZIER':
                cos = [bp.co for bp in spline.bezier_points if bp.select_control_point]
            else:
                cos = [p.co.xyz for p in spline.points if p.select]
            for co in cos:
                if obj == active_obj and si == active_index:
                    candidates.append(len(points))
                points.append(tuple(mw @ co))
    return Picked(points, candidates[0] if len(candidates) == 1 else None)


# -----------------------------------------------------------------------------
# The circle
# -----------------------------------------------------------------------------

class Circle:
    """center, radius, normal (towards the viewer), start (unit vector from
    the center to the start point when Oriented) and up (12 o'clock when it is
    not; also the Y axis of the new object)."""

    def __init__(self, center, radius, normal, start, up, contacts=()):
        self.center = center
        self.radius = radius
        self.normal = normal
        self.start = start
        self.up = up
        #: Points where the circle touches the lines of the tool (world space).
        self.contacts = list(contacts)


def _tolerance(points):
    size = max((geo.distance(a, b) for a in points for b in points), default=0.0)
    return 1e-6 * size + 1e-9


def _selected_point(co, hl, hr, handle_type):
    return sd.PointData(co=co, hl=hl, hr=hr, hlt=handle_type, hrt=handle_type,
                        select=True, select_left=True, select_right=True)


def circle_spline(circle, start, sweep=None):
    """SplineData of the circle (sweep None) or of an arc of `sweep` radians
    (clockwise seen from the normal when positive), from `start`.

    The whole circle has four points at 12, 3, 6 and 9 o'clock with Auto
    handles, like Blender's own. An arc has one point every 90 degrees at
    most, with Aligned handles; the outer handles of its two ends carry on
    along the circle, so they can be picked.
    """
    c, r, n = circle.center, circle.radius, circle.normal
    clockwise = geo.cross(start, n)        # 3 o'clock, when start is 12
    if sweep is None or abs(sweep) >= _FULL_TURN:
        if sweep is not None and sweep < 0.0:
            clockwise = geo.mul(clockwise, -1.0)
        k = CIRCLE_HANDLE * r
        points = []
        for i in range(4):
            a = i * math.pi / 2.0
            radial = geo.add(geo.mul(start, math.cos(a)), geo.mul(clockwise, math.sin(a)))
            travel = geo.add(geo.mul(start, -math.sin(a)), geo.mul(clockwise, math.cos(a)))
            co = geo.add(c, geo.mul(radial, r))
            points.append(_selected_point(
                co, geo.sub(co, geo.mul(travel, k)), geo.add(co, geo.mul(travel, k)), 'AUTO'))
        return sd.SplineData('BEZIER', points, True, {})

    turn = clockwise if sweep > 0.0 else geo.mul(clockwise, -1.0)
    # The angle is a single-precision property, so 180 degrees can come in a
    # hair over pi: the step allows for that, or it would need a third piece.
    anchors = geo.arc_beziers(c, start, turn, r, abs(sweep), max_step=_MAX_STEP)
    points = []
    last = len(anchors) - 1
    for i, (co, hl, hr) in enumerate(anchors):
        if i == 0:
            hl = geo.sub(co, geo.sub(hr, co))
        if i == last:
            hr = geo.add(co, geo.sub(co, hl))
        points.append(_selected_point(co, hl, hr, 'ALIGNED'))
    return sd.SplineData('BEZIER', points, False, {})


def stray_point(co):
    """A stray control point: a Poly spline of its own with a single point
    (extruding it makes straight segments, with no handles to tidy up), like
    every other construction point of the toolkit."""
    return sd.SplineData('POLY', [sd.PointData(co=co, select=True)], False, {})


def rotated_in_plane(vector, normal, angle):
    """`vector` (in the plane) turned `angle` radians about `normal`,
    clockwise seen from the normal when positive."""
    clockwise = geo.cross(vector, normal)
    return geo.add(geo.mul(vector, math.cos(angle)), geo.mul(clockwise, math.sin(angle)))


def toward_viewer(normal, view_normal):
    """`normal` flipped, if needed, to face the viewer, so that clockwise is
    clockwise on the screen. A plane seen edge-on falls back on world Z, Y
    and X."""
    for reference in (view_normal, (0.0, 0.0, 1.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)):
        d = geo.dot(normal, reference)
        if abs(d) > 1e-4:
            return geo.mul(normal, -1.0) if d < 0.0 else normal
    return normal


def capable_arc(circle, points, goal):
    """(start, sweep) of the arc of `circle` that goes through the 3 points:
    from the one after the Goal, through the next one, to the Goal itself
    (in the order of the points, around). With the Goal on the last point,
    which is where it starts, that is from the first point, through the
    second, to the third."""
    a, b, c = (points[(goal + k) % 3] for k in (1, 2, 3))
    start = geo.normalized(geo.sub(a, circle.center))
    clockwise = geo.cross(start, circle.normal)

    def turn(p):
        """Clockwise angle from `start` to p, in [0, 2 pi)."""
        v = geo.sub(p, circle.center)
        return math.atan2(geo.dot(v, clockwise), geo.dot(v, start)) % (2.0 * math.pi)

    to_b, to_c = turn(b), turn(c)
    # Clockwise when that way meets B before C, counter-clockwise otherwise.
    return start, (to_c if to_b < to_c else to_c - 2.0 * math.pi)


def foot_on_line(p, a, b):
    """Foot of the perpendicular from p to the line through a and b."""
    along = geo.sub(b, a)
    return geo.add(a, geo.mul(along, geo.dot(geo.sub(p, a), along) / geo.dot(along, along)))


def triangle_plane(goal, others, tol, label):
    """Unit normal of the plane of three points, or Fail when they are in a
    straight line."""
    a = geo.sub(others[0], goal)
    b = geo.sub(others[1], goal)
    normal = geo.cross(a, b)
    area = geo.length(normal)
    if area <= tol * max(geo.length(a), geo.length(b), tol):
        raise Fail(f"{label}: the three points are in a straight line (or two of them "
                   "at the same place)")
    return geo.mul(normal, 1.0 / area)


def frame_matrix(circle):
    """World matrix of a new object for the circle: at the center, with its
    local Z along the normal and its local Y at 12 o'clock (not Oriented), so
    the circle lies flat in the local XY plane, as Offset and the Booleans
    want it."""
    z = Vector(circle.normal).normalized()
    y = Vector(circle.up)
    y = (y - z * y.dot(z)).normalized()
    x = y.cross(z)
    m = Matrix((x, y, z)).transposed().to_4x4()
    m.translation = Vector(circle.center)
    return m


# -----------------------------------------------------------------------------
# Shared operator
# -----------------------------------------------------------------------------

class CircleFromPoints:
    """Shared behaviour of the six buttons.

    Subclasses set `count` (2 or 3), `planar` (False for 3 Points), `hint`
    (what the active point is, for the messages) and solve(), which turns the
    active point and the others into a Circle.
    """

    bl_options = {'REGISTER', 'UNDO'}

    count = 2
    planar = True
    hint = ""
    #: True for the tools that offer Add Helper Points.
    helpers = True
    #: True when the center is one of the picked points (no helper point there).
    center_given = False
    #: True for the tool that offers Capable Arc (3 Points).
    capable = False

    view: EnumProperty(
        name="View",
        description="Plane the circle is drawn on, as seen from this view. It comes from "
                    "the 3D Viewport when the button is clicked: a free perspective and "
                    "the camera view count as Top",
        items=_VIEW_ITEMS,
        default='TOP',
        options={'SKIP_SAVE'},
    )
    oriented: BoolProperty(
        name="Oriented",
        description="Start the circle (its point at 12 o'clock) at the start point of the "
                    "tool. Off: the four points sit on the axes of the plane",
        default=True,
        options={'SKIP_SAVE'},
    )
    arc: BoolProperty(
        name="Arc",
        description="Draw only an arc of the circle, from its start",
        default=False,
        options={'SKIP_SAVE'},
    )
    capable_arc: BoolProperty(
        name="Capable Arc",
        description="The only arc of the circle that goes through the 3 points: from the "
                    "first one, through the second, to the third (the Goal). Oriented, "
                    "Angle and Normal Rotation do not apply",
        default=False,
        options={'SKIP_SAVE'},
    )
    angle: FloatProperty(
        name="Angle",
        description="Angle of the arc: clockwise when positive, counter-clockwise when "
                    "negative (seen from the view)",
        default=math.pi,
        min=-2.0 * math.pi,
        max=2.0 * math.pi,
        subtype='ANGLE',
        options={'SKIP_SAVE'},
    )
    goal: EnumProperty(
        name="Goal",
        description="Which of the 3 selected points plays the part of the active one "
                    "(counted in the order of the selection, or of the curve). It starts "
                    "at the active point, or at the last one when that cannot be told",
        items=(
            ('1', "1", "The first of the selected points"),
            ('2', "2", "The second of the selected points"),
            ('3', "3", "The third of the selected points"),
        ),
        default='1',
        options={'SKIP_SAVE'},
    )
    toggle_goal: BoolProperty(
        name="Toggle Goal",
        description="Swap the parts of the two selected points: the other one plays the "
                    "part of the active one",
        default=False,
        options={'SKIP_SAVE'},
    )
    normal_rotation: FloatProperty(
        name="Normal Rotation",
        description="Turn the circle or arc about the axis through its center, normal to "
                    "its plane (clockwise when positive, seen from the view)",
        default=0.0,
        subtype='ANGLE',
        options={'SKIP_SAVE'},
    )
    helper_points: BoolProperty(
        name="Add Helper Points",
        description="Also add stray control points (Poly, one point each) at every "
                    "point where the circle touches a line, even when an arc does not reach "
                    "it, and at its center when the center was not one of the picked points",
        default=False,
        options={'SKIP_SAVE'},
    )
    # Read from the 3D Viewport on the first run and kept for the F9 panel,
    # where the view can no longer be read.
    view_normal: FloatVectorProperty(size=3, default=(0.0, 0.0, 1.0),
                                     options={'HIDDEN', 'SKIP_SAVE'})
    view_up: FloatVectorProperty(size=3, default=(0.0, 1.0, 0.0),
                                 options={'HIDDEN', 'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        if context.mode == EDIT_MESH:
            return True
        if context.mode == EDIT_MODE and is_curve(context.active_object):
            return True
        cls.poll_message_set("Works in the Edit Mode of a mesh (vertices) or of a curve "
                             "(control points)")
        return False

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        self.draw_extra(layout)
        # The Capable Arc is fixed by the 3 points: the settings that turn or
        # size the arc are greyed out.
        free = not self._capable_on()
        row = layout.row()
        row.enabled = free
        row.prop(self, "oriented")
        if self.count == 2:
            layout.prop(self, "toggle_goal")
        else:
            # Three small buttons, the chosen one highlighted.
            layout.row().prop(self, "goal", expand=True)
        layout.prop(self, "arc")
        if self.capable:
            row = layout.row()
            row.enabled = self.arc
            row.prop(self, "capable_arc")
        row = layout.row()
        row.enabled = self.arc and free
        row.prop(self, "angle")
        row = layout.row()
        row.enabled = free
        row.prop(self, "normal_rotation")
        if self.helpers:
            layout.prop(self, "helper_points")
        if self.planar:
            layout.separator()
            layout.prop(self, "view")

    def draw_extra(self, layout):
        """Tool settings drawn first (Radius of Tangent to 2 Segments)."""

    # -- Running -------------------------------------------------------------

    def _read_view(self, context):
        props = self.properties
        if props.is_property_set("view_normal"):
            return
        name, normal, up = read_view(context)
        self.view_normal = normal
        self.view_up = up
        if not props.is_property_set("view"):
            self.view = name

    def execute(self, context):
        self._read_view(context)
        try:
            if context.mode == EDIT_MESH:
                return self._from_mesh(context)
            return self._from_curve(context)
        except Fail as error:
            self.report({'ERROR'}, str(error))
            return {'CANCELLED'}

    def _from_mesh(self, context):
        circle, datas = self._build(picked_in_meshes(context), "vertices")
        bpy.ops.object.mode_set(mode='OBJECT')
        name = unique_name("Circle" if datas[0].cyclic else "Arc")
        curve = bpy.data.curves.new(name, 'CURVE')
        curve.dimensions = '3D'
        obj = bpy.data.objects.new(name, curve)
        matrix = frame_matrix(circle)
        obj.matrix_basis = matrix
        to_local = matrix.inverted()
        sd.replace_splines(curve, [_transformed(d, to_local) for d in datas])
        (context.collection or context.scene.collection).objects.link(obj)
        for other in context.selected_objects:
            other.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        return {'FINISHED'}

    def _from_curve(self, context):
        obj = context.active_object
        active_index = active_spline_index(obj.data)
        try:
            to_local = world_matrix(obj).inverted()
        except ValueError:
            raise Fail(f"'{obj.name}' has a degenerate transform (zero scale)")
        with edit_scope(context) as objs:
            picked = picked_in_curves(objs, obj, active_index)
            _, datas = self._build(picked, "control points")
            datas = [_transformed(d, to_local) for d in datas]
            for o in objs:
                _deselect_all(o.data)
            splines = [sd.write_spline(obj.data, d) for d in datas]
            obj.data.splines.active = splines[0]
        if obj.data.dimensions == '2D' and not all(_flat_in_xy(d) for d in datas):
            self.report({'WARNING'},
                        f"'{obj.name}' is a 2D curve: the new spline is flattened onto its "
                        "local XY plane")
        return {'FINISHED'}

    def _capable_on(self):
        return self.capable and self.arc and self.capable_arc

    def goal_index(self, picked):
        """Index of the point that plays the part of the active one.

        It starts at the active point (the last one when that cannot be told).
        With 2 points Toggle Goal swaps it; with 3, Goal picks any of them.
        """
        n = len(picked.points)
        active = picked.active if picked.active is not None else n - 1
        if n == 2:
            return 1 - active if self.toggle_goal else active
        if not self.properties.is_property_set("goal"):
            self.goal = str(active + 1)
        return min(int(self.goal), n) - 1

    def _build(self, picked, what):
        """Circle and list of SplineData (in world space) from the picked
        points: the circle or arc first, then the helper points."""
        n = len(picked.points)
        if n != self.count:
            raise Fail(f"{self.bl_label}: select exactly {self.count} {what} "
                       f"({n} selected). {self.hint}")
        goal = self.goal_index(picked)
        points = picked.points
        others = [p for i, p in enumerate(points) if i != goal]
        circle = self.solve(points[goal], others, _tolerance(points))

        if self._capable_on():
            start, sweep = capable_arc(circle, points, goal)
        else:
            start = circle.start if self.oriented else circle.up
            if self.normal_rotation:
                start = rotated_in_plane(start, circle.normal, self.normal_rotation)
            sweep = self.angle if self.arc else None
            if sweep is not None and abs(sweep) < 1e-6:
                raise Fail(f"{self.bl_label}: the Angle of the arc cannot be 0")
        datas = [circle_spline(circle, start, sweep)]
        if self.helpers and self.helper_points:
            helpers = list(circle.contacts)
            if not self.center_given:
                helpers.append(circle.center)
            datas += [stray_point(co) for co in helpers]
        return circle, datas

    # -- Planar tools --------------------------------------------------------

    def plane(self):
        """Normal (towards the viewer) and 12 o'clock of the plane of the view."""
        normal = VIEWS[self.view][0]
        return normal, snapped_up(self.view, tuple(self.view_normal), tuple(self.view_up))

    def projector(self, active):
        """Function that puts a point on the plane of the view, at the height
        of the active point."""
        normal, _ = self.plane()
        level = geo.dot(active, normal)

        def project(p):
            return geo.sub(p, geo.mul(normal, geo.dot(p, normal) - level))
        return project

    def solve(self, active, others, tol):
        raise NotImplementedError


def _transformed(data, matrix):
    for p in data.points:
        p.co = tuple(matrix @ Vector(p.co))
        if p.hl is not None:                # Poly points have no handles
            p.hl = tuple(matrix @ Vector(p.hl))
            p.hr = tuple(matrix @ Vector(p.hr))
    return data


def _flat_in_xy(data):
    coords = [c for p in data.points for c in (p.co, p.hl, p.hr) if c is not None]
    size = max((max(abs(c[0]), abs(c[1])) for c in coords), default=0.0)
    return all(abs(c[2]) <= 1e-6 * size + 1e-7 for c in coords)


def _deselect_all(curve):
    for spline in curve.splines:
        if spline.type == 'BEZIER':
            for bp in spline.bezier_points:
                bp.select_control_point = False
                bp.select_left_handle = False
                bp.select_right_handle = False
        else:
            for p in spline.points:
                p.select = False


def _view_name(op):
    return op.view.title()


# -----------------------------------------------------------------------------
# The tools
# -----------------------------------------------------------------------------

class ETR_OT_curve_toolkit_circle_center_point(CircleFromPoints, bpy.types.Operator):
    """Bezier circle from 2 selected points: the active one (picked last) is the center, the other one is on the circle. Drawn on the plane of the view"""
    bl_idname = "etr.curve_toolkit_circle_center_point"
    bl_label = "Circle from Center & Point"

    count = 2
    helpers = False
    center_given = True
    hint = "The active one (picked last) is the center"

    def solve(self, active, others, tol):
        normal, up = self.plane()
        project = self.projector(active)
        center = project(active)
        point = project(others[0])
        radius = geo.distance(center, point)
        if radius <= tol:
            raise Fail(f"{self.bl_label}: the two points are at the same place in the "
                       f"{_view_name(self)} view")
        start = geo.mul(geo.sub(point, center), 1.0 / radius)
        return Circle(center, radius, normal, start, up)


class ETR_OT_curve_toolkit_circle_2_points(CircleFromPoints, bpy.types.Operator):
    """Bezier circle whose diameter goes from one selected point (12 o'clock) to the active one (6 o'clock). Drawn on the plane of the view"""
    bl_idname = "etr.curve_toolkit_circle_2_points"
    bl_label = "Circle from 2 Points"

    count = 2
    hint = "The active one (picked last) goes at 6 o'clock, the other one at 12"

    def solve(self, active, others, tol):
        normal, up = self.plane()
        project = self.projector(active)
        bottom = project(active)
        top = project(others[0])
        diameter = geo.distance(bottom, top)
        if diameter <= tol:
            raise Fail(f"{self.bl_label}: the two points are at the same place in the "
                       f"{_view_name(self)} view")
        center = geo.lerp(bottom, top, 0.5)
        start = geo.mul(geo.sub(top, bottom), 1.0 / diameter)
        return Circle(center, diameter / 2.0, normal, start, up)


class ETR_OT_curve_toolkit_circle_3_points(CircleFromPoints, bpy.types.Operator):
    """Bezier circle through 3 selected points, in their own plane, whatever the view. It starts at the active one (picked last)"""
    bl_idname = "etr.curve_toolkit_circle_3_points"
    bl_label = "Circle from 3 Points"

    count = 3
    planar = False
    capable = True
    hint = "The circle starts at the active one (picked last)"

    def solve(self, active, others, tol):
        a = geo.sub(others[0], active)
        b = geo.sub(others[1], active)
        normal = geo.cross(a, b)
        area = geo.length(normal)
        triangle_plane(active, others, tol, self.bl_label)
        # Circumcenter: active + ((|a|^2 b - |b|^2 a) x (a x b)) / (2 |a x b|^2)
        offset = geo.cross(
            geo.sub(geo.mul(b, geo.dot(a, a)), geo.mul(a, geo.dot(b, b))), normal)
        center = geo.add(active, geo.mul(offset, 1.0 / (2.0 * area * area)))
        radius = geo.distance(center, active)
        normal = toward_viewer(geo.mul(normal, 1.0 / area), tuple(self.view_normal))
        start = geo.mul(geo.sub(active, center), 1.0 / radius)
        return Circle(center, radius, normal, start, up_in_plane(normal, tuple(self.view_up)))


class ETR_OT_curve_toolkit_circle_segment_center(CircleFromPoints, bpy.types.Operator):
    """Bezier circle around the active point (picked last), tangent to the straight line through the other two selected points. Drawn on the plane of the view"""
    bl_idname = "etr.curve_toolkit_circle_segment_center"
    bl_label = "Circle from Segment & Center"

    count = 3
    center_given = True
    hint = "The active one (picked last) is the center, the other two make the line"

    def solve(self, active, others, tol):
        normal, up = self.plane()
        project = self.projector(active)
        center = project(active)
        s0, s1 = project(others[0]), project(others[1])
        along = geo.sub(s1, s0)
        span = geo.dot(along, along)
        if span <= tol * tol:
            raise Fail(f"{self.bl_label}: the two points of the line are at the same place "
                       f"in the {_view_name(self)} view")
        foot = geo.add(s0, geo.mul(along, geo.dot(geo.sub(center, s0), along) / span))
        radius = geo.distance(center, foot)
        if radius <= tol:
            raise Fail(f"{self.bl_label}: the center is on the line")
        start = geo.mul(geo.sub(foot, center), 1.0 / radius)
        return Circle(center, radius, normal, start, up, [foot])


def incircle(a, b, c):
    """Center and radius of the circle inscribed in the triangle a, b, c."""
    la, lb, lc = geo.distance(b, c), geo.distance(a, c), geo.distance(a, b)
    perimeter = la + lb + lc
    center = geo.mul(geo.add(geo.add(geo.mul(a, la), geo.mul(b, lb)), geo.mul(c, lc)),
                     1.0 / perimeter)
    area2 = geo.length(geo.cross(geo.sub(b, a), geo.sub(c, a)))
    return center, area2 / perimeter


class ETR_OT_curve_toolkit_circle_inscribed(CircleFromPoints, bpy.types.Operator):
    """Bezier circle inscribed in the triangle of 3 selected points (tangent to its 3 sides), in their own plane. It starts touching the side opposite the active point"""
    bl_idname = "etr.curve_toolkit_circle_inscribed"
    bl_label = "Circle Inscribed in a Triangle"

    count = 3
    planar = False
    hint = "The circle starts touching the side opposite the active one (picked last)"

    def solve(self, active, others, tol):
        normal = triangle_plane(active, others, tol, self.bl_label)
        normal = toward_viewer(normal, tuple(self.view_normal))
        center, radius = incircle(active, others[0], others[1])
        # The side opposite the goal first: it is where the circle starts.
        sides = ((others[0], others[1]), (active, others[1]), (active, others[0]))
        contacts = [foot_on_line(center, a, b) for a, b in sides]
        start = geo.mul(geo.sub(contacts[0], center), 1.0 / radius)
        return Circle(center, radius, normal, start,
                      up_in_plane(normal, tuple(self.view_up)), contacts)


class ETR_OT_curve_toolkit_circle_tangent_2(CircleFromPoints, bpy.types.Operator):
    """Bezier circle tangent to the 2 segments that meet at the active point (picked last), of 3 selected points. Its Radius starts as the one of the inscribed circle"""
    bl_idname = "etr.curve_toolkit_circle_tangent_2"
    bl_label = "Circle Tangent to 2 Segments"

    count = 3
    planar = False
    hint = "The two segments meet at the active one (picked last)"

    radius: FloatProperty(
        name="Radius",
        description="Radius of the circle, which stays tangent to the two segments that "
                    "meet at the Goal point. It starts as the one of the inscribed circle",
        default=1.0,
        min=0.0,
        subtype='DISTANCE',
        unit='LENGTH',
        options={'SKIP_SAVE'},
    )

    def draw_extra(self, layout):
        layout.prop(self, "radius")

    def solve(self, active, others, tol):
        normal = triangle_plane(active, others, tol, self.bl_label)
        normal = toward_viewer(normal, tuple(self.view_normal))
        if not self.properties.is_property_set("radius"):
            self.radius = incircle(active, others[0], others[1])[1]
        radius = self.radius
        if radius <= tol:
            raise Fail(f"{self.bl_label}: the Radius cannot be 0")
        u1 = geo.normalized(geo.sub(others[0], active))
        u2 = geo.normalized(geo.sub(others[1], active))
        half = math.acos(max(-1.0, min(1.0, geo.dot(u1, u2)))) / 2.0
        bisector = geo.normalized(geo.add(u1, u2))
        center = geo.add(active, geo.mul(bisector, radius / math.sin(half)))
        reach = radius / math.tan(half)
        contacts = [geo.add(active, geo.mul(u1, reach)), geo.add(active, geo.mul(u2, reach))]
        start = geo.mul(geo.sub(contacts[0], center), 1.0 / radius)
        return Circle(center, radius, normal, start,
                      up_in_plane(normal, tuple(self.view_up)), contacts)


# -----------------------------------------------------------------------------

classes = (
    ETR_OT_curve_toolkit_circle_center_point,
    ETR_OT_curve_toolkit_circle_2_points,
    ETR_OT_curve_toolkit_circle_3_points,
    ETR_OT_curve_toolkit_circle_segment_center,
    ETR_OT_curve_toolkit_circle_inscribed,
    ETR_OT_curve_toolkit_circle_tangent_2,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
