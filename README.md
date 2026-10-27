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

Panel location: **3D Viewport > Sidebar (N) > Tool > Curve Toolkit**.

## What is included

| Group | Tool | Status |
| --- | --- | --- |
| Primitive Curves | Line, Bezier, Rectangle, Polygon, Circle | Done (new object in Object Mode, new spline in Edit Mode) |
| Curve Booleans | Union, Intersection, Difference | Done |
| Curve Splits | Split Active, Split All | Done |
| Rounds, Bridge & Corners | Round Corners | Done (straight and curved corners, Radius and Tension) |
| Rounds, Bridge & Corners | Bridge Curves | Done |
| Rounds, Bridge & Corners | Arcs to Corners | Done (several pairs at a time, optional Dissolve Originals) |
| Curve Offset | Offset | Done (Miter / Round / Bevel corners, overlaps cleaned, Both Sides and Join Both with Arcs; new object in Object Mode, new spline in Edit Mode) |
| Extend Curve | Extend | Done (Automatic or Manual curvature in degrees, Direction for Poly, several end points at a time) |
| Slide Point | Slide Point | Done (Position along the span, exact on end points and on subdivided cubics, fitted otherwise; Bezier only) |
| Merges | Merge Pair | Done (At Center / At Point A / At Point B, any curve type) |
| Merges | Merge by Distance | Done (selected end points only, welded at their centre) |
| Utilities | Set First Point, Invert Direction, Subdivide, Simplify, Dissolve, Set Resolution, Split at Points, Separate All Selected, Join & Merge, Remove Doubles, Remove Strays, Cyclic | Done |
| Change Origin | In, Mid, Out, Geo | Done |

Full documentation of every tool: [etr_curves_toolkit_docs/README.md](etr_curves_toolkit_docs/README.md)
Version history: [etr_curves_toolkit_docs/CHANGELOG.md](etr_curves_toolkit_docs/CHANGELOG.md)

## License

GPL-3.0-or-later. Copyright (C) 2026 Cristobal Vila (etereaestudios.com)
