"""
pdf2md_fidelity - Stage 7b of the pdf2md pipeline: a CONTENT fidelity check
between the PDF and pdf2md's output, chapter by chapter, that finds real
conversion errors rather than miscounted metrics.

pdf2md_validate compares counts (words, sections, citation markers). On a
math-heavy chapter those counts are dominated by how each reader renders
formulas, so a large gap there says nothing about whether the conversion is
right. This module compares CONTENT instead and reports defects a person
would call conversion errors:

- missing_heading: a numbered heading (or, as a warning, an unnumbered one)
  that the PDF has and the output lacks. The report says whether the title
  text survives as plain text, which is the signature of a heading that
  mineru read but did not mark up.
- out_of_order_heading / out_of_order_paragraph: content present in the
  output but in a different order than in the PDF.
- missing_paragraph: a prose paragraph of the PDF with no counterpart in the
  output.
- extra_paragraph: prose in the output that the PDF chapter does not hold.
- duplicate_paragraph: a paragraph repeated in the output more often than
  in the PDF.
- embedded_image: a base64 data-URI image left in the markdown.
- html_residue: HTML markup (page-footnote spans) left in the markdown.
- image_analysis_block: a <details> block mineru wrote under an image (a table of values read off a plot, a description of a diagram).

Formulas are excluded from the comparison on both sides (the output's
$...$ spans, and PDF paragraphs that are mostly non-prose tokens), because
the PDF reader renders math as italic fragments that no text comparison can
match. Equation correctness is a separate check (a vision model reading the
page), not this one.

Matching is by letters-only, accent-folded character n-grams over prose
words, not by word equality: this PDF's font garbles accented characters
in the reader, so a word-level comparison would report every accented word
as different. The PDF reader also splits a paragraph at every page break
and interleaves running headers and page numbers, which is why a PDF
paragraph is matched against the whole output chapter and not against one
output paragraph.

Every threshold is read from pdf2md-fidelity.json (R0, R4).
"""

from __future__ import annotations

import bisect
import difflib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

_CONFIG_PATH = Path(__file__).with_name("pdf2md-fidelity.json")
_CONFIG_KEYS = (
    "min_prose_tokens",
    "min_token_letters",
    "min_prose_ratio",
    "ngram_chars",
    "paragraph_missing_below",
    "locate_chunk_words",
    "locate_secondary_vote_share",
    "locate_max_span_paragraphs",
    "out_of_order_min_displacement",
    "duplicate_vote_tolerance",
    "running_header_min_repeats",
    "running_header_min_letters",
    "caption_sentence_words",
    "figure_image_window_lines",
    "citation_min_letters",
    "title_match_ratio",
    "pdf_noise_markers",
    "html_residue_pattern",
    "unnumbered_heading_severity",
)

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
_SEVERITIES = (SEVERITY_ERROR, SEVERITY_WARNING)

_DATA_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(data:[^)]*\)")
_MATH_SPAN_RE = re.compile(r"\$\$.+?\$\$|\$[^$\n]+?\$", re.DOTALL)
_HEADING_LINE_RE = re.compile(r"^\s*#{1,6}\s+(?P<body>.+?)\s*$")
_NUMBERED_TITLE_RE = re.compile(r"^(?P<num>\d+(?:\.\d+)+)\.?\s+(?P<title>.+)$")
_CHAPTER_TITLE_RE = re.compile(r"^chapitre\s+\d+\b", re.IGNORECASE)
_PICTURE_MARKER_RE = re.compile(r"^\**==>.*<==\**$")
_EXCERPT_CHARS = 110


@dataclass(frozen=True)
class Paragraph:
    """One blank-line-separated block of prose, the 1-based line it starts on
    and the 1-based line it ends on (0 when a caller builds one by hand)."""

    text: str
    line: int
    end: int = 0


@dataclass(frozen=True)
class Heading:
    """A markdown heading: its numeric label (None when unnumbered), title text, and 1-based line."""

    number: tuple[int, ...] | None
    title: str
    line: int


@dataclass
class Issue:
    """One conversion defect, with enough context to find it in both documents."""

    chapter: int
    kind: str
    severity: str
    detail: str
    pdf_excerpt: str = ""
    output_line: int | None = None

    def to_dict(self) -> dict:
        """Return the issue as a plain dict, for the JSON report."""
        return asdict(self)


def load_fidelity_config(path: Path = _CONFIG_PATH) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read this module's thresholds from pdf2md-fidelity.json (R0), each key
        carrying a {"value", "provenance"} pair (R4).

    Inputs:
        path (Path): where the config lives; overridable for tests.

    Outputs:
        dict: key -> value for every key in _CONFIG_KEYS.

    Raises:
        FileNotFoundError: the config file is absent.
        KeyError: a required key is missing (R3: the key is named).
        ValueError: unnumbered_heading_severity is not "error" or "warning".
    --------------------------------------------------------------------------
    """
    if not path.exists():
        raise FileNotFoundError(f"pdf2md fidelity config not found at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in _CONFIG_KEYS if key not in data]
    if missing:
        raise KeyError(f"{path} is missing required config key(s): {missing}")
    config = {key: data[key]["value"] for key in _CONFIG_KEYS}
    if config["unnumbered_heading_severity"] not in _SEVERITIES:
        raise ValueError(f"{path}: unnumbered_heading_severity must be one of {_SEVERITIES}")
    return config


# --------------------------------------------------------------------------- #
# Text normalisation: what counts as comparable prose.
# --------------------------------------------------------------------------- #


def fold_letters(text: str) -> str:
    """Lower-case, accent-folded, letters-only form of text (digits, spaces and
    punctuation dropped). Letters that cannot be folded to ASCII are dropped,
    which is what lets a garbled accented character in the PDF reader line up
    with its clean counterpart in the output."""
    decomposed = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z]", "", decomposed.lower())


def prose_words(text: str, *, min_letters: int) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        The folded words of text that are long enough to be prose. A token
        with fewer than min_letters letters (a variable name, a subscript, a
        stray symbol) is dropped, so inline math contributes nothing.

    Inputs:
        text (str): a paragraph.
        min_letters (int): minimum letters for a token to count.

    Outputs:
        list[str]: folded prose words, in reading order.
    --------------------------------------------------------------------------
    """
    words = (fold_letters(token) for token in text.split())
    return [word for word in words if len(word) >= min_letters]


