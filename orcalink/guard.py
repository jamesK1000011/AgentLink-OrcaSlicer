# SPDX-License-Identifier: LGPL-2.1-or-later
# The checks every tool of this server shares (red team 3, 19 Nov 2026).
# An agent can be steered by what it reads (a model file, a web page), so:
#  - paths: secret folders are refused for reads and writes; writes go only
#    in the output folder, the home folder or the temporary folder, never in
#    a hidden folder, only with the expected extension, over a file only
#    when asked (the same rules as Agent Link for FreeCAD's paths.check);
#  - slicer keys that name a program or a plug-in (post_process …) are
#    refused when set and emptied before a slicer reads a project or a
#    profile: a slicer runs that program after it writes the G-code;
#  - G-code that changes the printer, heats over the caps, or turns the
#    motors or the power off is found in every G-code text a tool writes;
#  - text from files goes to the agent without invisible characters and
#    capped;
#  - paths under the home folder show as ~/... in results and errors.

import json
import os
import re
import tempfile
import unicodedata

from .protocol import ToolError

# ---- paths ------------------------------------------------------------------------------------

SECRET_PARTS = {".ssh", ".aws", ".gnupg", ".kube", ".docker", ".config", ".netrc", ".git", ".password-store", "keychains",
                ".zshrc", ".bashrc", ".profile", ".bash_profile", ".zprofile", ".env"}
NEVER_WRITE_EXT = {".sh", ".bash", ".zsh", ".command", ".tool", ".py", ".pyc", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".php",
                   ".app", ".plist", ".dylib", ".so", ".dll", ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".scpt", ".applescript", ".workflow",
                   ".service", ".desktop", ".kext", ".pkg", ".dmg", ".jar", ".fcmacro", ".pth", ".pyz", ".pyd", ".whl", ".egg"}
# In ~/Library a tool reads only the slicers' own preset folders.
LIBRARY_READ = ("library/application support/orcaslicer", "library/application support/bambustudio", "library/application support/prusaslicer")


def _real(p):
    return os.path.realpath(os.path.expanduser(p))


def _parts(p):
    return [x for x in str(p).replace("\\", "/").split("/") if x]


def _under(p, root):
    return p == root or p.startswith(root.rstrip("/") + "/")


def home():
    return _real("~")


def roots(out_dir):
    """Where a tool may write: the output folder, home, the temporary folder
    (never the disk's root)."""
    got = [_real(out_dir) if out_dir else None, home(), _real("/tmp"), _real(os.environ.get("TMPDIR") or "/tmp"), _real(tempfile.gettempdir())]
    out = []
    for r in got:
        if r and r != "/" and r not in out:
            out.append(r)
    return out


def check(p, out_dir, write=False, ext=None, key="path", new=False, overwrite=False):
    """p (absolute, ~ expanded) when a tool may read it, or write it when
    write; else ToolError invalid_input. ext: the extension (or a tuple of
    them) a written file must have. new: a file made at a path that was
    given: a file that is there is refused unless overwrite."""
    if not isinstance(p, str) or not p.strip():
        raise ToolError("invalid_input", f"{key}: a path.")
    q = os.path.expanduser(p.strip())
    if not os.path.isabs(q):
        q = os.path.join(out_dir, q)
    real = _real(q)
    folded = [x.casefold() for x in _parts(real)]
    secret = next((x for x in folded if x in SECRET_PARTS), None)
    if secret:
        raise ToolError("invalid_input", f"{key}: {tilde(q)} is in {secret}: credentials and shell settings are off limits.")
    h = home()
    rel = os.path.relpath(real, h).replace(os.sep, "/").casefold() if _under(real, h) else ""
    in_lib = rel == "library" or rel.startswith("library/")
    if in_lib and (write or not any(rel == r or rel.startswith(r + "/") for r in LIBRARY_READ)):
        raise ToolError("invalid_input", f"{key}: {tilde(q)} is in ~/Library, where apps keep their settings: not {'written' if write else 'read'} by this server.")
    if not write:
        return q
    from . import addons

    if addons.inside_app(real):
        raise ToolError("invalid_input", f"{os.path.basename(q)}: not in this server's own folder; write in the output folder.")
    root = next((r for r in roots(out_dir) if _under(real, r)), None)
    if root is None:
        raise ToolError("invalid_input", f"{key}: {tilde(q)}: files are written in the output folder, the home folder or the temporary folder, not there.")
    hidden = next((x for x in _parts(os.path.relpath(real, root)) if x.startswith(".") and x not in (".",)), None)
    if hidden:
        raise ToolError("invalid_input", f"{key}: {tilde(q)} is hidden ({hidden}): write it in a visible folder, with a visible name.")
    base = os.path.basename(q)
    if base != base.rstrip(". "):
        raise ToolError("invalid_input", f"{key}: {tilde(q)} ends in a dot or a space: give the file its own extension.")
    e = os.path.splitext(real)[1].lower()
    if e in NEVER_WRITE_EXT:
        raise ToolError("invalid_input", f"{key}: {tilde(q)}: this server writes models, drawings, data and G-code, never {e} files.")
    if ext:
        want = (ext,) if isinstance(ext, str) else tuple(ext)
        if not q.lower().endswith(tuple(x.lower() for x in want)):
            raise ToolError("invalid_input", f"{key}: {base}: a {' or '.join(want)} file.")
    if os.path.islink(q):
        raise ToolError("invalid_input", f"{key}: {tilde(q)} is a link: give the file itself.")
    if new and os.path.exists(q) and not overwrite:
        raise ToolError("invalid_input", f"{tilde(q)} is there already: overwrite true replaces it.")
    return q


