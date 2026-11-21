# SPDX-License-Identifier: LGPL-2.1-or-later
# The slicers' command lines (the one copy: Workshop for FreeCAD's Make
# slices through this module too): PrusaSlicer (as prusa.py drives it, or
# with a config bundle the person exported), OrcaSlicer and Bambu Studio
# (their --slice command line, which takes JSON machine, process and
# filament profiles: the person's own by path, or minimal ones written here
# from the print setup). The G-code each writes is read back and the pauses
# for parts encased mid-print written in, by each slicer's own layer marks.

import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile

from . import guard
from . import prusa


NAMES = ("prusaslicer", "orcaslicer", "bambustudio")
PAUSE = {"prusaslicer": "M601", "orcaslicer": "M601", "bambustudio": "M400 U1"}
_EXE = {
    "orcaslicer": ("AGENTLINK_ORCASLICER", ("orca-slicer", "OrcaSlicer", "orcaslicer"), ("/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer",)),
    "bambustudio": ("AGENTLINK_BAMBUSTUDIO", ("bambu-studio", "BambuStudio", "bambustudio"), ("/Applications/BambuStudio.app/Contents/MacOS/BambuStudio",)),
}


def find(name):
    if name == "prusaslicer":
        return prusa.find_slicer()
    env, names, places = _EXE[name]
    if os.environ.get(env):
        return os.environ[env]
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return next((p for p in places if os.path.exists(p)), None)


def present():
    return {n: bool(find(n)) for n in NAMES}


class SlicerBusy(RuntimeError):
    """The slicer's command line could not run because the slicer's own
    window is open (or another copy holds its lock). Nothing was changed."""


# Words a slicer prints when another copy of it holds the lock.
_LOCK = re.compile(r"another instance|already running|single.instance|lock file|could not (?:get|acquire|obtain) [^\n]*lock", re.I)
# Command-line flags: a process with one of them is a command line, not a window.
_CLI_FLAG = re.compile(r"^--(?:slice|export-|load-|info|inspect-|arrange|orient|outputdir|help)")


def window_open(exe, ps_text=None):
    """The process ids of the slicer's own window (exe started without
    command-line flags) other than this process. ps_text: the output of
    `ps -axo pid=,args=` (read here when None). [] when it cannot tell."""
    if not exe:
        return []
    if ps_text is None:
        try:
            ps_text = subprocess.run(["ps", "-axo", "pid=,args="], capture_output=True, text=True, timeout=10).stdout or ""
        except (OSError, subprocess.SubprocessError):
            return []
    base = os.path.basename(exe).lower()
    pids = []
    for line in ps_text.splitlines():
        parts = line.strip().split()
        if len(parts) < 2 or not parts[0].isdigit() or int(parts[0]) == os.getpid():
            continue
        if os.path.basename(parts[1]).lower() != base:
            continue
        if any(_CLI_FLAG.match(x) for x in parts[2:]):
            continue
        pids.append(int(parts[0]))
    return pids


def _busy_message(exe, what):
    name = os.path.basename(exe or "the slicer")
    return (f"{name}'s own window is open on this computer, and its command line {what} beside it. Nothing was changed. "
            f"Tell the person: save their work in {name}'s window and close it when they are done there, then ask again. "
            f"Do not close it for them.")


