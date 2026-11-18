# SPDX-License-Identifier: LGPL-2.1-or-later
"""The G-code preview, headless: what OrcaSlicer's preview pane shows, read
from the G-code itself (any slicer that marks layers and features the way
Orca, Bambu Studio and PrusaSlicer do).

The file is replayed move by move — absolute or relative positions and
extrusion, arcs, feedrate, fan, temperatures, tool changes, pauses and
colour changes — and gathered per layer and per feature. The views are the
preview's: feature type, height, width, speed, fan speed, temperature,
volumetric flow, layer time, tool, acceleration. A layer's toolpaths can be
drawn as an SVG, coloured by any view.

Layers are numbered from 1, as OrcaSlicer numbers them in the file
("; layer num/total_layer_count: 1/25") and on its preview's slider: the
last layer's number is the layer count. When the file marks its layers
(CHANGE_LAYER, LAYER_CHANGE, LAYER:n), a layer starts only at a mark, so
the printer's start G-code (its purge lines) is not a layer; OrcaSlicer's
MACHINE_START_GCODE_END and MACHINE_END_GCODE_START marks bound the
printer's own start and end G-code, which are kept out of the layers,
features, ranges, tools and events and reported apart (machineGcode).

Times are the moves' lengths over their feedrates (no acceleration): good
for comparing layers and features; the slicer's own estimate (from the
file's header) is the one to quote for the whole print. No FreeCAD needed.
"""

import math
import re

VIEWS = ("feature", "height", "width", "speed", "actual_speed", "fan", "temperature", "flow", "actual_flow", "layer_time", "tool", "acceleration")

_NUM = re.compile(r"([A-Za-z])\s*(-?\d*\.?\d+(?:[eE][-+]?\d+)?)")
_TYPE = re.compile(r"^;\s*(?:TYPE|FEATURE)\s*:\s*(.+?)\s*$")
# PrusaSlicer and older OrcaSlicer: ;WIDTH: / ;HEIGHT:. OrcaSlicer 2.5 and
# Bambu Studio: ; LINE_WIDTH: / ; LAYER_HEIGHT: (their reserved tags).
_WIDTH = re.compile(r"^;\s*(?:LINE_)?WIDTH\s*:\s*([\d.]+)")
_HEIGHT = re.compile(r"^;\s*(?:LAYER_)?HEIGHT\s*:\s*([\d.]+)")
_Z = re.compile(r"^;\s*(?:Z|Z_HEIGHT)\s*[:=]\s*([\d.]+)")
_LAYER = re.compile(r"^;\s*(LAYER_CHANGE|CHANGE_LAYER|LAYER:\s*\d+)\s*$")
_ANY_LAYER = re.compile(r"^;\s*(?:LAYER_CHANGE|CHANGE_LAYER|LAYER:\s*\d+)\s*$", re.M)
_START_END = re.compile(r"^;\s*MACHINE_START_GCODE_END\b")
_END_START = re.compile(r"^;\s*MACHINE_END_GCODE_START\b")
_HEADER = {
    "time": (r";\s*estimated printing time \(normal mode\)\s*=\s*(.+)", r";\s*total estimated time\s*:\s*(.+)", r";\s*model printing time\s*:\s*([^;]+)"),
    "filamentG": (r";\s*(?:total )?filament used \[g\]\s*=\s*([\d.,\s]+)", r";\s*total filament weight \[g\]\s*:\s*([\d.,\s]+)"),
    "filamentMm": (r";\s*(?:total )?filament used \[mm\]\s*=\s*([\d.,\s]+)", r";\s*total filament length \[mm\]\s*:\s*([\d.,\s]+)"),
    "filamentCm3": (r";\s*(?:total )?filament used \[cm3\]\s*=\s*([\d.,\s]+)",),
    "cost": (r";\s*(?:total )?filament cost\s*=\s*([\d.,\s]+)",),
}
PAUSES = ("M601", "M0", "M1", "M25", "M400 U1")
# T numbers at or above this are printer firmware codes, not filament tools.
MACHINE_TOOL_CODES = 255

COLOR_CHANGES = ("M600",)


class _AllLayers:
    def __contains__(self, _):
        return True


_ALL = _AllLayers()


