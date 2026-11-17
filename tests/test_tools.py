# SPDX-License-Identifier: LGPL-2.1-or-later
# The tools through the server, as an agent calls them: on the sample project
# with no slicer (every action that needs none), and end to end with the real
# OrcaSlicer when one is here (AGENTLINK_ORCASLICER; CI unpacks its AppImage).
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from orcalink import cli, meshgen as M, orca3mf as O  # noqa: E402
from orcalink.server import build  # noqa: E402
from test_orca3mf import sample  # noqa: E402


class Calls(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.server = build(self.d)
        self.p = os.path.join(self.d, "p.3mf")
        sample(self.p)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def call(self, name, args=None):
        r = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}})["result"]
        return r.get("isError", False), json.loads(r["content"][0]["text"])

    def ok(self, name, args=None):
        err, r = self.call(name, args)
        self.assertFalse(err, r)
        return r

    def refused(self, name, args, code):
        err, r = self.call(name, args)
        self.assertTrue(err, r)
        self.assertEqual(r["error"]["code"], code, r)
        return r

    def test_listing_and_guide(self):
        names = [t["name"] for t in self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]]
        self.assertEqual(names, ["orca_project", "orca_paint", "orca_calibrate", "orca_slice", "gcode_read", "guide_read", "orca_status"])
        self.assertIn("orca_project", self.ok("guide_read", {"topic": "orca"})["text"])
        self.assertIn("out", self.ok("orca_status"))

    def test_settings_and_levels(self):
        r = self.ok("orca_project", {"action": "settings", "query": "infill_density"})
        self.assertTrue(any(x["key"] == "sparse_infill_density" for x in r["settings"]))
        self.ok("orca_project", {"action": "set", "path": "p.3mf", "settings": {"sparse_infill_density": "25%", "wall_loops": 3}})
        self.ok("orca_project", {"action": "set", "path": "p.3mf", "object": "tall.stl", "key": "wall_loops", "value": 4})
        self.ok("orca_project", {"action": "set", "path": "p.3mf", "scope": "range", "object": "tall.stl", "zmin": 5, "zmax": 10, "settings": {"sparse_infill_density": "80%"}})
        self.refused("orca_project", {"action": "set", "path": "p.3mf", "key": "sparse_infill_density", "value": 300}, "invalid_input")
        info = self.ok("orca_project", {"action": "info", "path": "p.3mf", "object": "tall.stl"})
        self.assertEqual(str(info["effective"]["wall_loops"]), "4")

    def test_parts(self):
        self.ok("orca_project", {"action": "part_add", "path": "p.3mf", "object": "box.stl", "kind": "modifier_part", "box": [4, 4, 5], "at": [0, 0, 2.5], "settings": {"sparse_infill_density": "100%"}})
        r = self.ok("orca_project", {"action": "part_add", "path": "p.3mf", "object": "box.stl", "kind": "negative_part", "primitive": "cylinder", "size": [3, 3, 8], "at": [5, 0, 2.5]})
        kinds = [p["kind"] for p in O.Project(self.p).object("box.stl")["parts"]]
        self.assertEqual(kinds, ["normal_part", "modifier_part", "negative_part"])
        self.refused("orca_project", {"action": "part_add", "path": "p.3mf", "object": "box.stl", "body": "Body"}, "unavailable")
        self.refused("orca_project", {"action": "emboss", "path": "p.3mf", "object": "box.stl", "text": "A"}, "unavailable")
        del r

    def test_mesh_ops(self):
        self.refused("orca_project", {"action": "mesh", "path": "p.3mf", "object": "box.stl", "op": "simplify"}, "unavailable")
        r = self.ok("orca_project", {"action": "mesh", "path": "p.3mf", "object": "tall.stl", "op": "cut", "axis": "z", "at": 12})
        self.assertEqual(len(r["objects"]), 2)
        pr = O.Project(self.p)
        vols = sorted(round(M.volume(self._tris(pr, o)), 3) for o in pr.objects() if o["name"].startswith("tall"))
        self.assertEqual(vols, [8 * 8 * 8, 8 * 8 * 12])
        r = self.ok("orca_project", {"action": "mesh", "path": "p.3mf", "object": "box.stl", "op": "cut_grid", "size": [8, 8]})
        self.assertEqual(len(r["objects"]), 6)  # 20 x 10 in 8 mm cells: 3 x 2
        for op in ("fix", "smooth", "mirror"):
            self.ok("orca_project", {"action": "mesh", "path": "p.3mf", "object": "box.stl 1-1", "op": op})

    def _tris(self, pr, o):
        out = []
        for p in o["parts"]:
            v, t, _ = pr.mesh(p)
            w = [O.apply(p["transform"], x) for x in v]
            out += [[w[i], w[j], w[k]] for i, j, k in t]
        return out

    def test_paint_where(self):
        r = self.ok("orca_paint", {"path": "p.3mf", "object": "box.stl", "kind": "supports", "where": {"normal": [0, 0, -1]}, "state": "enforce"})
        self.assertEqual(r["triangles"], 2)
        self.assertIn("note", r)
        r = self.ok("orca_paint", {"path": "p.3mf", "object": "tall.stl", "kind": "seam", "where": {"above": 15}, "state": "block"})
        self.assertGreater(r["triangles"], 0)
        self.refused("orca_paint", {"path": "p.3mf", "object": "box.stl", "faces": ["Face1"]}, "unavailable")
        self.ok("orca_paint", {"path": "p.3mf", "object": "box.stl", "kind": "supports", "clear": True})

    def test_strength_from_the_mesh(self):
        r = self.ok("orca_project", {"action": "strength", "path": "p.3mf", "object": "tall.stl"})
        self.assertEqual(r["from"], "the object's own mesh")

    def test_exports_without_a_slicer(self):
        r = self.ok("orca_slice", {"path": "p.3mf", "export": "drc"})
        self.assertTrue(os.path.isfile(r["files"][0]))
        r = self.ok("orca_slice", {"path": "p.3mf", "export": "svg", "layerHeight": 0.5})
        self.assertGreater(r["layers"], 10)

    def test_plate_bed_type_read_back(self):
        r = self.ok("orca_project", {"action": "set", "path": "p.3mf", "scope": "plate", "plate": 1, "key": "bed_type", "value": "Textured PEI Plate"})
        self.assertEqual(r["bedType"], {"plate": 1, "readBack": "Textured PEI Plate"})
        self.assertEqual(O.Project(self.p).config["curr_bed_type"], "Textured PEI Plate")
        self.refused("orca_project", {"action": "set", "path": "p.3mf", "scope": "plate", "plate": 1, "key": "bed_type", "value": "Glass"}, "invalid_input")
        r = self.ok("orca_project", {"action": "set", "path": "p.3mf", "key": "curr_bed_type", "value": "High Temp Plate"})
        self.assertEqual(r["bedType"], {"project": "High Temp Plate"})

    def test_new_picks_a_bed_the_filament_takes(self):
        """The command line leaves a new project on Cool Plate; with PETG
        (0 °C there) a bed it goes on is chosen instead."""
        def fake(name, stls, dest, settings, profiles=None, options=None, timeout=600):
            sample(dest)
            pr = O.Project(dest)
            pr.config["cool_plate_temp"] = ["0", "0"]
            pr.changed = True
            pr.save()
            return "orca"

        real = cli.make_project
        cli.make_project = fake
        try:
            stl = os.path.join(self.d, "c.stl")
            O.write_stl(stl, M.box(10, 10, 10))
            r = self.ok("orca_project", {"action": "new", "files": [stl], "path": "n.3mf"})
            self.assertEqual(r["bedType"], "Textured PEI Plate")
            self.assertNotIn("Cool Plate", r["bedTypes"])
            self.assertEqual(O.Project(r["project"]).config["curr_bed_type"], "Textured PEI Plate")
            r = self.ok("orca_project", {"action": "new", "files": [stl], "path": "n2.3mf", "bed_type": "Cool Plate"})
            self.assertEqual(r["bedType"], "Textured PEI Plate")
            self.assertIn("bedTypeRefused", r)
            r = self.ok("orca_project", {"action": "new", "files": [stl], "path": "n3.3mf", "bed_type": "High Temp Plate"})
            self.assertEqual(r["bedType"], "High Temp Plate")
        finally:
            cli.make_project = real

    def test_new_bodies_map_by_source_not_order_or_prefix(self):
        """Two bodies whose names prefix each other ("Box", "Box lid"), and
        Orca giving the objects back in another order (here reversed, with
        full source paths): each object still names its own body, in new,
        info and every action that finds the body by itself."""
        from orcalink import tools as T

        sizes = {"Box": (40, 30, 20), "Box lid": (40, 30, 3)}
        asked = []

        class Geo(T.Geo):
            name = "FreeCAD"

            def body(self, name):
                # The loosest lookup a CAD side might have: whole name, else the
                # first body whose name starts with it.
                for k in sizes:
                    if k == name:
                        return k
                for k in sizes:
                    if name and k.startswith(name):
                        return k
                raise T.ToolError("not_found", name)

            def label(self, b):
                return b

            def tris(self, b, tol=0.01):
                return M.box(*sizes[b])

            def bbox(self, b):
                return [0, 0, 0, *sizes[b]]

            def face_normal(self, b, face):
                asked.append(b)
                return [0, 0, -1]

        def fake(name, stls, dest, settings, profiles=None, options=None, timeout=600):
            sample(dest)
            pr = O.Project(dest)
            for o in list(pr.objects())[::-1]:
                pr.remove_object(o["name"])
            for f in sorted(stls, reverse=True):
                pr.add_object(O.read_stl(f), os.path.basename(f))
                # Orca records the path it loaded the file from.
                for part in pr.settings_xml.findall("object")[-1].findall("part"):
                    for m in part.findall("metadata"):
                        if m.get("key") == "source_file":
                            m.set("value", os.path.abspath(f))
            pr.changed = True
            pr.save()
            return "orca"

        real = cli.make_project
        cli.make_project = fake
        try:
            srv = T.tools(self.d, Geo())
            run = {t.name: t for t in srv}["orca_project"].fn
            r = run({"action": "new", "bodies": ["Box", "Box lid"], "path": "enclosure.3mf"})
            got = {o["name"]: o.get("body") for o in r["objects"]}
            self.assertEqual(got, {"Box_lid.stl": "Box lid", "Box.stl": "Box"}, r["objects"])
            self.assertEqual([o["name"] for o in r["objects"]], ["Box_lid.stl", "Box.stl"])  # Orca's order, not the bodies'
            info = run({"action": "info", "path": "enclosure.3mf"})
            self.assertEqual({o["name"]: o.get("body") for o in info["objects"]}, got)
            # The project, saved again by another action, keeps the map.
            run({"action": "set", "path": "enclosure.3mf", "object": "Box.stl", "key": "wall_loops", "value": 3})
            info = run({"action": "info", "path": "enclosure.3mf", "object": "Box_lid.stl"})
            self.assertEqual(info["body"], "Box lid")
            # An action that finds the body itself asks for the right one.
            run({"action": "lay_flat", "path": "enclosure.3mf", "object": "Box_lid.stl", "face": "Face1"})
            run({"action": "lay_flat", "path": "enclosure.3mf", "object": "Box.stl", "face": "Face1"})
            self.assertEqual(asked, ["Box lid", "Box"])
            # Without the map (the project saved by Orca's window): whole names
            # of the source file only, never a body the name merely starts.
            pr = O.Project(r["project"])
            pr.files.pop(T.BODY_MAP)
            pr.save()
            self.assertNotIn("body", run({"action": "info", "path": "enclosure.3mf"})["objects"][0])
            del asked[:]
            run({"action": "lay_flat", "path": "enclosure.3mf", "object": "Box_lid.stl", "face": "Face1"})
            run({"action": "lay_flat", "path": "enclosure.3mf", "object": "Box.stl", "face": "Face1"})
            self.assertEqual(asked, ["Box lid", "Box"])
        finally:
            cli.make_project = real

    def test_slice_bed_error_names_beds_that_work(self):
        real = cli.slice_project
        realfind = cli.find

        def stop(*a, **k):
            raise RuntimeError("Cool Plate does not support filament 1 (code -51)")

        cli.slice_project, cli.find = stop, lambda name: "/bin/true"
        try:
            pr = O.Project(self.p)
            pr.config["cool_plate_temp"] = ["0", "0"]
            pr.changed = True
            pr.save()
            r = self.refused("orca_slice", {"path": "p.3mf"}, "failed")
            msg = r["error"]["message"]
            self.assertIn("Textured PEI Plate", msg)
            self.assertNotIn("go on: Cool Plate", msg)
            self.assertIn("curr_bed_type", msg)
        finally:
            cli.slice_project, cli.find = real, realfind

    def test_slicer_needed(self):
        if cli.find("orcaslicer"):
            self.skipTest("OrcaSlicer is here")
        stl = os.path.join(self.d, "c.stl")
        O.write_stl(stl, M.box(10, 10, 10))
        self.refused("orca_project", {"action": "new", "files": [stl]}, "unavailable")
        self.refused("orca_slice", {"path": "p.3mf"}, "unavailable")


