"""
pdf2md_refs - Stage 6 of the pdf2md pipeline: restructure mineru's flat
numbered bibliography into a BibTeX-like ref.md.

mineru renders a thesis bibliography as a flat numbered list
(`[171] Lin Xiao and Stephen Boyd. Fast linear iterations for distributed
averaging. Systems & Control Letters, 53(1):65-78, 2004.`). This module
splits each entry into (authors, title, venue/year) fields -- a heuristic
text split, not a citation parser with full correctness guarantees (real
author-name disambiguation, venue abbreviation expansion, etc. are out of
scope). Keys follow this repo's own citation-label convention
(code-style.md: first author, year, one keyword) so the output reads like
a .bib file's entries even though it is markdown, not BibTeX syntax -- the
earlier confirmed output-shape decision for this skill.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ENTRY_START_RE = re.compile(r"^\[(\d+)\]\s+(.*)$")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_AUTHOR_SEPARATOR_RE = re.compile(r",\s+|\s+and\s+")
_NAME_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ\-']+")
_KEYWORD_STOPWORDS = {
    "a", "an", "the", "of", "for", "on", "in", "with", "and", "to", "using",
    "based", "via", "under", "from", "between", "toward", "towards",
}


@dataclass
class RefEntry:
    """
    --------------------------------------------------------------------------
    Purpose:
        One parsed bibliography entry.

    Inputs:
        None.

    Outputs:
        number (str): the original numbered-list index, e.g. "171".
        authors (str): everything before the first sentence boundary.
        title (str): the sentence after authors, before the venue.
        venue_year (str): the remainder, typically "<venue>, <year>."
        key (str): firstauthor+year+onekeyword, this repo's citation-label
            convention (code-style.md).
    --------------------------------------------------------------------------
    """

    number: str
    authors: str
    title: str
    venue_year: str
    key: str


def _split_sentences(text: str) -> list[str]:
    """
    Split on plain '. ' boundaries. mineru's own bibliography rendering
    does not abbreviate names with mid-name periods (a middle initial
    renders as "Karl H Johansson", no period after "H" -- confirmed on a
    real thesis bibliography this session), so a plain split is the
    correct match for its actual output rather than a defensive
    abbreviation guard that would misfire on it.
    """
    parts = re.split(r"\.\s+", text.strip())
    return [part.strip().rstrip(".") for part in parts if part.strip()]


def _first_author_surname(authors: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Isolate the first author's SURNAME (last whitespace-separated name
        token), not their first name. Regression: a plain "first word of
        the authors string" match returned the first author's given name
        for every real entry ("Javier Alonso-Mora" -> "javier" instead of
        "alonso-mora"), since mineru renders "Firstname Lastname" with no
        comma between them.

    Inputs:
        authors (str): the full authors field, e.g.
            "Javier Alonso-Mora, Eduardo Montijano, ..., and Daniela Rus".

    Outputs:
        str: lowercased surname, or "unknown" if no name token is found.
    --------------------------------------------------------------------------
    """
    first_author = _AUTHOR_SEPARATOR_RE.split(authors.strip(), maxsplit=1)[0]
    tokens = _NAME_TOKEN_RE.findall(first_author)
    return tokens[-1].lower() if tokens else "unknown"


def _build_key(authors: str, title: str, venue_year: str) -> str:
    surname = _first_author_surname(authors)
    year_match = _YEAR_RE.search(venue_year) or _YEAR_RE.search(title)
    year = year_match.group(0) if year_match else "0000"
    keyword = next(
        (word.lower() for word in re.findall(r"[A-Za-zÀ-ÿ]+", title) if word.lower() not in _KEYWORD_STOPWORDS and len(word) > 3),
        "ref",
    )
    return f"{surname}{year}{keyword}"


def parse_numbered_references(text: str) -> list[RefEntry]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse a block of `[N] Authors. Title. Venue, Year.` lines (mineru's
        bibliography rendering, one entry possibly spanning several source
        lines until the next `[N]`) into structured entries.

    Inputs:
        text (str): the bibliography block, as extracted by
            pdf2md_postprocess's split_frontmatter_and_chapters.

    Outputs:
        list[RefEntry]: in document order. An entry whose text does not
            contain at least two sentence boundaries (authors/title/venue)
            is still returned, with venue_year left empty, rather than
            dropped -- a partially-structured entry is more useful than a
            silently missing one.
    --------------------------------------------------------------------------
    """
    raw_entries: list[tuple[str, str]] = []
    current_number: str | None = None
    current_lines: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = _ENTRY_START_RE.match(stripped)
        if match:
            if current_number is not None:
                raw_entries.append((current_number, " ".join(current_lines)))
            current_number, first_line = match.group(1), match.group(2)
            current_lines = [first_line]
        elif current_number is not None:
            current_lines.append(stripped)
    if current_number is not None:
        raw_entries.append((current_number, " ".join(current_lines)))

    entries: list[RefEntry] = []
    for number, body in raw_entries:
        sentences = _split_sentences(body)
        authors = sentences[0] if sentences else body
        title = sentences[1] if len(sentences) > 1 else ""
        venue_year = ". ".join(sentences[2:]) if len(sentences) > 2 else ""
        entries.append(RefEntry(number, authors, title, venue_year, _build_key(authors, title, venue_year)))
    return entries


def render_ref_md(entries: list[RefEntry]) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Render parsed reference entries as a BibTeX-like markdown document
        -- one block per entry with authors/title/venue fields labelled,
        so it reads similarly to a .bib file's entries without being real
        BibTeX syntax.

    Inputs:
        entries (list[RefEntry])

    Outputs:
        str: the full ref.md content.
    --------------------------------------------------------------------------
    """
    blocks = []
    for entry in entries:
        lines = [f"### [{entry.number}] {entry.key}", f"- **Authors:** {entry.authors}"]
        if entry.title:
            lines.append(f"- **Title:** {entry.title}")
        if entry.venue_year:
            lines.append(f"- **Venue/Year:** {entry.venue_year}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def _main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bibliography_file", help="a text/markdown file containing the raw [N] ... bibliography block")
    parser.add_argument("-o", "--output", required=True, help="path to write ref.md")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    text = Path(args.bibliography_file).read_text(encoding="utf-8")
    entries = parse_numbered_references(text)
    Path(args.output).write_text(render_ref_md(entries), encoding="utf-8")

    report = {"ok": True, "reference_count": len(entries), "output": args.output}
    print(json.dumps(report) if args.json else report)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
