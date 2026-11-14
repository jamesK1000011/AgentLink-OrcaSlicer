# SPDX-License-Identifier: LGPL-2.1-or-later
# Plain-Python meshes: primitives, cuts closed again (holes kept), pieces,
# repair, smoothing, picking.
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from orcalink import meshgen as M  # noqa: E402


def closed(tris):
    """Every edge used twice, once each way."""
    pts, faces = M._weld(tris, 1e-5)
    edges = {}
    for f in faces:
        for i in range(3):
            e = (f[i], f[(i + 1) % 3])
            edges[e] = edges.get(e, 0) + 1
    return all(edges.get((b, a), 0) == n for (a, b), n in edges.items())


class Meshes(unittest.TestCase):
    def test_primitives(self):
        self.assertAlmostEqual(M.volume(M.box(10, 20, 30)), 6000, places=6)
        self.assertAlmostEqual(M.volume(M.cylinder(10, 10, 256)), 785.398, delta=0.5)
        self.assertAlmostEqual(M.volume(M.sphere(10, 128)), 523.6, delta=1.5)
        for kind in ("cube", "cylinder", "sphere", "cone", "disc", "torus"):
            t = M.primitive(kind, [20, 20, 20])
            self.assertGreater(M.volume(t), 0, kind)
            self.assertTrue(closed(t), kind)

    def test_cut_keeps_volume_and_closes(self):
        for tris in (M.box(10, 10, 10), M.cylinder(12, 10), M.torus(40, 10)):
            v = M.volume(tris)
            for axis in "xyz":
                b = M.bbox(tris)
                k = "xyz".index(axis)
                at = b[k] + 0.37 * (b[k + 3] - b[k])
                lo, hi = M.cut(tris, axis, at)
                self.assertAlmostEqual(M.volume(lo) + M.volume(hi), v, delta=v * 1e-6)
                self.assertTrue(closed(lo) and closed(hi), axis)

    def test_slab_with_a_hole(self):
        # A torus cut across its middle: each cap is a ring (a hole kept).
        t = M.torus(40, 10)
        s = M.slab(t, 3, 7)
        self.assertTrue(closed(s))
        cap = [x for x in s if all(abs(p[2] - 7) < 1e-9 for p in x)]
        self.assertTrue(cap)
        self.assertFalse(any(all(abs(p[0]) < 5 and abs(p[1]) < 5 for p in x) for x in cap))

    def test_pieces_mirror_fix_smooth(self):
        two = M.box(5, 5, 5) + M.box(2, 2, 2, at=(10, 0, 0))
        self.assertEqual([len(p) for p in M.pieces(two)], [12, 12])
        m = M.mirror(M.box(4, 2, 1), "x")
        self.assertAlmostEqual(M.volume(m), 8)
        flipped = [[t[0], t[2], t[1]] for t in M.box(3, 3, 3)] + [M.box(3, 3, 3)[0]]
        self.assertAlmostEqual(M.volume(M.fix(flipped)), 27)
        sm = M.smooth(M.sphere(10), 2)
        self.assertTrue(closed(sm))
        self.assertLess(M.volume(sm), M.volume(M.sphere(10)))

    def test_pick(self):
        b = M.box(10, 10, 10)
        self.assertEqual(sum(M.pick(b, {"normal": [0, 0, 1]})), 2)
        self.assertEqual(sum(M.pick(b, {"normal": [0, 0, -1]})), 2)
        self.assertEqual(sum(M.pick(b, {"below": 0.1})), 2)
        self.assertEqual(sum(M.pick(b, {"box": [[-1, -1, -1], [11, 11, 4]]})), 6)  # the bottom and one triangle of each side (centres at z 3.3)
