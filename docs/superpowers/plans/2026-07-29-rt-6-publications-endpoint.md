# RT-6: Publications Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose one author's validated Scopus publications through the form service as a cached, rate-limited endpoint, so ThesisTracker can build a cohort report without ever holding the Scopus key or bypassing the approved-publisher policy.

**Architecture:** `scopus_api.py` gains one public function and one CLI mode, `publications`, that resolves an author name to a Scopus author identifier and then retrieves that author's documents. The service adds `app/publications.py`: an on-disk TTL cache keyed by the query, a token-bucket rate limiter sized for the Elsevier quota, and the approved-publisher classification, all behind `GET /publications`. The key, the throttling, and the publisher policy stay in ResearchTools; ThesisTracker sees a plain JSON list with a per-entry `approved_publisher` flag and never talks to Elsevier.

**Tech Stack:** Python 3.13, `requests`, FastAPI, standard library. No new dependency.

## Global Constraints

- Definition files (agents, skills, commands) are **English-only**.
- Style hygiene in any produced text: no em dash, no double or triple dash, straight quotes only, no zero-width or Unicode-tag characters, no single-character ellipsis, no leftover `*` or `#`.
- Python naming and type hints per `.claude/rules/code-style.md`; docstrings in the repo's extended `Purpose: / Inputs: / Outputs:` format.
- Logging: `logging.getLogger(__name__)`, prefixes `[SCOPUS]` in the skill and `[FORM-SERVICE]` in the service. **Never log the API key**, never log a full record body.
- **Never fabricate a reference or a DOI.** Every entry returned comes from Scopus with its own DOI, or the DOI field is empty. Nothing is synthesized to fill a gap.
- **Approved publishers:** IEEE, Springer, Elsevier, Taylor & Francis, Cambridge, Wiley, IET, IOP, ACM, MDPI, ASME, ACME, BioMed Central. Anything else is flagged, not dropped: the professor decides relevance, and a silent drop would hide a real publication.
- The Scopus key is read from `SCOPUS_API_KEY` or `.claude/skills/scopus/.scopus_key` (gitignored) exactly as today. It never crosses the service boundary and never appears in a response.
- Scopus access needs a campus network or an active VPN unless an institutional token is supplied. The endpoint degrades to `503` with an actionable message rather than an empty list, because an empty list reads as "this person has no publications".
- Offline tests only: `requests.get` and the clock are patched.
- Dependencies pinned exactly; `pip-audit -r ... --strict` on both requirements files.

**Depends on:** RT-5 (`feat/uqac-forms-service`).

---

## File Structure

**New files**

- `deploy/form-service/app/publications.py` - cache, rate limiter, publisher classification, the service-side entry point.
- `deploy/form-service/tests/test_publications.py` - offline unit tests.
- `.claude/skills/scopus/scripts/Test/test_author_documents.py` - offline unit tests for the new skill function.

**Modified files**

- `.claude/skills/scopus/scripts/scopus_api.py` - `author_documents()` plus the `publications` CLI mode.
- `deploy/form-service/app/main.py` - the `GET /publications` route.
- `deploy/form-service/app/config.py` - the publications settings.
- `deploy/form-service/README.md` - the endpoint row.
- `README.md`, `Architecture.md` - `scopus_api.py` now has seven modes.
- `.claude/skills/scopus/SKILL.md` - the new mode.
- `.claude/rules/testing.md` - the two new offline test commands.

---

## Interfaces consumed

From RT-5: `Settings`, `load_settings`, `require_service_key`, and the FastAPI application object `app`.

From the existing `scopus_api.py`: `_get_api_key()`, `_make_headers(api_key, insttoken)`, `_check_response(response)`, and the module-level Elsevier URL constants. The existing six modes (`search`, `cite`, `validate`, `verify`, `author`, `journal`) are not modified.

---

## Task 1: `author_documents` in the scopus skill

**Files:**

- Modify: `.claude/skills/scopus/scripts/scopus_api.py`
- Test: `.claude/skills/scopus/scripts/Test/test_author_documents.py`

**Interfaces:**

- Consumes: the existing private helpers of `scopus_api.py`.
- Produces:
  - `APPROVED_PUBLISHERS: tuple[str, ...]` module constant.
  - `is_approved_publisher(publisher_or_venue: str) -> bool`.
  - `author_documents(name: str, count: int = 10, api_key: str | None = None, insttoken: str | None = None, author_id: str | None = None) -> dict[str, Any]` returning
    `{"query": str, "author": {"author_id", "name", "affiliation", "h_index", "documents"}, "publications": [ {...} ], "fetched_at": str}`.
    Each publication is `{"title", "venue", "year", "doi", "doi_url", "type", "citations", "approved_publisher"}`. `doi_url` is `https://doi.org/<doi>` or `""`.
  - CLI mode `publications`: `python scopus_api.py publications "Martin Otis" --count 10`.

- [ ] **Step 1: Write the failing test**

Create `.claude/skills/scopus/scripts/Test/test_author_documents.py`:

