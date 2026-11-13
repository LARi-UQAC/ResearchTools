import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

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

def _words_match(word1: str, word2: str) -> bool:
    """
    Purpose: Check if two words match, allowing for minor spelling differences (e.g. accents, endings).
    Inputs:
        word1: str - The first word.
        word2: str - The second word.
    Outputs:
        bool - True if they match.
    """
    if word1 == word2:
        return True
    # Check if one is a prefix of the other (at least 5 chars)
    if len(word1) >= 5 and len(word2) >= 5:
        if word1.startswith(word2[:5]) or word2.startswith(word1[:5]):
            return True
    return False

def _extract_keywords(item: Dict[str, Any], min_word_len: int) -> set:
    """
    Purpose: Extract keywords from an item's title, criteria, and checklist.
    Inputs:
        item: Dict - The item containing title, criteria, checklist.
        min_word_len: int - Minimum length for a word to be considered a keyword.
    Outputs:
        set - A set of normalized keywords.
    """
    texts = [item.get("title", "")]
    texts.extend(item.get("criteria", []))
    texts.extend(item.get("checklist", []))
    
    keywords = set()
    for text in texts:
        # Split by non-alphanumeric characters
        words = re.split(r'[^a-zA-Z0-9]+', text)
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
        PromptError - If a slot is missing from values.
    """
    slots_in_template = set(re.findall(r'\{\{([A-Z_]+)\}\}', template))
    slots_in_values = set(values.keys())
    
    missing_slots = slots_in_template - slots_in_values
    if missing_slots:
        raise PromptError(f"Missing value for slot: {missing_slots.pop()}")

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
    for i, page_text in enumerate(pages):
        lines = page_text.split('\n')
        has_match = False
        for line in lines:
            if line.startswith('#'):
                # Extract words from heading
                heading_words = re.split(r'[^a-zA-Z0-9]+', line)
                for h_word in heading_words:
                    if len(h_word) < min_word_len:
                        continue
                    norm_h_word = _normalize_word(h_word)
                    for k_word in keywords:
                        if _words_match(norm_h_word, k_word):
                            has_match = True
                            break
                    if has_match:
                        break
            if has_match:
                break
        if has_match:
            matching_numbers.append(i + 1)
    
    selected = []
    current_tokens = 0
    for num in matching_numbers:
        block = page_blocks(pages, [num])
        block_tokens = count(block)
        if current_tokens + block_tokens <= budget_tokens:
            selected.append(num)
            current_tokens += block_tokens
        # else: skip page, never cut
        
    return selected

def split_body_and_references(pages: List[str]) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Purpose: Split the report text into body and reference list.
    Inputs:
        pages: List[str] - List of page texts.
    Outputs:
        Tuple[str, List[Dict]] - (body_text, references_list).
    """
    # Build a list of (page_number, line) tuples to track page boundaries
    all_lines = []
    for p_idx, page_text in enumerate(pages):
        page_lines = page_text.split('\n')
        for line in page_lines:
            all_lines.append((p_idx + 1, line))
            
    # Find the reference heading
    # Patterns: "References", "Références", "Bibliographie", optionally numbered, optionally with ##
    ref_heading_pattern = re.compile(r'^(?:#{1,6}\s*)?(?:\d+\.\s*)?(?:References|Références|Bibliographie)\s*$', re.IGNORECASE)
    
    ref_start_idx = -1
    for i, (page_num, line) in enumerate(all_lines):
        if ref_heading_pattern.match(line.strip()):
            ref_start_idx = i
            break
            
    if ref_start_idx == -1:
        # No reference heading found
        body_text = "\n".join([line for _, line in all_lines])
        return body_text, []
        
    body_lines = [line for _, line in all_lines[:ref_start_idx]]
    ref_lines = [(page_num, line) for page_num, line in all_lines[ref_start_idx + 1:]]
    
    body_text = "\n".join(body_lines).strip()
    
    # Parse references
    refs = []
    current_entry_lines = []
    current_start_page = None
    current_page = None
    
    # Entry starts with [n], n., n) or bullet
    entry_start_pattern = re.compile(r'^(\[\d+\]|\d+\.|\d+\)|[-*•])\s*')
    
    for page_num, line in ref_lines:
        stripped_line = line.strip()
        
        # Stop if we hit a new heading of same or higher level
        if stripped_line.startswith('#') and not entry_start_pattern.match(stripped_line):
            if current_entry_lines:
                refs.append({
                    "page": current_start_page,
                    "text": "\n".join(current_entry_lines).strip()
                })
                current_entry_lines = []
            break
            
        # If page changes and line is not an entry start, it might be a new entry (if no markers) or end of previous
        if current_page is not None and page_num != current_page:
             if current_entry_lines and not entry_start_pattern.match(stripped_line):
                 # New page, no marker, so separate
                 refs.append({
                    "page": current_start_page,
                    "text": "\n".join(current_entry_lines).strip()
                 })
                 current_entry_lines = []
                 
        current_page = page_num
        
        is_entry_start = bool(entry_start_pattern.match(stripped_line))
        
        if is_entry_start:
            if current_entry_lines:
                refs.append({
                    "page": current_start_page,
                    "text": "\n".join(current_entry_lines).strip()
                })
            current_entry_lines = [line]
            current_start_page = page_num
        else:
            if stripped_line == "":
                # Blank line separates entries
                if current_entry_lines:
                    refs.append({
                        "page": current_start_page,
                        "text": "\n".join(current_entry_lines).strip()
                    })
                    current_entry_lines = []
            else:
                if not current_entry_lines:
                    current_entry_lines = [line]
                    if current_start_page is None:
                        current_start_page = page_num
                else:
                    current_entry_lines.append(line)
                
    if current_entry_lines:
        refs.append({
            "page": current_start_page,
            "text": "\n".join(current_entry_lines).strip()
        })
        
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
