"""
semantic_scholar_api.py — Semantic Scholar Academic Graph client for the /scopus skill.

Role:
    Fallback metadata source. Scopus search results expose only the first
    creator (`dc:creator`), and some Scopus abstract records return an empty
    author block. When that happens, scopus_api.py calls this module to
    resolve the paper by DOI on Semantic Scholar and recover the missing
    fields (primarily the full, ordered author list).

Rate limit:
    Semantic Scholar allows 1 request per second, cumulative across ALL
    endpoints. `_throttle()` enforces a >= 1.05 s gap between every outgoing
    request from this process. Do not bypass it.

API key:
    Read from the environment variable 'S2_API_KEY', falling back to
    'SEMANTIC_SCHOLAR_API_KEY'.
    Sent in the 'x-api-key' header. Without a key the shared public pool is
    used, which is throttled far more aggressively than 1 req/s.

Design note — non-fatal:
    Unlike scopus_api.py, this client NEVER calls sys.exit on an API error.
    It is a best-effort enrichment layer; on failure it logs to stderr and
    returns None so the caller keeps the Scopus data it already has.

Usage (standalone, for testing):
    python semantic_scholar_api.py authors "10.1109/TRO.2020.1234567"
    python semantic_scholar_api.py paper   "10.1109/TRO.2020.1234567"

References:
    API docs : https://api.semanticscholar.org/api-docs/graph
    Tutorial : https://www.semanticscholar.org/product/api/tutorial
    Examples : https://github.com/allenai/s2-folks
"""

import argparse
import json
import os
import sys
import time
from typing import Any

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)

BASE_URL = "https://api.semanticscholar.org/graph/v1"
PAPER_PATH = "/paper/DOI:{doi}"
MATCH_PATH = "/paper/search/match"

# Default fields pulled for a general paper lookup. `authors` returns an
# ordered list of {authorId, name}; the order matches the publication's
# author order, which is what reference auditing needs.
DEFAULT_PAPER_FIELDS = "title,abstract,year,venue,externalIds,authors"

# Minimum spacing between requests. The documented limit is 1 req/s; the
# 0.05 s margin absorbs clock jitter so we never trip the 429 threshold.
_MIN_INTERVAL_S = 1.05
_last_request_ts = 0.0

# Lowercase surname particles kept attached to the family name when splitting
# a Semantic Scholar full-name string (S2 returns names as a single field).
_NAME_PARTICLES = {
    "van", "von", "der", "den", "de", "del", "di", "da", "dos", "das",
    "la", "le", "du", "bin", "al", "ibn", "st", "san", "santa",
}


def _get_api_key() -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve the Semantic Scholar API key from the environment.

    Inputs:
        none

    Outputs:
        key (str | None): the key string, or None when no variant is set
        (the public pool is then used).
    --------------------------------------------------------------------------
    """
    for name in ("S2_API_KEY", "SEMANTIC_SCHOLAR_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def _throttle() -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Block until at least _MIN_INTERVAL_S has elapsed since the previous
        request, satisfying the 1 request/second cumulative limit.

    Inputs:
        none

    Outputs:
        none (sleeps as a side effect; updates the module-level timestamp)
    --------------------------------------------------------------------------
    """
    global _last_request_ts
    elapsed = time.monotonic() - _last_request_ts
    wait = _MIN_INTERVAL_S - elapsed
    if wait > 0:
        time.sleep(wait)
    _last_request_ts = time.monotonic()


