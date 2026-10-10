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
#: Heuristic threshold, not a measurement: how many MORE "[N] ..." lines must
#: appear in the window following a candidate bibliography start before it is
#: trusted. A real bibliography is dense with these lines; a single inline
#: citation like "[40] presented a method..." sitting alone in ordinary prose
#: is not. Measured 2026-10-11: a real 162-page thesis with no actual
#: "RÉFÉRENCES" heading in its mineru output had its bibliography-start
#: fallback fire on an in-text citation roughly 1/4 of the way through the
#: document, swallowing the rest of the thesis (including a whole chapter)
#: into a 1.5 MB "bibliography".
_BIBLIOGRAPHY_DENSITY_WINDOW = 30
_BIBLIOGRAPHY_DENSITY_MIN_MATCHES = 5


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

        Digit-stripping is what lets "AVEC 54 PRIORITES" match "AVEC
        PRIORITES" (a stray page number fused mid-title). But title_leveling
        can ALSO clean a running header down to a bare "CHAPITRE N" with no
        title words left -- and digit-stripping two of THOSE ("CHAPITRE 1",
        "CHAPITRE 2") collapses them to the identical string "chapitre",
        wrongly flagging every chapter after the first as a repeat of it.
        Measured on a real 162-page thesis, 2026-10-11: chapters 2-5 were
        silently deleted this way, merging the whole rest of the document
        into chapitre1.md. Fix: two headings that both parsed a chapter
        number are NEVER a repeat of each other when those numbers differ,
        regardless of text similarity -- the chapter number is exactly the
        content digit-stripping must not be allowed to erase.

    Inputs:
        headings (list[Heading]): as returned by find_headings, in order.
        ratio (float): difflib.SequenceMatcher threshold for "close enough".

    Outputs:
        list[Heading]: the subset judged spurious.
    --------------------------------------------------------------------------
    """
    seen: list[tuple[str, int | None]] = []
    spurious: list[Heading] = []
    for heading in headings:
        normalized = _normalize_heading_text(heading.text)
        is_repeat = any(
            earlier_chapter == heading.chapter_number
            and difflib.SequenceMatcher(None, normalized, earlier_normalized).ratio() >= ratio
            for earlier_normalized, earlier_chapter in seen
        )
        if is_repeat:
            spurious.append(heading)
        else:
            seen.append((normalized, heading.chapter_number))
    return spurious


def _is_dense_bibliography_start(lines: list[str], index: int) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide whether a line matching the numbered-reference shape
        genuinely opens a bibliography block, versus being a one-off
        in-text citation. See module docstring for the measured false
        positive this guards against.

    Inputs:
        lines (list[str]): the document.
        index (int): the candidate start line (already confirmed to match
            _NUMBERED_REF_RE).

    Outputs:
        bool: True if at least _BIBLIOGRAPHY_DENSITY_MIN_MATCHES further
            lines in the following _BIBLIOGRAPHY_DENSITY_WINDOW lines also
            match the numbered-reference shape.
    --------------------------------------------------------------------------
    """
    window = lines[index + 1 : index + 1 + _BIBLIOGRAPHY_DENSITY_WINDOW]
    further_matches = sum(1 for line in window if _NUMBERED_REF_RE.match(line.strip()))
    return further_matches >= _BIBLIOGRAPHY_DENSITY_MIN_MATCHES


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
        if _BIBLIOGRAPHY_HEADING_RE.match(stripped.lstrip("#").strip()):
            bibliography_start = index
            break
        if _NUMBERED_REF_RE.match(stripped) and _is_dense_bibliography_start(lines, index):
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


