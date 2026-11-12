# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
Curve Toolkit - Slide Point (Edit Mode)

Moves a control point *along the curve it sits on*, keeping the shape of that
stretch as close to what it was as it can be, the way Vertex Slide does with
the vertices of a mesh - except that here the point runs along the curve and
not along an edge, and the handles have to be resized for the shape to stay.

Position (0 to 1, in the F9 panel) is where the point sits in its span,
measured by *length along the curve*:

  - A point in the middle has two neighbours, so its span is the pair of
    segments between them: 0 is the previous point and 1 is the next one. The
    slider opens showing where the point already sits - 0.85, say - so typing
    0.5 puts it exactly halfway along that stretch.
  - An end point has one neighbour and one segment: 0 is where the point is
    now and 1 is the neighbour, so sliding it shortens the curve at that end.
    Its outer handle, which does not shape the curve, is the mirror image of
    the inner one while it slides (in line with it and as long).

How close the shape stays:

  - An **end point** is exact, always. Cutting a cubic short at a parameter is
    de Casteljau's algorithm, and what is left is the very same curve.
  - A **point in the middle** is exact whenever the two segments of its span
    are two pieces of a single cubic, which is what Subdivide and Split at
    Points leave behind. The parent cubic is reconstructed and cut again at the
    new place, so nothing moves at all.
  - Otherwise it cannot be exact, and this is not a shortcoming of the code: a
    pair of cubics is a curve of degree six, and asking a new pair to trace it
    again from a different junction has no solution in general. The side of the
    new point that stays inside one of the two original segments is still
    exact; the other side, which has to merge the rest of one segment with the
    whole of the other, is fitted. The operator measures how far the result
    drifts and says so in its report, as a percentage of the length of the
    span.

The fit has only two unknowns, the lengths of the two handles: both ends and
both tangent directions are already fixed by the exact side and by the
neighbour, so the curve leaves and arrives exactly as it did and only its
fullness is solved for. A least squares pass sets them, and a short search
then trims them against the real distance between the two curves.

Bezier splines only. On a Poly spline a "slide" would cut the corner instead
of keeping the shape, and on a NURBS spline the control points are not even on
the curve.

