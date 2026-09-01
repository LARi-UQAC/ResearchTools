"""
bib_audit.py - Audit an EXISTING BibTeX file: parse, required fields, author
normalization, duplicates, DOI validation, venue metrics, publisher approval,
and an annotated pass-through copy of the source.

Direction matters. bib_batch.py goes candidates -> .bib (title-to-DOI
resolution, enrichment, generation). This script goes .bib -> audit. The two
are complementary; neither replaces the other.

Generalizes the two throwaway drivers written during the TCAS-I /bibclean run
(bibdrv.py, analyze.py) into one reusable skill script. Like bib_batch.py it
wraps scopus_api.py and never calls the Scopus API directly: the Serial Title
CITESCORE view that analyze.py reached over raw HTTP now lives in
scopus_api.py's `journal --issn` mode.

Usage:
  python bib_audit.py <file.bib> [--out-bib <base>_clean.bib]
                      [--out-report <base>_bib_report.md]
                      [--cache <cache.json>] [--no-network] [--json]

Design rules learned in production:
  - Venue metrics resolve by ISSN only. A lookup by journal TITLE returns empty
    stubs (measured on the 81-entry TCAS-I corpus), and a Scopus record may
    carry both the print and the electronic ISSN, so each is tried in turn.
  - No injected line ever contains '@'. BibTeX has no comment syntax and parses
    any '@' found between entries, so a stray one corrupts the database.
  - The annotated copy is a pass-through: the source is copied line by line and
    flags are injected before each entry's closing brace. No entry is deleted or
    reordered, which keeps the result diffable against the source.
  - Injected blocks sit between sentinels and are stripped before regeneration,
    so running the script on its own output does not double the annotations.
  - A Scopus 404 on a dataset DOI (OSF, Zenodo, figshare) is not a broken
    reference; it is separated from a transport error.
  - The report holds only what is measurable: counters, tables, flags. Judgment,
    recommendations, and what to submit to the professor stay with the calling
    agent.
"""

import argparse
import datetime
import difflib
import json
import logging
import os
import re
import subprocess
import sys
import time
from typing import Any

logger = logging.getLogger(__name__)

SCOPUS_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scopus_api.py")
CALL_DELAY_S = 0.25             # be polite to the Scopus quota
TITLE_DUP_RATIO = 0.90          # above this, two entries are the same paper
TITLE_MATCH_MIN = 0.75          # below this, the DOI does not describe the entry

# Approved publishers, synchronized with ".claude/CLAUDE.md" (References).
# Key: a lowercase token searched in the publisher string. Value: canonical name.
APPROVED_TOKENS: dict[str, str] = {
    "ieee": "IEEE",
    "institute of electrical": "IEEE",
    "springer": "Springer",
    "nature": "Springer",
    "elsevier": "Elsevier",
    "taylor": "Taylor & Francis",
    "informa": "Taylor & Francis",
    "cambridge": "Cambridge",
    "wiley": "Wiley",
    "institution of engineering": "IET",
    "iet ": "IET",
    "institute of physics": "IOP",
    "iop ": "IOP",
    "association for computing": "ACM",
    "acm": "ACM",
    "mdpi": "MDPI",
    "multidisciplinary digital publishing": "MDPI",
    "mechanical engineers": "ASME",
    "asme": "ASME",
    "acme": "ACME",
    "biomed central": "BMC",
    "bmc": "BMC",
}

# Publisher families known to be outside the approved list. Checked before the
# venue inference below, because a venue name can contain an approved-publisher
# substring by accident ("Frontiers in Robotics and AI" holds "Robotics").
NOT_APPROVED_PUBLISHERS: dict[str, str] = {
    "frontiers": "Frontiers Media",
    "hindawi": "Hindawi",
    "scirp": "Scientific Research Publishing",
    "bentham": "Bentham Science",
    "inderscience": "Inderscience",
}

# Repository hosts, recognized in `howpublished`. They are not publishers: an
# entry hosted there is a dataset or an artifact, and its inclusion is a
# decision for the professor rather than a defect.
REPOSITORY_HOSTS: dict[str, str] = {
    "osf": "OSF (Open Science Framework)",
    "zenodo": "Zenodo",
    "figshare": "figshare",
    "arxiv": "arXiv (preprint)",
    "biorxiv": "bioRxiv (preprint)",
    "ssrn": "SSRN (preprint)",
}

# DOI prefixes of repository hosts. A Scopus 404 on one of these is expected.
DATASET_DOI_PREFIXES = ("10.17605", "10.5281", "10.6084", "10.48550")

# Venue substrings that identify the publisher when the publisher field is absent.
VENUE_PUBLISHER_HINTS: list[tuple[str, str]] = [
    ("ifac", "Elsevier (inferred)"),
    ("procedia", "Elsevier (inferred)"),
    ("cirp", "Elsevier (inferred)"),
    ("ieee", "IEEE (inferred)"),
    ("lecture notes", "Springer (inferred)"),
    ("sustainable production", "Springer (inferred)"),
]