class _Layer:
    __slots__ = ("index", "z", "height", "features", "moves", "time", "travel", "travel_time", "fan", "temp", "tools", "events", "speeds", "widths",
                 "flows", "accels", "paths", "retracts", "wipes", "seams", "steps", "actual_speeds", "actual_flows")

    def __init__(self, index, z):
        self.index, self.z, self.height = index, z, None
        self.features = {}
        self.moves = 0
        self.time = self.travel = self.travel_time = 0.0
        self.fan, self.temp, self.tools = set(), set(), set()
        self.events = []
        self.speeds, self.widths, self.flows, self.accels = [], [], [], []
        self.paths = []
        self.retracts = self.wipes = 0
        self.seams = []
        # Kept layers: every move (kind, G-code line, x0, y0, x1, y1, mm/s, feature).
        self.steps = []
        self.actual_speeds, self.actual_flows = [], []


def _rng(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return [round(min(vals), 3), round(max(vals), 3)]


def read(path, keep_paths=None, filament_diameter=1.75):
    """Replay the file. keep_paths: the layer numbers (from 1) whose moves
    to keep (for drawing); None keeps none, "all" every one."""
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    header = {}
    for k, pats in _HEADER.items():
        for pat in pats:
            m = re.search(pat, text, re.M)
            if m:
                header[k] = m.group(1).strip()
                break
    area = math.pi * (filament_diameter / 2.0) ** 2
    pos = {"X": 0.0, "Y": 0.0, "Z": 0.0, "E": 0.0}
    absolute, abs_e = True, True
    feed = 1500.0
    role, width, height = None, None, None
    fan, temp, tool, accel = 0.0, None, 0, None
    layers, cur = [], None
    keep = _ALL if keep_paths == "all" else set(keep_paths or [])
    pending_z = None
    # A file that marks its layers starts one only at a mark: what comes
    # before the first is the printer's start G-code, not a layer.
    marked = bool(_ANY_LAYER.search(text))
    # The printer's own start and end G-code: replayed (positions, heat,
    # tool) but counted apart, not in a layer.
    machine = {}
    ended = False

    def mach(where, lineno):
        m = machine.setdefault(where, {"lines": [lineno, lineno], "filamentMm": 0.0, "timeS": 0.0, "temperature": set(), "tools": set()})
        m["lines"][1] = lineno
        return m

    def new_layer(z):
        nonlocal cur
        cur = _Layer(len(layers) + 1, z)
        cur.tools.add(tool)
        # What holds from the layer before (set before any move here).
        cur.fan.add(fan)
        if temp is not None:
            cur.temp.add(temp)
        layers.append(cur)

    wiping = False
    last_role = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith(";"):
            if _END_START.match(line):
                ended, cur, pending_z = True, None, None
                mach("end", lineno)
                continue
            if ended:
                continue
            if _LAYER.match(line):
                pending_z = "next"
                continue
            m = _Z.match(line)
            if m and pending_z == "next":
                new_layer(float(m.group(1)))
                pending_z = None
                continue
            m = _TYPE.match(line)
            if m:
                role = m.group(1)
                continue
            if line.startswith(";WIPE_START"):
                wiping = True
                if cur is not None:
                    cur.wipes += 1
                continue
            if line.startswith(";WIPE_END"):
                wiping = False
                continue
            m = _WIDTH.match(line)
            if m:
                width = float(m.group(1))
                continue
            m = _HEIGHT.match(line)
            if m:
                height = float(m.group(1))
                if cur is not None and cur.height is None:
                    cur.height = height
                continue
            up = line.upper()
            if cur is not None and ("PAUSE" in up or "COLOR_CHANGE" in up or "COLOUR_CHANGE" in up) and len(line) < 60:
                cur.events.append(line.lstrip("; "))
            continue
        code = line.split(";", 1)[0].strip()
        if not code:
            continue
        head = code.split()[0].upper()
        where = "end" if ended else ("start" if cur is None and marked else None)
        mm = mach(where, lineno) if where else None
        if pending_z == "next" and head in ("G0", "G1") and "Z" in code.upper():
            pass
        if head in ("G90",):
            absolute = True
        elif head == "G91":
            absolute = False
        elif head == "M82":
            abs_e = True
        elif head == "M83":
            abs_e = False
        elif head == "G92":
            for k, v in _NUM.findall(code[3:]):
                if k.upper() in pos:
                    pos[k.upper()] = float(v)
        elif head in ("M106",):
            s = dict((k.upper(), float(v)) for k, v in _NUM.findall(code[4:]))
            # The part cooling fan, as OrcaSlicer's preview reads it: M106
            # with no P, or P1 (Bambu's part fan); P2, P3 are other fans.
            if s.get("P", 1.0) == 1.0:
                fan = round(100.0 * s.get("S", 255.0) / 255.0, 1)
                if cur is not None:
                    cur.fan.add(fan)
        elif head == "M107":
            fan = 0.0
            if cur is not None:
                cur.fan.add(fan)
        elif head in ("M104", "M109"):
            s = dict((k.upper(), float(v)) for k, v in _NUM.findall(code[4:]))
            if "S" in s:
                temp = s["S"]
                if mm is not None:
                    mm["temperature"].add(temp)
                elif cur is not None:
                    cur.temp.add(temp)
        elif head == "M204":
            s = dict((k.upper(), float(v)) for k, v in _NUM.findall(code[4:]))
            accel = s.get("S", s.get("P", accel))
        elif re.fullmatch(r"T\d+", head):
            tool = int(head[1:])
            if mm is not None:
                mm["tools"].add(tool)
            elif cur is not None:
                cur.tools.add(tool)
                cur.events.append(f"tool {tool}")
        elif head in COLOR_CHANGES or code.upper() in PAUSES or head in ("M601", "M25", "M0", "M1"):
            if cur is not None:
                cur.events.append("colour change" if head in COLOR_CHANGES else f"pause ({code})")
        elif head in ("G0", "G1", "G2", "G3"):
            args = dict((k.upper(), float(v)) for k, v in _NUM.findall(code[len(head):]))
            if "F" in args:
                feed = args["F"]
            new = dict(pos)
            for k in ("X", "Y", "Z"):
                if k in args:
                    new[k] = args[k] if absolute else pos[k] + args[k]
            de = 0.0
            if "E" in args:
                de = args["E"] - pos["E"] if abs_e else args["E"]
                new["E"] = args["E"] if abs_e else pos["E"] + args["E"]
            dx, dy, dz = new["X"] - pos["X"], new["Y"] - pos["Y"], new["Z"] - pos["Z"]
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)
            if head in ("G2", "G3") and ("I" in args or "J" in args):
                r = math.hypot(args.get("I", 0.0), args.get("J", 0.0))
                cx, cy = pos["X"] + args.get("I", 0.0), pos["Y"] + args.get("J", 0.0)
                a0 = math.atan2(pos["Y"] - cy, pos["X"] - cx)
                a1 = math.atan2(new["Y"] - cy, new["X"] - cx)
                sweep = (a1 - a0) % (2 * math.pi) if head == "G3" else (a0 - a1) % (2 * math.pi)
                if sweep == 0:
                    sweep = 2 * math.pi
                dist = math.hypot(r * sweep, dz)
            if cur is None and not marked and not ended and (de > 0 and dist > 0):
                new_layer(new["Z"])
                mm = None
            secs = dist / (feed / 60.0) if feed > 0 else 0.0
            if mm is not None:
                mm["timeS"] += secs
                if de > 0:
                    mm["filamentMm"] += de
            kept = cur is not None and cur.index in keep
            if cur is not None and de < -1e-9 and math.hypot(dx, dy) < 1e-9:
                cur.retracts += 1
                if kept:
                    cur.steps.append(("retract", lineno, pos["X"], pos["Y"], new["X"], new["Y"], round(feed / 60.0, 2), role or "?"))
            if cur is not None and dist > 0:
                cur.moves += 1
                speed = feed / 60.0
                if de > 1e-9 and (role or "").lower() in ("outer wall", "external perimeter", "outer_wall") and last_role != role:
                    cur.seams.append((round(pos["X"], 3), round(pos["Y"], 3)))
                if de > 1e-9:
                    last_role = role
                    # The speed the move reaches: from rest at the layer's
                    # acceleration, over half its length (no lookahead).
                    a_ = accel or 1000.0
                    actual = min(speed, math.sqrt(a_ * dist)) if dist > 0 else speed
                    cur.actual_speeds.append(actual)
                    if actual > 0:
                        cur.actual_flows.append(de * area * actual / dist if dist else 0.0)
                    if kept:
                        cur.steps.append(("extrude", lineno, pos["X"], pos["Y"], new["X"], new["Y"], round(speed, 2), role or "?"))
                    feat = cur.features.setdefault(role or "?", {"length": 0.0, "filament": 0.0, "time": 0.0, "moves": 0, "speed": [], "width": []})
                    feat["length"] += dist
                    feat["filament"] += de
                    feat["time"] += secs
                    feat["moves"] += 1
                    feat["speed"].append(speed)
                    if width:
                        feat["width"].append(width)
                    cur.time += secs
                    cur.speeds.append(speed)
                    if width:
                        cur.widths.append(width)
                    if secs > 0:
                        cur.flows.append(de * area / secs)
                    if accel:
                        cur.accels.append(accel)
                    if cur.index in keep:
                        cur.paths.append((role or "?", pos["X"], pos["Y"], new["X"], new["Y"], width or 0.4, speed, fan, de * area / secs if secs else 0.0, tool))
                elif dist > 0:
                    cur.travel += dist
                    cur.travel_time += secs
                    if kept:
                        cur.steps.append(("wipe" if wiping else "travel", lineno, pos["X"], pos["Y"], new["X"], new["Y"], round(speed, 2), role or "?"))
            pos = new
    for m in machine.values():
        m["filamentMm"] = round(m["filamentMm"], 1)
        m["timeS"] = round(m["timeS"], 1)
        m["temperature"] = sorted(m["temperature"])
        # Bambu firmware takes T255 (unload), T1000/T1001 (its own nozzle
        # calls) and T65279/T65535 (reset) in its start and end G-code: they
        # are machine codes, not filament tools (live 18 Nov, 92).
        tools = sorted(m["tools"])
        m["tools"] = [t for t in tools if t < MACHINE_TOOL_CODES]
        codes = [t for t in tools if t >= MACHINE_TOOL_CODES]
        if codes:
            m["machineCodes"] = [f"T{t}" for t in codes]
    return {"header": header, "layers": layers, "path": path, "machine": machine}