def chapter_filenames(chapter_numbers: list[int]) -> dict[int, str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Map each chapter number to its output filename, following the
        universal UQAC thesis convention: the first chapter is always the
        Introduction and the last is always the Conclusion -- true whether
        or not the literal word survives in the text (mineru's own
        running-header cleanup can strip it, as measured 2026-10-11, where
        chapter 1's own "### INTRODUCTION" subheading was removed as a
        false-positive repeat; the chapter's CONTENT -- context, problem
        statement, research questions -- still identifies it as the
        introduction regardless). With fewer than two chapters there is
        nothing to distinguish, so every chapter keeps its plain
        chapitreN.md name.

    Inputs:
        chapter_numbers (list[int]): the chapter numbers actually found.

    Outputs:
        dict[int, str]: chapter number -> filename (no directory).
    --------------------------------------------------------------------------
    """
    if len(chapter_numbers) < 2:
        return {number: f"chapitre{number}.md" for number in chapter_numbers}
    first, last = min(chapter_numbers), max(chapter_numbers)
    return {
        number: "Introduction.md" if number == first else "Conclusion.md" if number == last else f"chapitre{number}.md"
        for number in chapter_numbers
    }


def render_main_md(
    *,
    frontmatter_path: str,
    chapter_paths: dict[int, tuple[str, str]],
    bibliography_path: str | None,
) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Render main.md, the markdown-link index tying every split file
        together in reading order -- the markdown counterpart of a UQAC
        main.tex's \\input list, so the output reads as one linked document
        rather than a pile of loose files.

    Inputs:
        frontmatter_path (str): filename of the front-matter file.
        chapter_paths (dict[int, tuple[str, str]]): chapter number ->
            (filename, heading text), in any order -- sorted here by number.
        bibliography_path (str | None): filename of the bibliography file,
            or None if none was found.

    Outputs:
        str: the full main.md content.
    --------------------------------------------------------------------------
    """
    lines = ["# Thesis", "", f"- [Front matter]({frontmatter_path})"]
    for number, (filename, title) in sorted(chapter_paths.items()):
        heading = title if title else f"Chapitre {number}"
        if filename == "Introduction.md":
            label = f"Introduction ({heading})"
        elif filename == "Conclusion.md":
            label = f"Conclusion ({heading})"
        else:
            label = heading
        lines.append(f"- [{label}]({filename})")
    if bibliography_path:
        lines.append(f"- [Bibliography]({bibliography_path})")
    return "\n".join(lines) + "\n"


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
    # Mirror thesis-auditor's own directory convention (thesis-auditor.md:98:
    # "If $ARGUMENTS is a directory path: look for src/main.tex inside it")
    # so a pdf2md output directory can be handed to thesis-auditor the same
    # way a real UQAC thesis project directory is: the project root, with
    # main.{tex,md} and every chapter file as siblings inside its own src/.
    out_dir = Path(args.output_dir) / "src"
    out_dir.mkdir(parents=True, exist_ok=True)

    split, removed_count = process_document(source.read_text(encoding="utf-8"))
    (out_dir / "frontmatter.md").write_text(split.frontmatter, encoding="utf-8")

    filenames = chapter_filenames(sorted(split.chapters.keys()))
    chapter_paths: dict[int, tuple[str, str]] = {}
    for number, (title, body) in split.chapters.items():
        filename = filenames[number]
        (out_dir / filename).write_text(body, encoding="utf-8")
        chapter_paths[number] = (filename, title)

    bibliography_path = None
    if split.bibliography is not None:
        bibliography_path = out_dir / "bibliography.md"
        bibliography_path.write_text(split.bibliography, encoding="utf-8")

    main_md = render_main_md(
        frontmatter_path="frontmatter.md",
        chapter_paths=chapter_paths,
        bibliography_path="bibliography.md" if bibliography_path else None,
    )
    main_path = out_dir / "main.md"
    main_path.write_text(main_md, encoding="utf-8")

    report = {
        "ok": True,
        "splice_headings_removed": removed_count,
        "chapters_written": {number: filename for number, (filename, _title) in chapter_paths.items()},
        "bibliography_found": split.bibliography is not None,
        "bibliography_path": str(bibliography_path) if bibliography_path else None,
        "frontmatter_path": str(out_dir / "frontmatter.md"),
        "main_path": str(main_path),
    }
    print(json.dumps(report) if args.json else report)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
