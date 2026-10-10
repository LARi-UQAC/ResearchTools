"""
pdf2md_postprocess - Stage 5 of the pdf2md pipeline: clean mineru's raw
markdown output and split it into UQAC-shaped files.

The defect this cleans up is specific and measured, not a generic "markdown
cleanup" pass: mineru's own title_leveling LLM step is meant to collapse a
page's running header (chapter title repeated on every page, sometimes with
the page number fused into it by the layout model, e.g.
"CHAPITRE 3. OPTIMISATION ... AVEC 54 PRIORITÉS...") back into the body text.
When that LLM step fails or is disabled (see pdf2md_config's
max_concurrency fix), mineru degrades by leaving the running header as a
spurious markdown heading sitting mid-paragraph. The sentence content is
NOT lost -- just split across a heading that should not exist. Confirmed on
a real 162-page UQAC thesis conversion, 2026-10-10: a sentence read
"...L'etude de revue presentee au" / [spurious heading] / "Chapitre 2 a
montre que..." -- deleting the heading and joining the two halves recovers
the original, grammatically complete sentence ("...presentee au Chapitre 2
a montre que...").

Known limitation: the detector is a fuzzy text-repeat heuristic (a heading
whose digit-stripped text closely matches an EARLIER heading's is treated as
a repeat), so it can theoretically misfire on a thesis with two genuinely
distinct sections that happen to share near-identical titles. This has not
been observed in practice; it is stated here the same way extract-contributions
states its own known misses, rather than claimed away.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_CHAPTER_NUMBER_RE = re.compile(r"^chapitre\s+(\d+)\b", re.IGNORECASE)
_MATH_FENCE = "$$"
_STRUCTURAL_PREFIXES = ("-", "*", "|", "```")
_NUMBERED_REF_RE = re.compile(r"^\[(\d+)\]\s")
_BIBLIOGRAPHY_HEADING_RE = re.compile(r"^(r[ée]f[ée]rences|bibliographie)\b", re.IGNORECASE)
FUZZY_MATCH_RATIO = 0.85


def _normalize_heading_text(text: str) -> str:
    """Strip digits/punctuation and lowercase, for repeat detection tolerant of a spliced-in page number."""
    stripped_digits = re.sub(r"\d+", "", text)
    return re.sub(r"[^\w]+", " ", stripped_digits, flags=re.UNICODE).strip().lower()


@dataclass
class Heading:
    """
    --------------------------------------------------------------------------
    Purpose:
        One markdown heading line found in a document, with the line index
        it occupies for later in-place editing.

    Inputs:
        None.

    Outputs:
        line_index (int), level (int), text (str), chapter_number (int|None)
    --------------------------------------------------------------------------
    """

    line_index: int
    level: int
    text: str
    chapter_number: int | None = None


def find_headings(lines: list[str]) -> list[Heading]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Locate every markdown heading line, skipping any that sit inside a
        $$ math fence (a line of exactly "$$" toggles fence state) -- a
        line starting with "#" inside LaTeX math is not a heading.

    Inputs:
        lines (list[str]): the document, one entry per line (no trailing
            newlines).

    Outputs:
        list[Heading]: in document order.
    --------------------------------------------------------------------------
    """
    headings: list[Heading] = []
    in_math = False
    for index, line in enumerate(lines):
        if line.strip() == _MATH_FENCE:
            in_math = not in_math
            continue
        if in_math:
            continue
        match = _HEADING_RE.match(line)
        if not match:
            continue
        level, text = len(match.group(1)), match.group(2)
        chapter_match = _CHAPTER_NUMBER_RE.match(text)
        headings.append(Heading(index, level, text, int(chapter_match.group(1)) if chapter_match else None))
    return headings


def find_spurious_headings(headings: list[Heading], *, ratio: float = FUZZY_MATCH_RATIO) -> list[Heading]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Flag headings that are a near-repeat of an EARLIER heading's text
        (digit-stripped) -- the running-header splice signature. The first
        occurrence of any heading text is always kept; only later repeats
        of the same text are spurious.

    Inputs:
        headings (list[Heading]): as returned by find_headings, in order.
        ratio (float): difflib.SequenceMatcher threshold for "close enough".

    Outputs:
        list[Heading]: the subset judged spurious.
    --------------------------------------------------------------------------
    """
    seen_normalized: list[str] = []
    spurious: list[Heading] = []
    for heading in headings:
        normalized = _normalize_heading_text(heading.text)
        is_repeat = any(
            difflib.SequenceMatcher(None, normalized, earlier).ratio() >= ratio for earlier in seen_normalized
        )
        if is_repeat:
            spurious.append(heading)
        else:
            seen_normalized.append(normalized)
    return spurious


def _is_structural_line(line: str) -> bool:
    stripped = line.strip()
    return (
        not stripped
        or stripped == _MATH_FENCE
        or bool(_HEADING_RE.match(line))
        or stripped.startswith(_STRUCTURAL_PREFIXES)
        or bool(re.match(r"^\d+\.\s", stripped))
    )


def strip_splice_headings(lines: list[str], spurious: list[Heading]) -> tuple[list[str], int]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Remove every spurious heading line. Where both the nearest preceding
        and following non-blank lines are plain prose (not a math fence,
        list, table, heading, or numbered item), join them into one flowing
        paragraph -- recovering the sentence the splice broke. Otherwise
        (e.g. a heading sitting right after an equation block) just delete
        the heading, since forcing a join there would corrupt structure
        rather than recover a sentence.

    Inputs:
        lines (list[str]): the document.
        spurious (list[Heading]): headings to remove, as returned by
            find_spurious_headings.

    Outputs:
        (list[str], int): the cleaned document, and how many headings were
            removed.
    --------------------------------------------------------------------------
    """
    remove_indices = {heading.line_index for heading in spurious}
    result: list[str] = []
    index = 0
    removed = 0
    while index < len(lines):
        if index not in remove_indices:
            result.append(lines[index])
            index += 1
            continue

        removed += 1
        prev_index = len(result) - 1
        while prev_index >= 0 and not lines[prev_index].strip():
            prev_index -= 1
        next_index = index + 1
        while next_index < len(lines) and not lines[next_index].strip():
            next_index += 1

        prev_line = lines[prev_index] if prev_index >= 0 else ""
        next_line = lines[next_index] if next_index < len(lines) else ""
        can_merge = (
            prev_index >= 0
            and next_index < len(lines)
            and not _is_structural_line(prev_line)
            and not _is_structural_line(next_line)
        )

        if can_merge:
            result[prev_index] = prev_line.rstrip() + " " + next_line.lstrip()
            index = next_index + 1
        else:
            index += 1

    return result, removed


