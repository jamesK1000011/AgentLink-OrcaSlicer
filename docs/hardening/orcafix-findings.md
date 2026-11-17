# Agent Link for OrcaSlicer: fixes from the first live run (17 Nov 2026)

The 16-call test model ran on a Mac with OrcaSlicer 2.5.0 (printer "Bambu Lab H2D 0.4 nozzle", process "0.20mm
Standard @BBL H2D", filament "Bambu PLA Basic @BBL H2D", a 20 x 10 x 5 mm box). Every accept and refuse matched. This
file covers the faults found in the answers. The evidence was the batch of live answers, the G-code OrcaSlicer wrote
and the three merged presets the server wrote. Nothing here ran on OrcaSlicer again: the fixes are proven by tests and
by reading the evidence and OrcaSlicer 2.5.0's own source (tag v2.5.0: its profiles, `PresetBundle.cpp`,
`GCodeProcessor.cpp`, `PrintConfig.cpp`, `Plater.cpp`).

Tests: `python3 -m pytest -q tests`: 136 passed, 19 skipped (127 passed and 1 failed before; the skipped ones need
OrcaSlicer or FreeCAD). The failure before was the licence check: `docs/hardening/*` had no licence entry. It is now in
REUSE.toml.

"Line" below means the line in the code before this change (commit 1786514).

## F4 (safety): the printer's start G-code was the wrong one

**What was wrong.** The merged H2D machine preset had a short generic start G-code (`G0 Z20 F9000` … purge lines at
X10 Y20 to Y200 … `M109 S205`) and an old Bambu end G-code (dated 20230428). OrcaSlicer 2.5.0's real H2D preset has
a long H2D start G-code (dated 20260605, about 580 lines) and an H2D end G-code (dated 2026/07/29).

**Cause.** `orcalink/presets.py` line 109 to 131 (`resolve`) follows `inherits` only. OrcaSlicer 2.5 also has an
`include` key: the H2D preset includes six template files that hold its start, end, layer-change, time-lapse,
wrapping-detection and filament-change G-code. The resolver ignored them, so these keys came from the parents
(`fdm_bbl_3dp_002_common`, `fdm_machine_common`). OrcaSlicer itself puts the parent first, then each included file in
order, then the preset's own keys (`PresetBundle.cpp`, the loop over `entry.includes`). The filament has an include
too (`fdm_filament_template_direct_dual_e3d`): its per-nozzle lists were lost.

A second, hidden fault: line 115 and 118 take the first file of a name across all vendor folders. Base names such as
`fdm_machine_common` are in 66 vendor folders, and 65 of them hold other values than BBL's. With more than one vendor
fetched, "Afinia" or "Anker" sorts before "BBL" and its values would be taken. OrcaSlicer looks a parent up in the
child's own vendor first, then in `OrcaFilamentLibrary`. On the Mac only BBL was there, so this did not happen in this
run (every non-include key matched BBL's own files).

**Effect on the print.** The live G-code shows it: the print ran at 205 °C (hard-coded in the generic start G-code)
where the filament says 220 °C; OrcaSlicer adds no temperature line of its own when the start G-code already has one.
The H2D-specific start steps (nozzle checks, its own homing, purge and calibration) were not there. **Do not print
`plate_1.gcode` from this run, or any project made with Bambu presets before this fix** (the project file keeps the
wrong start G-code: make it again with `orca_project new`, or apply the presets again with `orca_project presets`).

**By-hand check.** I resolved the three presets by hand from OrcaSlicer v2.5.0's profile files, as OrcaSlicer does,
and compared every key with the evidence files:

- Machine: differ in `machine_start_gcode`, `machine_end_gcode`, `layer_change_gcode`, `time_lapse_gcode`,
  `wrapping_detection_gcode` (empty in the evidence), `change_filament_gcode`. Also `include` (written through, should
  not be), and as expected by design: `nozzle_volume_type` (added by write_profiles), `bed_exclude_area` and
  `head_wrap_detect_zone` (empty lists, dropped on purpose).
- Process: no key differs.
- Filament: 32 per-nozzle keys were 1 long where OrcaSlicer has 3 (`filament_extruder_variant` and the others from the
  include). Three of them also had another value: `filament_preheat_temperature_delta` 0 (should be 10),
  `long_retractions_when_ec` 0 (should be 1), `retraction_distances_when_ec` 0 (should be 10). Also
  `compatible_printers_condition` (set on purpose) and `include`.

**Change.** `resolve` now layers each included file between the parent and the preset's own keys. A missing include
is refused with its name (left out, a printer would silently get a generic start G-code). Parents and includes are
taken from the child's own vendor folder, then `OrcaFilamentLibrary`, then the first found. `include` is no longer
written into the merged files. After the change, the resolver's output equals the by-hand resolution for all three
presets (only the two empty-list machine keys differ, as before).

**How sure.** Very sure that this was the fault and that the fix gives OrcaSlicer's own values: by-hand resolution of
the v2.5.0 profiles, OrcaSlicer's loader code, the evidence start G-code equal byte for byte to `fdm_machine_common`'s,
and four new tests (`tests/test_presets.py`, class Includes) that fail on the old code and pass now. Not tested: a slice
by OrcaSlicer's command line with the long H2D start G-code and 3-long filament lists (OrcaSlicer's own system presets
have both, so it should work).

