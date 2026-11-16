# Changelog

All notable changes to Agent Link for OrcaSlicer. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- `orca_project new` with bodies named each object after the wrong body when Orca
  gave its objects back in another order ("Box" and "Box lid" swapped). The
  body of each object now comes from the file Orca records it was loaded from
  (`source_file`), kept in the project as `Metadata/agentlink_bodies.json`;
  `info` reports it, and actions that find the body themselves (paint by faces,
  `lay_flat`, `part_add { of }`, `strength`) use it. Without the map only whole
  names match, never a body whose name merely starts the same. Two bodies
  whose file names would clash get one file each.

## [0.1.0] - 2026-11-16

The first release.

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

- The Claude extension has an icon (`mcpb/icon.png`, 512 px, drawn from
  `mcpb/icon.svg`; original artwork), named in the manifest and packed by
  `mcpb/build.sh`.
- `orca_project new` chooses a bed type every filament goes on (its bed
  temperature there above 0): `bed_type` when given and it fits, else the
  printer's `default_bed_type`, else Textured PEI first. The answer lists
  `bedTypes` that would work.
- `orca_slice`: a slice stopped by "<plate> does not support filament <n>"
  names the bed types that would work and how to set one.

### Fixed

- The person's own filament presets (a user preset on a system one) no longer
  stop OrcaSlicer's command line with "ConfigOptionVector::set_at():
  Assigning from an empty vector": a list the user preset leaves empty keeps
  the inherited one, a list shorter than the preset's per-variant one is
  padded with its last value, and no empty list is written.
- `orca_project set` scope plate key `bed_type` took no effect: it wrote a
  key OrcaSlicer does not read. It now writes the plate's own `bed_type` and
  the project's `curr_bed_type` (other plates keep theirs), reads the value
  back from the saved file, and is an error if it did not take.
- New projects no longer default to Cool Plate whatever the filament, which
  made PETG and others fail to slice.

### Changed

- The bridge reads records and filament densities from Agent Link, now that
  AddonKit is retired.
- `protocol.py` and the filament density table say where they come from.
