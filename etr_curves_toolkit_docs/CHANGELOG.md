# Changelog

## v0.24.0

- **Symmetrize**: when the selected curves have nothing on the side that is
  kept (for example, all of them on the right with *Left to Right*), nothing
  is made but the operator now finishes with a warning instead of
  cancelling, so the **F9 panel opens** and the *Direction* can be changed
  there (Right to Left). The same in a perspective view: the *View* can be
  picked in F9.
- **Panel order**: in *Shaping Splines*, **Handles to Axis** and **Handles to
  Lines** move to the end, under Slice. *Utilities* now goes from whole
  splines to points: Select All by Type, Separate All Selected; Subdivide,
  Simplify, Dissolve; Set First Point, Invert Direction; Snap / Merge / Swap
  Pair; Merge by Distance, Join & Merge, Remove Doubles; and last Resolution
  and Cyclic.
- Both READMEs describe the tools **in the order of the panel**. In the full
  documentation, *Resolution and Cyclic* has a section of its own, Join &
  Merge and Remove Doubles are described with the other merges, and Split at
  Control Points with the Splits.
- Full documentation: the six groups of the panel (Create Curves, Curve
  Booleans, Shaping Splines, Utilities, Change Origin, Global Settings) are
  now its main sections (H3) under *Tools*, with every tool one level below
  (H4), so the outline (Obsidian, GitHub) matches the panel. Global Settings
  has a section of its own.
- **Palette icons** adjusted: Line / Point, Bridge Curves, Slice, Points
  Along Curve, Handles to Axis, Tangents from Point, Circle Inscribed in a
  Triangle, Circle Tangent to 2 Segments (the circles no longer touch the
  white lines), Tangents to 2 Circles and Perpendicular from Point. The
  triangle of the two circle icons is a little smaller, so its points are no
  longer cut off at the edges.
- Development: `dev/make_icons.py --sheet` writes all the palette icons into
  one SVG document, in the order of the panel, on a 6 x 6 grid of 32 px cells
  (`dev/palette_icons_svg/palette_icons_sheet.svg`).

## v0.23.0

- **Change Origin**: **Geo** now goes to the **center of the bounding box**
  (Bounds Center) of the real shape of the curve, instead of Blender's Origin
  to Geometry (median of the points); Bezier handles do not pull it.
- **Change Origin**: **In**, **Mid**, **Out** and **Geo** also work in **Edit
  Mode**, on the spline that has a selected point (Geo: all the selected
  splines). With two consecutive control points selected, **Mid** goes to the
  middle of the segment between them.
- **Points Along Curve**: in Edit Mode, with two consecutive control points
  of a spline selected, the points go only along the segment between them.
- **Points at Intersections** and **Points Along Curve**: in Object Mode the
  new curve with the points is left in **Edit Mode**, where stray points can
  be seen.
- New: **Split at Stray Points** (Curve Booleans, under Split at Control
  Points, no icon): cuts the splines of a curve where stray points of the same
  curve lie on them, within the Threshold. Object Mode: every selected curve;
  Edit Mode: the selected splines, by the selected stray points. In an
  orthographic view it is enough for a point to be seen on a spline. Every
  piece becomes a new object, the original is kept, and Place Sources / Place
  Results apply. Poly and Bezier.
- **Split at Points** is now **Split at Control Points**.
- New sub-panel **Global Settings** (closed by default, under Change Origin):
  the **Threshold** moves there from Utilities, since tools of other sections
  (Split at Stray Points) use it too.
- **Add Line** is now **Add Line / Point**, with a **Points** option (F9,
  default 2, soft limit 99): 1 makes a single stray Poly point, 3 or more
  subdivide the line evenly.
- **Add Helper Points** of the Circles from Points: the helper points are now
  **Poly** stray points (they were Bezier points with zero-length handles), like
  every other construction point.
- **New palette icons**: two tones only, white and grey (no orange or other
  accents), the same line width and the same point size everywhere, a little
  bigger than before. The icons of the documentation do not change.

## v0.22.0

- **Fix Hole is now Slice**, a more general name: it divides a shape with
  partition walls (double seams), to remove holes or to break a complex
  shape into simpler ones. New **Undo Slice** button next to it (no icon):
  select the two pairs of coincident points of a seam (one point of each
  pair is enough) and the seam is taken away at any moment, merging each
  pair back into one point.
- New: **Points at Intersections** (Create Curves): a stray point where
  splines cross, without cutting them, also a spline with itself. Object
  Mode: a new object; Edit Mode: the same curve. Apparent crossings get a
  point on the plane of an orthographic Top, Front or Right view (Z, Y or
  X = 0); in perspective they are left out with a warning. Poly and Bezier
  exact, NURBS approximated.
- New: **Points Along Curve** (Create Curves): Count stray points (default 4)
  at equal lengths along each spline, without splitting it; *Add at
  Extremes* adds the ends (one point on a closed spline).
