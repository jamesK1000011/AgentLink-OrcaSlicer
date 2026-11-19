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
        # R3-1: force alone is not the person's word; alone, this server refuses and points to OrcaSlicer's window.
        msg = self.refused("orca_project", {"action": "gcode", "path": "p.3mf", "z": 2, "kind": "custom", "gcode": "M302 P1", "force": True}, "not_allowed")
        self.assertIn("OrcaSlicer's own window", msg)
        self.refused("orca_project", {"action": "set", "path": "p.3mf", "key": "nozzle_temperature", "value": [500], "force": True}, "not_allowed")
        # With a host's person-only approval: pending first, then done; the project shows it.
        fn = self.with_approval([{"pending": True, "approve": {"tool": "approve_code"}}, {"ok": True}])
        r = fn({"action": "gcode", "path": "p.3mf", "z": 2, "kind": "custom", "gcode": "M302 P1"})
        self.assertTrue(r.get("pending"), r)
        self.assertNotIn("M302", json.dumps(O.Project(self.p).gcodes()))
        r = fn({"action": "gcode", "path": "p.3mf", "z": 2, "kind": "custom", "gcode": "M302 P1"})
        self.assertIn("saved", r)
        self.assertEqual(self.asked[0][2], self.asked[1][2])  # the same fingerprint both times
        info = self.call("orca_project", {"action": "info", "path": "p.3mf"})[1]
        self.assertIn("M302", info["gcodeWarning"]["commands"])
        self.assertIn("fromFile", info)

    def with_approval(self, answers):
        from orcalink import tools as T

        self.asked = []

        def approve(what, lines, fp, name):
            self.asked.append((what, lines, fp, name))
            return answers[min(len(self.asked), len(answers)) - 1]

        return next(t for t in T.tools(self.d, approve=approve) if t.name == "orca_project").fn

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


# ---- red team 3 (19 Nov 2026) ----------------------------------------------------------------

def _read(path, mode="r"):
    with open(path, mode) as f:
        return f.read()


def with_config(path, extra):
    """The project at path with extra keys in its project settings, written
    as a file from elsewhere would carry them (not through Project.save)."""
    with zipfile.ZipFile(path) as z:
        members = {n: z.read(n) for n in z.namelist()}
    cfg = json.loads(members.get(O.PROJECT) or b"{}")
    cfg.update(extra)
    members[O.PROJECT] = json.dumps(cfg).encode()
    with zipfile.ZipFile(path, "w") as z:
        for n, d in members.items():
            z.writestr(n, d)