A point whose handles are not aligned is a corner, and a corner cannot be slid
with the shape kept: the kink would have to travel with the point, which no
pair of cubics through the new position can reproduce. Those are refused.
"""

import math

import bpy
from bpy.props import BoolProperty, FloatProperty

from . import geometry as geo
from . import spline_data as sd
from .context_utils import EDIT_MODE, edit_scope, has_active_curve

#: Largest turn, in degrees, still counted as a smooth point and not a corner.
CORNER_ANGLE = 1.0

#: Closest the point may get to a neighbour, as a fraction of the span.
MARGIN = 1e-3

#: Samples per segment of the reference used by the fit.
FIT_SAMPLES = 24

#: Reference and curve samples, and rounds, of the search that trims the fit.
POLISH_REFERENCE = 24
POLISH_SAMPLES = 10
POLISH_ROUNDS = 14

#: Two segments count as pieces of one cubic below this, relative to the span.
#: Blender keeps coordinates as 32 bit floats, so a curve that really was cut
#: out of one cubic comes back about 1e-7 of its size away from it; anything
#: tighter than that would never recognise one. Two segments that are not
#: pieces of one cubic are wrong by far more than this.
PARENT_TOLERANCE = 1e-5


class Rejected(Exception):
    """A point that cannot be slid, with the reason for the user."""


# -----------------------------------------------------------------------------
# Cubics, chains of cubics, and their length
# -----------------------------------------------------------------------------

def point_at(cubic, t):
    return geo.bezier_point(*cubic, t)


def speed_at(cubic, t):
    """First derivative of a cubic (not normalized)."""
    p0, h0, h1, p1 = cubic
    u = 1.0 - t
    return tuple(3.0 * u * u * (h0[i] - p0[i])
                 + 6.0 * u * t * (h1[i] - h0[i])
                 + 3.0 * t * t * (p1[i] - h1[i]) for i in (0, 1, 2))


def tangent_at(cubic, t):
    """Unit tangent of a cubic, also where the derivative vanishes because a
    handle sits on its own point."""
    for probe in (t, t + 1e-4, t - 1e-4, t + 1e-2, t - 1e-2):
        if 0.0 <= probe <= 1.0:
            d = geo.normalized(speed_at(cubic, probe))
            if d is not None:
                return d
    return geo.normalized(geo.sub(cubic[3], cubic[0]))


def reversed_cubic(cubic):
    p0, h0, h1, p1 = cubic
    return (p1, h1, h0, p0)


def chain_samples(cubics, per):
    """Points along a chain of cubics, the shared ends counted once."""
    out = [point_at(cubics[0], 0.0)]
    for cubic in cubics:
        out += [point_at(cubic, i / per) for i in range(1, per + 1)]
    return out


def _arc_table(cubics, per=64):
    """(global parameters, cumulative length) along a chain of cubics.

    The global parameter runs from 0 to the number of cubics: its whole part
    is the index of the cubic and its fraction the parameter inside it.
    """
    params, points = [], []
    for k, cubic in enumerate(cubics):
        for i in range(1 if k else 0, per + 1):
            params.append(k + i / per)
            points.append(point_at(cubic, i / per))
    _, cumulative = geo.sample_polyline(points)
    return params, cumulative


def chain_length(cubics):
    return _arc_table(cubics)[1][-1]


def param_at_factor(cubics, factor):
    """Global parameter at `factor` of the length of the chain."""
    params, cumulative = _arc_table(cubics)
    total = cumulative[-1]
    if total < geo.EPS:
        return factor * len(cubics)
    target = factor * total
    for i in range(1, len(cumulative)):
        if cumulative[i] >= target:
            step = cumulative[i] - cumulative[i - 1]
            w = 0.0 if step < geo.EPS else (target - cumulative[i - 1]) / step
            return params[i - 1] + w * (params[i] - params[i - 1])
    return params[-1]


def factor_at_param(cubics, g):
    """Where a global parameter sits in the length of the chain (0 to 1)."""
    params, cumulative = _arc_table(cubics)
    total = cumulative[-1]
    if total < geo.EPS:
        return 0.0
    for i in range(1, len(params)):
        if params[i] >= g:
            step = params[i] - params[i - 1]
            w = 0.0 if step < geo.EPS else (g - params[i - 1]) / step
            return (cumulative[i - 1] + w * (cumulative[i] - cumulative[i - 1])) / total
    return 1.0


def portion(cubics, g0, g1):
    """The cubics covering the part of a chain between two global parameters."""
    out = []
    for k, cubic in enumerate(cubics):
        a = max(g0 - k, 0.0)
        b = min(g1 - k, 1.0)
        if b - a <= 1e-12:
            continue
        out.append(geo.bezier_sub(*cubic, a, b))
    return out


def distance_to_polyline(p, points):
    """Shortest distance from a point to a polyline."""
    best = float('inf')
    for a, b in zip(points, points[1:]):
        ab = geo.sub(b, a)
        length2 = geo.dot(ab, ab)
        if length2 < 1e-18:
            d = geo.distance(p, a)
        else:
            t = max(0.0, min(1.0, geo.dot(geo.sub(p, a), ab) / length2))
            d = geo.distance(p, geo.add(a, geo.mul(ab, t)))
        if d < best:
            best = d
    return best


def drift(new_cubics, old_cubics, per=24, reference=60):
    """Largest distance from the new chain to the old one."""
    points = chain_samples(old_cubics, reference)
    return max(distance_to_polyline(point_at(cubic, i / per), points)
               for cubic in new_cubics for i in range(per + 1))


# -----------------------------------------------------------------------------
# Two pieces of one cubic
# -----------------------------------------------------------------------------

def _unsplit(left, tau):
    """The cubic W whose part from 0 to `tau` is `left` (de Casteljau run
    backwards)."""
    p0, a, d, m = left
    inv = 1.0 / tau
    rest = 1.0 - tau
    w1 = geo.add(p0, geo.mul(geo.sub(a, p0), inv))
    b = geo.mul(geo.sub(d, geo.mul(a, rest)), inv)
    w2 = geo.mul(geo.sub(b, geo.mul(w1, rest)), inv)
    e = geo.mul(geo.sub(m, geo.mul(d, rest)), inv)
    c = geo.mul(geo.sub(e, geo.mul(b, rest)), inv)
    w3 = geo.mul(geo.sub(c, geo.mul(w2, rest)), inv)
    return (p0, w1, w2, w3)


def parent_cubic(first, second, tolerance):
    """(the single cubic `first` and `second` are two pieces of, the parameter
    of their junction), or None when they are not.

    The two pieces of a cubic cut at `tau` leave the junction with speeds in
    the ratio tau : (1 - tau), which is what the handles on either side of it
    measure, so `tau` can be read off them and the parent rebuilt and checked.
    """
    arriving = geo.distance(first[3], first[2])
    leaving = geo.distance(second[1], second[0])
    if arriving + leaving < 1e-15:
        return None
    tau = arriving / (arriving + leaving)
    if not 1e-6 < tau < 1.0 - 1e-6:
        return None
    whole = _unsplit(first, tau)
    check = geo.bezier_sub(*whole, tau, 1.0)
    if max(geo.distance(x, y) for x, y in zip(check, second)) > tolerance:
        return None
    return whole, tau


# -----------------------------------------------------------------------------
# Fitting one cubic to a stretch of two
# -----------------------------------------------------------------------------

def _least_squares(start, out_dir, end, in_dir, references, params):
    """Handle lengths of the cubic that best follows `references`.

    The cubic is start + alpha * out_dir ... end - beta * in_dir, so only the
    two lengths are unknown and the problem is linear in them.
    """
    c11 = c12 = c22 = x1 = x2 = 0.0
    uv = geo.dot(out_dir, in_dir)
    for t, target in zip(params, references):
        u = 1.0 - t
        a = 3.0 * u * u * t
        c = 3.0 * u * t * t
        base = tuple((u ** 3 + 3.0 * u * u * t) * start[i]
                     + (3.0 * u * t * t + t ** 3) * end[i] for i in (0, 1, 2))
        d = geo.sub(target, base)
        c11 += a * a
        c12 += -a * c * uv
        c22 += c * c
        x1 += a * geo.dot(out_dir, d)
        x2 += -c * geo.dot(in_dir, d)
    span = geo.distance(start, end)
    det = c11 * c22 - c12 * c12
    if abs(det) < 1e-18:
        return span / 3.0, span / 3.0
    alpha = (x1 * c22 - x2 * c12) / det
    beta = (c11 * x2 - c12 * x1) / det
    floor = max(span * 1e-3, 1e-9)
    return max(alpha, floor), max(beta, floor)


def _cubic_from(start, out_dir, end, in_dir, alpha, beta):
    return (start, geo.add(start, geo.mul(out_dir, alpha)),
            geo.sub(end, geo.mul(in_dir, beta)), end)


def _reparametrize(cubic, references, params):
    """Move every sample parameter towards the closest point of the cubic."""
    out = []
    for t, target in zip(params, references):
        here = point_at(cubic, t)
        first = speed_at(cubic, t)
        diff = geo.sub(here, target)
        denominator = geo.dot(first, first)
        step = geo.dot(diff, first) / denominator if denominator > 1e-18 else 0.0
        out.append(min(1.0, max(0.0, t - step)))
    return out


def _polish(start, out_dir, end, in_dir, pieces, alpha, beta):
    """Trim the two handle lengths against the real distance between the fitted
    cubic and the stretch it stands for.

    The least squares pass minimises the distance between points that share a
    parameter, which is not the same as the distance between the two curves;
    this walks the pair of lengths downhill on the real one, halving the step
    whenever no direction improves.
    """
    reference = chain_samples(pieces, POLISH_REFERENCE)

    def worst(a, b):
        cubic = _cubic_from(start, out_dir, end, in_dir, a, b)
        return max(distance_to_polyline(point_at(cubic, i / POLISH_SAMPLES), reference)
                   for i in range(1, POLISH_SAMPLES))

    span = geo.distance(start, end)
    best = worst(alpha, beta)
    step = 0.25 * span
    for _ in range(POLISH_ROUNDS):
        for da, db in ((step, 0.0), (-step, 0.0), (0.0, step), (0.0, -step)):
            a, b = alpha + da, beta + db
            if a <= 0.0 or b <= 0.0:
                continue
            value = worst(a, b)
            if value < best - 1e-15:
                alpha, beta, best = a, b, value
                break
        else:
            step *= 0.5
            if step < 1e-6 * span:
                break
    return alpha, beta


def fit_one_cubic(pieces):
    """One cubic following a chain of two or more, with the ends and both
    tangent directions of the chain kept exactly."""
    start = point_at(pieces[0], 0.0)
    end = point_at(pieces[-1], 1.0)
    out_dir = tangent_at(pieces[0], 0.0)
    in_dir = tangent_at(pieces[-1], 1.0)
    references = chain_samples(pieces, FIT_SAMPLES)
    total, cumulative = geo.sample_polyline(references)
    if total < geo.EPS:
        params = [i / (len(references) - 1) for i in range(len(references))]
    else:
        params = [c / total for c in cumulative]
    alpha, beta = _least_squares(start, out_dir, end, in_dir, references, params)
    cubic = _cubic_from(start, out_dir, end, in_dir, alpha, beta)
    for _ in range(3):
        params = _reparametrize(cubic, references, params)
        alpha, beta = _least_squares(start, out_dir, end, in_dir, references, params)
        cubic = _cubic_from(start, out_dir, end, in_dir, alpha, beta)
    alpha, beta = _polish(start, out_dir, end, in_dir, pieces, alpha, beta)
    return _cubic_from(start, out_dir, end, in_dir, alpha, beta)


def slide_chain(cubics, factor, tolerance):
    """(the new pair of cubics, the new junction was placed exactly).

    `cubics` is the span of the point, one cubic for an end point and two for
    a point in the middle; the result has the same number.
    """
    if len(cubics) == 1:
        # An end point: what is left of the segment is the same curve. Only the
        # far side needs a margin - at 0 the point simply stays where it is.
        g = min(param_at_factor(cubics, factor), 1.0 - MARGIN)
        return [geo.bezier_sub(*cubics[0], g, 1.0)], True

    whole = parent_cubic(cubics[0], cubics[1], tolerance)
    if whole is not None:
        # The two segments are two pieces of one cubic: cut it again.
        parent, tau = whole
        g = min(max(param_at_factor(cubics, factor), MARGIN), 2.0 - MARGIN)
        t = tau * g if g <= 1.0 else tau + (1.0 - tau) * (g - 1.0)
        return [geo.bezier_sub(*parent, 0.0, t),
                geo.bezier_sub(*parent, t, 1.0)], True

    g = min(max(param_at_factor(cubics, factor), MARGIN), 2.0 - MARGIN)
    if abs(g - 1.0) < MARGIN:
        # Within a hair of where the point already is. Snapping there keeps
        # both segments exactly as they were, instead of fitting one of them
        # to a sliver of nothing plus its neighbour - which is also what makes
        # the slider give the curve back untouched at the value it opens with,
        # since that value has gone through a 32 bit float on the way.
        g = 1.0
    left = portion(cubics, 0.0, g)
    right = portion(cubics, g, 2.0)
    exact = len(left) == 1 and len(right) == 1
    return [left[0] if len(left) == 1 else fit_one_cubic(left),
            right[0] if len(right) == 1 else fit_one_cubic(right)], exact


# -----------------------------------------------------------------------------
# From a spline to its spans and back
# -----------------------------------------------------------------------------

def _segment(data, a, b):
    """The cubic of the segment from point `a` to point `b`."""
    pa, pb = data.points[a], data.points[b]
    return (pa.co, pa.hr, pb.hl, pb.co)


def neighbours(data, k):
    """(previous, next) point indices of `k`, None where there is no segment."""
    n = len(data.points)
    if data.cyclic:
        return (k - 1) % n, (k + 1) % n
    return (k - 1 if k > 0 else None), (k + 1 if k < n - 1 else None)


def corner_angle(data, k, prev, nxt):
    """Angle, in degrees, between the two tangents at a point of a span."""
    arriving = geo.normalized(geo.sub(data.points[k].co, data.points[k].hl))
    if arriving is None:
        arriving = geo.normalized(geo.sub(data.points[k].co, data.points[prev].co))
    leaving = geo.normalized(geo.sub(data.points[k].hr, data.points[k].co))
    if leaving is None:
        leaving = geo.normalized(geo.sub(data.points[nxt].co, data.points[k].co))
    if arriving is None or leaving is None:
        return 0.0
    return math.degrees(math.acos(max(-1.0, min(1.0, geo.dot(arriving, leaving)))))


def span_of(data, k):
    """(cubics of the span, previous index, next index) of point `k`.

    The span of an end point is its single segment, oriented so that it leaves
    the point: the factor then runs from the point to its neighbour.
    """
    prev, nxt = neighbours(data, k)
    if prev is not None and nxt is not None:
        return [_segment(data, prev, k), _segment(data, k, nxt)], prev, nxt
    if nxt is not None:                       # the first point of an open spline
        return [_segment(data, k, nxt)], None, nxt
    return [reversed_cubic(_segment(data, prev, k))], prev, None


def current_factor(data, k):
    """Where point `k` already sits in its span (0 to 1).

    An end point is at 0 of its own segment, so its slider opens closed: it can
    only be slid inwards, which shortens the curve.
    """
    cubics = span_of(data, k)[0]
    if len(cubics) == 1:
        return 0.0
    return factor_at_param(cubics, 1.0)


def _straight(cubic):
    return geo.is_straight_segment(*cubic)


def _freeze(point, side):
    """An Auto handle that Blender would recompute from the neighbours becomes
    Free where it is, so the segment on its far side keeps its shape."""
    if side == 'LEFT' and point.hlt == 'AUTO':
        point.hlt = 'FREE'
    if side == 'RIGHT' and point.hrt == 'AUTO':
        point.hrt = 'FREE'


def _apply(data, k, prev, nxt, pieces, factor=0.0):
    """Write the new cubics back into a copy of the spline. `factor` is the
    Position, which moves the outer handle of an end point."""
    out = data.copy()
    points = out.points
    moved = points[k]

    if prev is not None and nxt is not None:
        left, right = pieces
        before, after = points[prev], points[nxt]
        before.hr = left[1]
        moved.co, moved.hl, moved.hr = left[3], left[2], right[1]
        after.hl = right[2]
        # The outer handles of the neighbours do not move, but an Auto one
        # would be recomputed now that their neighbour has moved.
        _freeze(before, 'LEFT')
        _freeze(after, 'RIGHT')
        before.hrt = 'VECTOR' if _straight(left) else 'FREE'
        after.hlt = 'VECTOR' if _straight(right) else 'FREE'
        moved.hlt = 'VECTOR' if _straight(left) else 'ALIGNED'
        moved.hrt = 'VECTOR' if _straight(right) else 'ALIGNED'
        if moved.hlt != moved.hrt:
            # Aligned on one side only would be re-aimed at the other handle.
            moved.hlt = 'FREE' if moved.hlt == 'ALIGNED' else moved.hlt
            moved.hrt = 'FREE' if moved.hrt == 'ALIGNED' else moved.hrt
    else:
        piece = pieces[0]
        other = nxt if nxt is not None else prev
        neighbour = points[other]
        delta = geo.sub(piece[0], moved.co)
        if nxt is not None:                   # first point: the segment goes out
            moved.co, moved.hr = piece[0], piece[1]
            neighbour.hl = piece[2]
            neighbour.hlt = 'VECTOR' if _straight(piece) else 'FREE'
            _freeze(neighbour, 'RIGHT')
            moved.hl = geo.add(moved.hl, delta)
            moved.hrt = 'VECTOR' if _straight(piece) else 'FREE'
        else:                                 # last point: the segment comes in
            moved.co, moved.hl = piece[0], piece[1]
            neighbour.hr = piece[2]
            neighbour.hrt = 'VECTOR' if _straight(piece) else 'FREE'
            _freeze(neighbour, 'LEFT')
            moved.hr = geo.add(moved.hr, delta)
            moved.hlt = 'VECTOR' if _straight(piece) else 'FREE'
        # The outer handle of an end point belongs to no segment, so it does
        # not change the curve: as soon as the point slides it becomes the
        # mirror image of the inner handle (in line with it and as long), so
        # what is seen follows the curve. A Vector one is put back at a third
        # of the way (it is that mirror image already).
        outer = 'hlt' if nxt is not None else 'hrt'
        if getattr(moved, outer) == 'VECTOR':
            third = geo.lerp(moved.co, neighbour.co, -1.0 / 3.0)
            if nxt is not None:
                moved.hl = third
            else:
                moved.hr = third
        else:
            inner = moved.hr if nxt is not None else moved.hl
            handle = _outer_towards_mirror(moved.co, moved.hl if nxt is not None else moved.hr,
                                           inner, factor)
            if nxt is not None:
                moved.hl = handle
            else:
                moved.hr = handle
            if factor > 0.0 or getattr(moved, outer) == 'AUTO':
                setattr(moved, outer, 'FREE')
    return out


def _outer_towards_mirror(co, outer, inner, factor):
    """The outer handle of an end point: where it is at Position 0 (nothing
    has moved), and the mirror image of the inner handle through the point
    (in line with it, and as long) as soon as the point slides."""
    if factor <= 0.0:
        return outer
    return geo.sub(co, geo.sub(inner, co))


# -----------------------------------------------------------------------------
# The operator
# -----------------------------------------------------------------------------

def _selected(datas):
    """[(spline index, point index)] of the selected control points."""
    return [(i, k)
            for i, d in enumerate(datas)
            for k, p in enumerate(d.points)
            if p.select]


def _check(data, k):
    """Make sure point `k` can be slid, or raise Rejected."""
    if data.kind != 'BEZIER':
        raise Rejected(
            f"Slide Point works on Bezier curves only (this one is {data.kind}): on a "
            "Poly spline a slide would cut the corner instead of keeping the shape, "
            "and on a NURBS spline the control points are not on the curve")
    n = len(data.points)
    if n < 2:
        raise Rejected("the spline has a single point")
    prev, nxt = neighbours(data, k)
    if prev is not None and nxt is not None:
        if data.cyclic and n < 3:
            raise Rejected("a closed spline needs at least three points to slide one")
        angle = corner_angle(data, k, prev, nxt)
        if angle > CORNER_ANGLE:
            raise Rejected(
                f"its handles are not aligned (they turn {angle:.1f} degrees), so the "
                "point is a corner: no position of it can keep a kink that has to "
                "travel with it. Align its handles first, or slide a smooth point")


class ETR_OT_curve_toolkit_slide_point(bpy.types.Operator):
    """Slide the selected control point along its curve, keeping the shape as close as possible. Position (F9) measures where it sits between its neighbours. Bezier only"""
    bl_idname = "etr.curve_toolkit_slide_point"
    bl_label = "Slide Point"
    bl_options = {'REGISTER', 'UNDO'}

    factor: FloatProperty(
        name="Position",
        description=(
            "Where the point sits in its span, measured along the curve: 0 at "
            "the previous point and 1 at the next one (on an end point, 0 "
            "where it is now and 1 at its neighbour). With several points "
            "selected they are all moved to this same position"
        ),
        default=0.5,
        min=0.0,
        max=1.0,
        precision=4,
        subtype='FACTOR',
    )
    read_position: BoolProperty(
        name="Read the Position",
        description="Internal: start from where the point already sits",
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return context.mode == EDIT_MODE and has_active_curve(context)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "factor")

    def invoke(self, context, event):
        """Open the slider where the point already sits.

        The reading is done by execute(), inside the one scope it opens, so
        that the Edit Mode is not left and entered twice. Adjusting the slider
        afterwards re-runs execute() with the flag cleared, which is what makes
        every move start again from the curve as it was.
        """
        self.read_position = True
        return self.execute(context)

    def _plan(self, datas, picked):
        """Check the selection as a whole, or raise Rejected."""
        if not picked:
            raise Rejected("select the control point(s) to slide")
        for i, k in picked:
            _check(datas[i], k)
        # Two neighbouring points share a segment, so one would undo the work
        # of the other. Points two apart or more never touch the same handle.
        for a in range(len(picked)):
            for b in range(a + 1, len(picked)):
                (si, ki), (sj, kj) = picked[a], picked[b]
                if si != sj:
                    continue
                n = len(datas[si].points)
                near = abs(ki - kj) == 1 or (
                    datas[si].cyclic and n > 2 and {ki, kj} == {0, n - 1})
                if near:
                    raise Rejected(
                        "two of the selected points are neighbours: they share a "
                        "segment, so sliding both at once would undo the work of "
                        "one of them")

    def execute(self, context):
        moved = 0
        worst = 0.0
        exact = True
        with edit_scope(context) as objs:
            plans = []
            try:
                for obj in objs:
                    datas = sd.read_all(obj.data)
                    picked = _selected(datas)
                    if picked:
                        self._plan(datas, picked)
                        plans.append((obj, datas, picked))
            except Rejected as exc:
                self.report({'ERROR'}, f"Slide Point: {exc}")
                return {'CANCELLED'}
            if not plans:
                self.report({'WARNING'}, "Select the control point(s) to slide")
                return {'CANCELLED'}

            if self.read_position:
                _, datas, picked = plans[0]
                i, k = picked[0]
                self.factor = current_factor(datas[i], k)
                self.read_position = False

            for obj, datas, picked in plans:
                for i, k in picked:
                    data = datas[i]
                    cubics, prev, nxt = span_of(data, k)
                    length = chain_length(cubics)
                    if length < geo.EPS:
                        continue
                    pieces, was_exact = slide_chain(
                        cubics, self.factor, PARENT_TOLERANCE * max(length, 1.0))
                    exact = exact and was_exact
                    worst = max(worst, drift(pieces, cubics) / length)
                    datas[i] = _apply(data, k, prev, nxt, pieces, self.factor)
                    moved += 1
                sd.replace_splines(obj.data, datas)

        if not moved:
            self.report({'WARNING'}, "Nothing to slide")
            return {'CANCELLED'}

        if exact:
            note = "the shape is unchanged"
        else:
            note = f"the shape drifted {100.0 * worst:.3f}% of the span at most"
        self.report({'INFO'}, f"Slid {moved} point(s): {note}")
        return {'FINISHED'}


# -----------------------------------------------------------------------------

classes = (ETR_OT_curve_toolkit_slide_point,)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