def _run(args, timeout, cwd=None):
    try:
        run = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        if run.returncode != 0 and not os.environ.get("DISPLAY") and shutil.which("xvfb-run"):
            run = subprocess.run(["xvfb-run", "-a"] + args, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        if window_open(args[0]):
            raise SlicerBusy(_busy_message(args[0], f"did not finish in {timeout} s"))
        raise RuntimeError(f"The slicer did not finish in {timeout} s and was stopped.")
    return run


def _failed(run, why=None):
    """The error for a command line that made nothing: SlicerBusy, with the
    slicer's own words after it, when its window is open or it names a
    lock; else the slicer's own words."""
    tail = (why + " — " if why else "") + _tail(run)
    exe = run.args[0] if isinstance(run.args, (list, tuple)) and run.args else None
    if exe and os.path.basename(exe) == "xvfb-run" and len(run.args) > 2:
        exe = run.args[2]
    text = (run.stderr or "") + "\n" + (run.stdout or "")
    if window_open(exe):
        return SlicerBusy(_busy_message(exe, "made nothing") + " The slicer said: " + tail)
    if _LOCK.search(text):
        name = os.path.basename(exe or "the slicer")
        return SlicerBusy(f"Another copy of {name} holds its lock, so its command line made nothing. Nothing was changed. "
                          f"Tell the person: close any {name} window when they are done there, then ask again. The slicer said: " + tail)
    return RuntimeError(tail)


def minimal_profiles(settings, folder):
    """Machine, process and filament JSON from the print setup, written to
    folder: the minimal profiles of data/slicer-minimal.json, the setup's
    values put in; the slicer's defaults do the rest."""
    from . import presets as slicer_presets

    out = {}
    for k, v in slicer_presets.minimal(settings).items():
        p = os.path.join(folder, f"agentlink-{k}.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(v, f, indent=1)
        out[k] = p
    return out


# What the last OrcaSlicer / Bambu Studio slice said beside its G-code
# (results()): warnings, plate statistics.
LAST = {}


def _slice_with(name, stl, gcode, settings, profiles=None, timeout=900, options=None):
    """Slice stl (a path, or a list of them on one plate) into gcode with the
    named slicer. options (OrcaSlicer and Bambu Studio): orient, arrange
    (each bool), project (a .3mf path: the sliced plate as a project the
    slicer's window opens). Returns (exe, profiles used: 'given' or
    'written' or 'setup')."""
    options = options or {}
    stls = [stl] if isinstance(stl, str) else list(stl)
    if name == "prusaslicer" and len(stls) > 1:
        raise RuntimeError("Several bodies on one plate: OrcaSlicer or Bambu Studio.")
    stl = stls[0]
    exe = find(name)
    if not exe:
        how = "install PrusaSlicer, or set AGENTLINK_SLICER" if name == "prusaslicer" else f"install it, or set {_EXE[name][0]} to its command line"
        raise FileNotFoundError(f"{name} is not on this computer: {how}. present: {', '.join(k for k, v in present().items() if v) or 'none'}.")
    profiles = profiles or {}
    LAST.clear()
    if name == "prusaslicer":
        if not profiles.get("config"):
            prusa.slice_stl(stl, gcode, settings, timeout)
            return exe, "setup"
        args = [exe, "--export-gcode", "--load", profiles["config"], "--output", gcode, stl]
        run = _run(args, timeout)
        if run.returncode != 0 or not os.path.exists(gcode):
            raise _failed(run)
        return exe, "given"
    folder = os.path.dirname(gcode) or "."
    out_dir = os.path.join(folder, os.path.splitext(os.path.basename(gcode))[0] + f"-{name}")
    os.makedirs(out_dir, exist_ok=True)
    used = "given"
    if not all(profiles.get(k) for k in ("machine", "process", "filament")):
        written = minimal_profiles(settings, out_dir)
        profiles = {**written, **{k: v for k, v in profiles.items() if v}}
        used = "written" if not any(profiles.get(k) != written[k] for k in written) else "given and written"
    for k in ("machine", "process", "filament"):
        if not os.path.isfile(profiles[k]):
            raise RuntimeError(f"profiles.{k}: {profiles[k]} is not a file.")
    if options.get("overrides"):
        # Settings changed for this slice only, over the process preset.
        with open(profiles["process"], encoding="utf-8") as f:
            proc = json.load(f)
        proc.update({k: (v if isinstance(v, (str, list)) else str(v)) for k, v in options["overrides"].items()})
        p = os.path.join(out_dir, "agentlink-process-overrides.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(proc, f, indent=1)
        profiles = {**profiles, "process": p}
    three_mf = options.get("project") or os.path.join(out_dir, "out.3mf")
    for old in glob.glob(os.path.join(out_dir, "*.gcode")) + [os.path.join(out_dir, "result.json"), os.path.join(out_dir, "out.3mf")]:
        if os.path.exists(old):
            os.remove(old)
    args = [exe, "--slice", "0", "--load-settings", f"{profiles['machine']};{profiles['process']}", "--load-filaments", ";".join([profiles["filament"]] * len(stls)), "--outputdir", out_dir]
    if options.get("orient"):
        args += ["--orient", "1"]
    if options.get("arrange") or len(stls) > 1:
        args += ["--arrange", "1"]
    if name == "orcaslicer" and supports(exe, "--export-statistics"):
        args += ["--export-statistics"]
    if name == "bambustudio" or options.get("project"):
        # A bare name: OrcaSlicer puts the output folder in front of any path.
        args += ["--export-3mf", "out.3mf"]
    if name == "bambustudio":
        kinds = nozzle_volume_types(profiles["machine"])
        if kinds:
            # Each filament put on a nozzle by hand: left to itself the
            # command line reads past the end of its extruder list.
            # One entry per filament loaded (one per body): a shorter map
            # leaves the later filaments on no extruder.
            args += ["--nozzle-volume-type", ",".join(kinds), "--filament-map-mode", "Manual", "--filament-map", ",".join(["1"] * len(stls))]
    args += stls
    run = _run(args, timeout, cwd=out_dir)
    made = os.path.join(out_dir, "out.3mf")
    if options.get("project") and os.path.isfile(made) and os.path.abspath(made) != os.path.abspath(three_mf):
        shutil.move(made, three_mf)
    found = sorted(glob.glob(os.path.join(out_dir, "*.gcode")))
    if not found and os.path.isfile(three_mf):
        with zipfile.ZipFile(three_mf) as z:
            inner = sorted(n for n in z.namelist() if n.endswith(".gcode"))
            if inner:
                with z.open(inner[0]) as src, open(os.path.join(out_dir, "plate_1.gcode"), "wb") as dst:
                    shutil.copyfileobj(src, dst)
                found = [os.path.join(out_dir, "plate_1.gcode")]
    if not found:
        why = result_error(out_dir)
        raise _failed(run, why)
    shutil.copyfile(found[0], gcode)
    LAST.update(results(out_dir))
    return exe, used


SLICE_FLAGS = {"timelapse": "--enable-timelapse", "allow_mix_temp": "--allow-mix-temp", "allow_multicolor_oneplate": "--allow-multicolor-oneplate",
               "no_check": "--no-check", "skip_modified_gcodes": "--skip-modified-gcodes", "load_defaultfila": "--load-defaultfila", "allow_newer_file": "--allow-newer-file"}
SLICE_VALUES = {"skip_objects": "--skip-objects", "mtcpp": "--mtcpp", "mstpp": "--mstpp", "clone_objects": "--clone-objects", "load_filament_ids": "--load-filament-ids"}


def _slice_project(name, threemf, out_dir, timeout=900, export=None, plate=0, options=None, bake_textures=False):
    """A project (.3mf) sliced as it stands — its own presets, settings,
    plates and objects, as the person left them in the slicer's window.
    export: a .3mf path for the sliced project. bake_textures: bake painted
    texture displacement into the parts first (--bake-texture-displacement).
    Returns (exe, [G-code paths]) and fills LAST."""
    exe = find(name)
    if not exe:
        raise FileNotFoundError(f"{name} is not on this computer.")
    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, "*.gcode")) + glob.glob(os.path.join(out_dir, "plate_*.statistics.json")) + [os.path.join(out_dir, "result.json")]:
        if os.path.exists(old):
            os.remove(old)
    args = [exe, "--slice", str(int(plate or 0)), "--outputdir", out_dir]
    if name == "orcaslicer" and supports(exe, "--export-statistics"):
        args += ["--export-statistics"]
    if export:
        args += ["--export-3mf", "sliced.3mf"]
    if bake_textures:
        args += ["--bake-texture-displacement"]
    for k, v in (options or {}).items():
        if k in SLICE_FLAGS:
            if v:
                args.append(SLICE_FLAGS[k])
        elif k in SLICE_VALUES:
            args += [SLICE_VALUES[k], str(v)]
        else:
            raise RuntimeError(f"options.{k}: one of {', '.join(list(SLICE_FLAGS) + list(SLICE_VALUES))}.")
    args += [os.path.abspath(threemf)]
    LAST.clear()
    t0 = time.time()
    run = _run(args, timeout, cwd=out_dir)
    orca_ms = int((time.time() - t0) * 1000)
    found = sorted(glob.glob(os.path.join(out_dir, "*.gcode")))
    if export and os.path.isfile(os.path.join(out_dir, "sliced.3mf")):
        shutil.move(os.path.join(out_dir, "sliced.3mf"), export)
    if not found:
        why = result_error(out_dir)
        raise _failed(run, why)
    LAST.update(results(out_dir))
    LAST["orcaMs"] = orca_ms
    return exe, found


def _make_project(name, stls, dest, settings, profiles=None, options=None, timeout=600):
    """An unsliced project (.3mf) from STLs, one object each, with the
    profiles given (or minimal ones from settings): what the window makes
    when the files are dropped on its plate. options: orient, arrange."""
    exe = find(name)
    if not exe:
        raise FileNotFoundError(f"{name} is not on this computer.")
    options = options or {}
    out_dir = os.path.splitext(dest)[0] + "-cli"
    os.makedirs(out_dir, exist_ok=True)
    profiles = profiles or {}
    if not all(profiles.get(k) for k in ("machine", "process", "filament")):
        profiles = {**minimal_profiles(settings, out_dir), **{k: v for k, v in profiles.items() if v}}
    for old in (os.path.join(out_dir, "project.3mf"), os.path.join(out_dir, "result.json")):
        if os.path.exists(old):
            os.remove(old)
    args = [exe, "--load-settings", f"{profiles['machine']};{profiles['process']}", "--load-filaments", ";".join([profiles["filament"]] * len(stls)),
            "--arrange", "1" if options.get("arrange", True) else "0", "--outputdir", out_dir, "--export-3mf", "project.3mf"]
    if options.get("orient"):
        args += ["--orient", "1"]
    args += [os.path.abspath(x) for x in stls]
    run = _run(args, timeout, cwd=out_dir)
    made = os.path.join(out_dir, "project.3mf")
    if not os.path.isfile(made):
        # Some builds export only what they slice: slice, then drop the results.
        run = _run(args[:1] + ["--slice", "0"] + args[1:], timeout, cwd=out_dir)
        if os.path.isfile(made):
            from . import orca3mf

            pr = orca3mf.Project(made)
            pr.strip_results()
            pr.changed = False
            pr.save()
    if not os.path.isfile(made):
        why = result_error(out_dir)
        raise _failed(run, why)
    shutil.move(made, dest)
    return exe


RELAYOUT_FLAGS = ("allow_rotations", "align_to_y_axis", "avoid_extrusion_cali_region", "allow_multicolor_oneplate", "ensure_on_bed", "uptodate",
                  "min_save", "allow_newer_file", "skip_modified_gcodes", "repair", "ground_largest_face", "convert_unit")


def _relayout(name, threemf, arrange=False, orient=False, options=None, timeout=600):
    """The project's objects arranged on their plates and/or turned to their
    best side by the slicer itself, the project re-saved in place. options:
    any of RELAYOUT_FLAGS (true), clone_objects "1,3,…", repetitions n,
    scale f, rotate/rotate_x/rotate_y degrees, ground_face_normal "x,y,z"."""
    exe = find(name)
    if not exe:
        raise FileNotFoundError(f"{name} is not on this computer.")
    out_dir = os.path.splitext(threemf)[0] + "-layout"
    os.makedirs(out_dir, exist_ok=True)
    made = os.path.join(out_dir, "layout.3mf")
    if os.path.exists(made):
        os.remove(made)
    args = [exe, "--outputdir", out_dir]
    if arrange:
        args += ["--arrange", "1"]
    if orient:
        args += ["--orient", "1"]
    for k, v in (options or {}).items():
        if k in RELAYOUT_FLAGS:
            if v:
                args += ["--" + k.replace("_", "-")]
        elif k in ("clone_objects", "repetitions", "scale", "rotate", "rotate_x", "rotate_y", "ground_face_normal", "ground_face_point"):
            args += ["--" + k.replace("_", "-"), str(v)]
        else:
            raise RuntimeError(f"options.{k}: one of {', '.join(RELAYOUT_FLAGS)}, clone_objects, repetitions, scale, rotate, rotate_x, rotate_y, ground_face_normal, ground_face_point.")
    args += ["--export-3mf", "layout.3mf", os.path.abspath(threemf)]
    run = _run(args, timeout, cwd=out_dir)
    if not os.path.isfile(made):
        why = result_error(out_dir)
        raise _failed(run, why)
    shutil.move(made, threemf)
    return exe


def _inspect(name, threemf, what="mesh", timeout=300):
    """The slicer's own report on a project: what mesh (--inspect-mesh, each
    object's size and mesh), paint (--inspect-paint, painted layers) or info
    (--info). JSON when it prints JSON, else the text."""
    exe = find(name)
    if not exe:
        raise FileNotFoundError(f"{name} is not on this computer.")
    flag = {"mesh": "--inspect-mesh", "paint": "--inspect-paint", "info": "--info"}[what]
    if not supports(exe, flag):
        raise RuntimeError(f"This {name} has no {flag}.")
    run = _run([exe, flag, os.path.abspath(threemf)], timeout)
    text = run.stdout or ""
    if run.returncode != 0 and not text.strip():
        raise _failed(run)
    i = min([x for x in (text.find("{"), text.find("[")) if x >= 0] or [-1])
    if i >= 0:
        try:
            return json.loads(text[i:text.rfind("}" if text[i] == "{" else "]") + 1])
        except ValueError:
            pass
    return {"text": text.strip()[-6000:]}


EXPORTS = {"stl": ("--export-stl", None), "stls": ("--export-stls", "stls"), "settings": ("--export-settings", "settings.json"),
           "slicedata": ("--export-slicedata", "slicedata"), "3mf": ("--export-3mf", "export.3mf")}


def _export_project(name, threemf, out_dir, what, filename=None, timeout=600):
    """A project's objects or settings written out by the command line:
    what stl (all objects in one), stls (one each, a folder), settings (the
    project's config as JSON), slicedata (the sliced layers, a folder) or
    3mf (re-saved by the slicer). Returns the files made."""
    exe = find(name)
    if not exe:
        raise FileNotFoundError(f"{name} is not on this computer.")
    if what not in EXPORTS:
        raise ValueError(f"export: {', '.join(EXPORTS)}.")
    os.makedirs(out_dir, exist_ok=True)
    flag, arg = EXPORTS[what]
    before = set(os.listdir(out_dir))
    args = [exe, "--outputdir", out_dir]
    if what == "slicedata":
        args += ["--slice", "0"]
    args += [flag] + ([filename or arg] if arg else []) + [os.path.abspath(threemf)]
    run = _run(args, timeout, cwd=out_dir)
    made = sorted(os.path.join(out_dir, n) for n in set(os.listdir(out_dir)) - before if n != "result.json")
    if not made:
        why = result_error(out_dir)
        raise _failed(run, why)
    return made


# ---- no program from data (red team 3, R3-2) ---------------------------------------------------
# A slicer runs the programs a project or a profile names in post_process
# (and loads plugins) after it writes the G-code. Every file a slicer reads
# here goes to it with those keys empty: a copy in a temporary folder (the
# person's own file is not changed), removed after the run. Keys emptied in
# the last run's files: PROGRAMS_EMPTIED.
PROGRAMS_EMPTIED = []
_MARKS = (b"post_process", b"plugin")


def _3mf_has_programs(path):
    try:
        with zipfile.ZipFile(path) as z:
            for i in z.infolist():
                if i.filename.startswith("Metadata/") and i.filename.endswith(".config") and i.file_size < 64 * 1024 * 1024:
                    data = z.read(i)
                    if any(m in data for m in _MARKS):
                        return True
    except (OSError, zipfile.BadZipFile):
        return False
    return False


class _Clean:
    """Files for a slicer with every program key emptied."""

    def __init__(self):
        self.dir = None
        self.emptied = []

    def _copy_path(self, path):
        if self.dir is None:
            self.dir = tempfile.mkdtemp(prefix="orcalink-clean-")
        n = len(os.listdir(self.dir))
        return os.path.join(self.dir, f"{n}-{os.path.basename(path)}")

    def file(self, path):
        if not isinstance(path, str) or not os.path.isfile(path):
            return path
        low = path.lower()
        if low.endswith(".3mf"):
            if not _3mf_has_programs(path):
                return path
            from . import orca3mf

            pr = orca3mf.Project(path)
            hit = pr.empty_programs()
            if not hit:
                return path
            self.emptied += hit
            return pr.save(self._copy_path(path))
        if low.endswith(".json"):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                return path
            hit = guard.empty_programs(data) if isinstance(data, dict) else []
            if not hit:
                return path
            self.emptied += hit
            q = self._copy_path(path)
            with open(q, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=1)
            return q
        if low.endswith((".ini", ".config")):
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            hit = list(guard.ini_programs(text))
            if not hit:
                return path
            self.emptied += hit
            q = self._copy_path(path)
            with open(q, "w", encoding="utf-8") as f:
                f.write(guard.ini_empty(text))
            return q
        return path

    def profiles(self, profiles):
        return {k: self.file(v) for k, v in (profiles or {}).items()}

    def close(self):
        PROGRAMS_EMPTIED[:] = sorted(set(self.emptied))
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)


