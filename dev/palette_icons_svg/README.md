# Palette icons (SVG)

Vector versions of the 33 icons of the Curve Toolkit panel, written by
`dev/make_icons.py` from the same shapes as the PNG files the extension loads
(`etr_curves_toolkit/icons/*.png`):

```
python dev/make_icons.py etr_curves_toolkit/icons --svg dev/palette_icons_svg \
    --sheet dev/palette_icons_svg/palette_icons_sheet.svg
```

`palette_icons_sheet.svg` has all 33 icons in one document, in the order of
the panel (left to right, top to bottom: the four rows of Create Curves, then
Curve Booleans, then Shaping Splines), on a 6 × 6 grid of 32 × 32 px cells
with no gaps (192 × 192 px; the last three cells are empty). Slices of 32 px
over that grid give the icons one by one. Each icon is a group with its file
name as `id`.

- Document: 32 × 32 px (`viewBox="0 0 32 32"`), transparent background.
- Lines: 2.56 px wide, round caps and joins. Points: 3.03 px radius.
- Colors: white `#ffffff`, grey `#808080`, fill `#656565`. No other colors.
- The regions of the booleans, the white corners of Round and the gaps of the
  splits are clip paths (no SVG masks).

These files are for editing (Affinity, Inkscape, Illustrator...). They are
not part of the extension: Blender only reads the PNG files, and this folder
is outside `etr_curves_toolkit/`, so it never ends up in the `.zip`.

## Back to the panel

Each edited icon has to go back as `etr_curves_toolkit/icons/<same name>.png`:

- 32 × 32 px, RGBA with a transparent background, 8 bits per channel, sRGB.
- The file name (without `.png`) is the name the panel asks for: keep it.
- Export without metadata, and with antialiasing.
- Blender loads the icons when the extension is enabled: after replacing a
  PNG, disable and enable the extension (or restart Blender) to see it.

If the shapes are changed here, `make_icons.py` no longer describes them:
the next time it runs it would overwrite the edited PNG files. Either bring
the changes back into the script (or tell Claude the new values), or stop
using the script for those icons.
