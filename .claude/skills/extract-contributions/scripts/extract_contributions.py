"""
extract_contributions - subcommand-free CLI: pull the stated scientific
contribution of a paper out of its full text, so a citation can be checked
against what the paper actually claims rather than against its abstract.

Stage: reference validation, after download_pdf.py has put the full text in
refs/. Reuses the extract-statistic skill's extract_text.py for the PDF and
HTML readers rather than re-implementing them (R18: one owner per capability).

Why it exists. Measured 2026-09-12 on the BuildingGIS MITACS proposal:
fourteen references were retained, and their claims written into the text, on
the strength of their ABSTRACT alone. An abstract states what a paper is about;
it does not always state what the paper contributes, and the sentence a citing
author needs ("this is the first method that...", "we propose X, which unlike
Y...") often lives only in the introduction's contributions paragraph. Six of
those fourteen "full texts" were in fact one-page publisher previews, so even
the abstract-level check had been run on a stub.

Output is a JSON record per paper: the sentences that state a contribution,
where each was found, and what kind of claim it makes. It answers "what does
this paper say it contributes"; judging whether the citing sentence is faithful
to that is the caller's work, not the script's.
"""

import argparse
import json
import logging
import os
import re
import sys
from functools import lru_cache
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_EXTRACT_TEXT_DIR = os.path.normpath(
    os.path.join(_HERE, "..", "..", "extract-statistic", "scripts"))
sys.path.insert(0, _EXTRACT_TEXT_DIR)

try:
    import extract_text
except ImportError as exc:  # pragma: no cover - the sibling skill must be present
    print("ERROR: cannot import extract_text from %s (%s)" % (_EXTRACT_TEXT_DIR, exc),
          file=sys.stderr)
    sys.exit(1)

logger = logging.getLogger(__name__)

_CONFIG_PATH = os.path.join(_HERE, "contribution_markers.json")