**Check live.**
1. `orca_project new { files: [box], path: "alink-rest.3mf", machine: "Bambu Lab H2D 0.4 nozzle", process: "0.20mm
   Standard @BBL H2D", filament: "Bambu PLA Basic @BBL H2D" }`, then read `alink-rest-work/presets/agentlink-machine.json`:
   `machine_start_gcode` starts `;===== machine: H2D` and holds `date: 20260605`; `machine_end_gcode` starts
   `;========== H2D end ==========`; no `include` key. `agentlink-filament.json`: `filament_extruder_variant` has 3
   entries, `long_retractions_when_ec` is ["1", "1", "1"].
2. `orca_slice { path: "alink-rest.3mf" }`: answers G-code (not failed). Its first lines after
   `EXECUTABLE_BLOCK_START` include `;===== machine: H2D`, and there is no `Draw the first line`.
3. `gcode_read { path: "alink-rest-sliced.3mf" }`: `ranges.temperature` [220, 220].

## F1 gcode_read: wrong layer count, first z, missing height and width, end G-code in the ranges

**Causes.**
- `gcode_view.py` line 215: the first extrusion made a layer when none was open, so the start G-code's purge lines at
  Z0.28 (before the first `; CHANGE_LAYER`) became a layer: 26 layers, first z 0.28.
- Line 25 and 26: only `;WIDTH:` and `;HEIGHT:` were read. OrcaSlicer 2.5 writes `; LINE_WIDTH:` and `; LAYER_HEIGHT:`
  (its reserved tags in `GCodeProcessor.cpp`), so height and width were null.
- Line 175 to 188: the end G-code's `M104 S0` went into the last layer's temperatures (range from 0), and Bambu's
  `T255` (unload) into tools and events.
- Line 166 to 170 (found here): every `M106` set the part fan, also `M106 P2` (another fan). Layer 2 showed 74.9 %
  (P2 S191) where the part fan was 78.8 % (S201). OrcaSlicer reads only M106 with no P, or P1.

**Changes.**
- In a file that marks its layers, a layer starts only at a mark. Files without marks work as before.
- `LINE_WIDTH` and `LAYER_HEIGHT` are read.
- OrcaSlicer's `; MACHINE_START_GCODE_END` and `; MACHINE_END_GCODE_START` bound the printer's own G-code. It is still
  replayed (position, heat, tool) but is kept out of layers, features, ranges, tools and events. The whole-print reply
  reports it apart as `machineGcode { start, end }`: each with `lines` [first, last], `filamentMm`, `timeS`,
  `temperature`, `tools`. So nothing is lost: the purge's 30 mm of filament (OrcaSlicer's statistics call it
  "Custom") is there.
