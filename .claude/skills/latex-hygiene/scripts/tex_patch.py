"""
tex_patch - subcommand `patch`: apply a track-changed audit plan to a .tex file.

Stage: latex-hygiene pipeline, write side. Port of the reusable harness behind
the seven throwaway patch*.py scripts from the 2026-08-26 Assistive-feeding-
robot session (docs/superpowers/todo/2026-08-26-latex-trackchanges-patcher.md):
patch1.py::rep()'s count-then-substitute contract, and patch2.py's preamble
emitter for `--init`. None of the 106 manuscript-specific literal edits are
ported; only the harness.

PLAN FILE GRAMMAR (arbitrated in the main session; implement exactly this):

- The plan is a Markdown file. Each edit is ONE fenced code block, language
  tag `latex`, containing EXACTLY ONE top-level `changes` macro:
  `\\added[id=X]{...}`, `\\deleted[id=X]{...}`, or `\\replaced[id=X]{new}{old}`.
  A block with zero, or two or more, top-level macros is a MALFORMED PLAN:
  reported with its heading and skipped, never guessed. "Top-level" excludes
  a macro nested inside another macro's own argument (for example a
  `\\replaced` written inside an `\\added`'s content).
- The match anchor is: `\\replaced` matches on its SECOND argument (`old`);
  `\\deleted` matches on its single argument. Exact string match, no
  normalisation, no regex.
- `\\added` has no anchor of its own, so its block MUST carry an insertion
  point as a comment line immediately above the macro: `% after: <literal>`
  or `% before: <literal>`. The literal text is matched exactly and the
  macro is inserted immediately after or before it. Neither comment present
  is a MALFORMED block.
- The plan section reported on any failure is the nearest preceding Markdown
  heading (any level) above the fenced block.

Behaviour: every edit counts its anchor's occurrences in the working buffer
before substituting (patch1.py::rep()'s contract). Exactly 1 is required; on
0 or on 2+, the failure is COLLECTED and the remaining edits still run - one
bad pattern never abandons the rest. The target file is written only when
--dry-run is absent AND no edit failed: a patch that silently matched
nothing, or partially matched, is the dominant failure mode and this
subcommand's whole point is to fail loudly on it instead of writing a
half-applied file - a deliberate exception to the repo-wide "exit 0 unless
--strict" convention of the read-side subcommands in this skill. `scan`
(tex_scan.py) runs automatically once the file is written, and its findings
ride along in the report.
"""

import logging
import re
from typing import Dict, List, Optional, Tuple

from tex_common import CHANGES_MACRO, build_line_starts, line_at, macro_arg_spans, read_balanced_arg, read_text
from tex_scan import print_scan_text, scan_files

logger = logging.getLogger(__name__)

_HEADING = re.compile(r"(?m)^#{1,6}[ \t]+(.+?)[ \t]*$")
_FENCE = re.compile(r"(?ms)^```latex[ \t]*\n(.*?)\n```[ \t]*$")
_ADDED_MARK = re.compile(r"^\s*%\s*(after|before):\s*(.*?)\s*$")


def _nearest_heading(headings: List[Tuple[int, str]], line_no: int) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find the nearest Markdown heading strictly above a given line, for
        the "plan section reported on any failure" requirement.

    Inputs:
        headings (List[Tuple[int, str]]): (line_no, text) pairs in document
            order, as produced by scanning the whole plan once.
        line_no (int): 1-based line of the fenced block's opening line.

    Outputs:
        heading (str): the closest preceding heading text, or a placeholder
            when the block has no heading above it.
    --------------------------------------------------------------------------
    """
    best = "(no heading)"
    for hline, htext in headings:
        if hline >= line_no:
            break
        best = htext
    return best


def _top_level_spans(spans: List[Tuple[int, int, str, str]]) -> List[Tuple[int, int, str, str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Keep only the spans not fully contained inside another span, so a
        `\\replaced` written inside an `\\added`'s argument does not count
        as a second top-level macro in the same block.

    Inputs:
        spans (List[Tuple[int, int, str, str]]): output of
            tex_common.macro_arg_spans over one fenced block.

    Outputs:
        top (List[Tuple[int, int, str, str]]): the spans with no other span
            strictly enclosing them.
    --------------------------------------------------------------------------
    """
    top = []
    for i, span in enumerate(spans):
        nested = any(
            j != i and other[0] <= span[0] and span[1] <= other[1]
            for j, other in enumerate(spans)
        )
        if not nested:
            top.append(span)
    return top


