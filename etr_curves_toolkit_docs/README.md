# Curve Toolkit

Tools to create, refine and operate on curves (Poly, Bezier and NURBS) for
Blender 5.2.

Independent Blender Extension, with its own installation, documentation and
icons (`etr_curves_toolkit`). Panel location:
**3D Viewport > Sidebar (N) > Tool > Curve Toolkit**.

## Tools

### Primitive Curves (Object and Edit Mode)

Five icon buttons that add a simple curve to the scene:

| Button | Curve | Shape |
| --- | --- | --- |
| Line | Poly, 2 points, open | A straight line on the X axis, from -Radius to +Radius |
| Bezier | Bezier, 2 points, open | The same curve as Blender's *Add > Curve > Bezier*, with the same Aligned handles |
| Rectangle | Poly, 4 points, closed | A rectangle on the XY plane, *Width* x *Height* |
| Polygon | Poly, N points, closed | A regular polygon on the XY plane, N = *Sides* |
| Circle | Bezier, 4 points, closed | The same circle as Blender's *Add > Curve > Circle*, with the same Auto handles |

All of them follow the conventions of Blender's own *Add* operators. Right
after the click, the *Adjust Last Operation* panel (bottom left, or F9) has,
in this order:

- the size first: *Radius* (Line, Bezier, Circle), *Width* and *Height*
  (Rectangle), *Sides* (Polygon, default 6) and *Radius*.
- *Align*: World, View or 3D Cursor.
- *Location* XYZ and *Rotation* XYZ.

In the **Edit Mode of a curve** the same buttons add their shape as one more
**spline inside that curve**, instead of a new object:

- It goes where *Location* says (the 3D Cursor by default), with *Align* and
  *Rotation* working as usual: they are read in world space and brought into
  the local space of the object being edited.
- The splines that were there are left alone and **only the new one ends up
  selected**, ready to be moved, offset or rounded.
- The size is the size in the **scene**, so the transform of the object is
  taken out of the shape. In an object with a non-uniform scale that means the
  spline is written pre-distorted, so that it still looks right in the
  viewport. It is what Blender does when a mesh primitive is added in Edit
  Mode.
- In an object whose *Shape* is **2D** the height of the new spline is ignored
  by Blender, so a *Rotation* out of the XY plane cannot be seen. A warning
  says so.
- In the Edit Mode of anything that is not a curve the five buttons are
  **disabled**.

Notes:

- **Units**. The size comes in at one unit of the length shown in the
  interface: `Radius = 1 m` in a metric scene, `1 cm` when the Length of the
  scene is set to Centimeters, `1 ft` in an imperial one, and so on (the
  *Unit Scale* of the scene is taken into account; without units, the grid of
  the viewport is). The Rectangle comes in at 2 x 2 of the same unit. This
  goes a bit further than Blender's own primitives, which only follow the
  *unit system* (so they would read `100 cm` in that example).
- The *Radius* of the Line is half its length, so the default Radius 1 gives a
  line of length 2, the same meaning Blender gives it in its own primitives.
