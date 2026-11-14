# SPDX-License-Identifier: LGPL-2.1-or-later
# What Agent Link for FreeCAD loads from this package when both are
# installed: the orca tools on FreeCAD's bodies (orca_project, orca_paint,
# orca_calibrate, orca_slice, gcode_read). Agent Link finds this module by
# convention (a package on the path holding agentlink_families) and never
# names it; without Agent Link for FreeCAD it is never loaded.
from . import fam_freecad

FAMILIES = [fam_freecad]
CREDIT = None
LICENSE = "LGPL-2.1-or-later"
AGENTLINK_API = ">=1,<2"


def _guides():
    # The FreeCAD loop's guide beside Agent Link's own (guide_read { topic: "orca" }).
    import os

    from agentlink import tools as al_tools

    reg = getattr(al_tools, "register_guides", None)
    if reg is not None:
        reg(os.path.join(os.path.dirname(os.path.abspath(__file__)), "freecad_guides"))


try:
    _guides()
except Exception:  # noqa: BLE001 — an Agent Link without the hook: the tools still load
    pass
