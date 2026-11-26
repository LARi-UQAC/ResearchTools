"""
Purpose: Rebuild a table drawn as an image as Markdown from the word boxes of its OCR (spec E3, plan 8).
Details: Words are grouped into rows when their boxes overlap vertically, and each row is split into cells at the
    horizontal gaps of at least the configured width. A row shorter than the widest one is padded with empty cells.
    Nothing here runs OCR: the caller supplies the word boxes, so the module is tested without Tesseract.
Pipeline stage: work-ugs-audit, page text preparation (issue 126).
"""
import json
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Sequence, Tuple

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "assets" / "ugs_config.json"
GAP_KEY = "tables.image_column_gap_pt"
MIN_ROWS_KEY = "tables.image_min_rows"
OVERLAP_KEY = "tables.image_row_overlap_ratio"
UNTITLED_ROWS_KEY = "tables.untitled_min_rows"
UNTITLED_COLS_KEY = "tables.untitled_min_cols"
TITLED_ROWS_KEY = "tables.titled_min_rows"  # review D: the grid rule of a titled figure
TITLED_COLS_KEY = "tables.titled_min_cols"


class ImageSettings(NamedTuple):
    """The configuration of a table drawn as an image: gap, minimum rows and row overlap ratio."""

    column_gap_pt: float
    min_rows: int
    row_overlap_ratio: float


class TableImageError(Exception):
    """A configuration value needed to rebuild a table drawn as an image is missing or invalid."""


class TableImageUnreadable(Exception):
    """A table drawn as an image yields no usable rows; the message gives the reason, never the words."""


def _read_entry(raw: Any, key: str, source: Path) -> Any:
    """
    Purpose: Return the value of one configuration key, refusing a missing or malformed entry by name.
    Inputs:
        raw: Any - the parsed configuration (expected to be a JSON object).
        key: str - the dotted key to read.
        source: Path - the file the configuration came from, named in the refusal.
    Outputs:
        Any - the value under the key's "value" field.
    Raises:
        TableImageError: If the file is not a JSON object, or the key or its value field is missing.
    """
    entry = raw.get(key) if isinstance(raw, dict) else None
    if not isinstance(entry, dict) or "value" not in entry:
        raise TableImageError(f"missing or invalid key '{key}' in {source.name}")
    return entry["value"]


