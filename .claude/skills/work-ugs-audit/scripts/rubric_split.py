"""
rubric_split - split a Markdown rubric by its numbered sections and keep the exact text of every section.

Why: the grader model used to turn the professor's rubric into short criteria, and the tables, quotations and
lists of the original were lost (Issue 120, measured 2026-11-15: 19179 bytes became 6605). The split is done by
code, so no sentence is removed or shortened. The grader and the auditor receive the exact text of an item.
"""
import re
from decimal import Decimal
from typing import Dict, Optional

MAX_ITEMS = 99  # the item id pattern of the rubric schema is I and two digits


class RubricSplitError(ValueError):
    """Raised when a rubric cannot be split faithfully (a wrong stated total, too many sections)."""


def _number(text: str) -> Decimal:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read a point value written with a point or a comma as a decimal.
    Inputs:
        text (str): the number as written, for example 0.5 or 0,5
    Outputs:
        value (Decimal): the exact value.
    --------------------------------------------------------------------------
    """
    return Decimal(text.replace(",", "."))


def _plain(value: Decimal):
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn a decimal into an int when it is whole and a float otherwise, as the rubric JSON writes points.
    Inputs:
        value (Decimal): the value.
    Outputs:
        number (int | float): the value.
    --------------------------------------------------------------------------
    """
    return int(value) if value == value.to_integral_value() else float(value)


def _trim(lines: list) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Join the lines of a section and drop the blank lines and the closing horizontal rule at its end.
    Inputs:
        lines (list[str]): the lines of one section, or of the preamble.
    Outputs:
        text (str): the exact text without trailing blank lines and without a final `---` rule.
    --------------------------------------------------------------------------
    """
    kept = list(lines)
    while kept and not kept[-1].strip():
        kept.pop()
    if kept and kept[-1].strip() == "---":
        kept.pop()
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept)


def split_rubric(text: str, assessment_type: str, heading_regex: str, total_regex: str,
                 loose_heading_regex: str) -> Optional[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Split a Markdown rubric on its numbered section headings. Each section keeps its exact text.
    Details:
        The heading regex has the named groups `n`, `title` and `points`. The text before the first heading is
        the preamble (title, points table, acronyms) and is copied into every item so the grader sees it.
        The ids follow the order of the sections.
    Inputs:
        text (str): the rubric as written by the professor
        assessment_type (str): the assessment type of the run
        heading_regex (str): the section heading pattern (config key rubric.section_heading_regex)
        total_regex (str): the stated total pattern with the group `total` (config key rubric.total_regex), searched
            in the whole text
        loose_heading_regex (str): any numbered heading, with or without points (config key
            rubric.loose_heading_regex), used to refuse a heading the strict pattern did not read
    Outputs:
        rubric (dict | None): assessment_type, total_points, preamble and items (id, title, max_points, text,
        preamble), or None when fewer than two numbered sections are found.
    Raises:
        RubricSplitError: a stated total differs from the sum of the item points, more than 99 sections, or a
        numbered heading that the strict pattern did not read (it would be absorbed into the previous item).
    --------------------------------------------------------------------------
    """
    heading = re.compile(heading_regex)
    lines = text.replace("\r\n", "\n").split("\n")
    starts = [(index, heading.match(line)) for index, line in enumerate(lines)]
    starts = [(index, match) for index, match in starts if match]
    if len(starts) < 2:
        return None
    if len(starts) > MAX_ITEMS:
        raise RubricSplitError("more than %d numbered sections" % MAX_ITEMS)
    strict = {index for index, _ in starts}
    loose = re.compile(loose_heading_regex)
    for index, line in enumerate(lines):
        if index not in strict and loose.match(line):
            raise RubricSplitError("a numbered heading has no points or does not match the heading pattern: %s"
                                   % line.strip())
    preamble = _trim(lines[:starts[0][0]])
    items = []
    total = Decimal(0)
    for position, (index, match) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        points = _number(match.group("points"))
        total += points
        items.append({"id": "I%02d" % (position + 1), "title": match.group("title").strip(),
                      "max_points": _plain(points), "text": _trim(lines[index:end]), "preamble": preamble})
    stated = re.search(total_regex, text)
    if stated and _number(stated.group("total")) != total:
        raise RubricSplitError("the stated total %s differs from the sum of the items %s"
                               % (stated.group("total"), _plain(total)))
    return {"assessment_type": assessment_type, "total_points": _plain(total), "preamble": preamble,
            "items": items}


def item_markdown(item: dict) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        The Markdown of one item: its exact text when it has one, else the title, criteria and checklist.
    Inputs:
        item (dict): a rubric item
    Outputs:
        markdown (str): the section.
    --------------------------------------------------------------------------
    """
    if item.get("text"):
        return item["text"]
    lines = ["## %s - %s (%s)" % (item["id"], item["title"], item["max_points"])]
    if item.get("criteria"):
        lines += ["Criteria:"] + ["- %s" % text for text in item["criteria"]]
    if item.get("checklist"):
        lines += ["Checklist:"] + ["- %s" % text for text in item["checklist"]]
    return "\n".join(lines)


def item_prompt_text(item: dict) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        The text a prompt receives for an item: the exact section of the professor's rubric and, when there is
        one, the preamble with the acronym table, never a Python representation of the dict.
    Inputs:
        item (dict): a rubric item
    Outputs:
        text (str): the item as the grader or the auditor reads it.
    --------------------------------------------------------------------------
    """
    body = "%s\n(item %s, %s points)" % (item_markdown(item), item["id"], item["max_points"])
    if item.get("preamble"):
        return "Rubric context:\n%s\n\nRubric section:\n%s" % (item["preamble"], body)
    return body


def _norm(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Lower-case a text and collapse its spacing, to compare lines of a rubric.
    Inputs:
        text (str): any text.
    Outputs:
        text (str): the comparable form.
    --------------------------------------------------------------------------
    """
    return " ".join(text.lower().split())


def check_text_kept(source: str, rubric: dict, min_words: int) -> Optional[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Check that a rubric rebuilt by a model kept every line of the professor's text.
    Inputs:
        source (str): the rubric file as written
        rubric (dict): the rubric dict, with `text` on each item
        min_words (int): lines with fewer words are not checked (config key rubric.min_check_words)
    Outputs:
        missing (str | None): the first source line absent from the preamble and the item texts, or None.
    --------------------------------------------------------------------------
    """
    haystack = _norm(" ".join([rubric.get("preamble", "")] + [item.get("text", "") for item in rubric["items"]]))
    wanted: Dict[str, int] = {}
    for line in source.splitlines():
        if len(line.split()) >= min_words:
            wanted[_norm(line)] = wanted.get(_norm(line), 0) + 1
    # A line the professor repeats in several sections must be kept as many times as it is written
    for line in source.splitlines():
        if len(line.split()) >= min_words and haystack.count(_norm(line)) < wanted[_norm(line)]:
            return line.strip()
    return None
