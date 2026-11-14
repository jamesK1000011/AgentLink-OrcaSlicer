# OrcaSlicer, headless

## The loop
1. `orca_project { action: new, files, path }` makes the project from model files (STL, OBJ, 3MF, STEP …), with presets if given (`bundle`, or `machine`, `process`, `filament` names), minimal ones otherwise. Inside Agent Link for FreeCAD, `bodies` makes it from FreeCAD bodies with their print setup's presets.
2. Change it at any level with `orca_project set { scope project|object|part|range|plate, key, value | settings }` — every value is checked against OrcaSlicer's own table (`action: settings { query }` lists keys, types, limits, values). `slot` sets one filament's value.
3. `orca_paint { object, kind supports|seam|fuzzy_skin|color, state, where }` paints the triangles where says: `normal [x, y, z]` (within degrees), `box`, `below` / `above` a height, in object coordinates. With FreeCAD, `faces` paints by face names.
4. `orca_slice { path }` slices it; `gcode_read` shows layers, moves and views.
5. The return leg: the model changed, then `orca_project replace { object, file }` (or `body`) — its settings, modifiers and place stay; paint goes and is painted again.
6. `orca_project strength { object }` reads walls, infill and layers against the part's size (a feasibility estimate); with FreeCAD, `fea_setup { printed: { project, object } }` takes them into the strength study.

## orca_project actions
- Objects: object_add { body | file (STL, OBJ, 3MF, STEP, a ZIP) | handy | primitive cube|cylinder|sphere|cone|disc|torus + size, plate, at }, object_remove, copy, instance { count, move | remove, instance }, instance_to_object, printable, place { move, rotate, scale, at [x,y], drop }, lay_flat { face | normal }, scale_to_fit, fill_bed { spacing }, grid { nx, ny }.
- Parts: part_add { kind modifier_part|negative_part|support_blocker|support_enforcer|normal_part, file | box [x,y,z] + at | primitive + size + at | body, name, settings }, part_remove, replace { body | file }, emboss { text | svg, size, depth, at, rotate, kind } (FreeCAD draws the letters).
- Mesh: mesh { op simplify (FreeCAD)|fix|smooth|subdivide|mirror|boolean (with, mode; FreeCAD)|cut (axis, at, keep)|cut_grid (size)|split|split_objects|merge (objects)|decompose_color }.
- Layers: layer_heights { profile [[z, h]…] | adaptive 0..1 }, gcode { z, kind pause|color_change|tool_change|template|custom, gcode, extruder, plate, remove }, brim_ears { points, radius }.
- Filaments and presets: filament { slot | like, color, type, settings | remove }, flush { matrix, multiplier }, presets { machine, process, filament | bundle }.
- Plates: plate { object, plate } (moves it; the next number makes a plate), plate_add, plate_remove, plate_duplicate, plate_move { plate, to }, set { scope: plate, key: name|locked|bed_type|print_sequence … }.
- OrcaSlicer's own: arrange, orient (options allow_rotations, align_to_y_axis …), cli { options } (uptodate, repair, clone_objects, repetitions, scale, rotate, ground_face_normal …).
- info { object } (with its effective print settings), saveAs writes a copy.

## Traps
- Plates sit side by side in the project's world (a bed and a fifth apart): `place at` is on the object's own plate.
- Calibrations (`orca_calibrate`) use the models of the OrcaSlicer on this computer; the retraction tower rewrites the sliced G-code, so slice it with `orca_slice`.
- Starting a print is the person's call.
