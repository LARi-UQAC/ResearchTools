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

Optional second opinion (--vlm-check): renders a mismatched chapter's PDF
pages to images and asks a LOCAL, OPERATOR-NAMED vision-capable Ollama
model (--vlm-check-model TAG; never a default or a hardcoded tag, R2 --
this is a reader/verifier use with no adopted role in model_resolver's
writer/coder taxonomy, so the operator names their own model explicitly,
the same pattern --tier and --server-url already use elsewhere in this
skill) to read the rendered page directly, which is not subject to the
font-encoding or heading-level limits above since it reads glyph shapes,
not font codepoints.

UNVERIFIED LIVE as of this writing (R15): every HTTP/subprocess effect
below is behind an injected seam for offline testing (R20/R21), but no
real call against a running Ollama model has been made yet -- the
operator's local model was in use by another process when this was built.
Re-verify against a real page before trusting the second-opinion counts.
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


_CONFIG_PATH = Path(__file__).with_name("pdf2md-validate.json")
_CONFIG_KEYS = (
    "word_count_mismatch_threshold_pct",
    "math_density_min_symbols_per_line",
    "math_symbol_chars",
    "vlm_check_timeout_s",
    "vlm_check_dpi",
    "vlm_check_base_url",
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
_WORD_RE = re.compile(r"\S+")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_FIGURE_CAPTION_RE = re.compile(r"^\**\s*(figure|fig\.?)\s*\d+", re.IGNORECASE)
_CITATION_MARKER_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_HEADING_PREFIX_RE = re.compile(r"^#{1,6}\s+")
_LEADING_NUMBER_RE = re.compile(r"^\**\s*(\d+(?:\.\d+)+)\b")
_MATH_DELIM_RE = re.compile(r"\$\$.+?\$\$|\$[^$\n]{1,200}\$", re.DOTALL)

METRICS = ("words", "sections", "subsections", "tables", "figures", "citation_markers", "equations_rough")
METRIC_LABELS = {"equations_rough": "equations (rough estimate)"}


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


def count_words(text: str) -> int:
    """Whitespace-token count. Survives the PDF's own font-encoding garbling
    of accented characters, since a replaced glyph does not introduce a
    whitespace boundary where none existed."""
    return len(_WORD_RE.findall(text))


def count_tables(text: str) -> int:
    """Counts markdown table SEPARATOR rows ("|---|---|"), one per table,
    which both pymupdf4llm's and mineru's own markdown renderers emit
    immediately under a table's header row regardless of heading-level
    drift elsewhere in the document."""
    return sum(1 for line in text.splitlines() if _TABLE_SEPARATOR_RE.match(line))


def count_figures(text: str) -> int:
    """Counts figure-caption LINES ("Figure 3", "Fig. 3"), not embedded
    images -- neither side currently extracts real image files (mineru's
    include_images defaults False; extract-statistic's read_pdf extracts
    no images at all), so caption text is the only comparable signal."""
    return sum(1 for line in text.splitlines() if _FIGURE_CAPTION_RE.match(line.strip()))


def count_citation_markers(text: str) -> int:
    """Counts individual citation-number OCCURRENCES in running text
    ("[12, 13]" counts as 2), not unique keys -- uniqueness is already a
    document-wide property reported by pdf2md_refs.py's reference_count;
    this is a per-chapter signal that citations were not dropped or
    duplicated during conversion."""
    total = 0
    for match in _CITATION_MARKER_RE.finditer(text):
        total += len(re.findall(r"\d+", match.group(1)))
    return total


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


def count_equations_rough(text: str, *, min_symbols_per_line: int, math_symbol_chars: str) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        A ROUGH, explicitly labelled heuristic equation count: every
        $$...$$ or $...$ delimited span counts as one, and every
        remaining line (not already counted via a delimiter) whose
        math-symbol-character density clears min_symbols_per_line counts
        as one more. No formula-aware backend is installed (Docling is
        absent), so this is a correlated signal, not a real detector --
        state this in any report built from it, never present it as exact.

    Inputs:
        text (str): the chapter's plain/markdown text.
        min_symbols_per_line (int): threshold from pdf2md-validate.json.
        math_symbol_chars (str): the character set counted as math-like,
            from pdf2md-validate.json (R6: data, not a code literal).

    Outputs:
        int: the rough count.
    --------------------------------------------------------------------------
    """
    symbol_set = set(math_symbol_chars)
    count = len(_MATH_DELIM_RE.findall(text))
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or _MATH_DELIM_RE.search(stripped):
            continue
        symbol_count = sum(1 for ch in stripped if ch in symbol_set)
        if symbol_count >= min_symbols_per_line:
            count += 1
    return count


def compute_metrics(text: str, *, math_min_symbols: int, math_symbol_chars: str) -> dict[str, int]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run every counting function over one chapter's text.

    Inputs:
        text (str): the chapter's plain/markdown text.
        math_min_symbols (int): see count_equations_rough.
        math_symbol_chars (str): see count_equations_rough.

    Outputs:
        dict[str, int]: metric name -> count, keys matching METRICS.
    --------------------------------------------------------------------------
    """
    return {
        "words": count_words(text),
        "sections": count_sections(text),
        "subsections": count_subsections(text),
        "tables": count_tables(text),
        "figures": count_figures(text),
        "citation_markers": count_citation_markers(text),
        "equations_rough": count_equations_rough(text, min_symbols_per_line=math_min_symbols, math_symbol_chars=math_symbol_chars),
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
        heading line found after it, if any (see _BIBLIOGRAPHY_LINE_RE),
        rather than running to end of document -- measured live: without
        this, a 190-reference bibliography with no "CHAPITRE N+1" to end
        it was swallowed whole into the last chapter's body, inflating its
        word and citation-marker counts far past pdf2md's own output
        (which correctly holds the bibliography out separately).

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

    bibliography_start = next((index for index, line in enumerate(lines) if _BIBLIOGRAPHY_LINE_RE.match(line.strip())), None)

    ordered = sorted(first_occurrence.items(), key=lambda item: item[1])
    chapters: dict[int, str] = {}
    for position, (number, start) in enumerate(ordered):
        is_last = position + 1 >= len(ordered)
        end = len(lines) if is_last else ordered[position + 1][1]
        if is_last and bibliography_start is not None and start < bibliography_start < end:
            end = bibliography_start
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
    math_min_symbols: int,
    math_symbol_chars: str,
) -> list[ChapterComparison]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build one ChapterComparison per chapter number present on EITHER
        side, so a chapter missing from one side is reported (as all
        zeros on that side, with in_pdf/in_output stating the fact) rather
        than silently skipped.

    Inputs:
        pdf_chapters, output_chapters: as returned by extract_pdf_chapters
            / load_output_chapters.
        math_min_symbols, math_symbol_chars: see count_equations_rough.

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
            compute_metrics(pdf_text, math_min_symbols=math_min_symbols, math_symbol_chars=math_symbol_chars)
            if number in pdf_chapters
            else dict(zero_metrics)
        )
        out_metrics = (
            compute_metrics(out_text, math_min_symbols=math_min_symbols, math_symbol_chars=math_symbol_chars)
            if number in output_chapters
            else dict(zero_metrics)
        )
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
        Identify chapters worth a closer (--vlm-check) look: present on
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


