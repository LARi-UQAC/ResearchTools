#!/usr/bin/env python3
"""
manuscript_bib.py — Bibliography + citation module for the word2latex skill
(manuscript mode, opt-in via --bibliography).

Deterministic first-pass extractor. It does NOT replace the existing
XML-inspect + pandoc + agent visual-fidelity pipeline; it only fills the two
gaps that pipeline has for *manuscripts* (papers): a BibTeX bibliography and
inline citation rewriting. The emitted .bib is a FIRST PASS only — route it
through /bibclean then /scopus to normalise, deduplicate, enrich DOIs, annotate
SJR quartile, and flag non-approved publishers (see
../references/manuscript_bibliography.md).

Adapted from SciDeliberate/docx2latex/docx2latex/scripts/docx2latex.py
(parse_bib_entries, render_bibtex, sup_to_cite). The citation detector here is
extended beyond Unicode superscripts to also cover pandoc's
``\\textsuperscript{...}`` markers and IEEE-style ``[n]`` / ``[n-m]`` brackets,
because the input is the pandoc-produced .tex (or an auxiliary gfm markdown),
not the docx skill's _clean.md.

Usage:
    python manuscript_bib.py SOURCE [--bib-source PATH] [--out PATH]
                                    [--bib PATH] [--no-brackets]

    SOURCE         text scanned for citations and (if --bib-source absent) for
                   the numbered bibliography. Usually <file>.tex from pandoc,
                   or a markdown file.
    --bib-source   separate file to parse the numbered bibliography from
                   (preferred: a gfm markdown that keeps explicit "1." numbers).
    --out          rewritten SOURCE with citations as \\cite{...}
                   (default: <stem>.cited<ext>, never overwrites SOURCE).
    --bib          BibTeX output (default: <stem>.first-pass.bib).
    --no-brackets  disable [n] bracket -> \\cite conversion (keep only
                   superscript forms).

Outputs (stdout) a QC summary: entries, citation keys, unresolved cites
(\\cite{refN}), bracket conversions. Stdlib only — no external dependency.
"""

import argparse
import logging
import re
import sys
from datetime import date
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Patterns (Unicode-superscript block ported verbatim from docx2latex.py)
# --------------------------------------------------------------------------
SUP_TRANS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹",
                          "0123456789")
SUP_PATTERN = re.compile(
    r"[⁰¹²³⁴-⁹]"
    r"[⁰¹²³⁴-⁹,⁻–—\-\s]*"
    r"[⁰¹²³⁴-⁹]"
    r"|[⁰¹²³⁴-⁹]"
)
TEXSUP_PATTERN = re.compile(r"\\textsuperscript\{([0-9][0-9,\s\-–—]*)\}")
# Bracket cites: require digit-only content; lookbehind rejects backslash and
# word chars so \item[1], array[1], fig[1], display-math \[ are left alone.
BRACKET_PATTERN = re.compile(r"(?<![\\\w])\[\s*([0-9][0-9,\s\-–—]*)\]")

BIB_HEADER = re.compile(r"(?i)^(#+\s*)?(bibliograph|r[eé]f[eé]rence|references)")
DOI_RE = re.compile(r"\bdoi[:\s]+([^\s,;\)]+)", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
REF_LINE = re.compile(r"^(\d+)[.\)]\s*(.+)")
LATEX_SPECIAL = [
    ("&", r"\&"), ("%", r"\%"), ("$", r"\$"), ("#", r"\#"),
    ("_", r"\_"), ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}"),
]


