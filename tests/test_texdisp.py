# SPDX-License-Identifier: LGPL-2.1-or-later
# Texture displacement written as OrcaSlicer's Texture Displacement gizmo
# saves it (orcalink/texdisp.py): the layer stack's JSON byte for byte against
# the C++ serialiser's own output (data/texture-displacement-golden.json), and
# orca_paint kind texture round-tripped through the sample project.
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from orcalink import cli, orca3mf as O, texdisp as T  # noqa: E402
from orcalink.server import build  # noqa: E402
from test_orca3mf import sample  # noqa: E402

GOLDEN = os.path.join(os.path.dirname(__file__), "data", "texture-displacement-golden.json")


def GOLDEN_STACK():
    """The stack the golden file was made from, set member by member as the C++ harness set it."""
    layers = [
        T.layer(0, name="Knurl", path="Knurl.png", path_in_3mf="Metadata/texture_displacement/3_0.png"),
        T.layer(2, name='Bricks "old"', path="/tmp/b.png", path_in_3mf="Metadata/texture_displacement/3_2.png", depth_mm=0.8, tiling_scale=6,
                rotation_deg=45, offset=[1.5, -2], invert=True, midlevel=0.5, smoothing=0.25, edge_smoothing=True, edge_smoothing_amount=0.3,
                tile_method=1, projection_method=1, blend_mode=1, color_enabled=True),
        T.layer(5, name="View", projection_method=4, view_project_right=[0, 0.6, 0.8], view_project_up=[0, -0.8, 0.6], lscm_seam_edges=[(1, 4), (2, 7)],
                islands=[[0.5, 1, 15, 1.25]], island_groups=[0, -1], lscm_uv_overrides=[(-3, 0.1, 0.2)], blend_mode=4, tile_enabled=False,
                lscm_seam_angle_deg=45, island_padding_mm=0.75),
    ]
    opts = T.options(smooth_enabled=True, smooth_strength=0.5, smooth_iterations=3, active_slot=2, v2_refine_mm=0.35, v2_max_triangles_k=400,
                     pipeline_v2=False, color_mix_count=4)
    return layers, opts