def slice_with(name, stl, gcode, settings, profiles=None, timeout=900, options=None):
    """See _slice_with. Program keys refused in options.overrides and
    emptied in every profile (a PrusaSlicer .ini too) and model project."""
    options = dict(options or {})
    bad = sorted(k for k in (options.get("overrides") or {}) if guard.is_program_key(k))
    if bad:
        raise RuntimeError(f"overrides: {', '.join(bad)} names a program or a plug-in that the slicer runs. It is never set here; a person adds it in the slicer's own window.")
    cl = _Clean()
    try:
        stls = [cl.file(x) for x in ([stl] if isinstance(stl, str) else list(stl))]
        return _slice_with(name, stls[0] if isinstance(stl, str) else stls, gcode, settings, cl.profiles(profiles), timeout, options)
    finally:
        cl.close()


def slice_project(name, threemf, out_dir, timeout=900, export=None, plate=0, options=None, bake_textures=False):
    """See _slice_project; the project goes to the slicer with its program
    keys emptied (a copy; the person's file is not changed)."""
    cl = _Clean()
    try:
        return _slice_project(name, cl.file(threemf), out_dir, timeout, export, plate, options, bake_textures)
    finally:
        cl.close()


def make_project(name, stls, dest, settings, profiles=None, options=None, timeout=600):
    """See _make_project; models and profiles go to the slicer with their
    program keys emptied, and the new project has none."""
    cl = _Clean()
    try:
        exe = _make_project(name, [cl.file(x) for x in stls], dest, settings, cl.profiles(profiles), options, timeout)
    finally:
        cl.close()
    if _3mf_has_programs(dest):
        from . import orca3mf

        orca3mf.Project(dest).save()
    return exe


