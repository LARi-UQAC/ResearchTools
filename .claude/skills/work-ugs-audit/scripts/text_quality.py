"""text_quality - page text repair by OCR, and the OCR preflight (Issue 122, plan 5, task 1).

Purpose: Prove that Tesseract OCR works for each language before any page is repaired, count the Unicode
replacement characters of a page text, normalise a repaired text, and repair only the damaged pages by OCR.
The OCR call of a page is injected by the caller, so this module never reads a report by itself.
Every value comes from assets/ocr_languages.json with its provenance (R0, R4); a missing key is a named error (R3).
Nothing from a report reaches stdout, a log or any output.
"""

import json
import os
import unicodedata
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Tuple

# The Unicode REPLACEMENT CHARACTER (U+FFFD). It is a fixed code point of the standard, not a tunable value.
REPLACEMENT_CHARACTER = "�"

# Keys every data file must carry (R3). The language map and the probe settings are read from them.
REQUIRED_KEYS = (
    "language_codes",
    "tessdata_env_var",
    "tesseract_tool_name",
    "ocr_probe_word",
    "ocr_probe_font_size",
    "ocr_probe_dpi",
)

# Keys the repair step needs from the caller's settings (R3). A page with fewer words than min_words_per_page is
# treated as having no text layer, so a scanned page with no text is sent to OCR as well as a damaged one.
REPAIR_KEYS = ("min_replacement_chars", "min_words_per_page", "language_codes")


class TextQualityError(ValueError):
    """Base error of the text quality module."""


class OcrUnavailable(TextQualityError):
    """Raised when OCR cannot run: a tool, a language file or the tessdata folder is missing or the probe fails."""


class QualityConfigError(TextQualityError):
    """Raised when a configuration value or data file key is missing or malformed (R3)."""


def default_data_path() -> Path:
    """
    Purpose: Return the path of the OCR data file shipped with the skill.
    Inputs: None.
    Outputs: Path: the path of assets/ocr_languages.json beside the scripts folder.
    Raises: None.
    """
    return Path(__file__).resolve().parent.parent / "assets" / "ocr_languages.json"


