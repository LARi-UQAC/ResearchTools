"""
extract_paper_idea - mechanical merge only: pulls a paper's own content into one
JSON artifact by reusing three sibling scripts (paper_extract, extract_text,
extract_contributions), so the abstract-writer agent has real evidence for
every field it fills instead of re-reading the whole paper itself each time.

Stage: authoring, before an abstract or a UQAC Resume is drafted. Ships no
reader of its own (R18: paper2talk owns \\input flattening and the section
map, extract-statistic owns the future-works-cue section scan, and
extract-contributions owns the contribution/novelty/method/result marker
scan) - this module only calls them and assembles the schema.

The fields left as null/empty by this script (background_context,
objective_purpose, implications, hypotheses, keyword_candidates, and the
drafted abstract/resume text itself) are LLM judgment the calling agent
supplies next; this script never invents them. `hypotheses` matters only for
a UQAC thesis Resume, which needs one of its six required components stated
that no marker scan can surface on its own.
"""

import argparse
import json
import os
import re
import sys
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))


def _sibling_import(skill_dir: str, module_name: str):
    """
    --------------------------------------------------------------------------
    Purpose:
        Import a sibling skill's script module by inserting its scripts/
        directory onto sys.path, the same cross-skill import pattern
        extract_contributions.py already uses to reach extract_text.py (R18).

    Inputs:
        skill_dir (str): the sibling skill's directory name under .claude/skills/
        module_name (str): the module to import from that directory

    Outputs:
        module: the imported module object.

    Raises:
        SystemExit: the sibling skill is absent from this clone.
    --------------------------------------------------------------------------
    """
    path = os.path.normpath(os.path.join(_HERE, "..", "..", skill_dir, "scripts"))
    sys.path.insert(0, path)
    try:
        return __import__(module_name)
    except ImportError as exc:  # pragma: no cover - the sibling skill must be present
        print("ERROR: cannot import %s from %s (%s)" % (module_name, path, exc),
              file=sys.stderr)
        sys.exit(1)


paper_extract = _sibling_import("paper2talk", "paper_extract")
extract_text = _sibling_import("extract-statistic", "extract_text")
extract_contributions = _sibling_import("extract-contributions", "extract_contributions")