def summary(data):
    L = data["layers"]
    feats = {}
    for ly in L:
        for k, f in ly.features.items():
            g = feats.setdefault(k, {"length": 0.0, "filament": 0.0, "time": 0.0})
            g["length"] += f["length"]
            g["filament"] += f["filament"]
            g["time"] += f["time"]
    total_t = sum(f["time"] for f in feats.values()) or 1.0
    events = [{"layer": ly.index, "z": ly.z, "event": e} for ly in L for e in ly.events]
    return {
        "layers": len(L),
        "z": [round(L[0].z, 3), round(L[-1].z, 3)] if L else None,
        "slicer": {k: v for k, v in data["header"].items()},
        "features": {k: {"lengthMm": round(v["length"], 1), "filamentMm": round(v["filament"], 1), "timeShare": round(v["time"] / total_t, 3)}
                     for k, v in sorted(feats.items(), key=lambda kv: -kv[1]["time"])},
        "tools": sorted({t for ly in L for t in ly.tools}),
        "events": events,
        "ranges": {
            "height": _rng([ly.height for ly in L]),
            "width": _rng([w for ly in L for w in ly.widths]),
            "speed": _rng([s for ly in L for s in ly.speeds]),
            "fan": _rng([f for ly in L for f in ly.fan]),
            "temperature": _rng([t for ly in L for t in ly.temp]),
            "flow": _rng([q for ly in L for q in ly.flows]),
            "actual_speed": _rng([q for ly in L for q in ly.actual_speeds]),
            "actual_flow": _rng([q for ly in L for q in ly.actual_flows]),
            "layer_time": _rng([ly.time + ly.travel_time for ly in L]),
            "acceleration": _rng([a for ly in L for a in ly.accels]),
        },
        **({"machineGcode": data["machine"]} if data.get("machine") else {}),
    }