- The first point of the **Polygon** is on the +Y axis (at 12 o'clock) and
  stays there when *Sides* changes. The first point of the **Circle** is on
  the -X axis, as in Blender's own circle.
- The closed primitives (Rectangle, Polygon, Circle) turn
  **counter-clockwise** seen from +Z, so the Booleans, Round Corners and the
  rest of the tools see all of them the same way. Blender's own Bezier circle
  turns clockwise, so this is the one difference with it.
- New curves are **3D** (Shape: 3D), as Blender's own ones. The Booleans and
  Splits turn flat 3D curves into 2D by themselves when they need to.

### Curve Booleans (Object Mode)

2D boolean operations between closed curves, as three icon buttons:

| Button | Curves | Result |
| --- | --- | --- |
| Union | 2 or more | The union of all of them (order and active object do not matter) |
| Intersection | Exactly 2 | The common area |
| Difference | Exactly 2 | The active curve (selected last) bites the other one |

- Every selected object must have a **single closed** Poly or Bezier spline.
  NURBS are not supported.
- 3D curves that are flat (all their points at z = 0 in their local space) are
  turned into **2D curves automatically**. A 3D curve that is not flat gives a
  message and nothing is changed.
- The curves can be anywhere and rotated (XY, XZ, YZ or any other plane, at any
  height), as long as they all lie in the **same plane**. They are checked in
  the local space of the active object; if they are not coplanar, nothing is
  done and a message explains why.
- The result is a new object, `Curve Boolean`, with the transform and the look
  (bevel, fill, materials...) of the active object. The originals are hidden,
  never modified (apart from the automatic switch to 2D).
- If all the curves are Poly the result is Poly. Otherwise it is Bezier, and
  the Poly sides get Vector handles (as Set Spline Type does).
- The result can have several contours: disjoint pieces, or holes (a
  Difference that leaves a hole gives an outer and an inner spline).
- The shape is exact: intersections are computed on the real Bezier curves (not
  on a polygonal approximation), the curves are cut there with de Casteljau,
  and edges shared by both curves are handled. Original points that survive
  keep their handle type (Auto handles become Aligned); the new points at the
  crossings are corners with Free handles.

### Curve Splits (Object Mode)

Cut 2D curves where they cross other selected curves. Unlike the booleans,
open curves are allowed: an open curve can cut a closed one, several open
curves can cut each other, and so on.

- **Split Active**: only the active curve is cut, by all the others.
- **Split All**: every selected curve is cut by all the others.
- Every piece becomes a new object (`Split_01`, `Split_02`...) with the look
  and transform of the curve it comes from. Poly pieces stay Poly and Bezier
  pieces stay Bezier. All the selected originals are hidden.
- Same requirements as the booleans: Poly or Bezier curves in the same plane
  (flat 3D curves are turned into 2D automatically). Curves of one object
  (several splines) do not cut each other.
- An end of an open curve that only touches another curve is not a cut. A
  closed curve cut at a single point becomes one open piece whose ends meet.

**Split at Points** (see Utilities) is drawn with the Splits.

### Sources and Results collections

Two options under the Booleans and Splits, shared by all of them (Union,
Intersection, Difference, Split Active, Split All and Split at Points), both
off by default:

- *Place Sources inside a Collection*: the original curves are moved into the
  collection `Curve Boolean Sources`.
- *Place Results inside a Collection*: the new curves go into the collection
  `Curve Boolean Results`.

If a collection with that name already exists in the scene it is reused,
wherever it is in the Outliner. Otherwise it is created inside the collection
of the active source. The sources are always hidden, but the visibility of the
collections (and their Exclude checkbox) is never changed.

### Rounds, Bridge & Corners (Edit Mode)

**Round Corners** replaces every selected corner by an arc tangent to both
sides (a true fillet), also when one or both segments are curved. The rest of
the curve keeps its exact shape: curved segments are trimmed at the tangent
points with de Casteljau. Radius and Tension are editable right after the
click in the *Adjust Last Operation* panel (bottom left, or F9).

- *Radius*: radius of the circle tangent to both sides.
- *Tension* (default 1.0, no upper limit): 1.0 gives a circular arc, 0.0 a
  straight bevel between the two tangent points, and higher values stretch the
  Bezier handles for a sharper rounding. Very high values on sharp corners can
  make the rounding loop over itself.

- Works on Poly splines and on Bezier splines. Arcs are cubic Beziers, so a
  Poly spline becomes a Bezier spline (the other corners keep Vector handles).
- Handle types: sides along straight segments get Vector handles (at 1/3 of
  the segment, so with Tension 0.0 the bevel's points can be selected and
  rounded again); points between two curved segments get Aligned handles (no
  pinch when one handle is moved); other curved sides are Free.
- Several corners can be rounded at once. When two neighbouring corners are
  rounded, each arc may use at most half of the segment between them; a radius
  that does not fit is reduced.
- Works in 3D (the corner defines its own plane).
- On curved corners the fillet is solved numerically (the curves offset by the
  radius are intersected and refined with Newton's method). When the requested
  radius does not fit, the largest one that fits is used.
- NURBS are not supported.

**Bridge Curves** joins two selected end points with a Bezier segment that
follows the tangent of both curves, without changing either curve. Select
exactly two end points of open splines (two splines of one object, or one
spline in each of two objects).

- *Tension* (default 1.0, no upper limit, in the F9 panel): the length of the
  handles is `Tension * distance / 3`. 0.0 gives a straight segment. Dragging
  goes up to 4.0; higher values can be typed.
- Two splines of the same object are welded into a single Bezier spline. If
  the two points are the two ends of the same spline, it is closed.
- Two different objects: a new `Bridge` object is created, with the look of the
  active object, and the originals are not modified.
- Poly splines are converted to Bezier when they are welded.
- Handle types follow the same rules as Round Corners: Vector along straight
  segments (Tension 0.0 gives Vector handles at 1/3), Aligned where two curved
  segments meet.
- Works in 2D and 3D. Poly and Bezier only.

### Arcs to Corners (Edit Mode)

**Arcs to Corners** is the inverse of *Round Corners*: it brings back the hard
corner a curved segment was rounded from. Its button is in the same group,
slightly apart under *Round* and *Bridge*.

Select **two consecutive control points** and the two handles that shape the
segment between them are prolonged until they meet; a new control point with
**Vector** handles is placed at that meeting point, so both sides of the corner
come out straight. The two original points are left **selected with their
handles** and the new corner **unselected**, so a *Dissolve* right after
removes exactly those two points and leaves the hard corner alone. *Round
Corners* leaves its own two points selected, so the two buttons can be pressed
one after the other with nothing to reselect, and the corner lands back where
it was.

**Several pairs at a time**: every pair of consecutive selected points is
solved, so selecting the whole of a rounded rectangle un-rounds its four
corners in one press (its straight sides have parallel handles and are left
alone). A pair that is **not** selected is never touched, so a corner can be
kept rounded on purpose. On a closed spline the pair from the last point to the
first counts as well.

A segment is **left alone**, and the report says how many were, when its
handles do not meet in front of both points:

- a **straight** segment, and an **exact half turn**: parallel handles, no
  meeting point at all;
- an **S** shape, and handles pointing backwards: they would meet *behind* the
  points, putting the corner on the wrong side;
- an **almost** straight segment or an **almost** half turn (over 179.4
  degrees), whose meeting point lies absurdly far away: more than a hundred
  times the distance between the two points;
- in 3D, two handles that are **not in the same plane**: they never meet. No
  plane is asked of the spline as a whole, though: every segment is solved on
  its own, so a flat segment of a warped 3D spline works too, whatever its
  orientation. The gap accepted as a meeting point is a ten-thousandth of the
  distance between the points, which covers the single precision of curve
  coordinates and nothing more.

Notes:

- **Poly and NURBS** splines have no handles to prolong (a Poly segment is
  straight), so they are ignored and the report says so.
- The handles that now aim at the corner become **Free**, and so does any
  **Auto** handle of the two points, on either side: Blender recomputes an Auto
  handle from the neighbouring points, and the corner is a new neighbour that
  would bend the previous and the next segment, which have to stay as they are.
  A **Vector** handle stays Vector, and an **Aligned** handle on the outer side
  stays Aligned (the direction of the inner handle does not change, so there is
  nothing to re-align). Those handles are put at **a third of the way** to the
  corner, the length a Vector handle takes on a straight segment.
- *Dissolve Originals* (off by default, in the *Adjust Last Operation* panel,
  F9) runs Blender's own *Dissolve Vertices* right after, which removes the two
  original points and refits the segments around the corner. It is off so that
  the curvature next to the corner can be looked at first, which is the whole
  point of leaving the two points selected.
- Radius, tilt and softbody weight of the new corner are the **average** of the
  two points, so a bevel or a taper along the curve does not jump at it.

### Curve Offset (Object and Edit Mode)

**Offset** creates a curve parallel to every selected one, at a signed
*Distance*. The button is drawn at the top of the Utilities group.

In **Object Mode** the originals are not modified and stay visible; each one
gets a new object, `Curve Offset`, with its look (bevel, fill, materials...)
and its transform. The new curves end up selected, so they can be offset again
right away.

In the **Edit Mode** of a curve no new object is made: the offset of every
selected spline goes **into the same curve**, as a new spline right after the
one it comes from, which stays where it was.

- A spline with only some of its points selected is taken **whole**, which is
  the *Select Linked* one would do by hand. On a Bezier spline a selected
  handle is enough.
- Only the offset is left **selected**, so it can be offset again right away.
- One spline can give **more than one**, where *Clean Overlaps* cuts it in two.
- A spline that the Distance eats whole gives nothing, so it is **left alone**
  and the report says how many.
- The object is **never converted from 3D to 2D** (that is a setting of the
  whole object, and the other splines are none of our business): the selected
  splines simply have to be flat in the local XY plane, which is checked
  before anything is written.
- Several curve objects in Edit Mode at the same time are handled.

- *Distance* (F9 panel): on a **closed** curve, positive goes **outwards** and
  negative **inwards**, whichever way the curve turns (clockwise or not). On an
  **open** curve, positive goes to the **left** of its direction and negative
  to the right. It is a length in the scene, so the scale of the object is
  taken into account (a non-uniform scale in X / Y cannot be honoured exactly
  and is reported).
- *Corners*: how a corner that opens a gap is closed.
  - **Miter** (default): both sides are prolonged until they meet. Between two
    straight sides they are simply made longer, so the offset of a rectangle is
    again a rectangle with four points.
  - **Round**: an arc of radius equal to the Distance, which is the exact
    offset of the corner.
  - **Bevel**: a straight segment between the two sides.
- *Miter Limit* (default 4.0, only with Miter): the longest miter, as a
  multiple of the Distance. A corner so sharp that its miter would shoot
  further out than this gets a bevel instead.
- *Clean Overlaps* (on by default): removes the parts that fold back over the
  curve, which appear on concavities tighter than the Distance, and where a
  closed curve is shrunk past its own width. Turn it off to see the raw offset
  of every segment.
- *Both Sides* (off by default): one parallel on **each** side of the curve
  instead of one. The **sign of the Distance then means nothing**: there is a
  parallel either way, so it is used as a width. In Object Mode both go into
  the **same** new object; in Edit Mode both go into the same curve, right
  after the spline they come from.
- *Join Both with Arcs* (off by default, greyed out until *Both Sides* is on):
  closes the two parallels of an **open** spline with a **half circle of radius
  equal to the Distance** at each end, so the pair comes out as a **single
  closed curve**. A **closed** spline has no ends to join, so it simply keeps
  its two parallels, inside and outside.

Each half circle is built as **two quarters**, which is one control point of
its own between the two ends of the parallels - the fewest a round half turn
can have. One cubic per quarter is off by 0.03% of the radius, which is
invisible; one cubic for the whole half turn would be off by a few percent,
which is not. A Poly spline becomes a **Bezier** one when the arcs are added,
for the same reason Round corners do that: an arc is not something a Poly
spline can hold.

When *Clean Overlaps* cuts an offset into several pieces or eats an end away -
which happens when the Distance is larger than a concavity of the curve - the
ends the arcs would close onto are no longer there. The two parallels are then
left as they are, unjoined, and the report says how many splines that happened
to. Lowering the Distance, or turning *Clean Overlaps* off, gets the arcs back.

Notes:

- **Bezier curves stay Bezier**. The parallel curve of a Bezier segment is not
  a Bezier curve, so it is approximated: the segment is cut where the offset
  would have a cusp, and each piece becomes a cubic whose ends and tangents are
  exact and whose handles are solved so that it also passes through the exact
  offset of its midpoint. The piece is halved until the error is under 0.05% of
  the size of the curve, so a few extra control points appear only where one
  cubic is not enough. The offset of a Bezier circle still has four points.
  (Blender's own offset turns Bezier curves into polylines.)
- **Poly curves stay Poly**, with Miter or Bevel corners. With Round corners
  the arcs make it a Bezier curve.
- Points that reach the result untouched keep their radius, tilt and (when it
  is still valid) their handle type; Auto and Aligned become Aligned, so the
  shape is exactly the offset one but moving one handle still moves the other.
  Points along straight sides get Vector handles.
- A closed curve shrunk enough **falls apart into several curves**, and all of
  them are put in the same new object. If nothing is left, nothing is created
  and a message explains why.
- Same requirements as the Booleans: Poly or Bezier **2D** curves (in Object
  Mode flat 3D curves are converted to 2D automatically). NURBS are not
  supported, as a parallel NURBS curve is a different problem.
- Several objects can be offset at once, and an object with several splines
  offsets all of them (in Edit Mode, all the splines that are selected).

### Extend Curve (Edit Mode)

**Extend** grows the open splines of a curve out of their selected end points.
The button is under *Offset*. Each of those points stays where it is, a new
piece comes out of it, and the **new end points** are the ones left selected,
so the button can be pressed again to keep going.

**Several end points at a time** are extended with the same settings, including
both ends of one spline, and across several objects in Edit Mode. A selected
point that is not the end of an open Poly or Bezier spline (one in the middle,
one of a closed spline, one of a NURBS spline) is simply **left alone**, and
the report says how many were. With a mix of Poly and Bezier splines, each
setting applies to the ones it is meant for, and the ones that apply to
nothing are greyed out.

The piece is an **arc of a circle**, which is the shape that behaves at any
distance: it leaves the curve with the same tangent and keeps turning at the
same rate. (The other candidate, prolonging the cubic of the last segment, also
leaves with the same curvature, but a cubic shoots off as soon as the distance
grows.)

- *Distance*: length of the new piece, measured along it. Its default is about
  **15% of the largest side of the bounding box** of the spline (of the largest
  one, when several are extended), rounded to a round number (1, 1.5, 2, 3, 5
  or 7.5 times a power of ten), so 0.16489 m comes in as 0.15 m. It is a length
  in the scene, so the scale of the object is taken into account. From 0 up,
  with no upper limit.
- *Curvature* (Bezier): **Automatic** keeps turning as the curve does where it
  arrives, with the radius of its osculating circle there (which depends on the
  handle that arrives, and on the point and handle before it). **Manual** takes
  the turn from the angle below.
- *Curvature* angle (Bezier, Manual only): the **turn of the arc itself**, in
  degrees. 0 leaves straight along the tangent, positive turns to the **right**
  and negative to the **left**, up to a **full circle** either way (soft limits
  at 180 degrees, so dragging stays usable and a wider turn is typed in). The
  angle is exact, so this also draws arcs of 30, 45, 90 or 120 degrees, and at
  360 degrees the new end point lands on the one it grew from (the spline stays
  open).
- *Direction* angle (Poly): the straight piece leaves in the direction of the
  last segment **turned by this angle**, from -180 to +180 degrees, positive to
  the right. At 0 it carries straight on, at 90 it leaves square to it.

Notes:

- A **Poly** spline has no curvature to continue, so it is always extended
  **straight**, with one new point, in the direction *Direction* says.
- Extending a Bezier curve needs the **outgoing handle** of its end point,
  which an Auto or Aligned handle would not keep: Blender recalculates those as
  soon as the point has a neighbour, and the last segment would change shape.
  So that handle becomes **Free** (a Vector handle stays Vector, and a straight
  piece is exactly what a Vector handle does). The handle that *arrives* at the
  point, and everything before it, do not move.
- A turn of more than 90 degrees comes in as **several cubics** (one every 90
  degrees), as Round Corners does, because a single cubic cannot hold a wider
  arc accurately. A Distance so large that the arc would wind more than a full
  turn is clamped to one turn.
- **Both angles turn in the plane the spline lies in**, whatever its
  orientation: a curve drawn in the XZ plane or in a tilted one turns inside
  it. Left and right are then the ones seen from the + side of that plane (+Z
  for a curve in the XY plane), and the side is chosen from the plane itself,
  not from the order of the points, so it never flips between one press and the
  next. Only a **warped** 3D spline has no plane of its own: there the local XY
  plane, the plane the curve is bending in, or the first axis that is not along
  the tangent is used, in that order.
- The end point of a **closed** (Cyclic) spline is not an end point, so it is
  refused, as are NURBS splines and a selection that is not one single end
  point.
- A zero-length handle at the end point is not a problem: the direction comes
  from the derivative of the last segment, and when that is zero, from the
  point and handle before it.

### Slide Point (Edit Mode)

**Slide Point** moves a control point **along the curve it sits on**, keeping
the shape of that stretch as close to what it was as possible - the way *Vertex
Slide* moves a vertex of a mesh along an edge, except that here the point runs
along the curve and the handles have to be resized for the shape to stay. The
button is under *Extend*. **Bezier splines only.**

*Position* (F9 panel, 0 to 1) is where the point sits in its **span**, measured
by **length along the curve**:

- A point **in the middle** has two neighbours, so its span is the pair of
  segments between them: 0 is the previous point and 1 is the next one. The
  slider opens showing **where the point already is** - 0.85, say - so typing
  **0.5** puts it exactly halfway along that stretch.
- An **end point** has one neighbour and one segment: 0 is where it is now and
  1 is its neighbour, so sliding it **shortens** the curve at that end.

Several points can be slid at once, each in its own span, and they all go to
the same *Position*; the slider then opens at the position of the first one.
Two points that are **neighbours** are refused, because they share a segment
and one would undo the work of the other (two points with at least one point
between them never touch the same handle).

#### How close the shape stays

The report says, every time, either that the shape is unchanged or how far it
drifted, as a percentage of the length of the span.

- An **end point** is **exact**, always. Cutting a cubic short at a parameter
  is de Casteljau's algorithm, and what is left is the very same curve.
- A point **in the middle** is **exact** whenever the two segments of its span
  are two pieces of a single cubic - which is what *Subdivide* and *Split at
  Points* leave behind, and what a curve drawn and then cut usually is. The
  parent cubic is reconstructed from the two and cut again at the new place, so
  nothing moves at all. (The two pieces of a cubic cut at *tau* leave their
  junction with speeds in the ratio *tau* : 1 - *tau*, which is exactly what
  the two handles there measure, so *tau* can be read off them and the parent
  rebuilt and checked.)
- **Otherwise it cannot be exact**, and that is not a shortcoming of the tool:
  a pair of cubics is a curve of degree six, and asking a *new* pair to trace
  it again from a different junction has no solution in general. What happens
  instead: the side of the new point that stays **inside one of the two
  original segments** is still exact, and the other side, which has to merge
  the rest of one segment with the whole of the other, is **fitted**. In
  practice the drift stays well under 1% of the span, and under 2.5% in the
  worst cases (the point pushed close to one of its neighbours on a stretch
  that changes direction).

The fit has only **two unknowns**, the lengths of the two handles: both ends
and both tangent *directions* are already fixed by the exact side and by the
neighbour, so the curve leaves and arrives exactly as it did and only its
fullness is solved for. A least squares pass sets the two lengths, and a short
search then trims them against the real distance between the two curves, which
is not quite the same thing as the distance between points sharing a parameter.

#### Notes

- Sliding a point to **where it already is** gives the curve back untouched.
  (The *Position* value travels through a 32 bit float, so a value within a
  thousandth of the junction is snapped to it rather than fitting one segment
  to a sliver of nothing plus its neighbour.)
- The point never quite reaches a neighbour: it stops a thousandth of the span
  short, so no segment is left with zero length.
- A point whose **handles are not aligned** is a **corner**, and it is
  **refused** with the angle it turns in the message. A corner cannot be slid
  with the shape kept: the kink would have to travel with the point, and no
  pair of cubics through the new position can reproduce it. Up to one degree
  of turn still counts as smooth. Align the handles first, or slide a smooth
  point.
- The slid point comes out **Aligned** on both sides (its two handles are
  collinear by construction), or **Vector** where its span is straight.
- The **neighbours do not move**, and neither does anything beyond them. Only
  the handle that faces the slid point changes. An **Auto** handle on the far
  side of a neighbour becomes **Free** where it is, because Blender would
  otherwise recompute it now that its neighbour has moved, and that would
  change a segment this tool has no business touching.
- The **outer** handle of an end point belongs to no segment, so it travels
  with its point (a Vector one is put back at a third of the way).
- **Poly** splines are refused: sliding a point along the two legs would cut
  the corner instead of keeping the shape, which is a different tool. **NURBS**
  splines are refused too, since their control points are not even on the
  curve.
- Works in **3D** (the whole tool is, Offset and the Booleans being the 2D
  ones) and in the **local space** of the curve, so the transform of the object
  does not change the result.
- A **closed** spline slides like an open one; point 0 of a closed spline has
  two neighbours like any other. A closed spline of only two points is refused.

### Merges (Edit Mode)

Blender can merge the vertices of a mesh but not the control points of a curve.
These two tools do, each of them only ever welding points that can be welded
without tearing a spline apart.

| Tool | What it does |
| --- | --- |
| Merge Pair | Welds **two selected control points** into one, **however far apart they are** (no Threshold). *Merge*: **At Center** (default), **At Point A** or **At Point B**. Any curve type (Poly, Bezier and NURBS; 2D and 3D). |
| Merge by Distance | Welds every pair of **selected end points** closer to each other than the *Threshold*, **at their centre**, chaining open splines into as few as possible. Splines of different types are never welded to each other. |

**Merge Pair** takes the pair in index order: **A** is the point that comes
first (the lower index, or the one in the first spline) and **B** the other, so
the result does not depend on the order in which they were picked. Blender does
not expose the *active* control point of a curve to add-ons, which is why the
two are told apart by index and not by which one was selected last. Only the
control point counts as a selection here: a handle picked on its own is not
asking for its point to be moved.

The three pairs it accepts are:

- **Two neighbouring points of the same spline** (open or closed; on a closed
  one the last point and point 0 are neighbours too). The spline loses a point.
- **The two end points of the same open spline**, which **closes** it.
- **The end points of two different open splines**, which **joins** them into
  one. The first spline is laid out first, so one of the two may come out with
  its direction inverted.

Everything else is refused with the reason, because it would cut a spline in
two or invent a connection: two points in the middle of a spline that are not
neighbours, two middle points of different splines, a point of a closed spline
welded to another spline, a pair of splines of different types, and the only
two points of a spline (welding them would leave a single point). A NURBS
spline that ends up with fewer points than its *Order U* has the order lowered
to fit, and the report says so.

On a **Bezier** spline the handles **travel with their point**, keeping their
length and direction, so the curve arrives at the weld exactly as it did
before. Of the two handles that meet there, the incoming one of the first point
and the outgoing one of the second survive, which is what keeps the shape of
the two segments that stay. Handles that were *Auto* or *Aligned* become
*Free*, so Blender does not recompute them and change the shape; *Vector*
handles stay *Vector*.

**Merge by Distance** only looks at **end points**: two points that happen to
overlap in the middle of a spline are left alone, which is what *Remove
Doubles* is for. A spline whose **own two ends** fall within the Threshold is
closed. The closest pair is welded first and the search then starts again, so
the result does not depend on the order of the splines. Select the end points
to consider (`A` selects them all); nothing selected cancels with a hint. It
shares the *Threshold* with *Join & Merge*, the Object Mode tool that does the
same welding after joining the curves, which is why it sits right above it in
the panel. *Merge Pair* sits slightly apart from both: it is the one the
Threshold does not reach.

### Utilities

| Tool | Where | What it does |
| --- | --- | --- |
| Set First Point | Edit Mode | The selected point becomes point 0. On an open spline only an end point can be selected, and it inverts the direction. Any curve type. |
| Invert Direction | Object / Edit | Reverses the order of the points keeping the shape. On a closed spline point 0 stays point 0. Edit Mode: only splines with selected points. Any curve type. |
| Subdivide | Edit Mode | Blender's own *Subdivide*: adds points between the selected ones, keeping the shape. *Number of Cuts* in the F9 panel. Any curve type. |
| Simplify | Edit Mode | Blender's own *Decimate Curve* (right click > Simplify): removes points while keeping the shape as close as possible. *Ratio* in the F9 panel (1.0, the default, changes nothing: lower it). **Bezier only**, it warns on the other types. |
| Dissolve | Edit Mode | Blender's own *Dissolve Vertices*: removes the selected points and joins their neighbours, so the shape does change (unlike Simplify, which tries to keep it). End points cannot be dissolved. Any curve type. |
| Split at Points | Object / Edit | Every segment between control points becomes a new curve object (`Split_01`, `Split_02`...). The original stays hidden. Edit Mode: cuts only at the selected points. The button is drawn with the Splits and uses the Sources / Results collection options. Poly and Bezier only. |
| Join & Merge | Object | Joins the selected curves (like Ctrl+J) and welds the end points closer than the *Threshold* into as few splines as possible. A mix of Poly and Bezier is converted to Bezier. Poly and Bezier only. If some ends are farther apart than the Threshold, separate splines remain and a warning is shown. |
| Separate All Selected | Edit Mode | Every selected spline goes to a **new curve object of its own** (`c_01`, `c_02`...), the way *Separate by Loose Parts* does with the islands of a mesh (Blender's own *Separate* puts them all in one object instead, and cuts a partly selected spline). A spline with only some of its points selected goes whole. The splines leave the curve they were in, which keeps the ones that were not selected; when **every** spline is selected, one is left behind so the object is not left empty. Ends in Object Mode with the new objects selected, and nothing is hidden. Any curve type. |
| Remove Doubles | Object / Edit | Merges consecutive points closer than the *Threshold*, keeping the outer handles so the shape does not change. Edit Mode: only selected points. Any curve type. |
| Remove Strays | Object / Edit | Removes the stray splines that booleans, offsets and splits can leave behind: those with a **single point** and those **shorter than the Threshold**, measured in world space (so the scale of the object counts). Object Mode: every spline of the selected curves. Edit Mode: every spline of the curves being edited, **selected or not**, because a stray spline is hard to see and harder to pick. A curve whose splines are all strays is left with none, and the report says so. Of a NURBS spline the control polygon is measured, which is never shorter than the curve, so one is only removed when it really is a stray. Any curve type. |
| Set Resolution | Object / Edit | Gives the same *Resolution U* (the points Blender computes between every pair of control points) to many splines at once. On a row of its own, the field next to **Set All** reads and writes the **curve** in Object Mode and the **active spline** in Edit Mode, when one has really been made active: the same two values as *Object Data > Shape* and *Sidebar > Item*. **Set All** then spreads that value: in Object Mode to every spline of all the selected curves and to their curve data; in Edit Mode to every spline with a selected point or handle, leaving the curve data with its own value. The field is a property of the toolkit that passes the value through, not the native one, so that **Backspace over it gives 12**, the resolution of a new curve, whichever of the two it is pointing at (see the note below). Any curve type. |

The *Threshold* (default 0.001 m) is shared by Merge by Distance, Join & Merge,
Remove Doubles and Remove Strays.

Blender itself keeps **two** Resolution U: the one of the curve (*Object Data >
Shape > Resolution Preview U*), which it hands to every spline as soon as it is
changed, and the one of each spline (*Sidebar > Item > Active Spline*). They are
different properties, and only the first one declares a default, 12; the one of
the spline declares none, so Blender resets it to 0, which the field clamps to
**1**. That is why Backspace gives 12 in one place and 1 in the other, and why
the field of this panel is one of the toolkit's own, with 12 as its default,
that reads and writes whichever of the two it is pointing at.

**Cyclic** is Blender's own *Cyclic U* of the **active spline** (the one of
*Sidebar > Item > Active Spline*), so it shows the state and changes it, and it
is only available in Edit Mode. Next to it, **Toggle All** is Blender's own
*Toggle Cyclic* (`Curve > Toggle Cyclic`), which opens or closes **every
selected spline** at once instead of only the active one.

### Change Origin (Object Mode)

Acts on all the selected curves. **In**, **Mid** and **Out** move the origin to
Factor 0.0, 0.5 and 1.0 of the first spline, measured along its length (like
the Factor of *Sample Curve* in Geometry Nodes). **Geo** is Blender's own
*Origin to Geometry*. The geometry does not move, and children keep their
place. Curves whose data is shared by several objects are skipped.

## Notes

- Selection flags, radius, tilt, weights and handle types of the points are
  kept by all the tools. Custom per-point attributes of curves are not.
- Blender cannot reorder or delete spline points in place, so the tools rebuild
  the affected splines. As a side effect, switching to Object Mode and back to
  Edit Mode happens inside the Edit Mode tools.
- The tools never read `Object.matrix_world`, which is runtime data filled in
  by the depsgraph: an operator that runs again from the *Adjust Last
  Operation* panel runs right after the undo step and before the next
  evaluation, where that matrix can still be the identity. They go through
  `context_utils.world_matrix()`, which builds the matrix from the location,
  rotation and scale of the object and the parent inverse of its chain
  (objects with constraints, or parented to a bone or to vertices, fall back
  to `matrix_world`).

## Development

```
etr_curves_toolkit/        the Blender Extension (zip this folder)
dev/make_icons.py         generates the PNG icons (preview sheet: second argument)
dev/test_engine.py        tests of the 2D engine (plain Python, no Blender needed)
dev/test_offset.py        tests of the offset engine (plain Python too)
dev/test_phase1.py        tests of utilities, Round and Bridge (Blender as a Python module, bpy)
dev/test_phase3.py        tests of booleans and splits (bpy)
dev/test_edit_mode.py     tests of the primitives, of Offset in both modes and of
                          world_matrix() (bpy)
dev/test_phase9.py        tests of Arcs to Corners, Remove Strays and
                          Set Resolution (bpy)
dev/test_phase10.py       tests of Merge Pair and Merge by Distance (bpy)
dev/test_phase11.py       tests of Offset > Both Sides and Join Both with Arcs (bpy)
dev/test_phase12.py       tests of Slide Point (bpy)
```

`etr_curves_toolkit/curve_engine.py` is the pure-Python 2D engine of the
booleans and splits: exact Bezier intersections (subdivision + Newton),
overlap detection, exact even-odd point-in-region test, cutting with de
Casteljau and chaining the kept pieces into loops.

`etr_curves_toolkit/offset_engine.py` is the pure-Python 2D engine of the
offset: offset of each segment (exact for lines, fitted cubics for curves, cut
at the cusps), corner joins, and removal of the parts that fold back over the
curve, using the intersections of `curve_engine`. `close_both_sides()` is its
other entry point: it takes the two offsets of an open path and closes them
into one loop with a half-turn at each end, or returns None when the ends of
the offsets are no longer the exact offsets of the ends of the original.

`etr_curves_toolkit/extend.py` works in 3D and needs no engine: the frame at the
end of a spline (tangent, centre of curvature and curvature, from the
derivatives of the last cubic) and then `geometry.arc_beziers()`, the same arc
Round Corners is built with.

`etr_curves_toolkit/arcs_to_corners.py` works segment by segment: the meeting
point of the two handle lines, with the closest points of the two lines when
they are skew, and the checks that tell a real corner from a straight segment,
a half turn, an S shape or two handles that never meet.

`etr_curves_toolkit/slide.py` works in 3D and needs no engine either: the span
of a point as a chain of one or two cubics, its length table (so Position is
measured along the curve and not in the parameter), de Casteljau for the parts
that stay exact, the reconstruction of the single cubic two segments may be
pieces of, and the two-unknown fit plus its downhill trim for the rest.

`etr_curves_toolkit/merge.py` holds the two merges of the control points, and
shares `merge_chains()` with Join & Merge: the welding of the end points that
lie within the Threshold, closest pair first.

Run the tests: `python dev/test_phase1.py <folder containing etr_curves_toolkit>`
(same for the other eight). The seven `bpy` suites also run against the
`bpy` wheel of the matching Blender version (`pip install bpy==5.2.3`), with no
Blender installed.

Build the extension: `blender --command extension build --source-dir etr_curves_toolkit`

## License

GPL-3.0-or-later. Copyright (C) 2026 Cristobal Vila (etereaestudios.com)