def png(w=4, h=4, depth=8, ctype=0):
    """A small PNG, made here (no image library)."""
    per = {0: 1, 2: 3, 6: 4}.get(ctype, 1) * max(depth // 8, 1)
    raw = b"".join(b"\0" + bytes((x * 60 + y * 20) % 256 for x in range(w * per)) for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, ctype, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class Format(unittest.TestCase):
    def test_matches_the_gizmos_serialiser(self):
        with open(GOLDEN, encoding="utf-8") as f:
            golden = json.load(f)["json"]
        self.assertEqual(T.to_json(*GOLDEN_STACK()), golden)
        # Read back as texture_displacement_layers_from_json() reads it, and written again unchanged.
        self.assertEqual(T.to_json(*T.from_json(golden)), golden)

    def test_reader_rules(self):
        # cpp:5903 a slot outside 0..7 rejects the document; 5886 active_slot clamps; a wrong-typed scalar keeps its default.
        with self.assertRaises(T.Malformed):
            T.from_json('{"layers":[{"slot":8}]}')
        with self.assertRaises(T.Malformed):
            T.from_json('{"layers":[{"slot":0,"offset":["a",1]}]}')
        layers, opts = T.from_json('{"options":{"active_slot":12,"smooth_strength":"x"},"layers":[{"slot":1,"depth_mm":"deep","projection_method":5}]}')
        self.assertEqual(opts["active_slot"], 7)
        self.assertEqual(opts["smooth_strength"], 0.3)
        self.assertEqual(layers[0]["depth_mm"], 0.4)
        self.assertEqual(layers[0]["projection_method"], 4)  # std::clamp(projection, 0, 4)

    def test_png_rule(self):
        self.assertEqual(T.png_check(png(5, 3)), (5, 3, False))
        self.assertTrue(T.png_check(png(ctype=2))[2])
        self.assertTrue(T.png_check(png(ctype=6))[2])
        for bad in (png(depth=16), png(ctype=4), b"GIF89a" + b"\0" * 40):
            with self.assertRaises(ValueError):
                T.png_check(bad)


class Tool(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.server = build(self.d)
        self.p = os.path.join(self.d, "p.3mf")
        sample(self.p)
        self.img = os.path.join(self.d, "dots.png")
        with open(self.img, "wb") as f:
            f.write(png(8, 8))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def call(self, args):
        r = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "orca_paint", "arguments": {"path": "p.3mf", "object": "box.stl", "kind": "texture", **args}}})["result"]
        return r.get("isError", False), json.loads(r["content"][0]["text"])

    def ok(self, args):
        err, r = self.call(args)
        self.assertFalse(err, r)
        return r

    def refused(self, args, code="invalid_input"):
        err, r = self.call(args)
        self.assertTrue(err, r)
        self.assertEqual(r["error"]["code"], code, r)

    def test_round_trip(self):
        r = self.ok({"texture": {"image": "dots.png", "depth": 0.6, "tileSize": 5, "rotation": 30, "invert": True, "edgeFade": 0.25, "mirror": True},
                     "where": {"normal": [0, 0, 1]}})
        self.assertEqual((r["slot"], r["triangles"]), (0, 2))
        self.assertEqual(r["layer"]["edgeFade"], 0.25)
        pr = O.Project(self.p)
        o = pr.object("box.stl")
        p = o["parts"][0]
        with zipfile.ZipFile(self.p) as z:
            names = z.namelist()
            settings = z.read(O.SETTINGS).decode()
            base = T.DIR + p["id"]
            self.assertIn(base + "_0.png", names)
            self.assertEqual(z.getinfo(base + "_0.png").compress_type, zipfile.ZIP_STORED)
            with open(self.img, "rb") as f:
                self.assertEqual(z.read(base + "_0.png"), f.read())
            stack = z.read(base + ".json").decode()
        # The part names its JSON (bbs_3mf.cpp:8300), and the JSON is what the serialiser writes for this stack.
        self.assertIn(f'key="texture_displacement" value="{base}.json"', settings)
        want = T.layer(0, name="dots", path=self.img, path_in_3mf=base + "_0.png", depth_mm=0.6, tiling_scale=5, rotation_deg=30, invert=True,
                       edge_smoothing=True, edge_smoothing_amount=0.25, tile_method=1)
        self.assertEqual(stack, T.to_json([want], T.options()))
        _, tris, attrs = pr.mesh(p)
        self.assertEqual(attrs["paint_texture_0"].count("4"), 2)
        self.assertEqual(pr.info()["objects"][0]["parts"][0]["textures"][0]["name"], "dots")
        self.assertNotIn("texture_displacement", pr.info()["objects"][0]["parts"][0].get("settings", {}))

        # A second layer takes the next free slot; editing keeps the paint; removing drops its paint and image.
        r = self.ok({"texture": {"image": "dots.png", "blend": "subtract", "projection": "cylindrical"}, "where": {"below": 1}})
        self.assertEqual(r["slot"], 1)
        r = self.ok({"texture": {"slot": 0, "depth": 1.2}, "textureOptions": {"smooth": {"strength": 0.5, "passes": 4}, "pipeline": "classic"}})
        self.assertEqual((r["layer"]["depth"], r["triangles"]), (1.2, 2))
        layers, opts = O.Project(self.p).textures("box.stl")
        self.assertEqual([l["slot"] for l in layers], [0, 1])
        self.assertEqual((opts["smooth_enabled"], opts["smooth_iterations"], opts["pipeline_v2"], opts["active_slot"]), (True, 4, False, 0))
        self.ok({"texture": {"slot": 1, "remove": True}})
        with zipfile.ZipFile(self.p) as z:
            self.assertNotIn(base + "_1.png", z.namelist())
        self.assertNotIn("paint_texture_1", O.Project(self.p).mesh(p)[2])
        self.ok({"texture": {"slot": 0, "remove": True}})
        with zipfile.ZipFile(self.p) as z:
            self.assertFalse([n for n in z.namelist() if n.startswith(T.DIR)])
            self.assertNotIn("texture_displacement", z.read(O.SETTINGS).decode())

    def test_slice_bakes_the_texture(self):
        # orca_slice hands a textured project to OrcaSlicer with --bake-texture-displacement, which bakes the
        # relief as the panel's Bake does; a project without a texture stack is sliced as before.
        self.assertFalse(O.Project(self.p).has_textures())
        self.assertEqual(self.sliced_with(), [])
        r = self.ok({"texture": {"image": "dots.png", "depth": 0.6}, "where": {"normal": [0, 0, 1]}})
        self.assertIn("orca_slice bakes the relief", r["note"])
        self.assertTrue(O.Project(self.p).has_textures())
        self.assertEqual(self.sliced_with(), ["--bake-texture-displacement"])
        # A slicer without the option slices flat, and says so.
        res = self.slice(supports=False)
        self.assertIn("--bake-texture-displacement", res["warning"])

    def slice(self, supports=True):
        """orca_slice against a stand-in OrcaSlicer that writes an empty G-code; gives the result and the
        command line it was run with."""
        seen = []

        def run(args, timeout, cwd=None):
            seen.append(args)
            with open(os.path.join(cwd, "plate_1.gcode"), "w") as f:
                f.write("; stand-in\n")
            return None

        with mock.patch.object(cli, "find", return_value="/stand-in/orca-slicer"), \
                mock.patch.object(cli, "supports", side_effect=lambda exe, opt: supports and opt == "--bake-texture-displacement"), \
                mock.patch.object(cli, "_run", side_effect=run), mock.patch.object(cli, "results", return_value={}):
            r = self.server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "orca_slice", "arguments": {"path": "p.3mf", "keep": False}}})["result"]
        out = json.loads(r["content"][0]["text"])
        self.assertFalse(r.get("isError", False), out)
        out["_args"] = seen[0]
        return out

    def sliced_with(self):
        return [a for a in self.slice()["_args"] if a == "--bake-texture-displacement"]

    def test_refusals(self):
        self.refused({"texture": {"depth": 1}})  # a new layer needs a picture
        self.refused({"texture": {"image": "dots.png", "depth": 20}})
        self.refused({"texture": {"image": "dots.png", "tileSize": 0.1}})
        self.refused({"texture": {"image": "dots.png", "projection": "model_uv"}})
        self.refused({"texture": {"image": "dots.png", "projection": "view"}})
        self.refused({"texture": {"image": "dots.png", "projection": "view", "view": {"right": [1, 0, 0], "up": [2, 0, 0]}}})
        self.refused({"texture": {"slot": 3, "depth": 1}})
        self.refused({"texture": {"image": "missing.png"}}, "not_found")
        with open(os.path.join(self.d, "deep.png"), "wb") as f:
            f.write(png(depth=16))
        self.refused({"texture": {"image": "deep.png"}})
        for _ in range(T.SLOTS):
            self.ok({"texture": {"image": "dots.png"}, "where": {"above": 4}})
        self.refused({"texture": {"image": "dots.png"}})  # eight layers is the most a part holds


if __name__ == "__main__":
    unittest.main()
