# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Cristobal Vila (etereaestudios.com)

"""Tests of the pure-Python 2D offset engine (no Blender needed):

    python test_offset.py <folder containing etr_curves_toolkit>
"""

import math
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]) / "etr_curves_toolkit"))

import curve_engine as E           # noqa: E402
import offset_engine as O          # noqa: E402

K = 4 / 3 * math.tan(math.pi / 8)
TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


# -----------------------------------------------------------------------------
# Shapes and measurements
# -----------------------------------------------------------------------------

def polygon(points):
    n = len(points)
    return [E.line_seg(points[i], points[(i + 1) % n]) for i in range(n)]


def square(half=1.0):
    return polygon([(-half, -half), (half, -half), (half, half), (-half, half)])


def circle(radius=1.0, cx=0.0, cy=0.0):
    segs = []
    for i in range(4):
        a0, a1 = i * math.pi / 2, (i + 1) * math.pi / 2
        p0 = (cx + radius * math.cos(a0), cy + radius * math.sin(a0))
        p1 = (cx + radius * math.cos(a1), cy + radius * math.sin(a1))
        t0 = (-math.sin(a0), math.cos(a0))
        t1 = (-math.sin(a1), math.cos(a1))
        segs.append(E.Seg(p0,
                          (p0[0] + t0[0] * K * radius, p0[1] + t0[1] * K * radius),
                          (p1[0] - t1[0] * K * radius, p1[1] - t1[1] * K * radius),
                          p1))
    return segs


def bbox(segs):
    xs, ys = [], []
    for s in segs:
        for i in range(17):
            p = s.pt(i / 16)
            xs.append(p[0])
            ys.append(p[1])
    return min(xs), min(ys), max(xs), max(ys)


def samples(segs, per_seg=12):
    out = []
    for s in segs:
        for i in range(per_seg):
            out.append(s.pt(i / per_seg))
        out.append(s.p1)
    return out


def distances(result_segs, original_segs, cyclic):
    pts = O._polyline(original_segs, steps=64)
    return [O._distance_to_polyline(p, pts, cyclic) for p in samples(result_segs)]


def self_intersections(segs, cyclic):
    tol = E.tolerances_for(E.segs_points(segs))
    return sum(len(v) for v in O._self_cuts(segs, cyclic, tol))


def is_closed(segs, tol=1e-9):
    return E._dist(segs[-1].p1, segs[0].p0) <= tol


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def near(a, b, eps=1e-9):
    return abs(a - b) <= eps


# -----------------------------------------------------------------------------
# Lines and corners
# -----------------------------------------------------------------------------

@test
def square_outwards_is_a_square():
    out = O.offset_path(square(1.0), True, 0.2)
    check(len(out) == 1, f"one result expected, got {len(out)}")
    segs, cyclic = out[0]
    check(cyclic, "the result must be closed")
    check(len(segs) == 4, f"a mitered square must keep 4 segments, got {len(segs)}")
    check(all(s.line for s in segs), "every side must still be a straight line")
    x0, y0, x1, y1 = bbox(segs)
    check(all(near(v, w, 1e-9) for v, w in zip((x0, y0, x1, y1), (-1.2, -1.2, 1.2, 1.2))),
          f"bbox {x0, y0, x1, y1} should be (-1.2, -1.2, 1.2, 1.2)")


@test
def square_inwards():
    segs, cyclic = O.offset_path(square(1.0), True, -0.2)[0]
    check(cyclic and len(segs) == 4, "4 closed segments expected")
    x0, y0, x1, y1 = bbox(segs)
    check(all(near(v, w, 1e-9) for v, w in zip((x0, y0, x1, y1), (-0.8, -0.8, 0.8, 0.8))),
          f"bbox {x0, y0, x1, y1} should be (-0.8, -0.8, 0.8, 0.8)")


@test
def direction_does_not_change_the_side():
    clockwise = [s.reversed() for s in reversed(square(1.0))]
    check(O.signed_area(clockwise) < 0.0, "the test shape must turn clockwise")
    segs, _ = O.offset_path(clockwise, True, 0.2)[0]
    x0, _, x1, _ = bbox(segs)
    check(near(x1 - x0, 2.4, 1e-9), f"a positive offset must grow it: width {x1 - x0}")


