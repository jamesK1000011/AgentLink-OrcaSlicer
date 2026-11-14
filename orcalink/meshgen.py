# SPDX-License-Identifier: LGPL-2.1-or-later
# Triangle meshes in plain Python, for the mesh work a slicer's window does
# without a CAD kernel: primitives, cutting a closed mesh with planes and
# closing the cut (outlines with holes triangulated by ear clipping),
# separate pieces, mirror, volume and area, picking triangles by direction or
# place. A list of triangles is [[(x, y, z), (x, y, z), (x, y, z)], …].

import math

# ---- primitives ---------------------------------------------------------------------------


def box(sx, sy, sz, at=(0.0, 0.0, 0.0)):
    v = [(0, 0, 0), (sx, 0, 0), (sx, sy, 0), (0, sy, 0), (0, 0, sz), (sx, 0, sz), (sx, sy, sz), (0, sy, sz)]
    v = [(x + at[0], y + at[1], z + at[2]) for x, y, z in v]
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return [[v[a], v[b], v[c]] for a, b, c in f]


def _revolve(profile, segments=64):
    """A solid of revolution about Z from a profile [(r, z), …] running
    bottom to top; r 0 at an end closes it there."""
    out = []
    ring = [(math.cos(2 * math.pi * k / segments), math.sin(2 * math.pi * k / segments)) for k in range(segments)]
    for (r0, z0), (r1, z1) in zip(profile, profile[1:]):
        for k in range(segments):
            c0, s0 = ring[k]
            c1, s1 = ring[(k + 1) % segments]
            a, b = (r0 * c0, r0 * s0, z0), (r0 * c1, r0 * s1, z0)
            c, d = (r1 * c0, r1 * s0, z1), (r1 * c1, r1 * s1, z1)
            if r0 > 1e-12:
                out.append([a, b, d] if r1 > 1e-12 else [a, b, c])
            if r1 > 1e-12:
                out.append([a, d, c] if r0 > 1e-12 else [a, d, c])
    return out


def cylinder(d, h, segments=64):
    r = d / 2
    return _revolve([(0, 0), (r, 0), (r, h), (0, h)], segments)


def cone(d, h, segments=64):
    return _revolve([(0, 0), (d / 2, 0), (0, h)], segments)


def sphere(d, segments=48):
    r = d / 2
    n = segments // 2
    prof = [(r * math.sin(math.pi * i / n), r - r * math.cos(math.pi * i / n)) for i in range(n + 1)]
    prof[0], prof[-1] = (0.0, 0.0), (0.0, 2 * r)
    return _revolve(prof, segments)


def torus(d, tube, segments=64, sides=24):
    """Outer diameter d, tube diameter tube."""
    R, r = d / 2 - tube / 2, tube / 2
    out = []

    def p(u, v):
        return ((R + r * math.cos(v)) * math.cos(u), (R + r * math.cos(v)) * math.sin(u), r + r * math.sin(v))

    for i in range(segments):
        u0, u1 = 2 * math.pi * i / segments, 2 * math.pi * (i + 1) / segments
        for j in range(sides):
            v0, v1 = 2 * math.pi * j / sides, 2 * math.pi * (j + 1) / sides
            a, b, c, e = p(u0, v0), p(u1, v0), p(u1, v1), p(u0, v1)
            out += [[a, b, c], [a, c, e]]
    return out


def primitive(kind, size):
    d = size if isinstance(size, (list, tuple)) else [size] * 3
    d = list(d) + [d[-1]] * (3 - len(d))
    makers = {"cube": lambda: box(*d), "cylinder": lambda: cylinder(d[0], d[2]), "sphere": lambda: sphere(d[0]),
              "cone": lambda: cone(d[0], d[2]), "disc": lambda: cylinder(d[0], d[2] if d[2] != d[0] else 2), "torus": lambda: torus(d[0], d[2] if d[2] != d[0] else d[0] / 4)}
    if kind not in makers:
        raise ValueError(f"primitive: {', '.join(makers)}")
    return makers[kind]()


# ---- measures -----------------------------------------------------------------------------


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def normal(t):
    n = _cross(_sub(t[1], t[0]), _sub(t[2], t[0]))
    ln = math.sqrt(sum(x * x for x in n))
    return (n[0] / ln, n[1] / ln, n[2] / ln) if ln > 0 else (0.0, 0.0, 0.0), ln / 2


