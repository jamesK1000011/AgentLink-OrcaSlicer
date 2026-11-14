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
