"""
tex_check - CLI entry point for the latex-hygiene skill.

Stage: latex-hygiene pipeline, dispatch and output. Thirteen subcommands
(chars, aiscan, wc, abstract, braces, par, citecov, refcov, all, accept,
build, patch, scan), each delegating to a sibling module (tex_chars.py ...
tex_refcov.py, tex_build.py, tex_patch.py, tex_scan.py) so this file stays
under the repo's per-file token ceiling (.claude/rules/code-style.md); it
carries no scanning, build, or patch logic itself. Plain-text rendering and
the --strict defect predicate live in tex_report.py (split out 2026-08-27
for the same ceiling reason) and are imported back here.

Contract: paths are CLI arguments (globs accepted), never a hardcoded file
list or a chdir; every subcommand accepts --json; the process exits 0 even
when a defect is found, unless --strict is passed, so the script stays
usable mid-audit without breaking a calling chain.
"""

import argparse
import json
import logging
import sys
from typing import Dict, List, Optional

from tex_abstract import scan_abstract
from tex_aiscan import scan_aiscan
from tex_braces import scan_braces
from tex_chars import scan_chars
from tex_citecov import scan_citecov
from tex_common import expand_globs, read_text
from tex_par import scan_par
from tex_patch import run_patch
from tex_refcov import scan_refcov
from tex_report import has_defect, print_text
from tex_scan import scan_files
from tex_build import run_both, run_build, write_accepted
from tex_wc import scan_wc, scan_wc_accepted, scan_wc_accepted_delta

logger = logging.getLogger(__name__)


