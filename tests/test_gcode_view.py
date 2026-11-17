# SPDX-License-Identifier: LGPL-2.1-or-later
# The headless G-code preview (agentlink/gcode_view.py) on a small file
# written the way OrcaSlicer marks layers and features. No FreeCAD needed.
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orcalink import gcode_view as G  # noqa: E402

SAMPLE = """; HEADER_BLOCK_START
; estimated printing time (normal mode) = 12m 3s
; filament used [mm] = 1234.5
; HEADER_BLOCK_END
M104 S210
G90
M83
;LAYER_CHANGE
;Z:0.2
;HEIGHT:0.2
G1 Z.2 F600
M106 S0
;TYPE:Outer wall
;WIDTH:0.45
G1 X10 Y0 E0.5 F1800
G1 X10 Y10 E0.5
;TYPE:Sparse infill
;WIDTH:0.5
G1 X0 Y10 E0.5 F6000
G1 E-.8 F2100
;WIPE_START
G1 X2 Y8 F3000
;WIPE_END
G0 X0 Y0 F12000
G1 E.8
;LAYER_CHANGE
;Z:0.4
;HEIGHT:0.2
G1 Z.4
M106 S255
M104 S205
;TYPE:Outer wall
;WIDTH:0.45
G2 X10 Y0 I5 J0 E0.8 F1800
;PAUSE_PRINT
M601
T1
;TYPE:Inner wall
G1 X10 Y10 E0.5
"""


class GcodeView(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".gcode")
        with os.fdopen(fd, "w") as f:
            f.write(SAMPLE)

    def tearDown(self):
        os.remove(self.path)

    def test_summary(self):
        d = G.read(self.path)
        s = G.summary(d)
        self.assertEqual(s["layers"], 2)
        self.assertEqual(s["z"], [0.2, 0.4])
        self.assertEqual(s["slicer"]["time"], "12m 3s")
        self.assertIn("Outer wall", s["features"])
        self.assertEqual(s["tools"], [0, 1])
        self.assertEqual(s["ranges"]["temperature"], [205.0, 210.0])
        self.assertEqual(s["ranges"]["fan"], [0.0, 100.0])
        self.assertTrue(any("pause" in e["event"].lower() for e in s["events"]))

    def test_layer_and_arc(self):
        d = G.read(self.path)
        ly = G.layer(d, z=0.4)
        self.assertEqual(ly["layer"], 2)  # numbered from 1, as OrcaSlicer numbers them
        # a half circle of radius 5 from (0,0) to (10,0), counter-clockwise flag G2: clockwise
        self.assertAlmostEqual(ly["features"]["Outer wall"]["lengthMm"], round(math.pi * 5, 1), places=1)
        self.assertEqual(G.layer(d, -1)["layer"], 2)
        self.assertEqual(G.layer(d, 9)["layer"], 2)  # past the top: the last
        with self.assertRaises(ValueError):
            G.layer(d, 0)
        first = G.layer(d, 1)
        self.assertAlmostEqual(first["travelMm"], round(0.2 + 8 ** 0.5 + 68 ** 0.5, 1), places=3)  # lift, wipe, travel
        self.assertEqual(first["width"], [0.45, 0.5])

    def test_legend_and_svg(self):
        d = G.read(self.path, keep_paths=[1])
        leg = G.legend(d, "feature")
        self.assertAlmostEqual(sum(b["share"] for b in leg["bands"]), 1.0, places=2)
        self.assertEqual(G.legend(d, "speed")["view"], "speed")
        with self.assertRaises(ValueError):
            G.legend(d, "nope")
        svg = G.svg(d, 1, "feature")
        self.assertIn("<svg", svg)
        self.assertEqual(svg.count("<line"), 3)
        self.assertIn("Sparse infill", svg)
        with self.assertRaises(ValueError):
            G.svg(d, 2)


import math  # noqa: E402

class Preview(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".gcode")
        with os.fdopen(fd, "w") as f:
            f.write(SAMPLE)

    def tearDown(self):
        os.remove(self.path)

    def test_retracts_wipes_seams(self):
        d = G.read(self.path, keep_paths={1})
        ly = G.layer(d, 1)
        self.assertEqual(ly["retracts"], 1)
        self.assertEqual(ly["wipes"], 1)
        self.assertEqual(ly["seams"], [[0.0, 0.0]] if isinstance(ly["seams"][0], list) else [(0.0, 0.0)])
        self.assertEqual(ly["moves"], 7)  # the lift to the layer, 3 extrusions, retract, wipe, travel

    def test_move_slider(self):
        d = G.read(self.path, keep_paths={1})
        m = G.move(d, 1, 1)
        self.assertEqual(m["kind"], "extrude")
        self.assertEqual(m["gcode"], "G1 X10 Y0 E0.5 F1800")
        self.assertEqual(G.move(d, 1, 4)["kind"], "retract")
        self.assertEqual(G.move(d, 1, 5)["kind"], "wipe")

    def test_actual_speed_is_lower(self):
        d = G.read(self.path)
        s = G.summary(d)
        self.assertLessEqual(s["ranges"]["actual_speed"][1], s["ranges"]["speed"][1])
        self.assertTrue(G.legend(d, "actual_flow")["bands"])

    def test_toolpaths_and_toggles(self):
        d = G.read(self.path, keep_paths="all")
        out = G.toolpaths_obj(d, self.path + ".obj")
        self.assertEqual(out["ribbons"], 5)
        svg = G.svg(d, 1, "feature", show=("travel", "wipe", "retract", "seams"))
        self.assertIn("stroke-dasharray", svg)
        self.assertIn("#ff4fa3", svg)
        os.remove(self.path + ".obj")