def render_report_md(rows: list[ChapterComparison]) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Render the comparison as a markdown table, one row per
        (chapter, metric), with a diff column.

    Inputs:
        rows (list[ChapterComparison]): from compare_chapters.

    Outputs:
        str: the full report, including a note on any chapter missing
            from one side.
    --------------------------------------------------------------------------
    """
    lines = ["| Chapter | Metric | PDF | Output | Diff |", "|---|---|---|---|---|"]
    notes = []
    for row in rows:
        if not row.in_pdf:
            notes.append(f"- Chapter {row.chapter}: not found on the PDF side.")
        if not row.in_output:
            notes.append(f"- Chapter {row.chapter}: not found in pdf2md's output.")
        for metric in METRICS:
            pdf_v = row.pdf_metrics[metric]
            out_v = row.output_metrics[metric]
            label = METRIC_LABELS.get(metric, metric)
            lines.append(f"| {row.chapter} | {label} | {pdf_v} | {out_v} | {out_v - pdf_v:+d} |")
    report = "\n".join(lines) + "\n"
    if notes:
        report += "\n" + "\n".join(notes) + "\n"
    return report


# --------------------------------------------------------------------------- #
# Optional second opinion: a local vision-capable Ollama model reads the
# mismatched chapter's own rendered pages directly. UNVERIFIED LIVE (see
# module docstring) -- every effect below is behind an injected seam.
# --------------------------------------------------------------------------- #


def find_chapter_page_range(pdf_path: str, chapter_number: int, *, page_texts: list[str] | None = None) -> tuple[int, int] | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find the (start_page, end_page) 0-indexed page range a chapter
        occupies, by searching each page's own text for "CHAPITRE N" and
        "CHAPITRE N+1" (or end of document).

    Inputs:
        pdf_path (str): path to the PDF (opened only if page_texts is None).
        chapter_number (int): the chapter to locate.
        page_texts (list[str] | None): injected per-page text for tests
            (R20/R21 -- no real PDF open in the offline suite); when None,
            read via PyMuPDF (fitz).

    Outputs:
        (int, int) | None: 0-indexed (start_page, end_page_inclusive), or
            None if the chapter's own heading was not found on any page.
    --------------------------------------------------------------------------
    """
    if page_texts is None:
        import fitz

        doc = fitz.open(pdf_path)
        page_texts = [page.get_text() for page in doc]

    start = None
    end = len(page_texts) - 1
    for index, text in enumerate(page_texts):
        match = _CHAPTER_NUMBER_RE.search(text)
        if not match:
            continue
        number = int(match.group(1))
        if number == chapter_number and start is None:
            start = index
        elif start is not None and number > chapter_number:
            end = index - 1
            break
    return (start, end) if start is not None else None