@test
def square_round_corners():
    segs, cyclic = O.offset_path(square(1.0), True, 0.25, corners='ROUND')[0]
    check(cyclic, "closed")
    check(len(segs) == 8, f"4 sides + 4 arcs expected, got {len(segs)}")
    ds = distances(segs, square(1.0), True)
    check(all(abs(d - 0.25) < 2e-3 for d in ds),
          f"a round offset stays at the distance: {min(ds)} .. {max(ds)}")


@test
def square_bevel_corners():
    segs, _ = O.offset_path(square(1.0), True, 0.25, corners='BEVEL')[0]
    check(len(segs) == 8, f"4 sides + 4 bevels expected, got {len(segs)}")
    check(all(s.line for s in segs), "a bevelled offset of a polygon is a polygon")


@test
def miter_limit_falls_back_to_bevel():
    spike = polygon([(0.0, 0.0), (10.0, 0.3), (0.0, 0.6)])     # a very thin tip
    tight = O.offset_path(spike, True, 0.3, corners='MITER', miter_limit=1.5)[0][0]
    loose = O.offset_path(spike, True, 0.3, corners='MITER', miter_limit=40.0)[0][0]
    check(len(tight) > len(loose),
          "a small miter limit must add a bevel where the spike is too long")
    pts = O._polyline(spike, 64)
    far = max(O._distance_to_polyline(p, pts, True) for p in samples(loose))
    near_tip = max(O._distance_to_polyline(p, pts, True) for p in samples(tight))
    check(far > 2.0, f"with a loose limit the miter reaches far: {far}")
    check(near_tip < 1.0, f"with a tight limit the tip is cut back: {near_tip}")


# -----------------------------------------------------------------------------
# Bezier curves
# -----------------------------------------------------------------------------

@test
def circle_outwards_keeps_four_segments():
    segs, cyclic = O.offset_path(circle(1.0), True, 0.5)[0]
    check(cyclic, "closed")
    check(len(segs) == 4, f"an offset circle should still have 4 segments, got {len(segs)}")
    radii = [math.hypot(*p) for p in samples(segs)]
    check(all(abs(r - 1.5) < 2e-3 for r in radii),
          f"radius should be 1.5: {min(radii)} .. {max(radii)}")


@test
def circle_inwards():
    segs, _ = O.offset_path(circle(1.0), True, -0.6)[0]
    radii = [math.hypot(*p) for p in samples(segs)]
    check(all(abs(r - 0.4) < 2e-3 for r in radii),
          f"radius should be 0.4: {min(radii)} .. {max(radii)}")


@test
def circle_shrunk_past_its_center_gives_nothing():
    check(O.offset_path(circle(1.0), True, -1.3) == [],
          "shrinking a circle more than its radius must give no curve")


@test
def offset_of_a_curve_is_still_a_curve():
    segs, _ = O.offset_path(circle(1.0), True, 0.5)[0]
    check(not any(s.line for s in segs), "the offset of a circle must stay curved")


# -----------------------------------------------------------------------------
# Open curves
# -----------------------------------------------------------------------------

@test
def open_polyline_both_sides():
    path = [E.line_seg((-1.0, 0.0), (0.0, 0.0)), E.line_seg((0.0, 0.0), (0.0, 1.0))]
    left = O.offset_path(path, False, 0.2)
    right = O.offset_path(path, False, -0.2)
    for name, out in (("left", left), ("right", right)):
        check(len(out) == 1, f"{name}: one path expected, got {len(out)}")
        check(not out[0][1], f"{name}: the result of an open curve must stay open")
    (ls, _), (rs, _) = left[0], right[0]
    check(ls[0].p0[1] > 0.0, "a positive offset goes to the left of the direction")
    check(rs[0].p0[1] < 0.0, "a negative offset goes to the right")
    for segs in (ls, rs):
        ds = distances(segs, path, False)
        check(all(d >= 0.2 * O.KEEP_TOLERANCE for d in ds),
              f"nothing may come closer than the distance: {min(ds)}")