_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def strip_math_and_images(text: str) -> str:
    """Remove base64 images, HTML comments and $...$ / $$...$$ spans from
    markdown, replacing each with the newlines it held so every remaining
    line keeps its number. A comment is a note to a reader of the markdown (the
    one pdf2md writes beside a transcribed equation), not content to compare."""
    def keep_newlines(match: re.Match) -> str:
        return " " + "\n" * match.group(0).count("\n")

    return _MATH_SPAN_RE.sub(keep_newlines, _HTML_COMMENT_RE.sub(keep_newlines, _DATA_IMAGE_RE.sub(keep_newlines, text)))


def split_paragraphs(text: str) -> list[Paragraph]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Split markdown or reader text into blank-line-separated paragraphs.
        A heading line and a picture-omitted marker each end the paragraph
        in progress and are not paragraphs themselves.

    Inputs:
        text (str): chapter text.

    Outputs:
        list[Paragraph]: non-empty paragraphs with their starting line.
    --------------------------------------------------------------------------
    """
    paragraphs: list[Paragraph] = []
    current: list[str] = []
    start = 0
    last = 0

    def flush() -> None:
        if current:
            paragraphs.append(Paragraph(" ".join(current), start, last))
            current.clear()

    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or _HEADING_LINE_RE.match(line) or _PICTURE_MARKER_RE.match(stripped):
            flush()
            continue
        if not current:
            start = number
        current.append(stripped)
        last = number
    flush()
    return paragraphs


def drop_running_headers(paragraphs: list[Paragraph], *, min_repeats: int) -> list[Paragraph]:
    """Drop every paragraph that, once digits and punctuation are removed,
    occurs at least min_repeats times: a page header, footer or page number,
    which the PDF reader repeats on every page."""
    keys = [fold_letters(paragraph.text) or paragraph.text.strip() for paragraph in paragraphs]
    counts = Counter(keys)
    return [paragraph for paragraph, key in zip(paragraphs, keys) if counts[key] < min_repeats]


def _fingerprint(paragraph: Paragraph, config: dict, *, require_prose_ratio: bool = True) -> str | None:
    """The folded prose of a paragraph, or None when it is too short or too
    formula-like to compare (fewer than min_prose_tokens prose words, or, when
    require_prose_ratio is set, a prose share below min_prose_ratio). Locating
    a page waives the ratio: a math-heavy page is exactly the one wanted, and
    its prose words are still a valid fingerprint."""
    words = prose_words(paragraph.text, min_letters=config["min_token_letters"])
    total = len(paragraph.text.split())
    if len(words) < config["min_prose_tokens"] or not total:
        return None
    if require_prose_ratio and len(words) / total < config["min_prose_ratio"]:
        return None
    return "".join(words)


def is_pdf_noise(paragraph: Paragraph, markers: list[str]) -> bool:
    """True for a PDF paragraph that is a table row or holds text rendered
    from inside a figure or a table cell: not prose, and not comparable to
    the output's own markdown tables."""
    return paragraph.text.startswith("|") or any(marker in paragraph.text for marker in markers)


def _ngrams(folded: str, size: int) -> set[str]:
    return {folded[i : i + size] for i in range(len(folded) - size + 1)}


def _longest_nondecreasing(sequence: list[int]) -> set[int]:
    """Indices of one longest non-decreasing subsequence of sequence. The
    indices NOT returned are the elements that sit out of order."""
    tails: list[int] = []
    tail_index: list[int] = []
    previous = [-1] * len(sequence)
    for index, value in enumerate(sequence):
        position = bisect.bisect_right(tails, value)
        if position == len(tails):
            tails.append(value)
            tail_index.append(index)
        else:
            tails[position] = value
            tail_index[position] = index
        previous[index] = tail_index[position - 1] if position else -1
    keep: set[int] = set()
    cursor = tail_index[-1] if tail_index else -1
    while cursor != -1:
        keep.add(cursor)
        cursor = previous[cursor]
    return keep


# --------------------------------------------------------------------------- #
# Headings.
# --------------------------------------------------------------------------- #


