# AgentLink-OrcaSlicer: hardening findings (orca tools, 7) — 16 Nov 2026

Nothing here ran on OrcaSlicer (it is not on the build machine) or on FreeCAD. The server itself is plain Python and did
run here: every action that needs no OrcaSlicer was called through the MCP server on the repo's sample project, including
220 deliberately wrong calls. Tests: `python3 -m pytest -q` 128 passed, 19 skipped (109 before; the skipped ones need
OrcaSlicer or FreeCAD).

There is no OrcaSlicer source or documentation among the references, so the command line and the 3MF format were checked
only against this repo's own code comments, guide and tests. Everything about OrcaSlicer's own behaviour is listed under
"Not verified".

## Bugs fixed (each proven by running the server here)

1. orca_paint `where` with an unknown key (`{ face: "top" }`, `{ z: 5 }`) selected **every** triangle and painted the
   whole part with no warning (meshgen.pick ignores keys it does not know). Now refused with the keys there are; `within`
   alone, a `normal` or `box` of the wrong shape, and a non-number `below` / `above` are refused too; a `box` given
   corner-reversed is put in order instead of matching nothing.
2. orca_slice `export: svg` with a negative `layerHeight` looped for ever (orca3mf.export_svg steps z by the height until
   it passes the top) and the process was killed for memory here. A tiny positive height did the same slowly. Now
   0.01 to 10 mm, refused otherwise.
3. 38 calls answered `orca_project failed: 'object'` (or `'plate'`, `'slot'`, "list index out of range", a raw ValueError
   text): any action missing `object`, `plate`, `slot`; `box` / `points` / `profile` / `normal` of the wrong length;
   `cut` with a bad `axis` or `at`; `cut_grid` with a non-list `size`; `instance_to_object` on an object with one
   instance; `presets` with an unknown `bundle`. Each now refuses by name with what is allowed and where to read it.
4. `part_add { file }` and `replace { file }` read a relative path from the server's working folder, while `path`,
   `new { files }` and `object_add { file }` use the output folder. Now the output folder, with not_found when missing
   (it was `failed: [Errno 2]`). `emboss { svg }` the same.
5. A missing or absent project path was wrapped as "<name> is not an OrcaSlicer project: …" with code invalid_input;
   it is now path_of's own refusal (invalid_input for no path, not_found for no file).
6. `orca_slice` exports drc / drcs / svg / obj with a `plate` the project lacks answered `failed: nothing printable`;
   now invalid_input with the plate count.
7. `gcode_read` of a `.3mf` that does not exist crashed in zipfile (`failed: [Errno 2]`); now not_found, naming orca_slice.
8. orca_paint `kind: color` with a non-number `state` answered "invalid literal for int()"; now says a filament slot.
9. Refusals reworded to say the next step: not sliced, plate out of range in a sliced file, no such G-code file, no
   OrcaSlicer for arrange / orient / cli, unknown guide topic.

## Per tool

| Tool | Checked against | Wrong and fixed | Not verified | Description |
|---|---|---|---|---|
| orca_project | tools.py act(), orca3mf.Project (index bases, limits), cli.make_project / relayout, presets.py, guide | 3, 4, 5 above | see below: CLI flags, bed-type rules, 3MF fields | rewritten: file-not-window warning, numbering, every action with arguments, limits (200 instances, 50 x 50 grid, 400 pieces, 200 copies), what needs OrcaSlicer, force rules, reply fields |
| orca_paint | tools.orca_paint, texture_paint, meshgen.pick, texdisp.RANGES / SLOTS, orca3mf.PAINT | 1, 8 | paint encoding as OrcaSlicer reads it; a colour slot above the filament count is still accepted (OrcaSlicer's own rule not known) | rewritten: where semantics, adds vs replace vs clear, texture layer and options with ranges, that relief needs the bake, reply |
| orca_calibrate | calibrate.plan (every kind's params and defaults) | nothing | the models' paths under calib/ per OrcaSlicer version; the G-code lines per firmware flavour | rewritten: defaults per kind, profiles, that a minimal printer means little, howToRead |
| orca_slice | cli.slice_project, export_project, inspect, results, SLICE_FLAGS / SLICE_VALUES, timeouts (900 / 600 / 300 s) | 2, 6 | every flag below | rewritten: where files go, reply fields, options list, time and what happens when the client gives up, which exports need OrcaSlicer |
| gcode_read | gcode_view.summary / layer / move / VIEWS (run here on a hand-written G-code) | 7 | parsing of real OrcaSlicer G-code (only CI's WithOrca test covers it) | rewritten: layer and move from 0, clamping past the end, every reply field, cost on large files |
| guide_read | server.py | refusal names the topics | nothing | rewritten |
| orca_status | server.py, cli.find | nothing | presets.orca_version on the Mac's build | rewritten: what works without OrcaSlicer |

Index fields: these tools are Python `Tool(...)` definitions, not a tools.json, so there is nowhere for `workbench` /
`commands` (and none apply: they are not FreeCAD commands). `words` are in `orcalink.tools.WORDS` and
`fam_freecad.tools()` declares them to Agent Link's index (`agentlink.toolindex.declare`, inside try/except for an older
Agent Link). **Not run**: check `tool_groups { find: "temperature tower" }` finds orca_calibrate.

Both guides (orcalink/guides/orca.md and freecad_guides/orca.md) got a section "Numbering, limits and time". README tool
list regenerated. CHANGELOG has the fixes under Unreleased.

## Not verified (no OrcaSlicer, no source)

- The command-line flags as this build takes them: `--slice`, `--arrange`, `--orient`, `--export-3mf`, `--outputdir`,
  `--load-settings`, `--load-filaments`, `--export-stl`, `--export-stls`, `--export-settings`, `--export-slicedata`,
  `--info`, and the options passed through by name. The code asks `--help` before using `--export-statistics`,
  `--inspect-mesh`, `--inspect-paint`, `--info` and `--bake-texture-displacement`, but **not** before `--export-stls` or
  the relayout options (`align_to_y_axis`, `repair`, `ground_largest_face`, `ground_face_normal`, `ground_face_point`
  among them). I could not tell which are upstream and which are the agent-cli fork's, so the description says only that a
  build without one answers failed with OrcaSlicer's words.
- That OrcaSlicer reads the files this writes the way the code comments say: paint attributes, plate bed_type and
  curr_bed_type, layer ranges, custom G-code per layer, brim ears, texture displacement layers. The repo's tests round-trip
  them through its own reader only.
- The time figures: only the code's timeouts are stated (slice 15 min, layout and exports 10, inspect 5). No real slice was
  timed.
- `orca_project place` with a negative `instance` picks from the end (Python indexing); harmless, left.
- Object lookup falls back to a part of the name, first hit: with "box" and "box lid" the wrong one can be taken. Described
  in the description; behaviour left (changing it could break callers).

## Proposed, not done

- Long slices under Agent Link for FreeCAD: `fam_freecad` could set `HEAVY = {"orca_slice"}` so a slice runs as a job from
  the first call. Not done: I could not check what the hub's heavy deadline (sized from the FreeCAD document) would do to a
  10-minute slice.
- The standalone server has no jobs: a slice longer than the client's call limit is dropped by the client while it runs
  on. The description tells the agent to read `<project>-sliced.3mf` afterwards. A `background` slice would be a feature.

## Test model

orca-model.json: 38 calls, 12 of them expected refusals. The 29 that need no OrcaSlicer were dry-run here on the sample
project and matched; `new`, `arrange`, the two G-code slices, the three gcode_read calls on the sliced file, and the two
orca_calibrate calls have not run anywhere.