def render_pdf_pages_to_images(
    pdf_path: str, page_range: tuple[int, int], out_dir: Path, *, dpi: int, renderer: Callable[[str, int, int, Path], Path] | None = None
) -> list[Path]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Render each page in the given 0-indexed inclusive range to a PNG.

    Inputs:
        pdf_path (str): path to the PDF.
        page_range (tuple[int, int]): (start_page, end_page_inclusive).
        out_dir (Path): where to write the PNGs.
        dpi (int): render resolution, from pdf2md-validate.json.
        renderer (callable | None): injected for tests -- (pdf_path,
            page_index, dpi, out_dir) -> written Path; defaults to a real
            PyMuPDF render (R20/R21).

    Outputs:
        list[Path]: one path per rendered page, in page order.
    --------------------------------------------------------------------------
    """
    def default_renderer(path: str, page_index: int, render_dpi: int, directory: Path) -> Path:
        import fitz

        doc = fitz.open(path)
        pixmap = doc[page_index].get_pixmap(dpi=render_dpi)
        image_path = directory / f"page_{page_index + 1}.png"
        pixmap.save(str(image_path))
        return image_path

    renderer = renderer or default_renderer
    out_dir.mkdir(parents=True, exist_ok=True)
    start, end = page_range
    return [renderer(pdf_path, page_index, dpi, out_dir) for page_index in range(start, end + 1)]


def build_vlm_check_prompt() -> str:
    """The fixed prompt sent with every --vlm-check call, asking for
    STRUCTURED counts rather than free prose, so the response can be
    parsed without a second model call to interpret it."""
    return (
        "Count, across the document pages shown, the number of: numbered "
        "equations, tables, figures with a caption, numbered sections, and "
        "numbered subsections. Answer ONLY as JSON with exactly these keys: "
        '{"equations": N, "tables": N, "figures": N, "sections": N, "subsections": N}'
    )


def ask_local_vlm_for_counts(
    image_paths: list[Path],
    *,
    model_tag: str,
    base_url: str,
    timeout_s: float,
    caller: Callable[[str, bytes, float], bytes] | None = None,
) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Send the rendered page images to a local Ollama vision model via
        its /api/generate endpoint and parse the structured JSON it
        returns. UNVERIFIED LIVE (module docstring) -- caller is injected
        for every offline test; no real HTTP call has yet succeeded
        against a running model.

    Inputs:
        image_paths (list[Path]): PNG files to send, base64-encoded here.
        model_tag (str): the OPERATOR-NAMED Ollama tag (--vlm-check-model;
            never a default, R2 -- this script never names a model).
        base_url (str): Ollama's API base, from pdf2md-validate.json.
        timeout_s (float): bounded timeout, from pdf2md-validate.json (R10).
        caller (callable | None): injected for tests -- (url, body_bytes,
            timeout_s) -> raw response bytes; defaults to a real
            urllib.request POST.

    Outputs:
        dict: the parsed {"equations", "tables", "figures", "sections",
            "subsections"} counts.

    Raises:
        ValueError: the model's response is not the expected JSON shape.
    --------------------------------------------------------------------------
    """
    import base64

    images_b64 = [base64.b64encode(path.read_bytes()).decode("ascii") for path in image_paths]
    body = json.dumps(
        {"model": model_tag, "prompt": build_vlm_check_prompt(), "images": images_b64, "stream": False, "format": "json"}
    ).encode("utf-8")

    def default_caller(url: str, data: bytes, timeout: float) -> bytes:
        import urllib.request

        request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()

    caller = caller or default_caller
    raw = caller(f"{base_url}/api/generate", body, timeout_s)
    try:
        envelope = json.loads(raw)
        return json.loads(envelope["response"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"local VLM returned an unparsable response: {raw!r}") from exc


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_path")
    parser.add_argument("-o", "--output-dir", required=True)
    parser.add_argument("--vlm-check", action="store_true", help="second-opinion pass on mismatched chapters via a local vision model")
    parser.add_argument("--vlm-check-model", default=None, help="REQUIRED with --vlm-check; the operator's own Ollama tag (R2 -- never a default)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.vlm_check and not args.vlm_check_model:
        print("[VALIDATE] refusing: --vlm-check requires --vlm-check-model TAG (never a default, R2).", file=sys.stderr)
        return 2

    config = load_config()
    pdf_chapters = extract_pdf_chapters(args.pdf_path)
    output_chapters = load_output_chapters(Path(args.output_dir))
    rows = compare_chapters(
        pdf_chapters,
        output_chapters,
        math_min_symbols=config["math_density_min_symbols_per_line"],
        math_symbol_chars=config["math_symbol_chars"],
    )
    flagged = flag_mismatched_chapters(rows, word_tolerance_pct=config["word_count_mismatch_threshold_pct"])
    report = render_report_md(rows)

    vlm_results: dict[int, dict] = {}
    if args.vlm_check:
        scratch_dir = Path(args.output_dir) / "validate-scratch"
        for chapter_number in flagged:
            page_range = find_chapter_page_range(args.pdf_path, chapter_number)
            if page_range is None:
                continue
            images = render_pdf_pages_to_images(args.pdf_path, page_range, scratch_dir / f"chapter_{chapter_number}", dpi=config["vlm_check_dpi"])
            vlm_results[chapter_number] = ask_local_vlm_for_counts(
                images, model_tag=args.vlm_check_model, base_url=config["vlm_check_base_url"], timeout_s=config["vlm_check_timeout_s"]
            )

    result = {"ok": True, "flagged_chapters": flagged, "report_md": report, "vlm_check": vlm_results if args.vlm_check else None}
    if args.json:
        print(json.dumps(result))
    else:
        print(report)
        if flagged:
            print(f"Flagged for closer review: chapters {flagged}")
        if vlm_results:
            print(json.dumps(vlm_results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