class Hardening(Calls):
    """16 Nov 2026: a wrong call is refused with what to give, never a bare
    KeyError; an unknown where key no longer paints every triangle; a
    negative layer height no longer runs until memory is gone."""

    def test_a_missing_argument_is_named(self):
        for action in ("part_add", "part_remove", "replace", "place", "plate", "object_remove", "instance", "printable", "layer_heights",
                       "brim_ears", "mesh", "lay_flat", "copy", "instance_to_object", "scale_to_fit", "fill_bed", "grid", "strength"):
            r = self.refused("orca_project", {"action": action, "path": "p.3mf"}, "invalid_input")
            self.assertIn("object is needed", r["error"]["message"], action)
        for action in ("plate_remove", "plate_move"):
            r = self.refused("orca_project", {"action": action, "path": "p.3mf"}, "invalid_input")
            self.assertIn("plate is needed", r["error"]["message"], action)
        r = self.refused("orca_project", {"action": "set", "path": "p.3mf", "scope": "object", "key": "wall_loops", "value": 3}, "invalid_input")
        self.assertIn("object is needed", r["error"]["message"])
        r = self.refused("orca_project", {"action": "filament", "path": "p.3mf", "remove": True}, "invalid_input")
        self.assertIn("slot is needed", r["error"]["message"])
        r = self.refused("orca_project", {"action": "info"}, "invalid_input")
        self.assertTrue(r["error"]["message"].startswith("path:"), r)
        self.refused("orca_project", {"action": "info", "path": "nofile.3mf"}, "not_found")

    def test_wrong_shapes_are_refused_in_words(self):
        bad = [{"action": "part_add", "object": "box.stl", "box": [1, 2]},
               {"action": "brim_ears", "object": "box.stl", "points": [[1]]},
               {"action": "layer_heights", "object": "box.stl", "profile": [[1]]},
               {"action": "lay_flat", "object": "box.stl", "normal": [1]},
               {"action": "mesh", "object": "box.stl", "op": "cut", "axis": "w"},
               {"action": "mesh", "object": "box.stl", "op": "cut", "at": "x"},
               {"action": "mesh", "object": "box.stl", "op": "cut_grid", "size": "a"},
               {"action": "instance_to_object", "object": "box.stl"}]
        for a in bad:
            r = self.refused("orca_project", {"path": "p.3mf", **a}, "invalid_input")
            self.assertNotIn("failed:", r["error"]["message"], a)
        for a in ({"action": "part_add", "object": "box.stl", "file": "nofile.stl"}, {"action": "replace", "object": "box.stl", "file": "nofile.stl"},
                  {"action": "presets", "bundle": "nope"}):
            self.refused("orca_project", {"path": "p.3mf", **a}, "not_found")

    def test_a_relative_part_file_is_in_the_output_folder(self):
        O.write_stl(os.path.join(self.d, "blk.stl"), M.box(2, 2, 2))
        self.ok("orca_project", {"action": "part_add", "path": "p.3mf", "object": "box.stl", "file": "blk.stl"})
        self.assertEqual(len(O.Project(self.p).object("box.stl")["parts"]), 2)

    def test_where_keys_are_checked(self):
        r = self.refused("orca_paint", {"path": "p.3mf", "object": "box.stl", "where": {"face": "top"}}, "invalid_input")
        self.assertIn("where.face", r["error"]["message"])
        self.refused("orca_paint", {"path": "p.3mf", "object": "box.stl", "where": {"within": 10}}, "invalid_input")
        self.refused("orca_paint", {"path": "p.3mf", "object": "box.stl", "where": {"normal": [0, 0]}}, "invalid_input")
        self.refused("orca_paint", {"path": "p.3mf", "object": "box.stl", "where": {"box": [1, 2]}}, "invalid_input")
        self.refused("orca_paint", {"path": "p.3mf", "object": "box.stl", "kind": "color", "where": {"above": 0}, "state": "x"}, "invalid_input")
        # Nothing was painted by the refused calls; a box's corners may come either way round.
        self.assertNotIn("painted", self.ok("orca_project", {"action": "info", "path": "p.3mf", "object": "box.stl"})["parts"][0])
        r = self.ok("orca_paint", {"path": "p.3mf", "object": "box.stl", "where": {"box": [[30, 30, 30], [-30, -30, -30]]}})
        self.assertEqual(r["triangles"], 12)

    def test_svg_layer_height_and_plate_bounds(self):
        for lh in (-1, 0.0001, 50):
            self.refused("orca_slice", {"path": "p.3mf", "export": "svg", "layerHeight": lh}, "invalid_input")
        for what in ("svg", "drc", "obj"):
            r = self.refused("orca_slice", {"path": "p.3mf", "export": what, "plate": 9}, "invalid_input")
            self.assertIn("1 plate(s)", r["error"]["message"])

    def test_gcode_read_of_a_missing_sliced_project(self):
        r = self.refused("gcode_read", {"path": "none-sliced.3mf"}, "not_found")
        self.assertIn("orca_slice", r["error"]["message"])

    def test_gcode_read_one_layer_is_short(self):
        from test_gcode_view import ORCA25

        with open(os.path.join(self.d, "o.gcode"), "w") as f:
            f.write(ORCA25)
        whole = self.ok("gcode_read", {"path": "o.gcode"})
        self.assertEqual((whole["layers"], whole["z"]), (2, [0.2, 0.4]))
        self.assertIn("machineGcode", whole)
        # One layer asked for: that, with only the two short totals.
        r = self.ok("gcode_read", {"path": "o.gcode", "layer": 2, "move": 0, "svg": True})
        self.assertEqual(set(r) - {"ms"}, {"layers", "z", "layer", "move", "svg"})
        self.assertEqual((r["layer"]["layer"], r["layer"]["z"]), (2, 0.4))
        self.assertTrue(r["svg"].endswith("-layer2-feature.svg") and os.path.isfile(r["svg"]))
        # totals: true gives the whole-print part too, nothing lost.
        t = self.ok("gcode_read", {"path": "o.gcode", "layer": 2, "totals": True})
        for k in ("slicer", "features", "tools", "events", "ranges", "legend", "machineGcode"):
            self.assertEqual(t[k], whole[k], k)
        self.assertIn("numbered from 1", self.refused("gcode_read", {"path": "o.gcode", "layer": 0}, "invalid_input")["error"]["message"])

    def test_slice_warnings_always_there(self):
        out = os.path.join(self.d, "res")
        os.makedirs(out)
        self.assertIsNone(cli.results(out)["warnings"])  # no result.json: not read
        with open(os.path.join(out, "result.json"), "w") as f:
            json.dump({"return_code": 0, "warnings": []}, f)
        self.assertEqual(cli.results(out)["warnings"], [])

    def test_every_description_says_its_reply(self):
        tools = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
        for t in tools:
            self.assertTrue("reply" in t["description"].lower() or "answers" in t["description"], t["name"])
        from orcalink import tools as T

        self.assertEqual(set(T.WORDS), {t["name"] for t in tools} - {"guide_read", "orca_status"})


