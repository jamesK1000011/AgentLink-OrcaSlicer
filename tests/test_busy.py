# SPDX-License-Identifier: LGPL-2.1-or-later
# OrcaSlicer's own window open: the command line that cannot run beside it
# answers busy and says so, never an obscure failure. A stand-in slicer (a
# small script) and a stand-in process list; no OrcaSlicer needed.
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from orcalink import cli  # noqa: E402
from orcalink.server import build  # noqa: E402
from test_orca3mf import sample  # noqa: E402

GUI = "/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"


def stand_in(folder, body):
    """An executable named OrcaSlicer that runs body (sh)."""
    p = os.path.join(folder, "OrcaSlicer")
    with open(p, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\n" + body + "\n")
    os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
    return p


class WindowOpen(unittest.TestCase):
    def test_window_found_command_lines_and_others_not(self):
        ps = "\n".join([
            f"  101 {GUI}",
            f"  102 {GUI} -psn_0_12345",
            f"  103 {GUI} --slice 0 --outputdir /tmp/x /tmp/p.3mf",
            f"  104 {GUI} --info /tmp/p.3mf",
            "  105 /usr/bin/python3 orcalink_server.py",
            f"  {os.getpid()} {GUI}",
            "garbage line",
        ])
        self.assertEqual(cli.window_open(GUI, ps), [101, 102])
        self.assertEqual(cli.window_open("/opt/orca/orca-slicer", ps), [])
        self.assertEqual(cli.window_open(None, ps), [])


class Busy(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.real_window_open = cli.window_open
        self.real_env = os.environ.get("AGENTLINK_ORCASLICER")
        cli._HELP.clear()

    def tearDown(self):
        cli.window_open = self.real_window_open
        if self.real_env is None:
            os.environ.pop("AGENTLINK_ORCASLICER", None)
        else:
            os.environ["AGENTLINK_ORCASLICER"] = self.real_env
        cli._HELP.clear()
        shutil.rmtree(self.d, ignore_errors=True)

    def slice(self, exe, timeout=30):
        p = os.path.join(self.d, "p.3mf")
        sample(p)
        return cli.slice_project("orcaslicer", p, os.path.join(self.d, "out"), timeout=timeout)

    def test_failure_with_window_open_is_busy(self):
        exe = stand_in(self.d, 'echo "Segmentation fault" >&2; exit 139')
        os.environ["AGENTLINK_ORCASLICER"] = exe
        cli.window_open = lambda e, ps=None: [4242]
        with self.assertRaises(cli.SlicerBusy) as c:
            self.slice(exe)
        self.assertIn("window is open", str(c.exception))
        self.assertIn("Nothing was changed", str(c.exception))
        self.assertIn("Segmentation fault", str(c.exception))  # the slicer's own words stay

    def test_failure_without_window_is_plain(self):
        exe = stand_in(self.d, 'echo "bad config" >&2; exit 1')
        os.environ["AGENTLINK_ORCASLICER"] = exe
        cli.window_open = lambda e, ps=None: []
        with self.assertRaises(RuntimeError) as c:
            self.slice(exe)
        self.assertNotIsInstance(c.exception, cli.SlicerBusy)
        self.assertIn("bad config", str(c.exception))

    def test_lock_words_are_busy_without_a_window(self):
        exe = stand_in(self.d, 'echo "Another instance of OrcaSlicer is already running" >&2; exit 1')
        os.environ["AGENTLINK_ORCASLICER"] = exe
        cli.window_open = lambda e, ps=None: []
        with self.assertRaises(cli.SlicerBusy) as c:
            self.slice(exe)
        self.assertIn("lock", str(c.exception))

    def test_timeout_is_said_plainly(self):
        exe = stand_in(self.d, 'case "$1" in --help) exit 0;; esac; sleep 30')
        os.environ["AGENTLINK_ORCASLICER"] = exe
        cli.window_open = lambda e, ps=None: []
        with self.assertRaises(RuntimeError) as c:
            self.slice(exe, timeout=1)
        self.assertIn("did not finish in 1 s", str(c.exception))
        cli.window_open = lambda e, ps=None: [4242]
        with self.assertRaises(cli.SlicerBusy) as c:
            self.slice(exe, timeout=1)
        self.assertIn("window is open", str(c.exception))

    def test_tools_answer_busy(self):
        exe = stand_in(self.d, "exit 1")
        os.environ["AGENTLINK_ORCASLICER"] = exe
        cli.window_open = lambda e, ps=None: [4242]
        server = build(self.d)
        sample(os.path.join(self.d, "p.3mf"))

        def call(name, args):
            r = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})["result"]
            return r.get("isError", False), json.loads(r["content"][0]["text"])

        for name, args in (("orca_slice", {"path": "p.3mf"}), ("orca_project", {"action": "arrange", "path": "p.3mf"})):
            err, r = call(name, args)
            self.assertTrue(err, r)
            self.assertEqual(r["error"]["code"], "busy", r)
            self.assertIn("window is open", r["error"]["message"])
        err, r = call("orca_status", {})
        self.assertFalse(err, r)
        self.assertIs(r["windowOpen"], True)


if __name__ == "__main__":
    unittest.main()
