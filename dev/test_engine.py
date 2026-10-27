# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""Tests of the pure-Python 2D engine (no Blender needed):

    python test_engine.py <folder containing etr_curve_toolkit>
"""

import importlib.util
import math
import sys
import traceback
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "curve_engine", Path(sys.argv[1]) / "etr_curve_toolkit" / "curve_engine.py")
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

K = 4 / 3 * math.tan(math.pi / 8)
TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def rect(x0, y0, x1, y1):
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    return [E.line_seg(pts[i], pts[(i + 1) % 4]) for i in range(4)]


def circle(cx, cy, r, start=0.0):
    segs = []
    for i in range(4):
        a0 = start + i * math.pi / 2
        a1 = a0 + math.pi / 2
        p0 = (cx + r * math.cos(a0), cy + r * math.sin(a0))
        p1 = (cx + r * math.cos(a1), cy + r * math.sin(a1))
        h0 = (p0[0] - K * r * math.sin(a0), p0[1] + K * r * math.cos(a0))
        h1 = (p1[0] + K * r * math.sin(a1), p1[1] - K * r * math.cos(a1))
        segs.append(E.Seg(p0, h0, h1, p1))
    return segs


def area(loops, steps=200):
    """Signed area (shoelace on a dense sampling); positive = CCW."""
    total = 0.0
    for loop in loops:
        pts = [s.pt(i / steps) for s in loop for i in range(steps)]
        total += 0.5 * sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1]))
    return total


def tol_for(*shapes):
    return E.tolerances_for([p for sh in shapes for p in E.segs_points(sh)])


def closed_ok(loops):
    for loop in loops:
        for a, b in zip(loop, loop[1:] + loop[:1]):
            assert a.p1 == b.p0, "loop not welded"


SQ = rect(0, 0, 2, 2)
CI = circle(2, 2, 1)          # centered on the square's corner
A_SQ, A_CI = 4.0, math.pi


@test
def intersections_line_circle():
    tol = tol_for(SQ, CI)
    hits = []
    for a in SQ:
        for b in CI:
            hits += [a.pt(s) for s, t in E.intersect(a, b, tol)]
    hits = sorted({(round(x, 9), round(y, 9)) for x, y in hits})
    assert hits == [(1.0, 2.0), (2.0, 1.0)], hits


@test
def intersections_curve_curve_exact():
    c1, c2 = circle(0, 0, 1), circle(1, 0, 1)
    tol = tol_for(c1, c2)
    pts = []
    for a in c1:
        for b in c2:
            for s, t in E.intersect(a, b, tol):
                pa, pb = a.pt(s), b.pt(t)
                assert math.dist(pa, pb) < 1e-9
                pts.append(pa)
    # Cubic circles are not exact circles (radial error ~2.7e-4).
    pts = sorted({(round(x, 6), round(y, 6)) for x, y in pts})
    assert len(pts) == 2 and all(abs(x - 0.5) < 1e-9 and abs(abs(y) - 0.866) < 1e-3 for x, y in pts), pts


@test
def booleans_square_circle():
    tol = tol_for(SQ, CI)
    quarter = math.pi / 4
    u = E.boolean([SQ], [CI], 'UNION', tol)
    i = E.boolean([SQ], [CI], 'INTERSECTION', tol)
    d = E.boolean([SQ], [CI], 'DIFFERENCE', tol)
    for loops in (u, i, d):
        closed_ok(loops)
        assert len(loops) == 1
    assert abs(area(u) - (A_SQ + A_CI - quarter)) < 2e-3, area(u)
    assert abs(area(i) - quarter) < 2e-3, area(i)
    assert abs(area(d) - (A_SQ - quarter)) < 2e-3, area(d)
    # Union vertices: 3 square corners, the 2 crossings (which are also circle
    # points) and 2 circle points.
    assert len(u[0]) == 7, len(u[0])


@test
def difference_hole_and_contained():
    big, small = rect(0, 0, 4, 4), circle(2, 2, 1)
    tol = tol_for(big, small)
    d = E.boolean([big], [small], 'DIFFERENCE', tol)
    assert len(d) == 2 and abs(area(d) - (16 - math.pi)) < 2e-3, (len(d), area(d))
    e = E.boolean([small], [big], 'DIFFERENCE', tol)
    assert e == []
    u = E.boolean([big], [small], 'UNION', tol)
    assert len(u) == 1 and abs(area(u) - 16) < 1e-6
    i = E.boolean([big], [small], 'INTERSECTION', tol)
    assert len(i) == 1 and abs(area(i) - math.pi) < 2e-3


@test
def disjoint():
    a, b = rect(0, 0, 1, 1), rect(3, 0, 4, 1)
    tol = tol_for(a, b)
    assert len(E.boolean([a], [b], 'UNION', tol)) == 2
    assert E.boolean([a], [b], 'INTERSECTION', tol) == []
    d = E.boolean([a], [b], 'DIFFERENCE', tol)
    assert len(d) == 1 and abs(area(d) - 1) < 1e-9


@test
def shared_edges():
    a, b = rect(0, 0, 2, 2), rect(2, 0, 4, 2)          # touching along x = 2
    tol = tol_for(a, b)
    u = E.boolean([a], [b], 'UNION', tol)
    assert len(u) == 1 and abs(area(u) - 8) < 1e-9, (len(u), area(u))
    c = rect(1, 0, 3, 2)                                 # overlapping, collinear bottom/top edges
    tol = tol_for(a, c)
    u = E.boolean([a], [c], 'UNION', tol)
    assert len(u) == 1 and abs(area(u) - 6) < 1e-9, (len(u), area(u))
    i = E.boolean([a], [c], 'INTERSECTION', tol)
    assert len(i) == 1 and abs(area(i) - 2) < 1e-9
    d = E.boolean([a], [c], 'DIFFERENCE', tol)
    assert len(d) == 1 and abs(area(d) - 2) < 1e-9
    same = E.boolean([a], [rect(0, 0, 2, 2)], 'UNION', tol)
    assert len(same) == 1 and abs(area(same) - 4) < 1e-9


@test
def identical_circles_and_shared_arc():
    a, b = circle(0, 0, 1), circle(0, 0, 1, start=0.0)
    tol = tol_for(a, b)
    u = E.boolean([a], [b], 'UNION', tol)
    assert len(u) == 1 and abs(area(u) - math.pi) < 2e-3
    assert E.boolean([a], [b], 'DIFFERENCE', tol) == []
    # A half disc sharing the circle's arc.
    half = circle(0, 0, 1)[:2] + [E.line_seg((-1, 0), (1, 0))]
    i = E.boolean([a], [half], 'INTERSECTION', tol)
    assert len(i) == 1 and abs(area(i) - math.pi / 2) < 2e-3, area(i)


@test
def union_many_and_orientation():
    shapes = [circle(x, 0, 1) for x in (0, 1.2, 2.4)] + [rect(-0.5, -0.2, 3, 0.2)]
    tol = tol_for(*shapes)
    u = E.union_all([[s] for s in shapes], tol)
    assert len(u) == 1
    # Clockwise input works the same.
    cw = [s.reversed() for s in reversed(SQ)]
    tol = tol_for(cw, CI)
    i = E.boolean([cw], [CI], 'INTERSECTION', tol)
    assert abs(area(i) - math.pi / 4) < 2e-3


@test
def union_creating_a_hole():
    # A "C" shape closed by a bar leaves a hole.
    c = [rect(0, 0, 3, 1), rect(0, 2, 3, 3), rect(0, 0, 1, 3)]
    bar = rect(2, 0, 3, 3)
    tol = tol_for(*c, bar)
    u = E.union_all([[s] for s in c + [bar]], tol)
    assert len(u) == 2 and abs(area(u) - 8) < 1e-9, (len(u), area(u))


@test
def inside_exact_near_boundary():
    tol = tol_for(CI)
    assert E.inside_region((2 + 0.999999, 2), [CI])
    assert not E.inside_region((2 + 1.000001, 2), [CI])
    assert E.inside_region((2, 2), [CI]) and not E.inside_region((5, 5), [CI])


@test
def splits_open_and_closed():
    line = E.Path([E.line_seg((-1, 1.5), (4, 1.5))], False, 'L')
    sq = E.Path(rect(0, 0, 2, 2), True, 'S')
    ci = E.Path(circle(2, 2, 1), True, 'C')
    paths = [line, sq, ci]
    tol = E.tolerances_for([p for P in paths for p in E.segs_points(P.segs)])
    iv = E.split_intervals(paths, [0, 1, 2], tol)
    assert len(iv[0]) == 5, iv[0]          # the line crosses the square twice and the circle twice
    assert len(iv[1]) == 4, iv[1]          # square: 2 by the line + 2 by the circle
    assert len(iv[2]) == 4, iv[2]          # circle: 2 by the square + 2 by the line
    for i, path in enumerate(paths):
        pieces = [E.extract(path.segs, path.cyclic, a, b) for a, b in iv[i]]
        assert all(pieces)
        # Consecutive pieces meet.
        for p, q in zip(pieces, pieces[1:]):
            assert math.dist(p[-1].p1, q[0].p0) < 1e-9


@test
def splits_without_cuts_and_touching_ends():
    a = E.Path([E.line_seg((0, 0), (1, 0))], False, 'A')
    b = E.Path([E.line_seg((1, 0), (1, 1))], False, 'B')     # touches a's end only
    c = E.Path(rect(5, 5, 6, 6), True, 'C')
    paths = [a, b, c]
    tol = E.tolerances_for([p for P in paths for p in E.segs_points(P.segs)])
    iv = E.split_intervals(paths, [0, 1, 2], tol)
    assert iv == {0: None, 1: None, 2: None}, iv


def star(cx, cy, r_out, r_in, n, rot):
    pts = []
    for i in range(2 * n):
        r = r_out if i % 2 == 0 else r_in
        a = rot + i * math.pi / n
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return [E.line_seg(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]


def blob(cx, cy, rng):
    """A closed smooth-ish Bezier shape with random handles."""
    n = rng.randint(3, 6)
    anchors = []
    for i in range(n):
        a = 2 * math.pi * i / n + rng.uniform(-0.3, 0.3)
        r = rng.uniform(0.6, 1.4)
        anchors.append((cx + r * math.cos(a), cy + r * math.sin(a), a))
    segs = []
    for i in range(n):
        x0, y0, a0 = anchors[i]
        x1, y1, a1 = anchors[(i + 1) % n]
        k0, k1 = rng.uniform(0.2, 0.6), rng.uniform(0.2, 0.6)
        segs.append(E.Seg((x0, y0), (x0 - k0 * math.sin(a0), y0 + k0 * math.cos(a0)),
                          (x1 + k1 * math.sin(a1), y1 - k1 * math.cos(a1)), (x1, y1)))
    return segs


@test
def random_shapes_area_identities():
    import random
    rng = random.Random(7)
    for it in range(40):
        if it % 2:
            a = star(0, 0, 1.2, 0.5, rng.randint(4, 7), rng.uniform(0, 1))
            b = star(rng.uniform(-0.8, 0.8), rng.uniform(-0.8, 0.8), 1.1, 0.6, rng.randint(3, 6), rng.uniform(0, 1))
        else:
            a = blob(0, 0, rng)
            b = blob(rng.uniform(-0.8, 0.8), rng.uniform(-0.8, 0.8), rng)
        tol = tol_for(a, b)
        A, B = abs(area([a])), abs(area([b]))
        u = E.boolean([a], [b], 'UNION', tol)
        i = E.boolean([a], [b], 'INTERSECTION', tol)
        d = E.boolean([a], [b], 'DIFFERENCE', tol)
        for loops in (u, i, d):
            closed_ok(loops)
        U, I, D = area(u), area(i), area(d)
        assert abs(U + I - (A + B)) < 1e-3 * (A + B), (it, U, I, A, B)
        assert abs(D - (A - I)) < 1e-3 * (A + B), (it, D, A, I)


def main():
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print("PASS ", fn.__name__)
        except Exception:
            failed += 1
            print("FAIL ", fn.__name__)
            traceback.print_exc()
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)


main()