- New: **Tangents from Point** (Create Curves): the two Poly lines from a
  selected point that touch a circle.
- New: **Handles to Axis** (Shaping Splines): handles within a *Threshold*
  (default 5°) of a local axis are turned onto it. Object Mode: every
  handle; Edit Mode: the selected points, or a single handle.
- New: **Symmetrize** (Curve Booleans, under the three booleans): one side of
  the curves mirrored onto the other and welded on the axis, relative to an
  orthographic axis view. Four directions, World Origin / Object Origin /
  3D Cursor as center, open and closed curves, originals kept as backups
  with the Sources and Results options.
- New: **To World Origin** and **To 3D Cursor** in Change Origin (Object and
  Edit Mode).
- **Round Corners**: no soft limit (10 m) on the Radius any more.
- Panel: Create Curves has four rows (construction lines, then construction
  points); **Handles to Lines** moved to Shaping Splines, under Handles to
  Axis; **Arcs to Corners** glued under Round and Bridge.

## v0.21.0

- New: **Fix Hole** (Shaping Splines, after Slide Point): a double seam
  between two selected points, two coincident straight segments (Vector
  handles) without merging the points. One point on the outer spline and one
  on the hole: they are joined into one closed outline (the direction of the
  hole is inverted when needed; two splines side by side can be joined too).
  Both points on the same closed spline: it is cut in two along the line
  between them. Seams can be added one after another, so *Fill Curve* puts
  its inner edges exactly where they were picked. Bezier and Poly.
- Fix: **Round Corners** refused the corner of a closed spline of only two
  points ("No corners to round").
- **Curve Boolean Sources** is always kept above **Curve Boolean Results** in
  the Outliner.
- Panel: **Separate All Selected** is a little apart from the *Select All by
  Type* menu, instead of glued to it.

## v0.20.0

- **Split All** also cuts every curve where it **crosses itself** (a loop),
  so a single looping curve can be split on its own (the button is no longer
  greyed out with one curve). Everything is cut by everything, the splines
  of one object included. It no longer needs an active object, so it works
  after a Select All or a box selection. Split Active is unchanged.
- **Offset**: new *Duplicate* option (on by default). Turned off, the original
  is replaced by its offset, in Object and in Edit Mode.
