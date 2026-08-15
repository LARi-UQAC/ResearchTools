"""
paper_extract - read the accepted paper and hand the deck builder a structured inventory.

A talk is built from the paper's own argument, figures, equations and numbers. Doing
that by eye on a multi-file LaTeX thesis is where content silently goes missing: a
`\\input{chapters/results}` that was never opened is a results section that never
reaches the deck.

Preference order, and it matters for quality:

    1. LaTeX source   the argument, the labels and the numbers are all typed
    2. PDF            best effort - two-column layout, maths and tables extract
                      badly, so the deck is only as good as the text layer
    3. plain text     whatever the professor pasted

The PDF path deliberately refuses two cases rather than producing plausible rubbish:
an encrypted file, and a scanned file with no text layer. Both say what to do next.

Usage
-----
    python paper_extract.py main.tex --json
    python paper_extract.py paper.pdf --out inventory.json
    python paper_extract.py main.tex --numbers      # just the number inventory

The number inventory is what `talk_model.py --check-numbers` verifies the deck
against, so a figure on a slide that is in no source sentence is caught before the
room catches it.

Exit codes: 0 read, 1 the extraction looks too thin to trust, 2 a usage or file error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

TAG = "[EXTRACT]"

# Below these the extraction is almost certainly broken rather than the paper short.
MIN_WORDS = 500
MIN_SECTIONS = 3
MAX_INCLUDE_DEPTH = 3

_RE_INPUT = re.compile(r"\\(?:input|include|subfile)\{([^}]+)\}")
_RE_COMMENT = re.compile(r"(?<!\\)%.*$", re.M)
_RE_SECTION = re.compile(
    r"\\(chapter|section|subsection)\*?\{((?:[^{}]|\{[^}]*\})*)\}"
)
_RE_TITLE = re.compile(r"\\title\{((?:[^{}]|\{[^}]*\})*)\}", re.S)
_RE_AUTHOR = re.compile(r"\\author\{((?:[^{}]|\{[^}]*\})*)\}", re.S)
_RE_ABSTRACT = re.compile(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", re.S)
_RE_GRAPHIC = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}")
_RE_FLOAT = re.compile(
    r"\\begin\{(figure|table)\*?\}(.*?)\\end\{\1\*?\}", re.S
)
_RE_LABEL = re.compile(r"\\label\{([^}]+)\}")
_RE_CAPTION = re.compile(r"\\caption\{((?:[^{}]|\{[^}]*\})*)\}", re.S)
_RE_EQUATION = re.compile(
    r"\\begin\{(equation|align|gather)\*?\}(.*?)\\end\{\1\*?\}", re.S
)
_RE_CITE = re.compile(r"\\cite[tp]?\*?(?:\[[^\]]*\])*\{([^}]+)\}")
# A number a speaker would actually say: 95.2, 1 950, 12 %, 0.84, 32.
_RE_NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:[ \u00a0]\d{3})+|\d+(?:[.,]\d+)?)(?![\w])")


def strip_comments(tex: str) -> str:
    """Drop LaTeX comments, keeping escaped percent signs."""
    return _RE_COMMENT.sub("", tex)


def resolve_includes(path: str, depth: int = 0, seen: set | None = None) -> tuple[str, list[str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Inline every \\input, \\include and \\subfile so the rest of the module
        sees one document. A thesis keeps its chapters in separate files, and a
        chapter that is never opened is a section that never reaches the deck.

    Inputs:
        path (str): the main .tex
        depth (int): current recursion depth; stops at MAX_INCLUDE_DEPTH
        seen (set): files already inlined, so a circular include terminates

    Outputs:
        (text, warnings): the flattened source and one warning per file that
            could not be found or was cut off by the depth limit
    --------------------------------------------------------------------------
    """
    seen = set() if seen is None else seen
    warnings: list[str] = []
    real = os.path.abspath(path)
    if real in seen:
        return "", [f"{TAG} circular include ignored: {os.path.basename(path)}"]
    if depth > MAX_INCLUDE_DEPTH:
        return "", [f"{TAG} include depth over {MAX_INCLUDE_DEPTH}, stopped at "
                    f"{os.path.basename(path)}"]
    seen.add(real)

    with open(real, encoding="utf8", errors="replace") as fh:
        text = strip_comments(fh.read())
    base = os.path.dirname(real)

    def substitute(match: re.Match) -> str:
        name = match.group(1).strip()
        candidate = name if name.endswith(".tex") else name + ".tex"
        target = candidate if os.path.isabs(candidate) else os.path.join(base, candidate)
        if not os.path.exists(target):
            warnings.append(f"{TAG} missing include: {name}")
            return f"% missing include: {name}"
        inner, inner_warnings = resolve_includes(target, depth + 1, seen)
        warnings.extend(inner_warnings)
        return inner

    return _RE_INPUT.sub(substitute, text), warnings


