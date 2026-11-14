# SPDX-License-Identifier: LGPL-2.1-or-later
# Agent Link for OrcaSlicer: the MCP server, over stdio. Plain Python 3.9+,
# no FreeCAD. Run it as an MCP server's command:
#   python3 /path/to/orcalink_server.py [--out ~/Documents/AgentLink]
# OrcaSlicer is found where it is installed (AGENTLINK_ORCASLICER sets the
# path to its executable).
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from orcalink.server import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
