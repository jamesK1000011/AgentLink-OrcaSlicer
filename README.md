# Agent Link for OrcaSlicer

OrcaSlicer, driven headless by an AI agent over the Model Context Protocol
(MCP). The agent reads and changes OrcaSlicer projects (`.3mf`) at every level
the slicer's window reaches, slices and exports them with OrcaSlicer's own
command line, and reads the G-code back layer by layer. It is plain Python
with no FreeCAD needed.

[FreeCAD Agent Link](https://github.com/jamesK1000011/FreeCAD-AgentLink) uses
it for its design loop when both are installed: bodies go into the project,
faces are painted by name, and walls, infill and layers come back for the
strength check.

## What it does

- **orca_project**: make a project from model files (STL, OBJ, 3MF, STEP and
  more). Change settings for the project, a filament, an object, a part, a
  layer range or a plate, and every value is checked against OrcaSlicer's own
  table. Add modifiers, negative parts, and support blockers or enforcers.
  It also handles instances, plates, per-layer G-code (pause, colour change,
  custom), variable layer height, brim ears, filaments and flushing, presets,
  arrange and orient, and mesh tools (cut, cut grid, split, merge, mirror,
  fix, smooth).
- **orca_paint**: paint supports, seam, fuzzy skin or colour on the triangles
  you choose by direction, box or height.
- **orca_calibrate**: build OrcaSlicer's calibration prints from its own test
  models (temperature, pressure advance, retraction, flow, max flow, VFA,
  input shaping, cornering).
- **orca_slice**: slice a project, or export STL, OBJ, AMF, Draco (DRC), solid
  slices as SVG, settings, slice data or 3MF.
- **gcode_read**: read the result the way the preview shows it, with totals,
  a legend for each view, one layer, a single move with its G-code line, an
  SVG of a layer, or the toolpaths as an OBJ.

Starting a print is always the person's call.

## Install

You need Python 3.9 or newer and OrcaSlicer. Point an MCP client at the
server:

```json
{
  "mcpServers": {
    "orcaslicer": {
      "command": "python3",
      "args": ["/path/to/OrcaSlicer-AgentLink/orcalink_server.py", "--out", "~/Documents/AgentLink"]
    }
  }
}
```

OrcaSlicer is found where it is installed. To use another copy, set
`AGENTLINK_ORCASLICER` to its executable. Bambu Studio is found the same way,
with `AGENTLINK_BAMBUSTUDIO`.

## Tests

```
python3 -m unittest discover -s tests
```

The end-to-end tests run when OrcaSlicer is present. CI runs Python 3.9
without a slicer, and Python 3.12 with the latest OrcaSlicer AppImage.

## Licence

LGPL-2.1-or-later. OrcaSlicer itself is AGPL-3.0. This project runs
OrcaSlicer as a separate program and reads and writes its files. No
OrcaSlicer code, labels or help text are copied here. The settings table in
`orcalink/data/orca-options.json` holds only keys, types and limits.
