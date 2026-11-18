# SPDX-License-Identifier: LGPL-2.1-or-later
# Add-ons found by convention (orcalink/addons.py): a package with an
# orcalink_addon module adds its tools; with none, nothing is added; the
# server names no add-on in its own code.
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from orcalink import addons  # noqa: E402
from orcalink.server import build  # noqa: E402

ADDON = '''
VERSION = "9.9"
LICENSE = "MIT"


def tools(ctx):
    assert ctx["api"] == 1 and "gcode_read" in ctx["tools"]

    def hello(a):
        if not a.get("who"):
            raise ctx["ToolError"]("invalid_input", "who: a name.")
        return {"hello": a["who"]}

    return [{"name": "zz_hello", "description": "Say hello.", "inputSchema": {"type": "object", "properties": {"who": {"type": "string"}}}, "fn": hello},
            {"name": "gcode_read", "description": "a clash", "fn": hello}]
'''


class Addons(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.out = tempfile.mkdtemp()
        self.env = os.environ.get("ORCALINK_ADDONS")

    def tearDown(self):
        if self.env is None:
            os.environ.pop("ORCALINK_ADDONS", None)
        else:
            os.environ["ORCALINK_ADDONS"] = self.env
        if self.d in sys.path:
            sys.path.remove(self.d)
        sys.modules.pop("zzaddon", None)
        sys.modules.pop("zzaddon.orcalink_addon", None)
        shutil.rmtree(self.d, ignore_errors=True)
        shutil.rmtree(self.out, ignore_errors=True)

    def names(self, server):
        return [t["name"] for t in server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]]

    def test_none_installed_adds_nothing(self):
        os.environ["ORCALINK_ADDONS"] = self.d  # an empty folder
        names = self.names(build(self.out))
        self.assertNotIn("zz_hello", names)
        self.assertEqual(addons.LOADED, [])

    def test_found_by_convention(self):
        pkg = os.path.join(self.d, "zzaddon")
        os.makedirs(pkg)
        open(os.path.join(pkg, "__init__.py"), "w").close()
        with open(os.path.join(pkg, "orcalink_addon.py"), "w") as f:
            f.write(ADDON)
        os.environ["ORCALINK_ADDONS"] = self.d
        server = build(self.out)
        names = self.names(server)
        self.assertIn("zz_hello", names)
        self.assertEqual(names.count("gcode_read"), 1)  # an add-on cannot replace a tool
        r = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "zz_hello", "arguments": {}}})["result"]
        self.assertTrue(r["isError"])
        self.assertEqual(json.loads(r["content"][0]["text"])["error"]["code"], "invalid_input")
        st = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "orca_status", "arguments": {}}})["result"]
        st = json.loads(st["content"][0]["text"])
        self.assertEqual(st["addons"][0]["tools"], ["zz_hello"])

    def test_broken_addon_is_left_out(self):
        pkg = os.path.join(self.d, "zzaddon")
        os.makedirs(pkg)
        open(os.path.join(pkg, "__init__.py"), "w").close()
        with open(os.path.join(pkg, "orcalink_addon.py"), "w") as f:
            f.write("raise RuntimeError('broken')\n")
        os.environ["ORCALINK_ADDONS"] = self.d
        names = self.names(build(self.out))
        self.assertIn("gcode_read", names)
        self.assertEqual(addons.SKIPPED[0]["module"], "zzaddon.orcalink_addon")

    def zzpkg(self, parent):
        pkg = os.path.join(parent, "zzaddon")
        os.makedirs(pkg)
        open(os.path.join(pkg, "__init__.py"), "w").close()
        with open(os.path.join(pkg, "orcalink_addon.py"), "w") as f:
            f.write(ADDON)

    def test_app_addons_folder(self):
        # <app>/addons/<repository>/<package>: what FreeCAD Agent Link's
        # launcher puts there. Found with no ORCALINK_ADDONS.
        os.environ.pop("ORCALINK_ADDONS", None)
        app_addons = os.path.join(self.d, "addons")
        self.zzpkg(os.path.join(app_addons, "ZZ-Repo"))
        os.makedirs(os.path.join(app_addons, ".hidden"))
        old = addons.APP_ADDONS
        addons.APP_ADDONS = app_addons
        try:
            self.assertEqual(addons.app_dirs(), [os.path.join(app_addons, "ZZ-Repo")])
            server = build(self.out)
            self.assertIn("zz_hello", self.names(server))
            st = json.loads(server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "orca_status", "arguments": {}}})["result"]["content"][0]["text"])
            self.assertEqual([a["module"] for a in st["addons"]], ["zzaddon.orcalink_addon"])
        finally:
            addons.APP_ADDONS = old
            p = os.path.join(app_addons, "ZZ-Repo")
            if p in sys.path:
                sys.path.remove(p)

    def test_app_addons_is_beside_the_package(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(addons.__file__)))
        self.assertEqual(addons.APP_ADDONS, os.path.join(root, "addons"))
        self.assertEqual(addons.app_dirs(os.path.join(self.d, "nothing-here")), [])

    def test_agentlink_folder_is_never_searched(self):
        # A folder the agent can write (~/AgentLink) is never searched by
        # default: an add-on there would be code run without the person's OK.
        os.environ.pop("ORCALINK_ADDONS", None)
        home = os.path.join(self.d, "home")
        al = os.path.join(home, "AgentLink")
        self.zzpkg(al)
        self.zzpkg(os.path.join(al, "addons", "ZZ-Repo"))
        self.zzpkg(os.path.join(al, "orcaslicer", "addons", "ZZ-Repo"))
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = home
        try:
            dirs = addons._dirs()
            self.assertFalse([d for d in dirs if d and os.path.abspath(d).startswith(al)], dirs)
            self.assertNotIn("zzaddon.orcalink_addon", addons.found())
            self.assertNotIn("zz_hello", self.names(build(self.out)))
        finally:
            if old_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = old_home

    def test_no_addon_named_in_orcalink(self):
        here = os.path.join(os.path.dirname(__file__), "..", "orcalink")
        for root, _, files in os.walk(here):
            for n in files:
                if n.endswith(".py"):
                    with open(os.path.join(root, n), encoding="utf-8") as f:
                        self.assertNotIn("printloop", f.read().lower(), n)


if __name__ == "__main__":
    unittest.main()
