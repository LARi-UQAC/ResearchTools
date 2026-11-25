import json
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Import dependencies
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Add loop-engineer scripts to path for bridge_images
_LOOP_ENGINEER_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "loop-engineer" / "scripts"
if str(_LOOP_ENGINEER_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LOOP_ENGINEER_SCRIPTS))

from ugs_bridge import NotRun
from ugs_text import StepContext, fill
from pdf_annotate import normalize

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
ACCEPTED_SPELLINGS_PATH = ASSETS_DIR / "accepted_spellings.json"
# The categories table is owned by language-review (R1.x and codes); the spelling code is read from it, never written here.
CATEGORIES_PATH = Path(__file__).resolve().parent.parent.parent / "language-review" / "assets" / "language_categories.json"
SPELLING_LABEL = "Spelling"


class LanguageDataError(ValueError):
    """A language data file is missing, unreadable or lacks the entry asked for; the message names it."""


def load_accepted(language: str, path: Path = ACCEPTED_SPELLINGS_PATH) -> set:
    """
    Purpose: Read the spellings both forms of which are correct for one language (N1), normalised as the quote check
        normalises them, so a finding on any member of a pair is recognised.
    Inputs:
        language (str): the report language, a key of the file (fr, en).
        path (Path): the accepted spellings file.
    Outputs:
        set: the normalised spellings of every pair of the language.
    Raises:
        LanguageDataError: the file is unreadable, or the language has no entry or no value list (R3).
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LanguageDataError(f"cannot read {Path(path).name}: {exc}") from exc
    entry = raw.get(language) if isinstance(raw, dict) else None
    value = entry.get("value") if isinstance(entry, dict) else None
    if not isinstance(value, list):
        raise LanguageDataError(f"language '{language}' has no value list in {Path(path).name}")
    forms = set()
    for pair in value:
        if not isinstance(pair, list) or not all(isinstance(word, str) for word in pair):
            raise LanguageDataError(f"each pair of '{language}' must be a list of strings in {Path(path).name}")
        forms.update(normalize(word) for word in pair)
    return forms


def spelling_code(path: Path = CATEGORIES_PATH) -> str:
    """
    Purpose: Give the code of the spelling category from the shared categories table (its English label is Spelling).
    Inputs:
        path (Path): the language categories file.
    Outputs:
        str: the code, for example SP.
    Raises:
        LanguageDataError: the file is unreadable or holds no entry labelled Spelling (R3).
    """
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LanguageDataError(f"cannot read {Path(path).name}: {exc}") from exc
    for entry in raw.get("entries", []):
        if entry.get("label_en") == SPELLING_LABEL:
            return entry["code"]
    raise LanguageDataError(f"no entry labelled '{SPELLING_LABEL}' in {Path(path).name}")


def load_table(path: Path) -> List[Dict]:
    """
    Purpose: Load language table entries with scope 'both'.
    Inputs:
        path: Path - Path to the JSON file.
    Outputs:
        List[Dict] - The filtered entries.
    Raises:
        ValueError - If file is missing or 'entries' key is absent.
    """
    if not path.exists():
        raise ValueError(f"File not found: {path}")
        
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    if "entries" not in data:
        raise ValueError(f"Missing key 'entries' in {path}")
        
    return [e for e in data["entries"] if e.get("scope") == "both"]


def table_text(entries: List[Dict], language: str) -> str:
    """
    Purpose: Generate text representation of the table.
    Inputs:
        entries: List[Dict] - The table entries.
        language: str - 'fr' or 'en'.
    Outputs:
        str - The formatted text.
    """
    lines = []
    for e in entries:
        label_key = f"label_{language}"
        label = e.get(label_key, e.get("label_en", ""))
        lines.append(f"{e['code']} - {label} - {e['severity']}")
    return "\n".join(lines)


def _partial(records: Dict[int, dict]) -> Dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the result of the pages answered so far: the three result keys, plus `pages`, the record of each page.

    Details:
        The `pages` key is what a resume reads back, so a stop never loses a page already answered. The final
        result of language_report carries the three result keys only.

    Inputs:
        records (Dict[int, dict]): page number to the page record {annotations, rejected, not_run}

    Outputs:
        partial (dict): `annotations`, `rejected`, `not_run` and `pages` (keys of the page numbers as strings).

    Raises:
        None.
    --------------------------------------------------------------------------
    """
    result = _result(records)
    result["pages"] = {str(number): records[number] for number in sorted(records)}
    return result


