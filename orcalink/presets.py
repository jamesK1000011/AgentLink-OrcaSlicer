# SPDX-License-Identifier: LGPL-2.1-or-later
"""Slicer presets as data: the person's own printer, process and filament
presets read from where Bambu Studio and OrcaSlicer keep them, their
inheritance resolved (a user preset on top of a system one), and kept or
passed on as one JSON bundle that can be exported and imported. Nothing of
a printer is written into the code: the minimal profiles used when no
preset is chosen are a data file too (data/slicer-minimal.json).

A bundle is
    {"agentlinkPresets": 1, "slicer": "bambustudio", "name": "...",
     "machine": {...}, "process": {...}, "filament": {...}}
each part the slicer's own JSON, flattened (no "inherits")."""

import glob
import json
import os

KINDS = ("machine", "process", "filament")
HOME = os.path.expanduser("~")
_SUPPORT = os.path.join(HOME, "Library", "Application Support")

# Where each slicer keeps its presets, newest first: the person's own, the
# system ones it downloaded, then the ones inside the app.
ROOTS = {
    "bambustudio": (
        ("AGENTLINK_BAMBU_PRESETS",),
        [os.path.join(_SUPPORT, "BambuStudio", "user"), os.path.join(_SUPPORT, "BambuStudio", "system"),
         "/Applications/BambuStudio.app/Contents/Resources/profiles",
         os.path.join(HOME, ".config", "BambuStudio", "user"), os.path.join(HOME, ".config", "BambuStudio", "system")],
    ),
    "orcaslicer": (
        ("AGENTLINK_ORCA_PRESETS",),
        [os.path.join(_SUPPORT, "OrcaSlicer", "user"), os.path.join(_SUPPORT, "OrcaSlicer", "system"),
         "/Applications/OrcaSlicer.app/Contents/Resources/profiles",
         os.path.join(HOME, ".config", "OrcaSlicer", "user"), os.path.join(HOME, ".config", "OrcaSlicer", "system")],
    ),
}

MINIMAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "slicer-minimal.json")


class PresetError(Exception):
    pass


def _own_roots(slicer):
    env, places = ROOTS[slicer]
    given = [p for e in env for p in (os.environ.get(e) or "").split(os.pathsep) if p]
    return [p for p in (given or places) if os.path.isdir(p)]


def roots(slicer):
    """The folders read for a slicer's presets, in the order a name is
    looked up. OrcaSlicer: its own folders, the system presets fetched as
    JSON (fetch_orca), then Bambu Studio's folders last. OrcaSlicer takes
    Bambu Studio's presets (same format), and the person's own filament
    presets are often kept in Bambu Studio only: so slicer_presets list and
    orca_project read the same names."""
    found = _own_roots(slicer)
    if slicer == "orcaslicer":
        found += [p for p in orca_cached() if p not in found]
        found += [p for p in _own_roots("bambustudio") if p not in found]
    return found


def _is_user(root):
    return os.sep + "user" in root


def _foreign_system(slicer, root):
    """A root of another slicer's system presets: read to resolve what a
    preset inherits, not listed (OrcaSlicer's own system presets are)."""
    return slicer == "orcaslicer" and root in _own_roots("bambustudio") and not _is_user(root)


def _kind_of(path, data):
    t = str(data.get("type") or "").lower()
    if t in KINDS:
        return t
    if t:
        return None  # machine_model and the like: not a preset to choose
    for k in KINDS:
        if f"{os.sep}{k}{os.sep}" in path:
            return k
    return None


def scan(slicer):
    """{kind: {name: [entry …]}}, an entry {path, root, user, listed}; the
    same name in several places is kept in the order of roots (the person's
    own first)."""
    index = {k: {} for k in KINDS}
    every = roots(slicer)
    # Another slicer's system presets are read only when a name is not
    # found in the rest (find_name): a few thousand files, seldom needed.
    index["_later"] = [r for r in every if _foreign_system(slicer, r)]
    index["_slicer"] = slicer
    _read(index, slicer, [r for r in every if r not in index["_later"]])
    return index