def volume(tris):
    return sum(sum(a * b for a, b in zip(t[0], _cross(t[1], t[2]))) for t in tris) / 6.0


def area(tris):
    return sum(normal(t)[1] for t in tris)


def bbox(tris):
    pts = [p for t in tris for p in t]
    xs, ys, zs = zip(*pts)
    return [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]


class Shape:
    """Volume, Area and BoundBox of a mesh, as printstrength reads a body."""

    def __init__(self, tris):
        b = bbox(tris)

        class BB:
            XLength, YLength, ZLength = b[3] - b[0], b[4] - b[1], b[5] - b[2]

        self.Volume, self.Area, self.BoundBox = abs(volume(tris)), area(tris), BB()


# ---- picking triangles --------------------------------------------------------------------


def pick(tris, where):
    """Which triangles a selection names: normal [x, y, z] with within
    degrees (default 20) — faces looking that way; box [[x0, y0, z0], [x1,
    y1, z1]] — centres inside; below / above z — centres under / over a
    height. Several given: all must hold."""
    out = []
    nrm = where.get("normal")
    if nrm:
        ln = math.sqrt(sum(x * x for x in nrm)) or 1
        nrm = [x / ln for x in nrm]
        cosw = math.cos(math.radians(float(where.get("within", 20))))
    bx = where.get("box")
    for t in tris:
        c = [sum(p[k] for p in t) / 3 for k in range(3)]
        ok = True
        if nrm:
            n, _ = normal(t)
            ok = sum(a * b for a, b in zip(n, nrm)) >= cosw
        if ok and bx:
            ok = all(bx[0][k] <= c[k] <= bx[1][k] for k in range(3))
        if ok and where.get("below") is not None:
            ok = c[2] <= float(where["below"])
        if ok and where.get("above") is not None:
            ok = c[2] >= float(where["above"])
        out.append(ok)
    return out


# ---- pieces, mirror -----------------------------------------------------------------------