_UQAC_CLS_RE = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{uqac\}")
_ABSTRACT_RE = re.compile(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", re.S)
_RESUME_RE = re.compile(r"\\begin\{resume\}(.*?)\\end\{resume\}", re.S)
_TITLE_RE = re.compile(r"\\title\{([^}]*)\}")

_BABEL_RE = re.compile(r"\\usepackage\[([^\]]*)\]\{babel\}", re.I)
_FRENCH_ALIASES = {"french", "francais", "frenchb", "acadian"}
_ENGLISH_ALIASES = {"english", "american", "british", "australian", "canadian"}

# Environments whose payload is not the paper's own new-evidence prose: an
# existing abstract/resume restates (or misstates) the claim under evaluation,
# and a bibliography is other papers' titles, not this paper's own words.
_EVIDENCE_STRIP_RE = re.compile(
    r"\\begin\{(?:abstract|resume|thebibliography)\}.*?\\end\{(?:abstract|resume|thebibliography)\}",
    re.S)

# A section/subsection heading, converted into its own short titled sentence
# (leading AND trailing period) so text on either side of it gets a real
# sentence boundary. Left as a bare "\section{...}" macro, the backslash
# blocks the capital-letter lookahead extract_contributions' splitter uses,
# gluing the heading and neighbouring prose into one corrupted "sentence"
# (measured 2026-09-25, see test_a_heading_with_no_preceding_period...).
_HEADING_RE = re.compile(r"\\(?:sub)*section\*?\{([^}]*)\}")


def _prepare_evidence_text(flattened: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Produce the text the contribution/novelty/method/result marker scan
        is run against: the paper's own new prose only (no existing abstract,
        resume, or bibliography), with section headings turned into
        sentence-boundary-safe text instead of a bare LaTeX macro.

    Inputs:
        flattened (str): the fully \\input/\\include-resolved LaTeX source.

    Outputs:
        str: evidence text, safe to hand to extract_contributions.analyse_file.
    --------------------------------------------------------------------------
    """
    text = _EVIDENCE_STRIP_RE.sub(" ", flattened)
    text = _HEADING_RE.sub(lambda m: ". " + m.group(1).strip() + ". ", text)
    return text


def _detect_document_type(flattened: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide paper vs UQAC thesis from the flattened text, the same signal
        thesis-auditor.md already uses (uqac.cls in the preamble). Runs on the
        FLATTENED text, not just the main file, so a thesis whose uqac.cls
        sits in an \\input'd setup file is still detected correctly.

    Inputs:
        flattened (str): the fully \\input/\\include-resolved LaTeX source.

    Outputs:
        str: "thesis" or "paper".
    --------------------------------------------------------------------------
    """
    return "thesis" if _UQAC_CLS_RE.search(flattened) else "paper"


def _detect_language(flattened: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Detect the document's own current language: babel option first, a
        stopword-count fallback otherwise. Never a forced default - a paper's
        abstract must be drafted in the language the paper is already in.

    Details:
        babel's own convention is that the LAST language in the option list is
        the main document language (`[french,english]` means English), so a
        bare substring search for "french"/"english" answers the wrong
        question on a multi-language document. French aliases (`francais`,
        `frenchb`, `acadian`) are also babel-valid and are mapped explicitly.

    Inputs:
        flattened (str): the fully resolved LaTeX source.

    Outputs:
        str: "fr" or "en".
    --------------------------------------------------------------------------
    """
    m = _BABEL_RE.search(flattened)
    if m:
        options = [o.strip().lower() for o in m.group(1).split(",") if o.strip()]
        if options:
            last = options[-1]
            if last in _FRENCH_ALIASES:
                return "fr"
            if last in _ENGLISH_ALIASES:
                return "en"
    fr_hits = len(re.findall(r"\b(le|la|les|des|est|dans|pour|nous)\b", flattened, re.I))
    en_hits = len(re.findall(r"\b(the|is|are|for|this|that|we)\b", flattened, re.I))
    return "fr" if fr_hits > en_hits else "en"


def _extract_existing(pattern: "re.Pattern[str]", flattened: str) -> tuple[str | None, bool]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Capture an existing \\begin{abstract}/\\begin{resume} payload verbatim,
        so the calling agent can show it before any overwrite, and report
        whether the environment exists at all - distinct from existing but
        blank, since "nothing to overwrite" and "overwrite an empty shell"
        call for different agent behaviour.

    Inputs:
        pattern (re.Pattern): the compiled environment regex to search for.
        flattened (str): the fully resolved LaTeX source.

    Outputs:
        (str | None, bool): the payload text (None when absent or blank), and
        whether the environment itself was found (True even if its body is
        blank).
    --------------------------------------------------------------------------
    """
    m = pattern.search(flattened)
    if not m:
        return None, False
    text = m.group(1).strip()
    return (text or None), True


def build_extraction(tex_path: str) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Merge paper_extract, extract_text.scan_sections, and
        extract_contributions.analyse_file into one JSON-serializable schema
        for the abstract-writer agent.

    Inputs:
        tex_path (str): path to the paper's main .tex file.

    Outputs:
        dict: the merged extraction schema. LLM-judgment fields
        (background_context, objective_purpose, implications, hypotheses,
        keyword_candidates) are always null/empty here; the calling agent
        fills them.
    --------------------------------------------------------------------------
    """
    flattened, include_warnings = paper_extract.resolve_includes(tex_path)
    sections = paper_extract.sections_of(flattened)
    warnings = list(include_warnings)
    if not sections:
        warnings.append("no \\section found in the flattened document")

    fw_sections = extract_text.scan_sections(flattened)
    future_work = [s["excerpt"] for s in fw_sections
                   if s["label"] in ("future_work", "open_problems")]
    limitations = [s["excerpt"] for s in fw_sections if s["label"] == "limitations"]

    evidence_text = _prepare_evidence_text(flattened)
    markers = extract_contributions.load_markers()
    contrib_record = extract_contributions.analyse_file(tex_path, markers, text=evidence_text)

    contribution_status = contrib_record.get("status", "unreadable")
    if contribution_status != "ok":
        warnings.append("contribution scan status: %s (%s)" % (
            contribution_status,
            contrib_record.get("reason", "no marker matched the paper's own text")))

    sentences = contrib_record.get("sentences", [])
    contribution_novelty = [s["sentence"] for s in sentences
                             if s["kind"] in ("contribution", "novelty")]
    key_findings = [s["sentence"] for s in sentences if s["kind"] == "result"]
    methodology_sentences = [s["sentence"] for s in sentences if s["kind"] == "method"]

    title_match = _TITLE_RE.search(flattened)
    existing_abstract, abstract_present = _extract_existing(_ABSTRACT_RE, flattened)
    existing_resume, resume_present = _extract_existing(_RESUME_RE, flattened)

    return {
        "source": {
            "tex_path": os.path.abspath(tex_path),
            "document_type": _detect_document_type(flattened),
            "language": _detect_language(flattened),
        },
        "title": title_match.group(1).strip() if title_match else None,
        "section_map": [{"level": s["level"], "title": s["title"], "words": s["words"],
                          "text": s["text"][:2000]}
                         for s in sections],
        "background_context": None,
        "objective_purpose": None,
        "methodology_summary": " ".join(methodology_sentences) or None,
        "key_findings": key_findings,
        "contribution_novelty": contribution_novelty,
        "contribution_status": contribution_status,
        "limitations": limitations,
        "future_work": future_work,
        "implications": None,
        "hypotheses": [],
        "keyword_candidates": [],
        "existing_abstract": existing_abstract,
        "existing_abstract_present": abstract_present,
        "existing_resume": existing_resume,
        "existing_resume_present": resume_present,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        CLI entry point: build the extraction, write it beside the paper, and
        optionally print it to stdout as JSON.

    Inputs:
        argv (list[str] | None): CLI arguments, or None to read sys.argv.

    Outputs:
        int: process exit code (always 0; this script never fails on a
        well-formed .tex path - a section-less or contribution-less paper is
        a warning, not an error).
    --------------------------------------------------------------------------
    """
    extract_text.configure_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tex_path", help="path to the paper's main .tex file")
    parser.add_argument("--out", default=None, help="output JSON path "
                         "(default: <basename>_abstract_extraction.json beside the paper)")
    parser.add_argument("--json", action="store_true", help="also print the JSON to stdout")
    args = parser.parse_args(argv)

    result = build_extraction(args.tex_path)
    out_path = args.out or (os.path.splitext(args.tex_path)[0] + "_abstract_extraction.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("[EXTRACT-PAPER-IDEA] wrote %s (%d section(s), %d warning(s))" % (
            out_path, len(result["section_map"]), len(result["warnings"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