def _read(index, slicer, folders):
    for root in folders:
        user = _is_user(root)
        foreign = _foreign_system(slicer, root)
        for path in sorted(glob.glob(os.path.join(root, "**", "*.json"), recursive=True)):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if not data.get("name"):
                if not user:
                    continue
                # A preset of the person's own may keep its name only in
                # the file name (the .info file beside it has the rest).
                data["name"] = os.path.splitext(os.path.basename(path))[0]
            kind = _kind_of(path, data)
            if kind is None:
                continue
            listed = str(data.get("instantiation", "true")).lower() != "false" and not foreign
            # The vendor folder (BBL, Creality …) a system preset sits in:
            # base names such as fdm_machine_common are in every vendor's
            # folder, with different values, and the slicer looks a parent
            # up in the child's own vendor first.
            rel = os.path.relpath(path, root).split(os.sep)
            vendor = rel[0] if len(rel) >= 3 else None
            index[kind].setdefault(data["name"], []).append({"path": path, "root": root, "user": user, "listed": listed, "vendor": vendor,
                                                             "name": data["name"]})


def _norm(name):
    return " ".join(str(name or "").replace("\u00a0", " ").split()).casefold()


def find_name(index, kind, name):
    """The preset name as the files have it: the name itself, else the
    same words in any case and spacing, else a file named so (a preset of
    the person's own is often given as its file shows it). None when not
    found."""
    if name in index[kind]:
        return name
    later = index.pop("_later", None)
    if later:
        _read(index, index.get("_slicer"), later)
        if name in index[kind]:
            return name
    want = _norm(name)
    for n, entries in index[kind].items():
        if _norm(n) == want or any(_norm(os.path.splitext(os.path.basename(e["path"]))[0]) == want for e in entries):
            return n
    return None


def listing(slicer, kind=None, query=None, limit=60):
    """The presets that can be chosen (not the base ones others inherit from),
    the person's own marked, filtered by words in query."""
    index = scan(slicer)
    words = [w.lower() for w in (query or "").split()]
    bambu = set(_own_roots("bambustudio")) if slicer == "orcaslicer" else set()
    out = {}
    for k in ([kind] if kind else KINDS):
        names = []
        for name, entries in index[k].items():
            if not entries[0]["listed"]:
                continue
            if all(w in name.lower() for w in words):
                names.append({"name": name, **({"own": True} if entries[0]["user"] else {}),
                              **({"in": "Bambu Studio"} if entries[0]["root"] in bambu else {})})
        names.sort(key=lambda x: (not x.get("own"), x["name"]))
        out[k] = {"count": len(names), "presets": names[:limit]}
    return out


# Keys of an included file that say what the file is, not settings.
_META = ("name", "type", "inherits", "include", "instantiation", "from", "setting_id", "filament_id", "description", "renamed_from")
# OrcaSlicer's shared filament library: a vendor's filament may stand on a
# base kept there when the vendor's own folder lacks it.
BASE_VENDOR = "OrcaFilamentLibrary"


def _entry(index, kind, name, near=None):
    """The file for a preset name. A name that several vendors' folders
    hold (fdm_machine_common, fdm_process_common …: their values differ) is
    taken from the folder of the preset that asks for it (near), then from
    OrcaSlicer's filament library beside it, then the first found, as the
    slicer looks a parent up in the vendor's own bundle, then its base
    bundle."""
    entries = index[kind].get(name)
    if not entries:
        return None
    if near is not None and near.get("vendor"):
        for vendor in (near["vendor"], BASE_VENDOR):
            for e in entries:
                if e["root"] == near["root"] and e.get("vendor") == vendor:
                    return e
    return entries[0]


def _includes(data):
    inc = data.get("include")
    if not inc:
        return []
    return [inc] if isinstance(inc, str) else [x for x in inc if isinstance(x, str) and x]


