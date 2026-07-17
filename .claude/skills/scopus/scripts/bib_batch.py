"""
bib_batch.py - Batch title-to-DOI resolution, citation enrichment, venue grading,
and BibTeX generation for literature-review corpora.

Generalizes the ad hoc drivers written during the TCAS-I /litreview run
(enrich_driver.py, add_consensus.py, validate_grade.py, gen_bib.py) into one
reusable skill script. Wraps scopus_api.py; never calls the Scopus API directly.

Usage:
  python bib_batch.py resolve <candidates.json> [--out corpus.json]
  python bib_batch.py enrich  <corpus.json>     [--out corpus.json]
  python bib_batch.py bib     <corpus.json>     [--out review.bib]
  python bib_batch.py all     <candidates.json> [--corpus corpus.json] [--bib review.bib]

candidates.json: [{"key": "smith2024energy", "source": "SCOPUS.AI-P1",
                   "title": "Exact paper title"}, ...]
corpus.json: dict keyed by citekey with resolved/enriched metadata.

Design rules learned in production:
  - Title queries use TITLE("<title>") - a free-text search ranks by recency and
    returns wrong DOIs; never fall back to the first hit on a weak match.
  - Excluded entries are written to the .bib as comments WITHOUT any '@' char:
    BibTeX has no comment syntax and parses any '@' found between entries, so a
    commented-out entry corrupts the whole database.
  - All output files are UTF-8; forbidden typographic characters imported from
    Scopus metadata (en dash, zero-width space, curly quotes, ellipsis) are
    normalized to their ASCII equivalents at bib-generation time.
"""

import argparse
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
CALL_DELAY_S = 0.4          # be polite to the Scopus quota
TITLE_JACCARD_MIN = 0.6     # word-set similarity threshold for a title match

# Venue-substring -> (grade, publisher, approved) map. First match wins; grades
# follow the scopus-researcher Step 3b venue scale (A: flagship journals from
# approved publishers; B: solid journals, MDPI, proceedings). Extend as needed.
VENUE_GRADES: list[tuple[str, str, str, bool]] = [
    ("ieee transactions", "A", "IEEE", True),
    ("robotics and computer", "A", "Elsevier", True),
    ("journal of manufacturing systems", "A", "Elsevier", True),
    ("cirp annals", "A", "Elsevier", True),
    ("cirp journal", "A", "Elsevier", True),
    ("international journal of production research", "A", "Taylor & Francis", True),
    ("international journal of production economics", "A", "Elsevier", True),
    ("journal of cleaner production", "A", "Elsevier", True),
    ("waste management", "A", "Elsevier", True),
    ("resources, conservation", "A", "Elsevier", True),
    ("engineering applications of artificial intelligence", "A", "Elsevier", True),
    ("expert systems with applications", "A", "Elsevier", True),
    ("computers and industrial engineering", "A", "Elsevier", True),
    ("computers & industrial engineering", "A", "Elsevier", True),
    ("advanced engineering informatics", "A", "Elsevier", True),
    ("journal of intelligent manufacturing", "A", "Springer", True),
    ("annals of operations research", "A", "Springer", True),
    ("applied mathematical modelling", "A", "Elsevier", True),
    ("autonomous robots", "A", "Springer", True),
    ("international journal of advanced manufacturing", "A", "Springer", True),
    ("swarm and evolutionary", "A", "Elsevier", True),
    ("journal of energy storage", "A", "Elsevier", True),
    ("journal of manufacturing science and engineering", "A", "ASME", True),
    ("international journal of precision engineering", "A", "Springer", True),
    ("environmental science and pollution", "B", "Springer", True),
    ("scientific reports", "B", "Springer", True),
    ("robotica", "B", "Cambridge", True),
    ("artificial intelligence for engineering design", "B", "Cambridge", True),
    ("batteries", "B", "MDPI", True),
    ("energies", "B", "MDPI", True),
    ("robotics", "B", "MDPI", True),
    ("biomimetics", "B", "MDPI", True),
    ("applied sciences", "B", "MDPI", True),
    ("designs", "B", "MDPI", True),
    ("metals", "B", "MDPI", True),
    ("sustainability", "B", "MDPI", True),
    ("automation", "B", "MDPI", True),
    ("sensors", "B", "MDPI", True),
    ("procedia cirp", "B", "Elsevier", True),
    ("ifac", "B", "Elsevier", True),
    ("procedia computer science", "B", "Elsevier", True),
    ("iise transactions", "B", "Taylor & Francis", True),
    ("frontiers in", "B", "Frontiers", False),
    ("sustainable production", "B", "Springer", True),
    ("lecture notes", "C", "Springer", True),
    ("proceedings of the", "B", "IEEE", True),
    ("international conference", "B", "IEEE", True),
]

