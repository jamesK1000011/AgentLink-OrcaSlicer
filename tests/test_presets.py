# SPDX-License-Identifier: LGPL-2.1-or-later
# The person's slicer presets as data: read, inheritance resolved, chosen,
# exported and imported. A fake Bambu Studio preset tree; no FreeCAD.
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from orcalink import presets as SP  # noqa: E402


def put(root, rel, data):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(data, f)


class Presets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        sysroot = os.path.join(self.tmp, "system")
        user = os.path.join(self.tmp, "user")
        put(sysroot, "BBL/machine/fdm_machine_common.json", {"type": "machine", "name": "fdm_machine_common", "instantiation": "false", "gcode_flavor": "marlin", "nozzle_diameter": ["0.4"]})
        put(sysroot, "BBL/machine/Bambu Lab H2D.json", {"type": "machine_model", "name": "Bambu Lab H2D", "nozzle_diameter": "0.4;0.2;0.6;0.8"})
        put(sysroot, "BBL/machine/Bambu Lab H2D 0.4 nozzle.json", {"type": "machine", "name": "Bambu Lab H2D 0.4 nozzle", "inherits": "fdm_machine_common", "printable_height": "325"})
        put(sysroot, "BBL/process/fdm_process_common.json", {"type": "process", "name": "fdm_process_common", "instantiation": "false", "wall_loops": "2", "sparse_infill_density": "15%", "top_shell_layers": "5", "bottom_shell_layers": "3"})
        put(sysroot, "BBL/process/0.20mm Standard @BBL H2D.json", {"type": "process", "name": "0.20mm Standard @BBL H2D", "inherits": "fdm_process_common", "layer_height": "0.2", "compatible_printers": ["Bambu Lab H2D 0.4 nozzle"]})
        put(sysroot, "BBL/filament/Bambu PLA Basic @BBL H2D.json", {"type": "filament", "name": "Bambu PLA Basic @BBL H2D", "filament_type": ["PLA"], "filament_density": ["1.26"]})
        # The person's own: finer layers, three walls, on top of the system one.
        put(user, "1234/process/My fine PLA.json", {"name": "My fine PLA", "inherits": "0.20mm Standard @BBL H2D", "layer_height": "0.12", "wall_loops": "3", "from": "User"})
        # A filament of the person's own that says nothing of its kind, as Bambu
        # Studio's user folder has them: the command line refuses it written so.
        put(user, "1234/filament/My PLA.json", {"name": "My PLA", "inherits": "Bambu PLA Basic @BBL H2D", "from": "User", "filament_density": ["1.24"]})
        os.environ["AGENTLINK_BAMBU_PRESETS"] = os.pathsep.join([user, sysroot])
        self.out = os.path.join(self.tmp, "out")

    def tearDown(self):
        os.environ.pop("AGENTLINK_BAMBU_PRESETS", None)

    def test_listing(self):
        got = SP.listing("bambustudio")
        procs = got["process"]["presets"]
        # The base presets others inherit from are not offered; the person's own first.
        self.assertEqual(procs[0], {"name": "My fine PLA", "own": True})
        self.assertNotIn("fdm_process_common", [p["name"] for p in procs])
        self.assertEqual(SP.listing("bambustudio", "machine", "h2d")["machine"]["count"], 1)

    def test_bundle_resolves_inheritance(self):
        b = SP.bundle("bambustudio", "Bambu Lab H2D 0.4 nozzle", "My fine PLA", "Bambu PLA Basic @BBL H2D")
        p = b["process"]
        self.assertEqual(p["layer_height"], "0.12")       # the person's
        self.assertEqual(p["wall_loops"], "3")            # the person's
        self.assertEqual(p["sparse_infill_density"], "15%")  # from the base, two levels up
        self.assertNotIn("inherits", p)
        self.assertEqual(b["machine"]["gcode_flavor"], "marlin")
        self.assertEqual(SP.setup_from(b), {"layerHeight": 0.12, "walls": 3, "infill": 15.0, "topLayers": 5, "bottomLayers": 3, "nozzle": 0.4})

    def test_profiles_name_the_printer(self):
        b = SP.bundle("bambustudio", "Bambu Lab H2D 0.4 nozzle", "My fine PLA", "My PLA")
        paths = SP.write_profiles(b, os.path.join(self.tmp, "w"))
        with open(paths["filament"]) as f:
            fil = json.load(f)
        self.assertEqual(fil["type"], "filament")
        self.assertIn("Bambu Lab H2D 0.4 nozzle", fil["compatible_printers"])
        with open(paths["process"]) as f:
            proc = json.load(f)
        self.assertEqual(proc["compatible_printers"].count("Bambu Lab H2D 0.4 nozzle"), 1)
        # The person's process stands on its system one; the system printer is one.
        self.assertEqual((proc["from"], proc["inherits"]), ("User", "0.20mm Standard @BBL H2D"))
        with open(paths["machine"]) as f:
            mach = json.load(f)
        self.assertEqual(mach["from"], "system")
        self.assertNotIn("_system", mach)

    def test_two_nozzles_get_their_volume_types(self):
        from orcalink import cli as slicers

        p = os.path.join(self.tmp, "m2.json")
        with open(p, "w") as f:
            json.dump({"nozzle_diameter": ["0.4", "0.4"], "default_nozzle_volume_type": ["Standard"]}, f)
        self.assertEqual(slicers.nozzle_volume_types(p), ["Standard", "Standard"])
        with open(p, "w") as f:
            json.dump({"nozzle_diameter": ["0.4"]}, f)
        self.assertIsNone(slicers.nozzle_volume_types(p))
        b = SP.bundle("bambustudio", "Bambu Lab H2D 0.4 nozzle", "My fine PLA", "My PLA")
        b["machine"]["default_nozzle_volume_type"] = ["Standard", "Standard"]
        with open(SP.write_profiles(b, os.path.join(self.tmp, "w2"))["machine"]) as f:
            self.assertEqual(json.load(f)["nozzle_volume_type"], ["Standard", "Standard"])

    def test_user_filament_on_two_nozzles(self):
        """A user filament preset as OrcaSlicer saves one for an H2D: only
        what differs, one value where the system preset has one per extruder
        variant, and lists left empty. The command line stopped on those
        ("ConfigOptionVector::set_at(): Assigning from an empty vector")."""
        sysroot = os.path.join(self.tmp, "system")
        put(sysroot, "BBL/filament/Generic PETG @BBL H2D.json", {
            "type": "filament", "name": "Generic PETG @BBL H2D", "filament_type": ["PETG"],
            "filament_extruder_variant": ["Direct Drive Standard", "Direct Drive High Flow"],
            "nozzle_temperature": ["250", "255"], "filament_max_volumetric_speed": ["12", "20"],
            "cool_plate_temp": ["0"], "textured_plate_temp": ["70"], "filament_vendor": ["Generic"]})
        put(os.path.join(self.tmp, "user"), "1234/filament/Brand PETG @ H2D.json", {
            "name": "Brand PETG @ H2D", "inherits": "Generic PETG @BBL H2D", "from": "User",
            "nozzle_temperature": ["240"], "filament_vendor": [], "filament_ids": [], "compatible_printers": [],
            "filament_max_volumetric_speed": ["14", "22"]})
        b = SP.bundle("bambustudio", "Bambu Lab H2D 0.4 nozzle", "My fine PLA", "Brand PETG @ H2D")
        f = b["filament"]
        self.assertEqual(f["nozzle_temperature"], ["240", "240"])          # the person's, for both variants
        self.assertEqual(f["filament_max_volumetric_speed"], ["14", "22"])
        self.assertEqual(f["filament_vendor"], ["Generic"])                # empty: the parent's kept
        self.assertEqual(f["cool_plate_temp"], ["0"])
        with open(SP.write_profiles(b, os.path.join(self.tmp, "w3"))["filament"]) as fh:
            written = json.load(fh)
        empty = [k for k, v in written.items() if isinstance(v, list) and not v]
        self.assertEqual(empty, [])
        self.assertNotIn("filament_ids", written)
        self.assertEqual(written["type"], "filament")

    def test_export_import_round_trip(self):
        b = SP.bundle("bambustudio", "Bambu Lab H2D 0.4 nozzle", "My fine PLA", "Bambu PLA Basic @BBL H2D", "H2D fine")
        name, path = SP.save(self.out, b)
        self.assertEqual(SP.load_saved(self.out, "H2D fine")["process"]["layer_height"], "0.12")
        self.assertEqual(SP.saved(self.out)[0]["machine"], "Bambu Lab H2D 0.4 nozzle")
        # Elsewhere, no Bambu presets: the bundle alone still slices.
        os.environ["AGENTLINK_BAMBU_PRESETS"] = os.path.join(self.tmp, "nowhere")
        with open(path) as f:
            again = SP.check_bundle(json.load(f))
        self.assertEqual(again["filament"]["filament_density"], ["1.26"])
        with self.assertRaises(SP.PresetError):
            SP.check_bundle({"slicer": "bambustudio"})

    def test_unknown_and_looping(self):
        with self.assertRaises(SP.PresetError):
            SP.bundle("bambustudio", "Bambu Lab H2D 0.4 nozzle", "Nope", "Bambu PLA Basic @BBL H2D")
        put(os.path.join(self.tmp, "user"), "1234/process/Loop.json", {"type": "process", "name": "Loop", "inherits": "Loop"})
        with self.assertRaises(SP.PresetError):
            SP.resolve(SP.scan("bambustudio"), "process", "Loop")

    def test_minimal_is_data(self):
        m = SP.minimal({"layerHeight": 0.16, "walls": 4, "volume": (350, 320, 325), "filament": "petg", "density": 1.27})
        self.assertEqual(m["process"]["layer_height"], "0.16")
        self.assertEqual(m["process"]["wall_loops"], "4")
        self.assertEqual(m["machine"]["printable_height"], "325")
        self.assertEqual(m["filament"]["filament_type"], ["PETG"])


