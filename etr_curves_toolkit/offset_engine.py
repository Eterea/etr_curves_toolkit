# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
2D offset engine of the Curve Toolkit (pure Python, no bpy).

offset_path() takes a path (the cubic Bezier segments of curve_engine, with
straight segments flagged as lines) and gives back the parallel path at a
signed distance, as a list of (segments, cyclic) - one closed curve can fall
apart into several when it is shrunk, and an open one too.

How it works:

  1. Every segment is offset on its own. A line is translated (exact). A curve
     is first cut where the offset would have a cusp (1 + distance * curvature
     = 0) and every piece is approximated by a cubic whose ends and tangents
     are the exact ones and whose handles are solved so that it also passes
     through the exact offset of its midpoint. The error is measured and the
     piece is halved until it is below the tolerance, so Bezier curves stay
     Bezier instead of becoming polylines.
  2. The pieces are stitched together at the corners. Where the corner opens a
     gap the join is a Miter (the two sides prolonged until they meet, with a
     limit), a Round (an arc of radius = distance) or a Bevel. Where the corner
     closes, the two sides are trimmed at their crossing.
  3. The result is cut at all of its self-intersections and the parts that are
     closer to the original curve than the distance are dropped, which removes
     the loops that an offset makes on tight concavities. What is left is
     chained back into closed loops and open paths.

close_both_sides() is the other entry point: it takes the two offsets of an
open path, one to each side, and closes them into a single loop with a
half-turn at each end (the Both Sides + Join Both with Arcs of the panel).

