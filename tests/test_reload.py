# SPDX-License-Identifier: LGPL-2.1-or-later
# New code without a restart of Claude (orcalink/reload.py, live 68): the
# server started by the extension's launcher from a version folder takes up
# the version the launcher's state.json names, between two calls, in place
# (the process and its pipes stay). The new process answers the next call
# with no initialize sent again. Plain Python: two copies of this checkout
# stand in for two versions; no OrcaSlicer needed.
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from orcalink import reload  # noqa: E402

A, B = "a" * 40, "b" * 40


def cache_with(*versions, current=None):
    d = tempfile.mkdtemp(prefix="orcalink-cache-")
    for v in versions:
        dst = os.path.join(d, "app-" + v)
        os.makedirs(dst)
        shutil.copy(os.path.join(ROOT, "orcalink_server.py"), dst)
        shutil.copytree(os.path.join(ROOT, "orcalink"), os.path.join(dst, "orcalink"), ignore=shutil.ignore_patterns("__pycache__"))
    state(d, current or versions[0])
    return d


def state(d, current, **more):
    p = os.path.join(d, "state.json")
    with open(p + ".tmp", "w") as f:
        json.dump({"current": current, **more}, f)
    os.replace(p + ".tmp", p)
    # A new time even within the same second.
    t = time.time() + (os.path.getmtime(p) - time.time()) + 1
    os.utime(p, (t, t))


class Lines(unittest.TestCase):
    def test_lines_and_what_is_left(self):
        r, w = os.pipe()
        os.write(w, b'{"a": 1}\n{"b": 2}\n{"c"')
        os.close(w)
        lines = reload.Lines(r, b'{"z": 0}\n')
        self.assertEqual(lines.readline(), '{"z": 0}\n')
        self.assertEqual(lines.readline(), '{"a": 1}\n')
        self.assertEqual(lines.pending(), b'{"b": 2}\n{"c"')
        self.assertEqual(lines.readline(), '{"b": 2}\n')
        self.assertEqual(lines.readline(), '{"c"')
        self.assertEqual(lines.readline(), "")


class Newer(unittest.TestCase):
    def test_found_and_not(self):
        d = cache_with(A, B, current=A)
        env = {"ORCALINK_CACHE": d, "ORCALINK_VERSION": A}
        rl = reload.Reloader("/tmp", env=env)
        self.assertIsNone(rl.newer())
        state(d, B)
        self.assertEqual(rl.newer(), (os.path.join(d, "app-" + B), B))
        state(d, B, bad=[B])
        self.assertIsNone(rl.newer())
        state(d, "c" * 40)  # no such folder
        self.assertIsNone(rl.newer())
        # A checkout, or updates turned off: never swapped.
        state(d, B)
        for extra in ({"ORCALINK_FROM": "/x"}, {"ORCALINK_UPDATE": "false"}, {"ORCALINK_VERSION": "local"}):
            self.assertIsNone(reload.Reloader("/tmp", env={**env, **extra}).newer(), extra)
        # The bundled copy moves on to a fetched one.
        self.assertEqual(reload.Reloader("/tmp", env={**env, "ORCALINK_VERSION": "bundled"}).newer()[1], B)

    def test_a_version_that_does_not_load_is_left(self):
        d = cache_with(A, B, current=B)
        rl = reload.Reloader("/tmp", env={"ORCALINK_CACHE": d, "ORCALINK_VERSION": A}, loads=lambda p: False,
                             execve=lambda *a: self.fail("started"))
        self.assertFalse(rl.check(None))
        self.assertIsNone(rl.newer())

    def test_hand_off(self):
        d = cache_with(A, B, current=B)
        got = []
        rl = reload.Reloader("/out", env={"ORCALINK_CACHE": d, "ORCALINK_VERSION": A}, loads=lambda p: True, execve=lambda *a: got.append(a))
        rl.seen({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
        r, w = os.pipe()
        os.write(w, b'{"id": 2}\n{"id": 3}\n')
        os.close(w)
        lines = reload.Lines(r)
        line = rl.readline(lines)
        exe, argv, env = got[0]
        self.assertEqual(argv[1:], ["-I", os.path.join(d, "app-" + B, "orcalink_server.py"), "--out", "/out"])
        self.assertEqual((env["ORCALINK_VERSION"], env["ORCALINK_RELOADED_FROM"]), (B, A))
        h = reload.take_handoff(env)
        self.assertEqual(h["init"], {"protocolVersion": "2025-06-18"})
        self.assertEqual(h["pending"], b'{"id": 2}\n{"id": 3}\n')
        self.assertFalse(os.path.exists(env["ORCALINK_HANDOFF"]))
        self.assertEqual(reload.take_handoff(env), {})
        # The stand-in execve returned: the line is served here after all.
        self.assertEqual(line, '{"id": 2}\n')


class InPlace(unittest.TestCase):
    """The real thing: a server process from version A, state.json moved to
    B between two calls, the next call answered by B in the same process."""

    def test_next_call_answered_by_the_new_version(self):
        d = cache_with(A, B, current=A)
        out = tempfile.mkdtemp()
        env = {**os.environ, "ORCALINK_CACHE": d, "ORCALINK_VERSION": A, "ORCALINK_UPDATE": "true", "PYTHONUNBUFFERED": "1"}
        env.pop("ORCALINK_FROM", None)
        env.pop("ORCALINK_HANDOFF", None)
        env.pop("ORCALINK_RELOADED_FROM", None)
        p = subprocess.Popen([sys.executable, "-I", os.path.join(d, "app-" + A, "orcalink_server.py"), "--out", out],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)
        self.addCleanup(lambda: p.poll() is None and p.kill())

        def ask(mid, method, params=None):
            p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}) + "\n")
            p.stdin.flush()
            return json.loads(p.stdout.readline())

        def status(mid):
            r = ask(mid, "tools/call", {"name": "orca_status", "arguments": {}})
            return json.loads(r["result"]["content"][0]["text"])

        self.assertEqual(ask(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})["result"]["serverInfo"]["name"], "orcaslicer-agentlink")
        pid = p.pid
        first = status(2)
        self.assertEqual(first["commit"], A[:7])
        self.assertNotIn("reloadedFrom", first)
        state(d, B)
        second = status(3)
        self.assertEqual((second["commit"], second["reloadedFrom"]), (B[:7], A[:7]))
        self.assertEqual(p.pid, pid)
        # tools/list still answers, with no initialize sent again.
        self.assertTrue(ask(4, "tools/list")["result"]["tools"])
        p.stdin.close()
        self.assertEqual(p.wait(30), 0)


if __name__ == "__main__":
    unittest.main()