# --------------------------------------------------------------------------
# Bibliography parsing
# --------------------------------------------------------------------------
def find_bib_start(lines: list[str]) -> Optional[int]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate the first line index following a bibliography/references heading.

    Inputs:
        lines (list[str]): document lines.

    Outputs:
        result (Optional[int]): index of the first reference line, or None.
    --------------------------------------------------------------------------
    """
    for i, line in enumerate(lines):
        if BIB_HEADER.match(line.strip()):
            return i + 1
    return None


def parse_bib_entries(lines: list[str]) -> list[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse a numbered bibliography into first-pass entries (number, key,
        authors, title, year, doi, raw). Multi-line entries are merged.

    Inputs:
        lines (list[str]): document lines including the bibliography section.

    Outputs:
        result (list[dict]): one dict per reference, with a collision-free
            BibTeX key ({firstauthor}{year}, suffixed b, c, ... on collision).
    --------------------------------------------------------------------------
    """
    start = find_bib_start(lines)
    if start is None:
        return []

    raws: list[str] = []
    current = ""
    for line in lines[start:]:
        s = line.strip()
        if not s:
            if current:
                raws.append(current)
                current = ""
            continue
        if REF_LINE.match(s):
            if current:
                raws.append(current)
            current = s
        else:
            current = (current + " " + s) if current else s
    if current:
        raws.append(current)

    entries: list[dict] = []
    seen: dict[str, int] = {}

    for raw in raws:
        m = REF_LINE.match(raw.strip())
        if not m:
            continue
        num = int(m.group(1))
        body = m.group(2).strip()

        doi = ""
        dm = DOI_RE.search(body)
        if dm:
            doi = dm.group(1).rstrip(".,)")
            body = body[: dm.start()].strip()

        ym = YEAR_RE.search(body)
        year = ym.group(0) if ym else ""
        parts = [p.strip() for p in body.split(".") if p.strip()]
        authors = parts[0] if parts else ""
        title = parts[1] if len(parts) > 1 else ""

        first = re.sub(r"[^a-zA-Z]", "",
                       (authors.split(",")[0].split()[0] if authors else "ref"))
        base = f"{first.lower()}{year}"
        if base in seen:
            seen[base] += 1
            key = f"{base}{chr(96 + seen[base])}"
        else:
            seen[base] = 0
            key = base

        entries.append({"num": num, "key": key, "authors": authors,
                        "title": title, "year": year, "doi": doi,
                        "raw": raw[:200]})
    return entries