def extract_headings(text: str) -> list[Heading]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List the markdown headings of a chapter, parsing a leading N.M.K
        number when there is one. The chapter's own "CHAPITRE N" heading is
        left out, since the chapter splitter already keys on it.

    Inputs:
        text (str): chapter text (pdf2md output or PDF reader markdown).

    Outputs:
        list[Heading]: in document order.
    --------------------------------------------------------------------------
    """
    headings: list[Heading] = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = _HEADING_LINE_RE.match(line)
        if not match:
            continue
        body = match.group("body").replace("*", "").strip()
        if not body or _CHAPTER_TITLE_RE.match(body):
            continue
        numbered = _NUMBERED_TITLE_RE.match(body)
        if numbered:
            label = tuple(int(part) for part in numbered.group("num").split("."))
            headings.append(Heading(label, numbered.group("title").strip(), number))
        else:
            headings.append(Heading(None, body, number))
    return headings


def plain_text_line(output_text: str, title: str) -> int | None:
    """The line of a non-heading line that holds exactly this title, or None:
    the signature of a heading that was read but not marked up."""
    wanted = fold_letters(title)
    if not wanted:
        return None
    for number, line in enumerate(output_text.splitlines(), start=1):
        if not _HEADING_LINE_RE.match(line) and fold_letters(line) == wanted:
            return number
    return None


def compare_headings(chapter: int, pdf_text: str, output_text: str, config: dict) -> list[Issue]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report headings the output lost, headings out of order, and headings
        whose title text differs from the PDF's.

    Inputs:
        chapter (int): chapter number, for the issue records.
        pdf_text (str): the PDF reader's text for the chapter.
        output_text (str): pdf2md's output for the chapter.
        config (dict): thresholds from load_fidelity_config.

    Outputs:
        list[Issue]: possibly empty.
    --------------------------------------------------------------------------
    """
    issues: list[Issue] = []
    pdf_headings = extract_headings(pdf_text)
    output_headings = extract_headings(output_text)
    output_by_number: dict[tuple[int, ...], Heading] = {}
    for heading in output_headings:
        if heading.number is not None:
            output_by_number.setdefault(heading.number, heading)
    output_titles = {fold_letters(heading.title) for heading in output_headings}

    for heading in pdf_headings:
        label = ".".join(str(part) for part in heading.number) + " " if heading.number else ""
        if heading.number is not None:
            found = output_by_number.get(heading.number)
            severity = SEVERITY_ERROR
        else:
            found = Heading(None, heading.title, 0) if fold_letters(heading.title) in output_titles else None
            severity = config["unnumbered_heading_severity"]
        if found is None:
            plain_line = plain_text_line(output_text, heading.title)
            if heading.number is None and plain_line:
                # An unnumbered "heading" whose text survives as a line is
                # most often a bold label the reader promoted (measured:
                # "Statut de soumission :"), not a lost heading.
                continue
            where = f"the title text is present as plain text at output line {plain_line}" if plain_line else "the title text is absent as a line"
            issues.append(Issue(chapter, "missing_heading", severity, f"heading '{label}{heading.title}' is not in the output; {where}", heading.title, plain_line))
        elif heading.number is not None:
            ratio = difflib.SequenceMatcher(None, fold_letters(heading.title), fold_letters(found.title)).ratio()
            if ratio < config["title_match_ratio"]:
                issues.append(Issue(chapter, "heading_title_mismatch", SEVERITY_WARNING, f"heading {label}reads '{found.title}' in the output and '{heading.title}' in the PDF", heading.title, found.line))

    rank = {heading.number: index for index, heading in enumerate(h for h in pdf_headings if h.number is not None)}
    ordered = [heading for heading in output_headings if heading.number in rank]
    keep = _longest_nondecreasing([rank[heading.number] for heading in ordered])
    for index, heading in enumerate(ordered):
        if index not in keep:
            label = ".".join(str(part) for part in heading.number)
            issues.append(Issue(chapter, "out_of_order_heading", SEVERITY_ERROR, f"heading {label} '{heading.title}' sits out of order relative to the PDF", heading.title, heading.line))
    return issues


# --------------------------------------------------------------------------- #
# Paragraph content.
# --------------------------------------------------------------------------- #


def is_caption_paragraph(text: str, config: dict) -> bool:
    """True when the paragraph is a figure or table caption (not an in-text
    sentence about one): see caption_labels."""
    return any(caption_labels(text.splitlines()[0] if text else "", config).values())


def _best_position(votes: Counter) -> int:
    """The position with the most votes; a tie goes to the EARLIEST position.
    Without the explicit tie-break the winner followed set-iteration order,
    which Python randomises per process, so the same inputs gave a different
    alignment (measured 2026-10-11: 55 then 52 errors on the same files, R19)."""
    return min(votes, key=lambda position: (-votes[position], position))


def index_paragraphs(paragraphs: list[Paragraph], config: dict) -> dict[str, set[int]]:
    """Inverted index: every letters-only n-gram of every paragraph's prose
    words -> the positions of the paragraphs that hold it."""
    index: dict[str, set[int]] = {}
    for position, paragraph in enumerate(paragraphs):
        folded = "".join(prose_words(paragraph.text, min_letters=config["min_token_letters"]))
        for gram in _ngrams(folded, config["ngram_chars"]):
            index.setdefault(gram, set()).add(position)
    return index


def locate_paragraph(paragraph: Paragraph, index: dict[str, set[int]], config: dict) -> int | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find the output paragraph that holds a PDF paragraph's prose.

    Inputs:
        paragraph (Paragraph): a PDF paragraph.
        index (dict): from index_paragraphs over the output's paragraphs.
        config (dict): thresholds from load_fidelity_config.

    Outputs:
        int | None: position (in the output paragraph list the index was built
            from) of the paragraph holding most of its fingerprints, or None
            when the paragraph is too short or formula-like to compare, or
            fewer than paragraph_missing_below of its fingerprints are found.
    --------------------------------------------------------------------------
    """
    fingerprint = _fingerprint(paragraph, config)
    if fingerprint is None or len(fingerprint) < config["ngram_chars"]:
        return None
    grams = _ngrams(fingerprint, config["ngram_chars"])
    hits = [gram for gram in grams if gram in index]
    if len(hits) / len(grams) < config["paragraph_missing_below"]:
        return None
    return _best_position(Counter(position for gram in hits for position in index[gram]))


def locate_in_output(page_text: str, output_text: str, config: dict) -> tuple[int, int] | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find the output lines that hold the prose of one PDF page, so a
        reader of that page's image can be shown the markdown that is
        supposed to say the same thing, formulas included.

    Details:
        A raw page text has no blank lines between paragraphs, so it is cut
        into chunks of locate_chunk_words words and each chunk is matched
        on its own. Each chunk goes to the output paragraph holding most of
        its fingerprints, if at least paragraph_missing_below of them are
        found; a chunk that matches nothing is ignored.

    Inputs:
        page_text (str): the page's text from the PDF reader.
        output_text (str): the chapter's markdown (formulas included).
        config (dict): thresholds from load_fidelity_config.

    Outputs:
        (int, int) | None: first and last 1-based output line of the matched
            paragraphs, or None when no chunk of the page could be located.
    --------------------------------------------------------------------------
    """
    size = config["ngram_chars"]
    output_paragraphs = split_paragraphs(strip_math_and_images(output_text))
    index = index_paragraphs(output_paragraphs, config)
    words = page_text.split()
    step = config["locate_chunk_words"]
    located: set[int] = set()
    for begin in range(0, len(words), step):
        chunk = Paragraph(" ".join(words[begin : begin + step]), 0)
        fingerprint = _fingerprint(chunk, config, require_prose_ratio=False)
        if fingerprint is None or len(fingerprint) < size:
            continue
        grams = _ngrams(fingerprint, size)
        hits = [gram for gram in grams if gram in index]
        if len(hits) / len(grams) < config["paragraph_missing_below"]:
            continue
        votes = Counter(position for gram in hits for position in index[gram])
        top = votes.most_common(1)[0][1]
        # A chunk can straddle two output paragraphs, so every paragraph
        # holding a comparable share of its fingerprints is kept, not only the best.
        for position, count in votes.items():
            if count >= top * config["locate_secondary_vote_share"]:
                located.add(position)
    if not located:
        return None
    # A page is a few paragraphs wide. A chunk that matches a paragraph far
    # from the rest (a repeated phrase) would stretch the range over half the
    # chapter, so only the densest window of locate_max_span_paragraphs is kept.
    ordered = sorted(located)
    window = max(
        ([p for p in ordered if first <= p <= first + config["locate_max_span_paragraphs"]] for first in ordered),
        key=len,
    )
    return output_paragraphs[window[0]].line, output_paragraphs[window[-1]].end


