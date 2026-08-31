"""
tex_build - subcommands `accept` and `build`: the write side of the latex-hygiene
skill that turns a track-changed .tex source into a buildable PDF.

Stage: latex-hygiene pipeline, post-audit build step. Dispatch lives in
tex_check.py (tex_check.py accept / tex_check.py build), matching every other
subcommand module in this skill; this file carries no argparse of its own.

`accept` generates the accepted-markup source FROM the tracked source instead
of maintaining two hand-edited files. Two files diverge: the 2026-08-26
Penelope_Allan session proved it twice, once when the accepted target was
rebuilt before two new citations had been propagated into it. Regenerating on
demand from the single tracked source removes the divergence entirely.

`build` runs the standard four-command LaTeX sequence (pdflatex, bibtex,
pdflatex, pdflatex) and reports four counters read back from the .log/.bbl,
so a regression is visible in a single glance instead of a full log re-read.
Two guards, both measured against a real 653-line IEEE manuscript:

  - GUARD 7a: bibtex runs with the output directory as its working directory
    and will not find references.bib one level up. It reports that as a
    WARNING, not an error, and the PDF still builds with every citation
    typeset as a question mark. BIBINPUTS is therefore mandatory on the
    bibtex call (see build_commands below - marked load-bearing there).
  - GUARD 7b: a stale .bib copied into the output directory shadows the real
    one with no warning at all; it cost a full debugging pass when 25 added
    url fields silently failed to appear. `build` refuses to run rather than
    build against a shadow copy.
"""

import logging
import os
import re
import shutil
import subprocess
from typing import Dict, List, Optional

from tex_common import read_text, resolve_accepted

logger = logging.getLogger(__name__)

REQUIRED_TOOLS = ("pdflatex", "bibtex")

_CHANGES_PKG = re.compile(r"\\usepackage(\[[^\]]*\])?\{changes\}")
_TODONOTES_PKG = re.compile(r"\\usepackage(\[[^\]]*\])?\{todonotes\}")

# The count of pages LaTeX prints at the very end of a run, e.g. "Output
# written on out/foo.pdf (17 pages, 512034 bytes)." The last match in the
# log is the final pass's count (mirrors build.sh's `grep ... | tail -1`).
_PAGES_RE = re.compile(r"\((\d+)\s+pages")


def write_accepted(target: str, out: Optional[str] = None, resolve: bool = False) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Generate the accepted-markup source from a track-changed source.
        Default mode changes only the two package-option lines so `changes`
        renders every \\added/\\deleted/\\replaced as accepted text and
        `todonotes` stops printing margin notes; nothing else in the file is
        touched. --resolve instead textually resolves the changes macros via
        tex_common.resolve_accepted, for the rare case where a downstream
        tool does not honor the `changes` package's [final] option.

    Inputs:
        target (str): path to the track-changed .tex source.
        out (Optional[str]): output path; default <target>_accepted.tex.
        resolve (bool): resolve macros textually instead of switching
            package options.

    Outputs:
        result (Dict): {"target", "out", "resolve", "note", "bytes_written"}.
    --------------------------------------------------------------------------
    """
    text = read_text(target)
    if resolve:
        new_text = resolve_accepted(text)
        note = "changes macros resolved textually (tex_common.resolve_accepted)"
    else:
        n_changes = len(_CHANGES_PKG.findall(text))
        n_todo = len(_TODONOTES_PKG.findall(text))
        new_text = _CHANGES_PKG.sub(lambda m: "\\usepackage[final]{changes}", text, count=1)
        new_text = _TODONOTES_PKG.sub(lambda m: "\\usepackage[disable]{todonotes}", new_text, count=1)
        note = "package options switched (changes found=%s, todonotes found=%s)" % (
            bool(n_changes), bool(n_todo),
        )

    out_path = out or (os.path.splitext(target)[0] + "_accepted.tex")
    with open(out_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(new_text)

    logger.info("[HYGIENE] accept: %s -> %s (%s)", target, out_path, note)
    return {
        "target": target,
        "out": out_path,
        "resolve": resolve,
        "note": note,
        "bytes_written": len(new_text.encode("utf-8")),
    }


def _stray_bib_files(outdir: str) -> List[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List every .bib file already sitting inside the output directory
        (GUARD 7b). A copy there shadows the real references.bib with no
        warning, so `build` must refuse rather than silently build against it.

    Inputs:
        outdir (str): the LaTeX output directory.

    Outputs:
        stray (List[str]): sorted paths of .bib files found; empty if none or
            if outdir does not exist yet.
    --------------------------------------------------------------------------
    """
    if not os.path.isdir(outdir):
        return []
    return sorted(
        os.path.join(outdir, name) for name in os.listdir(outdir) if name.lower().endswith(".bib")
    )


