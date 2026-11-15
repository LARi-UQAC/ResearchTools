import re
import tempfile
from pathlib import Path
from typing import Optional

class LedgerError(ValueError):
    pass

MARKS = [" ", "x", "!"]
NOTE_RE = re.compile(r"^[A-Za-z0-9 _.,:=/+/-]{1,60}$")

def _check_note(note: Optional[str]) -> None:
    if note is None:
        return
    if not NOTE_RE.match(note):
        raise LedgerError(f"Invalid note: {note!r}")

def new_ledger(title: str) -> str:
    """
    Purpose: Create a new ledger with a title and empty notes section.
    Inputs:
        title: str - The title of the ledger.
    Outputs:
        str - The initial ledger text.
    """
    return f"# {title}\n\n## notes\n"

def add_report(text: str, report_id: str, item_ids: list[str]) -> str:
    """
    Purpose: Add a report section with step lines.
    Inputs:
        text: str - The current ledger text.
        report_id: str - The ID of the report.
        item_ids: list[str] - List of item IDs.
    Outputs:
        str - The updated ledger text.
    """
    if f"## {report_id}" in text:
        return text
    
    lines = [f"## {report_id}", "- [ ] prepare"]
    for item_id in item_ids:
        lines.append(f"- [ ] grade {item_id}")
    lines.extend([
        "- [ ] language",
        "- [ ] figures",
        "- [ ] audit",
        "- [ ] assemble"
    ])
    
    return text.rstrip("\n") + "\n" + "\n".join(lines) + "\n"

def add_figures(text: str, report_id: str, figure_ids: list[str]) -> str:
    """
    Purpose: Add figure step lines after the figures line.
    Inputs:
        text: str - The current ledger text.
        report_id: str - The ID of the report.
        figure_ids: list[str] - List of figure IDs.
    Outputs:
        str - The updated ledger text.
    """
    lines = text.splitlines()
    insert_idx = None
    current_report = None
    for i, line in enumerate(lines):
        if line.startswith("## "):
            current_report = line[3:].strip()
        elif current_report == report_id and line.strip() == "- [ ] figures":
            insert_idx = i + 1
            break
    
    if insert_idx is None:
        return text

    new_lines = []
    for fid in figure_ids:
        new_lines.append(f"- [ ] figure {fid}")
    
    # Check if already present
    existing = set()
    for line in lines[insert_idx:]:
        if line.startswith("- [ ] figure "):
            existing.add(line)
        else:
            break
            
    to_insert = [l for l in new_lines if l not in existing]
    if not to_insert:
        return text
        
    lines[insert_idx:insert_idx] = to_insert
    return "\n".join(lines) + "\n"

def parse(text: str) -> list[dict]:
    """
    Purpose: Parse ledger text into a list of step dictionaries.
    Inputs:
        text: str - The ledger text.
    Outputs:
        list[dict] - List of step dictionaries.
    """
    steps = []
    current_report = None
    for line in text.splitlines():
        if line.startswith("## "):
            current_report = line[3:].strip()
        elif line.startswith("- ["):
            # Format: - [ ] label - note
            parts = line.split(" - ", 1)
            label_part = parts[0]
            note = parts[1] if len(parts) > 1 else None
            
            # Extract mark and label
            match = re.match(r"- \[(.)\] (.*)", label_part)
            if match:
                mark = match.group(1)
                label = match.group(2).strip()
                steps.append({
                    "report_id": current_report,
                    "label": label,
                    "mark": mark,
                    "note": note
                })
    return steps

def set_mark(text: str, report_id: str, label: str, mark: str, note: Optional[str] = None) -> str:
    """
    Purpose: Set the mark and optional note for a specific step.
    Inputs:
        text: str - The current ledger text.
        report_id: str - The ID of the report.
        label: str - The label of the step.
        mark: str - The new mark.
        note: Optional[str] - The new note.
    Outputs:
        str - The updated ledger text.
    Raises:
        LedgerError: If report, label, or mark is invalid, or note is invalid.
    """
    if mark not in MARKS:
        raise LedgerError(f"Invalid mark: {mark}")
    _check_note(note)
    
    lines = text.splitlines()
    current_report = None
    found = False
    
    new_lines = []
    for line in lines:
        if line.startswith("## "):
            current_report = line[3:].strip()
        elif line.startswith("- ["):
            parts = line.split(" - ", 1)
            label_part = parts[0]
            if len(label_part) >= 6:
                old_mark = label_part[3]
                old_label = label_part[6:].strip()
                
                if current_report == report_id and old_label == label:
                    new_line = f"- [{mark}] {label}"
                    if note:
                        new_line += f" - {note}"
                    new_lines.append(new_line)
                    found = True
                    continue
        
        new_lines.append(line)
        
    if not found:
        raise LedgerError(f"Step not found: {report_id} {label}")
        
    return "\n".join(new_lines) + "\n"

def first_open(text: str) -> tuple[str, str] | None:
    """
    Purpose: Find the first open step.
    Inputs:
        text: str - The ledger text.
    Outputs:
        tuple[str, str] | None - (report_id, label) or None.
    """
    for step in parse(text):
        if step["mark"] == " ":
            return (step["report_id"], step["label"])
    return None

def counts(text: str) -> dict:
    """
    Purpose: Count steps by mark.
    Inputs:
        text: str - The ledger text.
    Outputs:
        dict - Counts of done, open, blocked.
    """
    c = {"done": 0, "open": 0, "blocked": 0}
    for step in parse(text):
        if step["mark"] == "x":
            c["done"] += 1
        elif step["mark"] == " ":
            c["open"] += 1
        elif step["mark"] == "!":
            c["blocked"] += 1
    return c

def reopen_all(text: str, keep: list[str]) -> str:
    """
    Purpose: Reopen all steps except those in keep.
    Inputs:
        text: str - The ledger text.
        keep: list[str] - List of labels to keep marked.
    Outputs:
        str - The updated ledger text.
    """
    lines = text.splitlines()
    new_lines = []
    for line in lines:
        if line.startswith("- ["):
            parts = line.split(" - ", 1)
            label_part = parts[0]
            if len(label_part) >= 6:
                label = label_part[6:].strip()
                if label not in keep:
                    new_lines.append(f"- [ ] {label}")
                    continue
        new_lines.append(line)
    return "\n".join(new_lines) + "\n"

def add_note(text: str, line: str) -> str:
    """
    Purpose: Add a note to the notes section.
    Inputs:
        text: str - The ledger text.
        line: str - The note text.
    Outputs:
        str - The updated ledger text.
    Raises:
        LedgerError: If note is invalid.
    """
    _check_note(line)
    if "## notes" not in text:
        return text.rstrip("\n") + "\n\n## notes\n" + line + "\n"
    
    lines = text.splitlines()
    idx = lines.index("## notes")
    lines.insert(idx + 1, line)
    return "\n".join(lines) + "\n"

def read(path: Path) -> str:
    """
    Purpose: Read ledger from file.
    Inputs:
        path: Path - Path to file.
    Outputs:
        str - Ledger text.
    """
    return Path(path).read_text(encoding="utf-8")

def write(path: Path, text: str) -> None:
    """
    Purpose: Write ledger to file atomically.
    Inputs:
        path: Path - Path to file.
        text: str - Ledger text.
    Outputs:
        None.
    """
    path = Path(path)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent)
    try:
        with open(fd, 'w', encoding='utf-8') as f:
            f.write(text)
        Path(tmp_path).replace(path)
    except:
        if Path(tmp_path).exists():
            Path(tmp_path).unlink()
        raise
