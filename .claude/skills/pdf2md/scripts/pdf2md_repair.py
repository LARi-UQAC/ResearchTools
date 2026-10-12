"""
pdf2md_repair - Stage 7d of the pdf2md pipeline: repair the conversion
errors that pdf2md_fidelity finds, so the markdown is usable by a reader or
by thesis-auditor without hand editing.

Four repairs, each one the fix of a defect measured on a real 162-page
thesis (2026-10-11):

1. Embedded images. mineru leaves every figure as a base64 data-URI inside
   the markdown (22 of them, one per figure, thousands of characters each).
   Each is decoded into <out>/assets/figures/ and replaced by a relative
   link, so the figure survives and the text becomes readable again.
2. HTML residue. mineru wraps a page footnote in <small><span ...>. The
   footnote text is kept, the tags are dropped.
3. Lost numbered headings. A heading the PDF has (3.1.1 Introduction, 4.2
   Conclusion du chapitre) and the output lacks is restored: placed before
   the output paragraph that follows it in the PDF, or, when its title
   survived as a plain line, that line is promoted to a heading.
4. Misplaced blocks. A paragraph that sits far from the place it holds in
   the PDF (the chapter's concluding paragraph written before its article)
   is moved to just before the paragraph that follows its predecessor in the
   PDF. A small shift is left alone and reported (a caption next to its
   float is not a misplaced block).

The PDF reader is the guide for headings and order, and nothing else:
paragraph text is never copied from it, since it garbles accented
characters. A restored title is taken from the PDF reading, so a title with
a garbled accent is flagged as suspect in the report rather than trusted.

A state-changing stage (R16): a dry run by default that writes nothing and
reports what it would do, and --yes to write. Before a file is rewritten its
original is copied into <out>/pdf2md-backup/, and a run refuses to start over
an existing backup directory so a second run cannot overwrite the first
run's originals. Exit codes (R12): 0 done, 2 refused by design, 1 failure.
A JSON report is available with --json (R17).
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import pdf2md_fidelity as fidelity  # noqa: E402  (after the sys.path edit above, by design)
import pdf2md_validate as validate  # noqa: E402

_CONFIG_PATH = Path(__file__).with_name("pdf2md-repair.json")
_CONFIG_KEYS = (
    "anchor_lookahead_paragraphs",
    "heading_level_offset",
    "assets_dir_name",
    "figures_dir_name",
    "image_extensions",
    "footnote_pattern",
    "backup_dir_name",
    "garbled_citation_span_max_chars",
    "garbled_span_forbidden",
    "removed_blocks_file",
    "glyph_image_max_bytes",
    "glyph_image_replacement",
)

_BASE64_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\(data:image/(?P<kind>[A-Za-z0-9.+-]+);base64,(?P<data>[A-Za-z0-9+/=\s]+)\)")
_HEADING_HASHES_RE = re.compile(r"^\s*(#+)")
_BLANK_RUN_RE = re.compile(r"\n{3,}")
_MAX_HEADING_LEVEL = 6
_PRIVATE_USE_FIRST, _PRIVATE_USE_LAST = "", ""


class RepairRefused(Exception):
    """The repair refuses to run by design (exit code 2), for example over an existing backup."""


def load_repair_config(path: Path = _CONFIG_PATH) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read this module's settings from pdf2md-repair.json (R0), each key
        carrying a {"value", "provenance"} pair (R4).

    Inputs:
        path (Path): where the config lives; overridable for tests.

    Outputs:
        dict: key -> value for every key in _CONFIG_KEYS.

    Raises:
        FileNotFoundError: the config file is absent.
        KeyError: a required key is missing (R3: the key is named).
    --------------------------------------------------------------------------
    """
    if not path.exists():
        raise FileNotFoundError(f"pdf2md repair config not found at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [key for key in _CONFIG_KEYS if key not in data]
    if missing:
        raise KeyError(f"{path} is missing required config key(s): {missing}")
    return {key: data[key]["value"] for key in _CONFIG_KEYS}


# --------------------------------------------------------------------------- #
# Repairs 1 and 2: embedded images and HTML footnotes.
# --------------------------------------------------------------------------- #


def replace_glyph_images(text: str, config: dict) -> tuple[str, int]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Replace each tiny embedded image (a symbol mineru rasterised, such as
        the end-of-proof square) by its text symbol, so it is neither written
        as a figure file nor counted in the figure numbering.

    Details:
        An image is a glyph when its decoded size is at most
        glyph_image_max_bytes. An image of an unknown type or with undecodable
        data is left exactly as it is, as in extract_embedded_images.

    Inputs:
        text (str): the chapter markdown.
        config (dict): from load_repair_config.

    Outputs:
        (str, int): the new text and the number of images replaced.
    --------------------------------------------------------------------------
    """
    replaced = 0

    def replace(match: re.Match) -> str:
        nonlocal replaced
        if match.group("kind").lower() not in config["image_extensions"]:
            return match.group(0)
        try:
            data = base64.b64decode(re.sub(r"\s+", "", match.group("data")), validate=True)
        except (binascii.Error, ValueError):
            return match.group(0)
        if len(data) > config["glyph_image_max_bytes"]:
            return match.group(0)
        replaced += 1
        return config["glyph_image_replacement"]

    return _BASE64_IMAGE_RE.sub(replace, text), replaced


def extract_embedded_images(text: str, chapter: int, config: dict) -> tuple[str, list[tuple[str, bytes]]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Replace every base64 data-URI image by a relative link to a file the
        caller will write under assets/figures/.

    Details:
        An image whose type is not in image_extensions, or whose data does
        not decode, is left exactly as it is, so nothing is lost; the
        fidelity check keeps reporting it.

    Inputs:
        text (str): the chapter markdown.
        chapter (int): chapter number, used in the generated file names.
        config (dict): from load_repair_config.

    Outputs:
        (str, list[tuple[str, bytes]]): the new text, and (file name, bytes)
            for every image extracted, in order of appearance.
    --------------------------------------------------------------------------
    """
    figures: list[tuple[str, bytes]] = []
    prefix = f"../{config['assets_dir_name']}/{config['figures_dir_name']}"

    def replace(match: re.Match) -> str:
        extension = config["image_extensions"].get(match.group("kind").lower())
        if extension is None:
            return match.group(0)
        try:
            data = base64.b64decode(re.sub(r"\s+", "", match.group("data")), validate=True)
        except (binascii.Error, ValueError):
            return match.group(0)
        name = f"chapter{chapter}_figure{len(figures) + 1}.{extension}"
        figures.append((name, data))
        return f"![{match.group('alt')}]({prefix}/{name})"

    return _BASE64_IMAGE_RE.sub(replace, text), figures


def unwrap_footnotes(text: str, config: dict) -> tuple[str, int]:
    """Replace each page-footnote HTML wrapper by its text, on its own
    paragraph. Returns (new text, number of footnotes unwrapped)."""
    pattern = re.compile(config["footnote_pattern"], re.DOTALL)
    return pattern.subn(lambda match: match.group(1).strip(), text)


def remove_image_analysis_blocks(text: str, chapter: int) -> tuple[str, list[dict]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Take out the <details> blocks mineru wrote under an image: a table of
        approximate values read off a plot, or a sentence describing a
        diagram. They are not in the PDF, and a table of values reads as a
        result of the thesis. The image above each block stays.

    Details:
        Nothing is destroyed: each removed block is returned in full so the
        caller can write it to a side file, with the chapter and the line it
        came from.

    Inputs:
        text (str): the chapter markdown.
        chapter (int): chapter number, recorded with each block.

    Outputs:
        (str, list[dict]): the text without the blocks, and for each block its
            chapter, line, summary title and body.
    --------------------------------------------------------------------------
    """
    matches = fidelity.find_image_analysis_blocks(text)
    if not matches:
        return text, []
    removed = [
        {"chapter": chapter, "line": text.count("\n", 0, match.start()) + 1, "title": match.group("title").strip(), "body": match.group("body").strip()}
        for match in matches
    ]
    pieces, cursor = [], 0
    for match in matches:
        pieces.append(text[cursor : match.start()])
        cursor = match.end()
    pieces.append(text[cursor:])
    return _BLANK_RUN_RE.sub("\n\n", "".join(pieces)), removed


def restore_misread_citations(output_text: str, pdf_text: str, config: dict, fidelity_config: dict) -> tuple[str, list[dict], list[dict]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Put back a citation mineru read as a fragment of mathematics. The
        measured case: "the following holds [14]:" came out as "the following
        holds ${ \\\\sqrt { I } } { \\\\sqrt { J } } .$", so the claim lost its
        source.

    Details:
        Only for a citation the output cites FEWER times than the PDF. The
        place is identified by the five words that precede the citation in the
        PDF: the output span is replaced only when exactly one short math span
        directly follows those same five words, the span holds none of
        garbled_span_forbidden (so it is not a real formula), and it is at most
        garbled_citation_span_max_chars long. Zero or several candidates leave
        the text unchanged and the citation is reported as unplaced.

    Inputs:
        output_text (str): the chapter markdown.
        pdf_text (str): the PDF reader's text for the chapter (cleaned).
        config (dict): from load_repair_config.
        fidelity_config (dict): from pdf2md_fidelity.load_fidelity_config.

    Outputs:
        (str, list[dict], list[dict]): the new text, the citations restored
            ({bracket, replaced}) and those that could not be placed
            ({bracket, reason}).
    --------------------------------------------------------------------------
    """
    occurrences = fidelity.citation_occurrences(pdf_text, fidelity_config)
    deficit = Counter(n for o in occurrences for n in o["numbers"]) - Counter(fidelity.citation_numbers(output_text, fidelity_config))
    if not deficit:
        return output_text, [], []
    span_re = re.compile(r"\$[^$\n]{1,%d}\$" % config["garbled_citation_span_max_chars"])
    restored: list[dict] = []
    unplaced: list[dict] = []
    text = output_text
    for occurrence in occurrences:
        if not any(deficit[n] > 0 for n in occurrence["numbers"]):
            continue
        candidates = []
        for span in span_re.finditer(text):
            if any(token in span.group(0) for token in config["garbled_span_forbidden"]):
                continue
            before = fidelity.strip_math_and_images(text[max(0, span.start() - 300) : span.start()])
            words = [fidelity.fold_letters(w) for w in re.findall(r"[^\W\d_]+", before)][-len(occurrence["words"]) :]
            if occurrence["words"] and words == occurrence["words"]:
                candidates.append(span)
        if len(candidates) != 1:
            unplaced.append({"bracket": occurrence["bracket"], "reason": f"{len(candidates)} math spans follow the same five words"})
            continue
        span = candidates[0]
        text = text[: span.start()] + occurrence["bracket"] + occurrence["after"] + text[span.end() :]
        restored.append({"bracket": occurrence["bracket"], "replaced": span.group(0)})
        for number in occurrence["numbers"]:
            deficit[number] -= 1
    # An occurrence already intact in the output also looks "unplaced" while the
    # deficit is still open; once the deficit is settled it is no finding.
    unplaced = [u for u in unplaced if any(deficit[n] > 0 for n in map(int, re.findall(r"\d+", u["bracket"])))]
    return text, restored, unplaced


def normalize_equation_numbers(text: str) -> tuple[str, int]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Write as a tag the equation numbers mineru left as text at the end of
        a display equation (`, (3. 2 5)` becomes `, \\tag {3.25}`), so the
        numbering is uniform and checkable. The equation itself is not touched.

    Inputs:
        text (str): the chapter markdown.

    Outputs:
        (str, int): the new text and how many numbers were rewritten.
    --------------------------------------------------------------------------
    """
    count = 0

    def rewrite(match: re.Match) -> str:
        nonlocal count
        body = match.group("body")
        if fidelity._TAG_RE.search(body):
            return match.group(0)
        stripped = body.rstrip()
        trailing = fidelity._TRAILING_NUMBER_RE.search(stripped)
        if not trailing:
            return match.group(0)
        number = f"{trailing.group('chapter')}.{re.sub(r'\s+', '', trailing.group('index'))}"
        count += 1
        comma = "," if trailing.group("lead").strip().startswith(",") else ""
        return "$$" + stripped[: trailing.start()].rstrip() + comma + " \\tag {" + number + "}\n$$"

    return fidelity._DISPLAY_RE.sub(rewrite, text), count


# --------------------------------------------------------------------------- #
# Repair 3: lost numbered headings.
# --------------------------------------------------------------------------- #


def _heading_levels(text: str, headings: list[fidelity.Heading]) -> dict[int, int]:
    """The markdown level used by the output's own numbered headings, by depth."""
    lines = text.splitlines()
    levels: dict[int, int] = {}
    for heading in headings:
        if heading.number is not None:
            levels.setdefault(len(heading.number), len(_HEADING_HASHES_RE.match(lines[heading.line - 1]).group(1)))
    return levels


def _heading_line(heading: fidelity.Heading, levels: dict[int, int], config: dict) -> str:
    depth = len(heading.number)
    level = min(levels.get(depth, depth + config["heading_level_offset"]), _MAX_HEADING_LEVEL)
    return f"{'#' * level} {'.'.join(str(part) for part in heading.number)} {heading.title}"


def _title_is_suspect(title: str) -> bool:
    return any(char == "�" or _PRIVATE_USE_FIRST <= char <= _PRIVATE_USE_LAST for char in title)


def restore_headings(output_text: str, pdf_text: str, config: dict, fidelity_config: dict) -> tuple[str, list[dict], list[dict]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Put back the numbered headings the PDF has and the output lost.

    Details:
        A heading whose title survives as a plain line is promoted in place.
        Otherwise it is inserted before the output paragraph that holds the
        first comparable PDF paragraph following it (looking at most
        anchor_lookahead_paragraphs ahead). A heading with no such anchor is
        reported as unplaced and nothing is written for it. Only numbered
        headings are restored: an unnumbered one is a font-size guess by the
        PDF reader and is not trusted as a heading.

    Inputs:
        output_text (str): the chapter markdown.
        pdf_text (str): the PDF reader's text for the chapter.
        config (dict): from load_repair_config.
        fidelity_config (dict): from pdf2md_fidelity.load_fidelity_config.

    Outputs:
        (str, list[dict], list[dict]): the new text, the headings restored
            (number, title, level, method, line, title_suspect), and the
            headings that could not be placed (number, title, reason).
    --------------------------------------------------------------------------
    """
    pdf_headings = [heading for heading in fidelity.extract_headings(pdf_text) if heading.number is not None]
    output_headings = fidelity.extract_headings(output_text)
    present = {heading.number for heading in output_headings if heading.number is not None}
    missing = [heading for heading in pdf_headings if heading.number not in present]
    if not missing:
        return output_text, [], []

    levels = _heading_levels(output_text, output_headings)
    pdf_paragraphs = [
        paragraph
        for paragraph in fidelity.drop_running_headers(fidelity.split_paragraphs(pdf_text), min_repeats=fidelity_config["running_header_min_repeats"])
        if not fidelity.is_pdf_noise(paragraph, fidelity_config["pdf_noise_markers"])
    ]
    output_paragraphs = fidelity.split_paragraphs(fidelity.strip_math_and_images(output_text))
    index = fidelity.index_paragraphs(output_paragraphs, fidelity_config)

    lines = output_text.split("\n")
    promotions: dict[int, str] = {}
    insertions: dict[int, list[str]] = {}
    restored: list[dict] = []
    unplaced: list[dict] = []
    for heading in missing:
        text = _heading_line(heading, levels, config)
        label = ".".join(str(part) for part in heading.number)
        record = {"number": label, "title": heading.title, "level": text.index(" "), "title_suspect": _title_is_suspect(heading.title)}
        plain = fidelity.plain_text_line(output_text, heading.title)
        if plain:
            promotions[plain - 1] = text
            restored.append({**record, "method": "promote_plain_line", "line": plain})
            continue
        anchor = None
        for paragraph in [p for p in pdf_paragraphs if p.line > heading.line][: config["anchor_lookahead_paragraphs"]]:
            position = fidelity.locate_paragraph(paragraph, index, fidelity_config)
            if position is not None:
                anchor = output_paragraphs[position].line - 1
                break
        if anchor is None:
            unplaced.append({"number": label, "title": heading.title, "reason": "no paragraph following the heading in the PDF could be located in the output"})
            continue
        insertions.setdefault(anchor, []).extend([text, ""])
        restored.append({**record, "method": "insert", "line": anchor + 1})

    for line_index, text in promotions.items():
        lines[line_index] = text
    for anchor in sorted(insertions, reverse=True):
        block = insertions[anchor]
        if anchor > 0 and lines[anchor - 1].strip():
            block = [""] + block
        lines[anchor:anchor] = block
    return "\n".join(lines), restored, unplaced


# --------------------------------------------------------------------------- #
# Repair 4: misplaced blocks.
# --------------------------------------------------------------------------- #


def _segments(text: str, paragraphs: list[fidelity.Paragraph]) -> list[dict]:
    """Cut text into segments: each paragraph (pid = its position) and each
    run of lines between paragraphs (pid None: blank lines, formulas)."""
    lines = text.split("\n")
    segments: list[dict] = []
    cursor = 0
    for position, paragraph in enumerate(paragraphs):
        start = paragraph.line - 1
        if start > cursor:
            segments.append({"pid": None, "lines": lines[cursor:start]})
        segments.append({"pid": position, "lines": lines[start : paragraph.end]})
        cursor = paragraph.end
    if cursor < len(lines):
        segments.append({"pid": None, "lines": lines[cursor:]})
    return segments


def _place(segments: list[dict], moved: dict, *, after_pid: int | None, before_pid: int | None) -> None:
    """Insert the moved paragraph segment right before the paragraph that
    follows after_pid (its trailing run of formulas stays attached to it), or
    right before before_pid when there is no predecessor."""
    if after_pid is not None:
        position = next(i for i, segment in enumerate(segments) if segment["pid"] == after_pid) + 1
        while position < len(segments) and segments[position]["pid"] is None:
            position += 1
    else:
        position = next(i for i, segment in enumerate(segments) if segment["pid"] == before_pid)
    segments[position:position] = [moved, {"pid": None, "lines": [""]}]


def _keep_edges(original: str, rebuilt: str) -> str:
    """Give the rebuilt text the same leading and trailing blank lines as the
    original: moving a paragraph out of the first or last place leaves an
    empty run behind that was never there."""
    leading = len(original) - len(original.lstrip("\n"))
    trailing = len(original) - len(original.rstrip("\n"))
    return "\n" * leading + rebuilt.strip("\n") + "\n" * trailing


def restore_order(output_text: str, pdf_text: str, config: dict, fidelity_config: dict) -> tuple[str, list[dict], list[dict]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Move paragraphs that sit far from their place in the PDF back to it.

    Details:
        Which paragraphs are displaced comes from pdf2md_fidelity's own
        alignment (the paragraphs outside one longest in-order run), so this
        repair and the check that reports the defect cannot disagree. A
        displaced paragraph goes just before the paragraph that follows its
        nearest in-order predecessor in the PDF. A paragraph that sits fewer
        than the fidelity config's out_of_order_min_displacement paragraphs
        from its place is left alone and reported as skipped. Only prose paragraphs move: a formula
        block between two paragraphs stays where it is.

    Inputs:
        output_text (str): the chapter markdown.
        pdf_text (str): the PDF reader's text for the chapter.
        config (dict): from load_repair_config.
        fidelity_config (dict): from pdf2md_fidelity.load_fidelity_config.

    Outputs:
        (str, list[dict], list[dict]): the new text, the moves made (from_line,
            displacement, excerpt) and the moves skipped as too small.
    --------------------------------------------------------------------------
    """
    alignment = fidelity.align_paragraphs(pdf_text, output_text, fidelity_config)
    if not alignment.keep or len(alignment.keep) == len(alignment.matched):
        return output_text, [], []
    output_paragraphs = [paragraph for paragraph, _print in alignment.output_prints]
    kept_positions = {alignment.matched[i][1] for i in alignment.keep}
    kept_order = sorted(alignment.keep)

    plans: list[tuple[int, int | None, int, dict]] = []
    skipped: list[dict] = []
    seen: set[int] = set()
    for index, (paragraph, position) in enumerate(alignment.matched):
        if index in alignment.keep or position in kept_positions or position in seen:
            continue
        seen.add(position)
        predecessors = [k for k in kept_order if k < index]
        after = alignment.matched[predecessors[-1]][1] if predecessors else None
        record = {"from_line": output_paragraphs[position].line, "displacement": alignment.displacement[index], "excerpt": paragraph.text[:80]}
        if record["displacement"] < fidelity_config["out_of_order_min_displacement"]:
            skipped.append(record)
            continue
        plans.append((position, after, alignment.matched[kept_order[0]][1], record))

    if not plans:
        return output_text, [], skipped
    segments = _segments(output_text, output_paragraphs)
    last_placed: dict[int, int] = {}
    for position, after, first_kept, _record in plans:
        moved = segments.pop(next(i for i, segment in enumerate(segments) if segment["pid"] == position))
        # Several displaced paragraphs can share one predecessor: each goes
        # after the one placed before it, so their PDF order is kept.
        _place(segments, moved, after_pid=last_placed.get(after, after) if after is not None else None, before_pid=first_kept)
        if after is not None:
            last_placed[after] = position
    joined = "\n".join(line for segment in segments for line in segment["lines"])
    return _keep_edges(output_text, _BLANK_RUN_RE.sub("\n\n", joined)), [record for _p, _a, _f, record in plans], skipped


# --------------------------------------------------------------------------- #
# One chapter, then the whole output directory.
# --------------------------------------------------------------------------- #


def repair_chapter(chapter: int, pdf_text: str, output_text: str, config: dict, fidelity_config: dict) -> tuple[str, list[tuple[str, bytes]], dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Apply the four repairs to one chapter, in the order that keeps each
        one valid: images and footnotes first (they only shorten the text),
        then block order, then headings (which anchor on the reordered text).

    Inputs:
        chapter (int): chapter number.
        pdf_text (str): the PDF reader's text for the chapter.
        output_text (str): the chapter markdown.
        config (dict): from load_repair_config.
        fidelity_config (dict): from pdf2md_fidelity.load_fidelity_config.

    Outputs:
        (str, list[tuple[str, bytes]], dict): the repaired text, the figure
            files to write, and a report dict (images, footnotes, headings,
            unplaced_headings, moves, skipped_moves).
    --------------------------------------------------------------------------
    """
    text, removed_blocks = remove_image_analysis_blocks(output_text, chapter)
    text, glyphs = replace_glyph_images(text, config)
    text, figures = extract_embedded_images(text, chapter, config)
    text, footnotes = unwrap_footnotes(text, config)
    text, equations = normalize_equation_numbers(text)
    clean_pdf = fidelity.clean_pdf_text(pdf_text, fidelity_config)
    text, citations, citations_unplaced = restore_misread_citations(text, clean_pdf, config, fidelity_config)
    text, moves, skipped = restore_order(text, clean_pdf, config, fidelity_config)
    text, headings, unplaced = restore_headings(text, clean_pdf, config, fidelity_config)
    info = {
        "citations_restored": citations,
        "citations_unplaced": citations_unplaced,
        "images": [name for name, _data in figures],
        "glyph_images_replaced": glyphs,
        "footnotes": footnotes,
        "analysis_blocks_removed": removed_blocks,
        "equation_numbers_fixed": equations,
        "headings": headings,
        "unplaced_headings": unplaced,
        "moves": moves,
        "skipped_moves": skipped,
    }
    return text, figures, info


def repair_output(
    pdf_chapters: dict[int, tuple[str, str]], output_dir: Path, config: dict, fidelity_config: dict, *, apply: bool
) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Repair every chapter file of an output directory, and with apply=True
        write the result.

    Details:
        The fidelity check is run on each chapter before and after, so the
        report states what the repair actually fixed (R9: the effect is
        measured, not assumed). With apply=True the original of every
        rewritten file is first copied into the backup directory.

    Inputs:
        pdf_chapters (dict): chapter -> (title, text), from validate.extract_pdf_chapters.
        output_dir (Path): the pdf2md output directory (holds content/).
        config (dict): from load_repair_config.
        fidelity_config (dict): from pdf2md_fidelity.load_fidelity_config.
        apply (bool): write the repaired files and figures.

    Outputs:
        dict: {"applied", "chapters": {"N": {...info, errors_before, errors_after}},
            "errors_before", "errors_after", "files_written"}.

    Raises:
        RepairRefused: apply is set and the backup directory already holds files,
            or an image file to write already exists with different content.
    --------------------------------------------------------------------------
    """
    output_dir = Path(output_dir)
    backup_dir = output_dir / config["backup_dir_name"]
    figures_dir = output_dir / config["assets_dir_name"] / config["figures_dir_name"]
    if apply and backup_dir.exists() and any(backup_dir.iterdir()):
        raise RepairRefused(f"{backup_dir} already holds the originals of an earlier repair; move it aside first so they are not overwritten")

    report: dict = {"applied": apply, "chapters": {}, "errors_before": 0, "errors_after": 0, "files_written": [], "analysis_blocks_removed": 0}
    writes: list[tuple[Path, str]] = []
    figure_writes: list[tuple[Path, bytes]] = []
    removed_blocks: list[dict] = []
    for chapter, (stem, text) in sorted(validate.load_output_chapters(output_dir).items()):
        if chapter not in pdf_chapters:
            report["chapters"][str(chapter)] = {"skipped": "the PDF reading has no such chapter"}
            continue
        pdf_text = pdf_chapters[chapter][1]
        new_text, figures, info = repair_chapter(chapter, pdf_text, text, config, fidelity_config)
        info["errors_before"] = fidelity.check_chapters({chapter: pdf_chapters[chapter]}, {chapter: (stem, text)}, fidelity_config)["error_count"]
        info["errors_after"] = fidelity.check_chapters({chapter: pdf_chapters[chapter]}, {chapter: (stem, new_text)}, fidelity_config)["error_count"]
        report["errors_before"] += info["errors_before"]
        report["errors_after"] += info["errors_after"]
        report["chapters"][str(chapter)] = info
        if new_text != text:
            writes.append((output_dir / "content" / f"{stem}.md", new_text))
        figure_writes += [(figures_dir / name, data) for name, data in figures]
        removed_blocks += info["analysis_blocks_removed"]

    if removed_blocks:
        figure_writes.append((output_dir / config["assets_dir_name"] / config["removed_blocks_file"], render_removed_blocks(removed_blocks).encode("utf-8")))
        report["analysis_blocks_removed"] = len(removed_blocks)

    if apply:
        for path, data in figure_writes:
            if path.exists() and path.read_bytes() != data:
                raise RepairRefused(f"{path} already exists with different content; nothing was written")
        for path, new_text in writes:
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_dir / path.name)
            _write_atomic(path, new_text.encode("utf-8"))
            report["files_written"].append(str(path))
        for path, data in figure_writes:
            path.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(path, data)
            report["files_written"].append(str(path))
    return report


def render_removed_blocks(blocks: list[dict]) -> str:
    """The side file that keeps every removed image-analysis block, so
    removing them from the chapters loses nothing."""
    lines = [
        "# Image analysis written by mineru and removed from the chapters",
        "",
        "Each block below sits under an image in the converted chapter and is NOT in the PDF:",
        "a table of values read off a plot (approximate) or a description of a diagram.",
        "The image itself stays in the chapter. Nothing here is a result of the thesis.",
        "",
    ]
    for block in blocks:
        lines += [f"## Chapter {block['chapter']}, line {block['line']}, summary '{block['title']}'", "", block["body"], ""]
    return "\n".join(lines)


def _write_atomic(path: Path, data: bytes) -> None:
    """Write through a sibling temp file and replace, so a crash never leaves a half-written file."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def render_repair_md(report: dict) -> str:
    """Render a repair_output report as one summary table."""
    if report["applied"]:
        headline = f"Repair: fidelity errors {report['errors_before']} -> {report['errors_after']}; wrote {len(report['files_written'])} file(s)"
    else:
        headline = f"Repair (dry run, nothing written): fidelity errors {report['errors_before']} -> {report['errors_after']}"
    lines = [
        headline,
        "",
        "| Chapter | Images extracted | Footnotes unwrapped | Analysis blocks removed | Equation numbers fixed | Headings restored | Headings unplaced | Blocks moved | Moves skipped | Errors before | Errors after |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for chapter, info in report["chapters"].items():
        if "skipped" in info:
            lines.append(f"| {chapter} | - | - | - | - | - | - | - | - | - | {info['skipped']} |")
            continue
        lines.append(
            f"| {chapter} | {len(info['images'])} | {info['footnotes']} | {len(info['analysis_blocks_removed'])} | {info['equation_numbers_fixed']} | {len(info['headings'])} | {len(info['unplaced_headings'])} | {len(info['moves'])} | {len(info['skipped_moves'])} | {info['errors_before']} | {info['errors_after']} |"
        )
    return "\n".join(lines)


def _main(argv: list[str] | None = None) -> int:
    import argparse

    validate.extract_text.configure_streams()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_path")
    parser.add_argument("-o", "--output-dir", required=True)
    parser.add_argument("--yes", action="store_true", help="write the repaired files (default: a dry run that writes nothing)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        report = repair_output(
            validate.extract_pdf_chapters(args.pdf_path), Path(args.output_dir), load_repair_config(), fidelity.load_fidelity_config(), apply=args.yes
        )
    except RepairRefused as exc:
        print(f"[REPAIR] refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report) if args.json else render_repair_md(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
