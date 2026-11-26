"""
Purpose: Verify that a quote an element cites is on its page (review round 2, item 1), in three tiers: key (the
normalised text is a substring), elision (fragments found in order), fuzzy (accent-folded words in a window, in order).
The thresholds come from ugs_config.json (R0, R4). pdf_annotate.normalize is not changed: annotation placement needs it.
"""

import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ugs_config import default_path

KEY_TIER = "key"
ELISION_TIER = "elision"
FUZZY_TIER = "fuzzy"
TIERS = (KEY_TIER, ELISION_TIER, FUZZY_TIER)

# The configuration keys this module reads, each a {value, provenance} entry of ugs_config.json (R3).
QUOTE_SETTING_KEYS = {
    "min_chars": "grade.quote_min_chars",
    "min_words": "grade.quote_min_words",
    "min_word_share": "grade.quote_min_word_share",
    "window_factor": "grade.quote_window_factor",
    "page_window": "grade.quote_page_window",
    "max_words": "grade.quote_max_words",
}
# The settings read as whole numbers (a character, word or page count); the others are read as numbers.
WHOLE_SETTINGS = ("min_chars", "min_words", "page_window", "max_words")

INVISIBLE_RE = re.compile("[­​‌‍⁠﻿]")
HTML_TAG_RE = re.compile(r"<[^>]*>")
ESCAPE_RE = re.compile(r"\\(.)")
MARKUP_RE = re.compile(r"[*_`#>~|]")
ELISION_RE = re.compile(r"\.\.\.|…|\[\.\.\.\]|\(\.\.\.\)")
WORD_RE = re.compile(r"[a-z0-9]+")


def default_config_path() -> Path:
    """
    Purpose: Give the configuration file that holds the quote settings.
    Inputs:
        None.
    Outputs:
        Path - the shipped ugs_config.json.
    Raises:
        None.
    """
    return default_path()


def read_quote_settings(path: Path) -> Dict[str, Any]:
    """
    Purpose: Read the three quote settings from the configuration file (R0, R3): the shortest key a key match may use,
        the word share of the fuzzy tier and the window factor of the fuzzy tier.
    Inputs:
        path: Path - The configuration JSON file.
    Outputs:
        dict - min_chars (int), min_word_share (float), window_factor (float).
    Raises:
        ValueError: If the file is unreadable, a key is absent, or a value is not a usable number (R3).
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    settings: Dict[str, Any] = {}
    for name, key in QUOTE_SETTING_KEYS.items():
        entry = raw.get(key) if isinstance(raw, dict) else None
        if not isinstance(entry, dict) or "value" not in entry:
            raise ValueError(f"missing key '{key}' in {path}")
        value = entry["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"'{key}' must be a positive number in {path}")
        settings[name] = int(value) if name in WHOLE_SETTINGS else float(value)
    if settings["min_word_share"] > 1:
        raise ValueError(f"'{QUOTE_SETTING_KEYS['min_word_share']}' must not exceed 1 in {path}")
    return settings


def _canonical(text: str) -> str:
    """
    Purpose: Normalise a text for the key tier: NFKC, casefold, no invisible characters, no HTML tags, no backslash
        escapes (kept as the character they escape) and no Markdown or table marks.
    Inputs:
        text: str - The text.
    Outputs:
        str - The canonical text.
    Raises:
        None.
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    folded = INVISIBLE_RE.sub("", folded)
    folded = HTML_TAG_RE.sub("", folded)
    folded = ESCAPE_RE.sub(r"\1", folded)
    return MARKUP_RE.sub("", folded)


def _key(text: str) -> str:
    """
    Purpose: Reduce a text to its letters and digits, for the substring test of the key tier.
    Inputs:
        text: str - The text.
    Outputs:
        str - The canonical text without any character that is not a letter or a digit.
    Raises:
        None.
    """
    return "".join(char for char in _canonical(text) if char.isalnum())


def _fold_words(text: str) -> List[str]:
    """
    Purpose: Give the words of a text with accents removed, for the fuzzy tier.
    Inputs:
        text: str - The text.
    Outputs:
        List[str] - The lower-case words, accent-folded.
    Raises:
        None.
    """
    decomposed = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text).casefold())
    stripped = "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
    return WORD_RE.findall(stripped)


def _key_tier(quote: str, text: str, min_chars: int) -> bool:
    """
    Purpose: Tell whether the key of the quote is a substring of the key of the text, the quote being long enough.
    Inputs:
        quote: str - The quote.
        text: str - The page text.
        min_chars: int - The shortest key a match may use.
    Outputs:
        bool - True on a match.
    Raises:
        None.
    """
    key = _key(quote)
    return len(key) >= min_chars and key in _key(text)


def _elision_tier(quote: str, text: str, min_chars: int) -> bool:
    """
    Purpose: Tell whether the quote, split on an ellipsis, has at least two fragments that are each long enough and
        are found in the text in order.
    Inputs:
        quote: str - The quote.
        text: str - The page text.
        min_chars: int - The shortest key a fragment may use.
    Outputs:
        bool - True on a match.
    Raises:
        None.
    """
    fragments = [_key(part) for part in ELISION_RE.split(quote)]
    fragments = [fragment for fragment in fragments if fragment]
    if len(fragments) < 2 or any(len(fragment) < min_chars for fragment in fragments):
        return False
    page_key = _key(text)
    position = 0
    for fragment in fragments:
        found = page_key.find(fragment, position)
        if found < 0:
            return False
        position = found + len(fragment)
    return True