def pieces(tris, tol=1e-5):
    """The separate pieces of a mesh (triangles sharing a corner join)."""
    key = lambda p: (round(p[0] / tol), round(p[1] / tol), round(p[2] / tol))
    parent = list(range(len(tris)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    seen = {}
    for i, t in enumerate(tris):
        for p in t:
            k = key(p)
            if k in seen:
                a, b = root(i), root(seen[k])
                if a != b:
                    parent[a] = b
            else:
                seen[k] = i
    groups = {}
    for i in range(len(tris)):
        groups.setdefault(root(i), []).append(tris[i])
    return sorted(groups.values(), key=len, reverse=True)


def mirror(tris, axis):
    k = "xyz".index(axis)
    b = bbox(tris)
    c = (b[k] + b[k + 3]) / 2

    def m(p):
        q = list(p)
        q[k] = 2 * c - q[k]
        return tuple(q)

    return [[m(t[0]), m(t[2]), m(t[1])] for t in tris]  # winding flipped: normals stay out


# ---- cutting and closing --------------------------------------------------------------------


def _area2(loop):
    return sum(loop[i][0] * loop[(i + 1) % len(loop)][1] - loop[(i + 1) % len(loop)][0] * loop[i][1] for i in range(len(loop))) / 2


def _inside(p, loop):
    x, y, c = p[0], p[1], False
    for i in range(len(loop)):
        (x0, y0), (x1, y1) = loop[i][:2], loop[i - 1][:2]
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            c = not c
    return c


def _segments_cross(a, b, c, d):
    def o(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return (v > 1e-12) - (v < -1e-12)

    return o(a, b, c) * o(a, b, d) < 0 and o(c, d, a) * o(c, d, b) < 0


def _bridge(outer, hole):
    """One polygon from an outline and a hole inside it: a slit from the
    hole's rightmost point to an outline point it can see."""
    hi = max(range(len(hole)), key=lambda i: hole[i][0])
    h = hole[hi]
    cands = sorted(range(len(outer)), key=lambda i: (outer[i][0] - h[0]) ** 2 + (outer[i][1] - h[1]) ** 2)
    edges = [(outer[i], outer[(i + 1) % len(outer)]) for i in range(len(outer))] + [(hole[i], hole[(i + 1) % len(hole)]) for i in range(len(hole))]
    oi = cands[0]
    for i in cands:
        o = outer[i]
        if not any(_segments_cross(h, o, a, b) for a, b in edges if a is not o and b is not o and a is not h and b is not h):
            oi = i
            break
    hole_seq = hole[hi:] + hole[:hi] + [hole[hi]]
    return outer[:oi + 1] + hole_seq + outer[oi:]


def _ear_clip(poly):
    """Triangles of a simple polygon (counter-clockwise, 2D points)."""
    idx = list(range(len(poly)))
    out = []
    guard = 0
    while len(idx) > 3 and guard < 10 * len(poly) + 100:
        guard += 1
        n = len(idx)
        for k in range(n):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % n]
            a, b, c = poly[i0], poly[i1], poly[i2]
            cr = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            if cr <= 1e-14:
                continue
            ear = True
            for j in idx:
                if j in (i0, i1, i2):
                    continue
                p = poly[j]
                if p == a or p == b or p == c:
                    continue
                d1 = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
                d2 = (c[0] - b[0]) * (p[1] - b[1]) - (c[1] - b[1]) * (p[0] - b[0])
                d3 = (a[0] - c[0]) * (p[1] - c[1]) - (a[1] - c[1]) * (p[0] - c[0])
                if d1 >= 0 and d2 >= 0 and d3 >= 0:
                    ear = False
                    break
            if ear:
                out.append((i0, i1, i2))
                idx.pop(k)
                break
        else:
            # Nothing convex left (collinear runs): drop the flattest corner.
            idx.pop(0)
    if len(idx) == 3:
        out.append(tuple(idx))
    return out


def cap(loops):
    """Triangles (2D) filling closed outlines, holes kept: even-odd
    nesting, each hole bridged into its outline, then ear clipping."""
    loops = [lp for lp in loops if len(lp) >= 3 and abs(_area2(lp)) > 1e-12]
    depth = [sum(1 for j, o in enumerate(loops) if j != i and _inside(lp[0], o)) for i, lp in enumerate(loops)]
    tris = []
    for i, lp in enumerate(loops):
        if depth[i] % 2:
            continue
        outer = lp if _area2(lp) > 0 else lp[::-1]
        holes = [loops[j] for j in range(len(loops)) if depth[j] == depth[i] + 1 and _inside(loops[j][0], lp)]
        poly = list(outer)
        for h in sorted(holes, key=lambda h: -max(p[0] for p in h)):
            poly = _bridge(poly, h if _area2(h) < 0 else h[::-1])
        tris += [(poly[a], poly[b], poly[c]) for a, b, c in _ear_clip(poly)]
    return tris


def _chain(segs, tol=1e-5):
    key = lambda p: (round(p[0] / tol), round(p[1] / tol))
    nxt = {}
    for a, b in segs:
        nxt.setdefault(key(a), []).append(b)
    loops, used = [], set()
    for a, b in segs:
        if (key(a), key(b)) in used:
            continue
        loop, cur = [a], b
        used.add((key(a), key(b)))
        while key(cur) != key(a) and len(loop) < 1000000:
            loop.append(cur)
            cand = [x for x in nxt.get(key(cur), []) if (key(cur), key(x)) not in used]
            if not cand:
                break
            used.add((key(cur), key(cand[0])))
            cur = cand[0]
        if len(loop) >= 3:
            loops.append(loop)
    return loops


def slab(tris, lo, hi, capper=None):
    """A closed mesh cut to the heights lo..hi and closed again: triangles
    clipped by the two planes, each cut's outlines filled. capper(loops,
    z) may fill them instead (a CAD kernel's flat faces)."""

    def clip(poly, z, keep_above):
        out = []
        n = len(poly)
        for i in range(n):
            p, q = poly[i], poly[(i + 1) % n]
            pin = (p[2] >= z) if keep_above else (p[2] <= z)
            qin = (q[2] >= z) if keep_above else (q[2] <= z)
            if pin:
                out.append(p)
            if pin != qin:
                t = (z - p[2]) / (q[2] - p[2])
                out.append((p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]), z))
        return out

    kept, segs = [], {lo: [], hi: []}
    for tri in tris:
        zs = [p[2] for p in tri]
        if max(zs) <= lo or min(zs) >= hi:
            continue
        poly = list(tri)
        if min(zs) < lo:
            poly = clip(poly, lo, True)
        if max(p[2] for p in poly) > hi:
            poly = clip(poly, hi, False)
        if len(poly) < 3:
            continue
        for k in range(1, len(poly) - 1):
            kept.append([poly[0], poly[k], poly[k + 1]])
        for z in (lo, hi):
            # The kept surface's edge on the plane, in its own winding (so
            # the outlines chain one way round).
            if not (min(zs) < z - 1e-9 or max(zs) > z + 1e-9):
                continue
            n = len(poly)
            for i in range(n):
                p, q = poly[i], poly[(i + 1) % n]
                if abs(p[2] - z) < 1e-9 and abs(q[2] - z) < 1e-9 and p != q:
                    segs[z].append((p, q))
    for z, ss in segs.items():
        if not ss:
            continue
        loops = _chain(ss)
        flat = capper(loops, z) if capper else None
        if flat is None:
            flat = [((a[0], a[1]), (b[0], b[1]), (c[0], c[1])) for a, b, c in cap([[(p[0], p[1]) for p in lp] for lp in loops])]
        for A, B, C in flat:
            up = (B[0] - A[0]) * (C[1] - A[1]) - (B[1] - A[1]) * (C[0] - A[0]) > 0
            tri = [(A[0], A[1], z), (B[0], B[1], z), (C[0], C[1], z)]
            if up == (z == lo):  # the bottom cap faces down, the top up
                tri = [tri[0], tri[2], tri[1]]
            kept.append(tri)
    return kept


