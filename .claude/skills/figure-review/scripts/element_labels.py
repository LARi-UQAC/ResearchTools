"""
Purpose: Find the title, the legend and the notes of a figure or a table on a page (spec R2).
Pure: text blocks and words in, labels out. The element extractor calls these functions.
Pipeline stage: figure-review, element extraction (plan 2 of issue 122).
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_MARKERS_PATH = Path(__file__).resolve().parent.parent / "assets" / "element_markers.json"

# Prefix lists the markers file must carry (R3: a missing key is a named error).
PREFIX_KEYS = ("figure_prefixes", "table_prefixes", "note_prefixes")
# Numeric entries, each {"value": number, "provenance": str} (R4).
NUMERIC_KEYS = ("max_title_distance_pt", "max_note_distance_pt", "centre_tolerance_ratio", "column_min_words")

# Element type to the prefix list it must start with.
ELEMENT_PREFIX_KEYS = {"figure": "figure_prefixes", "table": "table_prefixes"}
# Direction order: a figure title is usually below its figure, a table title above its table.
ELEMENT_DIRECTIONS = {"figure": ("below", "above"), "table": ("above", "below")}
POSITION_BELOW = "below"
POSITION_ABOVE = "above"
ALIGN_LEFT = "left"
ALIGN_CENTER = "center"
ALIGN_RIGHT = "right"
TEXT_BLOCK_TYPE = 0


class MarkerError(ValueError):
    """Raised when the element markers file is missing, unreadable or incomplete."""


def _marker_value(markers: Dict[str, Any], key: str) -> float:
    """
    Purpose: Read the numeric value of a {value, provenance} entry, naming the key if absent.
    Inputs:
        markers: Dict[str, Any] - the markers returned by load_markers.
        key: str - the entry name.
    Outputs:
        float - the value stored under the entry.
    Raises:
        MarkerError: If the entry or its value is missing.
    """
    entry = markers.get(key)
    if not isinstance(entry, dict) or "value" not in entry:
        raise MarkerError(f"element markers: key '{key}' with a 'value' is missing")
    return float(entry["value"])


def _marker_prefixes(markers: Dict[str, Any], key: str) -> List[str]:
    """
    Purpose: Read a prefix list from the markers, naming the key if absent.
    Inputs:
        markers: Dict[str, Any] - the markers returned by load_markers.
        key: str - the list name.
    Outputs:
        List[str] - the prefixes.
    Raises:
        MarkerError: If the list is missing.
    """
    prefixes = markers.get(key)
    if not isinstance(prefixes, list):
        raise MarkerError(f"element markers: key '{key}' (a list of prefixes) is missing")
    return prefixes


def _is_number(value: Any) -> bool:
    """
    Purpose: Tell a real number from a boolean, which is a subclass of int in Python.
    Inputs:
        value: Any - the value to test.
    Outputs:
        bool - True for an int or a float that is not a boolean.
    Raises:
        None.
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate_markers(data: Dict[str, Any], source: Path) -> None:
    """
    Purpose: Check every required key of the markers data, naming the key and the file on failure.
    Inputs:
        data: Dict[str, Any] - the parsed JSON object.
        source: Path - the file it came from, named in each message.
    Outputs:
        None. Returns normally when the data is complete.
    Raises:
        MarkerError: If a key is missing, a prefix list is empty or malformed, or a value is not a
            non-negative number with a provenance (the ratio must lie between 0 and 1).
    """
    for key in PREFIX_KEYS:
        values = data.get(key)
        if not isinstance(values, list) or not values:
            raise MarkerError(f"{source}: key '{key}' must be a non-empty list of prefixes")
        if not all(isinstance(v, str) and v.strip() for v in values):
            raise MarkerError(f"{source}: key '{key}' holds an empty or non-text prefix")
    for key in NUMERIC_KEYS:
        entry = data.get(key)
        if not isinstance(entry, dict):
            raise MarkerError(f"{source}: key '{key}' is missing (expected value and provenance)")
        if "value" not in entry:
            raise MarkerError(f"{source}: key '{key}' has no 'value'")
        if not _is_number(entry["value"]) or entry["value"] < 0:
            raise MarkerError(f"{source}: key '{key}' value must be a number of 0 or more")
        if not isinstance(entry.get("provenance"), str) or not entry["provenance"].strip():
            raise MarkerError(f"{source}: key '{key}' has no provenance")
    if data["centre_tolerance_ratio"]["value"] > 1:
        raise MarkerError(f"{source}: key 'centre_tolerance_ratio' must lie between 0 and 1")


