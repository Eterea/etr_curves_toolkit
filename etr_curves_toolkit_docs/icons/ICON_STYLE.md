# Icon style guide — Eterea Curves Toolkit documentation

These icons illustrate the online documentation of the toolkit (the two README
files). **They are not the icons of the panel inside Blender** (those are the
32 px PNG files in `etr_curves_toolkit/icons/`, made by `dev/make_icons.py`).

They follow the same rules as the documentation icons of the sister kit,
Eterea Blender Tools (`etr_blender_tools_docs/icons/ICON_STYLE.md`): same tile,
palette, line weights and knockout outlines. This file repeats the essentials
and adds the curve vocabulary of this toolkit.

---

## Files and folders

| What | Where | Size |
| --- | --- | --- |
| Vector sources | `etr_curves_toolkit_docs/icons/src/<name>.svg` | 256 × 256 |
| Generator script | `etr_curves_toolkit_docs/icons/src/build_icons.py` | — |
| Large icons (full documentation README) | `etr_curves_toolkit_docs/icons/<name>.png` | 256 px, shown at 64 px (headings) or 32 px (tables) |
| Small icons (repository README table) | `icons/<name>.png` | 64 px, shown at 32 px |

- Both PNG sizes are rendered **from the vector source**, so the small ones stay crisp.
- The SVG sources are standalone, so they can be reused at any size (a poster, a slide).
- The documentation folders live outside the extension folder, so none of these files ends up in the installable `.zip`.

### Regenerating the icons

```
pip install cairosvg
python3 etr_curves_toolkit_docs/icons/src/build_icons.py
```

It rewrites the `.svg` sources and both PNG sets. Overlaps are painted flat
(shapes painted over each other, clip paths), never with SVG masks, which some
renderers ignore.

### Using them in the READMEs

```html
<img src="icons/<name>.png" width="32" alt="">          <!-- tables -->
### <img src="icons/<name>.png" width="64" alt=""> Section   <!-- headings -->
```

---

## Visual rules (shared with Eterea Blender Tools)

- Square 256 × 256 canvas; rounded tile `#2B2B2B`, corner radius 25.6 px, 4 px inner border `#3D3D3D`; transparent outside.
- Safe area 40–216 px. Flat: solid fills and strokes, no gradients, shadows or text.
- Round caps and joins. Strokes: 12 px main, 8–10 px secondary and arrows, 6 px guides and dashes.
- Knockout ring in the tile color around dots and badges that sit on lines.

| Role | Color |
| --- | --- |
| Tile / border | `#2B2B2B` / `#3D3D3D` |
| Light / mid / dark grey | `#E3E3E3` / `#A3A3A3` / `#6E6E6E` |
| **Orange** (the result) / dark orange (filled results) | `#FFA31A` / `#C2740A` |
| **Blue** (the action, the active point) / dark blue | `#4C9BF0` / `#2F64A8` |

## Curve vocabulary

| Motif | Meaning |
| --- | --- |
| Light-grey stroke with light dots | The curve as it is, and its control points |
| Orange stroke or orange dot | What the tool makes or changes (the new curve, the new point) |
| Blue dot | The active point (picked last), or the point the tool acts at (cut, tangent end) |
| Blue arrow | The action: move, slide, push out, merge |
| Dark-grey dashed stroke or dot | The state before the tool, or a guide (bisector, removed point) |
| Orange circle with a dark minus | Remove (the motif of the other kit) |
| Square + circle, as in the panel | Booleans and splits |
| Ring with a dot | The object origin |

## Current icons

Create Curves: `line`, `bezier`, `rectangle`, `polygon`, `circle`, `lines_from_points`, `points_in_between`,
`circle_center_point`, `circle_2_points`, `circle_3_points`, `circle_segment_center`,
`circle_inscribed`, `circle_tangent_2`, `tangents_2_circles`, `tangents_from_point`,
`perpendicular`, `points_along_curve`, `points_at_intersections`. Booleans group:
`symmetrize`. Booleans and splits: `union`, `intersection`,
`difference`, `split_active`, `split_all`. Shaping Splines: `round_corners`, `bridge_curves`,
`arcs_to_corners`, `handles_to_axis`, `handles_to_lines`. Tools: `offset`, `extend`, `slide_point`, `slice`, `snap_pair`, `merge_pair`,
`swap_pair`, `merge_by_distance`. Utilities: `set_first_point`, `invert_direction`, `subdivide`,
`simplify`, `dissolve`, `split_at_points`, `join_merge`, `separate`, `remove_doubles`,
`select_strays`, `select_polys`, `select_beziers`, `select_nurbs`, `remove_strays`, `set_resolution`, `cyclic`. Change Origin:
`origin_to_selected`, `change_origin`. Groups (repository README): `create_curves`,
`utilities`.

## Checklist for a new icon

1. Add a block to `build_icons.py`, named after the tool.
2. Light grey for the curve as it is, orange for the result, blue for the action or the active point.
3. Stay inside 40–216 px; minimum stroke 6 px; no text.
4. Run the script and check the 64 px PNG at 32 px on light and dark backgrounds.
5. Add it to both READMEs and to the list above.