def resolve(index, kind, name, _seen=None, _near=None):
    """A preset with what it inherits merged under it: the slicer's JSON,
    flat. As OrcaSlicer 2.5 loads its system presets: the parent (inherits)
    first, then each file the preset includes ("include": a list of names;
    Bambu Lab printers keep their start, end, layer-change, filament-change
    and time-lapse G-code in such files, and filaments their per-nozzle
    lists), in the order listed, then the preset's own keys on top. An
    include that is not there stops it: left out, a printer would take a
    generic start G-code."""
    seen = _seen or []
    name = find_name(index, kind, name) or name
    if name in seen:
        raise PresetError(f"{kind} preset {name!r} inherits from itself ({' > '.join(seen + [name])}).")
    entry = _entry(index, kind, name, _near)
    if entry is None:
        if seen:
            raise PresetError(f"{kind} preset {seen[-1]!r} inherits or includes {name!r}, which is not among the presets read: fetch that vendor's presets again (or the person's slicer lacks it).")
        import difflib

        near = difflib.get_close_matches(_norm(name), [_norm(n) for n in index[kind]], n=3, cutoff=0.6)
        names = [n for n in index[kind] if _norm(n) in near][:3]
        if not names:
            names = near_by_words(index, kind, name)
        raise PresetError(f"No {kind} preset named {name!r} in the preset folders read. Give the name as the slicer lists it."
                          + (f" Near names: {', '.join(names)}." if names else ""))
    with open(entry["path"], encoding="utf-8") as f:
        data = json.load(f)
    parent = data.get("inherits")
    flat = {}
    if parent:
        flat = resolve(index, kind, parent, seen + [name], entry)
    up = flat.get("_system")
    for inc in _includes(data):
        got = resolve(index, kind, inc, seen + [name], entry)
        flat = merge(kind, flat, {k: v for k, v in got.items() if k not in _META and k != "_system"})
    flat = merge(kind, flat, {k: v for k, v in data.items() if k not in ("inherits", "include")})
    flat["name"] = name
    # The system preset this one stands on (itself when it is one): Bambu
    # Studio's command line names a printer by it when it checks a
    # process against it.
    flat["_system"] = name if not entry["user"] and entry["listed"] else up
    return flat


# The key whose length says how many extruders (machine), or extruder
# variants (process, filament), a preset's per-extruder lists hold.
VARIANT_KEY = {"machine": "nozzle_diameter", "process": "print_extruder_variant", "filament": "filament_extruder_variant"}


def variant_count(kind, data):
    v = data.get(VARIANT_KEY[kind])
    if kind == "machine" and not (isinstance(v, list) and v):
        v = data.get("printer_extruder_variant")
    return len(v) if isinstance(v, list) and v else 1


def merge(kind, parent, child):
    """A preset's own values put over what it inherits, as the slicer does
    when it loads a user preset: a user preset keeps only what differs
    (often one value of a list the system preset has per extruder or per
    extruder variant), so a list it leaves empty keeps the parent's, and a
    list shorter than the parent's per-extruder one is padded with its last
    value to the same length, so each extruder keeps the person's value.
    The slicer's command line stops on an empty list ("Assigning from an
    empty vector") where its window would fill it in."""
    out = dict(parent)
    out.update({k: v for k, v in child.items() if not (isinstance(v, list) and not v)})
    n = variant_count(kind, out)
    if n > 1:
        for k, v in child.items():
            pv = parent.get(k)
            if isinstance(v, list) and v and isinstance(pv, list) and len(pv) == n and len(v) < n:
                out[k] = list(v) + [v[-1]] * (n - len(v))
    return out


def complete(kind, data):
    """A flat preset made ready for the command line: no empty lists. The
    command line copies each filament's lists into the project one value at
    a time and stops on an empty one ("ConfigOptionVector::set_at():
    Assigning from an empty vector"); left out, the slicer's own default
    stands instead, as in its window."""
    return {k: v for k, v in data.items() if not (isinstance(v, list) and not v)}


