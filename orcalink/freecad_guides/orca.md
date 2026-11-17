# OrcaSlicer, headless

These tools are Agent Link for OrcaSlicer's (a separate add-on, github.com/jamesK1000011/AgentLink-OrcaSlicer), given FreeCAD's bodies, faces and kernel here.

## The loop
1. `orca_project { action: new, bodies, path }` makes the project from FreeCAD bodies with the print setup's presets (`slicer_presets use` first, else minimal ones). Each object in the answer names its `body`, matched by the file Orca loaded it from (the project keeps the map, and `info` shows it), never by order: Orca sorts and arranges the files, so object 1 need not be the first body. Actions that find the body themselves (paint by `faces`, `lay_flat` by `face`, `part_add { of }`, `strength`) use the same map.
2. Change it at any level with `orca_project set { scope project|object|part|range|plate, key, value | settings }` — every value is checked against OrcaSlicer's own table (`action: settings { query }` lists keys, types, limits, values). `slot` sets one filament's value.
3. `orca_paint { object, faces, kind supports|seam|fuzzy_skin|color, state }` paints by FreeCAD face names; `where { normal, within, box, below, above }` paints by direction or place instead. `kind texture` with `texture { image | library, depth, tileSize, … }` adds a Texture Displacement layer on those faces; `orca_slice` bakes the relief as it slices (colour layers give relief only).
4. `orca_slice { path }` slices it; `gcode_read` shows layers, moves and views.
5. The return leg: change the body in FreeCAD, then `orca_project replace { object, body }` — its settings, modifiers and place stay; paint goes and is painted again.
6. `orca_project strength { object }` and `fea_setup { printed: { project, object } }` read the walls, infill and layers back into the strength study (a feasibility estimate).

## orca_project actions
- Objects: object_add { body | file (STL, OBJ, 3MF, STEP, a ZIP) | handy | primitive cube|cylinder|sphere|cone|disc|torus + size, plate, at }, object_remove, copy, instance { count, move | remove, instance }, instance_to_object, printable, place { move, rotate, scale, at [x,y], drop }, lay_flat { face | normal }, scale_to_fit, fill_bed { spacing }, grid { nx, ny }.
- Parts: part_add { kind modifier_part|negative_part|support_blocker|support_enforcer|normal_part, body | box [x,y,z] + at | file, name, settings }, part_remove, replace { body | file }, emboss { text | svg, size, depth, at, rotate, kind }.
- Mesh: mesh { op simplify|fix|smooth|subdivide|mirror|boolean (with, mode)|cut (axis, at, keep)|cut_grid (size)|split|split_objects|merge (objects)|decompose_color }.
- Layers: layer_heights { profile [[z, h]…] | adaptive 0..1 }, gcode { z, kind pause|color_change|tool_change|template|custom, gcode, extruder, plate, remove }, brim_ears { points, radius }.
- Filaments and presets: filament { slot | like, color, type, settings | remove }, flush { matrix, multiplier }, presets { machine, process, filament | bundle }.
- Plates: plate { object, plate } (moves it; the next number makes a plate), plate_add, plate_remove, plate_duplicate, plate_move { plate, to }, set { scope: plate, key: name|locked|bed_type|print_sequence … } (bed_type is written as the plate's own and as the project's curr_bed_type, read back, and an error if it did not take). A new project's bed type is chosen so every filament goes on it (bedType, bedTypes in the answer); a slice stopped by "<plate> does not support filament <n>" names the bed types that would work.
- OrcaSlicer's own: arrange, orient (options allow_rotations, align_to_y_axis …), cli { options } (uptodate, repair, clone_objects, repetitions, scale, rotate, ground_face_normal …).
- info { object } (with its effective print settings), saveAs writes a copy.

## Numbering, limits and time
- Paths: a relative path is in the output folder (`orca_status` names it). Outputs of a slice or an export go in `<project>-out/`, the sliced project is `<project>-sliced.3mf`.
- Objects are named or numbered from 1 as `info` lists them (a part of the name matches too: the first hit wins); parts from 1; instances from 0; plates from 1; filament slots from 1; texture layers (slots) from 0; G-code layers from 1 as OrcaSlicer numbers them (layer 1 is the first, the last is the layer count), G-code moves from 0.
- Lengths are mm and angles degrees. `where`, `box`, `at` for a part and `cut at` are in the object's own coordinates (`info` gives `size`); `place at` is [x, y] on the object's own plate; `info`'s `placed` is in the project's world, where plates stand side by side.
- Limits: instance `count` 1 to 200, `grid` 1 to 50 each way, `fill_bed` 200 copies, `cut_grid` 400 pieces, `smooth` 1 to 50 iterations, 8 texture layers, `orca_slice` svg `layerHeight` 0.01 to 10 mm.
- The tools work on the project file. A project that is open in OrcaSlicer's window is not updated: the person reloads it, and a save from the window afterwards overwrites the change.
- Time: reading and changing a small project takes milliseconds; every call reads and writes the whole project, so large meshes cost more on each call (not measured). `new`, `arrange`, `orient`, `cli` and the exports that run OrcaSlicer are allowed 10 minutes, a slice 15; the server answers no other call meanwhile. When the client gives up on a long slice, the slice still finishes: `gcode_read { path: "<project>-sliced.3mf" }` reads it.
- A refused value changes nothing: the project is saved only after every value of the call has been checked.

## Traps
- Plates sit side by side in the project's world (a bed and a fifth apart): `place at` is on the object's own plate.
- Calibrations (`orca_calibrate`) use the models of the OrcaSlicer on this computer; the retraction tower rewrites the sliced G-code, so slice it with `orca_slice`.
- Starting a print is the person's call.
