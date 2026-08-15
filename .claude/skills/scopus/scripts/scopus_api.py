"""
scopus_api.py — Scopus REST API client for the Claude Code /scopus skill.

Usage:
  python scopus_api.py search "<query>" [--count N] [--year_min YYYY] [--sort ORDER]
                                        [--insttoken TOKEN]
  python scopus_api.py cite "<DOI>"     [--insttoken TOKEN]
  python scopus_api.py validate "<DOI or title>" [--insttoken TOKEN]
  python scopus_api.py verify "<DOI or title>" \\
      [--expected-title "..."] [--expected-authors "Smith, J.; Doe, A."] \\
      [--expected-journal "..."] [--expected-volume "..."] \\
      [--expected-issue "..."] [--expected-pages "..."] \\
      [--expected-year "YYYY"] [--insttoken TOKEN]
  python scopus_api.py author "<name>"  [--insttoken TOKEN]
  python scopus_api.py journal "<journal name>" [--issn "<ISSN>"] [--insttoken TOKEN]

Output: JSON to stdout. Errors to stderr with actionable messages.

Requires: SCOPUS_API_KEY env var (set via Windows User environment variables).
          On-campus network or UQAC VPN (or --insttoken for off-campus access).
"""

import argparse
import difflib
import json
import os
import re
import sys
from typing import Any

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)

# Every mode prints JSON with ensure_ascii=False, and a Windows console defaults
# to cp1252: a single record carrying an author-note asterisk (U+2217), a Greek
# letter or a CJK title made the script die on UnicodeEncodeError after the
# Scopus call had already been paid for. Force UTF-8 on the streams we own.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):  # redirected to a non-reconfigurable stream
        pass

# Semantic Scholar fallback (same scripts/ directory). Used to backfill the
# full author list when Scopus returns only the first creator or an empty
# author block. Import is best-effort: if the sibling module is unavailable,
# enrichment is silently skipped and the pure-Scopus behaviour is preserved.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import semantic_scholar_api as s2
except ImportError:
    s2 = None

from doi_publisher import annotate as _annotate_publisher  # noqa: E402

# Global toggle, flipped off by the --no-s2 CLI flag.
_S2_FALLBACK_ENABLED = True

SEARCH_URL = "https://api.elsevier.com/content/search/scopus"
ABSTRACT_URL = "https://api.elsevier.com/content/abstract/doi/{doi}"
AUTHOR_SEARCH_URL = "https://api.elsevier.com/content/search/author"
SERIAL_TITLE_URL = "https://api.elsevier.com/content/serial/title"

# Accepted values of the search `sort` parameter, and the reason each exists.
# MEASURED (2026-08-05, TITLE-ABS-KEY(free space optical communication), 17 467
# hits, count=5, one session): sending NO sort makes Scopus answer by descending
# date, so the five hits were all 2026 papers cited 0 to 3 times and no founding
# work could ever surface. `-citedby-count` answered Khalighi 2014 (2434
# citations) in fourth position, the very reference a literature task had had to
# go and fetch elsewhere. `relevancy` is accepted by the API but was worthless on
# that query (hits cited 0, 15, 0, 14, 3), so it is offered and not defaulted.
# The three variants all return HTTP 200 and the same totalResults, so a recipe
# that only checks the status code proves nothing.
SORT_CHOICES = (
    "-citedby-count",   # most cited first: discovery of the founding works
    "citedby-count",    # least cited first: rarely useful, kept for symmetry
    "-coverDate",       # newest first: delta searches, "most recent papers" lists
    "coverDate",        # oldest first: historical ordering
    "-pubyear",         # newest first, by year granularity
    "pubyear",          # oldest first, by year granularity
    "relevancy",        # Scopus relevance ranking
    "none",             # send no sort parameter at all (legacy Scopus default)
)
DEFAULT_SEARCH_SORT = "-citedby-count"

# Dash-free aliases. argparse reads `--sort -coverDate` as a new option and
# refuses the call, so the canonical descending forms are only reachable as
# `--sort=-coverDate`. The aliases remove that trap from every caller.
SORT_ALIASES = {
    "cited": "-citedby-count",
    "least-cited": "citedby-count",
    "recent": "-coverDate",
    "oldest": "coverDate",
    "recent-year": "-pubyear",
    "oldest-year": "pubyear",
}