@dataclass
class SplitResult:
    """
    --------------------------------------------------------------------------
    Purpose:
        The document split into the files pdf2md writes, mirroring the
        front-matter/chapters/bibliography shape of a real UQAC thesis
        export.

    Inputs:
        None.

    Outputs:
        frontmatter (str): everything before the first real CHAPITRE heading.
        chapters (dict[int, tuple[str, str]]): chapter number -> (title,
            body text), in encounter order.
        bibliography (str | None): the bibliography block, held out of the
            last chapter if one was detected; None if none was found.
    --------------------------------------------------------------------------
    """

    frontmatter: str
    chapters: dict[int, tuple[str, str]] = field(default_factory=dict)
    bibliography: str | None = None


def split_frontmatter_and_chapters(lines: list[str], headings: list[Heading]) -> SplitResult:
    """
    --------------------------------------------------------------------------
    Purpose:
        Split a (spurious-heading-free) document into front matter, one
        block per real CHAPITRE N heading, and a trailing bibliography.

    Inputs:
        lines (list[str]): the cleaned document.
        headings (list[Heading]): headings of the CLEANED document (call
            find_headings again after strip_splice_headings, since removing
            lines shifts every later line_index).

    Outputs:
        SplitResult
    --------------------------------------------------------------------------
    """
    chapter_headings = [h for h in headings if h.chapter_number is not None]
    frontmatter_end = chapter_headings[0].line_index if chapter_headings else len(lines)
    frontmatter = "\n".join(lines[:frontmatter_end]).strip() + "\n"

    bibliography: str | None = None
    bibliography_start: int | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if _BIBLIOGRAPHY_HEADING_RE.match(stripped.lstrip("#").strip()) or (
            _NUMBERED_REF_RE.match(stripped) and bibliography_start is None
        ):
            bibliography_start = index
            break
    if bibliography_start is not None:
        bibliography = "\n".join(lines[bibliography_start:]).strip() + "\n"

    chapters: dict[int, tuple[str, str]] = {}
    for position, heading in enumerate(chapter_headings):
        body_end = chapter_headings[position + 1].line_index if position + 1 < len(chapter_headings) else (
            bibliography_start if bibliography_start is not None else len(lines)
        )
        body_end = max(body_end, heading.line_index)
        chapters[heading.chapter_number] = (heading.text, "\n".join(lines[heading.line_index:body_end]).strip() + "\n")

    return SplitResult(frontmatter=frontmatter, chapters=chapters, bibliography=bibliography)


def process_document(markdown_text: str) -> tuple[SplitResult, int]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Full stage-5 pipeline on one markdown string: find and strip
        splice-defect headings, then split into front matter / chapters /
        bibliography.

    Inputs:
        markdown_text (str): the raw mineru output.

    Outputs:
        (SplitResult, int): the split result, and the number of splice
            headings removed.
    --------------------------------------------------------------------------
    """
    lines = markdown_text.splitlines()
    headings = find_headings(lines)
    spurious = find_spurious_headings(headings)
    cleaned_lines, removed_count = strip_splice_headings(lines, spurious)
    cleaned_headings = find_headings(cleaned_lines)
    split = split_frontmatter_and_chapters(cleaned_lines, cleaned_headings)
    return split, removed_count


def _main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("markdown_file")
    parser.add_argument("-o", "--output-dir", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    source = Path(args.markdown_file)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    split, removed_count = process_document(source.read_text(encoding="utf-8"))
    (out_dir / "frontmatter.md").write_text(split.frontmatter, encoding="utf-8")
    for number, (title, body) in sorted(split.chapters.items()):
        (out_dir / f"chapitre{number}.md").write_text(body, encoding="utf-8")

    bibliography_path = None
    if split.bibliography is not None:
        bibliography_path = out_dir / "bibliography.md"
        bibliography_path.write_text(split.bibliography, encoding="utf-8")

    report = {
        "ok": True,
        "splice_headings_removed": removed_count,
        "chapters_written": sorted(split.chapters.keys()),
        "bibliography_found": split.bibliography is not None,
        "bibliography_path": str(bibliography_path) if bibliography_path else None,
        "frontmatter_path": str(out_dir / "frontmatter.md"),
    }
    print(json.dumps(report) if args.json else report)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