@dataclass
class Alignment:
    """How a chapter's PDF paragraphs line up with its output paragraphs.

    pdf_prints / output_prints: (paragraph, fingerprint or None) in reading order.
    pdf_grams: every n-gram of the PDF side, for the extra-content check.
    missing: PDF paragraphs with no counterpart, as (paragraph, hits, total).
    matched: PDF paragraphs found in the output, as (paragraph, output position).
    keep: indices into matched that lie on one longest in-order run; every
        other matched paragraph sits out of order.
    displacement: for each out-of-order index, how many output paragraphs it
        sits from the interval its in-order neighbours allow. A caption next
        to the float the reader placed elsewhere moves by one or two; a
        block in the wrong chapter section moves by dozens.
    """

    pdf_prints: list[tuple[Paragraph, str | None]]
    output_prints: list[tuple[Paragraph, str | None]]
    pdf_grams: set[str]
    missing: list[tuple[Paragraph, int, int]]
    matched: list[tuple[Paragraph, int]]
    keep: set[int]
    displacement: dict[int, int] = field(default_factory=dict)


def align_paragraphs(pdf_text: str, output_text: str, config: dict) -> Alignment:
    """
    --------------------------------------------------------------------------
    Purpose:
        Match every comparable PDF paragraph to the output paragraph that
        holds most of its fingerprints, and find which matches are out of
        order. The shared first half of compare_paragraphs and of the repair
        stage, so the two cannot disagree about what is misplaced.

    Inputs:
        pdf_text (str): the PDF reader's text for the chapter.
        output_text (str): pdf2md's output for the chapter.
        config (dict): thresholds from load_fidelity_config.

    Outputs:
        Alignment: see the class.
    --------------------------------------------------------------------------
    """
    size = config["ngram_chars"]
    pdf_paragraphs = drop_running_headers(split_paragraphs(pdf_text), min_repeats=config["running_header_min_repeats"])
    pdf_paragraphs = [p for p in pdf_paragraphs if not is_pdf_noise(p, config["pdf_noise_markers"])]
    output_paragraphs = split_paragraphs(strip_math_and_images(output_text))

    pdf_prints = [(paragraph, _fingerprint(paragraph, config)) for paragraph in pdf_paragraphs]
    output_prints = [(paragraph, _fingerprint(paragraph, config)) for paragraph in output_paragraphs]

    output_index = index_paragraphs(output_paragraphs, config)
    pdf_grams: set[str] = set()
    for paragraph, _print in pdf_prints:
        pdf_grams |= _ngrams("".join(prose_words(paragraph.text, min_letters=config["min_token_letters"])), size)

    missing: list[tuple[Paragraph, int, int]] = []
    matched: list[tuple[Paragraph, int]] = []
    last = -1
    for paragraph, fingerprint in pdf_prints:
        if fingerprint is None or len(fingerprint) < size:
            continue
        if is_caption_paragraph(paragraph.text, config):
            # A figure or a table floats: the PDF reader puts its caption where
            # the page layout put it, mineru where the text refers to it, and
            # neither is wrong. Its presence is compare_captions' job. Moving
            # one in a repair detached 3.8 and 3.9 from their images.
            continue
        grams = _ngrams(fingerprint, size)
        hits = [gram for gram in grams if gram in output_index]
        if len(hits) / len(grams) < config["paragraph_missing_below"]:
            missing.append((paragraph, len(hits), len(grams)))
            continue
        votes = Counter(position for gram in hits for position in output_index[gram])
        # Near-identical paragraphs (a theorem restated, a repeated sentence)
        # tie or nearly tie. Take the first of the near-best that does not go
        # backwards, so a repeat is matched to the occurrence the PDF order
        # implies instead of to an earlier look-alike.
        top = max(votes.values())
        near_best = [position for position, count in votes.items() if count >= top * config["duplicate_vote_tolerance"]]
        forward = [position for position in near_best if position >= last]
        chosen = min(forward) if forward else _best_position(votes)
        last = max(last, chosen)
        matched.append((paragraph, chosen))

    keep = _longest_nondecreasing([position for _paragraph, position in matched])
    kept_sorted = sorted(keep)
    displacement: dict[int, int] = {}
    for index, (_paragraph, position) in enumerate(matched):
        if index in keep:
            continue
        before = [k for k in kept_sorted if k < index]
        after = [k for k in kept_sorted if k > index]
        low = matched[before[-1]][1] if before else None
        high = matched[after[0]][1] if after else None
        if high is not None and position > high:
            displacement[index] = position - high
        elif low is not None and position < low:
            displacement[index] = low - position
        else:
            displacement[index] = 0
    return Alignment(pdf_prints, output_prints, pdf_grams, missing, matched, keep, displacement)