def load_image_settings(path: Optional[Path] = None) -> ImageSettings:
    """
    Purpose: Read the column gap, the minimum row count and the row overlap ratio of a table drawn as an image.
    Inputs:
        path: Optional[Path] - the configuration file; None means the work-ugs-audit assets file.
    Outputs:
        ImageSettings - the gap in points (positive), the minimum rows (positive integer) and the overlap ratio
            (above 0 and at most 1).
    Raises:
        TableImageError: If the file is unreadable, or a key is missing or not a valid value.
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TableImageError(f"configuration {config_path.name} is not readable JSON: {exc}") from None
    gap = _read_entry(raw, GAP_KEY, config_path)
    min_rows = _read_entry(raw, MIN_ROWS_KEY, config_path)
    overlap = _read_entry(raw, OVERLAP_KEY, config_path)
    if isinstance(gap, bool) or not isinstance(gap, (int, float)) or gap <= 0:
        raise TableImageError(f"key '{GAP_KEY}' in {config_path.name} must be a positive number")
    if isinstance(min_rows, bool) or not isinstance(min_rows, int) or min_rows <= 0:
        raise TableImageError(f"key '{MIN_ROWS_KEY}' in {config_path.name} must be a positive integer")
    if isinstance(overlap, bool) or not isinstance(overlap, (int, float)) or not 0 < overlap <= 1:
        raise TableImageError(f"key '{OVERLAP_KEY}' in {config_path.name} must be a number above 0 and at most 1")
    return ImageSettings(float(gap), min_rows, float(overlap))


def _usable(words: Sequence[tuple]) -> List[tuple]:
    """
    Purpose: Keep the words that carry visible text, after collapsing their whitespace.
    Inputs:
        words: Sequence[tuple] - PyMuPDF word tuples (x0, y0, x1, y1, text, ...).
    Outputs:
        List[tuple] - the words whose text is not blank.
    Raises:
        None.
    """
    return [word for word in words if " ".join(str(word[4]).split())]


def _group_lines(words: List[tuple], row_overlap_ratio: float) -> List[Dict[str, Any]]:
    """
    Purpose: Group words into lines, a word joining a line when their boxes overlap vertically enough.
    Inputs:
        words: List[tuple] - usable word tuples.
        row_overlap_ratio: float - the share of the smaller box height that two boxes must overlap.
    Outputs:
        List[Dict[str, Any]] - one dict per line with keys y0, y1 and words, in top-to-bottom order.
    Raises:
        None.
    """
    lines: List[Dict[str, Any]] = []
    for word in sorted(words, key=lambda item: (item[1], item[0])):
        placed = False
        for line in lines:
            overlap = min(word[3], line["y1"]) - max(word[1], line["y0"])
            height = min(word[3] - word[1], line["y1"] - line["y0"])
            if height > 0 and overlap >= row_overlap_ratio * height:
                line["words"].append(word)
                line["y0"] = min(line["y0"], word[1])
                line["y1"] = max(line["y1"], word[3])
                placed = True
                break
        if not placed:
            lines.append({"y0": word[1], "y1": word[3], "words": [word]})
    return sorted(lines, key=lambda line: line["y0"])


def _cells(line_words: List[tuple], column_gap_pt: float) -> List[str]:
    """
    Purpose: Split the words of one row into cells at the horizontal gaps of at least column_gap_pt.
    Inputs:
        line_words: List[tuple] - the words of one row.
        column_gap_pt: float - the gap that starts a new cell, in points.
    Outputs:
        List[str] - the text of each cell, left to right, words joined by one space.
    Raises:
        None.
    """
    ordered = sorted(line_words, key=lambda item: item[0])
    groups: List[List[tuple]] = [[ordered[0]]]
    for previous, word in zip(ordered, ordered[1:]):
        if word[0] - previous[2] >= column_gap_pt:
            groups.append([word])
        else:
            groups[-1].append(word)
    return [" ".join(" ".join(str(item[4]).split()) for item in group) for group in groups]


def words_to_rows(words: Sequence[tuple], column_gap_pt: float, row_overlap_ratio: float) -> List[List[str]]:
    """
    Purpose: Turn the word boxes of a table drawn as an image into rows of cell texts.
    Details: A column is a run of words with no gap of column_gap_pt or more. The columns are not aligned
        across rows: a row with an empty cell in its middle shifts its later cells, which is a stated limit.
    Inputs:
        words: Sequence[tuple] - PyMuPDF word tuples (x0, y0, x1, y1, text, ...) of one region.
        column_gap_pt: float - the gap that starts a new column, in points.
        row_overlap_ratio: float - the vertical overlap, as a share of the smaller box, that joins two words in one row.
    Outputs:
        List[List[str]] - the rows, top to bottom, each a list of cell texts; empty when no word has text.
    Raises:
        None.
    """
    usable = _usable(words)
    if not usable:
        return []
    return [_cells(line["words"], column_gap_pt) for line in _group_lines(usable, row_overlap_ratio)]


def _markdown_cell(text: str) -> str:
    """
    Purpose: Escape one cell text for a Markdown table, so that a pipe cannot open a new column.
    Inputs:
        text: str - the cell text.
    Outputs:
        str - the text with every pipe escaped.
    Raises:
        None.
    """
    return text.replace("|", "\\|")


def words_to_markdown(words: Sequence[tuple], column_gap_pt: float, min_rows: int, row_overlap_ratio: float) -> str:
    """
    Purpose: Build the Markdown of a table drawn as an image, its first row used as the header.
    Inputs:
        words: Sequence[tuple] - PyMuPDF word tuples of the region.
        column_gap_pt: float - the gap that starts a new column, in points.
        min_rows: int - the fewest rows that make a table.
        row_overlap_ratio: float - the vertical overlap that joins two words in one row.
    Outputs:
        str - the Markdown table, lines joined by a newline; rows shorter than the widest are padded.
    Raises:
        TableImageUnreadable: If the region has fewer than min_rows rows, with the count as the reason.
    """
    rows = words_to_rows(words, column_gap_pt, row_overlap_ratio)
    if len(rows) < min_rows:
        raise TableImageUnreadable(f"{len(rows)} rows found, {min_rows} needed")
    width = max(len(row) for row in rows)
    padded = [[_markdown_cell(cell) for cell in row] + [""] * (width - len(row)) for row in rows]
    lines = ["| " + " | ".join(padded[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in padded[1:]]
    return "\n".join(lines)


UNTITLED_FIGURE = "figure"
UNTITLED_TABLE = "table_image"


def classify_untitled(words: Sequence[tuple], column_gap_pt: float, min_rows: int, min_cols: int,
                      row_overlap_ratio: float) -> str:
    """
    Purpose: Decide whether an untitled region is a table drawn as an image (plan 11, spec E5).
    Details: The region is a table when its OCR words rebuild a grid of at least min_rows rows and min_cols columns,
        the rows and columns being those words_to_rows gives: at least min_rows rows that each reach min_cols
        non-empty cells, so a diagram whose labels make ragged rows stays a figure. Nothing here runs OCR.
    Inputs:
        words: Sequence[tuple] - PyMuPDF word tuples of the region (x0, y0, x1, y1, text, ...).
        column_gap_pt: float - the gap that starts a new column, in points.
        min_rows: int - the fewest rows that make a table.
        min_cols: int - the fewest columns that make a table (the widest row).
        row_overlap_ratio: float - the vertical overlap that joins two words in one row.
    Outputs:
        str - "table_image" or "figure".
    Raises:
        None.
    """
    rows = words_to_rows(words, column_gap_pt, row_overlap_ratio)
    full_rows = sum(1 for row in rows if sum(1 for cell in row if cell.strip()) >= min_cols)
    if full_rows >= min_rows:
        return UNTITLED_TABLE
    return UNTITLED_FIGURE


def load_titled_settings(path: Optional[Path] = None) -> Tuple[int, int]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the minimum rows and columns of a grid that makes a titled figure a table (review D of plan 20).

    Inputs:
        path (Path | None): the configuration file; None means the work-ugs-audit assets file.

    Outputs:
        Tuple[int, int]: the minimum rows and the minimum columns, both positive integers.

    Raises:
        TableImageError: when the file is unreadable, or a key is missing or not a positive integer (the key is named).
    --------------------------------------------------------------------------
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TableImageError(f"configuration {config_path.name} is not readable JSON: {exc}") from None
    values = []
    for key in (TITLED_ROWS_KEY, TITLED_COLS_KEY):
        value = _read_entry(raw, key, config_path)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise TableImageError(f"key '{key}' in {config_path.name} must be a positive integer")
        values.append(value)
    return values[0], values[1]


def load_untitled_settings(path: Optional[Path] = None) -> Tuple[int, int]:
    """
    Purpose: Read the minimum rows and columns of an untitled table drawn as an image (plan 11, spec E5).
    Inputs:
        path: Optional[Path] - the configuration file; None means the work-ugs-audit assets file.
    Outputs:
        Tuple[int, int] - the minimum rows and the minimum columns, both positive integers.
    Raises:
        TableImageError: If the file is unreadable, or a key is missing or not a positive integer (the key is named).
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TableImageError(f"configuration {config_path.name} is not readable JSON: {exc}") from None
    values = []
    for key in (UNTITLED_ROWS_KEY, UNTITLED_COLS_KEY):
        value = _read_entry(raw, key, config_path)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise TableImageError(f"key '{key}' in {config_path.name} must be a positive integer")
        values.append(value)
    return values[0], values[1]
