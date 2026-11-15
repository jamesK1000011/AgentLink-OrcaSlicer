# SPDX-License-Identifier: LGPL-2.1-or-later
# Texture displacement as OrcaSlicer's Texture Displacement gizmo stores it in
# a project (.3mf), written without the window. Ported from the fork's C++
# (github.com/jamesK1000011/OrcaSlicer, main, 14 Nov 2026):
#
#   * the layer stack and its options: one JSON file per part,
#     Metadata/texture_displacement/<id>.json, made by
#     texture_displacement_layers_to_json() and read back by
#     texture_displacement_layers_from_json()
#     (src/libslic3r/TextureDisplacement.cpp:5768-5980);
#   * each layer's image: Metadata/texture_displacement/<id>_<slot>.png,
#     stored uncompressed (add_texture_displacement(),
#     src/libslic3r/Format/bbs_3mf.cpp:8274-8302);
#   * the part names the JSON with <metadata key="texture_displacement"
#     value="<json path>"/> in Metadata/model_settings.config
#     (bbs_3mf.cpp:365, 8300; read back at 5435);
#   * which triangles each layer covers: a paint attribute per slot,
#     paint_texture_0 … paint_texture_7, in the TriangleSelector encoding
#     supports and seams use; a painted triangle is ENFORCER, "4"
#     (bbs_3mf.cpp:362-364, 7807-7818; the gizmo paints ENFORCER,
#     GLGizmoTextureDisplacement.cpp:239, 313).
#
# Field names, defaults and order follow struct TextureDisplacementLayer and
# struct TextureDisplacementOptions (src/libslic3r/TextureDisplacement.hpp:
# 209-473). Plain Python.

import json
import struct

DIR = "Metadata/texture_displacement/"  # bbs_3mf.cpp:366 TEXTURE_DISPLACEMENT_DIR
KEY = "texture_displacement"  # bbs_3mf.cpp:365 TEXTURE_DISPLACEMENT_KEY
SLOTS = 8  # TextureDisplacement.hpp:44 TEXTURE_DISPLACEMENT_MAX_LAYERS
PAINTED = "4"  # EnforcerBlockerType::ENFORCER, whole triangle (orca3mf.paint_state(1))


def attr(slot):
    """The triangle attribute of a slot's paint mask (bbs_3mf.cpp:362)."""
    return f"paint_texture_{slot}"


# Enum values: TextureDisplacement.hpp:48 (TextureTileMethod), 55 (TextureProjectionMethod), 129 (TextureBlendMode).
TILES = {"repeat": 0, "mirrored": 1}
PROJECTIONS = {"triplanar": 0, "cylindrical": 1, "spherical": 2, "lscm": 3, "view": 4, "model_uv": 5}
BLENDS = {"add": 0, "subtract": 1, "multiply": 2, "divide": 3, "override": 4}

# The gizmo's own control ranges; its sliders clamp to them (ImGuiSliderFlags_AlwaysClamp,
# GLGizmoTextureDisplacement.cpp:7277-7290). Line numbers are that file's.
RANGES = {
    "depth_mm": (0.01, 10.0),  # 7807 Depth
    "tiling_scale": (0.2, 200.0),  # 7816 Tile size
    "rotation_deg": (0.0, 360.0),  # 7827 Rotation
    "midlevel": (0.0, 10.0),  # 7845 Midlevel
    "smoothing": (0.0, 1.0),  # 7858 Smoothing
    "edge_smoothing_amount": (0.02, 1.0),  # 7872 Edge fade amount
    "lscm_seam_angle_deg": (5.0, 90.0),  # 3084 SetSeamAngle
    "smooth_strength": (0.01, 1.0),  # 8545 Strength
    "smooth_iterations": (1, 10),  # 8548 Passes
    "color_despeckle": (0, 6),  # 7936 Denoise
    "color_mix_count": (1, 31),  # 7920: ExtruderMax (32) less the filaments in use
}


def f32(x):
    """x as the C++ float it is stored in: nlohmann::json widens a float to
    double, so 0.4f is written 0.4000000059604645."""
    return struct.unpack("<f", struct.pack("<f", float(x)))[0]