```python
"""
test_author_documents.py - Offline unit tests for scopus_api.author_documents.

No network and no API key: requests.get is patched and the key is injected.
Run with the project Python:
    python .claude/skills/scopus/scripts/Test/test_author_documents.py
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scopus_api  # noqa: E402


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status
        self.text = json.dumps(payload)
        self.headers = {"Content-Type": "application/json"}

    def json(self) -> dict:
        return self._payload


AUTHOR_PAYLOAD = {
    "search-results": {"entry": [{
        "dc:identifier": "AUTHOR_ID:7004212771",
        "preferred-name": {"surname": "Otis", "given-name": "Martin J.-D."},
        "affiliation-current": {"affiliation-name": "Universite du Quebec a Chicoutimi"},
        "document-count": "120", "h-index": "20",
    }]}
}

DOCS_PAYLOAD = {
    "search-results": {"entry": [
        {"dc:title": "Adaptive control of a cable driven robot",
         "prism:publicationName": "IEEE Transactions on Robotics",
         "prism:coverDate": "2025-04-01", "prism:doi": "10.1109/TRO.2025.000001",
         "subtypeDescription": "Article", "citedby-count": "7"},
        {"dc:title": "A predatory-sounding venue paper",
         "prism:publicationName": "Journal of Universal Everything",
         "prism:coverDate": "2024-01-01", "prism:doi": "10.9999/jue.2024.1",
         "subtypeDescription": "Article", "citedby-count": "0"},
        {"dc:title": "Preprint with no DOI",
         "prism:publicationName": "Springer Lecture Notes in Computer Science",
         "prism:coverDate": "2023-06-01",
         "subtypeDescription": "Conference Paper", "citedby-count": "3"},
    ]}
}


class TestApprovedPublisher(unittest.TestCase):
    def test_an_approved_venue_is_recognized(self) -> None:
        self.assertTrue(scopus_api.is_approved_publisher("IEEE Transactions on Robotics"))
        self.assertTrue(scopus_api.is_approved_publisher("Springer Lecture Notes in Computer Science"))
        self.assertTrue(scopus_api.is_approved_publisher("Elsevier Applied Soft Computing"))

    def test_an_unlisted_venue_is_flagged_not_dropped(self) -> None:
        self.assertFalse(scopus_api.is_approved_publisher("Journal of Universal Everything"))

    def test_an_empty_venue_is_not_approved(self) -> None:
        self.assertFalse(scopus_api.is_approved_publisher(""))


class TestAuthorDocuments(unittest.TestCase):
    def setUp(self) -> None:
        self._real_get = scopus_api.requests.get
        self.calls: list = []

        def fake_get(url, **kwargs):
            self.calls.append((url, kwargs.get("params", {})))
            return _FakeResponse(AUTHOR_PAYLOAD if "author" in url.lower() else DOCS_PAYLOAD)

        scopus_api.requests.get = fake_get

    def tearDown(self) -> None:
        scopus_api.requests.get = self._real_get

    def test_it_resolves_the_author_then_queries_the_documents(self) -> None:
        result = scopus_api.author_documents("Martin Otis", count=10, api_key="fake")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(result["author"]["author_id"], "7004212771")

    def test_the_document_query_is_scoped_to_the_resolved_author_id(self) -> None:
        scopus_api.author_documents("Martin Otis", count=10, api_key="fake")
        _url, params = self.calls[1]
        self.assertIn("AU-ID(7004212771)", params["query"])

    def test_a_known_author_id_skips_the_resolution_call(self) -> None:
        scopus_api.author_documents("Martin Otis", api_key="fake", author_id="7004212771")
        self.assertEqual(len(self.calls), 1)

    def test_every_publication_carries_its_own_doi_never_a_synthesized_one(self) -> None:
        pubs = scopus_api.author_documents("Martin Otis", api_key="fake")["publications"]
        self.assertEqual(pubs[0]["doi"], "10.1109/TRO.2025.000001")
        self.assertEqual(pubs[0]["doi_url"], "https://doi.org/10.1109/TRO.2025.000001")
        # No DOI in the record means an empty string, never an invented one.
        self.assertEqual(pubs[2]["doi"], "")
        self.assertEqual(pubs[2]["doi_url"], "")

    def test_an_unapproved_venue_is_flagged_and_still_returned(self) -> None:
        pubs = scopus_api.author_documents("Martin Otis", api_key="fake")["publications"]
        self.assertEqual(len(pubs), 3)
        flags = {p["title"]: p["approved_publisher"] for p in pubs}
        self.assertTrue(flags["Adaptive control of a cable driven robot"])
        self.assertFalse(flags["A predatory-sounding venue paper"])

    def test_the_year_comes_from_the_cover_date(self) -> None:
        pubs = scopus_api.author_documents("Martin Otis", api_key="fake")["publications"]
        self.assertEqual(pubs[0]["year"], "2025")

    def test_the_api_key_never_appears_in_the_result(self) -> None:
        result = scopus_api.author_documents("Martin Otis", api_key="super-secret-key")
        self.assertNotIn("super-secret-key", json.dumps(result))

    def test_an_unresolvable_author_raises_with_the_name(self) -> None:
        scopus_api.requests.get = lambda url, **kwargs: _FakeResponse(
            {"search-results": {"entry": []}})
        with self.assertRaises(ValueError) as ctx:
            scopus_api.author_documents("Personne Inexistante", api_key="fake")
        self.assertIn("Personne Inexistante", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python .claude/skills/scopus/scripts/Test/test_author_documents.py`