# As OrcaSlicer 2.5 writes it for a Bambu Lab printer (cut down from a real
# slice): the start G-code's purge lines at Z0.28 before the first layer
# mark, the reserved tags "; LAYER_HEIGHT:" and "; LINE_WIDTH:", the part
# fan as M106 (P2 is another fan), and the end G-code with Bambu's T255
# unload and M104 S0.
ORCA25 = """; HEADER_BLOCK_START
; generated by OrcaSlicer 2.5.0
; total layer number: 2
; HEADER_BLOCK_END
; EXECUTABLE_BLOCK_START
M204 P20000 R5000 T20000
; FEATURE: Custom
G28
G90;
G92 E0 ;Reset Extruder
G1 X10.1 Y20 Z0.28 F5000.0 ;Move to start position
M109 S205;
G1 X10.1 Y200.0 Z0.28 F1500.0 E15 ;Draw the first line
G1 X10.4 Y200.0 Z0.28 F5000.0 ;Move to side a little
G1 X10.4 Y20 Z0.28 F1500.0 E30 ;Draw the second line
G92 E0 ;Reset Extruder
; MACHINE_START_GCODE_END
M83
; CHANGE_LAYER
; Z_HEIGHT: 0.2
; LAYER_HEIGHT: 0.2
; layer num/total_layer_count: 1/2
M204 S500
G1 X100 Y100 F30000
G1 Z.2
; FEATURE: Outer wall
; LINE_WIDTH: 0.5
G1 X110 Y100 E.5 F3000
G1 X110 Y110 E.5
; CHANGE_LAYER
; Z_HEIGHT: 0.4
; LAYER_HEIGHT: 0.2
; layer num/total_layer_count: 2/2
M106 S201
M106 P2 S191
G1 Z.4
; FEATURE: Outer wall
; LINE_WIDTH: 0.42
G1 X100 Y110 E.4 F3000
; FEATURE: Custom
; MACHINE_END_GCODE_START
G1 Z5.5 F900
M140 S0
M106 S0
M620 S255
T255
M104 S0 ; turn off hotend
; EXECUTABLE_BLOCK_END
"""


class Orca25(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".gcode")
        with os.fdopen(fd, "w") as f:
            f.write(ORCA25)

    def tearDown(self):
        os.remove(self.path)

    def test_the_model_alone(self):
        s = G.summary(G.read(self.path))
        # The layer count OrcaSlicer writes (and orca_slice answers); the
        # purge lines at Z0.28 are not a layer.
        self.assertEqual(s["layers"], 2)
        self.assertEqual(s["z"], [0.2, 0.4])
        self.assertEqual(s["ranges"]["height"], [0.2, 0.2])
        self.assertEqual(s["ranges"]["width"], [0.42, 0.5])
        # M104 S0 and T255 of the end G-code are not the model's.
        self.assertEqual(s["ranges"]["temperature"], [205.0, 205.0])
        self.assertEqual(s["tools"], [0])
        self.assertEqual(s["events"], [])
        self.assertNotIn("Custom", s["features"])
        self.assertEqual(s["ranges"]["acceleration"], [500.0, 500.0])
        m = s["machineGcode"]
        self.assertEqual(m["start"]["filamentMm"], 30.0)
        self.assertEqual(m["start"]["temperature"], [205.0])
        self.assertEqual((m["end"]["tools"], m["end"]["temperature"]), ([255], [0.0]))

    def test_layers_as_orca_numbers_them(self):
        d = G.read(self.path)
        one, two = G.layer(d, 1), G.layer(d, 2)
        self.assertEqual((one["layer"], one["z"], one["height"]), (1, 0.2, 0.2))
        self.assertEqual((two["layer"], two["z"]), (2, 0.4))
        self.assertEqual(one["features"]["Outer wall"]["width"], [0.5, 0.5])
        # The part fan only: S201 of 255, not the other fan's P2 S191.
        self.assertEqual(two["fan"], [0.0, 78.8])


if __name__ == "__main__":
    unittest.main()