def _rewrite_author(macro_text: str, author: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Rewrite the `id=...` bracket option of one rendered macro to a new
        author id, so a plan written with `id=AU` lands as `id=MO` without a
        manual pass.

    Inputs:
        macro_text (str): the macro's literal source, e.g. `\\deleted[id=AU]{x}`.
        author (str): the replacement author id.

    Outputs:
        text (str): macro_text with its `[id=...]` option rewritten.
    --------------------------------------------------------------------------
    """
    return re.sub(r"\[id=[^\]]*\]", "[id=%s]" % author, macro_text, count=1)


def _extract_macro(block: str, span: Tuple[int, int, str, str], author: Optional[str]) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn one top-level macro span into an edit record: the anchor text
        to search for in the target file (or, for `\\added`, the insertion
        point read from the `% after:`/`% before:` comment line immediately
        above it), and the macro's own rendered text (author id rewritten if
        requested).

    Inputs:
        block (str): the fenced block's content.
        span (Tuple[int, int, str, str]): (start, end, kind, full_text) for
            the block's single top-level macro.
        author (Optional[str]): replacement author id, or None to leave the
            macro's id as written in the plan.

    Outputs:
        edit (Dict): well-formed -> {"kind", "anchor", "insert_marker",
            "insert_anchor", "macro_text", "malformed": False}; malformed
            (added with no anchor comment) -> {"malformed": True, "reason"}.
    --------------------------------------------------------------------------
    """
    start, _end, kind, full_text = span
    if author:
        full_text = _rewrite_author(full_text, author)

    if kind != "added":
        m = CHANGES_MACRO.match(block, start)
        a1, j = read_balanced_arg(block, m.end())
        if kind == "replaced":
            k = block.find("{", j)
            anchor, _j2 = read_balanced_arg(block, k + 1)
        else:  # deleted
            anchor = a1
        return {"kind": kind, "anchor": anchor, "insert_marker": None, "insert_anchor": None,
                "macro_text": full_text, "malformed": False}

    starts = build_line_starts(block)
    macro_line = line_at(start, starts)
    lines = block.split("\n")
    marker_line = lines[macro_line - 2] if macro_line >= 2 else ""
    m2 = _ADDED_MARK.match(marker_line)
    if not m2:
        return {"malformed": True, "reason": "\\added with no % after:/% before: comment above it"}
    return {"kind": kind, "anchor": None, "insert_marker": m2.group(1), "insert_anchor": m2.group(2),
            "macro_text": full_text, "malformed": False}


def parse_plan(plan_text: str, author: Optional[str]) -> List[Dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse every fenced `latex` code block of a Markdown audit plan into
        an ordered list of edit records (document order, matching the order
        edits must be applied in), each tagged with its governing heading.

    Inputs:
        plan_text (str): full Markdown plan content.
        author (Optional[str]): replacement author id, or None.

    Outputs:
        edits (List[Dict]): one dict per fenced block, well-formed or
            malformed (see _extract_macro), each carrying "heading".
    --------------------------------------------------------------------------
    """
    starts = build_line_starts(plan_text)
    headings = [(line_at(m.start(), starts), m.group(1)) for m in _HEADING.finditer(plan_text)]

    edits: List[Dict] = []
    for m in _FENCE.finditer(plan_text):
        block = m.group(1)
        heading = _nearest_heading(headings, line_at(m.start(), starts))
        spans = _top_level_spans(macro_arg_spans(block, CHANGES_MACRO))
        if len(spans) != 1:
            reason = "no changes macro in block" if not spans else "%d top-level changes macros in block" % len(spans)
            edits.append({"heading": heading, "malformed": True, "reason": reason})
            continue
        edit = _extract_macro(block, spans[0], author)
        edit["heading"] = heading
        edits.append(edit)
    return edits


def apply_edits(text: str, edits: List[Dict]) -> Tuple[str, List[Dict], int]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Apply each edit in document order against a working buffer, counting
        the anchor's occurrences before substituting (patch1.py::rep()'s
        contract): exactly 1 required, 0 or 2+ collected as a failure and
        the loop continues, never raising and never abandoning the rest.

    Inputs:
        text (str): the target file's current content.
        edits (List[Dict]): output of parse_plan.

    Outputs:
        buf (str), fails (List[Dict]), applied (int): the buffer after every
            successful edit, one {"heading", "count", "pattern"} dict per
            failure (count is None for a malformed block), and the count of
            edits actually applied.
    --------------------------------------------------------------------------
    """
    buf = text
    fails: List[Dict] = []
    applied = 0
    for edit in edits:
        if edit["malformed"]:
            fails.append({"heading": edit["heading"], "count": None, "pattern": edit["reason"][:80]})
            continue
        anchor = edit["insert_anchor"] if edit["kind"] == "added" else edit["anchor"]
        n = buf.count(anchor)
        if n != 1:
            fails.append({"heading": edit["heading"], "count": n, "pattern": anchor[:80]})
            continue
        if edit["kind"] == "added":
            idx = buf.index(anchor)
            pos = idx + len(anchor) if edit["insert_marker"] == "after" else idx
            buf = buf[:pos] + edit["macro_text"] + buf[pos:]
        else:
            buf = buf.replace(anchor, edit["macro_text"], 1)
        applied += 1
    return buf, fails, applied


def apply_init(text: str, author: str, author_name: str, author_color: str,
                added_color: str, deleted_color: str) -> Tuple[str, bool]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Insert the four `changes`-package preamble lines if `changes` is not
        already loaded (guard 3): the package, the author declaration, and
        colour-only added/deleted markup. The package default deleted markup
        is `ulem`'s `\\sout`, which breaks on `\\cite`, on math mode and on
        `\\newline`; colour-only markup never invokes `\\sout`.

    Inputs:
        text (str): the target file's current content.
        author (str), author_name (str), author_color (str): the
            `\\definechangesauthor` id, display name, and colour. Flags, not
            hardcoded to any one author.
        added_color (str), deleted_color (str): the two markup colours.

    Outputs:
        text (str), applied (bool): the text with the preamble inserted (or
            unchanged if `changes` was already loaded), and whether the
            insertion happened.
    --------------------------------------------------------------------------
    """
    if "\\usepackage{changes}" in text:
        return text, False
    preamble = "\n".join([
        "\\usepackage{changes}",
        "\\definechangesauthor[name={%s}, color=%s]{%s}" % (author_name, author_color, author),
        "\\setaddedmarkup{\\color{%s}#1}" % added_color,
        "\\setdeletedmarkup{\\color{%s}[#1]}" % deleted_color,
    ])
    marker = "\\begin{document}"
    idx = text.find(marker)
    if idx == -1:
        return text + "\n" + preamble + "\n", True
    return text[:idx] + preamble + "\n\n" + text[idx:], True


def write_text(path: str, text: str) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Write the patched buffer back to disk without newline translation,
        since tex_common.read_text already normalised line endings to `\\n`
        on the way in.

    Inputs:
        path (str): target file path.
        text (str): patched content.

    Outputs:
        None. Writes the file.
    --------------------------------------------------------------------------
    """
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def run_patch(args) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Drive one `patch` invocation end to end: optional `--init`, plan
        parsing, sequential edit application, and a gated write (see module
        docstring for the write-gating rule) with an automatic `scan` pass.

    Inputs:
        args: argparse.Namespace with plan, target, author, dry_run, init,
            author_name, author_color, added_color, deleted_color.

    Outputs:
        result (Dict): {"target", "plan", "dry_run", "edits_total",
            "edits_applied", "fails", "written", "init_applied", "scan"}.
    --------------------------------------------------------------------------
    """
    plan_text = read_text(args.plan)
    buf = read_text(args.target)

    init_applied = None
    if args.init:
        buf, init_applied = apply_init(
            buf, args.author or "AU", args.author_name, args.author_color, args.added_color, args.deleted_color,
        )

    edits = parse_plan(plan_text, args.author)
    buf, fails, applied = apply_edits(buf, edits)

    written = False
    scan_result = None
    if not args.dry_run and not fails:
        write_text(args.target, buf)
        written = True
        scan_result = scan_files([args.target], None, False)

    for f in fails:
        logger.error("[HYGIENE] patch fail: heading=%s count=%s pattern=%s", f["heading"], f["count"], f["pattern"])

    return {
        "target": args.target,
        "plan": args.plan,
        "dry_run": bool(args.dry_run),
        "edits_total": len(edits),
        "edits_applied": applied,
        "fails": fails,
        "written": written,
        "init_applied": init_applied,
        "scan": scan_result,
    }


def print_patch_text(result: Dict) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Plain-text rendering of a `patch` result for interactive use.

    Inputs:
        result (Dict): output of run_patch.

    Outputs:
        None. Writes to stdout.
    --------------------------------------------------------------------------
    """
    print("target: %s | plan: %s | dry_run: %s" % (result["target"], result["plan"], result["dry_run"]))
    print("edits: %d total, %d applied, %d failed" % (result["edits_total"], result["edits_applied"], len(result["fails"])))
    if result["fails"]:
        print("FAILS:")
        for f in result["fails"]:
            print("  [%s] count=%s pattern=%s" % (f["heading"], f["count"], f["pattern"]))
    print("written:", result["written"])
    if result["init_applied"] is not None:
        print("init_applied:", result["init_applied"])
    if result["scan"]:
        print("--- post-write scan ---")
        print_scan_text(result["scan"])