Expected: FAIL with `AttributeError: module 'scopus_api' has no attribute 'is_approved_publisher'`.

- [ ] **Step 3: Write the minimal implementation**

Add to `.claude/skills/scopus/scripts/scopus_api.py`, after the existing `_author` function:

```python
# The approved-publisher list from .claude/CLAUDE.md. A venue outside it is
# FLAGGED, never dropped: the professor decides relevance, and a silent drop
# would hide a real publication from a cohort report.
APPROVED_PUBLISHERS = (
    "ieee", "springer", "elsevier", "taylor", "francis", "cambridge", "wiley",
    "iet ", "institution of engineering", "iop ", "institute of physics", "acm",
    "mdpi", "asme", "acme", "biomed central", "bmc",
)


def is_approved_publisher(publisher_or_venue: str) -> bool:
    """
    --------------------------------------------------------------------------
    Purpose:
        Decide whether a venue or publisher string belongs to the approved list.
        Matching is a lowercase substring test on the venue name, because Scopus
        returns the publication name rather than the publisher for most records.

    Inputs:
        publisher_or_venue (str): the venue or publisher name

    Outputs:
        approved (bool): True when the name matches an approved publisher
    --------------------------------------------------------------------------
    """
    text = (publisher_or_venue or "").lower()
    if not text:
        return False
    return any(marker in text for marker in APPROVED_PUBLISHERS)


def _resolve_author_id(name: str, api_key: str, insttoken: str | None) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Resolve an author name to one Scopus author record, reusing the same
        query shape as the existing `author` mode.

    Inputs:
        name (str): the author's name, "Given Family" or a single family name
        api_key (str): Scopus API key
        insttoken (str | None): institutional token for off-campus access

    Outputs:
        author (dict): {author_id, name, affiliation, h_index, documents}

    Raises:
        ValueError naming the query when Scopus returns no author.
    --------------------------------------------------------------------------
    """
    parts = name.split()
    query = (f"AUTHLASTNAME({parts[-1]}) AND AUTHFIRST({parts[0][0]})"
             if len(parts) >= 2 else f"AUTHLASTNAME({name})")
    response = requests.get(
        AUTHOR_SEARCH_URL, headers=_make_headers(api_key, insttoken),
        params={"query": query, "count": 1,
                "field": "dc:identifier,preferred-name,affiliation-current,"
                         "document-count,h-index"},
        timeout=30)
    _check_response(response)
    entries = response.json().get("search-results", {}).get("entry", [])
    if not entries or not entries[0].get("dc:identifier"):
        raise ValueError(f"no Scopus author found for {name!r}")

    entry = entries[0]
    preferred = entry.get("preferred-name", {})
    affiliation = entry.get("affiliation-current", {})
    return {
        "author_id": str(entry.get("dc:identifier", "")).replace("AUTHOR_ID:", ""),
        "name": f"{preferred.get('surname', '')}, {preferred.get('given-name', '')}".strip(", "),
        "affiliation": (affiliation.get("affiliation-name", "")
                        if isinstance(affiliation, dict) else ""),
        "h_index": entry.get("h-index", ""),
        "documents": entry.get("document-count", ""),
    }


def author_documents(name: str, count: int = 10, api_key: str | None = None,
                     insttoken: str | None = None,
                     author_id: str | None = None) -> dict[str, Any]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Retrieve one author's most recent Scopus documents, each carrying its
        own DOI and a flag saying whether its venue belongs to the approved
        publisher list. Nothing is synthesized: a record with no DOI in Scopus
        comes back with an empty DOI.

    Inputs:
        name (str): the author's name
        count (int): how many documents to return, most recent first
        api_key (str | None): Scopus key, read from the environment when None
        insttoken (str | None): institutional token for off-campus access
        author_id (str | None): skip the resolution call when already known

    Outputs:
        result (dict): {query, author, publications, fetched_at}

    Raises:
        ValueError when the author cannot be resolved.
    --------------------------------------------------------------------------
    """
    import datetime

    key = api_key or _get_api_key()
    author = ({"author_id": author_id, "name": name, "affiliation": "",
               "h_index": "", "documents": ""}
              if author_id else _resolve_author_id(name, key, insttoken))

    response = requests.get(
        SEARCH_URL, headers=_make_headers(key, insttoken),
        params={"query": f"AU-ID({author['author_id']})", "count": count,
                "sort": "-coverDate",
                "field": "dc:title,prism:publicationName,prism:coverDate,prism:doi,"
                         "subtypeDescription,citedby-count"},
        timeout=30)
    _check_response(response)

    publications: list[dict[str, Any]] = []
    for entry in response.json().get("search-results", {}).get("entry", []):
        doi = str(entry.get("prism:doi", "") or "")
        venue = str(entry.get("prism:publicationName", "") or "")
        publications.append({
            "title": str(entry.get("dc:title", "") or ""),
            "venue": venue,
            "year": str(entry.get("prism:coverDate", "") or "")[:4],
            "doi": doi,
            "doi_url": f"https://doi.org/{doi}" if doi else "",
            "type": str(entry.get("subtypeDescription", "") or ""),
            "citations": str(entry.get("citedby-count", "") or ""),
            "approved_publisher": is_approved_publisher(venue),
        })

    logger.info("[SCOPUS] %d document(s) for author %s", len(publications),
                author["author_id"])
    return {
        "query": name,
        "author": author,
        "publications": publications,
        "fetched_at": datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0).isoformat(),
    }
```

