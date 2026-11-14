# SPDX-License-Identifier: LGPL-2.1-or-later
# The standalone server: the OrcaSlicer tools, a guide, and where OrcaSlicer is.
import argparse
import os
import sys

from . import VERSION
from . import cli
from . import tools as T
from .protocol import Server, Tool, ToolError, serve_lines

GUIDES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guides")

INSTRUCTIONS = (
    "OrcaSlicer, headless: orca_project reads and changes a project (.3mf) at every level the window reaches; orca_paint paints supports, seam, "
    "fuzzy skin and colour; orca_calibrate builds OrcaSlicer's calibration prints; orca_slice slices or exports by its command line; gcode_read "
    "reads the G-code back layer by layer. Relative paths go in the output folder (orca_status). guide_read { topic: \"orca\" } has each action's arguments. "
    "Starting a print is the person's call."
)


def build(out_dir):
    def guide_read(a):
        topic = (a.get("topic") or "orca").replace("/", "")
        p = os.path.join(GUIDES, topic + ".md")
        if not os.path.isfile(p):
            raise ToolError("not_found", f"topic: {', '.join(sorted(os.path.splitext(n)[0] for n in os.listdir(GUIDES)))}.")
        with open(p, encoding="utf-8") as f:
            return {"topic": topic, "text": f.read()}

    def orca_status(a):
        exe = cli.find("orcaslicer")
        out = {"version": VERSION, **({"commit": os.environ["ORCALINK_VERSION"][:7]} if os.environ.get("ORCALINK_VERSION") else {}), "out": out_dir, "orcaslicer": exe, "bambustudio": cli.find("bambustudio")}
        if exe:
            from . import presets

            out["orcaVersion"] = presets.orca_version(exe)
        else:
            out["note"] = "OrcaSlicer not found: install it, or set AGENTLINK_ORCASLICER to its executable."
        return out

    obj = T.obj
    tools = T.tools(lambda: out_dir) + [
        Tool("guide_read", "How to use these tools, by topic (orca).", obj({"topic": {"type": "string"}}), guide_read),
        Tool("orca_status", "Which OrcaSlicer (and Bambu Studio) is here, its version, and the output folder.", obj({}), orca_status),
    ]
    return Server("orcaslicer-agentlink", VERSION, tools, instructions=INSTRUCTIONS)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Agent Link for OrcaSlicer: an MCP server over stdio.")
    ap.add_argument("--out", default=os.environ.get("AGENTLINK_OUT", "~/Documents/AgentLink"), help="where relative paths and outputs go")
    args = ap.parse_args(argv)
    out_dir = os.path.expanduser(args.out)
    os.makedirs(out_dir, exist_ok=True)
    server = build(out_dir)
    out = sys.stdout
    sys.stdout = sys.stderr  # stray prints never reach the protocol

    def write(line):
        out.write(line if line.endswith("\n") else line + "\n")
        out.flush()

    serve_lines(server, sys.stdin.readline, write)
    return 0
