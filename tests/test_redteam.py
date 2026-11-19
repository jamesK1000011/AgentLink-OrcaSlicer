# SPDX-License-Identifier: LGPL-2.1-or-later
# The 14 Nov red team's findings, each held shut: damaged and hostile files
# refused with a reason, printer-changing G-code and runaway temperatures
# needing the person's word, calibration plans from elsewhere not acted on,
# writes kept to sensible places, runaway loops capped.
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from orcalink import calibrate as C, meshgen as M, orca3mf as O  # noqa: E402
from orcalink.server import build  # noqa: E402
from test_orca3mf import sample  # noqa: E402


class RedTeam(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        os.environ["ORCALINK_PLAN_KEY"] = os.path.join(self.d, "plan-key")
        self.server = build(self.d)
        self.p = os.path.join(self.d, "p.3mf")
        sample(self.p)

    def tearDown(self):
        os.environ.pop("ORCALINK_PLAN_KEY", None)
        shutil.rmtree(self.d, ignore_errors=True)

    def call(self, name, args):
        r = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})["result"]
        return r.get("isError", False), json.loads(r["content"][0]["text"])

    def refused(self, name, args, code="invalid_input"):
        err, r = self.call(name, args)
        self.assertTrue(err, r)
        self.assertEqual(r["error"]["code"], code, r)
        return r["error"]["message"]

    def test_damaged_models_say_why(self):
        bad = os.path.join(self.d, "nan.stl")
        with open(bad, "wb") as f:
            f.write(b"\0" * 80 + struct.pack("<I", 1) + struct.pack("<12fH", 0, 0, 0, float("nan"), 0, 0, 1, 0, 0, 0, 1, 0, 0))
        self.assertIn("finite", self.refused("orca_project", {"action": "object_add", "path": "p.3mf", "file": bad}))
        cut = os.path.join(self.d, "cut.stl")
        with open(cut, "wb") as f:
            f.write(b"\0" * 80 + struct.pack("<I", 5) + b"\0" * 60)
        self.assertIn("cut short", self.refused("orca_project", {"action": "object_add", "path": "p.3mf", "file": cut}))
        obj = os.path.join(self.d, "bad.obj")
        with open(obj, "w") as f:
            f.write("v 0 0 0\nv 1 0 0\nf 1 2 9\n")
        self.assertIn("line 3", self.refused("orca_project", {"action": "object_add", "path": "p.3mf", "file": obj}))

    def test_zip_bomb_refused_before_reading(self):
        bomb = os.path.join(self.d, "bomb.3mf")
        with zipfile.ZipFile(self.p) as z, zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as out:
            for n in z.namelist():
                out.writestr(n, z.read(n))
            out.writestr("Metadata/pad.bin", b"\0" * (40 * 1024 * 1024))
        self.assertIn("thousand to one", self.refused("orca_project", {"action": "info", "path": bomb}))

    def test_printer_changing_gcode_needs_the_persons_word(self):
        self.refused("orca_project", {"action": "gcode", "path": "p.3mf", "z": 2, "kind": "custom", "gcode": "M117 hi\nM997"}, "not_allowed")
        self.refused("orca_project", {"action": "set", "path": "p.3mf", "key": "machine_start_gcode", "value": "G28\nM211 S0"}, "not_allowed")
        self.refused("orca_project", {"action": "set", "path": "p.3mf", "key": "nozzle_temperature", "value": [500]}, "not_allowed")
        err, r = self.call("orca_project", {"action": "gcode", "path": "p.3mf", "z": 2, "kind": "custom", "gcode": "M302 P1", "force": True})
        self.assertFalse(err, r)
        info = self.call("orca_project", {"action": "info", "path": "p.3mf"})[1]
        self.assertIn("M302", info["gcodeWarning"]["commands"])
        self.assertIn("fromFile", info)

    def test_calibration_plans_from_elsewhere_are_not_acted_on(self):
        plan = {"post": {"retraction": [[0, 5, 1.0]]}}
        mine = C.dump(plan)
        self.assertEqual(C.load_post(mine), plan["post"])
        forged = json.dumps({"plan": json.dumps(plan, sort_keys=True), "sig": "0" * 64}).encode()
        self.assertIsNone(C.load_post(forged))
        self.assertIsNone(C.load_post(json.dumps({"post": {"retraction": [[0, 1e9, 500]]}}).encode()))
        self.assertIsNone(C.load_post(C.dump({"post": {"retraction": [[0, 1e9, 500]]}})))

    def test_writes_stay_sensible(self):
        self.assertIn("folders", self.refused("orca_slice", {"path": "p.3mf", "export": "obj", "name": "../../evil.obj"}))

    # R2-15: no tool writes into the app copy, where add-ons load from.
    def test_no_write_into_the_app_copy(self):
        from orcalink import addons
        dest = os.path.join(addons.APP_ROOT, "zz-redteam.3mf")
        self.assertIn("own folder", self.refused("orca_project", {"action": "set", "path": "p.3mf", "key": "wall_loops", "value": 3, "saveAs": dest}))
        self.assertFalse(os.path.exists(dest))
        self.refused("orca_project", {"action": "set", "path": "p.3mf", "key": "wall_loops", "value": 3, "saveAs": ".zshrc.3mf"})
        self.refused("orca_project", {"action": "set", "path": "p.3mf", "key": "wall_loops", "value": 3, "saveAs": "x.txt"})
        self.assertIn("overwrite", self.refused("orca_project", {"action": "set", "path": "p.3mf", "key": "wall_loops", "value": 3, "saveAs": "p.3mf"}))

    def test_runaway_loops_capped(self):
        self.refused("orca_project", {"action": "mesh", "path": "p.3mf", "object": "box.stl", "op": "smooth", "iterations": 100000000})
        self.refused("orca_project", {"action": "instance", "path": "p.3mf", "object": "box.stl", "count": 100000})
        self.refused("orca_project", {"action": "mesh", "path": "p.3mf", "object": "box.stl", "op": "cut_grid", "size": [0.01, 0.01]})
        self.refused("orca_project", {"action": "grid", "path": "p.3mf", "object": "box.stl", "nx": 1000, "ny": 1000})

    def test_presets_action_answers(self):
        msg = self.refused("orca_project", {"action": "presets", "path": "p.3mf", "machine": "No Such Printer"})
        self.assertNotIn("slicer_presets list", msg)


if __name__ == "__main__":
    unittest.main()
