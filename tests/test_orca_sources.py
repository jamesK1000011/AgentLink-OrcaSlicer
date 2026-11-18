# SPDX-License-Identifier: LGPL-2.1-or-later
# Findings 42, 43, 44 (18 Nov): one preset source for listing and
# orca_project, the slicer's own error lines in a failed answer, and an
# arrange that keeps each object on its plate. No OrcaSlicer needed.
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from orcalink import cli, orca3mf as O, presets as SP, tools as T  # noqa: E402
from test_orca3mf import sample  # noqa: E402


def put(root, rel, data):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(data, f)
    return p


class OneSource(unittest.TestCase):
    """OrcaSlicer reads its own folders, then Bambu Studio's: a user filament
    kept in Bambu Studio only is listed and taken by name."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        osys, ouser = os.path.join(self.tmp, "orca", "system"), os.path.join(self.tmp, "orca", "user")
        bsys, buser = os.path.join(self.tmp, "bambu", "system"), os.path.join(self.tmp, "bambu", "user")
        put(osys, "BBL/machine/Bambu Lab H2D 0.4 nozzle.json", {"type": "machine", "name": "Bambu Lab H2D 0.4 nozzle", "nozzle_diameter": ["0.4", "0.4"]})
        put(osys, "BBL/process/0.20mm Standard @BBL H2D.json", {"type": "process", "name": "0.20mm Standard @BBL H2D", "layer_height": "0.2"})
        # Only in Bambu Studio's system folder: read to resolve, not listed for OrcaSlicer.
        put(bsys, "BBL/filament/SUNLU PETG @base.json", {"type": "filament", "name": "SUNLU PETG @base", "instantiation": "false",
                                                           "filament_type": ["PETG"], "filament_vendor": ["SUNLU"], "nozzle_temperature": ["240"],
                                                           "filament_ramming_parameters": ["120 100"]})
        put(bsys, "BBL/filament/Bambu PLA Basic @BBL X1.json", {"type": "filament", "name": "Bambu PLA Basic @BBL X1", "filament_type": ["PLA"]})
        # The person's own, as Bambu Studio saves it: only what differs, empty lists.
        put(buser, "1234/filament/SUNLU PETG BASIC GEN2 @ H2D.json", {
            "name": "SUNLU PETG BASIC GEN2 @ H2D", "inherits": "SUNLU PETG @base", "from": "User",
            "nozzle_temperature": ["245"], "filament_vendor": [], "compatible_printers": []})
        # A preset of the person's own in OrcaSlicer's folder with no name key.
        put(ouser, "default/process/My draft.json", {"inherits": "0.20mm Standard @BBL H2D", "from": "User", "layer_height": "0.28"})
        os.environ["AGENTLINK_ORCA_PRESETS"] = os.pathsep.join([ouser, osys])
        os.environ["AGENTLINK_BAMBU_PRESETS"] = os.pathsep.join([buser, bsys])
        self._cache = SP.ORCA_CACHE
        SP.ORCA_CACHE = os.path.join(self.tmp, "no-cache")

    def tearDown(self):
        os.environ.pop("AGENTLINK_ORCA_PRESETS", None)
        os.environ.pop("AGENTLINK_BAMBU_PRESETS", None)
        SP.ORCA_CACHE = self._cache
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_listing_shows_the_bambu_user_preset(self):
        fil = SP.listing("orcaslicer", "filament")["filament"]["presets"]
        self.assertIn({"name": "SUNLU PETG BASIC GEN2 @ H2D", "own": True, "in": "Bambu Studio"}, fil)
        names = [x["name"] for x in fil]
        self.assertNotIn("Bambu PLA Basic @BBL X1", names)  # Bambu Studio's system presets: not listed here
        self.assertIn({"name": "My draft", "own": True}, SP.listing("orcaslicer", "process")["process"]["presets"])
        # Bambu Studio's system folders are read only when a name is missing.
        index = SP.scan("orcaslicer")
        self.assertNotIn("SUNLU PETG @base", index["filament"])
        self.assertEqual(SP.find_name(index, "filament", "SUNLU PETG @base"), "SUNLU PETG @base")

    def test_bundle_takes_the_same_names(self):
        b = SP.bundle("orcaslicer", "Bambu Lab H2D 0.4 nozzle", "My draft", "SUNLU PETG BASIC GEN2 @ H2D")
        f = b["filament"]
        self.assertEqual(f["nozzle_temperature"], ["245"])
        self.assertEqual(f["filament_vendor"], ["SUNLU"])  # empty in the user preset: the parent's kept
        self.assertEqual(f["filament_ramming_parameters"], ["120 100"])
        self.assertEqual(b["process"]["layer_height"], "0.28")
        paths = SP.write_profiles(b, os.path.join(self.tmp, "w"))
        with open(paths["filament"]) as fh:
            written = json.load(fh)
        self.assertEqual([k for k, v in written.items() if isinstance(v, list) and not v], [])
        self.assertNotIn("inherits", written)  # its parent is not one of OrcaSlicer's own

    def test_name_in_other_case_and_spacing(self):
        b = SP.bundle("orcaslicer", "bambu lab h2d 0.4 nozzle", "My draft", "SUNLU  PETG basic GEN2 @ H2D")
        self.assertEqual(b["filament"]["name"], "SUNLU PETG BASIC GEN2 @ H2D")
        self.assertEqual(b["machine"]["name"], "Bambu Lab H2D 0.4 nozzle")

    def test_unknown_name_offers_near_ones(self):
        with self.assertRaises(SP.PresetError) as e:
            SP.bundle("orcaslicer", "Bambu Lab H2D 0.4 nozzle", "My draft", "SUNLU PETG BASIC GEN3 @ H2D")
        self.assertIn("SUNLU PETG BASIC GEN2 @ H2D", str(e.exception))
        self.assertNotIn("slicer_presets", str(e.exception))

    def test_given_user_file_is_flattened(self):
        src = os.path.join(os.environ["AGENTLINK_BAMBU_PRESETS"].split(os.pathsep)[0], "1234", "filament", "SUNLU PETG BASIC GEN2 @ H2D.json")
        out = SP.flatten_file("orcaslicer", "filament", src, os.path.join(self.tmp, "flat"))
        self.assertNotEqual(out, src)
        with open(out) as fh:
            flat = json.load(fh)
        self.assertEqual(flat["filament_vendor"], ["SUNLU"])
        self.assertEqual(flat["type"], "filament")
        self.assertEqual([k for k, v in flat.items() if isinstance(v, list) and not v], [])
        plain = put(self.tmp, "plain.json", {"type": "filament", "name": "x", "filament_type": ["PLA"]})
        self.assertEqual(SP.flatten_file("orcaslicer", "filament", plain, self.tmp), plain)

    def test_presets_action_on_a_project(self):
        d = os.path.join(self.tmp, "out")
        os.makedirs(d)
        sample(os.path.join(d, "p.3mf"))
        from orcalink.server import build

        server = build(d)
        r = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "orca_project", "arguments": {
            "action": "presets", "path": "p.3mf", "filament": "SUNLU PETG BASIC GEN2 @ H2D"}}})["result"]
        got = json.loads(r["content"][0]["text"])
        self.assertFalse(r.get("isError"), got)
        self.assertEqual(got["presets"]["filaments"], ["SUNLU PETG BASIC GEN2 @ H2D"])
        self.assertEqual(O.Project(os.path.join(d, "p.3mf")).config["filament_settings_id"][0], "SUNLU PETG BASIC GEN2 @ H2D")


class OwnErrorLines(unittest.TestCase):
    def test_conflict_line_comes_first(self):
        out = "\n".join(["[2026-11-18 10:00:01.1] [0x1] [info]    loading", "[2026-11-18 10:00:02.2] [0x1] [error]   gcode path conflicts found between box.stl and tall.stl at 12.40 mm"]
                        + [f"[2026-11-18 10:00:03.{i}] [0x1] [info]    step {i}" for i in range(20)]
                        + ["[2026-11-18 10:00:04.0] [0x1] [error]   plate 1: found slicing result conflict!"])
        run = subprocess.CompletedProcess(["orca-slicer"], 155, stdout=out, stderr="")
        msg = str(cli._failed(run, "run found error (code 155)"))
        self.assertIn("gcode path conflicts found between box.stl and tall.stl at 12.40 mm", msg)
        self.assertIn("code 155", msg)
        self.assertNotIn("[0x1]", msg.split("The slicer stopped")[1].split(" / ")[0])

    def test_no_error_lines_keeps_the_tail(self):
        run = subprocess.CompletedProcess(["orca-slicer"], 1, stdout="a\nb\nc\nd", stderr="")
        self.assertIn("b / c / d", str(cli._failed(run)))


class ArrangeKeepsPlates(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.p = os.path.join(self.d, "p.3mf")
        sample(self.p)
        pr = O.Project(self.p)
        pr.move_to_plate("tall.stl", 2)
        pr.save()
        self.calls = []

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def fake_orca(self, name, path, arrange=False, orient=False, options=None):
        """As OrcaSlicer's command line: every instance on an unlocked plate
        goes to the first unlocked plate."""
        pr = O.Project(path)
        plates = pr.plates()
        locks = {p["plate"]: p["settings"].get("locked") == "true" for p in plates}
        self.calls.append(dict(locks))
        free = [n for n, l in sorted(locks.items()) if not l]
        if not free:
            return
        for p in plates:
            if not locks[p["plate"]]:
                for mi in p["instances"]:
                    pr.move_to_plate(next(o["name"] for o in pr.objects() if o["id"] == mi["object_id"]), free[0], int(mi.get("instance_id", 0)))
        pr.save()

    def plate_of(self, name):
        return O.Project(self.p).plate_of(name)

    def test_each_plate_alone(self):
        got = T.arrange_by_plate(self.p, relayout=self.fake_orca)
        self.assertEqual(got, {"plates": [1, 2]})
        self.assertEqual((self.plate_of("box.stl"), self.plate_of("tall.stl")), (1, 2))
        self.assertEqual(self.calls, [{1: False, 2: True}, {1: True, 2: False}])
        self.assertEqual([p["settings"]["locked"] for p in O.Project(self.p).plates()], ["false", "false"])

    def test_the_old_way_lost_the_plate(self):
        self.fake_orca("orcaslicer", self.p, arrange=True)
        self.assertEqual(self.plate_of("tall.stl"), 1)

    def test_a_locked_plate_stays_locked_and_is_not_arranged(self):
        pr = O.Project(self.p)
        pr.set_plate(2, "locked", True)
        pr.save()
        got = T.arrange_by_plate(self.p, relayout=self.fake_orca)
        self.assertEqual(got["plates"], [1])
        self.assertEqual([p["settings"]["locked"] for p in O.Project(self.p).plates()], ["false", "true"])

    def test_locks_come_back_when_orca_fails(self):
        def broken(*a, **k):
            raise RuntimeError("The slicer stopped (code 1)")

        with self.assertRaises(RuntimeError):
            T.arrange_by_plate(self.p, relayout=broken)
        self.assertEqual([p["settings"]["locked"] for p in O.Project(self.p).plates()], ["false", "false"])

    def test_one_plate_is_one_run(self):
        sample(self.p)
        T.arrange_by_plate(self.p, relayout=self.fake_orca)
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