@test
def open_curve_keeps_its_ends():
    path = [E.line_seg((0.0, 0.0), (2.0, 0.0))]
    segs, cyclic = O.offset_path(path, False, 0.3)[0]
    check(not cyclic, "open")
    check(near(segs[0].p0[1], 0.3) and near(segs[-1].p1[1], 0.3), "translated by 0.3")
    check(near(segs[0].p0[0], 0.0) and near(segs[-1].p1[0], 2.0),
          "an open offset is not capped: the ends stay at the ends")


# -----------------------------------------------------------------------------
# Overlaps
# -----------------------------------------------------------------------------

@test
def tight_concavity_loses_its_loop():
    # A narrow slot: offsetting outwards folds the two sides of the slot over
    # each other and the loop has to be removed.
    shape = polygon([
        (-2.0, -1.0), (2.0, -1.0), (2.0, 1.0), (0.3, 1.0),
        (0.3, -0.2), (-0.3, -0.2), (-0.3, 1.0), (-2.0, 1.0),
    ])
    raw = O.offset_path(shape, True, 0.4, clean=False)
    clean = O.offset_path(shape, True, 0.4, clean=True)
    check(self_intersections(raw[0][0], True) > 0, "the raw offset should fold over itself")
    total = 0
    for segs, cyclic in clean:
        total += self_intersections(segs, cyclic)
        ds = distances(segs, shape, True)
        check(all(d >= 0.4 * O.KEEP_TOLERANCE - 1e-9 for d in ds),
              f"a folded part survived at {min(ds)}")
    check(total == 0, f"the cleaned offset still crosses itself {total} times")


@test
def shrinking_can_split_a_curve_in_two():
    # A dumbbell: two wide ends joined by a thin waist. Shrunk enough, the
    # waist disappears and two separate curves are left.
    shape = polygon([
        (-3.0, -1.0), (-1.0, -1.0), (-1.0, -0.25), (1.0, -0.25), (1.0, -1.0),
        (3.0, -1.0), (3.0, 1.0), (1.0, 1.0), (1.0, 0.25), (-1.0, 0.25),
        (-1.0, 1.0), (-3.0, 1.0),
    ])
    out = O.offset_path(shape, True, -0.4)
    check(len(out) == 2, f"two separate curves expected, got {len(out)}")
    for segs, cyclic in out:
        check(cyclic, "both pieces must be closed")
        check(self_intersections(segs, True) == 0, "no piece may cross itself")


@test
def every_result_is_continuous():
    shapes = [
        (square(1.0), True, 0.2),
        (square(1.0), True, -0.3),
        (circle(1.0), True, 0.4),
        (polygon([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.6, 0.6)]), True, 0.15),
        (polygon([(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.6, 0.6)]), True, -0.15),
    ]
    for segs, cyclic, d in shapes:
        for corners in ('MITER', 'ROUND', 'BEVEL'):
            for result, closed in O.offset_path(segs, cyclic, d, corners=corners):
                for a, b in zip(result, result[1:]):
                    check(E._dist(a.p1, b.p0) < 1e-9,
                          f"{corners} {d}: a gap of {E._dist(a.p1, b.p0)} between segments")
                if closed:
                    check(is_closed(result), f"{corners} {d}: the loop does not close")


@test
def a_polygon_stays_a_polygon():
    hexagon = polygon([(math.cos(i * math.pi / 3), math.sin(i * math.pi / 3)) for i in range(6)])
    for d in (0.2, -0.2):
        segs, cyclic = O.offset_path(hexagon, True, d)[0]
        check(cyclic and len(segs) == 6, f"{d}: 6 closed sides expected, got {len(segs)}")
        check(all(s.line for s in segs), f"{d}: a mitered polygon must stay a polygon")


@test
def star_with_sharp_concave_corners():
    points = []
    for i in range(10):
        r = 1.0 if i % 2 == 0 else 0.45
        a = math.pi / 2 + i * math.pi / 5
        points.append((r * math.cos(a), r * math.sin(a)))
    star = polygon(points)
    for d in (0.12, -0.12):
        out = O.offset_path(star, True, d)
        check(out, f"{d}: nothing came out")
        for segs, cyclic in out:
            check(self_intersections(segs, cyclic) == 0, f"{d}: the result crosses itself")
            ds = distances(segs, star, True)
            check(all(x >= abs(d) * O.KEEP_TOLERANCE - 1e-6 for x in ds),
                  f"{d}: a part survived at {min(ds)}")