# Minimum fields per entry type. "author|editor" means either one satisfies it.
REQUIRED_FIELDS: dict[str, list[str]] = {
    "article": ["author", "title", "journal", "year"],
    "inproceedings": ["author", "title", "booktitle", "year"],
    "incollection": ["author", "title", "booktitle", "publisher", "year"],
    "book": ["author|editor", "title", "publisher", "year"],
    "inbook": ["author|editor", "title", "publisher", "year"],
    "techreport": ["author", "title", "institution", "year"],
    "misc": ["author|title", "year"],
}

# Sentinels around every block this script injects. Stripping them before a new
# run is what makes the script idempotent on its own output.
HEADER_BEGIN = "% >>> bib-audit header"
HEADER_END = "% <<< bib-audit header"
FLAGS_BEGIN = "% >>> bib-audit flags"
FLAGS_END = "% <<< bib-audit flags"

# French function words used to decide the language of the corpus. The report is
# written in English regardless (script-emitted headings are English by repo
# rule); the calling agent uses this to pick the language of its own judgment.
FRENCH_MARKERS = {"de", "des", "du", "la", "le", "les", "pour", "une", "dans",
                  "sur", "avec", "par", "et", "aux", "au"}


# ---------------------------------------------------------------------------
# Parsing and normalization
# ---------------------------------------------------------------------------

def parse_bib(path: str) -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Parse a BibTeX file tolerantly: commented lines are skipped, an entry
        opens on '@type{key,' and closes on a lone '}'. Deliberately forgiving,
        because the input is a hand-maintained file that may not satisfy a
        strict grammar.

    Inputs:
        path (str): path to the .bib file.

    Outputs:
        entries (list[dict]): [{"type", "key", "fields": {name: value}}, ...]
            in source order. Commented-out entries are not returned.
    --------------------------------------------------------------------------
    """
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            stripped = line.strip()
            if stripped.startswith("%"):
                continue
            opening = re.match(r"^@(\w+)\s*\{\s*([^,]+),", line)
            if opening:
                current = {"type": opening.group(1).lower(),
                           "key": opening.group(2).strip(), "fields": {}}
                entries.append(current)
                continue
            if current is not None:
                field = re.match(r"^\s*(\w+)\s*=\s*\{(.*)\}\s*,?\s*$", line)
                if field:
                    current["fields"][field.group(1).lower().strip()] = field.group(2).strip()
                elif stripped == "}":
                    current = None
    return entries


def norm(text: str) -> str:
    """Lowercase, strip braces, LaTeX backslashes and punctuation, collapse
    whitespace. Used for every similarity comparison in this script."""
    if not text:
        return ""
    text = text.replace("{", "").replace("}", "").replace("\\", " ")
    text = re.sub(r"[\.,;:'\"`\-_/]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def first_surname_bib(author: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Extract the first author's surname from a BibTeX author field, in both
        conventions: "Surname, Firstname and ..." and the initials-last style
        "Darwish M.A. and ..." where the first token is already the surname.

    Inputs:
        author (str): the raw BibTeX author field.

    Outputs:
        surname (str): normalized surname, or "" when the field is empty.
    --------------------------------------------------------------------------
    """
    if not author:
        return ""
    first = author.split(" and ")[0].strip()
    if "," in first:
        return norm(first.split(",")[0])
    tokens = first.split()
    return norm(tokens[0]) if tokens else ""


def similarity(left: str, right: str) -> float:
    """Normalized-title similarity in [0, 1]; 0 when either side is empty."""
    a, b = norm(left), norm(right)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def detect_language(entries: list[dict[str, Any]]) -> str:
    """Return 'fr' when French function words dominate the titles, else 'en'.
    Reported so the calling agent writes its judgment in the corpus language."""
    french = 0
    total = 0
    for entry in entries:
        words = norm(entry["fields"].get("title", "")).split()
        total += len(words)
        french += sum(1 for word in words if word in FRENCH_MARKERS)
    return "fr" if total and french / total > 0.08 else "en"


# ---------------------------------------------------------------------------
# Publisher approval
# ---------------------------------------------------------------------------