def _require_tool(name: str) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Refuse to proceed, with an actionable message naming the tool, when a
        required LaTeX executable is not on PATH. `build` must never silently
        degrade when pdflatex or bibtex is missing.

    Inputs:
        name (str): executable name to look up (e.g. "pdflatex").

    Outputs:
        None. Raises RuntimeError when the tool is absent.
    --------------------------------------------------------------------------
    """
    if shutil.which(name) is None:
        raise RuntimeError(
            "[HYGIENE] %s not found on PATH; install a LaTeX distribution "
            "(MiKTeX or TeX Live) that provides it, or add it to PATH." % name
        )


def build_commands(target: str, outdir: str) -> List[Dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the exact four-command sequence (pdflatex, bibtex, pdflatex,
        pdflatex) as a list of {"cmd", "cwd", "env"} steps, shared by the real
        run and --dry-run so the two can never drift apart.

    Inputs:
        target (str): path to the .tex file to build.
        outdir (str): LaTeX output directory (pdflatex -output-directory).

    Outputs:
        steps (List[Dict]): four entries, each {"cmd": List[str],
            "cwd": Optional[str], "env": Optional[Dict[str, str]]}.
    --------------------------------------------------------------------------
    """
    name = os.path.splitext(os.path.basename(target))[0]
    pdflatex_cmd = ["pdflatex", "-interaction=nonstopmode", "-output-directory=%s" % outdir, target]
    bibtex_cmd = ["bibtex", name]
    # MANDATORY: bibtex is run with outdir as its working directory, so a bare
    # "references.bib" resolves relative to outdir, not to the project root
    # one level up (GUARD 7a). Without this, bibtex reports a WARNING, the
    # build still exits "successfully", and every citation typesets as "?".
    # Do not remove this even though the surrounding pdflatex calls need no
    # environment override.
    bibtex_env = {"BIBINPUTS": ".."}
    return [
        {"cmd": list(pdflatex_cmd), "cwd": None, "env": None},
        {"cmd": bibtex_cmd, "cwd": outdir, "env": bibtex_env},
        {"cmd": list(pdflatex_cmd), "cwd": None, "env": None},
        {"cmd": list(pdflatex_cmd), "cwd": None, "env": None},
    ]


def parse_counters(name: str, outdir: str) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the four regression counters back from the build artifacts, the
        same four build.sh prints: LaTeX errors, "undefined" warnings, DOI
        links resolved into the bibliography, and the final page count.

    Inputs:
        name (str): target basename without extension (the .log/.bbl stem).
        outdir (str): LaTeX output directory.

    Outputs:
        counters (Dict): {"errors": int, "undefined": int, "doi_links": int,
            "pages": Optional[int]}. Missing artifacts read as empty text
            rather than raising, so a build that failed before producing a
            .bbl still reports errors/undefined from whatever .log exists.
    --------------------------------------------------------------------------
    """
    log_path = os.path.join(outdir, name + ".log")
    bbl_path = os.path.join(outdir, name + ".bbl")
    log_text = read_text(log_path) if os.path.isfile(log_path) else ""
    bbl_text = read_text(bbl_path) if os.path.isfile(bbl_path) else ""

    errors = len(re.findall(r"(?m)^!", log_text))
    undefined = len(re.findall(r"undefined", log_text, re.IGNORECASE))
    doi_links = bbl_text.count("doi.org")
    pages_hits = _PAGES_RE.findall(log_text)
    pages = int(pages_hits[-1]) if pages_hits else None

    return {"errors": errors, "undefined": undefined, "doi_links": doi_links, "pages": pages}


def run_build(target: str, outdir: str = "out", dry_run: bool = False) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run (or, with dry_run, plan) the pdflatex/bibtex/pdflatex/pdflatex
        sequence for one target and report the four counters. Refuses before
        touching a single subprocess when a stray .bib sits in outdir (GUARD
        7b) or when pdflatex/bibtex is missing from PATH; both guards apply
        whether or not this is a dry run, since a plan that would fail for
        real is exactly what --dry-run exists to surface.

    Inputs:
        target (str): path to the .tex file to build.
        outdir (str): LaTeX output directory, created if absent.
        dry_run (bool): print the command sequence and change nothing.

    Outputs:
        result (Dict): dry run -> {"target", "outdir", "dry_run": True,
            "commands"}; real run -> {"target", "outdir", "dry_run": False,
            "errors", "undefined", "doi_links", "pages"}.
    --------------------------------------------------------------------------
    """
    stray = _stray_bib_files(outdir)
    if stray:
        raise RuntimeError(
            "[HYGIENE] refusing to build: stray .bib file(s) inside %s: %s. "
            "A copy in the output directory shadows the real references.bib with no "
            "warning; remove it and let BIBINPUTS resolve the real one instead." % (
                outdir, ", ".join(stray),
            )
        )
    for tool in REQUIRED_TOOLS:
        _require_tool(tool)

    os.makedirs(outdir, exist_ok=True)
    steps = build_commands(target, outdir)
    name = os.path.splitext(os.path.basename(target))[0]

    if dry_run:
        logger.info("[HYGIENE] build --dry-run: %s (%d commands planned)", target, len(steps))
        return {"target": target, "outdir": outdir, "dry_run": True, "commands": steps}

    for step in steps:
        env = os.environ.copy()
        if step["env"]:
            env.update(step["env"])
        subprocess.run(step["cmd"], cwd=step["cwd"], env=env, capture_output=True, check=False)

    counters = parse_counters(name, outdir)
    logger.info(
        "[HYGIENE] %s: errors=%s undefined=%s doi_links=%s pages=%s",
        name, counters["errors"], counters["undefined"], counters["doi_links"], counters["pages"],
    )
    result = {"target": target, "outdir": outdir, "dry_run": False}
    result.update(counters)
    return result


def run_both(target: str, outdir: str = "out", resolve: bool = False, dry_run: bool = False) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        The loop an author runs after every editing pass: regenerate the
        accepted source from the tracked one, then build both targets, so the
        two PDFs can never silently diverge from each other or from the
        source.

    Inputs:
        target (str): path to the tracked .tex source.
        outdir (str): shared LaTeX output directory for both builds.
        resolve (bool): forwarded to write_accepted.
        dry_run (bool): forwarded to both run_build calls.

    Outputs:
        result (Dict): {"accept": write_accepted result, "tracked": run_build
            result for target, "accepted": run_build result for the
            generated accepted source}.
    --------------------------------------------------------------------------
    """
    accept_result = write_accepted(target, None, resolve)
    tracked = run_build(target, outdir, dry_run)
    accepted = run_build(accept_result["out"], outdir, dry_run)
    return {"accept": accept_result, "tracked": tracked, "accepted": accepted}
