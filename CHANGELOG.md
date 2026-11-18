# Changelog

All notable changes to Agent Link for OrcaSlicer. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- With OrcaSlicer's own window open, a command line that could not run beside
  it failed with the slicer's last lines only (or hung to the time limit). The
  calls that run OrcaSlicer now answer `busy`: its window is open (or another
  copy holds its lock), nothing was changed, ask the person to close it when
  they are done there. A time limit reached says so. `orca_status` gives
  `windowOpen`.
- `orca_paint where` with a key that is not normal, within, box, below or above
  (say `{ face: "top" }`) painted every triangle of the part. It is refused now,
  with the keys there are; a normal or box of the wrong shape is refused too.
- `orca_slice export: svg` with a negative `layerHeight` never reached the top
  of the part and ran until memory was gone. `layerHeight` is 0.01 to 10 mm.
- A call that left out `object`, `plate` or `slot` answered `failed: 'object'`.
  Each action now says what it needs and where to read it; wrong shapes for
  `box`, `points`, `profile`, `normal`, `axis`, `at` and `size` are refused in
  words; a missing `file` or saved `bundle` answers not_found.
- `part_add` and `replace` read a relative `file` from the server's working
  folder; it is in the output folder now, as every other path is.
- A missing project path was reported as "is not an OrcaSlicer project".
- `orca_slice` exports drc, drcs, svg and obj with a plate the project does not
  have say so, instead of "nothing printable".
- Presets: a preset's `include` files were ignored. OrcaSlicer 2.5 keeps a Bambu
  Lab printer's start, end, layer-change, filament-change and time-lapse G-code
  in included template files, so a "Bambu Lab H2D 0.4 nozzle" was written with
  the generic start G-code of `fdm_machine_common` (purge lines at X10 Y20 to
  Y200) and an older Bambu end G-code. Includes are now layered between the
  parent and the preset's own keys, as OrcaSlicer does; a missing include stops
  with its name. Filaments get their per-nozzle lists from their includes too.
- Presets: a parent name that several vendors' folders hold
  (`fdm_machine_common`, `fdm_process_common` …, with other values in each) is
  now taken from the child's own vendor folder, then OrcaSlicer's filament
  library, as OrcaSlicer looks it up; it was the first found, often another
  vendor's.
- `gcode_read` counted the start G-code's purge lines as a first layer (26
  layers where OrcaSlicer wrote 25, first z 0.28), read no height or width from
  OrcaSlicer 2.5's `; LAYER_HEIGHT:` and `; LINE_WIDTH:` tags, took the end
  G-code's `M104 S0` into the temperature range and Bambu's `T255` unload as a
  tool, and read another fan (`M106 P2`) as the part fan. The printer's own
  start and end G-code is now kept out of layers, features, ranges, tools and
  events and reported apart as `machineGcode`.
- `orca_calibrate` temperature: `howToRead` names both ends and the block count;
  a `start` below `end` is refused (the tower's labels get cooler going up).
- `orca_slice` always answers `warnings` ([] when OrcaSlicer said none), and
  `orcaMs`, the time its command line ran.

### Changed

- Every tool's description says its inputs, numbering (objects, parts, plates
  and slots from 1; instances, texture slots and moves from 0), limits,
  how long it can take and each field of the reply. The guide has a section
  "Numbering, limits and time".
- `gcode_read` numbers layers from 1, as OrcaSlicer does in its G-code ("layer
  num/total_layer_count") and on its preview's slider: the last layer's number
  is the layer count orca_slice answers. Layer 0 is refused.
- `gcode_read` with `layer`, `z`, `move` or `svg` answers that and only the
  whole print's `layers` and `z` (`totals: true` adds the rest): for the live
  test's call, 2201 characters became 887.

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