def compare_paragraphs(chapter: int, pdf_text: str, output_text: str, config: dict) -> list[Issue]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report prose paragraphs missing from the output, prose in the output
        that the PDF does not hold, paragraphs repeated in the output, and
        paragraphs that sit out of order. Formulas are excluded on both sides.

    Inputs:
        chapter (int): chapter number, for the issue records.
        pdf_text (str): the PDF reader's text for the chapter.
        output_text (str): pdf2md's output for the chapter.
        config (dict): thresholds from load_fidelity_config.

    Outputs:
        list[Issue]: possibly empty.
    --------------------------------------------------------------------------
    """
    size = config["ngram_chars"]
    alignment = align_paragraphs(pdf_text, output_text, config)
    pdf_prints, output_prints, pdf_grams = alignment.pdf_prints, alignment.output_prints, alignment.pdf_grams

    issues: list[Issue] = []
    for paragraph, hits, total in alignment.missing:
        issues.append(Issue(chapter, "missing_paragraph", SEVERITY_ERROR, f"a PDF paragraph has no counterpart in the output ({hits}/{total} fingerprints found)", paragraph.text[:_EXCERPT_CHARS]))
    for index, (paragraph, position) in enumerate(alignment.matched):
        if index not in alignment.keep and alignment.displacement[index] >= config["out_of_order_min_displacement"]:
            issues.append(Issue(chapter, "out_of_order_paragraph", SEVERITY_ERROR, "a PDF paragraph appears in the output, but not at the place it holds in the PDF", paragraph.text[:_EXCERPT_CHARS], output_prints[position][0].line))

    for paragraph, fingerprint in output_prints:
        if fingerprint is None or len(fingerprint) < size:
            continue
        grams = _ngrams(fingerprint, size)
        if len(grams & pdf_grams) / len(grams) < config["paragraph_missing_below"]:
            issues.append(Issue(chapter, "extra_paragraph", SEVERITY_WARNING, "an output paragraph has no counterpart in this chapter's PDF text", paragraph.text[:_EXCERPT_CHARS], paragraph.line))

    pdf_counts = Counter(fingerprint for _paragraph, fingerprint in pdf_prints if fingerprint)
    seen: Counter = Counter()
    for paragraph, fingerprint in output_prints:
        if not fingerprint:
            continue
        seen[fingerprint] += 1
        if seen[fingerprint] > max(1, pdf_counts[fingerprint]):
            issues.append(Issue(chapter, "duplicate_paragraph", SEVERITY_ERROR, "an output paragraph repeats more often than in the PDF", paragraph.text[:_EXCERPT_CHARS], paragraph.line))
    return issues


def find_embedded_images(chapter: int, output_text: str) -> list[Issue]:
    """One embedded_image error per base64 data-URI image left in the markdown."""
    return [
        Issue(chapter, "embedded_image", SEVERITY_ERROR, "a base64 image is embedded in the markdown", "", output_text.count("\n", 0, match.start()) + 1)
        for match in _DATA_IMAGE_RE.finditer(output_text)
    ]


def find_html_residue(chapter: int, output_text: str, config: dict) -> list[Issue]:
    """One html_residue error per output line holding HTML markup that
    html_residue_pattern names (page-footnote spans left by mineru)."""
    pattern = re.compile(config["html_residue_pattern"])
    return [
        Issue(chapter, "html_residue", SEVERITY_ERROR, "HTML markup is left in the markdown", pattern.search(line).group(0), number)
        for number, line in enumerate(output_text.splitlines(), start=1)
        if pattern.search(line)
    ]


# --------------------------------------------------------------------------- #
# What the PDF reader adds that is not content: running headers, figure text.
# --------------------------------------------------------------------------- #


def clean_pdf_text(text: str, config: dict) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Remove from the PDF reader's text what is not the document's content:
        running page headers and footers, page numbers, the text the reader
        lifts out of figures ("Start of picture text") and its "picture
        omitted" markers. Used before any count, so the PDF side is not
        inflated by lines the converted markdown rightly does not carry
        (measured 2026-10-11: about 900 words of repeated chapter titles in
        one chapter).

    Details:
        A line is a running header when, digits and punctuation removed, it
        repeats running_header_min_repeats times or more and holds at least
        running_header_min_letters letters. A line made only of digits is a
        page number. Line numbering is preserved: a removed line becomes an
        empty one.

    Inputs:
        text (str): one chapter of the PDF reader's text.
        config (dict): thresholds from load_fidelity_config.

    Outputs:
        str: the cleaned text, same number of lines.
    --------------------------------------------------------------------------
    """
    lines = text.splitlines()
    keys = [fold_letters(line) for line in lines]
    counts = Counter(key for key in keys if len(key) >= config["running_header_min_letters"])
    cleaned = []
    for line, key in zip(lines, keys):
        stripped = line.strip()
        # A real heading ("## 1.1 Contexte") folds to the same key as its own
        # running header ("1.1. CONTEXTE") and must not go with it.
        is_heading = bool(_HEADING_LINE_RE.match(line))
        header = not is_heading and len(key) >= config["running_header_min_letters"] and counts[key] >= config["running_header_min_repeats"]
        page_number = bool(stripped) and stripped.replace("*", "").strip().isdigit()
        # Text the reader lifts out of a figure is <br>-joined and is not a
        # table row (rows start with a pipe), so it goes: its words and its
        # "[31]" labels are in the picture, not in the prose.
        picture = "intentionally omitted" in stripped or ("<br>" in stripped and not stripped.startswith("|"))
        cleaned.append("" if header or page_number or picture else line)
    return "\n".join(cleaned)