@unittest.skipUnless(cli.find("orcaslicer"), "no OrcaSlicer here (AGENTLINK_ORCASLICER sets it; CI unpacks its AppImage)")
class WithOrca(Calls):
    def test_loop(self):
        stl = os.path.join(self.d, "peg.stl")
        O.write_stl(stl, M.cylinder(10, 15))
        plate = os.path.join(self.d, "plate.stl")
        O.write_stl(plate, M.box(30, 20, 4))
        r = self.ok("orca_project", {"action": "new", "files": [plate, stl], "path": "loop.3mf", "arrange": True})
        p = r["project"]
        self.assertEqual(len(r["objects"]), 2)
        self.ok("orca_project", {"action": "set", "path": p, "settings": {"sparse_infill_density": "20%"}})
        self.ok("orca_paint", {"path": p, "object": "plate.stl", "kind": "seam", "where": {"normal": [0, 0, 1]}, "state": "block"})
        self.ok("orca_project", {"action": "gcode", "path": p, "z": 2.0, "kind": "custom", "gcode": "M117 orcalink"})
        s = self.ok("orca_slice", {"path": p})
        with open(s["gcode"][0]) as f:
            self.assertIn("M117 orcalink", f.read())
        g = self.ok("gcode_read", {"path": s["gcode"][0], "layer": 3, "svg": True})
        self.assertTrue(os.path.isfile(g["svg"]))
        # The model changed: its part replaced, settings kept, sliced again.
        O.write_stl(stl, M.cylinder(10, 18))  # taller, the same footprint
        self.ok("orca_project", {"action": "replace", "path": p, "object": "peg.stl", "file": stl})
        self.ok("orca_slice", {"path": p})
        r = self.ok("orca_project", {"action": "mesh", "path": p, "object": "peg.stl", "op": "cut", "at": 7})
        self.assertEqual(len(r["objects"]), 2)
        self.ok("orca_slice", {"path": p})


if __name__ == "__main__":
    unittest.main()
