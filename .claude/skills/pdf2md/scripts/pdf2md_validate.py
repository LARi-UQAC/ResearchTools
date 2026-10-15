"""
pdf2md_validate - Stage 7 of the pdf2md pipeline: a structural sanity pass
comparing the PDF's own content against pdf2md's final output, chapter by
chapter, to catch gross content loss or corruption (a collapsed chapter, a
bibliography that swallowed a chapter) that earlier stages were built to
fix but could regress silently again.

Ground truth comes from a SECOND, independent reader (PyMuPDF/pymupdf4llm,
via extract-statistic's own read_pdf -- reused by direct import, R18,
never re-implemented here) rather than mineru's own VLM, so a mineru-
specific mistake has a chance of being caught instead of confirmed by
asking the same tool twice.

Measured limits of that second reader, against the real 162-page UQAC
thesis this skill was built against (R14 -- checked, not guessed):

- Docling (the only backend with a formula-enrichment model) is not
  installed here; read_pdf() falls back to pymupdf4llm/PyMuPDF, confirmed
  by inspecting pymupdf4llm.helpers.pymupdf_rag.to_markdown's real
  parameter list: no LLM/model/API parameter exists anywhere in it, it is
  purely rule-based (font-size heading inference, PyMuPDF table detection,
  Tesseract OCR for scanned pages). count_equations_rough() is therefore a
  ROUGH heuristic (delimited math spans + math-symbol-dense lines), never
  a real detector, and is labelled as such in every report.
- This PDF's own embedded font garbles accented French characters under
  BOTH pymupdf4llm and raw PyMuPDF page.get_text() identically (confirmed:
  "DISTRIBU?E" for "DISTRIBUEE" with the accented E replaced by a
  placeholder) -- a defect of the PDF's font encoding, not of either
  library; mineru's VLM reads glyph shapes and is unaffected, which is why
  its own output is clean. Word COUNTS stay roughly valid (word
  boundaries survive); heading TEXT comparisons would not, which is why
  chapter/section/subsection matching here keys on NUMBERING ("CHAPITRE
  N", "N.M", "N.M.K"), never on title text.
- Heading LEVEL (#/##/###) is not comparable between the two readers:
  pymupdf4llm infers depth from font size and flattened most of this real
  thesis's headings to the same level, while mineru's output nests
  correctly (## chapter, ### section, #### subsection). Section/
  subsection counting therefore matches the NUMBERING PATTERN in the
  heading's own text (N.M vs N.M.K), independent of heading depth, which
  works identically on both sides.
- No figure extraction exists in extract-statistic's read_pdf, and mineru
  itself never extracts images either (include_images defaults False and
  this pipeline never enables it) -- figures are counted by caption-line
  text ("Figure N"/"Fig. N"), comparable on both sides precisely because
  neither side has a real image to count.

Content checks beyond the counts, each its own module and flag:

- --fidelity (pdf2md_fidelity): compares CONTENT chapter by chapter and
  reports lost or misplaced headings, missing, extra, repeated or
  reordered paragraphs, embedded base64 images and HTML residue. The counts
  above are NOT conversion errors on a math-heavy chapter: measured
  2026-10-11, the word and citation-marker gaps of two chapters were
  produced by how each reader renders formulas (LaTeX code counted as
  words, matrix indices such as [11] counted as citations), not by lost
  content. This check is the one that finds real conversion errors.
- --vlm-check (pdf2md_vlmcheck, needs --vlm-check-model TAG): a LOCAL,
  OPERATOR-NAMED vision model reads the pages richest in math and checks
  their formulas against the markdown, with its answer forced into a schema
  and validated. It replaces an earlier --vlm-check that asked the model to
  count items on one page and compared the answer to nothing.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_HERE = os.path.dirname(os.path.abspath(__file__))
_EXTRACT_TEXT_DIR = os.path.normpath(os.path.join(_HERE, "..", "..", "extract-statistic", "scripts"))
sys.path.insert(0, _EXTRACT_TEXT_DIR)

try:
    import extract_text
except ImportError as exc:  # pragma: no cover - the sibling skill must be present
    print(f"ERROR: cannot import extract_text from {_EXTRACT_TEXT_DIR} ({exc})", file=sys.stderr)
    sys.exit(1)

# This module's own siblings: `python -I` does not put the script's directory
# on sys.path, so it is added explicitly.
sys.path.insert(0, _HERE)
import pdf2md_fidelity  # noqa: E402  (after the sys.path edit above, by design)
import pdf2md_postprocess  # noqa: E402
import pdf2md_vlmcheck  # noqa: E402


_CONFIG_PATH = Path(__file__).with_name("pdf2md-validate.json")
_CONFIG_KEYS = (
    "word_count_mismatch_threshold_pct",
    "math_symbol_chars",
    "word_min_letters",
)

_CHAPTER_NUMBER_RE = re.compile(r"chapitre\s+(\d+)\b", re.IGNORECASE)
# NOT case-insensitive, deliberately: measured live against the real
# thesis, a genuine chapter heading or running-header repeat always
# renders "CHAPITRE" in full caps ("## **CHAPITRE 1**", "CHAPITRE 1.
# INTRODUCTION"), while an in-body cross-reference sentence uses ordinary
# title case ("Chapitre 2 a montre que..."). A case-insensitive match
# treated that cross-reference sentence, which happened to start a line,
# as chapter 2's own start -- truncating chapter 1's real body at that
# point (787 words measured instead of the true ~4800+).
_CHAPTER_START_RE = re.compile(r"^\**\s*#{0,6}\s*\**\s*CHAPITRE\s+(\d+)\b")
# Matches a BARE bibliography heading line ("References", "Bibliographie",
# "Liste des references") and nothing else, anchored at both ends so it
# never matches a sentence that merely CONTAINS one of these words. Measured
# live against the real thesis: the heading is "LISTE DES REFERENCES", which
# pdf2md_postprocess's own _BIBLIOGRAPHY_HEADING_RE (anchored on the word
# alone) would also miss -- that module recovers via its numbered-reference
# density fallback instead, which this simpler line-scan splitter does not
# have, so the heading match is widened here to cover the real case directly.
_BIBLIOGRAPHY_LINE_RE = re.compile(r"^\**\s*#{0,6}\s*\**\s*(liste des\s+)?(r[ée]f[ée]rences|bibliographie)\**\s*$", re.IGNORECASE)
_HEADING_PREFIX_RE = re.compile(r"^#{1,6}\s+")
_LEADING_NUMBER_RE = re.compile(r"^\**\s*(\d+(?:\.\d+)+)\b")

METRICS = ("words", "sections", "subsections", "tables", "figures", "citation_markers", "numbered_equations")
METRIC_LABELS = {
    "tables": "tables (captions)",
    "figures": "figures (captions)",
    "citation_markers": "citations in prose",
    "numbered_equations": "numbered equations (expected from numbering)",
}


def load_config(path: Path = _CONFIG_PATH) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read this module's thresholds from pdf2md-validate.json (R0: no
        hardcoded numerical value), each key carrying a {"value",
        "provenance"} pair (R4).

    Inputs:
        path (Path): where the config lives; overridable for tests.

    Outputs:
        dict: key -> value, for every key in _CONFIG_KEYS.

    Raises:
        FileNotFoundError: the config file is absent.
        KeyError: a required key is missing (R3: an explicit error naming
            the key, never a silent default).
    --------------------------------------------------------------------------
    """
    if not path.exists():
        raise FileNotFoundError(f"pdf2md validate config not found at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in _CONFIG_KEYS if key not in data]
    if missing:
        raise KeyError(f"{path} is missing required config key(s): {missing}")
    return {key: data[key]["value"] for key in _CONFIG_KEYS}


# --------------------------------------------------------------------------- #
# Pure counting functions. Every one operates on plain text so the SAME
# function runs on both the PDF-extracted side and pdf2md's own output side.
# --------------------------------------------------------------------------- #


def count_words(text: str, *, min_letters: int) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Count the words of a chapter, with formulas excluded: a formula is
        read, not counted, and the two readers render it very differently
        (mineru as LaTeX source between dollar signs, the PDF reader as
        italic fragments), so counting it made a math-heavy chapter look
        thousands of words longer in the output than in the PDF (measured
        2026-10-11: +6171 and +8449 words on two chapters).

    Details:
        The output's $...$ and $$...$$ spans and its base64 images are
        removed first. A remaining whitespace token counts when it holds a
        run of at least min_letters letters, which drops numbers, symbols
        and one-letter variable names such as the PDF reader's italic
        fragments. A token with a garbled accent still counts: the
        replacement character does not break the letter run around it.

    Inputs:
        text (str): the chapter text, either side.
        min_letters (int): the shortest letter run that makes a word, from
            pdf2md-validate.json.

    Outputs:
        int: the number of words.
    --------------------------------------------------------------------------
    """
    run = re.compile(r"[^\W\d_]{%d,}" % min_letters)
    return sum(1 for token in pdf2md_fidelity.strip_math_and_images(text).split() if run.search(token))


def count_tables(text: str, fidelity_config: dict) -> int:
    """Number of distinct tables, by caption label ("Table 3.2"), on either
    side. Markdown separator rows were counted before 2026-10-11 and missed
    mineru's HTML tables while counting the 8 chart-derived tables it adds
    from plots, so two chapters read 4 against 10 with 4 real tables on each
    side."""
    return len(pdf2md_fidelity.caption_labels(text, fidelity_config)["table"])


def count_figures(text: str, fidelity_config: dict) -> int:
    """Number of distinct figures, by caption label ("Figure 3.8"). In-text
    sentences about a figure are not captions (pdf2md_fidelity.caption_labels
    explains the rule), which is what made the earlier line count read 11
    against 10 on one chapter."""
    return len(pdf2md_fidelity.caption_labels(text, fidelity_config)["figure"])


def count_citation_markers(text: str, fidelity_config: dict) -> int:
    """Number of citations in the prose, one per reference number per
    occurrence ("[12, 13]" counts 2). The matrix indices the PDF reader prints
    as "[0]" and "[1]" are not citations and are not counted
    (pdf2md_fidelity.citation_numbers)."""
    return len(pdf2md_fidelity.citation_numbers(text, fidelity_config))


def _heading_number_depth(line: str) -> int | None:
    """Returns the number of dot-separated numeric groups in a heading
    line's leading number (2 for "2.1", 3 for "2.1.2"), or None if the
    line is not a heading, or is a heading with no leading number at all
    (an unnumbered thesis element like "Abstract" or "Avant-propos",
    which is neither a section nor a subsection for this count)."""
    prefix_match = _HEADING_PREFIX_RE.match(line)
    if not prefix_match:
        return None
    rest = line[prefix_match.end():]
    number_match = _LEADING_NUMBER_RE.match(rest)
    if not number_match:
        return None
    return number_match.group(1).count(".") + 1


def count_sections(text: str) -> int:
    """Counts heading lines numbered like "N.M" (e.g. "2.1 Article
    publie") -- matched on the NUMBER pattern in the heading's own text,
    not on heading depth (#/##/###), since depth is not comparable between
    mineru's layout-aware nesting and pymupdf4llm's font-size-based
    flattening (measured: both "3.1" and "3.1.1" rendered at the identical
    "##" depth in the real PDF extraction)."""
    return sum(1 for line in text.splitlines() if _heading_number_depth(line) == 2)


def count_subsections(text: str) -> int:
    """Counts heading lines numbered like "N.M.K" (e.g. "2.1.2 Existing
    surveys"). See count_sections for why depth is not used."""
    return sum(1 for line in text.splitlines() if _heading_number_depth(line) == 3)


def compute_metrics(text: str, *, side: str, word_min_letters: int, fidelity_config: dict) -> dict[str, int]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Measure one chapter on one side, on the same footing: the PDF side is
        cleaned first of running headers, page numbers and figure text, which
        the markdown rightly does not carry.

    Details:
        numbered_equations is not read from the text: the PDF reader cannot
        read equation numbers. compare_chapters fills it from the output's
        own numbering (expected = highest number, found = distinct numbers).

    Inputs:
        text (str): the chapter text.
        side (str): "pdf" or "output".
        word_min_letters (int): see count_words.
        fidelity_config (dict): thresholds from pdf2md_fidelity.load_fidelity_config.

    Outputs:
        dict[str, int]: metric name -> count, keys matching METRICS.
    --------------------------------------------------------------------------
    """
    if side == "pdf":
        text = pdf2md_fidelity.clean_pdf_text(text, fidelity_config)
    return {
        "words": count_words(text, min_letters=word_min_letters),
        "sections": count_sections(text),
        "subsections": count_subsections(text),
        "tables": count_tables(text, fidelity_config),
        "figures": count_figures(text, fidelity_config),
        "citation_markers": count_citation_markers(text, fidelity_config),
        "numbered_equations": 0,
    }


# --------------------------------------------------------------------------- #
# Chapter extraction: the SAME tested splitting logic pdf2md_postprocess
# already uses, applied to BOTH the PDF-extracted text and pdf2md's own
# output, so a chapter number means the same thing on both sides.
# --------------------------------------------------------------------------- #


def split_pdf_text_into_chapters(text: str) -> dict[int, str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Split the PDF-extracted text into chapters by scanning every LINE
        for "CHAPITRE N", independent of markdown heading syntax.

        This does NOT reuse pdf2md_postprocess's find_headings: measured
        live against the real 162-page thesis, pymupdf4llm never marks a
        "CHAPITRE N" line as a "#"-prefixed heading at all (it appears as
        plain prose in its output -- a font-size/layout artifact of this
        specific extractor, not a general markdown property), so a
        heading-syntax-based splitter finds zero chapters on this side.
        mineru's own VLM-based structure detection, by contrast, DOES mark
        it as a real heading, which is why pdf2md_postprocess's own
        splitter works correctly on mineru's output.

        A chapter's first-occurring "CHAPITRE N" line is taken as its
        start; mineru's running-header splice defect means the SAME text
        repeats on every later page of that chapter, but only the first
        occurrence of a given number is used as a boundary, so the repeats
        land as harmless noise inside the chapter's own body rather than
        as false boundaries.

        The LAST chapter's end is truncated at the first bibliography
        heading line found AFTER ITS OWN START (see _BIBLIOGRAPHY_LINE_RE),
        rather than running to end of document -- measured live: without
        this, a 190-reference bibliography with no "CHAPITRE N+1" to end
        it was swallowed whole into the last chapter's body, inflating its
        word and citation-marker counts far past pdf2md's own output
        (which correctly holds the bibliography out separately). A
        code-review finding caught a second-order version of the same
        bug: searching the WHOLE document for the bibliography line (via
        a single next(...) over every line) locks onto the FIRST match
        anywhere, so a table-of-contents entry or an early running header
        matching the same pattern, appearing BEFORE the last chapter even
        starts, silently disables the cutoff for the real bibliography
        further down -- the search is now scoped to lines AFTER the last
        chapter's own start line only.

    Inputs:
        text (str): the PDF-extracted text (pymupdf4llm/PyMuPDF markdown
            or plain text).

    Outputs:
        dict[int, str]: chapter number -> body text (the chapter's own
            "CHAPITRE N" line through the line before the next chapter's
            first occurrence, the bibliography's first occurrence for the
            last chapter, or end of document if neither is found).
    --------------------------------------------------------------------------
    """
    lines = text.splitlines()
    first_occurrence: dict[int, int] = {}
    for index, line in enumerate(lines):
        match = _CHAPTER_START_RE.match(line.strip())
        if match:
            number = int(match.group(1))
            if number not in first_occurrence:
                first_occurrence[number] = index

    ordered = sorted(first_occurrence.items(), key=lambda item: item[1])
    chapters: dict[int, str] = {}
    for position, (number, start) in enumerate(ordered):
        is_last = position + 1 >= len(ordered)
        end = len(lines) if is_last else ordered[position + 1][1]
        if is_last:
            bibliography_offset = next(
                (i for i, line in enumerate(lines[start:end]) if _BIBLIOGRAPHY_LINE_RE.match(line.strip())), None
            )
            if bibliography_offset is not None:
                end = start + bibliography_offset
        chapters[number] = "\n".join(lines[start:end])
    return chapters


def extract_pdf_chapters(pdf_path: str, *, reader: Callable[[str], tuple[str, list]] | None = None) -> dict[int, tuple[str, str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the PDF via extract-statistic's own read_pdf (R18: reused,
        not re-implemented) and split it into chapters by chapter-number
        text match (split_pdf_text_into_chapters), so chapter N means the
        same thing here as it does in pdf2md's final output, without
        depending on markdown heading syntax this extractor does not
        reliably produce for chapter titles.

    Inputs:
        pdf_path (str): path to the PDF.
        reader (callable | None): injected for tests; defaults to
            extract_text.read_pdf (R20/R21 -- no real PDF parse in the
            offline suite).

    Outputs:
        dict[int, tuple[str, str]]: chapter number -> (empty title placeholder, body text).
            The title is always "" here (unlike pdf2md_postprocess's own
            SplitResult) since this splitter works on raw text lines, not
            parsed Heading objects; callers that only need body text
            (compare_chapters) are unaffected.
    --------------------------------------------------------------------------
    """
    reader = reader or extract_text.read_pdf
    text, _tables = reader(pdf_path)
    return {number: ("", body) for number, body in split_pdf_text_into_chapters(text).items()}


def load_output_chapters(output_dir: Path) -> dict[int, tuple[str, str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read pdf2md's own content/*.md files back, recovering each
        chapter's TRUE number from its own first "CHAPITRE N" heading
        line (never from the Introduction.md/Conclusion.md filename,
        which does not encode it) so numbering lines up with the PDF
        side's own "CHAPITRE N" matches.

    Inputs:
        output_dir (Path): the pdf2md output directory (its own src/,
            holding content/*.md).

    Outputs:
        dict[int, tuple[str, str]]: chapter number -> (filename stem,
            body text). A content file with no recognizable chapter
            number (frontmatter.md, or a malformed file) is skipped.
    --------------------------------------------------------------------------
    """
    content_dir = Path(output_dir) / "content"
    result: dict[int, tuple[str, str]] = {}
    if not content_dir.exists():
        return result
    for path in sorted(content_dir.glob("*.md")):
        if path.name == "frontmatter.md":
            continue
        text = path.read_text(encoding="utf-8")
        first_line = text.splitlines()[0] if text.splitlines() else ""
        heading_match = _CHAPTER_NUMBER_RE.search(first_line)
        if heading_match:
            number = int(heading_match.group(1))
        else:
            filename_match = re.search(r"chapitre(\d+)", path.stem, re.IGNORECASE)
            if not filename_match:
                continue
            number = int(filename_match.group(1))
        result[number] = (path.stem, text)
    return result


def extract_pdf_single(pdf_path: str, *, reader: Callable[[str], tuple[str, list]] | None = None) -> dict[int, tuple[str, str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        The single-document layout's PDF side: the whole PDF text as ONE unit,
        numbered 1, cut before the LAST bibliography heading line (an earlier
        match is a table-of-contents entry or a running header).

    Inputs:
        pdf_path (str): path to the PDF.
        reader (callable | None): injected for tests; defaults to
            extract_text.read_pdf (R20/R21).

    Outputs:
        dict[int, tuple[str, str]]: {1: ("", body text)}.
    --------------------------------------------------------------------------
    """
    reader = reader or extract_text.read_pdf
    text, _tables = reader(pdf_path)
    # The same rule as the output side (pdf2md_postprocess.split_single_document), so both
    # sides hold the bibliography out at the same place.
    lines = text.splitlines()
    start = pdf2md_postprocess.single_bibliography_start(lines)
    end = start if start is not None else len(lines)
    return {1: ("", "\n".join(lines[:end]))}


def load_output_single(output_dir: Path) -> dict[int, tuple[str, str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        The single-document layout's output side: main.md as ONE unit,
        numbered 1, with its bibliography held out the way the PDF side does.

    Inputs:
        output_dir (Path): the pdf2md output directory holding main.md.

    Outputs:
        dict[int, tuple[str, str]]: {1: ("main", body text)}.

    Raises:
        FileNotFoundError: main.md is absent (R3: named, never an empty result).
    --------------------------------------------------------------------------
    """
    main_path = Path(output_dir) / "main.md"
    if not main_path.exists():
        raise FileNotFoundError(f"single layout recorded but {main_path} is missing")
    text, bibliography = pdf2md_postprocess.split_single_document(main_path.read_text(encoding="utf-8").splitlines())
    body = text[: len(text) - len(bibliography)] if bibliography else text
    return {1: ("main", body)}


@dataclass
class ChapterComparison:
    """
    --------------------------------------------------------------------------
    Purpose:
        One chapter's PDF-side vs output-side metrics.

    Inputs:
        None.

    Outputs:
        chapter (int): chapter number.
        in_pdf (bool): a chapter with this number was found on the PDF side.
        in_output (bool): a chapter with this number was found in the output.
        pdf_metrics (dict[str, int]): from compute_metrics, or all zeros
            if in_pdf is False.
        output_metrics (dict[str, int]): from compute_metrics, or all
            zeros if in_output is False.
    --------------------------------------------------------------------------
    """

    chapter: int
    in_pdf: bool
    in_output: bool
    pdf_metrics: dict[str, int]
    output_metrics: dict[str, int]


def compare_chapters(
    pdf_chapters: dict[int, tuple[str, str]],
    output_chapters: dict[int, tuple[str, str]],
    *,
    word_min_letters: int,
    fidelity_config: dict,
) -> list[ChapterComparison]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build one ChapterComparison per chapter number present on EITHER
        side, so a chapter missing from one side is reported (as all
        zeros on that side, with in_pdf/in_output stating the fact) rather
        than silently skipped.

    Details:
        numbered_equations is the one measure the PDF reader cannot give: its
        PDF-side value is the number of equations the chapter should hold,
        read from the output's own numbering (the highest equation number),
        and its output-side value is how many distinct numbers are present.
        A gap is therefore an equation lost, and a chapter with no numbered
        equation reads 0 / 0.

    Inputs:
        pdf_chapters, output_chapters: as returned by extract_pdf_chapters
            / load_output_chapters.
        word_min_letters: see count_words.
        fidelity_config (dict): thresholds from pdf2md_fidelity.load_fidelity_config.

    Outputs:
        list[ChapterComparison]: sorted by chapter number.
    --------------------------------------------------------------------------
    """
    zero_metrics = {metric: 0 for metric in METRICS}
    rows = []
    for number in sorted(set(pdf_chapters) | set(output_chapters)):
        pdf_text = pdf_chapters[number][1] if number in pdf_chapters else ""
        out_text = output_chapters[number][1] if number in output_chapters else ""
        pdf_metrics = (
            compute_metrics(pdf_text, side="pdf", word_min_letters=word_min_letters, fidelity_config=fidelity_config)
            if number in pdf_chapters
            else dict(zero_metrics)
        )
        out_metrics = (
            compute_metrics(out_text, side="output", word_min_letters=word_min_letters, fidelity_config=fidelity_config)
            if number in output_chapters
            else dict(zero_metrics)
        )
        if number in output_chapters:
            expected, found = pdf2md_fidelity.numbered_equation_counts(out_text)
            if number in pdf_chapters:
                pdf_metrics["numbered_equations"] = expected
            out_metrics["numbered_equations"] = found
        rows.append(
            ChapterComparison(
                chapter=number,
                in_pdf=number in pdf_chapters,
                in_output=number in output_chapters,
                pdf_metrics=pdf_metrics,
                output_metrics=out_metrics,
            )
        )
    return rows


def flag_mismatched_chapters(rows: list[ChapterComparison], *, word_tolerance_pct: float) -> list[int]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Identify chapters whose word count differs most between the two readers: present on
        only one side, or whose word counts differ by more than the
        configured tolerance.

    Inputs:
        rows (list[ChapterComparison]): from compare_chapters.
        word_tolerance_pct (float): from pdf2md-validate.json.

    Outputs:
        list[int]: flagged chapter numbers, in chapter order.
    --------------------------------------------------------------------------
    """
    flagged = []
    for row in rows:
        if not row.in_pdf or not row.in_output:
            flagged.append(row.chapter)
            continue
        pdf_words = row.pdf_metrics["words"]
        if pdf_words == 0:
            continue
        pct_diff = abs(row.output_metrics["words"] - pdf_words) / pdf_words * 100
        if pct_diff > word_tolerance_pct:
            flagged.append(row.chapter)
    return flagged


def error_pct(pdf_value: int, output_value: int) -> float:
    """
    --------------------------------------------------------------------------
    Purpose:
        The relative error of one count against the PDF reading, in percent.

    Details:
        |output - pdf| / pdf * 100. When the PDF reading holds none of the
        item, the error is 0 if the output holds none either and 100 if it
        holds any, since a ratio to zero is undefined and an item the PDF
        does not have is a full miss.

    Inputs:
        pdf_value (int): the count read from the PDF.
        output_value (int): the count in pdf2md's output.

    Outputs:
        float: the error in percent, never negative.
    --------------------------------------------------------------------------
    """
    if pdf_value == 0:
        return 0.0 if output_value == 0 else 100.0
    return abs(output_value - pdf_value) / pdf_value * 100


def build_report_table(rows: list[ChapterComparison], file_names: dict[int, str]) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Arrange the comparison as measures x converted files, with the
        errors in percent that the report's last row and last column carry.

    Details:
        - cell error: error_pct of that measure in that file.
        - last row, per file: the mean of the file's cell errors over all
          measures, each measure weighing the same.
        - last column, per measure: the sum over files of |output - pdf|
          divided by the sum over files of pdf (same zero rule as
          error_pct), so an excess in one file never cancels a deficit in
          another.
        - corner: the mean of the per-measure global errors.

    Inputs:
        rows (list[ChapterComparison]): from compare_chapters.
        file_names (dict[int, str]): chapter number -> converted file name,
            the column headers.

    Outputs:
        dict: {"files": [names], "measures": {metric: {"cells": {file:
            {"pdf", "output", "error_pct"}}, "global_error_pct"}],
            "file_error_pct": {file: pct}, "overall_error_pct": pct,
            "notes": [str]}.
    --------------------------------------------------------------------------
    """
    names = [file_names.get(row.chapter, f"chapter {row.chapter}") for row in rows]
    table: dict = {"files": names, "measures": {}, "file_error_pct": {}, "overall_error_pct": 0.0, "notes": []}
    for row in rows:
        if not row.in_pdf:
            table["notes"].append(f"Chapter {row.chapter}: not found on the PDF side.")
        if not row.in_output:
            table["notes"].append(f"Chapter {row.chapter}: not found in pdf2md's output.")
    for metric in METRICS:
        cells = {}
        for name, row in zip(names, rows):
            pdf_v, out_v = row.pdf_metrics[metric], row.output_metrics[metric]
            cells[name] = {"pdf": pdf_v, "output": out_v, "error_pct": error_pct(pdf_v, out_v)}
        total_pdf = sum(cell["pdf"] for cell in cells.values())
        total_absolute_gap = sum(abs(cell["output"] - cell["pdf"]) for cell in cells.values())
        if total_pdf == 0:
            global_error = 0.0 if total_absolute_gap == 0 else 100.0
        else:
            global_error = total_absolute_gap / total_pdf * 100
        table["measures"][metric] = {"cells": cells, "global_error_pct": global_error}
    for name in names:
        errors = [table["measures"][metric]["cells"][name]["error_pct"] for metric in METRICS]
        table["file_error_pct"][name] = sum(errors) / len(errors) if errors else 0.0
    globals_ = [table["measures"][metric]["global_error_pct"] for metric in METRICS]
    table["overall_error_pct"] = sum(globals_) / len(globals_) if globals_ else 0.0
    return table


def render_report_md(rows: list[ChapterComparison], file_names: dict[int, str] | None = None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Render the comparison as one markdown table: a row per measure, a
        column per converted file, each cell "PDF / output", then a last
        column with each measure's global error in percent and a last row
        with each file's error in percent.

    Inputs:
        rows (list[ChapterComparison]): from compare_chapters.
        file_names (dict[int, str] | None): chapter number -> file name for
            the column headers; a chapter with no entry is headed "chapter N".

    Outputs:
        str: the table, the definitions of its percentages, and a note on
            any chapter missing from one side.
    --------------------------------------------------------------------------
    """
    table = build_report_table(rows, file_names or {})
    files = table["files"]
    lines = [
        "| Measure | " + " | ".join(files) + " | Global error (%) |",
        "|---|" + "---|" * (len(files) + 1),
    ]
    for metric in METRICS:
        data = table["measures"][metric]
        cells = " | ".join(f"{data['cells'][name]['pdf']} / {data['cells'][name]['output']}" for name in files)
        lines.append(f"| {METRIC_LABELS.get(metric, metric)} | {cells} | {data['global_error_pct']:.1f} |")
    per_file = " | ".join(f"{table['file_error_pct'][name]:.1f}" for name in files)
    lines.append(f"| Error (%) | {per_file} | {table['overall_error_pct']:.1f} |")
    report = "\n".join(lines) + "\n"
    report += (
        "\nEach cell reads PDF / output. Error of one cell = |output - PDF| / PDF x 100 "
        "(0 when both are zero, 100 when only the PDF reading is zero). "
        "Last row: mean of a file's errors over the measures. "
        "Last column: sum of |output - PDF| over the files divided by the sum of PDF. "
        "Bottom right: mean of the last column.\n"
    )
    if table["notes"]:
        report += "\n" + "\n".join(f"- {note}" for note in table["notes"]) + "\n"
    return report


# --------------------------------------------------------------------------- #
# Page ranges (used to hand pages to the formula check of pdf2md_vlmcheck) and
# the command line.
# --------------------------------------------------------------------------- #


def find_chapter_page_range(
    pdf_path: str, chapter_number: int, *, page_texts: list[str] | None = None, max_pages: int | None = None
) -> tuple[int, int] | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find the (start_page, end_page) 0-indexed page range a chapter
        occupies, by scanning each page's own LINES for a genuine
        "CHAPITRE N" start (the same _CHAPTER_START_RE rule
        split_pdf_text_into_chapters uses, never the looser
        case-insensitive-anywhere-in-line _CHAPTER_NUMBER_RE -- a code
        review finding, confirmed live: that looser match turned a
        cross-reference sentence or a table-of-contents page into a false
        chapter boundary, and a bibliography heading with no later
        "CHAPITRE N+1" to stop it let a flagged chapter's range run to the
        bibliography and appendices, rendering 32 pages into one oversized
        request that then timed out).

    Inputs:
        pdf_path (str): path to the PDF (opened only if page_texts is None).
        chapter_number (int): the chapter to locate.
        page_texts (list[str] | None): injected per-page text for tests
            (R20/R21 -- no real PDF open in the offline suite); when None,
            read via PyMuPDF (fitz), closed via `with` so no handle leaks.
        max_pages (int | None): cap the range to at most this many pages
            from its start (None means uncapped);
            None means uncapped, used by direct unit tests of this
            function's boundary logic.

    Outputs:
        (int, int) | None: 0-indexed (start_page, end_page_inclusive), or
            None if the chapter's own heading was not found on any page.

    Raises:
        ValueError: max_pages is given and is less than 1 (a 0 or
            negative cap silently produced an empty page range before
            this check, a re-review finding).
    --------------------------------------------------------------------------
    """
    if page_texts is None:
        import fitz

        with fitz.open(pdf_path) as doc:
            page_texts = [page.get_text() for page in doc]

    first_page_for_number: dict[int, int] = {}
    for page_index, text in enumerate(page_texts):
        for line in text.splitlines():
            chapter_match = _CHAPTER_START_RE.match(line.strip())
            if chapter_match:
                number = int(chapter_match.group(1))
                if number not in first_page_for_number:
                    first_page_for_number[number] = page_index

    if chapter_number not in first_page_for_number:
        return None
    start = first_page_for_number[chapter_number]
    later_starts = [page for number, page in first_page_for_number.items() if number > chapter_number]
    end = min(later_starts) - 1 if later_starts else len(page_texts) - 1

    # Bibliography cutoff scoped to AFTER this chapter's own start -- a
    # SECOND /code-review finding on a re-review: the first fix applied
    # this scoping in split_pdf_text_into_chapters but left the original
    # whole-document-first-match bug here, in the page-level function
    # --vlm-check actually uses. A bare bibliography-heading-shaped line
    # anywhere EARLIER in the document (a front-matter heading, in the
    # general case) must never be allowed to block finding the real one
    # inside this chapter's own candidate range.
    if max_pages is not None:
        if max_pages < 1:
            raise ValueError(f"max_pages must be >= 1, got {max_pages}")
        end = min(end, start + max_pages - 1)
    for page_index in range(start, end + 1):
        if any(_BIBLIOGRAPHY_LINE_RE.match(line.strip()) for line in page_texts[page_index].splitlines()):
            end = page_index - 1
            break
    return (start, end)


def _read_page_texts(pdf_path: str) -> list[str]:
    """Raw text of every PDF page, read with PyMuPDF (closed via `with`)."""
    import fitz

    with fitz.open(pdf_path) as document:
        return [page.get_text() for page in document]


def _run_vlm_check(args, output_chapters: dict, config: dict) -> dict:
    """Run pdf2md_vlmcheck's formula check on every output chapter, locating
    each chapter's pages in the PDF with find_chapter_page_range."""
    page_texts = _read_page_texts(args.pdf_path)
    ranges: dict[int, tuple[int, int]] = {}
    for chapter in output_chapters:
        page_range = find_chapter_page_range(args.pdf_path, chapter, page_texts=page_texts)
        if page_range is not None:
            ranges[chapter] = page_range
    return pdf2md_vlmcheck.run_vlm_fidelity(
        args.pdf_path,
        output_chapters,
        ranges,
        page_texts,
        model_tag=args.vlm_check_model,
        config=pdf2md_vlmcheck.load_vlmcheck_config(),
        math_symbol_chars=config["math_symbol_chars"],
        fidelity_config=pdf2md_fidelity.load_fidelity_config(),
        scratch_dir=Path(args.output_dir) / "validate-scratch",
    )


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_path")
    parser.add_argument("-o", "--output-dir", required=True)
    parser.add_argument("--fidelity", action="store_true", help="content fidelity check (pdf2md_fidelity): lost or misplaced headings, missing, extra, repeated or reordered paragraphs, embedded images, HTML residue")
    parser.add_argument("--vlm-check", action="store_true", help="formula check (pdf2md_vlmcheck): a local vision model reads the pages richest in math and verifies their formulas against the markdown")
    parser.add_argument("--vlm-check-model", default=None, help="REQUIRED with --vlm-check; the operator's own Ollama tag (R2 -- never a default)")
    parser.add_argument("--strict", action="store_true", help="exit 1 when --fidelity finds an error-severity issue, or --vlm-check finds a formula issue or a page it could not check")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.vlm_check and not args.vlm_check_model:
        print("[VALIDATE] refusing: --vlm-check requires --vlm-check-model TAG (never a default, R2).", file=sys.stderr)
        return 2

    try:
        layout = pdf2md_postprocess.read_layout(Path(args.output_dir))
    except ValueError as exc:
        print(f"[VALIDATE] refusing: {exc}", file=sys.stderr)
        return 2
    if layout == "single" and args.vlm_check:
        # The formula check locates pages by "CHAPITRE N", which a single document does not have.
        print("[VALIDATE] refusing: --vlm-check needs the thesis layout (it finds pages by chapter heading).", file=sys.stderr)
        return 2

    config = load_config()
    fidelity_config = pdf2md_fidelity.load_fidelity_config()
    if layout == "single":
        pdf_chapters = extract_pdf_single(args.pdf_path)
        try:
            output_chapters = load_output_single(Path(args.output_dir))
        except FileNotFoundError as exc:
            print(f"[VALIDATE] refusing: {exc}", file=sys.stderr)
            return 2
    else:
        pdf_chapters = extract_pdf_chapters(args.pdf_path)
        output_chapters = load_output_chapters(Path(args.output_dir))
    rows = compare_chapters(
        pdf_chapters,
        output_chapters,
        word_min_letters=config["word_min_letters"],
        fidelity_config=fidelity_config,
    )
    flagged = flag_mismatched_chapters(rows, word_tolerance_pct=config["word_count_mismatch_threshold_pct"])
    file_names = {number: f"{stem}.md" for number, (stem, _text) in output_chapters.items()}
    report = render_report_md(rows, file_names)
    table = build_report_table(rows, file_names)

    fidelity = None
    if args.fidelity:
        fidelity = pdf2md_fidelity.check_chapters(pdf_chapters, output_chapters, fidelity_config)

    # The formula check runs last: it is the slow part, and a failure there
    # must not lose the report already computed above.
    vlm = None
    if args.vlm_check:
        vlm = _run_vlm_check(args, output_chapters, config)

    result = {"ok": True, "flagged_chapters": flagged, "report_md": report, "table": table, "fidelity": fidelity, "vlm_check": vlm}
    if args.json:
        print(json.dumps(result))
    else:
        print(report)
        if flagged:
            print(f"Flagged for closer review: chapters {flagged}")
        if fidelity is not None:
            print(pdf2md_fidelity.render_fidelity_md(fidelity))
        if vlm is not None:
            print(pdf2md_vlmcheck.render_vlm_md(vlm))
    if args.strict:
        if fidelity is not None and fidelity["error_count"]:
            return 1
        if vlm is not None and (vlm["issue_count"] or vlm["error_count"]):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