# Forbidden typographic characters (workspace style hygiene) -> ASCII replacement.
FORBIDDEN_CHARS = {
    "—": "-", "–": "-", "…": "...",
    "​": "", "‌": "", "‍": "",
    "‘": "'", "’": "'", "“": "``", "”": "''",
}

CONF_HINTS = ("conference", "proceedings", "procedia", "ifac", "workshop", "symposium")


def _run_scopus(args: list[str]) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Invoke scopus_api.py as a subprocess with UTF-8 I/O (Windows console
        redirects default to cp1252 and corrupt author names otherwise) and
        return the parsed JSON, or an {'error': ...} dict on any failure.

    Inputs:
        args (list[str]): scopus_api.py CLI arguments (e.g. ['search', q]).

    Outputs:
        result (dict): parsed scopus_api.py output or {'error': <detail>}.
    --------------------------------------------------------------------------
    """
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run([sys.executable, SCOPUS_SCRIPT] + args,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, timeout=90)
    try:
        return json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError):
        return {"error": (proc.stdout or "")[:300] + (proc.stderr or "")[:300]}


def _norm_title(title: str) -> str:
    # Hyphens become spaces BEFORE stripping, so "human-robot" == "human robot";
    # collapsing them instead would fuse the words and break the Jaccard match.
    text = re.sub(r"[-‐-―]", " ", (title or "").lower())
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", text)).strip()


def title_match(a: str, b: str) -> bool:
    """True when the two titles agree on a 60-char prefix or a word-set Jaccard
    similarity above TITLE_JACCARD_MIN (robust to punctuation and truncation)."""
    na, nb = _norm_title(a), _norm_title(b)
    if na[:60] == nb[:60]:
        return True
    wa, wb = set(na.split()), set(nb.split())
    return len(wa & wb) / max(1, len(wa | wb)) > TITLE_JACCARD_MIN


# Publisher families that must be identified BEFORE the generic substring pass:
# "Frontiers in Robotics and AI" contains the substring "robotics" and would
# otherwise be graded as the MDPI journal Robotics (a real production miss).
VENUE_PREFIX_OVERRIDES: list[tuple[str, str, str, bool]] = [
    ("frontiers in", "B", "Frontiers", False),
]


def grade_venue(journal: str, aggregation_type: str = "") -> tuple[str, str, bool]:
    """Return (grade, publisher, approved) for a venue name; prefix overrides
    run first (publisher families), then the VENUE_GRADES substring pass;
    unknown venues get ('?', '?', False) and must be reviewed manually."""
    name = (journal or "").lower().strip()
    for prefix, grade, publisher, approved in VENUE_PREFIX_OVERRIDES:
        if name.startswith(prefix):
            return grade, publisher, approved
    for substring, grade, publisher, approved in VENUE_GRADES:
        if substring in name:
            return grade, publisher, approved
    if (aggregation_type or "").lower() == "conference proceeding":
        return "B", "?", False
    return "?", "?", False


def resolve_titles(candidates: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve each candidate title to its Scopus record via a strict
        TITLE("<title>") query. A candidate with no title-matching hit stays
        found=False (never the first weak hit - that pollutes the corpus with
        wrong DOIs, the production failure this script encodes).

    Inputs:
        candidates (list[dict]): [{key, source, title}, ...]

    Outputs:
        corpus (dict): {key: record} with found/doi/journal/year/... fields.
    --------------------------------------------------------------------------
    """
    corpus: dict[str, dict[str, Any]] = {}
    for cand in candidates:
        key, title = cand["key"], cand["title"]
        res = _run_scopus(["search", f'TITLE("{title}")', "--count", "3"])
        record: dict[str, Any] = {"key": key, "source": cand.get("source", ""),
                                  "query_title": title, "found": False}
        for hit in res.get("results", []):
            if title_match(title, hit.get("title", "")):
                record.update(hit)
                record["found"] = True
                break
        corpus[key] = record
        logger.info("[BIB-BATCH] resolve %s: %s doi=%s", key,
                    "OK" if record["found"] else "MISS", record.get("doi", "-"))
        time.sleep(CALL_DELAY_S)
    return corpus


