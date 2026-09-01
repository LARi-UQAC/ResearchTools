"""
talk_doctor - what this machine can and cannot build, before the build starts.

The skill spans four toolchains (Python, Node, Office, LaTeX) and most of them are
optional. Discovering a missing one at the render step means the deck is already
written to a target that cannot be produced. This runs first and says, per target,
whether it is available and what happens if it is not.

Nothing here installs anything: it reports, and the professor decides.

Usage
-----
    python talk_doctor.py                     # everything
    python talk_doctor.py --target pptx       # only what that target needs
    python talk_doctor.py --json

Exit codes: 0 the requested target is buildable, 1 a hard requirement is missing,
2 a usage error. Optional gaps are reported and never fail the run.
"""
from __future__ import annotations

import argparse
import importlib
import json
import shutil
import subprocess
import sys

TAG = "[DOCTOR]"

# name -> (kind, targets it serves, what happens without it)
PY_DEPS = {
    "pptx": ("required for pptx", ("pptx",),
             "no PowerPoint target at all; pip install python-pptx"),
    "pypdf": ("required for paper output", ("pptx", "beamer", "web"),
              "no A4/Letter reflow and no page-count gate; pip install pypdf"),
    "jinja2": ("required for beamer/web", ("beamer", "web"),
               "the Beamer and web renderers cannot run; pip install jinja2"),
    "defusedxml": ("recommended", ("pptx",),
                   "OOXML is parsed with the stdlib parser instead; pip install defusedxml"),
    "fitz": ("optional", ("pptx", "beamer", "web"),
             "no PDF paper input (LaTeX source still works); pip install pymupdf"),
}

CLI_DEPS = {
    "pdftoppm": ("required for visual QA", ("pptx", "beamer", "web"),
                 "no page images, so no visual inspection; install Poppler "
                 "(it ships with MiKTeX)"),
    "soffice": ("optional", ("pptx",),
                "PowerPoint COM is used instead on Windows"),
    "pdflatex": ("required for beamer", ("beamer",),
                 "the Beamer target cannot be compiled; install MiKTeX or TeX Live"),
    "node": ("optional", ("pptx",),
             "the no-gabarit pptxgenjs fallback cannot run; the gabarit renderer "
             "(talk_pptx.py) does not need it"),
    "drawio": ("optional", ("pptx", "beamer", "web"),
               "figures cannot be re-exported at scale 3; supply projector-grade "
               "assets yourself"),
}

TARGETS = ("pptx", "beamer", "web")


def _python_ok(module: str) -> bool:
    try:
        importlib.import_module(module)
        return True
    except Exception:      # a broken install raises something other than ImportError
        return False


def _powerpoint_com() -> bool:
    """True when PowerPoint answers COM, which is the Windows render backend."""
    if sys.platform != "win32":
        return False
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NonInteractive", "-NoProfile", "-Command",
             "$p = New-Object -ComObject PowerPoint.Application; $p.Quit(); 'ok'"],
            capture_output=True, text=True, timeout=90,
        )
        return "ok" in proc.stdout
    except Exception:
        return False


def diagnose(target: str | None = None, check_com: bool = True) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report every dependency, whether it is present, which targets it serves,
        and what degrades without it.

    Inputs:
        target (str): pptx, beamer or web; None checks everything
        check_com (bool): probe PowerPoint over COM (slow, Windows only)

    Outputs:
        report (dict): rows, the targets that are buildable, and the blockers
    --------------------------------------------------------------------------
    """
    rows = []
    for module, (kind, targets, degradation) in PY_DEPS.items():
        if target and target not in targets:
            continue
        rows.append({"name": f"python:{module}", "present": _python_ok(module),
                     "kind": kind, "targets": list(targets), "without": degradation})
    for command, (kind, targets, degradation) in CLI_DEPS.items():
        if target and target not in targets:
            continue
        if command == "drawio":
            # draw.io installs as `draw.io.exe` in a per-user folder on Windows, so
            # PATH alone under-reports it; reuse the exporter's own locator.
            try:
                import fig_export
                found = bool(fig_export.find_drawio(None))
            except Exception:
                found = bool(shutil.which(command))
        else:
            found = bool(shutil.which(command))
        rows.append({"name": command, "present": found,
                     "kind": kind, "targets": list(targets), "without": degradation})

    com = _powerpoint_com() if (check_com and (target in (None, "pptx"))) else None
    if com is not None:
        rows.append({
            "name": "PowerPoint (COM)", "present": com, "kind": "render backend",
            "targets": ["pptx"],
            "without": "install LibreOffice so `soffice` is on PATH, or render on a "
                       "machine with PowerPoint",
        })

    def present(name: str) -> bool:
        return any(r["present"] for r in rows if r["name"] == name)

    buildable = {}
    if target in (None, "pptx"):
        buildable["pptx"] = present("python:pptx")
    if target in (None, "beamer"):
        buildable["beamer"] = present("python:jinja2") and present("pdflatex")
    if target in (None, "web"):
        buildable["web"] = present("python:jinja2")

    # None, not False, when the COM probe was skipped: "not checked" and "absent"
    # are different answers and only one of them is a reason to stop.
    renderable = True if (present("soffice") or com) else (
        None if (com is None and sys.platform == "win32") else False
    )
    inspectable = present("pdftoppm")

    return {
        "rows": rows,
        "buildable": buildable,
        "can_render_pdf": renderable,
        "can_inspect_pages": inspectable,
        "blockers": [r["name"] for r in rows
                     if not r["present"] and r["kind"].startswith("required")],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Report what this machine can build.")
    ap.add_argument("--target", choices=TARGETS, help="check one target only")
    ap.add_argument("--no-com", action="store_true",
                    help="skip the PowerPoint COM probe (it opens and closes PowerPoint)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    report = diagnose(args.target, check_com=not args.no_com)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{TAG} {'dep':<20} {'state':<8} {'kind':<24} serves")
        for row in report["rows"]:
            print(f"{TAG} {row['name']:<20} {'ok' if row['present'] else 'MISSING':<8} "
                  f"{row['kind']:<24} {', '.join(row['targets'])}")
        print(f"{TAG}")
        for row in report["rows"]:
            if not row["present"]:
                print(f"{TAG} without {row['name']}: {row['without']}")
        print(f"{TAG}")
        for name, ok in report["buildable"].items():
            print(f"{TAG} target {name:<7} {'buildable' if ok else 'NOT buildable'}")
        pdf_state = {True: "available", False: "UNAVAILABLE",
                     None: "not probed (--no-com); PowerPoint COM is the Windows path"}
        print(f"{TAG} deck -> PDF   {pdf_state[report['can_render_pdf']]}")
        print(f"{TAG} page images   "
              f"{'available' if report['can_inspect_pages'] else 'UNAVAILABLE (no visual QA)'}")

    if args.target:
        return 0 if report["buildable"].get(args.target) else 1
    return 1 if report["blockers"] else 0


if __name__ == "__main__":
    sys.exit(main())