def relayout(name, threemf, arrange=False, orient=False, options=None, timeout=600):
    """See _relayout. The slicer rewrites the project in place, so its
    program keys are emptied in place first."""
    if _3mf_has_programs(threemf):
        from . import orca3mf

        pr = orca3mf.Project(threemf)
        PROGRAMS_EMPTIED[:] = pr.empty_programs()
        pr.save()
    return _relayout(name, threemf, arrange, orient, options, timeout)


def inspect(name, threemf, what="mesh", timeout=300):
    cl = _Clean()
    try:
        return _inspect(name, cl.file(threemf), what, timeout)
    finally:
        cl.close()


def export_project(name, threemf, out_dir, what, filename=None, timeout=600):
    """See _export_project. filename: a file name only (no folders, not
    hidden)."""
    if filename is not None and (filename != os.path.basename(filename) or filename.startswith(".") or not filename.strip() or "\\" in filename):
        raise ValueError(f"name: a file name only, no folders and not hidden ({filename!r}).")
    cl = _Clean()
    try:
        return _export_project(name, cl.file(threemf), out_dir, what, filename, timeout)
    finally:
        cl.close()


_HELP = {}


def supports(exe, option):
    """Whether this slicer's command line takes option (its --help, read once)."""
    if exe not in _HELP:
        try:
            r = subprocess.run([exe, "--help"], capture_output=True, text=True, timeout=120)
            _HELP[exe] = (r.stdout or "") + (r.stderr or "")
        except Exception:
            _HELP[exe] = ""
    return option in _HELP[exe]


