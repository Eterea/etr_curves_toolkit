# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""
2D engine of the Curve Booleans and Curve Splits (pure Python, no bpy).

Curves are lists of cubic Bezier segments in a common 2D plane. Straight
segments (Poly, or Bezier with Vector handles) are cubics flagged as lines.

  - intersect()        exact intersections between two segments: recursive
                       subdivision of their bounding boxes, then Newton's
                       method on the real curves. Lines are solved
                       analytically. Overlapping (coincident) stretches are
                       detected and reported by their end points.
  - inside_region()    exact even-odd point-in-region test (the horizontal ray
                       is intersected with the cubics themselves, not with a
                       polygonal approximation).
  - boolean()          union / intersection / difference of two regions. A
                       region is a list of closed loops (holes allowed). The
                       boundaries are cut at their crossings with de Casteljau
                       (the shape of every piece is exact), each piece is kept
                       or dropped by testing whether it lies inside the other
                       region, and the kept pieces are chained into loops.
  - split_intervals()  where each path is cut by the paths of other owners,
                       as parameter intervals. extract() builds the pieces.

All tolerances are relative to the size of the input (see Tolerances).
"""

import math


# -----------------------------------------------------------------------------
# Segments
# -----------------------------------------------------------------------------

class Seg:
    """A cubic Bezier segment in 2D.

    m0, m1: optional "meta" of the end points, used by the caller to restore
            the original point data (handle types, radius...). Each is a tuple
            (original point object, side) where side is 'R' when the segment
            leaves the original point through its right handle and 'L' through
            its left handle. Only set while the end is an untouched original
            point; points created by a cut have no meta.
    """

    __slots__ = ("p0", "h0", "h1", "p1", "line", "m0", "m1")

    def __init__(self, p0, h0, h1, p1, line=False, m0=None, m1=None):
        self.p0, self.h0, self.h1, self.p1 = p0, h0, h1, p1
        self.line = line
        self.m0, self.m1 = m0, m1

    def pt(self, t):
        u = 1.0 - t
        a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
        return (a * self.p0[0] + b * self.h0[0] + c * self.h1[0] + d * self.p1[0],
                a * self.p0[1] + b * self.h0[1] + c * self.h1[1] + d * self.p1[1])

    def d(self, t):
        u = 1.0 - t
        a, b, c = 3 * u * u, 6 * u * t, 3 * t * t
        return (a * (self.h0[0] - self.p0[0]) + b * (self.h1[0] - self.h0[0]) + c * (self.p1[0] - self.h1[0]),
                a * (self.h0[1] - self.p0[1]) + b * (self.h1[1] - self.h0[1]) + c * (self.p1[1] - self.h1[1]))

    def split(self, t):
        p0, h0, h1, p1 = self.p0, self.h0, self.h1, self.p1
        a, b, c = _lerp(p0, h0, t), _lerp(h0, h1, t), _lerp(h1, p1, t)
        d, e = _lerp(a, b, t), _lerp(b, c, t)
        m = _lerp(d, e, t)
        return (Seg(p0, a, d, m, self.line, self.m0, None),
                Seg(m, e, c, p1, self.line, None, self.m1))

    def sub(self, s, e):
        """Part between parameters s and e (keeps the metas of untouched ends)."""
        seg = self
        if e < 1.0:
            seg = seg.split(e)[0]
            s = s / e if e > 0.0 else 0.0
        if s > 0.0:
            seg = seg.split(s)[1]
        return seg

    def reversed(self):
        return Seg(self.p1, self.h1, self.h0, self.p0, self.line,
                   _flip_meta(self.m1), _flip_meta(self.m0))

    def bbox(self):
        xs = (self.p0[0], self.h0[0], self.h1[0], self.p1[0])
        ys = (self.p0[1], self.h0[1], self.h1[1], self.p1[1])
        return min(xs), min(ys), max(xs), max(ys)

    def flatness(self):
        """Largest distance of the handles to the chord."""
        cx, cy = self.p1[0] - self.p0[0], self.p1[1] - self.p0[1]
        n = math.hypot(cx, cy)
        if n < 1e-300:
            return max(_dist(self.h0, self.p0), _dist(self.h1, self.p0))
        return max(abs((h[0] - self.p0[0]) * cy - (h[1] - self.p0[1]) * cx) / n
                   for h in (self.h0, self.h1))


def _flip_meta(meta):
    if meta is None:
        return None
    return (meta[0], 'L' if meta[1] == 'R' else 'R')


def line_seg(a, b, m0=None, m1=None):
    """Straight segment with handles at thirds (what Blender's Vector handles do)."""
    return Seg(a, _lerp(a, b, 1 / 3), _lerp(a, b, 2 / 3), b, True, m0, m1)


def _lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


# -----------------------------------------------------------------------------
# Tolerances
# -----------------------------------------------------------------------------

class Tolerances:
    """All tolerances, derived from the size of the input."""

    def __init__(self, scale):
        scale = max(scale, 1e-6)
        self.scale = scale
        self.newton = 1e-10 * scale    # residual target of Newton's method
        self.accept = 1e-7 * scale     # an intersection is accepted below this
        self.join = 1e-6 * scale       # two points are the same point
        self.flat = 1e-3 * scale       # a sub-curve is flat enough to stop subdividing
        self.probe = 1e-5 * scale      # offset of the side probes


def tolerances_for(paths_points):
    xs, ys = [], []
    for p in paths_points:
        xs.append(p[0])
        ys.append(p[1])
    if not xs:
        return Tolerances(1.0)
    return Tolerances(math.hypot(max(xs) - min(xs), max(ys) - min(ys)))


def segs_points(segs):
    for s in segs:
        yield s.p0
        yield s.h0
        yield s.h1
        yield s.p1


# -----------------------------------------------------------------------------
# Intersections
# -----------------------------------------------------------------------------

def _boxes_overlap(a, b, pad):
    return not (a[2] + pad < b[0] or b[2] + pad < a[0] or a[3] + pad < b[1] or b[3] + pad < a[1])


def _newton(A, B, s, t, tol, iterations=30):
    """Refine A(s) == B(t). Returns (s, t, residual)."""
    for _ in range(iterations):
        pa, pb = A.pt(s), B.pt(t)
        fx, fy = pa[0] - pb[0], pa[1] - pb[1]
        if math.hypot(fx, fy) < tol.newton:
            break
        da, db = A.d(s), B.d(t)
        # J = [da, -db]
        det = da[0] * (-db[1]) - (-db[0]) * da[1]
        if abs(det) < 1e-300:
            break
        ds = (fx * (-db[1]) - (-db[0]) * fy) / det
        dt = (da[0] * fy - da[1] * fx) / det
        s = min(1.0, max(0.0, s - ds))
        t = min(1.0, max(0.0, t - dt))
    pa, pb = A.pt(s), B.pt(t)
    return s, t, _dist(pa, pb)


def _closest_param(seg, p, samples=24):
    """Parameter of the point of `seg` closest to p, and its distance."""
    best_t, best_d = 0.0, _dist(seg.p0, p)
    for i in range(1, samples + 1):
        t = i / samples
        dd = _dist(seg.pt(t), p)
        if dd < best_d:
            best_t, best_d = t, dd
    t = best_t
    for _ in range(20):
        q, dq = seg.pt(t), seg.d(t)
        rx, ry = q[0] - p[0], q[1] - p[1]
        g = rx * dq[0] + ry * dq[1]
        # second derivative by finite difference of the derivative
        h = 1e-6
        dq2 = seg.d(min(1.0, t + h))
        ddx, ddy = (dq2[0] - dq[0]) / h, (dq2[1] - dq[1]) / h
        gp = dq[0] * dq[0] + dq[1] * dq[1] + rx * ddx + ry * ddy
        if abs(gp) < 1e-300:
            break
        nt = min(1.0, max(0.0, t - g / gp))
        if abs(nt - t) < 1e-14:
            t = nt
            break
        t = nt
    return t, _dist(seg.pt(t), p)


def _line_line(A, B, tol):
    ax, ay = A.p1[0] - A.p0[0], A.p1[1] - A.p0[1]
    bx, by = B.p1[0] - B.p0[0], B.p1[1] - B.p0[1]
    den = ax * by - ay * bx
    la, lb = math.hypot(ax, ay), math.hypot(bx, by)
    if la < 1e-300 or lb < 1e-300:
        return []
    qx, qy = B.p0[0] - A.p0[0], B.p0[1] - A.p0[1]
    if abs(den) > 1e-12 * la * lb:
        s = (qx * by - qy * bx) / den
        t = (qx * ay - qy * ax) / den
        es, et = tol.join / la, tol.join / lb
        if -es <= s <= 1 + es and -et <= t <= 1 + et:
            return [(min(1.0, max(0.0, s)), min(1.0, max(0.0, t)))]
        return []
    # Parallel: overlapping only if collinear.
    if abs(qx * ay - qy * ax) / la > tol.join:
        return []
    return _overlap_hits(A, B, tol, line=True)


def _param_on_line(seg, p):
    ax, ay = seg.p1[0] - seg.p0[0], seg.p1[1] - seg.p0[1]
    l2 = ax * ax + ay * ay
    t = ((p[0] - seg.p0[0]) * ax + (p[1] - seg.p0[1]) * ay) / l2
    t = min(1.0, max(0.0, t))
    return t, _dist(seg.pt(t), p)


def _overlap_hits(A, B, tol, line=False):
    """End points of each segment that lie on the other one, as (s, t) pairs,
    or [] when there are fewer than two distinct ones."""
    closest = _param_on_line if line else _closest_param
    hits = []
    for p, which in ((A.p0, 'A0'), (A.p1, 'A1'), (B.p0, 'B0'), (B.p1, 'B1')):
        if which[0] == 'A':
            t, dd = closest(B, p)
            s = 0.0 if which == 'A0' else 1.0
        else:
            s, dd = closest(A, p)
            t = 0.0 if which == 'B0' else 1.0
        if dd <= tol.join:
            pt = A.pt(s)
            if all(_dist(pt, A.pt(h[0])) > tol.join for h in hits):
                hits.append((s, t))
    return hits if len(hits) >= 2 else []


def _overlapping(A, B, tol):
    """Hits if the two curves run on top of each other, else None."""
    hits = _overlap_hits(A, B, tol)
    if len(hits) < 2:
        return None
    hits.sort()
    # The middle of the shared stretch must also be on both curves.
    s_mid = 0.5 * (hits[0][0] + hits[1][0])
    _, dd = _closest_param(B, A.pt(s_mid))
    if dd > tol.join:
        return None
    return hits


def intersect(A, B, tol):
    """Intersections of two segments as a list of parameter pairs (s, t)."""
    if not _boxes_overlap(A.bbox(), B.bbox(), tol.join):
        return []
    if A.line and B.line:
        return _line_line(A, B, tol)
    ov = _overlapping(A, B, tol)
    if ov is not None:
        return ov

    candidates = []
    stack = [(A, 0.0, 1.0, B, 0.0, 1.0, 0)]
    while stack:
        a, a0, a1, b, b0, b1, depth = stack.pop()
        if not _boxes_overlap(a.bbox(), b.bbox(), tol.join):
            continue
        if (a.flatness() <= tol.flat and b.flatness() <= tol.flat) or depth >= 40:
            hit = _chord_hit(a, b)
            if hit is not None:
                candidates.append((a0 + (a1 - a0) * hit[0], b0 + (b1 - b0) * hit[1]))
            continue
        if len(candidates) > 400:
            break
        ba, bb = a.bbox(), b.bbox()
        if (ba[2] - ba[0]) + (ba[3] - ba[1]) >= (bb[2] - bb[0]) + (bb[3] - bb[1]):
            l, r = a.split(0.5)
            am = 0.5 * (a0 + a1)
            stack.append((l, a0, am, b, b0, b1, depth + 1))
            stack.append((r, am, a1, b, b0, b1, depth + 1))
        else:
            l, r = b.split(0.5)
            bm = 0.5 * (b0 + b1)
            stack.append((a, a0, a1, l, b0, bm, depth + 1))
            stack.append((a, a0, a1, r, bm, b1, depth + 1))

    found = []
    for s, t in candidates:
        s, t, res = _newton(A, B, s, t, tol)
        if res > tol.accept:
            continue
        p = A.pt(s)
        if any(_dist(p, A.pt(fs)) <= tol.join for fs, _ in found):
            continue
        found.append((s, t))
    return found


def _chord_hit(a, b, extend=0.05):
    """Crossing of the chords of two (flat) sub-curves, in their parameters."""
    rx, ry = a.p1[0] - a.p0[0], a.p1[1] - a.p0[1]
    sx, sy = b.p1[0] - b.p0[0], b.p1[1] - b.p0[1]
    den = rx * sy - ry * sx
    if abs(den) < 1e-300:
        return None
    qx, qy = b.p0[0] - a.p0[0], b.p0[1] - a.p0[1]
    s = (qx * sy - qy * sx) / den
    t = (qx * ry - qy * rx) / den
    if -extend <= s <= 1 + extend and -extend <= t <= 1 + extend:
        return min(1.0, max(0.0, s)), min(1.0, max(0.0, t))
    return None


# -----------------------------------------------------------------------------
# Point in region (exact, even-odd)
# -----------------------------------------------------------------------------

def _monotone_y_params(seg):
    """Parameters splitting a cubic into pieces monotone in y."""
    y0, y1, y2, y3 = seg.p0[1], seg.h0[1], seg.h1[1], seg.p1[1]
    # dy/dt = 3[(y1-y0)(1-t)^2 + 2(y2-y1)(1-t)t + (y3-y2)t^2] = a t^2 + b t + c
    p, q, r = y1 - y0, y2 - y1, y3 - y2
    a = p - 2 * q + r
    b = 2 * (q - p)
    c = p
    roots = []
    if abs(a) < 1e-300:
        if abs(b) > 1e-300:
            roots.append(-c / b)
    else:
        disc = b * b - 4 * a * c
        if disc >= 0:
            sq = math.sqrt(disc)
            roots += [(-b - sq) / (2 * a), (-b + sq) / (2 * a)]
    return [0.0] + sorted(t for t in roots if 0.0 < t < 1.0) + [1.0]


def _crossings_right(seg, px, py):
    """Number of times the ray from (px, py) towards +x crosses the segment.

    Half-open rule on every monotone piece, so a ray through a vertex is
    counted once."""
    count = 0
    ts = _monotone_y_params(seg)
    for ta, tb in zip(ts, ts[1:]):
        ya, yb = seg.pt(ta)[1], seg.pt(tb)[1]
        if not ((ya <= py < yb) or (yb <= py < ya)):
            continue
        lo, hi = ta, tb
        increasing = yb > ya
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            ym = seg.pt(mid)[1]
            if (ym < py) == increasing:
                lo = mid
            else:
                hi = mid
        if seg.pt(0.5 * (lo + hi))[0] > px:
            count += 1
    return count


def inside_region(p, loops):
    """Even-odd test: is point p inside the region bounded by the loops?"""
    px, py = p
    count = 0
    for loop in loops:
        for seg in loop:
            b = seg.bbox()
            if b[2] < px or py < b[1] or py > b[3]:
                continue
            count += _crossings_right(seg, px, py)
    return count % 2 == 1


# -----------------------------------------------------------------------------
# Booleans
# -----------------------------------------------------------------------------

def _left_probe(seg, t, eps):
    p, d = seg.pt(t), seg.d(t)
    n = math.hypot(d[0], d[1])
    if n < 1e-300:
        p2 = seg.pt(min(1.0, t + 1e-4))
        d = (p2[0] - p[0], p2[1] - p[1])
        n = math.hypot(d[0], d[1]) or 1.0
    return (p[0] - d[1] / n * eps, p[1] + d[0] / n * eps)


def _loop_reversed(loop):
    return [s.reversed() for s in reversed(loop)]


def orient_region(loops, tol):
    """Orient every loop so that the region's interior is on its left."""
    out = []
    for loop in loops:
        seg = max(loop, key=lambda s: _dist(s.p0, s.p1) + _dist(s.p0, s.h0) + _dist(s.h1, s.p1))
        probe = _left_probe(seg, 0.5, tol.probe)
        out.append(loop if inside_region(probe, loops) else _loop_reversed(loop))
    return out


def _cut_loops(loops, cuts, tol):
    """Pieces of the loops, cut at the given parameters.

    cuts: {(loop index, segment index): [t, ...]}.
    """
    pieces = []
    for li, loop in enumerate(loops):
        for si, seg in enumerate(loop):
            ts = sorted(set(cuts.get((li, si), ())))
            bounds = [0.0]
            for t in ts:
                p = seg.pt(t)
                if _dist(p, seg.pt(bounds[-1])) > tol.join and _dist(p, seg.p1) > tol.join:
                    bounds.append(t)
            bounds.append(1.0)
            for a, b in zip(bounds, bounds[1:]):
                pieces.append(seg.sub(a, b))
    return pieces


def _intersect_regions(A, B, tol):
    cuts_a, cuts_b = {}, {}
    boxes_b = [[s.bbox() for s in loop] for loop in B]
    for ai, la in enumerate(A):
        for aj, sa in enumerate(la):
            box_a = sa.bbox()
            for bi, lb in enumerate(B):
                for bj, sb in enumerate(lb):
                    if not _boxes_overlap(box_a, boxes_b[bi][bj], tol.join):
                        continue
                    for s, t in intersect(sa, sb, tol):
                        cuts_a.setdefault((ai, aj), []).append(s)
                        cuts_b.setdefault((bi, bj), []).append(t)
    return cuts_a, cuts_b


def _same_curve(p, q, tol):
    """+1 if pieces p and q are the same curve in the same direction, -1 if
    in opposite directions, 0 otherwise."""
    if _dist(p.p0, q.p0) <= tol.join and _dist(p.p1, q.p1) <= tol.join:
        direction = 1
    elif _dist(p.p0, q.p1) <= tol.join and _dist(p.p1, q.p0) <= tol.join:
        direction = -1
    else:
        return 0
    for t in (0.25, 0.5, 0.75):
        if _closest_param(q, p.pt(t))[1] > tol.join * 10:
            return 0
    return direction


def boolean(region_a, region_b, op, tol):
    """Boolean of two regions (lists of closed loops of Seg).

    op: 'UNION', 'INTERSECTION' or 'DIFFERENCE' (a minus b).
    Returns the resulting loops (interior on the left of each loop).
    """
    A = orient_region(region_a, tol)
    B = orient_region(region_b, tol)
    cuts_a, cuts_b = _intersect_regions(A, B, tol)
    pa = _cut_loops(A, cuts_a, tol)
    pb = _cut_loops(B, cuts_b, tol)

    # Pieces shared by both boundaries.
    shared_a, shared_b = {}, set()
    for i, p in enumerate(pa):
        for j, q in enumerate(pb):
            if j in shared_b:
                continue
            d = _same_curve(p, q, tol)
            if d:
                shared_a[i] = d
                shared_b.add(j)
                break

    keep = []
    for i, p in enumerate(pa):
        if i in shared_a:
            same = shared_a[i] == 1
            if (op in ('UNION', 'INTERSECTION') and same) or (op == 'DIFFERENCE' and not same):
                keep.append(p)
            continue
        inside = inside_region(p.pt(0.5), B)
        if (op == 'INTERSECTION') == inside:
            keep.append(p)
    for j, q in enumerate(pb):
        if j in shared_b:
            continue
        inside = inside_region(q.pt(0.5), A)
        if op == 'UNION' and not inside:
            keep.append(q)
        elif op == 'INTERSECTION' and inside:
            keep.append(q)
        elif op == 'DIFFERENCE' and inside:
            keep.append(q.reversed())
    return chain_loops(keep, tol)


def chain_loops(pieces, tol):
    """Chain pieces end to start into closed loops. Pieces that cannot be
    closed are dropped."""
    remaining = list(pieces)
    loops = []
    while remaining:
        loop = [remaining.pop(0)]
        start = loop[0].p0
        closed = _dist(loop[-1].p1, start) <= tol.join * 10
        while not closed:
            end = loop[-1].p1
            best, best_d = None, tol.join * 10
            for k, p in enumerate(remaining):
                dd = _dist(p.p0, end)
                if dd <= best_d:
                    best, best_d = k, dd
            if best is None:
                break
            loop.append(remaining.pop(best))
            closed = _dist(loop[-1].p1, start) <= tol.join * 10
        if closed:
            loops.append(_weld(loop))
    return loops


def _weld(loop):
    """Make consecutive end points coincide exactly (moving the handle that
    belongs to the moved point with it)."""
    out = []
    for i, s in enumerate(loop):
        start = loop[i - 1].p1
        dx, dy = start[0] - s.p0[0], start[1] - s.p0[1]
        out.append(Seg(start, (s.h0[0] + dx, s.h0[1] + dy), s.h1, s.p1, s.line, s.m0, s.m1))
    return out


def union_all(regions, tol):
    result = regions[0]
    for region in regions[1:]:
        result = boolean(result, region, 'UNION', tol)
    return result


# -----------------------------------------------------------------------------
# Splits
# -----------------------------------------------------------------------------

class Path:
    """An open or closed curve: segments, cyclic flag and owner id."""

    def __init__(self, segs, cyclic, owner):
        self.segs = segs
        self.cyclic = cyclic
        self.owner = owner


def split_intervals(paths, targets, tol):
    """Where each target path is cut by the paths of other owners.

    Returns {path index: list of (g0, g1)} where g is a global parameter
    (segment index + local parameter). For a closed path, g1 may exceed the
    number of segments (the piece wraps around). Paths without cuts are
    returned with None.
    """
    boxes = [[s.bbox() for s in p.segs] for p in paths]
    result = {}
    for i in targets:
        path = paths[i]
        n = len(path.segs)
        cuts = []
        for k, seg in enumerate(path.segs):
            box = boxes[i][k]
            for j, other in enumerate(paths):
                if other.owner == path.owner:
                    continue
                for m, oseg in enumerate(other.segs):
                    if not _boxes_overlap(box, boxes[j][m], tol.join):
                        continue
                    for s, _ in intersect(seg, oseg, tol):
                        cuts.append(_global_param(path, k, s, tol))
        cuts = [g for g in cuts if g is not None]
        cuts = _dedupe_params(path, sorted(cuts), tol)
        if not cuts:
            result[i] = None
            continue
        if path.cyclic:
            result[i] = [(g, cuts[(m + 1) % len(cuts)] + (n if m + 1 == len(cuts) else 0))
                         for m, g in enumerate(cuts)]
        else:
            bounds = [0.0] + cuts + [float(n)]
            result[i] = list(zip(bounds, bounds[1:]))
    return result


def _global_param(path, k, s, tol):
    """Global parameter of a cut, snapped to the vertices. Cuts on the end
    points of an open path are ignored (there is nothing to cut there)."""
    n = len(path.segs)
    seg = path.segs[k]
    p = seg.pt(s)
    if _dist(p, seg.p1) <= tol.join:
        k, s = k + 1, 0.0
    elif _dist(p, seg.p0) <= tol.join:
        s = 0.0
    if path.cyclic:
        return float(k % n) + s
    if (k == 0 and s == 0.0) or k >= n:
        return None
    return float(k) + s


def _dedupe_params(path, gs, tol):
    out = []
    for g in gs:
        if out and _dist(point_at(path, g), point_at(path, out[-1])) <= tol.join:
            continue
        out.append(g)
    if path.cyclic and len(out) > 1 and _dist(point_at(path, out[0]), point_at(path, out[-1])) <= tol.join:
        out.pop()
    return out


def point_at(path, g):
    n = len(path.segs)
    if not path.cyclic and g >= n:
        return path.segs[-1].p1
    k = int(math.floor(g))
    return path.segs[k % n].pt(g - k)


def extract(segs, cyclic, g0, g1):
    """Segments of a path between global parameters g0 and g1 (g1 > g0; for
    a closed path g1 may exceed the number of segments)."""
    n = len(segs)
    out = []
    k = int(math.floor(g0))
    while k < g1 - 1e-12:
        s = max(g0 - k, 0.0)
        e = min(g1 - k, 1.0)
        if e - s > 1e-12:
            out.append(segs[k % n].sub(s, e) if cyclic else segs[k].sub(s, e))
        k += 1
    return out