def flatten_file(slicer, kind, path, folder_):
    """A preset file given by path made ready for the command line: what it
    inherits merged in (looked up among the slicer's presets) and no empty
    list. The command line stops on a user preset file as the slicer saves
    it ("Assigning from an empty vector"). Returns the path to load: the
    file itself when it needs nothing, else a flat copy in folder_."""
    with open(os.path.expanduser(path), encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise PresetError(f"{path}: not a preset (a JSON object).")
    empty = any(isinstance(v, list) and not v for v in data.values())
    if not data.get("inherits") and not empty:
        return path
    flat = {}
    if data.get("inherits"):
        flat = resolve(scan(slicer), kind, data["inherits"])
        flat.pop("_system", None)
    flat = complete(kind, merge(kind, flat, {k: v for k, v in data.items() if k != "inherits"}))
    flat["type"] = kind
    os.makedirs(folder_, exist_ok=True)
    out = os.path.join(folder_, f"agentlink-given-{kind}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(flat, f, indent=1)
    return out


def bundle(slicer, machine, process, filament, name=None):
    index = scan(slicer)
    if not roots(slicer):
        raise PresetError(f"No {slicer} presets on this computer (looked in {', '.join(ROOTS[slicer][1][:3])}).")
    out = {"agentlinkPresets": 1, "slicer": slicer, "name": name or machine}
    if not machine:
        raise PresetError("machine (a printer preset name) is needed to make presets: give the printer as the slicer lists it.")
    out["machine"] = resolve(index, "machine", machine)
    defaults = {"process": out["machine"].get("default_print_profile"), "filament": out["machine"].get("default_filament_profile")}
    for kind, n in (("process", process), ("filament", filament)):
        if not n:
            n = defaults[kind]
            if isinstance(n, list):
                n = n[0] if n else None
            if not n:
                raise PresetError(f"No {kind} preset given, and the printer {machine!r} names no default {kind}: give {kind} as the slicer lists it."
                                  + _hint(index, kind, machine))
            out.setdefault("defaulted", {})[kind] = n
        out[kind] = resolve(index, kind, n)
    return out


def near_by_words(index, kind, name, n=3):
    """Presets that share the most words with name (the printer after @,
    the material): a hint when the spelling is far off."""
    want = set(_norm(name).replace("@", " ").split())
    if not want:
        return []
    scored = []
    for k, entries in index[kind].items():
        if not entries[0].get("listed", True):
            continue
        got = set(_norm(k).replace("@", " ").split())
        common = len(want & got)
        if common:
            scored.append((-common, k))
    scored.sort()
    return [k for _, k in scored[:n]]


def _hint(index, kind, machine):
    names = near_by_words(index, kind, machine)
    return f" Presets for that printer: {', '.join(names)}." if names else ""


def check_bundle(data):
    if not isinstance(data, dict) or data.get("agentlinkPresets") != 1:
        raise PresetError("Not a presets bundle: an Agent Link presets bundle ({ agentlinkPresets: 1, slicer, machine, process, filament }).")
    if data.get("slicer") not in ROOTS:
        raise PresetError(f"The bundle's slicer {data.get('slicer')!r} is not one of {', '.join(ROOTS)}.")
    for k in KINDS:
        if not isinstance(data.get(k), dict):
            raise PresetError(f"The bundle has no {k}.")
    return data


def folder(out_dir):
    return os.path.join(out_dir, "presets")


def save(out_dir, data, name=None):
    """A bundle kept with the person's files, to choose by name later."""
    check_bundle(data)
    name = (name or data.get("name") or "presets").strip()
    safe = "".join(c if c.isalnum() or c in " -_.@" else "_" for c in name).strip() or "presets"
    os.makedirs(folder(out_dir), exist_ok=True)
    path = os.path.join(folder(out_dir), safe + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({**data, "name": name}, f, indent=1)
    return name, path


def load_saved(out_dir, name):
    for path in glob.glob(os.path.join(folder(out_dir), "*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if data.get("name") == name or os.path.splitext(os.path.basename(path))[0] == name:
            return check_bundle(data)
    raise PresetError(f"No saved presets bundle named {name!r} in {folder(out_dir)}: save one there first (Agent Link for FreeCAD's slicer_presets export, or a bundle file put in that folder).")


def saved(out_dir):
    out = []
    for path in sorted(glob.glob(os.path.join(folder(out_dir), "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            out.append({"name": d.get("name"), "slicer": d.get("slicer"), "machine": d["machine"].get("name"), "process": d["process"].get("name"), "filament": d["filament"].get("name")})
        except Exception:
            continue
    return out


def write_profiles(data, folder_):
    """The bundle's three parts as the files the slicer's command line loads.
    Loaded together as new presets, Bambu Studio counts a process or a
    filament compatible only when it names the printer: the printer is added
    to their lists (the person chose them together)."""
    os.makedirs(folder_, exist_ok=True)
    m = data["machine"]
    printer = m.get("_system") or m.get("name")
    paths = {}
    for k in KINDS:
        part = complete(k, {key: v for key, v in data[k].items() if key != "_system"})
        system = data[k].get("_system")
        # Bambu Studio's command line takes a printer's name for the check
        # from the file itself when it is a system preset, else from its
        # inherits: a preset is written as the one, or on top of the other.
        if system and system == part.get("name"):
            part["from"] = "system"
        else:
            part["from"] = "User"
            if system:
                part["inherits"] = system
        part["instantiation"] = "true"
        # A preset in the person's own folder may say nothing of its kind
        # (Bambu Studio knows it by the folder); the command line refuses a
        # file that does not.
        part["type"] = k
        if k == "machine" and "nozzle_volume_type" not in part and part.get("default_nozzle_volume_type"):
            # The window seeds it from the default; the command line looks
            # for the key itself.
            part["nozzle_volume_type"] = part["default_nozzle_volume_type"]
        if k != "machine" and printer:
            cp = list(part.get("compatible_printers") or [])
            for want in (printer, m.get("name")):
                if want and want not in cp:
                    cp.append(want)
            part["compatible_printers"] = cp
            part["compatible_printers_condition"] = ""
        p = os.path.join(folder_, f"agentlink-{k}.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(part, f, indent=1)
        paths[k] = p
    return paths


def _first(v):
    return v[0] if isinstance(v, list) and v else v


def setup_from(data):
    """What a chosen bundle says of the print setup's own settings — so the
    mass estimate, the checks and the slicer agree: layer height, walls,
    infill, top and bottom layers, nozzle."""
    p, m = data["process"], data["machine"]
    out = {}

    def num(v, cast=float):
        try:
            return cast(str(_first(v)).rstrip("%"))
        except (TypeError, ValueError):
            return None

    for key, src, cast in (("layerHeight", p.get("layer_height"), float), ("firstLayer", p.get("initial_layer_print_height"), float),
                           ("walls", p.get("wall_loops"), int), ("infill", p.get("sparse_infill_density"), float),
                           ("topLayers", p.get("top_shell_layers"), int), ("bottomLayers", p.get("bottom_shell_layers"), int),
                           ("nozzle", m.get("nozzle_diameter"), float)):
        v = num(src, cast)
        if v is not None:
            out[key] = v
    return out


def minimal(settings):
    """The minimal profiles from data/slicer-minimal.json, the setup's
    values put in: {machine, process, filament} dicts."""
    with open(MINIMAL, encoding="utf-8") as f:
        tpl = json.load(f)
    vol = settings.get("volume") or (220, 220, 250)
    values = {
        "layerHeight": settings.get("layerHeight", 0.2), "firstLayer": settings.get("firstLayer", settings.get("layerHeight", 0.2)),
        "walls": int(settings.get("walls", 2)), "infill": int(settings.get("infill", 15)),
        "topLayers": int(settings.get("topLayers", 5)), "bottomLayers": int(settings.get("bottomLayers", 4)),
        "nozzle": settings.get("nozzle", 0.4), "flavor": settings.get("flavor", "marlin"),
        "volumeX": vol[0], "volumeY": vol[1], "volumeZ": vol[2],
        "filament": str(settings.get("filament", "PLA")).upper(), "density": settings.get("density", 1.24),
        "filamentDiameter": settings.get("filamentDiameter", 1.75),
    }

    def fill(v):
        if isinstance(v, str):
            try:
                return v.format(**values)
            except (KeyError, IndexError, ValueError):
                return v
        if isinstance(v, list):
            return [fill(x) for x in v]
        if isinstance(v, dict):
            return {k: fill(x) for k, x in v.items()}
        return v

    return {k: fill(tpl[k]) for k in KINDS}


# ---- OrcaSlicer's own system presets, as JSON ----------------------------------------------
# From 2.5 OrcaSlicer ships each vendor's system presets packed (<Vendor>.opc,
# its own binary cache), not as JSON. The same presets are in its source, as
# JSON, at the release's tag: fetched once per version and vendor by a sparse
# git checkout (this computer's git; public repository, no sign-in), kept
# under ~/.config/freecad-agentlink/orca-profiles/<version>, and read like the
# rest.

ORCA_CACHE = os.path.join(HOME, ".config", "freecad-agentlink", "orca-profiles")
ORCA_REPO = "https://github.com/OrcaSlicer/OrcaSlicer.git"


def packed_only(slicer):
    """Folders holding packed presets (.opc) and no JSON ones."""
    out = []
    for r in roots(slicer):
        if glob.glob(os.path.join(r, "*.opc")) and not glob.glob(os.path.join(r, "*", "machine", "*.json")):
            out.append(r)
    return out


def orca_version(exe):
    """The version of the OrcaSlicer at exe: its app bundle's Info.plist on a
    Mac, else what its --help says."""
    import re
    import subprocess

    if ".app/" in exe:
        import plistlib

        try:
            with open(exe.split(".app/")[0] + ".app/Contents/Info.plist", "rb") as f:
                v = str(plistlib.load(f).get("CFBundleShortVersionString") or "")
            m = re.match(r"(\d+)\.(\d+)\.(\d+)", v)
            if m:
                return ".".join(str(int(x)) for x in m.groups())  # 02.05.00 -> 2.5.0
        except Exception:
            pass
    try:
        r = subprocess.run([exe, "--help"], capture_output=True, text=True, timeout=120)
    except Exception:
        return None
    m = re.search(r"OrcaSlicer-(\d+\.\d+\.\d+)", (r.stdout or "") + (r.stderr or ""))
    return m.group(1) if m else None


def fetch_orca(vendors, version=None, exe=None, repo=None):
    """The vendors' system presets for this OrcaSlicer's version, as JSON,
    into the cache; their folder is then one of the places presets are read
    from. Returns {version, folder, vendors, files}."""
    import shutil
    import subprocess

    if version is None:
        if exe is None:
            from . import cli as slicers

            exe = slicers.find("orcaslicer")
        version = orca_version(exe) if exe else None
    if not version:
        raise PresetError("Which OrcaSlicer: none found here to read its version from — give version.")
    git = shutil.which("git") or next((g for g in ("/usr/bin/git", "/opt/homebrew/bin/git", "/usr/local/bin/git") if os.path.exists(g)), None)
    if not git:
        raise PresetError("git is not installed on this computer: it fetches the presets.")
    dest = os.path.join(ORCA_CACHE, version)
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    def run(*args, timeout=600):
        r = subprocess.run([git, *args], capture_output=True, text=True, timeout=timeout, env=env)
        if r.returncode != 0:
            raise PresetError(f"git {args[0]}: {((r.stderr or r.stdout).strip().splitlines() or ['failed'])[-1]}")
        return r

    paths = [f"/resources/profiles/{v}/" for v in vendors] + [f"/resources/profiles/{v}.json" for v in vendors]
    if not os.path.isdir(os.path.join(dest, ".git")):
        os.makedirs(ORCA_CACHE, exist_ok=True)
        tag = f"v{version}"
        try:
            run("clone", "--depth", "1", "--filter=blob:none", "--no-checkout", "-b", tag, repo or ORCA_REPO, dest)
        except PresetError as e:
            raise PresetError(f"OrcaSlicer {tag} could not be fetched: {e}")
        run("-C", dest, "sparse-checkout", "set", "--no-cone", *paths)
        run("-C", dest, "checkout")
    else:
        have = run("-C", dest, "sparse-checkout", "list").stdout.split()
        run("-C", dest, "sparse-checkout", "set", "--no-cone", *sorted(set(have) | set(paths)))
    folder = os.path.join(dest, "resources", "profiles")
    files = len(glob.glob(os.path.join(folder, "**", "*.json"), recursive=True))
    return {"version": version, "folder": folder, "vendors": sorted(v for v in vendors if os.path.isdir(os.path.join(folder, v))), "files": files}


def orca_cached():
    """The fetched profile folders, newest version first."""
    return sorted(glob.glob(os.path.join(ORCA_CACHE, "*", "resources", "profiles")), reverse=True)