@test
def open_bezier_curve():
    # The two-point curve of Blender's Add > Curve > Bezier (an S with an
    # inflection), which the Primitive Curves button makes.
    path = [E.Seg((-1.0, 0.0), (-0.5, 0.5), (0.0, 0.0), (1.0, 0.0))]
    for d in (0.2, -0.2):
        out = O.offset_path(path, False, d)
        check(len(out) == 1 and not out[0][1], f"{d}: one open path expected")
        segs = out[0][0]
        check(not any(s.line for s in segs), f"{d}: the offset of a curve must stay curved")
        ds = distances(segs, path, False)
        check(all(abs(x - abs(d)) < 3e-3 for x in ds),
              f"{d}: distance should be {abs(d)}: {min(ds)} .. {max(ds)}")


@test
def rounded_rectangle_mixes_lines_and_curves():
    r, half = 0.4, 1.0
    k = K * r
    segs = []
    corners = [(half, half), (-half, half), (-half, -half), (half, -half)]
    for i, (cx, cy) in enumerate(corners):
        a0 = i * math.pi / 2
        sx, sy = (1 if cx > 0 else -1), (1 if cy > 0 else -1)
        # straight side then a quarter arc, built from the corner centers
        c = (cx - sx * r, cy - sy * r)
        p0 = (c[0] + r * math.cos(a0), c[1] + r * math.sin(a0))
        p1 = (c[0] + r * math.cos(a0 + math.pi / 2), c[1] + r * math.sin(a0 + math.pi / 2))
        t0 = (-math.sin(a0), math.cos(a0))
        t1 = (-math.sin(a0 + math.pi / 2), math.cos(a0 + math.pi / 2))
        arc = E.Seg(p0, (p0[0] + t0[0] * k, p0[1] + t0[1] * k),
                    (p1[0] - t1[0] * k, p1[1] - t1[1] * k), p1)
        segs.append(arc)
        nxt_c = (corners[(i + 1) % 4][0] - (1 if corners[(i + 1) % 4][0] > 0 else -1) * r,
                 corners[(i + 1) % 4][1] - (1 if corners[(i + 1) % 4][1] > 0 else -1) * r)
        a_next = ((i + 1) % 4) * math.pi / 2
        p_next = (nxt_c[0] + r * math.cos(a_next), nxt_c[1] + r * math.sin(a_next))
        segs.append(E.line_seg(p1, p_next))
    for d in (0.25, -0.25):
        out = O.offset_path(segs, True, d)
        check(len(out) == 1 and out[0][1], f"{d}: one closed path expected, got {len(out)}")
        result = out[0][0]
        check(any(s.line for s in result) and any(not s.line for s in result),
              f"{d}: lines and curves should both survive")
        ds = distances(result, segs, True)
        check(all(abs(x - abs(d)) < 4e-3 for x in ds),
              f"{d}: distance should be {abs(d)}: {min(ds)} .. {max(ds)}")


@test
def a_dense_curve_is_fast_enough():
    import time
    n = 180
    shape = polygon([(math.cos(2 * math.pi * i / n) * (1.0 + 0.15 * (i % 2)),
                      math.sin(2 * math.pi * i / n) * (1.0 + 0.15 * (i % 2))) for i in range(n)])
    start = time.time()
    out = O.offset_path(shape, True, 0.05)
    elapsed = time.time() - start
    check(out, "nothing came out")
    check(elapsed < 20.0, f"too slow: {elapsed:.1f} s for {n} segments")
    print(f"      ({n} segments offset in {elapsed:.2f} s)")


# -----------------------------------------------------------------------------

def main():
    failed = 0
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed += 1
            print(f"FAIL  {fn.__name__}: {exc}")
            if "-v" in sys.argv:
                traceback.print_exc()
        else:
            print(f"ok    {fn.__name__}")
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