def _clean(value: str) -> str:
    """Strip the LaTeX markup a title or caption carries, for reading."""
    value = re.sub(r"\\(?:thanks|footnote)\{[^}]*\}", "", value)
    # Escaped punctuation first: \& is an ampersand, not a control word.
    value = re.sub(r"\\([&%_#$])", r"\1", value)
    value = re.sub(r"\\[a-zA-Z]+\*?", " ", value)
    value = value.replace("{", " ").replace("}", " ").replace("~", " ")
    return re.sub(r"\s+", " ", value).strip()


def sections_of(tex: str) -> list[dict]:
    """
    --------------------------------------------------------------------------
    Purpose:
        List the document's sections with their text, which is what the slide
        budget is allocated across.

    Inputs:
        tex (str): flattened LaTeX

    Outputs:
        sections (list): level, title, word count and body text, in order
    --------------------------------------------------------------------------
    """
    marks = list(_RE_SECTION.finditer(tex))
    sections = []
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(tex)
        body = tex[mark.end():end]
        sections.append(
            {
                "level": mark.group(1),
                "title": _clean(mark.group(2)),
                "words": len(_clean(body).split()),
                "text": body.strip(),
            }
        )
    return sections


def floats_of(tex: str) -> list[dict]:
    """Figures and tables, with their label, caption and asset paths."""
    out = []
    for match in _RE_FLOAT.finditer(tex):
        kind, body = match.group(1), match.group(2)
        label = _RE_LABEL.search(body)
        caption = _RE_CAPTION.search(body)
        out.append(
            {
                "kind": kind,
                "label": label.group(1) if label else None,
                "caption": _clean(caption.group(1)) if caption else None,
                "assets": _RE_GRAPHIC.findall(body),
            }
        )
    return out


def equations_of(tex: str) -> list[dict]:
    """Numbered equations, with their label and body."""
    out = []
    for match in _RE_EQUATION.finditer(tex):
        body = match.group(2)
        label = _RE_LABEL.search(body)
        out.append(
            {
                "env": match.group(1),
                "label": label.group(1) if label else None,
                "tex": re.sub(r"\s+", " ", _RE_LABEL.sub("", body)).strip(),
            }
        )
    return out


def numbers_of(text: str) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Collect every number the source states, normalised so a deck can be
        checked against it. This is the evidence base for the rule that no
        number appears on a slide unless it is in the paper.

    Inputs:
        text (str): source text, LaTeX or plain

    Outputs:
        numbers (list): unique normalised numeric strings, sorted
    --------------------------------------------------------------------------
    """
    found = set()
    for raw in _RE_NUMBER.findall(text):
        found.add(normalise_number(raw))
    return sorted(found)


def normalise_number(raw: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Put a number in one shape so "1 950", "1950", "95,2" and "95.2" compare
        equal. A French manuscript and an English slide write the same value
        differently, and a false hallucination alarm is worse than none.

    Inputs:
        raw (str): the number as written

    Outputs:
        value (str): digits, with a dot decimal separator and no thousands mark
    --------------------------------------------------------------------------
    """
    value = raw.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    if value.count(".") > 1:                    # 1.234.567 style thousands marks
        value = value.replace(".", "")
    if "." in value:
        value = value.rstrip("0").rstrip(".") or "0"
    return value


