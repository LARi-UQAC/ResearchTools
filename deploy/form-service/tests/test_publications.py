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

    def test_a_scopus_failure_maps_to_scopus_unavailable_not_a_crash(self) -> None:
        def failing(name, count=10, **kwargs):
            raise RuntimeError("document search for AU-ID(1) failed (503): ...")
        with self.assertRaises(publications.ScopusUnavailable):
            publications.fetch_publications("Martin Otis", 10, False, self.settings,
                                            self.bucket, fetcher=failing)


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
        os.environ.pop("FORM_SERVICE_PUBLICATIONS_CACHE_DIR", None)
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

    def test_a_count_above_the_scopus_page_cap_is_422(self) -> None:
        # 25, not 50: Scopus's STANDARD view refuses a page above 25 with HTTP
        # 400 (measured, see _SEARCH_PAGE in scopus_api.py). A caller allowed to
        # ask for 26-50 would 400 against the real API.
        response = self.client.get("/publications?author=Otis&count=26", headers=self.headers)
        self.assertEqual(response.status_code, 422)

    def test_a_count_of_25_is_accepted(self) -> None:
        response = self.client.get("/publications?author=Otis&count=25", headers=self.headers)
        self.assertEqual(response.status_code, 200)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