# ---- slicer keys that run a program -----------------------------------------------------------

# post_process: programs the slicer runs on the G-code it wrote (OrcaSlicer,
# PrusaSlicer, Bambu Studio); plugins / slicing_pipeline_plugin: code the
# slicer loads.
PROGRAM_KEYS = {"post_process", "plugins", "slicing_pipeline_plugin"}


def is_program_key(k):
    k = str(k).strip().lower()
    return k in PROGRAM_KEYS or "post_process" in k or "plugin" in k


def _filled(v):
    if isinstance(v, (list, tuple)):
        return any(str(x).strip() for x in v)
    return v is not None and str(v).strip() != ""


def programs_in(config):
    """{key: value (capped)} of the keys in config that name a program and
    are not empty."""
    if not isinstance(config, dict):
        return {}
    return {k: text(json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v, 200) for k, v in config.items() if is_program_key(k) and _filled(v)}


def empty_programs(config):
    """Every program key in config emptied in place; answers the keys."""
    hit = [k for k, v in (config or {}).items() if is_program_key(k) and _filled(v)]
    for k in hit:
        config[k] = [] if isinstance(config[k], (list, tuple)) else ""
    return hit


def refuse_programs(keys, where="settings"):
    bad = sorted(k for k in keys if is_program_key(k))
    if bad:
        raise ToolError("not_allowed", f"{where}: {', '.join(bad)} names a program or a plug-in that the slicer runs. This server never sets it, and empties it before a slice. "
                                       "A person who wants a post-processing script adds it in OrcaSlicer's own window.")


def ini_programs(text_):
    """{key: value} of program keys in a PrusaSlicer .ini that are not empty."""
    out = {}
    for line in text_.splitlines():
        if "=" in line and not line.lstrip().startswith(("#", ";")):
            k, v = line.split("=", 1)
            if is_program_key(k) and v.strip():
                out[k.strip()] = v.strip()[:200]
    return out


def ini_empty(text_):
    lines = []
    for line in text_.splitlines():
        if "=" in line and not line.lstrip().startswith(("#", ";")) and is_program_key(line.split("=", 1)[0]):
            line = line.split("=", 1)[0].rstrip() + " = "
        lines.append(line)
    return "\n".join(lines) + "\n"


# ---- G-code -----------------------------------------------------------------------------------

NOZZLE_MAX = 350.0
BED_MAX = 130.0
# Commands that change the printer itself, turn off a protection or the
# power: never written without the person.
RISKY = {"M997": "firmware update", "M500": "saves settings to the printer", "M502": "factory reset", "M501": "reloads saved settings",
         "M211": "software endstops", "M302": "cold extrusion", "M303": "PID autotune", "M112": "emergency stop", "M552": "network", "M587": "Wi-Fi",
         "M906": "motor current", "M92": "steps per mm", "M851": "probe offset", "M80": "power supply on", "M81": "power supply off",
         "M999": "restart after a stop", "FIRMWARE_RESTART": "firmware restart (Klipper)", "SAVE_CONFIG": "saves the configuration (Klipper)",
         "RESTART": "host restart (Klipper)"}
