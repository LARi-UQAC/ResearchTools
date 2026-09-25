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

    def test_a_lastname_comma_firstname_query_resolves_correctly(self) -> None:
        # _split_author_name's own reason for existing: "Otis, Martin" must not
        # be read as surname="Martin". This proves author_documents reuses it
        # rather than a naive name.split().
        scopus_api.author_documents("Otis, Martin", count=10, api_key="fake")
        _url, params = self.calls[0]
        self.assertIn("AUTHLASTNAME(Otis)", params["query"])

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

    def test_a_non_200_response_raises_rather_than_exiting_the_process(self) -> None:
        # Measured defect: _check_response() calls sys.exit(1) on a non-200
        # response, which is correct for the CLI but fatal for a request
        # handled inside a long-lived service process. author_documents must
        # never let that escape: a Scopus outage is a caught exception, not a
        # dead worker.
        scopus_api.requests.get = lambda url, **kwargs: _FakeResponse(
            {"service-error": "quota exceeded"}, status=429)
        with self.assertRaises(Exception) as ctx:
            scopus_api.author_documents("Martin Otis", api_key="fake", author_id="7004212771")
        self.assertNotIsInstance(ctx.exception, SystemExit)

    def test_an_unlicensed_author_search_api_names_the_workaround(self) -> None:
        # Measured 2026-08-12 on _author: a key valid for Scopus Search but not
        # for the Author Search API answers 401/403 AUTHORIZATION_ERROR. The
        # caller's fix is to pass author_id directly, so the message must say so
        # rather than reading as an invalid key.
        scopus_api.requests.get = lambda url, **kwargs: _FakeResponse(
            {"service-error": {"status": {"statusCode": "AUTHORIZATION_ERROR"}}}, status=401)
        with self.assertRaises(Exception) as ctx:
            scopus_api.author_documents("Martin Otis", api_key="fake")
        self.assertIn("author_id", str(ctx.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
