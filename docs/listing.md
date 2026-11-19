<!-- SPDX-License-Identifier: LGPL-2.1-or-later -->
# Listing text for Agent Link for OrcaSlicer

The text for the Claude extension (`mcpb/manifest.json`) and other MCP
directories. Written in ASD-STE100. Version 1.0.0.

## Name

- Name: Agent Link for OrcaSlicer
- Claude extension name: `orcaslicer-agentlink`
- Repository: https://github.com/jamesK1000011/AgentLink-OrcaSlicer
- Licence: LGPL-2.1-or-later. OrcaSlicer itself is AGPL-3.0 and runs as
  its own program.

There is no MCP Registry entry (`server.json`) yet. The registry needs a
published package: a PyPI package, or the release's `.mcpb` file with its
SHA-256. Make the entry after the release file exists.

## Short text (100 characters or fewer)

Use OrcaSlicer from an agent without its window: projects, paint, slice and read the G-code back.

## Long text

Agent Link for OrcaSlicer is an MCP server for OrcaSlicer. An AI agent
changes an OrcaSlicer project file (.3mf) at every level: objects, plates,
settings and per-layer G-code. It paints parts (supports, seams, fuzzy skin,
colours, textures), slices with OrcaSlicer's own command line, exports, and
reads the sliced G-code back as the preview shows it. It also makes
OrcaSlicer's calibration prints.

It works on the files, not on OrcaSlicer's open window. It needs a Python 3
and OrcaSlicer. It does not need FreeCAD.

With Agent Link for FreeCAD installed too, the tools work from FreeCAD
bodies. There, risky G-code goes to you for approval (`approve_code`, kind
`gcode`). When this server runs alone, it refuses risky G-code.

Not affiliated with or endorsed by the OrcaSlicer project.

## Keywords

OrcaSlicer, 3D printing, slicer, G-code, 3MF, MCP, Model Context Protocol,
calibration, AI agent, Claude

## Privacy note

- The server has no telemetry. It opens no network port. It talks to the
  agent only over its own pipes.
- What leaves your computer is your MCP client's own traffic: what the agent
  reads goes to your client's AI provider, under that provider's terms.
- Your models, projects and G-code stay on your computer, in `~/AgentLink`
  (or the output folder that you choose). The extension's log is in
  `~/Library/Logs/OrcaSlicer Agent Link`. No log is sent anywhere.
- The network is used only when you ask for it: the Claude extension's
  update from GitHub (**Keep it up to date**, which you can turn off), and
  the fetch of OrcaSlicer's printer presets for a version number. These
  requests send nothing about you or your files.

## Tools

`orca_status`, `guide_read`, `orca_project`, `orca_paint`,
`orca_calibrate`, `orca_slice`, `gcode_read`. Add-ons that you install can
add more (`tools_generated` in the manifest).