class RedTeam3(RedTeam):
    # R3-2: no program from slicer settings.
    def test_program_keys_refused_emptied_and_shown(self):
        from orcalink import cli

        for args in ({"action": "set", "path": "p.3mf", "key": "post_process", "value": ["/tmp/x.sh"]},
                     {"action": "set", "path": "p.3mf", "settings": {"plugins": ["x"]}},
                     {"action": "set", "path": "p.3mf", "scope": "object", "object": 1, "key": "post_process", "value": "x"},
                     {"action": "new", "files": [self.p], "path": "n.3mf", "settings": {"post_process": "x"}}):
            self.assertIn("program", self.refused("orca_project", args, "not_allowed"))
        with self.assertRaises(O.ProjectError):
            O.check("post_process", ["x"])
        # A project from elsewhere: info shows it; any save here empties it.
        with_config(self.p, {"post_process": ["/tmp/evil.sh"], "slicing_pipeline_plugin": ["p"]})
        info = self.call("orca_project", {"action": "info", "path": "p.3mf"})[1]
        self.assertIn("post_process", info["programs"]["settings"]["project"])
        self.assertFalse(self.call("orca_project", {"action": "set", "path": "p.3mf", "key": "wall_loops", "value": 3})[0])
        cfg = O.Project(self.p).config
        self.assertEqual(cfg["post_process"], [])
        self.assertEqual(cfg["slicing_pipeline_plugin"], [])
        # Profiles (JSON and a PrusaSlicer .ini) go to a slicer as clean copies; the person's files stay.
        js = os.path.join(self.d, "proc.json")
        with open(js, "w") as f:
            json.dump({"name": "p", "post_process": ["/tmp/evil.sh"]}, f)
        ini = os.path.join(self.d, "conf.ini")
        with open(ini, "w") as f:
            f.write("layer_height = 0.2\npost_process = /tmp/evil.sh\n")
        cl = cli._Clean()
        try:
            cj, ci = cl.file(js), cl.file(ini)
            self.assertNotEqual(cj, js)
            self.assertEqual(json.loads(_read(cj))["post_process"], [])
            self.assertIn("post_process = \n", _read(ci))
            self.assertIn("/tmp/evil.sh", _read(ini))
        finally:
            cl.close()
        self.assertFalse(os.path.exists(cj))
        self.assertEqual(cli.PROGRAMS_EMPTIED, ["post_process"])
        with self.assertRaises(RuntimeError) as c:
            cli.slice_with("orcaslicer", "a.stl", "a.gcode", {}, options={"overrides": {"post_process": "x"}})
        self.assertIn("program", str(c.exception))

    def test_slicer_reads_a_clean_copy(self):
        from orcalink import cli
        from test_busy import stand_in

        with_config(self.p, {"post_process": ["/tmp/evil.sh"]})
        exe = stand_in(self.d, 'for a; do last="$a"; done; case "$last" in *.3mf) cp "$last" seen.3mf; echo G1 > plate_1.gcode;; esac')
        old = os.environ.get("AGENTLINK_ORCASLICER")
        os.environ["AGENTLINK_ORCASLICER"] = exe
        try:
            cli.slice_project("orcaslicer", self.p, os.path.join(self.d, "out"), timeout=30)
        finally:
            os.environ.pop("AGENTLINK_ORCASLICER", None) if old is None else os.environ.__setitem__("AGENTLINK_ORCASLICER", old)
        seen = O.Project(os.path.join(self.d, "out", "seen.3mf")).config
        self.assertEqual(seen["post_process"], [])
        self.assertEqual(json.loads(zipfile.ZipFile(self.p).read(O.PROJECT))["post_process"], ["/tmp/evil.sh"])
        self.assertEqual(cli.PROGRAMS_EMPTIED, ["post_process"])

    # R3-3: one path check for reads and writes.
    def test_paths_checked(self):
        home = os.path.expanduser("~")
        stl = os.path.join(self.d, "box.stl")
        M_ = M.box(10, 10, 10)
        O.write_stl(stl, M_)
        for path in ("~/.zshrc", "~/.ssh/x.3mf", "~/Library/x.3mf", "/etc/x.3mf", "x.txt", ".hidden.3mf", "sub/.h/x.3mf"):
            self.refused("orca_project", {"action": "new", "files": [stl], "path": path})
        self.assertIn("overwrite", self.refused("orca_project", {"action": "new", "files": [stl], "path": "p.3mf"}))
        self.assertIn("credentials", self.refused("orca_project", {"action": "info", "path": "~/.ssh/id.3mf"}))
        self.assertIn("credentials", self.refused("orca_project", {"action": "object_add", "path": "p.3mf", "file": "~/.aws/credentials"}))
        self.assertIn("Library", self.refused("orca_project", {"action": "object_add", "path": "p.3mf", "file": "~/Library/Keys/x.stl"}))
        self.refused("gcode_read", {"path": "~/.gnupg/x.gcode"})
        for name in ("../../../x", "sub/x.json", ".x.json", "x.sh"):
            self.refused("orca_slice", {"path": "p.3mf", "export": "settings", "name": name})
        self.refused("orca_slice", {"path": "p.3mf", "export": "svg", "name": "x.txt"})
        self.refused("orca_slice", {"path": "p.3mf", "export": "amf", "name": "x.obj"})
        # A project in a hidden folder is read, but its -out folder is not written there.
        hid = os.path.join(self.d, ".hid")
        os.makedirs(hid)
        shutil.copy(self.p, os.path.join(hid, "q.3mf"))
        self.assertFalse(self.call("orca_project", {"action": "info", "path": os.path.join(hid, "q.3mf")})[0])
        self.assertIn("hidden", self.refused("orca_slice", {"path": os.path.join(hid, "q.3mf"), "export": "obj"}))
        # gcode_read's side files: never in a hidden folder.
        g = os.path.join(hid, "a.gcode")
        with open(g, "w") as f:
            f.write(";LAYER_CHANGE\n;Z:0.2\nG1 X1 Y1 E1 F600\n")
        self.assertIn("hidden", self.refused("gcode_read", {"path": g, "layer": 1, "svg": True}))
        self.assertIn("hidden", self.refused("gcode_read", {"path": g, "toolpaths": True}))
        self.assertTrue(home)

    def test_calibrate_dest_checked(self):
        from test_busy import stand_in

        os.makedirs(os.path.join(self.d, "app", "resources", "calib"))
        exe = stand_in(os.path.join(self.d, "app"), "exit 1")
        old = os.environ.get("AGENTLINK_ORCASLICER")
        os.environ["AGENTLINK_ORCASLICER"] = exe
        try:
            self.refused("orca_calibrate", {"kind": "temperature", "path": "~/.ssh/c.3mf"})
            self.assertIn("overwrite", self.refused("orca_calibrate", {"kind": "temperature", "path": "p.3mf"}))
        finally:
            os.environ.pop("AGENTLINK_ORCASLICER", None) if old is None else os.environ.__setitem__("AGENTLINK_ORCASLICER", old)

    # R3-4: heat, motors, power and pause commands in every G-code text.
    def test_gcode_checks(self):
        from orcalink import cli, guard

        for args in ({"action": "set", "path": "p.3mf", "key": "layer_change_gcode", "value": "M104 S450"},
                     {"action": "set", "path": "p.3mf", "key": "machine_start_gcode", "value": "M190 R150"},
                     {"action": "gcode", "path": "p.3mf", "z": 2, "kind": "custom", "gcode": "M109 S400"},
                     {"action": "gcode", "path": "p.3mf", "z": 2, "kind": "custom", "gcode": "G1 X1\nM84"},
                     {"action": "gcode", "path": "p.3mf", "z": 2, "kind": "custom", "gcode": "M18"},
                     {"action": "gcode", "path": "p.3mf", "z": 2, "kind": "custom", "gcode": "M81"},
                     {"action": "set", "path": "p.3mf", "key": "machine_end_gcode", "value": "M84\nM81"},
                     {"action": "gcode", "path": "p.3mf", "z": 2, "kind": "custom", "gcode": "N12 m0104s400"}):
            self.refused("orca_project", args, "not_allowed")
        # What a normal slice makes passes: placeholders, motors off at the end, ordinary heat and fans.
        for args in ({"action": "set", "path": "p.3mf", "key": "machine_start_gcode", "value": "M190 S[bed_temperature_initial_layer_single]\nM109 S{nozzle_temperature[0]}\nM104 S215"},
                     {"action": "set", "path": "p.3mf", "key": "machine_end_gcode", "value": "M104 S0\nM140 S0\nM107\nM84"},
                     {"action": "gcode", "path": "p.3mf", "z": 2, "kind": "custom", "gcode": "M106 S255 ; fan full"}):
            err, r = self.call("orca_project", args)
            self.assertFalse(err, r)
        info = self.call("orca_project", {"action": "info", "path": "p.3mf"})[1]
        self.assertEqual(info["fanCommands"][0]["gcode"], "M106 S255")
        self.assertNotIn("gcodeWarning", info)
        self.refused("orca_project", {"action": "gcode", "path": "p.3mf", "z": 3, "kind": "pause", "gcode": "hi\nM104 S450"})
        # The pauses written into G-code: only a pause command, one line; the note stays a comment.
        g = os.path.join(self.d, "a.gcode")
        with open(g, "w") as f:
            f.write(";LAYER_CHANGE\n;Z:0.2\nG1 X1\n;LAYER_CHANGE\n;Z:0.4\nG1 X2\n")
        for bad in ("M104 S300", "M601\nM104 S300", "M84", ""):
            with self.assertRaises(ValueError):
                cli.insert_pauses(g, [{"z": 0.3, "note": "x"}], bad)
        cli.insert_pauses(g, [{"z": 0.3, "note": "drop\nM104 S450 in"}], "M601")
        text = _read(g)
        self.assertNotIn("\nM104", text)
        self.assertIn("M601 ; drop M104 S450 in", text)
        self.assertEqual(guard.pause_command("pause"), "PAUSE")

    # R3-6: unpacked size, ratio and member count capped.
    def test_unpack_limits(self):
        bomb = os.path.join(self.d, "models.zip")
        with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("big.stl", b"\0" * (40 * 1024 * 1024))
        self.assertIn("thousand to one", self.refused("orca_project", {"action": "object_add", "path": "p.3mf", "file": bomb}))
        many = os.path.join(self.d, "many.zip")
        with zipfile.ZipFile(many, "w") as z:
            for i in range(30):
                z.writestr(f"m{i}.stl", b"x")
        was = O.MAX_MEMBERS
        O.MAX_MEMBERS = 20
        try:
            self.assertIn("more than 20", self.refused("orca_project", {"action": "object_add", "path": "p.3mf", "file": many}))
        finally:
            O.MAX_MEMBERS = was
        sliced = os.path.join(self.d, "s.3mf")
        with zipfile.ZipFile(sliced, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("Metadata/plate_1.gcode", b"\0" * (40 * 1024 * 1024))
        self.assertIn("thousand to one", self.refused("gcode_read", {"path": sliced}))

    # R3-7: the preset fetch takes only a version number, inside the cache, with safe git.
    def test_preset_fetch_version(self):
        from unittest import mock

        from orcalink import presets as SP

        for v in ("../../..", "/tmp/repo", "2.3", "2.3.1-beta", "2.3.1\n"):
            with self.assertRaises(SP.PresetError):
                SP.fetch_orca(["Acme"], version=v)
        with self.assertRaises(SP.PresetError):
            SP.fetch_orca(["../x"], version="2.3.1")
        if not shutil.which("git"):
            return
        seen = []

        def run(args, **kw):
            seen.append(args)
            raise SP.PresetError("stop")

        with mock.patch("subprocess.run", run), mock.patch.object(SP, "ORCA_CACHE", os.path.join(self.d, "cache")):
            with self.assertRaises(SP.PresetError):
                SP.fetch_orca(["Acme"], version="2.3.1")
        self.assertEqual(seen[0][1:5], ["-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null"])

    # R3-11: text from files without invisible characters, capped.
    def test_text_from_files_cleaned(self):
        from orcalink import guard

        self.assertEqual(guard.text("a\u200bb\u202ec\U000E0041d\x07"), "abcd")
        self.assertEqual(guard.text("x" * 300, 10), "x" * 10 + "…")
        pr = O.Project(self.p)
        pr.set_object(1, "name", "box\u200b\U000E0049\U000E0047")
        pr.set_gcode(2, "custom", gcode="M117 a\u2066b")
        pr.save()
        info = self.call("orca_project", {"action": "info", "path": "p.3mf"})[1]
        self.assertEqual(info["objects"][0]["name"], "box")
        self.assertEqual(info["customGcode"][0]["gcode"], "M117 ab")

    # R3-12: paths under home as ~/...
    def test_home_paths_shown_as_tilde(self):
        from orcalink import guard

        home = os.path.expanduser("~")
        if home in ("", "/"):
            return
        self.assertEqual(guard.tilde({"a": [home + "/x"], "b": home}), {"a": ["~/x"], "b": "~"})
        self.assertEqual(guard.tilde(home + "-other/x"), home + "-other/x")
        msg = self.refused("orca_project", {"action": "info", "path": os.path.join(home, "no-such-zz.3mf")}, "not_found")
        self.assertIn("~/no-such-zz.3mf", msg)
        self.assertNotIn(home + "/", msg)

    # R3-13: temporary folders go when the call ends.
    def test_temp_folders_removed(self):
        tmp = os.path.join(self.d, "tmp")
        os.makedirs(tmp)
        was = tempfile.tempdir
        tempfile.tempdir = tmp
        try:
            z = os.path.join(self.d, "m.zip")
            with zipfile.ZipFile(z, "w") as zz:
                zz.writestr("cube.stl", _read(self.stl(), "rb"))
            self.assertFalse(self.call("orca_project", {"action": "object_add", "path": "p.3mf", "file": z})[0])
            self.refused("orca_project", {"action": "object_add", "path": "p.3mf", "file": os.path.join(self.d, "nope.zip")}, "not_found")
        finally:
            tempfile.tempdir = was
        self.assertEqual(os.listdir(tmp), [])

    def stl(self):
        p = os.path.join(self.d, "cube.stl")
        O.write_stl(p, M.box(10, 10, 10))
        return p



class HubDeclarations(unittest.TestCase):
    # The hub's path guard reads these from the FreeCAD family (hub 8ac1f25).
    def test_writers_and_path_keys(self):
        import ast
        src = open(os.path.join(os.path.dirname(__file__), "..", "orcalink", "fam_freecad.py"), encoding="utf-8").read()
        got = {n.targets[0].id: ast.literal_eval(n.value) for n in ast.parse(src).body
               if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in ("WRITERS", "PATH_KEYS")}
        self.assertEqual(got["WRITERS"], {"orca_project", "orca_calibrate", "orca_slice"})
        self.assertEqual(got["PATH_KEYS"]["orca_paint"], ["texture.file"])


if __name__ == "__main__":
    unittest.main()