- The part fan is M106 with no P, or P1.
- **Numbering, settled:** layers are numbered from 1, as OrcaSlicer numbers them in its G-code ("layer
  num/total_layer_count: 1/25") and on its preview's slider. The last layer's number equals `layers` and equals
  orca_slice's `layers`. `layer: 0` is refused; -1 is the last; past the top gives the last. Moves stay from 0. The
  SVG file name uses the layer number. Description, both guides and CHANGELOG say so.

On the live G-code the reader now answers: layers 25, z [0.2, 5.0], tools [0], events [], height [0.2, 0.2], width
[0.383, 0.502], temperature [205, 205] (205 only because of F4), speed [43.867, 300], acceleration [500, 8000],
layer_time [3.904, 5.245], no "Custom" feature, machineGcode start lines [768, 810] with filamentMm 30, end lines
[3706, 3766] with tools [255] and temperature [0]. Layer 2: z 0.4, height 0.2, fan [78.8], width [0.417, 0.45].

**How sure.** Tests on a cut-down copy of the live G-code (`tests/test_gcode_view.py`, class Orca25) and a run on the
live file itself. Sure.

**Check live.** `gcode_read { path: "alink-rest-sliced.3mf" }`: layers 25 (same as orca_slice), z [0.2, 5.0], tools
[0], ranges.height [0.2, 0.2], ranges.width not null, ranges.temperature [220, 220] after F4, machineGcode present.
`gcode_read { path: "alink-rest-sliced.3mf", layer: 1 }`: layer.z 0.2. `{ layer: 25 }`: z 5.0. `{ layer: 0 }`: refused
invalid_input.

## F2 gcode_read: whole-file totals repeated beside one layer

**Cause.** `tools.py` line 1517 and 1518: the whole-print summary and legend were always in the reply.

**Change.** With `layer`, `z`, `move` or `svg`, the reply is `layers`, `z` (two short totals that place the layer) and
what was asked (`layer`, `move`, `svg`). `totals: true` adds the whole-print part (slicer, features, tools, events,
ranges, legend, machineGcode), the same as a call with only `path`. Nothing is lost: one more call, or `totals`, gives
the rest. Description and tests updated (`tests/test_tools.py`, test_gcode_read_one_layer_is_short).

**Size of call 11's reply** (`{ layer: 2, move: 0, svg: true }`, run here on the live G-code, compact JSON as the server
sends it): before 2201 characters, after 887 (60 % less). With `totals: true`: 2311 (it now also has machineGcode).
The live reply was 2482 characters as stored in the batch file (with spaces).

**How sure.** Test and measurement. Sure.

**Check live.** `gcode_read { path: "alink-rest-sliced.3mf", layer: 2, move: 0, svg: true }`: keys only layers, z,
layer, move, svg, ms.

## F3 orca_calibrate temperature: howToRead named only one end

**Cause.** `calibrate.py` line 96.

