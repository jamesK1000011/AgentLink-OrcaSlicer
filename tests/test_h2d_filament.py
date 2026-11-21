# SPDX-License-Identifier: LGPL-2.1-or-later
# A filament preset of the person's own on a two-extruder printer (Bambu Lab
# H2D): made whole before the command line, checked, and a system filament of
# the same type in its place when the command line still stops. Fixture
# presets in tests/data/h2d-tpu-presets; no slicer, no FreeCAD.
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from orcalink import cli, meshgen as M, orca3mf as O, presets as SP  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "h2d-tpu-presets")
PRINTER = "Bambu Lab H2D 0.4 nozzle"
MINE = "SUNLU TPU 95A GEN2 @Bambu Lab H2D 0.4 nozzle"
CRASH = "The slicer stopped (code -6): ConfigOptionVector::set_at(): Assigning from an empty vector"


class H2DFilament(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._cache = SP.ORCA_CACHE
        SP.ORCA_CACHE = os.path.join(self.tmp, "no-cache")
        os.environ["AGENTLINK_ORCA_PRESETS"] = os.path.join(self.tmp, "no-orca")
        os.environ["AGENTLINK_BAMBU_PRESETS"] = os.pathsep.join([os.path.join(DATA, "user"), os.path.join(DATA, "system")])

    def tearDown(self):
        os.environ.pop("AGENTLINK_ORCA_PRESETS", None)
        os.environ.pop("AGENTLINK_BAMBU_PRESETS", None)
        SP.ORCA_CACHE = self._cache
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_user_filament_made_whole_for_two_extruders(self):
        b = SP.bundle("orcaslicer", PRINTER, None, MINE)
        f = b["filament"]
        self.assertEqual(f["filament_extruder_variant"], ["Direct Drive Standard", "Direct Drive High Flow"])
        self.assertEqual(f["nozzle_temperature"], ["225", "225"])              # the person's, for both variants
        self.assertEqual(f["filament_max_volumetric_speed"], ["3.6", "3.6"])   # empty: its base's one value, padded
        self.assertEqual(f["filament_adhesiveness_category"], ["600"])        # left out: from the nearest system TPU
        self.assertEqual(f["filament_retraction_length"], ["0.4", "0.4"])      # the base's one value, padded
        self.assertEqual(f["filament_flush_temp"], ["0", "0"])
        self.assertEqual(f["filament_density"], ["1.21"])                      # the person's base kept
        self.assertEqual(f["filament_vendor"], ["SUNLU"])                      # never taken from another filament
        self.assertNotIn("filament_ids", f)
        self.assertEqual(b["nearestSystem"], "Bambu TPU 95A @BBL H2D")
        self.assertEqual(b["checked"]["problems"], [])
        self.assertEqual(b["checked"]["filled"], ["filament_adhesiveness_category", "filament_extruder_variant", "filament_flush_temp"])
        with open(SP.write_profiles(b, os.path.join(self.tmp, "w"))["filament"]) as fh:
            written = json.load(fh)
        self.assertEqual([k for k, v in written.items() if isinstance(v, list) and not v], [])
        self.assertEqual(SP.check_filament(written), [])

    def test_system_filament_left_as_it_is(self):
        b = SP.bundle("orcaslicer", PRINTER, None, "Bambu TPU 95A @BBL H2D")
        self.assertNotIn("checked", b)
        self.assertEqual(b["filament"]["nozzle_temperature"], ["230", "235"])

    def test_check_finds_what_stops_the_command_line(self):
        bad = {"filament_extruder_variant": ["a", "b"], "nozzle_temperature": ["220"], "filament_flush_temp": []}
        got = SP.check_filament(bad, {"filament_extruder_variant": ["a", "b"], "nozzle_temperature": ["1", "2"]})
        self.assertIn("filament_flush_temp is empty", got)
        self.assertIn("nozzle_temperature has 1 of 2 values", got)

    def test_nearest_system_same_type_and_printer(self):
        index = SP.scan("orcaslicer")
        got = SP.nearest_system(index, {"name": "Some TPU", "filament_type": ["TPU"]}, {"name": PRINTER})
        self.assertIn(got[0], ("Bambu TPU 95A @BBL H2D", "Generic TPU @BBL H2D"))
        self.assertNotEqual(got[0], "Generic TPU @BBL X1")                    # another printer
        self.assertIsNone(SP.nearest_system(index, {"name": "x", "filament_type": ["PEEK"]}, {"name": PRINTER}))

    def test_given_file_fitted_to_the_given_printer(self):
        src = os.path.join(DATA, "user", "1234", "filament", MINE.replace(" ", "_").replace("@", "at_") + ".json")
        machine = SP.resolve(SP.scan("orcaslicer"), "machine", PRINTER)
        out = SP.flatten_file("orcaslicer", "filament", src, os.path.join(self.tmp, "flat"), machine=machine)
        with open(out) as fh:
            flat = json.load(fh)
        self.assertEqual(flat["nozzle_temperature"], ["225", "225"])
        self.assertEqual(SP.check_filament(flat), [])

    def test_new_falls_back_once_on_the_crash(self):
        from orcalink.server import build

        out = os.path.join(self.tmp, "out")
        os.makedirs(out)
        server = build(out)
        calls = []

        def fake(name, stls, dest, settings, profiles=None, options=None, timeout=600):
            with open(profiles["filament"]) as fh:
                calls.append(json.load(fh)["name"])
            if len(calls) == 1:
                raise RuntimeError(CRASH)
            from test_orca3mf import sample

            sample(dest)
            return "orca"

        real = cli.make_project
        cli.make_project = fake
        try:
            stl = os.path.join(out, "c.stl")
            O.write_stl(stl, M.box(10, 10, 10))
            r = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "orca_project", "arguments": {
                "action": "new", "files": [stl], "path": "n.3mf", "machine": PRINTER, "process": "0.20mm Standard @BBL H2D", "filament": MINE}}})["result"]
            got = json.loads(r["content"][0]["text"])
            self.assertFalse(r.get("isError"), got)
            self.assertEqual(calls, [MINE, "Bambu TPU 95A @BBL H2D"])
            self.assertEqual((got["fallbackFrom"], got["fallbackTo"]), (MINE, "Bambu TPU 95A @BBL H2D"))
            self.assertIn("Tell the person", got["fallbackNote"])
            # Another error: no fallback, the slicer's words come back.
            calls.clear()

            def other(*a, **k):
                calls.append(1)
                raise RuntimeError("The slicer stopped (code 1): no G-code written")

            cli.make_project = other
            r = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "orca_project", "arguments": {
                "action": "new", "files": [stl], "path": "n2.3mf", "machine": PRINTER, "process": "0.20mm Standard @BBL H2D", "filament": MINE}}})["result"]
            self.assertTrue(r.get("isError"))
            self.assertEqual(calls, [1])
        finally:
            cli.make_project = real


