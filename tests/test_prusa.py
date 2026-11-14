# SPDX-License-Identifier: LGPL-2.1-or-later
# PrusaSlicer's setup-driven runner beside the other slicers' command lines:
# found where the person says, and run through cli.slice_with like the rest.
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from orcalink import cli, prusa  # noqa: E402


class Prusa(unittest.TestCase):
    def test_found_by_the_setting(self):
        old = os.environ.get("AGENTLINK_SLICER")
        os.environ["AGENTLINK_SLICER"] = "/opt/prusa/prusa-slicer"
        try:
            self.assertEqual(prusa.find_slicer(), "/opt/prusa/prusa-slicer")
            self.assertEqual(cli.find("prusaslicer"), "/opt/prusa/prusa-slicer")
        finally:
            if old is None:
                os.environ.pop("AGENTLINK_SLICER", None)
            else:
                os.environ["AGENTLINK_SLICER"] = old

    def test_missing_says_how(self):
        old = os.environ.pop("AGENTLINK_SLICER", None)
        try:
            if prusa.find_slicer():
                self.skipTest("PrusaSlicer is on this computer")
            with self.assertRaises(FileNotFoundError) as c:
                cli.slice_with("prusaslicer", os.path.join(tempfile.mkdtemp(), "a.stl"), "a.gcode", {})
            self.assertIn("install PrusaSlicer", str(c.exception))
        finally:
            if old is not None:
                os.environ["AGENTLINK_SLICER"] = old


if __name__ == "__main__":
    unittest.main()