def fmt_time(sec):
    sec = int(round(sec or 0))
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return (f"{h}h " if h else "") + (f"{m}m " if h or m else "") + f"{s}s"


def statistics(path):
    """OrcaSlicer's plate_N.statistics.json (2.5 on, --export-statistics),
    in brief: time, filament and cost, what of it is model, support, prime
    tower and flush, the features by time, and each object's share."""
    with open(path, encoding="utf-8") as f:
        st = json.load(f)
    sm = st.get("summary") or {}
    out = {"time": fmt_time(sm.get("time")), "timeS": sm.get("time"), "weightG": sm.get("weight"), "cost": sm.get("filament_cost"),
           "layers": sm.get("layer_count"), "filamentChanges": sm.get("filament_changes"), "travelMm": sm.get("travel_distance")}
    split = {}
    for fil in sm.get("filaments") or []:
        for part in ("model", "support", "prime_tower", "flush"):
            w = (fil.get(part) or {}).get("weight")
            if w:
                split[part] = round(split.get(part, 0) + w, 3)
    if split:
        out["weightBy"] = split
    feats = sm.get("features") or {}
    total = sum((v or {}).get("time", 0) for v in feats.values()) or 1
    out["features"] = [{"feature": k, "time": fmt_time(v.get("time")), "share%": round(100 * v.get("time", 0) / total), "weightG": v.get("weight")}
                       for k, v in sorted(feats.items(), key=lambda kv: -(kv[1] or {}).get("time", 0))[:8]]
    objs = st.get("objects")
    if isinstance(objs, list) and objs:
        out["objects"] = [{k: o.get(k) for k in ("name", "id", "time", "weight", "volume") if k in o} for o in objs[:20]]
    elif isinstance(objs, dict) and objs:
        out["objects"] = [{"name": k, **{kk: vv for kk, vv in (v or {}).items() if kk in ("time", "weight", "volume")}} for k, v in list(objs.items())[:20]]
    return out


