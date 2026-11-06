# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Plain-Python snapshots of Blender curve splines.

Blender's API cannot reorder or delete the points of a spline in place, so the
tools of this add-on read a spline into a SplineData snapshot, edit that
snapshot (rotate, reverse, merge, split, round...), and write it back as a
new spline with replace_splines().

The snapshots are independent of the object transform: coordinates stay in
the curve's local space.
"""

from dataclasses import dataclass, field, replace

import bpy

from . import geometry as geo

# Spline settings copied verbatim between a spline and its snapshot.
_SPLINE_SETTINGS = (
    "resolution_u",
    "order_u",
    "use_endpoint_u",
    "use_bezier_u",
    "use_smooth",
    "material_index",
    "tilt_interpolation",
    "radius_interpolation",
)


@dataclass
class PointData:
    co: tuple
    w: float = 1.0                  # NURBS weight (4th coordinate)
    hl: tuple = None                # Bezier left handle
    hr: tuple = None                # Bezier right handle
    hlt: str = 'VECTOR'             # left handle type
    hrt: str = 'VECTOR'             # right handle type
    radius: float = 1.0
    tilt: float = 0.0
    weight_softbody: float = 1.0
    select: bool = False            # control point selected
    select_left: bool = False
    select_right: bool = False


@dataclass
class SplineData:
    kind: str                       # 'BEZIER', 'POLY' or 'NURBS'
    points: list = field(default_factory=list)
    cyclic: bool = False
    settings: dict = field(default_factory=dict)

    def copy(self):
        return SplineData(
            self.kind,
            [replace(p) for p in self.points],
            self.cyclic,
            dict(self.settings),
        )


# -----------------------------------------------------------------------------
# Read / write
# -----------------------------------------------------------------------------

def read_spline(spline):
    """Snapshot a bpy Spline."""
    data = SplineData(
        kind=spline.type,
        cyclic=spline.use_cyclic_u,
        settings={name: getattr(spline, name) for name in _SPLINE_SETTINGS},
    )
    if spline.type == 'BEZIER':
        for bp in spline.bezier_points:
            data.points.append(PointData(
                co=tuple(bp.co),
                hl=tuple(bp.handle_left),
                hr=tuple(bp.handle_right),
                hlt=bp.handle_left_type,
                hrt=bp.handle_right_type,
                radius=bp.radius,
                tilt=bp.tilt,
                weight_softbody=bp.weight_softbody,
                select=bp.select_control_point,
                select_left=bp.select_left_handle,
                select_right=bp.select_right_handle,
            ))
    else:
        for p in spline.points:
            data.points.append(PointData(
                co=tuple(p.co)[:3],
                w=p.co[3],
                radius=p.radius,
                tilt=p.tilt,
                weight_softbody=p.weight_softbody,
                select=p.select,
            ))
    return data


def write_spline(curve, data):
    """Create a new spline in `curve` from a snapshot and return it."""
    n = len(data.points)
    spline = curve.splines.new(data.kind)
    if data.kind == 'BEZIER':
        spline.bezier_points.add(n - 1)
        bps = spline.bezier_points
        # Pass 1: positions, with FREE handles so nothing is recomputed.
        for bp, p in zip(bps, data.points):
            bp.handle_left_type = 'FREE'
            bp.handle_right_type = 'FREE'
            bp.co = p.co
            bp.handle_left = p.hl
            bp.handle_right = p.hr
        # Pass 2: final types, extra data and selection.
        for bp, p in zip(bps, data.points):
            bp.handle_left_type = p.hlt
            bp.handle_right_type = p.hrt
            bp.radius = p.radius
            bp.tilt = p.tilt
            bp.weight_softbody = p.weight_softbody
            bp.select_control_point = p.select
            bp.select_left_handle = p.select_left
            bp.select_right_handle = p.select_right
    else:
        spline.points.add(n - 1)
        for sp, p in zip(spline.points, data.points):
            sp.co = (p.co[0], p.co[1], p.co[2], p.w)
            sp.radius = p.radius
            sp.tilt = p.tilt
            sp.weight_softbody = p.weight_softbody
            sp.select = p.select
    spline.use_cyclic_u = data.cyclic
    for name, value in data.settings.items():
        try:
            setattr(spline, name, value)
        except (AttributeError, TypeError):
            pass
    return spline


def read_all(curve):
    return [read_spline(s) for s in curve.splines]


def point_selected(point, kind):
    """True when a point of a spline counts as selected in Edit Mode.

    On a Bezier spline a handle on its own is enough: moving a handle is as
    much a selection as picking the control point. Tools that work on whole
    splines (Offset, Separate) use this to decide which ones are picked.
    """
    if kind == 'BEZIER':
        return point.select or point.select_left or point.select_right
    return point.select


def selected_segment(data):
    """Index k of the segment picked by selecting its two ends, or None.

    It is picked when exactly two control points of the spline are selected
    (handles do not count) and they are consecutive: points k and k + 1, or
    the last and the first of a closed spline (its closing segment, k = n - 1).
    A single point, two points apart or three or more mean the whole spline.
    """
    picked = [i for i, p in enumerate(data.points) if p.select]
    if len(picked) != 2:
        return None
    a, b = picked
    n = len(data.points)
    if b == a + 1:
        return a
    if data.cyclic and n > 2 and a == 0 and b == n - 1:
        return n - 1
    return None


def replace_splines(curve, datas):
    """Replace every spline of `curve` by the given snapshots (in order)."""
    curve.splines.clear()
    for data in datas:
        write_spline(curve, data)


# -----------------------------------------------------------------------------
# Edits on snapshots
# -----------------------------------------------------------------------------

def reversed_point(p):
    """Point as seen when the spline direction is inverted."""
    q = replace(p)
    q.hl, q.hr = p.hr, p.hl
    q.hlt, q.hrt = p.hrt, p.hlt
    q.select_left, q.select_right = p.select_right, p.select_left
    return q


def inverted(data):
    """Spline with inverted direction and the same shape.

    Closed: point 0 stays point 0 and the others come in reverse order.
    Open: the whole sequence is reversed.
    """
    out = data.copy()
    n = len(out.points)
    order = [0] + list(range(n - 1, 0, -1)) if out.cyclic else list(range(n - 1, -1, -1))
    out.points = [reversed_point(data.points[i]) for i in order]
    return out


def rotated(data, start):
    """Closed spline whose first point is the point at index `start`."""
    out = data.copy()
    out.points = [replace(p) for p in data.points[start:] + data.points[:start]]
    return out


def to_bezier(data):
    """Poly spline as a Bezier spline with Vector handles (the result of
    Blender's own Set Spline Type > Bezier)."""
    if data.kind == 'BEZIER':
        return data.copy()
    if data.kind != 'POLY':
        raise ValueError("Only Poly splines can be converted to Bezier")
    out = data.copy()
    out.kind = 'BEZIER'
    pts = out.points
    n = len(pts)
    for i, p in enumerate(pts):
        prev_co = pts[i - 1].co if (i > 0 or out.cyclic) else None
        next_co = pts[(i + 1) % n].co if (i < n - 1 or out.cyclic) else None
        if prev_co is None and next_co is not None:
            prev_co = geo.sub(p.co, geo.sub(next_co, p.co))       # mirrored
        if next_co is None and prev_co is not None:
            next_co = geo.sub(p.co, geo.sub(prev_co, p.co))       # mirrored
        if prev_co is None:                                       # single point
            prev_co = next_co = p.co
        p.hl = geo.lerp(p.co, prev_co, 1.0 / 3.0)
        p.hr = geo.lerp(p.co, next_co, 1.0 / 3.0)
        p.hlt = p.hrt = 'VECTOR'
        p.w = 1.0
    return out


def settle_handle_type(handle_type):
    """Handle type to use once a handle has been moved by hand.

    Vector handles stay Vector (they follow the neighbour point, so the shape
    does not change). Auto and Aligned handles would be recalculated by
    Blender and could change the shape, so they become Free.
    """
    return 'VECTOR' if handle_type == 'VECTOR' else 'FREE'


def moved(point, delta):
    """Copy of a point translated by `delta`.

    On a Bezier point the handles travel with it instead of being recomputed,
    so they keep their length and direction relative to the point and the shape
    of the segments on either side is unchanged.
    """
    out = replace(point)
    out.co = tuple(c + d for c, d in zip(point.co, delta))
    if point.hl is not None:
        out.hl = tuple(c + d for c, d in zip(point.hl, delta))
    if point.hr is not None:
        out.hr = tuple(c + d for c, d in zip(point.hr, delta))
    return out


def moved_to(point, target):
    """Copy of a point placed at `target`, handles included (see moved())."""
    return moved(point, tuple(t - c for t, c in zip(target, point.co)))


def midpoint(a, b):
    return tuple(0.5 * (x + y) for x, y in zip(a.co, b.co))


def merge_points(left, right):
    """One point replacing two coincident ones.

    Takes the incoming side (left handle) from `left` and the outgoing side
    (right handle) from `right`, so the shape of both curves is unchanged.
    """
    out = replace(left)
    out.hl = left.hl
    out.hlt = settle_handle_type(left.hlt)
    out.hr = right.hr
    out.hrt = settle_handle_type(right.hrt)
    out.select = left.select or right.select
    out.select_left = left.select_left
    out.select_right = right.select_right
    return out


def flatten(data, steps=24):
    """Polyline approximation of a spline (closing segment included when
    cyclic). Used for lengths and for shape checks in the tests."""
    pts = data.points
    n = len(pts)
    if n == 0:
        return []
    if data.kind != 'BEZIER':
        out = [p.co for p in pts]
        if data.cyclic and n > 1:
            out.append(pts[0].co)
        return out
    out = [pts[0].co]
    last = n if data.cyclic else n - 1
    for i in range(last):
        a, b = pts[i], pts[(i + 1) % n]
        for s in range(1, steps + 1):
            out.append(geo.bezier_point(a.co, a.hr, b.hl, b.co, s / steps))
    return out