def load_markers(path: Path) -> Dict[str, Any]:
    """
    Purpose: Load and validate the element markers data file (marker words and distances, R0 and R6).
    Inputs:
        path: Path - the JSON file to read.
    Outputs:
        Dict[str, Any] - the parsed data with the keys figure_prefixes, table_prefixes,
            note_prefixes, and max_title_distance_pt, max_note_distance_pt,
            centre_tolerance_ratio as {value, provenance}.
    Raises:
        MarkerError: If the file is missing, is not JSON, or lacks or malforms a required key.
    """
    source = Path(path)
    if not source.exists():
        raise MarkerError(f"element markers file not found: {source}")
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarkerError(f"element markers file {source} is not readable JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise MarkerError(f"element markers file {source} must hold a JSON object")
    _validate_markers(data, source)
    return data


def _clean(text: str) -> str:
    """
    Purpose: Collapse every run of whitespace, line breaks included, into one space.
    Inputs:
        text: str - the raw block text.
    Outputs:
        str - the normalised text, stripped at both ends.
    Raises:
        None.
    """
    return " ".join(text.split())


def _starts_with_marker(text: str, prefixes: List[str]) -> bool:
    """
    Purpose: Tell whether a text opens with one of the marker words, case-insensitively.
    Inputs:
        text: str - the cleaned block text.
        prefixes: List[str] - the marker words.
    Outputs:
        bool - True when a prefix matches and, for a word-like prefix, ends at a word boundary,
            so that "Table" does not match "Tableau".
    Raises:
        None.
    """
    folded = text.casefold()
    for prefix in prefixes:
        marker = prefix.strip().casefold()
        if not marker or not folded.startswith(marker):
            continue
        rest = folded[len(marker):]
        if not marker[-1].isalnum() or not rest or not rest[0].isalnum():
            return True
    return False


def _overlaps(block: tuple, rect: "fitz.Rect") -> bool:
    """
    Purpose: Tell whether a block lies, even partly, inside the element rectangle.
    Inputs:
        block: tuple - a block tuple (x0, y0, x1, y1, ...).
        rect: fitz.Rect - the element rectangle.
    Outputs:
        bool - True when the two rectangles share an area.
    Raises:
        None.
    """
    return block[0] < rect.x1 and block[2] > rect.x0 and block[1] < rect.y1 and block[3] > rect.y0


def lines_alignment(lines: List[tuple], rect: "fitz.Rect", tolerance_ratio: float) -> Optional[str]:
    """
    Purpose: Measure a title from its own lines against the element edges (owner, 2026-11-27, plan 28): a line is
        centred when its left gap and its right gap to the element differ by no more than the tolerance; the title
        is "center" when its last line is centred, "left" when its first line starts within the tolerance of the
        element left edge, and "right" otherwise. A single line spanning the width is "center".
    Details: The tolerance is tolerance_ratio of the element width, the shipped centre_tolerance_ratio.
    Inputs:
        lines: List[tuple] - the title lines as (x0, y0, x1, y1), in any order.
        rect: fitz.Rect - the element rectangle.
        tolerance_ratio: float - the share of the element width within which a gap counts as equal.
    Outputs:
        Optional[str] - "left", "center" or "right", or None when there is no line.
    Raises:
        None.
    """
    if not lines:
        return None
    tolerance = tolerance_ratio * rect.width
    ordered = sorted(lines, key=lambda line: line[1])

    def centred(line: tuple) -> bool:
        """
        Purpose: Tell whether one title line is centred on the element.
        Inputs:
            line: tuple - (x0, y0, x1, y1) of the line.
        Outputs:
            bool - True when the left and right gaps differ by no more than the tolerance.
        Raises:
            None.
        """
        return abs((line[0] - rect.x0) - (rect.x1 - line[2])) <= tolerance

    if centred(ordered[-1]):
        return ALIGN_CENTER
    if ordered[0][0] - rect.x0 <= tolerance:
        return ALIGN_LEFT
    return ALIGN_RIGHT


def _lines_inside(block: tuple, line_boxes: Optional[List[tuple]]) -> List[tuple]:
    """
    Purpose: Give the page lines that lie inside a text block's rectangle (one pixel of slack for rounding).
    Inputs:
        block: tuple - a block tuple of page.get_text("blocks").
        line_boxes: Optional[List[tuple]] - the (x0, y0, x1, y1) of every text line of the page, or None.
    Outputs:
        List[tuple] - the lines inside the block, empty when none were given.
    Raises:
        None.
    """
    if not line_boxes:
        return []
    return [box for box in line_boxes
            if box[0] >= block[0] - 1 and box[2] <= block[2] + 1 and box[1] >= block[1] - 1 and box[3] <= block[3] + 1]


def _alignment(block: tuple, rect: "fitz.Rect", tolerance_ratio: float,
               column: Optional[Tuple[float, float]] = None) -> str:
    """
    Purpose: Measure how a block is aligned against the element, from the horizontal centres (plan 24, Task 2).
    Details: A block centred on the element is "center". A block centred on the page text column (when given) is
        "center" too, so a figure that sits off the column can still carry a title centred under the text. Otherwise
        the block is "left" or "right" of the element centre.
    Inputs:
        block: tuple - the block tuple, its x0 and x1 are used.
        rect: fitz.Rect - the element rectangle.
        tolerance_ratio: float - the share of the element width (of the column width for the column) within which a
            block counts as centred.
        column: Optional[Tuple[float, float]] - the left and right edges of the page text column, or None.
    Outputs:
        str - "left", "center" or "right".
    Raises:
        None.
    """
    block_centre = (block[0] + block[2]) / 2
    element_centre = (rect.x0 + rect.x1) / 2
    tolerance = tolerance_ratio * rect.width
    if abs(block_centre - element_centre) <= tolerance:
        return ALIGN_CENTER
    if column is not None:
        column_centre = (column[0] + column[1]) / 2
        if abs(block_centre - column_centre) <= tolerance_ratio * (column[1] - column[0]):
            return ALIGN_CENTER
    return ALIGN_LEFT if block_centre < element_centre else ALIGN_RIGHT


def _gap_and_position(block: tuple, rect: "fitz.Rect") -> Optional[tuple]:
    """
    Purpose: Measure the vertical gap between a block and the element, and say on which side it lies.
    Inputs:
        block: tuple - the block tuple.
        rect: fitz.Rect - the element rectangle.
    Outputs:
        tuple or None - (gap in points, "below" or "above"), None when the block is beside the element.
    Raises:
        None.
    """
    if block[1] >= rect.y1:
        return block[1] - rect.y1, POSITION_BELOW
    if block[3] <= rect.y0:
        return rect.y0 - block[3], POSITION_ABOVE
    return None


def _title_placement(block: tuple, rect: "fitz.Rect", overlap_allowed: float) -> Optional[tuple]:
    """
    Purpose: Place a title block against an element, allowing a caption that reaches into the element's edge.
    Details: A drawing's box can run a few points into the caption under it (plan 17, R01 page 17). A block that
        straddles the bottom or top edge, beside the element horizontally, by no more than overlap_allowed points
        is still the title on that side. A block lying inside the element is never a title.
    Inputs:
        block: tuple - the block tuple.
        rect: fitz.Rect - the element rectangle.
        overlap_allowed: float - the largest overlap in points that still counts as beside the edge.
    Outputs:
        tuple or None - (gap in points, "below" or "above"), None when the block is not a title of the element.
    Raises:
        None.
    """
    placement = _gap_and_position(block, rect)
    if placement is not None:
        return placement
    if min(block[2], rect.x1) <= max(block[0], rect.x0):
        return None
    if block[1] < rect.y1 < block[3] and rect.y1 - block[1] <= overlap_allowed:
        return 0.0, POSITION_BELOW
    if block[1] < rect.y0 < block[3] and block[3] - rect.y0 <= overlap_allowed:
        return 0.0, POSITION_ABOVE
    return None


def text_column(blocks: List[tuple], markers: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """
    Purpose: Measure the page text column as the median left and right edges of its body blocks (plan 24, Task 2).
    Details: A body block holds at least column_min_words words; a shorter block is a caption or a label and does not
        define the column.
    Inputs:
        blocks: List[tuple] - the tuples of page.get_text("blocks") for one page.
        markers: Dict[str, Any] - the data returned by load_markers.
    Outputs:
        Optional[Tuple[float, float]] - (left, right) in points, or None when no block is long enough.
    Raises:
        MarkerError: If column_min_words is missing.
    """
    min_words = _marker_value(markers, "column_min_words")
    body = [block for block in blocks
            if len(block) >= 7 and block[6] == TEXT_BLOCK_TYPE and len(_clean(block[4]).split()) >= min_words]
    if not body:
        return None
    lefts = sorted(block[0] for block in body)
    rights = sorted(block[2] for block in body)
    middle = len(body) // 2
    return _median(lefts, middle), _median(rights, middle)


def _median(values: List[float], middle: int) -> float:
    """
    Purpose: Give the median of a sorted list of edges, the mean of the two middle values for an even count.
    Inputs:
        values: List[float] - the sorted values, not empty.
        middle: int - len(values) // 2.
    Outputs:
        float - the median.
    Raises:
        None.
    """
    if len(values) % 2:
        return float(values[middle])
    return (values[middle - 1] + values[middle]) / 2


def find_title(blocks: List[tuple], rect: "fitz.Rect", element_type: str,
               markers: Dict[str, Any], column: Optional[Tuple[float, float]] = None,
               line_boxes: Optional[List[tuple]] = None) -> Optional[Dict[str, Any]]:
    """
    Purpose: Find the title of a figure or a table: the nearest text block that opens with a marker
        word of its type, looking below first for a figure and above first for a table.
    Inputs:
        blocks: List[tuple] - the tuples of page.get_text("blocks").
        rect: fitz.Rect - the element rectangle.
        element_type: str - "figure" or "table".
        markers: Dict[str, Any] - the data returned by load_markers.
    Outputs:
        Optional[Dict[str, str]] - {"text", "position", "alignment"}, or None when no title is within
            the distance of the markers file.
    Raises:
        ValueError: If element_type is neither "figure" nor "table".
        MarkerError: If the markers lack the prefix list or the distance of the element type.
    """
    if element_type not in ELEMENT_PREFIX_KEYS:
        raise ValueError(f"unknown element type '{element_type}' (expected figure or table)")
    prefixes = _marker_prefixes(markers, ELEMENT_PREFIX_KEYS[element_type])
    max_distance = _marker_value(markers, "max_title_distance_pt")
    tolerance = _marker_value(markers, "centre_tolerance_ratio")

    overlap_allowed = _marker_value(markers, "title_overlap_pt")

    found: Dict[str, List[tuple]] = {POSITION_BELOW: [], POSITION_ABOVE: []}
    for block in blocks:
        if len(block) < 7 or block[6] != TEXT_BLOCK_TYPE:
            continue
        text = _clean(block[4])
        if not _starts_with_marker(text, prefixes):
            continue
        placement = _title_placement(block, rect, overlap_allowed)
        if placement is None or placement[0] > max_distance:
            continue
        found[placement[1]].append((placement[0], block, text))

    for direction in ELEMENT_DIRECTIONS[element_type]:
        candidates = sorted(found[direction], key=lambda item: item[0])
        if candidates:
            _, block, text = candidates[0]
            lines = _lines_inside(block, line_boxes)
            alignment = lines_alignment(lines, rect, tolerance) if lines else None
            return {
                "text": text,
                "position": direction,
                "alignment": alignment or _alignment(block, rect, tolerance, column),
                "rect": [block[0], block[1], block[2], block[3]],
                "lines": [[box[0], box[2]] for box in sorted(lines, key=lambda box: box[1])],
            }
    return None


IN_IMAGE_TOP = "in_image_top"
IN_IMAGE_BOTTOM = "in_image_bottom"


def _lines_of(words: List[tuple]) -> List[List[tuple]]:
    """
    Purpose: Group OCR word tuples into their lines, in reading order (top to bottom, left to right in a line).
    Details: A word carries its block and line numbers at indices 5 and 6 (PyMuPDF and the page OCR); a tuple
        without them is taken as a line of its own.
    Inputs:
        words: List[tuple] - the word tuples (x0, y0, x1, y1, text, ...).
    Outputs:
        List[List[tuple]] - the lines, each sorted by x0, the lines sorted by their top edge.
    Raises:
        None.
    """
    groups: Dict[tuple, List[tuple]] = {}
    for index, word in enumerate(words):
        key = (word[5], word[6]) if len(word) >= 7 else ("single", index)
        groups.setdefault(key, []).append(word)
    lines = [sorted(members, key=lambda item: item[0]) for members in groups.values()]
    return sorted(lines, key=lambda members: min(item[1] for item in members))


def find_in_image_title(words: List[tuple], rect: "fitz.Rect", element_type: str, markers: Dict[str, Any],
                        band_ratio: float) -> Optional[Dict[str, str]]:
    """
    Purpose: Find a title drawn inside a raster element: a line opening with a marker word of its type, lying in the
        top or the bottom band of the element (plan 24, Task 1).
    Details: The band is band_ratio of the element height at each edge. A marker word inside the drawing, or a line
        that does not open with a marker, is not a title. The top band is preferred for a table and the bottom band
        for a figure, the same order as find_title. The alignment is measured on the line, as for a text title.
    Inputs:
        words: List[tuple] - the OCR word tuples of the element region (clipped to the element by the caller).
        rect: fitz.Rect - the element rectangle.
        element_type: str - "figure" or "table".
        markers: Dict[str, Any] - the data returned by load_markers.
        band_ratio: float - the share of the element height read at each edge, above 0 and at most one half.
    Outputs:
        Optional[Dict[str, str]] - {"text", "position" ("in_image_top" or "in_image_bottom"), "alignment"}, or None.
    Raises:
        ValueError: If element_type is unknown or band_ratio is outside (0, 0.5].
        MarkerError: If the markers lack the prefix list or the centring tolerance.
    """
    if element_type not in ELEMENT_PREFIX_KEYS:
        raise ValueError(f"unknown element type '{element_type}' (expected figure or table)")
    if isinstance(band_ratio, bool) or not isinstance(band_ratio, (int, float)) or not 0 < band_ratio <= 0.5:
        raise ValueError(f"band_ratio must be a number above 0 and at most 0.5, got {band_ratio!r}")
    prefixes = _marker_prefixes(markers, ELEMENT_PREFIX_KEYS[element_type])
    tolerance = _marker_value(markers, "centre_tolerance_ratio")
    band = band_ratio * rect.height
    found: Dict[str, List[tuple]] = {IN_IMAGE_TOP: [], IN_IMAGE_BOTTOM: []}
    for members in _lines_of(words):
        text = _clean(" ".join(item[4] for item in members))
        if not _starts_with_marker(text, prefixes):
            continue
        box = (min(item[0] for item in members), min(item[1] for item in members),
               max(item[2] for item in members), max(item[3] for item in members))
        if box[3] <= rect.y0 + band:
            found[IN_IMAGE_TOP].append((box, text))
        elif box[1] >= rect.y1 - band:
            found[IN_IMAGE_BOTTOM].append((box, text))
    order = [IN_IMAGE_TOP, IN_IMAGE_BOTTOM] if element_type == "table" else [IN_IMAGE_BOTTOM, IN_IMAGE_TOP]
    for position in order:
        if found[position]:
            box, text = found[position][0]
            return {"text": text, "position": position, "alignment": _alignment(box, rect, tolerance)}
    return None


def _remove_sequence(words: List[str], sequence: List[str]) -> List[str]:
    """
    Purpose: Remove every contiguous run of words equal to a sequence, the words of a title.
    Inputs:
        words: List[str] - the words in reading order.
        sequence: List[str] - the title words to remove.
    Outputs:
        List[str] - the words that remain.
    Raises:
        None.
    """
    if not sequence:
        return words
    kept: List[str] = []
    index = 0
    width = len(sequence)
    while index < len(words):
        if words[index:index + width] == sequence:
            index += width
            continue
        kept.append(words[index])
        index += 1
    return kept


def find_legend(page_words: List[tuple], rect: "fitz.Rect", title_text: Optional[str]) -> str:
    """
    Purpose: Collect the legend of a figure: the words whose centre lies inside the element rectangle,
        without the words of its title.
    Inputs:
        page_words: List[tuple] - the tuples of page.get_text("words").
        rect: fitz.Rect - the element rectangle.
        title_text: Optional[str] - the title text to remove from the legend, None when there is none.
    Outputs:
        str - the legend words in reading order, joined by spaces, empty when there is none.
    Raises:
        None.
    """
    inside = []
    for word in page_words:
        centre_x = (word[0] + word[2]) / 2
        centre_y = (word[1] + word[3]) / 2
        if rect.x0 <= centre_x <= rect.x1 and rect.y0 <= centre_y <= rect.y1:
            inside.append(word)
    inside.sort(key=lambda w: (w[5], w[6], w[7]))
    texts = [w[4] for w in inside]
    title_words = title_text.split() if title_text else []
    return " ".join(_remove_sequence(texts, title_words))


def find_notes(blocks: List[tuple], rect: "fitz.Rect", markers: Dict[str, Any]) -> List[str]:
    """
    Purpose: Collect the notes under a table: consecutive text blocks below it that open with a note
        word, nearest first, stopping at the first block that is not a note or is too far.
    Inputs:
        blocks: List[tuple] - the tuples of page.get_text("blocks").
        rect: fitz.Rect - the table rectangle.
        markers: Dict[str, Any] - the data returned by load_markers.
    Outputs:
        List[str] - the cleaned note texts in reading order, empty when no note is directly below.
    Raises:
        MarkerError: If the markers lack the note prefixes or the note distance.
    """
    prefixes = _marker_prefixes(markers, "note_prefixes")
    max_distance = _marker_value(markers, "max_note_distance_pt")

    below = []
    for block in blocks:
        if len(block) < 7 or block[6] != TEXT_BLOCK_TYPE or _overlaps(block, rect):
            continue
        if block[1] >= rect.y1:
            below.append(block)
    below.sort(key=lambda b: b[1])

    notes: List[str] = []
    previous_bottom = rect.y1
    for block in below:
        gap = block[1] - previous_bottom
        if gap > max_distance:
            break
        text = _clean(block[4])
        if not _starts_with_marker(text, prefixes):
            break
        notes.append(text)
        previous_bottom = block[3]
    return notes