def enrich_corpus(corpus: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Enrich every found record with the citation payload (abstract, authors,
        citation count, publisher) via scopus_api.py cite, then attach the venue
        grade and a Step 3 validation status.

    Inputs:
        corpus (dict): output of resolve_titles (or compatible).

    Outputs:
        corpus (dict): same keys, enriched in place and returned.
    --------------------------------------------------------------------------
    """
    for key, record in corpus.items():
        doi = record.get("doi")
        if not record.get("found") or not doi:
            record["validation"] = "[UNVERIFIED: no DOI]"
            continue
        res = _run_scopus(["cite", doi])
        hit = (res.get("results") or [res])[0] if isinstance(res, dict) else {}
        for field in ("abstract", "authors", "citations", "publisher",
                      "journal", "year", "title", "volume", "pages"):
            if isinstance(hit, dict) and hit.get(field):
                record[field] = hit[field]
        grade, publisher, approved = grade_venue(record.get("journal", ""),
                                                 record.get("aggregation_type", ""))
        record["grade"] = grade
        record["publisher_guess"] = record.get("publisher") or publisher
        record["publisher_approved"] = approved
        missing = [f for f in ("title", "authors", "journal") if not record.get(f)]
        record["validation"] = "OK" if not missing else f"[UNVERIFIED: {','.join(missing)}]"
        logger.info("[BIB-BATCH] enrich %s: grade=%s approved=%s cit=%s",
                    key, grade, approved, record.get("citations", "?"))
        time.sleep(CALL_DELAY_S)
    return corpus


def _format_authors(authors: Any) -> str:
    """Scopus cite returns authors as a list of dicts; flatten to BibTeX form."""
    if isinstance(authors, list):
        parts = []
        for author in authors:
            if isinstance(author, dict):
                display = author.get("display") or (
                    author.get("surname", "") + ", " +
                    author.get("given_name", author.get("initials", "")))
                parts.append(display.strip(", "))
            else:
                parts.append(str(author))
        return " and ".join(parts)
    return authors or ""


def _latex_escape(value: Any) -> str:
    text = _format_authors(value) if isinstance(value, list) else str(value or "")
    for char, replacement in FORBIDDEN_CHARS.items():
        text = text.replace(char, replacement)
    return text.replace("&", r"\&").replace("%", r"\%").replace("_", r"\_")


def generate_bib(corpus: dict[str, dict[str, Any]], excluded: dict[str, str] | None = None,
                 flagged: dict[str, str] | None = None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Emit a BibTeX database from an enriched corpus: one entry per validated
        record with doi + clickable url + a grade/source comment line, following
        the workspace citation conventions. Excluded entries become '@'-free
        comment blocks (BibTeX parses any stray '@'); flagged entries stay
        active with the flag appended to their comment.

    Inputs:
        corpus (dict): enriched corpus.
        excluded (dict | None): {key: reason} entries to comment out.
        flagged (dict | None): {key: flag text} entries kept but flagged.

    Outputs:
        bibtex (str): the full .bib content (UTF-8, forbidden chars normalized).
    --------------------------------------------------------------------------
    """
    excluded = excluded or {}
    flagged = flagged or {}
    blocks: list[str] = []
    for key, record in sorted(corpus.items(),
                              key=lambda kv: (kv[1].get("theme", ""), kv[0])):
        if not record.get("found") or not record.get("doi"):
            blocks.append(f"% SKIPPED (unresolved, no Scopus match): {key}")
            continue
        journal = record.get("journal", "")
        is_conf = any(h in journal.lower() for h in CONF_HINTS) or \
            (record.get("aggregation_type", "").lower() == "conference proceeding")
        entry_type = "inproceedings" if is_conf else "article"
        venue_field = "booktitle" if is_conf else "journal"
        doi = record["doi"]
        lines = [f"@{entry_type}{{{key},",
                 f"  author  = {{{_latex_escape(record.get('authors', ''))}}},",
                 f"  title   = {{{_latex_escape(record.get('title', ''))}}},",
                 f"  {venue_field} = {{{_latex_escape(journal)}}},",
                 f"  year    = {{{str(record.get('year', ''))[:4]}}},"]
        if record.get("volume"):
            lines.append(f"  volume  = {{{record['volume']}}},")
        if record.get("pages"):
            lines.append(f"  pages   = {{{record['pages']}}},")
        lines += [f"  doi     = {{{doi}}},",
                  f"  url     = {{https://doi.org/{doi}}},", "}"]
        comment = (f"% [GRADE: {record.get('grade', '?')}] {journal} -- "
                   f"citations: {record.get('citations', '?')} -- "
                   f"source: {record.get('source', '')}")
        if key in flagged:
            comment += " -- " + flagged[key]
        if key in excluded:
            # No '@' anywhere in the excluded block: BibTeX would parse it.
            body = "\n".join("% " + line.replace("@", "[at]") for line in lines)
            blocks.append(f"% EXCLUDED FROM SYNTHESIS: {excluded[key]}\n{body}\n{comment}")
        else:
            blocks.append("\n".join(lines) + "\n" + comment)
    return "\n\n".join(blocks) + "\n"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Batch corpus resolution/enrichment/BibTeX")
    parser.add_argument("mode", choices=["resolve", "enrich", "bib", "all"])
    parser.add_argument("input", help="candidates.json (resolve/all) or corpus.json (enrich/bib)")
    parser.add_argument("--out", default=None, help="output path (mode-dependent default)")
    parser.add_argument("--corpus", default="corpus.json", help="corpus path for mode 'all'")
    parser.add_argument("--bib", default="review.bib", help="bib path for mode 'all'")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as handle:
        data = json.load(handle)

    if args.mode in ("resolve", "all"):
        corpus = resolve_titles(data)
        out = args.corpus if args.mode == "all" else (args.out or "corpus.json")
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(corpus, handle, ensure_ascii=False, indent=1)
        logger.info("[BIB-BATCH] resolved %d candidates -> %s", len(corpus), out)
        data = corpus
    if args.mode in ("enrich", "all"):
        corpus = enrich_corpus(data if isinstance(data, dict) else
                               {r["key"]: r for r in data})
        out = args.corpus if args.mode == "all" else (args.out or args.input)
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(corpus, handle, ensure_ascii=False, indent=1)
        logger.info("[BIB-BATCH] enriched %d records -> %s", len(corpus), out)
        data = corpus
    if args.mode in ("bib", "all"):
        bib = generate_bib(data)
        out = args.bib if args.mode == "all" else (args.out or "review.bib")
        with open(out, "w", encoding="utf-8") as handle:
            handle.write(bib)
        logger.info("[BIB-BATCH] wrote %s (%d active entries)", out, bib.count("\n@") + bib.startswith("@"))


if __name__ == "__main__":
    main()