def _result(records: Dict[int, dict]) -> Dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Combine the page records, in page order, into the result of the language step.

    Inputs:
        records (Dict[int, dict]): page number to the page record {annotations, rejected, not_run}

    Outputs:
        result (dict): `annotations` (all pages in order), `rejected` (the sum) and `not_run` (the pages not answered).

    Raises:
        None.
    --------------------------------------------------------------------------
    """
    annotations: List[dict] = []
    for number in sorted(records):
        annotations.extend(records[number]["annotations"])
    return {
        "annotations": annotations,
        "rejected": sum(records[number]["rejected"] for number in records),
        "rejected_correct": sum(records[number].get("rejected_correct", 0) for number in records),
        "not_run": [number for number in sorted(records) if records[number]["not_run"]],
    }


def language_report(
    pages: List[str],
    call: Callable,
    ctx: StepContext,
    entries: List[Dict],
    language: str,
    existing: Optional[Dict[int, dict]] = None,
    on_page: Optional[Callable[[int, Dict[str, Any]], None]] = None
) -> Dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run the language check on each page and collect the findings, resuming from the pages already answered.

    Details:
        A page whose number is in `existing` is not sent to the model again; its saved record is used as it is.
        After each page that was sent to the model (answered or not run), `on_page` receives the partial result
        of the pages done so far (see _partial), so a stop loses nothing already answered. A blank page is skipped
        as before and leaves no record.

    Inputs:
        pages (List[str]): page texts
        call (Callable): the model call function
        ctx (StepContext): the step context
        entries (List[Dict]): the valid language entries
        language (str): report language
        existing (Dict[int, dict] | None): page number to the saved record of a page already answered; None for none
        on_page (Callable[[int, dict], None] | None): called with the page number and the partial result after
            each page sent to the model; None changes nothing

    Outputs:
        Dict - With 'annotations', 'rejected', 'not_run'.

    Raises:
        NotRun - If an unretriable error occurs; the pages answered before it are already given to on_page.
    --------------------------------------------------------------------------
    """
    records: Dict[int, dict] = dict(existing or {})
    valid_codes = {e["code"] for e in entries}
    spelling_value = spelling_code()
    accepted = load_accepted(language)
    
    table_txt = table_text(entries, language)
    
    for i, page_text in enumerate(pages):
        page_num = i + 1
        
        if page_num in records:
            continue
        if not page_text.strip():
            continue
            
        prompt = fill(
            ctx.prompts["language"],
            {
                "LANGUAGE_TABLE": table_txt,
                "SECTION": page_text,
                "LANGUAGE_OF_REPORT": language
            }
        )
        
        answer = None
        last_err = None
        
        for attempt in range(ctx.grade_retries + 1):
            try:
                answer = call(prompt, ctx.schemas["language"])
                break
            except NotRun as e:
                last_err = e
                if not e.retryable:
                    raise
                # retryable, continue loop
        
        if answer is None:
            records[page_num] = {"annotations": [], "rejected": 0, "not_run": True}
        else:
            records[page_num] = _answer_record(answer, page_num, page_text, valid_codes, spelling_value, accepted)
        if on_page is not None:
            on_page(page_num, _partial(records))
        
    return _result(records)


def _answer_record(answer: dict, page_num: int, page_text: str, valid_codes: set,
                   spelling_code_value: Optional[str] = None, accepted: Optional[set] = None) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn the model answer of one page into its record: the findings that name a valid code and quote the page.

    Inputs:
        answer (dict): the model answer, with a `findings` list
        page_num (int): the page number
        page_text (str): the page text the quotes must be found in
        valid_codes (set): the codes of the language table

    Outputs:
        record (dict): {annotations, rejected, not_run: False}; a finding with an unknown code or a quote not in the
        page is counted as rejected; a repeated (code, quote) on the page is kept once.

    Raises:
        None.
    --------------------------------------------------------------------------
    """
    findings = answer.get("findings", [])
    rejected = 0
    rejected_correct = 0
    seen = set()
    # F3: compared case-folded, and a quote is refused when any of its words is an accepted spelling.
    accepted_words = {normalize(word).casefold() for word in (accepted or ())}
    page_annotations = []
    
    for f in findings:
        code = f.get("code")
        quote = f.get("quote", "")
        
        if code not in valid_codes:
            rejected += 1
            continue
            
        # Check if quote is in page
        # We check if normalized quote is a substring of normalized page text
        norm_quote = normalize(quote)
        norm_page = normalize(page_text)
        
        if norm_quote not in norm_page:
            rejected += 1
            continue

        # N1: a spelling finding is refused when its quote is an accepted spelling (either form of a 1990 reform
        # pair) or when its proposal equals the quote: the word is correct, so a finding on it is never a fault.
        quote_words = re.findall(r"\w+", norm_quote.casefold())
        same_word = normalize(f.get("proposed", "")).casefold() == norm_quote.casefold()
        if code == spelling_code_value and (same_word or any(word in accepted_words for word in quote_words)):
            rejected_correct += 1
            continue
            
        key = (code, norm_quote)
        if key in seen:
            continue
        seen.add(key)
        
        proposed = f.get("proposed", "")
        reason = f.get("reason", "")
        
        if proposed:
            comment = f"{proposed} - {reason}" if reason else proposed
        else:
            comment = reason
            
        page_annotations.append({
            "page": page_num,
            "kind": "language",
            "code": code,
            "quote": quote,
            "rect": None,
            "comment": comment
        })
    return {"annotations": page_annotations, "rejected": rejected, "rejected_correct": rejected_correct,
            "not_run": False}