- **Offset**: the outer handles of the ends of an open offset are now in line
  with the inner ones (Aligned, with the length of the original's), instead
  of Free handles all pointing at the same spot. Smooth points with Free
  handles, the joints of *Join Both with Arcs* included, become Aligned.
- **Select All by Type**: one drop-down menu (None, Strays, Polys, Beziers,
  NURBS) replaces the four selection buttons; Separate All Selected stays
  under it.
- **Place Sources inside a Collection**: the `Curve Boolean Sources`
  collection is excluded from the View Layer instead of hiding the curves;
  later operations enable it, add their sources and exclude it again.

## v0.19.0

- New: **Lines from Points** (Create Curves, third row, before Points in
  Between): joins the selected points with straight lines, without merging
  them. 2 points make a segment; 3 or more a closed shape with no crossings
  (*Closed* in F9 leaves it open). The order is worked out from where the
  points are: shapes drawn along the axes (L, T, H, cross, stair...) follow
  their outline, the rest the shortest closed path. A Poly spline of the
  active curve, or vertices and edges of the active mesh; points of several
  objects can be joined.
- New: **Snap Pair** and **Swap Pair**, on either side of Merge Pair: two
  selected points go to the same place (At Center / At Point A / At Point B)
  or trade places, without welding, so any two points will do. Also two mesh
  vertices.
- New: **Select All Polys / Beziers / NURBS**: select every spline of one
  type in the curves being edited (*Extend* in F9).
- Points in Between: the new points are **Poly** stray points instead of
  Bezier ones.
- Panel: *Rounds, Bridge & Corners* becomes **Shaping Splines** and also holds
  **Offset**, **Extend** and **Slide Point** (out of Utilities), now with icons.
  In Utilities, Select Strays, the three Select All buttons and Separate All
  Selected make a group of their own, under Resolution.

## v0.18.1

- Tangents to 2 Circles > Boolean All: the circles (their object or objects)
  are hidden, so only the belt shape is left in view.
- Perpendicular from Point: the segments are always Poly.

## v0.18.0

- New: **Tangents to 2 Circles**: the outer tangents of two circles (two
  objects, or two splines of one), as straight Bezier segments with Vector
  handles. Options: *Add Crossing Tangents*, and *Boolean All* (the belt
  shape, joined and merged, as a new object, with the circles hidden).
- New: **Perpendicular from Point**: a straight segment from every selected
  point, perpendicular to the curve or along the bisector of a corner, in the
  plane of the view, always as a Poly spline. *Length* in F9 (negative for
  the other side).
- New: **Handles to Lines**: the handles of Bezier curves as Poly lines (a new
  object in Object Mode; the same curve, selected points only, in Edit Mode).
- Create Curves has a third row: the second one keeps five circles (Center &
  Point, 2 Points, 3 Points, Inscribed, Tangent to 2 Segments) and the third
  one holds Segment & Center, Tangents to 2 Circles, Perpendicular from Point,
  Handles to Lines and Points in Between.

## v0.17.0

- Round Corners (and Bridge): where an arc meets a straight segment, the
  handle on the arc side is now **Aligned** (in line with the Vector handle of
  the straight side) instead of Free, so moving it keeps the joint smooth.
- Circles from Points: *Stray Points at Contact* becomes **Add Helper Points**:
  the contact points as before, plus a point at the **center** when the center
  was not one of the picked points. Now offered by every tool but Center &
  Point.
- Curve Booleans: an object may now have **several closed splines** (a shape
  with holes, or several islands): its splines make one region, even-odd, the
  way Blender fills a 2D curve.
- **Separate All Selected** also works in **Object Mode**: every selected
  curve with several splines is split into one object per spline.
- Documentation: an icon for every tool and section, in the style of the
  Eterea Blender Tools kit (SVG sources and PNG files, see
  `etr_curves_toolkit_docs/icons/ICON_STYLE.md`).

## v0.16.0

- Circles from Points: the F9 options in a new order (Radius, Oriented, Goal,
  Arc, Angle, Normal Rotation, Stray Points at Contact, View), and **Goal** as
  three small buttons 1 / 2 / 3 instead of a number field.
- Change Origin: new **To Selected Point** button on top (Edit Mode of a
  curve): the origin goes to the selected control point, and the Edit Mode is
  kept.

## v0.15.0

- Circles from Points:
  - **Goal** replaces *Active Point* in the 3-point tools: always in the F9
    panel, for mesh vertices as well as curve points. The 2-point tools get a
    **Toggle Goal** checkbox that swaps the parts of the two points.
  - New **Normal Rotation** option: turns the circle or arc about its center,
    in its plane.
  - New **Stray Points at Contact** option (Segment & Center and the two new
    tools): stray control points, zero-length Vector handles, where the circle
    touches the lines.
  - New: **Circle Inscribed in a Triangle** and **Circle Tangent to 2
    Segments** (with an editable Radius), after Segment & Center.
- **Select Strays** replaces *Remove Strays* in the panel (Edit Mode of a curve
  or a mesh): selects the stray points, and only those, so they can be checked
  before deleting them. Remove Strays stays available for F3 search.
- **Points in Between**: the stray points of a curve now have zero-length
  Vector handles (they had Auto ones).

## v0.14.0

- New: **Points in Between**, first button of the second row of Create Curves.
  With 2 selected points it adds *Count* evenly spaced points on the straight
  line between them, in 3D (1 at the middle by default; soft limit 100):
  stray control points (single-point Bezier splines, Auto handles) in the
  Edit Mode of a curve, loose vertices in the Edit Mode of a mesh. Edit Mode
  is kept and only the new points end up selected.
- **Remove Strays** also works in the Edit Mode of a mesh: it deletes its
  stray (loose) vertices.

## v0.13.0

- New: **Circles from Points**, four icon buttons on a second row of the first
  section: Circle from Center & Point, from 2 Points, from 3 Points and from
  Segment & Center. Bezier circles or arcs from the selected vertices of a mesh
  (new curve object, left in Edit Mode) or the selected control points of a
  curve (new spline in that curve). The plane comes from the view of the 3D
  Viewport (Top/Bottom XY, Front/Back XZ, Right/Left YZ, perspective and camera
  as Top). F9: View, Oriented, Arc and Angle (clockwise when positive).
- The section *Primitive Curves* is now **Create Curves**.
- Sidebar: the tab is now **Eterea Curves**, with the title *Eterea Curves
  Toolkit* on top and one collapsible sub-panel per section (Utilities and
  Change Origin collapsed by default). Shorter tooltips; the full detail stays
  in the README.

## v0.12.0

Initial standalone release of the Curve Toolkit as its own Blender Extension
(`etr_curves_toolkit`), independent from the Eterea Blender Tools kit:

- Primitive Curves (Line, Bezier, Rectangle, Polygon, Circle)
- Curve Booleans (Union, Intersection, Difference)
- Curve Splits (Split Active, Split All)
- Round Corners, Bridge Curves, Arcs to Corners
- Offset (Miter / Round / Bevel, Both Sides, Join Both with Arcs)
- Extend
- Slide Point
- Merge Pair, Merge by Distance
- Utilities (Set First Point, Invert Direction, Subdivide, Simplify, Dissolve,
  Set Resolution, Split at Points, Separate All Selected, Join & Merge, Remove
  Doubles, Remove Strays, Cyclic)
- Change Origin (In, Mid, Out, Geo)