# Motors off: normal at the end of a print, not in the middle of one.
MID_PRINT = {"M18": "motors off mid-print", "M84": "motors off mid-print"}
HEAT = {"M104": ("nozzle", NOZZLE_MAX), "M109": ("nozzle", NOZZLE_MAX), "M140": ("bed", BED_MAX), "M190": ("bed", BED_MAX)}
FANS = {"M106", "M107"}
# M400 U1: Bambu Studio's own pause (cli.PAUSE).
PAUSES = ("M601", "M600", "M0", "M1", "PAUSE", "M400 U1")
_NUMBERED = re.compile(r"^\s*N\d+\s*", re.I)
_LETTER = re.compile(r"^\s*([A-Za-z])\s*(\d+)(?!\d)(.*)$")
_WORD = re.compile(r"^\s*([A-Za-z_]+)\b(.*)$")


def _code(line):
    """(code, rest) of a G-code line: "M104", "S300" for "N12 m0104s300";
    a word command (PAUSE, SAVE_CONFIG) as it is; None for none."""
    line = _NUMBERED.sub("", line.split(";", 1)[0])
    m = _LETTER.match(line)
    if m:
        return m.group(1).upper() + str(int(m.group(2))), m.group(3)
    m = _WORD.match(line)
    return (m.group(1).upper(), m.group(2)) if m else None
_PARAM = re.compile(r"([SR])\s*(-?\d+(?:\.\d+)?)", re.I)


def gcode_scan(text_, mid=True):
    """(risky {code: what}, fans [lines]) in G-code text. mid: the text runs
    in the middle of a print (motors off is risky there). Temperatures with
    a placeholder ([nozzle_temperature] …) are the slicer's own and pass."""
    risky, fans = {}, []
    for line in str(text_ or "").splitlines():
        code_part = line.split(";", 1)[0].strip()
        got = _code(code_part)
        if not got:
            continue
        code, rest = got
        if code in RISKY:
            risky[code] = RISKY[code]
        elif mid and code in MID_PRINT:
            risky[code] = MID_PRINT[code]
        elif code in HEAT:
            what, cap = HEAT[code]
            for _, v in _PARAM.findall(rest):
                if float(v) > cap:
                    risky[code] = f"{what} {float(v):g} °C, over {cap:g} °C"
        elif code in FANS:
            fans.append(text(code_part, 80))
    return risky, fans


def pause_command(cmd):
    """A pause command: one of PAUSES, one line; else ValueError."""
    c = str(cmd or "").strip()
    if "\n" in c or "\r" in c or c.upper() not in PAUSES:
        raise ValueError(f"pause command {text(c, 40)!r}: one of {', '.join(PAUSES)}, one line, nothing else.")
    return c.upper()


def one_line(s, cap=120):
    """Text for a G-code comment: one line, no control characters."""
    return text(" ".join(str(s or "").split()), cap)


# ---- text from files --------------------------------------------------------------------------

def text(s, cap=200):
    """Text from a file or a device for the agent: Unicode format characters
    (category Cf: zero-width, direction marks) and the tag block removed,
    other control characters but new lines and tabs removed, capped."""
    if s is None:
        return s
    s = str(s)
    out = "".join(c for c in s if not (unicodedata.category(c) == "Cf" or 0xE0000 <= ord(c) <= 0xE007F
                                       or (unicodedata.category(c) == "Cc" and c not in "\n\t")))
    return out[:cap] + ("…" if len(out) > cap else "")


# ---- paths shown --------------------------------------------------------------------------

def tilde(obj):
    """Paths under the home folder as ~/... in every string of obj."""
    h = os.path.expanduser("~").rstrip("/")
    hs = [x for x in dict.fromkeys((h, _real(h))) if x and x != "/"]

    def one(s):
        for x in hs:
            s = re.sub(re.escape(x) + r"(?![\w.-])", "~", s)
        return s

    if isinstance(obj, str):
        return one(obj)
    if isinstance(obj, dict):
        return {k: tilde(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [tilde(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(tilde(v) for v in obj)
    return obj