def layer(slot, **kw):
    """A layer with TextureDisplacementLayer's defaults (hpp:209-354), its
    members by their C++ names; kw overrides them."""
    out = {
        "slot": slot, "name": "", "path": "", "path_in_3mf": "",
        "depth_mm": 0.4, "tiling_scale": 12.5, "rotation_deg": 0.0, "offset": [0.0, 0.0], "invert": False,
        "midlevel": 0.0, "smoothing": 0.0, "edge_smoothing": False, "edge_smoothing_amount": 0.5,
        "auto_connect_islands": True, "tile_enabled": True, "tile_method": 0, "projection_method": 0,
        "lscm_seam_angle_deg": 30.0, "island_padding_mm": -1.0, "lscm_seam_edges": [],
        "view_project_right": [1.0, 0.0, 0.0], "view_project_up": [0.0, 1.0, 0.0],
        "view_project_projective": False, "view_project_matrix": [0.0] * 12,
        "islands": [], "island_groups": [], "lscm_uv_overrides": [], "blend_mode": 0, "color_enabled": False,
    }
    out.update(kw)
    return out


def options(**kw):
    """TextureDisplacementOptions' defaults (hpp:388-464)."""
    out = {
        "displace_border": True, "smooth_enabled": False, "smooth_strength": 0.3, "smooth_iterations": 2,
        "smooth_skip_border": True, "pipeline_v2": True, "v2_refine_mm": 0.0, "v2_regularize": False,
        "v2_max_triangles_k": -1, "v2_relocate": False, "v2_flip_edges": True, "color_mix_enabled": True,
        "color_despeckle": 2, "color_mix_count": 8, "active_slot": 0, "panel_mode": 0,
    }
    out.update(kw)
    return out


_OPT_FLOATS = {"smooth_strength", "v2_refine_mm"}
_LAYER_FLOATS = {"depth_mm", "tiling_scale", "rotation_deg", "midlevel", "smoothing", "edge_smoothing_amount",
                 "lscm_seam_angle_deg", "island_padding_mm"}