def cut(tris, axis, at, capper=None):
    """(lower, upper) halves of a closed mesh cut square to an axis."""
    k = "xyz".index(axis)
    fwd = {0: lambda p: (p[1], p[2], p[0]), 1: lambda p: (p[2], p[0], p[1]), 2: tuple}[k]
    back = {0: lambda p: (p[2], p[0], p[1]), 1: lambda p: (p[1], p[2], p[0]), 2: tuple}[k]
    src = [[fwd(q) for q in t] for t in tris]
    b = bbox(src)
    lower = slab(src, b[2], at, capper)
    upper = slab(src, at, b[5], capper)
    return [[back(q) for q in t] for t in lower], [[back(q) for q in t] for t in upper]


# ---- repair, smoothing ----------------------------------------------------------------------


def _weld(tris, tol=1e-6):
    key = lambda p: (round(p[0] / tol), round(p[1] / tol), round(p[2] / tol))
    pts, index, faces = [], {}, []
    for t in tris:
        f = []
        for p in t:
            k = key(p)
            if k not in index:
                index[k] = len(pts)
                pts.append(tuple(p))
            f.append(index[k])
        faces.append(f)
    return pts, faces


def fix(tris):
    """Duplicate and degenerate triangles dropped, points welded, and the
    winding of each piece turned outward (positive volume)."""
    pts, faces = _weld(tris)
    seen, keep = set(), []
    for f in faces:
        if len(set(f)) < 3:
            continue
        k = tuple(sorted(f))
        if k in seen:
            continue
        a, b, c = (pts[i] for i in f)
        if normal([a, b, c])[1] < 1e-14:
            continue
        seen.add(k)
        keep.append([a, b, c])
    out = []
    for piece in pieces(keep):
        out += piece if volume(piece) >= 0 else [[t[0], t[2], t[1]] for t in piece]
    return out


def smooth(tris, iterations=3, k=0.5):
    """Laplacian smoothing, each point moved part way to its neighbours'
    centre; points on an open edge stay."""
    pts, faces = _weld(tris)
    nb = [set() for _ in pts]
    edges = {}
    for f in faces:
        for i in range(3):
            a, b = f[i], f[(i + 1) % 3]
            nb[a].add(b)
            nb[b].add(a)
            e = (min(a, b), max(a, b))
            edges[e] = edges.get(e, 0) + 1
    border = {v for e, n in edges.items() if n == 1 for v in e}
    p = [list(x) for x in pts]
    for _ in range(max(0, iterations)):
        q = []
        for i, x in enumerate(p):
            if i in border or not nb[i]:
                q.append(x)
                continue
            c = [sum(p[j][m] for j in nb[i]) / len(nb[i]) for m in range(3)]
            q.append([x[m] + k * (c[m] - x[m]) for m in range(3)])
        p = q
    return [[tuple(p[i]) for i in f] for f in faces]
