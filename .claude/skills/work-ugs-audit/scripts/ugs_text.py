import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

# R0: No numeric literals in code, but regex patterns and constants are allowed if they are not "thresholds" in the logic sense.
# However, the audit specifically flagged the prefix length 5 in _words_match.
# We define regex patterns here.

WORD_SPLIT_RE = re.compile(r'[^a-zA-Z0-9\u00C0-\u024F]+')
REF_ENTRY_START_RE = re.compile(r'^(\[\d+\]|\d+\.|\d+\)|[-*•])\s*')
REF_HEADING_RE = re.compile(r'^(?:#{1,6}\s*)?(?:\d+\.\s*)?(?:References|Références|Bibliographie)\s*$', re.IGNORECASE)

NUMBERED_LINE_RE = re.compile(r'^\d+(?:\.\d+)*\.?\s+\S')
YEAR_RE = re.compile(r'\b(?:19|20)\d{2}\b')
# Longest numbered line still read as a section heading ("7. Conclusion"). Author's choice, unmeasured:
# a numbered reference "1. Smith, J. 2020. A paper." is longer, holds a comma and a year.
MAX_NUMBERED_HEADING_CHARS = 40


def _is_numbered_heading(stripped: str) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Tell a numbered section heading ("7. Conclusion") from a numbered reference ("1. Smith, J. 2020.").

    Inputs:
        stripped (str): a line without surrounding blanks

    Outputs:
        heading (bool): True for a short numbered line with no comma and no year.
    --------------------------------------------------------------------------
    """
    return (bool(NUMBERED_LINE_RE.match(stripped)) and len(stripped) <= MAX_NUMBERED_HEADING_CHARS
            and ',' not in stripped and not YEAR_RE.search(stripped))


class PromptError(ValueError):
    """Raised when a prompt operation fails."""
    pass

@dataclass
class StepContext:
    prompts: Dict[str, str]
    schemas: Dict[str, Any]
    levels: Dict[str, float]
    window_tokens: int
    reserve_tokens: int
    count: Callable[[str], int]
    grade_retries: int
    audit_retries: int
    min_word_len: int
    # Optional action emitter (ugs_events.make_emitter): None keeps every step silent, as before plan 10.
    emit: Optional[Callable[..., None]] = None

def _normalize_word(word: str) -> str:
    """
    Purpose: Normalize a word for comparison by lowercasing and removing accents.
    Inputs:
        word: str - The word to normalize.
    Outputs:
        str - The normalized word.
    """
    word = word.lower()
    nfkd_form = unicodedata.normalize('NFKD', word)
    return ''.join([c for c in nfkd_form if not unicodedata.combining(c)])

def _words_match(word1: str, word2: str, prefix_len: int) -> bool:
    """
    Purpose: Check if two words match, allowing for minor spelling differences (e.g. accents, endings).
    Inputs:
        word1: str - The first word (normalized).
        word2: str - The second word (normalized).
        prefix_len: int - Minimum length for prefix matching.
    Outputs:
        bool - True if they match.
    """
    if word1 == word2:
        return True
    if len(word1) >= prefix_len and len(word2) >= prefix_len:
        if word1.startswith(word2[:prefix_len]) or word2.startswith(word1[:prefix_len]):
            return True
    return False

def _extract_keywords(item: Dict[str, Any], min_word_len: int) -> set:
    """
    Purpose: Extract keywords from an item's title, criteria, checklist and exact section text.
    Inputs:
        item: Dict - The item containing title, criteria, checklist and, for a rubric split by code, text.
        min_word_len: int - Minimum length for a word to be considered a keyword.
    Outputs:
        set - A set of normalized keywords.
    """
    texts = [item.get("title", "")]
    texts.extend(item.get("criteria", []))
    texts.extend(item.get("checklist", []))
    if item.get("text"):
        texts.append(item["text"])
    
    keywords = set()
    for text in texts:
        words = WORD_SPLIT_RE.split(text)
        for word in words:
            if len(word) >= min_word_len:
                keywords.add(_normalize_word(word))
    return keywords

def fill(template: str, values: Dict[str, str]) -> str:
    """
    Purpose: Replace every {{NAME}} slot in the template with the corresponding value.
    Inputs:
        template: str - The template string.
        values: Dict[str, str] - Mapping of slot names to values.
    Outputs:
        str - The filled template.
    Raises:
        PromptError - If a slot is missing from values or a value is provided for an unknown slot.
    """
    slots_in_template = set(re.findall(r'\{\{([A-Z_]+)\}\}', template))
    values_keys = set(values.keys())
    
    missing_slots = slots_in_template - values_keys
    if missing_slots:
        raise PromptError(f"Missing value for slot: {missing_slots.pop()}")
        
    for key in values_keys:
        if key not in slots_in_template:
            raise PromptError(f"Unknown slot in values: {key}")

    def replace_slot(match: re.Match) -> str:
        name = match.group(1)
        return values[name]

    return re.sub(r'\{\{([A-Z_]+)\}\}', replace_slot, template)

def prompt_section(text: str, name: str) -> str:
    """
    Purpose: Extract the body under the heading '## name' up to the next '## ' heading.
    Inputs:
        text: str - The full text.
        name: str - The name of the section.
    Outputs:
        str - The section body.
    Raises:
        PromptError - If the section is not found.
    """
    # Match ## name (allowing optional whitespace)
    pattern = rf'^##\s+{re.escape(name)}\s*$(.*?)(?=^##\s|\Z)'
    match = re.search(pattern, text, flags=re.MULTILINE | re.DOTALL)
    if not match:
        raise PromptError(f"Section not found: {name}")
    return match.group(1).strip()

def page_blocks(pages: List[str], numbers: List[int]) -> str:
    """
    Purpose: Create a string of page blocks for the given page numbers.
    Inputs:
        pages: List[str] - List of page texts (0-indexed).
        numbers: List[int] - List of 1-based page numbers.
    Outputs:
        str - The concatenated blocks.
    """
    blocks = []
    for num in numbers:
        if 1 <= num <= len(pages):
            blocks.append(f"### Page {num}\n{pages[num-1]}")
    return "\n".join(blocks)

def select_pages(item: Dict[str, Any], pages: List[str], budget_tokens: int, count: Callable[[str], int], min_word_len: int) -> List[int]:
    """
    Purpose: Select pages that fit the token budget, prioritizing those with matching headings.
    Inputs:
        item: Dict - The grading item.
        pages: List[str] - List of page texts.
        budget_tokens: int - The token budget.
        count: Callable[[str], int] - Function to count tokens.
        min_word_len: int - Minimum word length for matching.
    Outputs:
        List[int] - List of 1-based page numbers selected.
    """
    all_numbers = list(range(1, len(pages) + 1))
    all_blocks = page_blocks(pages, all_numbers)
    if count(all_blocks) <= budget_tokens:
        return all_numbers

    keywords = _extract_keywords(item, min_word_len)
    
    # Filter pages that have a heading matching keywords
    matching_numbers = []
    hits: Dict[int, int] = {}
    for i, page_text in enumerate(pages):
        lines = page_text.split('\n')
        has_match = False
        hit_words = set()
        for line in lines:
            # Headings might not start with # in all cases, but usually do in markdown.
            # The test `test_accented_heading_matches_an_unaccented_word` expects "Résumé" to match "Resume".
            # If the line is "## Résumé", we extract "Résumé", normalize to "resume".
            # Keyword "Resume" normalizes to "resume". Match.
            
            # We should check ALL lines, not just those starting with #, 
            # in case the "heading" is just a bold line or something.
            # But the spec says "matching headings".
            # Let's assume lines starting with # or just short lines that look like titles.
            
            # Let's stick to lines that look like headings (start with #) OR 
            # if the page text is short, maybe the whole page is a heading?
            # No, let's assume standard markdown headings.
            
            if line.startswith('#'):
                heading_words = WORD_SPLIT_RE.split(line)
                for h_word in heading_words:
                    if len(h_word) < min_word_len:
                        continue
                    norm_h_word = _normalize_word(h_word)
                    for k_word in keywords:
                        if _words_match(norm_h_word, k_word, min_word_len):
                            has_match = True
                            hit_words.add(k_word)
        if has_match:
            matching_numbers.append(i + 1)
            hits[i + 1] = len(hit_words)

    # A rubric section of hundreds of words gives many keywords, so most headings can match one of them:
    # the pages whose headings match the most distinct keywords are kept first, and the result is in page order.
    ranked = sorted(matching_numbers, key=lambda number: (-hits[number], number))
    selected = []
    current_tokens = 0
    for num in ranked:
        block = page_blocks(pages, [num])
        block_tokens = count(block)
        if current_tokens + block_tokens <= budget_tokens:
            selected.append(num)
            current_tokens += block_tokens
        # else: skip page, never cut

    return sorted(selected)

def split_body_and_references(pages: List[str]) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Purpose: Split the report text into body and reference list.
    Inputs:
        pages: List[str] - List of page texts.
    Outputs:
        Tuple[str, List[Dict]] - (body_text, references_list).
    """
    all_lines = []
    for p_idx, page_text in enumerate(pages):
        page_lines = page_text.split('\n')
        for line in page_lines:
            all_lines.append((p_idx + 1, line))
            
    ref_start_idx = -1
    for i, (page_num, line) in enumerate(all_lines):
        if REF_HEADING_RE.match(line.strip()):
            ref_start_idx = i
            break
            
    if ref_start_idx == -1:
        body_text = "\n".join([line for _, line in all_lines])
        return body_text, []
        
    body_lines = [line for _, line in all_lines[:ref_start_idx]]
    ref_lines = [(page_num, line) for page_num, line in all_lines[ref_start_idx + 1:]]
    
    body_text = "\n".join(body_lines).strip()
    
    refs = []
    current_entry_lines = []
    current_start_page = None
    ref_heading_text = all_lines[ref_start_idx][1].strip()
    ref_level = len(ref_heading_text) - len(ref_heading_text.lstrip('#'))

    def is_heading(line: str, prev_line: str = "") -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        if stripped.startswith('#'):
            # Only a heading of the same or a higher level ends the list (fewer or equal hashes).
            hashes = len(stripped) - len(stripped.lstrip('#'))
            return ref_level == 0 or hashes <= ref_level
        # Check for numbered headings like "7. Conclusion"
        if _is_numbered_heading(stripped):
            return True
        
        # Heuristic for "Next section" type headings:
        # Must be short, capitalized, not a reference, not indented.
        # AND the previous line should look like a completed sentence (ends with .)
        if (len(stripped) < 20 and 
            stripped[0].isupper() and 
            not REF_ENTRY_START_RE.match(stripped) and
            not line.startswith(' ') and
            prev_line.strip().endswith('.')):
            return True
            
        return False

    def finalize_entry():
        # An entry carries the page where its first line stands.
        if current_entry_lines:
            refs.append({
                "page": current_start_page,
                "text": "\n".join(current_entry_lines).strip()
            })
        current_entry_lines.clear()

    prev_line = ""
    for page_num, line in ref_lines:
        stripped_line = line.strip()

        if is_heading(line, prev_line):
            break

        if REF_ENTRY_START_RE.match(stripped_line):
            finalize_entry()
            current_entry_lines.append(line)
            current_start_page = page_num
        elif stripped_line == "":
            finalize_entry()
        else:
            if not current_entry_lines:
                current_start_page = page_num
            current_entry_lines.append(line)
        prev_line = line

    finalize_entry()

    return body_text, refs