Conventions: the offset of a closed curve is outwards for a positive distance
and inwards for a negative one, whichever way the curve turns. On an open
curve a positive distance goes to the left of its direction.
"""

import math

try:
    from . import curve_engine as eng
except ImportError:                               # loaded directly by the tests
    import curve_engine as eng

MAX_DEPTH = 6               # a segment is halved at most 2^6 = 64 times
FIT_TOLERANCE = 5e-4        # error of the approximation, relative to the size
KEEP_TOLERANCE = 0.98       # a part closer than distance * this is dropped
CORNER_SEARCH = 4           # segments looked at on each side of a closing corner
ARC_STEP = math.pi / 2      # longest arc of a Round join in one cubic


# -----------------------------------------------------------------------------
# Small 2D helpers
# -----------------------------------------------------------------------------

def _unit(v):
    n = math.hypot(v[0], v[1])
    if n < 1e-300:
        return None
    return (v[0] / n, v[1] / n)


def _left(t):
    """Normal of a unit tangent, 90 degrees to its left."""
    return (-t[1], t[0])


def _move(p, n, d):
    return (p[0] + n[0] * d, p[1] + n[1] * d)


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _tangent(seg, t):
    """Unit tangent, also where the derivative vanishes (handle on the point)."""
    u = _unit(seg.d(t))
    if u is not None:
        return u
    for step in (1e-5, 1e-4, 1e-3, 1e-2, 0.1):
        tt = min(1.0, max(0.0, t + (step if t < 0.5 else -step)))
        u = _unit(seg.d(tt))
        if u is not None:
            return u
    return _unit((seg.p1[0] - seg.p0[0], seg.p1[1] - seg.p0[1])) or (1.0, 0.0)


def _second_derivative(seg, t):
    u = 1.0 - t
    return tuple(
        6.0 * u * (seg.h1[i] - 2.0 * seg.h0[i] + seg.p0[i])
        + 6.0 * t * (seg.p1[i] - 2.0 * seg.h1[i] + seg.h0[i])
        for i in (0, 1)
    )


def _curvature(seg, t):
    dx, dy = seg.d(t)
    ddx, ddy = _second_derivative(seg, t)
    den = (dx * dx + dy * dy) ** 1.5
    if den < 1e-300:
        return 0.0
    return (dx * ddy - dy * ddx) / den


def _offset_point(seg, t, d):
    return _move(seg.pt(t), _left(_tangent(seg, t)), d)


def signed_area(segs):
    """Signed area of a closed path (positive when it turns counter-clockwise),
    from a polyline through the segments."""
    pts = []
    for s in segs:
        for i in range(8):
            pts.append(s.pt(i / 8.0))
    total = 0.0
    for a, b in zip(pts, pts[1:] + pts[:1]):
        total += a[0] * b[1] - b[0] * a[1]
    return 0.5 * total


# -----------------------------------------------------------------------------
# Offset of one segment
# -----------------------------------------------------------------------------

def _offset_line(seg, d):
    n = _left(_tangent(seg, 0.5))
    return eng.Seg(_move(seg.p0, n, d), _move(seg.h0, n, d),
                   _move(seg.h1, n, d), _move(seg.p1, n, d),
                   True, seg.m0, seg.m1)


def _fit(seg, d):
    """One cubic through the exact offset of both ends and of the midpoint."""
    t0, t1 = _tangent(seg, 0.0), _tangent(seg, 1.0)
    q0 = _move(seg.pt(0.0), _left(t0), d)
    q1 = _move(seg.pt(1.0), _left(t1), d)
    mid = _offset_point(seg, 0.5, d)

    # B(0.5) = (q0 + 3 h0 + 3 h1 + q1) / 8  with  h0 = q0 + a t0, h1 = q1 - b t1
    rx = (8.0 * mid[0] - 4.0 * q0[0] - 4.0 * q1[0]) / 3.0
    ry = (8.0 * mid[1] - 4.0 * q0[1] - 4.0 * q1[1]) / 3.0
    det = -_cross(t0, t1)
    a = b = None
    if abs(det) > 1e-9:
        a = (-rx * t1[1] + t1[0] * ry) / det
        b = (t0[0] * ry - rx * t0[1]) / det
    if (a is None or not math.isfinite(a) or not math.isfinite(b)
            or a <= 0.0 or b <= 0.0):
        # Tangents almost parallel (a nearly straight segment): keep the
        # proportions of the original handles.
        chord = eng._dist(seg.p0, seg.p1)
        scale = (eng._dist(q0, q1) / chord) if chord > 1e-300 else 1.0
        a = eng._dist(seg.p0, seg.h0) * scale
        b = eng._dist(seg.p1, seg.h1) * scale
    return eng.Seg(q0, _move(q0, t0, a), _move(q1, t1, -b), q1,
                   False, seg.m0, seg.m1)


def _fit_error(seg, candidate, d):
    worst = 0.0
    for i in range(1, 8):
        target = _offset_point(seg, i / 8.0, d)
        _, distance = eng._closest_param(candidate, target, samples=12)
        if distance > worst:
            worst = distance
    return worst


def _offset_curve(seg, d, fit_tolerance, depth=0):
    candidate = _fit(seg, d)
    if depth >= MAX_DEPTH or _fit_error(seg, candidate, d) <= fit_tolerance:
        return [candidate]
    left, right = seg.split(0.5)
    return (_offset_curve(left, d, fit_tolerance, depth + 1)
            + _offset_curve(right, d, fit_tolerance, depth + 1))


def _cusp_params(seg, d, samples=24):
    """Parameters where the offset degenerates: 1 + d * curvature = 0."""
    def f(t):
        return 1.0 + d * _curvature(seg, t)

    values = [(i / samples, f(i / samples)) for i in range(samples + 1)]
    out = []
    for (ta, fa), (tb, fb) in zip(values, values[1:]):
        if fa == 0.0:
            out.append(ta)
        elif fa * fb < 0.0:
            lo, hi = ta, tb
            for _ in range(50):
                mid = 0.5 * (lo + hi)
                if fa * f(mid) <= 0.0:
                    hi = mid
                else:
                    lo = mid
            out.append(0.5 * (lo + hi))
    return [t for t in out if 1e-6 < t < 1.0 - 1e-6]


def _offset_segment(seg, d, fit_tolerance):
    if seg.line:
        return [_offset_line(seg, d)]
    bounds = [0.0] + _cusp_params(seg, d) + [1.0]
    out = []
    for s, e in zip(bounds, bounds[1:]):
        if e - s > 1e-9:
            out += _offset_curve(seg.sub(s, e), d, fit_tolerance)
    return out


# -----------------------------------------------------------------------------
# Corners
# -----------------------------------------------------------------------------

def _ray_crossing(p, u, q, v):
    """Where the ray p + s u (s >= 0) meets the ray q + w v (w <= 0)."""
    den = _cross(u, v)
    if abs(den) < 1e-12:
        return None
    s = _cross((q[0] - p[0], q[1] - p[1]), v) / den
    if s < 0.0:
        return None
    return _move(p, u, s)


def _arc(center, start, end, radius, tol):
    """Cubic arcs around `center`, from `start` to `end`, the short way."""
    a0 = math.atan2(start[1] - center[1], start[0] - center[0])
    a1 = math.atan2(end[1] - center[1], end[0] - center[0])
    sweep = (a1 - a0) % (2.0 * math.pi)
    if sweep > math.pi:
        sweep -= 2.0 * math.pi
    if abs(sweep) < 1e-9 or radius <= tol.join:
        return [eng.line_seg(start, end)]
    steps = max(1, int(math.ceil(abs(sweep) / ARC_STEP)))
    step = sweep / steps
    k = 4.0 / 3.0 * math.tan(step / 4.0)
    out = []
    point = start
    for i in range(steps):
        b0, b1 = a0 + step * i, a0 + step * (i + 1)
        nxt = (center[0] + radius * math.cos(b1), center[1] + radius * math.sin(b1))
        t0 = (-math.sin(b0), math.cos(b0))
        t1 = (-math.sin(b1), math.cos(b1))
        out.append(eng.Seg(point, _move(point, t0, k * radius),
                           _move(nxt, t1, -k * radius), nxt))
        point = nxt
    return out


def _bevel(q_in, q_out, corner):
    """A straight join and the smallest distance it legitimately has from the
    corner it cuts: unlike the offset itself, a bevel does come closer than the
    offset distance, so it needs its own limit for the cleaning pass."""
    middle = (0.5 * (q_in[0] + q_out[0]), 0.5 * (q_in[1] + q_out[1]))
    return [eng.line_seg(q_in, q_out)], eng._dist(middle, corner) * KEEP_TOLERANCE


def _open_join(before, after, corner, t_in, t_out, d, corners, miter_limit, tol):
    """Segments bridging a corner where the offset opens a gap, and the limit
    of the cleaning pass for them.

    A Miter between two straight sides prolongs them to the miter point instead
    of adding segments, so the offset of a rectangle is again a rectangle with
    four points. `before` and `after` are modified in place for that.
    """
    q_in, q_out = before[-1].p1, after[0].p0
    limit = abs(d) * KEEP_TOLERANCE
    if corners == 'ROUND':
        return _arc(corner, q_in, q_out, abs(d), tol), limit
    if corners == 'MITER':
        point = _ray_crossing(q_in, t_in, q_out, t_out)
        if point is not None and eng._dist(point, corner) <= miter_limit * abs(d):
            middle = []
            if before[-1].line:
                before[-1] = eng.line_seg(before[-1].p0, point,
                                          before[-1].m0, before[-1].m1)
            else:
                middle.append(eng.line_seg(q_in, point))
            if after[0].line:
                after[0] = eng.line_seg(point, after[0].p1,
                                        after[0].m0, after[0].m1)
            else:
                middle.append(eng.line_seg(point, q_out))
            return middle, limit
    return _bevel(q_in, q_out, corner)


def _trim_closing(before, after, tol):
    """Trim the end of `before` and the start of `after` at their crossing.

    Both lists are modified in place. True when a crossing was found.
    """
    for ia in range(len(before) - 1, max(-1, len(before) - 1 - CORNER_SEARCH), -1):
        for ib in range(min(CORNER_SEARCH, len(after))):
            hits = eng.intersect(before[ia], after[ib], tol)
            if not hits:
                continue
            # The crossing closest to the corner: latest on `before`.
            s, t = max(hits, key=lambda st: st[0])
            if s < 1e-9 and ia == len(before) - 1:
                continue
            del before[ia + 1:]
            if s < 1.0 - 1e-9:
                before[ia] = before[ia].sub(0.0, s)
            del after[:ib]
            if t > 1e-9:
                after[0] = after[0].sub(t, 1.0)
            return True
    return False


# -----------------------------------------------------------------------------
# Naive offset (segments + corners, overlaps not removed yet)
# -----------------------------------------------------------------------------

def _naive_offset(segs, cyclic, d, corners, miter_limit, tol, fit_tolerance):
    groups = [_offset_segment(s, d, fit_tolerance) for s in segs]
    n = len(segs)
    last = n if cyclic else n - 1
    limit = abs(d) * KEEP_TOLERANCE
    bridges = {}
    for i in range(last):
        j = (i + 1) % n
        before, after = groups[i], groups[j]
        if not before or not after:
            continue
        if eng._dist(before[-1].p1, after[0].p0) <= tol.join:
            continue                                   # smooth point, no corner
        t_in = _tangent(segs[i], 1.0)
        t_out = _tangent(segs[j], 0.0)
        if d * _cross(t_in, t_out) < 0.0:              # the corner opens a gap
            bridges[i] = _open_join(before, after, segs[j].p0, t_in, t_out,
                                    d, corners, miter_limit, tol)
        elif not _trim_closing(before, after, tol):    # it closes: trim, or bevel
            bridges[i] = _bevel(before[-1].p1, after[0].p0, segs[j].p0)

    out = []
    for i in range(n):
        out += [(s, limit) for s in groups[i]]
        if i in bridges:
            pieces, bridge_limit = bridges[i]
            out += [(s, bridge_limit) for s in pieces]
    return out


# -----------------------------------------------------------------------------
# Removing the parts that fold over the original curve
# -----------------------------------------------------------------------------

def _polyline(segs, steps=12):
    pts = []
    for s in segs:
        if s.line:
            pts.append(s.p0)
        else:
            for i in range(steps):
                pts.append(s.pt(i / steps))
    if segs:
        pts.append(segs[-1].p1)
    return pts


def _distance_to_polyline(p, pts, cyclic):
    best = float("inf")
    pairs = zip(pts, pts[1:] + pts[:1]) if cyclic else zip(pts, pts[1:])
    for a, b in pairs:
        vx, vy = b[0] - a[0], b[1] - a[1]
        den = vx * vx + vy * vy
        if den < 1e-300:
            t = 0.0
        else:
            t = ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / den
            t = min(1.0, max(0.0, t))
        dd = math.hypot(p[0] - (a[0] + vx * t), p[1] - (a[1] + vy * t))
        if dd < best:
            best = dd
    return best


def _self_cuts(segs, cyclic, tol):
    """Local parameters where the path crosses itself, per segment."""
    n = len(segs)
    cuts = [[] for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            neighbours = (j == i + 1) or (cyclic and i == 0 and j == n - 1)
            for s, t in eng.intersect(segs[i], segs[j], tol):
                if neighbours:
                    shared = segs[i].p1 if j == i + 1 else segs[i].p0
                    if eng._dist(segs[i].pt(s), shared) <= tol.join * 10.0:
                        continue
                cuts[i].append(s)
                cuts[j].append(t)
    return cuts


def _cut_into_segments(pairs, cyclic, tol):
    """The path cut at its self-intersections, as (segment, limit) pairs."""
    segs = [s for s, _ in pairs]
    cuts = _self_cuts(segs, cyclic, tol)
    if not any(cuts):
        return list(pairs)
    out = []
    for (seg, limit), ss in zip(pairs, cuts):
        bounds = [0.0]
        for s in sorted(ss):
            if s - bounds[-1] > 1e-9 and s < 1.0 - 1e-9:
                bounds.append(s)
        bounds.append(1.0)
        for a, b in zip(bounds, bounds[1:]):
            if b - a > 1e-12:
                out.append((seg.sub(a, b), limit))
    return out


def _drop_duplicates(pieces, tol):
    """Drop pieces that lie on top of another one.

    Two parts of the offset can run over each other (two walls of a slot, for
    instance), and both are at the offset distance from their own side of the
    original curve, so the test above keeps both. Only one is needed.
    """
    out = []
    for piece, limit in pieces:
        mid = piece.pt(0.5)
        for other, _ in out:
            if eng._dist(mid, other.pt(0.5)) > tol.join:
                continue
            same = (eng._dist(piece.p0, other.p0) <= tol.join
                    and eng._dist(piece.p1, other.p1) <= tol.join)
            flipped = (eng._dist(piece.p0, other.p1) <= tol.join
                       and eng._dist(piece.p1, other.p0) <= tol.join)
            if same or flipped:
                break
        else:
            out.append((piece, limit))
    return out


def _mergeable(a, b, tol):
    """True when two straight segments meeting at a point that no original
    control point owns are the same straight line."""
    if not (a.line and b.line and a.m1 is None and b.m0 is None):
        return False
    if eng._dist(a.p1, b.p0) > tol.join:
        return False
    u = _unit((a.p1[0] - a.p0[0], a.p1[1] - a.p0[1]))
    v = _unit((b.p1[0] - b.p0[0], b.p1[1] - b.p0[1]))
    if u is None or v is None:
        return True
    return abs(_cross(u, v)) < 1e-9 and (u[0] * v[0] + u[1] * v[1]) > 0.0


def _merge_collinear(segs, cyclic, tol):
    """Join the straight segments that the cuts left in the middle of a line,
    so the result does not carry points that say nothing about the shape."""
    out = []
    for seg in segs:
        if out and _mergeable(out[-1], seg, tol):
            out[-1] = eng.line_seg(out[-1].p0, seg.p1, out[-1].m0, seg.m1)
        else:
            out.append(seg)
    if cyclic and len(out) > 2 and _mergeable(out[-1], out[0], tol):
        merged = eng.line_seg(out[-1].p0, out[0].p1, out[-1].m0, out[0].m1)
        out = [merged] + out[1:-1]
    return out


def _chain(pieces, tol):
    """Chain pieces end to start. Returns a list of (segments, cyclic)."""
    remaining = list(pieces)
    reach = tol.join * 10.0
    paths = []
    while remaining:
        chain = [remaining.pop(0)]
        while True:                                   # forward
            if eng._dist(chain[-1].p1, chain[0].p0) <= reach:
                break
            end = chain[-1].p1
            best, best_d = None, reach
            for k, piece in enumerate(remaining):
                dd = eng._dist(piece.p0, end)
                if dd <= best_d:
                    best, best_d = k, dd
            if best is None:
                break
            chain.append(remaining.pop(best))
        while True:                                   # backward
            if eng._dist(chain[-1].p1, chain[0].p0) <= reach:
                break
            start = chain[0].p0
            best, best_d = None, reach
            for k, piece in enumerate(remaining):
                dd = eng._dist(piece.p1, start)
                if dd <= best_d:
                    best, best_d = k, dd
            if best is None:
                break
            chain.insert(0, remaining.pop(best))
        closed = len(chain) > 1 and eng._dist(chain[-1].p1, chain[0].p0) <= reach
        paths.append((eng._weld(chain) if closed else chain, closed))
    return paths


# -----------------------------------------------------------------------------
# Public entry point
# -----------------------------------------------------------------------------

def offset_path(segs, cyclic, distance, corners='MITER', miter_limit=4.0,
                clean=True, tol=None):
    """Parallel path of a 2D path, as a list of (segments, cyclic).

    distance:    signed. Outwards / inwards on a closed path (whichever way it
                 turns), left / right of the direction on an open one.
    corners:     'MITER', 'ROUND' or 'BEVEL', for the corners that open a gap.
    miter_limit: a miter longer than miter_limit * |distance| becomes a bevel.
    clean:       remove the parts that fold over the original curve.
    """
    if not segs or abs(distance) < 1e-12:
        return []
    if tol is None:
        tol = eng.tolerances_for(eng.segs_points(segs))

    # The left normal points inwards on a counter-clockwise closed path, so the
    # sign is flipped there to make a positive distance go outwards.
    d = distance
    if cyclic and signed_area(segs) > 0.0:
        d = -distance

    fit_tolerance = FIT_TOLERANCE * tol.scale
    raw = _naive_offset(segs, cyclic, d, corners, miter_limit, tol, fit_tolerance)
    raw = [(s, lim) for s, lim in raw
           if eng._dist(s.p0, s.p1) > tol.join or not s.line]
    if not raw:
        return []
    if not clean:
        plain = [s for s, _ in raw]
        return [(eng._weld(plain) if cyclic else plain, cyclic)]

    pieces = _cut_into_segments(raw, cyclic, tol)
    original = _polyline(segs)
    kept = []
    for piece, limit in pieces:
        if eng._dist(piece.p0, piece.p1) <= tol.join and piece.flatness() <= tol.join:
            continue
        if _distance_to_polyline(piece.pt(0.5), original, cyclic) >= limit - tol.join:
            kept.append((piece, limit))
    kept = _drop_duplicates(kept, tol)
    if not kept:
        return []
    return [(_merge_collinear(path, closed, tol), closed)
            for path, closed in _chain([p for p, _ in kept], tol)]


# -----------------------------------------------------------------------------
# Both Sides: closing the two parallels with a half-turn at each end
# -----------------------------------------------------------------------------

def _half_turn(center, start, end, outwards, radius, tol):
    """The 180 degree arc around `center`, from `start` to `end`, bulging away
    from the curve in the direction `outwards`.

    Two quarters, so the arc needs a single control point of its own between
    its two ends: one cubic per quarter is accurate to 0.03% of the radius,
    while a single cubic for the whole half turn would be off by a few percent.
    A half turn is also the one sweep _arc() cannot resolve on its own, since
    it goes "the short way" and both ways are equally short here, which is why
    the point it has to pass through is handed to it as two quarters.
    """
    through = _move(center, outwards, radius)
    return (_arc(center, start, through, radius, tol)
            + _arc(center, through, end, radius, tol))


def ends_of(segs):
    """(point, outwards unit tangent) at the start and at the end of an open
    path. "Outwards" points away from the path at each end."""
    t0 = _tangent(segs[0], 0.0)
    t1 = _tangent(segs[-1], 1.0)
    return (segs[0].p0, (-t0[0], -t0[1])), (segs[-1].p1, t1)


def close_both_sides(segs, plus, minus, distance, tol):
    """One closed path from the two offsets of an open path, with a half-turn
    closing each pair of ends, or None when it cannot be built.

    segs:         the original open path.
    plus, minus:  what offset_path() gave for +distance and -distance.
    distance:     positive.

    It is only possible when each side came out as a single open piece whose
    ends are still the exact offsets of the ends of the original: the cleaning
    pass can cut an offset into pieces or eat its ends away when the distance
    is larger than a concavity of the curve, and then there is nothing for the
    half-turns to close.
    """
    if len(plus) != 1 or len(minus) != 1:
        return None
    (side_a, a_closed), (side_b, b_closed) = plus[0], minus[0]
    if a_closed or b_closed or not side_a or not side_b:
        return None

    (p0, out0), (p1, out1) = ends_of(segs)
    # The left normal at each end, which is the direction offset_path() moved
    # the ends of the +distance side in (and the other way for -distance).
    n0 = _left((-out0[0], -out0[1]))
    n1 = _left(out1)
    expected = (
        (side_a[0].p0, _move(p0, n0, distance)),
        (side_a[-1].p1, _move(p1, n1, distance)),
        (side_b[0].p0, _move(p0, n0, -distance)),
        (side_b[-1].p1, _move(p1, n1, -distance)),
    )
    for found, want in expected:
        if eng._dist(found, want) > tol.join * 10.0:
            return None

    # Round the loop: one side forward, the half-turn at the far end, the other
    # side backwards, and the half-turn at the near end.
    loop = (
        list(side_a)
        + _half_turn(p1, side_a[-1].p1, side_b[-1].p1, out1, distance, tol)
        + [s.reversed() for s in reversed(side_b)]
        + _half_turn(p0, side_b[0].p0, side_a[0].p0, out0, distance, tol)
    )
    return eng._weld(loop)
