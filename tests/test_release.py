# SPDX-License-Identifier: LGPL-2.1-or-later
# Release readiness without FreeCAD: the README's tool list is current, the
# licence of every file is stated (a REUSE-style check, for when the `reuse`
# tool is not installed), the Claude extension's manifest is complete, and the changelog has an Unreleased section.
import fnmatch
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import gen_readme_tools  # noqa: E402

MAIN = "LGPL-2.1-or-later"
SOURCE = (".py", ".js", ".mjs", ".sh")


def tracked():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return [f for f in out.splitlines() if os.path.exists(os.path.join(ROOT, f))]


def reuse_annotations():
    """(globs, licence) pairs from REUSE.toml, read without tomllib."""
    out, globs = [], None
    for line in open(os.path.join(ROOT, "REUSE.toml"), encoding="utf-8"):
        m = re.match(r"\s*path\s*=\s*(.+)", line)
        if m:
            globs = re.findall(r'"([^"]+)"', m.group(1))
        m = re.match(r'\s*SPDX-License-Identifier\s*=\s*"([^"]+)"', line)
        if m and globs is not None:
            out.append((globs, m.group(1)))
            globs = None
    return out


def _match(path, glob):
    rx = re.escape(glob).replace(r"\*\*", "\0").replace(r"\*", "[^/]*").replace("\0", ".*")
    return re.fullmatch(rx, path) is not None


class Readme(unittest.TestCase):
    def test_tool_list_is_current(self):
        text = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
        self.assertEqual(gen_readme_tools.render(text), text, "run python3 tools/gen_readme_tools.py")

    def test_tool_list_not_empty(self):
        self.assertGreater(gen_readme_tools.block().count("\n| `"), 0)


class Licences(unittest.TestCase):
    def test_every_file_has_a_licence(self):
        files = tracked()
        if files is None:
            self.skipTest("not a git checkout")
        notes = reuse_annotations()
        missing, wrong = [], []
        for f in files:
            if f == "LICENSE" or f.startswith("LICENSES/"):
                continue
            with open(os.path.join(ROOT, f), "rb") as fh:
                head = fh.read(600).decode("utf-8", "replace")
            m = re.search(r"SPDX-License-Identifier:\s*([^\s*>-][^\s>]*)", head)
            if m:
                ids = [m.group(1)]
            else:
                ids = [lic for globs, lic in notes if any(_match(f, g) for g in globs)]
                if f.endswith(SOURCE) or not ids:
                    missing.append(f)
                    continue
            for i in ids:
                for part in re.split(r"\s+(?:AND|OR|WITH)\s+", i):
                    if part != MAIN and not os.path.exists(os.path.join(ROOT, "LICENSES", part + ".txt")):
                        wrong.append(f"{f}: {part}")
        self.assertEqual(missing, [], "no SPDX header or REUSE.toml entry")
        self.assertEqual(wrong, [], "licence text not in LICENSES/")

    def test_main_licence_is_lgpl(self):
        head = open(os.path.join(ROOT, "LICENSE"), encoding="utf-8").read(400)
        self.assertIn("LESSER GENERAL PUBLIC LICENSE", head)
        self.assertIn("Version 2.1", head)

    def test_no_bytecode_tracked(self):
        files = tracked()
        if files is None:
            self.skipTest("not a git checkout")
        self.assertEqual([f for f in files if "__pycache__" in f or f.endswith(".pyc")], [])


class Changelog(unittest.TestCase):
    def test_unreleased_section(self):
        text = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
        self.assertRegex(text, r"(?m)^## \[?Unreleased\]?")


class Manifest(unittest.TestCase):
    """mcpb/manifest.json: the Claude Desktop extension's packaging metadata."""

    @classmethod
    def setUpClass(cls):
        import json

        cls.m = json.load(open(os.path.join(ROOT, "mcpb", "manifest.json"), encoding="utf-8"))

    def test_required_fields(self):
        for key in ("manifest_version", "name", "display_name", "version", "description", "author", "license", "server"):
            self.assertTrue(self.m.get(key), key)
        self.assertTrue(self.m["author"].get("name"))
        self.assertNotIn("email", self.m["author"])
        self.assertEqual(self.m["license"], MAIN)
        self.assertRegex(self.m["version"], r"^\d+\.\d+\.\d+$")

    def test_version_matches_package(self):
        src = open(os.path.join(ROOT, "orcalink", "__init__.py"), encoding="utf-8").read()
        self.assertIn('VERSION = "%s"' % self.m["version"], src)

    def test_server_entry_point(self):
        srv = self.m["server"]
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "mcpb", srv["entry_point"])))
        self.assertTrue(srv["mcp_config"]["command"])
        for key in srv["mcp_config"].get("env", {}).values():
            name = re.match(r"\$\{user_config\.(\w+)\}", key)
            if name:
                self.assertIn(name.group(1), self.m.get("user_config", {}))

    def test_build_ships_the_server(self):
        files = open(os.path.join(ROOT, "FILES"), encoding="utf-8").read().split()
        for f in ("orcalink_server.py", "orcalink/server.py", "orcalink/tools.py"):
            self.assertIn(f, files)


if __name__ == "__main__":
    unittest.main()
