"""
scopus_api.py — Scopus REST API client for the Claude Code /scopus skill.

Usage:
  python scopus_api.py search "<query>" [--count N] [--year_min YYYY] [--insttoken TOKEN]
  python scopus_api.py cite "<DOI>"     [--insttoken TOKEN]
  python scopus_api.py validate "<DOI or title>" [--insttoken TOKEN]
  python scopus_api.py verify "<DOI or title>" \\
      [--expected-title "..."] [--expected-authors "Smith, J.; Doe, A."] \\
      [--expected-journal "..."] [--expected-volume "..."] \\
      [--expected-issue "..."] [--expected-pages "..."] \\
      [--expected-year "YYYY"] [--insttoken TOKEN]
  python scopus_api.py author "<name>"  [--insttoken TOKEN]
  python scopus_api.py journal "<journal name or ISSN>" [--insttoken TOKEN]

Output: JSON to stdout. Errors to stderr with actionable messages.

Requires: SCOPUS_API_KEY env var (set via Windows User environment variables).
          On-campus network or UQAC VPN (or --insttoken for off-campus access).
"""

import argparse
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

# Semantic Scholar fallback (same scripts/ directory). Used to backfill the
# full author list when Scopus returns only the first creator or an empty
# author block. Import is best-effort: if the sibling module is unavailable,
# enrichment is silently skipped and the pure-Scopus behaviour is preserved.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import semantic_scholar_api as s2
except ImportError:
    s2 = None

# Global toggle, flipped off by the --no-s2 CLI flag.
_S2_FALLBACK_ENABLED = True

SEARCH_URL = "https://api.elsevier.com/content/search/scopus"
ABSTRACT_URL = "https://api.elsevier.com/content/abstract/doi/{doi}"
AUTHOR_SEARCH_URL = "https://api.elsevier.com/content/search/author"
SERIAL_TITLE_URL = "https://api.elsevier.com/content/serial/title"


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
            year_min: int | None = None, enrich_authors: bool = False) -> None:
    full_query = query if year_min is None else f"({query}) AND PUBYEAR > {year_min - 1}"
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
    resp = requests.get(
        SEARCH_URL, headers=_make_headers(api_key, insttoken), params=params, timeout=30
    )
    _check_response(resp)

    entries = resp.json().get("search-results", {}).get("entry", [])
    results = [
        {
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
        }
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

    print(json.dumps({"mode": "search", "query": full_query, "count": len(results), "results": results}, ensure_ascii=False, indent=2))


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
    # Recover the full author list from Semantic Scholar if Scopus gave none.
    return _enrich_authors_from_semantic_scholar(record)


def _cite(doi: str, api_key: str, insttoken: str | None) -> None:
    record = _fetch_abstract_record(doi, api_key, insttoken)
    record["mode"] = "cite"
    print(json.dumps(record, ensure_ascii=False, indent=2))


def _validate(ref: str, api_key: str, insttoken: str | None) -> None:
    # DOI lookup takes priority
    if ref.startswith("10."):
        _cite(ref, api_key, insttoken)
        return

    params = {
        "query": f"TITLE({ref})",
        "count": 5,
        "field": "dc:title,dc:creator,prism:publicationName,prism:coverDate,prism:doi,citedby-count",
    }
    resp = requests.get(
        SEARCH_URL, headers=_make_headers(api_key, insttoken), params=params, timeout=30
    )
    _check_response(resp)

    data = resp.json().get("search-results", {})
    total = int(data.get("opensearch:totalResults", 0))
    entries = data.get("entry", [])
    results = [
        {
            "title": e.get("dc:title", ""),
            "authors": e.get("dc:creator", ""),
            "journal": e.get("prism:publicationName", ""),
            "year": (e.get("prism:coverDate") or "")[:4],
            "doi": e.get("prism:doi", ""),
            "citations": e.get("citedby-count", "0"),
        }
        for e in entries
    ]
    print(json.dumps({
        "mode": "validate",
        "query": ref,
        "total_found": total,
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


def _journal(name: str, api_key: str, insttoken: str | None, fallback_doi: str | None = None) -> None:
    """
    Venue lookup. The Scopus Serial Title API covers journals, conference
    proceedings, book series and trade journals — any venue with an ISSN.
    For one-off books and edited volumes (no ISSN) the API returns nothing;
    in that case, if --fallback-doi is provided, fall back to the abstract
    retrieval API to surface the venue type and publisher.

    Output exposes `venue_type` (journal / conference proceeding / book series /
    book / trade journal / unknown) so the caller can decide whether SJR
    quartile rules apply (journals and conference proceedings) or not (books).
    """
    params = {
        "title": name,
        "field": "Title,ISSN,SJRList,CiteScoreYearInfoList,SubjectArea,"
                 "Publisher,SNIPList,prism:aggregationType,prism:isbn",
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

        agg = (e.get("prism:aggregationType") or "").strip().lower()
        venue_type = agg if agg else "unknown"
        sjr_applicable = venue_type in ("journal", "conference proceeding", "trade journal")

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
            "Books and edited volumes without ISSN require --fallback-doi to be classified."
        ),
    }, ensure_ascii=False, indent=2))


def _author(name: str, api_key: str, insttoken: str | None) -> None:
    parts = name.split()
    if len(parts) >= 2:
        query = f"AUTHLASTNAME({parts[-1]}) AND AUTHFIRST({parts[0][0]})"
    else:
        query = f"AUTHLASTNAME({name})"

    params = {
        "query": query,
        "count": 5,
        "field": "dc:identifier,preferred-name,affiliation-current,document-count,h-index,coauthor-count",
    }
    resp = requests.get(
        AUTHOR_SEARCH_URL, headers=_make_headers(api_key, insttoken), params=params, timeout=30
    )
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
    print(json.dumps({"mode": "author", "query": name, "results": results}, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Scopus REST API client for Claude Code")
    parser.add_argument("mode", choices=["search", "cite", "validate", "verify", "author", "journal"])
    parser.add_argument("query", help="Search query, DOI, title fragment, or author name")
    parser.add_argument("--count", type=int, default=10, help="Max results (search mode only)")
    parser.add_argument("--year_min", type=int, default=None,
                        help="Minimum publication year filter (search mode only)")
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
    parser.add_argument("--enrich-authors", action="store_true",
                        help="search mode: backfill the full ordered author list per result "
                             "from Semantic Scholar (1 req/s per DOI)")
    parser.add_argument("--no-s2", action="store_true",
                        help="disable the Semantic Scholar fallback entirely (pure Scopus)")
    args = parser.parse_args()

    global _S2_FALLBACK_ENABLED
    if args.no_s2:
        _S2_FALLBACK_ENABLED = False

    api_key = _get_api_key()

    dispatch = {
        "search": lambda: _search(args.query, args.count, api_key, args.insttoken,
                                   args.year_min, args.enrich_authors),
        "cite": lambda: _cite(args.query, api_key, args.insttoken),
        "validate": lambda: _validate(args.query, api_key, args.insttoken),
        "verify": lambda: _verify(
            args.query, api_key, args.insttoken,
            args.expected_title, args.expected_authors, args.expected_journal,
            args.expected_volume, args.expected_issue, args.expected_pages,
            args.expected_year,
        ),
        "author": lambda: _author(args.query, api_key, args.insttoken),
        "journal": lambda: _journal(args.query, api_key, args.insttoken, args.fallback_doi),
    }
    dispatch[args.mode]()


if __name__ == "__main__":
    main()