def render_bibtex(entries: list[dict]) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Render first-pass entries as BibTeX. @article when a DOI is present,
        else @misc. The original entry text is kept in `note` so /bibclean and
        /scopus can recover journal/volume/pages later.

    Inputs:
        entries (list[dict]): output of parse_bib_entries.

    Outputs:
        result (str): BibTeX file body.
    --------------------------------------------------------------------------
    """
    blocks = []
    for e in entries:
        btype = "@article" if e["doi"] else "@misc"
        lines = [f"{btype}{{{e['key']},"]
        if e["authors"]:
            lines.append(f'  author    = {{{e["authors"]}}},')
        if e["title"]:
            lines.append(f'  title     = {{{{{e["title"]}}}}},')
        if e["year"]:
            lines.append(f'  year      = {{{e["year"]}}},')
        if e["doi"]:
            lines.append(f'  doi       = {{{e["doi"]}}},')
            lines.append(f'  url       = {{https://doi.org/{e["doi"]}}},')
        lines.append(f'  note      = {{[{e["num"]}] {e["raw"][:100]}}},')
        lines.append("}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


# --------------------------------------------------------------------------
# Citation conversion
# --------------------------------------------------------------------------
def _expand_nums(norm: str) -> list[int]:
    """Expand a normalised "1,2,5" or "1-3" string into a list of ints."""
    nums: list[int] = []
    for part in re.split(r"[,\s]+", norm):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                a, b = part.split("-", 1)
                nums.extend(range(int(a), int(b) + 1))
            except ValueError:
                pass
        else:
            try:
                nums.append(int(part))
            except ValueError:
                pass
    return nums


def _nums_to_cite(nums: list[int], num_to_key: dict[int, str]) -> str:
    keys = [num_to_key.get(n, f"ref{n}") for n in nums if n]
    return r"\cite{" + ",".join(keys) + "}" if keys else ""


def sup_to_cite(match_str: str, num_to_key: dict[int, str]) -> str:
    """Unicode superscript range -> \\cite{...}; unresolved numbers -> refN."""
    norm = (match_str.translate(SUP_TRANS)
            .replace("⁻", "-").replace("–", "-").replace("—", "-"))
    cite = _nums_to_cite(_expand_nums(norm), num_to_key)
    return cite or match_str


def texsup_to_cite(inner: str, num_to_key: dict[int, str]) -> str:
    """pandoc \\textsuperscript{1-3} -> \\cite{...}; unresolved -> refN."""
    norm = inner.replace("–", "-").replace("—", "-")
    cite = _nums_to_cite(_expand_nums(norm), num_to_key)
    return cite or f"\\textsuperscript{{{inner}}}"


def bracket_to_cite(inner: str, num_to_key: dict[int, str]) -> str:
    """
    [1-3] -> \\cite{...} ONLY when every number resolves to a known key.
    Brackets are ambiguous, so an unresolved number leaves the text untouched
    rather than emitting a refN placeholder.
    """
    norm = inner.replace("–", "-").replace("—", "-")
    nums = _expand_nums(norm)
    if nums and all(n in num_to_key for n in nums):
        return _nums_to_cite(nums, num_to_key)
    return f"[{inner}]"


def convert_citations(text: str, num_to_key: dict[int, str],
                      brackets: bool = True) -> tuple[str, int]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Rewrite inline citations to \\cite{...}. Handles pandoc
        \\textsuperscript{}, Unicode superscripts, and (optionally) [n]
        brackets, in that order.

    Inputs:
        text (str): source text.
        num_to_key (dict[int, str]): bibliography number -> BibTeX key.
        brackets (bool): convert [n] brackets when True.

    Outputs:
        result (tuple[str, int]): rewritten text, count of bracket conversions.
    --------------------------------------------------------------------------
    """
    text = TEXSUP_PATTERN.sub(
        lambda m: texsup_to_cite(m.group(1), num_to_key), text)
    text = SUP_PATTERN.sub(
        lambda m: sup_to_cite(m.group(0), num_to_key), text)

    bracket_count = 0
    if brackets:
        def _sub(m: re.Match) -> str:
            nonlocal bracket_count
            out = bracket_to_cite(m.group(1), num_to_key)
            if out.startswith("\\cite"):
                bracket_count += 1
            return out
        text = BRACKET_PATTERN.sub(_sub, text)
    return text, bracket_count


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="word2latex manuscript bibliography module")
    p.add_argument("source", help="Text scanned for citations / bibliography")
    p.add_argument("--bib-source", help="Separate file to parse the bibliography from")
    p.add_argument("--out", help="Rewritten source output path")
    p.add_argument("--bib", help="BibTeX output path")
    p.add_argument("--no-brackets", action="store_true",
                   help="Disable [n] bracket -> \\cite conversion")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    src = Path(args.source)
    if not src.exists():
        print(f"ERROR: {src} not found", file=sys.stderr)
        sys.exit(1)

    src_text = src.read_text(encoding="utf-8")

    bib_path = Path(args.bib_source) if args.bib_source else src
    if not bib_path.exists():
        print(f"ERROR: {bib_path} not found", file=sys.stderr)
        sys.exit(1)
    bib_lines = bib_path.read_text(encoding="utf-8").splitlines()

    entries = parse_bib_entries(bib_lines)
    num_to_key = {e["num"]: e["key"] for e in entries}

    cited_text, bracket_count = convert_citations(
        src_text, num_to_key, brackets=not args.no_brackets)

    stem = src.stem
    out_path = Path(args.out) if args.out else src.with_name(f"{stem}.cited{src.suffix}")
    out_bib = Path(args.bib) if args.bib else src.with_name(f"{stem}.first-pass.bib")

    header = (f"% First-pass BibTeX generated by manuscript_bib.py on "
              f"{date.today().isoformat()}.\n"
              f"% Route through /bibclean then /scopus before use.\n\n")
    out_path.write_text(cited_text, encoding="utf-8")
    out_bib.write_text(header + render_bibtex(entries) + "\n", encoding="utf-8")

    unresolved = len(re.findall(r"\\cite\{ref\d+\}", cited_text))
    logger.info("[BIB] Rewritten source : %s", out_path)
    logger.info("[BIB] First-pass BibTeX: %s", out_bib)
    logger.info("[BIB]   Entries          : %d", len(entries))
    logger.info("[BIB]   Citation keys    : %d", len(num_to_key))
    logger.info("[BIB]   Bracket cites    : %d", bracket_count)
    logger.info("[BIB]   Unresolved cites : %d  (grep \\cite{refN})", unresolved)
    logger.info("[BIB]   Next             : /bibclean %s  then  /scopus validate", out_bib.name)


if __name__ == "__main__":
    main()
