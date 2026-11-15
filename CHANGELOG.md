# Changelog

All notable changes to Agent Link for OrcaSlicer. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

The first release, 0.1.0, is being prepared.

### Added

- OrcaSlicer driven headless over MCP: projects made and changed at every
  level, painting, calibration prints, slicing and export by OrcaSlicer's own
  command line, and the G-code read back layer by layer.
- A companion MCP server (`orcalink_server.py`) and a Claude Desktop extension
  (`mcpb/`) that finds Python and OrcaSlicer on a Mac and keeps itself up to
  date.
- The orca group for Agent Link for FreeCAD: bodies into projects, painting by
  FreeCAD face, and walls, infill and layers back for the strength check.
- CI runs the bridge with Workshop's Make add-on beside it, for the strength
  read-back and slicing with chosen settings.
- Release preparation: a beginner's README with a generated tool list, checks
  for the extension's manifest, licence headers checked for every file, and
  this changelog.
- README: a privacy statement and how to uninstall; the extension's
  manifest names its repository, documentation, support page and keywords.

- Texture displacement: `orca_paint` kind `texture` writes the layer stack,
  images and per-triangle masks exactly as OrcaSlicer's Texture
  Displacement panel saves them, checked byte for byte against the panel's
  own serialiser. `orca_slice` bakes the relief as it slices, by OrcaSlicer's
  `--bake-texture-displacement` (the agent-cli build); colour layers give
  relief only. A slicer without the option slices flat and says so.

### Changed

- The bridge reads records and filament densities from Agent Link, now that
  AddonKit is retired.
- `protocol.py` and the filament density table say where they come from.