def run_all(files: List[str], main_file: Optional[str], bib_file: Optional[str]) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Aggregate of chars, aiscan, wc, abstract, braces, par, citecov, and
        refcov over the same file set. abstract and citecov need a single
        main file and a .bib respectively, which `all` does not require
        positionally: the main file is auto-detected as the first input file
        containing \\documentclass (overridable with --main), and citecov is
        skipped with a note when --bib is not given. refcov needs neither and
        always runs.

    Inputs:
        files (List[str]): expanded .tex files.
        main_file (Optional[str]): explicit main file for `abstract`.
        bib_file (Optional[str]): .bib file for `citecov`.

    Outputs:
        result (Dict): {"chars", "aiscan", "wc", "braces", "par", "refcov",
            "abstract", "citecov"}, each the corresponding subcommand's own
            result dict, or {"skipped": <reason>} for abstract/citecov when
            unresolved.
    --------------------------------------------------------------------------
    """
    result = {
        "chars": scan_chars(files),
        "aiscan": scan_aiscan(files),
        "wc": scan_wc(files),
        "braces": scan_braces(files),
        "par": scan_par(files),
        "refcov": scan_refcov(files),
    }

    detected_main = main_file
    if detected_main is None:
        for path in files:
            if r"\documentclass" in read_text(path):
                detected_main = path
                break
    if detected_main:
        result["abstract"] = scan_abstract(detected_main)
    else:
        result["abstract"] = {"skipped": "no main file given or detected; pass --main"}

    if bib_file:
        result["citecov"] = scan_citecov(files, bib_file)
    else:
        result["citecov"] = {"skipped": "no --bib given"}

    return result


def build_parser() -> argparse.ArgumentParser:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the tex_check.py argument parser: nine subcommands sharing
        --json and --strict.

    Inputs:
        None.

    Outputs:
        parser (argparse.ArgumentParser): configured parser.
    --------------------------------------------------------------------------
    """
    # --json/--strict must work whether given before or after the subcommand
    # name, so they are declared once on a parents=[] parser shared by the
    # top-level parser and every subparser (argparse only applies a parent's
    # default when the destination is not already set in the namespace, so
    # the top-level value survives into the subparser round untouched).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="Emit JSON instead of plain text.")
    common.add_argument("--strict", action="store_true", help="Exit non-zero when a defect is found.")

    parser = argparse.ArgumentParser(
        prog="tex_check.py",
        description="LaTeX hygiene checks for the latex-hygiene skill.",
        parents=[common],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_chars = sub.add_parser("chars", parents=[common], help="Forbidden invisible/typographic character scan.")
    p_chars.add_argument("files", nargs="+", help=".tex files or globs.")

    p_aiscan = sub.add_parser("aiscan", parents=[common], help="AI-usage style risk score.")
    p_aiscan.add_argument("files", nargs="+", help=".tex files or globs.")

    p_wc = sub.add_parser("wc", parents=[common], help="Prose word count and page estimate.")
    p_wc.add_argument("files", nargs="+", help=".tex files or globs.")
    p_wc.add_argument("--accepted", action="store_true",
                       help="Count the changes-package accepted text instead of raw source.")
    p_wc.add_argument("--before", metavar="DIR",
                       help="With --accepted: compare against a before/ directory (before/after/delta table).")

    p_abstract = sub.add_parser("abstract", parents=[common], help="Abstract word count and keyword count.")
    p_abstract.add_argument("main_file", help="Path to the manuscript's main .tex file.")

    p_braces = sub.add_parser("braces", parents=[common], help="Brace-balance check.")
    p_braces.add_argument("files", nargs="+", help=".tex files or globs.")

    p_par = sub.add_parser("par", parents=[common], help="Blank line inside a changes-package macro argument.")
    p_par.add_argument("files", nargs="+", help=".tex files or globs.")

    p_citecov = sub.add_parser("citecov", parents=[common], help="Citation coverage against a .bib file.")
    p_citecov.add_argument("--tex", nargs="+", required=True, dest="tex_files", help=".tex files or globs.")
    p_citecov.add_argument("--bib", required=True, help=".bib file.")

    p_refcov = sub.add_parser("refcov", parents=[common], help="Label / cross-reference coverage.")
    p_refcov.add_argument("files", nargs="+", help=".tex files or globs.")

    p_all = sub.add_parser(
        "all", parents=[common],
        help="Aggregate of chars/aiscan/wc/abstract/braces/par/citecov/refcov.",
    )
    p_all.add_argument("files", nargs="+", help=".tex files or globs.")
    p_all.add_argument("--main", dest="main_file", default=None,
                        help="Main .tex file for the abstract check (auto-detected via \\documentclass if omitted).")
    p_all.add_argument("--bib", dest="bib_file", default=None,
                        help="Bib file for the citecov check (skipped if omitted).")

    p_accept = sub.add_parser("accept", parents=[common], help="Generate an accepted source.")
    p_accept.add_argument("--target", required=True, help="Track-changed .tex source.")
    p_accept.add_argument("--out", default=None, help="Output path (default <target>_accepted.tex).")
    p_accept.add_argument("--resolve", action="store_true", help="Resolve macros textually, not by package option.")

    p_build = sub.add_parser("build", parents=[common], help="Run the pdflatex/bibtex build sequence.")
    p_build.add_argument("--target", required=True, help="Main .tex file to build.")
    p_build.add_argument("--outdir", default="out", help="LaTeX output directory (default out).")
    p_build.add_argument("--both", action="store_true", help="Build the tracked target and its accepted copy.")
    p_build.add_argument("--resolve", action="store_true", help="With --both, forwarded to accept.")
    p_build.add_argument("--dry-run", dest="dry_run", action="store_true", help="Print the plan; run nothing.")

    p_patch = sub.add_parser("patch", parents=[common], help="Apply a track-changed audit plan to a .tex file.")
    p_patch.add_argument("--plan", required=True, help="Markdown audit-plan file (see tex_patch.py docstring).")
    p_patch.add_argument("--target", required=True, help="Target .tex file to patch.")
    p_patch.add_argument("--author", default=None, help="Rewrite id=... to this author id in every applied macro.")
    p_patch.add_argument("--dry-run", dest="dry_run", action="store_true",
                          help="Report match counts only; write nothing. Default in CI.")
    p_patch.add_argument("--init", action="store_true", help="Insert the changes-package preamble lines if absent.")
    p_patch.add_argument("--author-name", default="Author", help="Display name for --init (default: Author).")
    p_patch.add_argument("--author-color", default="blue", help="definechangesauthor color for --init (default: blue).")
    p_patch.add_argument("--added-color", default="blue", help="Added-markup color for --init (default: blue).")
    p_patch.add_argument("--deleted-color", default="red", help="Deleted-markup color for --init (default: red).")

    p_scan = sub.add_parser("scan", parents=[common], help="Post-write LaTeX track-changes hygiene guard.")
    p_scan.add_argument("files", nargs="+", help=".tex files or globs.")
    p_scan.add_argument("--bib", dest="bib_file", default=None, help=".bib file for the dangling-cite guard.")
    p_scan.add_argument("--fail-on-markers", dest="fail_on_markers", action="store_true",
                         help="Count \\hl{}/\\todo{}/TODO(author) markers as a --strict defect.")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse arguments, dispatch to the matching subcommand module, print
        the result, and compute the exit code.

    Inputs:
        argv (Optional[List[str]]): argument vector (defaults to sys.argv[1:]).

    Outputs:
        exit_code (int): 0 unless --strict is passed and a defect was found,
            or the command itself is unrecognized (2, from argparse).
    --------------------------------------------------------------------------
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_parser().parse_args(argv)
    command = args.command

    if command == "chars":
        result = scan_chars(expand_globs(args.files))
    elif command == "aiscan":
        result = scan_aiscan(expand_globs(args.files))
    elif command == "wc":
        files = expand_globs(args.files)
        if args.accepted and args.before:
            result = scan_wc_accepted_delta(args.before, files)
        elif args.accepted:
            result = scan_wc_accepted(files)
        else:
            result = scan_wc(files)
    elif command == "abstract":
        result = scan_abstract(args.main_file)
    elif command == "braces":
        result = scan_braces(expand_globs(args.files))
    elif command == "par":
        result = scan_par(expand_globs(args.files))
    elif command == "citecov":
        result = scan_citecov(expand_globs(args.tex_files), args.bib)
    elif command == "refcov":
        result = scan_refcov(expand_globs(args.files))
    elif command == "accept":
        result = write_accepted(args.target, args.out, args.resolve)
    elif command == "build":
        if args.both:
            result = run_both(args.target, args.outdir, args.resolve, args.dry_run)
        else:
            result = run_build(args.target, args.outdir, args.dry_run)
    elif command == "patch":
        result = run_patch(args)
    elif command == "scan":
        result = scan_files(expand_globs(args.files), args.bib_file, args.fail_on_markers)
    else:
        result = run_all(expand_globs(args.files), args.main_file, args.bib_file)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print_text(command, result)

    # patch is the one deliberate exception to the "exit 0 unless --strict"
    # convention: a plan edit that silently matched 0 or 2+ times, or a
    # malformed block, must fail loudly regardless of --strict.
    if command == "patch" and result.get("fails"):
        return 1
    if args.strict and has_defect(command, result):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
