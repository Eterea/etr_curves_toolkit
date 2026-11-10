# Eterea Curves Toolkit

Free tool for Blender by [Eterea Estudios](https://www.etereaestudios.com): a
Blender Extension dedicated to creating, refining and operating on curves
(Poly, Bezier and NURBS) — **Curve Toolkit**.

![Blender](https://img.shields.io/badge/Blender-5.2%2B-orange) ![License](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)

## Download and install

1. Go to the [**Releases**](../../releases/latest) page and download `etr_curves_toolkit-<version>.zip`.
2. In Blender: `Edit > Preferences > Get Extensions > ⌄ (top-right menu) > Install from Disk...`
3. Select the downloaded `.zip` and enable the extension if it is not enabled automatically.

To update, install the new `.zip` the same way: it replaces the previous version.

**Requires Blender 5.2 or newer.**

Panel location: **3D Viewport > Sidebar (N) > Eterea Curves**.

## What is included

In the same order as in the panel.

| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp; | Group | Tool | Status |
| :-: | --- | --- | --- |
| <img src="icons/create_curves.png" width="32" alt=""> | Create Curves | Line / Point, Bezier, Rectangle, Polygon, Circle | Done (new object in Object Mode, new spline in Edit Mode; Line / Point with a number of Points, 1 = a single stray point) |
| <img src="icons/circle_3_points.png" width="32" alt=""> | Create Curves | Circle from Center & Point, from 2 Points, from 3 Points, from Segment & Center, Inscribed in a Triangle, Tangent to 2 Segments | Done (from mesh vertices: new curve object; from curve points: new spline; plane from the view; Goal, Oriented, Normal Rotation, Arc and Add Helper Points options) |
| <img src="icons/tangents_2_circles.png" width="32" alt=""> | Create Curves | Tangents to 2 Circles | Done (outer tangents; optional crossing tangents, or the whole belt shape as a new object) |
| <img src="icons/tangents_from_point.png" width="32" alt=""> | Create Curves | Tangents from Point | Done (the two Poly lines from a point that touch a circle) |
| <img src="icons/perpendicular.png" width="32" alt=""> | Create Curves | Perpendicular from Point | Done (perpendicular, or bisector on corners; plane of the view; Length in F9) |
| <img src="icons/lines_from_points.png" width="32" alt=""> | Create Curves | Lines from Points | Done (selected points joined with straight lines, no crossings: a segment, or a closed shape; Poly spline in a curve, edges in a mesh) |
| <img src="icons/points_in_between.png" width="32" alt=""> | Create Curves | Points in Between | Done (stray Poly points in a curve, loose vertices in a mesh; Count in F9) |
| <img src="icons/points_along_curve.png" width="32" alt=""> | Create Curves | Points Along Curve | Done (Count stray points at equal lengths, optional points at the extremes, or only along a segment; new object in Object Mode, same curve in Edit Mode) |
| <img src="icons/points_at_intersections.png" width="32" alt=""> | Create Curves | Points at Intersections | Done (stray points where splines cross, themselves included; apparent crossings on the plane of an orthographic view; Poly, Bezier and NURBS) |
| <img src="icons/union.png" width="32" alt=""> | Curve Booleans | Union, Intersection, Difference | Done (also curves with holes or several closed splines) |
| <img src="icons/symmetrize.png" width="32" alt=""> | Curve Booleans | Symmetrize | Done (one side mirrored onto the other and welded on the axis, relative to an orthographic view; four directions; World Origin, Object Origin or 3D Cursor as center; open and closed curves) |
| <img src="icons/split_all.png" width="32" alt=""> | Curve Splits | Split Active, Split All, Split at Control Points, Split at Stray Points | Done (Split All also cuts curves where they cross themselves, and needs no active object; Split at Stray Points cuts splines where stray points of the same curve lie on them) |
| <img src="icons/round_corners.png" width="32" alt=""> | Shaping Splines | Round Corners | Done (straight and curved corners, Radius and Tension) |
| <img src="icons/bridge_curves.png" width="32" alt=""> | Shaping Splines | Bridge Curves | Done |
| <img src="icons/arcs_to_corners.png" width="32" alt=""> | Shaping Splines | Arcs to Corners | Done (several pairs at a time, optional Dissolve Originals) |
| <img src="icons/offset.png" width="32" alt=""> | Shaping Splines | Offset | Done (Miter / Round / Bevel corners, overlaps cleaned, Both Sides and Join Both with Arcs; Duplicate: new object or spline, or the original replaced) |
| <img src="icons/extend.png" width="32" alt=""> | Shaping Splines | Extend | Done (Automatic or Manual curvature in degrees, Direction for Poly, several end points at a time) |
| <img src="icons/slide_point.png" width="32" alt=""> | Shaping Splines | Slide Point | Done (Position along the span, exact on end points and on subdivided cubics, fitted otherwise; Bezier only) |
| <img src="icons/slice.png" width="32" alt=""> | Shaping Splines | Slice, Undo Slice | Done (double seams where you pick them: two coincident, unmerged straight segments between two points; joins a hole to its outer spline, or cuts a closed spline in two, as many times as needed; Undo Slice takes any seam away later; Bezier and Poly) |
| <img src="icons/handles_to_axis.png" width="32" alt=""> | Shaping Splines | Handles to Axis | Done (handles within a Threshold of a local axis turned onto it, keeping their length; Object and Edit Mode) |
| <img src="icons/handles_to_lines.png" width="32" alt=""> | Shaping Splines | Handles to Lines | Done (Bezier handles as Poly lines; new object in Object Mode, same curve in Edit Mode) |
| <img src="icons/utilities.png" width="32" alt=""> | Utilities | Select All by Type (None, Strays, Polys, Beziers, NURBS), Separate All Selected, Subdivide, Simplify, Dissolve, Set First Point, Invert Direction | Done |
| <img src="icons/snap_pair.png" width="32" alt=""> | Pairs and Merges | Snap Pair | Done (two points to the same place without welding: At Center / At Point A / At Point B; any point, any curve type, also mesh vertices) |
| <img src="icons/merge_pair.png" width="32" alt=""> | Pairs and Merges | Merge Pair | Done (At Center / At Point A / At Point B, any curve type) |
| <img src="icons/swap_pair.png" width="32" alt=""> | Pairs and Merges | Swap Pair | Done (two points swap places; any point, any curve type, also mesh vertices) |
| <img src="icons/merge_by_distance.png" width="32" alt=""> | Pairs and Merges | Merge by Distance | Done (selected end points only, welded at their centre) |
| <img src="icons/join_merge.png" width="32" alt=""> | Pairs and Merges | Join & Merge, Remove Doubles | Done (Threshold of Global Settings) |
| <img src="icons/set_resolution.png" width="32" alt=""> | Utilities | Set Resolution, Cyclic | Done |
| <img src="icons/change_origin.png" width="32" alt=""> | Change Origin | To World Origin, To 3D Cursor, To Selected Point (Edit Mode), In, Mid, Out, Geo (bounds center) | Done (In / Mid / Out / Geo also in Edit Mode, on the selected spline or segment) |

The **Threshold** shared by several tools is in **Global Settings**, near the bottom of the panel. The last sub-panel, **Documentation**, opens the full documentation online.

Full documentation of every tool: [etr_curves_toolkit_docs/README.md](etr_curves_toolkit_docs/README.md)
Version history: [etr_curves_toolkit_docs/CHANGELOG.md](etr_curves_toolkit_docs/CHANGELOG.md)

## Feedback and issues

Found a bug or have an idea? Please open an [issue](../../issues).

## More resources

More Blender resources, courses and tools: [etereaestudios.com/resources/blender-resources](https://etereaestudios.com/resources/blender-resources/)

## License

GPL-3.0-or-later. Copyright (C) 2026 Cristobal Vila (etereaestudios.com)