If `SEARCH_URL` or `AUTHOR_SEARCH_URL` is named differently in the file, use the existing constant names rather than introducing new ones, and if `logger` is not already defined at module level, use the existing logging idiom of the file.

- [ ] **Step 4: Add the CLI mode**

In `main()` of `scopus_api.py`, extend the mode choices:

```python
    parser.add_argument("mode", choices=["search", "cite", "validate", "verify",
                                         "author", "journal", "publications"])
```

and add the dispatch branch next to the existing ones:

```python
    if args.mode == "publications":
        print(json.dumps(
            author_documents(args.query, count=args.count, insttoken=args.insttoken),
            ensure_ascii=False, indent=2))
        return
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python .claude/skills/scopus/scripts/Test/test_author_documents.py`
Expected: PASS, 11 tests.

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/scopus/scripts/scopus_api.py \
        .claude/skills/scopus/scripts/Test/test_author_documents.py
git commit -m "feat(scopus): author_documents and the publications CLI mode"
```

---

## Task 2: Cache and rate limiter

**Files:**

- Create: `deploy/form-service/app/publications.py`
- Modify: `deploy/form-service/app/config.py`
- Test: `deploy/form-service/tests/test_publications.py`

**Interfaces:**

- Consumes: `Settings` from RT-5.
- Produces:
  - `Settings` gains `publications_cache_dir: str`, `publications_ttl_s: int` (default 86400), `publications_rate_per_minute: int` (default 20), `scopus_available: bool` derived from whether a key is reachable.
  - `class TokenBucket` with `TokenBucket(capacity: int, refill_per_minute: int, now: Callable[[], float] = time.monotonic)` and `take() -> bool`.
  - `cache_key(author: str, count: int) -> str` (SHA-256 hex of the normalized query).
  - `read_cache(key: str, settings: Settings, now: float | None = None) -> dict | None` returning `None` on a miss or an expired entry.
  - `write_cache(key: str, payload: dict, settings: Settings) -> None`.

- [ ] **Step 1: Write the failing test**

Create `deploy/form-service/tests/test_publications.py`:

```python
"""
test_publications.py - Offline unit tests for the publications endpoint.

No network and no Scopus key: the skill call is patched and the clock is
injected. Run with the project Python from the repo root:
    python deploy/form-service/tests/test_publications.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import config, publications  # noqa: E402

VALID_KEY = "k" * 48

PAYLOAD = {
    "query": "Martin Otis",
    "author": {"author_id": "7004212771", "name": "Otis, Martin J.-D.",
               "affiliation": "UQAC", "h_index": "20", "documents": "120"},
    "publications": [{"title": "Adaptive control", "venue": "IEEE Transactions on Robotics",
                      "year": "2025", "doi": "10.1109/TRO.2025.000001",
                      "doi_url": "https://doi.org/10.1109/TRO.2025.000001",
                      "type": "Article", "citations": "7", "approved_publisher": True}],
    "fetched_at": "2026-07-29T12:00:00+00:00",
}


class TestTokenBucket(unittest.TestCase):
    def test_it_allows_up_to_capacity_then_refuses(self) -> None:
        clock = [0.0]
        bucket = publications.TokenBucket(capacity=3, refill_per_minute=60,
                                          now=lambda: clock[0])
        self.assertTrue(all(bucket.take() for _ in range(3)))
        self.assertFalse(bucket.take())

    def test_it_refills_over_time(self) -> None:
        clock = [0.0]
        bucket = publications.TokenBucket(capacity=2, refill_per_minute=60,
                                          now=lambda: clock[0])
        bucket.take()
        bucket.take()
        self.assertFalse(bucket.take())
        clock[0] = 61.0  # one minute later: fully refilled
        self.assertTrue(bucket.take())

    def test_it_never_exceeds_capacity_after_a_long_idle(self) -> None:
        clock = [0.0]
        bucket = publications.TokenBucket(capacity=2, refill_per_minute=60,
                                          now=lambda: clock[0])
        clock[0] = 100000.0
        self.assertTrue(bucket.take())
        self.assertTrue(bucket.take())
        self.assertFalse(bucket.take())


class TestCache(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = config.load_settings({
            "FORM_SERVICE_KEY": VALID_KEY,
            "FORM_SERVICE_PUBLICATIONS_CACHE_DIR": os.path.join(self.tmp.name, "pub"),
            "FORM_SERVICE_PUBLICATIONS_TTL_S": "100",
        })

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_a_miss_returns_none(self) -> None:
        key = publications.cache_key("Martin Otis", 10)
        self.assertIsNone(publications.read_cache(key, self.settings))

    def test_a_write_then_read_round_trips(self) -> None:
        key = publications.cache_key("Martin Otis", 10)
        publications.write_cache(key, PAYLOAD, self.settings)
        cached = publications.read_cache(key, self.settings)
        self.assertEqual(cached["author"]["author_id"], "7004212771")

    def test_an_expired_entry_is_a_miss(self) -> None:
        key = publications.cache_key("Martin Otis", 10)
        publications.write_cache(key, PAYLOAD, self.settings)
        self.assertIsNone(publications.read_cache(key, self.settings, now=1e12))

    def test_the_key_is_stable_and_case_insensitive_on_the_name(self) -> None:
        self.assertEqual(publications.cache_key("Martin Otis", 10),
                         publications.cache_key("  martin otis ", 10))

    def test_a_different_count_is_a_different_key(self) -> None:
        self.assertNotEqual(publications.cache_key("Martin Otis", 10),
                            publications.cache_key("Martin Otis", 25))

    def test_the_cache_file_name_leaks_no_author_name(self) -> None:
        key = publications.cache_key("Martin Otis", 10)
        publications.write_cache(key, PAYLOAD, self.settings)
        names = os.listdir(self.settings.publications_cache_dir)
        self.assertTrue(names)
        self.assertNotIn("otis", " ".join(names).lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python deploy/form-service/tests/test_publications.py`
Expected: FAIL with `ImportError: cannot import name 'publications' from 'app'`.

- [ ] **Step 3: Extend the settings**

In `deploy/form-service/app/config.py`, add three fields to `Settings`:

```python
    publications_cache_dir: str
    publications_ttl_s: int
    publications_rate_per_minute: int
```

and three lines to the `Settings(...)` construction in `load_settings`:

```python
        publications_cache_dir=env.get("FORM_SERVICE_PUBLICATIONS_CACHE_DIR",
                                       "/data/publications"),
        publications_ttl_s=int(env.get("FORM_SERVICE_PUBLICATIONS_TTL_S", 86400)),
        publications_rate_per_minute=int(
            env.get("FORM_SERVICE_PUBLICATIONS_RATE_PER_MINUTE", 20)),
```

- [ ] **Step 4: Write the minimal implementation**

Create `deploy/form-service/app/publications.py`:

```python
"""
publications.py - Cached, rate-limited access to one author's Scopus
publications.

