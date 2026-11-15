import json
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


def language_report(
    pages: List[str],
    call: Callable,
    ctx: StepContext,
    entries: List[Dict],
    language: str
) -> Dict:
    """
    Purpose: Run language check on each page and collect findings.
    Inputs:
        pages: List[str] - Page texts.
        call: Callable - The model call function.
        ctx: StepContext - The step context.
        entries: List[Dict] - The valid language entries.
        language: str - Report language.
    Outputs:
        Dict - With 'annotations', 'rejected', 'not_run'.
    Raises:
        NotRun - If an unretriable error occurs.
    """
    annotations = []
    rejected = 0
    not_run = []
    valid_codes = {e["code"] for e in entries}
    
    table_txt = table_text(entries, language)
    
    for i, page_text in enumerate(pages):
        page_num = i + 1
        
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
            not_run.append(page_num)
            continue
            
        findings = answer.get("findings", [])
        
        # Deduplicate findings on this page
        seen = set()
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
            
        annotations.extend(page_annotations)
        
    return {
        "annotations": annotations,
        "rejected": rejected,
        "not_run": not_run
    }