def load_ocr_settings(path: Optional[Path] = None) -> Dict[str, object]:
    """
    Purpose: Read the OCR data file and return each value, after checking that every required key is present.
    Inputs: path (Optional[Path]): the data file; None means the shipped file.
    Outputs: Dict[str, object]: a mapping from each key to its "value".
    Raises: QualityConfigError: if the file is missing, not valid JSON, an entry lacks "value" or a non-empty
        "provenance" string, or a required key is absent.
    """
    if path is None:
        path = default_data_path()
    if not path.is_file():
        raise QualityConfigError(f"missing data file: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise QualityConfigError(f"unreadable or invalid JSON data file: {path}")
    if not isinstance(raw, dict):
        raise QualityConfigError(f"top level must be an object: {path}")

    values: Dict[str, object] = {}
    for key, entry in raw.items():
        if not isinstance(entry, dict) or "value" not in entry:
            raise QualityConfigError(f"entry {key} has no 'value': {path}")
        provenance = entry.get("provenance")
        if not isinstance(provenance, str) or not provenance.strip():
            raise QualityConfigError(f"entry {key} has no provenance: {path}")
        values[key] = entry["value"]

    for key in REQUIRED_KEYS:
        if key not in values:
            raise QualityConfigError(f"missing required key '{key}': {path}")
    return values


def tesseract_codes(language: str, language_codes: Mapping[str, List[str]]) -> List[str]:
    """
    Purpose: Map a document language key (fr, en or ambiguous) to its Tesseract language codes.
    Inputs: language (str): the key; language_codes (Mapping[str, List[str]]): the map from the data file.
    Outputs: List[str]: the Tesseract codes, e.g. ["fra"] for fr and ["fra", "eng"] for ambiguous.
    Raises: QualityConfigError: if the language has no entry in the map, or the entry is not a non-empty list.
    """
    if language not in language_codes:
        raise QualityConfigError(f"no Tesseract code for language '{language}' in the language map")
    codes = language_codes[language]
    if not isinstance(codes, list) or not codes or not all(isinstance(c, str) and c for c in codes):
        raise QualityConfigError(f"the Tesseract codes for language '{language}' must be a non-empty list")
    return list(codes)


def normalize_text(text: str) -> str:
    """
    Purpose: Normalise a repaired page text to Unicode NFC and expand the ligature letters to plain letters.
    Inputs: text (str): the text to normalise.
    Outputs: str: the NFC text, where each character whose compatibility decomposition is only ASCII letters
        (the fi, fl, ff ligatures) is replaced by those letters.
    Raises: None.
    """
    composed = unicodedata.normalize("NFC", text)
    pieces = []
    for char in composed:
        decomposition = unicodedata.decomposition(char)
        if decomposition.startswith("<compat>"):
            parts = decomposition.split()[1:]
            letters = [chr(int(part, 16)) for part in parts]
            if letters and all(letter.isascii() and letter.isalpha() for letter in letters):
                pieces.append("".join(letters))
                continue
        pieces.append(char)
    return "".join(pieces)


def has_readable_text(text: str) -> bool:
    """
    Purpose: Tell whether a page text holds any readable character once the replacement characters are removed.
    Inputs: text (str): the page text.
    Outputs: bool: True when at least one character other than whitespace and U+FFFD is present.
    Raises: None.
    """
    return bool(text.replace(REPLACEMENT_CHARACTER, "").strip())


def replacement_count(text: str) -> int:
    """
    Purpose: Count the Unicode replacement characters of a page text, the sign of a damaged text layer.
    Inputs: text (str): the page text.
    Outputs: int: the number of U+FFFD characters in the text.
    Raises: None.
    """
    return text.count(REPLACEMENT_CHARACTER)


def _probe_ocr(tesseract_language: str, tessdata: str, settings: Mapping[str, object]) -> str:
    """
    Purpose: Run one real OCR on a fictitious image holding the probe word, and return the recognised text.
    Inputs: tesseract_language (str): the Tesseract code; tessdata (str): the language folder;
        settings (Mapping[str, object]): the OCR data values (probe word, font size, dpi).
    Outputs: str: the text read by PyMuPDF's OCR of the image.
    Raises: Exception: any error of PyMuPDF or of Tesseract is raised to the caller, which names it.
    """
    import fitz

    word = str(settings["ocr_probe_word"])
    font_size = settings["ocr_probe_font_size"]
    dpi = settings["ocr_probe_dpi"]
    source = fitz.open()
    page = source.new_page(width=400, height=200)
    page.insert_text((20, 120), word, fontsize=font_size)
    pixmap = page.get_pixmap(dpi=dpi)
    image_document = fitz.open("png", pixmap.tobytes("png"))
    textpage = image_document[0].get_textpage_ocr(
        language=tesseract_language, dpi=dpi, full=True, tessdata=tessdata
    )
    return textpage.extractText()


def ocr_preflight(
    languages: List[str],
    environ: Optional[Mapping[str, str]] = None,
    ocr_run: Optional[Callable[[str, str], str]] = None,
    settings: Optional[Mapping[str, object]] = None,
) -> None:
    """
    Purpose: Prove that OCR works for each Tesseract language before any page is repaired.
    Inputs: languages (List[str]): Tesseract codes to check, e.g. ["fra", "eng"];
        environ (Optional[Mapping[str, str]]): the environment; None means os.environ, read at call time;
        ocr_run (Optional[Callable[[str, str], str]]): the OCR call (language, tessdata) -> text; None means the
            real PyMuPDF probe; settings (Optional[Mapping[str, object]]): the OCR data values; None means the
            shipped data file.
    Outputs: None. Returns only when every language has its data file and its probe word is read.
    Raises: OcrUnavailable: if the list is empty, TESSDATA_PREFIX is unset, a traineddata file is missing, the OCR
        call raises (the tool is missing or broken), or the probe word is not read. The message names it.
        QualityConfigError: if the data file is missing or incomplete.
    """
    if not languages:
        raise TextQualityError("no language given to the OCR preflight")
    values = dict(settings) if settings is not None else load_ocr_settings()
    env = environ if environ is not None else os.environ
    tool_name = str(values["tesseract_tool_name"])
    env_name = str(values["tessdata_env_var"])
    probe_word = str(values["ocr_probe_word"])

    tessdata = env.get(env_name, "")
    if not tessdata:
        raise OcrUnavailable(f"{tool_name} language data folder unknown: {env_name} is not set")

    runner = ocr_run if ocr_run is not None else (
        lambda language, folder: _probe_ocr(language, folder, values)
    )
    for language in languages:
        data_file = Path(tessdata) / f"{language}.traineddata"
        if not data_file.is_file():
            raise OcrUnavailable(f"{tool_name} language data missing: {data_file.name} not found in {tessdata}")
        try:
            recognised = runner(language, tessdata)
        except Exception as error:
            raise OcrUnavailable(f"{tool_name} OCR failed for language '{language}': {error}") from error
        if probe_word.lower() not in recognised.lower():
            raise OcrUnavailable(
                f"{tool_name} OCR for language '{language}' did not read the probe word; "
                "check the installation and its language data"
            )


def repair_pages(
    pdf: Path,
    texts: List[str],
    language: str,
    settings: Mapping[str, object],
    ocr_page: Callable[[Path, int, str], str],
) -> Tuple[List[str], List[dict]]:
    """
    Purpose: Replace the text of each damaged or text-less page by its OCR, and keep every other page as it is.
    Details: A page is sent to OCR when its replacement count reaches min_replacement_chars (and is at least 1), or
        when it holds fewer than min_words_per_page words, which includes a page with no text layer at all. The OCR
        text replaces the page text when it is not blank. A page still without readable text afterwards keeps its
        text and is flagged empty.
    Inputs: pdf (Path): the report; texts (List[str]): the text of each page, in page order;
        language (str): the document language key (fr, en or ambiguous); settings (Mapping[str, object]) with
        "min_replacement_chars" (the replacement count from which a page is OCR'd), "min_words_per_page" (the word
        count below which a page is OCR'd) and "language_codes" (the language map); ocr_page
        (Callable[[Path, int, str], str]): the OCR of one page, called with the 1-based page number and the
        Tesseract code(s), joined with "+" when there are several.
    Outputs: Tuple[List[str], List[dict]]: the new texts, and one quality entry per page
        {"page": int (1-based), "replacement_chars": int, "ocr": bool, "empty": bool}. ocr is true when the page was
        sent to OCR, whatever the OCR returned. empty is true when the text kept for the page holds no readable
        character, so the page needs a human reader.
    Raises: QualityConfigError: if a required settings key is missing, or the language has no entry in the map.
    """
    for key in REPAIR_KEYS:
        if key not in settings:
            raise QualityConfigError(f"missing settings key '{key}' for the text repair")
    threshold = max(int(settings["min_replacement_chars"]), 1)
    word_minimum = int(settings["min_words_per_page"])
    tesseract_language = "+".join(tesseract_codes(language, settings["language_codes"]))

    new_texts: List[str] = []
    quality: List[dict] = []
    for index, text in enumerate(texts, start=1):
        count = replacement_count(text)
        needs_ocr = count >= threshold or len(text.split()) < word_minimum
        entry = {"page": index, "replacement_chars": count, "ocr": False, "empty": False}
        kept = text
        if needs_ocr:
            entry["ocr"] = True
            recognised = ocr_page(pdf, index, tesseract_language)
            if recognised.strip():
                kept = normalize_text(recognised)
        new_texts.append(kept)
        entry["empty"] = not has_readable_text(kept)
        quality.append(entry)
    return new_texts, quality