def read_pdf(path: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Pull the text layer out of a PDF, refusing the two cases that produce
        plausible rubbish: an encrypted file and a scan with no text layer.
        Reuses the extract-statistic skill's reader when it is importable rather
        than adding a second PDF stack to the repo.

    Inputs:
        path (str): the PDF

    Outputs:
        text (str): the extracted text
    --------------------------------------------------------------------------
    """
    try:
        import fitz  # PyMuPDF, already a dependency of extract-statistic
    except ImportError as exc:
        raise RuntimeError(
            f"{TAG} reading a PDF needs PyMuPDF (pip install pymupdf), or give the "
            "LaTeX source instead, which extracts far better"
        ) from exc

    doc = fitz.open(path)
    if doc.is_encrypted:
        raise RuntimeError(
            f"{TAG} {path} is encrypted. Supply the decrypted file or the LaTeX source."
        )
    text = "".join(page.get_text() for page in doc)
    if len(text.strip()) < 100:
        raise RuntimeError(
            f"{TAG} {path} has no usable text layer (a scan). OCR it, or give the LaTeX "
            "source."
        )
    return text


def extract(path: str) -> dict:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the inventory the deck is authored from, whatever the input format.

    Inputs:
        path (str): a .tex, .pdf, .md or .txt

    Outputs:
        inventory (dict): source kind, meta, sections, floats, equations,
            citations, numbers, and the warnings worth showing the professor
    --------------------------------------------------------------------------
    """
    suffix = os.path.splitext(path)[1].lower()
    warnings: list[str] = []

    if suffix == ".tex":
        text, warnings = resolve_includes(path)
        kind = "latex"
    elif suffix == ".pdf":
        text = read_pdf(path)
        kind = "pdf"
        warnings.append(
            f"{TAG} PDF extraction is best effort: two-column layout, maths and tables "
            "come out unreliable. Prefer the LaTeX source when it exists."
        )
    else:
        with open(path, encoding="utf8", errors="replace") as fh:
            text = fh.read()
        kind = "text"

    title = _RE_TITLE.search(text)
    author = _RE_AUTHOR.search(text)
    abstract = _RE_ABSTRACT.search(text)
    sections = sections_of(text) if kind == "latex" else []
    words = len(_clean(text).split()) if kind == "latex" else len(text.split())

    if words < MIN_WORDS:
        warnings.append(
            f"{TAG} only {words} words extracted (expected at least {MIN_WORDS}); the "
            "extraction is probably incomplete"
        )
    if kind == "latex" and len(sections) < MIN_SECTIONS:
        warnings.append(
            f"{TAG} only {len(sections)} section(s) found (expected at least "
            f"{MIN_SECTIONS}); check the \\input paths"
        )

    return {
        "source": os.path.abspath(path),
        "kind": kind,
        "meta": {
            "title": _clean(title.group(1)) if title else None,
            "authors": _clean(author.group(1)) if author else None,
            "abstract": _clean(abstract.group(1)) if abstract else None,
        },
        "words": words,
        "sections": [{k: v for k, v in s.items() if k != "text"} for s in sections],
        "floats": floats_of(text),
        "equations": equations_of(text),
        "citations": sorted({key.strip() for group in _RE_CITE.findall(text)
                             for key in group.split(",")}),
        "numbers": numbers_of(text),
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extract a paper's argument, floats and numbers.")
    ap.add_argument("paper")
    ap.add_argument("--out", help="write the inventory here instead of stdout")
    ap.add_argument("--numbers", action="store_true", help="print the number inventory only")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    try:
        inventory = extract(args.paper)
    except (OSError, RuntimeError) as exc:
        print(f"{TAG} {exc}", file=sys.stderr)
        return 2

    if args.numbers:
        print("\n".join(inventory["numbers"]))
        return 0

    text = json.dumps(inventory, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf8") as fh:
            fh.write(text + "\n")
    elif args.json:
        print(text)
    else:
        meta = inventory["meta"]
        print(f"{TAG} {inventory['kind']} source, {inventory['words']} words")
        print(f"{TAG} title: {meta['title'] or '(not found)'}")
        print(f"{TAG} {len(inventory['sections'])} section(s), "
              f"{len(inventory['floats'])} float(s), "
              f"{len(inventory['equations'])} equation(s), "
              f"{len(inventory['citations'])} citation key(s), "
              f"{len(inventory['numbers'])} distinct number(s)")
        for section in inventory["sections"]:
            print(f"{TAG}   {section['level']:<11} {section['words']:>5} w  {section['title']}")

    for line in inventory["warnings"]:
        print(line, file=sys.stderr)
    return 1 if any("incomplete" in w or "section(s) found" in w
                    for w in inventory["warnings"]) else 0


if __name__ == "__main__":
    sys.exit(main())
