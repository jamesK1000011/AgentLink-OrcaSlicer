# SPDX-License-Identifier: LGPL-2.1-or-later
"""Add-ons for this server, found by convention and never named here.

An add-on is a package on the Python path (or in a folder that the
ORCALINK_ADDONS variable lists, separated as PATH is) that holds a module
orcalink_addon.py. That module has tools(ctx): a list of tools as dicts
{name, description, inputSchema, fn, changes?, group?}. ctx gives
out_dir, tools (this server's own tool functions by name), ToolError and
api (1). The module may also give VERSION, LICENSE and CREDIT, which
orca_status shows.

Without an add-on, nothing is loaded and no tool is added: an add-on that
is not installed costs no tokens. An add-on that fails to load is left
out and the reason goes to stderr; the server still starts.
"""
import importlib
import os
import sys

from .protocol import Tool, ToolError

API = 1
MODULE = "orcalink_addon"
# The add-ons loaded: [{module, version, license, credit, tools}].
LOADED = []
# The add-ons left out, with why.
SKIPPED = []


def _dirs():
    env = os.environ.get("ORCALINK_ADDONS", "")
    extra = [os.path.expanduser(d) for d in env.split(os.pathsep) if d.strip()]
    for d in extra:
        if os.path.isdir(d) and d not in sys.path:
            sys.path.append(d)
    return extra + [d for d in sys.path if d not in extra]


def found():
    """Module names of the add-ons on the path, in path order."""
    out = []
    for d in _dirs():
        if not d or not os.path.isdir(d):
            continue
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for pkg in sorted(names):
            if pkg.startswith((".", "_")) or not pkg.isidentifier() or pkg == "orcalink":
                continue
            if os.path.isfile(os.path.join(d, pkg, MODULE + ".py")) and os.path.isfile(os.path.join(d, pkg, "__init__.py")):
                n = f"{pkg}.{MODULE}"
                if n not in out:
                    out.append(n)
    return out


def tools(out_dir, own):
    """The add-ons' tools as Tool objects. own: {name: fn} of this
    server's tools (an add-on may call them; it may not replace them)."""
    del LOADED[:]
    del SKIPPED[:]
    result = []
    taken = set(own)
    ctx = {"out_dir": out_dir, "tools": dict(own), "ToolError": ToolError, "api": API}
    for name in found():
        try:
            mod = importlib.import_module(name)
            specs = list(mod.tools(ctx))
        except Exception as e:  # noqa: BLE001 - one add-on must not stop the server
            SKIPPED.append({"module": name, "why": f"{type(e).__name__}: {e}"})
            sys.stderr.write(f"OrcaSlicer Agent Link: add-on {name} left out — {e}\n")
            continue
        names = []
        for sp in specs:
            n = sp.get("name")
            if not n or n in taken:
                SKIPPED.append({"module": name, "tool": n, "why": "no name, or the name of a tool that is already there"})
                continue
            taken.add(n)
            names.append(n)
            result.append(Tool(n, sp.get("description", ""), sp.get("inputSchema") or {"type": "object", "properties": {}},
                               sp["fn"], changes=bool(sp.get("changes")), group=sp.get("group") or name.split(".")[0]))
        LOADED.append({"module": name, "version": getattr(mod, "VERSION", None), "license": getattr(mod, "LICENSE", None),
                       "credit": getattr(mod, "CREDIT", None), "tools": names})
    return result