class BambuFilamentMap(unittest.TestCase):
    def test_one_map_entry_per_filament(self):
        """Bambu Studio on a two-nozzle printer: each filament loaded gets
        its place in the filament map (one per body on the plate)."""
        d = tempfile.mkdtemp()
        prof = {}
        for k, data in (("machine", {"nozzle_diameter": ["0.4", "0.4"], "default_nozzle_volume_type": ["Standard", "Standard"]}),
                        ("process", {"layer_height": "0.2"}), ("filament", {"filament_type": ["PLA"]})):
            prof[k] = os.path.join(d, k + ".json")
            with open(prof[k], "w") as f:
                json.dump(data, f)
        stls = []
        for n in ("a", "b"):
            stls.append(os.path.join(d, n + ".stl"))
            O.write_stl(stls[-1], M.box(5, 5, 5))
        seen = []

        class Run:
            returncode, stdout, stderr = 1, "", "stopped"

        def fake_run(args, timeout, cwd=None):
            seen.append(args)
            r = Run()
            r.args = args
            return r

        real = (cli.find, cli._run)
        cli.find, cli._run = (lambda name: "/bin/bambu-studio"), fake_run
        try:
            with self.assertRaises(RuntimeError):
                cli._slice_with("bambustudio", stls, os.path.join(d, "x.gcode"), {}, prof)
        finally:
            cli.find, cli._run = real
        args = seen[0]
        self.assertEqual(args[args.index("--filament-map") + 1], "1,1")
        self.assertEqual(args[args.index("--nozzle-volume-type") + 1], "Standard,Standard")
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