@lru_cache(maxsize=4096)
def deligature(phrase: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return the spelling a phrase takes once a PDF extractor has dropped the
        fi and fl ligatures, so a marker written in correct English still
        matches damaged text.

    Inputs:
        phrase (str): a lower-cased marker phrase.

    Outputs:
        damaged (str): the same phrase with "fi" and "fl" reduced to "f".

    Measured 2026-09-13 on the BuildingGIS refs/ corpus: pymupdf4llm renders
    Elsevier PDFs as "this paper fnds", "fll this gap", "the frst study",
    "signifcantly". The text is damaged, not the marker, so the marker is
    damaged the same way and tried a second time. Repairing the text instead
    would mean guessing where an "i" belongs, which is not recoverable.
    --------------------------------------------------------------------------
    """
    return phrase.replace("fi", "f").replace("fl", "f")


def phrase_in(phrase: str, low: str) -> bool:
    """True when the phrase appears in `low`, in its correct or damaged spelling."""
    if phrase in low:
        return True
    damaged = deligature(phrase)
    return damaged != phrase and damaged in low


def load_markers(path: str = _CONFIG_PATH) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read the marker catalogue. The phrases that announce a contribution are
        DATA, not code (R6): they differ by discipline and by decade, and a
        reviewer must be able to extend them without touching this module.

    Inputs:
        path (str): the JSON catalogue beside this script.

    Outputs:
        markers (Dict): {"kinds": {kind: [phrase, ...]}, "caps": {...}}.

    A missing or unparsable catalogue is an explicit error naming the file
    (R3): scanning with an empty marker set would return "no contribution
    found" for every paper, which reads like a measurement and is not one.
    --------------------------------------------------------------------------
    """
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise SystemExit("ERROR: marker catalogue unreadable: %s (%s)" % (path, exc))
    if not data.get("kinds"):
        raise SystemExit("ERROR: marker catalogue has no 'kinds': %s" % path)
    return data


# Closing marks that may stand between a terminator and the next sentence, and
# opening marks the next sentence may begin with.
_CLOSERS = "\"'\u201d\u2019\u00bb)\\]"
_OPENERS = "\"'\u201c\u2018\u00ab("
_SENTENCE_BOUNDARY = re.compile(
    r"(?:(?<=[.!?])|(?<=[.!?][" + _CLOSERS + r"]))\s+(?=[" + _OPENERS + r"]?[A-Z(])")


def split_sentences(text: str) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Split prose into sentences, tolerating the abbreviations and decimal
        numbers that a naive split on '.' would cut in the middle.

    Inputs:
        text (str): extracted full text.

    Outputs:
        sentences (List[str]): whitespace-normalised sentences.
    --------------------------------------------------------------------------
    """
    text = re.sub(r"\s+", " ", text)
    # Protect the common abbreviations and any digit.digit before splitting.
    guarded = re.sub(r"\b(e\.g|i\.e|et al|vs|cf|Fig|Eq|Sec|Ref|No|Dr|Prof)\.",
                     lambda m: m.group(1) + "\x00", text)
    # Replacement is a NORMAL string: in a raw one, \x00 is four literal
    # characters and re rejects it as a bad escape in the template.
    guarded = re.sub(r"(\d)\.(\d)", "\\1\x00\\2", guarded)
    # A sentence may end on a closing quote or bracket rather than on the
    # terminator itself. Measured 2026-09-13 on davis2021upzonings:
    # '... pursuant to state policy." Despite these valuable contributions ...'
    # came back as ONE sentence, so the paper's own gap statement was handed to
    # the reader welded to a clause about other authors. re allows only a
    # fixed-width lookbehind, hence two of them in an alternation; putting the
    # closing quote in the pattern itself would let re.split CONSUME it, which
    # deletes it from the sentence it closes.
    parts = re.split(_SENTENCE_BOUNDARY, guarded)
    return [p.replace("\x00", ".").strip() for p in parts if p.strip()]


def scan_contributions(text: str, markers: dict[str, Any]) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Find the sentences in which the paper states its own contribution, and
        label each by the kind of claim it makes.

    Inputs:
        text (str): the paper's full text.
        markers (Dict): the catalogue from load_markers.

    Outputs:
        result (Dict): {"sentences": [{"kind", "marker", "sentence",
            "position"}], "kinds_found": [...], "sentence_count": int,
            "truncated": bool}.

    `position` is the sentence index divided by the sentence count, so a caller
    can tell a contributions paragraph in the introduction (near 0.1) from a
    claim restated in the conclusion (near 0.9) without needing the page
    numbers, which the text extractors do not preserve.
    --------------------------------------------------------------------------
    """
    caps = markers.get("caps", {})
    max_hits = int(caps.get("max_sentences", 40))
    min_words = int(caps.get("min_sentence_words", 6))
    max_words = int(caps.get("max_sentence_words", 80))
    # Boilerplate that carries a marker word without ever making a claim. An
    # Elsevier CRediT block and an acknowledgement both contain "contribution",
    # so without this the contribution markers fire in every Elsevier paper
    # (measured 2026-09-13 on agbossou2026nolandtake).
    exclusions = tuple(markers.get("exclusions", {}).get("phrases", []))

    sentences = split_sentences(text)
    total = len(sentences) or 1
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, sentence in enumerate(sentences):
        words = sentence.split()
        if not (min_words <= len(words) <= max_words):
            continue
        low = sentence.lower()
        if any(phrase_in(x, low) for x in exclusions):
            continue
        for kind, phrases in markers["kinds"].items():
            hit = next((p for p in phrases if phrase_in(p, low)), None)
            if not hit:
                continue
            key = sentence[:120]
            if key in seen:
                break
            seen.add(key)
            hits.append({
                "kind": kind,
                "marker": hit,
                "sentence": sentence,
                "position": round(index / total, 3),
            })
            break
        if len(hits) >= max_hits:
            return {"sentences": hits, "kinds_found": sorted({h["kind"] for h in hits}),
                    "sentence_count": total, "truncated": True}

    return {"sentences": hits, "kinds_found": sorted({h["kind"] for h in hits}),
            "sentence_count": total, "truncated": False}


def read_any(path: str) -> str:
    """Read a PDF or a text-like file through the extract-statistic readers."""
    if path.lower().endswith(".pdf"):
        text, _tables = extract_text.read_pdf(path)
        return text
    return extract_text.read_textlike(path)


def analyse_file(path: str, markers: dict[str, Any],
                 text: str | None = None) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Produce one record for one full-text file, including the refusal cases.

    Inputs:
        path (str): a .pdf / .html / .md / .txt full text.
        markers (Dict): the catalogue.

    Outputs:
        record (Dict): {"citekey", "file", "chars", "status", ...}. `status` is
            "ok", "empty" when no text could be extracted, or "no-contribution"
            when text was read but no marker matched. The three are kept
            distinct because a paper whose text could not be read and a paper
            that states no contribution are different findings, and merging
            them would let an extraction failure read as a property of the
            paper.
    --------------------------------------------------------------------------
    """
    citekey = os.path.splitext(os.path.basename(path))[0]
    if text is None:
        try:
            text = read_any(path)
        except Exception as exc:                 # noqa: BLE001 - reported, not raised
            return {"citekey": citekey, "file": os.path.basename(path), "chars": 0,
                    "status": "unreadable", "reason": str(exc)[:200], "sentences": []}

    text = text or ""
    if len(text.strip()) < int(markers.get("caps", {}).get("min_text_chars", 500)):
        return {"citekey": citekey, "file": os.path.basename(path), "chars": len(text),
                "status": "empty",
                "reason": "less text than a full paper carries; a preview or a scan?",
                "sentences": []}

    found = scan_contributions(text, markers)
    return {
        "citekey": citekey,
        "file": os.path.basename(path),
        "chars": len(text),
        "status": "ok" if found["sentences"] else "no-contribution",
        "sentence_count": found["sentence_count"],
        "kinds_found": found["kinds_found"],
        "truncated": found["truncated"],
        "sentences": found["sentences"],
    }


_CITE_RE = re.compile(r"\\cite[tp]?\*?(?:\[[^\]]*\])*\{([^}]*)\}")

# A sentence may end on a closing mark, and the next one may open on a LaTeX
# macro (\added, \cite) rather than on a capital letter.
_TEX_BOUNDARY = re.compile(
    r"(?:(?<=[.!?])|(?<=[.!?][" + _CLOSERS + r"]))\s+(?=[" + _OPENERS + r"]?[A-Z\\])")

# Structure is a sentence boundary too. \label and \caption are deliberately
# NOT here: they sit INSIDE a sentence, and splitting on them would cut it.
_TEX_STRUCT = re.compile(
    r"\\(?:section|subsection|subsubsection|paragraph|item|begin|end)\*?(?:\{[^}]*\})?"
    r"|\\\\")


def strip_tex_comments(text: str) -> str:
    r"""
    --------------------------------------------------------------------------
    Purpose:
        Blank out every LaTeX comment while keeping the text the same LENGTH,
        so an offset computed on the result still points at the same character
        of the file and a line number stays exact.

    Inputs:
        text (str): the raw .tex source.

    Outputs:
        cleaned (str): same length, comment characters replaced by spaces.

    An escaped percent (\\%) is not a comment and is left alone.
    --------------------------------------------------------------------------
    """
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":                    # a backslash escapes the next character
            i += 2
            continue
        if ch == "%":
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
            continue
        i += 1
    return "".join(out)


def _display(fragment: str) -> str:
    """Collapse whitespace so a sentence spanning source lines reads as one."""
    return re.sub(r"\s+", " ", fragment).strip()


def citing_sentences(tex: str) -> dict[str, list[dict[str, Any]]]:
    r"""
    --------------------------------------------------------------------------
    Purpose:
        For every \cite{} in a manuscript, return the sentence that carries it,
        so the claim the manuscript makes can be read beside the claim the
        cited paper makes.

    Inputs:
        tex (str): the raw .tex source.

    Outputs:
        by_key (Dict[str, List[Dict]]): citekey -> [{"line", "sentence"}, ...],
            one entry per occurrence, in document order.

    Comments are blanked rather than removed, so the reported line number is the
    line of the file and not of a rewritten copy. A multi-key \cite{a,b} yields
    the same sentence under each key, which is correct: the sentence asserts
    something of both papers.
    --------------------------------------------------------------------------
    """
    clean = strip_tex_comments(tex)
    bounds = [0]
    bounds += [m.end() for m in _TEX_BOUNDARY.finditer(clean)]
    bounds += [m.end() for m in re.finditer(r"\n\s*\n", clean)]
    for m in _TEX_STRUCT.finditer(clean):
        bounds += [m.start(), m.end()]
    bounds.append(len(clean))
    bounds = sorted(set(bounds))

    by_key: dict[str, list[dict[str, Any]]] = {}
    for match in _CITE_RE.finditer(clean):
        pos = match.start()
        start = max(b for b in bounds if b <= pos)
        end = min(b for b in bounds if b > pos)
        sentence = _display(clean[start:end])
        line = clean.count("\n", 0, pos) + 1
        for key in (k.strip() for k in match.group(1).split(",")):
            if key:
                by_key.setdefault(key, []).append({"line": line, "sentence": sentence})
    return by_key


_NUMBER_RE = re.compile(r"\d[\d\u00a0\u202f]*(?:[.,]\d+)?")


def normalise_number(token: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Put a numeric token into one spelling, so a French manuscript and an
        English paper can be compared without the decimal comma defeating it.

    Inputs:
        token (str): a number as written, e.g. "52,5" or "1 800".

    Outputs:
        value (str): the same number with a decimal point and no separators,
            and with a trailing ".0" removed so "43.0" and "43" are one value.
    --------------------------------------------------------------------------
    """
    cleaned = token.replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    cleaned = cleaned.replace(",", ".")
    if cleaned.count(".") > 1:              # a thousands separator, not a decimal
        cleaned = cleaned.replace(".", "")
    if cleaned.endswith("."):
        cleaned = cleaned[:-1]
    if "." in cleaned:
        cleaned = cleaned.rstrip("0").rstrip(".")
    return cleaned or "0"


def numbers_in(text: str) -> list[str]:
    """Every number of a text, normalised, in order of appearance."""
    return [normalise_number(m.group(0)) for m in _NUMBER_RE.finditer(text)]


def claim_text(sentence: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Remove the citation commands from a sentence, leaving what the sentence
        ASSERTS.

    Inputs:
        sentence (str): the citing sentence as written.

    Outputs:
        claim (str): the same sentence without its \\cite{...} commands.

    Measured 2026-09-13: a citekey carries a year, so \\cite{otto2026sanborn}
    put "2026" into a sentence that was then checked against Lin 2023 and
    reported as a figure the paper does not support. Half the absent figures of
    the first real run were this. A citation command is a pointer, never a
    claim.
    --------------------------------------------------------------------------
    """
    return _CITE_RE.sub(" ", sentence)


def check_numbers(sentence: str, paper_text: str) -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Say, for each number a citing sentence carries, whether that number
        appears anywhere in the cited paper's full text.

    Inputs:
        sentence (str): the citing sentence, as written in the manuscript.
        paper_text (str): the cited paper's extracted full text.

    Outputs:
        checks (List[Dict]): [{"value", "as_written", "in_paper"}], one per
            distinct number, in order of first appearance.

    A year that is also a citation year, and the manuscript's own arithmetic,
    both show up here; `in_paper` is evidence for a reader, never a verdict.
    Numbers under two characters are dropped, because a bare "1" or "3" matches
    almost any document and would drown the real claims.
    --------------------------------------------------------------------------
    """
    haystack = set(numbers_in(paper_text))
    checks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _NUMBER_RE.finditer(claim_text(sentence)):
        value = normalise_number(match.group(0))
        if len(value.replace(".", "")) < 2 or value in seen:
            continue
        seen.add(value)
        checks.append({"value": value, "as_written": match.group(0),
                       "in_paper": value in haystack})
    return checks


def find_fulltext(refs_dir: str, citekey: str) -> str | None:
    """Return the full-text file of a citekey in refs/, or None when absent."""
    for ext in (".pdf", ".html", ".md", ".txt"):
        candidate = os.path.join(refs_dir, citekey + ext)
        if os.path.isfile(candidate):
            return candidate
    return None


def validate_manuscript(tex_path: str, refs_dir: str,
                        markers: dict[str, Any],
                        only: list[str] | None = None) -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Produce, for every key the manuscript cites, the sentences that cite it
        and the sentences in which the cited paper states its own contribution.

    Inputs:
        tex_path (str): the manuscript .tex.
        refs_dir (str): the refs/ directory holding the full texts.
        markers (Dict): the marker catalogue.

    Outputs:
        records (List[Dict]): one per cited key, in citation order, carrying
            "citations" and either the contribution record or status
            "no-fulltext".

    The script pairs and never judges. Whether the citing sentence is faithful
    to the paper is the reader's call, and the evidence is reported verbatim so
    that call can be made without opening the PDF again.
    --------------------------------------------------------------------------
    """
    with open(tex_path, encoding="utf-8", errors="replace") as handle:
        tex = handle.read()
    by_key = citing_sentences(tex)

    records: list[dict[str, Any]] = []
    for citekey, citations in by_key.items():
        # Skip BEFORE the full text is parsed. Filtering the finished records
        # instead made --only cost a whole corpus pass (51 PDFs, one of them
        # 7 MB) to report a handful of keys.
        if only and citekey not in only:
            continue
        path = find_fulltext(refs_dir, citekey)
        if path is None:
            record: dict[str, Any] = {
                "citekey": citekey, "file": None, "chars": 0,
                "status": "no-fulltext",
                "reason": "no %s.* in %s" % (citekey, refs_dir),
                "sentences": [],
            }
        else:
            # Read the paper ONCE: analyse_file and the numeric check both need
            # the full text, and parsing a 7 MB PDF twice doubled a corpus run.
            try:
                paper_text = read_any(path)
            except Exception as exc:     # noqa: BLE001 - reported in the record
                paper_text = ""
                record = {"citekey": citekey, "file": os.path.basename(path),
                          "chars": 0, "status": "unreadable",
                          "reason": str(exc)[:200], "sentences": []}
            else:
                record = analyse_file(path, markers, text=paper_text)
            for citation in citations:
                citation["numbers"] = check_numbers(citation["sentence"], paper_text)
        record["cite_count"] = len(citations)
        record["citations"] = citations
        records.append(record)
    return records


def write_contribution_files(records: list[dict[str, Any]], out_dir: str) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Keep one Markdown file per cited paper holding what that paper says it
        contributes and every sentence of the manuscript that cites it.

    Inputs:
        records (List[Dict]): the output of validate_manuscript.
        out_dir (str): destination directory, created when absent.

    Outputs:
        written (List[str]): the paths written.

    The directory name starts with an underscore on purpose: `expand()` skips
    such entries, so these notes can live inside refs/ without a later corpus
    scan reading them back as though they were full texts.
    --------------------------------------------------------------------------
    """
    os.makedirs(out_dir, exist_ok=True)
    written: list[str] = []
    for rec in records:
        path = os.path.join(out_dir, "%s.md" % rec["citekey"])
        lines = [
            "# %s" % rec["citekey"],
            "",
            "- source: %s" % (rec.get("file") or "ABSENT from refs/"),
            "- status: %s" % rec["status"],
            "- kinds: %s" % (", ".join(rec.get("kinds_found") or []) or "-"),
            "- characters of full text: %d" % rec.get("chars", 0),
            "- cited %d time(s) in the manuscript" % rec.get("cite_count", 0),
        ]
        if rec.get("reason"):
            lines.append("- reason: %s" % rec["reason"])
        lines += ["", "## What the paper says it contributes", ""]
        if rec["sentences"]:
            for hit in rec["sentences"]:
                lines.append("- **%s** (position %.3f, marker `%s`)"
                             % (hit["kind"], hit["position"], hit["marker"]))
                lines.append("  > %s" % hit["sentence"].replace("<br>", " ").strip())
                lines.append("")
        else:
            lines += ["_No contribution sentence was matched. This is a statement about "
                      "the marker catalogue as much as about the paper: read it by hand "
                      "before concluding._", ""]
        lines += ["## Where the manuscript cites it", ""]
        for cit in rec.get("citations", []):
            lines.append("- line %d" % cit["line"])
            lines.append("  > %s" % cit["sentence"])
            checks = cit.get("numbers") or []
            if checks:
                absent = [c["as_written"] for c in checks if not c["in_paper"]]
                lines.append("  - numbers checked against the paper: %d"
                             % len(checks))
                lines.append("  - NOT found in the paper: %s"
                             % (", ".join(absent) if absent else "none"))
            lines.append("")
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines).rstrip() + "\n")
        written.append(path)
    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="extract_contributions.py",
        description="Extract the stated scientific contribution of one paper or a refs/ corpus.")
    parser.add_argument("paths", nargs="+",
                        help="full-text files, or a refs/ directory to scan whole.")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text.")
    parser.add_argument("--only", metavar="KEY", action="append",
                        help="restrict a directory scan to these citekeys (repeatable).")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 when any paper yields no contribution sentence.")
    parser.add_argument("--manuscript", metavar="TEX",
                        help="validate mode: pair every \\cite{} of this .tex with the "
                             "cited paper's own contribution sentences. The positional "
                             "path is then the refs/ directory.")
    parser.add_argument("--write-contributions", metavar="DIR",
                        help="write one Markdown note per cited paper into DIR "
                             "(validate mode only).")
    return parser