def detect_language(pages: List[str], hints: Dict[str, List[str]]) -> str:
    """
    Purpose: Detect the language of the report based on word frequency hints.
    Inputs:
        pages: List[str] - List of page texts.
        hints: Dict[str, List[str]] - Mapping of language code to list of common words.
    Outputs:
        str - 'fr' or 'en'.
    """
    text = " ".join(pages).lower()
    words = re.findall(r'\b\w+\b', text)
    
    scores = {}
    for lang, hint_words in hints.items():
        hint_set = set(hint_words)
        score = sum(1 for w in words if w in hint_set)
        scores[lang] = score
        
    fr_score = scores.get('fr', 0)
    en_score = scores.get('en', 0)
    
    if fr_score > en_score:
        return 'fr'
    else:
        return 'en'

def load_hints(path: Path) -> Dict[str, List[str]]:
    """
    Purpose: Load language hints from a JSON file.
    Inputs:
        path: Path - Path to the JSON file.
    Outputs:
        Dict[str, List[str]] - The hints.
    Raises:
        PromptError - If a required key is missing.
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        raise PromptError(f"File not found: {path}")
        
    required_keys = ['fr', 'en']
    for key in required_keys:
        if key not in data:
            raise PromptError(f"Missing key in hints file: {key}")
        if 'value' not in data[key]:
            raise PromptError(f"Missing 'value' in hints for: {key}")
            
    return {key: data[key]['value'] for key in required_keys}

def read_pages(work_dir: Path, report_id: str) -> List[str]:
    """
    Purpose: Read pages of a report in numeric order.
    Inputs:
        work_dir: Path - Working directory.
        report_id: str - Report ID (e.g., R01).
    Outputs:
        List[str] - List of page texts.
    Raises:
        PromptError - If no pages are found.
    """
    pages_dir = work_dir / report_id / "pages"
    if not pages_dir.exists():
        raise PromptError(f"Pages directory not found: {pages_dir}")
        
    page_files = list(pages_dir.glob("p*.md"))
    if not page_files:
        raise PromptError(f"No pages found in: {pages_dir}")
        
    # Sort by numeric part
    def sort_key(p: Path) -> int:
        match = re.search(r'p(\d+)\.md', p.name)
        return int(match.group(1)) if match else 0
        
    page_files.sort(key=sort_key)
    
    pages = []
    for p in page_files:
        pages.append(p.read_text(encoding='utf-8'))
        
    return pages

def load_prompts(prompts_dir: Path) -> Dict[str, str]:
    """
    Purpose: Load all markdown prompts from a directory.
    Inputs:
        prompts_dir: Path - Directory containing prompt files.
    Outputs:
        Dict[str, str] - Mapping of file stem to text.
    """
    prompts = {}
    for p in prompts_dir.glob("*.md"):
        prompts[p.stem] = p.read_text(encoding='utf-8')
    return prompts

def load_schemas(path: Path, required: List[str]) -> Dict[str, Any]:
    """
    Purpose: Load JSON schemas and verify required keys.
    Inputs:
        path: Path - Path to the JSON file.
        required: List[str] - List of required keys.
    Outputs:
        Dict[str, Any] - The schemas.
    Raises:
        PromptError - If a required key is missing.
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        raise PromptError(f"File not found: {path}")
        
    for key in required:
        if key not in data:
            raise PromptError(f"Missing required schema key: {key}")
            
    return data
