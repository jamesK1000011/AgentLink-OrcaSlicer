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
    "fuzzy skin, colour and texture displacement; orca_calibrate builds OrcaSlicer's calibration prints; orca_slice slices or exports by its command line; gcode_read "
    "reads the G-code back layer by layer. Relative paths go in the output folder (orca_status). guide_read { topic: \"orca\" } has each action's arguments. "
    "Starting a print is the person's call."
)


def build(out_dir):
    def guide_read(a):
        topic = (a.get("topic") or "orca").replace("/", "")
        p = os.path.join(GUIDES, topic + ".md")
        if not os.path.isfile(p):
            raise ToolError("not_found", f"topic {a.get('topic')!r}: there is no such guide here; the topics are: {', '.join(sorted(os.path.splitext(n)[0] for n in os.listdir(GUIDES)))}.")
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
        Tool("guide_read", "The written guide to these tools. topic: orca (the only one here, and the default): the loop from project to slice to reading the G-code back, every orca_project action with its arguments, how bed types and filaments go together, and the traps. Read it once before the first orca_project call that is more than info or set. The reply: topic, text. An unknown topic is refused with the topics there are.",
             obj({"topic": {"type": "string", "description": "orca (the default)."}}), guide_read),
        Tool("orca_status", "What this server has to work with; call it first. No inputs. The reply: version (this server's), commit (when started from the extension), out (the output folder, where every relative path goes and files are written), orcaslicer (the path of the OrcaSlicer executable found, or null), orcaVersion, bambustudio (its path or null), and note when OrcaSlicer is not found (install it, or set AGENTLINK_ORCASLICER to its executable). Without OrcaSlicer, orca_project still reads and changes projects, orca_paint paints, gcode_read reads and orca_slice exports drc, drcs, svg, amf and obj; making a project (new), slicing, arrange, orient, cli, the other exports and orca_calibrate need it. Changes nothing.",
             obj({}), orca_status),
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
