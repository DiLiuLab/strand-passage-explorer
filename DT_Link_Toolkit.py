#!/usr/bin/env python3
"""Universal launcher for the DT Link Toolkit.

Starts any of the toolkit's tools from one entry point, as a small graphical
launcher or from the command line:

    DT_Link_Toolkit.py                       graphical launcher (no arguments)
    DT_Link_Toolkit.py <tool> [arguments]    run one tool directly
    DT_Link_Toolkit.py --list                show what each tool resolves to
    DT_Link_Toolkit.py --menu                text menu instead of the GUI

Tools:
    draw             DT diagram drawing and 3-D XYZ export
    strand-passage   Strand-passage explorer (GUI / --nongui / --demo)
    score            Diagram generation, deduplication, and scoring
    canonical        Canonical DT code and diagram symmetry
    figure           Extract a DT code from a diagram image
    find             Search SnapPy databases for a DT match

Version-independent tool lookup
-------------------------------
Several tool scripts carry a version number in their filename (for example
``draw_dt_original_labelsV5_5.py``).  The launcher does not hard-code these: for
each tool it finds every matching ``<base>*.py`` in this directory and picks the
highest version, so a newer ``...V5_6.py`` or ``...V6_0.py`` is used
automatically once added, with no edit to this file.

Interpreter selection
---------------------
The toolkit can run under Sage's Python (which provides the Sage algebra used
for Jones polynomials) or under a plain Python 3.  Neither is always the right
answer, so the launcher *probes* each available interpreter once and caches what
it found:

  * ``tkagg``   -- can matplotlib open a Tk window?  (needed by every GUI tool)
  * ``sage``    -- is the Sage library importable?   (needed for Jones under Sage)
  * ``snappy``  -- is SnapPy importable?
  * ``skimage`` -- is scikit-image importable?       (needed by the figure tool)

A GUI run is then sent to an interpreter whose TkAgg actually works, and a
headless run prefers an interpreter that has Sage.  This matters in practice: a
Sage built against Tcl/Tk 9 can ship a matplotlib whose ``_tkagg`` still expects
Tcl 8, which fails at import with "Failed to load Tcl_SetVar" -- Sage is then
perfectly good for headless work but cannot open a GUI.  A tool can also declare
capability ``needs`` (the figure tool needs ``skimage``, which typically lives in
the plain Python 3 rather than Sage); such a tool is steered to an interpreter
that satisfies them for both its GUI and headless runs.  Override the choice with
``--interp sage`` or ``--interp python``, and re-probe with ``--rescan``.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

PROJECT_DIR = Path(__file__).resolve().parent

CACHE_VERSION = 2   # bumped when the probe's capability set changed (added skimage)
CACHE_DIR = Path(
    os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
) / "dt_link_toolkit"
CACHE_FILE = CACHE_DIR / "interpreters.json"

PROBE_TIMEOUT = 180  # seconds; a cold Sage start can be slow


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------

class Tool(NamedTuple):
    key: str                      # canonical name
    base: str                     # filename stem before any ``V<version>``
    aliases: Tuple[str, ...]
    desc: str
    gui: str                      # "optional" | "default" | "never"
    headless_flags: Tuple[str, ...] = ()
    needs: Tuple[str, ...] = ()   # capabilities the tool requires (probe keys),
    #                               e.g. ("skimage",); steers interpreter choice


# ``gui`` says how the tool decides between a window and a headless run:
#   "optional" -- GUI when given no arguments or --gui   (draw, score, canonical)
#   "default"  -- GUI unless a headless flag is present  (strand-passage)
#   "never"    -- always headless                        (find)
TOOLS: Tuple[Tool, ...] = (
    Tool(
        key="draw",
        base="draw_dt_original_labels",
        aliases=("draw", "drawing", "labels", "diagram"),
        desc="DT diagram drawing and 3-D XYZ export",
        gui="optional",
    ),
    Tool(
        key="strand-passage",
        base="strand_passage_gui",
        aliases=("strand-passage", "strand_passage", "passage", "gui", "sp"),
        desc="Strand-passage explorer (GUI / --nongui / --demo)",
        gui="default",
        headless_flags=("--nongui", "--demo"),
    ),
    Tool(
        key="score",
        base="score_diagram",
        aliases=("score", "scoring", "diagram-score"),
        desc="Diagram generation, deduplication, and scoring",
        gui="optional",
    ),
    Tool(
        key="canonical",
        base="canonical_dt",
        aliases=("canonical", "canonical-dt", "canon", "symmetry"),
        desc="Canonical DT code and diagram symmetry",
        gui="optional",
    ),
    Tool(
        key="figure",
        base="figure_to_dt",
        aliases=("figure", "figure-to-dt", "image", "img2dt", "trace"),
        desc="Extract a DT code from a diagram image",
        gui="optional",
        # Needs scikit-image (both trace and fill methods); on this setup only the
        # plain Python 3 has it, not Sage -- so both its GUI and headless runs are
        # steered to a skimage-capable interpreter rather than the usual Sage one.
        needs=("skimage",),
    ),
    Tool(
        key="find",
        base="find_link_in_snappy",
        aliases=("find", "search", "snappy", "find-link"),
        desc="Search SnapPy databases for a DT match",
        gui="never",
    ),
)


def _version_key(version: Optional[str]) -> Tuple[int, ...]:
    """Sort key for a ``V<...>`` filename suffix.

    ``"V5_5"`` -> ``(5, 5)``, ``"V12"`` -> ``(12,)``, no suffix -> ``()``.
    An unversioned file therefore sorts below any versioned one, so a versioned
    script is preferred when both exist.
    """
    if not version:
        return ()
    return tuple(int(n) for n in re.findall(r"\d+", version))


def resolve_script(tool: Tool, root: Path = PROJECT_DIR) -> Optional[Path]:
    """Return the highest-versioned script file for ``tool``, or None."""
    # <base>, optionally followed by a version, then .py -- and nothing else.
    # The repository uses several suffix styles, all of which must be accepted:
    #   draw_dt_original_labelsV5_5.py   V, no separator
    #   link_engine_v4_0.py              _v, lowercase
    #   canonical_dt_V2_0.py             _V, uppercase
    # Requiring a v/V + digit after the optional separator keeps a sibling like
    # ``score_diagram_helper.py`` from being mistaken for the tool.
    pattern = re.compile(
        r"^" + re.escape(tool.base) + r"(?:[_-]?[Vv](?P<ver>\d[A-Za-z0-9_.]*))?\.py$"
    )
    candidates: List[Tuple[Tuple[int, ...], str, Path]] = []
    for path in root.glob(tool.base + "*.py"):
        match = pattern.match(path.name)
        if not match:
            continue
        candidates.append((_version_key(match.group("ver")), path.name, path))
    if not candidates:
        return None
    candidates.sort()  # highest version last; filename breaks ties
    return candidates[-1][2]


def find_tool(token: str) -> Optional[Tool]:
    needle = token.strip().lower()
    for tool in TOOLS:
        if needle == tool.key or needle in tool.aliases:
            return tool
    return None


def wants_gui(tool: Tool, args: Sequence[str]) -> bool:
    """Will this invocation try to open a window?"""
    if any(a in ("-h", "--help") for a in args):
        return False
    if tool.gui == "never":
        return False
    if "--gui" in args:
        return True
    if tool.gui == "default":
        return not any(a in tool.headless_flags for a in args)
    return not args  # "optional": a window only when given nothing to do


# --------------------------------------------------------------------------
# Interpreters
# --------------------------------------------------------------------------

PROBE_SOURCE = r"""
import json, sys
caps = {"version": sys.version.split()[0]}
try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg  # noqa: F401
    caps["tkagg"] = True