def publisher_status(publisher: str, journal: str, booktitle: str,
                     howpublished: str) -> tuple[str, bool | None]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide whether the entry comes from an approved publisher, per the list
        in .claude/CLAUDE.md (IEEE, Springer, Elsevier, Taylor & Francis,
        Cambridge, Wiley, IET, IOP, ACM, MDPI, ASME, ACME, BMC).

    Inputs:
        publisher (str): publisher field, or the publisher Scopus returned.
        journal (str), booktitle (str), howpublished (str): venue fields, used
            to infer the publisher when the publisher field is absent.

    Outputs:
        (name, approved) (tuple[str, bool | None]): approved is True (on the
            list), False (identified and off the list), or None (undetermined,
            which is not a defect but not a clearance either).
    --------------------------------------------------------------------------
    """
    haystack = " ".join([publisher or "", journal or "", booktitle or ""]).lower()
    for token, name in NOT_APPROVED_PUBLISHERS.items():
        if token in haystack:
            return name, False
    host = (howpublished or "").lower()
    for token, name in REPOSITORY_HOSTS.items():
        if token in host:
            return name, False

    if publisher:
        lowered = publisher.lower()
        for token, _ in APPROVED_TOKENS.items():
            if token in lowered:
                return publisher, True

    venue = ((journal or "") + " " + (booktitle or "")).lower()
    for token, name in VENUE_PUBLISHER_HINTS:
        if token in venue:
            return name, True

    if publisher:
        return publisher, False
    return "unknown", None


# ---------------------------------------------------------------------------
# Scopus access (always through scopus_api.py)
# ---------------------------------------------------------------------------

def _run_scopus(args: list[str], force_utf8: bool = False) -> dict[str, Any]:
    """Invoke scopus_api.py as a subprocess and return its parsed JSON, or an
    {'_error': detail} dict. Windows console redirection defaults to cp1252 and
    corrupts author names, hence the explicit UTF-8 environment."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if force_utf8:
        env["PYTHONUTF8"] = "1"
    try:
        proc = subprocess.run([sys.executable, SCOPUS_SCRIPT] + args,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", env=env, timeout=90)
    except subprocess.TimeoutExpired:
        return {"_error": "timeout"}
    if proc.returncode != 0:
        return {"_error": (proc.stderr or proc.stdout or "nonzero").strip()[-200:]}
    try:
        return json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        return {"_error": f"parse:{exc}", "_raw": (proc.stdout or "")[:200]}


def fetch_cite(doi: str) -> dict[str, Any]:
    """Retrieve the Scopus record of one DOI. A cp1252 'charmap' crash is a real
    Windows defect and not a missing record, so it is retried under PYTHONUTF8."""
    record = _run_scopus(["cite", doi, "--no-s2"])
    if record.get("_error") and "charmap" in str(record["_error"]):
        record = _run_scopus(["cite", doi, "--no-s2"], force_utf8=True)
    return record


def fetch_metrics(journal: str, issn: str) -> dict[str, Any]:
    """Retrieve venue metrics by ISSN through scopus_api.py journal --issn, and
    flatten the single result. Lookup by title returns empty stubs (measured)."""
    payload = _run_scopus(["journal", journal or issn, "--issn", issn])
    if payload.get("_error"):
        return {"error": str(payload["_error"])[:120]}
    results = payload.get("results") or []
    if not results:
        return {"error": "no-serial-record"}
    return results[0]


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def audit(entries: list[dict[str, Any]], cache: dict[str, Any],
          offline: bool = False) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run every check over the parsed entries: duplicates, required fields,
        DOI validity, author formatting, publisher approval, venue metrics and
        venue-name drift. Network access goes through fetch_cite / fetch_metrics
        and is fully served by the cache when offline is True.

    Inputs:
        entries (list[dict]): output of parse_bib.
        cache (dict): {"cite": {doi: record}, "metrics": {issn: record}}, read
            and written in place so a rerun costs no quota.
        offline (bool): when True, never call Scopus; unknown DOIs and venues
            are reported as unverified rather than fetched.

    Outputs:
        result (dict): {"findings": {key: {...}}, "summary": {...},
            "issn_metrics": {...}, "journal_issn": {...}} where findings[key]
            holds the flags, the metric comment and the suggestion lines of one
            entry.
    --------------------------------------------------------------------------
    """
    cite_cache: dict[str, Any] = cache.setdefault("cite", {})
    metric_cache: dict[str, Any] = cache.setdefault("metrics", {})

    # --- DOI records (deduplicated: the same DOI is fetched once) -----------
    for entry in entries:
        doi = entry["fields"].get("doi", "").strip()
        if not doi or doi in cite_cache:
            continue
        if offline:
            cite_cache[doi] = {"_error": "offline: not in cache"}
            continue
        logger.info("[BIBAUDIT] cite %s %s", entry["key"], doi)
        cite_cache[doi] = fetch_cite(doi)
        time.sleep(CALL_DELAY_S)

    # --- venue metrics, keyed by the ISSN of the article's Scopus record ----
    journal_issn: dict[str, str] = {}
    for entry in entries:
        if entry["type"] != "article":
            continue
        journal = entry["fields"].get("journal", "").strip()
        record = cite_cache.get(entry["fields"].get("doi", "").strip(), {})
        issn = (record.get("issn") or "").strip() if isinstance(record, dict) else ""
        if journal and issn and journal not in journal_issn:
            journal_issn[journal] = issn

    issn_metrics: dict[str, Any] = {}
    for journal, issn in journal_issn.items():
        if issn in issn_metrics:
            continue
        cached = metric_cache.get(issn)
        if cached and not cached.get("error"):
            issn_metrics[issn] = cached
            continue
        if offline:
            issn_metrics[issn] = cached or {"error": "offline: not in cache"}
            continue
        logger.info("[BIBAUDIT] metrics %s %s", journal, issn)
        issn_metrics[issn] = fetch_metrics(journal, issn)
        metric_cache[issn] = issn_metrics[issn]
        time.sleep(CALL_DELAY_S)

    findings: dict[str, dict[str, Any]] = {
        entry["key"]: {"entry": entry, "flags": [], "suggestions": [], "metric_comment": ""}
        for entry in entries
    }
    summary: dict[str, Any] = {
        "doi_invalid": [], "doi_mismatch": [], "doi_not_in_scopus": [], "doi_unverified": [],
        "missing_doi": [], "missing_field": [], "pub_not_approved": [], "pub_undetermined": [],
        "author_fmt": [], "low_impact": [], "not_ranked": [], "journal_unverified": [],
        "venue_not_applicable": [], "abbreviated": [], "duplicate_pairs": [],
    }

    # --- duplicates: exact DOI, then title similarity -----------------------
    seen_doi: dict[str, str] = {}
    for entry in entries:
        doi = entry["fields"].get("doi", "").strip().lower()
        if not doi:
            continue
        if doi in seen_doi:
            findings[entry["key"]]["flags"].append(f"[DUPLICATE DOI: {seen_doi[doi]}]")
            findings[seen_doi[doi]]["flags"].append(f"[DUPLICATE DOI: {entry['key']}]")
            summary["duplicate_pairs"].append([seen_doi[doi], entry["key"]])
        else:
            seen_doi[doi] = entry["key"]

    for i, left in enumerate(entries):
        for right in entries[i + 1:]:
            ratio = similarity(left["fields"].get("title", ""), right["fields"].get("title", ""))
            if ratio > TITLE_DUP_RATIO:
                findings[left["key"]]["flags"].append(
                    f"[DUPLICATE: {right['key']} sim={ratio:.2f}]")
                findings[right["key"]]["flags"].append(
                    f"[DUPLICATE: {left['key']} sim={ratio:.2f}]")
                summary["duplicate_pairs"].append([left["key"], right["key"]])

    # --- per-entry checks ---------------------------------------------------
    for entry in entries:
        key, fields, kind = entry["key"], entry["fields"], entry["type"]
        flags: list[str] = findings[key]["flags"]
        suggestions: list[str] = findings[key]["suggestions"]

        for requirement in REQUIRED_FIELDS.get(kind, []):
            if not any(fields.get(name, "").strip() for name in requirement.split("|")):
                flags.append(f"[MISSING FIELD: {requirement}]")
                summary["missing_field"].append(key)

        doi = fields.get("doi", "").strip()
        if kind in ("article", "inproceedings") and not doi:
            flags.append("[MISSING DOI]")
            summary["missing_doi"].append(key)

        record = cite_cache.get(doi, {}) if doi else {}
        if doi and isinstance(record, dict) and record.get("_error"):
            error = str(record["_error"])
            is_dataset = (kind == "misc"
                          or doi.startswith(DATASET_DOI_PREFIXES))
            if "404" in error or "RESOURCE_NOT_FOUND" in error:
                if is_dataset:
                    flags.append("[DOI NOT IN SCOPUS - dataset or artifact, expected]")
                    summary["doi_not_in_scopus"].append(key)
                else:
                    flags.append("[DOI INVALID - not found in Scopus]")
                    summary["doi_invalid"].append(key)
            else:
                flags.append(f"[DOI UNVERIFIED - {error[:60]}]")
                summary["doi_unverified"].append(key)
        elif doi and isinstance(record, dict) and record.get("title"):
            ratio = similarity(fields.get("title", ""), record.get("title", ""))
            bib_surname = first_surname_bib(fields.get("author", ""))
            authors = record.get("authors") or []
            scopus_surname = norm(authors[0].get("surname", "")) if authors else ""
            surname_ok = (not bib_surname or not scopus_surname
                          or bib_surname == scopus_surname)
            if ratio < TITLE_MATCH_MIN or not surname_ok:
                flags.append(f"[DOI MISMATCH - title_sim={ratio:.2f} "
                             f"bibAuthor1={bib_surname} scopusAuthor1={scopus_surname}]")
                summary["doi_mismatch"].append(key)

        author = fields.get("author", "")
        if author:
            if "," not in author:
                flags.append("[AUTHOR FORMAT INCONSISTENT - no comma; use Surname, Firstname]")
                summary["author_fmt"].append(key)
                suggestions.append(f"% SUGGESTED: author = {{{_suggest_author(author)}}}")
            else:
                for part in author.split(" and "):
                    surname = part.split(",")[0].strip()
                    if len(surname) > 1 and surname.isupper():
                        flags.append(
                            f"[AUTHOR FORMAT INCONSISTENT - all-caps surname {surname}]")
                        summary["author_fmt"].append(key)
                        suggestions.append(
                            f"% SUGGESTED: author = {{{_suggest_author(author)}}}")
                        break

        journal = fields.get("journal", "").strip()
        issn = journal_issn.get(journal, "")
        metrics = issn_metrics.get(issn, {}) if issn else {}
        scopus_publisher = metrics.get("publisher", "") if isinstance(metrics, dict) else ""
        name, approved = publisher_status(
            scopus_publisher or fields.get("publisher", ""), journal,
            fields.get("booktitle", ""), fields.get("howpublished", ""))
        findings[key]["publisher"] = name
        findings[key]["approved"] = approved
        if approved is False:
            flags.append(f"[PUBLISHER NOT APPROVED - {name}]")
            suggestions.append("% Requires professor approval before inclusion")
            summary["pub_not_approved"].append(key)
        elif approved is None:
            summary["pub_undetermined"].append(key)

        if kind == "article":
            findings[key]["metric_comment"] = _metric_comment(key, metrics, issn, flags, summary)

        venue_field = "journal" if journal else "booktitle"
        venue = journal or fields.get("booktitle", "").strip()
        scopus_venue = record.get("journal", "") if isinstance(record, dict) else ""
        if venue and _is_abbreviated(venue):
            flags.append("[ABBREVIATION INCONSISTENT - abbreviated venue name]")
            summary["abbreviated"].append(key)
        if venue and scopus_venue and norm(venue) != norm(scopus_venue):
            suggestions.append(f"% SUGGESTED {venue_field} = {{{scopus_venue}}}")

    return {"findings": findings, "summary": summary, "issn_metrics": issn_metrics,
            "journal_issn": journal_issn}


def _suggest_author(author: str) -> str:
    """Rewrite an author field into the "Surname, Firstname and ..." standard.
    Initials-last input ("Darwish M.A.") puts the first token as the surname."""
    parts = []
    for raw in author.split(" and "):
        person = raw.strip()
        if "," in person:
            surname, _, given = person.partition(",")
            surname = surname.strip()
            if len(surname) > 1 and surname.isupper():
                surname = surname.capitalize()
            parts.append(f"{surname}, {given.strip()}")
            continue
        tokens = person.split()
        if len(tokens) >= 2:
            parts.append(f"{tokens[0]}, {' '.join(tokens[1:])}")
        else:
            parts.append(person)
    return " and ".join(parts)


def _is_abbreviated(venue: str) -> bool:
    """True when the venue name holds an abbreviated word ("Trans.", "Autom.").
    A single-letter token followed by a period is an initial, not a shortening."""
    return any(len(token.rstrip(".")) > 1 and token.endswith(".")
               for token in venue.split())


def _metric_comment(key: str, metrics: dict[str, Any], issn: str,
                    flags: list[str], summary: dict[str, Any]) -> str:
    """Turn one venue-metrics record into its `% Journal:` comment line and the
    matching flag. A venue where SJR does not apply (book series) is reported as
    such, never as a weak journal."""
    if not issn or not metrics:
        flags.append("[JOURNAL UNVERIFIED - no ISSN in Scopus record]")
        summary["journal_unverified"].append(key)
        return "% Journal: metrics unverified (no ISSN in the Scopus record)"
    if metrics.get("error"):
        flags.append("[JOURNAL UNVERIFIED]")
        summary["journal_unverified"].append(key)
        return f"% Journal: metrics unverified ({metrics['error']})"
    if metrics.get("sjr_applicable") is False:
        summary["venue_not_applicable"].append(key)
        return (f"% Journal: {metrics.get('venue_type', 'unknown')} - SJR not applicable; "
                f"CiteScore={metrics.get('cite_score') or 'n/a'} "
                f"publisher={metrics.get('publisher', '')}")
    if not metrics.get("sjr"):
        flags.append("[JOURNAL NOT RANKED]")
        summary["not_ranked"].append(key)
        return f"% Journal: no SJR returned; CiteScore={metrics.get('cite_score') or 'n/a'}"

    quartile = metrics.get("quartile") or "?"
    if quartile in ("Q3", "Q4"):
        flags.append(f"[LOW IMPACT - {quartile}]")
        summary["low_impact"].append(key)
    return (f"% Journal: SJR={metrics['sjr']} [{quartile}] "
            f"CiteScore={metrics.get('cite_score') or 'n/a'} "
            f"(CiteScore pct={metrics.get('pct')}) publisher={metrics.get('publisher', '')}")


# ---------------------------------------------------------------------------
# Output generation
# ---------------------------------------------------------------------------

def _sanitize(line: str) -> str:
    """No injected line may contain '@': BibTeX parses any '@' between entries
    as the start of a new one, which corrupts the whole database."""
    return line.replace("@", "[at]")


def _strip_generated(lines: list[str]) -> list[str]:
    """Remove every block this script previously injected, so a run over its own
    output regenerates the annotations instead of stacking a second copy."""
    kept: list[str] = []
    inside = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith((HEADER_BEGIN, FLAGS_BEGIN)):
            inside = True
            continue
        if stripped.startswith((HEADER_END, FLAGS_END)):
            inside = False
            continue
        if not inside:
            kept.append(line)
    # The header block is followed by a blank line; without this the file would
    # gain one empty line per run and never reach a fixed point.
    while kept and not kept[0].strip():
        kept.pop(0)
    return kept


def generate_clean_bib(source_path: str, findings: dict[str, dict[str, Any]]) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build the annotated copy by pass-through: every source line is copied in
        order and the flags of an entry are injected just before its closing
        brace. Nothing is deleted, reordered or rewritten, so the output diffs
        cleanly against the source.

    Inputs:
        source_path (str): the .bib being audited.
        findings (dict): the per-entry findings from audit().

    Outputs:
        content (str): the full annotated .bib, ready to write.
    --------------------------------------------------------------------------
    """
    with open(source_path, encoding="utf-8") as handle:
        lines = _strip_generated(handle.read().split("\n"))

    out: list[str] = [
        HEADER_BEGIN,
        "% Cleaned by bib_audit.py (bib-cleaner / bibclean).",
        f"% Generated: {datetime.date.today().isoformat()}",
        f"% Source: {os.path.basename(source_path)} - all entries preserved in original order.",
        "% Flags use the % [FLAG] notation; no entry is deleted. See the companion report.",
        "% Journal metrics: SJR, CiteScore and quartile (best CiteScore subject percentile)",
        "%   from the Scopus Serial Title API, looked up by ISSN (STANDARD + CITESCORE views).",
        HEADER_END,
        "",
    ]

    current_key: str | None = None
    for line in lines:
        stripped = line.strip()
        opening = re.match(r"^@(\w+)\s*\{\s*([^,]+),", line)
        if opening and not stripped.startswith("%"):
            current_key = opening.group(2).strip()
        out.append(line)
        if current_key and stripped == "}":
            finding = findings.get(current_key)
            if finding and (finding["flags"] or finding["metric_comment"]
                            or finding["suggestions"]):
                out.append(FLAGS_BEGIN)
                for flag in finding["flags"]:
                    out.append(_sanitize(f"% {flag}"))
                if finding["metric_comment"]:
                    out.append(_sanitize(finding["metric_comment"]))
                for suggestion in dict.fromkeys(finding["suggestions"]):
                    out.append(_sanitize(suggestion))
                out.append(FLAGS_END)
            current_key = None
    return "\n".join(out)


def build_machine_summary(entries: list[dict[str, Any]], result: dict[str, Any],
                          source_path: str) -> dict[str, Any]:
    """Assemble the JSON summary the calling agent reads to write its judgment:
    counters, key lists per defect category, temporal distribution, per-entry
    flags. No prose, no recommendation."""
    findings, summary = result["findings"], result["summary"]
    years = [int(e["fields"]["year"].strip()) for e in entries
             if e["fields"].get("year", "").strip().isdigit()]
    decades: dict[str, int] = {}
    for year in years:
        decades[str((year // 10) * 10)] = decades.get(str((year // 10) * 10), 0) + 1
    this_year = datetime.date.today().year
    with_doi = [e for e in entries if e["fields"].get("doi", "").strip()]
    validated = sum(1 for e in with_doi
                    if not summary_contains(summary, e["key"]))

    return {
        "source": os.path.abspath(source_path),
        "corpus_language": detect_language(entries),
        "total_entries": len(entries),
        "entries_with_doi": len(with_doi),
        "dois_validated": validated,
        "flagged_entries_count": sum(1 for f in findings.values() if f["flags"]),
        "by_type": _count_by(entries, "type"),
        "doi_invalid": summary["doi_invalid"],
        "doi_mismatch": summary["doi_mismatch"],
        "doi_not_in_scopus": summary["doi_not_in_scopus"],
        "doi_unverified": summary["doi_unverified"],
        "missing_doi": summary["missing_doi"],
        "missing_field": sorted(set(summary["missing_field"])),
        "duplicate_pairs": summary["duplicate_pairs"],
        "publisher_not_approved": summary["pub_not_approved"],
        "publisher_undetermined": summary["pub_undetermined"],
        "author_format": sorted(set(summary["author_fmt"])),
        "low_impact": summary["low_impact"],
        "not_ranked": summary["not_ranked"],
        "venue_sjr_not_applicable": summary["venue_not_applicable"],
        "journal_unverified": summary["journal_unverified"],
        "abbreviated_venue": summary["abbreviated"],
        "years_min": min(years) if years else None,
        "years_max": max(years) if years else None,
        "last_5_years": sum(1 for y in years if y >= this_year - 4),
        "decades": decades,
        "venue_metrics": result["issn_metrics"],
        "journal_issn": result["journal_issn"],
        "flags": {key: f["flags"] for key, f in findings.items() if f["flags"]},
    }


def summary_contains(summary: dict[str, Any], key: str) -> bool:
    """True when the entry appears in any DOI-defect list (invalid, mismatched,
    unverified, or absent from Scopus)."""
    return any(key in summary[name] for name in
               ("doi_invalid", "doi_mismatch", "doi_unverified", "doi_not_in_scopus"))


def _count_by(entries: list[dict[str, Any]], attribute: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry[attribute]] = counts.get(entry[attribute], 0) + 1
    return counts


def generate_report(entries: list[dict[str, Any]], result: dict[str, Any],
                    machine: dict[str, Any], source_path: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Render the measurable half of the audit as Markdown: counters, temporal
        distribution, per-entry flags, venue-metrics table, and the lists the
        professor has to arbitrate. Judgment and recommendations are the calling
        agent's job and are deliberately absent here.

    Inputs:
        entries (list[dict]): parsed entries.
        result (dict): output of audit().
        machine (dict): output of build_machine_summary.
        source_path (str): the audited .bib.

    Outputs:
        report (str): Markdown report content.
    --------------------------------------------------------------------------
    """
    findings, summary = result["findings"], result["summary"]
    lines: list[str] = []
    add = lines.append

    add(f"# BibTeX Audit Report - {os.path.basename(source_path)}")
    add(f"Generated: {datetime.date.today().isoformat()}")
    add("")
    add(f"Source: `{os.path.abspath(source_path)}`  ")
    add(f"Corpus language detected: `{machine['corpus_language']}`  ")
    add("Measured values only. Judgment, recommendations and the decisions to submit "
        "to the professor are written by the calling agent.")
    add("")

    add("## Summary")
    add(f"- Total entries: {machine['total_entries']} "
        f"({', '.join(f'{n} @{t}' for t, n in sorted(machine['by_type'].items()))})")
    add(f"- Entries with at least one flag: {machine['flagged_entries_count']}")
    add(f"- Entries with a DOI: {machine['entries_with_doi']} "
        f"(validated against Scopus: {machine['dois_validated']})")
    add(f"- Missing DOIs: {len(summary['missing_doi'])}")
    add(f"- Invalid DOIs: {len(summary['doi_invalid'])} | "
        f"DOI mismatches: {len(summary['doi_mismatch'])} | "
        f"DOI outside Scopus (dataset or artifact): {len(summary['doi_not_in_scopus'])} | "
        f"DOI unverified (transport): {len(summary['doi_unverified'])}")
    add(f"- Duplicate pairs (DOI or title > {TITLE_DUP_RATIO:.2f}): "
        f"{len(summary['duplicate_pairs'])}")
    add(f"- Missing required fields: {len(set(summary['missing_field']))} entries")
    add(f"- Publisher not approved: {len(summary['pub_not_approved'])} | "
        f"publisher undetermined: {len(summary['pub_undetermined'])}")
    add(f"- Author-format inconsistencies: {len(set(summary['author_fmt']))}")
    add(f"- Low-impact journals (Q3/Q4): {len(summary['low_impact'])} | "
        f"not ranked: {len(summary['not_ranked'])} | "
        f"SJR not applicable (book series and the like): "
        f"{len(summary['venue_not_applicable'])} | "
        f"unverified: {len(summary['journal_unverified'])}")
    add(f"- Abbreviated venue names: {len(summary['abbreviated'])}")
    add("")

    add("## Temporal Distribution")
    if machine["decades"]:
        for decade in sorted(machine["decades"]):
            count = machine["decades"][decade]
            add(f"- {decade}s : {count:2d}  {'#' * count}")
        add("")
        total_dated = sum(machine["decades"].values())
        share = round(100 * machine["last_5_years"] / total_dated) if total_dated else 0
        add(f"Oldest: {machine['years_min']}  Newest: {machine['years_max']}  "
            f"Last 5 years: {machine['last_5_years']} ({share}% of dated entries)")
    else:
        add("- No dated entry.")
    add("")

    add("## Entry Issues")
    add("Only entries carrying at least one flag are listed.")
    add("")
    for entry in entries:
        finding = findings[entry["key"]]
        if not finding["flags"]:
            continue
        venue = (entry["fields"].get("journal") or entry["fields"].get("booktitle")
                 or entry["fields"].get("howpublished") or "")
        add(f"### {entry['key']} (@{entry['type']}) - {venue}")
        for flag in finding["flags"]:
            add(f"- {flag}")
        if finding["metric_comment"]:
            add(f"- {finding['metric_comment'].lstrip('% ').strip()}")
        for suggestion in dict.fromkeys(finding["suggestions"]):
            add(f"- {suggestion.lstrip('% ').strip()}")
        add("")

    add("## Venue Metrics")
    add("| Venue | ISSN | SJR | CiteScore | Percentile | Quartile | Publisher | Type |")
    add("|---|---|---|---|---|---|---|---|")
    for journal, issn in sorted(result["journal_issn"].items()):
        metrics = result["issn_metrics"].get(issn, {})
        if metrics.get("error"):
            add(f"| {journal} | {issn} | - | - | - | - | - | error: {metrics['error']} |")
            continue
        add(f"| {journal} | {metrics.get('issn_used', issn)} | {metrics.get('sjr', '') or '-'} "
            f"| {metrics.get('cite_score', '') or '-'} | {metrics.get('pct') if metrics.get('pct') is not None else '-'} "
            f"| {metrics.get('quartile', '') or '-'} | {metrics.get('publisher', '') or '-'} "
            f"| {metrics.get('venue_type', '') or '-'} |")
    if not result["journal_issn"]:
        add("| (no article entry resolved to an ISSN) | - | - | - | - | - | - | - |")
    add("")

    add("## Entries Requiring Professor Approval")
    add("Publisher outside the approved list (IEEE, Springer, Elsevier, Taylor & Francis, "
        "Cambridge, Wiley, IET, IOP, ACM, MDPI, ASME, ACME, BMC):")
    for key in summary["pub_not_approved"]:
        finding = findings[key]
        fields = finding["entry"]["fields"]
        venue = fields.get("journal") or fields.get("booktitle") or fields.get("howpublished") or ""
        add(f"- `{key}` - {venue} ({finding.get('publisher')})")
    if not summary["pub_not_approved"]:
        add("- None.")
    add("")

    add("## Low-Impact Journal Entries (Q3/Q4)")
    for key in summary["low_impact"]:
        add(f"- `{key}` - {findings[key]['metric_comment'].lstrip('% ').strip()}")
    if not summary["low_impact"]:
        add("- None.")
    add("")

    add("## Files Written")
    add(f"- `{os.path.basename(source_path)}` annotated copy, all entries in original order, "
        "inline `% [FLAG]` annotations between the bib-audit sentinels. Valid BibTeX: "
        "comments only, no `@` in any injected line.")
    add("- This report.")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    parser = argparse.ArgumentParser(
        description="Audit an existing BibTeX file against Scopus (via scopus_api.py)")
    parser.add_argument("bib", help="path to the .bib file to audit")
    parser.add_argument("--out-bib", default=None,
                        help="annotated copy (default: <base>_clean.bib beside the source)")
    parser.add_argument("--out-report", default=None,
                        help="Markdown report (default: <base>_bib_report.md beside the source)")
    parser.add_argument("--cache", default=None,
                        help="cite + venue-metrics cache "
                             "(default: <base>_bib_audit_cache.json beside the source)")
    parser.add_argument("--no-network", action="store_true",
                        help="replay from the cache only; never call Scopus")
    parser.add_argument("--json", action="store_true",
                        help="print the machine summary as JSON on stdout")
    args = parser.parse_args()

    base = os.path.splitext(args.bib)[0]
    out_bib = args.out_bib or f"{base}_clean.bib"
    out_report = args.out_report or f"{base}_bib_report.md"
    cache_path = args.cache or f"{base}_bib_audit_cache.json"

    entries = parse_bib(args.bib)
    logger.info("[BIBAUDIT] parsed %d active entries from %s", len(entries), args.bib)

    cache: dict[str, Any] = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as handle:
                cache = json.load(handle)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[BIBAUDIT] cache unreadable (%s), starting empty", exc)

    result = audit(entries, cache, offline=args.no_network)

    with open(cache_path, "w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=False, indent=1)

    machine = build_machine_summary(entries, result, args.bib)
    with open(out_bib, "w", encoding="utf-8") as handle:
        handle.write(generate_clean_bib(args.bib, result["findings"]))
    with open(out_report, "w", encoding="utf-8") as handle:
        handle.write(generate_report(entries, result, machine, args.bib))
    logger.info("[BIBAUDIT] wrote %s and %s", out_bib, out_report)

    if args.json:
        print(json.dumps(machine, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