def expand(paths: list[str], only: list[str] | None) -> list[str]:
    """Turn the CLI paths into a file list, expanding a directory to its full texts."""
    out: list[str] = []
    for path in paths:
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                if name.startswith("_"):
                    continue
                if not name.lower().endswith((".pdf", ".html", ".md", ".txt")):
                    continue
                if only and os.path.splitext(name)[0] not in only:
                    continue
                out.append(os.path.join(path, name))
        else:
            out.append(path)
    return out


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = build_parser().parse_args(argv)
    markers = load_markers()

    written: list[str] = []
    if args.manuscript:
        refs_dir = args.paths[0]
        if not os.path.isdir(refs_dir):
            raise SystemExit("ERROR: validate mode needs the refs/ directory as its "
                             "positional argument, got: %s" % refs_dir)
        records = validate_manuscript(args.manuscript, refs_dir, markers,
                                      only=args.only)
        if args.write_contributions:
            written = write_contribution_files(records, args.write_contributions)
    else:
        if args.write_contributions:
            raise SystemExit("ERROR: --write-contributions needs --manuscript")
        records = [analyse_file(p, markers) for p in expand(args.paths, args.only)]

    # A paper's own sentences carry whatever glyphs the publisher used, and a
    # Windows console is cp1252: printing a bullet or a dash the codec does not
    # know raised UnicodeEncodeError mid-corpus and lost the whole run
    # (measured 2026-09-12 on U+25E6 in the BuildingGIS refs/). The stream
    # setup lives in extract_text, which owns the readers this script reuses,
    # so the two cannot drift into two ideas of what a printable report is
    # (R18); the private copy that used to sit here asked for errors="replace"
    # alone, which substituted a question mark for a character utf-8 can carry.
    extract_text.configure_streams()

    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    else:
        for rec in records:
            print("%-32s %-16s %s" % (rec["citekey"], rec["status"],
                                      ", ".join(rec.get("kinds_found") or []) or "-"))
            for hit in rec["sentences"][:3]:
                print("    [%s @%.2f] %s" % (hit["kind"], hit["position"],
                                             hit["sentence"][:160]))
        silent = [r["citekey"] for r in records if r["status"] != "ok"]
        print("\n%d paper(s), %d with a stated contribution, %d without"
              % (len(records), len(records) - len(silent), len(silent)))
        if silent:
            print("without: " + ", ".join(silent))
        if written:
            print("%d contribution note(s) written to %s"
                  % (len(written), os.path.dirname(written[0])))

    if args.strict and any(r["status"] != "ok" for r in records):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