def to_json(layers, opts):
    """The stack as texture_displacement_layers_to_json() writes it
    (TextureDisplacement.cpp:5768-5852): nlohmann's dump(), compact, its
    object keys sorted, floats widened from float."""
    o = {}
    for k, v in options(**opts).items():
        o[k] = f32(v) if k in _OPT_FLOATS else (bool(v) if isinstance(v, bool) else int(v))
    arr = []
    for src in layers:
        l = {**layer(-1), **src}
        j = {"slot": int(l["slot"]), "name": l["name"], "path": l["path"], "path_in_3mf": l["path_in_3mf"]}
        for k in _LAYER_FLOATS:
            j[k] = f32(l[k])
        j["offset"] = [f32(x) for x in l["offset"]]
        for k in ("invert", "edge_smoothing", "auto_connect_islands", "tile_enabled", "color_enabled", "view_project_projective"):
            j[k] = bool(l[k])
        for k in ("tile_method", "projection_method", "blend_mode"):
            j[k] = int(l[k])
        j["view_project_right"] = [f32(x) for x in l["view_project_right"]]
        j["view_project_up"] = [f32(x) for x in l["view_project_up"]]
        j["view_project_matrix"] = [f32(x) for x in l["view_project_matrix"]]
        # Flat pairs (cpp:5827-5833), [x, y, rotation, scale] islands (5835-5839), [key, u, v] overrides (5843-5846).
        j["lscm_seam_edges"] = [int(x) for e in l["lscm_seam_edges"] for x in e]
        j["islands"] = [[f32(x) for x in i] for i in l["islands"]]
        j["island_groups"] = [int(x) for x in l["island_groups"]]
        j["lscm_uv_overrides"] = [[int(k), f32(u), f32(v)] for k, u, v in l["lscm_uv_overrides"]]
        arr.append(j)
    return json.dumps({"version": 1, "options": o, "layers": arr}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Malformed(ValueError):
    pass


def _num(v, kind):
    # nlohmann's get<int>() / get<float>() take any number (a float truncates) and throw on anything else.
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise Malformed("a number of the wrong type")
    return kind(v)


def from_json(text):
    """(layers, options) as texture_displacement_layers_from_json() reads
    them (TextureDisplacement.cpp:5854-5977): a value of the wrong type
    keeps its default, but a layer slot outside 0..7 or a wrong number in an
    array rejects the whole document (Malformed)."""
    try:
        root = json.loads(text)
    except ValueError:
        raise Malformed("not JSON")
    if not isinstance(root, dict):
        raise Malformed("not a JSON object")

    def read(j, k, cur):
        v = j.get(k, cur)
        if isinstance(cur, bool):
            return v if isinstance(v, bool) else cur
        if isinstance(cur, int):
            return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else cur
        if isinstance(cur, float):
            return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else cur
        if isinstance(cur, str):
            return v if isinstance(v, str) else cur
        return cur

    opts = options()
    if isinstance(root.get("options"), dict):
        for k, cur in list(opts.items()):
            opts[k] = read(root["options"], k, cur)
        opts["active_slot"] = min(max(opts["active_slot"], 0), SLOTS - 1)  # cpp:5886
        opts["panel_mode"] = min(max(opts["panel_mode"], 0), 1)
    layers = []
    for j in root.get("layers") if isinstance(root.get("layers"), list) else []:
        if not isinstance(j, dict):
            continue
        l = layer(-1)
        l["slot"] = read(j, "slot", -1)
        if not 0 <= l["slot"] < SLOTS:  # cpp:5903
            raise Malformed(f"layer slot {l['slot']} outside 0..{SLOTS - 1}")
        for k in ("name", "path", "path_in_3mf", *_LAYER_FLOATS, "invert", "edge_smoothing", "auto_connect_islands",
                  "tile_enabled", "color_enabled", "tile_method", "projection_method", "blend_mode", "view_project_projective"):
            l[k] = read(j, k, l[k])
        l["projection_method"] = min(max(l["projection_method"], 0), 4)  # cpp: std::clamp(projection, 0, 4)
        for k, n in (("offset", 2), ("view_project_right", 3), ("view_project_up", 3)):
            v = j.get(k)
            if isinstance(v, list) and len(v) == n:
                l[k] = [_num(x, float) for x in v]
        v = j.get("view_project_matrix")
        if isinstance(v, list) and len(v) == 12:
            l["view_project_matrix"] = [_num(x, float) for x in v]
        v = j.get("lscm_seam_edges")
        if isinstance(v, list):
            l["lscm_seam_edges"] = [(_num(v[i], int), _num(v[i + 1], int)) for i in range(0, len(v) - 1, 2)]
        v = j.get("islands")
        if isinstance(v, list):
            l["islands"] = [[_num(x, float) for x in e] for e in v if isinstance(e, list) and len(e) == 4]
        v = j.get("island_groups")
        if isinstance(v, list) and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
            l["island_groups"] = [int(x) for x in v]
        v = j.get("lscm_uv_overrides")
        if isinstance(v, list):
            l["lscm_uv_overrides"] = [(_num(e[0], int), _num(e[1], float), _num(e[2], float)) for e in v if isinstance(e, list) and len(e) == 3]
        layers.append(l)
    return layers, opts


def png_check(data):
    """(width, height, colour) of an image the bake can read, or ValueError.
    The rule of PNGReadWrite.cpp:235-240 (is_png + decode_png /
    decode_colored_png): a PNG, 8 bits a channel, grey, RGB or RGBA, not
    empty. Read from its header (IHDR)."""
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 33 or data[12:16] != b"IHDR":
        raise ValueError("not a PNG image (OrcaSlicer's texture displacement reads PNG only).")
    w, h, depth, ctype = struct.unpack(">IIBB", data[16:26])
    if not (w and h):
        raise ValueError("the image is empty (0 pixels).")
    if depth != 8 or ctype not in (0, 2, 6):
        raise ValueError(f"the PNG is {depth}-bit, colour type {ctype}: OrcaSlicer reads 8-bit grey, RGB or RGBA.")
    return w, h, ctype != 0