def _request(path: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Perform a throttled GET against the Academic Graph API. Retries once
        on 429 after backing off; treats 404 as "not found" (None).

    Inputs:
        path (str): API path beginning with '/'
        params (dict): query string parameters

    Outputs:
        body (dict | None): parsed JSON on 200, or None on 404 / error.
        All errors are logged to stderr; this function never raises to the
        caller and never exits the process.
    --------------------------------------------------------------------------
    """
    key = _get_api_key()
    headers = {"Accept": "application/json"}
    if key:
        headers["x-api-key"] = key
    url = f"{BASE_URL}{path}"

    try:
        _throttle()
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 429:
            # One backoff-and-retry; the throttle already spaces requests, so
            # a 429 here means a transient shared-pool spike.
            time.sleep(2.0)
            _throttle()
            resp = requests.get(url, headers=headers, params=params, timeout=30)
    except requests.RequestException as exc:
        print(f"WARN [semantic_scholar]: network error for {url}: {exc}", file=sys.stderr)
        return None

    if resp.status_code == 404:
        return None
    if resp.status_code == 403:
        print("WARN [semantic_scholar]: 403 Forbidden — check the S2 API key.", file=sys.stderr)
        return None
    if resp.status_code != 200:
        print(f"WARN [semantic_scholar]: HTTP {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
        return None

    try:
        return resp.json()
    except ValueError:
        print("WARN [semantic_scholar]: response was not valid JSON.", file=sys.stderr)
        return None


def _split_name(full_name: str) -> dict[str, str]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Split a Semantic Scholar full-name string into the same structured
        shape scopus_api.py produces, so the two author lists are comparable.
        Lowercase particles (van, de, della, ...) stay attached to the
        surname.

    Inputs:
        full_name (str): e.g. "John A. Smith", "Ludwig van Beethoven"

    Outputs:
        author (dict): {surname, given_name, initials, display}
    --------------------------------------------------------------------------
    """
    full_name = (full_name or "").strip()
    if not full_name:
        return {"surname": "", "given_name": "", "initials": "", "display": ""}

    tokens = full_name.split()
    if len(tokens) == 1:
        surname, given = tokens[0], ""
    else:
        idx = len(tokens) - 1
        surname_tokens = [tokens[idx]]
        while idx - 1 >= 1 and tokens[idx - 1].lower().strip(".") in _NAME_PARTICLES:
            idx -= 1
            surname_tokens.insert(0, tokens[idx])
        surname = " ".join(surname_tokens)
        given = " ".join(tokens[:idx])

    initials = "".join(f"{tok[0]}." for tok in given.split() if tok)
    display = f"{surname}, {given}".strip(", ").strip()
    return {"surname": surname, "given_name": given, "initials": initials, "display": display}


def paper_for_doi(doi: str, fields: str = DEFAULT_PAPER_FIELDS) -> dict[str, Any] | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Fetch a paper record from Semantic Scholar by DOI.

    Inputs:
        doi (str): the DOI, with or without a leading "https://doi.org/"
        fields (str): comma-separated Academic Graph field list

    Outputs:
        record (dict | None): the raw S2 paper object, or None if not found.
    --------------------------------------------------------------------------
    """
    doi = (doi or "").strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "DOI:"):
        if doi.lower().startswith(prefix.lower()):
            doi = doi[len(prefix):]
            break
    if not doi:
        return None
    return _request(PAPER_PATH.format(doi=doi), {"fields": fields})


def authors_for_doi(doi: str) -> list[dict[str, str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return the full, ordered author list for a DOI in the structured
        scopus_api.py shape. This is the primary backfill entry point used
        when Scopus omits authors.

    Inputs:
        doi (str): the paper DOI

    Outputs:
        authors (list[dict]): each {surname, given_name, initials, display},
        in publication order. Empty list when the paper or its authors are
        not available on Semantic Scholar.
    --------------------------------------------------------------------------
    """
    record = paper_for_doi(doi, fields="authors")
    if not record:
        return []
    raw_authors = record.get("authors") or []
    return [_split_name(a.get("name", "")) for a in raw_authors if a.get("name")]


def external_ids_for_doi(doi: str) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return the Semantic Scholar externalIds map for a DOI (ArXiv,
        PubMedCentral, PubMed, DOI, etc.). download_pdf.py uses it to route the
        arXiv and PMC open-access full-text tiers without re-querying raw JSON.

    Inputs:
        doi (str): the paper DOI, with or without a leading "https://doi.org/"

    Outputs:
        ids (dict): the externalIds object, or an empty dict when S2 has no
        record for the DOI. Never raises; never exits the process.
    --------------------------------------------------------------------------
    """
    record = paper_for_doi(doi, fields="externalIds")
    if not record:
        return {}
    return record.get("externalIds") or {}


def oa_pdf_for_doi(doi: str) -> str | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return the open-access PDF URL Semantic Scholar holds for a DOI, if any.
        This is the fallback PDF source used by download_pdf.py when Scopus /
        Elsevier cannot deliver the full text.

    Inputs:
        doi (str): the paper DOI, with or without a leading "https://doi.org/"

    Outputs:
        url (str | None): the openAccessPdf URL, or None when S2 has no record
        for the DOI or the record carries no open-access PDF.
    --------------------------------------------------------------------------
    """
    record = paper_for_doi(doi, fields="openAccessPdf")
    if not record:
        return None
    oa = record.get("openAccessPdf") or {}
    url = (oa.get("url") or "").strip()
    return url or None


# Fields needed to assemble a complete IEEE-style reference from a title match.
FULL_REFERENCE_FIELDS = (
    "title,authors,year,venue,publicationVenue,externalIds,journal,publicationTypes"
)


def match_title(title: str, fields: str = FULL_REFERENCE_FIELDS) -> dict[str, Any] | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve a paper from its title using the Academic Graph
        /paper/search/match endpoint, which returns the single closest title
        match (not a candidate list). Used when no DOI is available.

    Inputs:
        title (str): full or near-full paper title
        fields (str): comma-separated Academic Graph field list

    Outputs:
        record (dict | None): the best-matching paper object, or None when S2
        finds no match. The match must be checked against the queried title by
        the caller before trusting it in an audit context.
    --------------------------------------------------------------------------
    """
    title = (title or "").strip()
    if not title:
        return None
    body = _request(MATCH_PATH, {"query": title, "fields": fields})
    if not body:
        return None
    data = body.get("data") or []
    return data[0] if data else None


def structured_authors(record: dict[str, Any]) -> list[dict[str, str]]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Convert the raw S2 authors array of any paper record into the
        structured {surname, given_name, initials, display} shape.

    Inputs:
        record (dict): an S2 paper object carrying an 'authors' list

    Outputs:
        authors (list[dict]): structured, in publication order.
    --------------------------------------------------------------------------
    """
    raw = record.get("authors") or []
    return [_split_name(a.get("name", "")) for a in raw if a.get("name")]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Semantic Scholar Academic Graph client (fallback for the /scopus skill)"
    )
    parser.add_argument("mode", choices=["authors", "paper", "match", "oa"])
    parser.add_argument("query", help="DOI (authors/paper/oa mode) or title (match mode)")
    args = parser.parse_args()

    if args.mode == "authors":
        result = {"mode": "authors", "doi": args.query, "authors": authors_for_doi(args.query)}
    elif args.mode == "match":
        result = {"mode": "match", "title": args.query, "record": match_title(args.query)}
    elif args.mode == "oa":
        result = {"mode": "oa", "doi": args.query, "pdf_url": oa_pdf_for_doi(args.query)}
    else:
        result = {"mode": "paper", "doi": args.query, "record": paper_for_doi(args.query)}

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