**Change.** It now reads: "7 blocks of 10 mm, from 230 °C at the bottom to 200 °C at the top, 5 °C cooler each block
up: pick …". Found here too: a `start` below `end` was accepted, but the model's labels get cooler going up (the trim
mirrors OrcaSlicer's own `Plater::calib_temp`, hottest block at the bottom), so the printed blocks would not match their
labels. It is now refused, saying to give the hotter one as start. The reply also says `printer` when the minimal
generic printer was used (the model's call 15 expected that to be visible). Tests in `tests/test_calibrate.py`.

**How sure.** Test; the labels point is from reading OrcaSlicer's code. Sure.

**Check live.** `orca_calibrate { kind: "temperature", params: { start: 230, end: 200 }, path: "alink-rest-cal.3mf" }`:
howToRead contains "7 blocks", "230 °C at the bottom", "200 °C at the top"; `printer` present. Then
`orca_project info { path: "alink-rest-cal.3mf" }`: objects[0].size z should be 70 mm (7 blocks). The live reply had no
`model` field, which the code adds only when it trimmed the tower: if the size is not 70, the trim did not take.
`{ params: { start: 200, end: 230 } }`: refused invalid_input.

## F5 orca_slice: warnings and ms

**Warnings.** `cli.py` line 393: `warnings` was in the reply only when OrcaSlicer listed some, so the model's call 9
could not tell "none" from "not read". Now always there after a G-code slice: [] when OrcaSlicer's result.json has
none, null when there was no result.json. Test: test_slice_warnings_always_there.

**ms.** `ms` is measured around the whole tool call (`protocol.py` line 288 to 321), and the slice runs inside the call
(`subprocess.run`, it waits), so it counts the OrcaSlicer run. 279 ms is plausible on that Mac: call 1, which also runs
OrcaSlicer's command line, took 550 ms, and the G-code header's time (01:15:49) is within the batch (started
01:15:48). To make it plain, the reply now has `orcaMs`, the command line's own run time. Code reading; not run with
OrcaSlicer here.

**Check live.** `orca_slice { path: "alink-rest.3mf" }`: `warnings` present (likely []), `orcaMs` present and below `ms`.

## F6 Every other expectation against the live answers

| Call | Result | Note |
|---|---|---|
| 1 orca_status | not in the batch file | nothing to compare |
| 2 new | match | the runner used the name alink-hub, not alink-rest (all calls); bedType Textured PEI Plate; presets written as copies (evidence presets/) |
| 3 info | match | size [20, 10, 5], 12 triangles, presets and filament as given, sliced false |
| 4 new, missing file | match | |
| 5 paint seam | match | triangles 2 |
| 6 paint where.face | match | |
| 7 info object | match | painted [seam], layer_height 0.2, wall_loops 2, sparse_infill_density 15% |
| 8 svg export | match | 10 layers, 1 ms |
| 9 drc plate 9 | match | message exact |
| 10 slice | tool fault (F5) | no `warnings` key; the rest matched (25 layers, 0.79 g, 261 mm, 2m 50s, sliced) |
| 11 gcode_read | tool faults (F1, F4) | 26 layers, z 0.28, height and width null, temperature from 0 and 205 not the filament's 220, tool 255 |
| 12 gcode_read layer 2 | wrong expectation (now), tool faults (F1, F2) | see corrected text below |
| 13 view colour | match | |
| 14 not sliced | match | |
| 15 calibrate | tool fault (F3) and wrong expectation | objects is a list of names, not a count; nothing said "minimal generic printer" (now `printer`) |
| 16 step 3 | match | |

**Corrected expectation texts** (for the model file; the main session edits it):

- Call 10 (orca_slice): add "warnings (a list: [] when OrcaSlicer said none); orcaMs (OrcaSlicer's run, within ms)".
- Call 11 (gcode_read, whole): "layers the same count as call 9 (25); z [0.2, 5.0] (the first layer's height, the
  top); slicer (the header's values); features with 'Outer wall' among them, each with lengthMm, filamentMm,
  timeShare, and no 'Custom' (the purge is in machineGcode); tools [0]; events []; ranges with height [0.2, 0.2],
  width not null, temperature [220, 220] (<FILAMENT>'s nozzle_temperature) and speed up to <PROCESS>'s fastest;
  legend for view 'feature'; machineGcode { start, end } (end tools [255]: Bambu's unload)".
- Call 12 (gcode_read layer 2): "layers 25 and z [0.2, 5.0] and nothing else of the whole print (no slicer, features,
  ranges, legend); layer { layer 2, z 0.4 (the second layer: layers count from 1 as OrcaSlicer numbers them), height
  0.2, timeS, features (width not null), moves over 0 }; move { move 0, of, kind, from, to, speed, feature, line,
  gcode }; svg: a path beside the G-code ending -layer2-feature.svg, and the file is there".
- Call 15 (orca_calibrate): "project ends alink-rest-cal.3mf, kind 'temperature', objects ['temperature_tower.drc'],
  howToRead naming 7 blocks, 230 °C at the bottom and 200 °C at the top, 5 °C apart; printer (the minimal generic
  printer: no profiles given, the person's presets are not read and not written); next naming orca_slice. It only makes
  the file: nothing is sliced or printed".

## The nine earlier fixes and the "not verified" list (orca-findings.md), against this run

Earlier fixes now verified live: **1** (orca_paint `where.face` refused, call 6), **6** (plate 9 refused with the plate
count, call 9), **9** in part (the "not sliced" refusal, call 14, and the view list, call 13). Call 4 also verified
that `new { files }` reads a relative path from the output folder (part of fix 4's rule). Not exercised live: 2
(negative layerHeight), 3 (missing object/plate/slot), 4 (`part_add`/`replace` file), 5 (missing project path), 7
(gcode_read of a missing .3mf), 8 (paint colour state).

"Not verified" items:

- Command-line flags. **Verified by the run:** `--slice`, `--outputdir`, `--export-3mf` (the sliced 3MF was written),
  `--load-settings`, `--load-filaments`, `--arrange` (call 2 made the project with the presets; the G-code's own
  settings name all three presets) and `--export-statistics` (statistics came back). **Verified by OrcaSlicer
  v2.5.0's source** (each is defined in `PrintConfig.cpp`): `--orient`, `--export-stl`, `--export-stls`,
  `--export-settings`, `--export-slicedata`, `--info`, `--inspect-mesh`, `--inspect-paint`, the relayout options
  (`allow_rotations`, `ensure_on_bed`, `avoid_extrusion_cali_region`, `allow_multicolor_oneplate`, `uptodate`,
  `min_save`, `convert_unit`, `allow_newer_file`, `skip_modified_gcodes`, `align_to_y_axis`, `repair`,
  `ground_largest_face`, `clone_objects`, `repetitions`, `scale`, `rotate`, `rotate_x`, `rotate_y`,
  `ground_face_normal`, `ground_face_point`) and the slice options (`enable_timelapse`, `allow_mix_temp`, `no_check`,
  `load_defaultfila`, `skip_objects`, `mtcpp`, `mstpp`, `load_filament_ids`). So they are upstream, not the fork's
  only. **Not upstream:** `--bake-texture-displacement` (the agent-cli fork only; the code already asks `--help`).
- 3MF fields. **Verified:** `curr_bed_type` (the G-code's settings say `curr_bed_type = Textured PEI Plate`, as the
  server set it); the project's preset names. **Still not verified:** seam paint as OrcaSlicer reads it (the top face
  has no seam to move), layer ranges, custom G-code per layer, brim ears, texture layers.
- Time. Measured live: `new` 550 ms, `orca_slice` 279 ms (a 25-layer box), `orca_calibrate` 1652 ms, the rest 1 to 14
  ms. Large files are still not measured.
- `presets.orca_version` on the Mac: not verified (orca_status is not in the batch file); the G-code header says
  OrcaSlicer 2.5.0, and the presets matched the v2.5.0 tag's files.

## Not done, and risks

- Bambu Studio presets go through the same resolver. If Bambu Studio's profiles use `include` the fix covers them too;
  not checked (no Bambu Studio source here).
- An included file is applied with all its keys. OrcaSlicer applies only the keys that differ from its built-in
  defaults. The same for every v2.5.0 template (they have no parent of their own); a future template with a parent
  could differ.
- A per-nozzle list that a preset gives shorter than the machine's nozzle count is still padded only when the parent's
  list has that count (as before this change).
- The calibration tower refuses `start` below `end` now: a caller that relied on it gets a refusal.
- `gcode_read` layer numbers moved from 0-based to 1-based: a caller that asked `layer: 0` is refused, and any other
  number now means the layer one lower than before.