def results(out_dir):
    """What the slicer said beside the G-code: result.json's warnings, and
    the plate statistics when written."""
    out = {}
    try:
        with open(os.path.join(out_dir, "result.json"), encoding="utf-8") as f:
            r = json.load(f)
        warns = [w for w in (r.get("warnings") or []) if w]
        warns += [p["warning_message"] for p in (r.get("sliced_plates") or []) if p.get("warning_message")]
        # Always there once result.json is read: [] is OrcaSlicer saying
        # nothing, not a list that was not read.
        out["warnings"] = warns
    except (OSError, ValueError):
        out["warnings"] = None
    stats = sorted(glob.glob(os.path.join(out_dir, "plate_*.statistics.json")))
    if stats:
        try:
            out["statistics"] = statistics(stats[0])
        except (OSError, ValueError):
            pass
    return out


def result_error(out_dir):
    """The slicer's own word on a failed slice: OrcaSlicer and Bambu Studio
    write result.json beside the plates, with an error string."""
    try:
        with open(os.path.join(out_dir, "result.json"), encoding="utf-8") as f:
            r = json.load(f)
    except (OSError, ValueError):
        return None
    if r.get("return_code") in (0, None) and not r.get("error_string"):
        return None
    return f"{r.get('error_string') or 'failed'} (code {r.get('return_code')})"