def _at(L, number):
    """The layer of a number from 1 (negative: from the top, -1 the last);
    past the top gives the last."""
    i = int(number)
    if i == 0:
        raise ValueError("layer: numbered from 1, as OrcaSlicer numbers them (negative counts from the top: -1 is the last).")
    i = i - 1 if i > 0 else i + len(L)
    return L[max(0, min(len(L) - 1, i))]


def layer(data, number=None, z=None):
    L = data["layers"]
    if not L:
        return None
    if z is not None:
        ly = min(L, key=lambda x: abs(x.z - float(z)))
    else:
        ly = _at(L, number if number is not None else 1)
    return {
        "layer": ly.index, "z": round(ly.z, 3), "height": ly.height, "timeS": round(ly.time + ly.travel_time, 1), "travelMm": round(ly.travel, 1),
        "features": {k: {"lengthMm": round(f["length"], 1), "filamentMm": round(f["filament"], 2), "timeS": round(f["time"], 1), "speed": _rng(f["speed"]),
                         "width": _rng(f["width"])} for k, f in ly.features.items()},
        "fan": sorted(ly.fan), "temperature": sorted(ly.temp), "tools": sorted(ly.tools), "events": ly.events,
        "speed": _rng(ly.speeds), "width": _rng(ly.widths), "flow": _rng(ly.flows), "actualSpeed": _rng(ly.actual_speeds),
        "retracts": ly.retracts, "wipes": ly.wipes, "seams": ly.seams[:50], **({"moves": len(ly.steps)} if ly.steps else {}),
    }