# --------------------------------------------------------------------------- #
# Captions, figures and tables.
# --------------------------------------------------------------------------- #

_CAPTION_RE = re.compile(r"^[\s|*_#>]*(?P<kind>Figure|Fig\.|Table|Tableau)\s+(?P<label>\d+(?:\.\d+)*)\**\s*[.:]?\**(?:\s+|<br>)(?P<first>[^\s]+)", re.IGNORECASE)


def caption_labels(text: str, config: dict) -> dict[str, list[tuple[str, int]]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        The captions of a chapter: a line that starts with a figure or table
        label followed by a description. An in-text sentence about the same
        label ("Figure 3.8 presents ...") is not a caption.

    Details:
        The word after the label decides, against caption_sentence_words
        (data, with its measured provenance). Table markup the PDF reader
        puts before a caption ("||Table 3.3<br>") is ignored.

    Inputs:
        text (str): chapter text, either side.
        config (dict): thresholds from load_fidelity_config.

    Outputs:
        dict: {"figure": [(label, line)], "table": [(label, line)]}, first
            occurrence of each label only, in document order, 1-based lines.
    --------------------------------------------------------------------------
    """
    verbs = {word.lower() for word in config["caption_sentence_words"]}
    found: dict[str, list[tuple[str, int]]] = {"figure": [], "table": []}
    seen: set[tuple[str, str]] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        match = _CAPTION_RE.match(line)
        if not match:
            continue
        first = re.sub(r"^[^\w]+|<br>.*$", "", match.group("first")).lower()
        if first in verbs:
            continue
        kind = "figure" if match.group("kind").lower().startswith("fig") else "table"
        if (kind, match.group("label")) not in seen:
            seen.add((kind, match.group("label")))
            found[kind].append((match.group("label"), number))
    return found


_IMAGE_LINE_RE = re.compile(r"!\[[^\]]*\]\(")


def _has_image_before(lines: list[str], caption_line: int, window: int) -> bool:
    """True when an image link sits within `window` lines above the caption
    without a heading or another caption in between (1-based caption_line)."""
    for index in range(caption_line - 2, max(-1, caption_line - 2 - window), -1):
        line = lines[index]
        if _IMAGE_LINE_RE.search(line):
            return True
        if _HEADING_LINE_RE.match(line) or _CAPTION_RE.match(line):
            return False
    return False


def compare_captions(chapter: int, pdf_text: str, output_text: str, config: dict) -> list[Issue]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report a figure or a table of the PDF that the output lost: its
        caption absent, a figure caption with no image above it, a table
        caption with no table next to it.

    Inputs:
        chapter (int): chapter number, for the issue records.
        pdf_text (str): the PDF reader's text for the chapter (cleaned).
        output_text (str): pdf2md's output for the chapter.
        config (dict): thresholds from load_fidelity_config.

    Outputs:
        list[Issue]: possibly empty.
    --------------------------------------------------------------------------
    """
    pdf_captions = caption_labels(pdf_text, config)
    output_captions = caption_labels(output_text, config)
    output_lines = output_text.splitlines()
    issues: list[Issue] = []
    for kind in ("figure", "table"):
        in_output = dict(output_captions[kind])
        for label, _line in pdf_captions[kind]:
            if label not in in_output:
                issues.append(Issue(chapter, f"{kind}_caption_missing", SEVERITY_ERROR, f"the PDF has the caption of {kind} {label} and the output does not"))
                continue
            line = in_output[label]
            if kind == "figure" and not _has_image_before(output_lines, line, config["figure_image_window_lines"]):
                issues.append(Issue(chapter, "figure_without_image", SEVERITY_ERROR, f"figure {label} has a caption but no image above it", output_lines[line - 1][:_EXCERPT_CHARS], line))
            if kind == "table" and not _table_near(output_lines, line, config["figure_image_window_lines"]):
                issues.append(Issue(chapter, "table_without_content", SEVERITY_ERROR, f"table {label} has a caption but no table next to it", output_lines[line - 1][:_EXCERPT_CHARS], line))
    return issues


_TABLE_START_RE = re.compile(r"^\s*(<table\b|\|.*\|\s*$)")


def _table_near(lines: list[str], caption_line: int, window: int) -> bool:
    """True when a markdown or HTML table starts within `window` lines after
    the caption or before it (mineru writes either order)."""
    low, high = max(0, caption_line - 1 - window), min(len(lines), caption_line + window)
    return any(_TABLE_START_RE.match(lines[index]) for index in range(low, high) if index != caption_line - 1)


# --------------------------------------------------------------------------- #
# Content that is not in the document: mineru's analysis of an image.
# --------------------------------------------------------------------------- #

_DETAILS_RE = re.compile(r"<details>\s*<summary>(?P<title>[^<]*)</summary>(?P<body>.*?)</details>", re.DOTALL)


def find_image_analysis_blocks(text: str) -> list[re.Match]:
    """
    --------------------------------------------------------------------------
    Purpose:
        The <details> blocks of the markdown. mineru writes one under an
        image it has analysed: a table of values read off a plot (summary
        "line", values written "~2.0"), or a sentence describing a diagram
        (summary "flowchart"). Neither is in the PDF, which has the image
        only, and a table of approximate values reads as a result of the
        thesis. Measured 2026-10-11 on the real thesis: 9 such blocks.

    Inputs:
        text (str): the chapter markdown.

    Outputs:
        list[re.Match]: one match per block, with groups "title" and "body".
    --------------------------------------------------------------------------
    """
    return list(_DETAILS_RE.finditer(text))


def find_image_analysis_issues(chapter: int, output_text: str) -> list[Issue]:
    """One image_analysis_block error per block, with its line and its first row."""
    issues = []
    for match in find_image_analysis_blocks(output_text):
        body = match.group("body").strip()
        first = body.splitlines()[0] if body else ""
        issues.append(Issue(chapter, "image_analysis_block", SEVERITY_ERROR, f"text written by the image analysis ('{match.group('title').strip()}') is in the markdown but not in the PDF", first[:_EXCERPT_CHARS], output_text.count("\n", 0, match.start()) + 1))
    return issues


# --------------------------------------------------------------------------- #
# Numbered equations.
# --------------------------------------------------------------------------- #

_DISPLAY_RE = re.compile(r"\$\$(?P<body>.+?)\$\$", re.DOTALL)
_TAG_RE = re.compile(r"\\tag\*?\s*\{\s*\(?\s*(?P<number>[\d.\s]+?)\s*\)?\s*\}")
_TRAILING_NUMBER_RE = re.compile(r"(?P<lead>,?\s*)\(\s*(?P<chapter>\d+)\s*\.\s*(?P<index>(?:\d\s*)+)\)\s*$")


def _split_label(raw: str) -> tuple[int, int] | None:
    parts = re.sub(r"\s+", "", raw).split(".")
    return (int(parts[0]), int(parts[-1])) if len(parts) >= 2 and all(p.isdigit() for p in parts) else None


def equation_numbers(text: str) -> list[tuple[tuple[int, int], int, str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        The numbered display equations of a chapter, whether mineru wrote the
        number as a tag (`\\tag {3.24}`) or left it as trailing text in the
        equation body (`, (3. 2 5)`, measured on the real thesis).

    Inputs:
        text (str): the chapter markdown.

    Outputs:
        list[tuple]: ((chapter part, index), 1-based line of the equation,
            form) where form is "tag" or "trailing".
    --------------------------------------------------------------------------
    """
    found = []
    for match in _DISPLAY_RE.finditer(text):
        body = match.group("body").rstrip()
        line = text.count("\n", 0, match.start()) + 1
        tag = _TAG_RE.search(body)
        label = _split_label(tag.group("number")) if tag else None
        if label:
            found.append((label, line, "tag"))
            continue
        trailing = _TRAILING_NUMBER_RE.search(body)
        if trailing:
            label = _split_label(f"{trailing.group('chapter')}.{trailing.group('index')}")
            if label:
                found.append((label, line, "trailing"))
    return found


def equation_gaps(output_text: str) -> list[tuple[int, int]]:
    """The equation numbers missing below the highest one of their prefix, as
    (prefix, index) pairs in order: (4, 5) is equation (4.5)."""
    by_prefix: dict[int, set[int]] = {}
    for (prefix, index), _line, _form in equation_numbers(output_text):
        by_prefix.setdefault(prefix, set()).add(index)
    return [(prefix, index) for prefix, present in sorted(by_prefix.items()) for index in range(1, max(present) + 1) if index not in present]


def find_equation_issues(chapter: int, output_text: str) -> list[Issue]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Check the equation numbering of a chapter against itself, which is
        the one check on equations that needs no second reader: LaTeX numbers
        equations without gaps, so a gap is an equation the conversion lost,
        and a number left as text is an equation whose label was not written
        as a tag.

    Inputs:
        chapter (int): chapter number, for the issue records.
        output_text (str): the chapter markdown.

    Outputs:
        list[Issue]: equation_number_gap (error) for each missing number
            below the highest, equation_number_unformatted (warning) for each
            number written as trailing text, equation_number_duplicate (error)
            for a number used twice.
    --------------------------------------------------------------------------
    """
    issues: list[Issue] = []
    numbers = equation_numbers(output_text)
    by_prefix: dict[int, list[int]] = {}
    for (prefix, index), line, form in numbers:
        by_prefix.setdefault(prefix, []).append(index)
        if form == "trailing":
            issues.append(Issue(chapter, "equation_number_unformatted", SEVERITY_WARNING, f"equation ({prefix}.{index}) carries its number as text, not as a tag", "", line))
    for prefix, indexes in sorted(by_prefix.items()):
        for index in sorted({i for i in indexes if indexes.count(i) > 1}):
            issues.append(Issue(chapter, "equation_number_duplicate", SEVERITY_ERROR, f"equation number ({prefix}.{index}) is used more than once"))
    for prefix, index in equation_gaps(output_text):
        issues.append(Issue(chapter, "equation_number_gap", SEVERITY_ERROR, f"equation ({prefix}.{index}) is missing between ({prefix}.{index - 1}) and ({prefix}.{index + 1})"))
    return issues


def numbered_equation_counts(output_text: str) -> tuple[int, int]:
    """(expected, found): the highest equation number of the chapter and the
    number of distinct numbers present. The PDF reader cannot read equation
    numbers, so numbering continuity is the reference."""
    numbers = {label for label, _line, _form in equation_numbers(output_text)}
    indexes = [index for _prefix, index in numbers]
    return (max(indexes) if indexes else 0, len(numbers))


# --------------------------------------------------------------------------- #
# Citations.
# --------------------------------------------------------------------------- #

_CITATION_RE = re.compile(r"\[\s*(\d+(?:\s*[,\u2013-]\s*\d+)*)\s*\]")


def citation_occurrences(text: str, config: dict) -> list[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Every citation in a chapter's prose, with the words that precede it.

    Details:
        A bracketed number counts when it follows a space and the word just
        before it has at least citation_min_letters letters and does not come
        out of a formula (preceded by an underscore, an asterisk or a
        bracket). That drops the matrix indices the PDF reader prints as
        "[0]", "[1]", "[11]" and the footnote calls attached to their word
        ("follows[3]").

    Inputs:
        text (str): chapter text, either side (formulas in $ are removed).
        config (dict): thresholds from load_fidelity_config.

    Outputs:
        list[dict]: for each citation, "numbers" (list[int]), "bracket" (the
            text as written, for example "[6, 38]"), "after" (the punctuation
            character right after it, or ""), and "words" (the folded letters
            of the five words before it, a context that identifies the place).
    --------------------------------------------------------------------------
    """
    flat = strip_math_and_images(text).replace("\n", " ")
    occurrences: list[dict] = []
    for match in _CITATION_RE.finditer(flat):
        raw_tail = flat[max(0, match.start() - 120) : match.start()]
        if not raw_tail[-1:].isspace():
            continue  # "follows[3]": a footnote call attached to its word, not a citation
        tail = raw_tail.rstrip()
        word = re.search(r"([^\W\d_]+)[,;:.]?$", tail)
        if not word or len(word.group(1)) < config["citation_min_letters"]:
            continue
        before = tail[word.start(1) - 1] if word.start(1) > 0 else " "
        if before in "_[*":
            continue
        following = flat[match.end() : match.end() + 1]
        occurrences.append({
            "numbers": [int(n) for n in re.findall(r"\d+", match.group(1))],
            "bracket": match.group(0),
            "after": following if following in ",;:." else "",
            "words": [fold_letters(w) for w in re.findall(r"[^\W\d_]+", tail)[-5:]],
        })
    return occurrences


def citation_numbers(text: str, config: dict) -> list[int]:
    """The reference numbers cited in a chapter's prose, one entry per
    occurrence (see citation_occurrences)."""
    return [number for occurrence in citation_occurrences(text, config) for number in occurrence["numbers"]]


def compare_citations(chapter: int, pdf_text: str, output_text: str, config: dict) -> list[Issue]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Report a reference the PDF cites in a chapter that the output does
        not cite there at all, and a reference cited fewer times in the
        output than in the PDF. Both are errors: a citation lost is a claim
        left without its source (measured 2026-10-11: mineru read "[14]:"
        as a fragment of mathematics).

    Inputs:
        chapter (int): chapter number, for the issue records.
        pdf_text (str): the PDF reader's text for the chapter (cleaned).
        output_text (str): pdf2md's output for the chapter.
        config (dict): thresholds from load_fidelity_config.

    Outputs:
        list[Issue]: possibly empty.
    --------------------------------------------------------------------------
    """
    in_pdf, in_output = Counter(citation_numbers(pdf_text, config)), Counter(citation_numbers(output_text, config))
    absent = sorted(n for n in in_pdf if n not in in_output)
    fewer = sorted(n for n in in_pdf if n in in_output and in_output[n] < in_pdf[n])
    issues = []
    if absent:
        issues.append(Issue(chapter, "citation_missing", SEVERITY_ERROR, f"cited in the PDF and not in the output: {absent}"))
    if fewer:
        issues.append(Issue(chapter, "citation_undercounted", SEVERITY_ERROR, f"cited fewer times in the output than in the PDF: {fewer}"))
    return issues


# --------------------------------------------------------------------------- #
# Whole-document report.
# --------------------------------------------------------------------------- #


def check_chapters(pdf_chapters: dict[int, tuple[str, str]], output_chapters: dict[int, tuple[str, str]], config: dict) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run every fidelity check on every chapter present on either side.

    Inputs:
        pdf_chapters (dict): chapter number -> (title, text), PDF side, as
            pdf2md_validate.extract_pdf_chapters returns it.
        output_chapters (dict): same shape, pdf2md output side.
        config (dict): thresholds from load_fidelity_config.

    Outputs:
        dict: {"chapters": {"N": [issue dict, ...]}, "totals": {kind: count},
            "error_count": int, "warning_count": int}.
    --------------------------------------------------------------------------
    """
    report: dict = {"chapters": {}, "totals": {}, "error_count": 0, "warning_count": 0}
    for chapter in sorted(set(pdf_chapters) | set(output_chapters)):
        if chapter not in output_chapters:
            issues = [Issue(chapter, "chapter_missing_in_output", SEVERITY_ERROR, "the PDF has this chapter and the output has no file for it")]
        elif chapter not in pdf_chapters:
            issues = [Issue(chapter, "chapter_missing_in_pdf", SEVERITY_WARNING, "the output has this chapter and the PDF reading did not find it")]
        else:
            pdf_text, output_text = clean_pdf_text(pdf_chapters[chapter][1], config), output_chapters[chapter][1]
            issues = (
                find_embedded_images(chapter, output_text)
                + find_html_residue(chapter, output_text, config)
                + find_image_analysis_issues(chapter, output_text)
                + compare_headings(chapter, pdf_text, output_text, config)
                + compare_paragraphs(chapter, pdf_text, output_text, config)
                + compare_captions(chapter, pdf_text, output_text, config)
                + find_equation_issues(chapter, output_text)
                + compare_citations(chapter, pdf_text, output_text, config)
            )
        report["chapters"][str(chapter)] = [issue.to_dict() for issue in issues]
        for issue in issues:
            report["totals"][issue.kind] = report["totals"].get(issue.kind, 0) + 1
            report["error_count" if issue.severity == SEVERITY_ERROR else "warning_count"] += 1
    return report


def render_fidelity_md(report: dict) -> str:
    """Render a check_chapters report as one markdown table per chapter."""
    lines = [f"Fidelity check: {report['error_count']} error(s), {report['warning_count']} warning(s)", ""]
    for chapter, issues in report["chapters"].items():
        lines.append(f"Chapter {chapter}: {'no issue' if not issues else str(len(issues)) + ' issue(s)'}")
        if not issues:
            lines.append("")
            continue
        lines += ["", "| Kind | Severity | Output line | Detail | PDF excerpt |", "|---|---|---|---|---|"]
        for issue in issues:
            excerpt = issue["pdf_excerpt"].replace("|", "/")
            lines.append(f"| {issue['kind']} | {issue['severity']} | {issue['output_line'] or ''} | {issue['detail'].replace('|', '/')} | {excerpt} |")
        lines.append("")
    return "\n".join(lines)