class Includes(unittest.TestCase):
    """OrcaSlicer 2.5's system presets as its source has them: a Bambu Lab
    printer's start and end G-code in included template files, base names
    such as fdm_machine_common in every vendor's folder with other values."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        root = self.root = os.path.join(self.tmp, "profiles")
        generic = "G28\nG1 X10.1 Y20 Z0.28 F5000.0 ;Move to start position"
        # Another vendor, sorted first, with the same base names.
        put(root, "Anker/machine/fdm_machine_common.json", {"type": "machine", "name": "fdm_machine_common", "instantiation": "false",
                                                            "machine_start_gcode": "ANKER", "retract_length_toolchange": ["4"], "nozzle_diameter": ["0.4"]})
        put(root, "Anker/filament/fdm_filament_common.json", {"type": "filament", "name": "fdm_filament_common", "instantiation": "false", "filament_density": ["9"]})
        put(root, "BBL/machine/fdm_machine_common.json", {"type": "machine", "name": "fdm_machine_common", "instantiation": "false",
                                                          "machine_start_gcode": generic, "machine_end_gcode": "OLD END", "retract_length_toolchange": ["2"],
                                                          "nozzle_diameter": ["0.4"]})
        put(root, "BBL/machine/fdm_bbl_3dp_002_common.json", {"type": "machine", "name": "fdm_bbl_3dp_002_common", "inherits": "fdm_machine_common",
                                                              "instantiation": "false", "machine_end_gcode": "BBL OLD END"})
        put(root, "BBL/machine/Bambu Lab H2D 0.4 nozzle template machine_start_gcode.json",
            {"type": "machine", "name": "Bambu Lab H2D 0.4 nozzle template machine_start_gcode", "instantiation": "false", "machine_start_gcode": ";===== machine: H2D\nM993 A0 B0 C0"})
        put(root, "BBL/machine/Bambu Lab H2D 0.4 nozzle template machine_end_gcode.json",
            {"type": "machine", "name": "Bambu Lab H2D 0.4 nozzle template machine_end_gcode", "instantiation": "false", "machine_end_gcode": ";== H2D end ==",
             "z_hop": ["9"]})
        put(root, "BBL/machine/Bambu Lab H2D 0.4 nozzle.json",
            {"type": "machine", "name": "Bambu Lab H2D 0.4 nozzle", "inherits": "fdm_bbl_3dp_002_common", "from": "system", "instantiation": "true",
             "nozzle_diameter": ["0.4", "0.4"], "z_hop": ["0.4"],
             "include": ["Bambu Lab H2D 0.4 nozzle template machine_start_gcode", "Bambu Lab H2D 0.4 nozzle template machine_end_gcode"]})
        put(root, "BBL/filament/fdm_filament_common.json", {"type": "filament", "name": "fdm_filament_common", "instantiation": "false", "filament_density": ["1.24"],
                                                            "filament_extruder_variant": ["Direct Drive Standard"], "long_retractions_when_ec": ["0"]})
        put(root, "BBL/filament/fdm_filament_template_direct_dual_e3d.json",
            {"type": "filament", "name": "fdm_filament_template_direct_dual_e3d", "instantiation": "false",
             "filament_extruder_variant": ["Direct Drive Standard", "Direct Drive High Flow", "Direct Drive E3D High Flow"],
             "long_retractions_when_ec": ["1", "1", "1"], "filament_flow_ratio": ["0.95", "0.95", "0.95"]})
        put(root, "BBL/filament/Bambu PLA Basic @BBL H2D.json",
            {"type": "filament", "name": "Bambu PLA Basic @BBL H2D", "inherits": "fdm_filament_common", "instantiation": "true",
             "filament_flow_ratio": ["0.98"], "include": ["fdm_filament_template_direct_dual_e3d"]})
        os.environ["AGENTLINK_ORCA_PRESETS"] = root
        self.old_cache, SP.ORCA_CACHE = SP.ORCA_CACHE, os.path.join(self.tmp, "no-cache")

    def tearDown(self):
        os.environ.pop("AGENTLINK_ORCA_PRESETS", None)
        SP.ORCA_CACHE = self.old_cache

    def test_included_gcode_is_the_printers_own(self):
        m = SP.resolve(SP.scan("orcaslicer"), "machine", "Bambu Lab H2D 0.4 nozzle")
        # Not the generic start G-code of fdm_machine_common, nor the old end
        # G-code of fdm_bbl_3dp_002_common: the H2D's own, from its templates.
        self.assertEqual(m["machine_start_gcode"], ";===== machine: H2D\nM993 A0 B0 C0")
        self.assertEqual(m["machine_end_gcode"], ";== H2D end ==")
        # The preset's own keys go over what it includes.
        self.assertEqual(m["z_hop"], ["0.4"])
        self.assertNotIn("include", m)
        # The parent is the BBL folder's, not another vendor's of the same name.
        self.assertEqual(m["retract_length_toolchange"], ["2"])

    def test_included_per_nozzle_lists(self):
        f = SP.resolve(SP.scan("orcaslicer"), "filament", "Bambu PLA Basic @BBL H2D")
        self.assertEqual(f["long_retractions_when_ec"], ["1", "1", "1"])
        self.assertEqual(f["filament_flow_ratio"], ["0.98", "0.98", "0.98"])
        self.assertEqual(f["filament_density"], ["1.24"])  # BBL's base, not Anker's

    def test_written_profile_carries_the_resolved_gcode(self):
        idx = SP.scan("orcaslicer")
        data = {"machine": SP.resolve(idx, "machine", "Bambu Lab H2D 0.4 nozzle"), "process": {"name": "p", "layer_height": "0.2"},
                "filament": SP.resolve(idx, "filament", "Bambu PLA Basic @BBL H2D")}
        paths = SP.write_profiles(data, os.path.join(self.tmp, "w"))
        with open(paths["machine"]) as fh:
            mach = json.load(fh)
        self.assertTrue(mach["machine_start_gcode"].startswith(";===== machine: H2D"))
        self.assertNotIn("include", mach)

    def test_missing_include_stops(self):
        os.remove(os.path.join(self.root, "BBL", "machine", "Bambu Lab H2D 0.4 nozzle template machine_start_gcode.json"))
        with self.assertRaises(SP.PresetError) as e:
            SP.resolve(SP.scan("orcaslicer"), "machine", "Bambu Lab H2D 0.4 nozzle")
        self.assertIn("template machine_start_gcode", str(e.exception))


class OrcaFetch(unittest.TestCase):
    """OrcaSlicer's packed presets: the same version's JSON fetched by git
    from a repository (a local one here) and read like the rest."""

    @unittest.skipUnless(__import__("shutil").which("git"), "git is not here")
    def test_fetch_and_read(self):
        import subprocess

        src = tempfile.mkdtemp()
        m = os.path.join(src, "resources", "profiles", "Acme", "machine")
        os.makedirs(m)
        with open(os.path.join(src, "resources", "profiles", "Acme.json"), "w") as f:
            json.dump({"name": "Acme"}, f)
        with open(os.path.join(m, "fdm_acme_common.json"), "w") as f:
            json.dump({"type": "machine", "name": "fdm_acme_common", "instantiation": "false", "nozzle_diameter": ["0.4"], "bed": "x"}, f)
        with open(os.path.join(m, "Acme One 0.4 nozzle.json"), "w") as f:
            json.dump({"type": "machine", "name": "Acme One 0.4 nozzle", "inherits": "fdm_acme_common", "printer_model": "Acme One"}, f)
        for c in (["init", "-q", "-b", "main"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"], ["tag", "v9.9.9"]):
            subprocess.run(["git", "-C", src] + c, check=True)
        cache = tempfile.mkdtemp()
        old_cache, old_env = SP.ORCA_CACHE, os.environ.get("AGENTLINK_ORCA_PRESETS")
        SP.ORCA_CACHE = cache
        os.environ["AGENTLINK_ORCA_PRESETS"] = os.path.join(cache, "nothing-here")
        try:
            out = SP.fetch_orca(["Acme"], version="9.9.9", repo="file://" + src)
            self.assertEqual(out["vendors"], ["Acme"])
            idx = SP.scan("orcaslicer")
            self.assertEqual(SP.listing("orcaslicer", "machine")["machine"]["presets"], [{"name": "Acme One 0.4 nozzle"}])
            flat = SP.resolve(idx, "machine", "Acme One 0.4 nozzle")
            self.assertEqual((flat["bed"], flat["printer_model"]), ("x", "Acme One"))
            with self.assertRaises(SP.PresetError):
                SP.fetch_orca(["Acme"], version="0.0.1", repo="file://" + src)
        finally:
            SP.ORCA_CACHE = old_cache
            if old_env is None:
                os.environ.pop("AGENTLINK_ORCA_PRESETS", None)
            else:
                os.environ["AGENTLINK_ORCA_PRESETS"] = old_env


if __name__ == "__main__":
    unittest.main()