def move(data, number, n):
    """The nth move (0..) of a kept layer (number from 1), as the preview's
    move slider and G-code window show it: its kind, where from and to,
    speed, feature, and the G-code line (number and text)."""
    ly = _at(data["layers"], number)
    if not ly.steps:
        raise ValueError("no moves kept for that layer: read it with keep_paths")
    if n < 0:
        n += len(ly.steps)
    k, lineno, x0, y0, x1, y1, v, role = ly.steps[max(0, min(len(ly.steps) - 1, n))]
    line = None
    try:
        with open(data["path"], encoding="utf-8", errors="replace") as f:
            for i, ln in enumerate(f, 1):
                if i == lineno:
                    line = ln.rstrip("\n")
                    break
    except OSError:
        pass
    return {"move": n, "of": len(ly.steps), "kind": k, "from": [round(x0, 3), round(y0, 3)], "to": [round(x1, 3), round(y1, 3)], "speed": v,
            "feature": role, "line": lineno, "gcode": line}


def toolpaths_obj(data, out, layers=None):
    """The extrusions as ribbons (width x layer height boxes along each
    move), one OBJ file: the preview's Export toolpaths as OBJ. Read with
    keep_paths for the layers wanted ("all" for every one); layers: their
    numbers from 1."""
    vs, fs = [], []
    for ly in data["layers"]:
        if layers is not None and ly.index not in layers:
            continue
        h = ly.height or 0.2
        for p in ly.paths:
            role, x0, y0, x1, y1, w = p[:6]
            dx, dy = x1 - x0, y1 - y0
            ln = math.hypot(dx, dy)
            if ln < 1e-9:
                continue
            nx, ny = -dy / ln * w / 2, dx / ln * w / 2
            z0, z1 = ly.z - h, ly.z
            b = len(vs) + 1
            vs += [(x0 + nx, y0 + ny, z0), (x0 - nx, y0 - ny, z0), (x1 - nx, y1 - ny, z0), (x1 + nx, y1 + ny, z0),
                   (x0 + nx, y0 + ny, z1), (x0 - nx, y0 - ny, z1), (x1 - nx, y1 - ny, z1), (x1 + nx, y1 + ny, z1)]
            for a, c, d in ((0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)):
                fs.append((b + a, b + c, b + d))
    with open(out, "w", encoding="utf-8") as f:
        f.write("# toolpaths\n")
        f.writelines(f"v {x:.4f} {y:.4f} {z:.4f}\n" for x, y, z in vs)
        f.writelines(f"f {a} {b} {c}\n" for a, b, c in fs)
    return {"path": out, "ribbons": len(fs) // 12}


def legend(data, view, buckets=6):
    """The preview's legend for a view: each value or band and its share of
    the extrusion time."""
    if view not in VIEWS:
        raise ValueError(f"view: one of {', '.join(VIEWS)}")
    L = data["layers"]
    if view == "feature":
        acc = {}
        for ly in L:
            for k, f in ly.features.items():
                acc[k] = acc.get(k, 0.0) + f["time"]
    elif view == "tool":
        acc = {}
        for ly in L:
            for t in ly.tools:
                acc[f"T{t}"] = acc.get(f"T{t}", 0.0) + ly.time
    else:
        pairs = []
        for ly in L:
            if view == "height":
                pairs.append((ly.height or 0.0, ly.time))
            elif view == "layer_time":
                pairs.append((ly.time + ly.travel_time, 1.0))
            elif view == "fan":
                pairs += [(v, ly.time / max(1, len(ly.fan))) for v in (ly.fan or {0.0})]
            elif view == "temperature":
                pairs += [(v, ly.time / max(1, len(ly.temp))) for v in ly.temp]
            else:
                src = {"width": ly.widths, "speed": ly.speeds, "flow": ly.flows, "acceleration": ly.accels, "actual_speed": ly.actual_speeds, "actual_flow": ly.actual_flows}[view]
                w = ly.time / max(1, len(src))
                pairs += [(v, w) for v in src]
        if not pairs:
            return {"view": view, "bands": []}
        lo, hi = min(p[0] for p in pairs), max(p[0] for p in pairs)
        n = 1 if hi - lo < 1e-9 else buckets
        step = (hi - lo) / n if n > 1 else 1.0
        acc = {}
        for v, w in pairs:
            b = 0 if n == 1 else min(n - 1, int((v - lo) / step))
            key = f"{lo + b * step:.3g}–{lo + (b + 1) * step:.3g}" if n > 1 else f"{lo:.3g}"
            acc[key] = acc.get(key, 0.0) + w
    total = sum(acc.values()) or 1.0
    return {"view": view, "bands": [{"value": k, "share": round(v / total, 3)} for k, v in sorted(acc.items(), key=lambda kv: -kv[1])]}


_PALETTE = ["#e8553e", "#f2a33a", "#f7d04b", "#7bc24a", "#3fa7a3", "#3d7bd9", "#7a5fd1", "#c25bb5", "#8a8a8a", "#4f4f4f"]


def svg(data, number, view="feature", size=600, show=()):
    """One layer's (number from 1) extrusion moves as an SVG, coloured by a
    view; show travel, wipe, retract, seams draws those too (the preview's
    toggles)."""
    ly = _at(data["layers"], number)
    if not ly.paths:
        raise ValueError("no moves kept for that layer: read it with keep_paths")
    xs = [p[1] for p in ly.paths] + [p[3] for p in ly.paths]
    ys = [p[2] for p in ly.paths] + [p[4] for p in ly.paths]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    span = max(x1 - x0, y1 - y0, 1e-6)
    k = (size - 20) / span

    def X(x):
        return 10 + (x - x0) * k

    def Y(y):
        return size - 10 - (y - y0) * k

    col = {}
    idx = {"feature": 0, "width": 5, "speed": 6, "actual_speed": 6, "fan": 7, "flow": 8, "actual_flow": 8, "tool": 9}.get(view, 0)
    vals = [p[idx] for p in ly.paths]
    if isinstance(vals[0], str):
        for i, v in enumerate(sorted(set(vals))):
            col[v] = _PALETTE[i % len(_PALETTE)]

        def colour(v):
            return col[v]
    else:
        lo, hi = min(vals), max(vals)

        def colour(v):
            t = 0.0 if hi - lo < 1e-9 else (v - lo) / (hi - lo)
            return _PALETTE[min(len(_PALETTE) - 3, int(t * (len(_PALETTE) - 3)))]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">',
           f'<rect width="{size}" height="{size}" fill="#1e1e1e"/>']
    for p in ly.paths:
        out.append(f'<line x1="{X(p[1]):.2f}" y1="{Y(p[2]):.2f}" x2="{X(p[3]):.2f}" y2="{Y(p[4]):.2f}" stroke="{colour(p[idx])}" '
                   f'stroke-width="{max(0.5, p[5] * k):.2f}" stroke-linecap="round"/>')
    for st in ly.steps:
        if st[0] in show and st[0] in ("travel", "wipe"):
            out.append(f'<line x1="{X(st[2]):.2f}" y1="{Y(st[3]):.2f}" x2="{X(st[4]):.2f}" y2="{Y(st[5]):.2f}" stroke="{"#5aa0ff" if st[0] == "travel" else "#ffd75a"}" '
                       'stroke-width="0.6" stroke-dasharray="3 2"/>')
        elif st[0] == "retract" and "retract" in show:
            out.append(f'<circle cx="{X(st[2]):.2f}" cy="{Y(st[3]):.2f}" r="2.5" fill="#ff4fa3"/>')
    if "seams" in show:
        for sx, sy in ly.seams:
            out.append(f'<circle cx="{X(sx):.2f}" cy="{Y(sy):.2f}" r="3" fill="none" stroke="#ffffff" stroke-width="1.2"/>')
    if col:
        for i, (name, c) in enumerate(col.items()):
            out.append(f'<rect x="12" y="{12 + i * 16}" width="10" height="10" fill="{c}"/><text x="26" y="{21 + i * 16}" fill="#ddd" font-size="11" font-family="sans-serif">{name}</text>')
    out.append(f'<text x="{size - 10}" y="{size - 12}" fill="#aaa" font-size="11" font-family="sans-serif" text-anchor="end">layer {ly.index} · z {ly.z:.2f} mm · {view}</text>')
    out.append("</svg>")
    return "\n".join(out)