def resolve_sort(value: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn a --sort argument into the value Scopus expects, accepting both
        the canonical API form and the dash-free alias.

    Inputs:
        value (str): "recent", "-coverDate", "none", ...

    Outputs:
        sort (str): a member of SORT_CHOICES. Exits with an actionable message
            on an unknown value rather than sending it to Scopus, which would
            answer 200 with a silently unsorted list.
    --------------------------------------------------------------------------
    """
    candidate = SORT_ALIASES.get(value.strip().lower(), value.strip())
    if candidate not in SORT_CHOICES:
        print(
            f"ERROR: unknown --sort value '{value}'.\n"
            f"Accepted: {', '.join(SORT_CHOICES)}\n"
            f"Aliases (no leading dash needed): {', '.join(SORT_ALIASES)}",
            file=sys.stderr,
        )
        sys.exit(2)
    return candidate

# Uppercase words that open a parenthesis without being a Scopus field code.
_BOOLEAN_TOKENS = frozenset({"AND", "OR", "NOT", "PRE", "W", "ANDNOT"})
# A Scopus field code is uppercase, may carry hyphens, and opens a parenthesis:
# TITLE(, TITLE-ABS-KEY(, AU-ID(, AUTHLASTNAME(, SRCTITLE(, DOI(, ...
_FIELD_CODE = re.compile(r"\b([A-Z][A-Z-]{1,24})\s*\(")
_BARE_YEAR_FILTER = re.compile(r"\bPUBYEAR\b")


def qualify_query(query: str) -> tuple[str, bool]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Wrap a bare keyword query in TITLE-ABS-KEY() so it searches the title,
        abstract and keywords rather than every indexed field.

        MEASURED (2026-08-12): with the new citation-first ordering, the bare
        query "free space optical communication" answered Elements of
        Information Theory, QUANTUM ESPRESSO and GEANT4 — the most-cited papers
        in all of Scopus that happen to contain those words somewhere, in a
        reference list included. Unqualified, the default field is ALL, and
        sorting by citations turns that breadth into pure noise. The same query
        as TITLE-ABS-KEY() reproduces the measured table exactly, Khalighi 2014
        in fourth position.

        A query that already names a field, or filters on PUBYEAR, is passed
        through untouched: AU-ID(...), TITLE(...), and every boolean query the
        agents already send keep their exact meaning.

    Inputs:
        query (str): the query as the caller wrote it.

    Outputs:
        (query, qualified) (tuple[str, bool]): the query to send, and whether
            this function wrapped it.
    --------------------------------------------------------------------------
    """
    stripped = query.strip()
    if not stripped:
        return stripped, False
    for match in _FIELD_CODE.finditer(stripped):
        if match.group(1).replace("-", "") not in _BOOLEAN_TOKENS:
            return stripped, False
    if _BARE_YEAR_FILTER.search(stripped):
        return stripped, False
    return f"TITLE-ABS-KEY({stripped})", True


def _get_api_key() -> str:
    key = os.environ.get("SCOPUS_API_KEY", "").strip()
    if not key:
        fallback = os.path.join(os.path.dirname(__file__), "..", ".scopus_key")
        if os.path.exists(fallback):
            with open(fallback) as f:
                key = f.read().strip()
    if not key:
        print(
            "ERROR: SCOPUS_API_KEY is not set.\n"
            "Fix: run in PowerShell:\n"
            "  [System.Environment]::SetEnvironmentVariable('SCOPUS_API_KEY', 'your-key', 'User')\n"
            "Then restart Claude Code.",
            file=sys.stderr,
        )
        sys.exit(1)
    return key


def _make_headers(api_key: str, insttoken: str | None = None) -> dict:
    headers = {"X-ELS-APIKey": api_key, "Accept": "application/json"}
    if insttoken:
        headers["X-ELS-Insttoken"] = insttoken
    return headers


def _check_response(response: requests.Response) -> None:
    if response.status_code == 401:
        print("ERROR 401: Invalid API key. Verify SCOPUS_API_KEY.", file=sys.stderr)
        sys.exit(1)
    if response.status_code == 403:
        print(
            "ERROR 403: Access denied. Connect to UQAC VPN or provide --insttoken.",
            file=sys.stderr,
        )
        sys.exit(1)
    if response.status_code == 429:
        print("ERROR 429: Rate limit exceeded. Wait 60 seconds and retry.", file=sys.stderr)
        sys.exit(1)
    if response.status_code != 200:
        print(f"ERROR {response.status_code}: {response.text[:300]}", file=sys.stderr)
        sys.exit(1)


def _enrich_authors_from_semantic_scholar(record: dict[str, Any]) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Backfill the full ordered author list from Semantic Scholar when the
        Scopus record carries 0 or 1 author. Scopus search results expose only
        the first creator, and a minority of abstract records return an empty
        author block; this recovers the missing co-authors by DOI.

    Inputs:
        record (dict): a Scopus record holding at least 'doi' and 'authors'
            (a list in the {surname, given_name, initials, display} shape).

    Outputs:
        record (dict): the same object, with 'authors_source' always set to
            'scopus' or 'semantic_scholar', and 'authors' replaced only when
            Semantic Scholar returns a strictly longer list. Non-fatal: any S2
            error leaves the Scopus data untouched.
    --------------------------------------------------------------------------
    """
    record.setdefault("authors_source", "scopus")
    if not _S2_FALLBACK_ENABLED or s2 is None:
        return record

    doi = (record.get("doi") or "").strip()
    existing = record.get("authors") or []
    # Scopus already returns the complete ordered list once it has 2+ authors.
    if not doi or len(existing) > 1:
        return record

    try:
        s2_authors = s2.authors_for_doi(doi)
    except Exception as exc:  # defensive: enrichment must never break the audit
        print(f"WARN: Semantic Scholar author backfill failed for {doi}: {exc}", file=sys.stderr)
        return record

    if s2_authors and len(s2_authors) > len(existing):
        record["authors"] = s2_authors
        record["authors_source"] = "semantic_scholar"
    return record


def _search(query: str, count: int, api_key: str, insttoken: str | None,
            year_min: int | None = None, enrich_authors: bool = False,
            sort: str = DEFAULT_SEARCH_SORT, raw_query: bool = False) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Run a Scopus search and print the results as JSON. The result ORDER is
        the point: see SORT_CHOICES for the measurement that sets the default
        to `-citedby-count`. A caller that needs recency (delta search for new
        papers, "most recent publications" list) must ask for `-coverDate`
        explicitly; the default would otherwise rank a 20-year-old classic
        above this month's paper.

    Inputs:
        query (str): Scopus query, any supported field syntax.
        count (int): maximum number of results.
        api_key (str), insttoken (str | None): Scopus credentials.
        year_min (int | None): lower publication-year bound, appended to the
            query as PUBYEAR.
        enrich_authors (bool): backfill full author lists from Semantic Scholar.
        sort (str): one of SORT_CHOICES. "none" sends no sort parameter and
            restores the legacy Scopus ordering.
        raw_query (bool): send the query verbatim, without the TITLE-ABS-KEY
            wrapping described in qualify_query.

    Outputs:
        result (None): JSON on stdout, carrying the resolved `query`, whether
            it was `query_qualified`, and the `sort` actually applied, so
            neither the field scope nor the order is a silent property.
    --------------------------------------------------------------------------
    """
    scoped_query, qualified = (query.strip(), False) if raw_query else qualify_query(query)
    full_query = (scoped_query if year_min is None
                  else f"({scoped_query}) AND PUBYEAR > {year_min - 1}")
    params = {
        "query": full_query,
        "count": count,
        "field": (
            "dc:title,dc:creator,prism:publicationName,prism:coverDate,"
            "prism:doi,citedby-count,dc:description,"
            "prism:volume,prism:issueIdentifier,prism:pageRange,"
            "prism:aggregationType,prism:publisher"
        ),
    }
    if sort != "none":
        params["sort"] = sort
    resp = requests.get(
        SEARCH_URL, headers=_make_headers(api_key, insttoken), params=params, timeout=30
    )
    _check_response(resp)

    entries = resp.json().get("search-results", {}).get("entry", [])
    results = [
        # `publisher` is what Scopus states and `publisher_by_prefix` is what the
        # DOI registrant says; where they disagree the prefix is the reliable one.
        _annotate_publisher({
            "title": e.get("dc:title", ""),
            "authors": e.get("dc:creator", ""),
            "journal": e.get("prism:publicationName", ""),
            "year": (e.get("prism:coverDate") or "")[:4],
            "doi": e.get("prism:doi", ""),
            "citations": e.get("citedby-count", "0"),
            "abstract": e.get("dc:description", ""),
            "volume": e.get("prism:volume", ""),
            "issue": e.get("prism:issueIdentifier", ""),
            "pages": e.get("prism:pageRange", ""),
            "aggregation_type": e.get("prism:aggregationType", ""),
            "publisher": e.get("prism:publisher", ""),
        })
        for e in entries
    ]

    # Scopus search returns only dc:creator (the first author). When asked,
    # backfill the full ordered list per result from Semantic Scholar. One S2
    # request per DOI, throttled to 1 req/s, so this is opt-in for large sets.
    if enrich_authors and _S2_FALLBACK_ENABLED and s2 is not None:
        for r in results:
            r["authors_source"] = "scopus"
            doi = (r.get("doi") or "").strip()
            if not doi:
                continue
            try:
                s2_authors = s2.authors_for_doi(doi)
            except Exception as exc:
                print(f"WARN: Semantic Scholar author backfill failed for {doi}: {exc}", file=sys.stderr)
                continue
            if s2_authors:
                r["authors_full"] = [a["display"] for a in s2_authors]
                r["authors_source"] = "semantic_scholar"

    print(json.dumps({
        "mode": "search",
        "query": full_query,
        "query_qualified": qualified,
        "sort": sort,
        "count": len(results),
        "results": results,
    }, ensure_ascii=False, indent=2))


def _fetch_abstract_record(doi: str, api_key: str, insttoken: str | None) -> dict[str, Any]:
    """
    Pull the full Scopus abstract retrieval record for a DOI and return a flat dict
    with every field the auditor compares against the bibliography:
        title, authors (full ordered list), journal, year, volume, issue, pages,
        starting_page, ending_page, doi, issn, publisher, aggregation_type,
        abstract, keywords, citations.
    """
    url = ABSTRACT_URL.format(doi=doi.strip())
    params = {
        "field": (
            "dc:title,dc:creator,prism:publicationName,prism:coverDate,"
            "prism:doi,citedby-count,dc:description,prism:issn,authkeywords,"
            "prism:volume,prism:issueIdentifier,prism:pageRange,"
            "prism:startingPage,prism:endingPage,prism:aggregationType,"
            "dc:publisher,prism:publisher,affiliation"
        )
    }
    resp = requests.get(
        url, headers=_make_headers(api_key, insttoken), params=params, timeout=30
    )
    _check_response(resp)

    data = resp.json().get("abstracts-retrieval-response", {})
    core = data.get("coredata", {})

    raw_authors = data.get("authors", {}).get("author", [])
    if isinstance(raw_authors, dict):
        raw_authors = [raw_authors]
    authors = []
    for a in raw_authors:
        surname = (a.get("ce:surname") or "").strip()
        given = (a.get("ce:given-name") or a.get("preferred-name", {}).get("ce:given-name") or "").strip()
        initials = (a.get("ce:initials") or a.get("preferred-name", {}).get("ce:initials") or "").strip()
        authors.append({
            "surname": surname,
            "given_name": given,
            "initials": initials,
            "display": f"{surname}, {given}".strip(", ").strip(),
        })

    keywords = data.get("authkeywords", {}).get("author-keyword", [])
    if isinstance(keywords, dict):
        keywords = [keywords]
    keyword_list = [k.get("$", "") for k in keywords if isinstance(k, dict)]

    publisher = core.get("dc:publisher") or core.get("prism:publisher") or ""

    record = {
        "doi": core.get("prism:doi", doi),
        "title": core.get("dc:title", ""),
        "authors": authors,
        "journal": core.get("prism:publicationName", ""),
        "year": (core.get("prism:coverDate") or "")[:4],
        "volume": core.get("prism:volume", ""),
        "issue": core.get("prism:issueIdentifier", ""),
        "pages": core.get("prism:pageRange", ""),
        "starting_page": core.get("prism:startingPage", ""),
        "ending_page": core.get("prism:endingPage", ""),
        "aggregation_type": core.get("prism:aggregationType", ""),
        "publisher": publisher,
        "issn": core.get("prism:issn", ""),
        "citations": core.get("citedby-count", "0"),
        "abstract": core.get("dc:description", ""),
        "keywords": keyword_list,
    }
    # The DOI prefix names the registrant and settles who published the paper
    # when `publisher` above disagrees with it (see doi_publisher.py).
    _annotate_publisher(record)
    # Recover the full author list from Semantic Scholar if Scopus gave none.
    return _enrich_authors_from_semantic_scholar(record)


def _cite(doi: str, api_key: str, insttoken: str | None) -> None:
    record = _fetch_abstract_record(doi, api_key, insttoken)
    record["mode"] = "cite"
    print(json.dumps(record, ensure_ascii=False, indent=2))


def _validate_search(query: str, api_key: str, insttoken: str | None) -> tuple[int, list[dict]]:
    """Single Scopus title query for validate mode. Returns (total, entries)."""
    params = {
        "query": query,
        "count": 5,
        "field": "dc:title,dc:creator,prism:publicationName,prism:coverDate,prism:doi,citedby-count",
    }
    resp = requests.get(
        SEARCH_URL, headers=_make_headers(api_key, insttoken), params=params, timeout=30
    )
    _check_response(resp)
    data = resp.json().get("search-results", {})
    return int(data.get("opensearch:totalResults", 0)), data.get("entry", [])


def _validate(ref: str, api_key: str, insttoken: str | None) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Coarse existence check of a reference by DOI or title. A DOI resolves
        through `cite`; a title is queried as a quoted phrase, which is the
        precise form, and only falls back to the loose form when the phrase
        returns nothing, so recall is never lost.

        The mode publishes a similarity score and refuses to designate a single
        record when the title is ambiguous. MEASURED (2026-08-05): the exact
        title "Deep learning for unmanned aerial vehicles detection: A review"
        returns 6 records, and the FIRST one is a corrigendum to an unrelated
        paper on photovoltaic thermal imaging. A client reading `results[0]`
        therefore cited the wrong reference with nothing to warn it. Field-level
        checking belongs to `verify`; this is the guard rail `validate` lacked.

    Inputs:
        ref (str): a DOI ("10." prefixed) or a paper title.
        api_key (str), insttoken (str | None): Scopus credentials.

    Outputs:
        result (None): JSON on stdout. There is no `found` and no `record` key:
            read `total_found` and `results`, and read `ambiguous` before using
            `results[0]`.
    --------------------------------------------------------------------------
    """
    # DOI lookup takes priority
    if ref.startswith("10."):
        _cite(ref, api_key, insttoken)
        return

    # Scopus takes the double quote as the phrase delimiter, so a quote inside
    # the title would truncate the query rather than be searched for.
    cleaned = ref.replace('"', " ").replace("{", " ").replace("}", " ").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)

    query_form = "phrase"
    query = f'TITLE("{cleaned}")'
    total, entries = _validate_search(query, api_key, insttoken)
    if total == 0:
        # The loose form is what this mode used to send. Keeping it as a
        # fallback means the stricter query can only add precision, never
        # remove a record that used to be found.
        query_form = "loose"
        query = f"TITLE({cleaned})"
        total, entries = _validate_search(query, api_key, insttoken)

    results = [
        _annotate_publisher({
            "title": e.get("dc:title", ""),
            "authors": e.get("dc:creator", ""),
            "journal": e.get("prism:publicationName", ""),
            "year": (e.get("prism:coverDate") or "")[:4],
            "doi": e.get("prism:doi", ""),
            "citations": e.get("citedby-count", "0"),
            "title_similarity": _title_similarity(ref, e.get("dc:title", "")),
        })
        for e in entries
    ]

    best_index: int | None = None
    if results:
        best_index = max(range(len(results)), key=lambda i: results[i]["title_similarity"])

    ambiguous = total > 1
    warning = ""
    if ambiguous:
        warning = (
            f"{total} records match this title. Do NOT take results[0]: on a measured case "
            "the first hit was a corrigendum to an unrelated paper. Compare `title_similarity`, "
            "and confirm the chosen record with `verify` before citing it."
        )
    elif total == 0:
        warning = "No record matches this title in Scopus."

    print(json.dumps({
        "mode": "validate",
        "query": ref,
        "scopus_query": query,
        "query_form": query_form,
        "total_found": total,
        "ambiguous": ambiguous,
        "best_match_index": best_index,
        "warning": warning,
        "results": results,
    }, ensure_ascii=False, indent=2))


def _norm_text(s: str) -> str:
    """Lowercase, strip punctuation and LaTeX braces, collapse whitespace."""
    if not s:
        return ""
    s = s.replace("{", "").replace("}", "").replace("\\", " ")
    s = re.sub(r"[\.,;:'\"`\-_/]+", " ", s.lower())
    s = re.sub(r"\s+", " ", s).strip()
    leading = ("the ", "a ", "an ", "le ", "la ", "les ", "un ", "une ", "des ")
    for prefix in leading:
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return s


def _title_similarity(requested: str, returned: str) -> float:
    """
    --------------------------------------------------------------------------
    Purpose:
        Score how close a returned title is to the requested one, so a caller
        can see that a hit is a near-miss instead of assuming Scopus ranked the
        right record first.

    Inputs:
        requested (str): the title as asked for.
        returned (str): the title as returned by Scopus.

    Outputs:
        score (float): 0.0 to 1.0, rounded to three decimals, on the normalized
            forms (case, punctuation and leading article stripped).
    --------------------------------------------------------------------------
    """
    a, b = _norm_text(requested), _norm_text(returned)
    if not a or not b:
        return 0.0
    return round(difflib.SequenceMatcher(None, a, b).ratio(), 3)


def _norm_pages(s: str) -> str:
    if not s:
        return ""
    s = s.lower().replace("pp.", "").replace("p.", "").replace(" ", "")
    s = s.replace("—", "-").replace("–", "-").replace("--", "-")
    return s.strip()


def _norm_volissue(s: str) -> str:
    if not s:
        return ""
    s = s.lower()
    for tok in ("vol.", "vol", "volume", "no.", "no", "n°", "number", "issue", "iss.", "iss"):
        s = s.replace(tok, "")
    return re.sub(r"\s+", "", s).strip()


def _parse_expected_authors(raw: str) -> list[dict[str, str]]:
    """
    Accept either BibTeX 'A and B and C' or 'Smith, J.; Doe, A.' formats.
    Return a list of {surname, given_or_initials} dicts in the cited order.
    """
    if not raw:
        return []
    if " and " in raw and ";" not in raw:
        parts = [p.strip() for p in raw.split(" and ")]
    else:
        parts = [p.strip() for p in raw.replace("&", ";").split(";")]
    out = []
    for p in parts:
        if not p:
            continue
        if "," in p:
            surname, rest = p.split(",", 1)
            out.append({"surname": surname.strip(), "given_or_initials": rest.strip()})
        else:
            tokens = p.split()
            if len(tokens) >= 2:
                out.append({"surname": tokens[-1].strip(), "given_or_initials": " ".join(tokens[:-1]).strip()})
            else:
                out.append({"surname": p.strip(), "given_or_initials": ""})
    return out


def _author_match(expected: dict[str, str], scopus: dict[str, str]) -> bool:
    exp_surname = _norm_text(expected.get("surname", ""))
    sco_surname = _norm_text(scopus.get("surname", ""))
    if not exp_surname or not sco_surname or exp_surname != sco_surname:
        return False
    exp_initial = _norm_text(expected.get("given_or_initials", ""))[:1]
    sco_initial = (_norm_text(scopus.get("given_name", "")) or _norm_text(scopus.get("initials", "")))[:1]
    if exp_initial and sco_initial and exp_initial != sco_initial:
        return False
    return True


def _check_field(label: str, expected: str | None, scopus_value: str, normalizer) -> dict[str, Any]:
    if expected is None or expected == "":
        return {"field": label, "match": None, "expected": None, "scopus": scopus_value, "note": "not provided"}
    norm_exp = normalizer(expected)
    norm_sco = normalizer(scopus_value)
    return {
        "field": label,
        "match": bool(norm_exp) and bool(norm_sco) and norm_exp == norm_sco,
        "expected": expected,
        "scopus": scopus_value,
    }


def _verify(
    ref: str,
    api_key: str,
    insttoken: str | None,
    expected_title: str | None,
    expected_authors: str | None,
    expected_journal: str | None,
    expected_volume: str | None,
    expected_issue: str | None,
    expected_pages: str | None,
    expected_year: str | None,
) -> None:
    """
    Per-field validation against Scopus. Resolve the paper by DOI when possible,
    otherwise by title search (highest-similarity hit). Report per-field match
    status; the paper is 'valid' only when every supplied field matches.
    """
    record: dict[str, Any] | None = None
    resolution = "doi"
    if ref.startswith("10."):
        record = _fetch_abstract_record(ref, api_key, insttoken)
    else:
        params = {
            "query": f"TITLE({ref})",
            "count": 5,
            "field": "dc:title,prism:doi,prism:coverDate",
        }
        resp = requests.get(
            SEARCH_URL, headers=_make_headers(api_key, insttoken), params=params, timeout=30
        )
        _check_response(resp)
        entries = resp.json().get("search-results", {}).get("entry", [])
        norm_ref = _norm_text(ref)
        best_doi = ""
        for e in entries:
            if _norm_text(e.get("dc:title", "")) == norm_ref and e.get("prism:doi"):
                best_doi = e["prism:doi"]
                break
        if not best_doi and entries and entries[0].get("prism:doi"):
            best_doi = entries[0]["prism:doi"]
            resolution = "title-best-match"
        if not best_doi:
            print(json.dumps({
                "mode": "verify",
                "query": ref,
                "valid": False,
                "resolution": "not-found",
                "field_checks": [],
                "summary": "Scopus did not return any record for this title.",
            }, ensure_ascii=False, indent=2))
            return
        record = _fetch_abstract_record(best_doi, api_key, insttoken)
        resolution = "title-best-match" if resolution == "title-best-match" else "title-exact"

    checks: list[dict[str, Any]] = []
    checks.append(_check_field("title", expected_title, record["title"], _norm_text))
    checks.append(_check_field("journal", expected_journal, record["journal"], _norm_text))
    checks.append(_check_field("volume", expected_volume, record["volume"], _norm_volissue))
    checks.append(_check_field("issue", expected_issue, record["issue"], _norm_volissue))
    checks.append(_check_field("pages", expected_pages, record["pages"], _norm_pages))
    checks.append(_check_field("year", expected_year, record["year"], lambda s: re.sub(r"\D", "", s or "")))

    author_check: dict[str, Any] = {"field": "authors"}
    if expected_authors:
        expected_list = _parse_expected_authors(expected_authors)
        scopus_authors = record["authors"]
        per_position: list[dict[str, Any]] = []
        all_ok = bool(expected_list) and len(expected_list) <= len(scopus_authors)
        for idx, exp in enumerate(expected_list):
            sco = scopus_authors[idx] if idx < len(scopus_authors) else {}
            ok = _author_match(exp, sco) if sco else False
            per_position.append({
                "position": idx + 1,
                "match": ok,
                "expected": exp,
                "scopus": {
                    "surname": sco.get("surname", ""),
                    "given_name": sco.get("given_name", ""),
                    "initials": sco.get("initials", ""),
                } if sco else None,
            })
            if not ok:
                all_ok = False
        author_check.update({
            "match": all_ok,
            "expected_count": len(expected_list),
            "scopus_count": len(scopus_authors),
            "by_position": per_position,
        })
    else:
        author_check.update({"match": None, "note": "not provided",
                             "scopus": [a["display"] for a in record["authors"]]})
    checks.append(author_check)

    decisive = [c for c in checks if c.get("match") is not None]
    valid = bool(decisive) and all(c["match"] for c in decisive)
    mismatched = [c["field"] for c in decisive if not c["match"]]

    print(json.dumps({
        "mode": "verify",
        "query": ref,
        "resolution": resolution,
        "scopus_doi": record["doi"],
        "valid": valid,
        "mismatched_fields": mismatched,
        "field_checks": checks,
        "scopus_record": record,
    }, ensure_ascii=False, indent=2))


SERIAL_FIELDS = ("Title,ISSN,SJRList,CiteScoreYearInfoList,SubjectArea,"
                 "Publisher,SNIPList,prism:aggregationType,prism:isbn")


def issn_candidates(raw: str) -> list[str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Turn the raw `issn` string of a Scopus abstract record into the list of
        hyphenated 8-character ISSNs to try against the Serial Title API. A
        record may carry both the print and the electronic ISSN, joined by a
        space or a semicolon, and only one of the two resolves.

    Inputs:
        raw (str): the record's issn field, e.g. "00189456 15579662".

    Outputs:
        candidates (list[str]): ["0018-9456", "1557-9662"], order preserved,
            duplicates removed.
    --------------------------------------------------------------------------
    """
    candidates: list[str] = []
    for token in re.findall(r"[0-9xX]{8}", (raw or "").replace("-", "")):
        hyphenated = f"{token[:4]}-{token[4:]}"
        if hyphenated not in candidates:
            candidates.append(hyphenated)
    return candidates


def normalize_venue_type(aggregation_type: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Canonicalize prism:aggregationType. MEASURED: the Serial Title API
        answers "conferenceproceeding" (no space) while the search and abstract
        APIs answer "Conference Proceeding", so a plain equality test silently
        declared Procedia CIRP unrankable and dropped its quartile.

    Inputs:
        aggregation_type (str): the raw prism:aggregationType value.

    Outputs:
        venue_type (str): spaced lowercase form, e.g. "conference proceeding",
            or "unknown" when the field is absent.
    --------------------------------------------------------------------------
    """
    collapsed = re.sub(r"[^a-z]", "", (aggregation_type or "").lower())
    known = {
        "journal": "journal",
        "conferenceproceeding": "conference proceeding",
        "bookseries": "book series",
        "tradejournal": "trade journal",
        "book": "book",
    }
    if collapsed in known:
        return known[collapsed]
    return (aggregation_type or "").strip().lower() or "unknown"


SJR_APPLICABLE_TYPES = ("journal", "conference proceeding", "trade journal")


def quartile_from_percentile(percentile: int | None) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Map a CiteScore subject-area percentile to its quartile. Scopus
        publishes the percentile, not the quartile, so the caller derives it.

    Inputs:
        percentile (int | None): 0-100, or None when no percentile was returned.

    Outputs:
        quartile (str): "Q1" (>=75), "Q2" (>=50), "Q3" (>=25), "Q4" (<25),
            or "" when the percentile is unknown.
    --------------------------------------------------------------------------
    """
    if percentile is None:
        return ""
    if percentile >= 75:
        return "Q1"
    if percentile >= 50:
        return "Q2"
    if percentile >= 25:
        return "Q3"
    return "Q4"


def _serial_get(params: dict, api_key: str, insttoken: str | None) -> dict | None:
    """Query the Serial Title API. Authentication and quota failures stay fatal
    (they are configuration errors), but a per-ISSN miss returns None so the
    caller can try the next candidate instead of aborting the whole lookup."""
    resp = requests.get(
        SERIAL_TITLE_URL, headers=_make_headers(api_key, insttoken), params=params, timeout=30
    )
    if resp.status_code in (401, 403, 429):
        _check_response(resp)
    if resp.status_code != 200:
        return None
    return resp.json()


def _best_citescore_percentile(entry: dict) -> int | None:
    """Highest subject-area percentile of the most recent Complete CiteScore
    year, as returned by the CITESCORE view of the Serial Title API."""
    years = entry.get("citeScoreYearInfoList", {}).get("citeScoreYearInfo", [])
    if isinstance(years, dict):
        years = [years]
    for year in years:
        if year.get("@status") != "Complete":
            continue
        best: int | None = None
        infos = year.get("citeScoreInformationList", [])
        if isinstance(infos, dict):
            infos = [infos]
        for info in infos:
            cite_scores = info.get("citeScoreInfo", [])
            if isinstance(cite_scores, dict):
                cite_scores = [cite_scores]
            for cite_score in cite_scores:
                ranks = cite_score.get("citeScoreSubjectRank", [])
                if isinstance(ranks, dict):
                    ranks = [ranks]
                for rank in ranks:
                    percentile = rank.get("percentile")
                    if percentile is not None:
                        percentile = int(percentile)
                        if best is None or percentile > best:
                            best = percentile
        return best
    return None


def _journal_by_issn(raw_issn: str, name: str, api_key: str,
                     insttoken: str | None) -> list[dict[str, Any]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve venue metrics by ISSN, the only lookup that returns populated
        records. MEASURED (2026-08-04, 81-entry TCAS-I corpus): a lookup by
        journal TITLE returns empty stubs — title, publisher and SJR come back
        blank — so do not "simplify" this back to a title query. A record may
        carry several ISSNs (print + electronic); each candidate is tried until
        one resolves.

    Inputs:
        raw_issn (str): the ISSN string from the abstract record, possibly
            holding two ISSNs joined by a space or a semicolon.
        name (str): venue name, echoed in the result for traceability.
        api_key (str), insttoken (str | None): Scopus credentials.

    Outputs:
        results (list[dict]): zero or one venue record, carrying the same keys
            as the title lookup plus `issn_used`, `pct` (best CiteScore subject
            percentile) and `quartile` derived from it.
    --------------------------------------------------------------------------
    """
    candidates = issn_candidates(raw_issn)
    if not candidates:
        return []

    for candidate in candidates:
        # No `field` parameter here. MEASURED: combining `field` with an ISSN
        # lookup makes the API answer 200 with a two-key stub (aggregationType
        # and url only), which is what "empty stub" looks like from the caller.
        payload = _serial_get({"issn": candidate, "view": "STANDARD"}, api_key, insttoken)
        if not payload:
            continue
        entry = payload.get("serial-metadata-response", {}).get("entry", [{}])
        entry = entry[0] if isinstance(entry, list) else entry
        if not entry or entry.get("@error"):
            continue

        sjr_list = entry.get("SJRList", {}).get("SJR", [])
        if isinstance(sjr_list, dict):
            sjr_list = [sjr_list]
        title = entry.get("dc:title", "")
        if not title and not sjr_list:
            continue        # stub record: try the next ISSN of the pair

        venue_type = normalize_venue_type(entry.get("prism:aggregationType"))
        # The most recent SJR value is the last of the list, not the first.
        record = {
            "title": title,
            "venue_type": venue_type,
            "issn": entry.get("prism:issn", "") or candidate,
            "issn_used": candidate,
            "isbn": entry.get("prism:isbn", ""),
            "publisher": entry.get("dc:publisher", ""),
            "sjr": sjr_list[-1].get("$", "") if sjr_list else "",
            "sjr_applicable": venue_type in SJR_APPLICABLE_TYPES,
            "cite_score": entry.get("citeScoreYearInfoList", {}).get("citeScoreCurrentMetric", ""),
            "subject_areas": [],
            "pct": None,
            "quartile": "",
            "query_name": name,
        }

        payload = _serial_get(
            {"issn": candidate, "view": "CITESCORE"}, api_key, insttoken)
        if payload:
            entry2 = payload.get("serial-metadata-response", {}).get("entry", [{}])
            entry2 = entry2[0] if isinstance(entry2, list) else entry2
            percentile = _best_citescore_percentile(entry2 or {})
            record["pct"] = percentile
            record["quartile"] = quartile_from_percentile(percentile)
        return [record]
    return []


def _journal(name: str, api_key: str, insttoken: str | None, fallback_doi: str | None = None,
             issn: str | None = None) -> None:
    """
    Venue lookup. The Scopus Serial Title API covers journals, conference
    proceedings, book series and trade journals — any venue with an ISSN.
    For one-off books and edited volumes (no ISSN) the API returns nothing;
    in that case, if --fallback-doi is provided, fall back to the abstract
    retrieval API to surface the venue type and publisher.

    With --issn the lookup runs by ISSN and additionally returns `pct` (best
    CiteScore subject percentile) and `quartile`. Prefer it: a lookup by title
    returns empty stubs (measured on the 81-entry TCAS-I corpus), so the ISSN
    read from the entry's `cite` record is the reliable path.

    Output exposes `venue_type` (journal / conference proceeding / book series /
    book / trade journal / unknown) so the caller can decide whether SJR
    quartile rules apply (journals and conference proceedings) or not (books).
    """
    if issn:
        results = _journal_by_issn(issn, name, api_key, insttoken)
        print(json.dumps({
            "mode": "journal",
            "query": name,
            "issn_query": issn,
            "issn_candidates": issn_candidates(issn),
            "results": results,
            "note": (
                "Looked up by ISSN. `quartile` is derived from `pct`, the best CiteScore "
                "subject-area percentile (>=75 Q1, >=50 Q2, >=25 Q3, else Q4). "
                "SJR quartile rules apply only when `sjr_applicable: true`."
            ),
        }, ensure_ascii=False, indent=2))
        return

    params = {
        "title": name,
        "field": SERIAL_FIELDS,
        "count": 3,
    }
    resp = requests.get(
        SERIAL_TITLE_URL, headers=_make_headers(api_key, insttoken), params=params, timeout=30
    )
    _check_response(resp)

    data = resp.json().get("serial-metadata-response", {})
    entries = data.get("entry", [])
    if isinstance(entries, dict):
        entries = [entries]

    results = []
    for e in entries:
        sjr_list = e.get("SJRList", {}).get("SJR", [])
        if isinstance(sjr_list, dict):
            sjr_list = [sjr_list]
        sjr_value = sjr_list[0].get("$", "") if sjr_list else ""

        # CiteScore from most recent Complete year
        cite_score = ""
        cs_years = e.get("CiteScoreYearInfoList", {}).get("CiteScoreYearInfo", [])
        if isinstance(cs_years, dict):
            cs_years = [cs_years]
        for cs in cs_years:
            if cs.get("@status") == "Complete":
                cs_infos = cs.get("CiteScoreInformationList", {}).get("CiteScoreInfo", [])
                if isinstance(cs_infos, dict):
                    cs_infos = [cs_infos]
                if cs_infos:
                    cite_score = cs_infos[0].get("CiteScore", "")
                break

        # Subject areas with quartile when available
        subject_areas = e.get("SubjectArea", [])
        if isinstance(subject_areas, dict):
            subject_areas = [subject_areas]
        areas = []
        for sa in subject_areas[:4]:
            abbrev = sa.get("@abbrevName", "")
            code = sa.get("@code", "")
            areas.append(f"{abbrev} ({code})" if code else abbrev)

        venue_type = normalize_venue_type(e.get("prism:aggregationType"))
        sjr_applicable = venue_type in SJR_APPLICABLE_TYPES

        results.append({
            "title": e.get("dc:title", ""),
            "venue_type": venue_type,
            "issn": e.get("prism:issn", ""),
            "isbn": e.get("prism:isbn", ""),
            "publisher": e.get("dc:publisher", ""),
            "sjr": sjr_value,
            "sjr_applicable": sjr_applicable,
            "cite_score": cite_score,
            "subject_areas": areas,
            # Title lookups do not carry the CiteScore percentile; the keys stay
            # present so both lookup paths return the same shape.
            "pct": None,
            "quartile": "",
        })

    # Fallback: books and edited volumes without ISSN never appear in the
    # Serial Title API. If a DOI is provided, use the abstract retrieval
    # record's aggregationType and publisher so the caller still gets a
    # venue classification.
    fallback = None
    if not results and fallback_doi:
        try:
            rec = _fetch_abstract_record(fallback_doi, api_key, insttoken)
            fallback = {
                "title": rec.get("journal", ""),
                "venue_type": (rec.get("aggregation_type") or "unknown").lower(),
                "issn": rec.get("issn", ""),
                "isbn": "",
                "publisher": rec.get("publisher", ""),
                "sjr": "",
                "sjr_applicable": False,
                "cite_score": "",
                "subject_areas": [],
                "source": "abstract-retrieval-fallback",
            }
            results = [fallback]
        except SystemExit:
            fallback = {"source": "abstract-retrieval-fallback", "error": "lookup-failed"}

    print(json.dumps({
        "mode": "journal",
        "query": name,
        "results": results,
        "note": (
            "Covers journals, conference proceedings, book series and trade journals. "
            "SJR quartile rules apply only when `sjr_applicable: true`. "
            "Books and edited volumes without ISSN require --fallback-doi to be classified. "
            "Title lookups return sparse stubs on many venues (measured): pass --issn for "
            "populated metrics and a quartile."
        ),
    }, ensure_ascii=False, indent=2))


def _split_author_name(name: str) -> tuple[str, str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Split a person name into (surname, first initial) accepting BOTH the
        "Firstname Lastname" and the "Lastname, Firstname" conventions.

        Without the comma branch, "Otis, Martin" was read as surname="Martin",
        initial="O" (the last whitespace token was taken as the surname), which
        silently returned unrelated authors instead of an empty result. The
        comma is the reliable signal: everything before it is the surname.

    Inputs:
        name (str): person name in either convention, e.g. "Martin Otis",
                    "Otis, Martin", "Otis, Martin J.-D."

    Outputs:
        (surname, initial) (tuple[str, str]): initial is "" when the given name
                    is absent, in which case the caller must query on surname
                    alone.
    --------------------------------------------------------------------------
    """
    if "," in name:
        surname, _, given = name.partition(",")
        surname = surname.strip()
        given = given.strip()
        return surname, (given[0] if given else "")

    parts = name.split()
    if len(parts) >= 2:
        return parts[-1], parts[0][0]
    return name.strip(), ""


_AU_ID = re.compile(r"AU-ID\(\s*(\d{6,})\s*\)|^\s*(\d{8,})\s*$", re.IGNORECASE)
# Scopus caps a STANDARD-view search page at 25; count=100 answers HTTP 400.
_SEARCH_PAGE = 25


def extract_au_id(text: str) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Read an author identifier out of what the caller typed, accepting both
        `AU-ID(57210200087)` and the bare number. A name returns "".

    Inputs:
        text (str): the author argument.

    Outputs:
        au_id (str): the digits, or "" when the argument is a person name.
    --------------------------------------------------------------------------
    """
    found = _AU_ID.search(text or "")
    if not found:
        return ""
    return found.group(1) or found.group(2) or ""


def h_index(citation_counts: list[int]) -> int:
    """
    --------------------------------------------------------------------------
    Purpose:
        Compute the h-index from a list of per-paper citation counts: the
        largest h such that h papers have at least h citations each.

    Inputs:
        citation_counts (list[int]): citations per paper, any order.

    Outputs:
        h (int): the h-index over exactly the papers supplied. It is a lower
            bound when the list was truncated, which is why the caller pages
            until the index stops growing.
    --------------------------------------------------------------------------
    """
    ranked = sorted((c for c in citation_counts if c >= 0), reverse=True)
    h = 0
    for rank, citations in enumerate(ranked, start=1):
        if citations >= rank:
            h = rank
        else:
            break
    return h


def _is_authorization_error(resp: requests.Response) -> bool:
    """True when Scopus refused the VIEW rather than the key. MEASURED
    (2026-08-12): an API key entitled for Scopus Search answers 401
    AUTHORIZATION_ERROR on the Author Search API, the Author Retrieval API and
    any `view=COMPLETE` search. The key is valid; the product is not licensed,
    so telling the user to check SCOPUS_API_KEY sends them hunting for a fault
    that is not there."""
    if resp.status_code not in (401, 403):
        return False
    try:
        code = resp.json().get("service-error", {}).get("status", {}).get("statusCode", "")
    except ValueError:
        return False
    return code == "AUTHORIZATION_ERROR"


def _scopus_documents_by_au_id(au_id: str, api_key: str, insttoken: str | None,
                               max_pages: int = 8) -> tuple[list[dict], int]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Page an author's publications, most cited first, through the Scopus
        Search API — the endpoint this key IS entitled for. Paging stops as
        soon as the h-index can no longer grow, so a prolific author costs a
        handful of calls, not one per paper.

    Inputs:
        au_id (str): Scopus author identifier, digits only.
        api_key (str), insttoken (str | None): Scopus credentials.
        max_pages (int): hard ceiling on pages of 25, a runaway guard.

    Outputs:
        (documents, total) (tuple[list[dict], int]): the documents retrieved,
            and the author's total document count as Scopus reports it.
    --------------------------------------------------------------------------
    """
    documents: list[dict] = []
    total = 0
    for page in range(max_pages):
        params = {
            "query": f"AU-ID({au_id})",
            "count": _SEARCH_PAGE,
            "start": page * _SEARCH_PAGE,
            "sort": "-citedby-count",
            "field": ("dc:title,prism:publicationName,prism:coverDate,prism:doi,"
                      "citedby-count,prism:aggregationType,affiliation"),
        }
        resp = requests.get(SEARCH_URL, headers=_make_headers(api_key, insttoken),
                            params=params, timeout=30)
        _check_response(resp)
        data = resp.json().get("search-results", {})
        total = int(data.get("opensearch:totalResults", 0) or 0)
        entries = data.get("entry", [])
        if not entries:
            break
        for e in entries:
            affiliations = e.get("affiliation", [])
            if isinstance(affiliations, dict):
                affiliations = [affiliations]
            documents.append(_annotate_publisher({
                "title": e.get("dc:title", ""),
                "journal": e.get("prism:publicationName", ""),
                "year": (e.get("prism:coverDate") or "")[:4],
                "doi": e.get("prism:doi", ""),
                "citations": int(e.get("citedby-count", 0) or 0),
                "aggregation_type": e.get("prism:aggregationType", ""),
                "affiliations": [a.get("affilname", "") for a in affiliations if isinstance(a, dict)],
            }))
        if len(documents) >= total:
            break
        # Sorted by descending citations, so once the h-index is smaller than
        # what we hold, no later page can raise it.
        if h_index([d["citations"] for d in documents]) < len(documents):
            break
    return documents, total


def _author_profile_by_au_id(au_id: str, api_key: str, insttoken: str | None,
                             count: int) -> dict[str, Any]:
    """Build an author profile from the entitled Search API alone. The h-index
    is computed from the citation counts rather than read from a profile
    endpoint, and agrees with the published value on the reference case."""
    documents, total = _scopus_documents_by_au_id(au_id, api_key, insttoken)
    computed_h = h_index([d["citations"] for d in documents])
    by_date = sorted(documents, key=lambda d: d["year"], reverse=True)
    affiliation = ""
    for doc in by_date:
        if doc["affiliations"]:
            affiliation = doc["affiliations"][0]
            break
    return {
        "name": "",   # the entitled views carry no author-name block
        "affiliation": affiliation,
        "documents": total,
        "h_index": computed_h,
        "h_index_source": "computed from citation counts of "
                          f"{len(documents)} of {total} documents",
        "coauthors": None,   # needs the author block, which this key cannot read
        "author_id": au_id,
        "top_papers": [
            {k: d[k] for k in ("title", "year", "citations", "journal", "doi")}
            for d in documents[:count]
        ],
    }


def _author_candidates_from_s2(name: str, count: int) -> list[dict[str, Any]]:
    """Name-to-author resolution through Semantic Scholar, used only when the
    Scopus Author Search API is not licensed. S2 has no Scopus AU-ID, so this
    identifies the person and their metrics but cannot hand back the identifier
    the rest of the pipeline needs."""
    if s2 is None or not _S2_FALLBACK_ENABLED:
        return []
    try:
        payload = s2._request("/author/search", {
            "query": name,
            "fields": "name,affiliations,paperCount,citationCount,hIndex,url",
            "limit": max(count, 1),
        })
    except Exception as exc:  # never let the fallback raise over the primary failure
        print(f"WARN: Semantic Scholar author search failed: {exc}", file=sys.stderr)
        return []
    if not payload:
        return []
    return [
        {
            "name": a.get("name", ""),
            "affiliation": "; ".join(a.get("affiliations") or []),
            "documents": a.get("paperCount", ""),
            "h_index": a.get("hIndex", ""),
            "citations": a.get("citationCount", ""),
            "coauthors": None,
            "author_id": None,            # no Scopus AU-ID exists on this side
            "semantic_scholar_id": a.get("authorId", ""),
            "url": a.get("url", ""),
        }
        for a in payload.get("data", [])
    ]


def _author(name: str, api_key: str, insttoken: str | None, count: int = 5,
            au_id: str | None = None) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Author profile, by AU-ID when one is known and by name otherwise.

        Three paths, in order of authority. Given an AU-ID, the profile is
        built from the Scopus Search API, which every key is entitled for.
        Given a name, the Scopus Author Search API is tried first. When that
        API answers AUTHORIZATION_ERROR — the key is valid but the product is
        not licensed, MEASURED 2026-08-12 — the mode degrades to Semantic
        Scholar instead of dying, and says so in its own output.

    Inputs:
        name (str): person name, or an AU-ID in either accepted form.
        api_key (str), insttoken (str | None): Scopus credentials.
        count (int): number of candidates, and of top papers in a profile.
        au_id (str | None): explicit --au-id, which wins over the query.

    Outputs:
        result (None): JSON on stdout, always carrying `source` and, when the
            answer is degraded, a `note` naming what is missing and how to fix
            it. `results` keeps the historical shape, so a caller reading
            `author_id` and `h_index` is unaffected.
    --------------------------------------------------------------------------
    """
    resolved_au_id = (au_id or "").strip() or extract_au_id(name)
    if resolved_au_id:
        profile = _author_profile_by_au_id(resolved_au_id, api_key, insttoken, count)
        print(json.dumps({
            "mode": "author",
            "query": name,
            "scopus_query": f"AU-ID({resolved_au_id})",
            "source": "scopus-search-by-au-id",
            "results": [profile],
            "note": ("Profile built from the Scopus Search API. The h-index is computed from "
                     "the citation counts of the indexed documents; `name` and `coauthors` stay "
                     "empty because the author block needs the Author Retrieval API."),
        }, ensure_ascii=False, indent=2))
        return

    surname, initial = _split_author_name(name)
    if surname and initial:
        query = f"AUTHLASTNAME({surname}) AND AUTHFIRST({initial})"
    else:
        query = f"AUTHLASTNAME({surname or name})"

    params = {
        "query": query,
        "count": count,
        "field": "dc:identifier,preferred-name,affiliation-current,document-count,h-index,coauthor-count",
    }
    resp = requests.get(
        AUTHOR_SEARCH_URL, headers=_make_headers(api_key, insttoken), params=params, timeout=30
    )

    if _is_authorization_error(resp):
        candidates = _author_candidates_from_s2(name, count)
        print(json.dumps({
            "mode": "author",
            "query": name,
            "scopus_query": query,
            "source": "semantic-scholar-fallback",
            "scopus_author_api": "unlicensed",
            "results": candidates,
            "note": (
                "The Scopus Author Search API answered AUTHORIZATION_ERROR: this key is "
                "entitled for Scopus Search, not for the Author APIs, so no Scopus AU-ID can "
                "be resolved from a name. The candidates below come from Semantic Scholar and "
                "carry no `author_id`. To obtain a Scopus profile, either request the Author "
                "Search entitlement for the key at https://dev.elsevier.com, or read the AU-ID "
                "off the author's scopus.com profile page and rerun with "
                "`author \"AU-ID(<digits>)\"`, which uses the entitled Search API."
            ),
        }, ensure_ascii=False, indent=2))
        return

    _check_response(resp)

    entries = resp.json().get("search-results", {}).get("entry", [])
    results = []
    for e in entries:
        pn = e.get("preferred-name", {})
        aff = e.get("affiliation-current", {})
        results.append({
            "name": f"{pn.get('surname', '')}, {pn.get('given-name', '')}",
            "affiliation": aff.get("affiliation-name", "") if isinstance(aff, dict) else "",
            "documents": e.get("document-count", ""),
            "h_index": e.get("h-index", ""),
            "coauthors": e.get("coauthor-count", ""),
            "author_id": e.get("dc:identifier", "").replace("AUTHOR_ID:", ""),
        })
    # Echo the RESOLVED Scopus query, not just the raw input: when the name was parsed into the
    # wrong field the only visible symptom was a list of unrelated authors, which reads as "Scopus
    # cannot find this person" rather than "the query asked for the wrong surname".
    print(json.dumps({"mode": "author", "query": name, "scopus_query": query,
                      "source": "scopus-author-search", "results": results},
                     ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Scopus REST API client for Claude Code")
    parser.add_argument("mode", choices=["search", "cite", "validate", "verify", "author", "journal"])
    parser.add_argument("query", help="Search query, DOI, title fragment, or author name")
    parser.add_argument("--count", type=int, default=10, help="Max results (search mode only)")
    parser.add_argument("--year_min", type=int, default=None,
                        help="Minimum publication year filter (search mode only)")
    parser.add_argument("--sort", default=DEFAULT_SEARCH_SORT,
                        help="search mode: result ordering. Default 'cited' (-citedby-count) "
                             "because the Scopus default is by descending date, which never "
                             "surfaces a founding work. Use 'recent' (-coverDate) when you need "
                             "the most RECENT papers, 'relevancy', or 'none' to send no sort "
                             f"parameter at all. Accepted: {', '.join(SORT_CHOICES)}; aliases: "
                             f"{', '.join(SORT_ALIASES)}")
    parser.add_argument("--insttoken", default=None, help="Institution token for off-campus access")
    parser.add_argument("--expected-title", default=None, help="verify mode: expected title")
    parser.add_argument("--expected-authors", default=None,
                        help="verify mode: expected authors in BibTeX 'A and B and C' "
                             "or 'Surname, F.; Surname, G.' format")
    parser.add_argument("--expected-journal", default=None,
                        help="verify mode: expected journal, conference or proceedings name")
    parser.add_argument("--expected-volume", default=None, help="verify mode: expected volume")
    parser.add_argument("--expected-issue", default=None, help="verify mode: expected issue / number")
    parser.add_argument("--expected-pages", default=None, help="verify mode: expected page range")
    parser.add_argument("--expected-year", default=None, help="verify mode: expected publication year")
    parser.add_argument("--fallback-doi", default=None,
                        help="journal mode: DOI to use when the Serial Title API returns nothing "
                             "(books and edited volumes without ISSN)")
    parser.add_argument("--issn", default=None,
                        help="journal mode: look the venue up by ISSN instead of by title, and "
                             "return the CiteScore percentile and quartile. Accepts the raw "
                             "print+electronic pair from a cite record; each is tried in turn")
    parser.add_argument("--au-id", default=None,
                        help="author mode: profile this Scopus author identifier directly, "
                             "through the Search API. Use it when the key is not entitled for "
                             "the Author Search API, which cannot resolve a name to an AU-ID")
    parser.add_argument("--raw-query", action="store_true",
                        help="search mode: send the query verbatim instead of wrapping bare "
                             "keywords in TITLE-ABS-KEY(). Queries that already name a Scopus "
                             "field are never wrapped, so this is only needed to search every "
                             "indexed field on purpose")
    parser.add_argument("--enrich-authors", action="store_true",
                        help="search mode: backfill the full ordered author list per result "
                             "from Semantic Scholar (1 req/s per DOI)")
    parser.add_argument("--no-s2", action="store_true",
                        help="disable the Semantic Scholar fallback entirely (pure Scopus)")
    args = parser.parse_args()

    global _S2_FALLBACK_ENABLED
    if args.no_s2:
        _S2_FALLBACK_ENABLED = False

    args.sort = resolve_sort(args.sort)

    api_key = _get_api_key()

    dispatch = {
        "search": lambda: _search(args.query, args.count, api_key, args.insttoken,
                                   args.year_min, args.enrich_authors, args.sort,
                                   args.raw_query),
        "cite": lambda: _cite(args.query, api_key, args.insttoken),
        "validate": lambda: _validate(args.query, api_key, args.insttoken),
        "verify": lambda: _verify(
            args.query, api_key, args.insttoken,
            args.expected_title, args.expected_authors, args.expected_journal,
            args.expected_volume, args.expected_issue, args.expected_pages,
            args.expected_year,
        ),
        "author": lambda: _author(args.query, api_key, args.insttoken, args.count, args.au_id),
        "journal": lambda: _journal(args.query, api_key, args.insttoken, args.fallback_doi,
                                    args.issn),
    }
    dispatch[args.mode]()


if __name__ == "__main__":
    main()