ThesisTracker never calls Elsevier. The key, the throttling, and the
approved-publisher policy stay here; a caller sees plain JSON with a per-entry
approved_publisher flag.

The cache is on disk and keyed by a hash, so a cache directory listing does not
reveal which people were looked up.
"""

import hashlib
import json
import logging
import os
import time
from typing import Any, Callable

from .config import Settings
from .skill_bridge import _DEFAULT_SCRIPTS  # noqa: F401  (ensures sys.path is set)

import scopus_api  # noqa: E402

logger = logging.getLogger(__name__)


class TokenBucket:
    """
    A minimal token bucket. Sized for the Elsevier quota rather than for load:
    the point is to never hammer Scopus from a report that iterates a roster.
    """

    def __init__(self, capacity: int, refill_per_minute: int,
                 now: Callable[[], float] = time.monotonic) -> None:
        self.capacity = capacity
        self.refill_per_minute = refill_per_minute
        self._now = now
        self._tokens = float(capacity)
        self._last = now()

    def take(self) -> bool:
        """
        ----------------------------------------------------------------------
        Purpose:
            Consume one token, refilling first for the elapsed time.

        Inputs:
            none

        Outputs:
            allowed (bool): True when a token was available
        ----------------------------------------------------------------------
        """
        current = self._now()
        elapsed = max(0.0, current - self._last)
        self._last = current
        self._tokens = min(float(self.capacity),
                           self._tokens + elapsed * (self.refill_per_minute / 60.0))
        if self._tokens < 1.0:
            return False
        self._tokens -= 1.0
        return True


def cache_key(author: str, count: int) -> str:
    """
    --------------------------------------------------------------------------
    Purpose:
        Build a stable cache key for one query. The author name is trimmed and
        lowercased so trivial spelling variants share an entry, and the digest
        keeps the name out of the file system.

    Inputs:
        author (str): the queried author name
        count (int): how many documents were requested

    Outputs:
        key (str): SHA-256 hexadecimal digest
    --------------------------------------------------------------------------
    """
    normalized = f"{' '.join(author.lower().split())}|{count}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _cache_path(key: str, settings: Settings) -> str:
    return os.path.join(settings.publications_cache_dir, f"{key}.json")


def read_cache(key: str, settings: Settings, now: float | None = None) -> dict[str, Any] | None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return a cached payload when one exists and is younger than the TTL.

    Inputs:
        key (str): cache key
        settings (Settings): service configuration
        now (float | None): epoch seconds, injected by the tests

    Outputs:
        payload (dict | None): the cached document, or None on miss or expiry
    --------------------------------------------------------------------------
    """
    path = _cache_path(key, settings)
    if not os.path.isfile(path):
        return None
    age = (time.time() if now is None else now) - os.path.getmtime(path)
    if age > settings.publications_ttl_s:
        logger.info("[FORM-SERVICE] publications cache entry expired")
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def write_cache(key: str, payload: dict[str, Any], settings: Settings) -> None:
    """
    --------------------------------------------------------------------------
    Purpose:
        Persist a payload for later reuse.

    Inputs:
        key (str): cache key
        payload (dict): the document to store
        settings (Settings): service configuration

    Outputs:
        none
    --------------------------------------------------------------------------
    """
    os.makedirs(settings.publications_cache_dir, exist_ok=True)
    with open(_cache_path(key, settings), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python deploy/form-service/tests/test_publications.py`
Expected: PASS, 9 tests.

- [ ] **Step 6: Commit**

```bash
git add deploy/form-service/app/publications.py deploy/form-service/app/config.py \
        deploy/form-service/tests/test_publications.py
git commit -m "feat(form-service): publications cache and token-bucket rate limiter"
```

---

## Task 3: The endpoint

**Files:**

- Modify: `deploy/form-service/app/publications.py`
- Modify: `deploy/form-service/app/main.py`
- Test: `deploy/form-service/tests/test_publications.py`

**Interfaces:**

- Consumes: Tasks 1 and 2, plus `require_service_key` and `load_settings` from RT-5.
- Produces the HTTP contract **TT-6 codes against**:

| Method and path | Query | Success | Failure |
|---|---|---|---|
| `GET /publications` | `author` (required), `count` (default 10, max 50), `refresh` (default false) | `200 {"query", "author": {...}, "publications": [...], "fetched_at", "cached": bool}` | `422` no author, `429` rate limited, `503` Scopus unreachable or no key, `404` author not found in Scopus |

- `fetch_publications(author: str, count: int, refresh: bool, settings: Settings, bucket: TokenBucket, fetcher: Callable[..., dict] | None = None) -> tuple[dict, bool]` returning `(payload, cached)`. `fetcher` defaults to `scopus_api.author_documents` and is injected by the tests.

- [ ] **Step 1: Write the failing test**

Append to `deploy/form-service/tests/test_publications.py`, above the `if __name__` block:

```python
class TestFetchPublications(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = config.load_settings({
            "FORM_SERVICE_KEY": VALID_KEY,
            "FORM_SERVICE_PUBLICATIONS_CACHE_DIR": os.path.join(self.tmp.name, "pub"),
        })
        self.calls: list = []

        def fetcher(name, count=10, **kwargs):
            self.calls.append((name, count))
            return PAYLOAD
        self.fetcher = fetcher
        self.bucket = publications.TokenBucket(capacity=5, refill_per_minute=60)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_the_first_call_hits_scopus_and_the_second_hits_the_cache(self) -> None:
        first, cached = publications.fetch_publications(
            "Martin Otis", 10, False, self.settings, self.bucket, fetcher=self.fetcher)
        self.assertFalse(cached)
        second, cached = publications.fetch_publications(
            "Martin Otis", 10, False, self.settings, self.bucket, fetcher=self.fetcher)
        self.assertTrue(cached)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(first["author"], second["author"])

    def test_refresh_bypasses_the_cache(self) -> None:
        publications.fetch_publications("Martin Otis", 10, False, self.settings,
                                        self.bucket, fetcher=self.fetcher)
        publications.fetch_publications("Martin Otis", 10, True, self.settings,
                                        self.bucket, fetcher=self.fetcher)
        self.assertEqual(len(self.calls), 2)

    def test_a_cache_hit_does_not_consume_a_token(self) -> None:
        bucket = publications.TokenBucket(capacity=1, refill_per_minute=0)
        publications.fetch_publications("Martin Otis", 10, False, self.settings,
                                        bucket, fetcher=self.fetcher)
        # The bucket is empty now; a cache hit must still succeed.
        payload, cached = publications.fetch_publications(
            "Martin Otis", 10, False, self.settings, bucket, fetcher=self.fetcher)
        self.assertTrue(cached)
        self.assertEqual(payload["query"], "Martin Otis")

    def test_an_exhausted_bucket_raises_rate_limited_on_a_miss(self) -> None:
        bucket = publications.TokenBucket(capacity=1, refill_per_minute=0)
        publications.fetch_publications("Martin Otis", 10, False, self.settings,
                                        bucket, fetcher=self.fetcher)
        with self.assertRaises(publications.RateLimited):
            publications.fetch_publications("Quelqu un Dautre", 10, False,
                                            self.settings, bucket, fetcher=self.fetcher)


class TestPublicationsRoute(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["FORM_SERVICE_KEY"] = VALID_KEY
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["FORM_SERVICE_PUBLICATIONS_CACHE_DIR"] = os.path.join(self.tmp.name, "pub")

        from fastapi.testclient import TestClient
        from app import main

        self.main = main
        self.client = TestClient(main.app)
        self.headers = {"X-Form-Service-Key": VALID_KEY}
        self._real = publications.fetch_publications
        publications.fetch_publications = lambda author, count, refresh, settings, bucket, **kw: (
            PAYLOAD, False)

    def tearDown(self) -> None:
        publications.fetch_publications = self._real
        self.tmp.cleanup()

    def test_it_requires_the_service_key(self) -> None:
        self.assertEqual(self.client.get("/publications?author=Otis").status_code, 401)

    def test_it_returns_the_publications_with_the_cached_flag(self) -> None:
        response = self.client.get("/publications?author=Martin%20Otis", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["cached"])
        self.assertEqual(body["publications"][0]["doi"], "10.1109/TRO.2025.000001")
        self.assertTrue(body["publications"][0]["approved_publisher"])

    def test_a_missing_author_is_422(self) -> None:
        self.assertEqual(self.client.get("/publications", headers=self.headers).status_code, 422)

    def test_a_count_above_the_cap_is_422(self) -> None:
        response = self.client.get("/publications?author=Otis&count=500", headers=self.headers)
        self.assertEqual(response.status_code, 422)

    def test_rate_limiting_maps_to_429(self) -> None:
        def limited(*args, **kwargs):
            raise publications.RateLimited("too many Scopus queries, retry shortly")
        publications.fetch_publications = limited
        response = self.client.get("/publications?author=Otis", headers=self.headers)
        self.assertEqual(response.status_code, 429)

    def test_an_unresolvable_author_maps_to_404(self) -> None:
        def missing(*args, **kwargs):
            raise ValueError("no Scopus author found for 'Personne'")
        publications.fetch_publications = missing
        response = self.client.get("/publications?author=Personne", headers=self.headers)
        self.assertEqual(response.status_code, 404)

    def test_an_unreachable_scopus_maps_to_503_not_to_an_empty_list(self) -> None:
        def unreachable(*args, **kwargs):
            raise publications.ScopusUnavailable("SCOPUS_API_KEY is not set")
        publications.fetch_publications = unreachable
        response = self.client.get("/publications?author=Otis", headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertIn("SCOPUS_API_KEY", response.json()["detail"])

    def test_the_scopus_key_never_appears_in_a_response(self) -> None:
        os.environ["SCOPUS_API_KEY"] = "super-secret-key"
        try:
            response = self.client.get("/publications?author=Otis", headers=self.headers)
            self.assertNotIn("super-secret-key", response.text)
        finally:
            os.environ.pop("SCOPUS_API_KEY", None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python deploy/form-service/tests/test_publications.py`
Expected: FAIL with `AttributeError: module 'app.publications' has no attribute 'RateLimited'`.

- [ ] **Step 3: Write the minimal implementation**

Append to `deploy/form-service/app/publications.py`:

```python
class RateLimited(RuntimeError):
    """Raised when the Scopus token bucket is empty."""


class ScopusUnavailable(RuntimeError):
    """Raised when Scopus cannot be reached or no key is configured."""


def fetch_publications(author: str, count: int, refresh: bool, settings: Settings,
                       bucket: TokenBucket,
                       fetcher: Callable[..., dict[str, Any]] | None = None
                       ) -> tuple[dict[str, Any], bool]:
    """
    --------------------------------------------------------------------------
    Purpose:
        Return one author's publications, from cache when possible. A cache hit
        costs no Scopus quota, so a cohort report over a roster of already seen
        students makes no network call at all.

    Inputs:
        author (str): the author name
        count (int): how many documents
        refresh (bool): bypass the cache
        settings (Settings): service configuration
        bucket (TokenBucket): the shared rate limiter
        fetcher (callable | None): injected for tests; defaults to
            scopus_api.author_documents

    Outputs:
        result (tuple): (payload, cached)

    Raises:
        RateLimited when the bucket is empty on a cache miss.
        ScopusUnavailable when no key is configured or Scopus is unreachable.
        ValueError when the author cannot be resolved.
    --------------------------------------------------------------------------
    """
    key = cache_key(author, count)
    if not refresh:
        cached = read_cache(key, settings)
        if cached is not None:
            return cached, True

    if not bucket.take():
        raise RateLimited(
            "the Scopus rate limit for this service is exhausted, retry shortly")

    call = fetcher or scopus_api.author_documents
    try:
        payload = call(author, count=count)
    except ValueError:
        raise
    except Exception as exc:  # network, key, quota: one actionable class
        # The message is safe to surface: _get_api_key never echoes the key.
        raise ScopusUnavailable(str(exc)) from exc

    write_cache(key, payload, settings)
    return payload, False
```

- [ ] **Step 4: Add the route**

In `deploy/form-service/app/main.py`, add the import and the shared bucket near the top:

```python
from . import publications

# One bucket per process, sized from the configuration. Scopus quota is a
# property of the key, not of the caller, so the limiter is shared.
_PUBLICATIONS_BUCKET = publications.TokenBucket(
    capacity=load_settings().publications_rate_per_minute,
    refill_per_minute=load_settings().publications_rate_per_minute)
```

and the route at the end of the file:

```python
@app.get("/publications", dependencies=[Depends(require_service_key)])
async def author_publications(author: str, count: int = 10,
                              refresh: bool = False) -> dict[str, Any]:
    """One author's Scopus publications, cached and rate limited."""
    if not author.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="author is required")
    if count < 1 or count > 50:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="count must be between 1 and 50")
    settings = load_settings()
    try:
        payload, cached = publications.fetch_publications(
            author, count, refresh, settings, _PUBLICATIONS_BUCKET)
    except publications.RateLimited as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    except publications.ScopusUnavailable as exc:
        # 503, never an empty list: an empty list reads as "no publications".
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return {**payload, "cached": cached}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python deploy/form-service/tests/test_publications.py`
Expected: PASS, 21 tests.

- [ ] **Step 6: Verify against the real Scopus (campus network or VPN)**

```powershell
$env:SCOPUS_API_KEY = "<your key>"
python .claude/skills/scopus/scripts/scopus_api.py publications "Martin Otis" --count 5
curl -s -H "X-Form-Service-Key: $env:FORM_SERVICE_KEY" `
  "http://127.0.0.1:8081/publications?author=Martin%20Otis&count=5"
curl -s -H "X-Form-Service-Key: $env:FORM_SERVICE_KEY" `
  "http://127.0.0.1:8081/publications?author=Martin%20Otis&count=5"
```

Expected: the CLI prints five records, each with its own DOI and an
`approved_publisher` flag; the first HTTP call returns `"cached": false` and the
second `"cached": true`. Confirm by eye that every DOI resolves and that no
record was invented.

- [ ] **Step 7: Update the documentation**

1. `deploy/form-service/README.md`, endpoint table, add:

```markdown
| `GET /publications` | query `author`, `count` (max 50), `refresh` | `{"query", "author", "publications", "fetched_at", "cached"}` |
```

plus a sentence: the Scopus key, the throttling, and the approved-publisher
policy live in ResearchTools; a caller never reaches Elsevier and never sees the
key. An unreachable Scopus is `503`, never an empty list.

2. `deploy/.env.example`, add:

```
# Publications endpoint (RT-6). The Scopus key itself is read by the skill from
# SCOPUS_API_KEY or .claude/skills/scopus/.scopus_key and is never stored here.
FORM_SERVICE_PUBLICATIONS_TTL_S=86400
FORM_SERVICE_PUBLICATIONS_RATE_PER_MINUTE=20
SCOPUS_API_KEY=
```

3. `.claude/skills/scopus/SKILL.md`: add the `publications` mode next to the six existing ones.

4. `README.md` and `Architecture.md`: `scopus_api.py` now offers seven modes, `search cite validate verify author journal publications`. Update the mode list in the Architecture script table (the `scopus_api.py` row) and anywhere the six modes are enumerated.

5. `.claude/rules/testing.md`, add:

```powershell
python .claude/skills/scopus/scripts/Test/test_author_documents.py   # author resolution, DOI fidelity, approved-publisher flag
python deploy/form-service/tests/test_publications.py                # cache, token bucket, route status mapping
```

- [ ] **Step 8: Regenerate the mirrors and run the full offline suite**

```powershell
.\install.ps1 -Profile engineering
python deploy/form-service/tests/test_publications.py
python deploy/form-service/tests/test_api.py
python .claude/skills/scopus/scripts/Test/test_author_documents.py
python .claude/skills/uqac-forms/scripts/Test/test_sign_form.py
python .claude/skills/uqac-forms/scripts/Test/test_fill_form.py
python .claude/skills/uqac-forms/scripts/Test/test_field_map.py
python .claude/skills/uqac-forms/scripts/Test/test_form_registry.py
python .claude/skills/scopus/scripts/Test/test_download_pdf.py
python .claude/skills/scopus/scripts/Test/test_browser_fetch.py
python .claude/skills/scopus/scripts/Test/test_bib_batch.py
python .claude/skills/scopus/scripts/Test/test_litreview_update.py
python .claude/skills/extract-statistic/scripts/Test/test_section_scan.py
```

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add deploy .claude README.md Architecture.md .github .opencode .continue
git commit -m "feat(form-service): cached, rate-limited publications endpoint"
```

---

## Interfaces published by RT-6

**HTTP, consumed by TT-6:**

`GET /publications?author=<name>&count=<1..50>&refresh=<bool>` with `X-Form-Service-Key`, returning

```json
{
  "query": "Martin Otis",
  "author": {"author_id": "...", "name": "...", "affiliation": "...", "h_index": "...", "documents": "..."},
  "publications": [
    {"title": "...", "venue": "...", "year": "2025", "doi": "10.1109/...",
     "doi_url": "https://doi.org/10.1109/...", "type": "Article",
     "citations": "7", "approved_publisher": true}
  ],
  "fetched_at": "2026-07-29T12:00:00+00:00",
  "cached": false
}
```

Status codes: `401` no or wrong key, `404` author not found in Scopus, `422` missing author or count out of range, `429` rate limited, `503` Scopus unreachable or unconfigured.

**Python:** `scopus_api.author_documents(name, count=10, api_key=None, insttoken=None, author_id=None) -> dict`, `scopus_api.is_approved_publisher(venue) -> bool`, `scopus_api.APPROVED_PUBLISHERS`.

---

## Acceptance

```powershell
python .claude/skills/scopus/scripts/Test/test_author_documents.py
python deploy/form-service/tests/test_publications.py
python .claude/skills/scopus/scripts/scopus_api.py publications "Martin Otis" --count 5   # campus network or VPN
pip-audit -r deploy/form-service/requirements.txt --strict
.\install.ps1 -Profile engineering
```

Plus the RT-1 through RT-5 suites and the five existing offline suites in `.claude/rules/testing.md`, which must stay green.
