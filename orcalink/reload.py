# SPDX-License-Identifier: LGPL-2.1-or-later
# New code without a restart of Claude. The extension's launcher
# (mcpb/server/index.js) starts this server from a folder named by its
# version (~/.config/orcaslicer-agentlink/app-<commit>) and keeps the version
# to serve in state.json there ("current"). A newer version is put there by
# the launcher's own update (at a start) or by FreeCAD Agent Link's
# agentlink_update. Between two calls the server compares "current" with its
# own version (ORCALINK_VERSION). When they differ and the new folder loads,
# it starts itself again in place (os.execve): the process, and so the pipes
# to Claude, stay. Claude does not send initialize again, so its parameters
# and any input already read go to the new process in a hand-off file.
import base64
import json
import os
import re
import subprocess
import sys
import tempfile

SHA = re.compile(r"[0-9a-f]{40}")
ENTRY = "orcalink_server.py"


def cache_dir(env=None):
    env = os.environ if env is None else env
    return os.path.expanduser(env.get("ORCALINK_CACHE") or os.path.join("~", ".config", "orcaslicer-agentlink"))


class Lines:
    """Lines read from a file descriptor with a buffer of our own, so that
    what was read but not used yet can go to the new process (pending)."""

    def __init__(self, fd, pending=b""):
        self.fd = fd
        self.buf = bytearray(pending or b"")

    def readline(self):
        while b"\n" not in self.buf:
            chunk = os.read(self.fd, 65536)
            if not chunk:
                out = bytes(self.buf)
                self.buf.clear()
                return out.decode("utf-8", "replace")
            self.buf += chunk
        i = self.buf.index(b"\n") + 1
        out = bytes(self.buf[:i])
        del self.buf[:i]
        return out.decode("utf-8", "replace")

    def pending(self):
        return bytes(self.buf)


class Reloader:
    """Watches for a newer version between calls (check) and starts it in
    place (go). env: the environment (os.environ); out_dir: the server's
    output folder; loads(dir): True when the folder's server builds (the
    same check the launcher makes before a version is used)."""

    def __init__(self, out_dir, env=None, loads=None, execve=None):
        self.env = os.environ if env is None else env
        self.out_dir = out_dir
        self.own = self.env.get("ORCALINK_VERSION") or ""
        self.init = None
        self.refused = set()
        self.loads = loads or _loads
        self.execve = execve or os.execve
        self._seen = None

    def enabled(self):
        """Only under the extension's launcher, with updates on: a checkout
        (ORCALINK_FROM, version local) is never swapped."""
        if self.env.get("ORCALINK_FROM") or self.own in ("", "local"):
            return False
        return str(self.env.get("ORCALINK_UPDATE", "")).lower() != "false"

    def newer(self):
        """(folder, version) of a version to serve instead of this one, or
        None. Cheap when nothing changed: state.json is read again only when
        its time changes."""
        if not self.enabled():
            return None
        p = os.path.join(cache_dir(self.env), "state.json")
        try:
            t = os.path.getmtime(p)
        except OSError:
            return None
        if self._seen is not None and self._seen[0] == t:
            return self._seen[1]
        found = None
        try:
            with open(p, encoding="utf-8") as f:
                st = json.load(f)
            cur = st.get("current")
            if isinstance(cur, str) and SHA.fullmatch(cur) and cur != self.own and cur not in (st.get("bad") or []) and cur not in self.refused:
                d = os.path.join(cache_dir(self.env), "app-" + cur)
                if os.path.isfile(os.path.join(d, ENTRY)):
                    found = (d, cur)
        except (OSError, ValueError, AttributeError):
            found = None
        self._seen = (t, found)
        return found

    def seen(self, msg):
        """Told each message read: initialize's parameters are kept."""
        if isinstance(msg, dict) and msg.get("method") == "initialize":
            self.init = msg.get("params") or {}

    def readline(self, reader):
        """The next line, read between two calls; when a newer version is
        there by then, that line goes to it with the rest of the input (go):
        the call that came after an update is answered by the new code."""
        line = reader.readline()
        if line and self.newer() is not None:
            reader.buf[0:0] = line.encode("utf-8")
            self.check(reader)
            return reader.readline()  # not started (it did not load): served here
        return line

    def check(self, reader):
        """Start the newer version in place when there is one and it loads.
        Returns only when nothing was started."""
        got = self.newer()
        if got is None:
            return False
        d, version = got
        if not self.loads(d):
            self.refused.add(version)
            self._seen = None
            return False
        self.go(d, version, reader.pending() if reader is not None else b"")
        return True

    def go(self, d, version, pending):
        fd, hand = tempfile.mkstemp(prefix="handoff-", suffix=".json", dir=_handoff_dir(self.env))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"init": self.init, "pending": base64.b64encode(pending).decode("ascii"), "from": self.own}, f)
        env = dict(self.env)
        env.update({"ORCALINK_VERSION": version, "ORCALINK_HANDOFF": hand, "ORCALINK_RELOADED_FROM": self.own or "bundled"})
        try:
            sys.stdout.flush()
            sys.__stdout__.flush()
        except Exception:  # noqa: BLE001
            pass
        exe = sys.executable
        self.execve(exe, [exe, "-I", os.path.join(d, ENTRY), "--out", self.out_dir], env)


def _handoff_dir(env):
    d = cache_dir(env)
    try:
        os.makedirs(d, exist_ok=True)
        return d
    except OSError:
        return None


def _loads(d):
    """The folder's server imports and builds its tools (the launcher's own
    check before it uses a version)."""
    try:
        r = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); from orcalink.server import build; build(sys.argv[2])",
                            d, tempfile.mkdtemp(prefix="orcalink-check-")], capture_output=True, timeout=60)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def take_handoff(env=None):
    """What the process before this one handed over ({init, pending (bytes),
    from}), read once and removed; {} when it was not started so."""
    env = os.environ if env is None else env
    p = env.get("ORCALINK_HANDOFF")
    if not p:
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            h = json.load(f)
    except (OSError, ValueError):
        return {}
    finally:
        try:
            os.remove(p)
        except OSError:
            pass
    try:
        h["pending"] = base64.b64decode(h.get("pending") or "")
    except (ValueError, TypeError):
        h["pending"] = b""
    return h if isinstance(h, dict) else {}