def nozzle_volume_types(machine_path):
    """One nozzle volume type per nozzle for a printer with more than one
    (an H2D): Bambu Studio's command line does not seed them from the
    printer as its window does, and stops — or crashes — without them. None
    for a printer with one nozzle."""
    try:
        with open(machine_path, encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError):
        return None
    nozzles = m.get("nozzle_diameter")
    n = len(nozzles) if isinstance(nozzles, list) else 1
    if n < 2:
        return None
    given = m.get("nozzle_volume_type") or m.get("default_nozzle_volume_type") or []
    if isinstance(given, str):
        given = [given]
    return [(given[i] if i < len(given) else (given[-1] if given else "Standard")) for i in range(n)]


_ERRLINE = re.compile(r"\[(error|fatal)\]|found error|conflicts? found|error:", re.I)


def own_errors(text, most=5):
    """The slicer's own error lines in its output, in order, each once: the
    log prefix (time, thread, level) cut off. The last lines alone can hide
    them ("run found error" with the cause some lines up)."""
    out = []
    for line in (text or "").splitlines():
        if not _ERRLINE.search(line):
            continue
        msg = re.sub(r"^(\s*\[[^\]]*\])+\s*", "", line).strip()
        msg = msg[:300]
        if msg and msg not in out:
            out.append(msg)
    return out[:most]


