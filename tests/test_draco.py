# SPDX-License-Identifier: LGPL-2.1-or-later
# Draco files written in plain Python (agentlink/draco.py): the bitstream's
# fields byte by byte, and a round trip. OrcaSlicer reading them back is
# test_orca's.

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from orcalink import draco  # noqa: E402

CUBE_V = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
CUBE_F = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]


class Draco(unittest.TestCase):
    def test_header_and_layout(self):
        b = draco.encode(CUBE_V, CUBE_F)
        self.assertEqual(b[:5], b"DRACO")
        self.assertEqual(struct.unpack_from("<BBBBH", b, 5), (2, 2, 1, 0, 0))
        self.assertEqual(b[11:14], bytes([12, 8, 1]))  # faces, points, uncompressed
        # 36 one-byte indices, then decoders 1, attributes 1, POSITION float32 x3, id 0, generic.
        self.assertEqual(b[14 + 36:14 + 36 + 8], bytes([1, 1, 0, 9, 3, 0, 0, 0]))
        self.assertEqual(len(b), 14 + 36 + 8 + 8 * 12)

    def test_round_trip_and_index_widths(self):
        for n in (8, 300, 70000):
            verts = [(float(i), 0.5 * i, -i) for i in range(n)]
            faces = [(i, (i + 1) % n, (i + 2) % n) for i in range(0, n, 3)]
            v, f = draco.decode(draco.encode(verts, faces))
            self.assertEqual(f, faces)
            self.assertEqual(len(v), n)
            self.assertAlmostEqual(v[-1][1], 0.5 * (n - 1), places=2)

    def test_varint(self):
        self.assertEqual(draco._varint(0x10000000), bytes([0x80, 0x80, 0x80, 0x80, 0x01]))  # five bytes, as the spec says
        self.assertEqual(draco._read_varint(draco._varint(300), 0), (300, 2))


if __name__ == "__main__":
    unittest.main()