except Exception as exc:
    caps["tkagg"] = False
    caps["tkagg_error"] = "{}: {}".format(type(exc).__name__, exc)[:200]
for mod in ("sage", "snappy", "spherogram", "skimage"):
    try:
        __import__(mod)
        caps[mod] = True
    except Exception:
        caps[mod] = False
sys.stdout.write("DTLT_CAPS " + json.dumps(caps) + "\n")
"""


class Interp(NamedTuple):
    name: str            # "sage" or "python"
    cmd: Tuple[str, ...] # e.g. ("sage", "-python") or ("/usr/bin/python3",)
    caps: Dict[str, object]

    @property
    def display(self) -> str:
        return " ".join(self.cmd)

    def has(self, cap: str) -> bool:
        return bool(self.caps.get(cap))


def candidate_commands() -> List[Tuple[str, Tuple[str, ...]]]:
    """Interpreters worth probing, best-equipped first."""
    out: List[Tuple[str, Tuple[str, ...]]] = []
    if shutil.which("sage"):
        out.append(("sage", ("sage", "-python")))
    plain = sys.executable or shutil.which("python3") or "python3"
    # If the launcher itself is running under Sage, sys.executable is Sage's
    # Python -- so look up a separate plain python3 rather than duplicating it.
    if "sage" in str(plain).lower():
        plain = shutil.which("python3") or plain
    out.append(("python", (str(plain),)))
    return out


def _cache_key(cmd: Sequence[str]) -> str:
    exe = shutil.which(cmd[0]) or cmd[0]
    try:
        stamp = str(int(os.path.getmtime(exe)))
    except OSError:
        stamp = "0"
    return "{}|{}|{}".format(CACHE_VERSION, " ".join(cmd), stamp)


def _load_cache() -> Dict[str, Dict[str, object]]:
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cache(cache: Dict[str, Dict[str, object]]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, indent=2, sort_keys=True)
    except OSError:
        pass  # a probe cache is a convenience, never a hard requirement


def probe(cmd: Sequence[str], rescan: bool = False) -> Dict[str, object]:
    """Ask an interpreter what it can do; cached across runs."""
    key = _cache_key(cmd)
    cache = _load_cache()
    if not rescan and key in cache:
        return dict(cache[key])

    caps: Dict[str, object] = {"tkagg": False, "sage": False, "snappy": False}
    try:
        proc = subprocess.run(
            list(cmd) + ["-c", PROBE_SOURCE],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT,
        )
        for line in proc.stdout.splitlines():
            if line.startswith("DTLT_CAPS "):
                caps = json.loads(line[len("DTLT_CAPS "):])
                break
        else:
            caps["error"] = (proc.stderr.strip().splitlines() or ["no output"])[-1][:200]
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        caps["error"] = "{}: {}".format(type(exc).__name__, exc)[:200]

    caps["probed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    cache[key] = caps
    _save_cache(cache)
    return dict(caps)


def interpreters(rescan: bool = False) -> List[Interp]:
    return [Interp(name, cmd, probe(cmd, rescan)) for name, cmd in candidate_commands()]


def choose_interp(
    need_gui: bool,
    prefer: str = "auto",
    rescan: bool = False,
    needs: Sequence[str] = (),
) -> Tuple[Optional[Interp], List[str]]:
    """Pick an interpreter for this run; also return notes to show the user.

    ``needs`` lists extra capabilities the tool requires (probe keys such as
    ``"skimage"``).  Interpreters that have them are preferred over Sage, and a
    warning is emitted if none can satisfy them.
    """
    found = interpreters(rescan)
    notes: List[str] = []

    def satisfies(interp: Interp) -> bool:
        return all(interp.has(cap) for cap in needs)

    def missing(interp: Interp) -> List[str]:
        return [cap for cap in needs if not interp.has(cap)]

    if prefer in ("sage", "python"):
        for interp in found:
            if interp.name == prefer:
                if need_gui and not interp.has("tkagg"):
                    notes.append(
                        "warning: --interp {} was forced, but its matplotlib cannot "
                        "open a Tk window ({}). The tool will probably fail.".format(
                            prefer, interp.caps.get("tkagg_error", "TkAgg unavailable")
                        )
                    )
                if needs and not satisfies(interp):
                    notes.append("warning: --interp {} is missing {} required by this "
                                 "tool; it may fail.".format(prefer, ", ".join(missing(interp))))
                return interp, notes
        notes.append("error: --interp {} requested but not available".format(prefer))
        return None, notes

    if need_gui:
        # A window is only possible where matplotlib's Tk backend imports.
        usable = [i for i in found if i.has("tkagg")]
        if not usable:
            notes.append(
                "error: no interpreter can open a GUI (matplotlib TkAgg fails "
                "everywhere). Run a headless mode, or repair Tk/matplotlib."
            )
            return None, notes
        # Among GUI-capable interpreters, honour the tool's capability needs
        # first, then prefer one that also has Sage (so Jones stays available).
        pool = [i for i in usable if satisfies(i)] or usable
        best = next((i for i in pool if i.has("sage")), pool[0])
        if needs and not satisfies(best):
            notes.append("warning: {} is missing {} required by this tool; it may fail."
                         .format(best.display, ", ".join(missing(best))))
        elif not needs and not best.has("sage"):
            # Only relevant to the Sage-backed drawing/scoring tools.
            sage_only = next((i for i in found if i.has("sage") and not i.has("tkagg")), None)
            if sage_only is not None:
                notes.append(
                    "note: using {} for the GUI -- {} has Sage but its matplotlib "
                    "cannot open a Tk window ({}). Sage-backed Jones polynomials are "
                    "unavailable in GUI runs until that is fixed; SnapPy still works."
                    .format(best.display, sage_only.display,
                            sage_only.caps.get("tkagg_error", "TkAgg unavailable"))
                )
        return best, notes

    # Headless: honour capability needs first; otherwise Sage gives the fullest algebra.
    pool = [i for i in found if satisfies(i)] if needs else list(found)
    if not pool:
        pool = list(found)
    best = next((i for i in pool if i.has("sage")), pool[0] if pool else None)
    if best is None:
        return None, notes
    if needs and not satisfies(best):
        notes.append("warning: {} is missing {} required by this tool; it may fail."
                     .format(best.display, ", ".join(missing(best))))
    elif not needs and not best.has("sage"):
        notes.append("note: no Sage found; running {} without Sage algebra."
                     .format(best.display))
    return best, notes


# --------------------------------------------------------------------------
# Launching
# --------------------------------------------------------------------------

def build_command(
    tool: Tool,
    args: Sequence[str],
    prefer: str = "auto",
    rescan: bool = False,
) -> Tuple[Optional[List[str]], List[str]]:
    script = resolve_script(tool)
    if script is None:
        return None, ["error: no script for tool '{}' (expected '{}*.py' in {})"
                      .format(tool.key, tool.base, PROJECT_DIR)]
    interp, notes = choose_interp(wants_gui(tool, args), prefer, rescan,
                                  needs=tool.needs)
    if interp is None:
        return None, notes
    return list(interp.cmd) + [str(script)] + list(args), notes


def launch_exec(tool: Tool, args: Sequence[str], prefer: str = "auto",
                rescan: bool = False) -> int:
    """Replace this process with the tool (command-line path)."""
    cmd, notes = build_command(tool, args, prefer, rescan)
    for note in notes:
        sys.stderr.write(note + "\n")
    if cmd is None:
        return 1
    try:
        os.execvp(cmd[0], cmd)
    except OSError as exc:
        sys.stderr.write("error: could not launch {}: {}\n".format(cmd[0], exc))
        return 1
    return 0  # unreachable


def launch_detached(tool: Tool, args: Sequence[str], prefer: str = "auto"):
    """Start the tool as a child process (GUI-launcher path)."""
    cmd, notes = build_command(tool, args, prefer)
    if cmd is None:
        return None, notes
    proc = subprocess.Popen(cmd, cwd=str(PROJECT_DIR))
    return proc, notes


# --------------------------------------------------------------------------
# Graphical launcher
# --------------------------------------------------------------------------

def gui_launcher(prefer: str = "auto") -> int:
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as exc:
        sys.stderr.write("error: the graphical launcher needs Tkinter: {}\n".format(exc))
        sys.stderr.write("Falling back to the text menu.\n\n")
        return text_menu(prefer)

    root = tk.Tk()
    root.title("DT Link Toolkit")
    root.minsize(720, 480)

    outer = ttk.Frame(root, padding=12)
    outer.pack(fill="both", expand=True)

    ttk.Label(outer, text="DT Link Toolkit",
              font=("TkDefaultFont", 16, "bold")).pack(anchor="w")
    ttk.Label(outer, text="Choose a tool. Optional arguments are passed straight "
                          "to it (for example: --dt \"DT: [(4,6,2)]\").",
              wraplength=680, foreground="#555").pack(anchor="w", pady=(2, 10))

    args_row = ttk.Frame(outer)
    args_row.pack(fill="x", pady=(0, 10))
    ttk.Label(args_row, text="Arguments:").pack(side="left")
    args_var = tk.StringVar()
    args_entry = ttk.Entry(args_row, textvariable=args_var)
    args_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))

    table = ttk.Frame(outer)
    table.pack(fill="both", expand=True)
    table.columnconfigure(1, weight=1)

    log = tk.Text(outer, height=8, wrap="word")
    log.configure(state="disabled")

    def say(msg: str) -> None:
        log.configure(state="normal")
        log.insert("end", msg.rstrip() + "\n")
        log.see("end")
        log.configure(state="disabled")

    def run_tool(tool: Tool) -> None:
        try:
            extra = shlex.split(args_var.get().strip())
        except ValueError as exc:
            say("error: could not parse arguments: {}".format(exc))
            return
        cmd, notes = build_command(tool, extra, prefer)
        for note in notes:
            say(note)
        if cmd is None:
            return
        say("$ " + " ".join(shlex.quote(c) for c in cmd))
        try:
            subprocess.Popen(cmd, cwd=str(PROJECT_DIR))
            say("started {} (this launcher stays open)".format(tool.key))
        except OSError as exc:
            say("error: could not start {}: {}".format(tool.key, exc))

    for row, tool in enumerate(TOOLS):
        script = resolve_script(tool)
        shown = script.name if script is not None else "(not found)"
        btn = ttk.Button(table, text=tool.key, width=16,
                         command=lambda t=tool: run_tool(t))
        btn.grid(row=row, column=0, sticky="w", pady=3)
        if script is None:
            btn.state(["disabled"])
        cell = ttk.Frame(table)
        cell.grid(row=row, column=1, sticky="we", padx=(10, 0))
        ttk.Label(cell, text=tool.desc).pack(anchor="w")
        ttk.Label(cell, text=shown, foreground="#777").pack(anchor="w")

    ttk.Separator(outer).pack(fill="x", pady=10)
    log.pack(fill="both", expand=True)

    status = ttk.Frame(outer)
    status.pack(fill="x", pady=(8, 0))
    status_var = tk.StringVar(value="probing interpreters...")
    ttk.Label(status, textvariable=status_var, foreground="#555").pack(side="left")

    def refresh(rescan: bool = False) -> None:
        status_var.set("probing interpreters...")
        root.update_idletasks()
        found = interpreters(rescan)
        bits = []
        for interp in found:
            caps = [c for c in ("tkagg", "sage", "snappy", "skimage") if interp.has(c)]
            bits.append("{} [{}]".format(interp.display, ", ".join(caps) or "none"))
        status_var.set(" | ".join(bits) if bits else "no interpreters found")
        gui_i, notes = choose_interp(True, prefer)
        head_i, _ = choose_interp(False, prefer)
        say("GUI tools -> {}".format(gui_i.display if gui_i else "unavailable"))
        say("headless   -> {}".format(head_i.display if head_i else "unavailable"))
        for note in notes:
            say(note)

    ttk.Button(status, text="Re-scan",
               command=lambda: refresh(True)).pack(side="right")

    root.after(50, refresh)
    root.mainloop()
    return 0


# --------------------------------------------------------------------------
# Text interface
# --------------------------------------------------------------------------

def print_usage(stream=sys.stdout) -> None:
    width = max(len(t.key) for t in TOOLS)
    stream.write("DT Link Toolkit launcher\n\n")
    stream.write("Usage: DT_Link_Toolkit.py [<tool> [tool arguments...]]\n\n")
    stream.write("Tools:\n")
    for tool in TOOLS:
        stream.write("  {:<{w}}  {}\n".format(tool.key, tool.desc, w=width))
    stream.write("\nWith no tool, the graphical launcher opens.\n\n")
    stream.write("  --list             show the resolved script and interpreters\n")
    stream.write("  --menu             text menu instead of the graphical launcher\n")
    stream.write("  --interp {auto,sage,python}   force the interpreter\n")
    stream.write("  --rescan           re-probe interpreters, ignoring the cache\n")
    stream.write("  <tool> --help      forward --help to that tool\n")


def print_list(rescan: bool = False, stream=sys.stdout) -> None:
    width = max(len(t.key) for t in TOOLS)
    stream.write("Tools:\n")
    for tool in TOOLS:
        script = resolve_script(tool)
        stream.write("  {:<{w}}  {}\n".format(
            tool.key, script.name if script else "(not found)", w=width))
    stream.write("\nInterpreters:\n")
    for interp in interpreters(rescan):
        caps = [c for c in ("tkagg", "sage", "snappy", "skimage") if interp.has(c)]
        stream.write("  {:<24} [{}]\n".format(interp.display, ", ".join(caps) or "none"))
        if not interp.has("tkagg") and interp.caps.get("tkagg_error"):
            stream.write("  {:<24}  no GUI: {}\n".format("", interp.caps["tkagg_error"]))
    gui_i, notes = choose_interp(True)
    head_i, _ = choose_interp(False)
    stream.write("\nGUI tools -> {}\n".format(gui_i.display if gui_i else "unavailable"))
    stream.write("headless  -> {}\n".format(head_i.display if head_i else "unavailable"))
    for note in notes:
        stream.write(note + "\n")


def text_menu(prefer: str = "auto") -> int:
    print("DT Link Toolkit -- choose a tool:\n")
    for i, tool in enumerate(TOOLS, 1):
        script = resolve_script(tool)
        print("  {}. {:<15} {}".format(i, tool.key, tool.desc))
        print("     {}".format(script.name if script else "(not found)"))
    print("  q. quit\n")
    try:
        choice = input("Enter a number (1-{}) or q: ".format(len(TOOLS))).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 130
    if choice.lower() in ("q", "quit", "exit", ""):
        return 0
    if choice.isdigit() and 1 <= int(choice) <= len(TOOLS):
        return launch_exec(TOOLS[int(choice) - 1], [], prefer)
    sys.stderr.write("error: invalid choice '{}'\n".format(choice))
    return 2


# --------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    prefer = "auto"
    rescan = False
    # Launcher-level options may only appear before the tool name; everything
    # after the tool name belongs to the tool.
    while args and args[0].startswith("-"):
        opt = args[0]
        if opt in ("-h", "--help"):
            print_usage()
            return 0
        if opt in ("-l", "--list"):
            args.pop(0)
            print_list(rescan)
            return 0
        if opt == "--menu":
            args.pop(0)
            return text_menu(prefer)
        if opt == "--rescan":
            rescan = True
            args.pop(0)
            continue
        if opt == "--interp":
            if len(args) < 2 or args[1] not in ("auto", "sage", "python"):
                sys.stderr.write("error: --interp needs one of: auto, sage, python\n")
                return 2
            prefer = args[1]
            del args[0:2]
            continue
        if opt.startswith("--interp="):
            prefer = opt.split("=", 1)[1]
            if prefer not in ("auto", "sage", "python"):
                sys.stderr.write("error: --interp needs one of: auto, sage, python\n")
                return 2
            args.pop(0)
            continue
        sys.stderr.write("error: unknown option '{}'\n\n".format(opt))
        print_usage(sys.stderr)
        return 2

    if not args:
        if rescan:
            interpreters(True)
        return gui_launcher(prefer)

    tool = find_tool(args[0])
    if tool is None:
        sys.stderr.write("error: unknown tool '{}'\n\n".format(args[0]))
        print_usage(sys.stderr)
        return 2

    # Everything after the tool name is forwarded verbatim (including --help).
    return launch_exec(tool, args[1:], prefer, rescan)


if __name__ == "__main__":
    raise SystemExit(main())