def _tail(run):
    text = (run.stderr or "") + "\n" + (run.stdout or "")
    lines = text.strip().splitlines()
    tail = [l for l in lines if l.strip()][-3:]
    errs = [e for e in own_errors(text) if not any(e in t for t in tail)]
    if errs:
        tail = errs + tail
    # Which build stopped matters: the slicers' command lines change a lot
    # between releases (Bambu Studio's for two-nozzle printers above all).
    version = next((l.split("]")[-1].strip() for l in lines if re.search(r"version", l, re.I) and re.search(r"\d+\.\d+\.\d+", l)), None)
    return f"The slicer stopped (code {run.returncode}): {' / '.join(tail) or 'no G-code written'}" + (f" [{version}]" if version else "")


# ---- reading and pausing any of them ------------------------------------------------------

_LAYER = re.compile(r"^;\s*(LAYER_CHANGE|CHANGE_LAYER)\s*$")
_Z = re.compile(r"^;\s*(?:Z|Z_HEIGHT)\s*[:=]\s*([\d.]+)")


def read_gcode(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()

    def grab(*patterns):
        for pat in patterns:
            m = re.search(pat, text, re.M)
            if m:
                return m.group(1).strip()
        return None

    layers = sum(1 for line in text.splitlines() if _LAYER.match(line))
    g = grab(r";\s*(?:total )?filament used \[g\]\s*=\s*([\d.]+)", r";\s*total filament weight \[g\]\s*:\s*([\d.]+)")
    mm = grab(r";\s*(?:total )?filament used \[mm\]\s*=\s*([\d.]+)", r";\s*total filament length \[mm\]\s*:\s*([\d.]+)")
    t = grab(r";\s*estimated printing time \(normal mode\)\s*=\s*(.+)", r";\s*total estimated time\s*:\s*(.+)", r";\s*model printing time\s*:\s*([^;]+)")
    return {"layers": layers, "filamentG": float(g) if g else None, "filamentMm": float(mm) if mm else None, "time": t}


def insert_pauses(path, pauses, command):
    """Each pause before the first layer whose height is past its z, by the
    layer marks any of the three slicers writes. Returns where they went.
    command: one of M601, M600, M0, M1, PAUSE (one line, nothing else); a
    note goes in as one comment line."""
    command = guard.pause_command(command)
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().split("\n")
    todo = sorted(pauses, key=lambda p: p["z"])
    out, done = [], []
    for i, line in enumerate(lines):
        if todo and _LAYER.match(line):
            z = None
            for nxt in lines[i + 1:i + 4]:
                m = _Z.match(nxt)
                if m:
                    z = float(m.group(1))
                    break
            if z is not None:
                while todo and z > todo[0]["z"] + 1e-6:
                    p = todo.pop(0)
                    note = guard.one_line(p.get("note"))
                    out += [f"; pause: {note}", "M400", f"{command} ; {note}"]
                    done.append({"z": z, "note": note})
        out.append(line)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return done