def _longest_common_subsequence(first: Sequence[str], second: Sequence[str]) -> int:
    """
    Purpose: Give the length of the longest common subsequence of two word lists (words in order, not adjacent).
    Inputs:
        first: Sequence[str] - The quote words.
        second: Sequence[str] - The window words.
    Outputs:
        int - The length of the longest common subsequence.
    Raises:
        None.
    """
    previous = [0] * (len(second) + 1)
    for word in first:
        current = [0]
        for index, other in enumerate(second):
            if word == other:
                current.append(previous[index] + 1)
            else:
                current.append(max(current[-1], previous[index + 1]))
        previous = current
    return previous[-1]


def _fuzzy_tier(quote: str, text: str, min_share: float, factor: float) -> bool:
    """
    Purpose: Tell whether the quote's words, accent-folded, appear in order in a window of the text about factor times
        the quote's length, in a share at least min_share.
    Details: A page that holds too few of the quote's words is skipped before the window search, so the search stays
        short on long reports.
    Inputs:
        quote: str - The quote.
        text: str - The page text.
        min_share: float - The share of the quote's words the window must hold, in order.
        factor: float - The window length as a multiple of the quote's word count.
    Outputs:
        bool - True on a match.
    Raises:
        None.
    """
    quote_words = _fold_words(quote)
    page_words = _fold_words(text)
    if not quote_words or not page_words:
        return False
    needed = min_share * len(quote_words)
    if sum(1 for word in set(quote_words) if word in set(page_words)) < needed:
        return False
    width = max(len(quote_words), math.ceil(factor * len(quote_words)))
    for start in range(len(page_words)):
        window = page_words[start:start + width]
        if _longest_common_subsequence(quote_words, window) >= needed:
            return True
    return False


def _candidates(named_page: int, pages: List[str], window: int) -> List[Tuple[int, str]]:
    """
    Purpose: List the texts to search for a quote: the named page first, then the pages within the window around it,
        then each join of two consecutive pages inside the window (a quote can cross a page break). Pages further away
        are never searched (review round 2, item 2).
    Inputs:
        named_page: int - The page the element names; anything outside the report gives no candidate.
        pages: List[str] - The page texts of the report.
        window: int - How many pages either side of the named page are searched.
    Outputs:
        List[Tuple[int, str]] - (page number, text) pairs; a join carries the number of its first page.
    Raises:
        None.
    """
    if not 1 <= named_page <= len(pages):
        return []
    inside = list(range(max(1, named_page - window), min(len(pages), named_page + window) + 1))
    ordered = [named_page] + [number for number in inside if number != named_page]
    found = [(number, pages[number - 1]) for number in ordered]
    for number in inside[:-1]:
        found.append((number, pages[number - 1] + "\n" + pages[number]))
    return found


def verify_element(quote: Any, named_page: Any, pages: List[str], settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Purpose: Verify one element's quote against the report pages (review round 2, item 1): tier by tier, each tier on
        the named page first, then the other pages and the page joins. The first match gives the tier and the page.
    Inputs:
        quote: Any - The quote the element cites.
        named_page: Any - The page the element names (1-based); anything else searches every page.
        pages: List[str] - The page texts of the report.
        settings: dict - min_chars, min_word_share and window_factor, from read_quote_settings.
    Outputs:
        dict - verified (bool), tier (the matching tier or None), page (the matched page or None), page_corrected
            (bool: the match is not on the named page), tiers_tried (the tiers searched, in order).
    Raises:
        None.
    """
    result: Dict[str, Any] = {"verified": False, "tier": None, "page": None, "page_corrected": False,
                              "tiers_tried": []}
    if not isinstance(quote, str) or not quote.strip():
        return result
    words = len(_fold_words(quote))
    if words < settings["min_words"]:  # review round 2, item 2: a short quote never verifies, in any tier
        return result
    named = named_page if isinstance(named_page, int) and not isinstance(named_page, bool) else 0
    candidates = _candidates(named, pages, settings["page_window"])
    for tier in TIERS:
        if tier == FUZZY_TIER and words > settings["max_words"]:  # review round 2, item 3: no fuzzy on a long quote
            continue
        result["tiers_tried"].append(tier)
        for number, text in candidates:
            if _matches(tier, quote, text, settings):
                result.update(verified=True, tier=tier, page=number, page_corrected=number != named)
                return result
    return result


def _matches(tier: str, quote: str, text: str, settings: Dict[str, Any]) -> bool:
    """
    Purpose: Run one tier on one text.
    Inputs:
        tier: str - key, elision or fuzzy.
        quote: str - The quote.
        text: str - The text to search.
        settings: dict - The quote settings.
    Outputs:
        bool - True on a match.
    Raises:
        ValueError: If the tier is unknown.
    """
    if tier == KEY_TIER:
        return _key_tier(quote, text, settings["min_chars"])
    if tier == ELISION_TIER:
        return _elision_tier(quote, text, settings["min_chars"])
    if tier == FUZZY_TIER:
        return _fuzzy_tier(quote, text, settings["min_word_share"], settings["window_factor"])
    raise ValueError(f"unknown quote tier '{tier}'")
